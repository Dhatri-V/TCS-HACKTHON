"""Human-gated orchestration around diagnosis; does not change the LLM agent.

A retry means one re-investigation, NOT an automatic action replay. Its result
returns to DIAGNOSED; trusted application code must create a new proposal and
obtain new human approval before another execution can occur.
"""
from threading import RLock
from typing import Callable

from .remediation import ExecutionBoundary
from .remediation_contracts import (
    ActionProposal, ApprovalStatus, BoundaryError, ExecutionResult,
    HealthResult, HumanDecision, RemediationAction, WorkflowState,
)
from .schemas import Evidence, ReasoningRequest, ReasoningResponse

Reinvestigator = Callable[[ReasoningRequest], ReasoningResponse]


class RemediationWorkflow:
    def __init__(self, *, incident: ReasoningRequest | dict,
                 diagnosis: ReasoningResponse, boundary: ExecutionBoundary,
                 reinvestigate: Reinvestigator | None = None, max_reinvestigations: int = 1):
        if type(max_reinvestigations) is not int or not 0 <= max_reinvestigations <= 3:
            raise ValueError('Re-investigation budget must be an integer from 0 to 3')
        self._incident = ReasoningRequest.model_validate(incident.model_dump() if isinstance(incident, ReasoningRequest) else incident)
        self._diagnosis = ReasoningResponse.model_validate(diagnosis.model_dump())
        if self._diagnosis.incident_id != self._incident.incident_id:
            raise BoundaryError('incident_mismatch')
        self._boundary = boundary
        self._reinvestigate = reinvestigate
        self._max_reinvestigations = max_reinvestigations
        self._reinvestigations = 0
        self._action_id: str | None = None
        self._state = WorkflowState.DIAGNOSED
        self._history = [self._state]
        self._last_execution: ExecutionResult | None = None
        self._last_health: HealthResult | None = None
        self._failure_code: str | None = None
        self._lock = RLock()

    @property
    def state(self):
        return self._state

    @property
    def history(self):
        return tuple(self._history)

    @property
    def diagnosis(self):
        return self._diagnosis.model_copy(deep=True)

    @property
    def reinvestigations(self):
        return self._reinvestigations

    @property
    def last_execution(self):
        return self._last_execution

    @property
    def last_health(self):
        return self._last_health

    @property
    def failure_code(self):
        return self._failure_code

    def _transition(self, state):
        self._state = state
        self._history.append(state)

    def _fail(self, code):
        self._failure_code = code
        self._transition(WorkflowState.FAILED)

    def propose(self, proposal: ActionProposal | dict) -> RemediationAction:
        with self._lock:
            if self._state != WorkflowState.DIAGNOSED:
                raise BoundaryError('proposal_not_allowed_in_current_state')
            proposal = ActionProposal.model_validate(proposal.model_dump() if isinstance(proposal, ActionProposal) else proposal)
            if proposal.incident_id != self._incident.incident_id:
                raise BoundaryError('incident_mismatch')
            action = self._boundary.create_proposal(proposal)
            self._action_id = action.action_id
            self._transition(WorkflowState.PROPOSED)
            self.refresh_eligibility()
            return self._boundary.action(action.action_id)

    def refresh_eligibility(self) -> RemediationAction:
        with self._lock:
            if self._state not in {WorkflowState.PROPOSED, WorkflowState.BLOCKED,
                                   WorkflowState.PENDING_APPROVAL, WorkflowState.APPROVED}:
                raise BoundaryError('eligibility_refresh_not_allowed')
            action = self._boundary.action(self._action_id)
            if action.approval_status == ApprovalStatus.REJECTED:
                self._transition(WorkflowState.REJECTED)
            elif not action.approval_eligible:
                self._transition(WorkflowState.BLOCKED)
            elif action.approval_status == ApprovalStatus.APPROVED:
                self._transition(WorkflowState.APPROVED)
            else:
                self._transition(WorkflowState.PENDING_APPROVAL)
            return action

    def decide(self, decision: HumanDecision | dict) -> RemediationAction:
        """Called only by the authenticated human-decision application handler."""
        with self._lock:
            if self._state not in {WorkflowState.PENDING_APPROVAL, WorkflowState.BLOCKED}:
                raise BoundaryError('decision_not_allowed_in_current_state')
            decision = HumanDecision.model_validate(decision.model_dump() if isinstance(decision, HumanDecision) else decision)
            if decision.action_id != self._action_id:
                raise BoundaryError('wrong_action_for_workflow')
            action = self._boundary.record_approval(decision)
            self._transition(WorkflowState.APPROVED if action.approval_status == ApprovalStatus.APPROVED else WorkflowState.REJECTED)
            return action

    def execute_approved(self) -> ExecutionResult:
        """One controlled attempt + verification; never auto-approve a retry."""
        with self._lock:
            if self._state != WorkflowState.APPROVED:
                return ExecutionResult(action_id=self._action_id or '', status='blocked', code='workflow_not_approved')
            self._transition(WorkflowState.EXECUTING)
            result = self._boundary.execute(self._action_id)
            self._last_execution = result
            if result.status == 'blocked':
                self._transition(WorkflowState.BLOCKED)
                return result
            if result.status != 'succeeded':
                self._fail('execution_not_successful')
                return result
            self._transition(WorkflowState.VERIFYING)
            health = self._boundary.registry.check_service_health(result.service)
            self._last_health = health
            if health.status == 'healthy':
                self._transition(WorkflowState.RESOLVED)
                return result
            if self._reinvestigations >= self._max_reinvestigations:
                self._fail('retry_budget_exhausted')
                return result
            if self._reinvestigate is None:
                self._fail('reinvestigator_unavailable')
                return result
            self._reinvestigations += 1
            self._transition(WorkflowState.REINVESTIGATING)
            context = self._incident.model_copy(deep=True)
            existing_ids = {e.id for e in context.logs + context.system_context + context.similar_incidents}
            eid = f'verification:{self._action_id}:{self._reinvestigations}'
            while eid in existing_ids:
                eid += ':health'
            context.system_context.append(Evidence(id=eid,
                text=f'Controlled health adapter reports service={health.service}, status={health.status}. {health.details}'))
            try:
                raw = self._reinvestigate(context.model_copy(deep=True))
                diagnosis = ReasoningResponse.model_validate(raw.model_dump() if isinstance(raw, ReasoningResponse) else raw)
                if diagnosis.incident_id != context.incident_id:
                    raise ValueError('Wrong incident returned')
            except Exception:
                self._fail('reinvestigation_failed')
                return result
            self._incident = context
            self._diagnosis = diagnosis
            self._action_id = None
            # Even if the LLM says 'healthy', only the adapter can resolve a workflow.
            self._transition(WorkflowState.DIAGNOSED)
            return result
