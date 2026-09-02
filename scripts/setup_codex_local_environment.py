"""Install the locked development environment for a Codex local worktree."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    uv = shutil.which("uv")
    if uv is None:
        print("uv is required but was not found on PATH.", file=sys.stderr)
        return 127

    repository_root = Path(__file__).resolve().parents[1]
    commands = (
        (uv, "lock", "--check"),
        (uv, "sync", "--frozen", "--extra", "dev", "--python", "3.10"),
    )
    for command in commands:
        completed = subprocess.run(command, cwd=repository_root, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
