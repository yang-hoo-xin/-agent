"""Independent Mod initialization through the normal DSH bridge, without inference."""
import hashlib
import io
import json
import shutil
from pathlib import Path

import pytest

from scripts import dsh_run_request as bridge
from src.mod_agent import local_entry
from tests.unit.test_dsh_run_request import execution_config  # noqa: F401


@pytest.fixture
def profile(execution_config, monkeypatch):  # noqa: F811
    root = execution_config.parent / 'deps'
    for name in ('BepInEx/core/BepInEx.Core.dll', 'BepInEx/core/BepInEx.Unity.IL2CPP.dll',
                 'BepInEx/core/Il2CppInterop.Runtime.dll', 'BepInEx/core/0Harmony.dll',
                 'BepInEx/interop/UnityEngine.CoreModule.dll', 'BepInEx/plugins/GTFO-API.dll'):
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'offline reference fixture')
    snapshot = local_entry._binary_tree_snapshot(root)
    binding = execution_config.parent / 'dependencies.json'
    binding.write_text(json.dumps({'binding_version': 'run_local_game_folder_binding_v1',
        'source_root': str(root), 'snapshot_sha256': local_entry._binary_tree_snapshot_sha256(snapshot),
        'file_count': len(snapshot), 'property_name': 'GameFolder'}))
    config = json.loads(execution_config.read_text())
    config['arguments'] += ['--game-folder-build-binding', str(binding)]
    execution_config.write_text(json.dumps(config))
    monkeypatch.setattr(bridge.cli, 'main', lambda *_: pytest.fail('No product execution during initialization'))
    return execution_config


def initialize(profile):
    selected = bridge.prepare_new_task(execution_config=str(profile), description='手动开始暂停分段重置',
                                      project_name='远征分段计时器')
    _, options = bridge._configuration_arguments(selected)
    return bridge.preview_new_project(execution_config=str(profile), run_id=options['--run-id'])


def test_independent_projects_are_neutral_unique_recoverable_and_not_model_runs(profile):
    first, second = initialize(profile), initialize(profile)
    assert first['run_id'] != second['run_id']
    assert first['project_identity']['plugin_guid'] != second['project_identity']['plugin_guid']
    assert first['project_identity']['assembly_name'] != second['project_identity']['assembly_name']
    assert first['project_identity']['config_file_name'] != second['project_identity']['config_file_name']
    for value in (first, second):
        assert value['model_calls_performed'] == 0 and value['product_execution_started'] is False
        assert not Path(value['run_root']).exists()
        target = Path(value['target_project'])
        assert len(list(target.glob('*.csproj'))) == 1
        assert 'override void Load()' in (target / 'Plugin.cs').read_text()
        recovered = bridge.preview_new_project(execution_config=str(profile), run_id=value['run_id'])
        assert recovered == value
        assert bridge.task_execution_config(execution_config=str(profile), run_id=value['run_id']) == value['execution_config_path']


@pytest.mark.parametrize('damage', ['source', 'receipt', 'request', 'config', 'profile', 'target'])
def test_dynamic_project_recovery_rejects_changed_bindings(profile, damage):
    value = initialize(profile)
    config_path = Path(value['execution_config_path'])
    config = json.loads(config_path.read_text())
    binding = config['new_project_binding']
    if damage == 'source':
        (Path(value['target_project']) / 'Plugin.cs').write_text('changed')
    elif damage == 'receipt':
        Path(binding['receipt_ref']['path']).write_text('{}')
    elif damage == 'request':
        Path(binding['request_ref']['path']).write_text('{}')
    elif damage == 'profile':
        profile.write_text(profile.read_text() + ' ')
    else:
        if damage == 'target':
            args = config['arguments']
            args[args.index('--target-project') + 1] = str(profile.parent)
            config_path.write_text(json.dumps(config))
        else:
            config_path.write_text(config_path.read_text() + ' ')
    with pytest.raises(ValueError):
        bridge.task_execution_config(execution_config=str(profile), run_id=value['run_id'])


def test_start_dispatches_bound_request_to_original_cli_without_changing_budget(profile, monkeypatch, capsys):
    value = initialize(profile)
    captured = []
    monkeypatch.setattr(bridge.cli, 'main', lambda args: captured.append(args) or 0)
    assert bridge.main(['--execution-config', str(profile), '--start-project', value['run_id']]) == 0
    args = captured[0]
    assert args[0] == 'run-request'
    assert args[-1] == value['description']
    assert args[args.index('--target-project') + 1] == value['target_project']
    assert args[args.index('--task-model-call-limit') + 1] == '9'
    with pytest.raises(ValueError, match='REQUEST_CHANGED'):
        bridge.build_product_argv(execution_config=value['execution_config_path'], description='different')


def test_main_initialization_and_restart_preview_never_dispatch_product(profile, monkeypatch, capsys):
    monkeypatch.setattr(bridge.sys, 'stdin', io.TextIOWrapper(io.BytesIO('计时需求'.encode())))
    assert bridge.main(['--execution-config', str(profile), '--initialize-project-name', '计时器']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['entry'] == 'dsh-new-project' and result['model_calls_performed'] == 0
    before = hashlib.sha256(Path(result['initialization_receipt_ref']['path']).read_bytes()).hexdigest()
    assert bridge.main(['--execution-config', str(profile), '--preview-project', result['run_id']]) == 0
    assert json.loads(capsys.readouterr().out) == result
    assert hashlib.sha256(Path(result['initialization_receipt_ref']['path']).read_bytes()).hexdigest() == before


def test_legacy_new_task_keeps_exact_fixed_target_check(profile):
    selected = Path(bridge.prepare_new_task(execution_config=str(profile), description='existing project request'))
    config = json.loads(selected.read_text())
    args = config['arguments']
    run_id = args[args.index('--run-id') + 1]
    args[args.index('--target-project') + 1] = str(profile.parent / 'Elsewhere')
    selected.write_text(json.dumps(config))
    with pytest.raises(ValueError, match='DSH_NEW_TASK_CONFIGURATION_IDENTITY_MISMATCH'):
        bridge.task_execution_config(execution_config=str(profile), run_id=run_id)


@pytest.mark.parametrize("factory,suppress", [("make_compilation_feedback", None),
    ("make_startup_notice_evaluator", True), ("make_startup_notice_evaluator", None)])
def test_neutral_project_binds_existing_compilation_feedback_to_its_actual_project(profile, factory, suppress):
    from src.mod_agent.domain import compilation_feedback
    from src.mod_agent.domain.compilation_feedback import make_compilation_feedback

    config = json.loads(profile.read_text())
    dependency_path = Path(config['arguments'][config['arguments'].index('--game-folder-build-binding') + 1])
    worker_path = profile.parent / 'old_worker.json'
    worker = {'schema_version': 'patch_worker_configuration_v1', 'enable_recovery_loop': True,
        'behavior_evaluator': {'factory_name': factory,
            'factory_ref': bridge._file_ref(Path(compilation_feedback.__file__)),
            'kwargs': {'output_root': 'allocated-by-bridge', 'compilation_kwargs': {
                'source_root': 'allocated-by-bridge', 'workspace_root': 'allocated-by-bridge',
                'artifact_store_root': 'allocated-by-bridge', 'output_root': 'allocated-by-bridge',
                'project_relative_path': 'AccurateCrosshair.csproj',
                'expected_artifact': 'bin/Debug/net6/AccurateCrosshair.dll',
                'dependency_binding': json.loads(dependency_path.read_text()),
                'nuget_config_ref': bridge._file_ref(profile), 'timeout_seconds': 120}}}}
    if factory == 'make_startup_notice_evaluator':
        worker['behavior_evaluator']['kwargs'].update(probe_configuration_ref=bridge._file_ref(profile))
        if suppress is not None:
            worker['behavior_evaluator']['kwargs']['suppress_blank_messages'] = suppress
    worker_path.write_text(json.dumps(worker))
    config['arguments'] += ['--patch-worker-config', str(worker_path)]
    base = ['behavior_evaluator', 'kwargs', 'compilation_kwargs']
    config['worker_path_bindings'] = [
        {'path': base + ['source_root'], 'relative_path': 'generated_mods/AccurateCrosshair'},
        {'path': base + ['workspace_root'], 'relative_path': '.'},
        {'path': base + ['artifact_store_root'], 'relative_path': 'a'},
        {'path': base + ['output_root'], 'relative_path': 'checks/compile'},
        {'path': ['behavior_evaluator', 'kwargs', 'output_root'], 'relative_path': 'checks/reports'},
    ]
    profile.write_text(json.dumps(config))
    prepared = initialize(profile)
    _, options = bridge._configuration_arguments(prepared['execution_config_path'])
    selected_worker = json.loads(Path(options['--patch-worker-config']).read_text())
    kwargs = selected_worker['behavior_evaluator']['kwargs']
    target = Path(prepared['target_project'])
    isolated = Path(prepared['run_root']) / 'generated_mods' / target.name
    # Only copy neutral bytes to the original owner layout; never run Build.
    shutil.copytree(target, isolated)
    checker = make_compilation_feedback(compilation_kwargs=kwargs['compilation_kwargs'], output_root=kwargs['output_root']).checker
    assert checker.source_root == isolated
    assert checker.project == isolated / 'Mod.csproj'
    assert checker.expected_artifact == 'bin/Debug/net6.0/' + prepared['project_identity']['assembly_name'] + '.dll'
    assert checker.nuget_config_ref == bridge._file_ref(target / 'nuget.config')
    assert checker._calls == 0
    assert selected_worker['behavior_evaluator']['factory_ref'] == worker['behavior_evaluator']['factory_ref']
    assert kwargs['compilation_kwargs']['timeout_seconds'] == 120
    if factory == 'make_startup_notice_evaluator':
        assert kwargs['probe_configuration_ref'] == worker['behavior_evaluator']['kwargs']['probe_configuration_ref']
        assert kwargs.get('suppress_blank_messages') is suppress
    Path(options['--patch-worker-config']).write_text('{}')
    with pytest.raises(ValueError, match='REFERENCE_CHANGED'):
        bridge.preview_new_project(execution_config=str(profile), run_id=prepared['run_id'])
