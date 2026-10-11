"""Public graph and historical reconstruction preserve online comparison settings.

Model transports and baseline compiler are controlled fixture boundaries.
"""
import json
from pathlib import Path

import pytest

from src.mod_agent import cli, local_entry
from src.mod_agent.evidence.optimization_policy import optimization_policy, run_optimization_policy
from src.mod_agent.evidence.requirement_coverage_provider import StructuredModelRequirementCoverageProvider
from tests.unit import test_mod_agent_cli as scenarios
from tests.unit.test_dsh_run_request import execution_config as _execution_config_fixture
from tests.unit.test_initial_findings_continuation import _failed_run

execution_config = _execution_config_fixture


@pytest.mark.parametrize("flags,expected", [([], True), (["--no-reuse-query-observations", "--no-compress-findings-input"], False)])
def test_cli_controls_reach_initial_and_reassessment_owners_and_records(tmp_path, monkeypatch, capsys, flags, expected):
    real_main = scenarios.main
    monkeypatch.setattr(scenarios, "main", lambda args: real_main([*args, *flags]))
    constructed = []
    real_init = StructuredModelRequirementCoverageProvider.__init__
    def record(self, *args, **kwargs):
        # This existing transport fixture emits legacy Findings rows, not native planning decisions.
        kwargs["native_findings_contract"] = None
        real_init(self, *args, **kwargs)
        constructed.append(self.compress_findings_input)
    monkeypatch.setattr(StructuredModelRequirementCoverageProvider, "__init__", record)
    result = scenarios._public_patch_upstream_scenario(tmp_path, monkeypatch, capsys,
        initial_findings_gap=True)
    assert result.exit_code == 0 and result.result["status"] == "awaiting_approval", result.result
    assert len(result.findings) == 2 and len(result.searches) == 2
    assert len(constructed) >= 2 and set(constructed) == {expected}
    for _, pack in result.searches:
        assert pack.budget_summary["query_observation_reuse"].get("enabled", True) is expected
    wanted = optimization_policy(reuse_query_observations=expected, compress_findings_input=expected)
    assert result.result["evidence_optimization"] == wanted
    root = Path(result.result["run_root"])
    for filename in ("run_manifest.json", "run_result.json"):
        assert json.loads((root / filename).read_text(encoding="utf-8"))["evidence_optimization"] == wanted
    assert run_optimization_policy(root) == wanted
    assert result.result["actual_write_performed"] is False


@pytest.mark.parametrize("key", ["reuse_query_observations", "compress_findings_input"])
@pytest.mark.parametrize("bad", [0, 1, None, "false"])
def test_local_entry_rejects_nonboolean_controls_before_any_effect(tmp_path, key, bad):
    with pytest.raises(ValueError, match="EVIDENCE_OPTIMIZATION_POLICY_INVALID"):
        local_entry.run_local_request(description="test", target_project=tmp_path / "missing",
            workspace_base=tmp_path / "runs", settings_path=tmp_path / "missing-settings",
            confirm_isolated_write=True, allow_build=False, allow_source_disclosure=False,
            **{key: bad})
    assert not (tmp_path / "runs").exists()


def test_recorded_false_and_legacy_defaults_are_distinct(tmp_path):
    assert run_optimization_policy(tmp_path) == optimization_policy()
    path = tmp_path / "run_manifest.json"
    path.write_text(json.dumps({"run_id": "legacy"}))
    assert run_optimization_policy(tmp_path) == optimization_policy()
    wanted = optimization_policy(reuse_query_observations=False, compress_findings_input=False)
    path.write_text(json.dumps({"evidence_optimization": wanted}))
    assert run_optimization_policy(tmp_path) == wanted
    for invalid in (None, {}, {**wanted, "compress_findings_input": "false"}, {**wanted, "extra": True}):
        path.write_text(json.dumps({"evidence_optimization": invalid}))
        with pytest.raises(ValueError, match="EVIDENCE_OPTIMIZATION_POLICY_INVALID"):
            run_optimization_policy(tmp_path)


def test_cli_boolean_optional_controls_are_independent():
    args = cli.build_parser().parse_args(["run-request", "test", "--target-project", "x",
        "--workspace-root", "y", "--no-reuse-query-observations", "--compress-findings-input"])
    assert args.reuse_query_observations is False and args.compress_findings_input is True


def test_same_task_preparation_keeps_disabled_controls(execution_config, monkeypatch, capsys):
    from src.mod_agent.initial_findings_continuation import prepare_initial_findings_continuation
    from src.mod_agent.evidence.rg_live import RgLiveEvidenceProvider

    config = json.loads(execution_config.read_text())
    config["arguments"] += ["--no-reuse-query-observations", "--no-compress-findings-input"]
    execution_config.write_text(json.dumps(config))
    result, _ = _failed_run(execution_config, monkeypatch, capsys)
    root = Path(result["run_root"])
    source_modes, semantic_modes = [], []
    real_source_init = RgLiveEvidenceProvider.__init__
    real_semantic_init = StructuredModelRequirementCoverageProvider.__init__
    def source_init(self, *args, **kwargs):
        real_source_init(self, *args, **kwargs)
        source_modes.append(self.reuse_query_observations)
    def semantic_init(self, *args, **kwargs):
        real_semantic_init(self, *args, **kwargs)
        semantic_modes.append(self.compress_findings_input)
    monkeypatch.setattr(RgLiveEvidenceProvider, "__init__", source_init)
    monkeypatch.setattr(StructuredModelRequirementCoverageProvider, "__init__", semantic_init)
    prepared = prepare_initial_findings_continuation(run_root=root, run_id=result["run_id"],
        execution_config=execution_config)
    assert prepared["status"] == "prepared_blocked", prepared
    assert source_modes and set(source_modes) == {False}
    assert semantic_modes and set(semantic_modes) == {False}
    assert prepared["continuation_input"]["evidence_optimization"] == optimization_policy(
        reuse_query_observations=False, compress_findings_input=False)


def test_dsh_new_task_preserves_explicit_controls_and_rejects_ambiguity(execution_config):
    from scripts import dsh_run_request as bridge
    config = json.loads(execution_config.read_text())
    config["arguments"] += ["--no-reuse-query-observations", "--no-compress-findings-input"]
    execution_config.write_text(json.dumps(config))
    selected = bridge.prepare_new_task(execution_config=str(execution_config), description="change Load")
    args = cli.build_parser().parse_args(bridge.build_product_argv(
        execution_config=selected, description="change Load"))
    assert args.reuse_query_observations is False and args.compress_findings_input is False
    config["arguments"].append("--compress-findings-input")
    execution_config.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="OPTION_CONFLICT"):
        bridge.build_product_argv(execution_config=str(execution_config), description="change Load")
