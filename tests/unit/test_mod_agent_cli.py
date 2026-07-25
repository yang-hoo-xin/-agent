"""Tests for the controlled code-generation platform CLI."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.libs.llm import (
    AgentToolCall,
    AgentTurnProviderError,
    AgentTurnResponse,
    AgentUsage,
)
from src.mod_agent import __version__
from src.mod_agent.artifacts.store import ArtifactStorePreflightError
from src.mod_agent.cli import main, plan_request
from src.mod_agent.evidence.discovery_tools import LocalAssemblyEvidenceToolExecutor
from src.mod_agent.intelligent_evidence_only import (
    IntelligentEvidenceEntryError,
    _evidence_run_failure_code,
    _failure_attribution,
    run_intelligent_evidence_only,
)


def test_mod_agent_package_imports() -> None:
    """The new platform package is importable through the repository package root."""

    assert __version__


WALLCRAWLER_REQUEST = (
    "希望让 GTFO 的怪物在配置指定的区域内，能够在原本不支持行走的墙面、"
    "斜面和天花板上移动。区域应能通过面向地图开发者的 JSON 配置；配置需要"
    "与游戏/地图数据库的真实 PersistentID 或准确等价身份建立绑定。"
)


class _CliMetadataRunner:
    def search(
        self,
        assembly_path: str | Path,
        *,
        queries: tuple[str, ...],
    ) -> dict[str, object]:
        assembly = Path(assembly_path)
        assert queries == ("movement",)
        return {
            "assembly_sha256": hashlib.sha256(assembly.read_bytes()).hexdigest().upper(),
            "module_mvid": "00000000-0000-0000-0000-000000000042",
            "methods": [
                {
                    "symbol": "Observed.Type.Move",
                    "metadata_token": "0x06000042",
                    "has_method_body": True,
                }
            ],
            "types": [],
            "fields": [],
        }


class _CliILRunner:
    def __init__(self, symbols: tuple[str, ...]) -> None:
        self.symbols = symbols

    def inspect(self, assembly_path: str | Path) -> dict[str, object]:
        assembly = Path(assembly_path)
        assert self.symbols == ("Observed.Type.Move",)
        return {
            "assembly_sha256": hashlib.sha256(assembly.read_bytes()).hexdigest().upper(),
            "module_mvid": "00000000-0000-0000-0000-000000000042",
            "methods": [
                {
                    "symbol": "Observed.Type.Move",
                    "metadata_token": "0x06000042",
                    "attributes": "Public",
                    "impl_attributes": "IL",
                    "signature_blob": "0001",
                    "rva": 42,
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


class _CliInjectedAgentAdapter:
    provider = "injected_cli_agent"
    instances: list["_CliInjectedAgentAdapter"] = []

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        max_output_tokens: int,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.turn = 0
        self.model_observations: list[object] = []
        self.__class__.instances.append(self)

    def complete_turn(self, request) -> AgentTurnResponse:
        self.turn += 1
        if request.tool_results:
            observation = request.tool_results[0].output
            self.model_observations.append(observation)
        if self.turn == 1:
            return AgentTurnResponse(
                provider=self.provider,
                model=self.model,
                content=None,
                tool_calls=(
                    AgentToolCall(
                        call_id="call-cli-001",
                        name="search_dotnet_metadata",
                        arguments={
                            "source_id": "cli-source",
                            "queries": ["movement"],
                            "result_kinds": ["methods"],
                            "limit_per_kind": 5,
                            "evidence_need": "Find one observed movement method.",
                            "derived_from_observation_ids": [],
                        },
                    ),
                ),
                stop_reason="tool_calls",
                request_id="provider-cli-001",
                usage=AgentUsage(input_tokens=10, output_tokens=5),
                provider_state={"turn": 1},
            )
        if self.turn == 2:
            observation = self.model_observations[-1]
            assert isinstance(observation, dict)
            serialized = json.dumps(observation)
            assert "method_id" not in serialized
            data = observation["data"]
            assert isinstance(data, dict)
            methods = data["methods"]
            assert isinstance(methods, list)
            method = methods[0]
            assert isinstance(method, dict)
            candidate_ref = str(method["candidate_ref"])
            return AgentTurnResponse(
                provider=self.provider,
                model=self.model,
                content=None,
                tool_calls=(
                    AgentToolCall(
                        call_id="call-cli-002",
                        name="inspect_method_il",
                        arguments={
                            "source_id": "cli-source",
                            "candidate_ref": candidate_ref,
                            "evidence_need": "Inspect the selected evidence reference.",
                            "derived_from_observation_ids": ["obs-001"],
                        },
                    ),
                ),
                stop_reason="tool_calls",
                request_id="provider-cli-002",
                usage=AgentUsage(input_tokens=20, output_tokens=5),
                provider_state={"turn": 2},
            )
        return AgentTurnResponse(
            provider=self.provider,
            model=self.model,
            content=json.dumps(
                {
                    "action": "finish",
                    "decision": "needs_more_evidence",
                    "evidence_conclusions": [
                        {
                            "claim": (
                                "Observed inspected symbol: Observed.Type.Move."
                            ),
                            "claim_status": "observed",
                            "observation_ids": ["obs-002"],
                            "limitations": [],
                        }
                    ],
                    "unresolved_questions": [
                        "Runtime movement behavior remains unresolved."
                    ],
                    "missing_capabilities": [],
                }
            ),
            stop_reason="stop",
            request_id="provider-cli-003",
            usage=AgentUsage(input_tokens=30, output_tokens=10),
        )


class _CliUnknownToolAgentAdapter:
    provider = "qwen_chat"
    instances: list["_CliUnknownToolAgentAdapter"] = []

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        max_completion_tokens: int,
    ) -> None:
        assert api_key == "test-api-key"
        self.base_url = base_url
        self.model = model
        self.max_completion_tokens = max_completion_tokens
        self.calls = 0
        self.__class__.instances.append(self)

    def complete_turn(self, request) -> AgentTurnResponse:
        self.calls += 1
        return AgentTurnResponse(
            provider=self.provider,
            model=self.model,
            content=None,
            tool_calls=(
                AgentToolCall(
                    call_id="call-cli-unknown-tool",
                    name="search_metadata",
                    arguments={},
                ),
            ),
            stop_reason="tool_calls",
            request_id="provider-cli-unknown-tool",
            usage=AgentUsage(input_tokens=53, output_tokens=7),
            provider_diagnostic={
                "api_type": "openai_compatible_chat_completions",
                "streaming": False,
                "provider_request_id": "provider-cli-unknown-tool",
                "finish_reason": "tool_calls",
                "tool_calls": [
                    {
                        "tool_call_id": "call-cli-unknown-tool",
                        "provider_reported_tool_name": "search_metadata",
                        "adapter_extracted_tool_name": "search_metadata",
                        "normalized_tool_name": "search_metadata",
                        "normalization_applied": False,
                        "arguments_valid_json": True,
                        "arguments_is_object": True,
                        "arguments_sha256": hashlib.sha256(b"{}").hexdigest(),
                    }
                ],
                "usage": {
                    "input_tokens": 53,
                    "output_tokens": 7,
                    "total_tokens": 60,
                    "reasoning_tokens": 0,
                    "cached_input_tokens": 0,
                },
            },
        )


class _CliRejectToolExecution:
    def __init__(self) -> None:
        self.actions: list[dict[str, object]] = []

    def execute(self, **kwargs):
        self.actions.append(dict(kwargs))
        raise AssertionError("an unknown model tool must not execute")


class _CliFailSecondToolExecution:
    def __init__(self, delegate: LocalAssemblyEvidenceToolExecutor) -> None:
        self.delegate = delegate
        self.dispatch_count = 0

    def begin_run(self, *, run_id: str) -> None:
        self.delegate.begin_run(run_id=run_id)

    def execute(self, **kwargs):
        self.dispatch_count += 1
        if self.dispatch_count == 2:
            raise ValueError("sensitive query text must not persist")
        return self.delegate.execute(**kwargs)


@pytest.mark.parametrize(
    ("provider_name", "adapter_name", "expected"),
    (
        (
            "search_dotnet_metadata",
            "functions.search_dotnet_metadata",
            "provider_adapter_extraction_failure",
        ),
        (
            " search_dotnet_metadata ",
            " search_dotnet_metadata ",
            "whitespace_normalization_issue",
        ),
        ("", "search_metadata", "unresolved"),
    ),
)
def test_unknown_tool_failure_attribution_uses_both_identity_layers(
    provider_name: str,
    adapter_name: str,
    expected: str,
) -> None:
    model = SimpleNamespace(
        provider_turn_records=(
            {
                "tool_calls": [
                    {
                        "provider_reported_tool_name": provider_name,
                        "adapter_extracted_tool_name": adapter_name,
                    }
                ]
            },
        )
    )

    assert _failure_attribution(
        model=model,
        error="UNKNOWN_EVIDENCE_TOOL",
    ) == expected


def test_external_provider_error_body_is_not_used_as_persisted_failure_code() -> None:
    error = AgentTurnProviderError(
        "Agent provider HTTP 400: full prompt and raw arguments"
    )

    assert _evidence_run_failure_code(error) == "AGENT_TURN_PROVIDER_ERROR"


def test_plan_request_returns_no_write_planning_result() -> None:
    """Planning stops before feature_spec without performing writes."""

    result = plan_request(
        WALLCRAWLER_REQUEST,
        target_game="GTFO",
        target_mod="WallCrawler",
    )

    assert result.status == "needs_evidence"
    assert result.command == "plan-request"
    assert result.execution_mode == "planning_only"
    assert result.writes_performed is False
    assert result.stopped_before == "feature_spec"
    assert result.request_planning_report["route"] == "game_hook_investigation"
    assert result.request_planning_report["risk_level"] == "high"
    assert result.request_planning_report["requires_hook_evidence"] is True
    assert result.request_planning_report["requires_runtime_evidence"] is True
    assert result.mod_planning_brief["request_type"]["value"] == "hook-required"
    assert result.mod_planning_brief["decision"] == "needs_evidence"
    assert result.mod_planning_brief["next_action"] == "hook discovery"
    assert result.mod_planning_brief["blockers"][0]["code"] == (
        "HOOK_EVIDENCE_REQUIRED"
    )


def test_cli_plan_request_prints_planning_only_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI emits both planning payloads and no downstream artifacts."""

    exit_code = main(
        [
            "plan-request",
            WALLCRAWLER_REQUEST,
            "--target-game",
            "GTFO",
            "--target-mod",
            "WallCrawler",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["status"] == "needs_evidence"
    assert payload["command"] == "plan-request"
    assert payload["execution_mode"] == "planning_only"
    assert payload["writes_performed"] is False
    assert payload["stopped_before"] == "feature_spec"
    assert payload["request_planning_report"]["target_mod"] == "WallCrawler"
    assert payload["mod_planning_brief"]["user_intent"]["target_game"] == "GTFO"
    assert "feature_spec" not in payload
    assert "patch_proposal" not in payload


def test_cli_plan_request_preserves_true_config_only_route(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "plan-request",
            "default config EnableLogging false",
            "--target-mod",
            "BetterHitFeedback",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "ready_for_feature_spec"
    assert payload["request_planning_report"]["route"] == "quick_patch"
    assert payload["mod_planning_brief"]["request_type"]["value"] == "config-only"
    assert payload["writes_performed"] is False


def test_cli_confirmed_apply_is_blocked(capsys: pytest.CaptureFixture[str]) -> None:
    """Confirmed writes are blocked in Phase A."""

    exit_code = main(["apply-patch", "--confirm"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["status"] == "BLOCKED"
    assert payload["command"] == "apply-patch"
    assert payload["confirmed"] is True


def test_cli_evidence_request_emits_hard_stop_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "src.mod_agent.cli.run_gtfo_r8_evidence_only",
        lambda **_: {
            "status": "needs_more_evidence",
            "command": "evidence-request",
            "execution_mode": "evidence_only",
            "current_stage": "evidence_retrieval",
            "stopped_before": "implementation_plan",
            "forbidden_artifacts_present": [],
        },
    )

    exit_code = main(
        [
            "evidence-request",
            "WallCrawler enemy movement hook",
            "--evidence-root",
            "supplied-r8",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["execution_mode"] == "evidence_only"
    assert payload["current_stage"] == "evidence_retrieval"
    assert payload["stopped_before"] == "implementation_plan"
    assert payload["forbidden_artifacts_present"] == []


def test_cli_intelligent_evidence_request_emits_graph_stop_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "src.mod_agent.cli.run_intelligent_evidence_only",
        lambda **_: {
            "status": "completed",
            "command": "intelligent-evidence-request",
            "execution_mode": "intelligent_evidence_only",
            "current_stage": "evidence_retrieval",
            "stopped_before": "implementation_plan",
            "forbidden_artifacts_present": [],
            "source_roots_disclosed_to_model": False,
        },
    )

    exit_code = main(
        [
            "intelligent-evidence-request",
            "Discover WallCrawler hook evidence.",
            "--source-registry",
            "machine-local-sources.json",
            "--allow-evidence-disclosure",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["execution_mode"] == "intelligent_evidence_only"
    assert payload["current_stage"] == "evidence_retrieval"
    assert payload["source_roots_disclosed_to_model"] is False


def test_cli_preserves_budget_exhausted_terminal_status_without_evidence_pack(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "src.mod_agent.cli.run_intelligent_evidence_only",
        lambda **_: (_ for _ in ()).throw(
            IntelligentEvidenceEntryError(
                "EVIDENCE_RUN_VALIDATION_ERROR",
                diagnostic={
                    "run_status": "budget_exhausted",
                    "failure_diagnostics": {
                        "failure_stage": "finish_validation",
                        "symbolic_failure_code": (
                            "OBSERVED_CONCLUSION_CANONICAL_FACT_MISMATCH"
                        ),
                        "correction_attempted": False,
                        "correction_unavailable_reason": (
                            "no_remaining_model_turn"
                        ),
                    },
                },
            )
        ),
    )

    exit_code = main(
        [
            "intelligent-evidence-request",
            "Discover WallCrawler hook evidence.",
            "--source-registry",
            "machine-local-sources.json",
            "--allow-evidence-disclosure",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["status"] == "budget_exhausted"
    assert "evidence_pack" not in payload
    assert payload["diagnostic"]["failure_diagnostics"] == {
        "failure_stage": "finish_validation",
        "symbolic_failure_code": (
            "OBSERVED_CONCLUSION_CANONICAL_FACT_MISMATCH"
        ),
        "correction_attempted": False,
        "correction_unavailable_reason": "no_remaining_model_turn",
    }


def test_cli_intelligent_evidence_preflight_failure_is_structured_and_stops_execution(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    execution = {"model": False, "tool": False, "graph": False}

    monkeypatch.setattr(
        "src.mod_agent.intelligent_evidence_only.load_evidence_discovery_sources",
        lambda _path: (),
    )

    def fail_preflight(self, *, feature_id, artifact_types) -> None:
        assert feature_id.startswith("feature_")
        assert artifact_types == (
            "evidence_run_attempt",
            "request_planning_report",
            "mod_planning_brief",
            "feature_spec",
            "evidence_pack",
        )
        raise ArtifactStorePreflightError(
            artifact_type="request_planning_report",
            path_role="pending_marker",
            source_path_length=222,
            target_path_length=269,
            target_parent_exists=True,
            winerror=3,
        )

    monkeypatch.setattr(
        "src.mod_agent.intelligent_evidence_only.ArtifactStore.preflight_atomic_commit",
        fail_preflight,
    )

    def fail_model(**_kwargs):
        execution["model"] = True
        raise AssertionError("model construction must not start")

    def fail_tool(cls, _inspector_path):
        execution["tool"] = True
        raise AssertionError("tool construction must not start")

    def fail_graph(*_args, **_kwargs):
        execution["graph"] = True
        raise AssertionError("graph construction must not start")

    monkeypatch.setattr(
        "src.mod_agent.intelligent_evidence_only.OllamaChatAgentAdapter",
        fail_model,
    )
    monkeypatch.setattr(
        LocalAssemblyEvidenceToolExecutor,
        "from_inspector",
        classmethod(fail_tool),
    )
    monkeypatch.setattr(
        "src.mod_agent.intelligent_evidence_only.build_graph",
        fail_graph,
    )

    exit_code = main(
        [
            "intelligent-evidence-request",
            "Discover exact WallCrawler evidence.",
            "--source-registry",
            "unused-source-registry.json",
            "--local-ollama",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["status"] == "BLOCKED"
    assert payload["command"] == "intelligent-evidence-request"
    diagnostic = payload["diagnostic"]
    assert diagnostic == {
        "category": "infrastructure_preflight_failure",
        "component": "artifact_store",
        "stage": "artifact_preflight",
        "code": "artifact_path_unaddressable",
        "operation": "os.replace",
        "model_execution_started": False,
        "tool_execution_started": False,
        "model_call_count": 0,
        "tool_call_count": 0,
        "details": {
            "artifact_type": "request_planning_report",
            "path_role": "pending_marker",
            "source_path_length": 222,
            "target_path_length": 269,
            "target_parent_exists": True,
            "winerror": 3,
        },
    }
    assert execution == {"model": False, "tool": False, "graph": False}


def test_cli_intelligent_evidence_request_persists_candidate_binding_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "Modules-ASM.dll").write_bytes(b"managed-cli-test-bytes")
    registry_path = tmp_path / "source-registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "evidence_discovery_source_registry_v1",
                "sources": [
                    {
                        "source_id": "cli-source",
                        "source_type": "decompiled_api",
                        "root_path": str(source_root),
                        "metadata": {
                            "evidence_discovery_kind": "unity_script_assembly",
                            "evidence_class": "cli_candidate_reference_test",
                            "description": "Generic CLI source capability view.",
                            "allowed_tools": [
                                "search_dotnet_metadata",
                                "inspect_method_il",
                            ],
                            "assembly_relative_paths": ["Modules-ASM.dll"],
                            "version_identity": {},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    executor = LocalAssemblyEvidenceToolExecutor(
        metadata_runner=_CliMetadataRunner(),
        il_runner_factory=_CliILRunner,
    )
    monkeypatch.setattr(
        LocalAssemblyEvidenceToolExecutor,
        "from_inspector",
        classmethod(lambda cls, inspector_path: executor),
    )
    monkeypatch.setattr(
        "src.mod_agent.intelligent_evidence_only.OllamaChatAgentAdapter",
        _CliInjectedAgentAdapter,
    )
    monkeypatch.setattr(
        "src.mod_agent.intelligent_evidence_only._PROJECT_ROOT",
        tmp_path,
    )
    uuid_values = iter(("1" * 32, "2" * 32))
    monkeypatch.setattr(
        "src.mod_agent.intelligent_evidence_only.uuid4",
        lambda: SimpleNamespace(hex=next(uuid_values)),
    )
    _CliInjectedAgentAdapter.instances.clear()

    exit_code = main(
        [
            "intelligent-evidence-request",
            "Discover one exact movement method and inspect its IL.",
            "--source-registry",
            str(registry_path),
            "--artifact-root",
            "a",
            "--local-ollama",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0, payload
    assert payload["run_id"] == f"intelligent_evidence_{'1' * 32}"
    assert payload["current_stage"] == "evidence_retrieval"
    pack = payload["evidence_pack"]
    provenance = pack["provenance_validation"]
    assert provenance["run_id"] == payload["run_id"]
    assert provenance["all_method_inspections_derived_from_observations"] is True
    assert len(provenance["candidate_binding_trace"]) == 1
    binding = provenance["candidate_binding_trace"][0]
    assert binding["candidate_ref"].startswith("candidate_")
    assert binding["internal_method_id"].startswith("method_")
    assert binding["candidate_ref"] != binding["internal_method_id"]
    assert binding["source_id"] == "cli-source"
    assert binding["metadata_observation_id"] == "obs-001"
    assert binding["il_observation_id"] == "obs-002"
    assert len(binding["il_observation_sha256"]) == 64
    assert pack["model_action_trace"][1]["action"]["arguments"] == {
        "candidate_ref": binding["candidate_ref"]
    }
    assert pack["items"][0]["symbol"] == "Observed.Type.Move"
    adapter = _CliInjectedAgentAdapter.instances[0]
    assert len(adapter.model_observations) == 2
    assert "method_id" not in json.dumps(adapter.model_observations)
    attempt_envelope = json.loads(
        Path(payload["attempt_artifact"]["path"]).read_text(encoding="utf-8")
    )
    attempt = attempt_envelope["data"]
    assert attempt["run_id"] == payload["run_id"]
    assert attempt["run_validity"] == "valid_run"
    assert attempt["model_calls"] == 3
    assert attempt["external_model_calls"] == 0
    assert attempt["accepted_model_actions"] == 3
    assert attempt["tool_calls_executed"] == 2


def test_phase1_source_bound_no_write_run_persists_complete_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    assembly = source_root / "Modules-ASM.dll"
    assembly.write_bytes(b"managed-cli-test-bytes")
    assembly_sha256 = hashlib.sha256(assembly.read_bytes()).hexdigest().upper()
    module_mvid = "00000000-0000-0000-0000-000000000042"
    registry_path = tmp_path / "source-registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "evidence_discovery_source_registry_v1",
                "sources": [
                    {
                        "source_id": "cli-source",
                        "source_type": "decompiled_api",
                        "root_path": str(source_root),
                        "metadata": {
                            "evidence_discovery_kind": "unity_script_assembly",
                            "evidence_class": "phase1_lineage_test",
                            "description": "Phase 1 test source.",
                            "allowed_tools": [
                                "search_dotnet_metadata",
                                "inspect_method_il",
                            ],
                            "assembly_relative_paths": ["Modules-ASM.dll"],
                            "version_identity": {
                                "assembly_sha256": assembly_sha256,
                                "module_mvid": module_mvid,
                            },
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "phase1.py").write_text("BOUND = True\n", encoding="utf-8")
    executor = LocalAssemblyEvidenceToolExecutor(
        metadata_runner=_CliMetadataRunner(),
        il_runner_factory=_CliILRunner,
    )
    monkeypatch.setattr(
        LocalAssemblyEvidenceToolExecutor,
        "from_inspector",
        classmethod(lambda cls, inspector_path: executor),
    )
    monkeypatch.setattr(
        "src.mod_agent.intelligent_evidence_only.OllamaChatAgentAdapter",
        _CliInjectedAgentAdapter,
    )
    monkeypatch.setattr(
        "src.mod_agent.intelligent_evidence_only._PROJECT_ROOT",
        tmp_path,
    )
    monkeypatch.setattr(
        "src.mod_agent.intelligent_evidence_only._PHASE1_SOURCE_ID",
        "cli-source",
    )
    monkeypatch.setattr(
        "src.mod_agent.intelligent_evidence_only._PHASE1_ASSEMBLY_SHA256",
        assembly_sha256,
    )
    monkeypatch.setattr(
        "src.mod_agent.intelligent_evidence_only._PHASE1_MODULE_MVID",
        module_mvid,
    )
    monkeypatch.setattr(
        "src.mod_agent.intelligent_evidence_only._PHASE1_METHOD_SYMBOL",
        "Observed.Type.Move",
    )
    uuid_values = iter(("7" * 32, "8" * 32))
    monkeypatch.setattr(
        "src.mod_agent.intelligent_evidence_only.uuid4",
        lambda: SimpleNamespace(hex=next(uuid_values)),
    )
    _CliInjectedAgentAdapter.instances.clear()

    output = run_intelligent_evidence_only(
        description="Discover one exact movement method and inspect its IL.",
        source_registry_path=registry_path,
        artifact_root="artifacts",
        settings_path=tmp_path / "unused-settings.yaml",
        allow_evidence_disclosure=False,
        local_ollama=True,
        phase1_lineage=True,
    )

    assert output["phase1_lineage_passed"] is True
    assert output["external_model_called"] is False
    assert output["forbidden_artifacts_present"] == []
    assert output["workflow_trace_artifact"]["artifact_type"] == "workflow_trace"
    assert (
        output["post_run_validation_artifact"]["artifact_type"]
        == "evidence_post_run_validation"
    )
    terminal = json.loads(
        Path(output["attempt_artifact"]["path"]).read_text(encoding="utf-8")
    )["data"]
    assert terminal["lineage_schema_version"] == "phase1_source_bound_no_write_v1"
    assert terminal["target_source_binding"]["source_id"] == "cli-source"
    assert terminal["target_source_binding"]["source_roots_persisted"] is False
    assert terminal["authorization_boundary"] == {
        "local_ollama": True,
        "external_model_fallback": False,
        "control_artifact_writes": True,
        "target_source_writes": False,
        "proposal": False,
        "apply": False,
        "build": False,
        "game_runtime": False,
    }
    serialized = json.dumps(terminal)
    assert str(source_root) not in serialized
    assert "Discover one exact movement method" not in serialized
    validation = json.loads(
        Path(output["post_run_validation_artifact"]["path"]).read_text(
            encoding="utf-8"
        )
    )["data"]
    assert validation["lineage_passed"] is True
    assert validation["affects_runtime_route"] is False
    assert all(validation["lineage_checks"].values())


def test_cli_unknown_external_tool_persists_invalid_attempt_without_execution_or_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "Modules-ASM.dll").write_bytes(b"managed-cli-test-bytes")
    registry_path = tmp_path / "source-registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "evidence_discovery_source_registry_v1",
                "sources": [
                    {
                        "source_id": "cli-source",
                        "source_type": "decompiled_api",
                        "root_path": str(source_root),
                        "metadata": {
                            "evidence_discovery_kind": "unity_script_assembly",
                            "evidence_class": "cli_unknown_tool_test",
                            "description": "Generic CLI source capability view.",
                            "allowed_tools": [
                                "search_dotnet_metadata",
                                "inspect_method_il",
                            ],
                            "assembly_relative_paths": ["Modules-ASM.dll"],
                            "version_identity": {},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    executor = _CliRejectToolExecution()
    monkeypatch.setattr(
        LocalAssemblyEvidenceToolExecutor,
        "from_inspector",
        classmethod(lambda cls, inspector_path: executor),
    )
    monkeypatch.setattr(
        "src.mod_agent.intelligent_evidence_only.QwenChatAgentAdapter",
        _CliUnknownToolAgentAdapter,
    )
    monkeypatch.setattr(
        "src.mod_agent.intelligent_evidence_only._PROJECT_ROOT",
        tmp_path,
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-api-key")
    monkeypatch.setenv(
        "DASHSCOPE_BASE_URL",
        "https://dashscope.example/compatible-mode/v1",
    )
    uuid_values = iter(("3" * 32, "4" * 32))
    monkeypatch.setattr(
        "src.mod_agent.intelligent_evidence_only.uuid4",
        lambda: SimpleNamespace(hex=next(uuid_values)),
    )
    _CliUnknownToolAgentAdapter.instances.clear()

    exit_code = main(
        [
            "intelligent-evidence-request",
            "Discover one exact movement method and inspect its IL.",
            "--source-registry",
            str(registry_path),
            "--artifact-root",
            "a",
            "--settings",
            str(Path("config/settings.yaml").resolve()),
            "--allow-evidence-disclosure",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["reason"] == "UNKNOWN_EVIDENCE_TOOL"
    diagnostic = payload["diagnostic"]
    assert diagnostic["run_id"] == f"intelligent_evidence_{'3' * 32}"
    assert diagnostic["stage"] == "tool_call_validation"
    assert diagnostic["external_model_calls"] == 1
    assert diagnostic["accepted_model_actions"] == 0
    assert diagnostic["tool_calls_executed"] == 0
    assert diagnostic["failure_attribution"] == (
        "model_or_provider_emitted_unknown_tool"
    )
    attempt_envelope = json.loads(
        Path(diagnostic["attempt_artifact"]["path"]).read_text(encoding="utf-8")
    )
    attempt = attempt_envelope["data"]
    assert attempt["run_id"] == diagnostic["run_id"]
    assert attempt["run_validity"] == "invalid_run"
    assert attempt["terminal_stage"] == "tool_call_validation"
    assert attempt["model_calls"] == 1
    assert attempt["external_model_calls"] == 1
    assert attempt["accepted_model_actions"] == 0
    assert attempt["tool_calls_executed"] == 0
    assert attempt["failure"]["code"] == "UNKNOWN_EVIDENCE_TOOL"
    assert attempt["failure"]["symbolic_code"] == "UNKNOWN_EVIDENCE_TOOL"
    failure_diagnostics = attempt["failure_diagnostics"]
    assert failure_diagnostics["provider_tool_calls"] == 1
    assert failure_diagnostics["adapter_accepted_actions"] == 0
    assert failure_diagnostics["deterministic_validation_passed"] == 0
    assert failure_diagnostics["dispatch_started"] == 0
    assert failure_diagnostics["tool_execution_completed"] == 0
    assert failure_diagnostics["observation_created"] == 0
    assert failure_diagnostics["failure_stage"] == "adapter_action_conversion"
    assert failure_diagnostics["symbolic_failure_code"] == "UNKNOWN_EVIDENCE_TOOL"
    assert failure_diagnostics["traceback"]["recoverable_from_artifact"] is True
    assert failure_diagnostics["traceback"]["source_lines_persisted"] is False
    assert failure_diagnostics["traceback"]["locals_persisted"] is False
    assert failure_diagnostics["traceback"]["exception_message_persisted"] is False
    assert attempt["provider_turns"][0]["streaming"] is False
    assert attempt["provider_turns"][0]["usage"]["total_tokens"] == 60
    serialized_attempt = json.dumps(attempt, ensure_ascii=False)
    assert "test-api-key" not in serialized_attempt
    assert str(source_root) not in serialized_attempt
    assert "Discover one exact movement method and inspect its IL." not in (
        serialized_attempt
    )
    tool_identity = attempt["provider_turns"][0]["tool_calls"][0]
    assert tool_identity["provider_reported_tool_name"] == "search_metadata"
    assert tool_identity["adapter_extracted_tool_name"] == "search_metadata"
    assert len(tool_identity["arguments_sha256"]) == 64
    assert _CliUnknownToolAgentAdapter.instances[0].calls == 1
    assert executor.actions == []
    artifact_root = tmp_path / "a"
    attempt_revisions = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in artifact_root.glob("features/*/r/evidence_run_attempt/*.json")
    ]
    assert {item["status"] for item in attempt_revisions} == {"running", "failed"}
    assert {
        item["data"]["run_id"] for item in attempt_revisions
    } == {diagnostic["run_id"]}
    started_attempt = next(
        item for item in attempt_revisions if item["status"] == "running"
    )
    assert started_attempt["data"]["run_validity"] == "attempt_started"
    assert started_attempt["data"]["external_model_calls"] == 0
    assert not [
        path
        for path in artifact_root.rglob("*.json")
        if json.loads(path.read_text(encoding="utf-8")).get("artifact_type")
        == "evidence_pack"
    ]


def test_cli_failed_attempt_persists_partial_execution_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "Modules-ASM.dll").write_bytes(b"managed-cli-test-bytes")
    registry_path = tmp_path / "source-registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "evidence_discovery_source_registry_v1",
                "sources": [
                    {
                        "source_id": "cli-source",
                        "source_type": "decompiled_api",
                        "root_path": str(source_root),
                        "metadata": {
                            "evidence_discovery_kind": "unity_script_assembly",
                            "evidence_class": "cli_failure_diagnostics_test",
                            "description": "Generic CLI source capability view.",
                            "allowed_tools": [
                                "search_dotnet_metadata",
                                "inspect_method_il",
                            ],
                            "assembly_relative_paths": ["Modules-ASM.dll"],
                            "version_identity": {},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    executor = _CliFailSecondToolExecution(
        LocalAssemblyEvidenceToolExecutor(
            metadata_runner=_CliMetadataRunner(),
            il_runner_factory=_CliILRunner,
        )
    )
    monkeypatch.setattr(
        LocalAssemblyEvidenceToolExecutor,
        "from_inspector",
        classmethod(lambda cls, inspector_path: executor),
    )
    monkeypatch.setattr(
        "src.mod_agent.intelligent_evidence_only.OllamaChatAgentAdapter",
        _CliInjectedAgentAdapter,
    )
    monkeypatch.setattr(
        "src.mod_agent.intelligent_evidence_only._PROJECT_ROOT",
        tmp_path,
    )
    uuid_values = iter(("5" * 32, "6" * 32))
    monkeypatch.setattr(
        "src.mod_agent.intelligent_evidence_only.uuid4",
        lambda: SimpleNamespace(hex=next(uuid_values)),
    )
    _CliInjectedAgentAdapter.instances.clear()

    exit_code = main(
        [
            "intelligent-evidence-request",
            "Discover one exact movement method and inspect its IL.",
            "--source-registry",
            str(registry_path),
            "--artifact-root",
            "a",
            "--local-ollama",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["reason"] == "EVIDENCE_RUN_VALIDATION_ERROR"
    diagnostic = payload["diagnostic"]
    assert diagnostic["accepted_model_actions"] == 2
    assert diagnostic["tool_calls_executed"] == 1
    failure_diagnostics = diagnostic["failure_diagnostics"]
    assert failure_diagnostics["schema_version"] == (
        "evidence_run_failure_diagnostics_v1"
    )
    assert failure_diagnostics["provider_tool_calls"] == 2
    assert failure_diagnostics["adapter_accepted_actions"] == 2
    assert failure_diagnostics["deterministic_validation_passed"] == 2
    assert failure_diagnostics["dispatch_started"] == 2
    assert failure_diagnostics["tool_execution_completed"] == 1
    assert failure_diagnostics["observation_created"] == 1
    assert failure_diagnostics["failure_stage"] == "tool_execution"
    assert failure_diagnostics["symbolic_failure_code"] == (
        "EVIDENCE_DISCOVERY_VALUE_ERROR"
    )
    traceback_data = failure_diagnostics["traceback"]
    assert traceback_data["available_in_process"] is True
    assert traceback_data["recoverable_from_artifact"] is True
    assert traceback_data["source_lines_persisted"] is False
    assert traceback_data["locals_persisted"] is False
    assert traceback_data["exception_message_persisted"] is False
    assert traceback_data["project_frames"]
    assert all(
        set(frame) == {"path", "line", "function"}
        for frame in traceback_data["project_frames"]
    )

    attempt_envelope = json.loads(
        Path(diagnostic["attempt_artifact"]["path"]).read_text(encoding="utf-8")
    )
    attempt = attempt_envelope["data"]
    assert attempt["tool_calls_executed"] == 1
    assert attempt["failure"]["code"] == "EVIDENCE_RUN_VALIDATION_ERROR"
    assert attempt["failure"]["symbolic_code"] == "EVIDENCE_DISCOVERY_VALUE_ERROR"
    assert attempt["failure_diagnostics"] == failure_diagnostics
    serialized_attempt = json.dumps(attempt, ensure_ascii=False)
    assert str(source_root) not in serialized_attempt
    assert (
        "Discover one exact movement method and inspect its IL."
        not in serialized_attempt
    )
    assert "sensitive query text must not persist" not in serialized_attempt
    assert not [
        path
        for path in (tmp_path / "a").rglob("*.json")
        if json.loads(path.read_text(encoding="utf-8")).get("artifact_type")
        == "evidence_pack"
    ]


def test_cli_intelligent_evidence_request_selects_local_ollama_without_disclosure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def run(**kwargs):
        captured.update(kwargs)
        return {
            "status": "completed",
            "command": "intelligent-evidence-request",
            "execution_mode": "intelligent_evidence_only",
            "current_stage": "evidence_retrieval",
            "stopped_before": "implementation_plan",
            "forbidden_artifacts_present": [],
        }

    monkeypatch.setattr("src.mod_agent.cli.run_intelligent_evidence_only", run)
    exit_code = main(
        [
            "intelligent-evidence-request",
            "Discover WallCrawler hook evidence.",
            "--source-registry",
            "machine-local-sources.json",
            "--local-ollama",
            "--ollama-base-url",
            "http://127.0.0.1:11434",
            "--ollama-model",
            "qwen3:4b-instruct",
        ]
    )

    json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert captured["local_ollama"] is True
    assert captured["allow_evidence_disclosure"] is False
    assert captured["ollama_base_url"] == "http://127.0.0.1:11434"
    assert captured["ollama_model"] == "qwen3:4b-instruct"


def test_cli_intelligent_evidence_request_blocks_without_disclosure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "intelligent-evidence-request",
            "Discover WallCrawler hook evidence.",
            "--source-registry",
            "machine-local-sources.json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["status"] == "BLOCKED"
    assert "--allow-evidence-disclosure" in payload["reason"]


def test_cli_run_request_blocks_before_target_access_without_source_disclosure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "run-request",
            "change local source",
            "--target-project",
            "missing-target",
            "--confirm-isolated-write",
            "--allow-build",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["status"] == "BLOCKED"
    assert "--allow-source-disclosure" in payload["reason"]


def test_cli_run_request_passes_local_ollama_boundary_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def run(**kwargs):
        captured.update(kwargs)
        return {
            "build_summary": {
                "status": "not_run",
                "claims_real_build_success": False,
            }
        }

    monkeypatch.setattr("src.mod_agent.cli.run_local_request", run)

    exit_code = main(
        [
            "run-request",
            "change local source",
            "--target-project",
            "target",
            "--local-ollama",
            "--ollama-base-url",
            "http://127.0.0.1:11434",
            "--ollama-model",
            "qwen3:4b-instruct",
            "--ollama-max-output-tokens",
            "3072",
            "--ollama-context-window",
            "32768",
            "--confirm-isolated-write",
            "--allow-build",
        ]
    )

    assert exit_code == 1
    json.loads(capsys.readouterr().out)
    assert captured["local_ollama"] is True
    assert captured["ollama_base_url"] == "http://127.0.0.1:11434"
    assert captured["ollama_model"] == "qwen3:4b-instruct"
    assert captured["ollama_max_output_tokens"] == 3072
    assert captured["ollama_context_window"] == 32768
    assert captured["allow_source_disclosure"] is False
    assert captured["run_gtfo_runtime"] is False
    assert captured["allow_game_launch"] is False
    assert captured["runtime_plugin_destination"] is None
    assert captured["allow_game_directory_write"] is False
    assert callable(captured["diff_approval_reader"])


def test_cli_run_request_passes_runtime_admission_and_requires_runtime_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def run(**kwargs):
        captured.update(kwargs)
        return {
            "current_stage": "done",
            "build_summary": {"claims_real_build_success": True},
            "runtime_summary": {"claims_real_runtime_success": True},
        }

    monkeypatch.setattr("src.mod_agent.cli.run_local_request", run)

    exit_code = main(
        [
            "run-request",
            "change local source and verify runtime",
            "--target-project",
            "target",
            "--allow-source-disclosure",
            "--confirm-isolated-write",
            "--allow-build",
            "--run-gtfo-runtime",
            "--allow-game-launch",
            "--runtime-plugin-destination",
            r"C:\GTFO\BepInEx\plugins\BetterHitFeedback.dll",
            "--allow-game-directory-write",
        ]
    )

    assert exit_code == 0
    json.loads(capsys.readouterr().out)
    assert captured["run_gtfo_runtime"] is True
    assert captured["allow_game_launch"] is True
    assert captured["runtime_plugin_destination"] == (
        r"C:\GTFO\BepInEx\plugins\BetterHitFeedback.dll"
    )
    assert captured["allow_game_directory_write"] is True


def test_cli_runtime_request_does_not_exit_success_on_build_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "src.mod_agent.cli.run_local_request",
        lambda **_: {
            "current_stage": "build",
            "build_summary": {"claims_real_build_success": True},
            "runtime_summary": {},
        },
    )

    exit_code = main(
        [
            "run-request",
            "change local source and verify runtime",
            "--target-project",
            "target",
            "--allow-source-disclosure",
            "--confirm-isolated-write",
            "--allow-build",
            "--run-gtfo-runtime",
            "--allow-game-launch",
            "--runtime-plugin-destination",
            r"C:\GTFO\BepInEx\plugins\BetterHitFeedback.dll",
            "--allow-game-directory-write",
        ]
    )

    assert exit_code == 1
    json.loads(capsys.readouterr().out)


def test_cli_does_not_treat_non_real_success_status_as_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "src.mod_agent.cli.run_local_request",
        lambda **_: {
            "build_summary": {
                "status": "success",
                "claims_real_build_success": False,
            }
        },
    )

    exit_code = main(
        [
            "run-request",
            "change local source",
            "--target-project",
            "target",
            "--allow-source-disclosure",
            "--confirm-isolated-write",
            "--allow-build",
        ]
    )

    assert exit_code == 1
    assert json.loads(capsys.readouterr().out)["build_summary"][
        "claims_real_build_success"
    ] is False
