"""Bridge between Express incident-platform REST API and the LLM reasoner."""
import os
import sys
from typing import Any, Callable
import requests
from pydantic import BaseModel

from .agent import investigate_incident
from .schemas import Evidence, ReasoningRequest, ReasoningResponse
from .tools import ToolRegistry, ToolResult


class BridgeError(RuntimeError):
    """Bridge integration error with error code and detail."""

    def __init__(self, code: str, message: str = ""):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}" if message else code)


def get_api_base(override_url: str | None = None) -> str:
    """Return the base URL for the incident-platform REST API."""
    if override_url:
        return override_url.rstrip("/")
    return os.getenv("INCIDENT_API_BASE", "http://localhost:3000").rstrip("/")


def fetch_incident(
    incident_id: str,
    api_base: str | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Fetch an incident by incident_id from the backend API."""
    base = get_api_base(api_base)
    url = f"{base}/api/incidents/{incident_id}"
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise BridgeError("backend_unavailable", f"Failed to connect to {url}: {exc}") from exc

    if response.status_code == 404:
        raise BridgeError("incident_not_found", f"Incident {incident_id} not found at {url}")
    if response.status_code != 200:
        raise BridgeError("fetch_failed", f"Unexpected status {response.status_code} from {url}: {response.text}")

    try:
        return response.json()
    except Exception as exc:
        raise BridgeError("invalid_json", f"Non-JSON response from {url}") from exc


def incident_to_reasoning_request(incident: dict[str, Any]) -> ReasoningRequest:
    """Transform backend incident record into a ReasoningRequest."""
    incident_id = incident.get("incident_id")
    if not incident_id:
        raise BridgeError("invalid_incident", "Missing incident_id in incident payload")

    service = incident.get("service", "unknown-service")
    message = incident.get("message", "Incident reported")

    # Format natural language current_incident summary
    current_incident = f"{service}: {message}"

    # Extract initial logs from incident message or logs list
    logs: list[Evidence] = []
    if "logs" in incident and isinstance(incident["logs"], list):
        for item in incident["logs"]:
            if isinstance(item, dict) and "id" in item and "text" in item:
                logs.append(Evidence(id=str(item["id"]), text=str(item["text"])))
    elif message:
        # Ground initial evidence in the reported error log message
        logs.append(Evidence(id="LOG-1", text=message))

    system_context: list[Evidence] = []
    if "system_context" in incident and isinstance(incident["system_context"], list):
        for item in incident["system_context"]:
            if isinstance(item, dict) and "id" in item and "text" in item:
                system_context.append(Evidence(id=str(item["id"]), text=str(item["text"])))

    similar_incidents: list[Evidence] = []
    if "similar_incidents" in incident and isinstance(incident["similar_incidents"], list):
        for item in incident["similar_incidents"]:
            if isinstance(item, dict) and "id" in item and "text" in item:
                similar_incidents.append(Evidence(id=str(item["id"]), text=str(item["text"])))

    return ReasoningRequest(
        incident_id=incident_id,
        current_incident=current_incident,
        logs=logs,
        system_context=system_context,
        similar_incidents=similar_incidents,
    )


from .docker_adapters import get_incident_context_adapter, get_logs_adapter
from .rag import rag_tool_adapter


class ToolCallRecord(BaseModel):
    tool: str
    arguments: dict[str, Any]
    status: str


def create_investigation_tools(
    *,
    log_adapter: Callable | None = None,
    context_adapter: Callable | None = None,
    rag_adapter: Callable | None = None,
    use_docker_demo: bool = True,
) -> tuple[ToolRegistry, list[ToolCallRecord]]:
    """Create tracked Docker and Chroma tool adapters for the investigation graph."""
    call_log: list[ToolCallRecord] = []

    active_log_adapter = log_adapter or (get_logs_adapter if use_docker_demo else None)
    active_context_adapter = context_adapter or (get_incident_context_adapter if use_docker_demo else None)
    active_rag_adapter = rag_adapter if rag_adapter is not None else rag_tool_adapter

    def get_logs_wrapper(incident_id: str, args):
        record = ToolCallRecord(tool="get_logs", arguments=args.model_dump(), status="unavailable")
        call_log.append(record)
        if active_log_adapter is not None:
            res = active_log_adapter(incident_id, args)
            record.status = res.status if isinstance(res, ToolResult) else res.get("status", "error")
            return res
        return ToolResult(status="unavailable")

    def get_incident_context_wrapper(incident_id: str, args):
        record = ToolCallRecord(tool="get_incident_context", arguments=args.model_dump(), status="unavailable")
        call_log.append(record)
        if active_context_adapter is not None:
            res = active_context_adapter(incident_id, args)
            record.status = res.status if isinstance(res, ToolResult) else res.get("status", "error")
            return res
        return ToolResult(status="unavailable")

    def retrieve_similar_incidents_wrapper(incident_id: str, args):
        record = ToolCallRecord(tool="retrieve_similar_incidents", arguments=args.model_dump(), status="unavailable")
        call_log.append(record)
        if active_rag_adapter is not None:
            res = active_rag_adapter(incident_id, args)
            record.status = res.status if isinstance(res, ToolResult) else res.get("status", "error")
            return res
        return ToolResult(status="unavailable")

    tools: ToolRegistry = {
        "get_logs": get_logs_wrapper,
        "get_incident_context": get_incident_context_wrapper,
        "retrieve_similar_incidents": retrieve_similar_incidents_wrapper,
    }
    return tools, call_log


def publish_analysis(
    incident_id: str,
    diagnosis: ReasoningResponse,
    api_base: str | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Publish the structured analysis to Express API via PATCH /api/incidents/:id/analysis."""
    base = get_api_base(api_base)
    url = f"{base}/api/incidents/{incident_id}/analysis"
    payload = diagnosis.model_dump()

    # Backend validation requires nonempty strings for array items
    for field in ("remediation_steps", "configuration_changes", "references", "missing_information"):
        if field in payload and isinstance(payload[field], list):
            payload[field] = [s.strip() for s in payload[field] if isinstance(s, str) and s.strip()]

    try:
        response = requests.patch(url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise BridgeError("backend_unavailable", f"Failed to patch analysis to {url}: {exc}") from exc

    if response.status_code != 200:
        raise BridgeError("publish_analysis_failed", f"Status {response.status_code} from {url}: {response.text}")

    try:
        return response.json()
    except Exception as exc:
        raise BridgeError("invalid_json", f"Non-JSON response from {url}") from exc


def update_status(
    incident_id: str,
    status: str = "DIAGNOSED",
    api_base: str | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Update incident lifecycle status via PATCH /api/incidents/:id/status."""
    base = get_api_base(api_base)
    url = f"{base}/api/incidents/{incident_id}/status"
    payload = {"status": status}

    try:
        response = requests.patch(url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise BridgeError("backend_unavailable", f"Failed to patch status to {url}: {exc}") from exc

    if response.status_code != 200:
        raise BridgeError("update_status_failed", f"Status {response.status_code} from {url}: {response.text}")

    try:
        return response.json()
    except Exception as exc:
        raise BridgeError("invalid_json", f"Non-JSON response from {url}") from exc


class InvestigationOutcome(BaseModel):
    incident_id: str
    fetched_incident: dict[str, Any]
    tools_selected: list[ToolCallRecord]
    reasoning_response: ReasoningResponse
    published_analysis: dict[str, Any]
    final_status: str
    updated_incident: dict[str, Any]


def run_incident_investigation(
    incident_id: str,
    api_base: str | None = None,
    target_status: str = "DIAGNOSED",
    *,
    log_adapter: Callable | None = None,
    context_adapter: Callable | None = None,
    rag_adapter: Callable | None = None,
    use_docker_demo: bool = True,
) -> InvestigationOutcome:
    """Execute the full end-to-end investigation workflow."""
    # 1. Fetch incident from Express API
    incident = fetch_incident(incident_id, api_base=api_base)

    # 2. Transform incident into ReasoningRequest
    request = incident_to_reasoning_request(incident)

    # 3. Setup tools with tracking
    tools, tool_calls = create_investigation_tools(
        log_adapter=log_adapter,
        context_adapter=context_adapter,
        rag_adapter=rag_adapter,
        use_docker_demo=use_docker_demo,
    )

    # 4. Invoke LangGraph agent investigation
    response = investigate_incident(request, tools)

    # 5. Publish analysis to Express API
    analysis_result = publish_analysis(incident_id, response, api_base=api_base)

    # 6. Update incident lifecycle status
    status_result = update_status(incident_id, status=target_status, api_base=api_base)

    return InvestigationOutcome(
        incident_id=incident_id,
        fetched_incident=incident,
        tools_selected=tool_calls,
        reasoning_response=response,
        published_analysis=analysis_result,
        final_status=status_result.get("status", target_status),
        updated_incident=status_result,
    )


def main():
    """Command-line entrypoint for running an investigation."""
    incident_id = sys.argv[1] if len(sys.argv) > 1 else "INC-DEMO-001"
    print(f"==================================================")
    print(f"Starting Investigation Bridge for {incident_id}")
    print(f"==================================================")
    api_base = os.getenv("INCIDENT_API_BASE", "http://localhost:3000")
    print(f"Connecting to Express API at: {api_base}")

    try:
        outcome = run_incident_investigation(incident_id, api_base=api_base)
    except BridgeError as err:
        print(f"Bridge error: {err}")
        sys.exit(1)
    except Exception as err:
        print(f"Investigation failed: {err}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("\nInvestigation Complete!")
    print("--------------------------------------------------")
    print(f"Incident ID: {outcome.incident_id}")
    print(f"Tools selected: {[f'{t.tool}({t.arguments})' for t in outcome.tools_selected] or 'None (finalize)'}")
    print(f"Reasoning Status: {outcome.reasoning_response.status}")
    print(f"Probable Root Cause: {outcome.reasoning_response.probable_root_cause}")
    print(f"Explanation: {outcome.reasoning_response.explanation}")
    print(f"References: {outcome.reasoning_response.references}")
    print(f"Remediation Steps: {outcome.reasoning_response.remediation_steps}")
    print(f"Missing Information: {outcome.reasoning_response.missing_information}")
    print(f"Final Lifecycle Status: {outcome.final_status}")
    print("--------------------------------------------------")
    print("Analysis successfully published and incident updated in MongoDB.")


if __name__ == "__main__":
    main()
