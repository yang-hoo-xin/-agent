# Engineering Issue Register

Status: lightweight observation register
Last reviewed: 2026-08-25

## 1. Purpose And Authority Boundary

This register records engineering problems that were physically observed in a
real run, deterministic replay, or verified checkpoint. It keeps the problem's
owner, evidence, current disposition, and exact reopening condition available
without turning old failures into current authority.

This file is not:

- the Implementation Queue or a source of execution authorization;
- an automatic repair, routing, policy, or prioritization rule set;
- a replacement for `docs/ACTIVE_PRODUCT_CONTRACT.md`, `docs/PROJECT_STATE.md`,
  `docs/IMPLEMENTATION_QUEUE.md`, or `docs/audits/LOOP_HISTORY.md`;
- the complete Trace/Eval engineering area;
- a repository-wide TODO scan or a ten-thousand-line asset reconciliation.

The current user request and Active Product Contract always outrank this
register. A matching entry can inform a decision only after a current physical
failure has independently established the same owner and satisfied the entry's
`reopen_trigger`.

## 2. Classification

### 2.1 Severity

| Value | Meaning |
| --- | --- |
| `S0` | Fact fabrication, unauthorized action, or irrecoverable-risk boundary |
| `S1` | Blocks the current product completion gate |
| `S2` | Quality, stability, or traceability defect |
| `S3` | Local cost or maintenance issue |

### 2.2 Decision Priority

| Value | Meaning |
| --- | --- |
| `P0` | Immediately blocks the current work |
| `P1` | Must be handled in the current product stage |
| `P2` | Observe; handle after physical repetition |
| `P3` | Frozen; do not proactively handle |

### 2.3 Status

Allowed values are:

- `observed`
- `active`
- `mitigated_for_current_scope`
- `explicit_unresolved`
- `closed`
- `deferred`
- `rejected_currently`
- `superseded`

### 2.4 Evidence Level

| Value | Meaning |
| --- | --- |
| `real_run` | Direct current-run process, provider, tool, Build, or Artifact evidence |
| `real_run_and_comparison` | Real actual plus an independently executed expected-side comparison |
| `checkpoint_and_tests` | Current source checkpoint plus focused executable tests |
| `mechanical_replay` | Deterministic reconstruction or identity replay without a model call |

### 2.5 Optional Stage-Gate Fields

Operational issues may add:

- `required_before_stage`: the product stage that cannot be authorized until
  the issue meets its minimum boundary;
- `minimum_acceptance`: a bounded list of observable facts required to close
  the issue or record a verified mitigation boundary.

These fields do not put an issue in the Implementation Queue. An Internal Alpha
completion checkpoint reopens every entry whose `required_before_stage` is
Coding Agent v0 public alpha, raises its decision priority to `P1`, and creates
one bounded Operational Readiness work package. Implementation still requires
current user authority.

## 3. Event-Triggered Review Protocol

Review this register only after one of these events:

- a first physical failure is frozen;
- Evidence is committed as `blocked` or `insufficient`;
- the same owner/failure signature repeats;
- two consecutive bounded runs make no progress;
- a proposed fix crosses an owner or layer boundary;
- a product-stage checkpoint is formed.

The mandatory order is:

```text
freeze the current failure and immutable evidence
-> locate the current physical owner without using this register
-> inspect this register only for that owner/signature
-> retain only entries whose reopen_trigger is currently satisfied
-> decide reopen, add, defer, reject, or leave closed
```

Do not read old issues first and fit the current observation to them. A reopened
entry grants no permission to edit code, change a model, expand a budget, run a
tool, or change product scope. Those actions require current authority.

## 4. Registered Issues

### OBS-001

```yaml
issue_id: OBS-001
title: qwen3:4b BHF semantic discovery and source disambiguation are insufficient
scope: BHF positive calibration on the bound R8 corpus
owner: EvidenceDiscovery Search Planning and action selection for the current local model
evidence_level: real_run_and_comparison
severity: S1
decision_priority: P3
status: explicit_unresolved
first_seen: 2026-08-21 run002
latest_evidence: run004 EvidencePack b554e02190af1117b4b552072eea0404ae4271927b803619db9447c89764e9b1; expected-side acceptable_hook_identity_set_matches=false
current_effect: BHF positive direction gate is unresolved for the current model and strategy; RAG-1A positive gate is not passed
workaround: preserve the explicit unresolved result and continue only with another selected product slice
reopen_trigger: an explicitly authorized model-role evaluation, or an independent task with the same semantic discovery/disambiguation failure
next_action: none in the current BHF route
last_reviewed: 2026-08-22
```

Reopen review on 2026-08-24 did not map AccurateCrosshair run `8d26e4e5`
to `OBS-001`. The symptom again involved source disambiguation, but the current
owner is deterministic `RgLiveEvidenceProvider.collect` Evidence sufficiency,
not model-driven EvidenceDiscovery Search Planning/action selection. The new
failure signature, `deterministic RgLive Evidence relevance-to-sufficiency
promotion failure`, is now recorded as `EVID-001` and mitigated for the current
scope by checkpoint `c8004845fe3f01d844e79ab8b6aba0634b6a5c01`. Its run facts
remain in `docs/audits/ACCURATE_CROSSHAIR_ACTUAL_OUTCOME_20260824.json`; the
owner audit is `docs/audits/RG_LIVE_EVIDENCE_SUFFICIENCY_OWNER_AUDIT_20260824.json`.

### OBS-002

```yaml
issue_id: OBS-002
title: Search Plan investigation coverage was unstable
scope: split Requirement Projection and Search Planning subturn
owner: EvidenceDiscovery Search Planning structural compliance
evidence_level: real_run
severity: S2
decision_priority: P2
status: mitigated_for_current_scope
first_seen: 2026-08-21 run003
latest_evidence: checkpoint e7b84f14e0c600f41e583f1b9019d8dd64ac2d5b adds one bounded correction; run004 used it and froze a Search Plan
current_effect: the observed coverage mismatch no longer blocks the current scope, but another task may expose the same structural failure
workaround: one correction only; the original coverage gate remains strict
reopen_trigger: a new independent task returns a Search Plan investigation-count mismatch after the bounded correction
next_action: record the new run facts before deciding whether the mitigation is insufficient
last_reviewed: 2026-08-22
```

### RET-001

```yaml
issue_id: RET-001
title: bge-m3 per-text OllamaEmbedding and Chroma fail during full-R8 materialization
scope: full-R8 source-only Dense feasibility experiment
owner: embedding provider full-corpus stability
evidence_level: real_run
severity: S2
decision_priority: P3
status: rejected_currently
first_seen: 2026-08-21 full-R8 experiment bge_m3_full_r8_ab_20260821_001
latest_evidence: decision_record SHA256 7404f84661f7fdc3051e9047b3c3ab8d83fce4772fa9c2686ad1ad29b2b688e7; failure_record SHA256 e8c69f52ddeb6cf9436520e34c7f9091820082c341a70224b6195d5cece3a860
current_effect: the current Dense path is not eligible for experimental auxiliary adoption
workaround: use the existing non-Dense Retrieval Plane; do not treat the synthetic micro-canary as full-corpus proof
reopen_trigger: a new product failure explicitly requires Dense reconsideration and the user separately authorizes provider materialization work
next_action: none; Retrieval provider exploration is closed
last_reviewed: 2026-08-22
```

### CTX-001

```yaml
issue_id: CTX-001
title: Ollama service default context was insufficient for a bounded discovery turn
scope: local Agent-turn execution with qwen3:4b-instruct
owner: run-level Ollama context configuration
evidence_level: real_run
severity: S2
decision_priority: P3
status: mitigated_for_current_scope
first_seen: 2026-08-21 BHF run001
latest_evidence: Wall relation-aware run001 and run003 were rejected before HTTP at explicit num_ctx 16384 and 32768 respectively; final run004 used run-level num_ctx 65536, passed per-call admission through seven model-call attempts, and stopped instead on Provider response timeout rather than context admission
current_effect: context admission is not the latest first blocker for the closed Wall route; 65536 is only a bounded run-level observation and does not change product defaults or prove every future request fits
workaround: preserve per-call admission and the run-level identities; do not continue Wall context escalation or promote 65536 to a product default
reopen_trigger: a new authorized run fails context admission with an explicit, model-supported context setting
next_action: none in the current Wall route; reopen only on a new selected product task that fails the existing per-call admission under an explicit model-supported setting
last_reviewed: 2026-08-22
```

### ART-001

```yaml
issue_id: ART-001
title: Hand-authored future FeatureSpec identity was not reproducible
scope: calibration actual authorization packet construction
owner: production FeatureSpec and ArtifactStore identity projection
evidence_level: mechanical_replay
severity: S1
decision_priority: P3
status: closed
first_seen: 2026-08-21 BHF preflight
latest_evidence: production RequestPlanner and FeatureSpecBuilder produce feature_258e3fb80ea6 with hash 79786316d2c4a8201e5c5659a81ae9906b6cf5fa638edd32c6da3cdee751dded
current_effect: future calibration runs use the production owner rather than hand-authored payload fields
workaround: none required after production-owner projection
reopen_trigger: production projection, materialized ArtifactRef, and approved identity drift for the same immutable input
next_action: fail before model execution if identity drift is observed
last_reviewed: 2026-08-22
```

### EVID-001

```yaml
issue_id: EVID-001
title: RgLive lexical observations were promoted to Patch authority without requirement coverage
scope: ProductExecution RgLive lexical-only Evidence sufficiency
owner: src/mod_agent/evidence/rg_live.py::RgLiveEvidenceProvider.collect
evidence_level: real_run
severity: S1
decision_priority: P3
status: mitigated_for_current_scope
first_seen: AccurateCrosshair run 8d26e4e5
latest_evidence: checkpoint c8004845fe3f01d844e79ab8b6aba0634b6a5c01 makes lexical-only and source-authentic RgLive observations non-authoritative when explicit requirement coverage is absent
current_effect: the observed wrong sufficient-to-Patch-authority transition is closed for the current lexical-only scope; positive requirement coverage remains the independent P1 capability and is not owned by this Issue
workaround: none required for the current scope; preserve the deterministic fail-closed boundary
reopen_trigger: any lexical or source-authentic observation again produces readiness=sufficient, can_generate_patch=true, or Patch Proposal authority without explicit validated requirement coverage
next_action: reopen only on that exact false-sufficiency signature; do not merge P1 positive coverage work into this Issue
last_reviewed: 2026-08-25
```

### ISO-001

```yaml
issue_id: ISO-001
title: Actual execution and expected-side evaluation ownership were mixed
scope: manifest-bound calibration actual and Hidden-Golden comparison
owner: Evidence actual owner and evaluation expected-side owner boundary
evidence_level: checkpoint_and_tests
severity: S0
decision_priority: P3
status: closed
first_seen: 2026-08-20 checkpoint 16574890 review
latest_evidence: checkpoint 1d6ceb4d5e61fb0bd6f491c7f1e3a845b5495775 establishes one-way ownership; checkpoint 6925d4bd834f02faae20486478336745f6789928 rebinds manifest identity before annotation read
current_effect: actual execution remains request/source-only and expected truth is read only after immutable committed actual validation
workaround: none required in the current scope
reopen_trigger: any actual model input, Store payload, or pre-commit route reads expected/Golden content, or evaluation changes a frozen actual
next_action: stop the run as contaminated before interpreting model quality
last_reviewed: 2026-08-22
```

### AUTH-001

```yaml
issue_id: AUTH-001
title: A sealed packet runner could automatically substitute for human exact-diff approval
scope: exact-diff semantic review and isolated Apply authorization
owner: sealed packet human approval gate
evidence_level: mechanical_replay
severity: S0
decision_priority: P3
status: closed
first_seen: 2026-08-25 Attempt1 packet macro review before execution
latest_evidence: macro review rejected payload manifest 8110b7b7cc5c86c139733c2c9e07fec5b29114401407fcf8d347c60c599d0b4e because its callback returned the generated diff_hash without a user decision; the packet was superseded before execution and later packets require an interactive PTY marker, full diff display, and exact user input
current_effect: no unknown generated diff was approved or applied through the defective packet; the superseded packet is not executable
workaround: none; only the explicit human PTY gate is valid
reopen_trigger: any packet, Runner, callback, automation, or Agent generates, copies, infers, simulates, or submits the user's exact-diff approval input
close_trigger: the active sealed packet requires full diff presentation, records AWAITING_EXACT_DIFF_APPROVAL, and accepts only text actually supplied by the user
next_action: stop before Apply and treat any recurrence as an authorization-boundary failure
last_reviewed: 2026-08-25
```

### DOC-001

```yaml
issue_id: DOC-001
title: Authoritative documents disagreed on the current selected product slice
scope: Active Product Contract, Project State, Implementation Queue, and Coding Agent v0 target
owner: authoritative documentation state synchronization
evidence_level: checkpoint_and_tests
severity: S2
decision_priority: P1
status: active
first_seen: 2026-08-21 checkpoint 397629ee review
latest_evidence: on 2026-08-25 Active Product Contract, Project State, Implementation Queue, and the P0-P3 decision record still described P0 as pending, P1b as active/uncommitted, or P2 as not admitted after checkpoints c8004845fe3f01d844e79ab8b6aba0634b6a5c01, d377ab466fb3e2c57c4c33e29bc2408864e5976e, and 32a939b3f217721b076704cd7e701369fef532ed had changed the current state
current_effect: authoritative short pages disagree on the selected stage and first blocker; this is a documentation synchronization defect and does not block product capability by itself
workaround: keep detailed run evidence in one primary record and short selection fields elsewhere
reopen_trigger: Active Product Contract, Project State, Implementation Queue, or the §8 execution sequence name different current selections
trigger_state: satisfied_by_2026_08_25_P0_P1_P2_state_drift
next_action: align the owning short status fields with the Attempts1-5 incident record and current checkpoint; do not duplicate the full run narrative
last_reviewed: 2026-08-25
```

### REP-001

```yaml
issue_id: REP-001
title: r8 Repair Patch was structurally invalid and the repository objective remained unresolved
scope: second real repository issue Repair loop
owner: Repair model output semantic and structural quality
evidence_level: real_run
severity: S1
decision_priority: P3
status: explicit_unresolved
first_seen: 2026-08-20 bounded r8 Repair runs
latest_evidence: run 32e29415 stopped at dry_run_apply_execution/unmatched_closing_brace; checkpoint e436434dc894df87339b2f3a6767f34477989426
current_effect: the r8 repository objective did not pass and does not support an internal-alpha completion claim
workaround: preserve the explicit unresolved result and do not hand-edit the model Patch
reopen_trigger: the user explicitly reselects r8, or an independent repository task shows the same Repair output failure
next_action: none in the current selected product slice
last_reviewed: 2026-08-22
```

### CASE-001

```yaml
issue_id: CASE-001
title: WallCrawler negative calibration comparator cannot distinguish evidence-grounded block from incomplete budget stop
scope: WallCrawler negative calibration reliability and minimal relation Eval
owner: existing expected-side Calibration Reliability/Eval owner in the formal hidden_golden comparator
evidence_level: real_run_and_comparison
severity: S2
decision_priority: P3
status: explicit_unresolved
first_seen: WallCrawler run002
latest_evidence: old run002 EvidencePack 4588f5f5e357e00f788ec552af6960c0302aa3adb8ca48987956665077e2d704 remains inconclusive under the old protocol; deterministic checkpoints now implement shared reliability, structured relation scoring, request-side Relation identity, Relation-to-Observation lineage, bounded missing, and strict rehydrate, but relation-aware run004 stopped before Artifact commit after seven model-call attempts and two accepted model actions because the seventh Provider response timed out
current_effect: neither the old nor relation-aware Wall route proves negative capability; RAG-1A relation-aware remains explicit unresolved and no current Wall work is selected
workaround: preserve old comparison and new partial control-flow facts without constructing an EvidencePack or verdict after failure
reopen_trigger: after Internal Alpha, an explicitly authorized model/runtime role can complete the relation-aware protocol, or an independent task reproduces the same need to distinguish grounded negative evidence from incomplete execution
next_action: none in the current Wall route; proceed to a simple actual-only product task
last_reviewed: 2026-08-22
```

### OPS-001

```yaml
issue_id: OPS-001
title: Unified Runner lifecycle projection, stage/run deadlines, and event heartbeat are incomplete
scope: Coding Agent Runner operational visibility
owner: existing Runner/Workflow runtime projection; not a second state machine
evidence_level: real_run
severity: S1
decision_priority: P2
status: observed
first_seen: BHF and WallCrawler local actuals required chat polling while only per-provider timeout was available
latest_evidence: AccurateCrosshair first-run collaboration took about 52 minutes while the sealed ProductExecution command took about 159 seconds; packet preparation, one zero-model projectless permission stop, execution-root correction, fresh-page execution, and strict result extraction were manually coordinated without a stage heartbeat. Detailed timing remains only in docs/audits/ACCURATE_CROSSHAIR_ACTUAL_OUTCOME_20260824.json
current_effect: current manual coordination does not block the selected Evidence-owner correction or invalidate Internal Alpha evidence, but operational stability cannot be measured reliably and Public Alpha Operational Readiness remains blocked
workaround: bounded attempts, per-call timeout, manual polling, and terminal Artifact/failure receipt
reopen_trigger: satisfied by run004 duration/progress opacity; implementation remains scheduled after Internal Alpha and before core stability/public alpha
trigger_state: satisfied_by_wall_run004_and_accurate_run8d26e4e5_without_heartbeat
implementation_timing: after Internal Alpha and before Core Stability Validation
next_action: after Internal Alpha, project lifecycle state from existing LangGraph state plus ArtifactStore/attempt facts
last_reviewed: 2026-08-24
required_before_stage: Coding Agent v0 public alpha
minimum_acceptance:
  - stable CREATED/PREFLIGHTING/EXECUTING/WAITING_PROVIDER/SUCCEEDED/FAILED/CANCELLED/EXPIRED states mapped from existing facts
  - event-driven heartbeat on stage change, model response, tool completion, and Artifact commit
  - stage and overall deadlines derived from measured runs
  - queryable current owner, remaining budgets, and terminal receipt
  - no new durable business truth outside ArtifactStore
```

### TOOL-001

```yaml
issue_id: TOOL-001
title: Fresh execution contexts do not reliably bind required metadata/IL tool artifacts
scope: fresh worktree and expected-isolated Runner tool packaging
owner: tool manifest, resolver, and preflight
evidence_level: real_run
severity: S1
decision_priority: P2
status: mitigated_for_current_scope
first_seen: WallCrawler run001 METADATA_IL_INSPECTOR_ARTIFACT_MISSING
latest_evidence: WallCrawler run002 bound external inspector SHA256 552949586FB6F072AF5ACA0910D552FB6A5D0BF936E25B74FAA8CDDCF4D1A2A1, passed target_code_executed=false canary, and committed EvidencePack 4588f5f5e357e00f788ec552af6960c0302aa3adb8ca48987956665077e2d704
current_effect: current WallCrawler scope recovered with one exact external tool, while generalized fresh-context readiness remains unproven
workaround: explicitly bind and validate the approved external inspector path/hash before model execution
reopen_trigger: any fresh execution context cannot resolve and validate an approved tool manifest
next_action: after Internal Alpha, add tool-manifest resolution and fresh-context preflight without requiring untracked bin output in every checkout
last_reviewed: 2026-08-22
required_before_stage: Coding Agent v0 public alpha
minimum_acceptance:
  - logical tool role, name, version, runtime, and source-or-build identity
  - resolver returns the exact path and hash
  - preflight proves availability, runtime compatibility, and a read-only canary
  - one fresh-context proof without path guessing
  - no requirement that an untracked bin artifact exists in every checkout
```

### REPORT-001

```yaml
issue_id: REPORT-001
title: Reporting projection can fail after committed business Artifact success
scope: console, UI, or local trace projection of Artifact refs and failure receipts
owner: stable reporting projection, separate from the ArtifactStore business object
evidence_level: real_run
severity: S2
decision_priority: P2
status: observed
first_seen: WallCrawler run001 post-commit ArtifactRef.to_dict missing
latest_evidence: AccurateCrosshair run 8d26e4e5 produced a 69,253-byte public execution receipt and five valid Store refs, but owner/result auditing still required bounded manual field extraction from the receipt, run_result, and strict readback. Detailed Artifact facts remain only in docs/audits/ACCURATE_CROSSHAIR_ACTUAL_OUTCOME_20260824.json
current_effect: Store truth survived and was verifiable, but the terminal projection remains too large for direct owner triage; reporting is not yet uniform across permission, pre-Artifact, and committed-Artifact boundaries
workaround: use explicit field projection and Store readback for committed results; for current pre-Artifact calibration failures preserve the Provider diagnostic and manually retain the known control-flow limitation without rerunning solely to reconstruct Trace
reopen_trigger: an independent report/console/UI projection failure, or the Internal Alpha completion checkpoint
trigger_state: satisfied_by_wall_trace_gap_and_accurate_run8d26e4e5_large_manual_projection
implementation_timing: after Internal Alpha and before Coding Agent v0 public alpha
next_action: define one stable reporting/failure-receipt projection after Internal Alpha that consumes committed Artifact facts when present and bounded in-memory runtime diagnostics when failure occurs before an Artifact, without changing Artifact schemas
last_reviewed: 2026-08-24
required_before_stage: Coding Agent v0 public alpha
minimum_acceptance:
  - one stable serializer/projection for ArtifactRef, attempt, and result
  - report failure cannot hide a committed business result
  - a pre-Artifact Provider or Planning failure preserves bounded stage, owner, admission, and Projection Attempt diagnostics without raw prompt, reasoning, or expected-side content
  - focused tests plus one real-run projection
  - no second Artifact schema
```

### REC-001

```yaml
issue_id: REC-001
title: Minimal graceful cancellation, checkpoint resume, and policy-driven fallback are not productized
scope: Public Alpha Runner recovery boundary
owner: existing Runner/attempt policy; no model gateway or recovery platform
evidence_level: real_run
severity: S1
decision_priority: P2
status: observed
first_seen: long BHF and WallCrawler runs relied on bounded no-retry protocol and manual waiting
latest_evidence: relation-aware Wall runs used explicit new-attempt identities after context admission rejects at 16384 and 32768; final run004 at 65536 crossed into the Action/Observation loop and then stopped on a seventh-call 180-second Provider read timeout without retry, model switch, or overwrite of prior failures
current_effect: the calibration path demonstrates fail-closed detection and bounded manual fallback for context and timeout samples, but the Runner still lacks productized classification, resume, cancellation, and recovery policy
workaround: fail closed, preserve immutable attempts, classify the failure, and require explicit new-attempt authorization; the current 32768 attempt is one bounded manual fallback instance, not an automatic recovery platform
reopen_trigger: Internal Alpha completion checkpoint, or a real transient provider/tool failure requiring user-visible recovery
trigger_state: satisfied_by_wall_relation_actual_context_rejects_and_run004_provider_timeout
implementation_timing: after Internal Alpha and before Coding Agent v0 public alpha
next_action: keep the immediate recovery manual and bounded; after Internal Alpha, add the minimum policy to the existing Runner/attempt owner using this failure as the first context-admission recovery sample
last_reviewed: 2026-08-22
required_before_stage: Coding Agent v0 public alpha
minimum_acceptance:
  - deterministic versus transient error classification
  - cooperative CANCEL_REQUESTED to safe point to CANCELLED transition
  - resume only from committed Artifact/checkpoint with fresh identity checks
  - fallback creates a new attempt and preserves the original failure
  - no silent model or tool switch
  - at least one bounded retry policy for an explicitly retryable technical failure
  - full circuit breaker, model gateway, and distributed resume are not required
```

### ENTRY-001

```yaml
issue_id: ENTRY-001
title: Public product execution lacks one unique Runner/owner entrypoint
scope: RAG-1B and Coding Agent v0 Public Alpha
owner: public Runner adoption and workflow entry ownership
evidence_level: checkpoint_and_tests
severity: S1
decision_priority: P2
status: deferred
first_seen: inventory records run-request, evidence-request, intelligent-evidence-request, and direct Graph/internal entry paths
latest_evidence: AccurateCrosshair run 8d26e4e5 invoked the existing ProductExecution/StateGraph once and committed five Store Artifacts, but its first projectless launch stopped before Runner entry because mutable lock/state were coupled to a read-only master packet directory; a sealed external execution-root wrapper was required for the successful single run
current_effect: one bounded internal actual used the same Runner, but the projectless handoff remains wrapper-bound and Public Alpha cannot yet claim one public lifecycle, route authority, Store truth, and terminal projection
workaround: keep current internal-alpha/calibration paths explicitly bounded and non-public
reopen_trigger: Internal Alpha completion checkpoint or RAG-1B activation
next_action: during RAG-1B, inventory every public, CLI, API, and MCP entry and make each delegate or explicitly exit product authority
last_reviewed: 2026-08-24
required_before_stage: Coding Agent v0 public alpha
minimum_acceptance:
  - exactly one public product entry invokes the same Agent Runner
  - one Runner owns run lifecycle and invokes the existing single StateGraph
  - conditional edges remain final route authority
  - ArtifactStore remains the sole durable business-output truth
  - Evidence sufficiency has one existing semantic owner
  - Plan/Patch/Review/Apply/Build/Repair contracts remain unchanged across entry adapters
  - evidence-request, intelligent-evidence-request, and diagnostic paths either delegate or are explicitly non-product with no Store, route, or final-result authority
  - no entry constructs a second Graph, interprets completion independently, writes duplicate business Artifacts, or bypasses Approval/Binding
  - public result correlates request, run, tool, observation, Artifact, Plan, Patch, Build, repair, and final result
  - focused entry-delegation tests
  - one real actual-only task completes through the unique public entry before a Public Alpha claim
```

### ENTRY-002

```yaml
issue_id: ENTRY-002
title: Fresh sealed execution entry cannot reliably admit packet-bound ProductExecution
scope: P2 expected-isolated sealed entry and same-context preflight
owner: sealed/fresh execution entry preflight; not ProductExecution, Evidence, provider, or the future Public Runner
evidence_level: real_run
severity: S1
decision_priority: P0
status: active
first_seen: p2_ac_20260825_001/attempt_1
incident_signatures:
  - A1: porcelain ?? was incorrectly classified as staged
  - A2: stdout.strip removed the first fixed-width porcelain status character
  - A3: source Git returned nonzero without retained stderr, so exact ownership was inconclusive
  - A4: source Git returned fatal dubious ownership under the fresh security principal
  - A5: preflight output-root textual path comparison rejected equivalent Windows paths before receipt creation
latest_evidence: Attempts1-4 entered no ProductExecution run and made zero model calls; Attempt5 payload 979c0fdeca85dbedf9e1156931cf0bf724b57fa69a0cdd2394612745d88f78f7 stopped in sealed_run.py::_write_fresh_preflight_receipt with fresh preflight output root argument drifted, produced no receipt/hash, did not consume the outer attempt, and did not authorize an actual
incident_record: docs/audits/ACCURATE_CROSSHAIR_SEALED_ENTRY_ATTEMPTS_20260825.md
incident_record_sha256: e21443626ed67561ee0206caed2edac1652a3b04f736315548890b01267a1241
current_effect: P2 product-path construction is admitted at checkpoint 32a939b3f217721b076704cd7e701369fef532ed, but sealed-entry admission is blocked and empirical ProductExecution actual remains unstarted
workaround: none authorized; preserve the first failures and keep actual blocked
reopen_trigger: any fresh sealed entry or preflight fails before packet-bound ProductExecution because entry identity, filesystem authority, Git trust, path equivalence, lock/state, or receipt admission is not represented consistently
close_trigger: one newly authorized fresh same-context preflight produces a hash-bound receipt after all packet/platform/source/Git/Ollama gates, and a separately authorized sealed actual enters ProductExecution without entry-side identity or permission repair
next_action: apply only a bounded Windows physical-path equivalence repair to the Attempt5 packet owner, rerun fresh same-context preflight under new authority, and request actual authorization only after receipt review
last_reviewed: 2026-08-25
required_before_stage: P2 empirical actual
minimum_acceptance:
  - declared textual and resolved canonical paths are compared by normalized physical identity before any strict textual receipt binding
  - packet hash, branch, HEAD, four protected WIP states, Git executable/version, source show-toplevel/HEAD/trees/snapshot, and Ollama identity remain exact
  - preflight-only creates no execution_root, model call, ProductExecution run, Build, Runtime, diff approval, or Apply
  - successful preflight writes one bounded receipt plus hash and does not itself authorize actual
  - failure preserves the exact first boundary and does not create an automatic next attempt
  - ENTRY-001 remains the separate future Public Runner adoption issue
```

## 5. Public Alpha Advanced Robustness Trigger Catalog

This catalog is not part of `Registered Issues`. Its entries are conditional
capability directions, not observations that a physical problem has occurred,
not claims that a capability exists, and not execution authority. Entries use
`capability_key`, never `issue_id`. Grouping by an expected owner family does
not authorize a shared implementation owner: activation must relocate the
current physical owner, and distinct owners require distinct Issues.

```yaml
catalog_key: public_alpha_activation_triggered_advanced_robustness_backlog
status: conditional_trigger
activation_trigger: Public Alpha readiness/entry activation plus explicit user selection
current_queue: false
internal_alpha_blocker: false
minimum_public_alpha_blocker: false
promotion_rule: Only a real risk audit performed at activation time may promote an entry into the minimum Public Alpha blocking boundary; activation first relocates the current physical owner, then creates a new single-owner Issue only when the observed risk requires implementation.
```

The existing `ENTRY-001`, `OPS-001`, `TOOL-001`, `REPORT-001`, and `REC-001`
`minimum_acceptance` lists remain the minimum Operational Readiness boundary
before Public Alpha. This catalog does not expand, replace, weaken, or complete
those hard gates.

### 5.1 Provider And Tool Resilience

#### Bounded Exponential Backoff Plus Jitter

```yaml
capability_key: provider_tool_bounded_exponential_backoff_jitter
expected_owner_family: existing Runner attempt policy and the exact provider or tool transport owner
real_activation_signal: repeated explicitly retryable transient failures after Public Alpha activation where immediate bounded retry causes synchronized load or unstable recovery
expected_benefit: spreads bounded retry pressure and reduces synchronized transient-failure amplification
cost_and_risk: adds latency, timing nondeterminism, retry-budget tuning, and a risk of replaying work outside its valid identity window
degradation_boundary: never retries non-idempotent or high-risk side effects automatically; exhausted or ineligible work stops with the original failure and a terminal receipt
separate_issue_on_activation: true
```

#### Full Circuit Breaker

This is the single catalog entry for both “full Circuit Breaker” and any
“complete circuit-breaker platform” wording; they must not become duplicates.

```yaml
capability_key: provider_tool_full_circuit_breaker
expected_owner_family: existing Runner attempt policy plus the exact failing provider or tool transport owner
real_activation_signal: repeated current failures show that bounded attempts continue reaching a known-unhealthy dependency and materially worsen availability or cost
expected_benefit: stops calls to a demonstrably unhealthy dependency and exposes an explicit open, half-open, and closed recovery boundary
cost_and_risk: requires durable health-window semantics, concurrency control, reset policy, observability, and protection against stale or cross-tenant health state
degradation_boundary: an open breaker grants no fallback authority and cannot convert unavailable evidence or execution into success
separate_issue_on_activation: true
```

#### Tool Gateway

```yaml
capability_key: provider_tool_gateway
expected_owner_family: existing tool manifest, resolver, preflight, and tool invocation boundary
real_activation_signal: Public Alpha exposes repeated cross-tool policy, identity, isolation, quota, or observability failures that cannot be represented by current tool instances and preflight
expected_benefit: centralizes verified tool identity, invocation policy, receipts, quotas, and isolation without giving tools route authority
cost_and_risk: creates a critical dependency and possible bottleneck, expands policy surface, and can obscure exact tool ownership if introduced without physical failures
degradation_boundary: gateway failure blocks or reduces the operation to an explicitly authorized read-only mode; it never fabricates a tool result or bypasses tool-specific validation
separate_issue_on_activation: true
```

#### Model Gateway

```yaml
capability_key: provider_model_gateway
expected_owner_family: existing model admission, disclosure, provider adapter, and attempt-policy boundary
real_activation_signal: Public Alpha shows repeated cross-model admission, capability-profile, quota, disclosure, or receipt failures that cannot be handled by current exact provider adapters
expected_benefit: provides one audited model admission and receipt boundary while retaining exact provider and attempt identities
cost_and_risk: concentrates routing and disclosure risk, may conceal provider-specific behavior, and can become a second workflow authority
degradation_boundary: gateway unavailability or uncertainty blocks model execution or reduces it to an explicitly authorized lower-permission mode; no silent provider or model switch is allowed
separate_issue_on_activation: true
```

### 5.2 Model Quality Resilience

#### Prevalidated Fallback Model Routing

```yaml
capability_key: model_prevalidated_fallback_routing
expected_owner_family: existing Runner attempt policy, model admission, and capability-profile validation owners
real_activation_signal: a repeated model-specific failure has a prevalidated alternate capability profile and a current user-selected fallback policy after Public Alpha activation
expected_benefit: permits bounded continuation after a classified model failure without erasing the original failure or widening authority
cost_and_risk: model outputs are not behaviorally interchangeable; routing can change quality, cost, latency, disclosure, and safety assumptions
degradation_boundary: fallback creates a new attempt, preserves the original failure, revalidates identity and disclosure, lowers permissions, and emits an auditable receipt; it never occurs silently
separate_issue_on_activation: true
```

#### Business-Quality Monitoring

```yaml
capability_key: model_business_quality_monitoring
expected_owner_family: existing product Eval and acceptance owners for the selected business capability
real_activation_signal: Public Alpha traffic provides outcome-bound quality observations whose deterioration is not visible through transport or schema success
expected_benefit: detects product-relevant quality loss separately from provider availability and syntactic validity
cost_and_risk: requires reviewed outcome definitions, delayed labels, sampling controls, privacy boundaries, and protection against metric gaming
degradation_boundary: monitoring is advisory until a reviewed policy binds it; weak or missing labels cannot block, route, or claim model quality automatically
separate_issue_on_activation: true
```

#### Model Drift Alerting

```yaml
capability_key: model_drift_alerting
expected_owner_family: existing model identity, capability-profile, and product Eval observation owners
real_activation_signal: a bound model, provider revision, or observed outcome distribution changes beyond a reviewed threshold after Public Alpha activation
expected_benefit: makes model or outcome drift visible before it silently changes product behavior
cost_and_risk: drift signals can be noisy, seasonal, data-sensitive, or unrelated to product quality and require version-aware baselines
degradation_boundary: an alert does not authorize fallback, prompt changes, threshold changes, or policy learning; uncertain drift remains an investigation signal
separate_issue_on_activation: true
```

#### Capability-Profile-Based Model Weighting Or Deprioritization

```yaml
capability_key: model_capability_profile_weighting_deprioritization
expected_owner_family: existing reviewed capability-profile registry and Runner model-selection policy owner
real_activation_signal: multiple prevalidated models are explicitly authorized and real Public Alpha outcomes show stable task-specific capability differences
expected_benefit: prefers models whose verified capability profiles fit the current bounded task while deprioritizing repeatedly weak profiles
cost_and_risk: weighting can become opaque adaptive routing, overfit sparse observations, or create self-reinforcing traffic bias
degradation_boundary: weights cannot grant new permissions, bypass exact model admission, or use an unvalidated profile; ambiguous profiles require explicit selection or manual escalation
separate_issue_on_activation: true
```

### 5.3 Capability Degradation

#### Cache-Backed Degradation

```yaml
capability_key: degradation_cache_backed
expected_owner_family: existing read-model, evidence freshness, and cache identity owners for the affected capability
real_activation_signal: Public Alpha availability requirements justify serving a previously verified bounded result when its source, scope, age, and invalidation conditions remain inspectable
expected_benefit: preserves limited read availability during a transient dependency failure
cost_and_risk: stale data can mislead planning, conceal dependency failure, or cross identity and authorization boundaries
degradation_boundary: cached data is labeled stale or cached with source identity and age; it never appears as fresh, current, complete, or sufficient evidence without revalidation
separate_issue_on_activation: true
```

#### Partial-Result Degradation

```yaml
capability_key: degradation_partial_result
expected_owner_family: existing result projection and sufficiency owner for the affected capability
real_activation_signal: a real Public Alpha operation can safely expose independently valid completed subsets while other declared subsets fail or remain unavailable
expected_benefit: returns inspectable useful work instead of discarding every valid subset
cost_and_risk: consumers may treat partial output as complete, combine incompatible subsets, or miss the failed coverage boundary
degradation_boundary: every partial result declares missing scope, failed owners, freshness, and non-authority; partial results cannot masquerade as complete Evidence or authorize writes
separate_issue_on_activation: true
```

#### Read-Only, Draft, Or Manual-Escalation Degradation

```yaml
capability_key: degradation_read_only_draft_manual_escalation
expected_owner_family: existing permission, approval, and operation-risk policy owners
real_activation_signal: Public Alpha encounters a classified degraded or fallback state where observation or drafting remains useful but normal write authority is not defensible
expected_benefit: preserves bounded assistance while preventing uncertain dependencies from performing high-risk actions
cost_and_risk: creates more user-visible states, handoff work, and possible confusion between drafts and approved changes
degradation_boundary: high-risk writes default to read-only, draft, or manual approval; degraded output never inherits normal Apply, Build, Runtime, or external side-effect authority
separate_issue_on_activation: true
```

### 5.4 Distributed Continuity

Distributed resume and distributed recovery share a capability family but are
not synonyms. Resume continues unfinished work from a durable checkpoint after
current identity and permission validation. Recovery reconstructs auditable
execution ownership and a terminal state after host, process, or worker
ownership is lost; it is not simple resume.

#### Distributed Resume

```yaml
capability_key: continuity_distributed_resume
expected_owner_family: existing Runner checkpoint continuation and immutable Artifact identity owners
real_activation_signal: Public Alpha deployment requires an unfinished authorized run to continue on another admitted worker from a durable checkpoint
expected_benefit: continues bounded work without replaying completed stages or losing immutable lineage
cost_and_risk: stale checkpoints, identity drift, double execution, split ownership, and cross-worker permission mismatch can corrupt the run
degradation_boundary: resume requires durable checkpoint ownership, fresh identity and permission validation, and an idempotent side-effect boundary; otherwise it remains blocked
separate_issue_on_activation: true
```

#### Distributed Recovery

```yaml
capability_key: continuity_distributed_recovery
expected_owner_family: existing Runner lifecycle, lease or ownership, checkpoint, and terminal-receipt owners
real_activation_signal: a real Public Alpha host, process, or worker loss leaves execution ownership or terminal state unresolved across machines
expected_benefit: reconstructs one auditable current owner and reaches a truthful terminal or resumable state after ownership loss
cost_and_risk: duplicate ownership, lost leases, partial side effects, stale observations, and ambiguous terminal state require distributed coordination
degradation_boundary: recovery cannot assume that checkpoint continuation is safe; it must reconcile durable ownership and side effects before resume, retry, or terminalization
separate_issue_on_activation: true
```

#### Durable Checkpoint Ownership

```yaml
capability_key: continuity_durable_checkpoint_ownership
expected_owner_family: existing ArtifactStore checkpoint identity and Runner ownership projection
real_activation_signal: Public Alpha distributed execution demonstrates that process-local checkpoint ownership cannot establish one current continuation authority
expected_benefit: binds each durable checkpoint to one inspectable run, revision, owner or lease, and continuation boundary
cost_and_risk: ownership metadata can become stale, create lock contention, or form a second business-truth store if separated from existing durable facts
degradation_boundary: an unowned, multiply owned, stale, or identity-mismatched checkpoint cannot authorize resume or recovery
separate_issue_on_activation: true
```

#### Idempotent Side-Effect Boundary

```yaml
capability_key: continuity_idempotent_side_effect_boundary
expected_owner_family: existing operation-specific approval, Apply, Build, Runtime, and external side-effect owners
real_activation_signal: Public Alpha continuity or retry scenarios expose a real risk of duplicating an already-started side effect after ownership loss
expected_benefit: makes retry, resume, and recovery distinguish completed, absent, and safely replayable side effects
cost_and_risk: requires operation-specific idempotency keys, receipts, reconciliation, and compensation boundaries that cannot be generalized without evidence
degradation_boundary: unknown or non-idempotent side effects block automatic retry, resume, backoff replay, and recovery; high-risk continuation requires manual approval
separate_issue_on_activation: true
```

### 5.5 Safety Invariants And Non-Activation Boundary

- Backup-model routing must never occur silently.
- Fallback may use only a prevalidated capability profile. It must create a new
  attempt, preserve the original failure, lower permissions, and produce an
  auditable receipt.
- High-risk writes in fallback or degraded mode default to read-only, draft, or
  manual approval.
- Backoff and jitter must never automatically replay non-idempotent or
  high-risk side effects.
- Cache-backed and partial results must never appear as fresh, current,
  complete, or sufficient Evidence.
- Distributed continuity requires durable checkpoint ownership, fresh identity
  validation, and an idempotent side-effect boundary.

This catalog is only the
`public_alpha_activation_triggered_advanced_robustness_backlog`. It does not
enter the current P1 Queue, does not block Internal Alpha, and does not
automatically become a minimum Public Alpha hard gate. Documentation is not
implementation: no advanced robustness direction in this catalog is claimed
implemented or complete. Semantic/vector Retrieval, Dense, RRF, and reranking
are not activated by this catalog.

## 6. Document Relationships

- `docs/ACTIVE_PRODUCT_CONTRACT.md` keeps only the current product selection and
  permission boundary; it does not copy this table.
- `docs/PROJECT_STATE.md` keeps only the current active blocker/selection and may
  link this register without copying entries.
- `docs/IMPLEMENTATION_QUEUE.md` keeps only selected executable or conditional
  work; an observed issue is not automatically queued.
- `docs/audits/LOOP_HISTORY.md` owns completed chronological narratives.
- This register retains compact problem identity and reopening conditions only.
