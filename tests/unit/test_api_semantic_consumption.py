"""API authority visibility and existing Findings/Planning composition.

These scripted semantic responses test production input and admission wiring.
They do not establish that a real model chooses the correct API or edit target.
The trigger is the existing BetterHitFeedback distinction between reference
assemblies and the current target API; all code here is synthetic fixture code.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace

import pytest

from src.libs.llm.agent_turn import AgentTurnResponse, AgentUsage
from src.mod_agent.evidence import (
    build_requirement_coverage_pack,
    materialize_requirement_coverage_projection,
)
from src.mod_agent.evidence.models import EvidenceItem, EvidencePack
from src.mod_agent.evidence.requirement_coverage_provider import (
    StructuredModelRequirementCoverageProvider,
    _source_observation_model_view,
)
from src.mod_agent.planning.model_selection import (
    ModelPlanningTargetSelector,
    _restore_source_identities,
)
from tests.unit.test_fresh_planning_continuation import _inputs, _positive_findings, _projection


def _api_item(authority="authoritative", *, evidence_id="synthetic-current-api"):
    return EvidenceItem(evidence_id=evidence_id, source_type="decompiled_api",
        source_path="Modules-ASM.dll", symbol="Synthetic.Game.ObserveResult", span=None,
        retrieval_method="agent_selected_cli_metadata_il_read", score=1.0,
        claim_supported="Metadata exposes the inspected method in the selected assembly.",
        excerpt='{"has_method_body":false,"instructions":[]}',
        source_ref="source://synthetic-current/Modules-ASM.dll", source_hash="a" * 64,
        file_hash="a" * 64, module_mvid="00000000-0000-0000-0000-000000000001",
        metadata_token="0x06000001", signature_blob="200001", source_authority=authority,
        authority="mod_agent_deterministic")


def test_api_observation_keeps_existing_version_and_authority_facts():
    item = _api_item().to_dict()
    visible = _source_observation_model_view(item)
    assert {key: visible[key] for key in (
        "source_authority", "source_hash", "module_mvid", "metadata_token", "signature_blob",
    )} == {key: item[key] for key in (
        "source_authority", "source_hash", "module_mvid", "metadata_token", "signature_blob",
    )}
    assert visible["excerpt"] == item["excerpt"]
    assert "source_ref" not in visible  # Local root paths are not needed by the semantic owner.


@pytest.mark.parametrize("authority", ["authoritative", "supporting", None])
def test_scripted_findings_consumes_api_authority_before_original_planning_gate(tmp_path, authority):
    inputs = _inputs(tmp_path)
    retrieved = EvidencePack.from_artifact_payload(inputs.store.read(inputs.evidence_ref)["data"])
    combined = replace(retrieved, items=(*retrieved.items, _api_item(authority)))
    materialized = materialize_requirement_coverage_projection(feature_data=inputs.feature_payload,
        request=inputs.feature_payload["user_request"], projection=_projection())
    captured = []

    def scripted_findings(_role, payload, schema):
        captured.append(deepcopy(payload))
        api = next(item for item in payload["source_observations"] if item["source_type"] == "decompiled_api")
        # A deterministic test double only: the live model owns this judgment.
        supported = api.get("source_authority") == "authoritative"
        response = _positive_findings(materialized, retrieved)
        indexes = schema["properties"]["findings"]["items"]["properties"]["relation_index"]["enum"]
        response["findings"] = [row for row in response["findings"] if row["relation_index"] in indexes]
        first = response["findings"][0]
        first["evidence_ids"].append(api["evidence_id"])
        if not supported:
            first["relationship"] = "missing"
            first["edit_target_evidence_ids"] = []
            first["unresolved_gaps"] = ["No current-target API contract supports the requested behavior."]
        return response

    provider = StructuredModelRequirementCoverageProvider(scripted_findings)
    findings = provider.findings(materialized_projection=materialized, retrieved_pack=combined,
        request=inputs.feature_payload["user_request"])
    pack = build_requirement_coverage_pack(query=inputs.feature_payload["user_request"],
        materialized_projection=materialized, retrieved_pack=combined, findings=findings)
    assert len(captured) == 1
    api = next(item for item in captured[0]["source_observations"] if item["source_type"] == "decompiled_api")
    assert api["source_authority"] == authority
    assert pack.can_generate_patch is (authority == "authoritative")

    class PlanningClient:
        provider, model = "offline_test", "scripted_semantic_consumer"

        def __init__(self):
            self.requests = []

        def complete_turn(self, request):
            self.requests.append(request)
            payload = _restore_source_identities(request.messages[1].content)
            api = next(item for item in payload["source_observations"] if item["source_type"] == "decompiled_api")
            assert api["source_authority"] == "authoritative"
            assert api["selectable_for_edit"] is False
            assert api["evidence_id"] not in payload["allowed_edit_evidence_ids"]
            return AgentTurnResponse(provider=self.provider, model=self.model,
                content=json.dumps({"decision": "select_targets", "selected_evidence_ids": payload["allowed_edit_evidence_ids"],
                    "rationale": "Synthetic current API supports the existing source-side change.", "missing_evidence": []}),
                usage=AgentUsage(input_tokens=10, output_tokens=10))

    client = PlanningClient()
    selector = ModelPlanningTargetSelector(client=client, workspace_root=inputs.workspace,
        receipt_path=tmp_path / "selection.json")
    if authority == "authoritative":
        selection = selector(inputs.feature_payload, pack.to_artifact_payload())
        assert selection and len(client.requests) == 1
        assert _api_item().evidence_id not in selection
    else:
        with pytest.raises(ValueError, match="Planning requires current sufficient formal coverage"):
            selector.prepare(inputs.feature_payload, pack.to_artifact_payload())
        assert client.requests == []
