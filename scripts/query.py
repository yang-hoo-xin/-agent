#!/usr/bin/env python
"""Normal query→rewrite→hybrid retrieval→rerank→answer/citations entry.

Use --json for one structured final result or --stream for JSONL progress/content/final events.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.core.query_engine.query_service import QueryRequest
from src.core.query_engine.service_factory import create_query_service
from src.core.settings import load_settings


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", "-q", required=True)
    parser.add_argument("--collection", "-c", default="default")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--config", "--settings", default=str(REPO_ROOT / "config/settings.yaml"))
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--rewrite", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--request-id")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        settings = load_settings(args.config)
        service = create_query_service(settings, args.collection)
        request = QueryRequest(query=args.query, collection=args.collection, top_k=args.top_k,
            answer=not args.retrieval_only, rewrite=args.rewrite, stream=True if args.stream else None,
            rerank=not args.no_rerank, request_id=args.request_id)
    except Exception as error:
        print(json.dumps({"status": "configuration_failed", "error_type": type(error).__name__}), file=sys.stderr)
        return 2
    def event(row):
        print(json.dumps(row, ensure_ascii=False), flush=True)
    response = service.query(request, on_event=event if args.stream else None).to_dict()
    if not args.stream:
        if args.json:
            print(json.dumps(response, ensure_ascii=False, indent=2))
        elif response["status"] == "completed":
            print(response["answer"] or "\n".join(item["text"] for item in response["results"]) or "No retrieved evidence.")
            for item in response["citations"]:
                print(f"[context:{item['context_number']}] {item['metadata'].get('source_path', item['chunk_id'])}")
        else:
            print(json.dumps({"status": response["status"], "error": response["error"]}), file=sys.stderr)
    if args.verbose:
        print(json.dumps(response["trace"], ensure_ascii=False), file=sys.stderr)
    return 0 if response["status"] == "completed" else 1


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
