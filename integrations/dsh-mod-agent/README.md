# DSH request preparation, review and isolated application

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

The backend reuses original Feature/Evidence/Plan admission, immutable successful
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

Automatic execution after submission, durable approval recovery, transactional
task cancellation, Build/Runtime continuation, delivery and a polished end-user
workflow remain unfinished. Approval-to-isolated-Apply has subprocess acceptance
with synthetic explicit human decisions; real Mod approval is not inferred.
