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
import stat
import tempfile

from .log_ingestion import IngestionError


FIELDS = {
    'incident_id', 'timestamp', 'service', 'log_level', 'message',
    'classification', 'status', 'analysis',
}


def _secure_owner_directory(path: Path, *, parents: bool = False) -> None:
    """Create/verify an owner-only real directory, or fail closed."""
    getuid = getattr(os, 'getuid', None)
    if getuid is None:
        raise IngestionError('unsafe_outbox_directory')
    try:
        path.mkdir(mode=0o700, parents=parents, exist_ok=True)
        before = path.lstat()
        if not stat.S_ISDIR(before.st_mode) or stat.S_ISLNK(before.st_mode):
            raise IngestionError('unsafe_outbox_directory')
        if before.st_uid != getuid():
            raise IngestionError('unsafe_outbox_directory')
        path.chmod(0o700)
        after = path.lstat()
        if after.st_uid != getuid() or not stat.S_ISDIR(after.st_mode):
            raise IngestionError('unsafe_outbox_directory')
        if stat.S_IMODE(after.st_mode) != 0o700:
            raise IngestionError('unsafe_outbox_directory')
    except IngestionError:
        raise
    except OSError:
        raise IngestionError('unsafe_outbox_directory') from None


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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
        self._default_root = None
        if configured:
            self.directory = Path(configured)
        else:
            getuid = getattr(os, 'getuid', None)
            if getuid is None:
                raise IngestionError('unsafe_outbox_directory')
            self._default_root = (
                Path(tempfile.gettempdir()) / f'cloud-incident-copilot-{getuid()}'
            )
            self.directory = self._default_root / 'incident-outbox'

    def _ensure_directory(self) -> None:
        if self._default_root is not None:
            _secure_owner_directory(self._default_root)
            _secure_owner_directory(self.directory)
        else:
            _secure_owner_directory(self.directory, parents=True)

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
            _fsync_directory(self.directory)
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
        self._ensure_directory()
        try:
            self._path(incident_id).unlink()
        except FileNotFoundError:
            pass
        else:
            _fsync_directory(self.directory)

    def read_pending(self) -> tuple[list[dict], int]:
        self._ensure_directory()
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
