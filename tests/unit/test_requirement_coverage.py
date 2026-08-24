from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from src.mod_agent.bindings import BindingResolver
from src.mod_agent.evidence import (
    EvidencePack,
    RequirementCoverageEvidenceProvider,
    RgLiveEvidenceProvider,
    build_requirement_coverage_pack,
    default_feature_requirement_projection,
    materialize_requirement_coverage_projection,
)
from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.planning import FeatureSpec, ImplementationPlanner
from src.mod_agent.proposal import PatchProposalBuilder, ProposalReviewer
from src.mod_agent.workflow import build_graph, create_initial_state


def _feature_data() -> dict[str, object]:
    return {
        "node_name": "draft_feature_spec",
        "stage": "feature_spec",
        "message": "Feature spec drafted.",
        "feature_id": "feature_synthetic_coverage",
        "user_request": "Change the marker while preserving existing feedback.",
        "target_behavior": "Use ChangeMarker for the configurable marker behavior.",
        "non_goals": ["PreserveFeedback must remain unchanged."],
        "target_mod": "SyntheticMod",
        "risk_level": "medium",
        "acceptance_criteria": ["RuntimeMarker is observed after the change."],
        "evidence_requirements": ["ConfigKey must exist before patching."],
        "runtime_verification_plan": ["Observe RuntimeMarker."],
        "hook_requirement": {"required": False, "reason": "not_required"},
        "blocked": False,
        "blockers": [],
    }


def _projection() -> dict[str, object]:
    return {
        "requirements": [
            {
                "role": "change",
                "text": "Use ChangeMarker for the configurable marker behavior.",
                "input_obligation_indexes": [1, 2],
                "query_leads": ["ChangeMarker"],
            },
            {
                "role": "pre_patch_evidence",
                "text": "ConfigKey must exist before patching.",
                "input_obligation_indexes": [3],
                "query_leads": ["ConfigKey"],
            },
            {
                "role": "preservation",
                "text": "PreserveFeedback must remain unchanged.",
                "input_obligation_indexes": [4],
                "query_leads": ["PreserveFeedback"],
            },
            {
                "role": "post_change_acceptance",
                "text": "RuntimeMarker is observed after the change.",
                "input_obligation_indexes": [5, 6],
                "query_leads": ["RuntimeMarker"],
            },
        ],
        "relations": [
            {
                "parent_requirement_indexes": [1, 3],
                "meaning": "The editable behavior also carries the preservation guard.",
            },
            {
                "parent_requirement_indexes": [2],
                "meaning": "Configuration evidence exists before patching.",
            },
            {
                "parent_requirement_indexes": [4],
                "meaning": "Runtime acceptance is evaluated after the change.",
            },
        ],
        "input_dispositions": [],
    }


def _write_sources(root: Path) -> None:
    source = root / "generated_mods" / "SyntheticMod"
    source.mkdir(parents=True)
    (source / "Behavior.cs").write_text(
        "public sealed class Behavior\n"
        "{\n"
        "    public void ChangeMarker()\n"
        "    {\n"
        "        KeepExistingFeedback();\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    (source / "Configuration.cs").write_text(
        "public sealed class Configuration\n"
        "{\n"
        '    public const string ConfigKey = "Marker.Enabled";\n'
        "}\n",
        encoding="utf-8",
    )
    (source / "Preservation.cs").write_text(
        "public sealed class Preservation\n"
        "{\n"
        "    public void PreserveFeedback() { }\n"
        "}\n",
        encoding="utf-8",
    )


def _materialized_and_retrieved(tmp_path: Path):
    _write_sources(tmp_path)
    feature = _feature_data()
    materialized = materialize_requirement_coverage_projection(
        feature_data=feature,
        request=str(feature["user_request"]),
        projection=_projection(),
    )
    retrieved = RgLiveEvidenceProvider(tmp_path).collect_query_set(
        queries=tuple(dict(value) for value in materialized["queries"]),
        search_root="generated_mods/SyntheticMod",
        max_items=len(materialized["queries"]),
    )
    return feature, materialized, retrieved


def _evidence_by_requirement(materialized, retrieved) -> dict[str, list[str]]:
    execution = retrieved.budget_summary["per_query_execution"]
    result: dict[str, list[str]] = {}
    for row in execution:
        result.setdefault(str(row["requirement_id"]), []).extend(
            str(value) for value in row["evidence_ids"]
        )
    return result


def _positive_findings(materialized, retrieved) -> dict[str, object]:
    evidence = _evidence_by_requirement(materialized, retrieved)
    requirements = materialized["requirements"]
    change_id = str(requirements[0]["requirement_id"])
    prepatch_id = str(requirements[1]["requirement_id"])
    change_evidence = evidence[change_id][0]
    return {
        "findings": [
            {
                "relation_index": 1,
                "relationship": "support",
                "evidence_ids": [change_evidence],
                "unresolved_gaps": [],
            },
            {
                "relation_index": 2,
                "relationship": "support",
                "evidence_ids": [evidence[prepatch_id][0]],
                "unresolved_gaps": [],
            },
            {
                "relation_index": 3,
                "relationship": "missing",
                "evidence_ids": [],
                "unresolved_gaps": ["Runtime observation occurs after patching."],
            },
        ]
    }


def _positive_pack(tmp_path: Path):
    feature, materialized, retrieved = _materialized_and_retrieved(tmp_path)
    pack = build_requirement_coverage_pack(
        query=str(feature["user_request"]),
        materialized_projection=materialized,
        retrieved_pack=retrieved,
        findings=_positive_findings(materialized, retrieved),
    )
    return feature, materialized, retrieved, pack


def _feature_spec(feature: dict[str, object]) -> FeatureSpec:
    return FeatureSpec(
        feature_id=str(feature["feature_id"]),
        user_request=str(feature["user_request"]),
        target_behavior=str(feature["target_behavior"]),
        non_goals=tuple(feature["non_goals"]),
        target_mod=str(feature["target_mod"]),
        risk_level="medium",
        acceptance_criteria=tuple(feature["acceptance_criteria"]),
        evidence_requirements=tuple(feature["evidence_requirements"]),
        runtime_verification_plan=tuple(feature["runtime_verification_plan"]),
    )


def test_positive_requirement_coverage_roundtrips_and_derives_edit_target(
    tmp_path: Path,
) -> None:
    _, materialized, retrieved, pack = _positive_pack(tmp_path)

    assert pack.readiness == "sufficient"
    assert pack.can_generate_patch is True
    coverage = pack.requirement_coverage
    assert coverage is not None
    change_requirement_id = materialized["requirements"][0]["requirement_id"]
    preservation_requirement_id = materialized["requirements"][2]["requirement_id"]
    shared_finding = coverage["findings"][0]
    assert shared_finding["parent_requirement_ids"] == [
        change_requirement_id,
        preservation_requirement_id,
    ]
    assert len(shared_finding["evidence_ids"]) == 1
    edit_target_id = coverage["edit_target_evidence_ids"][0]
    assert edit_target_id == shared_finding["evidence_ids"][0]
    assert retrieved.items[0].source_hash

    payload = pack.to_artifact_payload()
    assert payload["authoritative_for_patch"] is True
    assert EvidencePack.from_artifact_payload(payload).to_artifact_payload() == payload


def test_planner_separates_coverage_edit_and_supporting_bindings(
    tmp_path: Path,
) -> None:
    feature, _, _, pack = _positive_pack(tmp_path)
    plan = ImplementationPlanner().build(
        feature_spec=_feature_spec(feature),
        evidence_pack=pack.to_artifact_payload(),
    )

    assert plan.blocking is False
    assert len(plan.binding_registry["edit_bindings"]) == 1
    assert plan.binding_registry["edit_bindings"][0]["evidence_id"] in (
        pack.requirement_coverage["edit_target_evidence_ids"]
    )
    assert len(plan.binding_registry["supporting_bindings"]) == 2
    assert any(
        binding["source_path"].endswith("Configuration.cs")
        for binding in plan.binding_registry["supporting_bindings"]
    )
    assert plan.proposed_changes[0]["supporting_binding_ids"] == []
    assert "PreserveFeedback must remain unchanged." in plan.side_effect_boundaries
    validation = BindingResolver(
        binding_registry=plan.binding_registry,
        evidence_pack=pack.to_artifact_payload(),
    ).validate_registry_against_evidence()
    assert validation.allowed is True
    assert validation.blockers == ()


def test_preservation_only_target_source_does_not_become_edit_target(
    tmp_path: Path,
) -> None:
    feature, materialized, retrieved = _materialized_and_retrieved(tmp_path)
    evidence = _evidence_by_requirement(materialized, retrieved)
    requirements = materialized["requirements"]
    change_evidence = evidence[str(requirements[0]["requirement_id"])][0]
    preservation_evidence = evidence[str(requirements[2]["requirement_id"])][0]
    assert change_evidence != preservation_evidence

    split_projection = deepcopy(_projection())
    split_projection["relations"] = [
        {"parent_requirement_indexes": [1], "meaning": "Change evidence."},
        {"parent_requirement_indexes": [2], "meaning": "Configuration evidence."},
        {"parent_requirement_indexes": [3], "meaning": "Preservation evidence."},
        {"parent_requirement_indexes": [4], "meaning": "Post-change acceptance."},
    ]
    split = materialize_requirement_coverage_projection(
        feature_data=feature,
        request=str(feature["user_request"]),
        projection=split_projection,
    )
    split_retrieved = RgLiveEvidenceProvider(tmp_path).collect_query_set(
        queries=tuple(dict(value) for value in split["queries"]),
        search_root="generated_mods/SyntheticMod",
        max_items=len(split["queries"]),
    )
    split_evidence = _evidence_by_requirement(split, split_retrieved)
    findings = {
        "findings": [
            {
                "relation_index": index,
                "relationship": "support" if index < 4 else "missing",
                "evidence_ids": (
                    [split_evidence[str(split["requirements"][index - 1]["requirement_id"])][0]]
                    if index < 4
                    else []
                ),
                "unresolved_gaps": [] if index < 4 else ["After patch."],
            }
            for index in range(1, 5)
        ]
    }
    pack = build_requirement_coverage_pack(
        query=str(feature["user_request"]),
        materialized_projection=split,
        retrieved_pack=split_retrieved,
        findings=findings,
    )
    preservation_ids = set(findings["findings"][2]["evidence_ids"])

    assert pack.can_generate_patch is True
    assert preservation_ids.isdisjoint(
        pack.requirement_coverage["edit_target_evidence_ids"]
    )


@pytest.mark.parametrize("mode", ["missing", "conflict", "unresolved"])
def test_required_before_patch_gap_fails_closed(tmp_path: Path, mode: str) -> None:
    feature, materialized, retrieved = _materialized_and_retrieved(tmp_path)
    findings = _positive_findings(materialized, retrieved)
    prepatch = findings["findings"][1]
    if mode == "missing":
        prepatch.update(relationship="missing", evidence_ids=[])
    elif mode == "conflict":
        prepatch["relationship"] = "conflict"
    else:
        prepatch["unresolved_gaps"] = ["The current declaration is ambiguous."]

    pack = build_requirement_coverage_pack(
        query=str(feature["user_request"]),
        materialized_projection=materialized,
        retrieved_pack=retrieved,
        findings=findings,
    )

    assert pack.readiness == "insufficient"
    assert pack.can_generate_patch is False
    assert (
        EvidencePack.from_artifact_payload(pack.to_artifact_payload())
        .to_artifact_payload()
        == pack.to_artifact_payload()
    )
    assert pack.to_artifact_payload()["authoritative_for_patch"] is False


def test_real_source_identity_without_findings_remains_insufficient(
    tmp_path: Path,
) -> None:
    feature, materialized, retrieved = _materialized_and_retrieved(tmp_path)
    assert all(item.source_path and item.source_hash and item.span for item in retrieved.items)

    pack = build_requirement_coverage_pack(
        query=str(feature["user_request"]),
        materialized_projection=materialized,
        retrieved_pack=retrieved,
        findings={"findings": []},
    )

    assert pack.readiness == "insufficient"
    assert pack.can_generate_patch is False


def test_rg_live_query_set_executes_every_query_without_top_one_starvation(
    tmp_path: Path,
) -> None:
    _, materialized, retrieved = _materialized_and_retrieved(tmp_path)
    execution = retrieved.budget_summary["per_query_execution"]

    assert len(execution) == len(materialized["queries"])
    assert [row["query_id"] for row in execution] == [
        row["query_id"] for row in materialized["queries"]
    ]
    assert execution[0]["evidence_ids"]
    assert execution[1]["evidence_ids"]
    assert execution[2]["evidence_ids"]
    assert retrieved.budget_summary["all_queries_executed"] is True
    assert retrieved.readiness == "insufficient"
    assert retrieved.can_generate_patch is False
    assert retrieved.disabled_modes["dense"].startswith("Dense retrieval is disabled")


def test_projection_and_findings_reject_authority_and_identity_invention(
    tmp_path: Path,
) -> None:
    feature, materialized, retrieved = _materialized_and_retrieved(tmp_path)
    illegal_projection = deepcopy(_projection())
    illegal_projection["can_generate_patch"] = True
    with pytest.raises(ValueError, match="REQUIREMENT_COVERAGE_PROJECTION_SHAPE_INVALID"):
        materialize_requirement_coverage_projection(
            feature_data=feature,
            request=str(feature["user_request"]),
            projection=illegal_projection,
        )

    duplicate_relation = deepcopy(_projection())
    duplicate_relation["relations"].append(deepcopy(duplicate_relation["relations"][0]))
    with pytest.raises(ValueError, match="REQUIREMENT_COVERAGE_RELATION_DUPLICATE"):
        materialize_requirement_coverage_projection(
            feature_data=feature,
            request=str(feature["user_request"]),
            projection=duplicate_relation,
        )

    for finding in (
        {
            "findings": [],
            "edit_target_evidence_ids": [retrieved.items[0].evidence_id],
        },
        {
            "findings": [
                {
                    "relation_index": 1,
                    "relationship": "support",
                    "evidence_ids": ["unknown_evidence"],
                    "unresolved_gaps": [],
                }
            ]
        },
        {
            "findings": [
                {
                    "relation_index": 1,
                    "relationship": "support",
                    "evidence_ids": [retrieved.items[0].evidence_id],
                    "unresolved_gaps": [],
                    "source_ref": "invented.cs",
                }
            ]
        },
    ):
        with pytest.raises(ValueError, match="REQUIREMENT_COVERAGE_FINDING"):
            build_requirement_coverage_pack(
                query=str(feature["user_request"]),
                materialized_projection=materialized,
                retrieved_pack=retrieved,
                findings=finding,
            )


def test_projection_requires_complete_input_obligation_accounting() -> None:
    feature = _feature_data()
    incomplete = deepcopy(_projection())
    incomplete["requirements"].pop()
    incomplete["relations"].pop()

    with pytest.raises(
        ValueError,
        match="REQUIREMENT_COVERAGE_INPUT_ACCOUNTING_INCOMPLETE",
    ):
        materialize_requirement_coverage_projection(
            feature_data=feature,
            request=str(feature["user_request"]),
            projection=incomplete,
        )


def test_post_change_obligations_can_be_explicitly_disposed_without_patch_gate() -> None:
    feature = _feature_data()
    disposed = deepcopy(_projection())
    disposed["requirements"].pop()
    disposed["relations"].pop()
    disposed["input_dispositions"] = [
        {
            "input_obligation_index": 5,
            "disposition": "post_change",
            "reason": "Acceptance is observed only after applying the approved patch.",
        },
        {
            "input_obligation_index": 6,
            "disposition": "post_change",
            "reason": "Runtime verification follows Build and deployment.",
        },
    ]

    materialized = materialize_requirement_coverage_projection(
        feature_data=feature,
        request=str(feature["user_request"]),
        projection=disposed,
    )

    assert len(materialized["input_dispositions"]) == 2
    assert all(
        disposition["disposition"] == "post_change"
        for disposition in materialized["input_dispositions"]
    )
    assert all(
        requirement["required_before_patch"] is True
        for requirement in materialized["requirements"]
    )


def test_model_cannot_downgrade_pre_patch_obligation_role_or_gate() -> None:
    feature = _feature_data()
    downgraded = deepcopy(_projection())
    downgraded["requirements"][1]["role"] = "post_change_acceptance"

    with pytest.raises(ValueError, match="REQUIREMENT_COVERAGE_REQUIREMENT_INVALID"):
        materialize_requirement_coverage_projection(
            feature_data=feature,
            request=str(feature["user_request"]),
            projection=downgraded,
        )

    materialized = materialize_requirement_coverage_projection(
        feature_data=feature,
        request=str(feature["user_request"]),
        projection=_projection(),
    )
    assert materialized["requirements"][1]["required_before_patch"] is True
    assert materialized["requirements"][3]["required_before_patch"] is False


def test_one_input_obligation_can_be_carried_by_multiple_requirements() -> None:
    feature = _feature_data()
    projection = deepcopy(_projection())
    projection["requirements"].append(
        {
            "role": "preservation",
            "text": "Preserve the user-requested existing feedback behavior.",
            "input_obligation_indexes": [1],
            "query_leads": ["preserve existing feedback"],
        }
    )
    projection["relations"].append(
        {
            "parent_requirement_indexes": [5],
            "meaning": "User-request preservation semantics remain explicit.",
        }
    )

    materialized = materialize_requirement_coverage_projection(
        feature_data=feature,
        request=str(feature["user_request"]),
        projection=projection,
    )
    obligation_id = materialized["input_obligations"][0]["input_obligation_id"]
    carrying_requirements = [
        requirement
        for requirement in materialized["requirements"]
        if obligation_id in requirement["input_obligation_ids"]
    ]

    assert {requirement["role"] for requirement in carrying_requirements} == {
        "change",
        "preservation",
    }


def test_binding_resolver_rejects_supporting_evidence_promoted_to_edit(
    tmp_path: Path,
) -> None:
    feature, _, _, pack = _positive_pack(tmp_path)
    plan = ImplementationPlanner().build(
        feature_spec=_feature_spec(feature),
        evidence_pack=pack.to_artifact_payload(),
    ).to_artifact_payload()
    supporting = plan["binding_registry"]["supporting_bindings"][0]
    tampered = deepcopy(plan["binding_registry"])
    tampered["edit_bindings"].append(
        {
            **tampered["edit_bindings"][0],
            "binding_id": "edit_binding_tampered",
            "evidence_id": supporting["evidence_id"],
            "canonical_target_path": supporting["source_path"],
            "target_symbol": supporting["target_symbol"],
            "target_span": supporting["target_span"],
        }
    )
    result = BindingResolver(
        binding_registry=tampered,
        evidence_pack=pack.to_artifact_payload(),
    ).validate_registry_against_evidence()

    assert result.allowed is False
    assert any(
        blocker["code"] == "EDIT_BINDING_OUTSIDE_REQUIREMENT_COVERAGE"
        for blocker in result.blockers
    )

    valid_plan = ImplementationPlanner().build(
        feature_spec=_feature_spec(feature),
        evidence_pack=pack.to_artifact_payload(),
    ).to_artifact_payload()
    proposal = PatchProposalBuilder().build(
        valid_plan,
        evidence_pack=pack.to_artifact_payload(),
    ).to_artifact_payload()
    tampered_plan = deepcopy(valid_plan)
    tampered_plan["binding_registry"] = tampered
    review = ProposalReviewer().review(
        proposal,
        evidence_pack=pack.to_artifact_payload(),
        implementation_plan=tampered_plan,
    )
    assert review.allowed_next_stage is None
    assert any(
        finding.rule_id == "binding_registry"
        and "coverage-derived edit target" in finding.message
        for finding in review.findings
    )


def test_graph_reaches_nonblocking_plan_from_explicit_positive_coverage(
    tmp_path: Path,
) -> None:
    source = tmp_path / "generated_mods" / "SyntheticMod" / "Behavior.cs"
    source.parent.mkdir(parents=True)
    source.write_text(
        "public sealed class Behavior\n"
        "{\n"
        "    public void ChangeMarker()\n"
        "    {\n"
        "        // target source API evidence config text preserve normal feedback\n"
        "        // runtime verification acceptance criteria\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )

    def findings_factory(materialized, retrieved):
        items = retrieved.items
        assert items
        required_by_id = {
            str(requirement["requirement_id"]): bool(
                requirement["required_before_patch"]
            )
            for requirement in materialized["requirements"]
        }
        return {
            "findings": [
                {
                    "relation_index": int(
                        relation["provenance"]["relation_index"]
                    ),
                    "relationship": (
                        "support"
                        if any(
                            required_by_id[str(parent)]
                            for parent in relation["parent_requirement_ids"]
                        )
                        else "missing"
                    ),
                    "evidence_ids": (
                        [items[0].evidence_id]
                        if any(
                            required_by_id[str(parent)]
                            for parent in relation["parent_requirement_ids"]
                        )
                        else []
                    ),
                    "unresolved_gaps": (
                        []
                        if any(
                            required_by_id[str(parent)]
                            for parent in relation["parent_requirement_ids"]
                        )
                        else ["Observed only after patching."]
                    ),
                }
                for relation in materialized["relations"]
            ]
        }

    provider = RequirementCoverageEvidenceProvider(
        RgLiveEvidenceProvider(tmp_path),
        projection_factory=default_feature_requirement_projection,
        findings_factory=findings_factory,
    )

    def evidence_factory(state, feature_data):
        return provider.collect(
            query=str(state["user_request"]),
            search_root="generated_mods/SyntheticMod",
            feature_data=feature_data,
        )

    store = ArtifactStore(tmp_path / "artifacts")
    graph = build_graph(
        store,
        evidence_pack_factory=evidence_factory,
        interrupt_after=["create_implementation_plan"],
    )
    result = graph.invoke(
        create_initial_state(
            run_id="run_synthetic_requirement_coverage",
            request_id="req_synthetic_requirement_coverage",
            user_request="Change the marker while preserving normal feedback.",
            target_mod="SyntheticMod",
        )
    )

    assert "evidence_pack" in result["artifacts"]
    assert "implementation_plan" in result["artifacts"]
    assert "patch_proposal" not in result["artifacts"]
    evidence_ref = ArtifactRef(
        feature_id=result["feature_id"],
        artifact_type="evidence_pack",
        path=result["artifacts"]["evidence_pack"],
        artifact_hash=result["artifact_hashes"]["evidence_pack"],
    )
    plan_ref = ArtifactRef(
        feature_id=result["feature_id"],
        artifact_type="implementation_plan",
        path=result["artifacts"]["implementation_plan"],
        artifact_hash=result["artifact_hashes"]["implementation_plan"],
    )
    evidence = store.read(evidence_ref)["data"]
    plan = store.read(plan_ref)["data"]
    assert evidence["readiness"] == "sufficient"
    assert evidence["authoritative_for_patch"] is True
    assert plan["blocking"] is False
    assert plan["binding_registry"]["edit_bindings"]


def test_requirement_coverage_tamper_is_rejected_on_rehydrate(
    tmp_path: Path,
) -> None:
    _, _, _, pack = _positive_pack(tmp_path)
    payload = pack.to_artifact_payload()
    payload["requirement_coverage"]["edit_target_evidence_ids"] = [
        payload["items"][1]["evidence_id"]
    ]

    with pytest.raises(ValueError, match="REQUIREMENT_COVERAGE_SEMANTIC_DRIFT"):
        EvidencePack.from_artifact_payload(payload)
