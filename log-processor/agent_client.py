"""
agent_client.py
───────────────
HTTP client responsible for sending incident data to the external Agent API.

THIS IS THE FINAL STEP IN OUR SCOPE.
We do NOT implement any AI, LLM, RAG, or Agent logic here.
We only prepare and send an HTTP POST request with the incident payload.

Failure handling:
  - Retry up to MAX_RETRIES times with exponential backoff
  - Log every attempt and failure
  - Save failed incidents to disk so they are not silently lost
  - Never crash the processor — always continue after failure
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Configuration (read from environment / .env) ────────────────────────────
AGENT_API_URL   = os.getenv("AGENT_API_URL", "http://localhost:8000/api/analyze")
AGENT_API_KEY   = os.getenv("AGENT_API_KEY", "")
MAX_RETRIES     = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY_SEC = int(os.getenv("RETRY_DELAY_SECONDS", "5"))

# Directory where failed incidents are persisted so they can be retried later
FAILED_DIR = Path(__file__).parent / "failed_incidents"


def _get_headers() -> dict:
    """Build request headers, including optional Bearer token."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if AGENT_API_KEY:
        headers["Authorization"] = f"Bearer {AGENT_API_KEY}"
    return headers


def send_incident(incident: dict) -> dict:
    """
    Send a single incident to the external Agent API.

    Retries up to MAX_RETRIES times on failure.
    Saves failed incidents to disk if all retries are exhausted.

    Parameters
    ----------
    incident : dict
        The clean incident object built by classifier._build_incident().

    Returns
    -------
    dict with shape:
        {
            "incident_id":      str,
            "delivery_status":  "SUCCESS" | "FAILED",
            "reason":           str | None,
            "attempts":         int,
            "agent_response":   dict | None
        }
    """
    incident_id = incident.get("incident_id", "UNKNOWN")
    raw_log = incident.get("raw_log", "")
    
    print(f"\n[AgentClient] 📤 Preparing to send Error Log / Incident Payload:")
    print(f"[AgentClient] Incident ID : {incident_id}")
    print(f"[AgentClient] Target URL  : {AGENT_API_URL}")
    if raw_log:
        print(f"[AgentClient] Raw Error Log:\n{raw_log}")
    print(f"[AgentClient] Payload JSON:\n{json.dumps(incident, indent=2)}")

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"[AgentClient] Attempt {attempt}/{MAX_RETRIES} for {incident_id}...")

            response = requests.post(
                AGENT_API_URL,
                headers=_get_headers(),
                json=incident,
                timeout=15,
            )

            if response.status_code in (200, 201, 202):
                print(f"[AgentClient] ✓ Incident {incident_id} delivered successfully "
                      f"(HTTP {response.status_code})")

                agent_resp = None
                try:
                    agent_resp = response.json()
                except Exception:
                    pass

                return {
                    "incident_id":     incident_id,
                    "delivery_status": "SUCCESS",
                    "reason":          None,
                    "attempts":        attempt,
                    "agent_response":  agent_resp,
                }
            else:
                last_error = (
                    f"Agent API returned HTTP {response.status_code}: {response.text[:200]}"
                )
                print(f"[AgentClient] ✗ {last_error}")

        except requests.exceptions.ConnectionError:
            last_error = f"Agent API unavailable — connection refused at {AGENT_API_URL}"
            print(f"[AgentClient] ✗ {last_error}")

        except requests.exceptions.Timeout:
            last_error = "Agent API request timed out after 15 seconds"
            print(f"[AgentClient] ✗ {last_error}")

        except requests.exceptions.RequestException as exc:
            last_error = f"Request error: {exc}"
            print(f"[AgentClient] ✗ {last_error}")

        # Wait before retry (skip sleep after last attempt)
        if attempt < MAX_RETRIES:
            wait = RETRY_DELAY_SEC * attempt  # simple linear backoff
            print(f"[AgentClient] Waiting {wait}s before retry…")
            time.sleep(wait)

    # ── All retries exhausted ─────────────────────────────────────────────────
    print(f"[AgentClient] ✗ All {MAX_RETRIES} attempts failed for {incident_id}. "
          f"Saving to failed_incidents/")

    _save_failed(incident, last_error, MAX_RETRIES)

    return {
        "incident_id":     incident_id,
        "delivery_status": "FAILED",
        "reason":          last_error or "Agent API unavailable",
        "attempts":        MAX_RETRIES,
        "agent_response":  None,
    }


def _save_failed(incident: dict, reason: str, attempts: int) -> None:
    """
    Persist a failed incident to disk as a JSON file.

    Files are stored in:   log-processor/failed_incidents/<incident_id>.json

    This ensures incidents are NOT silently lost when the Agent API is down.
    The file can be replayed later once the Agent comes back online.
    """
    FAILED_DIR.mkdir(parents=True, exist_ok=True)

    incident_id = incident.get("incident_id", f"UNKNOWN-{uuid.uuid4().hex[:6]}")
    filepath = FAILED_DIR / f"{incident_id}.json"

    record = {
        "incident_id":     incident_id,
        "delivery_status": "FAILED",
        "reason":          reason,
        "attempts":        attempts,
        "failed_at":       datetime.now(timezone.utc).isoformat(),
        "incident":        incident,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)

    print(f"[AgentClient] Saved failed incident to {filepath}")


def retry_failed_incidents() -> list[dict]:
    """
    Scan the failed_incidents/ directory and attempt to resend each one.

    Called on startup or on demand.

    Returns a list of delivery result dicts.
    """
    if not FAILED_DIR.exists():
        return []

    results = []
    failed_files = list(FAILED_DIR.glob("*.json"))

    if not failed_files:
        return []

    print(f"[AgentClient] Retrying {len(failed_files)} previously failed incident(s)…")

    for filepath in failed_files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                record = json.load(f)

            incident = record.get("incident", {})
            result = send_incident(incident)
            results.append(result)

            if result["delivery_status"] == "SUCCESS":
                # Remove the file on successful delivery
                filepath.unlink(missing_ok=True)
                print(f"[AgentClient] Removed resolved failed-incident file: {filepath.name}")

        except Exception as exc:
            print(f"[AgentClient] Error processing failed incident file {filepath}: {exc}")
            results.append({
                "incident_id":     filepath.stem,
                "delivery_status": "FAILED",
                "reason":          str(exc),
                "attempts":        0,
            })

    return results
