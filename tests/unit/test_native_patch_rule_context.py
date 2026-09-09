"""Compact fixed rules preserve native data and the existing authority contracts.

The policy allowance comes from the retained developer request with SHA-256
94f571639f7d13d751e521ba0f994d230a168b486953846d6c2f66314c75aa12.
That private request stays outside repository fixtures; only public owned source
definitions and synthetic observations are used here.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from scripts import prepare_patch_sft_data as data
from src.libs.llm import ChatResponse
from src.mod_agent.local_entry import (
    LocalOllamaInitialPatchAdapter,
    _patch_agent_initial_messages,
    _restore_patch_agent_context,
)
from src.mod_agent.proposal import LLMExactPatchGenerator, PatchGenerationError
from src.mod_agent.proposal.code_generator import _patch_system_prompt
from src.mod_agent.proposal.patch_agent_loop import (
    PatchAgentLoopPolicy,
    PlanBoundSourceInspector,
    _source_tool_definition,
)
from src.mod_agent.proposal.working_view import build_materialized_patch_view
from tests.unit.test_patch_code_generator import _large_projection_fixture


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Native rule tests must not use a real model or network.")
    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("socket.socket.connect_ex", forbidden)


@pytest.mark.parametrize("case_id", ["paging_partial_tail", "snapshot_nested_tags"])
def test_owned_native_context_keeps_source_failed_code_and_full_view(tmp_path, case_id):
    definition = next(row for row in data.load_tasks().TASKS if row["case_id"] == case_id)
    workspace, plan, generator, prepared, _ = data.prepare_contract(definition, tmp_path / "case")
    raw, generated, materialized = data.structured_output(
        definition, "C1", tmp_path / "case", plan, generator, prepared, workspace)
    initial = _patch_agent_initial_messages(prepared.messages)
    projected = _restore_patch_agent_context(json.loads(initial[1].content))
    projected.pop("patch_agent_context_policy")
    assert projected == json.loads(prepared.messages[1].content)
    policy = PatchAgentLoopPolicy(require_source_inspection=False, finalize_after_first_observation=False,
        enable_supporting_reads=True, allow_batched_reads=True, reuse_covered_source_observations=True,
        max_tool_rounds=6, max_total_model_turns=5)
    inspector = PlanBoundSourceInspector(workspace_root=workspace, implementation_plan=plan, policy=policy)
    tool = _source_tool_definition(inspector)
    # The observed 13,710-byte request has 10,664 bytes outside these two strings.
    assert len(initial[0].content.encode()) + len(tool.description.encode()) <= 1624
    assert tool.parameters == {"type": "object", "additionalProperties": False,
        "required": ["binding_id"], "properties": {"binding_id": {
            "type": "string", "enum": list(inspector.available_read_binding_ids)}}}
    assert tool.strict is True
    view = build_materialized_patch_view(materialized, context_radius_lines=policy.context_radius_lines)
    feedback = {"status": "behavior_failed", "generated_changes_sha256": "a" * 64,
        "observations": [{"check_id": "offline_input_preserved", "input": {"case_id": case_id,
            "initial_state": {"source": "owned fixture"}, "operations": [{"step": 1, "action": "fixture"}]},
            "expected": "original expectation", "observed": "original failed observation"}],
        "working_code_view": view}
    before = deepcopy(feedback)
    recovery = LocalOllamaInitialPatchAdapter._revision_messages(raw, feedback, message_type="patch_repair_context")
    assert recovery[0].content == raw and recovery[1].content["validator_feedback"] == before
    assert feedback == before
    assert materialized.files["OwnedTraining/Subject.cs"] == definition["sources"]["C1"].encode()
    assert all(file["complete"] and file["unified_diff"] and file["hunks"] for file in view["files"])
    assert Path(workspace, "OwnedTraining/Subject.cs").read_bytes() == definition["sources"]["B0"].encode()
    assert generator.materialize_prepared_native(prepared, ChatResponse(content=raw, model="offline")).changes == generated.changes


def test_multiple_bindings_keep_native_schema_and_reject_added_authority():
    fixture = _large_projection_fixture()
    generator = LLMExactPatchGenerator(None)
    prepared = generator.prepare_native_contract(
        user_request=fixture["user_request"], evidence_items=fixture["evidence_items"],
        binding_registry=fixture["binding_registry"], constraints=fixture["constraints"],
        required_change_units=fixture["required_change_units"],
        required_validation_by_binding=fixture["required_validation_by_binding"])
    expected_ids = [row["edit_binding_id"] for row in fixture["required_change_units"]]
    assert len(expected_ids) > 1
    schema = prepared.response_schema["properties"]["changes"]
    assert schema["minItems"] == schema["maxItems"] == len(expected_ids)
    assert schema["items"]["required"] == ["edit_binding_id", "rationale", "rollback_hint", "after_text"]
    assert schema["items"]["additionalProperties"] is False
    result = generator.materialize_prepared_native(prepared,
        ChatResponse(content=json.dumps(fixture["response"]), model="offline"))
    assert [row["edit_binding_id"] for row in result.changes] == expected_ids
    invalid = deepcopy(fixture["response"])
    invalid["changes"][0]["path"] = "outside-the-authorized-binding.cs"
    with pytest.raises(PatchGenerationError) as raised:
        generator.materialize_prepared_native(prepared, ChatResponse(content=json.dumps(invalid), model="offline"))
    assert raised.value.diagnostics["failure_classification"] == "native_response_fields_invalid"


@pytest.mark.parametrize("plan_bound,digest", [
    (False, "039881a18a6a9f2fbfc466c6b66b292a753105d8a75f89874e82a4d26297ed4c"),
    (True, "32a04e4b81a40bd66bcff30906ab32e5a120239ef96a1cb8e22cb41a09636511"),
])
def test_legacy_system_prompts_remain_byte_identical(plan_bound, digest):
    text = _patch_system_prompt(require_native_schema=False, plan_bound_response=plan_bound)
    assert hashlib.sha256(text.encode()).hexdigest() == digest


@pytest.mark.parametrize("reuse,deduplicate", [(False, False), (False, True), (True, False)])
def test_source_description_retains_policy_specific_read_costs(reuse, deduplicate):
    from types import SimpleNamespace

    policy = PatchAgentLoopPolicy(reuse_covered_source_observations=reuse,
        deduplicate_source_excerpts=deduplicate)
    tool = _source_tool_definition(SimpleNamespace(policy=policy, available_read_binding_ids=("bound_a",)))
    assert "Read existing registered content and return it here; no Evidence/Coverage or Plan reassessment." in tool.description
    assert "original B0 (no generated edits)" in tool.description
    assert "API bindings return full saved Evidence, not live inspection" in tool.description
    assert ("cost 0 reads" in tool.description) is reuse
    assert ("Each dispatched binding read costs one read" in tool.description) is (not reuse)
    assert ("excerpt_ref" in tool.description) is (reuse or deduplicate)
    assert ("source_excerpt_span" in tool.description) is reuse


@pytest.mark.parametrize("modules", [
    ("src.mod_agent.local_entry", "src.mod_agent.proposal.code_generator", "src.mod_agent.proposal.patch_agent_loop"),
    ("src.mod_agent.proposal.code_generator", "src.mod_agent.proposal.patch_agent_loop", "src.mod_agent.local_entry"),
])
def test_rule_owners_import_in_fresh_processes(modules):
    program = "\n".join("import " + name for name in modules)
    result = subprocess.run([sys.executable, "-B", "-c", program],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
