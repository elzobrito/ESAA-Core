import json
import os
import subprocess
import sys
from esaa.validator import validate_file_update_resource_limits
from esaa.errors import ESAAError
import pytest


def test_file_limit_with_defaults_and_explicit_ceiling():
    file = [{'path': 'x', 'content': 'ááá'}]
    task = {'resource_limits': {'max_bytes_per_update': 5}}
    with pytest.raises(ESAAError, match='max_bytes_per_update'):
        validate_file_update_resource_limits(file, {}, task)
    validate_file_update_resource_limits(file, {}, {'resource_limits': {'max_bytes_per_update': 6}})
    with pytest.raises(ESAAError, match='ceiling'):
        validate_file_update_resource_limits(file, {}, {'resource_limits': {'max_bytes_per_update': 2097153}})


def test_rejected_submission_never_writes_output(tmp_path):
    def run(*args):
        return subprocess.run([sys.executable, '-B', '-m', 'esaa', '--root', str(tmp_path), *args], env=dict(os.environ), text=True, capture_output=True)
    for args in [('bootstrap',), ('init',), ('task', 'create', 'A', '--kind', 'impl', '--title', 'A', '--max-file-bytes', '4'), ('claim', 'A', '--actor', 'agent-impl')]:
        p=run(*args); assert p.returncode==0, p.stdout+p.stderr
    updates=tmp_path/'updates.json';updates.write_text(json.dumps([{'path':'src/test.txt','content':'12345'}]))
    p=run('complete','A','--actor','agent-impl','--check','one','--check','two','--file-updates',str(updates))
    assert p.returncode!=0
    assert not (tmp_path/'src/test.txt').exists()
    assert json.loads(run('state','A').stdout)['task']['status']=='in_progress'


def test_policy_changed_between_validation_and_commit_is_rejected(tmp_path, monkeypatch):
    import yaml
    from esaa.bootstrap import bootstrap_workspace
    from esaa.service import ESAAService
    bootstrap_workspace(tmp_path)
    svc=ESAAService(tmp_path); svc.init()
    svc.create_task('A',task_kind='impl',title='A',resource_limits={'max_bytes_per_update':4})
    svc.submit({'activity_event':{'action':'claim','task_id':'A','prior_status':'todo'}},actor='agent-impl')
    orig=svc._append_events_transactionally
    def change_policy(*args,**kwargs):
        path=tmp_path/'.roadmap/RUNTIME_POLICY.yaml';policy=yaml.safe_load(path.read_text())
        policy['resource_limits']={'max_file_updates':32,'max_bytes_per_update':3,'max_bytes_total':8388608}
        path.write_text(yaml.safe_dump(policy))
        return orig(*args,**kwargs)
    monkeypatch.setattr(svc,'_append_events_transactionally',change_policy)
    payload={'activity_event':{'action':'complete','task_id':'A','prior_status':'in_progress','verification':{'checks':['one','two']}},'file_updates':[{'path':'src/x.txt','content':'1234'}]}
    with pytest.raises(ESAAError): svc.submit(payload,actor='agent-impl')
    assert not (tmp_path/'src/x.txt').exists()
    assert svc.task_state('A')['task']['status']=='in_progress'


def test_batch_revalidation_checks_all_tasks_against_current_policy(tmp_path):
    from esaa.bootstrap import bootstrap_workspace
    from esaa.service import ESAAService
    from esaa.store import parse_event_store
    from esaa.submission import _revalidate_limits_under_lock
    bootstrap_workspace(tmp_path); svc=ESAAService(tmp_path); svc.init()
    svc.create_task('A',task_kind='impl',title='A',resource_limits={'max_bytes_per_update':4})
    svc.create_task('B',task_kind='impl',title='B',resource_limits={'max_bytes_per_update':2})
    a=svc.task_state('A')['task']; b=svc.task_state('B')['task']
    updates=[(a,[{'path':'src/a','content':'1234'}]),(b,[{'path':'src/b','content':'123'}])]
    with pytest.raises(ESAAError,match='max_bytes_per_update'):
        _revalidate_limits_under_lock(tmp_path,parse_event_store(tmp_path),updates,{})
    updates[1][1][0]['content']='12'
    _revalidate_limits_under_lock(tmp_path,parse_event_store(tmp_path),updates,{})
