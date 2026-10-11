"""Initialize a neutral GTFO source project for the existing run-request owner.

Only template bytes and project identity are materialized here. Product models,
Graph routing, code Apply, Build, and runtime remain owned by their existing paths.
"""
from __future__ import annotations

import hashlib
import json
import re
import stat
from collections.abc import Mapping
from pathlib import Path
from string import Template
from uuid import NAMESPACE_URL, uuid5

from src.mod_agent.product_executor import source_snapshot, source_snapshot_sha256

TEMPLATE_ROOT = Path(__file__).parent / "domain" / "gtfo_templates" / "neutral"
SCHEMA_VERSION = "neutral_mod_project_v1"
_REQUIRED_DEPENDENCIES = (
    "BepInEx/core/BepInEx.Core.dll",
    "BepInEx/core/BepInEx.Unity.IL2CPP.dll",
    "BepInEx/core/Il2CppInterop.Runtime.dll",
    "BepInEx/core/0Harmony.dll",
    "BepInEx/interop/UnityEngine.CoreModule.dll",
    "BepInEx/plugins/GTFO-API.dll",
)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _plain_path(value):
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("NEW_MOD_ABSOLUTE_PATH_REQUIRED")
    # Reject indirection before resolve, including existing ancestors of a new target.
    # Why: containment after resolve alone cannot detect a redirected input directory.
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("NEW_MOD_LINK_NOT_ALLOWED")
    return path.resolve()


def _bound_json(ref):
    if (not isinstance(ref, Mapping) or set(ref) != {"path", "sha256"}
            or not isinstance(ref["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]) is None):
        raise ValueError("NEW_MOD_REFERENCE_INVALID")
    path = _plain_path(ref["path"])
    if not path.is_file() or path.stat().st_size > 256 * 1024:
        raise ValueError("NEW_MOD_REFERENCE_FILE_INVALID")
    raw = path.read_bytes()
    if _sha(raw) != ref["sha256"]:
        raise ValueError("NEW_MOD_REFERENCE_CHANGED")
    value = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("NEW_MOD_REFERENCE_OBJECT_REQUIRED")
    return path, value


def _dependency(ref, target):
    # Reuse the run-request binding and snapshot format; no second dependency registry.
    from src.mod_agent.build.dependencies import (
        RunLocalGameFolderBindingV1,
        _binary_tree_snapshot,
        _binary_tree_snapshot_sha256,
    )

    path, document = _bound_json(ref)
    fields = {"binding_version", "source_root", "snapshot_sha256", "file_count", "property_name"}
    if set(document) != fields or document["binding_version"] != "run_local_game_folder_binding_v1":
        raise ValueError("NEW_MOD_DEPENDENCY_BINDING_INVALID")
    binding = RunLocalGameFolderBindingV1(**{k: v for k, v in document.items() if k != "binding_version"})
    root = _plain_path(binding.source_root)
    if root == target or root.is_relative_to(target) or target.is_relative_to(root):
        raise ValueError("NEW_MOD_DEPENDENCY_SOURCE_OVERLAP")
    snapshot = _binary_tree_snapshot(root)
    if len(snapshot) != binding.file_count or _binary_tree_snapshot_sha256(snapshot) != binding.snapshot_sha256:
        raise ValueError("NEW_MOD_DEPENDENCY_SNAPSHOT_CHANGED")
    missing = sorted(set(_REQUIRED_DEPENDENCIES) - {item["path"] for item in snapshot})
    if missing:
        raise ValueError("NEW_MOD_DEPENDENCY_FILES_MISSING: " + ", ".join(missing))
    return {"path": str(path), "sha256": ref["sha256"]}, binding.to_dict()


def prepare_new_mod_project(*, workspace_root, project_id, display_name,
                            dependency_binding_ref, plugin_version="0.1.0"):
    """Return exact template/source identity without writes or provider calls."""
    return _prepare_new_mod_project(workspace_root=workspace_root, project_id=project_id,
        display_name=display_name, dependency_binding_ref=dependency_binding_ref,
        plugin_version=plugin_version)


def _prepare_new_mod_project(*, workspace_root, project_id, display_name,
                             dependency_binding_ref, plugin_version, template_refs=None):
    workspace = _plain_path(workspace_root)
    if (not isinstance(project_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", project_id) is None
            or project_id.endswith((".", " "))
            or project_id.split(".")[0].upper() in {
                "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10))}):
        raise ValueError("NEW_MOD_PROJECT_ID_INVALID")
    if (not isinstance(display_name, str) or not display_name.strip() or len(display_name) > 120
            or any(ord(ch) < 32 for ch in display_name)):
        raise ValueError("NEW_MOD_DISPLAY_NAME_INVALID")
    if (not isinstance(plugin_version, str)
            or re.fullmatch(r"(?:0|[1-9][0-9]{0,3})\.(?:0|[1-9][0-9]{0,3})\.(?:0|[1-9][0-9]{0,3})", plugin_version) is None):
        raise ValueError("NEW_MOD_PLUGIN_VERSION_INVALID")
    token = uuid5(NAMESPACE_URL, "neutral_mod_project_v1\n" + str(workspace) + "\n" + project_id).hex
    assembly_name = "GeneratedMod_" + token
    guid = "local.modagent." + token
    identity = {"assembly_name": assembly_name, "root_namespace": assembly_name,
                "plugin_guid": guid, "plugin_name": display_name, "plugin_version": plugin_version,
                "config_file_name": guid + ".cfg"}
    container = _plain_path(workspace / "new_mod_sources" / project_id)
    target = _plain_path(container / assembly_name)
    if not target.is_relative_to(workspace):
        raise ValueError("NEW_MOD_TARGET_OUTSIDE_WORKSPACE")
    ref, dependency = _dependency(dependency_binding_ref, target)
    replacements = {**identity,
        "plugin_guid_literal": json.dumps(guid, ensure_ascii=True),
        "plugin_name_literal": json.dumps(display_name, ensure_ascii=True),
        "plugin_version_literal": json.dumps(plugin_version)}
    files, templates = [], []
    layout = (
        ("Plugin.cs.template", "Plugin.cs"), ("Mod.csproj.template", "Mod.csproj"),
        ("Dependencies.props", "Dependencies.props"), ("nuget.config", "nuget.config"),
    )
    if template_refs is not None and (not isinstance(template_refs, list) or len(template_refs) != len(layout)):
        raise ValueError("NEW_MOD_TEMPLATE_REFERENCES_INVALID")
    for index, (template_name, destination) in enumerate(layout):
        if template_refs is None:
            template_path = _plain_path(TEMPLATE_ROOT.resolve() / template_name)
        else:
            # 为什么要有它：恢复已有工程必须重读初始化绑定的历史模板，当前产品安装路径不应替换那次输入。
            reference = template_refs[index]
            if (not isinstance(reference, Mapping) or set(reference) != {"path", "sha256"}
                    or not isinstance(reference["sha256"], str)
                    or re.fullmatch(r"[0-9a-f]{64}", reference["sha256"]) is None):
                raise ValueError("NEW_MOD_TEMPLATE_REFERENCES_INVALID")
            template_path = _plain_path(reference["path"])
            if (template_path.name != template_name or not template_path.is_file()
                    or template_path.stat().st_size > 256 * 1024):
                raise ValueError("NEW_MOD_TEMPLATE_REFERENCE_FILE_INVALID")
        raw = template_path.read_bytes()
        if template_refs is not None and _sha(raw) != template_refs[index]["sha256"]:
            raise ValueError("NEW_MOD_TEMPLATE_REFERENCE_CHANGED")
        templates.append({"path": str(template_path), "sha256": _sha(raw)})
        content = raw.decode("utf-8")
        if template_name.endswith(".template"):
            content = Template(content).substitute(replacements)
        encoded = content.encode("utf-8")
        files.append({"path": destination, "sha256": _sha(encoded), "size": len(encoded), "content": content})
    prepared = {"schema_version": SCHEMA_VERSION, "status": "prepared",
        "workspace_root": str(workspace), "project_id": project_id,
        "target_project": str(target), "project_file": str(target / "Mod.csproj"),
        "receipt_path": str(container / "initialization.json"), "identity": identity,
        "template_refs": templates, "dependency_binding_ref": ref, "dependency_binding": dependency,
        "source_files": files, "config_identity_status": "reserved_not_written",
        "model_calls_performed": 0, "builds_performed": 0, "business_logic_generated": False}
    return {**prepared, "scope_hash": _digest(prepared)}


def _reprepare(value, workspace, *, historical_templates=False):
    identity = value["identity"]
    return _prepare_new_mod_project(workspace_root=workspace, project_id=value["project_id"],
        display_name=identity["plugin_name"], plugin_version=identity["plugin_version"],
        dependency_binding_ref=value["dependency_binding_ref"],
        template_refs=value["template_refs"] if historical_templates else None)


def _receipt(prepared):
    result = {key: value for key, value in prepared.items() if key != "source_files"}
    files = [{k: v for k, v in item.items() if k != "content"} for item in prepared["source_files"]]
    snapshot = sorted(files, key=lambda row: Path(row["path"]))
    result.update(status="initialized", source_files=files,
                  source_snapshot_sha256=source_snapshot_sha256(snapshot))
    return result


def initialize_new_mod_project(prepared):
    """Create only the reviewed neutral source bytes; preserve any existing project."""
    if not isinstance(prepared, Mapping):
        raise ValueError("NEW_MOD_PREPARATION_INVALID")
    current = _reprepare(prepared, prepared["workspace_root"])
    if current != dict(prepared):
        raise ValueError("NEW_MOD_PREPARATION_CHANGED")
    target = Path(current["target_project"])
    receipt_path = Path(current["receipt_path"])
    if receipt_path.exists():
        return verify_new_mod_project(receipt_path=receipt_path,
            workspace_root=current["workspace_root"], expected_scope_hash=current["scope_hash"])
    # Exclusive container creation refuses partial/unowned state instead of overwriting it.
    # Why: a retry must not silently replace another task's source or an incomplete initialization.
    target.parent.parent.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(exist_ok=False)
    target.mkdir(exist_ok=False)
    for row in current["source_files"]:
        with (target / row["path"]).open("xb") as handle:
            handle.write(row["content"].encode("utf-8"))
    receipt = _receipt(current)
    if source_snapshot_sha256(source_snapshot(target)) != receipt["source_snapshot_sha256"]:
        raise ValueError("NEW_MOD_SOURCE_CHANGED_DURING_INITIALIZATION")
    with receipt_path.open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle, ensure_ascii=False, indent=2)
    return receipt


def verify_new_mod_project(*, receipt_path, workspace_root, expected_scope_hash):
    """Revalidate template, dependencies, generated source, and exact project identity."""
    workspace = _plain_path(workspace_root)
    path = _plain_path(receipt_path)
    if not path.is_relative_to(workspace) or path.stat().st_size > 256 * 1024:
        raise ValueError("NEW_MOD_RECEIPT_OUTSIDE_WORKSPACE")
    value = json.loads(path.read_text(encoding="utf-8"))
    prepared = _reprepare(value, workspace, historical_templates=True)
    if (prepared["scope_hash"] != expected_scope_hash or value != _receipt(prepared)
            or path != Path(prepared["receipt_path"])):
        raise ValueError("NEW_MOD_RECEIPT_IDENTITY_CHANGED")
    target = _plain_path(prepared["target_project"])
    for child in target.rglob("*"):
        _plain_path(child)
    if source_snapshot(target) != sorted(value["source_files"], key=lambda row: Path(row["path"])):
        raise ValueError("NEW_MOD_SOURCE_CHANGED")
    return value


def validate_new_mod_project_receipt(receipt_ref, *, workspace_root, expected_scope_hash):
    """DSH recovery entry: verify the external receipt hash, then all bound inputs."""
    workspace = _plain_path(workspace_root)
    if not _plain_path(receipt_ref["path"]).is_relative_to(workspace):
        raise ValueError("NEW_MOD_RECEIPT_OUTSIDE_WORKSPACE")
    path, _ = _bound_json(receipt_ref)
    return verify_new_mod_project(receipt_path=path, workspace_root=workspace,
                                  expected_scope_hash=expected_scope_hash)
