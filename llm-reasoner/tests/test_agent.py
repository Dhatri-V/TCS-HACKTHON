import json
from unittest.mock import Mock, patch
import pytest
from llm_reasoner import investigate_incident, ReasoningError
from llm_reasoner.agent import Decision
from llm_reasoner.schemas import Analysis, DiagnosisDraft
from llm_reasoner.tools import ToolResult

INC = {"incident_id": "I1", "current_incident": "Database connection refused",
       "logs": [{"id": "L1", "text": "Connection refused"}]}
ANSWER = {"status": "completed", "probable_root_cause": "Database may be unavailable",
          "explanation": "L1 reports connection refusal", "references": ["L1"],
          "remediation_steps": ["Verify service health"], "configuration_changes": [],
          "missing_information": ["Current service health"]}

def decision(action="finalize", **arguments):
    return json.dumps({"action": action, "arguments": arguments, "reason": "Investigate missing facts", "information_gap": "" if action == "finalize" else "What additional evidence establishes the current database failure cause?"})

def result(text="Database health unknown"):
    return {"status": "ok", "evidence": [{"id": "E1", "text": text}]}

def run(sequence, tools=None, answer=ANSWER):
    with patch("llm_reasoner.client.complete", side_effect=sequence + [json.dumps(answer)]) as llm:
        response = investigate_incident(INC, tools or {})
        return response, llm

def test_immediate_finalization():
    tool = Mock()
    response, llm = run([decision()], {"get_logs": tool})
    tool.assert_not_called()
    assert response.incident_id == "I1"
    assert llm.call_args_list[0].kwargs['response_schema'] is Decision
    assert llm.call_args_list[1].kwargs == {'response_schema': DiagnosisDraft}

@pytest.mark.parametrize('name,args', [
    ('get_incident_context', {'fields': ['service_health']}),
    ('retrieve_similar_incidents', {'query': 'database unavailable'}),
    ('get_logs', {'query': 'database errors'})])
def test_select_tool_and_validate_arguments(name, args):
    tool = Mock(return_value=result())
    response, llm = run([decision(name, **args), decision()], {name: tool})
    tool.assert_called_once()
    assert tool.call_args.args[0] == 'I1'
    observed = json.loads(llm.call_args_list[1].args[0][1]['content'])
    assert observed['observations'][0]['evidence'][0]['id'] == f'tool:1:{name}:E1'
    assert response.status == 'insufficient_evidence'
    assert any('Unverified root-cause hypothesis' in item for item in response.missing_information)

def test_observation_changes_next_decision():
    context = Mock(return_value=result('Service status unknown; inspect startup logs'))
    logs = Mock(return_value=result('Startup failed'))
    def model(messages, **kwargs):
        if kwargs.get('response_schema') is not Decision:
            return json.dumps(ANSWER)
        payload = json.loads(messages[1]['content'])
        obs = payload['observations']
        if not obs:
            return decision('get_incident_context', fields=['service_health'])
        if len(obs) == 1:
            assert 'inspect startup logs' in obs[0]['evidence'][0]['text']
            return decision('get_logs', query='startup')
        return decision()
    with patch('llm_reasoner.client.complete', side_effect=model):
        investigate_incident(INC, {'get_incident_context': context, 'get_logs': logs})
    context.assert_called_once(); logs.assert_called_once()

def test_tool_exception_is_observation_not_evidence():
    tool = Mock(side_effect=RuntimeError('secret traceback'))
    response, llm = run([decision('get_logs', query='startup'), decision()], {'get_logs': tool})
    payload = json.loads(llm.call_args_list[1].args[0][1]['content'])
    assert payload['observations'][0] == {'tool': 'get_logs', 'status': 'error', 'arguments': {'query': 'startup', 'limit': 20}, 'evidence': []}
    final_input = json.loads(llm.call_args_list[-1].args[0][1]['content'])
    assert final_input == {'incident_id': INC['incident_id'], 'current_incident': INC['current_incident'],
                           'evidence_catalog': [{'number': 1, 'source': 'logs', 'text': 'Connection refused'}]}
    assert 'secret' not in str(response)
    assert any('did not provide' in x for x in response.missing_information)

@pytest.mark.parametrize('raw', [decision('delete_database'), decision('get_logs', query='x', incident_id='other'), decision('get_logs', query='x', limit=1000), 'not json'])
def test_invalid_decision_never_executes(raw):
    tool = Mock()
    with patch('llm_reasoner.client.complete', return_value=raw):
        with pytest.raises(ReasoningError, match='invalid_agent_decision'):
            investigate_incident(INC, {'get_logs': tool})
    tool.assert_not_called()

def test_unregistered_tool_rejected():
    with patch('llm_reasoner.client.complete', return_value=decision('get_logs', query='x')):
        with pytest.raises(ReasoningError, match='invalid_agent_decision'):
            investigate_incident(INC, {})

def test_repeat_stops_without_second_execution():
    tool = Mock(return_value=result())
    action = decision('get_logs', query='same')
    response, _ = run([action, action], {'get_logs': tool})
    tool.assert_called_once()
    assert any('repeated_call' in x for x in response.missing_information)

def test_budget_stops_at_three():
    tool = Mock(return_value=result())
    response, llm = run([decision('get_logs', query=str(i)) for i in range(3)], {'get_logs': tool})
    assert tool.call_count == 3
    assert llm.call_count == 4
    assert any('budget' in x for x in response.missing_information)

def test_tool_evidence_can_be_cited():
    eid = 'tool:1:get_logs:E1'
    answer = dict(ANSWER, explanation=eid + ' reports failed startup', references=[eid])
    response, _ = run([decision('get_logs', query='startup'), decision()],
                      {'get_logs': Mock(return_value=result())}, answer)
    assert response.references == [eid]

def test_fabricated_citation_rejected():
    with pytest.raises(ReasoningError, match='unknown_reference'):
        run([decision()], answer=dict(ANSWER, references=['invented']))

def test_insufficient_evidence_preserved():
    response, _ = run([decision()], answer=dict(ANSWER, status='insufficient_evidence',
                         probable_root_cause=None, explanation='More facts needed', references=[]))
    assert response.status == 'insufficient_evidence'

def test_failure_envelope_cannot_supply_evidence():
    with pytest.raises(ValueError):
        ToolResult.model_validate(dict(result(), status='error'))
