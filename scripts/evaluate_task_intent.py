"""Evaluate frozen dialogue labels through the normal routing CLI, retaining its records."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def save(path, value):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)


def matches(decision, allowed, active):
    if not isinstance(decision, dict):
        return False
    return any(all(decision.get(key) == (active if key == 'target_id' and value == 'prior' else value)
                   for key, value in candidate.items()) for candidate in allowed)


def evaluate(*, cases_path, output_root, execution_config, parent_execution_config, active_run_id,
             platform_root, dispatch_cases=(), only_cases=()):
    corpus = json.loads(Path(cases_path).read_bytes())
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=False)
    if corpus.get('schema') != 'clarification-evaluation-cases.v1':
        raise ValueError('INTENT_EVALUATION_CASE_SCHEMA_INVALID')
    episodes = [case for case in corpus['episodes'] if not only_cases or case['id'] in only_cases]
    if set(dispatch_cases) - {case['id'] for case in episodes if case['execution_mode'] == 'real_dispatch_candidate'}:
        raise ValueError('INTENT_EVALUATION_DISPATCH_NOT_SELECTED')
    # 为什么要有它：标签只在评分端读取，真实路由入口只收到用户消息和可验证的项目/任务绑定。
    protocol = {'cases_ref': reference(cases_path), 'execution_config_ref': reference(execution_config),
        'parent_execution_config_ref': reference(parent_execution_config), 'active_run_id': active_run_id,
        'platform_root': str(Path(platform_root).resolve()), 'script_ref': reference(__file__),
        'split': corpus['split'], 'dispatch_cases': list(dispatch_cases), 'independent_mod_task_increment': 0,
        'selected_episode_ids': [case['id'] for case in episodes],
        'scope': 'agent-authored dialogue episodes, real normal routing CLI; previews are not product execution',
        'latency_scope': 'recorded CLI process wall time; scripted replies exclude human reading and response delay',
        'logical_target_mapping': {'prior': active_run_id, 'configured_project': 'configured_project'},
        'requested_context_profiles': sorted({case['context_profile'] for case in episodes}),
        'context_source': 'actual normal routing request records, never the illustrative fixture status or budget'}
    save(output / 'protocol.json', protocol)
    rows = []
    for case in episodes:
        case_root = output / case['id']; case_root.mkdir()
        conversation = output.name + '-' + case['id']
        parent = None
        turns = []
        for index, expected in enumerate(case['turns'], 1):
            folder = case_root / str(index); folder.mkdir()
            command = [sys.executable, '-X', 'utf8', '-B', '-m', 'scripts.dsh_run_request',
                '--execution-config', str(Path(execution_config).resolve()),
                '--route-request' if case['id'] in dispatch_cases else '--route-preview',
                '--conversation-id', conversation, '--routing-turn-id', f'turn-{index}',
                '--active-run-id', active_run_id, '--parent-execution-config', str(Path(parent_execution_config).resolve())]
            if parent:
                command += ['--clarification-for', parent]
            save(folder / 'command.json', {'argv': command, 'stdin': expected['user_message'], 'cwd': str(platform_root)})
            started = time.perf_counter()
            process = subprocess.run(command, cwd=platform_root, input=expected['user_message'].encode('utf-8'),
                capture_output=True, timeout=2400 if case['id'] in dispatch_cases else 240,
                env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'},
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            (folder / 'stdout.json').write_bytes(process.stdout); (folder / 'stderr.log').write_bytes(process.stderr)
            try:
                result = json.loads(process.stdout)
            except (ValueError, UnicodeError):
                result = {'status': 'invalid_cli_output'}
            decision = result.get('decision')
            row = {'turn': index, 'result': result, 'exit_code': process.returncode,
                'process_seconds': time.perf_counter()-started, 'stdout_ref': reference(folder / 'stdout.json'),
                'stderr_ref': reference(folder / 'stderr.log'), 'expected': expected,
                'action_target_joint_correct': matches(decision, expected['allowed_decisions'], active_run_id),
                'clarification_required': expected['must_clarify'],
                'clarification_returned': isinstance(decision, dict) and decision.get('action') == 'clarify',
                'unnecessary_clarification': expected['clarification_not_needed'] and isinstance(decision, dict)
                    and decision.get('action') == 'clarify'}
            if result.get('routing_record_path'):
                row['routing_result_ref'] = reference(result['routing_record_path'])
            save(folder / 'scored-result.json', row)
            turns.append(row)
            if index < len(case['turns']):
                if result.get('status') != 'needs_clarification':
                    break
                parent = result['route_id']
        row = {'episode_id': case['id'], 'families': case['families'], 'planned_turns': len(case['turns']),
            'turns': turns, 'all_turns_reached': len(turns) == len(case['turns']),
            'episode_joint_correct': len(turns) == len(case['turns']) and all(t['action_target_joint_correct'] for t in turns),
            'execution_mode': 'normal_dispatch' if case['id'] in dispatch_cases else 'route_preview',
            'post_clarification_execution_status': turns[-1]['result'].get('status') if case['id'] in dispatch_cases else 'not_executed_preview'}
        rows.append(row); save(case_root / 'result.json', row)
        print(json.dumps({'episode': case['id'], 'correct': row['episode_joint_correct'],
            'turns': len(turns), 'status': turns[-1]['result'].get('status')}, ensure_ascii=False), flush=True)
    actual = [turn for row in rows for turn in row['turns']]
    usage = {}
    for key in ('input_tokens', 'output_tokens'):
        values = [(turn['result'].get('routing_usage') or {}).get(key) for turn in actual
                  if turn['result'].get('routing_model_calls_reserved')]
        usage[key] = {'total': sum(values) if all(type(v) is int for v in values) else None,
            'known_subtotal': sum(v for v in values if type(v) is int), 'unknown_count': sum(type(v) is not int for v in values)}
    result = {'split': corpus['split'], 'episodes': rows, 'episode_count': len(rows),
        'episode_joint_correct': sum(row['episode_joint_correct'] for row in rows),
        'planned_turns': sum(row['planned_turns'] for row in rows), 'executed_turns': len(actual),
        'turn_action_target_joint_correct': sum(turn['action_target_joint_correct'] for turn in actual),
        'necessary_clarification_opportunities': sum(turn['clarification_required'] for turn in actual),
        'necessary_clarifications_returned': sum(turn['clarification_required'] and turn['clarification_returned'] for turn in actual),
        'unnecessary_clarifications': sum(turn['unnecessary_clarification'] for turn in actual),
        'routing_calls_reserved': sum(turn['result'].get('routing_model_calls_reserved', 0) for turn in actual),
        'routing_transport_calls': (sum(turn['result']['routing_transport_calls'] for turn in actual)
            if all(type(turn['result'].get('routing_transport_calls')) is int for turn in actual) else None),
        'routing_transport_calls_known_subtotal': sum(turn['result'].get('routing_transport_calls_known_subtotal', 0) for turn in actual),
        'routing_usage': usage, 'process_seconds_sum': sum(turn['process_seconds'] for turn in actual),
        'independent_mod_task_increment': 0, 'protocol_ref': reference(output / 'protocol.json')}
    save(output / 'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('cases', 'output-root', 'execution-config', 'parent-execution-config', 'active-run-id', 'platform-root'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--dispatch-case', action='append', default=[])
    parser.add_argument('--only-case', action='append', default=[])
    args = parser.parse_args()
    result = evaluate(cases_path=args.cases, output_root=args.output_root, execution_config=args.execution_config,
        parent_execution_config=args.parent_execution_config, active_run_id=args.active_run_id,
        platform_root=args.platform_root, dispatch_cases=args.dispatch_case, only_cases=args.only_case)
    print(json.dumps({key: result[key] for key in ('episode_count', 'episode_joint_correct', 'executed_turns',
        'turn_action_target_joint_correct', 'routing_calls_reserved', 'routing_usage')}))


if __name__ == '__main__':
    main()
