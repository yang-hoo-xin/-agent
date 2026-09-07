"""Fixed DSH request-preparation bridge over the existing plan-request owner.

This entry persists only the two existing planning Artifacts. It does not read
target source, select an implementation, construct model clients or run a Graph.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.cli import plan_request

MAX_REQUEST_BYTES = 32768


def prepare_request(
    *, description: str, workspace_root: str, artifact_store_root: str, target_mod: str
) -> dict:
    """Persist deterministic intake results; no implementation Plan is implied."""
    if (not isinstance(description, str) or not description.strip()
            or "\0" in description or len(description.encode("utf-8")) > MAX_REQUEST_BYTES):
        raise ValueError("SUBMIT_REQUEST_INVALID")
    if (not isinstance(target_mod, str) or not target_mod.strip()
            or len(target_mod) > 300 or any(c in target_mod for c in "\r\n\0")):
        raise ValueError("SUBMIT_TARGET_INVALID")
    workspace = Path(workspace_root)
    store_root = Path(artifact_store_root)
    if not workspace.is_absolute() or not workspace.is_dir():
        raise ValueError("SUBMIT_WORKSPACE_UNAVAILABLE")
    if not store_root.is_absolute() or not store_root.is_dir():
        raise ValueError("SUBMIT_STORE_UNAVAILABLE")
    # Both paths come from deployment configuration, never from request text.
    result = plan_request(description, target_mod=target_mod)
    request_plan = result.request_planning_report
    brief = result.mod_planning_brief
    feature_id = request_plan["feature_id"]
    if brief["feature_id"] != feature_id:
        raise ValueError("SUBMIT_PLANNING_IDENTITY_MISMATCH")
    store = ArtifactStore(store_root)
    request_ref = store.write(
        feature_id=feature_id, artifact_type="request_planning_report",
        payload=request_plan, status="blocked" if request_plan["blocked"] else "success",
    )
    brief_ref = store.write(
        feature_id=feature_id, artifact_type="mod_planning_brief", payload=brief,
        status="blocked" if brief["blocked"] else "success", upstream_refs=[request_ref],
    )
    return {
        "entry": result.command, "status": result.status,
        "feature_id": feature_id, "target_mod": target_mod,
        "stopped_before": result.stopped_before,
        "execution_mode": "request_preparation",
        "request_planning_report": request_plan, "mod_planning_brief": brief,
        "artifacts": {"request_planning_report": asdict(request_ref),
                      "mod_planning_brief": asdict(brief_ref)},
        "artifact_writes_performed": True, "product_source_writes_performed": False,
        "model_calls_performed": 0, "verifier_executions_performed": 0,
        "configured_workspace_exists": True, "source_evidence_collected": False,
        "implementation_plan_generated": False, "product_execution_started": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--artifact-store-root", required=True)
    parser.add_argument("--target-mod", required=True)
    args = parser.parse_args(argv)
    body = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(body) > MAX_REQUEST_BYTES:
        raise ValueError("SUBMIT_REQUEST_INVALID")
    result = prepare_request(
        description=body.decode("utf-8"), workspace_root=args.workspace_root,
        artifact_store_root=args.artifact_store_root, target_mod=args.target_mod,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
