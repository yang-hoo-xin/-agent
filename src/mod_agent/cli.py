"""Minimal Phase A CLI for the Controlled Mod Agent platform."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Sequence

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
        description="Controlled Mod Agent Platform CLI",
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

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
