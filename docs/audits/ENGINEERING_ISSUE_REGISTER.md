# Engineering Issue Register

Status: lightweight observation register
Last reviewed: 2026-08-28

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
status: mitigated_for_current_scope
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

### EXEC-001

```yaml
issue_id: EXEC-001
title: Long packet and run roots exceeded the Windows isolated-workspace path budget
scope: P2 isolated workspace materialization before ProductExecution
owner: packet-bound execution-root path budget
evidence_level: real_run
severity: S1
decision_priority: P2
status: mitigated_for_current_scope
first_seen: actual1 run a63fdb36
latest_evidence: actual1 stopped at workspace_preparation before ProductExecution; its actual_failure SHA256 is 257855d76ce8de66b26915ffc8ef46ef539be91ee5de4b6e4ef82f351a322808 and product run_failure SHA256 is 54f74947912ebee5573cd47d40481062509faeea59c5fa7288fb060075d6eede. Short a6a2-a6a6 roots remained within the sealed path budget and later actuals entered ProductExecution
incident_record: docs/audits/CODING_AGENT_V0_RECENT_ISSUE_INTERACTION_AUDIT_20260826.md
current_effect: the selected Case no longer fails workspace materialization, but arbitrary long delivery roots are not claimed supported
workaround: seal a conservative destination-path budget and use a short packet-bound execution root
reopen_trigger: a fresh Windows actual that satisfies the sealed path budget fails workspace materialization because a projected destination path is too long, or a packet is sealed without checking every generated destination class
next_action: none in the current scope; reopen only on the exact workspace path-budget signature
last_reviewed: 2026-08-26
```

### BUILD-001

```yaml
issue_id: BUILD-001
title: Isolated baseline restore could not resolve the target project's GameFolder dependency
scope: run-local build dependency identity and MSBuild GameFolder projection
owner: src/mod_agent/local_entry.py::RunLocalGameFolderBindingV1
evidence_level: real_run
severity: S1
decision_priority: P2
status: mitigated_for_current_scope
first_seen: actual2 run d9c35191
latest_evidence: actual2 baseline restore reported `The GameFolder property must be set to the Game folder.`; checkpoint a182db4 added one exact read-only binding and run-local `-p:GameFolder`; actual6 run 905a0a60 then completed isolated baseline restore/build with DLL SHA256 174ce450da330c36bb57ab709880040e1961a3eeefd5bd48c6ab455c12b33e6d
incident_record: docs/audits/CODING_AGENT_V0_RECENT_ISSUE_INTERACTION_AUDIT_20260826.md
current_effect: the selected AccurateCrosshair baseline build dependency is admitted and buildable; changed-product Build remains not reached
workaround: use the exact sealed GameFolder snapshot through the run-local binding; do not modify canonical GameFolder.props
reopen_trigger: a new bound target with a verified run-local GameFolder dependency reaches baseline restore/build but the existing binding cannot project the exact property without changing canonical source
next_action: none in the current scope; do not generalize to arbitrary MSBuild properties without a real consumer
last_reviewed: 2026-08-26
```

### FS-001

```yaml
issue_id: FS-001
title: Ordinary Windows directory copy omitted or could not read long GameFolder dependency paths
scope: run-local GameFolder dependency copy on Windows
owner: src/mod_agent/local_entry.py::_copy_validated_directory_tree
evidence_level: real_run
severity: S1
decision_priority: P2
status: mitigated_for_current_scope
first_seen: actual3 run 65541df6
latest_evidence: actual3 stopped at build_dependency_copy with long-path file reads reported missing; checkpoint 1036f98 added validated extended-length path projection, and actual4 copied the physical 165-file dependency before the later independent snapshot failure
incident_record: docs/audits/CODING_AGENT_V0_RECENT_ISSUE_INTERACTION_AUDIT_20260826.md
current_effect: copy no longer blocks the selected Windows Case; long-path snapshot identity remained a separate owner under FS-002
workaround: use validated absolute extended-length source and destination paths only inside the bounded directory-copy owner
reopen_trigger: a fresh Windows run with an exact bound dependency again fails or omits a regular file during run-local copy because of path-length handling
next_action: none in the current scope; preserve the exact copy boundary and reject symlink/reparse expansion
last_reviewed: 2026-08-26
```

### FS-002

```yaml
issue_id: FS-002
title: GameFolder snapshot traversal omitted Windows long-path files and produced false identity drift
scope: run-local binary dependency snapshot and post-copy identity
owner: src/mod_agent/local_entry.py::_binary_tree_snapshot
evidence_level: real_run
severity: S1
decision_priority: P2
status: mitigated_for_current_scope
first_seen: actual4 run f3a54f16
latest_evidence: actual4 physically contained 165 source and destination files while the old snapshot observed 137 and rejected copy identity; product run_failure SHA256 is 2100c60a7e7f1580c242d2c533a09b11b5eb11312a73215b1514a77691a66b6f. Checkpoint 2ee3e03 added complete extended-length traversal; actual5 and actual6 admitted the full 165-file snapshot e7bed3c58810a0203f2aa08f58e1dc7d43def39574899d1add6f0fb46326673b
incident_record: docs/audits/CODING_AGENT_V0_RECENT_ISSUE_INTERACTION_AUDIT_20260826.md
current_effect: the selected dependency source/copy identity now remains equal and no longer blocks baseline Build
workaround: use the single complete long-path snapshot owner for binding, copy verification, and path budget inventory
reopen_trigger: a fresh Windows run reports source/copy count or hash drift while an independent physical inventory proves regular long-path files were omitted by the snapshot owner
next_action: none in the current scope; no second snapshot algorithm
last_reviewed: 2026-08-26
```

### EVID-002

```yaml
issue_id: EVID-002
title: Requirement projection structured output fails deterministic disposition admission after one correction
scope: ProductExecution requirement projection response-schema admission, semantic rejection diagnostics, and bounded correction contract
owner: src/mod_agent/evidence/requirement_coverage_provider.py::StructuredModelRequirementCoverageProvider.project
evidence_level: real_run
severity: S1
decision_priority: P3
status: closed
first_seen: actual5 run f6bdb182
latest_evidence: fresh actual p2_ac_20260825_010/actual_10, Product run 940f14d6, passed Entry, baseline Build, Requirement Projection, and reached Findings without REQUIREMENT_COVERAGE_INPUT_DISPOSITION_INVALID. Its actual_result SHA256 is 596ab34dcda6c97431481b6787dd954c539c0ff49bd6c078a1c1ded0ebe82128. Coverage was insufficient and ImplementationPlan blocked; Patch, ProposalReview, Dry-run, approval, Apply, changed-product Build, Repair, Revalidation, and Runtime were not reached
incident_record: docs/audits/CODING_AGENT_V0_RECENT_ISSUE_INTERACTION_AUDIT_20260826.md
implementation_checkpoint: 22f8fa0f6913e964b556d49c8d3d6a01ead5ae2e
implementation_checkpoint_lineage: 984716f09ef18111b781bcc1623bf184881f6e41 followed by diagnostic closure 22f8fa0f6913e964b556d49c8d3d6a01ead5ae2e
implementation_checkpoint_status: accepted_for_bounded_code_and_tests
close_evidence: actual10 met the original close trigger through a fresh passed preflight and a fresh actual that reached Findings without the prior Projection failure signature
current_effect: the old Projection owner is closed. This does not establish actual10 or product success; actual10 stopped at insufficient Coverage and a blocking ImplementationPlan, now owned separately by EVID-003
workaround: preserve the immutable actual5/actual6 outputs and fail-closed EvidencePack; do not add a third correction, switch model, change retrieval, or relax coverage policy
reopen_trigger: any selected real task returns a projection object that fails exact response-schema admission or deterministic input-disposition semantics after the single bounded correction
close_trigger: the accepted focused checkpoint is followed by a newly sealed preflight that passes, and a separately authorized fresh actual reaches findings without this failure signature
next_action: none; reopen only on the recorded reopen_trigger
last_reviewed: 2026-08-28
required_before_stage: none_closed
minimum_acceptance:
  - the returned projection object is locally validated against the exact response schema before semantic materialization
  - schema failure is distinct from duplicate disposition index, requirement/disposition overlap, disallowed disposition, invalid reason, and incomplete accounting
  - the one correction receives bounded machine-readable rejection detail without model reasoning or authority
  - failed output remains non-authoritative and cannot grant Evidence sufficiency or Patch authority
  - no third correction, model switch, retrieval expansion, or policy relaxation
```

### EVID-003

```yaml
issue_id: EVID-003
title: Supported change expected-delta gaps revoke the authoritative edit target before Planning
scope: ProductExecution Findings-to-Coverage expected-delta semantics and deterministic edit-target derivation
owner: src/mod_agent/evidence/requirement_coverage.py::resolve_requirement_coverage and Findings semantic boundary
evidence_level: real_run
severity: S1
decision_priority: P3
status: closed
first_seen: p2_ac_20260825_010/actual_10 Product run 940f14d6
latest_evidence: fresh actual p2_ac_20260825_012/actual_12 passed Entry, baseline Build, compiled-plugin inspection, Requirement Projection, RgLive Retrieval, and Findings; formed sufficient Coverage with edit_target_evidence_ids rg_live_7b954ec77325936f, rg_live_a301d80d4e9593b0, and rg_live_aad4f3b5731dbc95; set EvidencePack can_generate_patch=true; formed a non-blocking ImplementationPlan with blockers=[]; and entered generate_patch_proposal before the independent EVID-004 pre-call failure
actual_result: 'C:\Users\10160\Documents\Codex\2026-08-28\accurate-crosshair-actual12-fresh-preflight\outputs\actual_p2_ac_20260825_012_actual_12\e\p\p2_ac_20260825_012\run_result.json'
actual_result_sha256: 8b4f5388109519bd686091e768eb4f5c630e309eb3ff560d65c9428771ac395c
rg_live_method_span_checkpoint: 68893efb50acdd940608a3fd133fe6e79ddfc77b
implementation_checkpoint: 206c94d00b79d2c92fa162624a5d3b924409f396
implementation_checkpoint_status: accepted_for_bounded_code_and_tests_and_validated_by_actual12_close_evidence
bounded_semantics: role=change plus support plus an exact authoritative target-source identity retains an edit target even when unresolved gaps describe behavior that does not exist until the change; missing, conflict, pre_patch_evidence, and preservation remain fail closed
close_evidence: actual12 met the recorded close trigger through sufficient Coverage, three non-empty authorized edit-target evidence ids, a non-blocking ImplementationPlan, and entry into generate_patch_proposal while the existing missing, conflict, pre_patch_evidence, and preservation fail-closed semantics were unchanged
current_effect: the expected-delta owner is closed. This does not establish product success; actual12 stopped before the Patch model call under the separately registered EVID-004 owner
workaround: none required for EVID-003; preserve actual10, the Findings-only replay, and actual12 as immutable evidence and do not relax missing, conflict, pre_patch_evidence, or preservation gates
reopen_trigger: after closure, any selected real task again revokes an exact authoritative edit target solely because a supported role=change Finding retains the requested expected delta, or any missing/conflict/pre_patch_evidence/preservation case becomes authorized
close_trigger: a fresh actual forms Coverage sufficient, a non-empty authorized edit target, and enters non-blocking Planning and Patch, while missing, conflict, pre_patch_evidence, and preservation remain fail closed
next_action: none; reopen only on the recorded reopen_trigger
last_reviewed: 2026-08-28
required_before_stage: none_closed
minimum_acceptance:
  - Entry, Projection, RgLive Retrieval, and Findings are reached on the fresh actual
  - Coverage is sufficient and exposes a non-empty authorized edit target from exact authoritative source identity
  - Planning is non-blocking and generate_patch_proposal is entered
  - missing, conflict, pre_patch_evidence, and preservation remain fail closed
```

### EVID-004

```yaml
issue_id: EVID-004
title: Patch request duplicates full Evidence and edit_binding_contexts, pushing conservative admission to 51,064 over 40,960
scope: Patch model-input projection and Ollama structured-request pre-call context admission only
owner: src/mod_agent/proposal/code_generator.py::LLMExactPatchGenerator.generate Patch model-input projection plus existing Ollama structured pre-call admission
evidence_level: real_run
severity: S1
decision_priority: P0
status: active
first_seen: p2_ac_20260825_012/actual_12
latest_evidence: >-
  actual12 reached generate_patch_proposal after sufficient Coverage and non-blocking Planning, then failed at source_node=generate_patch_proposal, stage=generate_patch_proposal_execution, owner=platform, with OllamaLLMError: [Ollama] Structured request exceeds the configured pre-call context budget.
actual_result: 'C:\Users\10160\Documents\Codex\2026-08-28\accurate-crosshair-actual12-fresh-preflight\outputs\actual_p2_ac_20260825_012_actual_12\e\p\p2_ac_20260825_012\run_result.json'
actual_result_sha256: 8b4f5388109519bd686091e768eb4f5c630e309eb3ff560d65c9428771ac395c
consumption: consumed_once
failure_boundary: the third model role was Patch generation, but structured pre-call admission rejected its provider body before the Patch request was sent; total model_call_count=2 for requirement_projection and requirement_findings, Patch model calls=0, and patch_payload_parser_entered=false
unreached_effects: no Patch Artifact, ProposalReview, Dry-run, diff or approval, Apply, changed-product Build, Repair, Revalidation, or Runtime; the passed Build was baseline-only
physical_cause: the Patch request projected full Evidence together with edit_binding_contexts, including repeated declared_members and related facts, so the 46,968-byte body required a conservative 51,064 against configured num_ctx 40,960 with num_predict 4,096
implementation_checkpoint: 05bbca578baad23403d3ab7fc3327755592e3ac8
implementation_checkpoint_status: accepted_for_deterministic_code_and_tests_pending_fresh_preflight_and_actual
checkpoint_evidence: deterministic reconstruction of frozen actual12 data reduced the provider body from 46,968 to 26,440 bytes and conservative required context from 51,064 to 30,536 under the same num_ctx 40,960 and num_predict 4,096, changing admission from false to true; all six required edit/support excerpts remain present; missing or drifted authoritative input fails before the provider call; independent regressions report Patch plus ProductExecution plus Planning 169 passed and Local Entry 126 passed
checkpoint_claim_boundary: the model now receives only a deterministic compressed view while the complete EvidencePack and Binding Registry remain in process for post-response validation; this checkpoint does not prove a real Patch provider call, model output, schema or semantic admission, Review, or Dry-run
current_effect: only the Patch model call is blocked before provider admission. Retrieval, Findings, Coverage, and Planning already passed and are not owned by this Issue. No Patch output existed, so Qwen output quality is not implicated
workaround: preserve actual12 as consumed immutable evidence; do not infer retry authority from the checkpoint or treat deterministic reconstruction as a real Patch call
reopen_trigger: after closure, a fresh selected actual bound to the same compact-projection lineage again reproduces the old structured pre-call budget signature before a Patch provider call
close_trigger: a new fresh preflight bound to checkpoint 05bbca578baad23403d3ab7fc3327755592e3ac8 passes; a separately authorized new actual does not reproduce the old pre-call budget signature; and the Patch provider request is admitted and forms a real Patch model call. Any later model-output schema or semantic failure, ProposalReview result, or Dry-run failure belongs to the newly reached physical owner and does not keep EVID-004 open
next_action: a fresh sealed checkpoint-bound preflight requires separate user authorization; after receipt review, actual13 packet preparation and actual13 execution require separate authorizations. Neither actual13 nor any later attempt is pre-authorized
last_reviewed: 2026-08-28
required_before_stage: next P2 Patch provider call
minimum_acceptance:
  - the fresh preflight is sealed against checkpoint 05bbca578baad23403d3ab7fc3327755592e3ac8 and passes
  - the separately authorized fresh actual does not reproduce the old structured pre-call budget signature
  - the Patch provider request is admitted and a real Patch model call is formed
  - any failure after response arrival is assigned to its reached schema, semantic, Review, or Dry-run owner rather than retained under EVID-004
  - no fresh preflight, packet, actual, exact-diff approval, Apply, or changed-product Build is inferred from this Issue
```

### PLAN-001

```yaml
issue_id: PLAN-001
title: selected ProductExecution treats missing formal requirement coverage as legacy unrestricted planning
scope: selected ProductExecution create_implementation_plan coverage admission before edit-binding derivation
owner: src/mod_agent/planning/implementation_plan.py::ImplementationPlanner.build selected ProductExecution formal requirement-coverage admission
evidence_level: mechanical_replay
severity: S0
decision_priority: P0
status: closed
first_seen: HEAD f240d103df89b95c8259f2bca731afc34f26b02b deterministic vertical scenario; failing test test_product_execution_blocks_removed_formal_coverage_before_patch_effect
latest_evidence: the formal provider first generated valid requirement coverage; after the section was removed, readiness, can_generate_patch, and Evidence items remained, and Patch, Dry-run, isolated Apply, and Build call counts were 1/1/1/1 instead of 0/0/0/0. The valid formal-coverage positive vertical scenario passed through changed isolated bytes and a byte-consuming Build substitute. Canonical source was not written
reopen_trigger: selected ProductExecution forms an edit binding, Patch authority, or any later effect after the formal requirement coverage section is missing or invalid
close_trigger: a focused checkpoint makes selected ProductExecution mode require formal coverage and produces a blocking ImplementationPlan before edit binding or Patch when coverage is missing or invalid; the valid formal positive vertical still reaches changed isolated bytes and the byte-consuming Build substitute; legacy non-selected Planner/Graph behavior remains compatible; both negative scenarios have zero Apply and Build calls
implementation_checkpoint: 61a4df677ad39ca87ec9486ec0556481778c9c36
close_evidence: selected ProductExecution missing coverage now produces a blocking ImplementationPlan before edit binding or Patch; the valid formal positive reaches changed isolated bytes and the byte-consuming Build substitute; the coverage-removal and path/Review negatives have zero Apply/Build; full regressions passed requirement_coverage 33, product_execution 103, planning 30, proposal_review 32, patch_apply 22, workflow_graph 135, plus py_compile
current_effect: the deterministic selected ProductExecution authority bypass is closed. The checkpoint is composition/authority evidence only, not an actual or real Build; actual10 reached a blocking ImplementationPlan because Coverage was insufficient, under active Issue EVID-003
workaround: none required for PLAN-001; fresh preflight, receipt, actual11 packet preparation, and actual11 execution remain separately controlled
next_action: none; reopen only on the recorded reopen_trigger
last_reviewed: 2026-08-28
required_before_stage: next P2 empirical actual
minimum_acceptance:
  - selected ProductExecution missing formal requirement coverage fails closed
  - Patch, Dry-run, isolated Apply, and Build effect calls are all zero
  - no success terminal Artifact is created
  - valid formal coverage positive vertical still reaches changed isolated bytes and the byte-consuming Build substitute
  - legacy non-selected Planner and Graph behavior remains compatible
  - the selected ProductExecution path/Review negative passes
  - no new Artifact, Graph branch, Approval, or control plane
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
decision_priority: P2
status: mitigated_for_current_scope
first_seen: 2026-08-21 checkpoint 397629ee review
latest_evidence: the 2026-08-28 docs-only synchronization aligns Active Product Contract, Project State, Implementation Queue, and this Issue Register to product-code checkpoint 1b9acd0 and actual10. It records EVID-002 closed, EVID-003 active, P0 completed, the P2 Findings/Coverage boundary, and both Internal Alpha hard gates false. Internal Alpha documentation was outside this synchronization scope
current_effect: the four authorized status owners agree that P2 empirical execution reached Findings and is blocked by insufficient Coverage and a blocking ImplementationPlan under EVID-003; P0 remains completed and is not reopened. Documentation remains evidence projection rather than capability progress
workaround: keep detailed run evidence in one primary record and short selection fields elsewhere
reopen_trigger: Active Product Contract, Project State, Implementation Queue, or the §8 execution sequence name different current selections
trigger_state: mitigated_by_2026_08_28_actual10_docs_only_sync
next_action: keep detailed incident evidence in its audit record and reopen only if the owning short pages diverge again
last_reviewed: 2026-08-28
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
stable_runner_checkpoint: 81d0147c8bcabeccccd3244ea29253a0a0c22c01 -> 1b9acd0b780e2f54853fa0e8ebcd0ade322b1a39 accepted for bounded code/tests only, including best-effort terminal summary; it is not actual or runtime evidence
current_effect: current manual coordination does not block the selected EVID-003 validation or invalidate Internal Alpha evidence, but operational stability cannot be measured reliably and Public Alpha Operational Readiness remains blocked. The stable runner lineage does not close OPS-001
workaround: bounded attempts, per-call timeout, manual polling, and terminal Artifact/failure receipt
reopen_trigger: satisfied by run004 duration/progress opacity; implementation remains scheduled after Internal Alpha and before core stability/public alpha
trigger_state: satisfied_by_wall_run004_and_accurate_run8d26e4e5_without_heartbeat
implementation_timing: after Internal Alpha and before Core Stability Validation
next_action: after Internal Alpha, project lifecycle state from existing LangGraph state plus ArtifactStore/attempt facts
last_reviewed: 2026-08-28
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
latest_evidence: actual6 run 905a0a60 committed a blocked EvidencePack and ImplementationPlan after the earlier semantic provider failure REQUIREMENT_COVERAGE_INPUT_DISPOSITION_INVALID, but the top-level terminal blocker projected downstream REQUIREMENT_COVERAGE_INSUFFICIENT with owner=domain. The same result projected canonical_source_unchanged=false while source_change_verification=null; independent snapshot verification proved the source unchanged
current_effect: committed Store truth and run-local diagnostics remain recoverable, but the public terminal projection can hide the primary provider owner and collapses not_evaluated into false
workaround: use explicit field projection and Store readback for committed results; for current pre-Artifact calibration failures preserve the Provider diagnostic and manually retain the known control-flow limitation without rerunning solely to reconstruct Trace
reopen_trigger: an independent report/console/UI projection failure, or the Internal Alpha completion checkpoint
trigger_state: satisfied_by_wall_trace_gap_accurate_run8d26e4e5_and_actual6_primary_failure_tristate_drift
implementation_timing: after Internal Alpha and before Coding Agent v0 public alpha
next_action: do not interrupt EVID-003; after Internal Alpha, project primary_failure separately from downstream_disposition and preserve true/false/not_evaluated without changing Artifact schemas
last_reviewed: 2026-08-28
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
latest_evidence: relation-aware Wall runs preserved explicit attempts around context and timeout failures. AccurateCrosshair entry Attempts A1-A5 and Recovery actual1-actual6 preserve distinct packet, receipt, run, failure, checkpoint, and recovery identities; actual5 and actual6 each entered ProductExecution once, and no Recovery automatically replayed a consumed actual or approved a diff
stable_runner_checkpoint: 81d0147c8bcabeccccd3244ea29253a0a0c22c01 -> 1b9acd0b780e2f54853fa0e8ebcd0ade322b1a39 accepted for bounded code/tests only, including deterministic Actual root and journal/consumption race handling; it is not real recovery evidence
current_effect: the current Case and runner lineage demonstrate bounded immutable attempt controls, not automatic retry, durable distributed resume, fallback, or a general recovery platform. The lineage does not close REC-001
workaround: fail closed, preserve immutable attempts, classify the failure, and require explicit new-attempt authorization; the current 32768 attempt is one bounded manual fallback instance, not an automatic recovery platform
reopen_trigger: Internal Alpha completion checkpoint, or a real transient provider/tool failure requiring user-visible recovery
trigger_state: satisfied_by_wall_relation_actual_context_rejects_and_run004_provider_timeout
implementation_timing: after Internal Alpha and before Coding Agent v0 public alpha
next_action: do not route Attempts1–5 through REC-001 retry; after Internal Alpha, evaluate minimum general recovery policy only from separately classified real failures
last_reviewed: 2026-08-28
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
stable_runner_checkpoint: 81d0147c8bcabeccccd3244ea29253a0a0c22c01 -> 1b9acd0b780e2f54853fa0e8ebcd0ade322b1a39 accepted for bounded code/tests only, including one deterministic Actual root, no per-run Python launcher, RunSpec field projection, and GameFolder/compiled-artifact profile passage; it is not a public-entry actual
current_effect: bounded internal actuals and the stable Actual runner lineage do not establish one adopted public entrypoint. Public Alpha cannot yet claim one public lifecycle, route authority, Store truth, and terminal projection, so ENTRY-001 remains deferred
workaround: keep current internal-alpha/calibration paths explicitly bounded and non-public
reopen_trigger: Internal Alpha completion checkpoint or RAG-1B activation
next_action: during RAG-1B, inventory every public, CLI, API, and MCP entry and make each delegate or explicitly exit product authority
last_reviewed: 2026-08-28
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
decision_priority: P3
status: closed
first_seen: p2_ac_20260825_001/attempt_1
incident_signatures:
  - A1: porcelain ?? was incorrectly classified as staged
  - A2: stdout.strip removed the first fixed-width porcelain status character
  - A3: source Git returned nonzero without retained stderr, so exact ownership was inconclusive
  - A4: source Git returned fatal dubious ownership under the fresh security principal
  - A5: preflight output-root textual path comparison rejected equivalent Windows paths before receipt creation
latest_evidence: checkpoint c906d99 owns Entry admission. Fresh preflight4 produced ready receipt SHA256 5a46b500e1078aa01afd952a551ae1624f7bf240a91f8c28f44a35a1fef7e0b0 and actual5 entered ProductExecution without entry repair. After checkpoint 2b18874, fresh preflight5 produced ready receipt SHA256 383c856ac4d12e08c91eaa215452fe4c941d79a58dbeec5248badf1ca4112859 and actual6 again entered ProductExecution without entry repair
incident_record: docs/audits/ACCURATE_CROSSHAIR_SEALED_ENTRY_ATTEMPTS_20260825.md
incident_record_sha256: d2b19630bd209cb03eb7af04f99aad67d80b70bab986dea73756126563322044
packet_only_repair_stop_condition: satisfied_by_attempt5
implementation_checkpoint: c906d99dba8f1850864e090c4f925a78fbd4f373
code_owner_and_focused_test_boundary: met
fresh_same_context_admission: passed_for_current_scope_twice
current_effect: no current Entry blocker remains; actual10 passed Entry and reached Findings, while its downstream Coverage/Planning failure belongs to EVID-003 inside ProductExecution
workaround: none required for the current scope; each new checkpoint still requires its normal hash-bound preflight and separate actual authority
reopen_trigger: any fresh sealed entry or preflight fails before packet-bound ProductExecution because entry identity, filesystem authority, Git trust, path equivalence, lock/state, or receipt admission is not represented consistently
close_trigger: one newly authorized fresh same-context preflight produces a hash-bound receipt after all packet/platform/source/Git/Ollama gates, and a separately authorized sealed actual enters ProductExecution without entry-side identity or permission repair
next_action: none; reopen only on a new failure before ProductExecution with an Entry-owned signature. ENTRY-001 remains the separate Public Alpha adoption issue
last_reviewed: 2026-08-28
required_before_stage: P2 empirical actual
code_checkpoint_met:
  - repository EntryAdmission request/result/blocker/receipt owner exists with focused tests
  - textual/canonical Windows paths use physical parent identity and normalized leaf identity
  - strict Git identity is shared by entry and downstream source verification without PATH fallback on the strict route
  - no ProductExecution schema, StateGraph, or Artifact contract was added or changed
closure_evidence:
  - preflight4 and preflight5 each passed packet, platform, source, Git, and Ollama gates with model generation and ProductExecution counts zero
  - actual5 and actual6 each revalidated Entry and entered one ProductExecution run without entry-side identity or permission repair
  - no preflight authorized actual, no outer retry occurred, and no packet supplied exact-diff approval
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

All retry-capable entries in this family retain one logical retry owner. An
adapter reports transport/tool facts; it does not independently replay work or
compete with the Runner attempt owner.

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

#### Formal Model Comparative Evaluation

```yaml
capability_key: model_formal_comparative_evaluation
expected_owner_family: existing product Eval, model identity, expected-isolation, and reviewed selection owners
real_activation_signal: stable model interfaces plus a real product bottleneck plus explicit user selection justify a frozen comparative run
expected_benefit: distinguishes task-bound model capability, latency, cost, and failure behavior without changing defaults from anecdotes
cost_and_risk: requires frozen task, model, runtime, Prompt, schema, source, and expected-isolation identities and can otherwise reward leakage or unstable interfaces
degradation_boundary: one old diagnostic, social-media claim, or desire to complete an experiment cannot activate comparison or change the default model; no default change occurs before Level 2 evidence
separate_issue_on_activation: true
```

### 5.3 Capability Degradation

`FULL`, `EVIDENCE_DEGRADED`, `PLAN_ONLY`, and `SAFE_STOP` are logical mappings
over existing readiness, blocker, coverage, and authority facts. They do not add
a schema. Degradation can only preserve or contract authority; unknown source,
permission, or side-effect state maps to `SAFE_STOP`.

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

#### Side-Effect Reconciliation

```yaml
capability_key: continuity_side_effect_reconciliation
expected_owner_family: existing operation-specific receipt, approval, Apply, Build, Runtime, and external-effect owners
real_activation_signal: a real authorized operation loses process or ownership continuity after a side effect may have started and current receipts cannot determine its physical state
expected_benefit: classifies the current effect as NOT_APPLIED, APPLIED, PARTIALLY_APPLIED, or UNKNOWN before any continuation decision
cost_and_risk: reconciliation is operation-specific and can itself observe stale or incomplete external state; false certainty can duplicate or conceal effects
degradation_boundary: retry is eligible only for NOT_APPLIED plus a verified idempotent operation; UNKNOWN and non-idempotent states safe-stop pending manual authority
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
- One logical retry owner decides whether a classified operation is retryable;
  adapters and gateways never retry independently.
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

## 6. Conditional Retrieval Activation Catalog

This catalog is conditional and does not use `issue_id`. It does not activate
semantic/vector Retrieval, add current Queue work, or grant Evidence authority.
`RET-001` remains limited to the observed bge-m3 plus Chroma full-R8
materialization failure; it does not own future semantic retrieval as a whole.

### 6.1 Semantic Retrieval A/B

```yaml
capability_key: retrieval_semantic_ab
activation_trigger: a selected real task misses mandatory source through exact, symbol, lexical, and live retrieval; independent current-source inspection proves the source exists; the user explicitly selects a bounded A/B
required_evidence:
  - frozen task, source snapshot, query set, baseline Retriever identity, semantic provider identity, and expected-isolated relevance judgment
  - one independently verified mandatory-source miss attributable to location recall rather than Entry, coverage, provider timeout, or authority failure
minimum_acceptance:
  - compare unique Recall@K against the non-semantic baseline
  - rehydrate every semantic hit from live source and reject stale identity
  - measure false-sufficiency behavior and preserve deterministic Patch-authority gates
non_activation:
  - ENTRY failure, requirement-coverage failure, provider timeout, available embedding dependency, repository size alone, or architecture-completeness preference
stop_condition: record only the bounded A/B result; do not activate fusion, storage, or default adoption without a separate trigger
```

### 6.2 Hybrid Fusion

```yaml
capability_key: retrieval_hybrid_fusion
activation_trigger: a completed semantic A/B shows independent product-relevant gain and current retrievers demonstrate complementary misses under explicit user selection
required_evidence:
  - frozen outputs and identities for exact/symbol/lexical and semantic retrievers
  - evidence that neither retriever alone covers the bounded mandatory-source set
minimum_acceptance:
  - compare baseline, simple merge, and bounded RRF without changing sufficiency or authority owners
  - report recall, duplicate suppression, latency, stale rejection, and failure attribution
non_activation:
  - semantic provider availability, one attractive hit, or desire to implement a documented architecture
stop_condition: retain the simplest method unless bounded fusion shows independent gain; do not activate persistence or reranking automatically
```

### 6.3 Persistent Vector Storage

```yaml
capability_key: retrieval_persistent_vector_storage
activation_trigger: semantic retrieval has verified product gain and a real consumer proves material rebuild cost, multi-task or multi-repository reuse, or incremental invalidation cannot be handled by a rebuildable run-local cache
required_evidence:
  - measured rebuild and query cost over bound source identities
  - repeated consumer demand plus explicit invalidation and ownership requirements
minimum_acceptance:
  - exact index identity binds provider, embedding model, chunking, source snapshot, and schema
  - stale entries are rejected and rebuild/incremental invalidation is deterministic
  - the index remains a cache and never becomes Evidence, sufficiency, or Patch authority
non_activation:
  - one hundred thousand lines, installed vector dependencies, general scale concern, or unmeasured future reuse
stop_condition: prefer rebuildable ephemeral storage until measured consumers justify persistence; stop on unresolved stale-index or ownership behavior
```

## 7. Document Relationships

- `docs/ACTIVE_PRODUCT_CONTRACT.md` keeps only the current product selection and
  permission boundary; it does not copy this table.
- `docs/PROJECT_STATE.md` keeps only the current active blocker/selection and may
  link this register without copying entries.
- `docs/IMPLEMENTATION_QUEUE.md` keeps only selected executable or conditional
  work; an observed issue is not automatically queued.
- `docs/audits/LOOP_HISTORY.md` owns completed chronological narratives.
- This register retains compact problem identity and reopening conditions only.
