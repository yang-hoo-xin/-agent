"""Minimal Phase A CLI for the Evidence-Grounded Controlled Code Generation Agent Platform."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from .local_entry import LocalEntryError, run_local_request
from .tools import PermissionModel


@dataclass(frozen=True)
class StubPlanRequestResult:
    """Structured placeholder returned by the Phase A plan-request command."""

    status: str
    command: str
    request: str
    message: str


def plan_request(description: str) -> StubPlanRequestResult:
    """Return a safe Phase A placeholder for request planning."""

    return StubPlanRequestResult(
        status="stubbed",
        command="plan-request",
        request=description,
        message=(
            "Phase A platform skeleton only. Request planning is not implemented yet."
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser."""

    parser = argparse.ArgumentParser(
        prog="mod-agent",
        description="Evidence-Grounded Controlled Code Generation Agent Platform CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser(
        "plan-request",
        help="Return a stubbed request-planning result.",
    )
    plan_parser.add_argument("description", help="Natural-language request description.")

    apply_parser = subparsers.add_parser(
        "apply-patch",
        help="Blocked placeholder for future patch application.",
    )
    apply_parser.add_argument("--confirm", action="store_true", help="Request confirmed apply.")

    run_parser = subparsers.add_parser(
        "run-request",
        help="Run one controlled request against an isolated copy of a real target project.",
    )
    run_parser.add_argument("description", help="Natural-language Mod request.")
    run_parser.add_argument("--target-project", required=True)
    run_parser.add_argument(
        "--workspace-root",
        default="workspaces/v2_codegen_real_001",
    )
    run_parser.add_argument("--settings", default="config/settings.yaml")
    run_parser.add_argument("--api-key-env", default="DASHSCOPE_API_KEY")
    run_parser.add_argument("--base-url-env", default="DASHSCOPE_BASE_URL")
    run_parser.add_argument(
        "--allow-source-disclosure",
        action="store_true",
        help=(
            "Explicitly allow this run to send retrieved local source excerpts "
            "and binding context to the configured external LLM."
        ),
    )
    run_parser.add_argument("--confirm-isolated-write", action="store_true")
    run_parser.add_argument("--allow-build", action="store_true")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Phase A CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "plan-request":
        result = plan_request(args.description)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0

    if args.command == "apply-patch":
        decision = PermissionModel().decide("confirmed_write")
        print(
            json.dumps(
                {
                    "status": "BLOCKED" if not decision.allowed else "allowed",
                    "command": "apply-patch",
                    "reason": decision.reason,
                    "required_approval": decision.required_approval,
                    "confirmed": bool(args.confirm),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "run-request":
        def read_diff_approval(dry_run: dict[str, object]) -> str:
            print(
                json.dumps(
                    {
                        "status": "AWAITING_EXACT_DIFF_APPROVAL",
                        "diff_hash": dry_run.get("diff_hash"),
                        "context_hashes": dry_run.get("context_hashes"),
                        "diff_preview": dry_run.get("diff_preview"),
                        "instruction": (
                            "Paste the exact diff_hash to approve isolated apply; "
                            "any other input blocks the write."
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                file=sys.stderr,
            )
            print("Exact diff hash approval: ", end="", file=sys.stderr, flush=True)
            return sys.stdin.readline().strip()

        try:
            result = run_local_request(
                description=args.description,
                target_project=args.target_project,
                workspace_base=args.workspace_root,
                settings_path=args.settings,
                api_key_env=args.api_key_env,
                base_url_env=args.base_url_env,
                confirm_isolated_write=bool(args.confirm_isolated_write),
                allow_build=bool(args.allow_build),
                allow_source_disclosure=bool(args.allow_source_disclosure),
                diff_approval_reader=read_diff_approval,
            )
        except LocalEntryError as exc:
            print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return (
            0
            if result.get("build_summary", {}).get("claims_real_build_success") is True
            else 1
        )

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
