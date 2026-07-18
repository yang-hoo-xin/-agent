"""Intelligence-first acceptance tests for bounded evidence discovery."""

from __future__ import annotations

import json
import hashlib
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from src.mod_agent.evidence.discovery import (
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
)
from src.mod_agent.evidence.discovery_tools import LocalAssemblyEvidenceToolExecutor
from src.mod_agent.evidence.models import EvidenceItem
from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
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
    def __init__(self) -> None:
        self.actions: list[dict[str, object]] = []

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
                            "symbol": "Observed.Type.Move",
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
                "symbol": "Observed.Type.Move",
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
                    symbol="Observed.Type.Move",
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
    assert result.pack.evidence_conclusions[0]["claim_status"] == "observed"
    assert result.pack.verified_findings[0]["claim_status"] == "observed"
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
    assert result.pack.budget_summary["total_discovery_message_bytes"] < 16_000


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
                        "claim": "One method body was observed.",
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
                        "claim": "One exact method body was observed.",
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
                        "claim": "One exact method body was observed.",
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
                    "claim": "One exact method body was observed.",
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
    assert result.pack.budget_summary["total_discovery_message_bytes"] < 44_000
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
    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=executor,
    ).discover(_request(tmp_path))

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
                        "claim": "Observed.Type.Move has an inspected CLI method body.",
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

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=executor,
    ).discover(_request(tmp_path))

    assert result.run_status == "budget_exhausted"
    assert len(executor.actions) == 1
    assert result.pack.budget_summary["tool_calls_used"] == 1
    assert result.pack.unresolved_questions == (
        "The single exact-repeat correction opportunity was exhausted before the model finished.",
    )


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

    with pytest.raises(ValueError, match="UNVERIFIED_CANDIDATE_REFERENCE"):
        EvidenceDiscoverySpecialist(
            model=model,
            tool_executor=_ObservedToolExecutor(),
        ).discover(_request(tmp_path))


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


def test_source_version_identity_must_match_live_assembly(tmp_path: Path) -> None:
    (tmp_path / "Modules-ASM.dll").write_bytes(b"managed-test-bytes")
    source = EvidenceDiscoverySource(
        source_id="r8-modules",
        source_type="decompiled_api",
        kind="unity_script_assembly",
        evidence_class="supplied_r8_unity_export",
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
                        "claim": "One exact method body was observed.",
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
            },
            {"observation_id": "obs-002", "tool": "inspect_method_il"},
        ],
        "evidence_conclusions": [
            {
                "claim": "Observed inspected symbol: EnemyLocomotion.Move.",
                "claim_status": "observed",
                "observation_ids": ["obs-002"],
                "limitations": ["PersistentID region binding remains unresolved."],
            }
        ],
        "observation_fact_catalog": [
            {
                "fact_id": "obs-002:inspected_symbol:fixture",
                "observation_id": "obs-002",
                "source_id": "source-a",
                "fact_type": "inspected_symbol",
                "subject": "EnemyLocomotion.Move",
                "value": {"symbol": "EnemyLocomotion.Move"},
                "canonical_claim": (
                    "Observed inspected symbol: EnemyLocomotion.Move."
                ),
            }
        ],
        "verified_findings": [
            {
                "claim": "Observed inspected symbol: EnemyLocomotion.Move.",
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

    result = evaluate_wallcrawler_local_evidence(
        evidence_pack=pack,
        current_stage="evidence_retrieval",
        forbidden_artifacts=[],
    )
    assert result["capability_gate"]["passed"] is True
    assert result["convergence_gate"]["passed"] is True
    assert result["semantic_gate"]["passed"] is True

    overclaim_pack = deepcopy(pack)
    overclaim = (
        "EnemyLocomotion.Move is a viable Hook point, suggesting movement logic "
        "may reside in a base class."
    )
    overclaim_pack["evidence_conclusions"][0]["claim"] = overclaim
    overclaim_pack["verified_findings"][0]["claim"] = overclaim
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
    truncated_nonexistence_pack["observation_fact_catalog"] = [
        {
            "fact_id": "obs-001:metadata_search_result:fixture",
            "observation_id": "obs-001",
            "source_id": "source-a",
            "fact_type": "metadata_search_result",
            "subject": "source-a",
            "value": {
                "matched_counts": {"methods": 20, "types": 0, "fields": 0},
                "returned_counts": {"methods": 5, "types": 0, "fields": 0},
                "results_truncated": True,
            },
            "canonical_claim": (
                "Observed metadata search result: "
                'matched_counts={"fields":0,"methods":20,"types":0}; '
                'returned_counts={"fields":0,"methods":5,"types":0}; '
                "results_truncated=true."
            ),
        }
    ]
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
