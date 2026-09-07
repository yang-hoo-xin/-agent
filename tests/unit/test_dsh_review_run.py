"""Human diff view uses exact retained outputs without executing the task."""
import json
import socket
from pathlib import Path

import pytest

from scripts.dsh_review_run import review_run
from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.fresh_planning_continuation import (
    _canonical_sha256,
    run_fresh_patch_continuation,
)
from src.mod_agent.local_entry import make_exact_no_write_dry_run_factory
from tests.unit.test_fresh_planning_continuation import (
    _inputs,
    _local_patch_adapter,
    _patch_request,
)


@pytest.fixture
def case(tmp_path):
    inputs = _inputs(tmp_path)
    adapter, _ = _local_patch_adapter(inputs)  # Existing deterministic unit provider, no network.
    result = run_fresh_patch_continuation(_patch_request(inputs), patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace))
    assert result.status == 'terminal'
    return inputs, result, {'artifact_store_root': str(inputs.store.root.resolve()),
        'workspace_root': str(inputs.workspace.resolve()), 'feature_id': result.feature_id, 'run_id': result.run_id}


def _snapshot(root):
    return {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_exact_success_diff_review_and_current_source_are_read_only(case, tmp_path, monkeypatch):
    inputs, completed, config = case
    before = _snapshot(tmp_path)
    monkeypatch.setattr(socket.socket, 'connect', lambda *a: pytest.fail('No network in review'))
    monkeypatch.setattr(ArtifactStore, 'write', lambda *a, **k: pytest.fail('No Artifact writes in review'))
    result = review_run(**config)
    assert result['status'] == 'reviewable_diff', result
    dry = json.loads(Path(completed.dry_run_artifact['path']).read_text(encoding='utf-8'))['data']
    assert result['unified_diff'] == dry['unified_diff'] and result['diff_hash'] == dry['diff_hash']
    assert result['source_currentness']['status'] == 'matches_original_baseline'
    assert result['source_currentness']['diff_recomputed_matches'] is True
    assert result['original_review']['decision'] == 'approve_dry_run'
    assert result['apply_allowed'] is False and result['approval_created'] is False
    assert result['query_model_calls'] == result['query_verifier_executions'] == 0
    assert _snapshot(tmp_path) == before


def test_failed_attempt_does_not_borrow_feature_latest_or_its_parent_diff(case, tmp_path):
    inputs, completed, config = case
    path = Path(completed.attempt_receipt['path'])
    journal = json.loads(path.read_text(encoding='utf-8'))
    journal['run_id'] = 'failed-with-no-new-output'
    journal['proposal_admitted'] = False
    journal['repair_context'] = {'parent_proposal': journal['artifacts']['patch_proposal']}
    journal['artifacts'] = {}
    journal['terminal_result'].update(status='partial', patch_proposal_artifact=None,
        proposal_review_artifact=None, dry_run_artifact=None)
    journal['terminal_result_sha256'] = _canonical_sha256(journal['terminal_result'])
    (path.parent/'failed-view.json').write_text(json.dumps(journal), encoding='utf-8')
    before = _snapshot(tmp_path)
    result = review_run(**{**config, 'run_id': journal['run_id']})
    assert result['status'] == 'no_reviewable_diff' and result['unified_diff'] is None
    assert result['artifacts'] == {} and result['reason'] == 'THIS_RUN_HAS_NO_NEW_PROPOSAL'
    assert _snapshot(tmp_path) == before


def test_source_drift_is_visible_beside_original_diff_without_apply_claim(case, tmp_path):
    inputs, completed, config = case
    dry = json.loads(Path(completed.dry_run_artifact['path']).read_text(encoding='utf-8'))['data']
    source = inputs.workspace / dry['changes'][0]['path']
    source.write_bytes(source.read_bytes()+b'\n// source changed after original dry run\n')
    before = _snapshot(tmp_path)
    result = review_run(**config)
    assert result['status'] == 'reviewable_diff' and result['unified_diff'] == dry['unified_diff']
    assert result['source_currentness']['status'] == 'source_changed'
    assert result['source_currentness']['first_difference']['path'] == dry['changes'][0]['path']
    assert result['source_currentness']['first_difference']['matches'] is False
    assert result['apply_allowed'] is False and _snapshot(tmp_path) == before


@pytest.mark.parametrize('damage', ['proposal', 'terminal', 'cross_run_refs'])
def test_broken_current_artifact_or_terminal_identity_cannot_display_diff(case, damage):
    _, completed, config = case
    journal_path = Path(completed.attempt_receipt['path'])
    journal = json.loads(journal_path.read_text(encoding='utf-8'))
    if damage == 'proposal':
        Path(completed.patch_proposal_artifact['path']).write_text('{}', encoding='utf-8')
    elif damage == 'terminal':
        journal['terminal_result_sha256'] = '0'*64
        journal_path.write_text(json.dumps(journal), encoding='utf-8')
    else:
        journal['artifacts']['patch_proposal'] = dict(journal['artifacts']['proposal_review'])
        journal_path.write_text(json.dumps(journal), encoding='utf-8')
    result = review_run(**config)
    assert result['status'] == 'review_unavailable' and result['unified_diff'] is None


def test_configured_feature_and_exact_run_are_required(case):
    _, _, config = case
    for change in ({'feature_id':'another_feature'}, {'run_id':'--artifact-store-root=elsewhere'}):
        with pytest.raises(ValueError, match='RUN_NOT_UNIQUE_OR_MISSING'):
            review_run(**{**config, **change})
