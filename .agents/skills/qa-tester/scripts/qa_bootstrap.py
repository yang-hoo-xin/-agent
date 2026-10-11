#!/usr/bin/env python3
"""Set up or inspect data in an explicitly isolated QA checkout.

Usage:
    python .agents/skills/qa-tester/scripts/qa_bootstrap.py COMMAND --target-repo PATH

Commands:
    baseline   Set up Baseline state (default collection + test_col + traces)
    clear      Clear all data → Empty state
    status     Show current system state
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from qa_paths import SOURCE_REPO_ROOT, require_contained_path, resolve_isolated_repo


REPO_ROOT = SOURCE_REPO_ROOT
sys.path.insert(0, str(REPO_ROOT))

# Baseline documents
BASELINE_DEFAULT = ["simple.pdf", "with_images.pdf"]
BASELINE_TEST_COL = ["complex_technical_doc.pdf"]

# Baseline queries (to generate query traces)
BASELINE_QUERIES = [
    ("What is hybrid search and how does it work", "default"),
    ("What is Modular RAG", "default"),
    ("Explain the chunking strategy", "default"),
    ("Retrieval-Augmented Generation modular architecture", "test_col"),
    ("Sample Document PDF loader", "default"),
]


def run_cmd(
    target_repo: Path,
    args: list[str],
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess:
    """Run a target checkout command from that checkout."""
    return subprocess.run(
        [sys.executable] + args,
        cwd=str(target_repo),
        check=check,
        capture_output=capture,
        text=True,
    )


def _target_paths(target_repo: Path) -> tuple[Path, Path, Path, Path]:
    scripts_dir = target_repo / "scripts"
    fixtures_dir = target_repo / "tests" / "fixtures" / "sample_documents"
    data_dir = target_repo / "data"
    traces_file = target_repo / "logs" / "traces.jsonl"
    return scripts_dir, fixtures_dir, data_dir, traces_file


def clear_all(target_repo: Path) -> None:
    """Clear QA state only inside a marked isolated checkout."""
    target_repo = resolve_isolated_repo(target_repo)
    _, _, data_dir, traces_file = _target_paths(target_repo)
    data_dir = require_contained_path(target_repo, data_dir)
    traces_file = require_contained_path(target_repo, traces_file)
    print("🗑️  Clearing all data...")

    # Clear Chroma
    chroma_dir = data_dir / "db" / "chroma"
    chroma_dir = require_contained_path(target_repo, chroma_dir)
    if chroma_dir.exists():
        for item in chroma_dir.iterdir():
            require_contained_path(target_repo, item)
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        print("   ✅ Chroma data cleared")

    # Clear BM25
    bm25_dir = data_dir / "db" / "bm25"
    bm25_dir = require_contained_path(target_repo, bm25_dir)
    if bm25_dir.exists():
        for item in bm25_dir.iterdir():
            require_contained_path(target_repo, item)
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        print("   ✅ BM25 data cleared")

    # Clear images
    images_dir = data_dir / "images"
    images_dir = require_contained_path(target_repo, images_dir)
    if images_dir.exists():
        for item in images_dir.iterdir():
            require_contained_path(target_repo, item)
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        print("   ✅ Image data cleared")

    # Clear file integrity DB
    integrity_db = data_dir / "db" / "ingestion_history.db"
    integrity_db = require_contained_path(target_repo, integrity_db)
    if integrity_db.exists():
        integrity_db.unlink()
        print("   ✅ File integrity DB cleared")

    # Clear traces
    if traces_file.exists():
        traces_file.write_text("", encoding="utf-8")
        print("   ✅ Traces cleared")

    print("✅ System is now in Empty state")


def setup_baseline(target_repo: Path) -> bool:
    """Set up baseline state in a marked isolated checkout."""
    target_repo = resolve_isolated_repo(target_repo)
    scripts_dir, fixtures_dir, _, _ = _target_paths(target_repo)
    scripts_dir = require_contained_path(target_repo, scripts_dir)
    fixtures_dir = require_contained_path(target_repo, fixtures_dir)
    config = require_contained_path(
        target_repo, target_repo / "config" / "settings.yaml"
    )
    succeeded = True
    print("📦 Setting up Baseline state...")
    print()

    # Step 1: Clear existing data
    clear_all(target_repo)
    print()

    # Step 2: Ingest default collection
    print("📄 Ingesting default collection (simple.pdf + with_images.pdf)...")
    for filename in BASELINE_DEFAULT:
        pdf = fixtures_dir / filename
        if not pdf.exists():
            print(f"   ⚠️  File not found: {pdf}")
            succeeded = False
            continue
        print(f"   → {pdf.name}")
        result = run_cmd(
            target_repo,
            [str(scripts_dir / "ingest.py"), "--path", str(pdf), "--collection", "default", "--force", "--config", str(config)],
            check=False,
        )
        if result.returncode != 0:
            print(f"   ❌ Failed to ingest {pdf.name} (exit code: {result.returncode})")
            succeeded = False
        else:
            print(f"   ✅ {pdf.name}")

    print()

    # Step 3: Ingest test_col collection
    print("📄 Ingesting test_col collection (complex_technical_doc.pdf)...")
    for filename in BASELINE_TEST_COL:
        pdf = fixtures_dir / filename
        if not pdf.exists():
            print(f"   ⚠️  File not found: {pdf}")
            succeeded = False
            continue
        print(f"   → {pdf.name}")
        result = run_cmd(
            target_repo,
            [str(scripts_dir / "ingest.py"), "--path", str(pdf), "--collection", "test_col", "--force", "--config", str(config)],
            check=False,
        )
        if result.returncode != 0:
            print(f"   ❌ Failed to ingest {pdf.name} (exit code: {result.returncode})")
            succeeded = False
        else:
            print(f"   ✅ {pdf.name}")

    print()

    # Step 4: Run queries to generate query traces
    print("🔍 Running baseline queries to generate traces...")
    for query_item in BASELINE_QUERIES:
        if isinstance(query_item, tuple):
            query, collection = query_item
        else:
            query, collection = query_item, "default"
        print(f"   → \"{query}\" (collection={collection})")
        cmd = [str(scripts_dir / "query.py"), "--query", query, "--collection", collection, "--config", str(config)]
        result = run_cmd(target_repo, cmd, check=False)
        if result.returncode != 0:
            print(f"   ❌ Query failed (exit code: {result.returncode})")
            succeeded = False
        else:
            print(f"   ✅ Done")

    print()
    if succeeded:
        print("✅ System is now in Baseline state")
        print("   default: simple.pdf + with_images.pdf")
        print("   test_col: complex_technical_doc.pdf")
        print("   traces: ingestion + query traces generated")
    else:
        print("❌ Baseline setup failed; inspect the missing or failed steps above")
    return succeeded


def show_status(target_repo: Path) -> None:
    """Show state for a marked isolated checkout."""
    target_repo = resolve_isolated_repo(target_repo)
    _, _, data_dir, traces_file = _target_paths(target_repo)
    data_dir = require_contained_path(target_repo, data_dir)
    traces_file = require_contained_path(target_repo, traces_file)
    print("📊 System Status")
    print("=" * 50)

    # Check Chroma
    chroma_dir = data_dir / "db" / "chroma"
    if chroma_dir.exists():
        files = list(chroma_dir.rglob("*"))
        print(f"   Chroma: {len(files)} files")
    else:
        print("   Chroma: empty")

    # Check BM25
    bm25_dir = data_dir / "db" / "bm25"
    if bm25_dir.exists():
        files = list(bm25_dir.rglob("*"))
        print(f"   BM25: {len(files)} files")
    else:
        print("   BM25: empty")

    # Check images
    images_dir = data_dir / "images"
    if images_dir.exists():
        imgs = list(images_dir.rglob("*.png")) + list(images_dir.rglob("*.jpg"))
        print(f"   Images: {len(imgs)} files")
    else:
        print("   Images: empty")

    # Check traces
    if traces_file.exists():
        lines = [l for l in traces_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        print(f"   Traces: {len(lines)} entries")
    else:
        print("   Traces: none")


def main() -> int:
    parser = argparse.ArgumentParser(description="QA Bootstrap — manage system state")
    parser.add_argument(
        "command",
        nargs="?",
        default="status",
        choices=["baseline", "clear", "status"],
        help="Command to execute (default: status)",
    )
    parser.add_argument(
        "--target-repo",
        required=True,
        type=Path,
        help="Marked isolated checkout that receives every QA state change",
    )
    args = parser.parse_args()

    if args.command == "baseline":
        return 0 if setup_baseline(args.target_repo) else 1
    elif args.command == "clear":
        clear_all(args.target_repo)
    elif args.command == "status":
        show_status(args.target_repo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
