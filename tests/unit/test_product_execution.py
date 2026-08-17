from __future__ import annotations

from pathlib import Path
import copy
import inspect
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.mod_agent.artifacts import ArtifactStore, ArtifactWriteResult
from src.mod_agent.build import BuildAdapter, BuildCommandResult, BuildProfile
from src.mod_agent.evidence import EvidenceItem, EvidencePack
from src.mod_agent.evidence.models import DETERMINISTIC_EVIDENCE_AUTHORITY
from src.mod_agent.execution import ExactDiffApprovalRejectedError
from src.mod_agent.runtime import (
    RuntimeEvidenceItem,
    build_real_runtime_evidence_payload,
)
from src.mod_agent.product_execution import (
    PRODUCT_EXECUTION_DECLARATION,
    ProductExecutionContractError,
    ProductExecutionInputBindingV1,
    ProductExecutionRequestV1,
    ProductExecutionResultV1,
)
from src.mod_agent.product_executor import (
    ProductExecutionAdaptersV1,
    _bind_owner_validated_runtime_evidence_factory,
    _local_model_admission_record,
    _local_no_external_disclosure_record,
    _runtime_admission_record,
    execute_product_execution,
    preflight_product_execution,
    source_snapshot,
    source_snapshot_sha256,
)


def _request(tmp_path: Path) -> tuple[ProductExecutionRequestV1, ArtifactStore]:
    source = (tmp_path / "source").resolve()
    isolated = (tmp_path / "run" / "generated_mods" / "Example").resolve()
    source.mkdir(parents=True)
    isolated.mkdir(parents=True)
    (source / "Plugin.cs").write_text("sealed class Plugin {}\n", encoding="utf-8")
    (isolated / "Plugin.cs").write_text("sealed class Plugin {}\n", encoding="utf-8")
    store = ArtifactStore((tmp_path / "run" / "a").resolve())
    return (
        ProductExecutionRequestV1(
            contract_version="1",
            run_id="run_product_001",
            request_id="request_product_001",
            user_request="make the example behavior explicit",
            target_domain="gtfo",
            target_mod="Example",
            requested_completion_scope="compile_only",
            repair_budget=2,
            isolated_workspace_root=str((tmp_path / "run").resolve()),
            isolated_target_root=str(isolated),
            source_root=str(source),
            artifact_store_root=str(store.root),
            source_snapshot_sha256=source_snapshot_sha256(source_snapshot(source)),
            isolated_source_snapshot_sha256=source_snapshot_sha256(
                source_snapshot(isolated)
            ),
            input_bindings=tuple(
                ProductExecutionInputBindingV1.create(kind, payload)
                for kind, payload in (
                    ("source_revision_binding", None),
                    ("source_disclosure", _local_no_external_disclosure_record()),
                    (
                        "model_admission",
                        _local_model_admission_record(
                            model_identity={
                                "name": "deterministic-test",
                                "digest": "sha256:" + "1" * 64,
                                "base_url": "http://127.0.0.1:11434",
                            },
                            provider_adapter="deterministic_test",
                        ),
                    ),
                    (
                        "runtime_admission",
                        _runtime_admission_record(
                            object(),
                            run_gtfo_runtime=False,
                            allow_game_launch=False,
                            runtime_plugin_destination=None,
                            allow_game_directory_write=False,
                        ),
                    ),
                )
            ),
            completion_classification=(),
            confirmed_isolated_write=True,
            allow_build=True,
        ),
        store,
    )


def _blocked_evidence_adapters() -> ProductExecutionAdaptersV1:
    return ProductExecutionAdaptersV1(
        evidence_pack_factory=lambda _state, _feature: EvidencePack(
            query="missing symbol",
            readiness="insufficient",
            can_generate_patch=False,
            blockers=(
                {
                    "code": "PRODUCT_EVIDENCE_MISSING",
                    "message": "Required source evidence is missing.",
                },
            ),
        ),
        patch_change_factory=lambda *_: (),
        dry_run_factory=lambda *_: {},
        isolated_apply_factory=lambda *_: {},
        build_result_factory=lambda *_: (_ for _ in ()).throw(
            AssertionError("Build must not run on the early blocked route")
        ),
        runtime_evidence_factory=None,
        compiled_artifact_verifier=None,
        source_change_verifier=None,
    )


def _successful_compile_adapters(
    request: ProductExecutionRequestV1,
    *,
    build_exit_codes: list[int] | None = None,
) -> ProductExecutionAdaptersV1:
    source_path = "generated_mods/Example/Plugin.cs"
    diff_hash = "sha256:" + "d" * 64
    remaining_build_exit_codes = list(build_exit_codes or [0])

    def evidence_pack_factory(_state, _feature):
        return EvidencePack(
            query=request.user_request,
            readiness="sufficient",
            can_generate_patch=True,
            items=(
                EvidenceItem(
                    evidence_id="evidence_product_compile_001",
                    source_type="target_source",
                    source_path=source_path,
                    symbol="Load",
                    span={"start_line": 1, "end_line": 1},
                    retrieval_method="symbol_exact",
                    score=1.0,
                    claim_supported="Load is the exact selected source symbol.",
                    excerpt="public void Load() {}",
                    source_hash="a" * 64,
                    authority=DETERMINISTIC_EVIDENCE_AUTHORITY,
                ),
            ),
            retrieval_methods_used=("symbol_exact",),
        )

    def patch_change_factory(_state, implementation, _evidence_pack):
        changes = copy.deepcopy(implementation["proposed_changes"])
        assert len(changes) == 1
        changes[0]["patch"] = {
            "kind": "exact_text_replace",
            "before_text": "public void Load() {}",
            "after_text": "public void Load() { /* product */ }",
            "expected_occurrences": 1,
        }
        return tuple(changes)

    def dry_run_factory(_proposal, _implementation, _review):
        return {
            "execution_mode": "dry_run",
            "diff_hash": diff_hash,
            "unified_diff": "--- Plugin.cs\n+++ Plugin.cs\n",
            "actual_write_performed": False,
            "real_patch_applied": False,
            "changed_files": [source_path],
        }

    def isolated_apply_factory(_proposal, _implementation, _review):
        return {
            "execution_mode": "isolated_apply",
            "actual_write_performed": True,
            "real_patch_applied": True,
            "approved_by_review": True,
            "approved_by_user": True,
            "changed_files": [source_path],
            "diff_hash": diff_hash,
            "approved_diff_hash": diff_hash,
        }

    def build_result_factory(feature_id, input_execution_mode):
        build_root = Path(request.isolated_target_root)
        expected = build_root / "bin" / "Debug" / "Example.dll"

        def runner(_profile):
            exit_code = remaining_build_exit_codes.pop(0)
            if exit_code == 0:
                expected.parent.mkdir(parents=True, exist_ok=True)
                expected.write_bytes(b"deterministic product build")
            return BuildCommandResult(
                exit_code=exit_code,
                stdout="Build succeeded" if exit_code == 0 else "Build failed",
                stderr=(
                    ""
                    if exit_code == 0
                    else (
                        f"{source_path}(1,1): error CS0246: "
                        "The type or namespace name 'Missing' could not be found"
                    )
                ),
                duration_ms=3,
            )

        return BuildAdapter().run_local(
            feature_id=feature_id,
            profile=BuildProfile(
                profile_id="product_compile_test",
                build_system="dotnet",
                working_directory=str(build_root),
                command=("dotnet", "build"),
                timeout_seconds=30,
                expected_artifacts=("bin/Debug/Example.dll",),
            ),
            command_runner=runner,
            allow_execution=True,
            input_execution_mode=input_execution_mode,
        )

    return ProductExecutionAdaptersV1(
        evidence_pack_factory=evidence_pack_factory,
        patch_change_factory=patch_change_factory,
        dry_run_factory=dry_run_factory,
        isolated_apply_factory=isolated_apply_factory,
        build_result_factory=build_result_factory,
        runtime_evidence_factory=None,
        compiled_artifact_verifier=None,
        source_change_verifier=None,
    )


def _install_actual_store_failure(
    monkeypatch: pytest.MonkeyPatch,
    store: ArtifactStore,
    *,
    artifact_role: str,
    outcome: str,
    occurrence: int = 1,
) -> None:
    original_write_with_result = store.write_with_result
    original_write_text = store._write_text_atomic
    state: dict[str, object] = {
        "active": False,
        "count": 0,
        "latest_path": None,
    }

    def fail_commit_path(
        path: Path,
        content: str,
        *,
        capture_replace_error: bool = False,
    ) -> None:
        if state["active"] is True:
            if outcome == "blocked_before_commit" and path.parent.parent.name == "p":
                raise OSError(f"injected {artifact_role} pending failure")
            if outcome == "partial" and path == state["latest_path"]:
                raise OSError(f"injected {artifact_role} latest failure")
        original_write_text(
            path,
            content,
            capture_replace_error=capture_replace_error,
        )

    def write_with_result(**kwargs):
        selected = kwargs["artifact_type"] == artifact_role
        if selected:
            state["count"] = int(state["count"]) + 1
        active = selected and state["count"] == occurrence
        state["active"] = active
        state["latest_path"] = (
            store._artifact_path(kwargs["feature_id"], artifact_role)
            if active
            else None
        )
        try:
            return original_write_with_result(**kwargs)
        finally:
            state["active"] = False
            state["latest_path"] = None

    monkeypatch.setattr(store, "_write_text_atomic", fail_commit_path)
    monkeypatch.setattr(store, "write_with_result", write_with_result)


def _runtime_owner_binding(
    tmp_path: Path,
) -> tuple[dict[str, object], SimpleNamespace, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    executable = tmp_path / "GTFO.exe"
    executable.write_bytes(b"test executable")
    config = tmp_path / "BepInEx" / "config" / "BepInEx.cfg"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("[Logging.Disk]\nAppendLog = false\n", encoding="utf-8")
    destination = tmp_path / "BepInEx" / "plugins" / "Example.dll"
    destination.parent.mkdir(parents=True, exist_ok=True)
    settings = SimpleNamespace(
        runtime=SimpleNamespace(
            gtfo=SimpleNamespace(
                enabled=True,
                game_executable=str(executable),
                working_directory=str(tmp_path),
                launch_args=["-test"],
                log_paths=["BepInEx/LogOutput.log"],
                screenshot_directory=str(tmp_path / "screenshots"),
                screenshot_timeout_seconds=15,
                startup_markers=["Chainloader startup complete"],
                acceptance_markers={"behavior works": "BEHAVIOR_OK"},
                timeout_seconds=120,
                poll_interval_seconds=1.0,
                output_limit_chars=20_000,
                terminate_after_capture=True,
            )
        )
    )
    record = _runtime_admission_record(
        settings,
        run_gtfo_runtime=True,
        allow_game_launch=True,
        runtime_plugin_destination=destination,
        allow_game_directory_write=True,
    )
    return record, settings, destination


def _runtime_request_and_adapters(
    tmp_path: Path,
    *,
    diagnosed_binding_gap: bool = False,
    terminal_runtime_repair: bool = False,
    exhausted_runtime_repair: bool = False,
    build_exit_codes: list[int] | None = None,
) -> tuple[ProductExecutionRequestV1, ArtifactStore, ProductExecutionAdaptersV1]:
    request, store = _request(tmp_path)
    Path(request.isolated_target_root, "Plugin.cs").write_text(
        "public void Load() {}\n", encoding="utf-8"
    )
    values = request.to_dict()
    values["requested_completion_scope"] = "runtime_workflow"
    values["isolated_source_snapshot_sha256"] = source_snapshot_sha256(
        source_snapshot(Path(request.isolated_target_root))
    )
    runtime_admission, runtime_settings, runtime_destination = (
        _runtime_owner_binding(tmp_path / "runtime")
    )
    values["input_bindings"][3] = ProductExecutionInputBindingV1.create(
        "runtime_admission", runtime_admission
    ).to_dict()
    request = ProductExecutionRequestV1.from_dict(values)
    base = _successful_compile_adapters(
        request,
        build_exit_codes=build_exit_codes,
    )

    def runtime_evidence_factory(feature_id, build, feature_spec):
        criteria = tuple(str(item) for item in feature_spec["acceptance_criteria"])
        if terminal_runtime_repair or exhausted_runtime_repair:
            return build_real_runtime_evidence_payload(
                feature_id=feature_id,
                input_execution_mode=str(build["execution_mode"]),
                evidence_items=(),
                startup_loaded=True,
                gameplay_behavior_verified=False,
                verification_status="failed",
                raw_runtime_output="Runtime observation requires new evidence.",
                acceptance_criteria=criteria,
                runtime_verification_plan=tuple(
                    str(item) for item in feature_spec["runtime_verification_plan"]
                ),
                failure_ownership=(
                    {
                        "owner": "product_behavior",
                        "failure_class": "product_behavior",
                        "source_repair_allowed": True,
                        "required_action": "repair_product_behavior",
                        "reason": "A bound product criterion is false.",
                    }
                    if exhausted_runtime_repair
                    else {
                        "owner": "observation",
                        "failure_class": "runtime_observation_incomplete",
                        "source_repair_allowed": False,
                        "required_action": "collect_runtime_evidence",
                        "reason": "The observation does not authorize source repair.",
                    }
                ),
            )
        if diagnosed_binding_gap:
            payload = build_real_runtime_evidence_payload(
                feature_id=feature_id,
                input_execution_mode=str(build["execution_mode"]),
                evidence_items=(),
                startup_loaded=True,
                gameplay_behavior_verified=False,
                verification_status="failed",
                raw_runtime_output=(
                    "signal=PRODUCT_RUNTIME_FAILED "
                    "reason=unresolved_runtime_binding"
                ),
                acceptance_criteria=criteria,
                runtime_verification_plan=tuple(
                    str(item) for item in feature_spec["runtime_verification_plan"]
                ),
                failure_ownership={
                    "owner": "product_behavior",
                    "failure_class": "product_behavior",
                    "source_repair_allowed": True,
                    "required_action": "repair_product_behavior",
                    "reason": "A bound product criterion is false.",
                },
            )
            payload["runtime_failure_diagnosis"] = {
                "schema_version": "stagger_runtime_failure_diagnosis_v1",
                "status": "diagnosed",
                "feature_id": feature_id,
                "failure_class": "product_behavior",
                "evidence_refs": [
                    {
                        "source": "deterministic_product_runtime",
                        "locator": "runtime://binding-gap",
                    }
                ],
                "responsibility_anchors": {
                    "component": "ui_attachment",
                    "symbol": "Example.Plugin.Load",
                    "dependency": "runtime binding",
                    "repair_scope": ["runtime_binding"],
                    "source_hash": None,
                    "source_span": None,
                },
                "root_cause_status": "unresolved",
                "unresolved_root_causes": ["runtime_binding_unresolved"],
            }
            return payload
        return build_real_runtime_evidence_payload(
            feature_id=feature_id,
            input_execution_mode=str(build["execution_mode"]),
            evidence_items=(
                RuntimeEvidenceItem(
                    item_type="runtime_log",
                    source="deterministic_product_runtime",
                    locator="runtime://product-001",
                    supports_acceptance=criteria,
                    confidence=1.0,
                    raw_excerpt="Runtime observed the requested behavior.",
                ),
            ),
            startup_loaded=True,
            gameplay_behavior_verified=True,
            verification_status="verified",
            raw_runtime_output="Runtime observed the requested behavior.",
            acceptance_criteria=criteria,
            runtime_verification_plan=tuple(
                str(item) for item in feature_spec["runtime_verification_plan"]
            ),
            plugin_marker_binding={
                "marker_source": "deterministic_product_runtime",
                "markers": [
                    {
                        "acceptance_criterion": criterion,
                        "marker": f"MARKER_{index}",
                        "observed": True,
                    }
                    for index, criterion in enumerate(criteria, start=1)
                ],
            },
        )

    adapters = replace(
        base,
        runtime_evidence_factory=_bind_owner_validated_runtime_evidence_factory(
            runtime_evidence_factory,
            settings=runtime_settings,
            allow_game_launch=True,
            runtime_plugin_destination=runtime_destination,
            allow_game_directory_write=True,
            expected_runtime_admission=runtime_admission,
        ),
    )
    return request, store, adapters


def _execute_store_role_scenario(
    tmp_path: Path,
    *,
    scenario: str,
    monkeypatch: pytest.MonkeyPatch | None = None,
    failure_role: str | None = None,
    failure_outcome: str | None = None,
    failure_occurrence: int = 1,
) -> ProductExecutionResultV1:
    if scenario in {
        "runtime",
        "runtime_terminal",
        "runtime_terminal_max",
        "runtime_max",
        "binding",
    }:
        request, store, adapters = _runtime_request_and_adapters(
            tmp_path,
            diagnosed_binding_gap=scenario == "binding",
            terminal_runtime_repair=scenario
            in {"runtime_terminal", "runtime_terminal_max"},
            exhausted_runtime_repair=scenario == "runtime_max",
            build_exit_codes=(
                [1, 1, 0]
                if scenario in {"runtime_terminal_max", "runtime_max"}
                else None
            ),
        )
    else:
        request, store = _request(tmp_path)
        if scenario == "blocked":
            adapters = _blocked_evidence_adapters()
        else:
            Path(request.isolated_target_root, "Plugin.cs").write_text(
                "public void Load() {}\n", encoding="utf-8"
            )
            values = request.to_dict()
            values["isolated_source_snapshot_sha256"] = source_snapshot_sha256(
                source_snapshot(Path(request.isolated_target_root))
            )
            request = ProductExecutionRequestV1.from_dict(values)
            adapters = _successful_compile_adapters(
                request,
                build_exit_codes=(
                    [1, 1]
                    if scenario == "review_max"
                    else [1, 1, 1]
                    if scenario == "repair"
                    else [0]
                ),
            )
            if scenario in {"review", "review_max"}:
                original_patch_factory = adapters.patch_change_factory

                def invalid_review_patch(state, *args):
                    items = original_patch_factory(state, *args)
                    should_block = scenario == "review" or state["retry_count"] == 2
                    return tuple(
                        {**item, "expected_validation": []}
                        if should_block
                        else item
                        for item in items
                    )

                adapters = replace(
                    adapters,
                    patch_change_factory=invalid_review_patch,
                )
    if failure_role is not None:
        assert monkeypatch is not None and failure_outcome is not None
        _install_actual_store_failure(
            monkeypatch,
            store,
            artifact_role=failure_role,
            outcome=failure_outcome,
            occurrence=failure_occurrence,
        )
    return execute_product_execution(
        preflight_product_execution(request, adapters, store), adapters, store
    )


def test_public_product_executor_runs_real_graph_and_strict_store_chain(
    tmp_path: Path,
) -> None:
    request, store = _request(tmp_path)
    adapters = _blocked_evidence_adapters()

    preflight = preflight_product_execution(request, adapters, store)
    result = execute_product_execution(preflight, adapters, store)

    assert preflight.preflight_status == "ready"
    assert result.platform_status == "completed"
    assert result.execution_disposition == "domain_blocked"
    assert result.terminal_node == "blocked"
    assert [item.artifact_role for item in result.store_attempts] == [
        "request_planning_report",
        "mod_planning_brief",
        "feature_spec",
        "evidence_pack",
        "implementation_plan",
        "blocked_report",
    ]
    assert all(
        item.store_result.outcome == "committed" for item in result.store_attempts
    )
    assert ProductExecutionResultV1.from_dict(result.to_dict()) == result


def test_product_preflight_rejects_snapshot_drift_without_graph_or_store(
    tmp_path: Path,
) -> None:
    request, store = _request(tmp_path)
    Path(request.isolated_target_root, "Plugin.cs").write_text(
        "sealed class Changed {}\n", encoding="utf-8"
    )

    preflight = preflight_product_execution(
        request, _blocked_evidence_adapters(), store
    )

    assert preflight.preflight_status == "blocked"
    assert [item.code for item in preflight.blockers] == [
        "PRODUCT_ISOLATED_SNAPSHOT_DRIFT"
    ]
    assert not store.root.exists()


def test_compile_preflight_accepts_owner_runtime_record_with_enabled_settings(
    tmp_path: Path,
) -> None:
    request, store = _request(tmp_path)
    values = request.to_dict()
    settings = SimpleNamespace(
        runtime=SimpleNamespace(gtfo=SimpleNamespace(enabled=True))
    )
    runtime_admission = _runtime_admission_record(
        settings,
        run_gtfo_runtime=False,
        allow_game_launch=False,
        runtime_plugin_destination=None,
        allow_game_directory_write=False,
    )
    values["input_bindings"][3] = ProductExecutionInputBindingV1.create(
        "runtime_admission", runtime_admission
    ).to_dict()
    request = ProductExecutionRequestV1.from_dict(values)

    preflight = preflight_product_execution(
        request, _blocked_evidence_adapters(), store
    )

    assert preflight.preflight_status == "ready"
    assert not store.root.exists()


def test_product_preflight_returns_structured_blocked_for_binding_drift(
    tmp_path: Path,
) -> None:
    request, store = _request(tmp_path)
    values = request.to_dict()
    disclosure = copy.deepcopy(values["input_bindings"][1]["canonical_payload"])
    disclosure["reason"] = "caller_selected_reason"
    values["input_bindings"][1] = ProductExecutionInputBindingV1.create(
        "source_disclosure", disclosure
    ).to_dict()
    request = ProductExecutionRequestV1.from_dict(values)

    preflight = preflight_product_execution(
        request, _blocked_evidence_adapters(), store
    )

    assert preflight.preflight_status == "blocked"
    assert preflight.failure_stage == "admission"
    assert [item.code for item in preflight.blockers] == [
        "PRODUCT_INPUT_BINDING_ADMISSION_FAILED"
    ]
    assert not store.root.exists()


def test_product_preflight_rejects_unbound_runtime_adapter(
    tmp_path: Path,
) -> None:
    request, store = _request(tmp_path)
    values = request.to_dict()
    values["requested_completion_scope"] = "runtime_workflow"
    values["input_bindings"][3] = ProductExecutionInputBindingV1.create(
        "runtime_admission", {"requested": True, "caller_asserted": True}
    ).to_dict()
    request = ProductExecutionRequestV1.from_dict(values)
    adapters = replace(
        _blocked_evidence_adapters(), runtime_evidence_factory=lambda *_: None
    )

    preflight = preflight_product_execution(request, adapters, store)

    assert preflight.preflight_status == "blocked"
    assert preflight.failure_stage == "admission"
    assert not store.root.exists()


def test_public_product_executor_runs_exact_mutation_build_chain(
    tmp_path: Path,
) -> None:
    request, store = _request(tmp_path)
    Path(request.isolated_target_root, "Plugin.cs").write_text(
        "public void Load() {}\n", encoding="utf-8"
    )
    request_values = request.to_dict()
    request_values["isolated_source_snapshot_sha256"] = source_snapshot_sha256(
        source_snapshot(Path(request.isolated_target_root))
    )
    request = ProductExecutionRequestV1.from_dict(request_values)
    adapters = _successful_compile_adapters(request)

    preflight = preflight_product_execution(request, adapters, store)
    result = execute_product_execution(preflight, adapters, store)

    assert result.platform_status == "completed"
    assert result.execution_disposition == "succeeded"
    assert result.terminal_node == "build"
    roles = tuple(item.artifact_role for item in result.store_attempts)
    assert roles[-4:] == (
        "dry_run_result",
        "isolated_apply_result",
        "build_result",
        "workflow_checkpoint",
    )
    assert all(
        item.store_result.outcome == "committed" for item in result.store_attempts
    )
    assert tuple(item.artifact_role for item in result.outputs) == roles
    assert result.variant_result.build_status == "success"
    assert result.variant_result.workflow_checkpoint_ref is not None
    assert ProductExecutionResultV1.from_dict(result.to_dict()) == result


def test_public_product_executor_runs_exact_runtime_terminal_chain(
    tmp_path: Path,
) -> None:
    request, store = _request(tmp_path)
    source = Path(request.isolated_target_root, "Plugin.cs")
    source.write_text("public void Load() {}\n", encoding="utf-8")
    values = request.to_dict()
    values["requested_completion_scope"] = "runtime_workflow"
    values["isolated_source_snapshot_sha256"] = source_snapshot_sha256(
        source_snapshot(Path(request.isolated_target_root))
    )
    runtime_admission, runtime_settings, runtime_destination = (
        _runtime_owner_binding(tmp_path / "runtime")
    )
    values["input_bindings"][3] = ProductExecutionInputBindingV1.create(
        "runtime_admission", runtime_admission
    ).to_dict()
    request = ProductExecutionRequestV1.from_dict(values)
    base = _successful_compile_adapters(request)

    def runtime_evidence_factory(feature_id, build, feature_spec):
        criteria = tuple(str(item) for item in feature_spec["acceptance_criteria"])
        return build_real_runtime_evidence_payload(
            feature_id=feature_id,
            input_execution_mode=str(build["execution_mode"]),
            evidence_items=(
                RuntimeEvidenceItem(
                    item_type="runtime_log",
                    source="deterministic_product_runtime",
                    locator="runtime://product-001",
                    supports_acceptance=criteria,
                    confidence=1.0,
                    raw_excerpt="Runtime observed the requested behavior.",
                ),
            ),
            startup_loaded=True,
            gameplay_behavior_verified=True,
            verification_status="verified",
            raw_runtime_output="Runtime observed the requested behavior.",
            acceptance_criteria=criteria,
            runtime_verification_plan=tuple(
                str(item) for item in feature_spec["runtime_verification_plan"]
            ),
            plugin_marker_binding={
                "marker_source": "deterministic_product_runtime",
                "markers": [
                    {
                        "acceptance_criterion": criterion,
                        "marker": f"MARKER_{index}",
                        "observed": True,
                    }
                    for index, criterion in enumerate(criteria, start=1)
                ],
            },
        )

    adapters = replace(
        base,
        runtime_evidence_factory=_bind_owner_validated_runtime_evidence_factory(
            runtime_evidence_factory,
            settings=runtime_settings,
            allow_game_launch=True,
            runtime_plugin_destination=runtime_destination,
            allow_game_directory_write=True,
            expected_runtime_admission=runtime_admission,
        ),
    )
    result = execute_product_execution(
        preflight_product_execution(request, adapters, store), adapters, store
    )

    assert result.platform_status == "completed"
    assert result.execution_disposition == "succeeded"
    assert result.terminal_node == "done"
    assert tuple(item.artifact_role for item in result.store_attempts[-4:]) == (
        "build_result",
        "runtime_evidence",
        "eval_report",
        "workflow_summary",
    )
    assert all(
        item.store_result.outcome == "committed"
        for item in result.store_attempts
    )
    assert ProductExecutionResultV1.from_dict(result.to_dict()) == result


def test_public_product_executor_reaches_runtime_binding_gap_store_role(
    tmp_path: Path,
) -> None:
    request, store, adapters = _runtime_request_and_adapters(
        tmp_path, diagnosed_binding_gap=True
    )

    result = execute_product_execution(
        preflight_product_execution(request, adapters, store), adapters, store
    )

    assert result.execution_disposition == "domain_blocked"
    assert "binding_resolution" in tuple(
        item.artifact_role for item in result.store_attempts
    )
    assert ProductExecutionResultV1.from_dict(result.to_dict()) == result


def test_product_request_rejects_binding_order_drift(tmp_path: Path) -> None:
    request, _ = _request(tmp_path)
    values = request.to_dict()
    values["input_bindings"] = list(reversed(values["input_bindings"]))

    with pytest.raises(ProductExecutionContractError, match="exact ordered"):
        ProductExecutionRequestV1.from_dict(values)


def test_product_preflight_delegates_owner_records_and_rejects_scope_drift(
    tmp_path: Path,
) -> None:
    request, store = _request(tmp_path)
    values = request.to_dict()
    drifted = dict(values["input_bindings"][1]["canonical_payload"])
    drifted["scope"] = "another_run"
    values["input_bindings"][1] = ProductExecutionInputBindingV1.create(
        "source_disclosure", drifted
    ).to_dict()
    drifted_request = ProductExecutionRequestV1.from_dict(values)

    preflight = preflight_product_execution(
        drifted_request,
        _blocked_evidence_adapters(),
        store,
    )
    assert preflight.preflight_status == "blocked"
    assert preflight.failure_stage == "admission"
    assert "Source disclosure record changed" in preflight.blockers[0].message
    assert not store.root.exists()


def test_domain_blocked_result_is_not_overridden_by_completion_classification(
    tmp_path: Path,
) -> None:
    request, store = _request(tmp_path)
    values = request.to_dict()
    values["completion_classification"] = [["requested_behavior", True]]
    request = ProductExecutionRequestV1.from_dict(values)
    adapters = _blocked_evidence_adapters()

    result = execute_product_execution(
        preflight_product_execution(request, adapters, store), adapters, store
    )

    assert result.platform_status == "completed"
    assert result.execution_disposition == "domain_blocked"
    assert result.failure_stage is None
    assert result.validation_facts.completion_classification_status == "not_applicable"


def test_product_store_first_noncommitted_attempt_stops_real_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, store = _request(tmp_path)
    original = store.write_with_result

    def write_with_result(**kwargs):
        if kwargs["artifact_type"] == "patch_proposal":
            return ArtifactWriteResult(
                outcome="blocked_before_commit",
                feature_id=kwargs["feature_id"],
                artifact_type="patch_proposal",
                artifact_hash=None,
                artifact_ref=None,
                revision_path=None,
                latest_alias_path=None,
                pending_marker_path=None,
                commit_started=False,
                revision_state="absent",
                latest_alias_state="absent",
                pending_marker_state="absent",
                failure_stage="admission_validation",
                failure_class="ArtifactStoreError",
                failure_message="injected precommit failure",
                recovery_available=False,
                recovery_authorized=False,
            )
        return original(**kwargs)

    monkeypatch.setattr(store, "write_with_result", write_with_result)
    adapters = _successful_compile_adapters(request)

    result = execute_product_execution(
        preflight_product_execution(request, adapters, store), adapters, store
    )

    assert result.platform_status == "partial"
    assert result.execution_disposition == "partial"
    assert result.failure_stage == "patch_proposal_store"
    assert result.store_attempts[-1].artifact_role == "patch_proposal"
    assert result.store_attempts[-1].store_result.outcome == "blocked_before_commit"
    assert all(
        item.artifact_role not in {
            "proposal_review",
            "dry_run_result",
            "isolated_apply_result",
            "build_result",
            "workflow_checkpoint",
        }
        for item in result.store_attempts
    )
    assert tuple(item.artifact_role for item in result.outputs) == tuple(
        item.artifact_role for item in result.store_attempts[:-1]
    )


def test_store_failure_is_not_overridden_by_completion_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, store = _request(tmp_path)
    values = request.to_dict()
    values["completion_classification"] = [["requested_behavior", True]]
    request = ProductExecutionRequestV1.from_dict(values)
    original = store.write_with_result

    def write_with_result(**kwargs):
        if kwargs["artifact_type"] == "patch_proposal":
            return ArtifactWriteResult(
                outcome="blocked_before_commit",
                feature_id=kwargs["feature_id"],
                artifact_type="patch_proposal",
                artifact_hash=None,
                artifact_ref=None,
                revision_path=None,
                latest_alias_path=None,
                pending_marker_path=None,
                commit_started=False,
                revision_state="absent",
                latest_alias_state="absent",
                pending_marker_state="absent",
                failure_stage="admission_validation",
                failure_class="ArtifactStoreError",
                failure_message="injected precommit failure",
                recovery_available=False,
                recovery_authorized=False,
            )
        return original(**kwargs)

    monkeypatch.setattr(store, "write_with_result", write_with_result)
    adapters = _successful_compile_adapters(request)

    result = execute_product_execution(
        preflight_product_execution(request, adapters, store), adapters, store
    )

    assert result.failure_stage == "patch_proposal_store"
    assert result.execution_disposition == "partial"
    assert result.validation_facts.completion_classification_status == "not_applicable"


def test_domain_blocked_output_readback_failure_is_platform_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, store = _request(tmp_path)
    original = store.read

    def read(ref):
        if ref.artifact_type == "blocked_report" and any(
            frame.function == "validate_product_execution_outputs"
            for frame in inspect.stack()
        ):
            raise OSError("injected committed BlockedReport readback failure")
        return original(ref)

    monkeypatch.setattr(store, "read", read)
    adapters = _blocked_evidence_adapters()
    result = execute_product_execution(
        preflight_product_execution(request, adapters, store), adapters, store
    )

    assert result.platform_status == "partial"
    assert result.execution_disposition == "partial"
    assert result.failure_stage == "post_execution_validation"
    assert result.terminal_node == "blocked"
    assert result.validation_facts.output_readback_status == "failed"
    assert result.outputs[-1].artifact_role == "blocked_report"
    assert all(
        item.store_result.outcome == "committed"
        for item in result.store_attempts
    )


def test_graph_node_exception_uses_exact_current_node_after_completed_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, store = _request(tmp_path)
    adapters = _successful_compile_adapters(request)

    def fail_create_implementation_plan(*_args, **_kwargs):
        raise RuntimeError("injected plan construction failure")

    monkeypatch.setattr(
        "src.mod_agent.workflow.graph._run_create_implementation_plan",
        fail_create_implementation_plan,
    )
    result = execute_product_execution(
        preflight_product_execution(request, adapters, store), adapters, store
    )

    assert result.failure_stage == "create_implementation_plan_execution"
    assert result.execution_disposition == "partial"
    assert result.effect_events[-1].effect_role == "evidence_retrieval"
    assert result.effect_events[-1].event_status == "completed"
    assert all(
        item.artifact_role != "implementation_plan"
        for item in result.store_attempts
    )


def test_public_product_executor_preserves_repair_attempt_prefixes(
    tmp_path: Path,
) -> None:
    request, store = _request(tmp_path)
    Path(request.isolated_target_root, "Plugin.cs").write_text(
        "public void Load() {}\n", encoding="utf-8"
    )
    request_values = request.to_dict()
    request_values["isolated_source_snapshot_sha256"] = source_snapshot_sha256(
        source_snapshot(Path(request.isolated_target_root))
    )
    request = ProductExecutionRequestV1.from_dict(request_values)
    adapters = _successful_compile_adapters(request, build_exit_codes=[1, 0])

    result = execute_product_execution(
        preflight_product_execution(request, adapters, store), adapters, store
    )

    assert result.execution_disposition == "succeeded"
    build_attempts = [
        item for item in result.store_attempts if item.artifact_role == "build_result"
    ]
    repair_attempts = [
        item for item in result.store_attempts if item.artifact_role == "repair_plan"
    ]
    assert [item.repair_attempt for item in build_attempts] == [0, 1]
    assert [item.repair_attempt for item in repair_attempts] == [1]
    assert result.store_attempts[-1].artifact_role == "workflow_checkpoint"
    assert ProductExecutionResultV1.from_dict(result.to_dict()) == result


def test_product_repair_review_uses_ephemeral_review_context_only_on_repair(
    tmp_path: Path,
) -> None:
    request, store = _request(tmp_path)
    Path(request.isolated_target_root, "Plugin.cs").write_text(
        "public void Load() {}\n", encoding="utf-8"
    )
    request_values = request.to_dict()
    request_values["isolated_source_snapshot_sha256"] = source_snapshot_sha256(
        source_snapshot(Path(request.isolated_target_root))
    )
    request = ProductExecutionRequestV1.from_dict(request_values)
    adapters = _successful_compile_adapters(request, build_exit_codes=[1, 0])
    review_context_calls: list[str] = []

    def proposal_review_context_factory(state, implementation, evidence_pack):
        review_context_calls.append(str(state["current_stage"]))
        return implementation, evidence_pack

    adapters = replace(
        adapters,
        proposal_review_context_factory=proposal_review_context_factory,
    )

    result = execute_product_execution(
        preflight_product_execution(request, adapters, store), adapters, store
    )

    assert result.execution_disposition == "succeeded"
    assert review_context_calls == ["patch_proposal"]
    assert [
        item.repair_attempt
        for item in result.store_attempts
        if item.artifact_role == "proposal_review"
    ] == [0, 1]


def test_public_product_executor_returns_repair_budget_exhaustion_result(
    tmp_path: Path,
) -> None:
    request, store = _request(tmp_path)
    Path(request.isolated_target_root, "Plugin.cs").write_text(
        "public void Load() {}\n", encoding="utf-8"
    )
    request_values = request.to_dict()
    request_values["isolated_source_snapshot_sha256"] = source_snapshot_sha256(
        source_snapshot(Path(request.isolated_target_root))
    )
    request = ProductExecutionRequestV1.from_dict(request_values)
    adapters = _successful_compile_adapters(request, build_exit_codes=[1, 1, 1])

    result = execute_product_execution(
        preflight_product_execution(request, adapters, store), adapters, store
    )

    assert result.platform_status == "completed"
    assert result.execution_disposition == "domain_blocked"
    assert result.failure_stage is None
    selected = [
        (item.node_name, item.repair_attempt, item.artifact_role)
        for item in result.store_attempts
        if item.node_name in {"build", "create_repair_plan", "blocked"}
    ]
    assert selected == [
        ("build", 0, "build_result"),
        ("create_repair_plan", 1, "repair_plan"),
        ("build", 1, "build_result"),
        ("create_repair_plan", 2, "repair_plan"),
        ("build", 2, "build_result"),
        ("create_repair_plan", 2, "repair_plan"),
        ("blocked", 2, "blocked_report"),
    ]
    assert all(
        item.store_result.outcome == "committed" for item in result.store_attempts
    )
    assert result.blockers
    assert all(item.owner == "domain" for item in result.blockers)
    assert ProductExecutionResultV1.from_dict(result.to_dict()) == result


@pytest.mark.parametrize(
    ("scenario", "expected_tail"),
    (
        (
            "review",
            (
                ("review_proposal", 0, "proposal_review"),
                ("create_repair_plan", 1, "repair_plan"),
                ("blocked", 1, "blocked_report"),
            ),
        ),
        (
            "review_max",
            (
                ("review_proposal", 2, "proposal_review"),
                ("create_repair_plan", 2, "repair_plan"),
                ("blocked", 2, "blocked_report"),
            ),
        ),
        (
            "runtime_terminal",
            (
                ("collect_runtime_evidence", 0, "runtime_evidence"),
                ("create_repair_plan", 0, "repair_plan"),
                ("blocked", 0, "blocked_report"),
            ),
        ),
        (
            "runtime_max",
            (
                ("collect_runtime_evidence", 2, "runtime_evidence"),
                ("create_repair_plan", 2, "repair_plan"),
                ("blocked", 2, "blocked_report"),
            ),
        ),
        (
            "runtime_terminal_max",
            (
                ("collect_runtime_evidence", 2, "runtime_evidence"),
                ("create_repair_plan", 2, "repair_plan"),
                ("blocked", 2, "blocked_report"),
            ),
        ),
    ),
)
def test_owner_produced_terminal_repair_shapes_use_exact_attempt_transition(
    tmp_path: Path,
    scenario: str,
    expected_tail: tuple[tuple[str, int, str], ...],
) -> None:
    result = _execute_store_role_scenario(tmp_path, scenario=scenario)

    assert result.platform_status == "completed"
    assert result.execution_disposition == "domain_blocked"
    assert result.failure_stage is None
    selected = tuple(
        (item.node_name, item.repair_attempt, item.artifact_role)
        for item in result.store_attempts
        if item.node_name in {
            "review_proposal",
            "collect_runtime_evidence",
            "create_repair_plan",
            "blocked",
        }
    )
    assert selected[-3:] == expected_tail
    assert ProductExecutionResultV1.from_dict(result.to_dict()) == result


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("status", "success"),
        ("retry_exhausted", False),
        ("retry_count", 1),
        ("retry_budget", 3),
        ("retry_budget_remaining", 1),
        ("allowed_next_stage", "generate_patch_proposal"),
        ("blockers", []),
    ),
)
def test_strict_replay_rejects_tampered_exhausted_repair_plan(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    request, store = _request(tmp_path)
    Path(request.isolated_target_root, "Plugin.cs").write_text(
        "public void Load() {}\n", encoding="utf-8"
    )
    values = request.to_dict()
    values["isolated_source_snapshot_sha256"] = source_snapshot_sha256(
        source_snapshot(Path(request.isolated_target_root))
    )
    request = ProductExecutionRequestV1.from_dict(values)
    adapters = _successful_compile_adapters(request, build_exit_codes=[1, 1, 1])
    result = execute_product_execution(
        preflight_product_execution(request, adapters, store), adapters, store
    )
    projection = copy.deepcopy(result.to_dict())
    readback = projection["validation_facts"]["details"][0]["payload"]
    plan = next(
        item
        for item in reversed(readback)
        if item["artifact_type"] == "repair_plan"
    )
    if field == "status":
        plan["status"] = value
    else:
        plan["data"][field] = value

    with pytest.raises(ProductExecutionContractError, match="lifecycle predicate"):
        ProductExecutionResultV1.from_dict(projection)


@pytest.mark.parametrize(
    ("scenario", "replacement_attempt"),
    (
        ("review", 0),
        ("review_max", 1),
        ("runtime_terminal", 1),
        ("runtime_max", 1),
        ("repair", 1),
    ),
)
def test_strict_replay_rejects_terminal_repair_attempt_drift_by_source(
    tmp_path: Path,
    scenario: str,
    replacement_attempt: int,
) -> None:
    result = _execute_store_role_scenario(tmp_path, scenario=scenario)
    projection = copy.deepcopy(result.to_dict())
    terminal_nodes = {"create_repair_plan", "blocked"}
    for collection in (projection["store_attempts"], projection["outputs"]):
        last_plan = max(
            index
            for index, item in enumerate(collection)
            if item["node_name"] == "create_repair_plan"
        )
        collection[last_plan]["repair_attempt"] = replacement_attempt
        if collection[-1]["node_name"] == "blocked":
            collection[-1]["repair_attempt"] = replacement_attempt
    assert projection["store_attempts"][-1]["node_name"] in terminal_nodes

    with pytest.raises(ProductExecutionContractError):
        ProductExecutionResultV1.from_dict(projection)


@pytest.mark.parametrize("mutation", ("missing", "wrong_attempt"))
def test_strict_replay_rejects_missing_or_wrong_attempt_blocked_report(
    tmp_path: Path,
    mutation: str,
) -> None:
    result = _execute_store_role_scenario(tmp_path, scenario="review")
    projection = copy.deepcopy(result.to_dict())
    readback = projection["validation_facts"]["details"][0]["payload"]
    if mutation == "missing":
        projection["store_attempts"].pop()
        projection["outputs"].pop()
        readback.pop()
    else:
        projection["store_attempts"][-1]["repair_attempt"] = 0
        projection["outputs"][-1]["repair_attempt"] = 0

    with pytest.raises(ProductExecutionContractError):
        ProductExecutionResultV1.from_dict(projection)


def test_strict_replay_rejects_unreadable_terminal_repair_without_blocked_report(
    tmp_path: Path,
) -> None:
    result = _execute_store_role_scenario(tmp_path, scenario="review")
    projection = copy.deepcopy(result.to_dict())
    projection["store_attempts"].pop()
    projection["outputs"].pop()
    validation = projection["validation_facts"]
    validation["output_readback_status"] = "failed"
    validation["failure_class"] = "OSError"
    validation["failure_message"] = "injected terminal readback failure"
    validation["details"][0]["payload"] = None
    projection["platform_status"] = "partial"
    projection["execution_disposition"] = "partial"
    projection["failure_stage"] = "post_execution_validation"
    projection["blockers"].append(
        {
            "contract_version": "1",
            "owner": "platform",
            "stage": "post_execution_validation",
            "code": "PRODUCT_OUTPUT_READBACK_FAILED",
            "message": "Committed output readback failed.",
            "source_node": "product_executor",
        }
    )

    with pytest.raises(
        ProductExecutionContractError,
        match="lacks its committed BlockedReport",
    ):
        ProductExecutionResultV1.from_dict(projection)


def test_strict_replay_rejects_store_after_blocked_terminal(tmp_path: Path) -> None:
    result = _execute_store_role_scenario(tmp_path, scenario="review")
    projection = copy.deepcopy(result.to_dict())
    extra_attempt = copy.deepcopy(projection["store_attempts"][-1])
    extra_output = copy.deepcopy(projection["outputs"][-1])
    extra_envelope = copy.deepcopy(
        projection["validation_facts"]["details"][0]["payload"][-1]
    )
    extra_attempt["sequence"] = len(projection["store_attempts"])
    extra_output["sequence"] = len(projection["outputs"])
    projection["store_attempts"].append(extra_attempt)
    projection["outputs"].append(extra_output)
    projection["validation_facts"]["details"][0]["payload"].append(
        extra_envelope
    )

    with pytest.raises(ProductExecutionContractError):
        ProductExecutionResultV1.from_dict(projection)


def test_strict_replay_rejects_higher_attempt_effect_after_blocked_terminal(
    tmp_path: Path,
) -> None:
    result = _execute_store_role_scenario(tmp_path, scenario="review")
    projection = copy.deepcopy(result.to_dict())
    next_sequence = len(projection["effect_events"])
    for offset, status in enumerate(("started", "completed")):
        projection["effect_events"].append(
            {
                "contract_version": "1",
                "sequence": next_sequence + offset,
                "phase": "repair",
                "repair_attempt": 2,
                "effect_role": "build",
                "event_status": status,
                "failure_class": None,
                "failure_message": None,
            }
        )

    with pytest.raises(
        ProductExecutionContractError,
        match="continues after its blocked repair terminal",
    ):
        ProductExecutionResultV1.from_dict(projection)


@pytest.mark.parametrize("outcome", ("blocked_before_commit", "partial"))
def test_repair_plan_store_failure_keeps_c5_truth_before_payload_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    request, store = _request(tmp_path)
    Path(request.isolated_target_root, "Plugin.cs").write_text(
        "public void Load() {}\n", encoding="utf-8"
    )
    values = request.to_dict()
    values["isolated_source_snapshot_sha256"] = source_snapshot_sha256(
        source_snapshot(Path(request.isolated_target_root))
    )
    request = ProductExecutionRequestV1.from_dict(values)
    _install_actual_store_failure(
        monkeypatch,
        store,
        artifact_role="repair_plan",
        outcome=outcome,
        occurrence=3,
    )
    adapters = _successful_compile_adapters(request, build_exit_codes=[1, 1, 1])

    result = execute_product_execution(
        preflight_product_execution(request, adapters, store), adapters, store
    )

    assert result.platform_status == "partial"
    assert result.execution_disposition == "partial"
    assert result.failure_stage == "repair_plan_store"
    assert result.store_attempts[-1].artifact_role == "repair_plan"
    assert result.store_attempts[-1].store_result.outcome == outcome
    assert tuple(item.artifact_role for item in result.outputs) == tuple(
        item.artifact_role for item in result.store_attempts[:-1]
    )
    assert ProductExecutionResultV1.from_dict(result.to_dict()) == result


@pytest.mark.parametrize("outcome", ("blocked_before_commit", "partial"))
def test_blocked_report_store_failure_validates_committed_repair_plan_then_keeps_c5_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    request, store = _request(tmp_path)
    Path(request.isolated_target_root, "Plugin.cs").write_text(
        "public void Load() {}\n", encoding="utf-8"
    )
    values = request.to_dict()
    values["isolated_source_snapshot_sha256"] = source_snapshot_sha256(
        source_snapshot(Path(request.isolated_target_root))
    )
    request = ProductExecutionRequestV1.from_dict(values)
    _install_actual_store_failure(
        monkeypatch,
        store,
        artifact_role="blocked_report",
        outcome=outcome,
    )
    adapters = _successful_compile_adapters(request, build_exit_codes=[1, 1, 1])
    result = execute_product_execution(
        preflight_product_execution(request, adapters, store), adapters, store
    )

    assert result.platform_status == "partial"
    assert result.execution_disposition == "partial"
    assert result.failure_stage == "blocked_report_store"
    assert result.store_attempts[-1].store_result.outcome == outcome
    assert ProductExecutionResultV1.from_dict(result.to_dict()) == result

    projection = copy.deepcopy(result.to_dict())
    readback = projection["validation_facts"]["details"][0]["payload"]
    plan = next(
        item
        for item in reversed(readback)
        if item["artifact_type"] == "repair_plan"
    )
    plan["data"]["retry_exhausted"] = False
    with pytest.raises(ProductExecutionContractError, match="lifecycle predicate"):
        ProductExecutionResultV1.from_dict(projection)


def test_committed_terminal_repair_plan_readback_failure_is_post_validation_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, store = _request(tmp_path)
    Path(request.isolated_target_root, "Plugin.cs").write_text(
        "public void Load() {}\n", encoding="utf-8"
    )
    values = request.to_dict()
    values["isolated_source_snapshot_sha256"] = source_snapshot_sha256(
        source_snapshot(Path(request.isolated_target_root))
    )
    request = ProductExecutionRequestV1.from_dict(values)
    original_read = store.read
    state = {"repair_reads": 0}

    def fail_final_repair_readback(ref):
        if ref.artifact_type == "repair_plan" and any(
            frame.function == "validate_product_execution_outputs"
            for frame in inspect.stack()
        ):
            state["repair_reads"] += 1
            if state["repair_reads"] == 3:
                raise OSError("injected terminal RepairPlan readback failure")
        return original_read(ref)

    monkeypatch.setattr(store, "read", fail_final_repair_readback)
    adapters = _successful_compile_adapters(request, build_exit_codes=[1, 1, 1])

    result = execute_product_execution(
        preflight_product_execution(request, adapters, store), adapters, store
    )

    assert result.platform_status == "partial"
    assert result.execution_disposition == "partial"
    assert result.failure_stage == "post_execution_validation"
    assert result.validation_facts.output_readback_status == "failed"
    assert result.store_attempts[-2].artifact_role == "repair_plan"
    assert result.store_attempts[-1].artifact_role == "blocked_report"
    assert all(
        item.store_result.outcome == "committed" for item in result.store_attempts
    )
    assert ProductExecutionResultV1.from_dict(result.to_dict()) == result


@pytest.mark.parametrize("outcome", ("blocked_before_commit", "partial"))
@pytest.mark.parametrize(
    ("scenario", "artifact_role", "occurrence"),
    (
        ("blocked", "request_planning_report", 1),
        ("blocked", "mod_planning_brief", 1),
        ("blocked", "feature_spec", 1),
        ("blocked", "evidence_pack", 1),
        ("compile", "implementation_plan", 1),
        ("compile", "patch_proposal", 1),
        ("compile", "proposal_review", 1),
        ("compile", "dry_run_result", 1),
        ("compile", "isolated_apply_result", 1),
        ("compile", "build_result", 1),
        ("compile", "workflow_checkpoint", 1),
        ("repair", "repair_plan", 3),
        ("binding", "binding_resolution", 1),
        ("runtime", "runtime_evidence", 1),
        ("runtime", "eval_report", 1),
        ("runtime", "workflow_summary", 1),
        ("repair", "blocked_report", 1),
    ),
)
def test_each_active_public_store_role_preserves_real_c5_failure_and_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    artifact_role: str,
    occurrence: int,
    outcome: str,
) -> None:
    declared_roles = tuple(
        role for _node, role in PRODUCT_EXECUTION_DECLARATION.node_store_roles
    )
    assert artifact_role in declared_roles
    baseline = _execute_store_role_scenario(
        tmp_path / "baseline",
        scenario=scenario,
    )
    matching = [
        index
        for index, item in enumerate(baseline.store_attempts)
        if item.artifact_role == artifact_role
    ]
    assert len(matching) >= occurrence
    stop_index = matching[occurrence - 1]

    result = _execute_store_role_scenario(
        tmp_path / "failure",
        scenario=scenario,
        monkeypatch=monkeypatch,
        failure_role=artifact_role,
        failure_outcome=outcome,
        failure_occurrence=occurrence,
    )

    attempt_signature = lambda item: (
        item.node_name,
        item.artifact_role,
        item.repair_attempt,
    )
    output_signature = lambda item: (
        item.node_name,
        item.artifact_role,
        item.repair_attempt,
    )
    assert tuple(map(attempt_signature, result.store_attempts)) == tuple(
        map(attempt_signature, baseline.store_attempts[: stop_index + 1])
    )
    assert result.store_attempts[-1].artifact_role == artifact_role
    assert result.store_attempts[-1].store_result.outcome == outcome
    assert tuple(map(output_signature, result.outputs)) == tuple(
        map(attempt_signature, baseline.store_attempts[:stop_index])
    )
    assert tuple(item.to_dict() for item in result.effect_events) == tuple(
        item.to_dict()
        for item in baseline.effect_events[: len(result.effect_events)]
    )
    assert result.failure_stage == f"{artifact_role}_store"
    expected_partial = bool(result.outputs) or any(
        item.event_status == "started" for item in result.effect_events
    ) or outcome == "partial"
    assert result.platform_status == ("partial" if expected_partial else "blocked")
    assert result.execution_disposition == (
        "partial" if expected_partial else "platform_blocked"
    )
    assert ProductExecutionResultV1.from_dict(result.to_dict()) == result


def test_product_store_role_matrix_excludes_only_unreachable_optional_critic() -> None:
    assert ("review_proposal", "critic_assessment") in (
        PRODUCT_EXECUTION_DECLARATION.node_store_roles
    )
    assert "proposal_critic" not in ProductExecutionAdaptersV1.__dataclass_fields__


def test_exact_diff_rejection_is_domain_terminal_without_apply_effect(
    tmp_path: Path,
) -> None:
    request, store = _request(tmp_path)
    source = Path(request.isolated_target_root, "Plugin.cs")
    before = source.read_bytes()
    base = _successful_compile_adapters(request)

    def reject_exact_diff(*_args):
        raise ExactDiffApprovalRejectedError("operator rejected exact diff")

    adapters = replace(base, isolated_apply_factory=reject_exact_diff)
    result = execute_product_execution(
        preflight_product_execution(request, adapters, store), adapters, store
    )

    assert result.platform_status == "completed"
    assert result.execution_disposition == "domain_blocked"
    assert source.read_bytes() == before
    assert tuple(item.artifact_role for item in result.store_attempts[-2:]) == (
        "isolated_apply_result",
        "blocked_report",
    )
    assert all(
        item.store_result.outcome == "committed"
        for item in result.store_attempts[-2:]
    )
    assert all(
        item.effect_role not in {"isolated_apply", "build"}
        for item in result.effect_events
    )


def test_strict_result_replay_rejects_store_order_drift(tmp_path: Path) -> None:
    request, store = _request(tmp_path)
    result = execute_product_execution(
        preflight_product_execution(request, _blocked_evidence_adapters(), store),
        _blocked_evidence_adapters(),
        store,
    )
    projection = result.to_dict()
    projection["store_attempts"][0], projection["store_attempts"][1] = (
        projection["store_attempts"][1],
        projection["store_attempts"][0],
    )

    with pytest.raises(ProductExecutionContractError):
        ProductExecutionResultV1.from_dict(projection)


def test_strict_result_replay_rejects_terminal_stage_drift(tmp_path: Path) -> None:
    request, store = _request(tmp_path)
    adapters = _blocked_evidence_adapters()
    result = execute_product_execution(
        preflight_product_execution(request, adapters, store), adapters, store
    )
    projection = result.to_dict()
    projection["terminal_node"] = "build"

    with pytest.raises(ProductExecutionContractError):
        ProductExecutionResultV1.from_dict(projection)


def test_strict_result_replay_rejects_undeclared_failure_stage(
    tmp_path: Path,
) -> None:
    request, store = _request(tmp_path)
    adapters = _blocked_evidence_adapters()
    result = execute_product_execution(
        preflight_product_execution(request, adapters, store), adapters, store
    )
    projection = result.to_dict()
    projection["failure_stage"] = "caller_selected_failure"

    with pytest.raises(ProductExecutionContractError):
        ProductExecutionResultV1.from_dict(projection)
