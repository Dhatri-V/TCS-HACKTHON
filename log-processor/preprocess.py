"""
preprocess.py
─────────────
Reads raw log lines (JSON strings) from the application.log file.
Parses, validates, and normalises them into clean Python dicts
that the classifier and incident builder can work with.

No AI / LLM logic here — purely structural validation.
"""

import json
import re
from datetime import datetime, timezone
from typing import Optional


# ── Required fields that every valid log entry must contain ─────────────────
REQUIRED_FIELDS = {"timestamp", "level", "service", "message"}

# ── Allowed log levels (normalised to uppercase for comparison) ─────────────
VALID_LEVELS = {"INFO", "WARN", "WARNING", "ERROR", "CRITICAL", "DEBUG"}


class LogParseError(Exception):
    """Raised when a log line cannot be parsed or is missing required fields."""
    pass


def parse_line(raw_line: str) -> dict:
    """
    Parse a single raw log line (expected to be a JSON string).

    Returns a normalised log dict on success.
    Raises LogParseError if the line is blank, not valid JSON,
    or is missing required fields.
    """
    line = raw_line.strip()

    # Skip blank lines
    if not line:
        raise LogParseError("Empty line")

    # Parse JSON
    try:
        entry = json.loads(line)
    except json.JSONDecodeError as exc:
        raise LogParseError(f"Invalid JSON: {exc}") from exc

    if not isinstance(entry, dict):
        raise LogParseError("Log entry is not a JSON object")

    # Validate required fields
    missing = REQUIRED_FIELDS - entry.keys()
    if missing:
        raise LogParseError(f"Missing required fields: {missing}")

    return normalise(entry)


def normalise(entry: dict) -> dict:
    """
    Normalise field values for consistent downstream processing.

    - level → uppercase string
    - timestamp → ISO-8601 string (keep as-is; validate format)
    - statusCode → int or None
    - All string fields stripped of whitespace
    """
    normalised = dict(entry)  # shallow copy; we own this dict

    # Normalise log level
    level_raw = str(normalised.get("level", "")).strip().upper()
    # Winston uses "warn"; normalise to "WARNING" for clarity
    if level_raw == "WARN":
        level_raw = "WARNING"
    normalised["level"] = level_raw

    # Warn if level is unrecognised but still process it
    if level_raw not in VALID_LEVELS:
        normalised["_unknown_level"] = True

    # Normalise string fields
    for field in ("service", "message", "method", "endpoint", "errorType"):
        if field in normalised and isinstance(normalised[field], str):
            normalised[field] = normalised[field].strip()

    # Normalise statusCode to int
    if "statusCode" in normalised:
        try:
            normalised["statusCode"] = int(normalised["statusCode"])
        except (ValueError, TypeError):
            normalised["statusCode"] = None

    # Normalise timestamp — keep the string, but verify it looks like ISO-8601
    ts = normalised.get("timestamp", "")
    if ts and not _looks_like_iso8601(ts):
        normalised["_invalid_timestamp"] = True

    return normalised


def _looks_like_iso8601(ts: str) -> bool:
    """
    Basic check: does the string look like an ISO-8601 datetime?
    Example valid forms:
      2026-09-25T10:30:21.123+05:30
      2026-09-25T10:30:21Z
    """
    pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    return bool(re.match(pattern, ts))


def parse_lines(raw_lines: list[str]) -> tuple[list[dict], list[str]]:
    """
    Process a list of raw log line strings.

    Returns:
        (valid_entries, errors)
        valid_entries — list of normalised log dicts
        errors        — list of error strings for lines that failed
    """
    valid = []
    errors = []
    for i, raw in enumerate(raw_lines, start=1):
        try:
            entry = parse_line(raw)
            valid.append(entry)
        except LogParseError as exc:
            errors.append(f"Line {i}: {exc}")
    return valid, errors
