"""Extract tool observations without running a task or scoring it with a model.

Unknown semantic usefulness and recovery attribution stay unknown.
为什么要有它：a completed command, repeated input, or later delivery alone cannot
prove that an investigation helped or that a failed operation recovered.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from src.mod_agent.evaluation.task_measurement import _read_bound, _safe_reference


def _body(ref, root):
    path = _safe_reference(ref, root)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref.get("sha256"):
        raise ValueError("Tool body reference hash mismatch.")
    return json.loads(raw)


def _operational(row, bodies=None):
    a = row.get("attributes") or {}
    name, status = row.get("name"), row.get("status")
    response = (bodies or {}).get("response")
    # A queued diagnostic is not a successful source read.
    # 为什么要有它：queue delivery proves transmission, not completion of the requested action.
    if a.get("error_code") or (isinstance(response, dict) and (
        response.get("error_code") or response.get("status") in {"failed", "error", "not_executed", "rejected"}
    )):
        return False, "unknown", "explicit_tool_result_error"
    # Only explicit codes classify errors; prose and tool names are not diagnoses.
    # 为什么要有它：model-generated error text and nonzero search exits can misclassify failures.
    categories = {
        "query_terms_missing": "parameter_error",
        "source_scope_rejected": "parameter_error",
        "source_root_missing": "environment_failure",
        "source_decode_failed": "environment_failure",
        "tool_failed": "unknown",
    }
    if name == "evidence.source_query" and a.get("retrieval_status") in categories:
        return False, categories[a["retrieval_status"]], "explicit_retrieval_status"
    if status in {"failed", "error", "rejected"}:
        return False, "unknown", "recorded_failed_operation"
    if status != "completed":
        return None, "unknown", "insufficient_completion_evidence"
    if name == "evidence.source_query" and a.get("tool_dispatch_performed") is True:
        if (a.get("tool_exit_code"), a.get("retrieval_status")) in {
            (0, "source_observations_returned"), (1, "no_matches")
        }:
            return True, None, "completed_search_including_legitimate_no_matches"
    if (name == "source.inspect" and a.get("tool_dispatch_performed") is True
            and a.get("observation_queued") is True and a.get("encoded_payload_sha256")
            and a.get("source_observation_id") and a.get("source_snapshot_sha256")
            and type(a.get("encoded_payload_bytes")) is int and a["encoded_payload_bytes"] > 0):
        return True, None, "recorded_source_observation_payload_queued"
    if name == "patch.upstream_request" and a.get("request_registered") is True:
        return True, None, "request_registered_only_not_upstream_execution"
    return None, "unknown", "insufficient_tool_specific_evidence"


def _fingerprint(name, attributes, bodies, refs):
    if attributes.get("input_payload_sha256"):
        return attributes["input_payload_sha256"], "recorded_input_payload_sha256"
    request = bodies.get("request")
    # Only entire known parameter objects qualify; never guess which fields to strip.
    # 为什么要有它：turn identifiers or timing metadata would split identical tool inputs.
    if name == "source.inspect" and isinstance(request, dict) and set(request) == {"binding_id"}:
        if isinstance(request["binding_id"], str) and request["binding_id"]:
            return refs["request"]["sha256"], "verified_request_bytes_pure_binding_parameter"
    expected = {"max_items", "query", "search_root", "source_identity_query", "source_view_policy"}
    if name == "evidence.source_query" and isinstance(request, dict) and set(request) == expected:
        return refs["request"]["sha256"], "verified_request_bytes_source_query_parameters"
    return None, "unknown_no_verified_parameter_identity"


def extract_tool_effects(measurement):
    """Enrich a measure_product_task result using its hash-bound selected manifests."""
    if measurement.get("schema_version") != "product_task_measurement_v1":
        raise ValueError("A product_task_measurement_v1 selection is required.")
    rows, seen = [], {}
    for segment in measurement["segments"]:
        root = Path(segment["run_root"]).resolve()
        ref = segment["manifest_ref"]
        _safe_reference(ref, root)
        manifest = _read_bound(ref, root)
        trace_id = (manifest.get("execution_trace") or {}).get("trace_id")
        observations = manifest.get("execution_observations") or {}
        for observation in observations.values():
            if observation.get("kind") != "tool":
                continue
            identity = (trace_id, observation["id"])
            encoded = json.dumps(observation, sort_keys=True, ensure_ascii=False)
            if identity in seen:
                if seen[identity] != encoded:
                    raise ValueError("Conflicting duplicate tool observation.")
                continue
            seen[identity] = encoded
            a = observation.get("attributes") or {}
            body_refs = a.get("local_detail_refs") or {}
            bodies = {role: _body(body_ref, root) for role, body_ref in body_refs.items()}
            effective, category, basis = _operational(observation, bodies)
            fingerprint, fingerprint_basis = _fingerprint(observation.get("name"), a, bodies, body_refs)
            rows.append({
                "trace_id": trace_id, "observation_id": observation["id"],
                "segment_index": segment["segment_index"], "name": observation.get("name"),
                "started_at": observation.get("started_at"),
                "elapsed_ms": observation.get("elapsed_ms"),
                "operation_effective": effective, "effectiveness_basis": basis,
                "failure_category": category, "content_usefulness": "unknown",
                "semantic_judgment_origin": None,
                "model_consumption_proven": a.get("model_consumption_proven"),
                "request_fingerprint": fingerprint,
                "request_fingerprint_basis": fingerprint_basis,
                "retrieval_status": a.get("retrieval_status"),
                "produced_materials": a.get("produced_materials", []),
                "manifest_ref": ref, "body_refs": body_refs,
                "recovery_success": None,
            })
    rows.sort(key=lambda r: (r["segment_index"], r["started_at"] or "", r["observation_id"]))
    groups = {}
    for row in rows:
        fingerprint = row["request_fingerprint"]
        # Do not group all calls to a tool as retries; arguments identify the read.
        # 为什么要有它：different queries can be necessary independent investigation.
        key = (row["trace_id"], row["name"], fingerprint) if fingerprint else None
        previous = groups.setdefault(key, []) if key else []
        row["same_input_prior_observations"] = [r["observation_id"] for r in previous]
        row["first_effective"] = row["operation_effective"] if key and not previous else None
        row["first_effective_scope"] = "first_exact_input_in_selected_trace" if key else "single_observation_no_input_identity"
        row["later_effective_after_failure"] = [r["observation_id"] for r in previous
            if r["operation_effective"] is False] if row["operation_effective"] is True else []
        if key:
            previous.append(row)
    repeats = [r for r in rows if r["same_input_prior_observations"]]
    durations = [r["elapsed_ms"] for r in repeats]
    return {
        "schema_version": "tool_effects_v1", "read_only": True, "inspection_model_calls": 0,
        "run_id": measurement["run_id"], "selection_scope": "explicit_measurement_segments_only",
        "observations": rows,
        "counts": {"observed": len(rows), "operationally_effective": sum(r["operation_effective"] is True for r in rows),
            "operationally_failed": sum(r["operation_effective"] is False for r in rows),
            "operationally_unknown": sum(r["operation_effective"] is None for r in rows),
            "by_failure_category": dict(Counter(r["failure_category"] for r in rows if r["failure_category"])),
            "semantic_usefulness_unknown": len(rows)},
        "repeated_input_cost": {"observed_tool_calls": len(repeats),
            "tool_elapsed_ms_sum": sum(durations) if all(isinstance(v, (int, float)) for v in durations) else None,
            "model_calls": None, "input_tokens": None, "output_tokens": None,
            "scope": "exact_input_repetitions_not_necessarily_retries_or_waste"},
        "recovery_cost": {"tool_calls": None, "model_calls": None, "input_tokens": None,
            "output_tokens": None, "elapsed_ms": None, "scope": "unknown_no_explicit_recovery_allocation"},
        "selected_model_cost": measurement["model"]["usage"],
        "selected_terminal": measurement["last_selected_terminal"],
        "task_delivered": None, "savings": None,
        "boundary": "Tool operation completion is separate from useful content, same-task recovery and task delivery."
    }
