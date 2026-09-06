"""Execution index is a read-only observation, not a retry or success ledger."""

import ast
import hashlib
import json
from pathlib import Path

import pytest

from scripts.engineering_cognition import EngineeringCognitionError, build_projection, main
from src.mod_agent.artifacts.store import ArtifactStore
from src.mod_agent.fresh_planning_continuation import (
    _canonical_sha256,
    run_fresh_patch_continuation,
)
from src.mod_agent.local_entry import make_exact_no_write_dry_run_factory
from src.observability.patch_execution_index import project_patch_executions
from tests.unit.test_fresh_planning_continuation import (
    _feature_payload,
    _inputs,
    _local_patch_adapter,
    _patch_request,
)


def _retain(path, value):
    raw = json.dumps(value, ensure_ascii=False).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def _fixture(tmp_path, *, terminal=True):
    root = tmp_path / "store"
    response = _retain(root / "cr" / "one.response.worker-turn-001.json", {
        "content": "DO_NOT_PROJECT_SOURCE_OR_SECRET",
        "raw_response": {"api_key": "DO_NOT_PROJECT_SECRET"},
        "tool_calls": [{"call_id": "read-1", "name": "inspect_plan_binding_source",
                        "arguments": {"binding_id": "edit_binding_001"}}],
    })
    report = _retain(tmp_path / "checks" / "failed.json", {"result": "failed"})
    journal = {
        "receipt_version": "patch_continuation_attempt_v1", "feature_id": "feature_one",
        "run_id": "run_one", "status": "continuation_failed", "selected_artifacts": {},
        "events": [{"event_index": 1, "phase": "local_patch_worker_turn_requested",
                    "private_context": "DO_NOT_PROJECT"}],
        "repair_context": {"failure_report_ref": report},
        "factory_receipt": {
            "worker_turns": [{"turn_index": 1, "status": "responded",
                              "response_origin": "live_provider_response",
                              "request_sha256": "a" * 64, "response_ref": response}],
            "model_responses": [{"path": response["path"], "output_sha256": response["sha256"]}],
            "patch_agent_loop": {
                "tool_availability_trace": [{"turn_index": 1, "selection": "rejected_not_executed",
                                             "allowed_tools": ["inspect_plan_binding_source"]}],
                "tool_call_trace": [
                    {"turn_index": 1, "binding_id": "edit_binding_001", "tool_call_id": "read-1",
                     "dispatch_started": False, "status": "rejected_not_executed"},
                    {"turn_index": 2, "binding_id": "edit_binding_001", "tool_call_id": "read-1",
                     "dispatch_started": True, "status": "accepted"},
                ],
                "observation_trace": [{"turn_index": 2, "binding_id": "edit_binding_001",
                                       "observation_id": "obs-1", "admitted_to_model": True,
                                       "observation_sha256": "b" * 64}],
                "behavior_evaluations": [{"evaluation_index": 1, "status": "behavior_failed",
                                          "report_ref": report, "verification_ref": report,
                                          "verification_summary": {"checks": 36, "failed_checks": 3},
                                          "observations": [{"check_id": "FIRST_SHOT", "result_ref": report,
                                                            "observed": "DO_NOT_PROJECT_RAW"}]}],
            },
        },
    }
    if terminal:
        journal["terminal_result"] = {"terminal_stage": "generate_patch_proposal", "status": "partial"}
    path = root / "cr" / "attempt-one.json"
    _retain(path, journal)
    return root, path, journal, report


def test_failed_attempt_index_links_response_tools_verification_without_inventing_success(tmp_path):
    root, _, _, _ = _fixture(tmp_path)
    projection = project_patch_executions(root)
    assert projection["match_count"] == 1
    row = projection["attempts"][0]
    assert row["worker_turns"][0]["response_ref"]["integrity"] == "verified_bytes"
    assert row["worker_turns"][0]["requested_tools"][0]["binding_id"] == "edit_binding_001"
    assert row["tool_execution"][0]["execution_observation"] == "not_executed"
    assert row["recorded_phases"] == [{"event_index": 1, "phase": "local_patch_worker_turn_requested"}]
    assert row["worker_state"]["tool_availability"][0]["allowed_tools"] == ["inspect_plan_binding_source"]
    assert row["tool_execution"][0]["returned_observations"] == []
    assert row["tool_execution"][1]["returned_observations"][0]["admitted_to_model"] is True
    assert row["behavior_evaluations"][0]["execution_observation"] == "unknown"
    assert row["behavior_evaluations"][0]["verification_summary"] == {"checks": 36, "failed_checks": 3}
    assert row["eval_observation"]["repair_success_rate"] is None
    assert projection["task_suite_denominator"] is None
    assert "DO_NOT_PROJECT" not in json.dumps(projection)


def test_replay_and_pending_turns_do_not_become_new_sends(tmp_path):
    root, path, journal, _ = _fixture(tmp_path, terminal=False)
    turn = journal["factory_receipt"]["worker_turns"][0]
    turn["response_origin"] = "verified_prior_response"
    turn["original_response_ref"] = turn["response_ref"]
    journal["factory_receipt"]["worker_turns"].append({"turn_index": 2, "status": "requested"})
    _retain(path, journal)
    row = project_patch_executions(root)["attempts"][0]
    assert row["journal_observation"] == "terminal_result_cache_not_recorded"
    assert row["worker_turns"][0]["send_observation"] == "journal_claim_replay_with_verified_response_refs"
    assert row["worker_turns"][1]["send_observation"] == "requested_send_unconfirmed"
    assert row["worker_turns"][1]["response_ref"]["integrity"] == "unverifiable_reference"
    assert row["integrity"] == "references_need_attention"


@pytest.mark.parametrize("origin,reference,damage", [
    ("live_provider_response", "response_ref", "missing"),
    ("live_provider_response", "response_ref", "corrupt"),
    ("verified_prior_response", "response_ref", "missing"),
    ("verified_prior_response", "response_ref", "corrupt"),
    ("verified_prior_response", "original_response_ref", "missing"),
    ("verified_prior_response", "original_response_ref", "corrupt"),
])
def test_origin_claim_does_not_override_missing_or_damaged_response(tmp_path, origin, reference, damage):
    root, path, journal, _ = _fixture(tmp_path)
    turn = journal["factory_receipt"]["worker_turns"][0]
    turn["response_origin"] = origin
    response_path = Path(turn["response_ref"]["path"])
    if origin == "verified_prior_response":
        turn["original_response_ref"] = _retain(
            root / "cr" / "original.response.worker.json", json.loads(response_path.read_text()),
        )
    _retain(path, journal)
    target = Path(turn[reference]["path"])
    if damage == "missing":
        target.unlink()
    else:
        target.write_text('{"corrupt":true}')
    row = project_patch_executions(root)["attempts"][0]["worker_turns"][0]
    assert row["response_origin"] == origin
    assert row["response_origin_basis"] == "journal_declaration"
    assert row["send_observation"] == "unknown_response_evidence_unavailable"
    assert row[reference]["integrity"] == ("missing" if damage == "missing" else "hash_mismatch")
    assert row["send_observation_basis"] == "journal_claim_with_reference_checks_not_independent_send_proof"


def test_successful_current_artifact_refs_are_queried_without_parent_substitution(tmp_path):
    inputs = _inputs(tmp_path)
    request = _patch_request(inputs)
    adapter, _ = _local_patch_adapter(inputs)  # Existing deterministic unit provider, no network.
    result = run_fresh_patch_continuation(
        request, patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace),
    )
    assert result.status == "terminal"
    journal_path = Path(result.attempt_receipt["path"])
    journal = json.loads(journal_path.read_text())
    expected = {
        "patch_proposal": "patch_proposal_artifact",
        "proposal_review": "proposal_review_artifact",
        "dry_run_result": "dry_run_artifact",
    }
    row = project_patch_executions(inputs.store.root, attempt_locator=str(journal_path))["attempts"][0]
    for kind, terminal_field in expected.items():
        assert row["current_artifacts"][kind]["source_field"] == f"artifacts.{kind}"
        assert row["current_artifacts"][kind]["ref"]["integrity"] == "verified_artifact"
        observed = row["terminal_artifacts"][terminal_field]
        assert observed["source_field"] == f"terminal_result.{terminal_field}"
        assert observed["ref"]["artifact_hash"] == journal["artifacts"][kind]["artifact_hash"]
    journal["repair_context"] = {"parent_proposal": journal["artifacts"]["patch_proposal"]}
    journal["artifacts"] = {}
    for field in expected.values():
        journal["terminal_result"][field] = None
    _retain(journal_path, journal)
    failed = project_patch_executions(inputs.store.root, attempt_locator=str(journal_path))["attempts"][0]
    assert failed["current_artifacts"] == {}
    assert failed["parents"]["parent_proposal"]["integrity"] == "verified_artifact"
    assert all(value["observation"] == "recorded_null" and value["ref"] is None
               for value in failed["terminal_artifacts"].values())


def test_historical_completed_journal_without_terminal_cache_is_not_called_intermediate(tmp_path):
    root, path, journal, _ = _fixture(tmp_path, terminal=False)
    journal["status"] = "stopped_before_exact_diff_approval"
    _retain(path, journal)
    row = project_patch_executions(root)["attempts"][0]
    assert row["status"] == "stopped_before_exact_diff_approval"
    assert row["journal_observation"] == "terminal_result_cache_not_recorded"
    assert all(item["observation"] == "not_recorded" for item in row["terminal_artifacts"].values())


def test_replay_request_reference_and_wire_hash_are_distinct_from_semantic_request_hash(tmp_path):
    root, path, journal, _ = _fixture(tmp_path)
    request_ref = _retain(root / "cr" / "request.body.json", {"messages": ["secret prompt"]})
    journal["factory_receipt"]["replay_request_matches"] = [{
        "original_request_ref": request_ref, "current_wire_sha256": "c" * 64,
        "exact_wire_bytes_match": False, "all_json_values_and_text_exact": True,
    }]
    turn = journal["factory_receipt"]["worker_turns"][0]
    turn["provider_diagnostic"] = {"request_identity": {
        "provider_body_sha256": "d" * 64, "provider_body_utf8_bytes": 1234,
        "hash_basis": "httpx_json_body_bytes",
    }}
    _retain(path, journal)
    row = project_patch_executions(root)["attempts"][0]
    assert row["replay_request_observations"][0]["original_request_ref"]["integrity"] == "verified_bytes"
    assert row["replay_request_observations"][0]["exact_wire_bytes_match"] is False
    assert row["worker_turns"][0]["request_sha256"] == "a" * 64
    assert row["worker_turns"][0]["provider_request_identity"]["provider_body_utf8_bytes"] == 1234
    assert "secret prompt" not in json.dumps(row)


def test_selected_artifact_uses_store_hash_validation_not_only_recorded_hash(tmp_path):
    root, path, journal, _ = _fixture(tmp_path)
    feature = _feature_payload()
    ref = ArtifactStore(root).write(
        feature_id=feature["feature_id"], artifact_type="feature_spec", payload=feature,
    )
    journal["selected_artifacts"] = {"feature_spec": {
        "path": ref.path, "artifact_hash": ref.artifact_hash,
        "feature_id": ref.feature_id, "artifact_type": ref.artifact_type,
    }}
    _retain(path, journal)
    first = project_patch_executions(root)["attempts"][0]
    assert first["selected_upstreams"]["feature_spec"]["integrity"] == "verified_artifact"
    journal["selected_artifacts"]["wrong_feature"] = {
        **journal["selected_artifacts"]["feature_spec"], "feature_id": "different_feature",
    }
    _retain(path, journal)
    mixed = project_patch_executions(root)["attempts"][0]
    assert mixed["selected_upstreams"]["wrong_feature"]["integrity"] == "invalid_or_unreadable_reference"
    artifact_path = Path(ref.path)
    envelope = json.loads(artifact_path.read_text())
    envelope["data"]["user_request"] = "Changed without changing its claimed hash"
    artifact_path.write_text(json.dumps(envelope))
    second = project_patch_executions(root)["attempts"][0]
    assert second["selected_upstreams"]["feature_spec"]["integrity"] == "invalid_or_unreadable_reference"
    assert second["integrity"] == "references_need_attention"


@pytest.mark.parametrize("origin,invoked", [("executed", True), ("reused", False), ("incomplete", True)])
def test_explicit_verification_execution_and_reuse_stay_separate(tmp_path, origin, invoked):
    root, path, journal, report = _fixture(tmp_path)
    evaluation = journal["factory_receipt"]["patch_agent_loop"]["behavior_evaluations"][0]
    evaluation.update(
        execution_origin=origin, callback_invoked=invoked,
        verification_identity={"validator_sha256": "1" * 64, "inputs_sha256": "2" * 64,
                               "environment_sha256": "3" * 64, "deterministic_reuse_allowed": True},
        materialized_code_identity={"baseline_sha256": "4" * 64, "code_sha256": "5" * 64,
                                    "files": ["Source.cs"]},
    )
    if origin == "reused":
        evaluation["reused_from_report_ref"] = report
    _retain(path, journal)
    result = project_patch_executions(root)["attempts"][0]["behavior_evaluations"][0]
    assert result["execution_origin_recorded"] == origin
    assert result["execution_observation"] == origin
    assert result["callback_invoked"] is invoked
    assert result["materialized_code_identity"]["code_sha256"] == "5" * 64
    assert result["verification_identity"]["validator_sha256"] == "1" * 64
    Path(report["path"]).unlink()
    changed = project_patch_executions(root)["attempts"][0]["behavior_evaluations"][0]
    assert changed["execution_origin_recorded"] == origin
    assert changed["execution_observation"] == "unknown"


@pytest.mark.parametrize("change,expected", [("delete", "missing"), ("rewrite", "hash_mismatch")])
def test_reference_loss_or_drift_is_visible(tmp_path, change, expected):
    root, _, _, report = _fixture(tmp_path)
    path = Path(report["path"])
    if change == "delete":
        path.unlink()
    else:
        path.write_text('{"changed": true}')
    row = project_patch_executions(root)["attempts"][0]
    assert row["parents"]["failure_report_ref"]["integrity"] == expected
    assert row["integrity"] == "references_need_attention"


def test_exact_filters_and_attempt_locator(tmp_path):
    root, path, journal, _ = _fixture(tmp_path)
    _retain(root / "cr" / "attempt-two.json", {**journal, "feature_id": "feature_two", "run_id": "run_two"})
    assert project_patch_executions(root, feature_id="feature_one")["match_count"] == 1
    assert project_patch_executions(root, run_id="run_two")["attempts"][0]["feature_id"] == "feature_two"
    assert project_patch_executions(root, run_id="RUN_ONE")["match_count"] == 0
    assert project_patch_executions(root, attempt_locator=str(path))["match_count"] == 1
    assert project_patch_executions(root, attempt_locator="cr/attempt-one.json")["match_count"] == 1
    with pytest.raises(ValueError, match="within"):
        project_patch_executions(root, attempt_locator="../outside.json")


def test_rebuild_is_read_only_and_does_not_invoke_store_writes_or_processes(tmp_path, monkeypatch):
    root, _, _, _ = _fixture(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    def forbidden(*args, **kwargs):
        raise AssertionError("projection must not execute or write")

    monkeypatch.setattr(ArtifactStore, "write", forbidden)
    monkeypatch.setattr(ArtifactStore, "write_with_result", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("socket.socket", forbidden)
    result = build_projection("patch-execution", artifact_store_root=root)
    assert result["persistence"] == "none"
    assert result["data"]["model_calls_performed"] == 0
    assert result["data"]["verifier_executions_performed"] == 0
    assert result["data"]["langfuse_delivery"] == "not_performed"
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_cli_requires_explicit_store_and_supports_exact_query(tmp_path, capsys):
    root, _, _, _ = _fixture(tmp_path)
    assert main(["--view", "patch-execution", "--artifact-store-root", str(root), "--run-id", "run_one"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["match_count"] == 1
    with pytest.raises(EngineeringCognitionError, match="requires"):
        build_projection("patch-execution")
    with pytest.raises(EngineeringCognitionError, match="require"):
        build_projection("summary", run_id="run_one")


def test_verification_claims_subquery_and_compatibility_alias_have_same_data(tmp_path):
    root, _, _, _ = _fixture(tmp_path)
    canonical = build_projection("verification-claims", query="patch-execution", artifact_store_root=root)
    alias = build_projection("patch-execution", artifact_store_root=root)
    assert canonical["data"] == alias["data"]
    assert canonical["view"] == "verification-claims"
    assert canonical["view_family"] == alias["view_family"] == "verification-claims"
    assert canonical["subquery"] == "patch-execution"


@pytest.mark.parametrize("condition,expected", [
    ("exact", "verified"), ("changed", "hash_mismatch"),
    ("missing_hash", "unknown_missing_terminal_or_hash"),
])
def test_terminal_hash_reuses_owner_rule_without_promoting_attempt_identity(tmp_path, condition, expected):
    root, path, journal, _ = _fixture(tmp_path)
    if condition != "missing_hash":
        journal["terminal_result_sha256"] = _canonical_sha256(journal["terminal_result"])
    if condition == "changed":
        journal["terminal_result"]["status"] = "tampered"
    journal["attempt_identity_sha256"] = "1" * 64
    _retain(path, journal)
    row = project_patch_executions(root)["attempts"][0]
    assert row["journal_identity_checks"]["terminal_result_hash"]["status"] == expected
    assert row["journal_identity_checks"]["attempt_identity"]["status"] == "unverifiable"
    assert "run_verified" not in row
    assert row["integrity"] == "checked_references_match"  # This is reference scope only.


def test_reading_real_artifact_does_not_recover_pending_writes_or_update_alias(tmp_path, monkeypatch):
    root, path, journal, _ = _fixture(tmp_path)
    store = ArtifactStore(root)
    payload = _feature_payload()
    ref = store.write(feature_id=payload["feature_id"], artifact_type="feature_spec", payload=payload)
    journal["selected_artifacts"] = {"feature_spec": {
        "path": ref.path, "artifact_hash": ref.artifact_hash,
        "feature_id": ref.feature_id, "artifact_type": ref.artifact_type,
    }}
    _retain(path, journal)
    pending = root / "features" / ref.feature_id / "p" / "unprocessed.json"
    _retain(pending, {"status": "pending_latest_replace"})
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}

    def forbidden(*args, **kwargs):
        raise AssertionError("query must not recover, maintain, or write the ArtifactStore")

    for method in ("recover_pending_writes", "_recover_pending_write", "_write_text_atomic",
                   "_write_text_exclusive_atomic", "_execute_write", "write", "write_with_result"):
        monkeypatch.setattr(ArtifactStore, method, forbidden)
    result = project_patch_executions(root)
    assert result["attempts"][0]["selected_upstreams"]["feature_spec"]["integrity"] == "verified_artifact"
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_product_execution_modules_do_not_import_query_projection():
    product_root = Path(__file__).resolve().parents[2] / "src" / "mod_agent"
    for path in product_root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            names = [node.module] if isinstance(node, ast.ImportFrom) else (
                [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
            )
            assert not any(name and "patch_execution_index" in name for name in names), path


def test_code_response_and_materialized_identity_require_explicit_report_links(tmp_path):
    root, path, journal, old_report = _fixture(tmp_path)
    factory = journal["factory_receipt"]
    evaluation = factory["patch_agent_loop"]["behavior_evaluations"][0]
    code_identity = {"baseline_sha256": "0" * 64, "code_sha256": "1" * 64, "files": ["Source.cs"]}
    evaluation.update(materialized_code_identity=code_identity, generated_changes_sha256="2" * 64,
                      model_response_sha256=factory["model_responses"][0]["output_sha256"])
    report = _retain(Path(old_report["path"]), {
        "materialized_code_identity": code_identity, "generated_changes_sha256": "2" * 64,
    })
    evaluation["report_ref"] = report
    _retain(path, journal)
    row = project_patch_executions(root)["attempts"][0]
    observed = row["behavior_evaluations"][0]
    assert observed["materialized_code_report_link"] == "matching_explicit_identity"
    assert observed["generated_changes_report_link"] == "matching_explicit_identity"
    assert observed["code_response_refs"][0]["integrity"] == "verified_bytes"
    assert row["worker_turns"][0]["observation_delivery"] == "unknown_no_explicit_request_reference"
    evaluation["materialized_code_identity"] = {**code_identity, "code_sha256": "3" * 64}
    _retain(path, journal)
    drifted = project_patch_executions(root)["attempts"][0]["behavior_evaluations"][0]
    assert drifted["materialized_code_report_link"] == "identity_mismatch"


def test_code_revision_preserves_owner_declaration_and_separate_report_integrity(tmp_path):
    root, path, journal, report = _fixture(tmp_path)
    old = project_patch_executions(root)["attempts"][0]["behavior_evaluations"][0]["code_revision"]
    assert old["declaration_status"] == "unknown"
    assert old["known_failed_report_ref"] is None
    evaluation = journal["factory_receipt"]["patch_agent_loop"]["behavior_evaluations"][0]
    evaluation["code_revision"] = {
        "comparison_basis": "same_B0_materializer_whole_file_bytes",
        "comparable_to_known_failed": True, "same_materialized_code": True,
        "known_failed_report_ref": report, "different_code_is_not_proof_of_repair": True,
    }
    _retain(path, journal)
    observed = project_patch_executions(root)["attempts"][0]["behavior_evaluations"][0]["code_revision"]
    assert observed["declaration_status"] == "recorded"
    assert observed["comparison_basis"] == "same_B0_materializer_whole_file_bytes"
    assert observed["comparable_to_known_failed"] is True
    assert observed["same_materialized_code"] is True
    assert observed["comparison_verification"] == "journal_declaration_not_recomputed"
    assert observed["known_failed_report_ref"]["integrity"] == "verified_bytes"
    assert observed["claim_scope"] == "code_comparison_not_repair_success"
    Path(report["path"]).write_text('{"changed":true}')
    damaged = project_patch_executions(root)["attempts"][0]["behavior_evaluations"][0]["code_revision"]
    assert damaged["declaration_status"] == "recorded"
    assert damaged["known_failed_report_ref"]["integrity"] == "hash_mismatch"


def test_missing_journal_is_reported_and_network_paths_are_not_read(tmp_path):
    root = tmp_path / "store"
    result = project_patch_executions(root, attempt_locator="cr/absent.json")
    assert result["unreadable_journals"][0]["status"] == "missing_or_invalid_journal"
    with pytest.raises(ValueError, match="network_path"):
        project_patch_executions("//untrusted/share")
