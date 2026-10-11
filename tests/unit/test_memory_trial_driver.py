"""Memory comparison dispatch retains the existing normal-entry boundaries."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import prepare_memory_trials as owner
from tests.unit.test_reload_trial_drivers import dispatch_inputs


def inputs(tmp_path, monkeypatch):
    trial, prepared, argv = dispatch_inputs(tmp_path)
    trial.update(task_ref=prepared['task_ref'], settings_ref=prepared['settings_ref'], memory_root=str(tmp_path / 'memory'),
                 pair_ref=owner.save(tmp_path / 'pair.json', {'snapshot_files': []}))
    prepared['preselection_ref'] = prepared['task_ref']
    monkeypatch.setattr(owner, 'FrozenExecution', lambda _: SimpleNamespace(verify_files=lambda: None, verify_loaded_modules=lambda: None))
    monkeypatch.setattr(owner, 'verify_memory_pair', lambda _: {'status': 'frozen_pair_intact'})
    return trial, prepared, argv


@pytest.mark.parametrize('damage', ['request', 'budget', 'permission', 'run_id', 'worker', 'memory', 'platform'])
def test_changed_dispatch_never_reaches_process(tmp_path, monkeypatch, damage):
    trial, prepared, argv = inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(owner, 'prepare_snapshot', lambda **_: pytest.fail('invalid dispatch froze'))
    monkeypatch.setattr(owner.subprocess, 'run', lambda *_a, **_k: pytest.fail('invalid dispatch executed'))
    if damage == 'request':
        argv[-1] = 'different request'
    elif damage == 'budget':
        argv[argv.index('--task-model-call-limit') + 1] = '99'
    elif damage == 'permission':
        argv.insert(-2, '--allow-game-launch')
    elif damage == 'run_id':
        argv[argv.index('--run-id') + 1] = '../../escape'
    elif damage == 'worker':
        path = Path(argv[argv.index('--patch-worker-config') + 1])
        value = json.loads(path.read_bytes())
        value['behavior_evaluator']['kwargs']['source_root'] = 'different'
        path.write_text(json.dumps(value))
    elif damage == 'memory':
        monkeypatch.setattr(owner, 'verify_memory_pair', lambda _: (_ for _ in ()).throw(ValueError('Frozen memory changed')))
    elif damage == 'platform':
        monkeypatch.setattr(owner, 'FrozenExecution', lambda _: SimpleNamespace(
            verify_files=lambda: (_ for _ in ()).throw(ValueError('Platform changed'))))
    with pytest.raises(ValueError):
        owner._executor(trial, prepared)(argv)


def test_allocated_normal_entry_keeps_exact_argv_and_failed_outcome(tmp_path, monkeypatch, capsys):
    trial, prepared, argv = inputs(tmp_path, monkeypatch)
    captured = {}
    def freeze(**kwargs):
        captured.update(kwargs)
        return owner.save(tmp_path / 'snapshot.json', {'fixture': True})
    monkeypatch.setattr(owner, 'prepare_snapshot', freeze)
    monkeypatch.setattr(owner.subprocess, 'run', lambda *_a, **_k: SimpleNamespace(returncode=2, stdout='partial\n', stderr='failure'))
    assert owner._executor(trial, prepared)(argv) == 2
    assert captured['business_argv'] == argv
    assert capsys.readouterr().out == 'partial\n'
    process = json.loads((Path(trial['root']) / 'product-process.json').read_bytes())
    assert process['exit_code'] == 2 and process['stderr'] == 'failure'
