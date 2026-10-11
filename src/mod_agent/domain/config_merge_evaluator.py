"""Recursive configuration merge checks over the compiled CLI and public store API."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from src.mod_agent.domain.compiled_probe_evaluator import CompiledProbeEvaluator
from src.mod_agent.domain.compilation_feedback import make_compilation_feedback
from src.mod_agent.domain.full_project_compilation import _ref
from src.mod_agent.model_qualification import read_bound_json


def _parse(text):
    def reject(value):
        raise ValueError(value)
    return json.loads(text, parse_constant=reject)


def _equal(left, right):
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_equal(a, b) for a, b in zip(left, right))
    return left == right


def _action_passed(observed, expected, mode):
    before, after = observed.get('before_file', {}), observed.get('after_file', {})
    for state in (before, after):
        if type(state.get('exists')) is not bool:
            return False
        if state['exists']:
            if (not isinstance(state.get('text'), str) or not isinstance(state.get('sha256'), str)
                    or len(state['sha256']) != 64 or any(c not in '0123456789abcdef' for c in state['sha256'])):
                return False
        elif state.get('sha256') is not None or state.get('text') is not None:
            return False
    if mode == 'api_merge':
        exception = observed.get('exception_type')
        allowed = expected['exception_types']
        if not (exception in allowed or exception is not None
                and set(observed.get('exception_base_types', [])) & set(allowed)):
            return False
    else:
        if observed.get('exit_code') != expected['exit_code']:
            return False
        try:
            if not _equal(_parse(observed.get('stdout', '')), expected['stdout_json']):
                return False
        except (ValueError, TypeError):
            return False
    if expected.get('file_missing'):
        return after.get('exists') is False
    if expected.get('file_unchanged'):
        return before.get('exists') is after.get('exists') and before.get('sha256') == after.get('sha256')
    try:
        return after.get('exists') is True and _equal(_parse(after['text']), expected['file_json'])
    except (ValueError, KeyError, TypeError):
        return False


class ConfigMergeEvaluator(CompiledProbeEvaluator):
    error_prefix = 'CONFIG_MERGE'
    probe_filename = 'config_cli_probe.dll'
    scope = 'complete_BCL_project_compilation_fresh_CLI_processes_and_public_Merge_calls_real_sandbox_disk'
    trace_name = 'validate.config_merge'
    patch_failure_phases = {'api_contract', 'api_sequence', 'cli_sequence'}
    protocol_sources = (__file__,)

    def __init__(self, *, compilation, output_root, probe_configuration_ref, case_configuration_ref):
        self.case_configuration_ref = deepcopy(case_configuration_ref)
        self.contract = read_bound_json(case_configuration_ref)
        cases = self.contract.get('cases')
        # 为什么要有它：冻结验收同时覆盖合并与保留行为，重复或缺失的动作不能冒充同一份合同。
        if (self.contract.get('schema') != 'config-merge-cases.v1' or not isinstance(cases, list) or not cases
                or len({case['name'] for case in cases}) != len(cases)
                or any(not case['actions'] or len({row['id'] for row in case['actions']}) != len(case['actions'])
                       for case in cases)):
            raise ValueError('CONFIG_MERGE_CASES_INVALID')
        self.protocol_parameters = {'case_configuration_ref': self.case_configuration_ref}
        super().__init__(compilation=compilation, output_root=output_root, probe_configuration_ref=probe_configuration_ref)

    def verification_identity(self):
        if read_bound_json(self.case_configuration_ref) != self.contract:
            raise ValueError('CONFIG_MERGE_CASES_CHANGED')
        return super().verification_identity()

    def assembly_file_refs(self, assembly):
        path = Path(assembly['path'])
        # 为什么要有它：真实CLI由dotnet读取runtimeconfig和deps，正式DLL与这两个启动文件须共同绑定。
        return [assembly, _ref(path.with_suffix('.deps.json')), _ref(path.with_suffix('.runtimeconfig.json'))]

    def case_definitions(self):
        return tuple((row['name'], deepcopy(row)) for row in self.contract['cases'])

    def request_fields(self, case):
        return {'mode': case[1].get('mode', 'cli'), 'seed_file': case[1]['seed_file'],
            'actions': [{key: deepcopy(row[key]) for key in ('id', 'args')} for row in case[1]['actions']],
            'dotnet_ref': self.configuration['dotnet']}

    def expected(self, case):
        result = {'execution_binding': 'actual bound full DLL, no API instrumentation, .NET 7',
            'sequence_identity': 'exact actions, each fresh CLI process or one isolated API probe process',
            **{row['id']: deepcopy(row['expected']) for row in case[1]['actions']}}
        if case[0] == self.contract['cases'][0]['name']:
            result['public_api_contract'] = 'public instance void JsonConfigStore.Merge(JsonElement)'
        return result

    def assess(self, observed, case, assembly_sha256):
        actions, rows = case[1]['actions'], observed.get('observations', [])
        mode = case[1].get('mode', 'cli')
        identity = len(rows) == len(actions) and all(
            row.get('id') == action['id'] and row.get('args') == action['args']
            for row, action in zip(rows, actions))
        pids = [row.get('process_id') for row in rows]
        identity = identity and all(type(pid) is int and pid > 0 for pid in pids)
        if mode == 'cli':
            identity = identity and len(set(pids)) == len(pids)
        # 为什么要有它：每次写入与拒绝必须相对于真实种子和前一动作的磁盘状态判定，不能接受丢失前像的空回执。
        seed = case[1]['seed_file']
        initial = {'exists': seed is not None, 'text': seed,
            'sha256': hashlib.sha256(seed.encode('utf-8')).hexdigest() if seed is not None else None}
        identity = identity and all(row.get('before_file') == (initial if index == 0 else rows[index - 1].get('after_file'))
                                    for index, row in enumerate(rows))
        results = {'execution_binding': observed.get('status') == 'observed'
            and observed.get('protocol') == 'config-cli-probe.v1'
            and observed.get('assembly_sha256') == assembly_sha256
            and observed.get('api_methods_instrumented') is False
            and observed.get('mode') == mode and str(observed.get('runtime_version')).startswith('7.'),
            'sequence_identity': identity}
        if case[0] == self.contract['cases'][0]['name']:
            results['public_api_contract'] = observed.get('api_contract_present') is True
        for index, action in enumerate(actions):
            results[action['id']] = bool(identity and _action_passed(rows[index], action['expected'], mode))
        return results

    def check_expectation(self, expected, key):
        return expected[key]

    def check_observation(self, observed, key):
        if key == 'public_api_contract':
            return observed.get('api_contract_present')
        rows = [row for row in observed.get('observations', []) if row.get('id') == key]
        if len(rows) == 1:
            return {name: deepcopy(rows[0].get(name)) for name in
                ('args', 'exit_code', 'stdout', 'stderr', 'exception_type', 'exception_base_types', 'before_file', 'after_file')}
        return {name: deepcopy(observed.get(name)) for name in
            ('status', 'protocol', 'mode', 'assembly_sha256', 'runtime_version', 'api_methods_instrumented')}

    def stable_observation(self, observed):
        if isinstance(observed, dict):
            return {key: deepcopy(value) for key, value in observed.items()
                    if key not in {'assembly_sha256', 'process_id'}}
        return observed


def make_config_merge_evaluator(*, compilation_kwargs, output_root, probe_configuration_ref, case_configuration_ref):
    parameters = deepcopy(compilation_kwargs)
    scope = uuid4().hex[:8]
    parameters['output_root'] = str(Path(parameters['output_root']) / scope)
    compilation = make_compilation_feedback(compilation_kwargs=parameters,
        output_root=str(Path(output_root) / scope / 'compile-feedback'))
    return ConfigMergeEvaluator(compilation=compilation, output_root=Path(output_root) / scope / 'behavior',
        probe_configuration_ref=probe_configuration_ref, case_configuration_ref=case_configuration_ref)
