"""Deterministic, extractive provenance. No fuzzy ID or semantic claim matching."""
import json
import re

from .client import ReasoningError
from .recommendations import assess_recommendations
from .schemas import DiagnosisDraft, ReasoningRequest, ReasoningResponse


def evidence_catalog(request: ReasoningRequest) -> list[dict]:
    return [dict(number=i, source=source, evidence_id=item.id, text=item.text)
            for i, (source, item) in enumerate(
                ((source, item) for source in ('logs', 'system_context', 'similar_incidents')
                 for item in getattr(request, source)), start=1)]


def reject_invented_citations(text: str, allowed: set[str]) -> None:
    citations = re.findall(r'\[([^\[\]]+)\]', text)
    citations += re.findall(r'tool:\d+:[a-z_]+:[\w:.-]+', text)
    citations += re.findall(r'\b(?:LOG|CTX|HIST)-[\w-]+', text)
    if any(c not in allowed and c.rstrip('.') not in allowed for c in citations):
        raise ReasoningError('unknown_reference')


def ground_draft(request: ReasoningRequest, draft: DiagnosisDraft) -> ReasoningResponse:
    catalog = evidence_catalog(request)
    by_number = {row['number']: row for row in catalog}
    allowed = {row['evidence_id'] for row in catalog}
    if any(number not in by_number for number in draft.evidence_numbers):
        raise ReasoningError('unknown_reference')
    for text in [draft.probable_root_cause or '', *draft.missing_information,
                 *draft.remediation_steps, *draft.configuration_changes]:
        reject_invented_citations(text, allowed)
    selected = [by_number[n] for n in dict.fromkeys(draft.evidence_numbers)]
    claims = [dict(evidence_id=row['evidence_id'], source=row['source'], text=row['text'])
              for row in selected]
    # Quote entire records: substrings can remove a negation or change scope.
    # JSON quoting keeps brackets/newlines inside untrusted source text visibly quoted.
    explanation = '\n'.join(
        f"{'Historical analogy only' if row['source'] == 'similar_incidents' else 'Reported evidence'}: "
        f"{json.dumps(row['text'], ensure_ascii=False)} [{row['evidence_id']}]"
        for row in selected) or 'No evidence was selected to support a factual diagnosis.'
    cause = draft.probable_root_cause
    missing = [f'Model-requested follow-up (unverified): {item}' for item in draft.missing_information]
    current_matches = [row for row in selected if row['source'] != 'similar_incidents'
                       and row['text'] == cause]
    if cause and not current_matches:
        missing.append(f'Unverified root-cause hypothesis; source confirmation required: {cause}')
        cause = None
    elif cause:
        cause = f"Reported diagnostic observation: {cause} [{current_matches[0]['evidence_id']}]"
    return ReasoningResponse(incident_id=request.incident_id,
        status='completed' if cause else 'insufficient_evidence', probable_root_cause=cause,
        explanation=explanation, references=[row['evidence_id'] for row in selected],
        grounded_claims=claims, remediation_steps=draft.remediation_steps,
        configuration_changes=draft.configuration_changes, missing_information=missing,
        remediation_metadata=assess_recommendations(draft.remediation_steps, draft.configuration_changes))
