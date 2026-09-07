from __future__ import annotations

import json

import pytest

from src.mod_agent.proposal.code_generator import (
    PatchGenerationError,
    _patch_response_schema,
    validate_patch_submission,
    validate_patch_submission_schema,
)


def _submission() -> dict[str, object]:
    return {
        "changes": [
            {
                "edit_binding_id": "edit_binding_001",
                "rationale": "Preserve the existing configuration behavior.",
                "rollback_hint": "Restore the bound source.",
                "after_text": "public bool Enabled => false;\r\n",
            }
        ]
    }


def test_explanation_followed_by_json_is_not_extracted_as_a_submission() -> None:
    raw = "The changes are ready.\n" + json.dumps(_submission())
    with pytest.raises(PatchGenerationError) as raised:
        validate_patch_submission(raw, _patch_response_schema({"edit_binding_001"}))
    assert raised.value.diagnostics["failure_classification"] == "malformed_structured_output"
    assert raised.value.diagnostics["json_error_line"] == 1
    assert raised.value.diagnostics["json_error_column"] == 1
    assert "public bool" not in str(raised.value)


def test_missing_required_field_identifies_its_path_without_copying_source() -> None:
    submission = _submission()
    del submission["changes"][0]["rollback_hint"]
    with pytest.raises(PatchGenerationError) as raised:
        validate_patch_submission(
            json.dumps(submission), _patch_response_schema({"edit_binding_001"})
        )
    assert raised.value.diagnostics["failure_classification"] == "patch_submission_schema_violation"
    assert raised.value.diagnostics["field_path"] == ["changes", 0]
    assert raised.value.diagnostics["schema_constraint"] == "required"
    assert "rollback_hint" in str(raised.value)
    assert "public bool" not in str(raised.value)


def test_existing_schema_accepts_submission_without_altering_inputs() -> None:
    submission = _submission()
    schema = _patch_response_schema({"edit_binding_001"}, required_change_count=1)
    schema_before = json.dumps(schema, sort_keys=True)
    raw = "\n  " + json.dumps(submission, ensure_ascii=False, indent=2) + "\n"
    raw_before = raw
    validate_patch_submission_schema(schema)
    assert validate_patch_submission(raw, schema) == submission
    assert raw == raw_before
    assert json.dumps(schema, sort_keys=True) == schema_before


@pytest.mark.parametrize(
    ("field", "replacement", "constraint"),
    [
        ("edit_binding_id", "edit_binding_outside", "enum"),
        ("after_text", 42, "type"),
        ("after_text", "", "minLength"),
    ],
)
def test_existing_schema_reports_exact_field_and_constraint(
    field: str, replacement: object, constraint: str
) -> None:
    submission = _submission()
    submission["changes"][0][field] = replacement
    with pytest.raises(PatchGenerationError) as raised:
        validate_patch_submission(
            json.dumps(submission), _patch_response_schema({"edit_binding_001"})
        )
    assert raised.value.diagnostics["field_path"] == ["changes", 0, field]
    assert raised.value.diagnostics["schema_constraint"] == constraint
    assert "public bool" not in str(raised.value)


def test_schema_errors_never_echo_business_code_in_feedback() -> None:
    source = "PRIVATE_IMPLEMENTATION_BODY" * 100
    schema = {"type": "object", "properties": {"code": {"type": "integer"}}}
    with pytest.raises(PatchGenerationError) as raised:
        validate_patch_submission(json.dumps({"code": source}), schema)
    assert "PRIVATE_IMPLEMENTATION_BODY" not in str(raised.value)
    assert "PRIVATE_IMPLEMENTATION_BODY" not in json.dumps(raised.value.diagnostics)
    assert len(str(raised.value)) < 250


@pytest.mark.parametrize("raw", ["[]", "null", '"plain text"'])
def test_non_object_submissions_are_model_format_errors(raw: str) -> None:
    with pytest.raises(PatchGenerationError) as raised:
        validate_patch_submission(raw, {"type": "object"})
    assert raised.value.diagnostics["failure_classification"] == "malformed_structured_output"


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "not_a_schema_type"},
        {"type": "object", "required": "changes"},
        {"$schema": ["invalid"], "type": "object"},
        {"$schema": "https://invalid.test/unknown-dialect", "type": "object"},
    ],
)
def test_invalid_schema_is_configuration_failure_before_content_is_parsed(schema) -> None:
    with pytest.raises(ValueError):
        validate_patch_submission_schema(schema)
    with pytest.raises(ValueError):
        validate_patch_submission("not json either", schema)


def test_simplified_schema_is_used_directly_without_imposing_patch_fields() -> None:
    schema = {"type": "object", "required": ["answer"]}
    assert validate_patch_submission('{"answer": 7}', schema) == {"answer": 7}


def test_local_schema_references_work_without_remote_retrieval() -> None:
    schema = {
        "type": "object",
        "$defs": {"text": {"type": "string"}},
        "properties": {"answer": {"$ref": "#/$defs/text"}},
    }
    assert validate_patch_submission('{"answer":"ready"}', schema) == {"answer": "ready"}


def test_remote_schema_reference_is_configuration_failure_without_network(monkeypatch) -> None:
    import urllib.request

    def forbid_remote(*args, **kwargs):
        raise AssertionError("Submission validation must not make network requests.")

    monkeypatch.setattr(urllib.request, "urlopen", forbid_remote)
    schema = {"$ref": "https://invalid.test/remote-schema"}
    with pytest.raises(ValueError, match="unresolved reference"):
        validate_patch_submission("{}", schema)
