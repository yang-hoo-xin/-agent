"""Tests for the controlled-agent read-only MCP tool surface."""

from __future__ import annotations

import json
from pathlib import Path

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.mcp import (
    CONTROLLED_AGENT_TOOL_NAMES,
    DANGEROUS_TOOL_NAMES,
    ControlledAgentMCPToolSurface,
)
from src.mod_agent.performance import BudgetLimit, OperationUsage, PerformanceBudgetPolicy


def test_controlled_agent_mcp_tools_hide_dangerous_actions(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    surface = ControlledAgentMCPToolSurface(store)

    tools = surface.list_tools()
    tool_names = {tool["name"] for tool in tools}

    assert tool_names == set(CONTROLLED_AGENT_TOOL_NAMES)
    assert tool_names.isdisjoint(DANGEROUS_TOOL_NAMES)
    for tool in tools:
        assert tool["annotations"] == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    get_artifact_schema = next(tool for tool in tools if tool["name"] == "get_artifact")[
        "inputSchema"
    ]
    assert get_artifact_schema["properties"]["artifact_type"]["enum"] == sorted(
        store.registry.artifact_types()
    )
    blocked = surface.call_tool("run_game", {})
    assert blocked["status"] == "unsupported"
    assert blocked["isError"] is True
    assert blocked["blockers"][0]["code"] == "UNSUPPORTED_TOOL"


def test_every_tool_result_has_mcp_structured_fields(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    surface = ControlledAgentMCPToolSurface(store)

    result = surface.call_tool("list_features", {})

    assert set(result) == {
        "status",
        "content",
        "structuredContent",
        "artifact_refs",
        "trace_refs",
        "blockers",
        "isError",
    }
    assert result["status"] == "available"
    assert result["structuredContent"] == {
        "feature_ids": [],
        "feature_count": 0,
    }
    assert result["content"][0] == {
        "type": "text",
        "text": "Found 0 controlled-agent feature ids.",
    }
    assert json.loads(result["content"][1]["text"]) == result["structuredContent"]


def test_get_job_status_uses_budget_summary_for_degraded_decision(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    decision = PerformanceBudgetPolicy(
        [
            BudgetLimit(
                operation="captions",
                max_items=1,
                on_exceed="degrade",
            )
        ]
    ).check(OperationUsage(operation="captions", item_count=2))
    payload = PerformanceBudgetPolicy([]).to_job_status_payload(
        job_id="job_perf_degraded",
        decision=decision,
        created_at="2026-07-04T00:00:00Z",
        started_at="2026-07-04T00:00:00Z",
        finished_at="2026-07-04T00:00:01Z",
        trace_refs=("trace_budget_degraded",),
    )
    store.write(
        feature_id="feature_001",
        artifact_type="job_status",
        payload=payload,
        status=decision.artifact_status(),
        trace_refs=["trace_budget_degraded"],
    )

    result = ControlledAgentMCPToolSurface(store).call_tool(
        "get_job_status",
        {"feature_id": "feature_001"},
    )

    assert decision.status == "degraded"
    assert decision.allowed is True
    assert decision.artifact_status() == "blocked"
    assert payload["status"] == "degraded"
    assert payload["budget_summary"]["status"] == "degraded"
    assert result["status"] == "degraded"
    assert result["isError"] is False
    assert result["blockers"] == []
    assert result["trace_refs"] == ["trace_budget_degraded"]
    structured = result["structuredContent"]
    assert structured["budget_decision"] == {
        "status": "degraded",
        "allowed": True,
        "source": "budget_summary",
    }
    assert structured["artifact_visibility"]["envelope_status"] == "blocked"
    assert "budget_summary.allowed" in structured["artifact_visibility"]["rule"]


def test_get_job_status_blocks_budget_summary_disallow(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    decision = PerformanceBudgetPolicy(
        [BudgetLimit(operation="retrieval", max_items=1, on_exceed="block")]
    ).check(OperationUsage(operation="retrieval", item_count=2))
    payload = PerformanceBudgetPolicy([]).to_job_status_payload(
        job_id="job_perf_blocked",
        decision=decision,
    )
    store.write(
        feature_id="feature_001",
        artifact_type="job_status",
        payload=payload,
        status=decision.artifact_status(),
    )

    result = ControlledAgentMCPToolSurface(store).call_tool(
        "get_job_status",
        {"feature_id": "feature_001"},
    )

    assert result["status"] == "blocked"
    assert result["isError"] is True
    assert result["structuredContent"]["budget_decision"]["allowed"] is False


def test_get_job_status_blocks_ambiguous_multiple_job_refs(tmp_path, monkeypatch) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    payload = PerformanceBudgetPolicy([]).to_job_status_payload(
        job_id="job_perf_success",
        decision=PerformanceBudgetPolicy([]).check(OperationUsage(operation="retrieval")),
    )
    ref = store.write(
        feature_id="feature_001",
        artifact_type="job_status",
        payload=payload,
    )
    surface = ControlledAgentMCPToolSurface(store)

    monkeypatch.setattr(
        surface,
        "_refs_by_type",
        lambda feature_id, artifact_type: [ref, ref],
    )

    result = surface.call_tool(
        "get_job_status",
        {"feature_id": "feature_001"},
    )

    assert result["status"] == "blocked"
    assert result["isError"] is True
    assert "Multiple 'job_status' artifacts exist" in result["structuredContent"]["error"]


def test_get_artifact_returns_sanitized_projection_not_raw_body(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    _write_patch_proposal_chain(store)

    result = ControlledAgentMCPToolSurface(store).call_tool(
        "get_artifact",
        {"feature_id": "feature_001", "artifact_type": "patch_proposal"},
    )

    latest_patch_ref = next(
        ref
        for ref in store.list_feature_artifacts("feature_001")
        if ref.artifact_type == "patch_proposal"
    )
    assert result["status"] == "available"
    assert result["artifact_refs"] == [_artifact_ref_string(latest_patch_ref)]
    artifact = result["structuredContent"]["artifact"]
    assert artifact["dashboard_projection"]["files"]["count"] == 1
    assert "diff_intent" not in artifact["dashboard_projection"]
    assert result["structuredContent"]["raw_body_exposed"] is False


def test_preview_tools_return_read_only_summaries(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    _write_patch_proposal_chain(store)

    retrieval = ControlledAgentMCPToolSurface(store).call_tool(
        "preview_retrieval",
        {"feature_id": "feature_001"},
    )
    proposal = ControlledAgentMCPToolSurface(store).call_tool(
        "preview_patch_proposal",
        {"feature_id": "feature_001"},
    )

    assert retrieval["structuredContent"]["retrieval"]["readiness"] == "sufficient"
    assert proposal["structuredContent"]["proposal"]["blocked"] is False


def test_get_eval_report_exposes_evaluation_gate_status(tmp_path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    _write_eval_report_chain(store)

    result = ControlledAgentMCPToolSurface(store).call_tool(
        "get_eval_report",
        {"feature_id": "feature_001"},
    )

    assert result["status"] == "inconclusive"
    assert result["structuredContent"]["eval"]["evaluation_gate_status"] == "failed"
    assert result["structuredContent"]["eval"]["evaluation_gate_failed"] == 1


def _write_patch_proposal_chain(store: ArtifactStore) -> dict[str, ArtifactRef]:
    feature_ref = store.write(
        feature_id="feature_001",
        artifact_type="feature_spec",
        payload={
            "node_name": "feature_spec",
            "stage": "feature_spec",
            "message": "Feature spec ready.",
            "feature_id": "feature_001",
            "user_request": "Change marker color.",
            "target_behavior": "Marker color changes.",
            "non_goals": [],
            "target_mod": "ExampleMod",
            "risk_level": "low",
            "acceptance_criteria": ["Color changes."],
            "evidence_requirements": ["target_source"],
            "runtime_verification_plan": ["manual"],
            "blocked": False,
            "blockers": [],
        },
    )
    evidence_ref = store.write(
        feature_id="feature_001",
        artifact_type="evidence_pack",
        payload={
            "node_name": "evidence_retrieval",
            "stage": "evidence_retrieval",
            "message": "Evidence ready.",
            "query": "marker color",
            "readiness": "sufficient",
            "can_generate_patch": True,
            "authority": "mod_agent_deterministic_evidence",
            "authoritative_for_patch": True,
            "identity_schema_version": "identity_v1",
            "identity_field_mapping": {
                "document_id": "Loaded document id",
                "file_hash": "Loaded source file hash",
                "source_hash": "V1 alias for file_hash",
                "doc_hash": "Document canonical text hash",
                "chunk_id": "Stable chunk id",
                "source_ref": "Chunk-to-document reference",
                "content_hash": "Stored content hash",
            },
            "items": [],
            "gaps": [],
            "excluded": [],
            "blockers": [],
            "retrieval_methods_used": ["symbol"],
            "missing_evidence": [],
            "disabled_modes": {},
            "timing": {},
            "trace_refs": [],
        },
        upstream_refs=[feature_ref],
    )
    plan_ref = store.write(
        feature_id="feature_001",
        artifact_type="implementation_plan",
        payload={
            "node_name": "implementation_plan",
            "stage": "implementation_plan",
            "message": "Plan ready.",
            "feature_id": "feature_001",
            "evidence_source_paths": ["src/example.py"],
            "target_files": ["src/example.py"],
            "target_symbols": ["Example.update_marker"],
            "evidence_refs": ["ev_001"],
            "proposed_changes": ["Change marker color branch."],
            "side_effect_boundaries": ["No runtime hook changes."],
            "test_plan": ["unit"],
            "rollback_plan": ["revert patch"],
            "open_questions": [],
            "blocking": False,
            "blockers": [],
        },
        upstream_refs=[feature_ref, evidence_ref],
    )
    proposal_ref = store.write(
        feature_id="feature_001",
        artifact_type="patch_proposal",
        payload={
            "node_name": "patch_proposal",
            "stage": "patch_proposal",
            "message": "Proposal ready.",
            "proposal_id": "proposal_001",
            "feature_id": "feature_001",
            "summary": "Change marker color branch.",
            "files": ["src/example.py"],
            "diff_intent": [
                {
                    "change_id": "chg_001",
                    "path": "src/example.py",
                    "target_file": "src/example.py",
                    "edit_target_path": "src/example.py",
                    "evidence_refs": ["ev_001"],
                    "rollback_hint": "revert patch",
                    "body": "raw diff body must not appear in MCP projection",
                }
            ],
            "change_units": [
                {
                    "change_unit_id": "chg_001",
                    "change_type": None,
                    "target_file": "src/example.py",
                    "edit_target_path": "src/example.py",
                    "target_symbol": None,
                    "evidence_refs": ["ev_001"],
                    "expected_validation": [],
                    "rollback_hint": "revert patch",
                }
            ],
            "context_pack": {
                "feature_id": "feature_001",
                "files": ["src/example.py"],
                "evidence_refs": ["ev_001"],
                "evidence_source_paths": ["src/example.py"],
                "scope_boundary": ["marker branch only"],
                "change_unit_ids": ["chg_001"],
            },
            "evidence_refs": ["ev_001"],
            "scope_boundary": ["marker branch only"],
            "risk_assessment": {"level": "low"},
            "expected_tests": ["unit"],
            "no_op_status": {"is_no_op": False, "reason": None},
            "rollback_hints": [
                {
                    "change_unit_id": "chg_001",
                    "rollback_hint": "revert patch",
                }
            ],
            "manual_review_notes": [],
            "blocked": False,
            "blockers": [],
        },
        upstream_refs=[plan_ref, evidence_ref],
    )
    return {
        "feature_spec": feature_ref,
        "evidence_pack": evidence_ref,
        "implementation_plan": plan_ref,
        "patch_proposal": proposal_ref,
    }


def _write_eval_report_chain(store: ArtifactStore) -> dict[str, ArtifactRef]:
    refs = _write_patch_proposal_chain(store)
    review_ref = store.write(
        feature_id="feature_001",
        artifact_type="proposal_review",
        payload={
            "node_name": "review_proposal",
            "stage": "proposal_review",
            "message": "Proposal approved for dry-run.",
            "decision": "approve_dry_run",
            "findings": [],
            "required_changes": [],
            "allowed_next_stage": "dry_run_apply",
            "checked_rules": [],
            "trace_metrics": {"num_changes_checked": 1, "num_blocking_findings": 0},
        },
        upstream_refs=[refs["patch_proposal"]],
    )
    dry_run_ref = store.write(
        feature_id="feature_001",
        artifact_type="dry_run_result",
        payload={
            "node_name": "dry_run_apply",
            "stage": "dry_run_apply",
            "message": "Dry run completed.",
        },
        upstream_refs=[refs["patch_proposal"], review_ref],
    )
    build_ref = store.write(
        feature_id="feature_001",
        artifact_type="build_result",
        payload={
            "node_name": "build",
            "stage": "build",
            "message": "Fake build skipped.",
            "feature_id": "feature_001",
            "execution_mode": "fake",
            "status": "skipped",
            "command": [],
            "exit_code": 0,
            "stdout_path": None,
            "stderr_path": None,
            "errors": [],
            "warnings": [],
            "duration_ms": 0,
            "error_class": "unknown",
            "diagnostics": [],
            "repair_handoff": {"allowed": False},
            "expected_artifacts": [],
            "verified_artifacts": [],
            "artifact_verification": {"status": "skipped"},
            "real_build_performed": False,
            "claims_real_build_success": False,
        },
        status="skipped",
        upstream_refs=[dry_run_ref],
    )
    eval_ref = store.write(
        feature_id="feature_001",
        artifact_type="eval_report",
        payload={
            "node_name": "evaluate",
            "stage": "evaluation",
            "message": "Evaluation gate failed.",
            "execution_mode": "fake",
            "workflow_completion_status": "fake_execution_completed",
            "requested_behavior_status": "not_verified",
            "verdict": "inconclusive",
            "claims_real_success": False,
            "checks": [],
            "input_runtime_status": "inconclusive",
            "input_acceptance_status": "inconclusive",
            "input_acceptance_verified": False,
            "acceptance_contract": {
                "acceptance_criteria": [],
                "runtime_verification_plan": [],
            },
            "evaluation_gate": {
                "gate_name": "TRANSITION-001 Eval Gate",
                "status": "failed",
                "summary": {"total": 1, "passed": 0, "failed": 1},
                "cases": [],
                "blockers": [
                    {
                        "case_id": "example_failed_gate",
                        "message": "Example failed evaluation gate.",
                    }
                ],
            },
            "v1_acceptance_status": "blocked",
            "v1_acceptance_blockers": [],
        },
        upstream_refs=[build_ref],
    )
    refs.update(
        {
            "proposal_review": review_ref,
            "dry_run_result": dry_run_ref,
            "build_result": build_ref,
            "eval_report": eval_ref,
        }
    )
    return refs


def _artifact_ref_string(ref: ArtifactRef) -> str:
    return f"{ref.feature_id}:{ref.artifact_type}:{Path(ref.path).name}:{ref.artifact_hash}"
