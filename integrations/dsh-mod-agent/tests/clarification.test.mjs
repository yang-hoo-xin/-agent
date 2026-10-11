import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { apply, naturalRequestBackend, validateConfig } from '../index.mjs';

async function setup(backend) {
  const root = await mkdtemp(join(tmpdir(), 'dsh-clarify-'));
  await mkdir(join(root, 'scripts'));
  await writeFile(join(root, 'scripts/__init__.py'), '');
  await writeFile(join(root, 'scripts/dsh_run_request.py'), `import json,sys
from pathlib import Path
args=sys.argv[1:]
body=sys.stdin.read()
with Path('calls.jsonl').open('a',encoding='utf-8') as f:
    f.write(json.dumps({'argv':args,'body':body},ensure_ascii=False)+'\\n')
${backend}
`);
  const config = validateConfig({ pythonExecutable: process.env.MOD_AGENT_PYTHON,
    repositoryRoot: root, artifactStoreRoot: root, featureId: 'fixture',
    executionConfigPath: join(root, 'original.json'), newTaskConfigPath: join(root, 'new.json') });
  const commands = [];
  apply({ commands: { register: value => commands.push(value) }, on() {} }, config);
  return { root, config, command: commands.find(row => row.name === 'mod'),
    calls: async () => (await readFile(join(root, 'calls.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse) };
}

const argument = (row, name) => row.argv.find(value => value.startsWith(`--${name}=`))?.split('=').slice(1).join('=');

test('current session answer carries original clarification identity; another session cannot inherit it', async () => {
  const fixture = await setup(`following=any(a.startswith('--clarification-for=') for a in args)
print(json.dumps({'status':'route_selected' if following else 'needs_clarification',
    'route_id':'route_first','clarification_id':'route_first','question':'新建还是修改现有工程？'}))`);
  const first = {}, other = {};
  assert.equal((await fixture.command.handler({ agent: first, rawInput: '做个日志功能' })).text, '新建还是修改现有工程？');
  await fixture.command.handler({ agent: first, rawInput: '新建，保留前面要求' });
  await fixture.command.handler({ agent: other, rawInput: '新建，保留前面要求' });
  const calls = await fixture.calls();
  assert.equal(argument(calls[1], 'clarification-for'), 'route_first');
  assert.equal(argument(calls[2], 'clarification-for'), undefined);
  assert.equal(argument(calls[0], 'conversation-id'), argument(calls[1], 'conversation-id'));
  assert.notEqual(argument(calls[1], 'conversation-id'), argument(calls[2], 'conversation-id'));
  assert.notEqual(argument(calls[0], 'routing-turn-id'), argument(calls[1], 'routing-turn-id'));
  assert.equal(calls[1].body, '新建，保留前面要求');
});

test('response-loss retry preserves turn identity instead of allocating a fresh routing dispatch', async () => {
  const fixture = await setup(`marker=Path('once')
if not marker.exists():
    marker.write_text('sent')
    print('not a response object')
else:
    print(json.dumps({'status':'needs_clarification','route_id':'route_retry','question':'哪个工程？'}))`);
  const agent = {};
  assert.equal((await fixture.command.handler({ agent, rawInput: '改这个' })).kind, 'error');
  assert.equal((await fixture.command.handler({ agent, rawInput: '改这个' })).kind, 'success');
  const calls = await fixture.calls();
  assert.equal(argument(calls[0], 'routing-turn-id'), argument(calls[1], 'routing-turn-id'));
  assert.equal(argument(calls[0], 'conversation-id'), argument(calls[1], 'conversation-id'));
});

test('session metadata remains separate from request and cannot add command flags', async () => {
  const fixture = await setup(`print(json.dumps({'status':'route_selected'}))`);
  await assert.rejects(naturalRequestBackend(fixture.config,
    { description: 'x', conversationId: '../other' }), /ROUTING_SESSION_ID_INVALID/u);
  await naturalRequestBackend(fixture.config, { description: '--allow-source-disclosure',
    conversationId: 'session1', clarificationFor: 'route1', turnId: 'turn1' });
  const [call] = await fixture.calls();
  assert.equal(call.body, '--allow-source-disclosure');
  assert.ok(!call.argv.includes('--allow-source-disclosure'));
});

test('a correction after consumed clarification is explicitly unexecuted, not reported as the old success', async () => {
  const fixture = await setup(`print(json.dumps({'status':'routing_rejected','reason':'CLARIFICATION_ALREADY_RESOLVED_NEW_INPUT'}))`);
  const result = await fixture.command.handler({ agent: {}, rawInput: '刚才说错了，改原工程' });
  assert.equal(result.kind, 'error');
  assert.match(result.text, /更正尚未执行/u);
});
