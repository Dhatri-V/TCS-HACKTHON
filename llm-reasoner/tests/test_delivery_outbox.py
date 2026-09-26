import json
import os
import stat
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from llm_reasoner.delivery_outbox import DeliveryOutbox, _fsync_directory
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


def test_default_outbox_uses_uid_scoped_owner_only_directories(tmp_path):
    with patch('llm_reasoner.delivery_outbox.tempfile.gettempdir', return_value=str(tmp_path)):
        outbox = DeliveryOutbox()
        outbox.enqueue(incident())
    assert outbox.directory.parent.name == f'cloud-incident-copilot-{os.getuid()}'
    assert outbox.directory.parent.stat().st_uid == os.getuid()
    assert stat.S_IMODE(outbox.directory.parent.stat().st_mode) == 0o700
    assert outbox.directory.stat().st_uid == os.getuid()
    assert stat.S_IMODE(outbox.directory.stat().st_mode) == 0o700


def test_outbox_fails_closed_when_directory_cannot_be_secured(tmp_path):
    outbox = DeliveryOutbox(tmp_path / 'outbox')
    with patch.object(type(outbox.directory), 'chmod', side_effect=OSError):
        with pytest.raises(IngestionError, match='unsafe_outbox_directory'):
            outbox.enqueue(incident())


def test_outbox_fails_closed_when_directory_has_different_owner(tmp_path):
    directory = tmp_path / 'outbox'
    directory.mkdir()
    with patch('llm_reasoner.delivery_outbox.os.getuid',
               return_value=os.getuid() + 1):
        with pytest.raises(IngestionError, match='unsafe_outbox_directory'):
            DeliveryOutbox(directory).read_pending()


def test_outbox_rejects_symlink_directory(tmp_path):
    target = tmp_path / 'target'
    target.mkdir()
    link = tmp_path / 'outbox'
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(IngestionError, match='unsafe_outbox_directory'):
        DeliveryOutbox(link).enqueue(incident())


def test_atomic_enqueue_fsyncs_containing_directory(tmp_path):
    outbox = DeliveryOutbox(tmp_path / 'outbox')
    with patch('llm_reasoner.delivery_outbox._fsync_directory',
               wraps=_fsync_directory) as sync_directory:
        outbox.enqueue(incident())
    sync_directory.assert_called_once_with(outbox.directory)


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


class EmptyProcess:
    stdout = iter(())
    returncode = 0
    def poll(self): return self.returncode
    def terminate(self): self.returncode = 0
    def kill(self): self.returncode = -9
    def wait(self, timeout=None): return self.returncode


def test_watcher_captures_log_watermark_before_outbox_replay(tmp_path):
    compose = tmp_path / 'compose.yaml'
    compose.write_text('services: {}')
    outbox = DeliveryOutbox(tmp_path / 'outbox')
    outbox.enqueue(incident())
    events = []
    class Clock:
        @classmethod
        def now(cls, zone):
            events.append('watermark')
            return datetime(2026, 9, 25, tzinfo=timezone.utc)
    def replay(*args, **kwargs):
        events.append('replay')
        return {'status': 'diagnosed', 'incident_id': 'INC-DEMO-001',
                'delivery': 'created'}
    with patch('llm_reasoner.log_watcher.datetime', Clock):
        assert watch_docker_logs(compose_file=str(compose), service='orders-api',
                                 api_base='http://api', once=True, outbox=outbox,
                                 pending_processor=replay,
                                 popen=Mock(side_effect=AssertionError)) == 1
    assert events == ['watermark', 'replay']


@pytest.mark.parametrize('code', ['incident_conflict', 'delivery_rejected'])
def test_permanently_rejected_queued_incident_is_discarded_with_safe_id(
        tmp_path, capsys, code):
    compose = tmp_path / 'compose.yaml'
    compose.write_text('services: {}')
    outbox = DeliveryOutbox(tmp_path / 'outbox')
    outbox.enqueue(incident())
    def reject(*args, **kwargs):
        raise IngestionError(code)
    assert watch_docker_logs(compose_file=str(compose), service='orders-api',
                             api_base='http://api', once=True, outbox=outbox,
                             pending_processor=reject,
                             popen=Mock(return_value=EmptyProcess())) == 0
    assert outbox.read_pending() == ([], 0)
    diagnostic = json.loads(capsys.readouterr().err.strip())
    assert diagnostic == {'watcher': 'outbox_discarded',
                          'incident_id': 'INC-DEMO-001', 'code': code}


def test_transient_queued_incident_is_retained_with_safe_diagnostic(tmp_path, capsys):
    compose = tmp_path / 'compose.yaml'
    compose.write_text('services: {}')
    outbox = DeliveryOutbox(tmp_path / 'outbox')
    outbox.enqueue(incident())
    def fail(*args, **kwargs):
        raise IngestionError('delivery_queued')
    watch_docker_logs(compose_file=str(compose), service='orders-api',
                      api_base='http://api', once=True, outbox=outbox,
                      pending_processor=fail,
                      popen=Mock(return_value=EmptyProcess()))
    assert outbox.read_pending()[0] == [incident()]
    diagnostic = json.loads(capsys.readouterr().err.strip())
    assert diagnostic == {'watcher': 'outbox_replay_failed',
                          'incident_id': 'INC-DEMO-001',
                          'code': 'delivery_queued'}


def test_tampered_outbox_record_is_never_replayed(tmp_path):
    outbox = DeliveryOutbox(tmp_path)
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / 'INC-DEMO-001.json').write_text(json.dumps({
        **incident(), 'token': 'must-not-be-accepted',
    }))
    assert outbox.read_pending() == ([], 1)
