#!/usr/bin/env python
"""Run deterministic controlled-agent evaluation from versioned JSON fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.mod_agent.evaluation import (  # noqa: E402
    QualityGatePolicy,
    RetrievalRegressionRunner,
    RunManifest,
    load_agent_quality_cases,
    load_observations,
)

DEFAULT_FIXTURE = PROJECT_ROOT / "tests/fixtures/evaluation/agent_quality_cases.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate fixed controlled-agent observations against versioned "
            "Hook/file/readiness ground truth."
        )
    )
    parser.add_argument(
        "--cases",
        default=str(DEFAULT_FIXTURE),
        help="Versioned case JSON path.",
    )
    parser.add_argument(
        "--observations",
        default=str(DEFAULT_FIXTURE),
        help="Observation JSON path.",
    )
    parser.add_argument("--arm-id", default="fixture_baseline")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--run-manifest", help="Required run-manifest JSON for benchmark datasets.")
    parser.add_argument("--quality-policy", help="Required quality-policy JSON for benchmark datasets.")
    parser.add_argument(
        "--require-quality-pass",
        action="store_true",
        help="Return exit code 5 unless an eligible benchmark quality gate passes.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        dataset = load_agent_quality_cases(args.cases)
        observations = load_observations(args.observations)
        if dataset.dataset_kind == "benchmark" and (not args.run_manifest or not args.quality_policy):
            print(
                "controlled-agent evaluation configuration missing: benchmark requires "
                "--run-manifest and --quality-policy",
                file=sys.stderr,
            )
            return 3
        manifest = (
            _load_run_manifest(Path(args.run_manifest))
            if args.run_manifest
            else RunManifest(
                repository_revision="calibration-unbound",
                worktree_diff_sha256="calibration-unbound",
                corpus_manifest_sha256="calibration-unbound",
                evaluation_protocol_sha256="calibration-v2",
                provider_id="fixed_calibration_observations",
                provider_version="1",
                evidence_status="unknown",
            )
        )
        policy = _load_quality_policy(Path(args.quality_policy)) if args.quality_policy else None
        report = RetrievalRegressionRunner().run_fixed_observations(
            dataset=dataset,
            arm_id=args.arm_id,
            observation_set=observations,
            run_manifest=manifest,
            top_k=args.top_k,
            quality_policy=policy,
        )
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"controlled-agent evaluation failed: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"controlled-agent evaluation execution failed: {exc}", file=sys.stderr)
        return 3
    try:
        print(
            json.dumps(
                report.to_dict(),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
        )
    except ValueError as exc:
        print(f"controlled-agent evaluation serialization failed: {exc}", file=sys.stderr)
        return 3
    if report.completeness_status != "complete":
        return 4
    if args.require_quality_pass and report.quality_gate_status != "pass":
        return 5
    return 0


def _load_json_object(path: Path, label: str) -> dict[str, object]:
    def reject_duplicates(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicates,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f"non-standard JSON numeric constant: {token}")
        ),
    )
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _load_run_manifest(path: Path) -> RunManifest:
    value = _load_json_object(path, "run manifest")
    allowed = {
        "repository_revision", "worktree_diff_sha256", "corpus_manifest_sha256",
        "evaluation_protocol_sha256", "provider_id", "provider_version",
        "evidence_status", "percentile_method",
    }
    extra = set(value) - allowed
    if extra:
        raise ValueError(f"unexpected run-manifest fields: {', '.join(sorted(extra))}")
    return RunManifest(**value)  # type: ignore[arg-type]


def _load_quality_policy(path: Path) -> QualityGatePolicy:
    return QualityGatePolicy.from_mapping(_load_json_object(path, "quality policy"))


if __name__ == "__main__":
    raise SystemExit(main())
