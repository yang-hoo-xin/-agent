# Repository Instructions For Codex

These instructions apply to work in this repository. They are execution rules,
not evidence that a capability exists.

## 1. Accuracy And Communication

- Avoid excessive praise. Treat both user and agent judgments as reviewable.
- Use structured, precise answers and state important uncertainty or missing
  evidence directly.
- Do not use the English word prohibited by the user for speculative options.
- Never guess identifier casing, field shape, JSON paths, filenames, symbols,
  commands, or configuration keys. Read the relevant source, test, log, capture,
  or configuration first and quote the exact form.
- When a request is ambiguous, infer its likely practical intent and confirm the
  interpretation before an assumption would materially change scope.

## 2. Task Entry And Evidence Order

After this file, read only what the concrete task requires, in this order:

1. the current user request;
2. the current selection and active block in
   `docs/ACTIVE_PRODUCT_CONTRACT.md`;
3. the top of `docs/PROJECT_STATE.md` only when current product status matters;
4. current source, configuration, logs, and focused tests for the touched path;
5. only the affected rows in `docs/SPEC_COVERAGE_MATRIX.md`;
6. only the active task block in `docs/IMPLEMENTATION_QUEUE.md`;
7. `docs/ARCHITECTURE_OVERVIEW.md` only when architecture or task direction is
   at issue;
8. detailed SPEC sections only for the boundary actually touched.

Do not read an entire history-heavy control document merely because it appears
in this list. An audit, historical reconstruction, or explicit document review
may require a wider read; ordinary implementation does not.

### 2.1 Authority Order

The current user request and the active product contract govern scope, intent,
and permission. Source code, tests, retrieval results, and runtime observations
do not grant write, model-disclosure, Build, process-launch, or game-directory
authority.

### 2.2 Evidence Order

For empirical claims about current behavior, current source, API metadata,
configuration, focused tests, and current-run runtime evidence outrank model
output, community hints, historical artifacts, plans, diagrams, and frozen
documents. Evidence describes what is true; it does not replace the authority
order above.

### 2.3 Regenerable Engineering Cognition

- Keep two cognition systems distinct. Codex engineering cognition explains
  this repository's entry surfaces, workflow and routes, Artifacts, owners,
  state fields, tests, receipts, and current Git facts. Product Dependency/API
  Evidence grounds the product Agent's understanding of a target Mod, game,
  dependency APIs, usage, behavior, and verification. Neither proves the other.
- For architecture, ownership, route, Artifact, field, or current-status
  questions, first run
  `python -m scripts.engineering_cognition --view summary --pretty`, then request
  only the affected deeper view. Treat every result as a read-only, regenerable
  projection, not durable state or an authority source.
- Entry/Surface, Workflow/Route, Artifact DAG, Ownership/Authority,
  Source/Dependency, API Usage, Behavior/Dataflow, and Verification/Claim are
  on-demand query views. Do not persist them as eight graphs, add a second
  `StateGraph`, create a cognition database or shadow registry, or make them a
  new control plane.
- Distinguish declarations, current observations, executed verification,
  stale facts, and unknowns. A source or test reference is not an executed test;
  a static edge is not a run; and none of these facts grants semantic, route,
  write, approval, or claim authority.
- Treat a stale `.codex/task-packet.json` as context only. It cannot select the
  current task or override the user request, active contract, current source,
  Git identity, tests, or current-run evidence.
- Do not infer business semantics, the correct edit target, verified behavior,
  or an executed Actual from a name, static edge, reachable Graph path,
  contract declaration, test presence, or historical Artifact. Require an
  explicit current owner and bound source/test/receipt/trace evidence;
  otherwise report the limitation or `unknown`.

### 2.4 Frozen Project Playbooks

- Every project-local directory whose name ends in `-playbook` is frozen. Its
  `SKILL.md.frozen` file is historical process material, not an active Skill,
  task router, fact source, authority source, or default decision input.
- Do not load, cite, restore, or follow a frozen playbook merely because a task
  resembles its former description. Current user intent, current source,
  exact Artifacts, logs, configuration, and focused tests govern the work.
- A frozen playbook may be restored or consulted only when the user explicitly
  names that exact playbook in the current request and asks to thaw or inspect
  it. Restoration is a separately reviewed versioned edit.
- If a frozen playbook is loaded accidentally, disclose that fact, stop using
  it, and independently revalidate every affected conclusion from current
  evidence before acting.

## 3. Task Entry And Capability-First Work

- Do not execute platform expansion without a concrete product capability, real
  Mod request, observed failure, demonstrated safety defect, or bounded product
  decision requiring evidence.
- Unless explicitly performing audit, documentation, approval review, or
  closure, an authorized and unblocked implementation cycle must prioritize one
  verifiable new capability. Risk notes, schema cleanup, and narrower claims do
  not substitute for capability delivery.
- Prefer the smallest real vertical result. Reuse existing control-plane
  contracts and add infrastructure only for a failure observed in that result.
- After the selected capability succeeds, stop infrastructure work and return
  to the product mainline.
- Do not revive queued, frozen, formal-validation, Dense/RRF, Dashboard, MCP,
  memory, or Agentic work merely because it appears in an older roadmap or SPEC.
  A concrete current user request may activate bounded work in those areas.
- A local blocker must not turn into an open-ended contract exercise. After one
  focused diagnosis cycle without new evidence, choose a bounded experiment,
  report an exact blocker, request the missing decision, or reduce the claim.
  Do not keep adding schemas or gates as a substitute for the selected result.

### 3.1 Contract Reuse First

- Keep authority precision in immutable instance data: exact path, symbol,
  source hash, span, operation, revision, and approved diff hash.
- Reuse the existing EditAuthorityRequest, EditAuthorityApproval,
  BindingResolver, ResolvedRepairTarget, and Artifact contracts across product
  domains.
- A new failure normally creates an existing type's new instance or revision.
  It does not by itself justify a new Artifact type, Approval type, Graph
  branch, CLI path, or domain-specific authority subsystem.
- Group related exact bindings under one bounded repair objective. Diagnostic
  writes and product-behavior writes retain separate approvals, but use the
  same authority schemas and resolver.
- Before adding a platform contract, identify the existing contract considered,
  the exact fact it cannot represent without semantic distortion, why instance
  data or a new revision is insufficient, and either the repeated real product
  cases or the current safety-critical distinction that requires the new
  representation.
- These reuse rules govern new work. Existing committed or materialized
  contracts are not automatically invalidated, deleted, consolidated, or
  migrated. Consolidation requires a separately authorized migration task with
  compatibility and Artifact-history handling.

### 3.2 Actual First-Failure Loop

- Use an Actual as a bounded integration or acceptance attempt, not as the
  default tool for local diagnosis and not as an automatic retry loop.
- For each authorized Actual, handle only its first physical failure:
  freeze the exact input identities and trace, reproduce the failure with the
  smallest evidence-preserving focused test, deterministic vertical scenario,
  or offline replay, implement one general repair at the verified owner, and
  prove the old failure signature is caught deterministically before another
  Actual is eligible.
- The repair must express a reusable invariant. Task-specific paths, symbols,
  spans, and model outputs may be regression fixtures, but must not become
  hard-coded production policy unless the selected product contract explicitly
  makes them domain facts.
- After focused and vertical evidence passes, authorize at most one new Actual
  to accept that repair. A later first failure belongs to a new decision cycle;
  it does not authorize an automatic next attempt, fallback, prompt change, or
  downstream repair.
- If one general repair does not remove the same first-failure signature, stop
  local patching and re-audit the input representation, responsibility split,
  or technical choice. Do not keep extending timeouts, schemas, gates, or
  control-plane surface to preserve the existing route.
- A successful Actual proves only the stages and bound facts it reached. Promote
  a stable capability claim only after the same invariants hold across the
  required real-task set and no task-specific authority was smuggled into the
  implementation.

## 4. Architecture Guardrails

- Keep one LangGraph `StateGraph` as the workflow control plane. Conditional
  edges own final routing.
- Workflow specialist roles, including Planner, Evidence, Reviewer, and
  ProposalCritic, operate inside that graph. They do not receive independent
  write or route authority. This restriction applies to product workflow nodes,
  not to a user-authorized Codex engineering task or its implementation agents.
- Use same-level specialist fan-out only when a concrete request has separable
  risk dimensions whose independent assessment can change a decision. Do not
  create an always-on multi-agent swarm for architectural appearance.
- Give each specialist a bounded context pack with registered Artifact refs,
  hashes, and necessary evidence excerpts. Require structured findings,
  supporting refs, unknowns, limitations, and a recommended action. A returned
  summary without traceable refs is not decision evidence.
- Those workflow specialists may not write files, select authoritative paths or
  Hooks, approve diffs, launch builds/runtime, or choose LangGraph routes.
  Deterministic fusion validates their outputs; conditional edges retain final
  route authority.
- Keep ReAct as an optional bounded strategy inside a specialist node. Do not
  replace the top-level controlled Workflow with ReAct without a recorded real
  failure and an explicit architecture decision.
- A ProposalCritic or other assessment may not authorize writes, change paths,
  bypass ProposalReviewer, override human approval, or defeat a deterministic
  blocker. Read current policy names, thresholds, and provider behavior from
  source, focused tests, and `docs/ARCHITECTURE_OVERVIEW.md`; do not freeze
  version-specific settings in this file.
- ArtifactStore owns durable business outputs and audit lineage. LangGraph owns
  runtime state and routing. Do not hide durable claims only in graph state.
- Domain-specific GTFO behavior belongs behind domain/game boundaries, not in
  generic workflow modules.

## 4.1 Long-Term Memory And Closed-Loop Rules

- Artifact history, checkpoint state, chat history, and model reasoning are not
  automatically trusted long-term memory.
- Record a reusable lesson only from a bound outcome. Preserve the request,
  source/Artifact hashes, environment and version, observed failure, action,
  verification result, limitations, and invalidation conditions.
- Reusable lessons are planning-only hints. They may suggest evidence queries,
  risks, non-goals, or tests; they cannot authorize paths, Hooks, patches,
  permissions, runtime claims, or delivery.
- Revalidate every retrieved lesson against current source, API, Binding
  Registry, environment, and runtime evidence. Reject or mark stale when the
  recorded assumptions no longer match.
- Do not silently update prompts, thresholds, routing, permissions,
  `AGENTS.md`, SPEC documents, or product policy from run feedback. Durable
  control changes require explicit human review and normal versioned edits.
- Do not build automated lesson extraction, a memory database, feedback jobs,
  or policy learning until repeated real tasks expose a concrete retrieval or
  recurrence failure that manually recorded lessons cannot solve.

## 4.2 Architecture Reference Status Control

- Interpret architecture references using three exact states: `implemented`,
  `documented_only`, and `conditional_trigger`.
- `implemented` requires current source plus focused evidence and may be reused
  only within its recorded claim boundary.
- `documented_only` describes responsibility separation or a possible design.
  It is not current behavior, partial implementation, planned work, or a queue
  entry. Do not create code, schemas, graph nodes, providers, or tests merely to
  make a documented-only diagram executable.
- `conditional_trigger` may enter the queue only after the exact named product
  failure or use case is recorded. Implement only the smallest capability that
  addresses that trigger.
- A conditional trigger never activates the whole reference architecture and
  never overrides the current queue, permission, disclosure, write, runtime, or
  claim boundaries.
- Current maturity, exact triggers, policy versions, and thresholds belong in
  source, focused tests, `docs/ARCHITECTURE_OVERVIEW.md`, and the active product
  contract. Do not duplicate changing implementation state here.

## 5. Evidence, Models, And Writes

- Retrieval relevance never grants write authority.
- For product-source changes generated by the controlled Mod workflow, the
  Binding Registry and current live source determine writable targets.
  Model-generated paths or copied path strings are not authority. Dry-run must
  not write, and real apply requires the exact displayed approval hash plus a
  fresh live-source/binding check.
- User-authorized development of this platform repository is not a
  product-source Apply and does not require a Mod Edit Binding or product
  Approval Artifact. It remains subject to the user's requested scope, current
  filesystem authority, Git safety, focused tests, and preservation of
  unrelated changes.
- Sending source or other local material to an external model requires explicit
  per-run consent covering the exact data classes. Never expose API key values.
- A model-based ProposalCritic requires the same disclosure consent; a local or
  test ProposalCritic must be labelled as such.
- Game launch, game-directory copy, and gameplay evidence require separate
  explicit approval. One approval may cover a bounded set of attempts only when
  it states the task, capability classes, paths, attempt budget, stop
  conditions, and restoration boundary. Scope, identity, or budget drift
  requires new approval.

## 6. Verification And Claims

- Run focused tests proportional to the touched behavior. When a tracked
  capability changes, record the exact command and result once in its primary
  control location; other documents should link or summarize status rather than
  duplicate the full run narrative.
- Unit tests prove tested local behavior. Dry-run proves no-write validation.
  Apply proves approved bytes were written in isolation. Build proves the
  declared artifact compiled. Runtime evidence proves only the observed bound
  facts. Do not promote a claim beyond its evidence level.
- Never generalize one Mod, repository, language, scorer, or environment into a
  cross-project claim.
- Preserve unrelated user changes. Do not delete, roll back, reset, or rewrite
  dirty work without explicit authorization.

## 7. Documentation Discipline

- `docs/ARCHITECTURE_OVERVIEW.md` explains current structure, maturity, and drift
  boundaries. It is not a second implementation queue.
- `docs/ACTIVE_PRODUCT_CONTRACT.md` remains the short daily product contract.
- `DEV_SPEC.md` remains the detailed control-plane authority.
- `docs/SPEC_COVERAGE_MATRIX.md` must distinguish implemented, tested, partial,
  deferred, and unproven behavior.
- Update architecture documents only when a decision, boundary, or verified
  implementation state changes. Do not create documents merely to increase
  apparent completeness.
- Keep one authoritative location for detailed run evidence. Do not materialize
  the same hashes, commands, and narrative independently across Active Contract,
  Project State, Implementation Queue, and the coverage matrix.
