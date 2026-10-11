"""Accounting counterexamples; synthetic records are not benchmark outcomes."""
import json

import pytest

from scripts.summarize_context_online_ab import (
    discover_records,
    distribution,
    infer_current_trial_cost_coverage,
    main,
    measure_trace,
    native_cache_measurement,
    phase_timings,
    preserve_source_version,
    query_sets,
    reference,
    summarize,
)
from tests.unit.test_task_measurement import _segment, _write


def order():
    return {"order": [{"task_id": str(task), "arm": arm, "repeat": repeat}
                      for task in range(5) for arm in ("baseline", "candidate") for repeat in (1, 2)]}


def records(tmp_path, outcomes):
    rows = []
    for index, (trial, success) in enumerate(zip(order()["order"], outcomes)):
        path = tmp_path / f"{index}.json"
        path.write_text(json.dumps({**trial, "success": success, "status": "completed" if success else "failed",
                                    "elapsed_seconds": index + 1, "agent_process": {"started": True}}), encoding="utf-8")
        rows.append({**trial, "result_ref": reference(path)})
    return {"runs": rows}


def test_unexecuted_are_kept_and_rates_unknown():
    result = summarize(order(), {"runs": []})
    assert len(result["runs"]) == 20
    assert result["blind_holdout_tasks"] == 0
    for arm in result["by_arm"].values():
        assert arm["unknown_outcomes"] == 10
        assert arm["completion_fraction"] is None
        assert arm["observed_pass_at_2"] is None
        assert arm["cost_all_runs_including_failures"]["input_tokens"]["total"] is None


def test_repeated_success_denominators_and_failed_cost_remain(tmp_path):
    result = summarize(order(), records(tmp_path, [True, False, True, True] * 5))
    base, candidate = (result["by_arm"][arm] for arm in ("baseline", "candidate"))
    assert base["success_runs"] == 5
    assert base["observed_pass_at_2"] == 1
    assert base["observed_pass_power_2"] == 0
    assert candidate["success_runs"] == 10
    assert candidate["observed_pass_power_2"] == 1
    assert base["elapsed_seconds_all_runs"]["n"] == 10
    assert result["paired_success_seconds"]["n"] == 5
    assert all(row["repeat"] == 1 for row in result["paired_success_seconds"]["pairs"])


def test_partial_repeat_does_not_claim_complete_pass_at_2(tmp_path):
    result = summarize(order(), records(tmp_path, [True]))
    assert result["by_arm"]["baseline"]["task_at_least_once"] == 1
    assert result["by_arm"]["baseline"]["observed_pass_at_2"] is None


def test_hash_drift_keeps_invalid_row(tmp_path):
    selected = records(tmp_path, [True])
    (tmp_path / "0.json").write_text("{}", encoding="utf-8")
    result = summarize(order(), selected)
    assert result["runs"][0]["status"] == "invalid_measurement"
    assert result["runs"][0]["success"] is None
    assert len(result["runs"]) == 20


def test_duplicate_or_missing_registration_rejected(tmp_path):
    selected = records(tmp_path, [True])
    selected["runs"] *= 2
    with pytest.raises(ValueError, match="Duplicate"):
        summarize(order(), selected)
    broken = order()
    broken["order"].pop()
    with pytest.raises(ValueError, match="exactly"):
        summarize(broken, {"runs": []})


def test_percentiles_are_nearest_rank_with_missing_not_zero():
    assert distribution([1, 5, 3, 2, None]) == {
        "n": 4, "missing": 1, "p50": 2, "p95": 5,
        "algorithm": "nearest_rank: sorted[ceil(p*n)-1]; observed values only"}


def test_routing_is_known_subtotal_not_complete_tokens(tmp_path):
    selected = records(tmp_path, [True])
    route = tmp_path / "route.json"
    route.write_text(json.dumps({"routing_usage": {"input_tokens": 7, "output_tokens": 3}}), encoding="utf-8")
    path = tmp_path / "0.json"
    body = json.loads(path.read_text())
    body["routing_result_ref"] = reference(route)
    path.write_text(json.dumps(body), encoding="utf-8")
    selected["runs"][0]["result_ref"] = reference(path)
    metrics = summarize(order(), selected)["runs"][0]["metrics"]
    assert metrics["known_input_tokens_subtotal"] == 7
    assert metrics["input_tokens"] is None
    assert metrics["cache_tokens"] is None


def test_explicit_metric_source_is_bound_and_preserved(tmp_path):
    selected = records(tmp_path, [False])
    evidence = tmp_path / "reuse.json"
    evidence.write_text(json.dumps({"query_observation_reuse": {"collect_calls": 12, "reused_lanes": 29}}))
    selected["runs"][0]["metric_sources"] = {"rg_collect": {
        "ref": reference(evidence), "pointer": "/query_observation_reuse/collect_calls"}}
    row = summarize(order(), selected)["runs"][0]
    assert row["additional_metrics"]["rg_collect"]["value"] == 12
    assert row["success"] is False


def test_reuse_receipts_do_not_double_count(tmp_path):
    path = tmp_path / "pack.json"
    path.write_text(json.dumps({"budget_summary": {"query_count": 41, "query_observation_reuse": {
        "collect_calls": 12, "reused_lanes": 29}}}))
    source = {"ref": reference(path), "pointer": "/budget_summary"}
    measured = query_sets([source])
    assert measured["actual_collect_calls"]["total"] == 12
    assert measured["reused_lanes"]["total"] == 29
    with pytest.raises(ValueError, match="Duplicate"):
        query_sets([source, source])


def test_bound_process_log_drift_invalidates_measurement(tmp_path):
    selected = records(tmp_path, [False])
    log = tmp_path / "out.bin"
    log.write_bytes(b"failure details")
    path = tmp_path / "0.json"
    body = json.loads(path.read_text())
    body["agent_process"] = {"stdout_ref": reference(log)}
    path.write_text(json.dumps(body))
    selected["runs"][0]["result_ref"] = reference(path)
    log.write_bytes(b"rewritten")
    result = summarize(order(), selected)
    assert result["runs"][0]["status"] == "invalid_measurement"


@pytest.mark.parametrize("product_total,expected", [(10, 17), (None, None)])
def test_whole_run_tokens_need_native_completeness_even_with_coverage(tmp_path, monkeypatch, product_total, expected):
    selected = records(tmp_path, [False])
    route = tmp_path / "route.json"
    route.write_text(json.dumps({"routing_usage": {"input_tokens": 7, "output_tokens": 3}}))
    monkeypatch.setattr("scripts.summarize_context_online_ab.measure_trace", lambda selection: {
        "native_usage": {"input_tokens": {"total": product_total, "known_subtotal": 10},
                         "output_tokens": {"total": 2, "known_subtotal": 2}},
        "rg_actual_executions": 3})
    path = tmp_path / "0.json"
    body = json.loads(path.read_text())
    body.update(routing_result_ref=reference(route), product_run={"test": True}, cost_coverage={
        "routing_complete": True, "product_complete": True, "delivery_model_calls": 0, "other_model_calls": 0})
    path.write_text(json.dumps(body))
    selected["runs"][0]["result_ref"] = reference(path)
    metrics = summarize(order(), selected)["runs"][0]["metrics"]
    assert metrics["input_tokens"] == expected
    assert metrics["output_tokens"] == 5
    assert metrics["known_input_tokens_subtotal"] == 17
    assert metrics["cache_tokens"] is None


def _coverage_fixture(tmp_path):
    workspace = tmp_path / "runs"
    root = workspace / "run-one"
    _segment(root)
    records = tmp_path / "records"
    route_root = workspace / ".dsh-routing/route-one"
    route_root.mkdir(parents=True)
    body_refs = {role: _write(route_root / f"{role}.json", {"body": role}) for role in ("request", "response")}
    usage = {"input_tokens": 7, "output_tokens": 3}
    attrs = {"transport_started": True, "response_complete": True, "usage": usage, "local_detail_refs": body_refs}
    _write(route_root / "trace.json", {"observations": [
        {"id": "req", "name": "model.request", "kind": "span", "status": "completed", "attributes": attrs},
        {"id": "gen", "parent_id": "req", "kind": "generation", "status": "completed", "attributes": attrs}]})
    natural = {"routing_record_path": str(route_root / "result.json"), "turn_id": "initial",
               "decision": {"action": "modify_project"}, "product_result": {"run_id": root.name},
               "budget": {"routing_model_call_limit": 1}, "routing_transport_calls": 1, "routing_usage": usage}
    _write(route_root / "result.json", natural)
    _write(records / "product-process.json", {"exit_code": 2, "stdout": json.dumps({"run_id": root.name})})
    process = {"started": True, "status": "exited", "timeout": False, "exit_code": 2, "finished_at": "now",
               "stdout_ref": _write(tmp_path / "stdout.json", {}), "stderr_ref": _write(tmp_path / "stderr.json", {})}
    result = {"schema": "context-online-ab.run-result.v1", "agent_process": process,
              "dispatch_ref": _write(records / "dispatch.json", {"run_root": str(root)}),
              "routing_result_ref": _write(records / "natural-result.json", natural),
              "product_run": {"allowed_root": str(workspace), "run_root": str(root), "run_id": root.name,
                              "manifest_ref": reference(root / "run_manifest.json"), "result_ref": reference(root / "run_result.json")}}
    ready = {"records_root": str(records), "profile_ref": _write(tmp_path / "profile.json", {
        "arguments": ["--workspace-root", str(workspace)]})}
    return result, ready


def test_cost_coverage_accepts_failed_task_with_complete_cost(tmp_path):
    result, ready = _coverage_fixture(tmp_path)
    # Actual S2 routing stores conversation receipts beside route directories.
    (tmp_path / "runs/.dsh-routing/conversations").mkdir()
    coverage = infer_current_trial_cost_coverage(result, ready)
    assert coverage["missing"] == []
    assert coverage["product_complete"] is True
    assert coverage["routing_complete"] is True
    assert coverage["delivery_model_calls"] == 0
    assert coverage["basis_refs"]


def test_host_recomputes_coverage_without_rewriting_recorded_false(tmp_path):
    result, ready = _coverage_fixture(tmp_path)
    (tmp_path / "runs/.dsh-routing/conversations").mkdir()
    result.update(order()["order"][0], status="completed", success=True, elapsed_seconds=99)
    ready_ref = _write(tmp_path / "ready.json", ready)
    result["trial_ref"] = _write(tmp_path / "trial.json", {**order()["order"][0], "ready_ref": ready_ref})
    result["cost_coverage"] = {"routing_complete": False, "product_complete": False}
    result_ref = _write(tmp_path / "outer-result.json", result)
    summary = summarize(order(), {"runs": [{**order()["order"][0], "result_ref": result_ref}]})
    row = summary["runs"][0]
    assert row["recorded_cost_coverage"]["product_complete"] is False
    assert row["cost_coverage"]["product_complete"] is True
    assert row["metrics"]["input_tokens"] == 17
    assert row["metrics"]["output_tokens"] == 6
    assert row["metrics"]["cache_tokens"] is None
    assert reference(result_ref["path"]) == result_ref


def _routing_only_fixture(tmp_path):
    workspace, records_root = tmp_path / "runs", tmp_path / "records"
    route_root = workspace / ".dsh-routing/route-one"
    route_root.mkdir(parents=True)
    (route_root.parent / "conversations").mkdir()
    usage = {"input_tokens":4088,"output_tokens":94}
    body_refs = {role:_write(route_root / f"{role}.json", {"body":role}) for role in ("request","response")}
    attrs = {"transport_started":True,"response_complete":True,"usage":usage,"local_detail_refs":body_refs}
    _write(route_root / "trace.json", {"observations":[
        {"id":"req","name":"model.request","kind":"span","status":"completed","attributes":attrs},
        {"id":"gen","parent_id":"req","kind":"generation","status":"completed","attributes":attrs}]})
    natural = {"status":"needs_clarification","decision":{"action":"clarify"},
        "product_execution_started":False,"product_owner_invoked":False,
        "routing_record_path":str(route_root / "result.json"),"turn_id":"initial",
        "budget":{"routing_model_call_limit":1},"routing_transport_calls":1,"routing_usage":usage}
    _write(route_root / "result.json",natural)
    process = {"started":True,"status":"exited","timeout":False,"exit_code":2,"finished_at":"now",
        "stdout_ref":_write(tmp_path / "stdout.json",{}),"stderr_ref":_write(tmp_path / "stderr.json",{})}
    result = {**order()["order"][0],"schema":"context-online-ab.run-result.v1","status":"agent_failed",
        "success":False,"elapsed_seconds":42.562,"agent_process":process,
        "routing_result_ref":_write(records_root / "natural-result.json",natural),
        "cost_coverage":{"routing_complete":False,"product_complete":False,"missing":["KeyError: 'product_run'"]}}
    ready = {"records_root":str(records_root),"profile_ref":_write(tmp_path / "profile.json",
        {"arguments":["--workspace-root",str(workspace)]})}
    return result, ready, natural


def test_routing_clarification_counts_route_and_warmup_without_fake_product(tmp_path):
    result, ready, _ = _routing_only_fixture(tmp_path)
    result["trial_ref"] = _write(tmp_path / "trial.json", {**order()["order"][0],
        "ready_ref":_write(tmp_path / "ready.json",ready)})
    result_ref = _write(tmp_path / "outer.json",result)
    summary = summarize(order(),{"runs":[{**order()["order"][0],"result_ref":result_ref,
        "startup_ref":_startup(tmp_path,"routing-only")}]})
    row = summary["runs"][0]
    assert row["status"] == row["recorded_status"] == "agent_failed"
    assert row["execution_outcome"] == "needs_clarification" and row["delivery_outcome"] == "not_delivered"
    assert row["success"] is False and row["product_execution_started"] is False
    assert row["cost_coverage"]["product_not_executed_proven"] is True
    assert row["product_nonexecution_measurement"]["model_calls"] == 0
    assert row["metrics"]["selected_product_input_tokens"] == 0
    assert row["metrics"]["input_tokens"] == 4088 and row["metrics"]["output_tokens"] == 94
    assert row["metrics"]["cache_tokens"] is None
    assert "trace_measurement" not in row and "native product trace unavailable" not in row["missing"]
    assert row["recorded_cost_coverage"]["missing"] == ["KeyError: 'product_run'"]
    combined = summary["all_attempt_costs_including_additional"]["baseline"]["with_warmup"]
    assert combined["input_tokens"]["including_warmup"]["known_subtotal"] == 4092
    assert combined["output_tokens"]["including_warmup"]["known_subtotal"] == 96
    assert combined["elapsed_seconds"]["including_warmup"]["known_subtotal"] == pytest.approx(45.562)
    assert reference(result_ref["path"]) == result_ref


@pytest.mark.parametrize("defect", ["missing_flags","owner_invoked","execution_started","product_directory",
    "dispatch_file","product_process_file","acceptance_started","timeout","extra_route","usage_missing","body_drift"])
def test_routing_only_zero_requires_positive_nonexecution_and_complete_cost(tmp_path, defect):
    result, ready, natural = _routing_only_fixture(tmp_path)
    if defect == "missing_flags":
        natural.pop("product_execution_started")
    elif defect == "owner_invoked":
        natural["product_owner_invoked"] = True
    elif defect == "execution_started":
        natural["product_execution_started"] = True
    elif defect == "product_directory":
        (tmp_path / "runs/unrecorded-product").mkdir()
    elif defect == "dispatch_file":
        _write(tmp_path / "records/dispatch.json",{})
    elif defect == "product_process_file":
        _write(tmp_path / "records/product-process.json",{})
    elif defect == "acceptance_started":
        result["acceptance_process"] = {"started":True}
    elif defect == "timeout":
        result["agent_process"]["timeout"] = True
    elif defect == "extra_route":
        (tmp_path / "runs/.dsh-routing/route-two").mkdir()
    elif defect == "usage_missing":
        natural["routing_usage"].pop("input_tokens")
    elif defect == "body_drift":
        (tmp_path / "runs/.dsh-routing/route-one/response.json").write_text("{}")
    _write(tmp_path / "runs/.dsh-routing/route-one/result.json",natural)
    result["routing_result_ref"] = _write(tmp_path / "records/natural-result.json",natural)
    coverage = infer_current_trial_cost_coverage(result,ready)
    assert coverage.get("product_not_executed_proven") is not True
    assert coverage["product_complete"] is False and coverage["missing"]


@pytest.mark.parametrize("defect", ["timeout", "continuation", "extra_route", "extra_product", "body_drift", "usage_missing", "orphan_request"])
def test_cost_coverage_rejects_incomplete_or_ambiguous_history(tmp_path, defect):
    result, ready = _coverage_fixture(tmp_path)
    root = tmp_path / "runs/run-one"
    if defect == "timeout":
        result["agent_process"]["timeout"] = True
    elif defect == "continuation":
        (root / "continuations").mkdir()
    elif defect == "extra_route":
        (tmp_path / "runs/.dsh-routing/route-two").mkdir()
    elif defect == "extra_product":
        (tmp_path / "runs/run-two").mkdir()
    elif defect == "body_drift":
        (root / "details/response.json").write_text('{}')
    elif defect == "usage_missing":
        manifest = json.loads((root / "run_manifest.json").read_text())
        manifest["execution_observations"]["generation"]["attributes"]["usage"].pop("input_tokens")
        result["product_run"]["manifest_ref"] = _write(root / "run_manifest.json", manifest)
    else:
        manifest = json.loads((root / "run_manifest.json").read_text())
        manifest["execution_observations"]["orphan"] = {
            "id": "orphan", "name": "model.request", "kind": "span", "attributes": {"transport_started": True}}
        result["product_run"]["manifest_ref"] = _write(root / "run_manifest.json", manifest)
    coverage = infer_current_trial_cost_coverage(result, ready)
    assert coverage["product_complete"] is False
    assert coverage["missing"]


def test_admission_extra_keeps_cost_without_changing_registered_rates(tmp_path):
    selected = records(tmp_path, [True] * 20)
    protocol = order()
    original = tmp_path / "admission-failed.json"
    original.write_text(json.dumps({**protocol["order"][0], "status": "agent_failed", "success": False,
        "elapsed_seconds": 4.984, "agent_process": {"started": True}}))
    protocol["additional_attempts"] = [{**protocol["order"][0], "result_ref": reference(original),
        "classification": "pre_model_environment_admission_failed"}]
    result = summarize(protocol, selected)
    assert result["by_arm"]["baseline"]["completion_fraction"] == 1
    assert result["by_arm"]["baseline"]["observed_pass_power_2"] == 1
    assert result["attempt_accounting"]["total_attempts"] == 21
    assert result["additional_attempts"][0]["status"] == "agent_failed"
    assert result["additional_attempts"][0]["metrics"]["input_tokens"] is None
    assert result["all_attempt_costs_including_additional"]["baseline"]["elapsed_seconds"]["total"] == pytest.approx(99.984)


def test_extra_duplicate_cannot_count_registered_attempt_twice(tmp_path):
    selected = records(tmp_path, [False])
    protocol = order()
    protocol["additional_attempts"] = [{**selected["runs"][0], "classification": "admission_failed"}]
    with pytest.raises(ValueError, match="counted more than once"):
        summarize(protocol, selected)


def test_extra_zero_usage_needs_explicit_bound_measurement(tmp_path):
    original = tmp_path / "admission-failed.json"
    identity_row = order()["order"][0]
    original.write_text(json.dumps({**identity_row, "status": "agent_failed", "success": False,
                                   "agent_process": {"started": True}, "native_usage": {"input_tokens": 0}}))
    ref = reference(original)
    protocol = {"trials": order()["order"], "additional_attempts": [{**identity_row,
        "result_ref": ref, "classification": "pre_model_environment_admission_failed",
        "metric_sources": {"input_tokens": {"ref": ref, "pointer": "/native_usage/input_tokens"}}}]}
    result = summarize(protocol, {"runs": []})
    assert result["attempt_accounting"]["total_attempts"] == 1
    assert result["by_arm"]["baseline"]["completion_fraction"] is None
    metrics = result["additional_attempts"][0]["metrics"]
    assert metrics["input_tokens"] == 0
    assert metrics["output_tokens"] is None


def _startup(tmp_path, name, version="hot-v1", classification="hot_verified"):
    request_ref = _write(tmp_path / f"{name}-req.json", {"prompt": "warmup"})
    response_ref = _write(tmp_path / f"{name}-resp.json", {"response": "ok"})
    warmup_ref = _write(tmp_path / f"{name}-warm.json", {"input_tokens": 4, "output_tokens": 2,
        "elapsed_seconds": 3, "request_ref": request_ref, "response_ref": response_ref})
    return _write(tmp_path / f"{name}-startup.json", {"startup_condition_version": version,
        "condition_classification": classification, "warmup_ref": warmup_ref,
        "residency_refs": [_write(tmp_path / f"{name}-residency.json", {"samples": ["start", "end"]})]})


def _actual_conditions_fixture(tmp_path, *, different=False, annotated=True, terminal=True):
    protocol = order()
    for index, row in enumerate(protocol["order"]):
        row["trial_id"] = f"trial-{index}"
    protocol_ref = _write(tmp_path / "actual-protocol.json", protocol)
    selected = records(tmp_path, [True, False, True])
    for index, row in enumerate(selected["runs"]):
        row["startup_ref"] = _startup(tmp_path, f"actual-{index}")
    def stratum(name):
        return {"id": name, "model_digest": "model", "context_length": 65536}
    excerpt = _write(tmp_path / "runner-excerpt.json", {"scope": "synthetic fixture, not runtime evidence"})
    rows = []
    for index in (0, 2) if annotated else ():
        initial = {"digest": "model", "context_length": 65536, "size": 100, "size_vram": 50}
        rows.append({"trial_id": f"trial-{index}", "actual_execution_stratum": "second" if different and index == 2 else "first",
            "initial_residency_ref": _write(tmp_path / f"actual-{index}-ps.json", {"models": [initial]}),
            "initial_residency_validation_ref": _write(tmp_path / f"actual-{index}-validation.json", {"classification": "hot_verified"}),
            "startup_before_task_ref": _write(tmp_path / f"actual-{index}-before.json", {"trial_id": f"trial-{index}", "protocol_ref": protocol_ref}),
            "warmup_request_ref": _write(tmp_path / f"actual-{index}-warmup-request.json", {"prompt": "one token"}),
            "observed_initial_residency": initial, "runner_load_log_ids": ["runner"],
            **({"terminal_ref": selected["runs"][index]["result_ref"],
                "completed_startup_ref": selected["runs"][index]["startup_ref"]} if terminal else {})})
    conditions = _write(tmp_path / "actual-conditions.json", {"schema": "online-ab-actual-host-conditions.v1",
        "protocol_ref": protocol_ref, "strata": [stratum("first"), stratum("second")], "trials": rows,
        "log_excerpts": [{"id": "runner", "excerpt_ref": excerpt}]})
    return protocol, selected, protocol_ref, conditions


def test_actual_condition_difference_excludes_latency_pair_without_changing_scores(tmp_path):
    protocol, selected, protocol_ref, conditions = _actual_conditions_fixture(tmp_path, different=True)
    old = summarize(protocol, selected)
    result = summarize(protocol, selected, actual_conditions_ref=conditions, order_ref=protocol_ref)
    assert result["by_arm"] == old["by_arm"]
    assert [(x["status"], x["success"]) for x in result["runs"]] == [(x["status"], x["success"]) for x in old["runs"]]
    assert result["registered_runs"] == 20 and result["by_arm"]["baseline"]["success_denominator"] == 10
    assert result["paired_success_seconds"]["n"] == 0
    assert result["by_startup_condition"]["hot-v1"]["paired_success_seconds"]["n"] == 0
    assert result["all_joint_success_pairs"][0]["startup_verified_comparable"] is True
    assert result["all_joint_success_pairs"][0]["actual_execution_verified_comparable"] is False
    assert all(x["paired_success_seconds"]["n"] == 0 for x in result["by_actual_execution_condition"])


def test_unknown_actual_conditions_do_not_compare_equal(tmp_path):
    protocol, selected, protocol_ref, conditions = _actual_conditions_fixture(tmp_path, annotated=False)
    result = summarize(protocol, selected, actual_conditions_ref=conditions, order_ref=protocol_ref)
    assert result["paired_success_seconds"]["n"] == 0
    assert result["all_joint_success_pairs"][0]["actual_execution_strata"] == {"baseline": None, "candidate": None}
    assert result["all_joint_success_pairs"][0]["verified_comparable"] is False


def test_same_bound_actual_conditions_keep_success_pair_and_original_hot_classification(tmp_path):
    protocol, selected, protocol_ref, conditions = _actual_conditions_fixture(tmp_path)
    result = summarize(protocol, selected, actual_conditions_ref=conditions, order_ref=protocol_ref)
    assert result["paired_success_seconds"]["n"] == 1
    group = next(x for x in result["by_actual_execution_condition"] if x["actual_execution_stratum"] == "first")
    assert group["startup_condition_version"] == "hot-v1" and group["paired_success_seconds"]["n"] == 1
    assert result["runs"][0]["startup"]["condition_classification"] == "hot_verified"
    assert result["runs"][0]["actual_execution_condition"]["evidence_refs"]


def test_initial_only_condition_does_not_certify_later_terminal(tmp_path):
    protocol, selected, protocol_ref, conditions = _actual_conditions_fixture(tmp_path, terminal=False)
    result = summarize(protocol, selected, actual_conditions_ref=conditions, order_ref=protocol_ref)
    assert result["runs"][0]["actual_execution_stratum"] == "first"
    assert result["runs"][0]["actual_execution_condition"]["status"] == "initial_evidence_only"
    assert result["paired_success_seconds"]["n"] == 0
    assert result["runs"][0]["success"] is True


def test_actual_condition_protocol_cannot_be_reused_for_another_series(tmp_path):
    protocol, selected, _, conditions = _actual_conditions_fixture(tmp_path)
    other_ref = _write(tmp_path / "another-series.json", protocol)
    with pytest.raises(ValueError, match="exact protocol"):
        summarize(protocol, selected, actual_conditions_ref=conditions, order_ref=other_ref)


def test_historical_summary_without_conditions_retains_behavior_and_marks_dimension_unknown(tmp_path):
    protocol, selected, _, _ = _actual_conditions_fixture(tmp_path)
    result = summarize(protocol, selected)
    assert result["paired_success_seconds"]["n"] == 1
    assert result["actual_condition_dimension"] == "not_verified_no_conditions_input"
    assert result["all_joint_success_pairs"][0]["verified_comparable"] is False


def test_cli_actual_conditions_are_bound_in_saved_summary(tmp_path):
    protocol, selected, protocol_ref, conditions = _actual_conditions_fixture(tmp_path)
    records_ref = _write(tmp_path / "actual-records.json", selected)
    output = tmp_path / "actual-summary.json"
    assert main(["--order", protocol_ref["path"], "--records", records_ref["path"],
                 "--actual-conditions", conditions["path"], "--output", str(output)]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["summarizer_version"] == "3.8"
    assert result["actual_conditions_ref"] == conditions
    assert result["paired_success_seconds"]["n"] == 1


def test_actual_condition_evidence_drift_does_not_rewrite_task_outcome(tmp_path):
    protocol, selected, protocol_ref, conditions = _actual_conditions_fixture(tmp_path)
    (tmp_path / "runner-excerpt.json").write_text("changed", encoding="utf-8")
    result = summarize(protocol, selected, actual_conditions_ref=conditions, order_ref=protocol_ref)
    assert result["runs"][0]["success"] is True
    assert result["runs"][0]["status"] == "completed"
    assert result["runs"][0]["actual_execution_condition"]["status"] == "condition_evidence_unavailable"
    assert result["paired_success_seconds"]["n"] == 0


def test_actual_condition_costs_partition_all_failures_warmups_and_unknowns_once(tmp_path):
    protocol, selected, protocol_ref, conditions = _actual_conditions_fixture(tmp_path, different=True)
    result = summarize(protocol, selected, actual_conditions_ref=conditions, order_ref=protocol_ref)
    strata = result["by_actual_execution_condition"]
    assert result["runs"][1]["success"] is False
    unknown_hot = next(row for row in strata if row["startup_condition_version"] == "hot-v1"
                       and row["actual_execution_stratum"] is None)
    assert unknown_hot["by_arm_observed_cost"]["baseline"]["elapsed_seconds"]["delivery"]["known_subtotal"] == 2
    assert unknown_hot["by_arm_observed_cost"]["baseline"]["elapsed_seconds"]["warmup"]["known_subtotal"] == 3
    for arm in ("baseline", "candidate"):
        assert result["by_arm"][arm]["registered_runs"] == 10
        assert "diagnostic" in result["by_arm"][arm]["elapsed_seconds_all_runs_scope"]
        for metric in ("elapsed_seconds", "input_tokens", "output_tokens", "cache_tokens"):
            whole = result["all_attempt_costs_including_additional"][arm]["with_warmup"][metric]
            for scope in ("delivery", "warmup", "including_warmup"):
                for count in ("known_subtotal", "observed", "missing"):
                    assert sum(layer["by_arm_observed_cost"][arm][metric][scope][count] for layer in strata) == whole[scope][count]
        assert result["all_attempt_costs_including_additional"][arm]["with_warmup"]["input_tokens"]["including_warmup"]["total"] is None


def test_warmup_expense_separate_and_included_without_changing_delivery(tmp_path):
    selected = records(tmp_path, [True, True, True])
    for index, row in enumerate(selected["runs"]):
        row["startup_ref"] = _startup(tmp_path, str(index))
    result = summarize(order(), selected)
    assert result["runs"][0]["elapsed_seconds"] == 1
    combined = result["all_attempt_costs_including_additional"]["baseline"]["with_warmup"]["elapsed_seconds"]
    assert combined["delivery"]["known_subtotal"] == 3
    assert combined["warmup"]["known_subtotal"] == 6
    assert combined["including_warmup"]["known_subtotal"] == 9
    assert result["by_startup_condition"]["hot-v1"]["paired_success_seconds"]["n"] == 1
    assert result["by_startup_condition"]["hot-v1"]["by_arm_outcomes"]["baseline"]["observed_pass_at_2"] is None


def test_legacy_hot_versions_and_deviations_never_form_comparable_pair(tmp_path):
    selected = records(tmp_path, [True] * 8)
    selected["runs"][2]["startup_ref"] = _startup(tmp_path, "cold-opponent")
    selected["runs"][4]["startup_ref"] = _startup(tmp_path, "hot-baseline")
    selected["runs"][6]["startup_ref"] = _startup(tmp_path, "hot-candidate", classification="deviation")
    result = summarize(order(), selected)
    assert result["paired_success_seconds"]["mixed_conditions_suppressed"] is True
    assert result["paired_success_seconds"]["n"] == 0
    assert result["by_startup_condition"]["hot-v1"]["paired_success_seconds"]["n"] == 0
    assert result["by_startup_condition"]["legacy_unclassified"]["paired_success_seconds"]["n"] == 0
    assert len(result["runs"]) == 20
    assert result["by_arm"]["baseline"]["success_runs"] == 4


def test_startup_evidence_fault_does_not_turn_delivery_failure(tmp_path):
    selected = records(tmp_path, [True])
    startup = _startup(tmp_path, "one")
    selected["runs"][0]["startup_ref"] = startup
    (tmp_path / "one-residency.json").write_text("{}")
    row = summarize(order(), selected)["runs"][0]
    assert row["success"] is True
    assert row["startup"]["condition_classification"] == "unknown"
    assert row["startup"]["measurement_error"]
    assert row["startup"]["warmup"]["input_tokens"] == 4


def test_same_warmup_receipt_not_charged_twice(tmp_path):
    selected = records(tmp_path, [True, True])
    startup = _startup(tmp_path, "shared")
    for row in selected["runs"]:
        row["startup_ref"] = startup
    with pytest.raises(ValueError, match="Warmup cost evidence counted"):
        summarize(order(), selected)


def test_native_worker_cache_overrides_zero_and_records_conflict(tmp_path):
    ref = _write(tmp_path / "worker.json", {"usage": {"cached_input_tokens": 0}, "raw_response": {
        "model": "local", "done": True, "prompt_eval_count": 9000, "eval_count": 200, "prompt_eval_cached_count": 6035}})
    measured = native_cache_measurement(ref)
    assert measured["value"] == 6035
    assert measured["normalized_cached_input_tokens"] == 0
    assert measured["normalization_conflict"] is True
    assert measured["native_prompt_tokens"] == 9000
    assert measured["pointer"] == "/raw_response/prompt_eval_cached_count"


@pytest.mark.parametrize("preferred,expected_cache", [
    ("transport_response", 7), ("provider_response", 5), ("response", 3)])
def test_planning_native_response_reference_priority(tmp_path, preferred, expected_cache):
    root = tmp_path / "run-one"
    manifest = _segment(root)
    attrs = manifest["execution_observations"]["generation"]["attributes"]
    refs = attrs["local_detail_refs"]
    native = {"model":"local-model", "done":True, "prompt_eval_count":10,
              "eval_count":3, "prompt_eval_cached_count":3}
    if preferred == "response":
        refs["response"] = _write(root / "details/worker.response.json", {"raw_response":native})
    else:
        # Real planning layout: parsed text remains alongside the retained native envelope.
        parsed = root / "details/planning.response.txt"
        parsed.write_text("parsed planning prose, not a provider usage receipt", encoding="utf-8")
        refs["response"] = reference(parsed)
        refs["provider_response"] = _write(root / "details/planning.provider_response.json",
            {**native,"prompt_eval_cached_count":5})
        attrs["provider_response_capture_boundary"] = "adapter_raw_response_json_not_wire_bytes"
        if preferred == "transport_response":
            refs["transport_response"] = _write(root / "details/planning.transport_response.json",
                {**native,"prompt_eval_cached_count":7})
    selection = {"allowed_root":str(tmp_path),"run_root":str(root),"run_id":"run-one",
                 "manifest_ref":_write(root / "run_manifest.json",manifest),
                 "result_ref":reference(root / "run_result.json")}
    measured = measure_trace(selection)
    assert measured["cache_tokens"]["total"] == expected_cache
    row = measured["cache_token_records"][0]
    assert row["response_ref"] == refs[preferred] and row["source_kind"] == preferred
    if preferred == "provider_response":
        assert row["capture_boundary"] == "adapter_raw_response_json_not_wire_bytes"
    assert measured["native_usage"]["input_tokens"]["total"] == 10
    assert measured["native_usage"]["output_tokens"]["total"] == 3


@pytest.mark.parametrize("native_field,normalized_field", [
    ("prompt_eval_count","input_tokens"),("eval_count","output_tokens"),
    ("prompt_eval_cached_count","cached_input_tokens")])
def test_planning_partial_native_usage_does_not_turn_missing_into_zero(tmp_path, native_field, normalized_field):
    root = tmp_path / "run-one"
    usage = {"input_tokens":10,"output_tokens":3,"cached_input_tokens":0}
    usage.pop(normalized_field)
    manifest = _segment(root,usage=usage)
    native = {"model":"local-model","done":True,"prompt_eval_count":10,
              "eval_count":3,"prompt_eval_cached_count":0}
    native.pop(native_field)
    attrs = manifest["execution_observations"]["generation"]["attributes"]
    attrs["local_detail_refs"]["provider_response"] = _write(root / "details/provider_response.json",native)
    measured = measure_trace({"allowed_root":str(tmp_path),"run_root":str(root),"run_id":"run-one",
        "manifest_ref":_write(root / "run_manifest.json",manifest),
        "result_ref":reference(root / "run_result.json")})
    assert measured["cache_tokens"]["total"] is None
    if normalized_field != "cached_input_tokens":
        assert measured["native_usage"][normalized_field]["total"] is None


@pytest.mark.parametrize("payload", [{"usage": {"cached_input_tokens": 0}}, {"findings": []}, {
    "model": "fake-model-content", "done": True, "prompt_eval_count": 9, "eval_count": 1, "prompt_eval_cached_count": 8}])
def test_missing_native_cache_does_not_become_zero_or_model_assertion(tmp_path, payload):
    ref = _write(tmp_path / "parsed-answer.json", payload)
    assert native_cache_measurement(ref, normalized=0)["value"] is None


def test_warmup_native_zero_is_proven_without_adding_to_input(tmp_path):
    selected = records(tmp_path, [True])
    startup = _startup(tmp_path, "cache")
    raw_ref = _write(tmp_path / "warmup-native.json", {"model": "local", "done": True,
        "prompt_eval_count": 13, "eval_count": 1, "prompt_eval_cached_count": 0})
    warm = json.loads((tmp_path / "cache-warm.json").read_text())
    warm.update(response_ref=raw_ref, input_tokens=13, output_tokens=1, cached_input_tokens=None)
    warm_ref = _write(tmp_path / "cache-warm.json", warm)
    start = json.loads((tmp_path / "cache-startup.json").read_text())
    start["warmup_ref"] = warm_ref
    startup = _write(tmp_path / "cache-startup.json", start)
    selected["runs"][0]["startup_ref"] = startup
    record = summarize(order(), selected)["runs"][0]["startup"]
    assert record["warmup"]["cache_tokens"] == 0
    assert record["warmup"]["input_tokens"] == 13
    assert record["warmup_cache_measurement"]["response_ref"] == raw_ref


def _discovery_protocol(tmp_path):
    protocol = {"startup_condition": {"version": "hot-v1"}, "trials": []}
    for index, trial in enumerate(order()["order"]):
        body = {**trial, "trial_id": f"trial{index}", "output_root": str(tmp_path / "outputs" / f"trial{index}")}
        protocol["trials"].append({**body, "trial_ref": _write(tmp_path / f"trial{index}.json", body)})
    return protocol


def test_discovery_ignores_hot_task_result_until_wrapper_terminal(tmp_path):
    protocol = _discovery_protocol(tmp_path)
    trial = protocol["trials"][0]
    task_ref = _write(tmp_path / "outputs/trial0/result.json", {**trial, "success": True})
    assert len(discover_records(protocol)["runs"]) == 0
    startup = _startup(tmp_path, "discovery")
    startup_ref = _write(tmp_path / "outputs/trial0-startup-hot-v1/startup.json", json.loads(open(startup["path"]).read()))
    _write(tmp_path / "outputs/trial0-startup-hot-v1/result.json", {
        "schema": "context-online-ab.hot-wrapper-result.v1", "trial_id": "trial0",
        "task_started": True, "startup_ref": startup_ref, "task_result_ref": task_ref})
    index = discover_records(protocol)
    assert len(index["runs"]) == 1
    assert len(index["pending"]) == 19
    assert index["runs"][0]["result_ref"] == task_ref


def test_discovery_keeps_failed_warmup_expense_without_task_success(tmp_path):
    protocol = _discovery_protocol(tmp_path)
    startup = _startup(tmp_path, "failed-warmup", classification="deviation")
    startup_ref = _write(tmp_path / "outputs/trial0-startup-hot-v1/startup.json", json.loads(open(startup["path"]).read()))
    _write(tmp_path / "outputs/trial0-startup-hot-v1/result.json", {
        "schema": "context-online-ab.hot-wrapper-result.v1", "trial_id": "trial0",
        "task_started": False, "success": None, "startup_ref": startup_ref, "task_result_ref": None})
    result = summarize(protocol, discover_records(protocol))
    row = result["runs"][0]
    assert row["status"] == "startup_failed_before_task"
    assert row["success"] is None
    assert row["startup"]["warmup"]["input_tokens"] == 4
    assert row["metrics"]["input_tokens"] == 0
    assert result["by_arm"]["baseline"]["completion_fraction"] is None
    assert result["all_attempt_costs_including_additional"]["baseline"]["with_warmup"]["input_tokens"]["including_warmup"]["known_subtotal"] == 4


def test_source_version_survives_later_source_change(tmp_path):
    source = tmp_path / "source.py"
    source.write_bytes(b"print('version one')\n")
    first = preserve_source_version(tmp_path / "output", source)
    source.write_bytes(b"print('version two')\n")
    second = preserve_source_version(tmp_path / "output", source)
    assert first["summarizer_ref"] != second["summarizer_ref"]
    assert reference(first["summarizer_ref"]["path"]) == first["summarizer_ref"]
    assert first["origin_ref"]["path"] == str(source.resolve())


def test_discover_cli_emits_bound_index_and_immutable_source(tmp_path):
    protocol_path = tmp_path / "protocol.json"
    _write(protocol_path, _discovery_protocol(tmp_path))
    output = tmp_path / "summary.json"
    assert main(["--order", str(protocol_path), "--discover-records", "--output", str(output)]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["records_ref"] == reference(tmp_path / "summary.records.json")
    assert result["summarizer_ref"] == reference(result["summarizer_ref"]["path"])
    assert "source-versions" in result["summarizer_ref"]["path"]
    assert len(result["discovery_pending"]) == 20
    dependencies = {row["module"]: row for row in result["host_dependency_refs"]}
    assert "src.mod_agent.evaluation.task_measurement" in dependencies
    assert "src.mod_agent.evaluation.tool_effects" in dependencies
    for module in ("src.mod_agent.evaluation.task_measurement", "src.mod_agent.evaluation.tool_effects"):
        ref = dependencies[module]["source_ref"]
        assert reference(ref["path"]) == ref


def test_phase_boundaries_keep_nested_spans_without_summing(tmp_path):
    observations = {}
    for name, span_id, parent_id, start, end, elapsed in (
        ("product.execution", "product", None, 0, 10, 10000),
        ("patch.worker", "patch", "product", 2, 8, 6000),
        ("validate.full_project_compilation", "build", "patch", 4, 6, 2000)):
        observations[span_id] = {"id": span_id, "trace_id": "trace", "name": name, "kind": "span",
            "parent_id": parent_id, "elapsed_ms": elapsed, "started_at": f"2026-10-06T00:00:{start:02d}+00:00",
            "finished_at": f"2026-10-06T00:00:{end:02d}+00:00"}
    manifest_ref = _write(tmp_path / "manifest.json", {"execution_observations": observations})
    outer = {"elapsed_seconds": 12, "agent_process": {"started_at": "2026-10-06T00:00:00+00:00",
        "finished_at": "2026-10-06T00:00:11+00:00", "wall_seconds": 11},
        "product_run": {"manifest_ref": manifest_ref}}
    measured = phase_timings(outer, _write(tmp_path / "result.json", outer))
    assert measured["sum_seconds"] is None
    build = next(r for r in measured["records"] if r["stage"] == "build")
    assert build["elapsed_seconds"] == 2
    assert build["relative_start_seconds"] == 4
    assert build["relative_end_seconds"] == 6
    assert build["parent"] == "patch"
    assert next(r for r in measured["missing"] if r["stage"] == "delivery")["elapsed_seconds"] is None


def test_delivery_timer_and_build_are_nested_under_acceptance_not_added(tmp_path):
    execution_ref = _write(tmp_path / "build.json", {"execution_observations": {
        "b": {"id": "b", "trace_id": "delivery", "name": "workflow.build", "elapsed_ms": 4000}}})
    delivery_ref = _write(tmp_path / "delivery.json", {"delivery_seconds": 9.77, "execution_refs": [execution_ref]})
    outer = {"elapsed_seconds": 40, "acceptance_process": {"wall_seconds": 12.7}, "acceptance_result_ref": delivery_ref}
    measured = phase_timings(outer, _write(tmp_path / "result.json", outer))
    assert {r["stage"]: r["elapsed_seconds"] for r in measured["records"]} == {
        "end_to_end": 40, "acceptance_process": 12.7, "delivery": 9.77, "build": 4}
    assert measured["sum_seconds"] is None
    assert next(r for r in measured["missing"] if r["stage"] == "formal_acceptance_only")["elapsed_seconds"] is None


@pytest.mark.parametrize("evidence", ["outputs/trial0/admission.json", "outputs/trial0-startup-hot-v1/startup-before-task.json"])
def test_started_without_terminal_is_incomplete_not_unexecuted_or_live(tmp_path, evidence):
    protocol = _discovery_protocol(tmp_path)
    start_ref = _write(tmp_path / evidence, {"observed": "admission; no terminal yet"})
    index = discover_records(protocol)
    assert index["runs"] == []
    result = summarize(protocol, index)
    row = result["runs"][0]
    assert row["status"] == "awaiting_terminal_evidence"
    assert row["success"] is None
    assert row["attempt_started"] is None
    assert row["elapsed_seconds"] is None
    assert row["start_evidence_refs"] == [start_ref]
    assert row["live_process_state"] == "unknown_not_inferred_from_files"
    assert result["runs"][1]["status"] == "not_executed"
    assert result["by_arm"]["baseline"]["registered_runs"] == 10
    assert result["by_arm"]["baseline"]["completion_fraction"] is None
    assert result["attempt_accounting"]["total_attempts"] is None
    assert result["attempt_accounting"]["unknown_start_status"] == 1


@pytest.mark.parametrize("failure", ["permission", "hash_drift"])
def test_discovery_observation_failure_is_not_not_executed_or_task_failure(tmp_path, monkeypatch, failure):
    protocol = _discovery_protocol(tmp_path)
    broken_ref = protocol["trials"][0]["trial_ref"]
    if failure == "permission":
        from scripts import summarize_context_online_ab as module
        original = module.read_bound

        def denied(ref):
            if ref == broken_ref:
                raise PermissionError("selected trial cannot be read")
            return original(ref)

        monkeypatch.setattr(module, "read_bound", denied)
    else:
        (tmp_path / "trial0.json").write_text("{}", encoding="utf-8")
    index = discover_records(protocol)
    assert index["pending"][0]["reason"] == "discovery_evidence_unavailable"
    result = summarize(protocol, index)
    row = result["runs"][0]
    assert row["status"] == "evidence_unavailable"
    assert row["success"] is None
    assert row["attempt_started"] is None
    assert row["discovery_error"]["unverified_trial_ref"] == broken_ref
    assert result["runs"][1]["status"] == "not_executed"
    assert result["by_arm"]["baseline"]["success_runs"] == 0
    assert result["by_arm"]["baseline"]["completion_fraction"] is None
    assert result["by_arm"]["baseline"]["outcomes"]["evidence_unavailable"] == 1
