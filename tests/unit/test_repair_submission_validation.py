from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.libs.llm import BaseLLM, ChatResponse, Message
from src.mod_agent.execution import patch_apply
from src.mod_agent.proposal import code_generator as codegen


class _LocalResponse(BaseLLM):
    def __init__(self, content: str) -> None:
        self.content = content

    def chat(self, messages: list[Message], trace=None, **kwargs) -> ChatResponse:
        return ChatResponse(content=self.content, model="offline-submission-test")


def _inputs(before: str) -> dict:
    source_hash = hashlib.sha256(before.encode()).hexdigest()
    span = {"start_line": 1, "end_line": len(before.splitlines())}
    return {
        "user_request": "Return the requested value while preserving other source.",
        "constraints": [],
        "evidence_items": [{
            "evidence_id": "ev_001", "source_path": "Subject.cs",
            "source_hash": source_hash, "symbol": "Subject.Apply",
            "span": span, "excerpt": before,
        }],
        "binding_registry": {"edit_bindings": [{
            "binding_id": "edit_binding_001", "evidence_id": "ev_001",
            "canonical_target_path": "Subject.cs", "source_hash": source_hash,
            "target_symbol": "Subject.Apply", "target_span": span,
        }]},
        "required_change_units": [{
            "change_id": "change_001", "change_type": "modify_behavior",
            "edit_binding_id": "edit_binding_001", "supporting_binding_ids": [],
            "operation": "minimal_evidence_bound_change",
            "rationale": "Implement the bounded request.",
            "expected_validation": ["compile or static validation"],
        }],
    }


def _payload(after: str) -> dict:
    return {"changes": [{
        "edit_binding_id": "edit_binding_001", "after_text": after,
        "rationale": "Implement the bounded request.", "rollback_hint": "Restore source.",
    }]}


def _generate(before: str, payload: dict):
    generator = codegen.LLMExactPatchGenerator(_LocalResponse(json.dumps(payload)))
    return generator.generate(
        **_inputs(before), require_native_schema=True, provider_request_recorder=lambda _: None,
    )


@pytest.mark.parametrize("prepared", [False, True])
@pytest.mark.parametrize("failure", ["no_op", "header"])
def test_complete_submission_text_errors_retain_recoverable_type(
    failure: str, prepared: bool,
) -> None:
    before = "using System;\nclass Subject { public int Apply() => 1; }\n"
    after = before if failure == "no_op" else "class Subject { public int Apply() => 2; }\n"
    content = json.dumps(_payload(after))
    generator = codegen.LLMExactPatchGenerator(_LocalResponse(content))
    with pytest.raises(codegen.PatchGenerationError) as caught:
        if prepared:
            contract = generator.prepare_native_contract(**_inputs(before))
            generator.materialize_prepared_native(
                contract, ChatResponse(content=content, model="offline-submission-test"),
            )
        else:
            generator.generate(
                **_inputs(before), require_native_schema=True,
                provider_request_recorder=lambda _: None,
            )

    assert type(caught.value).__name__ == "PatchSubmissionValidationError"
    assert caught.value.diagnostic_content == content
    assert caught.value.diagnostics["failure_classification"] == {
        "no_op": "native_after_text_not_replacement",
        "header": "csharp_file_header_usings_removed",
    }[failure]
    assert caught.value.diagnostics["binding_id"] == "edit_binding_001"


@pytest.mark.parametrize("violation", ["unknown_binding", "duplicate", "missing_field", "extra_path"])
def test_noop_does_not_mask_hard_submission_identity_failures(violation: str) -> None:
    before = "class Subject { public int Apply() => 1; }\n"
    payload = _payload(before)
    if violation == "unknown_binding":
        payload["changes"].append({**payload["changes"][0], "edit_binding_id": "unknown"})
    elif violation == "duplicate":
        payload["changes"].append(dict(payload["changes"][0]))
    elif violation == "missing_field":
        payload["changes"].append({"edit_binding_id": "edit_binding_001"})
    else:
        payload["changes"].append({**payload["changes"][0], "path": "Other.cs"})
    with pytest.raises(codegen.PatchGenerationError) as caught:
        _generate(before, payload)
    assert type(caught.value) is codegen.PatchGenerationError
    assert caught.value.diagnostics["failure_classification"] != "native_after_text_not_replacement"


@pytest.mark.parametrize("content", ['{"changes":', "", '{"changes": [{"edit_binding_id": "edit_binding_001"}]}'])
def test_incomplete_submission_remains_hard_at_materializer(content: str) -> None:
    before = "class Subject { public int Apply() => 1; }\n"
    generator = codegen.LLMExactPatchGenerator(_LocalResponse(content))
    with pytest.raises(codegen.PatchGenerationError) as caught:
        generator.generate(
            **_inputs(before), require_native_schema=True, provider_request_recorder=lambda _: None,
        )
    assert type(caught.value) is codegen.PatchGenerationError


def test_prepared_schema_identity_drift_is_hard_before_noop() -> None:
    before = "class Subject { public int Apply() => 1; }\n"
    content = json.dumps(_payload(before))
    generator = codegen.LLMExactPatchGenerator(_LocalResponse(content))
    contract = generator.prepare_native_contract(**_inputs(before))
    with pytest.raises(codegen.PatchGenerationError) as caught:
        generator.materialize_prepared_native(
            replace(contract, schema_sha256="0" * 64),
            ChatResponse(content=content, model="offline-submission-test"),
        )
    assert type(caught.value) is codegen.PatchGenerationError


def _materialized(tmp_path: Path, before: str, after: str, *, change_plan=None):
    (tmp_path / "Subject.cs").write_bytes(before.encode())
    plan = {"binding_registry": _inputs(before)["binding_registry"]}
    if change_plan:
        change_plan(plan)
    changes = [{
        "change_id": "change_001", "edit_binding_id": "edit_binding_001",
        "patch": {"kind": "exact_text_replace", "before_text": before,
                  "after_text": after, "expected_occurrences": 1},
    }]
    materialized = patch_apply.materialize_exact_text_patch(
        workspace_root=tmp_path, diff_intent=changes, implementation_plan=plan,
    )
    return materialized, plan, changes


def test_three_added_whitespace_lines_match_original_dry_run_standard(tmp_path: Path) -> None:
    before = "class Subject {\n    public int Apply() => 1;\n}\n"
    after = "class Subject {  \n    public int Apply() => 2;\t\n} \n"
    materialized, plan, changes = _materialized(tmp_path, before, after)
    with pytest.raises(codegen.PatchGenerationError) as caught:
        patch_apply.validate_materialized_patch_submission(materialized)
    assert type(caught.value).__name__ == "PatchSubmissionValidationError"
    assert caught.value.diagnostics["failure_classification"] == "added_diff_trailing_whitespace"
    assert caught.value.diagnostics["added_trailing_whitespace_count"] == 3
    with pytest.raises(patch_apply.PatchApplyError, match="3 added line"):
        patch_apply.ExactTextPatchApplier().run(
            workspace_root=tmp_path,
            proposal={"proposal_id": "proposal_001", "diff_intent": changes},
            implementation_plan=plan,
            review={"allowed_next_stage": "dry_run_apply"}, allow_write=False,
        )
    assert materialized.files["Subject.cs"] == after.encode()
    assert (tmp_path / "Subject.cs").read_bytes() == before.encode()


@pytest.mark.parametrize("prefix", ["", "\ufeff"])
def test_unchanged_old_whitespace_is_not_a_new_diff_error(tmp_path: Path, prefix: str) -> None:
    before = prefix + "class Subject {  \r\n    public int Apply() => 1;\r\n}\r\n"
    after = prefix + "class Subject {  \r\n    public int Apply() => 2;\r\n}\r\n"
    materialized, _, _ = _materialized(tmp_path, before, after)
    patch_apply.validate_materialized_patch_submission(materialized)
    assert materialized.files["Subject.cs"] == after.encode()


@pytest.mark.parametrize("violation", ["source_hash", "span", "path"])
def test_live_authority_fault_is_hard_before_diff_feedback(tmp_path: Path, violation: str) -> None:
    before = "class Subject { public int Apply() => 1; }\n"
    after = "class Subject { public int Apply() => 2; }  \n"

    def change_plan(plan):
        binding = plan["binding_registry"]["edit_bindings"][0]
        if violation == "source_hash":
            binding["source_hash"] = "0" * 64
        elif violation == "span":
            binding["target_span"] = {"start_line": 2, "end_line": 2}
        else:
            binding["canonical_target_path"] = "../Subject.cs"

    with pytest.raises((patch_apply.PatchApplyError, ValueError)):
        _materialized(tmp_path, before, after, change_plan=change_plan)
