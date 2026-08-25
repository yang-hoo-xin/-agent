"""Provider orchestration for generic ProductExecution requirement coverage."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any, Protocol

from .models import EvidencePack, missing_evidence_from_blockers
from .requirement_coverage import (
    REQUIREMENT_ROLES,
    default_feature_requirement_projection,
    materialize_requirement_coverage_projection,
    requirement_input_obligation_model_view,
    resolve_requirement_coverage,
)

StructuredJsonCompletion = Callable[
    [str, Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]
]


class RequirementCoverageSemanticProvider(Protocol):
    """Propose bounded semantics without owning identities or authority."""

    def project(
        self,
        *,
        feature_data: Mapping[str, Any],
        request: str,
    ) -> Mapping[str, Any]: ...

    def findings(
        self,
        *,
        materialized_projection: Mapping[str, Any],
        retrieved_pack: EvidencePack,
        request: str,
    ) -> Mapping[str, Any]: ...


class StructuredModelRequirementCoverageProvider:
    """Use one admitted structured-model adapter with one bounded correction."""

    def __init__(self, complete_json: StructuredJsonCompletion) -> None:
        self.complete_json = complete_json

    def project(
        self,
        *,
        feature_data: Mapping[str, Any],
        request: str,
    ) -> Mapping[str, Any]:
        obligations = requirement_input_obligation_model_view(feature_data)
        schema = requirement_projection_response_schema(
            max_input_obligation_index=len(obligations)
        )
        payload = {
            "message_type": "product_requirement_projection",
            "request": request,
            "input_obligations": obligations,
            "rules": [
                "Return only requirement semantics, obligation indexes, focused query leads, relations, and allowed post-change dispositions.",
                "Every input obligation must be carried by one or more requirements or receive one allowed post-change disposition with a bounded reason.",
                "A user-request obligation may be carried by both change and preservation requirements when both semantics are present.",
                "Do not return stable ids, final required_before_patch, sufficiency, edit targets, paths, symbols, Patch authority, or execution authority.",
                "Do not use expected-side data, historical implementations, or prior outputs.",
            ],
        }
        projection: Mapping[str, Any] | None = None
        try:
            projection = self.complete_json(
                "requirement_projection", payload, schema
            )
            materialize_requirement_coverage_projection(
                feature_data=feature_data,
                request=request,
                projection=projection,
            )
        except ValueError as exc:
            correction = {
                **payload,
                "message_type": "product_requirement_projection_correction",
                "rejected_output_sha256": (
                    _json_sha256(projection) if projection is not None else None
                ),
                "error_code": str(exc),
                "instruction": (
                    "Return one complete corrected projection using the same schema; "
                    "do not patch the rejected output."
                ),
            }
            corrected = self.complete_json(
                "requirement_projection_correction", correction, schema
            )
            materialize_requirement_coverage_projection(
                feature_data=feature_data,
                request=request,
                projection=corrected,
            )
            return corrected
        return projection

    def findings(
        self,
        *,
        materialized_projection: Mapping[str, Any],
        retrieved_pack: EvidencePack,
        request: str,
    ) -> Mapping[str, Any]:
        relation_indexes = [
            int(relation["provenance"]["relation_index"])
            for relation in materialized_projection["relations"]
        ]
        evidence_ids = [item.evidence_id for item in retrieved_pack.items]
        schema = requirement_findings_response_schema(
            relation_indexes=relation_indexes,
            evidence_ids=evidence_ids,
        )
        payload = {
            "message_type": "product_requirement_findings",
            "request_sha256": hashlib.sha256(
                request.strip().encode("utf-8")
            ).hexdigest(),
            "requirements": [
                {
                    "requirement_id": requirement["requirement_id"],
                    "role": requirement["role"],
                    "text": requirement["text"],
                    "required_before_patch": requirement[
                        "required_before_patch"
                    ],
                }
                for requirement in materialized_projection["requirements"]
            ],
            "relations": [
                {
                    "relation_index": relation["provenance"]["relation_index"],
                    "relation_id": relation["relation_id"],
                    "parent_requirement_ids": list(
                        relation["parent_requirement_ids"]
                    ),
                    "meaning": relation["meaning"],
                }
                for relation in materialized_projection["relations"]
            ],
            "query_execution": list(
                retrieved_pack.budget_summary.get("per_query_execution", [])
            ),
            "source_observations": [
                _source_observation_model_view(item.to_dict())
                for item in retrieved_pack.items
            ],
            "rules": [
                "Return only support, conflict, or missing findings for listed relation indexes and evidence ids.",
                "Semantic findings are proposals; deterministic code validates every identity and derives sufficiency and authority.",
                "Do not return paths, source refs, stable ids, sufficiency, edit targets, Patch authority, or execution authority.",
                "State unresolved gaps explicitly and do not infer missing current source as support.",
            ],
        }
        findings: Mapping[str, Any] | None = None
        try:
            findings = self.complete_json("requirement_findings", payload, schema)
            resolve_requirement_coverage(
                query=request,
                materialized_projection=materialized_projection,
                items=retrieved_pack.items,
                findings=findings,
            )
        except ValueError as exc:
            correction = {
                **payload,
                "message_type": "product_requirement_findings_correction",
                "rejected_output_sha256": (
                    _json_sha256(findings) if findings is not None else None
                ),
                "error_code": str(exc),
                "instruction": (
                    "Return one complete corrected findings object using the same "
                    "listed identities and schema."
                ),
            }
            corrected = self.complete_json(
                "requirement_findings_correction", correction, schema
            )
            resolve_requirement_coverage(
                query=request,
                materialized_projection=materialized_projection,
                items=retrieved_pack.items,
                findings=corrected,
            )
            return corrected
        return findings


class RequirementCoverageEvidenceProvider:
    """Compose semantic providers, current-source retrieval, and pack assembly."""

    def __init__(
        self,
        source_provider: Any,
        *,
        semantic_provider: RequirementCoverageSemanticProvider | None = None,
        projection_factory: Callable[
            [Mapping[str, Any]], Mapping[str, Any]
        ]
        | None = None,
        findings_factory: Callable[
            [Mapping[str, Any], EvidencePack], Mapping[str, Any]
        ]
        | None = None,
    ) -> None:
        self.source_provider = source_provider
        self.semantic_provider = semantic_provider
        self.projection_factory = projection_factory
        self.findings_factory = findings_factory
        if semantic_provider is not None and (
            projection_factory is not None or findings_factory is not None
        ):
            raise ValueError("Choose semantic_provider or injected factories, not both.")

    def collect(
        self,
        *,
        query: str,
        search_root: str,
        feature_data: Mapping[str, Any],
    ) -> EvidencePack:
        provider_failure_codes: list[str] = []
        if self.semantic_provider is not None:
            try:
                projection = self.semantic_provider.project(
                    feature_data=feature_data,
                    request=query,
                )
            except ValueError as exc:
                provider_failure_codes.append(str(exc))
                projection = default_feature_requirement_projection(feature_data)
        elif self.projection_factory is not None:
            projection = self.projection_factory(feature_data)
        else:
            projection = default_feature_requirement_projection(feature_data)
        materialized = materialize_requirement_coverage_projection(
            feature_data=feature_data,
            request=query,
            projection=projection,
        )
        retrieved = self.source_provider.collect_query_set(
            queries=tuple(dict(item) for item in materialized["queries"]),
            search_root=search_root,
            max_items=max(1, len(materialized["queries"])),
        )
        if self.semantic_provider is not None:
            if provider_failure_codes:
                findings = {"findings": []}
            else:
                try:
                    findings = self.semantic_provider.findings(
                        materialized_projection=materialized,
                        retrieved_pack=retrieved,
                        request=query,
                    )
                except ValueError as exc:
                    provider_failure_codes.append(str(exc))
                    findings = {"findings": []}
        elif self.findings_factory is not None:
            findings = self.findings_factory(materialized, retrieved)
        else:
            findings = {"findings": []}
        pack = build_requirement_coverage_pack(
            query=query,
            materialized_projection=materialized,
            retrieved_pack=retrieved,
            findings=findings,
        )
        if not provider_failure_codes:
            return pack
        return replace(
            pack,
            budget_summary={
                **pack.budget_summary,
                "semantic_provider_failure_codes": provider_failure_codes,
                "semantic_provider_failed_closed": True,
            },
            message=(
                "The bounded semantic provider failed validation; deterministic "
                "fallback retained observations without Patch authority."
            ),
        )


def make_requirement_coverage_evidence_provider(
    source_provider: Any,
    *,
    complete_json: StructuredJsonCompletion,
    projection_factory: Callable[
        [Mapping[str, Any]], Mapping[str, Any]
    ]
    | None = None,
    findings_factory: Callable[
        [Mapping[str, Any], EvidencePack], Mapping[str, Any]
    ]
    | None = None,
) -> RequirementCoverageEvidenceProvider:
    """Select the formal model path unless explicit test seams are injected."""

    semantic_provider = (
        StructuredModelRequirementCoverageProvider(complete_json)
        if projection_factory is None and findings_factory is None
        else None
    )
    return RequirementCoverageEvidenceProvider(
        source_provider,
        semantic_provider=semantic_provider,
        projection_factory=projection_factory,
        findings_factory=findings_factory,
    )


def build_requirement_coverage_pack(
    *,
    query: str,
    materialized_projection: Mapping[str, Any],
    retrieved_pack: EvidencePack,
    findings: Mapping[str, Any],
) -> EvidencePack:
    """Assemble one EvidencePack from authority-core output."""

    section, readiness, can_generate_patch, blockers, gaps = (
        resolve_requirement_coverage(
            query=query,
            materialized_projection=materialized_projection,
            items=retrieved_pack.items,
            findings=findings,
        )
    )
    return EvidencePack(
        query=query,
        readiness=readiness,
        can_generate_patch=can_generate_patch,
        items=retrieved_pack.items,
        gaps=gaps,
        excluded=retrieved_pack.excluded,
        blockers=blockers,
        retrieval_methods_used=retrieved_pack.retrieval_methods_used,
        missing_evidence=missing_evidence_from_blockers(blockers),
        disabled_modes=dict(retrieved_pack.disabled_modes),
        timing=dict(retrieved_pack.timing),
        budget_summary=dict(retrieved_pack.budget_summary),
        requirement_coverage=section,
        message=(
            "Current-source evidence satisfies every required pre-patch requirement."
            if can_generate_patch
            else "Requirement coverage is incomplete or conflicting; patch authority is blocked."
        ),
    )


def requirement_projection_response_schema(
    *, max_input_obligation_index: int
) -> dict[str, object]:
    requirement = {
        "type": "object",
        "properties": {
            "role": {"type": "string", "enum": sorted(REQUIREMENT_ROLES)},
            "text": {"type": "string", "minLength": 1},
            "input_obligation_indexes": {
                "type": "array",
                "minItems": 1,
                "maxItems": max_input_obligation_index,
                "items": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": max_input_obligation_index,
                },
            },
            "query_leads": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": {"type": "string", "minLength": 1},
            },
        },
        "required": [
            "role",
            "text",
            "input_obligation_indexes",
            "query_leads",
        ],
        "additionalProperties": False,
    }
    relation = {
        "type": "object",
        "properties": {
            "parent_requirement_indexes": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": {"type": "integer", "minimum": 1, "maximum": 16},
            },
            "meaning": {"type": "string", "minLength": 1},
        },
        "required": ["parent_requirement_indexes", "meaning"],
        "additionalProperties": False,
    }
    disposition = {
        "type": "object",
        "properties": {
            "input_obligation_index": {
                "type": "integer",
                "minimum": 1,
                "maximum": max_input_obligation_index,
            },
            "disposition": {
                "type": "string",
                "enum": ["post_change", "scope_boundary"],
            },
            "reason": {"type": "string", "minLength": 1},
        },
        "required": ["input_obligation_index", "disposition", "reason"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "requirements": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": requirement,
            },
            "relations": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "items": relation,
            },
            "input_dispositions": {
                "type": "array",
                "maxItems": max_input_obligation_index,
                "items": disposition,
            },
        },
        "required": ["requirements", "relations", "input_dispositions"],
        "additionalProperties": False,
    }


def requirement_findings_response_schema(
    *, relation_indexes: list[int], evidence_ids: list[str]
) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "maxItems": len(relation_indexes),
                "items": {
                    "type": "object",
                    "properties": {
                        "relation_index": {
                            "type": "integer",
                            "enum": relation_indexes,
                        },
                        "relationship": {
                            "type": "string",
                            "enum": ["support", "conflict", "missing"],
                        },
                        "evidence_ids": {
                            "type": "array",
                            "uniqueItems": True,
                            "items": {"type": "string", "enum": evidence_ids},
                        },
                        "unresolved_gaps": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                    "required": [
                        "relation_index",
                        "relationship",
                        "evidence_ids",
                        "unresolved_gaps",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["findings"],
        "additionalProperties": False,
    }


def _source_observation_model_view(item: Mapping[str, Any]) -> dict[str, object]:
    return {
        key: item.get(key)
        for key in (
            "evidence_id",
            "source_type",
            "source_path",
            "symbol",
            "span",
            "source_hash",
            "file_hash",
            "doc_hash",
            "retrieval_method",
            "claim_supported",
            "excerpt",
        )
    }


def _json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
