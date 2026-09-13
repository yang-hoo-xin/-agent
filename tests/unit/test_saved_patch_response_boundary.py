"""A retained tool-call body is not a complete native Patch, even with valid file refs."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.fresh_planning_continuation import run_fresh_patch_continuation
from src.mod_agent.proposal.code_generator import PatchGenerationError
from tests.unit.test_saved_patch_admission import saved_case


def test_tool_only_saved_response_cannot_enter_proposal_review_or_dry_run(tmp_path, monkeypatch):
    request, _, original, _, _ = saved_case(tmp_path, product_layout=True)
    journal = deepcopy(original)
    reported_plan = journal["factory_receipt"]["patch_agent_loop"]["behavior_evaluations"][0]["implementation_plan_ref"]
    plan = request.implementation_plan_ref
    document = ArtifactStore(request.artifact_store_root).semantic_read_immutable(plan)["data"]
    selected_binding = document["binding_registry"]["edit_bindings"][0]["binding_id"]
    assert reported_plan["artifact_hash"] == plan.artifact_hash
    body = json.dumps({"tool_calls": [{"function": {"name": "inspect_plan_binding_source",
        "arguments": {"binding_id": selected_binding}}}]}, ensure_ascii=False).encode("utf-8")
    response_path = tmp_path / "intermediate-tool-response.json"
    response_path.write_bytes(body)
    response = journal["factory_receipt"]["model_response"]
    response.update(path=str(response_path), output_sha256=hashlib.sha256(body).hexdigest(), output_utf8_bytes=len(body))
    source_path = tmp_path / "tool-only-attempt.json"
    source_path.write_text(json.dumps(journal, ensure_ascii=False), encoding="utf-8")
    selected = replace(request, attempt_id="tool-only-saved-check", saved_patch_selection={
        **request.saved_patch_selection,
        "source_attempt_ref": {"path": str(source_path), "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest()},
    })
    before = {str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    def forbidden(*args, **kwargs):
        pytest.fail("A tool-only source cannot execute a model, create a Proposal, or enter Dry-run.")
    monkeypatch.setattr(ArtifactStore, "write", forbidden)
    monkeypatch.setattr(ArtifactStore, "write_with_result", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("socket.socket.connect_ex", forbidden)
    with pytest.raises(PatchGenerationError) as caught:
        run_fresh_patch_continuation(selected, patch_change_factory=None, dry_run_factory=forbidden, max_model_calls=0)
    assert caught.value.diagnostics["failure_classification"] == "native_response_fields_invalid"
    assert caught.value.diagnostics["missing_fields"] == ["changes"]
    assert caught.value.diagnostics["unexpected_fields"] == ["tool_calls"]
    assert before == {str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
