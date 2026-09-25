"""
main.py
───────
Entry point for the Python log-processing service.

Pipeline:
  1. Read new log lines from application.log (tail mode — no repeated processing)
  2. Preprocess (parse + validate JSON)
  3. Classify (rule-based — no AI)
  4. If INFO  → ignore
     If WARNING → print, skip
     If ERROR / CRITICAL → build incident → send to Agent API
  5. Track file offset to avoid duplicate processing
  6. On startup: retry any previously failed incidents

Run with:
  python main.py

or with the virtual environment active:
  venv\Scripts\python main.py     (Windows)
  venv/bin/python main.py         (Linux/Mac)
"""

import os
import sys
import time
import signal
import json
from pathlib import Path
from datetime import datetime, timezone

# Ensure stdout uses UTF-8 encoding on Windows to prevent UnicodeEncodeError
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from dotenv import load_dotenv

# Load .env before importing modules that read os.getenv()
load_dotenv()

from preprocess import parse_line, LogParseError
from classifier import classify
from agent_client import send_incident, retry_failed_incidents, AGENT_API_URL


# ── Configuration ─────────────────────────────────────────────────────────────
LOG_FILE_PATH    = os.getenv("LOG_FILE_PATH", "../backend/logs/application.log")
POLL_INTERVAL    = float(os.getenv("POLL_INTERVAL_SECONDS", "5"))

# Resolve path relative to this file's location if not absolute
_this_dir = Path(__file__).parent
_log_path = Path(LOG_FILE_PATH)
if not _log_path.is_absolute():
    _log_path = (_this_dir / _log_path).resolve()

LOG_FILE = _log_path

# ── Graceful shutdown flag ─────────────────────────────────────────────────────
_running = True


def _handle_shutdown(signum, frame):
    global _running
    print("\n[Main] Shutdown signal received. Stopping gracefully...")
    _running = False


signal.signal(signal.SIGINT,  _handle_shutdown)
signal.signal(signal.SIGTERM, _handle_shutdown)


# ── Statistics (in-memory; printed periodically) ──────────────────────────────
stats = {
    "total_lines":    0,
    "info":           0,
    "warnings":       0,
    "errors":         0,
    "criticals":      0,
    "incidents_sent": 0,
    "failures":       0,
    "parse_errors":   0,
}


def _print_stats():
    print(
        f"\n[Main] -- Stats --------------------------------------\n"
        f"  Lines processed : {stats['total_lines']}\n"
        f"  INFO            : {stats['info']}\n"
        f"  WARNING         : {stats['warnings']}\n"
        f"  ERROR           : {stats['errors']}\n"
        f"  CRITICAL        : {stats['criticals']}\n"
        f"  Incidents sent  : {stats['incidents_sent']}\n"
        f"  Failed sends    : {stats['failures']}\n"
        f"  Parse errors    : {stats['parse_errors']}\n"
        f"------------------------------------------------------\n"
    )


def process_line(raw_line: str) -> None:
    """
    Full pipeline for a single raw log line.

    Steps:
      1. Preprocess (parse JSON, validate, normalise)
      2. Classify (rule-based)
      3. Route based on classification
    """
    stats["total_lines"] += 1

    # Step 1 — Preprocess
    try:
        log_entry = parse_line(raw_line)
    except LogParseError as exc:
        stats["parse_errors"] += 1
        print(f"[Preprocess] Skipped line (parse error): {exc}")
        return

    level = log_entry.get("level", "")
    ts    = log_entry.get("timestamp", "")
    msg   = log_entry.get("message", "")

    # Step 2 — Classify
    result = classify(log_entry)
    classification = result["classification"]
    is_incident    = result["is_incident"]

    # Step 3 — Route
    if classification == "INFO":
        # Normal operations — just count, do NOT forward
        stats["info"] += 1
        print(f"[Classifier] INFO  | {ts} | {msg[:80]}")

    elif classification == "WARNING":
        # Record but do NOT send to Agent API
        stats["warnings"] += 1
        print(f"[Classifier] WARN  | {ts} | {msg[:80]}")

    elif classification in ("ERROR", "CRITICAL") and is_incident:
        if classification == "ERROR":
            stats["errors"] += 1
        else:
            stats["criticals"] += 1

        incident = result["incident"]

        # Print the error log clearly in terminal before sending to Agent API
        raw_log_str = incident.get("raw_log", raw_line)
        print(
            f"\n"
            f"+-----------------------------------------------------------------------------+\n"
            f"| [!] ERROR LOG DETECTED -- Incident ID: {incident['incident_id']}\n"
            f"+-----------------------------------------------------------------------------+\n"
            f"| Timestamp   : {ts}\n"
            f"| Severity    : {classification}\n"
            f"| Service     : {incident.get('service', 'N/A')}\n"
            f"| Error Type  : {incident.get('error_type', 'N/A')}\n"
            f"| Endpoint    : {incident.get('method', '')} {incident.get('endpoint', '')} [Status: {incident.get('status_code', 'N/A')}]\n"
            f"| Message     : {msg}\n"
            f"+-----------------------------------------------------------------------------+\n"
            f"| RAW ERROR LOG:\n"
            f"| {raw_log_str}\n"
            f"+-----------------------------------------------------------------------------+\n"
            f"[Processor] Forwarding error log & incident payload to Agent API ({AGENT_API_URL})...\n"
        )

        # Step 4 — Send incident to Agent API
        delivery = send_incident(incident)

        if delivery["delivery_status"] == "SUCCESS":
            stats["incidents_sent"] += 1
            print(f"[AgentClient] [OK] {incident['incident_id']} delivered in {delivery['attempts']} attempt(s)")
        else:
            stats["failures"] += 1
            print(f"[AgentClient] [FAIL] {incident['incident_id']} FAILED: {delivery['reason']}")


def tail_log_file() -> None:
    """
    Watch the log file for new lines, processing only new content.

    Tracks the file offset so we never reprocess old lines.
    If the file is rotated (new file created), we detect this via inode change
    and reset the offset.
    """
    print(f"[Main] Watching log file: {LOG_FILE}")
    print(f"[Main] Poll interval: {POLL_INTERVAL}s")
    print(f"[Main] Starting log tail...\n")

    offset = 0
    last_inode = None

    # If the file already exists, start from the end (don't reprocess history)
    if LOG_FILE.exists():
        offset = LOG_FILE.stat().st_size
        last_inode = LOG_FILE.stat().st_ino
        print(f"[Main] Log file exists. Starting from offset {offset} (end of existing content).")
    else:
        print(f"[Main] Log file not found yet at {LOG_FILE}. Will start watching when it appears...")

    stats_print_interval = 60  # print stats every N seconds
    last_stats_print = time.time()

    while _running:
        try:
            if not LOG_FILE.exists():
                time.sleep(POLL_INTERVAL)
                continue

            current_stat = LOG_FILE.stat()
            current_inode = current_stat.st_ino

            # Detect file rotation (inode changed)
            if last_inode is not None and current_inode != last_inode:
                print("[Main] Log file rotated. Resetting offset to 0.")
                offset = 0

            last_inode = current_inode
            current_size = current_stat.st_size

            # New data available
            if current_size > offset:
                with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(offset)
                    new_content = f.read()
                    offset = f.tell()

                # Split into lines and process each
                lines = new_content.splitlines()
                for line in lines:
                    if line.strip():
                        process_line(line)

            # File was truncated (e.g. log rotation without inode change)
            elif current_size < offset:
                print("[Main] Log file truncated. Resetting offset to 0.")
                offset = 0

        except PermissionError as exc:
            print(f"[Main] Permission error reading log file: {exc}. Retrying...")

        except Exception as exc:
            print(f"[Main] Unexpected error in tail loop: {exc}")

        # Print stats periodically
        if time.time() - last_stats_print >= stats_print_interval:
            _print_stats()
            last_stats_print = time.time()

        time.sleep(POLL_INTERVAL)

    # Final stats on exit
    _print_stats()
    print("[Main] Log processor stopped.")


def main():
    print("=" * 60)
    print("  TCS Cloud Incident Monitor -- Log Processor")
    print("=" * 60)
    print(f"  Started at : {datetime.now(timezone.utc).isoformat()}")
    print(f"  Log file   : {LOG_FILE}")
    print(f"  Agent API  : {os.getenv('AGENT_API_URL', 'not set')}")
    print("=" * 60)
    print()

    # Retry any incidents that failed to send in a previous run
    retry_failed_incidents()

    # Start watching the log file
    tail_log_file()


if __name__ == "__main__":
    main()
