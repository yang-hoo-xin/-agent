import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, writeFile, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { apply, validateConfig } from '../index.mjs';

const python = process.env.MOD_AGENT_PYTHON;
assert.ok(python, 'Set MOD_AGENT_PYTHON to the exact test Python executable.');

// These child processes simulate only the existing read-only Python boundaries.
// No product model, compiler, verifier or Apply is available to the fixture.
const common = `import json,sys
from pathlib import Path
data = json.loads(Path("fixture.json").read_text(encoding="utf-8"))
def option(name):
    return next((arg.split("=", 1)[1] for arg in sys.argv[1:] if arg.startswith(name + "=")), None)
def audit(kind):
    with Path("calls.jsonl").open("a", encoding="utf-8") as output:
        output.write(json.dumps({"kind":kind,"argv":sys.argv[1:],"model_calls_performed":0}) + "\\n")
`;

async function fixture({ attempts = [], failed = false, inlineRunId = false, delivered = false,
  admitted = false, deliveryPending = false, blockedReceipt, wrongReceiptRun = false } = {}) {
  const root = await mkdtemp(join(tmpdir(), 'dsh-task-'));
  const runId = 'public-task';
  const featureId = 'current-feature';
  const runRoot = join(root, 'runs', runId);
  const storeRoot = join(runRoot, 'a');
  await Promise.all([mkdir(join(root, 'scripts')), mkdir(storeRoot, { recursive: true }),
    mkdir(join(root, 'old-intake'))]);
  const source = join(runRoot, 'Source.cs');
  await writeFile(source, 'class Source { public bool Enabled = true; }\n');
  const blockers = failed ? [{ owner: 'platform', stage: 'generate_patch_proposal_execution',
    code: 'PRODUCT_NODE_EXECUTION_FAILED',
    message: 'PatchContinuationError: PATCH_CONTINUATION_SEMANTIC_IDENTITY_MISMATCH' }] : [];
  const result = { run_id: runId, request_id: 'request-one', feature_id: featureId,
    run_root: runRoot, current_stage: failed ? null : 'awaiting_approval',
    model_call_count: failed ? 3 : 4, canonical_source_unchanged: true,
    actual_write_performed: false, blockers, artifacts: {},
    ...(failed ? { product_execution_result: { execution_disposition: 'partial',
      failure_stage: 'generate_patch_proposal_execution', blockers } } : { status: 'awaiting_approval' }) };
  const manifest = { run_id: runId, model: 'fixture-recorded-model', model_call_count: result.model_call_count };
  const record = { entry: 'run-request-status', read_only: true, run_id: runId,
    run_root: runRoot, status: 'recorded', model_calls_performed: 0, result, manifest };
  if (admitted) {
    record.result = null;
    manifest.status = 'admitted';
  }
  const rows = attempts.map((id, index) => ({ run_id: id, feature_id: featureId,
    parent_run_id: runId, terminal: { status: index ? 'awaiting_approval' : 'failed',
      terminal_stage: index ? 'dry_run_apply' : 'generate_patch_proposal' },
    proposal_admitted: index > 0, budget_and_counts_recorded: { model_call_count: index + 1 } }));
  await writeFile(join(root, 'fixture.json'), JSON.stringify({ record, attempts: rows, storeRoot,
    result, runRoot, featureId, reviewDiff: '--- Source.cs\n+++ Source.cs\n@@ -1 +1 @@\n-old\n+new\n' }));
  await writeFile(join(runRoot, 'run_result.json'), JSON.stringify(result));
  await writeFile(join(runRoot, 'run_manifest.json'), JSON.stringify(manifest));
  await writeFile(join(root, 'scripts', '__init__.py'), '');
  await writeFile(join(root, 'scripts', 'dsh_run_request.py'), common + `
selected = option("--inspect-run")
if selected is None:
    audit("execute_fixture_only")
    print(json.dumps(data["result"]))
    sys.exit(2 if "product_execution_result" in data["result"] else 0)
audit("inspect")
if selected == data["record"]["run_id"]:
    print(json.dumps(data["record"]))
else:
    print(json.dumps({"entry":"run-request-status","read_only":True,"run_id":selected,
        "status":"not_found","model_calls_performed":0}))
`);
  await writeFile(join(root, 'scripts', 'engineering_cognition.py'), common + `
audit("query")
arguments = sys.argv[1:]
selected_store = arguments[arguments.index("--artifact-store-root") + 1]
if selected_store != data["storeRoot"] or option("--feature-id") != data["featureId"]:
    sys.exit(1)
selected = option("--run-id")
rows = [row for row in data["attempts"] if selected is None or row["run_id"] == selected]
print(json.dumps({"data":{"read_only":True,"model_calls_performed":0,
    "verifier_executions_performed":0,"product_source_writes_performed":False,"attempts":rows}}))
`);
  await writeFile(join(root, 'scripts', 'dsh_review_run.py'), common + `
audit("review")
selected = option("--run-id")
if (option("--artifact-store-root") != data["storeRoot"] or
    option("--workspace-root") != data["runRoot"] or
    option("--feature-id") != data["featureId"] or
    selected not in [row["run_id"] for row in data["attempts"]]):
    sys.exit(1)
print(json.dumps({"entry":"review-run","read_only":True,"run_id":selected,
    "feature_id":data["featureId"],"query_model_calls":0,"query_verifier_executions":0,
    "product_source_writes_performed":False,"artifact_writes_performed":False,
    "approval_created":False,"apply_allowed":False,"product_execution_started":False,
    "status":"reviewable_diff","unified_diff":data["reviewDiff"]}))
`);
  const executionConfigPath = join(root, 'execution.json');
  await writeFile(executionConfigPath, JSON.stringify({ arguments: [
    '--workspace-root', join(root, 'runs'), ...(inlineRunId ? [`--run-id=${runId}`] : ['--run-id', runId]),
  ] }));
  if (delivered) await writeFile(join(root, 'scripts', 'dsh_deliver_run.py'), common + `
assert option('--action') == 'status'
audit('delivery_status')
scope='sha256:'+'a'*64
destination=str(Path('delivery').resolve())
receipt={'status':'delivered','run_id':data['record']['run_id'],'scope_hash':scope,'delivery_path':destination,
    'apply_result':{'status':'applied_in_isolation'},
    'build_result':{'status':'built','build_result':{'path':'fixture-build.json','artifact_hash':'b'*64}},
    'delivery_ref':{'path':'fixture-delivery.json','sha256':'c'*64}}
print(json.dumps({'entry':'dsh-delivery','run_id':data['record']['run_id'],'read_only':True,
    'status':'delivered','model_calls_performed':0,'runtime_executions_performed':0,
    'product_source_writes_performed':False,'builds_performed':0,'scope_hash':scope,
    'delivery_path':destination,'receipt':receipt}))
`);
  if (deliveryPending) await writeFile(join(root, 'scripts', 'dsh_deliver_run.py'), common + `
audit('delivery_status')
print(json.dumps({'entry':'dsh-delivery','run_id':data['record']['run_id'],'read_only':True,
    'status':'blocked','reason':'DSH_DELIVERY_PENDING_PUBLIC_RESULT_REQUIRED',
    'model_calls_performed':0,'runtime_executions_performed':0,
    'product_source_writes_performed':False,'builds_performed':0}))
`);
  if (blockedReceipt) await writeFile(join(root, 'scripts', 'dsh_deliver_run.py'), common + `
assert option('--action') == 'status'
audit('delivery_status')
scope='sha256:'+'a'*64
destination=str(Path('delivery').resolve())
receipt={'status':'blocked','run_id':${wrongReceiptRun ? "'other-task'" : "data['record']['run_id']"},
    'scope_hash':scope,'delivery_path':destination,'apply_owner_invoked':True,
    'stopped_after':'applying','reason':'fixture owner failed',
    'uncertain_effects':{'product_source_writes_performed':None,'builds_performed':0}}
if ${blockedReceipt === 'after_build' ? 'True' : 'False'}:
    receipt.update(stopped_after='built',build_owner_invoked=True,
        apply_result={'status':'applied_in_isolation','product_source_writes_performed':True},
        build_result={'status':'built','builds_performed':1,
            'build_result':{'path':'fixture-build.json','artifact_hash':'b'*64}},
        uncertain_effects={'product_source_writes_performed':True,'builds_performed':1},
        reason='fixture delivery retention failed')
print(json.dumps({'entry':'dsh-delivery','run_id':data['record']['run_id'],'read_only':True,
    'status':'blocked','model_calls_performed':0,'runtime_executions_performed':0,
    'product_source_writes_performed':False,'builds_performed':0,'scope_hash':scope,
    'delivery_path':destination,'receipt':receipt,
    'receipt_ref':{'path':str(Path('receipt.json').resolve()),'sha256':'c'*64}}))
`);
  const config = validateConfig({ pythonExecutable: python, repositoryRoot: root,
    artifactStoreRoot: join(root, 'old-intake'), featureId: 'old-feature',
    workspaceRoot: root, targetMod: 'FixtureMod', executionConfigPath,
    ...(delivered || deliveryPending || blockedReceipt ? { deliveryRoot: join(root, 'delivery') } : {}) });
  function session() {
    const commands = new Map();
    apply({ commands: { register: command => commands.set(command.name, command) }, on() {} }, config);
    return (name, rawInput = '') => commands.get(name).handler({ rawInput });
  }
  const protectedFiles = [source, join(runRoot, 'run_result.json'), join(runRoot, 'run_manifest.json')];
  const hashes = async () => Promise.all(protectedFiles.map(async path =>
    createHash('sha256').update(await readFile(path)).digest('hex')));
  const before = await hashes();
  const calls = async () => (await readFile(join(root, 'calls.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse);
  async function assertReadOnly() {
    assert.deepEqual(await hashes(), before, 'source and original run records must remain unchanged');
    const recorded = await calls();
    assert.ok(recorded.length > 0);
    assert.ok(recorded.every(call => call.model_calls_performed === 0));
    assert.ok(recorded.every(call => call.kind !== 'execute_fixture_only'), 'status/review must never dispatch a run');
  }
  return { runId, session, record, rows, storeRoot, calls, assertReadOnly };
}

test('reopened delivered task shows Build stage while preserving original awaiting-approval history', async () => {
  const f = await fixture({ delivered: true });
  for (let i = 0; i < 2; i++) {
    const response = await f.session()('mod-status', f.runId);
    assert.equal(response.kind, 'success', response.text);
    const shown = JSON.parse(response.text);
    assert.equal(shown.current_status, 'delivered');
    assert.equal(shown.current_stage, 'build');
    assert.equal(shown.recorded_status, 'awaiting_approval');
    assert.equal(shown.recorded_stage, 'awaiting_approval');
    assert.equal(shown.delivery_continuation.builds_performed, 0);
    assert.equal(shown.delivery_continuation.receipt.build_result.status, 'built');
  }
  await f.assertReadOnly();
});

for (const state of ['admitted', 'partial']) test(`delivery query does not overwrite ${state} task state`, async () => {
  const f = await fixture({ admitted: state === 'admitted', failed: state === 'partial', deliveryPending: true });
  const response = await f.session()('mod-status', f.runId);
  assert.equal(response.kind, 'success', response.text);
  const shown = JSON.parse(response.text);
  assert.equal(shown.current_status, state);
  assert.equal(shown.recorded_status, state);
  assert.equal(shown.delivery_continuation.status, 'not_applicable');
  assert.equal(shown.delivery_continuation.reason, 'DSH_DELIVERY_PENDING_PUBLIC_RESULT_REQUIRED');
  assert.equal((await f.calls()).some(call => call.kind === 'delivery_status'), false);
  await f.assertReadOnly();
});

test('a blocked delivery lookup is reported separately from the retained task status', async () => {
  const f = await fixture({ deliveryPending: true });
  const response = await f.session()('mod-status', f.runId);
  assert.equal(response.kind, 'success', response.text);
  const shown = JSON.parse(response.text);
  assert.equal(shown.current_status, 'awaiting_approval');
  assert.equal(shown.delivery_continuation.status, 'blocked');
  assert.equal(shown.delivery_continuation.reason, 'DSH_DELIVERY_PENDING_PUBLIC_RESULT_REQUIRED');
  await f.assertReadOnly();
});

for (const blockedReceipt of ['apply_exception', 'after_build']) test(`stored blocked receipt preserves execution failure: ${blockedReceipt}`, async () => {
  const f = await fixture({ blockedReceipt });
  for (const command of ['mod-status', 'mod-runs']) {
    const response = await f.session()(command, command === 'mod-status' ? f.runId : '');
    assert.equal(response.kind, 'success', response.text);
    const shown = JSON.parse(response.text);
    assert.equal(shown.current_status, 'blocked');
    assert.equal(shown.recorded_status, 'awaiting_approval');
    assert.equal(shown.delivery_continuation.receipt.status, 'blocked');
    assert.equal(shown.delivery_continuation.builds_performed, 0, 'query cost stays zero');
    if (blockedReceipt === 'after_build') {
      assert.equal(shown.current_stage, 'build');
      assert.equal(shown.delivery_continuation.receipt.build_result.builds_performed, 1);
      assert.equal(shown.delivery_continuation.receipt.reason, 'fixture delivery retention failed');
    } else {
      assert.equal(shown.delivery_continuation.receipt.uncertain_effects.product_source_writes_performed, null);
    }
  }
  await f.assertReadOnly();
});

test('blocked receipt from a different run is rejected instead of projecting a task failure', async () => {
  const f = await fixture({ blockedReceipt: 'after_build', wrongReceiptRun: true });
  const response = await f.session()('mod-status', f.runId);
  assert.equal(response.kind, 'error');
  assert.match(response.text, /DELIVERY_CONTRACT_INVALID/u);
  await f.assertReadOnly();
});

test('public task lists two distinct Patch attempts and selects each original child Store', async () => {
  const f = await fixture({ attempts: ['recorded-segment-blue', 'recorded-segment-green'] });
  const invoke = f.session();
  const task = await invoke('mod-status', f.runId);
  assert.equal(task.kind, 'success');
  const shown = JSON.parse(task.text);
  assert.equal(shown.run_id, f.runId);
  assert.deepEqual(shown.patch_attempts.map(row => row.run_id), f.rows.map(row => row.run_id));
  assert.equal(shown.query_model_calls, 0);
  for (const row of f.rows) {
    const child = await invoke('mod-status', row.run_id);
    assert.equal(child.kind, 'success', child.text);
    assert.deepEqual(JSON.parse(child.text).records.map(item => item.run_id), [row.run_id]);
    const review = await invoke('mod-review', row.run_id);
    assert.equal(review.kind, 'success', review.text);
    assert.match(review.text, /--- Source\.cs/u);
    assert.match(review.text, new RegExp(row.run_id, 'u'));
  }
  const parentReview = await invoke('mod-review', f.runId);
  assert.equal(parentReview.kind, 'success');
  assert.match(parentReview.text, /recorded-segment-blue/u);
  assert.match(parentReview.text, /recorded-segment-green/u);
  assert.match(parentReview.text, /不把任务ID当作Patch ID/u);
  await f.assertReadOnly();
});

test('a failure before Patch remains queryable with its original error and zero query model calls', async () => {
  const f = await fixture({ failed: true });
  const invoke = f.session();
  for (const [command, input] of [['mod-runs', ''], ['mod-status', f.runId]]) {
    const response = await invoke(command, input);
    assert.equal(response.kind, 'success', response.text);
    const shown = JSON.parse(response.text);
    assert.equal(shown.recorded_status, 'partial');
    assert.equal(shown.model_call_count, 3, 'historical execution calls must not be replaced by query cost');
    assert.equal(shown.query_model_calls, 0);
    assert.deepEqual(shown.blockers, f.record.result.blockers);
    assert.deepEqual(shown.patch_attempts, []);
    assert.equal(shown.original_result_path, join(f.record.run_root, 'run_result.json'));
  }
  const review = await invoke('mod-review', f.runId);
  assert.equal(review.kind, 'success', review.text);
  assert.match(review.text, /尚无可审查diff/u);
  assert.equal((await f.calls()).some(call => call.kind === 'review'), false);
  await f.assertReadOnly();
});

for (const inlineRunId of [false, true]) test(`a new plugin instance recovers child Store from fixed ${inlineRunId ? 'inline' : 'separate'} run ID`, async () => {
  const f = await fixture({ attempts: ['persisted-child-one', 'persisted-child-two'], inlineRunId });
  const beforeRestart = f.session();
  assert.equal((await beforeRestart('mod-runs')).kind, 'success');
  // No selected Store or child binding is shared with this new plugin instance.
  const afterRestart = f.session();
  const child = await afterRestart('mod-status', 'persisted-child-two');
  assert.equal(child.kind, 'success', child.text);
  assert.equal(JSON.parse(child.text).records[0].run_id, 'persisted-child-two');
  const reviewAfterAnotherRestart = await f.session()('mod-review', 'persisted-child-one');
  assert.equal(reviewAfterAnotherRestart.kind, 'success', reviewAfterAnotherRestart.text);
  assert.match(reviewAfterAnotherRestart.text, /--- Source\.cs/u);
  const queryCalls = (await f.calls()).filter(call => call.kind === 'query');
  assert.ok(queryCalls.every(call => call.argv.includes(f.storeRoot)));
  await f.assertReadOnly();
});

test('partial execution is an error result while its original failure remains visible', async () => {
  const f = await fixture({ failed: true });
  const response = await f.session()('mod-run', 'Read this stored fixture result only.');
  assert.equal(response.kind, 'error');
  const shown = JSON.parse(response.text);
  assert.equal(shown.result.product_execution_result.execution_disposition, 'partial');
  assert.equal(shown.result.product_execution_result.failure_stage, 'generate_patch_proposal_execution');
  assert.deepEqual(shown.result.blockers, f.record.result.blockers);
  assert.equal(shown.result.canonical_source_unchanged, true);
  assert.equal(shown.original_result_path, join(f.record.run_root, 'run_result.json'));
  assert.deepEqual((await f.calls()).map(call => call.kind), ['execute_fixture_only']);
});
