import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { readFile, stat } from 'node:fs/promises';
import { isAbsolute, join } from 'node:path';

export const name = 'controlled-mod-agent';
export const inject = ['commands'];
const deliveryInFlight = new Set(); // One host process; durable replay protection stays with the original resume owner.

function requiredText(value, label, max = 300) {
  if (typeof value !== 'string' || !value.trim() || value.length > max || /[\r\n\0]/u.test(value)) {
    throw new Error(`INVALID_${label}`);
  }
  return value;
}

export function validateConfig(config) {
  const keys = ['pythonExecutable', 'repositoryRoot', 'artifactStoreRoot', 'featureId', 'timeoutMs', 'maxOutputBytes',
    'workspaceRoot', 'targetMod', 'isolatedRoot', 'executionConfigPath', 'runTimeoutMs', 'deliveryRoot',
    'investigationConfigPath', 'memoryStoreRoot', 'observationDirectory', 'runtimeConfigPath', 'newTaskConfigPath', 'findingsContinuationConfigPath'];
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
  if (config.isolatedRoot !== undefined) {
    if (config.workspaceRoot === undefined) throw new Error('APPLY_CONFIG_INCOMPLETE');
    requiredText(config.isolatedRoot, 'ISOLATED_ROOT', 4096);
    if (!isAbsolute(config.isolatedRoot)) throw new Error('ABSOLUTE_ISOLATED_ROOT_REQUIRED');
  }
  if (config.executionConfigPath !== undefined) {
    requiredText(config.executionConfigPath, 'EXECUTION_CONFIG_PATH', 4096);
    if (!isAbsolute(config.executionConfigPath)) throw new Error('ABSOLUTE_EXECUTION_CONFIG_PATH_REQUIRED');
  }
  if (config.deliveryRoot !== undefined) {
    requiredText(config.deliveryRoot, 'DELIVERY_ROOT', 4096);
    if (!isAbsolute(config.deliveryRoot)) throw new Error('ABSOLUTE_DELIVERY_ROOT_REQUIRED');
    if (config.executionConfigPath === undefined) throw new Error('DELIVERY_CONFIG_INCOMPLETE');
  }
  for (const key of ['investigationConfigPath', 'memoryStoreRoot', 'observationDirectory', 'runtimeConfigPath', 'newTaskConfigPath', 'findingsContinuationConfigPath']) {
    if (config[key] === undefined) continue;
    requiredText(config[key], key, 4096);
    if (!isAbsolute(config[key])) throw new Error('ABSOLUTE_MEMORY_OR_INVESTIGATION_PATH_REQUIRED');
  }
  const result = { timeoutMs: 30000, runTimeoutMs: 1200000, maxOutputBytes: 2 * 1024 * 1024, ...config };
  if (!Number.isInteger(result.timeoutMs) || result.timeoutMs < 1 || result.timeoutMs > 120000
      || !Number.isInteger(result.maxOutputBytes) || result.maxOutputBytes < 1024 || result.maxOutputBytes > 8 * 1024 * 1024) {
    throw new Error('INVALID_LIMIT');
  }
  if (!Number.isInteger(result.runTimeoutMs) || result.runTimeoutMs < 1 || result.runTimeoutMs > 3600000) {
    throw new Error('INVALID_RUN_LIMIT');
  }
  return Object.freeze(result);
}

export function backendArguments(config, runId, investigation = false) {
  if (investigation && runId === undefined) throw new Error('INVESTIGATION_RUN_REQUIRED');
  const argv = ['-B', '-m', 'scripts.engineering_cognition', '--view', 'verification-claims',
    '--query', investigation ? 'patch-investigation' : 'patch-execution', '--artifact-store-root', config.artifactStoreRoot,
    `--feature-id=${config.featureId}`];
  if (runId !== undefined) argv.push(`--run-id=${requiredText(runId, 'RUN_ID')}`);
  return argv;
}

async function runBackend(config, argv, { signal, input, operation = 'QUERY', acceptedExitCodes = [0] } = {}) {
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
      if (failure || !acceptedExitCodes.includes(code)) reject(failure ?? new Error(`${operation}_BACKEND_FAILED`));
      else resolve(Buffer.concat(chunks).toString('utf8'));
    });
    if (input !== undefined) {
      child.stdin.on('error', () => {}); // Process failure is reported by close/error above.
      child.stdin.end(input, 'utf8');
    }
    if (signal?.aborted) abort();
  });
}

export async function queryBackend(config, { runId, signal, investigation = false } = {}) {
  await stat(join(config.repositoryRoot, 'scripts', 'engineering_cognition.py'));
  if (!(await stat(config.artifactStoreRoot)).isDirectory()) throw new Error('STORE_UNAVAILABLE');
  const raw = await runBackend(config, backendArguments(config, runId, investigation), { signal });
  const value = JSON.parse(raw);
  const data = value?.data;
  if (data?.read_only !== true || data?.model_calls_performed !== 0
      || data?.verifier_executions_performed !== 0 || data?.product_source_writes_performed !== false
      || !Array.isArray(data.attempts)) throw new Error('QUERY_CONTRACT_INVALID');
  return data;
}

export async function investigationSelection(config, runId) {
  if (config.investigationConfigPath === undefined) throw new Error('INVESTIGATION_NOT_CONFIGURED');
  const selected = JSON.parse(await readFile(config.investigationConfigPath, 'utf8'));
  if (!selected || Array.isArray(selected)
      || Object.keys(selected).some(key => !['artifactStoreRoot', 'featureId', 'runId', 'currentContext'].includes(key))) {
    throw new Error('INVESTIGATION_CONFIG_INVALID');
  }
  requiredText(selected.artifactStoreRoot, 'ARTIFACT_STORE_ROOT', 4096);
  requiredText(selected.featureId, 'FEATURE_ID');
  requiredText(selected.runId, 'RUN_ID');
  if (!isAbsolute(selected.artifactStoreRoot)) throw new Error('INVESTIGATION_STORE_MUST_BE_ABSOLUTE');
  if (runId !== undefined && runId !== selected.runId) throw new Error('INVESTIGATION_RUN_MISMATCH');
  return { ...config, artifactStoreRoot: selected.artifactStoreRoot, featureId: selected.featureId, runId: selected.runId };
}

export function renderInvestigation(attempt) {
  const chain = attempt.investigation_chain;
  if (chain?.authority !== 'non_authoritative' || !Array.isArray(chain.stages) || chain.stages.length !== 6) {
    throw new Error('INVESTIGATION_CONTRACT_INVALID');
  }
  const lines = ['本次调查读取原任务材料与实际请求，未运行模型或验证器。未知项保留为未知；报告不授予修改权限。',
    `任务：${attempt.run_id}`, ''];
  for (const stage of chain.stages) {
    lines.push(`**${stage.title}**`, `状态：${stage.status}`, stage.conclusion,
      `下一核验：${stage.next_verification}`, '');
  }
  lines.push('完整结构化证据：', '```json', JSON.stringify({ run_id: attempt.run_id,
    journal_ref: attempt.journal_ref, investigation_chain: chain }, null, 2), '```');
  return lines.join('\n');
}

export async function memoryBackend(config, { action, query, signal, runId, execution = false } = {}) {
  if (config.memoryStoreRoot === undefined) throw new Error('MEMORY_NOT_CONFIGURED');
  if (!['remember', 'query'].includes(action)) throw new Error('MEMORY_ACTION_INVALID');
  const argv = ['-B', '-m', 'scripts.dsh_task_memory', `--memory-root=${config.memoryStoreRoot}`, `--action=${action}`];
  if (execution) {
    if (action !== 'remember' || config.executionConfigPath === undefined) throw new Error('MEMORY_EXECUTION_CONFIG_REQUIRED');
    argv.push(`--execution-config=${config.executionConfigPath}`, `--run-id=${requiredText(runId, 'RUN_ID')}`);
  } else {
    if (config.investigationConfigPath === undefined) throw new Error('INVESTIGATION_NOT_CONFIGURED');
    argv.push(`--investigation-config=${config.investigationConfigPath}`);
  }
  if (action === 'query' && (typeof query !== 'string' || !query.trim() || Buffer.byteLength(query, 'utf8') > 32768)) {
    throw new Error('MEMORY_QUERY_INVALID');
  }
  await stat(join(config.repositoryRoot, 'scripts', 'dsh_task_memory.py'));
  const result = JSON.parse(await runBackend(config, argv, { signal, input: action === 'query' ? query : undefined,
    operation: 'MEMORY', acceptedExitCodes: [0, 2] }));
  if (result.entry !== 'dsh-task-memory' || result.model_calls_performed !== 0
      || result.product_source_writes_performed !== false || result.authority !== 'planning_only'
      || (action === 'query' && (result.read_only !== true || result.artifact_writes_performed !== false))) {
    throw new Error('MEMORY_CONTRACT_INVALID');
  }
  return result;
}

export function reviewArguments(config, runId, operationId) {
  if (config.workspaceRoot === undefined) throw new Error('REVIEW_NOT_CONFIGURED');
  const argv = ['-B', '-m', 'scripts.dsh_review_run', `--workspace-root=${config.workspaceRoot}`,
    `--artifact-store-root=${config.artifactStoreRoot}`, `--feature-id=${config.featureId}`,
    `--run-id=${requiredText(runId, 'RUN_ID')}`];
  if (config.isolatedRoot !== undefined) argv.push(`--isolated-root=${config.isolatedRoot}`,
    `--operation-id=${requiredText(operationId, 'OPERATION_ID')}`);
  return argv;
}

export async function reviewBackend(config, { runId, signal, operationId }) {
  const argv = reviewArguments(config, runId, operationId);
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

export function approvalArguments(config, runId) {
  if (config.isolatedRoot === undefined) throw new Error('APPLY_NOT_CONFIGURED');
  return ['-B', '-m', 'src.mod_agent.cli', 'apply-patch', '--confirm', '--human-decision-stdin',
    `--workspace-root=${config.workspaceRoot}`, `--artifact-store-root=${config.artifactStoreRoot}`,
    `--feature-id=${config.featureId}`, `--run-id=${requiredText(runId, 'RUN_ID')}`,
    `--isolated-root=${config.isolatedRoot}`];
}

export async function approveBackend(config, { runId, binding, decision, reviewerIdentity, signal }) {
  if (!['approve', 'reject'].includes(decision)) throw new Error('HUMAN_DECISION_INVALID');
  requiredText(reviewerIdentity, 'REVIEWER_IDENTITY', 200);
  if (!binding || binding.run_id !== runId || binding.feature_id !== config.featureId
      || !binding.human_semantic_decision_binding) throw new Error('DISPLAYED_BINDING_REQUIRED');
  const input = JSON.stringify({ displayed_binding: binding, human_semantic_decision: {
    ...binding.human_semantic_decision_binding, decision, reviewer_identity: reviewerIdentity,
  } });
  const result = JSON.parse(await runBackend(config, approvalArguments(config, runId),
    { signal, input, operation: 'APPLY' }));
  if (result?.entry !== 'apply-patch' || result.run_id !== runId || result.feature_id !== config.featureId
      || result.model_calls_performed !== 0 || result.builds_performed !== 0
      || result.runtime_executions_performed !== 0 || result.stopped_before !== 'build'
      || !['applied_in_isolation', 'rejected', 'blocked'].includes(result.status)) throw new Error('APPLY_CONTRACT_INVALID');
  if (result.status === 'applied_in_isolation' && (result.product_source_writes_performed !== true
      || result.source_workspace_written !== false || result.diff_hash !== binding.diff_hash
      || result.isolated_workspace !== binding.isolated_workspace)) throw new Error('APPLY_CONTRACT_INVALID');
  if (result.status === 'rejected' && (result.product_source_writes_performed !== false
      || result.artifact_writes_performed !== false || result.isolated_workspace_created !== false)) throw new Error('APPLY_CONTRACT_INVALID');
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

export function executionArguments(config) {
  if (config.executionConfigPath === undefined) throw new Error('RUN_NOT_CONFIGURED');
  return ['-B', '-m', 'scripts.dsh_run_request', `--execution-config=${config.executionConfigPath}`];
}

export async function observationBackend(config, { response, signal, runId } = {}) {
  let directory = config.observationDirectory;
  if (runId !== undefined) {
    const record = await inspectPublicRun(config, { runId, signal });
    if (record.status !== 'recorded') throw new Error('OBSERVATION_RUN_NOT_FOUND');
    directory = join(record.run_root, 'operator_completion');
  }
  if (directory === undefined) throw new Error('OBSERVATION_NOT_CONFIGURED');
  const argv = ['-B', '-m', 'scripts.dsh_observe_run', `--exchange-directory=${directory}`];
  if (response !== undefined) argv.push('--submit');
  const result = JSON.parse(await runBackend(config, argv, { signal, operation: 'OBSERVATION',
    input: response === undefined ? undefined : JSON.stringify(response), acceptedExitCodes: [0, 2] }));
  if (result.entry !== 'dsh-observation' || result.model_calls_performed !== 0
      || result.runtime_success_claimed !== false) throw new Error('OBSERVATION_CONTRACT_INVALID');
  return result;
}

export async function runtimeBackend(config, { runId, action, decision, signal }) {
  if (config.newTaskConfigPath) {
    const record = await inspectPublicRun(config, { runId, signal });
    if (record.execution_config_path) config = { ...config, executionConfigPath: record.execution_config_path };
  }
  if (!config.runtimeConfigPath || !config.executionConfigPath || !config.deliveryRoot) throw new Error('RUNTIME_NOT_CONFIGURED');
  const argv = ['-B', '-m', 'scripts.dsh_runtime_run', `--execution-config=${config.executionConfigPath}`,
    `--delivery-root=${config.deliveryRoot}`, `--runtime-config=${config.runtimeConfigPath}`,
    `--run-id=${requiredText(runId, 'RUN_ID')}`, `--action=${action}`];
  const result = JSON.parse(await runBackend(action === 'execute' ? { ...config, timeoutMs: config.runTimeoutMs } : config,
    argv, { signal, input: decision ? JSON.stringify(decision) : undefined,
      operation: 'RUNTIME', acceptedExitCodes: [0, 2] }));
  if (result.entry !== 'dsh-runtime' || result.run_id !== runId || result.model_calls_performed !== 0
      || result.runtime_success_claimed !== false) throw new Error('RUNTIME_CONTRACT_INVALID');
  return result;
}

export function observationReply(request, rawInput) {
  const lines = rawInput.trim().split(/\r?\n/u);
  const observedBy = requiredText(lines.shift(), 'OBSERVER', 200);
  if (lines.length !== request.acceptance_criteria.length) throw new Error('OBSERVATION_ALL_CRITERIA_REQUIRED');
  const statuses = new Map([['通过', 'passed'], ['未通过', 'failed'], ['未观察', 'not_observed']]);
  const observations = lines.map(line => {
    const separator = line.indexOf('|');
    const status = statuses.get(line.slice(0, separator).trim());
    const notes = line.slice(separator + 1).trim();
    if (separator < 0 || !status || !notes) throw new Error('OBSERVATION_EXPLICIT_STATUS_REQUIRED');
    return { status, notes };
  });
  return { request_id: request.request_id, request_sha256: request.request_sha256,
    observed_by: observedBy, observations };
}

export async function executeRequest(config, { description, signal, newTask = false }) {
  if (newTask && config.newTaskConfigPath) config = { ...config, executionConfigPath: config.newTaskConfigPath };
  if (typeof description !== 'string' || !description.trim() || description.includes('\0')
      || Buffer.byteLength(description, 'utf8') > 32768) throw new Error('RUN_REQUEST_INVALID');
  const argv = executionArguments(config);
  if (newTask) argv.push('--new-task');
  await stat(join(config.repositoryRoot, 'scripts', 'dsh_run_request.py'));
  if (!(await stat(config.executionConfigPath)).isFile()) throw new Error('RUN_CONFIG_UNAVAILABLE');
  const raw = await runBackend({ ...config, timeoutMs: config.runTimeoutMs }, argv,
    { signal, input: description, operation: 'RUN', acceptedExitCodes: [0, 1, 2] });
  const result = JSON.parse(raw);
  const structuredOutcome = result?.product_execution_result?.execution_disposition;
  if (!result || Array.isArray(result)
      || (typeof result.status !== 'string' && !(typeof structuredOutcome === 'string'
        && typeof result.run_id === 'string' && typeof result.run_root === 'string'))) throw new Error('RUN_CONTRACT_INVALID');
  return result;
}

export function parseNewProjectInput(rawInput) {
  const value = rawInput.trim();
  if (value.startsWith('--independent ')) {
    const separator = value.indexOf(' -- ', '--independent '.length);
    if (separator < 0) throw new Error('NEW_PROJECT_NAME_AND_DESCRIPTION_REQUIRED');
    const displayName = requiredText(value.slice('--independent '.length, separator).trim(), 'PROJECT_NAME', 200);
    const description = value.slice(separator + 4);
    if (!description.trim() || description.includes('\0') || Buffer.byteLength(description, 'utf8') > 32768) {
      throw new Error('RUN_REQUEST_INVALID');
    }
    return { action: 'initialize', displayName, description };
  }
  for (const action of ['start', 'preview']) {
    if (value.startsWith(`--${action} `)) {
      const runId = value.slice(action.length + 3).trim();
      if (!/^[A-Za-z0-9][A-Za-z0-9_.-]*$/u.test(runId)) throw new Error('NEW_PROJECT_RUN_ID_INVALID');
      return { action, runId };
    }
  }
  if (/^--(?:independent|start|preview)(?:\s|$)/u.test(value)) throw new Error('NEW_PROJECT_COMMAND_INVALID');
  return null;
}

export async function naturalRequestBackend(config, { description, activeRunId, parentExecutionConfig,
  conversationId, clarificationFor, turnId, signal }) {
  if (typeof description !== 'string' || !description.trim() || description.includes('\0')
      || Buffer.byteLength(description, 'utf8') > 32768) throw new Error('RUN_REQUEST_INVALID');
  const selected = { ...config, executionConfigPath: config.newTaskConfigPath ?? config.executionConfigPath };
  const argv = [...executionArguments(selected), '--route-request'];
  // 为什么要有它：会话与turn标识只用于关联记录，不能混入用户正文或被解释成执行参数。
  for (const [flag, value] of [['conversation-id', conversationId], ['clarification-for', clarificationFor], ['routing-turn-id', turnId]]) {
    if (value !== undefined) {
      if (typeof value !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u.test(value)) throw new Error('ROUTING_SESSION_ID_INVALID');
      argv.push(`--${flag}=${value}`);
    }
  }
  if (activeRunId !== undefined) {
    if (!/^[A-Za-z0-9][A-Za-z0-9_.-]*$/u.test(activeRunId)) throw new Error('NEW_PROJECT_RUN_ID_INVALID');
    argv.push(`--active-run-id=${activeRunId}`);
  }
  if (parentExecutionConfig !== undefined) {
    requiredText(parentExecutionConfig, 'PARENT_EXECUTION_CONFIG', 4096);
    if (activeRunId === undefined || !isAbsolute(parentExecutionConfig)) throw new Error('PARENT_EXECUTION_CONFIG_INVALID');
    argv.push(`--parent-execution-config=${parentExecutionConfig}`);
  }
  if (config.findingsContinuationConfigPath) argv.push(`--findings-allocation-config=${config.findingsContinuationConfigPath}`);
  if (config.deliveryRoot) argv.push(`--followup-delivery-root=${config.deliveryRoot}`);
  const result = JSON.parse(await runBackend({ ...selected, timeoutMs: config.runTimeoutMs }, argv,
    { signal, input: description, operation: 'NATURAL_REQUEST', acceptedExitCodes: [0, 1, 2] }));
  if (!result || typeof result.status !== 'string') throw new Error('RUN_CONTRACT_INVALID');
  return result;
}

export async function newProjectBackend(config, { selection, signal }) {
  const selected = { ...config, executionConfigPath: config.newTaskConfigPath ?? config.executionConfigPath };
  const argv = executionArguments(selected);
  if (selection.action === 'initialize') argv.push(`--initialize-project-name=${selection.displayName}`);
  else if (selection.action === 'start' && config.findingsContinuationConfigPath) {
    argv.push(`--advance-task=${selection.runId}`, `--findings-allocation-config=${config.findingsContinuationConfigPath}`);
  }
  else argv.push(`--${selection.action}-project=${selection.runId}`);
  const result = JSON.parse(await runBackend({ ...selected, timeoutMs: config.runTimeoutMs }, argv,
    { signal, input: selection.description, operation: 'NEW_PROJECT', acceptedExitCodes: [0, 1, 2] }));
  if (result.status === 'DSH_INPUT_ERROR') return result;
  if (selection.action !== 'start' && (result.entry !== 'dsh-new-project'
      || result.model_calls_performed !== 0 || result.product_execution_started !== false
      || result.build_performed !== false || result.game_deployment_performed !== false)) {
    throw new Error('NEW_PROJECT_CONTRACT_INVALID');
  }
  return result;
}

export function renderExecution(result, backendEntry = 'run-request') {
  const fields = ['status', 'run_id', 'request_id', 'feature_id', 'run_root', 'current_stage',
    'model_call_count', 'model_call_budget', 'graph_invoked', 'actual_write_performed',
    'canonical_source_unchanged', 'blockers', 'reason', 'stopped_before', 'diff_hash',
    'unified_diff', 'human_semantic_decision_binding', 'approval_recorded', 'artifacts', 'execution_trace',
    'continuation_root', 'request_interpretation_revision'];
  const shown = Object.fromEntries(fields.filter(key => key in result).map(key => [key, result[key]]));
  if (result.product_execution_result) shown.product_execution_result = {
    execution_disposition: result.product_execution_result.execution_disposition,
    failure_stage: result.product_execution_result.failure_stage,
    blockers: result.product_execution_result.blockers,
  };
  return JSON.stringify({
    display_notice: `已调用原Mod Agent的${backendEntry}入口。下方保留原后端结果；模型调用、验证和停止原因以该结果为准。未自动批准、部署或启动游戏。`,
    backend_entry: backendEntry,
    original_result_path: result.continuation_root || result.run_root
      ? join(result.continuation_root ?? result.run_root, 'run_result.json') : null,
    result: shown,
  }, null, 2);
}

export async function inspectPublicRun(config, { runId, signal }) {
  const found = [];
  let missing;
  for (const path of new Set([config.executionConfigPath, config.newTaskConfigPath].filter(Boolean))) {
    const selected = { ...config, executionConfigPath: path };
    const argv = [...executionArguments(selected), `--inspect-run=${requiredText(runId, 'RUN_ID')}`];
    const result = JSON.parse(await runBackend(selected, argv, { signal, operation: 'STATUS', acceptedExitCodes: [0, 2] }));
    if (result.entry !== 'run-request-status' || result.read_only !== true || result.run_id !== runId
        || result.model_calls_performed !== 0 || !['recorded', 'not_found'].includes(result.status)) throw new Error('STATUS_CONTRACT_INVALID');
    // 为什么要有它：已准备但尚未启动的任务没有manifest，后端验证的配置仍是可恢复身份，且须参与重复身份检查。
    if (result.status === 'recorded' || result.execution_config_path) found.push(result); else missing = result;
  }
  if (found.length > 1) throw new Error('TASK_IDENTITY_NOT_UNIQUE');
  if (!found.length && !missing) throw new Error('RUN_NOT_CONFIGURED');
  return found[0] ?? missing;
}

export function deliveryArguments(config, runId, action) {
  if (config.deliveryRoot === undefined || config.executionConfigPath === undefined) throw new Error('DELIVERY_NOT_CONFIGURED');
  if (!['preview', 'status', 'deliver', 'reject'].includes(action)) throw new Error('DELIVERY_ACTION_INVALID');
  return ['-B', '-m', 'scripts.dsh_deliver_run', `--config-path=${config.executionConfigPath}`,
    `--delivery-root=${config.deliveryRoot}`, `--run-id=${requiredText(runId, 'RUN_ID')}`, `--action=${action}`,
    ...(['deliver', 'reject'].includes(action) ? ['--decision-stdin'] : [])];
}

export async function findingsContinuationBackend(config, { runId, signal, decision }) {
  const record = await inspectPublicRun(config, { runId, signal });
  if (record.status !== 'recorded' || !record.execution_config_path) throw new Error('CONTINUATION_ORIGINAL_CONFIG_REQUIRED');
  const selected = { ...config, executionConfigPath: record.execution_config_path };
  const argv = [...executionArguments(selected), `--${decision ? 'execute' : 'prepare'}-findings-continuation=${requiredText(runId, 'RUN_ID')}`];
  if (config.findingsContinuationConfigPath) argv.push(`--findings-allocation-config=${config.findingsContinuationConfigPath}`);
  if (decision) {
    if (!config.findingsContinuationConfigPath) throw new Error('CONTINUATION_ALLOCATION_NOT_CONFIGURED');
    argv.push('--decision-stdin');
  }
  let timeoutMs = config.timeoutMs;
  if (decision) {
    const allocation = JSON.parse(await readFile(config.findingsContinuationConfigPath, 'utf8'));
    if (!Number.isInteger(allocation.max_execution_seconds) || allocation.max_execution_seconds < 1
        || allocation.max_execution_seconds > 3600) throw new Error('CONTINUATION_TIME_SCOPE_INVALID');
    timeoutMs = Math.min(config.runTimeoutMs, allocation.max_execution_seconds * 1000);
  }
  const result = JSON.parse(await runBackend({ ...selected, timeoutMs }, argv,
    { signal, operation: 'CONTINUATION', input: decision ? JSON.stringify(decision) : undefined, acceptedExitCodes: [0, 2] }));
  if (result.status === 'DSH_INPUT_ERROR') throw new Error('CONTINUATION_INPUT_CHANGED_OR_UNAVAILABLE');
  if (result.entry !== 'initial-findings-continuation' || result.run_id !== runId
      || (!decision && (result.read_only !== true || result.model_calls_performed !== 0))
      || (result.continuation_input && (result.graph_invoked !== false || result.model_invocation_authorized !== false))) {
    throw new Error('CONTINUATION_CONTRACT_INVALID');
  }
  return result;
}

export function renderFindingsContinuation(result) {
  if (!result.continuation_input) return JSON.stringify({
    display_notice: result.read_only ? '读取已记录的续接结果，本次没有新的模型调用。' : '已调用原产品Graph；累计预算包含之前的调用，未重领任务额度。',
    ...result,
  }, null, 2);
  return JSON.stringify({
    display_notice: '读取原任务并准备纠正输入，没有启动模型或重新运行Graph。历史记录保持原样；离线重建与原实时Trace分别标明。',
    entry: result.entry, run_id: result.run_id, status: result.status,
    budget: result.budget, budget_stage: result.budget_stage, blockers: result.blockers,
    effective_budget_if_approved: result.effective_budget, execution_scope: result.execution_scope, scope_hash: result.scope_hash,
    model_identity: Object.fromEntries(['model', 'digest', 'base_url'].map(key => [key, result.continuation_input.model_identity[key]])),
    model_limits: result.continuation_input.model_limits,
    correction_contract: result.continuation_input.correction_contract
      ? Object.fromEntries(Object.entries(result.continuation_input.correction_contract).filter(([key]) => key !== 'historical_turn')) : undefined,
    cause_chain: result.cause_chain, continuation_input_sha256: result.continuation_input_sha256,
    original_input_refs: result.continuation_input.parent_refs,
    next_model_role: result.continuation_input.next_turn.role,
    model_calls_performed: 0, product_source_writes_performed: false, model_invocation_authorized: false,
    next_action: result.blockers.includes('PRODUCT_STAGE_MODEL_CALL_BUDGET_EXHAUSTED')
      ? '当前Findings阶段额度已用完。需先明确阶段额度安排及新的调用授权，不能把剩余额度重置为新任务预算。'
      : result.status === 'awaiting_continuation_approval'
        ? '核对模型、阶段分配和本段时间范围后，/mod-resume 后接审查人姓名才执行；到原精确diff审查处停止。补查仍可能耗尽Findings余量，未保证任务成功。'
        : '续接输入待审查；准备结果不授予新的模型调用权限。',
  }, null, 2);
}

export async function deliveryBackend(config, { runId, action, decision, signal }) {
  if (config.newTaskConfigPath) {
    const record = await inspectPublicRun(config, { runId, signal });
    if (record.execution_config_path) config = { ...config, executionConfigPath: record.execution_config_path };
  }
  const argv = deliveryArguments(config, runId, action);
  const readOnly = ['preview', 'status'].includes(action);
  if (!readOnly && (!decision || decision.decision !== (action === 'deliver' ? 'approve' : 'reject')
      || typeof decision.scope_hash !== 'string' || !/^sha256:[a-f0-9]{64}$/u.test(decision.scope_hash))) {
    throw new Error('DISPLAYED_DELIVERY_REQUIRED');
  }
  if (!readOnly) requiredText(decision.reviewer, 'REVIEWER_IDENTITY', 200);
  await stat(join(config.repositoryRoot, 'scripts', 'dsh_deliver_run.py'));
  const result = JSON.parse(await runBackend(readOnly ? config : { ...config, timeoutMs: config.runTimeoutMs }, argv,
    { signal, input: readOnly ? undefined : JSON.stringify(decision), operation: 'DELIVERY', acceptedExitCodes: [0, 2] }));
  if (result?.entry !== 'dsh-delivery' || result.run_id !== runId || typeof result.status !== 'string'
      || result.model_calls_performed !== 0 || result.runtime_executions_performed !== 0
      || (readOnly && (result.read_only !== true || result.product_source_writes_performed !== false || result.builds_performed !== 0))) {
    throw new Error('DELIVERY_CONTRACT_INVALID');
  }
  if (result.receipt !== undefined || ['delivered', 'rejected'].includes(result.status)) {
    const receipt = result.receipt;
    if (!receipt || receipt.status !== result.status || receipt.run_id !== runId
        || receipt.scope_hash !== result.scope_hash || receipt.delivery_path !== result.delivery_path) {
      throw new Error('DELIVERY_CONTRACT_INVALID');
    }
    if (result.status === 'delivered' && (receipt.apply_result?.status !== 'applied_in_isolation'
        || receipt.build_result?.status !== 'built' || typeof receipt.build_result?.build_result?.path !== 'string'
        || !/^[a-f0-9]{64}$/u.test(receipt.build_result?.build_result?.artifact_hash)
        || typeof receipt.delivery_ref?.path !== 'string' || !/^[a-f0-9]{64}$/u.test(receipt.delivery_ref?.sha256))) {
      throw new Error('DELIVERY_CONTRACT_INVALID');
    }
    if (result.status === 'rejected' && (result.product_source_writes_performed !== false || result.builds_performed !== 0
        || receipt.apply_result?.status !== 'rejected' || receipt.build_result)) throw new Error('DELIVERY_CONTRACT_INVALID');
  }
  return result;
}

export function renderDelivery(result) {
  const { unified_diff: diff, ...metadata } = result;
  const notice = result.status === 'delivered'
    ? '正式构建与交付副本已完成。以下为原续接结果和保存位置；本次未进入游戏。'
    : result.status === 'rejected' ? '这份修改已拒绝。以下为原续接记录。'
      : result.read_only && result.status === 'awaiting_approval'
        ? '请核对完整差异、隔离写入位置、构建命令和交付位置。/mod-deliver 后接审查人姓名，表示批准本页这份差异、正式构建及交付副本；/mod-decline 后接姓名表示拒绝。预览没有执行修改或构建。'
        : '续接尚未确认交付，请查看具体状态与已发生的执行事实；不会重新生成代码或自动重试。';
  const summary = JSON.stringify({ display_notice: notice, ...metadata }, null, 2);
  if (typeof diff !== 'string') return summary;
  const longest = Math.max(0, ...Array.from(diff.matchAll(/`+/gu), match => match[0].length));
  const fence = '`'.repeat(Math.max(3, longest + 1));
  return `${summary}\n\n${fence}diff\n${diff}\n${fence}`;
}

function renderTaskStatus(record, attempts = [], delivery) {
  const result = record.result;
  const initial = record.original_result ?? result;
  const manifest = record.manifest;
  const continuationStatus = delivery?.status === 'not_applicable'
    || (delivery?.status === 'blocked' && !delivery.receipt)
    ? undefined : delivery?.status;
  return JSON.stringify({
    display_notice: '读取原任务记录；没有启动新模型、编译或修订。任务与Patch子尝试分别列出。',
    read_only: true, query_model_calls: 0, run_id: record.run_id, run_root: record.run_root,
    recorded_status: initial?.status ?? initial?.product_execution_result?.execution_disposition ?? manifest?.status ?? null,
    current_status: continuationStatus ?? result?.status ?? result?.product_execution_result?.execution_disposition ?? manifest?.status ?? null,
    recorded_stage: initial?.current_stage ?? null,
    ...(record.continuation ? { model_continuation: {
      status: record.continuation.status, result_ref: record.continuation.result_ref,
      prior_model_call_count: record.continuation.prior_model_call_count,
      current_invocation_model_call_count: record.continuation.current_invocation_model_call_count,
      history_rewritten: false,
    } } : {}),
    current_stage: delivery?.receipt?.build_result ? 'build' : result?.current_stage ?? null,
    model: manifest?.model ?? null,
    model_call_count: result?.model_call_count ?? manifest?.model_call_count ?? null,
    model_call_budget: result?.model_call_budget ?? null,
    blockers: result?.blockers ?? result?.product_execution_result?.blockers ?? [],
    artifacts: result?.artifacts ?? {}, execution_trace: result?.execution_trace ?? manifest?.execution_trace ?? null,
    patch_attempts: attempts.map(summary),
    original_result_path: result ? join(record.run_root, 'run_result.json') : null,
    original_manifest_path: manifest ? join(record.run_root, 'run_manifest.json') : null,
    ...(delivery ? { delivery_continuation: delivery } : {}),
  }, null, 2);
}

async function configuredPublicRunId(config) {
  const profile = JSON.parse(await readFile(config.executionConfigPath, 'utf8'));
  const args = profile.arguments;
  const index = args.indexOf('--run-id');
  return index >= 0 ? args[index + 1] : args.find(value => value.startsWith('--run-id='))?.slice('--run-id='.length);
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
  const displayed = new WeakMap();
  const displayedDelivery = new WeakMap();
  const displayedObservation = new WeakMap();
  const displayedRuntime = new WeakMap();
  const displayedContinuation = new WeakMap();
  const naturalTaskContext = new WeakMap();
  const naturalConversationContext = new WeakMap();
  let executionRunning = false;
  const completedRunBindings = new Map(); // UI selection only; Python revalidates every query/review.
  let mostRecentRun;
  function bindPublicResult(result) {
    if (typeof result?.run_id === 'string' && typeof result?.feature_id === 'string'
        && typeof result?.run_root === 'string' && isAbsolute(result.run_root)) {
      const selected = { ...config, featureId: result.feature_id,
        workspaceRoot: result.run_root, artifactStoreRoot: join(result.run_root, 'a') };
      completedRunBindings.set(result.run_id, selected);
      mostRecentRun = result.run_id;
      return selected;
    }
    return null;
  }
  async function taskRecord(runId, signal) {
    const record = await inspectPublicRun(config, { runId, signal });
    if (record.status !== 'recorded') return null;
    const selected = bindPublicResult(record.result);
    const attempts = selected ? (await queryBackend(selected, { signal })).attempts : [];
    for (const row of attempts) completedRunBindings.set(row.run_id, selected);
    let delivery;
    if (config.deliveryRoot !== undefined && (record.execution_config_path || runId === await configuredPublicRunId(config))) {
      delivery = record.result?.status === 'awaiting_approval'
        ? await deliveryBackend(config, { runId, action: 'status', signal })
        : { status: 'not_applicable', reason: 'DSH_DELIVERY_PENDING_PUBLIC_RESULT_REQUIRED', read_only: true };
    }
    return { record, attempts, delivery };
  }
  // DSH's stock loop provides the session factory. Keep that factory while
  // rejecting its model steps; human commands use the separate commands path.
  ctx.on('agent/pre-step', async () => ({ kind: 'reject' }));
  ctx.commands.register({ name: 'mod-continue', description: '查原任务完整原因链，准备初始Findings纠正输入并继承预算；不调用模型。',
    input: { hint: '<原任务run_id>' },
    async handler({ rawInput, signal, agent }) {
      const pending = {};
      try {
        if (agent && typeof agent === 'object') displayedContinuation.set(agent, pending);
        const result = await findingsContinuationBackend(config, { runId: requiredText(rawInput.trim(), 'RUN_ID'), signal });
        if (agent && typeof agent === 'object') {
          if (displayedContinuation.get(agent) !== pending) throw new Error('REVIEW_SUPERSEDED');
          displayedContinuation.delete(agent);
          if (result.status === 'awaiting_continuation_approval' && /^[a-f0-9]{64}$/u.test(result.scope_hash)) {
            displayedContinuation.set(agent, { runId: result.run_id, scopeHash: result.scope_hash });
          }
        }
        return { kind: result.status === 'prepared_blocked' ? 'error' : 'success', text: renderFindingsContinuation(result) };
      } catch (error) {
        if (agent && displayedContinuation.get(agent) === pending) displayedContinuation.delete(agent);
        const code = /^[A-Z_]+$/u.test(error.message) ? error.message : 'CONTINUATION_PREPARATION_FAILED';
        return { kind: 'error', text: `${code}：未获得合法续接输入，未调用模型或改写历史。` };
      }
    } });
  ctx.commands.register({ name: 'mod-resume', description: '批准本会话显示的阶段分配和调用范围，续接原Findings并进入原Graph；不自动Apply。',
    input: { hint: '<审查人姓名>' },
    async handler({ rawInput, signal, agent }) {
      if (executionRunning) return { kind: 'error', text: 'RUN_ALREADY_ACTIVE' };
      try {
        const selected = agent && displayedContinuation.get(agent);
        if (!selected) throw new Error('REVIEW_CONTINUATION_THIS_SESSION_FIRST');
        const reviewer = requiredText(rawInput.trim(), 'REVIEWER_IDENTITY', 200);
        if (signal?.aborted) throw new Error('CONTINUATION_CANCELLED_BEFORE_START');
        executionRunning = true;
        displayedContinuation.delete(agent);
        const result = await findingsContinuationBackend(config, { runId: selected.runId,
          decision: { decision: 'approve', reviewer, scope_hash: selected.scopeHash } });
        bindPublicResult(result);
        return { kind: result.status === 'awaiting_approval' ? 'success' : 'error', text: renderFindingsContinuation(result) };
      } catch (error) {
        const code = /^[A-Z_]+$/u.test(error.message) ? error.message : 'CONTINUATION_FAILED';
        return { kind: 'error', text: `${code}：核对原任务的续接记录及已用额度，不会自动重跑。` };
      } finally { executionRunning = false; }
    } });
  ctx.commands.register({ name: 'mod-observe',
    description: '查看当前待答观察；在同一会话按显示顺序提交观察，直接结束原运行器等待。',
    input: { hint: '<留空查看；答复首行姓名，其后每项一行：通过/未通过/未观察 | 具体观察>' },
    async handler({ rawInput, signal, agent }) {
      try {
        if (!agent || typeof agent !== 'object') throw new Error('OBSERVATION_SESSION_REQUIRED');
        if (!rawInput.trim() || /^[A-Za-z0-9][A-Za-z0-9_.-]*$/u.test(rawInput.trim())) {
          displayedObservation.delete(agent);
          const runId = rawInput.trim() || undefined;
          const result = await observationBackend(config, { signal, runId });
          if (result.status === 'blocked') return { kind: 'error', text: JSON.stringify(result, null, 2) };
          if (!result.requests?.length) return { kind: 'success', text: '当前没有尚在有效期内的待答观察。' };
          if (result.requests.length !== 1) throw new Error('OBSERVATION_REQUEST_NOT_UNIQUE');
          const request = result.requests[0];
          displayedObservation.set(agent, { request: structuredClone(request), runId });
          return { kind: 'success', text: [
            `待答观察：${request.feature_id}；运行进程：${request.runtime_process_pid}`,
            ...request.acceptance_criteria.map((row, index) => `${index + 1}. ${row.acceptance_criterion}${row.operator_guidance ? '\n   ' + row.operator_guidance : ''}`),
            '使用 /mod-observe 答复：首行填写观察人姓名，随后按上方顺序每项一行。',
            '每行格式：通过 | 具体观察，或 未通过 | 具体观察，或 未观察 | 原因。',
            '提交会直接交给原运行器；没有观察到的项目请明确填“未观察”。',
          ].join('\n') };
        }
        const selected = displayedObservation.get(agent);
        if (!selected) throw new Error('OBSERVATION_VIEW_THIS_SESSION_FIRST');
        const response = observationReply(selected.request, rawInput);
        const result = await observationBackend(config, { response, signal, runId: selected.runId });
        if (result.status === 'submitted') displayedObservation.delete(agent);
        return { kind: result.status === 'submitted' ? 'success' : 'error',
          text: JSON.stringify(result, null, 2) + '\n答复记录不等于运行验证通过；最终状态由原运行器判定。' };
      } catch (error) {
        const code = /^[A-Z_]+$/u.test(error.message) ? error.message : 'OBSERVATION_FAILED';
        return { kind: 'error', text: `${code}：没有确认答复已提交，请核对待答观察与原运行状态。` };
      }
    } });
  ctx.commands.register({ name: 'mod-investigate', description: '调查配置中选定的失败任务：材料、Plan、请求消费、判断、验证与执行六段；只读。',
    input: { hint: '<留空使用已配置run_id>' },
    async handler({ rawInput, signal }) {
      try {
        const selected = await investigationSelection(config, rawInput.trim() || undefined);
        const data = await queryBackend(selected, { runId: selected.runId, signal, investigation: true });
        if (data.attempts.length !== 1) throw new Error('RUN_NOT_UNIQUE_OR_MISSING');
        return { kind: 'success', text: renderInvestigation(data.attempts[0]) };
      } catch (error) {
        const code = /^[A-Z_]+$/u.test(error.message) ? error.message : 'INVESTIGATION_FAILED';
        return { kind: 'error', text: `${code}：没有重新运行任务，也没有将缺失证据判作不存在。` };
      }
    } });
  for (const [name, action] of [['mod-remember', 'remember'], ['mod-memory', 'query']]) {
    ctx.commands.register({ name, description: action === 'remember'
      ? '从配置中选定任务的已核验记录生成或更新事实型经验；不训练模型。'
      : '检索在当前配置条件下可用的任务经验，展示过滤与冲突；不调用模型。',
      input: { hint: action === 'query' ? '<检索问题>' : '<无需参数>' },
      async handler({ rawInput, signal }) {
        try {
          if (action === 'remember' && rawInput.trim()) throw new Error('NO_ARGUMENTS_EXPECTED');
          const result = await memoryBackend(config, { action, query: rawInput, signal });
          return { kind: result.status === 'blocked' ? 'error' : 'success', text: JSON.stringify(result, null, 2) };
        } catch (error) {
          const code = /^[A-Z_]+$/u.test(error.message) ? error.message : 'MEMORY_FAILED';
          return { kind: 'error', text: `${code}：未确认经验处理完成，未训练模型或修改产品源码。` };
        }
      } });
  }
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
          if (config.executionConfigPath !== undefined) {
            const publicId = runId ?? mostRecentRun ?? await configuredPublicRunId(config);
            const task = publicId ? await taskRecord(publicId, signal) : null;
            if (task) return { kind: 'success', text: renderTaskStatus(task.record, task.attempts, task.delivery) };
            const configured = await configuredPublicRunId(config);
            if (configured) await taskRecord(configured, signal); // Recover child Store selection after host restart.
          }
          const selectedConfig = completedRunBindings.get(runId ?? mostRecentRun) ?? config;
          const data = await queryBackend(selectedConfig, { runId, signal });
          for (const row of data.attempts) completedRunBindings.set(row.run_id, selectedConfig);
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
    async handler({ rawInput, signal, agent }) {
      try {
        const runId = requiredText(rawInput.trim(), 'RUN_ID');
        if (config.executionConfigPath !== undefined) {
          const task = await taskRecord(runId, signal);
          if (task) return { kind: 'success', text: renderTaskStatus(task.record, task.attempts, task.delivery)
            + (task.attempts.length ? '\n请用上面实际返回的Patch子尝试ID执行 /mod-review；不把任务ID当作Patch ID。' : '\n此任务没有Patch子尝试，尚无可审查diff。') };
          const configured = await configuredPublicRunId(config);
          if (configured) await taskRecord(configured, signal);
        }
        if (config.isolatedRoot !== undefined && (!agent || typeof agent !== 'object')) throw new Error('REVIEW_SESSION_REQUIRED');
        const pending = { operationId: randomUUID() };
        if (agent && typeof agent === 'object') displayed.set(agent, pending);
        const selectedConfig = completedRunBindings.get(runId) ?? config;
        const result = await reviewBackend(selectedConfig, { runId, signal, operationId: pending.operationId });
        if (agent && displayed.get(agent) !== pending) throw new Error('REVIEW_SUPERSEDED');
        const text = renderReview(result);
        if (agent && displayed.get(agent) === pending && result.apply_preparation?.binding) {
          displayed.set(agent, { runId, binding: structuredClone(result.apply_preparation.binding), selectedConfig });
        }
        return { kind: 'success', text };
      } catch (error) {
        const code = /^[A-Z_]+$/u.test(error.message) ? error.message : 'REVIEW_FAILED';
        return { kind: 'error', text: `${code}：未取得本次运行的可审查diff；未批准、未执行。` };
      }
    },
  });
  for (const decision of ['approve', 'reject']) {
    ctx.commands.register({ name: `mod-${decision}`,
      description: decision === 'approve'
        ? '批准本会话刚显示的精确diff与隔离目标，原后端重新核验后仅执行隔离Apply，停在Build前。'
        : '拒绝本会话刚显示的精确diff，不写源码或创建隔离副本。',
      input: { hint: '<你的审查人姓名>' },
      async handler({ rawInput, signal, agent }) {
        try {
          if (config.isolatedRoot === undefined) throw new Error('APPLY_NOT_CONFIGURED');
          const selected = agent && displayed.get(agent);
          if (!selected?.binding) throw new Error('REVIEW_THIS_SESSION_FIRST');
          const reviewerIdentity = requiredText(rawInput.trim(), 'REVIEWER_IDENTITY', 200);
          if (signal?.aborted) throw new Error('APPLY_CANCELLED_BEFORE_START');
          displayed.delete(agent);
          const result = await approveBackend(selected.selectedConfig ?? config, { ...selected, decision, reviewerIdentity, signal });
          return { kind: result.status === 'blocked' ? 'error' : 'success', text: JSON.stringify({
            display_notice: result.status === 'applied_in_isolation'
              ? '批准的代码已写入显示的隔离目录；原源码未写，Build和Runtime尚未执行。'
              : result.status === 'rejected' ? '已拒绝本次diff；没有创建副本或写入源码。'
                : '本次受控Apply未确认完成，请查看原后端原因和已创建的隔离输出；重新查看diff后才可再次决定。',
            ...result,
          }, null, 2) };
        } catch (error) {
          const code = /^[A-Z_]+$/u.test(error.message) ? error.message : 'APPLY_FAILED';
          return { kind: 'error', text: `${code}：未确认隔离Apply完成；中断不等于回滚。原后端输出需核对，Build未启动。` };
        }
      },
    });
  }
  ctx.commands.register({ name: 'mod-delivery',
    description: '核验已有任务，展示完整diff、正式构建与交付范围；不调用模型或执行修改。',
    input: { hint: '<原任务run_id>' },
    async handler({ rawInput, signal, agent }) {
      const pending = {};
      try {
        if (!agent || typeof agent !== 'object') throw new Error('REVIEW_SESSION_REQUIRED');
        const runId = requiredText(rawInput.trim(), 'RUN_ID');
        displayedDelivery.set(agent, pending);
        const result = await deliveryBackend(config, { runId, action: 'preview', signal });
        if (displayedDelivery.get(agent) !== pending) throw new Error('REVIEW_SUPERSEDED');
        if (result.status === 'awaiting_approval' && result.approval_ready === true && /^sha256:[a-f0-9]{64}$/u.test(result.scope_hash)
            && typeof result.unified_diff === 'string' && result.unified_diff.trim()) {
          displayedDelivery.set(agent, { runId, scopeHash: result.scope_hash });
        } else displayedDelivery.delete(agent);
        return { kind: result.status === 'blocked' ? 'error' : 'success', text: renderDelivery(result) };
      } catch (error) {
        if (agent && displayedDelivery.get(agent) === pending) displayedDelivery.delete(agent);
        const code = /^[A-Z_]+$/u.test(error.message) ? error.message : 'DELIVERY_PREVIEW_FAILED';
        return { kind: 'error', text: `${code}：本次未取得可批准的交付范围；未执行修改或构建。` };
      }
    },
  });
  for (const [name, action, decision] of [['mod-deliver', 'deliver', 'approve'], ['mod-decline', 'reject', 'reject']]) {
    ctx.commands.register({ name,
      description: decision === 'approve' ? '明确批准本会话显示的diff及构建范围，沿原Graph隔离Apply、正式Build并保存交付副本；不调用模型或启动游戏。'
        : '拒绝本会话显示的修改，原后端记录决定，不写目标源码。',
      input: { hint: '<你的审查人姓名>' },
      async handler({ rawInput, signal, agent }) {
        let activeKey;
        try {
          const selected = agent && displayedDelivery.get(agent);
          if (!selected?.scopeHash) throw new Error('REVIEW_DELIVERY_THIS_SESSION_FIRST');
          const reviewer = requiredText(rawInput.trim(), 'REVIEWER_IDENTITY', 200);
          if (signal?.aborted) throw new Error('DELIVERY_CANCELLED_BEFORE_START');
          activeKey = `${config.executionConfigPath}\0${selected.runId}`;
          if (deliveryInFlight.has(activeKey)) {
            activeKey = undefined;
            throw new Error('DELIVERY_ALREADY_ACTIVE');
          }
          deliveryInFlight.add(activeKey);
          displayedDelivery.delete(agent);
          // A UI disconnect must not kill an already-authorized side effect.
          const result = await deliveryBackend(config, { runId: selected.runId, action,
            decision: { decision, reviewer, scope_hash: selected.scopeHash } });
          return { kind: ['delivered', 'rejected'].includes(result.status) ? 'success' : 'error', text: renderDelivery(result) };
        } catch (error) {
          const code = /^[A-Z_]+$/u.test(error.message) ? error.message : 'DELIVERY_FAILED';
          return { kind: 'error', text: `${code}：没有确认新的交付成功。请用 /mod-status 查看原任务的续接事实；中断不等于回滚，不会自动重跑。` };
        } finally {
          if (activeKey !== undefined) deliveryInFlight.delete(activeKey);
        }
      },
    });
  }
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
  ctx.commands.register({ name: 'mod-deployment', description: '预览本次构建的DLL部署、游戏运行和恢复范围；不执行。',
    input: { hint: '<任务run_id>' },
    async handler({ rawInput, signal, agent }) {
      try {
        if (!agent || typeof agent !== 'object') throw new Error('REVIEW_SESSION_REQUIRED');
        displayedRuntime.delete(agent);
        const runId = requiredText(rawInput.trim(), 'RUN_ID');
        const result = await runtimeBackend(config, { runId, action: 'preview', signal });
        if (result.status === 'awaiting_runtime_approval' && /^[a-f0-9]{64}$/u.test(result.scope_hash)) {
          displayedRuntime.set(agent, { runId, scopeHash: result.scope_hash });
        }
        return { kind: result.status === 'blocked' ? 'error' : 'success', text: JSON.stringify(result, null, 2)
          + '\n这是部署、启动新游戏进程及结束后恢复原DLL的同一次验收范围。批准使用 /mod-deploy <审查人姓名>。' };
      } catch (error) {
        const code = /^[A-Z_]+$/u.test(error.message) ? error.message : 'RUNTIME_PREVIEW_FAILED';
        return { kind: 'error', text: code };
      }
    } });
  ctx.commands.register({ name: 'mod-deploy', description: '批准刚展示的部署及Runtime范围，由原本地后端执行并恢复。',
    input: { hint: '<审查人姓名>' },
    async handler({ rawInput, signal, agent }) {
      if (executionRunning) return { kind: 'error', text: 'RUN_ALREADY_ACTIVE' };
      try {
        const selected = agent && displayedRuntime.get(agent);
        if (!selected) throw new Error('REVIEW_RUNTIME_THIS_SESSION_FIRST');
        const reviewer = requiredText(rawInput.trim(), 'REVIEWER_IDENTITY', 200);
        if (signal?.aborted) throw new Error('RUNTIME_CANCELLED_BEFORE_START');
        displayedRuntime.delete(agent);
        executionRunning = true;
        const result = await runtimeBackend(config, { runId: selected.runId, action: 'execute',
          decision: { decision: 'approve', reviewer, scope_hash: selected.scopeHash } });
        return { kind: result.status === 'blocked' ? 'error' : 'success', text: JSON.stringify(result, null, 2)
          + '\n文件复制、实际加载和行为结论分别以原部署及Runtime结果为准。' };
      } catch (error) {
        const code = /^[A-Z_]+$/u.test(error.message) ? error.message : 'RUNTIME_FAILED';
        return { kind: 'error', text: `${code}：未确认本次Runtime完成；核对原记录，不能据此重试或认定已恢复。` };
      } finally { executionRunning = false; }
    } });
  ctx.commands.register({ name: 'mod-tasks', description: '列出执行目录中已记录的任务身份，重启后仍可查询。',
    async handler({ rawInput, signal }) {
      try {
        if (rawInput.trim()) throw new Error('NO_ARGUMENTS_EXPECTED');
        const records = [];
        for (const path of new Set([config.executionConfigPath, config.newTaskConfigPath].filter(Boolean))) {
          const selected = { ...config, executionConfigPath: path };
          const listing = JSON.parse(await runBackend(selected, [...executionArguments(selected), '--list-runs'], { signal }));
          if (listing.entry !== 'run-request-list' || listing.read_only !== true || listing.model_calls_performed !== 0
              || !Array.isArray(listing.records)) throw new Error('STATUS_CONTRACT_INVALID');
          records.push(...listing.records);
        }
        return { kind: 'success', text: JSON.stringify({ entry: 'run-request-list', records,
          read_only: true, model_calls_performed: 0 }, null, 2) };
      } catch (error) {
        const code = /^[A-Z_]+$/u.test(error.message) ? error.message : 'TASK_LIST_FAILED';
        return { kind: 'error', text: code };
      }
    } });
  ctx.commands.register({ name: 'mod', description: '用自然语言新建、修改或继续Mod任务。',
    input: { hint: '<需求正文> | --task <run_id> -- <后续需求>' },
    async handler({ rawInput, agent, signal }) {
      if (executionRunning) return { kind: 'error', text: 'RUN_ALREADY_ACTIVE' };
      const selected = /^--task ([A-Za-z0-9][A-Za-z0-9_.-]*) -- ([\s\S]+)$/u.exec(rawInput);
      if (rawInput.startsWith('--task') && !selected) return { kind: 'error', text: 'NEW_PROJECT_RUN_ID_INVALID' };
      const canRemember = agent !== null && ['object', 'function'].includes(typeof agent);
      const remembered = canRemember ? naturalTaskContext.get(agent) : undefined;
      let conversation = canRemember ? naturalConversationContext.get(agent) : undefined;
      // 为什么要有它：澄清答复须回到同一会话的问题，其它会话不能继承这个待答问题。
      if (canRemember && !conversation) {
        conversation = { id: `conversation_${randomUUID()}`, pending: undefined, retry: undefined };
        naturalConversationContext.set(agent, conversation);
      }
      const activeRunId = selected?.[1] ?? remembered?.runId;
      let parentExecutionConfig = activeRunId === remembered?.runId ? remembered?.executionConfigPath : undefined;
      executionRunning = true;
      try {
        if (selected && parentExecutionConfig === undefined) {
          // 为什么要有它：新会话显式选中的旧任务须按原配置恢复，不能在新任务workspace中猜测其来源。
          const record = await inspectPublicRun(config, { runId: activeRunId, signal });
          if (!record.execution_config_path) throw new Error('TASK_ORIGINAL_CONFIG_REQUIRED');
          parentExecutionConfig = record.execution_config_path;
        }
        const description = selected?.[2] ?? rawInput;
        const retryKey = JSON.stringify([description, activeRunId, parentExecutionConfig]);
        // 为什么要有它：后端响应丢失后重试保留同一turn身份，不能重复创建工程；不同用户提交仍保留独立原文。
        const submission = conversation?.retry?.key === retryKey ? conversation.retry : {
          key: retryKey, turnId: randomUUID(), clarificationFor: conversation?.pending,
        };
        if (conversation) conversation.retry = submission;
        const result = await naturalRequestBackend(config,
          { description, activeRunId, parentExecutionConfig, signal,
            ...(conversation ? { conversationId: conversation.id, turnId: submission.turnId,
              clarificationFor: submission.clarificationFor } : {}) });
        if (conversation) {
          if (!['routing_indeterminate', 'dispatch_failed'].includes(result.status)) {
            conversation.pending = result.status === 'needs_clarification' ? result.clarification_id ?? result.route_id : undefined;
            conversation.retry = undefined;
          }
        }
        const product = result.product_result;
        if (product?.run_id) {
          bindPublicResult(product);
          // 为什么要有它：当前工程仅在同一用户会话延续，不能把其它会话最近的运行当作目标。
          if (canRemember) naturalTaskContext.set(agent, { runId: product.run_id,
            executionConfigPath: result.execution_config_path ?? parentExecutionConfig ?? config.newTaskConfigPath ?? config.executionConfigPath });
        }
        const failed = ['routing_failed', 'routing_rejected', 'routing_indeterminate', 'dispatch_failed', 'DSH_INPUT_ERROR', 'blocked', 'partial',
          'domain_blocked', 'platform_blocked'].includes(result.status);
        if (result.reason === 'CLARIFICATION_ALREADY_RESOLVED_NEW_INPUT') {
          return { kind: 'error', text: '上次澄清已经处理，这段更正尚未执行。请将更正作为新需求发送，或先查看 /mod-tasks。' };
        }
        if (result.status === 'needs_clarification') return { kind: 'success', text: result.question };
        const shown = { status: result.status, selection: result.decision, reason: result.reason,
          routing_usage: result.routing_usage, budget: result.budget, record_path: result.routing_record_path,
          cumulative_routing_usage: result.cumulative_routing_usage,
          cumulative_routing_calls: result.cumulative_routing_calls,
          ...(product ? { result: JSON.parse(renderExecution(product)).result } : {}) };
        return { kind: failed ? 'error' : 'success', text: JSON.stringify(shown, null, 2) };
      } catch (error) {
        const code = /^[A-Z_]+$/u.test(error.message) ? error.message : 'NATURAL_REQUEST_FAILED';
        return { kind: 'error', text: code };
      } finally { executionRunning = false; }
    } });
  for (const commandName of ['mod-run', 'mod-new']) ctx.commands.register({ name: commandName,
    description: commandName === 'mod-new' ? '自动创建独立任务、配置和目录，按新任务配置调用原Agent；停在原批准边界。'
      : '按已配置的本地模型、工程和预算实际执行需求，调用原Mod Agent并停在原批准边界。',
    input: { hint: commandName === 'mod-new' ? '--independent <显示名> -- <需求正文> | --preview <run_id> | --start <run_id> | <现有项目需求>' : '<需求正文>' },
    async handler({ rawInput, signal }) {
      if (commandName === 'mod-new' && rawInput.trim().startsWith('--')) {
        let selection;
        try { selection = parseNewProjectInput(rawInput); }
        catch (error) { return { kind: 'error', text: error.message }; }
        if (selection) {
          if (executionRunning) return { kind: 'error', text: 'RUN_ALREADY_ACTIVE' };
          executionRunning = true;
          try {
            const result = await newProjectBackend(config, { selection, signal });
            if (selection.action === 'start') {
              if (result.status !== 'DSH_INPUT_ERROR') bindPublicResult(result);
              return { kind: ['DSH_INPUT_ERROR', 'partial', 'domain_blocked', 'platform_blocked',
                'task_incomplete_inspect_before_retry'].includes(result.status) ? 'error' : 'success',
                text: result.status === 'DSH_INPUT_ERROR' ? JSON.stringify(result, null, 2)
                  : renderExecution(result, config.findingsContinuationConfigPath ? 'advance-task' : 'run-request') };
            }
            return { kind: result.status === 'DSH_INPUT_ERROR' ? 'error' : 'success', text: JSON.stringify({
              display_notice: '独立中性工程已准备；这里只包含项目、依赖、独立身份和空入口。产品模型尚未开始。',
              ...result,
              next_action: result.run_id ? `/mod-new --start ${result.run_id}` : null,
              deployment_boundary: '后续mod-deployment/mod-deploy是临时验收部署并恢复；永久安装与20项同时加载尚未验证。',
            }, null, 2) };
          } catch (error) {
            return { kind: 'error', text: /^[A-Z_]+$/u.test(error.message) ? error.message : 'NEW_PROJECT_FAILED' };
          } finally { executionRunning = false; }
        }
      }
      if (!rawInput.trim()) {
        try {
          const path = commandName === 'mod-new' ? config.newTaskConfigPath ?? config.executionConfigPath : config.executionConfigPath;
          executionArguments({ ...config, executionConfigPath: path });
          const profile = JSON.parse(await readFile(path, 'utf8'));
          return { kind: 'success', text: JSON.stringify({
            display_notice: `当前执行配置预览；尚未启动模型或编译。使用 /${commandName} 后接需求正文开始一次任务。`,
            target_mod: config.targetMod, target_workspace: config.workspaceRoot,
            execution_config_path: path, configured_arguments: profile.arguments,
            model_calls_performed: 0, product_execution_started: false,
            new_project_usage: commandName === 'mod-new' ? '/mod-new --independent <显示名> -- <需求正文>，初始化后用 --preview 查回、--start 明确启动。' : undefined,
          }, null, 2) };
        } catch { return { kind: 'error', text: 'RUN_NOT_CONFIGURED：执行配置尚不可读，未启动。' }; }
      }
      if (executionRunning) return { kind: 'error', text: 'RUN_ALREADY_ACTIVE：本配置已有任务运行，未重复启动。' };
      executionRunning = true;
      try {
        const result = await executeRequest(config, { description: rawInput, signal, newTask: commandName === 'mod-new' });
        bindPublicResult(result);
        let memory;
        if (config.memoryStoreRoot !== undefined && typeof result.run_id === 'string') {
          try { memory = await memoryBackend(commandName === 'mod-new' && config.newTaskConfigPath
            ? { ...config, executionConfigPath: config.newTaskConfigPath } : config,
          { action: 'remember', execution: true, runId: result.run_id }); }
          catch (error) { memory = { status: 'unavailable', reason: /^[A-Z_]+$/u.test(error.message) ? error.message : 'MEMORY_RECORDING_FAILED' }; }
        }
        const outcome = result.status ?? result.product_execution_result?.execution_disposition;
        return { kind: ['BLOCKED', 'CONTRACT_ERROR', 'PRESENTATION_FAILED', 'DSH_INPUT_ERROR', 'domain_blocked', 'platform_blocked', 'partial'].includes(outcome) ? 'error' : 'success',
          text: renderExecution(result) + (memory ? '\n\n任务经验存档（不改变原任务结果）：\n' + JSON.stringify(memory, null, 2) : '') };
      } catch (error) {
        const code = /^[A-Z_]+$/u.test(error.message) ? error.message : 'RUN_FAILED';
        return { kind: 'error', text: `${code}：未取得完整执行结果。已开始的模型、编译和记录不因中断撤销；核对原运行记录后再决定下一步。` };
      } finally {
        executionRunning = false;
      }
    },
  });
}
