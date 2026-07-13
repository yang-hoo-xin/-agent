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

## 2. Daily Authority Order

Before ordinary product work, read only what the task requires, in this order:

1. `docs/ACTIVE_PRODUCT_CONTRACT.md`;
2. the top of `docs/PROJECT_STATE.md`;
3. the concrete user request;
4. current source, configuration, logs, and focused tests for the touched path;
5. affected rows in `docs/SPEC_COVERAGE_MATRIX.md`;
6. `docs/IMPLEMENTATION_QUEUE.md` when a task is active;
7. `docs/ARCHITECTURE_OVERVIEW.md` when architecture or task direction is at issue;
8. detailed SPEC sections only for the boundary actually touched.

Current source/API/runtime evidence outranks model output, community hints,
historical artifacts, plans, diagrams, and frozen documents.

## 3. Task Entry And Capability-First Work

- Do not execute platform expansion without a concrete product capability, real
  Mod request, observed failure, demonstrated safety defect, or bounded product
  decision requiring evidence.
- Unless the user explicitly asks for audit, documentation, or closure, each
  implementation turn must prioritize one verifiable new capability. Risk notes,
  schema cleanup, and narrower claims do not substitute for capability delivery.
- Prefer the smallest real vertical result. Reuse existing control-plane
  contracts and add infrastructure only for a failure observed in that result.
- After the selected capability succeeds, stop infrastructure work and return
  to the product mainline.
- Do not revive queued, frozen, formal-validation, Dense/RRF, Dashboard, MCP,
  memory, or Agentic work merely because it appears in an older roadmap or SPEC.

## 4. Architecture Guardrails

- Keep one LangGraph `StateGraph` as the workflow control plane. Conditional
  edges own final routing.
- Specialist roles, including Planner, Evidence, Reviewer, and ProposalCritic,
  operate inside that graph. They do not receive independent write or route
  authority.
- Use same-level specialist fan-out only when a concrete request has separable
  risk dimensions whose independent assessment can change a decision. Do not
  create an always-on multi-agent swarm for architectural appearance.
- Define specialist dimensions from the selected product request. Fraud-domain
  labels such as merchant, device, or network risk are not generic platform
  modules; use them only when the actual target domain requires those facts.
- Give each specialist a bounded context pack with registered Artifact refs,
  hashes, and necessary evidence excerpts. Require structured findings,
  supporting refs, unknowns, limitations, and a recommended action. A returned
  summary without traceable refs is not decision evidence.
- Specialists may not write files, select authoritative paths or Hooks, approve
  diffs, launch builds/runtime, or choose LangGraph routes. Deterministic fusion
  validates their outputs; conditional edges retain final route authority.
- Keep ReAct as an optional bounded strategy inside a specialist node. Do not
  replace the top-level controlled Workflow with ReAct without a recorded real
  failure and an explicit architecture decision.
- The ProposalCritic local/injected assessment boundary may read registered
  upstream artifacts and emit a structured score,
  verdict, findings, and limitations. It cannot authorize writes, change paths,
  bypass ProposalReviewer, or override human approval.
- Deterministic policy must fuse ProposalCritic output with binding, permission,
  risk, review, runtime, and evaluation gates. High ProposalCritic scores never
  override hard blockers.
- ProposalCritic is controlled only by explicit `critic_requirement`:
  `not_required` does not call it; `required` must produce a valid current-bound
  assessment or the path blocks. Do not infer requirement from risk wording,
  request type, or provider availability.
- Apply `proposal_critic_local_injected_v1` only to patch proposal review. Its
  four dimensions have equal 25 percent weight and require a rounded mean of at
  least 80 plus verdict `pass`. Hard ProposalReviewer rules always take priority.
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
- For two-level Critic design, current implementation stops at deterministic
  ProposalReviewer rules plus the optional ProposalCritic local/injected
  assessment inside `review_proposal`. Worker self-check, parallel specialist
  scoring, deterministic multi-Worker fusion, and a clean-context second-level
  Critic are `documented_only`. Trigger them only after a real task exposes a
  material cross-context review failure or requires separate retry, timeout, or
  context isolation.
- For business action translation, the existing Mod workflow decisions,
  repair/blocked routes, exact-diff approval, and acceptance-bound
  runtime/evaluation applicability are `implemented`. A generic low/medium/high/
  grey-zone risk engine and dynamically learned business thresholds are
  `documented_only`. Add a new action rule only when a selected request cannot
  be represented by current deterministic routes.
- For long-term memory, ArtifactStore, hashes, Git history, and LOOP_HISTORY are
  implemented audit storage, not learned memory. Verified-lesson extraction,
  asynchronous outcome feedback, experience retrieval, Recall/Precision-driven
  iteration, threshold tuning, and policy learning are `documented_only`.
  Trigger a bounded memory experiment only after repeated provenance-bound real
  outcomes show the same failure and manual lessons are insufficient.
- A conditional trigger never activates the whole reference architecture and
  never overrides the current queue, permission, disclosure, write, runtime, or
  claim boundaries.

## 5. Evidence, Models, And Writes

- Retrieval relevance never grants write authority.
- The Binding Registry and current live source determine writable targets.
- Model-generated paths or copied path strings are not authority.
- Dry-run must not write. Real apply requires the exact displayed approval hash
  and a fresh live-source/binding check.
- Sending source or other local material to an external model requires explicit
  per-run consent covering the exact data classes. Never expose API key values.
- A model-based ProposalCritic requires the same disclosure consent; a local or
  test ProposalCritic must be labelled as such.
- Game launch, game-directory copy, and gameplay evidence require separate
  explicit approval.

## 6. Verification And Claims

- Run focused tests proportional to the touched behavior and record the exact
  command and result in the relevant control documents when the task changes a
  tracked capability.
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
