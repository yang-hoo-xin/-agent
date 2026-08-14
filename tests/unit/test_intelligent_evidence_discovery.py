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
)
from src.mod_agent.evidence.discovery_loop import (
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
)
from src.mod_agent.knowledge import SourceDefinition
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


class _ScriptedModel:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self._responses = [json.dumps(item) for item in responses]
        self.calls: list[tuple[dict[str, object], ...]] = []

    def complete(self, messages: tuple[dict[str, object], ...]) -> str:
        self.calls.append(messages)
        return self._responses.pop(0)


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
            "schema_version": "hook_discovery_search_plan_v2",
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
                },
                {
                    "lane": "exact_il_verification",
                    "tool": "inspect_method_il",
                    "source_ids": ["current-interop"],
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
    assert correction["required_next_action"] == "plan"
    assert "ES_Hitreact.ActivateState" not in json.dumps(correction)
    assert result.agent_discovery is not None
    assert result.agent_discovery["planning_status"] == "ready"
    assert result.pack.budget_summary["planning_model_steps_used"] == 2
    assert result.pack.budget_summary["total_model_steps_used"] == 5


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
    }
    supplemental = {
        "action": "use_tool",
        "tool": "search_dotnet_metadata",
        "source_id": "current-interop",
        "arguments": _metadata_arguments("guard"),
        "evidence_need": "Find guard metadata.",
        "derived_from_observation_ids": [],
    }
    actual = _validated_actual_from_plan(plan)

    with pytest.raises(
        ValueError,
        match="SUPPLEMENTAL_ACTION_OBSERVATION_BINDING_REQUIRED",
    ):
        _validate_supplemental_search(
            supplemental,
            actions=[first_action],
            agent_discovery=actual,
        )

    supplemental["derived_from_observation_ids"] = ["obs-001"]
    supplemental["evidence_need"] = "changed need"
    with pytest.raises(ValueError, match="SUPPLEMENTAL_EVIDENCE_NEED_MISMATCH"):
        _validate_supplemental_search(
            supplemental,
            actions=[first_action],
            agent_discovery=actual,
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
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": _metadata_arguments("enemy reaction"),
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
        tool_executor=_ObservedToolExecutor(),
        sources=(source,),
    )

    assert pack.agent_discovery is not None
    assert pack.prompt_contract["actual_planning_required"] is True
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


def test_phase_2_supplemental_search_rejects_already_executed_family_with_new_tuning(
    tmp_path: Path,
) -> None:
    evidence_need = "Which current managed method exposes movement?"
    plan = _actual_plan(
        behavior_goal="Find and verify a current movement method.",
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
                "arguments": {"candidate_ref": "candidate_obs_001"},
                "evidence_need": "Verify the observed movement method.",
                "derived_from_observation_ids": ["obs-001"],
            },
            {
                "action": "use_tool",
                "tool": "search_dotnet_metadata",
                "source_id": "current-interop",
                "arguments": {
                    "queries": ["movement"],
                    "result_kinds": ["types", "fields"],
                    "limit_per_kind": 5,
                },
                "evidence_need": evidence_need,
                "derived_from_observation_ids": ["obs-002"],
            },
        ]
    )
    executor = _ObservedToolExecutor()
    specialist = EvidenceDiscoverySpecialist(model=model, tool_executor=executor)

    with pytest.raises(
        ValueError,
        match="SUPPLEMENTAL_QUERY_FAMILY_ALREADY_EXECUTED",
    ):
        specialist.discover(
            replace(
                _request(tmp_path),
                natural_language_request="Find and verify a current movement method.",
                require_actual_planning=True,
            )
        )

    assert len(executor.actions) == 2
    assert specialist.runtime_diagnostics["failure_stage"] == "action_validation"


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
        "repeat_correction_and_supported_facts_v6"
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
                "Finish now with an observed or inferred conclusion whose observation_ids "
                "includes one listed inspect_method_il observation id, unless one exact "
                "unresolved gap justifies one new tool call. needs_more_evidence is valid; "
                "do not broad-search or repeat a method."
            )
        ],
        "required_next_action": "finish_or_use_tool_for_exact_gap",
    }
    assert len(result.pack.budget_summary["discovery_message_bytes_by_turn"]) == 3
    assert result.pack.budget_summary["total_discovery_message_bytes"] == sum(
        result.pack.budget_summary["discovery_message_bytes_by_turn"]
    )
    assert result.pack.budget_summary["total_discovery_message_bytes"] < 17_000


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
            "Each observed claim must exactly copy one supported_fact "
            "canonical_claim and cite only that fact's observation_id. Put any "
            "interpretation in a separate inferred conclusion with limitations."
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
    assert result.pack.budget_summary["total_discovery_message_bytes"] < 47_000
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
                {"symbol": "Observed.Type", "metadata_token": "0x02000002"}
            ],
            "fields": [
                {"symbol": "Observed.Type.Speed", "metadata_token": "0x04000002"}
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


class _ILRunner:
    def __init__(self, symbols: tuple[str, ...]) -> None:
        self.symbols = symbols

    def inspect(self, assembly_path: str | Path) -> dict[str, object]:
        assembly = Path(assembly_path)
        assert self.symbols == ("Observed.Type.Move",)
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
            "arguments": _metadata_arguments("movement"),
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
            "arguments": _metadata_arguments("movement"),
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
            "arguments": _metadata_arguments("movement", limit_per_kind=50),
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
            "arguments": _metadata_arguments("movement"),
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
