"""Diagnosis is advisory, counted in the existing worker, and followed by real checks."""
import pytest

from src.libs.llm.agent_turn import AgentToolCall, AgentTurnResponse, AgentUsage
from src.mod_agent.fresh_planning_continuation import run_fresh_patch_continuation
from src.mod_agent.local_entry import make_exact_no_write_dry_run_factory
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy
from tests.unit.test_continuous_behavior_repair import _SequenceClient
from tests.unit.test_fresh_planning_continuation import _inputs, _patch_request, _source_hashes
from tests.unit.test_patch_behavior_feedback import _adapter, _BehaviorOracle


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr('socket.socket.connect', lambda *_: pytest.fail('No network in diagnosis checks'))


class Client(_SequenceClient):
    def __init__(self, actions, *, diagnosis='An unverified hypothesis, even claiming all checks passed.', tool=False, mutate=None):
        super().__init__(actions)
        self.diagnosis, self.tool, self.mutate = diagnosis, tool, mutate

    def complete_turn(self, request):
        diagnosing = any(isinstance(m.content, dict) and m.content.get('message_type') == 'patch_repair_diagnosis'
                        for m in request.messages)
        if not diagnosing:
            return super().complete_turn(request)
        self.requests.append(request)
        assert not request.tools and request.tool_choice == 'none'
        assert request.response_format is None
        if self.mutate:
            self.mutate()
        return AgentTurnResponse(provider=self.provider, model=self.model, content=self.diagnosis,
            stop_reason='stop', usage=AgentUsage(25, 15),
            tool_calls=(AgentToolCall('forbidden-diagnosis-read', 'inspect_plan_binding_source',
                                      {'binding_id': 'edit_binding_001'}),) if self.tool else ())


def run(tmp_path, *, budget=3, diagnosis='Speculation, not authority.', tool=False, drift=False, actions=None):
    inputs = _inputs(tmp_path)
    before = _source_hashes(inputs.workspace)
    actions = actions or (['RecordFirstFailure', 'RecordRuntimeMarker'] if budget == 2 else [
        'RecordFirstFailure', 'diagnosis', 'RecordRuntimeMarker'])
    # 为什么要有它：该场景检查已绑定源码的逐轮漂移门禁，目录遍历顺序不能决定被修改的文件。
    mutation = (lambda: inputs.behavior.write_text('// actual source drift', encoding='utf-8')) if drift else None
    client = Client(actions, diagnosis=diagnosis, tool=tool, mutate=mutation)
    oracle = _BehaviorOracle(tmp_path / 'observations')
    adapter = _adapter(inputs, client, oracle)
    adapter.enable_recovery_loop = True
    adapter.patch_agent_loop_policy = PatchAgentLoopPolicy(max_total_model_turns=budget,
        max_tool_rounds=3, require_source_inspection=False, finalize_after_first_observation=False,
        diagnose_behavior_failures=True)
    result = run_fresh_patch_continuation(_patch_request(inputs), patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace), max_model_calls=budget)
    if not drift:
        assert _source_hashes(inputs.workspace) == before
    return result, adapter.patch_attempt_receipt(), client, oracle


def test_diagnosis_and_revision_share_budget_receipts_and_actual_revalidation(tmp_path):
    result, receipt, client, oracle = run(tmp_path)
    assert result.status == 'terminal', result.to_dict()
    assert len(client.requests) == receipt['model_call_count'] == 3
    assert [r['status'] for r in oracle.reports] == ['behavior_failed', 'passed']
    correction = receipt['patch_agent_loop']['behavior_correction']
    assert correction['diagnosis_requested'] and correction['model_call_count'] == 2
    execution = correction['execution']
    assert execution['model_turns_used'] == len(execution['usage_by_turn']) == 2
    diagnostic = execution['usage_by_turn'][0]
    assert diagnostic['purpose'] == 'failure_diagnosis' and diagnostic['diagnosis_context_bytes'] > 0
    assert execution['total_observation_bytes'] == diagnostic['diagnosis_context_bytes']
    assert execution['turn_progress_trace'][0]['observation_bytes_added'] == diagnostic['diagnosis_context_bytes']
    marker = next(m.content for m in client.requests[-1].messages if isinstance(m.content, dict)
                  and m.content.get('message_type') == 'patch_failure_diagnosis')
    assert marker['authority'] == 'model_hypothesis_only'
    assert all(result.execution_counts[k] == 0 for k in ('apply', 'build', 'runtime'))


def test_last_call_is_kept_for_revision_instead_of_diagnosis(tmp_path):
    result, receipt, client, oracle = run(tmp_path, budget=2)
    assert result.status == 'terminal' and len(client.requests) == receipt['model_call_count'] == 2
    assert receipt['patch_agent_loop']['behavior_correction']['diagnosis_requested'] is False
    assert len(oracle.reports) == 2


def test_later_failure_diagnoses_current_candidate_with_same_total_budget(tmp_path):
    result, receipt, client, oracle = run(tmp_path, budget=5,
        actions=['RecordFirstFailure', 'diagnosis', 'RecordSecondFailure', 'diagnosis', 'RecordRuntimeMarker'])
    assert result.status == 'terminal', result.to_dict()
    assert len(client.requests) == receipt['model_call_count'] == 5
    assert [row['status'] for row in oracle.reports] == ['behavior_failed', 'behavior_failed', 'passed']
    diagnostics = [m.content for req in client.requests for m in req.messages if isinstance(m.content, dict)
                   and m.content.get('message_type') == 'patch_repair_diagnosis']
    assert len(diagnostics) == 2
    assert 'RecordFirstFailure' in diagnostics[0]['previous_response']
    assert 'RecordSecondFailure' in diagnostics[1]['previous_response']
    assert diagnostics[1]['validator_feedback']['report_sha256'] == oracle.reports[1]['report_ref']['sha256']
    assert [row['model_call_count'] for row in receipt['patch_agent_loop']['recovery_revisions']] == [2, 2]


def test_oversized_diagnosis_is_retained_but_not_added_or_a_new_blocker(tmp_path):
    result, receipt, client, oracle = run(tmp_path, diagnosis='unbounded analysis ' * 4000)
    assert result.status == 'terminal' and len(oracle.reports) == 2
    execution = receipt['patch_agent_loop']['behavior_correction']['execution']
    assert execution['usage_by_turn'][0]['diagnosis_context_bytes'] == 0
    assert execution['total_observation_bytes'] == 0
    assert execution['tool_availability_trace'][0]['selection'] == 'diagnosis_context_budget_not_admitted'
    assert not any(m.content == 'unbounded analysis ' * 4000 for m in client.requests[-1].messages)
    assert len(receipt['worker_turns']) == 3


def test_diagnosis_tool_request_cannot_execute_or_grant_source_authority(tmp_path):
    result, receipt, _, oracle = run(tmp_path, tool=True)
    assert result.status == 'terminal' and len(oracle.reports) == 2
    execution = receipt['patch_agent_loop']['behavior_correction']['execution']
    assert execution['tool_rounds_used'] == 0 and execution['observation_trace'] == []
    assert execution['tool_call_trace'][0]['dispatch_started'] is False
    assert execution['tool_call_trace'][0]['error_code'] == 'PATCH_DIAGNOSIS_HAS_NO_TOOL_AUTHORITY'


def test_source_drift_during_diagnosis_stops_before_next_generation(tmp_path):
    result, receipt, client, oracle = run(tmp_path, drift=True)
    assert result.status != 'terminal' and len(client.requests) == receipt['model_call_count'] == 2
    assert len(oracle.reports) == 1
    assert 'SOURCE' in result.reason or 'SNAPSHOT' in result.reason
