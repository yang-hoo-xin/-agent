"""Reuse exact visible failed response text, never a hash-only or changed version."""

import hashlib

from src.libs.llm import AgentMessage
from src.mod_agent.local_entry import LocalOllamaInitialPatchAdapter


def test_revision_reuses_exact_visible_patch_and_preserves_new_failure():
    raw = '{"changes":[{"after_text":"measured failing code"}]}'
    visible = (AgentMessage(role="user", content="Preserve independent behavior."),
               AgentMessage(role="assistant", content=raw))
    feedback = {"observations": [{"expected": 30, "observed": 10}]}
    messages = LocalOllamaInitialPatchAdapter._revision_messages(
        raw, feedback, message_type="patch_behavior_correction", visible_messages=visible,
    )
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert messages[0].content["validator_feedback"] == feedback
    assert messages[0].content["previous_response_ref"]["content_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert "earlier complete assistant Patch" in messages[0].content["required_action"]
    assert messages[0].content["revision_semantics"] == "complete_replacement_relative_to_B0"


def test_changed_or_absent_visible_response_must_include_full_current_code():
    raw = '{"changes":[{"after_text":"current code"}]}'
    for visible in ((), (AgentMessage(role="assistant", content=raw + " "),),
                    (AgentMessage(role="user", content=raw),)):
        messages = LocalOllamaInitialPatchAdapter._revision_messages(
            raw, {"observations": []}, message_type="patch_behavior_correction", visible_messages=visible,
        )
        assert len(messages) == 2
        assert messages[0].role == "assistant" and messages[0].content == raw
        assert "previous_response_ref" not in messages[1].content
