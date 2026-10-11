import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { apply, backendArguments, queryBackend, renderResult, renderSubmission, submissionArguments,
  submitRequest, validateConfig, reviewArguments, reviewBackend, renderReview } from '../index.mjs';

const python = process.env.MOD_AGENT_PYTHON;
assert.ok(python, 'Set MOD_AGENT_PYTHON to the exact test Python executable.');

function data(rows = []) {
  return { read_only: true, model_calls_performed: 0, verifier_executions_performed: 0,
    product_source_writes_performed: false, attempts: rows };
}

async function fixture(body) {
  const root = await mkdtemp(join(tmpdir(), 'dsh-bridge-'));
  await mkdir(join(root, 'scripts'));
  await writeFile(join(root, 'scripts', '__init__.py'), '');
  await writeFile(join(root, 'scripts', 'engineering_cognition.py'), body);
  await mkdir(join(root, 'store'));
  return validateConfig({ pythonExecutable: python, repositoryRoot: root,
    artifactStoreRoot: join(root, 'store'), featureId: 'feature_test' });
}

test('only fixed read-query arguments can cross the process boundary', async () => {
  const config = await fixture('print("unused")');
  const argv = backendArguments(config, '--run-request=changed');
  assert.ok(argv.includes('--run-id=--run-request=changed'));
  assert.equal(argv.filter(item => item === '--query').length, 1);
  assert.equal(argv[argv.indexOf('--query') + 1], 'patch-execution');
  assert.throws(() => backendArguments(config, 'id\napply-patch'), /INVALID_RUN_ID/u);
  assert.throws(() => validateConfig({ ...config, command: 'anything' }), /INVALID_CONFIG/u);
});

test('real child process must return the existing read-only contract', async () => {
  const config = await fixture(`import json\nprint(json.dumps({'data': ${JSON.stringify(data()).replaceAll('true', 'True').replaceAll('false', 'False')}}))`);
  const result = await queryBackend(config);
  assert.deepEqual(result, data());
  await writeFile(join(config.repositoryRoot, 'scripts', 'engineering_cognition.py'),
    'import json\nprint(json.dumps({"data":{"read_only":False,"attempts":[]}}))');
  await assert.rejects(queryBackend(config), /QUERY_CONTRACT_INVALID/u);
});

test('cancellation and output limits stop only the read query', async () => {
  const config = await fixture('import time\ntime.sleep(30)');
  const controller = new AbortController();
  const pending = queryBackend(config, { signal: controller.signal });
  setTimeout(() => controller.abort(), 100);
  await assert.rejects(pending, /QUERY_CANCELLED/u);
  await writeFile(join(config.repositoryRoot, 'scripts', 'engineering_cognition.py'), 'print("x" * 3000)');
  await assert.rejects(queryBackend({ ...config, maxOutputBytes: 1024 }), /QUERY_OUTPUT_LIMIT/u);
});

test('host registers human commands only and returns backend errors without model work', async () => {
  const config = await fixture('raise RuntimeError("private /local/path")');
  const commands = [];
  const events = [];
  apply({ commands: { register: value => commands.push(value) },
    on: (name, handler) => events.push({ name, handler }) }, config);
  assert.equal(events[0].name, 'agent/pre-step');
  assert.deepEqual(await events[0].handler({}, () => assert.fail('DSH must not enter model generation')), { kind: 'reject' });
  assert.deepEqual(commands.map(command => command.name), ['mod-continue', 'mod-resume', 'mod-observe', 'mod-investigate', 'mod-remember', 'mod-memory', 'mod-runs', 'mod-status', 'mod-review', 'mod-approve', 'mod-reject', 'mod-delivery', 'mod-deliver', 'mod-decline', 'mod-submit', 'mod-deployment', 'mod-deploy', 'mod-tasks', 'mod-run', 'mod-new']);
  assert.equal((await commands.find(command => command.name === 'mod-status').handler({ rawInput: '', signal: new AbortController().signal })).kind, 'error');
  const failed = await commands.find(command => command.name === 'mod-runs').handler({ rawInput: '', signal: new AbortController().signal });
  assert.deepEqual(failed, { kind: 'error', text: 'QUERY_BACKEND_FAILED' });
});

test('submission requires administrator-configured target and keeps request out of argv', async () => {
  const config = await fixture('print("unused")');
  assert.throws(() => submissionArguments(config), /SUBMIT_NOT_CONFIGURED/u);
  assert.throws(() => validateConfig({ ...config, workspaceRoot: config.repositoryRoot }), /SUBMIT_CONFIG_INCOMPLETE/u);
  const configured = validateConfig({ ...config, workspaceRoot: config.repositoryRoot, targetMod: 'OwnedConfigService' });
  assert.deepEqual(submissionArguments(configured), ['-B', '-m', 'scripts.dsh_prepare_request',
    `--workspace-root=${configured.workspaceRoot}`, `--artifact-store-root=${configured.artifactStoreRoot}`,
    '--target-mod=OwnedConfigService']);
  await assert.rejects(submitRequest(configured, { description: 'x'.repeat(32769) }), /SUBMIT_REQUEST_INVALID/u);
});

test('human submission reaches original Python planner and persists original Artifact types', async () => {
  const repo = resolve(fileURLToPath(new URL('../../..', import.meta.url)));
  const root = await mkdtemp(join(tmpdir(), 'dsh-submit-'));
  await mkdir(join(root, 'store'));
  await mkdir(join(root, 'source'));
  const source = join(root, 'source', 'keep.cs');
  await writeFile(source, '// unchanged\n');
  const config = validateConfig({ pythonExecutable: python, repositoryRoot: repo,
    artifactStoreRoot: join(root, 'store'), featureId: 'feature_query_only',
    workspaceRoot: join(root, 'source'), targetMod: 'OwnedConfigService' });
  const commands = [];
  apply({ commands: { register: command => commands.push(command) }, on() {} }, config);
  const submit = commands.find(command => command.name === 'mod-submit');
  const description = 'Validate configuration maxRetries and preserve every unrelated JSON key.';
  const response = await submit.handler({ rawInput: description, signal: new AbortController().signal });
  assert.equal(response.kind, 'success', response.text);
  const shown = JSON.parse(response.text);
  assert.equal(shown.stopped_before, 'feature_spec');
  assert.equal(shown.model_calls_performed, 0);
  assert.equal(shown.implementation_plan_generated, false);
  assert.equal(shown.product_execution_started, false);
  assert.equal(shown.artifacts.request_planning_report.artifact_type, 'request_planning_report');
  const report = JSON.parse(await readFile(shown.artifacts.request_planning_report.path, 'utf8'));
  const brief = JSON.parse(await readFile(shown.artifacts.mod_planning_brief.path, 'utf8'));
  assert.equal(report.data.user_request, description);
  assert.equal(brief.inputs.upstream_artifacts[0].artifact_hash, report.artifact_hash);
  const repeated = await submit.handler({ rawInput: description, signal: new AbortController().signal });
  assert.equal(repeated.text, response.text);
  assert.equal(await readFile(source, 'utf8'), '// unchanged\n');
});

test('submission display preserves clarification rather than pretending execution started', () => {
  const shown = JSON.parse(renderSubmission({ status: 'needs_clarification', feature_id: 'feature_new',
    target_mod: 'OwnedConfigService', stopped_before: 'feature_spec', artifacts: {},
    request_planning_report: { uncertainties: [{ question: 'What behavior should change?' }] },
    mod_planning_brief: { next_action: 'clarify request', blockers: [{ code: 'AMBIGUOUS' }] } }));
  assert.equal(shown.uncertainties[0].question, 'What behavior should change?');
  assert.equal(shown.blockers[0].code, 'AMBIGUOUS');
  assert.equal(shown.product_execution_started, false);
});

test('display keeps a failed or unresolved task separate from query success', () => {
  const row = { run_id: 'r1', terminal: { status: 'partial', terminal_stage: 'generate_patch_proposal' },
    proposal_admitted: false, worker_state: { termination: { code: 'PATCH_AGENT_UPSTREAM_REQUESTED' } },
    source_currentness: 'not_rechecked_by_index', private_payload: 'must not render' };
  const result = JSON.parse(renderResult(data([row]), 'r1'));
  assert.ok(result.display_notice.startsWith('查询已有运行：'));
  assert.equal(result.query_model_calls, 0);
  assert.equal(result.product_execution_started, false);
  assert.equal(result.records[0].state, 'partial');
  assert.equal(result.records[0].proposal_admitted, false);
  assert.equal(result.records[0].source_currentness, 'not_rechecked_by_index');
  assert.ok(!JSON.stringify(result).includes('must not render'));
  assert.throws(() => renderResult(data([]), 'missing'), /RUN_NOT_UNIQUE_OR_MISSING/u);
});

test('real product query reads retained 013 without changing its journal', async () => {
  const repo = resolve(fileURLToPath(new URL('../../..', import.meta.url)));
  const store = join(repo, 'artifacts', 'g1_assisted_findings_context_repaired_27b_fc', 'store');
  const journalPath = join(store, 'cr', 'bd085763297c4de2a004d12a3c1f4e74.json');
  const before = await readFile(journalPath);
  const journal = JSON.parse(before);
  const config = validateConfig({ pythonExecutable: python, repositoryRoot: repo,
    artifactStoreRoot: store, featureId: journal.feature_id });
  const result = await queryBackend(config, { runId: journal.run_id });
  const displayed = JSON.parse(renderResult(result, journal.run_id));
  assert.equal(displayed.records[0].stop_code, 'PATCH_AGENT_UPSTREAM_REQUESTED');
  assert.equal(displayed.records[0].proposal_admitted, false);
  assert.deepEqual(await readFile(journalPath), before);
});

test('review only accepts a run ID and administrator-configured workspace', async () => {
  const config = await fixture('print("unused")');
  assert.throws(() => reviewArguments(config, 'run-one'), /REVIEW_NOT_CONFIGURED/u);
  const ready = validateConfig({ ...config, workspaceRoot: config.repositoryRoot, targetMod: 'OwnedConfigService' });
  const argv = reviewArguments(ready, '--workspace-root=elsewhere');
  assert.equal(argv[2], 'scripts.dsh_review_run');
  assert.equal(argv.at(-1), '--run-id=--workspace-root=elsewhere');
  assert.ok(argv.includes(`--workspace-root=${ready.workspaceRoot}`));
  assert.throws(() => reviewArguments(ready, 'run\nApply'), /INVALID_RUN_ID/u);
  await writeFile(join(config.repositoryRoot, 'scripts', 'dsh_review_run.py'), 'import json\nprint(json.dumps({"read_only":False}))');
  await assert.rejects(reviewBackend(ready, { runId: 'run-one' }), /REVIEW_CONTRACT_INVALID/u);
});

test('review display separates original diff from current source drift and does not make approval', () => {
  const shown = renderReview({ status: 'reviewable_diff', source_currentness: { status: 'source_changed' },
    apply_allowed: false, unified_diff: '--- a/source.cs\n+++ b/source.cs\n+// ``` literal source fence\n' });
  assert.ok(shown.includes('source_changed') && shown.includes('不批准、不执行'));
  assert.ok(shown.includes('````diff\n--- a/source.cs'));
  assert.ok(renderReview({ status: 'no_reviewable_diff', unified_diff: null }).includes('未借用旧 Proposal'));
});
