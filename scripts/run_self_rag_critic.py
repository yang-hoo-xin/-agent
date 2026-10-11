"""Prepare exposed RAG candidates by default; execute the fixed local Critic explicitly."""
from __future__ import annotations

import argparse
import json

from src.mod_agent.evaluation.self_rag_critic import execute, prepare


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("prepare", "execute"), default="prepare")
    parser.add_argument("--answers")
    parser.add_argument("--retrieval")
    parser.add_argument("--output")
    parser.add_argument("--prepared")
    args = parser.parse_args(argv)
    if args.mode == "prepare":
        if not all((args.answers, args.retrieval, args.output)) or args.prepared:
            parser.error("prepare requires --answers, --retrieval and --output only")
        result = prepare(args.answers, args.retrieval, args.output)
    else:
        if not args.prepared or any((args.answers, args.retrieval, args.output)):
            parser.error("execute requires --prepared only")
        result = execute(args.prepared)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
