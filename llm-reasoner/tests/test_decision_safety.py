"""Decision gaps, inline citations and non-executable recommendation metadata."""
import json
from unittest.mock import Mock, patch
import pytest
from llm_reasoner import analyze_incident, investigate_incident, ReasoningError
from llm_reasoner.schemas import Analysis
from test_agent import INC, ANSWER, decision, result

@pytest.mark.parametrize('gap', [None, '', '   ', 'more'])
def test_tool_without_material_gap_never_dispatches(gap):
    tool = Mock()
    raw = {'action': 'get_logs', 'arguments': {'query': 'Database startup errors'},
           'reason': 'Investigate', 'information_gap': gap}
    with patch('llm_reasoner.client.complete', return_value=json.dumps(raw)):
        with pytest.raises(ReasoningError, match='invalid_agent_decision'):
            investigate_incident(INC, {'get_logs': tool})
    tool.assert_not_called()


def test_finalize_cannot_claim_unresolved_tool_gap():
    raw = {'action': 'finalize', 'arguments': {}, 'reason': 'Done',
           'information_gap': 'What is the current database service health?'}
    with patch('llm_reasoner.client.complete', return_value=json.dumps(raw)):
        with pytest.raises(ReasoningError, match='invalid_agent_decision'):
            investigate_incident(INC, {})


def test_explicit_finalize_after_observation_has_no_guard_stop():
    tool = Mock(return_value=result())
    with patch('llm_reasoner.client.complete', side_effect=[
        decision('get_logs', query='Database startup errors'), decision(), json.dumps(ANSWER)]):
        response = investigate_incident(INC, {'get_logs': tool})
    tool.assert_called_once()
    assert not any('Investigation stopped' in x for x in response.missing_information)


def test_bracketed_citation_and_reference_agree():
    answer = dict(ANSWER, explanation='Connection attempts were refused [L1].')
    with patch('llm_reasoner.client.complete', return_value=json.dumps(answer)):
        assert analyze_incident(INC).references == ['L1']


@pytest.mark.parametrize('explanation,refs,code', [
    ('Connection refused [FAKE].', ['L1'], 'unknown_reference'),
    ('Connection refused [L1].', [], 'missing_references'),
    ('Connection refused.', ['L1'], 'unattributed_references'),
])
def test_invalid_citation_pairs_rejected(explanation, refs, code):
    answer = dict(ANSWER, explanation=explanation, references=refs)
    with patch('llm_reasoner.client.complete', return_value=json.dumps(answer)):
        with pytest.raises(ReasoningError, match=code):
            analyze_incident(INC)


def metadata(kind='state_changing', **overrides):
    return dict(source='remediation_steps', index=0, action_type=kind,
                preconditions=['An authorized operator has reviewed the affected service and maintenance impact.'],
                safeguards=['Verify a recoverable backup and approve the exact affected target before proceeding.'],
                verification=['Confirm service health and application connectivity after the reviewed change.'], **overrides)


def test_legacy_inspection_retains_text_and_gains_metadata():
    answer = Analysis.model_validate(ANSWER)
    assert answer.remediation_steps == ANSWER['remediation_steps']
    assert answer.remediation_metadata[0].action_type == 'inspection'


@pytest.mark.parametrize('text', ['Restart PostgreSQL.', 'Delete old database files.', 'Ensure adequate capacity.'])
def test_legacy_changes_without_safety_are_rejected(text):
    with patch('llm_reasoner.client.complete', return_value=json.dumps(dict(ANSWER, remediation_steps=[text]))):
        with pytest.raises(ReasoningError, match='invalid_model_response'):
            analyze_incident(INC)


@pytest.mark.parametrize('text,kind', [
    ('Inspect the PostgreSQL status.', 'inspection'),
    ('Restart PostgreSQL after approved maintenance review.', 'state_changing'),
    ('Delete explicitly approved disposable files after backup verification.', 'potentially_destructive'),
])
def test_structured_classifications(text, kind):
    answer = Analysis.model_validate(dict(ANSWER, remediation_steps=[text], remediation_metadata=[metadata(kind)]))
    assert answer.remediation_metadata[0].action_type == kind


@pytest.mark.parametrize('field,value', [('preconditions', []), ('safeguards', []), ('verification', []), ('safeguards', ['none'])])
def test_destructive_safety_details_are_required(field, value):
    item = metadata('potentially_destructive')
    item[field] = value
    with pytest.raises(ValueError):
        Analysis.model_validate(dict(ANSWER, remediation_steps=['Delete old database files.'], remediation_metadata=[item]))


@pytest.mark.parametrize('text,kind', [
    ('Restart PostgreSQL.', 'inspection'),
    ('Check storage then delete database files.', 'inspection'),
    ('Delete database files.', 'state_changing'),
])
def test_model_cannot_downgrade_obvious_action_risk(text, kind):
    with pytest.raises(ValueError):
        Analysis.model_validate(dict(ANSWER, remediation_steps=[text], remediation_metadata=[metadata(kind)]))


@pytest.mark.parametrize('indices', [[0, 0], [1]])
def test_metadata_indices_must_match_recommendations(indices):
    items = []
    for index in indices:
        item = metadata('inspection')
        item['index'] = index
        items.append(item)
    with pytest.raises(ValueError):
        Analysis.model_validate(dict(ANSWER, remediation_metadata=items))


def test_configuration_changes_require_safety_too():
    with pytest.raises(ValueError):
        Analysis.model_validate(dict(ANSWER, configuration_changes=['Set a larger storage volume.']))


def test_decision_schema_requires_all_fields_for_real_model():
    from llm_reasoner.agent import Decision
    for branch in Decision.model_json_schema()['anyOf']:
        assert set(branch['required']) == {'action', 'arguments', 'reason', 'information_gap'}
        props = branch['properties']
        if props['action']['const'] == 'finalize':
            assert props['information_gap']['const'] == ''
        else:
            assert props['information_gap']['minLength'] == 10
            assert props['arguments']['additionalProperties'] is False


@pytest.mark.parametrize('missing', ['arguments', 'information_gap'])
def test_omitted_decision_field_never_dispatches(missing):
    tool = Mock()
    raw = json.loads(decision('get_logs', query='Database startup errors'))
    raw.pop(missing)
    with patch('llm_reasoner.client.complete', return_value=json.dumps(raw)):
        with pytest.raises(ReasoningError, match='invalid_agent_decision'):
            investigate_incident(INC, {'get_logs': tool})
    tool.assert_not_called()
