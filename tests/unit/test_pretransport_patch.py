"""Pre-transport recovery admits only original terminal facts and retains cost."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from src.mod_agent import interrupted_patch_continuation as entry
from src.mod_agent.pretransport_patch_admission import admit_pretransport_patch
from src.mod_agent.saved_patch_admission import _hash
from tests.unit.test_interrupted_patch_admission import interrupted  # noqa: F401
from tests.unit.test_saved_patch_admission import _save


@pytest.fixture
def failed(interrupted):  # noqa: F811
    data = interrupted
    journal, manifest = data['journal'], data['manifest']
    budget = {'maximum': 18, 'consumed': 3, 'remaining': 15, 'policy': 'task_total_only',
        'count_basis': 'reserved_provider_invocations_not_transport_proof',
        'by_stage': {kind: {'consumed': count} for kind, count in
            {'requirement_projection': 1, 'requirement_findings': 1, 'planning': 1, 'initial_patch': 0, 'repair': 0}.items()}}
    factory = journal['factory_receipt']
    factory.update(status='failed', failure={'message': 'payload path before send'}, model_call_count=0,
        provider_request=None, model_response=None, model_responses=[], worker_turns=[],
        model_call_budget={'maximum_total_model_calls': 15},
        patch_agent_loop={'status': 'not_started', 'policy': {**factory['patch_agent_loop']['policy'], 'max_total_model_turns': 15}})
    journal.update(status='product_execution_finished', model_call_count=0, max_model_calls=15,
        shared_model_budget=budget, terminal_result={'parent_execution_disposition': 'partial', 'owner_effect_invocations': {'isolated_apply': 0}})
    journal['terminal_result_sha256'] = _hash(journal['terminal_result'])
    manifest.update(model_call_count=3, execution_observations={role: {'name': 'model.request', 'attributes': {'model_role': role}}
        for role in ('requirement_projection', 'requirement_findings', 'planning')})
    data['result'] = {'run_id': manifest['run_id'], 'model_call_count': 3, 'model_call_budget': budget,
        'actual_write_performed': False, 'local_model_identity': manifest['local_model_identity'],
        'product_execution_result': {'execution_disposition': 'partial', 'request_id': manifest['request_id']},
        'blockers': [{'stage': 'generate_patch_proposal_execution', 'code': 'PRODUCT_NODE_EXECUTION_FAILED', 'source_node': 'generate_patch_proposal'}],
        'artifacts': {key: row['path'] for key, row in journal['selected_artifacts'].items()}}
    data['selection'] = {'execution_config_ref': _save(data['root'] / 'execution.json', {})}
    save_failed(data)
    return data


def save_failed(data):
    journal, result, manifest = data['journal'], data['result'], data['manifest']
    selection = data['selection']
    selection['source_attempt_ref'] = _save(data['inputs'].store.root / 'cr/failed.json', journal)
    result['patch_execution_receipts'] = [{**selection['source_attempt_ref'], 'model_call_count': 0, 'proposal_admitted': False}]
    selection['parent_result_ref'] = _save(data['inputs'].workspace / 'run_result.json', result)
    manifest['terminal_record'] = selection['parent_result_ref']
    selection['parent_manifest_ref'] = _save(data['inputs'].workspace / 'run_manifest.json', manifest)


def admit(data):
    return admit_pretransport_patch(data['selection'], workspace_root=data['inputs'].workspace, artifact_store=data['inputs'].store)


def test_admission_preserves_three_prior_calls_and_original_bytes(failed, monkeypatch):
    monkeypatch.setattr('src.mod_agent.patch_worker_configuration._LazyBehaviorEvaluator._construct', lambda *a: pytest.fail('admission executes evaluator'))
    before = {str(p): p.read_bytes() for p in failed['root'].rglob('*') if p.is_file()}
    admitted = admit(failed)
    assert admitted['shared_model_budget']['maximum'] == 18
    assert admitted['shared_model_budget']['consumed'] == 3
    assert admitted['shared_model_budget']['remaining'] == 15
    assert admitted['model_calls_performed'] == 0 and admitted['approval_inherited'] is False
    assert before == {str(p): p.read_bytes() for p in failed['root'].rglob('*') if p.is_file()}


@pytest.mark.parametrize('damage', ['response', 'request', 'turns', 'proposal', 'apply', 'interrupted', 'exhausted', 'counter', 'role', 'source', 'plan', 'worker', 'config_hash'])
def test_other_boundaries_cannot_claim_patch_balance(failed, damage):
    f, j, r, m = failed['journal']['factory_receipt'], failed['journal'], failed['result'], failed['manifest']
    if damage == 'response': f['model_responses'] = [{'content': 'code'}]
    elif damage == 'request': f['provider_request'] = {'sent': True}
    elif damage == 'turns': f['worker_turns'] = [{'status': 'sent'}]
    elif damage == 'proposal': j['proposal_admitted'] = True
    elif damage == 'apply': r['actual_write_performed'] = True
    elif damage == 'interrupted': j['status'] = 'local_patch_post_response_model_admitted'
    elif damage == 'exhausted': r['model_call_budget'].update(maximum=3, remaining=0)
    elif damage == 'counter': r['model_call_count'] = 0
    elif damage == 'role': m['execution_observations']['planning']['attributes']['model_role'] = 'initial_patch'
    elif damage == 'source': failed['inputs'].behavior.write_text('changed source')
    elif damage == 'plan': r['artifacts']['implementation_plan'] += '-other'
    elif damage == 'worker': j['worker_profile_sha256'] = '0' * 64
    elif damage == 'config_hash': failed['selection']['execution_config_ref']['sha256'] = '0' * 64
    save_failed(failed)
    with pytest.raises((ValueError, OSError)):
        admit(failed)


def test_completed_and_incomplete_claims_never_reexecute(failed, monkeypatch):
    root = failed['inputs'].workspace
    config = {'selection': failed['selection']}
    segment = root / 'continuations/pt-test'
    segment.mkdir(parents=True)
    claim = segment.parent / ('pretransport-' + config['selection']['source_attempt_ref']['sha256'][:24] + '.json')
    record = {'recovery_config_sha256': _hash(config), 'status': 'claimed', 'model_call_budget': {'consumed': 4, 'remaining': 14}, 'result_path': str(segment / 'run_result.json')}
    _save(claim, record)
    monkeypatch.setattr(entry, 'prepare_interrupted_patch', lambda **_: pytest.fail('reexecuted'))
    kwargs = dict(run_root=root, run_id=root.name, execution_config=config['selection']['execution_config_ref']['path'], recovery_config=config, pretransport=True)
    assert entry.resume_interrupted_patch(**kwargs)['automatic_execution_started'] is False
    result = {'status': 'awaiting_approval', 'model_call_count': 4}
    record.update(status='recorded', result_ref=_save(segment / 'run_result.json', result))
    _save(claim, record)
    before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert entry.resume_interrupted_patch(**kwargs) == result
    assert before == {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    (segment / 'run_result.json').write_text('{"status":"delivered"}')
    with pytest.raises(ValueError, match='RECORDED_RESULT_CHANGED'):
        entry.resume_interrupted_patch(**kwargs)


def test_dsh_advance_dispatches_same_task_without_routing(failed, monkeypatch, capsys):
    from scripts import dsh_run_request as dsh
    root = failed['inputs'].workspace
    config = {'selection': failed['selection']}
    allocation = _save(failed['root'] / 'allocation.json', {'pretransport_patch': config})
    monkeypatch.setattr(dsh, 'task_execution_config', lambda **_: failed['selection']['execution_config_ref']['path'])
    monkeypatch.setattr(dsh, 'inspect_run', lambda **_: {'status': 'recorded', 'run_root': str(root), 'manifest': failed['manifest'], 'result': failed['result']})
    calls = []
    def execute(**kwargs):
        calls.append(kwargs)
        return {'status': 'awaiting_approval', 'model_call_count': 4}
    monkeypatch.setattr(entry, 'resume_interrupted_patch', execute)
    assert dsh.main(['--execution-config', failed['selection']['execution_config_ref']['path'], '--advance-task', root.name, '--findings-allocation-config', allocation['path']]) == 0
    assert json.loads(capsys.readouterr().out)['model_call_count'] == 4
    assert calls[0]['pretransport'] is True and calls[0]['run_id'] == root.name
    assert calls[0]['recovery_config'] == config


def test_real_graph_starts_at_patch_and_preserves_approval_gate(tmp_path, monkeypatch):
    from tests.unit.test_interrupted_product_graph import _selected
    from src.mod_agent.product_executor import execute_product_execution, preflight_product_execution, ProductApprovalDeferred
    request, store, adapters, admitted, _, _ = _selected(tmp_path, monkeypatch)
    selection = {key: _save(tmp_path / (key + '.json'), {}) for key in
        ('source_attempt_ref', 'parent_manifest_ref', 'parent_result_ref', 'execution_config_ref')}
    count = []
    def admission(*args, **kwargs):
        count.append(1)
        return deepcopy(admitted)
    monkeypatch.setattr('src.mod_agent.pretransport_patch_admission.admit_pretransport_patch', admission)
    with pytest.raises(ProductApprovalDeferred) as caught:
        execute_product_execution(preflight_product_execution(request, adapters, store), adapters, store,
            defer_approval=True, pretransport_patch_selection=selection)
    result = caught.value
    assert len(count) == 2
    assert all(row.node_name == 'pretransport_patch_admission' and row.origin == 'reused_input' for row in result.outputs[:3])
    assert [row.artifact_role for row in result.outputs[3:]] == ['patch_proposal', 'proposal_review', 'dry_run_result']
    assert {row.effect_role for row in result.effect_events} == {'patch_generation', 'dry_run'}
    assert store.semantic_read_immutable(result.dry_run_ref)['data']['actual_write_performed'] is False


def test_shared_execution_records_cumulative_cost_once_and_preserves_parent(failed, monkeypatch):
    from types import SimpleNamespace
    from src.mod_agent import local_entry
    from src.mod_agent.product_executor import source_snapshot
    root = failed['inputs'].workspace
    manifest = failed['manifest']
    manifest.update(source_snapshot=source_snapshot(Path(manifest['target_source'])),
        source_view_policy={'schema_version': 'source_view_policy_v1', 'small_file_max_bytes': 8192}, source_revision_binding={},
        source_disclosure={'fixture': True}, model_admission={'fixture': True}, runtime_admission={'fixture': True})
    prepared = {'admission': admit(failed), 'manifest': manifest,
        'parsed': SimpleNamespace(settings='config/settings.yaml'),
        'scope': {'worker_configuration_ref': failed['journal']['worker_configuration_ref'], 'maximum_seconds': 1800},
        'scope_sha256': 'd' * 64}
    from src.mod_agent.model_qualification import worker_implementation_identity
    prepared['scope'].update(recovery_implementation=worker_implementation_identity(), recovery_entry_sources={})
    monkeypatch.setattr(entry, 'prepare_interrupted_patch', lambda **_: deepcopy(prepared))
    monkeypatch.setattr(local_entry, '_read_ollama_model_identity', lambda *a: deepcopy(manifest['local_model_identity']))
    monkeypatch.setattr('src.mod_agent.planning.model_selection.ModelPlanningTargetSelector.from_settings', lambda **_: None)
    monkeypatch.setattr(local_entry, 'preflight_product_execution', lambda *a: None)
    from src.mod_agent.request_patch_execution import RequestPatchExecution
    monkeypatch.setattr(RequestPatchExecution, 'complete_product', lambda *a: None)
    calls = []
    def graph(_preflight, adapters, _store, **kwargs):
        assert kwargs['defer_approval'] is True and kwargs['pretransport_patch_selection'] == failed['selection']
        worker = adapters.patch_change_factory
        assert worker.pretransport_patch_selection == failed['selection']
        assert worker.budget_snapshot()['consumed'] == 3
        worker.reserve_model_call('initial_patch')
        assert worker.budget_snapshot()['consumed'] == 4 and worker.budget_snapshot()['remaining'] == 14
        calls.append(1)
        return SimpleNamespace(execution_disposition='partial', terminal_node='generate_patch_proposal', outputs=[], blockers=[], to_dict=lambda: {})
    monkeypatch.setattr(local_entry, 'execute_product_execution', graph)
    config = {'selection': failed['selection']}
    kwargs = dict(run_root=root, run_id=root.name, execution_config=config['selection']['execution_config_ref']['path'], recovery_config=config, pretransport=True)
    originals = {key: open(ref['path'], 'rb').read() for key, ref in failed['selection'].items()}
    result = entry.resume_interrupted_patch(**kwargs)
    assert result.get('failure_class') is None, result
    assert result['prior_model_call_count'] == 3 and result['current_invocation_model_call_count'] == 1
    assert result['model_call_count'] == 4 and result['model_call_budget']['maximum'] == 18
    assert result['actual_write_performed'] is False and result['history_rewritten'] is False
    assert calls == [1]
    assert entry.resume_interrupted_patch(**kwargs) == result and calls == [1]
    assert originals == {key: open(ref['path'], 'rb').read() for key, ref in failed['selection'].items()}
    assert entry.read_interrupted_patch_execution(root, pretransport=True) == result


@pytest.mark.parametrize('damage', [None, 'wrong_segment', 'existing', 'prepare', 'wrong_run'])
def test_frozen_recovery_selects_only_new_bound_segment(failed, damage):
    from types import SimpleNamespace
    from src.mod_agent.platform_execution_snapshot import validate_cli_selection
    root = failed['inputs'].workspace
    config_ref = _save(failed['root'] / 'recovery.json', {'selection': failed['selection']})
    segment = root / 'continuations' / ('pt-' + failed['selection']['source_attempt_ref']['sha256'][:12])
    args = SimpleNamespace(command='continue-pretransport-patch', run_root=str(root), run_id=root.name,
        recovery_config=config_ref['path'], prepare_only=damage == 'prepare')
    document = {'selected_run_root': str(segment)}
    if damage == 'wrong_segment': document['selected_run_root'] = str(root / 'other')
    elif damage == 'existing': segment.mkdir(parents=True)
    elif damage == 'wrong_run': args.run_id = 'other'
    if damage:
        with pytest.raises(ValueError, match='SEGMENT_SELECTION'):
            validate_cli_selection(args, document)
    else:
        validate_cli_selection(args, document)


@pytest.mark.parametrize('damage', [None, 'budget', 'cost', 'scope', 'old_check', 'unverified', 'wrong_segment'])
def test_delivery_requires_new_execution_proof_and_same_task_budget(failed, monkeypatch, damage):
    from src.mod_agent.evaluation.isolated_delivery_adapter import _pretransport_delivery_binding
    root = failed['inputs'].workspace
    selection = failed['selection']
    segment = root / 'continuations' / ('pt-' + selection['source_attempt_ref']['sha256'][:12])
    scope = {'selection': selection, 'inherited_budget': failed['result']['model_call_budget']}
    scope_ref = _save(segment / 'scope.json', scope)
    snapshot_ref = _save(failed['root'] / 'frozen/snapshot.json', {'selected_run_root': str(segment), 'business_argv': ['continue-pretransport-patch']})
    check = {'status': 'verified', 'phase': 'finished', 'run_id': root.name, 'request_id': failed['manifest']['request_id'], 'execution_version_ref': snapshot_ref}
    if damage == 'old_check': check['phase'] = 'started'
    elif damage == 'unverified': check['status'] = 'unknown'
    elif damage == 'wrong_segment': snapshot_ref = _save(failed['root'] / 'frozen/snapshot.json', {'selected_run_root': str(root), 'business_argv': ['continue-pretransport-patch']}); check['execution_version_ref'] = snapshot_ref
    check_ref = _save(failed['root'] / 'frozen/check.json', check)
    budget = deepcopy(failed['result']['model_call_budget'])
    budget.update(consumed=4, remaining=14)
    budget['by_stage']['initial_patch']['consumed'] = 1
    if damage == 'budget': budget.update(maximum=19, remaining=15)
    initial = {'entry': 'pretransport-patch-continuation', 'generation_origin': 'new_patch_after_verified_pretransport_failure',
        'parent_selection': selection, 'parent_manifest_ref': selection['parent_manifest_ref'], 'parent_result_ref': selection['parent_result_ref'],
        'run_id': root.name, 'parent_run_id': root.name, 'request_id': failed['manifest']['request_id'], 'continuation_root': str(segment),
        'model_call_budget': budget, 'model_call_count': 4, 'prior_model_call_count': 3, 'current_invocation_model_call_count': 0 if damage == 'cost' else 1,
        'history_rewritten': False, 'actual_write_performed': False, 'continuation_scope_ref': scope_ref,
        'execution_version_check_ref': check_ref, 'execution_version_ref': snapshot_ref, 'execution_version_status': 'verified'}
    initial_ref = _save(segment / 'run_result.json', initial)
    claim = _save(root / 'continuations' / ('pretransport-' + selection['source_attempt_ref']['sha256'][:24] + '.json'),
        {'status': 'recorded', 'result_ref': initial_ref, 'scope_sha256': '0' * 64 if damage == 'scope' else _hash(scope)})
    _save(root / 'continuations/pretransport_latest.json', {'result_ref': initial_ref, 'claim_ref': claim})
    if damage:
        with pytest.raises(ValueError, match='DELIVERY_PRETRANSPORT'):
            _pretransport_delivery_binding(root, initial, initial_ref, selection['parent_manifest_ref'])
    else:
        assert _pretransport_delivery_binding(root, initial, initial_ref, selection['parent_manifest_ref']) == scope
