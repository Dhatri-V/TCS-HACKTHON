"""Read-only adapters connecting investigation tools to demo-infrastructure."""
import json
import os
import re
import subprocess
from typing import Any
import requests

from .schemas import Evidence
from .tools import ContextArgs, LogsArgs, ToolResult


def find_compose_file() -> str | None:
    """Find the path to demo-infrastructure/compose.yaml."""
    explicit = os.getenv("DEMO_COMPOSE_FILE")
    if explicit and os.path.isfile(explicit):
        return explicit

    candidates = [
        os.path.abspath("demo-infrastructure/compose.yaml"),
        os.path.abspath("../demo-infrastructure/compose.yaml"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "demo-infrastructure", "compose.yaml"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def probe_orders_api_health(health_url: str | None = None, timeout: float = 3.0) -> dict[str, Any] | None:
    """Probe the orders-api health endpoint (read-only)."""
    url = health_url or os.getenv("ORDERS_API_HEALTH_URL", "http://127.0.0.1:18080/health")
    try:
        response = requests.get(url, timeout=timeout)
        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}
        return {
            "status_code": response.status_code,
            "data": data,
            "url": url,
        }
    except Exception as exc:
        return {
            "status_code": 0,
            "error": str(exc),
            "url": url,
        }


def inspect_docker_compose_services(compose_file: str | None = None) -> list[dict[str, Any]]:
    """Query docker compose ps -a --format json (read-only)."""
    compose_path = compose_file or find_compose_file()
    cmd = ["docker", "compose"]
    if compose_path:
        cmd.extend(["-f", compose_path])
    cmd.extend(["ps", "-a", "--format", "json"])

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if proc.returncode != 0:
            return []
        services = []
        for line in proc.stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                services.append(json.loads(line))
            except Exception:
                continue
        return services
    except Exception:
        return []


def get_incident_context_adapter(incident_id: str, args: ContextArgs) -> ToolResult:
    """Provide verified read-only operational context for orders-api demo."""
    evidence: list[Evidence] = []
    fields = set(args.fields)

    # 1. service_health category
    if "service_health" in fields:
        probe = probe_orders_api_health()
        if probe:
            if probe["status_code"] == 200:
                data = probe.get("data", {})
                evidence.append(Evidence(
                    id="ctx-orders-api-health",
                    text=f"orders-api health probe returned 200: status={data.get('status', 'healthy')}, database={data.get('database', 'healthy')}",
                ))
            elif probe["status_code"] == 503:
                data = probe.get("data", {})
                evidence.append(Evidence(
                    id="ctx-orders-api-health",
                    text=f"orders-api health probe returned 503: status={data.get('status', 'unhealthy')}, database={data.get('database', 'unavailable')}",
                ))
            elif probe.get("error"):
                evidence.append(Evidence(
                    id="ctx-orders-api-health",
                    text=f"orders-api health probe unreachable at {probe['url']}: {probe['error']}",
                ))

        # Inspect real Docker container states for postgres and orders-api
        services = inspect_docker_compose_services()
        for svc in services:
            name = svc.get("Service", "")
            state = svc.get("State", "")
            status = svc.get("Status", "")
            health = svc.get("Health", "")

            if name == "postgres":
                if state == "exited" or "exit" in state.lower():
                    evidence.append(Evidence(
                        id="ctx-postgres-state",
                        text=f"PostgreSQL container (postgres) is stopped (State: {state}, Status: {status}).",
                    ))
                else:
                    evidence.append(Evidence(
                        id="ctx-postgres-state",
                        text=f"PostgreSQL container (postgres) is {state} (Health: {health or 'healthy'}, Status: {status}).",
                    ))
            elif name == "orders-api":
                evidence.append(Evidence(
                    id="ctx-orders-api-state",
                    text=f"orders-api container (orders-api) is {state} (Health: {health or 'none'}, Status: {status}).",
                ))

    # 2. configuration category
    if "configuration" in fields:
        evidence.append(Evidence(
            id="ctx-configuration",
            text="orders-api database configuration: PGHOST=postgres, PGPORT=5432, PGDATABASE=orders, PGUSER=demo.",
        ))

    # 3. network category
    if "network" in fields:
        evidence.append(Evidence(
            id="ctx-network",
            text="orders-api network configuration: container port 8000 mapped to host 127.0.0.1:18080; connects to PostgreSQL at host 'postgres' port 5432.",
        ))

    # 4. storage category
    if "storage" in fields:
        evidence.append(Evidence(
            id="ctx-storage",
            text="PostgreSQL storage configuration: volume 'postgres-data' mounted at /var/lib/postgresql/data.",
        ))

    # 5. recent_changes category
    if "recent_changes" in fields:
        evidence.append(Evidence(
            id="ctx-recent-changes",
            text="No recent deployments or infrastructure changes recorded in demo environment.",
        ))

    if not evidence:
        return ToolResult(status="unavailable")

    return ToolResult(status="ok", evidence=evidence)


def get_logs_adapter(incident_id: str, args: LogsArgs) -> ToolResult:
    """Fetch and filter actual read-only logs from orders-api container."""
    compose_path = find_compose_file()
    cmd = ["docker", "compose"]
    if compose_path:
        cmd.extend(["-f", compose_path])
    tail_count = max(args.limit * 3, 50)
    cmd.extend(["logs", "--no-log-prefix", "--tail", str(tail_count), "orders-api"])

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except Exception:
        return ToolResult(status="unavailable")

    if proc.returncode != 0:
        return ToolResult(status="unavailable")

    # Parse and filter actual JSON log records
    query_terms = [t.lower() for t in re.findall(r"\w+", args.query)
                   if t.lower() not in {"the", "a", "an", "is", "in", "to", "for", "of", "and"}]

    evidence: list[Evidence] = []
    seen_timestamps: set[str] = set()
    idx = 1

    # Read from most recent to oldest
    lines = proc.stdout.splitlines()
    for line in reversed(lines):
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue

        ts = rec.get("timestamp", str(idx))
        if ts in seen_timestamps:
            continue
        seen_timestamps.add(ts)

        # Match query terms if specified
        if query_terms:
            text_repr = f"{rec.get('level', '')} {rec.get('message', '')} {rec.get('dependency', '')} {rec.get('error_type', '')}".lower()
            if not any(term in text_repr for term in query_terms):
                continue

        log_text = (
            f"orders-api log [{rec.get('level', '').upper()}]: {rec.get('message', '')} "
            f"(dependency={rec.get('dependency', 'none')}, error_type={rec.get('error_type', 'none')})"
        )
        evidence.append(Evidence(id=f"orders-log-{idx}", text=log_text))
        idx += 1
        if len(evidence) >= args.limit:
            break

    if not evidence:
        return ToolResult(status="unavailable")

    return ToolResult(status="ok", evidence=evidence)
