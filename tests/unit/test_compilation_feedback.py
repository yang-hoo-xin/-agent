"""Compiler observations remain feedback, never a gameplay verdict."""

import pytest

from src.mod_agent.domain.compilation_feedback import CompilationFeedback


def test_compiler_projection_preserves_external_paths_and_original_observations():
    from copy import deepcopy
    from src.mod_agent.domain.compilation_feedback import _failure_state_observations

    root = r"C:\checks\version-001\source"
    observations = [{"check_id": "full_project_compilation", "observed": {
        "report_ref": {"path": "unique-report", "sha256": "unique-hash"},
        "dependency_documentation": {"members": ["ManualLogSource.LogInfo"]},
        "diagnostics": [{"code": "CS0103", "line": 16, "file": root + r"\Plugin.cs",
                         "message": "Unknown Logger [" + root + r"\Mod.csproj]"},
                        {"file": root + r"-other\External.cs", "message": "External diagnostic"}]}}]
    before = deepcopy(observations)
    projection = _failure_state_observations(observations, root)
    assert observations == before
    projected = projection[0]["observed"]
    assert "report_ref" not in projected
    assert projected["diagnostics"][0]["file"] == "<compiled-source>/Plugin.cs"
    assert projected["diagnostics"][0]["message"] == "Unknown Logger [<compiled-source>/Mod.csproj]"
    assert projected["diagnostics"][1] == before[0]["observed"]["diagnostics"][1]
    assert projected["dependency_documentation"] == before[0]["observed"]["dependency_documentation"]


@pytest.mark.parametrize("changed_fact", [None, "code", "line", "message"])
def test_compiler_repeated_failure_ignores_run_paths_but_keeps_diagnostic_facts(tmp_path, changed_fact):
    from src.mod_agent.fresh_planning_continuation import run_fresh_patch_continuation
    from src.mod_agent.local_entry import make_exact_no_write_dry_run_factory
    from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy
    from tests.unit.test_continuous_behavior_repair import _SequenceClient
    from tests.unit.test_fresh_planning_continuation import _inputs, _patch_request
    from tests.unit.test_patch_behavior_feedback import _adapter

    class Checker:
        calls = 0

        def verification_identity(self):
            return {"validator_sha256": "a" * 64, "inputs_sha256": "b" * 64,
                    "environment_sha256": "c" * 64, "deterministic_reuse_allowed": False}

        def __call__(self, context):
            self.calls += 1
            root = str(tmp_path / f"version-{self.calls:03d}" / "source")
            diagnostic = {"code": "CS0103", "line": 16, "column": 17, "severity": "error",
                          "file": root + "/Plugin.cs", "message": "Unknown Logger [" + root + "/Mod.csproj]"}
            if changed_fact:
                diagnostic[changed_fact] = self.calls if changed_fact == "line" else str(self.calls)
            return {"status": "compilation_failed", "failure_owner": "patch_implementation",
                    "baseline": {"execution_origin": "executed", "isolated_source_root": root,
                                 "report_ref": {"path": root + "/report.json", "sha256": str(self.calls)},
                                 "build_result": {"diagnostics": [diagnostic]}}}

    inputs = _inputs(tmp_path / "case")
    # A/B/A/A reproduces new1: nonconsecutive A failures must share the same state.
    client = _SequenceClient(["RecordFirstFailure", "RecordSecondFailure", "RecordFirstFailure",
                              "RecordFirstFailure", "RecordFirstFailure"])
    checker = Checker()
    oracle = CompilationFeedback(checker, tmp_path / "reports")
    adapter = _adapter(inputs, client, oracle)
    adapter.enable_recovery_loop = True
    adapter.patch_agent_loop_policy = PatchAgentLoopPolicy(max_total_model_turns=4 if changed_fact else 5,
        max_tool_rounds=6, max_observation_bytes=100000, require_source_inspection=False,
        finalize_after_first_observation=False, enable_supporting_reads=True, allow_upstream_request=True)
    result = run_fresh_patch_continuation(_patch_request(inputs), patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace), max_model_calls=5)
    assert result.reason == ("PATCH_AGENT_CORRECTION_BUDGET_EXHAUSTED" if changed_fact else "PATCH_BEHAVIOR_NO_PROGRESS")
    assert checker.calls == len(client.requests) == 4
    evaluations = adapter.patch_attempt_receipt()["patch_agent_loop"]["behavior_evaluations"]
    assert all(item["execution_origin"] == "executed" for item in evaluations)
    assert len({item["observations"][0]["observed"]["diagnostics"][0]["file"] for item in evaluations}) == 4
    if not changed_fact:
        assert adapter.patch_attempt_receipt()["patch_agent_loop"]["behavior_repair_termination"]["remaining_model_turns"] == 1


@pytest.mark.parametrize("status,owner,expected", [
    ("passed", None, "passed"), ("compilation_failed", "patch_implementation", "behavior_failed"),
    ("environment_failed", "environment", "infrastructure_failed"),
])
def test_compilation_mapping_keeps_diagnostics_and_downstream_unknown(tmp_path, status, owner, expected):
    class Checker:
        def verification_identity(self):
            return {"validator_sha256": "a" * 64}
        def __call__(self, _):
            return {"status": status, "failure_owner": owner,
                    "baseline": {"execution_origin": "executed", "report_ref": {"path": "report"},
                                 "build_result": {"diagnostics": [{"message": "exact compiler diagnostic"}]}}}
    report = CompilationFeedback(Checker(), tmp_path)({"generated_changes": [{"edit_binding_id": "binding"}],
        "generated_changes_sha256": "changes", "source_snapshot_sha256": "source", "materialized_code_identity": {}})
    assert report["status"] == expected
    assert report["validation_results"]["runtime"]["status"] == "not_executed"
    if owner:
        assert report["observations"][0]["observed"]["diagnostics"][0]["message"] == "exact compiler diagnostic"
    assert report["owner_binding_ids"] == (["binding"] if owner == "patch_implementation" else [])


@pytest.mark.parametrize("candidate_failure,expected", [(None, "passed"), ("compiler", "behavior_failed")])
def test_failed_source_baseline_feedback_reports_the_current_candidate(tmp_path, monkeypatch, candidate_failure, expected):
    from tests.unit.test_full_project_compilation import _checker

    _, context, checker, calls, _ = _checker(tmp_path, monkeypatch,
        fail_baseline=True, changed_failure=candidate_failure)
    report = CompilationFeedback(checker, tmp_path / "feedback")(context)
    verification = report["validation_results"]["full_compilation"]
    assert report["status"] == expected and len(calls) == 2
    assert verification["baseline"]["status"] == "compilation_failed"
    assert verification["changed"]["materialized_code_identity"] == context["materialized_code_identity"]
    assert report["validation_results"]["runtime"]["status"] == "not_executed"
    if candidate_failure:
        assert report["observations"][0]["observed"]["report_ref"] == verification["changed"]["report_ref"]
    else:
        assert verification["changed"]["build_result"]["claims_real_build_success"] is True
