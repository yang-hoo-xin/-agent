# DSH product execution, request preparation and review

## Natural-language task entry

`/mod <需求正文>` uses the configured local model once to select a new independent
Mod, a new requirement on an existing project, continuation of the same request,
or a clarification. It then invokes the existing Python entry and Graph with the
literal request. `/mod --task <run_id> -- <后续需求>` selects prior task context
after restart; subsequent `/mod` requests in the same user session retain that
selection. 为什么要有它：起点由自然语言和明确任务上下文共同确定，不能把新需求丢进旧请求的续跑。

Routing records and native model observations are saved under `.dsh-routing`.
The routing allowance is one additional call per user turn; a new product task retains the
profile's existing budget. A 12-call product profile plus one routing turn allows
13 calls; a clarification conversation also retains all earlier routing costs.
Same-task continuation retains its recorded budget and existing supported
continuation routes. Ambiguous or invalid selections do not start a product task.
为什么要有它：路由成本必须可见，选择继续不能重新领取旧任务预算。

A new requirement on a selected delivered Mod uses its verified Apply/Build
output, with a new run/request identity and a bound parent-source snapshot.
Original neutral templates remain unchanged. Preparation can be resumed via
`advance-task` with the stored literal request. Compiler feedback and the
startup-notice compiler/cold-Load evaluator can be rebound to the derived project; other evaluator contracts still
need their own explicit binding support. 为什么要有它：后续修改应从实际交付源码出发，同时核对其来源与验收接口。

Python callers use `scripts.dsh_run_request --execution-config <profile>
--route-request` with UTF-8 request text on stdin, optionally `--active-run-id`
and `--followup-delivery-root`. `--parent-execution-config` explicitly selects the
unchanged prior-task configuration when the new request uses a new profile or
workspace. Session context retains that origin; an explicit `--task` after restart
searches the configured existing/new workspaces and rejects duplicate identities.
为什么要有它：更新验收配置不能改写父交付记录，也不能让已记录任务在换会话后失去来源。

`--route-preview` performs selection and records
its model cost without initializing or executing a product task.

After a clarification, the next `/mod` answer in the same session retains the
original request, constraints, question and cumulative routing cost. Python callers
use `--conversation-id`, `--routing-turn-id` and, when explicitly selecting a pending
question, `--clarification-for`. Replaying the same turn and inputs returns its recorded
result. A changed answer to an already consumed clarification is rejected as a new
input; an incomplete execution claim is reported as indeterminate. An already
delivered task returns its verified delivery without allocating another project.
为什么要有它：澄清答案必须接回原上下文，同时区分重复请求、新纠正与尚未确定是否执行的请求。

An administrator profile can add `--dependency-api-config <absolute JSON path>`
to expose the existing read-only metadata/IL tools over the run's verified GameFolder
copy. The configuration has exactly `schema_version: "run_dependency_api_config_v1"`,
`inspector_ref: {path, sha256}` and `max_method_inspections` (1–3). The inspector path
is absolute and its SHA256 is explicit; this requires the existing GameFolder build
binding. Use a current platform inspector build supporting both metadata search and
exact `--inspect-method-token` reads; a hash alone does not establish protocol compatibility.
Configuration, inspector and dependency-copy drift are rejected before
returning evidence. This reads dependency metadata and method bodies without executing
target code; it does not establish semantic support or grant Apply, deployment or game
permissions. 为什么要有它：调查应能读取实际绑定的依赖接口，同时保持读取范围和证据身份。

`make_startup_notice_evaluator` combines the existing full compiler with a
hash-bound `bepinex_plugin_probe`. Its normal three cases preserve default and
explicit configuration behavior; `suppress_blank_messages=true` adds empty and
whitespace configuration cases. The original Patch worker receives real failures
and uses the same repair budget. Cold Load injects real Config/Log objects, skips
the plugin constructor and saves configuration in the probe; it does not run the
Chainloader or game. 为什么要有它：把适用行为检查放进修订循环，同时保留实际覆盖范围。

## Independent neutral Mod projects

An explicitly selected `candidate_reverification` recovery allocation contains
`source_attempt_ref`, `worker_configuration_ref` and a stable `attempt_id`.
`advance-task` admits the retained native candidate and original failed task,
then invokes the selected current verifier through the existing Patch/Review/
Dry-run Graph with zero model allowance. It preserves the original request ID,
task budget and failed result; continuation results live under `continuations/cv_*`.
Repeated completion reads do not reverify, and a matching verified delivery is
shown as delivered. 为什么要有它：基础设施故障后的重验与重新生成是不同操作，不能丢掉旧成本或再次审批已完成交付。

This recovery requires the original bound new-project/followup execution
configuration and a failed infrastructure evaluation of an exact native response.
The old passed-Patch/context-review reassembly contract remains separate.
The reconstructed delivery request records its origin and uses the existing
exact-diff approval owner; it carries no inherited human approval.
为什么要有它：未通过验收的候选不能继承旧成功，重建checkpoint也不能被表述成历史授权。

`/mod-new --independent <display name> -- <request text>` creates a separate
neutral project through `src.mod_agent.new_mod_project`. It displays the exact
identity, initialization scope, request, original execution settings and run ID.
No product model, Build or game operation is started by this command.

`/mod-new --preview <run_id>` recovers that prepared project after a host restart.
`/mod-new --start <run_id>` explicitly submits its bound original request and
project to the existing `run-request` Graph. Plain `/mod-new <request text>` and
`/mod-run` retain their existing fixed-project behavior.

When `findingsContinuationConfigPath` is configured, `/mod-new --start <run_id>`
dispatches exactly one `--advance-task=<run_id>` call with that allocation file.
The original Python owner decides whether to start a fresh project, load existing
progress, continue, or stop, and retains the original budget and revision links.
The UI does not prepare then execute, select a recovery route, retry, or fall back.
Why: resuming progress belongs to the product owner rather than a frontend loop.
Without that configuration the command retains `--start-project`; initialization,
preview, and `/mod-run` keep their existing routes.

The initialization uses `newTaskConfigPath` (or `executionConfigPath` when absent),
including its explicit `--game-folder-build-binding`. The new source is under
the configured run workspace's `new_mod_sources/<run_id>`; task inputs remain in
`.dsh-inputs/<run_id>`. Recovery checks receipt bytes and scope, template/source
identity, dependency binding, run/request IDs, base profile bytes, allocated
configuration bytes and the literal original request. Existing fixed targets
still require exact target-project equality. Why: task recovery must select the
same independent project without weakening the old task identity check.

When the selected worker uses `make_compilation_feedback`, the bridge binds its
source directory, project filename, expected DLL, dependency binding and NuGet
reference to the initialization receipt. The existing factory, policy, output
directories and timeout remain selected by the profile, and the allocated worker
file is hash-bound for recovery. Other evaluator contracts require explicit
support. Why: the new project cannot enter compiler feedback with a previous
Mod's source path or DLL name.

The neutral template only supplies project/dependency declarations, independent
assembly/GUID/config identity and an empty plugin entry. The product Agent owns
business investigation, API/Hook selection, generation and revisions. Why:
initialization enables the product workflow without supplying the feature answer.

After product execution, use the existing review, delivery, deployment-preview
and observation commands for the same task. `mod-deployment`/`mod-deploy` currently
cover temporary acceptance deployment followed by restoration. Permanent
installation and twenty Mods loaded together have not been verified. Why:
temporary runtime acceptance cannot establish durable installation or coexistence.

## New task and runtime observation entry

`/mod-continue <run_id>` is a **read-only initial Findings continuation preparation**.
It shows the first rejection, exact conflicting fields, correction preparation and
budget refusal, with historical Trace separated from current offline reconstruction.
The original request/response hashes, Feature, source tree, model selection and
execution configuration are checked before reusing the original correction builder.
It exposes the inherited total and stage allowances and an exact prepared-input
hash. It never changes gaps, support decisions, prompts, limits or the old run.
Preparation does not invoke a model or Graph, does not grant a new time window,
and is not completed task resumption. Without a separately reviewed allocation,
the current shortcut run remains blocked because its Findings allowance is zero.

Optional `findingsContinuationConfigPath` points to an instance containing
`stage_model_call_limits` and `max_execution_seconds`, with optional
`findings_contract_version: "3"` to select the provider-compatible Findings contract and an
optional exact `dependency_api` inspector reference. The stage total cannot grow,
consumed calls cannot be refunded, and the time window is limited to 3600 seconds.
With this instance, `/mod-continue` displays the model identity, limits, original
and proposed budgets, time scope and approval hash. `/mod-resume <reviewer>` consumes
that same-session review and invokes the original `run-request` and Graph from the
Findings correction. It reuses the original projection and baseline; subsequent
Planning/Patch calls use the inherited task budget and stop at original exact-diff
approval. This command does not authorize Apply, deployment or gameplay.

Without an explicit revision, preparation replays the recorded Findings contract
and schema exactly. Version 2 remains reproducible historical input. Version 3
supplies consistent edit-hint rules plus rejected fields, their relations and validator diagnostics in the
correction request. It preserves relevant partial evidence and genuine missing
current source/API knowledge; absent requested new behavior is post-change
acceptance, not proof that current implementation evidence is missing. The preview
binds both historical and selected input hashes; a prior approval cannot authorize
the changed input version. Historical requests, responses and results stay unchanged.

The version-3 wire schema keeps all five common fields required and leaves conditional
edit-hint semantics to the existing deterministic validator; Ollama rejects the
known destructive mixed `properties`/`required` plus `oneOf` shape before transport.
The revised preview projects the complete correction → missing-evidence query →
Findings reassessment sequence before any reservation. From the retained task's
latest 3/11 result this requires Findings 4 and Repair at least 1; the reviewed redistribution
uses `1/4/1/1/4`, preserving the total and prior three calls. If either stage cannot
complete the sequence, execution stops before sending the query. A configured
dependency supplement reads only the run's hash-bound isolated GameFolder copy
with the existing metadata/IL tools and a hash-bound inspector. Its queries come
from the model's reassessment request; it supplies current API observations but no
Hook choice, edit target, approval or extra model allowance.

Each traced structured Ollama call now retains two distinct local records:
`request` is the application messages/schema/options document, while
`provider_request` is the exact native body passed to the HTTP adapter. The Trace
records the native body hash, size and non-secret transport metadata. A missing
provider-request ref remains unknown unless the recorded failure boundary proves
the request was rejected before construction. Schema-to-grammar output remains
unknown unless a future exact backend supplies a bound grammar or warning record.

The claim and continuation records are separate from the original manifest and
result. Admission checks current source/configuration/input hashes again. Repeated
execution reads the recorded result; an incomplete claim requires inspection and
cannot automatically retry. `/mod-status` distinguishes the original result from
the latest continuation. Controlled transport tests cover this route; they do not
establish real-model correction quality or a completed shortcut feature.

`/mod-new <request>` allocates a new paired request/run identity and persists its
exact invocation configuration beneath `.dsh-inputs` in the configured workspace.
The original `run-request` owner creates the task directory and runs its Graph;
the old single-use `/mod-run` profile is unchanged. Optional `newTaskConfigPath`
selects a separate durable workspace while retaining historical task queries.
`/mod-tasks` enumerates recorded public tasks; `/mod-status <run_id>` recovers the
selected task after restart. The delivery bridge consumes that task's saved
configuration rather than requiring a manually edited fixed ID.

A template with an evaluator declares `worker_path_bindings`: each row contains
an exact `path` list beneath `behavior_evaluator.kwargs` and a `relative_path`
inside the new task directory. Only those declared values are relocated. Factory
hashes, dependency references, policy and budgets are retained. Missing bindings
block before execution; this is not recursive string/path guessing.

`/mod-observe <run_id>` displays the original runtime's pending criteria, process
identity and guidance. Reply in the same session with observer name on the first
line, then one line per displayed criterion: `通过 | observation`,
`未通过 | observation`, or `未观察 | reason`. The bridge uses the original runtime
validator and publishes its hash-confirmed response; no separate manual file
entry is needed. Unknown observations remain unknown. A configured absolute
`observationDirectory` also supports an explicitly selected standalone exchange.
This is operator feedback, not a model's independent judgment or general code
revision continuation.

Optional `runtimeConfigPath` selects a JSON object containing `settings_path`
and `runtime_plugin_destination`. `/mod-deployment <run_id>` consumes the verified
delivery's original Build checkpoint and calls `preflight_local_runtime` without
effects. It displays the exact DLL, current installation, game profile and restore
scope. `/mod-deploy <reviewer>` confirms the current session's displayed scope and
calls `resume_local_runtime`; the existing local owner deploys, launches, observes
and restores. It is temporary deployment for acceptance, not a permanent install.
An already running game blocks deployment. Changed inputs require a fresh preview;
uncertain results are retained without automatic retry. Observations may be
submitted in another DSH session while execution waits. Copying a DLL is not a
claim of correct loading or behavior; inspect the original Runtime result.

New-task/observation engineering tests use controlled provider/compiler boundaries.
The deployment bridge's scope tests use controlled owner results. These tests do
not establish the shortcut feature, real gameplay, or memory benefit.

## Investigation and task experience

Configure `investigationConfigPath` with the exact `artifactStoreRoot`, `featureId`,
`runId` and `currentContext` for the selected historical task; configure
`memoryStoreRoot` separately for persisted experience.

- `/mod-investigate` displays six investigation stages with their original refs,
  observed failures, unknowns and next verification steps. It does not rerun a task.
- `/mod-remember` imports bound execution facts into the existing ArtifactStore.
  Repeating an unchanged import returns `reused` / `no_new_revision`.
- `/mod-memory <question>` retrieves applicable experience and displays evidence
  refs, applicability, unknowns and invalidation conditions. It makes no model call.

New execution lessons use `execution:<SHA256 of resolved source Store root>:<run_id>`.
Independent Stores with the same run ID retain independent revision histories.
Legacy `execution:<run_id>` lessons and their refs remain untouched and readable;
the first explicit reimport creates a separate scoped lesson, not a migration.
Both may be returned by retrieval. Moving a source Store changes this identity.

Experience remains `planning_only`. The existing Planning assembly supplies a
separately bounded model view (at most 3000 characters); memory cannot select
edit targets, approve changes or choose workflow routes. Saved request capture
proves input assembly only; model repair quality or completion gains are unverified.

Status queries preserve `admitted` and `partial` when delivery does not apply,
reporting `delivery_continuation.status=not_applicable` separately. A blocked
query without an execution receipt does not replace the original task status.
A backend-verified blocked receipt preserves the actual execution failure,
including Build results and unknown effects. Receipt identity must match the
queried run and response. Verified delivery receipts still display `delivered`
/ `build` with the original history retained.

The three fixes and real historical command acceptance are recorded once in
[audit 0.39](../../docs/audits/PATCH_AGENT_PROGRESS_RECONCILIATION_20260905.md#039-调查与任务经验三个缺陷修复2026-09-20).
The fixes, including the blocked-receipt correction, are integrated into the
main tree. The original 3088 host has passed actual page operations: retained
001/002 status, historical investigation, save/reuse, and experience retrieval.
The earlier isolated-host browser block is historical; follow-up evidence is
in audit 0.39.1. These operations made no new model or product execution calls.

`/mod-run` now invokes the original local `run-request` entry. Empty input previews
the administrator-configured project, model and arguments; a description starts
one actual product run with explicit model/stage budgets and deferred approval.
The original Mod Agent performs investigation, generation and verification. DSH's
own model loop remains disabled. This is an execution entry, not a second Agent
or a complete persistent conversational workflow.

Configure `executionConfigPath` as an absolute JSON file containing only an
`arguments` array of supported original CLI options. The Python bridge requires
local Ollama, explicit budgets, isolated preparation/build permission and
`--defer-approval`; it does not enable external disclosure or game operations.
Requests are literal UTF-8 stdin, not CLI options. Existing typed worker configs
and their verified local factories are supported. A profile with fixed run and
request IDs is single-use, which permits an existing evaluator to bind exact
paths; a consumed profile must be replaced deliberately, never silently retried.
Without fixed IDs, the bridge creates fresh paired identities. `runTimeoutMs`
is the host timeout (default 20 minutes, at most one hour), not extra model budget.

`/mod-status <public_run_id>` reads the original manifest/result, including failures
before a Patch journal exists. It returns actual recorded counts and blockers;
the status query itself makes no model calls. `/mod-runs` can recover the fixed
configured public task after host restart and lists its actual Patch sub-attempt
IDs. Those IDs, rather than guessed suffixes, select the original Patch query or
`/mod-review`. Reviewing a public task lists its sub-attempts or explains that no
Patch exists. Approval still requires a separately configured isolation root and
a review in the same live session. The execution result displays original key
facts, diff, artifact references and original-result path; it does not render the
entire internal Artifact readback or infer success from subprocess exit.

For a retained public `awaiting_approval` task, configure an absolute
`deliveryRoot` outside the original input/workspace and keep the original fixed
`executionConfigPath`. `/mod-delivery <public_run_id>` rechecks the original
checkpoint, source, dependencies and diff, then shows the exact Apply, NuGet
restore/build and persistent-copy scope. `/mod-deliver <reviewer name>` explicitly
approves that displayed scope; `/mod-decline <reviewer name>` records rejection.
These commands use `scripts.dsh_deliver_run`, `resume_deferred_approval` and
`continue_reviewed_patch`. They do not regenerate a Patch or use the older
reviewed-copy Apply entry. The original isolated target remains fixed; only
after a verified Build does the adapter preserve a complete delivery copy.
The original task and Artifact paths remain provenance, not migrated checkpoints.

The approval binds the exact diff, checkpoint, source/dependency identities,
build profile and output directory. A new live session must display the scope
again. The host admits one concurrent dispatch for the configured task; original
resume records and the adapter's initial receipt retain interruption/replay facts.
A UI disconnect after dispatch does not cancel the already-approved subprocess.
`/mod-status` includes `delivery_continuation` and `current_status`, while keeping
the original run's `recorded_status` and model count. Query cost is zero; historical
Apply/Build facts are in the returned receipt. No game operation is included.
This path is separately configured from `/mod-approve` and `/mod-reject`, whose
older review-copy semantics below remain unchanged.

This plugin uses DSH for the browser interface, interaction session and plugin
host. The original Python journal and ArtifactStore remain the product facts.
It can submit natural-language intake to the existing deterministic planner and
save its two planning Artifacts. With an administrator-configured isolation root,
a human can approve an already reviewed exact diff; the original backend then
copies the configured source tree, repeats Dry-run, and applies only inside that
new directory. It stops before Build. No DSH model or game operation runs.

The tested host is official `@deepseek-ai/dsh` **0.1.2-rc.1**, on Node 24.19.0.
The host includes the pinned peer modules; no replacement Agent or renderer is
implemented here. Future DSH compatibility needs acceptance against that version.

The current dedicated local deployment also disables the existing
`ui-settings-models` and `ui-model-selection` rows: their DeepSeek onboarding and
picker describe DSH's unused model loop, not the configured Mod Agent. No key or
credential is removed. Product model/budget details remain in `/mod-run` preview.
Real UI execution and restart readback are recorded in
[the existing audit, section 0.37](../../docs/audits/PATCH_AGENT_PROGRESS_RECONCILIATION_20260905.md).

Commands are human commands, not model tools:

- `/mod-runs` lists up to 20 records for the configured Feature, with truncation
  reported. It does not claim this is chronological pagination.
- `/mod-status <run_id>` selects exactly one recorded run.
- `/mod-review <run_id>` displays that run's exact retained Proposal, Review and
  Dry-run diff, its recorded verification summaries, and a current source check.
  It grants no approval and does not invoke a verifier or apply code.
- `/mod-submit <request text>` prepares a new request using the existing
  `plan-request` implementation, with its original ambiguity and evidence-gap
  decisions. It stops before `feature_spec`; no implementation Plan is generated.
- `/mod-approve <reviewer name>` approves the exact diff and isolation target most
  recently displayed by `/mod-review` in this live session. It sends the existing
  `human_semantic_decision_v1` binding to the original `apply-patch` CLI and Graph.
- `/mod-reject <reviewer name>` rejects that displayed action without copying or
  writing source or Artifacts. A different session cannot consume the binding.

The query commands call the existing engineering-cognition `verification-claims` /
`patch-execution` query with fixed arguments and `shell: false`. Deployment
configuration supplies `pythonExecutable`, `repositoryRoot`, `artifactStoreRoot`
and `featureId`, plus optional `timeoutMs` and `maxOutputBytes`. User command text
cannot select a shell command, store or filesystem path. Results retain unknown
source freshness and never infer Mod success from command completion.

To enable submission, deployment configuration must additionally provide both
`workspaceRoot` (absolute existing target directory) and `targetMod` (exact
target name). Keep `artifactStoreRoot` as the original backend Store. The
configured `featureId` still selects query results; it does not override a new
submission's Feature ID, which the original RequestPlanner derives from input.
An unconfigured `/mod-submit` reports `SUBMIT_NOT_CONFIGURED`.

Review also requires the configured `workspaceRoot`; without it `/mod-review`
returns `REVIEW_NOT_CONFIGURED`. Its fixed `scripts.dsh_review_run` bridge uses
the canonical Patch journal, its verified terminal-result hash, and immutable Store reads. It selects only refs
recorded by the requested run, verifies Proposal→Review→Dry-run lineage and
original diff identity, and never substitutes the Feature's latest result or
the run's parent Proposal. A failed run without a new Proposal explicitly has
no reviewable diff. Missing or corrupt refs do not produce a reviewable result.

The displayed diff is the original Dry-run diff. The view reports each changed
file's expected original baseline hash, its current hash and the first mismatch.
When those files still match, the original materializer reconstructs the output
in memory and compares the resulting diff. This does not rerun Review, compile,
execute behavior checks or prove freshness of every supporting file. Historical
Review and behavior results remain separate from this source check. The command
does not perform semantic review, create exact approval, Apply, Build or Runtime;
those actions still need their existing independent product entry and authority.

For the new approval path, configure `isolatedRoot` as an existing absolute
directory disjoint from both `workspaceRoot` and `artifactStoreRoot`. Review then
also shows the concrete new isolation target and original semantic-decision
binding. The human supplies only a decision and reviewer identity; all references
come from that displayed result and are revalidated by the backend. The source
root is explicitly configured and verified against the retained baseline, not
guessed from edit paths. Copying retains the source tree while excluding the
existing `bin`, `obj`, `.git`, `.idea` directories; external links are rejected.

The approval backend reuses original Feature/Evidence/Plan admission, immutable successful
Proposal/Review/Dry-run artifacts, and `ExactTextPatchApplier`. It seeds the same
Graph after the verified Review, repeats its real Dry-run and isolated Apply,
then interrupts before `build`. This does not claim compilation, Runtime or
complete task delivery. The original source workspace remains unchanged.

Approval consumes the live session's displayed binding once. Host restart or a
different session requires reviewing again; this is not durable approval-resume
acceptance. A source, artifact, diff or destination change invalidates the action.
An already aborted command never dispatches Apply. Interrupting a started child
is not transactional cancellation or rollback; inspect the isolated output and
original `isolated_apply_result` before deciding what to do next.

Submission uses the fixed `scripts.dsh_prepare_request` bridge with UTF-8 stdin,
not shell interpolation or user-selected options. The bridge calls
`src.mod_agent.cli.plan_request`, then writes existing `request_planning_report`
and `mod_planning_brief` Artifacts with their existing upstream relationship.
The Store keeps revisions and handles repeated identical submissions; no job
database or DSH task-state authority is added. The workspace is checked for
existence, not searched or treated as verified source Evidence.

The command result shows the new Feature ID, exact Artifact refs, original
clarification questions/blockers and stop point. Missing information is not
silently guessed. Request persistence is a write to backend planning records,
not a product source Apply or task success. If the child stops between writes,
it does not undo an already written Artifact or claim completion; repeating the
same input uses the existing deterministic IDs and Store. This is not execution
resume or transactional cancellation of a running product job.

## Host composition

Load the absolute file URL of `index.mjs` in a standard DSH patch `insert` row,
with the configuration above. The nearest package manifest declares the client
module; the same row loads both halves. Do not insert another client copy.

Keep DSH's stock `agent-loop` factory: removing it also prevents session
creation. This plugin registers the official `agent/pre-step` rejection hook,
so DSH model generation is not used for these commands. In the tested dedicated
profile, the agent preset is empty, `session-title-llm`, `goal-round-driver`,
`session-telemetry-otel` and `command-feedback` are disabled. This is a
preparation/query composition, not an OS sandbox or a product execution policy.

For unattended browser testing, disable the existing `directory-picker` auto
row and insert the official browse backend **and** its client UI. A patch `name`
is a match assertion, not a plugin rename; changing it on the old row is skipped.
Do not mount auto/native and browse simultaneously.

The tested standalone overlay and isolated home are under the current task's
`dsh-runtime/mod-readonly.patch.yml` and `dsh-demo-home`. A normal deployment must
supply its own paths. No token, API key or replayable authorization is stored here.

## Empty-session display

DSH 0.1.2-rc.1's chat target excludes pure command content from its active test.
`client.js` registers a read-only activity view of paired command results so
that the existing conversation shell activates. Original `CommandNodeView` /
`GenericCommandCard` still render the original result. No fake assistant message,
duplicate command node, custom result renderer or product state is introduced.

## Verification

Set `MOD_AGENT_PYTHON` to the selected Python executable and
`DSH_RUNTIME_NODE_MODULES` to the pinned host's `node_modules`, then run:

```text
node --test integrations/dsh-mod-agent/tests/*.test.mjs
```

Tests exercise real query subprocesses, argument boundaries, output/cancellation
limits, retained 013 reads without journal mutation, and actual published DSH
conversation components with unchanged command-result text.

The browser acceptance created a real DSH session, ran `/mod-status` against
013, persisted `command/run` and `command/done`, restarted the host and displayed
the retained `partial` / `PATCH_AGENT_UPSTREAM_REQUESTED` result. No model events
were recorded for that query. Ordinary-message rejection has a local hook test;
it was not accepted as a separate real model-transport test.

Natural-language preparation has subprocess acceptance through the original
planner and ArtifactStore, including ambiguity, repeated input, literal request
text and unchanged source checks. Actual official-host submission acceptance is
separate from those automated checks; the historical browser run above covered
querying only.

The preparation command still stops before execution; use the explicit execution
command for an actual local task. Task 002 has separately completed real approved
Apply, formal Build and persistent delivery (audit 0.38); this task only queried
that retained result. Incremental phase display, same-task follow-up and observation
submission, general interruption recovery, transactional task cancellation and
game Runtime remain outside that demonstrated result.
