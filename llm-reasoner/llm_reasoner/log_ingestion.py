"""Winston-compatible JSON lines -> existing incident-platform API.

Adapted from PR #6's preprocess/classifier/client separation. No LLM, database,
web server or remediation implementation. Input must already be sanitized at
its application source; raw logs, stack traces and arbitrary metadata are never
copied or printed. Failed delivery exits nonzero so the source can be replayed.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
import sys

import requests


class IngestionError(ValueError):
    pass


def incident_from_line(line: str, *, demo: bool = False) -> dict | None:
    if len(line.encode('utf-8')) > 65536:
        raise IngestionError('log_too_large')
    try:
        entry = json.loads(line)
    except (ValueError, TypeError):
        raise IngestionError('invalid_json') from None
    if not isinstance(entry, dict):
        raise IngestionError('invalid_log')
    for key in ('timestamp', 'level', 'service', 'message'):
        if not isinstance(entry.get(key), str) or not entry[key].strip():
            raise IngestionError('missing_log_field')
    level = entry['level'].strip().upper()
    if level not in {'DEBUG', 'INFO', 'WARN', 'WARNING', 'ERROR', 'CRITICAL'}:
        raise IngestionError('unknown_level')
    stamp = entry['timestamp'].strip()
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})', stamp):
        raise IngestionError('invalid_timestamp')
    try:
        timestamp = datetime.fromisoformat(stamp.replace('Z', '+00:00')).astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    except ValueError:
        raise IngestionError('invalid_timestamp') from None
    service, message = entry['service'].strip(), entry['message'].strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', service) or len(message) > 4000:
        raise IngestionError('invalid_log_field')
    # Reject common accidental credential-bearing messages instead of storing them.
    if re.search(r'(?i)(?:[a-z][a-z0-9+.-]*://|\bbearer\s+|\b(?:password|passwd|api[_-]?key|token|secret)\s*[:=])', message):
        raise IngestionError('unsafe_log_message')
    if level not in {'ERROR', 'CRITICAL'}:
        return None
    value = dict(timestamp=timestamp, service=service, log_level=level.lower(),
                 message=message, classification=level)
    digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    incident_id = 'INC-LOG-' + digest
    if demo:
        if service != 'orders-api' or message != 'PostgreSQL connection failed' or level != 'ERROR':
            raise IngestionError('outside_demo_scope')
        incident_id = 'INC-DEMO-001'
    return dict(incident_id=incident_id, **value, status='INVESTIGATING', analysis=None)


def publish_incident(incident: dict, api_base: str = 'http://localhost:3000') -> str:
    base = api_base.rstrip('/') + '/api/incidents'
    try:
        response = requests.post(base, json=incident, timeout=10, allow_redirects=False)
        if response.status_code == 201:
            return 'created'
        if response.status_code == 409:
            existing = requests.get(base + '/' + incident['incident_id'], timeout=10, allow_redirects=False)
            if existing.status_code == 200:
                value = existing.json()
                # A retry must match the original event; never reset analysis or lifecycle.
                fields = ('incident_id', 'timestamp', 'service', 'log_level', 'message', 'classification')
                if all(value.get(k) == incident[k] for k in fields):
                    return 'already_delivered'
        raise IngestionError('delivery_failed')
    except (requests.RequestException, ValueError) as error:
        if isinstance(error, IngestionError):
            raise
        raise IngestionError('delivery_failed') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-base', default='http://localhost:3000')
    parser.add_argument('--demo', action='store_true', help='Reserve INC-DEMO-001 for one orders-api outage; refuses to overwrite an earlier event.')
    args = parser.parse_args()
    failed = False
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            incident = incident_from_line(line, demo=args.demo)
            if incident:
                print(json.dumps({'incident_id': incident['incident_id'], 'delivery': publish_incident(incident, args.api_base)}))
        except IngestionError as error:
            print(json.dumps({'error': str(error)}), file=sys.stderr)
            failed = True
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
