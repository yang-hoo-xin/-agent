from __future__ import annotations

import json

import pytest

from src.libs.llm import BaseLLM, ChatResponse, Message
from src.libs.llm.ollama_llm import build_ollama_context_admission
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


def _large_projection_fixture() -> dict[str, object]:
    evidence_items: list[dict[str, object]] = []
    edit_bindings: list[dict[str, object]] = []
    supporting_bindings: list[dict[str, object]] = []
    required_change_units: list[dict[str, object]] = []
    required_validation_by_binding: dict[str, list[str]] = {}
    response_changes: list[dict[str, object]] = []

    for index in range(1, 4):
        binding_id = f"edit_binding_{index:03d}"
        evidence_id = f"edit_evidence_{index:03d}"
        source_path = f"generated_mods/Generic/Feature{index}.cs"
        source_hash = f"{index:064x}"
        symbol = f"Generic.Feature{index}.Apply"
        span = {"start_line": index * 100, "end_line": index * 100 + 30}
        receiver_name = f"Setting{index}"
        receiver_type = "Shared.SettingBox<bool>"
        declared_members = {
            f"Member{member_index:03d}": {
                "member_name": f"Member{member_index:03d}",
                "member_kind": "property",
                "declared_type": receiver_type,
                "declaring_type": f"Generic.Feature{index}",
                "declaration_span": {
                    "start_line": member_index + 1,
                    "end_line": member_index + 1,
                },
                "is_static": True,
            }
            for member_index in range(18)
        }
        declared_members[receiver_name] = {
            "member_name": receiver_name,
            "member_kind": "property",
            "declared_type": receiver_type,
            "declaring_type": f"Generic.Feature{index}",
            "declaration_span": {"start_line": 5, "end_line": 5},
            "is_static": True,
        }
        declared_member_types = {
            name: str(identity["declared_type"])
            for name, identity in declared_members.items()
        }
        verified_member_accesses = [
            {
                "edit_binding_id": binding_id,
                "source_receiver": {
                    "evidence_id": evidence_id,
                    "source_path": source_path,
                    "source_hash": source_hash,
                    "declaring_type": f"Generic.Feature{index}",
                    "member_name": receiver_name,
                    "member_kind": "property",
                    "declaration_span": {"start_line": 5, "end_line": 5},
                    "declared_type": receiver_type,
                    "receiver_closed_type": "Shared.SettingBox`1<System.Boolean>",
                },
                "consumer": {
                    "declaring_type": f"Generic.Feature{index}",
                    "receiver_member": receiver_name,
                    "member_kind": "property",
                    "is_static": True,
                    "receiver_closed_type": "Shared.SettingBox`1<System.Boolean>",
                },
                "type_reference": {"symbol": "Shared.SettingBox`1"},
                "member_access": {
                    "declaring_type": "Shared.SettingBox`1",
                    "member_name": "Value",
                    "member_kind": "property",
                    "access_kind": "instance_property_get",
                    "closed_result_type": "System.Boolean",
                },
            }
        ]
        before_text = f"ApplyFeature{index}();"
        excerpt = "\n".join(
            [
                f"// verified source context {index}:{line:02d} " + "x" * 48
                for line in range(16)
            ]
            + [before_text]
        )
        evidence_items.append(
            {
                "authority": "deterministic_fixture",
                "chunk_id": f"chunk_{index:03d}",
                "claim_supported": f"Feature {index} current behavior is visible.",
                "declared_member_types": declared_member_types,
                "declared_members": declared_members,
                "declaring_type": f"Feature{index}",
                "declaring_type_full_name": f"Generic.Feature{index}",
                "doc_hash": source_hash,
                "document_id": f"document_{index:03d}",
                "evidence_id": evidence_id,
                "excerpt": excerpt,
                "file_hash": source_hash,
                "method_kind": "method",
                "method_name": "Apply",
                "parameter_types": [],
                "retrieval_method": "fixture_live_read",
                "return_type": "void",
                "risk_notes": ["Keep unrelated behavior unchanged."],
                "score": 1.0,
                "source_hash": source_hash,
                "source_path": source_path,
                "source_ref": f"source://target_source/{source_path}",
                "source_type": "target_source",
                "span": span,
                "symbol": symbol,
                "usage": "edit_source_evidence",
                "verified_member_accesses": verified_member_accesses,
            }
        )
        edit_bindings.append(
            {
                "authority": "deterministic_fixture",
                "binding_id": binding_id,
                "canonical_target_path": source_path,
                "claim_supported": f"Feature {index} is an authorized edit target.",
                "declared_member_types": declared_member_types,
                "declared_members": declared_members,
                "declaring_type": f"Feature{index}",
                "declaring_type_full_name": f"Generic.Feature{index}",
                "evidence_id": evidence_id,
                "method_kind": "method",
                "method_name": "Apply",
                "parameter_types": [],
                "retrieval_method": "fixture_live_read",
                "return_type": "void",
                "source_hash": source_hash,
                "source_type": "target_source",
                "target_span": span,
                "target_symbol": symbol,
                "usage": "edit_target_scope",
                "verified_member_accesses": verified_member_accesses,
            }
        )
        required_change_units.append(
            {
                "change_id": f"change_{index:03d}",
                "change_type": "modify_behavior",
                "edit_binding_id": binding_id,
                "hook_target_binding_id": None,
                "supporting_binding_ids": [],
                "operation": "minimal_evidence_bound_change",
            }
        )
        required_validation_by_binding[binding_id] = [
            "compile or static validation",
            "behavior evidence observed",
        ]
        response_changes.append(
            {
                "change_id": f"change_{index:03d}",
                "change_type": "modify_behavior",
                "edit_binding_id": binding_id,
                "operation": "exact_text_replace",
                "rationale": "Apply the bounded behavior change.",
                "expected_validation": ["behavior evidence observed"],
                "rollback_hint": "Restore the exact prior source text.",
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": before_text,
                    "after_text": f"ApplyUpdatedFeature{index}();",
                    "expected_occurrences": 1,
                },
            }
        )

    for index in range(1, 4):
        binding_id = f"support_binding_{index:03d}"
        evidence_id = f"support_evidence_{index:03d}"
        source_path = f"generated_mods/Generic/Support{index}.cs"
        source_hash = f"{index + 10:064x}"
        symbol = f"Generic.Support{index}.Observe"
        span = {"start_line": index * 20, "end_line": index * 20 + 12}
        excerpt = "\n".join(
            [
                f"// supporting source context {index}:{line:02d} " + "y" * 48
                for line in range(8)
            ]
            + [f"ObserveSupport{index}();"]
        )
        support_declared_members = {
            f"SupportMember{member_index:03d}": {
                "member_name": f"SupportMember{member_index:03d}",
                "member_kind": "field",
                "declared_type": "System.Int32",
                "declaring_type": f"Generic.Support{index}",
                "declaration_span": {
                    "start_line": member_index + 1,
                    "end_line": member_index + 1,
                },
                "is_static": False,
            }
            for member_index in range(18)
        }
        evidence_items.append(
            {
                "authority": "deterministic_fixture",
                "chunk_id": f"support_chunk_{index:03d}",
                "claim_supported": f"Support behavior {index} constrains the change.",
                "declared_member_types": {
                    name: "System.Int32" for name in support_declared_members
                },
                "declared_members": support_declared_members,
                "declaring_type": f"Support{index}",
                "declaring_type_full_name": f"Generic.Support{index}",
                "doc_hash": source_hash,
                "document_id": f"support_document_{index:03d}",
                "evidence_id": evidence_id,
                "excerpt": excerpt,
                "file_hash": source_hash,
                "method_kind": "method",
                "method_name": "Observe",
                "parameter_types": [],
                "retrieval_method": "fixture_live_read",
                "return_type": "void",
                "risk_notes": ["Preserve this supporting behavior."],
                "score": 0.9,
                "source_hash": source_hash,
                "source_path": source_path,
                "source_ref": f"source://target_source/{source_path}",
                "source_type": "target_source",
                "span": span,
                "symbol": symbol,
                "usage": "edit_source_evidence",
                "verified_member_accesses": [],
            }
        )
        supporting_bindings.append(
            {
                "authority": "deterministic_fixture",
                "binding_id": binding_id,
                "claim_supported": f"Support behavior {index} constrains the change.",
                "declaring_type": f"Support{index}",
                "evidence_id": evidence_id,
                "method_kind": "method",
                "method_name": "Observe",
                "parameter_types": [],
                "retrieval_method": "fixture_live_read",
                "return_type": "void",
                "source_path": source_path,
                "source_type": "target_source",
                "target_span": span,
                "target_symbol": symbol,
                "usage": "edit_source_evidence",
            }
        )

    return {
        "user_request": "Apply three bounded behavior changes.",
        "evidence_items": evidence_items,
        "binding_registry": {
            "schema_version": "binding_registry_v1",
            "owner_artifact_type": "implementation_plan",
            "edit_bindings": edit_bindings,
            "supporting_bindings": supporting_bindings,
        },
        "constraints": [
            "Do not perform unrelated refactors.",
            "Preserve supporting behavior.",
        ],
        "required_change_units": required_change_units,
        "required_validation_by_binding": required_validation_by_binding,
        "response": {"changes": response_changes},
    }


def _generate_projection_fixture(
    fixture: dict[str, object],
) -> tuple[_RecordingLLM, object]:
    llm = _RecordingLLM(json.dumps(fixture["response"]))
    generated = LLMExactPatchGenerator(llm).generate(
        user_request=str(fixture["user_request"]),
        evidence_items=list(fixture["evidence_items"]),
        binding_registry=dict(fixture["binding_registry"]),
        constraints=list(fixture["constraints"]),
        required_change_units=list(fixture["required_change_units"]),
        required_validation_by_binding=dict(
            fixture["required_validation_by_binding"]
        ),
        require_native_schema=True,
        provider_request_recorder=lambda _: None,
    )
    return llm, generated


def test_patch_model_projection_admits_actual_scale_generic_fixture() -> None:
    fixture = _large_projection_fixture()
    llm, generated = _generate_projection_fixture(fixture)

    prompt_payload = json.loads(llm.messages[1].content)
    evidence_by_id = {
        item["evidence_id"]: item for item in fixture["evidence_items"]
    }
    edit_bindings = fixture["binding_registry"]["edit_bindings"]
    expected_edit_ids = {
        item["binding_id"] for item in edit_bindings
    }
    assert set(prompt_payload["edit_binding_contexts"]) == expected_edit_ids
    for binding in edit_bindings:
        evidence = evidence_by_id[binding["evidence_id"]]
        context = prompt_payload["edit_binding_contexts"][binding["binding_id"]]
        assert context["binding_id"] == binding["binding_id"]
        assert context["evidence_id"] == binding["evidence_id"]
        assert context["canonical_target_path"] == binding["canonical_target_path"]
        assert context["source_hash"] == binding["source_hash"]
        assert context["target_symbol"] == binding["target_symbol"]
        assert context["target_span"] == binding["target_span"]
        assert context["source_excerpt"] == evidence["excerpt"]
        assert context["declared_member_types"] == binding["declared_member_types"]
        assert context["declared_members"] == binding["declared_members"]
        assert context["verified_member_accesses"] == binding[
            "verified_member_accesses"
        ]

    expected_support = fixture["binding_registry"]["supporting_bindings"]
    support_by_id = {
        item["binding_id"]: item for item in prompt_payload["supporting_evidence"]
    }
    assert set(support_by_id) == {
        item["binding_id"] for item in expected_support
    }
    for binding in expected_support:
        evidence = evidence_by_id[binding["evidence_id"]]
        projected = support_by_id[binding["binding_id"]]
        assert projected["evidence_id"] == binding["evidence_id"]
        assert projected["source_path"] == binding["source_path"]
        assert projected["source_hash"] == evidence["source_hash"]
        assert projected["target_symbol"] == binding["target_symbol"]
        assert projected["target_span"] == binding["target_span"]
        assert projected["excerpt"] == evidence["excerpt"]

    assert prompt_payload["required_change_units"] == fixture[
        "required_change_units"
    ]
    assert prompt_payload["required_validation_by_binding"] == {
        binding_id: ["behavior evidence observed"]
        for binding_id in sorted(expected_edit_ids)
    }
    assert prompt_payload["constraints"] == fixture["constraints"]
    assert "evidence" not in prompt_payload
    assert "doc_hash" not in llm.messages[1].content
    assert "document_id" not in llm.messages[1].content
    assert llm.messages[1].content.count('"declared_members"') == len(
        expected_edit_ids
    )

    output_budget = 4096
    context_window = 40960
    for model_name in (
        "generic-local-structured-model",
        "generic-" + "long-model-identity-" * 12,
    ):
        provider_payload = {
            "model": model_name,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in llm.messages
            ],
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_predict": output_budget,
                "num_ctx": context_window,
            },
            "think": False,
            "format": llm.kwargs["response_format"],
        }
        admission = build_ollama_context_admission(
            payload=provider_payload,
            configured_num_ctx=context_window,
            num_predict=output_budget,
        )
        assert admission["admitted"] is True
        assert admission["conservative_required_context"] <= context_window

    assert len(generated.changes) == len(expected_edit_ids)


@pytest.mark.parametrize(
    "failure_case",
    [
        "required_evidence_missing",
        "required_excerpt_missing",
        "canonical_target_path_missing",
        "source_hash_missing",
        "source_hash_mismatch",
        "target_identity_mismatch",
        "required_change_coverage_missing",
        "required_supporting_evidence_missing",
    ],
)
def test_patch_model_projection_fails_closed_before_provider_call(
    failure_case: str,
) -> None:
    fixture = json.loads(json.dumps(_large_projection_fixture()))
    evidence_items = fixture["evidence_items"]
    edit_bindings = fixture["binding_registry"]["edit_bindings"]
    required_change_units = fixture["required_change_units"]
    first_binding = edit_bindings[0]
    first_evidence_id = first_binding["evidence_id"]

    if failure_case == "required_evidence_missing":
        fixture["evidence_items"] = [
            item
            for item in evidence_items
            if item["evidence_id"] != first_evidence_id
        ]
    elif failure_case == "required_excerpt_missing":
        next(
            item for item in evidence_items if item["evidence_id"] == first_evidence_id
        ).pop("excerpt")
    elif failure_case == "canonical_target_path_missing":
        first_binding.pop("canonical_target_path")
    elif failure_case == "source_hash_missing":
        first_binding.pop("source_hash")
    elif failure_case == "source_hash_mismatch":
        first_binding["source_hash"] = "f" * 64
    elif failure_case == "target_identity_mismatch":
        first_binding["target_symbol"] = "Generic.Different.Apply"
    elif failure_case == "required_change_coverage_missing":
        required_change_units.pop()
    elif failure_case == "required_supporting_evidence_missing":
        required_change_units[0]["supporting_binding_ids"] = [
            "support_binding_001"
        ]
        fixture["evidence_items"] = [
            item
            for item in evidence_items
            if item["evidence_id"] != "support_evidence_001"
        ]

    llm = _RecordingLLM(json.dumps(fixture["response"]))
    with pytest.raises(PatchGenerationError) as exc_info:
        LLMExactPatchGenerator(llm).generate(
            user_request=str(fixture["user_request"]),
            evidence_items=list(fixture["evidence_items"]),
            binding_registry=dict(fixture["binding_registry"]),
            constraints=list(fixture["constraints"]),
            required_change_units=list(fixture["required_change_units"]),
            required_validation_by_binding=dict(
                fixture["required_validation_by_binding"]
            ),
            require_native_schema=True,
            provider_request_recorder=lambda _: None,
        )

    assert llm.messages == []
    assert exc_info.value.diagnostics["failure_boundary"] == (
        "patch_model_input_projection"
    )


def test_post_response_validation_uses_authoritative_binding_evidence() -> None:
    fixture = _large_projection_fixture()
    supporting_evidence = next(
        item
        for item in fixture["evidence_items"]
        if item["evidence_id"] == "support_evidence_001"
    )
    fixture["response"]["changes"][0]["patch"]["before_text"] = (
        supporting_evidence["excerpt"].splitlines()[-1]
    )
    fixture["response"]["changes"][0]["patch"]["after_text"] = (
        "ChangedSupportOnly();"
    )
    llm = _RecordingLLM(json.dumps(fixture["response"]))

    with pytest.raises(PatchGenerationError) as exc_info:
        LLMExactPatchGenerator(llm).generate(
            user_request=str(fixture["user_request"]),
            evidence_items=list(fixture["evidence_items"]),
            binding_registry=dict(fixture["binding_registry"]),
            constraints=list(fixture["constraints"]),
            required_change_units=list(fixture["required_change_units"]),
            required_validation_by_binding=dict(
                fixture["required_validation_by_binding"]
            ),
            require_native_schema=True,
            provider_request_recorder=lambda _: None,
        )

    assert llm.messages
    assert exc_info.value.diagnostics["failure_classification"] == (
        "before_text_outside_edit_binding"
    )


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


def test_generator_rejects_incomplete_plan_change_coverage() -> None:
    registry = {
        "edit_bindings": [
            {
                "binding_id": "edit_binding_001",
                "evidence_id": "ev_001",
                "source_hash": "1" * 64,
                "canonical_target_path": "Patches/BehaviorOne.cs",
                "target_symbol": "BehaviorOne.Apply",
                "target_span": {"start_line": 1, "end_line": 2},
            },
            {
                "binding_id": "edit_binding_002",
                "evidence_id": "ev_002",
                "source_hash": "2" * 64,
                "canonical_target_path": "Patches/BehaviorTwo.cs",
                "target_symbol": "BehaviorTwo.Apply",
                "target_span": {"start_line": 3, "end_line": 4},
            },
        ]
    }
    payload = {
        "changes": [
            {
                "change_id": "chg_001",
                "change_type": "modify_behavior",
                "edit_binding_id": "edit_binding_001",
                "operation": "exact_text_replace",
                "rationale": "Implement the first planned operation.",
                "expected_validation": ["dotnet build"],
                "rollback_hint": "Restore the first source text.",
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "First();",
                    "after_text": "FirstChanged();",
                    "expected_occurrences": 1,
                },
            }
        ]
    }

    with pytest.raises(PatchGenerationError) as exc_info:
        LLMExactPatchGenerator(_FakeLLM(json.dumps(payload))).generate(
            user_request="Implement both planned changes.",
            evidence_items=[
                {
                    "evidence_id": "ev_001",
                    "source_hash": "1" * 64,
                    "source_path": "Patches/BehaviorOne.cs",
                    "symbol": "BehaviorOne.Apply",
                    "span": {"start_line": 1, "end_line": 2},
                    "excerpt": "First();",
                },
                {
                    "evidence_id": "ev_002",
                    "source_hash": "2" * 64,
                    "source_path": "Patches/BehaviorTwo.cs",
                    "symbol": "BehaviorTwo.Apply",
                    "span": {"start_line": 3, "end_line": 4},
                    "excerpt": "Second();",
                },
            ],
            binding_registry=registry,
            constraints=[],
            required_change_units=[
                {
                    "change_id": "chg_001",
                    "edit_binding_id": "edit_binding_001",
                    "operation": "Change the first behavior.",
                },
                {
                    "change_id": "chg_002",
                    "edit_binding_id": "edit_binding_002",
                    "operation": "Change the second behavior.",
                },
            ],
        )

    assert exc_info.value.diagnostics["failure_classification"] == (
        "plan_change_coverage_incomplete"
    )
    assert exc_info.value.diagnostics["missing_plan_changes"] == [
        {"change_id": "chg_002", "edit_binding_id": "edit_binding_002"}
    ]


def test_generator_rejects_before_text_from_another_binding() -> None:
    registry = {
        "edit_bindings": [
            {
                "binding_id": "edit_binding_001",
                "evidence_id": "ev_001",
                "source_hash": "1" * 64,
                "canonical_target_path": "Patches/Behavior.cs",
                "target_symbol": "Behavior.Apply",
                "target_span": {"start_line": 1, "end_line": 2},
            }
        ],
        "supporting_bindings": [
            {
                "binding_id": "support_binding_002",
                "evidence_id": "ev_002",
                "source_path": "Patches/Support.cs",
                "source_type": "target_source",
                "target_symbol": "Support.Observe",
                "target_span": {"start_line": 1, "end_line": 2},
                "declaring_type": "Support",
                "method_name": "Observe",
                "parameter_types": [],
                "return_type": "void",
                "method_kind": "method",
            },
        ],
    }
    payload = {
        "changes": [
            {
                "change_id": "chg_001",
                "change_type": "modify_behavior",
                "edit_binding_id": "edit_binding_001",
                "operation": "exact_text_replace",
                "rationale": "Claim the first binding while editing the second.",
                "expected_validation": ["dotnet build"],
                "rollback_hint": "Restore source.",
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "Second();",
                    "after_text": "SecondChanged();",
                    "expected_occurrences": 1,
                },
            }
        ]
    }

    with pytest.raises(PatchGenerationError) as exc_info:
        LLMExactPatchGenerator(_FakeLLM(json.dumps(payload))).generate(
            user_request="Change only the first behavior.",
            evidence_items=[
                {
                    "evidence_id": "ev_001",
                    "source_hash": "1" * 64,
                    "source_path": "Patches/Behavior.cs",
                    "symbol": "Behavior.Apply",
                    "span": {"start_line": 1, "end_line": 2},
                    "excerpt": "First();",
                },
                {
                    "evidence_id": "ev_002",
                    "source_hash": "2" * 64,
                    "source_path": "Patches/Support.cs",
                    "source_type": "target_source",
                    "symbol": "Support.Observe",
                    "span": {"start_line": 1, "end_line": 2},
                    "declaring_type": "Support",
                    "method_name": "Observe",
                    "parameter_types": [],
                    "return_type": "void",
                    "method_kind": "method",
                    "excerpt": "Second();",
                },
            ],
            binding_registry=registry,
            constraints=[],
            required_change_units=[
                {
                    "change_id": "chg_001",
                    "edit_binding_id": "edit_binding_001",
                }
            ],
        )

    assert exc_info.value.diagnostics["failure_classification"] == (
        "before_text_outside_edit_binding"
    )


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


def test_generator_inherits_compile_validation_without_model_repetition() -> None:
    behavior_validation = [
        "startup_loaded",
        "target_path_executed",
        "acceptance_evidence_observed",
        "non_goals_preserved",
    ]
    payload = {
        "changes": [
            {
                "change_id": "change_001",
                "change_type": "modify_behavior",
                "edit_binding_id": "edit_binding_001",
                "operation": "exact_text_replace",
                "rationale": "bounded",
                "expected_validation": behavior_validation,
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
            "edit_binding_001": [
                "compile or static validation",
                *behavior_validation,
            ]
        },
    )

    prompt_payload = json.loads(llm.messages[1].content)
    assert prompt_payload["required_validation_by_binding"] == {
        "edit_binding_001": behavior_validation
    }
    assert generated.changes[0]["expected_validation"] == [
        "compile or static validation",
        *behavior_validation,
    ]


def test_generator_still_rejects_missing_behavior_validation_after_inheritance() -> None:
    payload = {
        "changes": [
            {
                "edit_binding_id": "edit_binding_001",
                "expected_validation": ["dotnet build"],
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": "old",
                    "after_text": "new",
                    "expected_occurrences": 1,
                },
            }
        ]
    }
    behavior_validation = [
        "startup_loaded",
        "target_path_executed",
        "acceptance_evidence_observed",
        "non_goals_preserved",
    ]

    with pytest.raises(PatchGenerationError) as exc_info:
        LLMExactPatchGenerator(_FakeLLM(json.dumps(payload))).generate(
            user_request="change it",
            evidence_items=[{"excerpt": "old"}],
            binding_registry=_registry(),
            constraints=[],
            required_validation_by_binding={
                "edit_binding_001": [
                    "compile or static validation",
                    *behavior_validation,
                ]
            },
        )

    assert exc_info.value.diagnostics["failure_classification"] == (
        "upstream_validation_omitted"
    )
    assert exc_info.value.diagnostics["missing_upstream_validation"] == (
        behavior_validation
    )


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
