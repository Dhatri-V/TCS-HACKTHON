"""Bounded LangGraph investigation; no teammate services implemented here."""
import json
from copy import deepcopy
from typing import Literal, TypedDict
from pydantic import Field, ValidationError, model_validator
from langgraph.graph import StateGraph, START, END
from . import client
from .client import ReasoningError
from .schemas import Contract, Evidence, ReasoningRequest, ReasoningResponse
from .tools import ARGUMENTS, ToolRegistry, ToolResult
from .prompts import INVESTIGATION_PROMPT
from .reasoner import analyze_incident

class Decision(Contract):
    action: Literal["get_logs", "get_incident_context", "retrieve_similar_incidents", "finalize"]
    arguments: dict = Field(description="Required tool arguments matching its supplied schema; use an empty object for finalize.")
    reason: str = Field(min_length=1, max_length=500)
    information_gap: str = Field(max_length=500,
        description="For a tool call: the specific unanswered question that could materially change the diagnosis. For finalize: an empty string.")

    @model_validator(mode='after')
    def require_gap(self):
        if self.action != 'finalize' and len(self.information_gap.strip()) < 10:
            raise ValueError('A tool call requires a specific unresolved information gap')
        if self.action == 'finalize' and self.information_gap != '':
            raise ValueError('Finalize requires an empty information_gap')
        return self

    @classmethod
    def model_json_schema(cls, **kwargs):
        # Express action-dependent constraints to Ollama's JSON grammar, not just
        # in post-generation validators. Keep the same public Decision shape.
        base = super().model_json_schema(**kwargs)
        branches = []
        for action in [*ARGUMENTS, 'finalize']:
            branch = deepcopy(base)
            props = branch['properties']
            props['action'] = {'type': 'string', 'const': action}
            if action == 'finalize':
                props['arguments'] = {'type': 'object', 'properties': {}, 'additionalProperties': False}
                props['information_gap'] = {'type': 'string', 'const': ''}
            else:
                props['arguments'] = ARGUMENTS[action].model_json_schema()
                props['information_gap']['minLength'] = 10
            branches.append(branch)
        return {'title': 'Decision', 'anyOf': branches}

class InvestigationState(TypedDict):
    incident: ReasoningRequest
    observations: list[dict]
    calls: list[str]
    decision: Decision
    stop_reason: str
    response: ReasoningResponse
    collected_context_fields: list[str]


def call_signature(decision: Decision) -> str:
    arguments = dict(decision.arguments)
    if 'query' in arguments:
        arguments['query'] = ' '.join(arguments['query'].casefold().split())
    return json.dumps([decision.action, arguments], sort_keys=True)


def investigate_incident(incident: ReasoningRequest | dict, tools: ToolRegistry) -> ReasoningResponse:
    request = ReasoningRequest.model_validate(incident.model_dump() if isinstance(incident, ReasoningRequest) else incident)
    if set(tools) - set(ARGUMENTS):
        raise ValueError("Unknown tool registration")

    def decide(state):
        if len(state["calls"]) >= 3:
            return {"decision": Decision(action="finalize", arguments={}, reason="Tool budget exhausted", information_gap=""),
                    "stop_reason": "budget"}
        payload = {"incident": state["incident"].model_dump(), "observations": state["observations"],
                   "remaining_calls": 3 - len(state["calls"]),
                   "collected_context_fields": state["collected_context_fields"],
                   "tools": {n: ARGUMENTS[n].model_json_schema() for n in tools}}
        content = json.dumps(payload)
        if len(content) > 60000:
            raise ReasoningError("context_too_large")
        raw = client.complete([
            {"role": "system", "content": INVESTIGATION_PROMPT + json.dumps(Decision.model_json_schema())},
            {"role": "user", "content": content}], response_schema=Decision)
        try:
            decision = Decision.model_validate_json(raw)
            if decision.action == "finalize":
                if decision.arguments:
                    raise ValueError("Finalize accepts no arguments")
            else:
                if decision.action not in tools:
                    raise ValueError("Tool is not registered")
                args = ARGUMENTS[decision.action].model_validate(decision.arguments)
                decision.arguments = args.model_dump()
        except (ValidationError, ValueError, TypeError):
            raise ReasoningError("invalid_agent_decision") from None
        if decision.action == "get_incident_context":
            # Only fulfilled categories are suppressed. New categories remain useful.
            decision.arguments['fields'] = [f for f in decision.arguments['fields']
                                            if f not in state['collected_context_fields']]
            if not decision.arguments['fields']:
                return {"decision": Decision(action="finalize", arguments={}, reason="Context already collected", information_gap=""),
                        "stop_reason": "redundant_context"}
        signature = call_signature(decision)
        if signature in state["calls"]:
            return {"decision": Decision(action="finalize", arguments={}, reason="Repeated tool request", information_gap=""),
                    "stop_reason": "repeated_call"}
        return {"decision": decision}

    def execute_tool(state):
        decision = state["decision"]
        signature = call_signature(decision)
        calls = state["calls"] + [signature]
        try:
            raw = tools[decision.action](request.incident_id, ARGUMENTS[decision.action].model_validate(decision.arguments))
            result = ToolResult.model_validate(raw.model_dump() if isinstance(raw, ToolResult) else raw)
            if len(result.model_dump_json()) > 12000:
                raise ValueError("Tool result too large")
        except Exception:
            # Never expose raw exception details or turn errors into factual evidence.
            result = ToolResult(status="error")
        data = state["incident"].model_dump()
        field = {"get_logs": "logs", "get_incident_context": "system_context",
                 "retrieve_similar_incidents": "similar_incidents"}[decision.action]
        used = {e.id for e in state["incident"].logs + state["incident"].system_context + state["incident"].similar_incidents}
        evidence = []
        if result.status == "ok":
            for item in result.evidence:
                eid = f"tool:{len(calls)}:{decision.action}:{item.id}"
                if eid in used:
                    result = ToolResult(status="error")
                    evidence = []
                    break
                evidence.append(Evidence(id=eid, text=item.text))
        data[field].extend(e.model_dump() for e in evidence)
        observation = {"tool": decision.action, "status": result.status,
                       "arguments": decision.arguments,
                       "evidence": [e.model_dump() for e in evidence]}
        collected = state['collected_context_fields']
        if decision.action == 'get_incident_context' and result.status == 'ok' and evidence:
            collected = sorted(set(collected + decision.arguments['fields']))
        return {"incident": ReasoningRequest.model_validate(data), "calls": calls,
                "collected_context_fields": collected,
                "observations": state["observations"] + [observation]}

    def finalize(state):
        response = analyze_incident(state["incident"])
        # Investigation limitations belong in missing_information, never evidence.
        limitations = [f"{o['tool']} did not provide verified information ({o['status']})."
                       for o in state["observations"] if o["status"] != "ok"]
        if state.get("stop_reason"):
            limitations.append("Investigation stopped: " + state["stop_reason"] + ". Additional checks may be needed.")
        response.missing_information = list(dict.fromkeys(response.missing_information + limitations))
        return {"response": response}

    graph = StateGraph(InvestigationState)
    graph.add_node("decide", decide)
    graph.add_node("execute_tool", execute_tool)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "decide")
    graph.add_conditional_edges("decide", lambda s: "finalize" if s["decision"].action == "finalize" else "execute_tool")
    graph.add_edge("execute_tool", "decide")
    graph.add_edge("finalize", END)
    state = graph.compile().invoke({"incident": request, "observations": [], "calls": [], "stop_reason": "", "collected_context_fields": []},
                                   config={"recursion_limit": 12})
    return state["response"]
