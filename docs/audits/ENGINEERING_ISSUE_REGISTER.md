# Engineering Issue Register

Status: lightweight observation register
Last reviewed: 2026-08-22

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
latest_evidence: 6553 input tokens exceeded the service-default 4096 context; run002 and later bounded runs sent options.num_ctx=16384
current_effect: no current context admission blocker when the explicit 16384 run setting is used
workaround: use the existing finite run-level context_window setting without changing product defaults
reopen_trigger: a new authorized run fails context admission with an explicit, model-supported context setting
next_action: freeze request/input/output/context facts before considering any change
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

### DOC-001

```yaml
issue_id: DOC-001
title: Authoritative documents disagreed on the current selected product slice
scope: Active Product Contract, Project State, Implementation Queue, and Coding Agent v0 target
owner: authoritative documentation state synchronization
evidence_level: checkpoint_and_tests
severity: S2
decision_priority: P2
status: mitigated_for_current_scope
first_seen: 2026-08-21 checkpoint 397629ee review
latest_evidence: checkpoint d13382e18d9b9ad4f85ac303e68e0c85bfe12104 aligns WallCrawler selected/pending authorization and links the Dense decision record
current_effect: current pages restore the WallCrawler selection instead of the stale r8 task
workaround: keep detailed run evidence in one primary record and short selection fields elsewhere
reopen_trigger: Active Product Contract, Project State, Implementation Queue, or the §8 execution sequence name different current selections
next_action: update only the owning short status fields; do not duplicate full run narratives
last_reviewed: 2026-08-22
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
severity: S1
decision_priority: P0
status: active
first_seen: WallCrawler run002
latest_evidence: EvidencePack 4588f5f5e357e00f788ec552af6960c0302aa3adb8ca48987956665077e2d704; generic comparison matched insufficiency, block, and empty acceptable identities while only 2/4 lanes completed and verified_findings was empty; checkpoint 0001a86 adds a tested shared verdict gate but structured expected-relation scoreability remains unimplemented; RAG-1A outcome report SHA256 7EFC4F46CB41162585F56F21EF4CB48EA7E347CC676188935D7256C5F5FBA95B
current_effect: WallCrawler cannot currently evaluate Agent negative capability; RAG-1A is explicit unresolved rather than passed
workaround: none; preserve actual and comparison as inconclusive evidence
reopen_trigger: current active until structured relation scoreability and the formal comparator can distinguish a grounded negative conclusion from incomplete execution
next_action: wait for an explicit user decision on structured relation scoreability; do not infer a negative capability pass from generic comparison
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
status: deferred
first_seen: BHF and WallCrawler local actuals required chat polling while only per-provider timeout was available
latest_evidence: WallCrawler run002 remained a single bounded process with no machine-readable stage heartbeat until terminal Artifact receipt
current_effect: does not block WallCrawler or Internal Alpha evidence, but blocks Public Alpha operational readiness
workaround: bounded attempts, per-call timeout, manual polling, and terminal Artifact/failure receipt
reopen_trigger: Internal Alpha completion checkpoint, or any run exceeds explainable duration or has no machine-readable terminal progress
next_action: after Internal Alpha, project lifecycle state from existing LangGraph state plus ArtifactStore/attempt facts
last_reviewed: 2026-08-22
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
latest_evidence: read-only Store projection confirmed the committed FeatureSpec and failure-attempt hashes after the console projection failed
current_effect: Store truth survives, but a user-facing terminal/report can fail after a successful commit
workaround: explicit field projection followed by Store readback
reopen_trigger: an independent report/console/UI projection failure, or the Internal Alpha completion checkpoint
next_action: define one reporting serializer/projection after Internal Alpha without changing Artifact schemas
last_reviewed: 2026-08-22
required_before_stage: Coding Agent v0 public alpha
minimum_acceptance:
  - one stable serializer/projection for ArtifactRef, attempt, and result
  - report failure cannot hide a committed business result
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
status: deferred
first_seen: long BHF and WallCrawler runs relied on bounded no-retry protocol and manual waiting
latest_evidence: immutable attempts and fail-closed stops preserve truth, but no unified cancellation/resume/fallback policy exists
current_effect: calibration correctness remains safe, but Public Alpha cannot promise graceful operational recovery
workaround: fail closed, preserve immutable attempts, and require explicit new authorization
reopen_trigger: Internal Alpha completion checkpoint, or a real transient provider/tool failure requiring user-visible recovery
next_action: after Internal Alpha, add the minimum policy to the existing Runner/attempt owner
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
latest_evidence: current internal and calibration paths remain bounded but do not prove one public lifecycle, route authority, Store truth, and final result projection
current_effect: internal diagnostics can run, but Public Alpha cannot claim one product execution owner
workaround: keep current internal-alpha/calibration paths explicitly bounded and non-public
reopen_trigger: Internal Alpha completion checkpoint or RAG-1B activation
next_action: during RAG-1B, inventory every public, CLI, API, and MCP entry and make each delegate or explicitly exit product authority
last_reviewed: 2026-08-22
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

## 5. Document Relationships

- `docs/ACTIVE_PRODUCT_CONTRACT.md` keeps only the current product selection and
  permission boundary; it does not copy this table.
- `docs/PROJECT_STATE.md` keeps only the current active blocker/selection and may
  link this register without copying entries.
- `docs/IMPLEMENTATION_QUEUE.md` keeps only selected executable or conditional
  work; an observed issue is not automatically queued.
- `docs/audits/LOOP_HISTORY.md` owns completed chronological narratives.
- This register retains compact problem identity and reopening conditions only.
