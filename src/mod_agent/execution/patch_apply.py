"""Fail-closed exact-text patch validation and isolated application."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any

from src.mod_agent.bindings import BindingResolver


class PatchApplyError(RuntimeError):
    """Raised when an executable patch is unsafe, stale, or ambiguous."""


class ExactTextPatchApplier:
    """Validate exact replacements and optionally write them inside one workspace."""

    def run(
        self,
        *,
        workspace_root: str | Path,
        proposal: dict[str, Any],
        implementation_plan: dict[str, Any],
        review: dict[str, Any],
        allow_write: bool,
        approved_diff_hash: str | None = None,
    ) -> dict[str, Any]:
        if review.get("allowed_next_stage") != "dry_run_apply":
            raise PatchApplyError("Proposal review did not allow dry-run apply.")
        root = Path(workspace_root).resolve()
        if not root.is_dir():
            raise PatchApplyError("Patch workspace does not exist or is not a directory.")

        resolver = BindingResolver.from_implementation_plan(implementation_plan)
        staged: dict[Path, str] = {}
        file_results: list[dict[str, Any]] = []
        diff_preview: list[dict[str, Any]] = []
        for index, change in enumerate(proposal.get("diff_intent") or [], start=1):
            binding_id = str(change.get("edit_binding_id") or "")
            paths = resolver.display_files_for_edit_ids([binding_id])
            if len(paths) != 1:
                raise PatchApplyError(f"Change {index} does not resolve to one edit path.")
            relative = _safe_relative_path(paths[0])
            target = (root / relative).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise PatchApplyError(f"Change {index} escapes the isolated workspace.") from exc
            if not target.is_file():
                raise PatchApplyError(f"Change {index} target file is missing: {relative}")

            patch = change.get("patch")
            if not isinstance(patch, dict) or patch.get("kind") != "exact_text_replace":
                raise PatchApplyError(f"Change {index} has no executable exact-text patch.")
            before = patch.get("before_text")
            after = patch.get("after_text")
            if not isinstance(before, str) or not isinstance(after, str) or before == after:
                raise PatchApplyError(f"Change {index} patch text is invalid or a no-op.")

            current = staged.get(target, target.read_text(encoding="utf-8"))
            count = current.count(before)
            if patch.get("expected_occurrences") != 1 or count != 1:
                raise PatchApplyError(
                    f"Change {index} expected one live source match but found {count}."
                )
            updated = current.replace(before, after, 1)
            staged[target] = updated
            file_results.append(
                {
                    "change_id": change.get("change_id"),
                    "edit_binding_id": binding_id,
                    "path": relative.as_posix(),
                    "before_sha256": _sha256_text(current),
                    "after_sha256": _sha256_text(updated),
                    "matched_occurrences": count,
                }
            )
            diff_preview.append(
                {
                    "change_id": change.get("change_id"),
                    "edit_binding_id": binding_id,
                    "path": relative.as_posix(),
                    "before_text": before,
                    "after_text": after,
                    "expected_occurrences": 1,
                    "before_sha256": _sha256_text(current),
                    "after_sha256": _sha256_text(updated),
                }
            )

        if not staged:
            raise PatchApplyError("Proposal contains no executable changes.")
        context_hashes = {
            "proposal_payload_sha256": _sha256_json(proposal),
            "implementation_plan_payload_sha256": _sha256_json(implementation_plan),
            "evidence_artifact_hash": _evidence_artifact_hash(proposal),
            "source_snapshot_sha256": _sha256_json(
                [
                    {
                        "path": item["path"],
                        "before_sha256": item["before_sha256"],
                    }
                    for item in diff_preview
                ]
            ),
        }
        diff_hash = _diff_hash(
            proposal_id=str(proposal.get("proposal_id") or ""),
            diff_preview=diff_preview,
            context_hashes=context_hashes,
        )
        if allow_write:
            if approved_diff_hash is None:
                raise PatchApplyError("Exact diff hash approval is required before writing.")
            if approved_diff_hash != diff_hash:
                raise PatchApplyError(
                    "Approved diff hash does not match the current exact patch."
                )
            for target, content in staged.items():
                temporary = target.with_name(f".{target.name}.v2-codegen.tmp")
                temporary.write_text(content, encoding="utf-8", newline="")
                os.replace(temporary, target)

        return {
            "execution_mode": "isolated_apply" if allow_write else "dry_run",
            "actual_write_performed": allow_write,
            "real_patch_applied": allow_write,
            "approved_by_review": True,
            "review_decision": review.get("decision"),
            "proposal_id": proposal.get("proposal_id"),
            "diff_hash": diff_hash,
            "approved_diff_hash": approved_diff_hash,
            "approved_by_user": allow_write and approved_diff_hash == diff_hash,
            "context_hashes": context_hashes,
            "diff_preview": diff_preview,
            "changed_files": sorted({item["path"] for item in file_results}),
            "changes": file_results,
        }


def _safe_relative_path(raw: str) -> Path:
    normalized = PurePosixPath(raw.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise PatchApplyError("Edit binding path must be workspace-relative.")
    return Path(*normalized.parts)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _diff_hash(
    *,
    proposal_id: str,
    diff_preview: list[dict[str, Any]],
    context_hashes: dict[str, Any],
) -> str:
    canonical = json.dumps(
        {
            "proposal_id": proposal_id,
            "context_hashes": context_hashes,
            "changes": diff_preview,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _evidence_artifact_hash(proposal: dict[str, Any]) -> str | None:
    context_pack = proposal.get("context_pack")
    if not isinstance(context_pack, dict):
        return None
    artifact_hashes = context_pack.get("artifact_hashes")
    if not isinstance(artifact_hashes, dict):
        return None
    value = artifact_hashes.get("evidence_pack")
    return str(value) if value else None
