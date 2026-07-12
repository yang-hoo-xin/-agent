#!/usr/bin/env python
"""Execute the repository-backed Arm A rg/live-read benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.mod_agent.evaluation import (  # noqa: E402
    OfficialArmARunner,
    QualityGatePolicy,
    load_agent_quality_cases,
)

DEFAULT_CASES = PROJECT_ROOT / "evaluation/benchmarks/arm_a_repo_smoke_v3.json"
DEFAULT_PROTOCOL = PROJECT_ROOT / "evaluation/benchmarks/arm_a_repo_smoke_protocol_v3.json"
DEFAULT_POLICY = PROJECT_ROOT / "evaluation/benchmarks/arm_a_repo_smoke_policy_v1.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data/evaluation/runs"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run real Arm A rg plus live-read benchmark.")
    parser.add_argument("--workspace", default=str(PROJECT_ROOT))
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--protocol", default=str(DEFAULT_PROTOCOL))
    parser.add_argument("--quality-policy", default=str(DEFAULT_POLICY))
    parser.add_argument("--git-executable")
    parser.add_argument("--rg-executable")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--run-id", help="Optional safe run ID; generated when omitted.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        workspace = Path(args.workspace).resolve()
        dataset = load_agent_quality_cases(args.cases)
        protocol = _load_object(Path(args.protocol), "Arm A protocol")
        policy = QualityGatePolicy.from_mapping(
            _load_object(Path(args.quality_policy), "quality policy")
        )
        if protocol.get("protocol_schema_version") != "arm_a_protocol_v3":
            raise ValueError("unsupported Arm A protocol_schema_version")
        if protocol.get("dataset_version") != dataset.dataset_version:
            raise ValueError("Arm A protocol dataset_version does not match cases")
        top_k = protocol.get("top_k")
        search_roots = protocol.get("search_roots")
        search_patterns = protocol.get("search_patterns")
        if not isinstance(top_k, int) or isinstance(top_k, bool):
            raise ValueError("Arm A protocol top_k must be an integer")
        if not isinstance(search_roots, list) or not all(
            isinstance(item, str) for item in search_roots
        ):
            raise ValueError("Arm A protocol search_roots must be a string array")
        if not isinstance(search_patterns, dict) or not all(
            isinstance(case_id, str)
            and isinstance(patterns, list)
            and all(isinstance(pattern, str) for pattern in patterns)
            for case_id, patterns in search_patterns.items()
        ):
            raise ValueError("Arm A protocol search_patterns must map case IDs to string arrays")
        run_id = args.run_id or (
            "arm_a_smoke_"
            + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_")
            + uuid4().hex[:8]
        )
        runner = OfficialArmARunner(
            workspace,
            git_executable=args.git_executable,
            rg_executable=args.rg_executable,
        )
        result = runner.run(
            run_id=run_id,
            dataset=dataset,
            quality_policy=policy,
            search_patterns=search_patterns,
            search_roots=search_roots,
            top_k=top_k,
            protocol_document_sha256=(
                "sha256:" + hashlib.sha256(Path(args.protocol).read_bytes()).hexdigest()
            ),
        )
        payload = result.to_dict()
        index_entry = _write_run_ledger(
            payload=payload,
            output_dir=Path(args.output_dir).resolve(),
            run_id=run_id,
            metadata={
            "execution_mode": result.execution_mode,
            "formal_run_eligible": result.formal_run_eligible,
            "benchmark_scope": result.report.benchmark_scope,
            "promotion_eligible": result.report.promotion_eligible,
            "quality_gate_status": result.report.quality_gate_status,
            },
        )
        print(json.dumps({"result": payload, "ledger": index_entry}, ensure_ascii=False, indent=2))
        return 0 if result.report.quality_gate_status == "pass" else 5
    except (FileNotFoundError, FileExistsError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"Arm A benchmark failed: {exc}", file=sys.stderr)
        return 2


def _write_run_ledger(
    *,
    payload: dict[str, Any],
    output_dir: Path,
    run_id: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    encoded_bytes = encoded.encode("utf-8")
    result_sha256 = "sha256:" + hashlib.sha256(encoded_bytes).hexdigest()
    digest = result_sha256.removeprefix("sha256:")
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{run_id}_{digest}.json"
    with output.open("xb") as handle:
        handle.write(encoded_bytes)
    index_dir = output_dir / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    try:
        recorded_result_path = output.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        recorded_result_path = str(output)
    index_entry = {
        "run_id": run_id,
        "result_path": recorded_result_path,
        "result_sha256": result_sha256,
        **metadata,
    }
    index_path = index_dir / f"{run_id}.json"
    index_bytes = (json.dumps(index_entry, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    with index_path.open("xb") as handle:
        handle.write(index_bytes)
    return index_entry


def _load_object(path: Path, label: str) -> dict[str, Any]:
    def reject_duplicates(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
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


if __name__ == "__main__":
    raise SystemExit(main())
