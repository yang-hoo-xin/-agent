# Coding Agent v0 P0-P3 Delivery Route Decision

Status: detailed decision record
Recorded: 2026-08-25
Recording context: `recorded_during_P1b_working_session`; status synchronized after P1b checkpoint and P2 sealed-entry incidents

## 1. Authority And Use

This record preserves the stable product-route decisions behind Coding Agent
v0. It is not implementation authority, a completion claim, an expected-side
truth source, or a second Implementation Queue. Current source, focused tests,
committed Artifacts, and actual-run evidence remain the empirical authority.
The current user request and `docs/ACTIVE_PRODUCT_CONTRACT.md` retain execution
authority.

Two user-authored review files remain authoritative thought material for the
engineering goal, value, tradeoffs, interview demonstration, and treatment of
failure:

- `C:/Users/10160/Desktop/项目回头自检.txt`
- `C:/Users/10160/Desktop/项目自检-8月17.txt`

They are not current implementation facts, expected truth, or permission to
execute. Time boxes and elapsed cost are feasibility warnings and reporting
inputs only; they do not veto the engineering structure required for a correct
capability. Each work package is evaluated by direct benefit, reuse benefit,
avoided future cost, added complexity, elapsed time, and an explicit decision
to continue or stop expansion.

## 2. Product Objective And Closed Loop

The objective is a trustworthy, evaluable, demonstrable Coding Agent v0, not a
production-grade Agent or RAG platform built in advance.

```text
request
→ Plan / Brief / FeatureSpec
→ repository and tool observations
→ requirement coverage
→ Evidence sufficiency
→ ImplementationPlan
→ Patch
→ Review / Dry-run
→ exact approval
→ isolated Apply
→ Build / Test
→ Repair / Revalidation
→ conditional Runtime
→ truthful result
```

Evaluation, RAG, authority controls, and documentation serve this chain. They
are not independent product lines.

## 3. Six Authority Layers

```text
Source Authenticity
→ Relevance
→ Requirement Coverage
→ Evidence Sufficiency
→ Patch Proposal Authority
→ Execution Authority
```

No retrieval signal independently grants sufficiency or Patch authority. A
model may propose a semantic finding; it may not invent identity, omit a
mandatory input, or directly set sufficiency, edit targets, Patch authority, or
execution authority. High-risk writes and runtime actions require deterministic
contracts, explicit authorization, and an auditable receipt.

## 4. Shared Requirement Pipeline

There is no “dual lane architecture.” `change`, `pre_patch_evidence`,
`preservation`, and `post_change_acceptance` are requirement semantic roles
inside one shared Search Planning, Retrieval, Source Verification,
EvidenceItem, and Coverage pipeline. Existing `planned_lanes` retain their
tool/source/question execution meaning and are not repurposed as semantic
roles.

- EvidenceItems and requirements are many-to-many.
- One EvidenceItem may support both change and preservation.
- Preservation constrains the allowed semantic delta; it does not prohibit
  editing the file that contains the preserved behavior.
- Role count, query-hit count, and EvidenceItem count are never sufficiency
  proxies.
- Post-change acceptance must be accounted for but normally does not become a
  pre-patch loop gate.
- `required_before_patch` is derived and validated by deterministic policy;
  the model cannot downgrade a mandatory obligation.

The semantic trust boundary is:

```text
model-originated semantic finding
→ deterministic requirement/evidence identity validation
→ deterministic current-source/reference validation
→ deterministic input accounting and coverage projection
→ deterministic sufficiency/edit-target/Patch-authority derivation
```

Deterministic code does not normally prove that natural-language semantic
support is true; it constrains and audits what the model is allowed to claim.

## 5. Delivery Route And Current Status

| Stage | Current synchronized status | Verified boundary | Next authority gate |
| --- | --- | --- | --- |
| P0 | completed | lexical-only RgLive observations fail closed without coverage | do not reopen for positive coverage |
| P1a | completed at `d377ab466fb3e2c57c4c33e29bc2408864e5976e` | structural/synthetic positive requirement-coverage vertical | P1b formal provider and entry |
| P1b | completed at `32a939b3f217721b076704cd7e701369fef532ed` | formal local projection/findings providers, validated consumer view, formal ProductExecution entry tests | stop Evidence expansion and enter P2 |
| P2 | product path admitted; sealed entry blocked at `ENTRY-002` | ProductExecution actual runs remain zero; empirical actual has not started | bounded entry-preflight repair, fresh preflight receipt review, then separate actual authorization |
| Internal Alpha | hard gates false/false | no changed-product success plus repair success pair | P2 empirical hard gates |
| Public Alpha | not started | public entry and case evidence absent | Internal checkpoint plus public-entry actual |

The current committed product checkpoint is
`32a939b3f217721b076704cd7e701369fef532ed`. The P2 sealed-entry blocker is an
entry/preflight incident, not evidence that the committed P1b provider or
coverage capability is unimplemented.

## 6. P0: False-Sufficiency Closure

P0 ensures that lexical-only or source-authentic observations remain
non-authoritative when explicit requirement coverage is absent.

- Checkpoint: `c8004845fe3f01d844e79ab8b6aba0634b6a5c01`
- Completed transition: wrong `sufficient` → correct `insufficient`
- P0 does not own positive requirement coverage and is not reopened by P1.
- `EVID-001` should describe only the false-sufficiency defect; P1 is an
  independent product capability.

## 7. P1: Requirement Coverage And Positive Authority

### 7.1 P1a

P1a checkpoint `d377ab466fb3e2c57c4c33e29bc2408864e5976e`
completed the structural/synthetic vertical, not all of P1. It established:

- input-obligation accounting;
- versioned `requirement_coverage` inside the existing EvidencePack;
- deterministic sufficiency and edit-target authority;
- bounded multi-query live observations;
- Planner selection of change-only edit targets;
- Resolver rejection of supporting-to-edit promotion;
- strict roundtrip and Hook/P0 compatibility.

### 7.2 P1b

P1b checkpoint `32a939b3f217721b076704cd7e701369fef532ed`
completed the formal local-model projection provider, findings provider,
`run-request`/CLI construction, real preservation capture, and formal
positive/blocked entry tests. This completion is bounded to product-path
construction; it does not prove that a fresh sealed execution context can enter
ProductExecution.

The coupling decision is:

- one coverage authority core owns accounting, validation, sufficiency, and
  edit-target derivation;
- Planner and Resolver consume a stable validated coverage view;
- generic relation identity belongs to a shared Evidence/Requirement boundary,
  while Hook Discovery keeps compatibility exports;
- provider orchestration is separate from the authority core;
- semantic validation remains in the core, while EvidencePack serialization
  and Artifact persistence remain in models/ArtifactStore;
- ProposalReviewer continues through BindingResolver and does not repeat
  semantic judgment.

Formal CLI tests may inject an admitted fake model adapter. They may not inject
hand-authored projection/findings callbacks and call that the product entry.
Natural-language keyword tables are not a substitute for the change versus
preservation semantic provider; stable protocol syntax parsing remains valid.

P1b completion ends default Evidence Architecture expansion and triggers a P2
admission review.

## 8. P2: Sealed Fresh Actual

P2 product-path admission starts after the P1b actual-ready checkpoint. A fresh
empirical actual additionally requires sealed-entry admission. The current
entry blocker is `ENTRY-002`, detailed in
`docs/audits/ACCURATE_CROSSHAIR_SEALED_ENTRY_ATTEMPTS_20260825.md`; no current
P2 ProductExecution actual has started.

```text
new checkpoint
→ new sealed packet
→ one new fresh actual task
→ Evidence
→ Plan
→ Patch
→ Review / Dry-run / exact approval
→ Apply
→ Build / Test
→ Repair / Revalidation when required
```

Each fresh actual task executes only. It does not implement providers, carry
hand-written callbacks or expected projections, or repair platform code in
place. On failure it freezes the first physical failure and returns to that
owner. Runtime requires separate authorization only when applicable to the
task's acceptance boundary.

P2 hard gates are:

1. one actual-only changed-product Build/Test success;
2. one Failure → Different Repair → Revalidation success.

## 9. Internal Alpha To Public Alpha

The two P2 hard gates produce the Internal Alpha checkpoint. After Internal
Alpha, minimum Trace/Eval and the unique Public Runner/RAG-1B advance together;
they do not wait for every operations platform.

```text
one public entry
→ the same Runner
→ the same StateGraph
→ the same ArtifactStore and authority chain
```

Internal success does not prove public-entry success. The public entry requires
another real actual. A bounded set of three to five real Cases should cover
success, repair, correct block, authority-negative behavior, and technical
failure attribution, retaining trajectories, calls, timings, failures, and
limitations.

Before Public Alpha, minimum Operational Readiness remains owned by the
`minimum_acceptance` of `ENTRY-001`, `OPS-001`, `TOOL-001`, `REPORT-001`, and
`REC-001` in `docs/audits/ENGINEERING_ISSUE_REGISTER.md`.

The advanced-robustness catalog—full circuit breaker, model gateway, automatic
fallback, distributed recovery, and related capabilities—remains
`conditional_trigger`, `current_queue=false`, `internal_alpha_blocker=false`,
and `minimum_public_alpha_blocker=false` unless a real risk audit at activation
time promotes a specific item.

Minimum Trace/Eval does not mean building a Langfuse, OpenTelemetry, Dashboard,
or release platform first. Existing Artifacts and receipts may provide the
initial inspectable demonstration.

## 10. Evidence Architecture And Issue Activation

P1b is a required capability for the next actual and therefore belongs in the
current work, not in an Issue waiting for repetition. Without it the formal
entry deterministically remains insufficient. After P1b, Evidence Architecture
stops expanding by default and the product returns to P2.

Classification rule:

- required by the next actual → current Queue;
- observed with a known owner but not blocking the next actual → Engineering
  Issue;
- not physically observed → conditional trigger;
- long-term principle → decision record or `documented_only` reference;
- completed work → audit or loop history.

The Issue Register is not a TODO list, Queue, or authority source. Later
Evidence work reactivates only after a fresh actual exposes a new first failure,
the same failure repeats, a real consumer appears, and the user selects that
owner.

## 11. P3 And Public-Alpha Maturity

P3 covers only capabilities justified by the selected product route:

- task-applicable Runtime/gameplay evidence;
- one Runner and Public entry;
- three to five tasks plus bounded repeatability evidence;
- minimum Trace/Eval, run reporting, and demonstration;
- the minimum `OPS`/`ENTRY`/`TOOL`/`REPORT`/`REC` package;
- documentation and checkpoint closure;
- a truthful Public Alpha claim.

P3 does not automatically include every advanced-robustness direction.

## 12. Explicit Deferrals And Conditional Triggers

The following are not activated by this route:

- Dense retrieval, semantic hybrid retrieval, RRF, and reranking;
- complete Eval, CI, nightly, release, or observability platforms;
- fifty to two hundred Cases;
- formal model-comparison programs;
- LoRA, SFT, DPO, or multimodal work;
- complete distributed recovery or model-gateway platforms;
- reconciliation of the four protected WIP documents, which remains separate,
  incremental, and non-blocking for P1/P2.

Semantic/vector retrieval activates only if exact, symbol, and live-source
retrieval still demonstrates a real recall failure under a real Eval.

## 13. Collaboration And Workspace Boundaries

- The current macro review task owns architecture, priority, and authorization
  packets.
- The only implementation-progress task is
  `01a0285e-22ac-7d02-8052-227def631dfe`.
- Old long-context tasks receive no new work.
- Every fresh actual uses a new task and is never reused.
- The following user WIP files remain protected from modification, staging, or
  commit:
  - `docs/ARCHITECTURE_OVERVIEW.md`
  - `docs/ENGINEERING_RAG_EVIDENCE_INTELLIGENCE_TARGET_DRAFT.md`
  - `docs/SPEC_COVERAGE_MATRIX.md`
  - `docs/LOCAL_MODEL_COMPARATIVE_EVALUATION_EXPERIMENT.md`

## 14. Related Records

- `docs/audits/ENGINEERING_ISSUE_REGISTER.md`
- `docs/audits/RG_LIVE_EVIDENCE_SUFFICIENCY_OWNER_AUDIT_20260824.json`
- `docs/audits/ACCURATE_CROSSHAIR_ACTUAL_OUTCOME_20260824.json`
- `docs/audits/ACCURATE_CROSSHAIR_SEALED_ENTRY_ATTEMPTS_20260825.md`
- `docs/audits/LOOP_HISTORY.md`
- P0 checkpoint `c8004845fe3f01d844e79ab8b6aba0634b6a5c01`
- P1a checkpoint `d377ab466fb3e2c57c4c33e29bc2408864e5976e`
- P1b checkpoint `32a939b3f217721b076704cd7e701369fef532ed`

This record preserves the decision route only. It does not claim sealed-entry
readiness, authorize a preflight rerun or actual, or claim Internal or Public
Alpha readiness.
