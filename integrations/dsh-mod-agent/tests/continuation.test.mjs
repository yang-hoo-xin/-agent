import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { apply, validateConfig } from '../index.mjs';

test('normal command shows original rejection and remaining budget without dispatching execution', async () => {
  const root = await mkdtemp(join(tmpdir(), 'dsh-continue-'));
  await mkdir(join(root, 'scripts'));
  await writeFile(join(root, 'scripts', '__init__.py'), '');
  const profile = join(root, 'execution.json');
  await writeFile(profile, '{"arguments":[]}');
  const prepared = { entry: 'initial-findings-continuation', run_id: 'r1', read_only: true,
    status: 'prepared_blocked', model_calls_performed: 0, graph_invoked: false, model_invocation_authorized: false,
    budget: { maximum: 11, consumed: 2, remaining: 9 }, budget_stage: 'requirement_findings',
    blockers: ['PRODUCT_STAGE_MODEL_CALL_BUDGET_EXHAUSTED'],
    cause_chain: { reconstruction_origin: 'offline_exact_input_replay', historical_trace_audit: null,
      first_rejection_reconstruction: { error_code: 'REQUIREMENT_COVERAGE_EDIT_TARGET_SELECTION_INVALID' },
      history_rewritten: false, correction_payload_prepared: true },
    continuation_input_sha256: 'a'.repeat(64), continuation_input: { parent_refs: [],
      model_identity: { model: 'fixture', digest: 'b'.repeat(64), base_url: 'http://127.0.0.1:11434' },
      model_limits: { timeout_seconds: 600, context_window: 32768, output_tokens: 4096 },
      correction_contract: { historical_version: '2', selected_version: '3',
        historical_turn_sha256: 'c'.repeat(64), selected_turn_sha256: 'd'.repeat(64),
        revision_requires_new_approval: true, historical_turn: { source: 'historical-not-for-summary' } },
      next_turn: { role: 'requirement_findings_correction', payload: { source: 'not-for-summary' } } } };
  await writeFile(join(root, 'prepared.json'), JSON.stringify(prepared));
  await writeFile(join(root, 'scripts', 'dsh_run_request.py'), `import json,sys
from pathlib import Path
with Path('calls.jsonl').open('a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')
if '--inspect-run=r1' in sys.argv:
 print(json.dumps({'entry':'run-request-status','run_id':'r1','read_only':True,'model_calls_performed':0,
  'status':'recorded','execution_config_path':str(Path('execution.json').resolve())}))
elif '--prepare-findings-continuation=r1' in sys.argv:
 print(Path('prepared.json').read_text())
else: raise RuntimeError('Execution forbidden in this fixture')
`);
  const config = validateConfig({ repositoryRoot: root, pythonExecutable: process.env.MOD_AGENT_PYTHON,
    artifactStoreRoot: root, featureId: 'f1', executionConfigPath: profile });
  const commands = [];
  apply({ commands: { register: value => commands.push(value) }, on() {} }, config);
  const result = await commands.find(row => row.name === 'mod-continue').handler({ rawInput: 'r1' });
  assert.equal(result.kind, 'error');
  const shown = JSON.parse(result.text);
  assert.deepEqual(shown.budget, { maximum: 11, consumed: 2, remaining: 9 });
  assert.equal(shown.cause_chain.history_rewritten, false);
  assert.equal(shown.cause_chain.reconstruction_origin, 'offline_exact_input_replay');
  assert.equal(shown.model_invocation_authorized, false);
  assert.equal(shown.correction_contract.selected_version, '3');
  assert.equal(shown.correction_contract.revision_requires_new_approval, true);
  assert.equal('historical_turn' in shown.correction_contract, false);
  assert.ok(!result.text.includes('not-for-summary'));
  const calls = (await readFile(join(root, 'calls.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse);
  assert.equal(calls.length, 2);
  assert.ok(calls[1].includes('--prepare-findings-continuation=r1'));
});

test('execution consumes only the displayed same-session scope and never repeats it', async () => {
  const root = await mkdtemp(join(tmpdir(), 'dsh-resume-'));
  await mkdir(join(root, 'scripts'));
  await writeFile(join(root, 'scripts', '__init__.py'), '');
  const profile = join(root, 'execution.json');
  const allocation = join(root, 'allocation.json');
  await writeFile(profile, '{"arguments":[]}');
  await writeFile(allocation, '{"max_execution_seconds":1800}');
  const scope = 'c'.repeat(64);
  await writeFile(join(root, 'scripts', 'dsh_run_request.py'), `import json,sys
from pathlib import Path
if '--inspect-run=r1' in sys.argv:
 print(json.dumps({'entry':'run-request-status','run_id':'r1','read_only':True,'model_calls_performed':0,'status':'recorded','execution_config_path':str(Path('execution.json').resolve())}))
elif '--prepare-findings-continuation=r1' in sys.argv:
 print(json.dumps({'entry':'initial-findings-continuation','run_id':'r1','status':'awaiting_continuation_approval','scope_hash':'${scope}','read_only':True,'model_calls_performed':0}))
elif '--execute-findings-continuation=r1' in sys.argv:
 decision=json.load(sys.stdin)
 with Path('executions.jsonl').open('a') as f: f.write(json.dumps(decision)+'\\n')
 print(json.dumps({'entry':'initial-findings-continuation','run_id':'r1','status':'awaiting_approval','read_only':False,'model_call_count':5,'current_invocation_model_call_count':3}))
else: raise RuntimeError('Unexpected operation')
`);
  const config = validateConfig({ repositoryRoot: root, pythonExecutable: process.env.MOD_AGENT_PYTHON,
    artifactStoreRoot: root, featureId: 'f1', executionConfigPath: profile, findingsContinuationConfigPath: allocation });
  const commands = [];
  apply({ commands: { register: value => commands.push(value) }, on() {} }, config);
  const preview = commands.find(row => row.name === 'mod-continue').handler;
  const resume = commands.find(row => row.name === 'mod-resume').handler;
  const session = {};
  assert.match((await resume({ rawInput: 'reviewer', agent: session })).text, /REVIEW_CONTINUATION_THIS_SESSION_FIRST/u);
  assert.equal((await preview({ rawInput: 'r1', agent: session })).kind, 'success');
  assert.match((await resume({ rawInput: 'reviewer', agent: {} })).text, /REVIEW_CONTINUATION_THIS_SESSION_FIRST/u);
  assert.equal((await resume({ rawInput: 'reviewer', agent: session })).kind, 'success');
  assert.match((await resume({ rawInput: 'reviewer', agent: session })).text, /REVIEW_CONTINUATION_THIS_SESSION_FIRST/u);
  const calls = (await readFile(join(root, 'executions.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse);
  assert.deepEqual(calls, [{ decision: 'approve', reviewer: 'reviewer', scope_hash: scope }]);
});
