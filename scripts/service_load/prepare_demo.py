"""Idempotent Compose initialization over a source-bound real retrieval corpus."""
import argparse
import hashlib
import json
from pathlib import Path

from prepare_corpus import REPO, prepare


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    root = args.output_root.resolve()
    if not root.exists():
        print(json.dumps(prepare(root, "service_load")))
        return
    manifest = json.loads((root / "manifest.json").read_bytes())
    assert manifest["status"] == "ready"
    for row in manifest["source_refs"]:
        assert hashlib.sha256((REPO / row["source"]).read_bytes()).hexdigest() == row["sha256"], "Corpus sources changed; select a fresh corpus volume"
    assert hashlib.sha256((root / "settings.yaml").read_bytes()).hexdigest() == manifest["settings_sha256"]
    # 为什么要有它：重新启动可复用同一语料，源码变化则明确拒绝，不能删除旧证据或静默把旧索引当新版本。
    print(json.dumps({"status": "existing_source_bound_corpus", "documents": manifest["document_count"]}))


if __name__ == "__main__":
    main()
