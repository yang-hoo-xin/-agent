"""Exact-value feedback preservation, corruption and model-entry counterexamples."""
import json
from copy import deepcopy

import pytest

from src.mod_agent.proposal.behavior_feedback_view import project_behavior_feedback
from src.mod_agent.proposal.observation_value_refs import (
    GUIDE,
    SHORT_TAG,
    TABLE,
    TAG,
    TEXT_TAG,
    project_observation_values,
    restore_observation_values,
)


def feedback():
    state = {"text": "中文 file content\\n" * 120, "exists": True, "null": None,
             "number": 1.25, "nested": [False, 0, "0", {"kept": 7}]}
    return {"failure_owner": "patch_implementation", "observations": [
        {"check_id": f"scenario-{i}.check", "input": {"args": ["merge", str(i)]},
         "expected": {"exit_code": 0, "file": deepcopy(state)},
         "observed": {"exit_code": 2, "before_file": deepcopy(state), "after_file": deepcopy(state)}}
        for i in range(4)], "owner_binding_ids": ["original"], "report_sha256": "a" * 64}


def test_preserves_every_check_input_and_typed_value_without_mutating_original():
    raw = feedback()
    original = deepcopy(raw)
    compact = project_observation_values(raw)
    assert GUIDE in compact
    assert len(json.dumps(compact, ensure_ascii=False)) < len(json.dumps(raw, ensure_ascii=False))
    assert restore_observation_values(compact) == original
    assert raw == original
    assert [row["check_id"] for row in restore_observation_values(compact)["observations"]] == [
        row["check_id"] for row in original["observations"]]


@pytest.mark.parametrize("reserved", [TAG, SHORT_TAG, TEXT_TAG, TABLE, GUIDE])
def test_reserved_input_is_never_reinterpreted(reserved):
    raw = feedback()
    if reserved in {TAG, SHORT_TAG, TEXT_TAG}:
        raw["observations"][0]["observed"][reserved] = 0
    else:
        raw[reserved] = "user value"
    assert project_observation_values(raw) == raw


def test_small_unique_feedback_keeps_original_display():
    raw = {"observations": [{"check_id": "one", "expected": 0, "observed": 1}]}
    assert project_observation_values(raw) == raw


@pytest.mark.parametrize("bad_index", [-1, True, 999])
def test_invalid_references_fail_closed(bad_index):
    compact = project_observation_values(feedback())
    key = compact[GUIDE].get("reference_key", TAG)
    compact["observations"] = [{key: bad_index}]
    with pytest.raises(ValueError):
        restore_observation_values(compact)


def test_cyclic_table_and_tampered_values_are_rejected():
    compact = project_observation_values(feedback())
    compact[TABLE][0] = {compact[GUIDE].get("reference_key", TAG): 0}
    with pytest.raises(ValueError):
        restore_observation_values(compact)
    compact = project_observation_values(feedback())
    compact[TABLE][0] = "changed"
    with pytest.raises(ValueError):
        restore_observation_values(compact)


def test_normal_feedback_projection_uses_same_reversible_display():
    raw = feedback()
    compact = project_behavior_feedback(raw, "no parseable patch")
    assert GUIDE in compact
    assert restore_observation_values(compact) == raw


def test_public_expectation_protocol_is_not_reencoded():
    raw = feedback()
    for row in raw["observations"]:
        row["origin"] = "explicit_public_development_case"
    assert project_observation_values(raw) == raw


def test_recovery_budget_counts_the_same_projected_messages_sent_for_revision(monkeypatch):
    from dataclasses import asdict

    from src.mod_agent.local_entry import LocalOllamaInitialPatchAdapter, _patch_agent_context_json
    from src.mod_agent.proposal import behavior_feedback_view

    adapter = object.__new__(LocalOllamaInitialPatchAdapter)
    raw = feedback()
    previous = '{"changes":[]}'
    with monkeypatch.context() as original:
        original.setattr(behavior_feedback_view, "project_behavior_feedback", lambda value, _: value)
        raw_cost = adapter._revision_payload_bytes(previous, raw, None)
    cost = adapter._revision_payload_bytes(previous, raw, None)
    messages = adapter._revision_messages(previous, raw, message_type="patch_behavior_correction")
    assert cost < raw_cost
    assert cost == len(_patch_agent_context_json([asdict(message) for message in messages]).encode("utf-8"))
    visible = messages[-1].content["validator_feedback"]
    assert restore_observation_values(visible) == raw


@pytest.mark.parametrize("prefix", ["C:\\retained\\真实执行\\" + "deep-component\\" * 30, "a" * 120])
def test_distinct_strings_share_prefix_without_removing_any_path_or_suffix(prefix):
    raw = {"observations": [{"check_id": f"case-{i}", "expected": 0,
            "observed": {"input_path": prefix + f"{i}-case-" + "unique-file-name-" * 4 + "execution.json"}} for i in range(20)]}
    compact = project_observation_values(raw)
    assert compact[GUIDE]["version"] in {"inline_observation_values_v2", "inline_observation_values_v3"}
    assert TEXT_TAG in json.dumps(compact)
    assert restore_observation_values(compact) == raw
    assert len(json.dumps(compact, ensure_ascii=False)) < len(json.dumps(raw, ensure_ascii=False))
    bad = deepcopy(compact)
    bad["observations"] = [{TEXT_TAG: [False, "suffix"]}]
    with pytest.raises(ValueError, match="strings"):
        restore_observation_values(bad)


def test_invalid_column_layout_cannot_change_or_drop_fields():
    compact = project_observation_values(feedback())
    assert "columns" in compact[GUIDE]
    compact[GUIDE]["columns"].append("invented")
    with pytest.raises(ValueError, match="columns"):
        restore_observation_values(compact)


def test_legacy_encoding_keeps_short_reference_key_as_literal_data():
    import hashlib

    raw = feedback()
    raw["observations"][0]["observed"][SHORT_TAG] = 7
    encoded = deepcopy(raw)
    encoded[TABLE] = []
    encoded[GUIDE] = {"version": "inline_observation_values_v1", "original_observations_sha256":
        hashlib.sha256(json.dumps(raw["observations"], ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode("utf-8")).hexdigest()}
    assert restore_observation_values(encoded) == raw
