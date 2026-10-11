"""Exact td2 byte-budget counterexample and lossless public model-view checks."""
import hashlib
import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest

from src.mod_agent.local_entry import LocalOllamaInitialPatchAdapter, _patch_agent_context_json
from src.mod_agent.proposal import behavior_feedback_view as view


def _recorded():
    return json.loads((Path(__file__).parents[1] /
        "fixtures/transfer_public_development_0928/td2_feedback_public.json").read_text(encoding="utf-8"))


def _bytes(messages):
    return len(_patch_agent_context_json([asdict(message) for message in messages]).encode("utf-8"))


def _messages(response, feedback):
    return LocalOllamaInitialPatchAdapter._revision_messages(
        response, feedback, message_type="patch_behavior_correction")


def _at(value, path):
    for key in path:
        value = value[key]
    return value


def _restore_observation(row, shared):
    restored = deepcopy(row)
    if restored.get("origin") == "explicit_public_development_case" and shared:
        restored.update(shared)
    if "expectations" in restored:
        expected = []
        for assertion in restored.pop("expectations"):
            actual = _at(restored["observed"], assertion["path"])
            target = deepcopy(actual)
            for delta in assertion["matches_observed_except"]:
                assert _at(actual, delta["path"]) == delta["observed"]
                if delta["path"]:
                    _at(target, delta["path"][:-1])[delta["path"][-1]] = deepcopy(delta["expected"])
                else:
                    target = deepcopy(delta["expected"])
            expected.append({"path": assertion["path"], "equals": target})
        restored["expected"] = expected
    return restored


def test_exact_td2_feedback_budget_failure_fits_without_changing_any_allowance(monkeypatch):
    recorded = _recorded()
    pairs = list(zip(recorded["responses"], recorded["feedbacks"]))
    with monkeypatch.context() as original:
        original.setattr(view, "project_behavior_feedback", lambda feedback, _response: feedback)
        old_bytes = [_bytes(_messages(response, feedback)) for response, feedback in pairs]
    assert old_bytes == recorded["recorded_feedback_message_bytes"] == [15674, 16318]
    fixed_cost = recorded["initial_feedback_bytes"] + recorded["source_observation_bytes"]
    assert fixed_cost + sum(old_bytes) == recorded["recorded_combined_bytes"] == 36339
    assert fixed_cost + sum(old_bytes) > recorded["limit"] == 30472
    new_bytes = [_bytes(_messages(response, feedback)) for response, feedback in pairs]
    assert new_bytes == [11821, 12465]
    assert fixed_cost + sum(new_bytes) == 28633 < recorded["limit"]


@pytest.mark.parametrize("index", [0, 1])
def test_public_facts_restore_exactly_and_code_uses_the_checked_literal(index):
    recorded = _recorded()
    raw, original = recorded["responses"][index], recorded["feedbacks"][index]
    unchanged = deepcopy(original)
    projected = view.project_behavior_feedback(original, raw)
    assert original == unchanged
    restored_rows = [_restore_observation(row, projected.get("public_development_provenance"))
        for row in projected["observations"]]
    assert restored_rows == original["observations"]
    assert projected["observations"][0] == original["observations"][0]
    by_binding = {row["edit_binding_id"]: row["after_text"] for row in json.loads(raw)["changes"]}
    for projected_file, original_file in zip(projected["working_code_view"]["files"], original["working_code_view"]["files"]):
        restored = deepcopy(projected_file)
        reference = restored["hunks"][0].pop("text_from_checked_patch")
        text = by_binding[reference["edit_binding_id"]]
        assert hashlib.sha256(text.encode()).hexdigest() == reference["after_text_sha256"] == original_file["raw_bytes_sha256"]
        restored["hunks"][0]["text"] = text
        assert restored == {key: value for key, value in original_file.items() if key != "unified_diff"}
    for key in original.keys() - {"working_code_view", "observations"}:
        assert projected[key] == original[key]
    message = _messages(raw, original)
    assert message[0].role == "assistant" and message[0].content == raw
    assert message[-1].content["validator_feedback"] == projected


@pytest.mark.parametrize("damage", ["partial", "bytes", "code_identity", "ambiguous_candidate", "non_native"])
def test_unproven_code_duplication_keeps_complete_working_view(damage):
    recorded = _recorded()
    raw, feedback = recorded["responses"][0], recorded["feedbacks"][0]
    if damage == "partial":
        feedback["working_code_view"]["files"][0]["complete"] = False
    elif damage == "bytes":
        feedback["working_code_view"]["files"][0]["raw_bytes_sha256"] = "0" * 64
    elif damage == "code_identity":
        feedback["working_code_view"]["code_sha256"] = "sha256:" + "0" * 64
    elif damage == "ambiguous_candidate":
        value = json.loads(raw)
        value["changes"].append(deepcopy(value["changes"][0]))
        raw = json.dumps(value)
    else:
        raw = "not a native Patch"
    assert view.project_behavior_feedback(feedback, raw)["working_code_view"] == feedback["working_code_view"]


def test_structural_and_type_differences_preserve_actual_errors_and_inputs():
    equal = {f"stable_{index}": "preservation value" for index in range(40)}
    actual = {**equal, "errors": ["OverflowException"], "value": True, "balance": -1}
    expected = {**equal, "errors": [], "value": 1, "balance": 8}
    row = {"origin": "explicit_public_development_case", "check_id": "public",
        "input": {"operation": "keep this exact input"}, "expected": [{"path": [], "equals": expected}],
        "observed": actual, "execution": {"completed": True, "exit_code": 0}}
    projected = view.project_behavior_feedback({"observations": [row]}, "{}")
    assert projected["observations"][0]["observed"] == actual
    differences = projected["observations"][0]["expectations"][0]["matches_observed_except"]
    boolean_difference = next(value for value in differences if value["path"] == ["value"])
    assert type(boolean_difference["expected"]) is int and type(boolean_difference["observed"]) is bool
    assert _restore_observation(projected["observations"][0], None) == row


def test_private_or_unknown_observations_are_not_reinterpreted():
    row = {"origin": "host_private", "input": "never promote", "expected": {"x": 3}, "observed": {"x": 2}}
    feedback = {"observations": [row], "failure_owner": "environment"}
    assert view.project_behavior_feedback(feedback, "{}") == feedback


@pytest.mark.parametrize("helper", ["proposal/behavior_feedback_view.py", "proposal/observation_value_refs.py", "evidence/reassessment.py", "request_patch_execution.py"])
def test_helper_only_drift_changes_worker_fingerprint(tmp_path, monkeypatch, helper):
    from src.mod_agent import model_qualification

    source_root = Path(model_qualification.__file__).resolve().parent
    for name in {*model_qualification._WORKER_FILES, helper}:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((source_root / name).read_bytes())
    monkeypatch.setattr(model_qualification, "__file__", str(tmp_path / "model_qualification.py"))
    before = model_qualification.worker_implementation_identity()
    path = tmp_path / helper
    path.write_bytes(path.read_bytes() + b"\n# controlled helper-only identity drift\n")
    after = model_qualification.worker_implementation_identity()
    assert before["implementation_sha256"] != after["implementation_sha256"]
    assert before["files"][helper] != after["files"][helper]
    assert {name for name in before["files"] if before["files"][name] != after["files"][name]} == {helper}



def _same_code_responses():
    code = "// 原样代码\n" + ("int value = 1;\r\n" * 180)
    earlier = {"changes": [{"edit_binding_id": "b", "rationale": "old explanation", "after_text": code}]}
    current = {"changes": [{"edit_binding_id": "b", "rationale": "new explanation", "after_text": code}]}
    return earlier, current


def test_visible_same_code_reference_keeps_new_rationale_and_exact_code():
    from src.libs.llm.agent_turn import AgentMessage
    old, current = _same_code_responses()
    messages = (AgentMessage(role="assistant", content=json.dumps(old)),)
    original = json.dumps(current)
    encoded = view.project_visible_patch_response(original, messages)
    assert encoded != original
    assert view.restore_visible_patch_response(encoded, messages) == current
    document = json.loads(encoded)
    assert document["changes"][0]["rationale"] == "new explanation"
    assert "after_text" not in document["changes"][0]
    assert document["changes"][0]["after_text_ref"]["earlier_assistant_patch"] == 1
    assert json.loads(messages[0].content) == old and json.loads(original) == current
    assert len(json.dumps(encoded).encode()) < len(json.dumps(original).encode())


@pytest.mark.parametrize("damage", ["source", "binding", "pointer", "extra", "rationale"])
def test_visible_code_reference_tampering_fails_expansion(damage):
    from src.libs.llm.agent_turn import AgentMessage
    old, current = _same_code_responses()
    messages = (AgentMessage(role="assistant", content=json.dumps(old)),)
    encoded = json.loads(view.project_visible_patch_response(json.dumps(current), messages))
    if damage == "source":
        old["changes"][0]["after_text"] += "changed"
        messages = (AgentMessage(role="assistant", content=json.dumps(old)),)
    elif damage == "binding":
        encoded["changes"][0]["edit_binding_id"] = "other"
    elif damage == "pointer":
        encoded["changes"][0]["after_text_ref"]["earlier_assistant_patch"] = 0
    elif damage == "extra":
        encoded["changes"][0]["after_text_ref"]["new_authority"] = True
    elif damage == "rationale":
        encoded["changes"][0]["rationale"] = "altered"
    with pytest.raises(ValueError):
        view.restore_visible_patch_response(json.dumps(encoded), messages)


def test_similar_code_and_ambiguous_binding_are_not_deduplicated():
    from src.libs.llm.agent_turn import AgentMessage
    old, current = _same_code_responses()
    original = json.dumps(current)
    old["changes"][0]["after_text"] += " "
    assert view.project_visible_patch_response(original, (AgentMessage(role="assistant", content=json.dumps(old)),)) == original
    old, current = _same_code_responses()
    old["changes"] *= 2
    assert view.project_visible_patch_response(original, (AgentMessage(role="assistant", content=json.dumps(old)),)) == original


def test_normal_behavior_correction_shares_code_but_keeps_current_feedback():
    from src.libs.llm.agent_turn import AgentMessage
    old, current = _same_code_responses()
    messages = (AgentMessage(role="assistant", content=json.dumps(old)),)
    feedback = {"status": "behavior_failed", "observations": [{"expected": [], "observed": ["unexpected"]}]}
    revisions = LocalOllamaInitialPatchAdapter._revision_messages(json.dumps(current), feedback,
        message_type="patch_behavior_correction", visible_messages=messages)
    assert len(revisions) == 2
    assert view.restore_visible_patch_response(revisions[0].content, messages) == current
    assert revisions[1].content["validator_feedback"] == {**feedback, "observations": feedback["observations"]}
