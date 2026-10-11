import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { apply, validateConfig, backendArguments } from '../index.mjs';

const python = process.env.MOD_AGENT_PYTHON;
assert.ok(python, 'Set MOD_AGENT_PYTHON to the selected Python.');

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'dsh-investigation-'));
  await mkdir(join(root, 'scripts'));
  await mkdir(join(root, 'source-store'));
  const selected = { artifactStoreRoot: join(root, 'source-store'), featureId: 'original-feature', runId: 'original-failure',
    currentContext: { target_mod: 'ExampleMod', model: 'original-model' } };
  const investigationConfigPath = join(root, 'investigation.json');
  const executionConfigPath = join(root, 'execution.json');
  await writeFile(investigationConfigPath, JSON.stringify(selected));
  await writeFile(executionConfigPath, JSON.stringify({ arguments: ['--run-id', 'new-public-run'] }));
  await writeFile(join(root, 'scripts/__init__.py'), '');
  const common = `import json,sys
from pathlib import Path
def arg(name): return next((v.split('=',1)[1] for v in sys.argv[1:] if v.startswith(name+'=')),None)
def audit(kind,body=None):
    with Path('calls.jsonl').open('a') as f: f.write(json.dumps({'kind':kind,'argv':sys.argv[1:],'body':body})+'\\n')
`;
  await writeFile(join(root, 'scripts/engineering_cognition.py'), common + `
audit('investigate')
assert sys.argv[sys.argv.index('--query')+1]=='patch-investigation'
assert arg('--run-id')=='original-failure'
assert arg('--feature-id')=='original-feature'
print(json.dumps({'data':{'read_only':True,'model_calls_performed':0,'verifier_executions_performed':0,
  'product_source_writes_performed':False,'attempts':[{'run_id':'original-failure','investigation_chain':{
    'authority':'non_authoritative','stages':[{'title':str(i),'status':'unknown','conclusion':'Bound source facts only.',
    'next_verification':'Check explicit missing evidence.'} for i in range(6)]}}]}}))
`);
  await writeFile(join(root, 'scripts/dsh_task_memory.py'), common + `
action=arg('--action'); body=sys.stdin.read() if action=='query' else None
audit('memory:'+action,body)
result={'entry':'dsh-task-memory','authority':'planning_only','status':'queried' if action=='query' else 'recorded',
  'model_calls_performed':0,'product_source_writes_performed':False,
  'read_only':action=='query','artifact_writes_performed':action!='query'}
if action=='query': result['query']=body
print(json.dumps(result))
`);
  await writeFile(join(root, 'scripts/dsh_run_request.py'), common + `
audit('original-product',sys.stdin.read())
print(json.dumps({'run_id':'new-public-run','status':'awaiting_approval','feature_id':'new-feature',
  'run_root':str(Path('run').resolve()),'actual_write_performed':False,'model_call_count':2}))
`);
  const config = validateConfig({ pythonExecutable: python, repositoryRoot: root, artifactStoreRoot: selected.artifactStoreRoot,
    featureId: 'unrelated-current-ui-feature', investigationConfigPath, executionConfigPath, memoryStoreRoot: join(root, 'memory') });
  const commands = new Map();
  apply({ on() {}, commands: { register: value => commands.set(value.name, value) } }, config);
  const run = (name, rawInput = '') => commands.get(name).handler({ rawInput });
  const calls = async () => (await readFile(join(root, 'calls.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse);
  return { config, run, calls };
}

test('investigation uses the explicit original task and read-only query, not the current 002 configuration', async () => {
  const f = await fixture();
  assert.throws(() => backendArguments(f.config, undefined, true), /INVESTIGATION_RUN_REQUIRED/u);
  assert.equal((await f.run('mod-investigate', 'wrong-task')).kind, 'error');
  const result = await f.run('mod-investigate');
  assert.equal(result.kind, 'success', result.text);
  assert.match(result.text, /original-failure/u);
  assert.match(result.text, /non_authoritative/u);
  assert.deepEqual((await f.calls()).map(row => row.kind), ['investigate']);
});

test('remember and memory search are distinct actions with literal stdin and no model execution', async () => {
  const f = await fixture();
  assert.equal((await f.run('mod-remember', 'invent this lesson')).kind, 'error');
  const remember = await f.run('mod-remember');
  assert.equal(remember.kind, 'success');
  assert.equal(JSON.parse(remember.text).artifact_writes_performed, true);
  const query = '--action=remember\nFind earlier timeout evidence';
  const search = await f.run('mod-memory', query);
  assert.equal(search.kind, 'success');
  assert.equal(JSON.parse(search.text).query, query);
  const calls = await f.calls();
  assert.deepEqual(calls.map(row => row.kind), ['memory:remember', 'memory:query']);
  assert.ok(!calls[1].argv.some(value => value.includes('Find earlier')));
});

test('a newly completed DSH task invokes bound fact recording once without altering the original outcome', async () => {
  const f = await fixture();
  const result = await f.run('mod-run', 'A new request through the original product.');
  assert.equal(result.kind, 'success', result.text);
  assert.match(result.text, /"status": "awaiting_approval"/u);
  assert.match(result.text, /"model_call_count": 2/u);
  assert.match(result.text, /任务经验存档/u);
  const calls = await f.calls();
  assert.deepEqual(calls.map(row => row.kind), ['original-product', 'memory:remember']);
  assert.ok(calls[1].argv.includes('--run-id=new-public-run'));
  assert.ok(calls[1].argv.some(value => value.startsWith('--execution-config=')));
  assert.ok(!calls[1].argv.some(value => value.startsWith('--investigation-config=')));
});
