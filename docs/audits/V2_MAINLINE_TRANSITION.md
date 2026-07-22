# V2 Mainline Transition

[PROPOSED] This document is a non-normative transition draft. It does not
  define V2 completion criteria, create a product gate, impose an implementation
  requirement, select a product direction, or change the implementation queue.

## Status labels

[PROPOSED] Each substantive statement in this draft uses exactly one of these
  labels:

- [OBSERVED] Directly recorded by the preserved real-run EvidencePack or trace.
- [SOURCE_CONFIRMED] Confirmed by current registered source inspected for the
  stated claim.
- [INFERRED] A bounded interpretation of recorded evidence.
- [UNKNOWN] Not established by the evidence currently cited here.
- [PROPOSED] A reviewable idea with no normative or queue effect.

[OBSERVED] Current registered source was not inspected during this document
  migration, so this draft contains no SOURCE_CONFIRMED transition claim.

[OBSERVED] Later runtime-path reconstruction, component-responsibility mapping,
  Phase 1 lineage validation, and Phase 2A delivery-canary work occurred after
  the initial migration text above. The later proposed target and the observed
  migration checkpoints are preserved below without upgrading this document to
  normative authority.

## Preserved V2-C evidence boundary

- [OBSERVED] One repaired-path real run completed the bounded intelligent loop
  with capability=true and semantic=true.
- [OBSERVED] The same run recorded convergence=false, readiness=partial, and
  can_generate_patch=false.
- [OBSERVED] The run did not bind source_revision, git_commit, or
  modified_files_hash; its recorded status is source_binding_status=missing.
- [OBSERVED] The run produced no Proposal, Patch, Build, or runtime artifact.
- [INFERRED] This evidence supports freezing V2-C as a validation spike, but it
  does not establish a continuing V2-C product route.

## Runtime-path questions

- [UNKNOWN] Which current entry point initiates the relevant Agent execution.
- [UNKNOWN] Which current path carries intelligent decisions during a real run.
- [UNKNOWN] Which persisted artifacts and trace records are sufficient to
  reconstruct one run from entry to terminal observation.
- [UNKNOWN] Whether more than one current path performs overlapping roles.
- [UNKNOWN] Where evidence continuity first becomes unavailable if the path
  cannot be reconstructed end to end.

## State and control questions

- [UNKNOWN] Where the relevant runtime state is created, updated, persisted,
  and consumed in current source.
- [UNKNOWN] Which current component performs retry, stop, and terminal routing
  in the observed path.
- [UNKNOWN] Whether the recorded V2-C loop shares those responsibilities or is
  isolated experimental scaffolding.
- [INFERRED] Resolving these questions may clarify whether existing paths can be
  described consistently without introducing a new state model.

## Reviewable runtime-path shapes

- [PROPOSED] Shape A: document the existing graph-centred path if source and
  trace show that one graph already carries entry, routing, and terminal state.
- [PROPOSED] Shape B: document an existing admission facade feeding the graph if
  source and trace show a stable pre-graph control boundary.
- [PROPOSED] Shape C: document separate control, intelligent-execution, and
  evidence paths if source shows that no single current path owns all three.
- [PROPOSED] None of these shapes is selected, canonical, required, or a reason
  to create implementation work.

## Later proposed V2 target architecture

[PROPOSED] The review direction developed after the initial runtime-path shapes
is the following responsibility flow. It is a target shape for evaluating
incremental migration, not a declaration that every box exists as a separate
module or service:

```text
[PROPOSED] User / Product Request
        |
        v
[PROPOSED] Thin Admission / Lifecycle Boundary
        |
        v
[PROPOSED] LangGraph Runtime Core
        |
        v
[PROPOSED] Intelligence Components
        |
        v
[PROPOSED] Verification Layer
```

### Thin Admission / Lifecycle Boundary

- [PROPOSED] Accept the concrete user or product request.
- [PROPOSED] Bind the approved source, worktree, Source Registry identity, and
  source revision or snapshot identity before execution.
- [PROPOSED] Create or bind run identity and preserve one lineage across the
  selected execution.
- [PROPOSED] Record authorization and external-disclosure boundaries before the
  affected action occurs.
- [PROPOSED] Bind the terminal record to the same request, source, authorization,
  run, and produced Artifact lineage.
- [PROPOSED] Do not own graph-internal routing, intelligence decisions, or node
  retry/repair decisions.
- [PROPOSED] Do not replace the LangGraph runtime or imply a separately deployed
  Lifecycle Service.

### LangGraph Runtime Core

- [PROPOSED] Reuse the existing LangGraph StateGraph as the single runtime
  orchestration core.
- [PROPOSED] Keep node orchestration, conditional routing, runtime state
  transitions, retry/repair routing, and applicable runtime verification gates
  inside that control plane.
- [PROPOSED] Do not make the graph responsible for an external product-lifecycle
  service, multi-user task administration, or a general scheduling platform.

### Intelligence Components

- [PROPOSED] Keep planning, evidence discovery, retrieval, implementation
  planning, Proposal generation, patch generation, and build planning as
  bounded capabilities used by the runtime.
- [PROPOSED] Intelligence components provide structured outputs and evidence;
  they do not independently authorize writes or select the final graph route.
- [PROPOSED] Reuse existing components before adding another orchestration or
  execution framework.

### Verification Layer

- [PROPOSED] Runtime verification supplies facts that may affect the current
  continue, block, repair, or terminal route when the selected request requires
  that verification.
- [PROPOSED] Post-run validation audits claims such as capability, semantic,
  convergence, and readiness without silently becoming graph-route authority.
- [PROPOSED] Persist verification results with the same source-bound run lineage
  and state whether each result affected runtime routing.
- [PROPOSED] Do not treat post-run evaluation alone as proof of product behavior
  or as a replacement for build or runtime evidence.

## Proposed migration strategy

[PROPOSED] The current migration path reuses existing implementation and adds
only the minimum boundary exposed by a real vertical slice:

```text
[PROPOSED] Thin Admission Boundary
        |
        v
[PROPOSED] Existing LangGraph Runtime
        |
        v
[PROPOSED] Existing Intelligence Components
        |
        v
[PROPOSED] Runtime / Post-run Verification
        |
        v
[PROPOSED] Terminal Record
```

[PROPOSED] Do not implement a complete Lifecycle Service merely to match the
target diagram. A separate Lifecycle Service and Runtime Worker boundary may be
reviewed only if real product requirements introduce multi-user operation,
asynchronous execution, a remote API product, or long-running task management.

[PROPOSED] If one of those triggers is established, the later shape to review is:

```text
[PROPOSED] Lifecycle Service
        |
        v
[PROPOSED] Runtime Workers using the controlled LangGraph runtime
```

[PROPOSED] Such a later review does not automatically authorize a service,
scheduler, database, worker fleet, or migration task.

## Proposed migration constraints

1. [PROPOSED] Do not create a second workflow or orchestration engine.
2. [PROPOSED] Do not let Admission directly control graph-internal routing.
3. [PROPOSED] Do not let Lifecycle state replace LangGraph runtime state.
4. [PROPOSED] Do not make ArtifactStore state, evaluator state, or graph state
   individually authoritative for every kind of state; retain their bounded
   responsibilities and explicit lineage links.
5. [PROPOSED] Do not design a new unified RunState without an observed failure
   and direct current-source evidence that existing state cannot represent the
   required lineage.
6. [PROPOSED] Do not build a complete task scheduling, multi-tenant, or remote
   execution platform before a real product requirement establishes the need.

[PROPOSED] These constraints prevent migration drift. They do not define V2
completion criteria, activate implementation, or prevent a later reviewed
architecture decision based on new evidence.

## Minimal unresolved migration questions

- [UNKNOWN] Whether all current product entry points should converge on one
  thin boundary or retain several entry-specific adapters behind one contract.
- [UNKNOWN] Which exact persisted identity should be the common run-lineage key
  across entry, graph execution, Artifact revisions, verification, and terminal
  closure for future product slices.
- [UNKNOWN] How every supported source type should bind repository revision,
  worktree or snapshot identity, registry identity, and permitted file scope.
- [UNKNOWN] Which terminal outcomes require runtime verification, post-run
  validation, both, or an explicit not-applicable record for each product
  request.
- [UNKNOWN] Whether evaluator verdict persistence needs any boundary beyond the
  existing ArtifactStore and terminal-record contracts.

[PROPOSED] Resolve only the first unknown that blocks a selected real product
slice. Do not expand this list into a microservice, database, scheduler, or
multi-tenant platform design.

## Migration phases and observed checkpoints

### Phase 1: Runtime Boundary Stabilization

[PROPOSED] Validate that one source-bound no-write request can travel through:

```text
[PROPOSED] Request
  -> Thin Admission Boundary
  -> LangGraph Runtime
  -> Intelligence Component
  -> Runtime / Post-run Verification
  -> Terminal Record
```

[OBSERVED] `V2-RUNTIME-BOUNDARY-001` completed this bounded validation for the
registered `gtfo-r8-modules-asm` source. Run
`intelligent_evidence_4c811b6933d54a258b8ba0b2c4e14229` persisted source and
run identity, workflow trace, post-run validation, and terminal attempt lineage
without Proposal, apply, build, runtime, or target-source-write artifacts.

### Phase 2: Product delivery slices

[PROPOSED] Select a real Mod request and exercise the required controlled chain
through planning, evidence, implementation plan, Proposal, review, dry-run,
approval, isolated apply, build, applicable verification, and truthful terminal
classification.

[OBSERVED] Phase 2A run `42c5d93c` completed only the source-bound delivery
pipeline canary for the BetterHitFeedback VERSION change. It established
`delivery_canary_complete=true`, while `product_slice_complete=false`,
`runtime_behavior_verified=false`, and `phase_2_complete=false` remain explicit.

[PROPOSED] Phase 2B selects a meaningful product behavior or maintenance slice
whose acceptance boundary demonstrates more than pipeline mechanics. No Phase
2B request is selected, and this draft does not select one.

### Phase 3: Optional Lifecycle Evolution

[PROPOSED] Review a separate Lifecycle Service only after real product demand
demonstrates multi-user, asynchronous, remote-API, or long-running task
management requirements that the thin boundary and existing runtime cannot
represent safely.

[PROPOSED] Phase 3 is optional, inactive, and not implied by completion of
Phase 1, Phase 2A, or any future Phase 2B slice.

## Productization topics for later review

- [PROPOSED] Review source binding, entry visibility, trace continuity, retry
  behavior, stop behavior, terminal reporting, and path isolation as separate
  topics rather than as a bundled specification.
- [PROPOSED] Compare any later product direction using user-visible outcome,
  contract relevance, available evidence, minimal vertical observability,
  source reachability, dependencies, unknowns, and implementation risk.
- [PROPOSED] Keep grounded/walkable behavior, collision/contact response, and
  other gameplay directions unselected unless a later human decision selects
  one.

## Abstention and stop conditions for this analysis

- [PROPOSED] Abstain from describing a runtime path when the exact registered
  source or a readable trace/EvidencePack is unavailable.
- [PROPOSED] Stop at the first explicit evidence break and record the missing
  material instead of inferring a Hook, owner, or mechanism.
- [PROPOSED] Do not convert an inferred path into a source-confirmed statement
  without direct current-source evidence.
- [PROPOSED] Do not create a task id, queue item, product gate, implementation
  requirement, or product-direction decision from this draft.
