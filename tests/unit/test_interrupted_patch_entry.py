"""The public resume bridge never replays a claimed segment or trusts a changed result."""
import json

import pytest

from src.mod_agent import interrupted_patch_continuation as owner
from src.mod_agent.model_qualification import canonical_hash


def claimed(tmp_path, *, completed):
    root = tmp_path / 'run'
    segment = root / 'continuations/ip-scope'
    segment.mkdir(parents=True)
    config = {'selection': {
        'source_attempt_ref': {'path': str(root / 'attempt.json'), 'sha256': 'a' * 64},
        'parent_manifest_ref': {'path': str(root / 'run_manifest.json'), 'sha256': 'b' * 64},
        'execution_stop_ref': {'path': str(root / 'stop.json'), 'sha256': 'c' * 64}}}
    result = {'status': 'awaiting_approval', 'model_call_count': 8, 'actual_write_performed': False}
    output = segment / 'run_result.json'
    if completed:
        output.write_text(json.dumps(result))
    record = {'status': 'recorded' if completed else 'claimed', 'result_path': str(output),
        'recovery_config_sha256': canonical_hash(config), 'model_call_budget': {'consumed': 8, 'remaining': 4}}
    if completed:
        record['result_ref'] = owner._ref(output)
    (root / 'continuations' / ('interrupted-' + 'a' * 24 + '.json')).write_text(json.dumps(record))
    return root, config, output, result


def test_repeat_returns_recorded_result_without_admission_or_model(tmp_path, monkeypatch):
    root, config, _, result = claimed(tmp_path, completed=True)
    monkeypatch.setattr(owner, 'prepare_interrupted_patch', lambda **_: pytest.fail('repeated execution'))
    assert owner.resume_interrupted_patch(run_root=root, run_id='run', execution_config='not-read', recovery_config=config) == result


def test_missing_terminal_is_not_treated_as_permission_to_restart(tmp_path, monkeypatch):
    root, config, _, _ = claimed(tmp_path, completed=False)
    monkeypatch.setattr(owner, 'prepare_interrupted_patch', lambda **_: pytest.fail('restarted incomplete segment'))
    result = owner.resume_interrupted_patch(run_root=root, run_id='run', execution_config='not-read', recovery_config=config)
    assert result['status'] == 'interrupted_continuation_incomplete'
    assert result['automatic_execution_started'] is False
    assert result['model_call_budget']['consumed'] == 8


def test_result_tampering_is_not_reported_as_delivery(tmp_path):
    root, config, output, _ = claimed(tmp_path, completed=True)
    output.write_text('{"status":"delivered"}')
    with pytest.raises(ValueError, match='RECORDED_RESULT_CHANGED'):
        owner.resume_interrupted_patch(run_root=root, run_id='run', execution_config='not-read', recovery_config=config)


def test_changed_selection_configuration_cannot_claim_existing_remaining_budget(tmp_path):
    root, config, _, _ = claimed(tmp_path, completed=False)
    config['maximum_seconds'] = 3600
    with pytest.raises(ValueError, match='ALREADY_CLAIMED_WITH_OTHER_INPUT'):
        owner.resume_interrupted_patch(run_root=root, run_id='run', execution_config='not-read', recovery_config=config)


@pytest.mark.parametrize('damage', ['path', 'hash', 'unknown'])
def test_invalid_recovery_reference_is_rejected_before_claim_lookup(tmp_path, damage):
    root, config, _, _ = claimed(tmp_path, completed=False)
    if damage == 'path':
        config['selection']['source_attempt_ref']['path'] = '../attempt.json'
    elif damage == 'hash':
        config['selection']['source_attempt_ref']['sha256'] = '../../other'
    else:
        config['skip_approval'] = True
    with pytest.raises(ValueError, match='RECOVERY_'):
        owner.resume_interrupted_patch(run_root=root, run_id='run', execution_config='not-read', recovery_config=config)
