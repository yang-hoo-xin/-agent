"""Run one preregistered online strategy trial through routing, product and delivery."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_benchmark_arm import execute, read, ref, save, source_snapshot


def checked_trial(protocol_ref, trial_id, *, allow_runtime=False):
    protocol = read(protocol_ref)
    rows = protocol['trials']
    identities = {(row['task_id'], row['arm'], row['repeat']) for row in rows}
    expected = {(task, arm, repeat) for task in protocol['task_ids']
                for arm in ('baseline', 'candidate') for repeat in (1, 2)}
    if (protocol.get('status') != 'frozen_not_executed' or len(rows) != 20
            or len(protocol['task_ids']) != 5 or identities != expected
            or len({row['trial_id'] for row in rows}) != 20
            or protocol['wall_seconds'] != 900):
        raise ValueError('ONLINE_AB_PREREGISTRATION_INVALID')
    selected = [row for row in rows if row['trial_id'] == trial_id]
    if len(selected) != 1:
        raise ValueError('ONLINE_AB_REGISTERED_TRIAL_REQUIRED')
    trial = read(selected[0]['trial_ref'])
    for key in ('trial_id', 'task_id', 'arm', 'repeat'):
        if trial[key] != selected[0][key]:
            raise ValueError('ONLINE_AB_TRIAL_IDENTITY_CHANGED')
    if type(trial.get('runtime_required')) is not bool:
        raise ValueError('ONLINE_AB_RUNTIME_SCOPE_REQUIRED')
    if trial['runtime_required'] and not allow_runtime:
        raise ValueError('ONLINE_AB_RUNTIME_NOT_STARTED_OPERATOR_UNAVAILABLE')
    for item in trial['input_refs']:
        if ref(item['path']) != item:
            raise ValueError('ONLINE_AB_INPUT_CHANGED')
    ready = read(trial['ready_ref'])
    if ready['platform_snapshot_ref'] != protocol['platform_snapshot_ref']:
        raise ValueError('ONLINE_AB_CORE_CHANGED')
    from src.mod_agent.platform_execution_snapshot import FrozenExecution
    FrozenExecution(protocol['platform_snapshot_ref']).verify_files()
    args = read(ready['profile_ref'])['arguments']
    enabled = trial['arm'] == 'candidate'
    for name in ('reuse-query-observations', 'compress-findings-input'):
        wanted = '--' + ('' if enabled else 'no-') + name
        opposite = '--' + ('no-' if enabled else '') + name
        if args.count(wanted) != 1 or opposite in args:
            raise ValueError('ONLINE_AB_STRATEGY_SWITCH_CHANGED')
    workspace, source, output = (Path(trial[key]).resolve() for key in ('workspace', 'source_audit_root', 'output_root'))
    if (not source.is_relative_to(workspace) or output.is_relative_to(workspace)
            or workspace.is_relative_to(output) or output.exists()):
        raise ValueError('ONLINE_AB_WORKSPACE_OR_OUTPUT_INVALID')
    return protocol, selected[0], trial, ready


def product_references(ready):
    records = Path(ready['records_root'])
    result = {}
    natural = records / 'natural-result.json'
    if natural.is_file():
        result['routing_result_ref'] = ref(natural)
    dispatch = records / 'dispatch.json'
    if dispatch.is_file():
        value = read(ref(dispatch))
        root = Path(value['run_root'])
        manifest, terminal = root / 'run_manifest.json', root / 'run_result.json'
        result['dispatch_ref'] = ref(dispatch)
        if manifest.is_file() and terminal.is_file():
            run = read(ref(terminal))
            result['product_run'] = {'allowed_root': str(root.parent), 'run_root': str(root),
                'run_id': run.get('run_id', root.name), 'manifest_ref': ref(manifest), 'result_ref': ref(terminal)}
    return result


def run(protocol_ref, trial_id, *, allow_runtime=False):
    protocol, registered, trial, ready = checked_trial(protocol_ref, trial_id, allow_runtime=allow_runtime)
    # 为什么要有它：原顺序以每次终态记录推进，不跳过失败或重复执行同一预登记行来挑最好成绩。
    for previous in protocol['trials'][:protocol['trials'].index(registered)]:
        prior = read(previous['trial_ref'])
        path = Path(prior['output_root']) / 'result.json'
        if not path.is_file() or read(ref(path)).get('trial_id') != previous['trial_id']:
            raise ValueError('ONLINE_AB_PRIOR_REGISTERED_TRIAL_NOT_TERMINAL')
    output = Path(trial['output_root'])
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    deadline = started + protocol['wall_seconds']
    deadline_epoch = time.time() + protocol['wall_seconds']
    before = source_snapshot(trial['source_audit_root'])
    save(output / 'admission.json', {'protocol_ref': protocol_ref, 'trial_ref': registered['trial_ref'],
        'plan_ref': trial.get('acceptance_plan_ref'),
        'source_before': before, 'started_at': datetime.now(timezone.utc).isoformat(),
        'deadline_epoch_seconds': deadline_epoch, 'deadline_monotonic_seconds': deadline})
    result = {'schema': 'context-online-ab.run-result.v1', **{key: trial[key] for key in ('trial_id','task_id','arm','repeat')},
        'protocol_ref': protocol_ref, 'trial_ref': registered['trial_ref'], 'status': 'not_started', 'success': False,
        'wall_budget_seconds': protocol['wall_seconds'], 'agent_process': None, 'acceptance_process': None,
        'acceptance_result_ref': None, 'source_before': before, 'forbidden_changes': []}
    try:
        snapshot = read(protocol['platform_snapshot_ref'])
        command = [sys.executable, '-I', '-B', str(Path(snapshot['snapshot_root']) / 'scripts/benchmark_platform_entry.py'),
                   '--ready', trial['ready_ref']['path']]
        agent = execute(command, cwd=trial['workspace'], stdin_path=None, output=output / 'agent', deadline=deadline)
        result['agent_process'] = agent
        after = source_snapshot(trial['source_audit_root'])
        changed = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
        result['source_after_agent'] = after
        result['changed_source_paths'] = changed
        result['forbidden_changes'] = [name for name in changed if name not in trial['allowed_source_paths']]
        if agent.get('timeout'):
            result['status'] = 'agent_timeout'
        elif result['forbidden_changes']:
            result['status'] = 'source_scope_failed'
        elif agent.get('exit_code') != 0:
            result['status'] = 'agent_failed'
        else:
            fields = {'ready': trial['ready_ref']['path'], 'output_root': str(output),
                'remaining_seconds': str(max(0, deadline-time.monotonic())),
                'deadline_epoch_seconds': str(deadline_epoch), 'deadline_monotonic_seconds': str(deadline),
                'workspace': trial['workspace'], 'arm': trial['arm']}
            acceptance = execute([item.format(**fields) for item in trial['acceptance_command']],
                cwd=trial['workspace'], stdin_path=None, output=output / 'acceptance', deadline=deadline)
            result['acceptance_process'] = acceptance
            path = Path(trial['acceptance_result_path'])
            if path.is_file():
                result['acceptance_result_ref'] = ref(path)
                value = read(result['acceptance_result_ref'])
                result['success'] = (acceptance.get('exit_code') == 0 and not acceptance.get('timeout')
                    and value.get('delivery_complete') is True and time.monotonic() <= deadline)
            result['status'] = 'completed' if result['success'] else 'acceptance_timeout' if acceptance.get('timeout') else 'acceptance_failed'
    except Exception as error:
        result.update(status='execution_error', error={'type': type(error).__name__, 'message': str(error)})
    finally:
        result['elapsed_seconds'] = time.monotonic()-started
        result['source_after_acceptance'] = source_snapshot(trial['source_audit_root'])
        result.update(product_references(ready))
        # 为什么要有它：终态文件存在不证明超时请求的完整计费，完整用量只能由实际provider记录覆盖来确认。
        result['cost_coverage'] = {'routing_complete': False, 'product_complete': False,
            'delivery_model_calls': 0, 'other_model_calls': 0}
        try:
            from scripts.summarize_context_online_ab import infer_current_trial_cost_coverage
            result['cost_coverage'] = infer_current_trial_cost_coverage(result, ready)
        except Exception as error:
            result['cost_inference_error'] = {'type': type(error).__name__, 'message': str(error)}
        reference = save(output / 'result.json', result)
    return reference


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--protocol', required=True, type=Path)
    parser.add_argument('--trial-id', required=True)
    parser.add_argument('--preflight-only', action='store_true')
    parser.add_argument('--allow-runtime', action='store_true')
    args = parser.parse_args()
    if args.preflight_only:
        checked_trial(ref(args.protocol), args.trial_id, allow_runtime=args.allow_runtime)
        print(json.dumps({'status': 'preflight_passed', 'trial_id': args.trial_id, 'model_calls': 0}))
        return 0
    result = run(ref(args.protocol), args.trial_id, allow_runtime=args.allow_runtime)
    print(json.dumps(result))
    return 0 if read(result)['success'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
