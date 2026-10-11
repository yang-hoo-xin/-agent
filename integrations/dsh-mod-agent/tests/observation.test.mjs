import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { createHash } from 'node:crypto';
import { apply, observationReply, validateConfig } from '../index.mjs';

test('same-session page observation reaches original exchange through Python; unknown stays unknown', async () => {
  const root = await mkdtemp(join(tmpdir(), 'dsh-observation-'));
  const directory = join(root, 'exchange');
  await mkdir(directory);
  const criterion = 'Restore position';
  const request = { schema_version: 'gtfo_operator_completion_request_v1', request_id: 'operator_test',
    feature_id: 'feature_test', profile_id: 'profile_test', runtime_process_pid: 4242,
    acceptance_criteria: [{ acceptance_criterion: criterion,
      criterion_sha256: createHash('sha256').update(criterion).digest('hex') }], timeout_seconds: 60 };
  const canonical = value => value && !Array.isArray(value) && typeof value === 'object'
    ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]))
    : Array.isArray(value) ? value.map(canonical) : value;
  request.request_sha256 = createHash('sha256').update(JSON.stringify(canonical(request))).digest('hex');
  await writeFile(join(directory, 'operator_test.request.json'), JSON.stringify({ event: 'GTFO_OPERATOR_COMPLETION_REQUIRED', request }));
  const config = validateConfig({ pythonExecutable: process.env.MOD_AGENT_PYTHON,
    repositoryRoot: resolve('.'), artifactStoreRoot: root, featureId: 'feature_test', observationDirectory: directory });
  const commands = [];
  apply({ commands: { register: item => commands.push(item) }, on() {} }, config);
  const command = commands.find(item => item.name === 'mod-observe');
  const agent = {};
  assert.match((await command.handler({ rawInput: '', agent })).text, /Restore position/u);
  assert.match((await command.handler({ rawInput: '仍然有问题', agent })).text, /OBSERVATION_ALL_CRITERIA_REQUIRED/u);
  assert.match((await command.handler({ rawInput: 'tester\n未观察 | 未进入场景', agent: {} })).text, /VIEW_THIS_SESSION_FIRST/u);
  const result = await command.handler({ rawInput: 'tester\n未观察 | 未进入场景', agent });
  assert.equal(result.kind, 'success');
  const payload = JSON.parse(await readFile(join(directory, 'operator_test.response.json'), 'utf8'));
  assert.equal(payload.observations[0].status, 'not_observed');
  assert.equal(payload.request_sha256, request.request_sha256);
  assert.match((await command.handler({ rawInput: 'tester\n通过 | ok', agent })).text, /VIEW_THIS_SESSION_FIRST/u);
});

test('reply grading requires explicit human status; observations stay literal', () => {
  const request = { request_id: 'r', request_sha256: 'h', acceptance_criteria: [{}] };
  assert.throws(() => observationReply(request, 'user\n可能正常'), /EXPLICIT_STATUS/u);
  assert.equal(observationReply(request, 'user\n未通过 | $(literal) --option').observations[0].notes, '$(literal) --option');
});
