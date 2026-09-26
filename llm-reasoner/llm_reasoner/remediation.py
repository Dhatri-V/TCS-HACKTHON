"""Trusted, in-memory controlled adapter boundary. No infrastructure adapters ship.

Only authenticated application code may call readiness/approval entry points.
Never expose these methods as LLM tools. Process-local locks prevent concurrent
replays, but durable distributed storage is required before production use.
"""
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from types import MappingProxyType
from typing import Callable, Mapping

from pydantic import ValidationError

from .remediation_contracts import (
    PARAMETERS, ActionProposal, AdapterExecutionResult, ApprovalRecord,
    ApprovalStatus, BoundaryError, ConfigChange, ExecutionResult, HealthResult,
    HumanDecision, RemediationAction, validate_name,
)


REQUIREMENTS = MappingProxyType({
    'restart_service': frozenset({'target_scope_reviewed', 'impact_reviewed',
                                 'rollback_plan_verified', 'health_check_ready'}),
    'rollback_deployment': frozenset({'target_scope_reviewed', 'impact_reviewed',
                                    'rollback_plan_verified', 'health_check_ready',
                                    'version_compatibility_verified', 'backup_restore_verified'}),
    'apply_allowed_config_change': frozenset({'target_scope_reviewed', 'impact_reviewed',
                                            'rollback_plan_verified', 'health_check_ready',
                                            'config_change_reviewed', 'backup_restore_verified'}),
})


@dataclass(frozen=True)
class ServiceScope:
    """Trusted service/action allowlists; no wildcard or arbitrary config patch."""
    actions: frozenset[str] = frozenset()
    rollback_versions: frozenset[str] = frozenset()
    config_changes: tuple[ConfigChange, ...] = ()

    def __post_init__(self):
        if set(self.actions) - set(PARAMETERS):
            raise ValueError('Unknown action in service policy')
        object.__setattr__(self, 'actions', frozenset(self.actions))
        object.__setattr__(self, 'rollback_versions', frozenset(validate_name(v) for v in self.rollback_versions))
        object.__setattr__(self, 'config_changes', tuple(
            ConfigChange.model_validate(c.model_dump() if isinstance(c, ConfigChange) else c)
            for c in self.config_changes))


class ControlledRegistry:
    """Registry is configured by trusted application code, never by the model."""
    def __init__(self, *, services: Mapping[str, ServiceScope],
                 adapters: Mapping[str, Callable], check_service_health: Callable | None):
        if set(adapters) - set(PARAMETERS):
            raise ValueError('Unknown remediation adapter')
        if any(not callable(adapter) for adapter in adapters.values()):
            raise ValueError('Adapters must be application callables')
        if check_service_health is not None and not callable(check_service_health):
            raise ValueError('Health adapter must be callable')
        self.services = MappingProxyType({validate_name(name): ServiceScope(
            actions=scope.actions, rollback_versions=scope.rollback_versions,
            config_changes=scope.config_changes) for name, scope in services.items()})
        self.adapters = MappingProxyType(dict(adapters))
        self.health_adapter = check_service_health

    def missing_requirements(self, proposal: ActionProposal, attestations: frozenset[str]) -> tuple[str, ...]:
        missing = set(REQUIREMENTS[proposal.action_type] - attestations)
        if proposal.action_type not in self.adapters:
            missing.add('action_not_registered')
        scope = self.services.get(proposal.service)
        if scope is None or proposal.action_type not in scope.actions:
            missing.add('service_out_of_scope')
        else:
            args = PARAMETERS[proposal.action_type].model_validate(proposal.parameters)
            if proposal.action_type == 'rollback_deployment' and args.version not in scope.rollback_versions:
                missing.add('version_not_allowed')
            if proposal.action_type == 'apply_allowed_config_change':
                # JSON comparison distinguishes booleans from integers (True != 1).
                encoded = args.change.model_dump_json()
                if encoded not in {change.model_dump_json() for change in scope.config_changes}:
                    missing.add('config_change_not_allowed')
        if self.health_adapter is None:
            missing.add('health_adapter_not_registered')
        return tuple(sorted(missing))

    def check_service_health(self, service: str) -> HealthResult:
        if service not in self.services or self.health_adapter is None:
            return HealthResult(service=service, status='unknown', details='Health check unavailable')
        try:
            raw = self.health_adapter(service)
            result = HealthResult.model_validate(raw.model_dump() if isinstance(raw, HealthResult) else raw)
            if result.service != service:
                raise ValueError('Wrong health target')
            return result
        except Exception:
            return HealthResult(service=service, status='unknown', details='Health check failed')


@dataclass
class _ActionRecord:
    proposal_json: str
    fingerprint: str
    readiness: frozenset[str] = frozenset()
    readiness_actor: str | None = None
    approval: ApprovalRecord | None = None
    suspended: bool = False
    attempted: bool = False
    result: ExecutionResult | None = None
    audit: list[dict] = field(default_factory=list)


class ExecutionBoundary:
    """Approval-bound, at-most-once adapter dispatch within this process."""
    def __init__(self, registry: ControlledRegistry, *, authorized_operators: frozenset[str]):
        self.registry = registry
        self._operators = frozenset(validate_name(actor) for actor in authorized_operators)
        self._records: dict[str, _ActionRecord] = {}
        self._disabled_services: set[str] = set()
        self._lock = RLock()

    def _record(self, action_id: str) -> _ActionRecord:
        if action_id not in self._records:
            raise BoundaryError('unknown_action_id')
        return self._records[action_id]

    def _operator(self, actor: str):
        if actor not in self._operators:
            raise BoundaryError('unauthorized_operator')

    def create_proposal(self, proposal: ActionProposal | dict) -> RemediationAction:
        # Revalidate model instances too; nested parameter dictionaries are mutable.
        proposal = ActionProposal.model_validate(proposal.model_dump() if isinstance(proposal, ActionProposal) else proposal)
        payload = json.dumps(proposal.model_dump(), sort_keys=True, separators=(',', ':'))
        fingerprint = hashlib.sha256(payload.encode()).hexdigest()
        with self._lock:
            if proposal.action_id in self._records:
                raise BoundaryError('duplicate_action_id')
            self._records[proposal.action_id] = _ActionRecord(payload, fingerprint)
            return self.action(proposal.action_id)

    def action(self, action_id: str) -> RemediationAction:
        with self._lock:
            record = self._record(action_id)
            proposal = ActionProposal.model_validate_json(record.proposal_json)
            missing = self.registry.missing_requirements(proposal, record.readiness)
            if proposal.service in self._disabled_services:
                missing = tuple(sorted(set(missing) | {'service_disabled'}))
            status = ApprovalStatus(record.approval.decision) if record.approval else ApprovalStatus.PENDING_APPROVAL
            eligible = not missing
            executable = eligible and status == ApprovalStatus.APPROVED and not record.suspended and not record.attempted
            return RemediationAction(**proposal.model_dump(), proposal_fingerprint=record.fingerprint,
                approval_status=status, approval_eligible=eligible, executable=executable,
                missing_requirements=missing)

    def attest_readiness(self, action_id: str, *, actor: str, satisfied_requirements: frozenset[str]) -> RemediationAction:
        """Trusted host assertion after real checks; never accept LLM attestations."""
        with self._lock:
            self._operator(actor)
            record = self._record(action_id)
            if record.attempted or (record.approval and record.approval.decision == 'REJECTED'):
                raise BoundaryError('action_closed')
            proposal = ActionProposal.model_validate_json(record.proposal_json)
            if set(satisfied_requirements) - REQUIREMENTS[proposal.action_type]:
                raise BoundaryError('unknown_readiness_requirement')
            record.readiness = frozenset(satisfied_requirements)
            record.readiness_actor = actor
            # Updating/revoking readiness invalidates any previous approval.
            record.approval = None
            record.audit.append({'event': 'readiness', 'actor': actor, 'requirements': sorted(record.readiness)})
            return self.action(action_id)

    def record_approval(self, decision: HumanDecision | dict) -> RemediationAction:
        decision = HumanDecision.model_validate(decision.model_dump() if isinstance(decision, HumanDecision) else decision)
        with self._lock:
            self._operator(decision.actor)
            record = self._record(decision.action_id)
            if record.attempted or record.approval is not None:
                raise BoundaryError('approval_already_decided')
            if decision.proposal_fingerprint != record.fingerprint:
                raise BoundaryError('stale_or_mismatched_approval')
            current = self.action(decision.action_id)
            if decision.decision == 'APPROVED' and not current.approval_eligible:
                raise BoundaryError('action_ineligible')
            record.approval = ApprovalRecord(**decision.model_dump(), recorded_at=datetime.now(timezone.utc).isoformat())
            record.audit.append({'event': 'human_decision', **record.approval.model_dump()})
            return self.action(decision.action_id)

    def suspend(self, action_id: str, *, actor: str):
        with self._lock:
            self._operator(actor)
            self._record(action_id).suspended = True

    def disable_service(self, service: str, *, actor: str):
        """Trusted emergency scope revocation, checked again at dispatch."""
        with self._lock:
            self._operator(actor)
            self._disabled_services.add(validate_name(service))

    def execute(self, action_id: str) -> ExecutionResult:
        """Only a stored ID is accepted, never caller-provided flags or commands."""
        if not isinstance(action_id, str):
            return ExecutionResult(action_id='', status='blocked', code='invalid_action_id')
        with self._lock:
            if action_id not in self._records:
                return ExecutionResult(action_id=action_id, status='blocked', code='unknown_action_id')
            record = self._record(action_id)
            try:
                proposal = ActionProposal.model_validate_json(record.proposal_json)
                action = self.action(action_id)
                args = PARAMETERS[proposal.action_type].model_validate(proposal.parameters)
            except (ValidationError, ValueError):
                return ExecutionResult(action_id=action_id, status='blocked', code='invalid_action')
            code = None
            if record.attempted:
                code = 'duplicate_execution'
            elif not action.approval_eligible:
                code = 'action_ineligible'
            elif action.approval_status != ApprovalStatus.APPROVED:
                code = 'approval_required'
            elif not action.executable:
                code = 'action_not_executable'
            elif record.approval.proposal_fingerprint != record.fingerprint:
                code = 'stale_or_mismatched_approval'
            if code:
                return ExecutionResult(action_id=action_id, service=proposal.service, status='blocked', code=code)
            # Reserve before calling an adapter, including exceptions/uncertain outcomes.
            record.attempted = True
            record.audit.append({'event': 'execution_reserved'})
            adapter = self.registry.adapters[proposal.action_type]
        try:
            if proposal.action_type == 'restart_service':
                raw = adapter(proposal.service)
            elif proposal.action_type == 'rollback_deployment':
                raw = adapter(proposal.service, args.version)
            else:
                raw = adapter(proposal.service, args.change)
            outcome = AdapterExecutionResult.model_validate(raw.model_dump() if isinstance(raw, AdapterExecutionResult) else raw)
            result = ExecutionResult(action_id=action_id, service=proposal.service,
                                     status=outcome.status, code='adapter_' + outcome.status)
        except Exception:
            result = ExecutionResult(action_id=action_id, service=proposal.service,
                                     status='unknown', code='adapter_error')
        with self._lock:
            record.result = result
            record.audit.append({'event': 'execution_result', **result.model_dump()})
        return result

    def audit(self, action_id: str) -> list[dict]:
        with self._lock:
            # Do not leak a mutable reference to authoritative records.
            return json.loads(json.dumps(self._record(action_id).audit))
