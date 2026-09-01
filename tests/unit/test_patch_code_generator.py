from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.libs.llm import BaseLLM, ChatResponse, Message, OllamaLLM
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


class _FrozenTestLLM(BaseLLM):
    def __init__(self, response: ChatResponse) -> None:
        self.response = response
        self.chat_count = 0
        self.prepare_count = 0
        self.resume_count = 0

    def chat(self, messages: list[Message], trace=None, **kwargs) -> ChatResponse:
        self.chat_count += 1
        raise AssertionError("freeze/resume must not call the immediate chat path")

    def prepare_structured_chat(
        self,
        messages: list[Message],
        trace=None,
        **kwargs,
    ) -> dict[str, object]:
        self.prepare_count += 1
        payload = {
            "model": "fake-codegen",
            "messages": [
                {"role": item.role, "content": item.content} for item in messages
            ],
            "stream": False,
            "options": {
                "temperature": kwargs["temperature"],
                "num_predict": 4096,
            },
            "think": False,
            "format": kwargs["response_format"],
        }
        body = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        request = {
            "method": "POST",
            "destination": "http://127.0.0.1:11434/api/chat",
            "headers": {"Content-Type": "application/json"},
            "content_type": "application/json",
            "body_utf8": body.decode("utf-8"),
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "body_size_bytes": len(body),
            "timeout_seconds": 600.0,
            "trust_environment": False,
            "follow_redirects": False,
            "context_admission": None,
            "model": "fake-codegen",
            "output_budget": 4096,
            "context_window": None,
        }
        kwargs["provider_request_recorder"](request)
        return request

    def resume_structured_chat(
        self,
        frozen_request: dict[str, object],
    ) -> ChatResponse:
        self.resume_count += 1
        assert frozen_request["body_sha256"] == hashlib.sha256(
            frozen_request["body_utf8"].encode("utf-8")
        ).hexdigest()
        return self.response


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
                "rationale": f"Implement the bounded behavior for change {index}.",
                "expected_validation": [
                    "compile or static validation",
                    "behavior evidence observed",
                ],
            }
        )
        required_validation_by_binding[binding_id] = [
            "compile or static validation",
            "behavior evidence observed",
        ]
        response_changes.append(
            {
                "change_id": f"change_{index:03d}",
                "edit_binding_id": binding_id,
                "rationale": "Apply the bounded behavior change.",
                "rollback_hint": "Restore the exact prior source text.",
                "after_text": excerpt.replace(
                    before_text,
                    f"ApplyUpdatedFeature{index}();",
                ),
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


def _frozen_resume_identity() -> dict[str, object]:
    return {
        "run_id": "run_001",
        "request_id": "request_001",
        "model_role": "initial_patch",
        "role_ordinal": 1,
        "remaining_call_budget": 1,
        "model": "fake-codegen",
        "output_budget": 4096,
        "context_window": 32768,
        "source_snapshot_sha256": "a" * 64,
        "artifact_bindings": {
            "feature_spec_ref": "a/feature_spec.json",
            "feature_spec_hash": "b" * 64,
            "evidence_pack_ref": "a/evidence_pack.json",
            "evidence_pack_hash": "c" * 64,
            "implementation_plan_ref": "a/implementation_plan.json",
            "implementation_plan_hash": "d" * 64,
        },
        "binding_registry_sha256": "e" * 64,
    }


def _prepare_frozen_fixture(
    fixture: dict[str, object],
    llm: _FrozenTestLLM,
    store: dict[str, object],
) -> LLMExactPatchGenerator:
    generator = LLMExactPatchGenerator(llm)
    generator.prepare_frozen_native(
        resume_identity=_frozen_resume_identity(),
        frozen_attempt_recorder=lambda value: store.update(value=value),
        user_request=str(fixture["user_request"]),
        evidence_items=list(fixture["evidence_items"]),
        binding_registry=dict(fixture["binding_registry"]),
        constraints=list(fixture["constraints"]),
        required_change_units=list(fixture["required_change_units"]),
        required_validation_by_binding=dict(
            fixture["required_validation_by_binding"]
        ),
    )
    return generator


def test_native_freeze_uses_existing_prompt_schema_and_pauses_without_generation() -> None:
    fixture = _large_projection_fixture()
    immediate_llm, _ = _generate_projection_fixture(fixture)
    frozen_llm = _FrozenTestLLM(
        ChatResponse(
            content=json.dumps(fixture["response"]),
            model="fake-codegen",
        )
    )
    store: dict[str, object] = {}

    _prepare_frozen_fixture(fixture, frozen_llm, store)

    attempt = store["value"]
    body = json.loads(attempt["provider_request"]["body_utf8"])
    assert body["messages"] == [
        {"role": item.role, "content": item.content}
        for item in immediate_llm.messages
    ]
    assert body["format"] == immediate_llm.kwargs["response_format"]
    assert attempt["status"] == "paused_frozen"
    assert attempt["consumed"] is False
    assert attempt["terminal"] is None
    assert attempt["resume_identity"]["model_role"] == "initial_patch"
    assert attempt["resume_identity"]["role_ordinal"] == 1
    assert frozen_llm.prepare_count == 1
    assert frozen_llm.chat_count == 0
    assert frozen_llm.resume_count == 0


def test_native_frozen_resume_materializes_then_rejects_duplicate_without_call() -> None:
    fixture = _large_projection_fixture()
    frozen_llm = _FrozenTestLLM(
        ChatResponse(
            content=json.dumps(fixture["response"]),
            model="fake-codegen",
            usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            raw_response={"done": True, "done_reason": "stop"},
        )
    )
    store: dict[str, object] = {}
    generator = _prepare_frozen_fixture(fixture, frozen_llm, store)
    admitted: list[ChatResponse] = []

    generated = generator.resume_frozen_native(
        frozen_attempt_loader=lambda: store["value"],
        frozen_attempt_recorder=lambda value: store.update(value=value),
        current_resume_identity=_frozen_resume_identity(),
        post_response_admission=admitted.append,
    )

    assert len(generated.changes) == 3
    assert admitted[0].content == json.dumps(fixture["response"])
    assert frozen_llm.resume_count == 1
    assert store["value"]["status"] == "terminal_succeeded"
    with pytest.raises(PatchGenerationError) as exc_info:
        generator.resume_frozen_native(
            frozen_attempt_loader=lambda: store["value"],
            frozen_attempt_recorder=lambda value: store.update(value=value),
            current_resume_identity=_frozen_resume_identity(),
        )
    assert exc_info.value.diagnostics["failure_classification"] == (
        "frozen_patch_attempt_not_resumable"
    )
    assert frozen_llm.resume_count == 1


@pytest.mark.parametrize(
    "field",
    (
        "run_id",
        "request_id",
        "model",
        "output_budget",
        "source_snapshot_sha256",
        "artifact_bindings",
        "binding_registry_sha256",
    ),
)
def test_native_frozen_resume_identity_drift_blocks_before_provider(
    field: str,
) -> None:
    fixture = _large_projection_fixture()
    frozen_llm = _FrozenTestLLM(
        ChatResponse(content=json.dumps(fixture["response"]), model="fake-codegen")
    )
    store: dict[str, object] = {}
    generator = _prepare_frozen_fixture(fixture, frozen_llm, store)
    current = _frozen_resume_identity()
    current[field] = "drift"

    with pytest.raises(PatchGenerationError) as exc_info:
        generator.resume_frozen_native(
            frozen_attempt_loader=lambda: store["value"],
            frozen_attempt_recorder=lambda value: store.update(value=value),
            current_resume_identity=current,
        )

    assert exc_info.value.diagnostics["failure_classification"] == (
        "frozen_patch_resume_identity_mismatch"
    )
    assert frozen_llm.resume_count == 0


def test_native_frozen_file_corruption_hash_mismatch_blocks_before_provider() -> None:
    fixture = _large_projection_fixture()
    frozen_llm = _FrozenTestLLM(
        ChatResponse(content=json.dumps(fixture["response"]), model="fake-codegen")
    )
    store: dict[str, object] = {}
    generator = _prepare_frozen_fixture(fixture, frozen_llm, store)
    corrupted = json.loads(json.dumps(store["value"]))
    corrupted["materialization_context"]["allowed_bindings"].append(
        "edit_binding_forged"
    )
    store["value"] = corrupted

    with pytest.raises(PatchGenerationError) as exc_info:
        generator.resume_frozen_native(
            frozen_attempt_loader=lambda: store["value"],
            frozen_attempt_recorder=lambda value: store.update(value=value),
            current_resume_identity=_frozen_resume_identity(),
        )

    assert exc_info.value.diagnostics["failure_classification"] == (
        "frozen_patch_attempt_hash_mismatch"
    )
    assert frozen_llm.resume_count == 0


def test_native_frozen_invalid_response_is_terminal_without_correction() -> None:
    fixture = _large_projection_fixture()
    frozen_llm = _FrozenTestLLM(
        ChatResponse(
            content='{"changes":[{"change_id":"wrong"}]}',
            model="fake-codegen",
            raw_response={"done": True, "done_reason": "stop"},
        )
    )
    store: dict[str, object] = {}
    generator = _prepare_frozen_fixture(fixture, frozen_llm, store)

    with pytest.raises(PatchGenerationError):
        generator.resume_frozen_native(
            frozen_attempt_loader=lambda: store["value"],
            frozen_attempt_recorder=lambda value: store.update(value=value),
            current_resume_identity=_frozen_resume_identity(),
        )

    assert frozen_llm.resume_count == 1
    assert store["value"]["status"] == "terminal_failed"
    assert store["value"]["terminal"]["automatic_correction"] is False
    assert store["value"]["terminal"]["automatic_retry"] is False


def test_native_frozen_invalid_response_uses_exactly_one_http_post() -> None:
    fixture = _large_projection_fixture()
    settings = SimpleNamespace(
        llm=SimpleNamespace(
            model="fake-codegen",
            temperature=0.0,
            max_tokens=4096,
        )
    )
    generator = LLMExactPatchGenerator(
        OllamaLLM(
            settings,
            base_url="http://127.0.0.1:11434",
            timeout=600.0,
            context_window=200_000,
        )
    )
    store: dict[str, object] = {}
    resume_identity = _frozen_resume_identity()
    resume_identity["context_window"] = 200_000
    generator.prepare_frozen_native(
        resume_identity=resume_identity,
        frozen_attempt_recorder=lambda value: store.update(value=value),
        user_request=str(fixture["user_request"]),
        evidence_items=list(fixture["evidence_items"]),
        binding_registry=dict(fixture["binding_registry"]),
        constraints=list(fixture["constraints"]),
        required_change_units=list(fixture["required_change_units"]),
        required_validation_by_binding=dict(
            fixture["required_validation_by_binding"]
        ),
    )
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "model": "fake-codegen",
        "message": {"role": "assistant", "content": '{"changes":[]}'},
        "done": True,
        "done_reason": "stop",
    }

    with patch("httpx.Client") as client:
        post = client.return_value.__enter__.return_value.post
        post.return_value = response
        with pytest.raises(PatchGenerationError):
            generator.resume_frozen_native(
                frozen_attempt_loader=lambda: store["value"],
                frozen_attempt_recorder=lambda value: store.update(value=value),
                current_resume_identity=resume_identity,
            )

    assert post.call_count == 1
    assert store["value"]["status"] == "terminal_failed"
    assert store["value"]["terminal"]["automatic_correction"] is False


def _non_native_plan_response_changes(
    fixture: dict[str, object],
) -> list[dict[str, object]]:
    evidence_by_id = {
        item["evidence_id"]: item for item in fixture["evidence_items"]
    }
    binding_by_id = {
        item["binding_id"]: item
        for item in fixture["binding_registry"]["edit_bindings"]
    }
    native_by_identity = {
        (item["change_id"], item["edit_binding_id"]): item
        for item in fixture["response"]["changes"]
    }
    changes: list[dict[str, object]] = []
    for required in fixture["required_change_units"]:
        identity = (required["change_id"], required["edit_binding_id"])
        native = native_by_identity[identity]
        binding = binding_by_id[required["edit_binding_id"]]
        evidence = evidence_by_id[binding["evidence_id"]]
        changes.append(
            {
                "change_id": required["change_id"],
                "change_type": "modify_behavior",
                "edit_binding_id": required["edit_binding_id"],
                "operation": "exact_text_replace",
                "rationale": native["rationale"],
                "rollback_hint": native["rollback_hint"],
                "patch": {
                    "kind": "exact_text_replace",
                    "before_text": evidence["excerpt"],
                    "after_text": native["after_text"],
                    "expected_occurrences": 1,
                },
            }
        )
    return changes


def _generate_non_native_plan_fixture(
    fixture: dict[str, object],
    response_changes: list[dict[str, object]],
) -> tuple[_RecordingLLM, object]:
    llm = _RecordingLLM(json.dumps({"changes": response_changes}))
    generated = LLMExactPatchGenerator(llm).generate(
        user_request=str(fixture["user_request"]),
        evidence_items=list(fixture["evidence_items"]),
        binding_registry=dict(fixture["binding_registry"]),
        constraints=list(fixture["constraints"]),
        target_behavior="Implement the feature-level behavior.",
        acceptance_criteria=["Observe the feature-level behavior."],
        runtime_verification_plan=["Restart and observe the feature."],
        required_change_units=list(fixture["required_change_units"]),
        required_validation_by_binding={},
        require_native_schema=False,
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

    assert prompt_payload["required_change_units"] == [
        {
            key: value
            for key, value in item.items()
            if key not in {"rationale", "expected_validation"}
        }
        for item in fixture["required_change_units"]
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
    required_by_pair = {
        (item["change_id"], item["edit_binding_id"]): item
        for item in fixture["required_change_units"]
    }
    for change in generated.changes:
        required = required_by_pair[
            (change["change_id"], change["edit_binding_id"])
        ]
        binding = next(
            item
            for item in edit_bindings
            if item["binding_id"] == change["edit_binding_id"]
        )
        evidence = evidence_by_id[binding["evidence_id"]]
        assert change["change_type"] == required["change_type"]
        assert change["operation"] == "exact_text_replace"
        assert change["supporting_binding_ids"] == required[
            "supporting_binding_ids"
        ]
        assert change["expected_validation"] == fixture[
            "required_validation_by_binding"
        ][change["edit_binding_id"]]
        assert change["patch"]["kind"] == "exact_text_replace"
        assert change["patch"]["before_text"] == evidence["excerpt"]
        assert change["patch"]["after_text"] != evidence["excerpt"]
        assert change["patch"]["expected_occurrences"] == 1


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


def test_native_response_does_not_repair_legacy_authoritative_patch_fields() -> None:
    fixture = _large_projection_fixture()
    first = fixture["response"]["changes"][0]
    first["patch"] = {
        "kind": "exact_text_replace",
        "before_text": "frozen 4B copied text outside the binding",
        "after_text": first.pop("after_text"),
        "expected_occurrences": 1,
    }
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
        "native_response_fields_invalid"
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
                    "expected_validation": ["Validate the first Plan change."],
                },
                {
                    "change_id": "chg_002",
                    "edit_binding_id": "edit_binding_002",
                    "operation": "Change the second behavior.",
                    "expected_validation": ["Validate the second Plan change."],
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
                    "expected_validation": ["Validate the exact Plan change."],
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


def test_external_non_native_plan_validation_is_hidden_and_materialized() -> None:
    fixture = _large_projection_fixture()
    hidden_validation = "Plan-only validation must be restored internally."
    for index, required in enumerate(fixture["required_change_units"], start=1):
        required["expected_validation"] = [f"{hidden_validation} {index}"]
    response_changes = _non_native_plan_response_changes(fixture)

    llm, generated = _generate_non_native_plan_fixture(
        fixture,
        response_changes,
    )

    prompt_payload = json.loads(llm.messages[1].content)
    assert prompt_payload["required_validation_by_binding"] == {}
    assert all(
        "expected_validation" not in item
        for item in prompt_payload["required_change_units"]
    )
    assert "expected_validation" not in prompt_payload["required_output"][
        "changes"
    ][0]
    provider_visible_messages = "\n".join(
        message.content for message in llm.messages
    )
    assert hidden_validation not in provider_visible_messages
    assert all("expected_validation" not in item for item in response_changes)
    expected_by_identity = {
        (item["change_id"], item["edit_binding_id"]): item[
            "expected_validation"
        ]
        for item in fixture["required_change_units"]
    }
    assert {
        (item["change_id"], item["edit_binding_id"]): item[
            "expected_validation"
        ]
        for item in generated.changes
    } == expected_by_identity


def test_external_non_native_plan_response_rejects_forged_validation_field() -> None:
    fixture = _large_projection_fixture()
    response_changes = _non_native_plan_response_changes(fixture)
    response_changes[0]["expected_validation"] = ["model-authored validation"]

    with pytest.raises(PatchGenerationError) as exc_info:
        _generate_non_native_plan_fixture(fixture, response_changes)

    assert exc_info.value.diagnostics["failure_boundary"] == (
        "deterministic_patch_validation"
    )
    assert exc_info.value.diagnostics["failure_classification"] == (
        "plan_bound_non_native_response_fields_invalid"
    )
    assert exc_info.value.diagnostics["unexpected_fields"] == [
        "expected_validation"
    ]


@pytest.mark.parametrize(
    ("failure_case", "expected_classification"),
    [
        ("missing", "plan_change_coverage_incomplete"),
        ("duplicate", "plan_change_coverage_incomplete"),
        (
            "mismatched_identity",
            "plan_bound_non_native_change_identity_unknown",
        ),
    ],
)
def test_external_non_native_plan_identity_fails_closed(
    failure_case: str,
    expected_classification: str,
) -> None:
    fixture = _large_projection_fixture()
    response_changes = _non_native_plan_response_changes(fixture)
    if failure_case == "missing":
        response_changes.pop()
    elif failure_case == "duplicate":
        response_changes[-1] = dict(response_changes[0])
    else:
        response_changes[0]["change_id"] = "change_unknown"

    with pytest.raises(PatchGenerationError) as exc_info:
        _generate_non_native_plan_fixture(fixture, response_changes)

    assert exc_info.value.diagnostics["failure_classification"] == (
        expected_classification
    )


def test_native_schema_in_prompt_and_provider_format_share_one_object() -> None:
    source_hash = "1" * 64
    source_path = "Patches/Behavior.cs"
    source_span = {"start_line": 1, "end_line": 1}
    payload = {
        "changes": [
            {
                "change_id": "change_001",
                "edit_binding_id": "edit_binding_001",
                "rationale": "bounded",
                "rollback_hint": "restore",
                "after_text": "new",
            }
        ]
    }
    llm = _RecordingLLM(json.dumps(payload))
    recorded_requests = []
    post_admission_calls = []

    generated = LLMExactPatchGenerator(llm).generate(
        user_request="change it",
        evidence_items=[
            {
                "evidence_id": "ev_001",
                "source_path": source_path,
                "source_hash": source_hash,
                "symbol": "Behavior.Apply",
                "span": source_span,
                "excerpt": "old",
            }
        ],
        binding_registry={
            "edit_bindings": [
                {
                    "binding_id": "edit_binding_001",
                    "evidence_id": "ev_001",
                    "canonical_target_path": source_path,
                    "source_hash": source_hash,
                    "target_symbol": "Behavior.Apply",
                    "target_span": source_span,
                }
            ]
        },
        constraints=[],
        required_change_units=[
            {
                "change_id": "change_001",
                "change_type": "modify_behavior",
                "edit_binding_id": "edit_binding_001",
                "supporting_binding_ids": [],
                "operation": "minimal_evidence_bound_change",
                "rationale": "Implement the bounded behavior.",
                "expected_validation": ["compile or static validation"],
            }
        ],
        required_validation_by_binding={
            "edit_binding_001": ["compile or static validation"]
        },
        require_native_schema=True,
        provider_request_recorder=recorded_requests.append,
        post_response_admission=post_admission_calls.append,
    )

    prompt_payload = json.loads(llm.messages[1].content)
    assert llm.kwargs["response_format"] == prompt_payload["required_output_schema"]
    assert llm.kwargs["response_format"]["properties"]["changes"]["items"][
        "properties"
    ]["edit_binding_id"]["enum"] == ["edit_binding_001"]
    item_schema = llm.kwargs["response_format"]["properties"]["changes"][
        "items"
    ]
    assert item_schema["required"] == [
        "change_id",
        "edit_binding_id",
        "rationale",
        "rollback_hint",
        "after_text",
    ]
    assert set(item_schema["properties"]) == set(item_schema["required"])
    assert "patch" not in item_schema["properties"]
    assert "expected_validation" not in item_schema["properties"]
    assert "before_text" not in json.dumps(item_schema)
    assert "kind" not in json.dumps(item_schema)
    assert "expected_occurrences" not in json.dumps(item_schema)
    assert recorded_requests == [{"body_sha256": "bound", "body_utf8": "{}"}]
    assert len(post_admission_calls) == 1
    assert generated.changes[0]["patch"]["after_text"] == "new"
    assert generated.changes[0]["patch"]["before_text"] == "old"
    assert generated.changes[0]["patch"]["kind"] == "exact_text_replace"
    assert generated.changes[0]["patch"]["expected_occurrences"] == 1
    assert generated.changes[0]["expected_validation"] == [
        "compile or static validation"
    ]


@pytest.mark.parametrize(
    ("failure_case", "expected_classification"),
    [
        ("unknown_binding", "native_change_binding_unknown"),
        ("unknown_change", "native_change_identity_unknown"),
        ("missing_change", "plan_change_coverage_incomplete"),
        ("duplicate_change", "plan_change_coverage_incomplete"),
        ("empty_after_text", "native_after_text_invalid"),
        ("same_after_text", "native_after_text_not_replacement"),
        ("unverified_member_access", "csharp_unverified_boolean_member_operand"),
        ("unexpected_root_field", "native_response_fields_invalid"),
    ],
)
def test_native_materialization_fails_closed_for_invalid_model_semantics(
    failure_case: str,
    expected_classification: str,
) -> None:
    fixture = json.loads(json.dumps(_large_projection_fixture()))
    changes = fixture["response"]["changes"]
    if failure_case == "unknown_binding":
        changes[0]["edit_binding_id"] = "edit_binding_unknown"
    elif failure_case == "unknown_change":
        changes[0]["change_id"] = "change_unknown"
    elif failure_case == "missing_change":
        changes.pop()
    elif failure_case == "duplicate_change":
        changes[-1] = dict(changes[0])
    elif failure_case == "empty_after_text":
        changes[0]["after_text"] = ""
    elif failure_case == "same_after_text":
        first_binding = fixture["binding_registry"]["edit_bindings"][0]
        first_evidence = next(
            item
            for item in fixture["evidence_items"]
            if item["evidence_id"] == first_binding["evidence_id"]
        )
        changes[0]["after_text"] = first_evidence["excerpt"]
    elif failure_case == "unverified_member_access":
        changes[0]["after_text"] += "\nif (!Setting1.IsReady) { return; }"
    elif failure_case == "unexpected_root_field":
        fixture["response"]["copied_source_hash"] = "not model authority"

    with pytest.raises(PatchGenerationError) as exc_info:
        _generate_projection_fixture(fixture)

    assert exc_info.value.diagnostics["failure_classification"] == (
        expected_classification
    )


def test_native_materialization_requires_plan_bound_complete_authority_input() -> None:
    llm = _RecordingLLM(
        json.dumps(
            {
                "changes": [
                    {
                        "change_id": "change_001",
                        "edit_binding_id": "edit_binding_001",
                        "rationale": "bounded",
                        "rollback_hint": "restore",
                        "after_text": "new",
                    }
                ]
            }
        )
    )

    with pytest.raises(PatchGenerationError) as exc_info:
        LLMExactPatchGenerator(llm).generate(
            user_request="change it",
            evidence_items=[{"excerpt": "old"}],
            binding_registry=_registry(),
            constraints=[],
            require_native_schema=True,
            provider_request_recorder=lambda _: None,
        )

    assert llm.messages == []
    assert exc_info.value.diagnostics["failure_boundary"] == (
        "patch_model_input_projection"
    )
    assert exc_info.value.diagnostics["failure_classification"] == (
        "native_patch_contract_requires_plan_bound_changes"
    )


@pytest.mark.parametrize(
    ("field", "value", "expected_classification"),
    [
        ("change_type", None, "required_change_unit_change_type_invalid"),
        (
            "change_type",
            "repair",
            "required_change_unit_change_type_invalid",
        ),
        ("operation", None, "required_change_unit_operation_invalid"),
        (
            "operation",
            "replace_unbounded_source",
            "required_change_unit_operation_invalid",
        ),
    ],
)
def test_native_plan_authority_fields_fail_closed_before_provider_call(
    field: str,
    value: str | None,
    expected_classification: str,
) -> None:
    fixture = json.loads(json.dumps(_large_projection_fixture()))
    required_change = fixture["required_change_units"][0]
    if value is None:
        required_change.pop(field)
    else:
        required_change[field] = value
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
    assert exc_info.value.diagnostics["failure_classification"] == (
        expected_classification
    )


def test_native_generated_patch_keeps_legacy_non_authoritative_risk_metadata() -> None:
    fixture = _large_projection_fixture()
    _, generated = _generate_projection_fixture(fixture)

    assert all(
        "risk_tags" not in item for item in fixture["required_change_units"]
    )
    assert all(change["risk_tags"] == ["medium"] for change in generated.changes)


def test_normalized_nested_region_requires_two_patch_replacements() -> None:
    configuration_excerpt = "ReloadConfiguration();"
    spread_inner_excerpt = "crosshairSize = GetCrosshairSize();"
    spread_outer_excerpt = (
        "crosshairSize = GetCrosshairSize();\nreturn true;"
    )
    evidence_items = [
        {
            "evidence_id": "ev_configuration",
            "source_path": "generated_mods/AccurateCrosshair/Configuration.cs",
            "source_hash": "configuration_hash",
            "symbol": "OnFileChanged",
            "span": {"start_line": 35, "end_line": 55},
            "source_type": "target_source",
            "excerpt": configuration_excerpt,
        },
        {
            "evidence_id": "ev_spread_inner",
            "source_path": (
                "generated_mods/AccurateCrosshair/CrosshairPatches/SpreadPatches.cs"
            ),
            "source_hash": "spread_hash",
            "symbol": "OverrideCrosshairSize",
            "span": {"start_line": 115, "end_line": 155},
            "source_type": "target_source",
            "declaring_type": "SpreadPatches",
            "method_name": "OverrideCrosshairSize",
            "parameter_types": None,
            "return_type": "bool",
            "method_kind": "method",
            "excerpt": spread_inner_excerpt,
        },
        {
            "evidence_id": "ev_spread_outer",
            "source_path": (
                "generated_mods/AccurateCrosshair/CrosshairPatches/SpreadPatches.cs"
            ),
            "source_hash": "spread_hash",
            "symbol": "OverrideCrosshairSize",
            "span": {"start_line": 115, "end_line": 160},
            "source_type": "target_source",
            "excerpt": spread_outer_excerpt,
        },
    ]
    binding_registry = {
        "schema_version": "binding_registry_v1",
        "owner_artifact_type": "implementation_plan",
        "edit_bindings": [
            {
                "binding_id": "edit_binding_001",
                "evidence_id": "ev_configuration",
                "canonical_target_path": evidence_items[0]["source_path"],
                "source_hash": "configuration_hash",
                "target_symbol": "OnFileChanged",
                "target_span": evidence_items[0]["span"],
            },
            {
                "binding_id": "edit_binding_002",
                "evidence_id": "ev_spread_outer",
                "canonical_target_path": evidence_items[2]["source_path"],
                "source_hash": "spread_hash",
                "target_symbol": "OverrideCrosshairSize",
                "target_span": evidence_items[2]["span"],
            },
        ],
        "supporting_bindings": [
            {
                "binding_id": "support_binding_ev_spread_inner",
                "evidence_id": "ev_spread_inner",
                "source_path": evidence_items[1]["source_path"],
                "source_type": "target_source",
                "target_symbol": "OverrideCrosshairSize",
                "target_span": evidence_items[1]["span"],
                "declaring_type": "SpreadPatches",
                "method_name": "OverrideCrosshairSize",
                "parameter_types": None,
                "return_type": "bool",
                "method_kind": "method",
                "usage": "edit_source_evidence",
            }
        ],
    }
    required_change_units = [
        {
            "change_id": "chg_001",
            "change_type": "modify_behavior",
            "edit_binding_id": "edit_binding_001",
            "hook_target_binding_id": None,
            "supporting_binding_ids": [],
            "operation": "minimal_evidence_bound_change",
            "rationale": "  Implement the configuration behavior only.  ",
            "expected_validation": ["  Validate configuration behavior.  "],
        },
        {
            "change_id": "chg_002",
            "change_type": "modify_behavior",
            "edit_binding_id": "edit_binding_002",
            "hook_target_binding_id": None,
            "supporting_binding_ids": ["support_binding_ev_spread_inner"],
            "operation": "minimal_evidence_bound_change",
            "rationale": (
                "Preserve the existing enabled spread behavior at this binding only."
            ),
            "expected_validation": ["Validate enabled spread preservation."],
        },
    ]
    response = {
        "changes": [
            {
                "change_id": "chg_001",
                "edit_binding_id": "edit_binding_001",
                "rationale": "bounded configuration change",
                "rollback_hint": "restore configuration",
                "after_text": "ReloadConfigurationAndSpreadSetting();",
            },
            {
                "change_id": "chg_002",
                "edit_binding_id": "edit_binding_002",
                "rationale": "bounded spread change",
                "rollback_hint": "restore spread method",
                "after_text": (
                    "if (enabled) crosshairSize = GetCrosshairSize();\nreturn true;"
                ),
            },
        ]
    }
    llm = _RecordingLLM(json.dumps(response))

    generated = LLMExactPatchGenerator(llm).generate(
        user_request="add an accurate spread enabled setting",
        evidence_items=evidence_items,
        binding_registry=binding_registry,
        constraints=[],
        acceptance_criteria=[
            "Validate configuration behavior.",
            "Validate enabled spread preservation.",
        ],
        required_change_units=required_change_units,
        required_validation_by_binding={
            "edit_binding_001": ["  Validate configuration behavior.  "],
            "edit_binding_002": ["Validate enabled spread preservation."],
        },
        require_native_schema=True,
        provider_request_recorder=lambda _: None,
    )

    prompt_payload = json.loads(llm.messages[1].content)
    response_schema = llm.kwargs["response_format"]
    assert len(prompt_payload["required_change_units"]) == 2
    assert set(prompt_payload["edit_binding_contexts"]) == {
        "edit_binding_001",
        "edit_binding_002",
    }
    assert prompt_payload["required_change_units"][1]["supporting_binding_ids"] == [
        "support_binding_ev_spread_inner"
    ]
    assert prompt_payload["required_change_units"] == [
        {
            key: value
            for key, value in item.items()
            if key not in {"rationale", "expected_validation"}
        }
        for item in required_change_units
    ]
    assert prompt_payload["acceptance_criteria"] == [
        "Validate configuration behavior.",
        "Validate enabled spread preservation.",
    ]
    assert response_schema["properties"]["changes"]["minItems"] == 2
    assert response_schema["properties"]["changes"]["maxItems"] == 2
    assert len(generated.changes) == 2
    assert generated.changes[0]["patch"] == {
        "kind": "exact_text_replace",
        "before_text": configuration_excerpt,
        "after_text": "ReloadConfigurationAndSpreadSetting();",
        "expected_occurrences": 1,
    }
    assert generated.changes[1]["patch"]["before_text"] == spread_outer_excerpt


@pytest.mark.parametrize(
    ("field", "value", "expected_classification"),
    [
        ("rationale", None, "required_change_unit_rationale_invalid"),
        ("rationale", "", "required_change_unit_rationale_invalid"),
        (
            "expected_validation",
            None,
            "required_change_unit_expected_validation_invalid",
        ),
        (
            "expected_validation",
            [""],
            "required_change_unit_expected_validation_invalid",
        ),
    ],
)
def test_native_change_semantic_obligations_fail_closed_before_provider_call(
    field: str,
    value: object,
    expected_classification: str,
) -> None:
    fixture = json.loads(json.dumps(_large_projection_fixture()))
    fixture["required_change_units"][0][field] = value
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
    assert exc_info.value.diagnostics["failure_classification"] == (
        expected_classification
    )


@pytest.mark.parametrize(
    ("argument_name", "value", "expected_classification"),
    [
        ("constraints", [""], "constraints_invalid"),
        ("constraints", "preserve", "constraints_invalid"),
        ("target_behavior", "", "target_behavior_invalid"),
        ("target_behavior", 1, "target_behavior_invalid"),
        ("acceptance_criteria", [], "acceptance_criteria_invalid"),
        ("acceptance_criteria", [""], "acceptance_criteria_invalid"),
        ("acceptance_criteria", "observe", "acceptance_criteria_invalid"),
        (
            "runtime_verification_plan",
            [],
            "runtime_verification_plan_invalid",
        ),
        (
            "runtime_verification_plan",
            [""],
            "runtime_verification_plan_invalid",
        ),
    ],
)
def test_provider_semantic_obligation_collections_fail_closed_before_call(
    argument_name: str,
    value: object,
    expected_classification: str,
) -> None:
    fixture = json.loads(json.dumps(_large_projection_fixture()))
    llm = _RecordingLLM(json.dumps(fixture["response"]))
    arguments = {
        "user_request": str(fixture["user_request"]),
        "evidence_items": list(fixture["evidence_items"]),
        "binding_registry": dict(fixture["binding_registry"]),
        "constraints": list(fixture["constraints"]),
        "target_behavior": "Implement the requested behavior.",
        "acceptance_criteria": ["Observe the requested behavior."],
        "runtime_verification_plan": ["Restart and observe the behavior."],
        "required_change_units": list(fixture["required_change_units"]),
        "required_validation_by_binding": dict(
            fixture["required_validation_by_binding"]
        ),
        "require_native_schema": True,
        "provider_request_recorder": lambda _: None,
    }
    arguments[argument_name] = value

    with pytest.raises(PatchGenerationError) as exc_info:
        LLMExactPatchGenerator(llm).generate(**arguments)

    assert llm.messages == []
    assert exc_info.value.diagnostics["failure_classification"] == (
        expected_classification
    )


def test_native_change_semantic_obligations_are_optional_compatibility_fields() -> None:
    fixture = json.loads(json.dumps(_large_projection_fixture()))
    for required_change in fixture["required_change_units"]:
        required_change.pop("rationale")
        required_change.pop("expected_validation")
    llm = _RecordingLLM(json.dumps(fixture["response"]))

    generated = LLMExactPatchGenerator(llm).generate(
        user_request=str(fixture["user_request"]),
        evidence_items=list(fixture["evidence_items"]),
        binding_registry=dict(fixture["binding_registry"]),
        constraints=list(fixture["constraints"]),
        target_behavior="Implement the requested behavior.",
        acceptance_criteria=["Observe the requested behavior."],
        runtime_verification_plan=["Restart and observe the behavior."],
        required_change_units=list(fixture["required_change_units"]),
        required_validation_by_binding=dict(
            fixture["required_validation_by_binding"]
        ),
        require_native_schema=True,
        provider_request_recorder=lambda _: None,
    )

    prompt_payload = json.loads(llm.messages[1].content)
    assert all(
        "rationale" not in item and "expected_validation" not in item
        for item in prompt_payload["required_change_units"]
    )
    assert len(generated.changes) == len(fixture["required_change_units"])


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
