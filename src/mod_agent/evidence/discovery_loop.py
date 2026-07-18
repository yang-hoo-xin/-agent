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
    evidence_discovery_finish_decision_constraints,
    evidence_discovery_finish_schema,
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
        run_id = str(state.get("run_id") or "").strip()
        request_id = str(state.get("request_id") or "").strip()
        goal = str(
            feature_data.get("target_behavior") or state.get("user_request") or ""
        ).strip()
        result = self.specialist.discover(
            EvidenceDiscoveryRequest(
                run_id=run_id,
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
        begin_tool_run = getattr(self.tool_executor, "begin_run", None)
        if callable(begin_tool_run):
            begin_tool_run(run_id=request.run_id)
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
            "context_strategy": (
                "deduplicated_catalog_latest_observation_zero_result_recovery_"
                "repeat_correction_and_supported_facts_v6"
            ),
            "raw_prompt_persisted": False,
        }
        actions: list[dict[str, object]] = []
        model_action_attempts: list[dict[str, object]] = []
        observations: list[ToolObservation] = []
        observations_by_id: dict[str, ToolObservation] = {}
        candidate_origins: dict[str, tuple[str, str]] = {}
        total_observation_bytes = 0
        discovery_message_bytes_by_turn: list[int] = []
        pending_observation: ToolObservation | None = None
        finish_validation_error: str | None = None
        finish_correction_used = False
        tool_action_validation_error: dict[str, object] | None = None
        repeated_action_correction_used = False
        executed_tool_action_signatures: set[str] = set()

        model_steps_used = 0
        for model_step in range(1, request.max_model_steps + 1):
            model_steps_used = model_step
            messages = _build_turn_messages(
                initial_messages=initial_messages,
                actions=actions,
                observations=observations,
                pending_observation=pending_observation,
                finish_validation_error=finish_validation_error,
                tool_action_validation_error=tool_action_validation_error,
                request=request,
                model_step=model_step,
            )
            discovery_message_bytes_by_turn.append(_json_size(messages))
            correction_required = finish_validation_error is not None
            pending_observation = None
            finish_validation_error = None
            tool_action_validation_error = None
            raw = self.model.complete(messages)
            action = _parse_action(raw)
            if correction_required and action["action"] != "finish":
                model_action_attempts.append(
                    _model_action_attempt(
                        model_step=model_step,
                        action=action,
                        status="rejected",
                        validation_error="FINISH_CORRECTION_TOOL_CALL_FORBIDDEN",
                    )
                )
                return self._budget_result(
                    request=request,
                    actions=actions,
                    observations=observations,
                    candidate_origins=candidate_origins,
                    reason=(
                        "The single finish-correction opportunity returned a tool "
                        "action instead of finish."
                    ),
                    prompt_contract=prompt_contract,
                    model_steps_used=model_steps_used,
                    total_observation_bytes=total_observation_bytes,
                    discovery_message_bytes_by_turn=discovery_message_bytes_by_turn,
                    model_action_attempts=model_action_attempts,
                )
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
                    if finish_correction_used:
                        return self._budget_result(
                            request=request,
                            actions=actions,
                            observations=observations,
                            candidate_origins=candidate_origins,
                            reason=(
                                "The single finish-correction opportunity was "
                                "exhausted."
                            ),
                            prompt_contract=prompt_contract,
                            model_steps_used=model_steps_used,
                            total_observation_bytes=total_observation_bytes,
                            discovery_message_bytes_by_turn=(
                                discovery_message_bytes_by_turn
                            ),
                            model_action_attempts=model_action_attempts,
                        )
                    finish_correction_used = True
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
                    candidate_origins=candidate_origins,
                    prompt_contract=prompt_contract,
                    model_steps_used=model_steps_used,
                    total_observation_bytes=total_observation_bytes,
                    discovery_message_bytes_by_turn=discovery_message_bytes_by_turn,
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
                    candidate_origins=candidate_origins,
                    reason="Tool-call budget was exhausted before the model finished.",
                    prompt_contract=prompt_contract,
                    model_steps_used=model_steps_used,
                    total_observation_bytes=total_observation_bytes,
                    discovery_message_bytes_by_turn=discovery_message_bytes_by_turn,
                    model_action_attempts=model_action_attempts,
                )
            _validate_tool_action(
                action,
                sources=sources,
                observations_by_id=observations_by_id,
                candidate_origins=candidate_origins,
            )
            action_signature = _tool_action_signature(action)
            if action_signature in executed_tool_action_signatures:
                model_action_attempts.append(
                    _model_action_attempt(
                        model_step=model_step,
                        action=action,
                        status="rejected",
                        validation_error="REPEATED_EXACT_TOOL_ACTION",
                    )
                )
                if repeated_action_correction_used:
                    return self._budget_result(
                        request=request,
                        actions=actions,
                        observations=observations,
                        candidate_origins=candidate_origins,
                        reason=(
                            "The single exact-repeat correction opportunity was "
                            "exhausted before the model finished."
                        ),
                        prompt_contract=prompt_contract,
                        model_steps_used=model_steps_used,
                        total_observation_bytes=total_observation_bytes,
                        discovery_message_bytes_by_turn=discovery_message_bytes_by_turn,
                        model_action_attempts=model_action_attempts,
                    )
                repeated_action_correction_used = True
                tool_action_validation_error = {
                    "error_code": "REPEATED_EXACT_TOOL_ACTION",
                    "rejected_action_signature_sha256": action_signature,
                    "rejected_tool": action["tool"],
                    "rejected_source_id": action["source_id"],
                }
                continue
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
                    candidate_origins=candidate_origins,
                    reason="Total observation byte budget was exhausted.",
                    prompt_contract=prompt_contract,
                    model_steps_used=model_steps_used,
                    total_observation_bytes=total_observation_bytes,
                    discovery_message_bytes_by_turn=discovery_message_bytes_by_turn,
                    model_action_attempts=model_action_attempts,
                )
            actions.append(action)
            executed_tool_action_signatures.add(action_signature)
            observations.append(observation)
            observations_by_id[observation.observation_id] = observation
            for method in observation.data.get("methods", []):
                if isinstance(method, dict) and method.get("candidate_ref"):
                    candidate_origins[str(method["candidate_ref"])] = (
                        observation.observation_id,
                        observation.source_id,
                    )
            pending_observation = observation

        return self._budget_result(
            request=request,
            actions=actions,
            observations=observations,
            candidate_origins=candidate_origins,
            reason="Model-step budget was exhausted before the model finished.",
            prompt_contract=prompt_contract,
            model_steps_used=model_steps_used,
            total_observation_bytes=total_observation_bytes,
            discovery_message_bytes_by_turn=discovery_message_bytes_by_turn,
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
        candidate_origins: dict[str, tuple[str, str]],
        prompt_contract: dict[str, object],
        model_steps_used: int,
        total_observation_bytes: int,
        discovery_message_bytes_by_turn: list[int],
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
        method_inspection_provenance_valid = (
            _all_method_inspections_derived_from_observations(
                actions=actions,
                candidate_origins=candidate_origins,
            )
        )
        candidate_binding_trace = _candidate_binding_trace(
            actions=actions,
            observations=observations,
        )
        intelligence_transfer = _intelligence_transfer(
            actions=actions,
            observations=observations,
            finish=finish,
            input_audit=input_audit,
            source_count=len(request.sources),
            run_status=run_status,
            finish_origin=finish_origin,
            method_inspection_provenance_valid=method_inspection_provenance_valid,
        )
        usage_records = _model_usage_records(self.model)
        observation_fact_catalog = tuple(
            fact
            for observation in observations
            for fact in observation.supported_facts()
        )
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
                "discovery_message_bytes_by_turn": list(
                    discovery_message_bytes_by_turn
                ),
                "total_discovery_message_bytes": sum(
                    discovery_message_bytes_by_turn
                ),
                "model_turn_usage": list(usage_records),
                "model_usage_totals": _usage_totals(usage_records),
            },
            trace_refs=tuple(observation.observation_id for observation in observations),
            run_status=run_status,
            verified_findings=_verified_observed_findings(
                conclusions=conclusions,
                observation_facts=observation_fact_catalog,
            ),
            evidence_conclusions=conclusions,
            observation_fact_catalog=observation_fact_catalog,
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
                "run_id": request.run_id,
                "all_method_inspections_derived_from_observations": (
                    method_inspection_provenance_valid
                ),
                "candidate_binding_trace": candidate_binding_trace,
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
        candidate_origins: dict[str, tuple[str, str]],
        reason: str,
        prompt_contract: dict[str, object],
        model_steps_used: int,
        total_observation_bytes: int,
        discovery_message_bytes_by_turn: list[int],
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
            candidate_origins=candidate_origins,
            prompt_contract=prompt_contract,
            model_steps_used=model_steps_used,
            total_observation_bytes=total_observation_bytes,
            discovery_message_bytes_by_turn=discovery_message_bytes_by_turn,
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
    tool_action_validation_error: dict[str, object] | None,
    request: EvidenceDiscoveryRequest,
    model_step: int,
) -> tuple[dict[str, object], ...]:
    messages = list(initial_messages)
    if actions:
        excluded_observation_id = (
            pending_observation.observation_id
            if pending_observation is not None
            else None
        )
        excluded_method_ids = _observation_internal_method_ids(pending_observation)
        messages.append(
            {
                "role": "user",
                "content": {
                    "message_type": "compact_trajectory",
                    "steps": [
                        _compact_step(index, action, observations[index])
                        for index, action in enumerate(actions)
                    ],
                    "observed_method_catalog": _observed_method_catalog(
                        observations,
                        excluded_observation_id=excluded_observation_id,
                        excluded_method_ids=excluded_method_ids,
                    ),
                    "inspection_catalog": _inspection_catalog(
                        observations,
                        excluded_observation_id=excluded_observation_id,
                    ),
                    "supported_fact_catalog": _compact_supported_fact_catalog(
                        observations,
                        excluded_observation_id=excluded_observation_id,
                    ),
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
                    "required_finish_schema": evidence_discovery_finish_schema(),
                    "decision_constraints": (
                        evidence_discovery_finish_decision_constraints()
                    ),
                    "repair_focus": _finish_validation_repair_focus(
                        finish_validation_error
                    ),
                    "available_inspection_observation_ids": (
                        _inspection_observation_ids(observations)
                    ),
                    "instruction": (
                        "Return one corrected finish JSON object that follows the "
                        "system contract. Do not request another tool."
                    ),
                },
            }
        )
    if tool_action_validation_error is not None:
        messages.append(
            {
                "role": "user",
                "content": {
                    "message_type": "tool_action_validation_error",
                    **tool_action_validation_error,
                    "executed_tool_call_count": len(actions),
                    "required_change": (
                        "Choose a different source, tool, or arguments, or finish. "
                        "Changing only evidence_need or derived observation ids does "
                        "not make the action different."
                    ),
                    "metadata_query_semantics": (
                        "search_dotnet_metadata uses case-insensitive literal-substring "
                        "matching against fully qualified managed type, method, and "
                        "field symbols. It does not interpret behavioral sentences as "
                        "semantic search."
                    ),
                    "instruction": (
                        "Do not repeat the rejected source/tool/arguments action. No "
                        "expected symbol or hidden evaluator value is provided."
                    ),
                },
            }
        )
    remaining_tool_calls = request.max_tool_calls - len(actions)
    acceptance_progress = _acceptance_progress(observations)
    messages.append(
        {
            "role": "user",
            "content": {
                "message_type": "budget_state",
                "tool_calls_used": len(actions),
                "remaining_tool_calls": remaining_tool_calls,
                "model_steps_used": model_step - 1,
                "remaining_model_steps": request.max_model_steps - model_step + 1,
                "acceptance_progress": acceptance_progress["progress"],
                "remaining_acceptance_requirements": acceptance_progress[
                    "remaining_requirements"
                ],
                "required_next_action": (
                    "finish"
                    if remaining_tool_calls == 0 or finish_validation_error is not None
                    else (
                        "finish_or_use_tool_for_exact_gap"
                        if acceptance_progress["progress"][
                            "inspect_method_il_observation_ids"
                        ]
                        else "use_tool_or_finish"
                    )
                ),
            },
        }
    )
    return tuple(messages)


def _acceptance_progress(
    observations: list[ToolObservation],
) -> dict[str, object]:
    metadata_observation_ids = [
        observation.observation_id
        for observation in observations
        if observation.tool == "search_dotnet_metadata"
    ]
    inspection_observation_ids = _inspection_observation_ids(observations)
    metadata_candidate_refs = _metadata_candidate_refs(observations)
    if not metadata_observation_ids:
        remaining_requirements = [
            "Use search_dotnet_metadata to obtain a current-run candidate_ref.",
            "Use inspect_method_il with a candidate_ref from that metadata observation.",
            (
                "Finish with an observed or inferred conclusion whose observation_ids "
                "includes an inspect_method_il observation_id."
            ),
        ]
    elif not metadata_candidate_refs:
        remaining_requirements = [
            (
                "No current-run candidate_ref has been observed. Do not call "
                "inspect_method_il without one."
            ),
            (
                "Use a materially different literal managed-symbol substring, change "
                "result_kinds to types or fields, or finish with needs_more_evidence. "
                "Do not treat zero results as proof that a symbol does not exist."
            ),
        ]
    elif not inspection_observation_ids:
        remaining_requirements = [
            "Use inspect_method_il with a candidate_ref from a current-run metadata observation.",
            (
                "Finish with an observed or inferred conclusion whose observation_ids "
                "includes an inspect_method_il observation_id."
            ),
        ]
    else:
        remaining_requirements = [
            (
                "Finish now with an observed or inferred conclusion whose observation_ids "
                "includes one listed inspect_method_il observation id, unless one exact "
                "unresolved gap justifies one new tool call. needs_more_evidence is valid; "
                "do not broad-search or repeat a method."
            )
        ]
    return {
        "progress": {
            "metadata_observation_ids": metadata_observation_ids,
            "inspect_method_il_observation_ids": inspection_observation_ids,
        },
        "remaining_requirements": remaining_requirements,
    }


def _metadata_candidate_refs(
    observations: list[ToolObservation],
) -> list[str]:
    refs: list[str] = []
    for observation in observations:
        if observation.tool != "search_dotnet_metadata":
            continue
        methods = observation.data.get("methods", [])
        if not isinstance(methods, list):
            continue
        for raw in methods:
            if isinstance(raw, dict) and raw.get("candidate_ref"):
                refs.append(str(raw["candidate_ref"]))
    return refs


def _finish_validation_repair_focus(error_code: str) -> dict[str, object]:
    if error_code == "DISCOVERY_DECISION_INVALID":
        return {
            "field": "decision",
            "requirement": "Use exactly one value from allowed_decisions.",
        }
    if error_code == "EVIDENCE_CONCLUSION_SHAPE_INVALID":
        return {
            "field": "evidence_conclusions[]",
            "required_keys": [
                "claim",
                "claim_status",
                "observation_ids",
                "limitations",
            ],
            "field_types": {
                "claim": "non-empty string",
                "claim_status": "observed | inferred | unknown",
                "observation_ids": "array of non-empty strings",
                "limitations": "array of non-empty strings",
            },
            "additional_keys_allowed": False,
        }
    if error_code == "EVIDENCE_CONCLUSION_INSPECTION_REFERENCE_REQUIRED":
        return {
            "field": "evidence_conclusions[].observation_ids",
            "requirement": (
                "At least one observed or inferred conclusion must cite one id "
                "from available_inspection_observation_ids."
            ),
        }
    return {
        "field": "finish",
        "requirement": "Match required_finish_schema exactly.",
    }


def _compact_step(
    index: int,
    action: dict[str, object],
    observation: ToolObservation,
) -> dict[str, object]:
    return {
        "step": index + 1,
        "tool": action.get("tool"),
        "source_id": action.get("source_id"),
        "arguments": dict(action.get("arguments") or {}),
        "derived_from_observation_ids": list(
            action.get("derived_from_observation_ids") or []
        ),
        "observation_id": observation.observation_id,
        "observation_summary": observation.summary,
    }


def _compact_supported_fact_catalog(
    observations: list[ToolObservation],
    *,
    excluded_observation_id: str | None,
) -> list[dict[str, object]]:
    catalog: dict[str, dict[str, object]] = {}
    for observation in observations:
        if observation.observation_id == excluded_observation_id:
            continue
        for fact in observation.model_supported_facts():
            key = str(fact["canonical_claim"])
            catalog[key] = fact
    return list(catalog.values())


def _observed_method_catalog(
    observations: list[ToolObservation],
    *,
    excluded_observation_id: str | None,
    excluded_method_ids: set[str],
) -> list[dict[str, object]]:
    catalog: dict[str, dict[str, object]] = {}
    for observation in observations:
        if observation.observation_id == excluded_observation_id:
            continue
        for raw in observation.data.get("methods", []):
            if (
                not isinstance(raw, dict)
                or not raw.get("candidate_ref")
                or not raw.get("method_id")
            ):
                continue
            method_id = str(raw["method_id"])
            candidate_ref = str(raw["candidate_ref"])
            if method_id in excluded_method_ids:
                continue
            entry = {
                "candidate_ref": candidate_ref,
                "source_id": observation.source_id,
                "discovered_in_observation_id": observation.observation_id,
                **{
                    key: raw[key]
                    for key in (
                        "symbol",
                        "has_method_body",
                    )
                    if key in raw
                },
            }
            existing = catalog.get(method_id)
            if existing is not None and _method_identity(existing) != _method_identity(
                entry
            ):
                raise ValueError("COMPACT_CANDIDATE_IDENTITY_CONFLICT")
            catalog.setdefault(method_id, entry)
    return list(catalog.values())


def _inspection_catalog(
    observations: list[ToolObservation],
    *,
    excluded_observation_id: str | None,
) -> list[dict[str, object]]:
    catalog: dict[str, dict[str, object]] = {}
    for observation in observations:
        if (
            observation.observation_id == excluded_observation_id
            or observation.tool != "inspect_method_il"
        ):
            continue
        data = observation.data
        candidate_ref = str(data.get("candidate_ref") or "")
        method_id = str(data.get("method_id") or "")
        if not candidate_ref or not method_id:
            raise ValueError("COMPACT_INSPECTION_CANDIDATE_REF_MISSING")
        entry = {
            "candidate_ref": candidate_ref,
            "source_id": observation.source_id,
            "inspection_observation_id": observation.observation_id,
            **{
                key: data[key]
                for key in (
                    "symbol",
                    "metadata_token",
                    "has_method_body",
                    "rva",
                    "instruction_count",
                    "instructions_truncated",
                    "resolved_refs",
                    "target_code_executed",
                )
                if key in data
            },
        }
        catalog.setdefault(method_id, entry)
    return list(catalog.values())


def _method_identity(entry: dict[str, object]) -> tuple[object, ...]:
    return tuple(entry.get(key) for key in ("source_id", "symbol"))


def _inspection_observation_ids(
    observations: list[ToolObservation],
) -> list[str]:
    return [
        observation.observation_id
        for observation in observations
        if observation.tool == "inspect_method_il"
    ]


def _observation_internal_method_ids(
    observation: ToolObservation | None,
) -> set[str]:
    if observation is None:
        return set()
    method_ids = {
        str(raw["method_id"])
        for raw in observation.data.get("methods", [])
        if isinstance(raw, dict) and raw.get("method_id")
    }
    direct_method_id = observation.data.get("method_id")
    if direct_method_id:
        method_ids.add(str(direct_method_id))
    return method_ids


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
    candidate_origins: dict[str, tuple[str, str]],
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
        if set(arguments) != {"candidate_ref"}:
            raise ValueError("METHOD_INSPECTION_ARGUMENTS_INVALID")
        candidate_ref = str(arguments.get("candidate_ref") or "")
        origin = candidate_origins.get(candidate_ref)
        if origin is None:
            raise ValueError("UNVERIFIED_CANDIDATE_REFERENCE")
        origin_observation_id, origin_source_id = origin
        if origin_source_id != source_id:
            raise ValueError("CANDIDATE_SOURCE_MISMATCH")
        if origin_observation_id not in derived:
            raise ValueError("CANDIDATE_ORIGIN_OBSERVATION_REQUIRED")
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
    inspection_observation_ids = {
        observation_id
        for observation_id, observation in observations_by_id.items()
        if observation.tool == "inspect_method_il"
    }
    if inspection_observation_ids and not any(
        conclusion.get("claim_status") in {"observed", "inferred"}
        and isinstance(conclusion.get("observation_ids"), list)
        and bool(
            inspection_observation_ids.intersection(
                conclusion["observation_ids"]
            )
        )
        for conclusion in conclusions
        if isinstance(conclusion, dict)
    ):
        raise ValueError("EVIDENCE_CONCLUSION_INSPECTION_REFERENCE_REQUIRED")
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


def _verified_observed_findings(
    *,
    conclusions: tuple[dict[str, Any], ...],
    observation_facts: tuple[dict[str, object], ...],
) -> tuple[dict[str, Any], ...]:
    facts_by_claim: dict[str, list[dict[str, object]]] = {}
    for fact in observation_facts:
        canonical_claim = fact.get("canonical_claim")
        observation_id = fact.get("observation_id")
        if isinstance(canonical_claim, str) and isinstance(observation_id, str):
            facts_by_claim.setdefault(canonical_claim, []).append(fact)
    verified: list[dict[str, Any]] = []
    for conclusion in conclusions:
        if conclusion.get("claim_status") != "observed":
            continue
        claim = conclusion.get("claim")
        observation_ids = conclusion.get("observation_ids")
        if not isinstance(claim, str) or not isinstance(observation_ids, list):
            continue
        matching_facts = [
            fact
            for fact in facts_by_claim.get(claim, [])
            if observation_ids == [fact["observation_id"]]
        ]
        if len(matching_facts) == 1:
            verified.append(dict(conclusion))
    return tuple(verified)


def _intelligence_transfer(
    *,
    actions: list[dict[str, object]],
    observations: list[ToolObservation],
    finish: dict[str, object],
    input_audit: dict[str, int],
    source_count: int,
    run_status: str,
    finish_origin: str,
    method_inspection_provenance_valid: bool,
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
    followup = method_inspection_provenance_valid
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
                    "search_dotnet_metadata": [
                        "queries",
                        "result_kinds",
                        "limit_per_kind",
                    ],
                    "inspect_method_il": ["candidate_ref"],
                },
            },
            "finish": {
                "schema": evidence_discovery_finish_schema(),
                "acceptance_requirements": [
                    "First obtain a current-run candidate_ref through search_dotnet_metadata.",
                    "Then inspect that reference through inspect_method_il.",
                    (
                        "A grounded finish cites an inspect_method_il observation_id in at "
                        "least one observed or inferred conclusion."
                    ),
                ],
            },
        },
        "rules": [
            "Return one JSON object or one native tool call only.",
            "Use only listed source_ids and allowed tools.",
            (
                "Metadata queries match case-insensitive substrings of fully qualified "
                "managed type/method/field symbols; they are not behavioral semantic search."
            ),
            "Select focused result_kinds and the smallest useful limit_per_kind.",
            "Do not repeat an already executed identical source/tool/arguments action.",
            "An inspect_method_il candidate_ref must come from a prior observation.",
            "Observed and inferred conclusions must reference prior observations.",
            (
                "An observed conclusion must exactly copy canonical_claim from one "
                "supported_fact and cite only that fact's observation_id."
            ),
            "Inferred conclusions must state limitations; unknown conclusions cite no observation.",
            "When budget_state.required_next_action is finish, return finish and do not request another tool.",
            "Community evidence cannot confirm current runtime behavior.",
        ],
    }


def _all_method_inspections_derived_from_observations(
    *,
    actions: list[dict[str, object]],
    candidate_origins: dict[str, tuple[str, str]],
) -> bool:
    inspection_actions = [
        action
        for action in actions
        if action.get("action") == "use_tool"
        and action.get("tool") == "inspect_method_il"
    ]
    if not inspection_actions:
        return False
    return all(
        isinstance(action.get("arguments"), dict)
        and str(action["arguments"].get("candidate_ref") or "")
        in candidate_origins
        and candidate_origins[str(action["arguments"].get("candidate_ref"))][0]
        in action.get("derived_from_observation_ids", [])
        and candidate_origins[str(action["arguments"].get("candidate_ref"))][1]
        == action.get("source_id")
        for action in inspection_actions
    )


def _candidate_binding_trace(
    *,
    actions: list[dict[str, object]],
    observations: list[ToolObservation],
) -> list[dict[str, object]]:
    if len(actions) != len(observations):
        raise ValueError("CANDIDATE_TRACE_ACTION_OBSERVATION_COUNT_MISMATCH")
    bindings: dict[str, tuple[str, str, str]] = {}
    for observation in observations:
        if observation.tool != "search_dotnet_metadata":
            continue
        for method in observation.data.get("methods", []):
            if not isinstance(method, dict):
                continue
            candidate_ref = str(method.get("candidate_ref") or "")
            method_id = str(method.get("method_id") or "")
            if not candidate_ref or not method_id:
                continue
            bindings[candidate_ref] = (
                observation.observation_id,
                observation.source_id,
                method_id,
            )

    trace: list[dict[str, object]] = []
    for action, observation in zip(actions, observations):
        if action.get("tool") != "inspect_method_il":
            continue
        arguments = action.get("arguments")
        if not isinstance(arguments, dict):
            raise ValueError("CANDIDATE_TRACE_INSPECTION_ARGUMENTS_INVALID")
        candidate_ref = str(arguments.get("candidate_ref") or "")
        binding = bindings.get(candidate_ref)
        if binding is None:
            raise ValueError("CANDIDATE_TRACE_BINDING_MISSING")
        metadata_observation_id, source_id, method_id = binding
        if observation.tool != "inspect_method_il":
            raise ValueError("CANDIDATE_TRACE_IL_OBSERVATION_MISSING")
        if observation.source_id != source_id:
            raise ValueError("CANDIDATE_TRACE_SOURCE_MISMATCH")
        if str(observation.data.get("method_id") or "") != method_id:
            raise ValueError("CANDIDATE_TRACE_INTERNAL_METHOD_ID_MISMATCH")
        trace.append(
            {
                "candidate_ref": candidate_ref,
                "source_id": source_id,
                "metadata_observation_id": metadata_observation_id,
                "internal_method_id": method_id,
                "il_observation_id": observation.observation_id,
                "il_observation_sha256": _json_sha256(observation.model_view()),
            }
        )
    return trace


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
    if (
        disclosure.get("execution_kind") == "local_agent_turn_adapter"
        and isinstance(destination, dict)
    ):
        return {
            "execution_kind": "local_agent_turn_adapter",
            "provider": destination.get("provider"),
            "model": destination.get("model"),
            "endpoint": destination.get("endpoint"),
        }
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


def _tool_action_signature(action: dict[str, object]) -> str:
    return _json_sha256(
        {
            "tool": action.get("tool"),
            "source_id": action.get("source_id"),
            "arguments": action.get("arguments"),
        }
    )


def _json_size(value: object) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


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
