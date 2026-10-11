"""Optional, locally bound XML member documentation for native Patch context."""
from __future__ import annotations

import hashlib
import json
import re
import stat
import xml.etree.ElementTree as ET
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def documentation_policy() -> dict[str, Any]:
    return {"policy_version": "bound_xml_members_v1", "max_members": 8, "max_context_chars": 6000}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class DependencyDocumentationError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _safe_path(root: Path, value: str | Path) -> Path:
    raw = Path(value)
    raw = raw if raw.is_absolute() else root / raw
    try:
        relative = raw.relative_to(root)
        if ".." in relative.parts or not relative.parts:
            raise ValueError("invalid relative path")
        resolved = raw.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise ValueError("outside root")
        selected = root
        for part in relative.parts:
            selected = selected / part
            metadata = selected.lstat()
            if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
                raise ValueError("linked entry")
        return resolved
    except (ValueError, OSError) as error:
        raise DependencyDocumentationError("PATCH_DEPENDENCY_DOCUMENTATION_PATH_INVALID") from error


def _manifest_context(root: Path) -> tuple[dict, dict] | None:
    path = root / "run_manifest.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if not isinstance(value, dict):
        return None
    policy = value.get("dependency_documentation_policy")
    build_dependency = value.get("build_dependency")
    dependency = build_dependency.get("game_folder") if isinstance(build_dependency, dict) else None
    if not isinstance(policy, dict) or not isinstance(dependency, dict):
        return None
    if (policy.get("policy_version") != "bound_xml_members_v1"
            or type(policy.get("max_members")) is not int or not 1 <= policy["max_members"] <= 8
            or type(policy.get("max_context_chars")) is not int or not 1 <= policy["max_context_chars"] <= 6000
            or dependency.get("build_uses_isolated_copy") is not True
            or not isinstance(dependency.get("isolated_copy"), str)
            or re.fullmatch("[a-f0-9]{64}", str(dependency.get("copy_snapshot_sha256"))) is None):
        return None
    return policy, {key: dependency[key] for key in (
        "isolated_copy", "copy_snapshot_sha256", "build_uses_isolated_copy")}


def _member_match(locator: str, code: str, tokens: Counter) -> int:
    # XML member IDs use fully qualified declaring types and optional generic arity.
    signature = locator.split("(", 1)[0]
    if not re.match(r"^[MPEF]:", signature) or "." not in signature:
        return 0
    declaring, member = signature[2:].rsplit(".", 1)
    type_name = re.sub(r"`\d+$", "", declaring.rsplit(".", 1)[-1])
    member = re.sub(r"`+\d+$", "", member)
    if not tokens[type_name]:
        return 0
    if member in {"#ctor", "#cctor"}:
        return len(re.findall(r"\bnew\s+(?:[\w]+\.)*" + re.escape(type_name) + r"\b", code))
    return tokens[member] if re.fullmatch(r"[A-Za-z_]\w*", member) else 0


def _with_digest(value: dict) -> dict:
    return {**value, "bundle_sha256": _sha(_json(value).encode("utf-8"))}


@dataclass(frozen=True)
class BoundDependencyDocumentation:
    root: Path
    manifest_context: tuple[dict, dict]
    files: tuple[tuple[str, str], ...]
    bundle: dict

    def model_view(self) -> dict:
        return deepcopy(self.bundle)

    def validate(self) -> None:
        """After the full initial snapshot check, recheck only consumed references.

        为什么要有它：模型不能继续使用已漂移的文档或源码；无关依赖不应在每次调用前后重复扫描。
        """
        if _manifest_context(self.root) != self.manifest_context:
            raise DependencyDocumentationError("PATCH_DEPENDENCY_DOCUMENTATION_BINDING_CHANGED")
        for relative, expected in self.files:
            if _sha(_safe_path(self.root, relative).read_bytes()) != expected:
                raise DependencyDocumentationError("PATCH_DEPENDENCY_DOCUMENTATION_SOURCE_CHANGED")

    def bind_client(self, client):
        def complete_turn(request):
            self.validate()
            response = client.complete_turn(request)
            self.validate()
            return response
        return SimpleNamespace(provider=client.provider, model=client.model, complete_turn=complete_turn)


def prepare_dependency_documentation(*, workspace_root: str | Path, implementation_plan: dict,
                                    compiler_diagnostics=()) -> BoundDependencyDocumentation | None:
    """Select by current source identifiers; missing/unsupported XML stays optional.

    为什么要有它：已复制依赖的说明可回答 API 语义，但匹配片段不是已验证行为，也不赋予任何编辑或执行权限。
    """
    from src.mod_agent.build.dependencies import (
        _binary_tree_snapshot,
        _binary_tree_snapshot_sha256,
    )
    from src.mod_agent.proposal.code_generator import _strip_csharp_non_code

    root = Path(workspace_root).resolve(strict=True)
    context = _manifest_context(root)
    diagnostic_types = set()
    for row in compiler_diagnostics:
        if row.get("code") != "CS1061" or row.get("severity") != "error":
            continue
        match = re.match(r"^[\"'‘“]([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)[\"'’”](?:\s+does not contain a definition for|未包含)",
                         str(row.get("message", "")))
        if match:
            diagnostic_types.add(match[1].rsplit(".", 1)[-1])
    # 为什么要有它：编译器已指出接收类型时，修订需要查看该类型可用成员，不能只检索源码里已经猜对的成员名。
    bindings = (implementation_plan.get("binding_registry") or {}).get("edit_bindings")
    if context is None or not isinstance(bindings, list) or not bindings:
        return None
    policy, dependency = context
    dependency_root = _safe_path(root, dependency["isolated_copy"])
    snapshot = _binary_tree_snapshot(dependency_root)
    if _binary_tree_snapshot_sha256(snapshot) != dependency["copy_snapshot_sha256"]:
        raise DependencyDocumentationError("PATCH_DEPENDENCY_DOCUMENTATION_SNAPSHOT_CHANGED")
    sources: dict[str, str] = {}
    code_units = []
    for binding in bindings:
        path = _safe_path(root, binding["canonical_target_path"])
        raw = path.read_bytes()
        if _sha(raw) != binding["source_hash"]:
            raise DependencyDocumentationError("PATCH_DEPENDENCY_DOCUMENTATION_SOURCE_CHANGED")
        span = binding["target_span"]
        lines = raw.decode("utf-8-sig").splitlines(keepends=True)
        if (not isinstance(span, dict) or type(span.get("start_line")) is not int
                or type(span.get("end_line")) is not int
                or not 1 <= span["start_line"] <= span["end_line"] <= len(lines)):
            raise DependencyDocumentationError("PATCH_DEPENDENCY_DOCUMENTATION_SOURCE_RANGE_INVALID")
        code = _strip_csharp_non_code("".join(lines[span["start_line"] - 1:span["end_line"]]))
        code_units.append((code, Counter(re.findall(r"\b[A-Za-z_]\w*\b", code))))
        sources[path.relative_to(root).as_posix()] = binding["source_hash"]
    candidates = []
    for entry in snapshot:
        if not entry["path"].lower().endswith(".xml") or entry["size"] > 4 * 1024 * 1024:
            continue
        path = _safe_path(root, dependency_root / entry["path"])
        raw = path.read_bytes()
        if _sha(raw) != entry["sha256"]:
            raise DependencyDocumentationError("PATCH_DEPENDENCY_DOCUMENTATION_SNAPSHOT_CHANGED")
        # Unsupported document forms are omitted, including DTD/entity declarations.
        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            continue
        try:
            document = ET.fromstring(raw)
        except ET.ParseError:
            continue
        for member in document.findall("./members/member"):
            locator = member.get("name", "")
            score = sum(_member_match(locator, code, tokens) for code, tokens in code_units)
            signature = locator.split("(", 1)[0]
            if re.match(r"^[MPEF]:", signature) and "." in signature:
                declaring = signature[2:].rsplit(".", 1)[0].rsplit(".", 1)[-1]
                if re.sub(r"`\d+$", "", declaring) in diagnostic_types:
                    score += 100
            if not score:
                continue
            xml_member = ET.tostring(member, encoding="unicode").strip()
            row = {"source_path": path.relative_to(root).as_posix(), "xml_sha256": _sha(raw),
                "member_locator": locator, "xml_member": xml_member}
            candidates.append((-score, row["source_path"], locator, row))
    if not candidates:
        return None
    selected = []
    base = {"source_kind": "dependency_xml_documentation", "authority": "read_only_reference",
        "selection_basis": ("compiler_CS1061_receiver_type_and_current_plan_source_identifiers"
                            if diagnostic_types else "current_plan_source_type_and_member_identifiers"),
        **({"compiler_receiver_types": sorted(diagnostic_types)} if diagnostic_types else {}),
        "behavior_execution_proven": False, "dependency_snapshot_sha256": dependency["copy_snapshot_sha256"],
        "validation_scope": "initial_dependency_tree_then_consumed_xml_and_source_files",
        "source_refs": [{"source_path": path, "sha256": digest} for path, digest in sorted(sources.items())],
        "policy": deepcopy(policy)}
    for _, _, _, row in sorted(candidates, key=lambda item: item[:3]):
        proposed = _with_digest({**base, "entries": [*selected, row]})
        if len(_json(proposed)) <= policy["max_context_chars"]:
            selected.append(row)
        if len(selected) >= policy["max_members"]:
            break
    if not selected:
        return None
    files = {**sources, **{row["source_path"]: row["xml_sha256"] for row in selected}}
    bound = BoundDependencyDocumentation(root, deepcopy(context), tuple(sorted(files.items())),
        _with_digest({**base, "entries": selected}))
    bound.validate()
    return bound
