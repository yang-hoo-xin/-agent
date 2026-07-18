"""Local CLI for the Evidence-Grounded Controlled Code Generation Agent Platform."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from .artifacts.store import ArtifactStorePreflightError
from .evidence import R8EvidenceError, R8ILInspectionError
from .evidence_only import EvidenceOnlyError, run_gtfo_r8_evidence_only
from .intelligent_evidence_only import (
    IntelligentEvidenceEntryError,
    run_intelligent_evidence_only,
)
from .local_entry import LocalEntryError, run_local_request
from .planning import ModPlanningBriefBuilder, RequestPlanner
from .tools import PermissionModel


@dataclass(frozen=True)
class PlanRequestResult:
    """Structured no-write planning result returned by plan-request."""

    status: str
    command: str
    request: str
    execution_mode: str
    writes_performed: bool
    stopped_before: str
    request_planning_report: dict[str, object]
    mod_planning_brief: dict[str, object]


def plan_request(
    description: str,
    *,
    target_game: str | None = None,
    target_mod: str | None = None,
) -> PlanRequestResult:
    """Run request planning and stop before feature specification."""

    request_plan = RequestPlanner().plan(description, target_mod=target_mod)
    planning_brief = ModPlanningBriefBuilder().build_planning_only(
        request_plan,
        target_game=target_game,
    )
    return PlanRequestResult(
        status=planning_brief.decision,
        command="plan-request",
        request=description,
        execution_mode="planning_only",
        writes_performed=False,
        stopped_before="feature_spec",
        request_planning_report=request_plan.to_artifact_payload(),
        mod_planning_brief=planning_brief.to_artifact_payload(),
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
        help="Create a no-write request plan and planning brief.",
    )
    plan_parser.add_argument("description", help="Natural-language request description.")
    plan_parser.add_argument("--target-game")
    plan_parser.add_argument("--target-mod")

    evidence_parser = subparsers.add_parser(
        "evidence-request",
        help="Read the approved GTFO R8 snapshot and stop before implementation planning.",
    )
    evidence_parser.add_argument("description", help="Natural-language Mod request.")
    evidence_parser.add_argument("--evidence-root", required=True)
    evidence_parser.add_argument("--artifact-root", default="artifacts/evidence_only")
    evidence_parser.add_argument("--target-mod", default="WallCrawler")
    evidence_parser.add_argument("--assembly-path")
    evidence_parser.add_argument("--current-interop-path")
    evidence_parser.add_argument("--enemy-animation-fix-path")
    evidence_parser.add_argument("--stuck-enemy-fix-path")

    intelligent_evidence_parser = subparsers.add_parser(
        "intelligent-evidence-request",
        help="Let the Evidence specialist select read-only assembly tools and stop after evidence.",
    )
    intelligent_evidence_parser.add_argument(
        "description", help="Natural-language evidence request."
    )
    intelligent_evidence_parser.add_argument("--source-registry", required=True)
    intelligent_evidence_parser.add_argument(
        "--artifact-root", default="artifacts/intelligent_evidence_only"
    )
    intelligent_evidence_parser.add_argument("--settings", default="config/settings.yaml")
    intelligent_evidence_parser.add_argument("--target-domain", default="gtfo")
    intelligent_evidence_parser.add_argument("--target-mod", default="WallCrawler")
    intelligent_evidence_parser.add_argument("--api-key-env", default="DASHSCOPE_API_KEY")
    intelligent_evidence_parser.add_argument(
        "--base-url-env", default="DASHSCOPE_BASE_URL"
    )
    intelligent_evidence_parser.add_argument(
        "--allow-evidence-disclosure",
        action="store_true",
        help=(
            "Approve this run to send the natural-language request, path-hidden source "
            "views, and metadata/IL tool observations to the configured model."
        ),
    )
    intelligent_evidence_parser.add_argument(
        "--local-ollama",
        action="store_true",
        help=(
            "Use Ollama through a literal loopback endpoint; no external model "
            "disclosure is authorized."
        ),
    )
    intelligent_evidence_parser.add_argument(
        "--ollama-base-url", default="http://127.0.0.1:11434"
    )
    intelligent_evidence_parser.add_argument(
        "--ollama-model", default="qwen3:4b-instruct"
    )
    intelligent_evidence_parser.add_argument(
        "--ollama-max-output-tokens", type=int, default=4096
    )

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
    """Run the local controlled-development CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "plan-request":
        result = plan_request(
            args.description,
            target_game=args.target_game,
            target_mod=args.target_mod,
        )
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

    if args.command == "evidence-request":
        try:
            result = run_gtfo_r8_evidence_only(
                description=args.description,
                evidence_root=args.evidence_root,
                artifact_root=args.artifact_root,
                target_mod=args.target_mod,
                assembly_path=args.assembly_path,
                current_interop_path=args.current_interop_path,
                enemy_animation_fix_path=args.enemy_animation_fix_path,
                stuck_enemy_fix_path=args.stuck_enemy_fix_path,
            )
        except (
            EvidenceOnlyError,
            R8EvidenceError,
            R8ILInspectionError,
            OSError,
            ValueError,
        ) as exc:
            print(
                json.dumps(
                    {"status": "BLOCKED", "command": "evidence-request", "reason": str(exc)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "intelligent-evidence-request":
        try:
            result = run_intelligent_evidence_only(
                description=args.description,
                source_registry_path=args.source_registry,
                artifact_root=args.artifact_root,
                settings_path=args.settings,
                allow_evidence_disclosure=bool(args.allow_evidence_disclosure),
                target_domain=args.target_domain,
                target_mod=args.target_mod,
                api_key_env=args.api_key_env,
                base_url_env=args.base_url_env,
                local_ollama=bool(args.local_ollama),
                ollama_base_url=args.ollama_base_url,
                ollama_model=args.ollama_model,
                ollama_max_output_tokens=args.ollama_max_output_tokens,
            )
        except ArtifactStorePreflightError as exc:
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "command": "intelligent-evidence-request",
                        "reason": str(exc),
                        "diagnostic": {
                            "category": "infrastructure_preflight_failure",
                            "component": "artifact_store",
                            "stage": "artifact_preflight",
                            "code": "artifact_path_unaddressable",
                            "operation": "os.replace",
                            "model_execution_started": False,
                            "tool_execution_started": False,
                            "model_call_count": 0,
                            "tool_call_count": 0,
                            "details": {
                                "artifact_type": exc.artifact_type,
                                "path_role": exc.path_role,
                                "source_path_length": exc.source_path_length,
                                "target_path_length": exc.target_path_length,
                                "target_parent_exists": exc.target_parent_exists,
                                "winerror": exc.winerror,
                            },
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        except (IntelligentEvidenceEntryError, OSError, RuntimeError, ValueError) as exc:
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "command": "intelligent-evidence-request",
                        "reason": str(exc),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
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
