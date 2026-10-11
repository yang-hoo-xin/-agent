import hashlib
import json

import pytest

from src.mod_agent import local_entry
from src.mod_agent.cli import main
from src.mod_agent.dependency_api_config import DependencyAPIConfiguration


def configuration(tmp_path, **changes):
    inspector = tmp_path / "inspector.dll"
    inspector.write_bytes(b"inspector")
    value = {"schema_version": "run_dependency_api_config_v1",
             "inspector_ref": {"path": str(inspector), "sha256": hashlib.sha256(b"inspector").hexdigest()},
             "max_method_inspections": 3, **changes}
    path = tmp_path / "api.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path, inspector


def dependency_copy(tmp_path):
    root = tmp_path / "build_dependencies" / "GameFolder"
    root.mkdir(parents=True)
    (root / "dependency.dll").write_bytes(b"original dependency")
    snapshot = local_entry._binary_tree_snapshot(root)
    digest = local_entry._binary_tree_snapshot_sha256(snapshot)
    return {"binding_version": "run_local_game_folder_binding_v1",
            "isolated_copy": str(root), "source_snapshot_sha256": digest,
            "copy_snapshot_sha256": digest, "source_file_count": len(snapshot),
            "copy_file_count": len(snapshot), "build_uses_isolated_copy": True}


@pytest.mark.parametrize("maximum", [0, 4, True, "3"])
def test_inspection_limit_is_bounded(tmp_path, maximum):
    path, _ = configuration(tmp_path, max_method_inspections=maximum)
    with pytest.raises(ValueError, match="INSPECTION_LIMIT_INVALID"):
        DependencyAPIConfiguration.load(path)


@pytest.mark.parametrize("change", [
    {"extra_root": "/arbitrary"},
    {"schema_version": "other"},
    {"inspector_ref": {"path": "relative.dll", "sha256": "0" * 64}},
    {"inspector_ref": {"path": "relative.dll", "sha256": "bad"}},
])
def test_configuration_cannot_expand_scope_or_guess_inspector(tmp_path, change):
    path, _ = configuration(tmp_path, **change)
    with pytest.raises(ValueError):
        DependencyAPIConfiguration.load(path)


@pytest.mark.parametrize("changed", ["config", "inspector"])
def test_bound_configuration_rechecks_before_each_tool_batch(tmp_path, monkeypatch, changed):
    path, inspector = configuration(tmp_path)
    config = DependencyAPIConfiguration.load(path)
    dependency = dependency_copy(tmp_path)
    invoked = []
    def factory(projection, retrieved):
        invoked.append((projection, retrieved))
        return "evidence"
    factory.query_capabilities = {"available": True}
    captured = {}
    def bind(**kwargs):
        captured.update(kwargs)
        return factory, {"target_code_execution_allowed": False,
                         "source_snapshot_sha256": dependency["source_snapshot_sha256"],
                         "source_file_count": dependency["source_file_count"]}
    monkeypatch.setattr(local_entry, "make_run_dependency_api_reassessment_augmentation", bind)
    bound, receipt = config.bind(run_root=tmp_path, run_id="r", game_folder_dependency=dependency)
    assert captured["game_folder_dependency"] == dependency
    assert captured["inspector_sha256"] == config.inspector_sha256
    assert bound.query_capabilities == factory.query_capabilities
    assert receipt["configuration_ref"] == config.reference
    assert bound({}, "retrieved") == "evidence"
    (path if changed == "config" else inspector).write_bytes(b"changed")
    with pytest.raises(ValueError, match="CHANGED"):
        bound({}, "retrieved")
    assert len(invoked) == 1


@pytest.mark.parametrize("when, mutation", [
    (None, None), ("before", "modify"), ("before", "add"),
    ("during", "modify"), ("during", "remove"),
])
def test_dependency_batch_rechecks_original_tree_before_returning_evidence(tmp_path, monkeypatch, when, mutation):
    path, _ = configuration(tmp_path)
    config = DependencyAPIConfiguration.load(path)
    dependency = dependency_copy(tmp_path)
    root = tmp_path / "build_dependencies" / "GameFolder"
    invoked = []
    original_bind = local_entry.make_run_dependency_api_reassessment_augmentation

    def mutate():
        if mutation == "modify":
            (root / "dependency.dll").write_bytes(b"changed dependency")
        elif mutation == "add":
            (root / "extra.dll").write_bytes(b"extra dependency")
        elif mutation == "remove":
            (root / "dependency.dll").unlink()

    def tools(projection, retrieved):
        invoked.append((projection, retrieved))
        if when == "during":
            mutate()
        return "candidate evidence"

    def bind(**kwargs):
        original, receipt = original_bind(**kwargs)
        tools.query_capabilities = original.query_capabilities
        return tools, receipt

    monkeypatch.setattr(local_entry, "make_run_dependency_api_reassessment_augmentation", bind)
    bound, _ = config.bind(run_root=tmp_path, run_id="r", game_folder_dependency=dependency)
    if when == "before":
        mutate()
    if when is None:
        assert bound({}, "retrieved") == "candidate evidence"
    else:
        with pytest.raises(ValueError, match="DEPENDENCY_API_RUN_COPY_CHANGED"):
            bound({}, "retrieved")
    assert len(invoked) == (0 if when == "before" else 1)


@pytest.mark.parametrize("factory, expected", [(None, "GAME_FOLDER_BINDING_REQUIRED"), (lambda *_: None, "FACTORY_CONFLICT")])
def test_run_rejects_missing_scope_or_conflicting_factory_before_work(tmp_path, factory, expected):
    path, _ = configuration(tmp_path)
    with pytest.raises(local_entry.LocalEntryError, match=expected):
        local_entry.run_local_request(description="request", target_project=tmp_path / "missing",
            workspace_base=tmp_path / "runs", settings_path="missing", local_ollama=True,
            confirm_isolated_write=True, allow_build=True, allow_source_disclosure=False,
            defer_approval=True, task_model_call_limit=1, dependency_api_config=path,
            initial_findings_source_augmentation_factory=factory)
    assert not (tmp_path / "runs").exists()


def test_cli_forwards_explicit_config(tmp_path, monkeypatch, capsys):
    captured = {}
    def run(**kwargs):
        captured.update(kwargs)
        return {"status": "awaiting_approval"}
    monkeypatch.setattr("src.mod_agent.cli.run_local_request", run)
    path, _ = configuration(tmp_path)
    assert main(["run-request", "request", "--target-project", str(tmp_path),
                 "--dependency-api-config", str(path)]) == 0
    assert captured["dependency_api_config"] == str(path)
    assert json.loads(capsys.readouterr().out)["status"] == "awaiting_approval"
