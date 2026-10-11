"""Caller-bound, immutable routing turns and clarification replay records."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4


def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def reference(path):
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def read_reference(ref, workspace):
    path = Path(ref["path"]).resolve()
    if not path.is_relative_to(workspace.resolve()) or reference(path) != ref:
        raise ValueError("CLARIFICATION_RECORD_CHANGED")
    return json.loads(path.read_text(encoding="utf-8"))


def transcript(turns):
    if len(turns) == 1:
        return turns[0]["content"]
    # 为什么要有它：保留原文及发言来源，问题只提供上下文，用户纠正才可变更原约束。
    return ("以下为需求澄清转录。原需求中未被用户修改的约束保留；后续用户纠正优先。"
            "助手澄清问题仅为上下文，不自行增加需求或授权。\n" +
            json.dumps(turns, ensure_ascii=False, indent=2))


class ClarificationState:
    def __init__(self, *, workspace, conversation_id, turn_id, clarification_for, request):
        if not isinstance(conversation_id, str) or not conversation_id.strip() or len(conversation_id) > 256:
            raise ValueError("CLARIFICATION_CONVERSATION_ID_INVALID")
        if turn_id is not None and (not isinstance(turn_id, str) or not turn_id.strip() or len(turn_id) > 256):
            raise ValueError("CLARIFICATION_TURN_ID_INVALID")
        self.workspace = workspace
        self.conversation_id = conversation_id
        self.conversation_sha256 = digest(conversation_id)
        parent = workspace / ".dsh-routing" / "conversations"
        self.short_root = parent / self.conversation_sha256[:32]
        self.legacy_root = parent / self.conversation_sha256
        if self.short_root.exists() and self.legacy_root.exists():
            raise ValueError("CLARIFICATION_CONVERSATION_LAYOUT_CONFLICT")
        self.root = self.legacy_root if self.legacy_root.exists() else self.short_root
        self.identity = self.root / "session.identity"
        expected_identity = {"layout_version": "clarification_path_v2", "conversation_id": conversation_id,
                             "conversation_sha256": self.conversation_sha256}
        if self.root == self.short_root:
            try:
                self.root.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                pass
            else:
                # 为什么要有它：短路径避免真实Windows MAX_PATH失败，完整身份仍留原件以拒绝截断碰撞。
                save(self.identity, expected_identity)
        self._check_conversation_layout()
        self.turn_id = turn_id or uuid4().hex
        self.turn_sha256 = digest(self.turn_id)
        short_turn = self.root / (self.turn_sha256[:32] + ".json")
        legacy_turn = self.root / (self.turn_sha256 + ".json")
        if short_turn.exists() and legacy_turn.exists():
            raise ValueError("CLARIFICATION_TURN_LAYOUT_CONFLICT")
        self.turn = legacy_turn if legacy_turn.exists() else short_turn
        self.key = digest({**request, "clarification_for": clarification_for})
        self.lock = self.root / "active.lock"
        self.locked = False
        self.parent = None
        self.resolved_reply = None
        self.history = []

    def _check_conversation_layout(self):
        if self.short_root.exists() and self.legacy_root.exists():
            raise ValueError("CLARIFICATION_CONVERSATION_LAYOUT_CONFLICT")
        if not self.root.is_dir():
            raise ValueError("CLARIFICATION_CONVERSATION_LAYOUT_INVALID")
        if self.root == self.short_root:
            expected = {"layout_version": "clarification_path_v2", "conversation_id": self.conversation_id,
                        "conversation_sha256": self.conversation_sha256}
            if not self.identity.is_file() or json.loads(self.identity.read_text(encoding="utf-8")) != expected:
                raise ValueError("CLARIFICATION_CONVERSATION_IDENTITY_CONFLICT")

    def _read_claim(self, path):
        claim = json.loads(path.read_text(encoding="utf-8"))
        turn_id = claim.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id.strip() or len(turn_id) > 256:
            raise ValueError("CLARIFICATION_TURN_IDENTITY_CONFLICT")
        full_hash = digest(turn_id)
        short = self.root / (full_hash[:32] + ".json")
        legacy = self.root / (full_hash + ".json")
        if short.exists() and legacy.exists():
            raise ValueError("CLARIFICATION_TURN_LAYOUT_CONFLICT")
        if path not in {short, legacy}:
            raise ValueError("CLARIFICATION_TURN_IDENTITY_CONFLICT")
        if path == short or any(key in claim for key in ("conversation_id", "conversation_sha256", "turn_sha256")):
            if (claim.get("conversation_id") != self.conversation_id
                    or claim.get("conversation_sha256") != self.conversation_sha256
                    or claim.get("turn_sha256") != full_hash):
                raise ValueError("CLARIFICATION_TURN_IDENTITY_CONFLICT")
        return claim

    def begin(self, clarification_for, preview_only=False):
        self._check_conversation_layout()
        if self.turn.exists():
            claim = self._read_claim(self.turn)
            if claim["turn_id"] != self.turn_id or digest(claim["turn_id"]) != self.turn_sha256:
                raise ValueError("CLARIFICATION_TURN_IDENTITY_CONFLICT")
            if claim["request_hash"] != self.key:
                raise ValueError("CLARIFICATION_TURN_REUSED_WITH_DIFFERENT_INPUT")
            return self.replay(claim)
        try:
            save(self.lock, {"turn_id": self.turn_id})
        except FileExistsError:
            raise ValueError("CLARIFICATION_SESSION_IN_PROGRESS_OR_INTERRUPTED") from None
        self.locked = True
        try:
            self.history = sorted((self._read_claim(p) for p in self.root.glob("*.json")),
                                  key=lambda row: row["created_ns"])
            pending = None
            for row in self.history:
                record = self.replay(row)
                if not record.get("preview_only"):
                    if record.get("status") == "needs_clarification":
                        pending = record
                    elif record.get("product_owner_invoked") or record.get("status") != "routing_failed":
                        pending = None
            if clarification_for is not None:
                candidates = [row for row in self.history if row["route_id"] == clarification_for]
                if not candidates:
                    raise ValueError("CLARIFICATION_NOT_IN_CONVERSATION")
                previous = self.replay(candidates[0])
                if previous.get("status") != "needs_clarification" or (previous.get("preview_only") and not preview_only):
                    raise ValueError("CLARIFICATION_NOT_PENDING")
                replies = [row for row in self.history if row.get("clarification_for") == clarification_for
                           and not row.get("preview_only")
                           and (self.replay(row).get("status") != "routing_failed"
                                or self.replay(row).get("product_owner_invoked"))]
                if replies:
                    # 为什么要有它：新一轮对旧澄清的纠正不能被旧成功结果吞掉，正文和当前绑定须再核对。
                    self.resolved_reply = replies[0]
                pending = previous
            self.parent = pending if clarification_for is not None or not preview_only else None
            return None
        except BaseException:
            self.close()
            raise

    def replay(self, claim):
        path = Path(claim["result_path"]).resolve()
        expected = self.workspace.resolve() / ".dsh-routing" / claim["route_id"] / "result.json"
        if path != expected or path.parent.parent != self.workspace.resolve() / ".dsh-routing":
            raise ValueError("CLARIFICATION_RECORD_IDENTITY_CHANGED")
        receipt = path.parent / "conversation_receipt.json"
        if not receipt.is_file():
            raise ValueError("CLARIFICATION_TURN_IN_PROGRESS_OR_INTERRUPTED")
        bound = json.loads(receipt.read_text(encoding="utf-8"))
        request = read_reference(bound["request_ref"], self.workspace)
        result = read_reference(bound["result_ref"], self.workspace)
        if (Path(bound["request_ref"]["path"]).resolve() != path.parent / "request.json"
                or Path(bound["result_ref"]["path"]).resolve() != path
                or request.get("conversation_id") != self.conversation_id
                or result.get("conversation_id") != self.conversation_id
                or request.get("turn_id") != claim["turn_id"] or result.get("turn_id") != claim["turn_id"]
                or result.get("route_id") != claim["route_id"]):
            raise ValueError("CLARIFICATION_RECORD_IDENTITY_CHANGED")
        return result

    def claim(self, route_root, preview_only):
        self._check_conversation_layout()
        counterpart = self.root / ((self.turn_sha256 if len(self.turn.stem) == 32 else self.turn_sha256[:32]) + ".json")
        if counterpart.exists():
            raise ValueError("CLARIFICATION_TURN_LAYOUT_CONFLICT")
        save(self.turn, {"turn_id": self.turn_id, "turn_sha256": self.turn_sha256,
            "conversation_id": self.conversation_id, "conversation_sha256": self.conversation_sha256,
            "request_hash": self.key, "created_ns": time.time_ns(),
            "route_id": route_root.name, "result_path": str(route_root / "result.json"),
            "clarification_for": self.parent["route_id"] if self.parent else None,
            "preview_only": preview_only})

    def totals(self, current):
        rows = [self.replay(row) for row in self.history] + [current]
        calls = sum(row.get("routing_model_calls_reserved", 0) for row in rows)
        usage = {}
        for key in ("input_tokens", "output_tokens"):
            values = [(row.get("routing_usage") or {}).get(key) for row in rows
                      if row.get("routing_model_calls_reserved")]
            usage[key] = sum(values) if all(type(v) is int for v in values) else None
        transports = [row.get("routing_transport_calls") for row in rows]
        return {"cumulative_routing_calls": calls, "cumulative_routing_usage": usage,
                "cumulative_routing_calls_scope": "reserved routing calls across this conversation, including previews",
                "cumulative_routing_transport_calls": sum(transports) if all(type(v) is int for v in transports) else None,
                "cumulative_routing_transport_calls_known_subtotal": sum(v for v in transports if type(v) is int),
                "cumulative_routing_elapsed_seconds": sum(row.get("routing_elapsed_seconds", 0) for row in rows)}

    def finish(self, route_root):
        save(route_root / "conversation_receipt.json", {"request_ref": reference(route_root / "request.json"),
            "result_ref": reference(route_root / "result.json")})

    def close(self):
        if self.locked:
            self.lock.unlink()
            self.locked = False
