"""Index real retained worker paths with offline HTTP, never external models."""
import hashlib
import json
from pathlib import Path

from src.mod_agent.model_qualification import canonical_hash
from src.observability.patch_execution_index import project_patch_executions
from tests.unit.test_external_patch import _consent, _run
from tests.unit.test_patch_submission_cli import _case, _install, _profile_json


def _prepared(tmp_path, monkeypatch):
    case = _case(tmp_path)
    profile = _profile_json()
    _install(monkeypatch, ["read", "failed", "read", "passed"])
    result = _run(case, profile, _consent(profile))
    assert result.status == "terminal", result.to_dict()
    path = Path(result.attempt_receipt["path"])
    return case, path, json.loads(path.read_text(encoding="utf-8"))


def _query(case, path):
    return project_patch_executions(case.inputs.store.root, attempt_locator=str(path))["attempts"][0]


def _rewrite_request(journal, journal_path, selected_turn, transform):
    turn = journal["factory_receipt"]["worker_turns"][selected_turn]
    path = Path(turn["request_ref"]["path"])
    document = json.loads(path.read_text(encoding="utf-8"))
    transform(document)
    raw = json.dumps(document, ensure_ascii=False).encode()
    path.write_bytes(raw)
    turn["request_ref"]["sha256"] = hashlib.sha256(raw).hexdigest()
    turn["request_sha256"] = canonical_hash(document)
    journal_path.write_text(json.dumps(journal, ensure_ascii=False), encoding="utf-8")


def test_public_worker_failure_and_tool_observations_are_matched_to_actual_retained_requests(tmp_path, monkeypatch):
    case, path, _ = _prepared(tmp_path, monkeypatch)
    row = _query(case, path)
    summary = row["failure_summary"]
    assert summary["stopped_at"]["proposal_admitted"] is True
    requests = summary["request_evidence"]
    assert all(item["normalized_request_identity"] == "matched" for item in requests)
    tools = [link for item in requests for link in item["tool_observation_links"]]
    feedback = [link for item in requests for link in item["failure_feedback_links"]
                if link["message_type"] == "patch_behavior_correction"]
    assert tools and all(link["binding_status"] == "matched" for link in tools)
    assert feedback and all(link["binding_status"] == "matched" for link in feedback)
    assert all(item["response_after_request_observed"] for item in requests)
    assert all(summary["formal_downstream"][name]["recorded_count"] == 0 for name in ("apply", "build", "runtime"))
    assert "RecordMissingMarker" not in json.dumps(summary)
    assert "RecordRuntimeMarker" not in json.dumps(summary)


def test_changed_request_file_is_unknown_without_fabricating_delivery(tmp_path, monkeypatch):
    case, path, journal = _prepared(tmp_path, monkeypatch)
    Path(journal["factory_receipt"]["worker_turns"][-1]["request_ref"]["path"]).write_text("{}")
    item = _query(case, path)["failure_summary"]["request_evidence"][-1]
    assert item["request_ref"]["integrity"] == "hash_mismatch"
    assert item["normalized_request_identity"] == "unknown_no_verified_request"
    assert item["tool_observation_links"] == item["failure_feedback_links"] == []


def test_wrong_feedback_report_hash_does_not_match_just_because_core_fields_exist(tmp_path, monkeypatch):
    case, path, journal = _prepared(tmp_path, monkeypatch)
    def change(document):
        message = next(row for row in document["messages"] if isinstance(row.get("content"), dict)
                       and row["content"].get("message_type") == "patch_behavior_correction")
        message["content"]["validator_feedback"]["report_sha256"] = "0" * 64
    _rewrite_request(journal, path, -1, change)
    item = _query(case, path)["failure_summary"]["request_evidence"][-1]
    assert item["normalized_request_identity"] == "matched"
    link = next(value for value in item["failure_feedback_links"] if value["message_type"] == "patch_behavior_correction")
    assert link["binding_status"] == "unmatched_report_hash"


def test_tool_content_change_is_detected_even_with_a_valid_request_file_hash(tmp_path, monkeypatch):
    case, path, journal = _prepared(tmp_path, monkeypatch)
    def change(document):
        document["tool_results"][0]["output"]["excerpt"] += "\nDO_NOT_PROJECT_TOOL_CODE"
    _rewrite_request(journal, path, 1, change)
    item = _query(case, path)["failure_summary"]["request_evidence"][1]
    assert item["normalized_request_identity"] == "matched"
    assert item["tool_observation_links"][0]["binding_status"] == "mismatch"
    assert "DO_NOT_PROJECT_TOOL_CODE" not in json.dumps(item)


def test_legacy_without_native_trace_does_not_invent_transport_count(tmp_path, monkeypatch):
    case, path, journal = _prepared(tmp_path, monkeypatch)
    journal.pop("execution_observations", None)
    path.write_text(json.dumps(journal), encoding="utf-8")
    summary = _query(case, path)["failure_summary"]
    assert summary["model_requests"]["transport_started_observation_count"] is None
    assert summary["model_requests"]["journal_call_count"] == 4
    assert summary["model_requests"]["transport_count_basis"] == "unknown_no_native_execution_history"
