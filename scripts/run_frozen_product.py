"""Freeze selected platform sources, then invoke the original CLI in a fresh process."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def _child(reference):
    # Verify the bootstrap and helper bytes before importing any project package.
    # 为什么要有它：子进程必须从保存的原文开始，不能继承父进程已加载的主树模块。
    path = Path(reference["path"])
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise ValueError("FROZEN_EXECUTION_MANIFEST_CHANGED")
    document = json.loads(raw)
    root = Path(document["snapshot_root"]).resolve()
    if root != Path(__file__).resolve().parents[1] or path.resolve().parent != root:
        raise ValueError("FROZEN_EXECUTION_BOOTSTRAP_OUTSIDE_SNAPSHOT")
    for name, expected in document["files"].items():
        target = root / name
        if not target.resolve().is_relative_to(root) or target.is_symlink():
            raise ValueError("FROZEN_EXECUTION_SNAPSHOT_PATH_ESCAPE")
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected["sha256"]:
            raise ValueError("FROZEN_EXECUTION_SOURCE_CHANGED: " + name)
    sys.path.insert(0, str(root))
    from src.mod_agent.platform_execution_snapshot import child_main

    return child_main(reference)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--_child"]:
        return _child({"path": args[1], "sha256": args[2]})
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--extra-load-ref", nargs=2, action="append", default=[], metavar=("PATH", "SHA256"))
    parser.add_argument("--bound-input", nargs=2, action="append", default=[], metavar=("PATH", "SHA256"))
    parser.add_argument("--resource-dir", action="append", default=[])
    parser.add_argument("business_args", nargs=argparse.REMAINDER)
    selected = parser.parse_args(args)
    business = selected.business_args
    if business[:1] == ["--"]:
        business = business[1:]
    if not business:
        parser.error("Pass the original Product CLI arguments after --.")
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from src.mod_agent.platform_execution_snapshot import prepare_snapshot

    reference = prepare_snapshot(source_root=root, snapshot_root=selected.snapshot_root,
        business_argv=business, run_root=selected.run_root, extra_load_refs=selected.extra_load_ref,
        bound_inputs=selected.bound_input, resource_dirs=("config", *selected.resource_dir))
    command = [sys.executable, "-I", "-B", str(selected.snapshot_root / "scripts/run_frozen_product.py"),
               "--_child", reference["path"], reference["sha256"]]
    # Inherit original stdout/stderr and working directory; the child CLI owns output.
    # 为什么要有它：启动器不能重写业务参数、结果或退出码来制造成功。
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from error
