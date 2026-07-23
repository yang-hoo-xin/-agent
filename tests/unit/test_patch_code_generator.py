from __future__ import annotations

import json

import pytest

from src.libs.llm import BaseLLM, ChatResponse, Message
from src.mod_agent.proposal import LLMExactPatchGenerator, PatchGenerationError


class _FakeLLM(BaseLLM):
    def __init__(self, content: str) -> None:
        self.content = content

    def chat(self, messages: list[Message], trace=None, **kwargs) -> ChatResponse:
        self.validate_messages(messages)
        return ChatResponse(content=self.content, model="fake-codegen")


class _RecordingLLM(BaseLLM):
    def __init__(self, content: str) -> None:
        self.content = content
        self.messages: list[Message] = []
        self.kwargs: dict[str, object] = {}

    def chat(self, messages: list[Message], trace=None, **kwargs) -> ChatResponse:
        self.validate_messages(messages)
        self.messages = messages
        self.kwargs = kwargs
        recorder = kwargs.get("provider_request_recorder")
        if callable(recorder):
            recorder({"body_sha256": "bound", "body_utf8": "{}"})
        return ChatResponse(
            content=self.content,
            model="fake-codegen",
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            raw_response={"done": True, "done_reason": "stop"},
        )


def _registry() -> dict[str, object]:
    return {
        "edit_bindings": [
            {
                "binding_id": "edit_binding_001",
                "canonical_target_path": "Patches/HitFeedbackBehaviorPatch.cs",
            }
        ]
    }


def _verified_boolean_access(
    *,
    receiver_name: str = "ConfigEnabled",
    receiver_type: str = "ConfigEntry<bool>",
    member_name: str = "Value",
) -> dict[str, object]:
    compiled_receiver_type = "Shared.SettingBox`1<System.Boolean>"
    return {
        "edit_binding_id": "edit_binding_001",
        "source_receiver": {
            "evidence_id": "ev_load",
            "source_path": "generated_mods/Example/Plugin.cs",
            "source_hash": "source_hash_001",
            "declaring_type": "Example.Plugin",
            "member_name": receiver_name,
            "member_kind": "property",
            "declaration_span": {"start_line": 5, "end_line": 5},
            "declared_type": receiver_type,
            "receiver_closed_type": compiled_receiver_type,
        },
        "consumer": {
            "declaring_type": "Example.Plugin",
            "receiver_member": receiver_name,
            "member_kind": "property",
            "is_static": True,
            "receiver_closed_type": compiled_receiver_type,
        },
        "type_reference": {
            "symbol": "Shared.SettingBox`1",
        },
        "member_access": {
            "declaring_type": "Shared.SettingBox`1",
            "member_name": member_name,
            "member_kind": "property",
            "access_kind": "instance_property_get",
            "closed_result_type": "System.Boolean",
        },
    }


def _verified_binding_context(
    *,
    receiver_name: str,
    receiver_type: str,
    facts: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "binding_id": "edit_binding_001",
        "evidence_id": "ev_load",
        "source_hash": "source_hash_001",
        "canonical_target_path": "generated_mods/Example/Plugin.cs",
        "declaring_type_full_name": "Example.Plugin",
        "method_name": "Load",
        "return_type": "void",
        "declared_member_types": {receiver_name: receiver_type},
        "declared_members": {
            receiver_name: {
                "member_name": receiver_name,
                "member_kind": "property",
                "declared_type": receiver_type,
                "declaring_type": "Example.Plugin",
                "declaration_span": {"start_line": 5, "end_line": 5},
                "is_static": True,
            }
        },
        "verified_member_accesses": facts,
    }


def test_generator_accepts_strict_binding_only_exact_replacement() -> None:
    payload = {
        "changes": [
            {
                "change_id": "change_kill_color",
                "edit_binding_id": "edit_binding_001",
                "rationale": "Change only the kill color constant.",
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "KillMarkerColor = red;",
                    "after_text": "KillMarkerColor = pink;",
                    "expected_occurrences": 1,
                },
            }
        ]
    }
    generated = LLMExactPatchGenerator(_FakeLLM(json.dumps(payload))).generate(
        user_request="Make the kill marker pink.",
        evidence_items=[{"excerpt": "KillMarkerColor = red;"}],
        binding_registry=_registry(),
        constraints=["Do not change normal hits."],
    )

    assert generated.model == "fake-codegen"
    assert generated.changes[0]["edit_binding_id"] == "edit_binding_001"
    assert generated.changes[0]["patch"]["after_text"] == "KillMarkerColor = pink;"


def test_generator_rejects_model_selected_path() -> None:
    payload = {
        "changes": [
            {
                "edit_binding_id": "edit_binding_001",
                "target_file": "invented.cs",
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "old",
                    "after_text": "new",
                    "expected_occurrences": 1,
                },
            }
        ]
    }
    with pytest.raises(PatchGenerationError, match="must not copy or invent a path"):
        LLMExactPatchGenerator(_FakeLLM(json.dumps(payload))).generate(
            user_request="change it",
            evidence_items=[{"excerpt": "old"}],
            binding_registry=_registry(),
            constraints=[],
        )


def test_generator_rejects_before_text_with_normalized_line_endings() -> None:
    payload = {
        "changes": [
            {
                "edit_binding_id": "edit_binding_001",
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "first\nsecond",
                    "after_text": "first\nchanged",
                    "expected_occurrences": 1,
                },
            }
        ]
    }

    with pytest.raises(PatchGenerationError) as exc_info:
        LLMExactPatchGenerator(_FakeLLM(json.dumps(payload))).generate(
            user_request="change it",
            evidence_items=[{"excerpt": "first\r\nsecond"}],
            binding_registry=_registry(),
            constraints=[],
        )

    assert "not verbatim current evidence" in str(exc_info.value)
    assert exc_info.value.diagnostics["failure_classification"] == (
        "before_text_not_verbatim_evidence"
    )


def test_generator_accepts_crlf_before_text_from_current_evidence() -> None:
    payload = {
        "changes": [
            {
                "edit_binding_id": "edit_binding_001",
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "first\r\nsecond",
                    "after_text": "first\r\nchanged",
                    "expected_occurrences": 1,
                },
            }
        ]
    }

    generated = LLMExactPatchGenerator(_FakeLLM(json.dumps(payload))).generate(
        user_request="change it",
        evidence_items=[{"excerpt": "first\r\nsecond"}],
        binding_registry=_registry(),
        constraints=[],
    )

    assert generated.changes[0]["patch"]["before_text"] == "first\r\nsecond"


def test_generator_rejects_missing_declared_literal_validation_marker() -> None:
    payload = {
        "changes": [
            {
                "edit_binding_id": "edit_binding_001",
                "expected_validation": ["MOD_DISABLED", "dotnet build"],
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "old",
                    "after_text": "new",
                    "expected_occurrences": 1,
                },
            }
        ]
    }

    with pytest.raises(PatchGenerationError) as exc_info:
        LLMExactPatchGenerator(_FakeLLM(json.dumps(payload))).generate(
            user_request="emit MOD_DISABLED",
            evidence_items=[{"excerpt": "old"}],
            binding_registry=_registry(),
            constraints=[],
        )

    assert exc_info.value.diagnostics["failure_classification"] == (
        "declared_validation_marker_missing"
    )
    assert exc_info.value.diagnostics["missing_validation_markers"] == [
        "MOD_DISABLED"
    ]


def test_generator_rejects_return_value_from_bound_csharp_void_method() -> None:
    payload = {
        "changes": [
            {
                "edit_binding_id": "edit_binding_001",
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "ConfigEnabled = true;",
                    "after_text": "if (!ConfigEnabled) { return false; }",
                    "expected_occurrences": 1,
                },
            }
        ]
    }
    evidence = {
        "evidence_id": "ev_load",
        "source_path": "generated_mods/Example/Plugin.cs",
        "method_name": "Load",
        "return_type": "void",
        "excerpt": "public override void Load() { ConfigEnabled = true; }",
    }
    registry = {
        "edit_bindings": [
            {
                "binding_id": "edit_binding_001",
                "evidence_id": "ev_load",
                "canonical_target_path": "generated_mods/Example/Plugin.cs",
                "method_name": "Load",
                "return_type": "void",
            }
        ]
    }

    with pytest.raises(PatchGenerationError) as exc_info:
        LLMExactPatchGenerator(_FakeLLM(json.dumps(payload))).generate(
            user_request="disable startup",
            evidence_items=[evidence],
            binding_registry=registry,
            constraints=[],
        )

    assert exc_info.value.diagnostics["failure_classification"] == (
        "csharp_return_value_in_void_method"
    )
    assert exc_info.value.diagnostics["method_name"] == "Load"
    assert exc_info.value.diagnostics["return_type"] == "void"


def test_generator_allows_bare_return_and_ignores_return_text_in_csharp_strings() -> None:
    payload = {
        "changes": [
            {
                "edit_binding_id": "edit_binding_001",
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "ConfigEnabled = true;",
                    "after_text": (
                        'LogInfo("return false;"); // return false;\n'
                        "if (!ConfigEnabled) { return; }"
                    ),
                    "expected_occurrences": 1,
                },
            }
        ]
    }
    evidence = {
        "evidence_id": "ev_load",
        "source_path": "generated_mods/Example/Plugin.cs",
        "method_name": "Load",
        "return_type": "void",
        "excerpt": "public override void Load() { ConfigEnabled = true; }",
    }
    registry = {
        "edit_bindings": [
            {
                "binding_id": "edit_binding_001",
                "evidence_id": "ev_load",
                "canonical_target_path": "generated_mods/Example/Plugin.cs",
                "method_name": "Load",
                "return_type": "void",
            }
        ]
    }

    generated = LLMExactPatchGenerator(_FakeLLM(json.dumps(payload))).generate(
        user_request="disable startup",
        evidence_items=[evidence],
        binding_registry=registry,
        constraints=[],
    )

    assert "return;" in generated.changes[0]["patch"]["after_text"]


def test_generator_rejects_unary_not_for_bound_non_boolean_csharp_member() -> None:
    payload = {
        "changes": [
            {
                "edit_binding_id": "edit_binding_001",
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "ConfigEnabled = Config.Bind();",
                    "after_text": (
                        "ConfigEnabled = Config.Bind();\n"
                        "if (!ConfigEnabled) { return; }"
                    ),
                    "expected_occurrences": 1,
                },
            }
        ]
    }
    evidence = {
        "evidence_id": "ev_load",
        "source_path": "generated_mods/Example/Plugin.cs",
        "method_name": "Load",
        "return_type": "void",
        "declared_member_types": {"ConfigEnabled": "ConfigEntry<bool>"},
        "excerpt": "public override void Load() { ConfigEnabled = Config.Bind(); }",
    }
    registry = {
        "edit_bindings": [
            {
                "binding_id": "edit_binding_001",
                "evidence_id": "ev_load",
                "canonical_target_path": "generated_mods/Example/Plugin.cs",
                "method_name": "Load",
                "return_type": "void",
                "declared_member_types": {"ConfigEnabled": "ConfigEntry<bool>"},
            }
        ]
    }

    with pytest.raises(PatchGenerationError) as exc_info:
        LLMExactPatchGenerator(_FakeLLM(json.dumps(payload))).generate(
            user_request="disable startup",
            evidence_items=[evidence],
            binding_registry=registry,
            constraints=[],
        )

    assert exc_info.value.diagnostics == {
        "failure_boundary": "deterministic_patch_validation",
        "response_model": "fake-codegen",
        "done": None,
        "done_reason": None,
        "usage": None,
        "failure_classification": "csharp_boolean_operator_operand_type_mismatch",
        "binding_id": "edit_binding_001",
        "method_name": "Load",
        "operator": "!",
        "member_name": "ConfigEnabled",
        "declared_type": "ConfigEntry<bool>",
    }


@pytest.mark.parametrize(
    ("declared_type", "condition"),
    [
        ("bool", "!PrimitiveEnabled"),
        ("System.Boolean", "!PrimitiveEnabled"),
        ("ConfigEntry<bool>", "!ConfigEnabled.Value"),
    ],
)
def test_generator_does_not_reject_supported_or_member_access_boolean_operands(
    declared_type: str,
    condition: str,
) -> None:
    member_name = "ConfigEnabled" if "." in condition else "PrimitiveEnabled"
    payload = {
        "changes": [
            {
                "edit_binding_id": "edit_binding_001",
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "Bind();",
                    "after_text": f"Bind();\nif ({condition}) {{ return; }}",
                    "expected_occurrences": 1,
                },
            }
        ]
    }
    evidence = {
        "evidence_id": "ev_load",
        "excerpt": "public override void Load() { Bind(); }",
    }
    registry = {
        "edit_bindings": [
            _verified_binding_context(
                receiver_name=member_name,
                receiver_type=declared_type,
                facts=(
                    [_verified_boolean_access()]
                    if "." in condition
                    else []
                ),
            )
        ]
    }

    generated = LLMExactPatchGenerator(_FakeLLM(json.dumps(payload))).generate(
        user_request="disable startup",
        evidence_items=[evidence],
        binding_registry=registry,
        constraints=[],
    )

    assert condition in generated.changes[0]["patch"]["after_text"]


def test_generator_rejects_unverified_member_access_boolean_operand() -> None:
    payload = {
        "changes": [
            {
                "edit_binding_id": "edit_binding_001",
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "Bind();",
                    "after_text": "Bind();\nif (!SettingsHandle.IsReady) { return; }",
                    "expected_occurrences": 1,
                },
            }
        ]
    }
    registry = {
        "edit_bindings": [
            {
                "binding_id": "edit_binding_001",
                "canonical_target_path": "generated_mods/Example/Plugin.cs",
                "method_name": "Load",
                "return_type": "void",
                "declared_member_types": {
                    "SettingsHandle": "SettingBox<bool>",
                },
                "verified_member_accesses": [],
            }
        ]
    }

    with pytest.raises(PatchGenerationError) as exc_info:
        LLMExactPatchGenerator(_FakeLLM(json.dumps(payload))).generate(
            user_request="disable startup",
            evidence_items=[{"excerpt": "public void Load() { Bind(); }"}],
            binding_registry=registry,
            constraints=[],
        )

    assert exc_info.value.diagnostics["failure_classification"] == (
        "csharp_unverified_boolean_member_operand"
    )


def test_generator_rejects_member_fact_with_wrong_source_hash() -> None:
    payload = {
        "changes": [
            {
                "edit_binding_id": "edit_binding_001",
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "Bind();",
                    "after_text": (
                        "Bind();\nif (!SettingsHandle.IsReady) { return; }"
                    ),
                    "expected_occurrences": 1,
                },
            }
        ]
    }
    fact = _verified_boolean_access(
        receiver_name="SettingsHandle",
        receiver_type="SettingBox<bool>",
        member_name="IsReady",
    )
    fact["source_receiver"]["source_hash"] = "different_source_hash"
    registry = {
        "edit_bindings": [
            _verified_binding_context(
                receiver_name="SettingsHandle",
                receiver_type="SettingBox<bool>",
                facts=[fact],
            )
        ]
    }

    with pytest.raises(PatchGenerationError) as exc_info:
        LLMExactPatchGenerator(_FakeLLM(json.dumps(payload))).generate(
            user_request="disable startup",
            evidence_items=[{"excerpt": "public void Load() { Bind(); }"}],
            binding_registry=registry,
            constraints=[],
        )

    assert exc_info.value.diagnostics["failure_classification"] == (
        "csharp_unverified_boolean_member_operand"
    )


def test_generator_rejects_shadowing_of_bound_receiver() -> None:
    payload = {
        "changes": [
            {
                "edit_binding_id": "edit_binding_001",
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "Bind();",
                    "after_text": (
                        "Bind();\n"
                        "var SettingsHandle = Other();\n"
                        "if (!SettingsHandle.IsReady) { return; }"
                    ),
                    "expected_occurrences": 1,
                },
            }
        ]
    }
    registry = {
        "edit_bindings": [
            _verified_binding_context(
                receiver_name="SettingsHandle",
                receiver_type="SettingBox<bool>",
                facts=[
                    _verified_boolean_access(
                        receiver_name="SettingsHandle",
                        receiver_type="SettingBox<bool>",
                        member_name="IsReady",
                    )
                ],
            )
        ]
    }

    with pytest.raises(PatchGenerationError) as exc_info:
        LLMExactPatchGenerator(_FakeLLM(json.dumps(payload))).generate(
            user_request="disable startup",
            evidence_items=[{"excerpt": "public void Load() { Bind(); }"}],
            binding_registry=registry,
            constraints=[],
        )

    assert exc_info.value.diagnostics["failure_classification"] == (
        "csharp_bound_member_shadowed"
    )


def test_generator_ignores_shadowing_text_inside_csharp_comment() -> None:
    payload = {
        "changes": [
            {
                "edit_binding_id": "edit_binding_001",
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "Bind();",
                    "after_text": (
                        "Bind();\n"
                        "// var SettingsHandle = Other();\n"
                        "if (!SettingsHandle.IsReady) { return; }"
                    ),
                    "expected_occurrences": 1,
                },
            }
        ]
    }
    registry = {
        "edit_bindings": [
            _verified_binding_context(
                receiver_name="SettingsHandle",
                receiver_type="SettingBox<bool>",
                facts=[
                    _verified_boolean_access(
                        receiver_name="SettingsHandle",
                        receiver_type="SettingBox<bool>",
                        member_name="IsReady",
                    )
                ],
            )
        ]
    }

    generated = LLMExactPatchGenerator(_FakeLLM(json.dumps(payload))).generate(
        user_request="disable startup",
        evidence_items=[{"excerpt": "public void Load() { Bind(); }"}],
        binding_registry=registry,
        constraints=[],
    )

    assert "if (!SettingsHandle.IsReady)" in (
        generated.changes[0]["patch"]["after_text"]
    )


def test_generator_carries_verified_member_access_in_binding_context() -> None:
    payload = {
        "changes": [
            {
                "edit_binding_id": "edit_binding_001",
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "Bind();",
                    "after_text": "Bind();\nif (!SettingsHandle.IsReady) { return; }",
                    "expected_occurrences": 1,
                },
            }
        ]
    }
    fact = _verified_boolean_access(
        receiver_name="SettingsHandle",
        receiver_type="SettingBox<bool>",
        member_name="IsReady",
    )
    registry = {
        "edit_bindings": [
            _verified_binding_context(
                receiver_name="SettingsHandle",
                receiver_type="SettingBox<bool>",
                facts=[fact],
            )
        ]
    }
    llm = _RecordingLLM(json.dumps(payload))

    LLMExactPatchGenerator(llm).generate(
        user_request="disable startup",
        evidence_items=[{"excerpt": "public void Load() { Bind(); }"}],
        binding_registry=registry,
        constraints=[],
    )

    prompt_payload = json.loads(llm.messages[1].content)
    assert prompt_payload["edit_binding_contexts"]["edit_binding_001"][
        "verified_member_accesses"
    ] == [fact]


def test_generator_rejects_omitted_upstream_validation_requirement() -> None:
    payload = {
        "changes": [
            {
                "edit_binding_id": "edit_binding_001",
                "expected_validation": ["compile"],
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "old",
                    "after_text": "new",
                    "expected_occurrences": 1,
                },
            }
        ]
    }

    with pytest.raises(PatchGenerationError) as exc_info:
        LLMExactPatchGenerator(_FakeLLM(json.dumps(payload))).generate(
            user_request="change it",
            evidence_items=[{"excerpt": "old"}],
            binding_registry=_registry(),
            constraints=[],
            required_validation_by_binding={
                "edit_binding_001": ["compile", "runtime marker observed"]
            },
        )

    assert exc_info.value.diagnostics["failure_classification"] == (
        "upstream_validation_omitted"
    )
    assert exc_info.value.diagnostics["missing_upstream_validation"] == [
        "runtime marker observed"
    ]


def test_generator_carries_required_validation_contract_in_prompt() -> None:
    payload = {
        "changes": [
            {
                "change_id": "change_001",
                "change_type": "modify_behavior",
                "edit_binding_id": "edit_binding_001",
                "operation": "exact_text_replace",
                "rationale": "bounded",
                "expected_validation": ["compile", "runtime marker observed"],
                "rollback_hint": "restore",
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "old",
                    "after_text": "new",
                    "expected_occurrences": 1,
                },
            }
        ]
    }
    llm = _RecordingLLM(json.dumps(payload))

    generated = LLMExactPatchGenerator(llm).generate(
        user_request="change it",
        evidence_items=[{"excerpt": "old"}],
        binding_registry=_registry(),
        constraints=[],
        required_validation_by_binding={
            "edit_binding_001": ["compile", "runtime marker observed"]
        },
    )

    prompt_payload = json.loads(llm.messages[1].content)
    assert prompt_payload["required_validation_by_binding"] == {
        "edit_binding_001": ["compile", "runtime marker observed"]
    }
    assert generated.changes[0]["expected_validation"] == [
        "compile",
        "runtime marker observed",
    ]


def test_native_schema_in_prompt_and_provider_format_share_one_object() -> None:
    payload = {
        "changes": [
            {
                "change_id": "change_001",
                "change_type": "modify_behavior",
                "edit_binding_id": "edit_binding_001",
                "operation": "exact_text_replace",
                "rationale": "bounded",
                "expected_validation": ["dotnet build"],
                "rollback_hint": "restore",
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "old",
                    "after_text": "new",
                    "expected_occurrences": 1,
                },
            }
        ]
    }
    llm = _RecordingLLM(json.dumps(payload))
    recorded_requests = []
    post_admission_calls = []

    generated = LLMExactPatchGenerator(llm).generate(
        user_request="change it",
        evidence_items=[{"excerpt": "old"}],
        binding_registry=_registry(),
        constraints=[],
        require_native_schema=True,
        provider_request_recorder=recorded_requests.append,
        post_response_admission=post_admission_calls.append,
    )

    prompt_payload = json.loads(llm.messages[1].content)
    assert llm.kwargs["response_format"] == prompt_payload["required_output_schema"]
    assert llm.kwargs["response_format"]["properties"]["changes"]["items"][
        "properties"
    ]["edit_binding_id"]["enum"] == ["edit_binding_001"]
    assert recorded_requests == [{"body_sha256": "bound", "body_utf8": "{}"}]
    assert len(post_admission_calls) == 1
    assert generated.changes[0]["patch"]["after_text"] == "new"


def test_malformed_patch_json_preserves_diagnostics_without_repairing_content() -> None:
    content = '{"changes":[{"patch":}'
    llm = _RecordingLLM(content)

    with pytest.raises(PatchGenerationError) as exc_info:
        LLMExactPatchGenerator(llm).generate(
            user_request="change it",
            evidence_items=[{"excerpt": "old"}],
            binding_registry=_registry(),
            constraints=[],
        )

    assert exc_info.value.diagnostic_content == content
    assert exc_info.value.diagnostics["failure_classification"] == (
        "malformed_structured_output"
    )
    assert exc_info.value.diagnostics["failure_boundary"] == (
        "deterministic_patch_validation"
    )


def test_post_response_binding_failure_occurs_before_patch_json_parser() -> None:
    content = "not-json"
    llm = _RecordingLLM(content)

    def fail_binding(_):
        raise RuntimeError("digest drift")

    with pytest.raises(RuntimeError, match="digest drift") as exc_info:
        LLMExactPatchGenerator(llm).generate(
            user_request="change it",
            evidence_items=[{"excerpt": "old"}],
            binding_registry=_registry(),
            constraints=[],
            post_response_admission=fail_binding,
        )

    assert getattr(exc_info.value, "diagnostic_content") == content
    assert getattr(exc_info.value, "diagnostics")["done_reason"] == "stop"
