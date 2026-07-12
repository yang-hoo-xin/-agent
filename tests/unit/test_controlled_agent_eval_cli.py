"""Tests for the controlled-agent evaluation CLI."""

from __future__ import annotations

import json

from scripts.evaluate_controlled_agent import DEFAULT_FIXTURE, main
from src.mod_agent.evaluation import load_agent_quality_cases


def test_cli_outputs_complete_calibration_report(capsys, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = main(["--arm-id", "arm_a_fixture", "--top-k", "5"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["dataset_version"] == "v2_eval_001_fixture_v2"
    assert output["arm_id"] == "arm_a_fixture"
    assert output["top_k"] == 5
    assert output["completeness_status"] == "complete"
    assert output["quality_gate_status"] == "not_evaluated"
    assert output["gate_eligible"] is False


def test_cli_quality_requirement_rejects_calibration(capsys) -> None:
    exit_code = main(["--require-quality-pass"])

    capsys.readouterr()
    assert exit_code == 5


def test_cli_runs_a_fully_bound_benchmark(tmp_path, capsys) -> None:
    data = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))
    data["dataset_kind"] = "benchmark"
    data["quality_gate_eligible"] = True
    cases = tmp_path / "benchmark.json"
    cases.write_text(json.dumps(data), encoding="utf-8")
    data["dataset_sha256"] = load_agent_quality_cases(cases).dataset_sha256
    cases.write_text(json.dumps(data), encoding="utf-8")

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "repository_revision": "abc123", "worktree_diff_sha256": "sha256:diff",
        "corpus_manifest_sha256": "sha256:corpus",
        "evaluation_protocol_sha256": "sha256:protocol", "provider_id": "fixed",
        "provider_version": "1", "evidence_status": "fresh",
        "percentile_method": "nearest_rank",
    }), encoding="utf-8")
    names = ["recall_at_k", "precision_at_k", "precision_at_returned", "mrr_at_k"]
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({
        "policy_schema_version": "quality_gate_policy_v1", "policy_id": "test-v1",
        "required_metric_names": names, "thresholds": {name: 0.01 for name in names},
    }), encoding="utf-8")

    exit_code = main([
        "--cases", str(cases), "--observations", str(cases),
        "--run-manifest", str(manifest), "--quality-policy", str(policy),
        "--require-quality-pass",
    ])
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["dataset_kind"] == "benchmark"
    assert output["quality_gate_status"] == "pass"


def test_cli_rejects_duplicate_json_keys(tmp_path, capsys) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"dataset_schema_version":"1","dataset_schema_version":"2"}', encoding="utf-8")
    assert main(["--cases", str(duplicate)]) == 2
    assert "duplicate JSON key" in capsys.readouterr().err
