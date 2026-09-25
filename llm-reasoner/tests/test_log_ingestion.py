import json
from unittest.mock import Mock, patch
import pytest
from llm_reasoner.log_ingestion import incident_from_line, publish_incident, IngestionError

ENTRY = dict(timestamp='2026-09-25T10:00:00.123Z', level='error', service='orders-api', message='PostgreSQL connection failed')
def line(**changes): return json.dumps({**ENTRY, **changes})

def test_shared_incident_contract_and_stable_replay_id():
    value=incident_from_line(line(raw_log='discard', metadata={'private':'discard'}, status='RESOLVED', executable=True))
    assert set(value)=={'incident_id','timestamp','service','log_level','message','classification','status','analysis'}
    assert value==incident_from_line(line())
    assert value['classification']=='ERROR' and value['log_level']=='error'
    assert value['status']=='INVESTIGATING' and value['analysis'] is None
    assert incident_from_line(line(timestamp='2026-09-25T15:30:00.123+05:30'))==value

@pytest.mark.parametrize('level',['debug','info','warn','warning'])
def test_normal_and_warning_logs_do_not_create_incidents(level):
    assert incident_from_line(line(level=level)) is None

@pytest.mark.parametrize('raw',['[]','broken', '{}', line(timestamp='2026-02-30T00:00:00Z'),line(timestamp='yesterday'),line(level='unknown'),line(message=23),line(service='bad/service'),line(message='password=do-not-store'),line(message='mongodb://credentials')])
def test_invalid_or_unsafe_logs_rejected(raw):
    with pytest.raises(IngestionError): incident_from_line(raw)

def test_demo_scope_cannot_be_selected_by_log_metadata():
    assert incident_from_line(line(incident_id='INC-DEMO-001'))['incident_id'].startswith('INC-LOG-')
    assert incident_from_line(line(),demo=True)['incident_id']=='INC-DEMO-001'
    with pytest.raises(IngestionError): incident_from_line(line(service='other'),demo=True)

def test_delivery_targets_existing_incident_api():
    value=incident_from_line(line())
    with patch('requests.post',return_value=Mock(status_code=201)) as post:
        assert publish_incident(value)=='created'
    assert post.call_args.args[0]=='http://localhost:3000/api/incidents'
    assert post.call_args.kwargs['json']==value

def test_retry_never_overwrites_progress_and_conflicts_fail():
    value=incident_from_line(line())
    with patch('requests.post',return_value=Mock(status_code=409)),patch('requests.get',return_value=Mock(status_code=200,json=lambda:{**value,'status':'RESOLVED'})):
        assert publish_incident(value)=='already_delivered'
    with patch('requests.post',return_value=Mock(status_code=409)),patch('requests.get',return_value=Mock(status_code=200,json=lambda:{**value,'message':'Different event'})):
        with pytest.raises(IngestionError): publish_incident(value)
