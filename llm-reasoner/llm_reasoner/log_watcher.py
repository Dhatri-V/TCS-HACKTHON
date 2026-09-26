"""Watch structured Docker logs and drive the existing incident pipeline.

This is a local process supervisor, not an LLM tool. It accepts only JSON log
records through log_ingestion, publishes the shared incident contract to the
existing backend, and starts the existing LangGraph investigation. RAG remains
an optional adapter owned elsewhere.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Callable

from .bridge import fetch_incident, run_incident_investigation
from .delivery_outbox import DeliveryOutbox
from .log_ingestion import IngestionError, incident_from_line, publish_incident


PERMANENT_DELIVERY_ERRORS = {'delivery_rejected', 'incident_conflict'}


def _publish_with_retry(incident: dict, api_base: str, publisher: Callable,
                        attempts: int, delay_seconds: float, sleeper: Callable) -> str:
    if attempts < 1:
        raise ValueError('invalid_delivery_attempts')
    for attempt in range(attempts):
        try:
            return publisher(incident, api_base)
        except IngestionError as error:
            if str(error) != 'delivery_failed' or attempt + 1 == attempts:
                raise
            sleeper(delay_seconds * (2 ** attempt))
    raise AssertionError('unreachable')


def process_incident(
    incident: dict,
    *,
    api_base: str,
    publisher: Callable = publish_incident,
    incident_fetcher: Callable = fetch_incident,
    investigator: Callable = run_incident_investigation,
    outbox: DeliveryOutbox | None = None,
    delivery_attempts: int = 3,
    retry_delay: float = 1.0,
    sleeper: Callable = time.sleep,
) -> dict:
    """Persist and diagnose one already-sanitized incident exactly once."""
    active_outbox = outbox or DeliveryOutbox()
    try:
        delivery = _publish_with_retry(incident, api_base, publisher,
                                       delivery_attempts, retry_delay, sleeper)
    except IngestionError as error:
        if str(error) == 'delivery_failed':
            active_outbox.enqueue(incident)
            raise IngestionError('delivery_queued') from None
        raise
    stored = incident_fetcher(incident['incident_id'], api_base=api_base)
    investigated = False
    if stored.get('status') == 'INVESTIGATING' and stored.get('analysis') is None:
        outcome = investigator(incident['incident_id'], api_base=api_base)
        if outcome.final_status != 'DIAGNOSED':
            raise RuntimeError('investigation_not_diagnosed')
        investigated = True
    active_outbox.discard(incident['incident_id'])
    return {
        'status': 'diagnosed' if investigated else 'already_processed',
        'incident_id': incident['incident_id'],
        'delivery': delivery,
    }


def process_log_line(
    raw_line: str,
    *,
    api_base: str,
    demo: bool = False,
    publisher: Callable = publish_incident,
    incident_fetcher: Callable = fetch_incident,
    investigator: Callable = run_incident_investigation,
    outbox: DeliveryOutbox | None = None,
    delivery_attempts: int = 3,
    retry_delay: float = 1.0,
    sleeper: Callable = time.sleep,
) -> dict:
    """Classify one line, persist an incident, and diagnose it exactly once."""
    incident = incident_from_line(raw_line, demo=demo)
    if incident is None:
        return {'status': 'ignored'}
    return process_incident(
        incident, api_base=api_base, publisher=publisher,
        incident_fetcher=incident_fetcher, investigator=investigator,
        outbox=outbox, delivery_attempts=delivery_attempts,
        retry_delay=retry_delay, sleeper=sleeper,
    )


def watch_docker_logs(
    *,
    compose_file: str,
    service: str,
    api_base: str,
    demo: bool = False,
    once: bool = False,
    popen: Callable = subprocess.Popen,
    processor: Callable = process_log_line,
    pending_processor: Callable = process_incident,
    outbox: DeliveryOutbox | None = None,
) -> int:
    """Follow new Docker Compose log records until interrupted or one succeeds."""
    compose_path = Path(compose_file).resolve()
    if not compose_path.is_file():
        raise ValueError('compose_file_not_found')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', service):
        raise ValueError('invalid_service')
    # Capture the stream watermark before replay so records emitted while a
    # slow backend/outbox replay is running are still included by Docker.
    since = datetime.now(timezone.utc).isoformat(timespec='microseconds')
    active_outbox = outbox or DeliveryOutbox()
    diagnosed = 0
    pending, invalid = active_outbox.read_pending()
    if invalid:
        print(json.dumps({'watcher': 'outbox_invalid', 'count': invalid}), file=sys.stderr)
    for incident in pending:
        try:
            result = pending_processor(incident, api_base=api_base, outbox=active_outbox)
            if result['status'] in {'diagnosed', 'already_processed'}:
                active_outbox.discard(incident['incident_id'])
                diagnosed += 1
                print(json.dumps({'watcher': 'outbox_replayed', **result}), flush=True)
        except IngestionError as error:
            code = str(error)
            if code in PERMANENT_DELIVERY_ERRORS:
                active_outbox.discard(incident['incident_id'])
                print(json.dumps({'watcher': 'outbox_discarded',
                                  'incident_id': incident['incident_id'],
                                  'code': code}), file=sys.stderr)
            else:
                print(json.dumps({'watcher': 'outbox_replay_failed',
                                  'incident_id': incident['incident_id'],
                                  'code': code}), file=sys.stderr)
        except Exception:
            print(json.dumps({'watcher': 'outbox_replay_failed',
                              'incident_id': incident['incident_id']}), file=sys.stderr)
    if once and diagnosed:
        return diagnosed
    command = ['docker', 'compose', '-f', str(compose_path), 'logs', '--follow',
               '--no-log-prefix', '--since', since, service]
    process = popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, bufsize=1)
    print(json.dumps({'watcher': 'ready', 'service': service}), flush=True)
    try:
        for line in process.stdout:
            if not line.strip():
                continue
            try:
                result = processor(line, api_base=api_base, demo=demo,
                                   outbox=active_outbox)
            except IngestionError as error:
                # Docker may emit non-application lines. Report stable codes only.
                print(json.dumps({'watcher': 'ignored', 'code': str(error)}), file=sys.stderr)
                continue
            except Exception:
                print(json.dumps({'watcher': 'pipeline_failed'}), file=sys.stderr)
                if once:
                    process.terminate()
                    break
                continue
            if result['status'] in {'diagnosed', 'already_processed'}:
                diagnosed += 1
                print(json.dumps(result), flush=True)
                if once:
                    process.terminate()
                    break
    except KeyboardInterrupt:
        process.terminate()
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            returncode = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            returncode = -1
    if not once and returncode:
        raise RuntimeError('docker_log_stream_failed')
    return diagnosed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compose-file', required=True)
    parser.add_argument('--service', default='orders-api')
    parser.add_argument('--api-base', default=os.getenv('INCIDENT_API_BASE', 'http://localhost:3000'))
    parser.add_argument('--demo', action='store_true',
                        help='Map the exact orders-api PostgreSQL error to INC-DEMO-001.')
    parser.add_argument('--once', action='store_true',
                        help='Exit after the first incident is persisted and diagnosed.')
    args = parser.parse_args()
    try:
        count = watch_docker_logs(compose_file=args.compose_file, service=args.service,
                                  api_base=args.api_base, demo=args.demo, once=args.once)
        return 0 if count or not args.once else 1
    except Exception:
        print(json.dumps({'watcher': 'failed'}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
