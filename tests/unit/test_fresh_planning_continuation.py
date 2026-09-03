from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.cli import main
from src.mod_agent.evidence import (
    RgLiveEvidenceProvider,
    build_requirement_coverage_pack,
    materialize_requirement_coverage_projection,
)
from src.mod_agent.fresh_planning_continuation import (
    PLANNING_CONTINUATION_CONTRACT_VERSION,
    PlanningContinuationError,
    PlanningContinuationInputV1,
    run_fresh_planning_continuation,
)
from src.mod_agent.planning import FeatureSpec, ImplementationPlan, ImplementationPlanner
from src.mod_agent.workflow import build_graph, create_initial_state


def _fresh_execution_receipt() -> dict[str, object]:
    roles = ["requirement_projection", "requirement_findings"]
    return {
        "roles": roles,
        "role_call_counts": {
            "requirement_projection": 1,
            "requirement_projection_correction": 0,
            "requirement_findings": 1,
            "requirement_findings_correction": 0,
        },
        "call_count": 2,
        "correction_count": 0,
        "attempts": [
            {
                "attempt_index": index,
                "role": role,
                "duration_seconds": 0.01,
                "status": "accepted",
                "error_code": None,
                "payload_canonical_sha256": str(index) * 64,
                "schema_canonical_sha256": str(index + 2) * 64,
                "output_canonical_sha256": str(index + 4) * 64,
            }
            for index, role in enumerate(roles, start=1)
        ],
        "budget": {
            "maximum_total_calls": 4,
            "maximum_calls_by_role": {
                "requirement_projection": 1,
                "requirement_projection_correction": 1,
                "requirement_findings": 1,
                "requirement_findings_correction": 1,
            },
            "automatic_provider_fallback": False,
            "automatic_retry": False,
        },
        "admission": {
            "provider": "ollama",
            "execution_locality": "local",
            "external_disclosure_occurred": False,
        },
    }


def _feature_payload() -> dict[str, object]:
    return FeatureSpec(
        feature_id="feature_planning_continuation",
        user_request="Change the marker while preserving existing feedback.",
        target_behavior="Use ChangeMarker for the configurable marker behavior.",
        non_goals=("PreserveFeedback must remain unchanged.",),
        target_mod="SyntheticMod",
        risk_level="medium",
        acceptance_criteria=("RuntimeMarker is observed after the change.",),
        evidence_requirements=("ConfigKey must exist before patching.",),
        runtime_verification_plan=("Observe RuntimeMarker.",),
    ).to_artifact_payload()


def _projection() -> dict[str, object]:
    return {
        "requirements": [
            {
                "role": "change",
                "text": "Use ChangeMarker for the configurable marker behavior.",
                "input_obligation_indexes": [1, 2],
                "query_leads": ["ChangeMarker"],
            },
            {
                "role": "pre_patch_evidence",
                "text": "ConfigKey must exist before patching.",
                "input_obligation_indexes": [3],
                "query_leads": ["ConfigKey"],
            },
            {
                "role": "preservation",
                "text": "PreserveFeedback must remain unchanged.",
                "input_obligation_indexes": [4],
                "query_leads": ["PreserveFeedback"],
            },
            {
                "role": "post_change_acceptance",
                "text": "RuntimeMarker is observed after the change.",
                "input_obligation_indexes": [5, 6],
                "query_leads": ["RuntimeMarker"],
            },
        ],
        "relations": [
            {
                "parent_requirement_indexes": [1, 3],
                "meaning": "The editable behavior carries the preservation guard.",
            },
            {
                "parent_requirement_indexes": [2],
                "meaning": "Configuration evidence exists before patching.",
            },
            {
                "parent_requirement_indexes": [4],
                "meaning": "Runtime acceptance is evaluated after the change.",
            },
        ],
        "input_dispositions": [],
    }


def _write_sources(workspace: Path) -> Path:
    source = workspace / "generated_mods" / "SyntheticMod"
    source.mkdir(parents=True)
    behavior = source / "Behavior.cs"
    behavior.write_text(
        "public sealed class Behavior\n"
        "{\n"
        "    public void ChangeMarker()\n"
        "    {\n"
        "        KeepExistingFeedback();\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    (source / "Configuration.cs").write_text(
        "public sealed class Configuration\n"
        "{\n"
        '    public const string ConfigKey = "Marker.Enabled";\n'
        "}\n",
        encoding="utf-8",
    )
    (source / "Preservation.cs").write_text(
        "public sealed class Preservation\n{\n    public void PreserveFeedback() { }\n}\n",
        encoding="utf-8",
    )
    return behavior


def _evidence_by_requirement(
    materialized: dict[str, object],
    retrieved,
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for row in retrieved.budget_summary["per_query_execution"]:
        result.setdefault(str(row["requirement_id"]), []).extend(
            str(value) for value in row["evidence_ids"]
        )
    return result


def _positive_findings(
    materialized: dict[str, object],
    retrieved,
) -> dict[str, object]:
    evidence = _evidence_by_requirement(materialized, retrieved)
    requirements = materialized["requirements"]
    change_id = str(requirements[0]["requirement_id"])
    prepatch_id = str(requirements[1]["requirement_id"])
    return {
        "findings": [
            {
                "relation_index": 1,
                "relationship": "support",
                "evidence_ids": [evidence[change_id][0]],
                "unresolved_gaps": [],
            },
            {
                "relation_index": 2,
                "relationship": "support",
                "evidence_ids": [evidence[prepatch_id][0]],
                "unresolved_gaps": [],
            },
            {
                "relation_index": 3,
                "relationship": "missing",
                "evidence_ids": [],
                "unresolved_gaps": ["Runtime observation occurs after patching."],
            },
        ]
    }


@dataclass(frozen=True)
class _Inputs:
    request: PlanningContinuationInputV1
    store: ArtifactStore
    workspace: Path
    behavior: Path
    feature_ref: ArtifactRef
    evidence_ref: ArtifactRef
    feature_payload: dict[str, object]


def _inputs(tmp_path: Path) -> _Inputs:
    workspace = tmp_path / "workspace"
    store_root = tmp_path / "artifact-store"
    behavior = _write_sources(workspace)
    feature = _feature_payload()
    materialized = materialize_requirement_coverage_projection(
        feature_data=feature,
        request=str(feature["user_request"]),
        projection=_projection(),
    )
    retrieved = RgLiveEvidenceProvider(workspace).collect_query_set(
        queries=tuple(dict(value) for value in materialized["queries"]),
        search_root="generated_mods/SyntheticMod",
        max_items=len(materialized["queries"]),
    )
    pack = build_requirement_coverage_pack(
        query=str(feature["user_request"]),
        materialized_projection=materialized,
        retrieved_pack=retrieved,
        findings=_positive_findings(materialized, retrieved),
    )
    pack = replace(
        pack,
        budget_summary={
            **pack.budget_summary,
            "fresh_coverage_model_execution": _fresh_execution_receipt(),
        },
    )
    assert pack.can_generate_patch is True
    store = ArtifactStore(store_root)
    feature_ref = store.write(
        feature_id=str(feature["feature_id"]),
        artifact_type="feature_spec",
        payload=feature,
        status="success",
    )
    evidence_ref = store.write(
        feature_id=str(feature["feature_id"]),
        artifact_type="evidence_pack",
        payload=pack.to_artifact_payload(),
        status="success",
        upstream_refs=[feature_ref],
    )
    request = PlanningContinuationInputV1(
        contract_version=PLANNING_CONTINUATION_CONTRACT_VERSION,
        artifact_store_root=str(store_root),
        workspace_root=str(workspace),
        feature_spec_ref=feature_ref,
        evidence_pack_ref=evidence_ref,
    )
    return _Inputs(
        request=request,
        store=store,
        workspace=workspace,
        behavior=behavior,
        feature_ref=feature_ref,
        evidence_ref=evidence_ref,
        feature_payload=feature,
    )


def _source_hashes(workspace: Path) -> dict[str, str]:
    return {
        path.relative_to(workspace).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in workspace.rglob("*.cs")
    }


def _write_evidence_revision(
    inputs: _Inputs,
    *,
    payload: dict[str, object],
) -> ArtifactRef:
    return inputs.store.write(
        feature_id=inputs.evidence_ref.feature_id,
        artifact_type="evidence_pack",
        payload=payload,
        status="success",
        upstream_refs=[inputs.feature_ref],
    )


def _direct_graph_state(inputs: _Inputs):
    state = create_initial_state(
        run_id="run_direct_planning_continuation",
        request_id="request_direct_planning_continuation",
        user_request=str(inputs.feature_payload["user_request"]),
        target_mod=str(inputs.feature_payload["target_mod"]),
    )
    state["feature_id"] = inputs.feature_ref.feature_id
    state["risk_level"] = inputs.feature_payload["risk_level"]
    state["current_stage"] = "evidence_retrieval"
    state["next_stage"] = "implementation_plan"
    state["artifacts"] = {
        "feature_spec": inputs.feature_ref.path,
        "evidence_pack": inputs.evidence_ref.path,
    }
    state["artifact_hashes"] = {
        "feature_spec": inputs.feature_ref.artifact_hash,
        "evidence_pack": inputs.evidence_ref.artifact_hash,
    }
    return state


def _cli_args(inputs: _Inputs) -> list[str]:
    return [
        "continue-fresh-planning",
        "--artifact-root",
        inputs.request.artifact_store_root,
        "--workspace-root",
        inputs.request.workspace_root,
        "--feature-id",
        inputs.feature_ref.feature_id,
        "--feature-spec-path",
        inputs.feature_ref.path,
        "--feature-spec-hash",
        inputs.feature_ref.artifact_hash,
        "--evidence-pack-path",
        inputs.evidence_ref.path,
        "--evidence-pack-hash",
        inputs.evidence_ref.artifact_hash,
    ]


def test_exact_fresh_refs_run_existing_planning_once_and_stop(
    tmp_path: Path,
    monkeypatch,
) -> None:
    inputs = _inputs(tmp_path)
    source_before = _source_hashes(inputs.workspace)
    calls = 0
    original_build = ImplementationPlanner.build

    def recording_build(self, **kwargs):
        nonlocal calls
        calls += 1
        assert kwargs["formal_requirement_coverage_required"] is True
        return original_build(self, **kwargs)

    monkeypatch.setattr(ImplementationPlanner, "build", recording_build)
    result = run_fresh_planning_continuation(inputs.request)
    public = result.to_dict()

    assert calls == 1
    assert result.status == "terminal"
    assert result.plan_blocking is False
    assert result.first_failure is None
    assert public["execution_counts"] == {
        "fresh_coverage": 0,
        "model": 0,
        "planning": 1,
        "patch": 0,
        "apply": 0,
        "build": 0,
        "runtime": 0,
    }
    assert public["stopped_before"] == "patch_proposal"
    assert public["product_source_writes_performed"] is False
    assert public["source_modified_during_run"] is False
    assert _source_hashes(inputs.workspace) == source_before
    plan_ref = ArtifactRef(**public["implementation_plan_artifact"])
    plan = inputs.store.read(plan_ref)
    assert plan["data"]["blocking"] is False
    assert {item["artifact_type"] for item in plan["inputs"]["upstream_artifacts"]} == {
        "feature_spec",
        "evidence_pack",
    }
    assert {
        ref.artifact_type
        for ref in inputs.store.list_feature_artifacts(inputs.feature_ref.feature_id)
    } == {"feature_spec", "evidence_pack", "implementation_plan"}


def test_planning_continuation_preserves_blocked_plan_and_stops(
    tmp_path: Path,
    monkeypatch,
) -> None:
    inputs = _inputs(tmp_path)

    def blocked_build(_self, *, feature_spec, **_kwargs):
        return ImplementationPlan(
            feature_id=feature_spec.feature_id,
            target_files=(),
            target_symbols=(),
            evidence_refs=(),
            proposed_changes=(),
            side_effect_boundaries=(),
            test_plan=(),
            rollback_plan=(),
            open_questions=("Synthetic planning blocker.",),
            blocking=True,
            blockers=(
                {
                    "code": "SYNTHETIC_PLANNING_BLOCKER",
                    "message": "Synthetic planning blocker.",
                },
            ),
        )

    monkeypatch.setattr(ImplementationPlanner, "build", blocked_build)
    result = run_fresh_planning_continuation(inputs.request)
    public = result.to_dict()

    assert result.status == "blocked"
    assert result.plan_blocking is True
    assert result.first_failure == {
        "code": "SYNTHETIC_PLANNING_BLOCKER",
        "stage": "implementation_plan",
    }
    assert public["execution_counts"]["planning"] == 1
    assert public["execution_counts"]["patch"] == 0
    assert result.implementation_plan_artifact is not None
    assert {
        ref.artifact_type
        for ref in inputs.store.list_feature_artifacts(inputs.feature_ref.feature_id)
    } == {"feature_spec", "evidence_pack", "implementation_plan"}


@pytest.mark.parametrize(
    ("ref_field", "replacement"),
    [
        ("feature_spec_ref", "latest"),
        ("evidence_pack_ref", "wrong_hash"),
    ],
)
def test_planning_continuation_rejects_non_exact_refs_before_planning(
    tmp_path: Path,
    monkeypatch,
    ref_field: str,
    replacement: str,
) -> None:
    inputs = _inputs(tmp_path)
    feature_ref = inputs.feature_ref
    evidence_ref = inputs.evidence_ref
    if ref_field == "feature_spec_ref":
        feature_ref = ArtifactRef(
            feature_id=feature_ref.feature_id,
            artifact_type=feature_ref.artifact_type,
            path=str(
                Path(inputs.request.artifact_store_root)
                / "features"
                / feature_ref.feature_id
                / "feature_spec.json"
            ),
            artifact_hash=feature_ref.artifact_hash,
        )
    elif replacement == "wrong_hash":
        evidence_ref = ArtifactRef(
            feature_id=evidence_ref.feature_id,
            artifact_type=evidence_ref.artifact_type,
            path=evidence_ref.path,
            artifact_hash="0" * 64,
        )
    request = PlanningContinuationInputV1(
        contract_version=PLANNING_CONTINUATION_CONTRACT_VERSION,
        artifact_store_root=inputs.request.artifact_store_root,
        workspace_root=inputs.request.workspace_root,
        feature_spec_ref=feature_ref,
        evidence_pack_ref=evidence_ref,
    )
    monkeypatch.setattr(
        ImplementationPlanner,
        "build",
        lambda *_args, **_kwargs: pytest.fail("Planning must remain unreachable"),
    )

    result = run_fresh_planning_continuation(request)

    assert result.status == "blocked"
    assert result.first_failure == {
        "code": "PLANNING_CONTINUATION_EXACT_REVISION_REQUIRED",
        "stage": "artifact_admission",
    }
    assert result.planning_execution_count == 0
    assert result.implementation_plan_artifact is None


def test_planning_continuation_rejects_stale_artifact_before_planning(
    tmp_path: Path,
    monkeypatch,
) -> None:
    inputs = _inputs(tmp_path)
    updated = deepcopy(inputs.feature_payload)
    updated["target_behavior"] = "Use a later marker behavior."
    inputs.store.write(
        feature_id=inputs.feature_ref.feature_id,
        artifact_type="feature_spec",
        payload=updated,
        status="success",
    )
    monkeypatch.setattr(
        ImplementationPlanner,
        "build",
        lambda *_args, **_kwargs: pytest.fail("Planning must remain unreachable"),
    )

    result = run_fresh_planning_continuation(inputs.request)

    assert result.status == "blocked"
    assert result.first_failure == {
        "code": "PLANNING_CONTINUATION_ARTIFACT_STALE",
        "stage": "artifact_admission",
    }
    assert result.planning_execution_count == 0


def test_planning_continuation_rejects_superseded_evidence_pack(
    tmp_path: Path,
    monkeypatch,
) -> None:
    inputs = _inputs(tmp_path)
    updated = deepcopy(inputs.store.read(inputs.evidence_ref)["data"])
    updated["message"] = "A later Fresh EvidencePack revision."
    newer_ref = _write_evidence_revision(inputs, payload=updated)
    assert newer_ref.artifact_hash != inputs.evidence_ref.artifact_hash
    monkeypatch.setattr(
        ImplementationPlanner,
        "build",
        lambda *_args, **_kwargs: pytest.fail("Planning must remain unreachable"),
    )

    result = run_fresh_planning_continuation(inputs.request)

    assert result.status == "blocked"
    assert result.first_failure == {
        "code": "PLANNING_CONTINUATION_ARTIFACT_STALE",
        "stage": "artifact_admission",
    }
    assert result.planning_execution_count == 0
    assert result.implementation_plan_artifact is None


def test_planning_continuation_rejects_missing_fresh_origin(
    tmp_path: Path,
    monkeypatch,
) -> None:
    inputs = _inputs(tmp_path)
    payload = deepcopy(inputs.store.read(inputs.evidence_ref)["data"])
    del payload["budget_summary"]["fresh_coverage_model_execution"]
    evidence_ref = _write_evidence_revision(inputs, payload=payload)
    request = replace(inputs.request, evidence_pack_ref=evidence_ref)
    monkeypatch.setattr(
        ImplementationPlanner,
        "build",
        lambda *_args, **_kwargs: pytest.fail("Planning must remain unreachable"),
    )

    result = run_fresh_planning_continuation(request)

    assert result.status == "blocked"
    assert result.first_failure == {
        "code": "PLANNING_CONTINUATION_FRESH_ORIGIN_MISSING",
        "stage": "artifact_admission",
    }
    assert result.planning_execution_count == 0
    assert result.implementation_plan_artifact is None


@pytest.mark.parametrize(
    "rejected_role",
    ["requirement_projection", "requirement_findings"],
)
def test_planning_continuation_rejects_unrepaired_fresh_model_output(
    tmp_path: Path,
    monkeypatch,
    rejected_role: str,
) -> None:
    inputs = _inputs(tmp_path)
    payload = deepcopy(inputs.store.read(inputs.evidence_ref)["data"])
    execution = payload["budget_summary"]["fresh_coverage_model_execution"]
    attempt = next(item for item in execution["attempts"] if item["role"] == rejected_role)
    attempt["status"] = "rejected"
    attempt["error_code"] = "SYNTHETIC_REJECTION"
    evidence_ref = _write_evidence_revision(inputs, payload=payload)
    request = replace(inputs.request, evidence_pack_ref=evidence_ref)
    monkeypatch.setattr(
        ImplementationPlanner,
        "build",
        lambda *_args, **_kwargs: pytest.fail("Planning must remain unreachable"),
    )

    result = run_fresh_planning_continuation(request)

    assert result.status == "blocked"
    assert result.first_failure == {
        "code": "PLANNING_CONTINUATION_FRESH_ORIGIN_INVALID",
        "stage": "artifact_admission",
    }
    assert result.planning_execution_count == 0
    assert result.implementation_plan_artifact is None


def test_planning_continuation_accepts_repaired_fresh_model_output(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    payload = deepcopy(inputs.store.read(inputs.evidence_ref)["data"])
    execution = payload["budget_summary"]["fresh_coverage_model_execution"]
    projection_attempt, findings_attempt = execution["attempts"]
    projection_attempt["status"] = "rejected"
    projection_attempt["error_code"] = "SYNTHETIC_REJECTION"
    correction_attempt = {
        **projection_attempt,
        "attempt_index": 2,
        "role": "requirement_projection_correction",
        "status": "accepted",
        "error_code": None,
        "payload_canonical_sha256": "a" * 64,
        "schema_canonical_sha256": "b" * 64,
        "output_canonical_sha256": "c" * 64,
    }
    findings_attempt["attempt_index"] = 3
    execution["roles"] = [
        "requirement_projection",
        "requirement_projection_correction",
        "requirement_findings",
    ]
    execution["role_call_counts"]["requirement_projection_correction"] = 1
    execution["call_count"] = 3
    execution["correction_count"] = 1
    execution["attempts"] = [
        projection_attempt,
        correction_attempt,
        findings_attempt,
    ]
    evidence_ref = _write_evidence_revision(inputs, payload=payload)
    request = replace(inputs.request, evidence_pack_ref=evidence_ref)

    result = run_fresh_planning_continuation(request)

    assert result.status == "terminal"
    assert result.first_failure is None
    assert result.planning_execution_count == 1
    assert result.implementation_plan_artifact is not None


def test_planning_continuation_rejects_current_source_drift_before_planning(
    tmp_path: Path,
    monkeypatch,
) -> None:
    inputs = _inputs(tmp_path)
    inputs.behavior.write_text("changed outside continuation\n", encoding="utf-8")
    monkeypatch.setattr(
        ImplementationPlanner,
        "build",
        lambda *_args, **_kwargs: pytest.fail("Planning must remain unreachable"),
    )

    result = run_fresh_planning_continuation(inputs.request)

    assert result.status == "blocked"
    assert result.first_failure == {
        "code": "PLANNING_CONTINUATION_SOURCE_HASH_MISMATCH",
        "stage": "source_validation",
    }
    assert result.planning_execution_count == 0


def test_planning_continuation_blocks_source_drift_before_plan_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    inputs = _inputs(tmp_path)
    original_build = ImplementationPlanner.build

    def build_then_drift(self, **kwargs):
        plan = original_build(self, **kwargs)
        inputs.behavior.write_text("changed during planning\n", encoding="utf-8")
        return plan

    monkeypatch.setattr(ImplementationPlanner, "build", build_then_drift)
    result = run_fresh_planning_continuation(inputs.request)

    assert result.status == "blocked"
    assert result.first_failure == {
        "code": "PLANNING_CONTINUATION_SOURCE_HASH_MISMATCH",
        "stage": "source_validation",
    }
    assert result.planning_execution_count == 1
    assert result.implementation_plan_artifact is None
    assert result.source_modified_during_run is True
    assert result.to_dict()["execution_counts"]["patch"] == 0


def test_planning_continuation_graph_rejects_state_and_control_drift(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    graph = build_graph(
        inputs.store,
        planning_continuation_mode=inputs.request,
        use_default_proposal_git_binding=False,
    )
    invalid_state = create_initial_state(
        run_id="run_invalid_planning_continuation",
        request_id="request_invalid_planning_continuation",
        user_request=str(inputs.feature_payload["user_request"]),
    )

    with pytest.raises(ValueError, match="state changed"):
        graph.invoke(invalid_state)
    with pytest.raises(ValueError, match="unrelated workflow"):
        build_graph(
            inputs.store,
            planning_continuation_mode=inputs.request,
            use_default_proposal_git_binding=False,
            patch_change_factory=lambda *_args: (),
        )


def test_planning_continuation_graph_rechecks_source_before_entry(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    graph = build_graph(
        inputs.store,
        planning_continuation_mode=inputs.request,
        use_default_proposal_git_binding=False,
    )
    state = _direct_graph_state(inputs)
    inputs.behavior.write_text("changed before direct graph entry\n", encoding="utf-8")

    with pytest.raises(PlanningContinuationError) as caught:
        graph.invoke(state)

    assert caught.value.code == "PLANNING_CONTINUATION_SOURCE_HASH_MISMATCH"
    assert caught.value.stage == "source_validation"
    assert {
        ref.artifact_type
        for ref in inputs.store.list_feature_artifacts(inputs.feature_ref.feature_id)
    } == {"feature_spec", "evidence_pack"}


def test_planning_continuation_graph_has_only_planning_reachable(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    graph = build_graph(
        inputs.store,
        planning_continuation_mode=inputs.request,
        use_default_proposal_git_binding=False,
    ).get_graph()

    assert {(edge.source, edge.target, edge.conditional) for edge in graph.edges} == {
        ("__start__", "create_implementation_plan", True),
        ("create_implementation_plan", "__end__", True),
    }


def test_continue_fresh_planning_cli_returns_one_terminal_json(
    tmp_path: Path,
    capsys,
) -> None:
    inputs = _inputs(tmp_path)

    exit_code = main(_cli_args(inputs))

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert result["result_type"] == "planning_continuation_result_v1"
    assert result["status"] == "terminal"
    assert result["stopped_before"] == "patch_proposal"
    assert result["execution_counts"]["fresh_coverage"] == 0
    assert result["execution_counts"]["model"] == 0
    assert result["execution_counts"]["planning"] == 1


def test_continue_fresh_planning_cli_returns_one_blocked_json(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    inputs = _inputs(tmp_path)

    def blocked_build(_self, *, feature_spec, **_kwargs):
        return ImplementationPlan(
            feature_id=feature_spec.feature_id,
            target_files=(),
            target_symbols=(),
            evidence_refs=(),
            proposed_changes=(),
            side_effect_boundaries=(),
            test_plan=(),
            rollback_plan=(),
            open_questions=("Synthetic planning blocker.",),
            blocking=True,
            blockers=(
                {
                    "code": "SYNTHETIC_PLANNING_BLOCKER",
                    "message": "Synthetic planning blocker.",
                },
            ),
        )

    monkeypatch.setattr(ImplementationPlanner, "build", blocked_build)

    exit_code = main(_cli_args(inputs))

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert exit_code == 1
    assert captured.err == ""
    assert result["status"] == "blocked"
    assert result["first_failure"] == {
        "code": "SYNTHETIC_PLANNING_BLOCKER",
        "stage": "implementation_plan",
    }
    assert result["implementation_plan_artifact"] is not None


def test_continue_fresh_planning_cli_admission_failure_is_terminal_json(
    tmp_path: Path,
    capsys,
) -> None:
    inputs = _inputs(tmp_path)
    args = _cli_args(inputs)
    args[args.index("--evidence-pack-hash") + 1] = "not-a-sha256"

    exit_code = main(args)

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert exit_code == 2
    assert captured.err == ""
    assert result["status"] == "blocked"
    assert result["first_failure"] == {
        "code": "PLANNING_CONTINUATION_REF_INVALID",
        "stage": "request",
    }
    assert result["implementation_plan_artifact"] is None


def test_continue_fresh_planning_cli_reports_partial_store_write(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    inputs = _inputs(tmp_path)
    original_write = ArtifactStore._write_text_atomic

    def fail_plan_latest(
        store: ArtifactStore,
        path: Path,
        content: str,
        *,
        capture_replace_error: bool = False,
    ) -> None:
        latest_plan_path = store._artifact_path(
            inputs.feature_ref.feature_id,
            "implementation_plan",
        )
        if path == latest_plan_path:
            raise OSError("injected latest ImplementationPlan write failure")
        original_write(
            store,
            path,
            content,
            capture_replace_error=capture_replace_error,
        )

    monkeypatch.setattr(ArtifactStore, "_write_text_atomic", fail_plan_latest)

    exit_code = main(_cli_args(inputs))

    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert exit_code == 2
    assert captured.err == ""
    assert result["status"] == "partial"
    assert result["first_failure"] == {
        "code": "PLANNING_CONTINUATION_PLAN_STORE_PARTIAL",
        "stage": "implementation_plan_store",
    }
    assert result["artifact_write"]["outcome"] == "partial"
    assert result["artifact_write"]["commit_started"] is True
    assert result["artifact_write"]["revision_state"] == "valid"
    assert result["artifact_write"]["pending_marker_state"] == "present"
    assert result["artifact_write"]["failure_stage"] == "latest_alias_write"
    assert result["artifact_write"]["recovery_available"] is True
    assert result["execution_counts"]["planning"] == 1
    assert result["implementation_plan_artifact"] is not None
    assert Path(result["implementation_plan_artifact"]["path"]).is_file()
    assert not inputs.store._artifact_path(
        inputs.feature_ref.feature_id,
        "implementation_plan",
    ).exists()
