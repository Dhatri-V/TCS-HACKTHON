"""Small durable outbox for sanitized watcher incidents.

Adapted from PR #6's failed-incident retry idea for the existing watcher and
shared incident contract. It deliberately stores neither raw logs nor API URLs,
headers, credentials, stack traces or arbitrary metadata.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile

from .log_ingestion import IngestionError


FIELDS = {
    'incident_id', 'timestamp', 'service', 'log_level', 'message',
    'classification', 'status', 'analysis',
}


def _validated_incident(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise IngestionError('invalid_outbox_record')
    if not re.fullmatch(r'(?:INC-DEMO-001|INC-LOG-[a-f0-9]{64})', value.get('incident_id', '')):
        raise IngestionError('invalid_outbox_record')
    if value.get('status') != 'INVESTIGATING' or value.get('analysis') is not None:
        raise IngestionError('invalid_outbox_record')
    if value.get('classification') not in {'ERROR', 'CRITICAL'}:
        raise IngestionError('invalid_outbox_record')
    if value.get('log_level') != value['classification'].lower():
        raise IngestionError('invalid_outbox_record')
    for name in ('timestamp', 'service', 'message'):
        if not isinstance(value.get(name), str) or not value[name]:
            raise IngestionError('invalid_outbox_record')
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')
    if len(encoded) > 65536:
        raise IngestionError('invalid_outbox_record')
    return dict(value)


class DeliveryOutbox:
    """Atomic, permission-restricted storage for failed API deliveries."""

    def __init__(self, directory: str | Path | None = None):
        configured = directory or os.getenv('INCIDENT_OUTBOX_DIR')
        self.directory = Path(configured) if configured else (
            Path(tempfile.gettempdir()) / 'cloud-incident-copilot' / 'incident-outbox'
        )

    def _ensure_directory(self) -> None:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            self.directory.chmod(0o700)
        except OSError:
            pass

    def _path(self, incident_id: str) -> Path:
        if not re.fullmatch(r'(?:INC-DEMO-001|INC-LOG-[a-f0-9]{64})', incident_id):
            raise IngestionError('invalid_outbox_record')
        return self.directory / f'{incident_id}.json'

    def enqueue(self, incident: dict) -> None:
        value = _validated_incident(incident)
        self._ensure_directory()
        target = self._path(value['incident_id'])
        fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=self.directory)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(value, stream, sort_keys=True, separators=(',', ':'))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                Path(temporary).unlink()
            except OSError:
                pass
            raise

    def discard(self, incident_id: str) -> None:
        try:
            self._path(incident_id).unlink()
        except FileNotFoundError:
            pass

    def read_pending(self) -> tuple[list[dict], int]:
        if not self.directory.is_dir():
            return [], 0
        records, invalid = [], 0
        for path in sorted(self.directory.glob('*.json')):
            try:
                if path.stat().st_size > 65536:
                    raise IngestionError('invalid_outbox_record')
                value = json.loads(path.read_text(encoding='utf-8'))
                value = _validated_incident(value)
                if path != self._path(value['incident_id']):
                    raise IngestionError('invalid_outbox_record')
                records.append(value)
            except (OSError, ValueError, TypeError, IngestionError):
                invalid += 1
        return records, invalid
