#!/usr/bin/env python
"""Read-only, hash-bound accounting for the registered five-task online A/B."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.mod_agent.evaluation.task_measurement import measure_product_task  # noqa: E402
from src.mod_agent.evaluation.tool_effects import extract_tool_effects  # noqa: E402


def reference(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def bound_bytes(ref):
    raw_path = ref["path"]
    if str(raw_path).startswith(("\\\\", "//")):
        raise ValueError("Only local evidence is accepted")
    path = Path(raw_path)
    if not path.is_absolute():
        raise ValueError("Evidence paths must be absolute")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise ValueError(f"Evidence hash mismatch: {path}")
    return raw


def read_bound(ref):
    return json.loads(bound_bytes(ref))


def pointer(document, field):
    if not isinstance(field, str) or not field.startswith("/"):
        raise ValueError("Field selectors must be JSON pointers")
    try:
        for part in field[1:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            document = document[int(part)] if isinstance(document, list) else document[part]
        return document
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def distribution(values):
    known = sorted(v for v in values if number(v))
    return {"n": len(known), "missing": len(values) - len(known),
            "p50": known[math.ceil(len(known) * .50) - 1] if known else None,
            "p95": known[math.ceil(len(known) * .95) - 1] if known else None,
            "algorithm": "nearest_rank: sorted[ceil(p*n)-1]; observed values only"}


def total(values):
    known = [v for v in values if number(v)]
    return {"total": sum(known) if len(known) == len(values) and values else None,
            "known_subtotal": sum(known), "observed": len(known), "missing": len(values) - len(known)}


def identity(row):
    return row["task_id"], row["arm"], row["repeat"]


def native_cache_measurement(response_ref, normalized=None, *, native_transport=False, response_kind=None):
    """Prefer bound native Ollama counters; never add cache hits to input tokens."""
    response_kind = response_kind or ("transport_response" if native_transport else "response")
    result = {"value": None, "normalized_cached_input_tokens": normalized,
              "source_kind": response_kind,
              "capture_boundary": {"provider_response": "adapter_raw_response_json_not_wire_bytes",
                                   "transport_response": "retained_transport_response_json",
                                   "response": "normalized_response_with_native_envelope"}.get(response_kind, "unknown"),
              "normalization_conflict": False, "response_ref": response_ref,
              "missing": "native_response_or_cache_counter_unavailable"}
    if response_ref is None:
        return result
    try:
        document = json.loads(bound_bytes(response_ref))
    except (ValueError, UnicodeDecodeError):
        return result
    if not isinstance(document, dict):
        return result
    usage = document.get("usage")
    recorded = usage.get("cached_input_tokens") if isinstance(usage, dict) else None
    if normalized is None:
        result["normalized_cached_input_tokens"] = recorded
    raw = document.get("raw_response", document)
    prefix = "/raw_response" if "raw_response" in document else ""
    # Parsed answer JSON is not a provider usage receipt.
    # 为什么要有它：model-authored cache-like fields cannot replace native transport evidence.
    if response_kind not in {"transport_response", "provider_response"} and "raw_response" not in document:
        return result
    if not isinstance(raw, dict) or raw.get("done") is not True or not isinstance(raw.get("model"), str):
        return result
    for key in ("prompt_eval_count", "eval_count", "prompt_eval_cached_count"):
        if type(raw.get(key)) is not int or raw[key] < 0:
            return result
    result.update(value=raw["prompt_eval_cached_count"], native_prompt_tokens=raw["prompt_eval_count"],
                  native_output_tokens=raw["eval_count"], pointer=prefix + "/prompt_eval_cached_count", missing=None)
    normalized_values = [v for v in (normalized, recorded) if type(v) is int]
    result["normalization_conflict"] = any(value != result["value"] for value in normalized_values)
    result["input_accounting"] = "prompt_eval_count already includes cached prompt tokens; cache is a subset"
    return result


def phase_timings(result, result_ref):
    """Expose measured boundaries, retaining nested spans without adding them."""
    records, missing = [], []
    anchor = (result.get("agent_process") or {}).get("started_at")

    def relative(value):
        try:
            return (datetime.fromisoformat(value) - datetime.fromisoformat(anchor)).total_seconds()
        except (TypeError, ValueError):
            return None

    def scalar(stage, seconds, ref, field, *, start=None, end=None, parent=None):
        if not number(seconds):
            return
        records.append({"stage": stage, "name": field, "elapsed_seconds": seconds,
            "started_at": start, "finished_at": end, "relative_start_seconds": relative(start),
            "relative_end_seconds": relative(end), "parent": parent,
            "source": {"ref": ref, "pointer": field}, "scope": "recorded_boundary_not_exclusive_active_time"})

    scalar("end_to_end", result.get("elapsed_seconds"), result_ref, "/elapsed_seconds")
    for key, stage in (("agent_process", "agent_process"), ("acceptance_process", "acceptance_process")):
        process = result.get(key) or {}
        scalar(stage, process.get("wall_seconds"), result_ref, f"/{key}/wall_seconds",
               start=process.get("started_at"), end=process.get("finished_at"), parent="end_to_end")
    sources = []
    if result.get("routing_result_ref"):
        route = read_bound(result["routing_result_ref"])
        scalar("routing", route.get("routing_elapsed_seconds"), result["routing_result_ref"],
               "/routing_elapsed_seconds", parent="agent_process")
        route_path = Path(route["routing_record_path"]).parent / "trace.json" if route.get("routing_record_path") else None
        if route_path is not None and route_path.is_file():
            sources.append((reference(route_path), "routing"))
    if result.get("product_run"):
        sources.append((result["product_run"]["manifest_ref"], "product"))
    if result.get("acceptance_result_ref"):
        delivery_ref = result["acceptance_result_ref"]
        delivery = read_bound(delivery_ref)
        scalar("delivery", delivery.get("delivery_seconds"), delivery_ref, "/delivery_seconds", parent="acceptance_process")
        sources.extend((ref, "delivery") for ref in delivery.get("execution_refs", []))
    seen = set()
    for ref, owner in sources:
        document = read_bound(ref)
        observed = (document.get("execution_observations") or {}).values() if owner != "routing" else document.get("observations", [])
        for row in observed:
            key = (row.get("trace_id"), row.get("id"))
            if key in seen:
                continue
            seen.add(key)
            name = row.get("name", "")
            if owner == "routing":
                stage = "routing"
            elif name.startswith("evidence.") or name == "source.inspect":
                stage = "investigation"
            elif name.startswith("requirements."):
                stage = "requirements"
            elif name.startswith("planning.") or name in {"workflow.plan_request", "workflow.planning_brief", "workflow.create_implementation_plan"}:
                stage = "planning"
            elif name in {"baseline_build", "validate.full_project_compilation", "workflow.build"}:
                stage = "build"
            elif name.startswith("validate."):
                stage = "candidate_validation"
            elif name.startswith("patch."):
                stage = "patch" if owner == "product" else "delivery"
            elif name == "workflow.isolated_apply":
                stage = "apply"
            elif name == "product.execution":
                stage = "product_execution"
            else:
                stage = "other_native"
            ms = row.get("elapsed_ms")
            scalar(stage, ms / 1000 if number(ms) else None, ref,
                   f"/execution_observations/{row.get('id')}/elapsed_ms" if owner != "routing" else
                   f"/observations/{document['observations'].index(row)}/elapsed_ms",
                   start=row.get("started_at"), end=row.get("finished_at"), parent=row.get("parent_id"))
            if number(ms):
                records[-1].update(observation_id=row.get("id"), trace_id=row.get("trace_id"),
                                   name=name, kind=row.get("kind"), status=row.get("status"), owner=owner)
    for stage in ("routing", "investigation", "planning", "patch", "build", "candidate_validation", "apply", "delivery", "acceptance_process"):
        if not any(row["stage"] == stage for row in records):
            missing.append({"stage": stage, "elapsed_seconds": None, "reason": "no_explicit_bound_timing_record"})
    missing.extend({"stage": stage, "elapsed_seconds": None, "reason": reason} for stage, reason in (
        ("formal_acceptance_only", "acceptance_process also includes delivery; no exclusive probe boundary selected"),
        ("human_wait", "no explicit operator-wait boundaries selected"),
        ("queue", "no explicit task queue boundaries selected")))
    return {"records": records, "missing": missing, "anchor": {"started_at": anchor, "source_ref": result_ref},
            "sum_seconds": None,
            "scope": "Each span includes children and may overlap other phases; do not add process, model, build and delivery spans. Relative timestamps use agent start; exclusive active time is unknown."}


def measure_trace(selection):
    """Reuse native observation deduplication; RG dispatches are a tool subset."""
    for key, filename in (("manifest_ref", "run_manifest.json"), ("result_ref", "run_result.json")):
        if Path(selection[key]["path"]).resolve() != (Path(selection["run_root"]) / filename).resolve():
            raise ValueError("Product reference and selected run disagree")
        read_bound(selection[key])
    measured = measure_product_task(**{key: selection[key] for key in ("allowed_root", "run_root", "run_id")})
    effects = extract_tool_effects(measured)
    manifest = read_bound(selection["manifest_ref"])
    rows = list((manifest.get("execution_observations") or {}).values())
    rg = [r for r in rows if r.get("kind") == "tool" and r.get("name") == "evidence.source_query"]
    dispatched = [(r.get("attributes") or {}).get("tool_dispatch_performed") for r in rg]
    usage = measured["model"]["usage"]
    calls = measured["model"]["calls"]
    cache_rows = []
    observations = manifest.get("execution_observations") or {}
    for call in calls:
        attrs = (observations.get(call["generation_span_id"]) or {}).get("attributes") or {}
        refs = attrs.get("local_detail_refs") or {}
        response_kind = next((kind for kind in ("transport_response", "provider_response", "response")
                              if refs.get(kind)), "response")
        cache_rows.append({"generation_span_id": call["generation_span_id"],
            **native_cache_measurement(refs.get(response_kind),
                                       (call.get("usage") or {}).get("cached_input_tokens"),
                                       response_kind=response_kind)})
    cache = total([row["value"] for row in cache_rows])
    if measured["coverage"]["segments_missing_observations"] or usage["unaccounted_request_possible"]:
        cache["total"] = None
    return {"selection": selection, "native_usage": usage,
            "cache_tokens": cache, "cache_token_records": cache_rows,
            "model_generation_records": len(calls),
            "model_transport_started": measured["model"]["recorded_transport_started_total"],
            "model_tool_requests": None,
            "model_tool_requests_missing_reason": "Native kind=tool spans include orchestrator tools; they do not establish model-origin requests",
            "native_tool_observations": measured["tools"]["selected_record_total"],
            "rg_actual_executions": sum(v is True for v in dispatched) if all(type(v) is bool for v in dispatched) and not measured["coverage"]["segments_missing_observations"] else None,
            "rg_dispatch_scope": "evidence.source_query tool_dispatch_performed; subset of tools, not query-lane or model-request count",
            "repeated_same_input_observations": effects["repeated_input_cost"]["observed_tool_calls"],
            "recovery_cost": effects["recovery_cost"], "coverage": measured["coverage"]}


def _routing_only_cost_coverage(result, ready, coverage, *, check, bound):
    """Prove a terminal initial clarification without inventing a product run."""
    records = Path(ready["records_root"]).resolve()
    profile = bound(ready["profile_ref"])
    argv = profile["arguments"]
    workspace = Path(argv[argv.index("--workspace-root") + 1]).resolve()
    natural = bound(result["routing_result_ref"])
    check("routing_record_matches_ready", Path(result["routing_result_ref"]["path"]).resolve() == records / "natural-result.json")
    check("routing_terminal_without_product", natural.get("status") == "needs_clarification"
          and natural.get("decision", {}).get("action") == "clarify"
          and natural.get("product_execution_started") is False
          and natural.get("product_owner_invoked") is False
          and natural.get("product_result") is None
          and result.get("success") is False)
    check("no_product_dispatch_or_acceptance", not result.get("product_run") and not result.get("dispatch_ref")
          and not (records / "dispatch.json").exists() and not (records / "product-process.json").exists()
          and not result.get("acceptance_process") and not result.get("acceptance_result_ref"))
    check("empty_product_workspace", workspace.is_dir()
          and {p.name for p in workspace.iterdir() if p.is_dir()} == {".dsh-routing"})
    route_path = Path(natural["routing_record_path"]).resolve()
    route_root = route_path.parent
    check("one_initial_route", route_root.parent == workspace / ".dsh-routing"
          and {p.name for p in route_root.parent.iterdir() if p.is_dir() and p.name != "conversations"} == {route_root.name}
          and natural.get("turn_id") == "initial")
    check("routing_terminal_matches", bound(reference(route_path)) == natural)
    trace = bound(reference(route_root / "trace.json"))
    requests = [row for row in trace["observations"] if row.get("name") == "model.request"]
    generations = [row for row in trace["observations"] if row.get("kind") == "generation"]
    check("one_routing_transport", natural.get("budget", {}).get("routing_model_call_limit") == 1
          and natural.get("routing_transport_calls") == 1 and len(requests) == 1 and len(generations) == 1
          and generations[0].get("parent_id") == requests[0].get("id"))
    usage = natural.get("routing_usage") or {}
    check("routing_usage_present", all(type(usage.get(k)) is int and usage[k] >= 0
                                      for k in ("input_tokens", "output_tokens")))
    for row in (*requests, *generations):
        attrs = row.get("attributes") or {}
        check("routing_response_complete_" + row["id"], row.get("status") == "completed"
              and attrs.get("transport_started") is True and attrs.get("response_complete") is True
              and all((attrs.get("usage") or {}).get(k) == usage[k] for k in ("input_tokens", "output_tokens")))
        for role in ("request", "response"):
            ref = attrs["local_detail_refs"][role]
            check("routing_body_contained", Path(ref["path"]).resolve().is_relative_to(route_root))
            bound_bytes(ref)
            coverage["basis_refs"].append(ref)
    # 为什么要有它：只有终态原件明确未调用产品且目录/trace相符时，产品成本0才是证据，而不是缺日志推断。
    coverage.update(routing_complete=True, product_complete=True, product_not_executed_proven=True,
                    product_model_calls=0, delivery_model_calls=0, other_model_calls=0,
                    routing_terminal_status=natural["status"],
                    product_cost_scope="zero from explicit nonexecution and bound initial route; no product trace asserted")
    return coverage


def infer_current_trial_cost_coverage(result, ready):
    """Qualify one fresh online runner attempt, not arbitrary historical runs.

    Delivery in this runner is Apply/Build/probe with no model invocation.
    为什么要有它：that code-path contract and complete native receipts are both
    necessary; a terminal success label cannot prove complete resource accounting.
    """
    coverage = {"routing_complete": False, "product_complete": False,
                "delivery_model_calls": None, "other_model_calls": None,
                "basis_refs": [], "checks": {}, "missing": [],
                "scope": "one fresh context-online-ab.run-result.v1 attempt; delivery Apply/Build/probe only"}

    def check(name, condition):
        coverage["checks"][name] = bool(condition)
        if not condition:
            raise ValueError(name)

    def bound(ref):
        value = read_bound(ref)
        coverage["basis_refs"].append(ref)
        return value

    try:
        check("current_runner_schema", result.get("schema") == "context-online-ab.run-result.v1")
        process = result.get("agent_process") or {}
        check("agent_terminal_without_timeout", process.get("started") is True
              and process.get("status") == "exited" and process.get("timeout") is False
              and type(process.get("exit_code")) is int and bool(process.get("finished_at")))
        for key in ("stdout_ref", "stderr_ref"):
            bound_bytes(process[key])
            coverage["basis_refs"].append(process[key])
        if not result.get("product_run"):
            return _routing_only_cost_coverage(result, ready, coverage, check=check, bound=bound)
        records = Path(ready["records_root"]).resolve()
        selection = result["product_run"]
        root = Path(selection["run_root"]).resolve()
        dispatch = bound(result["dispatch_ref"])
        check("dispatch_record_matches_ready", Path(result["dispatch_ref"]["path"]).resolve() == records / "dispatch.json")
        check("dispatch_matches_product", Path(dispatch["run_root"]).resolve() == root)
        profile = bound(ready["profile_ref"])
        argv = profile["arguments"]
        workspace = Path(argv[argv.index("--workspace-root") + 1]).resolve()
        check("fresh_single_product_root", root.parent == workspace and root.name == selection["run_id"]
              and {p.name for p in workspace.iterdir() if p.is_dir() and not p.name.startswith(".")} == {root.name})
        check("no_continuation_history", not (root / "continuations").exists())
        for key, filename in (("manifest_ref", "run_manifest.json"), ("result_ref", "run_result.json")):
            check("selected_" + key, Path(selection[key]["path"]).resolve() == root / filename)
        manifest, terminal = bound(selection["manifest_ref"]), bound(selection["result_ref"])
        check("no_parent_task", not manifest.get("parent_result_ref") and not terminal.get("parent_result_ref"))
        product_process_ref = reference(records / "product-process.json")
        child = bound(product_process_ref)
        check("product_child_exited", type(child.get("exit_code")) is int)
        child_result = json.loads(child["stdout"])
        check("product_child_identity", child_result.get("run_id") == selection["run_id"])

        natural = bound(result["routing_result_ref"])
        check("routing_record_matches_ready", Path(result["routing_result_ref"]["path"]).resolve() == records / "natural-result.json")
        route_path = Path(natural["routing_record_path"]).resolve()
        route_root = route_path.parent
        # Exclude only the routing owner's named conversation metadata container.
        # 为什么要有它：conversation receipts are not another model route; all other directories still expose additional attempts.
        check("one_initial_route", route_root.parent == workspace / ".dsh-routing"
              and {p.name for p in route_root.parent.iterdir() if p.is_dir() and p.name != "conversations"} == {route_root.name}
              and natural.get("turn_id") == "initial"
              and natural.get("decision", {}).get("action") in {"modify_project", "new_project"}
              and natural.get("product_result", {}).get("run_id") == selection["run_id"])
        route_result = bound(reference(route_path))
        check("routing_terminal_matches", route_result == natural)
        route_trace = bound(reference(route_root / "trace.json"))
        model_rows = [row for row in route_trace["observations"] if row.get("name") == "model.request"]
        generations = [row for row in route_trace["observations"] if row.get("kind") == "generation"]
        check("one_routing_transport", natural.get("budget", {}).get("routing_model_call_limit") == 1
              and natural.get("routing_transport_calls") == 1 and len(model_rows) == 1 and len(generations) == 1
              and generations[0].get("parent_id") == model_rows[0].get("id"))
        usage = natural.get("routing_usage") or {}
        check("routing_usage_present", all(type(usage.get(k)) is int and usage[k] >= 0
                                          for k in ("input_tokens", "output_tokens")))
        for row in (*model_rows, *generations):
            attrs = row.get("attributes") or {}
            check("routing_response_complete_" + row["id"], row.get("status") == "completed"
                  and attrs.get("transport_started") is True and attrs.get("response_complete") is True
                  and all((attrs.get("usage") or {}).get(k) == usage[k] for k in ("input_tokens", "output_tokens")))
            for role in ("request", "response"):
                ref = attrs["local_detail_refs"][role]
                check("routing_body_contained", Path(ref["path"]).resolve().is_relative_to(route_root))
                bound_bytes(ref)
                coverage["basis_refs"].append(ref)
        coverage["routing_complete"] = True

        measured = measure_product_task(**{key: selection[key] for key in ("allowed_root", "run_root", "run_id")})
        check("product_measurement_same_binding", all(
            Path(measured["segments"][0][key]["path"]).resolve() == Path(selection[key]["path"]).resolve()
            and measured["segments"][0][key]["sha256"] == selection[key]["sha256"]
            for key in ("manifest_ref", "result_ref")))
        observed = measured["coverage"]
        check("product_native_observations_complete", not observed["segments_missing_observations"]
              and not observed["unverified_model_local_evidence"]
              and measured["model"]["usage"]["unaccounted_request_possible"] is False
              and not measured["model"]["request_records_without_generation"]
              and measured["model"]["recorded_transport_started_total"] == measured["model"]["generation_records"])
        check("product_usage_complete", all(type(measured["model"]["usage"][k]["total"]) is int
                                          for k in ("input_tokens", "output_tokens")))
        check("product_all_generations_terminal", all(call.get("status") == "completed" for call in measured["model"]["calls"]))
        coverage.update(product_complete=True, delivery_model_calls=0, other_model_calls=0)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        coverage["missing"].append(f"{type(error).__name__}: {error}")
    return coverage


def selected_metric(spec):
    """Resolve an explicitly selected source field, without guessing metric names."""
    return pointer(read_bound(spec["ref"]), spec["pointer"])


def query_sets(sources):
    """Count each explicitly selected query-set receipt once."""
    seen, rows = set(), []
    for source in sources:
        key = (source["ref"]["sha256"], source["pointer"])
        if key in seen:
            raise ValueError("Duplicate query-set receipt")
        seen.add(key)
        budget = selected_metric(source)
        reuse = budget.get("query_observation_reuse", {}) if isinstance(budget, dict) else {}
        rows.append({"source": source, "query_count": budget.get("query_count") if isinstance(budget, dict) else None,
                     "actual_collect_calls": reuse.get("collect_calls"), "reused_lanes": reuse.get("reused_lanes")})
    return {"receipts": rows, "scope": "explicit query-set receipts; query lanes are not model-origin tool requests",
            **{key: total([row[key] for row in rows]) for key in ("query_count", "actual_collect_calls", "reused_lanes")}}


def inspect_startup(indexed):
    startup = {"startup_condition_version": "legacy_unclassified", "condition_classification": "unknown",
               "warmup": {"elapsed_seconds": None, "input_tokens": None, "output_tokens": None,
                          "cache_tokens": None}, "startup_ref": (indexed or {}).get("startup_ref")}
    if not startup["startup_ref"]:
        return startup
    try:
        raw = read_bound(startup["startup_ref"])
        version = raw["startup_condition_version"]
        if not isinstance(version, str) or not version:
            raise ValueError("Startup condition version required")
        startup.update(startup_condition_version=version,
                       condition_classification=raw["condition_classification"],
                       classification_origin="bound startup observer record")
        if raw["condition_classification"] not in {"hot_verified", "unknown", "deviation"}:
            raise ValueError("Unsupported startup classification")
        warmup = read_bound(raw["warmup_ref"])
        for role in ("request_ref", "response_ref"):
            bound_bytes(warmup[role])
        startup["warmup_ref"] = raw["warmup_ref"]
        startup["warmup"] = {"elapsed_seconds": warmup.get("elapsed_seconds"),
            "input_tokens": warmup.get("input_tokens"), "output_tokens": warmup.get("output_tokens"),
            "load_ns": warmup.get("load_ns"), "eval_ns": warmup.get("eval_ns")}
        startup["warmup_cache_measurement"] = native_cache_measurement(
            warmup["response_ref"], warmup.get("cached_input_tokens"), native_transport=True)
        startup["warmup"]["cache_tokens"] = startup["warmup_cache_measurement"]["value"]
        for ref in raw["residency_refs"]:
            bound_bytes(ref)
        if not raw["residency_refs"]:
            raise ValueError("Startup residency evidence missing")
        startup["residency_refs"] = raw["residency_refs"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        startup.update(condition_classification="unknown", measurement_error=f"{type(error).__name__}: {error}")
    return startup


def inspect_run(planned, indexed):
    row = {**planned, "status": "not_executed", "success": None, "elapsed_seconds": None,
           "attempt_started": False if indexed is None else None,
           "startup": inspect_startup(indexed),
           "metrics": {}, "missing": [], "exposure": "development_exposed_not_blind_holdout"}
    if indexed is None:
        return row
    ref = indexed["result_ref"]
    row["result_ref"] = ref
    try:
        result = read_bound(ref)
        if indexed.get("wrapper_only") is True:
            if result.get("schema") != "context-online-ab.hot-wrapper-result.v1" or result.get("trial_id") != planned.get("trial_id"):
                raise ValueError("Wrapper identity does not match registered trial")
            if result.get("startup_ref") != indexed.get("startup_ref"):
                raise ValueError("Wrapper startup evidence changed")
            row["wrapper_ref"] = ref
            row["attempt_started"] = result.get("task_started")
            row["status"] = "startup_failed_before_task" if result.get("task_started") is False else "missing_task_result"
            # No task started is explicit wrapper evidence, not an inferred task failure.
            # 为什么要有它：preparation expense survives while an unexecuted task cannot become a success or a scored content failure.
            if result.get("task_started") is False:
                row["elapsed_seconds"] = 0
                row["metrics"].update(input_tokens=0, output_tokens=0, cache_tokens=0)
            return row
        if identity(result) != identity(planned):
            raise ValueError("Result identity does not match registered trial")
        fields = {"success": "/success", "elapsed_seconds": "/elapsed_seconds", **indexed.get("result_fields", {})}
        success = pointer(result, fields["success"])
        row.update(status=result.get("status", "unknown"), success=success if type(success) is bool else None)
        started = (result.get("agent_process") or {}).get("started")
        row["attempt_started"] = started if type(started) is bool else None
        elapsed = pointer(result, fields["elapsed_seconds"])
        row["elapsed_seconds"] = elapsed if number(elapsed) else None
        row["field_sources"] = {k: {"ref": ref, "pointer": v} for k, v in fields.items()}
        if indexed.get("wrapper_ref"):
            wrapper = read_bound(indexed["wrapper_ref"])
            if wrapper.get("task_result_ref") != ref or wrapper.get("startup_ref") != indexed.get("startup_ref"):
                raise ValueError("Terminal wrapper references disagree with selected evidence")
            row["wrapper_ref"] = indexed["wrapper_ref"]
        row["process_log_refs"] = []
        for name in ("agent_process", "acceptance_process"):
            for key in ("stdout_ref", "stderr_ref"):
                log = (result.get(name) or {}).get(key)
                if log is not None:
                    bound_bytes(log)
                    row["process_log_refs"].append({"process": name, "stream": key, "ref": log})
        for name in ("acceptance_result_ref", "routing_result_ref", "human_intervention_refs", "retry_refs"):
            if result.get(name) is not None:
                refs = result[name] if isinstance(result[name], list) else [result[name]]
                for evidence in refs:
                    read_bound(evidence)
                row[name] = result[name]
        routing = read_bound(result["routing_result_ref"]) if result.get("routing_result_ref") else {}
        row["routing_usage"] = routing.get("routing_usage") or {}
        if result.get("product_run"):
            trace = measure_trace(result["product_run"])
            row["trace_measurement"] = trace
            for key in ("input_tokens", "output_tokens"):
                row["metrics"]["selected_product_" + key] = trace["native_usage"][key]["total"]
            row["metrics"]["rg_actual_executions"] = trace["rg_actual_executions"]
        else:
            row["missing"].append("native product trace unavailable")
        # Additional records can expose route usage, query lanes or interventions.
        # 为什么要有它：explicit provenance avoids interpreting absent counters as zero.
        row["additional_metrics"] = {name: {"value": selected_metric(spec), "source": spec}
                                     for name, spec in indexed.get("metric_sources", {}).items()}
        row["rg_query_sets"] = query_sets(indexed.get("rg_query_sets", []))
        coverage = result.get("cost_coverage") or {}
        row["recorded_cost_coverage"] = coverage
        if result.get("schema") == "context-online-ab.run-result.v1" and result.get("trial_ref"):
            trial = read_bound(result["trial_ref"])
            if identity(trial) != identity(planned):
                raise ValueError("Bound trial identity does not match registered slot")
            ready = read_bound(trial["ready_ref"])
            coverage = infer_current_trial_cost_coverage(result, ready)
            row["cost_coverage_derivation"] = {"trial_ref": result["trial_ref"], "ready_ref": trial["ready_ref"],
                "method": "infer_current_trial_cost_coverage; original result remains unchanged"}
        covered = (coverage.get("routing_complete") is True and coverage.get("product_complete") is True
                   and type(coverage.get("delivery_model_calls")) is int and coverage["delivery_model_calls"] == 0
                   and type(coverage.get("other_model_calls")) is int and coverage["other_model_calls"] == 0)
        row["cost_coverage"] = coverage
        if coverage.get("product_not_executed_proven") is True:
            row.update(recorded_status=result.get("status"),
                       execution_outcome=coverage["routing_terminal_status"], delivery_outcome="not_delivered",
                       product_execution_started=False, product_owner_invoked=False)
            row["product_nonexecution_measurement"] = {"model_calls": 0, "input_tokens": 0,
                "output_tokens": 0, "cache_tokens": 0, "basis_refs": coverage["basis_refs"],
                "scope": coverage["product_cost_scope"]}
            row["metrics"].update(selected_product_input_tokens=0, selected_product_output_tokens=0,
                                  rg_actual_executions=0)
            row["missing"] = [item for item in row["missing"] if item != "native product trace unavailable"]
        for key in ("input_tokens", "output_tokens", "cached_input_tokens"):
            route_value = row["routing_usage"].get(key)
            if type(route_value) is not int or route_value < 0:
                route_value = None
            product = row.get("trace_measurement", {})
            if key == "cached_input_tokens":
                native = product.get("cache_tokens", {})
                metric = "cache_tokens"
            else:
                native = product.get("native_usage", {}).get(key, {})
                metric = key
            if coverage.get("product_not_executed_proven") is True:
                native = {"total": 0, "known_subtotal": 0}
            product_value = native.get("total")
            row["metrics"][metric] = route_value + product_value if covered and number(route_value) and number(product_value) else None
            row["metrics"]["known_" + metric + "_subtotal"] = sum(v for v in (route_value, native.get("known_subtotal")) if number(v))
        if not covered:
            row["missing"].append("whole-run token total requires route, product, retries and delivery coverage; selected product cost is not full cost")
        try:
            row["phase_timings"] = phase_timings(result, ref)
        except (OSError, ValueError, KeyError, TypeError) as error:
            row["phase_timings"] = {"records": [], "sum_seconds": None,
                "measurement_error": f"{type(error).__name__}: {error}"}
    except (OSError, ValueError, KeyError, TypeError) as error:
        row.update(status="invalid_measurement", success=None)
        row["measurement_error"] = f"{type(error).__name__}: {error}"
    return row


def combined_cost(rows, name):
    """Keep delivery and warmup scopes distinct while accounting for both."""
    delivery = [row["elapsed_seconds"] if name == "elapsed_seconds" else row["metrics"].get(name) for row in rows]
    warmup = [row["startup"]["warmup"].get(name) for row in rows]
    return {"delivery": total(delivery), "warmup": total(warmup),
            "including_warmup": total([*delivery, *warmup])}


def actual_condition_index(reference_value, order, order_ref):
    """Read an explicitly selected, protocol-bound host condition annotation."""
    if reference_value is None:
        return None
    document = read_bound(reference_value)
    if (document.get("schema") != "online-ab-actual-host-conditions.v1" or order_ref is None
            or document.get("protocol_ref") != order_ref or read_bound(order_ref) != order):
        raise ValueError("Actual conditions must bind this exact protocol")
    strata = document.get("strata", [])
    named = {row.get("id"): row for row in strata}
    if (len(named) != len(strata) or any(not isinstance(key, str) or not key
            or key.lower() in {"unknown", "unverified"} for key in named)):
        raise ValueError("Actual condition strata require unique known identities")
    trials = document.get("trials", [])
    indexed = {row.get("trial_id"): row for row in trials}
    planned = {row.get("trial_id") for row in order.get("order", order.get("trials", []))}
    if len(indexed) != len(trials) or None in indexed or not set(indexed) <= planned:
        raise ValueError("Actual conditions contain duplicate or unregistered trials")
    excerpts = {row["id"]: row for row in document.get("log_excerpts", [])}
    return {"ref": reference_value, "strata": named, "trials": indexed, "excerpts": excerpts}


def annotate_actual_condition(row, selected):
    annotation = {"verified": False, "stratum": None, "evidence_refs": [],
                  "status": "dimension_not_verified_no_conditions_input" if selected is None else "trial_not_annotated"}
    row.update(actual_execution_stratum=None, actual_execution_condition=annotation)
    if selected is None:
        return
    annotation["conditions_ref"] = selected["ref"]
    value = selected["trials"].get(row.get("trial_id"))
    if value is None:
        return
    try:
        name = value["actual_execution_stratum"]
        if name not in selected["strata"]:
            raise ValueError("Unknown actual execution stratum")
        evidence = [value[key] for key in ("initial_residency_ref", "initial_residency_validation_ref",
                    "startup_before_task_ref", "warmup_request_ref")]
        log_ids = value.get("runner_load_log_ids", [])
        if not log_ids:
            raise ValueError("Runner log evidence required")
        evidence.extend(selected["excerpts"][key]["excerpt_ref"] for key in log_ids)
        for item in evidence:
            bound_bytes(item)
        initial = read_bound(value["startup_before_task_ref"])
        if initial.get("trial_id") != row.get("trial_id") or initial.get("protocol_ref") != read_bound(selected["ref"])["protocol_ref"]:
            raise ValueError("Actual condition startup identity mismatch")
        models = read_bound(value["initial_residency_ref"]).get("models", [])
        observed = value["observed_initial_residency"]
        if (len(models) != 1 or any(models[0].get(key) != expected for key, expected in observed.items())
                or models[0].get("digest") != selected["strata"][name].get("model_digest")
                or models[0].get("context_length") != selected["strata"][name].get("context_length")):
            raise ValueError("Actual condition residency identity mismatch")
        annotation.update(stratum=name, status="initial_evidence_only", evidence_refs=evidence)
        row["actual_execution_stratum"] = name
        # 为什么要有它：初始驻留只能关联环境，不能替代终态完整观察；后来结束的槽须用新增条件版本绑定实际终态。
        if value.get("terminal_ref") != row.get("result_ref") or not value.get("terminal_ref"):
            return
        completed = value.get("completed_startup_ref")
        if not completed or completed != row["startup"].get("startup_ref"):
            return
        bound_bytes(value["terminal_ref"])
        bound_bytes(completed)
        annotation["evidence_refs"].extend([value["terminal_ref"], completed])
        annotation.update(verified=True, status="verified_bound_host_annotation")
    except (OSError, ValueError, KeyError, TypeError) as error:
        annotation.update(verified=False, status="condition_evidence_unavailable", measurement_error=f"{type(error).__name__}: {error}")


def summarize(order, records, *, actual_conditions_ref=None, order_ref=None):
    planned = order.get("order", order.get("trials"))
    keys = [identity(row) for row in planned]
    tasks = {key[0] for key in keys}
    expected = {(task, arm, repeat) for task in tasks for arm in ("baseline", "candidate") for repeat in (1, 2)}
    if len(tasks) != 5 or len(keys) != 20 or set(keys) != expected:
        raise ValueError("Expected exactly 5 tasks x baseline/candidate x repeats 1/2")
    indexed = {}
    for row in records.get("runs", []):
        key = identity(row)
        if key not in expected or key in indexed:
            raise ValueError("Duplicate or unregistered trial")
        indexed[key] = row
    rows = [inspect_run(row, indexed.get(identity(row))) for row in planned]
    actual_conditions = actual_condition_index(actual_conditions_ref, order, order_ref)
    for row in rows:
        annotate_actual_condition(row, actual_conditions)
    pending = {identity(row): row for row in records.get("pending", [])}
    for row in rows:
        observed = pending.get(identity(row))
        if row["status"] != "not_executed" or not observed:
            continue
        if observed.get("reason") == "discovery_evidence_unavailable":
            # Failed observation cannot establish that execution never started.
            # 为什么要有它：permission errors and hash drift are measurement failures, not task outcomes or proof of no attempt.
            row.update(status="evidence_unavailable", success=None, attempt_started=None,
                       execution_state="unknown_evidence_unavailable",
                       live_process_state="unknown_not_inferred_from_files", discovery_error=observed)
            continue
        if observed.get("reason") != "awaiting_terminal_evidence":
            continue
        refs = observed.get("start_evidence_refs", [])
        for ref in refs:
            bound_bytes(ref)
        if refs:
            row.update(status="awaiting_terminal_evidence", attempt_started=None,
                       start_evidence_refs=refs, execution_state="incomplete",
                       live_process_state="unknown_not_inferred_from_files")
    extras = []
    seen_results = {(Path(row["result_ref"]["path"]).resolve(), row["result_ref"]["sha256"])
                    for row in indexed.values()}
    for extra in order.get("additional_attempts", []):
        if identity(extra) not in expected:
            raise ValueError("Additional attempt must identify its registered slot")
        ref = extra["result_ref"]
        result_key = (Path(ref["path"]).resolve(), ref["sha256"])
        if result_key in seen_results:
            raise ValueError("Attempt evidence counted more than once")
        seen_results.add(result_key)
        extra_row = inspect_run({key: extra[key] for key in ("task_id", "arm", "repeat")}, extra)
        extra_row["classification"] = extra["classification"]
        extra_row["classification_origin"] = "protocol_additional_attempts; original status preserved"
        extra_row["classification_evidence_refs"] = extra.get("classification_evidence_refs", [])
        for ref in extra_row["classification_evidence_refs"]:
            bound_bytes(ref)
        # Only explicit bound token measurements can replace unknown extra costs.
        # 为什么要有它：missing route/dispatch files alone do not prove zero provider usage.
        for name in ("input_tokens", "output_tokens", "cache_tokens"):
            observed = extra_row.get("additional_metrics", {}).get(name, {}).get("value")
            if type(observed) is int and observed >= 0:
                extra_row["metrics"][name] = observed
        annotate_actual_condition(extra_row, actual_conditions)
        extras.append(extra_row)
    groups = {}
    for arm in ("baseline", "candidate"):
        selected = [r for r in rows if r["arm"] == arm]
        complete = all(type(r["success"]) is bool for r in selected)
        task_rows = {task: [r for r in selected if r["task_id"] == task] for task in sorted(tasks)}
        atleast = sum(any(r["success"] is True for r in pair) for pair in task_rows.values())
        both = sum(all(r["success"] is True for r in pair) for pair in task_rows.values())
        groups[arm] = {"registered_runs": 10, "distinct_tasks": 5, "complete": complete,
            "success_runs": sum(r["success"] is True for r in selected), "success_denominator": 10,
            "completion_fraction": sum(r["success"] is True for r in selected) / 10 if complete else None,
            "task_at_least_once": atleast, "task_both_success": both, "task_denominator": 5,
            "observed_pass_at_2": atleast / 5 if complete else None,
            "observed_pass_power_2": both / 5 if complete else None,
            "unknown_outcomes": sum(r["success"] is None for r in selected),
            "outcomes": dict(Counter(r["status"] for r in selected)),
            "elapsed_seconds_all_runs": distribution([r["elapsed_seconds"] for r in selected]),
            "elapsed_seconds_all_runs_scope": "All registered attempts, including failures and unknown/mixed execution conditions; diagnostic distribution, not a single-environment strategy latency percentile.",
            "cost_all_runs_including_failures": {name: total([r["metrics"].get(name) for r in selected])
                for name in ("input_tokens", "output_tokens", "cache_tokens", "selected_product_input_tokens",
                             "selected_product_output_tokens", "known_input_tokens_subtotal", "known_output_tokens_subtotal",
                             "known_cache_tokens_subtotal", "rg_actual_executions")}}
    pairs = []
    for task in sorted(tasks):
        for repeat in (1, 2):
            pair = {r["arm"]: r for r in rows if r["task_id"] == task and r["repeat"] == repeat}
            if all(r["success"] is True and number(r["elapsed_seconds"]) for r in pair.values()):
                same_actual = (all(r["actual_execution_condition"]["verified"] is True for r in pair.values())
                    and len({r["actual_execution_stratum"] for r in pair.values()}) == 1
                    and all(r["actual_execution_stratum"] is not None for r in pair.values()))
                same_startup = (len({r["startup"]["startup_condition_version"] for r in pair.values()}) == 1
                    and all(r["startup"]["condition_classification"] == "hot_verified" for r in pair.values()))
                pairs.append({"task_id": task, "repeat": repeat,
                              "startup_versions": {arm: r["startup"]["startup_condition_version"] for arm, r in pair.items()},
                              "startup_verified_comparable": same_startup,
                              "actual_execution_strata": {arm: r["actual_execution_stratum"] for arm, r in pair.items()},
                              "actual_execution_verified_comparable": same_actual,
                              "verified_comparable": same_startup and same_actual,
                              "actual_condition_evidence_refs": {arm: r["actual_execution_condition"]["evidence_refs"] for arm, r in pair.items()},
                              **{arm: r["elapsed_seconds"] for arm, r in pair.items()}})
    all_attempts = [*rows, *extras]
    seen_warmups = set()
    for row in all_attempts:
        warmup_ref = row["startup"].get("warmup_ref")
        if warmup_ref:
            key = (Path(warmup_ref["path"]).resolve(), warmup_ref["sha256"])
            if key in seen_warmups:
                raise ValueError("Warmup cost evidence counted more than once")
            seen_warmups.add(key)
    conditions = {}
    versions = {row["startup"]["startup_condition_version"] for row in rows
                if row["attempt_started"] is True or row["startup"].get("startup_ref")}
    for version in sorted(versions):
        selected_pairs = [p for p in pairs if p["startup_verified_comparable"] and set(p["startup_versions"].values()) == {version}
                          and (actual_conditions is None or p["actual_execution_verified_comparable"])]
        mixed_actual = actual_conditions is not None and len({next(iter(p["actual_execution_strata"].values())) for p in selected_pairs}) > 1
        if mixed_actual:
            selected_pairs = []
        conditions[version] = {"registered_run_observations": [identity(r) for r in rows
            if r["startup"]["startup_condition_version"] == version and r["attempt_started"] is True],
            "condition_classifications": dict(Counter(r["startup"]["condition_classification"] for r in rows
                if r["startup"]["startup_condition_version"] == version and r["attempt_started"] is True)),
            "paired_success_seconds": {"pairs": selected_pairs, "n": len(selected_pairs),
                "mixed_actual_conditions_suppressed": mixed_actual,
                **{arm: distribution([p[arm] for p in selected_pairs]) for arm in groups}},
            "by_arm_outcomes": {arm: {
                "registered_denominator": 10,
                "success_runs": sum(r["success"] is True for r in rows if r["arm"] == arm
                    and r["startup"]["startup_condition_version"] == version),
                "known_outcomes": sum(type(r["success"]) is bool for r in rows if r["arm"] == arm
                    and r["startup"]["startup_condition_version"] == version),
                "completion_fraction": groups[arm]["completion_fraction"] if all(
                    r["startup"]["startup_condition_version"] == version for r in rows if r["arm"] == arm) else None,
                "observed_pass_at_2": groups[arm]["observed_pass_at_2"] if all(
                    r["startup"]["startup_condition_version"] == version for r in rows if r["arm"] == arm) else None,
                "observed_pass_power_2": groups[arm]["observed_pass_power_2"] if all(
                    r["startup"]["startup_condition_version"] == version for r in rows if r["arm"] == arm) else None}
                for arm in groups},
            "by_arm_cost": {arm: {name: combined_cost([r for r in all_attempts
                if r["arm"] == arm and r["startup"]["startup_condition_version"] == version], name)
                for name in ("elapsed_seconds", "input_tokens", "output_tokens", "cache_tokens")}
                for arm in groups}}
    # Cross-condition timing is retained per run, never pooled as an optimization gain.
    # 为什么要有它：model loading and residency differences can dominate a strategy's apparent latency.
    actual_groups = {}
    for row in all_attempts:
        name = row["actual_execution_stratum"]
        key = (row["startup"]["startup_condition_version"], name)
        actual_groups.setdefault(key, []).append(row)
    actual_summaries = []
    registered_objects = {id(row) for row in rows}
    for (version, name), members in sorted(actual_groups.items(), key=lambda item: (item[0][0], item[0][1] or "")):
        registered_members = [row for row in members if id(row) in registered_objects]
        selected_pairs = [p for p in pairs if p["verified_comparable"] and set(p["startup_versions"].values()) == {version}
                          and set(p["actual_execution_strata"].values()) == {name}]
        actual_summaries.append({"startup_condition_version": version, "actual_execution_stratum": name,
            "registered_run_observations": [identity(r) for r in registered_members],
            "additional_attempt_observations": [{"identity": identity(r), "result_ref": r["result_ref"]}
                for r in members if id(r) not in registered_objects],
            "verified_condition_runs": sum(r["actual_execution_condition"]["verified"] for r in members),
            "by_arm_observed_outcomes": {arm: {"registered_denominator": 10,
                "observed_runs_in_stratum": sum(r["arm"] == arm for r in registered_members),
                "success_runs": sum(r["arm"] == arm and r["success"] is True for r in registered_members),
                "unknown_outcomes": sum(r["arm"] == arm and r["success"] is None for r in registered_members)} for arm in groups},
            # 为什么要有它：环境分层不能挑掉失败成本或漏掉未归类尝试；所有记录恰属一层，未知仍是未知，整体账目不变。
            "by_arm_observed_cost": {arm: {
                "scope": "All registered and additional attempts in this stratum, including failures; delivery and warmup separated; unknown values retained.",
                **{metric: combined_cost([r for r in members if r["arm"] == arm], metric)
                   for metric in ("elapsed_seconds", "input_tokens", "output_tokens", "cache_tokens")},
                "other_metrics": {metric: total([r["metrics"].get(metric) for r in members if r["arm"] == arm])
                    for metric in ("known_input_tokens_subtotal", "known_output_tokens_subtotal", "known_cache_tokens_subtotal", "rg_actual_executions")}}
                for arm in groups},
            "paired_success_seconds": {"pairs": selected_pairs, "n": len(selected_pairs),
                **{arm: distribution([p[arm] for p in selected_pairs]) for arm in groups}}})
    # 为什么要有它：未知环境不能通过unknown==unknown得到可比结论；缺少新输入的历史调用仍保持旧统计，但明确未核验这一维。
    comparable = [p for p in pairs if p["verified_comparable"]]
    comparable_strata = {(next(iter(p["startup_versions"].values())), next(iter(p["actual_execution_strata"].values()))) for p in comparable}
    descriptive_pairs = (comparable if len(comparable_strata) <= 1 else []) if actual_conditions is not None else pairs if len(versions) <= 1 else []
    registered_started = sum(row["attempt_started"] is True for row in rows)
    extra_started = sum(row["attempt_started"] is True for row in extras)
    unknown_starts = sum(row["attempt_started"] is None for row in all_attempts)
    return {"schema": "context-online-ab.summary.v3", "summarizer_version": "3.8",
            "read_only": True, "model_calls_for_summary": 0,
            "distinct_tasks": 5, "registered_runs": 20, "blind_holdout_tasks": 0,
            "runs": rows, "by_arm": groups,
            "by_startup_condition": conditions,
            "actual_conditions_ref": actual_conditions_ref,
            "actual_condition_dimension": "explicit_bound_conditions" if actual_conditions is not None else "not_verified_no_conditions_input",
            "by_actual_execution_condition": actual_summaries,
            "all_joint_success_pairs": pairs,
            "additional_attempts": extras,
            "attempt_accounting": {"registered_executed": registered_started,
                "additional_executed": extra_started,
                "total_attempts": registered_started + extra_started if not unknown_starts else None,
                "known_started_attempts": registered_started + extra_started,
                "unknown_start_status": unknown_starts,
                "scope": "actual agent process starts; extra admission failures do not change registered outcome denominators"},
            "all_attempt_costs_including_additional": {arm: {
                "elapsed_seconds": total([r["elapsed_seconds"] for r in all_attempts if r["arm"] == arm]),
                "with_warmup": {name: combined_cost([r for r in all_attempts if r["arm"] == arm], name)
                    for name in ("elapsed_seconds", "input_tokens", "output_tokens", "cache_tokens")},
                **{name: total([r["metrics"].get(name) for r in all_attempts if r["arm"] == arm])
                   for name in ("input_tokens", "output_tokens", "cache_tokens", "known_input_tokens_subtotal", "known_output_tokens_subtotal")}}
                for arm in ("baseline", "candidate")},
            "paired_success_seconds": {"pairs": descriptive_pairs, "n": len(descriptive_pairs),
                "scope": "Verified same-condition pairs only; use by_actual_execution_condition for strata" if actual_conditions is not None
                    else "legacy descriptive only; actual execution configuration dimension not verified",
                "mixed_conditions_suppressed": (len(comparable_strata) > 1 or any(not p["verified_comparable"] for p in pairs)) if actual_conditions is not None else len(versions) > 1,
                **{arm: distribution([p[arm] for p in descriptive_pairs]) for arm in groups}},
            "comparison_claim": None,
            "scope": "Descriptive observed outcomes; no automatic causal or independent-holdout claim. Phase spans are never summed as wall time."}


def discover_records(protocol, protocol_ref=None):
    """Discover only terminal originals; live hot wrappers remain pending."""
    result = {"schema": "context-online-ab.records.v1", "protocol_ref": protocol_ref, "runs": [], "pending": []}
    hot = bool(protocol.get("startup_condition")) or ".hot." in protocol.get("schema_version", "")
    for registered in protocol["trials"]:
        row = {key: registered[key] for key in ("trial_id", "task_id", "arm", "repeat")}
        try:
            trial = read_bound(registered["trial_ref"])
            if identity(trial) != identity(registered) or trial.get("trial_id") != registered["trial_id"]:
                raise ValueError("Registered trial identity changed")
            output = Path(trial["output_root"]).resolve()
            task_path = output / "result.json"
            startup_root = output.parent / f"{registered['trial_id']}-startup-hot-v1"
            wrapper_path = startup_root / "result.json"
            # Receipts establish observed preparation/admission, never a live process.
            # 为什么要有它：an interrupted attempt must not become not-executed merely because its terminal record is absent.
            start_evidence = [reference(path) for path in (
                output / "admission.json", startup_root / "startup-before-task.json",
                startup_root / "warmup-request.json", startup_root / "preflight-command.json") if path.is_file()]
            if hot or startup_root.exists():
                if not wrapper_path.is_file():
                    result["pending"].append({**row,
                        "reason": "awaiting_terminal_evidence" if start_evidence else "hot_wrapper_not_terminal",
                        "start_evidence_refs": start_evidence,
                        "live_process_state": "unknown_not_inferred_from_files"})
                    continue
                wrapper_ref = reference(wrapper_path)
                wrapper = read_bound(wrapper_ref)
                if (wrapper.get("schema") != "context-online-ab.hot-wrapper-result.v1"
                        or wrapper.get("trial_id") != registered["trial_id"]):
                    raise ValueError("Unexpected hot wrapper terminal")
                startup_ref = wrapper["startup_ref"]
                if Path(startup_ref["path"]).resolve() != startup_root / "startup.json":
                    raise ValueError("Unexpected startup receipt path")
                read_bound(startup_ref)
                row.update(startup_ref=startup_ref, wrapper_ref=wrapper_ref)
                if wrapper.get("task_result_ref") is None:
                    row.update(result_ref=wrapper_ref, wrapper_only=True)
                else:
                    task_ref = wrapper["task_result_ref"]
                    if Path(task_ref["path"]).resolve() != task_path:
                        raise ValueError("Unexpected task result path")
                    read_bound(task_ref)
                    row["result_ref"] = task_ref
            elif task_path.is_file():
                row["result_ref"] = reference(task_path)
                read_bound(row["result_ref"])
            else:
                result["pending"].append({**row,
                    "reason": "awaiting_terminal_evidence" if start_evidence else "task_result_not_available",
                    "start_evidence_refs": start_evidence,
                    "live_process_state": "unknown_not_inferred_from_files"})
                continue
            result["runs"].append(row)
        except (OSError, ValueError, TypeError, KeyError) as error:
            result["pending"].append({**row, "reason": "discovery_evidence_unavailable",
                "unverified_trial_ref": registered.get("trial_ref"),
                "error_type": type(error).__name__, "error": str(error)})
    return result


def preserve_source_version(directory, source_path=None):
    """Preserve exact bytes before a future host edit changes the live source."""
    source_path = Path(source_path or __file__).resolve()
    raw = source_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    versions = Path(directory) / "source-versions"
    versions.mkdir(parents=True, exist_ok=True)
    saved = versions / f"{digest}.py"
    try:
        with saved.open("xb") as handle:
            handle.write(raw)
    except FileExistsError:
        if saved.read_bytes() != raw:
            raise ValueError("Preserved source version has conflicting bytes") from None
    return {"summarizer_ref": {"path": str(saved.resolve()), "sha256": digest},
            "origin_ref": {"path": str(source_path), "sha256": digest}}


def preserve_loaded_dependencies(directory):
    """Bind imported project code alongside the host summarizer."""
    root = Path(__file__).resolve().parent.parent
    rows = []
    for name, module in sorted(sys.modules.items()):
        raw_path = getattr(module, "__file__", None)
        if not raw_path:
            continue
        path = Path(raw_path).resolve()
        if path.suffix != ".py" or not path.is_relative_to(root) or path == Path(__file__).resolve():
            continue
        if path.relative_to(root).parts[0] not in {"src", "scripts"}:
            continue
        saved = preserve_source_version(directory, path)
        rows.append({"module": name, "source_ref": saved["summarizer_ref"], "origin_ref": saved["origin_ref"]})
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--order", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--records", type=Path)
    source.add_argument("--discover-records", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--actual-conditions", type=Path,
                        help="Explicit protocol-bound actual host conditions; never inferred from unrelated batches")
    args = parser.parse_args(argv)
    order_ref = reference(args.order)
    order = read_bound(order_ref)
    source_refs = preserve_source_version(args.output.parent)
    dependencies_before = preserve_loaded_dependencies(args.output.parent)
    if args.discover_records:
        records = discover_records(order, order_ref)
        index_path = args.output.with_name(args.output.stem + ".records.json")
        with index_path.open("x", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        records_ref = reference(index_path)
    else:
        records_ref = reference(args.records)
        records = read_bound(records_ref)
    actual_conditions_ref = reference(args.actual_conditions) if args.actual_conditions else None
    result = summarize(order, records, actual_conditions_ref=actual_conditions_ref, order_ref=order_ref)
    # Verify imported sources did not change during the read-only calculation.
    # 为什么要有它：binding only the entry script leaves imported measurement semantics mutable.
    for dependency in dependencies_before:
        bound_bytes(dependency["origin_ref"])
    dependencies_after = preserve_loaded_dependencies(args.output.parent)
    result.update(order_ref=order_ref, records_ref=records_ref, **source_refs)
    result["host_dependency_refs"] = dependencies_after
    result["discovery_pending"] = records.get("pending", [])
    # Exclusive creation never replaces historical records.
    # 为什么要有它：recomputable statistics must not rewrite their own evidence.
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
