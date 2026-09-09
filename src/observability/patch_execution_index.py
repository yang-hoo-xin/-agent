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
from src.mod_agent.proposal.patch_agent_loop import (
    PatchAgentLoopError,
    expand_patch_source_observations,
    iter_patch_recovery_revisions,
)

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


def _digest(value):
    try:
        return _canonical_sha256(value)
    except (ValueError, TypeError, UnicodeError):
        return None


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
    try:
        revisions = iter_patch_recovery_revisions(loop)
    except ValueError:
        return  # Malformed records do not acquire invented execution positions.
    for revision in revisions:
        name = ("validator_correction" if revision.get("message_type") == "patch_validator_correction"
                or ("message_type" not in revision and revision is loop.get("validator_correction"))
                else "behavior_correction")
        execution = _object(revision.get("execution"))
        if execution:
            yield name, execution


def _turns(factory: Mapping[str, Any], refs: _References) -> list[dict[str, Any]]:
    result = []
    loop = _object(factory.get("patch_agent_loop"))
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
        row["request_ref"], request_document = (refs.check(turn["request_ref"]) if "request_ref" in turn
            else ({"integrity": "unverifiable_reference"}, {}))
        row["request_observation"] = (
            "retained_request_identity_verified_not_send_proof"
            if row["request_ref"]["integrity"] == "verified_bytes"
            else "unknown_no_verified_request_reference"
        )
        row["observation_request_links"] = []
        row["failure_feedback_links"] = []
        row["normalized_request_identity"] = "unknown_no_verified_request"
        row["observation_delivery"] = (
            "unknown_observation_to_request_link_not_verified"
            if row["request_ref"]["integrity"] == "verified_bytes"
            else "unknown_no_explicit_request_reference"
        )
        if row["request_ref"]["integrity"] == "verified_bytes":
            declared = turn.get("request_sha256")
            row["normalized_request_identity"] = (
                "matched" if isinstance(declared, str) and _digest(request_document) == declared else
                "hash_mismatch" if isinstance(declared, str) else "unknown_missing_normalized_request_hash")
            if row["normalized_request_identity"] == "matched":
                row["observation_request_links"] = _tool_request_links(request_document, loop)
                row["failure_feedback_links"] = _failure_feedback_links(request_document, factory, refs)
            if row["observation_request_links"]:
                row["observation_delivery"] = (
                    "verified_retained_tool_payloads_in_request_not_model_understanding"
                    if all(item["binding_status"] == "matched" for item in row["observation_request_links"])
                    else "tool_payload_mismatch_or_unknown"
                )
        response, document = refs.check(turn.get("response_ref"))
        row["response_ref"] = response
        if "original_response_ref" in turn:
            row["original_response_ref"] = refs.check(turn["original_response_ref"])[0]
        verified_response = response["integrity"] == "verified_bytes"
        row["response_after_request_observed"] = turn.get("status") == "responded" and verified_response
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


def _message_object(message):
    content = message.get("content")
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        try:
            return _object(json.loads(content))
        except ValueError:
            pass
    return {}


def _tool_request_links(request, loop):
    results = [item for exchange in _rows(request.get("historical_tool_exchanges"))
               for item in _rows(exchange.get("tool_results"))]
    results.extend(_rows(request.get("tool_results")))
    source = [item for item in results if item.get("name") == "inspect_plan_binding_source"
              and isinstance(item.get("output"), dict) and isinstance(item["output"].get("observation_id"), str)]
    visible_valid = False
    try:
        expand_patch_source_observations([item["output"] for item in source])
        visible_valid = True
    except (PatchAgentLoopError, ValueError, TypeError, KeyError):
        pass
    known = [(phase, item) for phase, execution in _phases(loop) for item in _rows(execution.get("observation_trace"))]
    links = []
    for item in source:
        payload = item["output"]
        payload_hash = _digest(payload)
        matches = [(phase, row) for phase, row in known if row.get("observation_id") == payload["observation_id"]
                   and row.get("binding_id") == payload.get("binding_id")]
        matched = []
        for phase, row in matches:
            expected = row.get("encoded_payload_sha256")
            content_matches = (payload_hash == expected if isinstance(expected, str) else
                isinstance(row.get("observation_sha256"), str) and _digest({key: value for key, value in payload.items() if key != "observation_sha256"}) == row["observation_sha256"])
            if content_matches and visible_valid and payload.get("observation_sha256") == row.get("observation_sha256"):
                matched.append({"phase": phase, "tool_turn_index": row.get("turn_index")})
        links.append({"tool_call_id": item.get("call_id"), "observation_id": payload["observation_id"],
            "observation_sha256": payload.get("observation_sha256"), "payload_sha256": payload_hash,
            "binding_status": "matched" if matched else "mismatch" if matches else "unknown_no_matching_tool_observation",
            "visible_source_resolution": "verified" if visible_valid else "unverified",
            "matched_execution_positions": matched,
            "claim_scope": "matching_retained_request_content_not_independent_send_or_understanding"})
    return links


def _feedback_core(value):
    fields = ("failure_owner", "owner_binding_ids", "observations", "generated_changes_sha256", "source_snapshot_sha256")
    if not all(key in value for key in fields):
        return None
    result = {key: value[key] for key in fields}
    result["observations"] = [dict(row) for row in _rows(value["observations"])]
    for row in result["observations"]:
        if isinstance(row.get("result_ref"), dict):
            row["result_ref"] = {"sha256": row["result_ref"].get("sha256")}
    return result


def _failure_feedback_links(request, factory, refs):
    evaluations = _rows(_object(factory.get("patch_agent_loop")).get("behavior_evaluations"))
    related = [row.get("report_ref") for row in evaluations]
    related.extend(_object(row.get("code_revision")).get("known_failed_report_ref") for row in evaluations)
    reports = []
    for reference in related:
        if reference is None:
            continue
        checked, document = refs.check(reference)
        core = _feedback_core(document)
        if checked.get("integrity") == "verified_bytes" and core is not None:
            reports.append((checked, core, document.get("status")))
    links = []
    for position, message in enumerate(_rows(request.get("messages"))):
        value = _message_object(message)
        feedback = _object(value.get("validator_feedback"))
        if not feedback:
            continue
        core = _feedback_core(feedback)
        claimed_hash = feedback.get("report_sha256")
        matches = [(reference, expected, status) for reference, expected, status in reports if reference.get("sha256") == claimed_hash]
        matching = [reference for reference, expected, status in matches if core is not None and core == expected
                    and ("status" not in feedback or feedback["status"] == status)]
        links.append({"message_index": position, "message_type": value.get("message_type"),
            "report_sha256": claimed_hash, "core_fields_sha256": _digest(core) if core is not None else None,
            "generated_changes_sha256": feedback.get("generated_changes_sha256"),
            "source_snapshot_sha256": feedback.get("source_snapshot_sha256"),
            "failed_check_ids": [row.get("check_id", row.get("case_id")) for row in _rows(feedback.get("observations"))],
            "failed_check_count": len(_rows(feedback.get("observations"))),
            "binding_status": "matched" if matching else "core_fields_mismatch" if matches else
                              "unknown_no_report_hash" if not isinstance(claimed_hash, str) else "unmatched_report_hash",
            "verified_report_refs": matching,
            "claim_scope": "F1_core_fields_and_report_hash_in_retained_request_not_model_understanding"})
    return links


def _failure_summary(journal, factory, execution, worker_config_ref):
    terminal = _object(journal.get("terminal_result"))
    loop = _object(factory.get("patch_agent_loop"))
    turns = execution.get("worker_turns", [])
    evaluations = execution.get("behavior_evaluations", [])
    native = _object(journal.get("execution_observations"))
    generations = [row for row in native.values() if isinstance(row, dict)
        and row.get("kind") == "generation" and row.get("name") == "patch.generate"
        and _object(row.get("attributes")).get("transport_started") is True]
    terminations = [{"phase": phase, **_fields(_object(part.get("termination")), "code", "status", "turn_index")}
                    for phase, part in _phases(loop) if isinstance(part.get("termination"), dict)]
    counts = _object(terminal.get("execution_counts"))
    return {
        "authority": "non_authoritative", "task": _fields(journal, "feature_id", "run_id", "request_id"),
        "executor_identity": {**_fields(_object(factory.get("qualification_execution_identity")),
            "implementation_sha256", "worker_policy_sha256", "scope"), "verification": "recorded_not_recomputed"},
        "configuration": {"worker_ref": worker_config_ref, "profile_sha256": journal.get("worker_profile_sha256"),
            "profile": _fields(_object(factory.get("profile")), "provider", "model", "profile_version", "output_format_policy")},
        "stopped_at": {"terminal_stage": terminal.get("terminal_stage"), "status": journal.get("status"),
            "proposal_admitted": journal.get("proposal_admitted"), "phase_terminations": terminations,
            "failure": _fields(_object(journal.get("failure")), "code", "failure_class", "stage"),
            "submission_failure": _fields(_object(_object(factory.get("failure")).get("diagnostics")),
                "failure_boundary", "failure_classification", "json_error_line", "json_error_column")},
        "model_requests": {"journal_call_count": journal.get("model_call_count"),
            "retained_response_count": sum(row.get("response_after_request_observed") is True for row in turns),
            "transport_started_observation_count": len(generations) if native else None,
            "transport_count_basis": "native_generation_start_markers_not_independent_network_capture" if native else "unknown_no_native_execution_history",
            "record_completeness": "not_established_missing_records_do_not_prove_no_send"},
        "code_and_failure_reports": [{
            **_fields(row, "evaluation_index", "status", "failure_owner", "model_response_sha256", "generated_changes_sha256", "execution_observation"),
            "report_ref": row.get("report_ref"), "code_response_refs": row.get("code_response_refs"),
            "code_response_link": row.get("code_response_link"), "code_comparison": row.get("code_revision"),
            "failed_check_ids": [check.get("check_id", check.get("case_id")) for check in row.get("checks", [])],
            "observed_failure_item_count": len(row.get("checks", [])),
            "recorded_failed_check_count": _object(row.get("verification_summary")).get("failed_checks"),
            "verification_summary": row.get("verification_summary"),
        } for row in evaluations],
        "request_evidence": [{"turn_index": row.get("turn_index"), "request_ref": row.get("request_ref"),
            "normalized_request_identity": row.get("normalized_request_identity"),
            "tool_observation_links": row.get("observation_request_links", []),
            "failure_feedback_links": row.get("failure_feedback_links", []),
            "response_after_request_observed": row.get("response_after_request_observed"),
            "send_observation": row.get("send_observation")} for row in turns],
        "formal_downstream": {name: {"recorded_count": counts.get(name),
            "observation": "not_executed_by_recorded_counter" if type(counts.get(name)) is int and counts[name] == 0
                           else "execution_recorded" if type(counts.get(name)) is int and counts[name] > 0 else "unknown"}
            for name in ("apply", "build", "runtime")},
        "diagnosis_limit": "Evidence narrows the failure boundary; it does not identify a unique model, prompt, tool or policy root cause.",
    }


def _tools(loop: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = []
    for phase, execution in _phases(loop):
        observations = _rows(execution.get("observation_trace"))
        for call in _rows(execution.get("tool_call_trace")):
            row = {"phase": phase, **_fields(
                call, "turn_index", "tool_call_id", "tool", "binding_id",
                "arguments_sha256", "status", "dispatch_started", "error_code",
                "read_cost", "observation_origin",
            )}
            row["execution_observation"] = (
                "not_executed" if call.get("dispatch_started") is False else
                "prior_visible_source_reuse" if call.get("observation_origin") == "prior_visible_source_reuse" else
                "dispatch_started" if call.get("dispatch_started") is True else "unknown"
            )
            row["returned_observations"] = [{**_fields(
                observation, "observation_id", "observation_sha256", "source_ref",
                "source_hash", "source_snapshot_sha256", "source_identity_sha256", "admitted_to_model",
                "model_payload_bytes", "encoded_payload_bytes", "encoded_payload_sha256",
                "expanded_payload_bytes", "payload_admitted", "consumed_in_model_turn",
                "read_cost", "observation_origin",
            ), **({"excerpt_ref": {**_fields(observation["excerpt_ref"],
                "observation_id", "observation_sha256", "excerpt_sha256"),
                **({"source_excerpt_span": _fields(observation["excerpt_ref"]["source_excerpt_span"],
                    "start_line", "end_line")} if isinstance(observation["excerpt_ref"].get("source_excerpt_span"), dict) else {})}}
                if isinstance(observation.get("excerpt_ref"), dict) else {})}
                for observation in observations
                if isinstance(call.get("binding_id"), str)
                and observation.get("turn_index") == call.get("turn_index")
                and observation.get("binding_id") == call.get("binding_id")]
            row["delivery_verification"] = "journal_admission_only_not_wire_consumption"
            result.append(row)
    return result


def _submissions(factory: Mapping[str, Any], loop: Mapping[str, Any], refs: _References):
    """Expose submission checks without counting them as tools or behavior runs."""
    retained = []
    for turn in _rows(factory.get("worker_turns")):
        ref, document = refs.check(turn.get("response_ref"))
        content = document.get("content")
        if ref.get("integrity") == "verified_bytes" and isinstance(content, str):
            retained.append({"turn_index": turn.get("turn_index"), "ref": ref,
                "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()})
    result = []
    for phase, execution in _phases(loop):
        for submission in _rows(execution.get("submission_trace")):
            row = {"phase": phase, **_fields(submission, "turn_index", "response_sha256", "schema_sha256",
                "status", "stop_reason", "code_validation_performed", "feedback_payload_bytes", "feedback_queued", "feedback_in_request",
                "followup_response_observed", "consumed_in_model_turn")}
            diagnostics = _object(submission.get("diagnostics"))
            row["diagnostics"] = _fields(diagnostics, "failure_boundary", "failure_classification", "schema_constraint",
                "json_error_line", "json_error_column", "json_error_character_index")
            for key in ("field_path", "schema_path"):
                value = diagnostics.get(key)
                if isinstance(value, list):
                    row["diagnostics"][key] = [item[:96] if isinstance(item, str) else item
                        for item in value if type(item) in (str, int)][:32]
            matches = [item for item in retained if item["content_sha256"] == submission.get("response_sha256")]
            row["retained_response_matches"] = matches
            row["response_binding"] = "matching_retained_content_hash" if matches else "unknown_no_verified_matching_content"
            row["claim_scope"] = "submission_format_and_schema_only_not_patch_or_behavior_success"
            row["feedback_observation_basis"] = "journal_request_and_response_observations_not_independent_send_proof"
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
            **_fields(revision, "model_turn_index", "comparison_basis", "comparable_to_known_failed",
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
            **_fields(observation, "check_id", "case_id"),
            "result_ref": refs.check(observation.get("result_ref"))[0],
        } for observation in _rows(evaluation.get("observations"))]
        row["denominator_scope"] = "reported_local_checks_not_cross_task_eval"
        result.append(row)
    return result


def _factory_execution(factory: Mapping[str, Any], refs: _References) -> dict[str, Any]:
    """Project one worker without borrowing another segment's code or counters."""
    loop = _object(factory.get("patch_agent_loop"))
    evaluations = _evaluations(loop, refs)
    responses = [refs.check(item)[0] for item in _rows(factory.get("model_responses"))]
    if not responses and isinstance(factory.get("model_response"), dict):
        responses.append(refs.check(factory["model_response"])[0])
    for evaluation in evaluations:
        matches = [ref for ref in responses if isinstance(evaluation.get("model_response_sha256"), str)
                   and ref.get("output_sha256") == evaluation["model_response_sha256"]]
        evaluation["code_response_refs"] = matches
        evaluation["code_response_link"] = (
            "matching_explicit_response_hash" if matches else "unknown_no_matching_response_ref")
    return {
        "worker_turns": _turns(factory, refs), "tool_execution": _tools(loop),
        "submission_trace": _submissions(factory, loop, refs),
        "code_responses": responses, "behavior_evaluations": evaluations,
        "replay_request_observations": [{
            **_fields(item, "current_wire_sha256", "all_json_values_and_text_exact", "exact_wire_bytes_match"),
            "original_request_ref": refs.check(item.get("original_request_ref"))[0],
            "comparison_basis": "historical_journal_claim_not_comparison_reexecuted",
        } for item in _rows(factory.get("replay_request_matches"))],
        "tool_availability": [{
            "phase": phase, **_fields(item, "turn_index", "selection"),
            "allowed_tools": _strings(item.get("allowed_tools")),
        } for phase, execution in _phases(loop)
            for item in _rows(execution.get("tool_availability_trace"))],
        "turn_progress": [{"phase": phase, **_fields(
            item, "turn_index", "submitted_patch", "requested_source_reads", "dispatched_binding_reads",
            "new_source_windows", "reused_source_observations", "read_cost", "observation_bytes_added",
            "no_new_source_information",
        )} for phase, execution in _phases(loop) for item in _rows(execution.get("turn_progress_trace"))],
        "source_read_accounting": [{"phase": phase, **_fields(
            execution, "read_accounting_version", "tool_rounds_used", "dispatched_binding_reads",
            "reused_source_observations",
        )} for phase, execution in _phases(loop)],
    }


def _count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _upstream_provider_turns(journal: Mapping[str, Any], refs: _References) -> list[dict[str, Any]]:
    """Requested/responded events describe one call, not two model sends."""
    groups: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    for event in _rows(journal.get("events")):
        if event.get("phase") != "patch_upstream_provider_turn":
            continue
        request = _object(event.get("request_ref"))
        key = (event.get("role"), request.get("path"), request.get("sha256"))
        if not all(isinstance(value, str) for value in key):
            key = ("unknown_request", event.get("event_index"), len(groups))
        groups.setdefault(key, []).append(event)
    result = []
    for events in groups.values():
        event = events[-1]
        response, _ = refs.check(event.get("response_ref"))
        requested, _ = refs.check(event.get("request_ref"))
        result.append({
            **_fields(event, "role", "status", "error_code", "response_origin", "new_model_call_reserved"),
            "event_indexes": [item["event_index"] for item in events if type(item.get("event_index")) is int],
            "request_ref": requested, "response_ref": response,
            "configuration_ref": refs.check(event.get("configuration_ref"))[0],
            "usage": _fields(_object(event.get("usage")), "input_tokens", "output_tokens", "total_tokens"),
            "provider_request_identity": _fields(
                _object(_object(event.get("provider_diagnostic")).get("request_identity")),
                "hash_basis", "provider_body_sha256", "provider_body_utf8_bytes"),
            "send_observation": (
                "journal_claim_live_response_with_verified_ref"
                if event.get("status") == "responded" and event.get("response_origin") == "live_provider_response"
                and response["integrity"] == "verified_bytes" else "requested_send_unconfirmed"),
            "send_observation_basis": "journal_claim_with_reference_checks_not_independent_send_proof",
        })
    return result


def _chain_execution(journal: Mapping[str, Any], refs: _References):
    segments = _rows(journal.get("patch_execution_segments"))
    combined: dict[str, list[dict[str, Any]]] = {}
    projected = []
    for segment in segments:
        factory = _object(segment.get("factory_receipt"))
        number = _count(segment.get("segment_index"))
        values = _factory_execution(factory, refs) if factory else {}
        for key, rows in values.items():
            combined.setdefault(key, []).extend({"segment_index": number, **row} for row in rows)
        projected.append({
            "segment_index": number,
            "allocated_model_calls": _count(segment.get("allocated_model_calls")),
            "model_call_count": _count(factory.get("model_call_count")),
            "live_response_count": _count(factory.get("live_response_count")),
            "replayed_model_turns": _count(factory.get("replayed_model_turns")),
            "worker_receipt_observation": "recorded" if factory else "unknown_missing_factory_receipt",
            "factory_status": factory.get("status"),
            "selected_artifacts": {name: refs.check(ref)[0]
                for name, ref in sorted(_object(segment.get("selected_artifacts")).items())},
        })
    shared = _object(journal.get("shared_model_budget"))
    lineage = _object(journal.get("replanned_patch_lineage"))
    metadata = {
        "execution_segments_observation": (
            "unknown_not_recorded" if "patch_execution_segments" not in journal else
            "recorded" if isinstance(journal.get("patch_execution_segments"), list) else "invalid"),
        "patch_execution_segments": projected,
        "initial_selected_artifacts": ({name: refs.check(ref)[0]
            for name, ref in sorted(journal["initial_selected_artifacts"].items())}
            if isinstance(journal.get("initial_selected_artifacts"), dict) else None),
        **({"current_upstream_artifacts": {name: refs.check(ref)[0]
            for name, ref in sorted(_object(journal["current_upstream_artifacts"]).items())}}
            if "current_upstream_artifacts" in journal else {}),
        "shared_model_budget": {
            **{key: _count(shared.get(key)) for key in ("maximum", "consumed", "remaining")},
            "by_role": ({role: _count(value) for role, value in shared["by_role"].items()}
                if isinstance(shared.get("by_role"), dict) else None),
            "basis": "whole_invocation_owner_declaration_not_independent_send_audit",
        },
        "replanned_patch_lineage": ({
            **{key: refs.check(lineage[key])[0] for key in (
                "repair_plan", "prior_plan", "failed_response_ref", "failure_report_ref") if key in lineage},
            "approval_inherited": lineage.get("approval_inherited") if isinstance(lineage.get("approval_inherited"), bool) else None,
        } if lineage else None),
        "upstream_provider_turns": _upstream_provider_turns(journal, refs),
        "latest_factory_scope": "latest_patch_segment_not_entire_invocation",
    }
    counts = {}
    for key in ("live_response_count", "replayed_model_turns"):
        values = [_count(_object(segment.get("factory_receipt")).get(key)) for segment in segments]
        counts[key] = sum(values) if values and all(value is not None for value in values) else None
    return combined, metadata, counts


def _attempt(path: Path, raw: bytes, journal: Mapping[str, Any], refs: _References):
    factory = _object(journal.get("factory_receipt"))
    loop = _object(factory.get("patch_agent_loop"))
    repair = _object(journal.get("repair_context"))
    selected = _object(journal.get("selected_artifacts"))
    terminal = _object(journal.get("terminal_result"))
    worker_config_ref = (
        refs.check(journal["worker_configuration_ref"])[0]
        if journal.get("worker_configuration_ref") is not None else None
    )
    worker_profile = journal.get("worker_profile_sha256")
    worker_profile = worker_profile if isinstance(worker_profile, str) else None
    evaluator_config = _object(factory.get("behavior_evaluator_configuration"))
    evaluator_identity = {
        **_fields(evaluator_config, "factory_name", "kwargs_sha256"),
        "configuration_ref": refs.check(evaluator_config.get("configuration_ref"))[0],
        "factory_ref": refs.check(evaluator_config.get("factory_ref"))[0],
        "source_field": "factory_receipt.behavior_evaluator_configuration",
        "factory_execution": "not_performed_by_query",
    } if evaluator_config else None
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
        "failure_report_ref", "source_attempt_ref", "verification_result_ref", "failed_response_ref",
    ) if name in repair}
    verified_replay = _object(factory.get("verified_replay"))
    if "source_attempt_ref" in verified_replay:
        parents["replayed_from_attempt"] = refs.check(verified_replay["source_attempt_ref"])[0]
    chain_metadata = {}
    counts = _fields(factory, "live_response_count", "replayed_model_turns")
    if any(key in journal for key in ("patch_execution_segments", "shared_model_budget",
                                     "initial_selected_artifacts", "replanned_patch_lineage",
                                     "current_upstream_artifacts")):
        execution, chain_metadata, counts = _chain_execution(journal, refs)
    else:
        execution = _factory_execution(factory, refs)
    turns = execution.get("worker_turns", [])
    evaluations = execution.get("behavior_evaluations", [])
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
        "failure_summary": _failure_summary(journal, factory, execution, worker_config_ref),
        "execution_trace": {
            "availability": "recorded" if "execution_observations" in journal else "not_recorded",
            **_fields(_object(journal.get("execution_trace")), "trace_id", "session_id", "environment", "mode",
                      "cloud_readback"),
            "export": _fields(_object(_object(journal.get("execution_trace")).get("export")),
                "post_attempts", "http_accepted", "send_failures", "queue_dropped", "pending",
                "deadline_exhausted", "remote_readback"),
            "observations": [_fields(_object(row), "id", "parent_id", "trace_id", "session_id", "environment",
                "name", "kind", "status", "started_at", "finished_at", "elapsed_ms")
                for row in _object(journal.get("execution_observations")).values()],
            "scope": "journal_projection_not_remote_readback_or_model_quality",
        },
        "journal_observation": (
            "terminal_record_retained" if terminal else "terminal_result_cache_not_recorded"
        ),
        "recorded_phases": [_fields(event, "event_index", "phase")
                            for event in _rows(journal.get("events"))],
        "worker_state": {
            "factory_status": factory.get("status"), "loop_status": loop.get("status"),
            "termination": _fields(_object(loop.get("termination")), "status", "code", "turn_index"),
            "tool_availability": execution.get("tool_availability", []),
            "turn_progress": execution.get("turn_progress", []),
        },
        "integrity": "references_need_attention" if problems else "checked_references_match",
        "reference_freshness": (
            "stale" if integrity["hash_mismatch"] else "unknown" if problems else "retained_bytes_match"
        ),
        "reference_integrity_counts": dict(sorted(integrity.items())),
        "source_currentness": "not_rechecked_by_index",
        "worker_configuration_ref": worker_config_ref,
        "worker_profile_sha256": worker_profile,
        "worker_profile_identity_verification": "recorded_not_recomputed" if worker_profile else "unknown",
        "behavior_evaluator_configuration": evaluator_identity,
        **chain_metadata,
        "selected_upstreams": upstream,
        "current_artifacts": current_artifacts,
        "terminal_artifacts": terminal_artifacts,
        "parents": parents,
        "revision_semantics": _fields(_object(factory.get("repair_context")), "revision_semantics"),
        "worker_turns": turns,
        "replay_request_observations": execution.get("replay_request_observations", []),
        "tool_execution": execution.get("tool_execution", []),
        "submission_trace": execution.get("submission_trace", []),
        "code_responses": execution.get("code_responses", []),
        "behavior_evaluations": evaluations,
        "terminal": _fields(terminal, "status", "terminal_stage", "stopped_before", "reason",
                            "product_source_writes_performed", "source_modified_during_run"),
        "failure": _fields(_object(journal.get("failure")), "code", "failure_class", "stage"),
        "budget_and_counts_recorded": {
            **_fields(journal, "max_model_calls", "model_call_count"),
            **counts,
            "observed_turn_origins": dict(Counter(row["response_origin"] for row in turns)),
            "turn_origin_count_basis": "journal_declarations_not_independent_send_audit",
            "source_read_accounting": execution.get("source_read_accounting", []),
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
