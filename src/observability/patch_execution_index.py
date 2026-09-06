"""Regenerable, non-authoritative index of retained Patch execution journals.

Only local files explicitly referenced by a journal are read. No worker, model,
validator, graph, Artifact write, network sink, or recovery operation is invoked.
Missing fields remain unknown; journal claims are not promoted to execution proof.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.mod_agent.artifacts.envelope import ArtifactRef
from src.mod_agent.artifacts.store import ArtifactStore
from src.mod_agent.fresh_planning_continuation import _canonical_sha256

MAX_FILE_BYTES = 16 * 1024 * 1024


def _object(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _fields(value: Mapping[str, Any], *names: str) -> dict[str, Any]:
    """Never include arbitrary diagnostic bodies, prompt text or source code."""
    return {name: value[name] for name in names if name in value
            and isinstance(value[name], (str, int, float, bool, type(None)))}


def _strings(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _journal_checks(journal: Mapping[str, Any]) -> dict[str, Any]:
    terminal = journal.get("terminal_result")
    expected = journal.get("terminal_result_sha256")
    terminal_status = "unknown_missing_terminal_or_hash"
    if isinstance(terminal, dict) and isinstance(expected, str):
        try:
            terminal_status = "verified" if _canonical_sha256(terminal) == expected else "hash_mismatch"
        except (TypeError, ValueError, UnicodeError):
            terminal_status = "invalid_terminal_encoding"
    return {
        "terminal_result_hash": {
            "status": terminal_status,
            "rule_owner": "fresh_planning_continuation._canonical_sha256",
        },
        "attempt_identity": {
            "status": "unverifiable", "reason": "original_request_definition_not_retained",
        },
        "scope": "individual_identity_checks_not_whole_run_or_semantic_validation",
    }


def _local_path(root: Path, raw: str) -> Path:
    path = Path(raw)
    if raw.startswith(("\\\\", "//")) or path.drive.startswith("\\\\"):
        raise ValueError("network_path_not_read")
    resolved = (path if path.is_absolute() else root / path).resolve()
    if resolved.drive.startswith("\\\\"):
        raise ValueError("network_path_not_read")
    return resolved


def _read_bytes(path: Path) -> bytes:
    with path.open("rb") as stream:
        value = stream.read(MAX_FILE_BYTES + 1)
    if len(value) > MAX_FILE_BYTES:
        raise ValueError("file_too_large")
    return value


def _json(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("object_required")
    return value


class _References:
    def __init__(self, root: Path):
        self.root = root
        self.store = ArtifactStore(root)
        self.cache: dict[tuple[str, str, str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
        self.unverifiable_references = 0

    def check(self, value: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        ref = _object(value)
        result = _fields(ref, "path", "artifact_hash", "artifact_type", "feature_id",
                         "sha256", "output_sha256")
        expected = ref.get("artifact_hash", ref.get("sha256", ref.get("output_sha256")))
        raw_path = ref.get("path")
        if not isinstance(raw_path, str) or not isinstance(expected, str):
            self.unverifiable_references += 1
            return {**result, "integrity": "unverifiable_reference"}, {}
        key = (raw_path, expected, str(ref.get("artifact_type", "file")), str(ref.get("feature_id", "")))
        if key in self.cache:
            checked, document = self.cache[key]
            return {**result, "integrity": checked["integrity"]}, document
        document: dict[str, Any] = {}
        try:
            path = _local_path(self.root, raw_path)
            raw = _read_bytes(path)
            if "artifact_hash" in ref:
                # Reuse the Store's envelope/hash checks without invoking writes.
                path.relative_to(self.root)
                document = self.store.read(ArtifactRef(
                    feature_id=ref["feature_id"], artifact_type=ref["artifact_type"],
                    path=str(path), artifact_hash=expected,
                ))
                integrity = "verified_artifact"
            elif hashlib.sha256(raw).hexdigest() != expected:
                integrity = "hash_mismatch"
            else:
                integrity = "verified_bytes"
                try:
                    document = _json(raw)
                except (UnicodeError, ValueError):
                    pass  # Raw model text is verified but never copied into the index.
        except FileNotFoundError:
            integrity = "missing"
        except (OSError, ValueError, KeyError, TypeError):
            integrity = "invalid_or_unreadable_reference"
        checked = {**result, "integrity": integrity}
        self.cache[key] = (checked, document)
        return checked, document


def _phases(loop: Mapping[str, Any]):
    yield "initial", loop
    for name in ("validator_correction", "behavior_correction"):
        execution = _object(_object(loop.get(name)).get("execution"))
        if execution:
            yield name, execution


def _turns(factory: Mapping[str, Any], refs: _References) -> list[dict[str, Any]]:
    result = []
    for turn in _rows(factory.get("worker_turns")):
        row = _fields(turn, "turn_index", "status", "request_sha256", "tool_choice",
                      "tool_action", "error_type")
        origin = turn.get("response_origin")
        row["response_origin"] = origin if origin in (
            "live_provider_response", "verified_prior_response") else "unknown"
        row["response_origin_basis"] = "journal_declaration"
        row["tools_available"] = _strings(turn.get("tools_available"))
        row["usage"] = _fields(_object(turn.get("usage")), "input_tokens", "output_tokens",
                               "total_tokens", "cached_input_tokens", "reasoning_tokens")
        diagnostic = _object(turn.get("provider_diagnostic"))
        row["provider_request_identity"] = _fields(
            _object(diagnostic.get("request_identity")),
            "hash_basis", "provider_body_sha256", "provider_body_utf8_bytes",
        )
        row["wire_identity_verification"] = "digest_recorded_not_wire_replayed"
        row["observation_request_links"] = []
        row["observation_delivery"] = "unknown_no_explicit_request_reference"
        response, document = refs.check(turn.get("response_ref"))
        row["response_ref"] = response
        if "original_response_ref" in turn:
            row["original_response_ref"] = refs.check(turn["original_response_ref"])[0]
        verified_response = response["integrity"] == "verified_bytes"
        verified_original = _object(row.get("original_response_ref")).get("integrity") == "verified_bytes"
        row["send_observation"] = "requested_send_unconfirmed"
        if origin in ("live_provider_response", "verified_prior_response"):
            row["send_observation"] = "unknown_response_evidence_unavailable"
            if turn.get("status") == "responded" and verified_response:
                if origin == "live_provider_response":
                    row["send_observation"] = "journal_claim_live_response_with_verified_ref"
                elif verified_original:
                    row["send_observation"] = "journal_claim_replay_with_verified_response_refs"
        row["send_observation_basis"] = "journal_claim_with_reference_checks_not_independent_send_proof"
        row["requested_tools"] = [{
            **_fields(call, "call_id", "name"),
            **_fields(_object(call.get("arguments")), "binding_id"),
        } for call in _rows(document.get("tool_calls"))]
        result.append(row)
    return result


def _tools(loop: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = []
    for phase, execution in _phases(loop):
        observations = _rows(execution.get("observation_trace"))
        for call in _rows(execution.get("tool_call_trace")):
            row = {"phase": phase, **_fields(
                call, "turn_index", "tool_call_id", "tool", "binding_id",
                "arguments_sha256", "status", "dispatch_started", "error_code",
            )}
            row["execution_observation"] = (
                "not_executed" if call.get("dispatch_started") is False else
                "dispatch_started" if call.get("dispatch_started") is True else "unknown"
            )
            row["returned_observations"] = [_fields(
                observation, "observation_id", "observation_sha256", "source_ref",
                "source_hash", "source_snapshot_sha256", "admitted_to_model",
                "model_payload_bytes",
            ) for observation in observations
                if isinstance(call.get("binding_id"), str)
                and observation.get("turn_index") == call.get("turn_index")
                and observation.get("binding_id") == call.get("binding_id")]
            row["delivery_verification"] = "journal_admission_only_not_wire_consumption"
            result.append(row)
    return result


def _evaluations(loop: Mapping[str, Any], refs: _References) -> list[dict[str, Any]]:
    result = []
    for evaluation in _rows(loop.get("behavior_evaluations")):
        row = _fields(evaluation, "evaluation_index", "status", "failure_owner", "admission",
                      "generated_changes_sha256", "model_response_sha256",
                      "source_snapshot_sha256", "verification_scope")
        row["report_ref"], report = refs.check(evaluation.get("report_ref"))
        row["verification_ref"] = refs.check(evaluation.get("verification_ref"))[0]
        origin = evaluation.get("execution_origin")
        row["execution_origin_recorded"] = origin if origin in (
            "executed", "reused", "unknown", "incomplete") else "unknown"
        row["callback_invoked"] = evaluation.get("callback_invoked") if isinstance(
            evaluation.get("callback_invoked"), bool) else None
        row["execution_observation"] = (
            row["execution_origin_recorded"]
            if row["report_ref"]["integrity"] == "verified_bytes" else "unknown"
        )
        row["execution_basis"] = "explicit_journal_field_with_retained_report_not_new_execution"
        identity = _object(evaluation.get("verification_identity"))
        row["verification_identity"] = _fields(
            identity, "validator_sha256", "inputs_sha256", "environment_sha256",
            "deterministic_reuse_allowed",
        )
        code = _object(evaluation.get("materialized_code_identity"))
        row["materialized_code_identity"] = {
            **_fields(code, "baseline_sha256", "code_sha256"), "files": _strings(code.get("files")),
        } if code else None
        row["code_identity_verification"] = "recorded_not_rematerialized"
        revision = _object(evaluation.get("code_revision"))
        row["code_revision"] = {
            "declaration_status": "recorded" if revision else "unknown",
            "comparison_verification": "journal_declaration_not_recomputed",
            **_fields(revision, "comparison_basis", "comparable_to_known_failed",
                      "same_materialized_code", "different_code_is_not_proof_of_repair"),
            "known_failed_report_ref": (
                refs.check(revision["known_failed_report_ref"])[0]
                if isinstance(revision.get("known_failed_report_ref"), dict) else None
            ),
            "claim_scope": "code_comparison_not_repair_success",
        }
        report_code = _object(report.get("materialized_code_identity"))
        row["materialized_code_report_link"] = (
            "matching_explicit_identity" if code and report_code and code == report_code else
            "identity_mismatch" if code and report_code else "unknown_missing_explicit_identity"
        )
        reported_changes = report.get("generated_changes_sha256")
        row["generated_changes_report_link"] = (
            "matching_explicit_identity"
            if isinstance(reported_changes, str) and reported_changes == evaluation.get("generated_changes_sha256")
            else "identity_mismatch" if isinstance(reported_changes, str)
            else "unknown_missing_explicit_identity"
        )
        if "reused_from_report_ref" in evaluation:
            row["reused_from_report_ref"] = refs.check(evaluation["reused_from_report_ref"])[0]
            if row["reused_from_report_ref"]["integrity"] != "verified_bytes":
                row["execution_observation"] = "unknown"
        row["verification_summary"] = _fields(
            _object(evaluation.get("verification_summary")),
            "checks", "executions", "failed_checks",
        )
        row["checks"] = [{
            **_fields(observation, "check_id"),
            "result_ref": refs.check(observation.get("result_ref"))[0],
        } for observation in _rows(evaluation.get("observations"))]
        row["denominator_scope"] = "reported_local_checks_not_cross_task_eval"
        result.append(row)
    return result


def _attempt(path: Path, raw: bytes, journal: Mapping[str, Any], refs: _References):
    factory = _object(journal.get("factory_receipt"))
    loop = _object(factory.get("patch_agent_loop"))
    repair = _object(journal.get("repair_context"))
    selected = _object(journal.get("selected_artifacts"))
    terminal = _object(journal.get("terminal_result"))
    upstream = {name: refs.check(ref)[0] for name, ref in sorted(selected.items())}
    current_artifacts = {
        name: {"source_field": f"artifacts.{name}", "ref": refs.check(ref)[0]}
        for name, ref in sorted(_object(journal.get("artifacts")).items())
    }
    terminal_artifacts = {}
    for field in ("patch_proposal_artifact", "proposal_review_artifact", "dry_run_artifact"):
        value = terminal.get(field)
        terminal_artifacts[field] = {
            "source_field": f"terminal_result.{field}",
            "observation": (
                "not_recorded" if field not in terminal else
                "recorded_null" if value is None else "reference_recorded"
            ),
            "ref": None if value is None else refs.check(value)[0],
        }
    parents = {name: refs.check(repair[name])[0] for name in (
        "parent_attempt_ref", "parent_proposal", "parent_review", "parent_response_ref",
        "failure_report_ref",
    ) if name in repair}
    verified_replay = _object(factory.get("verified_replay"))
    if "source_attempt_ref" in verified_replay:
        parents["replayed_from_attempt"] = refs.check(verified_replay["source_attempt_ref"])[0]
    replay_requests = [{
        **_fields(item, "current_wire_sha256", "all_json_values_and_text_exact", "exact_wire_bytes_match"),
        "original_request_ref": refs.check(item.get("original_request_ref"))[0],
        "comparison_basis": "historical_journal_claim_not_comparison_reexecuted",
    } for item in _rows(factory.get("replay_request_matches"))]
    turns = _turns(factory, refs)
    evaluations = _evaluations(loop, refs)
    code_responses = [refs.check(item)[0] for item in _rows(factory.get("model_responses"))]
    if not code_responses and isinstance(factory.get("model_response"), dict):
        code_responses.append(refs.check(factory["model_response"])[0])
    for evaluation in evaluations:
        matches = [ref for ref in code_responses
                   if isinstance(evaluation.get("model_response_sha256"), str)
                   and ref.get("output_sha256") == evaluation["model_response_sha256"]]
        evaluation["code_response_refs"] = matches
        evaluation["code_response_link"] = (
            "matching_explicit_response_hash" if matches else "unknown_no_matching_response_ref"
        )
    integrity = Counter(item[0]["integrity"] for item in refs.cache.values())
    if refs.unverifiable_references:
        integrity["unverifiable_reference"] = refs.unverifiable_references
    problems = [value for value in integrity if value not in ("verified_bytes", "verified_artifact")]
    return {
        **_fields(journal, "run_id", "feature_id", "request_id", "receipt_version", "status",
                  "attempt_identity_sha256", "generated_against_snapshot_sha256",
                  "current_snapshot_sha256", "proposal_admitted"),
        "journal_ref": {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()},
        "journal_identity_checks": _journal_checks(journal),
        "journal_observation": (
            "terminal_record_retained" if terminal else "terminal_result_cache_not_recorded"
        ),
        "recorded_phases": [_fields(event, "event_index", "phase")
                            for event in _rows(journal.get("events"))],
        "worker_state": {
            "factory_status": factory.get("status"), "loop_status": loop.get("status"),
            "termination": _fields(_object(loop.get("termination")), "status", "code", "turn_index"),
            "tool_availability": [{
                "phase": phase, **_fields(item, "turn_index", "selection"),
                "allowed_tools": _strings(item.get("allowed_tools")),
            } for phase, execution in _phases(loop)
                for item in _rows(execution.get("tool_availability_trace"))],
        },
        "integrity": "references_need_attention" if problems else "checked_references_match",
        "reference_freshness": (
            "stale" if integrity["hash_mismatch"] else "unknown" if problems else "retained_bytes_match"
        ),
        "reference_integrity_counts": dict(sorted(integrity.items())),
        "source_currentness": "not_rechecked_by_index",
        "selected_upstreams": upstream,
        "current_artifacts": current_artifacts,
        "terminal_artifacts": terminal_artifacts,
        "parents": parents,
        "revision_semantics": _fields(_object(factory.get("repair_context")), "revision_semantics"),
        "worker_turns": turns,
        "replay_request_observations": replay_requests,
        "tool_execution": _tools(loop),
        "code_responses": code_responses,
        "behavior_evaluations": evaluations,
        "terminal": _fields(terminal, "status", "terminal_stage", "stopped_before", "reason",
                            "product_source_writes_performed", "source_modified_during_run"),
        "failure": _fields(_object(journal.get("failure")), "code", "failure_class", "stage"),
        "budget_and_counts_recorded": {
            **_fields(journal, "max_model_calls", "model_call_count"),
            **_fields(factory, "live_response_count", "replayed_model_turns"),
            "observed_turn_origins": dict(Counter(row["response_origin"] for row in turns)),
            "turn_origin_count_basis": "journal_declarations_not_independent_send_audit",
        },
        "eval_observation": {
            "reported_results": dict(Counter(row.get("status", "unknown") for row in evaluations)),
            "cross_task_denominator": None, "repair_success_rate": None,
            "execution_modes": dict(Counter(row["execution_observation"] for row in evaluations)),
        },
        "limitations": [
            "Historical journal claims are not new executions or authorization.",
            "Requested without a retained response does not establish whether sending occurred.",
            "Admitted observations do not independently prove actual model consumption.",
            "Report presence does not prove a new verifier execution or semantic correctness.",
            "This index does not establish Langfuse delivery, Runtime, rollback or resumability.",
        ],
    }


def project_patch_executions(
    artifact_store_root: str | Path, *, feature_id: str | None = None,
    run_id: str | None = None, attempt_locator: str | None = None,
) -> dict[str, Any]:
    """Read exact filters over ``cr`` journals, including failed and partial attempts."""
    root = _local_path(Path.cwd(), str(artifact_store_root))
    attempts_root = root / "cr"
    if attempt_locator is not None:
        path = _local_path(root, attempt_locator)
        try:
            path.relative_to(attempts_root.resolve())
        except ValueError as exc:
            raise ValueError("attempt locator must be within the store cr directory") from exc
        paths = [path]
    else:
        paths = sorted(attempts_root.glob("*.json"))
    attempts, unreadable = [], []
    for path in paths:
        if ".response." in path.name:
            continue
        try:
            raw = _read_bytes(path)
            journal = _json(raw)
        except (OSError, ValueError, UnicodeError):
            unreadable.append({"path": str(path), "status": "missing_or_invalid_journal"})
            continue
        if journal.get("receipt_version") != "patch_continuation_attempt_v1":
            continue
        if feature_id is not None and journal.get("feature_id") != feature_id:
            continue
        if run_id is not None and journal.get("run_id") != run_id:
            continue
        attempts.append(_attempt(path, raw, journal, _References(root)))
    return {
        "schema_version": "patch_execution_index_v1", "authority": "non_authoritative",
        "query_scope": "single_explicit_artifact_store_patch_journals",
        "read_only": True, "persistence": "none", "regeneration": "retained_journals_and_references",
        "filters": {"feature_id": feature_id, "run_id": run_id, "attempt_locator": attempt_locator},
        "attempts": attempts, "unreadable_journals": unreadable,
        "store_observation": (
            "missing_store" if not root.is_dir() else
            "missing_cr_directory" if not attempts_root.is_dir() else "cr_directory_read"
        ),
        "match_count": len(attempts), "model_calls_performed": 0,
        "verifier_executions_performed": 0, "product_source_writes_performed": False,
        "langfuse_delivery": "not_performed", "task_suite_denominator": None,
    }
