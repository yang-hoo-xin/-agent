"""Public numeric/state/callback contract and shared compiled-probe binding."""
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.mod_agent.domain import spread_api_evaluator as module
from src.mod_agent.domain.compilation_feedback import CompilationFeedback
from src.mod_agent.domain.full_project_compilation import _ref, _save
from src.mod_agent.model_qualification import read_bound_json
from tests.unit.test_full_project_compilation import _checker


def contract():
    return json.loads((Path(__file__).parents[1] / 'fixtures/evaluation/spread_api_input_atomicity.json').read_bytes())


def observed(case):
    return {"status": "observed", "assembly_sha256": "a"*64, "protocol": "spread-api-probe.v1",
        "mode": "real_harmony_callback_prefix", "runtime_version": "6.0.36", "initial_value": "1",
        "callback_calibration_count": 1,
        "callback_method": "AccurateCrosshair.CrosshairPatches.SpreadPatches.UpdateCrosshairSize",
        "callback_body_skipped": True, "api_methods_instrumented": False,
        "observations": [{**wanted, "operation": action["operation"], "key": action["key"], "argument": action.get("value")}
            for action,wanted in zip(case[1]["actions"],case[1]["expected"])]}


@pytest.mark.parametrize("damage", [None, "accept_invalid", "dictionary_poisoned", "extra_callback", "zero_rejected", "instrumented_api"])
def test_rejection_atomicity_and_normal_behavior(damage):
    evaluator = module.SpreadApiEvaluator.__new__(module.SpreadApiEvaluator)
    evaluator.contract = contract()
    cases = evaluator.case_definitions()
    selected = cases[0] if damage == "zero_rejected" else cases[1]
    value = observed(selected)
    if damage == "accept_invalid":
        value["observations"][1]["exception_type"] = None
    elif damage == "dictionary_poisoned":
        value["observations"][2]["value"] = "-3"
    elif damage == "extra_callback":
        value["observations"][1]["callback_delta"] = 1
    elif damage == "zero_rejected":
        value["observations"][5]["exception_type"] = "System.ArgumentOutOfRangeException"
    elif damage == "instrumented_api":
        value["api_methods_instrumented"] = True
    verdict = evaluator.assess(value, selected, "a"*64)
    assert all(verdict.values()) is (damage is None)


@pytest.mark.parametrize("failure_phase", [None, "api_contract", "callback_instrumentation"])
def test_shared_worker_report_checks_complete_compiled_candidate(tmp_path, monkeypatch, failure_phase):
    from src.mod_agent.domain import compiled_probe_evaluator as common
    _, context, checker, builds, _ = _checker(tmp_path, monkeypatch)
    probe = tmp_path / "probe"
    probe.mkdir()
    for name in ('spread_api_probe.dll','spread_api_probe.deps.json','spread_api_probe.runtimeconfig.json','dotnet.exe'):
        (probe/name).write_bytes(b'synthetic '+name.encode())
    cfg = _save(tmp_path/'probe.json',{'assembly_path':str(probe/'spread_api_probe.dll'),
        'files':[_ref(path) for path in probe.iterdir()], 'dotnet':_ref(probe/'dotnet.exe')})
    cases = _save(tmp_path/'cases.json',contract())
    evaluator = module.SpreadApiEvaluator(compilation=CompilationFeedback(checker,tmp_path/'feedback'),
        output_root=tmp_path/'behavior',probe_configuration_ref=cfg,case_configuration_ref=cases)
    calls=[]
    def run(command, **kwargs):
        req=read_bound_json(_ref(command[-1]));calls.append(req)
        if failure_phase:
            return SimpleNamespace(returncode=2, stdout=json.dumps({"status": "execution_failed",
                "execution_phase": failure_phase, "error_type": "System.MissingMethodException"}), stderr='')
        case=next(row for row in evaluator.cases if row[0]==Path(command[-1]).parent.name)
        output=observed(case);output['assembly_sha256']=req['assembly']['sha256']
        output['loaded_dependencies']=[{**ref,'name':Path(ref['path']).stem} for ref in req['dependencies']]
        return SimpleNamespace(returncode=0,stdout=json.dumps(output),stderr='')
    monkeypatch.setattr(common.subprocess,'run',run)
    report=evaluator(context)
    if failure_phase:
        # 为什么要有它：公开契约破坏必须交还模型修订，而探针绑定故障不能错误归责候选实现。
        assert report['status'] == ('behavior_failed' if failure_phase == 'api_contract' else 'infrastructure_failed')
        assert report['failure_owner'] == ('patch_implementation' if failure_phase == 'api_contract' else 'validator')
        assert len(calls) == 1 and report['verification_summary']['failed_checks'] == 1
        return
    assert report['status']=='passed' and len(calls)==9 and len(builds)==2
    assert report['verification_summary']=={'checks':87,'failed_checks':0,'executions':9}
    from src.mod_agent.execution.task_delegation import _verification
    detail=read_bound_json(report['verification_ref'])
    _verification(report['report_ref'],[row['check_id'] for row in detail['checks']],
        request=SimpleNamespace(isolated_workspace_root=str(tmp_path)),plan_ref=context['implementation_plan_ref'],
        code_identity=context['materialized_code_identity'],
        proposal={'diff_intent':[{'generation':{'model_response_sha256':report['model_response_sha256']}}]})
    Path(cases['path']).write_text('{}')
    with pytest.raises(ValueError):
        evaluator.verification_identity()


def test_feedback_projects_only_failed_step_without_losing_original_observations():
    evaluator=module.SpreadApiEvaluator.__new__(module.SpreadApiEvaluator)
    evaluator.contract=contract();case=evaluator.case_definitions()[1];value=observed(case);before=deepcopy(value)
    projected=evaluator.check_observation(value,case[1]['expected'][1]['id'])
    assert projected==case[1]['expected'][1] and value==before
    assert 'assembly_sha256' not in projected
