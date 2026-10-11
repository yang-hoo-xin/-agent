"""Explicit public counterexamples share the compiler without exposing private cases."""
import json
import os
from dataclasses import asdict
from pathlib import Path

import pytest

from src.mod_agent.evaluation import restricted_csharp as runtime
from src.mod_agent.evaluation import restricted_owned_judge as judge
from src.mod_agent.local_entry import LocalOllamaInitialPatchAdapter
from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy
from tests.unit.test_restricted_owned_judge import (
    PRIVATE_VALUE, _controlled_runtime, _fixture, _generic_fixture, _read, _save,
)


def _public_bundle(tmp_path, kwargs, *, expected=7):
    document = {"schema_version": judge.PUBLIC_DEVELOPMENT_SCHEMA,
        "task_id": kwargs["task_id"], "eligibility": judge.PUBLIC_DEVELOPMENT_ELIGIBILITY,
        "cases": [{"case_id": "public-sum", "operation": {"Numbers": [3, 3]},
            "assertions": [{"path": ["sum"], "equals": expected}]}]}
    kwargs["public_case_bundle_ref"] = _save(tmp_path / "public-development/cases.json", document)
    return document


def test_unconfigured_factory_keeps_private_only_contract(tmp_path, monkeypatch):
    kwargs, context, _ = _generic_fixture(tmp_path)
    calls = _controlled_runtime(monkeypatch, observation={"sum": 6})
    evaluator = judge.make_restricted_csharp_evaluator(**kwargs)
    report = evaluator(context)
    assert report["status"] == "passed" and report["observations"] == []
    assert report["verification_summary"] == {"checks": 1, "failed_checks": 0, "executions": 1}
    assert evaluator.check_ids == ("restricted_csharp.00000",)
    assert "public_development_source" not in report and "private_summary" not in report
    assert len(calls["sources"]) == 1 and calls["operations"] == [{"Numbers": [2, 3]}]


@pytest.mark.parametrize("private_pass,public_pass", [(False, False), (False, True), (True, False), (True, True)])
def test_public_feedback_and_private_acceptance_are_independent(tmp_path, monkeypatch, private_pass, public_pass):
    kwargs, context, source = _generic_fixture(tmp_path,
        assertions=[{"path": ["sum"], "equals": 6 if private_pass else PRIVATE_VALUE}])
    cases = _public_bundle(tmp_path, kwargs, expected=6 if public_pass else 7)
    calls = _controlled_runtime(monkeypatch, observation={"sum": 6})
    evaluator = judge.make_restricted_csharp_evaluator(**kwargs)
    report = evaluator(context)
    assert report["status"] == ("passed" if private_pass and public_pass else "behavior_failed")
    assert report["private_summary"] == {"status": "passed" if private_pass else "behavior_failed",
        "checks": 1, "failed_checks": int(not private_pass), "executions": 1}
    assert report["public_development_summary"] == {"status": "passed" if public_pass else "behavior_failed",
        "checks": 1, "failed_checks": int(not public_pass), "executions": 1}
    assert report["verification_summary"] == {"checks": 2,
        "failed_checks": int(not private_pass) + int(not public_pass), "executions": 2}
    assert len(calls["sources"]) == 1 and calls["operations"] == [{"Numbers": [2, 3]}, {"Numbers": [3, 3]}]
    assert all(PRIVATE_VALUE.encode() not in value for value in calls["sources"][0].values())
    assert evaluator.check_ids == ("restricted_csharp.00000", "public_development.00000")
    assert [row["check_id"] for row in _read(report["verification_ref"])["checks"]] == list(evaluator.check_ids)
    model_feedback = LocalOllamaInitialPatchAdapter._model_failure_feedback(report)
    assert PRIVATE_VALUE not in json.dumps(report) + json.dumps(model_feedback)
    assert "synthetic-private-case" not in json.dumps(model_feedback)
    public = [row for row in model_feedback["observations"] if row.get("origin") == "explicit_public_development_case"]
    if public_pass:
        assert public == []
    else:
        assert len(public) == 1 and public[0]["input"] == cases["cases"][0]["operation"]
        assert public[0]["expected"] == cases["cases"][0]["assertions"]
        assert public[0]["observed"] == {"sum": 6}
        assert public[0]["case_bundle_sha256"] == kwargs["public_case_bundle_ref"]["sha256"]
        assert public[0]["materialized_code_identity"] == context["materialized_code_identity"]
    if private_pass and public_pass:
        assert report["observations"] == []
    assert runtime._hash(source.read_bytes()) == next(iter(kwargs["source_files"].values()))


@pytest.mark.parametrize("damage", ["private_reference", "private_schema", "eligibility", "public_bytes", "source", "worker_bytes"])
def test_public_feedback_requires_explicit_bound_public_inputs_before_compile(tmp_path, monkeypatch, damage):
    kwargs, context, source = _generic_fixture(tmp_path)
    document = _public_bundle(tmp_path, kwargs)
    calls = _controlled_runtime(monkeypatch, observation={"sum": 6})
    if damage == "private_reference":
        kwargs["public_case_bundle_ref"] = kwargs["case_bundle_ref"]
    elif damage in {"private_schema", "eligibility"}:
        document["schema_version" if damage == "private_schema" else "eligibility"] = (
            judge.CASE_BUNDLE_SCHEMA if damage == "private_schema" else "independent_private_task")
        kwargs["public_case_bundle_ref"] = _save(tmp_path / "changed-public.json", document)
    if damage in {"private_reference", "private_schema", "eligibility"}:
        with pytest.raises(ValueError):
            judge.make_restricted_csharp_evaluator(**kwargs)
    else:
        evaluator = judge.make_restricted_csharp_evaluator(**kwargs)
        path = source if damage == "source" else Path(kwargs[
            "public_case_bundle_ref" if damage == "public_bytes" else "public_worker_source_ref"]["path"])
        path.write_bytes(path.read_bytes() + b"changed")
        with pytest.raises(ValueError):
            evaluator(context)
    assert calls["sources"] == []


def test_private_runtime_failure_does_not_run_or_disclose_public_cases(tmp_path, monkeypatch):
    kwargs, context, _ = _generic_fixture(tmp_path)
    _public_bundle(tmp_path, kwargs)
    calls = _controlled_runtime(monkeypatch, mode="host_error")
    report = judge.make_restricted_csharp_evaluator(**kwargs)(context)
    assert report["status"] == "infrastructure_failed"
    assert report["public_development_summary"]["status"] == "not_evaluated"
    assert len(calls["operations"]) == 1
    assert "private host path" not in json.dumps(report)


def test_configured_factory_retains_public_values_in_existing_patch_correction(tmp_path, monkeypatch):
    kwargs, context, _ = _generic_fixture(tmp_path, assertions=[{"path": ["sum"], "equals": PRIVATE_VALUE}])
    cases = _public_bundle(tmp_path, kwargs)
    _controlled_runtime(monkeypatch, observation={"sum": 6})
    config = _save(tmp_path / "configured-worker.json", {"schema_version": "patch_worker_configuration_v1",
        "policy": asdict(PatchAgentLoopPolicy()), "enable_recovery_loop": True,
        "behavior_evaluator": {"factory_ref": runtime._ref(Path(judge.__file__)),
            "factory_name": "make_restricted_csharp_evaluator", "kwargs": kwargs}})
    evaluator = PatchWorkerConfiguration.load(config["path"]).behavior_evaluator()
    evaluator.prepare_for_patch_attempt()
    context["verification_identity"] = evaluator.verification_identity()
    report = evaluator(context)
    feedback = LocalOllamaInitialPatchAdapter._model_failure_feedback(report)
    messages = LocalOllamaInitialPatchAdapter._revision_messages(
        "retained candidate JSON", feedback, message_type="patch_behavior_correction")
    corrected = messages[-1].content
    assert corrected["message_type"] == "patch_behavior_correction"
    assert corrected["validator_feedback"] == feedback
    public = corrected["validator_feedback"]["observations"][-1]
    assert public["input"] == cases["cases"][0]["operation"]
    assert public["expected"] == cases["cases"][0]["assertions"]
    assert public["observed"] == {"sum": 6}
    assert PRIVATE_VALUE not in json.dumps(corrected)


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("CODEX_TRANSFER_PUBLIC_DOCKER_TEST") != "1",
    reason="Explicit public Transfer control selection is required.")
@pytest.mark.parametrize("variant,expected", [("observed_wrong", "behavior_failed"), ("reference_control", "passed")])
def test_real_transfer_public_controls(tmp_path, variant, expected):
    fixtures = Path(__file__).parents[1] / "fixtures/transfer_public_development_0928"
    public_document = json.loads((fixtures / "cases.json").read_text(encoding="utf-8"))
    original = (fixtures / "original.cs").read_bytes()
    candidate = (fixtures / f"{variant}.cs").read_text(encoding="utf-8")
    root = Path(os.environ.get("CODEX_TRANSFER_PUBLIC_CONTROL_ROOT", str(tmp_path))) / (
        "w" if variant == "observed_wrong" else "r")
    assert not root.exists()
    # The opaque side is a new inert test fixture, never the original hidden task.
    opaque_smoke = {"schema_version": judge.CASE_BUNDLE_SCHEMA, "task_id": public_document["task_id"],
        "eligibility": "synthetic_harness_control_not_original_private_acceptance",
        "cases": [{"case_id": "synthetic-opaque-smoke", "operation": {"batches": []},
            "assertions": [{"path": [], "equals": []}]}]}
    def replace_bound_method(before):
        prefix, suffix = original.decode("utf-8").split(before)
        assert candidate.startswith(prefix) and candidate.endswith(suffix)
        return candidate[len(prefix):-len(suffix)]

    kwargs, context, source = _fixture(root, source_bytes=original,
        replacement=replace_bound_method, cases=opaque_smoke)
    kwargs.update(case_bundle_ref=kwargs.pop("cases_ref"), task_id=public_document["task_id"],
        public_worker_source_ref=runtime._ref(fixtures / "observation_driver.cs"),
        public_case_bundle_ref=runtime._ref(fixtures / "cases.json"))
    evaluator = judge.make_restricted_csharp_evaluator(**kwargs)
    assert evaluator._materialize(context) == {next(iter(kwargs["source_files"])): candidate.encode("utf-8")}
    context["verification_identity"] = evaluator.verification_identity()
    report = evaluator(context)
    feedback = LocalOllamaInitialPatchAdapter._model_failure_feedback(report)
    _save(root / "control-result.json", {"origin": "public_development_control_no_model",
        "candidate_origin": "retained_td1_model_candidate" if variant == "observed_wrong" else "test_only_reference_control",
        "candidate_ref": runtime._ref(fixtures / f"{variant}.cs"),
        "public_case_bundle_ref": kwargs["public_case_bundle_ref"],
        "public_worker_source_ref": kwargs["public_worker_source_ref"],
        "report_ref": report["report_ref"], "feedback": feedback,
        "status": report["status"], "private_summary": report["private_summary"],
        "public_development_summary": report["public_development_summary"],
        "private_scope": "synthetic_inert_smoke_fixture_only_original_private_cases_not_read",
        "model_calls": 0, "product_model_delivery_claimed": False, "independent_task_success_claimed": False})
    public_runs = [json.loads(path.read_text(encoding="utf-8")) for path in
        Path(kwargs["private_output_root"]).glob("*/public-*/run.json")]
    assert len(public_runs) == 4
    assert all(row["completed"] and row["exit_code"] == 0 and not row["timed_out"] for row in public_runs), public_runs
    assert all(isinstance(json.loads(row["stdout"]), list) for row in public_runs)
    assert report["status"] == expected, report
    assert report["compilation"] == "passed" and source.read_bytes() == original
    assert report["private_summary"] == {"status": "passed", "checks": 1, "failed_checks": 0, "executions": 1}
    assert report["public_development_summary"] == {"status": expected, "checks": 4,
        "failed_checks": 4 if variant == "observed_wrong" else 0, "executions": 4}
    assert len(list(Path(kwargs["private_output_root"]).glob("*/compile/compilation.json"))) == 1
    assert len(feedback["observations"]) == (4 if variant == "observed_wrong" else 0)
    assert "synthetic-opaque-smoke" not in json.dumps(feedback)
