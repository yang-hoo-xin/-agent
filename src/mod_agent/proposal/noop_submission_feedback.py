"""Factual feedback for a fully validated, entirely unchanged native submission."""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def whole_noop_facts(changes) -> dict:
    """Called only after all hard binding checks have passed.

    为什么要有它：改动说明不是代码变化；确定性相等事实能避免再次传入整份未改源码，也不会将无改动算作成功。
    """
    if not changes or any(row["patch"]["before_text"] != row["patch"]["after_text"] for row in changes):
        return {}
    identities = sorted(({"binding_id": row["edit_binding_id"],
        "effective_after_text_sha256": _sha(row["patch"]["after_text"])} for row in changes), key=lambda row: row["binding_id"])
    return {"whole_submission_unchanged": True, "unchanged_bindings": identities,
        "effective_code_sha256": _sha(_json(identities))}


def noop_code_identity(diagnostics) -> str | None:
    if (not isinstance(diagnostics, dict) or diagnostics.get("whole_submission_unchanged") is not True
            or diagnostics.get("failure_classification") != "native_after_text_not_replacement"):
        return None
    rows = diagnostics.get("unchanged_bindings")
    if (not isinstance(rows, list) or not rows or any(not isinstance(row, dict)
            or set(row) != {"binding_id", "effective_after_text_sha256"}
            or not isinstance(row["binding_id"], str) or not row["binding_id"]
            or re.fullmatch("[0-9a-f]{64}", str(row["effective_after_text_sha256"])) is None for row in rows)
            or len({row["binding_id"] for row in rows}) != len(rows)):
        return None
    identity = _sha(_json(sorted(rows, key=lambda row: row["binding_id"])))
    return identity if identity == diagnostics.get("effective_code_sha256") else None


def project_whole_noop_response(raw_content: str, diagnostics) -> str | None:
    identity = noop_code_identity(diagnostics)
    if identity is None:
        return None
    try:
        payload = json.loads(raw_content)
        changes = payload["changes"]
        expected = {row["binding_id"]: row["effective_after_text_sha256"] for row in diagnostics["unchanged_bindings"]}
        if (set(payload) != {"changes"} or not isinstance(changes, list) or len(changes) != len(expected)
                or {row["edit_binding_id"] for row in changes} != set(expected)):
            return None
        projected = []
        for change in changes:
            after = change["after_text"]
            digest = expected[change["edit_binding_id"]]
            if not isinstance(after, str) or (digest != _sha(after)
                    and (after.startswith("\ufeff") or digest != _sha("\ufeff" + after))):
                return None
            row = deepcopy(change)
            row.pop("after_text")
            projected.append({**row, "after_text_unchanged": True})
        return _json({"input_only": "unchanged_submission_view", "effective_code_sha256": identity,
            "changes": projected, "code_status": "Each after_text equals its bound baseline after existing BOM preservation. "
                "No code was changed, accepted or applied. Original response is retained locally."})
    except (ValueError, TypeError, KeyError):
        return None
