import { spawn } from 'node:child_process';
import { stat } from 'node:fs/promises';
import { isAbsolute, join } from 'node:path';

export const name = 'controlled-mod-agent';
export const inject = ['commands'];

function requiredText(value, label, max = 300) {
  if (typeof value !== 'string' || !value.trim() || value.length > max || /[\r\n\0]/u.test(value)) {
    throw new Error(`INVALID_${label}`);
  }
  return value;
}

export function validateConfig(config) {
  const keys = ['pythonExecutable', 'repositoryRoot', 'artifactStoreRoot', 'featureId', 'timeoutMs', 'maxOutputBytes',
    'workspaceRoot', 'targetMod'];
  if (!config || Object.keys(config).some(key => !keys.includes(key))) throw new Error('INVALID_CONFIG');
  for (const key of keys.slice(0, 3)) {
    requiredText(config[key], key, 4096);
    if (!isAbsolute(config[key])) throw new Error(`ABSOLUTE_${key}_REQUIRED`);
  }
  requiredText(config.featureId, 'FEATURE_ID');
  if ((config.workspaceRoot === undefined) !== (config.targetMod === undefined)) throw new Error('SUBMIT_CONFIG_INCOMPLETE');
  if (config.workspaceRoot !== undefined) {
    requiredText(config.workspaceRoot, 'WORKSPACE_ROOT', 4096);
    if (!isAbsolute(config.workspaceRoot)) throw new Error('ABSOLUTE_WORKSPACE_ROOT_REQUIRED');
    requiredText(config.targetMod, 'TARGET_MOD');
  }
  const result = { timeoutMs: 30000, maxOutputBytes: 2 * 1024 * 1024, ...config };
  if (!Number.isInteger(result.timeoutMs) || result.timeoutMs < 1 || result.timeoutMs > 120000
      || !Number.isInteger(result.maxOutputBytes) || result.maxOutputBytes < 1024 || result.maxOutputBytes > 8 * 1024 * 1024) {
    throw new Error('INVALID_LIMIT');
  }
  return Object.freeze(result);
}

export function backendArguments(config, runId) {
  const argv = ['-B', '-m', 'scripts.engineering_cognition', '--view', 'verification-claims',
    '--query', 'patch-execution', '--artifact-store-root', config.artifactStoreRoot,
    `--feature-id=${config.featureId}`];
  if (runId !== undefined) argv.push(`--run-id=${requiredText(runId, 'RUN_ID')}`);
  return argv;
}

async function runBackend(config, argv, { signal, input, operation = 'QUERY' } = {}) {
  if (signal?.aborted) throw new Error(`${operation}_CANCELLED`);
  return new Promise((resolve, reject) => {
    const child = spawn(config.pythonExecutable, argv, {
      cwd: config.repositoryRoot, shell: false, windowsHide: true,
      stdio: [input === undefined ? 'ignore' : 'pipe', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    });
    let size = 0;
    const chunks = [];
    let failure;
    const stop = code => { failure ??= new Error(code); child.kill(); };
    const abort = () => stop(`${operation}_CANCELLED`);
    const timer = setTimeout(() => stop(`${operation}_TIMEOUT`), config.timeoutMs);
    signal?.addEventListener('abort', abort, { once: true });
    const cleanup = () => { clearTimeout(timer); signal?.removeEventListener('abort', abort); };
    child.stdout.on('data', chunk => {
      size += chunk.length;
      if (size > config.maxOutputBytes) stop(`${operation}_OUTPUT_LIMIT`);
      else chunks.push(chunk);
    });
    child.stderr.on('data', () => {}); // Diagnostics may contain local paths; do not put them in the session.
    child.on('error', () => { cleanup(); reject(new Error(`${operation}_START_FAILED`)); });
    child.on('close', code => {
      cleanup();
      if (failure || code !== 0) reject(failure ?? new Error(`${operation}_BACKEND_FAILED`));
      else resolve(Buffer.concat(chunks).toString('utf8'));
    });
    if (input !== undefined) {
      child.stdin.on('error', () => {}); // Process failure is reported by close/error above.
      child.stdin.end(input, 'utf8');
    }
    if (signal?.aborted) abort();
  });
}

export async function queryBackend(config, { runId, signal } = {}) {
  await stat(join(config.repositoryRoot, 'scripts', 'engineering_cognition.py'));
  if (!(await stat(config.artifactStoreRoot)).isDirectory()) throw new Error('STORE_UNAVAILABLE');
  const raw = await runBackend(config, backendArguments(config, runId), { signal });
  const value = JSON.parse(raw);
  const data = value?.data;
  if (data?.read_only !== true || data?.model_calls_performed !== 0
      || data?.verifier_executions_performed !== 0 || data?.product_source_writes_performed !== false
      || !Array.isArray(data.attempts)) throw new Error('QUERY_CONTRACT_INVALID');
  return data;
}

export function reviewArguments(config, runId) {
  if (config.workspaceRoot === undefined) throw new Error('REVIEW_NOT_CONFIGURED');
  return ['-B', '-m', 'scripts.dsh_review_run', `--workspace-root=${config.workspaceRoot}`,
    `--artifact-store-root=${config.artifactStoreRoot}`, `--feature-id=${config.featureId}`,
    `--run-id=${requiredText(runId, 'RUN_ID')}`];
}

export async function reviewBackend(config, { runId, signal }) {
  const argv = reviewArguments(config, runId);
  await stat(join(config.repositoryRoot, 'scripts', 'dsh_review_run.py'));
  const result = JSON.parse(await runBackend(config, argv, { signal, operation: 'REVIEW' }));
  if (result?.entry !== 'review-run' || result?.read_only !== true || result?.run_id !== runId
      || result?.feature_id !== config.featureId || result?.query_model_calls !== 0
      || result?.query_verifier_executions !== 0 || result?.product_source_writes_performed !== false
      || result?.artifact_writes_performed !== false || result?.approval_created !== false
      || result?.apply_allowed !== false || result?.product_execution_started !== false
      || !['reviewable_diff', 'no_reviewable_diff', 'review_unavailable'].includes(result?.status)
      || (result.status === 'reviewable_diff' && typeof result.unified_diff !== 'string')) {
    throw new Error('REVIEW_CONTRACT_INVALID');
  }
  return result;
}

export function renderReview(result) {
  const { unified_diff: diff, ...metadata } = result;
  const notice = result.status === 'no_reviewable_diff' ? '本次运行没有可审查的新 diff；未借用旧 Proposal。'
    : result.status === 'review_unavailable' ? '本次运行的精确审查记录不完整或身份未通过核验。'
      : '查看本次运行原始 diff：历史 Review 不等于当前可 Apply；本命令不批准、不执行、不重新验证行为。';
  const summary = JSON.stringify({ display_notice: notice, ...metadata }, null, 2);
  if (typeof diff !== 'string') return summary;
  const longest = Math.max(0, ...Array.from(diff.matchAll(/`+/gu), match => match[0].length));
  const fence = '`'.repeat(Math.max(3, longest + 1));
  return `${summary}\n\n${fence}diff\n${diff}\n${fence}`;
}

export function submissionArguments(config) {
  if (config.workspaceRoot === undefined || config.targetMod === undefined) throw new Error('SUBMIT_NOT_CONFIGURED');
  return ['-B', '-m', 'scripts.dsh_prepare_request', `--workspace-root=${config.workspaceRoot}`,
    `--artifact-store-root=${config.artifactStoreRoot}`, `--target-mod=${config.targetMod}`];
}

export async function submitRequest(config, { description, signal }) {
  if (typeof description !== 'string' || !description.trim() || description.includes('\0')
      || Buffer.byteLength(description, 'utf8') > 32768) throw new Error('SUBMIT_REQUEST_INVALID');
  const argv = submissionArguments(config);
  await stat(join(config.repositoryRoot, 'scripts', 'dsh_prepare_request.py'));
  const raw = await runBackend(config, argv, { signal, input: description, operation: 'SUBMIT' });
  const result = JSON.parse(raw);
  if (result?.entry !== 'plan-request' || result?.stopped_before !== 'feature_spec'
      || typeof result?.feature_id !== 'string' || !result.feature_id
      || result?.model_calls_performed !== 0 || result?.verifier_executions_performed !== 0
      || result?.product_source_writes_performed !== false || result?.artifact_writes_performed !== true
      || result?.implementation_plan_generated !== false || result?.product_execution_started !== false
      || result?.feature_id !== result?.request_planning_report?.feature_id
      || result?.feature_id !== result?.mod_planning_brief?.feature_id
      || !result?.artifacts?.request_planning_report || !result?.artifacts?.mod_planning_brief) {
    throw new Error('SUBMIT_CONTRACT_INVALID');
  }
  return result;
}

export function renderSubmission(result) {
  return JSON.stringify({
    display_notice: '需求已交给原后端并保存准备结果。尚未生成FeatureSpec、实施Plan或代码，也没有启动模型。',
    status: result.status, feature_id: result.feature_id, target_mod: result.target_mod,
    stopped_before: result.stopped_before,
    next_action: result.mod_planning_brief.next_action,
    uncertainties: result.request_planning_report.uncertainties,
    blockers: result.mod_planning_brief.blockers,
    artifacts: result.artifacts, artifact_writes_performed: true,
    model_calls_performed: 0, product_source_writes_performed: false,
    implementation_plan_generated: false, product_execution_started: false,
  }, null, 2);
}

function summary(row) {
  return {
    run_id: row.run_id, feature_id: row.feature_id,
    state: row.terminal?.status ?? row.status ?? 'unknown',
    stage: row.terminal?.terminal_stage ?? 'unknown',
    stop_code: row.worker_state?.termination?.code ?? row.failure?.code ?? null,
    proposal_admitted: row.proposal_admitted ?? null,
    reference_integrity: row.integrity,
    source_currentness: row.source_currentness,
    counts: row.budget_and_counts_recorded,
    semantic_success: 'not_inferred_from_process_or_tool_success',
  };
}

export function renderResult(data, runId) {
  const selected = runId === undefined ? data.attempts : data.attempts.filter(row => row.run_id === runId);
  if (runId !== undefined && selected.length !== 1) throw new Error('RUN_NOT_UNIQUE_OR_MISSING');
  const rows = selected.slice(-20).map(summary);
  return JSON.stringify({
    display_notice: '查询已有运行：本次没有启动模型、重新修订或重新验证。下方状态与调用次数属于已保存的运行。',
    query_model_calls: 0, query_verifier_executions: 0, product_execution_started: false,
    read_only: true, backend_authority: 'original_journal_and_artifacts',
    matching_runs: selected.length, shown_runs: rows.length, truncated: selected.length > rows.length,
    records: rows }, null, 2);
}

export function apply(ctx, configuration) {
  const config = validateConfig(configuration);
  // DSH's stock loop provides the session factory. Keep that factory while
  // rejecting its model steps; human commands use the separate commands path.
  ctx.on('agent/pre-step', async () => ({ kind: 'reject' }));
  for (const command of [
    { name: 'mod-runs', description: '查看已配置Mod任务的运行记录，不调用模型或执行任务。' },
    { name: 'mod-status', description: '按已列出的run_id查看原后端状态；不把工具成功当作Mod完成。', input: { hint: '<run_id>' } },
  ]) {
    ctx.commands.register({ ...command,
      async handler({ rawInput, signal }) {
        try {
          const text = rawInput.trim();
          const runId = command.name === 'mod-status' ? requiredText(text, 'RUN_ID') : undefined;
          if (command.name === 'mod-runs' && text) throw new Error('NO_ARGUMENTS_EXPECTED');
          const data = await queryBackend(config, { runId, signal });
          return { kind: 'success', text: renderResult(data, runId) };
        } catch (error) {
          const code = /^[A-Z_]+$/u.test(error.message) ? error.message : 'QUERY_FAILED';
          return { kind: 'error', text: code };
        }
      },
    });
  }
  ctx.commands.register({ name: 'mod-review',
    description: '查看该run_id自己的待审diff、原验证和当前源码差异；不批准或执行。',
    input: { hint: '<run_id>' },
    async handler({ rawInput, signal }) {
      try {
        const runId = requiredText(rawInput.trim(), 'RUN_ID');
        return { kind: 'success', text: renderReview(await reviewBackend(config, { runId, signal })) };
      } catch (error) {
        const code = /^[A-Z_]+$/u.test(error.message) ? error.message : 'REVIEW_FAILED';
        return { kind: 'error', text: `${code}：未取得本次运行的可审查diff；未批准、未执行。` };
      }
    },
  });
  ctx.commands.register({ name: 'mod-submit',
    description: '提交自然语言需求，保存原后端准备结果与澄清项；不调用模型、不执行修改。',
    input: { hint: '<需求正文>' },
    async handler({ rawInput, signal }) {
      try {
        const result = await submitRequest(config, { description: rawInput, signal });
        return { kind: 'success', text: renderSubmission(result) };
      } catch (error) {
        const code = /^[A-Z_]+$/u.test(error.message) ? error.message : 'SUBMIT_FAILED';
        return { kind: 'error', text: `${code}：未确认准备完整完成；可重提相同需求核对原Artifact。未启动模型或产品执行。` };
      }
    },
  });
}
