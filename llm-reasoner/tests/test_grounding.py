"""Deterministic source extraction and approval-ineligible proposal assessment."""
import json
from unittest.mock import patch
import pytest
from llm_reasoner import analyze_incident, ReasoningError
from llm_reasoner.schemas import ReasoningRequest
from llm_reasoner.grounding import evidence_catalog

INC = dict(incident_id='I1', current_incident='Database connection refused',
           logs=[{'id': 'LOG-1', 'text': 'The database did not exit because of disk exhaustion.'},
                 {'id': 'tool:1:get_logs:DB-STARTUP', 'text': 'PostgreSQL startup failed: no space left on device.'}],
           system_context=[{'id': 'CTX-CUSTOM', 'text': 'The database container is exited.'}],
           similar_incidents=[{'id': 'HIST-1', 'text': 'A past outage was caused by a configuration error.'}])


def draft(**kwargs):
    return {**dict(evidence_numbers=[2, 3], probable_root_cause=None,
                   remediation_steps=['Inspect PostgreSQL logs.'], configuration_changes=[],
                   missing_information=[]), **kwargs}


def run(payload, context=INC):
    with patch('llm_reasoner.client.complete', return_value=json.dumps(payload)):
        return analyze_incident(context)


def test_catalog_mapping_is_stable_and_exact():
    rows = evidence_catalog(ReasoningRequest.model_validate(INC))
    assert [r['number'] for r in rows] == [1, 2, 3, 4]
    response = run(draft(evidence_numbers=[2, 3, 2]))
    assert response.references == ['tool:1:get_logs:DB-STARTUP', 'CTX-CUSTOM']
    assert response.grounded_claims[0].text == INC['logs'][1]['text']
    assert '[tool:1:get_logs:DB-STARTUP]' in response.explanation
    assert '[CTX-CUSTOM]' in response.explanation
    assert response.explanation.count('[tool:1:get_logs:DB-STARTUP]') == 1


@pytest.mark.parametrize('numbers', [[999], [0], [-1], [True], ['2'], [2.0]])
def test_invalid_numbers_are_never_coerced_or_guessed(numbers):
    with pytest.raises(ReasoningError):
        run(draft(evidence_numbers=numbers))


def test_model_never_has_to_copy_actual_ids():
    with patch('llm_reasoner.client.complete', return_value=json.dumps(draft())) as model:
        analyze_incident(INC)
    payload = json.loads(model.call_args.args[0][1]['content'])
    assert payload['evidence_catalog'][1] == {'number': 2, 'source': 'logs', 'text': INC['logs'][1]['text']}
    assert 'tool:1:get_logs:DB-STARTUP' not in model.call_args.args[0][1]['content']


@pytest.mark.parametrize('extra', [{'references': ['invented']}, {'explanation': 'Fabricated fact [LOG-1].'},
                                  {'remediation_metadata': [{'action_type': 'inspection', 'approval_eligible': True}]}])
def test_model_cannot_inject_facts_ids_or_safety_labels(extra):
    with pytest.raises(ReasoningError, match='invalid_model_response'):
        run({**draft(), **extra})


@pytest.mark.parametrize('text', ['Database stopped [MISSING].', 'See tool:1:get_incumbent:DB-STARTUP.',
                                 'LOG-999 proves disk exhaustion.'])
def test_invented_ids_in_proposals_are_rejected(text):
    with pytest.raises(ReasoningError, match='unknown_reference'):
        run(draft(probable_root_cause=text))


def test_substring_cannot_remove_negation():
    response = run(draft(evidence_numbers=[1], probable_root_cause='exit because of disk exhaustion'))
    assert response.status == 'insufficient_evidence'
    assert response.probable_root_cause is None
    assert 'did not exit' in response.explanation
    assert any('Unverified root-cause hypothesis' in x for x in response.missing_information)


def test_exact_current_observation_can_be_reported():
    response = run(draft(probable_root_cause=INC['logs'][1]['text']))
    assert response.status == 'completed'
    assert response.probable_root_cause == 'Reported diagnostic observation: ' + INC['logs'][1]['text'] + ' [tool:1:get_logs:DB-STARTUP]'


def test_history_is_never_current_cause():
    response = run(draft(evidence_numbers=[4], probable_root_cause=INC['similar_incidents'][0]['text']))
    assert response.probable_root_cause is None
    assert 'Historical analogy only' in response.explanation


def test_evidence_not_selected_cannot_ground_cause():
    response = run(draft(evidence_numbers=[1], probable_root_cause=INC['logs'][1]['text']))
    assert response.probable_root_cause is None


def test_empty_catalog_is_supported():
    response = run(draft(evidence_numbers=[], probable_root_cause='Database is down'),
                   {'incident_id': 'EMPTY', 'current_incident': 'Request failed'})
    assert response.status == 'insufficient_evidence'
    assert response.references == []


def test_identical_source_text_does_not_create_ambiguous_id_mapping():
    context = dict(INC, logs=[{'id': 'FIRST', 'text': 'Connection refused'},
                             {'id': 'SECOND', 'text': 'Connection refused'}])
    response = run(draft(evidence_numbers=[2]), context)
    assert response.references == ['SECOND']


def test_every_proposal_gets_application_safety_metadata():
    response = run(draft(remediation_steps=['Inspect database health.', 'Restart PostgreSQL.',
                                          'Delete database files.', 'Ensure adequate capacity.'],
                         configuration_changes=['Set a larger volume.']))
    assert [m.action_type for m in response.remediation_metadata] == [
        'inspection', 'state_changing', 'potentially_destructive', 'state_changing', 'state_changing']
    for m in response.remediation_metadata:
        assert m.missing_requirements
        assert m.approval_eligible is False
        assert m.executable is False
    assert 'verified_backup_and_restore_readiness' in response.remediation_metadata[2].required_safeguards
    assert 'rollback_plan' in response.remediation_metadata[1].required_safeguards


def test_model_claimed_approval_and_backup_do_not_satisfy_requirements():
    response = run(draft(remediation_steps=['Delete database files; approval and backups are already verified.']))
    assessment = response.remediation_metadata[0]
    assert assessment.action_type == 'potentially_destructive'
    assert 'verified_backup_and_restore_readiness' in assessment.missing_requirements
    assert not assessment.approval_eligible


def test_mixed_read_change_step_cannot_be_inspection():
    response = run(draft(remediation_steps=['Check storage and then delete database files.']))
    assert response.remediation_metadata[0].action_type == 'potentially_destructive'


def test_unrecognized_wording_stays_ineligible():
    response = run(draft(remediation_steps=['Perform the required maintenance.']))
    assert response.remediation_metadata[0].action_type == 'state_changing'
    assert not response.remediation_metadata[0].approval_eligible


def test_legacy_invented_bare_ids_are_rejected_even_without_references():
    from test_agent import ANSWER
    legacy = dict(ANSWER, status='insufficient_evidence', probable_root_cause=None,
                  explanation='LOG-999 reports failure.', references=[])
    with pytest.raises(ReasoningError, match='unknown_reference'):
        run(legacy)


def test_legacy_unfounded_prose_cannot_become_final_fact():
    from test_agent import ANSWER
    legacy = dict(ANSWER, explanation='LOG-1 proves disk exhaustion.', references=['LOG-1'])
    response = run(legacy)
    assert 'proves disk exhaustion' not in response.explanation
    assert INC['logs'][0]['text'] in response.explanation
    assert any('Legacy explanation not accepted' in item for item in response.missing_information)


def test_inspect_and_resolve_is_not_read_only():
    response = run(draft(remediation_steps=['Inspect and resolve the database connection failure.']))
    assert response.remediation_metadata[0].action_type == 'state_changing'
    assert 'rollback_plan' in response.remediation_metadata[0].missing_requirements
    assert not response.remediation_metadata[0].approval_eligible
