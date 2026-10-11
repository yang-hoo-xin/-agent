"""The clarification helper must use formal acceptance inside canonical delivery."""
import json
from types import SimpleNamespace

import pytest

from scripts import deliver_clarification_notice as helper
from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.evaluation import isolated_delivery_adapter as adapter
from tests.unit.test_isolated_delivery_adapter import _save


@pytest.mark.parametrize('outcome', ['passed', 'failed', 'exception'])
def test_helper_cannot_publish_delivered_before_formal_result(tmp_path, monkeypatch, outcome):
    root = tmp_path / 'run'
    target = root / 'target'
    target.mkdir(parents=True)
    (target / 'Plugin.dll').write_bytes(b'formal fixture')
    checkpoint = ArtifactRef(feature_id='f', artifact_type='workflow_checkpoint', path=str(root / 'cp.json'), artifact_hash='a' * 64)
    initial = {'run_id': 'run', 'request_id': 'request', 'feature_id': 'f', 'diff_hash': 'b' * 64, 'unified_diff': 'diff'}
    context = {'run_root': str(root), 'trial': {'delivery': {'final_acceptance_required': True}}}
    checked = {'run_root': root, 'initial': initial, 'store': SimpleNamespace(root=root / 'a',
        semantic_read_immutable=lambda _: {'data': {'artifact_refs': []}}), 'checkpoint': checkpoint,
        'config': {'policy_id': 'fixture', 'final_acceptance_required': True},
        'verification_report_ref': _save(root / 'verification.json', {'status': 'passed'}),
        'required_check_ids': ['case'], 'initial_ref': _save(root / 'run_result.json', initial),
        'manifest_ref': _save(root / 'run_manifest.json', {}), 'verifier_identity_binding': None,
        'profile': None, 'target': target, 'expected_artifact': 'Plugin.dll'}
    prepared = {'base': tmp_path, 'root': root, 'initial': initial, 'context': context, 'checked': checked,
        'worker_ref': {'fixture': True}, 'ready_ref': {'fixture': True}, 'report_ref': checked['verification_report_ref']}
    monkeypatch.setattr(helper, 'prepare_notice', lambda **_: prepared)
    monkeypatch.setattr(adapter, 'prepare_delivery', lambda _: checked)
    monkeypatch.setattr(adapter, 'prepare_task_delegation', lambda **_: {'path': 'fixture', 'sha256': 'c' * 64})
    cp = {key: getattr(checkpoint, key) for key in ('feature_id', 'artifact_type', 'path', 'artifact_hash')}
    monkeypatch.setattr(adapter, 'resume_deferred_approval', lambda **_: {'status': 'applied_in_isolation', 'workflow_checkpoint': cp})
    monkeypatch.setattr(adapter, 'continue_reviewed_patch', lambda **_: {'status': 'built'})
    monkeypatch.setattr('src.mod_agent.evaluation.task_measurement.measure_product_task', lambda **_: {})
    monkeypatch.setattr('src.mod_agent.evaluation.tool_effects.extract_tool_effects', lambda _: {})
    monkeypatch.setattr('src.mod_agent.evaluation.product_trial_batch.verify_product_model_proposal', lambda *a: {'fixture': True})
    def verify(assembly):
        assert not (root / 'delivery/result.json').exists()
        assert (root / 'delivery/build.json').exists()
        if outcome == 'exception':
            raise ValueError('formal failure')
        return {'status': outcome, 'assembly_ref': assembly, 'checks': [{'check_id': 'case', 'passed': outcome == 'passed'}]}
    monkeypatch.setattr(helper, 'formal_verifier', lambda _: verify)
    result_ref = helper.deliver_notice(ready_path='fixture', run_id='run')
    canonical = json.loads((root / 'delivery/result.json').read_bytes())
    assert canonical == json.loads(open(result_ref['path'], encoding='utf-8').read())
    assert canonical['delivery_complete'] is (outcome == 'passed')
    assert canonical['status'] == ('delivered' if outcome == 'passed' else 'failed')
