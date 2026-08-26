# Coding Agent v0 P0-P3 Delivery Route Decision

Status: detailed decision record
Recorded: 2026-08-25
Recording context: `recorded_during_P1b_working_session`; status synchronized through actual6 and the active EVID-002 owner

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
| P2 | empirical actual active; `ENTRY-002` closed for current scope; `EVID-002` active | actual5 and actual6 entered ProductExecution, called the local model twice each, and stopped before findings on the same projection disposition signature | bounded projection structured-output admission/diagnostic/correction checkpoint, then a new preflight and separately authorized actual7 |
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

P2 product-path admission starts after the P1b actual-ready checkpoint. Fresh
preflight4 plus actual5 and fresh preflight5 plus actual6 now satisfy the
`ENTRY-002` current-scope close trigger: both actuals entered ProductExecution
without entry-side repair. Entry remains separately reopenable on a new
pre-ProductExecution identity or permission failure.

Actual5 and actual6 establish the next current owner inside ProductExecution.
The per-obligation schema from checkpoint `2b18874` was physically sent to
Ollama, but one projection plus one correction still failed
`REQUIREMENT_COVERAGE_INPUT_DISPOSITION_INVALID` before findings. `EVID-002`
therefore owns exact local response-schema admission, precise semantic
rejection diagnostics, and the existing single correction. It does not own
retrieval, findings semantics, coverage policy, model switching, a third
correction, or vector work.

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

## 15. Current Decision Snapshot

```yaml
snapshot_as_of_commit: 2b18874a44e1785c1b8775ff2d8a8fa5f84594fb
P0: completed
P1a: completed
P1b: completed
ENTRY_repository_implementation_checkpoint: completed
P2_product_path_admission: admitted
fresh_sealed_entry_admission: passed_for_current_scope
ENTRY-002: closed
ProductExecution_actual_runs: 2
current_P2_model_calls: 4_total_across_actual5_and_actual6
current_owner: EVID-002
actual6_baseline_build: passed
actual6_changed_product_build: not_reached
Internal_Alpha_hard_gates: false/false
```

The current checkpoint plus actuals prove only the bounded facts above. They do
not prove positive sufficiency, Patch generation, changed-product Build,
Repair/Revalidation, Entry repeatability beyond the tested scope, or Internal
Alpha completion.

## 16. Single-Owner Orchestration Boundary

The intended composition is:

```text
Thin Entry Admission
→ ProductExecution Preflight
→ one existing StateGraph
→ bounded capability adapters
```

Entry Admission owns packet/manifest identity, execution security context,
physical locations, tool and local-model availability, outer permission and
budget facts, output-root admission, and one delegate/no-delegate decision. It
does not own product retry, Patch approval, completion, or business truth.

ProductExecution Preflight owns the product request, content/source binding,
provider/product contracts, Artifact boundary, and Graph admission. The two
layers must not independently own attempt, retry, approval, or completion. At
`c906d99dba8f1850864e090c4f925a78fbd4f373`, one `StrictGitAdmission`
identity is threaded through entry and downstream source revalidation without
turning Entry into a second control plane.

Observations may change the engineering direction. The Graph constrains legal
order, permission, and side effects; it does not pre-decide search strategy,
interpretation, or Repair direction. BHF and WallCrawler rules remain domain
Harness facts and do not enter the generic Workflow owner.

Models may propose engineering semantics; deterministic owners retain identity,
coverage, authority, and side-effect decisions. Capability work remains
consumer-first: identify who consumes the result, what decision it changes,
what current contract cannot represent, and what failure proves the need before
adding infrastructure. A read-only subsystem exits after returning its bounded
facts and cannot retain route or completion authority.

## 17. Recovery And Failure Semantics

- **Retry** repeats the same bounded operation under an explicit retry owner.
- **Resume** continues from a validated durable checkpoint without replaying
  completed work.
- **Recovery** re-establishes a trustworthy execution owner and state after a
  process, host, permission, or entry failure.
- **Repair** changes the proposed implementation in response to bound product
  evidence.
- **Rollback** directly restores a prior reversible state.
- **Compensation** uses a newly authorized action to offset an irreversible or
  externally visible side effect.
- **Fallback** creates a new, lower-authority attempt using a prevalidated
  capability profile; it never silently replaces the original failure.

Adapters report facts. One control owner decides whether retry is legal. Outer
Entry Admission does not own product retry.

| Failure fact | Default route |
| --- | --- |
| deterministic identity, authority, or schema rejection | block and return the exact owner |
| explicitly retryable transient provider/tool failure before side effects | one bounded retry owner may propose a new attempt |
| committed checkpoint with valid continuation authority | resume |
| lost or uncertain execution ownership | recovery or safe stop |
| product behavior failure with edit authority | Repair |
| unknown side-effect state | safe stop and reconcile |

## 18. Authority-Aware Degradation

`FULL`, `EVIDENCE_DEGRADED`, `PLAN_ONLY`, and `SAFE_STOP` are logical operating
semantics. They should first be projected through existing readiness, blockers,
requirement coverage, and authority facts rather than creating a new schema.

Capability degradation may preserve or contract authority; it may never expand
it. Unknown source identity, permission, or side-effect state maps to
`SAFE_STOP`. Cached, partial, or stale material cannot present itself as fresh,
complete, sufficient Evidence or Patch authority.

## 19. Retrieval And Vector Boundary

RAG does not require a vector database. Semantic vectors, when activated, are
only a location-recall aid. Retrieved locations must be rehydrated from current
live source and rebound to current path/hash/span identity. An index is a
rebuildable cache; a vector hit is not an `EvidenceItem`, requirement coverage,
Evidence sufficiency, or Patch authority.

Semantic A/B, hybrid fusion, and persistent vector storage activate only under
the separate conditional triggers in the Engineering Issue Register. This
decision record does not activate them.

## 20. Artifact, Checkpoint, Trace, Contract Reuse And Coverage Map

- Graph checkpoint answers **how execution may continue**.
- ArtifactStore owns product facts that require durable authority, side-effect,
  resume, lineage, or terminal truth.
- Trace answers **what happened** and does not become a second fact owner.

All stages should be observable, but not every stage creates an Artifact.
Persistence belongs only at durable boundaries.

Identity taxonomy remains explicit: outer run/attempt, entry preflight, product
run/request/feature, stage/action/observation, provider call, Patch/approval,
and Repair/revalidation identities must be correlated without being collapsed
into one identifier.

`RunEnvelope`, `ValidatedSourceBinding`, `StageOutcome`, `ToolCallSpec`, and
`ToolReceipt` are logical checklists. They do not justify new types until a real
consumer proves that existing contracts cannot represent the required fact.

Run-local working memory is necessary for bounded continuation. Cross-task
long-term memory activates only after repeated real tasks establish a retrieval
need; it remains planning-only and cannot store Golden data, old Hook answers,
or historical output as current fact.

| Content | Unique owner |
| --- | --- |
| stable orchestration, recovery, degradation, retrieval, and contract principles | this Decision Record |
| Sealed-entry Attempts A1–A5 physical facts | AccurateCrosshair sealed-entry incident record |
| Complete recent logical-chain Issue interaction and actual1–6 facts | `docs/audits/CODING_AGENT_V0_RECENT_ISSUE_INTERACTION_AUDIT_20260826.md` |
| trigger, physical owner, reopening and minimum acceptance | Engineering Issue Register |
| explicitly activated work | Implementation Queue |
| Architecture WIP stable single-Graph/observation principles; old BHF/WC order excluded | `reconcile_later` |
| RAG draft stable semantic/authority/consumer principles; obsolete checkpoints and exits excluded | `extract_stable_principles_then_historicalize_or_rewrite_later` |
| Coverage Matrix WIP | `regenerate_after_ENTRY` from current source; do not migrate the stale CAV0 table |
| Local Model untracked protocol | `paused_standalone_asset_reconcile_later`; comparison waits for stable interfaces and a real product bottleneck |

This record preserves the decision route only. It does not authorize the
`EVID-002` implementation checkpoint's successor packet, preflight, actual7,
or any Internal or Public Alpha claim.
