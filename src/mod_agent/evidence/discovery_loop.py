"""Bounded model/tool loop for intelligent evidence discovery."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .discovery_contract import (
    EVIDENCE_DISCOVERY_PROMPT_CONTRACT_VERSION,
    EVIDENCE_DISCOVERY_RESULT_KINDS,
    EvidenceDiscoveryModel,
    EvidenceDiscoveryRequest,
    EvidenceDiscoveryResult,
    EvidenceDiscoverySource,
    EvidenceDiscoveryToolExecutor,
    ToolObservation,
)
from .models import EvidencePack, missing_evidence_from_blockers


class IntelligentEvidencePackFactory:
    """Invoke discovery inside the graph evidence node and retain its audit result."""

    def __init__(
        self,
        *,
        specialist: "EvidenceDiscoverySpecialist",
        sources: tuple[EvidenceDiscoverySource, ...],
        max_tool_calls: int = 6,
        max_model_steps: int = 8,
        max_result_bytes_per_call: int = 65_536,
        max_total_observation_bytes: int = 262_144,
    ) -> None:
        self.specialist = specialist
        self.sources = sources
        self.max_tool_calls = max_tool_calls
        self.max_model_steps = max_model_steps
        self.max_result_bytes_per_call = max_result_bytes_per_call
        self.max_total_observation_bytes = max_total_observation_bytes
        self.last_result: EvidenceDiscoveryResult | None = None

    def __call__(self, state: dict[str, Any], feature_data: dict[str, Any]) -> EvidencePack:
        request_id = str(state.get("request_id") or "").strip()
        goal = str(
            feature_data.get("target_behavior") or state.get("user_request") or ""
        ).strip()
        result = self.specialist.discover(
            EvidenceDiscoveryRequest(
                request_id=request_id,
                natural_language_request=goal,
                sources=self.sources,
                max_tool_calls=self.max_tool_calls,
                max_model_steps=self.max_model_steps,
                max_result_bytes_per_call=self.max_result_bytes_per_call,
                max_total_observation_bytes=self.max_total_observation_bytes,
            )
        )
        self.last_result = result
        return result.pack


class EvidenceDiscoverySpecialist:
    """Run one bounded read-only action/observation loop inside Evidence."""

    def __init__(
        self,
        *,
        model: EvidenceDiscoveryModel,
        tool_executor: EvidenceDiscoveryToolExecutor,
    ) -> None:
        self.model = model
        self.tool_executor = tool_executor

    def discover(self, request: EvidenceDiscoveryRequest) -> EvidenceDiscoveryResult:
        begin_run = getattr(self.model, "begin_run", None)
        if callable(begin_run):
            begin_run()
        sources = {source.source_id: source for source in request.sources}
        initial_messages: tuple[dict[str, object], ...] = (
            {"role": "system", "content": _system_contract()},
            {
                "role": "user",
                "content": {
                    "request_id": request.request_id,
                    "goal": request.natural_language_request,
                    "sources": [source.model_view() for source in request.sources],
                    "constraints": {
                        "read_only": True,
                        "target_code_execution": False,
                        "stop_after": "evidence_retrieval",
                        "max_tool_calls": request.max_tool_calls,
                        "max_model_steps": request.max_model_steps,
                    },
                },
            },
        )
        prompt_contract = {
            "version": EVIDENCE_DISCOVERY_PROMPT_CONTRACT_VERSION,
            "system_contract_sha256": _json_sha256(initial_messages[0]["content"]),
            "initial_context_sha256": _json_sha256(initial_messages[1]["content"]),
            "context_strategy": "initial_plus_compact_trajectory_plus_latest_observation_v1",
            "raw_prompt_persisted": False,
        }
        actions: list[dict[str, object]] = []
        model_action_attempts: list[dict[str, object]] = []
        observations: list[ToolObservation] = []
        observations_by_id: dict[str, ToolObservation] = {}
        method_origins: dict[str, str] = {}
        total_observation_bytes = 0
        pending_observation: ToolObservation | None = None
        finish_validation_error: str | None = None

        model_steps_used = 0
        for model_step in range(1, request.max_model_steps + 1):
            model_steps_used = model_step
            messages = _build_turn_messages(
                initial_messages=initial_messages,
                actions=actions,
                observations=observations,
                pending_observation=pending_observation,
                finish_validation_error=finish_validation_error,
                request=request,
                model_step=model_step,
            )
            pending_observation = None
            finish_validation_error = None
            raw = self.model.complete(messages)
            action = _parse_action(raw)
            if action["action"] == "finish":
                try:
                    _validate_finish(action, observations_by_id)
                except ValueError as exc:
                    error = str(exc)
                    model_action_attempts.append(
                        _model_action_attempt(
                            model_step=model_step,
                            action=action,
                            status="rejected",
                            validation_error=error,
                        )
                    )
                    finish_validation_error = error
                    continue
                model_action_attempts.append(
                    _model_action_attempt(
                        model_step=model_step,
                        action=action,
                        status="accepted",
                    )
                )
                return self._result(
                    request=request,
                    run_status="completed",
                    finish=action,
                    actions=actions,
                    observations=observations,
                    method_origins=method_origins,
                    prompt_contract=prompt_contract,
                    model_steps_used=model_steps_used,
                    total_observation_bytes=total_observation_bytes,
                    finish_origin="model",
                    model_action_attempts=model_action_attempts,
                )
            if len(actions) >= request.max_tool_calls:
                model_action_attempts.append(
                    _model_action_attempt(
                        model_step=model_step,
                        action=action,
                        status="rejected",
                        validation_error="TOOL_CALL_BUDGET_EXHAUSTED",
                    )
                )
                return self._budget_result(
                    request=request,
                    actions=actions,
                    observations=observations,
                    method_origins=method_origins,
                    reason="Tool-call budget was exhausted before the model finished.",
                    prompt_contract=prompt_contract,
                    model_steps_used=model_steps_used,
                    total_observation_bytes=total_observation_bytes,
                    model_action_attempts=model_action_attempts,
                )
            _validate_tool_action(
                action,
                sources=sources,
                observations_by_id=observations_by_id,
                method_origins=method_origins,
            )
            model_action_attempts.append(
                _model_action_attempt(
                    model_step=model_step,
                    action=action,
                    status="accepted",
                )
            )
            observation_id = f"obs-{len(observations) + 1:03d}"
            source = sources[str(action["source_id"])]
            observation = self.tool_executor.execute(
                action=action,
                source=source,
                observation_id=observation_id,
            )
            _validate_observation(observation, action=action)
            encoded_size = len(
                json.dumps(
                    observation.model_view(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            if encoded_size > request.max_result_bytes_per_call:
                raise ValueError("TOOL_OBSERVATION_EXCEEDS_PER_CALL_BUDGET")
            total_observation_bytes += encoded_size
            if total_observation_bytes > request.max_total_observation_bytes:
                return self._budget_result(
                    request=request,
                    actions=actions,
                    observations=observations,
                    method_origins=method_origins,
                    reason="Total observation byte budget was exhausted.",
                    prompt_contract=prompt_contract,
                    model_steps_used=model_steps_used,
                    total_observation_bytes=total_observation_bytes,
                    model_action_attempts=model_action_attempts,
                )
            actions.append(action)
            observations.append(observation)
            observations_by_id[observation.observation_id] = observation
            for method in observation.data.get("methods", []):
                if isinstance(method, dict) and method.get("method_id"):
                    method_origins[str(method["method_id"])] = observation.observation_id
            pending_observation = observation

        return self._budget_result(
            request=request,
            actions=actions,
            observations=observations,
            method_origins=method_origins,
            reason="Model-step budget was exhausted before the model finished.",
            prompt_contract=prompt_contract,
            model_steps_used=model_steps_used,
            total_observation_bytes=total_observation_bytes,
            model_action_attempts=model_action_attempts,
        )

    def _result(
        self,
        *,
        request: EvidenceDiscoveryRequest,
        run_status: str,
        finish: dict[str, object],
        actions: list[dict[str, object]],
        observations: list[ToolObservation],
        method_origins: dict[str, str],
        prompt_contract: dict[str, object],
        model_steps_used: int,
        total_observation_bytes: int,
        finish_origin: str,
        model_action_attempts: list[dict[str, object]],
    ) -> EvidenceDiscoveryResult:
        unresolved = tuple(str(item) for item in finish.get("unresolved_questions", []))
        missing_capabilities = tuple(
            str(item) for item in finish.get("missing_capabilities", [])
        )
        blockers_list: list[dict[str, object]] = []
        if missing_capabilities:
            blockers_list.append(
                {
                    "code": "INTELLIGENT_DISCOVERY_MISSING_CAPABILITY",
                    "message": "The bounded discovery loop reported a missing evidence tool capability.",
                    "needed_evidence": list(missing_capabilities),
                }
            )
        if str(finish.get("decision")) != "sufficient_for_proposal":
            blockers_list.append(
                {
                    "code": "INTELLIGENT_DISCOVERY_NEEDS_MORE_EVIDENCE",
                    "message": "The model-selected evidence path did not establish proposal readiness.",
                    "needed_evidence": list(unresolved) or ["additional verified evidence"],
                }
            )
        blockers = tuple(blockers_list)
        items = tuple(
            item for observation in observations for item in observation.evidence_items
        )
        input_audit = _input_audit(request)
        conclusions = tuple(
            dict(item)
            for item in finish.get("evidence_conclusions", [])
            if isinstance(item, dict)
        )
        intelligence_transfer = _intelligence_transfer(
            actions=actions,
            observations=observations,
            method_origins=method_origins,
            finish=finish,
            input_audit=input_audit,
            source_count=len(request.sources),
            run_status=run_status,
            finish_origin=finish_origin,
        )
        usage_records = _model_usage_records(self.model)
        pack = EvidencePack(
            query=request.natural_language_request,
            readiness="partial" if items else "insufficient",
            can_generate_patch=False,
            items=items,
            gaps=(*unresolved, *missing_capabilities),
            blockers=blockers,
            retrieval_methods_used=tuple(
                dict.fromkeys(observation.tool for observation in observations)
            ),
            missing_evidence=missing_evidence_from_blockers(blockers),
            disabled_modes={
                "bm25": "Not used by the bounded intelligent evidence loop.",
                "dense": "Not used by the bounded intelligent evidence loop.",
                "fusion": "Not used by the bounded intelligent evidence loop.",
                "rerank": "Not used by the bounded intelligent evidence loop.",
            },
            timing={},
            budget_summary={
                "max_tool_calls": request.max_tool_calls,
                "tool_calls_used": len(actions),
                "max_model_steps": request.max_model_steps,
                "model_steps_used": model_steps_used,
                "max_result_bytes_per_call": request.max_result_bytes_per_call,
                "max_total_observation_bytes": request.max_total_observation_bytes,
                "total_observation_bytes_used": total_observation_bytes,
                "model_turn_usage": list(usage_records),
                "model_usage_totals": _usage_totals(usage_records),
            },
            trace_refs=tuple(observation.observation_id for observation in observations),
            run_status=run_status,
            verified_findings=tuple(
                dict(item) for item in conclusions if item.get("claim_status") == "observed"
            ),
            evidence_conclusions=conclusions,
            unresolved_questions=unresolved,
            missing_capabilities=missing_capabilities,
            tool_trace_summary=tuple(
                {
                    "observation_id": observation.observation_id,
                    "tool": observation.tool,
                    "source_id": observation.source_id,
                    "summary": observation.summary,
                }
                for observation in observations
            ),
            model_action_trace=tuple(model_action_attempts)
            + (
                ()
                if finish_origin == "model"
                else (
                    {
                        "model_step": model_steps_used,
                        "origin": finish_origin,
                        "status": "accepted",
                        "action": dict(finish),
                        "action_sha256": _json_sha256(finish),
                    },
                )
            ),
            observation_trace=tuple(
                {
                    "observation_id": observation.observation_id,
                    "tool": observation.tool,
                    "source_id": observation.source_id,
                    "observation_sha256": _json_sha256(observation.model_view()),
                    "model_payload_bytes": len(
                        json.dumps(
                            observation.model_view(),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ),
                }
                for observation in observations
            ),
            prompt_contract=dict(prompt_contract),
            model_identity=_model_identity(self.model),
            provenance_validation={
                "all_method_inspections_derived_from_observations": intelligence_transfer[
                    "followup_selection_by_platform"
                ],
                "target_code_executed": False,
                "model_disclosure": _model_disclosure_record(self.model),
            },
            input_audit=input_audit,
            intelligence_transfer=intelligence_transfer,
            message=(
                "The Evidence specialist selected sources and tools through a bounded "
                "action/observation loop; deterministic policy retained routing authority."
            ),
        )
        return EvidenceDiscoveryResult(
            run_status=run_status,
            pack=pack,
            actions=tuple(actions),
            observations=tuple(observations),
            input_audit=input_audit,
            intelligence_transfer=intelligence_transfer,
        )

    def _budget_result(
        self,
        *,
        request: EvidenceDiscoveryRequest,
        actions: list[dict[str, object]],
        observations: list[ToolObservation],
        method_origins: dict[str, str],
        reason: str,
        prompt_contract: dict[str, object],
        model_steps_used: int,
        total_observation_bytes: int,
        model_action_attempts: list[dict[str, object]],
    ) -> EvidenceDiscoveryResult:
        return self._result(
            request=request,
            run_status="budget_exhausted",
            finish={
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [],
                "unresolved_questions": [reason],
                "missing_capabilities": [],
            },
            actions=actions,
            observations=observations,
            method_origins=method_origins,
            prompt_contract=prompt_contract,
            model_steps_used=model_steps_used,
            total_observation_bytes=total_observation_bytes,
            finish_origin="deterministic_budget_stop",
            model_action_attempts=model_action_attempts,
        )


def _build_turn_messages(
    *,
    initial_messages: tuple[dict[str, object], ...],
    actions: list[dict[str, object]],
    observations: list[ToolObservation],
    pending_observation: ToolObservation | None,
    finish_validation_error: str | None,
    request: EvidenceDiscoveryRequest,
    model_step: int,
) -> tuple[dict[str, object], ...]:
    messages = list(initial_messages)
    if actions:
        messages.append(
            {
                "role": "user",
                "content": {
                    "message_type": "compact_trajectory",
                    "steps": [
                        _compact_step(index, action, observations[index])
                        for index, action in enumerate(actions)
                    ],
                    "history_policy": (
                        "Earlier full observations remain in the local audit record and "
                        "are not replayed. Use exact ids from this compact trajectory."
                    ),
                },
            }
        )
    if pending_observation is not None:
        messages.append({"role": "tool", "content": pending_observation.model_view()})
    if finish_validation_error is not None:
        messages.append(
            {
                "role": "user",
                "content": {
                    "message_type": "finish_validation_error",
                    "error_code": finish_validation_error,
                    "required_next_action": "finish",
                    "allowed_decisions": [
                        "sufficient_for_proposal",
                        "needs_more_evidence",
                        "blocked_by_missing_capability",
                        "conflicting_evidence",
                    ],
                    "instruction": (
                        "Return one corrected finish JSON object that follows the "
                        "system contract. Do not request another tool."
                    ),
                },
            }
        )
    remaining_tool_calls = request.max_tool_calls - len(actions)
    messages.append(
        {
            "role": "user",
            "content": {
                "message_type": "budget_state",
                "tool_calls_used": len(actions),
                "remaining_tool_calls": remaining_tool_calls,
                "model_steps_used": model_step - 1,
                "remaining_model_steps": request.max_model_steps - model_step + 1,
                "required_next_action": (
                    "finish"
                    if remaining_tool_calls == 0 or finish_validation_error is not None
                    else "use_tool_or_finish"
                ),
            },
        }
    )
    return tuple(messages)


def _compact_step(
    index: int,
    action: dict[str, object],
    observation: ToolObservation,
) -> dict[str, object]:
    methods: list[dict[str, object]] = []
    for raw in observation.data.get("methods", []):
        if isinstance(raw, dict):
            methods.append(
                {
                    key: raw[key]
                    for key in ("method_id", "assembly_id", "symbol", "metadata_token")
                    if key in raw
                }
            )
    return {
        "step": index + 1,
        "tool": action.get("tool"),
        "source_id": action.get("source_id"),
        "evidence_need": action.get("evidence_need"),
        "derived_from_observation_ids": list(
            action.get("derived_from_observation_ids") or []
        ),
        "observation_id": observation.observation_id,
        "observation_summary": observation.summary,
        "observed_methods": methods,
    }


def _parse_action(raw: str) -> dict[str, object]:
    try:
        action = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"MODEL_ACTION_INVALID_JSON: {exc}") from exc
    if not isinstance(action, dict):
        raise ValueError("MODEL_ACTION_MUST_BE_OBJECT")
    if action.get("action") not in {"use_tool", "finish"}:
        raise ValueError("MODEL_ACTION_TYPE_INVALID")
    return action


def _validate_tool_action(
    action: dict[str, object],
    *,
    sources: dict[str, EvidenceDiscoverySource],
    observations_by_id: dict[str, ToolObservation],
    method_origins: dict[str, str],
) -> None:
    if set(action) != {
        "action",
        "tool",
        "source_id",
        "arguments",
        "evidence_need",
        "derived_from_observation_ids",
    }:
        raise ValueError("TOOL_ACTION_SHAPE_INVALID")
    if not str(action.get("evidence_need") or "").strip():
        raise ValueError("TOOL_EVIDENCE_NEED_INVALID")
    tool = str(action.get("tool") or "")
    source_id = str(action.get("source_id") or "")
    if source_id not in sources:
        raise ValueError("UNAUTHORIZED_SOURCE_REFERENCE")
    if tool not in sources[source_id].allowed_tools:
        raise ValueError("SOURCE_TOOL_NOT_ALLOWED")
    arguments = action.get("arguments")
    if not isinstance(arguments, dict):
        raise ValueError("TOOL_ARGUMENTS_MUST_BE_OBJECT")
    derived = action.get("derived_from_observation_ids")
    if not isinstance(derived, list) or any(
        not isinstance(item, str) or item not in observations_by_id for item in derived
    ):
        raise ValueError("UNVERIFIED_OBSERVATION_REFERENCE")
    if len(derived) != len(set(derived)):
        raise ValueError("DUPLICATE_OBSERVATION_REFERENCE")
    if tool == "search_dotnet_metadata":
        if set(arguments) != {"queries", "result_kinds", "limit_per_kind"}:
            raise ValueError("METADATA_SEARCH_ARGUMENTS_INVALID")
        queries = arguments.get("queries")
        if (
            not isinstance(queries, list)
            or not queries
            or len(queries) > 12
            or any(not isinstance(query, str) or not query.strip() for query in queries)
        ):
            raise ValueError("METADATA_SEARCH_QUERIES_INVALID")
        result_kinds = arguments.get("result_kinds")
        if (
            not isinstance(result_kinds, list)
            or not result_kinds
            or len(result_kinds) != len(set(result_kinds))
            or any(kind not in EVIDENCE_DISCOVERY_RESULT_KINDS for kind in result_kinds)
        ):
            raise ValueError("METADATA_SEARCH_RESULT_KINDS_INVALID")
        limit = arguments.get("limit_per_kind")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            raise ValueError("METADATA_SEARCH_LIMIT_INVALID")
        return
    if tool == "inspect_method_il":
        if set(arguments) != {"method_id"}:
            raise ValueError("METHOD_INSPECTION_ARGUMENTS_INVALID")
        method_id = str(arguments.get("method_id") or "")
        origin = method_origins.get(method_id)
        if origin is None:
            raise ValueError("UNVERIFIED_METHOD_REFERENCE")
        if origin not in derived:
            raise ValueError("METHOD_ORIGIN_OBSERVATION_REQUIRED")
        return
    raise ValueError("UNKNOWN_EVIDENCE_TOOL")


def _validate_observation(
    observation: ToolObservation,
    *,
    action: dict[str, object],
) -> None:
    if observation.tool != action.get("tool"):
        raise ValueError("TOOL_OBSERVATION_TOOL_MISMATCH")
    if observation.source_id != action.get("source_id"):
        raise ValueError("TOOL_OBSERVATION_SOURCE_MISMATCH")
    if not observation.observation_id or not observation.summary:
        raise ValueError("TOOL_OBSERVATION_IDENTITY_INVALID")


def _validate_finish(
    finish: dict[str, object],
    observations_by_id: dict[str, ToolObservation],
) -> None:
    if set(finish) != {
        "action",
        "decision",
        "evidence_conclusions",
        "unresolved_questions",
        "missing_capabilities",
    }:
        raise ValueError("DISCOVERY_FINISH_SHAPE_INVALID")
    decision = finish.get("decision")
    if decision not in {
        "sufficient_for_proposal",
        "needs_more_evidence",
        "blocked_by_missing_capability",
        "conflicting_evidence",
    }:
        raise ValueError("DISCOVERY_DECISION_INVALID")
    conclusions = finish.get("evidence_conclusions")
    unresolved = finish.get("unresolved_questions")
    missing = finish.get("missing_capabilities")
    if not isinstance(conclusions, list) or not isinstance(unresolved, list) or not isinstance(missing, list):
        raise ValueError("DISCOVERY_FINISH_FIELDS_INVALID")
    if any(not isinstance(item, str) or not item.strip() for item in (*unresolved, *missing)):
        raise ValueError("DISCOVERY_FINISH_TEXT_ITEMS_INVALID")
    for conclusion in conclusions:
        if not isinstance(conclusion, dict) or set(conclusion) != {
            "claim",
            "claim_status",
            "observation_ids",
            "limitations",
        }:
            raise ValueError("EVIDENCE_CONCLUSION_SHAPE_INVALID")
        if not str(conclusion.get("claim") or "").strip():
            raise ValueError("EVIDENCE_CONCLUSION_CLAIM_INVALID")
        status = conclusion.get("claim_status")
        if status not in {"observed", "inferred", "unknown"}:
            raise ValueError("EVIDENCE_CONCLUSION_STATUS_INVALID")
        refs = conclusion.get("observation_ids")
        limitations = conclusion.get("limitations")
        if not isinstance(refs, list) or not isinstance(limitations, list) or any(
            not isinstance(item, str) or not item.strip() for item in limitations
        ):
            raise ValueError("EVIDENCE_CONCLUSION_FIELDS_INVALID")
        if len(refs) != len(set(refs)):
            raise ValueError("DUPLICATE_CONCLUSION_OBSERVATION_REFERENCE")
        if status in {"observed", "inferred"} and (
            not refs or any(ref not in observations_by_id for ref in refs)
        ):
            raise ValueError("EVIDENCE_CONCLUSION_OBSERVATION_REQUIRED")
        if status == "inferred" and not limitations:
            raise ValueError("INFERRED_CONCLUSION_LIMITATIONS_REQUIRED")
        if status == "unknown" and refs:
            raise ValueError("UNKNOWN_CONCLUSION_MUST_NOT_CITE_OBSERVATION")
        if status == "unknown" and not limitations:
            raise ValueError("UNKNOWN_CONCLUSION_LIMITATIONS_REQUIRED")
    if decision == "sufficient_for_proposal" and (unresolved or missing):
        raise ValueError("SUFFICIENT_DECISION_HAS_OPEN_GAPS")
    if decision == "sufficient_for_proposal" and not conclusions:
        raise ValueError("SUFFICIENT_DECISION_REQUIRES_CONCLUSION")
    if decision == "needs_more_evidence" and not (unresolved or missing):
        raise ValueError("NEEDS_MORE_EVIDENCE_REQUIRES_OPEN_GAP")
    if decision == "blocked_by_missing_capability" and not missing:
        raise ValueError("MISSING_CAPABILITY_DECISION_REQUIRES_CAPABILITY")


def _input_audit(request: EvidenceDiscoveryRequest) -> dict[str, int]:
    return {
        "manual_symbol_count": len(request.manual_symbols),
        "manual_tool_sequence_count": len(request.manual_tool_sequence),
        "precomputed_report_count": len(request.precomputed_reports),
        "operator_intervention_count": request.operator_intervention_count,
    }


def _intelligence_transfer(
    *,
    actions: list[dict[str, object]],
    observations: list[ToolObservation],
    method_origins: dict[str, str],
    finish: dict[str, object],
    input_audit: dict[str, int],
    source_count: int,
    run_status: str,
    finish_origin: str,
) -> dict[str, bool]:
    no_manual_input = all(value == 0 for value in input_audit.values())
    tool_actions = [action for action in actions if action.get("action") == "use_tool"]
    signatures = [
        _json_sha256(
            {
                "tool": action.get("tool"),
                "source_id": action.get("source_id"),
                "arguments": action.get("arguments"),
            }
        )
        for action in tool_actions
    ]
    no_repetition = len(signatures) == len(set(signatures))
    converged = run_status == "completed" and finish_origin == "model"
    search_used = any(action.get("tool") == "search_dotnet_metadata" for action in tool_actions)
    inspection_actions = [
        action for action in tool_actions if action.get("tool") == "inspect_method_il"
    ]
    followup = any(
        bool(action.get("derived_from_observation_ids"))
        and isinstance(action.get("arguments"), dict)
        and str(action["arguments"].get("method_id") or "") in method_origins
        and method_origins[str(action["arguments"].get("method_id"))]
        in action.get("derived_from_observation_ids", [])
        for action in inspection_actions
    )
    inspection_observation_ids = {
        observation.observation_id
        for observation in observations
        if observation.tool == "inspect_method_il"
    }
    conclusions = finish.get("evidence_conclusions")
    grounded_conclusions = [
        item
        for item in conclusions if isinstance(conclusions, list) and isinstance(item, dict)
        if item.get("claim_status") in {"observed", "inferred"}
        and isinstance(item.get("observation_ids"), list)
        and bool(item.get("observation_ids"))
    ] if isinstance(conclusions, list) else []
    symbol_grounded = any(
        inspection_observation_ids.intersection(item.get("observation_ids", []))
        for item in grounded_conclusions
    )
    common = no_manual_input and converged and no_repetition
    return {
        "source_selection_by_platform": common and source_count >= 2 and bool(tool_actions),
        "tool_selection_by_platform": common and search_used and bool(inspection_actions),
        "symbol_discovery_by_platform": common and followup and symbol_grounded,
        "followup_selection_by_platform": common and followup,
        "evidence_interpretation_by_platform": common and bool(grounded_conclusions),
        "converged_before_budget": converged,
        "grounded_conclusion_by_platform": common and bool(grounded_conclusions),
        "unproductive_repetition_absent": no_repetition,
        "semantic_relevance_evaluated": False,
    }


def _system_contract() -> dict[str, object]:
    return {
        "contract_version": EVIDENCE_DISCOVERY_PROMPT_CONTRACT_VERSION,
        "role": "Evidence specialist",
        "objective": "Discover exact evidence without inventing paths, symbols, or APIs.",
        "actions": {
            "use_tool": {
                "required": [
                    "action",
                    "tool",
                    "source_id",
                    "arguments",
                    "evidence_need",
                    "derived_from_observation_ids",
                ],
                "tools": {
                    "search_dotnet_metadata": {
                        "arguments": {
                            "queries": ["string"],
                            "result_kinds": ["methods | types | fields"],
                            "limit_per_kind": "integer 1..50",
                        }
                    },
                    "inspect_method_il": {"arguments": {"method_id": "observed id"}},
                },
            },
            "finish": {
                "required": [
                    "action",
                    "decision",
                    "evidence_conclusions",
                    "unresolved_questions",
                    "missing_capabilities",
                ]
            },
        },
        "rules": [
            "Return one JSON object or one native tool call only.",
            "Use only listed source_ids and allowed tools.",
            "Select focused result_kinds and the smallest useful limit_per_kind.",
            "An inspect_method_il method_id must come from a prior observation.",
            "Observed and inferred conclusions must reference prior observations.",
            "Inferred conclusions must state limitations; unknown conclusions cite no observation.",
            "When budget_state.required_next_action is finish, return finish and do not request another tool.",
            "Community evidence cannot confirm current runtime behavior.",
        ],
    }


def _model_disclosure_record(model: EvidenceDiscoveryModel) -> dict[str, object]:
    record = getattr(model, "disclosure_record", None)
    if isinstance(record, dict):
        return dict(record)
    return {
        "approved": False,
        "reason": "Injected local/test model; no external disclosure occurred.",
    }


def _model_identity(model: EvidenceDiscoveryModel) -> dict[str, object]:
    disclosure = _model_disclosure_record(model)
    destination = disclosure.get("destination")
    if disclosure.get("approved") is True and isinstance(destination, dict):
        return {
            "execution_kind": "external_agent_turn_adapter",
            "provider": destination.get("provider"),
            "model": destination.get("model"),
            "approval_id": disclosure.get("approval_id"),
        }
    return {
        "execution_kind": "injected_local_or_test",
        "provider": None,
        "model": None,
    }


def _model_usage_records(model: EvidenceDiscoveryModel) -> tuple[dict[str, object], ...]:
    records = getattr(model, "usage_records", ())
    if not isinstance(records, (tuple, list)):
        return ()
    return tuple(dict(item) for item in records if isinstance(item, dict))


def _usage_totals(records: tuple[dict[str, object], ...]) -> dict[str, int]:
    fields = (
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "cached_input_tokens",
        "total_tokens",
    )
    return {
        field: sum(
            int(record.get(field, 0))
            for record in records
            if isinstance(record.get(field, 0), int)
            and not isinstance(record.get(field, 0), bool)
        )
        for field in fields
    }


def _json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _model_action_attempt(
    *,
    model_step: int,
    action: dict[str, object],
    status: str,
    validation_error: str | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "model_step": model_step,
        "origin": "model",
        "status": status,
        "action": dict(action),
        "action_sha256": _json_sha256(action),
    }
    if validation_error is not None:
        record["validation_error"] = validation_error
    return record
