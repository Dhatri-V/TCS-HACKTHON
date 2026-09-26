"""Small JSON contracts shared with the RAG/backend team."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .recommendations import RISK, minimum_action_type


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Evidence(Contract):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class ReasoningRequest(Contract):
    incident_id: str = Field(min_length=1)
    current_incident: str = Field(min_length=1)
    logs: list[Evidence] = Field(default_factory=list)
    system_context: list[Evidence] = Field(default_factory=list)
    similar_incidents: list[Evidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [item.id for item in self.logs + self.system_context + self.similar_incidents]
        if len(ids) != len(set(ids)):
            raise ValueError("Evidence IDs must be unique across all input lists")
        return self


class RemediationMetadata(Contract):
    source: Literal['remediation_steps', 'configuration_changes']
    index: int = Field(ge=0, strict=True)
    action_type: Literal['inspection', 'state_changing', 'potentially_destructive']
    preconditions: list[str] = Field(default_factory=list)
    safeguards: list[str] = Field(default_factory=list)
    verification: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def require_change_safeguards(self):
        if self.action_type != 'inspection':
            for items in (self.preconditions, self.safeguards, self.verification):
                if not items or any(len(item.strip()) < 10 or item.strip().lower() in
                                    {'not applicable', 'to be determined'} for item in items):
                    raise ValueError('Changes require explicit preconditions, safeguards and verification')
        return self


class Analysis(Contract):
    status: Literal["completed", "insufficient_evidence"]
    probable_root_cause: str | None
    explanation: str = Field(min_length=1)
    remediation_steps: list[str]
    configuration_changes: list[str]
    references: list[str]
    missing_information: list[str]
    remediation_metadata: list[RemediationMetadata] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_status(self):
        if self.status == "completed" and not self.probable_root_cause:
            raise ValueError("Completed analysis requires a probable root cause")
        if self.status == "insufficient_evidence" and self.probable_root_cause is not None:
            raise ValueError("Insufficient evidence requires a null root cause")
        expected = {(source, index): text for source in ('remediation_steps', 'configuration_changes')
                    for index, text in enumerate(getattr(self, source))}
        supplied = {(item.source, item.index): item for item in self.remediation_metadata}
        if len(supplied) != len(self.remediation_metadata) or set(supplied) - set(expected):
            raise ValueError('Duplicate or unknown remediation metadata index')
        normalized = []
        for key, text in expected.items():
            floor = minimum_action_type(text)
            # Configuration changes always require review even if worded as a check.
            if key[0] == 'configuration_changes' and floor == 'inspection':
                floor = 'state_changing'
            item = supplied.get(key)
            if item is None:
                if floor != 'inspection':
                    raise ValueError('Changing recommendations require explicit safety metadata')
                item = RemediationMetadata(source=key[0], index=key[1], action_type='inspection')
            if RISK[item.action_type] < RISK[floor]:
                raise ValueError('Recommendation risk classification understates the action')
            normalized.append(item)
        self.remediation_metadata = normalized
        return self


class DiagnosisDraft(Contract):
    """Model selections/proposals only; no model-authored IDs or safety labels."""
    evidence_numbers: list[Annotated[int, Field(strict=True, ge=1)]] = Field(max_length=100)
    probable_root_cause: str | None
    remediation_steps: list[str]
    configuration_changes: list[str]
    missing_information: list[str]


class GroundedClaim(Contract):
    evidence_id: str
    source: Literal['logs', 'system_context', 'similar_incidents']
    text: str


class SafetyAssessment(Contract):
    source: Literal['remediation_steps', 'configuration_changes']
    index: int = Field(ge=0)
    action_type: Literal['inspection', 'state_changing', 'potentially_destructive']
    required_preconditions: list[str]
    required_safeguards: list[str]
    missing_requirements: list[str]
    # There is deliberately no trusted approval/safeguard input or execution path.
    approval_eligible: Literal[False] = False
    executable: Literal[False] = False


class ReasoningResponse(Contract):
    incident_id: str
    status: Literal['completed', 'insufficient_evidence']
    probable_root_cause: str | None
    explanation: str = Field(min_length=1)
    remediation_steps: list[str]
    configuration_changes: list[str]
    references: list[str]
    missing_information: list[str]
    grounded_claims: list[GroundedClaim]
    remediation_metadata: list[SafetyAssessment]

    @model_validator(mode='after')
    def consistent_output(self):
        if (self.status == 'completed') != bool(self.probable_root_cause):
            raise ValueError('Diagnosis status and cause must agree')
        if self.references != list(dict.fromkeys(c.evidence_id for c in self.grounded_claims)):
            raise ValueError('References must exactly match grounded claims')
        return self
