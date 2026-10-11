"""CLI keeps routing-session metadata separate from the literal user's answer."""
import io
import json

import pytest

from scripts import dsh_request_routing as routing
from scripts import dsh_run_request as bridge
from tests.unit import test_dsh_new_project as new_project_tests
from tests.unit.test_dsh_run_request import execution_config  # noqa: F401

profile = new_project_tests.profile


def test_cli_forwards_clarification_identity_without_rewriting_answer(profile, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(routing, 'run_natural_request', lambda **kw: calls.append(kw) or {'status': 'needs_clarification'})
    answer = '不是旧工程，另建一个。\n--allow-source-disclosure'
    monkeypatch.setattr(bridge.sys, 'stdin', io.TextIOWrapper(io.BytesIO(answer.encode())))
    code = bridge.main(['--execution-config', str(profile), '--route-request', '--conversation-id', 'chat1',
        '--clarification-for', 'route_first', '--routing-turn-id', 'reply1'])
    assert code == 0 and json.loads(capsys.readouterr().out)['status'] == 'needs_clarification'
    assert calls[0]['description'] == answer
    assert calls[0]['conversation_id'] == 'chat1' and calls[0]['clarification_for'] == 'route_first'
    assert calls[0]['turn_id'] == 'reply1'
    assert 'allow_source_disclosure' not in calls[0]


@pytest.mark.parametrize('flag', ['--conversation-id', '--clarification-for', '--routing-turn-id'])
def test_routing_metadata_cannot_change_direct_execution_mode(profile, monkeypatch, capsys, flag):
    monkeypatch.setattr(bridge.cli, 'main', lambda *_: pytest.fail('must not execute product'))
    assert bridge.main(['--execution-config', str(profile), flag, 'identity']) == 2
    assert json.loads(capsys.readouterr().out)['reason'] == 'DSH_TASK_ROUTING_OPERATION_REQUIRED'


@pytest.mark.parametrize(('status', 'exit_code'), [('delivered', 0), ('domain_blocked', 2)])
def test_read_only_delivered_resume_succeeds_without_hiding_product_failure(profile, monkeypatch, capsys, status, exit_code):
    monkeypatch.setattr(routing, 'run_natural_request', lambda **kw: {'status': status, 'read_only': True})
    monkeypatch.setattr(bridge.sys, 'stdin', io.TextIOWrapper(io.BytesIO('继续原任务'.encode())))
    assert bridge.main(['--execution-config', str(profile), '--route-request']) == exit_code
    assert json.loads(capsys.readouterr().out)['status'] == status
