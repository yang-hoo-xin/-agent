"""Offline normal-entry counterexamples: incomplete Findings do not preclude a bounded repair."""
import json
from pathlib import Path

import httpx
import pytest

from src.mod_agent import local_entry
from tests.unit.test_dsh_run_request import _arguments, _call, _install_execution_boundaries
from tests.unit.test_dsh_run_request import execution_config as execution_config  # noqa: F401
from tests.unit.test_patch_worker_configuration import _write_configuration


@pytest.mark.parametrize("configured", [False, True])
def test_normal_entry_attempts_source_bound_repair_without_relabeling_findings(
    execution_config, monkeypatch, capsys, configured,
):
    target, roles, builds = _install_execution_boundaries(execution_config.parent, monkeypatch)
    source = target / "Plugin.cs"
    source.write_text("namespace Example; public sealed class Plugin { MissingType field; public void Load() {} }\n",
                      encoding="utf-8")
    original = source.read_bytes()
    if configured:
        factory = '''
import hashlib
import json
from pathlib import Path
def make_evaluator(*, output):
    def evaluate(context):
        passed = all("MissingType" not in row["patch"]["after_text"] for row in context["generated_changes"])
        report = {"status": "passed" if passed else "behavior_failed",
            "failure_owner": None if passed else "patch_implementation",
            "owner_binding_ids": [] if passed else [row["edit_binding_id"] for row in context["generated_changes"]],
            "observations": [{"check_id": "synthetic_compile_control", "passed": passed}],
            "generated_changes_sha256": context["generated_changes_sha256"],
            "source_snapshot_sha256": context["source_snapshot_sha256"], "execution_origin": "executed"}
        raw = json.dumps(report).encode(); path = Path(output); path.write_bytes(raw)
        return {**report, "report_ref": {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}}
    return evaluate
'''
        config, _, document = _write_configuration(execution_config.parent, factory,
            kwargs={"output": str(execution_config.parent / "synthetic-check.json")})
        document["policy"] = {"require_source_inspection": False, "finalize_after_first_observation": False,
                              "enable_supporting_reads": True, "allow_upstream_request": True}
        config.write_text(json.dumps(document), encoding="utf-8")
        _arguments(execution_config, lambda values: [*values, "--patch-worker-config", str(config)])
    transport = httpx.HTTPTransport.handle_request
    captured = []
    current_fact_needed = "The source or API declaration that owns MissingType."
    planning_impact = "Its contract is needed to decide how the missing field type should be repaired."
    expected_gap = f"Current fact needed: {current_fact_needed}; Blocks planning: {planning_impact}"

    def controlled_transport(self, request):
        if request.method != "POST":
            return transport(self, request)
        body = json.loads(request.content)
        context = json.loads(next(row["content"] for row in body["messages"] if row["role"] == "user"))
        if "patch_agent_context_encoding" in context:
            context = local_entry._restore_patch_agent_context(context)
        captured.append(context)
        if context.get("message_type") == "initial_findings_evidence_queries":
            roles.append("initial_findings_queries")
            output = {"queries": [{"query": "Load", "metadata_queries": [],
                "gap_ids": [context["gap_investigation_targets"][0]["gap_id"]],
                "requirement_id": context["requirements"][0]["requirement_id"],
                "current_fact_needed": "Current source ownership", "modification_impact": "Locate repair source",
                "authorized_source": "target_source"}]}
            return httpx.Response(200, request=request, json={"model": body["model"],
                "message": {"role": "assistant", "content": json.dumps(output)}, "done": True,
                "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 20})
        response = transport(self, request)
        outer = response.json()
        output = json.loads(outer["message"]["content"])
        if "findings" in output:
            assert context["native_findings_contract"] == "planning_readiness_v1"
            for row in output["findings"]:
                row["planning_readiness"] = "needs_current_evidence"
                row["edit_target_evidence_ids"] = []
                row["current_basis"] = "The current source uses MissingType but does not declare its contract."
                row["blocking_current_facts"] = [{
                    "fact_needed": current_fact_needed,
                    "planning_impact": planning_impact,
                }]
        elif "allowed_edit_evidence_ids" in context and configured:
            output.pop("missing_evidence", None)
            output["verification_questions"] = ["Verify the repaired candidate actually compiles."]
        elif "changes" in output:
            for row in output["changes"]:
                row["after_text"] = row["after_text"].replace("MissingType field; ", "")
        outer["message"]["content"] = json.dumps(output)
        return httpx.Response(200, request=request, json=outer)

    def failed_baseline(profile):
        builds.append(profile)
        return local_entry.NuGetIsolatedBuildExecution(restore_exit_code=0, build_exit_code=1,
            restore_stdout="restored", restore_stderr="", build_stderr="", duration_ms=1,
            build_stdout=f"{profile.working_directory / 'Plugin.cs'}(1,49): error CS0246: MissingType is undefined")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", controlled_transport)
    monkeypatch.setattr(local_entry, "_run_nuget_isolated_build", failed_baseline)
    code = _call(execution_config, "修复这个 Mod 的 Load 编译错误，保留已有行为。", monkeypatch)
    result = json.loads(capsys.readouterr().out)
    assert "run_root" in result, result
    root = Path(result["run_root"])
    evidence = json.loads(Path(result["artifacts"]["evidence_pack"]).read_bytes())
    assert evidence["status"] == "blocked"
    assert evidence["data"]["can_generate_patch"] is False
    finding = evidence["data"]["requirement_coverage"]["findings"][0]
    assert finding["relationship"] == "missing"
    assert finding["unresolved_gaps"] == [expected_gap]
    assert source.read_bytes() == original and result["actual_write_performed"] is False
    assert len(builds) == 1
    if configured:
        assert code == 0 and result["status"] == "awaiting_approval", result
        assert roles == ["product_requirement_projection", "product_requirement_findings", "planning", "patch"]
        scope = evidence["data"]["budget_summary"]["compilation_repair_candidate"]
        assert scope["semantic_coverage_established"] is False
        plan = json.loads(Path(result["artifacts"]["implementation_plan"]).read_bytes())["data"]
        assert {row["evidence_id"] for row in plan["binding_registry"]["edit_bindings"]} <= set(scope["evidence_ids"])
        assert expected_gap in plan["verification_questions"]
        assert json.loads((execution_config.parent / "synthetic-check.json").read_bytes())["status"] == "passed"
        assert root.is_dir()
    else:
        assert code == 1 and "patch" not in roles
        assert "compilation_repair_candidate" not in evidence["data"]["budget_summary"]
