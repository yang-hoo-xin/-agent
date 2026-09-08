"""Metadata-only native observations for new Patch runs, with a bounded sink.

Mapping follows https://langfuse.com/integrations/native/opentelemetry and
https://langfuse.com/docs/observability/features/token-and-cost-tracking .
No SDK, environment/credential lookup, product state or durable retry ledger is
introduced. HTTP acceptance is recorded separately from remote readback.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from collections import Counter, OrderedDict, deque
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from src.observability.patch_langfuse import LangfuseHttpTransport

LIVE_MAPPING_VERSION = "patch_live_langfuse_metadata_v1"
OTLP_ENDPOINT = "/api/public/otel/v1/traces"
_KINDS = frozenset({"span", "generation", "tool", "agent", "chain", "retriever", "guardrail", "evaluator", "embedding", "event"})
_DIGEST = re.compile(r"(?:sha256:)?[a-f0-9]{64}\Z")
_MACHINE_TEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,95}\Z")
_METADATA_LABELS = frozenset({"provider", "response_origin", "tool_name", "source_kind", "status",
    "workflow_node", "workflow_status", "terminal_stage", "failure_code", "verification_status", "failure_owner", "execution_origin",
    "admission_result", "result_code", "timing_scope", "validator", "exception_type"})
_METADATA_NUMBERS = frozenset({"turn_index", "response_received", "usage_available", "byte_count", "reused",
    "evaluation_index", "checks_run", "checks_failed", "transport_started", "request_bytes", "file_count",
    "proposal_admitted", "callback_invoked", "tool_dispatch_performed", "encoded_payload_bytes", "observation_queued",
    "model_consumption_proven", "read_cost", "prepared_before_dispatch", "dispatch_started", "request_registered",
    "upstream_execution_performed", "exit_code", "timed_out", "process_index", "process_count"})
_METADATA_HASHES = frozenset({"request_sha256", "response_sha256", "observation_sha256",
    "behavior_report_sha256", "output_code_sha256", "output_sha256", "generated_changes_sha256", "baseline_sha256",
    "response_content_sha256", "source_snapshot_sha256", "encoded_payload_sha256", "arguments_sha256"})
_IDENTITY_ATTRIBUTES = frozenset({"source_observation_id", "binding_id", "provider_response_id"})
ALLOWED_ATTRIBUTE_KEYS = _METADATA_LABELS | _METADATA_NUMBERS | _METADATA_HASHES | {
    "model", "usage", "call_id", "tool_call_id", "artifact_refs", "consumed_tool_results", "tool_call_ids"} | _IDENTITY_ATTRIBUTES


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _machine_text(value: Any) -> str | None:
    if (isinstance(value, str) and _MACHINE_TEXT.fullmatch(value)
            and ":/" not in value and ".." not in value):
        return value
    return None


def _identity(value: Any, size: int, domain: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 300:
        raise ValueError("LIVE_OBSERVATION_ID_INVALID")
    if re.fullmatch(r"[0-9a-f]{" + str(size) + "}", value) and set(value) != {"0"}:
        return value
    return _hash_text(domain + ":" + value)[:size]


def live_trace_id(value: str) -> str:
    return _identity(value, 32, "patch-trace")


def live_observation_id(value: str) -> str:
    return _identity(value, 16, "patch-observation")


def _utc_nanos(value: Any) -> int:
    if not isinstance(value, str):
        raise ValueError("LIVE_OBSERVATION_TIME_REQUIRED")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("LIVE_OBSERVATION_TIMEZONE_REQUIRED")
    delta = parsed.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


def _attribute(key: str, value: Any) -> dict:
    if type(value) is bool:
        encoded = {"boolValue": value}
    elif type(value) is int:
        encoded = {"intValue": str(value)}
    elif type(value) is float:
        encoded = {"doubleValue": value}
    else:
        encoded = {"stringValue": value if isinstance(value, str) else _json(value).decode("utf-8")}
    return {"key": key, "value": encoded}


def _usage(attributes: Mapping) -> tuple[dict | None, str]:
    if attributes.get("usage_available") is not True:
        return None, "unknown"
    raw = attributes.get("usage")
    if not isinstance(raw, Mapping) or any(type(raw.get(key)) is not int or raw[key] < 0
        for key in ("input_tokens", "output_tokens")):
        return None, "invalid_counts"
    buckets = {"input": raw["input_tokens"], "output": raw["output_tokens"]}
    for field, aggregate, subtype in (("cached_input_tokens", "input", "input_cached_tokens"),
                                     ("reasoning_tokens", "output", "output_reasoning_tokens")):
        if field not in raw:
            continue
        if type(raw[field]) is not int or not 0 <= raw[field] <= buckets[aggregate]:
            return None, "invalid_inclusive_subtype"
        buckets[aggregate] -= raw[field]
        buckets[subtype] = raw[field]
    return buckets, "inclusive_provider_counts_to_exclusive_buckets"


def _metadata(attributes: Mapping) -> dict:
    result = {}
    for key in _METADATA_LABELS:
        value = _machine_text(attributes.get(key))
        if key == "exception_type" and (value is None or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,95}", value)):
            continue
        if value is not None:
            result[key] = value
    for key in _METADATA_NUMBERS:
        value = attributes.get(key)
        if type(value) in (bool, int) or type(value) is float and math.isfinite(value):
            result[key] = value
    for key in _METADATA_HASHES:
        value = attributes.get(key)
        if isinstance(value, str) and _DIGEST.fullmatch(value):
            result[key] = value
    call_ids = {attributes[key] for key in ("call_id", "tool_call_id")
        if isinstance(attributes.get(key), str) and len(attributes[key]) <= 300}
    if len(call_ids) == 1:
        result["call_id_sha256"] = _hash_text(next(iter(call_ids)))
    elif len(call_ids) > 1:
        result["call_identity_conflict"] = True
    for key in _IDENTITY_ATTRIBUTES:
        if isinstance(attributes.get(key), str) and len(attributes[key]) <= 300:
            result[key + "_sha256"] = _hash_text(attributes[key])
    calls = attributes.get("tool_call_ids")
    if isinstance(calls, (tuple, list)):
        result["tool_call_id_sha256s"] = [_hash_text(value) for value in calls[:64]
            if isinstance(value, str) and len(value) <= 300]
    consumed = attributes.get("consumed_tool_results")
    if isinstance(consumed, (tuple, list)):
        result["consumed_tool_results"] = []
        for item in consumed[:64]:
            if not isinstance(item, Mapping):
                continue
            kept = {}
            if isinstance(item.get("call_id"), str) and len(item["call_id"]) <= 300:
                kept["call_id_sha256"] = _hash_text(item["call_id"])
            value = item.get("observation_sha256")
            if isinstance(value, str) and _DIGEST.fullmatch(value):
                kept["observation_sha256"] = value
            if kept:
                result["consumed_tool_results"].append(kept)
    refs = attributes.get("artifact_refs")
    if isinstance(refs, Mapping):
        refs = list(refs.values())[:32]
    if isinstance(refs, (tuple, list)):
        result["artifact_refs"] = []
        for item in refs[:32]:
            if not isinstance(item, Mapping):
                continue
            kept = {}
            for key in ("type", "artifact_type"):
                if _machine_text(item.get(key)) is not None:
                    kept[key] = item[key]
            for key in ("hash", "artifact_hash", "sha256"):
                if isinstance(item.get(key), str) and _DIGEST.fullmatch(item[key]):
                    kept[key] = item[key]
            if type(item.get("revision")) is int and item["revision"] >= 0:
                kept["revision"] = item["revision"]
            if kept:
                result["artifact_refs"].append(kept)
    return result


def build_patch_live_otlp(row: Mapping) -> dict:
    """Map a completed neutral observation; never create missing timing facts."""
    if not isinstance(row, Mapping) or row.get("status") not in {"completed", "failed"}:
        raise ValueError("LIVE_OBSERVATION_NOT_FINISHED")
    kind, name = row.get("kind"), row.get("name")
    if kind not in _KINDS or not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("LIVE_OBSERVATION_KIND_OR_NAME_INVALID")
    started, finished = _utc_nanos(row.get("started_at")), _utc_nanos(row.get("finished_at"))
    if not 0 < started <= finished:
        raise ValueError("LIVE_OBSERVATION_TIME_ORDER_INVALID")
    attributes = row.get("attributes") if isinstance(row.get("attributes"), Mapping) else {}
    metadata = _metadata(attributes)
    metadata.update(mapping_version=LIVE_MAPPING_VERSION, metadata_only=True,
        source_prompt_output_included=False, historical_import=False, observation_status=row["status"])
    elapsed = row.get("elapsed_ms")
    if type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0:
        metadata["recorded_elapsed_ms"] = elapsed
    attrs = [_attribute("langfuse.observation.type", kind),
             _attribute("langfuse.trace.name", "Patch execution"),
             {"key": "langfuse.trace.tags", "value": {"arrayValue": {"values": [
                 {"stringValue": "live_execution"}, {"stringValue": "metadata_only"}]}}},
             _attribute("langfuse.observation.level", "ERROR" if row["status"] == "failed" else "DEFAULT")]
    if row.get("session_id") is not None:
        session = _machine_text(row["session_id"])
        if session is None:
            raise ValueError("LIVE_OBSERVATION_SESSION_INVALID")
        attrs.append(_attribute("session.id", session))
    if row.get("environment") is not None:
        environment = _machine_text(row["environment"])
        if environment is None:
            raise ValueError("LIVE_OBSERVATION_ENVIRONMENT_INVALID")
        attrs.append(_attribute("langfuse.environment", environment))
    if kind == "generation":
        model = _machine_text(attributes.get("model"))
        if model is not None:
            attrs.append(_attribute("langfuse.observation.model.name", model))
        usage, usage_status = _usage(attributes)
        metadata["usage_mapping_status"] = usage_status
        if usage is not None:
            attrs.append(_attribute("langfuse.observation.usage_details", usage))
    attrs.extend(_attribute("langfuse.observation.metadata." + key, value) for key, value in sorted(metadata.items()))
    span = {"traceId": live_trace_id(row.get("trace_id")), "spanId": live_observation_id(row.get("id")),
            "name": name, "kind": 1, "startTimeUnixNano": str(started), "endTimeUnixNano": str(finished),
            "status": {"code": 2 if row["status"] == "failed" else 1}, "attributes": attrs}
    if row.get("parent_id") is not None:
        parent = live_observation_id(row["parent_id"])
        if parent == span["spanId"]:
            raise ValueError("LIVE_OBSERVATION_SELF_PARENT")
        span["parentSpanId"] = parent
    return {"resourceSpans": [{"resource": {"attributes": [_attribute("service.name", "mod-agent-execution")]},
        "scopeSpans": [{"scope": {"name": "mod_agent.patch_live", "version": LIVE_MAPPING_VERSION}, "spans": [span]}]}]}


class PatchLiveLangfuseSink:
    """Nonblocking publisher; one bounded queue, one daemon HTTP worker, no retry.

    shutdown closes admission immediately and drains until its total deadline.
    An already-running transport cannot be killed by Python: timeout returns
    pending/worker_alive, and that worker may finish later. No process-level
    cancellation, durable delivery or remote readback is implied.
    """

    def __init__(self, transport: LangfuseHttpTransport, *, max_queue_size=128, max_recent_ids=2048,
                 max_payload_bytes=65536):
        if (not callable(getattr(transport, "_request", None)) or type(max_queue_size) is not int
                or not 1 <= max_queue_size <= 1024 or type(max_recent_ids) is not int or not 1 <= max_recent_ids <= 8192
                or type(max_payload_bytes) is not int or not 1024 <= max_payload_bytes <= 262144):
            raise ValueError("LIVE_SINK_CONFIGURATION_INVALID")
        self._transport = transport
        self._capacity, self._recent_capacity, self._max_payload = max_queue_size, max_recent_ids, max_payload_bytes
        self._condition = threading.Condition()
        self._queue = deque()
        self._recent = OrderedDict()
        self._pending = {}
        self._counts = Counter()
        self._active = 0
        self._closed = False
        self._last_error = None
        self._thread = threading.Thread(target=self._drain, name="patch-langfuse-export", daemon=True)
        self._thread.start()

    def publish(self, row: Mapping) -> None:
        with self._condition:
            if self._closed:
                self._counts["rejected_after_shutdown"] += 1
                return
            self._counts["received"] += 1
        if isinstance(row, Mapping) and row.get("status") == "running" and row.get("finished_at") is None:
            with self._condition:
                self._counts["running_not_exported"] += 1
            return
        try:
            payload = build_patch_live_otlp(row)
            raw = _json(payload)
            if len(raw) > self._max_payload:
                raise ValueError("LIVE_OBSERVATION_PAYLOAD_TOO_LARGE")
            span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
            key = (span["traceId"], span["spanId"])
            digest = hashlib.sha256(raw).hexdigest()
        except Exception:
            with self._condition:
                self._counts["invalid_records"] += 1
            return
        with self._condition:
            if self._closed:
                self._counts["rejected_after_shutdown"] += 1
            elif key in self._pending or key in self._recent:
                prior = self._pending.get(key, self._recent.get(key))
                self._counts["duplicate_records" if prior == digest else "conflicting_updates"] += 1
            elif len(self._queue) >= self._capacity:
                self._counts["queue_dropped"] += 1
            else:
                self._queue.append((payload, key))
                self._pending[key] = digest
                self._recent[key] = digest
                while len(self._recent) > self._recent_capacity:
                    self._recent.popitem(last=False)
                self._counts["queued"] += 1
                self._condition.notify_all()

    def _drain(self):
        while True:
            with self._condition:
                while not self._queue and not self._closed:
                    self._condition.wait()
                if not self._queue and self._closed:
                    return
                payload, key = self._queue.popleft()
                self._active = 1
                self._counts["post_attempts"] += 1
            try:
                response = self._transport._request("POST", OTLP_ENDPOINT, payload=payload)
                if not isinstance(response, Mapping) or not isinstance(response.get("partialSuccess", {}), Mapping):
                    raise ValueError("LIVE_OTLP_RESPONSE_INVALID")
                partial = response.get("partialSuccess", {})
                rejected = int(partial.get("rejectedSpans", 0))
                if rejected < 0:
                    raise ValueError("LIVE_OTLP_RESPONSE_INVALID")
                with self._condition:
                    self._counts["partial_responses" if rejected else "http_accepted"] += 1
            except Exception as exc:
                with self._condition:
                    self._counts["send_failures"] += 1
                    self._last_error = type(exc).__name__  # Never retain the exception text or request headers.
            finally:
                with self._condition:
                    self._active = 0
                    self._pending.pop(key, None)
                    self._condition.notify_all()

    def stats(self) -> dict:
        with self._condition:
            return {**{key: self._counts[key] for key in (
                "received", "running_not_exported", "queued", "duplicate_records", "conflicting_updates",
                "invalid_records", "queue_dropped", "post_attempts", "http_accepted", "partial_responses",
                "send_failures", "rejected_after_shutdown")},
                "pending": len(self._queue) + self._active, "queued_pending": len(self._queue),
                "active_sends": self._active, "closed_to_new_records": self._closed,
                "worker_alive": self._thread.is_alive(), "last_error_type": self._last_error,
                "remote_readback": "not_performed", "delivery_scope": "http_acceptance_not_verified_remote_delivery",
                "retry_policy": "no_automatic_post_retry", "deduplication_scope": "bounded_process_local_recent_ids"}

    @staticmethod
    def _deadline(timeout_millis):
        if type(timeout_millis) not in (int, float) or not math.isfinite(timeout_millis) or not 0 <= timeout_millis <= 120000:
            raise ValueError("LIVE_SINK_DEADLINE_INVALID")
        return time.monotonic() + timeout_millis / 1000

    def _wait(self, deadline):
        with self._condition:
            while self._queue or self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
        result = self.stats()
        return {**result, "deadline_exhausted": result["pending"] > 0}

    def flush(self, *, timeout_millis=2000) -> dict:
        return self._wait(self._deadline(timeout_millis))

    def shutdown(self, *, timeout_millis=2000) -> dict:
        deadline = self._deadline(timeout_millis)
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._wait(deadline)
        self._thread.join(max(0, deadline - time.monotonic()))
        result = self.stats()
        return {**result, "deadline_exhausted": result["pending"] > 0 or result["worker_alive"]}
