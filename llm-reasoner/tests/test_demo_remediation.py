import json
from unittest.mock import Mock, patch
import pytest
from llm_reasoner.demo_remediation import DemoDockerAdapter, run_operation, PROJECT
from llm_reasoner.remediation_contracts import ActionProposal, BoundaryError, HealthResult

CID = 'a' * 64
INCIDENT = dict(incident_id='INC-DEMO-001', service='orders-api', message='PostgreSQL connection failed',
    analysis=dict(incident_id='INC-DEMO-001', status='insufficient_evidence', probable_root_cause=None,
        explanation='Current database state needs verification.', remediation_steps=[], configuration_changes=[],
        references=[], missing_information=[], grounded_claims=[], remediation_metadata=[]))


def adapter():
    a = Mock()
    a.snapshot.return_value = dict(id=CID, state='exited', health='unhealthy', project=PROJECT, service='postgres')
    a.ready.return_value = True
    a.readiness.return_value = dict(checks={name: True for name in (
        'target_scope_reviewed', 'impact_reviewed', 'rollback_plan_verified', 'health_check_ready')},
        verified_requirements=['health_check_ready', 'impact_reviewed',
                               'rollback_plan_verified', 'target_scope_reviewed'])
    a.start_stopped_postgres.return_value = {'status': 'succeeded'}
    a.verify.return_value = HealthResult(service='postgres', status='healthy', details='Live checks passed')
    return a


def prepare(a):
    return run_operation(dict(operation='prepare', incident=INCIDENT, action_id='ACTION-1'), a)

def check_readiness(p, a):
    return run_operation(dict(operation='readiness', incident=INCIDENT, proposal=p['proposal']), a)


def execute_payload(p, decision='APPROVED'):
    return dict(operation='execute', incident=INCIDENT, proposal=p['proposal'], decision=dict(
        action_id='ACTION-1', proposal_fingerprint=p['action']['proposal_fingerprint'], actor='demo-operator', decision=decision))


def test_preparation_never_executes():
    a=adapter(); p=prepare(a)
    assert p['state'] == 'BLOCKED'
    assert not p['action']['executable']
    assert p['readiness'] is None
    a.start_stopped_postgres.assert_not_called(); a.verify.assert_not_called()


def test_complete_existing_workflow_lifecycle():
    a=adapter(); p=prepare(a); pending=check_readiness(p,a)
    assert pending['state']=='PENDING_APPROVAL'
    assert pending['readiness']['verified_requirements'] == [
        'health_check_ready', 'impact_reviewed',
        'rollback_plan_verified', 'target_scope_reviewed']
    assert pending['action']['missing_requirements'] == ()
    result=run_operation(execute_payload(pending), a)
    assert result['history'] == ['DIAGNOSED','PROPOSED','BLOCKED','PENDING_APPROVAL','APPROVED','EXECUTING','VERIFYING','RESOLVED']
    a.start_stopped_postgres.assert_called_once_with('postgres', CID)
    a.verify.assert_called_once_with('postgres', CID)
    assert not result['action']['executable']
    assert any(x['event']=='human_decision' for x in result['audit'])


def test_rejection_no_execution():
    a=adapter(); result=run_operation(execute_payload(check_readiness(prepare(a),a),'REJECTED'),a)
    assert result['state']=='REJECTED'
    a.start_stopped_postgres.assert_not_called()


@pytest.mark.parametrize('change', [{'actor':'model'}, {'proposal_fingerprint':'0'*64}, {'action_id':'OTHER'}])
def test_untrusted_or_stale_decision(change):
    a=adapter(); payload=execute_payload(prepare(a));payload['decision'].update(change)
    with pytest.raises(BoundaryError): run_operation(payload,a)
    a.start_stopped_postgres.assert_not_called()


def test_missing_approval():
    a=adapter(); payload=execute_payload(prepare(a)); del payload['decision']
    with pytest.raises(KeyError): run_operation(payload,a)
    a.start_stopped_postgres.assert_not_called()


def test_changed_live_preconditions_block():
    a=adapter(); p=prepare(a);a.readiness.return_value={
        'checks': {'target_scope_reviewed': False, 'impact_reviewed': True,
                   'rollback_plan_verified': True, 'health_check_ready': False},
        'verified_requirements': ['impact_reviewed', 'rollback_plan_verified']}
    with pytest.raises(BoundaryError): run_operation(execute_payload(p),a)
    a.start_stopped_postgres.assert_not_called()


@pytest.mark.parametrize('status',['failed','unknown'])
def test_execution_failure_never_verifies_or_resolves(status):
    a=adapter();p=prepare(a);a.start_stopped_postgres.return_value={'status':status}
    result=run_operation(execute_payload(p),a)
    assert result['state']=='FAILED'; assert 'RESOLVED' not in result['history']
    a.verify.assert_not_called()


@pytest.mark.parametrize('status',['unhealthy','unknown'])
def test_failed_verification_never_resolves(status):
    a=adapter();p=prepare(a);a.verify.return_value=HealthResult(service='postgres',status=status)
    result=run_operation(execute_payload(p),a)
    assert result['state']=='FAILED';assert 'VERIFYING' in result['history']
    assert 'RESOLVED' not in result['history']


@pytest.mark.parametrize('change',[{'service':'redis'},{'action_type':'rollback_deployment','parameters':{'version':'v1'}},
    {'description':'Run any command'},{'parameters':{'command':'anything'}},{'incident_id':'OTHER'}])
def test_proposal_scope_immutable(change):
    a=adapter(); payload=execute_payload(prepare(a));payload['proposal'].update(change)
    with pytest.raises((ValueError,BoundaryError)):run_operation(payload,a)
    a.start_stopped_postgres.assert_not_called()


def test_docker_command_is_exact_and_no_shell():
    a=DemoDockerAdapter()
    with patch.object(a,'ready',return_value=True), patch('subprocess.run',return_value=Mock(returncode=0)) as run:
        assert a.start_stopped_postgres('postgres',CID)=={'status':'succeeded'}
    run.assert_called_once_with(['docker','start',CID],capture_output=True,text=True,timeout=15,check=False)


def test_running_or_wrong_service_never_started():
    a=DemoDockerAdapter()
    with patch.object(a,'ready',return_value=False),patch.object(a,'_run') as run:
        assert a.start_stopped_postgres('postgres',CID)=={'status':'failed'}
        assert a.start_stopped_postgres('redis',CID)=={'status':'failed'}
    run.assert_not_called()


def test_snapshot_reads_only_safe_fields_and_validates_labels():
    a=DemoDockerAdapter()
    value=dict(id=CID,state='exited',health='unhealthy',project=PROJECT,service='postgres')
    with patch.object(a,'_run',side_effect=[Mock(returncode=0,stdout=CID[:12]),Mock(returncode=0,stdout=json.dumps(value))]) as run:
        assert a.snapshot()==value
    assert '.Config.Env' not in str(run.call_args_list)
    value['project']='other'
    with patch.object(a,'_run',side_effect=[Mock(returncode=0,stdout=CID[:12]),Mock(returncode=0,stdout=json.dumps(value))]):
        with pytest.raises(BoundaryError):a.snapshot()


@pytest.mark.parametrize('http,status,database,docker_health',[(503,'unhealthy','unavailable','healthy'),(200,'healthy','unavailable','healthy'),(200,'healthy','healthy','unhealthy')])
def test_verification_requires_all_health_signals(http,status,database,docker_health):
    a=DemoDockerAdapter()
    with patch.object(a,'snapshot',return_value=dict(id=CID,state='running',health=docker_health)),patch.object(a,'probe',return_value=dict(http_status=http,service='orders-api',status=status,database=database)):
        assert a.verify('postgres',CID,attempts=1).status=='unhealthy'


def test_successful_live_health_shape():
    a=DemoDockerAdapter()
    with patch.object(a,'snapshot',return_value=dict(id=CID,state='running',health='healthy')),patch.object(a,'probe',return_value=dict(http_status=200,service='orders-api',status='healthy',database='healthy')):
        assert a.verify('postgres',CID,attempts=1).status=='healthy'


def test_health_exception_sanitized():
    a=DemoDockerAdapter()
    with patch('requests.get',side_effect=RuntimeError('sensitive detail')):
        assert a.probe()=={'http_status':0}


def test_readiness_attests_only_concretely_verified_requirements():
    a=DemoDockerAdapter()
    state=dict(id=CID,state='exited',health='unhealthy',project=PROJECT,service='postgres')
    with patch.object(a,'snapshot',return_value=state), patch.object(a,'probe',return_value={
            'http_status':503,'service':'orders-api','status':'unhealthy','database':'unavailable'}):
        readiness=a.readiness(CID, ActionProposal.model_validate(prepare(adapter())['proposal']))
    assert set(readiness['verified_requirements']) == {
        'target_scope_reviewed','impact_reviewed','rollback_plan_verified','health_check_ready'}
    with patch.object(a,'snapshot',return_value={**state,'state':'running'}), patch.object(a,'probe',return_value={
            'http_status':200,'service':'orders-api','status':'healthy','database':'healthy'}):
        readiness=a.readiness(CID, ActionProposal.model_validate(prepare(adapter())['proposal']))
    assert readiness['checks']['target_scope_reviewed'] is False
    assert readiness['checks']['health_check_ready'] is False
    assert set(readiness['verified_requirements']) == {'impact_reviewed','rollback_plan_verified'}


def test_verification_acknowledgement_before_health():
    a=adapter();p=prepare(a);events=[]
    def progress(action_id):
        a.start_stopped_postgres.assert_called_once()
        a.verify.assert_not_called()
        events.append(action_id)
    assert run_operation(execute_payload(p),a,on_verifying=progress)['state']=='RESOLVED'
    assert events==['ACTION-1']


def test_failed_progress_persistence_never_resolves():
    a=adapter();p=prepare(a)
    def progress(action_id): raise RuntimeError('persistence unavailable')
    result=run_operation(execute_payload(p),a,on_verifying=progress)
    assert result['state']=='FAILED'
    a.verify.assert_not_called()
