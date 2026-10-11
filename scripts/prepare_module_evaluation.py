"""Freeze a module-evaluation source tree with the existing snapshot owner."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.mod_agent.platform_execution_snapshot import prepare_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    snapshot = Path(tempfile.mkdtemp(prefix="medd-src-")) / "s"
    reference = prepare_snapshot(source_root=ROOT, snapshot_root=snapshot, business_argv=[],
                                 resource_dirs=("config", "tests", "integrations"))
    document = json.loads(Path(reference["path"]).read_text(encoding="utf-8"))
    for name in ("pyproject.toml", "uv.lock", "README.md", "main.py", ".github/workflows/ci.yml"):
        path = ROOT / name
        if path.is_file():
            raw = path.read_bytes()
            target = snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            document["files"][name] = {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
    document["base_snapshot_ref"] = reference
    document["scope"] = "engineering sources/tests/resources; installed dependencies remain external"
    receipt = output / "receipt.json"
    receipt.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    # 为什么要有它：临时执行目录之外保留可恢复源码，首败与修后快照不能互相覆盖。
    archive = shutil.make_archive(str(output / "sources"), "zip", snapshot)
    (output / "archive.json").write_text(json.dumps({"path": archive,
        "sha256": hashlib.sha256(Path(archive).read_bytes()).hexdigest()}, indent=2), encoding="utf-8")
    print(json.dumps({"snapshot": str(snapshot), "receipt": str(receipt),
                      "files": len(document["files"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
