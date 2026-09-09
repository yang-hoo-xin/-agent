"""Product review context must retain all already-admitted Plan evidence."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from src.mod_agent.evidence import EvidencePack
from src.mod_agent.product_executor import (
    ProductApprovalDeferred,
    execute_product_execution,
    preflight_product_execution,
    source_snapshot,
    source_snapshot_sha256,
)
from src.mod_agent.proposal import PatchProposalBuilder, ProposalReviewer
from tests.unit.test_product_execution import (
    _formalize_product_test_pack,
    _request,
    _successful_compile_adapters,
)
from tests.unit.test_proposal_review import (
    _artifact_hashes,
    _evidence_pack,
    _implementation_payload,
)


@pytest.mark.parametrize("count,comment", [(12, "x" * 520), (3, "界" * 2200)], ids=["many_refs", "unicode_chars"])
def test_product_review_keeps_all_admitted_source_before_approval(tmp_path, count, comment):
    request, store = _request(tmp_path)
    source_text = "sealed class Plugin { /*" + comment + "*/ }\n"
    canonical = Path(request.source_root) / "Plugin.cs"
    isolated = Path(request.isolated_target_root) / "Plugin.cs"
    for path in (canonical, isolated):
        path.write_text(source_text, encoding="utf-8")
    source_bytes = canonical.read_bytes()
    source_text = source_bytes.decode("utf-8")
    request = replace(request,
        source_snapshot_sha256=source_snapshot_sha256(source_snapshot(canonical.parent)),
        isolated_source_snapshot_sha256=source_snapshot_sha256(source_snapshot(isolated.parent)))
    adapters = _successful_compile_adapters(request, physical_apply=True)
    original_evidence = adapters.evidence_pack_factory
    expected_refs = []
    def evidence(state, feature):
        pack = original_evidence(state, feature)
        item = pack.items[0]
        items = (item, *(replace(item, evidence_id=f"support_context_{index}") for index in range(1, count)))
        expected_refs.extend(value.evidence_id for value in items)
        return _formalize_product_test_pack(query=request.user_request, feature_data=feature,
            retrieved_pack=EvidencePack(query=request.user_request, readiness="sufficient",
                can_generate_patch=True, items=items, retrieval_methods_used=pack.retrieval_methods_used))
    adapters = replace(adapters, evidence_pack_factory=evidence)
    preflight = preflight_product_execution(request, adapters, store)
    with pytest.raises(ProductApprovalDeferred) as captured:
        execute_product_execution(preflight, adapters, store, defer_approval=True)
    pending = captured.value
    checkpoint = store.read(pending.checkpoint_ref)["data"]
    proposal = store.read(next(output.artifact_ref for output in pending.outputs
                              if output.artifact_role == "patch_proposal"))["data"]
    context = proposal["context_pack"]
    assert proposal["evidence_refs"] == expected_refs
    assert [item["evidence_id"] for item in context["source_snippets"]] == expected_refs
    assert all(item["excerpt"] == source_text and not item["truncated"] for item in context["source_snippets"])
    assert context["context_budget"]["source_snippet_chars"] == len(source_text) * count
    assert context["context_budget"]["source_snippet_char_limit"] == len(source_text) * count
    assert context["omission_blockers"] == []
    assert "dry_run_result" in checkpoint["state_snapshot"]["artifacts"]
    assert not any(effect.effect_role in {"isolated_apply", "build", "runtime"} for effect in pending.effect_events)
    assert canonical.read_bytes() == isolated.read_bytes() == source_bytes


def test_explicit_builder_budget_still_reports_omitted_evidence():
    plan, evidence = _implementation_payload(), _evidence_pack()
    second = deepcopy(evidence["items"][0])
    second["evidence_id"] = "explicit_support"
    evidence["items"].append(second)
    plan["evidence_refs"].append(second["evidence_id"])
    proposal = PatchProposalBuilder().build(plan, evidence_pack=evidence,
        artifact_hashes=_artifact_hashes(), source_snippet_char_limit=1).to_artifact_payload()
    review = ProposalReviewer().review(proposal, evidence_pack=evidence,
        implementation_plan=plan, artifact_hashes=_artifact_hashes())
    assert proposal["context_pack"]["context_budget"]["source_snippet_char_limit"] == 1
    assert any(item["code"] == "SOURCE_SNIPPET_BUDGET_EXCEEDED"
               for item in proposal["context_pack"]["omission_blockers"])
    assert any(item.rule_id == "context_pack" and item.level == "blocking" for item in review.findings)


def test_exact_budget_does_not_admit_missing_or_unreferenced_evidence():
    plan, evidence = _implementation_payload(), _evidence_pack()
    unrelated = deepcopy(evidence["items"][0])
    unrelated.update(evidence_id="unreferenced_item", excerpt="unused" * 2000)
    evidence["items"].append(unrelated)
    plan["evidence_refs"].append("missing_source")
    limit = PatchProposalBuilder.required_source_snippet_char_limit(plan, evidence)
    proposal = PatchProposalBuilder().build(plan, evidence_pack=evidence,
        artifact_hashes=_artifact_hashes(), source_snippet_char_limit=limit).to_artifact_payload()
    context = proposal["context_pack"]
    assert [item["evidence_id"] for item in context["source_snippets"]] == ["ev_001"]
    assert context["source_snippets"][0]["excerpt"] == evidence["items"][0]["excerpt"]
    assert context["omission_blockers"] == [{
        "code": "SOURCE_SNIPPET_MISSING",
        "message": "Proposal context requires a source snippet for every evidence ref.",
        "evidence_ref": "missing_source",
    }]
