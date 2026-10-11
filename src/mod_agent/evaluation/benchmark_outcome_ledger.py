"""Read-only aggregation for registered, task-level Product outcome ledgers.

The ledger is append-only at the record level.  A ``run_family_id`` may have
multiple revisions, but only its latest revision contributes to a snapshot.
This lets a later record invalidate or correct an earlier claim without
rewriting the original evidence.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

LEDGER_SCHEMA_VERSION = "benchmark-outcome-ledger.v1"
SUMMARY_SCHEMA_VERSION = "benchmark-outcome-summary.v1"

VALIDITIES = {"valid", "invalid"}
EXECUTION_STATUSES = {"executed", "not_executed", "environment_blocked"}
EXECUTION_ORIGINS = {"product", "developer_assisted"}
INTERVENTION_KINDS = ("developer", "user", "operational")
COST_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "model_calls",
    "provider_sends",
    "tool_calls",
    "source_retrieval_calls",
    "judge_calls",
    "retry_count",
    "elapsed_seconds",
    "human_wait_seconds",
)


# This is part of the public contract, not merely implementation commentary.
# Every rule carries its reason so reports can explain why a record was rejected.
SCHEMA_RULES = (
    {
        "id": "R1",
        "rule": "The ledger and every record use one exact versioned shape.",
        "why": "为什么要有它：缺字段、拼写漂移或混用版本不能被静默解释成零或失败。",
    },
    {
        "id": "R2",
        "rule": "Each registered task has one Product primary run family in every registered arm.",
        "why": "为什么要有它：冻结分母必须是任务×臂槽位，重复运行不能增加独立任务数。",
    },
    {
        "id": "R3",
        "rule": "Run-family identity is immutable and only its greatest revision is current.",
        "why": "为什么要有它：更正应保留历史，同时不能让修订次数膨胀交付或 Repair 分母。",
    },
    {
        "id": "R4",
        "rule": "Validity, execution status, outcome and execution origin are independent fields.",
        "why": "为什么要有它：无效证据、未执行、环境阻塞、失败和开发者辅助是不同事实。",
    },
    {
        "id": "R5",
        "rule": "Only valid executed records can contribute Product outcome metrics.",
        "why": "为什么要有它：无效或未运行记录中的成功声明不能变成产品成绩。",
    },
    {
        "id": "R6",
        "rule": "Delivery and first-attempt success remain nullable and logically ordered.",
        "why": "为什么要有它：未知不能转成失败，首次成功也不能超过最终交付。",
    },
    {
        "id": "R7",
        "rule": "Runtime requirement, execution and pass are recorded separately.",
        "why": "为什么要有它：需要 Runtime 却未运行的任务绝不能被统计为 Runtime 通过。",
    },
    {
        "id": "R8",
        "rule": "Repair eligibility, entry and pass are recorded per run family; only entered repairs form the pass denominator.",
        "why": "为什么要有它：Recovery 分母应是真正进入修订的有效运行族，不是 revision、未进入修订的任务或环境尾迹。",
    },
    {
        "id": "R9",
        "rule": "Developer, user and operational interventions have separate nullable counts.",
        "why": "为什么要有它：三类介入对自主性的含义不同，缺测也不能冒充零介入。",
    },
    {
        "id": "R10",
        "rule": "A complete cost row supplies every cost field; partial rows retain known values.",
        "why": "为什么要有它：完整成本和已知下界必须并存，失败得早不能伪装成节省成本。",
    },
    {
        "id": "R11",
        "rule": "Time-to-delivery and terminal failure stage follow the final delivery outcome.",
        "why": "为什么要有它：失败没有交付耗时，成功也没有终态失败阶段。",
    },
    {
        "id": "R12",
        "rule": "Every revision has exact absolute local evidence references and SHA-256 values.",
        "why": "为什么要有它：快照必须能回到不可混淆的原始证据，路径或内容漂移要失败关闭。",
    },
    {
        "id": "R13",
        "rule": "Final rates require the whole registered primary cohort to be resolved.",
        "why": "为什么要有它：registered snapshot 可以随时看，但十题未完成时不能发布 final rate。",
    },
    {
        "id": "R14",
        "rule": "Final task-arm outcome uses the greatest-repeat valid terminal run family.",
        "why": "为什么要有它：早期无效或环境尾迹不应遮蔽修正结果，早期成功也不能永久遮蔽后续正式回归失败。",
    },
    {
        "id": "R15",
        "rule": "Final intervention rates use valid executed Product attempts; pre-execution events are reported separately.",
        "why": "为什么要有它：无效记录和准备期人工操作不能污染产品自主性，但其实际成本也不能被丢弃。",
    },
)

_RULES = {row["id"]: row for row in SCHEMA_RULES}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_LEDGER_KEYS = {"schema", "registered_task_ids", "records"}
_RECORD_KEYS = {
    "record_id",
    "run_family_id",
    "revision",
    "repeat",
    "task_id",
    "arm",
    "primary",
    "validity",
    "execution_status",
    "execution_origin",
    "status_reason",
    "delivery",
    "first_attempt_success",
    "runtime",
    "repair",
    "interventions",
    "cost",
    "time_to_delivery_seconds",
    "failure_stage",
    "evidence_refs",
}


def _fail(rule_id: str, detail: str) -> None:
    rule = _RULES[rule_id]
    raise ValueError(f"{rule_id}: {detail} {rule['why']}")


def _is_bool_or_none(value: object) -> bool:
    return value is None or type(value) is bool


def _is_nonnegative_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _is_nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _require_exact_keys(value: object, keys: set[str], rule_id: str, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        _fail(rule_id, f"{label} keys must be exactly {sorted(keys)}.")
    return value


def validate_evidence_reference(reference: object) -> None:
    """Validate reference shape without reading the referenced bytes."""
    value = _require_exact_keys(reference, {"path", "sha256"}, "R12", "Evidence reference")
    path, digest = value["path"], value["sha256"]
    if not isinstance(path, str) or not path or path.startswith(("\\\\", "//")):
        _fail("R12", "Evidence paths must be non-network local strings.")
    if not Path(path).is_absolute():
        _fail("R12", "Evidence paths must be absolute.")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        _fail("R12", "Evidence sha256 must be 64 lowercase hexadecimal characters.")


def _validate_measurement(measurement: object, *, label: str) -> None:
    value = _require_exact_keys(measurement, {"required", "count"}, "R9", label)
    required, count = value["required"], value["count"]
    if not _is_bool_or_none(required):
        _fail("R9", f"{label}.required must be true, false or null.")
    if count is not None and not _is_nonnegative_int(count):
        _fail("R9", f"{label}.count must be a nonnegative integer or null.")
    if required is False and count != 0:
        _fail("R9", f"{label} known false requires an explicit zero count.")
    if required is True and (count is None or count < 1):
        _fail("R9", f"{label} known true requires a positive count.")
    if required is None and count is not None:
        _fail("R9", f"{label} unknown cannot carry a count.")


def _validate_record(record: object, registered: set[str]) -> Mapping[str, Any]:
    row = _require_exact_keys(record, _RECORD_KEYS, "R1", "Ledger record")
    for key in ("record_id", "run_family_id", "task_id", "arm"):
        if not isinstance(row[key], str) or not row[key]:
            _fail("R1", f"{key} must be a non-empty string.")
    if row["task_id"] not in registered:
        _fail("R2", f"Unknown task_id {row['task_id']!r}.")
    if type(row["revision"]) is not int or row["revision"] < 1:
        _fail("R3", "revision must be a positive integer.")
    if type(row["repeat"]) is not int or row["repeat"] < 1:
        _fail("R3", "repeat must be a positive integer.")
    if type(row["primary"]) is not bool:
        _fail("R2", "primary must be a boolean.")
    if row["validity"] not in VALIDITIES:
        _fail("R4", f"Unsupported validity {row['validity']!r}.")
    if row["execution_status"] not in EXECUTION_STATUSES:
        _fail("R4", f"Unsupported execution_status {row['execution_status']!r}.")
    if row["execution_origin"] not in EXECUTION_ORIGINS:
        _fail("R4", f"Unsupported execution_origin {row['execution_origin']!r}.")
    reason = row["status_reason"]
    reason_required = (
        row["validity"] == "invalid"
        or row["execution_status"] != "executed"
        or row["delivery"] is None
    )
    if reason_required and (not isinstance(reason, str) or not reason):
        _fail("R4", "Invalid, unexecuted, environment-blocked and nonterminal records require status_reason.")
    if not reason_required and reason is not None:
        _fail("R4", "A valid executed record has no status_reason.")
    if not _is_bool_or_none(row["delivery"]) or not _is_bool_or_none(row["first_attempt_success"]):
        _fail("R6", "delivery and first_attempt_success must be true, false or null.")

    runtime = _require_exact_keys(row["runtime"], {"required", "executed", "passed"}, "R7", "runtime")
    if not all(_is_bool_or_none(runtime[key]) for key in runtime):
        _fail("R7", "Runtime fields must be true, false or null.")
    repair = _require_exact_keys(row["repair"], {"eligible", "attempted", "passed"}, "R8", "repair")
    if not all(_is_bool_or_none(repair[key]) for key in repair):
        _fail("R8", "Repair fields must be true, false or null.")

    interventions = _require_exact_keys(
        row["interventions"], set(INTERVENTION_KINDS), "R9", "interventions"
    )
    for kind in INTERVENTION_KINDS:
        _validate_measurement(interventions[kind], label=f"interventions.{kind}")

    cost = _require_exact_keys(row["cost"], {"complete", *COST_FIELDS}, "R10", "cost")
    if type(cost["complete"]) is not bool:
        _fail("R10", "cost.complete must be a boolean.")
    for key in COST_FIELDS:
        value = cost[key]
        if value is not None and not _is_nonnegative_number(value):
            _fail("R10", f"cost.{key} must be a finite nonnegative number or null.")
        if key not in {"elapsed_seconds", "human_wait_seconds"} and type(value) is float and not value.is_integer():
            _fail("R10", f"cost.{key} must be an integer count when it is known.")
    if cost["complete"] and any(cost[key] is None for key in COST_FIELDS):
        _fail("R10", "A complete cost row cannot omit a cost field.")

    ttd = row["time_to_delivery_seconds"]
    if ttd is not None and not _is_nonnegative_number(ttd):
        _fail("R11", "time_to_delivery_seconds must be finite and nonnegative or null.")
    stage = row["failure_stage"]
    if stage is not None and (not isinstance(stage, str) or not stage):
        _fail("R11", "failure_stage must be a non-empty string or null.")

    references = row["evidence_refs"]
    if not isinstance(references, list) or not references:
        _fail("R12", "Every record requires at least one evidence reference.")
    seen_refs: set[tuple[str, str]] = set()
    for reference in references:
        validate_evidence_reference(reference)
        identity = (reference["path"], reference["sha256"])
        if identity in seen_refs:
            _fail("R12", "A record cannot repeat the same evidence reference.")
        seen_refs.add(identity)

    # Invalid records retain raw outcome/autonomy claims for audit.  Logical
    # outcome rules apply only when evidence validity says the record is usable.
    if row["validity"] == "valid":
        if row["execution_status"] != "executed":
            if row["delivery"] is not None or row["first_attempt_success"] is not None:
                _fail("R5", "A valid non-executed record cannot claim a Product outcome.")
            if repair != {"eligible": None, "attempted": None, "passed": None}:
                _fail("R8", "A valid non-executed record has no Repair outcome.")
            if runtime["required"] is True and not (
                runtime["executed"] is False and runtime["passed"] is False
            ):
                _fail("R7", "Required Runtime on a non-executed task must record not-executed and not-passed.")
        if row["first_attempt_success"] is True and row["delivery"] is not True:
            _fail("R6", "First-attempt success requires final delivery.")
        if runtime["required"] is False and (runtime["executed"] is not False or runtime["passed"] is not None):
            _fail("R7", "Runtime not required must be explicit not-executed with no pass value.")
        if runtime["required"] is None and (runtime["executed"] is not None or runtime["passed"] is not None):
            _fail("R7", "Unknown Runtime applicability cannot imply execution or pass.")
        if runtime["passed"] is True and not (runtime["required"] is True and runtime["executed"] is True):
            _fail("R7", "Runtime pass requires both required=true and executed=true.")
        if runtime["required"] is True and runtime["executed"] is False and runtime["passed"] is not False:
            _fail("R7", "A required but unexecuted Runtime must be recorded as not passed.")
        if row["delivery"] is True and runtime["required"] is True and not (
            runtime["executed"] is True and runtime["passed"] is True
        ):
            _fail("R7", "Delivery cannot pass while required Runtime acceptance did not pass.")
        if repair["eligible"] is False and (repair["attempted"] is not False or repair["passed"] is not None):
            _fail("R8", "Repair ineligible must be explicit not-attempted with no pass value.")
        if repair["eligible"] is None and (repair["attempted"] is not None or repair["passed"] is not None):
            _fail("R8", "Unknown Repair eligibility cannot imply an attempt or pass.")
        if repair["passed"] is True and not (
            repair["eligible"] is True
            and repair["attempted"] is True
            and row["delivery"] is True
            and row["first_attempt_success"] is False
        ):
            _fail("R8", "Repair pass requires an eligible attempted recovery after first-attempt failure and delivery.")
        if row["first_attempt_success"] is True and repair["eligible"] is not False:
            _fail("R8", "First-attempt success is not Repair-eligible.")
        if row["delivery"] is True and row["failure_stage"] is not None:
            _fail("R11", "A delivered outcome cannot have a terminal failure_stage.")
        if row["delivery"] is not True and row["time_to_delivery_seconds"] is not None:
            _fail("R11", "Only a delivered outcome can have time_to_delivery_seconds.")
        if row["delivery"] is not False and row["failure_stage"] is not None:
            _fail("R11", "Only a failed outcome can have a terminal failure_stage.")
        if row["execution_origin"] == "developer_assisted" and interventions["developer"]["required"] is not True:
            _fail("R9", "Developer-assisted execution requires a positive developer intervention record.")
    return row


def validate_outcome_ledger(ledger: object) -> None:
    """Validate the versioned ledger without opening any evidence reference."""
    value = _require_exact_keys(ledger, _LEDGER_KEYS, "R1", "Ledger")
    if value["schema"] != LEDGER_SCHEMA_VERSION:
        _fail("R1", f"Unsupported ledger schema {value['schema']!r}.")
    task_ids = value["registered_task_ids"]
    if not isinstance(task_ids, list) or not task_ids:
        _fail("R2", "registered_task_ids must be a non-empty list.")
    if any(not isinstance(task_id, str) or not task_id for task_id in task_ids):
        _fail("R2", "Every registered task ID must be a non-empty string.")
    if len(set(task_ids)) != len(task_ids):
        _fail("R2", "Registered task IDs must be unique.")
    records = value["records"]
    if not isinstance(records, list) or not records:
        _fail("R1", "records must be a non-empty list.")

    registered = set(task_ids)
    validated = [_validate_record(record, registered) for record in records]
    record_ids: set[str] = set()
    revision_ids: set[tuple[str, int]] = set()
    path_hashes: dict[str, str] = {}
    families: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in validated:
        if row["record_id"] in record_ids:
            _fail("R3", f"Duplicate record_id {row['record_id']!r}.")
        record_ids.add(row["record_id"])
        revision_identity = (row["run_family_id"], row["revision"])
        if revision_identity in revision_ids:
            _fail("R3", f"Duplicate run-family revision {revision_identity!r}.")
        revision_ids.add(revision_identity)
        families[row["run_family_id"]].append(row)
        for reference in row["evidence_refs"]:
            previous = path_hashes.setdefault(reference["path"], reference["sha256"])
            if previous != reference["sha256"]:
                _fail("R12", f"Evidence path {reference['path']!r} has conflicting hashes.")

    immutable_keys = ("task_id", "arm", "execution_origin", "repeat", "primary")
    slots: set[tuple[str, str, str, int]] = set()
    latest: list[Mapping[str, Any]] = []
    for family_id, revisions in families.items():
        identity = tuple(revisions[0][key] for key in immutable_keys)
        if any(tuple(row[key] for key in immutable_keys) != identity for row in revisions[1:]):
            _fail("R3", f"Run family {family_id!r} changed immutable identity.")
        slot = identity[:3] + (identity[3],)
        if slot in slots:
            _fail("R3", f"Two run families occupy task/arm/origin/repeat slot {slot!r}.")
        slots.add(slot)
        latest.append(max(revisions, key=lambda row: row["revision"]))

    primary_by_task: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    primary_slots: set[tuple[str, str]] = set()
    for row in latest:
        if row["primary"]:
            if row["execution_origin"] != "product":
                _fail("R2", "Developer-assisted run families cannot be primary Product outcomes.")
            slot = (row["task_id"], row["arm"])
            if slot in primary_slots:
                _fail("R2", f"Primary task/arm slot {slot!r} has more than one run family.")
            primary_slots.add(slot)
            primary_by_task[row["task_id"]].append(row)
    arm_sets = [{row["arm"] for row in primary_by_task[task_id]} for task_id in task_ids]
    if any(not arms for arms in arm_sets) or any(arms != arm_sets[0] for arms in arm_sets[1:]):
        _fail("R2", "Every registered task must have exactly the same non-empty primary arm set.")


def _latest_records(ledger: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], int]:
    families: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in ledger["records"]:
        families[row["run_family_id"]].append(row)
    latest = [max(rows, key=lambda row: row["revision"]) for rows in families.values()]
    return latest, len(ledger["records"]) - len(latest)


def verify_evidence_references(ledger: object) -> dict[str, Any]:
    """Read and hash every distinct evidence reference after schema validation."""
    validate_outcome_ledger(ledger)
    references: dict[tuple[str, str], Mapping[str, str]] = {}
    occurrences = 0
    for row in ledger["records"]:
        for reference in row["evidence_refs"]:
            occurrences += 1
            references[(reference["path"], reference["sha256"])] = reference
    for reference in references.values():
        path = Path(reference["path"])
        try:
            raw = path.read_bytes()
        except OSError as error:
            _fail("R12", f"Cannot read evidence {path}: {type(error).__name__}: {error}")
        if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
            _fail("R12", f"Evidence hash mismatch: {path}")
    return {
        "status": "verified",
        "record_count": len(ledger["records"]),
        "reference_occurrences": occurrences,
        "distinct_reference_count": len(references),
    }


def _classified_status(row: Mapping[str, Any]) -> str:
    return "invalid" if row["validity"] == "invalid" else row["execution_status"]


def _status_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    observed = Counter(_classified_status(row) for row in rows)
    return {
        status: observed.get(status, 0)
        for status in ("executed", "not_executed", "environment_blocked", "invalid")
    }


def _usable(row: Mapping[str, Any]) -> bool:
    return row["validity"] == "valid" and row["execution_status"] == "executed"


def _boolean_metric(
    rows: Sequence[Mapping[str, Any]],
    value: Callable[[Mapping[str, Any]], bool | None],
    *,
    cohort_complete: bool,
) -> dict[str, Any]:
    known = [value(row) for row in rows if _usable(row) and type(value(row)) is bool]
    true_count = sum(item is True for item in known)
    unknown_rows = [row for row in rows if not (_usable(row) and type(value(row)) is bool)]
    complete = cohort_complete and not unknown_rows
    return {
        "confirmed_true": true_count,
        "confirmed_false": sum(item is False for item in known),
        "observed_denominator": len(known),
        "registered_denominator": len(rows),
        "unknown_count": len(unknown_rows),
        "unknown_by_status": dict(Counter(_classified_status(row) for row in unknown_rows)),
        "observed_rate_among_known": true_count / len(known) if known else None,
        "final_numerator": true_count if complete else None,
        "final_denominator": len(rows) if complete else None,
        "final_rate": true_count / len(rows) if complete and rows else None,
        "is_final": complete,
    }


def _conditional_pass_metric(
    rows: Sequence[Mapping[str, Any]],
    section: str,
    eligibility_key: str,
    *,
    cohort_complete: bool,
) -> dict[str, Any]:
    eligibility_known = [
        row for row in rows if _usable(row) and type(row[section][eligibility_key]) is bool
    ]
    eligible = [row for row in eligibility_known if row[section][eligibility_key] is True]
    passes = [row[section]["passed"] for row in eligible if type(row[section]["passed"]) is bool]
    unknown_eligibility = len(rows) - len(eligibility_known)
    unknown_pass = len(eligible) - len(passes)
    complete = cohort_complete and unknown_eligibility == 0 and unknown_pass == 0
    passed = sum(value is True for value in passes)
    result = {
        "registered_denominator": len(rows),
        "confirmed_eligible": len(eligible),
        "confirmed_not_eligible": len(eligibility_known) - len(eligible),
        "unknown_eligibility": unknown_eligibility,
        "confirmed_passed": passed,
        "confirmed_failed": sum(value is False for value in passes),
        "observed_pass_denominator": len(passes),
        "unknown_pass_among_eligible": unknown_pass,
        "observed_pass_rate_among_known": passed / len(passes) if passes else None,
        "final_numerator": passed if complete else None,
        "final_denominator": len(eligible) if complete else None,
        "final_rate": passed / len(eligible) if complete and eligible else None,
        "is_final": complete,
    }
    if section == "runtime":
        result["required_but_not_executed"] = sum(
            row["runtime"]["required"] is True and row["runtime"]["executed"] is False
            for row in rows if row["validity"] == "valid"
        )
    return result


def _repair_recovery_metric(
    rows: Sequence[Mapping[str, Any]], *, cohort_complete: bool
) -> dict[str, Any]:
    usable = [row for row in rows if _usable(row)]
    entered = [row for row in usable if row["repair"]["attempted"] is True]
    pass_values = [
        row["repair"]["passed"] for row in entered
        if type(row["repair"]["passed"]) is bool
    ]
    unresolved_eligibility = sum(row["repair"]["eligible"] is None for row in usable)
    unresolved_entry = sum(
        row["repair"]["eligible"] is True and row["repair"]["attempted"] is None
        for row in usable
    )
    unknown_pass = len(entered) - len(pass_values)
    complete = (
        cohort_complete
        and unresolved_eligibility == 0
        and unresolved_entry == 0
        and unknown_pass == 0
    )
    passed = sum(value is True for value in pass_values)
    excluded = Counter(
        _classified_status(row) for row in rows if not _usable(row)
    )
    return {
        "denominator_kind": "valid_executed_run_families_with_repair_attempted_true",
        "registered_run_family_count": len(rows),
        "valid_executed_run_family_count": len(usable),
        "confirmed_eligible": sum(row["repair"]["eligible"] is True for row in usable),
        "confirmed_not_eligible": sum(row["repair"]["eligible"] is False for row in usable),
        "eligible_not_entered": sum(
            row["repair"]["eligible"] is True and row["repair"]["attempted"] is False
            for row in usable
        ),
        "unresolved_eligibility": unresolved_eligibility,
        "unresolved_entry": unresolved_entry,
        "entered_repair_denominator": len(entered),
        "confirmed_passed": passed,
        "confirmed_failed": sum(value is False for value in pass_values),
        "observed_pass_denominator": len(pass_values),
        "unknown_pass_among_entered": unknown_pass,
        "excluded_or_unresolved_by_status": {
            status: excluded.get(status, 0)
            for status in ("invalid", "environment_blocked", "not_executed")
        },
        "observed_pass_rate_among_known": passed / len(pass_values) if pass_values else None,
        "final_numerator": passed if complete else None,
        "final_denominator": len(entered) if complete else None,
        "final_rate": passed / len(entered) if complete and entered else None,
        "is_final": complete,
    }


def _distribution(values: Sequence[float | int]) -> dict[str, Any]:
    ordered = sorted(values)
    if not ordered:
        return {
            "count": 0,
            "mean": None,
            "p50": None,
            "p95": None,
            "minimum": None,
            "maximum": None,
        }
    return {
        "count": len(ordered),
        "mean": sum(ordered) / len(ordered),
        "p50": ordered[math.ceil(len(ordered) * 0.50) - 1],
        "p95": ordered[math.ceil(len(ordered) * 0.95) - 1],
        "minimum": ordered[0],
        "maximum": ordered[-1],
    }


def _time_to_delivery(
    rows: Sequence[Mapping[str, Any]], delivery: Mapping[str, Any]
) -> dict[str, Any]:
    successful = [row for row in rows if _usable(row) and row["delivery"] is True]
    known = [row["time_to_delivery_seconds"] for row in successful if row["time_to_delivery_seconds"] is not None]
    complete = delivery["is_final"] and len(known) == len(successful)
    return {
        "eligible_deliveries": len(successful),
        "known_count": len(known),
        "unknown_success_count": len(successful) - len(known),
        "observed": _distribution(known),
        "final": _distribution(known) if complete else None,
        "is_final": complete,
    }


def _failure_stages(
    rows: Sequence[Mapping[str, Any]], delivery: Mapping[str, Any]
) -> dict[str, Any]:
    failures = [row for row in rows if _usable(row) and row["delivery"] is False]
    known = [row["failure_stage"] for row in failures if row["failure_stage"] is not None]
    counts = dict(sorted(Counter(known).items()))
    complete = delivery["is_final"] and len(known) == len(failures)
    return {
        "confirmed_failure_denominator": len(failures),
        "known_stage_count": len(known),
        "unknown_stage_count": len(failures) - len(known),
        "observed_distribution": counts,
        "final_distribution": counts if complete else None,
        "is_final": complete,
    }


def _cost_metric(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    known: list[float | int] = []
    complete_values: list[float | int] = []
    complete = True
    for row in rows:
        value = row["cost"][key]
        if value is not None:
            known.append(value)
        if row["cost"]["complete"] is not True or value is None:
            complete = False
        else:
            complete_values.append(value)
    return {
        "known_lower_bound": sum(known) if known else None,
        "known_rows": len(known),
        "unknown_rows": len(rows) - len(known),
        "complete_total": sum(complete_values) if complete and rows else None,
        "is_complete": complete and bool(rows),
    }


def _total_tokens(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    known_components: list[float | int] = []
    fully_known_rows = 0
    complete = True
    totals: list[float | int] = []
    for row in rows:
        input_tokens, output_tokens = row["cost"]["input_tokens"], row["cost"]["output_tokens"]
        known_components.extend(value for value in (input_tokens, output_tokens) if value is not None)
        if input_tokens is not None and output_tokens is not None:
            fully_known_rows += 1
            totals.append(input_tokens + output_tokens)
        else:
            complete = False
        if row["cost"]["complete"] is not True:
            complete = False
    return {
        "known_component_lower_bound": sum(known_components) if known_components else None,
        "fully_known_rows": fully_known_rows,
        "unknown_rows": len(rows) - fully_known_rows,
        "complete_total": sum(totals) if complete and rows else None,
        "is_complete": complete and bool(rows),
    }


def _cost_summary(
    rows: Sequence[Mapping[str, Any]], delivery: Mapping[str, Any]
) -> dict[str, Any]:
    metrics = {key: _cost_metric(rows, key) for key in COST_FIELDS}
    metrics["total_tokens"] = _total_tokens(rows)
    valid_rows = [row for row in rows if row["validity"] == "valid"]
    valid_product_metrics = {key: _cost_metric(valid_rows, key) for key in COST_FIELDS}
    valid_product_metrics["total_tokens"] = _total_tokens(valid_rows)
    all_complete = bool(rows) and all(metric["is_complete"] for metric in metrics.values())
    successes = delivery["confirmed_true"] if delivery["is_final"] else None
    per_success_complete = all_complete and successes is not None and successes > 0
    per_success = {
        key: metric["complete_total"] / successes if per_success_complete else None
        for key, metric in metrics.items()
    }
    if not delivery["is_final"]:
        reason = "delivery_rate_not_final"
    elif not all_complete:
        reason = "included_attempt_cost_missing_or_invalid"
    elif not successes:
        reason = "no_successful_delivery"
    else:
        reason = None
    return {
        "scope": "all selected run-family attempt costs, including failed outcomes",
        "included_run_families": len(rows),
        "invalid_run_family_costs_included_in_all_attempt_lower_bound": sum(
            row["validity"] == "invalid" for row in rows
        ),
        "metrics": metrics,
        "valid_product_metrics": valid_product_metrics,
        "all_included_attempt_costs_complete": all_complete,
        "cost_per_successful_delivery": {
            "complete": per_success_complete,
            "successful_delivery_denominator": successes if per_success_complete else None,
            "metrics": per_success,
            "reason": reason,
        },
    }


def _intervention_summary(
    rows: Sequence[Mapping[str, Any]], *, cohort_complete: bool
) -> dict[str, Any]:
    by_kind: dict[str, Any] = {}
    for kind in INTERVENTION_KINDS:
        metric = _boolean_metric(
            rows,
            lambda row, kind=kind: row["interventions"][kind]["required"],
            cohort_complete=cohort_complete,
        )
        known_counts = [
            row["interventions"][kind]["count"]
            for row in rows
            if _usable(row) and row["interventions"][kind]["count"] is not None
        ]
        count_complete = cohort_complete and len(known_counts) == len(rows)
        metric["event_count"] = {
            "known_lower_bound": sum(known_counts) if known_counts else None,
            "known_rows": len(known_counts),
            "unknown_rows": len(rows) - len(known_counts),
            "complete_total": sum(known_counts) if count_complete else None,
            "is_final": count_complete,
        }
        by_kind[kind] = metric

    def any_required(row: Mapping[str, Any]) -> bool | None:
        values = [row["interventions"][kind]["required"] for kind in INTERVENTION_KINDS]
        if any(value is True for value in values):
            return True
        if all(value is False for value in values):
            return False
        return None

    return {
        "by_kind": by_kind,
        "any_intervention": _boolean_metric(rows, any_required, cohort_complete=cohort_complete),
    }


def _primary_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    cohort_complete = all(_usable(row) for row in rows)
    delivery = _boolean_metric(rows, lambda row: row["delivery"], cohort_complete=cohort_complete)
    return {
        "denominator_kind": "registered_independent_tasks",
        "registered_task_count": len(rows),
        "cohort_execution_complete": cohort_complete,
        "status_counts": _status_counts(rows),
        "delivery": delivery,
        "first_attempt_success": _boolean_metric(
            rows, lambda row: row["first_attempt_success"], cohort_complete=cohort_complete
        ),
        "runtime_acceptance": _conditional_pass_metric(
            rows, "runtime", "required", cohort_complete=cohort_complete
        ),
        "repair_recovery": _repair_recovery_metric(rows, cohort_complete=cohort_complete),
        "intervention": _intervention_summary(rows, cohort_complete=cohort_complete),
        "time_to_delivery_seconds": _time_to_delivery(rows, delivery),
        "failure_stage": _failure_stages(rows, delivery),
        "cost": _cost_summary(rows, delivery),
    }


def _task_arm_delivery(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_task: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_task[row["task_id"]].append(row)
    outcomes: list[bool | None] = []
    for family_rows in by_task.values():
        terminal = [
            row for row in family_rows
            if _usable(row) and type(row["delivery"]) is bool
        ]
        latest = max(terminal, key=lambda row: row["repeat"]) if terminal else None
        outcomes.append(latest["delivery"] if latest is not None else None)
    known = [value for value in outcomes if type(value) is bool]
    successes = sum(value is True for value in known)
    complete = len(known) == len(outcomes)
    return {
        "semantics": "latest valid terminal delivery by repeat per task arm; repeats never add successes",
        "confirmed_successes": successes,
        "confirmed_failures": sum(value is False for value in known),
        "observed_denominator": len(known),
        "registered_task_arm_denominator": len(outcomes),
        "unknown_count": len(outcomes) - len(known),
        "observed_rate_among_known": successes / len(known) if known else None,
        "final_rate": successes / len(outcomes) if complete and outcomes else None,
        "is_final": complete,
    }


def _combined_interventions(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [
        row for row in rows
        if _usable(row) and row["execution_origin"] == "product"
    ]
    combined: dict[str, Any] = {}
    for kind in INTERVENTION_KINDS:
        if not rows:
            combined[kind] = {"required": None, "count": None}
            continue
        required = [row["interventions"][kind]["required"] for row in rows]
        counts = [row["interventions"][kind]["count"] for row in rows]
        if any(value is True for value in required):
            combined_required = True
        elif all(value is False for value in required):
            combined_required = False
        else:
            combined_required = None
        combined[kind] = {
            "required": combined_required,
            "count": sum(counts) if all(value is not None for value in counts) else None,
        }
    return combined


def _excluded_preexecution_interventions(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    excluded = [
        row for row in rows
        if not (_usable(row) and row["execution_origin"] == "product")
    ]
    by_kind: dict[str, Any] = {}
    all_known: list[int] = []
    unknown_components = 0
    for kind in INTERVENTION_KINDS:
        values = [row["interventions"][kind]["count"] for row in excluded]
        known = [value for value in values if value is not None]
        all_known.extend(known)
        unknown_components += len(values) - len(known)
        by_kind[kind] = {
            "known_lower_bound": sum(known) if known else None,
            "known_rows": len(known),
            "unknown_rows": len(values) - len(known),
        }
    statuses = Counter(_classified_status(row) for row in excluded)
    return {
        "excluded_run_family_count": len(excluded),
        "excluded_by_status": dict(sorted(statuses.items())),
        "by_kind": by_kind,
        "known_event_lower_bound": sum(all_known) if all_known else None,
        "unknown_event_components": unknown_components,
    }


def _final_task_rows(
    rows: Sequence[Mapping[str, Any]], task_ids: Sequence[str]
) -> list[Mapping[str, Any]]:
    by_task: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_task[row["task_id"]].append(row)
    projected: list[Mapping[str, Any]] = []
    for task_id in task_ids:
        family_rows = sorted(by_task[task_id], key=lambda row: row["repeat"])
        terminal = [
            row for row in family_rows
            if _usable(row) and type(row["delivery"]) is bool
        ]
        chosen = max(terminal, key=lambda row: row["repeat"]) if terminal else family_rows[-1]
        projection = dict(chosen)
        projection["interventions"] = _combined_interventions(family_rows)
        projected.append(projection)
    return projected


def _final_product_summary(
    rows: Sequence[Mapping[str, Any]], task_ids: Sequence[str]
) -> dict[str, Any]:
    task_rows = _final_task_rows(rows, task_ids)
    cohort_complete = all(_usable(row) and type(row["delivery"]) is bool for row in task_rows)
    delivery = _boolean_metric(
        task_rows, lambda row: row["delivery"], cohort_complete=cohort_complete
    )
    return {
        "denominator_kind": "registered_independent_tasks_after_task_arm_collapse",
        "registered_task_count": len(task_rows),
        "registered_run_family_count": len(rows),
        "cohort_final_outcome_complete": cohort_complete,
        "task_status_counts": _status_counts(task_rows),
        "delivery": delivery,
        "runtime_acceptance": _conditional_pass_metric(
            task_rows, "runtime", "required", cohort_complete=cohort_complete
        ),
        "repair_recovery": _repair_recovery_metric(rows, cohort_complete=cohort_complete),
        "intervention": _intervention_summary(task_rows, cohort_complete=cohort_complete),
        "excluded_preexecution_intervention_events": _excluded_preexecution_interventions(rows),
        "time_to_delivery_seconds": _time_to_delivery(task_rows, delivery),
        "failure_stage": _failure_stages(task_rows, delivery),
        "cost": _cost_summary(rows, delivery),
    }


def _scope_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    task_delivery = _task_arm_delivery(rows)
    return {
        "registered_run_family_count": len(rows),
        "independent_task_count": len({row["task_id"] for row in rows}),
        "status_counts": _status_counts(rows),
        "task_arm_delivery": task_delivery,
        "repair_recovery": _repair_recovery_metric(
            rows, cohort_complete=task_delivery["is_final"]
        ),
        "cost": _cost_summary(rows, {
            "confirmed_true": task_delivery["confirmed_successes"],
            "is_final": task_delivery["is_final"],
        }),
    }


def aggregate_outcome_ledger(ledger: object) -> dict[str, Any]:
    """Validate and aggregate an in-memory ledger without reading or writing files."""
    validate_outcome_ledger(ledger)
    latest, superseded = _latest_records(ledger)
    primary = [row for row in latest if row["primary"]]
    primary_arms = sorted({row["arm"] for row in primary})
    primary_by_slot = {(row["task_id"], row["arm"]): row for row in primary}
    ordered_by_arm = {
        arm: [primary_by_slot[(task_id, arm)] for task_id in ledger["registered_task_ids"]]
        for arm in primary_arms
    }
    scopes: dict[str, dict[str, list[Mapping[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in latest:
        scopes[row["execution_origin"]][row["arm"]].append(row)
    by_scope = {
        origin: {arm: _scope_summary(rows) for arm, rows in sorted(arms.items())}
        for origin, arms in sorted(scopes.items())
    }
    primary_summaries = {
        arm: _primary_summary(rows) for arm, rows in ordered_by_arm.items()
    }
    final_summaries = {
        arm: _final_product_summary(
            [row for row in latest if row["execution_origin"] == "product" and row["arm"] == arm],
            ledger["registered_task_ids"],
        )
        for arm in primary_arms
    }
    return {
        "schema": SUMMARY_SCHEMA_VERSION,
        "source_schema": LEDGER_SCHEMA_VERSION,
        "schema_rules": [dict(rule) for rule in SCHEMA_RULES],
        "registered_snapshot": {
            "registered_task_ids": list(ledger["registered_task_ids"]),
            "registered_task_count": len(ledger["registered_task_ids"]),
            "primary_arms": primary_arms,
            "registered_slot_count": len(primary),
            "status_counts": _status_counts(primary),
            "ledger_record_count": len(ledger["records"]),
            "run_family_count": len(latest),
            "superseded_revision_count": superseded,
            "primary_final_delivery_available_by_arm": {
                arm: summary["delivery"]["is_final"] for arm, summary in final_summaries.items()
            },
        },
        "first_registered_by_arm": primary_summaries,
        "final_product_by_arm": final_summaries,
        "by_scope": by_scope,
    }


__all__ = [
    "COST_FIELDS",
    "EXECUTION_ORIGINS",
    "EXECUTION_STATUSES",
    "INTERVENTION_KINDS",
    "LEDGER_SCHEMA_VERSION",
    "SCHEMA_RULES",
    "SUMMARY_SCHEMA_VERSION",
    "VALIDITIES",
    "aggregate_outcome_ledger",
    "validate_evidence_reference",
    "validate_outcome_ledger",
    "verify_evidence_references",
]
