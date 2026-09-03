"""Bounded request-to-coverage runner that stops before implementation planning."""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.settings import load_settings
from src.libs.llm import LLMFactory, OllamaLLM, validate_loopback_http_base_url
from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.evidence import (
    RgLiveEvidenceProvider,
    make_requirement_coverage_evidence_provider,
)
from src.mod_agent.model_admission import (
    assert_ollama_model_identity_stable,
    local_model_admission_record,
    local_no_external_disclosure_record,
    read_ollama_model_identity,
    read_ollama_server_version,
    validate_ollama_context_window,
    validate_ollama_model_identity,
)
from src.mod_agent.planning import FeatureSpec
from src.mod_agent.requirement_coverage_model import (
    parse_requirement_coverage_json_object,
    request_requirement_coverage_model,
)

StructuredJsonCompletion = Callable[
    [str, Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]
]

FRESH_COVERAGE_RESULT_TYPE = "fresh_requirement_coverage_result_v1"
FRESH_COVERAGE_PROGRESS_TYPE = "fresh_coverage_progress_v1"
FRESH_COVERAGE_HEARTBEAT_INTERVAL_SECONDS = 15.0
FRESH_COVERAGE_MODEL_CALL_BUDGET = {
    "requirement_projection": 1,
    "requirement_projection_correction": 1,
    "requirement_findings": 1,
    "requirement_findings_correction": 1,
}
_FEATURE_SPEC_FIELDS = {
    "node_name",
    "stage",
    "message",
    "feature_id",
    "user_request",
    "target_behavior",
    "non_goals",
    "target_mod",
    "risk_level",
    "acceptance_criteria",
    "evidence_requirements",
    "runtime_verification_plan",
    "hook_requirement",
    "blocked",
    "blockers",
}


class FreshCoverageError(ValueError):
    """Reject an invalid run before downstream workflow stages can start."""

    def __init__(self, code: str, stage: str, reason: str) -> None:
        super().__init__(code)
        self.code = code
        self.stage = stage
        self.reason = reason


class FreshCoverageProgressReporter:
    """Emit content-free progress plus an independent periodic heartbeat."""

    def __init__(
        self,
        sink: Callable[[dict[str, Any]], None],
        *,
        heartbeat_interval_seconds: float = (
            FRESH_COVERAGE_HEARTBEAT_INTERVAL_SECONDS
        ),
        execution_id: str | None = None,
    ) -> None:
        if not callable(sink):
            raise ValueError("Fresh coverage progress sink must be callable.")
        if (
            isinstance(heartbeat_interval_seconds, bool)
            or not isinstance(heartbeat_interval_seconds, (int, float))
            or not math.isfinite(float(heartbeat_interval_seconds))
            or heartbeat_interval_seconds <= 0
        ):
            raise ValueError(
                "Fresh coverage heartbeat interval must be positive and finite."
            )
        if execution_id is not None and (
            not isinstance(execution_id, str) or not execution_id.strip()
        ):
            raise ValueError("Fresh coverage execution_id must be non-empty.")
        self.execution_id = execution_id or uuid.uuid4().hex
        self._sink = sink
        self._interval = float(heartbeat_interval_seconds)
        self._lock = threading.Lock()
        self._emit_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sequence = 0
        self._started_at: float | None = None
        self._stage = "model_admission"
        self._model_role: str | None = None
        self._attempt_index: int | None = None
        self._stream_chunk_count = 0
        self._stream_content_utf8_bytes = 0
        self._last_stream_activity_at: float | None = None

    def start(self) -> None:
        with self._lock:
            if self._started_at is not None:
                raise RuntimeError("Fresh coverage progress reporter already started.")
            self._started_at = time.perf_counter()
        self._emit("run_started", status="running")
        try:
            thread = threading.Thread(
                target=self._heartbeat_loop,
                name=f"fresh-coverage-heartbeat-{self.execution_id[:8]}",
                daemon=True,
            )
            thread.start()
        except RuntimeError:
            self._emit(
                "heartbeat_unavailable",
                status="degraded",
                extra={
                    "error_code": "FRESH_COVERAGE_HEARTBEAT_START_FAILED"
                },
            )
            return
        self._thread = thread

    def set_stage(self, stage: str) -> None:
        if not isinstance(stage, str) or not stage.strip():
            raise ValueError("Fresh coverage progress stage must be non-empty.")
        with self._lock:
            self._stage = stage

    def model_call_started(self, *, role: str, attempt_index: int) -> None:
        with self._emit_lock:
            with self._lock:
                self._stage = "requirement_coverage"
                self._model_role = role
                self._attempt_index = attempt_index
                self._stream_chunk_count = 0
                self._stream_content_utf8_bytes = 0
                self._last_stream_activity_at = None
            self._emit_locked("model_call_started", status="running")

    def model_call_finished(
        self,
        *,
        status: str,
        error_code: str | None,
    ) -> None:
        with self._emit_lock:
            self._emit_locked(
                "model_call_finished",
                status=status,
                extra={"error_code": error_code},
            )
            with self._lock:
                self._model_role = None
                self._attempt_index = None

    def record_stream_activity(self, event: Mapping[str, Any]) -> None:
        chunk_index = event.get("chunk_index")
        content_bytes = event.get("content_utf8_bytes")
        done = event.get("done")
        if (
            isinstance(chunk_index, bool)
            or not isinstance(chunk_index, int)
            or chunk_index <= 0
            or isinstance(content_bytes, bool)
            or not isinstance(content_bytes, int)
            or content_bytes < 0
            or type(done) is not bool
        ):
            return
        with self._emit_lock:
            now = time.perf_counter()
            with self._lock:
                first_chunk = self._stream_chunk_count == 0
                self._stream_chunk_count = chunk_index
                self._stream_content_utf8_bytes += content_bytes
                self._last_stream_activity_at = now
            if first_chunk:
                self._emit_locked("stream_started", status="running")
            if done:
                self._emit_locked("stream_completed", status="running")

    def finish(self, *, status: str, terminal_stage: str) -> None:
        self.stop_heartbeat()
        with self._emit_lock:
            with self._lock:
                self._stage = terminal_stage
            self._emit_locked("run_finished", status=status)

    def stop_heartbeat(self) -> None:
        """Stop periodic emission without claiming that result output succeeded."""

        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(1.0, self._interval))
            self._thread = None

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self._interval):
            self._emit("heartbeat", status="running")

    def _emit(
        self,
        event: str,
        *,
        status: str,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        with self._emit_lock:
            self._emit_locked(event, status=status, extra=extra)

    def _emit_locked(
        self,
        event: str,
        *,
        status: str,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self._sequence += 1
            started_at = self._started_at
            now = time.perf_counter()
            elapsed_seconds = (
                max(0.0, now - started_at) if started_at is not None else 0.0
            )
            seconds_since_stream_activity = (
                None
                if self._last_stream_activity_at is None
                else max(0.0, now - self._last_stream_activity_at)
            )
            payload: dict[str, Any] = {
                "progress_type": FRESH_COVERAGE_PROGRESS_TYPE,
                "claim_scope": "operational_liveness_only",
                "event": event,
                "sequence": self._sequence,
                "execution_id": self.execution_id,
                "emitted_at": datetime.now(timezone.utc).isoformat(),
                "status": status,
                "stage": self._stage,
                "heartbeat_interval_seconds": self._interval,
                "model_role": self._model_role,
                "attempt_index": self._attempt_index,
                "elapsed_seconds": elapsed_seconds,
                "stream_chunk_count": self._stream_chunk_count,
                "stream_content_utf8_bytes": self._stream_content_utf8_bytes,
                "seconds_since_stream_activity": (
                    seconds_since_stream_activity
                ),
            }
        if extra is not None:
            payload.update(dict(extra))
        try:
            self._sink(payload)
        except Exception:
            # Operational progress must never change the product result.
            return


@dataclass(frozen=True)
class FreshCoverageResult:
    """Stable terminal projection for one bounded fresh-coverage run."""

    status: str
    terminal_stage: str
    first_failure: dict[str, str] | None
    readiness: str | None
    can_generate_patch: bool
    query: str
    query_count: int
    item_count: int
    max_items: int
    model_execution: dict[str, Any]
    feature_spec_artifact: dict[str, str] | None
    evidence_pack_artifact: dict[str, str] | None
    duration_seconds: float
    source_modified: bool | None = False
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_type": FRESH_COVERAGE_RESULT_TYPE,
            "status": self.status,
            "command": "fresh-coverage",
            "terminal_stage": self.terminal_stage,
            "first_failure": (
                dict(self.first_failure) if self.first_failure is not None else None
            ),
            "readiness": self.readiness,
            "can_generate_patch": self.can_generate_patch,
            "query": self.query,
            "query_count": self.query_count,
            "item_count": self.item_count,
            "max_items": self.max_items,
            "model_execution": dict(self.model_execution),
            "feature_spec_artifact": (
                dict(self.feature_spec_artifact)
                if self.feature_spec_artifact is not None
                else None
            ),
            "evidence_pack_artifact": (
                dict(self.evidence_pack_artifact)
                if self.evidence_pack_artifact is not None
                else None
            ),
            "stopped_before": "implementation_planning",
            "execution_counts": {
                "planning": 0,
                "patch": 0,
                "apply": 0,
                "build": 0,
                "runtime": 0,
            },
            "source_modified": self.source_modified,
            "duration_seconds": self.duration_seconds,
            "reason": self.reason,
        }


class _ModelCallLedger:
    def __init__(
        self,
        complete_json: StructuredJsonCompletion,
        *,
        progress_reporter: FreshCoverageProgressReporter | None = None,
    ) -> None:
        self._complete_json = complete_json
        self._progress_reporter = progress_reporter
        self.attempts: list[dict[str, Any]] = []

    @property
    def roles(self) -> list[str]:
        return [str(attempt["role"]) for attempt in self.attempts]

    def complete(
        self,
        role: str,
        payload: Mapping[str, Any],
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if role not in FRESH_COVERAGE_MODEL_CALL_BUDGET:
            raise FreshCoverageError(
                "FRESH_COVERAGE_MODEL_ROLE_INVALID",
                "model_admission",
                f"Fresh coverage does not admit model role: {role}",
            )
        if self.roles.count(role) >= FRESH_COVERAGE_MODEL_CALL_BUDGET[role]:
            raise FreshCoverageError(
                "FRESH_COVERAGE_MODEL_CALL_BUDGET_EXCEEDED",
                "model_admission",
                f"Fresh coverage model role budget is exhausted: {role}",
            )
        attempt_index = len(self.attempts) + 1
        started = time.perf_counter()
        attempt = {
            "attempt_index": attempt_index,
            "role": role,
            "duration_seconds": 0.0,
            "status": "running",
            "error_code": None,
            "payload_canonical_sha256": _canonical_sha256(payload),
            "schema_canonical_sha256": _canonical_sha256(schema),
            "output_canonical_sha256": None,
        }
        self.attempts.append(attempt)
        if self._progress_reporter is not None:
            self._progress_reporter.model_call_started(
                role=role,
                attempt_index=attempt_index,
            )
        try:
            output = self._complete_json(role, payload, schema)
            attempt["output_canonical_sha256"] = _canonical_sha256(output)
        except Exception as exc:
            attempt["duration_seconds"] = time.perf_counter() - started
            attempt["status"] = "failed"
            attempt["error_code"] = _exception_code(exc)
            if self._progress_reporter is not None:
                self._progress_reporter.model_call_finished(
                    status="failed",
                    error_code=str(attempt["error_code"]),
                )
            raise
        attempt["duration_seconds"] = time.perf_counter() - started
        attempt["status"] = "succeeded"
        if self._progress_reporter is not None:
            self._progress_reporter.model_call_finished(
                status="response_received",
                error_code=None,
            )
        return output

    def to_dict(self, *, admission: Mapping[str, Any] | None) -> dict[str, Any]:
        roles = self.roles
        counts = Counter(roles)
        return {
            "roles": roles,
            "role_call_counts": {
                role: counts.get(role, 0)
                for role in FRESH_COVERAGE_MODEL_CALL_BUDGET
            },
            "call_count": len(roles),
            "correction_count": sum(
                1 for role in roles if role.endswith("_correction")
            ),
            "attempts": [dict(attempt) for attempt in self.attempts],
            "budget": {
                "maximum_total_calls": sum(
                    FRESH_COVERAGE_MODEL_CALL_BUDGET.values()
                ),
                "maximum_calls_by_role": dict(
                    FRESH_COVERAGE_MODEL_CALL_BUDGET
                ),
                "automatic_provider_fallback": False,
                "automatic_retry": False,
            },
            "admission": dict(admission or {}),
        }

    def apply_provider_attempt_audits(
        self,
        budget_summary: Mapping[str, Any],
    ) -> None:
        for audit_key, roles in (
            (
                "requirement_projection_attempt_audit",
                (
                    "requirement_projection",
                    "requirement_projection_correction",
                ),
            ),
            (
                "requirement_findings_attempt_audit",
                (
                    "requirement_findings",
                    "requirement_findings_correction",
                ),
            ),
        ):
            audits = budget_summary.get(audit_key, [])
            if not isinstance(audits, list):
                continue
            for audit in audits:
                if not isinstance(audit, Mapping):
                    continue
                attempt_index = audit.get("attempt_index")
                if (
                    isinstance(attempt_index, bool)
                    or not isinstance(attempt_index, int)
                    or not 1 <= attempt_index <= len(roles)
                ):
                    continue
                role = roles[attempt_index - 1]
                matching = next(
                    (
                        attempt
                        for attempt in self.attempts
                        if attempt.get("role") == role
                    ),
                    None,
                )
                if matching is None or matching.get("status") == "failed":
                    continue
                if audit.get("status") == "rejected":
                    matching["status"] = "rejected"
                    error_code = audit.get("error_code")
                    matching["error_code"] = (
                        error_code
                        if isinstance(error_code, str) and error_code
                        else "FRESH_COVERAGE_MODEL_OUTPUT_REJECTED"
                    )
                elif audit.get("status") == "accepted":
                    matching["status"] = "accepted"
                    matching["error_code"] = None


class LocalOllamaRequirementCoverageCompletion:
    """Exact local identity admission plus the shared structured adapter."""

    def __init__(
        self,
        *,
        llm: OllamaLLM,
        base_url: str,
        model: str,
        model_identity: Mapping[str, Any],
        context_window: int,
        output_budget: int,
        server_version: str,
        stream_activity_recorder: (
            Callable[[dict[str, Any]], None] | None
        ) = None,
    ) -> None:
        try:
            normalized_base_url = validate_loopback_http_base_url(base_url)
        except ValueError as exc:
            raise FreshCoverageError(
                "FRESH_COVERAGE_OLLAMA_ADAPTER_BINDING_INVALID",
                "model_admission",
                "OllamaLLM binding is invalid.",
            ) from exc
        _validate_llm_binding(
            llm,
            base_url=normalized_base_url,
            model=model,
            context_window=context_window,
        )
        validate_ollama_model_identity(
            model_identity,
            expected_base_url=base_url,
            expected_model=model,
        )
        validate_ollama_context_window(
            model_identity,
            requested_context_window=context_window,
        )
        if stream_activity_recorder is not None and not callable(
            stream_activity_recorder
        ):
            raise FreshCoverageError(
                "FRESH_COVERAGE_STREAM_ACTIVITY_RECORDER_INVALID",
                "model_admission",
                "Fresh coverage stream activity recorder must be callable.",
            )
        self.llm = llm
        self.base_url = normalized_base_url
        self.model = model
        self.model_identity = dict(model_identity)
        self.context_window = context_window
        self.output_budget = output_budget
        self.server_version = server_version
        self.stream_activity_recorder = stream_activity_recorder
        self.model_admission = {
            **local_model_admission_record(
                model_identity=self.model_identity,
                provider_adapter=f"{type(llm).__module__}.{type(llm).__qualname__}",
            ),
            "ollama_server_version": server_version,
            "context_window": context_window,
            "output_budget": output_budget,
            "response_transport": "ollama_ndjson_stream_v1",
            "provider_request_resumable": False,
            "stream_content_disclosed": False,
            "source_disclosure": local_no_external_disclosure_record(),
        }

    def __call__(
        self,
        _role: str,
        payload: Mapping[str, Any],
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        _validate_llm_binding(
            self.llm,
            base_url=self.base_url,
            model=self.model,
            context_window=self.context_window,
        )
        current_identity = read_ollama_model_identity(self.base_url, self.model)
        validate_ollama_model_identity(
            current_identity,
            expected_base_url=self.base_url,
            expected_model=self.model,
        )
        assert_ollama_model_identity_stable(
            expected=self.model_identity,
            observed=current_identity,
        )
        validate_ollama_context_window(
            current_identity,
            requested_context_window=self.context_window,
        )
        _assert_no_absolute_local_paths(payload)
        response, _provider_request = request_requirement_coverage_model(
            llm=self.llm,
            payload=payload,
            schema=schema,
            max_output_tokens=self.output_budget,
            capture_provider_request=True,
            stream_response=True,
            stream_activity_recorder=self.stream_activity_recorder,
        )
        _validate_llm_binding(
            self.llm,
            base_url=self.base_url,
            model=self.model,
            context_window=self.context_window,
        )
        observed_identity = read_ollama_model_identity(self.base_url, self.model)
        validate_ollama_model_identity(
            observed_identity,
            expected_base_url=self.base_url,
            expected_model=self.model,
        )
        assert_ollama_model_identity_stable(
            expected=self.model_identity,
            observed=observed_identity,
        )
        return parse_requirement_coverage_json_object(response.content)


def _validate_llm_binding(
    llm: Any,
    *,
    base_url: str,
    model: str,
    context_window: int,
) -> None:
    if type(llm) is not OllamaLLM:
        raise FreshCoverageError(
            "FRESH_COVERAGE_OLLAMA_ADAPTER_BINDING_INVALID",
            "model_admission",
            "OllamaLLM binding is invalid.",
        )
    try:
        observed_base_url = validate_loopback_http_base_url(llm.base_url)
    except (AttributeError, TypeError, ValueError) as exc:
        raise FreshCoverageError(
            "FRESH_COVERAGE_OLLAMA_ADAPTER_BINDING_INVALID",
            "model_admission",
            "OllamaLLM binding is invalid.",
        ) from exc
    if (
        llm.model != model
        or observed_base_url != base_url
        or llm.context_window != context_window
    ):
        raise FreshCoverageError(
            "FRESH_COVERAGE_OLLAMA_ADAPTER_BINDING_INVALID",
            "model_admission",
            "OllamaLLM binding is invalid.",
        )


def create_local_ollama_requirement_coverage_completion(
    *,
    settings_path: str | Path,
    ollama_base_url: str,
    ollama_model: str,
    ollama_context_window: int,
    ollama_output_budget: int,
    ollama_timeout_seconds: float | None = None,
    stream_activity_recorder: Callable[[dict[str, Any]], None] | None = None,
) -> LocalOllamaRequirementCoverageCompletion:
    """Create an explicitly selected local-only coverage completion adapter."""

    if not isinstance(ollama_model, str) or not ollama_model.strip():
        raise FreshCoverageError(
            "FRESH_COVERAGE_OLLAMA_MODEL_INVALID",
            "model_admission",
            "Fresh coverage requires an exact Ollama model name.",
        )
    if (
        isinstance(ollama_context_window, bool)
        or not isinstance(ollama_context_window, int)
        or ollama_context_window <= 0
        or isinstance(ollama_output_budget, bool)
        or not isinstance(ollama_output_budget, int)
        or ollama_output_budget <= 0
        or ollama_context_window <= ollama_output_budget
    ):
        raise FreshCoverageError(
            "FRESH_COVERAGE_OLLAMA_BUDGET_INVALID",
            "model_admission",
            "Ollama context_window must exceed the positive output_budget.",
        )
    if ollama_timeout_seconds is not None and (
        isinstance(ollama_timeout_seconds, bool)
        or not isinstance(ollama_timeout_seconds, (int, float))
        or not math.isfinite(float(ollama_timeout_seconds))
        or ollama_timeout_seconds <= 0
    ):
        raise FreshCoverageError(
            "FRESH_COVERAGE_OLLAMA_TIMEOUT_INVALID",
            "model_admission",
            "Ollama timeout_seconds must be positive and finite.",
        )
    base_url = validate_loopback_http_base_url(ollama_base_url)
    identity = read_ollama_model_identity(base_url, ollama_model)
    validate_ollama_model_identity(
        identity,
        expected_base_url=base_url,
        expected_model=ollama_model,
    )
    validate_ollama_context_window(
        identity,
        requested_context_window=ollama_context_window,
    )
    server_version = read_ollama_server_version(base_url)
    settings = load_settings(settings_path)
    selected_settings = replace(
        settings,
        llm=replace(
            settings.llm,
            provider="ollama",
            model=ollama_model,
            max_tokens=ollama_output_budget,
            api_key=None,
            base_url=base_url,
        ),
    )
    options: dict[str, Any] = {
        "base_url": base_url,
        "context_window": ollama_context_window,
    }
    if ollama_timeout_seconds is not None:
        options["timeout"] = float(ollama_timeout_seconds)
    llm = LLMFactory.create(selected_settings, **options)
    if type(llm) is not OllamaLLM:
        raise FreshCoverageError(
            "FRESH_COVERAGE_OLLAMA_ADAPTER_INVALID",
            "model_admission",
            "Local model selection did not create OllamaLLM.",
        )
    return LocalOllamaRequirementCoverageCompletion(
        llm=llm,
        base_url=base_url,
        model=ollama_model,
        model_identity=identity,
        context_window=ollama_context_window,
        output_budget=ollama_output_budget,
        server_version=server_version,
        stream_activity_recorder=stream_activity_recorder,
    )


def run_fresh_requirement_coverage(
    *,
    feature_data: Mapping[str, Any],
    workspace_root: str | Path,
    search_root: str | Path,
    artifact_root: str | Path,
    completion: StructuredJsonCompletion,
    rg_executable: str = "rg",
    progress_reporter: FreshCoverageProgressReporter | None = None,
) -> FreshCoverageResult:
    """Run projection, live rg retrieval, findings, and resolution, then stop."""

    started = time.perf_counter()
    feature_data = strict_feature_spec_payload(feature_data)
    model_admission = _completion_model_admission(completion)
    workspace = Path(workspace_root).resolve()
    if not workspace.is_dir():
        raise FreshCoverageError(
            "FRESH_COVERAGE_WORKSPACE_ROOT_INVALID",
            "request",
            "Fresh coverage workspace_root must be an existing directory.",
        )
    search = (workspace / search_root).resolve()
    try:
        search.relative_to(workspace)
    except ValueError as exc:
        raise FreshCoverageError(
            "FRESH_COVERAGE_SEARCH_ROOT_ESCAPES_WORKSPACE",
            "request",
            "Fresh coverage search_root escapes workspace_root.",
        ) from exc
    if not search.is_dir():
        raise FreshCoverageError(
            "FRESH_COVERAGE_SEARCH_ROOT_INVALID",
            "request",
            "Fresh coverage search_root must be an existing directory.",
        )
    artifact_store_root = Path(artifact_root).resolve()
    try:
        artifact_store_root.relative_to(search)
    except ValueError:
        pass
    else:
        raise FreshCoverageError(
            "FRESH_COVERAGE_ARTIFACT_ROOT_INSIDE_SOURCE",
            "request",
            "Fresh coverage artifact_root must remain outside search_root.",
        )
    query = feature_data.get("user_request")
    feature_id = feature_data.get("feature_id")
    if not isinstance(query, str) or not query.strip():
        raise FreshCoverageError(
            "FRESH_COVERAGE_REQUEST_INVALID",
            "request",
            "FeatureSpec user_request must be a non-empty string.",
        )
    if not isinstance(feature_id, str) or not feature_id:
        raise FreshCoverageError(
            "FRESH_COVERAGE_FEATURE_ID_INVALID",
            "request",
            "FeatureSpec feature_id must be a non-empty string.",
        )
    if feature_data.get("blocked") is not False:
        raise FreshCoverageError(
            "FRESH_COVERAGE_FEATURE_SPEC_BLOCKED",
            "request",
            "Fresh coverage requires an unblocked FeatureSpec payload.",
        )

    if progress_reporter is not None:
        progress_reporter.set_stage("source_integrity")
    source_before = _source_snapshot(search)
    if progress_reporter is not None:
        progress_reporter.set_stage("artifact_store")
    store = ArtifactStore(artifact_store_root)
    feature_ref = store.write(
        feature_id=feature_id,
        artifact_type="feature_spec",
        payload=dict(feature_data),
        status="success",
    )
    ledger = _ModelCallLedger(
        completion,
        progress_reporter=progress_reporter,
    )
    provider = make_requirement_coverage_evidence_provider(
        RgLiveEvidenceProvider(workspace, rg_executable=rg_executable),
        complete_json=ledger.complete,
    )
    if progress_reporter is not None:
        progress_reporter.set_stage("requirement_coverage")
    try:
        pack = provider.collect(
            query=query,
            search_root=Path(search_root).as_posix(),
            feature_data=feature_data,
        )
    except Exception as exc:
        first_failure = _first_ledger_failure(ledger) or {
            "code": _exception_code(
                exc,
                fallback="FRESH_COVERAGE_EXECUTION_FAILED",
            ),
            "stage": "requirement_coverage",
        }
        try:
            source_modified: bool | None = (
                _source_snapshot(search) != source_before
            )
        except OSError:
            return _blocked_after_feature_result(
                started=started,
                code="FRESH_COVERAGE_SOURCE_SNAPSHOT_FAILED",
                stage="source_integrity",
                query=query,
                ledger=ledger,
                model_admission=model_admission,
                feature_ref=feature_ref,
                source_modified=None,
                first_failure=first_failure,
            )
        return _blocked_after_feature_result(
            started=started,
            code=first_failure["code"],
            stage=first_failure["stage"],
            query=query,
            ledger=ledger,
            model_admission=model_admission,
            feature_ref=feature_ref,
            source_modified=source_modified,
        )
    ledger.apply_provider_attempt_audits(pack.budget_summary)
    model_execution = ledger.to_dict(admission=model_admission)
    if progress_reporter is not None:
        progress_reporter.set_stage("source_integrity")
    try:
        source_after = _source_snapshot(search)
    except OSError:
        prior_failure = _first_provider_failure(
            budget_summary=pack.budget_summary,
            roles=ledger.roles,
        )
        return _blocked_after_feature_result(
            started=started,
            code="FRESH_COVERAGE_SOURCE_SNAPSHOT_FAILED",
            stage="source_integrity",
            query=query,
            ledger=ledger,
            model_admission=model_admission,
            feature_ref=feature_ref,
            source_modified=None,
            first_failure=prior_failure,
        )
    if source_after != source_before:
        prior_failure = _first_provider_failure(
            budget_summary=pack.budget_summary,
            roles=ledger.roles,
        )
        return _blocked_after_feature_result(
            started=started,
            code="FRESH_COVERAGE_SOURCE_CHANGED",
            stage="source_integrity",
            query=query,
            ledger=ledger,
            model_admission=model_admission,
            feature_ref=feature_ref,
            source_modified=True,
            first_failure=prior_failure,
        )
    query_count = pack.budget_summary.get("query_count")
    max_items = pack.budget_summary.get("max_items")
    if (
        isinstance(query_count, bool)
        or not isinstance(query_count, int)
        or query_count < 0
        or isinstance(max_items, bool)
        or not isinstance(max_items, int)
        or max_items < 0
    ):
        prior_failure = _first_provider_failure(
            budget_summary=pack.budget_summary,
            roles=ledger.roles,
        )
        return _blocked_after_feature_result(
            started=started,
            code="FRESH_COVERAGE_BUDGET_SUMMARY_INVALID",
            stage="requirement_coverage",
            query=query,
            ledger=ledger,
            model_admission=model_admission,
            feature_ref=feature_ref,
            first_failure=prior_failure,
        )
    pack = replace(
        pack,
        budget_summary={
            **pack.budget_summary,
            "fresh_coverage_model_execution": model_execution,
        },
    )
    failure_codes = pack.budget_summary.get("semantic_provider_failure_codes", [])
    provider_failed = isinstance(failure_codes, list) and bool(failure_codes)
    first_failure = _first_provider_failure(
        budget_summary=pack.budget_summary,
        roles=ledger.roles,
    )
    if progress_reporter is not None:
        progress_reporter.set_stage("evidence_pack_store")
    try:
        evidence_write = store.write_with_result(
            feature_id=feature_id,
            artifact_type="evidence_pack",
            payload=pack.to_artifact_payload(),
            status="success" if pack.can_generate_patch else "blocked",
            upstream_refs=[feature_ref],
        )
    except Exception:
        prior_failure = _first_provider_failure(
            budget_summary=pack.budget_summary,
            roles=ledger.roles,
        )
        return _blocked_after_feature_result(
            started=started,
            code="FRESH_COVERAGE_EVIDENCE_PACK_STORE_FAILED",
            stage="evidence_pack_store",
            query=query,
            ledger=ledger,
            model_admission=model_admission,
            feature_ref=feature_ref,
            first_failure=prior_failure,
        )
    evidence_ref = evidence_write.artifact_ref
    if evidence_write.outcome != "committed" or evidence_ref is None:
        prior_failure = _first_provider_failure(
            budget_summary=pack.budget_summary,
            roles=ledger.roles,
        )
        return _blocked_after_feature_result(
            started=started,
            code="FRESH_COVERAGE_EVIDENCE_PACK_STORE_FAILED",
            stage="evidence_pack_store",
            query=query,
            ledger=ledger,
            model_admission=model_admission,
            feature_ref=feature_ref,
            first_failure=prior_failure,
        )
    return FreshCoverageResult(
        status="blocked" if provider_failed else "terminal",
        terminal_stage="requirement_coverage",
        first_failure=first_failure,
        readiness=pack.readiness,
        can_generate_patch=pack.can_generate_patch,
        query=pack.query,
        query_count=query_count,
        item_count=len(pack.items),
        max_items=max_items,
        model_execution=model_execution,
        feature_spec_artifact=_artifact_ref_dict(feature_ref),
        evidence_pack_artifact=_artifact_ref_dict(evidence_ref),
        duration_seconds=time.perf_counter() - started,
    )


def _first_provider_failure(
    *,
    budget_summary: Mapping[str, Any],
    roles: list[str],
) -> dict[str, str] | None:
    for stage, audit_key in (
        ("requirement_projection", "requirement_projection_attempt_audit"),
        ("requirement_findings", "requirement_findings_attempt_audit"),
    ):
        attempts = budget_summary.get(audit_key, [])
        if not isinstance(attempts, list):
            continue
        for attempt in attempts:
            if not isinstance(attempt, Mapping) or attempt.get("status") != "rejected":
                continue
            error_code = attempt.get("error_code")
            if isinstance(error_code, str) and error_code:
                return {"code": error_code, "stage": stage}
    failure_codes = budget_summary.get("semantic_provider_failure_codes", [])
    if isinstance(failure_codes, list) and failure_codes:
        return {
            "code": str(failure_codes[0]),
            "stage": _first_provider_failure_stage(roles),
        }
    return None


def _first_ledger_failure(ledger: _ModelCallLedger) -> dict[str, str] | None:
    for attempt in ledger.attempts:
        if attempt.get("status") != "failed":
            continue
        role = str(attempt["role"])
        stage = {
            "requirement_projection_correction": "requirement_projection",
            "requirement_findings_correction": "requirement_findings",
        }.get(role, role)
        return {
            "code": str(attempt["error_code"]),
            "stage": stage,
        }
    return None


def _first_provider_failure_stage(roles: list[str]) -> str:
    if "requirement_projection_correction" in roles:
        return "requirement_projection"
    if "requirement_findings_correction" in roles:
        return "requirement_findings"
    return "requirement_coverage"


def _source_snapshot(root: Path) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            path.relative_to(root).as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(root.rglob("*.cs"), key=lambda value: value.as_posix())
        if path.is_file()
    )


def _artifact_ref_dict(ref: ArtifactRef) -> dict[str, str]:
    return {
        "feature_id": ref.feature_id,
        "artifact_type": ref.artifact_type,
        "path": ref.path,
        "artifact_hash": ref.artifact_hash,
    }


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _exception_code(
    exc: Exception,
    *,
    fallback: str = "FRESH_COVERAGE_MODEL_COMPLETION_FAILED",
) -> str:
    code = getattr(exc, "code", None)
    return code if isinstance(code, str) and code else fallback


def empty_fresh_coverage_model_execution() -> dict[str, Any]:
    """Return the exact zero-call ledger used before adapter construction."""

    return _ModelCallLedger(
        lambda _role, _payload, _schema: {}
    ).to_dict(admission=None)


def _completion_model_admission(
    completion: StructuredJsonCompletion,
) -> dict[str, Any]:
    if not isinstance(completion, LocalOllamaRequirementCoverageCompletion):
        raise FreshCoverageError(
            "FRESH_COVERAGE_COMPLETION_INVALID",
            "model_admission",
            "Fresh coverage requires LocalOllamaRequirementCoverageCompletion.",
        )
    admission = getattr(completion, "model_admission", None)
    if not isinstance(admission, Mapping):
        raise FreshCoverageError(
            "FRESH_COVERAGE_MODEL_ADMISSION_MISSING",
            "model_admission",
            "Fresh coverage completion lacks model_admission.",
        )
    selected = dict(admission)
    if (
        selected.get("provider") != "ollama"
        or selected.get("execution_locality") != "local"
        or selected.get("external_disclosure_occurred") is not False
        or selected.get("automatic_provider_fallback") is not False
        or selected.get("automatic_external_retry") is not False
        or selected.get("source_disclosure")
        != local_no_external_disclosure_record()
    ):
        raise FreshCoverageError(
            "FRESH_COVERAGE_MODEL_ADMISSION_INVALID",
            "model_admission",
            "Fresh coverage completion model_admission is invalid.",
        )
    return selected


def blocked_fresh_coverage_result(
    *,
    code: str,
    stage: str,
    reason: str,
    duration_seconds: float,
) -> FreshCoverageResult:
    """Project one pre-run failure without inventing model or Artifact facts."""

    return FreshCoverageResult(
        status="blocked",
        terminal_stage=stage,
        first_failure={"code": code, "stage": stage},
        readiness=None,
        can_generate_patch=False,
        query="",
        query_count=0,
        item_count=0,
        max_items=0,
        model_execution=empty_fresh_coverage_model_execution(),
        feature_spec_artifact=None,
        evidence_pack_artifact=None,
        duration_seconds=duration_seconds,
        reason=reason,
    )


def _blocked_after_feature_result(
    *,
    started: float,
    code: str,
    stage: str,
    query: str,
    ledger: _ModelCallLedger,
    model_admission: Mapping[str, Any],
    feature_ref: ArtifactRef,
    source_modified: bool | None = False,
    first_failure: Mapping[str, str] | None = None,
) -> FreshCoverageResult:
    return FreshCoverageResult(
        status="blocked",
        terminal_stage=stage,
        first_failure=(
            dict(first_failure)
            if first_failure is not None
            else {"code": code, "stage": stage}
        ),
        readiness=None,
        can_generate_patch=False,
        query=query,
        query_count=0,
        item_count=0,
        max_items=0,
        model_execution=ledger.to_dict(admission=model_admission),
        feature_spec_artifact=_artifact_ref_dict(feature_ref),
        evidence_pack_artifact=None,
        duration_seconds=time.perf_counter() - started,
        source_modified=source_modified,
        reason=code,
    )


def _assert_no_absolute_local_paths(value: Any) -> None:
    if isinstance(value, Mapping):
        for nested in value.values():
            _assert_no_absolute_local_paths(nested)
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            _assert_no_absolute_local_paths(nested)
        return
    if not isinstance(value, str) or "\n" in value or "\r" in value:
        return
    if Path(value).is_absolute() or (
        len(value) >= 3
        and value[0].isalpha()
        and value[1] == ":"
        and value[2] in {"/", "\\"}
    ):
        raise FreshCoverageError(
            "FRESH_COVERAGE_MODEL_PAYLOAD_ABSOLUTE_LOCAL_PATH",
            "model_admission",
            "Requirement coverage model payload contains an absolute local path.",
        )


def load_feature_spec_payload(path: str | Path) -> dict[str, Any]:
    """Read one exact JSON object used as the existing FeatureSpec payload."""

    try:
        value = json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_non_finite_json_constant,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise FreshCoverageError(
            "FRESH_COVERAGE_FEATURE_SPEC_READ_FAILED",
            "request",
            f"Fresh coverage FeatureSpec could not be read: {type(exc).__name__}.",
        ) from exc
    if not isinstance(value, dict):
        raise FreshCoverageError(
            "FRESH_COVERAGE_FEATURE_SPEC_NOT_OBJECT",
            "request",
            "Fresh coverage FeatureSpec JSON must be one object.",
        )
    _validate_finite_json_numbers(value)
    return strict_feature_spec_payload(value)


def strict_feature_spec_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    """Strictly rehydrate and round-trip one unblocked FeatureSpec payload."""

    if type(value) is not dict or set(value) != _FEATURE_SPEC_FIELDS:
        raise FreshCoverageError(
            "FRESH_COVERAGE_FEATURE_SPEC_SHAPE_INVALID",
            "request",
            "Fresh coverage FeatureSpec fields do not match the exact payload.",
        )
    for field_name in ("feature_id", "user_request", "target_behavior"):
        field_value = value[field_name]
        if type(field_value) is not str or not field_value.strip():
            raise FreshCoverageError(
                "FRESH_COVERAGE_FEATURE_SPEC_FIELD_INVALID",
                "request",
                f"Fresh coverage FeatureSpec {field_name} must be non-empty text.",
            )
    target_mod = value["target_mod"]
    if target_mod is not None and (
        type(target_mod) is not str or not target_mod.strip()
    ):
        raise FreshCoverageError(
            "FRESH_COVERAGE_FEATURE_SPEC_TARGET_MOD_INVALID",
            "request",
            "Fresh coverage FeatureSpec target_mod must be non-empty text or null.",
        )
    if type(value["risk_level"]) is not str or value["risk_level"] not in {
        "low",
        "medium",
        "high",
    }:
        raise FreshCoverageError(
            "FRESH_COVERAGE_FEATURE_SPEC_RISK_LEVEL_INVALID",
            "request",
            "Fresh coverage FeatureSpec risk_level is invalid.",
        )
    for field_name in (
        "non_goals",
        "acceptance_criteria",
        "evidence_requirements",
        "runtime_verification_plan",
    ):
        field_value = value[field_name]
        if type(field_value) is not list or any(
            type(item) is not str or not item.strip() for item in field_value
        ):
            raise FreshCoverageError(
                "FRESH_COVERAGE_FEATURE_SPEC_LIST_INVALID",
                "request",
                f"Fresh coverage FeatureSpec {field_name} is invalid.",
            )
    hook_requirement = value["hook_requirement"]
    if (
        type(hook_requirement) is not dict
        or set(hook_requirement) != {"required", "reason"}
        or type(hook_requirement["required"]) is not bool
        or type(hook_requirement["reason"]) is not str
        or not hook_requirement["reason"].strip()
    ):
        raise FreshCoverageError(
            "FRESH_COVERAGE_FEATURE_SPEC_HOOK_REQUIREMENT_INVALID",
            "request",
            "Fresh coverage FeatureSpec hook_requirement is invalid.",
        )
    if value["node_name"] != "draft_feature_spec" or type(
        value["node_name"]
    ) is not str:
        raise FreshCoverageError(
            "FRESH_COVERAGE_FEATURE_SPEC_NODE_INVALID",
            "request",
            "Fresh coverage FeatureSpec node_name is invalid.",
        )
    if value["stage"] != "feature_spec" or type(value["stage"]) is not str:
        raise FreshCoverageError(
            "FRESH_COVERAGE_FEATURE_SPEC_STAGE_INVALID",
            "request",
            "Fresh coverage FeatureSpec stage is invalid.",
        )
    if value["message"] != "Feature spec drafted." or type(
        value["message"]
    ) is not str:
        raise FreshCoverageError(
            "FRESH_COVERAGE_FEATURE_SPEC_MESSAGE_INVALID",
            "request",
            "Fresh coverage FeatureSpec message is invalid.",
        )
    if value["blocked"] is not False or type(value["blockers"]) is not list or value[
        "blockers"
    ]:
        raise FreshCoverageError(
            "FRESH_COVERAGE_FEATURE_SPEC_BLOCKED",
            "request",
            "Fresh coverage requires blocked=false and blockers=[].",
        )
    rehydrated = FeatureSpec(
        feature_id=value["feature_id"],
        user_request=value["user_request"],
        target_behavior=value["target_behavior"],
        non_goals=tuple(value["non_goals"]),
        target_mod=target_mod,
        risk_level=value["risk_level"],
        acceptance_criteria=tuple(value["acceptance_criteria"]),
        evidence_requirements=tuple(value["evidence_requirements"]),
        runtime_verification_plan=tuple(value["runtime_verification_plan"]),
        hook_requirement={
            "required": hook_requirement["required"],
            "reason": hook_requirement["reason"],
        },
        blocked=False,
        blockers=(),
    ).to_artifact_payload()
    if rehydrated != value:
        raise FreshCoverageError(
            "FRESH_COVERAGE_FEATURE_SPEC_ROUNDTRIP_INVALID",
            "request",
            "Fresh coverage FeatureSpec changed during strict round-trip.",
        )
    return rehydrated


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FreshCoverageError(
                "FRESH_COVERAGE_FEATURE_SPEC_DUPLICATE_KEY",
                "request",
                "Fresh coverage FeatureSpec JSON contains a duplicate object key.",
            )
        result[key] = value
    return result


def _reject_non_finite_json_constant(value: str) -> Any:
    raise FreshCoverageError(
        "FRESH_COVERAGE_FEATURE_SPEC_NON_FINITE_NUMBER",
        "request",
        f"Fresh coverage FeatureSpec JSON contains non-finite number token {value}.",
    )


def _validate_finite_json_numbers(value: Any) -> None:
    if isinstance(value, Mapping):
        for nested in value.values():
            _validate_finite_json_numbers(nested)
        return
    if isinstance(value, list):
        for nested in value:
            _validate_finite_json_numbers(nested)
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise FreshCoverageError(
            "FRESH_COVERAGE_FEATURE_SPEC_NON_FINITE_NUMBER",
            "request",
            "Fresh coverage FeatureSpec JSON contains a non-finite number.",
        )
