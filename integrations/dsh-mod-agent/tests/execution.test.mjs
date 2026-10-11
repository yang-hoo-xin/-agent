import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { apply, executeRequest, executionArguments, renderExecution, validateConfig } from '../index.mjs';

const python = process.env.MOD_AGENT_PYTHON;
assert.ok(python, 'Set MOD_AGENT_PYTHON to the exact test Python executable.');

async function fixture(body) {
  const root = await mkdtemp(join(tmpdir(), 'dsh-run-'));
  await mkdir(join(root, 'scripts'));
  await mkdir(join(root, 'store'));
  await writeFile(join(root, 'scripts', '__init__.py'), '');
  await writeFile(join(root, 'scripts', 'dsh_run_request.py'), body);
  const executionConfigPath = join(root, 'execution.json');
  await writeFile(executionConfigPath, '{"arguments":[]}');
  return validateConfig({ pythonExecutable: python, repositoryRoot: root,
    artifactStoreRoot: join(root, 'store'), featureId: 'read_only_history', executionConfigPath });
}

test('execution uses the fixed bridge and literal stdin; configuration is administrator supplied', async () => {
  const config = await fixture('import json,sys\nprint(json.dumps({"status":"awaiting_approval","received":sys.stdin.read(),"argv":sys.argv[1:]}))');
  const request = '--allow-source-disclosure\n$(not_a_command) & retain Unicode 准星';
  const result = await executeRequest(config, { description: request });
  assert.equal(result.received, request);
  assert.deepEqual(result.argv, [`--execution-config=${config.executionConfigPath}`]);
  assert.equal(executionArguments(config)[2], 'scripts.dsh_run_request');
  assert.throws(() => executionArguments({ ...config, executionConfigPath: undefined }), /RUN_NOT_CONFIGURED/u);
  assert.throws(() => validateConfig({ ...config, executionConfigPath: 'relative.json' }), /ABSOLUTE_EXECUTION/u);
  assert.throws(() => validateConfig({ ...config, runTimeoutMs: 3600001 }), /INVALID_RUN_LIMIT/u);
  assert.throws(() => validateConfig({ ...config, command: 'shell' }), /INVALID_CONFIG/u);
});

for (const exitCode of [1, 2]) test(`real CLI blocked output with exit ${exitCode} remains visible instead of becoming generic backend failure`, async () => {
  const config = await fixture(`import json,sys\nprint(json.dumps({"status":"BLOCKED","reason":"original budget refusal","execution_trace":{"model_requests":0}}))\nsys.exit(${exitCode})`);
  const commands = [];
  apply({ commands: { register: command => commands.push(command) }, on() {} }, config);
  const result = await commands.find(command => command.name === 'mod-run').handler({ rawInput: 'Implement the feature.' });
  assert.equal(result.kind, 'error');
  const shown = JSON.parse(result.text);
  assert.equal(shown.result.reason, 'original budget refusal');
  assert.equal(shown.result.execution_trace.model_requests, 0);
  assert.equal(shown.backend_entry, 'run-request');
  assert.equal('product_execution_started' in shown, false);
});

test('cancellation before dispatch creates no child side effects; invalid output is not a task result', async () => {
  const config = await fixture('from pathlib import Path\nPath("started").write_text("yes")\nprint("{}")');
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(executeRequest(config, { description: 'task', signal: controller.signal }), /RUN_CANCELLED/u);
  await assert.rejects(readFile(join(config.repositoryRoot, 'started')), { code: 'ENOENT' });
  await assert.rejects(executeRequest(config, { description: 'task' }), /RUN_CONTRACT_INVALID/u);
  await assert.rejects(executeRequest(config, { description: 'x'.repeat(32769) }), /RUN_REQUEST_INVALID/u);
});

test('normal product outcome without a top-level status retains its original disposition', async () => {
  const config = await fixture('import json,sys\nprint(json.dumps({"run_id":"r1","run_root":"/run/r1","product_execution_result":{"execution_disposition":"domain_blocked"},"current_stage":"proposal_review"}))\nsys.exit(1)');
  const commands = [];
  apply({ commands: { register: command => commands.push(command) }, on() {} }, config);
  const response = await commands.find(command => command.name === 'mod-run').handler({ rawInput: 'task' });
  assert.equal(response.kind, 'error');
  const result = JSON.parse(response.text).result;
  assert.equal(result.current_stage, 'proposal_review');
  assert.equal(result.product_execution_result.execution_disposition, 'domain_blocked');
  assert.equal('status' in result, false);
});

test('one active product run per plugin instance; query model loop remains disabled', async () => {
  const config = await fixture('import json,time\ntime.sleep(0.25)\nprint(json.dumps({"status":"partial","run_id":"real-child","model_call_count":1}))');
  const commands = [];
  const events = [];
  apply({ commands: { register: command => commands.push(command) }, on: (name, handler) => events.push({ name, handler }) }, config);
  assert.deepEqual(await events[0].handler(), { kind: 'reject' });
  const run = commands.find(command => command.name === 'mod-run');
  const first = run.handler({ rawInput: 'first' });
  const second = await run.handler({ rawInput: 'second' });
  assert.match(second.text, /RUN_ALREADY_ACTIVE/u);
  const shown = JSON.parse((await first).text);
  assert.equal(shown.result.run_id, 'real-child');
  assert.equal(shown.result.status, 'partial');
  const rendered = JSON.parse(renderExecution(shown.result));
  assert.equal(rendered.result.model_call_count, 1);
  assert.equal('approved' in rendered, false);
});
