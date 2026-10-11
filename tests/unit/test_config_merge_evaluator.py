"""Oracle counterexamples distinguish recursive merge and real disk rejection semantics."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.mod_agent.domain.config_merge_evaluator import ConfigMergeEvaluator, _action_passed


def state(text):
    return {'exists': text is not None, 'text': text,
        'sha256': hashlib.sha256(text.encode()).hexdigest() if text is not None else None}


def setup(name):
    evaluator = ConfigMergeEvaluator.__new__(ConfigMergeEvaluator)
    evaluator.contract = json.loads((Path(__file__).parents[1] / 'fixtures/evaluation/config_merge_cases.json').read_bytes())
    case = next(case for case in evaluator.case_definitions() if case[0] == name)
    before = state(case[1]['seed_file'])
    observations = []
    for index, action in enumerate(case[1]['actions']):
        expected = action['expected']
        after = state(json.dumps(expected['file_json'])) if 'file_json' in expected else state(None) if expected.get('file_missing') else deepcopy(before)
        row = {'id': action['id'], 'args': action['args'], 'process_id': 100 + index,
            'before_file': before, 'after_file': after}
        if case[1].get('mode', 'cli') == 'cli':
            row.update(exit_code=expected['exit_code'], stdout=json.dumps(expected['stdout_json']), stderr='')
        else:
            row.update(exception_type=expected['exception_types'][0], exception_base_types=[])
        observations.append(row); before = after
    return evaluator, case, {'status': 'observed', 'protocol': 'config-cli-probe.v1', 'mode': case[1].get('mode', 'cli'),
        'assembly_sha256': 'a' * 64, 'runtime_version': '7.0.11', 'api_methods_instrumented': False,
        'api_contract_present': True, 'observations': observations}


@pytest.mark.parametrize('damage', [None, 'shallow_replace', 'null_retained', 'bad_stdout', 'same_process', 'changed_seed', 'missing_disk_state'])
def test_recursive_merge_retention_reopen_and_execution_identity(damage):
    evaluator, case, observed = setup('recursive-delete-retain')
    row = observed['observations'][0]
    if damage == 'shallow_replace':
        file = json.loads(row['after_file']['text']); del file['ui']['theme']['keep']; row['after_file'] = state(json.dumps(file))
    elif damage == 'null_retained':
        file = json.loads(row['after_file']['text']); file['remove'] = None; row['after_file'] = state(json.dumps(file))
    elif damage == 'bad_stdout':
        row['stdout'] += '\n{"extra":true}'
    elif damage == 'same_process':
        observed['observations'][1]['process_id'] = row['process_id']
    elif damage == 'changed_seed':
        row['before_file'] = state('{}')
    elif damage == 'missing_disk_state':
        del row['before_file']
    assert all(evaluator.assess(observed, case, 'a' * 64).values()) is (damage is None)


def test_rejection_compares_bytes_not_equivalent_parsed_json():
    before = state('{ "unchanged" : 1 }\r\n')
    expected = {'exit_code': 2, 'stdout_json': {'status': 'rejected', 'key': None}, 'file_unchanged': True}
    observed = {'exit_code': 2, 'stdout': '{"status":"rejected","key":null}',
        'before_file': before, 'after_file': state('{"unchanged":1}')}
    assert not _action_passed(observed, expected, 'cli')
    observed['after_file'] = deepcopy(before)
    assert _action_passed(observed, expected, 'cli')


@pytest.mark.parametrize('exception', ['System.InvalidOperationException', None])
def test_public_api_cannot_accept_invalid_root_or_throw_unrelated_exception(exception):
    expected = {'exception_types': ['System.ArgumentException', 'System.Text.Json.JsonException'], 'file_missing': True}
    observed = {'exception_type': exception, 'exception_base_types': [], 'before_file': state(None), 'after_file': state(None)}
    assert not _action_passed(observed, expected, 'api_merge')
    observed.update(exception_type='System.ArgumentOutOfRangeException', exception_base_types=['System.ArgumentException'])
    assert _action_passed(observed, expected, 'api_merge')


def test_boolean_cannot_masquerade_as_json_number():
    expected = {'exit_code': 0, 'stdout_json': {'x': 1}, 'file_json': {'x': 1}}
    observed = {'exit_code': 0, 'stdout': '{"x":true}', 'before_file': state('{}'), 'after_file': state('{"x":true}')}
    assert not _action_passed(observed, expected, 'cli')
