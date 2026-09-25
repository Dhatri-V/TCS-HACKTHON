"""
classifier.py
─────────────
Rule-based log classifier.

Classification rules (no LLM / AI):

  level=INFO     → INFO     (not an incident)
  level=DEBUG    → INFO     (not an incident)
  level=WARNING  → WARNING  (recorded, not sent to Agent)
  level=ERROR    → ERROR    (incident — send to Agent)
  level=CRITICAL → CRITICAL (incident — send to Agent)

Returns a classification result dict.
"""

import os
import uuid
import json
from datetime import datetime, timezone


# ── Levels that require an incident to be created and forwarded ──────────────
INCIDENT_LEVELS = {"ERROR", "CRITICAL"}

# ── Levels that are recorded but NOT forwarded ───────────────────────────────
WARNING_LEVELS  = {"WARNING", "WARN"}

# ── Levels that are silently ignored (no incident, no forwarding) ────────────
NORMAL_LEVELS   = {"INFO", "DEBUG"}


def classify(log_entry: dict) -> dict:
    """
    Classify a single normalised log entry.

    Parameters
    ----------
    log_entry : dict
        A normalised log dict produced by preprocess.parse_line().

    Returns
    -------
    dict with shape:
        {
            "classification": "INFO" | "WARNING" | "ERROR" | "CRITICAL",
            "is_incident":    bool,
            "incident":       dict | None   # only present when is_incident=True
        }
    """
    level = log_entry.get("level", "").upper()

    # Normalise WARN → WARNING
    if level == "WARN":
        level = "WARNING"

    # ── Rule: INFO / DEBUG → not an incident ────────────────────────────────
    if level in NORMAL_LEVELS or level == "":
        return {
            "classification": "INFO",
            "is_incident": False,
        }

    # ── Rule: WARNING → record but do NOT forward ────────────────────────────
    if level in WARNING_LEVELS:
        return {
            "classification": "WARNING",
            "is_incident": False,
        }

    # ── Rule: ERROR / CRITICAL → create incident ─────────────────────────────
    if level in INCIDENT_LEVELS:
        incident = _build_incident(log_entry, classification=level)
        return {
            "classification": level,
            "is_incident": True,
            "incident": incident,
        }

    # ── Unknown level → treat conservatively as WARNING ─────────────────────
    return {
        "classification": "WARNING",
        "is_incident": False,
        "_note": f"Unrecognised level '{level}' treated as WARNING",
    }


# ── Incident ID counter (in-memory; resets on restart) ─────────────────────
_incident_counter = 0


def _build_incident(log_entry: dict, classification: str) -> dict:
    """
    Build a clean, structured incident object from a log entry.

    The incident_id uses a monotonic counter + UUID fragment to ensure
    uniqueness even when entries arrive very close together.
    """
    global _incident_counter
    _incident_counter += 1

    incident_id = f"INC-{_incident_counter:04d}-{uuid.uuid4().hex[:6].upper()}"

    environment = os.getenv("ENVIRONMENT", "development")

    incident = {
        "incident_id":    incident_id,
        "timestamp":      log_entry.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "classification": classification,
        "service":        log_entry.get("service", "backend"),
        "method":         log_entry.get("method"),
        "endpoint":       log_entry.get("endpoint"),
        "status_code":    log_entry.get("statusCode"),
        "error_type":     log_entry.get("errorType"),
        "message":        log_entry.get("message", ""),
        "raw_log":        json.dumps(log_entry),
        "metadata": {
            "environment": environment,
        },
    }

    # Remove None values for cleanliness (optional, keeps payload small)
    incident = {k: v for k, v in incident.items() if v is not None or k in ("incident_id", "timestamp", "classification", "service", "message", "raw_log", "metadata")}

    return incident


def classify_batch(log_entries: list[dict]) -> list[dict]:
    """
    Classify a list of log entries.

    Returns a list of classification result dicts, one per entry.
    """
    return [classify(entry) for entry in log_entries]
