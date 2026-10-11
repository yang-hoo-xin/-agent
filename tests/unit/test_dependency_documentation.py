"""Bound local XML snippets are optional reference context, never edit authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.mod_agent.local_entry import _binary_tree_snapshot, _binary_tree_snapshot_sha256
from src.mod_agent.proposal.dependency_documentation import (
    DependencyDocumentationError,
    prepare_dependency_documentation,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Dependency context checks must not use a model or network.")
    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("socket.socket.connect_ex", forbidden)


def _setup(tmp_path, *, source=None, xml=None):
    fixtures = Path(__file__).parents[1] / "fixtures"
    source = source if source is not None else (fixtures / "patch_eval/accurate_crosshair/AccurateCrosshair/Configuration.cs").read_bytes()
    xml = xml if xml is not None else (fixtures / "dependency_config_members.xml").read_bytes()
    root = tmp_path / "run"
    target = root / "generated_mods/Example/Configuration.cs"
    target.parent.mkdir(parents=True)
    target.write_bytes(source)
    dependency = root / "build_dependencies/GameFolder"
    document = dependency / "BepInEx/core/BepInEx.Core.xml"
    document.parent.mkdir(parents=True)
    document.write_bytes(xml)
    manifest = {"build_dependency": {"game_folder": {
        "isolated_copy": str(dependency), "build_uses_isolated_copy": True,
        "copy_snapshot_sha256": _binary_tree_snapshot_sha256(_binary_tree_snapshot(dependency)),
    }}, "dependency_documentation_policy": {
        "policy_version": "bound_xml_members_v1", "max_members": 8, "max_context_chars": 6000,
    }}
    (root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    plan = {"binding_registry": {"edit_bindings": [{"binding_id": "edit_binding_001",
        "canonical_target_path": target.relative_to(root).as_posix(),
        "source_hash": hashlib.sha256(source).hexdigest(),
        "target_span": {"start_line": 1, "end_line": len(source.splitlines())}}]}}
    return root, target, document, manifest, plan


def test_current_config_identifiers_select_actual_bind_parameter_documentation(tmp_path):
    root, _, document, _, plan = _setup(tmp_path)
    context = prepare_dependency_documentation(workspace_root=root, implementation_plan=plan)
    assert context is not None
    bundle = context.model_view()
    assert len(bundle["entries"]) == 3
    assert all("ConfigFile.Bind" in row["member_locator"] for row in bundle["entries"])
    assert all('name="defaultValue"' in row["xml_member"] for row in bundle["entries"])
    assert all("Value of the setting if the setting was not created yet." in row["xml_member"] for row in bundle["entries"])
    assert all(row["xml_sha256"] == hashlib.sha256(document.read_bytes()).hexdigest() for row in bundle["entries"])
    assert len(json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))) <= 6000
    assert bundle["authority"] == "read_only_reference"
    context.validate()


@pytest.mark.parametrize("message", [
    "'ManualLogSource' does not contain a definition for 'Info'",
    "“ManualLogSource”未包含“Info”的定义，并且找不到可接受第一个类型参数的扩展方法",
])
def test_compiler_receiver_type_supplies_real_members_even_when_source_guess_is_wrong(tmp_path, message):
    xml = b'<doc><members><member name="M:BepInEx.Logging.ManualLogSource.LogInfo(System.Object)"><summary>Log an info entry.</summary></member></members></doc>'
    root, _, document, _, plan = _setup(tmp_path, source=b'public void Load() { Log.Info("Ready"); }', xml=xml)
    assert prepare_dependency_documentation(workspace_root=root, implementation_plan=plan) is None
    bound = prepare_dependency_documentation(workspace_root=root, implementation_plan=plan,
        compiler_diagnostics=[{"code": "CS1061", "severity": "error", "message": message}])
    assert bound.model_view()["compiler_receiver_types"] == ["ManualLogSource"]
    assert bound.model_view()["entries"][0]["member_locator"].endswith("LogInfo(System.Object)")
    assert bound.model_view()["behavior_execution_proven"] is False
    document.write_bytes(xml + b' ')
    with pytest.raises(DependencyDocumentationError, match="SOURCE_CHANGED"):
        bound.validate()


def test_untyped_error_does_not_invent_api_receiver(tmp_path):
    root, _, _, _, plan = _setup(tmp_path, source=b'public void Load() { Logger.Info("Ready"); }')
    assert prepare_dependency_documentation(workspace_root=root, implementation_plan=plan,
        compiler_diagnostics=[{"code": "CS0103", "severity": "error", "message": "ManualLogSource does not exist"}]) is None


@pytest.mark.parametrize("source", [
    b"ConfigFile instance; OtherMember();", b"AnotherType instance; instance.Bind();",
    b'// ConfigFile Bind\nstring text = "ConfigFile Bind";',
])
def test_both_source_identifiers_are_required_and_comments_are_not_code(tmp_path, source):
    root, _, _, _, plan = _setup(tmp_path, source=source)
    assert prepare_dependency_documentation(workspace_root=root, implementation_plan=plan) is None


@pytest.mark.parametrize("absence", ["policy", "binding", "xml", "malformed", "unsupported", "plan"])
def test_optional_missing_or_unsupported_documentation_does_not_block_patch(tmp_path, absence):
    root, _, document, manifest, plan = _setup(tmp_path)
    if absence == "policy":
        manifest.pop("dependency_documentation_policy")
    elif absence == "binding":
        manifest["build_dependency"]["game_folder"] = None
    elif absence == "xml":
        document.unlink()
    elif absence == "malformed":
        document.write_text("<broken")
    elif absence == "unsupported":
        document.write_text('<!DOCTYPE doc [<!ENTITY x "ConfigFile">]><doc/>')
    else:
        plan["binding_registry"]["edit_bindings"] = []
    if absence in {"xml", "malformed", "unsupported"}:
        dependency = manifest["build_dependency"]["game_folder"]
        dependency["copy_snapshot_sha256"] = _binary_tree_snapshot_sha256(
            _binary_tree_snapshot(Path(dependency["isolated_copy"])))
    (root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert prepare_dependency_documentation(workspace_root=root, implementation_plan=plan) is None


def test_stable_member_and_character_budget_never_truncates_a_member(tmp_path):
    root, _, _, manifest, plan = _setup(tmp_path)
    manifest["dependency_documentation_policy"]["max_members"] = 1
    (root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    first = prepare_dependency_documentation(workspace_root=root, implementation_plan=plan).model_view()
    again = prepare_dependency_documentation(workspace_root=root, implementation_plan=plan).model_view()
    assert first == again and len(first["entries"]) == 1
    assert first["entries"][0]["xml_member"].endswith("</member>")
    manifest["dependency_documentation_policy"]["max_context_chars"] = 100
    (root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert prepare_dependency_documentation(workspace_root=root, implementation_plan=plan) is None


@pytest.mark.parametrize("source,expected", [(b"var x = new ExampleType();", True), (b"ExampleType x;", False)])
def test_constructor_requires_new_type_in_current_bound_source(tmp_path, source, expected):
    xml = b'<doc><members><member name="M:Library.ExampleType.#ctor"><summary>Creates an instance.</summary></member></members></doc>'
    root, _, _, _, plan = _setup(tmp_path, source=source, xml=xml)
    assert (prepare_dependency_documentation(workspace_root=root, implementation_plan=plan) is not None) is expected


@pytest.mark.parametrize("change", ["source", "xml", "manifest", "unselected_dependency"])
def test_after_binding_only_consumed_files_and_declared_identity_must_remain_current(tmp_path, monkeypatch, change):
    root, source, document, manifest, plan = _setup(tmp_path)
    context = prepare_dependency_documentation(workspace_root=root, implementation_plan=plan)
    assert context is not None
    monkeypatch.setattr("src.mod_agent.build.dependencies._binary_tree_snapshot", lambda _root:
        pytest.fail("Per-turn validation must not rescan unrelated dependency files."))
    if change == "source":
        source.write_bytes(source.read_bytes() + b"\n// drift")
    elif change == "xml":
        document.write_bytes(document.read_bytes() + b"\n")
    elif change == "manifest":
        manifest["build_dependency"]["game_folder"]["copy_snapshot_sha256"] = "b" * 64
        (root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    else:
        (document.parent / "unselected.dll").write_bytes(b"new unrelated bytes")
        context.validate()
        return
    with pytest.raises(DependencyDocumentationError):
        context.validate()


def test_initial_full_dependency_binding_is_verified_before_documentation_is_given(tmp_path):
    root, _, document, _, plan = _setup(tmp_path)
    document.write_bytes(document.read_bytes() + b"\n")
    with pytest.raises(DependencyDocumentationError, match="SNAPSHOT_CHANGED"):
        prepare_dependency_documentation(workspace_root=root, implementation_plan=plan)


@pytest.mark.parametrize("damage", ["delete", "no_members", "malformed"])
def test_bound_document_cannot_hide_drift_by_removing_all_matches(tmp_path, damage):
    root, _, document, _, plan = _setup(tmp_path)
    if damage == "delete":
        document.unlink()
    else:
        document.write_text("<doc><members/></doc>" if damage == "no_members" else "<broken")
    with pytest.raises(DependencyDocumentationError, match="SNAPSHOT_CHANGED"):
        prepare_dependency_documentation(workspace_root=root, implementation_plan=plan)


def test_document_bytes_must_still_match_initial_snapshot_when_read(tmp_path, monkeypatch):
    root, _, document, _, plan = _setup(tmp_path)
    original = _binary_tree_snapshot

    def snapshot_then_drift(selected):
        snapshot = original(selected)
        document.write_bytes(document.read_bytes() + b"\n")
        return snapshot

    monkeypatch.setattr("src.mod_agent.build.dependencies._binary_tree_snapshot", snapshot_then_drift)
    with pytest.raises(DependencyDocumentationError, match="SNAPSHOT_CHANGED"):
        prepare_dependency_documentation(workspace_root=root, implementation_plan=plan)


@pytest.mark.parametrize("escape", ["dependency", "source"])
def test_paths_cannot_escape_selected_run(tmp_path, escape):
    root, _, _, manifest, plan = _setup(tmp_path)
    if escape == "dependency":
        manifest["build_dependency"]["game_folder"]["isolated_copy"] = str(tmp_path)
        (root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    else:
        plan["binding_registry"]["edit_bindings"][0]["canonical_target_path"] = "../outside.cs"
    with pytest.raises(DependencyDocumentationError, match="PATH_INVALID"):
        prepare_dependency_documentation(workspace_root=root, implementation_plan=plan)


@pytest.mark.parametrize("when", ["before", "after"])
def test_selected_document_drift_rejects_model_boundary_without_faking_response(tmp_path, when):
    root, _, document, _, plan = _setup(tmp_path)
    context = prepare_dependency_documentation(workspace_root=root, implementation_plan=plan)
    called = []

    def complete(request):
        called.append(request)
        if when == "after":
            document.write_bytes(document.read_bytes() + b"\n")
        return "recorded response"

    client = context.bind_client(SimpleNamespace(provider="ollama_chat_local", model="controlled", complete_turn=complete))
    if when == "before":
        document.write_bytes(document.read_bytes() + b"\n")
    with pytest.raises(DependencyDocumentationError, match="SOURCE_CHANGED"):
        client.complete_turn("request")
    assert len(called) == int(when == "after")


@pytest.mark.parametrize("enabled,external,post_drift", [
    (False, False, False), (True, False, False), (True, True, False), (True, False, True),
])
def test_real_patch_adapter_sends_optional_documentation_in_native_context(tmp_path, monkeypatch, enabled, external, post_drift):
    from src.mod_agent.fresh_planning_continuation import run_fresh_patch_continuation
    from src.mod_agent.local_entry import make_exact_no_write_dry_run_factory
    from tests.unit import test_fresh_planning_continuation as fixture
    from tests.unit.test_patch_behavior_feedback import _adapter, _BehaviorClient, _BehaviorOracle

    ordinary_sources = fixture._write_sources

    def sources(workspace):
        source = ordinary_sources(workspace)
        source.write_text(source.read_text().replace("KeepExistingFeedback();",
            "ExampleApi api = new ExampleApi(); api.Read(); KeepExistingFeedback();"))
        return source

    monkeypatch.setattr(fixture, "_write_sources", sources)
    inputs = fixture._inputs(tmp_path)
    request = fixture._patch_request(inputs)
    dependency = inputs.workspace / "build_dependencies/GameFolder"
    dependency.mkdir(parents=True)
    document = dependency / "Library.xml"
    document.write_text('<doc><members><member name="M:Library.ExampleApi.Read">'
        '<summary>Synthetic current API documentation.</summary></member></members></doc>')
    from src.mod_agent.proposal.dependency_documentation import documentation_policy
    (inputs.workspace / "run_manifest.json").write_text(json.dumps({
        "dependency_documentation_policy": documentation_policy(), "build_dependency": {"game_folder": {
            "isolated_copy": str(dependency), "build_uses_isolated_copy": True,
            "copy_snapshot_sha256": _binary_tree_snapshot_sha256(_binary_tree_snapshot(dependency)),
        }}}))
    client = _BehaviorClient()
    if external:
        client.provider = "external_test"
    adapter = _adapter(inputs, client, _BehaviorOracle(tmp_path / "checks"))
    adapter.dependency_documentation_enabled = enabled
    if post_drift:
        adapter.enable_recovery_loop = True
        ordinary_complete = client.complete_turn

        def respond_then_drift(request):
            response = ordinary_complete(request)
            document.write_bytes(document.read_bytes() + b"\n")
            return response

        client.complete_turn = respond_then_drift
    result = run_fresh_patch_continuation(request, patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace),
        max_model_calls=adapter.patch_agent_loop_policy.max_total_model_turns)
    if post_drift:
        assert result.status != "terminal"
        assert result.patch_proposal_artifact is None
        assert len(client.requests) == 1
        factory = json.loads(Path(result.attempt_receipt["path"]).read_text(encoding="utf-8"))["factory_receipt"]
        turn = factory["worker_turns"][0]
        assert turn["status"] == "responded"
        assert turn["usage"]["input_tokens"] == 40 and turn["usage"]["output_tokens"] == 5
        raw = Path(turn["response_ref"]["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == turn["response_ref"]["sha256"]
        assert json.loads(raw)["tool_calls"]
        assert "PATCH_DEPENDENCY_DOCUMENTATION_SOURCE_CHANGED" in json.dumps(result.to_dict())
        return
    if external:
        assert result.status != "terminal"
        assert client.requests == []
        assert result.patch_proposal_artifact is None
        assert "PATCH_DEPENDENCY_DOCUMENTATION_LOCAL_ONLY" in json.dumps(result.to_dict())
        return
    assert result.status == "terminal", result
    payload = json.loads(client.requests[0].messages[1].content)
    assert ("dependency_documentation" in payload) is enabled
    if enabled:
        assert payload["dependency_documentation"]["entries"][0]["member_locator"] == "M:Library.ExampleApi.Read"
        assert payload["dependency_documentation"]["authority"] == "read_only_reference"
        assert str(inputs.workspace) not in json.dumps(payload["dependency_documentation"])


def test_normal_local_entry_records_and_enables_policy_without_changing_optional_absence(tmp_path, monkeypatch, capsys):
    from src.mod_agent.local_entry import LocalOllamaInitialPatchAdapter
    from src.mod_agent.proposal.dependency_documentation import documentation_policy
    from tests.unit.test_mod_agent_cli import _public_patch_upstream_scenario

    enabled = []
    ordinary_init = LocalOllamaInitialPatchAdapter.__init__

    def initialize(self, **kwargs):
        enabled.append(kwargs.get("dependency_documentation_enabled", False))
        ordinary_init(self, **kwargs)

    monkeypatch.setattr(LocalOllamaInitialPatchAdapter, "__init__", initialize)
    observed = _public_patch_upstream_scenario(tmp_path, monkeypatch, capsys, request_patch_upstream=False)
    assert observed.result["status"] == "awaiting_approval", observed.result
    assert enabled == [True]
    manifest = json.loads((Path(observed.result["run_root"]) / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["dependency_documentation_policy"] == documentation_policy()
    assert "dependency_documentation" not in observed.patch_contexts[0]
