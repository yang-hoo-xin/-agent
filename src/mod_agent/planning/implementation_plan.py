"""Implementation planning from feature specs and evidence packs."""

from __future__ import annotations

from typing import Any

from src.mod_agent.evidence.models import (
    DETERMINISTIC_EVIDENCE_AUTHORITY,
    EVIDENCE_PACK_AUTHORITY,
    LEGACY_RAG_AUXILIARY_AUTHORITY,
)
from src.mod_agent.knowledge import IDENTITY_FIELD_MAPPING, IDENTITY_SCHEMA_VERSION

from .models import FeatureSpec, ImplementationPlan

EDITABLE_EVIDENCE_SOURCE_TYPES = frozenset({"target_source"})
HOOK_TARGET_SOURCE_TYPE = "decompiled_api"
HOOK_TARGET_USAGE = "hook_target"
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

        edit_bindings = tuple(
            self._edit_binding(index=index, item=item)
            for index, item in enumerate(editable_items, start=1)
        )
        supporting_bindings = self._supporting_bindings(planning_items)
        binding_registry = self._binding_registry(
            edit_bindings=edit_bindings,
            supporting_bindings=supporting_bindings,
        )
        hook_target_binding_id, hook_target_blocker = self._select_hook_target_binding(
            feature_spec=feature_spec,
            binding_registry=binding_registry,
        )
        if hook_target_blocker is not None:
            return self._blocked(
                feature_id=feature_spec.feature_id,
                blockers=(hook_target_blocker,),
                open_questions=(hook_target_blocker["message"],),
                evidence_source_paths=evidence_source_paths,
            )
        proposed_changes = tuple(
            self._proposed_change(
                index=index,
                feature_spec=feature_spec,
                hook_target_binding_id=hook_target_binding_id,
            )
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
            binding_registry=binding_registry,
        )

    @staticmethod
    def _edit_binding(
        *,
        index: int,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "binding_id": f"edit_binding_{index:03d}",
            "evidence_id": item.get("evidence_id"),
            "canonical_target_path": item.get("source_path"),
            "source_type": item.get("source_type"),
            "target_symbol": item.get("symbol"),
            "target_span": item.get("span"),
            "declaring_type": item.get("declaring_type"),
            "method_name": item.get("method_name"),
            "parameter_types": (
                list(item["parameter_types"])
                if isinstance(item.get("parameter_types"), (list, tuple))
                else None
            ),
            "return_type": item.get("return_type"),
            "method_kind": item.get("method_kind"),
            "retrieval_method": item.get("retrieval_method"),
            "claim_supported": item.get("claim_supported"),
            "authority": item.get("authority"),
            "usage": "edit_target_scope",
        }

    @classmethod
    def _supporting_bindings(
        cls,
        items: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], ...]:
        bindings: list[dict[str, Any]] = []
        hook_target_index = 1
        for item in items:
            is_hook_target = (
                item.get("source_type") == HOOK_TARGET_SOURCE_TYPE
                and item.get("usage") == HOOK_TARGET_USAGE
            )
            binding_id = (
                f"hook_target_{hook_target_index:03d}"
                if is_hook_target
                else f"support_binding_{item.get('evidence_id')}"
            )
            if is_hook_target:
                hook_target_index += 1
            bindings.append(cls._supporting_binding(item=item, binding_id=binding_id))
        return tuple(bindings)

    @staticmethod
    def _supporting_binding(
        *,
        item: dict[str, Any],
        binding_id: str,
    ) -> dict[str, Any]:
        return {
            "binding_id": binding_id,
            "evidence_id": item.get("evidence_id"),
            "source_path": item.get("source_path"),
            "source_type": item.get("source_type"),
            "target_symbol": item.get("symbol"),
            "target_span": item.get("span"),
            "declaring_type": item.get("declaring_type"),
            "method_name": item.get("method_name"),
            "parameter_types": (
                list(item["parameter_types"])
                if isinstance(item.get("parameter_types"), (list, tuple))
                else None
            ),
            "return_type": item.get("return_type"),
            "method_kind": item.get("method_kind"),
            "retrieval_method": item.get("retrieval_method"),
            "claim_supported": item.get("claim_supported"),
            "authority": item.get("authority"),
            "usage": (
                "edit_source_evidence"
                if item.get("source_type") in EDITABLE_EVIDENCE_SOURCE_TYPES
                else HOOK_TARGET_USAGE
                if item.get("source_type") == HOOK_TARGET_SOURCE_TYPE
                and item.get("usage") == HOOK_TARGET_USAGE
                else "hook_target_or_supporting_evidence"
            ),
        }

    @staticmethod
    def _binding_registry(
        *,
        edit_bindings: tuple[dict[str, Any], ...],
        supporting_bindings: tuple[dict[str, Any], ...],
    ) -> dict[str, Any]:
        edit_evidence_ids = {
            str(binding["evidence_id"])
            for binding in edit_bindings
            if binding.get("evidence_id")
        }
        return {
            "schema_version": "binding_registry_v1",
            "owner_artifact_type": "implementation_plan",
            "edit_bindings": [dict(binding) for binding in edit_bindings],
            "supporting_bindings": [
                dict(binding)
                for binding in supporting_bindings
                if binding.get("evidence_id")
                and str(binding["evidence_id"]) not in edit_evidence_ids
            ],
        }

    @classmethod
    def _select_hook_target_binding(
        cls,
        *,
        feature_spec: FeatureSpec,
        binding_registry: dict[str, Any],
    ) -> tuple[str | None, dict[str, Any] | None]:
        if feature_spec.hook_requirement.get("required") is not True:
            return None, None
        hook_bindings = [
            binding
            for binding in binding_registry.get("supporting_bindings") or []
            if isinstance(binding, dict)
            and binding.get("usage") == HOOK_TARGET_USAGE
        ]
        complete_bindings = [
            binding for binding in hook_bindings if cls._has_complete_hook_target_identity(binding)
        ]
        if len(complete_bindings) == 1:
            return str(complete_bindings[0]["binding_id"]), None
        if len(complete_bindings) > 1:
            return None, {
                "code": "AMBIGUOUS_HOOK_TARGET",
                "message": (
                    "Hook-required planning found multiple complete hook targets "
                    "and no single selected target."
                ),
                "binding_ids": [
                    str(binding["binding_id"]) for binding in complete_bindings
                ],
            }
        return None, {
            "code": "MISSING_CONCRETE_HOOK_TARGET_EVIDENCE",
            "message": (
                "Hook-required planning requires one selected decompiled API "
                "method with complete target identity."
            ),
        }

    @staticmethod
    def _has_complete_hook_target_identity(binding: dict[str, Any]) -> bool:
        return (
            binding.get("source_type") == HOOK_TARGET_SOURCE_TYPE
            and binding.get("usage") == HOOK_TARGET_USAGE
            and bool(binding.get("target_symbol"))
            and bool(binding.get("target_span"))
            and bool(binding.get("declaring_type"))
            and bool(binding.get("method_name"))
            and isinstance(binding.get("parameter_types"), list)
            and bool(binding.get("return_type"))
            and bool(binding.get("method_kind"))
        )

    @staticmethod
    def _proposed_change(
        *,
        index: int,
        feature_spec: FeatureSpec,
        hook_target_binding_id: str | None,
    ) -> dict[str, Any]:
        change = {
            "change_id": f"chg_{index:03d}",
            "change_type": "modify_behavior",
            "edit_binding_id": f"edit_binding_{index:03d}",
            "supporting_binding_ids": [],
            "operation": "minimal_evidence_bound_change",
            "rationale": feature_spec.target_behavior,
            "risk_tags": [feature_spec.risk_level],
            "expected_validation": list(feature_spec.runtime_verification_plan),
            "rollback_hint": "Revert this change unit or restore previous behavior.",
        }
        if hook_target_binding_id is not None:
            change["hook_target_binding_id"] = hook_target_binding_id
        return change

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
