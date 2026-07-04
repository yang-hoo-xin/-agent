"""Implementation planning from feature specs and evidence packs."""

from __future__ import annotations

from typing import Any

from src.mod_agent.knowledge import IDENTITY_FIELD_MAPPING, IDENTITY_SCHEMA_VERSION

from src.mod_agent.evidence.models import (
    DETERMINISTIC_EVIDENCE_AUTHORITY,
    EVIDENCE_PACK_AUTHORITY,
    LEGACY_RAG_AUXILIARY_AUTHORITY,
)
from .models import FeatureSpec, ImplementationPlan

EDITABLE_EVIDENCE_SOURCE_TYPES = frozenset({"target_source"})
AUTHORITATIVE_EVIDENCE_PACK = EVIDENCE_PACK_AUTHORITY
AUTHORITATIVE_ITEM_AUTHORITY = DETERMINISTIC_EVIDENCE_AUTHORITY
EVIDENCE_ITEM_PROVENANCE_FIELDS = frozenset(
    {"chunk_id", "document_id", "source_ref", "source_hash", "file_hash", "doc_hash"}
)


class ImplementationPlanner:
    """Create an evidence-bound implementation plan without producing a patch."""

    def build(
        self,
        *,
        feature_spec: FeatureSpec,
        evidence_pack: dict[str, Any],
    ) -> ImplementationPlan:
        """Return an implementation plan or a blocking result."""

        if feature_spec.blocked:
            return self._blocked(
                feature_id=feature_spec.feature_id,
                blockers=feature_spec.blockers,
                open_questions=("Feature spec is blocked.",),
            )

        if evidence_pack.get("readiness") != "sufficient" or not evidence_pack.get(
            "can_generate_patch"
        ):
            blockers = tuple(evidence_pack.get("blockers") or ())
            open_questions = tuple(
                str(gap) for gap in evidence_pack.get("gaps", ["Evidence is not sufficient."])
            )
            return self._blocked(
                feature_id=feature_spec.feature_id,
                blockers=blockers,
                open_questions=open_questions,
            )

        if (
            evidence_pack.get("authority") != AUTHORITATIVE_EVIDENCE_PACK
            or evidence_pack.get("authoritative_for_patch") is not True
        ):
            return self._blocked(
                feature_id=feature_spec.feature_id,
                blockers=(
                    {
                        "code": "NON_AUTHORITATIVE_EVIDENCE_PACK",
                        "message": (
                            "Only mod_agent deterministic evidence packs can "
                            "advance implementation planning."
                        ),
                    },
                ),
                open_questions=(
                    "Resolve mod_agent deterministic evidence before planning edits.",
                ),
            )

        if (
            evidence_pack.get("identity_schema_version") != IDENTITY_SCHEMA_VERSION
            or evidence_pack.get("identity_field_mapping") != dict(IDENTITY_FIELD_MAPPING)
        ):
            return self._blocked(
                feature_id=feature_spec.feature_id,
                blockers=(
                    {
                        "code": "UNVERIFIED_EVIDENCE_PROVENANCE",
                        "message": (
                            "Authoritative evidence packs must carry the current "
                            "identity schema and field mapping."
                        ),
                    },
                ),
                open_questions=("Resolve provenance-validated evidence before planning edits.",),
            )

        raw_items = list(evidence_pack.get("items") or [])
        items = [item for item in raw_items if isinstance(item, dict)]
        if len(items) != len(raw_items):
            return self._blocked(
                feature_id=feature_spec.feature_id,
                blockers=(
                    {
                        "code": "MALFORMED_EVIDENCE_ITEMS",
                        "message": "Evidence pack items must be mappings.",
                    },
                ),
                open_questions=("Regenerate evidence with structured evidence items.",),
            )
        missing_authority_items = [
            item
            for item in items
            if "authority" not in item
        ]
        if missing_authority_items:
            return self._blocked(
                feature_id=feature_spec.feature_id,
                blockers=(
                    {
                        "code": "NON_AUTHORITATIVE_EVIDENCE_ITEM",
                        "message": (
                            "Every evidence item used for implementation planning "
                            "must be mod_agent deterministic evidence."
                        ),
                    },
                ),
                open_questions=("Regenerate evidence with explicit item authority.",),
            )
        unsupported_authority_items = [
            item
            for item in items
            if item.get("authority")
            not in {AUTHORITATIVE_ITEM_AUTHORITY, LEGACY_RAG_AUXILIARY_AUTHORITY}
        ]
        if unsupported_authority_items:
            return self._blocked(
                feature_id=feature_spec.feature_id,
                blockers=(
                    {
                        "code": "UNSUPPORTED_EVIDENCE_ITEM_AUTHORITY",
                        "message": "Evidence item authority is not recognized.",
                    },
                ),
                open_questions=("Regenerate evidence with recognized item authority.",),
            )
        planning_items = [
            item for item in items if item.get("authority") == AUTHORITATIVE_ITEM_AUTHORITY
        ]
        if not planning_items:
            return self._blocked(
                feature_id=feature_spec.feature_id,
                blockers=(
                    {
                        "code": "MISSING_AUTHORITATIVE_EVIDENCE_ITEM",
                        "message": (
                            "Implementation planning requires at least one "
                            "mod_agent deterministic evidence item."
                        ),
                    },
                ),
                open_questions=("Resolve mod_agent deterministic evidence before planning edits.",),
            )
        unprovenanced_items = [
            item
            for item in planning_items
            if not any(item.get(field) for field in EVIDENCE_ITEM_PROVENANCE_FIELDS)
        ]
        if unprovenanced_items:
            return self._blocked(
                feature_id=feature_spec.feature_id,
                blockers=(
                    {
                        "code": "UNVERIFIED_EVIDENCE_ITEM_PROVENANCE",
                        "message": (
                            "Every evidence item used for implementation planning "
                            "must carry source identity metadata."
                        ),
                    },
                ),
                open_questions=("Regenerate evidence with item provenance metadata.",),
            )

        evidence_refs = tuple(
            item["evidence_id"] for item in planning_items if item.get("evidence_id")
        )
        evidence_source_paths = tuple(
            dict.fromkeys(
                item["source_path"] for item in planning_items if item.get("source_path")
            )
        )
        editable_items = [
            item
            for item in planning_items
            if item.get("evidence_id")
            and item.get("source_path")
            and item.get("source_type") in EDITABLE_EVIDENCE_SOURCE_TYPES
        ]
        target_files = tuple(
            dict.fromkeys(item["source_path"] for item in editable_items)
        )
        target_symbols = tuple(
            dict.fromkeys(item["symbol"] for item in editable_items if item.get("symbol"))
        )
        if not evidence_refs:
            return self._blocked(
                feature_id=feature_spec.feature_id,
                blockers=(
                    {
                        "code": "MISSING_EVIDENCE_BINDING",
                        "message": "Sufficient readiness was claimed without evidence refs.",
                    },
                ),
                open_questions=("Evidence pack lacks evidence ids.",),
                evidence_source_paths=evidence_source_paths,
            )

        if not target_files:
            return self._blocked(
                feature_id=feature_spec.feature_id,
                blockers=(
                    {
                        "code": "EDIT_TARGET_UNRESOLVED",
                        "message": (
                            "Evidence sources do not resolve to an editable target source."
                        ),
                        "evidence_source_paths": list(evidence_source_paths),
                    },
                ),
                open_questions=(
                    "Resolve an editable target source before patch proposal generation.",
                ),
                evidence_source_paths=evidence_source_paths,
            )

        proposed_changes = tuple(
            {
                "change_id": f"chg_{index:03d}",
                "change_type": "modify_behavior",
                "evidence_source_path": item.get("source_path"),
                "edit_target_path": item.get("source_path"),
                "target_file": item.get("source_path"),
                "target_symbol": item.get("symbol"),
                "operation": "minimal_evidence_bound_change",
                "rationale": feature_spec.target_behavior,
                "evidence_refs": [item["evidence_id"]],
                "risk_tags": [feature_spec.risk_level],
                "expected_validation": list(feature_spec.runtime_verification_plan),
                "rollback_hint": "Revert this change unit or restore previous behavior.",
            }
            for index, item in enumerate(editable_items, start=1)
        )

        return ImplementationPlan(
            feature_id=feature_spec.feature_id,
            target_files=target_files,
            target_symbols=target_symbols,
            evidence_refs=evidence_refs,
            proposed_changes=proposed_changes,
            side_effect_boundaries=feature_spec.non_goals,
            test_plan=feature_spec.runtime_verification_plan,
            rollback_plan=tuple(
                f"Rollback {change['change_id']}: {change['rollback_hint']}"
                for change in proposed_changes
            ),
            open_questions=(),
            blocking=False,
            evidence_source_paths=evidence_source_paths,
        )

    @staticmethod
    def _blocked(
        *,
        feature_id: str,
        blockers: tuple[dict[str, Any], ...],
        open_questions: tuple[str, ...],
        evidence_source_paths: tuple[str, ...] = (),
    ) -> ImplementationPlan:
        return ImplementationPlan(
            feature_id=feature_id,
            target_files=(),
            target_symbols=(),
            evidence_refs=(),
            proposed_changes=(),
            side_effect_boundaries=(),
            test_plan=(),
            rollback_plan=(),
            open_questions=open_questions,
            blocking=True,
            blockers=blockers,
            evidence_source_paths=evidence_source_paths,
        )
