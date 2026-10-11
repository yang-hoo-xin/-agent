import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { apply, validateConfig, deliveryArguments } from '../index.mjs';

const python = process.env.MOD_AGENT_PYTHON;
assert.ok(python, 'Set MOD_AGENT_PYTHON to the exact test Python.');
const scopeHash = `sha256:${'a'.repeat(64)}`;

// Test the command boundary using real Python subprocesses. The backend here
// is a protocol fixture; original Graph/Apply/Build are tested in Python.
async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'dsh-delivery-'));
  await mkdir(join(root, 'scripts'));
  await mkdir(join(root, 'store'));
  await writeFile(join(root, 'scripts', '__init__.py'), '');
  const executionConfigPath = join(root, 'execution.json');
  await writeFile(executionConfigPath, JSON.stringify({ arguments: ['--run-id', 'stored-task'] }));
  await writeFile(join(root, 'scripts', 'dsh_deliver_run.py'), `import json,sys,time
from pathlib import Path
def option(name):
    return next(arg.split('=',1)[1] for arg in sys.argv[1:] if arg.startswith(name+'='))
action=option('--action')
run_id=option('--run-id')
base=dict(entry='dsh-delivery',run_id=run_id,model_calls_performed=0,runtime_executions_performed=0)
if action in ('preview','status'):
    if action=='preview' and Path('delay-first-preview').exists():
        try:
            with Path('preview-entered').open('x'): pass
        except FileExistsError: pass
        else: time.sleep(0.5)
    prior=json.loads(Path('receipt.json').read_text()) if Path('receipt.json').exists() else None
    result=dict(base,read_only=True,product_source_writes_performed=False,builds_performed=0,
        status=prior['status'] if prior else 'awaiting_approval',
        approval_ready=action=='preview' and not prior,
        scope_hash='${scopeHash}',delivery_path=str(Path('delivery').resolve()),
        unified_diff='--- Config.cs\\n+++ Config.cs\\n-old\\n+new\\n',
        build_profile={'command':['dotnet','build'],'working_directory':str(Path('.').resolve())})
    if prior: result['receipt']=prior
else:
    decision=json.loads(sys.stdin.read())
    with Path('dispatches.jsonl').open('a') as handle:
        handle.write(json.dumps({'action':action,'decision':decision,'argv':sys.argv[1:]})+'\\n')
    time.sleep(0.15)
    if decision['scope_hash']!='${scopeHash}' or Path('drift').exists():
        result=dict(base,status='blocked',reason='DELIVERY_SCOPE_CHANGED')
    elif Path('receipt.json').exists():
        prior=json.loads(Path('receipt.json').read_text())
        result=dict(base,status=prior['status'],scope_hash=prior['scope_hash'],delivery_path=prior['delivery_path'],
            receipt=prior,product_source_writes_performed=False,builds_performed=0)
    else:
        receipt=dict(run_id=run_id,status='rejected' if action=='reject' else 'delivered',
            scope_hash=decision['scope_hash'],delivery_path=str(Path('delivery').resolve()),
            apply_result={'status':'rejected' if action=='reject' else 'applied_in_isolation'})
        if action=='deliver':
            receipt['build_result']={'status':'built','build_result':{'path':'fixture-build.json','artifact_hash':'b'*64}}
            receipt['delivery_ref']={'path':'fixture-delivery.json','sha256':'c'*64}
        Path('receipt.json').write_text(json.dumps(receipt))
        result=dict(base,status=receipt['status'],scope_hash=receipt['scope_hash'],delivery_path=receipt['delivery_path'],
            receipt=receipt,product_source_writes_performed=action=='deliver',builds_performed=0 if action=='reject' else 1)
        if action=='deliver': Path('apply-count.txt').write_text('1')
if Path('invalid-success-response').exists():
    result=dict(base,status='delivered')
print(json.dumps(result))
`);
  const config = validateConfig({ pythonExecutable: python, repositoryRoot: root,
    artifactStoreRoot: join(root, 'store'), featureId: 'feature', executionConfigPath,
    deliveryRoot: join(root, 'delivery') });
  function session(sharedAgent = {}) {
    const commands = new Map();
    apply({ on() {}, commands: { register: c => commands.set(c.name, c) } }, config);
    const run = (name, input = '', agent = sharedAgent, signal) => commands.get(name).handler({ rawInput: input, agent, signal });
    return { run, agent: sharedAgent };
  }
  const dispatches = async () => {
    try { return (await readFile(join(root, 'dispatches.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse); }
    catch (error) { if (error.code === 'ENOENT') return []; throw error; }
  };
  return { root, config, session, dispatches };
}

test('delivery stays disabled without a fixed execution config and persistent root', async () => {
  const f = await fixture();
  const { deliveryRoot, ...without } = f.config;
  assert.throws(() => deliveryArguments(without, 'stored-task', 'deliver'), /DELIVERY_NOT_CONFIGURED/u);
  assert.throws(() => validateConfig({ ...f.config, deliveryRoot: 'relative' }), /ABSOLUTE_DELIVERY_ROOT_REQUIRED/u);
  assert.ok(deliveryArguments(f.config, '--action=deliver', 'preview').includes('--run-id=--action=deliver'));
  assert.throws(() => deliveryArguments(f.config, 'stored-task', 'run-request'), /DELIVERY_ACTION_INVALID/u);
});

test('no approval or another session cannot write; explicit decision binds the shown scope', async () => {
  const f = await fixture();
  const { run } = f.session();
  assert.equal((await run('mod-deliver', 'Human')).kind, 'error');
  const preview = await run('mod-delivery', 'stored-task');
  assert.equal(preview.kind, 'success', preview.text);
  assert.match(preview.text, /--- Config\.cs/u);
  assert.match(preview.text, /dotnet/u);
  assert.match(preview.text, /delivery_path/u);
  assert.deepEqual(await f.dispatches(), []);
  assert.equal((await run('mod-deliver', 'Other', {})).kind, 'error');
  assert.equal((await run('mod-deliver', 'Human')).kind, 'success');
  const calls = await f.dispatches();
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0].decision, { decision: 'approve', reviewer: 'Human', scope_hash: scopeHash });
  assert.ok(calls[0].argv.includes('--decision-stdin'));
  assert.ok(!calls[0].argv.some(arg => arg.includes('Human')));
  assert.equal((await run('mod-deliver', 'Human')).kind, 'error');
  assert.equal((await f.dispatches()).length, 1);
});

test('concurrent approvals from different sessions start only one backend child', async () => {
  const f = await fixture();
  const one = f.session();
  const two = f.session();
  await Promise.all([one.run('mod-delivery', 'stored-task'), two.run('mod-delivery', 'stored-task')]);
  const replies = await Promise.all([one.run('mod-deliver', 'One'), two.run('mod-deliver', 'Two')]);
  assert.equal(replies.filter(r => r.kind === 'success').length, 1);
  assert.ok(replies.some(r => r.text.includes('DELIVERY_ALREADY_ACTIVE')));
  assert.equal((await f.dispatches()).length, 1);
});

test('an older preview returning last does not erase the newer displayed approval scope', async () => {
  const f = await fixture();
  await writeFile(join(f.root, 'delay-first-preview'), 'enabled');
  const { run } = f.session();
  const old = run('mod-delivery', 'stored-task');
  let entered = false;
  for (let i = 0; i < 60; i++) {
    try { await readFile(join(f.root, 'preview-entered')); entered = true; break; }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  assert.equal(entered, true, 'first subprocess entered its delayed preview');
  assert.equal((await run('mod-delivery', 'stored-task')).kind, 'success');
  assert.match((await old).text, /REVIEW_SUPERSEDED/u);
  assert.equal((await run('mod-deliver', 'Human')).kind, 'success');
  assert.equal((await f.dispatches()).length, 1);
});

test('rejection, drift and pre-dispatch cancellation retain zero successful writes', async () => {
  for (const outcome of ['reject', 'drift', 'cancel']) {
    const f = await fixture();
    const { run, agent } = f.session();
    await run('mod-delivery', 'stored-task');
    if (outcome === 'drift') await writeFile(join(f.root, 'drift'), 'source changed');
    const controller = new AbortController();
    if (outcome === 'cancel') controller.abort();
    const reply = await run(outcome === 'reject' ? 'mod-decline' : 'mod-deliver', 'Human', agent, controller.signal);
    assert.equal(reply.kind, outcome === 'reject' ? 'success' : 'error', reply.text);
    await assert.rejects(readFile(join(f.root, 'apply-count.txt')), { code: 'ENOENT' });
    if (outcome === 'cancel') assert.equal((await f.dispatches()).length, 0);
  }
});

test('reopen reads delivered artifacts without remembering or consuming an old approval', async () => {
  const f = await fixture();
  const first = f.session();
  await first.run('mod-delivery', 'stored-task');
  await first.run('mod-deliver', 'Human');
  const reopened = f.session();
  const result = await reopened.run('mod-delivery', 'stored-task');
  assert.equal(result.kind, 'success');
  assert.match(result.text, /"status": "delivered"/u);
  assert.match(result.text, /"receipt"/u);
  assert.match(result.text, /"builds_performed": 0/u);
  assert.equal((await reopened.run('mod-deliver', 'Human')).kind, 'error');
  assert.equal((await f.dispatches()).length, 1);
});

test('a delivered label without original Build and delivery references is not shown as success', async () => {
  const f = await fixture();
  await writeFile(join(f.root, 'invalid-success-response'), 'enabled');
  const { run } = f.session();
  const response = await run('mod-delivery', 'stored-task');
  assert.equal(response.kind, 'error');
  assert.match(response.text, /DELIVERY_CONTRACT_INVALID/u);
  assert.doesNotMatch(response.text, /正式构建与交付副本已完成/u);
  assert.equal((await run('mod-deliver', 'Human')).kind, 'error');
  assert.deepEqual(await f.dispatches(), []);
});
