import json
from unittest.mock import Mock, patch
import pytest

from llm_reasoner.bridge import (
    BridgeError,
    fetch_incident,
    incident_to_reasoning_request,
    publish_analysis,
    update_status,
    create_investigation_tools,
    run_incident_investigation,
)
from llm_reasoner.schemas import (
    Evidence,
    GroundedClaim,
    ReasoningRequest,
    ReasoningResponse,
    SafetyAssessment,
)
from llm_reasoner.tools import ToolResult


SAMPLE_INCIDENT = {
    "incident_id": "INC-TEST-001",
    "timestamp": "2026-09-25T21:12:00.000Z",
    "service": "orders-api",
    "log_level": "error",
    "message": "PostgreSQL connection failed",
    "classification": "ERROR",
    "status": "INVESTIGATING",
    "analysis": None,
}

SAMPLE_DIAGNOSIS = ReasoningResponse(
    incident_id="INC-TEST-001",
    status="insufficient_evidence",
    probable_root_cause=None,
    explanation="Reported evidence: \"PostgreSQL connection failed\" [LOG-1]",
    remediation_steps=["Check database connectivity"],
    configuration_changes=[],
    references=["LOG-1"],
    missing_information=["PostgreSQL server status unavailable"],
    grounded_claims=[
        GroundedClaim(
            evidence_id="LOG-1",
            source="logs",
            text="PostgreSQL connection failed",
        )
    ],
    remediation_metadata=[
        SafetyAssessment(
            source="remediation_steps",
            index=0,
            action_type="inspection",
            required_preconditions=[],
            required_safeguards=[],
            missing_requirements=[],
            approval_eligible=False,
            executable=False,
        )
    ],
)


def test_incident_transformation():
    req = incident_to_reasoning_request(SAMPLE_INCIDENT)
    assert req.incident_id == "INC-TEST-001"
    assert "orders-api: PostgreSQL connection failed" in req.current_incident
    assert len(req.logs) == 1
    assert req.logs[0].id == "LOG-1"
    assert req.logs[0].text == "PostgreSQL connection failed"
    assert req.system_context == []
    assert req.similar_incidents == []


def test_incident_transformation_missing_id():
    with pytest.raises(BridgeError, match="Missing incident_id"):
        incident_to_reasoning_request({"message": "no id"})


def test_fetch_incident_success():
    mock_resp = Mock(status_code=200)
    mock_resp.json.return_value = SAMPLE_INCIDENT

    with patch("requests.get", return_value=mock_resp) as mock_get:
        data = fetch_incident("INC-TEST-001", api_base="http://test:3000")
        assert data["incident_id"] == "INC-TEST-001"
        mock_get.assert_called_once_with(
            "http://test:3000/api/incidents/INC-TEST-001", timeout=10.0
        )


def test_fetch_incident_404():
    mock_resp = Mock(status_code=404)
    with patch("requests.get", return_value=mock_resp):
        with pytest.raises(BridgeError, match="incident_not_found"):
            fetch_incident("INC-NONEXISTENT")


def test_publish_analysis_success():
    mock_resp = Mock(status_code=200)
    mock_resp.json.return_value = {**SAMPLE_INCIDENT, "analysis": SAMPLE_DIAGNOSIS.model_dump()}

    with patch("requests.patch", return_value=mock_resp) as mock_patch:
        res = publish_analysis("INC-TEST-001", SAMPLE_DIAGNOSIS, api_base="http://test:3000")
        mock_patch.assert_called_once()
        url = mock_patch.call_args[0][0]
        assert url == "http://test:3000/api/incidents/INC-TEST-001/analysis"
        payload = mock_patch.call_args[1]["json"]
        assert payload["incident_id"] == "INC-TEST-001"
        assert payload["status"] == "insufficient_evidence"


def test_update_status_success():
    mock_resp = Mock(status_code=200)
    mock_resp.json.return_value = {**SAMPLE_INCIDENT, "status": "DIAGNOSED"}

    with patch("requests.patch", return_value=mock_resp) as mock_patch:
        res = update_status("INC-TEST-001", status="DIAGNOSED", api_base="http://test:3000")
        assert res["status"] == "DIAGNOSED"
        mock_patch.assert_called_once_with(
            "http://test:3000/api/incidents/INC-TEST-001/status",
            json={"status": "DIAGNOSED"},
            timeout=10.0,
        )


def test_tool_tracking_and_unavailability():
    tools, calls = create_investigation_tools(use_docker_demo=False)
    assert "get_logs" in tools
    assert "get_incident_context" in tools
    assert "retrieve_similar_incidents" in tools

    from llm_reasoner.tools import LogsArgs
    res = tools["get_logs"]("INC-TEST-001", LogsArgs(query="find db error"))
    assert res.status == "unavailable"
    assert len(calls) == 1
    assert calls[0].tool == "get_logs"
    assert calls[0].status == "unavailable"


def test_run_incident_investigation_e2e():
    get_resp = Mock(status_code=200)
    get_resp.json.return_value = SAMPLE_INCIDENT

    analysis_resp = Mock(status_code=200)
    analysis_resp.json.return_value = {**SAMPLE_INCIDENT, "analysis": SAMPLE_DIAGNOSIS.model_dump()}

    status_resp = Mock(status_code=200)
    status_resp.json.return_value = {**SAMPLE_INCIDENT, "status": "DIAGNOSED"}

    with patch("requests.get", return_value=get_resp):
        with patch("requests.patch", side_effect=[analysis_resp, status_resp]):
            with patch("llm_reasoner.bridge.investigate_incident", return_value=SAMPLE_DIAGNOSIS) as mock_inv:
                outcome = run_incident_investigation("INC-TEST-001", api_base="http://test:3000")
                assert outcome.incident_id == "INC-TEST-001"
                assert outcome.final_status == "DIAGNOSED"
                assert outcome.reasoning_response.status == "insufficient_evidence"
                mock_inv.assert_called_once()
