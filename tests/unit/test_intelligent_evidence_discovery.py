"""Intelligence-first acceptance tests for bounded evidence discovery."""

from __future__ import annotations

import json
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from src.mod_agent.evidence.discovery import (
    ChatEvidenceDiscoveryModel,
    EVIDENCE_DISCOVERY_DISCLOSURE_DATA_CLASSES,
    EvidenceDiscoveryDisclosure,
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
from src.libs.llm import (
    AgentToolCall,
    AgentTurnResponse,
    AgentUsage,
    BaseLLM,
    ChatResponse,
    Message,
)
from src.mod_agent.knowledge import SourceDefinition
from src.mod_agent.intelligent_evidence_only import load_evidence_discovery_sources


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
            return ToolObservation(
                observation_id=observation_id,
                tool="search_dotnet_metadata",
                source_id=source.source_id,
                summary="One exact method was observed.",
                data={
                    "methods": [
                        {
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
        return ToolObservation(
            observation_id=observation_id,
            tool="inspect_method_il",
            source_id=source.source_id,
            summary="Exact IL was read without target execution.",
            data={
                "method_id": "method_obs_001",
                "symbol": "Observed.Type.Move",
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
                "arguments": {"method_id": "method_obs_001"},
                "evidence_need": "Read the method body discovered in the first observation.",
                "derived_from_observation_ids": ["obs-001"],
            },
            {
                "action": "finish",
                "decision": "needs_more_evidence",
                "evidence_conclusions": [
                    {
                        "claim": "An exact movement-related method body was observed.",
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
    assert result.pack.evidence_conclusions[0]["claim_status"] == "observed"
    assert result.pack.verified_findings[0]["claim_status"] == "observed"
    assert len(result.pack.model_action_trace) == 3
    assert len(result.pack.observation_trace) == 2
    assert len(result.pack.prompt_contract["system_contract_sha256"]) == 64
    assert result.pack.model_identity["execution_kind"] == "injected_local_or_test"
    assert result.pack.budget_summary["model_steps_used"] == 3
    assert result.pack.budget_summary["total_observation_bytes_used"] > 0
    final_budget_state = model.calls[2][-1]["content"]
    assert isinstance(final_budget_state, dict)
    assert final_budget_state == {
        "message_type": "budget_state",
        "tool_calls_used": 2,
        "remaining_tool_calls": 1,
        "model_steps_used": 2,
        "remaining_model_steps": 2,
        "required_next_action": "use_tool_or_finish",
    }


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
                "arguments": {"method_id": "method_obs_001"},
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
    assert "method_obs_001" in third_turn


def test_repeated_identical_action_fails_intelligence_transfer(tmp_path: Path) -> None:
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

    result = EvidenceDiscoverySpecialist(
        model=model,
        tool_executor=_ObservedToolExecutor(),
    ).discover(_request(tmp_path))

    assert result.intelligence_transfer["unproductive_repetition_absent"] is False
    assert result.intelligence_transfer["source_selection_by_platform"] is False
    assert result.intelligence_transfer["tool_selection_by_platform"] is False


def test_unobserved_method_identity_is_rejected(tmp_path: Path) -> None:
    model = _ScriptedModel(
        [
            {
                "action": "use_tool",
                "tool": "inspect_method_il",
                "source_id": "current-interop",
                "arguments": {"method_id": "manually_supplied_method"},
                "evidence_need": "Attempt to skip discovery.",
                "derived_from_observation_ids": [],
            }
        ]
    )

    with pytest.raises(ValueError, match="UNVERIFIED_METHOD_REFERENCE"):
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
    assert result.run_status == "completed"
    assert [item["status"] for item in result.pack.model_action_trace] == [
        "rejected",
        "accepted",
    ]


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
            "arguments": {"method_id": method["method_id"]},
        },
        source=source,
        observation_id="obs-002",
    )

    assert inspection.data["metadata_token"] == "0x06000002"
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
    assert str(tmp_path) not in json.dumps(search.model_view())
    assert str(tmp_path) not in json.dumps(inspection.model_view())


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
                "arguments": {"method_id": "method_obs_001"},
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
    assert client.requests[1].tool_results[0].call_id == "call-test-001"
    assert client.requests[1].tool_result_insert_index == 1
    assert model.usage_records[1]["total_tokens"] == 27


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
