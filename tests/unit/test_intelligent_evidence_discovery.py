"""Intelligence-first acceptance tests for bounded evidence discovery."""

from __future__ import annotations

import json
import hashlib
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from src.mod_agent.evidence.discovery import (
    AGENT_DISCOVERY_ACTUAL_SCHEMA_VERSION,
    ChatEvidenceDiscoveryModel,
    EVIDENCE_DISCOVERY_DISCLOSURE_DATA_CLASSES,
    EvidenceDiscoveryDisclosure,
    EvidenceDiscoveryLocalExecution,
    EvidenceDiscoveryAgentModel,
    EvidenceDiscoveryRequest,
    EvidenceDiscoverySource,
    EvidenceDiscoverySpecialist,
    IntelligentEvidencePackFactory,
    ToolObservation,
    evidence_discovery_source_from_definition,
    validate_agent_discovery_actual,
)
from src.mod_agent.evidence.discovery_tools import LocalAssemblyEvidenceToolExecutor
from src.mod_agent.evidence.calibration import run_better_hit_feedback_calibration
from src.mod_agent.evidence.discovery_contract import (
    REQUIREMENT_PROJECTION_SCHEMA_VERSION,
    SEARCH_PLAN_SCHEMA_VERSION,
    evidence_discovery_finish_schema,
    evidence_discovery_planning_schema,
    evidence_discovery_requirement_projection_schema,
    evidence_discovery_search_plan_schema,
    validate_requirement_projection_actual,
)
from src.mod_agent.evidence.discovery_loop import (
    _bind_action_relation_ids,
    _bind_observation_relation_ids,
    discovery_plan_budget_feasibility,
    _normalize_family_query_leads,
    _method_focus_comparison,
    _parse_requirement_projection_action,
    _resolve_finish_fact_handles,
    _resolve_action_from_frozen_plan,
    _resolve_model_search_plan_action,
    _source_query_inputs,
    _validate_finish,
    _validate_supplemental_search,
)
from src.mod_agent.evidence.models import EvidenceItem, EvidencePack
from src.mod_agent.artifacts import (
    ArtifactRef,
    ArtifactRegistryError,
    ArtifactStore,
    ArtifactTypeRegistry,
)
from src.mod_agent.workflow import build_graph, create_initial_state
from src.mod_agent.domain.wallcrawler_acceptance import (
    evaluate_wallcrawler_local_evidence,
)
from src.libs.llm import (
    AgentToolCall,
    AgentTurnResponse,
    AgentUsage,
    BaseLLM,
    ChatResponse,
    Message,
    OllamaChatAgentAdapter,
)
from src.mod_agent.knowledge import (
    IncrementalIndexer,
    KnowledgeDatabase,
    SourceDefinition,
    SourceRegistry,
)
from src.mod_agent.evidence.retriever import DeterministicEvidenceRetriever
from src.mod_agent.intelligent_evidence_only import (
    _failed_run_diagnostics,
    _post_run_acceptance,
    load_evidence_discovery_sources,
)


def _metadata_arguments(*queries: str, limit_per_kind: int = 20) -> dict[str, object]:
    return {
        "queries": list(queries),
        "result_kinds": ["methods"],
        "limit_per_kind": limit_per_kind,
    }


def _family_selection(
    family_id: str,
    *,
    source_id: str = "current-interop",
    derived_from_observation_ids: list[str] | None = None,
) -> dict[str, object]:
    return {
        "action": "use_tool",
        "tool": "search_dotnet_metadata",
        "source_id": source_id,
        "family_id": family_id,
        "derived_from_observation_ids": list(
            derived_from_observation_ids or []
        ),
    }


def _source_identifier_selection(
    *identifiers: str,
    selection_ids: list[str] | None = None,
) -> dict[str, object]:
    return {
        "action": "select_observed_identifiers",
        "selection_ids": list(selection_ids)
        if selection_ids is not None
        else [
            f"$source_selection_for_identifier:{identifier}"
            for identifier in identifiers
        ],
    }


class _ScriptedModel:
    def __init__(
        self,
        responses: list[dict[str, object]],
        *,
        emit_stable_family_selection: bool = True,
    ) -> None:
        self._responses = [deepcopy(item) for item in responses]
        self._emit_stable_family_selection = emit_stable_family_selection
        self._frozen_plan: dict[str, object] | None = None
        self.calls: list[tuple[dict[str, object], ...]] = []

    def complete(self, messages: tuple[dict[str, object], ...]) -> str:
        self.calls.append(messages)
        response = self._responses.pop(0)
        if response.get("action") == "plan":
            self._frozen_plan = deepcopy(response)
        elif response.get("action") == "select_observed_identifiers":
            response = self._bind_source_identifier_selection(response, messages)
            self._apply_source_identifier_selection_to_frozen_plan(
                response,
                messages,
            )
        elif (
            self._emit_stable_family_selection
            and response.get("action") == "use_tool"
            and response.get("tool") == "search_dotnet_metadata"
            and "family_id" not in response
        ):
            response = self._stable_family_selection(response)
        return json.dumps(response)

    @staticmethod
    def _bind_source_identifier_selection(
        response: dict[str, object],
        messages: tuple[dict[str, object], ...],
    ) -> dict[str, object]:
        observation = messages[-1].get("content") if messages else None
        inventory = (
            observation.get("observed_identifier_inventory", [])
            if isinstance(observation, dict)
            else []
        )
        selection_ids = response.get("selection_ids")
        if not isinstance(selection_ids, list):
            return response
        for index, selection_id in enumerate(selection_ids):
            if (
                not isinstance(selection_id, str)
                or not selection_id.startswith(
                    "$source_selection_for_identifier:"
                )
            ):
                continue
            identifier = selection_id.split(":", 1)[1]
            match = next(
                (
                    item.get("selection_id")
                    for item in inventory
                    if isinstance(item, dict)
                    and item.get("observed_identifier") == identifier
                ),
                None,
            )
            if isinstance(match, str):
                selection_ids[index] = match
        return response

    def _apply_source_identifier_selection_to_frozen_plan(
        self,
        response: dict[str, object],
        messages: tuple[dict[str, object], ...],
    ) -> None:
        plan = self._frozen_plan
        search_plan = plan.get("search_plan") if isinstance(plan, dict) else None
        families = search_plan.get("query_families") if isinstance(search_plan, dict) else None
        if not isinstance(families, list):
            return
        observation = messages[-1].get("content") if messages else None
        inventory = (
            observation.get("observed_identifier_inventory", [])
            if isinstance(observation, dict)
            else []
        )
        selection_ids = response.get("selection_ids")
        if not isinstance(selection_ids, list):
            return
        identifiers = [
            str(item["observed_identifier"])
            for selection_id in selection_ids
            for item in inventory
            if isinstance(item, dict)
            and item.get("selection_id") == selection_id
        ]
        search_plan = plan.get("search_plan") if isinstance(plan, dict) else None
        focus = (
            search_plan.get("initial_focus_question_id")
            if isinstance(search_plan, dict)
            else None
        )
        for family in families:
            if (
                isinstance(family, dict)
                and family.get("tool") == "search_dotnet_metadata"
                and focus in family.get("question_ids", [])
            ):
                family["queries"] = identifiers
                return

    def _stable_family_selection(
        self,
        response: dict[str, object],
    ) -> dict[str, object]:
        plan = self._frozen_plan
        search_plan = plan.get("search_plan") if isinstance(plan, dict) else None
        families = search_plan.get("query_families") if isinstance(search_plan, dict) else None
        arguments = response.get("arguments")
        if not isinstance(families, list) or not isinstance(arguments, dict):
            return response
        matches = [
            family
            for family in families
            if isinstance(family, dict)
            and family.get("tool") == response.get("tool")
            and response.get("source_id") in family.get("source_ids", [])
            and family.get("queries") == arguments.get("queries")
            and family.get("evidence_need") == response.get("evidence_need")
        ]
        if len(matches) != 1:
            return response
        return {
            "action": "use_tool",
            "tool": "search_dotnet_metadata",
            "source_id": response["source_id"],
            "family_id": matches[0]["family_id"],
            "derived_from_observation_ids": list(
                response.get("derived_from_observation_ids", [])
            ),
        }


class _ObservedToolExecutor:
    def __init__(self, *, symbol: str = "Observed.Type.Move") -> None:
        self.actions: list[dict[str, object]] = []
        self.symbol = symbol

    def execute(
        self,
        *,
        action: dict[str, object],
        source: EvidenceDiscoverySource,
        observation_id: str,
    ) -> ToolObservation:
        self.actions.append(action)
        if action["tool"] == "search_dotnet_metadata":
            candidate_ref = f"candidate_{observation_id.replace('-', '_')}"
            return ToolObservation(
                observation_id=observation_id,
                tool="search_dotnet_metadata",
                source_id=source.source_id,
                summary="One exact method was observed.",
                data={
                    "methods": [
                        {
                            "candidate_ref": candidate_ref,
                            "method_id": "method_obs_001",
                            "assembly_id": "assembly_obs_001",
                            "relative_path": "Modules-ASM.dll",
                            "assembly_sha256": "A" * 64,
                            "module_mvid": "00000000-0000-0000-0000-000000000001",
                            "symbol": self.symbol,
                            "metadata_token": "0x06000001",
                        }
                    ]
                },
                evidence_items=(),
            )
        assert action["tool"] == "inspect_method_il"
        arguments = action.get("arguments")
        assert isinstance(arguments, dict)
        return ToolObservation(
            observation_id=observation_id,
            tool="inspect_method_il",
            source_id=source.source_id,
            summary="Exact IL was read without target execution.",
            data={
                "candidate_ref": str(arguments["candidate_ref"]),
                "method_id": "method_obs_001",
                "symbol": self.symbol,
                "metadata_token": "0x06000001",
                "has_method_body": True,
                "rva": 123,
                "instruction_count": 1,
                "instructions_truncated": False,
                "resolved_refs": [],
                "target_code_executed": False,
            },
            evidence_items=(
                EvidenceItem(
                    evidence_id="observed_il_001",
                    source_type="decompiled_api",
                    source_path="Modules-ASM.dll",
                    symbol=self.symbol,
                    span=None,
                    retrieval_method="agent_selected_il_read",
                    score=1.0,
                    claim_supported="The exact observed method has a CLI method body.",
                    excerpt="ret",
                    source_ref="source://current-interop/Modules-ASM.dll",
                    source_hash="A" * 64,
                    file_hash="A" * 64,
                    usage="hook_target",
                    authority="mod_agent_deterministic",
                    source_authority=source.source_authority,
                    declaring_type=self.symbol.rsplit(".", 1)[0],
                    method_name=self.symbol.rsplit(".", 1)[1],
                    module_mvid="00000000-0000-0000-0000-000000000001",
                    metadata_token="0x06000001",
                    signature_blob="200001",
                ),
            ),
        )


class _SourceGroundedObservedToolExecutor(_ObservedToolExecutor):
    def execute(
        self,
        *,
        action: dict[str, object],
        source: EvidenceDiscoverySource,
        observation_id: str,
    ) -> ToolObservation:
        observation = super().execute(
            action=action,
            source=source,
            observation_id=observation_id,
        )
        if action.get("tool") != "search_dotnet_metadata":
            return observation
        arguments = action.get("arguments")
        assert isinstance(arguments, dict)
        data = dict(observation.data)
        data["methods"] = [
            {
                **dict(item),
                "matched_queries": list(arguments.get("queries", [])),
            }
            for item in observation.data.get("methods", [])
            if isinstance(item, dict)
        ]
        return replace(observation, data=data)


class _QueryAwareObservedToolExecutor(_ObservedToolExecutor):
    def execute(
        self,
        *,
        action: dict[str, object],
        source: EvidenceDiscoverySource,
        observation_id: str,
    ) -> ToolObservation:
        arguments = action.get("arguments")
        if (
            action.get("tool") == "search_dotnet_metadata"
            and isinstance(arguments, dict)
            and arguments.get("queries") == ["enemy wall movement behavior"]
        ):
            self.actions.append(action)
            return ToolObservation(
                observation_id=observation_id,
                tool="search_dotnet_metadata",
                source_id=source.source_id,
                summary="No managed symbol contained the supplied literal substring.",
                data={"methods": [], "types": [], "fields": []},
                evidence_items=(),
            )
        return super().execute(
            action=action,
            source=source,
            observation_id=observation_id,
        )


def _request(
    tmp_path: Path,
    *,
    include_second_source: bool = True,
) -> EvidenceDiscoveryRequest:
    second_root = tmp_path / "r8-snapshot"
    second_root.mkdir(exist_ok=True)
    sources = [
        EvidenceDiscoverySource(
            source_id="current-interop",
            source_type="decompiled_api",
            kind="il2cpp_interop_directory",
            evidence_class="current_installed_generated_interop",
            source_authority="authoritative",
            description="Current installed generated interop assemblies.",
            root_path=tmp_path,
            allowed_tools=("search_dotnet_metadata", "inspect_method_il"),
        )
    ]
    if include_second_source:
        sources.append(
            EvidenceDiscoverySource(
                source_id="r8-snapshot",
                source_type="decompiled_api",
                kind="unity_script_assembly",
                evidence_class="supplied_r8_unity_export",
                source_authority="supporting",
                description="User-supplied R8 Unity assembly snapshot.",
                root_path=second_root,
                allowed_tools=("search_dotnet_metadata", "inspect_method_il"),
            )
        )
    return EvidenceDiscoveryRequest(
        run_id="run-wallcrawler-intelligent-evidence-test",
        request_id="wallcrawler-intelligent-evidence-test",
        natural_language_request=(
            "调查敌人在墙面、斜面和天花板上的移动与朝向实现证据。"
        ),
        sources=tuple(sources),
        max_tool_calls=3,
        max_model_steps=4,
        max_result_bytes_per_call=65536,
        max_total_observation_bytes=131072,
    )


def _metadata_then_il_responses(
    *finishes: dict[str, object],
) -> list[dict[str, object]]:
    return [
        {
            "action": "use_tool",
            "tool": "search_dotnet_metadata",
            "source_id": "current-interop",
            "arguments": _metadata_arguments("movement"),
            "evidence_need": "Find one exact movement method.",
            "derived_from_observation_ids": [],
        },
        {
            "action": "use_tool",
            "tool": "inspect_method_il",
            "source_id": "current-interop",
            "arguments": {"candidate_ref": "candidate_obs_001"},
            "evidence_need": "Inspect the observed method body.",
            "derived_from_observation_ids": ["obs-001"],
        },
        *finishes,
    ]


def _actual_plan(
    *,
    behavior_goal: str,
    queries: list[str],
    evidence_need: str,
    hard_constraints: list[str] | None = None,
    implementation_hints: list[str] | None = None,
) -> dict[str, object]:
    return {
        "action": "plan",
        "planning_status": "ready",
        "requirement_projection": {
            "schema_version": "hook_requirement_projection_v2",
            "behavior_goal": behavior_goal,
            "trigger": None,
            "actor": None,
            "target": None,
            "hard_constraints": list(hard_constraints or []),
            "forbidden_outcomes": [],
            "implementation_hints": [
                {"text": text, "role": "investigation_lead"}
                for text in (implementation_hints or [])
            ],
            "acceptance_signals": [],
            "planning_blocking_questions": [
                {"requirement_id": "req-primary", "question": evidence_need}
            ],
            "deferred_planning_or_runtime_questions": [],
        },
        "search_plan": {
            "schema_version": SEARCH_PLAN_SCHEMA_VERSION,
            "initial_focus_question_id": "question-primary",
            "engineering_questions": [
                {
                    "question_id": "question-primary",
                    "question": evidence_need,
                    "requirement_ids": ["req-primary"],
                }
            ],
            "source_roles": [
                {"source_id": "current-interop", "role": "current_api_and_il"}
            ],
            "planned_lanes": [
                {
                    "lane": "managed_metadata_discovery",
                    "tool": "search_dotnet_metadata",
                    "source_ids": ["current-interop"],
                    "question_ids": ["question-primary"],
                },
                {
                    "lane": "exact_il_verification",
                    "tool": "inspect_method_il",
                    "source_ids": ["current-interop"],
                    "question_ids": ["question-primary"],
                },
            ],
            "query_families": [
                {
                    "family_id": "request-derived-behavior",
                    "queries": queries,
                    "evidence_need": evidence_need,
                    "source_ids": ["current-interop"],
                    "tool": "search_dotnet_metadata",
                    "question_ids": ["question-primary"],
                }
            ],
            "initial_stop_condition": "Stop after exact IL verification closes the first question.",
            "initial_expand_condition": "Expand once only when a recorded planning question remains open.",
        },
    }


def _add_secondary_planning_question(
    plan: dict[str, object],
    *,
    deferred: bool = False,
) -> None:
    projection = plan["requirement_projection"]
    search_plan = plan["search_plan"]
    assert isinstance(projection, dict)
    assert isinstance(search_plan, dict)
    if deferred:
        projection["deferred_planning_or_runtime_questions"].append(
            "Verify the downstream effect during Runtime evaluation."
        )
        return
    projection["planning_blocking_questions"].append(
        {
            "requirement_id": "req-secondary",
            "question": "Which current method exposes the downstream integration boundary?",
        }
    )
    search_plan["engineering_questions"].append(
        {
            "question_id": "question-secondary",
            "question": "Which current method exposes the downstream integration boundary?",
            "requirement_ids": ["req-secondary"],
        }
    )
    search_plan["planned_lanes"].append(
        {
            "lane": "secondary_metadata_discovery",
            "tool": "search_dotnet_metadata",
            "source_ids": ["current-interop"],
            "question_ids": ["question-secondary"],
        }
    )
    search_plan["query_families"].append(
        {
            "family_id": "secondary-integration",
            "queries": ["integration"],
            "evidence_need": (
                "Which current method exposes the downstream integration boundary?"
            ),
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-secondary"],
        }
    )


def _finish_after_observed_il(
    *, symbol: str = "Observed.Type.Move",
) -> dict[str, object]:
    return {
        "action": "finish",
        "decision": "needs_more_evidence",
        "evidence_conclusions": [
            {
                "claim": f"Observed inspected symbol: {symbol}.",
                "claim_status": "observed",
                "observation_ids": ["obs-002"],
                "limitations": [],
                "requirement_ids": ["req-primary"],
                "relationship": "support",
            }
        ],
        "unresolved_questions": ["Runtime behavior remains unresolved."],
        "missing_capabilities": [],
    }


def _validated_actual_from_plan(plan: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": AGENT_DISCOVERY_ACTUAL_SCHEMA_VERSION,
        "planning_status": plan["planning_status"],
        "requirement_projection": plan["requirement_projection"],
        "search_plan": plan["search_plan"],
    }


def _strict_semantic_payload(
    tmp_path: Path,
    *,
    decision: str,
) -> dict[str, object]:
    evidence_need = "Which current method exposes movement?"
    plan = _actual_plan(
        behavior_goal="Find a current movement observation point.",
        queries=["movement"],
        evidence_need=evidence_need,
    )
    finish = _finish_after_observed_il()
    finish["decision"] = decision
    if decision == "sufficient_for_proposal":
        finish["unresolved_questions"] = []
    if decision == "conflicting_evidence":
        finish["unresolved_questions"] = []
        finish["evidence_conclusions"][0]["relationship"] = "conflict"
    result = EvidenceDiscoverySpecialist(
        model=_ScriptedModel(
            [
                plan,
                {
                    "action": "use_tool",
                    "tool": "search_dotnet_metadata",
                    "source_id": "current-interop",
                    "arguments": _metadata_arguments("movement"),
                    "evidence_need": evidence_need,
                    "derived_from_observation_ids": [],
                },
                {
                    "action": "use_tool",
                    "tool": "inspect_method_il",
                    "source_id": "current-interop",
                    "arguments": {"candidate_ref": "candidate_obs_001"},
                    "evidence_need": "Verify the observed method.",
                    "derived_from_observation_ids": ["obs-001"],
                },
                finish,
            ]
        ),
        tool_executor=_ObservedToolExecutor(),
    ).discover(replace(_request(tmp_path), require_actual_planning=True))
    return result.pack.to_artifact_payload()


def _strict_roundtrip_feature_payload(feature_id: str) -> dict[str, object]:
    return {
        "node_name": "draft_feature_spec",
        "stage": "feature_spec",
        "message": "Strict semantic EvidencePack roundtrip fixture.",
        "feature_id": feature_id,
        "user_request": "Find a current movement observation point.",
        "target_behavior": "Find a current movement observation point.",
        "non_goals": [],
        "target_mod": None,
        "risk_level": "medium",
        "acceptance_criteria": [],
        "evidence_requirements": [],
        "runtime_verification_plan": [],
        "blocked": False,
        "blockers": [],
    }


@pytest.mark.parametrize(
    ("decision", "readiness", "can_generate_patch"),
    [
        ("sufficient_for_proposal", "sufficient", True),
        ("needs_more_evidence", "insufficient", False),
        ("conflicting_evidence", "contradictory", False),
    ],
)
def test_phase_2c_semantic_evidence_pack_committed_strict_roundtrip(
    tmp_path: Path,
    decision: str,
    readiness: str,
    can_generate_patch: bool,
) -> None:
    payload = _strict_semantic_payload(tmp_path, decision=decision)
    assert payload["readiness"] == readiness
    assert payload["can_generate_patch"] is can_generate_patch
    canonical_before = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")

    ArtifactTypeRegistry().validate_write(
        artifact_type="evidence_pack",
        status="success",
        payload=payload,
    )
    store = ArtifactStore(tmp_path / f"artifacts-{decision}")
    feature_id = f"feature-{decision}"
    feature_ref = store.write(
        feature_id=feature_id,
        artifact_type="feature_spec",
        payload=_strict_roundtrip_feature_payload(feature_id),
    )
    ref = store.write(
        feature_id=feature_id,
        artifact_type="evidence_pack",
        payload=payload,
        upstream_refs=[feature_ref],
    )
    committed = store.read(ref)["data"]
    rehydrated = EvidencePack.from_artifact_payload(committed)
    canonical_after = json.dumps(
        rehydrated.to_artifact_payload(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    assert canonical_after == canonical_before
    assert rehydrated.hook_discovery == payload["hook_discovery"]
    assert rehydrated.agent_discovery == payload["agent_discovery"]
    assert rehydrated.readiness == readiness
    assert rehydrated.can_generate_patch is can_generate_patch
    first_attempt = rehydrated.model_action_trace[0]
    assert first_attempt["action"] == _family_selection(
        "request-derived-behavior"
    )
    assert first_attempt["resolved_action"] == {
        "action": "use_tool",
        "tool": "search_dotnet_metadata",
        "source_id": "current-interop",
        "arguments": _metadata_arguments("movement", limit_per_kind=10),
        "evidence_need": "Which current method exposes movement?",
        "derived_from_observation_ids": [],
        "query_family_id": "request-derived-behavior",
    }


def test_v2_agent_search_plan_strict_roundtrip_preserves_bytes_and_hash(
    tmp_path: Path,
) -> None:
    payload = _strict_semantic_payload(tmp_path, decision="needs_more_evidence")
    agent_discovery = payload["agent_discovery"]
    assert isinstance(agent_discovery, dict)
    search_plan = agent_discovery["search_plan"]
    assert isinstance(search_plan, dict)
    search_plan["schema_version"] = "hook_discovery_search_plan_v2"
    search_plan.pop("initial_focus_question_id")
    for lane in search_plan["planned_lanes"]:
        lane.pop("question_ids")
    payload["prompt_contract"]["version"] = "agent_evidence_discovery_prompt_v2"
    payload["prompt_contract"]["context_strategy"] = (
        "deduplicated_catalog_latest_observation_zero_result_recovery_"
        "repeat_correction_and_supported_facts_v6"
    )
    payload["prompt_contract"]["system_contract_sha256"] = (
        "da325eabf3c50521e9f3e8265e9f3ae924b7ab7edb36852c39ccc53dad30bd5d"
    )
    payload["budget_summary"]["discovery_message_bytes_by_turn"] = [
        6546,
        7573,
        8139,
    ]
    payload["budget_summary"]["total_discovery_message_bytes"] = 22_258
    payload["budget_summary"]["total_observation_bytes_used"] = 1_186
    payload["observation_trace"][1]["model_payload_bytes"] = 708
    payload["prompt_contract"]["agent_discovery_sha256"] = hashlib.sha256(
        json.dumps(
            agent_discovery,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    canonical_before = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    hash_before = hashlib.sha256(canonical_before).hexdigest()
    assert len(canonical_before) == 12_138
    assert hash_before == (
        "c24a82a9b51951df0dfa6e34c7ff13d6907bcb9c9666e6e190c8c6e3b9fedd91"
    )

    ArtifactTypeRegistry().validate_write(
        artifact_type="evidence_pack", status="success", payload=payload
    )
    rehydrated = EvidencePack.from_artifact_payload(payload).to_artifact_payload()
    canonical_after = json.dumps(
        rehydrated, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")

    assert canonical_after == canonical_before
    assert hashlib.sha256(canonical_after).hexdigest() == hash_before
    assert rehydrated["agent_discovery"]["search_plan"]["schema_version"] == (
        "hook_discovery_search_plan_v2"
    )
    assert all(
        "question_ids" not in lane
        for lane in rehydrated["agent_discovery"]["search_plan"]["planned_lanes"]
    )


def test_v3_agent_search_plan_strict_roundtrip_preserves_bytes_and_hash(
    tmp_path: Path,
) -> None:
    payload = _strict_semantic_payload(tmp_path, decision="needs_more_evidence")
    agent_discovery = payload["agent_discovery"]
    assert isinstance(agent_discovery, dict)
    search_plan = agent_discovery["search_plan"]
    assert isinstance(search_plan, dict)
    search_plan["schema_version"] = "hook_discovery_search_plan_v3"
    search_plan.pop("initial_focus_question_id")
    payload["prompt_contract"]["version"] = "agent_evidence_discovery_prompt_v4"
    payload["prompt_contract"]["context_strategy"] = (
        "deduplicated_catalog_latest_observation_zero_result_recovery_"
        "repeat_correction_and_supported_facts_v6"
    )
    payload["prompt_contract"]["system_contract_sha256"] = (
        "da325eabf3c50521e9f3e8265e9f3ae924b7ab7edb36852c39ccc53dad30bd5d"
    )
    payload["budget_summary"]["discovery_message_bytes_by_turn"] = [
        6898,
        7925,
        8491,
    ]
    payload["budget_summary"]["total_discovery_message_bytes"] = 23_314
    payload["budget_summary"]["total_observation_bytes_used"] = 1_186
    payload["observation_trace"][1]["model_payload_bytes"] = 708
    payload["prompt_contract"]["agent_discovery_sha256"] = hashlib.sha256(
        json.dumps(
            agent_discovery,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    canonical_before = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    hash_before = hashlib.sha256(canonical_before).hexdigest()
    assert len(canonical_before) == 12_210
    assert hash_before == (
        "b9c7b39265eddf16f0fa97a0ba78237941e4d3db63ac7cf3e62fd7dfdca70614"
    )

    ArtifactTypeRegistry().validate_write(
        artifact_type="evidence_pack", status="success", payload=payload
    )
    rehydrated = EvidencePack.from_artifact_payload(payload).to_artifact_payload()
    canonical_after = json.dumps(
        rehydrated, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")

    assert canonical_after == canonical_before
    assert hashlib.sha256(canonical_after).hexdigest() == hash_before
    assert rehydrated["agent_discovery"]["search_plan"]["schema_version"] == (
        "hook_discovery_search_plan_v3"
    )


def test_strict_reader_rejects_first_trace_outside_tampered_initial_focus(
    tmp_path: Path,
) -> None:
    payload = _strict_semantic_payload(tmp_path, decision="needs_more_evidence")
    agent_discovery = payload["agent_discovery"]
    search_plan = agent_discovery["search_plan"]
    search_plan["engineering_questions"].append(
        {
            "question_id": "question-secondary",
            "question": "Which current method exposes a secondary boundary?",
            "requirement_ids": ["req-primary"],
        }
    )
    for lane in search_plan["planned_lanes"]:
        lane["question_ids"].append("question-secondary")
    search_plan["query_families"].append(
        {
            "family_id": "secondary-boundary",
            "queries": ["secondary"],
            "evidence_need": "Which current method exposes a secondary boundary?",
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-secondary"],
        }
    )
    search_plan["initial_focus_question_id"] = "question-secondary"
    payload["prompt_contract"]["agent_discovery_sha256"] = hashlib.sha256(
        json.dumps(
            agent_discovery,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    with pytest.raises(
        ArtifactRegistryError,
        match="Invalid semantic EvidencePack",
    ):
        ArtifactTypeRegistry().validate_write(
            artifact_type="evidence_pack",
            status="success",
            payload=payload,
        )


def test_strict_reader_rejects_tampered_first_il_action_for_current_focus(
    tmp_path: Path,
) -> None:
    payload = _strict_semantic_payload(tmp_path, decision="needs_more_evidence")
    inspect_attempt = next(
        deepcopy(attempt)
        for attempt in payload["model_action_trace"]
        if attempt["action"].get("tool") == "inspect_method_il"
    )
    payload["model_action_trace"][0] = inspect_attempt
    payload["observation_trace"][0]["tool"] = "inspect_method_il"
    payload["tool_trace_summary"][0]["tool"] = "inspect_method_il"

    with pytest.raises(
        ArtifactRegistryError,
        match="Invalid semantic EvidencePack",
    ):
        ArtifactTypeRegistry().validate_write(
            artifact_type="evidence_pack",
            status="success",
            payload=payload,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "hook_version",
        "hook_extra_field",
        "evidence_ref",
        "observation_ref",
        "query_family_ref",
        "engineering_question_ref",
        "action_ref",
        "resolved_action_hash",
        "resolved_action_binding",
        "resolved_action_family_ref",
        "resolved_action_tuning",
        "resolved_action_extra_field",
        "raw_family_action_extra_field",
        "raw_family_id_removed",
        "planning_action",
        "top_readiness",
        "top_can_generate_patch",
        "top_authoritative_for_patch",
        "agent_version",
        "agent_hash",
        "remove_agent_keep_hash",
        "remove_agent_clear_hash",
        "top_extra_field",
        "agent_without_hook",
        "semantic_sections_removed",
    ],
)
def test_phase_2c_semantic_evidence_pack_tampering_fails_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    payload = deepcopy(
        _strict_semantic_payload(tmp_path, decision="sufficient_for_proposal")
    )
    if mutation == "hook_version":
        payload["hook_discovery"]["schema_version"] = "hook_discovery_evidence_v1"
    elif mutation == "hook_extra_field":
        payload["hook_discovery"]["unexpected"] = True
    elif mutation == "evidence_ref":
        payload["hook_discovery"]["evidence_relationships"][0][
            "evidence_ids"
        ] = ["missing-evidence"]
    elif mutation == "observation_ref":
        payload["hook_discovery"]["evidence_relationships"][0][
            "observation_ids"
        ] = ["missing-observation"]
    elif mutation == "query_family_ref":
        payload["hook_discovery"]["evidence_relationships"][0][
            "query_family_ids"
        ] = ["missing-family"]
    elif mutation == "engineering_question_ref":
        payload["hook_discovery"]["evidence_relationships"][0][
            "engineering_question_ids"
        ] = ["missing-question"]
    elif mutation == "action_ref":
        payload["hook_discovery"]["evidence_relationships"][0][
            "action_indexes"
        ] = [99]
    elif mutation in {"raw_family_action_extra_field", "raw_family_id_removed"}:
        action = payload["model_action_trace"][0]["action"]
        if mutation == "raw_family_action_extra_field":
            action["unexpected"] = True
        else:
            action.pop("family_id")
        payload["model_action_trace"][0]["action_sha256"] = hashlib.sha256(
            json.dumps(
                action,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    elif mutation in {
        "resolved_action_hash",
        "resolved_action_binding",
        "resolved_action_family_ref",
        "resolved_action_tuning",
        "resolved_action_extra_field",
    }:
        resolved = payload["model_action_trace"][0]["resolved_action"]
        if mutation == "resolved_action_family_ref":
            resolved.pop("query_family_id")
        elif mutation == "resolved_action_tuning":
            resolved["arguments"]["limit_per_kind"] = 49
        elif mutation == "resolved_action_extra_field":
            resolved["unexpected"] = True
        else:
            resolved["arguments"]["queries"] = ["rewritten-query"]
        if mutation != "resolved_action_hash":
            payload["model_action_trace"][0]["resolved_action_sha256"] = (
                hashlib.sha256(
                    json.dumps(
                        resolved,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
            )
    elif mutation == "planning_action":
        payload["hook_discovery"]["planning_action"] = "block"
    elif mutation == "top_readiness":
        payload["readiness"] = "insufficient"
    elif mutation == "top_can_generate_patch":
        payload["can_generate_patch"] = False
        payload["authoritative_for_patch"] = False
    elif mutation == "top_authoritative_for_patch":
        payload["authoritative_for_patch"] = False
    elif mutation == "agent_version":
        payload["agent_discovery"]["schema_version"] = "agent_evidence_discovery_actual_v1"
    elif mutation == "agent_hash":
        payload["prompt_contract"]["agent_discovery_sha256"] = "0" * 64
    elif mutation == "remove_agent_keep_hash":
        payload.pop("agent_discovery")
    elif mutation == "remove_agent_clear_hash":
        payload.pop("agent_discovery")
        payload["prompt_contract"]["agent_discovery_sha256"] = None
    elif mutation == "top_extra_field":
        payload["unexpected"] = True
    elif mutation == "agent_without_hook":
        payload.pop("hook_discovery")
    elif mutation == "semantic_sections_removed":
        payload.pop("hook_discovery")
        payload.pop("agent_discovery")
    else:  # pragma: no cover - parametrization is closed above
        raise AssertionError(mutation)

    with pytest.raises(ArtifactRegistryError, match="Invalid semantic EvidencePack"):
        ArtifactTypeRegistry().validate_write(
            artifact_type="evidence_pack",
            status="success",
            payload=payload,
        )


def test_phase_2_search_plan_rejects_duplicate_query_family_id() -> None:
    plan = _actual_plan(
        behavior_goal="Find a current movement method.",
        queries=["movement"],
        evidence_need="Which current method exposes movement?",
    )
    search_plan = plan["search_plan"]
    assert isinstance(search_plan, dict)
    search_plan["query_families"].append({
        "family_id": "request-derived-behavior",
        "queries": ["locomotion"],
        "evidence_need": "Which current method exposes movement?",
        "source_ids": ["current-interop"],
        "tool": "search_dotnet_metadata",
        "question_ids": ["question-primary"],
    })

    with pytest.raises(ValueError, match="SEARCH_PLAN_QUERY_FAMILY_ID_DUPLICATE"):
        validate_agent_discovery_actual(_validated_actual_from_plan(plan))


def test_phase_2_search_plan_rejects_ambiguous_query_family_dispatch() -> None:
    plan = _actual_plan(
        behavior_goal="Find a current movement method.",
        queries=["movement"],
        evidence_need="Which current method exposes movement?",
    )
    projection = plan["requirement_projection"]
    search_plan = plan["search_plan"]
    assert isinstance(projection, dict) and isinstance(search_plan, dict)
    search_plan["planned_lanes"][0]["source_ids"] = [
        "current-interop",
        "r8-snapshot",
    ]
    search_plan["query_families"][0]["source_ids"] = [
        "current-interop",
        "r8-snapshot",
    ]
    projection["planning_blocking_questions"].append({
        "requirement_id": "req-secondary",
        "question": "Which current method preserves movement state?",
    })
    search_plan["engineering_questions"].append({
        "question_id": "question-secondary",
        "question": "Which current method preserves movement state?",
        "requirement_ids": ["req-secondary"],
    })
    search_plan["query_families"].append({
        "family_id": "ambiguous-secondary-family",
        "queries": ["movement"],
        "evidence_need": "Which current method exposes movement?",
        "source_ids": ["current-interop"],
        "tool": "search_dotnet_metadata",
        "question_ids": ["question-secondary"],
    })

    with pytest.raises(
        ValueError,
        match="SEARCH_PLAN_QUERY_FAMILY_DISPATCH_AMBIGUOUS",
    ):
        validate_agent_discovery_actual(_validated_actual_from_plan(plan))


def test_search_plan_initial_focus_must_reference_declared_engineering_question() -> None:
    plan = _actual_plan(
        behavior_goal="Find a current movement method.",
        queries=["movement"],
        evidence_need="Which current method exposes movement?",
    )
    plan["search_plan"]["initial_focus_question_id"] = "question-unknown"

    with pytest.raises(
        ValueError,
        match="SEARCH_PLAN_INITIAL_FOCUS_QUESTION_UNKNOWN",
    ):
        validate_agent_discovery_actual(_validated_actual_from_plan(plan))


def test_search_plan_preserves_other_blockers_and_rejects_deferred_focus() -> None:
    plan = _actual_plan(
        behavior_goal="Observe an event before a downstream effect.",
        queries=["event"],
        evidence_need="Which current method exposes the event?",
    )
    _add_secondary_planning_question(plan)
    _add_secondary_planning_question(plan, deferred=True)
    validate_agent_discovery_actual(_validated_actual_from_plan(plan))
    projection = plan["requirement_projection"]
    assert len(projection["planning_blocking_questions"]) == 2
    assert len(projection["deferred_planning_or_runtime_questions"]) == 1

    plan["search_plan"]["initial_focus_question_id"] = (
        "Verify the downstream effect during Runtime evaluation."
    )
    with pytest.raises(
        ValueError,
        match="SEARCH_PLAN_INITIAL_FOCUS_QUESTION_UNKNOWN",
    ):
        validate_agent_discovery_actual(_validated_actual_from_plan(plan))


def test_first_metadata_action_must_bind_frozen_initial_focus(
    tmp_path: Path,
) -> None:
    plan = _actual_plan(
        behavior_goal="Observe an event before a downstream effect.",
        queries=["event"],
        evidence_need="Which current method exposes the event?",
    )
    _add_secondary_planning_question(plan)
    plan["search_plan"]["initial_focus_question_id"] = "question-secondary"
    model = _ScriptedModel(
        [
            plan,
            _family_selection("request-derived-behavior"),
            _family_selection("secondary-integration"),
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Verify the method observed for the initial focus.",
                "derived_from_observation_ids": ["obs-001"],
            },
            _finish_after_observed_il(),
        ]
    )
    executor = _ObservedToolExecutor()

    with pytest.raises(
        ValueError,
        match="FIRST_DISCOVERY_ACTION_NOT_INITIAL_FOCUS",
    ):
        EvidenceDiscoverySpecialist(
            model=model,
            tool_executor=executor,
        ).discover(replace(_request(tmp_path), require_actual_planning=True))

    assert executor.actions == []


def test_multi_question_plan_executes_focus_and_preserves_other_blocker(
    tmp_path: Path,
) -> None:
    plan = _actual_plan(
        behavior_goal="Observe an event before a downstream effect.",
        queries=["event"],
        evidence_need="Which current method exposes the event?",
    )
    _add_secondary_planning_question(plan)
    model = _ScriptedModel(
        [
            plan,
            _family_selection("request-derived-behavior"),
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Verify the observed initial-focus method.",
                "derived_from_observation_ids": ["obs-001"],
            },
            _finish_after_observed_il(),
        ]
    )
    executor = _ObservedToolExecutor()

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=executor,
    ).discover(replace(_request(tmp_path), require_actual_planning=True))

    assert result.agent_discovery["search_plan"]["initial_focus_question_id"] == (
        "question-primary"
    )
    assert len(
        result.agent_discovery["requirement_projection"][
            "planning_blocking_questions"
        ]
    ) == 2
    assert executor.actions[0]["query_family_id"] == "request-derived-behavior"
    assert executor.actions[0]["tool"] == "search_dotnet_metadata"


def test_phase_2_unrelated_hook_request_freezes_plan_before_tools(
    tmp_path: Path,
) -> None:
    request_text = (
        "When a terminal finishes authentication, briefly pulse nearby corridor lights."
    )
    evidence_need = "Which current managed methods expose terminal completion signals?"
    plan = _actual_plan(
        behavior_goal="Pulse nearby corridor lights after terminal authentication.",
        queries=["terminal authentication complete", "corridor light pulse"],
        evidence_need=evidence_need,
    )
    model = _ScriptedModel(
        [
            plan,
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments(
                    "terminal authentication complete", "corridor light pulse"
                ),
                "evidence_need": evidence_need,
                "derived_from_observation_ids": [],
            },
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Verify the exact identity returned by metadata discovery.",
                "derived_from_observation_ids": ["obs-001"],
            },
            _finish_after_observed_il(),
        ]
    )
    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(replace(_request(tmp_path), natural_language_request=request_text, require_actual_planning=True))

    assert len(model.calls) == 4
    first_call = json.dumps(model.calls[0], ensure_ascii=False)
    assert request_text in first_call
    assert "terminal authentication complete" not in first_call
    assert "Observed.Type.Move" not in first_call
    assert "hook-discovery-playbook" not in first_call
    assert result.agent_discovery == result.pack.agent_discovery
    assert result.agent_discovery == {
        "schema_version": "agent_evidence_discovery_actual_v2",
        "planning_status": "ready",
        "requirement_projection": plan["requirement_projection"],
        "search_plan": plan["search_plan"],
    }
    assert [item["tool"] for item in result.actions] == [
        "search_dotnet_metadata",
        "inspect_method_il",
    ]
    payload = result.pack.to_artifact_payload()
    assert payload["agent_discovery"] == result.agent_discovery
    assert EvidencePack.from_artifact_payload(payload).to_artifact_payload() == payload
    assert result.pack.hook_discovery is not None
    assert result.pack.hook_discovery["lane_coverage"] == [
        {
            "lane": "managed_metadata_discovery",
            "status": "searched_with_results",
            "hit_count": 1,
            "scope": {
                "tool": "search_dotnet_metadata",
                "source_ids": ["current-interop"],
                "action_count": 1,
            },
            "failure": None,
        },
        {
            "lane": "exact_il_verification",
            "status": "searched_with_results",
            "hit_count": 1,
            "scope": {
                "tool": "inspect_method_il",
                "source_ids": ["current-interop"],
                "action_count": 1,
            },
            "failure": None,
        },
    ]


def test_actual_metadata_family_selection_resolves_only_frozen_content(
    tmp_path: Path,
) -> None:
    evidence_need = "Which current method exposes movement?"
    plan = _actual_plan(
        behavior_goal="Find a current movement observation point.",
        queries=["movement"],
        evidence_need=evidence_need,
    )
    model = _ScriptedModel(
        [
            plan,
            _family_selection("request-derived-behavior"),
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Verify the observed method.",
                "derived_from_observation_ids": ["obs-001"],
            },
            _finish_after_observed_il(),
        ]
    )
    executor = _ObservedToolExecutor()

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=executor,
    ).discover(replace(_request(tmp_path), require_actual_planning=True))

    assert executor.actions[0] == {
        "action": "use_tool",
        "tool": "search_dotnet_metadata",
        "source_id": "current-interop",
        "arguments": _metadata_arguments("movement", limit_per_kind=10),
        "evidence_need": evidence_need,
        "derived_from_observation_ids": [],
        "query_family_id": "request-derived-behavior",
    }
    assert result.pack.model_action_trace[0]["action"] == _family_selection(
        "request-derived-behavior"
    )
    assert result.pack.model_action_trace[0]["resolved_action"] == executor.actions[0]


def test_lane_coverage_binds_only_executed_family_questions_and_roundtrips(
    tmp_path: Path,
) -> None:
    plan = _actual_plan(
        behavior_goal="Find one current movement observation point.",
        queries=["movement"],
        evidence_need="Which current method exposes movement?",
    )
    projection = plan["requirement_projection"]
    search_plan = plan["search_plan"]
    assert isinstance(projection, dict) and isinstance(search_plan, dict)
    projection["planning_blocking_questions"].append(
        {
            "requirement_id": "req-secondary",
            "question": "Which current method exposes a separate guard?",
        }
    )
    search_plan["engineering_questions"].append(
        {
            "question_id": "question-secondary",
            "question": "Which current method exposes a separate guard?",
            "requirement_ids": ["req-secondary"],
        }
    )
    search_plan["planned_lanes"].append(
        {
            "lane": "secondary_metadata_discovery",
            "tool": "search_dotnet_metadata",
            "source_ids": ["current-interop"],
            "question_ids": ["question-secondary"],
        }
    )
    search_plan["query_families"].append(
        {
            "family_id": "secondary-family",
            "queries": ["guard"],
            "evidence_need": "Which current method exposes a separate guard?",
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-secondary"],
        }
    )
    projection["planning_blocking_questions"].append(
        {
            "requirement_id": "req-tertiary",
            "question": "Which current method exposes a third behavior?",
        }
    )
    search_plan["engineering_questions"].append(
        {
            "question_id": "question-tertiary",
            "question": "Which current method exposes a third behavior?",
            "requirement_ids": ["req-tertiary"],
        }
    )
    search_plan["planned_lanes"].append(
        {
            "lane": "tertiary_metadata_discovery",
            "tool": "search_dotnet_metadata",
            "source_ids": ["current-interop"],
            "question_ids": ["question-tertiary"],
        }
    )
    search_plan["query_families"].append(
        {
            "family_id": "tertiary-family",
            "queries": ["third"],
            "evidence_need": "Which current method exposes a third behavior?",
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-tertiary"],
        }
    )
    result = EvidenceDiscoverySpecialist(
        model=_ScriptedModel(
            [
                plan,
                _family_selection("request-derived-behavior"),
                {
                    "action": "use_tool",
                    "tool": "inspect_method_il",
                    "source_id": "current-interop",
                    "arguments": {"candidate_ref": "candidate_obs_001"},
                    "evidence_need": "Verify the observed method.",
                    "derived_from_observation_ids": ["obs-001"],
                },
                _family_selection("secondary-family"),
                _finish_after_observed_il(),
                _finish_after_observed_il(),
            ]
        ),
        tool_executor=_ObservedToolExecutor(),
    ).discover(
        replace(
            _request(tmp_path),
            require_actual_planning=True,
            max_tool_calls=4,
            max_model_steps=5,
        )
    )

    coverage = result.pack.hook_discovery["lane_coverage"]
    assert [
        (
            row["lane"],
            row["status"],
            row["scope"]["source_ids"],
            row["scope"]["action_count"],
        )
        for row in coverage
    ] == [
        ("managed_metadata_discovery", "searched_with_results", ["current-interop"], 1),
        ("exact_il_verification", "searched_with_results", ["current-interop"], 1),
        ("secondary_metadata_discovery", "searched_with_results", ["current-interop"], 1),
        ("tertiary_metadata_discovery", "not_searched", [], 0),
    ]
    payload = result.pack.to_artifact_payload()
    ArtifactTypeRegistry().validate_write(
        artifact_type="evidence_pack", status="success", payload=payload
    )
    assert EvidencePack.from_artifact_payload(payload).to_artifact_payload() == payload
    store = ArtifactStore(tmp_path / "lane-coverage-artifacts")
    feature_ref = store.write(
        feature_id="lane-coverage-binding",
        artifact_type="feature_spec",
        payload=_strict_roundtrip_feature_payload("lane-coverage-binding"),
    )
    pack_ref = store.write(
        feature_id="lane-coverage-binding",
        artifact_type="evidence_pack",
        payload=payload,
        upstream_refs=[feature_ref],
    )
    committed = store.read(pack_ref)["data"]
    assert EvidencePack.from_artifact_payload(committed).to_artifact_payload() == payload

    tampered = deepcopy(payload)
    tertiary = tampered["hook_discovery"]["lane_coverage"][3]
    tertiary["status"] = "searched_with_results"
    tertiary["hit_count"] = 1
    tertiary["scope"]["action_count"] = 1
    with pytest.raises(ArtifactRegistryError, match="Invalid semantic EvidencePack"):
        ArtifactTypeRegistry().validate_write(
            artifact_type="evidence_pack", status="success", payload=tampered
        )

    tampered = deepcopy(payload)
    tampered["hook_discovery"]["lane_coverage"][0]["scope"]["source_ids"] = [
        "current-interop",
        "r8-snapshot",
    ]
    with pytest.raises(ArtifactRegistryError, match="Invalid semantic EvidencePack"):
        ArtifactTypeRegistry().validate_write(
            artifact_type="evidence_pack", status="success", payload=tampered
        )


@pytest.mark.parametrize(
    ("raw_action", "error_code"),
    [
        (
            _family_selection("unknown-family"),
            "QUERY_FAMILY_ID_UNKNOWN",
        ),
        (
            _family_selection(
                "request-derived-behavior",
                source_id="r8-snapshot",
            ),
            "QUERY_FAMILY_SOURCE_NOT_ALLOWED",
        ),
        (
            {
                **_family_selection("request-derived-behavior"),
                "arguments": _metadata_arguments("rewritten-query"),
                "evidence_need": "Rewritten evidence need.",
            },
            "QUERY_FAMILY_SELECTION_SHAPE_INVALID",
        ),
    ],
)
def test_actual_metadata_family_selection_rejects_before_dispatch(
    tmp_path: Path,
    raw_action: dict[str, object],
    error_code: str,
) -> None:
    plan = _actual_plan(
        behavior_goal="Find a current movement observation point.",
        queries=["movement"],
        evidence_need="Which current method exposes movement?",
    )
    model = _ScriptedModel(
        [plan, raw_action],
        emit_stable_family_selection=False,
    )
    executor = _ObservedToolExecutor()
    specialist = EvidenceDiscoverySpecialist(model=model, tool_executor=executor)

    with pytest.raises(ValueError, match=error_code):
        specialist.discover(
            replace(_request(tmp_path), require_actual_planning=True)
        )

    assert executor.actions == []
    assert specialist.runtime_diagnostics["failure_stage"] == "action_validation"


def test_phase_2_complete_plan_executes_when_model_labels_it_insufficient(
    tmp_path: Path,
) -> None:
    evidence_need = "Which current method exposes movement?"
    plan = _actual_plan(
        behavior_goal="Find a current movement observation point.",
        queries=["movement"],
        evidence_need=evidence_need,
    )
    plan["planning_status"] = "search_planning_insufficient"
    model = _ScriptedModel(
        [
            plan,
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("movement"),
                "evidence_need": evidence_need,
                "derived_from_observation_ids": [],
            },
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Verify the observed method.",
                "derived_from_observation_ids": ["obs-001"],
            },
            _finish_after_observed_il(),
        ]
    )

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(replace(_request(tmp_path), require_actual_planning=True))

    assert result.agent_discovery is not None
    assert result.agent_discovery["planning_status"] == "ready"
    assert [action["tool"] for action in result.actions] == [
        "search_dotnet_metadata",
        "inspect_method_il",
    ]
    assert result.pack.hook_discovery["evidence_relationships"][0] == {
        "requirement_id": "req-primary",
        "description": evidence_need,
        "relationship": "support",
        "evidence_ids": ["observed_il_001"],
        "decisive_evidence_ids": ["observed_il_001"],
        "observation_ids": ["obs-002"],
        "planning_blocking": True,
        "limitations": [],
        "query_family_ids": ["request-derived-behavior"],
        "engineering_question_ids": ["question-primary"],
        "action_indexes": [1, 2],
    }
    assert result.pack.hook_discovery["sufficiency"] == {
        "retrieval": {"status": "sufficient", "reasons": []},
        "engineering": {
            "status": "insufficient",
            "reasons": ["Runtime behavior remains unresolved."],
        },
        "planning": {
            "status": "insufficient",
            "reasons": ["Runtime behavior remains unresolved."],
        },
    }
    assert result.pack.hook_discovery["planning_action"] == "block"
    assert result.pack.readiness == "insufficient"
    assert result.pack.can_generate_patch is False
    assert result.pack.budget_summary["planning_model_steps_used"] == 1
    assert result.pack.budget_summary["model_steps_used"] == 3
    assert result.pack.budget_summary["total_model_steps_used"] == 4


def test_actual_planning_finish_schema_requires_requirement_relationships() -> None:
    legacy_required = evidence_discovery_finish_schema()["properties"][
        "evidence_conclusions"
    ]["items"]["required"]
    actual_required = evidence_discovery_finish_schema(
        require_requirement_binding=True
    )["properties"]["evidence_conclusions"]["items"]["required"]
    relation_required = evidence_discovery_finish_schema(
        require_requirement_binding=True,
        require_relation_binding=True,
    )["properties"]["evidence_conclusions"]["items"]["required"]

    assert legacy_required == [
        "claim",
        "claim_status",
        "observation_ids",
        "limitations",
    ]
    assert actual_required == [
        *legacy_required,
        "requirement_ids",
        "relationship",
    ]
    assert relation_required == [
        *legacy_required,
        "requirement_ids",
        "relation_ids",
        "relationship",
    ]


def test_actual_planning_allows_one_schema_bound_correction(
    tmp_path: Path,
) -> None:
    evidence_need = "Which current method exposes movement?"
    valid_plan = _actual_plan(
        behavior_goal="Find a current movement observation point.",
        queries=["movement"],
        evidence_need=evidence_need,
    )
    invalid_plan = deepcopy(valid_plan)
    invalid_plan["search_plan"]["engineering_questions"][0][
        "requirement_ids"
    ] = ["unknown-requirement"]
    model = _ScriptedModel(
        [
            invalid_plan,
            valid_plan,
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("movement"),
                "evidence_need": evidence_need,
                "derived_from_observation_ids": [],
            },
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Verify the observed method.",
                "derived_from_observation_ids": ["obs-001"],
            },
            _finish_after_observed_il(),
        ]
    )

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(replace(_request(tmp_path), require_actual_planning=True))

    correction = model.calls[1][-1]["content"]
    assert correction["message_type"] == "actual_planning_validation_error"
    assert correction["error_code"] == "SEARCH_PLAN_ENGINEERING_REQUIREMENT_UNKNOWN"
    assert correction["topology_issues"] == [
        {
            "code": "ENGINEERING_REQUIREMENT_REFERENCE_UNKNOWN",
            "unknown_requirement_ids": ["unknown-requirement"],
        },
        {
            "code": "PLANNING_REQUIREMENT_NOT_COVERED",
            "requirement_ids": ["req-primary"],
        },
    ]
    assert correction["required_next_action"] == "plan"
    assert "ES_Hitreact.ActivateState" not in json.dumps(correction)
    assert result.agent_discovery is not None
    assert result.agent_discovery["planning_status"] == "ready"
    assert result.pack.budget_summary["planning_model_steps_used"] == 2
    assert result.pack.budget_summary["total_model_steps_used"] == 5


def test_actual_planning_correction_reports_empty_and_dangling_topology_only(
    tmp_path: Path,
) -> None:
    evidence_need = "Which current method exposes status-effect activation?"
    valid_plan = _actual_plan(
        behavior_goal="Find a current status-effect activation observation point.",
        queries=["status", "effect", "activate"],
        evidence_need=evidence_need,
    )
    rejected_plan = deepcopy(valid_plan)
    rejected_plan["requirement_projection"]["planning_blocking_questions"] = []
    rejected_plan["search_plan"]["engineering_questions"] = []
    rejected_plan["search_plan"]["query_families"][0]["question_ids"] = [
        "unregistered-question"
    ]
    model = _ScriptedModel(
        [
            rejected_plan,
            valid_plan,
            _family_selection("request-derived-behavior"),
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Verify the method identity observed this run.",
                "derived_from_observation_ids": ["obs-001"],
            },
            _finish_after_observed_il(symbol="Observed.Status.Apply"),
        ]
    )

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(symbol="Observed.Status.Apply"),
    ).discover(
        replace(
            _request(tmp_path),
            natural_language_request=(
                "When a temporary status effect begins, log its current activation point."
            ),
            require_actual_planning=True,
        )
    )

    correction = model.calls[1][-1]["content"]
    assert correction["topology_issues"] == [
        {"code": "PLANNING_REQUIREMENTS_EMPTY"},
        {"code": "ENGINEERING_QUESTIONS_EMPTY"},
        {
            "code": "INITIAL_FOCUS_QUESTION_UNKNOWN",
            "initial_focus_question_id": "question-primary",
        },
        {
            "code": "QUERY_FAMILY_QUESTION_REFERENCE_UNKNOWN",
            "unknown_question_ids": ["unregistered-question"],
            "family_ids": ["request-derived-behavior"],
        },
    ]
    serialized = json.dumps(correction, ensure_ascii=False)
    assert "Observed.Status.Apply" not in serialized
    assert "expected_sufficiency" not in serialized
    assert "expected_control_action" not in serialized
    assert result.agent_discovery is not None
    assert result.agent_discovery["planning_status"] == "ready"
    assert [action["tool"] for action in result.actions] == [
        "search_dotnet_metadata",
        "inspect_method_il",
    ]


def test_actual_planning_second_invalid_plan_stops_without_tools(
    tmp_path: Path,
) -> None:
    invalid_plan = _actual_plan(
        behavior_goal="Find a current movement observation point.",
        queries=["movement"],
        evidence_need="Which current method exposes movement?",
    )
    invalid_plan["search_plan"]["engineering_questions"][0][
        "requirement_ids"
    ] = ["unknown-requirement"]
    model = _ScriptedModel([invalid_plan, deepcopy(invalid_plan)])
    executor = _ObservedToolExecutor()

    with pytest.raises(
        ValueError,
        match="SEARCH_PLAN_ENGINEERING_REQUIREMENT_UNKNOWN",
    ):
        EvidenceDiscoverySpecialist(
            model=model,
            tool_executor=executor,
        ).discover(replace(_request(tmp_path), require_actual_planning=True))

    assert len(model.calls) == 2
    assert executor.actions == []


def test_supplemental_family_reports_exact_binding_failures() -> None:
    plan = _actual_plan(
        behavior_goal="Find a current movement observation point.",
        queries=["movement"],
        evidence_need="Which current method exposes movement?",
    )
    plan["search_plan"]["query_families"].append(
        {
            "family_id": "guard-family",
            "queries": ["guard"],
            "evidence_need": "Find guard metadata.",
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-primary"],
        }
    )
    first_action = {
        "action": "use_tool",
        "tool": "search_dotnet_metadata",
        "source_id": "current-interop",
        "arguments": _metadata_arguments("movement"),
        "evidence_need": "Which current method exposes movement?",
        "derived_from_observation_ids": [],
        "query_family_id": "request-derived-behavior",
    }
    supplemental = {
        "action": "use_tool",
        "tool": "search_dotnet_metadata",
        "source_id": "current-interop",
        "arguments": _metadata_arguments("guard"),
        "evidence_need": "Find guard metadata.",
        "derived_from_observation_ids": [],
        "query_family_id": "guard-family",
    }
    actual = _validated_actual_from_plan(plan)
    observations = [
        ToolObservation(
            observation_id="obs-001",
            tool="search_dotnet_metadata",
            source_id="current-interop",
            summary="The initial frozen family was executed.",
            data={"methods": [], "types": [], "fields": []},
        )
    ]

    with pytest.raises(
        ValueError,
        match="SUPPLEMENTAL_ACTION_OBSERVATION_BINDING_REQUIRED",
    ):
        _validate_supplemental_search(
            supplemental,
            actions=[first_action],
            observations=observations,
            agent_discovery=actual,
        )

    supplemental["derived_from_observation_ids"] = ["obs-001"]
    supplemental["evidence_need"] = "changed need"
    with pytest.raises(ValueError, match="SUPPLEMENTAL_QUERY_FAMILY_MATCH_INVALID"):
        _validate_supplemental_search(
            supplemental,
            actions=[first_action],
            observations=observations,
            agent_discovery=actual,
        )


def test_supplemental_family_binds_the_only_pending_same_question_observation() -> None:
    plan = _actual_plan(
        behavior_goal="Find a current movement observation point.",
        queries=["movement"],
        evidence_need="Which current method exposes movement?",
    )
    plan["search_plan"]["query_families"].append(
        {
            "family_id": "guard-family",
            "queries": ["guard"],
            "evidence_need": "Find guard metadata.",
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-primary"],
        }
    )
    actual = _validated_actual_from_plan(plan)
    first_action = {
        "action": "use_tool",
        "tool": "search_dotnet_metadata",
        "source_id": "current-interop",
        "arguments": _metadata_arguments("movement", limit_per_kind=10),
        "evidence_need": "Which current method exposes movement?",
        "derived_from_observation_ids": [],
        "query_family_id": "request-derived-behavior",
    }
    observations = [
        ToolObservation(
            observation_id="obs-001",
            tool="search_dotnet_metadata",
            source_id="current-interop",
            summary="The initial family was searched.",
            data={"methods": [], "types": [], "fields": []},
        )
    ]

    resolved = _resolve_action_from_frozen_plan(
        _family_selection("guard-family"),
        actions=[first_action],
        observations=observations,
        agent_discovery=actual,
    )

    assert resolved["derived_from_observation_ids"] == ["obs-001"]
    _validate_supplemental_search(
        resolved,
        actions=[first_action],
        observations=observations,
        agent_discovery=actual,
    )


def test_supplemental_family_does_not_bind_ambiguous_pending_observations() -> None:
    plan = _actual_plan(
        behavior_goal="Find a current movement observation point.",
        queries=["movement"],
        evidence_need="Which current method exposes movement?",
    )
    plan["search_plan"]["query_families"].append(
        {
            "family_id": "guard-family",
            "queries": ["guard"],
            "evidence_need": "Find guard metadata.",
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-primary"],
        }
    )
    actual = _validated_actual_from_plan(plan)
    actions = [
        {
            "action": "use_tool",
            "tool": "search_dotnet_metadata",
            "source_id": "current-interop",
            "arguments": _metadata_arguments("movement", limit_per_kind=10),
            "evidence_need": "Which current method exposes movement?",
            "derived_from_observation_ids": [],
            "query_family_id": "request-derived-behavior",
        },
        {
            "action": "use_tool",
            "tool": "search_dotnet_metadata",
            "source_id": "current-interop",
            "arguments": _metadata_arguments("movement-detail", limit_per_kind=10),
            "evidence_need": "Which current method exposes movement?",
            "derived_from_observation_ids": [],
            "query_family_id": "movement-detail-family",
        },
    ]
    observations = [
        ToolObservation(
            observation_id=f"obs-{index:03d}",
            tool="search_dotnet_metadata",
            source_id="current-interop",
            summary="A family was searched.",
            data={"methods": [], "types": [], "fields": []},
        )
        for index in (1, 2)
    ]

    resolved = _resolve_action_from_frozen_plan(
        _family_selection("guard-family"),
        actions=actions,
        observations=observations,
        agent_discovery=actual,
    )

    assert resolved["derived_from_observation_ids"] == []


def test_strict_roundtrip_proves_supplemental_observation_binding(
    tmp_path: Path,
) -> None:
    class _SecondMetadataZeroExecutor(_ObservedToolExecutor):
        def __init__(self) -> None:
            super().__init__()
            self.metadata_calls = 0

        def execute(self, **kwargs) -> ToolObservation:
            action = kwargs["action"]
            if action["tool"] != "search_dotnet_metadata":
                return super().execute(**kwargs)
            self.metadata_calls += 1
            if self.metadata_calls == 1:
                return super().execute(**kwargs)
            source = kwargs["source"]
            observation_id = kwargs["observation_id"]
            self.actions.append(action)
            return ToolObservation(
                observation_id=observation_id,
                tool="search_dotnet_metadata",
                source_id=source.source_id,
                summary="The bounded metadata search returned no methods.",
                data={"methods": [], "types": [], "fields": []},
            )

    evidence_need = "Which current method exposes movement?"
    plan = _actual_plan(
        behavior_goal="Find a current movement observation point.",
        queries=["movement"],
        evidence_need=evidence_need,
    )
    plan["search_plan"]["query_families"].append(
        {
            "family_id": "guard-family",
            "queries": ["guard"],
            "evidence_need": evidence_need,
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-primary"],
        }
    )
    result = EvidenceDiscoverySpecialist(
        model=_ScriptedModel(
            [
                plan,
                _family_selection("request-derived-behavior"),
                {
                    "action": "use_tool",
                    "tool": "inspect_method_il",
                    "source_id": "current-interop",
                    "arguments": {"candidate_ref": "candidate_obs_001"},
                    "evidence_need": evidence_need,
                    "derived_from_observation_ids": ["obs-001"],
                },
                _family_selection("guard-family"),
                {
                    "action": "finish",
                    "decision": "needs_more_evidence",
                    "evidence_conclusions": [],
                    "unresolved_questions": [evidence_need],
                    "missing_capabilities": [
                        "No current managed method was observed."
                    ],
                },
            ]
        ),
        tool_executor=_SecondMetadataZeroExecutor(),
    ).discover(
        replace(
            _request(tmp_path),
            require_actual_planning=True,
            max_tool_calls=3,
            max_model_steps=4,
        )
    )
    payload = result.pack.to_artifact_payload()
    followup_attempt = next(
        attempt
        for attempt in payload["model_action_trace"]
        if attempt["action"].get("family_id") == "guard-family"
    )
    assert followup_attempt["action"]["derived_from_observation_ids"] == []
    assert followup_attempt["resolved_action"][
        "derived_from_observation_ids"
    ] == ["obs-002"]

    ArtifactTypeRegistry().validate_write(
        artifact_type="evidence_pack",
        status="success",
        payload=payload,
    )
    store = ArtifactStore(tmp_path / "supplemental-binding-store")
    feature_id = "feature-supplemental-binding"
    feature_ref = store.write(
        feature_id=feature_id,
        artifact_type="feature_spec",
        payload=_strict_roundtrip_feature_payload(feature_id),
    )
    evidence_ref = store.write(
        feature_id=feature_id,
        artifact_type="evidence_pack",
        payload=payload,
        upstream_refs=[feature_ref],
    )
    committed = store.read(evidence_ref)["data"]
    assert EvidencePack.from_artifact_payload(committed).to_artifact_payload() == payload

    for invalid_derivation in ([], ["obs-001"], ["obs-missing"]):
        tampered = deepcopy(payload)
        tampered_attempt = next(
            attempt
            for attempt in tampered["model_action_trace"]
            if attempt["action"].get("family_id") == "guard-family"
        )
        tampered_attempt["resolved_action"][
            "derived_from_observation_ids"
        ] = invalid_derivation
        tampered_attempt["resolved_action_sha256"] = hashlib.sha256(
            json.dumps(
                tampered_attempt["resolved_action"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with pytest.raises(
            ArtifactRegistryError,
            match="Invalid semantic EvidencePack",
        ):
            ArtifactTypeRegistry().validate_write(
                artifact_type="evidence_pack",
                status="success",
                payload=tampered,
            )

    ambiguous = deepcopy(payload)
    first_il_attempt = next(
        attempt
        for attempt in ambiguous["model_action_trace"]
        if attempt["action"].get("tool") == "inspect_method_il"
    )
    first_il_attempt["action"]["derived_from_observation_ids"] = []
    first_il_attempt["action_sha256"] = hashlib.sha256(
        json.dumps(
            first_il_attempt["action"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(
        ArtifactRegistryError,
        match="Invalid semantic EvidencePack",
    ):
        ArtifactTypeRegistry().validate_write(
            artifact_type="evidence_pack",
            status="success",
            payload=ambiguous,
        )


def test_supplemental_family_does_not_bind_a_different_question() -> None:
    plan = _actual_plan(
        behavior_goal="Find a current movement observation point.",
        queries=["movement"],
        evidence_need="Which current method exposes movement?",
    )
    projection = plan["requirement_projection"]
    search_plan = plan["search_plan"]
    projection["planning_blocking_questions"].append(
        {"requirement_id": "req-output", "question": "Which method renders output?"}
    )
    search_plan["engineering_questions"].append(
        {
            "question_id": "question-output",
            "question": "Which method renders output?",
            "requirement_ids": ["req-output"],
        }
    )
    search_plan["query_families"].append(
        {
            "family_id": "output-family",
            "queries": ["overlay"],
            "evidence_need": "Find output metadata.",
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-output"],
        }
    )
    actual = _validated_actual_from_plan(plan)
    first_action = {
        "action": "use_tool",
        "tool": "search_dotnet_metadata",
        "source_id": "current-interop",
        "arguments": _metadata_arguments("movement", limit_per_kind=10),
        "evidence_need": "Which current method exposes movement?",
        "derived_from_observation_ids": [],
        "query_family_id": "request-derived-behavior",
    }
    observations = [
        ToolObservation(
            observation_id="obs-001",
            tool="search_dotnet_metadata",
            source_id="current-interop",
            summary="The initial family was searched.",
            data={"methods": [], "types": [], "fields": []},
        )
    ]

    resolved = _resolve_action_from_frozen_plan(
        _family_selection("output-family"),
        actions=[first_action],
        observations=observations,
        agent_discovery=actual,
    )

    assert resolved["derived_from_observation_ids"] == []


def test_supplemental_family_does_not_rebind_a_consumed_observation() -> None:
    plan = _actual_plan(
        behavior_goal="Find a current movement observation point.",
        queries=["movement"],
        evidence_need="Which current method exposes movement?",
    )
    plan["search_plan"]["query_families"].append(
        {
            "family_id": "guard-family",
            "queries": ["guard"],
            "evidence_need": "Find guard metadata.",
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-primary"],
        }
    )
    actual = _validated_actual_from_plan(plan)
    consumed_action = {
        "action": "use_tool",
        "tool": "search_dotnet_metadata",
        "source_id": "current-interop",
        "arguments": _metadata_arguments("movement", limit_per_kind=10),
        "evidence_need": "Which current method exposes movement?",
        "derived_from_observation_ids": ["obs-001"],
        "query_family_id": "request-derived-behavior",
    }
    observations = [
        ToolObservation(
            observation_id="obs-001",
            tool="search_dotnet_metadata",
            source_id="current-interop",
            summary="The observation was already consumed.",
            data={"methods": [], "types": [], "fields": []},
        )
    ]

    resolved = _resolve_action_from_frozen_plan(
        _family_selection("guard-family"),
        actions=[consumed_action],
        observations=observations,
        agent_discovery=actual,
    )

    assert resolved["derived_from_observation_ids"] == []


def test_supplemental_family_must_share_the_origin_engineering_question() -> None:
    plan = _actual_plan(
        behavior_goal="Find a current status observation point.",
        queries=["status"],
        evidence_need="Which current method exposes the status transition?",
    )
    projection = plan["requirement_projection"]
    search_plan = plan["search_plan"]
    assert isinstance(projection, dict) and isinstance(search_plan, dict)
    projection["planning_blocking_questions"].append(
        {
            "requirement_id": "req-output",
            "question": "Which current method renders an output effect?",
        }
    )
    search_plan["engineering_questions"].append(
        {
            "question_id": "question-output",
            "question": "Which current method renders an output effect?",
            "requirement_ids": ["req-output"],
        }
    )
    search_plan["query_families"].append(
        {
            "family_id": "output-family",
            "queries": ["overlay"],
            "evidence_need": "Find output-effect metadata.",
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-output"],
        }
    )
    action = {
        "action": "use_tool",
        "tool": "search_dotnet_metadata",
        "source_id": "current-interop",
        "arguments": _metadata_arguments("overlay"),
        "evidence_need": "Find output-effect metadata.",
        "derived_from_observation_ids": ["obs-001"],
        "query_family_id": "output-family",
    }
    first_action = {
        "action": "use_tool",
        "tool": "search_dotnet_metadata",
        "source_id": "current-interop",
        "arguments": _metadata_arguments("status"),
        "evidence_need": "Which current method exposes the status transition?",
        "derived_from_observation_ids": [],
        "query_family_id": "request-derived-behavior",
    }
    observations = [
        ToolObservation(
            observation_id="obs-001",
            tool="search_dotnet_metadata",
            source_id="current-interop",
            summary="The first family returned unrelated methods.",
            data={"methods": [{"candidate_ref": "unrelated-ref"}]},
        )
    ]

    with pytest.raises(
        ValueError,
        match="SUPPLEMENTAL_QUERY_FAMILY_QUESTION_BINDING_MISMATCH",
    ):
        _validate_supplemental_search(
            action,
            actions=[first_action],
            observations=observations,
            agent_discovery=_validated_actual_from_plan(plan),
        )


def test_phase_2_model_sufficient_cannot_hide_unbound_planning_question(
    tmp_path: Path,
) -> None:
    plan = _actual_plan(
        behavior_goal="Find a current movement observation point.",
        queries=["movement"],
        evidence_need="Which current method exposes movement?",
    )
    projection = plan["requirement_projection"]
    search_plan = plan["search_plan"]
    assert isinstance(projection, dict) and isinstance(search_plan, dict)
    projection["planning_blocking_questions"].append({
        "requirement_id": "req-guard",
        "question": "Which current method proves the required guard?",
    })
    search_plan["engineering_questions"].append({
        "question_id": "question-guard",
        "question": "Which current method proves the required guard?",
        "requirement_ids": ["req-guard"],
    })
    search_plan["planned_lanes"].append({
        "lane": "guard_metadata_discovery",
        "tool": "search_dotnet_metadata",
        "source_ids": ["current-interop"],
        "question_ids": ["question-guard"],
    })
    search_plan["query_families"].append({
        "family_id": "guard-family",
        "queries": ["guard"],
        "evidence_need": "Which current method proves the required guard?",
        "source_ids": ["current-interop"],
        "tool": "search_dotnet_metadata",
        "question_ids": ["question-guard"],
    })
    finish = _finish_after_observed_il()
    finish["decision"] = "sufficient_for_proposal"
    finish["unresolved_questions"] = []
    model = _ScriptedModel([
        plan,
        {
            "action": "use_tool",
            "tool": "search_dotnet_metadata",
            "source_id": "current-interop",
            "arguments": _metadata_arguments("movement"),
            "evidence_need": "Which current method exposes movement?",
            "derived_from_observation_ids": [],
        },
        {
            "action": "use_tool",
            "tool": "inspect_method_il",
            "source_id": "current-interop",
            "arguments": {"candidate_ref": "candidate_obs_001"},
            "evidence_need": "Verify the observed method.",
            "derived_from_observation_ids": ["obs-001"],
        },
        finish,
    ])

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(replace(_request(tmp_path), require_actual_planning=True))

    semantics = result.pack.hook_discovery
    assert semantics is not None
    relationships = {
        value["requirement_id"]: value for value in semantics["evidence_relationships"]
    }
    assert relationships["req-primary"]["relationship"] == "support"
    assert relationships["req-guard"]["relationship"] == "missing"
    assert semantics["planning_action"] == "block"
    assert result.pack.readiness == "insufficient"
    assert result.pack.can_generate_patch is False


def test_phase_2_all_authoritative_planning_questions_close_top_level(
    tmp_path: Path,
) -> None:
    plan = _actual_plan(
        behavior_goal="Find a current movement observation point.",
        queries=["movement"],
        evidence_need="Which current method exposes movement?",
    )
    projection = plan["requirement_projection"]
    assert isinstance(projection, dict)
    projection["deferred_planning_or_runtime_questions"] = [
        "Which Runtime event multiplicity occurs in production?"
    ]
    finish = _finish_after_observed_il()
    finish["decision"] = "sufficient_for_proposal"
    finish["unresolved_questions"] = []
    model = _ScriptedModel([
        plan,
        {
            "action": "use_tool",
            "tool": "search_dotnet_metadata",
            "source_id": "current-interop",
            "arguments": _metadata_arguments("movement"),
            "evidence_need": "Which current method exposes movement?",
            "derived_from_observation_ids": [],
        },
        {
            "action": "use_tool",
            "tool": "inspect_method_il",
            "source_id": "current-interop",
            "arguments": {"candidate_ref": "candidate_obs_001"},
            "evidence_need": "Verify the observed method.",
            "derived_from_observation_ids": ["obs-001"],
        },
        finish,
    ])

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(replace(_request(tmp_path), require_actual_planning=True))

    semantics = result.pack.hook_discovery
    assert semantics is not None
    assert semantics["sufficiency"] == {
        "retrieval": {"status": "sufficient", "reasons": []},
        "engineering": {"status": "sufficient", "reasons": []},
        "planning": {"status": "sufficient", "reasons": []},
    }
    assert semantics["planning_action"] == "continue"
    assert result.pack.readiness == "sufficient"
    assert result.pack.can_generate_patch is True
    assert result.pack.gaps == ()
    assert result.pack.blockers == ()
    assert [item.evidence_id for item in result.pack.items] == ["observed_il_001"]


def test_phase_2_authoritative_conflict_projects_contradictory_top_level(
    tmp_path: Path,
) -> None:
    plan = _actual_plan(
        behavior_goal="Find a current movement observation point.",
        queries=["movement"],
        evidence_need="Which current method exposes movement?",
    )
    finish = _finish_after_observed_il()
    finish["decision"] = "conflicting_evidence"
    finish["evidence_conclusions"][0]["relationship"] = "conflict"
    finish["unresolved_questions"] = []
    model = _ScriptedModel([
        plan,
        {
            "action": "use_tool",
            "tool": "search_dotnet_metadata",
            "source_id": "current-interop",
            "arguments": _metadata_arguments("movement"),
            "evidence_need": "Which current method exposes movement?",
            "derived_from_observation_ids": [],
        },
        {
            "action": "use_tool",
            "tool": "inspect_method_il",
            "source_id": "current-interop",
            "arguments": {"candidate_ref": "candidate_obs_001"},
            "evidence_need": "Verify the observed method.",
            "derived_from_observation_ids": ["obs-001"],
        },
        finish,
    ])

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(replace(_request(tmp_path), require_actual_planning=True))

    semantics = result.pack.hook_discovery
    assert semantics is not None
    assert semantics["evidence_relationships"][0]["relationship"] == "conflict"
    assert semantics["sufficiency"]["engineering"]["status"] == "contradictory"
    assert semantics["sufficiency"]["planning"]["status"] == "contradictory"
    assert result.pack.readiness == "contradictory"
    assert result.pack.can_generate_patch is False


def test_legacy_evidence_pack_serialization_does_not_add_agent_discovery() -> None:
    payload = EvidencePack.empty(
        query="legacy deterministic request",
        reason="no matched evidence",
    ).to_artifact_payload()

    assert "agent_discovery" not in payload


def test_phase_2_calibration_adapter_uses_injected_actual_dependencies(
    tmp_path: Path,
) -> None:
    r8_root = tmp_path / "r8"
    (r8_root / "Assets" / "Scripts" / "Modules-ASM").mkdir(parents=True)
    evidence_need = "Which current managed method exposes an enemy reaction?"
    plan = _actual_plan(
        behavior_goal="Observe an enemy reaction for user feedback.",
        queries=["enemy reaction"],
        evidence_need=evidence_need,
    )
    model = _ScriptedModel(
        [
            plan,
            _source_identifier_selection("EnemyReaction"),
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("EnemyReaction"),
                "evidence_need": evidence_need,
                "derived_from_observation_ids": [],
            },
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Verify the identity from the current metadata observation.",
                "derived_from_observation_ids": ["obs-001"],
            },
            _finish_after_observed_il(),
        ]
    )
    source_root = tmp_path / "interop"
    source_root.mkdir()
    (r8_root / "Assets" / "Scripts" / "Modules-ASM" / "EnemyReaction.cs").write_text(
        "public class EnemyReaction { public void NotifyReaction() {} }\n",
        encoding="utf-8",
    )
    source = EvidenceDiscoverySource(
        source_id="current-interop",
        source_type="decompiled_api",
        kind="il2cpp_interop_directory",
        evidence_class="current_installed_generated_interop",
        source_authority="authoritative",
        description="Current generated interop used as an actual physical source.",
        root_path=source_root,
        allowed_tools=("search_dotnet_metadata", "inspect_method_il"),
    )

    pack = run_better_hit_feedback_calibration(
        r8_root=r8_root,
        request="Show feedback when a shot makes an enemy react.",
        model=model,
        tool_executor=_SourceGroundedObservedToolExecutor(),
        sources=(source,),
    )

    assert pack.agent_discovery is not None
    assert pack.prompt_contract["actual_planning_required"] is True
    assert pack.prompt_contract["version"] == "agent_evidence_discovery_prompt_v8"
    source_observation = model.calls[1][-1]["content"]
    assert isinstance(source_observation, dict)
    assert source_observation["message_type"] == "source_evidence_observation"
    inventory = source_observation["observed_identifier_inventory"]
    assert len(inventory) <= 64
    assert all(
        set(item)
        == {
            "selection_id",
            "observed_identifier",
            "extraction_kind",
            "source_path",
            "source_paths",
            "source_evidence_count",
            "source_fact",
        }
        for item in inventory
    )
    assert "source_evidence_refs" not in json.dumps(inventory)
    assert any(
        item["observed_identifier"] == "EnemyReaction"
        for item in inventory
    )
    enemy_reaction_view = next(
        item
        for item in inventory
        if item["observed_identifier"] == "EnemyReaction"
    )
    assert enemy_reaction_view["source_fact"] == (
        "public class EnemyReaction { public void NotifyReaction() {} }"
    )
    assert enemy_reaction_view["extraction_kind"] == "identity_field"
    assert enemy_reaction_view["source_paths"] == ["EnemyReaction.cs"]
    assert enemy_reaction_view["source_evidence_count"] >= 1
    assert pack.agent_discovery["search_plan"]["query_families"][0]["queries"] == [
        "EnemyReaction"
    ]
    assert any(item.source_path == "EnemyReaction.cs" for item in pack.items)
    assert {
        item.source_authority
        for item in pack.items
        if item.source_path == "EnemyReaction.cs"
    } == {"supporting"}
    source_discovery = pack.budget_summary["source_discovery"]
    assert source_discovery["query_terms"] == ["EnemyReaction"]
    assert {
        item["origin"] for item in source_discovery["source_queries"]
    } >= {
        "natural_language_request",
        "requirement_projection.behavior_goal",
        "initial_focus_question",
        "initial_focus_query_family",
    }
    lane_execution = source_discovery["query_lane_execution"]
    assert lane_execution
    assert any(
        item["admitted_evidence_refs"]
        and any(
            evidence.evidence_id in item["admitted_evidence_refs"]
            for evidence in pack.items
            if evidence.source_path == "EnemyReaction.cs"
        )
        for item in lane_execution
    )
    literal_binding = next(
        item
        for item in source_discovery["metadata_literal_bindings"]
        if item["metadata_literal"] == "EnemyReaction"
    )
    assert literal_binding["grounding_status"] == "source_observed"
    assert literal_binding["evidence_refs"]
    assert source_discovery["source_grounded_discovery"] is True
    assert source_discovery["metadata_to_il_grounding"][0][
        "source_evidence_refs"
    ] == literal_binding["evidence_refs"]
    assert [item["tool"] for item in pack.tool_trace_summary] == [
        "search_dotnet_metadata",
        "inspect_method_il",
    ]
    assert pack.input_audit == {
        "manual_symbol_count": 0,
        "manual_tool_sequence_count": 0,
        "precomputed_report_count": 0,
        "operator_intervention_count": 0,
    }


def test_family_query_normalization_deduplicates_roots_and_bounds_leads() -> None:
    retained, dropped = _normalize_family_query_leads(
        [
            "  Shooting  ",
            "shoot",
            "FinishAuthentication",
            "AuthenticationCompleted",
            "TerminalStateChanged",
            "OverflowVocabulary",
        ]
    )

    assert retained == [
        "Shooting",
        "FinishAuthentication",
        "AuthenticationCompleted",
        "TerminalStateChanged",
    ]
    assert dropped == [
        {"query": "shoot", "reason": "duplicate_lexical_root"},
        {"query": "OverflowVocabulary", "reason": "family_budget_exceeded"},
    ]


def test_source_grounded_discovery_preserves_semantics_and_binds_literal(
    tmp_path: Path,
) -> None:
    evidence_need = "Which managed method reports terminal authentication completion?"
    plan = _actual_plan(
        behavior_goal="Observe terminal authentication completion.",
        queries=["FinishAuthentication", "AuthenticationFinished"],
        evidence_need=evidence_need,
    )
    plan["search_plan"]["query_families"].append(
        {
            "family_id": "authentication-alternate",
            "queries": ["CompleteAuthentication", "authentication complete"],
            "evidence_need": "Which alternate symbol reports authentication completion?",
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-primary"],
        }
    )
    model = _ScriptedModel(
        [
            plan,
            _source_identifier_selection(
                "FinishAuthentication",
            ),
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("FinishAuthentication"),
                "evidence_need": evidence_need,
                "derived_from_observation_ids": [],
            },
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Verify the observed authentication method.",
                "derived_from_observation_ids": ["obs-001"],
            },
            _finish_after_observed_il(
                symbol="TerminalFlow.FinishAuthentication"
            ),
        ]
    )
    captured_queries: list[tuple[dict[str, str], ...]] = []
    source_root = tmp_path / "source-corpus"
    source_root.mkdir()
    (source_root / "TerminalFlow.cs").write_text(
        "public sealed class TerminalFlow {\n"
        "    public void FinishAuthentication() { CommitSuccess(); }\n"
        "}\n",
        encoding="utf-8",
    )
    (source_root / "TerminalPrompt.cs").write_text(
        "public sealed class TerminalPrompt {\n"
        "    public void ShowPasswordHint() { RenderHint(); }\n"
        "}\n",
        encoding="utf-8",
    )
    database = KnowledgeDatabase(tmp_path / "knowledge.db")
    registry = SourceRegistry(database)
    registry.register(
        SourceDefinition(
            source_id="terminal-source",
            source_type="decompiled_api",
            root_path=source_root,
            metadata={"evidence_authority": "supporting"},
            allowed_extensions=frozenset({".cs"}),
        )
    )
    indexer = IncrementalIndexer(database=database, source_registry=registry)
    assert indexer.index_source("terminal-source").failed_files == 0
    indexer.build_retrieval_snapshot("terminal-source")
    real_retriever = DeterministicEvidenceRetriever(database)

    def source_retriever(
        queries: tuple[dict[str, str], ...],
    ) -> EvidencePack:
        captured_queries.append(queries)
        return real_retriever.retrieve_query_set(
            queries=queries,
            source_ids=("terminal-source",),
            per_query_lane_max_items=3,
            max_items=36,
        )

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_SourceGroundedObservedToolExecutor(
            symbol="TerminalFlow.FinishAuthentication"
        ),
        source_evidence_retriever=source_retriever,
    ).discover(
        replace(
            _request(tmp_path, include_second_source=False),
            natural_language_request=(
                "When a terminal finishes authentication, briefly pulse nearby "
                "corridor lights."
            ),
            require_actual_planning=True,
        )
    )

    assert captured_queries
    assert {item["origin"] for item in captured_queries[0]} >= {
        "natural_language_request",
        "requirement_projection.behavior_goal",
        "initial_focus_question",
        "initial_focus_query_family",
    }
    assert not any(
        item["origin"].startswith("bounded_code_vocabulary_lead:")
        for item in captured_queries[0]
    )
    assert any(
        item["query"] == "FinishAuthentication"
        for item in captured_queries[0]
    )
    source_discovery = result.pack.budget_summary["source_discovery"]
    assert result.agent_discovery["search_plan"]["query_families"] == [
        {
            "family_id": "request-derived-behavior",
            "queries": ["FinishAuthentication"],
            "evidence_need": evidence_need,
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-primary"],
        },
        {
            "family_id": "authentication-alternate",
            "queries": ["CompleteAuthentication", "authentication complete"],
            "evidence_need": "Which alternate symbol reports authentication completion?",
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-primary"],
        },
    ]
    binding = source_discovery["metadata_literal_bindings"][0]
    assert binding["metadata_literal"] == "FinishAuthentication"
    terminal_evidence_ids = {
        item.evidence_id
        for item in result.pack.items
        if Path(item.source_path).name == "TerminalFlow.cs"
    }
    assert terminal_evidence_ids
    assert set(binding["evidence_refs"]).issubset(terminal_evidence_ids)
    assert source_discovery["source_grounded_discovery"] is True
    grounding = source_discovery["metadata_to_il_grounding"][0]
    assert grounding["initial_focus_question_id"] == "question-primary"
    assert grounding["metadata_observation_id"] == "obs-001"
    assert grounding["query_family_id"] == "request-derived-behavior"
    assert grounding["matched_queries"] == ["FinishAuthentication"]
    assert set(grounding["source_evidence_refs"]).issubset(
        terminal_evidence_ids
    )
    assert grounding["method_ref"] == "candidate_obs_001"
    assert grounding["method_symbol"] == "TerminalFlow.FinishAuthentication"


def test_supplemental_family_reuses_source_identifier_selection_before_metadata(
    tmp_path: Path,
) -> None:
    evidence_need = "Which current method exposes the initial event?"
    secondary_question = (
        "Which current method exposes the downstream integration boundary?"
    )
    plan = _actual_plan(
        behavior_goal="Observe an event and its downstream integration boundary.",
        queries=["initial event"],
        evidence_need=evidence_need,
    )
    _add_secondary_planning_question(plan)
    followup_finish = _finish_after_observed_il()
    followup_finish["unresolved_questions"] = [secondary_question]
    model = _ScriptedModel(
        [
            plan,
            _source_identifier_selection("InitialSignal"),
            _family_selection("request-derived-behavior"),
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Verify the observed initial method.",
                "derived_from_observation_ids": ["obs-001"],
            },
            followup_finish,
            _family_selection("secondary-integration"),
            _source_identifier_selection("FollowupSignal"),
        ]
    )
    captured_queries: list[tuple[dict[str, str], ...]] = []

    def source_retriever(
        queries: tuple[dict[str, str], ...],
    ) -> EvidencePack:
        captured_queries.append(queries)
        identifier = "InitialSignal" if len(captured_queries) == 1 else "FollowupSignal"
        evidence_id = "source_initial" if len(captured_queries) == 1 else "source_followup"
        return EvidencePack(
            query="bounded source query set",
            readiness="partial",
            can_generate_patch=False,
            items=(
                EvidenceItem(
                    evidence_id=evidence_id,
                    source_type="decompiled_api",
                    source_path=f"{identifier}.cs",
                    symbol=identifier,
                    span={"start_line": 1, "end_line": 1},
                    retrieval_method="symbol_exact",
                    score=1.0,
                    claim_supported=f"The source declares {identifier}.",
                    excerpt=f"public void {identifier}()",
                    source_hash=("B" if len(captured_queries) == 1 else "C") * 64,
                    authority="mod_agent_deterministic",
                    source_authority="supporting",
                ),
            ),
            budget_summary={
                "source_query_execution": [],
                "query_count": len(queries),
                "max_items": 36,
                "combined_max_items": 36,
                "admitted_item_count": 1,
                "observed_identifier_extraction": [],
                "bounded_identifier_reference_expansion": {
                    "performed": False,
                    "query_lane_execution": [],
                    "admitted_evidence_refs": [],
                    "expansion_kind": "exact_identifier_reference_and_type_lookup",
                    "expansion_depth": 0,
                },
            },
        )

    executor = _SourceGroundedObservedToolExecutor()
    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=executor,
        source_evidence_retriever=source_retriever,
    ).discover(
        replace(
            _request(tmp_path, include_second_source=False),
            natural_language_request=(
                "When a terminal finishes authentication, briefly pulse nearby "
                "corridor lights."
            ),
            require_actual_planning=True,
            max_tool_calls=3,
            max_model_steps=4,
        )
    )

    assert len(captured_queries) == 2
    assert {item["origin"] for item in captured_queries[1]} >= {
        "selected_query_family",
        "selected_engineering_question",
        "natural_language_request",
    }
    supplemental_source_view = model.calls[6][-1]["content"]
    assert isinstance(supplemental_source_view, dict)
    assert supplemental_source_view["selected_query_family_id"] == (
        "secondary-integration"
    )
    assert [action.get("query_family_id") for action in executor.actions] == [
        "request-derived-behavior",
        None,
        "secondary-integration",
    ]
    assert executor.actions[2]["arguments"]["queries"] == ["FollowupSignal"]
    families = result.agent_discovery["search_plan"]["query_families"]
    assert next(
        family for family in families if family["family_id"] == "secondary-integration"
    )["queries"] == ["FollowupSignal"]
    assert {item.evidence_id for item in result.pack.items} >= {
        "source_initial",
        "source_followup",
    }
    followup_binding = next(
        item
        for item in result.pack.budget_summary["source_discovery"][
            "metadata_literal_bindings"
        ]
        if item["query_family_id"] == "secondary-integration"
        and item["metadata_literal"] == "FollowupSignal"
    )
    assert followup_binding["evidence_refs"] == ["source_followup"]
    payload = result.pack.to_artifact_payload()
    assert EvidencePack.from_artifact_payload(payload).to_artifact_payload() == payload


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("unknown_selection", "SOURCE_IDENTIFIER_SELECTION_ID_INVALID"),
        ("duplicate_selection", "SOURCE_IDENTIFIER_SELECTION_CONTENT_INVALID"),
    ],
)
def test_source_identifier_selection_fails_before_tools_on_unknown_or_duplicate(
    tmp_path: Path,
    mutation: str,
    error: str,
) -> None:
    evidence_need = "Which method reports terminal authentication completion?"
    plan = _actual_plan(
        behavior_goal="Observe terminal authentication completion.",
        queries=["authentication"],
        evidence_need=evidence_need,
    )
    selected = _source_identifier_selection(
        "FinishAuthentication",
        selection_ids=(
            ["s99"]
            if mutation == "unknown_selection"
            else ["s01", "s01"]
        ),
    )
    model = _ScriptedModel([plan, selected])
    executor = _ObservedToolExecutor()

    def source_retriever(
        queries: tuple[dict[str, str], ...],
    ) -> EvidencePack:
        assert queries
        return EvidencePack(
            query="bounded source query set",
            readiness="partial",
            can_generate_patch=False,
            items=(
                EvidenceItem(
                    evidence_id="source_terminal_finish",
                    source_type="decompiled_api",
                    source_path="TerminalFlow.cs",
                    symbol="FinishAuthentication",
                    span={"start_line": 12, "end_line": 12},
                    retrieval_method="symbol_exact",
                    score=1.0,
                    claim_supported="The source declares FinishAuthentication.",
                    excerpt="public void FinishAuthentication()",
                    source_hash="B" * 64,
                    authority="mod_agent_deterministic",
                    source_authority="supporting",
                ),
            ),
            budget_summary={"source_query_execution": []},
        )

    specialist = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=executor,
        source_evidence_retriever=source_retriever,
    )
    with pytest.raises(ValueError, match=error):
        specialist.discover(
            replace(
                _request(tmp_path, include_second_source=False),
                natural_language_request=(
                    "When a terminal finishes authentication, briefly pulse nearby "
                    "corridor lights."
                ),
                require_actual_planning=True,
            )
        )
    assert executor.actions == []


def test_v4_first_slice_requires_family_only_for_initial_focus() -> None:
    plan = _actual_plan(
        behavior_goal="Observe one event before downstream integration planning.",
        queries=["event"],
        evidence_need="Which method exposes the event?",
    )
    _add_secondary_planning_question(plan)
    search_plan = plan["search_plan"]
    assert isinstance(search_plan, dict)
    secondary_family = search_plan["query_families"].pop()

    validate_agent_discovery_actual(_validated_actual_from_plan(plan))

    search_plan["query_families"] = [secondary_family]
    with pytest.raises(
        ValueError,
        match="SEARCH_PLAN_INITIAL_FOCUS_FAMILY_MISSING",
    ):
        validate_agent_discovery_actual(_validated_actual_from_plan(plan))


def test_phase_2_bhf_symbol_identity_only_enters_after_tool_observation(
    tmp_path: Path,
) -> None:
    request_text = "Show a yellow marker and play a sound when a shot makes an enemy stagger."
    evidence_need = "Which current managed methods expose an enemy stagger reaction?"
    plan = _actual_plan(
        behavior_goal="Observe a shot-triggered enemy stagger for feedback.",
        queries=["enemy stagger reaction"],
        evidence_need=evidence_need,
    )
    model = _ScriptedModel(
        [
            plan,
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("enemy stagger reaction"),
                "evidence_need": evidence_need,
                "derived_from_observation_ids": [],
            },
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Verify the identity observed in the metadata result.",
                "derived_from_observation_ids": ["obs-001"],
            },
            _finish_after_observed_il(symbol="ES_Hitreact.ActivateState"),
        ]
    )
    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(symbol="ES_Hitreact.ActivateState"),
    ).discover(replace(_request(tmp_path), natural_language_request=request_text, require_actual_planning=True))

    assert "ES_Hitreact.ActivateState" not in json.dumps(model.calls[0], ensure_ascii=False)
    assert "ES_Hitreact.ActivateState" not in json.dumps(result.agent_discovery, ensure_ascii=False)
    assert "ES_Hitreact.ActivateState" in json.dumps(model.calls[2], ensure_ascii=False)
    assert result.pack.items[0].symbol == "ES_Hitreact.ActivateState"


def test_phase_2_wall_hints_remain_separate_from_hard_constraints(
    tmp_path: Path,
) -> None:
    hard_constraint = "Unconfigured areas must never allow surface crawling."
    ladder_hint = "Investigate existing ladder movement logic."
    json_hint = "Investigate the supplied JSON map configuration reference."
    evidence_need = "What current mechanisms expose surface movement and configured areas?"
    plan = _actual_plan(
        behavior_goal="Allow eligible enemies to use configured walls and ceilings.",
        queries=["surface movement", "configured area"],
        evidence_need=evidence_need,
        hard_constraints=[hard_constraint],
        implementation_hints=[ladder_hint, json_hint],
    )
    model = _ScriptedModel([
        plan,
        {
            "action": "use_tool",
            "tool": "search_dotnet_metadata",
            "source_id": "current-interop",
            "arguments": _metadata_arguments("surface movement", "configured area"),
            "evidence_need": evidence_need,
            "derived_from_observation_ids": [],
        },
        {
            "action": "use_tool",
            "tool": "inspect_method_il",
            "source_id": "current-interop",
            "arguments": {"candidate_ref": "candidate_obs_001"},
            "evidence_need": "Verify the observed surface-related identity.",
            "derived_from_observation_ids": ["obs-001"],
        },
        _finish_after_observed_il(),
    ])
    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(
        replace(
            _request(tmp_path),
            natural_language_request=(
                "Let eligible enemies crawl on configured walls and ceilings; investigate ladder logic and a JSON map reference."
            ),
            require_actual_planning=True,
        )
    )
    assert result.agent_discovery is not None
    projection = result.agent_discovery["requirement_projection"]
    assert projection["hard_constraints"] == [hard_constraint]
    assert projection["implementation_hints"] == [
        {"text": ladder_hint, "role": "investigation_lead"},
        {"text": json_hint, "role": "investigation_lead"},
    ]
    assert "expected_control_action" not in json.dumps(result.agent_discovery)


def test_phase_2_zero_result_uses_one_planned_expansion_then_observation_bound_il(
    tmp_path: Path,
) -> None:
    evidence_need = "Which current managed method exposes surface movement?"
    plan = _actual_plan(
        behavior_goal="Find a current surface movement observation point.",
        queries=["enemy wall movement behavior"],
        evidence_need=evidence_need,
    )
    search_plan = plan["search_plan"]
    assert isinstance(search_plan, dict)
    families = search_plan["query_families"]
    assert isinstance(families, list)
    families.append(
        {
            "family_id": "planned-broader-movement",
            "queries": ["movement"],
            "evidence_need": evidence_need,
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-primary"],
        }
    )
    model = _ScriptedModel(
        [
            plan,
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("enemy wall movement behavior"),
                "evidence_need": evidence_need,
                "derived_from_observation_ids": [],
            },
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("movement"),
                "evidence_need": evidence_need,
                "derived_from_observation_ids": ["obs-001"],
            },
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_002"},
                "evidence_need": "Verify the identity from the expanded metadata observation.",
                "derived_from_observation_ids": ["obs-002"],
            },
            {
                **_finish_after_observed_il(),
                "evidence_conclusions": [
                    {
                        "claim": "Observed inspected symbol: Observed.Type.Move.",
                        "claim_status": "observed",
                        "observation_ids": ["obs-003"],
                        "limitations": [],
                    }
                ],
            },
        ]
    )
    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_QueryAwareObservedToolExecutor(),
    ).discover(
        replace(
            _request(tmp_path),
            natural_language_request="Find a current mechanism for surface movement.",
            require_actual_planning=True,
        )
    )

    assert [action["tool"] for action in result.actions] == [
        "search_dotnet_metadata",
        "search_dotnet_metadata",
        "inspect_method_il",
    ]
    assert result.actions[2]["arguments"] == {"candidate_ref": "candidate_obs_002"}
    assert result.pack.budget_summary["tool_calls_used"] == 3


def test_phase_2_nonzero_irrelevant_metadata_can_use_same_question_alternate_then_il(
    tmp_path: Path,
) -> None:
    evidence_need = "Which current managed method exposes the status transition?"
    plan = _actual_plan(
        behavior_goal="Find a current status-transition observation point.",
        queries=["status"],
        evidence_need=evidence_need,
    )
    search_plan = plan["search_plan"]
    assert isinstance(search_plan, dict)
    search_plan["query_families"].append(
        {
            "family_id": "alternate-transition-vocabulary",
            "queries": ["transition"],
            "evidence_need": evidence_need,
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-primary"],
        }
    )
    finish = _finish_after_observed_il()
    finish["evidence_conclusions"][0]["observation_ids"] = ["obs-003"]
    model = _ScriptedModel(
        [
            plan,
            _family_selection("request-derived-behavior"),
            _family_selection("alternate-transition-vocabulary"),
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_002"},
                "evidence_need": "Verify the method returned by the alternate family.",
                "derived_from_observation_ids": ["obs-002"],
            },
            finish,
        ]
    )

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(
        replace(
            _request(tmp_path),
            natural_language_request=(
                "When a temporary status transition starts, record the observation point."
            ),
            require_actual_planning=True,
            max_model_steps=4,
        )
    )

    assert [action["tool"] for action in result.actions] == [
        "search_dotnet_metadata",
        "search_dotnet_metadata",
        "inspect_method_il",
    ]
    assert result.actions[1]["query_family_id"] == (
        "alternate-transition-vocabulary"
    )
    assert result.actions[1]["derived_from_observation_ids"] == ["obs-001"]
    assert result.actions[2]["arguments"] == {
        "candidate_ref": "candidate_obs_002"
    }
    assert result.pack.budget_summary["tool_calls_used"] == 3


def test_phase_2_terminal_supplemental_method_stays_unverified_and_blocked(
    tmp_path: Path,
) -> None:
    evidence_need = "Which current managed methods expose the behavior and its guard?"
    plan = _actual_plan(
        behavior_goal="Find an observation point and its current guard.",
        queries=["movement"],
        evidence_need=evidence_need,
    )
    search_plan = plan["search_plan"]
    assert isinstance(search_plan, dict)
    families = search_plan["query_families"]
    assert isinstance(families, list)
    families.append(
        {
            "family_id": "planned-guard-search",
            "queries": ["guard"],
            "evidence_need": "Find the frozen guard metadata family.",
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-primary"],
        }
    )
    model = _ScriptedModel(
        [
            plan,
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("movement"),
                "evidence_need": evidence_need,
                "derived_from_observation_ids": [],
            },
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Verify the first observed method.",
                "derived_from_observation_ids": ["obs-001"],
            },
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("guard"),
                "evidence_need": "Find the frozen guard metadata family.",
                "derived_from_observation_ids": ["obs-002"],
            },
            {
                "action": "finish",
                "decision": "sufficient_for_proposal",
                "evidence_conclusions": [
                    {
                        "claim": "Observed inspected symbol: Observed.Type.Move.",
                        "claim_status": "observed",
                        "observation_ids": ["obs-002"],
                        "limitations": [],
                        "requirement_ids": ["req-primary"],
                        "relationship": "support",
                    }
                ],
                "unresolved_questions": [],
                "missing_capabilities": [],
            },
        ]
    )

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(
        replace(
            _request(tmp_path),
            natural_language_request="Find a behavior observation point and its guard.",
            require_actual_planning=True,
        )
    )

    assert [action["tool"] for action in result.actions] == [
        "search_dotnet_metadata",
        "inspect_method_il",
        "search_dotnet_metadata",
    ]
    assert len(result.pack.items) == 1
    assert result.pack.can_generate_patch is False
    assert result.pack.readiness == "insufficient"
    assert result.pack.unresolved_questions == (
        "Tool budget ended with metadata method references that did not receive exact IL verification: candidate_obs_003",
    )


def test_phase_2_negative_il_can_select_frozen_followup_and_verify_latest_method(
    tmp_path: Path,
) -> None:
    evidence_need = "Which current method exposes the requested transition?"
    plan = _actual_plan(
        behavior_goal="Find a current transition observation point.",
        queries=["input"],
        evidence_need=evidence_need,
    )
    _add_secondary_planning_question(plan)
    early_finish = _finish_after_observed_il()
    early_finish["unresolved_questions"] = [
        "WHICH CURRENT METHOD EXPOSES THE DOWNSTREAM INTEGRATION BOUNDARY?"
    ]
    finish = _finish_after_observed_il()
    finish["evidence_conclusions"][0]["observation_ids"] = ["obs-004"]
    model = _ScriptedModel(
        [
            plan,
            _family_selection("request-derived-behavior"),
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Verify whether the input-side method closes the focus.",
                "derived_from_observation_ids": ["obs-001"],
            },
            early_finish,
            _family_selection("secondary-integration"),
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_003"},
                "evidence_need": "Verify the method returned by the frozen follow-up.",
                "derived_from_observation_ids": ["obs-003"],
            },
            finish,
        ]
    )

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(
        replace(
            _request(tmp_path),
            natural_language_request=(
                "When an input transition occurs, observe its downstream state change."
            ),
            require_actual_planning=True,
            max_tool_calls=4,
            max_model_steps=6,
        )
    )

    assert [action["tool"] for action in result.actions] == [
        "search_dotnet_metadata",
        "inspect_method_il",
        "search_dotnet_metadata",
        "inspect_method_il",
    ]
    assert result.actions[2]["query_family_id"] == "secondary-integration"
    assert result.actions[2]["derived_from_observation_ids"] == ["obs-002"]
    assert result.actions[3]["derived_from_observation_ids"] == ["obs-003"]
    assert result.pack.budget_summary["tool_calls_used"] == 4
    assert result.pack.model_action_trace[2]["status"] == "rejected"
    assert result.pack.model_action_trace[2]["validation_error"] == (
        "OPEN_REQUIREMENT_FOLLOWUP_REQUIRED"
    )
    followup_budget_state = next(
        item["content"]
        for item in model.calls[4]
        if isinstance(item.get("content"), dict)
        and item["content"].get("message_type") == "budget_state"
    )
    assert followup_budget_state["available_unexecuted_query_families"] == [
        {
            "family_id": "secondary-integration",
            "queries": ["integration"],
            "evidence_need": (
                "Which current method exposes the downstream integration boundary?"
            ),
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-secondary"],
        }
    ]
    followup_correction = next(
        item["content"]
        for item in model.calls[4]
        if isinstance(item.get("content"), dict)
        and item["content"].get("message_type")
        == "tool_action_validation_error"
    )
    assert followup_correction["finish_allowed"] is False
    assert followup_correction["allowed_unexecuted_query_families"] == (
        followup_budget_state["available_unexecuted_query_families"]
    )



def test_phase_2_second_zero_method_search_rejects_third_metadata(
    tmp_path: Path,
) -> None:
    class _AlwaysZeroMetadataExecutor(_ObservedToolExecutor):
        def execute(self, **kwargs) -> ToolObservation:
            action = kwargs["action"]
            source = kwargs["source"]
            observation_id = kwargs["observation_id"]
            self.actions.append(action)
            return ToolObservation(
                observation_id=observation_id,
                tool="search_dotnet_metadata",
                source_id=source.source_id,
                summary="The bounded literal metadata search returned no methods.",
                data={"methods": [], "types": [], "fields": []},
            )

    evidence_need = "Which current managed method exposes movement?"
    plan = _actual_plan(
        behavior_goal="Find a current movement method.",
        queries=["surface movement"],
        evidence_need=evidence_need,
    )
    search_plan = plan["search_plan"]
    assert isinstance(search_plan, dict)
    families = search_plan["query_families"]
    assert isinstance(families, list)
    families.extend(
        [
            {
                "family_id": "alternate-movement",
                "queries": ["locomotion"],
                "evidence_need": evidence_need,
                "source_ids": ["current-interop"],
                "tool": "search_dotnet_metadata",
                "question_ids": ["question-primary"],
            },
            {
                "family_id": "forbidden-third-movement",
                "queries": ["path move"],
                "evidence_need": evidence_need,
                "source_ids": ["current-interop"],
                "tool": "search_dotnet_metadata",
                "question_ids": ["question-primary"],
            },
        ]
    )
    model = _ScriptedModel(
        [
            plan,
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("surface movement"),
                "evidence_need": evidence_need,
                "derived_from_observation_ids": [],
            },
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("locomotion"),
                "evidence_need": evidence_need,
                "derived_from_observation_ids": ["obs-001"],
            },
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("path move"),
                "evidence_need": evidence_need,
                "derived_from_observation_ids": ["obs-002"],
            },
        ]
    )
    executor = _AlwaysZeroMetadataExecutor()
    specialist = EvidenceDiscoverySpecialist(model=model, tool_executor=executor)

    with pytest.raises(
        ValueError,
        match="SECOND_METADATA_SEARCH_EXHAUSTED_WITHOUT_METHOD",
    ):
        specialist.discover(
            replace(
                _request(tmp_path),
                natural_language_request="Find a current movement method.",
                require_actual_planning=True,
            )
        )

    assert len(executor.actions) == 2
    assert specialist.runtime_diagnostics["failure_stage"] == "action_validation"


def test_phase_2_second_nonzero_metadata_requires_observation_bound_il(
    tmp_path: Path,
) -> None:
    evidence_need = "Which current managed method exposes the status transition?"
    plan = _actual_plan(
        behavior_goal="Find a current status-transition observation point.",
        queries=["status"],
        evidence_need=evidence_need,
    )
    search_plan = plan["search_plan"]
    assert isinstance(search_plan, dict)
    search_plan["query_families"].extend(
        [
            {
                "family_id": "alternate-transition",
                "queries": ["transition"],
                "evidence_need": evidence_need,
                "source_ids": ["current-interop"],
                "tool": "search_dotnet_metadata",
                "question_ids": ["question-primary"],
            },
            {
                "family_id": "forbidden-third-family",
                "queries": ["activate"],
                "evidence_need": evidence_need,
                "source_ids": ["current-interop"],
                "tool": "search_dotnet_metadata",
                "question_ids": ["question-primary"],
            },
        ]
    )
    model = _ScriptedModel(
        [
            plan,
            _family_selection("request-derived-behavior"),
            _family_selection(
                "alternate-transition",
                derived_from_observation_ids=["obs-001"],
            ),
            _family_selection(
                "forbidden-third-family",
                derived_from_observation_ids=["obs-002"],
            ),
        ]
    )
    executor = _ObservedToolExecutor()
    specialist = EvidenceDiscoverySpecialist(model=model, tool_executor=executor)

    with pytest.raises(
        ValueError,
        match="SECOND_METADATA_SEARCH_REQUIRES_IDENTITY_VERIFICATION",
    ):
        specialist.discover(
            replace(
                _request(tmp_path),
                natural_language_request=(
                    "When a temporary status transition starts, record its observation point."
                ),
                require_actual_planning=True,
            )
        )

    assert [action["tool"] for action in executor.actions] == [
        "search_dotnet_metadata",
        "search_dotnet_metadata",
    ]
    assert specialist.runtime_diagnostics["failure_stage"] == "action_validation"
    assert [
        observation["observation_id"]
        for observation in specialist.completed_observations
    ] == ["obs-001", "obs-002"]
    assert all(
        observation["tool"] == "search_dotnet_metadata"
        for observation in specialist.completed_observations
    )


def test_phase_2_second_metadata_il_rejects_first_observation_reference(
    tmp_path: Path,
) -> None:
    evidence_need = "Which current managed method exposes the status transition?"
    plan = _actual_plan(
        behavior_goal="Find a current status-transition observation point.",
        queries=["status"],
        evidence_need=evidence_need,
    )
    search_plan = plan["search_plan"]
    assert isinstance(search_plan, dict)
    search_plan["query_families"].append(
        {
            "family_id": "alternate-transition",
            "queries": ["transition"],
            "evidence_need": evidence_need,
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-primary"],
        }
    )
    model = _ScriptedModel(
        [
            plan,
            _family_selection("request-derived-behavior"),
            _family_selection(
                "alternate-transition",
                derived_from_observation_ids=["obs-001"],
            ),
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Verify the method from the first metadata observation.",
                "derived_from_observation_ids": ["obs-001"],
            },
        ]
    )
    executor = _ObservedToolExecutor()
    specialist = EvidenceDiscoverySpecialist(model=model, tool_executor=executor)

    with pytest.raises(
        ValueError,
        match="SECOND_METADATA_IL_MUST_BIND_LATEST_OBSERVATION",
    ):
        specialist.discover(
            replace(
                _request(tmp_path),
                natural_language_request=(
                    "When a temporary status transition starts, record its observation point."
                ),
                require_actual_planning=True,
            )
        )

    assert [action["tool"] for action in executor.actions] == [
        "search_dotnet_metadata",
        "search_dotnet_metadata",
    ]
    assert specialist.runtime_diagnostics["failure_stage"] == "action_validation"


def test_actual_zero_result_correction_replays_only_unexecuted_frozen_family(
    tmp_path: Path,
) -> None:
    class _ZeroMetadataExecutor(_ObservedToolExecutor):
        def execute(self, **kwargs) -> ToolObservation:
            action = kwargs["action"]
            source = kwargs["source"]
            self.actions.append(action)
            return ToolObservation(
                observation_id=kwargs["observation_id"],
                tool="search_dotnet_metadata",
                source_id=source.source_id,
                summary="No methods matched the frozen family.",
                data={"methods": [], "types": [], "fields": []},
            )

    evidence_need = "Which current method exposes movement?"
    plan = _actual_plan(
        behavior_goal="Find a current movement method.",
        queries=["surface movement"],
        evidence_need=evidence_need,
    )
    plan["search_plan"]["query_families"].append(
        {
            "family_id": "alternate-movement",
            "queries": ["locomotion"],
            "evidence_need": "Find the alternate frozen movement family.",
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-primary"],
        }
    )
    plan["requirement_projection"]["planning_blocking_questions"].append(
        {
            "requirement_id": "req-output",
            "question": "Which current method renders a downstream output?",
        }
    )
    plan["search_plan"]["engineering_questions"].append(
        {
            "question_id": "question-output",
            "question": "Which current method renders a downstream output?",
            "requirement_ids": ["req-output"],
        }
    )
    plan["search_plan"]["planned_lanes"].append(
        {
            "lane": "downstream-output-search",
            "tool": "search_dotnet_metadata",
            "source_ids": ["current-interop"],
            "question_ids": ["question-output"],
        }
    )
    plan["search_plan"]["query_families"].append(
        {
            "family_id": "unrelated-output-family",
            "queries": ["overlay"],
            "evidence_need": "Find downstream output metadata.",
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-output"],
        }
    )
    open_finish = {
        "action": "finish",
        "decision": "needs_more_evidence",
        "evidence_conclusions": [],
        "unresolved_questions": ["No method identity has been observed."],
        "missing_capabilities": [],
    }
    model = _ScriptedModel(
        [
            plan,
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("surface movement"),
                "evidence_need": evidence_need,
                "derived_from_observation_ids": [],
            },
            open_finish,
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("locomotion"),
                "evidence_need": "Find the alternate frozen movement family.",
                "derived_from_observation_ids": ["obs-001"],
            },
            open_finish,
        ]
    )

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ZeroMetadataExecutor(),
    ).discover(replace(_request(tmp_path), require_actual_planning=True))

    correction = model.calls[3][-2]["content"]
    assert correction["allowed_unexecuted_query_families"] == [
        plan["search_plan"]["query_families"][1]
    ]
    assert result.run_status == "completed"


def test_actual_zero_result_without_frozen_alternate_can_stop(
    tmp_path: Path,
) -> None:
    class _ZeroMetadataExecutor(_ObservedToolExecutor):
        def execute(self, **kwargs: object) -> ToolObservation:
            action = kwargs["action"]
            source = kwargs["source"]
            observation_id = kwargs["observation_id"]
            assert isinstance(action, dict)
            assert isinstance(source, EvidenceDiscoverySource)
            assert isinstance(observation_id, str)
            self.actions.append(action)
            return ToolObservation(
                observation_id=observation_id,
                tool="search_dotnet_metadata",
                source_id=source.source_id,
                summary="No managed symbol matched the frozen family.",
                data={"methods": [], "types": [], "fields": []},
            )

    plan = _actual_plan(
        behavior_goal="Find a current status observation point.",
        queries=["status"],
        evidence_need="Which current method exposes the status transition?",
    )
    model = _ScriptedModel(
        [
            plan,
            _family_selection("request-derived-behavior"),
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [
                    {
                        "claim": "The frozen metadata family did not expose a method identity.",
                        "claim_status": "unknown",
                        "observation_ids": [],
                        "limitations": [
                            "No additional family was frozen for the same engineering question."
                        ],
                        "requirement_ids": ["req-primary"],
                        "relationship": "missing",
                    }
                ],
                "unresolved_questions": [
                    "The current status-transition method identity remains unresolved."
                ],
                "missing_capabilities": [],
            },
        ]
    )
    executor = _ZeroMetadataExecutor()

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=executor,
    ).discover(
        replace(
            _request(tmp_path),
            natural_language_request="Record when a temporary status begins.",
            require_actual_planning=True,
        )
    )

    assert len(executor.actions) == 1
    assert result.run_status == "completed"
    assert result.pack.readiness == "insufficient"
    assert [item["status"] for item in result.pack.model_action_trace] == [
        "accepted",
        "accepted",
    ]
    assert all(
        not (
            isinstance(message.get("content"), dict)
            and message["content"].get("error_code")
            == "ZERO_RESULT_RECOVERY_REQUIRED"
        )
        for call in model.calls
        for message in call
    )


def test_phase_2_executed_family_gets_one_correction_to_unexecuted_family(
    tmp_path: Path,
) -> None:
    class _SecondMetadataZeroExecutor(_ObservedToolExecutor):
        def __init__(self) -> None:
            super().__init__()
            self.metadata_calls = 0

        def execute(self, **kwargs) -> ToolObservation:
            action = kwargs["action"]
            if action["tool"] != "search_dotnet_metadata":
                return super().execute(**kwargs)
            self.metadata_calls += 1
            if self.metadata_calls == 1:
                return super().execute(**kwargs)
            source = kwargs["source"]
            observation_id = kwargs["observation_id"]
            self.actions.append(action)
            return ToolObservation(
                observation_id=observation_id,
                tool="search_dotnet_metadata",
                source_id=source.source_id,
                summary="The alternate frozen family returned no methods.",
                data={"methods": [], "types": [], "fields": []},
            )

    evidence_need = "Which current managed method exposes movement?"
    plan = _actual_plan(
        behavior_goal="Find and verify a current movement method.",
        queries=["movement"],
        evidence_need=evidence_need,
    )
    plan["search_plan"]["query_families"].append(
        {
            "family_id": "guard-family",
            "queries": ["guard"],
            "evidence_need": evidence_need,
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-primary"],
        }
    )
    model = _ScriptedModel(
        [
            plan,
            _family_selection("request-derived-behavior"),
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Verify the observed movement method.",
                "derived_from_observation_ids": ["obs-001"],
            },
            _family_selection("request-derived-behavior"),
            _family_selection("guard-family"),
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [],
                "unresolved_questions": [evidence_need],
                "missing_capabilities": [
                    "No additional current managed method was observed."
                ],
            },
        ]
    )
    executor = _SecondMetadataZeroExecutor()
    specialist = EvidenceDiscoverySpecialist(model=model, tool_executor=executor)

    result = specialist.discover(
        replace(
            _request(tmp_path),
            natural_language_request="Find and verify a current movement method.",
            require_actual_planning=True,
            max_tool_calls=3,
            max_model_steps=5,
        )
    )

    assert [action.get("query_family_id") for action in result.actions] == [
        "request-derived-behavior",
        None,
        "guard-family",
    ]
    rejected = next(
        attempt
        for attempt in result.pack.model_action_trace
        if attempt.get("validation_error") == "QUERY_FAMILY_ALREADY_EXECUTED"
    )
    assert rejected["status"] == "rejected"
    correction = next(
        message["content"]
        for message in model.calls[4]
        if isinstance(message.get("content"), dict)
        and message["content"].get("error_code")
        == "QUERY_FAMILY_ALREADY_EXECUTED"
    )
    assert correction["allowed_unexecuted_query_families"] == [
        plan["search_plan"]["query_families"][1]
    ]


def test_phase_2_executed_family_repeated_after_correction_stops(
    tmp_path: Path,
) -> None:
    evidence_need = "Which current managed method exposes movement?"
    plan = _actual_plan(
        behavior_goal="Find and verify a current movement method.",
        queries=["movement"],
        evidence_need=evidence_need,
    )
    plan["search_plan"]["query_families"].append(
        {
            "family_id": "guard-family",
            "queries": ["guard"],
            "evidence_need": evidence_need,
            "source_ids": ["current-interop"],
            "tool": "search_dotnet_metadata",
            "question_ids": ["question-primary"],
        }
    )
    repeated = _family_selection("request-derived-behavior")
    model = _ScriptedModel([plan, repeated, repeated, repeated])
    executor = _ObservedToolExecutor()

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=executor,
    ).discover(
        replace(
            _request(tmp_path),
            require_actual_planning=True,
            max_tool_calls=3,
            max_model_steps=3,
        )
    )

    assert len(executor.actions) == 1
    assert result.run_status == "budget_exhausted"
    assert [
        attempt.get("validation_error")
        for attempt in result.pack.model_action_trace
        if attempt["status"] == "rejected"
    ] == ["QUERY_FAMILY_ALREADY_EXECUTED", "QUERY_FAMILY_ALREADY_EXECUTED"]


def test_phase_2_type_and_field_hits_do_not_enable_exact_il(
    tmp_path: Path,
) -> None:
    class _TypeFieldOnlyExecutor(_ObservedToolExecutor):
        def execute(self, **kwargs) -> ToolObservation:
            action = kwargs["action"]
            source = kwargs["source"]
            observation_id = kwargs["observation_id"]
            self.actions.append(action)
            return ToolObservation(
                observation_id=observation_id,
                tool="search_dotnet_metadata",
                source_id=source.source_id,
                summary="Only type and field investigation leads were observed.",
                data={
                    "methods": [],
                    "types": [{"symbol": "Observed.Type"}],
                    "fields": [{"symbol": "Observed.Type.Speed"}],
                },
            )

    evidence_need = "Which current managed method exposes movement?"
    plan = _actual_plan(
        behavior_goal="Find a movement method.",
        queries=["movement"],
        evidence_need=evidence_need,
    )
    model = _ScriptedModel(
        [
            plan,
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("movement"),
                "evidence_need": evidence_need,
                "derived_from_observation_ids": [],
            },
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "type_or_field_is_not_a_method_ref"},
                "evidence_need": "Attempt exact verification.",
                "derived_from_observation_ids": ["obs-001"],
            },
        ]
    )
    specialist = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_TypeFieldOnlyExecutor(),
    )

    with pytest.raises(ValueError, match="UNVERIFIED_CANDIDATE_REFERENCE"):
        specialist.discover(
            replace(
                _request(tmp_path),
                natural_language_request="Find a current movement method.",
                require_actual_planning=True,
            )
        )

    assert specialist.runtime_diagnostics["failure_stage"] == "action_validation"


@pytest.mark.parametrize(
    ("planning_status", "search_plan", "expected_status"),
    (
        ("requirement_projection_insufficient", None, "requirement_projection_insufficient"),
        (
            "search_planning_insufficient",
            {
                "schema_version": "hook_discovery_search_plan_v2",
                "engineering_questions": [],
                "source_roles": [],
                "planned_lanes": [],
                "query_families": [],
                "initial_stop_condition": "Stop because no valid literal query exists.",
                "initial_expand_condition": "Do not expand without a meaningful engineering question.",
            },
            "search_planning_insufficient",
        ),
    ),
)
def test_phase_2_planning_failures_stop_before_tool_execution(
    tmp_path: Path,
    planning_status: str,
    search_plan: dict[str, object] | None,
    expected_status: str,
) -> None:
    projection = _actual_plan(
        behavior_goal="A bounded behavior goal.",
        queries=["bounded behavior"],
        evidence_need="Which current managed method exposes the behavior?",
    )["requirement_projection"]
    assert isinstance(projection, dict)
    if planning_status == "requirement_projection_insufficient":
        projection = {**projection, "behavior_goal": "", "planning_blocking_questions": []}
    model = _ScriptedModel([
        {
            "action": "plan",
            "planning_status": planning_status,
            "requirement_projection": projection,
            "search_plan": search_plan,
        }
    ])
    executor = _ObservedToolExecutor()
    result = EvidenceDiscoverySpecialist(model=model, tool_executor=executor).discover(
        replace(_request(tmp_path), natural_language_request="Do something.", require_actual_planning=True)
    )

    assert result.run_status == expected_status
    assert result.pack.readiness == "insufficient"
    assert result.actions == ()
    assert result.observations == ()
    assert executor.actions == []
    payload = result.pack.to_artifact_payload()
    assert "hook_discovery" not in payload
    assert payload["agent_discovery"]["planning_status"] == planning_status
    assert payload["provenance_validation"]["run_id"] == (
        "run-wallcrawler-intelligent-evidence-test"
    )
    assert payload["provenance_validation"]["request_id"] == (
        "wallcrawler-intelligent-evidence-test"
    )
    assert payload["provenance_validation"]["model_disclosure"] == {
        "approved": False,
        "reason": "Injected local/test model; no external disclosure occurred.",
    }
    assert payload["model_identity"] == {
        "execution_kind": "injected_local_or_test",
        "provider": None,
        "model": None,
    }
    assert EvidencePack.from_artifact_payload(payload).to_artifact_payload() == payload

    store = ArtifactStore(tmp_path / f"early-termination-{planning_status}")
    feature_id = f"feature-{planning_status}"
    feature_ref = store.write(
        feature_id=feature_id,
        artifact_type="feature_spec",
        payload=_strict_roundtrip_feature_payload(feature_id),
    )
    evidence_ref = store.write(
        feature_id=feature_id,
        artifact_type="evidence_pack",
        payload=payload,
        upstream_refs=[feature_ref],
    )
    committed = store.read(evidence_ref)["data"]
    assert EvidencePack.from_artifact_payload(committed).to_artifact_payload() == payload


def test_phase_2c_agent_only_early_termination_prompt_versions_are_closed() -> None:
    projection = _actual_plan(
        behavior_goal="A bounded behavior goal.",
        queries=["bounded behavior"],
        evidence_need="Which current managed method exposes the behavior?",
    )["requirement_projection"]
    assert isinstance(projection, dict)
    projection = {
        **projection,
        "behavior_goal": "",
        "planning_blocking_questions": [],
    }
    result = EvidenceDiscoverySpecialist(
        model=_ScriptedModel(
            [
                {
                    "action": "plan",
                    "planning_status": "requirement_projection_insufficient",
                    "requirement_projection": projection,
                    "search_plan": None,
                }
            ]
        ),
        tool_executor=_ObservedToolExecutor(),
    ).discover(
        replace(
            _request(Path(".")),
            natural_language_request="Do something.",
            require_actual_planning=True,
        )
    )
    payload = result.pack.to_artifact_payload()

    for version in (
        "agent_evidence_discovery_prompt_v2",
        "agent_evidence_discovery_prompt_v3",
        "agent_evidence_discovery_prompt_v4",
        "agent_evidence_discovery_prompt_v5",
        "agent_evidence_discovery_prompt_v6",
        "agent_evidence_discovery_prompt_v7",
    ):
        versioned = deepcopy(payload)
        versioned["prompt_contract"]["version"] = version
        assert EvidencePack.from_artifact_payload(versioned).to_artifact_payload() == versioned

    for version in (
        "agent_evidence_discovery_prompt_v1",
        "agent_evidence_discovery_prompt_v9",
    ):
        versioned = deepcopy(payload)
        versioned["prompt_contract"]["version"] = version
        with pytest.raises(
            ValueError,
            match="EVIDENCE_PACK_EARLY_TERMINATION_PROMPT_BINDING_INVALID",
        ):
            EvidencePack.from_artifact_payload(versioned)


@pytest.mark.parametrize(
    "mutation",
    [
        "agent_version",
        "agent_extra_field",
        "agent_hash",
        "top_readiness",
        "top_can_generate_patch",
        "run_status",
        "execution_trace",
        "hook_segment",
    ],
)
def test_phase_2c_agent_only_early_termination_tampering_fails_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    projection = _actual_plan(
        behavior_goal="A bounded behavior goal.",
        queries=["bounded behavior"],
        evidence_need="Which current managed method exposes the behavior?",
    )["requirement_projection"]
    assert isinstance(projection, dict)
    projection = {
        **projection,
        "behavior_goal": "",
        "planning_blocking_questions": [],
    }
    result = EvidenceDiscoverySpecialist(
        model=_ScriptedModel(
            [{
                "action": "plan",
                "planning_status": "requirement_projection_insufficient",
                "requirement_projection": projection,
                "search_plan": None,
            }]
        ),
        tool_executor=_ObservedToolExecutor(),
    ).discover(
        replace(
            _request(tmp_path),
            natural_language_request="Do something.",
            require_actual_planning=True,
        )
    )
    payload = deepcopy(result.pack.to_artifact_payload())
    if mutation == "agent_version":
        payload["agent_discovery"]["schema_version"] = "agent_evidence_discovery_actual_v1"
    elif mutation == "agent_extra_field":
        payload["agent_discovery"]["unexpected"] = True
    elif mutation == "agent_hash":
        payload["prompt_contract"]["agent_discovery_sha256"] = "0" * 64
    elif mutation == "top_readiness":
        payload["readiness"] = "partial"
    elif mutation == "top_can_generate_patch":
        payload["can_generate_patch"] = True
        payload["authoritative_for_patch"] = True
    elif mutation == "run_status":
        payload["run_status"] = "completed"
    elif mutation == "execution_trace":
        payload["trace_refs"] = ["obs-001"]
    elif mutation == "hook_segment":
        payload["hook_discovery"] = {}
    else:  # pragma: no cover - parametrization is closed above
        raise AssertionError(mutation)

    with pytest.raises(ArtifactRegistryError, match="Invalid semantic EvidencePack"):
        ArtifactTypeRegistry().validate_write(
            artifact_type="evidence_pack",
            status="success",
            payload=payload,
        )


def test_actual_planning_required_is_request_configuration_not_semantic_proof() -> None:
    payload = EvidencePack.empty(
        query="Legacy diagnostic with requested planning.",
        reason="No semantic section was frozen.",
    ).to_artifact_payload()
    payload["prompt_contract"] = {
        "actual_planning_required": True,
        "agent_discovery_sha256": None,
    }

    assert EvidencePack.requires_strict_semantic_rehydrate(payload) is False
    ArtifactTypeRegistry().validate_write(
        artifact_type="evidence_pack",
        status="success",
        payload=payload,
    )


def test_actual_planning_schema_exposes_exact_nested_versions_to_real_models() -> None:
    schema = evidence_discovery_planning_schema()
    properties = schema["properties"]

    assert properties["requirement_projection"]["properties"]["schema_version"] == {
        "type": "string",
        "const": REQUIREMENT_PROJECTION_SCHEMA_VERSION,
    }
    assert properties["search_plan"]["properties"]["schema_version"] == {
        "type": "string",
        "const": SEARCH_PLAN_SCHEMA_VERSION,
    }
    focus_schema = properties["search_plan"]["properties"][
        "initial_focus_question_id"
    ]
    assert focus_schema["type"] == ["string", "null"]
    assert focus_schema["minLength"] == 1
    assert "first bounded Discovery focus" in focus_schema["description"]
    assert "initial_focus_question_id" in properties["search_plan"]["required"]
    requirement_description = properties["requirement_projection"]["properties"][
        "planning_blocking_questions"
    ]["description"]
    family_question_description = properties["search_plan"]["properties"][
        "query_families"
    ]["items"]["properties"]["question_ids"]["description"]
    family_query_description = properties["search_plan"]["properties"][
        "query_families"
    ]["items"]["properties"]["queries"]["description"]
    deferred_description = properties["requirement_projection"]["properties"][
        "deferred_planning_or_runtime_questions"
    ]["description"]
    assert "authorized actual evidence" in requirement_description
    assert "not user ambiguity" in requirement_description
    assert "Only question_id values declared" in family_question_description
    assert "OR union" in family_query_description
    assert "broad term expands" in family_query_description
    assert "space-separated behavioral sentences" in family_query_description
    assert "event deduplication" in deferred_description
    assert "final Runtime correctness" in deferred_description


def test_actual_planning_prompt_keeps_scope_without_global_alternate_requirement(
    tmp_path: Path,
) -> None:
    plan = _actual_plan(
        behavior_goal="Find a current status-transition observation point.",
        queries=["status"],
        evidence_need="Which current method exposes the status transition?",
    )
    model = _ScriptedModel(
        [
            plan,
            _family_selection("request-derived-behavior"),
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Verify the observed method.",
                "derived_from_observation_ids": ["obs-001"],
            },
            _finish_after_observed_il(),
        ]
    )

    EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(
        replace(
            _request(tmp_path),
            natural_language_request=(
                "When a temporary status transition starts, record its observation point."
            ),
            require_actual_planning=True,
            max_tool_calls=2,
            max_model_steps=3,
        )
    )

    planning_request = model.calls[0][-1]["content"]
    rules = planning_request["rules"]
    serialized = json.dumps(rules, ensure_ascii=False)
    assert "at least one engineering requirement" in serialized
    assert "observable event or state X" in serialized
    assert "stated actor, input, and target relate to X" in serialized
    assert "implementing Y is not a planning blocker" in serialized
    assert "Deterministic code assigns stable identities" in serialized
    assert "one vocabulary-distinct alternate family" not in serialized
    assert "not a universal Search Plan schema minimum" not in serialized
    assert "requirement_id" not in serialized
    assert "ActivateState" not in serialized
    assert "expected_control_action" not in serialized

    execution_instruction = next(
        message["content"]["instruction"]
        for message in model.calls[1]
        if isinstance(message.get("content"), dict)
        and message["content"].get("message_type") == "execute_frozen_plan"
    )
    assert "only if the frozen plan already contains" in execution_instruction
    assert "include initial_focus_question_id" in execution_instruction
    assert "otherwise stop without inventing or rewriting a family_id" in (
        execution_instruction
    )


def test_actual_planning_schema_aligns_direct_nonempty_validator_constraints() -> None:
    schema = evidence_discovery_planning_schema()
    projection = schema["properties"]["requirement_projection"]
    search_plan = schema["properties"]["search_plan"]
    requirement_item = projection["properties"]["planning_blocking_questions"][
        "items"
    ]
    engineering_item = search_plan["properties"]["engineering_questions"][
        "items"
    ]
    lane_item = search_plan["properties"]["planned_lanes"]["items"]
    family_item = search_plan["properties"]["query_families"]["items"]

    assert requirement_item["properties"]["requirement_id"]["minLength"] == 1
    assert requirement_item["properties"]["question"]["minLength"] == 1
    assert engineering_item["properties"]["question_id"]["minLength"] == 1
    assert engineering_item["properties"]["requirement_ids"]["minItems"] == 1
    assert "question_ids" in lane_item["required"]
    assert lane_item["properties"]["question_ids"]["minItems"] == 1
    assert family_item["properties"]["family_id"]["minLength"] == 1
    assert family_item["properties"]["queries"]["minItems"] == 1
    assert family_item["properties"]["source_ids"]["minItems"] == 1
    assert family_item["properties"]["question_ids"]["minItems"] == 1
    assert search_plan["properties"]["initial_focus_question_id"]["minLength"] == 1


def test_declared_ready_empty_search_plan_is_normalized_to_bounded_stop(
    tmp_path: Path,
) -> None:
    declared_ready = _actual_plan(
        behavior_goal="Find a current status transition observation point.",
        queries=["status", "transition"],
        evidence_need="Which current method exposes the status transition?",
    )
    declared_ready["search_plan"]["engineering_questions"] = []
    declared_ready["search_plan"]["planned_lanes"] = []
    declared_ready["search_plan"]["query_families"] = []
    declared_ready["search_plan"]["initial_focus_question_id"] = None
    executor = _ObservedToolExecutor()

    result = EvidenceDiscoverySpecialist(
        model=_ScriptedModel([declared_ready]),
        tool_executor=executor,
    ).discover(replace(_request(tmp_path), require_actual_planning=True))

    assert result.run_status == "search_planning_insufficient"
    assert result.agent_discovery is not None
    assert result.agent_discovery["planning_status"] == "search_planning_insufficient"
    assert result.actions == ()
    assert result.observations == ()
    assert executor.actions == []


def test_requirement_projection_and_search_plan_use_bounded_schema_views(
    tmp_path: Path,
) -> None:
    full_plan = _actual_plan(
        behavior_goal="Find a current status transition observation point.",
        queries=["status", "transition"],
        evidence_need="Which current method exposes the status transition?",
    )
    projection_response = {
        "action": "project_requirements",
        "planning_status": "ready",
        "requirement_projection": {
            key: deepcopy(value)
            for key, value in full_plan["requirement_projection"].items()
            if key != "schema_version"
        },
    }
    projection_response["requirement_projection"]["planning_blocking_questions"] = [
        item["question"]
        for item in full_plan["requirement_projection"][
            "planning_blocking_questions"
        ]
    ]
    projection_response["requirement_projection"]["relation_definitions"] = [
        {
            "parent_requirement_indexes": [1],
            "meaning": "Authentication completion observation identity.",
            "investigation_question": "Which observation establishes completion?",
        }
    ]
    search_response = {
        "action": "plan_search",
        "planning_status": "search_planning_insufficient",
        "search_plan": None,
    }

    class _PlanningClient:
        provider = "test_agent_turn"
        model = "test-agent-model"

        def __init__(self) -> None:
            self.requests = []
            self.responses = [projection_response, search_response]

        def complete_turn(self, request):
            self.requests.append(request)
            return AgentTurnResponse(
                provider=self.provider,
                model=self.model,
                content=json.dumps(self.responses.pop(0)),
                tool_calls=(),
                stop_reason="stop",
                usage=AgentUsage(input_tokens=10, output_tokens=10),
            )

    client = _PlanningClient()
    model = EvidenceDiscoveryAgentModel(
        client,
        local_execution=EvidenceDiscoveryLocalExecution(
            endpoint="http://127.0.0.1:11434",
            provider=client.provider,
            model=client.model,
        ),
    )
    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(replace(_request(tmp_path), require_actual_planning=True))

    assert result.run_status == "search_planning_insufficient"
    assert len(client.requests) == 2
    projection_format = client.requests[0].response_format
    search_format = client.requests[1].response_format
    assert projection_format is not None
    assert search_format is not None
    assert projection_format.name == "agent_evidence_requirement_projection"
    assert search_format.name == "agent_evidence_search_plan"
    assert projection_format.schema == evidence_discovery_requirement_projection_schema()
    assert search_format.schema == evidence_discovery_search_plan_schema()
    investigations = search_format.schema["properties"]["search_plan"][
        "properties"
    ]["investigations"]
    assert investigations["items"]["properties"]["query_families"]["items"][
        "properties"
    ]["queries"]["maxItems"] == 8
    assert "requirement_id" not in json.dumps(projection_format.schema)
    assert "question_id" not in json.dumps(search_format.schema)
    assert "family_id" not in json.dumps(search_format.schema)
    projection_schema_text = json.dumps(
        projection_format.schema,
        ensure_ascii=False,
    ).lower()
    assert "relation_definitions" in projection_schema_text
    assert "relation_contract" not in projection_schema_text
    for answer_field in (
        "expected_relationship",
        "expected_sufficiency",
        "expected_control_action",
        "target_symbol",
        "target_path",
        "hook_identity",
    ):
        assert answer_field not in projection_schema_text
    frozen_message = client.requests[1].messages[-1].content
    assert frozen_message["message_type"] == "frozen_requirement_projection"
    assert frozen_message["requirement_projection"]["planning_blocking_questions"] == [
        {
            "requirement_id": "requirement-001",
            "question": full_plan["requirement_projection"][
                "planning_blocking_questions"
            ][0]["question"],
        }
    ]
    relation_contract = frozen_message["requirement_projection"][
        "relation_contract"
    ]
    assert relation_contract["schema_version"] == "request_relation_identity_v1"
    assert len(relation_contract["relations"]) == 1
    assert relation_contract["relations"][0]["parent_requirement_ids"] == [
        "requirement-001"
    ]
    assert "search_plan" not in frozen_message
    planning_rules = " ".join(frozen_message["rules"])
    assert "two to four distinct code-shaped technical vocabulary variants" in (
        planning_rules
    )
    assert "These leads are not facts or authority" in planning_rules
    assert "multiple inflections of the same lexical root" in planning_rules


def _relation_projection_action(
    *,
    request: str = "Investigate two request-derived engineering requirements.",
) -> tuple[str, dict[str, object]]:
    action = {
        "action": "project_requirements",
        "planning_status": "ready",
        "requirement_projection": {
            "behavior_goal": "Investigate two bounded engineering relations.",
            "trigger": None,
            "actor": None,
            "target": None,
            "hard_constraints": [],
            "forbidden_outcomes": [],
            "implementation_hints": [],
            "acceptance_signals": [],
            "planning_blocking_questions": [
                "Which current observation establishes requirement one?",
                "Which current observation establishes requirement two?",
            ],
            "relation_definitions": [
                {
                    "parent_requirement_indexes": [1],
                    "meaning": "First independent relation for requirement one.",
                    "investigation_question": "How is relation one established?",
                },
                {
                    "parent_requirement_indexes": [1],
                    "meaning": "Second independent relation for requirement one.",
                    "investigation_question": "How is relation two established?",
                },
                {
                    "parent_requirement_indexes": [1],
                    "meaning": "Third independent relation for requirement one.",
                    "investigation_question": "How is relation three established?",
                },
                {
                    "parent_requirement_indexes": [1, 2],
                    "meaning": "One relation shared by both requirements.",
                    "investigation_question": "How is the shared relation established?",
                },
            ],
            "deferred_planning_or_runtime_questions": [],
        },
    }
    return request, action


def _projection_coverage_recovery_responses(
    request_text: str,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    evidence_question = "Which current observation establishes the transition?"
    deferred_question = "How should the final Runtime presentation appear?"
    rejected = {
        "action": "project_requirements",
        "planning_status": "ready",
        "requirement_projection": {
            "behavior_goal": request_text,
            "trigger": None,
            "actor": None,
            "target": None,
            "hard_constraints": [],
            "forbidden_outcomes": [],
            "implementation_hints": [],
            "acceptance_signals": [],
            "planning_blocking_questions": [
                evidence_question,
                deferred_question,
            ],
            "relation_definitions": [
                {
                    "parent_requirement_indexes": [1],
                    "meaning": "Current evidence establishes the transition.",
                    "investigation_question": evidence_question,
                }
            ],
            "deferred_planning_or_runtime_questions": [],
        },
    }
    corrected = deepcopy(rejected)
    corrected_projection = corrected["requirement_projection"]
    assert isinstance(corrected_projection, dict)
    corrected_projection["planning_blocking_questions"] = [evidence_question]
    corrected_projection["deferred_planning_or_runtime_questions"] = [
        deferred_question
    ]
    materialized = _parse_requirement_projection_action(
        json.dumps(corrected),
        natural_language_request=request_text,
    )["requirement_projection"]
    relation_id = str(
        materialized["relation_contract"]["relations"][0]["relation_id"]
    )
    search = {
        "action": "plan_search",
        "planning_status": "ready",
        "search_plan": {
            "investigations": [
                {
                    "engineering_question": evidence_question,
                    "initial_focus": True,
                    "source_ids": ["current-interop"],
                    "query_families": [
                        {
                            "queries": ["ObservedTransition", "TransitionState"],
                            "evidence_need": evidence_question,
                            "relation_indexes": [1],
                        }
                    ],
                }
            ],
            "initial_stop_condition": "Stop after exact transition evidence.",
            "initial_expand_condition": "Expand only from an observed gap.",
        },
    }
    finish = {
        "action": "finish",
        "decision": "needs_more_evidence",
        "evidence_conclusions": [
            {
                "claim": (
                    "Observed method body metadata for Observed.Type.Move: "
                    "metadata_token=0x06000001; rva=123; has_method_body=true; "
                    "instruction_count=1; instructions_truncated=false."
                ),
                "claim_status": "observed",
                "observation_ids": ["obs-002"],
                "limitations": [],
                "requirement_ids": ["requirement-001"],
                "relation_ids": [relation_id],
                "relationship": "support",
            }
        ],
        "unresolved_questions": ["Runtime verification remains deferred."],
        "missing_capabilities": [],
    }
    return rejected, corrected, search, finish


def test_projection_missing_coverage_allows_one_audited_recovery(
    tmp_path: Path,
) -> None:
    request_text = "Observe one transition while deferring final presentation."
    rejected, corrected, search, finish = (
        _projection_coverage_recovery_responses(request_text)
    )
    model = _ScriptedModel(
        [
            rejected,
            corrected,
            search,
            _family_selection("family-001-001"),
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Inspect the observed transition method.",
                "derived_from_observation_ids": ["obs-001"],
            },
            finish,
        ]
    )
    executor = _ObservedToolExecutor()
    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=executor,
    ).discover(
        replace(
            _request(tmp_path),
            natural_language_request=request_text,
            require_actual_planning=True,
            max_tool_calls=2,
            max_model_steps=3,
        )
    )

    attempts = result.pack.budget_summary["requirement_projection_attempts"]
    assert attempts[0] == {
        "attempt_index": 1,
        "structured_output_sha256": attempts[0]["structured_output_sha256"],
        "status": "rejected",
        "error_code": "MODEL_RELATION_REQUIREMENT_COVERAGE_INVALID",
        "requirement_count": 2,
        "relation_count": 1,
        "covered_requirement_indexes": [1],
        "missing_requirement_indexes": [2],
    }
    assert attempts[1] == {
        "attempt_index": 2,
        "structured_output_sha256": attempts[1]["structured_output_sha256"],
        "status": "accepted",
        "error_code": None,
        "requirement_count": 1,
        "relation_count": 1,
        "covered_requirement_indexes": [1],
        "missing_requirement_indexes": [],
    }
    assert attempts[0]["structured_output_sha256"] != attempts[1][
        "structured_output_sha256"
    ]
    assert result.pack.budget_summary["initial_projection_success"] is False
    assert result.pack.budget_summary["projection_recovery_attempted"] is True
    assert result.pack.budget_summary["projection_recovery_success"] is True
    assert result.pack.budget_summary["projection_attempt_count"] == 2
    assert result.pack.budget_summary["planning_model_steps_used"] == 3
    assert len(executor.actions) == 2
    correction = model.calls[1][-1]["content"]
    assert correction["message_type"] == (
        "requirement_projection_structure_correction"
    )
    assert "structured_output" not in correction
    assert correction["missing_requirement_indexes"] == [2]
    correction_text = json.dumps(correction, ensure_ascii=False)
    for forbidden in (
        "WallCrawler",
        "GTFO",
        "Expected",
        "Golden",
        "annotation",
        "prior actual",
    ):
        assert forbidden not in correction_text
    assert result.agent_discovery["requirement_projection"][
        "deferred_planning_or_runtime_questions"
    ] == ["How should the final Runtime presentation appear?"]


def test_projection_second_missing_coverage_fails_with_two_attempt_diagnostic(
    tmp_path: Path,
) -> None:
    request_text = "Observe one bounded transition."
    rejected, _, _, _ = _projection_coverage_recovery_responses(request_text)
    second_rejected = deepcopy(rejected)
    second_projection = second_rejected["requirement_projection"]
    assert isinstance(second_projection, dict)
    second_projection["behavior_goal"] = request_text + " Corrected output."
    model = _ScriptedModel([rejected, second_rejected])
    executor = _ObservedToolExecutor()
    specialist = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=executor,
    )
    request = replace(
        _request(tmp_path),
        natural_language_request=request_text,
        require_actual_planning=True,
    )
    factory = IntelligentEvidencePackFactory(
        specialist=specialist,
        sources=request.sources,
        max_tool_calls=request.max_tool_calls,
        max_model_steps=request.max_model_steps,
        require_actual_planning=True,
    )

    with pytest.raises(
        ValueError,
        match="MODEL_RELATION_REQUIREMENT_COVERAGE_INVALID",
    ) as raised:
        specialist.discover(request)

    assert len(model.calls) == 2
    assert executor.actions == []
    diagnostic = raised.value.diagnostic
    assert diagnostic["projection_attempt_count"] == 2
    assert diagnostic["initial_projection_success"] is False
    assert diagnostic["projection_recovery_attempted"] is True
    assert diagnostic["projection_recovery_success"] is False
    assert [item["status"] for item in diagnostic["requirement_projection_attempts"]] == [
        "rejected",
        "rejected",
    ]
    assert all(
        item["error_code"] == "MODEL_RELATION_REQUIREMENT_COVERAGE_INVALID"
        for item in diagnostic["requirement_projection_attempts"]
    )
    persisted = _failed_run_diagnostics(
        evidence_factory=factory,
        error=raised.value,
    )
    assert persisted["requirement_projection_attempts"] == diagnostic[
        "requirement_projection_attempts"
    ]
    assert persisted["projection_attempt_count"] == 2
    assert persisted["projection_recovery_success"] is False
    assert persisted["tool_execution_completed"] == 0


def test_projection_noncoverage_error_does_not_receive_correction(
    tmp_path: Path,
) -> None:
    request_text = "Observe one bounded transition."
    rejected, corrected, _, _ = _projection_coverage_recovery_responses(
        request_text
    )
    rejected["requirement_projection"]["relation_definitions"] = []
    model = _ScriptedModel([rejected, corrected])
    executor = _ObservedToolExecutor()
    specialist = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=executor,
    )

    with pytest.raises(ValueError, match="MODEL_RELATION_DEFINITIONS_REQUIRED"):
        specialist.discover(
            replace(
                _request(tmp_path),
                natural_language_request=request_text,
                require_actual_planning=True,
            )
        )

    assert len(model.calls) == 1
    assert executor.actions == []
    diagnostics = specialist.runtime_diagnostics
    assert diagnostics["projection_attempt_count"] == 1
    assert diagnostics["projection_recovery_attempted"] is False


def test_projection_recovery_composes_with_search_plan_correction_steps(
    tmp_path: Path,
) -> None:
    projection, incomplete, corrected_search = (
        _two_requirement_split_planning_responses()
    )
    rejected_projection = deepcopy(projection)
    raw_projection = rejected_projection["requirement_projection"]
    assert isinstance(raw_projection, dict)
    for relation in raw_projection["relation_definitions"]:
        relation["parent_requirement_indexes"] = [1]
    finish = {
        "action": "finish",
        "decision": "needs_more_evidence",
        "evidence_conclusions": [],
        "unresolved_questions": ["Current source observations are still required."],
        "missing_capabilities": [],
    }
    model = _ScriptedModel(
        [
            rejected_projection,
            projection,
            incomplete,
            corrected_search,
            finish,
        ]
    )
    executor = _ObservedToolExecutor()

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=executor,
    ).discover(replace(_request(tmp_path), require_actual_planning=True))

    assert len(model.calls) == 5
    assert executor.actions == []
    assert result.pack.budget_summary["planning_model_steps_used"] == 4
    assert result.pack.budget_summary["projection_attempt_count"] == 2
    assert result.pack.budget_summary["projection_recovery_success"] is True
    assert result.pack.budget_summary["total_model_steps_used"] == 5
    assert result.agent_discovery is not None


def test_projection_correction_each_provider_call_retains_context_admission(
    tmp_path: Path,
) -> None:
    request_text = "Observe one bounded transition."
    rejected, _, _, _ = _projection_coverage_recovery_responses(request_text)
    insufficient = deepcopy(rejected)
    insufficient["planning_status"] = "requirement_projection_insufficient"
    insufficient_projection = insufficient["requirement_projection"]
    assert isinstance(insufficient_projection, dict)
    insufficient_projection["planning_blocking_questions"] = []
    insufficient_projection["relation_definitions"] = []
    insufficient_projection["deferred_planning_or_runtime_questions"] = [
        "The request remains deferred."
    ]
    responses = [rejected, insufficient]
    payloads: list[dict[str, object]] = []

    def send(_url, payload, _headers):
        payloads.append(payload)
        response = responses.pop(0)
        return {
            "model": "qwen3:4b-instruct",
            "done": True,
            "done_reason": "stop",
            "message": {
                "role": "assistant",
                "content": json.dumps(response, ensure_ascii=False),
            },
            "prompt_eval_count": 1,
            "eval_count": 1,
        }

    client = OllamaChatAgentAdapter(
        base_url="http://127.0.0.1:11434",
        model="qwen3:4b-instruct",
        max_output_tokens=4096,
        context_window=32768,
        request_sender=send,
    )
    model = EvidenceDiscoveryAgentModel(
        client,
        local_execution=EvidenceDiscoveryLocalExecution(
            endpoint="http://127.0.0.1:11434",
            provider=client.provider,
            model=client.model,
        ),
    )
    executor = _ObservedToolExecutor()

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=executor,
    ).discover(
        replace(
            _request(tmp_path),
            natural_language_request=request_text,
            require_actual_planning=True,
        )
    )

    assert result.run_status == "requirement_projection_insufficient"
    assert len(payloads) == 2
    assert executor.actions == []
    assert all(
        payload["format"] == evidence_discovery_requirement_projection_schema()
        for payload in payloads
    )
    assert all(
        record["context_admission"]["admitted"] is True
        for record in model.provider_turn_records
    )
    assert result.pack.budget_summary["planning_model_steps_used"] == 2
    assert result.pack.budget_summary["projection_attempt_count"] == 2


def test_request_side_relation_identity_supports_required_cardinalities() -> None:
    request, action = _relation_projection_action()
    parsed = _parse_requirement_projection_action(
        json.dumps(action),
        natural_language_request=request,
    )
    projection = parsed["requirement_projection"]
    assert isinstance(projection, dict)
    validate_requirement_projection_actual(projection, require_meaningful=True)
    contract = projection["relation_contract"]
    relations = contract["relations"]

    assert len(relations) == 4
    assert len({row["relation_id"] for row in relations}) == 4
    assert [row["parent_requirement_ids"] for row in relations[:3]] == [
        ["requirement-001"],
        ["requirement-001"],
        ["requirement-001"],
    ]
    assert relations[3]["parent_requirement_ids"] == [
        "requirement-001",
        "requirement-002",
    ]
    assert [row["provenance"] for row in relations] == [
        {"relation_index": 1},
        {"relation_index": 2},
        {"relation_index": 3},
        {"relation_index": 4},
    ]
    serialized = json.dumps(contract, ensure_ascii=False)
    for answer_field in (
        "expected_relationship",
        "expected_sufficiency",
        "expected_control_action",
        "golden",
        "target_symbol",
        "target_path",
        "hook_identity",
    ):
        assert answer_field not in serialized.lower()

    duplicate = deepcopy(projection)
    duplicate_relations = duplicate["relation_contract"]["relations"]
    duplicate_relations[1]["relation_id"] = duplicate_relations[0]["relation_id"]
    with pytest.raises(ValueError, match="REQUEST_RELATION_IDENTITY_INVALID"):
        validate_requirement_projection_actual(
            duplicate,
            require_meaningful=True,
        )


def _relation_bound_finish(
    projection: dict[str, object],
    *,
    relation_ids: list[str],
    relationship: str = "missing",
    observation_ids: list[str] | None = None,
) -> dict[str, object]:
    relation_contract = projection["relation_contract"]
    assert isinstance(relation_contract, dict)
    relation_by_id = {
        str(row["relation_id"]): row
        for row in relation_contract["relations"]
    }
    requirement_ids = sorted(
        {
            str(parent)
            for relation_id in relation_ids
            if relation_id in relation_by_id
            for parent in relation_by_id[relation_id]["parent_requirement_ids"]
        }
    )
    return {
        "action": "finish",
        "decision": "needs_more_evidence",
        "evidence_conclusions": [
            {
                "claim": "Bounded relation disposition from one frozen observation.",
                "claim_status": "inferred",
                "observation_ids": list(
                    ["obs-relation"] if observation_ids is None else observation_ids
                ),
                "limitations": ["Synthetic relation binding test."],
                "requirement_ids": requirement_ids,
                "relation_ids": relation_ids,
                "relationship": relationship,
            }
        ],
        "unresolved_questions": ["Runtime behavior remains unresolved."],
        "missing_capabilities": [],
    }


def test_one_conclusion_can_bind_multiple_frozen_relation_identities() -> None:
    request, action = _relation_projection_action()
    parsed = _parse_requirement_projection_action(
        json.dumps(action),
        natural_language_request=request,
    )
    projection = parsed["requirement_projection"]
    assert isinstance(projection, dict)
    relations = projection["relation_contract"]["relations"]
    relation_ids = [str(row["relation_id"]) for row in relations]
    finish = _relation_bound_finish(projection, relation_ids=relation_ids)
    observation = ToolObservation(
        observation_id="obs-relation",
        tool="search_dotnet_metadata",
        source_id="current-interop",
        summary="Bounded search completed.",
        data={
            "assemblies_discovered": 1,
            "managed_assemblies_searched": 1,
            "unreadable_or_non_managed_assemblies": 0,
            "results_truncated": False,
            "returned_counts": {"methods": 0, "types": 0, "fields": 0},
            "matched_counts": {"methods": 0, "types": 0, "fields": 0},
        },
        relation_ids=tuple(relation_ids),
    )

    _validate_finish(
        finish,
        {observation.observation_id: observation},
        agent_discovery={"requirement_projection": projection},
    )

    conclusion = finish["evidence_conclusions"][0]
    assert conclusion["relation_ids"] == relation_ids
    assert conclusion["requirement_ids"] == [
        "requirement-001",
        "requirement-002",
    ]


@pytest.mark.parametrize(
    "mutation",
    ["empty", "duplicate", "unknown", "cross_projection"],
)
def test_relation_foreign_keys_fail_closed(mutation: str) -> None:
    request, action = _relation_projection_action()
    parsed = _parse_requirement_projection_action(
        json.dumps(action),
        natural_language_request=request,
    )
    projection = parsed["requirement_projection"]
    assert isinstance(projection, dict)
    relation_ids = [
        str(row["relation_id"])
        for row in projection["relation_contract"]["relations"]
    ]
    if mutation == "empty":
        selected_ids: list[str] = []
    elif mutation == "duplicate":
        selected_ids = [relation_ids[0], relation_ids[0]]
    elif mutation == "unknown":
        selected_ids = ["relation_unknown"]
    else:
        other_request, other_action = _relation_projection_action(
            request="A different frozen request identity."
        )
        other = _parse_requirement_projection_action(
            json.dumps(other_action),
            natural_language_request=other_request,
        )
        selected_ids = [
            str(
                other["requirement_projection"]["relation_contract"]["relations"][0][
                    "relation_id"
                ]
            )
        ]
    finish = _relation_bound_finish(projection, relation_ids=selected_ids)
    finish["evidence_conclusions"][0]["requirement_ids"] = ["requirement-001"]
    observation = ToolObservation(
        observation_id="obs-relation",
        tool="search_dotnet_metadata",
        source_id="current-interop",
        summary="Bounded search completed.",
        data={"methods": []},
    )

    with pytest.raises(
        ValueError,
        match="EVIDENCE_CONCLUSION_RELATION_BINDING_INVALID",
    ):
        _validate_finish(
            finish,
            {observation.observation_id: observation},
            agent_discovery={"requirement_projection": projection},
        )


@pytest.mark.parametrize("relationship", ["support", "conflict", "missing"])
def test_relation_disposition_requires_observation_grounding(
    relationship: str,
) -> None:
    request, action = _relation_projection_action()
    parsed = _parse_requirement_projection_action(
        json.dumps(action),
        natural_language_request=request,
    )
    projection = parsed["requirement_projection"]
    assert isinstance(projection, dict)
    relation_id = str(
        projection["relation_contract"]["relations"][0]["relation_id"]
    )
    finish = _relation_bound_finish(
        projection,
        relation_ids=[relation_id],
        relationship=relationship,
        observation_ids=[],
    )

    with pytest.raises(
        ValueError,
        match="EVIDENCE_CONCLUSION_RELATION_GROUNDING_REQUIRED",
    ):
        _validate_finish(
            finish,
            {},
            agent_discovery={"requirement_projection": projection},
        )


def test_relation_lineage_rejects_self_asserted_and_cross_bound_ids(
    tmp_path: Path,
) -> None:
    request, projection_action = _relation_projection_action()
    projection = _parse_requirement_projection_action(
        json.dumps(projection_action),
        natural_language_request=request,
    )["requirement_projection"]
    relation_ids = [
        str(row["relation_id"])
        for row in projection["relation_contract"]["relations"]
    ]
    agent_discovery = {"requirement_projection": projection}
    raw_il_action = {
        "action": "use_tool",
        "tool": "inspect_method_il",
        "source_id": "current-interop",
        "arguments": {"candidate_ref": "candidate_obs_001"},
        "evidence_need": "Inspect the exact observed method.",
        "derived_from_observation_ids": ["obs-001"],
    }
    origin = ToolObservation(
        observation_id="obs-001",
        tool="search_dotnet_metadata",
        source_id="current-interop",
        summary="One method observed.",
        data={"methods": []},
        relation_ids=(relation_ids[0],),
    )

    resolved = _bind_action_relation_ids(
        raw_il_action,
        raw_action=raw_il_action,
        observations_by_id={"obs-001": origin},
        candidate_origins={"candidate_obs_001": ("obs-001", "current-interop")},
        agent_discovery=agent_discovery,
    )
    assert resolved["relation_ids"] == [relation_ids[0]]

    asserted_action = {**raw_il_action, "relation_ids": [relation_ids[1]]}
    with pytest.raises(ValueError, match="MODEL_TOOL_ACTION_RELATION_IDS_FORBIDDEN"):
        _bind_action_relation_ids(
            asserted_action,
            raw_action=asserted_action,
            observations_by_id={"obs-001": origin},
            candidate_origins={
                "candidate_obs_001": ("obs-001", "current-interop")
            },
            agent_discovery=agent_discovery,
        )

    source = _request(tmp_path).sources[0]
    asserted_observation = _ObservedToolExecutor().execute(
        action={
            "action": "use_tool",
            "tool": "search_dotnet_metadata",
            "source_id": source.source_id,
            "arguments": _metadata_arguments("ObservedTransition"),
            "evidence_need": "Observe one transition method.",
            "derived_from_observation_ids": [],
            "query_family_id": "family-001-001",
            "relation_ids": [relation_ids[0]],
        },
        source=source,
        observation_id="obs-self-asserted",
    )
    asserted_observation = replace(
        asserted_observation,
        relation_ids=(relation_ids[1],),
    )
    with pytest.raises(
        ValueError,
        match="TOOL_OBSERVATION_SELF_ASSERTED_RELATION_IDS",
    ):
        _bind_observation_relation_ids(
            asserted_observation,
            action={"relation_ids": [relation_ids[0]]},
            agent_discovery=agent_discovery,
        )


def test_shared_multi_relation_observation_cannot_assert_relation_support(
    tmp_path: Path,
) -> None:
    request, projection_action = _relation_projection_action()
    projection = _parse_requirement_projection_action(
        json.dumps(projection_action),
        natural_language_request=request,
    )["requirement_projection"]
    relation_ids = [
        str(row["relation_id"])
        for row in projection["relation_contract"]["relations"]
    ]
    source = _request(tmp_path).sources[0]
    observation = _ObservedToolExecutor().execute(
        action={
            "tool": "inspect_method_il",
            "arguments": {"candidate_ref": "candidate_obs_001"},
        },
        source=source,
        observation_id="obs-shared",
    )
    observation = replace(
        observation,
        relation_ids=(relation_ids[0], relation_ids[1]),
    )
    canonical_claim = next(
        fact["canonical_claim"]
        for fact in observation.supported_facts()
        if fact["fact_type"] == "method_body_metadata"
    )
    finish = {
        "action": "finish",
        "decision": "needs_more_evidence",
        "evidence_conclusions": [
            {
                "claim": canonical_claim,
                "claim_status": "observed",
                "observation_ids": ["obs-shared"],
                "limitations": [],
                "requirement_ids": ["requirement-001"],
                "relation_ids": [relation_ids[0]],
                "relationship": "support",
            }
        ],
        "unresolved_questions": ["The second relation remains unresolved."],
        "missing_capabilities": [],
    }

    with pytest.raises(ValueError, match="RELATION_FACT_SPECIFIC_BINDING_REQUIRED"):
        _validate_finish(
            finish,
            {"obs-shared": observation},
            agent_discovery={"requirement_projection": projection},
        )


def _bounded_relation_observation(
    observation_id: str,
    relation_id: str,
) -> ToolObservation:
    zero_counts = {"methods": 0, "types": 0, "fields": 0}
    return ToolObservation(
        observation_id=observation_id,
        tool="search_dotnet_metadata",
        source_id="current-interop",
        summary="Complete bounded metadata search returned zero matches.",
        data={
            "queries": [observation_id],
            "assemblies_discovered": 1,
            "managed_assemblies_searched": 1,
            "unreadable_or_non_managed_assemblies": 0,
            "results_truncated": False,
            "truncated_by_kind": {
                "methods": False,
                "types": False,
                "fields": False,
            },
            "matched_counts": dict(zero_counts),
            "matched_query_counts": {observation_id: dict(zero_counts)},
            "returned_counts": dict(zero_counts),
            "returned_query_counts": {observation_id: dict(zero_counts)},
        },
        relation_ids=(relation_id,),
    )


def test_bounded_missing_relation_roundtrips_strict_lineage(tmp_path: Path) -> None:
    request_text = "Investigate one bounded absent transition relation."
    _, projection_action = _relation_projection_action(request=request_text)
    raw_projection = projection_action["requirement_projection"]
    raw_projection["planning_blocking_questions"] = [
        raw_projection["planning_blocking_questions"][0]
    ]
    raw_projection["relation_definitions"] = [
        raw_projection["relation_definitions"][0]
    ]
    materialized = _parse_requirement_projection_action(
        json.dumps(projection_action),
        natural_language_request=request_text,
    )["requirement_projection"]
    relation_id = str(
        materialized["relation_contract"]["relations"][0]["relation_id"]
    )
    question = raw_projection["planning_blocking_questions"][0]
    search_response = {
        "action": "plan_search",
        "planning_status": "ready",
        "search_plan": {
            "investigations": [
                {
                    "engineering_question": question,
                    "initial_focus": True,
                    "source_ids": ["current-interop"],
                    "query_families": [
                        {
                            "queries": ["AbsentTransition"],
                            "evidence_need": "Search one exact transition spelling.",
                            "relation_indexes": [1],
                        },
                        {
                            "queries": ["MissingTransitionState"],
                            "evidence_need": "Search one alternate transition spelling.",
                            "relation_indexes": [1],
                        },
                    ],
                }
            ],
            "initial_stop_condition": "Stop after bounded relation coverage.",
            "initial_expand_condition": "Use only the second frozen family.",
        },
    }
    finish = _relation_bound_finish(
        materialized,
        relation_ids=[relation_id],
        observation_ids=["obs-001", "obs-002"],
    )

    class _BoundedZeroExecutor:
        def execute(self, **kwargs: object) -> ToolObservation:
            action = kwargs["action"]
            assert isinstance(action, dict)
            arguments = action["arguments"]
            assert isinstance(arguments, dict)
            queries = list(arguments["queries"])
            observation = _bounded_relation_observation(
                str(kwargs["observation_id"]),
                "executor_must_not_assert_relation",
            )
            data = dict(observation.data)
            data["queries"] = queries
            zero_counts = {"methods": 0, "types": 0, "fields": 0}
            data["matched_query_counts"] = {
                query: dict(zero_counts) for query in queries
            }
            data["returned_query_counts"] = {
                query: dict(zero_counts) for query in queries
            }
            return replace(observation, data=data, relation_ids=())

    result = EvidenceDiscoverySpecialist(
        model=_ScriptedModel(
            [
                projection_action,
                search_response,
                _family_selection("family-001-001"),
                _family_selection("family-001-002"),
                finish,
            ]
        ),
        tool_executor=_BoundedZeroExecutor(),
    ).discover(
        replace(
            _request(tmp_path),
            natural_language_request=request_text,
            require_actual_planning=True,
            max_tool_calls=2,
            max_model_steps=3,
        )
    )
    payload = result.pack.to_artifact_payload()

    assert result.run_status == "completed"
    assert result.pack.evidence_conclusions[0]["relationship"] == "missing"
    assert EvidencePack.from_artifact_payload(payload).to_artifact_payload() == payload


@pytest.mark.parametrize(
    "mutation,expected_error",
    [
        ("incomplete_family", "RELATION_MISSING_FAMILY_COVERAGE_INVALID"),
        ("unreadable", "RELATION_MISSING_BOUNDED_ABSENCE_REQUIRED"),
        ("truncated", "RELATION_MISSING_BOUNDED_ABSENCE_REQUIRED"),
        ("returned", "RELATION_MISSING_BOUNDED_ABSENCE_REQUIRED"),
        ("il", "RELATION_MISSING_BOUNDED_ABSENCE_REQUIRED"),
        ("support_conflict", "RELATION_MISSING_FACT_CONFLICT"),
    ],
)
def test_relation_missing_requires_complete_bounded_zero_coverage(
    mutation: str,
    expected_error: str,
) -> None:
    request_text = "Investigate one bounded missing relation."
    _, projection_action = _relation_projection_action(request=request_text)
    raw_projection = projection_action["requirement_projection"]
    raw_projection["planning_blocking_questions"] = [
        raw_projection["planning_blocking_questions"][0]
    ]
    raw_projection["relation_definitions"] = [
        raw_projection["relation_definitions"][0]
    ]
    projection = _parse_requirement_projection_action(
        json.dumps(projection_action),
        natural_language_request=request_text,
    )["requirement_projection"]
    relation_id = str(projection["relation_contract"]["relations"][0]["relation_id"])
    families = [
        {
            "family_id": "family-001-001",
            "relation_ids": [relation_id],
        },
        {
            "family_id": "family-001-002",
            "relation_ids": [relation_id],
        },
    ]
    observations = {
        "obs-001": _bounded_relation_observation("obs-001", relation_id),
        "obs-002": _bounded_relation_observation("obs-002", relation_id),
    }
    actions = [
        {
            "tool": "search_dotnet_metadata",
            "query_family_id": family["family_id"],
        }
        for family in families
    ]
    finish = _relation_bound_finish(
        projection,
        relation_ids=[relation_id],
        observation_ids=["obs-001", "obs-002"],
    )
    agent_discovery = {
        "requirement_projection": projection,
        "search_plan": {"query_families": families},
    }
    _validate_finish(
        finish,
        observations,
        agent_discovery=agent_discovery,
        actions=actions,
    )
    if mutation == "incomplete_family":
        actions.pop()
    elif mutation == "unreadable":
        data = dict(observations["obs-002"].data)
        data["unreadable_or_non_managed_assemblies"] = 1
        observations["obs-002"] = replace(observations["obs-002"], data=data)
    elif mutation == "truncated":
        data = dict(observations["obs-002"].data)
        data["results_truncated"] = True
        observations["obs-002"] = replace(observations["obs-002"], data=data)
    elif mutation == "returned":
        data = deepcopy(observations["obs-002"].data)
        data["returned_counts"]["methods"] = 1
        observations["obs-002"] = replace(observations["obs-002"], data=data)
    elif mutation == "il":
        observations["obs-002"] = replace(
            observations["obs-002"],
            tool="inspect_method_il",
        )
    else:
        finish["evidence_conclusions"].append(
            {
                **finish["evidence_conclusions"][0],
                "claim": "Conflicting fact.",
                "claim_status": "observed",
                "relationship": "conflict",
            }
        )

    with pytest.raises(ValueError, match=expected_error):
        _validate_finish(
            finish,
            observations,
            agent_discovery=agent_discovery,
            actions=actions,
        )


def test_relation_bound_evidence_pack_roundtrips_and_rejects_dangling_ref(
    tmp_path: Path,
) -> None:
    request_text = "Investigate one request-derived transition relation."
    _, projection_action = _relation_projection_action(request=request_text)
    raw_projection = projection_action["requirement_projection"]
    raw_projection["planning_blocking_questions"] = [
        raw_projection["planning_blocking_questions"][0]
    ]
    raw_projection["relation_definitions"] = [
        raw_projection["relation_definitions"][0]
    ]
    materialized = _parse_requirement_projection_action(
        json.dumps(projection_action),
        natural_language_request=request_text,
    )["requirement_projection"]
    relation_id = str(
        materialized["relation_contract"]["relations"][0]["relation_id"]
    )
    search_response = {
        "action": "plan_search",
        "planning_status": "ready",
        "search_plan": {
            "investigations": [
                {
                    "engineering_question": raw_projection[
                        "planning_blocking_questions"
                    ][0],
                    "initial_focus": True,
                    "source_ids": ["current-interop"],
                    "query_families": [
                        {
                            "queries": ["ObservedTransition", "TransitionState"],
                            "evidence_need": "Find one current transition method.",
                            "relation_indexes": [1],
                        }
                    ],
                }
            ],
            "initial_stop_condition": "Stop after exact relation grounding.",
            "initial_expand_condition": "Expand only after an observed gap.",
        },
    }
    finish = {
        "action": "finish",
        "decision": "needs_more_evidence",
        "evidence_conclusions": [
            {
                "claim": (
                    "Observed method body metadata for Observed.Type.Move: "
                    "metadata_token=0x06000001; rva=123; has_method_body=true; "
                    "instruction_count=1; instructions_truncated=false."
                ),
                "claim_status": "observed",
                "observation_ids": ["obs-002"],
                "limitations": [],
                "requirement_ids": ["requirement-001"],
                "relation_ids": [relation_id],
                "relationship": "support",
            }
        ],
        "unresolved_questions": ["Runtime behavior remains unresolved."],
        "missing_capabilities": [],
    }
    model = _ScriptedModel(
        [
            projection_action,
            search_response,
            _family_selection("family-001-001"),
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Inspect the observed transition method.",
                "derived_from_observation_ids": ["obs-001"],
            },
            finish,
        ]
    )

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(
        replace(
            _request(tmp_path),
            natural_language_request=request_text,
            require_actual_planning=True,
            max_tool_calls=2,
            max_model_steps=3,
        )
    )
    payload = result.pack.to_artifact_payload()

    family = payload["agent_discovery"]["search_plan"]["query_families"][0]
    assert family["relation_ids"] == [relation_id]
    accepted_tools = [
        attempt
        for attempt in payload["model_action_trace"]
        if attempt["status"] == "accepted"
        and attempt["action"]["action"] == "use_tool"
    ]
    assert [
        attempt["resolved_action"]["relation_ids"]
        for attempt in accepted_tools
    ] == [[relation_id], [relation_id]]
    assert [row["relation_ids"] for row in payload["observation_trace"]] == [
        [relation_id],
        [relation_id],
    ]
    assert [row["relation_ids"] for row in payload["tool_trace_summary"]] == [
        [relation_id],
        [relation_id],
    ]
    assert EvidencePack.from_artifact_payload(payload).to_artifact_payload() == payload
    drifted = deepcopy(payload)
    drifted["evidence_conclusions"][0]["relation_ids"] = ["relation_unknown"]
    with pytest.raises(ValueError, match="Evidence conclusion relation ref is invalid"):
        EvidencePack.from_artifact_payload(drifted)

    drifted_origin = deepcopy(payload)
    il_attempt = [
        attempt
        for attempt in drifted_origin["model_action_trace"]
        if attempt.get("resolved_action", {}).get("tool") == "inspect_method_il"
    ][0]
    il_attempt["resolved_action"]["relation_ids"] = ["relation_unknown"]
    il_attempt["resolved_action_sha256"] = hashlib.sha256(
        json.dumps(
            il_attempt["resolved_action"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValueError, match="relation binding"):
        EvidencePack.from_artifact_payload(drifted_origin)


def _two_requirement_split_planning_responses() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    full_plan = _actual_plan(
        behavior_goal="Observe authentication completion and audit publication.",
        queries=["FinishAuthentication", "AuthenticationCompleted"],
        evidence_need="Which current method completes authentication?",
    )
    _add_secondary_planning_question(full_plan)
    projection = deepcopy(full_plan["requirement_projection"])
    projection.pop("schema_version")
    projection["planning_blocking_questions"] = [
        item["question"]
        for item in projection["planning_blocking_questions"]
    ]
    projection["relation_definitions"] = [
        {
            "parent_requirement_indexes": [1],
            "meaning": "Authentication completion relation.",
            "investigation_question": "Which observation establishes completion?",
        },
        {
            "parent_requirement_indexes": [2],
            "meaning": "Audit publication relation.",
            "investigation_question": "Which observation establishes publication?",
        },
        {
            "parent_requirement_indexes": [1, 2],
            "meaning": "Completion-to-publication boundary relation.",
            "investigation_question": "How are completion and publication connected?",
        },
    ]
    projection_response = {
        "action": "project_requirements",
        "planning_status": "ready",
        "requirement_projection": projection,
    }
    first_investigation = {
        "engineering_question": (
            "Which current method completes authentication?"
        ),
        "initial_focus": True,
        "source_ids": ["current-interop"],
        "query_families": [
            {
                "queries": [
                    "FinishAuthentication",
                    "AuthenticationCompleted",
                ],
                "evidence_need": (
                    "Which current method completes authentication?"
                ),
                "relation_indexes": [1, 3],
            }
        ],
    }
    incomplete_search = {
        "action": "plan_search",
        "planning_status": "ready",
        "search_plan": {
            "investigations": [first_investigation],
            "initial_stop_condition": "Stop after both requirements close.",
            "initial_expand_condition": "Expand only after an observed gap.",
        },
    }
    corrected_search = deepcopy(incomplete_search)
    corrected_search["search_plan"]["investigations"].append(
        {
            "engineering_question": (
                "Which current method publishes the downstream audit record?"
            ),
            "initial_focus": False,
            "source_ids": ["current-interop"],
            "query_families": [
                {
                    "queries": ["PublishAuditRecord", "AuditRecordCommitted"],
                    "evidence_need": (
                        "Which current method publishes the audit record?"
                    ),
                    "relation_indexes": [2, 3],
                }
            ],
        }
    )
    return projection_response, incomplete_search, corrected_search


def _four_requirement_search_plan_responses() -> tuple[
    dict[str, object],
    dict[str, object],
]:
    questions = [
        "Which method loads an area configuration?",
        "Which method observes surface-relative orientation?",
        "Which method controls arbitrary-surface locomotion?",
        "Which method identifies prone locomotion support?",
    ]
    projection = {
        "action": "project_requirements",
        "planning_status": "ready",
        "requirement_projection": {
            "behavior_goal": "Investigate bounded arbitrary-surface locomotion.",
            "trigger": None,
            "actor": "configured enemy",
            "target": "wall or ceiling surface",
            "hard_constraints": [],
            "forbidden_outcomes": [],
            "implementation_hints": [],
            "acceptance_signals": [],
            "planning_blocking_questions": questions,
            "relation_definitions": [
                {
                    "parent_requirement_indexes": [index],
                    "meaning": f"Bounded surface relation {index}.",
                    "investigation_question": question,
                }
                for index, question in enumerate(questions, 1)
            ],
            "deferred_planning_or_runtime_questions": [],
        },
    }
    search = {
        "action": "plan_search",
        "planning_status": "ready",
        "search_plan": {
            "investigations": [
                {
                    "engineering_question": question,
                    "initial_focus": index == 1,
                    "source_ids": ["current-interop"],
                    "query_families": [
                        {
                            "queries": [
                                f"TechnicalType{index}",
                                f"TechnicalMethod{index}",
                            ],
                            "evidence_need": question,
                            "relation_indexes": [index],
                        }
                    ],
                }
                for index, question in enumerate(questions, 1)
            ],
            "initial_stop_condition": "Stop after every requirement is disposed.",
            "initial_expand_condition": "Expand only from an observed gap.",
        },
    }
    return projection, search


def test_frozen_plan_budget_infeasibility_stops_before_tool_dispatch(
    tmp_path: Path,
) -> None:
    projection, search = _four_requirement_search_plan_responses()
    model = _ScriptedModel([projection, search])
    executor = _ObservedToolExecutor()
    specialist = EvidenceDiscoverySpecialist(model=model, tool_executor=executor)

    with pytest.raises(ValueError, match="DISCOVERY_PLAN_BUDGET_INFEASIBLE"):
        specialist.discover(
            replace(
                _request(tmp_path),
                require_actual_planning=True,
                max_tool_calls=4,
                max_model_steps=5,
            )
        )

    assert len(model.calls) == 2
    assert executor.actions == []
    diagnostics = specialist.runtime_diagnostics
    assert diagnostics["failure_stage"] == "plan_budget_feasibility"
    assert diagnostics["symbolic_failure_code"] == (
        "DISCOVERY_PLAN_BUDGET_INFEASIBLE"
    )
    assert diagnostics["dispatch_started"] == 0
    assert diagnostics["tool_execution_completed"] == 0
    assert diagnostics["plan_budget_required_tool_calls"] == 5
    assert diagnostics["plan_budget_required_model_steps"] == 6
    assert diagnostics["plan_budget_configured_tool_calls"] == 4
    assert diagnostics["plan_budget_configured_model_steps"] == 5
    assert diagnostics["plan_budget_feasible"] is False

    assert specialist._agent_discovery is not None
    feasible = discovery_plan_budget_feasibility(
        agent_discovery=specialist._agent_discovery,
        max_tool_calls=5,
        max_model_steps=6,
    )
    assert feasible == {
        "planned_lane_count": 4,
        "additional_il_verification_calls": 1,
        "final_finish_steps": 1,
        "required_tool_calls": 5,
        "required_model_steps": 6,
        "configured_tool_calls": 5,
        "configured_model_steps": 6,
        "feasible": True,
    }


def test_actual_planning_budget_remains_bounded_at_five_tools(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    accepted = replace(
        request,
        require_actual_planning=True,
        max_tool_calls=5,
        max_model_steps=6,
    )
    assert accepted.max_tool_calls == 5
    with pytest.raises(
        ValueError,
        match="FIRST_HOOK_DISCOVERY_TOOL_BUDGET_EXCEEDS_FIVE",
    ):
        replace(accepted, max_tool_calls=6)


def test_search_plan_count_mismatch_allows_one_structure_correction(
    tmp_path: Path,
) -> None:
    projection, incomplete, corrected = _two_requirement_split_planning_responses()
    finish = {
        "action": "finish",
        "decision": "needs_more_evidence",
        "evidence_conclusions": [],
        "unresolved_questions": ["Current source observations are still required."],
        "missing_capabilities": [],
    }
    model = _ScriptedModel([projection, incomplete, corrected, finish])
    executor = _ObservedToolExecutor()
    specialist = EvidenceDiscoverySpecialist(model=model, tool_executor=executor)

    result = specialist.discover(
        replace(_request(tmp_path), require_actual_planning=True)
    )

    assert len(model.calls) == 4
    assert executor.actions == []
    assert result.agent_discovery is not None
    assert len(result.agent_discovery["search_plan"]["engineering_questions"]) == 2
    assert result.pack.budget_summary["planning_model_steps_used"] == 3
    diagnostics = specialist.runtime_diagnostics
    assert diagnostics["search_plan_correction_used"] is True
    assert diagnostics["search_plan_required_investigation_count"] == 2
    assert diagnostics["search_plan_returned_investigation_count"] == 1
    correction = model.calls[2][-1]["content"]
    assert correction["message_type"] == "search_plan_structure_correction"
    assert correction["error_code"] == (
        "MODEL_SEARCH_PLAN_REQUIREMENT_COVERAGE_INVALID"
    )
    assert correction["required_investigation_count"] == 2
    assert correction["returned_investigation_count"] == 1
    assert correction["required_search_plan_schema"] == (
        evidence_discovery_search_plan_schema()
    )
    serialized = json.dumps(correction, ensure_ascii=False)
    assert "BetterHitFeedback" not in serialized
    assert "ES_Hitreact" not in serialized
    assert "ActivateState" not in serialized
    assert "frozen_judgment_hash" not in serialized
    assert "acceptable_hook_full_identities" not in serialized


def test_search_plan_second_count_mismatch_fails_without_another_correction(
    tmp_path: Path,
) -> None:
    projection, incomplete, _ = _two_requirement_split_planning_responses()
    model = _ScriptedModel([projection, incomplete, deepcopy(incomplete)])
    executor = _ObservedToolExecutor()
    specialist = EvidenceDiscoverySpecialist(model=model, tool_executor=executor)

    with pytest.raises(
        ValueError,
        match="MODEL_SEARCH_PLAN_REQUIREMENT_COVERAGE_INVALID",
    ):
        specialist.discover(
            replace(_request(tmp_path), require_actual_planning=True)
        )

    assert len(model.calls) == 3
    assert executor.actions == []
    diagnostics = specialist.runtime_diagnostics
    assert diagnostics["search_plan_correction_used"] is True
    assert diagnostics["search_plan_required_investigation_count"] == 2
    assert diagnostics["search_plan_returned_investigation_count"] == 1
    assert diagnostics["dispatch_started"] == 0
    assert diagnostics["tool_execution_completed"] == 0


def test_model_search_plan_resolves_registry_authority_and_metadata_tool(
    tmp_path: Path,
) -> None:
    persistent = _actual_plan(
        behavior_goal="Find one observable authentication completion event.",
        queries=["Terminal", "Authentication"],
        evidence_need="Which current symbol exposes authentication completion?",
    )
    frozen_projection = persistent["requirement_projection"]
    model_plan = {
        "investigations": [
            {
                "engineering_question": (
                    "Which current symbol exposes authentication completion?"
                ),
                "initial_focus": True,
                "source_ids": ["current-interop"],
                "query_families": [
                    {
                        "queries": ["Terminal", "Authentication", "Terminal"],
                        "evidence_need": (
                            "Which current symbol exposes authentication completion?"
                        ),
                    },
                    {
                        "queries": ["Terminal", "Authentication"],
                        "evidence_need": (
                            "Which current symbol exposes authentication completion?"
                        ),
                    },
                    {
                        "queries": ["FinishAuthentication"],
                        "evidence_need": (
                            "Which current symbol completes authentication?"
                        ),
                    }
                ],
            }
        ],
        "initial_stop_condition": "Stop after exact current evidence is found.",
        "initial_expand_condition": "Expand only after an explicit gap.",
    }
    request = _request(tmp_path)
    sources = {source.source_id: source for source in request.sources}
    quality_findings: list[dict[str, object]] = []

    resolved = _resolve_model_search_plan_action(
        {
            "action": "plan_search",
            "planning_status": "ready",
            "search_plan": model_plan,
        },
        frozen_projection=frozen_projection,
        sources=sources,
        quality_findings=quality_findings,
    )
    resolved_plan = resolved["search_plan"]

    assert resolved_plan["source_roles"] == [
        {"source_id": "current-interop", "role": "authoritative"}
    ]
    assert {lane["tool"] for lane in resolved_plan["planned_lanes"]} == {
        "search_dotnet_metadata"
    }
    assert {family["tool"] for family in resolved_plan["query_families"]} == {
        "search_dotnet_metadata"
    }
    assert resolved_plan["engineering_questions"] == [
        {
            "question_id": "question-001",
            "question": "Which current symbol exposes authentication completion?",
            "requirement_ids": [
                frozen_projection["planning_blocking_questions"][0][
                    "requirement_id"
                ]
            ],
        }
    ]
    assert resolved_plan["initial_focus_question_id"] == "question-001"
    assert resolved_plan["planned_lanes"][0]["lane"] == "lane-001"
    assert resolved_plan["query_families"][0]["family_id"] == "family-001-001"
    assert resolved_plan["query_families"][0]["queries"] == [
        "Terminal",
        "Authentication",
    ]
    assert [
        family["family_id"] for family in resolved_plan["query_families"]
    ] == ["family-001-001", "family-001-002"]
    assert resolved_plan["query_families"][1]["queries"] == [
        "FinishAuthentication"
    ]
    assert quality_findings == [
        {
            "code": "QUERY_FAMILY_LEADS_NORMALIZED",
            "investigation_index": 1,
            "model_family_index": 1,
            "retained_queries": ["Terminal", "Authentication"],
            "dropped_queries": [
                {
                    "query": "Terminal",
                    "reason": "duplicate_lexical_root",
                }
            ],
        },
        {
            "code": "DUPLICATE_QUERY_FAMILY_DISPATCH_COLLAPSED",
            "investigation_index": 1,
            "duplicate_model_family_index": 2,
            "retained_family_id": "family-001-001",
            "dispatch_identities": [
                {
                    "tool": "search_dotnet_metadata",
                    "source_id": "current-interop",
                    "queries": ["Terminal", "Authentication"],
                    "evidence_need": (
                        "Which current symbol exposes authentication completion?"
                    ),
                }
            ],
        }
    ]
    assert "tool" not in evidence_discovery_search_plan_schema()["properties"][
        "search_plan"
    ]["properties"]["investigations"]["items"]["properties"]["query_families"][
        "items"
    ]["properties"]
    assert "source_roles" not in evidence_discovery_search_plan_schema()[
        "properties"
    ]["search_plan"]["properties"]


def test_two_step_discovery_is_selected_by_model_and_derived_from_observation(
    tmp_path: Path,
) -> None:
    model = _ScriptedModel(
        [
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("movement", "rotation", "path"),
                "evidence_need": "Discover exact movement-related metadata.",
                "derived_from_observation_ids": [],
            },
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Read the method body discovered in the first observation.",
                "derived_from_observation_ids": ["obs-001"],
            },
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [
                    {
                        "claim": "Observed inspected symbol: Observed.Type.Move.",
                        "claim_status": "observed",
                        "observation_ids": ["obs-002"],
                        "limitations": [],
                    }
                ],
                "unresolved_questions": ["Non-horizontal navigation remains unresolved."],
                "missing_capabilities": [],
            },
        ]
    )
    executor = _ObservedToolExecutor()

    result = EvidenceDiscoverySpecialist(model=model, tool_executor=executor).discover(
        _request(tmp_path)
    )

    assert [action["tool"] for action in executor.actions] == [
        "search_dotnet_metadata",
        "inspect_method_il",
    ]
    assert result.pack.can_generate_patch is False
    assert result.pack.readiness == "partial"
    assert result.run_status == "completed"
    assert result.input_audit == {
        "manual_symbol_count": 0,
        "manual_tool_sequence_count": 0,
        "precomputed_report_count": 0,
        "operator_intervention_count": 0,
    }
    assert result.intelligence_transfer == {
        "source_selection_by_platform": True,
        "tool_selection_by_platform": True,
        "symbol_discovery_by_platform": True,
        "followup_selection_by_platform": True,
        "evidence_interpretation_by_platform": True,
        "converged_before_budget": True,
        "grounded_conclusion_by_platform": True,
        "unproductive_repetition_absent": True,
        "semantic_relevance_evaluated": False,
    }
    assert result.observations[1].data["method_id"] == "method_obs_001"
    assert result.observations[1].supported_facts()[0]["canonical_claim"] == (
        "Observed inspected symbol: Observed.Type.Move."
    )
    assert result.pack.observation_fact_catalog
    inspection_fact_hashes = {
        fact["observation_sha256"]
        for fact in result.pack.observation_fact_catalog
        if fact["observation_id"] == "obs-002"
    }
    assert inspection_fact_hashes == {
        result.pack.observation_trace[1]["observation_sha256"]
    }
    assert result.pack.provenance_validation["candidate_binding_trace"][0][
        "il_observation_sha256"
    ] == result.pack.observation_trace[1]["observation_sha256"]
    assert result.pack.evidence_conclusions[0]["claim_status"] == "observed"
    assert result.pack.verified_findings[0]["claim_status"] == "observed"
    assert len(model.calls) == 3
    assert all(
        item["status"] == "accepted" for item in result.pack.model_action_trace
    )
    assert len(result.pack.model_action_trace) == 3
    assert len(result.pack.observation_trace) == 2
    assert len(result.pack.prompt_contract["system_contract_sha256"]) == 64
    assert result.pack.model_identity["execution_kind"] == "injected_local_or_test"
    assert result.pack.budget_summary["model_steps_used"] == 3
    assert result.pack.budget_summary["total_observation_bytes_used"] > 0
    system_contract = model.calls[0][0]["content"]
    assert isinstance(system_contract, dict)
    assert system_contract["contract_version"] == "evidence_discovery_prompt_v9"
    assert "literal managed-symbol substring" not in json.dumps(
        system_contract,
        ensure_ascii=False,
    )
    search_arguments = system_contract["actions"]["use_tool"]["tools"][
        "search_dotnet_metadata"
    ]
    assert search_arguments == [
        "queries",
        "result_kinds",
        "limit_per_kind",
    ]
    assert result.pack.prompt_contract["context_strategy"] == (
        "deduplicated_catalog_latest_observation_zero_result_recovery_"
        "repeat_correction_method_focus_and_fact_handles_v7"
    )
    finish_schema = system_contract["actions"]["finish"]["schema"]
    assert finish_schema["required"] == [
        "action",
        "decision",
        "evidence_conclusions",
        "unresolved_questions",
        "missing_capabilities",
    ]
    conclusion_schema = finish_schema["properties"]["evidence_conclusions"]["items"]
    assert conclusion_schema["required"] == [
        "claim",
        "claim_status",
        "observation_ids",
        "limitations",
    ]
    assert conclusion_schema["properties"]["observation_ids"]["type"] == "array"
    assert conclusion_schema["properties"]["limitations"]["type"] == "array"
    assert finish_schema["description"].startswith("Cross-field:")
    final_budget_state = model.calls[2][-1]["content"]
    assert isinstance(final_budget_state, dict)
    assert final_budget_state == {
        "message_type": "budget_state",
        "tool_calls_used": 2,
        "remaining_tool_calls": 1,
        "model_steps_used": 2,
        "remaining_model_steps": 2,
        "acceptance_progress": {
            "metadata_observation_ids": ["obs-001"],
            "inspect_method_il_observation_ids": ["obs-002"],
        },
        "remaining_acceptance_requirements": [
            (
                "Compare the inspected method's supported_facts with the frozen initial "
                "focus before deciding. A physical fact that does not support the requested "
                "behavior cannot close that requirement. Choose exactly one bounded next "
                "step: inspect one still-unverified method from observed_method_catalog; "
                "execute one unexecuted frozen query family for an exact open question; or "
                "finish with support/conflict/missing grounded only in listed fact_ids. "
                "Do not broad-search, repeat a method, or promote an unrelated physical fact "
                "to support. Deterministic code expands fact handles and frozen families."
            )
        ],
        "required_next_action": "finish_or_use_tool_for_exact_gap",
    }
    assert len(result.pack.budget_summary["discovery_message_bytes_by_turn"]) == 3
    assert result.pack.budget_summary["total_discovery_message_bytes"] == sum(
        result.pack.budget_summary["discovery_message_bytes_by_turn"]
    )
    assert result.pack.budget_summary["total_discovery_message_bytes"] < 18_500


def test_metadata_method_view_compares_observed_methods_with_initial_focus() -> None:
    earlier_metadata = ToolObservation(
        observation_id="obs-001",
        tool="search_dotnet_metadata",
        source_id="current-interop",
        summary="An earlier method was observed.",
        data={
            "methods": [
                {
                    "candidate_ref": "ref-earlier",
                    "symbol": "Observed.Reaction.ActivateState",
                    "metadata_token": "0x06000002",
                },
                {
                    "candidate_ref": "ref-unchecked",
                    "symbol": "Observed.Reaction.Enter",
                    "metadata_token": "0x06000003",
                },
            ]
        },
    )
    inspection = ToolObservation(
        observation_id="obs-002",
        tool="inspect_method_il",
        source_id="current-interop",
        summary="Exact IL was read.",
        data={
            "candidate_ref": "ref-earlier",
            "symbol": "Observed.Reaction.ActivateState",
            "metadata_token": "0x06000002",
        },
    )
    observation = ToolObservation(
        observation_id="obs-003",
        tool="search_dotnet_metadata",
        source_id="current-interop",
        summary="Two methods were observed.",
        data={
            "methods": [
                {
                    "candidate_ref": "ref-constructor",
                    "symbol": "Observed.Reaction..ctor",
                    "metadata_token": "0x06000001",
                    "matched_queries": ["Reaction"],
                    "has_method_body": True,
                },
                {
                    "candidate_ref": "ref-behavior",
                    "symbol": "Observed.Reaction.ActivateState",
                    "metadata_token": "0x06000002",
                    "matched_queries": ["Reaction", "ActivateState"],
                    "has_method_body": True,
                },
                {
                    "candidate_ref": "ref-unchecked-now",
                    "symbol": "Observed.Reaction.Enter",
                    "metadata_token": "0x06000003",
                    "matched_queries": ["Reaction"],
                    "has_method_body": True,
                },
            ]
        },
    )
    agent_discovery = _actual_plan(
        behavior_goal="Observe a requested state transition.",
        queries=["Reaction", "ActivateState"],
        evidence_need="Which current method observes the requested state transition?",
    )

    comparison = _method_focus_comparison(
        observation,
        agent_discovery=agent_discovery,
        actions=[
            {
                "tool": "search_dotnet_metadata",
                "query_family_id": "request-derived-behavior",
            },
            {"tool": "inspect_method_il"},
            {
                "tool": "search_dotnet_metadata",
                "query_family_id": "request-derived-behavior",
            },
        ],
        observations=[earlier_metadata, inspection, observation],
    )

    assert comparison is not None
    assert comparison["initial_focus_question_id"] == "question-primary"
    assert comparison["initial_focus_question"] == (
        "Which current method observes the requested state transition?"
    )
    assert comparison["metadata_observation_id"] == "obs-003"
    assert comparison["query_family_id"] == "request-derived-behavior"
    assert comparison["family_question_ids"] == ["question-primary"]
    assert comparison["evidence_need"] == (
        "Which current method observes the requested state transition?"
    )
    assert [item["method_kind"] for item in comparison["methods"]] == [
        "constructor",
        "ordinary_method",
        "ordinary_method",
    ]
    assert comparison["methods"][1]["candidate_ref"] == "ref-behavior"
    assert [item["verification_state"] for item in comparison["methods"]] == [
        "new_uninspected",
        "already_inspected",
        "previously_observed_uninspected",
    ]
    assert comparison["methods"][1]["inspection_observation_ids"] == ["obs-002"]
    assert comparison["methods"][2]["previous_metadata_observation_ids"] == [
        "obs-001"
    ]


def test_finish_fact_handle_expands_to_frozen_canonical_fact(tmp_path: Path) -> None:
    source = _request(tmp_path).sources[0]
    executor = _ObservedToolExecutor()
    metadata = executor.execute(
        action={
            "action": "use_tool",
            "tool": "search_dotnet_metadata",
            "source_id": source.source_id,
            "arguments": _metadata_arguments("movement"),
        },
        source=source,
        observation_id="obs-001",
    )
    inspection = executor.execute(
        action={
            "action": "use_tool",
            "tool": "inspect_method_il",
            "source_id": source.source_id,
            "arguments": {"candidate_ref": "candidate_obs_001"},
        },
        source=source,
        observation_id="obs-002",
    )
    fact = inspection.supported_facts()[0]
    raw_finish = {
        "action": "finish",
        "decision": "needs_more_evidence",
        "evidence_conclusions": [
            {
                "claim": fact["fact_id"],
                "claim_status": "observed",
                "observation_ids": ["obs-002"],
                "limitations": [],
            }
        ],
        "unresolved_questions": ["Runtime behavior remains unresolved."],
        "missing_capabilities": [],
    }

    resolved = _resolve_finish_fact_handles(
        raw_finish,
        observations_by_id={"obs-001": metadata, "obs-002": inspection},
    )

    assert raw_finish["evidence_conclusions"][0]["claim"] == fact["fact_id"]
    assert resolved["evidence_conclusions"][0]["claim"] == fact["canonical_claim"]
    assert inspection.model_supported_facts()[0] == {
        "fact_id": fact["fact_id"],
        "observation_id": "obs-002",
        "canonical_claim": fact["canonical_claim"],
    }
    _validate_finish(
        resolved,
        {"obs-001": metadata, "obs-002": inspection},
    )


def test_strict_reader_preserves_resolved_finish_fact_handle(tmp_path: Path) -> None:
    payload = _strict_semantic_payload(
        tmp_path,
        decision="needs_more_evidence",
    )
    attempt = payload["model_action_trace"][-1]
    resolved_action = deepcopy(attempt["action"])
    fact = next(
        item
        for item in payload["observation_fact_catalog"]
        if item["fact_type"] == "inspected_symbol"
    )
    attempt["action"]["evidence_conclusions"][0]["claim"] = fact["fact_id"]
    attempt["action_sha256"] = hashlib.sha256(
        json.dumps(
            attempt["action"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    attempt["resolved_action"] = resolved_action
    attempt["resolved_action_sha256"] = hashlib.sha256(
        json.dumps(
            resolved_action,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    ArtifactTypeRegistry().validate_write(
        artifact_type="evidence_pack",
        status="success",
        payload=payload,
    )
    assert EvidencePack.from_artifact_payload(payload).to_artifact_payload() == payload

    tampered = deepcopy(payload)
    tampered_resolved = tampered["model_action_trace"][-1]["resolved_action"]
    tampered_resolved["evidence_conclusions"][0]["claim"] = (
        "A model-authored interpretation cannot replace the frozen fact."
    )
    tampered["model_action_trace"][-1]["resolved_action_sha256"] = hashlib.sha256(
        json.dumps(
            tampered_resolved,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(
        ArtifactRegistryError,
        match="Resolved finish fact handle does not bind one frozen observation fact",
    ):
        ArtifactTypeRegistry().validate_write(
            artifact_type="evidence_pack",
            status="success",
            payload=tampered,
        )


def test_each_turn_replays_compact_history_and_only_the_latest_full_observation(
    tmp_path: Path,
) -> None:
    model = _ScriptedModel(
        [
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("movement"),
                "evidence_need": "Find one exact method.",
                "derived_from_observation_ids": [],
            },
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Inspect the observed method.",
                "derived_from_observation_ids": ["obs-001"],
            },
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [
                    {
                        "claim": "Observed inspected symbol: Observed.Type.Move.",
                        "claim_status": "observed",
                        "observation_ids": ["obs-002"],
                        "limitations": [],
                    }
                ],
                "unresolved_questions": ["Runtime behavior remains unresolved."],
                "missing_capabilities": [],
            },
        ]
    )

    EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(_request(tmp_path))

    second_turn = json.dumps(model.calls[1], ensure_ascii=False)
    third_turn = json.dumps(model.calls[2], ensure_ascii=False)
    assert "A" * 64 in second_turn
    assert "A" * 64 not in third_turn
    assert "compact_trajectory" in third_turn
    assert "candidate_obs_001" in third_turn
    assert "method_obs_001" not in third_turn


def test_compact_history_preserves_prior_il_outcome_without_duplicate_method_rows(
    tmp_path: Path,
) -> None:
    model = _ScriptedModel(
        [
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("movement"),
                "evidence_need": "Find one exact method.",
                "derived_from_observation_ids": [],
            },
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Inspect the observed method.",
                "derived_from_observation_ids": ["obs-001"],
            },
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("navigation"),
                "evidence_need": "Search one additional view.",
                "derived_from_observation_ids": ["obs-002"],
            },
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [
                    {
                        "claim": "Observed inspected symbol: Observed.Type.Move.",
                        "claim_status": "observed",
                        "observation_ids": ["obs-002"],
                        "limitations": [],
                    }
                ],
                "unresolved_questions": ["Runtime behavior remains unresolved."],
                "missing_capabilities": [],
            },
        ]
    )

    EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(_request(tmp_path))

    compact = next(
        item["content"]
        for item in model.calls[3]
        if isinstance(item.get("content"), dict)
        and item["content"].get("message_type") == "compact_trajectory"
    )
    assert compact["observed_method_catalog"] == []
    assert compact["inspection_catalog"] == [
        {
            "candidate_ref": "candidate_obs_001",
            "source_id": "current-interop",
            "inspection_observation_id": "obs-002",
            "symbol": "Observed.Type.Move",
            "metadata_token": "0x06000001",
            "has_method_body": True,
            "rva": 123,
            "instruction_count": 1,
            "instructions_truncated": False,
            "resolved_refs": [],
            "target_code_executed": False,
        }
    ]
    assert compact["steps"][1]["arguments"] == {
        "candidate_ref": "candidate_obs_001"
    }
    assert "observed_methods" not in compact["steps"][1]


def test_finish_without_available_il_reference_receives_bounded_correction(
    tmp_path: Path,
) -> None:
    model = _ScriptedModel(
        [
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("movement"),
                "evidence_need": "Find one exact method.",
                "derived_from_observation_ids": [],
            },
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Inspect the observed method.",
                "derived_from_observation_ids": ["obs-001"],
            },
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [
                    {
                        "claim": "One metadata method was observed.",
                        "claim_status": "observed",
                        "observation_ids": ["obs-001"],
                        "limitations": [],
                    }
                ],
                "unresolved_questions": ["Method semantics remain unresolved."],
                "missing_capabilities": [],
            },
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [
                    {
                        "claim": "Observed inspected symbol: Observed.Type.Move.",
                        "claim_status": "observed",
                        "observation_ids": ["obs-002"],
                        "limitations": [],
                    }
                ],
                "unresolved_questions": ["Runtime behavior remains unresolved."],
                "missing_capabilities": [],
            },
        ]
    )

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(_request(tmp_path))

    correction = model.calls[3][-2]["content"]
    assert correction["error_code"] == (
        "EVIDENCE_CONCLUSION_INSPECTION_REFERENCE_REQUIRED"
    )
    assert correction["available_inspection_observation_ids"] == ["obs-002"]
    assert correction["repair_focus"] == {
        "field": "evidence_conclusions[].observation_ids",
        "requirement": (
            "At least one observed or inferred conclusion must cite one id "
            "from available_inspection_observation_ids."
        ),
    }
    assert result.intelligence_transfer["symbol_discovery_by_platform"] is True
    assert [item["status"] for item in result.pack.model_action_trace] == [
        "accepted",
        "accepted",
        "rejected",
        "accepted",
    ]


def test_exact_observed_claim_with_wrong_observation_id_receives_correction(
    tmp_path: Path,
) -> None:
    invalid_finish = {
        "action": "finish",
        "decision": "needs_more_evidence",
        "evidence_conclusions": [
            {
                "claim": "Observed inspected symbol: Observed.Type.Move.",
                "claim_status": "observed",
                "observation_ids": ["obs-001"],
                "limitations": [],
            },
            {
                "claim": "The inspected body may not contain runtime behavior.",
                "claim_status": "inferred",
                "observation_ids": ["obs-002"],
                "limitations": ["Only one method body was inspected."],
            },
        ],
        "unresolved_questions": ["Runtime movement remains unresolved."],
        "missing_capabilities": [],
    }
    corrected_finish = deepcopy(invalid_finish)
    corrected_finish["evidence_conclusions"] = [
        {
            "claim": "Observed inspected symbol: Observed.Type.Move.",
            "claim_status": "observed",
            "observation_ids": ["obs-002"],
            "limitations": [],
        }
    ]
    model = _ScriptedModel(
        _metadata_then_il_responses(invalid_finish, corrected_finish)
    )

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(_request(tmp_path))

    assert result.run_status == "completed"
    assert result.pack.model_action_trace[2]["validation_error"] == (
        "OBSERVED_CONCLUSION_CANONICAL_FACT_MISMATCH"
    )
    correction = model.calls[3][-2]["content"]
    assert correction["error_code"] == (
        "OBSERVED_CONCLUSION_CANONICAL_FACT_MISMATCH"
    )


def test_mixed_observed_claim_is_corrected_into_exact_observed_and_inferred(
    tmp_path: Path,
) -> None:
    mixed_finish = {
        "action": "finish",
        "decision": "needs_more_evidence",
        "evidence_conclusions": [
            {
                "claim": (
                    "Observed inspected symbol: Observed.Type.Move. This is likely "
                    "an empty runtime implementation."
                ),
                "claim_status": "observed",
                "observation_ids": ["obs-002"],
                "limitations": [],
            }
        ],
        "unresolved_questions": ["Runtime movement remains unresolved."],
        "missing_capabilities": [],
    }
    corrected_finish = {
        **mixed_finish,
        "evidence_conclusions": [
            {
                "claim": "Observed inspected symbol: Observed.Type.Move.",
                "claim_status": "observed",
                "observation_ids": ["obs-002"],
                "limitations": [],
            },
            {
                "claim": "The inspected symbol may be an empty runtime implementation.",
                "claim_status": "inferred",
                "observation_ids": ["obs-002"],
                "limitations": [
                    "The symbol identity alone does not establish runtime behavior."
                ],
            },
        ],
    }
    model = _ScriptedModel(
        _metadata_then_il_responses(mixed_finish, corrected_finish)
    )
    executor = _ObservedToolExecutor()
    specialist = EvidenceDiscoverySpecialist(model=model, tool_executor=executor)

    result = specialist.discover(_request(tmp_path))

    assert result.run_status == "completed"
    assert len(model.calls) == 4
    assert len(model.calls) <= _request(tmp_path).max_model_steps
    assert len(executor.actions) == 2
    assert [item["status"] for item in result.pack.model_action_trace] == [
        "accepted",
        "accepted",
        "rejected",
        "accepted",
    ]
    assert result.pack.model_action_trace[2]["validation_error"] == (
        "OBSERVED_CONCLUSION_CANONICAL_FACT_MISMATCH"
    )
    correction = model.calls[3][-2]["content"]
    assert correction["repair_focus"] == {
        "field": "evidence_conclusions[]",
        "requirement": (
            "For each observed conclusion, set claim to one exact supported_fact "
            "fact_id and cite only that fact's observation_id. Deterministic code "
            "expands the handle to canonical_claim. Put interpretation in a "
            "separate inferred conclusion with limitations."
        ),
    }
    assert [
        item["claim_status"] for item in result.pack.evidence_conclusions
    ] == ["observed", "inferred"]
    assert [item["claim_status"] for item in result.pack.verified_findings] == [
        "observed"
    ]
    assert all(
        item["claim_status"] != "inferred"
        for item in result.pack.verified_findings
    )
    assert specialist.runtime_diagnostics["failure_stage"] == "none"
    assert specialist.runtime_diagnostics["symbolic_failure_code"] == "none"


def test_repeated_mixed_observed_claim_exhausts_existing_finish_correction(
    tmp_path: Path,
) -> None:
    mixed_finish = {
        "action": "finish",
        "decision": "needs_more_evidence",
        "evidence_conclusions": [
            {
                "claim": (
                    "Observed inspected symbol: Observed.Type.Move. This is likely "
                    "an empty runtime implementation."
                ),
                "claim_status": "observed",
                "observation_ids": ["obs-002"],
                "limitations": [],
            }
        ],
        "unresolved_questions": ["Runtime movement remains unresolved."],
        "missing_capabilities": [],
    }
    model = _ScriptedModel(
        _metadata_then_il_responses(mixed_finish, deepcopy(mixed_finish))
    )
    executor = _ObservedToolExecutor()
    specialist = EvidenceDiscoverySpecialist(model=model, tool_executor=executor)
    request = _request(tmp_path)

    result = specialist.discover(request)

    assert result.run_status == "budget_exhausted"
    assert len(model.calls) == 4
    assert len(model.calls) <= request.max_model_steps
    assert len(executor.actions) == 2
    assert result.pack.model_action_trace[2]["validation_error"] == (
        "OBSERVED_CONCLUSION_CANONICAL_FACT_MISMATCH"
    )
    assert result.pack.model_action_trace[3]["validation_error"] == (
        "OBSERVED_CONCLUSION_CANONICAL_FACT_MISMATCH"
    )
    assert result.pack.model_action_trace[-1]["origin"] == (
        "deterministic_budget_stop"
    )
    diagnostics = specialist.runtime_diagnostics
    assert diagnostics["failure_stage"] == "finish_validation"
    assert diagnostics["symbolic_failure_code"] == (
        "OBSERVED_CONCLUSION_CANONICAL_FACT_MISMATCH"
    )
    assert "semantic_gate" not in diagnostics
    assert "semantic_gate" not in result.pack.to_artifact_payload()


def test_last_model_turn_first_observed_mismatch_has_no_correction_or_pack(
    tmp_path: Path,
) -> None:
    mixed_finish = {
        "action": "finish",
        "decision": "needs_more_evidence",
        "evidence_conclusions": [
            {
                "claim": (
                    "Observed inspected symbol: Observed.Type.Move. This is likely "
                    "an empty runtime implementation."
                ),
                "claim_status": "observed",
                "observation_ids": ["obs-002"],
                "limitations": [],
            }
        ],
        "unresolved_questions": ["Runtime movement remains unresolved."],
        "missing_capabilities": [],
    }
    model = _ScriptedModel(_metadata_then_il_responses(mixed_finish))
    executor = _ObservedToolExecutor()
    specialist = EvidenceDiscoverySpecialist(model=model, tool_executor=executor)
    request = replace(_request(tmp_path), max_model_steps=3)
    factory = IntelligentEvidencePackFactory(
        specialist=specialist,
        sources=request.sources,
        max_tool_calls=request.max_tool_calls,
        max_model_steps=request.max_model_steps,
        max_result_bytes_per_call=request.max_result_bytes_per_call,
        max_total_observation_bytes=request.max_total_observation_bytes,
    )

    with pytest.raises(
        ValueError,
        match="OBSERVED_CONCLUSION_CANONICAL_FACT_MISMATCH",
    ) as raised:
        factory(
            {
                "run_id": request.run_id,
                "request_id": request.request_id,
                "user_request": request.natural_language_request,
            },
            {"target_behavior": request.natural_language_request},
        )

    assert getattr(raised.value, "run_status") == "budget_exhausted"
    assert len(model.calls) == request.max_model_steps == 3
    assert len(executor.actions) == 2
    assert factory.last_result is None
    diagnostics = specialist.runtime_diagnostics
    assert diagnostics["failure_stage"] == "finish_validation"
    assert diagnostics["symbolic_failure_code"] == (
        "OBSERVED_CONCLUSION_CANONICAL_FACT_MISMATCH"
    )
    assert diagnostics["correction_attempted"] is False
    assert diagnostics["correction_unavailable_reason"] == (
        "no_remaining_model_turn"
    )
    persisted_diagnostics = _failed_run_diagnostics(
        evidence_factory=factory,
        error=raised.value,
    )
    assert persisted_diagnostics["failure_stage"] == "finish_validation"
    assert persisted_diagnostics["symbolic_failure_code"] == (
        "OBSERVED_CONCLUSION_CANONICAL_FACT_MISMATCH"
    )
    assert persisted_diagnostics["correction_attempted"] is False
    assert persisted_diagnostics["correction_unavailable_reason"] == (
        "no_remaining_model_turn"
    )


def test_repeated_method_context_is_deduplicated_and_byte_accounted(
    tmp_path: Path,
) -> None:
    responses: list[dict[str, object]] = [
        {
            "action": "use_tool",
            "tool": "search_dotnet_metadata",
            "source_id": "current-interop",
            "arguments": _metadata_arguments("movement-1"),
            "evidence_need": "Search movement metadata one.",
            "derived_from_observation_ids": [],
        },
        {
            "action": "use_tool",
            "tool": "inspect_method_il",
            "source_id": "current-interop",
            "arguments": {"candidate_ref": "candidate_obs_001"},
            "evidence_need": "Inspect the exact method body.",
            "derived_from_observation_ids": ["obs-001"],
        },
    ]
    for index in range(3, 7):
        responses.append(
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments(f"movement-{index}"),
                "evidence_need": "Search another view with a repeated method result.",
                "derived_from_observation_ids": [f"obs-{index - 1:03d}"],
            }
        )
    responses.append(
        {
            "action": "finish",
            "decision": "needs_more_evidence",
            "evidence_conclusions": [
                {
                    "claim": "Observed inspected symbol: Observed.Type.Move.",
                    "claim_status": "observed",
                    "observation_ids": ["obs-002"],
                    "limitations": [],
                }
            ],
            "unresolved_questions": ["Runtime behavior remains unresolved."],
            "missing_capabilities": [],
        }
    )
    model = _ScriptedModel(responses)

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(
        replace(
            _request(tmp_path),
            max_tool_calls=6,
            max_model_steps=7,
        )
    )

    final_compact = next(
        item["content"]
        for item in model.calls[-1]
        if isinstance(item.get("content"), dict)
        and item["content"].get("message_type") == "compact_trajectory"
    )
    final_compact_bytes = len(
        json.dumps(
            final_compact,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    assert final_compact["observed_method_catalog"] == []
    assert len(final_compact["inspection_catalog"]) == 1
    assert final_compact_bytes < 2_700
    assert result.pack.budget_summary["total_discovery_message_bytes"] < 52_000
    assert result.pack.budget_summary["total_discovery_message_bytes"] == sum(
        result.pack.budget_summary["discovery_message_bytes_by_turn"]
    )


def test_repeated_identical_action_is_rejected_before_tool_execution(
    tmp_path: Path,
) -> None:
    repeated = {
        "action": "use_tool",
        "tool": "search_dotnet_metadata",
        "source_id": "current-interop",
        "arguments": _metadata_arguments("movement"),
        "evidence_need": "Search exact metadata.",
        "derived_from_observation_ids": [],
    }
    model = _ScriptedModel(
        [
            repeated,
            repeated,
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [],
                "unresolved_questions": ["No method body was selected."],
                "missing_capabilities": [],
            },
        ]
    )

    executor = _ObservedToolExecutor()
    specialist = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=executor,
    )
    result = specialist.discover(_request(tmp_path))

    assert len(executor.actions) == 1
    assert result.pack.budget_summary["tool_calls_used"] == 1
    assert result.intelligence_transfer["unproductive_repetition_absent"] is True
    assert result.intelligence_transfer["source_selection_by_platform"] is True
    assert result.intelligence_transfer["tool_selection_by_platform"] is False
    assert [item["status"] for item in result.pack.model_action_trace] == [
        "accepted",
        "rejected",
        "accepted",
    ]
    assert result.pack.model_action_trace[1]["validation_error"] == (
        "REPEATED_EXACT_TOOL_ACTION"
    )
    correction = model.calls[2][-2]["content"]
    assert correction["message_type"] == "tool_action_validation_error"
    assert correction["error_code"] == "REPEATED_EXACT_TOOL_ACTION"
    assert correction["executed_tool_call_count"] == 1
    assert "PersistentID" not in json.dumps(correction, ensure_ascii=False)


def test_repeat_correction_recovers_through_metadata_il_and_grounded_finish(
    tmp_path: Path,
) -> None:
    behavioral_search = {
        "action": "use_tool",
        "tool": "search_dotnet_metadata",
        "source_id": "current-interop",
        "arguments": _metadata_arguments("enemy wall movement behavior"),
        "evidence_need": "Search for movement behavior.",
        "derived_from_observation_ids": [],
    }
    model = _ScriptedModel(
        [
            behavioral_search,
            {
                **behavioral_search,
                "evidence_need": "Try the same behavioral search again.",
            },
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("EnemyLocomotion"),
                "evidence_need": "Use a managed symbol-name substring.",
                "derived_from_observation_ids": [],
            },
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_002"},
                "evidence_need": "Inspect the method returned by metadata.",
                "derived_from_observation_ids": ["obs-002"],
            },
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [
                    {
                        "claim": "Observed inspected symbol: Observed.Type.Move.",
                        "claim_status": "observed",
                        "observation_ids": ["obs-003"],
                        "limitations": [],
                    }
                ],
                "unresolved_questions": [
                    "PersistentID runtime identity binding remains unresolved."
                ],
                "missing_capabilities": [],
            },
        ]
    )
    executor = _QueryAwareObservedToolExecutor()

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=executor,
    ).discover(
        replace(
            _request(tmp_path),
            max_tool_calls=3,
            max_model_steps=5,
        )
    )

    assert result.run_status == "completed"
    assert [action["tool"] for action in executor.actions] == [
        "search_dotnet_metadata",
        "search_dotnet_metadata",
        "inspect_method_il",
    ]
    assert executor.actions[0]["arguments"] != executor.actions[1]["arguments"]
    assert result.pack.budget_summary["tool_calls_used"] == 3
    assert result.pack.budget_summary["model_steps_used"] == 5
    assert [item["status"] for item in result.pack.model_action_trace] == [
        "accepted",
        "rejected",
        "accepted",
        "accepted",
        "accepted",
    ]
    assert result.pack.model_action_trace[1]["validation_error"] == (
        "REPEATED_EXACT_TOOL_ACTION"
    )
    correction = model.calls[2][-2]["content"]
    assert correction["metadata_query_semantics"].startswith(
        "search_dotnet_metadata uses case-insensitive literal-substring matching"
    )
    assert "EnemyLocomotion" not in json.dumps(correction, ensure_ascii=False)
    assert "Observed.Type.Move" not in json.dumps(correction, ensure_ascii=False)
    assert result.intelligence_transfer["followup_selection_by_platform"] is True
    assert result.intelligence_transfer["symbol_discovery_by_platform"] is True
    assert result.pack.evidence_conclusions[0]["observation_ids"] == ["obs-003"]


def test_second_repeated_action_exhausts_single_repeat_correction(
    tmp_path: Path,
) -> None:
    repeated = {
        "action": "use_tool",
        "tool": "search_dotnet_metadata",
        "source_id": "current-interop",
        "arguments": _metadata_arguments("movement"),
        "evidence_need": "Search exact metadata.",
        "derived_from_observation_ids": [],
    }
    model = _ScriptedModel([repeated, repeated, repeated])
    executor = _ObservedToolExecutor()

    specialist = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=executor,
    )
    result = specialist.discover(_request(tmp_path))

    assert result.run_status == "budget_exhausted"
    assert len(executor.actions) == 1
    assert result.pack.budget_summary["tool_calls_used"] == 1
    assert result.pack.unresolved_questions == (
        "The single exact-repeat correction opportunity was exhausted before the model finished.",
    )
    diagnostics = specialist.runtime_diagnostics
    assert diagnostics["deterministic_validation_passed"] == 1
    assert diagnostics["dispatch_started"] == 1
    assert diagnostics["tool_execution_completed"] == 1
    assert diagnostics["observation_created"] == 1


def test_unobserved_candidate_reference_is_rejected(tmp_path: Path) -> None:
    model = _ScriptedModel(
        [
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "manually_supplied_candidate"},
                "evidence_need": "Attempt to skip discovery.",
                "derived_from_observation_ids": [],
            }
        ]
    )

    specialist = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    )

    with pytest.raises(ValueError, match="UNVERIFIED_CANDIDATE_REFERENCE"):
        specialist.discover(_request(tmp_path))

    diagnostics = specialist.runtime_diagnostics
    assert diagnostics["deterministic_validation_passed"] == 0
    assert diagnostics["dispatch_started"] == 0
    assert diagnostics["tool_execution_completed"] == 0
    assert diagnostics["observation_created"] == 0
    assert diagnostics["failure_stage"] == "action_validation"
    assert diagnostics["symbolic_failure_code"] == "UNVERIFIED_CANDIDATE_REFERENCE"


def test_observation_validation_failure_retains_completed_tool_counters(
    tmp_path: Path,
) -> None:
    model = _ScriptedModel(
        [
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("movement"),
                "evidence_need": "Find one exact method.",
                "derived_from_observation_ids": [],
            }
        ]
    )

    class _WrongToolObservationExecutor(_ObservedToolExecutor):
        def execute(self, **kwargs) -> ToolObservation:
            observation = super().execute(**kwargs)
            return replace(observation, tool="inspect_method_il")

    specialist = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_WrongToolObservationExecutor(),
    )

    with pytest.raises(ValueError, match="TOOL_OBSERVATION_TOOL_MISMATCH"):
        specialist.discover(_request(tmp_path))

    diagnostics = specialist.runtime_diagnostics
    assert diagnostics["deterministic_validation_passed"] == 1
    assert diagnostics["dispatch_started"] == 1
    assert diagnostics["tool_execution_completed"] == 1
    assert diagnostics["observation_created"] == 1
    assert diagnostics["failure_stage"] == "observation_validation"
    assert diagnostics["symbolic_failure_code"] == "TOOL_OBSERVATION_TOOL_MISMATCH"


def test_result_construction_failure_is_distinct_from_action_and_tool_stages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _ScriptedModel(
        [
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [],
                "unresolved_questions": ["No exact evidence was established."],
                "missing_capabilities": [],
            }
        ]
    )

    def fail_result_construction(**kwargs):
        raise ValueError("CANDIDATE_TRACE_TEST_FAILURE")

    monkeypatch.setattr(
        "src.mod_agent.evidence.discovery_loop._candidate_binding_trace",
        fail_result_construction,
    )
    specialist = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    )

    with pytest.raises(ValueError, match="CANDIDATE_TRACE_TEST_FAILURE"):
        specialist.discover(_request(tmp_path))

    diagnostics = specialist.runtime_diagnostics
    assert diagnostics["deterministic_validation_passed"] == 0
    assert diagnostics["dispatch_started"] == 0
    assert diagnostics["tool_execution_completed"] == 0
    assert diagnostics["observation_created"] == 0
    assert diagnostics["failure_stage"] == "result_construction"
    assert diagnostics["symbolic_failure_code"] == "CANDIDATE_TRACE_TEST_FAILURE"


def test_candidate_reference_must_use_its_origin_observation(tmp_path: Path) -> None:
    model = _ScriptedModel(
        [
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("movement"),
                "evidence_need": "Find the first method reference.",
                "derived_from_observation_ids": [],
            },
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("locomotion"),
                "evidence_need": "Find a second method reference.",
                "derived_from_observation_ids": ["obs-001"],
            },
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Attempt to use the first reference with the second observation.",
                "derived_from_observation_ids": ["obs-002"],
            },
        ]
    )

    with pytest.raises(
        ValueError, match="CANDIDATE_ORIGIN_OBSERVATION_REQUIRED"
    ):
        EvidenceDiscoverySpecialist(
            model=model,
            tool_executor=_ObservedToolExecutor(),
        ).discover(_request(tmp_path))


def test_model_never_receives_absolute_source_root(tmp_path: Path) -> None:
    model = _ScriptedModel(
        [
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [],
                "unresolved_questions": ["No tool was selected."],
                "missing_capabilities": [],
            }
        ]
    )

    EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(_request(tmp_path))

    serialized = json.dumps(model.calls, ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert "current-interop" in serialized


def test_source_selection_transfer_requires_multiple_available_sources(
    tmp_path: Path,
) -> None:
    model = _ScriptedModel(
        [
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("movement"),
                "evidence_need": "Search one configured source.",
                "derived_from_observation_ids": [],
            },
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [],
                "unresolved_questions": ["Only one source was available."],
                "missing_capabilities": [],
            },
        ]
    )

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(_request(tmp_path, include_second_source=False))

    assert result.intelligence_transfer["source_selection_by_platform"] is False


def test_model_receives_mandatory_finish_when_tool_budget_reaches_zero(
    tmp_path: Path,
) -> None:
    model = _ScriptedModel(
        [
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("movement"),
                "evidence_need": "Use the only allowed tool call.",
                "derived_from_observation_ids": [],
            },
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [],
                "unresolved_questions": ["More evidence would require another run."],
                "missing_capabilities": [],
            },
        ]
    )

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(
        replace(
            _request(tmp_path),
            max_tool_calls=1,
            max_model_steps=2,
        )
    )

    budget_state = model.calls[1][-1]["content"]
    assert isinstance(budget_state, dict)
    assert budget_state["remaining_tool_calls"] == 0
    assert budget_state["required_next_action"] == "finish"
    assert budget_state["acceptance_progress"] == {
        "metadata_observation_ids": ["obs-001"],
        "inspect_method_il_observation_ids": [],
    }
    assert budget_state["remaining_acceptance_requirements"] == [
        "Use inspect_method_il with a candidate_ref from a current-run metadata observation.",
        (
            "Finish with an observed or inferred conclusion whose observation_ids "
            "includes an inspect_method_il observation_id."
        ),
    ]
    assert result.run_status == "completed"


def test_zero_result_metadata_requires_query_recovery_or_grounded_finish(
    tmp_path: Path,
) -> None:
    model = _ScriptedModel(
        [
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("enemy wall movement behavior"),
                "evidence_need": "Search for movement behavior.",
                "derived_from_observation_ids": [],
            },
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [],
                "unresolved_questions": [
                    "No current metadata observation exposed a method reference."
                ],
                "missing_capabilities": [],
            },
        ]
    )

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_QueryAwareObservedToolExecutor(),
    ).discover(
        replace(
            _request(tmp_path, include_second_source=False),
            max_tool_calls=2,
            max_model_steps=2,
        )
    )

    budget_state = model.calls[1][-1]["content"]
    assert isinstance(budget_state, dict)
    assert budget_state["required_next_action"] == "use_tool_or_finish"
    assert budget_state["acceptance_progress"] == {
        "metadata_observation_ids": ["obs-001"],
        "inspect_method_il_observation_ids": [],
    }
    assert budget_state["remaining_acceptance_requirements"] == [
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
    serialized_state = json.dumps(budget_state, ensure_ascii=False)
    assert "WallCrawler" not in serialized_state
    assert "MonsterMovementHandler" not in serialized_state
    assert result.run_status == "completed"


def test_first_zero_result_finish_requires_one_bounded_recovery_search(
    tmp_path: Path,
) -> None:
    model = _ScriptedModel(
        [
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("enemy wall movement behavior"),
                "evidence_need": "Search for movement behavior.",
                "derived_from_observation_ids": [],
            },
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [],
                "unresolved_questions": [
                    "The first literal metadata query returned no method reference."
                ],
                "missing_capabilities": [],
            },
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("movement"),
                "evidence_need": "Try one different literal symbol substring.",
                "derived_from_observation_ids": ["obs-001"],
            },
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [],
                "unresolved_questions": [
                    "The recovered method still requires exact IL inspection."
                ],
                "missing_capabilities": [],
            },
        ]
    )
    executor = _QueryAwareObservedToolExecutor()

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=executor,
    ).discover(
        replace(
            _request(tmp_path, include_second_source=False),
            max_tool_calls=3,
            max_model_steps=4,
        )
    )

    assert len(executor.actions) == 2
    assert executor.actions[1]["arguments"] == _metadata_arguments("movement")
    assert result.run_status == "completed"
    assert [item["status"] for item in result.pack.model_action_trace] == [
        "accepted",
        "rejected",
        "accepted",
        "accepted",
    ]
    assert result.pack.model_action_trace[1]["validation_error"] == (
        "ZERO_RESULT_RECOVERY_REQUIRED"
    )
    correction = model.calls[2][-2]["content"]
    assert correction["message_type"] == "tool_action_validation_error"
    assert correction["error_code"] == "ZERO_RESULT_RECOVERY_REQUIRED"
    assert correction["finish_allowed"] is False
    assert correction["required_change"].startswith(
        "Use search_dotnet_metadata once with a materially different"
    )
    budget_state = model.calls[2][-1]["content"]
    assert budget_state["required_next_action"] == "use_tool"
    serialized_correction = json.dumps(correction, ensure_ascii=False)
    assert "ES_Hitreact" not in serialized_correction
    assert "DoHitReact" not in serialized_correction


def test_invalid_finish_decision_receives_one_bounded_correction_step(
    tmp_path: Path,
) -> None:
    model = _ScriptedModel(
        [
            {
                "action": "finish",
                "decision": "insufficient_evidence",
                "evidence_conclusions": [],
                "unresolved_questions": ["Movement behavior is unresolved."],
                "missing_capabilities": [],
            },
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [
                    {
                        "claim": "Non-horizontal movement behavior is unknown.",
                        "claim_status": "unknown",
                        "observation_ids": [],
                        "limitations": ["No method body was inspected."],
                    }
                ],
                "unresolved_questions": ["Movement behavior is unresolved."],
                "missing_capabilities": [],
            },
        ]
    )

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(replace(_request(tmp_path), max_model_steps=2))

    correction = model.calls[1][-2]["content"]
    assert isinstance(correction, dict)
    assert correction["message_type"] == "finish_validation_error"
    assert correction["error_code"] == "DISCOVERY_DECISION_INVALID"
    assert correction["repair_focus"] == {
        "field": "decision",
        "requirement": "Use exactly one value from allowed_decisions.",
    }
    assert correction["required_finish_schema"]["properties"]["decision"][
        "enum"
    ] == correction["allowed_decisions"]
    assert correction["decision_constraints"] == {
        "sufficient_for_proposal": (
            "conclusions>0; unresolved_questions=0; missing_capabilities=0"
        ),
        "needs_more_evidence": "unresolved_questions+missing_capabilities>0",
        "blocked_by_missing_capability": "missing_capabilities>0",
        "conflicting_evidence": "conflict; proposal_locked",
    }
    assert result.run_status == "completed"
    assert [item["status"] for item in result.pack.model_action_trace] == [
        "rejected",
        "accepted",
    ]


def test_malformed_nested_conclusion_receives_exact_field_correction(
    tmp_path: Path,
) -> None:
    model = _ScriptedModel(
        [
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [
                    {
                        "conclusion": "Movement behavior remains unresolved.",
                        "derived_from_observation_ids": [],
                        "limitations": "No IL observation was produced.",
                    }
                ],
                "unresolved_questions": ["Movement behavior is unresolved."],
                "missing_capabilities": [],
            },
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [
                    {
                        "claim": "Non-horizontal movement behavior is unknown.",
                        "claim_status": "unknown",
                        "observation_ids": [],
                        "limitations": ["No method body was inspected."],
                    }
                ],
                "unresolved_questions": ["Movement behavior is unresolved."],
                "missing_capabilities": [],
            },
        ]
    )

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(replace(_request(tmp_path), max_model_steps=2))

    correction = model.calls[1][-2]["content"]
    assert isinstance(correction, dict)
    assert correction["error_code"] == "EVIDENCE_CONCLUSION_SHAPE_INVALID"
    assert correction["repair_focus"] == {
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
    conclusion_schema = correction["required_finish_schema"]["properties"][
        "evidence_conclusions"
    ]["items"]
    assert conclusion_schema["required"] == correction["repair_focus"][
        "required_keys"
    ]
    assert result.run_status == "completed"
    assert [item["status"] for item in result.pack.model_action_trace] == [
        "rejected",
        "accepted",
    ]


def test_second_invalid_finish_exhausts_single_correction_opportunity(
    tmp_path: Path,
) -> None:
    invalid = {
        "action": "finish",
        "decision": "not-an-allowed-decision",
        "evidence_conclusions": [],
        "unresolved_questions": ["Movement behavior remains unresolved."],
        "missing_capabilities": [],
    }
    model = _ScriptedModel([invalid, invalid, invalid])

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(replace(_request(tmp_path), max_model_steps=3))

    assert len(model.calls) == 2
    assert result.run_status == "budget_exhausted"
    assert result.pack.blockers == (
        {
            "code": "INTELLIGENT_DISCOVERY_NEEDS_MORE_EVIDENCE",
            "message": (
                "The model-selected evidence path did not establish proposal readiness."
            ),
            "needed_evidence": [
                "The single finish-correction opportunity was exhausted."
            ],
        },
    )
    assert [item["status"] for item in result.pack.model_action_trace] == [
        "rejected",
        "rejected",
        "accepted",
    ]
    assert result.pack.model_action_trace[-1]["origin"] == (
        "deterministic_budget_stop"
    )


def test_method_origin_provenance_survives_finish_correction_exhaustion(
    tmp_path: Path,
) -> None:
    model = _ScriptedModel(
        [
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("movement"),
                "evidence_need": "Find one managed movement symbol.",
                "derived_from_observation_ids": [],
            },
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Inspect the observed method body.",
                "derived_from_observation_ids": ["obs-001"],
            },
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [
                    {
                        "claim": "Observed.Type.Move has an inspected method body.",
                        "claim_status": "observed",
                        "observation_ids": ["obs-002"],
                        "limitations": [],
                    }
                ],
                "unresolved_gaps": ["PersistentID binding remains unresolved."],
                "required_next_action": "finish",
            },
            {
                "action": "finish",
                "decision": "sufficient_for_proposal",
                "evidence_conclusions": [
                    {
                        "claim": "Observed.Type.Move has an inspected method body.",
                        "claim_status": "observed",
                        "observation_ids": ["obs-002"],
                        "limitations": [],
                    }
                ],
                "unresolved_questions": ["PersistentID binding remains unresolved."],
                "missing_capabilities": [],
            },
        ]
    )

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(replace(_request(tmp_path), max_model_steps=4))

    assert result.run_status == "budget_exhausted"
    assert result.pack.provenance_validation[
        "all_method_inspections_derived_from_observations"
    ] is True
    assert result.pack.provenance_validation["run_id"] == (
        "run-wallcrawler-intelligent-evidence-test"
    )
    assert result.pack.provenance_validation["request_id"] == (
        "wallcrawler-intelligent-evidence-test"
    )
    assert result.intelligence_transfer["followup_selection_by_platform"] is False
    assert result.pack.model_action_trace[2]["validation_error"] == (
        "DISCOVERY_FINISH_SHAPE_INVALID"
    )
    assert result.pack.model_action_trace[3]["validation_error"] == (
        "SUFFICIENT_DECISION_HAS_OPEN_GAPS"
    )
    correction = model.calls[3][-2]["content"]
    assert correction["decision_constraints"]["sufficient_for_proposal"] == (
        "conclusions>0; unresolved_questions=0; missing_capabilities=0"
    )
    acceptance = evaluate_wallcrawler_local_evidence(
        evidence_pack=result.pack.to_artifact_payload(),
        current_stage="evidence_retrieval",
        forbidden_artifacts=[],
    )
    assert acceptance["capability_gate"]["checks"][
        "prior_observation_method_binding"
    ] is True
    assert acceptance["capability_gate"]["passed"] is False


def test_finish_correction_rejects_tool_action_without_executing_it(
    tmp_path: Path,
) -> None:
    model = _ScriptedModel(
        [
            {
                "action": "finish",
                "decision": "not-an-allowed-decision",
                "evidence_conclusions": [],
                "unresolved_questions": ["Movement behavior remains unresolved."],
                "missing_capabilities": [],
            },
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("movement"),
                "evidence_need": "Continue searching after correction.",
                "derived_from_observation_ids": [],
            },
        ]
    )

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(replace(_request(tmp_path), max_model_steps=3))

    assert len(model.calls) == 2
    assert result.run_status == "budget_exhausted"
    assert result.actions == ()
    assert result.observations == ()
    assert result.pack.model_action_trace[1]["validation_error"] == (
        "FINISH_CORRECTION_TOOL_CALL_FORBIDDEN"
    )


@pytest.mark.parametrize(
    ("conclusion", "error"),
    [
        (
            {
                "claim": "This behavior is inferred.",
                "claim_status": "inferred",
                "observation_ids": ["obs-001"],
                "limitations": [],
            },
            "INFERRED_CONCLUSION_LIMITATIONS_REQUIRED",
        ),
        (
            {
                "claim": "Runtime behavior is unknown.",
                "claim_status": "unknown",
                "observation_ids": ["obs-001"],
                "limitations": ["No runtime evidence."],
            },
            "UNKNOWN_CONCLUSION_MUST_NOT_CITE_OBSERVATION",
        ),
    ],
)
def test_conclusion_classification_is_strict(
    tmp_path: Path,
    conclusion: dict[str, object],
    error: str,
) -> None:
    model = _ScriptedModel(
        [
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("movement"),
                "evidence_need": "Create one observation.",
                "derived_from_observation_ids": [],
            },
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [conclusion],
                "unresolved_questions": [],
                "missing_capabilities": [],
            },
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [
                    {
                        "claim": "Runtime behavior remains unknown.",
                        "claim_status": "unknown",
                        "observation_ids": [],
                        "limitations": ["No runtime evidence was supplied."],
                    }
                ],
                "unresolved_questions": ["Runtime behavior remains unresolved."],
                "missing_capabilities": [],
            },
        ]
    )

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(_request(tmp_path))

    rejected = [
        item
        for item in result.pack.model_action_trace
        if item["status"] == "rejected"
    ]
    assert rejected[0]["validation_error"] == error
    assert result.pack.evidence_conclusions[0]["claim_status"] == "unknown"


class _MetadataRunner:
    def search(
        self,
        assembly_path: str | Path,
        *,
        queries: tuple[str, ...],
    ) -> dict[str, object]:
        assembly = Path(assembly_path)
        return {
            "assembly_sha256": hashlib.sha256(assembly.read_bytes()).hexdigest().upper(),
            "module_mvid": "00000000-0000-0000-0000-000000000002",
            "methods": [
                {
                    "symbol": "Observed.Type.Move",
                    "metadata_token": "0x06000002",
                    "has_method_body": True,
                }
            ],
            "types": [
                {"symbol": "Observed.MoveType", "metadata_token": "0x02000002"}
            ],
            "fields": [
                {"symbol": "Observed.Type.MoveSpeed", "metadata_token": "0x04000002"}
            ],
        }


class _LargeMetadataRunner:
    def search(
        self,
        assembly_path: str | Path,
        *,
        queries: tuple[str, ...],
    ) -> dict[str, object]:
        assembly = Path(assembly_path)
        return {
            "assembly_sha256": hashlib.sha256(assembly.read_bytes()).hexdigest().upper(),
            "module_mvid": "00000000-0000-0000-0000-000000000003",
            "methods": [
                {
                    "symbol": f"Observed.Type.Method{index:03d}",
                    "metadata_token": f"0x06{index:06X}",
                    "has_method_body": True,
                }
                for index in range(300)
            ],
            "types": [],
            "fields": [],
        }


class _MixedRelevanceMetadataRunner:
    def search(
        self,
        assembly_path: str | Path,
        *,
        queries: tuple[str, ...],
    ) -> dict[str, object]:
        assembly = Path(assembly_path)
        broad_rows = [
            {
                "symbol": f"Achievement.MarkEnemy{index:02d}",
                "metadata_token": f"0x06{index:06X}",
                "has_method_body": True,
            }
            for index in range(12)
        ]
        return {
            "assembly_sha256": hashlib.sha256(assembly.read_bytes()).hexdigest().upper(),
            "module_mvid": "00000000-0000-0000-0000-000000000004",
            "methods": [
                *broad_rows,
                {
                    "symbol": "Combat.StaggeredEnemy",
                    "metadata_token": "0x06000100",
                    "has_method_body": True,
                },
                {
                    "symbol": "Combat.StaggerResponse",
                    "metadata_token": "0x06000101",
                    "has_method_body": True,
                },
            ],
            "types": [],
            "fields": [],
        }


class _QueryFairMetadataRunner:
    def search(
        self,
        assembly_path: str | Path,
        *,
        queries: tuple[str, ...],
    ) -> dict[str, object]:
        assembly = Path(assembly_path)
        return {
            "assembly_sha256": hashlib.sha256(
                assembly.read_bytes()
            ).hexdigest().upper(),
            "module_mvid": "00000000-0000-0000-0000-000000000005",
            "methods": [
                *[
                    {
                        "symbol": f"LongNamedStructure.Action{index}",
                        "metadata_token": f"0x060001{index:02X}",
                        "has_method_body": True,
                    }
                    for index in range(6)
                ],
                {
                    "symbol": "ShortStructure.Observe",
                    "metadata_token": "0x06000201",
                    "has_method_body": True,
                },
                {
                    "symbol": "AnotherShortStructure.Verify",
                    "metadata_token": "0x06000202",
                    "has_method_body": True,
                },
            ],
            "types": [],
            "fields": [],
        }


class _ILRunner:
    def __init__(self, symbols: tuple[str, ...]) -> None:
        self.symbols = symbols

    def inspect_observed_method(
        self,
        assembly_path: str | Path,
        *,
        assembly_sha256: str,
        module_mvid: str,
        metadata_token: str,
    ) -> dict[str, object]:
        assembly = Path(assembly_path)
        assert self.symbols == ("Observed.Type.Move",)
        assert assembly_sha256 == hashlib.sha256(assembly.read_bytes()).hexdigest().upper()
        assert module_mvid == "00000000-0000-0000-0000-000000000002"
        assert metadata_token == "0x06000002"
        return {
            "assembly_sha256": hashlib.sha256(assembly.read_bytes()).hexdigest().upper(),
            "module_mvid": "00000000-0000-0000-0000-000000000002",
            "methods": [
                {
                    "symbol": "Observed.Type.Move",
                    "metadata_token": "0x06000002",
                    "attributes": "Public",
                    "impl_attributes": "IL",
                    "signature_blob": "0001",
                    "rva": 123,
                    "has_method_body": True,
                    "il_bytes": "2A",
                    "instructions": [
                        {
                            "offset": "IL_0000",
                            "opcode": "ret",
                            "operand": None,
                            "resolved": None,
                        }
                    ],
                    "custom_attributes": [],
                    "declaring_type_custom_attributes": [],
                }
            ],
        }


def test_real_tool_executor_binds_search_identity_to_exact_il(tmp_path: Path) -> None:
    assembly = tmp_path / "Modules-ASM.dll"
    assembly.write_bytes(b"managed-test-bytes")
    source = _request(tmp_path).sources[0]
    executor = LocalAssemblyEvidenceToolExecutor(
        metadata_runner=_MetadataRunner(),
        il_runner_factory=_ILRunner,
    )
    executor.begin_run(run_id="run-real-tool-binding")

    search = executor.execute(
        action={
            "tool": "search_dotnet_metadata",
            "arguments": _metadata_arguments("Move"),
        },
        source=source,
        observation_id="obs-001",
    )
    method = search.data["methods"][0]
    assert isinstance(method, dict)
    inspection = executor.execute(
        action={
            "tool": "inspect_method_il",
            "arguments": {"candidate_ref": method["candidate_ref"]},
        },
        source=source,
        observation_id="obs-002",
    )

    assert inspection.data["metadata_token"] == "0x06000002"
    assert inspection.data["method_id"] == method["method_id"]
    assert inspection.data["candidate_ref"] == method["candidate_ref"]
    assert method["candidate_ref"] != method["method_id"]
    assert inspection.data["target_code_executed"] is False
    assert inspection.evidence_items[0].source_path == "Modules-ASM.dll"
    assert search.data["requested_result_kinds"] == ["methods"]
    assert search.data["returned_counts"] == {
        "methods": 1,
        "types": 0,
        "fields": 0,
    }
    assert search.data["matched_counts"] == {
        "methods": 1,
        "types": 1,
        "fields": 1,
    }
    assert "assembly_sha256" not in method
    assert search.data["assemblies"][0]["assembly_sha256"]
    assert "method_id" not in json.dumps(search.model_view())
    assert "method_id" not in json.dumps(inspection.model_view())
    assert "method_id" not in json.dumps(search.supported_facts())
    assert "method_id" not in json.dumps(inspection.supported_facts())
    assert any(
        fact["fact_type"] == "instruction_sequence"
        for fact in inspection.supported_facts()
    )
    assert str(tmp_path) not in json.dumps(search.model_view())
    assert str(tmp_path) not in json.dumps(inspection.model_view())


def test_metadata_search_preserves_query_matches_and_ranks_before_truncation(
    tmp_path: Path,
) -> None:
    (tmp_path / "Modules-ASM.dll").write_bytes(b"managed-test-bytes")
    executor = LocalAssemblyEvidenceToolExecutor(
        metadata_runner=_MixedRelevanceMetadataRunner(),
        il_runner_factory=_ILRunner,
    )
    executor.begin_run(run_id="run-query-relevance")

    observation = executor.execute(
        action={
            "tool": "search_dotnet_metadata",
            "arguments": _metadata_arguments(
                "enemy", "stagger", "staggered", limit_per_kind=3
            ),
        },
        source=_request(tmp_path).sources[0],
        observation_id="obs-001",
    )

    methods = observation.data["methods"]
    assert [row["symbol"] for row in methods[:2]] == [
        "Combat.StaggeredEnemy",
        "Combat.StaggerResponse",
    ]
    assert methods[0]["matched_queries"] == ["enemy", "stagger", "staggered"]
    assert methods[1]["matched_queries"] == ["stagger"]
    frozen_queries = observation.data["queries"]
    assert frozen_queries == ["enemy", "stagger", "staggered"]
    for row in methods:
        assert row["matched_queries"] == [
            query
            for query in frozen_queries
            if query.casefold() in row["symbol"].casefold()
        ]
    assert observation.data["matched_query_counts"] == {
        "enemy": {"methods": 13, "types": 0, "fields": 0},
        "stagger": {"methods": 2, "types": 0, "fields": 0},
        "staggered": {"methods": 1, "types": 0, "fields": 0},
    }
    assert observation.data["returned_query_counts"] == {
        "enemy": {"methods": 2, "types": 0, "fields": 0},
        "stagger": {"methods": 2, "types": 0, "fields": 0},
        "staggered": {"methods": 1, "types": 0, "fields": 0},
    }
    assert observation.data["results_truncated"] is True
    assert observation.data["truncated_by_kind"] == {
        "methods": True,
        "types": False,
        "fields": False,
    }
    assert observation.data["matched_counts"] == {
        "methods": 14,
        "types": 0,
        "fields": 0,
    }
    assert observation.data["returned_counts"] == {
        "methods": 3,
        "types": 0,
        "fields": 0,
    }
    fact = observation.supported_facts()[0]
    assert fact["value"]["matched_query_counts"]["enemy"]["methods"] == 13
    assert "returned_query_counts=" in fact["canonical_claim"]

    repeated_executor = LocalAssemblyEvidenceToolExecutor(
        metadata_runner=_MixedRelevanceMetadataRunner(),
        il_runner_factory=_ILRunner,
    )
    repeated_executor.begin_run(run_id="run-query-relevance")
    repeated = repeated_executor.execute(
        action={
            "tool": "search_dotnet_metadata",
            "arguments": _metadata_arguments(
                "enemy", "stagger", "staggered", limit_per_kind=3
            ),
        },
        source=_request(tmp_path).sources[0],
        observation_id="obs-001",
    )
    assert repeated.data == observation.data


def test_metadata_method_window_is_fair_across_queries(
    tmp_path: Path,
) -> None:
    (tmp_path / "Modules-ASM.dll").write_bytes(b"managed-test-bytes")
    executor = LocalAssemblyEvidenceToolExecutor(
        metadata_runner=_QueryFairMetadataRunner(),
        il_runner_factory=_ILRunner,
    )
    executor.begin_run(run_id="run-query-fair-window")

    observation = executor.execute(
        action={
            "tool": "search_dotnet_metadata",
            "arguments": _metadata_arguments(
                "LongNamedStructure",
                "Short",
                limit_per_kind=4,
            ),
        },
        source=_request(tmp_path).sources[0],
        observation_id="obs-001",
    )

    assert [row["symbol"] for row in observation.data["methods"]] == [
        "LongNamedStructure.Action0",
        "AnotherShortStructure.Verify",
        "LongNamedStructure.Action1",
        "ShortStructure.Observe",
    ]
    assert observation.data["matched_query_counts"] == {
        "LongNamedStructure": {"methods": 6, "types": 0, "fields": 0},
        "Short": {"methods": 2, "types": 0, "fields": 0},
    }
    assert observation.data["returned_query_counts"] == {
        "LongNamedStructure": {"methods": 2, "types": 0, "fields": 0},
        "Short": {"methods": 2, "types": 0, "fields": 0},
    }


def test_real_tool_executor_rejects_candidate_from_previous_run_or_source(
    tmp_path: Path,
) -> None:
    assembly = tmp_path / "Modules-ASM.dll"
    assembly.write_bytes(b"managed-test-bytes")
    request = _request(tmp_path)
    source = request.sources[0]
    other_source = request.sources[1]
    executor = LocalAssemblyEvidenceToolExecutor(
        metadata_runner=_MetadataRunner(),
        il_runner_factory=_ILRunner,
    )
    executor.begin_run(run_id="run-source-bound-reference")
    search = executor.execute(
        action={
            "tool": "search_dotnet_metadata",
            "arguments": _metadata_arguments("Move"),
        },
        source=source,
        observation_id="obs-001",
    )
    method = search.data["methods"][0]
    assert isinstance(method, dict)
    candidate_ref = str(method["candidate_ref"])

    with pytest.raises(ValueError, match="CANDIDATE_SOURCE_MISMATCH"):
        executor.execute(
            action={
                "tool": "inspect_method_il",
                "arguments": {"candidate_ref": candidate_ref},
            },
            source=other_source,
            observation_id="obs-002",
        )

    executor.begin_run(run_id="run-new-reference-scope")
    with pytest.raises(ValueError, match="UNVERIFIED_CANDIDATE_REFERENCE"):
        executor.execute(
            action={
                "tool": "inspect_method_il",
                "arguments": {"candidate_ref": candidate_ref},
            },
            source=source,
            observation_id="obs-001",
        )


def test_metadata_search_truncates_inside_tool_observation_budget(
    tmp_path: Path,
) -> None:
    (tmp_path / "Modules-ASM.dll").write_bytes(b"managed-test-bytes")
    source = _request(tmp_path).sources[0]
    executor = LocalAssemblyEvidenceToolExecutor(
        metadata_runner=_LargeMetadataRunner(),
        il_runner_factory=_ILRunner,
        max_results_per_search=300,
        max_model_observation_bytes=8_192,
    )
    executor.begin_run(run_id="run-metadata-truncation")

    observation = executor.execute(
        action={
            "tool": "search_dotnet_metadata",
            "arguments": _metadata_arguments("Method", limit_per_kind=50),
        },
        source=source,
        observation_id="obs-001",
    )

    encoded = json.dumps(
        observation.model_view(),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    assert len(encoded) <= 8_192
    assert observation.data["results_truncated"] is True
    assert 0 < len(observation.data["methods"]) < 300
    search_fact = observation.supported_facts()[0]
    assert search_fact["fact_type"] == "metadata_search_result"
    assert search_fact["value"]["results_truncated"] is True
    assert search_fact["canonical_claim"].endswith("results_truncated=true.")


def test_repeated_il_targets_keep_distinct_instruction_facts() -> None:
    observation = ToolObservation(
        observation_id="obs-duplicate-call",
        tool="inspect_method_il",
        source_id="source-a",
        summary="Two calls to the same target were observed.",
        data={
            "symbol": "Observed.Type.Move",
            "metadata_token": "0x06000001",
            "rva": 12,
            "has_method_body": True,
            "instruction_count": 2,
            "instructions_truncated": False,
            "instructions": [
                {
                    "offset": "IL_0000",
                    "opcode": "call",
                    "resolved": "Observed.Target.Run",
                },
                {
                    "offset": "IL_0005",
                    "opcode": "call",
                    "resolved": "Observed.Target.Run",
                },
            ],
        },
    )

    call_facts = [
        fact
        for fact in observation.supported_facts()
        if fact["fact_type"] == "call_target"
    ]

    assert len(call_facts) == 2
    assert len({fact["fact_id"] for fact in call_facts}) == 2
    assert "offset=IL_0000" in call_facts[0]["canonical_claim"]
    assert "offset=IL_0005" in call_facts[1]["canonical_claim"]


def test_source_registry_can_bind_an_exact_relative_assembly(tmp_path: Path) -> None:
    (tmp_path / "Modules-ASM.dll").write_bytes(b"managed-test-bytes")
    (tmp_path / "Vendor.dll").write_bytes(b"vendor-noise")
    source = evidence_discovery_source_from_definition(
        SourceDefinition(
            source_id="r8-modules",
            source_type="decompiled_api",
            root_path=tmp_path,
            allowed_extensions=frozenset({".dll"}),
            metadata={
                "evidence_discovery_kind": "unity_script_assembly",
                "evidence_class": "supplied_r8_unity_export",
                "description": "R8 Modules assembly supplied by the user.",
                "evidence_authority": "supporting",
                "allowed_tools": [
                    "search_dotnet_metadata",
                    "inspect_method_il",
                ],
                "assembly_relative_paths": ["Modules-ASM.dll"],
                "version_identity": {"game_release": "R8"},
            },
        )
    )
    executor = LocalAssemblyEvidenceToolExecutor(
        metadata_runner=_MetadataRunner(),
        il_runner_factory=_ILRunner,
    )
    executor.begin_run(run_id="run-source-registry-binding")

    search = executor.execute(
        action={
            "tool": "search_dotnet_metadata",
            "arguments": _metadata_arguments("Move"),
        },
        source=source,
        observation_id="obs-001",
    )

    assert search.data["assemblies_discovered"] == 1
    assert search.data["assemblies"][0]["relative_path"] == "Modules-ASM.dll"
    assert source.model_view()["assembly_relative_paths"] == ["Modules-ASM.dll"]
    assert source.source_authority == "supporting"
    assert source.model_view()["source_authority"] == "supporting"


@pytest.mark.parametrize("authority", [None, "invalid"])
def test_source_registry_rejects_missing_or_invalid_evidence_authority(
    tmp_path: Path,
    authority: str | None,
) -> None:
    (tmp_path / "Modules-ASM.dll").write_bytes(b"managed-test-bytes")
    metadata = {
        "evidence_discovery_kind": "unity_script_assembly",
        "evidence_class": "supplied_r8_unity_export",
        "description": "R8 Modules assembly supplied by the user.",
        "allowed_tools": ["search_dotnet_metadata", "inspect_method_il"],
        "assembly_relative_paths": ["Modules-ASM.dll"],
    }
    if authority is not None:
        metadata["evidence_authority"] = authority
    definition = SourceDefinition(
        source_id="r8-modules",
        source_type="decompiled_api",
        root_path=tmp_path,
        allowed_extensions=frozenset({".dll"}),
        metadata=metadata,
    )

    with pytest.raises(ValueError, match="authority"):
        evidence_discovery_source_from_definition(definition)


def test_source_version_identity_must_match_live_assembly(tmp_path: Path) -> None:
    (tmp_path / "Modules-ASM.dll").write_bytes(b"managed-test-bytes")
    source = EvidenceDiscoverySource(
        source_id="r8-modules",
        source_type="decompiled_api",
        kind="unity_script_assembly",
        evidence_class="supplied_r8_unity_export",
        source_authority="supporting",
        description="R8 Modules assembly supplied by the user.",
        root_path=tmp_path,
        allowed_tools=("search_dotnet_metadata", "inspect_method_il"),
        assembly_relative_paths=("Modules-ASM.dll",),
        version_identity={
            "assembly_sha256": "F" * 64,
            "module_mvid": "00000000-0000-0000-0000-000000000002",
        },
    )
    executor = LocalAssemblyEvidenceToolExecutor(
        metadata_runner=_MetadataRunner(),
        il_runner_factory=_ILRunner,
    )
    executor.begin_run(run_id="run-source-identity-mismatch")

    with pytest.raises(ValueError, match="SOURCE_VERSION_IDENTITY_MISMATCH"):
        executor.execute(
            action={
                "tool": "search_dotnet_metadata",
                "arguments": _metadata_arguments("movement"),
            },
            source=source,
            observation_id="obs-001",
        )


def test_machine_local_registry_loader_uses_exact_schema(tmp_path: Path) -> None:
    (tmp_path / "Modules-ASM.dll").write_bytes(b"managed-test-bytes")
    registry = tmp_path / "sources.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": "evidence_discovery_source_registry_v1",
                "sources": [
                    {
                        "source_id": "r8-modules",
                        "source_type": "decompiled_api",
                        "root_path": str(tmp_path),
                        "metadata": {
                            "evidence_discovery_kind": "unity_script_assembly",
                            "evidence_class": "supplied_r8_unity_export",
                            "description": "R8 Modules assembly supplied by the user.",
                            "evidence_authority": "supporting",
                            "allowed_tools": [
                                "search_dotnet_metadata",
                                "inspect_method_il",
                            ],
                            "assembly_relative_paths": ["Modules-ASM.dll"],
                            "version_identity": {"game_release": "R8"},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    sources = load_evidence_discovery_sources(registry)

    assert len(sources) == 1
    assert sources[0].source_id == "r8-modules"
    assert sources[0].assembly_relative_paths == ("Modules-ASM.dll",)


def test_intelligent_factory_runs_inside_graph_and_stops_after_evidence(
    tmp_path: Path,
) -> None:
    model = _ScriptedModel(
        [
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("movement"),
                "evidence_need": "Discover exact movement metadata.",
                "derived_from_observation_ids": [],
            },
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Read exact IL from the observed method.",
                "derived_from_observation_ids": ["obs-001"],
            },
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [
                    {
                        "claim": "Observed inspected symbol: Observed.Type.Move.",
                        "claim_status": "observed",
                        "observation_ids": ["obs-002"],
                        "limitations": [],
                    }
                ],
                "unresolved_questions": ["Runtime movement remains unresolved."],
                "missing_capabilities": [],
            },
        ]
    )
    factory = IntelligentEvidencePackFactory(
        specialist=EvidenceDiscoverySpecialist(
            model=model,
            tool_executor=_ObservedToolExecutor(),
        ),
        sources=_request(tmp_path).sources,
    )
    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        evidence_pack_factory=factory,
        use_default_proposal_git_binding=False,
        stop_after_evidence=True,
    )
    state = create_initial_state(
        run_id="run_intelligent_evidence",
        request_id="req_intelligent_evidence",
        user_request="Discover exact WallCrawler hook evidence.",
        target_domain="gtfo",
        target_mod="WallCrawler",
    )

    result = graph.invoke(state)

    assert result["current_stage"] == "evidence_retrieval"
    assert "implementation_plan" not in result["artifacts"]
    assert factory.last_result is not None
    evidence_ref = ArtifactRef(
        feature_id=result["feature_id"],
        artifact_type="evidence_pack",
        path=result["artifacts"]["evidence_pack"],
        artifact_hash=result["artifact_hashes"]["evidence_pack"],
    )
    artifact = store.read(evidence_ref)["data"]
    assert artifact["run_status"] == "completed"
    assert artifact["input_audit"]["manual_symbol_count"] == 0
    assert artifact["intelligence_transfer"]["followup_selection_by_platform"] is True
    assert [item["tool"] for item in artifact["tool_trace_summary"]] == [
        "search_dotnet_metadata",
        "inspect_method_il",
    ]
    assert artifact["evidence_conclusions"][0]["claim_status"] == "observed"
    assert artifact["model_action_trace"][0]["action"]["tool"] == (
        "search_dotnet_metadata"
    )
    assert len(artifact["model_action_trace"][0]["action_sha256"]) == 64
    assert len(artifact["observation_trace"][0]["observation_sha256"]) == 64
    assert len(artifact["prompt_contract"]["initial_context_sha256"]) == 64
    assert artifact["budget_summary"]["model_steps_used"] == 3
    assert str(tmp_path) not in json.dumps(artifact, ensure_ascii=False)


class _ChatModel(BaseLLM):
    def __init__(self) -> None:
        self.messages: list[Message] = []

    def chat(self, messages: list[Message], trace=None, **kwargs) -> ChatResponse:
        self.validate_messages(messages)
        self.messages = messages
        return ChatResponse(
            content=json.dumps(
                {
                    "action": "finish",
                    "decision": "needs_more_evidence",
                    "evidence_conclusions": [],
                    "unresolved_questions": ["No tool call in adapter test."],
                    "missing_capabilities": [],
                }
            ),
            model="injected-chat-model",
        )


class _AgentTurnClient:
    provider = "test_agent_turn"
    model = "test-agent-model"

    def __init__(self) -> None:
        self.requests = []
        self.responses = [
            AgentTurnResponse(
                provider=self.provider,
                model=self.model,
                content=None,
                tool_calls=(
                    AgentToolCall(
                        call_id="call-test-001",
                        name="search_dotnet_metadata",
                        arguments={
                            "source_id": "current-interop",
                            "queries": ["movement"],
                            "result_kinds": ["methods"],
                            "limit_per_kind": 10,
                            "evidence_need": "Find exact movement metadata.",
                            "derived_from_observation_ids": [],
                        },
                    ),
                ),
                stop_reason="tool_calls",
                request_id="request-test-001",
                usage=AgentUsage(input_tokens=10, output_tokens=5),
                provider_state={"tool_calls": [{"id": "call-test-001"}]},
            ),
            AgentTurnResponse(
                provider=self.provider,
                model=self.model,
                content=json.dumps(
                    {
                        "action": "finish",
                        "decision": "needs_more_evidence",
                        "evidence_conclusions": [],
                        "unresolved_questions": ["More evidence is required."],
                        "missing_capabilities": [],
                    }
                ),
                stop_reason="stop",
                request_id="request-test-002",
                usage=AgentUsage(input_tokens=20, output_tokens=7),
            ),
        ]

    def complete_turn(self, request):
        self.requests.append(request)
        return self.responses.pop(0)


def test_agent_turn_model_maps_native_tool_call_and_bound_observation() -> None:
    client = _AgentTurnClient()
    model = EvidenceDiscoveryAgentModel(
        client,
        disclosure=EvidenceDiscoveryDisclosure(
            approved=True,
            approval_id="approval-agent-turn-001",
            destination={"provider": client.provider, "model": client.model},
            approved_data_classes=EVIDENCE_DISCOVERY_DISCLOSURE_DATA_CLASSES,
        ),
    )

    first = json.loads(
        model.complete(
            (
                {"role": "system", "content": {"contract": "v2"}},
                {"role": "user", "content": {"required_next_action": "use_tool_or_finish"}},
            )
        )
    )
    second = json.loads(
        model.complete(
            (
                {"role": "system", "content": {"contract": "v2"}},
                {"role": "tool", "content": {"observation_id": "obs-001"}},
                {"role": "user", "content": {"required_next_action": "finish"}},
            )
        )
    )

    assert first == {
        "action": "use_tool",
        "tool": "search_dotnet_metadata",
        "source_id": "current-interop",
        "arguments": _metadata_arguments("movement", limit_per_kind=10),
        "evidence_need": "Find exact movement metadata.",
        "derived_from_observation_ids": [],
    }
    assert second["action"] == "finish"
    assert client.requests[0].tool_choice == "auto"
    assert client.requests[1].tools == ()
    assert client.requests[1].tool_choice == "none"
    response_format = client.requests[1].response_format
    assert response_format is not None
    assert response_format.schema["required"] == [
        "action",
        "decision",
        "evidence_conclusions",
        "unresolved_questions",
        "missing_capabilities",
    ]
    assert response_format.schema["properties"]["evidence_conclusions"]["items"][
        "required"
    ] == ["claim", "claim_status", "observation_ids", "limitations"]
    assert client.requests[1].tool_results[0].call_id == "call-test-001"
    assert client.requests[1].tool_result_insert_index == 1
    assert model.usage_records[1]["total_tokens"] == 27


def test_agent_turn_source_identifier_selection_preserves_pending_tool_result_binding() -> None:
    client = _AgentTurnClient()
    client.responses.insert(
        1,
        AgentTurnResponse(
            provider=client.provider,
            model=client.model,
            content=json.dumps(
                {
                    "action": "select_observed_identifiers",
                    "selection_ids": ["s01"],
                }
            ),
            stop_reason="stop",
            request_id="request-source-selection-001",
            usage=AgentUsage(input_tokens=12, output_tokens=4),
        ),
    )
    model = EvidenceDiscoveryAgentModel(
        client,
        disclosure=EvidenceDiscoveryDisclosure(
            approved=True,
            approval_id="approval-agent-turn-source-selection-001",
            destination={"provider": client.provider, "model": client.model},
            approved_data_classes=EVIDENCE_DISCOVERY_DISCLOSURE_DATA_CLASSES,
        ),
    )

    model.complete(
        (
            {"role": "system", "content": {"contract": "v2"}},
            {"role": "user", "content": {"required_next_action": "use_tool"}},
        )
    )
    selection = json.loads(
        model.complete(
            (
                {"role": "system", "content": {"contract": "v2"}},
                {
                    "role": "user",
                    "content": {
                        "required_next_action": "source_identifier_selection",
                        "observed_identifier_inventory": [
                            {
                                "selection_id": "s01",
                                "observed_identifier": "ObservedSignal",
                            }
                        ],
                    },
                },
            )
        )
    )
    finish = json.loads(
        model.complete(
            (
                {"role": "system", "content": {"contract": "v2"}},
                {"role": "tool", "content": {"observation_id": "obs-001"}},
                {"role": "user", "content": {"required_next_action": "finish"}},
            )
        )
    )

    assert selection == {
        "action": "select_observed_identifiers",
        "selection_ids": ["s01"],
    }
    assert finish["action"] == "finish"
    assert client.requests[1].tools == ()
    assert client.requests[1].tool_results == ()
    assert client.requests[2].tool_results[0].call_id == "call-test-001"
    assert client.requests[2].provider_state == {
        "tool_calls": [{"id": "call-test-001"}]
    }


def test_agent_turn_required_tool_action_uses_existing_native_tool_contract() -> None:
    client = _AgentTurnClient()
    model = EvidenceDiscoveryAgentModel(
        client,
        disclosure=EvidenceDiscoveryDisclosure(
            approved=True,
            approval_id="approval-agent-turn-required-tool-001",
            destination={"provider": client.provider, "model": client.model},
            approved_data_classes=EVIDENCE_DISCOVERY_DISCLOSURE_DATA_CLASSES,
        ),
    )

    action = json.loads(
        model.complete(
            (
                {"role": "system", "content": {"contract": "v2"}},
                {"role": "user", "content": {"required_next_action": "use_tool"}},
            )
        )
    )

    assert action["action"] == "use_tool"
    assert client.requests[0].tools
    assert client.requests[0].tool_choice == "required"
    assert client.requests[0].response_format is None


def test_agent_turn_open_requirement_followup_exposes_only_frozen_family_tool() -> None:
    client = _AgentTurnClient()
    model = EvidenceDiscoveryAgentModel(
        client,
        disclosure=EvidenceDiscoveryDisclosure(
            approved=True,
            approval_id="approval-agent-turn-followup-tool-001",
            destination={"provider": client.provider, "model": client.model},
            approved_data_classes=EVIDENCE_DISCOVERY_DISCLOSURE_DATA_CLASSES,
        ),
    )

    model.complete(
        (
            {"role": "system", "content": {"contract": "v2"}},
            {
                "role": "user",
                "content": {
                    "message_type": "frozen_actual_plan",
                    "agent_discovery": {},
                },
            },
            {
                "role": "user",
                "content": {
                    "message_type": "tool_action_validation_error",
                    "error_code": "OPEN_REQUIREMENT_FOLLOWUP_REQUIRED",
                },
            },
            {"role": "user", "content": {"required_next_action": "use_tool"}},
        )
    )

    assert client.requests[0].tool_choice == "required"
    assert [tool.name for tool in client.requests[0].tools] == [
        "search_dotnet_metadata"
    ]
    metadata_tool = client.requests[0].tools[0]
    assert set(metadata_tool.parameters["properties"]) == {
        "source_id",
        "family_id",
    }
    assert metadata_tool.parameters["required"] == ["source_id", "family_id"]


def test_agent_turn_actual_plan_exposes_only_stable_family_selection() -> None:
    class _FamilySelectionClient:
        provider = "test_agent_turn"
        model = "test-agent-model"

        def __init__(self) -> None:
            self.requests = []

        def complete_turn(self, request):
            self.requests.append(request)
            return AgentTurnResponse(
                provider=self.provider,
                model=self.model,
                content=None,
                tool_calls=(
                    AgentToolCall(
                        call_id="call-family-001",
                        name="search_dotnet_metadata",
                        arguments={
                            "source_id": "current-interop",
                            "family_id": "request-derived-behavior",
                        },
                    ),
                ),
                stop_reason="tool_calls",
                request_id="request-family-001",
                usage=AgentUsage(input_tokens=10, output_tokens=5),
            )

    client = _FamilySelectionClient()
    model = EvidenceDiscoveryAgentModel(
        client,
        local_execution=EvidenceDiscoveryLocalExecution(
            endpoint="http://127.0.0.1:11434",
            provider=client.provider,
            model=client.model,
        ),
    )

    action = json.loads(
        model.complete(
            (
                {"role": "system", "content": {"contract": "v2"}},
                {
                    "role": "user",
                    "content": {
                        "message_type": "frozen_actual_plan",
                        "agent_discovery": {},
                    },
                },
            )
        )
    )

    assert action == _family_selection("request-derived-behavior")
    metadata_tool = next(
        tool
        for tool in client.requests[0].tools
        if tool.name == "search_dotnet_metadata"
    )
    assert set(metadata_tool.parameters["properties"]) == {
        "source_id",
        "family_id",
    }
    assert metadata_tool.parameters["required"] == ["source_id", "family_id"]
    assert "literal-substring OR union" in metadata_tool.description
    assert "Broad terms expand" in metadata_tool.description


def test_agent_turn_family_selection_rejects_provider_observation_identity() -> None:
    class _LeakingObservationIdentityClient:
        provider = "test_agent_turn"
        model = "test-agent-model"

        def complete_turn(self, request):
            return AgentTurnResponse(
                provider=self.provider,
                model=self.model,
                content=None,
                tool_calls=(
                    AgentToolCall(
                        call_id="call-family-stale-observation-001",
                        name="search_dotnet_metadata",
                        arguments={
                            "source_id": "current-interop",
                            "family_id": "request-derived-behavior",
                            "derived_from_observation_ids": ["obs-stale"],
                        },
                    ),
                ),
                stop_reason="tool_calls",
                request_id="request-family-stale-observation-001",
                usage=AgentUsage(input_tokens=10, output_tokens=5),
            )

    client = _LeakingObservationIdentityClient()
    model = EvidenceDiscoveryAgentModel(
        client,
        local_execution=EvidenceDiscoveryLocalExecution(
            endpoint="http://127.0.0.1:11434",
            provider=client.provider,
            model=client.model,
        ),
    )

    with pytest.raises(
        ValueError,
        match="QUERY_FAMILY_SELECTION_ARGUMENTS_INVALID",
    ):
        model.complete(
            (
                {"role": "system", "content": {"contract": "v2"}},
                {
                    "role": "user",
                    "content": {
                        "message_type": "frozen_actual_plan",
                        "agent_discovery": {},
                    },
                },
            )
        )


def test_agent_turn_model_preserves_provider_and_adapter_tool_names_on_rejection() -> None:
    provider_diagnostic = {
        "api_type": "openai_compatible_chat_completions",
        "streaming": False,
        "provider_request_id": "request-tool-name-mismatch",
        "finish_reason": "tool_calls",
        "tool_calls": [
            {
                "tool_call_id": "call-tool-name-mismatch",
                "provider_reported_tool_name": "search_dotnet_metadata",
                "adapter_extracted_tool_name": "functions.search_dotnet_metadata",
                "normalized_tool_name": "functions.search_dotnet_metadata",
                "normalization_applied": False,
                "arguments_valid_json": True,
                "arguments_is_object": True,
                "arguments_sha256": "A" * 64,
            }
        ],
        "usage": {
            "input_tokens": 41,
            "output_tokens": 3,
            "total_tokens": 44,
            "reasoning_tokens": 0,
            "cached_input_tokens": 0,
        },
    }

    class _ToolNameMismatchClient:
        provider = "qwen_chat"
        model = "qwen3.6-plus"

        def complete_turn(self, request):
            return AgentTurnResponse(
                provider=self.provider,
                model=self.model,
                content=None,
                tool_calls=(
                    AgentToolCall(
                        call_id="call-tool-name-mismatch",
                        name="functions.search_dotnet_metadata",
                        arguments={},
                    ),
                ),
                stop_reason="tool_calls",
                request_id="request-tool-name-mismatch",
                usage=AgentUsage(input_tokens=41, output_tokens=3),
                provider_diagnostic=provider_diagnostic,
            )

    client = _ToolNameMismatchClient()
    model = EvidenceDiscoveryAgentModel(
        client,
        disclosure=EvidenceDiscoveryDisclosure(
            approved=True,
            approval_id="approval-tool-name-mismatch",
            destination={"provider": client.provider, "model": client.model},
            approved_data_classes=EVIDENCE_DISCOVERY_DISCLOSURE_DATA_CLASSES,
        ),
    )

    with pytest.raises(ValueError, match="UNKNOWN_EVIDENCE_TOOL"):
        model.complete(
            (
                {"role": "system", "content": {"contract": "v2"}},
                {"role": "user", "content": {"required_next_action": "use_tool"}},
            )
        )

    assert model.model_call_count == 1
    assert model.accepted_action_count == 0
    assert model.provider_turn_records == (provider_diagnostic,)
    assert model.usage_records[0]["total_tokens"] == 44


def test_agent_turn_model_records_local_execution_without_disclosure() -> None:
    client = _AgentTurnClient()
    model = EvidenceDiscoveryAgentModel(
        client,
        local_execution=EvidenceDiscoveryLocalExecution(
            endpoint="http://127.0.0.1:11434",
            provider="ollama_chat_local",
            model="qwen3:4b-instruct",
        ),
    )

    record = model.disclosure_record
    assert record["approved"] is False
    assert record["execution_kind"] == "local_agent_turn_adapter"
    assert record["scope"] == "local_loopback_only"
    assert record["destination"] == {
        "provider": "ollama_chat_local",
        "model": "qwen3:4b-instruct",
        "endpoint": "http://127.0.0.1:11434",
    }


def test_agent_turn_model_requires_exactly_one_execution_boundary() -> None:
    client = _AgentTurnClient()
    with pytest.raises(
        ValueError, match="EVIDENCE_MODEL_EXECUTION_BOUNDARY_MUST_BE_EXACTLY_ONE"
    ):
        EvidenceDiscoveryAgentModel(client)


def test_wallcrawler_hidden_gates_separate_capability_from_convergence() -> None:
    search_observation = ToolObservation(
        observation_id="obs-001",
        tool="search_dotnet_metadata",
        source_id="source-a",
        summary="One exact movement method was returned.",
        data={
            "queries": ["movement"],
            "matched_counts": {"methods": 1, "types": 0, "fields": 0},
            "returned_counts": {"methods": 1, "types": 0, "fields": 0},
            "results_truncated": False,
            "truncated_by_kind": {
                "methods": False,
                "types": False,
                "fields": False,
            },
        },
    )
    inspection_observation = ToolObservation(
        observation_id="obs-002",
        tool="inspect_method_il",
        source_id="source-a",
        summary="Read exact IL for EnemyLocomotion.Move.",
        data={
            "symbol": "EnemyLocomotion.Move",
            "metadata_token": "0x06000001",
            "rva": 12,
            "has_method_body": True,
            "instruction_count": 1,
            "instructions_truncated": False,
            "instructions": [
                {
                    "offset": "IL_0000",
                    "opcode": "ret",
                    "resolved": None,
                }
            ],
        },
    )
    exact_claim = "Observed inspected symbol: EnemyLocomotion.Move."
    pack = {
        "run_status": "completed",
        "model_action_trace": [
            {
                "status": "accepted",
                "action": {
                    "action": "use_tool",
                    "tool": "search_dotnet_metadata",
                    "source_id": "source-a",
                    "arguments": {"queries": ["movement"]},
                },
            },
            {
                "status": "accepted",
                "action": {
                    "action": "use_tool",
                    "tool": "inspect_method_il",
                    "source_id": "source-a",
                    "arguments": {"candidate_ref": "candidate-001"},
                },
            },
            {
                "status": "accepted",
                "action": {
                    "action": "finish",
                    "decision": "needs_more_evidence",
                },
            },
        ],
        "tool_trace_summary": [
            {
                "observation_id": "obs-001",
                "tool": "search_dotnet_metadata",
                "source_id": "source-a",
            },
            {
                "observation_id": "obs-002",
                "tool": "inspect_method_il",
                "source_id": "source-a",
            },
        ],
        "observation_trace": [
            {
                "observation_id": observation.observation_id,
                "tool": observation.tool,
                "source_id": observation.source_id,
                "observation_sha256": observation.identity_sha256(),
            }
            for observation in (search_observation, inspection_observation)
        ],
        "evidence_conclusions": [
            {
                "claim": exact_claim,
                "claim_status": "observed",
                "observation_ids": ["obs-002"],
                "limitations": ["PersistentID region binding remains unresolved."],
            }
        ],
        "observation_fact_catalog": inspection_observation.supported_facts(),
        "verified_findings": [
            {
                "claim": exact_claim,
                "claim_status": "observed",
                "observation_ids": ["obs-002"],
                "limitations": ["PersistentID region binding remains unresolved."],
            }
        ],
        "unresolved_questions": ["Which PersistentID identifies the map region?"],
        "budget_summary": {"model_steps_used": 3, "tool_calls_used": 2},
        "provenance_validation": {
            "all_method_inspections_derived_from_observations": True
        },
        "input_audit": {
            "manual_symbol_count": 0,
            "manual_tool_sequence_count": 0,
            "precomputed_report_count": 0,
            "operator_intervention_count": 0,
        },
        "items": [
            {
                "retrieval_method": "agent_selected_cli_metadata_il_read",
                "symbol": "EnemyLocomotion.Move",
            }
        ],
        "can_generate_patch": False,
    }

    exact_finish = {
        "action": "finish",
        "decision": "needs_more_evidence",
        "evidence_conclusions": deepcopy(pack["evidence_conclusions"]),
        "unresolved_questions": deepcopy(pack["unresolved_questions"]),
        "missing_capabilities": [],
    }
    _validate_finish(
        exact_finish,
        {
            "obs-001": search_observation,
            "obs-002": inspection_observation,
        },
    )
    result = evaluate_wallcrawler_local_evidence(
        evidence_pack=pack,
        current_stage="evidence_retrieval",
        forbidden_artifacts=[],
    )
    assert result["capability_gate"]["passed"] is True
    assert result["capability_gate"]["checks"][
        "il_referencing_conclusion_present"
    ] is True
    assert "grounded_il_conclusion" not in result["capability_gate"]["checks"]
    assert result["convergence_gate"]["passed"] is True
    assert result["semantic_gate"]["passed"] is True
    assert result["semantic_gate"]["fact_catalog_status"] == "valid"
    assert result["semantic_gate"]["failure_reasons"] == []

    overclaim_pack = deepcopy(pack)
    overclaim = (
        "EnemyLocomotion.Move is a viable Hook point, suggesting movement logic "
        "may reside in a base class."
    )
    overclaim_pack["evidence_conclusions"][0]["claim"] = overclaim
    overclaim_pack["verified_findings"][0]["claim"] = overclaim
    overclaim_finish = deepcopy(exact_finish)
    overclaim_finish["evidence_conclusions"][0]["claim"] = overclaim
    with pytest.raises(
        ValueError,
        match="OBSERVED_CONCLUSION_CANONICAL_FACT_MISMATCH",
    ):
        _validate_finish(
            overclaim_finish,
            {
                "obs-001": search_observation,
                "obs-002": inspection_observation,
            },
        )
    result = evaluate_wallcrawler_local_evidence(
        evidence_pack=overclaim_pack,
        current_stage="evidence_retrieval",
        forbidden_artifacts=[],
    )
    assert result["capability_gate"]["passed"] is True
    assert result["semantic_gate"]["passed"] is False
    assert result["semantic_gate"]["checks"][
        "observed_claims_match_supported_facts"
    ] is False
    assert result["semantic_gate"]["unsupported_observed_claim_indexes"] == [0]
    assert "observed_claim_semantic_mismatch" in result["semantic_gate"][
        "failure_reasons"
    ]

    missing_catalog_pack = deepcopy(pack)
    missing_catalog_pack.pop("observation_fact_catalog")
    result = evaluate_wallcrawler_local_evidence(
        evidence_pack=missing_catalog_pack,
        current_stage="evidence_retrieval",
        forbidden_artifacts=[],
    )
    assert result["semantic_gate"]["passed"] is False
    assert result["semantic_gate"]["fact_catalog_status"] == "missing"
    assert result["semantic_gate"]["failure_reasons"] == [
        "observation_fact_catalog_missing"
    ]
    assert result["semantic_gate"]["checks"][
        "observed_claims_match_supported_facts"
    ] is None
    assert result["semantic_gate"]["unsupported_observed_claim_indexes"] == []

    forged_fact_pack = deepcopy(pack)
    forged_fact = forged_fact_pack["observation_fact_catalog"][0]
    forged_fact["canonical_claim"] = (
        "EnemyLocomotion.Move is a viable Hook point for wall traversal."
    )
    forged_digest = hashlib.sha256(
        json.dumps(
            {
                "observation_id": forged_fact["observation_id"],
                "observation_sha256": forged_fact["observation_sha256"],
                "source_id": forged_fact["source_id"],
                "fact_type": forged_fact["fact_type"],
                "subject": forged_fact["subject"],
                "value": forged_fact["value"],
                "canonical_claim": forged_fact["canonical_claim"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:16]
    forged_fact["fact_id"] = (
        f"{forged_fact['observation_id']}:{forged_fact['fact_type']}:"
        f"{forged_digest}"
    )
    result = evaluate_wallcrawler_local_evidence(
        evidence_pack=forged_fact_pack,
        current_stage="evidence_retrieval",
        forbidden_artifacts=[],
    )
    assert result["semantic_gate"]["fact_catalog_status"] == "invalid"
    assert result["semantic_gate"]["failure_reasons"] == [
        "observation_fact_catalog_integrity_invalid"
    ]

    for field_name, invalid_value in (
        ("observation_id", "obs-unknown"),
        ("source_id", "source-b"),
        ("observation_sha256", "0" * 64),
    ):
        mismatched_pack = deepcopy(pack)
        mismatched_pack["observation_fact_catalog"][0][field_name] = invalid_value
        result = evaluate_wallcrawler_local_evidence(
            evidence_pack=mismatched_pack,
            current_stage="evidence_retrieval",
            forbidden_artifacts=[],
        )
        assert result["semantic_gate"]["fact_catalog_status"] == "invalid"
        assert "observation_fact_catalog_integrity_invalid" in result[
            "semantic_gate"
        ]["failure_reasons"]

    mismatched_tool_pack = deepcopy(pack)
    mismatched_tool_pack["tool_trace_summary"][1]["tool"] = "search_dotnet_metadata"
    mismatched_tool_pack["observation_trace"][1]["tool"] = "search_dotnet_metadata"
    result = evaluate_wallcrawler_local_evidence(
        evidence_pack=mismatched_tool_pack,
        current_stage="evidence_retrieval",
        forbidden_artifacts=[],
    )
    assert result["semantic_gate"]["fact_catalog_status"] == "invalid"
    assert "observation_fact_catalog_integrity_invalid" in result["semantic_gate"][
        "failure_reasons"
    ]

    mismatched_trace_hash_pack = deepcopy(pack)
    mismatched_trace_hash_pack["observation_trace"][1]["observation_sha256"] = (
        "f" * 64
    )
    result = evaluate_wallcrawler_local_evidence(
        evidence_pack=mismatched_trace_hash_pack,
        current_stage="evidence_retrieval",
        forbidden_artifacts=[],
    )
    assert result["semantic_gate"]["fact_catalog_status"] == "invalid"
    assert "observation_fact_catalog_integrity_invalid" in result["semantic_gate"][
        "failure_reasons"
    ]

    abstention_pack = deepcopy(pack)
    abstention_pack["evidence_conclusions"] = [
        {
            "claim": "Hook viability remains unknown.",
            "claim_status": "unknown",
            "observation_ids": [],
            "limitations": ["The available evidence does not establish runtime use."],
        }
    ]
    abstention_pack["verified_findings"] = []
    result = evaluate_wallcrawler_local_evidence(
        evidence_pack=abstention_pack,
        current_stage="evidence_retrieval",
        forbidden_artifacts=[],
    )
    assert result["semantic_gate"]["passed"] is True
    assert result["capability_gate"]["passed"] is False

    truncated_nonexistence_pack = deepcopy(pack)
    truncated_nonexistence_pack["evidence_conclusions"][0]["claim"] = (
        "EnemyLocomotion.Missing does not exist."
    )
    truncated_nonexistence_pack["evidence_conclusions"][0]["observation_ids"] = [
        "obs-001"
    ]
    truncated_nonexistence_pack["observation_fact_catalog"] = (
        search_observation.supported_facts()
    )
    truncated_nonexistence_pack["verified_findings"] = []
    result = evaluate_wallcrawler_local_evidence(
        evidence_pack=truncated_nonexistence_pack,
        current_stage="evidence_retrieval",
        forbidden_artifacts=[],
    )
    assert result["semantic_gate"]["passed"] is False

    four_turn_pack = deepcopy(pack)
    four_turn_pack["budget_summary"]["model_steps_used"] = 4
    result = evaluate_wallcrawler_local_evidence(
        evidence_pack=four_turn_pack,
        current_stage="evidence_retrieval",
        forbidden_artifacts=[],
    )
    assert result["capability_gate"]["passed"] is True
    assert result["convergence_gate"]["passed"] is False


def test_wallcrawler_post_run_evaluator_is_provider_neutral(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def evaluate(**kwargs):
        calls.append(kwargs)
        return {"semantic_gate": {"passed": False}}

    monkeypatch.setattr(
        "src.mod_agent.intelligent_evidence_only.evaluate_wallcrawler_evidence",
        evaluate,
    )
    pack = {"run_status": "completed"}

    result = _post_run_acceptance(
        target_domain="gtfo",
        target_mod="WallCrawler",
        evidence_pack=pack,
        current_stage="evidence_retrieval",
        forbidden_artifacts=[],
    )

    assert result == {"semantic_gate": {"passed": False}}
    assert calls == [
        {
            "evidence_pack": pack,
            "current_stage": "evidence_retrieval",
            "forbidden_artifacts": [],
        }
    ]
    assert _post_run_acceptance(
        target_domain="gtfo",
        target_mod="AnotherMod",
        evidence_pack=pack,
        current_stage="evidence_retrieval",
        forbidden_artifacts=[],
    ) is None


def test_chat_adapter_requires_exact_one_run_disclosure() -> None:
    with pytest.raises(ValueError, match="EVIDENCE_MODEL_DISCLOSURE_NOT_APPROVED"):
        ChatEvidenceDiscoveryModel(
            _ChatModel(),
            disclosure=EvidenceDiscoveryDisclosure(
                approved=False,
                approval_id="",
                destination={"provider": "test", "model": "test"},
                approved_data_classes=EVIDENCE_DISCOVERY_DISCLOSURE_DATA_CLASSES,
            ),
        )


def test_chat_adapter_serializes_tool_observation_as_supported_user_role() -> None:
    llm = _ChatModel()
    adapter = ChatEvidenceDiscoveryModel(
        llm,
        disclosure=EvidenceDiscoveryDisclosure(
            approved=True,
            approval_id="approval-test-001",
            destination={"provider": "test", "model": "injected-chat-model"},
            approved_data_classes=EVIDENCE_DISCOVERY_DISCLOSURE_DATA_CLASSES,
        ),
    )

    adapter.complete(
        (
            {"role": "system", "content": {"contract": "strict-json"}},
            {"role": "tool", "content": {"observation_id": "obs-001"}},
        )
    )

    assert [message.role for message in llm.messages] == ["system", "user"]
    assert "tool_observation" in llm.messages[1].content
    assert adapter.disclosure_record["approval_id"] == "approval-test-001"
