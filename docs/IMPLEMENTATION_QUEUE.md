# Implementation Queue

This file contains only active and near-future executable work. Completed loop details are archived in `docs/audits/LOOP_HISTORY.md`.
## Queue Policy

```text
Do not execute a task unless dependencies are explicit.
Do not mark done without tests or a documented reason tests cannot run.
Do not add optional dense/vector/multimodal work before BM25/symbol/text evidence contracts are stable.
Do not let GTFO-specific behavior enter generic workflow modules.
If capability-first execution conflicts with this queue, refresh the queue before coding.
Keep the controlled code-generation loop runnable before deep optional Knowledge Hub expansion.
Use docs/SPEC_COVERAGE_MATRIX.md to identify affected requirement rows before starting a task.
Do not close a task without updating every affected coverage row.
```

## Current Queue

```text
current_queue: Expert Skill Decomposition
last_completed: SKILL-SPLIT-003
next_recommended_task: create repair-loop-playbook as the next expert Skill split from the committed E2E-001 delivery chain
Q_queue_status: Q-022, MISS-022, MISS-026A, STATE-001, SKILL-MCP-001, E2E-001, SKILL-SPLIT-001, SKILL-SPLIT-002, and SKILL-SPLIT-003 completed; MISS-026 remains open and is explicit opt-in production runtime automation work
next_stage_after_expert_split: PLANNING-BRIEF-001 create mod-planning-brief-playbook after SKILL-SPLIT-004 and a Skill split closure audit
```

## Evidence Provenance Policy

```text
Git-verifiable evidence:
  A task is current-branch evidence only when its referenced source/test files exist in this branch and focused tests have been run in the current branch.

Checkpoint evidence:
  E2E-001 is current-branch evidence only when the checkpoint commit containing tests/unit/test_mod_delivery_e2e.py, DEV_SPEC.md, control docs, restored LOOP_HISTORY, and the delivery Skill is present in branch history.

Test claim boundary:
  E2E-001 only claims its focused and affected test commands passed.
  Full unit baseline is not claimed green by E2E-001.

Historical record evidence:
  docs/audits/LOOP_HISTORY.md is restored from rescue commit c43f4ec and can explain Q-000B through Q-019 and R-001 through R-005 history.
  Historical records do not replace current-branch file/test verification.

Current known missing historical references:
  docs/EXECUTION_CONTROL_GUIDE.md
  src/mod_agent/evaluation/agent_quality.py
  src/mod_agent/evaluation/retrieval_regression.py
  src/mod_agent/git/workflow_binding.py
  src/mod_agent/mcp/jobs.py
  tests/fixtures/evaluation/agent_quality_cases.json
  tests/fixtures/retrieval/golden_queries.json
  tests/unit/test_agent_quality_eval.py
  tests/unit/test_mcp_async_jobs.py
  tests/unit/test_retrieval_regression.py
  tests/unit/test_runtime_screenshots.py
  tests/unit/test_workflow_checkpointing.py
```

## Skill And Auto-Coder Boundary

```text
auto-coder:
  .agents/skills/auto-coder/SKILL.md remains the DEV_SPEC.md-driven platform-development Skill.
mod-delivery-playbook:
  Planned process-only Skill for the user-facing mod delivery chain.
patch-review-playbook:
  Process-only expert Skill for patch proposal, diff, repair proposal, evidence binding, permission, path, risk, and handoff review procedure.
runtime-diagnosis-playbook:
  Process-only expert Skill for build/runtime evidence diagnosis, runtime evidence mode classification, acceptance signal checks, claim boundary control, and repair or handoff routing.
hook-discovery-playbook:
  Process-only expert Skill for behavior decomposition, evidence-first hook discovery, hook option review, risk classification, and proposal/runtime diagnosis handoff.
Boundary:
  Process playbooks must not replace auto-coder, store current state, duplicate interface schemas, or embed test results.
Runtime Skill system boundary:
  Process playbooks do not implement a runtime Skill registry, Skill selector, Skill loader, LangGraph selected-skill node injection, or Skill output validator.
Hook automation boundary:
  Process playbooks do not implement an automatic hook scanner, decompiler integration, runtime patch executor, or game binary scanner.
Planning brief boundary:
  The planned mod-planning-brief-playbook is not implemented yet. It must not claim natural-language-to-RAG extraction, accumulated-experience retrieval, planning negotiation, feature_spec generation, or code-generation guidance is validated until a future checkpoint creates and verifies that Skill.
```

## Post E2E-001 Optional Capability Policy

```text
Policy purpose: keep optional platform expansion explicit after the first end-to-end delivery chain is repeatable.

Default-paused items unless explicitly selected:
  - real dense retrieval provider
  - full multimodal ingestion and caption pipeline
  - dashboard polish beyond read-only controlled-agent summaries
  - multi-MCP write operations
  - automatic run_game and copy_to_game_directory operations
  - large-scale benchmark harnesses

Allowed next:
  - control-document recovery
  - evidence provenance reconciliation
  - read-only/report-only MCP inspection
  - expert process Skills split from the proven E2E-001 chain after closure review
  - explicit user-directed platform development through auto-coder
```

## Current Stabilization Queue

| Task | Status | Scope | Evidence |
| --- | --- | --- | --- |
| STATE-001 | completed | Restore LOOP_HISTORY, distinguish current Git-verifiable evidence from historical records, and record E2E-001 scope control | `docs/audits/LOOP_HISTORY.md`, `docs/PROJECT_STATE.md`, `docs/IMPLEMENTATION_QUEUE.md`, `docs/SPEC_COVERAGE_MATRIX.md` |
| E2E-001 | completed | Prove one minimal planning-to-handoff chain: user planning input, feature_spec, evidence lookup, patch proposal, review, build/runtime evidence, and handoff summary | `tests/unit/test_mod_delivery_e2e.py`; affected suite: workflow/build/runtime/artifact tests |
| SKILL-MCP-001 | completed | Create the first process-only Skill for the minimal delivery chain without replacing auto-coder or embedding current state, schema copies, or test results | `.agents/skills/mod-delivery-playbook/SKILL.md` |
| SKILL-SPLIT-001 | completed | Split patch-review-playbook from the proven delivery chain without embedding current branch facts, schema copies, or test results | `.agents/skills/patch-review-playbook/SKILL.md`; `python .agents\skills\skill-creator\scripts\quick_validate.py .agents\skills\patch-review-playbook` |
| SKILL-SPLIT-002 | completed | Split runtime-diagnosis-playbook from the proven delivery chain without embedding current branch facts, schema copies, test results, or runtime Skill system behavior | `.agents/skills/runtime-diagnosis-playbook/SKILL.md`; `python .agents\skills\skill-creator\scripts\quick_validate.py .agents\skills\runtime-diagnosis-playbook` |
| SKILL-SPLIT-003 | completed | Split hook-discovery-playbook from the proven delivery chain without embedding current branch facts, schema copies, test results, runtime Skill system behavior, or automatic hook scanning behavior | `.agents/skills/hook-discovery-playbook/SKILL.md`; `python .agents\skills\skill-creator\scripts\quick_validate.py .agents\skills\hook-discovery-playbook` |
| SKILL-SPLIT-004 | queued | Split repair-loop-playbook from the proven delivery chain without embedding current branch facts, schema copies, test results, runtime Skill system behavior, or automatic repair execution | New `.agents/skills/repair-loop-playbook/SKILL.md` plus control-doc update |
| SKILL-SPLIT-CLOSURE-001 | queued_after_SKILL-SPLIT-004 | Audit process Skills after repair-loop-playbook: validate every Skill, confirm no template residue, confirm E2E-001 evidence remains discoverable, and confirm docs do not claim runtime Skill system or real game automation | `quick_validate.py` for process Skills; `git ls-tree` over `.agents/skills`; control-doc overclaim scan |
| PLANNING-BRIEF-001 | queued_after_skill_split_closure | Create mod-planning-brief-playbook for natural language mod idea negotiation, knowledge evidence lookup planning, accumulated experience use, planning brief output, and feature_spec/code-generation guidance | New `.agents/skills/mod-planning-brief-playbook/SKILL.md` plus control-doc update |

## V1 Acceptance Audit Queue

```text
Queue purpose: verify the current implementation against DEV_SPEC.md V1 acceptance boundaries before adding further Q work.
```

| Task | Status | Scope | Evidence |
| --- | --- | --- | --- |
| V1-AUDIT-001 | completed | Audit V1 acceptance boundaries and gate FakeDenseRetrievalProvider behind explicit test opt-in | `docs/V1_ACCEPTANCE_AUDIT.md`, `tests/unit/test_config_loading.py` |
| V1-AUDIT-002 | completed | Carry FeatureSpec acceptance contract through runtime_evidence and eval_report, and enforce strict acceptance_verified routing | `src/mod_agent/workflow/graph.py`, `tests/unit/test_workflow_graph.py`, `tests/unit/test_repair_loop.py` |
| V1-AUDIT-003 | completed | Verify manual/supplied runtime acceptance evidence contract matching outside fake runtime fixtures | `src/mod_agent/runtime/evidence.py`, `tests/unit/test_runtime_evidence.py` |
| V1-AUDIT-004 | completed | Make fake/local eval and workflow summaries explicitly block V1 acceptance when real build/runtime evidence is missing | `src/mod_agent/workflow/graph.py`, `src/mod_agent/artifacts/registry.py`, `tests/unit/test_workflow_graph.py`, `tests/unit/test_artifact_contract.py` |
| V1-AUDIT-005 | completed | Produce the final V1 acceptance verdict and queue handoff without claiming real runtime execution | `docs/V1_ACCEPTANCE_AUDIT.md`, `docs/SPEC_COVERAGE_MATRIX.md` |

## Legacy Test Triage

```text
LEGACY-TEST-001_status: queued
Scope: normalize full-suite dependency parity, external-service gates, Windows Chroma cleanup, RAGAS compatibility, and historical legacy test assertions.
Policy: LEGACY-TEST-001 does not block R-009. R-009 may only absorb evidence_retrieval, stub_nodes, and sparse_encoder failures that directly affect retrieval authority or evidence boundary behavior.
```

## Hardening Follow-ups

```text
R-009-HARDENING-001_status: completed
Source task: R-009 Retrieval Authority Boundary
Scope: harden authority defaults, raw evidence-pack provenance, dashboard authority display semantics, and shared retrieval tokenization.
Policy: this records R-009 residual hardening work and does not reopen the completed R-009 loop.
Required follow-ups:
  - EvidenceItem.authority should default to legacy_rag_auxiliary; deterministic retrievers should explicitly set mod_agent_deterministic.
  - ImplementationPlanner should not treat raw dict evidence items with missing authority as authoritative.
  - ImplementationPlanner should eventually consume ArtifactRef/envelope or provenance-validated evidence payloads instead of untrusted raw dicts.
  - Dashboard authority displays must show readiness, can_generate_patch, and authoritative_for_patch together so authority is not misread as patch approval.
  - sparse/query tokenization should be extracted into a shared implementation to remove case and rule drift.
Recommended placement: address with artifact provenance / R-012 hardening, R-013 dashboard projection, and retrieval tokenizer cleanup work.
Implementation evidence:
  - EvidenceItem.authority now defaults to legacy_rag_auxiliary.
  - DeterministicEvidenceRetriever explicitly sets mod_agent_deterministic on symbol, symbol-index, BM25, and text evidence items.
  - ImplementationPlanner blocks authoritative raw dict packs missing identity_schema_version, identity_field_mapping, explicit item authority, or deterministic item provenance metadata; auxiliary context items are ignored for planning.
  - DashboardProjectionBuilder exposes readiness, can_generate_patch, authority, authoritative_for_patch, and projection_status together in the evidence summary.
  - QueryProcessor and SparseEncoder now share tokenize_retrieval_text for code-like retrieval tokenization; jieba remains a mandatory dependency and no silent fallback is used.
  - focused R-009-HARDENING-001 tests passed under .venv: 93 passed, 1 warning.
  - affected R-009-HARDENING-001 tests passed: 68 passed.
  - dashboard smoke passed: 6 passed.
```
## Recently Completed

Historical details for completed loops live in `docs/audits/LOOP_HISTORY.md`.

| Task | Status | Summary | History |
| --- | --- | --- | --- |
| Q-000B | completed | Spec coverage matrix created | `docs/audits/LOOP_HISTORY.md` |
| Q-001 | completed | Current implementation re-audited against spec | `docs/audits/LOOP_HISTORY.md` |
| Q-002A | completed | Controlled fake execution loop | `docs/audits/LOOP_HISTORY.md` |
| Q-002 | completed | Knowledge Hub text/metadata contracts | `docs/audits/LOOP_HISTORY.md` |
| Q-003 | completed | Source discovery and ignore rules | `docs/audits/LOOP_HISTORY.md` |
| Q-004 | completed | SQLite metadata store contract | `docs/audits/LOOP_HISTORY.md` |
| Q-005 | completed | BM25 inverted index V1 | `docs/audits/LOOP_HISTORY.md` |
| Q-006 | completed | Symbol Index V1 | `docs/audits/LOOP_HISTORY.md` |
| Q-007 | completed | EvidencePack timing and missing evidence fields | `docs/audits/LOOP_HISTORY.md` |
| Q-008 | completed | Retrieval regression query list | `docs/audits/LOOP_HISTORY.md` |
| Q-009 | completed | MCP async job contract | `docs/audits/LOOP_HISTORY.md` |
| Q-010 | completed | Workflow retrieval integration reconciled | `docs/audits/LOOP_HISTORY.md` |
| Q-011 | completed | Git decision-to-commit binding | `docs/audits/LOOP_HISTORY.md` |
| Q-012 | completed | Manual and supplied runtime evidence contract | `docs/audits/LOOP_HISTORY.md` |
| Q-013 | completed | Real build adapter contract | `docs/audits/LOOP_HISTORY.md` |
| Q-014 | completed | Repair loop and retry budget | `docs/audits/LOOP_HISTORY.md` |
| Q-015 | completed | Checkpoint interrupt resume contract | `docs/audits/LOOP_HISTORY.md` |
| Q-016 | completed | Dashboard trace viewer MVP | `docs/audits/LOOP_HISTORY.md` |
| Q-017 | completed | Domain Adapter and GTFO GameProfile contracts | `docs/audits/LOOP_HISTORY.md` |
| Q-018 | completed | Runtime screenshot registry contract | `docs/audits/LOOP_HISTORY.md` |
| Q-019 | completed | Agent decision-quality evaluation contract | `docs/audits/LOOP_HISTORY.md` |
| R-001 | completed | Graph domain policy wiring | `docs/audits/LOOP_HISTORY.md` |
| R-002 | completed | Evidence pack required for evidence-bound review | `docs/audits/LOOP_HISTORY.md` |
| R-003 | completed | Evidence source paths separated from edit target paths in planning/proposal | `docs/audits/LOOP_HISTORY.md` |
| R-004 | completed | Build success claims require expected artifact verification | `docs/audits/LOOP_HISTORY.md` |
| R-005 | completed | ArtifactStore enforces required upstream lineage | `docs/audits/LOOP_HISTORY.md` |
| R-006 | completed | Dashboard destructive operations are blocked by default behind confirmation, explicit enablement, permission decision, and operation summaries | `docs/audits/LOOP_HISTORY.md` |
| R-007 | completed | Trace/dashboard reads are redacted by default, raw access is explicit, timing preserves raw zero duration, and dashboard smoke e2e passes | `docs/audits/LOOP_HISTORY.md` |
| R-008 | completed | Fake/local execution summaries distinguish workflow completion from requested behavior success | `docs/audits/LOOP_HISTORY.md` |
| R-009 | completed | Legacy RAG output is auxiliary only; controlled implementation can advance only from mod_agent deterministic evidence packs | `docs/PROJECT_STATE.md` |
| R-010 | completed | Controlled-agent retrieval uses one collection resolver for explicit collection overrides and configured defaults | `docs/PROJECT_STATE.md` |
| R-011 | completed | Controlled-agent knowledge/evidence identity fields now have explicit mapping, artifact schema metadata, and write-time validation | `docs/PROJECT_STATE.md` |
| R-012 | completed | Checkpoint resume is bound to proposal/review/diff hashes and restores checkpoint state before resume | `docs/PROJECT_STATE.md` |
| R-013 | completed | Controlled-agent dashboard projection exposes sanitized workflow/artifact/proposal/build/runtime/repair/eval summaries and dashboard page integration | `docs/PROJECT_STATE.md` |
| R-009-HARDENING-001 | completed | Evidence authority defaults, raw dict provenance checks, dashboard authority projection, and shared tokenizer hardening | `docs/PROJECT_STATE.md` |
| Review Repair Queue refresh | completed | Confirmed no active Review Repair Queue blocker remains before Q-020; future open gaps stay tracked by the coverage matrix | `docs/PROJECT_STATE.md` |
| Q-020 | completed | Controlled-agent performance budget contract adds config-driven limits, blocked/degraded budget decisions, trace summaries, and job_status budget_summary serialization | `docs/PROJECT_STATE.md` |
| Q-021 | completed | Controlled-agent MCP tool surface exposes read-only/report-only status, artifact, retrieval, proposal, review, eval, and job summaries with degraded budget semantics preserved | `docs/PROJECT_STATE.md` |
| Q-022 | completed | Dense retrieval provider contract is disabled by default, supports fake provider chunk hits, reports retrieval budget accounting, and cannot replace BM25/symbol V1 gates; real embedding/vector retrieval remains deferred | `docs/PROJECT_STATE.md` |
## Review Repair Queue

```text
Status: inactive after post R-009-HARDENING-001 refresh
Source review: C:/Users/10160/Desktop/ai学习/mod_agent_full_issue_summary.md
Policy:
  - R tasks supersede ordinary Q feature work when an active P0/P1 review
    finding is queued.
  - Each R task must be closed through the normal small-loop gate: code/test
    inspection, implementation, focused tests, affected tests when shared
    contracts change, diff audit, control-doc update, git decision, stop.
  - P0/P1 findings must not be hidden by broad "next phase" progress.
  - Q-020 and later feature work can proceed while this queue is inactive.
```

### R-003: Separate Evidence Source From Edit Target

```text
Status: completed
Module: PLAN, PROP, REVIEW
Spec refs: 9, 10, 49.3
Source finding: P0-004
Goal: Split evidence_source_path from edit_target_path so implementation_plan cannot use a retrieval source as a write target by default.
Inputs: feature_spec, evidence_pack, source discovery metadata
Files to modify: src/mod_agent/planning/implementation_plan.py, proposal builder/reviewer tests
Artifacts produced: implementation_plan JSON in tests
Trace events: planning.edit_target_unresolved optional
Tests: unresolved edit target blocks implementation planning or marks target as unresolved; evidence source remains read-only
Acceptance criteria: write targets come from source discovery/edit-target resolution, not directly from evidence source_path
Failure behavior: missing edit target produces blocked plan with blockers
Out of scope: full C# symbol-aware edit-target resolver
Dependencies: source discovery contract
Conflict checks: no code may treat evidence_source_path as permission to edit
Completed evidence:
  - ImplementationPlan payloads now include evidence_source_paths separate from target_files.
  - ImplementationPlanner only resolves target_source evidence items into edit_target_path and target_files.
  - decompiled_api evidence remains read-only and produces EDIT_TARGET_UNRESOLVED when no target_source edit target exists.
  - PatchProposalBuilder blocks non-blocking plans that do not carry edit_target_path.
  - ProposalReviewer remains a final validation gate; no edit-target resolution was added there.
  - focused R-003 tests passed: 32 passed.
  - affected workflow/domain/dashboard/git/repair/checkpoint tests passed: 36 passed, 4 skipped.
```

### R-004: Build Expected Artifact Verification

```text
Status: completed
Module: BUILD, ART, REPAIR
Spec refs: 12, 14.4, 49.4.2
Source finding: P0-005
Goal: Require expected artifact existence/path safety/hash or mtime verification before claiming real build success.
Inputs: BuildProfile, BuildResult, expected_artifacts
Files to modify: src/mod_agent/build/adapter.py, tests/unit/test_build_adapter.py
Artifacts produced: build_result JSON in tests
Trace events: build.artifact_verified or existing build trace event
Tests: exit code 0 without expected artifact is blocked or inconclusive; verified artifact allows real build success claim
Acceptance criteria: claims_real_build_success cannot be true from process exit code alone
Failure behavior: missing/unsafe artifact routes to repair_handoff or blocked build_result
Out of scope: real dotnet build execution in unit tests
Dependencies: Q-013
Conflict checks: fake/local build artifacts must remain clearly non-real
Completed evidence:
  - BuildResult payloads now include verified_artifacts and artifact_verification.
  - Local real builds with exit_code 0 fail artifact verification when expected_artifacts are missing or unsafe.
  - claims_real_build_success is true only after a real local build verifies every expected artifact with path, sha256, size, and mtime evidence.
  - supplied_output and fake build paths remain unable to claim real build success.
  - focused R-004 tests passed: 30 passed.
  - affected workflow/repair/dashboard/runtime tests passed: 29 passed.
```

### R-005: Artifact Upstream Contract Enforcement

```text
Status: completed
Module: ART, WF
Spec refs: 6, 30, 49.1
Source finding: P1-004
Goal: Enforce required_upstream_artifacts in ArtifactStore.write and test missing/stale upstream rejection.
Inputs: ArtifactContract registry, ArtifactStore.write, upstream_refs
Files to modify: src/mod_agent/artifacts/store.py, tests/unit/test_artifact_store.py, workflow tests if needed
Artifacts produced: all affected artifact types in tests
Trace events: artifact.write_blocked optional
Tests: evidence_pack without required feature_spec blocks; downstream artifact missing upstream blocks; valid chain writes
Acceptance criteria: contract.required_upstream_artifacts is active behavior, not only documentation
Failure behavior: write raises/returns structured blocked error matching existing store style
Out of scope: persistence backend migration
Dependencies: Q-003, Q-014, Q-015
Conflict checks: update tests that intentionally wrote incomplete artifacts
Completed evidence:
  - ArtifactStore.write now enforces required_upstream_artifacts declared by ArtifactTypeRegistry contracts.
  - Missing required upstream artifact types block before writing with ArtifactStoreError.
  - Upstream refs must match the write feature_id, envelope artifact_type, stored hash, schema contract, and freshness check.
  - Stale upstream refs block normal writes with StaleArtifactError.
  - resume_report can record a blocked stale-resume audit artifact through explicit allow_stale_upstreams.
  - Repair patch proposals now carry implementation_plan, evidence_pack, and repair_plan lineage.
  - focused R-005 tests passed: 27 passed.
  - affected workflow/repair/checkpoint/dashboard tests passed: 25 passed.
```

### R-006: Dashboard Destructive Operation Guard

```text
Status: completed; not e2e verified
Module: OBS, REVIEW, ART
Spec refs: 18, 39, 45.12
Source finding: P0-006
Goal: Disable or guard DataService delete_document/reset_all with permission checks, audit records, and explicit confirmation.
Inputs: dashboard DataService, permission model, audit artifact contract
Files to modify: src/observability/dashboard/services/data_service.py, tests/unit/* or dashboard service tests
Artifacts produced: audit/operation summary in tests if existing artifact path supports it
Trace events: dashboard.destructive_operation_blocked optional
Tests: default delete/reset is blocked; confirmed path records an operation summary if enabled
Acceptance criteria: dashboard read-only claims are not contradicted by unguarded destructive methods
Failure behavior: blocked operation returns structured blocked result without deleting data
Out of scope: UI redesign
Dependencies: permission policy
Conflict checks: do not remove user data during tests
Completed evidence:
  - DataService delete_document returns DashboardOperationResult with operation_summary and errors when blocked.
  - DataService reset_all returns a summary dict with operation_summary and zero deletion counts when blocked.
  - Default delete/reset calls do not initialise or mutate storage.
  - Confirmed, explicitly enabled, permission-allowed delete/reset paths record operation summaries.
  - focused R-006 tests passed: 11 passed.
  - dashboard smoke is not required for R-006 clean completion because R-006 acceptance is service-level destructive-operation guarding.
  - dashboard smoke is verified under R-007 after installing streamlit in .venv.
```

### R-007: Trace And Dashboard Redaction Boundary

```text
Status: completed
Module: OBS
Spec refs: 18, 39, 45.12
Source finding: P0-007
Goal: Add redaction, size caps, and allowlisted keys for trace/dashboard display paths.
Inputs: trace_service, dashboard pages, metadata payloads
Files to modify: src/observability/dashboard/services/trace_service.py, src/observability/dashboard/pages/*, tests/unit/*
Artifacts produced: sanitized trace payloads in tests
Trace events: none
Tests: long text/path-like secrets are capped or redacted; allowlisted summary fields remain visible
Acceptance criteria: dashboard can inspect workflow state without exposing full raw text or sensitive paths by default
Failure behavior: unsupported payloads render as redacted summaries
Out of scope: full secret-scanning engine
Dependencies: none
Conflict checks: debugging detail can be exposed only through explicit unsafe raw/debug access if implemented
Closure evidence so far:
  - TraceService list_traces and get_trace now return sanitized trace dicts by default.
  - TraceService safe_mode=True remains redacted; raw trace payloads require explicit include_raw=True.
  - Sensitive keys redact entire values before recursion, including nested dict/list values.
  - Path keys, Windows absolute paths, POSIX absolute paths such as /work/... paths, and long strings are redacted or capped in nested trace metadata and stage data.
  - get_stage_timings preserves stage summary fields and supports legacy direct stage fields.
  - TraceContext total elapsed timings use raw perf_counter_ns measurement without fabricating a positive duration floor.
  - focused R-007 closure-repair tests passed: 56 passed.
  - dashboard smoke e2e passed after installing streamlit in .venv: 6 passed.
```

### R-008: Fake Execution Status Normalization

```text
Status: completed
Module: WF, BUILD, RUN, OBS
Spec refs: 12, 15, 18, 49.4
Source finding: P0-001
Goal: Normalize fake/local execution display so done/success envelopes cannot be read as real build/runtime/gameplay success.
Inputs: dry_run_result, build_result, runtime_evidence, eval_report, workflow_summary
Files to modify: src/mod_agent/workflow/graph.py, dashboard projection if affected, tests/unit/*
Artifacts produced: workflow_summary JSON in tests
Trace events: workflow.summary_written or existing event
Tests: fake path reports inconclusive/fake execution completed and all claims_real_* fields remain false
Acceptance criteria: user-facing summary distinguishes workflow completion from requested behavior success
Failure behavior: missing evidence mode blocks success claims
Out of scope: real runtime collector
Dependencies: Q-002A, Q-012, Q-013, Q-019
Conflict checks: do not break blocked-review path
Completed evidence:
  - fake build_result tests now expect build_status=fake_completed, not fake_success.
  - fake eval_report and workflow_summary payloads include workflow_completion_status=fake_execution_completed.
  - fake eval_report and workflow_summary payloads include requested_behavior_status=not_verified.
  - workflow_summary final_status remains inconclusive and all claims_real_* fields remain false.
  - artifact contract tests require the completion/status fields in eval_report and workflow_summary.
  - focused R-008 tests passed: 41 passed.
  - affected repair/dashboard tests passed: 17 passed.
```

### R-009: Retrieval Authority Boundary

```text
Status: completed
Module: RET, KB, WF
Spec refs: 8, 37, 45, 49
Source finding: P1-001
Goal: Define and enforce the authority boundary between legacy RAG query_engine outputs and mod_agent deterministic evidence gates.
Inputs: RAG query engine, mod_agent evidence_pack, readiness gate
Files to modify: docs/SPEC_COVERAGE_MATRIX.md, retrieval/evidence modules and tests if behavior changes
Artifacts produced: evidence_pack JSON in tests
Trace events: retrieval.authority_resolved optional
Tests: auxiliary RAG output cannot directly approve patching or bypass readiness
Acceptance criteria: only mod_agent evidence/readiness artifacts can advance controlled implementation
Failure behavior: unsupported source routes to insufficient evidence
Out of scope: replacing legacy RAG APIs
Dependencies: Q-007, Q-010
Conflict checks: preserve mature RAG skeleton as auxiliary evidence subsystem
Completed evidence:
  - EvidenceItem now carries an authority value and EvidencePack artifacts serialize authority plus authoritative_for_patch.
  - EvidenceReadinessClassifier blocks legacy_rag_auxiliary-only evidence as AUXILIARY_RETRIEVAL_NOT_AUTHORITATIVE.
  - ImplementationPlanner requires authority=mod_agent_deterministic_evidence and authoritative_for_patch=true before planning writable changes.
  - Stub retrieval evidence is explicitly marked non-authoritative for patching.
  - sparse/query tokenization preserves code-like terms such as machine-learning, deep_learning, and gpt-4 for retrieval boundary tests.
  - focused R-009 tests passed: 123 passed, 1 warning.
  - affected workflow/dashboard tests passed: 21 passed.
  - affected hybrid/query trace tests passed: 43 passed, 1 warning.
```

### R-010: Single Collection Resolver

```text
Status: completed
Module: KB, RET, MCP
Spec refs: 7, 8, 45
Source finding: P1-002
Goal: Introduce one collection resolver and remove scattered hardcoded default collection decisions from controlled-agent paths.
Inputs: config/settings.yaml, knowledge database, retrievers, MCP/query tools
Files to modify: src/mod_agent/knowledge/*, src/mod_agent/evidence/*, src/mod_agent/mcp/*, tests/unit/*
Artifacts produced: none
Trace events: retrieval.collection_resolved optional
Tests: default collection resolves consistently from config; explicit collection overrides are honored
Acceptance criteria: controlled-agent paths do not each invent their own default collection
Failure behavior: missing collection config returns structured blocked/degraded result
Out of scope: legacy RAG global cleanup unless directly used by mod_agent
Dependencies: Q-005, Q-009
Conflict checks: avoid breaking existing RAG tests by changing unrelated defaults
Completed evidence:
  - CollectionResolver now resolves explicit collection_id first and otherwise reads vector_store.collection_name from settings.
  - DeterministicEvidenceRetriever no longer hardcodes the controlled-agent default collection; it uses CollectionResolver.
  - build_graph accepts collection_id and collection_resolver for controlled retrieval paths.
  - Collection resolution failures produce an insufficient EvidencePack and route the workflow to blocked instead of crashing.
  - No tracked src/mod_agent/mcp files exist in the current tree, so no controlled MCP collection resolver path was changed in R-010.
  - focused R-010 tests passed: 23 passed.
  - affected repair/knowledge/config tests passed: 12 passed.
```

### R-011: Identifier And Hash Field Mapping

```text
Status: completed
Module: KB, RET, ART
Spec refs: 6, 7, 8, 30
Source finding: P1-003
Goal: Document and enforce the mapping among document_id, source_hash, file_hash, doc_hash, chunk_id, and source_ref.
Inputs: knowledge models, evidence models, artifact payloads
Files to modify: src/mod_agent/knowledge/models.py, src/mod_agent/evidence/models.py, tests/unit/*, docs/SPEC_COVERAGE_MATRIX.md
Artifacts produced: evidence_pack and knowledge records in tests
Trace events: none
Tests: identity fields serialize consistently and evidence refs resolve to chunks/documents without ambiguity
Acceptance criteria: each id/hash field has one meaning and one conversion path
Failure behavior: ambiguous or missing identity fields block indexing/evidence binding
Out of scope: database data migration
Dependencies: R-005 optional
Conflict checks: preserve backward-compatible aliases only with explicit mapping tests
Completed evidence:
  - knowledge.models now declares identity_v1 mapping for document_id, file_hash, source_hash, doc_hash, chunk_id, source_ref, and content_hash.
  - IndexedFile.to_document and chunk_from_document populate explicit file_hash/doc_hash/source_ref fields while preserving source_hash as a tested V1 alias for file_hash.
  - KnowledgeDatabase upsert_document and upsert_chunk reject missing or inconsistent identity metadata before persistence.
  - EvidenceItem serializes chunk/document/source/hash identity fields so evidence items can resolve back to chunks and documents when retrieval is chunk-backed.
  - evidence_pack artifact payloads now include identity_schema_version and identity_field_mapping.
  - .gitignore now anchors root /artifacts/ runtime output so src/mod_agent/artifacts/*.py is not ignored as source code.
  - Artifact envelope/store/freshness/registry source modules are tracked as formal code.
  - focused and affected R-011 plus artifact store tests passed: 77 passed.
```

### R-012: Checkpoint Resume Graph Binding

```text
Status: completed
Module: WF, ART, GIT
Spec refs: 5.6, 49.1.5
Source finding: P1-005
Goal: Bind checkpoint/resume to proposal and diff hashes in graph execution, and prove state restoration through tests.
Inputs: workflow_checkpoint, resume_report, patch_proposal, proposal_review
Files to modify: src/mod_agent/workflow/checkpointing.py, src/mod_agent/workflow/interrupts.py, graph tests
Artifacts produced: workflow_checkpoint, resume_report JSON in tests
Trace events: workflow.checkpoint_created, workflow.resume_rejected or existing events
Tests: graph resume restores expected state and rejects changed proposal/diff hashes
Acceptance criteria: resume cannot skip review or continue from stale proposal state
Failure behavior: stale resume returns STALE_RESUME_REJECTED or existing exact code
Out of scope: durable production checkpoint backend
Dependencies: Q-015, R-005
Conflict checks: checkpoint tests must not mutate Git history
Known R-005 PASS_WITH_RISK follow-up gaps:
  - Freshness checks are direct-upstream only, not full transitive DAG freshness.
  - ArtifactStore.read does not recompute envelope content hash; it compares envelope artifact_hash to ArtifactRef artifact_hash.
  - Artifact paths are still one feature/type file and do not preserve immutable historical revision files.
  - allow_stale_upstreams must remain audit/report-only and must not become an execution-input bypass.
Completed evidence:
  - workflow_checkpoint payloads now include resume_binding with patch_proposal ref/hash, proposal_review ref/hash, and a sha256 diff_hash derived from patch_proposal.diff_intent.
  - ResumeValidator rejects missing or mismatched diff_hash when a checkpoint has a bound diff_hash.
  - Accepted resume decisions include restored_state from the checkpoint state_snapshot so the graph resume point cannot silently skip the reviewed state.
  - checkpoint smoke tests prove accepted restore behavior, double resume rejection, changed patch_proposal stale rejection, and changed diff_hash rejection.
  - artifact contract tests require resume_binding on workflow_checkpoint payloads.
  - focused and affected R-012 tests passed: 48 passed.
```

### R-013: Mod-Agent Dashboard Projection

```text
Status: completed
Module: OBS, WF, ART
Spec refs: 18, 39, 45.12
Source finding: P1-006
Goal: Add dashboard pages or projection services for mod_agent workflow, artifact, proposal, build, runtime, repair, and eval summaries.
Inputs: artifacts, traces, workflow summaries, dashboard projection service
Files to modify: src/mod_agent/dashboard/*, src/observability/dashboard/* if integrated, tests/unit/*
Artifacts produced: dashboard projection summaries in tests
Trace events: none
Tests: projection exposes safe summaries for key artifact types without raw sensitive payloads
Acceptance criteria: dashboard observes controlled-agent state instead of only legacy RAG data
Failure behavior: missing artifacts show explicit empty/blocked states
Out of scope: visual polish and live web server E2E
Dependencies: R-007, Q-018, Q-019
Conflict checks: use sanitized projection; do not expose raw artifact bodies by default
Completed evidence:
  - DashboardProjectionBuilder reads ArtifactStore refs and returns sanitized summaries for workflow, artifact, proposal, build, runtime, repair, and eval state.
  - Projection outputs contract-declared dashboard_projection fields and derived counts/statuses, not raw artifact bodies.
  - raw_supplied_output, diff_intent, sensitive keys, and absolute paths are not exposed in projection output by default.
  - Missing artifacts render explicit empty states; stale artifacts expose freshness status and stale_reasons; unknown artifact types render blocked summaries without leaking raw data.
  - Streamlit dashboard includes a read-only Controlled Agent page backed by the projection.
  - .gitignore keeps runtime artifacts ignored while allowing src/mod_agent/build/*.py and src/mod_agent/dashboard/*.py source files to be tracked.
  - focused R-013 tests passed: 6 passed.
  - affected R-013 safety/workflow tests passed: 68 passed.
  - dashboard smoke passed: 6 passed.
```

### Q-020: Performance Budget And Resource Limit Contract

```text
Status: completed
Module: PERF, MCP, KB
Spec refs: 45.18.1, 45.18.2, 45.18.4, 41.6
Coverage IDs: PERF-001, PERF-002, PERF-004, PERF-006, MISS-013
Goal: Add budget/resource-limit contracts for indexing, retrieval, eval, captions, and tool calls.
Inputs: config/settings.yaml, MCP async job contract, EvidencePack timing
Files to modify: src/mod_agent/performance* or src/mod_agent/mcp/*, config/settings.yaml, tests/unit/*
Artifacts produced: performance benchmark or job_status JSON in tests
Trace events: perf.budget_checked, perf.limit_exceeded optional
Tests: over-budget operation is blocked or degraded; timing summary is serializable
Acceptance criteria: limits are config-driven and do not require network calls
Failure behavior: route to blocked/degraded status with explicit reason
Out of scope: real load testing infrastructure
Dependencies: Q-009, Q-007
Conflict checks: performance claims require measured outputs
Completed evidence:
  - config/settings.yaml now defines performance.operations budgets for indexing, retrieval, eval, captions, and tool_call.
  - src/core/settings.py parses optional PerformanceSettings and validates on_exceed values.
  - PerformanceBudgetPolicy checks OperationUsage against BudgetLimit and returns allowed, blocked, or degraded BudgetDecision results.
  - Unconfigured operations are blocked by default, cache_enabled is enforced when configured, and max_concurrency must be greater than zero.
  - Degraded decisions keep allowed true while using blocked artifact envelope status so dashboard/eval cannot treat degradation as success.
  - BudgetDecision exposes perf.budget_checked and perf.limit_exceeded trace-event summaries.
  - job_status payloads can include budget_summary, and dashboard projection includes that field.
  - focused Q-020 tests passed: 31 passed.
  - affected Q-020 tests passed: 35 passed.
```

### Q-021: Controlled-Agent MCP Tool Surface

```text
Status: completed
Module: MCP, ART, WF
Spec refs: 20.3, 45.12
Coverage IDs: MCP-001
Goal: Expose safe controlled-agent read-only/report-only tool schemas for workflow status, artifact reading, retrieval preview, proposal preview, review, eval, and job status.
Inputs: ArtifactStore, workflow state summaries, MCP async job contracts
Files to modify: src/mod_agent/mcp/*, tests/unit/*
Artifacts produced: none
Trace events: none
Tests: dangerous tools stay hidden; tool outputs include structuredContent, artifact_refs, trace_refs, blockers
Acceptance criteria: tool schemas match current artifact contracts and do not apply patches or run games
Failure behavior: unsupported tools return structured errors
Out of scope: network server deployment
Dependencies: Q-009, ART-001
Conflict checks: confirmed_apply, copy_to_game_directory, run_game, and delete_artifacts remain disabled
Completed evidence:
  - src/mod_agent/mcp/tools.py exposes only read-only/report-only controlled-agent tools.
  - Dangerous tools are hidden from list_tools and unsupported when called.
  - Tool results include status, content, structuredContent, artifact_refs, trace_refs, blockers, and isError.
  - get_artifact returns sanitized dashboard_projection summaries and does not expose raw artifact bodies.
  - get_job_status reads budget_summary.allowed for continuation semantics and treats envelope.status as artifact visibility/audit metadata only.
  - focused Q-021 tests passed: 6 passed.
  - affected Q-021 artifact/dashboard/performance tests passed: 33 passed.
  - affected Q-021 legacy MCP tests passed: 13 passed, 4 warnings.
```

### Q-022: Dense Retrieval Provider Contract

```text
Status: completed
Module: RET, KB, PERF
Spec refs: 8.7, 45.8, 45.18.1
Coverage IDs: RET-004, PERF-001
Goal: Add a disabled-by-default dense retrieval provider abstraction with explicit cost/budget accounting.
Inputs: ChunkRecord text_for_embedding, KnowledgeDatabase, config/settings.yaml
Files to modify: src/mod_agent/evidence/*, src/mod_agent/knowledge/*, config/settings.yaml, tests/unit/*
Artifacts produced: evidence_pack JSON in tests if enabled through fake provider
Trace events: retrieval.dense_started, retrieval.dense_finished optional
Tests: dense disabled by default; fake provider can return chunk ids; API budget accounting is reported
Acceptance criteria: dense retrieval cannot replace BM25/symbol V1 gates and must be trace-visible
Failure behavior: unavailable provider degrades to existing retrieval routes
Out of scope: real external embedding API calls
Dependencies: Q-005, Q-006, Q-007
Conflict checks: no network calls in unit tests
Implementation evidence:
  - Added dense retrieval provider contract with DisabledDenseRetrievalProvider and FakeDenseRetrievalProvider.
  - Dense route is disabled by default through config/settings.yaml and Settings.retrieval.
  - This is a contract-level dense retrieval closure only; it does not implement production embedding calls or vector database retrieval.
  - FakeDenseRetrievalProvider is for unit-test contract verification, must not be presented as real semantic retrieval, and now requires allow_test_providers=True when loaded through settings.
  - Fake dense hits can return chunk ids from KnowledgeDatabase stable chunks through ChunkRecord.text_for_embedding projection.
  - Dense evidence remains legacy_rag_auxiliary, so it cannot approve can_generate_patch without BM25/symbol deterministic evidence.
  - EvidencePack now serializes budget_summary for dense retrieval cost/accounting.
  - focused and affected Q-022 retrieval/config/artifact/dashboard/performance/knowledge tests passed: 88 passed.
  - affected Q-022 workflow/planning/proposal tests passed: 32 passed.
```


## Refresh Rule

After completing any five tasks:

```text
1. Re-run relevant focused tests.
2. Update docs/PROJECT_STATE.md coverage levels.
3. Mark completed tasks done with evidence.
4. Add the next 5-10 tasks from DEV_SPEC.
5. Check for conflicts before continuing.
```
