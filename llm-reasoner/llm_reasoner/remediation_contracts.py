"""Typed application proposals and outcomes; no command/code action type."""
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class ImmutableContract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)


Name = Annotated[str, Field(strict=True, min_length=1, max_length=100,
                            pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]*$')]
Scalar = Annotated[str, Field(strict=True, min_length=1, max_length=128,
                              pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:/-]*$')] | Annotated[int, Field(strict=True)] | Annotated[bool, Field(strict=True)]
ActionType = Literal['restart_service', 'rollback_deployment', 'apply_allowed_config_change']


class RestartParameters(ImmutableContract):
    pass


class RollbackParameters(ImmutableContract):
    version: Name


class ConfigChange(ImmutableContract):
    key: Name
    value: Scalar


class ConfigParameters(ImmutableContract):
    change: ConfigChange


PARAMETERS = {
    'restart_service': RestartParameters,
    'rollback_deployment': RollbackParameters,
    'apply_allowed_config_change': ConfigParameters,
}


class ActionProposal(ImmutableContract):
    action_id: Name
    incident_id: Name
    action_type: ActionType
    service: Name
    parameters: dict
    description: str = Field(min_length=1, max_length=2000)

    @model_validator(mode='after')
    def validate_parameters(self):
        PARAMETERS[self.action_type].model_validate(self.parameters)
        return self


class ApprovalStatus(str, Enum):
    PENDING_APPROVAL = 'PENDING_APPROVAL'
    APPROVED = 'APPROVED'
    REJECTED = 'REJECTED'


class RemediationAction(ActionProposal):
    proposal_fingerprint: str
    approval_required: Literal[True] = True
    approval_status: ApprovalStatus
    approval_eligible: bool
    executable: bool
    missing_requirements: tuple[str, ...]


class HumanDecision(ImmutableContract):
    action_id: Name
    proposal_fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')
    actor: Name
    decision: Literal['APPROVED', 'REJECTED']


class ApprovalRecord(HumanDecision):
    recorded_at: str


class AdapterExecutionResult(ImmutableContract):
    status: Literal['succeeded', 'failed', 'unknown']


class ExecutionResult(ImmutableContract):
    action_id: str
    service: str | None = None
    status: Literal['succeeded', 'failed', 'unknown', 'blocked']
    code: str


class HealthResult(ImmutableContract):
    service: Name
    status: Literal['healthy', 'unhealthy', 'unknown']
    # A bounded, trusted-adapter report, still untrusted evidence to the LLM.
    details: str = Field(default='', max_length=2000)


class WorkflowState(str, Enum):
    DIAGNOSED = 'DIAGNOSED'
    PROPOSED = 'PROPOSED'
    BLOCKED = 'BLOCKED'
    PENDING_APPROVAL = 'PENDING_APPROVAL'
    APPROVED = 'APPROVED'
    REJECTED = 'REJECTED'
    EXECUTING = 'EXECUTING'
    VERIFYING = 'VERIFYING'
    REINVESTIGATING = 'REINVESTIGATING'
    RESOLVED = 'RESOLVED'
    FAILED = 'FAILED'


class BoundaryError(RuntimeError):
    """Stable code only; never expose adapter exceptions."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def validate_name(value: str) -> str:
    return TypeAdapter(Name).validate_python(value)
