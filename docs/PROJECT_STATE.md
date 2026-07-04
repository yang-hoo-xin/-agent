# Project State

This file is the active state summary for the Controlled Mod Agent Platform.
Historical loop details are archived in `docs/audits/LOOP_HISTORY.md`.

Last updated: 2026-07-04

## Current Queue

```text
current_queue: Review Repair Queue
last_completed: R-009-HARDENING-001
next_recommended_task: review remaining Review Repair Queue hardening items before Q-020
ordinary_queue_status: Q-020 and later tasks remain queued but blocked behind active Review Repair Queue
```

## Current Baseline

```text
branch: codex/r009-hardening-001
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
commit policy: manual commit after focused tests and status review
```

## Unresolved R Gates

| Task | Source Finding | Status | Blocking Reason |
| --- | --- | --- | --- |
| Review Repair Queue refresh | post R-009-HARDENING-001 | queued | confirm remaining R hardening items before allowing Q-020 |

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
| Dense/vector/multimodal features can block V1 | Medium | BM25/symbol/deterministic first; optional providers later |
| Claims can outrun implemented evidence | High | Completion levels require tests and artifacts |
| Fake/local execution artifacts may be mistaken for real build/runtime success | High | Every artifact must include `execution_mode=fake|local|supplied_output|real`; reports must not claim real gameplay success from fake/local evidence |
| External review found P0/P1 structural issues after several Q loops | High | Use the active Review Repair Queue before Q-020; each R task must pass tests, diff audit, docs update, git decision, and stop |
| PROJECT_STATE may overclaim because it is generated by the agent itself | High | Verify claims against git status, code, tests, artifacts, and command output |
| Queue may become RAG-first despite capability-first spec direction | High | Prioritize runnable controlled loop and active repair gates before deeper optional Knowledge Hub expansion |
| R-005 artifact integrity remains PASS_WITH_RISK | Medium | Track transitive freshness, read-time envelope content hash recomputation, immutable revision files, and audit/report-only allow_stale_upstreams policy as future artifact integrity / immutable revision / R-012 follow-up gaps |
| R-009 authority boundary needs hardening beyond the completed behavior fix | Medium | Track R-009-HARDENING-001: default EvidenceItem authority should become auxiliary, deterministic retrievers should explicitly grant authority, raw dict evidence packs need provenance validation, dashboard authority display must pair authority with readiness/can_generate_patch/authoritative_for_patch, and sparse/query tokenization should share one implementation |

## Latest Loop Summary

```text
task: R-009-HARDENING-001
status: completed; focused and affected tests passed
files_changed:
  src/core/query_engine/tokenization.py
  src/core/query_engine/__init__.py
  src/core/query_engine/query_processor.py
  src/ingestion/embedding/sparse_encoder.py
  src/mod_agent/evidence/models.py
  src/mod_agent/evidence/readiness.py
  src/mod_agent/evidence/retriever.py
  src/mod_agent/planning/implementation_plan.py
  src/mod_agent/dashboard/projections.py
  src/observability/dashboard/pages/mod_agent_dashboard.py
  tests/unit/test_evidence_retrieval.py
  tests/unit/test_planning.py
  tests/unit/test_dashboard_projection.py
  tests/unit/test_query_processor.py
  tests/unit/test_sparse_encoder.py
behavior:
  EvidenceItem now defaults to legacy_rag_auxiliary, while DeterministicEvidenceRetriever explicitly assigns mod_agent_deterministic authority.
  ImplementationPlanner blocks authoritative raw dict evidence packs that lack identity_schema_version, identity_field_mapping, explicit item authority, or deterministic item provenance metadata; auxiliary context items are ignored for planning.
  Controlled-agent dashboard projection now shows evidence readiness, can_generate_patch, authority, authoritative_for_patch, and projection_status together.
  QueryProcessor and SparseEncoder now share tokenize_retrieval_text for code-like retrieval tokenization; jieba remains a mandatory dependency and no silent fallback is used.
verification:
  focused R-009-HARDENING-001 tests: 93 passed, 1 warning
  affected R-009-HARDENING-001 tests: 68 passed
  dashboard smoke: 6 passed
next_recommended_task: review remaining Review Repair Queue hardening items before Q-020
```

## Next Execution Rule

Use `docs/IMPLEMENTATION_QUEUE.md`.
Use `docs/SPEC_COVERAGE_MATRIX.md` to confirm which requirement rows a task changes.
If the Review Repair Queue is active, select the first ready R task before Q feature work.
Historical loop details live in `docs/audits/LOOP_HISTORY.md`.
