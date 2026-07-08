"""Tests for the Phase A LangGraph workflow skeleton."""

from __future__ import annotations

import sys
from pathlib import Path

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.build import BuildAdapter, BuildCommandResult, BuildProfile
from src.mod_agent.evidence import FakeDenseRetrievalProvider
from src.mod_agent.knowledge import (
    BM25Indexer,
    Chunk,
    CollectionResolver,
    IncrementalIndexer,
    KnowledgeDatabase,
    SourceDefinition,
    SourceRecord,
    SourceRegistry,
)
from src.mod_agent.runtime import (
    RuntimeEvidenceItem,
    RuntimeProbeProfile,
    build_manual_runtime_evidence_payload,
    build_real_runtime_evidence_payload,
    make_runtime_probe_evidence_factory,
)
from src.mod_agent.workflow import build_graph, create_initial_state


def _knowledge_with_load_symbol(tmp_path: Path, *, root_name: str = "source") -> KnowledgeDatabase:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    root = tmp_path / root_name
    root.mkdir()
    (root / "Plugin.cs").write_text(
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
    registry = SourceRegistry(db)
    registry.register(
        SourceDefinition(
            source_id="target_mod",
            source_type="target_source",
            root_path=root,
            allowed_extensions=frozenset({".cs"}),
        )
    )
    IncrementalIndexer(database=db, source_registry=registry).index_source("target_mod")
    return db


def _plugin_marker_binding(criteria: tuple[str, ...]) -> dict[str, object]:
    return {
        "marker_source": "runtime_probe",
        "markers": [
            {
                "acceptance_criterion": criterion,
                "marker": f"MARKER_{index}",
                "observed": True,
            }
            for index, criterion in enumerate(criteria, start=1)
        ],
    }


def _knowledge_with_dense_chunk(tmp_path: Path) -> KnowledgeDatabase:
    db = KnowledgeDatabase(tmp_path / "knowledge.db")
    collection_id = "knowledge_hub"
    index_version = "v1"
    document_id = "knowledge_hub_doc_001"
    chunk_id = "knowledge_hub_chunk_001"
    db.upsert_source(
        SourceRecord(
            source_id="target_mod",
            source_type="target_source",
            root_path=collection_id,
        )
    )
    db.start_index_version(
        collection_id=collection_id,
        index_version=index_version,
        source_count=1,
        chunk_count=1,
    )
    db.upsert_chunk(
        Chunk(
            chunk_id=chunk_id,
            document_id=document_id,
            text="Dense-only runtime hook evidence lives in this chunk.",
            text_for_retrieval="Dense-only runtime hook evidence lives in this chunk.",
            metadata={
                "chunk_id": chunk_id,
                "document_id": document_id,
                "source_ref": document_id,
                "content_hash": "knowledge_hub_chunk_hash",
                "file_hash": "knowledge_hub_file_hash",
                "source_hash": "knowledge_hub_file_hash",
                "doc_hash": "knowledge_hub_doc_hash",
                "source_id": "target_mod",
                "source_type": "target_source",
                "source_path": "knowledge_hub/runtime.json",
            },
        ),
        collection_id=collection_id,
        index_version=index_version,
    )
    BM25Indexer(db).index(collection_id=collection_id, index_version=index_version)
    db.set_index_version_status(
        collection_id=collection_id,
        index_version=index_version,
        status="stable",
    )
    return db


def _real_build_result_factory(tmp_path: Path):
    build_root = tmp_path / "build"
    expected_artifact = build_root / "bin" / "Debug" / "BetterHitFeedback.dll"

    def build_result_factory(feature_id: str, input_execution_mode: str | None):
        def runner(_: BuildProfile) -> BuildCommandResult:
            expected_artifact.parent.mkdir(parents=True)
            expected_artifact.write_bytes(b"verified runtime build")
            return BuildCommandResult(exit_code=0, stdout="Build succeeded", duration_ms=8)

        return BuildAdapter().run_local(
            feature_id=feature_id,
            profile=BuildProfile(
                profile_id="test_dotnet",
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


def test_evidence_backed_path_reaches_done(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
    )
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "done"
    assert "workflow_summary" in result["artifacts"]
    assert "blocked_report" not in result["artifacts"]
    assert result["blockers"] == []
    assert result["evidence_summary"]["can_generate_patch"] is True
    assert result["evidence_summary"]["retrieval_methods_used"] == ["symbol_exact"]
    assert result["evidence_summary"]["missing_evidence"] == []
    assert result["evidence_summary"]["timing"]["final_count"] == 1.0
    assert result["review_summary"]["allowed_next_stage"] == "dry_run_apply"
    assert result["build_summary"]["execution_mode"] == "fake"
    assert result["build_summary"]["claims_real_build_success"] is False
    assert result["runtime_summary"]["status"] == "verified"
    assert result["runtime_summary"]["acceptance_verified"] is True
    assert result["runtime_summary"]["claims_real_runtime_success"] is False


def test_missing_knowledge_routes_to_blocked_after_evidence(tmp_path: Path) -> None:
    graph = build_graph(ArtifactStore(tmp_path / "artifacts"))
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_domain="gtfo",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "blocked"
    assert "evidence_pack" in result["artifacts"]
    assert "implementation_plan" not in result["artifacts"]
    assert "patch_proposal" not in result["artifacts"]
    assert "proposal_review" not in result["artifacts"]
    assert "dry_run_result" not in result["artifacts"]
    assert "build_result" not in result["artifacts"]
    assert "runtime_evidence" not in result["artifacts"]
    assert result["evidence_summary"]["readiness"] == "insufficient"
    assert result["evidence_summary"]["missing_evidence"]
    assert result["evidence_summary"]["timing"]["final_count"] == 0.0
    assert result["blockers"]


def test_collection_resolution_failure_routes_to_blocked_after_evidence(
    tmp_path: Path,
) -> None:
    graph = build_graph(
        ArtifactStore(tmp_path / "artifacts"),
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        collection_resolver=CollectionResolver(settings_path=tmp_path / "missing.yaml"),
    )
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "blocked"
    assert result["evidence_summary"]["readiness"] == "insufficient"
    assert result["evidence_summary"]["can_generate_patch"] is False
    assert "Collection resolution failed" in result["evidence_summary"]["gaps"][0]
    assert result["blockers"][0]["code"] == "INSUFFICIENT_EVIDENCE"


def test_vague_request_routes_to_blocked(tmp_path: Path) -> None:
    graph = build_graph(ArtifactStore(tmp_path / "artifacts"))
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="test",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "blocked"
    assert "request_planning_report" in result["artifacts"]
    assert "blocked_report" in result["artifacts"]
    assert result["blockers"]
    assert result["blockers"][0]["stage"] == "request_planning"


def test_graph_trace_contains_node_started_and_finished(tmp_path: Path) -> None:
    graph = build_graph(
        ArtifactStore(tmp_path / "artifacts"),
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
    )
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    event_types = {event["event_type"] for event in result["trace_events"]}
    assert "node_started" in event_types
    assert "node_finished" in event_types
    assert any(event["node_name"] == "plan_request" for event in result["trace_events"])
    assert any(event["node_name"] == "done" for event in result["trace_events"])


def test_retrieve_evidence_trace_exposes_pack_summary(tmp_path: Path) -> None:
    graph = build_graph(
        ArtifactStore(tmp_path / "artifacts"),
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
    )
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    event = _finished_event(result, "retrieve_evidence")
    assert event["status"] == "success"
    assert event["artifact_refs"] == [result["artifacts"]["evidence_pack"]]
    assert event["details"]["readiness"] == "sufficient"
    assert event["details"]["can_generate_patch"] is True
    assert event["details"]["retrieval_methods_used"] == ["symbol_exact"]
    assert event["details"]["missing_evidence_count"] == 0
    assert event["details"]["disabled_modes"]["bm25"]
    assert event["details"]["timing"]["final_count"] == 1.0


def test_retrieve_evidence_trace_records_blocked_summary(tmp_path: Path) -> None:
    graph = build_graph(ArtifactStore(tmp_path / "artifacts"))
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    event = _finished_event(result, "retrieve_evidence")
    assert event["status"] == "blocked"
    assert event["details"]["readiness"] == "insufficient"
    assert event["details"]["can_generate_patch"] is False
    assert event["details"]["missing_evidence_count"] > 0
    assert event["details"]["timing"]["final_count"] == 0.0


def test_graph_writes_artifacts_through_store(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(store, knowledge_database=_knowledge_with_load_symbol(tmp_path))
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    refs = store.list_feature_artifacts(result["feature_id"])
    artifact_types = {ref.artifact_type for ref in refs}
    assert "feature_spec" in artifact_types
    assert "workflow_summary" in artifact_types
    assert set(result["artifacts"]).issubset(artifact_types)


def test_graph_retrieve_evidence_can_use_injected_dense_provider(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    knowledge_database = _knowledge_with_dense_chunk(tmp_path)
    stable_version = knowledge_database.stable_index_version("knowledge_hub")
    assert stable_version is not None
    chunks = knowledge_database.list_chunks(
        collection_id="knowledge_hub",
        index_version=stable_version.index_version,
    )
    assert chunks
    graph = build_graph(
        store,
        knowledge_database=knowledge_database,
        dense_enabled=True,
        dense_provider=FakeDenseRetrievalProvider({chunks[0].chunk_id: 0.88}),
        dense_top_k=1,
    )
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make MissingDenseOnly enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    evidence_pack = _artifact_data(store, result, "evidence_pack")
    assert "dense" in evidence_pack["retrieval_methods_used"]
    assert evidence_pack["items"][0]["retrieval_method"] == "dense"
    assert evidence_pack["items"][0]["chunk_id"] == chunks[0].chunk_id


def test_approved_path_writes_explicit_fake_execution_artifacts(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(store, knowledge_database=_knowledge_with_load_symbol(tmp_path))
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    dry_run = _artifact_data(store, result, "dry_run_result")
    build = _artifact_data(store, result, "build_result")
    runtime = _artifact_data(store, result, "runtime_evidence")
    evaluation = _artifact_data(store, result, "eval_report")
    summary = _artifact_data(store, result, "workflow_summary")

    assert dry_run["execution_mode"] == "fake"
    assert dry_run["actual_write_performed"] is False
    assert dry_run["real_patch_applied"] is False
    assert build["execution_mode"] == "fake"
    assert build["status"] == "skipped"
    assert build["real_build_performed"] is False
    assert build["build_status"] == "fake_completed"
    assert build["claims_real_build_success"] is False
    assert build["repair_handoff"]["allowed"] is False
    assert runtime["execution_mode"] == "fake"
    assert runtime["runtime_status"] == "verified"
    assert runtime["verification_status"] == "verified"
    assert runtime["acceptance_status"] == "accepted"
    assert runtime["acceptance_verified"] is True
    assert runtime["startup_loaded"] is True
    assert runtime["gameplay_behavior_verified"] is True
    assert runtime["real_runtime_performed"] is False
    assert runtime["raw_supplied_output"] is None
    assert runtime["claims_real_runtime_success"] is False
    assert runtime["acceptance_contract"]["acceptance_criteria"]
    assert evaluation["workflow_completion_status"] == "fake_execution_completed"
    assert evaluation["requested_behavior_status"] == "verified"
    assert evaluation["verdict"] == "inconclusive"
    assert evaluation["claims_real_success"] is False
    assert evaluation["evaluation_gate"]["status"] == "passed"
    assert {
        case["case_id"] for case in evaluation["evaluation_gate"]["cases"]
    } >= {
        "claim_boundary_no_false_success",
        "claim_boundary_no_false_block",
        "false_continue_after_review",
        "review_correctness",
        "dry_run_safety",
        "build_claim_boundary",
        "runtime_claim_boundary",
    }
    assert evaluation["v1_acceptance_status"] == "blocked"
    assert {
        blocker["code"] for blocker in evaluation["v1_acceptance_blockers"]
    } == {
        "REAL_BUILD_EVIDENCE_MISSING",
        "REAL_RUNTIME_MODE_REQUIRED",
        "REAL_RUNTIME_EVIDENCE_MISSING",
        "REAL_RUNTIME_SUCCESS_NOT_CLAIMED",
    }
    assert evaluation["input_acceptance_status"] == "accepted"
    assert evaluation["input_acceptance_verified"] is True
    assert evaluation["acceptance_contract"] == runtime["acceptance_contract"]
    assert summary["workflow_completion_status"] == "fake_execution_completed"
    assert summary["requested_behavior_status"] == "verified"
    assert summary["final_status"] == "inconclusive"
    assert summary["claims_real_mod_success"] is False
    assert summary["claims_real_build_success"] is False
    assert summary["claims_real_runtime_success"] is False
    assert summary["v1_acceptance_status"] == "blocked"
    assert summary["v1_acceptance_blockers"] == evaluation["v1_acceptance_blockers"]


def test_real_runtime_evidence_path_can_accept_v1_boundary(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    build_result_factory = _real_build_result_factory(tmp_path)

    def runtime_evidence_factory(
        feature_id: str,
        build: dict[str, object],
        feature_spec: dict[str, object],
    ) -> dict[str, object]:
        criteria = tuple(str(item) for item in feature_spec["acceptance_criteria"])
        return build_real_runtime_evidence_payload(
            feature_id=feature_id,
            input_execution_mode=str(build["execution_mode"]),
            evidence_items=(
                RuntimeEvidenceItem(
                    item_type="runtime_log",
                    source="runtime_probe",
                    locator="runtime://probe-001",
                    supports_acceptance=criteria,
                    confidence=1.0,
                    raw_excerpt="Runtime probe observed the requested behavior.",
                ),
            ),
            startup_loaded=True,
            gameplay_behavior_verified=True,
            verification_status="verified",
            raw_runtime_output="Runtime probe observed the requested behavior.",
            acceptance_criteria=criteria,
            runtime_verification_plan=tuple(
                str(item) for item in feature_spec["runtime_verification_plan"]
            ),
            plugin_marker_binding=_plugin_marker_binding(criteria),
        )

    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        build_result_factory=build_result_factory,
        runtime_evidence_factory=runtime_evidence_factory,
    )
    state = create_initial_state(
        run_id="run_real_runtime",
        request_id="req_real_runtime",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    build = _artifact_data(store, result, "build_result")
    runtime = _artifact_data(store, result, "runtime_evidence")
    evaluation = _artifact_data(store, result, "eval_report")
    summary = _artifact_data(store, result, "workflow_summary")

    assert result["current_stage"] == "done"
    assert build["execution_mode"] == "local"
    assert build["claims_real_build_success"] is True
    assert runtime["execution_mode"] == "real"
    assert runtime["real_runtime_performed"] is True
    assert runtime["claims_real_runtime_success"] is True
    assert runtime["acceptance_verified"] is True
    assert runtime["run_id"] == "run_real_runtime"
    assert runtime["build_artifact_ref"]["artifact_type"] == "build_result"
    assert runtime["build_artifact_hash"] == result["artifact_hashes"]["build_result"]
    assert runtime["plugin_marker_binding"]["markers"]
    assert evaluation["v1_acceptance_status"] == "accepted"
    assert evaluation["v1_acceptance_blockers"] == []
    assert evaluation["evaluation_gate"]["status"] == "passed"
    assert evaluation["workflow_completion_status"] == "real_runtime_acceptance_completed"
    assert evaluation["verdict"] == "accepted"
    assert evaluation["claims_real_success"] is True
    assert summary["final_status"] == "accepted"
    assert summary["claims_real_mod_success"] is True
    assert summary["claims_real_build_success"] is True
    assert summary["claims_real_runtime_success"] is True


def test_manual_runtime_evidence_does_not_accept_v1_boundary(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    build_result_factory = _real_build_result_factory(tmp_path)

    def runtime_evidence_factory(
        feature_id: str,
        build: dict[str, object],
        feature_spec: dict[str, object],
    ) -> dict[str, object]:
        criteria = tuple(str(item) for item in feature_spec["acceptance_criteria"])
        return build_manual_runtime_evidence_payload(
            feature_id=feature_id,
            evidence_items=(
                RuntimeEvidenceItem(
                    item_type="manual_observation",
                    source="manual_runtime_note",
                    locator="manual://note-001",
                    supports_acceptance=criteria,
                    confidence=1.0,
                    raw_excerpt="Manual verification observed the requested behavior.",
                ),
            ),
            startup_loaded=True,
            gameplay_behavior_verified=True,
            verification_status="verified",
            acceptance_criteria=criteria,
            runtime_verification_plan=tuple(
                str(item) for item in feature_spec["runtime_verification_plan"]
            ),
            plugin_marker_binding=_plugin_marker_binding(criteria),
        )

    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        build_result_factory=build_result_factory,
        runtime_evidence_factory=runtime_evidence_factory,
    )
    state = create_initial_state(
        run_id="run_manual_runtime",
        request_id="req_manual_runtime",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    runtime = _artifact_data(store, result, "runtime_evidence")
    evaluation = _artifact_data(store, result, "eval_report")

    assert result["current_stage"] == "blocked"
    assert "workflow_summary" not in result["artifacts"]
    assert "blocked_report" in result["artifacts"]
    eval_ref = _artifact_ref(store, result, "eval_report")
    assert store.read(eval_ref)["status"] == "blocked"
    assert runtime["execution_mode"] == "manual"
    assert runtime["claims_real_runtime_success"] is True
    assert runtime["acceptance_verified"] is True
    assert evaluation["v1_acceptance_status"] == "blocked"
    assert evaluation["evaluation_gate"]["status"] == "failed"
    assert {
        blocker["code"] for blocker in result["blockers"]
    } == {
        "EVAL_GATE_RUNTIME_CLAIM_BOUNDARY_EXECUTION_MODE_FAILED",
    }
    assert {
        blocker["code"] for blocker in evaluation["v1_acceptance_blockers"]
    } == {"REAL_RUNTIME_MODE_REQUIRED", "REAL_RUNTIME_EVIDENCE_MISSING"}


def test_eval_gate_insufficient_baseline_blocks_done(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    build_result_factory = _real_build_result_factory(tmp_path)

    def runtime_evidence_factory(
        feature_id: str,
        build: dict[str, object],
        feature_spec: dict[str, object],
    ) -> dict[str, object]:
        criteria = tuple(str(item) for item in feature_spec["acceptance_criteria"])
        return build_real_runtime_evidence_payload(
            feature_id=feature_id,
            input_execution_mode=str(build["execution_mode"]),
            evidence_items=(
                RuntimeEvidenceItem(
                    item_type="runtime_log",
                    source="runtime_probe",
                    locator="runtime://probe-001",
                    supports_acceptance=criteria,
                    confidence=1.0,
                    raw_excerpt="Runtime probe observed the requested behavior.",
                ),
            ),
            startup_loaded=True,
            gameplay_behavior_verified=True,
            verification_status="verified",
            raw_runtime_output="Runtime probe observed the requested behavior.",
            acceptance_criteria=criteria,
            runtime_verification_plan=tuple(
                str(item) for item in feature_spec["runtime_verification_plan"]
            ),
            plugin_marker_binding=_plugin_marker_binding(criteria),
        )

    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        build_result_factory=build_result_factory,
        runtime_evidence_factory=runtime_evidence_factory,
        evaluation_context_factory=lambda _: {
            "baseline_status": "insufficient_baseline",
        },
    )
    state = create_initial_state(
        run_id="run_eval_baseline",
        request_id="req_eval_baseline",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    evaluation = _artifact_data(store, result, "eval_report")
    eval_ref = _artifact_ref(store, result, "eval_report")
    assert result["current_stage"] == "blocked"
    assert store.read(eval_ref)["status"] == "blocked"
    assert evaluation["evaluation_gate"]["status"] == "failed"
    assert "workflow_summary" not in result["artifacts"]
    assert "blocked_report" in result["artifacts"]
    assert any(
        blocker["code"] == "EVAL_GATE_INSUFFICIENT_BASELINE_FAILED"
        for blocker in result["blockers"]
    )


def test_real_runtime_without_success_claim_does_not_accept_v1_boundary(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    build_result_factory = _real_build_result_factory(tmp_path)

    def runtime_evidence_factory(
        feature_id: str,
        build: dict[str, object],
        feature_spec: dict[str, object],
    ) -> dict[str, object]:
        criteria = tuple(str(item) for item in feature_spec["acceptance_criteria"])
        payload = build_real_runtime_evidence_payload(
            feature_id=feature_id,
            input_execution_mode=str(build["execution_mode"]),
            evidence_items=(
                RuntimeEvidenceItem(
                    item_type="runtime_log",
                    source="runtime_probe",
                    locator="runtime://probe-001",
                    supports_acceptance=criteria,
                    confidence=1.0,
                    raw_excerpt="Runtime probe observed the requested behavior.",
                ),
            ),
            startup_loaded=True,
            gameplay_behavior_verified=True,
            verification_status="verified",
            raw_runtime_output="Runtime probe observed the requested behavior.",
            acceptance_criteria=criteria,
            runtime_verification_plan=tuple(
                str(item) for item in feature_spec["runtime_verification_plan"]
            ),
        )
        payload["claims_real_runtime_success"] = False
        return payload

    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        build_result_factory=build_result_factory,
        runtime_evidence_factory=runtime_evidence_factory,
    )
    state = create_initial_state(
        run_id="run_real_runtime_without_success",
        request_id="req_real_runtime_without_success",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    runtime = _artifact_data(store, result, "runtime_evidence")
    evaluation = _artifact_data(store, result, "eval_report")

    assert runtime["execution_mode"] == "real"
    assert runtime["real_runtime_performed"] is True
    assert runtime["acceptance_verified"] is True
    assert runtime["claims_real_runtime_success"] is False
    assert evaluation["v1_acceptance_status"] == "blocked"
    assert {
        blocker["code"] for blocker in evaluation["v1_acceptance_blockers"]
    } == {"REAL_RUNTIME_SUCCESS_NOT_CLAIMED"}


def test_runtime_probe_factory_can_accept_v1_boundary(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    build_result_factory = _real_build_result_factory(tmp_path)
    requested_behavior = "make Load enable diagnostics"
    acceptance_criteria = (
        f"Requested behavior is implemented: {requested_behavior}",
        "Every proposed change is bound to evidence.",
        "Validation output is reported with real command or artifact evidence.",
    )
    profile = RuntimeProbeProfile(
        profile_id="graph_runtime_probe",
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
            acceptance_criteria[0]: "MOD_AGENT_ACCEPTANCE_BEHAVIOR",
            acceptance_criteria[1]: "MOD_AGENT_ACCEPTANCE_EVIDENCE",
            acceptance_criteria[2]: "MOD_AGENT_ACCEPTANCE_VALIDATION",
        },
    )

    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
        build_result_factory=build_result_factory,
        runtime_evidence_factory=make_runtime_probe_evidence_factory(
            profile=profile,
            allow_execution=True,
        ),
    )
    state = create_initial_state(
        run_id="run_runtime_probe",
        request_id="req_runtime_probe",
        user_request=requested_behavior,
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    runtime = _artifact_data(store, result, "runtime_evidence")
    evaluation = _artifact_data(store, result, "eval_report")

    assert runtime["execution_mode"] == "real"
    assert runtime["evidence_source"] == "real_runtime_probe"
    assert runtime["real_runtime_performed"] is True
    assert runtime["acceptance_verified"] is True
    assert runtime["claims_real_runtime_success"] is True
    assert runtime["raw_supplied_output"] is not None
    assert runtime["run_id"] == "run_runtime_probe"
    assert runtime["build_artifact_hash"] == result["artifact_hashes"]["build_result"]
    assert len(runtime["plugin_marker_binding"]["markers"]) == len(acceptance_criteria)
    assert evaluation["v1_acceptance_status"] == "accepted"
    assert evaluation["v1_acceptance_blockers"] == []


def test_review_block_does_not_create_fake_success_artifacts(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path, root_name="secrets"),
    )
    state = create_initial_state(
        run_id="run_001",
        request_id="req_001",
        user_request="make Load enable diagnostics",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "blocked"
    assert result["review_summary"]["allowed_next_stage"] is None
    assert "proposal_review" in result["artifacts"]
    assert "dry_run_result" not in result["artifacts"]
    assert "build_result" not in result["artifacts"]
    assert "runtime_evidence" not in result["artifacts"]
    assert "workflow_summary" not in result["artifacts"]


def test_default_graph_uses_domain_policy_for_unsupported_domain(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        knowledge_database=_knowledge_with_load_symbol(tmp_path),
    )
    state = create_initial_state(
        run_id="run_domain_policy",
        request_id="req_domain_policy",
        user_request="make Load change runtime behavior",
        target_domain="unsupported",
        target_mod="BetterHitFeedback",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "blocked"
    assert "proposal_review" in result["artifacts"]
    assert "dry_run_result" not in result["artifacts"]
    assert result["review_summary"]["allowed_next_stage"] is None
    assert any(blocker["code"] == "DOMAIN_PROFILE" for blocker in result["blockers"])
    review = _artifact_data(store, result, "proposal_review")
    assert review["decision"] == "blocked_requires_human"
    assert any(finding["rule_id"] == "domain_profile" for finding in review["findings"])


def _artifact_data(
    store: ArtifactStore,
    result: dict[str, object],
    artifact_type: str,
) -> dict[str, object]:
    return store.read(_artifact_ref(store, result, artifact_type))["data"]


def _artifact_ref(
    store: ArtifactStore,
    result: dict[str, object],
    artifact_type: str,
):
    for ref in store.list_feature_artifacts(str(result["feature_id"])):
        if ref.artifact_type == artifact_type:
            return ref
    raise AssertionError(f"Missing artifact: {artifact_type}")


def _finished_event(result: dict[str, object], node_name: str) -> dict[str, object]:
    for event in result["trace_events"]:
        if event["node_name"] == node_name and event["event_type"] == "node_finished":
            return event
    raise AssertionError(f"Missing finished event: {node_name}")
