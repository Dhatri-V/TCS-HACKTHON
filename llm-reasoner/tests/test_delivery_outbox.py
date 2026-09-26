import json
import stat
from unittest.mock import Mock

import pytest

from llm_reasoner.delivery_outbox import DeliveryOutbox
from llm_reasoner.log_ingestion import IngestionError, incident_from_line
from llm_reasoner.log_watcher import process_incident, watch_docker_logs


def incident():
    return incident_from_line(json.dumps({
        'timestamp': '2026-09-25T10:00:00.123Z',
        'level': 'error',
        'service': 'orders-api',
        'message': 'PostgreSQL connection failed',
    }), demo=True)


def test_outbox_persists_only_sanitized_incident_contract(tmp_path):
    outbox = DeliveryOutbox(tmp_path / 'outbox')
    value = incident()
    outbox.enqueue(value)
    files = list(outbox.directory.glob('*.json'))
    assert len(files) == 1
    assert json.loads(files[0].read_text()) == value
    assert stat.S_IMODE(files[0].stat().st_mode) == 0o600
    assert stat.S_IMODE(outbox.directory.stat().st_mode) == 0o700
    stored = json.loads(files[0].read_text())
    assert not ({'api_base', 'authorization', 'token', 'headers', 'raw_log'} & set(stored))
    pending, invalid = outbox.read_pending()
    assert pending == [value] and invalid == 0


def test_transient_delivery_is_retried_then_processed_without_queue(tmp_path):
    outbox = DeliveryOutbox(tmp_path)
    publish = Mock(side_effect=[IngestionError('delivery_failed'), 'created'])
    fetch = Mock(return_value={**incident(), 'status': 'DIAGNOSED', 'analysis': {}})
    sleep = Mock()
    result = process_incident(incident(), api_base='http://api', publisher=publish,
                              incident_fetcher=fetch, investigator=Mock(), outbox=outbox,
                              retry_delay=0.25, sleeper=sleep)
    assert result['delivery'] == 'created'
    assert publish.call_count == 2
    sleep.assert_called_once_with(0.25)
    assert outbox.read_pending() == ([], 0)


def test_exhausted_delivery_is_durably_queued_without_credentials(tmp_path):
    outbox = DeliveryOutbox(tmp_path)
    publish = Mock(side_effect=IngestionError('delivery_failed'))
    with pytest.raises(IngestionError, match='delivery_queued'):
        process_incident(incident(), api_base='http://operator:secret@api',
                         publisher=publish, outbox=outbox,
                         delivery_attempts=3, retry_delay=0, sleeper=Mock())
    assert publish.call_count == 3
    pending, invalid = outbox.read_pending()
    assert pending == [incident()] and invalid == 0
    assert 'secret' not in next(tmp_path.glob('*.json')).read_text()


def test_non_retryable_conflict_is_not_queued(tmp_path):
    outbox = DeliveryOutbox(tmp_path)
    publish = Mock(side_effect=IngestionError('incident_conflict'))
    with pytest.raises(IngestionError, match='incident_conflict'):
        process_incident(incident(), api_base='http://api', publisher=publish,
                         outbox=outbox, sleeper=Mock())
    publish.assert_called_once()
    assert outbox.read_pending() == ([], 0)


def test_watcher_replays_outbox_before_opening_docker_stream(tmp_path):
    compose = tmp_path / 'compose.yaml'
    compose.write_text('services: {}')
    outbox = DeliveryOutbox(tmp_path / 'outbox')
    outbox.enqueue(incident())
    popen = Mock(side_effect=AssertionError('Docker stream must not open'))
    pending_processor = Mock(return_value={
        'status': 'diagnosed', 'incident_id': 'INC-DEMO-001', 'delivery': 'created',
    })
    assert watch_docker_logs(compose_file=str(compose), service='orders-api',
                             api_base='http://api', demo=True, once=True,
                             popen=popen, pending_processor=pending_processor,
                             outbox=outbox) == 1
    popen.assert_not_called()
    pending_processor.assert_called_once()


def test_tampered_outbox_record_is_never_replayed(tmp_path):
    outbox = DeliveryOutbox(tmp_path)
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / 'INC-DEMO-001.json').write_text(json.dumps({
        **incident(), 'token': 'must-not-be-accepted',
    }))
    assert outbox.read_pending() == ([], 1)
