"""Resume a retained complete response through the original Product Graph and budget."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.evidence.optimization_policy import run_optimization_policy
from src.mod_agent.domain.full_project_compilation import _ref
from src.mod_agent.model_qualification import canonical_hash, read_bound_json


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def _validate_recovery_config(value):
    if (not isinstance(value, dict) or set(value) - {'selection', 'worker_configuration_ref', 'maximum_seconds'}
            or not isinstance(value.get('selection'), dict)
            or set(value['selection']) != {'source_attempt_ref', 'parent_manifest_ref', 'execution_stop_ref'}):
        raise ValueError('INTERRUPTED_PATCH_RECOVERY_CONFIG_INVALID')
    for reference in [*value['selection'].values(), *([value['worker_configuration_ref']] if value.get('worker_configuration_ref') else [])]:
        if (not isinstance(reference, dict) or set(reference) != {'path', 'sha256'}
                or not isinstance(reference['path'], str) or not Path(reference['path']).is_absolute()
                or not isinstance(reference['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', reference['sha256'])):
            raise ValueError('INTERRUPTED_PATCH_RECOVERY_REFERENCE_INVALID')


def read_interrupted_patch_execution(run_root, *, pretransport=False):
    root = Path(run_root).resolve()
    pointer = root / 'continuations' / ('pretransport_latest.json' if pretransport else 'interrupted_latest.json')
    if not pointer.exists():
        return None
    value = json.loads(pointer.read_bytes())
    reference = value['result_ref']
    path = Path(reference['path']).resolve()
    path.relative_to(root / 'continuations')
    Path(value['claim_ref']['path']).resolve().relative_to(root / 'continuations')
    claim = read_bound_json(value['claim_ref'])
    if claim.get('status') != 'recorded' or claim.get('result_ref') != reference:
        raise ValueError('INTERRUPTED_PATCH_RECORDED_CLAIM_CHANGED')
    result = read_bound_json(reference)
    if result.get('run_id') != root.name or result.get('entry') != ('pretransport-patch-continuation' if pretransport else 'interrupted-patch-continuation'):
        raise ValueError('INTERRUPTED_PATCH_RECORDED_RESULT_IDENTITY_CHANGED')
    return result


def prepare_interrupted_patch(*, run_root, run_id, execution_config, recovery_config, pretransport=False):
    from scripts.dsh_run_request import _configuration_arguments
    from src.mod_agent.cli import build_parser
    from src.mod_agent.interrupted_patch_admission import admit_interrupted_patch

    root = Path(run_root).resolve(strict=True)
    if pretransport:
        from src.mod_agent.pretransport_patch_admission import validate_recovery_config
        validate_recovery_config(recovery_config)
    else:
        _validate_recovery_config(recovery_config)
    selection = recovery_config['selection']
    worker_ref = recovery_config.get('worker_configuration_ref')
    if pretransport:
        from src.mod_agent.pretransport_patch_admission import admit_pretransport_patch
        admit_interrupted_patch = admit_pretransport_patch
    admission = admit_interrupted_patch(selection, workspace_root=root, artifact_store=ArtifactStore(root / 'a'),
        worker_configuration_ref=worker_ref)
    manifest = read_bound_json(selection['parent_manifest_ref'])
    arguments, _ = _configuration_arguments(execution_config)
    parsed = build_parser().parse_args(['run-request', *arguments, '--', manifest['request']])
    if pretransport:
        from src.mod_agent.platform_execution_snapshot import current_frozen_execution
        frozen = current_frozen_execution()
        if frozen is not None:
            frozen.bind_cli_inputs(parsed)
    profile = admission['factory_receipt']['profile']
    if (run_id != root.name or manifest['run_id'] != run_id or parsed.run_id != run_id
            or parsed.request_id != manifest['request_id']
            or Path(parsed.workspace_root).resolve() / run_id != root
            or Path(parsed.target_project).resolve() != Path(manifest['target_source']).resolve()
            or not parsed.local_ollama or parsed.allow_source_disclosure or not parsed.defer_approval
            or not parsed.confirm_isolated_write or not parsed.allow_build
            or parsed.ollama_model != profile['model'] or parsed.ollama_base_url != profile['base_url']
            or parsed.ollama_context_window != profile['context_window']
            or parsed.ollama_max_output_tokens != profile['output_budget']
            or parsed.ollama_timeout_seconds not in (None, profile['timeout_seconds'])
            or parsed.task_model_call_limit != admission['shared_model_budget']['maximum']
            or parsed.model_call_budget_policy != admission['shared_model_budget'].get('policy', 'stage_and_total')
            or _ref(parsed.patch_worker_config) != admission['original_worker_configuration_ref']
            or manifest.get('runtime_admission', {}).get('requested') is True):
        raise ValueError('INTERRUPTED_PATCH_EXECUTION_CONFIGURATION_CHANGED')
    maximum_seconds = recovery_config.get('maximum_seconds', 1800)
    if type(maximum_seconds) not in (int, float) or not profile['timeout_seconds'] <= maximum_seconds <= 3600:
        raise ValueError('INTERRUPTED_PATCH_TIME_LIMIT_INVALID')
    config_ref = _ref(execution_config)
    if pretransport and config_ref != selection['execution_config_ref']:
        raise ValueError('PRETRANSPORT_PATCH_EXECUTION_CONFIGURATION_CHANGED')
    settings_ref = _ref(parsed.settings)
    scope = {'selection': deepcopy(selection), 'worker_configuration_ref': worker_ref or admission['worker_configuration_ref'],
        'execution_config_ref': config_ref, 'settings_ref': settings_ref,
        'inherited_budget': admission['shared_model_budget'], 'maximum_seconds': maximum_seconds}
    if pretransport:
        from src.mod_agent.model_qualification import worker_implementation_identity
        scope['recovery_implementation'] = worker_implementation_identity()
        scope['recovery_entry_sources'] = {name: _ref(Path(__file__).parent / name) for name in
            ('pretransport_patch_admission.py', 'interrupted_patch_continuation.py', 'product_execution.py', 'product_executor.py', 'workflow/graph.py')}
        scope['generation_origin'] = 'new_patch_after_verified_pretransport_failure'
    return {'root': root, 'admission': admission, 'manifest': manifest, 'parsed': parsed,
        'scope': scope, 'scope_sha256': canonical_hash(scope)}


def resume_interrupted_patch(*, run_root, run_id, execution_config, recovery_config, pretransport=False):
    """Consume one explicit source journal once; never replace the incomplete parent record."""
    from src.core.settings import load_settings
    from src.libs.llm.ollama_llm import OllamaLLM
    from src.mod_agent import local_entry as owner, requirement_coverage_model
    from src.mod_agent.evidence import RgLiveEvidenceProvider
    from src.mod_agent.evidence.source_view import source_view_policy_from_manifest
    from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration
    from src.mod_agent.planning.model_selection import ModelPlanningTargetSelector
    from src.mod_agent.product_execution import ProductExecutionInputBindingV1, ProductExecutionRequestV1
    from src.mod_agent.product_executor import ProductExecutionAdaptersV1, ProductApprovalDeferred, source_snapshot, source_snapshot_sha256
    from src.mod_agent.patch_execution_trace import product_execution_trace, product_trace_identity
    from src.mod_agent.request_patch_execution import RequestPatchExecution
    from src.mod_agent.upstream_model_trace import trace_upstream_model_call

    root = Path(run_root).resolve(strict=True)
    if pretransport:
        from src.mod_agent.pretransport_patch_admission import validate_recovery_config
        validate_recovery_config(recovery_config)
        if run_id != root.name or _ref(execution_config) != recovery_config['selection']['execution_config_ref']:
            raise ValueError('PRETRANSPORT_PATCH_EXECUTION_CONFIGURATION_CHANGED')
    else:
        _validate_recovery_config(recovery_config)
    # 为什么要有它：同一原始中断只能消费一次；重复读取不能重领剩余额度或把未知的中断状态当成可重跑。
    claim = root / 'continuations' / (('pretransport-' if pretransport else 'interrupted-') + recovery_config['selection']['source_attempt_ref']['sha256'][:24] + '.json')
    if claim.exists():
        record = json.loads(claim.read_bytes())
        if record['recovery_config_sha256'] != canonical_hash(recovery_config):
            raise ValueError('INTERRUPTED_PATCH_ALREADY_CLAIMED_WITH_OTHER_INPUT')
        result_path = Path(record['result_path']).resolve()
        result_path.relative_to(root / 'continuations')
        if record.get('status') == 'recorded':
            if record.get('result_ref') != _ref(result_path):
                raise ValueError('INTERRUPTED_PATCH_RECORDED_RESULT_CHANGED')
            return json.loads(result_path.read_bytes())
        return (
            {'status': 'interrupted_continuation_incomplete', 'automatic_execution_started': False,
             'claim_path': str(claim), 'model_call_budget': record['model_call_budget']})
    prepared = prepare_interrupted_patch(run_root=root, run_id=run_id, execution_config=execution_config,
        recovery_config=recovery_config, **({"pretransport": True} if pretransport else {}))
    admission, manifest, parsed = (prepared[key] for key in ('admission', 'manifest', 'parsed'))
    profile_data = admission['factory_receipt']['profile']
    profile = owner.LocalOllamaInitialPatchProfileV1(**{key: profile_data[key] for key in
        ('profile_version', 'base_url', 'model', 'context_window', 'output_budget', 'timeout_seconds')})
    original_identity = admission['factory_receipt']['model_identity']
    budget = deepcopy(admission['shared_model_budget'])
    worker_config = PatchWorkerConfiguration.load(prepared['scope']['worker_configuration_ref']['path'])
    if worker_config.reference != prepared['scope']['worker_configuration_ref']:
        raise ValueError('INTERRUPTED_PATCH_WORKER_CONFIGURATION_CHANGED')
    settings = load_settings(parsed.settings)
    settings = replace(settings, llm=replace(settings.llm, provider='ollama', model=profile.model,
        base_url=profile.base_url, temperature=0.0, max_tokens=profile.output_budget))
    segment = root / 'continuations' / ('pt-' + recovery_config['selection']['source_attempt_ref']['sha256'][:12] if pretransport else 'ip-' + prepared['scope_sha256'][:12])
    claim.parent.mkdir(exist_ok=True)
    receipt = {'status': 'claimed', 'scope_sha256': prepared['scope_sha256'],
        'recovery_config_sha256': canonical_hash(recovery_config), 'result_path': str(segment / 'run_result.json'),
        'model_call_budget': deepcopy(budget)}
    with claim.open('x', encoding='utf-8') as handle:
        json.dump(receipt, handle, ensure_ascii=False)
    segment.mkdir(exist_ok=False)
    _write(segment / 'scope.json', prepared['scope'])
    segment_manifest = {'run_id': run_id, 'request_id': manifest['request_id'],
        'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'running',
        'source_view_policy': source_view_policy_from_manifest(manifest),
        'evidence_optimization': run_optimization_policy(root),
        'interrupted_parent_selection': deepcopy(recovery_config['selection']),
        'model_call_budget': deepcopy(budget), 'prior_model_call_count': budget['consumed'],
        'model_call_count': budget['consumed'], 'local_model_identity': original_identity,
        'generation_origin': ('new_patch_after_verified_pretransport_failure' if pretransport else 'retained_complete_response_then_new_live_calls_if_needed')}
    if pretransport:
        segment_manifest.update(parent_result_ref=recovery_config['selection']['parent_result_ref'],
            parent_manifest_ref=recovery_config['selection']['parent_manifest_ref'])
    _write(segment / 'run_manifest.json', segment_manifest)
    started = time.monotonic()
    def identity(base_url, model):
        observed = owner._read_ollama_model_identity(base_url, model)
        owner._assert_ollama_model_identity_stable(expected=original_identity, observed=observed)
        owner._validate_ollama_context_window(observed, requested_context_window=profile.context_window)
        return observed
    def reserve(role):
        nonlocal budget
        if prepared['scope']['maximum_seconds'] - (time.monotonic()-started) < profile.timeout_seconds:
            raise owner.LocalEntryError('PRODUCT_CONTINUATION_TIME_BUDGET_EXHAUSTED')
        if pretransport:
            from src.mod_agent.model_qualification import worker_implementation_identity
            if worker_implementation_identity() != prepared['scope']['recovery_implementation']:
                raise owner.LocalEntryError('PRETRANSPORT_PATCH_IMPLEMENTATION_CHANGED')
            for reference in prepared['scope']['recovery_entry_sources'].values():
                if _ref(reference['path']) != reference:
                    raise owner.LocalEntryError('PRETRANSPORT_PATCH_IMPLEMENTATION_CHANGED')
            if worker_config.reference != _ref(worker_config.reference['path']):
                raise owner.LocalEntryError('PRETRANSPORT_PATCH_WORKER_CONFIGURATION_CHANGED')
        budget = owner._reserve_request_model_call(budget, role)
        receipt['model_call_budget'] = deepcopy(budget)
        _write(claim, receipt)
        observed = json.loads((segment / 'run_manifest.json').read_bytes())
        observed.update(model_call_budget=deepcopy(budget), model_call_count=budget['consumed'])
        _write(segment / 'run_manifest.json', observed)
    result = None
    try:
        identity(profile.base_url, profile.model)
        llm = OllamaLLM(settings, base_url=profile.base_url, context_window=profile.context_window, timeout=profile.timeout_seconds)
        def complete(role, payload, schema):
            identity(profile.base_url, profile.model)
            owner._assert_no_absolute_local_paths(payload)
            output = owner._request_model_output_budget(role, profile.output_budget)
            messages = requirement_coverage_model.requirement_coverage_messages(payload)
            frozen = {}
            llm.prepare_structured_chat(messages, temperature=0.0, max_tokens=output, response_format=schema,
                provider_request_recorder=frozen.update)
            reserve(owner._request_model_budget_stage(role))
            def invoke(recorder):
                recorder(deepcopy(frozen))
                return llm.resume_structured_chat(frozen, expected_output_budget=output)
            response = trace_upstream_model_call(role=role, provider=type(llm).__name__, model=llm.model,
                input_payload=payload, request_document={'messages': [asdict(message) for message in messages],
                    'response_format': dict(schema), 'temperature': 0.0, 'max_tokens': output, 'stream_response': False},
                body_root=segment, invoke_with_provider_request=invoke)
            identity(profile.base_url, profile.model)
            return requirement_coverage_model.parse_requirement_coverage_json_object(response.content)
        store = ArtifactStore(root / 'a')
        source = Path(manifest['target_source']).resolve()
        target = root / 'generated_mods' / source.name
        worker = RequestPatchExecution(artifact_store=store, workspace_root=root, profile=profile,
            identity_reader=identity, policy=worker_config.policy, reserve_model_call=reserve,
            budget_snapshot=lambda: deepcopy(budget), behavior_evaluator=worker_config.behavior_evaluator(),
            worker_configuration_ref=worker_config.reference,
            **({'pretransport_patch_selection': recovery_config['selection']} if pretransport else
               {'interrupted_patch_selection': recovery_config['selection']}),
            invocation_namespace=('pt_' if pretransport else 'ip_') + prepared['scope_sha256'][:12])
        class PlanningClient:
            def __init__(self):
                self.client = owner.LocalOllamaInitialPatchAdapter._default_agent_turn_client(profile)
                self.provider, self.model = self.client.provider, self.client.model
            def complete_turn(self, request):
                identity(profile.base_url, profile.model); reserve('repair')
                response = trace_upstream_model_call(role='patch_upstream_planning', provider=self.provider, model=self.model,
                    input_payload=request.messages[1].content, request_document=asdict(request), body_root=segment,
                    invoke=lambda: self.client.complete_turn(request))
                identity(profile.base_url, profile.model)
                return response
        selector = ModelPlanningTargetSelector.from_settings(settings=settings, client=PlanningClient(), workspace_root=root,
            behavior_evaluator_configured=True, receipt_path=segment / 'planning_upstream_model_selection.json',
            model_identity=original_identity)
        upstream = owner._make_request_upstream_evidence_factory(artifact_store=store, workspace_root=root,
            compress_findings_input=run_optimization_policy(root)['compress_findings_input'],
            source_provider=RgLiveEvidenceProvider(root, small_file_max_bytes=manifest['source_view_policy']['small_file_max_bytes'],
                reuse_query_observations=run_optimization_policy(root)['reuse_query_observations']),
            upstream_search_root=target.relative_to(root).as_posix(), complete_requirement_coverage_json=complete,
            budget_snapshot=lambda: deepcopy(budget))
        def unused(*_):
            raise owner.LocalEntryError('INTERRUPTED_PATCH_UNEXPECTED_INITIAL_OR_SIDE_EFFECT_STAGE')
        request = ProductExecutionRequestV1(contract_version='1', run_id=run_id, request_id=manifest['request_id'],
            user_request=manifest['request'], target_domain='gtfo', target_mod=source.name,
            requested_completion_scope='compile_only', repair_budget=2, isolated_workspace_root=str(root),
            isolated_target_root=str(target), source_root=str(source), artifact_store_root=str(store.root),
            source_snapshot_sha256=manifest['source_snapshot_sha256'],
            isolated_source_snapshot_sha256=source_snapshot_sha256(source_snapshot(target)),
            input_bindings=tuple(ProductExecutionInputBindingV1.create(key, manifest[key] or None) for key in
                ('source_revision_binding', 'source_disclosure', 'model_admission', 'runtime_admission')),
            completion_classification=(), confirmed_isolated_write=True, allow_build=True)
        adapters = ProductExecutionAdaptersV1(evidence_pack_factory=unused, patch_change_factory=worker,
            planning_target_selection_factory=unused, product_patch_upstream_execution=worker,
            patch_upstream_evidence_pack_factory=upstream, patch_upstream_planning_target_selection_factory=selector,
            dry_run_factory=owner.make_exact_no_write_dry_run_factory(root), isolated_apply_factory=unused,
            build_result_factory=unused, runtime_evidence_factory=None, compiled_artifact_verifier=None,
            source_change_verifier=None)
        with product_execution_trace(run_root=segment, run_id=run_id, request_id=manifest['request_id'], artifact_store_root=store.root) as trace:
            preflight = owner.preflight_product_execution(request, adapters, store)
            try:
                product = owner.execute_product_execution(preflight, adapters, store, defer_approval=True,
                    **({'pretransport_patch_selection': recovery_config['selection']} if pretransport else
                       {'interrupted_patch_selection': recovery_config['selection']}))
                worker.complete_product(product)
                result = {'status': product.execution_disposition, 'product_execution_result': product.to_dict(),
                    'artifacts': {row.artifact_role: row.artifact_ref.path for row in product.outputs},
                    'current_stage': product.terminal_node, 'blockers': [row.to_dict() for row in product.blockers]}
            except ProductApprovalDeferred as pending:
                worker.complete_deferred(pending)
                result = {**pending.to_dict(), 'current_stage': 'awaiting_approval',
                    'artifacts': {row.artifact_role: row.artifact_ref.path for row in pending.outputs}}
            result.update(execution_trace=product_trace_identity(trace, segment),
                patch_execution_receipts=[journal.projection() for journal in worker.journals])
    except Exception as error:
        result = {'status': 'blocked', 'reason': str(error), 'failure_class': type(error).__name__}
    unchanged = source_snapshot(Path(manifest['target_source'])) == manifest['source_snapshot']
    isolated_unchanged = source_snapshot(root / 'generated_mods' / Path(manifest['target_source']).name) == manifest['source_snapshot']
    result.update(entry=('pretransport-patch-continuation' if pretransport else 'interrupted-patch-continuation'), run_id=run_id, request_id=manifest['request_id'],
        feature_id=admission['feature_id'],
        evidence_optimization=run_optimization_policy(root),
        run_root=str(root), continuation_root=str(segment), parent_selection=deepcopy(recovery_config['selection']),
        model_call_budget=deepcopy(budget), model_call_count=budget['consumed'],
        prior_model_call_count=admission['shared_model_budget']['consumed'],
        current_invocation_model_call_count=budget['consumed']-admission['shared_model_budget']['consumed'],
        canonical_source_unchanged=unchanged, actual_write_performed=False if isolated_unchanged else None,
        history_rewritten=False, elapsed_seconds=time.monotonic()-started)
    if pretransport:
        segment_document = json.loads((segment / 'run_manifest.json').read_bytes())
        result.update(generation_origin='new_patch_after_verified_pretransport_failure',
            parent_run_id=run_id, parent_manifest_ref=recovery_config['selection']['parent_manifest_ref'],
            parent_result_ref=recovery_config['selection']['parent_result_ref'],
            continuation_scope_ref=_ref(segment / 'scope.json'),
            **{key: segment_document[key] for key in ('execution_version_ref', 'execution_version_check_ref', 'execution_version_status') if key in segment_document})
    _write(segment / 'run_result.json', result)
    observed = json.loads((segment / 'run_manifest.json').read_bytes())
    observed.update(status=result['status'], model_call_budget=deepcopy(budget), model_call_count=budget['consumed'])
    if pretransport:
        observed.update(terminal_record=_ref(segment / 'run_result.json'), terminal_stage=result.get('current_stage', result['status']))
    _write(segment / 'run_manifest.json', observed)
    receipt.update(status='recorded', result_ref=_ref(segment / 'run_result.json'))
    _write(claim, receipt)
    # 为什么要有它：状态查询必须能找到另存的续接结果，不能改写原来未完成的manifest来制造终态。
    _write(root / 'continuations' / ('pretransport_latest.json' if pretransport else 'interrupted_latest.json'), {'result_ref': receipt['result_ref'], 'claim_ref': _ref(claim)})
    return result
