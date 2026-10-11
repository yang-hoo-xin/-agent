"""Outer-trial outcome boundaries with controlled process receipts, no model runs."""
from pathlib import Path

import pytest

from scripts import run_context_online_ab as module


def setup(tmp_path, monkeypatch, *, agent_code=0, accepted=True, over_deadline=False):
    workspace = tmp_path / 'workspace'
    source = workspace / 'source'
    source.mkdir(parents=True)
    (source / 'Program.cs').write_text('initial', encoding='utf-8')
    output = tmp_path / 'output'
    ready = {'records_root': str(output / 'records')}
    trial = {'trial_id': 's2b1', 'task_id': 'S2', 'arm': 'baseline', 'repeat': 1,
        'workspace': str(workspace), 'source_audit_root': str(source), 'output_root': str(output),
        'ready_ref': {'path': str(tmp_path / 'ready.json'), 'sha256': 'synthetic'},
        'allowed_source_paths': ['Program.cs'],
        'acceptance_command': ['accept', '{deadline_monotonic_seconds}', '{remaining_seconds}'],
        'acceptance_result_path': str(output / 'acceptance.json')}
    snapshot = tmp_path / 'snapshot.json'
    module.save(snapshot, {'snapshot_root': str(tmp_path / 'snapshot')})
    registered = {'trial_id': 's2b1', 'trial_ref': {'path': 'synthetic-trial', 'sha256': 'synthetic'}}
    protocol = {'trials': [registered], 'wall_seconds': 900, 'platform_snapshot_ref': module.ref(snapshot)}
    monkeypatch.setattr(module, 'checked_trial', lambda *a, **k: (protocol, registered, trial, ready))
    monkeypatch.setattr(module, 'product_references', lambda *a: {})
    now = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    calls = []
    def execute(command, **kwargs):
        calls.append((command, kwargs))
        if len(calls) == 1:
            now[0] = 500.0
            return {'exit_code': agent_code, 'timeout': False}
        module.save(Path(trial['acceptance_result_path']), {'delivery_complete': accepted})
        if over_deadline:
            now[0] = 1001.0
        return {'exit_code': 0, 'timeout': False}
    monkeypatch.setattr(module, 'execute', execute)
    return calls


def test_formal_delivery_reuses_original_deadline(tmp_path, monkeypatch):
    calls = setup(tmp_path, monkeypatch)
    result = module.read(module.run({'path': 'synthetic-protocol', 'sha256': 'synthetic'}, 's2b1'))
    assert result['success'] is True and result['status'] == 'completed'
    assert calls[0][1]['deadline'] == calls[1][1]['deadline'] == 1000
    assert calls[1][0] == ['accept', '1000.0', '500.0']


@pytest.mark.parametrize('agent_code,accepted,over_deadline', [(2, True, False), (0, False, False), (0, True, True)])
def test_exit_partial_checks_or_late_acceptance_cannot_become_success(tmp_path, monkeypatch, agent_code, accepted, over_deadline):
    calls = setup(tmp_path, monkeypatch, agent_code=agent_code, accepted=accepted, over_deadline=over_deadline)
    result = module.read(module.run({'path': 'synthetic-protocol', 'sha256': 'synthetic'}, 's2b1'))
    assert result['success'] is False
    assert len(calls) == (1 if agent_code else 2)
    assert result['source_before'] == result['source_after_acceptance']
