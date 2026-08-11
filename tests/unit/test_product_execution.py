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
