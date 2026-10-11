"""Contracts for Evidence RAG output."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from src.mod_agent.knowledge import IDENTITY_FIELD_MAPPING, IDENTITY_SCHEMA_VERSION

EvidenceReadiness = Literal["sufficient", "partial", "insufficient", "contradictory"]
EvidenceAuthority = Literal["mod_agent_deterministic", "legacy_rag_auxiliary"]
EvidenceSourceAuthority = Literal["authoritative", "supporting", "lead"]
DETERMINISTIC_EVIDENCE_AUTHORITY = "mod_agent_deterministic"
LEGACY_RAG_AUXILIARY_AUTHORITY = "legacy_rag_auxiliary"
EVIDENCE_PACK_AUTHORITY = "mod_agent_deterministic_evidence"


@dataclass(frozen=True)
class EvidenceRequest:
    """Retrieval input produced by planning or feature-spec stages."""

    query: str
    execution_path: str = "standard_feature"
    requires_hook_evidence: bool = True
    hook_requirement: dict[str, Any] = field(
        default_factory=lambda: {"required": False, "reason": "not_required"}
    )
    source_ids: tuple[str, ...] = ()
    max_items: int = 10


@dataclass(frozen=True)
class EvidenceItem:
    """Single evidence item bound to source, method, and claim."""

    evidence_id: str
    source_type: str
    source_path: str
    symbol: str | None
    span: dict[str, int] | None
    retrieval_method: str
    score: float
    claim_supported: str
    excerpt: str
    chunk_id: str | None = None
    document_id: str | None = None
    source_ref: str | None = None
    source_hash: str | None = None
    file_hash: str | None = None
    doc_hash: str | None = None
    usage: str | None = None
    declaring_type: str | None = None
    method_name: str | None = None
    parameter_types: tuple[str, ...] | None = None
    return_type: str | None = None
    method_kind: str | None = None
    declared_member_types: dict[str, str] | None = None
    declaring_type_full_name: str | None = None
    declared_members: dict[str, dict[str, Any]] | None = None
    verified_member_accesses: tuple[dict[str, Any], ...] = ()
    authority: EvidenceAuthority = LEGACY_RAG_AUXILIARY_AUTHORITY
    source_authority: EvidenceSourceAuthority | None = None
    module_mvid: str | None = None
    metadata_token: str | None = None
    signature_blob: str | None = None
    risk_notes: tuple[str, ...] = ()
    document_provenance: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable evidence."""

        payload = {
            "evidence_id": self.evidence_id,
            "source_type": self.source_type,
            "source_path": self.source_path,
            "symbol": self.symbol,
            "span": self.span,
            "retrieval_method": self.retrieval_method,
            "score": self.score,
            "claim_supported": self.claim_supported,
            "excerpt": self.excerpt,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "source_ref": self.source_ref,
            "source_hash": self.source_hash,
            "file_hash": self.file_hash,
            "doc_hash": self.doc_hash,
            "usage": self.usage,
            "declaring_type": self.declaring_type,
            "method_name": self.method_name,
            "parameter_types": (
                list(self.parameter_types)
                if self.parameter_types is not None
                else None
            ),
            "return_type": self.return_type,
            "method_kind": self.method_kind,
            "declared_member_types": (
                dict(sorted(self.declared_member_types.items()))
                if self.declared_member_types is not None
                else None
            ),
            "declaring_type_full_name": self.declaring_type_full_name,
            "declared_members": (
                {
                    name: dict(value)
                    for name, value in sorted(self.declared_members.items())
                }
                if self.declared_members is not None
                else None
            ),
            "verified_member_accesses": [
                dict(item) for item in self.verified_member_accesses
            ],
            "authority": self.authority,
            "risk_notes": list(self.risk_notes),
        }
        if self.source_authority is not None:
            payload["source_authority"] = self.source_authority
        if self.module_mvid is not None:
            payload["module_mvid"] = self.module_mvid
        if self.metadata_token is not None:
            payload["metadata_token"] = self.metadata_token
        if self.signature_blob is not None:
            payload["signature_blob"] = self.signature_blob
        if self.document_provenance is not None:
            payload["document_provenance"] = dict(self.document_provenance)
        return payload


@dataclass(frozen=True)
class EvidencePack:
    """Evidence RAG output consumed by implementation planning and review."""

    query: str
    readiness: EvidenceReadiness
    can_generate_patch: bool
    items: tuple[EvidenceItem, ...] = ()
    gaps: tuple[str, ...] = ()
    excluded: tuple[dict[str, Any], ...] = ()
    blockers: tuple[dict[str, Any], ...] = ()
    retrieval_methods_used: tuple[str, ...] = ()
    missing_evidence: tuple[dict[str, Any], ...] = ()
    disabled_modes: dict[str, str] = field(default_factory=dict)
    timing: dict[str, float] = field(default_factory=dict)
    budget_summary: dict[str, Any] = field(default_factory=dict)
    trace_refs: tuple[str, ...] = ()
    run_status: str | None = None
    verified_findings: tuple[dict[str, Any], ...] = ()
    evidence_conclusions: tuple[dict[str, Any], ...] = ()
    observation_fact_catalog: tuple[dict[str, Any], ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    missing_capabilities: tuple[str, ...] = ()
    tool_trace_summary: tuple[dict[str, Any], ...] = ()
    model_action_trace: tuple[dict[str, Any], ...] = ()
    observation_trace: tuple[dict[str, Any], ...] = ()
    prompt_contract: dict[str, Any] = field(default_factory=dict)
    model_identity: dict[str, Any] = field(default_factory=dict)
    provenance_validation: dict[str, Any] = field(default_factory=dict)
    input_audit: dict[str, int] = field(default_factory=dict)
    intelligence_transfer: dict[str, bool] = field(default_factory=dict)
    hook_discovery: dict[str, Any] | None = None
    agent_discovery: dict[str, Any] | None = None
    requirement_coverage: dict[str, Any] | None = None
    message: str = ""

    def to_artifact_payload(self) -> dict[str, Any]:
        """Return payload compatible with the evidence_pack artifact contract."""

        message = self.message or (
            f"Evidence readiness is {self.readiness}; "
            f"{len(self.items)} evidence items retrieved."
        )
        payload = {
            "node_name": "retrieve_evidence",
            "stage": "evidence_retrieval",
            "message": message,
            "query": self.query,
            "readiness": self.readiness,
            "can_generate_patch": self.can_generate_patch,
            "authority": EVIDENCE_PACK_AUTHORITY,
            "authoritative_for_patch": self.can_generate_patch,
            "identity_schema_version": IDENTITY_SCHEMA_VERSION,
            "identity_field_mapping": dict(IDENTITY_FIELD_MAPPING),
            "items": [item.to_dict() for item in self.items],
            "gaps": list(self.gaps),
            "excluded": list(self.excluded),
            "blockers": list(self.blockers),
            "retrieval_methods_used": list(self.retrieval_methods_used),
            "missing_evidence": list(self.missing_evidence),
            "disabled_modes": dict(self.disabled_modes),
            "timing": dict(self.timing),
            "budget_summary": dict(self.budget_summary),
            "trace_refs": list(self.trace_refs),
            "run_status": self.run_status,
            "verified_findings": [dict(item) for item in self.verified_findings],
            "evidence_conclusions": [dict(item) for item in self.evidence_conclusions],
            "observation_fact_catalog": [
                dict(item) for item in self.observation_fact_catalog
            ],
            "unresolved_questions": list(self.unresolved_questions),
            "missing_capabilities": list(self.missing_capabilities),
            "tool_trace_summary": [dict(item) for item in self.tool_trace_summary],
            "model_action_trace": [dict(item) for item in self.model_action_trace],
            "observation_trace": [dict(item) for item in self.observation_trace],
            "prompt_contract": dict(self.prompt_contract),
            "model_identity": dict(self.model_identity),
            "provenance_validation": dict(self.provenance_validation),
            "input_audit": dict(self.input_audit),
            "intelligence_transfer": dict(self.intelligence_transfer),
        }
        if self.hook_discovery is not None:
            payload["hook_discovery"] = dict(self.hook_discovery)
        if self.agent_discovery is not None:
            payload["agent_discovery"] = dict(self.agent_discovery)
        if self.requirement_coverage is not None:
            payload["requirement_coverage"] = dict(self.requirement_coverage)
        return payload

    @staticmethod
    def requires_strict_semantic_rehydrate(payload: Mapping[str, Any]) -> bool:
        """Identify declared semantic sections without treating config as execution."""

        prompt_contract = payload.get("prompt_contract")
        return bool(
            "hook_discovery" in payload
            or "agent_discovery" in payload
            or "requirement_coverage" in payload
            or (
                isinstance(prompt_contract, Mapping)
                and isinstance(
                    prompt_contract.get("agent_discovery_sha256"), str
                )
                and bool(prompt_contract.get("agent_discovery_sha256"))
            )
        )

    @classmethod
    def from_artifact_payload(cls, payload: Mapping[str, Any]) -> "EvidencePack":
        """Strictly rehydrate a versioned Hook Discovery EvidencePack payload."""

        base_fields = {
            "node_name",
            "stage",
            "message",
            "query",
            "readiness",
            "can_generate_patch",
            "authority",
            "authoritative_for_patch",
            "identity_schema_version",
            "identity_field_mapping",
            "items",
            "gaps",
            "excluded",
            "blockers",
            "retrieval_methods_used",
            "missing_evidence",
            "disabled_modes",
            "timing",
            "budget_summary",
            "trace_refs",
            "run_status",
            "verified_findings",
            "evidence_conclusions",
            "observation_fact_catalog",
            "unresolved_questions",
            "missing_capabilities",
            "tool_trace_summary",
            "model_action_trace",
            "observation_trace",
            "prompt_contract",
            "model_identity",
            "provenance_validation",
            "input_audit",
            "intelligence_transfer",
        }
        semantic_fields = set(payload) - base_fields
        if semantic_fields not in (
            {"hook_discovery"},
            {"agent_discovery"},
            {"hook_discovery", "agent_discovery"},
            {"requirement_coverage"},
        ):
            raise ValueError("EVIDENCE_PACK_SEMANTIC_PAYLOAD_SHAPE_INVALID")
        if payload.get("node_name") != "retrieve_evidence":
            raise ValueError("EVIDENCE_PACK_NODE_NAME_INVALID")
        if payload.get("stage") != "evidence_retrieval":
            raise ValueError("EVIDENCE_PACK_STAGE_INVALID")
        if payload.get("authority") != EVIDENCE_PACK_AUTHORITY:
            raise ValueError("EVIDENCE_PACK_AUTHORITY_INVALID")
        if payload.get("identity_schema_version") != IDENTITY_SCHEMA_VERSION:
            raise ValueError("EVIDENCE_PACK_IDENTITY_VERSION_INVALID")
        if payload.get("identity_field_mapping") != dict(IDENTITY_FIELD_MAPPING):
            raise ValueError("EVIDENCE_PACK_IDENTITY_MAPPING_INVALID")
        readiness = payload.get("readiness")
        if readiness not in {"sufficient", "partial", "insufficient", "contradictory"}:
            raise ValueError("EVIDENCE_PACK_READINESS_INVALID")
        can_generate_patch = payload.get("can_generate_patch")
        authoritative_for_patch = payload.get("authoritative_for_patch")
        if not isinstance(can_generate_patch, bool) or not isinstance(
            authoritative_for_patch, bool
        ):
            raise ValueError("EVIDENCE_PACK_PLANNING_BOOLEAN_INVALID")
        if authoritative_for_patch != can_generate_patch:
            raise ValueError("EVIDENCE_PACK_PLANNING_AUTHORITY_MISMATCH")

        item_rows = _object_array(payload, "items")
        items = tuple(_evidence_item_from_artifact_payload(item) for item in item_rows)
        evidence_ids = [item.evidence_id for item in items]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("EVIDENCE_PACK_EVIDENCE_ID_DUPLICATE")

        hook_discovery = payload.get("hook_discovery")
        if hook_discovery is not None and not isinstance(hook_discovery, dict):
            raise ValueError("EVIDENCE_PACK_HOOK_DISCOVERY_MUST_BE_OBJECT")
        agent_discovery = payload.get("agent_discovery")
        if agent_discovery is not None and not isinstance(agent_discovery, dict):
            raise ValueError("EVIDENCE_PACK_AGENT_DISCOVERY_MUST_BE_OBJECT")
        requirement_coverage = payload.get("requirement_coverage")
        if requirement_coverage is not None and not isinstance(
            requirement_coverage, dict
        ):
            raise ValueError("EVIDENCE_PACK_REQUIREMENT_COVERAGE_MUST_BE_OBJECT")

        pack = cls(
            query=_required_payload_string(payload, "query"),
            readiness=readiness,
            can_generate_patch=can_generate_patch,
            items=items,
            gaps=tuple(_string_array(payload, "gaps")),
            excluded=tuple(_object_array(payload, "excluded")),
            blockers=tuple(_object_array(payload, "blockers")),
            retrieval_methods_used=tuple(
                _string_array(payload, "retrieval_methods_used")
            ),
            missing_evidence=tuple(_object_array(payload, "missing_evidence")),
            disabled_modes=_object(payload, "disabled_modes"),
            timing=_object(payload, "timing"),
            budget_summary=_object(payload, "budget_summary"),
            trace_refs=tuple(_string_array(payload, "trace_refs")),
            run_status=_optional_payload_string(payload, "run_status"),
            verified_findings=tuple(_object_array(payload, "verified_findings")),
            evidence_conclusions=tuple(
                _object_array(payload, "evidence_conclusions")
            ),
            observation_fact_catalog=tuple(
                _object_array(payload, "observation_fact_catalog")
            ),
            unresolved_questions=tuple(
                _string_array(payload, "unresolved_questions")
            ),
            missing_capabilities=tuple(
                _string_array(payload, "missing_capabilities")
            ),
            tool_trace_summary=tuple(_object_array(payload, "tool_trace_summary")),
            model_action_trace=tuple(_object_array(payload, "model_action_trace")),
            observation_trace=tuple(_object_array(payload, "observation_trace")),
            prompt_contract=_object(payload, "prompt_contract"),
            model_identity=_object(payload, "model_identity"),
            provenance_validation=_object(payload, "provenance_validation"),
            input_audit=_object(payload, "input_audit"),
            intelligence_transfer=_object(payload, "intelligence_transfer"),
            hook_discovery=(
                dict(hook_discovery) if isinstance(hook_discovery, dict) else None
            ),
            agent_discovery=(
                dict(agent_discovery) if isinstance(agent_discovery, dict) else None
            ),
            requirement_coverage=(
                dict(requirement_coverage)
                if isinstance(requirement_coverage, dict)
                else None
            ),
            message=_required_payload_string(payload, "message"),
        )

        from .discovery_contract import validate_agent_discovery_actual
        from .hook_discovery import validate_hook_discovery_evidence_pack
        from .requirement_coverage import (
            validate_requirement_coverage_evidence_pack,
        )

        agent_hash = pack.prompt_contract.get("agent_discovery_sha256")
        if pack.agent_discovery is not None:
            validate_agent_discovery_actual(pack.agent_discovery)
            expected_agent_hash = hashlib.sha256(
                json.dumps(
                    pack.agent_discovery,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if agent_hash != expected_agent_hash:
                raise ValueError("EVIDENCE_PACK_AGENT_DISCOVERY_HASH_INVALID")
        elif agent_hash is not None:
            raise ValueError("EVIDENCE_PACK_AGENT_DISCOVERY_HASH_WITHOUT_SECTION")
        if pack.hook_discovery is not None:
            validate_hook_discovery_evidence_pack(pack)
        elif pack.requirement_coverage is None:
            _validate_agent_discovery_early_termination_pack(pack)
        if pack.requirement_coverage is not None:
            validate_requirement_coverage_evidence_pack(pack)
        if pack.to_artifact_payload() != dict(payload):
            raise ValueError("EVIDENCE_PACK_SEMANTIC_ROUNDTRIP_MISMATCH")
        return pack

    @classmethod
    def empty(cls, *, query: str, reason: str) -> "EvidencePack":
        """Return an insufficient empty pack with a blocking reason."""

        blockers = (
            {
                "code": "INSUFFICIENT_EVIDENCE",
                "message": reason,
                "needed_evidence": [
                    "target source symbol",
                    "API reference",
                    "domain note",
                ],
            },
        )
        return cls(
            query=query,
            readiness="insufficient",
            can_generate_patch=False,
            gaps=(reason,),
            blockers=blockers,
            missing_evidence=missing_evidence_from_blockers(blockers),
            disabled_modes={
                "deterministic": reason,
                "bm25": "BM25 inverted index is not available for this evidence pack.",
                "dense": "Dense retrieval is not available for this evidence pack.",
                "fusion": "Fusion is not available for this evidence pack.",
                "rerank": "Rerank is not available for this evidence pack.",
                "neural_sparse": "Neural sparse retrieval is outside the V1 retrieval path.",
            },
            timing={
                "query_processing_ms": 0.0,
                "symbol_ms": 0.0,
                "text_ms": 0.0,
                "bm25_ms": 0.0,
                "dense_ms": 0.0,
                "fusion_ms": 0.0,
                "rerank_ms": 0.0,
                "readiness_ms": 0.0,
                "total_ms": 0.0,
                "final_count": 0.0,
                "excluded_count": 0.0,
            },
        )


def missing_evidence_from_blockers(
    blockers: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Build structured missing evidence entries from readiness blockers."""

    missing: list[dict[str, Any]] = []
    for blocker in blockers:
        blocker_code = str(blocker.get("code", "UNKNOWN_BLOCKER"))
        blocker_message = str(blocker.get("message", "Evidence is missing."))
        for needed in blocker.get("needed_evidence", []):
            missing.append(
                {
                    "needed_evidence": str(needed),
                    "blocker_code": blocker_code,
                    "reason": blocker_message,
                }
            )
    return tuple(missing)


def _evidence_item_from_artifact_payload(value: Mapping[str, Any]) -> EvidenceItem:
    required = {
        "evidence_id",
        "source_type",
        "source_path",
        "symbol",
        "span",
        "retrieval_method",
        "score",
        "claim_supported",
        "excerpt",
        "chunk_id",
        "document_id",
        "source_ref",
        "source_hash",
        "file_hash",
        "doc_hash",
        "usage",
        "declaring_type",
        "method_name",
        "parameter_types",
        "return_type",
        "method_kind",
        "declared_member_types",
        "declaring_type_full_name",
        "declared_members",
        "verified_member_accesses",
        "authority",
        "risk_notes",
    }
    optional = {"source_authority", "module_mvid", "metadata_token", "signature_blob", "document_provenance"}
    if not required.issubset(value) or set(value) - required - optional:
        raise ValueError("EVIDENCE_ITEM_PAYLOAD_SHAPE_INVALID")
    if value.get("authority") not in {
        DETERMINISTIC_EVIDENCE_AUTHORITY,
        LEGACY_RAG_AUXILIARY_AUTHORITY,
    }:
        raise ValueError("EVIDENCE_ITEM_AUTHORITY_INVALID")
    source_authority = value.get("source_authority")
    document_provenance = value.get("document_provenance")
    if document_provenance is not None and (not isinstance(document_provenance, dict) or value.get("source_type") != "domain_note"):
        raise ValueError("EVIDENCE_ITEM_DOCUMENT_PROVENANCE_INVALID")
    if source_authority is not None and source_authority not in {
        "authoritative",
        "supporting",
        "lead",
    }:
        raise ValueError("EVIDENCE_ITEM_SOURCE_AUTHORITY_INVALID")
    score = value.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        raise ValueError("EVIDENCE_ITEM_SCORE_INVALID")
    span = value.get("span")
    if span is not None and not isinstance(span, dict):
        raise ValueError("EVIDENCE_ITEM_SPAN_INVALID")
    parameter_types = value.get("parameter_types")
    if parameter_types is not None and (
        not isinstance(parameter_types, list)
        or not all(isinstance(item, str) for item in parameter_types)
    ):
        raise ValueError("EVIDENCE_ITEM_PARAMETER_TYPES_INVALID")
    declared_member_types = value.get("declared_member_types")
    if declared_member_types is not None and not isinstance(declared_member_types, dict):
        raise ValueError("EVIDENCE_ITEM_DECLARED_MEMBER_TYPES_INVALID")
    declared_members = value.get("declared_members")
    if declared_members is not None and not isinstance(declared_members, dict):
        raise ValueError("EVIDENCE_ITEM_DECLARED_MEMBERS_INVALID")
    verified_member_accesses = value.get("verified_member_accesses")
    if not isinstance(verified_member_accesses, list) or not all(
        isinstance(item, dict) for item in verified_member_accesses
    ):
        raise ValueError("EVIDENCE_ITEM_VERIFIED_ACCESSES_INVALID")
    risk_notes = value.get("risk_notes")
    if not isinstance(risk_notes, list) or not all(
        isinstance(item, str) for item in risk_notes
    ):
        raise ValueError("EVIDENCE_ITEM_RISK_NOTES_INVALID")
    string_fields = (
        "evidence_id",
        "source_type",
        "source_path",
        "retrieval_method",
        "claim_supported",
        "excerpt",
    )
    for field_name in string_fields:
        _required_payload_string(value, field_name)
    nullable_strings = (
        "symbol",
        "chunk_id",
        "document_id",
        "source_ref",
        "source_hash",
        "file_hash",
        "doc_hash",
        "usage",
        "declaring_type",
        "method_name",
        "return_type",
        "method_kind",
        "declaring_type_full_name",
        "module_mvid",
        "metadata_token",
        "signature_blob",
    )
    for field_name in nullable_strings:
        if field_name in value:
            _optional_payload_string(value, field_name)
    return EvidenceItem(
        evidence_id=str(value["evidence_id"]),
        source_type=str(value["source_type"]),
        source_path=str(value["source_path"]),
        symbol=value.get("symbol"),
        span=(dict(span) if isinstance(span, dict) else None),
        retrieval_method=str(value["retrieval_method"]),
        score=score,
        claim_supported=str(value["claim_supported"]),
        excerpt=str(value["excerpt"]),
        chunk_id=value.get("chunk_id"),
        document_id=value.get("document_id"),
        source_ref=value.get("source_ref"),
        source_hash=value.get("source_hash"),
        file_hash=value.get("file_hash"),
        doc_hash=value.get("doc_hash"),
        usage=value.get("usage"),
        declaring_type=value.get("declaring_type"),
        method_name=value.get("method_name"),
        parameter_types=(
            tuple(parameter_types) if isinstance(parameter_types, list) else None
        ),
        return_type=value.get("return_type"),
        method_kind=value.get("method_kind"),
        declared_member_types=(
            dict(declared_member_types)
            if isinstance(declared_member_types, dict)
            else None
        ),
        declaring_type_full_name=value.get("declaring_type_full_name"),
        declared_members=(
            dict(declared_members) if isinstance(declared_members, dict) else None
        ),
        verified_member_accesses=tuple(
            dict(item) for item in verified_member_accesses
        ),
        authority=value["authority"],
        source_authority=source_authority,
        module_mvid=value.get("module_mvid"),
        metadata_token=value.get("metadata_token"),
        signature_blob=value.get("signature_blob"),
        risk_notes=tuple(risk_notes),
        document_provenance=deepcopy(document_provenance) if document_provenance is not None else None,
    )


def _validate_agent_discovery_early_termination_pack(pack: EvidencePack) -> None:
    from .discovery_contract import (
        AGENT_DISCOVERY_LEGACY_PROMPT_CONTRACT_VERSIONS,
        AGENT_DISCOVERY_PROMPT_CONTRACT_VERSION,
        agent_discovery_early_termination_state,
    )

    if pack.agent_discovery is None:
        raise ValueError("EVIDENCE_PACK_SEMANTIC_SECTION_MISSING")
    state = agent_discovery_early_termination_state(pack.agent_discovery)
    expected_top = {
        "run_status": state["run_status"],
        "readiness": state["readiness"],
        "can_generate_patch": state["can_generate_patch"],
        "gaps": state["gaps"],
        "blockers": state["blockers"],
        "missing_evidence": state["missing_evidence"],
        "message": state["message"],
    }
    actual_top = {
        "run_status": pack.run_status,
        "readiness": pack.readiness,
        "can_generate_patch": pack.can_generate_patch,
        "gaps": pack.gaps,
        "blockers": pack.blockers,
        "missing_evidence": pack.missing_evidence,
        "message": pack.message,
    }
    if actual_top != expected_top:
        raise ValueError("EVIDENCE_PACK_EARLY_TERMINATION_PROJECTION_INVALID")
    if any(
        (
            pack.items,
            pack.excluded,
            pack.retrieval_methods_used,
            pack.trace_refs,
            pack.verified_findings,
            pack.evidence_conclusions,
            pack.observation_fact_catalog,
            pack.unresolved_questions,
            pack.missing_capabilities,
            pack.tool_trace_summary,
            pack.model_action_trace,
            pack.observation_trace,
        )
    ):
        raise ValueError("EVIDENCE_PACK_EARLY_TERMINATION_EXECUTION_FACTS_INVALID")
    expected_agent_hash = hashlib.sha256(
        json.dumps(
            pack.agent_discovery,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    prompt_version = pack.prompt_contract.get("version")
    prompt_contract_without_version = {
        key: value
        for key, value in pack.prompt_contract.items()
        if key != "version"
    }
    if prompt_version not in (
        AGENT_DISCOVERY_LEGACY_PROMPT_CONTRACT_VERSIONS
        | {AGENT_DISCOVERY_PROMPT_CONTRACT_VERSION}
    ) or prompt_contract_without_version != {
        "actual_planning_required": True,
        "agent_discovery_sha256": expected_agent_hash,
        "raw_prompt_persisted": False,
    }:
        raise ValueError("EVIDENCE_PACK_EARLY_TERMINATION_PROMPT_BINDING_INVALID")


def _required_payload_string(value: Mapping[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError(f"EVIDENCE_PACK_{key.upper()}_INVALID")
    return result


def _optional_payload_string(value: Mapping[str, Any], key: str) -> str | None:
    result = value.get(key)
    if result is not None and (not isinstance(result, str) or not result):
        raise ValueError(f"EVIDENCE_PACK_{key.upper()}_INVALID")
    return result


def _string_array(value: Mapping[str, Any], key: str) -> list[str]:
    result = value.get(key)
    if not isinstance(result, list) or not all(isinstance(item, str) for item in result):
        raise ValueError(f"EVIDENCE_PACK_{key.upper()}_INVALID")
    return list(result)


def _object_array(value: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    result = value.get(key)
    if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
        raise ValueError(f"EVIDENCE_PACK_{key.upper()}_INVALID")
    return [dict(item) for item in result]


def _object(value: Mapping[str, Any], key: str) -> dict[str, Any]:
    result = value.get(key)
    if not isinstance(result, dict):
        raise ValueError(f"EVIDENCE_PACK_{key.upper()}_INVALID")
    return dict(result)
