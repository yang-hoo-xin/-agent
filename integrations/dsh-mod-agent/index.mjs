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
  const keys = ['pythonExecutable', 'repositoryRoot', 'artifactStoreRoot', 'featureId', 'timeoutMs', 'maxOutputBytes'];
  if (!config || Object.keys(config).some(key => !keys.includes(key))) throw new Error('INVALID_CONFIG');
  for (const key of keys.slice(0, 3)) {
    requiredText(config[key], key, 4096);
    if (!isAbsolute(config[key])) throw new Error(`ABSOLUTE_${key}_REQUIRED`);
  }
  requiredText(config.featureId, 'FEATURE_ID');
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

export async function queryBackend(config, { runId, signal } = {}) {
  if (signal?.aborted) throw new Error('QUERY_CANCELLED');
  await stat(join(config.repositoryRoot, 'scripts', 'engineering_cognition.py'));
  if (!(await stat(config.artifactStoreRoot)).isDirectory()) throw new Error('STORE_UNAVAILABLE');
  const raw = await new Promise((resolve, reject) => {
    const child = spawn(config.pythonExecutable, backendArguments(config, runId), {
      cwd: config.repositoryRoot, shell: false, windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    });
    let size = 0;
    const chunks = [];
    let failure;
    const stop = code => { failure ??= new Error(code); child.kill(); };
    const abort = () => stop('QUERY_CANCELLED');
    const timer = setTimeout(() => stop('QUERY_TIMEOUT'), config.timeoutMs);
    signal?.addEventListener('abort', abort, { once: true });
    const cleanup = () => { clearTimeout(timer); signal?.removeEventListener('abort', abort); };
    child.stdout.on('data', chunk => {
      size += chunk.length;
      if (size > config.maxOutputBytes) stop('QUERY_OUTPUT_LIMIT');
      else chunks.push(chunk);
    });
    child.stderr.on('data', () => {}); // Diagnostics may contain local paths; do not put them in the session.
    child.on('error', () => { cleanup(); reject(new Error('QUERY_START_FAILED')); });
    child.on('close', code => {
      cleanup();
      if (failure || code !== 0) reject(failure ?? new Error('QUERY_BACKEND_FAILED'));
      else resolve(Buffer.concat(chunks).toString('utf8'));
    });
    if (signal?.aborted) abort();
  });
  const value = JSON.parse(raw);
  const data = value?.data;
  if (data?.read_only !== true || data?.model_calls_performed !== 0
      || data?.verifier_executions_performed !== 0 || data?.product_source_writes_performed !== false
      || !Array.isArray(data.attempts)) throw new Error('QUERY_CONTRACT_INVALID');
  return data;
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
}
