"""Private backend worker using the existing approval boundary and workflow.

Only the authenticated backend spawns this worker. stdin is a trusted host message,
not an LLM tool. MongoDB reserves a decision/attempt before spawning execute; a
crash or uncertain result must never be replayed automatically.
"""
import json
import re
import subprocess
import sys
import time

import requests

from .bridge import incident_to_reasoning_request
from .remediation import ControlledRegistry, ExecutionBoundary, REQUIREMENTS, ServiceScope
from .remediation_contracts import ActionProposal, BoundaryError, HealthResult
from .remediation_workflow import RemediationWorkflow
from .schemas import ReasoningResponse

PROJECT = 'cloud-incident-copilot-demo'
ACTOR = 'demo-operator'
HEALTH_URL = 'http://127.0.0.1:18080/health'
PLAN = {
    'action': 'Start the existing stopped demo PostgreSQL container; do not recreate it.',
    'impact': 'Restores the database dependency for orders-api. No application deployment, configuration or volume changes.',
    'rollback': 'If recovery fails, stop this same demo container manually after review; retain its volume. No automatic rollback or retry.',
    'verification': 'Require PostgreSQL running and Docker healthy, then orders-api HTTP 200 with service=orders-api, status=healthy and database=healthy.',
}
REQUIRED_READINESS = REQUIREMENTS['restart_service']


class DemoDockerAdapter:
    def _run(self, args, timeout=5):
        return subprocess.run(['docker', *args], capture_output=True, text=True,
                              timeout=timeout, check=False)

    def snapshot(self):
        result = self._run(['ps', '-a', '--filter', f'label=com.docker.compose.project={PROJECT}',
                            '--filter', 'label=com.docker.compose.service=postgres', '--format', '{{.ID}}'])
        ids = result.stdout.split()
        if result.returncode or len(ids) != 1 or not re.fullmatch(r'[a-f0-9]{12,64}', ids[0]):
            raise BoundaryError('demo_container_unavailable')
        # Never inspect/return environment or raw daemon/provider exception text.
        template = '{"id":{{json .Id}},"state":{{json .State.Status}},"health":{{json .State.Health.Status}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}}}'
        result = self._run(['inspect', '--format', template, ids[0]])
        if result.returncode:
            raise BoundaryError('demo_container_unavailable')
        value = json.loads(result.stdout)
        if (value.get('project') != PROJECT or value.get('service') != 'postgres'
                or not re.fullmatch(r'[a-f0-9]{64}', value.get('id', ''))):
            raise BoundaryError('demo_scope_mismatch')
        return value

    def probe(self):
        try:
            response = requests.get(HEALTH_URL, timeout=3, allow_redirects=False)
            data = response.json()
            return {'http_status': response.status_code, **{
                k: data.get(k) for k in ('service', 'status', 'database')}}
        except Exception:
            return {'http_status': 0}

    def ready(self, container_id):
        checks = self.readiness(container_id)['checks']
        return checks['target_scope_reviewed'] and checks['health_check_ready']

    def readiness(self, container_id, proposal=None):
        """Verify each trusted-host requirement and report only proven facts."""
        try:
            state = self.snapshot()
        except Exception:
            state = None
        health = self.probe()
        checks = {
            'target_scope_reviewed': bool(state and state['id'] == container_id
                and state['project'] == PROJECT and state['service'] == 'postgres'
                and state['state'] == 'exited'),
            'impact_reviewed': bool(proposal
                and proposal.action_type == 'restart_service'
                and proposal.service == 'postgres' and proposal.parameters == {}
                and proposal.description == (
                    f'Start existing stopped PostgreSQL container {container_id} in {PROJECT}; '
                    'preserve volumes; verify orders-api health.')),
            # The trusted runbook fixes a manual stop rollback and volume retention.
            'rollback_plan_verified': PLAN['rollback'] == (
                'If recovery fails, stop this same demo container manually after review; '
                'retain its volume. No automatic rollback or retry.'),
            'health_check_ready': health == {
                'http_status': 503, 'service': 'orders-api',
                'status': 'unhealthy', 'database': 'unavailable'},
        }
        return {
            'checks': checks,
            'verified_requirements': sorted(name for name, verified in checks.items() if verified),
        }

    def start_stopped_postgres(self, service, container_id):
        if service != 'postgres' or not self.ready(container_id):
            return {'status': 'failed'}
        # Existing restart_service contract: stopped-service recovery is start,
        # never restart an already running DB. Only the fingerprint-bound ID.
        result = self._run(['start', container_id], timeout=15)
        return {'status': 'succeeded' if result.returncode == 0 else 'failed'}

    def verify(self, service, container_id, attempts=15):
        if service != 'postgres':
            return HealthResult(service=service, status='unknown', details='Target outside demo scope')
        for attempt in range(attempts):
            try:
                state = self.snapshot()
                health = self.probe()
                if (state['id'] == container_id and state['state'] == 'running' and state['health'] == 'healthy'
                        and health == {'http_status': 200, 'service': 'orders-api',
                                      'status': 'healthy', 'database': 'healthy'}):
                    return HealthResult(service='postgres', status='healthy',
                        details='PostgreSQL running and Docker healthy; orders-api HTTP 200, status=healthy, database=healthy.')
            except Exception:
                pass
            if attempt + 1 < attempts:
                time.sleep(1)
        return HealthResult(service='postgres', status='unhealthy',
                            details='Recovery verification did not confirm both PostgreSQL and orders-api healthy.')


def run_operation(payload, adapter=None, on_verifying=None):
    adapter = adapter or DemoDockerAdapter()
    if set(payload) - {'operation', 'incident', 'action_id', 'proposal', 'decision'}:
        raise BoundaryError('invalid_worker_request')
    incident = payload['incident']
    if incident.get('incident_id') != 'INC-DEMO-001' or incident.get('service') != 'orders-api':
        raise BoundaryError('incident_outside_demo_scope')
    request = incident_to_reasoning_request(incident)
    diagnosis = ReasoningResponse.model_validate(incident['analysis'])
    operation = payload['operation']
    if operation == 'prepare':
        snapshot = adapter.snapshot()
        container_id = snapshot['id']
        proposal = ActionProposal(action_id=payload['action_id'], incident_id=request.incident_id,
            action_type='restart_service', service='postgres', parameters={},
            description=f"Start existing stopped PostgreSQL container {container_id} in {PROJECT}; preserve volumes; verify orders-api health.")
    elif operation in {'readiness', 'execute'}:
        proposal = ActionProposal.model_validate(payload['proposal'])
        match = re.fullmatch(r'Start existing stopped PostgreSQL container ([a-f0-9]{64}) in '
                            + re.escape(PROJECT) + r'; preserve volumes; verify orders-api health\.', proposal.description)
        if not match or proposal.service != 'postgres' or proposal.action_type != 'restart_service' or proposal.parameters:
            raise BoundaryError('proposal_outside_demo_scope')
        container_id = match.group(1)
    else:
        raise BoundaryError('invalid_worker_operation')
    def verify(service):
        # Persist VERIFYING before health I/O. Failure to acknowledge fails closed.
        if on_verifying is not None:
            on_verifying(proposal.action_id)
        return adapter.verify(service, container_id)

    registry = ControlledRegistry(services={'postgres': ServiceScope(actions=frozenset({'restart_service'}))},
        adapters={'restart_service': lambda service: adapter.start_stopped_postgres(service, container_id)},
        check_service_health=verify)
    boundary = ExecutionBoundary(registry, authorized_operators=frozenset({ACTOR}))
    flow = RemediationWorkflow(incident=request, diagnosis=diagnosis, boundary=boundary, max_reinvestigations=0)
    flow.propose(proposal)
    readiness = None
    # Proposal creation deliberately remains BLOCKED. A separate authenticated
    # backend operation verifies and persists readiness for this fingerprint.
    if operation in {'readiness', 'execute'}:
        readiness = adapter.readiness(container_id, proposal)
        boundary.attest_readiness(proposal.action_id, actor=ACTOR,
            satisfied_requirements=frozenset(readiness['verified_requirements']))
        flow.refresh_eligibility()
    if operation == 'execute':
        # Never derive this decision from model recommendations or caller flags.
        flow.decide(payload['decision'])
        if payload['decision']['decision'] == 'APPROVED':
            flow.execute_approved()
    return {
        'proposal': proposal.model_dump(), 'action': boundary.action(proposal.action_id).model_dump(),
        'state': flow.state.value, 'history': [s.value for s in flow.history],
        'execution': flow.last_execution.model_dump() if flow.last_execution else None,
        'health': flow.last_health.model_dump() if flow.last_health else None,
        'failure_code': flow.failure_code, 'audit': boundary.audit(proposal.action_id),
        'plan': PLAN, 'readiness': readiness,
    }


def main():
    try:
        raw = sys.stdin.readline(262145)
        if len(raw) > 262144:
            raise ValueError
        def acknowledge_verifying(action_id):
            print(json.dumps({'event': 'VERIFYING', 'action_id': action_id}), flush=True)
            if sys.stdin.readline(128).strip() != 'VERIFICATION_PERSISTED':
                raise BoundaryError('verification_not_persisted')
        print(json.dumps(run_operation(json.loads(raw), on_verifying=acknowledge_verifying)), flush=True)
    except Exception:
        print(json.dumps({'error': 'remediation_worker_failed'}))
        sys.exit(1)


if __name__ == '__main__':
    main()
