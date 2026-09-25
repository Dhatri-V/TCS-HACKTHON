"""
test_pipeline.py - Quick unit tests for the log processing pipeline
Run: venv/Scripts/python test_pipeline.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from preprocess import parse_line, LogParseError
from classifier import classify

passed = 0
failed = 0

def check(name, condition, msg=""):
    global passed, failed
    if condition:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name} {msg}")
        failed += 1

print("=" * 50)
print("  TCS Log Processor — Unit Tests")
print("=" * 50)

# ── Test 1: INFO log ─────────────────────────────────────────
print("\nTest 1: INFO log")
entry = parse_line('{"timestamp":"2026-09-25T10:00:00Z","level":"info","service":"backend","method":"GET","endpoint":"/api/products","statusCode":200,"message":"Products fetched successfully"}')
r = classify(entry)
check("INFO classification", r["classification"] == "INFO")
check("INFO is_incident=False", r["is_incident"] == False)

# ── Test 2: ERROR log ─────────────────────────────────────────
print("\nTest 2: ERROR log")
entry = parse_line('{"timestamp":"2026-09-25T10:00:01Z","level":"error","service":"backend","method":"POST","endpoint":"/api/products","statusCode":500,"errorType":"MongoServerError","message":"Database connection failed"}')
r = classify(entry)
check("ERROR classification", r["classification"] == "ERROR")
check("ERROR is_incident=True", r["is_incident"] == True)
check("ERROR has incident", "incident" in r)
check("ERROR incident has ID", r.get("incident", {}).get("incident_id", "").startswith("INC-"))
check("ERROR incident has error_type", r.get("incident", {}).get("error_type") == "MongoServerError")
print(f"  INFO: Incident ID = {r.get('incident', {}).get('incident_id')}")

# ── Test 3: WARN log ──────────────────────────────────────────
print("\nTest 3: WARN log")
entry = parse_line('{"timestamp":"2026-09-25T10:00:02Z","level":"warn","service":"backend","method":"GET","endpoint":"/api/products/bad","statusCode":400,"errorType":"InvalidObjectId","message":"Invalid product ID format"}')
r = classify(entry)
check("WARN -> WARNING", r["classification"] == "WARNING")
check("WARNING is_incident=False", r["is_incident"] == False)

# ── Test 4: CRITICAL log ──────────────────────────────────────
print("\nTest 4: CRITICAL log")
entry = parse_line('{"timestamp":"2026-09-25T10:00:03Z","level":"critical","service":"backend","message":"Critical system failure"}')
r = classify(entry)
check("CRITICAL classification", r["classification"] == "CRITICAL")
check("CRITICAL is_incident=True", r["is_incident"] == True)
check("CRITICAL has incident", "incident" in r)

# ── Test 5: Invalid JSON ──────────────────────────────────────
print("\nTest 5: Invalid JSON")
try:
    parse_line("not json at all")
    check("Invalid JSON raises error", False)
except LogParseError:
    check("Invalid JSON raises LogParseError", True)

# ── Test 6: Missing required fields ──────────────────────────
print("\nTest 6: Missing required fields")
try:
    parse_line('{"level":"info"}')
    check("Missing fields raises error", False)
except LogParseError as e:
    check("Missing fields raises LogParseError", True)

# ── Test 7: Empty line ────────────────────────────────────────
print("\nTest 7: Empty line")
try:
    parse_line("   ")
    check("Empty line raises error", False)
except LogParseError:
    check("Empty line raises LogParseError", True)

# ── Test 8: Level normalisation ───────────────────────────────
print("\nTest 8: Level normalisation (warn -> WARNING)")
entry = parse_line('{"timestamp":"2026-09-25T10:00:04Z","level":"warn","service":"backend","message":"test"}')
check("warn normalised to WARNING", entry["level"] == "WARNING")

# ── Summary ───────────────────────────────────────────────────
print()
print("=" * 50)
print(f"  Results: {passed} passed, {failed} failed")
print("=" * 50)

if failed > 0:
    sys.exit(1)
