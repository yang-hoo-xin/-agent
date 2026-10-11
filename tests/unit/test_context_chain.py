"""Counterexamples for the read-only context chain, with no network or model."""
from __future__ import annotations

import hashlib
import json
import socket

import pytest

from scripts.product_trace import main
from src.mod_agent.evaluation.context_chain import inspect_context_chain
from tests.unit.test_product_trace_drilldown import _call, _write, run_records


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("Context report must be offline"))


def _inspect(root, continuation=None):
    return inspect_context_chain(allowed_root=root.parent.parent, run_root=root,
                                 run_id=root.name, continuation_root=continuation,
                                 include_local_raw=True)


def _read(root, filename):
    return json.loads((root / filename).read_text())


def _result(root, **changes):
    result = _read(root, "run_result.json")
    result.update(changes)
    ref = _write(root / "run_result.json", result)
    manifest = _read(root, "run_manifest.json")
    manifest["terminal_record"] = ref
    _write(root / "run_manifest.json", manifest)


def test_http_completion_and_contract_rejection_are_not_semantic_success(tmp_path):
    _, root, continuation = run_records(tmp_path)
    report = _inspect(root, continuation)
    row = next(r for r in report["segments"][1]["records"] if r["kind"] == "model")
    assert row["result"]["transport"]["http_status"] == 200
    assert row["judgment"]["contract_checks"][0]["recorded_attempts"][0]["status"] == "failed"
    assert row["judgment"]["semantic_correctness"]["status"] == "unknown"
    assert report["quality_assessment"]["task_or_cost_improvement"]["status"] == "unknown"


def test_accepted_contract_is_not_independent_correctness(tmp_path):
    _, root, continuation = run_records(tmp_path)
    manifest = _read(continuation, "run_manifest.json")
    manifest["execution_observations"]["coverage"]["attributes"]["requirement_findings_attempt_audit"] = [
        {"attempt_index": 1, "status": "accepted"}]
    _write(continuation / "run_manifest.json", manifest)
    row = next(r for r in _inspect(root, continuation)["segments"][1]["records"] if r["kind"] == "model")
    assert row["judgment"]["contract_checks"][0]["recorded_attempts"][0]["status"] == "accepted"
    assert row["judgment"]["semantic_correctness"]["status"] == "unknown"


def test_patch_generation_without_model_role_is_not_lost(tmp_path):
    _, root, _ = run_records(tmp_path)
    manifest = _read(root, "run_manifest.json")
    for row in manifest["execution_observations"].values():
        row["attributes"].pop("model_role")
        if row["kind"] == "generation":
            row["name"] = "patch.generate"
    _write(root / "run_manifest.json", manifest)
    report = _inspect(root)
    assert report["segments"][0]["stages"]["patch"]["status"] == "observed"
    row = next(r for r in report["segments"][0]["records"] if r["kind"] == "model")
    assert row["role"] == "unknown" and row["stage"] == "patch"


def test_missing_usage_and_absent_stages_remain_unknown(tmp_path):
    _, root, _ = run_records(tmp_path)
    manifest = _read(root, "run_manifest.json")
    for row in manifest["execution_observations"].values():
        row["attributes"]["usage"] = {"input_tokens": 8}
    _write(root / "run_manifest.json", manifest)
    result = _inspect(root)["segments"][0]
    assert result["cost"]["output_tokens"]["total"] is None
    assert result["cost"]["output_tokens"]["observed_calls"] == 0
    assert result["stages"]["planning"]["status"] == "unknown"
    assert result["terminal"]["runtime_summary"] is None


def test_material_link_requires_exact_identity_and_preceding_observation(tmp_path):
    _, root, _ = run_records(tmp_path)
    manifest = _read(root, "run_manifest.json")
    observations = manifest["execution_observations"]
    request = {"messages": [{"role": "user", "content": json.dumps({
        "source_observations": [{"evidence_id": "fact-one", "excerpt": "CURRENT SOURCE"}]})}]}
    request_ref = _write(root / "model_trace_bodies" / "old.request.json", request)
    digest = hashlib.sha256(b"CURRENT SOURCE").hexdigest()
    for row in observations.values():
        row["attributes"]["local_detail_refs"]["request"] = request_ref
    for identity, evidence, finished in (("before", "fact-one", "2026-09-20T07:59:00+08:00"),
                                        ("after", "fact-one", "2026-09-20T00:01:00+00:00"),
                                        ("different-id", "fact-two", "2026-09-19T23:59:00+00:00")):
        observations[identity] = {"id": identity, "trace_id": "1" * 32, "name": "evidence.source_query",
            "kind": "tool", "started_at": finished, "finished_at": finished, "status": "completed",
            "attributes": {"produced_materials": [{"evidence_id": evidence,
                "excerpt_sha256": digest, "source_hash": "a" * 64}]}}
    _write(root / "run_manifest.json", manifest)
    row = next(r for r in _inspect(root)["segments"][0]["records"] if r["kind"] == "model")
    material = row["input"]["payloads"][0]["materials"][0]
    assert material["source_hash"] is None  # Do not fill a missing input field from another record.
    assert [r["observation_id"] for r in material["producer_matches"]] == ["before"]
    assert material["model_utilization"] == "unknown"


@pytest.mark.parametrize("damage", ["body", "terminal"])
def test_changed_bytes_cannot_retain_a_verified_result(tmp_path, damage):
    _, root, _ = run_records(tmp_path)
    path = root / ("model_trace_bodies/old.response.txt" if damage == "body" else "run_result.json")
    path.write_text("{}")
    with pytest.raises(ValueError):
        _inspect(root)


def test_baseline_build_does_not_mask_failure_or_become_task_build(tmp_path):
    _, root, continuation = run_records(tmp_path)
    _result(root, blockers=[{"code": "FIRST_CAUSE", "source_node": "retrieve_evidence"}],
            build_summary={"status": "not_reached"}, patch_payload_parser_entered=False)
    manifest = _read(root, "run_manifest.json")
    manifest["execution_observations"]["baseline"] = {"id": "baseline", "trace_id": "1" * 32,
        "name": "baseline_build", "kind": "span", "status": "completed", "attributes": {}}
    _write(root / "run_manifest.json", manifest)
    result = _read(continuation, "run_result.json")
    result["blockers"] = [{"code": "LATER_STOP"}]
    _write(continuation / "run_result.json", result)
    report = _inspect(root, continuation)
    assert report["segments"][0]["terminal"]["blockers"][0]["code"] == "FIRST_CAUSE"
    assert report["segments"][1]["terminal"]["blockers"][0]["code"] == "LATER_STOP"
    assert report["segments"][0]["terminal"]["build_summary"]["status"] == "not_reached"


def test_request_without_transport_is_not_counted_as_model_generation(tmp_path):
    _, root, _ = run_records(tmp_path)
    manifest = _read(root, "run_manifest.json")
    observations = _call(root, "1" * 32, "prepared", "requirement_findings", "2026-09-20T00:00:01+00:00")
    del observations["gen-prepared"]
    observations["req-prepared"]["attributes"]["transport_started"] = False
    observations["req-prepared"]["attributes"]["response_received"] = False
    manifest["execution_observations"] = observations
    _write(root / "run_manifest.json", manifest)
    segment = _inspect(root)["segments"][0]
    assert segment["cost"]["generation_records"] == 0
    row = segment["records"][0]
    assert row["kind"] == "request_without_generation"
    assert row["result"]["recorded_decision"]["transport_started"] is False
    assert segment["stages"]["findings"]["status"] == "unknown"


def test_zero_reservations_do_not_prove_no_transport(tmp_path):
    _, root, _ = run_records(tmp_path)
    _result(root, model_call_budget={"by_stage": {"requirement_findings": {"consumed": 0}}})
    manifest = _read(root, "run_manifest.json")
    del manifest["execution_observations"]["gen-old"]
    _write(root / "run_manifest.json", manifest)
    segment = _inspect(root)["segments"][0]
    assert segment["stages"]["findings"]["status"] == "unknown"
    assert segment["stages"]["findings"]["recorded_budget_consumed"] == 0
    assert segment["stages"]["findings"]["request_records_without_generation"] == ["req-old"]
    assert segment["cost"]["input_tokens"]["total"] is None
    assert segment["cost"]["unaccounted_request_possible"] is True


def test_query_result_join_uses_hash_owner_and_time_not_proximity(tmp_path):
    _, root, _ = run_records(tmp_path)
    manifest = _read(root, "run_manifest.json")
    observations = manifest["execution_observations"]
    response_ref = _write(root / "model_trace_bodies/old.response.txt", {"queries": [{"query": "current input"}]})
    for row in observations.values():
        row["attributes"]["model_role"] = "initial_findings_queries"
        row["attributes"]["local_detail_refs"]["response"] = response_ref
    digest = hashlib.sha256(b"current input").hexdigest()
    for identity, owner, started, query_hash in (
            ("right", "coverage", "2026-09-21T00:00:03+00:00", digest),
            ("before", "coverage", "2026-09-19T00:00:00+00:00", digest),
            ("elsewhere", "other-span", "2026-09-21T00:00:03+00:00", digest),
            ("different", "coverage", "2026-09-21T00:00:03+00:00", "b" * 64)):
        observations[identity] = {"id": identity, "trace_id": "1" * 32, "parent_id": owner,
            "name": "evidence.source_query", "kind": "tool", "started_at": started, "finished_at": started,
            "attributes": {"query_sha256": query_hash, "evidence_item_count": 1}}
    _write(root / "run_manifest.json", manifest)
    row = next(r for r in _inspect(root)["segments"][0]["records"] if r["kind"] == "model")
    matches = row["result"]["query_execution_links"][0]["observations"]
    assert [r["observation_id"] for r in matches] == ["right"]


def test_cli_is_offline_requires_opt_in_and_will_not_overwrite(tmp_path):
    allowed, root, _ = run_records(tmp_path)
    args = ["--allowed-root", str(allowed), "--run-root", str(root), "--run-id", root.name, "--context-chain"]
    with pytest.raises(SystemExit):
        main(args)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    output = tmp_path / "report.md"
    assert main([*args, "--include-local-raw", "--format", "markdown", "--output", str(output)]) == 0
    assert "unknown" in output.read_text(encoding="utf-8")
    assert main([*args, "--include-local-raw", "--output", str(output)]) == 2
    assert all(p.read_bytes() == raw for p, raw in before.items())


def test_terminal_projects_outcome_without_duplicating_all_artifacts(tmp_path):
    _, root, _ = run_records(tmp_path)
    _result(root, product_execution_result={"execution_disposition": "partial", "failure_stage": "evidence",
            "outputs": {"large": "payload"}, "variant_result": {"nested": "execution state"}})
    report = _inspect(root)
    product = report["segments"][0]["terminal"]["product_execution_result"]
    assert product["execution_disposition"] == "partial" and product["failure_stage"] == "evidence"
    assert "variant_result" not in product and "outputs" not in product
    assert _read(root, "run_result.json")["product_execution_result"]["outputs"] == {"large": "payload"}


@pytest.mark.parametrize("parent_state", ["valid", "missing", "wrong_hash", "unselected"])
def test_recovery_materials_only_join_verified_selected_parent(tmp_path, parent_state):
    _, root, continuation = run_records(tmp_path)
    content = "original material"
    digest = hashlib.sha256(content.encode()).hexdigest()
    original = _read(root, "run_manifest.json")
    original["execution_observations"]["producer"] = {
        "id": "producer", "trace_id": "1" * 32, "name": "evidence.source_query", "kind": "tool",
        "started_at": "2026-09-19T00:00:00+00:00", "finished_at": "2026-09-19T00:00:01+00:00",
        "attributes": {"produced_materials": [
            {"evidence_id": "same-id", "excerpt_sha256": digest, "source_hash": "a" * 64},
            {"evidence_id": "unrelated-id", "excerpt_sha256": digest, "source_hash": "b" * 64}]}}
    _write(root / "run_manifest.json", original)
    current = _read(continuation, "run_manifest.json")
    ref = _write(continuation / "model_trace_bodies/new.request.json", {"messages": [{
        "role": "user", "content": json.dumps({"source_observations": [{"evidence_id": "same-id", "excerpt": content}]})}]})
    for row in current["execution_observations"].values():
        if row["name"] == "model.request" or row["kind"] == "generation":
            row["attributes"]["local_detail_refs"]["request"] = ref
    if parent_state != "missing":
        current["parent_result_ref"] = dict(original["terminal_record"])
        if parent_state == "wrong_hash":
            current["parent_result_ref"]["sha256"] = "0" * 64
        if parent_state == "unselected":
            current["parent_result_ref"]["path"] = str(root / "continuations/not-selected/run_result.json")
    _write(continuation / "run_manifest.json", current)
    if parent_state == "wrong_hash":
        with pytest.raises(ValueError, match="parent"):
            _inspect(root, continuation)
        return
    segment = _inspect(root, continuation)["segments"][1]
    row = next(r for r in segment["records"] if r["kind"] == "model")
    matches = row["input"]["payloads"][0]["materials"][0]["producer_matches"]
    if parent_state == "valid":
        assert [(m["segment"], m["observation_id"]) for m in matches] == [("original", "producer")]
        assert matches[0]["origin"] == "selected_parent"
        assert segment["parent_link"]["status"] == "verified_selected_parent"
    else:
        assert matches == []
        assert segment["parent_link"]["status"] == "unknown"


@pytest.mark.parametrize("schema_case", ["equal", "different", "missing", "tampered"])
def test_schema_comparison_is_separate_from_messages(tmp_path, schema_case):
    _, root, _ = run_records(tmp_path)
    manifest = _read(root, "run_manifest.json")
    observations = _call(root, "1" * 32, "native", "requirement_findings",
                         "2026-09-20T00:00:01+00:00", native_provider=True)
    request_path = root / "model_trace_bodies/native.request.json"
    native_path = root / "model_trace_bodies/native.provider-request.json"
    request = json.loads(request_path.read_text())
    native = json.loads(native_path.read_text())
    native["messages"] = request["messages"]
    if schema_case in {"different", "tampered"}:
        native["format"] = {"type": "number"}
    if schema_case == "missing":
        del request["response_format"]
        del native["format"]
    req_ref, native_ref = _write(request_path, request), _write(native_path, native)
    for row in observations.values():
        row["attributes"]["local_detail_refs"]["request"] = req_ref
        row["attributes"]["local_detail_refs"]["provider_request"] = native_ref
    manifest["execution_observations"] = observations
    _write(root / "run_manifest.json", manifest)
    if schema_case == "tampered":
        native_path.write_text("{}")
        with pytest.raises(ValueError):
            _inspect(root)
        return
    row = next(r for r in _inspect(root)["segments"][0]["records"] if r["kind"] == "model")
    assert row["input"]["native_messages_comparison"]["equal"] is True
    comparison = row["input"]["native_schema_comparison"]
    if schema_case == "missing":
        assert comparison["status"] == "unknown" and "equal" not in comparison
    else:
        assert comparison["equal"] is (schema_case == "equal")
    assert row["judgment"]["semantic_correctness"]["status"] == "unknown"


def test_each_planning_gate_retains_its_own_receipt(tmp_path):
    _, root, continuation = run_records(tmp_path)
    manifest = _read(continuation, "run_manifest.json")
    for identifier, turns, status in (("gate-1", 0, "blocked"), ("gate-2", 1, "selected")):
        receipt = _write(continuation / f"{identifier}.json", {"status": status,
            "model_turns_attempted": turns, "model_responses_received": turns,
            "failure": {"code": "NEEDS_EVIDENCE"} if turns == 0 else None})
        manifest["execution_observations"][identifier] = {"id": identifier, "trace_id": "2" * 32,
            "name": "planning.decision", "kind": "span", "status": "completed",
            "started_at": "2026-09-21T01:00:00+00:00", "attributes": {
                "decision_status": status, "local_detail_refs": {"planning_receipt": receipt}}}
    _write(continuation / "run_manifest.json", manifest)
    segment = _inspect(root, continuation)["segments"][1]
    gates = [r for r in segment["records"] if r["name"] == "planning.decision"]
    assert len(gates) == 2
    assert [g["result"]["recorded_decision"]["selection"]["model_turns_attempted"] for g in gates] == [0, 1]
    assert gates[0]["result"]["recorded_decision"]["selection"]["status"] == "blocked"
    assert segment["stages"]["planning"]["decision_record_ids"] == ["gate-1", "gate-2"]
    assert segment["stages"]["planning"]["model_invocation_status"] == "unknown"
    assert segment["stages"]["planning"]["status"] == "decision_observed"
    assert all(g["judgment"]["semantic_correctness"]["status"] == "unknown" for g in gates)


@pytest.mark.parametrize("field", ["schema", "messages"])
def test_native_comparison_distinguishes_json_booleans_and_numbers(tmp_path, field):
    _, root, _ = run_records(tmp_path)
    manifest = _read(root, "run_manifest.json")
    observations = _call(root, "1" * 32, "typed", "requirement_findings",
                         "2026-09-20T00:00:01+00:00", native_provider=True)
    request_path = root / "model_trace_bodies/typed.request.json"
    native_path = root / "model_trace_bodies/typed.provider-request.json"
    request, native = json.loads(request_path.read_text()), json.loads(native_path.read_text())
    if field == "schema":
        request["response_format"], native["format"] = {"enum": [True]}, {"enum": [1]}
    else:
        request["messages"] = [{"role": "user", "content": {"flag": True}}]
        native["messages"] = [{"role": "user", "content": {"flag": 1}}]
    req_ref, native_ref = _write(request_path, request), _write(native_path, native)
    for row in observations.values():
        row["attributes"]["local_detail_refs"].update(request=req_ref, provider_request=native_ref)
    manifest["execution_observations"] = observations
    _write(root / "run_manifest.json", manifest)
    row = next(r for r in _inspect(root)["segments"][0]["records"] if r["kind"] == "model")
    assert row["input"][f"native_{field}_comparison"]["equal"] is False


def test_boolean_planning_counters_are_not_measured_zero(tmp_path):
    _, root, continuation = run_records(tmp_path)
    manifest = _read(continuation, "run_manifest.json")
    receipt = _write(continuation / "planning.json", {"status": "blocked",
        "model_turns_attempted": False, "model_responses_received": False})
    manifest["execution_observations"]["planning"] = {"id": "planning", "trace_id": "2" * 32,
        "name": "planning.decision", "kind": "span", "status": "failed", "attributes": {
            "decision_status": "blocked", "local_detail_refs": {"planning_receipt": receipt}}}
    _write(continuation / "run_manifest.json", manifest)
    stage = _inspect(root, continuation)["segments"][1]["stages"]["planning"]
    assert stage["status"] == "decision_observed" and stage["model_invocation_status"] == "unknown"
