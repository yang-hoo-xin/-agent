"""Tests for the controlled code-generation platform CLI."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.libs.llm import AgentToolCall, AgentTurnResponse, AgentUsage
from src.mod_agent import __version__
from src.mod_agent.artifacts.store import ArtifactStorePreflightError
from src.mod_agent.cli import main, plan_request
from src.mod_agent.evidence.discovery_tools import LocalAssemblyEvidenceToolExecutor


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
                            "claim": "Observed.Type.Move has an inspected IL body.",
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
