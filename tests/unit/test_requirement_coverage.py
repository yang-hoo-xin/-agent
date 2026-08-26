from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from src.mod_agent.bindings import BindingResolver
from src.mod_agent.evidence import (
    EvidencePack,
    RequirementCoverageEvidenceProvider,
    RgLiveEvidenceProvider,
    StructuredModelRequirementCoverageProvider,
    build_requirement_coverage_pack,
    default_feature_requirement_projection,
    make_requirement_coverage_evidence_provider,
    materialize_requirement_coverage_projection,
    validated_requirement_coverage_view,
)
from src.mod_agent.evidence.discovery_contract import (
    request_relation_identity as hook_compatible_relation_identity,
)
from src.mod_agent.evidence.identity import request_relation_identity
from src.mod_agent.evidence.requirement_coverage import (
    RequirementCoverageProjectionError,
    requirement_input_obligation_model_view,
)
from src.mod_agent.evidence.requirement_coverage_provider import (
    RequirementProjectionAdmissionError,
    admit_requirement_projection_response,
    requirement_projection_response_schema,
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


def _schema_allows_input_disposition(
    schema: dict[str, object],
    *,
    index: int,
    disposition: str,
    reason: str = "bounded reason",
) -> bool:
    dispositions = schema["properties"]["input_dispositions"]
    if dispositions["maxItems"] < 1:
        return False
    value = {
        "input_obligation_index": index,
        "disposition": disposition,
        "reason": reason,
    }
    variants = dispositions["items"]["oneOf"]
    return any(
        set(value) == set(variant["required"])
        and variant["additionalProperties"] is False
        and all(
            (
                value[name] == property_schema["const"]
                if "const" in property_schema
                else isinstance(value[name], str)
                and len(value[name]) >= property_schema.get("minLength", 0)
            )
            for name, property_schema in variant["properties"].items()
        )
        for variant in variants
    )


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


def _projection_without_obligation_four() -> dict[str, object]:
    projection = deepcopy(_projection())
    del projection["requirements"][2]
    projection["relations"] = [
        {
            "parent_requirement_indexes": [1],
            "meaning": "Change evidence.",
        },
        {
            "parent_requirement_indexes": [2],
            "meaning": "Pre-patch evidence.",
        },
        {
            "parent_requirement_indexes": [3],
            "meaning": "Post-change evidence.",
        },
    ]
    return projection


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
    view = validated_requirement_coverage_view(payload)
    assert view is not None
    assert view.authorized_edit_target_ids == frozenset(
        coverage["edit_target_evidence_ids"]
    )
    assert view.preservation_requirement_texts == (
        "PreserveFeedback must remain unchanged.",
    )


def test_shared_relation_identity_preserves_hook_compatibility() -> None:
    values = {
        "request_sha256": "a" * 64,
        "projection_sha256": "b" * 64,
        "relation_index": 3,
    }
    assert request_relation_identity(**values) == hook_compatible_relation_identity(
        **values
    )


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


def test_projection_schema_binds_thirteen_obligation_dispositions_per_index(
) -> None:
    feature = _feature_data()
    feature["evidence_requirements"] = ["evidence 1", "evidence 2", "evidence 3"]
    feature["non_goals"] = ["boundary 1", "boundary 2", "boundary 3"]
    feature["acceptance_criteria"] = [
        "acceptance 1",
        "acceptance 2",
        "acceptance 3",
    ]
    feature["runtime_verification_plan"] = ["runtime 1", "runtime 2"]
    obligations = requirement_input_obligation_model_view(feature)

    schema = requirement_projection_response_schema(
        input_obligations=obligations
    )

    assert len(obligations) == 13
    dispositions = schema["properties"]["input_dispositions"]
    assert dispositions["maxItems"] == 8
    observed_pairs = {
        (
            variant["properties"]["input_obligation_index"]["const"],
            variant["properties"]["disposition"]["const"],
        )
        for variant in dispositions["items"]["oneOf"]
    }
    assert observed_pairs == {
        (6, "scope_boundary"),
        (7, "scope_boundary"),
        (8, "scope_boundary"),
        (9, "post_change"),
        (10, "post_change"),
        (11, "post_change"),
        (12, "post_change"),
        (13, "post_change"),
    }
    assert _schema_allows_input_disposition(
        schema,
        index=6,
        disposition="scope_boundary",
    )
    assert _schema_allows_input_disposition(
        schema,
        index=9,
        disposition="post_change",
    )
    assert not _schema_allows_input_disposition(
        schema,
        index=6,
        disposition="post_change",
    )
    assert not _schema_allows_input_disposition(
        schema,
        index=9,
        disposition="scope_boundary",
    )
    assert not _schema_allows_input_disposition(
        schema,
        index=1,
        disposition="scope_boundary",
    )
    assert not _schema_allows_input_disposition(
        schema,
        index=6,
        disposition="scope_boundary",
        reason="",
    )


def test_projection_schema_has_zero_dispositions_when_no_obligation_is_eligible(
) -> None:
    feature = _feature_data()
    feature["non_goals"] = []
    feature["acceptance_criteria"] = []
    feature["runtime_verification_plan"] = []
    obligations = requirement_input_obligation_model_view(feature)

    schema = requirement_projection_response_schema(
        input_obligations=obligations
    )

    dispositions = schema["properties"]["input_dispositions"]
    assert dispositions["maxItems"] == 0
    assert "oneOf" not in dispositions["items"]
    assert not _schema_allows_input_disposition(
        schema,
        index=1,
        disposition="scope_boundary",
    )


def test_projection_schema_invalid_pair_is_rejected_before_materializer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feature = _feature_data()
    obligations = requirement_input_obligation_model_view(feature)
    schema = requirement_projection_response_schema(
        input_obligations=obligations
    )
    invalid = deepcopy(_projection())
    invalid["input_dispositions"] = [
        {
            "input_obligation_index": 4,
            "disposition": "post_change",
            "reason": "Cross-bound pair.",
        }
    ]

    with pytest.raises(RequirementProjectionAdmissionError) as admission:
        admit_requirement_projection_response(invalid, schema=schema)
    assert str(admission.value) == "REQUIREMENT_COVERAGE_PROJECTION_SCHEMA_INVALID"
    assert admission.value.diagnostic == {
        "phase": "response_schema_admission",
        "failure_category": "disallowed_disposition",
        "json_path": "$.input_dispositions[0].disposition",
        "schema_keyword": "oneOf",
        "allowed_boundary": {
            "input_obligation_index": 4,
            "allowed_dispositions": ["scope_boundary"],
            "allowed_pairs": [
                {"input_obligation_index": 4, "disposition": "scope_boundary"},
                {"input_obligation_index": 5, "disposition": "post_change"},
                {"input_obligation_index": 6, "disposition": "post_change"},
            ],
        },
        "observed_disposition": "post_change",
    }

    materializer_calls: list[dict[str, object]] = []
    original_materializer = materialize_requirement_coverage_projection

    def tracked_materializer(**kwargs):
        materializer_calls.append(deepcopy(kwargs["projection"]))
        return original_materializer(**kwargs)

    monkeypatch.setattr(
        "src.mod_agent.evidence.requirement_coverage_provider."
        "materialize_requirement_coverage_projection",
        tracked_materializer,
    )
    roles: list[str] = []
    correction_payloads: list[dict[str, object]] = []
    schemas: list[dict[str, object]] = []

    def complete_json(role, payload, response_schema):
        roles.append(role)
        schemas.append(deepcopy(response_schema))
        if role == "requirement_projection":
            return deepcopy(invalid)
        correction_payloads.append(deepcopy(payload))
        return deepcopy(_projection())

    provider = StructuredModelRequirementCoverageProvider(complete_json)
    corrected = provider.project(
        feature_data=feature,
        request=str(feature["user_request"]),
    )

    assert corrected == _projection()
    assert roles == [
        "requirement_projection",
        "requirement_projection_correction",
    ]
    assert schemas[0] == schemas[1]
    assert materializer_calls == [_projection()]
    diagnostic = correction_payloads[0]["rejection_diagnostic"]
    assert diagnostic["json_path"] == "$.input_dispositions[0].disposition"
    assert diagnostic["failure_category"] == "disallowed_disposition"
    assert [item["status"] for item in provider.projection_attempt_audit] == [
        "rejected",
        "accepted",
    ]
    assert provider.projection_attempt_audit[0]["response_schema_admitted"] is False
    assert provider.projection_attempt_audit[1]["response_schema_admitted"] is True


def test_projection_schema_admission_rejects_unsupported_constructs() -> None:
    with pytest.raises(RequirementProjectionAdmissionError) as rejection:
        admit_requirement_projection_response(
            {},
            schema={"type": "object", "patternProperties": {}},
        )

    assert rejection.value.diagnostic["failure_category"] == (
        "schema_construct_unsupported"
    )
    assert rejection.value.diagnostic["allowed_boundary"][
        "supported_keywords"
    ]
    assert rejection.value.diagnostic["unsupported_keywords"] == [
        "patternProperties"
    ]


def test_projection_correction_receives_precise_semantic_overlap_diagnostic() -> None:
    feature = _feature_data()
    overlap = deepcopy(_projection())
    overlap["input_dispositions"] = [
        {
            "input_obligation_index": 4,
            "disposition": "scope_boundary",
            "reason": "Schema-valid but already requirement-accounted.",
        }
    ]
    correction_diagnostics: list[dict[str, object]] = []

    def complete_json(role, payload, _schema):
        if role == "requirement_projection":
            return deepcopy(overlap)
        correction_diagnostics.append(deepcopy(payload["rejection_diagnostic"]))
        return deepcopy(_projection())

    provider = StructuredModelRequirementCoverageProvider(complete_json)
    provider.project(
        feature_data=feature,
        request=str(feature["user_request"]),
    )

    assert correction_diagnostics == [
        {
            "error_code": "REQUIREMENT_COVERAGE_INPUT_DISPOSITION_INVALID",
            "phase": "semantic_materialization",
            "failure_category": (
                "obligation_already_accounted_and_dispositioned"
            ),
            "json_path": "$.input_dispositions[0].input_obligation_index",
            "input_obligation_index": 4,
            "allowed_dispositions": ["scope_boundary"],
        }
    ]
    attempts = provider.projection_attempt_audit
    assert attempts[0]["response_schema_admitted"] is True
    assert attempts[0]["semantic_materialization_admitted"] is False
    assert attempts[1]["status"] == "accepted"


@pytest.mark.parametrize(
    ("failure_case", "error_code", "category", "json_path"),
    [
        (
            "overlap",
            "REQUIREMENT_COVERAGE_INPUT_DISPOSITION_INVALID",
            "obligation_already_accounted_and_dispositioned",
            "$.input_dispositions[0].input_obligation_index",
        ),
        (
            "duplicate",
            "REQUIREMENT_COVERAGE_INPUT_DISPOSITION_INVALID",
            "duplicate_disposition_index",
            "$.input_dispositions[1].input_obligation_index",
        ),
        (
            "whitespace_reason",
            "REQUIREMENT_COVERAGE_INPUT_DISPOSITION_INVALID",
            "invalid_reason",
            "$.input_dispositions[0].reason",
        ),
        (
            "incomplete",
            "REQUIREMENT_COVERAGE_INPUT_ACCOUNTING_INCOMPLETE",
            "input_accounting_incomplete",
            "$.input_dispositions",
        ),
    ],
)
def test_projection_semantic_rejections_are_precise_and_legacy_compatible(
    failure_case: str,
    error_code: str,
    category: str,
    json_path: str,
) -> None:
    feature = _feature_data()
    projection = (
        deepcopy(_projection())
        if failure_case == "overlap"
        else _projection_without_obligation_four()
    )
    if failure_case == "overlap":
        projection["input_dispositions"] = [
            {
                "input_obligation_index": 4,
                "disposition": "scope_boundary",
                "reason": "Already covered by a requirement.",
            }
        ]
    elif failure_case == "duplicate":
        projection["input_dispositions"] = [
            {
                "input_obligation_index": 4,
                "disposition": "scope_boundary",
                "reason": "First disposition.",
            },
            {
                "input_obligation_index": 4,
                "disposition": "scope_boundary",
                "reason": "Duplicate disposition.",
            },
        ]
    elif failure_case == "whitespace_reason":
        projection["input_dispositions"] = [
            {
                "input_obligation_index": 4,
                "disposition": "scope_boundary",
                "reason": "   ",
            }
        ]
    obligations = requirement_input_obligation_model_view(feature)
    schema = requirement_projection_response_schema(
        input_obligations=obligations
    )
    admit_requirement_projection_response(projection, schema=schema)

    with pytest.raises(RequirementCoverageProjectionError) as rejection:
        materialize_requirement_coverage_projection(
            feature_data=feature,
            request=str(feature["user_request"]),
            projection=projection,
        )

    assert str(rejection.value) == error_code
    assert rejection.value.diagnostic["phase"] == "semantic_materialization"
    assert rejection.value.diagnostic["failure_category"] == category
    assert rejection.value.diagnostic["json_path"] == json_path


def test_projection_materializer_still_rejects_cross_bound_disposition() -> None:
    feature = _feature_data()
    projection = _projection_without_obligation_four()
    projection["input_dispositions"] = [
        {
            "input_obligation_index": 4,
            "disposition": "post_change",
            "reason": "Invalid cross-bound disposition.",
        }
    ]

    with pytest.raises(RequirementCoverageProjectionError) as rejection:
        materialize_requirement_coverage_projection(
            feature_data=feature,
            request=str(feature["user_request"]),
            projection=projection,
        )
    assert str(rejection.value) == "REQUIREMENT_COVERAGE_INPUT_DISPOSITION_INVALID"
    assert rejection.value.diagnostic["failure_category"] == "disallowed_disposition"
    assert rejection.value.diagnostic["allowed_dispositions"] == [
        "scope_boundary"
    ]


def test_legal_projection_correction_reaches_findings_consumer(
    tmp_path: Path,
) -> None:
    _write_sources(tmp_path)
    feature = _feature_data()
    invalid = deepcopy(_projection())
    invalid["input_dispositions"] = [
        {
            "input_obligation_index": 4,
            "disposition": "post_change",
            "reason": "Schema-invalid pair must not be retained.",
        }
    ]
    roles: list[str] = []

    def complete_json(role, payload, _schema):
        roles.append(role)
        if role == "requirement_projection":
            return deepcopy(invalid)
        if role == "requirement_projection_correction":
            assert payload["rejection_diagnostic"]["failure_category"] == (
                "disallowed_disposition"
            )
            return deepcopy(_projection())
        if role == "requirement_findings":
            return {
                "findings": [
                    {
                        "relation_index": relation["relation_index"],
                        "relationship": "missing",
                        "evidence_ids": [],
                        "unresolved_gaps": ["Semantic support is not established."],
                    }
                    for relation in payload["relations"]
                ]
            }
        raise AssertionError(role)

    provider = make_requirement_coverage_evidence_provider(
        RgLiveEvidenceProvider(tmp_path),
        complete_json=complete_json,
    )
    pack = provider.collect(
        query=str(feature["user_request"]),
        search_root="generated_mods/SyntheticMod",
        feature_data=feature,
    )

    assert roles == [
        "requirement_projection",
        "requirement_projection_correction",
        "requirement_findings",
    ]
    attempts = pack.budget_summary["requirement_projection_attempt_audit"]
    assert [attempt["status"] for attempt in attempts] == [
        "rejected",
        "accepted",
    ]
    assert attempts[0]["response_schema_admitted"] is False
    assert attempts[1]["semantic_materialization_admitted"] is True
    assert "Schema-invalid pair must not be retained." not in str(attempts)
    assert pack.readiness == "insufficient"
    assert pack.can_generate_patch is False


def test_second_schema_invalid_projection_fails_closed_with_bounded_audit(
    tmp_path: Path,
) -> None:
    _write_sources(tmp_path)
    feature = _feature_data()
    invalid = deepcopy(_projection())
    invalid["input_dispositions"] = [
        {
            "input_obligation_index": 4,
            "disposition": "post_change",
            "reason": "Invalid on both bounded attempts.",
        }
    ]
    roles: list[str] = []

    def complete_json(role, _payload, _schema):
        roles.append(role)
        if role.startswith("requirement_projection"):
            return deepcopy(invalid)
        raise AssertionError("findings must not be called")

    provider = make_requirement_coverage_evidence_provider(
        RgLiveEvidenceProvider(tmp_path),
        complete_json=complete_json,
    )
    pack = provider.collect(
        query=str(feature["user_request"]),
        search_root="generated_mods/SyntheticMod",
        feature_data=feature,
    )

    assert roles == [
        "requirement_projection",
        "requirement_projection_correction",
    ]
    assert pack.readiness == "insufficient"
    assert pack.can_generate_patch is False
    payload = pack.to_artifact_payload()
    assert payload["authoritative_for_patch"] is False
    attempts = pack.budget_summary["requirement_projection_attempt_audit"]
    assert len(attempts) == 2
    assert all(attempt["status"] == "rejected" for attempt in attempts)
    assert all(
        attempt["response_schema_admitted"] is False for attempt in attempts
    )
    assert all(
        attempt["structured_output_canonical_sha256"] for attempt in attempts
    )
    assert all(
        attempt["structured_output_hash_basis"] == "canonical_json_utf8"
        for attempt in attempts
    )
    assert pack.budget_summary["semantic_provider_failure_codes"] == [
        "REQUIREMENT_COVERAGE_PROJECTION_SCHEMA_INVALID"
    ]
    failure_diagnostic = pack.budget_summary[
        "semantic_provider_failure_diagnostics"
    ][0]
    assert failure_diagnostic["phase"] == "response_schema_admission"
    assert failure_diagnostic["failure_category"] == "disallowed_disposition"
    assert failure_diagnostic["json_path"] == (
        "$.input_dispositions[0].disposition"
    )
    assert "Invalid on both bounded attempts." not in str(pack.budget_summary)
    assert EvidencePack.from_artifact_payload(payload).to_artifact_payload() == payload


def test_formal_model_provider_handles_embedded_preservation_and_positive_pack(
    tmp_path: Path,
) -> None:
    _write_sources(tmp_path)
    feature = _feature_data()
    feature["non_goals"] = ["Do not add a new dependency."]
    calls: list[tuple[str, dict[str, object], dict[str, object]]] = []

    def complete_json(role, payload, schema):
        calls.append((role, dict(payload), dict(schema)))
        if role == "requirement_projection":
            return {
                "requirements": [
                    {
                        "role": "change",
                        "text": "Change the configurable marker behavior.",
                        "input_obligation_indexes": [1, 2],
                        "query_leads": ["ChangeMarker"],
                    },
                    {
                        "role": "preservation",
                        "text": "Preserve existing feedback from the user request.",
                        "input_obligation_indexes": [1],
                        "query_leads": ["ChangeMarker"],
                    },
                    {
                        "role": "pre_patch_evidence",
                        "text": "Confirm the configuration key.",
                        "input_obligation_indexes": [3],
                        "query_leads": ["ConfigKey"],
                    },
                    {
                        "role": "post_change_acceptance",
                        "text": "Observe runtime acceptance after patching.",
                        "input_obligation_indexes": [5, 6],
                        "query_leads": ["RuntimeMarker"],
                    },
                ],
                "relations": [
                    {
                        "parent_requirement_indexes": [1, 2],
                        "meaning": "Change and preservation share current behavior evidence.",
                    },
                    {
                        "parent_requirement_indexes": [3],
                        "meaning": "Configuration evidence exists before patching.",
                    },
                    {
                        "parent_requirement_indexes": [4],
                        "meaning": "Acceptance is observed after patching.",
                    },
                ],
                "input_dispositions": [
                    {
                        "input_obligation_index": 4,
                        "disposition": "scope_boundary",
                        "reason": "Dependency scope is a planning boundary, not source baseline evidence.",
                    }
                ],
            }
        if role == "requirement_findings":
            relations = payload["relations"]
            observations = payload["source_observations"]
            behavior_id = next(
                value["evidence_id"]
                for value in observations
                if str(value["source_path"]).endswith("Behavior.cs")
            )
            config_id = next(
                value["evidence_id"]
                for value in observations
                if str(value["source_path"]).endswith("Configuration.cs")
            )
            return {
                "findings": [
                    {
                        "relation_index": relations[0]["relation_index"],
                        "relationship": "support",
                        "evidence_ids": [behavior_id],
                        "unresolved_gaps": [],
                    },
                    {
                        "relation_index": relations[1]["relation_index"],
                        "relationship": "support",
                        "evidence_ids": [config_id],
                        "unresolved_gaps": [],
                    },
                    {
                        "relation_index": relations[2]["relation_index"],
                        "relationship": "missing",
                        "evidence_ids": [],
                        "unresolved_gaps": ["Observed after patching."],
                    },
                ]
            }
        raise AssertionError(f"Unexpected role: {role}")

    provider = make_requirement_coverage_evidence_provider(
        RgLiveEvidenceProvider(tmp_path),
        complete_json=complete_json,
    )
    pack = provider.collect(
        query=str(feature["user_request"]),
        search_root="generated_mods/SyntheticMod",
        feature_data=feature,
    )

    assert [call[0] for call in calls] == [
        "requirement_projection",
        "requirement_findings",
    ]
    projection_rules = calls[0][1]["rules"]
    assert any(
        "per-index values listed in input_obligations" in rule
        for rule in projection_rules
    )
    assert all(
        "allowed post-change dispositions" not in rule
        for rule in projection_rules
    )
    assert pack.readiness == "sufficient"
    assert pack.can_generate_patch is True
    coverage = pack.requirement_coverage
    assert any(
        requirement["role"] == "preservation"
        and requirement["input_obligation_ids"]
        for requirement in coverage["requirements"]
    )
    assert coverage["input_dispositions"][0]["disposition"] == "scope_boundary"
    for _, payload, schema in calls:
        serialized = str(payload) + str(schema)
        for forbidden in (
            "can_generate_patch",
            "edit_target_evidence_ids",
            "authoritative_for_patch",
            "source_ref",
        ):
            assert forbidden not in serialized


def test_formal_model_provider_invalid_accounting_fails_to_blocking_plan(
    tmp_path: Path,
) -> None:
    _write_sources(tmp_path)
    feature = _feature_data()
    calls: list[str] = []
    projection_schemas: list[dict[str, object]] = []

    def complete_json(role, _payload, schema):
        calls.append(role)
        projection_schemas.append(deepcopy(schema))
        return {
            "requirements": [
                {
                    "role": "change",
                    "text": "Incomplete change projection.",
                    "input_obligation_indexes": [2],
                    "query_leads": ["ChangeMarker"],
                }
            ],
            "relations": [
                {
                    "parent_requirement_indexes": [1],
                    "meaning": "Incomplete relation.",
                }
            ],
            "input_dispositions": [],
        }

    provider = make_requirement_coverage_evidence_provider(
        RgLiveEvidenceProvider(tmp_path),
        complete_json=complete_json,
    )
    pack = provider.collect(
        query=str(feature["user_request"]),
        search_root="generated_mods/SyntheticMod",
        feature_data=feature,
    )
    plan = ImplementationPlanner().build(
        feature_spec=_feature_spec(feature),
        evidence_pack=pack.to_artifact_payload(),
    )

    assert calls == [
        "requirement_projection",
        "requirement_projection_correction",
    ]
    assert projection_schemas[0] == projection_schemas[1]
    disposition_schema = projection_schemas[0]["properties"][
        "input_dispositions"
    ]
    assert disposition_schema["maxItems"] == 3
    assert not _schema_allows_input_disposition(
        projection_schemas[0],
        index=4,
        disposition="post_change",
    )
    assert pack.readiness == "insufficient"
    assert pack.can_generate_patch is False
    assert pack.budget_summary["semantic_provider_failed_closed"] is True
    assert plan.blocking is True
    assert plan.proposed_changes == ()

    calls.clear()
    graph_provider = make_requirement_coverage_evidence_provider(
        RgLiveEvidenceProvider(tmp_path),
        complete_json=complete_json,
    )
    store = ArtifactStore(tmp_path / "blocked_artifacts")
    graph = build_graph(
        store,
        evidence_pack_factory=lambda state, feature_data: graph_provider.collect(
            query=str(state["user_request"]),
            search_root="generated_mods/SyntheticMod",
            feature_data=feature_data,
        ),
    )
    result = graph.invoke(
        create_initial_state(
            run_id="run_formal_provider_blocked",
            request_id="req_formal_provider_blocked",
            user_request="Change the marker while preserving normal feedback.",
            target_mod="SyntheticMod",
        )
    )
    assert result["current_stage"] == "blocked"
    assert "implementation_plan" in result["artifacts"]
    assert "patch_proposal" not in result["artifacts"]


def test_formal_model_provider_graph_path_reaches_positive_plan(
    tmp_path: Path,
) -> None:
    source = tmp_path / "generated_mods" / "FormalMod" / "Behavior.cs"
    source.parent.mkdir(parents=True)
    source.write_text(
        "public sealed class Behavior\n"
        "{\n"
        "    public void ChangeMarker()\n"
        "    {\n"
        "        // preserve normal feedback target source API evidence config text\n"
        "        // runtime verification acceptance\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    calls: list[str] = []

    def complete_json(role, payload, _schema):
        calls.append(role)
        if role == "requirement_projection":
            obligations = payload["input_obligations"]
            change_indexes = [
                row["input_obligation_index"]
                for row in obligations
                if "change" in row["allowed_roles"]
            ]
            requirements = [
                {
                    "role": "change",
                    "text": "Change the marker behavior.",
                    "input_obligation_indexes": change_indexes,
                    "query_leads": ["ChangeMarker"],
                },
                {
                    "role": "preservation",
                    "text": "Preserve normal feedback requested by the user.",
                    "input_obligation_indexes": [1],
                    "query_leads": ["ChangeMarker"],
                },
            ]
            dispositions = []
            for row in obligations:
                index = row["input_obligation_index"]
                if index in change_indexes or index == 1:
                    continue
                if "scope_boundary" in row["allowed_dispositions"]:
                    dispositions.append(
                        {
                            "input_obligation_index": index,
                            "disposition": "scope_boundary",
                            "reason": "The non-goal is retained as a planning scope boundary.",
                        }
                    )
                elif "post_change" in row["allowed_dispositions"]:
                    dispositions.append(
                        {
                            "input_obligation_index": index,
                            "disposition": "post_change",
                            "reason": "This observation occurs after patching.",
                        }
                    )
                else:
                    requirements.append(
                        {
                            "role": row["allowed_roles"][0],
                            "text": row["text"],
                            "input_obligation_indexes": [index],
                            "query_leads": ["evidence"],
                        }
                    )
            return {
                "requirements": requirements,
                "relations": [
                    {
                        "parent_requirement_indexes": [index],
                        "meaning": f"Evidence disposition for requirement {index}.",
                    }
                    for index in range(1, len(requirements) + 1)
                ],
                "input_dispositions": dispositions,
            }
        if role == "requirement_findings":
            evidence_id = payload["source_observations"][0]["evidence_id"]
            return {
                "findings": [
                    {
                        "relation_index": relation["relation_index"],
                        "relationship": "support",
                        "evidence_ids": [evidence_id],
                        "unresolved_gaps": [],
                    }
                    for relation in payload["relations"]
                ]
            }
        raise AssertionError(role)

    provider = make_requirement_coverage_evidence_provider(
        RgLiveEvidenceProvider(tmp_path),
        complete_json=complete_json,
    )
    store = ArtifactStore(tmp_path / "formal_artifacts")
    graph = build_graph(
        store,
        evidence_pack_factory=lambda state, feature_data: provider.collect(
            query=str(state["user_request"]),
            search_root="generated_mods/FormalMod",
            feature_data=feature_data,
        ),
        interrupt_after=["create_implementation_plan"],
    )
    result = graph.invoke(
        create_initial_state(
            run_id="run_formal_positive",
            request_id="req_formal_positive",
            user_request="Change the marker while preserving normal feedback.",
            target_mod="FormalMod",
        )
    )

    assert calls == ["requirement_projection", "requirement_findings"]
    evidence = store.read(
        ArtifactRef(
            feature_id=result["feature_id"],
            artifact_type="evidence_pack",
            path=result["artifacts"]["evidence_pack"],
            artifact_hash=result["artifact_hashes"]["evidence_pack"],
        )
    )["data"]
    plan = store.read(
        ArtifactRef(
            feature_id=result["feature_id"],
            artifact_type="implementation_plan",
            path=result["artifacts"]["implementation_plan"],
            artifact_hash=result["artifact_hashes"]["implementation_plan"],
        )
    )["data"]
    assert evidence["readiness"] == "sufficient"
    assert plan["blocking"] is False
    assert plan["binding_registry"]["edit_bindings"]
    assert "patch_proposal" not in result["artifacts"]


def test_formal_model_provider_invalid_json_uses_one_correction_then_blocks(
    tmp_path: Path,
) -> None:
    _write_sources(tmp_path)
    roles: list[str] = []

    def complete_json(role, _payload, _schema):
        roles.append(role)
        raise ValueError("REQUIREMENT_COVERAGE_MODEL_INVALID_JSON")

    provider = make_requirement_coverage_evidence_provider(
        RgLiveEvidenceProvider(tmp_path),
        complete_json=complete_json,
    )
    pack = provider.collect(
        query=str(_feature_data()["user_request"]),
        search_root="generated_mods/SyntheticMod",
        feature_data=_feature_data(),
    )

    assert roles == [
        "requirement_projection",
        "requirement_projection_correction",
    ]
    assert pack.readiness == "insufficient"
    assert pack.can_generate_patch is False
    assert pack.budget_summary["semantic_provider_failed_closed"] is True
