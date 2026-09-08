import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, mkdir, readFile, writeFile, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { apply } from '../index.mjs';

const python = process.env.MOD_AGENT_PYTHON;
assert.ok(python, 'Set MOD_AGENT_PYTHON to the exact selected Python.');
const repo = resolve(fileURLToPath(new URL('../../..', import.meta.url)));
const setup = `
import json, sys, socket
from pathlib import Path
from tests.unit.test_fresh_planning_continuation import _inputs, _local_patch_adapter, _patch_request
from src.mod_agent.fresh_planning_continuation import run_fresh_patch_continuation
from src.mod_agent.local_entry import make_exact_no_write_dry_run_factory
socket.socket.connect = lambda *args: (_ for _ in ()).throw(AssertionError('No network in synthetic preparation'))
inputs = _inputs(Path(sys.argv[1]) / 'case')
project = inputs.behavior.parent / 'Synthetic.csproj'
project.write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>')
adapter, _ = _local_patch_adapter(inputs)
result = run_fresh_patch_continuation(_patch_request(inputs), patch_change_factory=adapter, dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace))
assert result.status == 'terminal', result.to_dict()
print(json.dumps({'runId':result.run_id,'featureId':result.feature_id,'workspaceRoot':str(inputs.workspace.resolve()),'artifactStoreRoot':str(inputs.store.root.resolve()),'sourceFile':str(inputs.behavior.resolve())}))
`;

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'dsh-approve-'));
  const prepared = spawnSync(python, ['-X', 'utf8', '-B', '-c', setup, root],
    { cwd: repo, windowsHide: true, encoding: 'utf8', timeout: 60000 });
  assert.equal(prepared.status, 0, prepared.stderr);
  const facts = JSON.parse(prepared.stdout);
  const isolatedRoot = join(root, 'isolation');
  await mkdir(isolatedRoot);
  const commands = new Map();
  apply({ commands: { register: command => commands.set(command.name, command) }, on() {} }, {
    pythonExecutable: python, repositoryRoot: repo, artifactStoreRoot: facts.artifactStoreRoot,
    workspaceRoot: facts.workspaceRoot, featureId: facts.featureId, targetMod: 'SyntheticMod', isolatedRoot,
  });
  const agent = {};
  const run = (name, rawInput, selectedAgent = agent, signal = new AbortController().signal) =>
    commands.get(name).handler({ rawInput, agent: selectedAgent, signal });
  return { ...facts, root, isolatedRoot, run, agent };
}

function reviewMetadata(result) {
  assert.equal(result.kind, 'success', result.text);
  return JSON.parse(result.text.slice(0, result.text.indexOf('\n\n```')));
}

test('human session review and approval reaches original CLI/Graph/applier in a real Python process', async () => {
  const f = await fixture();
  const original = await readFile(f.sourceFile);
  const preview = reviewMetadata(await f.run('mod-review', f.runId));
  assert.ok(preview.unified_diff_sha256);
  assert.equal(preview.apply_preparation.stop_before, 'build');
  assert.deepEqual(await readdir(f.isolatedRoot), []);
  const approved = await f.run('mod-approve', 'Offline Human');
  assert.equal(approved.kind, 'success', approved.text);
  const result = JSON.parse(approved.text);
  assert.equal(result.status, 'applied_in_isolation');
  assert.equal(result.diff_hash, preview.diff_hash);
  assert.equal(result.isolated_workspace, preview.apply_preparation.write_target);
  assert.equal(result.model_calls_performed, 0);
  assert.equal(result.builds_performed, 0);
  assert.equal(result.runtime_executions_performed, 0);
  assert.deepEqual(result.next_nodes, ['build']);
  assert.deepEqual(await readFile(f.sourceFile), original);
  const recorded = JSON.parse(await readFile(result.isolated_apply_result.path, 'utf8'));
  assert.equal(recorded.data.human_semantic_decision.reviewer_identity, 'Offline Human');
  assert.equal(recorded.data.human_semantic_decision.diff_hash, preview.diff_hash);
  assert.equal(recorded.data.actual_write_performed, true);
  const reused = await f.run('mod-approve', 'Offline Human');
  assert.equal(reused.kind, 'error');
  assert.ok(reused.text.includes('REVIEW_THIS_SESSION_FIRST'));
  assert.equal((await readdir(f.isolatedRoot)).length, 1);
});

test('another session cannot consume the displayed binding, and rejection does not create output', async () => {
  const f = await fixture();
  const original = await readFile(f.sourceFile);
  await f.run('mod-review', f.runId);
  const other = await f.run('mod-approve', 'Other Human', {});
  assert.equal(other.kind, 'error');
  assert.ok(other.text.includes('REVIEW_THIS_SESSION_FIRST'));
  const rejected = await f.run('mod-reject', 'Offline Human');
  assert.equal(rejected.kind, 'success', rejected.text);
  const result = JSON.parse(rejected.text);
  assert.equal(result.status, 'rejected');
  assert.equal(result.artifact_writes_performed, false);
  assert.equal(result.product_source_writes_performed, false);
  assert.deepEqual(await readdir(f.isolatedRoot), []);
  assert.deepEqual(await readFile(f.sourceFile), original);
});

test('cancellation before dispatch and source drift cannot apply the old reviewed code', async () => {
  const f = await fixture();
  await f.run('mod-review', f.runId);
  const cancelled = new AbortController();
  cancelled.abort();
  const stopped = await f.run('mod-approve', 'Offline Human', f.agent, cancelled.signal);
  assert.equal(stopped.kind, 'error');
  assert.ok(stopped.text.includes('APPLY_CANCELLED_BEFORE_START'));
  assert.deepEqual(await readdir(f.isolatedRoot), []);
  await writeFile(f.sourceFile, Buffer.concat([await readFile(f.sourceFile), Buffer.from('\n// user edit\n')]));
  const current = await readFile(f.sourceFile);
  const stale = await f.run('mod-approve', 'Offline Human');
  assert.equal(stale.kind, 'error', stale.text);
  assert.equal(JSON.parse(stale.text).reason, 'APPLY_REVIEW_SOURCE_CHANGED');
  assert.deepEqual(await readdir(f.isolatedRoot), []);
  assert.deepEqual(await readFile(f.sourceFile), current);
});
