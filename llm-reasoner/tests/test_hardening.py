"""Regression checks for contracts, investigation efficiency and attribution."""
import json
from unittest.mock import Mock, patch
import pytest
from llm_reasoner import investigate_incident, analyze_incident, ReasoningError
from llm_reasoner.tools import LogsArgs, RetrievalArgs
from test_agent import INC, ANSWER, decision, result, run

@pytest.mark.parametrize('action,args', [
    ('get_logs', {'query': 'SELECT * FROM logs'}),
    ('get_logs', {'query': 'print("logs")'}),
    ('get_logs', {'query': 'sudo cat /var/log/app'}),
    ('get_incident_context', {'fields': ['db-state']}),
    ('retrieve_similar_incidents', {'query': 'database refusal', 'limit': 3}),
    ('retrieve_similar_incidents', {'query': 'database refusal', 'k': 6}),
    ('retrieve_similar_incidents', {'query': 'database refusal', 'k': True}),
])
def test_bad_contract_rejected_before_dispatch(action, args):
    tool = Mock()
    with patch('llm_reasoner.client.complete', return_value=decision(action, **args)):
        with pytest.raises(ReasoningError, match='invalid_agent_decision'):
            investigate_incident(INC, {action: tool})
    tool.assert_not_called()


def test_retrieval_contract_reaches_adapter():
    tool = Mock(return_value=result())
    run([decision('retrieve_similar_incidents', query='PostgreSQL connection refusal', k=2, service='db'), decision()],
        {'retrieve_similar_incidents': tool})
    assert tool.call_args.args[1].model_dump() == {'query': 'PostgreSQL connection refusal', 'k': 2, 'service': 'db'}
    assert RetrievalArgs(query='database refusal').service is None


def test_technical_natural_language_is_allowed():
    assert LogsArgs(query='PostgreSQL connection failures (ECONNREFUSED) at db:5432').limit == 20


def test_context_subset_is_not_executed_again():
    tool = Mock(return_value=result())
    response, _ = run([decision('get_incident_context', fields=['storage', 'service_health']),
                       decision('get_incident_context', fields=['service_health'])], {'get_incident_context': tool})
    tool.assert_called_once()
    assert any('redundant_context' in s for s in response.missing_information)


def test_context_overlap_only_fetches_new_fields():
    tool = Mock(return_value=result())
    _, llm = run([decision('get_incident_context', fields=['service_health']),
                  decision('get_incident_context', fields=['storage', 'service_health']), decision()],
                 {'get_incident_context': tool})
    assert [c.args[1].fields for c in tool.call_args_list] == [['service_health'], ['storage']]
    payload = json.loads(llm.call_args_list[1].args[0][1]['content'])
    assert payload['collected_context_fields'] == ['service_health']


@pytest.mark.parametrize('first', [{'status': 'unavailable'}, {'status': 'ok', 'evidence': []}])
def test_missing_context_does_not_mark_fields_collected(first):
    tool = Mock(side_effect=[first, result()])
    run([decision('get_incident_context', fields=['service_health']),
         decision('get_incident_context', fields=['storage', 'service_health']), decision()],
        {'get_incident_context': tool})
    assert tool.call_args_list[1].args[1].fields == ['service_health', 'storage']


def test_query_case_and_whitespace_repeat_is_blocked():
    tool = Mock(return_value=result())
    response, _ = run([decision('get_logs', query='Database startup errors'),
                       decision('get_logs', query='database   STARTUP errors')], {'get_logs': tool})
    tool.assert_called_once()
    assert any('repeated_call' in s for s in response.missing_information)


def test_distinct_log_followup_is_allowed():
    tool = Mock(return_value=result())
    run([decision('get_logs', query='Database startup errors'),
         decision('get_logs', query='Application connection errors'), decision()], {'get_logs': tool})
    assert tool.call_count == 2


def test_prompt_encourages_evidence_based_early_stop():
    _, llm = run([decision()])
    prompt = llm.call_args_list[0].args[0][0]['content']
    assert 'Select finalize as soon as current evidence supports' in prompt
    assert 'not a reason to continue' in prompt


def test_listed_reference_requires_inline_attribution():
    answer = dict(ANSWER, explanation='The database may be down.')
    with patch('llm_reasoner.client.complete', return_value=json.dumps(answer)):
        with pytest.raises(ReasoningError, match='unattributed_references'):
            analyze_incident(INC)


def test_tool_fact_has_exact_source_citation():
    eid = 'tool:1:get_logs:DB-STARTUP'
    context = dict(INC, logs=INC['logs'] + [{'id': eid, 'text': 'PostgreSQL startup failed: no space left on device'}])
    answer = dict(ANSWER, explanation=f'{eid} reports storage exhaustion during startup; L1 reports connection refusal.', references=[eid, 'L1'])
    with patch('llm_reasoner.client.complete', return_value=json.dumps(answer)):
        assert analyze_incident(context).references == [eid, 'L1']


def test_invented_inline_tool_reference_is_rejected():
    answer = dict(ANSWER, explanation=ANSWER['explanation'] + ' tool:9:get_logs:FAKE reports disk full.')
    with patch('llm_reasoner.client.complete', return_value=json.dumps(answer)):
        with pytest.raises(ReasoningError, match='unknown_reference'):
            analyze_incident(INC)


def test_prompt_requires_provenance_and_change_safeguards():
    from llm_reasoner.prompts import SYSTEM_PROMPT
    for text in ['application copies selected records', 'Recommend inspection first',
                 'requires trusted preconditions/safeguards', 'No safety metadata is requested']:
        assert text in SYSTEM_PROMPT
