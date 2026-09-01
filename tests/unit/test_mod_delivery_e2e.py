"""E2E-001 tests for the minimal mod delivery chain."""

from __future__ import annotations

import sys
from pathlib import Path

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.build import BuildAdapter, BuildCommandResult, BuildProfile
from src.mod_agent.knowledge import (
    IncrementalIndexer,
    KnowledgeDatabase,
    SourceDefinition,
    SourceRegistry,
)
from src.mod_agent.runtime import RuntimeProbeProfile, make_runtime_probe_evidence_factory
from src.mod_agent.workflow import build_graph, create_initial_state


REQUESTED_BEHAVIOR = "make Load enable diagnostics"
TARGET_MOD = "BetterHitFeedback"
EXPECTED_ACCEPTANCE_CRITERIA = (
    f"Requested behavior is implemented: {REQUESTED_BEHAVIOR}",
    "Every proposed change is bound to evidence.",
    "Validation output is reported with real command or artifact evidence.",
)
EXPECTED_RUNTIME_PLAN_WITH_BRIEF = (
    "compile or static validation",
    "startup_loaded",
    "target_path_executed",
    "acceptance_evidence_observed",
    "non_goals_preserved",
    "diagnostic marker observed",
)


def test_e2e_001_minimal_mod_delivery_chain_reaches_handoff_with_current_evidence(
    tmp_path: Path,
) -> None:
    source_file = _write_minimal_target_source(tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_for_source(tmp_path),
        build_result_factory=_local_build_result_factory(tmp_path),
        runtime_evidence_factory=make_runtime_probe_evidence_factory(
            profile=_runtime_probe_profile(tmp_path),
            allow_execution=True,
        ),
    )
    state = create_initial_state(
        run_id="run_e2e_001",
        request_id="req_e2e_001",
        user_request=REQUESTED_BEHAVIOR,
        target_mod=TARGET_MOD,
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "done"
    assert result["blockers"] == []
    assert "repair_plan" not in result["artifacts"]
    assert "blocked_report" not in result["artifacts"]
    assert tuple(result["artifacts"]) == (
        "request_planning_report",
        "mod_planning_brief",
        "feature_spec",
        "evidence_pack",
        "implementation_plan",
        "patch_proposal",
        "proposal_review",
        "dry_run_result",
        "build_result",
        "runtime_evidence",
        "eval_report",
        "workflow_summary",
    )

    planning_brief = _artifact_data(store, result, "mod_planning_brief")
    feature_spec = _artifact_data(store, result, "feature_spec")
    feature_spec_envelope = _artifact_envelope(store, result, "feature_spec")
    evidence_pack = _artifact_data(store, result, "evidence_pack")
    implementation_plan = _artifact_data(store, result, "implementation_plan")
    patch_proposal = _artifact_data(store, result, "patch_proposal")
    proposal_review = _artifact_data(store, result, "proposal_review")
    dry_run = _artifact_data(store, result, "dry_run_result")
    build_result = _artifact_data(store, result, "build_result")
    runtime_evidence = _artifact_data(store, result, "runtime_evidence")
    eval_report = _artifact_data(store, result, "eval_report")
    workflow_summary = _artifact_data(store, result, "workflow_summary")

    assert planning_brief["decision"] == "ready_for_feature_spec"
    assert planning_brief["request_type"]["value"] == "runtime diagnostics"
    assert planning_brief["next_action"] == "feature_spec"
    assert planning_brief["blocked"] is False

    feature_spec_upstreams = {
        upstream["artifact_type"]
        for upstream in feature_spec_envelope["inputs"]["upstream_artifacts"]
    }
    assert feature_spec_upstreams == {
        "request_planning_report",
        "mod_planning_brief",
    }
    assert feature_spec["target_behavior"] == REQUESTED_BEHAVIOR
    assert feature_spec["target_mod"] == TARGET_MOD
    assert tuple(feature_spec["acceptance_criteria"]) == EXPECTED_ACCEPTANCE_CRITERIA
    assert tuple(feature_spec["runtime_verification_plan"]) == EXPECTED_RUNTIME_PLAN_WITH_BRIEF

    assert evidence_pack["readiness"] == "sufficient"
    assert evidence_pack["can_generate_patch"] is True
    assert evidence_pack["authoritative_for_patch"] is True
    assert evidence_pack["retrieval_methods_used"] == [
        "symbol_exact",
        "text_match",
    ]
    assert evidence_pack["missing_evidence"] == []
    symbol_evidence, text_evidence = evidence_pack["items"]
    assert symbol_evidence["retrieval_method"] == "symbol_exact"
    assert symbol_evidence["source_path"] == source_file.name
    assert symbol_evidence["symbol"] == "Load"
    assert symbol_evidence["authority"] == "mod_agent_deterministic"
    assert text_evidence["retrieval_method"] == "text_match"
    assert text_evidence["source_path"] == symbol_evidence["source_path"]
    assert text_evidence["source_type"] == symbol_evidence["source_type"]
    assert text_evidence["source_hash"] == symbol_evidence["source_hash"]

    assert implementation_plan["blocking"] is False
    assert implementation_plan["evidence_source_paths"] == [source_file.name]
    assert implementation_plan["target_files"] == [source_file.name]
    assert implementation_plan["target_symbols"] == ["Load"]
    assert implementation_plan["evidence_refs"] == [
        symbol_evidence["evidence_id"],
        text_evidence["evidence_id"],
    ]
    binding_registry = implementation_plan["binding_registry"]
    assert len(binding_registry["edit_bindings"]) == 1
    edit_binding = binding_registry["edit_bindings"][0]
    assert edit_binding["evidence_id"] == symbol_evidence["evidence_id"]
    assert edit_binding["retrieval_method"] == "symbol_exact"
    assert edit_binding["target_symbol"] == "Load"
    assert edit_binding["usage"] == "edit_target_scope"
    assert len(binding_registry["supporting_bindings"]) == 1
    supporting_binding = binding_registry["supporting_bindings"][0]
    assert supporting_binding["evidence_id"] == text_evidence["evidence_id"]
    assert supporting_binding["retrieval_method"] == "text_match"
    assert supporting_binding["usage"] == "edit_source_evidence"
    assert supporting_binding["binding_id"] not in {
        binding["binding_id"] for binding in binding_registry["edit_bindings"]
    }
    assert implementation_plan["proposed_changes"][0]["edit_binding_id"] == (
        edit_binding["binding_id"]
    )

    assert patch_proposal["blocked"] is False
    assert patch_proposal["files"] == [source_file.name]
    assert patch_proposal["evidence_refs"] == implementation_plan["evidence_refs"]
    assert proposal_review["decision"] == "approve_dry_run"
    assert proposal_review["allowed_next_stage"] == "dry_run_apply"
    assert proposal_review["required_changes"] == []

    assert dry_run["execution_mode"] == "fake"
    assert dry_run["actual_write_performed"] is False
    assert dry_run["real_patch_applied"] is False
    assert dry_run["approved_by_review"] is True

    assert build_result["execution_mode"] == "local"
    assert build_result["real_build_performed"] is True
    assert build_result["claims_real_build_success"] is True
    assert build_result["artifact_verification"]["status"] == "verified"
    assert build_result["verified_artifacts"][0]["path"] == (
        "bin/Debug/BetterHitFeedback.dll"
    )

    assert runtime_evidence["execution_mode"] == "real"
    assert runtime_evidence["evidence_source"] == "real_runtime_probe"
    assert runtime_evidence["real_runtime_performed"] is True
    assert runtime_evidence["acceptance_verified"] is True
    assert runtime_evidence["claims_real_runtime_success"] is True
    assert runtime_evidence["acceptance_contract"] == {
        "acceptance_criteria": list(EXPECTED_ACCEPTANCE_CRITERIA),
        "runtime_verification_plan": list(EXPECTED_RUNTIME_PLAN_WITH_BRIEF),
    }

    assert eval_report["v1_acceptance_status"] == "accepted"
    assert eval_report["claims_real_success"] is True
    assert workflow_summary["final_status"] == "accepted"
    assert workflow_summary["claims_real_mod_success"] is True
    assert workflow_summary["claims_real_build_success"] is True
    assert workflow_summary["claims_real_runtime_success"] is True


def _write_minimal_target_source(tmp_path: Path) -> Path:
    root = tmp_path / "target_source"
    root.mkdir()
    source_file = root / "Plugin.cs"
    source_file.write_text(
        """
public class Plugin
{
    public void Load()
    {
    }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return source_file


def _knowledge_for_source(tmp_path: Path) -> KnowledgeDatabase:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    registry = SourceRegistry(db)
    registry.register(
        SourceDefinition(
            source_id="target_mod",
            source_type="target_source",
            root_path=tmp_path / "target_source",
            allowed_extensions=frozenset({".cs"}),
        )
    )
    IncrementalIndexer(database=db, source_registry=registry).index_source("target_mod")
    return db


def _local_build_result_factory(tmp_path: Path):
    build_root = tmp_path / "build"
    expected_artifact = build_root / "bin" / "Debug" / "BetterHitFeedback.dll"

    def build_result_factory(feature_id: str, input_execution_mode: str | None):
        def runner(_: BuildProfile) -> BuildCommandResult:
            expected_artifact.parent.mkdir(parents=True)
            expected_artifact.write_bytes(b"e2e-001 verified build artifact")
            return BuildCommandResult(
                exit_code=0,
                stdout="Build succeeded",
                duration_ms=8,
            )

        return BuildAdapter().run_local(
            feature_id=feature_id,
            profile=BuildProfile(
                profile_id="e2e_001_local_build",
                build_system="dotnet",
                working_directory=str(build_root),
                command=("dotnet", "build"),
                timeout_seconds=120,
                expected_artifacts=("bin/Debug/BetterHitFeedback.dll",),
            ),
            command_runner=runner,
            allow_execution=True,
            input_execution_mode=input_execution_mode,
        )

    return build_result_factory


def _runtime_probe_profile(tmp_path: Path) -> RuntimeProbeProfile:
    return RuntimeProbeProfile(
        profile_id="e2e_001_runtime_probe",
        working_directory=str(tmp_path),
        command=(
            sys.executable,
            "-c",
            (
                "print('MOD_AGENT_STARTUP_OK'); "
                "print('MOD_AGENT_ACCEPTANCE_BEHAVIOR'); "
                "print('MOD_AGENT_ACCEPTANCE_EVIDENCE'); "
                "print('MOD_AGENT_ACCEPTANCE_VALIDATION')"
            ),
        ),
        timeout_seconds=10,
        startup_markers=("MOD_AGENT_STARTUP_OK",),
        acceptance_markers={
            EXPECTED_ACCEPTANCE_CRITERIA[0]: "MOD_AGENT_ACCEPTANCE_BEHAVIOR",
            EXPECTED_ACCEPTANCE_CRITERIA[1]: "MOD_AGENT_ACCEPTANCE_EVIDENCE",
            EXPECTED_ACCEPTANCE_CRITERIA[2]: "MOD_AGENT_ACCEPTANCE_VALIDATION",
        },
    )


def _artifact_data(
    store: ArtifactStore,
    result: dict[str, object],
    artifact_type: str,
) -> dict[str, object]:
    return _artifact_envelope(store, result, artifact_type)["data"]


def _artifact_envelope(
    store: ArtifactStore,
    result: dict[str, object],
    artifact_type: str,
) -> dict[str, object]:
    for ref in store.list_feature_artifacts(str(result["feature_id"])):
        if ref.artifact_type == artifact_type:
            return store.read(ref)
    raise AssertionError(f"Missing artifact: {artifact_type}")
