# Project State

This file is the active state summary for the Controlled Mod Agent Platform.
Historical loop details are archived in `docs/audits/LOOP_HISTORY.md`.

Last updated: 2026-07-03

## Current Queue

```text
current_queue: Review Repair Queue
last_completed: R-012 Checkpoint Resume Graph Binding
next_recommended_task: R-013 Mod-Agent Dashboard Projection
ordinary_queue_status: Q-020 and later tasks remain queued but blocked behind active Review Repair Queue
```

## Current Baseline

```text
branch: repair/r012-checkpoint-resume-graph-binding
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
current R-012 status: completed; focused and affected tests passed
commit policy: manual commit after focused tests and status review
```

## Unresolved R Gates

| Task | Source Finding | Status | Blocking Reason |
| --- | --- | --- | --- |
| R-013 | P1-006 | queued | dashboard needs mod_agent workflow/artifact/proposal/build/runtime/repair projections |

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

known broader-suite gaps:
  LEGACY-TEST-001 is queued for full-suite dependency parity, external-service gates, Windows Chroma cleanup, RAGAS compatibility, and historical legacy assertions.
  R-009 absorbed only evidence_retrieval, stub_nodes, sparse_encoder/query tokenization, and planning/artifact contract changes directly tied to retrieval authority or evidence boundary behavior.
  R-009-HARDENING-001 is queued for authority default hardening, raw evidence-pack provenance validation, dashboard authority display semantics, and shared sparse/query tokenization cleanup.
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
task: R-012 Checkpoint Resume Graph Binding
status: completed; focused and affected tests passed
files_changed:
  src/mod_agent/artifacts/registry.py
  src/mod_agent/workflow/checkpointing.py
  src/mod_agent/workflow/interrupts.py
  tests/unit/test_artifact_contract.py
  tests/unit/test_repair_checkpoint_smoke.py
  docs/IMPLEMENTATION_QUEUE.md
  docs/PROJECT_STATE.md
behavior:
  workflow_checkpoint artifacts bind resume attempts to patch_proposal ref/hash, proposal_review ref/hash, and a sha256 diff_hash derived from patch_proposal.diff_intent.
  ResumeValidator rejects missing or mismatched diff_hash when the checkpoint carries a bound diff_hash.
  Accepted resume decisions expose restored_state from checkpoint state_snapshot so a resume cannot silently skip the reviewed graph state.
  Changed patch_proposal upstream artifacts are rejected through stale checkpoint freshness checks.
verification:
  focused and affected R-012 tests: 48 passed
next_recommended_task: R-013 Mod-Agent Dashboard Projection
```

## Next Execution Rule

Use `docs/IMPLEMENTATION_QUEUE.md`.
Use `docs/SPEC_COVERAGE_MATRIX.md` to confirm which requirement rows a task changes.
If the Review Repair Queue is active, select the first ready R task before Q feature work.
Historical loop details live in `docs/audits/LOOP_HISTORY.md`.
