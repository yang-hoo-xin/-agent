# Project State

This file is the active state summary for the Controlled Mod Agent Platform.
Historical loop details are archived in `docs/audits/LOOP_HISTORY.md`.

Last updated: 2026-07-05

## Current Queue

```text
current_queue: Post V1 Acceptance Handoff
last_completed: MISS-026A
next_recommended_task: continue MISS-026 if real game process launch, persistent log collection, and screenshot capture are the goal
ordinary_queue_status: Q-022, MISS-022, and MISS-026A completed; real game runtime automation remains tracked as MISS-026
```

## Current Baseline

```text
branch: codex/miss-026-runtime-collector
remote: https://github.com/yang-hoo-xin/-agent.git
baseline commit: 914f16e chore: establish controlled mod agent baseline
baseline tag: baseline-controlled-agent-v0
repair chain:
  R-001-R-005 aggregate baseline: 55c0d66 chore(repair): restore R-001-R-005 historical repair baseline
  R-006 clean extraction: 525d8e7 fix(dashboard): extract R-006 destructive operation guard
  R-007 closure repair: 1c398dd fix(observability): close R-007 trace redaction boundary
  R-008 fake execution normalization: 86a5dc9 fix(workflow): normalize fake execution status reporting
  R-009 retrieval authority boundary: 547ba22 fix(retrieval): enforce R-009 evidence authority boundary
  R-009 hardening follow-up record: 09625b0 docs(repair): record R-009 authority hardening follow-ups
  R-010 single collection resolver: 3fc1ef5 fix(retrieval): resolve controlled collection centrally
  R-011 identifier and hash field mapping: fe5c5f3 fix(retrieval): enforce identity field mapping
  R-011 artifact source tracking boundary: fbdca70 fix(git): track mod_agent artifact modules
  R-009 hardening authority/tokenization: 12787ba fix(retrieval): harden evidence authority and shared tokenization
current R-012 status: completed; focused and affected tests passed
current R-013 status: completed; focused and affected tests passed
current R-009-HARDENING-001 status: completed; focused and affected tests passed
current Review Repair Queue refresh status: completed; control-doc refresh only
current Q-020 status: completed; focused and affected tests passed
current Q-021 status: completed; focused and affected tests passed
current Q-022 status: completed; focused and affected tests passed
current V1-AUDIT-001 status: completed; focused and affected tests passed
current V1-AUDIT-002 status: completed; focused and affected tests passed
current V1-AUDIT-003 status: completed; focused and affected tests passed
current V1-AUDIT-004 status: completed; focused and affected tests passed
current V1-AUDIT-005 status: completed; documentation consistency checks passed
current MISS-022 status: completed; focused and affected tests passed
commit policy: manual commit after focused tests and status review
```

## Unresolved R Gates

| Task | Source Finding | Status | Blocking Reason |
| --- | --- | --- | --- |
| None | post R-009-HARDENING-001 refresh | clear | R-001 through R-013 and R-009-HARDENING-001 are completed; remaining open missing rows are future task groups, not active Review Repair Queue blockers |

## Test Health

```text
latest focused R-005 suite:
  python -m pytest tests/unit/test_artifact_store.py tests/unit/test_artifact_contract.py -q
  result: 27 passed

latest affected workflow/repair/checkpoint/dashboard suite:
  python -m pytest tests/unit/test_workflow_graph.py tests/unit/test_repair_loop.py tests/unit/test_repair_checkpoint_smoke.py tests/unit/test_workflow_checkpointing.py tests/unit/test_dashboard_projection.py -q
  result: 25 passed

latest focused R-006 suite:
  .\.venv\Scripts\python.exe -m pytest tests/unit/test_permissions.py tests/unit/test_dashboard_data_service.py -q
  result: 11 passed

latest focused R-007 suite:
  .\.venv\Scripts\python.exe -m pytest tests/unit/test_trace_context.py tests/unit/test_trace_service.py tests/unit/test_permissions.py tests/unit/test_dashboard_data_service.py -q
  result: 56 passed

latest dashboard e2e smoke:
  .\.venv\Scripts\python.exe -m pytest tests/e2e/test_dashboard_smoke.py -q
  result: 6 passed

latest focused R-008 suite:
  .\.venv\Scripts\python.exe -m pytest tests/unit/test_workflow_graph.py tests/unit/test_build_adapter.py tests/unit/test_artifact_contract.py -q
  result: 41 passed

latest affected R-008 suite:
  .\.venv\Scripts\python.exe -m pytest tests/unit/test_repair_loop.py tests/unit/test_repair_checkpoint_smoke.py tests/unit/test_dashboard_data_service.py tests/e2e/test_dashboard_smoke.py -q
  result: 17 passed

latest focused R-009 suite:
  .\.venv\Scripts\python.exe -m pytest tests/unit/test_evidence_retrieval.py tests/unit/test_stub_nodes.py tests/unit/test_sparse_encoder.py tests/unit/test_query_processor.py tests/unit/test_planning.py tests/unit/test_artifact_contract.py tests/unit/test_artifact_store.py tests/unit/test_proposal_review.py tests/unit/test_repair_checkpoint_smoke.py -q --tb=short --disable-warnings
  result: 123 passed, 1 warning

latest affected R-009 workflow/dashboard suite:
  .\.venv\Scripts\python.exe -m pytest tests/unit/test_workflow_graph.py tests/unit/test_repair_loop.py tests/unit/test_repair_checkpoint_smoke.py tests/unit/test_dashboard_data_service.py -q --tb=short --disable-warnings
  result: 21 passed

latest affected R-009 retrieval integration suite:
  .\.venv\Scripts\python.exe -m pytest tests/integration/test_hybrid_search.py tests/integration/test_query_trace.py -q --tb=short --disable-warnings
  result: 43 passed, 1 warning

latest focused R-010 suite:
  .\.venv\Scripts\python.exe -m pytest tests/unit/test_collection_resolver.py tests/unit/test_evidence_retrieval.py tests/unit/test_workflow_graph.py -q --tb=short --disable-warnings
  result: 23 passed

latest affected R-010 suite:
  .\.venv\Scripts\python.exe -m pytest tests/unit/test_repair_loop.py tests/unit/test_knowledge_base.py tests/unit/test_config_loading.py -q --tb=short --disable-warnings
  result: 12 passed

latest focused and affected R-011 suite:
  .\.venv\Scripts\python.exe -m pytest tests/unit/test_artifact_contract.py tests/unit/test_artifact_store.py tests/unit/test_knowledge_base.py tests/unit/test_evidence_retrieval.py tests/unit/test_workflow_graph.py tests/unit/test_repair_loop.py tests/unit/test_planning.py tests/unit/test_proposal_review.py -q --tb=short --disable-warnings
  result: 77 passed

latest focused and affected R-012 suite:
  .\.venv\Scripts\python.exe -m pytest tests/unit/test_workflow_graph.py tests/unit/test_repair_loop.py tests/unit/test_repair_checkpoint_smoke.py tests/unit/test_artifact_contract.py tests/unit/test_artifact_store.py -q --tb=short --disable-warnings
  result: 48 passed

latest focused R-013 projection suite:
  python -m pytest tests/unit/test_dashboard_projection.py -q --tb=short
  result: 6 passed

latest affected R-013 safety/workflow suite:
  python -m pytest tests/unit/test_artifact_contract.py tests/unit/test_dashboard_data_service.py tests/unit/test_trace_service.py tests/unit/test_build_adapter.py tests/unit/test_workflow_graph.py tests/unit/test_repair_loop.py -q --tb=short
  result: 68 passed

latest R-013 dashboard smoke:
  .venv\Scripts\python.exe -m pytest tests/e2e/test_dashboard_smoke.py -q --tb=short
  result: 6 passed

latest focused R-009-HARDENING-001 suite:
  .venv\Scripts\python.exe -m pytest tests/unit/test_planning.py tests/unit/test_evidence_retrieval.py tests/unit/test_dashboard_projection.py tests/unit/test_query_processor.py tests/unit/test_sparse_encoder.py -q --tb=short
  result: 93 passed, 1 warning

latest affected R-009-HARDENING-001 suite:
  .venv\Scripts\python.exe -m pytest tests/unit/test_artifact_contract.py tests/unit/test_workflow_graph.py tests/unit/test_repair_loop.py tests/unit/test_dashboard_data_service.py tests/unit/test_build_adapter.py tests/unit/test_trace_service.py -q --tb=short
  result: 68 passed

latest R-009-HARDENING-001 dashboard smoke:
  .venv\Scripts\python.exe -m pytest tests/e2e/test_dashboard_smoke.py -q --tb=short
  result: 6 passed

latest focused Q-020 suite:
  .venv\Scripts\python.exe -m pytest tests/unit/test_performance_budget.py tests/unit/test_config_loading.py tests/unit/test_artifact_contract.py -q --tb=short
  result: 31 passed

latest affected Q-020 suite:
  .venv\Scripts\python.exe -m pytest tests/unit/test_dashboard_config.py tests/unit/test_artifact_store.py tests/unit/test_dashboard_projection.py tests/e2e/test_dashboard_smoke.py -q --tb=short
  result: 35 passed

latest focused Q-021 suite:
  .venv\Scripts\python.exe -m pytest tests/unit/test_controlled_agent_mcp_tools.py -q --tb=short
  result: 6 passed

latest affected Q-021 artifact/dashboard/performance suite:
  .venv\Scripts\python.exe -m pytest tests/unit/test_artifact_contract.py tests/unit/test_dashboard_projection.py tests/unit/test_performance_budget.py -q --tb=short
  result: 33 passed

latest affected Q-021 legacy MCP suite:
  .venv\Scripts\python.exe -m pytest tests/integration/test_mcp_server.py tests/e2e/test_mcp_client.py -q --tb=short
  result: 13 passed, 4 warnings

latest focused and affected Q-022 retrieval/config/artifact/dashboard/performance/knowledge suite:
  .venv\Scripts\python.exe -m pytest tests/unit/test_evidence_retrieval.py tests/unit/test_config_loading.py tests/unit/test_artifact_contract.py tests/unit/test_dashboard_projection.py tests/unit/test_performance_budget.py tests/unit/test_knowledge_base.py tests/unit/test_bm25_indexer_roundtrip.py tests/unit/test_collection_resolver.py -q --tb=short
  result: 88 passed

latest affected Q-022 workflow/planning/proposal suite:
  .venv\Scripts\python.exe -m pytest tests/unit/test_workflow_graph.py tests/unit/test_planning.py tests/unit/test_proposal_review.py -q --tb=short
  result: 32 passed

known broader-suite gaps:
  LEGACY-TEST-001 is queued for full-suite dependency parity, external-service gates, Windows Chroma cleanup, RAGAS compatibility, and historical legacy assertions.
  R-009 absorbed only evidence_retrieval, stub_nodes, sparse_encoder/query tokenization, and planning/artifact contract changes directly tied to retrieval authority or evidence boundary behavior.
  R-009-HARDENING-001 is completed for authority default hardening, raw evidence-pack provenance validation, dashboard authority display semantics, and shared sparse/query tokenization cleanup.
  streamlit is installed in .venv to satisfy dashboard e2e dependency
```

## Active Risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Spec is large enough to cause execution drift | High | Always use queue + state + small-loop audit |
| Spec detail coverage can be lost across many small loops | High | Use `docs/SPEC_COVERAGE_MATRIX.md` before selecting and closing tasks |
| Imported RAG skeleton can dominate product direction | High | Treat RAG as Evidence Knowledge Subsystem only |
| GTFO details can leak into generic platform | Medium | Put game-specific behavior behind domain adapters |
| Dense/vector/multimodal features can block V1 | Medium | BM25/symbol/deterministic first; Q-022 is contract-only dense provider work with real embedding/vector retrieval deferred |
| Claims can outrun implemented evidence | High | Completion levels require tests and artifacts |
| Fake/local execution artifacts may be mistaken for real build/runtime success | High | Every artifact must include `execution_mode=fake|local|supplied_output|real`; reports must not claim real gameplay success from fake/local evidence |
| External review found P0/P1 structural issues after several Q loops | High | Review Repair Queue is completed through R-009-HARDENING-001; any new P0/P1 review finding still supersedes ordinary Q feature work |
| PROJECT_STATE may overclaim because it is generated by the agent itself | High | Verify claims against git status, code, tests, artifacts, and command output |
| Queue may become RAG-first despite capability-first spec direction | High | Prioritize runnable controlled loop and active repair gates before deeper optional Knowledge Hub expansion |
| R-005 artifact integrity remains PASS_WITH_RISK | Medium | Track transitive freshness, read-time envelope content hash recomputation, immutable revision files, and audit/report-only allow_stale_upstreams policy as future artifact integrity / immutable revision / R-012 follow-up gaps |
| Retrieval authority and tokenizer changes can regress planning safety or ranking behavior | Medium | R-009-HARDENING-001 completed the authority default, deterministic authority grant, raw dict provenance, dashboard authority display, and shared tokenizer work; future retrieval changes must keep focused sparse/query and planning tests in scope |

## Latest Loop Summary

```text
task: Q-022
status: completed; focused and affected tests passed
files_changed:
  src/mod_agent/evidence/dense.py
  src/mod_agent/evidence/__init__.py
  src/mod_agent/evidence/retriever.py
  src/mod_agent/evidence/models.py
  src/mod_agent/artifacts/registry.py
  src/mod_agent/knowledge/__init__.py
  src/mod_agent/knowledge/models.py
  src/core/settings.py
  config/settings.yaml
  tests/unit/test_evidence_retrieval.py
  tests/unit/test_config_loading.py
  docs/PROJECT_STATE.md
  docs/IMPLEMENTATION_QUEUE.md
  docs/SPEC_COVERAGE_MATRIX.md
behavior:
  Added a disabled-by-default dense retrieval provider contract with DisabledDenseRetrievalProvider and FakeDenseRetrievalProvider.
  This is not production dense retrieval: FakeDenseRetrievalProvider returns configured chunk-id scores and no real embedding/vector database query is implemented.
  V1-AUDIT-001 now gates fake dense provider settings behind load_settings(..., allow_test_providers=True), so normal runtime settings cannot silently enable fake dense retrieval.
  Added a KnowledgeChunkRecord to ChunkRecord projection so persisted chunks expose text_for_embedding without changing the database schema.
  Dense evidence remains legacy_rag_auxiliary and cannot approve can_generate_patch without BM25/symbol deterministic evidence.
  Dense budget/cost accounting is serialized into evidence_pack budget_summary, and fake dense retrieval exposes retrieval.dense_started and retrieval.dense_finished trace refs.
  config/settings.yaml explicitly keeps retrieval.dense_enabled false and retrieval.dense_provider disabled.
verification:
  focused and affected Q-022 retrieval/config/artifact/dashboard/performance/knowledge tests: 88 passed
  affected Q-022 workflow/planning/proposal tests: 32 passed
next_recommended_task: V1-AUDIT-001 completed; continue to V1-AUDIT-002
```

## V1-AUDIT-001: V1 Acceptance Boundary And Fake Dense Provider Gate

```text
status: completed
branch: codex/v1-acceptance-audit
spec_refs:
  DEV_SPEC.md 48.9
  DEV_SPEC.md 49.1.4
  DEV_SPEC.md 49.7
  DEV_SPEC.md 50.4
  DEV_SPEC.md 50.6
  DEV_SPEC.md 50.9
files:
  src/core/settings.py
  tests/unit/test_config_loading.py
  docs/V1_ACCEPTANCE_AUDIT.md
  docs/PROJECT_STATE.md
  docs/IMPLEMENTATION_QUEUE.md
  docs/SPEC_COVERAGE_MATRIX.md
behavior:
  load_settings() and Settings.from_dict() reject retrieval.dense_provider=fake by default.
  Tests that need FakeDenseRetrievalProvider through settings must call allow_test_providers=True.
  The V1 audit records current status as implemented_with_known_gaps, not production-complete.
  Real dense retrieval remains deferred; Q-022 remains a disabled-by-default contract task only.
verification:
  focused V1-AUDIT-001 retrieval/config tests: 19 passed
  affected V1-AUDIT-001 config/retrieval/budget/dashboard/MCP/artifact tests: 59 passed
next_recommended_task: V1-AUDIT-002 acceptance-contract workflow linkage closure
```

## V1-AUDIT-002: Acceptance Contract Runtime Eval Linkage

```text
status: completed
branch: codex/v1-acceptance-audit
commit: b94b298 fix(workflow): carry acceptance contract through runtime eval
spec_refs:
  DEV_SPEC.md 49.1.4
  DEV_SPEC.md 50.9.3
files:
  src/mod_agent/runtime/evidence.py
  src/mod_agent/workflow/graph.py
  src/mod_agent/workflow/transitions.py
  src/mod_agent/artifacts/registry.py
  src/observability/evaluation/eval_runner.py
  tests/unit/test_workflow_graph.py
  tests/unit/test_repair_loop.py
  tests/unit/test_artifact_contract.py
behavior:
  FeatureSpec acceptance_criteria and runtime_verification_plan are copied into runtime_evidence.acceptance_contract.
  eval_report records the same acceptance_contract and input_acceptance_verified.
  route_after_runtime_evidence routes only acceptance_verified=True to evaluation; missing, false, and inconclusive acceptance route to repair.
  Fake runtime fixtures can satisfy the acceptance contract for controlled workflow tests, but still record real_runtime_performed=False and claims_real_runtime_success=False.
  Workflow summary still records claims_real_mod_success=False and final_status=inconclusive for the fake/local path.
verification:
  closure route and artifact-contract scripts passed
  workflow/planning/runtime/artifact affected tests: 71 passed
  eval tests: 42 passed
  git diff --check: passed
remaining:
  Real/manual/supplied runtime acceptance E2E evidence remains unverified.
  Do not claim V1 accepted until non-fake runtime acceptance evidence is tested.
next_recommended_task: V1-AUDIT-003 real/manual/supplied runtime acceptance evidence path
```

## V1-AUDIT-003: Manual And Supplied Runtime Acceptance Evidence

```text
status: completed
branch: codex/v1-acceptance-audit
commit: 5aad3be fix(runtime): bind acceptance evidence to contract
spec_refs:
  DEV_SPEC.md 49.1.4
  DEV_SPEC.md 50.9.3
files:
  src/mod_agent/runtime/evidence.py
  tests/unit/test_runtime_evidence.py
behavior:
  Manual and supplied runtime evidence can verify acceptance only when evidence_items.supports_acceptance covers every acceptance_criteria entry in the current acceptance_contract.
  Verified manual/supplied evidence with unrelated supports_acceptance now raises RuntimeEvidenceError.
  Unverified supplied evidence preserves acceptance_contract while keeping acceptance_verified=False.
  Fake runtime fixtures remain separate and still do not claim real runtime execution.
verification:
  focused runtime/routing/artifact tests: 25 passed
  affected runtime/workflow/artifact tests: 74 passed
  eval tests: 42 passed
  git diff --check: passed
remaining:
  Automated real runtime execution and real runtime evidence collection remain unimplemented.
  Do not claim V1 accepted until the real runtime branch is either tested end-to-end or explicitly scoped out of V1 acceptance.
next_recommended_task: V1-AUDIT-004 real runtime branch E2E boundary decision
```

## V1-AUDIT-004: Real Runtime Branch Acceptance Boundary

```text
status: completed
branch: codex/v1-acceptance-audit
commit: f6c83cf fix(workflow): block v1 acceptance without real runtime evidence
spec_refs:
  DEV_SPEC.md 49.1.4
  DEV_SPEC.md 50.9.3
files:
  src/mod_agent/workflow/graph.py
  src/mod_agent/artifacts/registry.py
  tests/unit/test_workflow_graph.py
  tests/unit/test_artifact_contract.py
  tests/unit/test_dashboard_projection.py
behavior:
  Fake/local eval_report and workflow_summary now include v1_acceptance_status and v1_acceptance_blockers.
  The default fake/local path records requested_behavior_status=verified only for the controlled contract fixture, while v1_acceptance_status remains blocked.
  Missing real build success evidence records REAL_BUILD_EVIDENCE_MISSING.
  Missing real runtime execution evidence records REAL_RUNTIME_EVIDENCE_MISSING.
verification:
  focused workflow/artifact/dashboard tests: 34 passed
  affected runtime/workflow/repair/eval/artifact/dashboard tests: 105 passed
remaining:
  Automated real runtime execution and real runtime evidence collection remain unimplemented.
  Do not claim real V1 runtime acceptance from fake/local, manual, or supplied fixture-style evidence alone.
next_recommended_task: V1-AUDIT-005 final V1 acceptance verdict and queue handoff
```

## V1-AUDIT-005: Final V1 Acceptance Verdict And Queue Handoff

```text
status: completed
branch: codex/v1-acceptance-audit
commit: 0c78c81 docs(v1): record final acceptance audit verdict
files:
  docs/V1_ACCEPTANCE_AUDIT.md
  docs/IMPLEMENTATION_QUEUE.md
  docs/PROJECT_STATE.md
  docs/SPEC_COVERAGE_MATRIX.md
verdict:
  V1 contract path is accepted with known gaps.
  Real runtime evidence branch was not accepted at V1-AUDIT-005 time; it is now closed by MISS-022.
  The project must not claim production runtime automation until MISS-026 is closed by implementation and tests.
architecture_note:
  v1_acceptance_status and v1_acceptance_blockers are V1 audit boundary fields.
  They are not generalized in this audit.
handoff:
  MISS-022 completed the injectable real runtime evidence branch after this audit.
  If the next goal is production runtime automation, continue MISS-026 after MISS-026A with real game launch, persistent log collection, and screenshot capture.
  If the next goal is feature expansion, select the next task from docs/SPEC_COVERAGE_MATRIX.md open gaps.
verification:
  documentation consistency checks: passed
  git diff --check: passed
next_recommended_task: continue MISS-026 if real game process launch, persistent log collection, and screenshot capture are the goal
```

## MISS-022: Real Runtime Evidence Branch

```text
status: completed
branch: codex/v1-acceptance-audit
commit: 5529e1f fix(workflow): add real runtime evidence branch
files:
  src/mod_agent/runtime/evidence.py
  src/mod_agent/runtime/__init__.py
  src/mod_agent/workflow/graph.py
  src/mod_agent/artifacts/registry.py
  tests/unit/test_runtime_evidence.py
  tests/unit/test_workflow_graph.py
  tests/unit/test_artifact_contract.py
  tests/unit/test_dashboard_projection.py
behavior:
  Runtime evidence now has build_real_runtime_evidence_payload for explicitly executed runtime probe evidence.
  build_graph now accepts runtime_evidence_factory so tests and future adapters can provide non-fake runtime evidence.
  The graph has a tested path where local build evidence and real runtime evidence remove v1_acceptance_blockers and produce v1_acceptance_status=accepted.
  V1 accepted now explicitly requires runtime execution_mode=real, real_runtime_performed=True, claims_real_runtime_success=True, and acceptance_verified=True.
  runtime_evidence and manual_evidence contracts now require real_runtime_performed.
claim_boundary:
  This closes the MISS-022 contract/E2E gap outside fake/manual/supplied fixture-style evidence.
  It does not implement a production game process launcher, persistent runtime log collector, or screenshot capture pipeline.
verification:
  focused runtime/workflow/artifact tests: 36 passed
  affected runtime/workflow/repair/eval/artifact/dashboard tests: 97 passed
  git diff --check: passed
remaining:
  Real game process launch, persistent log collection, and screenshot capture remain open as MISS-026.
next_recommended_task: continue MISS-026 if real game process launch, persistent log collection, and screenshot capture are the goal
```

## MISS-026A Local Runtime Probe Collector

```text
status: implemented
branch: codex/miss-026-runtime-collector
files:
  src/mod_agent/runtime/probe.py
  src/mod_agent/runtime/__init__.py
  tests/unit/test_runtime_probe.py
  tests/unit/test_workflow_graph.py
behavior:
  RuntimeProbeRunner can launch an explicitly approved local subprocess runtime probe.
  The probe collects stdout and stderr, checks startup markers, maps acceptance_criteria to configured log markers, and builds a runtime_evidence payload through build_real_runtime_evidence_payload.
  make_runtime_probe_evidence_factory exposes the runner as a graph-compatible runtime_evidence_factory without changing the default fake graph path.
claim_boundary:
  This proves a controlled local subprocess can produce runtime_evidence that the workflow consumes.
  It does not launch the real game process, manage a persistent runtime log file, capture screenshots, or prove real mod behavior inside GTFO.
verification:
  focused runtime probe/runtime evidence/workflow tests: 23 passed
  affected runtime/workflow/repair/artifact/dashboard tests: 51 passed
  screenshot-specific unit test file: not present in tests/unit
remaining:
  Real game process launcher, persistent log collection, and screenshot capture remain open as MISS-026.
next_recommended_task: continue MISS-026 if real game process launch, persistent log collection, and screenshot capture are the goal
```

## Next Execution Rule

Use `docs/IMPLEMENTATION_QUEUE.md`.
Use `docs/SPEC_COVERAGE_MATRIX.md` to confirm which requirement rows a task changes.
If the Review Repair Queue is active, select the first ready R task before Q feature work.
Current Review Repair Queue refresh is clear; continue with Q-022 unless a new P0/P1 review finding is added.
Historical loop details live in `docs/audits/LOOP_HISTORY.md`.
