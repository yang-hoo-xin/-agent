import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { apply, newProjectBackend, parseNewProjectInput, validateConfig } from '../index.mjs';

test('new project command distinguishes initialization, readback, start and existing target', () => {
  assert.deepEqual(parseNewProjectInput('--independent 远征计时器 -- 手动开始\n--target-project literal'),
    { action: 'initialize', displayName: '远征计时器', description: '手动开始\n--target-project literal' });
  assert.deepEqual(parseNewProjectInput('--start dsh_abc'), { action: 'start', runId: 'dsh_abc' });
  assert.deepEqual(parseNewProjectInput('--preview dsh_abc'), { action: 'preview', runId: 'dsh_abc' });
  assert.equal(parseNewProjectInput('existing target change'), null);
  assert.throws(() => parseNewProjectInput('--start ../other'), /RUN_ID_INVALID/u);
  assert.throws(() => parseNewProjectInput('--independent name'), /NAME_AND_DESCRIPTION/u);
});

test('normal mod-new handler initializes without model, preview survives a new session, start is explicit', async () => {
  const root = await mkdtemp(join(tmpdir(), 'dsh-new-project-'));
  await mkdir(join(root, 'scripts'));
  await writeFile(join(root, 'scripts', '__init__.py'), '');
  const profile = join(root, 'new.json');
  await writeFile(profile, '{"arguments":[]}');
  await writeFile(join(root, 'scripts', 'dsh_run_request.py'), `import json,sys
from pathlib import Path
args=sys.argv[1:]
with Path('calls.jsonl').open('a') as f: f.write(json.dumps(args)+'\\n')
if any(x.startswith('--start-project=') for x in args):
 print(json.dumps({'status':'partial','run_id':'dsh_fixture','model_call_count':1}))
else:
 print(json.dumps({'entry':'dsh-new-project','status':'initialized_awaiting_product_execution',
 'run_id':'dsh_fixture','project_identity':{'plugin_name':'计时器'},'model_calls_performed':0,
 'product_execution_started':False,'build_performed':False,'game_deployment_performed':False}))
`);
  const config = validateConfig({ pythonExecutable: process.env.MOD_AGENT_PYTHON,
    repositoryRoot: root, artifactStoreRoot: root, featureId: 'fixture',
    executionConfigPath: profile, newTaskConfigPath: profile });
  function session() {
    const commands = [];
    apply({ commands: { register: x => commands.push(x) }, on() {} }, config);
    return commands.find(x => x.name === 'mod-new');
  }
  const first = await session().handler({ rawInput: '--independent 计时器 -- 手动计时' });
  assert.equal(first.kind, 'success');
  assert.equal(JSON.parse(first.text).model_calls_performed, 0);
  assert.equal(JSON.parse(first.text).next_action, '/mod-new --start dsh_fixture');
  const fresh = session();
  const preview = await fresh.handler({ rawInput: '--preview dsh_fixture' });
  assert.equal(JSON.parse(preview.text).product_execution_started, false);
  const calls = (await readFile(join(root, 'calls.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse);
  assert.ok(calls[0].includes('--initialize-project-name=计时器'));
  assert.ok(calls[1].includes('--preview-project=dsh_fixture'));
  assert.ok(calls.every(x => !x.some(v => v.startsWith('--start-project='))));
  const started = await fresh.handler({ rawInput: '--start dsh_fixture' });
  assert.equal(started.kind, 'error');
  assert.equal(JSON.parse(started.text).result.status, 'partial');
  assert.equal(JSON.parse(started.text).result.model_call_count, 1);
});

for (const outcome of ['partial', 'awaiting_approval', 'DSH_INPUT_ERROR', 'task_incomplete_inspect_before_retry']) {
  test(`configured start delegates once to advance-task and preserves ${outcome}`, async () => {
    const root = await mkdtemp(join(tmpdir(), 'dsh-advance-'));
    await mkdir(join(root, 'scripts'));
    await writeFile(join(root, 'scripts', '__init__.py'), '');
    const profile = join(root, 'new.json');
    const allocation = join(root, 'allocation.json');
    await writeFile(profile, '{"arguments":[]}');
    await writeFile(allocation, '{}');
    const result = { status: outcome, run_id: 'dsh_recorded', model_call_budget: { consumed: 4, maximum: 13 },
      blockers: [{ code: 'ORIGINAL_STOP' }], reason: 'original backend reason',
      continuation_root: join(root, 'recorded-continuation'),
      request_interpretation_revision: { original: 'old-ref', current: 'new-ref' } };
    await writeFile(join(root, 'response.json'), JSON.stringify(result));
    await writeFile(join(root, 'scripts', 'dsh_run_request.py'), `import json,sys
from pathlib import Path
with Path('calls.jsonl').open('a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')
print(Path('response.json').read_text())
sys.exit(${outcome === 'awaiting_approval' ? 0 : 2})
`);
    const config = validateConfig({ pythonExecutable: process.env.MOD_AGENT_PYTHON,
      repositoryRoot: root, artifactStoreRoot: root, featureId: 'fixture',
      executionConfigPath: join(root, 'old.json'), newTaskConfigPath: profile,
      findingsContinuationConfigPath: allocation });
    const commands = [];
    apply({ commands: { register: c => commands.push(c) }, on() {} }, config);
    const response = await commands.find(c => c.name === 'mod-new').handler({ rawInput: '--start dsh_recorded' });
    const calls = (await readFile(join(root, 'calls.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse);
    assert.deepEqual(calls, [[`--execution-config=${profile}`, '--advance-task=dsh_recorded',
      `--findings-allocation-config=${allocation}`]]);
    assert.equal(response.kind, outcome === 'awaiting_approval' ? 'success' : 'error');
    const shown = JSON.parse(response.text);
    if (outcome === 'DSH_INPUT_ERROR') assert.deepEqual(shown, result);
    else {
      assert.equal(shown.backend_entry, 'advance-task');
      assert.deepEqual(shown.result.model_call_budget, result.model_call_budget);
      assert.deepEqual(shown.result.blockers, result.blockers);
      assert.equal(shown.result.reason, result.reason);
      assert.equal(shown.result.continuation_root, result.continuation_root);
      assert.deepEqual(shown.result.request_interpretation_revision, result.request_interpretation_revision);
    }
  });
}

test('allocation configuration does not turn initialization or preview into advance calls', async () => {
  const root = await mkdtemp(join(tmpdir(), 'dsh-advance-preview-'));
  await mkdir(join(root, 'scripts'));
  await writeFile(join(root, 'scripts', '__init__.py'), '');
  await writeFile(join(root, 'scripts', 'dsh_run_request.py'), `import json,sys
from pathlib import Path
with Path('calls.jsonl').open('a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')
print(json.dumps({'entry':'dsh-new-project','model_calls_performed':0,
'product_execution_started':False,'build_performed':False,'game_deployment_performed':False}))
`);
  const config = validateConfig({ pythonExecutable: process.env.MOD_AGENT_PYTHON,
    repositoryRoot: root, artifactStoreRoot: root, featureId: 'fixture',
    executionConfigPath: join(root, 'profile.json'), findingsContinuationConfigPath: join(root, 'allocation.json') });
  for (const selection of [{ action: 'initialize', displayName: 'timer', description: 'request' },
    { action: 'preview', runId: 'dsh_abc' }]) {
    assert.equal((await newProjectBackend(config, { selection })).model_calls_performed, 0);
  }
  const calls = (await readFile(join(root, 'calls.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse);
  assert.deepEqual(calls, [
    [`--execution-config=${config.executionConfigPath}`, '--initialize-project-name=timer'],
    [`--execution-config=${config.executionConfigPath}`, '--preview-project=dsh_abc'],
  ]);
});
