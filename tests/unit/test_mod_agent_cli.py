"""Tests for the controlled code-generation platform CLI."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml

import src.mod_agent.cli as cli_module
import src.mod_agent.local_entry as local_entry_module
from src.libs.llm import (
    AgentToolCall,
    AgentTurnProviderError,
    AgentTurnResponse,
    AgentUsage,
    ChatResponse,
)
from src.mod_agent import __version__
from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.artifacts.store import (
    ArtifactStorePreflightError,
    ArtifactWriteResult,
)
from src.mod_agent.cli import (
    _edit_authority_review_exit_code,
    _read_exact_diff_approval_from_stdin,
    main,
    plan_request,
)
from src.mod_agent.edit_authority_capabilities import (
    EDIT_AUTHORITY_CAPABILITIES,
    EditAuthorityStoreStepV1,
    project_edit_authority_review_result,
    resolve_edit_authority_capability,
)
from src.mod_agent.evidence import RgLiveEvidenceProvider
from src.mod_agent.evidence.discovery_tools import LocalAssemblyEvidenceToolExecutor
from src.mod_agent.intelligent_evidence_only import (
    IntelligentEvidenceEntryError,
    _evidence_run_failure_code,
    _failure_attribution,
    run_intelligent_evidence_only,
)
from src.mod_agent.local_entry import LocalEntryError
from src.mod_agent.runtime import RuntimeEvidenceItem, build_real_runtime_evidence_payload
from tests.fixtures.local_request_profile import request_budget_args


@pytest.fixture()
def injected_ollama_runtime(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Keep identity pre/postflight real while replacing only its HTTP boundary."""
    calls: list[str] = []

    def handle_request(_transport, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url).startswith("http://127.0.0.1:11434/api/")
        calls.append(request.url.path)
        if request.url.path == "/api/tags":
            payload = {"models": [{
                "name": "qwen3:4b-instruct",
                "model": "qwen3:4b-instruct",
                "digest": hashlib.sha256(b"injected-cli-model").hexdigest(),
                "details": {"context_length": 40960},
                "capabilities": ["completion", "tools"],
            }]}
        elif request.url.path == "/api/version":
            payload = {"version": "injected-cli-test"}
        else:
            raise AssertionError(f"Unexpected HTTP request: {request.url.path}")
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle_request)
    return calls


def _human_semantic_approval_line(dry_run: dict[str, object]) -> str:
    binding = dry_run["human_semantic_decision_binding"]
    assert isinstance(binding, dict)
    return json.dumps(
        {
            **binding,
            "decision": "approve",
            "reviewer_identity": "human:cli-integration-test",
        }
    ) + "\n"


def _read_exact_test_planning_target_id(
    tmp_path: Path,
    source_path: Path,
) -> str:
    probe_root = tmp_path / "planning-target-probe"
    probe_source = probe_root / "generated_mods" / "Example" / "Plugin.cs"
    probe_source.parent.mkdir(parents=True, exist_ok=True)
    probe_source.write_bytes(source_path.read_bytes())
    evidence = RgLiveEvidenceProvider(probe_root).collect(
        query="Load",
        search_root="generated_mods/Example",
        max_items=1,
    )
    assert len(evidence.items) == 1
    return evidence.items[0].evidence_id


def _successful_edit_authority_cli_result(
    *,
    schema_version: str,
    projection_kind: str | None,
    feature_id: str = "feature_001",
    request_hash: str = "sha256:" + ("a" * 64),
) -> dict[str, object]:
    capability = resolve_edit_authority_capability(
        schema_version=schema_version,
        projection_kind=projection_kind,
    )
    steps: list[EditAuthorityStoreStepV1] = []
    for role in capability.review_write_artifact_types:
        artifact_hash = role.ljust(64, "0")[:64]
        ref = ArtifactRef(
            feature_id=feature_id,
            artifact_type=role,
            path=f"C:/store/{role}/{artifact_hash[:32]}.json",
            artifact_hash=artifact_hash,
        )
        steps.append(
            EditAuthorityStoreStepV1(
                role=role,
                store_result=ArtifactWriteResult(
                    outcome="committed",
                    feature_id=feature_id,
                    artifact_type=role,
                    artifact_hash=artifact_hash,
                    artifact_ref=ref,
                    revision_path=ref.path,
                    latest_alias_path=f"C:/store/{role}.json",
                    pending_marker_path=f"C:/store/pending/{artifact_hash}.json",
                    commit_started=True,
                    revision_state="valid",
                    latest_alias_state="matches_identity",
                    pending_marker_state="absent",
                    failure_stage=None,
                    failure_class=None,
                    failure_message=None,
                    recovery_available=False,
                    recovery_authorized=False,
                ),
            )
        )
    machine_result = project_edit_authority_review_result(
        capability=capability,
        feature_id=feature_id,
        approval_identity_hash=request_hash,
        store_steps=tuple(steps),
        payload_decision="approve",
        resume_decision_status="accepted",
        resume_decision_allowed=True,
    )
    return {
        "status": capability.public_success_status,
        "feature_id": feature_id,
        "request_hash": request_hash,
        "edit_authority_review_result": machine_result.to_dict(),
    }


def _nonapproved_edit_authority_cli_result(scenario: str) -> dict[str, object]:
    feature_id = "feature_001"
    request_hash = "sha256:" + ("a" * 64)
    capability = resolve_edit_authority_capability(
        schema_version="stagger_edit_authority_request_v1",
        projection_kind=None,
    )
    successful = _successful_edit_authority_cli_result(
        schema_version="stagger_edit_authority_request_v1",
        projection_kind=None,
    )
    successful_projection = successful["edit_authority_review_result"]
    assert isinstance(successful_projection, dict)
    protocol_steps = tuple(
        EditAuthorityStoreStepV1.from_dict(item)
        for item in successful_projection["store_steps"][:2]
    )
    if scenario == "rejected":
        kwargs = {
            "payload_decision": "reject",
            "resume_decision_status": "accepted",
            "resume_decision_allowed": True,
            "execution_failure_stage": None,
        }
    elif scenario == "blocked":
        kwargs = {
            "payload_decision": "approve",
            "resume_decision_status": "blocked",
            "resume_decision_allowed": False,
            "execution_failure_stage": None,
        }
    else:
        kwargs = {
            "payload_decision": "approve",
            "resume_decision_status": "accepted",
            "resume_decision_allowed": True,
            "execution_failure_stage": "store_preflight",
        }
    machine_result = project_edit_authority_review_result(
        capability=capability,
        feature_id=feature_id,
        approval_identity_hash=request_hash,
        store_steps=protocol_steps,
        **kwargs,
    )
    return {
        "status": "BLOCKED",
        "feature_id": feature_id,
        "request_hash": request_hash,
        "edit_authority_review_result": machine_result.to_dict(),
    }


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
                    "symbol": "Observed.Type.Movement",
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

    def inspect_observed_method(
        self,
        assembly_path: str | Path,
        *,
        assembly_sha256: str,
        module_mvid: str,
        metadata_token: str,
    ) -> dict[str, object]:
        assembly = Path(assembly_path)
        assert self.symbols == ("Observed.Type.Movement",)
        assert assembly_sha256 == hashlib.sha256(assembly.read_bytes()).hexdigest().upper()
        assert module_mvid == "00000000-0000-0000-0000-000000000042"
        assert metadata_token == "0x06000042"
        return {
            "assembly_sha256": hashlib.sha256(assembly.read_bytes()).hexdigest().upper(),
            "module_mvid": "00000000-0000-0000-0000-000000000042",
            "methods": [
                {
                    "symbol": "Observed.Type.Movement",
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


def _cli_actual_plan_response(*, provider: str, model: str) -> AgentTurnResponse:
    return AgentTurnResponse(
        provider=provider,
        model=model,
        content=json.dumps(
            {
                "action": "plan",
                "planning_status": "ready",
                "requirement_projection": {
                    "schema_version": "hook_requirement_projection_v2",
                    "behavior_goal": "Discover and inspect one current movement method.",
                    "trigger": None,
                    "actor": None,
                    "target": None,
                    "hard_constraints": [],
                    "forbidden_outcomes": [],
                    "implementation_hints": [],
                    "acceptance_signals": [],
                    "planning_blocking_questions": [{
                        "requirement_id": "req-movement",
                        "question": "Which current managed method exposes movement behavior?",
                    }],
                    "deferred_planning_or_runtime_questions": [],
                },
                "search_plan": {
                    "schema_version": "hook_discovery_search_plan_v2",
                    "engineering_questions": [{
                        "question_id": "question-movement",
                        "question": "Which current managed method exposes movement behavior?",
                        "requirement_ids": ["req-movement"],
                    }],
                    "source_roles": [
                        {"source_id": "cli-source", "role": "current_api_and_il"}
                    ],
                    "planned_lanes": [
                        {
                            "lane": "managed_metadata_discovery",
                            "tool": "search_dotnet_metadata",
                            "source_ids": ["cli-source"],
                        },
                        {
                            "lane": "exact_il_verification",
                            "tool": "inspect_method_il",
                            "source_ids": ["cli-source"],
                        },
                    ],
                    "query_families": [
                        {
                            "family_id": "movement-behavior",
                            "queries": ["movement"],
                            "evidence_need": "Find one observed movement method.",
                            "source_ids": ["cli-source"],
                            "tool": "search_dotnet_metadata",
                            "question_ids": ["question-movement"],
                        }
                    ],
                    "initial_stop_condition": "Stop after exact IL verification.",
                    "initial_expand_condition": "Expand once only for a recorded open question.",
                },
            }
        ),
        stop_reason="stop",
        request_id="provider-cli-plan",
        usage=AgentUsage(input_tokens=8, output_tokens=12),
    )


class _CliInjectedAgentAdapter:
    provider = "injected_cli_agent"
    instances: list["_CliInjectedAgentAdapter"] = []

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        max_output_tokens: int,
        context_window: int | None = None,
        seed: int = 0,
        request_timeout_seconds: float = 180.0,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.context_window = context_window
        self.seed = seed
        self.request_timeout_seconds = request_timeout_seconds
        self.turn = 0
        self.model_observations: list[object] = []
        self.__class__.instances.append(self)

    def complete_turn(self, request) -> AgentTurnResponse:
        self.turn += 1
        if request.tool_results:
            observation = request.tool_results[0].output
            self.model_observations.append(observation)
        if self.turn == 1:
            return _cli_actual_plan_response(provider=self.provider, model=self.model)
        if self.turn == 2:
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
                            "family_id": "movement-behavior",
                        },
                    ),
                ),
                stop_reason="tool_calls",
                request_id="provider-cli-001",
                usage=AgentUsage(input_tokens=10, output_tokens=5),
                provider_state={"turn": 1},
            )
        if self.turn == 3:
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
                request_id="provider-cli-003",
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
                                "Observed inspected symbol: Observed.Type.Movement."
                            ),
                            "claim_status": "observed",
                            "observation_ids": ["obs-002"],
                            "limitations": [],
                            "requirement_ids": ["req-movement"],
                            "relationship": "support",
                        }
                    ],
                    "unresolved_questions": [
                        "Runtime movement behavior remains unresolved."
                    ],
                    "missing_capabilities": [],
                }
            ),
            stop_reason="stop",
            request_id="provider-cli-004",
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
        if self.calls == 1:
            return _cli_actual_plan_response(provider=self.provider, model=self.model)
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

    assert result.status == "ready_for_feature_spec"
    assert result.command == "plan-request"
    assert result.execution_mode == "planning_only"
    assert result.writes_performed is False
    assert result.stopped_before == "feature_spec"
    assert result.request_planning_report["route"] == "standard_feature"
    assert result.request_planning_report["risk_level"] == "medium"
    assert result.request_planning_report["requires_hook_evidence"] is False
    assert result.request_planning_report["requires_runtime_evidence"] is True
    assert result.mod_planning_brief["request_type"]["value"] == "gameplay behavior"
    assert result.mod_planning_brief["decision"] == "ready_for_feature_spec"
    assert result.mod_planning_brief["next_action"] == "feature_spec"
    assert result.mod_planning_brief["blockers"] == []


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
    assert payload["status"] == "ready_for_feature_spec"
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
    injected_ollama_runtime: list[str],
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
                            "evidence_authority": "authoritative",
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
    assert pack["items"][0]["symbol"] == "Observed.Type.Movement"
    adapter = _CliInjectedAgentAdapter.instances[0]
    assert len(adapter.model_observations) == 2
    assert "method_id" not in json.dumps(adapter.model_observations)
    attempt_envelope = json.loads(
        Path(payload["attempt_artifact"]["path"]).read_text(encoding="utf-8")
    )
    attempt = attempt_envelope["data"]
    assert attempt["run_id"] == payload["run_id"]
    assert attempt["run_validity"] == "valid_run"
    assert attempt["model_calls"] == 4
    assert attempt["external_model_calls"] == 0
    assert attempt["accepted_model_actions"] == 3
    assert attempt["tool_calls_executed"] == 2
    assert injected_ollama_runtime == ["/api/tags", "/api/version"] * 2


def test_phase1_source_bound_no_write_run_persists_complete_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    injected_ollama_runtime: list[str],
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
                            "evidence_authority": "authoritative",
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
        "Observed.Type.Movement",
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
    assert injected_ollama_runtime == ["/api/tags", "/api/version"] * 2


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
                            "evidence_authority": "authoritative",
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
    assert diagnostic["external_model_calls"] == 2
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
    assert attempt["model_calls"] == 2
    assert attempt["external_model_calls"] == 2
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
    assert attempt["provider_turns"][1]["streaming"] is False
    assert attempt["provider_turns"][1]["usage"]["total_tokens"] == 60
    serialized_attempt = json.dumps(attempt, ensure_ascii=False)
    assert "test-api-key" not in serialized_attempt
    assert str(source_root) not in serialized_attempt
    assert "Discover one exact movement method and inspect its IL." not in (
        serialized_attempt
    )
    tool_identity = attempt["provider_turns"][1]["tool_calls"][0]
    assert tool_identity["provider_reported_tool_name"] == "search_metadata"
    assert tool_identity["adapter_extracted_tool_name"] == "search_metadata"
    assert len(tool_identity["arguments_sha256"]) == 64
    assert _CliUnknownToolAgentAdapter.instances[0].calls == 2
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
    injected_ollama_runtime: list[str],
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
                            "evidence_authority": "authoritative",
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
    assert injected_ollama_runtime == ["/api/tags", "/api/version"]
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
            "qwen3.6:27b",
            "--ollama-context-window",
            "32768",
            "--ollama-request-timeout-seconds",
            "600",
        ]
    )

    json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert captured["local_ollama"] is True
    assert captured["allow_evidence_disclosure"] is False
    assert captured["ollama_base_url"] == "http://127.0.0.1:11434"
    assert captured["ollama_model"] == "qwen3.6:27b"
    assert captured["ollama_context_window"] == 32768
    assert captured["ollama_request_timeout_seconds"] == 600.0


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
            *request_budget_args(),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["status"] == "BLOCKED"
    assert "--allow-source-disclosure" in payload["reason"]


def test_cli_run_request_forwards_precomputed_targets_but_rejects_legacy_summary(
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
            "--planning-target-evidence-id",
            "evidence_cli_target_001",
            "--planning-target-evidence-id",
            "evidence_cli_target_002",
            *request_budget_args(),
        ]
    )

    assert exit_code == 2
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
    assert captured["planning_target_evidence_ids"] == (
        "evidence_cli_target_001",
        "evidence_cli_target_002",
    )
    assert callable(captured["diff_approval_reader"])
    assert "requirement_coverage_projection_factory" not in captured
    assert "requirement_coverage_findings_factory" not in captured


def test_cli_run_request_passes_runtime_admission_but_rejects_legacy_summary(
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
            *request_budget_args(),
        ]
    )

    assert exit_code == 2
    json.loads(capsys.readouterr().out)
    assert captured["run_gtfo_runtime"] is True
    assert captured["allow_game_launch"] is True
    assert captured["runtime_plugin_destination"] == (
        r"C:\GTFO\BepInEx\plugins\BetterHitFeedback.dll"
    )
    assert captured["allow_game_directory_write"] is True


def test_cli_runtime_request_rejects_build_only_legacy_summary(
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
            *request_budget_args(),
        ]
    )

    assert exit_code == 2
    json.loads(capsys.readouterr().out)


def test_cli_does_not_treat_legacy_status_as_machine_truth(
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
            *request_budget_args(),
        ]
    )

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out)["build_summary"][
        "claims_real_build_success"
    ] is False


def test_cli_run_request_uses_real_public_product_executor_and_graph(
    short_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = short_workspace / "Example"
    bepinex = short_workspace / "BepInEx"
    target.mkdir()
    bepinex.mkdir()
    (target / "Example.csproj").write_text(
        "<Project><PropertyGroup>"
        "<AssemblyName>Example</AssemblyName>"
        f"<BepInExDir>{bepinex}</BepInExDir>"
        "</PropertyGroup></Project>",
        encoding="utf-8",
    )
    (target / "Plugin.cs").write_text(
        "public sealed class Plugin {}\n", encoding="utf-8"
    )
    (target / "nuget.config").write_text("<configuration />", encoding="utf-8")

    digest = "0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0"
    identity = {
        "name": "qwen3:4b-instruct",
        "model": "qwen3:4b-instruct",
        "digest": digest,
        "modified_at": "2026-07-16T14:06:42.9800065+08:00",
        "size": 2497293803,
        "details": {
            "context_length": 262144,
            "parameter_size": "4.0B",
            "quantization_level": "Q4_K_M",
        },
        "capabilities": ["completion", "tools"],
        "base_url": "http://127.0.0.1:11434",
    }
    monkeypatch.setattr(
        local_entry_module,
        "_read_ollama_model_identity",
        lambda *_: identity,
    )
    monkeypatch.setattr(
        local_entry_module,
        "_read_ollama_server_version",
        lambda *_: "0.32.1",
    )
    monkeypatch.setattr(
        local_entry_module.LLMFactory,
        "create",
        staticmethod(
            lambda settings, **kwargs: local_entry_module.OllamaLLM(
                settings, **kwargs
            )
        ),
    )

    def build(profile):
        artifact = profile.working_directory / "bin" / "Debug" / "Example.dll"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(b"baseline")
        return local_entry_module.NuGetIsolatedBuildExecution(
            restore_exit_code=0,
            build_exit_code=0,
            restore_stdout="restore ok",
            restore_stderr="",
            build_stdout="build ok",
            build_stderr="",
            duration_ms=2,
        )

    monkeypatch.setattr(local_entry_module, "_run_nuget_isolated_build", build)

    exit_code = main(
        [
            "run-request",
            "test",
            "--target-project",
            str(target),
            "--workspace-root",
            str(short_workspace / "runs"),
            "--settings",
            "config/settings.yaml",
            "--local-ollama",
            "--ollama-model",
            "qwen3:4b-instruct",
            "--ollama-context-window",
            "32768",
            "--confirm-isolated-write",
            "--allow-build",
            *request_budget_args(),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    machine = payload["product_execution_result"]
    assert exit_code == 1
    assert machine["execution_disposition"] == "domain_blocked"
    assert machine["terminal_node"] == "blocked"
    assert [item["artifact_role"] for item in machine["store_attempts"]] == [
        "request_planning_report",
        "blocked_report",
    ]
    assert all(
        item["store_result"]["outcome"] == "committed"
        for item in machine["store_attempts"]
    )
def _formal_coverage_model_response(request: dict[str, object]) -> dict[str, object] | None:
    message_type = request.get("message_type")
    if message_type == "product_requirement_projection":
        obligations = request["input_obligations"]
        requirements = []
        dispositions = []
        change_indexes = [
            row["input_obligation_index"]
            for row in obligations
            if "change" in row["allowed_roles"]
        ]
        requirements.append(
            {
                "role": "change",
                "text": "Change the requested Load behavior.",
                "input_obligation_indexes": change_indexes,
                "query_leads": ["Load"],
            }
        )
        for row in obligations:
            index = row["input_obligation_index"]
            if index in change_indexes:
                continue
            if "scope_boundary" in row["allowed_dispositions"]:
                dispositions.append(
                    {
                        "input_obligation_index": index,
                        "disposition": "scope_boundary",
                        "reason": "This non-goal remains a planning scope boundary.",
                    }
                )
            elif "post_change" in row["allowed_dispositions"]:
                dispositions.append(
                    {
                        "input_obligation_index": index,
                        "disposition": "post_change",
                        "reason": "This observation occurs after the approved change.",
                    }
                )
            else:
                requirements.append(
                    {
                        "role": row["allowed_roles"][0],
                        "text": row["text"],
                        "input_obligation_indexes": [index],
                        "query_leads": ["Load"],
                    }
                )
        return {
            "requirements": requirements,
            "input_dispositions": dispositions,
        }
    if message_type == "product_requirement_findings":
        evidence_id = request["source_observations"][0]["evidence_id"]
        if request.get("native_findings_contract") == "planning_readiness_v1":
            return {"findings": [{"relation_index": relation["relation_index"], "planning_readiness": "ready",
                "current_evidence_ids": [evidence_id], "current_basis": "Fixture source identifies the current implementation and edit location.",
                "requested_behavior_status": "not_yet_implemented", "blocking_current_facts": [],
                "edit_target_evidence_ids": [evidence_id] if any(parent["role"] == "change"
                    for parent in relation["parent_requirements"]) else []} for relation in request["relations"]]}
        return {
            "findings": [
                {
                    "relation_index": relation["relation_index"],
                    "relationship": "support",
                    "evidence_ids": [evidence_id],
                    "edit_target_evidence_ids": (
                        [evidence_id]
                        if any(
                            parent["role"] == "change"
                            for parent in relation["parent_requirements"]
                        )
                        else []
                    ),
                    "unresolved_gaps": [],
                }
                for relation in request["relations"]
            ]
        }
    return None


def _install_public_run_request_native_chat(monkeypatch, deterministic_chat):
    """Replace HTTP only; keep native AgentTurn, the shared worker and Graph real."""
    def native_chat(_transport, request):
        assert request.method == "POST"
        assert str(request.url) == "http://127.0.0.1:11434/api/chat"
        payload = json.loads(request.content)
        contexts = []
        for message in payload["messages"]:
            if message["role"] != "user":
                continue
            try:
                context = json.loads(message["content"])
            except (TypeError, ValueError):
                continue
            if "patch_agent_context_encoding" in context:
                context = local_entry_module._restore_patch_agent_context(context)
            if ("required_change_units" in context or "allowed_edit_evidence_ids" in context
                    or context.get("message_type") in {"product_requirement_projection", "product_requirement_findings"}):
                contexts.append(context)
        assert contexts, "Native request omitted its real Evidence, Planning or Patch context."
        context = contexts[-1]
        coverage_response = _formal_coverage_model_response(context)
        if coverage_response is not None:
            response = ChatResponse(model=payload["model"], content=json.dumps(coverage_response))
        elif "allowed_edit_evidence_ids" in context:
            response = ChatResponse(model=payload["model"], content=json.dumps({
                "decision": "select_targets", "selected_evidence_ids": context["allowed_edit_evidence_ids"],
                "rationale": "Engineering transport fixture selected the observed source unit.", "missing_evidence": [],
            }))
        else:
            response = deterministic_chat(SimpleNamespace(), [SimpleNamespace(content=json.dumps(context))])
        return httpx.Response(200, request=request, json={"model": response.model,
            "message": {"role": "assistant", "content": response.content},
            "done": True, "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 20})

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", native_chat)


def test_cli_run_request_real_public_product_executor_compile_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "Example"
    bepinex = tmp_path / "BepInEx"
    workspace = tmp_path / "runs"
    target.mkdir()
    bepinex.mkdir()
    (target / "Example.csproj").write_text(
        "<Project><PropertyGroup>"
        "<AssemblyName>Example</AssemblyName>"
        f"<BepInExDir>{bepinex}</BepInExDir>"
        "</PropertyGroup></Project>",
        encoding="utf-8",
    )
    (target / "Plugin.cs").write_text(
        "namespace Example; public sealed class Plugin { public void Load() {} }\n",
        encoding="utf-8",
    )
    (target / "nuget.config").write_text("<configuration />", encoding="utf-8")

    digest = "0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0"
    identity = {
        "name": "qwen3:4b-instruct",
        "model": "qwen3:4b-instruct",
        "digest": digest,
        "modified_at": "2026-07-16T14:06:42.9800065+08:00",
        "size": 2497293803,
        "details": {
            "context_length": 262144,
            "parameter_size": "4.0B",
            "quantization_level": "Q4_K_M",
        },
        "capabilities": ["completion", "tools"],
        "base_url": "http://127.0.0.1:11434",
    }
    monkeypatch.setattr(local_entry_module, "_read_ollama_model_identity", lambda *_: identity)
    monkeypatch.setattr(local_entry_module, "_read_ollama_server_version", lambda *_: "0.32.1")
    monkeypatch.setattr(
        local_entry_module.LLMFactory,
        "create",
        staticmethod(lambda settings, **kwargs: local_entry_module.OllamaLLM(settings, **kwargs)),
    )

    def deterministic_chat(self, messages, trace=None, **kwargs):
        request = json.loads(messages[-1].content)
        coverage_response = _formal_coverage_model_response(request)
        if coverage_response is not None:
            recorder = kwargs.get("provider_request_recorder")
            if callable(recorder):
                recorder(
                    {
                        "body_sha256": "sha256:" + "c" * 64,
                        "body_utf8": "{}",
                        "body_size_bytes": 2,
                        "context_admission": {
                            "mode": "provider_body_utf8_proxy_plus_output_budget_v1",
                            "admitted": True,
                        },
                        "timeout_seconds": self.timeout,
                        "trust_environment": False,
                        "follow_redirects": False,
                    }
                )
            return ChatResponse(
                content=json.dumps(coverage_response),
                model="qwen3:4b-instruct",
                usage={
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                    "total_tokens": 30,
                },
                raw_response={"done": True, "done_reason": "stop"},
            )
        changes = []
        for unit in request["required_change_units"]:
            binding_id = unit["edit_binding_id"]
            context = request["edit_binding_contexts"][binding_id]
            before = context["source_excerpt"]
            markers = request["required_validation_by_binding"].get(binding_id) or []
            marker_text = " ".join(
                item for item in markers if re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", item)
            )
            replacement = "{ /* PRODUCT_TEST_CHANGE"
            if marker_text:
                replacement += f" {marker_text}"
            replacement += " */ }"
            after = before.replace("{}", replacement, 1)
            if after == before:
                after = before + "\n// PRODUCT_TEST_CHANGE " + marker_text
            changes.append(
                {
                    "edit_binding_id": binding_id,
                    "rationale": "Deterministic evidence-bound CLI integration change.",
                    "rollback_hint": "Restore the exact prior source text.",
                    "after_text": after,
                }
            )
        recorder = kwargs.get("provider_request_recorder")
        if callable(recorder):
            recorder(
                {
                    "body_sha256": "sha256:" + "a" * 64,
                    "body_utf8": "{}",
                    "timeout_seconds": self.timeout,
                    "trust_environment": False,
                    "follow_redirects": False,
                }
            )
        return ChatResponse(
            content=json.dumps({"changes": changes}),
            model="qwen3:4b-instruct",
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            raw_response={"done": True, "done_reason": "stop"},
        )

    monkeypatch.setattr(local_entry_module.OllamaLLM, "chat", deterministic_chat)
    _install_public_run_request_native_chat(monkeypatch, deterministic_chat)

    def build(profile):
        artifact = profile.working_directory / "bin" / "Debug" / "Example.dll"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(b"deterministic compiled artifact")
        return local_entry_module.NuGetIsolatedBuildExecution(
            restore_exit_code=0,
            build_exit_code=0,
            restore_stdout="restore ok",
            restore_stderr="",
            build_stdout="build ok",
            build_stderr="",
            duration_ms=2,
        )

    monkeypatch.setattr(local_entry_module, "_run_nuget_isolated_build", build)

    class ExactApprovalInput:
        def readline(self) -> str:
            for path in workspace.rglob("*.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError, UnicodeDecodeError):
                    continue
                if payload.get("artifact_type") == "dry_run_result":
                    dry_run = payload.get("data") or {}
                    if dry_run.get("human_semantic_review_required") is True:
                        return _human_semantic_approval_line(dry_run)
            raise AssertionError("CLI requested approval before durable DryRunResult existed")

    monkeypatch.setattr("src.mod_agent.cli.sys.stdin", ExactApprovalInput())
    production_run_local_request = local_entry_module.run_local_request

    def run_with_main_ollama_timeout(**kwargs):
        return production_run_local_request(
            **kwargs,
            ollama_timeout_seconds=600.0,
        )

    monkeypatch.setattr(
        "src.mod_agent.cli.run_local_request",
        run_with_main_ollama_timeout,
    )
    planning_target_id = _read_exact_test_planning_target_id(
        tmp_path,
        target / "Plugin.cs",
    )
    exit_code = main(
        [
            "run-request",
            "make Load record deterministic product diagnostics",
            "--target-project",
            str(target),
            "--workspace-root",
            str(workspace),
            "--settings",
            "config/settings.yaml",
            "--local-ollama",
            "--ollama-model",
            "qwen3:4b-instruct",
            "--ollama-context-window",
            "32768",
            "--task-model-call-limit",
            "9",
            "--confirm-isolated-write",
            "--allow-build",
            "--planning-target-evidence-id",
            planning_target_id,
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert "product_execution_result" in payload, payload
    machine = payload["product_execution_result"]
    assert exit_code == 0, payload
    assert machine["platform_status"] == "completed"
    assert machine["execution_disposition"] == "succeeded"
    assert machine["terminal_node"] == "build"
    assert [item["artifact_role"] for item in machine["store_attempts"][-4:]] == [
        "dry_run_result",
        "isolated_apply_result",
        "build_result",
        "workflow_checkpoint",
    ]
    assert all(
        item["store_result"]["outcome"] == "committed"
        for item in machine["store_attempts"]
    )
    evidence_envelope = next(
        value
        for path in workspace.rglob("*.json")
        if (value := json.loads(path.read_text(encoding="utf-8"))).get(
            "artifact_type"
        )
        == "evidence_pack"
    )
    coverage_audits = evidence_envelope["data"]["budget_summary"][
        "requirement_coverage_model_audits"
    ]
    assert [audit["model_role"] for audit in coverage_audits] == [
        "requirement_projection",
        "requirement_findings",
    ]
    assert all(audit["payload_sha256"] for audit in coverage_audits)
    assert all(
        audit["model_identity"]["digest"] == digest
        for audit in coverage_audits
    )
    assert all(
        audit["provider_request"]["context_admission"]["admitted"] is True
        for audit in coverage_audits
    )
    assert all(
        audit["provider_request"]["timeout_seconds"] == 600.0
        for audit in coverage_audits
    )
    assert all(
        "body_utf8" not in audit["provider_request"]
        for audit in coverage_audits
    )
    initial_patch_audit = payload["local_model_input_audit"]
    assert initial_patch_audit["model_role"] == "initial_patch"
    assert initial_patch_audit["provider_request"]["timeout_seconds"] == 600.0
    assert (
        initial_patch_audit["provider_request_profile"]["timeout_seconds"]
        == 600.0
    )
    manifest = json.loads(
        (Path(payload["run_root"]) / "run_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["ollama_patch_generation_profile"]["timeout_seconds"] == 600.0


def _public_patch_upstream_scenario(
    tmp_path, monkeypatch, capsys, *, owner="evidence", repair_limit=2,
    task_limit=9, planning_timeout=False, repeat_upstream=False,
    fail_first=False, retain_plan=False,
    initial_findings_gap=False, findings_still_missing=False, findings_limit=2,
    initial_provider_available=True, initial_query_timeout=False,
    source_retrieval_mode=None, source_setup=None, upstream_query="RefreshSharedState",
    request_patch_upstream=True, patch_response_transform=None,
    request_description=None, omit_approval_reader=False,
    upstream_reason="Offline fixture needs the unobserved shared-state source before patching.",
    upstream_repeat_count=0, model_call_budget_policy=None,
):
    """Deterministic HTTP/baseline compiler; stop before product Apply or Build."""
    from src.mod_agent.evidence.rg_live import RgLiveEvidenceProvider
    from src.mod_agent.proposal.patch_agent_loop import PATCH_UPSTREAM_REQUEST_TOOL_NAME

    ordinary_install = _install_public_run_request_native_chat
    ordinary_main = main
    actual_chat = local_entry_module.OllamaLLM.chat
    observed = SimpleNamespace(
        roles=[], requests=[], patch_contexts=[], findings=[], planning=[], searches=[],
        result=None, exit_code=None, source_bytes=None,
        evaluations=[], worker_requests=[], generated_responses=[],
    )

    def collect(provider, **kwargs):
        result = actual_collect(provider, **kwargs)
        observed.searches.append((kwargs, result))
        return result

    actual_collect = RgLiveEvidenceProvider.collect_query_set
    monkeypatch.setattr(RgLiveEvidenceProvider, "collect_query_set", collect)

    if fail_first:
        from dataclasses import replace
        from src.mod_agent.request_patch_execution import RequestPatchExecution
        ordinary_init = RequestPatchExecution.__init__

        def evaluate(context):
            passed = "PRODUCT_TEST_REPAIRED" in json.dumps(context["generated_changes"])
            report = {
                "status": "passed" if passed else "behavior_failed",
                "failure_owner": None if passed else "patch_implementation",
                "owner_binding_ids": [row["edit_binding_id"] for row in context["generated_changes"]],
                "observations": [{"check_id": "synthetic_product_marker", "passed": passed,
                    "detail": "Deterministic evaluator requires the repaired marker."}],
                "generated_changes_sha256": context["generated_changes_sha256"],
                "source_snapshot_sha256": context["source_snapshot_sha256"],
                "execution_origin": "executed",
            }
            path = tmp_path / f"behavior-{len(observed.evaluations) + 1}.json"
            raw = json.dumps(report).encode("utf-8")
            path.write_bytes(raw)
            report["report_ref"] = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
            observed.evaluations.append((context, report))
            return report

        evaluate.verification_identity = lambda: {
            "validator_sha256": "1" * 64, "inputs_sha256": "2" * 64,
            "environment_sha256": "3" * 64, "deterministic_reuse_allowed": True,
        }

        def initialize(self, **kwargs):
            kwargs["behavior_evaluator"] = evaluate
            # Select this scenario's three-turn worker before its first call.
            kwargs["policy"] = replace(kwargs["policy"], max_total_model_turns=3)
            return ordinary_init(self, **kwargs)

        monkeypatch.setattr(RequestPatchExecution, "__init__", initialize)

    def install_transport(patcher, deterministic_chat):
        ordinary_install(patcher, deterministic_chat)

        def transport(_transport, request):
            assert str(request.url) == "http://127.0.0.1:11434/api/chat"
            payload = json.loads(request.content)
            observed.requests.append(payload)
            contexts = []
            for message in payload["messages"]:
                if message["role"] != "user":
                    continue
                try:
                    context = json.loads(message["content"])
                except (ValueError, TypeError):
                    continue
                if "patch_agent_context_encoding" in context:
                    context = local_entry_module._restore_patch_agent_context(context)
                contexts.append(context)
            context = next((value for value in contexts if value.get("message_type") in {
                "product_requirement_projection", "product_requirement_findings",
                "patch_upstream_evidence_queries", "initial_findings_evidence_queries",
            }), None)
            if context is not None:
                message_type = context["message_type"]
                observed.roles.append(message_type)
                if message_type in {"patch_upstream_evidence_queries", "initial_findings_evidence_queries"}:
                    if message_type == "initial_findings_evidence_queries" and initial_query_timeout:
                        raise httpx.ReadTimeout("Offline initial-Findings query timeout.", request=request)
                    gaps = context["gap_investigation_targets"]
                    if message_type == "initial_findings_evidence_queries":
                        assert gaps, "Initial Findings investigation requires an actual accepted gap."
                    query_text = (upstream_query[observed.roles.count("patch_upstream_evidence_queries") - 1]
                        if isinstance(upstream_query, (tuple, list)) else upstream_query)
                    content = {"queries": [{"query": query_text,
                        "requirement_id": context["requirements"][0]["requirement_id"],
                        "gap_ids": [gaps[0]["gap_id"]] if gaps else [],
                        "current_fact_needed": "Existing source ownership.",
                        "modification_impact": "Planning needs a bound current fact.",
                        "authorized_source": "target_source",
                        "metadata_queries": []}]}
                else:
                    content = _formal_coverage_model_response(context)
                    if message_type == "product_requirement_findings":
                        observed.findings.append(context)
                        ids = [row["evidence_id"] for row in context["source_observations"]]
                        for row in content["findings"]:
                            row["evidence_ids"] = ids
                            if row["edit_target_evidence_ids"]:
                                row["edit_target_evidence_ids"] = ids
                        if initial_findings_gap and (len(observed.findings) == 1 or findings_still_missing):
                            for row in content["findings"]:
                                row.update(relationship="missing", evidence_ids=[],
                                    edit_target_evidence_ids=[],
                                    unresolved_gaps=["Offline fixture requires the unobserved shared-state source."])
            else:
                planning = next((value for value in contexts if "allowed_edit_evidence_ids" in value), None)
                if planning is not None:
                    observed.roles.append("planning")
                    observed.planning.append(planning)
                    if len(observed.planning) > 1 and planning_timeout:
                        raise httpx.ReadTimeout("Offline product upstream timeout.", request=request)
                    content = {"decision": "select_targets",
                        "selected_evidence_ids": planning["allowed_edit_evidence_ids"],
                        "rationale": "Deterministic product-entry reassessment over current source evidence.",
                        "missing_evidence": []}
                    if len(observed.planning) > 1 and retain_plan:
                        content.update(decision="retain_current_plan", selected_evidence_ids=[])
                else:
                    observed.roles.append("patch")
                    context = next(value for value in contexts if "required_change_units" in value)
                    observed.patch_contexts.append(context)
                    observed.worker_requests.append(contexts)
                    upstream_turn = 2 if fail_first else 1
                    if request_patch_upstream and not initial_findings_gap and (
                        upstream_turn <= len(observed.patch_contexts) <= upstream_turn + upstream_repeat_count or (
                            repeat_upstream and len(observed.patch_contexts) > upstream_turn
                        )
                    ):
                        tool = next(row["function"] for row in payload["tools"]
                            if row["function"]["name"] == PATCH_UPSTREAM_REQUEST_TOOL_NAME)
                        binding_id = context["required_change_units"][0]["edit_binding_id"]
                        message = {"role": "assistant", "content": "", "tool_calls": [{"function": {
                            "name": tool["name"], "arguments": {"required_owner": owner,
                                "reason": upstream_reason,
                                "source_refs": [f"binding://{binding_id}"]}}}]}
                        return response(request, payload, message)
                    content = json.loads(deterministic_chat(
                        SimpleNamespace(), [SimpleNamespace(content=json.dumps(context))]).content)
                    if fail_first and len(observed.patch_contexts) > upstream_turn:
                        for row in content["changes"]:
                            row["after_text"] += "\n// PRODUCT_TEST_REPAIRED\n"
                    if patch_response_transform is not None:
                        content = patch_response_transform(content)
                    observed.generated_responses.append(json.dumps(content))
            return response(request, payload, {"role": "assistant", "content": json.dumps(content)})

        def response(request, payload, message):
            return httpx.Response(200, request=request, json={"model": payload["model"],
                "message": message, "done": True, "done_reason": "stop",
                "prompt_eval_count": 10, "eval_count": 20})

        patcher.setattr(httpx.HTTPTransport, "handle_request", transport)
        patcher.setattr(local_entry_module.OllamaLLM, "chat", actual_chat)

    class ScenarioComplete(Exception):
        pass

    def run_without_approval(arguments):
        if request_description is not None:
            arguments = [arguments[0], request_description, *arguments[2:]]
        (tmp_path / "Example" / "SharedState.cs").write_text(
            "namespace Example;\npublic sealed class SharedState\n{\n"
            "    public void RefreshSharedState() {}\n}\n", encoding="utf-8")
        if source_setup is not None:
            source_setup(tmp_path / "Example")
        observed.source_bytes = {path.name: path.read_bytes()
            for path in (tmp_path / "Example").glob("*.cs")}
        offset = arguments.index("--planning-target-evidence-id")
        arguments = arguments[:offset] + arguments[offset + 2:]
        if source_retrieval_mode is not None:
            arguments = [*arguments, "--source-retrieval", source_retrieval_mode]
        run_local = cli_module.run_local_request

        def run_with_budget(**kwargs):
            kwargs.update(task_model_call_limit=task_limit, stage_model_call_limits={
                "requirement_projection": 2, "requirement_findings": findings_limit, "planning": 1,
                "initial_patch": 3 if fail_first else 2, "repair": repair_limit,
            })
            if model_call_budget_policy is not None:
                kwargs["model_call_budget_policy"] = model_call_budget_policy
            if omit_approval_reader:
                kwargs.pop("diff_approval_reader", None)
            return run_local(**kwargs)

        monkeypatch.setattr(cli_module, "run_local_request", run_with_budget)
        if not initial_provider_available:
            adapters_type = local_entry_module.ProductExecutionAdaptersV1

            def without_initial_reassessment(**kwargs):
                kwargs["initial_findings_reassessment_factory"] = None
                return adapters_type(**kwargs)

            monkeypatch.setattr(local_entry_module, "ProductExecutionAdaptersV1", without_initial_reassessment)
        observed.exit_code = ordinary_main([*arguments, "--defer-approval"])
        observed.result = json.loads(capsys.readouterr().out)
        raise ScenarioComplete

    monkeypatch.setattr(sys.modules[__name__], "_install_public_run_request_native_chat", install_transport)
    monkeypatch.setattr(sys.modules[__name__], "main", run_without_approval)
    monkeypatch.setattr("socket.socket.connect", lambda *_args, **_kwargs:
        pytest.fail("No actual network or model request is permitted."))
    with pytest.raises(ScenarioComplete):
        test_cli_run_request_real_public_product_executor_compile_success(tmp_path, monkeypatch, capsys)
    assert {path.name: path.read_bytes() for path in (tmp_path / "Example").glob("*.cs")} == observed.source_bytes
    return observed


@pytest.mark.parametrize("outer_whitespace", [" ", "\t\r\n", "\u3000"])
def test_cli_run_request_preserves_feature_request_identity_with_outer_whitespace(
    tmp_path, monkeypatch, capsys, outer_whitespace,
):
    request = "make Load record deterministic\nproduct  diagnostics"
    observed = _public_patch_upstream_scenario(
        tmp_path, monkeypatch, capsys, request_patch_upstream=False,
        request_description=outer_whitespace + request + outer_whitespace,
    )
    assert observed.exit_code == 0, observed.result
    assert observed.result["status"] == "awaiting_approval", observed.result
    assert observed.roles == ["product_requirement_projection",
        "product_requirement_findings", "planning", "patch"]
    run_root = Path(observed.result["run_root"])
    feature = json.loads(next(run_root.rglob("feature_spec.json")).read_text(encoding="utf-8"))
    evidence = json.loads(next(run_root.rglob("evidence_pack.json")).read_text(encoding="utf-8"))
    assert feature["data"]["user_request"] == evidence["data"]["query"] == outer_whitespace + request + outer_whitespace
    assert "\n" in evidence["data"]["query"] and "product  diagnostics" in evidence["data"]["query"]
    assert len(observed.planning) == len(observed.patch_contexts) == 1
    assert observed.result["actual_write_performed"] is False
    assert observed.result["approval_recorded"] is False
    assert observed.result["builds_performed"] == observed.result["runtime_executions_performed"] == 0


def test_cli_run_request_deferred_mode_can_omit_an_approval_reader(tmp_path, monkeypatch, capsys):
    observed = _public_patch_upstream_scenario(tmp_path, monkeypatch, capsys,
        request_patch_upstream=False, omit_approval_reader=True)
    assert observed.exit_code == 0, observed.result
    assert observed.result["status"] == "awaiting_approval"
    assert observed.result["actual_write_performed"] is False
    assert observed.result["approval_recorded"] is False
    assert observed.result["model_call_count"] == len(observed.requests) == 4


def test_run_request_non_deferred_mode_still_requires_approval_reader(tmp_path, monkeypatch):
    monkeypatch.setattr(local_entry_module.LLMFactory, "create",
        lambda *_args, **_kwargs: pytest.fail("Missing approval reader reached model construction"))
    with pytest.raises(local_entry_module.LocalEntryError, match="exact diff approval reader"):
        local_entry_module.run_local_request(description="Update the configured default.",
            target_project=tmp_path / "source", workspace_base=tmp_path / "runs",
            settings_path="config/settings.yaml", confirm_isolated_write=True, allow_build=True,
            allow_source_disclosure=False, local_ollama=True, task_model_call_limit=9)


def test_cli_run_request_patch_evidence_return_executes_new_search_and_reaches_original_review(
    tmp_path, monkeypatch, capsys,
):
    observed = _public_patch_upstream_scenario(tmp_path, monkeypatch, capsys)
    assert observed.roles == ["product_requirement_projection", "product_requirement_findings",
        "planning", "patch", "patch_upstream_evidence_queries", "product_requirement_findings",
        "planning", "patch"], observed.result
    assert observed.exit_code == 0 and observed.result["status"] == "awaiting_approval", observed.result
    assert len(observed.searches) == 2
    added_queries, added_pack = observed.searches[-1]
    assert [row["query"] for row in added_queries["queries"]] == ["RefreshSharedState"]
    query_request = next(json.loads(message["content"])
        for request in observed.requests for message in request["messages"] if message["role"] == "user"
        and isinstance(message["content"], str) and '"patch_upstream_evidence_queries"' in message["content"])
    assert query_request["gap_investigation_targets"] == []
    assert len(added_pack.items) == 1 and "RefreshSharedState" in added_pack.items[0].excerpt
    old_ids = {row["evidence_id"] for row in observed.findings[0]["source_observations"]}
    new_ids = {row["evidence_id"] for row in observed.findings[-1]["source_observations"]}
    assert new_ids - old_ids == {added_pack.items[0].evidence_id}
    assert set(observed.planning[-1]["allowed_edit_evidence_ids"]) == new_ids
    assert len(observed.patch_contexts[0]["required_change_units"]) == 1
    assert len(observed.patch_contexts[-1]["required_change_units"]) == 2
    assert "RefreshSharedState" in json.dumps(observed.patch_contexts[-1])
    resumed = next(row for row in observed.worker_requests[-1]
        if row.get("message_type") == "patch_replanned_context")
    assert resumed["prior_code_role"] == "no_failed_code_generated"
    assert "validator_feedback" not in resumed
    repair_path = next((tmp_path / "runs").rglob("repair_plan.json"))
    repair = json.loads(repair_path.read_text(encoding="utf-8"))["data"]
    assert repair["failure_findings"] == []
    assert repair["repair_context"]["failure_report"] is None
    assert repair["repair_context"]["failed_response_ref"] is None
    assert repair["repair_context"]["current_failure_available"] is False
    result = observed.result
    assert result["actual_write_performed"] is False and result["approval_recorded"] is False
    assert result["builds_performed"] == result["runtime_executions_performed"] == 0
    assert result["canonical_source_unchanged"] is True
    budget = result["model_call_budget"]
    assert budget["maximum"] == 9 and budget["consumed"] == len(observed.requests) == 8
    assert budget["policy"] == "task_total_only"
    assert budget["by_stage"]["planning"] == {"consumed": 1}
    assert budget["by_stage"]["repair"] == {"consumed": 2}


def test_cli_run_request_initial_findings_gap_searches_before_first_plan_and_patch(
    tmp_path, monkeypatch, capsys,
):
    observed = _public_patch_upstream_scenario(tmp_path, monkeypatch, capsys, initial_findings_gap=True)
    assert observed.exit_code == 0 and observed.result["status"] == "awaiting_approval", observed.result
    assert len(observed.findings) == 2
    assert observed.roles == ["product_requirement_projection", "product_requirement_findings",
        "initial_findings_evidence_queries", "product_requirement_findings", "planning", "patch"]
    assert len(observed.planning) == len(observed.patch_contexts) == 1
    assert len(observed.searches) == 2
    assert observed.roles.count("product_requirement_projection") == 1
    added_queries, added_pack = observed.searches[-1]
    assert [row["query"] for row in added_queries["queries"]] == ["RefreshSharedState"]
    assert len(added_pack.items) == 1 and "RefreshSharedState" in added_pack.items[0].excerpt
    old_ids = {row["evidence_id"] for row in observed.findings[0]["source_observations"]}
    current_ids = {row["evidence_id"] for row in observed.findings[-1]["source_observations"]}
    assert current_ids - old_ids == {added_pack.items[0].evidence_id}
    assert observed.findings[0]["relations"] == observed.findings[-1]["relations"]
    assert set(observed.planning[0]["allowed_edit_evidence_ids"]) == current_ids
    assert "RefreshSharedState" in json.dumps(observed.patch_contexts[0])
    assert len(observed.patch_contexts[0]["required_change_units"]) == 2
    assert observed.evaluations == []
    assert not list((tmp_path / "runs").rglob("repair_plan.json"))
    assert not any(row.get("message_type") == "patch_replanned_context"
        for contexts in observed.worker_requests for row in contexts)
    result = observed.result
    assert result["actual_write_performed"] is False and result["approval_recorded"] is False
    assert result["builds_performed"] == result["runtime_executions_performed"] == 0
    assert result["model_call_budget"]["maximum"] == 9
    assert result["model_call_budget"]["consumed"] == len(observed.requests) == 6
    assert result["model_call_budget"]["policy"] == "task_total_only"
    assert result["model_call_budget"]["by_stage"]["requirement_projection"] == {"consumed": 1}
    assert result["model_call_budget"]["by_stage"]["requirement_findings"] == {"consumed": 2}


@pytest.mark.parametrize("stop", ["still_missing", "missing_provider", "findings_budget", "task_budget", "query_timeout"])
def test_cli_run_request_initial_findings_gap_stops_without_first_plan_or_patch(
    tmp_path, monkeypatch, capsys, stop,
):
    observed = _public_patch_upstream_scenario(tmp_path, monkeypatch, capsys,
        initial_findings_gap=True, findings_still_missing=stop == "still_missing",
        initial_provider_available=stop != "missing_provider",
        findings_limit=1 if stop == "findings_budget" else 2,
        task_limit=2 if stop == "task_budget" else 9,
        # 为什么要有它：仅阶段额度用例显式选旧可选策略，其余检验当前任务总额度模式。
        model_call_budget_policy="stage_and_total" if stop == "findings_budget" else "task_total_only",
        initial_query_timeout=stop == "query_timeout")
    assert observed.exit_code != 0, observed.result
    assert "product_execution_result" in observed.result, observed.result
    result = observed.result
    machine = result["product_execution_result"]
    assert machine["blockers"]
    assert observed.planning == observed.patch_contexts == []
    assert not any(row["artifact_role"] in {
        "implementation_plan", "repair_plan", "patch_proposal", "proposal_review", "dry_run_result",
    } for row in machine["outputs"])
    assert not list((tmp_path / "runs").rglob("repair_plan.json"))
    expected_calls = {"still_missing": 6, "missing_provider": 2, "findings_budget": 2,
        "task_budget": 2, "query_timeout": 3}[stop]
    assert result["model_call_budget"]["consumed"] == len(observed.requests) == expected_calls
    assert observed.roles[:2] == ["product_requirement_projection", "product_requirement_findings"]
    assert observed.roles.count("product_requirement_projection") == 1
    assert observed.roles.count("initial_findings_evidence_queries") == (
        2 if stop == "still_missing" else 1 if stop == "query_timeout" else 0)
    assert len(observed.findings) == (3 if stop == "still_missing" else 1)
    assert len(observed.searches) == (3 if stop == "still_missing" else 1)
    assert result["actual_write_performed"] is False
    if stop in {"task_budget", "findings_budget"}:
        code = "PRODUCT_STAGE_MODEL_CALL_BUDGET_EXHAUSTED" if stop == "findings_budget" else "PRODUCT_MODEL_CALL_BUDGET_EXHAUSTED"
        assert code in json.dumps(machine["blockers"])
    if stop == "still_missing":
        assert machine["execution_disposition"] == "domain_blocked"
        assert "required_requirement_unresolved" in json.dumps(machine["blockers"])


@pytest.mark.parametrize("stop", ["repair_budget", "task_budget", "planning_timeout"])
def test_cli_run_request_patch_upstream_stops_with_consumed_original_budget(
    tmp_path, monkeypatch, capsys, stop,
):
    observed = _public_patch_upstream_scenario(tmp_path, monkeypatch, capsys,
        owner="planning" if stop == "planning_timeout" else "evidence",
        repair_limit=1 if stop == "repair_budget" else 2,
        task_limit=6 if stop == "task_budget" else 9,
        # 为什么要有它：这些断言检查阶段上限，不能将可选阶段策略误当默认任务策略。
        model_call_budget_policy="stage_and_total",
        planning_timeout=stop == "planning_timeout")
    assert observed.exit_code != 0, observed.result
    assert "product_execution_result" in observed.result, observed.result
    machine = observed.result["product_execution_result"]
    assert machine["execution_disposition"] == "domain_blocked"
    assert any(row["code"] == "PLANNING_MODEL_SELECTION_FAILED" for row in machine["blockers"])
    assert not any(row["artifact_role"] in {"patch_proposal", "proposal_review", "dry_run_result"}
        for row in machine["outputs"])
    assert len(observed.patch_contexts) == 1
    budget = observed.result["model_call_budget"]
    assert budget["consumed"] == len(observed.requests)
    assert budget["by_stage"]["planning"] == {"maximum": 1, "consumed": 1, "remaining": 0}
    if stop == "planning_timeout":
        assert observed.roles == ["product_requirement_projection", "product_requirement_findings",
            "planning", "patch", "planning"]
        assert budget["consumed"] == 5
        assert budget["by_stage"]["repair"] == {"maximum": 2, "consumed": 1, "remaining": 1}
    else:
        assert observed.roles == ["product_requirement_projection", "product_requirement_findings",
            "planning", "patch", "patch_upstream_evidence_queries", "product_requirement_findings"]
        assert budget["consumed"] == 6
        assert budget["by_stage"]["requirement_findings"] == {"maximum": 2, "consumed": 2, "remaining": 0}
        assert "PRODUCT_MODEL_CALL_BUDGET_EXHAUSTED" in json.dumps(machine["blockers"])
    assert observed.result["actual_write_performed"] is False


def test_cli_run_request_real_public_product_executor_runtime_success(
    short_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = short_workspace / "Example"
    bepinex = short_workspace / "BepInEx"
    workspace = short_workspace / "runs"
    runtime_root = short_workspace / "runtime"
    destination = runtime_root / "BepInEx" / "plugins" / "Example.dll"
    target.mkdir()
    bepinex.mkdir()
    destination.parent.mkdir(parents=True)
    executable = runtime_root / "GTFO.exe"
    executable.write_bytes(b"deterministic runtime executable")
    runtime_config = runtime_root / "BepInEx" / "config" / "BepInEx.cfg"
    runtime_config.parent.mkdir(parents=True, exist_ok=True)
    runtime_config.write_text(
        "[Logging.Disk]\nAppendLog = false\n", encoding="utf-8"
    )
    (target / "Example.csproj").write_text(
        "<Project><PropertyGroup>"
        "<AssemblyName>Example</AssemblyName>"
        f"<BepInExDir>{bepinex}</BepInExDir>"
        "</PropertyGroup></Project>",
        encoding="utf-8",
    )
    (target / "Plugin.cs").write_text(
        "namespace Example; public sealed class Plugin { public void Load() {} }\n",
        encoding="utf-8",
    )
    (target / "nuget.config").write_text("<configuration />", encoding="utf-8")
    settings_payload = yaml.safe_load(Path("config/settings.yaml").read_text(encoding="utf-8"))
    settings_payload["runtime"]["gtfo"].update(
        {
            "enabled": True,
            "game_executable": str(executable),
            "working_directory": str(runtime_root),
            "launch_args": ["-deterministic-test"],
            "log_paths": ["BepInEx/LogOutput.log"],
            "screenshot_directory": str(runtime_root / "screenshots"),
            "startup_markers": ["Chainloader startup complete"],
            "acceptance_markers": {},
            "terminate_after_capture": True,
        }
    )
    settings_path = short_workspace / "settings.yaml"
    settings_path.write_text(yaml.safe_dump(settings_payload), encoding="utf-8")

    digest = "0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0"
    identity = {
        "name": "qwen3:4b-instruct",
        "model": "qwen3:4b-instruct",
        "digest": digest,
        "modified_at": "2026-07-16T14:06:42.9800065+08:00",
        "size": 2497293803,
        "details": {
            "context_length": 262144,
            "parameter_size": "4.0B",
            "quantization_level": "Q4_K_M",
        },
        "capabilities": ["completion", "tools"],
        "base_url": "http://127.0.0.1:11434",
    }
    monkeypatch.setattr(local_entry_module, "_read_ollama_model_identity", lambda *_: identity)
    monkeypatch.setattr(local_entry_module, "_read_ollama_server_version", lambda *_: "0.32.1")
    monkeypatch.setattr(
        local_entry_module.LLMFactory,
        "create",
        staticmethod(lambda settings, **kwargs: local_entry_module.OllamaLLM(settings, **kwargs)),
    )

    def deterministic_chat(self, messages, trace=None, **kwargs):
        request = json.loads(messages[-1].content)
        coverage_response = _formal_coverage_model_response(request)
        if coverage_response is not None:
            recorder = kwargs.get("provider_request_recorder")
            if callable(recorder):
                recorder(
                    {
                        "body_sha256": "sha256:" + "c" * 64,
                        "body_utf8": "{}",
                        "body_size_bytes": 2,
                        "context_admission": {
                            "mode": "provider_body_utf8_proxy_plus_output_budget_v1",
                            "admitted": True,
                        },
                        "timeout_seconds": 120,
                        "trust_environment": False,
                        "follow_redirects": False,
                    }
                )
            return ChatResponse(
                content=json.dumps(coverage_response),
                model="qwen3:4b-instruct",
                usage={
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                    "total_tokens": 30,
                },
                raw_response={"done": True, "done_reason": "stop"},
            )
        changes = []
        for unit in request["required_change_units"]:
            binding_id = unit["edit_binding_id"]
            context = request["edit_binding_contexts"][binding_id]
            before = context["source_excerpt"]
            markers = request["required_validation_by_binding"].get(binding_id) or []
            marker_text = " ".join(
                item for item in markers if re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", item)
            )
            replacement = "{ /* PRODUCT_RUNTIME_TEST_CHANGE"
            if marker_text:
                replacement += f" {marker_text}"
            replacement += " */ }"
            after = before.replace("{}", replacement, 1)
            if after == before:
                after = before + "\n// PRODUCT_RUNTIME_TEST_CHANGE " + marker_text
            changes.append(
                {
                    "edit_binding_id": binding_id,
                    "rationale": "Deterministic evidence-bound Runtime CLI change.",
                    "rollback_hint": "Restore the exact prior source text.",
                    "after_text": after,
                }
            )
        recorder = kwargs.get("provider_request_recorder")
        if callable(recorder):
            recorder(
                {
                    "body_sha256": "sha256:" + "b" * 64,
                    "body_utf8": "{}",
                    "timeout_seconds": 120,
                    "trust_environment": False,
                    "follow_redirects": False,
                }
            )
        return ChatResponse(
            content=json.dumps({"changes": changes}),
            model="qwen3:4b-instruct",
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            raw_response={"done": True, "done_reason": "stop"},
        )

    monkeypatch.setattr(local_entry_module.OllamaLLM, "chat", deterministic_chat)
    _install_public_run_request_native_chat(monkeypatch, deterministic_chat)

    def build(profile):
        artifact = profile.working_directory / "bin" / "Debug" / "Example.dll"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(b"deterministic runtime compiled artifact")
        return local_entry_module.NuGetIsolatedBuildExecution(
            restore_exit_code=0,
            build_exit_code=0,
            restore_stdout="restore ok",
            restore_stderr="",
            build_stdout="build ok",
            build_stderr="",
            duration_ms=2,
        )

    monkeypatch.setattr(local_entry_module, "_run_nuget_isolated_build", build)

    def deterministic_runtime_factory(**_kwargs):
        def run(feature_id, build_payload, feature_spec):
            criteria = tuple(feature_spec["acceptance_criteria"])
            return build_real_runtime_evidence_payload(
                feature_id=feature_id,
                input_execution_mode=build_payload["execution_mode"],
                evidence_items=(
                    RuntimeEvidenceItem(
                        item_type="runtime_log",
                        source="deterministic_cli_runtime",
                        locator="runtime://cli-success",
                        supports_acceptance=criteria,
                        confidence=1.0,
                        raw_excerpt="All requested Runtime criteria were observed.",
                    ),
                ),
                startup_loaded=True,
                gameplay_behavior_verified=True,
                verification_status="verified",
                raw_runtime_output="All requested Runtime criteria were observed.",
                acceptance_criteria=criteria,
                runtime_verification_plan=tuple(feature_spec["runtime_verification_plan"]),
                plugin_marker_binding={
                    "marker_source": "deterministic_cli_runtime",
                    "markers": [
                        {
                            "acceptance_criterion": criterion,
                            "marker": f"CLI_MARKER_{index}",
                            "observed": True,
                        }
                        for index, criterion in enumerate(criteria, start=1)
                    ],
                },
            )

        return run

    monkeypatch.setattr(
        local_entry_module,
        "_make_deploying_runtime_evidence_factory",
        deterministic_runtime_factory,
    )

    class ExactApprovalInput:
        def readline(self) -> str:
            for path in workspace.rglob("*.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError, UnicodeDecodeError):
                    continue
                if payload.get("artifact_type") == "dry_run_result":
                    dry_run = payload.get("data") or {}
                    if dry_run.get("human_semantic_review_required") is True:
                        return _human_semantic_approval_line(dry_run)
            raise AssertionError("CLI requested approval before durable DryRunResult existed")

    monkeypatch.setattr("src.mod_agent.cli.sys.stdin", ExactApprovalInput())
    planning_target_id = _read_exact_test_planning_target_id(
        short_workspace,
        target / "Plugin.cs",
    )
    exit_code = main(
        [
            "run-request",
            "make Load record deterministic product diagnostics",
            "--target-project",
            str(target),
            "--workspace-root",
            str(workspace),
            "--settings",
            str(settings_path),
            "--local-ollama",
            "--ollama-model",
            "qwen3:4b-instruct",
            "--ollama-context-window",
            "32768",
            "--confirm-isolated-write",
            "--allow-build",
            "--run-gtfo-runtime",
            "--allow-game-launch",
            "--runtime-plugin-destination",
            str(destination),
            "--allow-game-directory-write",
            "--planning-target-evidence-id",
            planning_target_id,
            *request_budget_args(),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert "product_execution_result" in payload, payload
    machine = payload["product_execution_result"]
    assert exit_code == 0
    assert machine["platform_status"] == "completed"
    assert machine["execution_disposition"] == "succeeded"
    assert machine["terminal_node"] == "done"
    assert [item["artifact_role"] for item in machine["store_attempts"][-4:]] == [
        "build_result",
        "runtime_evidence",
        "eval_report",
        "workflow_summary",
    ]
    assert all(
        item["store_result"]["outcome"] == "committed"
        for item in machine["store_attempts"]
    )


def test_cli_resume_runtime_passes_fresh_authority_and_handoff_identity(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def resume(**kwargs):
        captured.update(kwargs)
        return {
            "current_stage": "done",
            "runtime_summary": {"claims_real_runtime_success": True},
            "verification_operation_result": {
                "execution_disposition": "succeeded"
            },
        }

    monkeypatch.setattr("src.mod_agent.cli.resume_local_runtime", resume)

    exit_code = main(
        [
            "resume-runtime",
            "--run-root",
            "run-root",
            "--feature-id",
            "feature_001",
            "--checkpoint-path",
            "checkpoint.json",
            "--checkpoint-hash",
            "a" * 64,
            "--resume-id",
            "resume_001",
            "--approved-by",
            "human",
            "--settings",
            "runtime.yaml",
            "--allow-game-launch",
            "--runtime-plugin-destination",
            r"C:\GTFO\BepInEx\plugins\BetterHitFeedback.dll",
            "--allow-game-directory-write",
        ]
    )

    assert exit_code == 0
    json.loads(capsys.readouterr().out)
    assert captured == {
        "run_root": "run-root",
        "artifact_store_root": None,
        "feature_id": "feature_001",
        "checkpoint_path": "checkpoint.json",
        "checkpoint_hash": "a" * 64,
        "resume_id": "resume_001",
        "recover_accepted_resume": False,
        "retry_runtime_observation": False,
        "runtime_output_root": None,
        "approved_by": "human",
        "settings_path": "runtime.yaml",
        "allow_game_launch": True,
        "runtime_plugin_destination": (
            r"C:\GTFO\BepInEx\plugins\BetterHitFeedback.dll"
        ),
        "allow_game_directory_write": True,
    }


def test_cli_runtime_preflight_passes_explicit_store_and_profile_without_authority(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def preflight(**kwargs):
        captured.update(kwargs)
        return {
            "status": "READY_FOR_EXTERNAL_AUTHORIZATION",
            "writes_performed": False,
            "graph_invoked": False,
            "checkpoint_consumed": False,
            "resume_report_created": False,
            "runtime_evidence_created": False,
            "process_launched": False,
            "dll_copied": False,
        }

    monkeypatch.setattr("src.mod_agent.cli.preflight_local_runtime", preflight)

    exit_code = main(
        [
            "preflight-runtime",
            "--run-root",
            "run-root",
            "--artifact-store-root",
            "shared-store",
            "--feature-id",
            "feature_001",
            "--checkpoint-path",
            "checkpoint.json",
            "--checkpoint-hash",
            "a" * 64,
            "--resume-id",
            "preflight_001",
            "--settings",
            "runtime.yaml",
            "--runtime-plugin-destination",
            r"C:\GTFO\BepInEx\plugins\BetterHitFeedback.dll",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "READY_FOR_EXTERNAL_AUTHORIZATION"
    assert payload["writes_performed"] is False
    assert captured == {
        "run_root": "run-root",
        "artifact_store_root": "shared-store",
        "feature_id": "feature_001",
        "checkpoint_path": "checkpoint.json",
        "checkpoint_hash": "a" * 64,
        "resume_id": "preflight_001",
        "recover_accepted_resume": False,
        "retry_runtime_observation": False,
        "runtime_output_root": None,
        "settings_path": "runtime.yaml",
        "runtime_plugin_destination": (
            r"C:\GTFO\BepInEx\plugins\BetterHitFeedback.dll"
        ),
    }


def test_cli_resume_runtime_reports_blocked_admission(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def blocked(**_: object):
        raise LocalEntryError("fresh Runtime authorization is missing")

    monkeypatch.setattr("src.mod_agent.cli.resume_local_runtime", blocked)

    exit_code = main(
        [
            "resume-runtime",
            "--run-root",
            "run-root",
            "--feature-id",
            "feature_001",
            "--checkpoint-path",
            "checkpoint.json",
            "--checkpoint-hash",
            "a" * 64,
            "--approved-by",
            "human",
            "--runtime-plugin-destination",
            r"C:\GTFO\BepInEx\plugins\BetterHitFeedback.dll",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["command"] == "resume-runtime"
    assert payload["status"] == "BLOCKED"


def test_cli_runtime_recovery_passes_exact_resume_id_to_preflight(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def preflight(**kwargs):
        captured.update(kwargs)
        return {
            "status": "READY_FOR_EXTERNAL_AUTHORIZATION",
            "writes_performed": False,
        }

    monkeypatch.setattr("src.mod_agent.cli.preflight_local_runtime", preflight)

    exit_code = main(
        [
            "preflight-runtime",
            "--run-root",
            "run-root",
            "--feature-id",
            "feature_001",
            "--checkpoint-path",
            "checkpoint.json",
            "--checkpoint-hash",
            "a" * 64,
            "--resume-id",
            "resume_accepted_001",
            "--recover-accepted-resume",
        ]
    )

    assert exit_code == 0
    json.loads(capsys.readouterr().out)
    assert captured["resume_id"] == "resume_accepted_001"
    assert captured["recover_accepted_resume"] is True


def test_cli_runtime_observation_retry_passes_separate_output_root(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def preflight(**kwargs):
        captured.update(kwargs)
        return {
            "status": "READY_FOR_EXTERNAL_AUTHORIZATION",
            "writes_performed": False,
            "runtime_observation_retry": {"enabled": True},
        }

    monkeypatch.setattr("src.mod_agent.cli.preflight_local_runtime", preflight)

    exit_code = main(
        [
            "preflight-runtime",
            "--run-root",
            "source-run",
            "--artifact-store-root",
            "shared-store",
            "--feature-id",
            "feature_001",
            "--checkpoint-path",
            "checkpoint.json",
            "--checkpoint-hash",
            "a" * 64,
            "--resume-id",
            "resume_accepted_001",
            "--retry-runtime-observation",
            "--runtime-output-root",
            r"C:\runtime-observation-retry",
            "--settings",
            "runtime.yaml",
            "--runtime-plugin-destination",
            r"C:\GTFO\BepInEx\plugins\BetterHitFeedback.dll",
        ]
    )

    assert exit_code == 0
    json.loads(capsys.readouterr().out)
    assert captured["recover_accepted_resume"] is False
    assert captured["retry_runtime_observation"] is True
    assert captured["runtime_output_root"] == (
        r"C:\runtime-observation-retry"
    )


def test_cli_stagger_edit_authority_preflight_passes_exact_inputs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def preflight(**kwargs):
        captured.update(kwargs)
        return {
            "status": "READY_TO_CREATE_EDIT_AUTHORITY_REQUEST",
            "proposal_hash": "sha256:" + ("a" * 64),
            "writes_performed": False,
            "registry_mutation_allowed": False,
            "repair_allowed": False,
        }

    monkeypatch.setattr(
        "src.mod_agent.cli.preflight_stagger_edit_authority",
        preflight,
    )
    target_symbol = (
        "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
        "TrySpawnStaggerYellowX"
    )

    exit_code = main(
        [
            "preflight-stagger-edit-authority",
            "--artifact-store-root",
            "shared-store",
            "--feature-id",
            "feature_001",
            "--run-id",
            "runtime_001",
            "--feature-spec-path",
            "feature-spec.json",
            "--feature-spec-hash",
            "1" * 64,
            "--runtime-evidence-path",
            "runtime-evidence.json",
            "--runtime-evidence-hash",
            "2" * 64,
            "--implementation-plan-path",
            "implementation-plan.json",
            "--implementation-plan-hash",
            "3" * 64,
            "--patch-proposal-path",
            "patch-proposal.json",
            "--patch-proposal-hash",
            "4" * 64,
            "--source-root",
            "source-root",
            "--canonical-target-path",
            "Patches/HitFeedbackBehaviorPatch.cs",
            "--target-symbol",
            target_symbol,
            "--target-start-line",
            "979",
            "--target-end-line",
            "984",
            "--proposed-operation",
            "replace_hud_recttransform_acquisition_and_null_guard_only",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "READY_TO_CREATE_EDIT_AUTHORITY_REQUEST"
    assert payload["writes_performed"] is False
    assert captured == {
        "artifact_store_root": "shared-store",
        "feature_id": "feature_001",
        "run_id": "runtime_001",
        "feature_spec_path": "feature-spec.json",
        "feature_spec_hash": "1" * 64,
        "runtime_evidence_path": "runtime-evidence.json",
        "runtime_evidence_hash": "2" * 64,
        "implementation_plan_path": "implementation-plan.json",
        "implementation_plan_hash": "3" * 64,
        "patch_proposal_path": "patch-proposal.json",
        "patch_proposal_hash": "4" * 64,
        "source_root": "source-root",
        "canonical_target_path": "Patches/HitFeedbackBehaviorPatch.cs",
        "target_symbol": target_symbol,
        "target_start_line": 979,
        "target_end_line": 984,
        "proposed_operation": (
            "replace_hud_recttransform_acquisition_and_null_guard_only"
        ),
    }


def test_cli_stagger_edit_authority_preflight_reports_blocked_without_writes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def blocked(**_: object):
        raise ValueError("exact Runtime lineage mismatch")

    monkeypatch.setattr(
        "src.mod_agent.cli.preflight_stagger_edit_authority",
        blocked,
    )

    exit_code = main(
        [
            "preflight-stagger-edit-authority",
            "--artifact-store-root",
            "shared-store",
            "--feature-id",
            "feature_001",
            "--run-id",
            "runtime_001",
            "--feature-spec-path",
            "feature-spec.json",
            "--feature-spec-hash",
            "1" * 64,
            "--runtime-evidence-path",
            "runtime-evidence.json",
            "--runtime-evidence-hash",
            "2" * 64,
            "--implementation-plan-path",
            "implementation-plan.json",
            "--implementation-plan-hash",
            "3" * 64,
            "--patch-proposal-path",
            "patch-proposal.json",
            "--patch-proposal-hash",
            "4" * 64,
            "--source-root",
            "source-root",
            "--canonical-target-path",
            "Patches/HitFeedbackBehaviorPatch.cs",
            "--target-symbol",
            (
                "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
                "TrySpawnStaggerYellowX"
            ),
            "--target-start-line",
            "979",
            "--target-end-line",
            "984",
            "--proposed-operation",
            "replace_hud_recttransform_acquisition_and_null_guard_only",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["status"] == "BLOCKED"
    assert payload["writes_performed"] is False
    assert payload["artifact_writes_performed"] is False
    assert payload["registry_mutation_allowed"] is False
    assert payload["repair_allowed"] is False


def test_cli_stagger_edit_authority_request_cannot_grant_authority(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def create_request(**kwargs):
        captured.update(kwargs)
        return {
            "status": "EDIT_AUTHORITY_REQUEST_CREATED",
            "request_hash": "sha256:" + ("a" * 64),
            "authority_granted": False,
            "registry_mutation_allowed": False,
            "repair_planner_invoked": False,
            "repair_allowed": False,
            "source_patch_allowed": False,
        }

    monkeypatch.setattr(
        "src.mod_agent.cli.create_stagger_edit_authority_request",
        create_request,
    )
    target_symbol = (
        "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
        "TrySpawnStaggerYellowX"
    )

    exit_code = main(
        [
            "request-stagger-edit-authority",
            "--artifact-store-root",
            "shared-store",
            "--feature-id",
            "feature_001",
            "--run-id",
            "runtime_001",
            "--feature-spec-path",
            "feature-spec.json",
            "--feature-spec-hash",
            "1" * 64,
            "--runtime-evidence-path",
            "runtime-evidence.json",
            "--runtime-evidence-hash",
            "2" * 64,
            "--implementation-plan-path",
            "implementation-plan.json",
            "--implementation-plan-hash",
            "3" * 64,
            "--patch-proposal-path",
            "patch-proposal.json",
            "--patch-proposal-hash",
            "4" * 64,
            "--source-root",
            "source-root",
            "--canonical-target-path",
            "Patches/HitFeedbackBehaviorPatch.cs",
            "--target-symbol",
            target_symbol,
            "--target-start-line",
            "979",
            "--target-end-line",
            "984",
            "--proposed-operation",
            "replace_hud_recttransform_acquisition_and_null_guard_only",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "EDIT_AUTHORITY_REQUEST_CREATED"
    assert payload["authority_granted"] is False
    assert payload["registry_mutation_allowed"] is False
    assert "approval_hash" not in captured
    assert "approved_by" not in captured
    assert captured["target_symbol"] == target_symbol
    assert captured["target_start_line"] == 979
    assert captured["target_end_line"] == 984


def test_cli_existing_binding_reauthorization_keeps_plan_roles_distinct(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def create_request(**kwargs):
        captured.update(kwargs)
        return {
            "status": (
                "EXISTING_BINDING_REAUTHORIZATION_REQUEST_CREATED"
            ),
            "request_hash": "sha256:" + ("a" * 64),
            "authority_granted": False,
            "registry_mutation_allowed": False,
            "repair_planner_invoked": False,
            "repair_allowed": False,
            "source_patch_allowed": False,
        }

    monkeypatch.setattr(
        "src.mod_agent.cli."
        "create_stagger_existing_binding_reauthorization_request",
        create_request,
    )
    exit_code = main(
        [
            "request-stagger-existing-binding-reauthorization",
            "--artifact-store-root",
            "shared-store",
            "--feature-id",
            "feature_001",
            "--run-id",
            "runtime_001",
            "--feature-spec-path",
            "feature-spec.json",
            "--feature-spec-hash",
            "1" * 64,
            "--runtime-evidence-path",
            "runtime-evidence.json",
            "--runtime-evidence-hash",
            "2" * 64,
            "--predecessor-implementation-plan-path",
            "predecessor-plan.json",
            "--predecessor-implementation-plan-hash",
            "3" * 64,
            "--patch-proposal-path",
            "patch-proposal.json",
            "--patch-proposal-hash",
            "4" * 64,
            "--current-implementation-plan-path",
            "current-plan.json",
            "--current-implementation-plan-hash",
            "8" * 64,
            "--existing-binding-resolution-path",
            "binding-resolution.json",
            "--existing-binding-resolution-hash",
            "9" * 64,
            "--source-root",
            "source-root",
            "--canonical-target-path",
            "Patches/HitFeedbackBehaviorPatch.cs",
            "--target-symbol",
            (
                "BetterHitFeedback.Patches.HitFeedbackBehaviorPatch."
                "TrySpawnStaggerYellowX"
            ),
            "--target-start-line",
            "979",
            "--target-end-line",
            "984",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["authority_granted"] is False
    assert captured["predecessor_implementation_plan_hash"] == "3" * 64
    assert captured["current_implementation_plan_hash"] == "8" * 64
    assert captured["existing_binding_resolution_hash"] == "9" * 64
    assert "approved_by" not in captured


def test_cli_stagger_observation_authority_preflight_passes_exact_roles(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def preflight(**kwargs):
        captured.update(kwargs)
        return {
            "status": (
                "READY_TO_CREATE_STAGGER_HUD_PARENT_OBSERVATION_"
                "AUTHORITY_REQUEST"
            ),
            "proposal_hash": "sha256:" + ("a" * 64),
            "writes_performed": False,
        }

    monkeypatch.setattr(
        "src.mod_agent.cli."
        "preflight_stagger_hud_parent_observation_authority",
        preflight,
    )
    exit_code = main(
        [
            "preflight-stagger-hud-parent-observation-authority",
            "--artifact-store-root",
            "shared-store",
            "--feature-id",
            "feature_001",
            "--run-id",
            "runtime_001",
            "--feature-spec-path",
            "feature-spec.json",
            "--feature-spec-hash",
            "1" * 64,
            "--runtime-evidence-path",
            "runtime-evidence.json",
            "--runtime-evidence-hash",
            "2" * 64,
            "--current-implementation-plan-path",
            "current-plan.json",
            "--current-implementation-plan-hash",
            "3" * 64,
            "--patch-proposal-path",
            "patch-proposal.json",
            "--patch-proposal-hash",
            "4" * 64,
            "--existing-binding-resolution-path",
            "binding-resolution.json",
            "--existing-binding-resolution-hash",
            "5" * 64,
            "--existing-edit-authority-approval-path",
            "edit-authority-approval.json",
            "--existing-edit-authority-approval-hash",
            "6" * 64,
            "--evidence-pack-path",
            "evidence-pack.json",
            "--evidence-pack-hash",
            "7" * 64,
            "--source-root",
            "source-root",
            "--build-dependency-root",
            "build-dependencies",
            "--unity-core-module-hash",
            "8" * 64,
            "--modules-asm-hash",
            "9" * 64,
            "--il2cpp-interop-runtime-hash",
            "a" * 64,
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["writes_performed"] is False
    assert captured["current_implementation_plan_hash"] == "3" * 64
    assert captured["existing_binding_resolution_hash"] == "5" * 64
    assert captured["existing_edit_authority_approval_hash"] == "6" * 64
    assert captured["evidence_pack_hash"] == "7" * 64
    assert captured["build_dependency_root"] == "build-dependencies"
    assert captured["unity_core_module_hash"] == "8" * 64
    assert captured["modules_asm_hash"] == "9" * 64
    assert captured["il2cpp_interop_runtime_hash"] == "a" * 64
    assert "approved_by" not in captured


def test_cli_stagger_diagnostic_plan_authorization_returns_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def resume_review(**kwargs):
        return _successful_edit_authority_cli_result(
            schema_version=(
                "stagger_hud_parent_diagnostic_execution_authority_request_v2"
            ),
            projection_kind=None,
        )

    monkeypatch.setattr(
        "src.mod_agent.cli.resume_stagger_edit_authority_review",
        resume_review,
    )
    exit_code = main(
        [
            "resume-stagger-edit-authority-review",
            "--artifact-store-root",
            "shared-store",
            "--feature-id",
            "feature_001",
            "--request-path",
            "request.json",
            "--request-artifact-hash",
            "b" * 64,
            "--authority-request-hash",
            "sha256:" + ("a" * 64),
            "--resume-id",
            "resume_001",
            "--decision",
            "approve",
            "--approved-by",
            "user",
            "--approved-at",
            "2026-07-30T12:00:00+08:00",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == (
        "STAGGER_HUD_PARENT_DIAGNOSTIC_PLAN_AUTHORIZED"
    )


def test_cli_bounded_edit_authority_success_uses_structured_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "src.mod_agent.cli.resume_stagger_edit_authority_review",
        lambda **_kwargs: _successful_edit_authority_cli_result(
            schema_version="stagger_edit_authority_request_v1",
            projection_kind="bounded_observation_only_plan_materialization",
        ),
    )

    exit_code = main(
        [
            "resume-stagger-edit-authority-review",
            "--artifact-store-root",
            "shared-store",
            "--feature-id",
            "feature_001",
            "--request-path",
            "request.json",
            "--request-artifact-hash",
            "b" * 64,
            "--authority-request-hash",
            "sha256:" + ("a" * 64),
            "--resume-id",
            "resume_001",
            "--decision",
            "approve",
            "--approved-by",
            "user",
            "--approved-at",
            "2026-07-30T12:00:00+08:00",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "STAGGER_BOUNDED_OBSERVATION_PLAN_AUTHORIZED"


@pytest.mark.parametrize("capability", EDIT_AUTHORITY_CAPABILITIES)
def test_cli_edit_authority_calls_real_public_structured_result_path(
    capability,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    feature_id = "feature_001"
    request_hash = "sha256:" + ("a" * 64)
    public_result = _successful_edit_authority_cli_result(
        schema_version=capability.schema_version,
        projection_kind=capability.projection_kind,
        feature_id=feature_id,
        request_hash=request_hash,
    )

    class ReadOnlyAuditStore:
        def list_feature_artifact_revisions(
            self,
            _feature_id: str,
            _artifact_type: str,
        ) -> list[ArtifactRef]:
            return []

    admission = local_entry_module._EditAuthorityReviewAdmission(
        store=ReadOnlyAuditStore(),
        request_ref=ArtifactRef(
            feature_id=feature_id,
            artifact_type="edit_authority_request",
            path=str(tmp_path / "request.json"),
            artifact_hash="b" * 64,
        ),
        request={},
        request_envelope={},
        run_id="run_cli_public_edit_authority",
        capability=capability,
        identity_sections={
            "identity_mode": "versioned_v1",
            "identity_schema_version": "edit_authority_approval_identity_v1",
            "approval_identity": {"schema_version": "test_identity_v1"},
            "execution_contract_summary": {
                "capability_id": capability.capability_id,
            },
        },
    )

    class CompletedGraph:
        def invoke(self, *_args, **_kwargs):
            return {
                "edit_authority_review_result": public_result[
                    "edit_authority_review_result"
                ],
                "current_stage": capability.terminal_stage,
                "artifacts": {},
                "artifact_hashes": {},
                "blockers": [],
            }

    monkeypatch.setattr(
        local_entry_module,
        "_admit_stagger_edit_authority_review",
        lambda **_kwargs: admission,
    )
    monkeypatch.setattr(
        local_entry_module,
        "_invoke_stagger_edit_authority_interrupt",
        lambda **_kwargs: (CompletedGraph(), ["request.json"], {}, {}),
    )

    exit_code = main(
        [
            "resume-stagger-edit-authority-review",
            "--artifact-store-root",
            str(tmp_path / "artifacts"),
            "--feature-id",
            feature_id,
            "--request-path",
            str(tmp_path / "request.json"),
            "--request-artifact-hash",
            "b" * 64,
            "--authority-request-hash",
            request_hash,
            "--resume-id",
            "resume_cli_public_edit_authority",
            "--decision",
            "approve",
            "--approved-by",
            "user",
            "--approved-at",
            "2026-08-06T13:00:00+08:00",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == capability.public_success_status
    assert payload["edit_authority_review_result"] == public_result[
        "edit_authority_review_result"
    ]


def test_cli_edit_authority_presentation_failure_preserves_machine_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    feature_id = "feature_001"
    request_hash = "sha256:" + ("a" * 64)
    capability = resolve_edit_authority_capability(
        schema_version="stagger_edit_authority_request_v1",
        projection_kind=None,
    )
    public_result = _successful_edit_authority_cli_result(
        schema_version=capability.schema_version,
        projection_kind=capability.projection_kind,
        feature_id=feature_id,
        request_hash=request_hash,
    )

    class AuditFailureStore:
        calls = 0

        def list_feature_artifact_revisions(
            self,
            _feature_id: str,
            _artifact_type: str,
        ) -> list[ArtifactRef]:
            self.calls += 1
            if self.calls > len(capability.review_write_artifact_types):
                raise OSError("injected post-result audit failure")
            return []

    admission = local_entry_module._EditAuthorityReviewAdmission(
        store=AuditFailureStore(),
        request_ref=ArtifactRef(
            feature_id=feature_id,
            artifact_type="edit_authority_request",
            path=str(tmp_path / "request.json"),
            artifact_hash="b" * 64,
        ),
        request={},
        request_envelope={},
        run_id="run_cli_presentation_failure",
        capability=capability,
        identity_sections={
            "identity_mode": "versioned_v1",
            "identity_schema_version": "edit_authority_approval_identity_v1",
            "approval_identity": {"schema_version": "test_identity_v1"},
            "execution_contract_summary": {
                "capability_id": capability.capability_id,
            },
        },
    )

    class CompletedGraph:
        def invoke(self, *_args, **_kwargs):
            return {
                "edit_authority_review_result": public_result[
                    "edit_authority_review_result"
                ],
                "current_stage": capability.terminal_stage,
                "artifacts": {},
                "artifact_hashes": {},
                "blockers": [],
            }

    monkeypatch.setattr(
        local_entry_module,
        "_admit_stagger_edit_authority_review",
        lambda **_kwargs: admission,
    )
    monkeypatch.setattr(
        local_entry_module,
        "_invoke_stagger_edit_authority_interrupt",
        lambda **_kwargs: (CompletedGraph(), ["request.json"], {}, {}),
    )

    exit_code = main(
        [
            "resume-stagger-edit-authority-review",
            "--artifact-store-root",
            str(tmp_path / "artifacts"),
            "--feature-id",
            feature_id,
            "--request-path",
            str(tmp_path / "request.json"),
            "--request-artifact-hash",
            "b" * 64,
            "--authority-request-hash",
            request_hash,
            "--resume-id",
            "resume_cli_presentation_failure",
            "--decision",
            "approve",
            "--approved-by",
            "user",
            "--approved-at",
            "2026-08-06T13:00:00+08:00",
        ]
    )

    raw_output = capsys.readouterr().out
    payload = json.loads(raw_output)
    assert exit_code == 2
    assert set(payload) == {
        "result_type",
        "status",
        "command",
        "reason",
        "edit_authority_review_result",
        "presentation_error",
        "audit_error",
    }
    assert payload["result_type"] == "edit_authority_presentation_error_v1"
    assert payload["status"] == "PRESENTATION_FAILED"
    assert payload["command"] == "resume-stagger-edit-authority-review"
    assert payload["reason"] == (
        "Edit Authority audit projection failed after machine result."
    )
    assert payload["edit_authority_review_result"] == public_result[
        "edit_authority_review_result"
    ]
    assert (
        payload["edit_authority_review_result"]["platform_status"]
        == "completed"
    )
    assert payload["presentation_error"] == {
        "error_class": "OSError",
        "error_message": "injected post-result audit failure",
    }
    assert payload["audit_error"] == payload["presentation_error"]
    assert "BLOCKED" not in raw_output


def test_cli_edit_authority_generic_local_entry_error_shape_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_review(**_kwargs):
        raise LocalEntryError("injected generic edit authority failure")

    monkeypatch.setattr(
        "src.mod_agent.cli.resume_stagger_edit_authority_review",
        fail_review,
    )
    exit_code = main(
        [
            "resume-stagger-edit-authority-review",
            "--artifact-store-root",
            "shared-store",
            "--feature-id",
            "feature_001",
            "--request-path",
            "request.json",
            "--request-artifact-hash",
            "b" * 64,
            "--authority-request-hash",
            "sha256:" + ("a" * 64),
            "--resume-id",
            "resume_generic_error",
            "--decision",
            "approve",
            "--approved-by",
            "user",
            "--approved-at",
            "2026-08-06T13:00:00+08:00",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload == {
        "status": "BLOCKED",
        "command": "resume-stagger-edit-authority-review",
        "reason": "injected generic edit authority failure",
        "artifact_store_inspection_required": True,
        "repair_planner_invoked": False,
        "source_patch_allowed": False,
        "source_modified": False,
        "build_performed": False,
        "process_launched": False,
    }


@pytest.mark.parametrize("scenario", ("rejected", "blocked", "partial"))
def test_cli_edit_authority_nonapproved_results_fail_closed(
    scenario: str,
) -> None:
    assert _edit_authority_review_exit_code(
        _nonapproved_edit_authority_cli_result(scenario)
    ) == 2


def test_cli_stagger_diagnostic_exact_diff_passes_exact_roles(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def preflight(**kwargs):
        captured.update(kwargs)
        return {
            "status": (
                "READY_FOR_STAGGER_HUD_PARENT_DIAGNOSTIC_DIFF_APPROVAL"
            ),
            "diff_hash": "sha256:" + ("a" * 64),
            "unified_diff": "--- a/source\n+++ b/source\n",
            "writes_performed": False,
            "artifact_writes_performed": False,
        }

    monkeypatch.setattr(
        "src.mod_agent.cli."
        "preflight_stagger_hud_parent_diagnostic_exact_diff",
        preflight,
    )
    exit_code = main(
        [
            "preflight-stagger-hud-parent-diagnostic-exact-diff",
            "--artifact-store-root",
            "shared-store",
            "--feature-id",
            "feature_001",
            "--run-id",
            "runtime_001",
            "--edit-authority-approval-path",
            "approval.json",
            "--edit-authority-approval-hash",
            "1" * 64,
            "--evidence-pack-path",
            "evidence.json",
            "--evidence-pack-hash",
            "2" * 64,
            "--implementation-plan-path",
            "plan.json",
            "--implementation-plan-hash",
            "3" * 64,
            "--source-root",
            "source-root",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["writes_performed"] is False
    assert captured == {
        "artifact_store_root": "shared-store",
        "feature_id": "feature_001",
        "run_id": "runtime_001",
        "edit_authority_approval_path": "approval.json",
        "edit_authority_approval_hash": "1" * 64,
        "evidence_pack_path": "evidence.json",
        "evidence_pack_hash": "2" * 64,
        "implementation_plan_path": "plan.json",
        "implementation_plan_hash": "3" * 64,
        "source_root": "source-root",
    }


def test_cli_stagger_edit_authority_review_delegates_to_graph_entry(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def resume_review(**kwargs):
        captured.update(kwargs)
        return _successful_edit_authority_cli_result(
            schema_version="stagger_edit_authority_request_v1",
            projection_kind=None,
        )

    monkeypatch.setattr(
        "src.mod_agent.cli.resume_stagger_edit_authority_review",
        resume_review,
    )
    request_hash = "sha256:" + ("a" * 64)

    exit_code = main(
        [
            "resume-stagger-edit-authority-review",
            "--artifact-store-root",
            "shared-store",
            "--feature-id",
            "feature_001",
            "--request-path",
            "request.json",
            "--request-artifact-hash",
            "b" * 64,
            "--authority-request-hash",
            request_hash,
            "--resume-id",
            "resume_001",
            "--decision",
            "approve",
            "--approved-by",
            "user",
            "--approved-at",
            "2026-07-30T12:00:00+08:00",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "EXACT_EDIT_AUTHORITY_RESOLVED"
    assert captured == {
        "artifact_store_root": "shared-store",
        "feature_id": "feature_001",
        "edit_authority_request_path": "request.json",
        "edit_authority_request_hash": "b" * 64,
        "authority_request_hash": request_hash,
        "resume_id": "resume_001",
        "decision": "approve",
        "approved_by": "user",
        "approved_at": "2026-07-30T12:00:00+08:00",
    }


def test_cli_stagger_edit_authority_review_preflight_is_no_write(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def preflight_review(**kwargs):
        captured.update(kwargs)
        return {
            "status": "READY_FOR_EDIT_AUTHORITY_REVIEW_EXECUTION",
            "request_hash": kwargs["authority_request_hash"],
            "checkpoint_artifact_refs": [kwargs["edit_authority_request_path"]],
            "writes_performed": False,
            "artifact_writes_performed": False,
        }

    monkeypatch.setattr(
        "src.mod_agent.cli.preflight_stagger_edit_authority_review",
        preflight_review,
    )
    request_hash = "sha256:" + ("a" * 64)

    exit_code = main(
        [
            "preflight-stagger-edit-authority-review",
            "--artifact-store-root",
            "shared-store",
            "--feature-id",
            "feature_001",
            "--request-path",
            "request.json",
            "--request-artifact-hash",
            "b" * 64,
            "--authority-request-hash",
            request_hash,
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == (
        "READY_FOR_EDIT_AUTHORITY_REVIEW_EXECUTION"
    )
    assert payload["writes_performed"] is False
    assert captured == {
        "artifact_store_root": "shared-store",
        "feature_id": "feature_001",
        "edit_authority_request_path": "request.json",
        "edit_authority_request_hash": "b" * 64,
        "authority_request_hash": request_hash,
    }


def test_cli_has_no_direct_stagger_edit_authority_approval_command() -> None:
    with pytest.raises(SystemExit):
        main(["approve-stagger-edit-authority"])


def test_cli_displays_exact_structured_human_semantic_decision_contract(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    binding = {
        "schema_version": "human_semantic_decision_v1",
        "feature_id": "feature_001",
        "feature_spec_artifact_hash": "sha256:feature",
        "proposal_id": "proposal_001",
        "proposal_payload_sha256": "sha256:proposal",
        "proposal_review_payload_sha256": "sha256:review",
        "semantic_assurance_payload_sha256": "sha256:assurance",
        "diff_hash": "sha256:diff",
    }
    decision_line = json.dumps(
        {
            **binding,
            "decision": "approve",
            "reviewer_identity": "human:cli-test",
        }
    ) + "\n"
    monkeypatch.setattr(
        "src.mod_agent.cli.sys.stdin",
        SimpleNamespace(readline=lambda: decision_line),
    )

    observed = _read_exact_diff_approval_from_stdin(
        {
            "diff_hash": "sha256:diff",
            "human_semantic_review_required": True,
            "human_semantic_decision_binding": binding,
        }
    )

    stderr = capsys.readouterr().err
    assert observed == decision_line.strip()
    assert '"human_semantic_decision_v1"' in stderr
    assert '"feature_spec_artifact_hash": "sha256:feature"' in stderr
    assert '"proposal_payload_sha256": "sha256:proposal"' in stderr
    assert '"semantic_assurance_payload_sha256": "sha256:assurance"' in stderr
    assert "Exact diff human semantic decision JSON:" in stderr
