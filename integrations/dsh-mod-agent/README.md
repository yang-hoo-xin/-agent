# DSH read-only product queries

This plugin uses DSH for the browser interface, interaction session and plugin
host. The original Python journal and ArtifactStore remain the product facts.
It does not submit work, run a model/verifier, approve, Apply, Build or launch a
game. Cancelling a query cancels its child reader, not a product task.

The tested host is official `@deepseek-ai/dsh` **0.1.2-rc.1**, on Node 24.19.0.
The host includes the pinned peer modules; no replacement Agent or renderer is
implemented here. Future DSH compatibility needs acceptance against that version.

Commands are human commands, not model tools:

- `/mod-runs` lists up to 20 records for the configured Feature, with truncation
  reported. It does not claim this is chronological pagination.
- `/mod-status <run_id>` selects exactly one recorded run.

Both call the existing engineering-cognition `verification-claims` /
`patch-execution` query with fixed arguments and `shell: false`. Deployment
configuration supplies `pythonExecutable`, `repositoryRoot`, `artifactStoreRoot`
and `featureId`, plus optional `timeoutMs` and `maxOutputBytes`. User command text
cannot select a shell command, store or filesystem path. Results retain unknown
source freshness and never infer Mod success from command completion.

## Host composition

Load the absolute file URL of `index.mjs` in a standard DSH patch `insert` row,
with the configuration above. The nearest package manifest declares the client
module; the same row loads both halves. Do not insert another client copy.

Keep DSH's stock `agent-loop` factory: removing it also prevents session
creation. This plugin registers the official `agent/pre-step` rejection hook,
so DSH model generation is not used for these commands. In the tested dedicated
profile, the agent preset is empty, `session-title-llm`, `goal-round-driver`,
`session-telemetry-otel` and `command-feedback` are disabled. This is a query-only
composition, not an OS sandbox or a product execution policy.

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

Task submission, diff approval, task cancellation, product execution resume,
delivery and a polished end-user workflow remain separate unfinished capabilities.
