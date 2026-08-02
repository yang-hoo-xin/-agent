from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore, ArtifactStoreError
from src.mod_agent.build import (
    BuildAdapter,
    BuildCommandResult,
    BuildProfile,
    BuildResult,
    build_fake_build_result,
)
from src.mod_agent.workflow import (
    ResumePayload,
    VerificationOnlyContinuationInput,
    WorkflowCheckpointStore,
    build_graph,
    create_initial_state,
    preflight_verification_only_continuation,
    resumed_state_from_decision,
)
from src.mod_agent.workflow.verification_only import (
    verification_only_lineage_payload,
)
from src.mod_agent.runtime import (
    RuntimeEvidenceItem,
    build_real_runtime_evidence_payload,
    build_supplied_runtime_evidence_payload,
)
from src.mod_agent.workflow.graph import _run_workflow_summary


FEATURE_ID = "feature_verification_only_001"
USER_REQUEST = "Verify the existing implementation without changing source."
TARGET_MOD = "BetterHitFeedback"
HANDOFF_CODE = "VERIFICATION_ONLY_FRESH_LINEAGE_HANDOFF_UNSUPPORTED"


def test_preflight_is_deterministic_and_performs_no_write(tmp_path: Path) -> None:
    store, continuation = _verification_inputs(tmp_path)
    before = _store_snapshot(store.root)

    first = _preflight(store, continuation)
    second = _preflight(store, continuation)

    assert first == second
    assert first["status"] == "ready_for_build_authorization"
    assert first["source_lineage"]["all_files_verified"] is True
    assert first["writes_performed"] is False
    assert first["artifact_writes_performed"] is False
    assert first["build_invoked"] is False
    assert _store_snapshot(store.root) == before


def test_preflight_blocks_stale_feature_lineage(tmp_path: Path) -> None:
    store, continuation = _verification_inputs(tmp_path)
    prior = store.read(continuation.feature_spec_ref)
    newer_payload = copy.deepcopy(prior["data"])
    newer_payload["message"] = "A newer FeatureSpec revision."
    store.write(
        feature_id=FEATURE_ID,
        artifact_type="feature_spec",
        payload=newer_payload,
        status="success",
    )

    report = _preflight(store, continuation)

    assert report["status"] == "blocked"
    assert {item["code"] for item in report["blockers"]} >= {
        "VERIFICATION_ARTIFACT_INVALID",
        "VERIFICATION_INPUT_NOT_LATEST",
    }


def test_preflight_blocks_changed_source_bytes(tmp_path: Path) -> None:
    store, continuation = _verification_inputs(tmp_path)
    feature = store.read(continuation.feature_spec_ref)["data"]
    source_root = Path(feature["source_lineage"]["root"])
    (source_root / "Plugin.cs").write_text("changed", encoding="utf-8")

    report = _preflight(store, continuation)

    assert report["status"] == "blocked"
    assert "VERIFICATION_SOURCE_HASH_MISMATCH" in {
        item["code"] for item in report["blockers"]
    }


def test_preflight_blocks_non_latest_evidence_pack(tmp_path: Path) -> None:
    store, continuation = _verification_inputs(tmp_path)
    envelope = store.read(continuation.evidence_pack_ref)
    payload = copy.deepcopy(envelope["data"])
    payload["message"] = "Newer reviewed verification evidence."
    store.write(
        feature_id=FEATURE_ID,
        artifact_type="evidence_pack",
        payload=payload,
        status="blocked",
        blockers=list(payload["blockers"]),
        trace_refs=list(payload["trace_refs"]),
        upstream_refs=[continuation.feature_spec_ref],
    )

    report = _preflight(store, continuation)

    assert report["status"] == "blocked"
    assert "VERIFICATION_INPUT_NOT_LATEST" in {
        item["code"] for item in report["blockers"]
    }


def test_preflight_blocks_unreviewed_evidence_disposition(tmp_path: Path) -> None:
    store, continuation = _verification_inputs(tmp_path)
    envelope = store.read(continuation.evidence_pack_ref)
    payload = copy.deepcopy(envelope["data"])
    payload["blockers"] = [
        {"code": "UNRELATED_BLOCKER", "message": "Different reason."}
    ]
    replacement = store.write(
        feature_id=FEATURE_ID,
        artifact_type="evidence_pack",
        payload=payload,
        status="blocked",
        blockers=list(payload["blockers"]),
        trace_refs=list(payload["trace_refs"]),
        upstream_refs=[continuation.feature_spec_ref],
    )

    report = _preflight(
        store,
        VerificationOnlyContinuationInput(
            feature_spec_ref=continuation.feature_spec_ref,
            evidence_pack_ref=replacement,
        ),
    )

    assert report["status"] == "blocked"
    assert "VERIFICATION_HANDOFF_DISPOSITION_INVALID" in {
        item["code"] for item in report["blockers"]
    }


def test_build_contract_requires_complete_verification_upstreams(tmp_path: Path) -> None:
    store, continuation = _verification_inputs(tmp_path)
    payload = build_fake_build_result(
        feature_id=FEATURE_ID,
        input_execution_mode="verification_only",
    ).to_artifact_payload()

    with pytest.raises(
        ArtifactStoreError,
        match="requires only one exact FeatureSpec and one exact EvidencePack",
    ):
        store.write(
            feature_id=FEATURE_ID,
            artifact_type="build_result",
            payload=payload,
            status="success",
            upstream_refs=[continuation.feature_spec_ref],
        )


def test_build_contract_rejects_mixed_lineage_in_both_directions(
    tmp_path: Path,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    fake_dry_run = ArtifactRef(
        feature_id=FEATURE_ID,
        artifact_type="dry_run_result",
        path=str(tmp_path / "not-read.json"),
        artifact_hash="0" * 64,
    )
    before = len(store.list_feature_artifact_revisions(FEATURE_ID, "build_result"))
    verification_payload = build_fake_build_result(
        feature_id=FEATURE_ID,
        input_execution_mode="verification_only",
    ).to_artifact_payload()
    verification_payload["verification_only_lineage"] = (
        verification_only_lineage_payload(_preflight(store, continuation))
    )

    with pytest.raises(ArtifactStoreError, match="requires only one exact"):
        store.write(
            feature_id=FEATURE_ID,
            artifact_type="build_result",
            payload=verification_payload,
            status="success",
            upstream_refs=[
                continuation.feature_spec_ref,
                continuation.evidence_pack_ref,
                fake_dry_run,
            ],
        )

    mutation_payload = build_fake_build_result(
        feature_id=FEATURE_ID,
        input_execution_mode="fake",
    ).to_artifact_payload()
    with pytest.raises(ArtifactStoreError, match="requires dry_run_result"):
        store.write(
            feature_id=FEATURE_ID,
            artifact_type="build_result",
            payload=mutation_payload,
            status="success",
            upstream_refs=[
                continuation.feature_spec_ref,
                continuation.evidence_pack_ref,
            ],
        )

    assert len(store.list_feature_artifact_revisions(FEATURE_ID, "build_result")) == before


def test_graph_builds_from_exact_verification_lineage_and_stops(tmp_path: Path) -> None:
    store, continuation = _verification_inputs(tmp_path)
    graph = build_graph(
        store,
        build_result_factory=_real_build_factory(tmp_path),
        stop_after_build=True,
        persist_build_runtime_handoff=True,
        verification_only_continuation=continuation,
    )

    result = graph.invoke(_initial_state())

    assert result["current_stage"] == "build"
    assert result["build_summary"]["input_execution_mode"] == "verification_only"
    assert "implementation_plan" not in result["artifacts"]
    assert "patch_proposal" not in result["artifacts"]
    assert "proposal_review" not in result["artifacts"]
    assert "dry_run_result" not in result["artifacts"]
    build_ref = _state_ref(result, "build_result")
    build_envelope = store.read(build_ref)
    assert {
        item["artifact_type"]
        for item in build_envelope["inputs"]["upstream_artifacts"]
    } == {"feature_spec", "evidence_pack"}
    assert build_envelope["data"]["input_execution_mode"] == "verification_only"
    checkpoint_ref = _state_ref(result, "workflow_checkpoint")
    decision = WorkflowCheckpointStore(store).preflight_resume(checkpoint_ref)
    assert decision.allowed is True


def test_graph_blocks_build_result_identity_drift_without_artifact_write(
    tmp_path: Path,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    calls = {"count": 0}

    def wrong_factory(feature_id: str, input_execution_mode: str | None) -> BuildResult:
        calls["count"] += 1
        valid = _real_build_factory(tmp_path)(feature_id, input_execution_mode)
        return BuildResult(
            **{
                **valid.__dict__,
                "input_execution_mode": "mutation",
            }
        )

    graph = build_graph(
        store,
        build_result_factory=wrong_factory,
        stop_after_build=True,
        persist_build_runtime_handoff=True,
        verification_only_continuation=continuation,
    )

    result = graph.invoke(_initial_state())

    assert calls["count"] == 1
    assert result["build_summary"]["status"] == "blocked"
    assert "build_result" not in result["artifacts"]
    assert "workflow_checkpoint" not in result["artifacts"]
    assert store.list_feature_artifact_revisions(FEATURE_ID, "build_result") == []


def test_graph_blocks_source_drift_during_build_before_artifact_write(
    tmp_path: Path,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    source_root = Path(
        store.read(continuation.feature_spec_ref)["data"]["source_lineage"]["root"]
    )
    valid_factory = _real_build_factory(tmp_path)

    def drifting_factory(
        feature_id: str,
        input_execution_mode: str | None,
    ) -> BuildResult:
        result = valid_factory(feature_id, input_execution_mode)
        (source_root / "Plugin.cs").write_text("drifted", encoding="utf-8")
        return result

    result = build_graph(
        store,
        build_result_factory=drifting_factory,
        stop_after_build=True,
        persist_build_runtime_handoff=True,
        verification_only_continuation=continuation,
    ).invoke(_initial_state())

    assert result["build_summary"]["status"] == "blocked"
    assert {item["code"] for item in result["blockers"]} >= {
        "VERIFICATION_BUILD_INPUT_DRIFT"
    }
    assert "build_result" not in result["artifacts"]
    assert "workflow_checkpoint" not in result["artifacts"]
    assert store.list_feature_artifact_revisions(FEATURE_ID, "build_result") == []


def test_graph_blocks_build_that_did_not_consume_admitted_source(
    tmp_path: Path,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    unrelated_root = tmp_path / "unrelated_build"
    output = unrelated_root / "bin" / "BetterHitFeedback.dll"

    def unbound_factory(
        feature_id: str,
        input_execution_mode: str | None,
    ) -> BuildResult:
        def runner(_: BuildProfile) -> BuildCommandResult:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"unbound build")
            return BuildCommandResult(exit_code=0, stdout="Build succeeded")

        return BuildAdapter().run_local(
            feature_id=feature_id,
            profile=BuildProfile(
                profile_id="unbound_verification_test",
                build_system="dotnet",
                working_directory=str(unrelated_root),
                command=("dotnet", "build"),
                timeout_seconds=120,
                expected_artifacts=("bin/BetterHitFeedback.dll",),
            ),
            command_runner=runner,
            allow_execution=True,
            input_execution_mode=input_execution_mode,
        )

    result = build_graph(
        store,
        build_result_factory=unbound_factory,
        stop_after_build=True,
        persist_build_runtime_handoff=True,
        verification_only_continuation=continuation,
    ).invoke(_initial_state())

    assert result["build_summary"]["status"] == "blocked"
    assert "VERIFICATION_BUILD_SOURCE_FILE_MISSING" in {
        item["code"] for item in result["blockers"]
    }
    assert "build_result" not in result["artifacts"]
    assert store.list_feature_artifact_revisions(FEATURE_ID, "build_result") == []


def test_fresh_process_runtime_reuses_verification_build_without_mutation_chain(
    tmp_path: Path,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    build_graph_instance = build_graph(
        store,
        build_result_factory=_real_build_factory(tmp_path),
        stop_after_build=True,
        persist_build_runtime_handoff=True,
        verification_only_continuation=continuation,
    )
    build_state = build_graph_instance.invoke(_initial_state())
    checkpoint_ref = _state_ref(build_state, "workflow_checkpoint")
    checkpoint = store.read(checkpoint_ref)["data"]
    checkpoint_store = WorkflowCheckpointStore(store)
    decision, resume_ref = checkpoint_store.resume(
        checkpoint_ref,
        _resume_payload(checkpoint),
    )
    resumed_state = resumed_state_from_decision(
        decision,
        checkpoint_ref=checkpoint_ref,
        resume_report_ref=resume_ref,
    )

    def forbidden_build(_: str, __: str | None) -> BuildResult:
        raise AssertionError("Build must not repeat during Runtime continuation.")

    runtime_graph = build_graph(
        store,
        build_result_factory=forbidden_build,
        runtime_continuation_checkpoint_id=checkpoint["checkpoint_id"],
    )
    result = runtime_graph.invoke(resumed_state)

    assert result["current_stage"] == "done"
    assert "repair_plan" not in result["artifacts"]
    assert "implementation_plan" not in result["artifacts"]
    evaluation = store.read(_state_ref(result, "eval_report"))["data"]
    assert evaluation["evaluation_gate"]["continuation_mode"] == "verification_only"
    assert {
        item["case_id"] for item in evaluation["evaluation_gate"]["cases"]
    } >= {"verification_only_continuation"}
    assert {
        item["case_id"] for item in evaluation["evaluation_gate"]["cases"]
    }.isdisjoint({"review_correctness", "dry_run_safety"})


def test_inconclusive_verification_runtime_stops_without_repair_planner(
    tmp_path: Path,
) -> None:
    store, continuation = _verification_inputs(tmp_path)
    build_state = build_graph(
        store,
        build_result_factory=_real_build_factory(tmp_path),
        stop_after_build=True,
        persist_build_runtime_handoff=True,
        verification_only_continuation=continuation,
    ).invoke(_initial_state())
    checkpoint_ref = _state_ref(build_state, "workflow_checkpoint")
    checkpoint = store.read(checkpoint_ref)["data"]
    decision, resume_ref = WorkflowCheckpointStore(store).resume(
        checkpoint_ref,
        _resume_payload(checkpoint),
    )
    resumed_state = resumed_state_from_decision(
        decision,
        checkpoint_ref=checkpoint_ref,
        resume_report_ref=resume_ref,
    )

    def runtime_factory(
        feature_id: str,
        _build: dict[str, object],
        feature_spec: dict[str, object],
    ) -> dict[str, object]:
        return build_supplied_runtime_evidence_payload(
            feature_id=feature_id,
            raw_supplied_output="Observation did not close acceptance.",
            verification_status="inconclusive",
            acceptance_criteria=tuple(feature_spec["acceptance_criteria"]),
            runtime_verification_plan=tuple(
                feature_spec["runtime_verification_plan"]
            ),
        )

    result = build_graph(
        store,
        runtime_evidence_factory=runtime_factory,
        runtime_continuation_checkpoint_id=checkpoint["checkpoint_id"],
    ).invoke(resumed_state)

    assert result["current_stage"] == "blocked"
    assert "runtime_evidence" in result["artifacts"]
    assert "repair_plan" not in result["artifacts"]
    assert "eval_report" not in result["artifacts"]
    assert "blocked_report" in result["artifacts"]


def test_eval_lineage_failure_never_claims_real_success(tmp_path: Path) -> None:
    store, continuation = _verification_inputs(tmp_path)
    build_state = build_graph(
        store,
        build_result_factory=_real_build_factory(tmp_path),
        stop_after_build=True,
        persist_build_runtime_handoff=True,
        verification_only_continuation=continuation,
    ).invoke(_initial_state())
    checkpoint_ref = _state_ref(build_state, "workflow_checkpoint")
    checkpoint = store.read(checkpoint_ref)["data"]
    decision, resume_ref = WorkflowCheckpointStore(store).resume(
        checkpoint_ref,
        _resume_payload(checkpoint),
    )
    resumed_state = resumed_state_from_decision(
        decision,
        checkpoint_ref=checkpoint_ref,
        resume_report_ref=resume_ref,
    )
    resumed_state["artifacts"]["dry_run_result"] = "not-used.json"
    resumed_state["artifact_hashes"]["dry_run_result"] = "0" * 64

    def accepted_runtime_factory(
        feature_id: str,
        build: dict[str, object],
        feature_spec: dict[str, object],
    ) -> dict[str, object]:
        criteria = tuple(str(item) for item in feature_spec["acceptance_criteria"])
        return build_real_runtime_evidence_payload(
            feature_id=feature_id,
            input_execution_mode=str(build["input_execution_mode"]),
            evidence_items=(
                RuntimeEvidenceItem(
                    item_type="runtime_log",
                    source="runtime_probe",
                    locator="runtime://verification-only-lineage-negative",
                    supports_acceptance=criteria,
                    confidence=1.0,
                    raw_excerpt="Runtime behavior was observed.",
                ),
            ),
            startup_loaded=True,
            gameplay_behavior_verified=True,
            verification_status="verified",
            acceptance_criteria=criteria,
            runtime_verification_plan=tuple(
                str(item) for item in feature_spec["runtime_verification_plan"]
            ),
            plugin_marker_binding={
                "marker_source": "runtime_probe",
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

    result = build_graph(
        store,
        runtime_evidence_factory=accepted_runtime_factory,
        runtime_continuation_checkpoint_id=checkpoint["checkpoint_id"],
    ).invoke(resumed_state)

    evaluation = store.read(_state_ref(result, "eval_report"))["data"]
    assert result["current_stage"] == "blocked"
    assert evaluation["evaluation_gate"]["status"] == "failed"
    assert evaluation["verdict"] == "blocked"
    assert evaluation["claims_real_success"] is False
    assert evaluation["workflow_completion_status"] == "evaluation_blocked"
    assert evaluation["requested_behavior_status"] == "not_verified"
    assert evaluation["v1_acceptance_status"] == "accepted"

    summary_state = _run_workflow_summary(result, store)
    summary = store.read(_state_ref(summary_state, "workflow_summary"))["data"]
    assert summary["final_status"] == "blocked"
    assert summary["claims_real_mod_success"] is False
    assert summary["next_required_evidence"]


def test_verification_only_configuration_keeps_build_runtime_authority_separate(
    tmp_path: Path,
) -> None:
    store, continuation = _verification_inputs(tmp_path)

    with pytest.raises(ValueError, match="must stop after Build"):
        build_graph(
            store,
            build_result_factory=_real_build_factory(tmp_path),
            verification_only_continuation=continuation,
        )


def _verification_inputs(
    tmp_path: Path,
) -> tuple[ArtifactStore, VerificationOnlyContinuationInput]:
    store = ArtifactStore(tmp_path / "artifacts")
    source_root = tmp_path / "source"
    source_root.mkdir()
    files = {
        "Plugin.cs": "plugin source",
        "Patches/HitFeedbackBehaviorPatch.cs": "patch source",
    }
    for relative_path, content in files.items():
        path = source_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    source_hashes = {
        relative_path: _sha256(source_root / relative_path)
        for relative_path in files
    }
    feature_payload = {
        "node_name": "draft_feature_spec",
        "stage": "feature_spec",
        "message": "Fresh verification FeatureSpec.",
        "feature_id": FEATURE_ID,
        "user_request": USER_REQUEST,
        "target_behavior": "Verify existing behavior.",
        "non_goals": ["No source change."],
        "target_mod": TARGET_MOD,
        "risk_level": "high",
        "acceptance_criteria": ["Existing behavior remains correct."],
        "evidence_requirements": ["Current source identity."],
        "runtime_verification_plan": ["Run after a fresh Build."],
        "blocked": False,
        "blockers": [],
        "source_lineage": {
            "root": str(source_root.resolve()),
            "read_only": True,
            "files": source_hashes,
        },
    }
    feature_ref = store.write(
        feature_id=FEATURE_ID,
        artifact_type="feature_spec",
        payload=feature_payload,
        status="success",
    )
    evidence_blockers = [
        {
            "code": HANDOFF_CODE,
            "message": "Existing source requires fresh Build verification, not a patch.",
        }
    ]
    trace_refs = [
        f"feature_spec:{feature_ref.artifact_hash}",
        f"source:sha256:{source_hashes['Plugin.cs'].lower()}",
    ]
    evidence_payload = {
        "node_name": "retrieve_evidence",
        "stage": "evidence_retrieval",
        "message": "Fresh source evidence is ready for verification only.",
        "query": USER_REQUEST,
        "readiness": "partial",
        "can_generate_patch": False,
        "authority": "mod_agent_deterministic_evidence",
        "authoritative_for_patch": False,
        "identity_schema_version": "1.0",
        "identity_field_mapping": {},
        "items": [],
        "gaps": ["Fresh Build is missing."],
        "excluded": [],
        "blockers": evidence_blockers,
        "retrieval_methods_used": ["source_inspection"],
        "missing_evidence": ["Fresh BuildResult"],
        "disabled_modes": {},
        "timing": {},
        "trace_refs": trace_refs,
    }
    evidence_ref = store.write(
        feature_id=FEATURE_ID,
        artifact_type="evidence_pack",
        payload=evidence_payload,
        status="blocked",
        blockers=evidence_blockers,
        trace_refs=trace_refs,
        upstream_refs=[feature_ref],
    )
    return store, VerificationOnlyContinuationInput(
        feature_spec_ref=feature_ref,
        evidence_pack_ref=evidence_ref,
    )


def _real_build_factory(tmp_path: Path):
    build_root = tmp_path / "build"
    source_root = tmp_path / "source"
    output = build_root / "bin" / "BetterHitFeedback.dll"

    def factory(feature_id: str, input_execution_mode: str | None) -> BuildResult:
        def runner(_: BuildProfile) -> BuildCommandResult:
            shutil.copytree(source_root, build_root, dirs_exist_ok=True)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"verification-only build")
            return BuildCommandResult(exit_code=0, stdout="Build succeeded")

        return BuildAdapter().run_local(
            feature_id=feature_id,
            profile=BuildProfile(
                profile_id="verification_only_test",
                build_system="dotnet",
                working_directory=str(build_root),
                command=("dotnet", "build"),
                timeout_seconds=120,
                expected_artifacts=("bin/BetterHitFeedback.dll",),
            ),
            command_runner=runner,
            allow_execution=True,
            input_execution_mode=input_execution_mode,
        )

    return factory


def _initial_state():
    return create_initial_state(
        run_id="verification_only_run_001",
        request_id="verification_only_request_001",
        user_request=USER_REQUEST,
        target_mod=TARGET_MOD,
    )


def _preflight(
    store: ArtifactStore,
    continuation: VerificationOnlyContinuationInput,
) -> dict[str, object]:
    return preflight_verification_only_continuation(
        store,
        continuation,
        run_id="verification_only_run_001",
        request_id="verification_only_request_001",
        user_request=USER_REQUEST,
        target_mod=TARGET_MOD,
    )


def _state_ref(state: dict[str, object], artifact_type: str) -> ArtifactRef:
    return ArtifactRef(
        feature_id=str(state["feature_id"]),
        artifact_type=artifact_type,
        path=str(state["artifacts"][artifact_type]),  # type: ignore[index]
        artifact_hash=str(state["artifact_hashes"][artifact_type]),  # type: ignore[index]
    )


def _resume_payload(checkpoint: dict[str, object]) -> ResumePayload:
    return ResumePayload(
        resume_id="verification_only_resume_001",
        run_id=str(checkpoint["run_id"]),
        request_id=str(checkpoint["request_id"]),
        feature_id=str(checkpoint["feature_id"]),
        stage="build",
        decision="approve",
        approved_by="human",
        approved_at="2026-08-02T00:00:00Z",
        artifact_refs=tuple(checkpoint["artifact_refs"]),  # type: ignore[arg-type]
        runtime_admission={
            "status": "admitted",
            "authorization_scope": "this_resume_only",
            "requested_side_effects": ["runtime_execution"],
            "authorized_side_effects": ["runtime_execution"],
            "provider": "injected_test",
        },
    )


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _store_snapshot(root: Path) -> tuple[int, int]:
    files = [path for path in root.rglob("*") if path.is_file()]
    return len(files), sum(path.stat().st_size for path in files)
