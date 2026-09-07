import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const clientPath = fileURLToPath(new URL('../client.js', import.meta.url));

function loadBundle(path, require = () => assert.fail('This module needs no value imports')) {
  let registration;
  vm.runInNewContext(readFileSync(path, 'utf8'), {
    window: { __ModuleLoader__: { load(value) { registration = value; } } },
    console, setTimeout, clearTimeout, URL, AbortController,
  }, { filename: path });
  assert.ok(registration?.factory);
  return registration.factory(require);
}

function capture(plugin) {
  const views = [];
  const events = [];
  const providers = [];
  const activations = [];
  plugin.apply({ uiConversation: {
    views: { register: definition => views.push(definition) },
    events: { register: definition => events.push(definition) },
    binding: binding => ({ activate: target => activations.push([binding.sessionId, target]) }),
  }, uiSession: { provide: provider => providers.push(provider) } });
  return { views, events, providers, activations };
}

const event = (seq, type, data) => ({ seq, type, data, time: '2026-09-07T00:00:00.000Z' });
const run = event(1, 'command/run', { commandId: 'query-one', name: 'mod-status', args: 'run-013', source: { kind: 'user' } });
const done = event(2, 'command/done', { commandId: 'query-one', kind: 'success', text: '{\n  "status": "blocked"\n}' });

test('plugin contributes activity only and preserves ordinary renderer ownership', () => {
  const plugin = loadBundle(clientPath);
  const captured = capture(plugin);
  assert.equal(captured.views.length, 1);
  assert.notEqual(captured.views[0].target, 'chat');
  assert.equal(captured.events.length, 1);
  assert.deepEqual(Array.from(plugin.inject), ['uiConversation', 'uiSession']);
  assert.equal(Object.keys(captured.providers[0].resolve({ sessionId: 'session-one' })).length, 0);
  assert.deepEqual(captured.activations, [['session-one', plugin.target]]);
  const definition = captured.events[0];
  const context = { key: 'stable-key', id: 'query-one', start: { event: run } };
  context.state = definition.start(context, { event: run });
  const builder = captured.views[0].create();
  assert.equal(builder.replace({ nodes: [definition.buildViewNode(context)] }), false);
  context.state = definition.update(context, { event: done });
  assert.equal(builder.apply({ upserts: [definition.buildViewNode(context)] }), true);
  assert.equal(definition.buildViewNode(context).data.hasResult, true);
  assert.equal('text' in definition.buildViewNode(context).data, false);
  assert.equal(definition.match(event(3, 'command/run', { commandId: 'other', name: 'unrelated' })), null);
  assert.equal(definition.buildViewNode({ key: 'orphan', id: 'orphan' }), null);
  context.state = definition.update(context, { event: { ...done, data: { ...done.data, text: '' } } });
  assert.equal(builder.apply({ upserts: [definition.buildViewNode(context)] }), false);
});

function packageRoot(pnpm, name) {
  for (const entry of readdirSync(pnpm, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const root = join(pnpm, entry.name, 'node_modules', ...name.split('/'));
    if (!existsSync(join(root, 'package.json'))) continue;
    const manifest = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
    if (manifest.name !== name) continue;
    assert.equal(manifest.version, '0.1.2-rc.1');
    return root;
  }
  assert.fail(`Published dependency not installed: ${name}`);
}

test('published Conversation assembler activates original chat command content without a model turn',
  { skip: !process.env.DSH_RUNTIME_NODE_MODULES }, () => {
    const pnpm = join(process.env.DSH_RUNTIME_NODE_MODULES, '.pnpm');
    const native = createRequire(join(pnpm, 'offline-client-test.cjs'));
    const react = native('react');
    // Browser service notifications and visual primitives are plumbing doubles;
    // the event engine, original Chat builder, node definitions and phase owner
    // below execute the installed official bundle unchanged.
    const externals = {
      '@deepseek-ai/cordis': native('@deepseek-ai/cordis'),
      '@deepseek-ai/dsh-client-store': {
        notifySubscribers(listeners) { for (const listener of listeners) listener(); },
      },
      '@deepseek-ai/dsh-client-ui-primitives': {},
      '@deepseek-ai/dsh-client-ui-slots': {},
      react, 'react/jsx-runtime': native('react/jsx-runtime'), 'react-dom': native('react-dom'),
    };
    const require = name => {
      assert.ok(name in externals, `Unexpected client value import: ${name}`);
      return externals[name];
    };
    const conversation = loadBundle(join(packageRoot(pnpm, '@deepseek-ai/dsh-client-ui-conversation'), 'lib/client.js'), require);
    const chat = loadBundle(join(packageRoot(pnpm, '@deepseek-ai/dsh-client-ui-chat'), 'lib/client.js'), require);
    const views = [];
    const events = [];
    const renderers = [];
    const afterOfficialRegistration = new Error('captured official registration');
    assert.throws(() => chat.apply({
      uiConversation: { views: { register: value => views.push(value) },
        events: { register: value => events.push(value), registerFallback() {} } },
      slots: { inject: (_name, register) => register(), register: (options, component) => renderers.push({ options, component }) },
      uiSession: { provide() { throw afterOfficialRegistration; } },
    }), error => error === afterOfficialRegistration);
    const originalChat = views.find(view => view.target === 'chat');
    assert.ok(originalChat && events.some(value => value.kind === 'command'));
    assert.ok(renderers.some(row => row.options.name === 'conversation.chat.node' && row.options.key === 'command'));
    const registries = () => [{ entries: () => events, fallbackEntry: () => undefined }, { entries: () => views }];
    const before = new conversation.ConversationNodeAssembler(...registries());
    const entries = [run, done].map(value => ({ event: value }));
    before.replaceWindow(entries, false);
    before.activateTarget('chat');
    before.flush();
    const priorSnapshot = before.snapshot('chat');
    assert.equal(priorSnapshot.order.length, 1);
    assert.equal(priorSnapshot.nodes.get(priorSnapshot.order[0]).data.outcome.text, done.data.text);
    assert.equal(originalChat.isActive(priorSnapshot), false);
    const session = { blank: true, awaitingFirstTurn: true, running: false, promptAttempted: false };
    assert.equal(conversation.conversationPhase(session, { activeTargets: before.activityTargets() }), 'blank');
    const local = loadBundle(clientPath);
    const localCapture = capture(local);
    views.push(...localCapture.views);
    events.push(...localCapture.events);
    const after = new conversation.ConversationNodeAssembler(...registries());
    after.replaceWindow(entries, false);
    after.activateTarget('chat');
    after.activateTarget(local.target);
    after.flush();
    assert.equal(conversation.conversationPhase(session, { activeTargets: after.activityTargets() }), 'active');
    const finalChat = after.snapshot('chat');
    assert.equal(finalChat.order.length, 1, 'Do not duplicate the official command card');
    assert.equal(finalChat.nodes.get(finalChat.order[0]).data.outcome.text, done.data.text);
    assert.deepEqual(entries.map(row => row.event.type), ['command/run', 'command/done']);
  });
