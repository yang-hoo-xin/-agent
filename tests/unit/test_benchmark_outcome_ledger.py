"""Outcome-ledger denominators and unknown coverage, without Product execution."""
from __future__ import annotations

import hashlib
from copy import deepcopy

import pytest

from src.mod_agent.evaluation.benchmark_outcome_ledger import (
    LEDGER_SCHEMA_VERSION,
    SCHEMA_RULES,
    aggregate_outcome_ledger,
    verify_evidence_references,
)


def _ref(tmp_path, name, content=None):
    raw = (content or name).encode("utf-8")
    path = tmp_path / f"{name}.json"
    path.write_bytes(raw)
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest()}


def _cost(*, complete=True, input_tokens=10, output_tokens=2, model_calls=1,
          tool_calls=3, judge_calls=1, elapsed_seconds=5):
    return {
        "complete": complete,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": 0 if input_tokens is not None else None,
        "model_calls": model_calls,
        "provider_sends": model_calls,
        "tool_calls": tool_calls,
        "source_retrieval_calls": 1 if tool_calls is not None else None,
        "judge_calls": judge_calls,
        "retry_count": 0 if model_calls is not None else None,
        "elapsed_seconds": elapsed_seconds,
        "human_wait_seconds": 0 if elapsed_seconds is not None else None,
    }


def _record(tmp_path, task_id, *, record_id=None, family=None, revision=1, repeat=1,
            primary=True, validity="valid", execution_status="executed",
            execution_origin="product", arm="candidate", delivery=False,
            first=False, runtime=None, repair=None, interventions=None, cost=None,
            ttd=None, failure_stage="planning"):
    record_id = record_id or f"{task_id}-{execution_origin}-{repeat}-r{revision}"
    if runtime is None:
        runtime = {"required": False, "executed": False, "passed": None}
    if repair is None:
        repair = {"eligible": False, "attempted": False, "passed": None}
    if interventions is None:
        interventions = {
            kind: {"required": False, "count": 0}
            for kind in ("developer", "user", "operational")
        }
    if cost is None:
        cost = _cost()
    if execution_status != "executed" and validity == "valid":
        delivery, first, ttd, failure_stage = None, None, None, None
        repair = {"eligible": None, "attempted": None, "passed": None}
    if delivery is None:
        failure_stage = None
    if delivery is True:
        failure_stage = None
        ttd = 5 if ttd is None else ttd
    return {
        "record_id": record_id,
        "run_family_id": family or f"family-{task_id}-{execution_origin}-{repeat}",
        "revision": revision,
        "repeat": repeat,
        "task_id": task_id,
        "arm": arm,
        "primary": primary,
        "validity": validity,
        "execution_status": execution_status,
        "execution_origin": execution_origin,
        "status_reason": (
            "evidence invalid" if validity == "invalid" else
            "not run" if execution_status == "not_executed" else
            "environment unavailable" if execution_status == "environment_blocked" else None
        ) or ("execution has no terminal outcome" if delivery is None else None),
        "delivery": delivery,
        "first_attempt_success": first,
        "runtime": runtime,
        "repair": repair,
        "interventions": interventions,
        "cost": cost,
        "time_to_delivery_seconds": ttd,
        "failure_stage": failure_stage,
        "evidence_refs": [_ref(tmp_path, record_id)],
    }


def _ledger(task_ids, records):
    return {"schema": LEDGER_SCHEMA_VERSION, "registered_task_ids": task_ids, "records": records}


def test_registered_snapshot_is_not_a_final_rate_and_unknown_cost_is_not_zero(tmp_path):
    missing = _cost(complete=False, input_tokens=None, output_tokens=None, model_calls=None,
                    tool_calls=None, judge_calls=None, elapsed_seconds=None)
    records = [
        _record(tmp_path, "S1", delivery=True, first=True),
        _record(tmp_path, "S2", execution_status="not_executed", cost=missing),
        _record(tmp_path, "S3", execution_status="environment_blocked", cost=missing),
        # Invalidity is orthogonal to the retained raw outcome: this success is excluded.
        _record(tmp_path, "S4", validity="invalid", delivery=True, first=True),
    ]
    result = aggregate_outcome_ledger(_ledger(["S1", "S2", "S3", "S4"], records))
    assert result["registered_snapshot"]["status_counts"] == {
        "executed": 1, "not_executed": 1, "environment_blocked": 1, "invalid": 1}
    delivery = result["final_product_by_arm"]["candidate"]["delivery"]
    assert delivery["confirmed_true"] == 1 and delivery["unknown_count"] == 3
    assert delivery["observed_rate_among_known"] == 1
    assert delivery["final_rate"] is None and delivery["final_denominator"] is None
    tokens = result["final_product_by_arm"]["candidate"]["cost"]["metrics"]["input_tokens"]
    assert tokens["known_lower_bound"] == 20  # Includes the invalid attempt's known cost.
    assert tokens["complete_total"] is None
    per_success = result["final_product_by_arm"]["candidate"]["cost"]["cost_per_successful_delivery"]
    assert per_success["complete"] is False
    assert per_success["metrics"]["total_tokens"] is None


def test_complete_primary_cohort_reports_delivery_runtime_repair_intervention_and_cost(tmp_path):
    developer = {
        "developer": {"required": True, "count": 1},
        "user": {"required": False, "count": 0},
        "operational": {"required": False, "count": 0},
    }
    user = {
        "developer": {"required": False, "count": 0},
        "user": {"required": True, "count": 1},
        "operational": {"required": False, "count": 0},
    }
    records = [
        _record(tmp_path, "S1", delivery=True, first=False, ttd=12,
                runtime={"required": True, "executed": True, "passed": True},
                repair={"eligible": True, "attempted": True, "passed": True},
                interventions=developer, cost=_cost(input_tokens=100, output_tokens=20,
                                                     model_calls=4, elapsed_seconds=30)),
        _record(tmp_path, "S2", delivery=False, first=False, failure_stage="build",
                runtime={"required": True, "executed": False, "passed": False},
                repair={"eligible": True, "attempted": True, "passed": False},
                interventions=user, cost=_cost(input_tokens=50, output_tokens=10,
                                                model_calls=2, elapsed_seconds=20)),
    ]
    aggregate = aggregate_outcome_ledger(_ledger(["S1", "S2"], records))
    result = aggregate["final_product_by_arm"]["candidate"]
    assert result["delivery"]["final_rate"] == 0.5
    assert aggregate["first_registered_by_arm"]["candidate"][
        "first_attempt_success"]["final_rate"] == 0
    assert result["runtime_acceptance"]["final_rate"] == 0.5
    assert result["runtime_acceptance"]["required_but_not_executed"] == 1
    assert result["repair_recovery"]["final_rate"] == 0.5
    assert result["repair_recovery"]["denominator_kind"] == (
        "valid_executed_run_families_with_repair_attempted_true")
    assert result["intervention"]["by_kind"]["developer"]["final_rate"] == 0.5
    assert result["intervention"]["by_kind"]["user"]["final_rate"] == 0.5
    assert result["failure_stage"]["final_distribution"] == {"build": 1}
    assert result["time_to_delivery_seconds"]["final"]["mean"] == 12
    costs = result["cost"]
    assert costs["metrics"]["total_tokens"]["complete_total"] == 180
    assert costs["metrics"]["model_calls"]["complete_total"] == 6
    assert costs["cost_per_successful_delivery"]["metrics"]["total_tokens"] == 180


def test_runtime_required_but_not_run_cannot_claim_pass(tmp_path):
    record = _record(tmp_path, "S1", delivery=False,
                     runtime={"required": True, "executed": False, "passed": True})
    with pytest.raises(ValueError, match="R7:.*Runtime pass requires"):
        aggregate_outcome_ledger(_ledger(["S1"], [record]))


def test_developer_assisted_delivery_is_visible_but_excluded_from_primary_score(tmp_path):
    primary = _record(tmp_path, "S1", delivery=False, first=False)
    interventions = {
        "developer": {"required": True, "count": 1},
        "user": {"required": False, "count": 0},
        "operational": {"required": False, "count": 0},
    }
    assisted = _record(tmp_path, "S1", record_id="S1-assisted", family="S1-assisted",
                       repeat=1, primary=False, execution_origin="developer_assisted",
                       delivery=True, first=False, interventions=interventions)
    result = aggregate_outcome_ledger(_ledger(["S1"], [primary, assisted]))
    assert result["final_product_by_arm"]["candidate"]["delivery"]["final_rate"] == 0
    assisted_scope = result["by_scope"]["developer_assisted"]["candidate"]
    assert assisted_scope["task_arm_delivery"]["confirmed_successes"] == 1


def test_repeats_do_not_add_independent_tasks_or_more_than_one_task_arm_success(tmp_path):
    first = _record(tmp_path, "S1", delivery=True, first=True)
    repeat = _record(tmp_path, "S1", record_id="S1-repeat2", family="S1-repeat2",
                     repeat=2, primary=False, delivery=True, first=True)
    scope = aggregate_outcome_ledger(_ledger(["S1"], [first, repeat]))[
        "by_scope"]["product"]["candidate"]
    assert scope["registered_run_family_count"] == 2
    assert scope["independent_task_count"] == 1
    assert scope["task_arm_delivery"]["confirmed_successes"] == 1
    assert scope["task_arm_delivery"]["registered_task_arm_denominator"] == 1


@pytest.mark.parametrize(
    ("first_validity", "first_status", "first_delivery", "second_delivery", "expected"),
    [
        ("valid", "environment_blocked", None, False, 0),
        ("invalid", "executed", True, True, 1),
        ("valid", "executed", True, False, 0),
    ],
)
def test_final_task_arm_uses_latest_valid_terminal_not_earlier_tail(
        tmp_path, first_validity, first_status, first_delivery, second_delivery, expected):
    first = _record(tmp_path, "S1", record_id="S1-attempt1", family="S1-attempt1",
                    repeat=1, validity=first_validity, execution_status=first_status,
                    delivery=first_delivery, first=first_delivery)
    second = _record(tmp_path, "S1", record_id="S1-attempt2", family="S1-attempt2",
                     repeat=2, primary=False, delivery=second_delivery,
                     first=False, failure_stage="build")
    result = aggregate_outcome_ledger(_ledger(["S1"], [first, second]))
    final = result["final_product_by_arm"]["candidate"]["delivery"]
    assert final["final_rate"] == expected
    assert final["confirmed_true"] == expected
    # Both attempt families remain in all-in cost even when the first outcome is unusable.
    assert result["final_product_by_arm"]["candidate"]["cost"][
        "metrics"]["input_tokens"]["complete_total"] == 20


def test_latest_revision_corrects_invalid_delivery_and_repair_denominator_is_run_family(tmp_path):
    original = _record(tmp_path, "S1", record_id="old", family="shared", revision=1,
                       delivery=True, first=False,
                       repair={"eligible": True, "attempted": True, "passed": True})
    invalidation = _record(tmp_path, "S1", record_id="invalid", family="shared", revision=2,
                           validity="invalid", delivery=True, first=False,
                           repair={"eligible": True, "attempted": True, "passed": True})
    invalid_result = aggregate_outcome_ledger(_ledger(["S1"], [original, invalidation]))
    assert invalid_result["registered_snapshot"]["superseded_revision_count"] == 1
    assert invalid_result["final_product_by_arm"]["candidate"]["delivery"]["confirmed_true"] == 0
    assert invalid_result["final_product_by_arm"]["candidate"]["delivery"]["final_rate"] is None

    correction = _record(tmp_path, "S1", record_id="corrected", family="shared", revision=3,
                         delivery=True, first=False,
                         repair={"eligible": True, "attempted": True, "passed": True})
    result = aggregate_outcome_ledger(_ledger(["S1"], [original, invalidation, correction]))
    assert result["registered_snapshot"]["superseded_revision_count"] == 2
    assert result["final_product_by_arm"]["candidate"]["delivery"]["confirmed_true"] == 1
    repair = result["by_scope"]["product"]["candidate"]["repair_recovery"]
    assert repair["registered_run_family_count"] == 1
    assert repair["observed_pass_denominator"] == 1
    assert repair["denominator_kind"] == (
        "valid_executed_run_families_with_repair_attempted_true")


def test_repair_rate_uses_entered_valid_families_and_reports_nonentered_and_tails(tmp_path):
    records = [
        _record(tmp_path, "S1", record_id="invalid-initial", family="invalid-initial",
                repeat=1, validity="invalid", delivery=False),
        _record(tmp_path, "S1", record_id="environment-tail", family="environment-tail",
                repeat=2, primary=False, execution_status="environment_blocked"),
        _record(tmp_path, "S1", record_id="not-executed-tail", family="not-executed-tail",
                repeat=3, primary=False, execution_status="not_executed"),
        _record(tmp_path, "S1", record_id="eligible-not-entered", family="eligible-not-entered",
                repeat=4, primary=False, delivery=False,
                repair={"eligible": True, "attempted": False, "passed": None}),
        _record(tmp_path, "S1", record_id="entered-repair", family="entered-repair",
                repeat=5, primary=False, delivery=True, first=False,
                repair={"eligible": True, "attempted": True, "passed": True}),
    ]
    repair = aggregate_outcome_ledger(_ledger(["S1"], records))[
        "final_product_by_arm"]["candidate"]["repair_recovery"]
    assert repair["registered_run_family_count"] == 5
    assert repair["entered_repair_denominator"] == 1
    assert repair["eligible_not_entered"] == 1
    assert repair["final_rate"] == 1
    assert repair["is_final"] is True
    assert repair["excluded_or_unresolved_by_status"] == {
        "invalid": 1, "environment_blocked": 1, "not_executed": 1}


def test_final_intervention_rate_excludes_invalid_and_preexecution_events(tmp_path):
    invalid_intervention = {
        "developer": {"required": True, "count": 5},
        "user": {"required": False, "count": 0},
        "operational": {"required": False, "count": 0},
    }
    preexecution_intervention = {
        "developer": {"required": False, "count": 0},
        "user": {"required": True, "count": 3},
        "operational": {"required": False, "count": 0},
    }
    product_intervention = {
        "developer": {"required": False, "count": 0},
        "user": {"required": False, "count": 0},
        "operational": {"required": True, "count": 2},
    }
    records = [
        _record(tmp_path, "S1", record_id="invalid-preparation", family="invalid-preparation",
                repeat=1, validity="invalid", delivery=True,
                interventions=invalid_intervention),
        _record(tmp_path, "S1", record_id="unexecuted-preparation", family="unexecuted-preparation",
                repeat=2, primary=False, execution_status="not_executed",
                interventions=preexecution_intervention),
        _record(tmp_path, "S1", record_id="valid-product", family="valid-product",
                repeat=3, primary=False, delivery=True, first=False,
                interventions=product_intervention),
    ]
    final = aggregate_outcome_ledger(_ledger(["S1"], records))[
        "final_product_by_arm"]["candidate"]
    assert final["intervention"]["by_kind"]["developer"]["final_rate"] == 0
    assert final["intervention"]["by_kind"]["user"]["final_rate"] == 0
    assert final["intervention"]["by_kind"]["operational"]["final_rate"] == 1
    excluded = final["excluded_preexecution_intervention_events"]
    assert excluded["excluded_run_family_count"] == 2
    assert excluded["excluded_by_status"] == {"invalid": 1, "not_executed": 1}
    assert excluded["by_kind"]["developer"]["known_lower_bound"] == 5
    assert excluded["by_kind"]["user"]["known_lower_bound"] == 3
    assert excluded["known_event_lower_bound"] == 8


def test_evidence_byte_verification_is_separate_and_detects_drift(tmp_path):
    record = _record(tmp_path, "S1", delivery=True, first=True)
    ledger = _ledger(["S1"], [record])
    snapshot = deepcopy(ledger)
    assert verify_evidence_references(ledger) == {
        "status": "verified", "record_count": 1,
        "reference_occurrences": 1, "distinct_reference_count": 1}
    assert ledger == snapshot
    evidence = record["evidence_refs"][0]
    with open(evidence["path"], "wb") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="R12:.*hash mismatch"):
        verify_evidence_references(ledger)


def test_every_published_schema_rule_explains_why_it_exists():
    assert SCHEMA_RULES
    assert all(rule["why"].startswith("为什么要有它：") for rule in SCHEMA_RULES)


def test_two_arm_registry_has_task_denominator_and_task_arm_slot_denominator(tmp_path):
    records = []
    for task_id in ("S1", "S2"):
        records.append(_record(tmp_path, task_id, arm="baseline", delivery=False,
                               record_id=f"{task_id}-baseline", family=f"{task_id}-baseline"))
        records.append(_record(tmp_path, task_id, arm="candidate", delivery=True, first=True,
                               record_id=f"{task_id}-candidate", family=f"{task_id}-candidate"))
    result = aggregate_outcome_ledger(_ledger(["S1", "S2"], records))
    assert result["registered_snapshot"]["registered_task_count"] == 2
    assert result["registered_snapshot"]["registered_slot_count"] == 4
    assert set(result["first_registered_by_arm"]) == {"baseline", "candidate"}
    assert result["final_product_by_arm"]["baseline"]["delivery"]["final_rate"] == 0
    assert result["final_product_by_arm"]["candidate"]["delivery"]["final_rate"] == 1
    with pytest.raises(ValueError, match="R2:.*same non-empty primary arm set"):
        aggregate_outcome_ledger(_ledger(["S1", "S2"], records[:-1]))


def test_nonterminal_execution_and_required_runtime_not_run_remain_unknown_not_zero(tmp_path):
    record = _record(tmp_path, "S1", delivery=None, first=None,
                     runtime={"required": True, "executed": False, "passed": False})
    result = aggregate_outcome_ledger(_ledger(["S1"], [record]))[
        "final_product_by_arm"]["candidate"]
    assert result["delivery"]["observed_denominator"] == 0
    assert result["delivery"]["final_rate"] is None
    assert result["runtime_acceptance"]["required_but_not_executed"] == 1


def test_valid_not_executed_can_retain_runtime_requirement_without_claiming_pass(tmp_path):
    record = _record(tmp_path, "S1", execution_status="not_executed",
                     runtime={"required": True, "executed": False, "passed": False})
    result = aggregate_outcome_ledger(_ledger(["S1"], [record]))[
        "final_product_by_arm"]["candidate"]
    assert result["runtime_acceptance"]["required_but_not_executed"] == 1
    assert result["runtime_acceptance"]["confirmed_passed"] == 0
    assert result["runtime_acceptance"]["final_rate"] is None
