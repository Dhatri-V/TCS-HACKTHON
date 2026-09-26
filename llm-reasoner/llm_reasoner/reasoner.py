"""One request, one completion, validated structured output."""
import re
import json

from pydantic import ValidationError

from . import client
from .client import ReasoningError
from .prompts import build_messages
from .schemas import Analysis, DiagnosisDraft, ReasoningRequest, ReasoningResponse
from .grounding import evidence_catalog, ground_draft


def analyze_incident(context: ReasoningRequest | dict) -> ReasoningResponse:
    # Revalidate even model instances, since callers can mutate their lists.
    request = ReasoningRequest.model_validate(
        context.model_dump() if isinstance(context, ReasoningRequest) else context
    )
    if len(request.model_dump_json()) > 60_000:
        raise ReasoningError("context_too_large")
    raw = client.complete(build_messages(request), response_schema=DiagnosisDraft)
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict) and 'evidence_numbers' in payload:
            draft = DiagnosisDraft.model_validate(payload)
            return ground_draft(request, draft)
        # Legacy model output retains ALL original validation before extraction.
        analysis = Analysis.model_validate(payload)
    except (ValidationError, TypeError, ValueError):
        raise ReasoningError("invalid_model_response") from None
    allowed = {item.id for item in
               request.logs + request.system_context + request.similar_incidents}
    cause = analysis.probable_root_cause
    if cause is not None:
        # Reject a bare ID even if surrounded by quotes/brackets/punctuation.
        normalized = cause.strip(" \"'`[]().:;").casefold()
        if normalized in {item.casefold() for item in allowed} or re.fullmatch(
            r"(?:log|ctx|hist)-[\w-]+", normalized
        ):
            raise ReasoningError("invalid_model_response")
    if not set(analysis.references).issubset(allowed):
        raise ReasoningError("unknown_reference")
    # Bracket citations are the preferred format. Legacy inline IDs remain valid.
    bracketed = re.findall(r'\[([^\[\]]+)\]', analysis.explanation)
    if any(citation not in allowed for citation in bracketed):
        raise ReasoningError('unknown_reference')
    # Check explicit citations, not semantic relevance (which needs evaluation).
    mentioned = {item for item in allowed if re.search(
        r"(?<![\w-])" + re.escape(item) + r"(?![\w-])", analysis.explanation
    )}
    if not mentioned.issubset(set(analysis.references)):
        raise ReasoningError("missing_references")
    if not set(analysis.references).issubset(mentioned):
        raise ReasoningError("unattributed_references")
    # Catch explicit invented tool citations even when omitted from references.
    cited_tools = set(re.findall(r"tool:\d+:[a-z_]+:[\w:.-]+", analysis.explanation))
    if any(eid.rstrip('.') not in allowed and eid not in allowed for eid in cited_tools):
        raise ReasoningError("unknown_reference")
    if analysis.status == "completed" and not analysis.references:
        raise ReasoningError("missing_references")
    numbers = {row['evidence_id']: row['number'] for row in evidence_catalog(request)}
    return ground_draft(request, DiagnosisDraft(
        evidence_numbers=[numbers[eid] for eid in analysis.references],
        probable_root_cause=analysis.probable_root_cause,
        remediation_steps=analysis.remediation_steps,
        configuration_changes=analysis.configuration_changes,
        missing_information=analysis.missing_information + [
            'Legacy explanation not accepted as verified prose: ' + analysis.explanation]))
