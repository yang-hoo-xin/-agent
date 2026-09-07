import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { apply, backendArguments, queryBackend, renderResult, validateConfig } from '../index.mjs';

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
  assert.deepEqual(commands.map(command => command.name), ['mod-runs', 'mod-status']);
  assert.equal((await commands[1].handler({ rawInput: '', signal: new AbortController().signal })).kind, 'error');
  const failed = await commands[0].handler({ rawInput: '', signal: new AbortController().signal });
  assert.deepEqual(failed, { kind: 'error', text: 'QUERY_BACKEND_FAILED' });
});

test('display keeps a failed or unresolved task separate from query success', () => {
  const row = { run_id: 'r1', terminal: { status: 'partial', terminal_stage: 'generate_patch_proposal' },
    proposal_admitted: false, worker_state: { termination: { code: 'PATCH_AGENT_UPSTREAM_REQUESTED' } },
    source_currentness: 'not_rechecked_by_index', private_payload: 'must not render' };
  const result = JSON.parse(renderResult(data([row]), 'r1'));
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
