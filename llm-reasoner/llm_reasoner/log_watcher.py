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
from typing import Callable

from .bridge import fetch_incident, run_incident_investigation
from .log_ingestion import IngestionError, incident_from_line, publish_incident


def process_log_line(
    raw_line: str,
    *,
    api_base: str,
    demo: bool = False,
    publisher: Callable = publish_incident,
    incident_fetcher: Callable = fetch_incident,
    investigator: Callable = run_incident_investigation,
) -> dict:
    """Classify one line, persist an incident, and diagnose it exactly once."""
    incident = incident_from_line(raw_line, demo=demo)
    if incident is None:
        return {'status': 'ignored'}
    delivery = publisher(incident, api_base)
    stored = incident_fetcher(incident['incident_id'], api_base=api_base)
    investigated = False
    if stored.get('status') == 'INVESTIGATING' and stored.get('analysis') is None:
        outcome = investigator(incident['incident_id'], api_base=api_base)
        if outcome.final_status != 'DIAGNOSED':
            raise RuntimeError('investigation_not_diagnosed')
        investigated = True
    return {
        'status': 'diagnosed' if investigated else 'already_processed',
        'incident_id': incident['incident_id'],
        'delivery': delivery,
    }


def watch_docker_logs(
    *,
    compose_file: str,
    service: str,
    api_base: str,
    demo: bool = False,
    once: bool = False,
    popen: Callable = subprocess.Popen,
    processor: Callable = process_log_line,
) -> int:
    """Follow new Docker Compose log records until interrupted or one succeeds."""
    compose_path = Path(compose_file).resolve()
    if not compose_path.is_file():
        raise ValueError('compose_file_not_found')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', service):
        raise ValueError('invalid_service')
    since = datetime.now(timezone.utc).isoformat(timespec='microseconds')
    command = ['docker', 'compose', '-f', str(compose_path), 'logs', '--follow',
               '--no-log-prefix', '--since', since, service]
    process = popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, bufsize=1)
    print(json.dumps({'watcher': 'ready', 'service': service}), flush=True)
    diagnosed = 0
    try:
        for line in process.stdout:
            if not line.strip():
                continue
            try:
                result = processor(line, api_base=api_base, demo=demo)
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
