"""Thin human DSH view of the existing reviewed Patch owner."""
import argparse
import json

from src.mod_agent.reviewed_patch_continuation import prepare_reviewed_patch_apply, review_run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("artifact-store-root", "workspace-root", "feature-id", "run-id"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--isolated-root")
    parser.add_argument("--operation-id")
    args = parser.parse_args(argv)
    if (args.isolated_root is None) != (args.operation_id is None):
        parser.error("isolated-root and operation-id must be supplied together")
    keywords = dict(artifact_store_root=args.artifact_store_root, workspace_root=args.workspace_root,
                    feature_id=args.feature_id, run_id=args.run_id)
    result = review_run(**keywords)
    if args.isolated_root is not None:
        try:
            result = prepare_reviewed_patch_apply(**keywords, isolated_root=args.isolated_root, operation_id=args.operation_id)
        except (ValueError, RuntimeError, OSError) as exc:
            result.update(apply_preparation=None, apply_preparation_unavailable_reason=str(exc))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
