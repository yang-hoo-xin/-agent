"""Bounded model/tool loop for intelligent evidence discovery."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .discovery_contract import (
    AGENT_DISCOVERY_ACTUAL_SCHEMA_VERSION,
    AGENT_DISCOVERY_PROMPT_CONTRACT_VERSION,
    EVIDENCE_DISCOVERY_PROMPT_CONTRACT_VERSION,
    EVIDENCE_DISCOVERY_RESULT_KINDS,
    EvidenceDiscoveryModel,
    EvidenceDiscoveryRequest,
    EvidenceDiscoveryResult,
    EvidenceDiscoverySource,
    EvidenceDiscoveryToolExecutor,
    ToolObservation,
    agent_discovery_early_termination_state,
    evidence_discovery_finish_decision_constraints,
    evidence_discovery_finish_schema,
    evidence_discovery_planning_schema,
    normalize_agent_discovery_planning_actual,
    observed_conclusion_matches_bound_fact,
    validate_agent_discovery_actual,
)
from .models import EvidencePack, missing_evidence_from_blockers
from .hook_discovery import (
    build_agent_discovery_semantics,
    evidence_pack_state_from_hook_discovery,
)


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
        require_actual_planning: bool = False,
    ) -> None:
        self.specialist = specialist
        self.sources = sources
        self.max_tool_calls = max_tool_calls
        self.max_model_steps = max_model_steps
        self.max_result_bytes_per_call = max_result_bytes_per_call
        self.max_total_observation_bytes = max_total_observation_bytes
        self.require_actual_planning = require_actual_planning
        self.last_result: EvidenceDiscoveryResult | None = None

    @property
    def runtime_diagnostics(self) -> dict[str, object]:
        """Expose the specialist's sanitized run snapshot even before result return."""

        return self.specialist.runtime_diagnostics

    def __call__(self, state: dict[str, Any], feature_data: dict[str, Any]) -> EvidencePack:
        self.last_result = None
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
                require_actual_planning=self.require_actual_planning,
            )
        )
        self.last_result = result
        return result.pack


class EvidenceDiscoverySpecialist:
    """Run one bounded read-only action/observation loop inside Evidence.

    The first invalid finish is rejected. At most one correction is offered only
    when a model/provider turn remains inside the existing model-step budget.
    """

    def __init__(
        self,
        *,
        model: EvidenceDiscoveryModel,
        tool_executor: EvidenceDiscoveryToolExecutor,
    ) -> None:
        self.model = model
        self.tool_executor = tool_executor
        self._runtime_diagnostics = _new_runtime_diagnostics()
        self._agent_discovery: dict[str, object] | None = None
        self._planning_model_steps_used = 0

    @property
    def runtime_diagnostics(self) -> dict[str, object]:
        """Return failure-safe counters without action arguments or observations."""

        snapshot = dict(self._runtime_diagnostics)
        snapshot["provider_tool_calls"] = _provider_tool_call_count(self.model)
        snapshot["adapter_accepted_actions"] = int(
            getattr(self.model, "accepted_action_count", 0)
        )
        return snapshot

    def discover(self, request: EvidenceDiscoveryRequest) -> EvidenceDiscoveryResult:
        self._runtime_diagnostics = _new_runtime_diagnostics()
        self._agent_discovery = None
        self._planning_model_steps_used = 0
        self._runtime_diagnostics["failure_stage"] = "run_initialization"
        try:
            result = self._discover(request)
        except (OSError, RuntimeError, ValueError) as exc:
            failure_stage = str(self._runtime_diagnostics["failure_stage"])
            if failure_stage == "provider_turn":
                model_stage = str(getattr(self.model, "runtime_stage", "") or "")
                if model_stage:
                    failure_stage = model_stage
            self._runtime_diagnostics["failure_stage"] = failure_stage
            self._runtime_diagnostics["symbolic_failure_code"] = (
                _symbolic_discovery_failure_code(exc)
            )
            raise
        if self._runtime_diagnostics["symbolic_failure_code"] == "none":
            self._runtime_diagnostics["failure_stage"] = "none"
        return result

    def _discover(self, request: EvidenceDiscoveryRequest) -> EvidenceDiscoveryResult:
        begin_run = getattr(self.model, "begin_run", None)
        if callable(begin_run):
            begin_run()
        begin_tool_run = getattr(self.tool_executor, "begin_run", None)
        if callable(begin_tool_run):
            begin_tool_run(run_id=request.run_id)
        sources = {source.source_id: source for source in request.sources}
        source_views = [source.model_view() for source in request.sources]
        initial_messages: tuple[dict[str, object], ...] = (
            {"role": "system", "content": _system_contract()},
            {
                "role": "user",
                "content": {
                    "request_id": request.request_id,
                    "goal": request.natural_language_request,
                    "sources": source_views,
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
        agent_discovery: dict[str, object] | None = None
        if request.require_actual_planning:
            self._runtime_diagnostics["failure_stage"] = "requirement_projection"
            planning_messages = (
                initial_messages[0],
                initial_messages[1],
                {
                    "role": "user",
                    "content": {
                        "message_type": "actual_planning_request",
                        "required_next_action": "plan",
                        "planning_scope": "first_hook_discovery_slice",
                        "rules": [
                            "Project only semantics stated or directly implied by the request.",
                            "Implementation hints are investigation_lead values, not facts or decisions.",
                            "planning_blocking_questions are engineering requirements that authorized actual evidence must answer before implementation planning; they are not user ambiguities or expected missing facts.",
                            "A ready plan declares at least one stable requirement_id, maps every requirement through engineering_questions, and lets every query family reference only declared question_id values.",
                            "Each planned lane references the engineering question identities it covers. Queries in one family are a case-insensitive OR union of literal managed-symbol substrings; every broad literal enlarges the bounded result set. Prefer short symbol fragments or established engineering terms, not space-separated behavioral sentences.",
                            "The first Hook Discovery slice investigates one trigger or observation direction. planning_blocking_questions contain only evidence-answerable requirements needed to identify that direction. Output presentation, feedback effects, event deduplication, death-path coverage, boundary regression, and final Runtime correctness belong in deferred_planning_or_runtime_questions and are not peer planning blockers.",
                            "Use only registered source_ids and allowed tools in the search plan.",
                            "Do not include a final Hook identity, Golden, expected evidence, historical answer, or prior output.",
                            "Queries are literal managed-symbol substring families derived from request semantics.",
                            "planning_status is advisory; deterministic validation classifies whether the returned projection and plan are executable.",
                        ],
                    },
                },
            )
            raw_plan = self.model.complete(planning_messages)
            self._planning_model_steps_used = 1
            self._runtime_diagnostics["failure_stage"] = "search_planning"
            try:
                agent_discovery = _validated_actual_plan_from_raw(
                    raw_plan,
                    sources=sources,
                )
            except ValueError as exc:
                first_error = str(exc)
                self._runtime_diagnostics["correction_attempted"] = True
                correction_messages = (
                    *planning_messages,
                    {
                        "role": "assistant",
                        "content": {
                            "message_type": "rejected_actual_plan",
                            "structured_output": raw_plan,
                        },
                    },
                    {
                        "role": "user",
                        "content": {
                            "message_type": "actual_planning_validation_error",
                            "error_code": first_error,
                            "topology_issues": _planning_topology_issues(raw_plan),
                            "required_next_action": "plan",
                            "required_plan_schema": evidence_discovery_planning_schema(),
                            "instruction": (
                                "Return one corrected actual-only plan. Preserve request "
                                "semantics and registered source_ids. Correct every listed "
                                "topology issue by declaring stable planning requirements, "
                                "mapping them through engineering questions, and binding "
                                "query families only to declared question identities. Do not "
                                "add a Hook "
                                "identity, Golden, expected facts, historical answer, or "
                                "prior output beyond correcting this rejected plan."
                            ),
                        },
                    },
                )
                corrected_raw_plan = self.model.complete(correction_messages)
                self._planning_model_steps_used = 2
                agent_discovery = _validated_actual_plan_from_raw(
                    corrected_raw_plan,
                    sources=sources,
                )
            self._agent_discovery = agent_discovery
            if agent_discovery["planning_status"] != "ready":
                return self._planning_insufficient_result(
                    request=request,
                    agent_discovery=agent_discovery,
                )
            initial_messages = (
                initial_messages[0],
                initial_messages[1],
                {
                    "role": "assistant",
                    "content": {
                        "message_type": "frozen_actual_plan",
                        "agent_discovery": agent_discovery,
                    },
                },
                {
                    "role": "user",
                    "content": {
                        "message_type": "execute_frozen_plan",
                        "required_next_action": "use_tool",
                        "instruction": (
                            "Begin with one planned metadata query family. Exact IL may "
                            "consume only a candidate_ref from this run's observation. "
                            "After reading the first metadata observation, inspect a "
                            "method only when its returned symbol and matched_queries "
                            "address the primary engineering question. When they do not, "
                            "select another family only if the frozen plan already contains "
                            "one not-yet-executed family bound to that same question; "
                            "otherwise stop without inventing or rewriting a family_id."
                        ),
                    },
                },
            )
        prompt_contract = {
            "version": (
                AGENT_DISCOVERY_PROMPT_CONTRACT_VERSION
                if request.require_actual_planning
                else EVIDENCE_DISCOVERY_PROMPT_CONTRACT_VERSION
            ),
            "system_contract_sha256": _json_sha256(initial_messages[0]["content"]),
            "initial_context_sha256": _json_sha256(initial_messages[1]["content"]),
            "context_strategy": (
                "deduplicated_catalog_latest_observation_zero_result_recovery_"
                "repeat_correction_and_supported_facts_v6"
            ),
            "raw_prompt_persisted": False,
            "actual_planning_required": request.require_actual_planning,
            "agent_discovery_sha256": (
                _json_sha256(agent_discovery) if agent_discovery is not None else None
            ),
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
        zero_result_recovery_correction_used = False
        repeated_action_correction_used = False
        executed_tool_action_signatures: set[str] = set()

        model_steps_used = 0
        for model_step in range(1, request.max_model_steps + 1):
            model_steps_used = model_step
            self._runtime_diagnostics["failure_stage"] = "turn_context_construction"
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
            if correction_required:
                self._runtime_diagnostics["correction_attempted"] = True
            pending_observation = None
            finish_validation_error = None
            tool_action_validation_error = None
            self._runtime_diagnostics["failure_stage"] = "provider_turn"
            raw = self.model.complete(messages)
            self._runtime_diagnostics["failure_stage"] = "action_parsing"
            action = _parse_action(raw)
            raw_action = action
            resolved_action: dict[str, object] | None = None
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
                zero_result_recovery_required = _zero_result_recovery_required(
                    actions=actions,
                    observations=observations,
                    request=request,
                    model_step=model_step,
                )
                allowed_unexecuted_query_families: list[dict[str, object]] | None = None
                if zero_result_recovery_required and self._agent_discovery is not None:
                    allowed_unexecuted_query_families = (
                        _unexecuted_query_family_views(
                            agent_discovery=self._agent_discovery,
                            actions=actions,
                        )
                    )
                    zero_result_recovery_required = bool(
                        allowed_unexecuted_query_families
                    )
                if zero_result_recovery_required:
                    model_action_attempts.append(
                        _model_action_attempt(
                            model_step=model_step,
                            action=action,
                            status="rejected",
                            validation_error="ZERO_RESULT_RECOVERY_REQUIRED",
                        )
                    )
                    if zero_result_recovery_correction_used:
                        return self._budget_result(
                            request=request,
                            actions=actions,
                            observations=observations,
                            candidate_origins=candidate_origins,
                            reason=(
                                "The single zero-result recovery opportunity was "
                                "not used for a different metadata search."
                            ),
                            prompt_contract=prompt_contract,
                            model_steps_used=model_steps_used,
                            total_observation_bytes=total_observation_bytes,
                            discovery_message_bytes_by_turn=(
                                discovery_message_bytes_by_turn
                            ),
                            model_action_attempts=model_action_attempts,
                        )
                    zero_result_recovery_correction_used = True
                    required_change = (
                        "Use search_dotnet_metadata once with a materially "
                        "different literal managed-symbol substring, result_kinds, "
                        "or authorized source. Do not infer a hidden symbol."
                    )
                    if self._agent_discovery is not None:
                        required_change = (
                            "Select exactly one not-yet-executed family_id from "
                            "frozen_actual_plan, select one of that family's source_ids, "
                            "and bind derived_from_observation_ids to the zero-result "
                            "metadata observation. Do not copy or alter the family's "
                            "tool, queries, evidence_need, or tuning."
                        )
                    tool_action_validation_error = {
                        "error_code": "ZERO_RESULT_RECOVERY_REQUIRED",
                        "rejected_action_signature_sha256": _json_sha256(action),
                        "required_change": required_change,
                        "finish_allowed": False,
                    }
                    if self._agent_discovery is not None:
                        tool_action_validation_error[
                            "allowed_unexecuted_query_families"
                        ] = allowed_unexecuted_query_families
                    continue
                self._runtime_diagnostics["failure_stage"] = "finish_validation"
                try:
                    _validate_finish(
                        action,
                        observations_by_id,
                        agent_discovery=self._agent_discovery,
                    )
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
                        result = self._budget_result(
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
                        if error == "OBSERVED_CONCLUSION_CANONICAL_FACT_MISMATCH":
                            self._runtime_diagnostics["failure_stage"] = (
                                "finish_validation"
                            )
                            self._runtime_diagnostics["symbolic_failure_code"] = error
                        return result
                    if (
                        error == "OBSERVED_CONCLUSION_CANONICAL_FACT_MISMATCH"
                        and model_step == request.max_model_steps
                    ):
                        self._runtime_diagnostics["failure_stage"] = (
                            "finish_validation"
                        )
                        self._runtime_diagnostics["symbolic_failure_code"] = error
                        self._runtime_diagnostics["correction_attempted"] = False
                        self._runtime_diagnostics[
                            "correction_unavailable_reason"
                        ] = "no_remaining_model_turn"
                        terminal_error = ValueError(error)
                        terminal_error.run_status = "budget_exhausted"  # type: ignore[attr-defined]
                        raise terminal_error
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
            self._runtime_diagnostics["failure_stage"] = "action_validation"
            if self._agent_discovery is not None:
                action = _resolve_action_from_frozen_plan(
                    raw_action,
                    actions=actions,
                    agent_discovery=self._agent_discovery,
                )
                if action != raw_action:
                    resolved_action = action
            _validate_tool_action(
                action,
                sources=sources,
                observations_by_id=observations_by_id,
                candidate_origins=candidate_origins,
            )
            if self._agent_discovery is not None:
                _validate_action_against_frozen_plan(
                    action,
                    actions=actions,
                    observations=observations,
                    agent_discovery=self._agent_discovery,
                )
            self._runtime_diagnostics["failure_stage"] = "repeat_policy"
            action_signature = _tool_action_signature(action)
            if action_signature in executed_tool_action_signatures:
                model_action_attempts.append(
                    _model_action_attempt(
                        model_step=model_step,
                        action=raw_action,
                        status="rejected",
                        validation_error="REPEATED_EXACT_TOOL_ACTION",
                        resolved_action=resolved_action,
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
            self._runtime_diagnostics["deterministic_validation_passed"] = int(
                self._runtime_diagnostics["deterministic_validation_passed"]
            ) + 1
            model_action_attempts.append(
                _model_action_attempt(
                    model_step=model_step,
                    action=raw_action,
                    status="accepted",
                    resolved_action=resolved_action,
                )
            )
            observation_id = f"obs-{len(observations) + 1:03d}"
            source = sources[str(action["source_id"])]
            self._runtime_diagnostics["failure_stage"] = "tool_dispatch"
            self._runtime_diagnostics["dispatch_started"] = int(
                self._runtime_diagnostics["dispatch_started"]
            ) + 1
            self._runtime_diagnostics["failure_stage"] = "tool_execution"
            observation = self.tool_executor.execute(
                action=action,
                source=source,
                observation_id=observation_id,
            )
            self._runtime_diagnostics["tool_execution_completed"] = int(
                self._runtime_diagnostics["tool_execution_completed"]
            ) + 1
            self._runtime_diagnostics["observation_created"] = int(
                self._runtime_diagnostics["observation_created"]
            ) + 1
            self._runtime_diagnostics["failure_stage"] = "observation_validation"
            _validate_observation(observation, action=action)
            self._runtime_diagnostics["failure_stage"] = "observation_projection"
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
            self._runtime_diagnostics["failure_stage"] = "observation_registration"
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

    def _planning_insufficient_result(
        self,
        *,
        request: EvidenceDiscoveryRequest,
        agent_discovery: dict[str, object],
    ) -> EvidenceDiscoveryResult:
        state = agent_discovery_early_termination_state(agent_discovery)
        status = str(state["run_status"])
        input_audit = _input_audit(request)
        pack = EvidencePack(
            query=request.natural_language_request,
            readiness=state["readiness"],
            can_generate_patch=state["can_generate_patch"],
            gaps=state["gaps"],
            blockers=state["blockers"],
            missing_evidence=state["missing_evidence"],
            run_status=status,
            agent_discovery=agent_discovery,
            prompt_contract={
                "version": AGENT_DISCOVERY_PROMPT_CONTRACT_VERSION,
                "actual_planning_required": True,
                "agent_discovery_sha256": _json_sha256(agent_discovery),
                "raw_prompt_persisted": False,
            },
            input_audit=input_audit,
            message=str(state["message"]),
        )
        transfer = {
            "source_selection_by_platform": True,
            "tool_selection_by_platform": False,
            "symbol_discovery_by_platform": False,
            "followup_selection_by_platform": False,
            "evidence_interpretation_by_platform": False,
            "converged_before_budget": True,
            "grounded_conclusion_by_platform": False,
            "unproductive_repetition_absent": True,
            "semantic_relevance_evaluated": False,
        }
        return EvidenceDiscoveryResult(
            run_status=status,
            pack=pack,
            actions=(),
            observations=(),
            input_audit=input_audit,
            intelligence_transfer=transfer,
            agent_discovery=agent_discovery,
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
        self._runtime_diagnostics["failure_stage"] = "result_construction"
        unverified_method_refs = _unverified_method_refs(
            actions=actions,
            observations=observations,
            max_tool_calls=request.max_tool_calls,
        )
        if unverified_method_refs:
            finish = dict(finish)
            finish["decision"] = "needs_more_evidence"
            finish["unresolved_questions"] = [
                *list(finish.get("unresolved_questions", [])),
                (
                    "Tool budget ended with metadata method references that did not "
                    "receive exact IL verification: " + ", ".join(unverified_method_refs)
                ),
            ]
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
        hook_discovery = (
            build_agent_discovery_semantics(
                agent_discovery=self._agent_discovery,
                items=items,
                actions=actions,
                observations=observations,
                finish=finish,
            )
            if self._agent_discovery is not None
            else None
        )
        semantic_state = (
            evidence_pack_state_from_hook_discovery(
                semantics=hook_discovery,
                items=items,
            )
            if hook_discovery is not None
            else None
        )
        if semantic_state is not None:
            blockers = semantic_state["blockers"]
        pack = EvidencePack(
            query=request.natural_language_request,
            readiness=(
                semantic_state["readiness"]
                if semantic_state is not None
                else "partial" if items else "insufficient"
            ),
            can_generate_patch=(
                semantic_state["can_generate_patch"]
                if semantic_state is not None
                else False
            ),
            items=(semantic_state["items"] if semantic_state is not None else items),
            excluded=(semantic_state["excluded"] if semantic_state is not None else ()),
            gaps=(
                semantic_state["gaps"]
                if semantic_state is not None
                else (*unresolved, *missing_capabilities)
            ),
            blockers=blockers,
            retrieval_methods_used=tuple(
                dict.fromkeys(observation.tool for observation in observations)
            ),
            disabled_modes={
                "bm25": "Not used by the bounded intelligent evidence loop.",
                "dense": "Not used by the bounded intelligent evidence loop.",
                "fusion": "Not used by the bounded intelligent evidence loop.",
                "rerank": "Not used by the bounded intelligent evidence loop.",
            },
            missing_evidence=missing_evidence_from_blockers(blockers),
            timing={},
            budget_summary={
                "max_tool_calls": request.max_tool_calls,
                "tool_calls_used": len(actions),
                "max_model_steps": request.max_model_steps,
                "model_steps_used": model_steps_used,
                **(
                    {
                        "planning_model_steps_used": self._planning_model_steps_used,
                        "total_model_steps_used": (
                            model_steps_used + self._planning_model_steps_used
                        ),
                    }
                    if request.require_actual_planning
                    else {}
                ),
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
                observations=tuple(observations),
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
                    "observation_sha256": observation.identity_sha256(),
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
            hook_discovery=hook_discovery,
            agent_discovery=self._agent_discovery,
            message=(
                semantic_state["message"]
                if semantic_state is not None
                else (
                    "The Evidence specialist selected sources and tools through a bounded "
                    "action/observation loop; deterministic policy retained routing authority."
                )
            ),
        )
        return EvidenceDiscoveryResult(
            run_status=run_status,
            pack=pack,
            actions=tuple(actions),
            observations=tuple(observations),
            input_audit=input_audit,
            intelligence_transfer=intelligence_transfer,
            agent_discovery=self._agent_discovery,
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
                    "required_finish_schema": evidence_discovery_finish_schema(
                        require_requirement_binding=request.require_actual_planning
                    ),
                    "decision_constraints": (
                        evidence_discovery_finish_decision_constraints()
                    ),
                    "repair_focus": _finish_validation_repair_focus(
                        finish_validation_error,
                        require_requirement_binding=request.require_actual_planning,
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
        required_change = str(
            tool_action_validation_error.get("required_change")
            or (
                "Choose a different source, tool, or arguments, or finish. "
                "Changing only evidence_need or derived observation ids does "
                "not make the action different."
            )
        )
        messages.append(
            {
                "role": "user",
                "content": {
                    "message_type": "tool_action_validation_error",
                    **tool_action_validation_error,
                    "executed_tool_call_count": len(actions),
                    "required_change": required_change,
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
                        "use_tool"
                        if (
                            tool_action_validation_error is not None
                            and tool_action_validation_error.get("finish_allowed")
                            is False
                        )
                        else (
                            "finish_or_use_tool_for_exact_gap"
                            if acceptance_progress["progress"][
                                "inspect_method_il_observation_ids"
                            ]
                            else "use_tool_or_finish"
                        )
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


def _unverified_method_refs(
    *,
    actions: list[dict[str, object]],
    observations: list[ToolObservation],
    max_tool_calls: int,
) -> list[str]:
    """Keep method refs from a terminal metadata call as unverified leads."""

    if (
        not actions
        or len(actions) < max_tool_calls
        or actions[-1].get("tool") != "search_dotnet_metadata"
        or not observations
        or observations[-1].tool != "search_dotnet_metadata"
    ):
        return []
    observed = set(_metadata_candidate_refs([observations[-1]]))
    inspected = {
        str(arguments["candidate_ref"])
        for action in actions
        if action.get("tool") == "inspect_method_il"
        and isinstance((arguments := action.get("arguments")), dict)
        and arguments.get("candidate_ref")
    }
    return sorted(observed - inspected)


def _zero_result_recovery_required(
    *,
    actions: list[dict[str, object]],
    observations: list[ToolObservation],
    request: EvidenceDiscoveryRequest,
    model_step: int,
) -> bool:
    """Require one bounded alternate search before accepting a first zero-result stop."""

    if (
        len(actions) != 1
        or len(observations) != 1
        or len(actions) >= request.max_tool_calls
        or model_step >= request.max_model_steps
    ):
        return False
    action = actions[0]
    observation = observations[0]
    if (
        action.get("action") != "use_tool"
        or action.get("tool") != "search_dotnet_metadata"
        or observation.tool != "search_dotnet_metadata"
    ):
        return False
    return not _metadata_candidate_refs(observations)


def _finish_validation_repair_focus(
    error_code: str,
    *,
    require_requirement_binding: bool = False,
) -> dict[str, object]:
    if error_code == "DISCOVERY_DECISION_INVALID":
        return {
            "field": "decision",
            "requirement": "Use exactly one value from allowed_decisions.",
        }
    if error_code == "EVIDENCE_CONCLUSION_SHAPE_INVALID":
        required_keys = [
            "claim",
            "claim_status",
            "observation_ids",
            "limitations",
        ]
        field_types = {
            "claim": "non-empty string",
            "claim_status": "observed | inferred | unknown",
            "observation_ids": "array of non-empty strings",
            "limitations": "array of non-empty strings",
        }
        if require_requirement_binding:
            required_keys.extend(["requirement_ids", "relationship"])
            field_types.update(
                {
                    "requirement_ids": "array of planning requirement ids",
                    "relationship": "support | conflict | missing",
                }
            )
        return {
            "field": "evidence_conclusions[]",
            "required_keys": required_keys,
            "field_types": field_types,
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
    if error_code == "EVIDENCE_CONCLUSION_REQUIREMENT_BINDING_INVALID":
        return {
            "field": "evidence_conclusions[]",
            "requirement": (
                "For the frozen actual plan, add non-empty requirement_ids drawn "
                "exactly from planning_blocking_questions and set relationship to "
                "support, conflict, or missing."
            ),
        }
    if error_code == "OBSERVED_CONCLUSION_CANONICAL_FACT_MISMATCH":
        return {
            "field": "evidence_conclusions[]",
            "requirement": (
                "Each observed claim must exactly copy one supported_fact "
                "canonical_claim and cite only that fact's observation_id. Put any "
                "interpretation in a separate inferred conclusion with limitations."
            ),
        }
    if error_code == "EVIDENCE_CONCLUSION_OBSERVATION_REQUIRED":
        return {
            "field": "evidence_conclusions[]",
            "requirement": (
                "An observed claim must exactly copy one supported_fact canonical_claim. "
                "An inferred claim must cite at least one actual observation_id and "
                "state non-empty limitations. If no observation grounds the claim, use "
                "claim_status=unknown with no observation_ids and non-empty limitations."
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


def _new_runtime_diagnostics() -> dict[str, object]:
    return {
        "provider_tool_calls": 0,
        "adapter_accepted_actions": 0,
        "deterministic_validation_passed": 0,
        "dispatch_started": 0,
        "tool_execution_completed": 0,
        "observation_created": 0,
        "failure_stage": "not_started",
        "symbolic_failure_code": "none",
        "correction_attempted": False,
        "correction_unavailable_reason": "none",
    }


def _provider_tool_call_count(model: EvidenceDiscoveryModel) -> int:
    total = 0
    for record in getattr(model, "provider_turn_records", ()):
        if not isinstance(record, dict):
            continue
        tool_calls = record.get("tool_calls")
        if isinstance(tool_calls, list):
            total += len(tool_calls)
    return total


def _symbolic_discovery_failure_code(exc: BaseException) -> str:
    """Keep known symbolic codes while refusing arbitrary exception text."""

    message = str(exc)
    compact = message.replace("_", "")
    allowed_prefixes = (
        "ASSEMBLY_",
        "CANDIDATE_",
        "COMPACT_",
        "DISCOVERY_",
        "DUPLICATE_",
        "EVIDENCE_",
        "EXACT_",
        "FINISH_",
        "INFERRED_",
        "METADATA_",
        "METHOD_",
        "MISSING_",
        "MODEL_",
        "NEEDS_",
        "OBSERVED_",
        "REPEATED_",
        "SEARCH_",
        "SOURCE_",
        "SUFFICIENT_",
        "TOOL_",
        "UNAUTHORIZED_",
        "UNKNOWN_",
        "UNVERIFIED_",
    )
    if (
        3 <= len(message) <= 96
        and compact.isalnum()
        and message == message.upper()
        and message.startswith(allowed_prefixes)
    ):
        return message
    if isinstance(exc, ValueError):
        return "EVIDENCE_DISCOVERY_VALUE_ERROR"
    if isinstance(exc, OSError):
        return "EVIDENCE_DISCOVERY_OS_ERROR"
    return "EVIDENCE_DISCOVERY_RUNTIME_ERROR"


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


def _parse_planning_action(raw: str) -> dict[str, object]:
    try:
        action = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"PLANNING_ACTION_INVALID_JSON: {exc}") from exc
    if not isinstance(action, dict) or action.get("action") != "plan":
        raise ValueError("PLANNING_ACTION_TYPE_INVALID")
    if set(action) != {
        "action",
        "planning_status",
        "requirement_projection",
        "search_plan",
    }:
        raise ValueError("PLANNING_ACTION_SHAPE_INVALID")
    return action


def _planning_topology_issues(raw: str) -> list[dict[str, object]]:
    """Describe only structural planning-reference failures from one rejected output."""

    try:
        action = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(action, dict):
        return []
    projection = action.get("requirement_projection")
    search_plan = action.get("search_plan")
    if not isinstance(projection, dict) or not isinstance(search_plan, dict):
        return []

    requirements = projection.get("planning_blocking_questions")
    engineering_questions = search_plan.get("engineering_questions")
    query_families = search_plan.get("query_families")
    requirements = requirements if isinstance(requirements, list) else []
    engineering_questions = (
        engineering_questions if isinstance(engineering_questions, list) else []
    )
    query_families = query_families if isinstance(query_families, list) else []

    requirement_ids = {
        str(item["requirement_id"])
        for item in requirements
        if isinstance(item, dict)
        and isinstance(item.get("requirement_id"), str)
        and str(item["requirement_id"]).strip()
    }
    question_ids = {
        str(item["question_id"])
        for item in engineering_questions
        if isinstance(item, dict)
        and isinstance(item.get("question_id"), str)
        and str(item["question_id"]).strip()
    }
    issues: list[dict[str, object]] = []
    if not requirement_ids:
        issues.append({"code": "PLANNING_REQUIREMENTS_EMPTY"})
    if not question_ids:
        issues.append({"code": "ENGINEERING_QUESTIONS_EMPTY"})

    referenced_requirement_ids: set[str] = set()
    for item in engineering_questions:
        if not isinstance(item, dict):
            continue
        refs = item.get("requirement_ids")
        if not isinstance(refs, list):
            continue
        referenced_requirement_ids.update(str(value) for value in refs)
    unknown_requirement_ids = sorted(referenced_requirement_ids - requirement_ids)
    if unknown_requirement_ids:
        issues.append(
            {
                "code": "ENGINEERING_REQUIREMENT_REFERENCE_UNKNOWN",
                "unknown_requirement_ids": unknown_requirement_ids,
            }
        )
    uncovered_requirement_ids = sorted(requirement_ids - referenced_requirement_ids)
    if uncovered_requirement_ids:
        issues.append(
            {
                "code": "PLANNING_REQUIREMENT_NOT_COVERED",
                "requirement_ids": uncovered_requirement_ids,
            }
        )

    referenced_question_ids: set[str] = set()
    family_ids_by_question_id: dict[str, set[str]] = {}
    for item in query_families:
        if not isinstance(item, dict):
            continue
        family_id = item.get("family_id")
        refs = item.get("question_ids")
        if not isinstance(refs, list):
            continue
        for value in refs:
            question_id = str(value)
            referenced_question_ids.add(question_id)
            if isinstance(family_id, str) and family_id.strip():
                family_ids_by_question_id.setdefault(question_id, set()).add(family_id)
    unknown_question_ids = sorted(referenced_question_ids - question_ids)
    if unknown_question_ids:
        issues.append(
            {
                "code": "QUERY_FAMILY_QUESTION_REFERENCE_UNKNOWN",
                "unknown_question_ids": unknown_question_ids,
                "family_ids": sorted(
                    {
                        family_id
                        for question_id in unknown_question_ids
                        for family_id in family_ids_by_question_id.get(question_id, set())
                    }
                ),
            }
        )
    uncovered_question_ids = sorted(question_ids - referenced_question_ids)
    if uncovered_question_ids:
        issues.append(
            {
                "code": "ENGINEERING_QUESTION_NOT_COVERED",
                "question_ids": uncovered_question_ids,
            }
        )
    return issues


def _validated_actual_plan_from_raw(
    raw: str,
    *,
    sources: dict[str, EvidenceDiscoverySource],
) -> dict[str, object]:
    plan_action = _parse_planning_action(raw)
    agent_discovery = normalize_agent_discovery_planning_actual(
        {
            "schema_version": AGENT_DISCOVERY_ACTUAL_SCHEMA_VERSION,
            "planning_status": plan_action["planning_status"],
            "requirement_projection": plan_action["requirement_projection"],
            "search_plan": plan_action["search_plan"],
        }
    )
    _validate_plan_against_sources(agent_discovery, sources=sources)
    return agent_discovery


def _validate_plan_against_sources(
    agent_discovery: dict[str, object],
    *,
    sources: dict[str, EvidenceDiscoverySource],
) -> None:
    search_plan = agent_discovery.get("search_plan")
    if search_plan is None:
        return
    if not isinstance(search_plan, dict):
        raise ValueError("SEARCH_PLAN_MUST_BE_OBJECT")
    for collection_name in ("source_roles", "planned_lanes", "query_families"):
        entries = search_plan.get(collection_name)
        if not isinstance(entries, list):
            raise ValueError("SEARCH_PLAN_COLLECTION_INVALID")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("SEARCH_PLAN_ENTRY_INVALID")
            source_ids = (
                [entry.get("source_id")]
                if collection_name == "source_roles"
                else entry.get("source_ids")
            )
            if not isinstance(source_ids, list) or any(
                source_id not in sources for source_id in source_ids
            ):
                raise ValueError("SEARCH_PLAN_UNAUTHORIZED_SOURCE")
            tool = entry.get("tool")
            if isinstance(tool, str) and any(
                tool not in sources[str(source_id)].allowed_tools
                for source_id in source_ids
            ):
                raise ValueError("SEARCH_PLAN_SOURCE_TOOL_NOT_ALLOWED")


def _resolve_action_from_frozen_plan(
    raw_action: dict[str, object],
    *,
    actions: list[dict[str, object]],
    agent_discovery: dict[str, object],
) -> dict[str, object]:
    """Resolve one exact metadata family selection without text matching."""

    if raw_action.get("tool") != "search_dotnet_metadata":
        return raw_action
    if set(raw_action) != {
        "action",
        "tool",
        "source_id",
        "family_id",
        "derived_from_observation_ids",
    }:
        raise ValueError("QUERY_FAMILY_SELECTION_SHAPE_INVALID")
    family_id = raw_action.get("family_id")
    if not isinstance(family_id, str) or not family_id.strip():
        raise ValueError("QUERY_FAMILY_ID_INVALID")
    search_plan = agent_discovery.get("search_plan")
    if not isinstance(search_plan, dict):
        raise ValueError("SEARCH_PLAN_MUST_BE_OBJECT")
    families = search_plan.get("query_families")
    if not isinstance(families, list):
        raise ValueError("SEARCH_PLAN_QUERY_FAMILIES_INVALID")
    matches = [
        family
        for family in families
        if isinstance(family, dict) and family.get("family_id") == family_id
    ]
    if len(matches) != 1:
        raise ValueError("QUERY_FAMILY_ID_UNKNOWN")
    family = matches[0]
    if family.get("tool") != "search_dotnet_metadata":
        raise ValueError("QUERY_FAMILY_TOOL_INVALID")
    source_ids = family.get("source_ids")
    if (
        not isinstance(source_ids, list)
        or raw_action.get("source_id") not in source_ids
    ):
        raise ValueError("QUERY_FAMILY_SOURCE_NOT_ALLOWED")
    if family_id in {
        str(action.get("query_family_id"))
        for action in actions
        if isinstance(action.get("query_family_id"), str)
    }:
        raise ValueError("QUERY_FAMILY_ALREADY_EXECUTED")
    queries = family.get("queries")
    evidence_need = family.get("evidence_need")
    if (
        not isinstance(queries, list)
        or not queries
        or any(not isinstance(query, str) or not query.strip() for query in queries)
        or not isinstance(evidence_need, str)
        or not evidence_need.strip()
    ):
        raise ValueError("QUERY_FAMILY_FROZEN_CONTENT_INVALID")
    return {
        "action": "use_tool",
        "tool": "search_dotnet_metadata",
        "source_id": raw_action["source_id"],
        "arguments": {
            "queries": list(queries),
            "result_kinds": ["methods"],
            "limit_per_kind": 10,
        },
        "evidence_need": evidence_need,
        "derived_from_observation_ids": list(
            raw_action.get("derived_from_observation_ids") or []
        ),
        "query_family_id": family_id,
    }


def _validate_action_against_frozen_plan(
    action: dict[str, object],
    *,
    actions: list[dict[str, object]],
    observations: list[ToolObservation],
    agent_discovery: dict[str, object],
) -> None:
    search_plan = agent_discovery.get("search_plan")
    if not isinstance(search_plan, dict):
        raise ValueError("SEARCH_PLAN_MUST_BE_OBJECT")
    if not actions:
        if action.get("tool") != "search_dotnet_metadata":
            raise ValueError("FIRST_DISCOVERY_ACTION_MUST_BE_METADATA_SEARCH")
        arguments = action.get("arguments")
        families = search_plan.get("query_families")
        if not isinstance(arguments, dict) or not isinstance(families, list):
            raise ValueError("FIRST_DISCOVERY_ACTION_NOT_PLANNED")
        if len(_matching_query_family_ids(action=action, families=families)) != 1:
            raise ValueError("FIRST_DISCOVERY_ACTION_NOT_PLANNED")
        return
    if len(actions) == 1:
        if action.get("tool") == "inspect_method_il":
            return
        _validate_supplemental_search(
            action,
            actions=actions,
            observations=observations,
            agent_discovery=agent_discovery,
        )
        return
    if len(actions) == 2:
        if (
            action.get("tool") == "inspect_method_il"
            and _latest_metadata_observation_has_identity(observations)
        ):
            latest_observation_id = observations[-1].observation_id
            if action.get("derived_from_observation_ids") != [latest_observation_id]:
                raise ValueError(
                    "SECOND_METADATA_IL_MUST_BIND_LATEST_OBSERVATION"
                )
            return
        if (
            actions[0].get("tool") == "search_dotnet_metadata"
            and actions[1].get("tool") == "search_dotnet_metadata"
            and not _latest_metadata_observation_has_identity(observations)
        ):
            raise ValueError("SECOND_METADATA_SEARCH_EXHAUSTED_WITHOUT_METHOD")
        if (
            actions[0].get("tool") == "search_dotnet_metadata"
            and actions[1].get("tool") == "search_dotnet_metadata"
        ):
            raise ValueError("SECOND_METADATA_SEARCH_REQUIRES_IDENTITY_VERIFICATION")
        _validate_supplemental_search(
            action,
            actions=actions,
            observations=observations,
            agent_discovery=agent_discovery,
        )
        return
    raise ValueError("FIRST_HOOK_DISCOVERY_TOOL_BUDGET_EXHAUSTED")


def _validate_supplemental_search(
    action: dict[str, object],
    *,
    actions: list[dict[str, object]],
    observations: list[ToolObservation],
    agent_discovery: dict[str, object],
) -> None:
    if action.get("tool") != "search_dotnet_metadata":
        raise ValueError("SUPPLEMENTAL_ACTION_MUST_BE_METADATA_SEARCH")
    projection = agent_discovery.get("requirement_projection")
    search_plan = agent_discovery.get("search_plan")
    if not isinstance(projection, dict) or not isinstance(search_plan, dict):
        raise ValueError("AGENT_DISCOVERY_PLAN_MUST_BE_OBJECT")
    families = search_plan.get("query_families")
    matching_family_ids = _matching_query_family_ids(
        action=action,
        families=families if isinstance(families, list) else [],
    )
    executed_family_ids = {
        str(executed_action["query_family_id"])
        for executed_action in actions
        if isinstance(executed_action.get("query_family_id"), str)
    }
    selected_family = (
        next(
            (
                family
                for family in families
                if isinstance(family, dict)
                and family.get("family_id") in matching_family_ids
            ),
            None,
        )
        if isinstance(families, list)
        else None
    )
    if not isinstance(families, list):
        raise ValueError("SUPPLEMENTAL_ACTION_SHAPE_INVALID")
    if not observations or len(actions) != len(observations):
        raise ValueError("SUPPLEMENTAL_ACTION_OBSERVATION_BINDING_INVALID")
    if action.get("derived_from_observation_ids") != [
        observations[-1].observation_id
    ]:
        raise ValueError("SUPPLEMENTAL_ACTION_OBSERVATION_BINDING_REQUIRED")
    if len(matching_family_ids) != 1 or not isinstance(selected_family, dict):
        raise ValueError("SUPPLEMENTAL_QUERY_FAMILY_MATCH_INVALID")
    if matching_family_ids[0] in executed_family_ids:
        raise ValueError("SUPPLEMENTAL_QUERY_FAMILY_ALREADY_EXECUTED")
    family_by_id = {
        str(family["family_id"]): family
        for family in families
        if isinstance(family, dict) and isinstance(family.get("family_id"), str)
    }
    latest_action = actions[-1]
    origin_family_id = latest_action.get("query_family_id")
    if latest_action.get("tool") == "inspect_method_il":
        derived_ids = latest_action.get("derived_from_observation_ids")
        metadata_origins = {
            str(origin_action["query_family_id"])
            for origin_action, observation in zip(actions, observations)
            if isinstance(derived_ids, list)
            and observation.observation_id in derived_ids
            and origin_action.get("tool") == "search_dotnet_metadata"
            and isinstance(origin_action.get("query_family_id"), str)
        }
        if len(metadata_origins) != 1:
            raise ValueError("SUPPLEMENTAL_ORIGIN_QUERY_FAMILY_INVALID")
        origin_family_id = next(iter(metadata_origins))
    origin_family = family_by_id.get(str(origin_family_id or ""))
    if not isinstance(origin_family, dict):
        raise ValueError("SUPPLEMENTAL_ORIGIN_QUERY_FAMILY_INVALID")
    if latest_action.get("tool") == "search_dotnet_metadata":
        selected_question_ids = selected_family.get("question_ids")
        origin_question_ids = origin_family.get("question_ids")
        if (
            not isinstance(selected_question_ids, list)
            or not isinstance(origin_question_ids, list)
            or set(selected_question_ids) != set(origin_question_ids)
        ):
            raise ValueError("SUPPLEMENTAL_QUERY_FAMILY_QUESTION_BINDING_MISMATCH")


def _matching_query_family_ids(
    *,
    action: dict[str, object],
    families: list[object],
) -> list[str]:
    """Verify a resolved action against its exact frozen family identity."""

    arguments = action.get("arguments")
    if action.get("tool") != "search_dotnet_metadata" or not isinstance(arguments, dict):
        return []
    family_id = action.get("query_family_id")
    matches: list[str] = []
    for family in families:
        if (
            isinstance(family, dict)
            and isinstance(family.get("family_id"), str)
            and family.get("family_id") == family_id
            and family.get("queries") == arguments.get("queries")
            and action.get("source_id") in family.get("source_ids", [])
            and family.get("tool") == "search_dotnet_metadata"
            and family.get("evidence_need") == action.get("evidence_need")
        ):
            matches.append(str(family["family_id"]))
    return matches


def _unexecuted_query_family_views(
    *,
    agent_discovery: dict[str, object],
    actions: list[dict[str, object]],
) -> list[dict[str, object]]:
    search_plan = agent_discovery.get("search_plan")
    if not isinstance(search_plan, dict):
        return []
    families = search_plan.get("query_families")
    if not isinstance(families, list):
        return []
    executed_ids = {
        str(action["query_family_id"])
        for action in actions
        if isinstance(action.get("query_family_id"), str)
    }
    required_question_ids: set[str] | None = None
    if actions and actions[-1].get("tool") == "search_dotnet_metadata":
        latest_family_id = actions[-1].get("query_family_id")
        latest_family = next(
            (
                family
                for family in families
                if isinstance(family, dict)
                and family.get("family_id") == latest_family_id
            ),
            None,
        )
        latest_question_ids = (
            latest_family.get("question_ids")
            if isinstance(latest_family, dict)
            else None
        )
        if isinstance(latest_question_ids, list):
            required_question_ids = {str(value) for value in latest_question_ids}
    return [
        {
            key: (
                list(family[key])
                if isinstance(family.get(key), list)
                else family.get(key)
            )
            for key in (
                "family_id",
                "queries",
                "evidence_need",
                "source_ids",
                "tool",
                "question_ids",
            )
        }
        for family in families
        if isinstance(family, dict)
        and isinstance(family.get("family_id"), str)
        and family["family_id"] not in executed_ids
        and (
            required_question_ids is None
            or (
                isinstance(family.get("question_ids"), list)
                and {str(value) for value in family["question_ids"]}
                == required_question_ids
            )
        )
    ]


def _latest_metadata_observation_has_no_identity(
    observations: list[ToolObservation],
) -> bool:
    return (
        bool(observations)
        and observations[-1].tool == "search_dotnet_metadata"
        and not _latest_metadata_observation_has_identity(observations)
    )


def _latest_metadata_observation_has_identity(
    observations: list[ToolObservation],
) -> bool:
    if not observations or observations[-1].tool != "search_dotnet_metadata":
        return False
    methods = observations[-1].data.get("methods")
    return bool(
        isinstance(methods, list)
        and any(
            isinstance(method, dict) and method.get("candidate_ref")
            for method in methods
        )
    )


def _validate_tool_action(
    action: dict[str, object],
    *,
    sources: dict[str, EvidenceDiscoverySource],
    observations_by_id: dict[str, ToolObservation],
    candidate_origins: dict[str, tuple[str, str]],
) -> None:
    required_fields = {
        "action",
        "tool",
        "source_id",
        "arguments",
        "evidence_need",
        "derived_from_observation_ids",
    }
    tool = str(action.get("tool") or "")
    allowed_shapes = {frozenset(required_fields)}
    if tool == "search_dotnet_metadata":
        allowed_shapes.add(frozenset(required_fields | {"query_family_id"}))
    if frozenset(action) not in allowed_shapes:
        raise ValueError("TOOL_ACTION_SHAPE_INVALID")
    if not str(action.get("evidence_need") or "").strip():
        raise ValueError("TOOL_EVIDENCE_NEED_INVALID")
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
        if "query_family_id" in action and (
            not isinstance(action.get("query_family_id"), str)
            or not str(action["query_family_id"]).strip()
        ):
            raise ValueError("QUERY_FAMILY_ID_INVALID")
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
    *,
    agent_discovery: dict[str, object] | None = None,
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
        base_fields = {
            "claim", "claim_status", "observation_ids", "limitations"
        }
        planning_fields = {"requirement_ids", "relationship"}
        if (
            not isinstance(conclusion, dict)
            or frozenset(conclusion)
            not in {frozenset(base_fields), frozenset(base_fields | planning_fields)}
        ):
            raise ValueError("EVIDENCE_CONCLUSION_SHAPE_INVALID")
        if not str(conclusion.get("claim") or "").strip():
            raise ValueError("EVIDENCE_CONCLUSION_CLAIM_INVALID")
        status = conclusion.get("claim_status")
        if status not in {"observed", "inferred", "unknown"}:
            raise ValueError("EVIDENCE_CONCLUSION_STATUS_INVALID")
        refs = conclusion.get("observation_ids")
        limitations = conclusion.get("limitations")
        if (
            not isinstance(refs, list)
            or not isinstance(limitations, list)
            or any(
            not isinstance(item, str) or not item.strip() for item in limitations
            )
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
        if agent_discovery is not None:
            refs = conclusion.get("requirement_ids")
            relationship = conclusion.get("relationship")
            projection = agent_discovery.get("requirement_projection")
            if not isinstance(projection, dict):
                raise ValueError("REQUIREMENT_PROJECTION_MUST_BE_OBJECT")
            blockers = projection.get("planning_blocking_questions")
            valid_requirement_ids = {
                str(value["requirement_id"])
                for value in blockers
                if isinstance(blockers, list) and isinstance(value, dict)
            }
            if (
                not isinstance(refs, list)
                or not refs
                or len(refs) != len(set(refs))
                or any(value not in valid_requirement_ids for value in refs)
                or relationship not in {"support", "conflict", "missing"}
            ):
                raise ValueError("EVIDENCE_CONCLUSION_REQUIREMENT_BINDING_INVALID")
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
    relationship_values = {
        conclusion.get("relationship")
        for conclusion in conclusions
        if isinstance(conclusion, dict) and "relationship" in conclusion
    }
    if agent_discovery is not None and (
        (decision == "conflicting_evidence") != ("conflict" in relationship_values)
    ):
        raise ValueError("CONFLICTING_DECISION_RELATIONSHIP_MISMATCH")
    for conclusion in conclusions:
        if conclusion.get("claim_status") != "observed":
            continue
        matching_fact_count = sum(
            1
            for observation in observations_by_id.values()
            for fact in observation.supported_facts()
            if observed_conclusion_matches_bound_fact(
                conclusion=conclusion,
                fact=fact,
                observation_id=observation.observation_id,
                observation_tool=observation.tool,
                observation_source_id=observation.source_id,
                observation_sha256=observation.identity_sha256(),
            )
        )
        if matching_fact_count != 1:
            raise ValueError("OBSERVED_CONCLUSION_CANONICAL_FACT_MISMATCH")


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
    observations: tuple[ToolObservation, ...],
) -> tuple[dict[str, Any], ...]:
    verified: list[dict[str, Any]] = []
    for conclusion in conclusions:
        if conclusion.get("claim_status") != "observed":
            continue
        matching_facts = [
            fact
            for observation in observations
            for fact in observation.supported_facts()
            if observed_conclusion_matches_bound_fact(
                conclusion=conclusion,
                fact=fact,
                observation_id=observation.observation_id,
                observation_tool=observation.tool,
                observation_source_id=observation.source_id,
                observation_sha256=observation.identity_sha256(),
            )
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
                    (
                        "For an actual frozen plan, every conclusion names exact "
                        "requirement_ids and one support, conflict, or missing relationship."
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
            (
                "A model decision never closes a planning requirement without a bound "
                "relationship and admitted authoritative physical evidence."
            ),
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
                "il_observation_sha256": observation.identity_sha256(),
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
            "query_family_id": action.get("query_family_id"),
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
    resolved_action: dict[str, object] | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "model_step": model_step,
        "origin": "model",
        "status": status,
        "action": dict(action),
        "action_sha256": _json_sha256(action),
    }
    if resolved_action is not None:
        record["resolved_action"] = dict(resolved_action)
        record["resolved_action_sha256"] = _json_sha256(resolved_action)
    if validation_error is not None:
        record["validation_error"] = validation_error
    return record
