"""Make omitted mandatory input actionable without completing it for the model."""
from copy import deepcopy

import pytest

from src.mod_agent.evidence.requirement_coverage import (
    RequirementCoverageProjectionError,
    requirement_input_obligation_model_view,
)
from src.mod_agent.evidence.requirement_coverage_provider import (
    StructuredModelRequirementCoverageProvider,
)
from tests.unit.test_requirement_coverage import _feature_data, _model_projection, _projection


def test_correction_highlights_required_evidence_without_inventing_its_answer():
    feature = _feature_data()
    valid = _model_projection(_projection())
    incomplete = deepcopy(valid)
    incomplete["requirements"] = [row for row in incomplete["requirements"]
                                  if row["input_obligation_indexes"] != [3]]
    calls = []

    def complete(role, payload, _schema):
        calls.append((role, deepcopy(payload)))
        if role == "requirement_projection":
            return deepcopy(incomplete)
        repairs = payload["unaccounted_input_obligations"]
        assert len(repairs) == 1
        assert repairs[0]["input"] == requirement_input_obligation_model_view(feature)[2]
        assert repairs[0]["response_locations"] == ["requirements"]
        assert "Do not add an input_dispositions entry" in repairs[0]["instruction"]
        assert payload["previous_projection"] == incomplete
        return deepcopy(valid)

    result = StructuredModelRequirementCoverageProvider(complete).project(
        feature_data=feature, request=feature["user_request"])
    assert len(calls) == 2
    assert result["requirements"] == valid["requirements"]
    assert incomplete["requirements"] == [row for row in valid["requirements"]
                                          if row["input_obligation_indexes"] != [3]]


def test_highlighted_missing_input_still_rejects_a_changed_but_incomplete_reply():
    feature = _feature_data()
    reply = _model_projection(_projection())
    reply["requirements"] = [row for row in reply["requirements"]
                             if row["input_obligation_indexes"] != [3]]
    roles = []

    def complete(role, payload, _schema):
        roles.append(role)
        result = deepcopy(reply)
        if role != "requirement_projection":
            assert payload["unaccounted_input_obligations"][0]["input"]["input_obligation_index"] == 3
            result["requirements"][0]["text"] += " Still incomplete."
        return result

    with pytest.raises(RequirementCoverageProjectionError, match="INPUT_ACCOUNTING_INCOMPLETE"):
        StructuredModelRequirementCoverageProvider(complete).project(
            feature_data=feature, request=feature["user_request"])
    assert roles == ["requirement_projection", "requirement_projection_correction"]
