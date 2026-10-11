"""Explicit normal-entry binding for the existing read-only dependency tools."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DependencyAPIConfiguration:
    path: Path
    sha256: str
    inspector_path: Path
    inspector_sha256: str
    max_method_inspections: int

    @classmethod
    def load(cls, path: str | Path) -> "DependencyAPIConfiguration":
        selected = Path(path)
        if not selected.is_absolute() or str(selected).startswith(("\\\\", "//")):
            raise ValueError("DEPENDENCY_API_CONFIG_LOCAL_ABSOLUTE_PATH_REQUIRED")
        selected = selected.resolve(strict=True)
        raw = selected.read_bytes()
        value = json.loads(raw)
        if (not isinstance(value, dict)
                or set(value) != {"schema_version", "inspector_ref", "max_method_inspections"}
                or value["schema_version"] != "run_dependency_api_config_v1"):
            raise ValueError("DEPENDENCY_API_CONFIG_INVALID")
        ref = value["inspector_ref"]
        if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
                or not isinstance(ref["path"], str) or not Path(ref["path"]).is_absolute()
                or ref["path"].startswith(("\\\\", "//"))
                or not isinstance(ref["sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]) is None):
            raise ValueError("DEPENDENCY_API_INSPECTOR_REF_INVALID")
        maximum = value["max_method_inspections"]
        if type(maximum) is not int or not 1 <= maximum <= 3:
            raise ValueError("DEPENDENCY_API_INSPECTION_LIMIT_INVALID")
        configuration = cls(selected, hashlib.sha256(raw).hexdigest(),
                            Path(ref["path"]).resolve(strict=True), ref["sha256"], maximum)
        configuration.verify()
        return configuration

    @property
    def reference(self) -> dict[str, str]:
        return {"path": str(self.path), "sha256": self.sha256}

    def verify(self) -> None:
        if hashlib.sha256(self.path.read_bytes()).hexdigest() != self.sha256:
            raise ValueError("DEPENDENCY_API_CONFIG_CHANGED")
        if hashlib.sha256(self.inspector_path.read_bytes()).hexdigest() != self.inspector_sha256:
            raise ValueError("DEPENDENCY_API_INSPECTOR_CHANGED")

    def bind(self, *, run_root, run_id, game_folder_dependency):
        from src.mod_agent.local_entry import (
            _binary_tree_snapshot,
            _binary_tree_snapshot_sha256,
            make_run_dependency_api_reassessment_augmentation,
        )

        self.verify()
        factory, binding = make_run_dependency_api_reassessment_augmentation(
            run_root=run_root, run_id=run_id, game_folder_dependency=game_folder_dependency,
            inspector_path=self.inspector_path, inspector_sha256=self.inspector_sha256,
            max_method_inspections=self.max_method_inspections)
        dependency_root = Path(game_folder_dependency["isolated_copy"]).resolve(strict=True)
        expected_sha256 = binding["source_snapshot_sha256"]
        expected_count = binding["source_file_count"]

        def verify_dependency():
            if dependency_root.resolve(strict=True) != dependency_root:
                raise ValueError("DEPENDENCY_API_RUN_COPY_CHANGED")
            snapshot = _binary_tree_snapshot(dependency_root)
            if (len(snapshot) != expected_count
                    or _binary_tree_snapshot_sha256(snapshot) != expected_sha256):
                raise ValueError("DEPENDENCY_API_RUN_COPY_CHANGED")

        def augment(projection, retrieved):
            # Recheck inputs and dependencies around each batch. 为什么要有它：补查前或期间的依赖漂移不能作为原构建材料返回。
            self.verify()
            verify_dependency()
            evidence = factory(projection, retrieved)
            self.verify()
            verify_dependency()
            return evidence

        augment.query_capabilities = factory.query_capabilities
        return augment, {"status": "configured", "configuration_ref": self.reference, **binding}
