"""Fail-closed exact-text patch validation and isolated application."""

from __future__ import annotations

import codecs
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any

from src.mod_agent.bindings import BindingResolver


class PatchApplyError(RuntimeError):
    """Raised when an executable patch is unsafe, stale, or ambiguous."""


class ExactDiffApprovalRejectedError(RuntimeError):
    """Raised when the user explicitly rejects the displayed exact diff."""


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
        staged: dict[Path, bytes] = {}
        original_by_target: dict[Path, bytes] = {}
        file_results: list[dict[str, Any]] = []
        diff_preview: list[dict[str, Any]] = []
        binding_span_checks: list[dict[str, Any]] = []
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

            original = original_by_target.get(target)
            if original is None:
                original = target.read_bytes()
                _validate_utf8(original, change_index=index)
                original_by_target[target] = original
            current = staged.get(target, original)
            try:
                before_bytes = before.encode("utf-8")
                after_bytes = after.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise PatchApplyError(
                    f"Change {index} patch text is not valid UTF-8 text."
                ) from exc
            match_mode = patch.get("match_mode", "unique")
            if match_mode == "bound_span_exact":
                if current != original:
                    raise PatchApplyError(
                        f"Change {index} bound-span match must be the first "
                        "change for its file."
                    )
                bound_position = _bound_span_match_position(
                    original=original,
                    before=before_bytes,
                    binding=resolver.edit_bindings.get(binding_id) or {},
                    change_index=index,
                )
                binding_span_checks.append(
                    _binding_span_check(
                        original=original,
                        before=before_bytes,
                        binding=resolver.edit_bindings.get(binding_id) or {},
                        position=bound_position,
                        change_index=index,
                        binding_id=binding_id,
                    )
                )
                count = 1
                updated = (
                    current[:bound_position]
                    + after_bytes
                    + current[bound_position + len(before_bytes) :]
                )
            elif match_mode == "unique":
                binding_span_check = _validate_bound_source_span(
                    original=original,
                    before=before_bytes,
                    binding=resolver.edit_bindings.get(binding_id) or {},
                    change_index=index,
                    binding_id=binding_id,
                )
                if binding_span_check is not None:
                    binding_span_checks.append(binding_span_check)
                count = current.count(before_bytes)
                if patch.get("expected_occurrences") != 1 or count != 1:
                    raise PatchApplyError(
                        f"Change {index} expected one live source match but "
                        f"found {count}."
                    )
                updated = current.replace(before_bytes, after_bytes, 1)
            else:
                raise PatchApplyError(
                    f"Change {index} patch match_mode is unsupported."
                )
            if patch.get("expected_occurrences") != 1:
                raise PatchApplyError(
                    f"Change {index} must expect exactly one occurrence."
                )
            if current.startswith(codecs.BOM_UTF8) != updated.startswith(codecs.BOM_UTF8):
                raise PatchApplyError(f"Change {index} must preserve the UTF-8 BOM.")
            staged[target] = updated
            before_sha256 = _sha256_bytes(current)
            after_sha256 = _sha256_bytes(updated)
            encoding = "utf-8-bom" if current.startswith(codecs.BOM_UTF8) else "utf-8"
            file_results.append(
                {
                    "change_id": change.get("change_id"),
                    "edit_binding_id": binding_id,
                    "path": relative.as_posix(),
                    "before_sha256": before_sha256,
                    "after_sha256": after_sha256,
                    "raw_before_sha256": before_sha256,
                    "raw_after_sha256": after_sha256,
                    "hash_mode": "raw_bytes",
                    "encoding": encoding,
                    "bom_preserved": current.startswith(codecs.BOM_UTF8)
                    == updated.startswith(codecs.BOM_UTF8),
                    "matched_occurrences": count,
                }
            )
            preview = {
                "change_id": change.get("change_id"),
                "edit_binding_id": binding_id,
                "path": relative.as_posix(),
                "before_text": before,
                "after_text": after,
                "expected_occurrences": 1,
                "before_sha256": before_sha256,
                "after_sha256": after_sha256,
                "raw_before_sha256": before_sha256,
                "raw_after_sha256": after_sha256,
                "hash_mode": "raw_bytes",
                "encoding": encoding,
                "bom_preserved": current.startswith(codecs.BOM_UTF8)
                == updated.startswith(codecs.BOM_UTF8),
            }
            if "match_mode" in patch:
                preview["match_mode"] = match_mode
            diff_preview.append(preview)

        if not staged:
            raise PatchApplyError("Proposal contains no executable changes.")
        structural_checks = _run_low_cost_static_checks(staged)
        unified_diff = _build_unified_diff(
            root=root,
            original_by_target=original_by_target,
            staged=staged,
        )
        unified_diff_bytes = unified_diff.encode("utf-8")
        diff_stats = _unified_diff_stats(unified_diff)
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
                try:
                    temporary.write_bytes(content)
                    if temporary.read_bytes() != content:
                        raise PatchApplyError(
                            "Temporary patch output does not match dry-run bytes."
                        )
                    os.replace(temporary, target)
                    if target.read_bytes() != content:
                        raise PatchApplyError(
                            "Applied patch bytes do not match dry-run bytes."
                        )
                finally:
                    if temporary.exists():
                        temporary.unlink()

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
            "unified_diff": unified_diff,
            "unified_diff_sha256": hashlib.sha256(unified_diff_bytes).hexdigest(),
            "unified_diff_bytes": len(unified_diff_bytes),
            "diff_stats": {
                "files": len(staged),
                "change_units": len(diff_preview),
                **diff_stats,
            },
            "static_checks": [
                *binding_span_checks,
                *structural_checks,
            ],
            "changed_files": sorted({item["path"] for item in file_results}),
            "changes": file_results,
        }


def _safe_relative_path(raw: str) -> Path:
    normalized = PurePosixPath(raw.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise PatchApplyError("Edit binding path must be workspace-relative.")
    return Path(*normalized.parts)


def _validate_utf8(value: bytes, *, change_index: int) -> None:
    try:
        value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PatchApplyError(
            f"Change {change_index} target is not valid UTF-8; exact bytes were not changed."
        ) from exc


def _validate_bound_source_span(
    *,
    original: bytes,
    before: bytes,
    binding: dict[str, Any],
    change_index: int,
    binding_id: str,
) -> dict[str, Any] | None:
    span = binding.get("target_span")
    if not isinstance(span, dict):
        return None
    start_line = span.get("start_line")
    end_line = span.get("end_line")
    if (
        not isinstance(start_line, int)
        or isinstance(start_line, bool)
        or not isinstance(end_line, int)
        or isinstance(end_line, bool)
        or start_line <= 0
        or end_line < start_line
    ):
        raise PatchApplyError(
            f"Change {change_index} edit binding has an invalid target_span."
        )
    positions: list[int] = []
    offset = 0
    while True:
        position = original.find(before, offset)
        if position < 0:
            break
        positions.append(position)
        offset = position + max(len(before), 1)
    if len(positions) != 1:
        raise PatchApplyError(
            f"Change {change_index} before_text is not unique in the bound source."
        )
    observed_start = original[: positions[0]].count(b"\n") + 1
    content = before.rstrip(b"\r\n")
    observed_end = observed_start + content.count(b"\n")
    if observed_start < start_line or observed_end > end_line:
        raise PatchApplyError(
            f"Change {change_index} before_text is outside edit binding target_span."
        )
    return {
        "check_id": "binding_target_span",
        "status": "passed",
        "change_index": change_index,
        "binding_id": binding_id,
        "bound_start_line": start_line,
        "bound_end_line": end_line,
        "observed_start_line": observed_start,
        "observed_end_line": observed_end,
    }


def _bound_span_match_position(
    *,
    original: bytes,
    before: bytes,
    binding: dict[str, Any],
    change_index: int,
) -> int:
    span = binding.get("target_span")
    if not isinstance(span, dict):
        raise PatchApplyError(
            f"Change {change_index} bound-span match requires target_span."
        )
    start_line = span.get("start_line")
    end_line = span.get("end_line")
    if (
        not isinstance(start_line, int)
        or isinstance(start_line, bool)
        or not isinstance(end_line, int)
        or isinstance(end_line, bool)
        or start_line <= 0
        or end_line < start_line
    ):
        raise PatchApplyError(
            f"Change {change_index} edit binding has an invalid target_span."
        )
    lines = original.splitlines(keepends=True)
    if end_line > len(lines):
        raise PatchApplyError(
            f"Change {change_index} target_span exceeds the live source."
        )
    span_start = sum(len(line) for line in lines[: start_line - 1])
    span_end = sum(len(line) for line in lines[:end_line])
    bound_bytes = original[span_start:span_end]
    if bound_bytes.count(before) != 1:
        raise PatchApplyError(
            f"Change {change_index} before_text does not match exactly once "
            "inside target_span."
        )
    return span_start + bound_bytes.index(before)


def _binding_span_check(
    *,
    original: bytes,
    before: bytes,
    binding: dict[str, Any],
    position: int,
    change_index: int,
    binding_id: str,
) -> dict[str, Any]:
    span = binding["target_span"]
    observed_start = original[:position].count(b"\n") + 1
    observed_end = observed_start + before.rstrip(b"\r\n").count(b"\n")
    if (
        observed_start < span["start_line"]
        or observed_end > span["end_line"]
    ):
        raise PatchApplyError(
            f"Change {change_index} before_text is outside edit binding "
            "target_span."
        )
    return {
        "check_id": "binding_target_span",
        "status": "passed",
        "change_index": change_index,
        "binding_id": binding_id,
        "bound_start_line": span["start_line"],
        "bound_end_line": span["end_line"],
        "observed_start_line": observed_start,
        "observed_end_line": observed_end,
        "match_mode": "bound_span_exact",
    }


def _run_low_cost_static_checks(staged: dict[Path, bytes]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for target, content in staged.items():
        if target.suffix.lower() != ".cs":
            continue
        text = content.decode("utf-8-sig")
        error = _csharp_delimiter_error(text)
        if error is not None:
            raise PatchApplyError(
                f"C# low-cost structural check failed for {target.name}: {error}"
            )
        checks.append(
            {
                "check_id": "csharp_delimiter_balance",
                "status": "passed",
                "path": target.name,
                "limitations": (
                    "This lexical check does not resolve symbols, types, overloads, "
                    "or all control-flow errors."
                ),
            }
        )
    return checks


def _csharp_delimiter_error(text: str) -> str | None:
    stack: list[tuple[str, int]] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    state = "code"
    index = 0
    while index < len(text):
        current = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if state == "line_comment":
            if current == "\n":
                state = "code"
            index += 1
            continue
        if state == "block_comment":
            if current == "*" and following == "/":
                state = "code"
                index += 2
            else:
                index += 1
            continue
        if state == "string":
            if current == "\\":
                index += 2
            elif current == '"':
                state = "code"
                index += 1
            else:
                index += 1
            continue
        if state == "verbatim_string":
            if current == '"' and following == '"':
                index += 2
            elif current == '"':
                state = "code"
                index += 1
            else:
                index += 1
            continue
        if state == "char":
            if current == "\\":
                index += 2
            elif current == "'":
                state = "code"
                index += 1
            else:
                index += 1
            continue
        if current == "/" and following == "/":
            state = "line_comment"
            index += 2
            continue
        if current == "/" and following == "*":
            state = "block_comment"
            index += 2
            continue
        if text.startswith('$@"', index) or text.startswith('@$"', index):
            state = "verbatim_string"
            index += 3
            continue
        if current == "@" and following == '"':
            state = "verbatim_string"
            index += 2
            continue
        if current == "$" and following == '"':
            state = "string"
            index += 2
            continue
        if current == '"':
            state = "string"
            index += 1
            continue
        if current == "'":
            state = "char"
            index += 1
            continue
        if current in "([{":
            stack.append((current, index))
        elif current in ")]}":
            if not stack or stack[-1][0] != pairs[current]:
                return f"unmatched {current!r} at character {index}"
            stack.pop()
        index += 1
    if state in {"block_comment", "string", "verbatim_string", "char"}:
        return f"unterminated {state.replace('_', ' ')}"
    if stack:
        delimiter, position = stack[-1]
        return f"unclosed {delimiter!r} at character {position}"
    return None


def _build_unified_diff(
    *,
    root: Path,
    original_by_target: dict[Path, bytes],
    staged: dict[Path, bytes],
) -> str:
    chunks: list[str] = []
    for target in sorted(staged, key=lambda item: item.as_posix()):
        relative = target.relative_to(root).as_posix()
        before_lines = original_by_target[target].decode("utf-8-sig").splitlines()
        after_lines = staged[target].decode("utf-8-sig").splitlines()
        chunks.extend(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=f"a/{relative}",
                tofile=f"b/{relative}",
                lineterm="",
            )
        )
    return "\n".join(chunks) + ("\n" if chunks else "")


def _unified_diff_stats(unified_diff: str) -> dict[str, int]:
    lines = unified_diff.splitlines()
    return {
        "insertions": sum(
            1 for line in lines if line.startswith("+") and not line.startswith("+++")
        ),
        "deletions": sum(
            1 for line in lines if line.startswith("-") and not line.startswith("---")
        ),
    }


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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
