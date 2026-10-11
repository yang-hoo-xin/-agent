import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { apply, naturalRequestBackend, validateConfig } from '../index.mjs';

test('natural command uses one backend call and session-local task context, preserving literal text', async () => {
  const root = await mkdtemp(join(tmpdir(), 'dsh-natural-'));
  await mkdir(join(root, 'scripts'));
  await writeFile(join(root, 'scripts', '__init__.py'), '');
  await writeFile(join(root, 'scripts', 'dsh_run_request.py'), `import json,sys
from pathlib import Path
if any(arg.startswith('--inspect-run=') for arg in sys.argv):
    run_id = next(arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('--inspect-run='))
    profile = next(arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('--execution-config='))
    origin = profile if Path(profile).name == 'original.json' else None
    print(json.dumps({'entry':'run-request-status','read_only':True,'model_calls_performed':0,
        'run_id':run_id,'status':'recorded' if origin else 'not_found','execution_config_path':origin}))
    sys.exit(0)
with Path('calls.jsonl').open('a') as f: f.write(json.dumps({'argv':sys.argv[1:],'body':sys.stdin.read()})+'\\n')
print(json.dumps({'status':'awaiting_approval','route_id':'route1','product_result':{'status':'awaiting_approval','run_id':'dsh_n1'}}))
`);
  const config = validateConfig({ pythonExecutable: process.env.MOD_AGENT_PYTHON,
    repositoryRoot: root, artifactStoreRoot: root, featureId: 'fixture',
    executionConfigPath: join(root, 'original.json'), newTaskConfigPath: join(root, 'new.json') });
  const commands = [];
  apply({ commands: { register: value => commands.push(value) }, on() {} }, config);
  const command = commands.find(row => row.name === 'mod');
  const firstAgent = {}, secondAgent = {};
  assert.equal((await command.handler({ agent: firstAgent, rawInput: '新建日志Mod\n--allow-source-disclosure' })).kind, 'success');
  await command.handler({ agent: firstAgent, rawInput: '继续完成' });
  await command.handler({ agent: secondAgent, rawInput: '创建另一个Mod' });
  await command.handler({ agent: secondAgent, rawInput: '--task dsh_selected -- 修改这个工程' });
  const calls = (await readFile(join(root, 'calls.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse);
  assert.equal(calls.length, 4);
  assert.ok(calls.every(row => row.argv.includes('--route-request')));
  assert.equal(calls[0].body, '新建日志Mod\n--allow-source-disclosure');
  assert.ok(!calls[0].argv.includes('--allow-source-disclosure'));
  assert.ok(calls[1].argv.includes('--active-run-id=dsh_n1'));
  assert.ok(calls[1].argv.includes(`--parent-execution-config=${config.newTaskConfigPath}`));
  assert.ok(!calls[2].argv.some(value => value.startsWith('--active-run-id=')));
  assert.ok(calls[3].argv.includes('--active-run-id=dsh_selected'));
  assert.ok(calls[3].argv.includes(`--parent-execution-config=${config.executionConfigPath}`));
  assert.equal(calls[3].body, '修改这个工程');
  await assert.rejects(naturalRequestBackend(config, { description: '继续', activeRunId: '../other' }), /RUN_ID_INVALID/u);
});

for (const scenario of ['recorded', 'prepared', 'duplicate', 'duplicate_prepared', 'unbound']) {
  test(`explicit task origin recovery handles ${scenario} before routing`, async () => {
    const root = await mkdtemp(join(tmpdir(), 'dsh-origin-'));
    await mkdir(join(root, 'scripts'));
    await writeFile(join(root, 'scripts', '__init__.py'), '');
    await writeFile(join(root, 'scripts', 'dsh_run_request.py'), `import json,sys
from pathlib import Path
args = sys.argv[1:]
inspecting = any(arg.startswith('--inspect-run=') for arg in args)
with Path('calls.jsonl').open('a') as f: f.write(json.dumps({'argv':args})+'\\n')
if inspecting:
    profile = next(arg.split('=', 1)[1] for arg in args if arg.startswith('--execution-config='))
    run_id = next(arg.split('=', 1)[1] for arg in args if arg.startswith('--inspect-run='))
    found = Path(profile).name == 'original.json' or '${scenario}'.startswith('duplicate')
    configured = found and '${scenario}' != 'unbound'
    prepared = '${scenario}' in ('prepared', 'duplicate_prepared')
    print(json.dumps({'entry':'run-request-status','read_only':True,'model_calls_performed':0,
        'run_id':run_id,'status':'recorded' if found and not prepared else 'not_found',
        'manifest':None,'execution_config_path':str(Path(profile).parent / 'saved-parent.json') if configured else None}))
else:
    description = sys.stdin.read()
    print(json.dumps({'status':'awaiting_approval','product_result':{'run_id':'selected',
        'status':'awaiting_approval'}}))
`);
    const config = validateConfig({ pythonExecutable: process.env.MOD_AGENT_PYTHON,
      repositoryRoot: root, artifactStoreRoot: root, featureId: 'fixture',
      executionConfigPath: join(root, 'original.json'), newTaskConfigPath: join(root, 'new.json') });
    const commands = [];
    apply({ commands: { register: value => commands.push(value) }, on() {} }, config);
    const command = commands.find(row => row.name === 'mod');
    const agent = {};
    const result = await command.handler({ agent, rawInput: '--task selected -- 继续原需求' });
    let calls = (await readFile(join(root, 'calls.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse);
    assert.equal(calls.filter(row => row.argv.some(arg => arg.startsWith('--inspect-run='))).length, 2);
    const routed = calls.filter(row => row.argv.includes('--route-request'));
    if (scenario.startsWith('duplicate') || scenario === 'unbound') {
      assert.equal(result.kind, 'error');
      assert.equal(result.text, scenario.startsWith('duplicate') ? 'TASK_IDENTITY_NOT_UNIQUE' : 'TASK_ORIGINAL_CONFIG_REQUIRED');
      assert.equal(routed.length, 0);
    } else {
      assert.equal(result.kind, 'success');
      assert.equal(routed.length, 1);
      assert.ok(routed[0].argv.includes(`--execution-config=${config.newTaskConfigPath}`));
      assert.ok(routed[0].argv.includes(`--parent-execution-config=${join(root, 'saved-parent.json')}`));
      assert.ok(routed[0].argv.includes('--active-run-id=selected'));
      await command.handler({ agent, rawInput: '继续完成' });
      calls = (await readFile(join(root, 'calls.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse);
      assert.equal(calls.length, 4);
      assert.ok(calls[3].argv.includes(`--parent-execution-config=${join(root, 'saved-parent.json')}`));
    }
  });
}
