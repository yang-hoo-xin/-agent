# Agent Engineering Harness Transition

Status: non-normative transition program

Program direction: user-approved bounded product decision

Prepared: 2026-07-25

Current implementation authority effect: H1.1 promoted through Phase B

First selected migration boundary:
H1.1 / `AGENT-HARNESS-BUILD-RUNTIME-HANDOFF-001`

Implementation entry status: H1.1 complete; no later boundary active

## 1. Purpose And Authority

This file defines a bounded transition from the current controlled Mod delivery
platform toward a production-oriented Agent Engineering Harness. It is a
transition guide, not a second product contract, workflow, implementation
queue, or source of current capability claims.

The engineering motivation is to reduce the cost and ambiguity of long-running
Agent work: a failed late stage must not force repeated model, Proposal, Apply,
or Build work; continuation must be reproducible; side effects must be admitted
and recoverable at their declared evidence level; and domain Runtime behavior
must remain replaceable without copying the control plane. The Harness
Evolution Program is an approved bounded product direction. That decision
permits evidence-producing migration work, but it does not pre-approve any
specific implementation, permission, side effect, or capability claim.

The working notes from 2026-07-23 are mandatory design-review input. They are
not product facts, architecture authority, implementation evidence, or task
authorization. Each concern from those notes must be checked against current
source, focused tests, configuration, and bound run Artifacts before it can
affect an architecture status or implementation task.

Authority remains with the repository reading order in `AGENTS.md`. This file
must not override:

- `docs/ACTIVE_PRODUCT_CONTRACT.md`;
- `docs/PROJECT_STATE.md`;
- current source and focused tests;
- `docs/SPEC_COVERAGE_MATRIX.md`;
- `docs/IMPLEMENTATION_QUEUE.md`;
- `docs/ARCHITECTURE_OVERVIEW.md`;
- the detailed control contracts in `DEV_SPEC.md`.

Only three architecture reference states are used:

- `implemented`: current source plus focused evidence supports the exact claim;
- `documented_only`: a responsibility or target is described but is not current
  behavior or an implementation task;
- `conditional_trigger`: implementation is forbidden until a named product
  capability, observed failure, demonstrated safety defect, or bounded product
  decision requiring evidence activates the smallest required boundary.

## 2. Transition Baseline Gate

Before H1.1 implementation begins, the implementation worktree must contain one
reviewed and committed baseline that includes the latest accepted Phase 2B
status, Runtime deployment/restoration behavior, marker-observation repair,
Artifact contracts, and related focused tests.

The current Harness transition worktree and the supplied latest Runtime
worktree diverge after a shared Git checkpoint. The supplied Runtime worktree
also contains uncommitted source, tests, Artifacts, and control-document
changes. H1.1 must not be implemented against an older Runtime boundary merely
because this transition file exists.

Baseline reconciliation is complete only when:

1. the intended source versions are identified by Git commit and reviewed diff;
2. unrelated user changes remain preserved;
3. Runtime deployment/restoration source and tests are present when their
   documented claims are retained;
4. current Phase 2B and queue status agree across the authority documents;
5. focused Runtime and Artifact tests pass from that exact worktree;
6. `git diff --check` passes;
7. the selected implementation worktree is explicitly recorded.

This gate may reconcile, commit, or deliberately reject supplied changes. It
must not silently copy documents while omitting the source and tests that make
their claims true.

## 3. Responsibility Boundary

### 3.1 Agent Engineering Harness

The project-level Harness owns:

- request and acceptance-boundary admission;
- source, environment, permission, run, and attempt identity;
- the existing LangGraph `StateGraph` and its conditional routes;
- Artifact refs, hashes, freshness, and durable lineage;
- checkpoint, handoff, resume validation, and idempotence;
- model and tool admission boundaries;
- review, dry-run, approval, apply, and Build gates;
- failure ownership, bounded Repair routing, evaluation, and terminal
  classification;
- context, tool-output, and trace budgets required to keep a run inspectable.

### 3.2 Domain Runtime Verification Provider

A Runtime provider owns only domain-specific execution and observation:

- capability preflight for the selected environment;
- verified deployment and restoration when required;
- process launch, liveness, termination, and cleanup;
- environment-specific logs, markers, screenshots, and behavior observations;
- a graph-compatible RuntimeEvidence payload with explicit limitations.

The GTFO provider does not own run lifecycle, checkpoint policy, graph routing,
Repair authorization, evaluation authority, or terminal success.

### 3.3 Stable And Replaceable Boundaries

Stable contracts include:

- run and request identity;
- source and Build Artifact identity;
- `ArtifactRef`, complete hash, and stale-lineage checks;
- explicit authorization and disclosure boundaries;
- checkpoint and resume binding;
- observation source, time/byte window, and limitation;
- RuntimeEvidence, evaluation, restoration outcome, and terminal lineage.

Replaceable domain behavior includes:

- executable and working-directory selection;
- loader, plugin, configuration, and log layout;
- startup and acceptance markers;
- process and screenshot collection details;
- environment-specific cleanup and restoration mechanics.

No domain implementation may promote itself into the stable core merely
because it is the first verified provider.

## 4. Target Structure

```text
Agent Engineering Harness
|
+-- Policy And Governance Overlay
|   +-- deterministic admission, permission, disclosure, approval, retention,
|       route authority, and claim ceiling across every boundary
|
+-- Thin Admission / Lifecycle Boundary
|   +-- request, source, environment, permission, run, attempt
|
+-- Existing LangGraph StateGraph
|   +-- nodes, conditional routes, interrupts, Repair, Terminal
|
+-- Working-State And Durability Boundary
|   +-- ArtifactStore, checkpoint, handoff, continuation, lineage
|   +-- target: side-effect attempt journal and crash-safe re-admission
|
+-- Model And Tool Execution Boundary
|   +-- provider-neutral turns, bounded context, structured tool feedback
|
+-- Delivery Boundary
|   +-- Proposal, Review, Dry-run, Approval, Apply, Build
|
+-- Runtime Verification Boundary
|   +-- stable RuntimeEvidence contract
|   +-- replaceable GTFO execution and observation behavior
|
+-- Evaluation And Diagnostic Boundary
    +-- deterministic gates, trace, failure evidence, terminal claim ceiling
```

This diagram describes responsibility composition. It does not require each
box to become a service, graph, registry, database, or independently deployed
module. The Policy And Governance Overlay is a cross-cutting view of existing
deterministic contracts, not a new policy engine, route owner, or second control
plane. The unified overlay is `documented_only`; each constituent gate retains
its separately evidenced status and current owner. The target diagram is
intentionally more complete than the current implementation; architecture
presence never bypasses Migration Boundary admission.

### 4.1 Three State Layers And Atomic Context Refresh

The Harness separates three state layers:

```text
Active Context
  the bounded input sent to one model/tool turn

Working State
  graph state, run-local files, registered Artifacts, checkpoint, and progress

Durable Project Guidance
  reviewed AGENTS.md rules, authority documents, Git checkpoints, and
  evidence-bound reusable guidance
```

**Active Context** manages the current responsibility. Each model-bearing node
must construct a fresh bounded context pack from the immutable goal, exact
Artifact refs/hashes, the latest relevant observation, current budget, and the
node's output contract. It must not inherit an unbounded conversation merely
because the previous node saw it. This is the product equivalent of atomic
task-context refresh.

Sliding windows, compaction, and interactive rewind are client techniques, not
portable repository contracts. When equivalent behavior is needed:

- a window retains only the turns required by the current node contract;
- a compacted summary is derived data with source refs, limitations, and an
  invalidation rule, never the only durable copy of a decision;
- a rewind restores or forks from a validated checkpoint and marks later
  outputs non-authoritative without deleting immutable audit history.

No universal percentage of a context window is an acceptance threshold. The
budget must be measured for the selected provider/model/task, and the Harness
must disclose truncation or summarization before information is lost.

**Working State** manages the selected run. Long-running work must expose
inspectable progress through existing queue/state documents, graph checkpoints,
and registered Artifacts. A run-local plan or scratch file may be used when it
reduces context load, but it is not route or approval authority. Temporary
search output, logs, and generated excerpts must be archived as registered
evidence when needed for claims, or removed after the round when they have no
continuing audit value.

**Durable Project Guidance** manages later sessions. A new session reconstructs
authority from reviewed control documents, exact Git commits, Artifact
refs/hashes, and the selected checkpoint/handoff. Git commits bind source
history but do not replace graph state or Runtime evidence. `AGENTS.md` remains
minimal and project-specific; Skills remain evaluated process guidance. Neither
becomes an automatic store of model reasoning.

## 5. Mandatory Harness Design Lenses

Every Migration Boundary review must address every row below. A row may be
not applicable to the selected boundary, but it may not be silently omitted.

| Lens | Current bounded evidence | Transition rule |
| --- | --- | --- |
| Model behavior profile | Provider-neutral structured turns and bounded output settings are `implemented` at their recorded paths; one universal role-based sampling policy is `documented_only` | Bind model identity, provider, output/context budget, structured-output contract, fallback, and retry. Model replacement requires the same contract tests and one bounded task evaluation; do not copy universal sampling or repetition values across providers or roles |
| Active context | The Evidence loop's compact trajectory, latest full observation, byte accounting, and bounded correction are `implemented`; a repository-wide compaction system is `conditional_trigger` | Build a fresh node-specific context pack; preserve decisions and refs rather than full dialogue. Compaction must disclose sources and loss; checkpoint restore replaces destructive audit deletion |
| Working state | ArtifactStore business outputs and graph runtime state are `implemented`; persistent cross-process graph resume is `documented_only` | Large or reusable intermediate results belong in run-local files or registered Artifacts. Progress must be inspectable across sessions, and disposable scratch state must be cleaned after its retention need ends |
| Durable project guidance | Reviewed `AGENTS.md`, Git history, control documents, and Artifact history are `implemented` audit inputs; automatic experience extraction is `conditional_trigger` | Persist only project-specific, evidence-bound guidance. Git, Artifact history, Skills, and instructions keep distinct authority and invalidation rules |
| Loop semantics | Conditional routing, retry budgets, deterministic gates, and RepairPlan are `implemented` at their recorded boundaries | Prefer one hypothesis and one discriminating check over blind retry. Refresh context at atomic task boundaries and do not require a heavyweight plan for a one-step deterministic action |
| Tool I/O hygiene | Several model, log, trace, and Runtime paths have bounded output and structured summaries; a universal tool-output middleware is `conditional_trigger` | Persist large raw evidence, return a bounded summary plus ref/hash, preserve the error type, failing test, relevant frame, and truncation disclosure. Numeric line/byte thresholds require measurement rather than note-derived constants |
| Tool-chain capability ceiling | Structured model turns, exact tool schemas, source identity, and bounded evidence tools are `implemented` at recorded paths; automatic tool expansion is `conditional_trigger` | Evaluate whether failure comes from model reasoning, missing tool affordance, lossy tool representation, or bad feedback before changing the model or adding a tool |
| Deterministic acceptance | Review, no-write Dry-run, exact approval, Apply, Build, RuntimeEvidence, Eval, and Terminal gates are `implemented` at their recorded claim levels | Key nodes automatically validate required upstream refs, hashes, permissions, and output shape before conditional routing. Model confidence and narrative never override a hard blocker |
| Permission and isolation | Per-action approvals, source disclosure, local-model admission, isolated Apply, Runtime launch, and game-directory-write gates are `implemented` at their recorded paths | Every resumed side effect requires current authorization. A checkpoint records state, not permission to repeat an action |
| Host safety boundary | Run-local workspaces and permission gates are `implemented` at bounded paths; a complete container/VM security boundary is `documented_only` | Do not describe a filesystem copy or subprocess wrapper as a sandbox. Secrets, user profiles, network access, dependency installation, destructive Git, and external side effects retain separate environment-level controls |
| Structural constraints | Binding Registry, allowed roots, forbidden paths, schema validation, focused tests, and diff checks are `implemented` at bounded paths; universal file/function-size limits are `conditional_trigger` | Enforce constraints through current source contracts, linters, tests, and reviewed policy. Do not copy arbitrary size limits into prompts unless a repeated maintainability failure and regression test justify them |
| Replaceability and removal | Model adapters, `runtime_evidence_factory`, DomainAdapter, and GTFO/unsupported domain seams are `implemented` at their recorded boundaries | Keep experimental behavior behind existing injection seams, avoid core-schema pollution, preserve readable persisted Artifacts, and require a removal path. Extend a seam only after a real incompatibility; do not create a parallel registry or workflow |
| Retrieval threshold | Live `rg` plus file reads is the active default; deeper retrieval is `conditional_trigger` | Use whole-file/exact-symbol reads while bounded. Add BM25 only after repeated corpus-scale lexical-ranking need, embedding/vector retrieval only after measured synonym or cross-language misses, and a database only after required multi-field queries, concurrency, or transactional recovery cannot be represented safely by current files/ArtifactStore |
| Context integrity | Whole-file and exact-symbol evidence with source hashes is `implemented` at bounded paths; generic chunk reconstruction is `conditional_trigger` | Prefer whole files when they fit. Every excerpt/chunk must retain file identity, revision/hash, offsets or symbol identity, truncation state, and enough neighboring context to detect a torn interpretation |
| Specialist use | Bounded specialists inside the existing graph are permitted by current architecture; an always-on specialist cluster is `conditional_trigger` | Use independent specialist assessment only when separable risk dimensions can change one real decision. Atomic context refresh does not itself justify spawning another Agent |
| Skill discipline | Process-only Skills with no route or write authority are `implemented`; systematic with/without Skill evaluation is `documented_only` | Add or retain a Skill only when repeated project-specific execution shows value and a focused evaluation can detect negative contribution |
| Failure corpus and improvement | Immutable failure Artifacts, traces, attempts, RepairPlan, and Git history are `implemented` audit data; automatic training or policy mutation is `conditional_trigger` | A failure may become a versioned evaluation case only with request, source, environment, action, outcome, limitations, and invalidation conditions. Dataset use never grants automatic prompt, threshold, or policy changes |
| Maintenance and drift | Hash, freshness, Binding, test, and documentation checks are `implemented` at bounded paths; an autonomous garbage-collection or maintenance role is `conditional_trigger` | Run deterministic consistency checks in the selected workflow and the Phase B document repair. Add a separate maintenance role only after repeated drift escapes those checks and blocks a selected result |
| Side-effect recovery | Run-scoped Runtime deployment and restoration records are `implemented` in the latest supplied Runtime boundary; a durable side-effect attempt journal is `documented_only` until separately admitted | Resume only when prior side-effect state is proven clean or safely restored. Unknown physical state blocks re-execution. The approved Harness direction may admit journal work from an observed residue/process-death failure, a demonstrated recovery defect, or an explicit crash-recovery product postcondition paired with focused proof that the current record cannot satisfy it |

The lenses constrain design quality. They are not independent product lines or
automatic Migration Boundaries.

## 6. Migration Boundary Map

```text
F0 Contract And Governance Foundation
  program invariant; no queue item
        |
        v
H1 Durable Execution Boundary
  |
  +-- H1.1 Validated BuildResult -> Runtime Continuation
  |     first selected implementation boundary
  |
  +-- H1.2 Side-Effect-Aware Runtime Recovery
        documented_only; requires separate admission

Later admission pool; no fixed automatic sequence
  +-- H2 Run / Attempt / Terminal Lifecycle Identity
  |     conditional_trigger
  |
  +-- H3 Failure Ownership / Repair Routing
  |     conditional_trigger
  |
  +-- H4 Runtime Provider Contract Hardening
  |     conditional_trigger
  |
  +-- H5 Evaluation Boundary
  |     conditional_trigger
  |
  +-- H6 Diagnostic Observability Boundary
        conditional_trigger
```

The diagram expresses known containment and possible capability dependencies,
not an automatic implementation roadmap. Completion of H1.1 activates neither
H1.2 nor H2-H6.

After every completed boundary, Phase B must finish and a new admission review
may select at most one next boundary. Selection requires a named product
capability, observed failure, demonstrated safety defect, bounded product
decision requiring evidence, or a verified result from the prior boundary that
proves the next capability is necessary. The Program may therefore progress
without waiting for avoidable production damage, but it may not progress merely
because a box exists in this map.

### F0: Contract And Governance Foundation

F0 is the responsibility and governance invariant in sections 3-5. It is not
code, a schema freeze, an implementation task, or a claim that the target
structure is fully implemented. Existing deterministic policies remain
distributed across Admission, permissions, approval, Artifact validation,
conditional routes, Eval, and Terminal; F0 does not consolidate them into a
second authority.

### H2: Run / Attempt / Terminal Lifecycle Identity

Activate when two supported entries cannot bind one concrete product run,
attempt, stage, Artifact lineage, and terminal outcome without contradiction,
or when the approved Harness lifecycle postcondition cannot be tested through
the current identities.

Align only the identities involved in that failure or postcondition. Do not
introduce a new unified RunState or Lifecycle Service when the existing graph
and Artifact representation can express the required facts.

### H3: Failure Ownership / Repair Routing

Activate when a real or focused failure assigns an observation, environment,
provider, Build, product-behavior, or permission failure to the wrong repair
owner and that error causes an invalid source repair, repeated expensive stage,
or false terminal classification. A focused failure injection is sufficient
when it demonstrates the safety or routing defect without causing avoidable
external damage.

Reuse existing conditional routes, RepairPlanner, `repair_plan`,
RuntimeEvidence, Eval, and Terminal contracts. Do not create a second exception
hierarchy or repair controller merely for uniform naming.

### H4: Runtime Provider Contract Hardening

Activate when a selected real Runtime, focused provider-contract test, or
approved provider-replaceability postcondition exposes a fact that the existing
factory and RuntimeEvidence contracts cannot represent without leaking
domain-specific behavior into generic workflow code.

Do not add a parallel adapter registry or generic provider hierarchy before
that incompatibility exists.

### H5: Evaluation Boundary

Activate when a real or focused accepted/rejected result cannot be classified
truthfully by the current acceptance contract, RuntimeEvidence, EvalReport, and
claim ceiling, or when an approved regression postcondition requires a missing
deterministic comparison.

Evaluation answers whether the bound result meets the request. It does not
replace trace or Runtime observation.

### H6: Diagnostic Observability Boundary

Activate when a selected real or focused failure cannot be located or
reconstructed because one exact trace, timing, cost, tool-call, truncation, or
ownership fact is absent, or when an approved inspectability postcondition
requires that exact signal.

Add only the missing signal and its redaction/retention rule. Do not create a
separate operations control plane.

## 7. H1 Durable Execution Definition

H1 defines the complete durable-execution direction through two independently
admitted increments:

- **H1.1 Validated Build-to-Runtime Continuation** persists and validates the
  completed Build boundary before any new Runtime side effect. It is the only
  selected implementation slice.
- **H1.2 Side-Effect-Aware Runtime Recovery** persists the state transitions
  required to determine whether an interrupted Runtime attempt may be cleaned,
  restored, resumed, or blocked. It is part of the target architecture but is
  not a current queue item and is not activated by H1.1 completion alone.

This separation keeps the first implementation atomic without misrepresenting
pre-side-effect continuation as complete arbitrary-crash recovery.

### 7.1 H1.1 Observed Trigger

The preserved automated Runtime failure cannot be resumed through a supported
current product entry:

- no matching `workflow_checkpoint` or `resume_report` exists;
- the CLI exposes no Runtime-boundary resume entry;
- a fresh full request repeats planning, model, Proposal, Apply, and Build;
- a direct Runtime-provider call does not prove the existing LangGraph,
  Artifact, Eval, WorkflowSummary, and Terminal chain;
- the available Runtime evidence is diagnostic history, not resume
  authorization.

This is a real repetition and recovery boundary. It supports H1.1 but does not
authorize mutation of an immutable historical run.

### 7.2 H1.1 Target Postcondition

Given one successful, current, source-bound `build_result`, a fresh process can
load a persistent handoff, validate it, obtain new Runtime authorization, and
continue through the existing `collect_runtime_evidence` node without
repeating any upstream model or delivery stage.

The resumed result must retain one truthful run lineage from request and Build
through RuntimeEvidence, applicable Eval/WorkflowSummary, and Terminal.

### 7.3 H1.1 Reused Contracts

H1.1 must reuse:

- the existing LangGraph `StateGraph`;
- `ArtifactStore` and `ArtifactRef`;
- complete content hashes and recursive freshness validation;
- `WorkflowCheckpointStore`;
- `ResumeValidator`;
- `workflow_checkpoint`;
- `resume_report`;
- `feature_spec`;
- `build_result`;
- the current Runtime factory injection boundary;
- `runtime_evidence`;
- the existing Runtime, Eval, Repair, WorkflowSummary, and Terminal routes;
- current permission/admission and Runtime deployment/restoration checks.

H1.1 must not introduce another workflow, lifecycle authority, Runtime registry,
or general checkpoint platform.

### 7.4 H1.1 Handoff Inputs

The persistent handoff must bind:

- original request, feature, and run identity;
- checkpoint stage and intended next graph node;
- exact `feature_spec` and `build_result` refs and hashes;
- all upstream Artifact refs/hashes required to reconstruct the existing state;
- source/environment identity required by the Build and Runtime boundary;
- state fields required by the existing graph after Build;
- consumed-resume evidence;
- limitations and the explicit fact that old permissions are not reusable.

The implementation must derive exact field names from current contracts. This
transition does not authorize guessed schema keys.

### 7.5 H1.1 Continuation Validation

Before graph execution, the supported resume entry must:

1. load the immutable checkpoint through ArtifactStore;
2. validate checkpoint content hash and schema;
3. validate run, request, feature, and checkpoint stage;
4. validate exact Artifact refs and hashes;
5. perform recursive stale-lineage validation;
6. reject a consumed checkpoint across fresh process instances;
7. re-run Runtime capability preflight;
8. acquire fresh launch and write authorization for every requested side
   effect;
9. verify current Build bytes and Runtime destination/pre-state;
10. block on unknown deployment, process, cleanup, or restoration state;
11. reconstruct only the graph state needed after Build;
12. enter the existing graph as the completed Build boundary.

### 7.6 H1.1 Side-effect Semantics

H1.1 provides at-least-once continuation admission with fail-closed side-effect
checks. It does not claim exactly-once Runtime execution or automatic recovery
under arbitrary process death.

- No side effect begins while handoff validation is incomplete.
- Checkpoint permission cannot authorize deployment or launch.
- A prior Runtime attempt may be repeated only when its persisted evidence
  proves restoration and cleanup, and a new authorization is present.
- Missing or incomplete Runtime evidence after a possible physical action is
  unresolved physical state and blocks automatic retry.
- Deployment hash drift, running process ambiguity, backup ambiguity,
  restoration failure, or environment drift blocks before re-execution.

A durable side-effect attempt journal belongs to H1.2, not H1.1. H1.2 may enter
admission from an observed process-death or residue failure, a focused failure
injection that demonstrates the same safety defect, or an explicit bounded
product decision requiring crash-safe Runtime continuation paired with source
proof or a focused failure injection showing that the current record cannot
provide that postcondition.

### 7.7 H1.2 Side-Effect-Aware Runtime Recovery Target

H1.2 is `documented_only` until a separate admission record exists. Its target
postcondition is:

> After a process interruption at any declared Runtime side-effect boundary, a
> fresh process can reconstruct the last durably proven physical state and make
> one deterministic decision: continue an unstarted action, verify and complete
> cleanup/restoration, or block for human recovery. It never guesses that an
> external action did or did not occur.

H1.2 must reuse ArtifactStore revision history, the existing graph routes,
Runtime deployment/restoration evidence, permission admission, RuntimeEvidence,
Eval, and Terminal. The durable record must capture the semantic facts required
to prove:

- the owning run and distinct Runtime attempt;
- the intended action and its pre-state;
- source, destination, backup, and relevant content hashes;
- whether deployment, process launch, cleanup, and restoration were unstarted,
  started, completed, failed, or unresolved;
- process identity and observation limits when a process may exist;
- the latest durable transition, its time/order, and its Artifact lineage;
- the fresh permission required before any continued external action.

Exact Artifact names, schema keys, and graph fields must be derived from the
implementation contracts during admission; this target does not authorize
invented identifiers. The journal remains business evidence in ArtifactStore.
It may inform the existing LangGraph route but may not become a second workflow
state authority.

The Harness owns attempt identity, journal admission, Artifact persistence,
permission checks, and routing. The Runtime provider owns the domain action and
reports the transition facts needed by that journal through a narrow injected
recording boundary. Persistence must occur before a declared physical action
and after its observed outcome. The provider may not gain direct route,
permission, evaluation, or terminal authority.

Focused H1.2 acceptance must include interruption injection before and after
each declared physical transition, journal tamper/staleness, ambiguous process
identity, missing backup, restoration failure, fresh-permission denial, and
proof that no upstream model, Proposal, Apply, or Build stage repeats. It does
not require claiming exactly-once behavior for an external process that cannot
provide an idempotency contract.

### 7.8 H1.1 Context And Tool Feedback

Resume reconstructs state from registered Artifacts and bounded summaries. It
must not replay the historical full conversation, raw model transcript, or
complete Runtime log into model context.

Runtime output must preserve:

- bounded structured observations used by acceptance;
- source/window identity and truncation disclosure;
- Artifact refs/hashes for larger retained evidence;
- concise failure type and limitation data.

No model call is required to validate, reconstruct, or execute H1.1.

### 7.9 H1.1 Non-goals

H1.1 does not implement:

- H1.2;
- H2-H6;
- a general Lifecycle Service;
- a new RunState;
- a new Runtime provider abstraction;
- arbitrary mid-node replay;
- automatic source repair;
- model retry or model switching;
- automatic reusable-lesson extraction;
- a new retrieval subsystem;
- autonomous maintenance;
- a real Runtime launch during local implementation acceptance.

## 8. H1.1 Focused Acceptance

H1.1 local acceptance must construct a fresh-process simulation using new
ArtifactStore, checkpoint/resume, and graph instances.

Required positive path:

1. a successful Build writes a persistent Runtime handoff;
2. the original process stops;
3. a fresh process loads the handoff;
4. fresh Runtime admission is supplied;
5. the graph continues at `collect_runtime_evidence`;
6. RuntimeEvidence binds the original run and exact Build hash;
7. applicable Eval/WorkflowSummary/Terminal artifacts retain that lineage.

Required non-repetition assertions:

- Evidence execution count remains zero;
- model call count remains zero;
- Proposal generation count remains zero;
- Review count remains zero;
- Dry-run count remains zero;
- Apply count remains zero;
- Build count remains zero.

Required negative paths:

- wrong run, request, feature, or stage;
- missing Artifact ref or hash;
- tampered checkpoint or upstream Artifact;
- stale direct or deep upstream lineage;
- Build bytes changed after checkpoint;
- consumed checkpoint from a new process instance;
- missing fresh Runtime authorization;
- deployment destination drift;
- prior restoration not proven;
- ambiguous running process or cleanup state;
- Runtime failure remains truthful and does not become source-repair authority.

Focused test scope after baseline reconciliation:

- `tests/unit/test_workflow_graph.py`;
- `tests/unit/test_repair_checkpoint_smoke.py`;
- `tests/unit/test_runtime_evidence.py`;
- `tests/unit/test_runtime_deployment.py`;
- `tests/unit/test_local_entry.py`;
- `tests/unit/test_mod_agent_cli.py`.

The exact command must be recorded in the authority-document repair pass. Unit
tests prove only local H1.1 behavior. A later real Runtime closure requires
separate launch and game-directory permissions and stops after one accepted
result or one immutable failure.

## 9. Migration Boundary Admission Template

Every later boundary must complete this template before queue entry:

1. **Concrete entry basis**: selected user capability, preserved real failure,
   demonstrated safety defect, bounded product decision requiring evidence, or
   a verified prior-boundary result that proves the capability dependency.
2. **Current failing seam**: exact class, Artifact, node, entry, or permission
   boundary.
3. **Evidence**: source/test/run refs and the narrow claim they support.
4. **Input representation**: what information is preserved, summarized, or
   lost.
5. **Target postcondition**: one externally inspectable behavior that becomes
   true.
6. **Reused contracts**: existing classes, Artifacts, graph nodes, routes, and
   permissions.
7. **State/Artifact delta**: smallest durable change required.
8. **Context and tool-I/O effect**: budget, truncation, persistence, and
   feedback shape.
9. **Side effects and idempotence**: repeatable, non-repeatable, newly
   authorized, and fail-closed actions.
10. **Failure ownership**: which layer owns each failure and which layer may
    repair it.
11. **Focused acceptance**: positive, negative, stale, tamper, permission, and
    no-repeat tests.
12. **Claim ceiling**: what the evidence does not prove.
13. **Non-goals**: adjacent boundaries that remain inactive.
14. **Stop condition**: exact success or immutable failure that ends the round.
15. **Rollback/removal**: which implementation is replaceable and which
    persisted contract must remain readable.
16. **Authority-document repair plan**: documents that change only after the
    implementation result exists.

If the concrete entry basis, target postcondition, focused acceptance, permission
boundary, or stop condition is absent, the boundary remains `documented_only`
or `conditional_trigger`.

## 10. Per-Round Closure And Promotion

Every Migration Boundary uses two explicit phases.

### Phase A: Capability And Evidence

1. select exactly one boundary and freeze its non-goals;
2. reconcile the implementation baseline;
3. implement the smallest real capability;
4. run focused tests and proportional static checks;
5. perform separately authorized real verification only when required;
6. stop at the first accepted result or immutable failure;
7. preserve the exact source, test command, result, Artifact, and limitation
   evidence.

Phase A may change source and tests. It must not pre-promote capability claims
in normative documents.

### Phase B: Authority-Document Repair

After Phase A stops, perform a separate review pass:

1. reread current source, focused test output, and produced Artifacts;
2. update `docs/PROJECT_STATE.md` with the observed result;
3. update affected rows in `docs/SPEC_COVERAGE_MATRIX.md`;
4. update `docs/ARCHITECTURE_OVERVIEW.md` only for verified responsibility or
   maturity changes;
5. update `docs/ACTIVE_PRODUCT_CONTRACT.md` only when the daily product claim or
   non-negotiable boundary changed;
6. close or replace the exact item in `docs/IMPLEMENTATION_QUEUE.md`;
7. append historical detail to `docs/audits/LOOP_HISTORY.md` when appropriate;
8. mark the completed or failed boundary in this Transition;
9. run document consistency checks and `git diff --check`;
10. perform the next-boundary admission review without implementing or
    pre-promoting the reviewed boundary in the same round.

A round is not closed until Phase B is completed or explicitly blocked with
the inconsistency recorded. Phase B cannot repair a failed implementation by
changing prose, weakening acceptance, or widening claims.

### Next-Boundary Re-admission

After Phase B, the Program may select at most one next boundary. The review must
use the section 9 template and the new source/test/Artifact evidence. It may:

- activate one smallest boundary because its entry basis and acceptance are
  complete;
- retain all later boundaries as `documented_only` or `conditional_trigger`;
- return to the Mod product mainline when no Harness boundary is presently
  justified;
- close the Program when the approved target maturity is reached or the user
  ends the direction.

This review is a new product-capability selection after active implementation
has stopped; it is not continuation of the previous infrastructure task. A
Harness boundary may be selected again only as the one current product
capability recorded through the normal queue and authority rules.

No next boundary is activated merely by sequence number, diagram position,
available implementation capacity, or completion of its predecessor. The
Harness direction supplies a legitimate product basis for evidence-producing
work; it does not waive contract reuse, permissions, focused acceptance, or the
one-boundary-per-round rule.

### Promotion Rule

Only verified deltas are promoted:

- stable responsibility changes go to `ARCHITECTURE_OVERVIEW`;
- tested implementation status goes to `SPEC_COVERAGE_MATRIX`;
- current execution state goes to `PROJECT_STATE`;
- the one selected task goes to `IMPLEMENTATION_QUEUE`;
- daily product claims go to `ACTIVE_PRODUCT_CONTRACT`;
- historical detail goes to `LOOP_HISTORY`.

The Transition remains a non-normative migration record. It is not copied
wholesale into mainline authority.

## 11. Program Management State

```text
program_id: AGENT-ENGINEERING-HARNESS-EVOLUTION
program_status: active_direction_h3_admitted
control_plane: existing LangGraph StateGraph
contract_foundation: F0
first_selected_boundary: H1.1 / AGENT-HARNESS-BUILD-RUNTIME-HANDOFF-001
implementation_entry: H1.1 Phase A and Phase B complete
active_later_boundary: H3 / AGENT-HARNESS-RUNTIME-FAILURE-OWNERSHIP-001
automatic_next_boundary: forbidden
round_closure: capability evidence, then authority-document repair
next_boundary_admission: H3 admitted; Phase A not started
```

### H3 Admission: Runtime Failure Ownership And Source-Repair Routing

1. **Concrete entry basis**: preserved real run `ec71c3a5` lost an earlier
   Chainloader marker through Harness output truncation, then stopped at
   `blocked` through `REPAIR_SCOPE_UNRESOLVED`. The later accepted repair
   changed Runtime observation, not Mod source.
2. **Current failing seam**:
   `route_after_runtime_evidence` maps every
   `acceptance_verified=false` result to `create_repair_plan`;
   `_run_create_repair_plan` maps every RuntimeEvidence failure to
   `RepairPlanner.from_runtime_failure`; the planner derives
   `failure_class` from `acceptance_status` or `verification_status` and has no
   owner decision before resolving a source edit binding.
3. **Evidence**: RuntimeEvidence Artifact hash
   `566a8a6554da0211bf7307d499803bea2592f7b3b927d1d6dcc6abe0abe574a6`;
   `run_result.json` hash
   `98a94df597e5f8c05b2acdf3b9767c3bffe4ac923c9588bf61e6fa134d6d1797`;
   focused existing-behavior tests passed 5/5. A wider 80-test command retained
   one already documented retry-budget failure and is not a green baseline.
4. **Input representation**: current RuntimeEvidence preserves acceptance,
   trust, evidence items, provider-specific failure detail, limitations, and
   Artifact lineage, but it does not preserve one provider-neutral decision
   about which layer owns the failure. Reducing all failures to
   `failed`/`inconclusive` loses the distinction required by repair routing.
5. **Target postcondition**: every failed RuntimeEvidence reaching repair
   planning has a durable, inspectable ownership decision. Only a
   product-behavior failure with current bound source evidence may enter the
   existing Proposal/Review repair path. Observation, environment, provider,
   permission, and unknown failures end with owner-specific required actions
   and no source repair.
6. **Reused contracts**: existing RuntimeEvidence and its Artifact hash,
   `RepairPlanner`, `repair_plan`, `route_after_runtime_evidence`,
   `create_repair_plan`, `blocked_report`, Eval, Terminal, ArtifactStore
   freshness, and current permission/admission contracts.
7. **State/Artifact delta**: add the smallest provider-neutral ownership fact
   needed by RuntimeEvidence and persist the decision through existing
   `repair_plan` fields and blockers. Do not add a Workflow state service,
   exception hierarchy, or repair controller.
8. **Context and tool-I/O effect**: ownership is a bounded structured summary,
   not raw log duplication. Existing raw-output truncation and Artifact
   persistence remain unchanged; detailed provider output stays in its current
   evidence location.
9. **Side effects and idempotence**: classification and planning are
   deterministic and no-write outside ArtifactStore. H3 does not automatically
   repeat Runtime, model, Proposal, Apply, or Build. Any later Runtime action
   still requires fresh current admission.
10. **Failure ownership**: product behavior may authorize bounded source repair
    only after existing binding checks; Runtime observation belongs to the
    observation layer; environment belongs to the execution environment;
    provider belongs to the selected Runtime provider; permission belongs to
    Admission/human authority; Build remains on the existing Build route;
    unknown fails closed without source authority.
11. **Focused acceptance**: prove product-behavior positive routing;
    observation, environment, provider, permission, and unknown negative
    routing; missing or malformed ownership fail-closed behavior; Artifact
    hash/tamper rejection; unchanged Proposal/Apply/Build revision counts for
    non-source owners; and preservation of the existing Build repair route.
12. **Claim ceiling**: local deterministic routing only. It does not prove
    semantic root-cause accuracy, real Runtime recovery, cross-environment
    operation, autonomous provider retry, or production concurrency.
13. **Non-goals**: H1.2 side-effect recovery, H2 lifecycle unification, H4
    provider hierarchy, H5 evaluation expansion, H6 tracing expansion,
    additional Runtime providers, model changes, and GTFO acceptance reruns.
14. **Stop condition**: stop at the first focused result that satisfies item 11
    or at one immutable conflict requiring a second control plane, new external
    authority, or unrepresentable provider fact. Then perform Phase B document
    repair and do not select another boundary in the same round.
15. **Rollback/removal**: the deterministic classifier and current GTFO mapping
    remain replaceable modules. Persisted RuntimeEvidence and repair-plan
    Artifacts must remain readable; removal may not reinterpret historical
    hashes or grant source-repair authority to older ownerless evidence.
16. **Authority-document repair plan**: after Phase A, repair
    `PROJECT_STATE`, affected `SPEC_COVERAGE_MATRIX` rows,
    `ARCHITECTURE_OVERVIEW` only if responsibility actually changes,
    `ACTIVE_PRODUCT_CONTRACT` only if the daily contract changes,
    `IMPLEMENTATION_QUEUE`, `LOOP_HISTORY`, and this Transition.

This admission activates only the bounded H3 task above. It does not claim that
H3 is implemented and does not activate H1.2, H2, or H4-H6.

H1.1 closed with this observed result:

```text
task_id: AGENT-HARNESS-BUILD-RUNTIME-HANDOFF-001
classification: Agent Engineering Harness Migration Boundary H1.1
capability: Continue a fresh process from a validated BuildResult handoff into
  the existing RuntimeEvidence/Eval/Terminal chain without repeating upstream
  model or delivery stages
result: implemented and focused-tested through injected local Runtime evidence
verification: 204 focused tests passed; compileall and git diff --check passed
claim_ceiling: pre-side-effect continuation only; no arbitrary crash recovery,
  concurrent exactly-once guarantee, model call, GTFO launch, or game-directory
  write was exercised
stop_condition: satisfied by Phase A evidence and this Phase B repair
```

This task must not automatically select H1.2 or H2-H6.

## 12. Round And Program Stop Conditions

Stop the active H1.1 implementation round when any of the following is true:

1. H1.1 Phase A and Phase B are complete;
2. H1.1 reaches one immutable blocker requiring new user authority or external
   state;
3. baseline reconciliation cannot establish a truthful source/document/test
   state;
4. implementation would require a second control plane or parallel domain
   registry;
5. the selected capability can be completed by an existing contract without
   migration;
6. the proposed change no longer reduces repeated model, Proposal, Apply,
   Build, or unsafe Runtime work.

Round closure does not automatically close the Harness Evolution Program and
does not automatically continue it. Complete the section 10 re-admission review,
then either select one justified next boundary, return to the Mod product
mainline, or close the Program.

Close the Program when the approved target maturity has been reached, the user
ends or replaces the Harness direction, or evidence proves that further
progress requires a conflicting second control plane or another unacceptable
architecture break. Available implementation capacity and the existence of
later boxes are never sufficient continuation reasons.
