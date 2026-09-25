import json
from pathlib import Path
from unittest.mock import Mock

from llm_reasoner.log_watcher import process_log_line, watch_docker_logs

ENTRY = dict(timestamp='2026-09-25T10:00:00.123Z', level='error',
             service='orders-api', message='PostgreSQL connection failed')


def line(**changes):
    return json.dumps({**ENTRY, **changes})


def test_info_is_ignored_without_delivery_or_investigation():
    publish=Mock(); investigate=Mock(); fetch=Mock()
    result=process_log_line(line(level='info'),api_base='http://api',
                            publisher=publish,incident_fetcher=fetch,investigator=investigate)
    assert result=={'status':'ignored'}
    publish.assert_not_called();fetch.assert_not_called();investigate.assert_not_called()


def test_error_is_forwarded_to_existing_backend_then_investigated():
    publish=Mock(return_value='created')
    fetch=Mock(return_value={**ENTRY,'incident_id':'INC-DEMO-001',
                             'status':'INVESTIGATING','analysis':None})
    investigate=Mock(return_value=Mock(final_status='DIAGNOSED'))
    result=process_log_line(line(),api_base='http://api',demo=True,
                            publisher=publish,incident_fetcher=fetch,investigator=investigate)
    assert result=={'status':'diagnosed','incident_id':'INC-DEMO-001','delivery':'created'}
    incident=publish.call_args.args[0]
    assert set(incident)=={'incident_id','timestamp','service','log_level','message',
                           'classification','status','analysis'}
    investigate.assert_called_once_with('INC-DEMO-001',api_base='http://api')


def test_replayed_event_does_not_repeat_completed_investigation():
    publish=Mock(return_value='already_delivered')
    fetch=Mock(return_value={**ENTRY,'incident_id':'INC-DEMO-001',
                             'status':'DIAGNOSED','analysis':{'status':'completed'}})
    investigate=Mock()
    result=process_log_line(line(),api_base='http://api',demo=True,
                            publisher=publish,incident_fetcher=fetch,investigator=investigate)
    assert result['status']=='already_processed'
    investigate.assert_not_called()


class FakeProcess:
    def __init__(self, lines):
        self.stdout=iter(lines);self.returncode=None;self.command=None
    def poll(self): return self.returncode
    def terminate(self): self.returncode=0
    def kill(self): self.returncode=-9
    def wait(self,timeout=None):
        if self.returncode is None:self.returncode=0
        return self.returncode


def test_docker_watcher_follows_only_new_logs_and_stops_after_incident(tmp_path):
    compose=tmp_path/'compose.yaml';compose.write_text('services: {}')
    process=FakeProcess([line(level='info')+'\n',line()+'\n'])
    calls=[]
    def popen(command,**kwargs):
        process.command=command;return process
    def processor(raw,**kwargs):
        calls.append((raw,kwargs))
        return {'status':'ignored'} if len(calls)==1 else {
            'status':'diagnosed','incident_id':'INC-DEMO-001','delivery':'created'}
    assert watch_docker_logs(compose_file=str(compose),service='orders-api',
        api_base='http://api',demo=True,once=True,popen=popen,processor=processor)==1
    assert process.command[:4]==['docker','compose','-f',str(compose.resolve())]
    assert '--follow' in process.command and '--since' in process.command
    assert process.command[-1]=='orders-api'
    assert calls[1][1]=={'api_base':'http://api','demo':True}
