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


def _registry() -> dict[str, object]:
    return {
        "edit_bindings": [
            {
                "binding_id": "edit_binding_001",
                "canonical_target_path": "Patches/HitFeedbackBehaviorPatch.cs",
            }
        ]
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
