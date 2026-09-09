"""Instance-checked native Repair input projection; never an output Patch format."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from typing import Any

from src.libs.llm.agent_turn import AgentMessage, AgentTurnRequest


class RepairInputProjectionError(RuntimeError):
    """A projected read-only reference no longer matches its admitted input."""

    code = "PATCH_REPAIR_INPUT_REFERENCE_INVALID"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _object(content: Any) -> dict[str, Any] | None:
    if isinstance(content, dict):
        return deepcopy(content)
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _require(value: bool) -> None:
    if not value:
        raise RepairInputProjectionError("Read-only Repair references changed or cannot be expanded exactly.")


_GUIDE = (
    " Ck: working_code_view; B0: inspect_plan_binding_source(binding_id). "
    "Input-only after_text_ref=[UTF8 byte offset,length,prefix?] reads its binding's Ck. "
    "Refs grant no edits; output literal after_text."
)


@dataclass(frozen=True)
class RepairInputProjection:
    """Keep logical history intact; project only the request sent to the provider."""

    original: tuple[AgentMessage, ...]
    projected: tuple[AgentMessage, ...]
    original_history: dict[str, Any]
    metadata: dict[str, Any]
    repair_message_bytes: int

    def validate(self, messages: Sequence[AgentMessage]) -> None:
        try:
            _require(len(messages) >= len(self.projected))
            prefix = tuple(messages[:len(self.projected)])
            native = _object(prefix[1].content)
            history = _object(prefix[-2].content)
            feedback = _object(prefix[-1].content)
            _require(isinstance(native, dict) and isinstance(history, dict) and isinstance(feedback, dict))
            view = feedback["validator_feedback"]["working_code_view"]
            _require(history["input_only"] is True and history["Ck"] == view["code_sha256"]
                     == self.metadata["code_sha256"])
            files = {row["path"]: row for row in view["files"]}
            _require(len(files) == len(view["files"]))
            restored = {"changes": []}
            for row in history["changes"]:
                row = deepcopy(row)
                binding = native["edit_binding_contexts"][row["edit_binding_id"]]
                _require(binding["source_excerpt_ref"] == "B0" and "source_excerpt" not in binding)
                file = files[binding["canonical_target_path"]]
                _require(file["complete"] is True and len(file["hunks"]) == 1)
                anchor = file["hunks"][0]["text"].encode("utf-8")
                _require(_hash(anchor) == self.metadata["anchor_text_sha256"][file["path"]])
                reference = row.pop("after_text_ref")
                _require(isinstance(reference, list) and len(reference) in (2, 3))
                offset, length = reference[:2]
                _require(type(offset) is int and type(length) is int and offset >= 0 and length > 0
                         and offset + length <= len(anchor))
                leading = reference[2] if len(reference) == 3 else ""
                _require(leading in ("", "\ufeff"))
                if leading:
                    _require(offset == 0 and file["raw_bytes_sha256"] == _hash(b"\xef\xbb\xbf" + anchor))
                row["after_text"] = leading + anchor[offset:offset + length].decode("utf-8")
                _require(_hash(row["after_text"].encode("utf-8"))
                         == self.metadata["after_text_sha256"][row["edit_binding_id"]])
                restored["changes"].append(row)
            _require(restored == self.original_history)
            # Also bind the untouched obligations, schema, F1 facts, file identities,
            # B0 spans and the complete visible text to this original local instance.
            _require(prefix == self.projected)
        except RepairInputProjectionError:
            raise
        except (KeyError, IndexError, TypeError, ValueError, UnicodeError) as exc:
            raise RepairInputProjectionError("A native Repair input reference is missing or invalid.") from exc

    def project_request(self, request: AgentTurnRequest) -> AgentTurnRequest:
        _require(tuple(request.messages[:len(self.original)]) == self.original)
        projected = replace(request, messages=(*deepcopy(self.projected), *request.messages[len(self.original):]))
        self.validate(projected.messages)
        return projected


def project_native_repair_input(
    messages: tuple[AgentMessage, ...], *, current_code_identity: Mapping[str, Any] | None,
) -> RepairInputProjection | None:
    """Use only admitted native C1 plus complete views; preserve all other paths.

    B0 becomes available through its existing allowed source tool. The result is
    not a self-contained copy of the old prompt and does not claim a source read.
    Ambiguous/non-native history keeps the old literal representation.
    """
    if len(messages) != 4 or messages[2].role != "assistant" or messages[3].role != "user":
        return None
    native, history, feedback = (_object(messages[index].content) for index in (1, 2, 3))
    if (not isinstance(native, dict) or not isinstance(history, dict) or not isinstance(feedback, dict)
            or feedback.get("message_type") != "patch_repair_context"
            or feedback.get("revision_semantics") != "complete_replacement_relative_to_B0"
            or not isinstance(current_code_identity, Mapping)):
        return None
    view = feedback.get("validator_feedback", {}).get("working_code_view")
    changes = history.get("changes")
    if (set(history) != {"changes"} or not isinstance(changes, list) or not changes
            or any(not isinstance(row, dict) or set(row) != {
                "edit_binding_id", "rationale", "rollback_hint", "after_text"}
                or not isinstance(row["after_text"], str) for row in changes)
            or not isinstance(view, dict) or not view.get("files")
            or any(row.get("complete") is not True or len(row.get("hunks", [])) != 1 for row in view["files"])):
        return None
    _require(view["code_sha256"] == current_code_identity["code_sha256"]
             and view["baseline_sha256"] == current_code_identity["baseline_sha256"]
             and sorted(row["path"] for row in view["files"]) == sorted(current_code_identity["files"]))
    _require(view["schema_version"] == "patch_materialized_working_view_v1"
             and view["source_role"] == "current_verified_materialization_not_live_baseline"
             and view["coordinate_system"] == "current_file_lines_not_edit_binding_spans")
    projected_native, projected_history, projected_feedback = deepcopy(native), deepcopy(history), deepcopy(feedback)
    files = {row["path"]: row for row in view["files"]}
    _require(len(files) == len(view["files"]))
    anchor_hashes = {}
    raw_files = {}
    for path, file in files.items():
        hunk = file["hunks"][0]
        _require(hunk["start_line"] == 1 and hunk["end_line"] == file["line_count"]
                 and len(hunk["text"].splitlines()) == file["line_count"])
        raw = hunk["text"].encode("utf-8")
        # The existing working-view producer decodes UTF-8-sig for display.
        _require(file["raw_bytes_sha256"] in (_hash(raw), _hash(b"\xef\xbb\xbf" + raw)))
        anchor_hashes[path] = _hash(raw)
        raw_files[path] = raw if _hash(raw) == file["raw_bytes_sha256"] else b"\xef\xbb\xbf" + raw
    from src.mod_agent.execution.patch_apply import _materialized_files_sha256

    _require(_materialized_files_sha256(raw_files) == current_code_identity["code_sha256"])
    after_hashes = {}
    for row in projected_history["changes"]:
        binding = native["edit_binding_contexts"].get(row["edit_binding_id"])
        _require(isinstance(binding, dict) and isinstance(binding.get("source_excerpt"), str))
        file = files.get(binding["canonical_target_path"])
        _require(file is not None)
        anchor = file["hunks"][0]["text"].encode("utf-8")
        text = row["after_text"]
        leading = "\ufeff" if text.startswith("\ufeff") and not anchor.startswith(b"\xef\xbb\xbf") else ""
        raw = text[len(leading):].encode("utf-8")
        if not raw or anchor.count(raw) != 1:
            return None
        reference = [anchor.index(raw), len(raw)]
        if leading:
            _require(reference[0] == 0 and file["raw_bytes_sha256"] == _hash(b"\xef\xbb\xbf" + anchor))
            reference.append(leading)
        after_hashes[row["edit_binding_id"]] = _hash(text.encode("utf-8"))
        del row["after_text"]
        row["after_text_ref"] = reference
    for binding in projected_native["edit_binding_contexts"].values():
        if not isinstance(binding.get("source_excerpt"), str):
            return None
        del binding["source_excerpt"]
        binding["source_excerpt_ref"] = "B0"
    projected_history.update(input_only=True, Ck=view["code_sha256"])
    for file in projected_feedback["validator_feedback"]["working_code_view"]["files"]:
        file.pop("unified_diff", None)
    action = projected_feedback["required_action"].replace(
        "B0 is unchanged source shown initially and by source tools.",
        "B0 is unchanged source available by binding tools.")
    projected_feedback["required_action"] = action + _GUIDE
    projected = (messages[0], AgentMessage(messages[1].role, _json(projected_native)),
                 AgentMessage("assistant", _json(projected_history)), AgentMessage("user", projected_feedback))
    original_wire = len(_json([asdict(item) for item in messages]).encode("utf-8"))
    projected_wire = len(_json([asdict(item) for item in projected]).encode("utf-8"))
    if projected_wire >= original_wire:
        return None
    result = RepairInputProjection(deepcopy(messages), projected, deepcopy(history), {
        "encoding": "native_repair_source_refs_v1", "code_sha256": view["code_sha256"],
        "baseline_sha256": view["baseline_sha256"], "anchor_text_sha256": anchor_hashes,
        "after_text_sha256": after_hashes, "raw_response_sha256": _hash(messages[2].content.encode("utf-8")),
        "B0_delivery": "existing_binding_tool_not_initial_literal", "input_only": True,
        "diff_display": "derived_duplicate_omitted",
        "original_messages_utf8_bytes": original_wire, "projected_messages_utf8_bytes": projected_wire,
    }, len(_json([asdict(item) for item in projected[2:]]).encode("utf-8")))
    result.validate(projected)
    return result
