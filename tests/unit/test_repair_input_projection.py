"""Native Repair references preserve exact current bytes and input/output boundaries."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from src.libs.llm.agent_turn import AgentMessage, AgentResponseFormat, AgentTurnRequest
from src.mod_agent.execution.patch_apply import materialize_exact_text_patch
from src.mod_agent.local_entry import LocalOllamaInitialPatchAdapter, _patch_agent_context_json
from src.mod_agent.proposal.code_generator import PatchGenerationError, validate_patch_submission
from src.mod_agent.proposal.patch_agent_loop import (
    PatchAgentLoopPolicy,
    PlanBoundSourceInspector,
    run_patch_agent_loop,
)
from src.mod_agent.proposal.repair_input_projection import (
    RepairInputProjectionError,
    project_native_repair_input,
)
from src.mod_agent.proposal.working_view import build_materialized_patch_view
from tests.unit.test_patch_agent_loop import _response, _ScriptedClient


def _fixture(tmp_path):
    method = "    string A() {\r\n" + "".join(
        f"        // stable observed input {index:02d} and preserved unrelated behavior\r\n" for index in range(12)
    ) + '        return "旧🧭";\r\n    }\r\n'
    before = {"One.cs": "\ufeffclass One {\r\n" + method + "    int B() => 2;\r\n}\r\n",
              "Two.cs": "class Two {\n    int C() => 3;\n}\n"}
    changes = []
    bindings = []
    contexts = {}
    history = {"changes": []}
    units = [("edit_a", "One.cs", method, method.replace('return "旧🧭";', 'var value = "新🧭";\r\n        return value;')),
             ("edit_b", "One.cs", "    int B() => 2;\r\n", "    int B() => 4;\r\n"),
             ("edit_c", "Two.cs", "    int C() => 3;\n", "    int C() => 5;\n")]
    for path, text in before.items():
        (tmp_path / path).write_bytes(text.encode("utf-8"))
    for binding_id, path, old, new in units:
        position = before[path].index(old)
        start = before[path][:position].count("\n") + 1
        span = {"start_line": start, "end_line": start + old.rstrip("\r\n").count("\n")}
        binding = {"binding_id": binding_id, "canonical_target_path": path,
            "source_hash": hashlib.sha256(before[path].encode()).hexdigest(), "target_span": span}
        bindings.append(binding)
        contexts[binding_id] = {**binding, "source_excerpt": old}
        changes.append({"change_id": binding_id, "edit_binding_id": binding_id,
            "patch": {"kind": "exact_text_replace", "before_text": old, "after_text": new, "expected_occurrences": 1}})
        history["changes"].append({"edit_binding_id": binding_id, "after_text": new,
            "rationale": "Preserve unrelated source.", "rollback_hint": "Restore the bound source."})
    materialized = materialize_exact_text_patch(workspace_root=tmp_path, diff_intent=changes,
        implementation_plan={"binding_registry": {"edit_bindings": bindings}})
    view = build_materialized_patch_view(materialized, context_radius_lines=64)
    schema = {"type": "object", "additionalProperties": False, "required": ["changes"], "properties": {
        "changes": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "required": ["edit_binding_id", "after_text", "rationale", "rollback_hint"], "properties": {
                key: {"type": "string"} for key in ("edit_binding_id", "after_text", "rationale", "rollback_hint")}}}}}
    native = {"request": "Retain all prior behavior while making the bounded change.",
        "edit_binding_contexts": contexts, "required_output_schema": schema}
    feedback = {"message_type": "patch_repair_context", "revision_semantics": "complete_replacement_relative_to_B0",
        "required_action": "B0 is unchanged source shown initially and by source tools. Keep every original requirement.",
        "validator_feedback": {"observations": [{"input": {"initial": [1, 2], "steps": ["one", "two"]},
            "expected": True, "observed": False}], "working_code_view": view}}
    messages = (AgentMessage("system", "Return the original strict JSON output schema."),
        AgentMessage("user", json.dumps(native)), AgentMessage("assistant", json.dumps(history, ensure_ascii=True, indent=2)),
        AgentMessage("user", feedback))
    identity = {"baseline_sha256": materialized.baseline_sha256, "code_sha256": materialized.code_sha256,
                "files": sorted(materialized.files)}
    return messages, identity, native, history, view


def test_two_files_and_shifted_later_edit_expand_exact_current_bytes(tmp_path):
    messages, identity, native, history, view = _fixture(tmp_path)
    projection = project_native_repair_input(messages, current_code_identity=identity)
    assert projection is not None
    projection.validate(projection.projected)
    projected_history = json.loads(projection.projected[2].content)
    assert projected_history["input_only"] is True
    assert all("after_text_ref" in row and "after_text" not in row for row in projected_history["changes"])
    later = projected_history["changes"][1]["after_text_ref"]
    current = view["files"][0]["hunks"][0]["text"].encode()
    assert current[later[0]:later[0] + later[1]].decode() == history["changes"][1]["after_text"]
    assert json.loads(projection.projected[1].content)["required_output_schema"] == native["required_output_schema"]
    assert projection.projected[3].content["validator_feedback"]["observations"] == messages[3].content["validator_feedback"]["observations"]
    assert [file["hunks"] for file in projection.projected[3].content["validator_feedback"]["working_code_view"]["files"]] == [file["hunks"] for file in view["files"]]
    assert projection.metadata["raw_response_sha256"] == hashlib.sha256(messages[2].content.encode()).hexdigest()
    assert projection.repair_message_bytes == len(_patch_agent_context_json([asdict(row) for row in projection.projected[2:]]).encode())


@pytest.mark.parametrize("damage", ["missing_ref", "wrong_version", "changed_anchor", "wrong_file_hash", "changed_B0_span", "wrong_offset"])
def test_invalid_projected_reference_is_rejected(damage, tmp_path):
    messages, identity, _, _, _ = _fixture(tmp_path)
    projection = project_native_repair_input(messages, current_code_identity=identity)
    damaged = list(deepcopy(projection.projected))
    history = json.loads(damaged[2].content)
    if damage == "missing_ref":
        del history["changes"][0]["after_text_ref"]
    elif damage == "wrong_version":
        history["Ck"] = "sha256:" + "0" * 64
    elif damage in ("changed_anchor", "wrong_file_hash"):
        file = damaged[3].content["validator_feedback"]["working_code_view"]["files"][0]
        if damage == "changed_anchor":
            file["hunks"][0]["text"] += "changed"
        else:
            file["raw_bytes_sha256"] = "0" * 64
    elif damage == "changed_B0_span":
        native = json.loads(damaged[1].content)
        native["edit_binding_contexts"]["edit_a"]["target_span"]["start_line"] = 99
        damaged[1] = replace(damaged[1], content=json.dumps(native))
    else:
        history["changes"][0]["after_text_ref"][0] += 1
    damaged[2] = replace(damaged[2], content=json.dumps(history))
    with pytest.raises(RepairInputProjectionError):
        projection.validate(damaged)


def test_input_reference_cannot_be_returned_as_final_patch(tmp_path):
    messages, identity, native, _, _ = _fixture(tmp_path)
    projection = project_native_repair_input(messages, current_code_identity=identity)
    history = json.loads(projection.projected[2].content)
    with pytest.raises(PatchGenerationError):
        validate_patch_submission(json.dumps({"changes": history["changes"]}), native["required_output_schema"])


def test_fresh_legacy_and_partial_view_keep_original_representation(tmp_path):
    messages, identity, _, _, _ = _fixture(tmp_path)
    assert project_native_repair_input(messages[:2], current_code_identity=None) is None
    legacy = list(messages)
    legacy[2] = AgentMessage("assistant", '{"changes":[{"patch":{"after_text":"legacy"}}]}')
    assert project_native_repair_input(tuple(legacy), current_code_identity=identity) is None
    partial = list(deepcopy(messages))
    partial[3].content["validator_feedback"]["working_code_view"]["files"][0]["complete"] = False
    assert project_native_repair_input(tuple(partial), current_code_identity=identity) is None


def test_projection_preserves_logical_history_for_resume(tmp_path):
    messages, identity, _, _, _ = _fixture(tmp_path)
    projection = project_native_repair_input(messages, current_code_identity=identity)
    request = AgentTurnRequest(messages=(*messages, AgentMessage("user", {"message_type": "patch_agent_loop_state"})))
    sent = projection.project_request(request)
    assert request.messages[:4] == messages
    assert sent.messages[:4] == projection.projected
    assert sent.messages[4:] == request.messages[4:]


def test_changed_current_bytes_cannot_keep_old_aggregate_identity(tmp_path):
    messages, identity, _, _, _ = _fixture(tmp_path)
    changed = list(deepcopy(messages))
    file = changed[3].content["validator_feedback"]["working_code_view"]["files"][1]
    file["hunks"][0]["text"] = file["hunks"][0]["text"].replace("class Two", "class Bad")
    file["raw_bytes_sha256"] = hashlib.sha256(file["hunks"][0]["text"].encode()).hexdigest()
    with pytest.raises(RepairInputProjectionError):
        project_native_repair_input(tuple(changed), current_code_identity=identity)


@pytest.mark.parametrize("field", ["schema_version", "source_role", "coordinate_system"])
def test_unknown_view_semantics_cannot_supply_current_code_references(tmp_path, field):
    messages, identity, _, _, _ = _fixture(tmp_path)
    changed = list(deepcopy(messages))
    changed[3].content["validator_feedback"]["working_code_view"][field] = "other_version"
    with pytest.raises(RepairInputProjectionError):
        project_native_repair_input(tuple(changed), current_code_identity=identity)


def test_bom_prefix_is_not_invented_at_an_interior_replacement(tmp_path):
    messages, identity, _, history, _ = _fixture(tmp_path)
    history["changes"][1]["after_text"] = "\ufeff" + history["changes"][1]["after_text"]
    changed = (*messages[:2], AgentMessage("assistant", json.dumps(history)), messages[3])
    with pytest.raises(RepairInputProjectionError):
        project_native_repair_input(changed, current_code_identity=identity)


def _loop_fixture(tmp_path):
    messages, identity, native, _, _ = _fixture(tmp_path)
    projection = project_native_repair_input(messages, current_code_identity=identity)
    policy = PatchAgentLoopPolicy(require_source_inspection=False, finalize_after_first_observation=False)
    bindings = [{key: value for key, value in row.items() if key != "source_excerpt"}
                for row in native["edit_binding_contexts"].values()]
    inspector = PlanBoundSourceInspector(workspace_root=tmp_path, policy=policy,
        implementation_plan={"binding_registry": {"edit_bindings": bindings},
            "proposed_changes": [{"change_id": row["binding_id"], "edit_binding_id": row["binding_id"]} for row in bindings]})
    return messages, native, projection, policy, inspector


def test_loop_records_projected_request_but_retains_logical_history_and_no_fake_reads(tmp_path):
    messages, native, projection, policy, inspector = _loop_fixture(tmp_path)
    client = _ScriptedClient([_response(turn=1, content=messages[2].content)])
    result = run_patch_agent_loop(client=client, initial_messages=messages,
        final_response_format=AgentResponseFormat(name="native", description="Unchanged output schema.", schema=native["required_output_schema"]),
        source_inspector=inspector, policy=policy, consumed_observation_bytes=projection.repair_message_bytes,
        request_projection=projection.project_request)
    assert result.completed and len(client.requests) == 1
    assert client.requests[0].messages[:4] == projection.projected
    assert result.final_request.messages[:4] == messages
    assert result.tool_rounds_used == 0 and not result.observation_trace
    assert client.requests[0].messages[-1].content["budget_state"]["observation_bytes_used"] == projection.repair_message_bytes
    owner = object.__new__(LocalOllamaInitialPatchAdapter)
    owner._repair_input_projection = projection
    owner.patch_agent_loop_policy = replace(policy, reuse_covered_source_observations=True)
    feedback = {"observations": [{"expected": True, "observed": False}]}
    additions = owner._revision_messages(messages[2].content, feedback, message_type="patch_behavior_correction",
        visible_messages=owner._model_visible_messages(result.final_request.messages))
    assert len(additions) == 2
    assert additions[0].content == messages[2].content
    assert "previous_response_ref" not in additions[1].content
    assert owner._revision_payload_bytes(messages[2].content, feedback, result.final_request) == len(
        _patch_agent_context_json([asdict(message) for message in additions]).encode())


def test_invalid_projection_stops_before_recording_client_or_request_budget(tmp_path):
    messages, native, projection, policy, inspector = _loop_fixture(tmp_path)
    client = _ScriptedClient([])
    def invalid(request):
        sent = projection.project_request(request)
        rows = list(deepcopy(sent.messages))
        rows[3].content["validator_feedback"]["working_code_view"]["files"].pop()
        projection.validate(rows)
    result = run_patch_agent_loop(client=client, initial_messages=messages,
        final_response_format=AgentResponseFormat(name="native", description="Unchanged output schema.", schema=native["required_output_schema"]),
        source_inspector=inspector, policy=policy, request_projection=invalid)
    assert not client.requests
    assert result.model_turns_used == 0 and result.tool_rounds_used == 0
    assert result.termination["code"] == "PATCH_REPAIR_INPUT_REFERENCE_INVALID"
