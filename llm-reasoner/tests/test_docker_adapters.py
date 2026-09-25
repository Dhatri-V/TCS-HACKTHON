import json
from unittest.mock import Mock, patch
import pytest

from llm_reasoner.docker_adapters import (
    find_compose_file,
    probe_orders_api_health,
    inspect_docker_compose_services,
    get_incident_context_adapter,
    get_logs_adapter,
)
from llm_reasoner.tools import ContextArgs, LogsArgs


MOCK_HEALTH_200 = {"service": "orders-api", "status": "healthy", "database": "healthy"}
MOCK_HEALTH_503 = {"service": "orders-api", "status": "unhealthy", "database": "unavailable"}

MOCK_COMPOSE_PS_HEALTHY = (
    '{"Service": "orders-api", "State": "running", "Status": "Up 3 hours (healthy)", "Health": "healthy"}\n'
    '{"Service": "postgres", "State": "running", "Status": "Up 3 hours (healthy)", "Health": "healthy"}\n'
)

MOCK_COMPOSE_PS_UNHEALTHY = (
    '{"Service": "orders-api", "State": "running", "Status": "Up 3 hours (unhealthy)", "Health": "unhealthy"}\n'
    '{"Service": "postgres", "State": "exited", "Status": "Exited (0) 10 seconds ago", "Health": ""}\n'
)

MOCK_LOGS_OUTPUT = (
    '{"timestamp": "2026-09-25T13:04:08.638+00:00", "service": "orders-api", "level": "info", "message": "orders-api listening", "port": 8000}\n'
    '{"timestamp": "2026-09-25T16:17:04.348+00:00", "service": "orders-api", "level": "error", "message": "PostgreSQL connection failed", "dependency": "postgres", "operation": "health_check", "error_type": "OperationalError", "sqlstate": null}\n'
    '{"timestamp": "2026-09-25T16:17:09.500+00:00", "service": "orders-api", "level": "error", "message": "PostgreSQL connection failed", "dependency": "postgres", "operation": "health_check", "error_type": "OperationalError", "sqlstate": null}\n'
    'What\'s next:\n    docker logs\n'
)


def test_probe_orders_api_health_success():
    mock_resp = Mock(status_code=200)
    mock_resp.json.return_value = MOCK_HEALTH_200
    with patch("requests.get", return_value=mock_resp):
        res = probe_orders_api_health(health_url="http://test:18080/health")
        assert res["status_code"] == 200
        assert res["data"]["database"] == "healthy"


def test_probe_orders_api_health_unhealthy():
    mock_resp = Mock(status_code=503)
    mock_resp.json.return_value = MOCK_HEALTH_503
    with patch("requests.get", return_value=mock_resp):
        res = probe_orders_api_health(health_url="http://test:18080/health")
        assert res["status_code"] == 503
        assert res["data"]["database"] == "unavailable"


def test_probe_orders_api_health_failure():
    with patch("requests.get", side_effect=RuntimeError("connection refused")):
        res = probe_orders_api_health(health_url="http://test:18080/health")
        assert res["status_code"] == 0
        assert "connection refused" in res["error"]


def test_inspect_docker_compose_services():
    mock_proc = Mock(returncode=0, stdout=MOCK_COMPOSE_PS_HEALTHY)
    with patch("subprocess.run", return_value=mock_proc):
        services = inspect_docker_compose_services(compose_file="/mock/compose.yaml")
        assert len(services) == 2
        assert services[0]["Service"] == "orders-api"
        assert services[1]["Service"] == "postgres"


def test_get_incident_context_healthy():
    mock_resp = Mock(status_code=200)
    mock_resp.json.return_value = MOCK_HEALTH_200
    mock_proc = Mock(returncode=0, stdout=MOCK_COMPOSE_PS_HEALTHY)

    with patch("requests.get", return_value=mock_resp), patch("subprocess.run", return_value=mock_proc):
        result = get_incident_context_adapter("INC-001", ContextArgs(fields=["service_health"]))
        assert result.status == "ok"
        texts = [e.text for e in result.evidence]
        assert any("200: status=healthy" in t for t in texts)
        assert any("postgres) is running" in t for t in texts)


def test_get_incident_context_unhealthy_stopped_postgres():
    mock_resp = Mock(status_code=503)
    mock_resp.json.return_value = MOCK_HEALTH_503
    mock_proc = Mock(returncode=0, stdout=MOCK_COMPOSE_PS_UNHEALTHY)

    with patch("requests.get", return_value=mock_resp), patch("subprocess.run", return_value=mock_proc):
        result = get_incident_context_adapter("INC-001", ContextArgs(fields=["service_health"]))
        assert result.status == "ok"
        texts = [e.text for e in result.evidence]
        assert any("503: status=unhealthy, database=unavailable" in t for t in texts)
        assert any("PostgreSQL container (postgres) is stopped" in t for t in texts)


def test_get_incident_context_other_fields():
    result = get_incident_context_adapter(
        "INC-001",
        ContextArgs(fields=["configuration", "network", "storage", "recent_changes"])
    )
    assert result.status == "ok"
    ids = [e.id for e in result.evidence]
    assert "ctx-configuration" in ids
    assert "ctx-network" in ids
    assert "ctx-storage" in ids
    assert "ctx-recent-changes" in ids


def test_get_logs_adapter_success():
    mock_proc = Mock(returncode=0, stdout=MOCK_LOGS_OUTPUT)
    with patch("subprocess.run", return_value=mock_proc):
        result = get_logs_adapter("INC-001", LogsArgs(query="PostgreSQL connection failed", limit=5))
        assert result.status == "ok"
        assert len(result.evidence) >= 1
        assert "PostgreSQL connection failed" in result.evidence[0].text
        assert "OperationalError" in result.evidence[0].text


def test_get_logs_adapter_no_match():
    mock_proc = Mock(returncode=0, stdout=MOCK_LOGS_OUTPUT)
    with patch("subprocess.run", return_value=mock_proc):
        result = get_logs_adapter("INC-001", LogsArgs(query="redis timeout", limit=5))
        assert result.status == "unavailable"


def test_get_logs_adapter_error():
    with patch("subprocess.run", side_effect=RuntimeError("docker error")):
        result = get_logs_adapter("INC-001", LogsArgs(query="errors", limit=5))
        assert result.status == "unavailable"
