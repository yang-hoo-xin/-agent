# Loop History

This archive preserves historical loop details moved out of the active control documents.

Active execution should start from `docs/PROJECT_STATE.md` and `docs/IMPLEMENTATION_QUEUE.md`.


## Archived PROJECT_STATE.md Before Sanitation


# Project State

This file is the durable progress ledger for the Evidence-Grounded Controlled Code Generation Agent Platform.

Last updated: 2026-06-30

## Current Baseline

Repository:

```text
branch: main
remote: https://github.com/yang-hoo-xin/-agent.git
baseline commit: 914f16e chore: establish controlled mod agent baseline
baseline tag: baseline-controlled-agent-v0
local tracking: main...origin/main
```

## 2026-07-13 Active Control Document Cleanup

Status: archived from active control documents

The completed, frozen, review, and prior-direction material that had accumulated
in `docs/PROJECT_STATE.md` and `docs/IMPLEMENTATION_QUEUE.md` is historical. It
must not participate in current task selection merely because it once appeared
under an active-document heading.

Archived record classes include:

- V1 acceptance, V1-to-V2 transition, Q-series, R-series, STATE, E2E,
  artifact-integrity, runtime-boundary, and retrieval-validation closures;
- `GTFO-VSLICE-001A/B/C`, `V2-PROP-001A`, `V2-EVAL-001`,
  `V2-RET-DIRECTIONAL-001`, and `V2-CODEGEN-REAL-001` completion evidence;
- prior review findings, focused-test counts, frozen/formal validation tracks,
  and superseded `next_recommended_task` values;
- former Dense/RAG, Dashboard, MCP, multimodal, production storage, and runtime
  expansion directions that have no currently satisfied product trigger.

The detailed records elsewhere in this file and the repository's Git history
remain the audit source. Their removal from the active state and
queue is a control-plane cleanup, not a deletion of evidence or a reversal of
implemented code.

Current effect:

- active authority order is defined only by `AGENTS.md` section 2;
- `docs/PROJECT_STATE.md` contains current verified boundaries and no inherited
  next-task recommendation;
- `docs/IMPLEMENTATION_QUEUE.md` contains only active or conditional work;
- formal retrieval, Dense/RAG, Dashboard, MCP, runtime, and storage expansion
  remain conditional until an explicit trigger is recorded.

Remote push status:

```text
baseline branch push: previously succeeded via `git push -u origin main`
baseline tag push: previously succeeded via `git push origin baseline-controlled-agent-v0`
origin/main commit observed locally: 914f16e
current remote re-verification: verified during Q-001
required future verification: repeat `git ls-remote --heads origin main` and `git ls-remote --tags origin baseline-controlled-agent-v0` before release/tag claims
```

Q-001 remote verification:

```text
verified_at: 2026-06-28
origin/main: 914f16e9da82aa90e6433cbf80d12683d36ea67b
origin tag baseline-controlled-agent-v0: 914f16e9da82aa90e6433cbf80d12683d36ea67b
verified_by:
  git ls-remote --heads origin main
  git ls-remote --tags origin baseline-controlled-agent-v0
```

Current uncommitted changes:

```text
M  .agents/skills/auto-coder/SKILL.md
M  .gitignore
M  DEV_SPEC.md
M  config/settings.yaml
M  src/mod_agent/__init__.py
M  src/mod_agent/evidence/models.py
M  src/mod_agent/evidence/readiness.py
M  src/mod_agent/evidence/retriever.py
M  src/mod_agent/git/__init__.py
M  src/mod_agent/git/repository.py
M  src/mod_agent/knowledge/__init__.py
M  src/mod_agent/knowledge/database.py
M  src/mod_agent/knowledge/models.py
M  src/mod_agent/knowledge/source_registry.py
M  src/mod_agent/knowledge/symbol_indexer.py
M  src/mod_agent/proposal/reviewer.py
M  src/mod_agent/workflow/__init__.py
M  src/mod_agent/workflow/graph.py
M  src/mod_agent/workflow/nodes.py
M  src/mod_agent/workflow/transitions.py
M  tests/unit/test_artifact_contract.py
M  tests/unit/test_artifact_store.py
M  tests/unit/test_evidence_retrieval.py
M  tests/unit/test_git_repository.py
M  tests/unit/test_knowledge_base.py
M  tests/unit/test_stub_nodes.py
M  tests/unit/test_workflow_graph.py
?? docs/EXECUTION_CONTROL_GUIDE.md
?? docs/IMPLEMENTATION_QUEUE.md
?? docs/PROJECT_STATE.md
?? docs/SPEC_COVERAGE_MATRIX.md
?? src/mod_agent/artifacts/
?? src/mod_agent/build/
?? src/mod_agent/dashboard/
?? src/mod_agent/domain/
?? src/mod_agent/evaluation/
?? src/mod_agent/git/workflow_binding.py
?? src/mod_agent/mcp/
?? src/mod_agent/repair/
?? src/mod_agent/runtime/
?? src/mod_agent/workflow/checkpointing.py
?? src/mod_agent/workflow/interrupts.py
?? src/mod_agent/knowledge/bm25_indexer.py
?? src/mod_agent/knowledge/source_discovery.py
?? tests/fixtures/retrieval/
?? tests/unit/test_build_adapter.py
?? tests/unit/test_dashboard_projection.py
?? tests/unit/test_domain_adapter.py
?? tests/unit/test_mcp_async_jobs.py
?? tests/unit/test_repair_loop.py
?? tests/unit/test_repair_checkpoint_smoke.py
?? tests/unit/test_retrieval_regression.py
?? tests/unit/test_runtime_evidence.py
?? tests/unit/test_workflow_checkpointing.py
```

Uncommitted change meaning:

```text
.agents/skills/auto-coder/SKILL.md:
  governance consistency update. The skill now uses DEV_SPEC plus the control
  documents for task selection, spec coverage, progress recovery, and reporting.
  Generated references are navigation aids only, not the execution queue.

DEV_SPEC.md:
  spec updates for RAG text/metadata/index/timing, 50k LOC target,
  targeting/black-box audit, multimodal design, testing, performance,
  MCP async, concurrency, and index design.

.gitignore:
  Q-013 anchors runtime output directory ignore rules to the repository root,
  so src/mod_agent/artifacts and src/mod_agent/build are visible to git status.

config/settings.yaml:
  Q-013 adds build.allow_real_execution, build.default_timeout_seconds,
  and build.profiles.

docs/EXECUTION_CONTROL_GUIDE.md:
  new execution protocol for small-loop planning, audit, conflict handling,
  completion levels, and context recovery.

docs/IMPLEMENTATION_QUEUE.md:
  new rolling queue. It must be refreshed after Q-001 because the first draft
  is biased toward Knowledge/Retrieval tasks.

docs/PROJECT_STATE.md:
  new/updated progress ledger. All coverage levels are estimates until Q-001
  verifies them against code, tests, artifacts, and git state.

docs/SPEC_COVERAGE_MATRIX.md:
  new requirement-level coverage ledger. It records DEV_SPEC details, current
  status, queue ownership, and high-impact missing requirements.

code files:
  src/mod_agent/evidence/models.py:
    Q-007 EvidencePack fields for retrieval_methods_used, missing_evidence,
    disabled_modes, timing, and trace_refs.
  src/mod_agent/evidence/readiness.py:
    Q-007 missing_evidence derivation from readiness blockers.
  src/mod_agent/evidence/retriever.py:
    Q-007 deterministic retrieval timing and disabled mode reporting.
    Q-005 stable-index BM25 evidence retrieval integration.
    Q-006 stable-index chunk symbol evidence retrieval integration.
  src/mod_agent/evaluation/retrieval_regression.py:
    Q-008 versioned golden query loader, deterministic retrieval regression
    evaluator, evidence-first metrics, false_continue gate, and eval_report payload.
  src/mod_agent/__init__.py:
    Q-012 exports the runtime package at the top package level.
    Q-013 exports the build package at the top package level.
    Q-017 exports the domain package at the top package level.
  src/mod_agent/artifacts/registry.py:
    Q-009 registers the job_status artifact contract for shared artifact-store use.
    Q-012 adds manual_evidence and upgrades runtime_evidence required fields.
    Q-013 upgrades build_result required fields for structured build output.
  src/mod_agent/build/adapter.py:
    Q-013 controlled build profile, adapter, result, diagnostic, and error
    classifier contracts. Local execution is explicit and tests use an injected
    runner.
  src/mod_agent/build/__init__.py:
    Q-013 build adapter public exports.
  src/mod_agent/dashboard/projections.py:
    Q-016 read-only dashboard projections for workflow_trace, artifact_dag,
    EvidencePack timing/bottleneck summary, stale/missing artifacts, and blockers.
  src/mod_agent/dashboard/__init__.py:
    Q-016 dashboard projection public exports.
  src/mod_agent/domain/models.py:
    Q-017 DomainAdapter, DomainProfile, DomainRoute, EvidenceQuery,
    RuntimeProfile, VerificationPlan, DomainReviewPolicy, and
    DomainAdapterRegistry contracts.
  src/mod_agent/domain/gtfo.py:
    Q-017 GTFO / BepInEx / IL2CPP / HarmonyX GameProfile adapter with risk
    taxonomy, forbidden paths, source definitions, build profile, runtime
    profile, and verification strategy.
  src/mod_agent/domain/unsupported.py:
    Q-017 unsupported-domain adapter that permits generic planning but blocks
    game-specific runtime changes.
  src/mod_agent/domain/__init__.py:
    Q-017 domain adapter public exports.
  src/mod_agent/repair/planner.py:
    Q-014 evidence-bound repair plans for build/runtime failures, retry-budget
    blocking, and intent-only repair proposal generation.
  src/mod_agent/repair/__init__.py:
    Q-014 repair loop public exports.
  src/mod_agent/proposal/reviewer.py:
    Q-014 allows proposal review to validate repair proposals against
    repair_plan failure evidence while keeping the same review gate.
    Q-017 accepts an optional domain_policy and blocks unsupported GameProfile
    runtime changes plus domain forbidden/out-of-root paths.
  src/mod_agent/git/__init__.py:
    Q-011 exports workflow Git binding helpers and binding error contracts.
  src/mod_agent/git/repository.py:
    Q-011 git_change_record payload now includes decision_artifacts and
    patch_artifacts with artifact_type, path, and artifact_hash.
  src/mod_agent/git/workflow_binding.py:
    Q-011 selects stage-specific workflow decision artifacts from ModAgentState
    and writes Git change records without creating commits.
  src/mod_agent/mcp/jobs.py:
    Q-009 async job status contract with job_id, job_type, status, timestamps,
    artifact_refs, trace_refs, structured errors, and cancellation behavior.
  src/mod_agent/mcp/tools.py:
    Q-009 safe MCP/API job tool contracts for start_ingestion, get_job_status,
    run_retrieval_eval, and build_mod; start commands return queued job records
    and do not execute long-running work.
  src/mod_agent/runtime/evidence.py:
    Q-012 runtime evidence payload builders for fake, manual, and supplied-output
    evidence. Verified runtime evidence requires startup, gameplay behavior, and
    explicit acceptance evidence.
  src/mod_agent/runtime/__init__.py:
    Q-012 runtime evidence public exports.
  src/mod_agent/knowledge/bm25_indexer.py:
    Q-005 BM25 lexical sparse inverted index builder and query engine.
  src/mod_agent/knowledge/__init__.py:
    Q-002 exports Document, Chunk, ChunkRecord, SourceSpan, and contract helpers.
    Q-004 exports SQLite metadata store record contracts.
    Q-005 exports BM25Indexer and BM25 result contracts.
  src/mod_agent/knowledge/database.py:
    Q-004 SQLite metadata store for collection-scoped sources, documents,
    chunks, and index_versions with stable-version protection.
    Q-005 SQLite bm25_terms and bm25_postings tables plus BM25 read/write helpers.
    Q-006 SQLite symbol_index table plus chunk-bound symbol read/write helpers.
  src/mod_agent/knowledge/models.py:
    Q-002 Document/Chunk/ChunkRecord contracts, raw/canonical/retrieval text
    separation, inherited metadata, and stable hash/id helpers.
    Q-004 KnowledgeSourceSnapshot, KnowledgeDocumentRecord, KnowledgeChunkRecord,
    and IndexVersion contracts.
    Q-005 BM25IndexResult and BM25Hit contracts.
    Q-006 SymbolIndexEntry and SymbolIndexResult contracts.
  src/mod_agent/knowledge/source_discovery.py:
    Q-003 SourceDiscovery and DiscoveredSourceFile contracts for deterministic
    source classification, ignore rules, stable source ids, and content hashes.
  src/mod_agent/knowledge/source_registry.py:
    Q-003 guarded deterministic file walking, default ignored directories/files,
    generated_mods blocking by default, and aggregate source_content_hash.
  src/mod_agent/knowledge/symbol_indexer.py:
    Q-006 chunk-bound symbol_index builder and exact symbol lookup over
    collection_id/index_version.
  src/mod_agent/workflow/graph.py:
    Q-002A controlled fake execution loop after proposal review;
    Q-007 evidence_summary now includes EvidencePack observability fields;
    Q-010 retrieve_evidence finished trace exposes EvidencePack summary.
    Q-012 fake runtime node emits the upgraded runtime evidence contract.
    Q-013 fake build node emits the upgraded build_result contract.
    Q-014 routes failed build/runtime summaries to create_repair_plan and sends
    non-exhausted repair plans back through generate_patch_proposal and review.
    Q-015 accepts LangGraph checkpointer, interrupt_before, and interrupt_after
    parameters while preserving the default graph execution path.
  src/mod_agent/workflow/checkpointing.py:
    Q-015 workflow_checkpoint and resume_report helpers, CheckpointPolicy,
    WorkflowCheckpointStore, stale resume blocking, and double resume rejection.
  src/mod_agent/workflow/interrupts.py:
    Q-015 InterruptRequest, ResumePayload, ResumeDecision, and ResumeValidator
    contracts for human-controlled resume payloads.
  src/mod_agent/workflow/__init__.py:
    Q-015 exports checkpoint and interrupt/resume contracts.
  src/mod_agent/workflow/nodes.py:
    Q-007 stub evidence_pack payload now satisfies the upgraded artifact contract.
    Q-012 stub runtime_evidence payload now satisfies the upgraded runtime contract.
    Q-013 stub build_result payload now satisfies the upgraded build contract.
    Q-014 stub repair_plan payload now satisfies the upgraded repair contract.
  src/mod_agent/workflow/transitions.py:
    Q-014 adds build/runtime failure repair routes and repair retry-budget routing.
  tests/unit/test_artifact_contract.py:
    Q-007 artifact contract assertions for EvidencePack observability fields.
    Q-012 artifact contract assertions for runtime_evidence/manual_evidence
    acceptance fields.
    Q-013 artifact contract assertions for structured build_result fields.
  tests/unit/test_build_adapter.py:
    Q-013 tests for build error taxonomy, supplied output classification,
    local execution gating, injected runner execution, fake build claims, build
    artifact required fields, and BuildProfileRegistry config parsing.
  tests/unit/test_dashboard_projection.py:
    Q-016 tests trace ordering, artifact DAG edges, stale status, missing
    artifacts, EvidencePack timing/bottlenecks, blockers, and read-only behavior.
  tests/unit/test_domain_adapter.py:
    Q-017 tests GTFO GameProfile fields, risk taxonomy, unknown profile
    blocking, forbidden paths, safe roots, and registry extension.
  tests/unit/test_repair_loop.py:
    Q-014 tests failed build repair planning, retry-budget exhaustion,
    repair proposal review re-entry, repair route labels, and graph repair loop blocking.
  tests/unit/test_repair_checkpoint_smoke.py:
    Q-014/Q-015 joint smoke for build failure repair_plan, repair patch proposal,
    proposal_review checkpointing, valid review resume, stale repair artifact
    rejection, and double resume rejection.
  tests/unit/test_workflow_checkpointing.py:
    Q-015 tests artifact contracts, checkpoint state/hash capture, valid resume,
    stale resume blocking, double resume rejection, and graph checkpointer wiring.
  tests/unit/test_artifact_store.py:
    Q-007 test payload compatibility with new evidence_pack contract.
  tests/unit/test_evidence_retrieval.py:
    Q-007 unit tests for EvidencePack timing, disabled modes, methods used,
    and missing evidence.
    Q-005 unit test for BM25 retrieval from the latest stable index version.
    Q-006 unit test for chunk-bound symbol evidence from the latest stable index version.
  tests/unit/test_git_repository.py:
    Q-011 tests for structured artifact hash bindings, workflow-state binding,
    and no implicit git commit during change-record writing.
  tests/fixtures/retrieval/golden_queries.json:
    Q-008 versioned retrieval query_set_id with a positive symbol hit case and
    a blocked missing-API case.
  tests/unit/test_retrieval_regression.py:
    Q-008 tests for golden query loading, regression pass/fail reports,
    eval_report artifact compatibility, missing required evidence failure,
    and false_continue high-risk representation.
  tests/unit/test_mcp_async_jobs.py:
    Q-009 tests for immediate queued job responses, read-only status lookup,
    incomplete partial artifacts on cancellation, job_status artifact compatibility,
    safe tool contracts, and job_id output.
  tests/unit/test_runtime_evidence.py:
    Q-012 tests for supplied-output raw evidence, manual acceptance evidence,
    verified-status guardrails, and runtime_evidence required fields.
  tests/unit/test_knowledge_base.py:
    Q-002 unit tests for text contract separation, metadata inheritance,
    stable hashes, and retrieval text projection.
    Q-003 unit tests for ignore rules, source classification, configured
    extensions, stable source ids, and aggregate source content hash.
    Q-004 unit tests for SQLite source/document/chunk persistence, chunk upsert
    deduplication, and failed index version isolation from stable versions.
    Q-005 unit test for BM25 terms/postings persistence, ranking, and term-hit metadata.
    Q-006 unit test for symbol_index persistence with span and chunk_id.
  tests/unit/test_stub_nodes.py:
    Q-007 stub evidence_pack contract regression test.
  tests/unit/test_workflow_graph.py:
    Q-002A fake execution artifact and blocked-review regression tests;
    Q-007 graph assertions for EvidencePack observability fields;
    Q-010 retrieval trace and evidence-before-proposal regression tests.
    Q-012 graph assertions for upgraded runtime evidence fields.
    Q-013 graph assertions for upgraded fake build evidence fields.
```

## Operating Mode

```text
mode: batch small-loop execution
primary spec: DEV_SPEC.md
active skill: .agents/skills/auto-coder/SKILL.md
execution guide: docs/EXECUTION_CONTROL_GUIDE.md
spec coverage: docs/SPEC_COVERAGE_MATRIX.md
queue: docs/IMPLEMENTATION_QUEUE.md
rollback policy: docs/GIT_WORKFLOW.md
```

## Coverage Matrix

Completion levels:

```text
0 Not Started
1 Contracted
2 Stubbed
3 Implemented
4 Integrated
5 Verified
```

This matrix is the Q-001 audited snapshot. Re-audit before major phase claims or after large implementation batches.

| Module ID | Module | Level | Evidence / Notes | Next Need |
| --- | --- | ---: | --- | --- |
| WF | LangGraph workflow control plane | 4 | Q-015 adds tested checkpoint/resume contracts, MemorySaver-ready graph compile, stale resume blocking, and double resume rejection; controlled fake tail remains in place | persistent SQLite checkpointer, real interrupt UI, E2E resume smoke |
| ART | Artifact contract and store | 4 | Q-016 adds tested read-only artifact DAG projections, stale/missing artifact visibility, dashboard_projection fields, and upstream status reporting | immutable revision history and UI DAG viewer |
| KB | Knowledge ingestion | 3 | Q-004 adds tested SQLite source/document/chunk/index_version persistence; Q-003 source discovery and Q-002 text/chunk contracts remain in place | BM25 index and richer loaders |
| RET | Evidence retrieval | 3 | Q-006 adds tested chunk-bound symbol retrieval over stable SQLite index versions; Q-005 BM25 lexical sparse retrieval remains in place; Q-010 verifies graph consumes generic EvidencePack fields and blocks unsafe continuation when evidence is insufficient; Q-008 adds retrieval regression gate; dense/fusion/rerank still absent | dense/fusion/rerank |
| MM | Multimodal evidence | 1 | Spec exists; implementation not yet real | image metadata/caption fallback |
| PLAN | Planning and feature spec | 3 | planning tests exist | stronger feature_spec artifacts |
| PROP | Patch proposal | 3 | proposal builder/reviewer tests exist | bind to real evidence and dry-run |
| REVIEW | Review gate and safety | 3 | review gate tests exist | integrate risk-tier policy with graph |
| GIT | Git audit and rollback | 4 | Q-011 binds workflow decision artifacts and patch artifacts to Git commit metadata with artifact hashes; no auto-commit behavior is tested; live Git tests are skipped in current Python test process | automated replay/rollback execution |
| BUILD | Build adapter | 4 | Q-013 adds tested BuildProfile, BuildAdapter, BuildResult, diagnostic parsing, error classification, explicit local execution gating, supplied-output classification, and graph-compatible fake build_result; no default dotnet execution in tests | repair loop integration and real project build profile smoke |
| RUN | Runtime evidence | 4 | Q-012 adds tested fake/manual/supplied-output runtime evidence contracts with explicit acceptance guardrails; no real runtime collector or screenshot/log collector | real runtime collector, screenshot/log registry, repair handoff |
| REPAIR | Repair loop | 4 | Q-014 adds tested repair_plan artifacts, retry-budget blocking, build/runtime failure routes, and review-gated repair proposals; no real LLM patch generation | real repair patch generation and runtime repair quality evaluation |
| MCP | MCP/API/tools | 2 | Q-009 adds controlled-agent async job contracts and safe MCP/API tool declarations for ingestion, eval, build, and job status; old RAG MCP server remains separate | integrate controlled-agent read-only MCP tools with graph/artifact readers |
| OBS | Trace, metrics, dashboard | 3 | Q-016 adds tested read-only dashboard projections for ordered workflow trace, evidence summary, artifact DAG, blockers, missing artifacts, and bottleneck timing; unified trace latency writer and UI pages remain incomplete | trace latency schema, persisted trace reader, dashboard UI |
| EVAL | Evaluation/regression gates | 3 | Q-008 adds a tested golden query list, evidence-first retrieval regression evaluator, eval_report payload, and false_continue representation; agent-quality metrics and baseline remain absent | faithfulness/context precision adaptation, agent decision quality, baseline |
| PERF | Performance/concurrency | 1 | Q-003/Q-004 provide source hashes and chunk upsert deduplication; broader batching, cache policy, resource limits, and concurrency controls are not implemented | limits, batching, cache metrics |
| DOM | Domain adapters | 3 | Q-017 adds tested DomainAdapter/GameProfile contracts, GTFO profile policy, unknown-domain blocking, and optional review-gate domain policy; no full onboarding workflow or capability report yet | onboarding workflow, capability report, additional profiles |

## Q-001 Audit Findings

Git:

```text
branch status: main...origin/main
remote: https://github.com/yang-hoo-xin/-agent.git
baseline commit/tag: 914f16e
remote main and tag verified by ls-remote during Q-001
```

Focused tests:

```text
command:
python -m pytest tests/unit/test_workflow_graph.py tests/unit/test_proposal_review.py tests/unit/test_planning.py tests/unit/test_evidence_retrieval.py tests/unit/test_knowledge_base.py tests/unit/test_artifact_contract.py tests/unit/test_stub_nodes.py tests/unit/test_permissions.py tests/unit/test_artifact_store.py tests/unit/test_mod_agent_state.py tests/unit/test_mod_agent_cli.py tests/unit/test_git_repository.py

result:
69 passed, 4 skipped
```

Node classification:

| Node | Classification | Evidence |
| --- | --- | --- |
| `plan_request` | real | RequestPlanner writes request_planning_report |
| `draft_feature_spec` | real | FeatureSpecBuilder writes feature_spec |
| `retrieve_evidence` | real deterministic | DeterministicEvidenceRetriever writes evidence_pack; no BM25/dense/timing fields |
| `create_implementation_plan` | real | ImplementationPlanner blocks/continues based on EvidencePack |
| `generate_patch_proposal` | real intent-only | PatchProposalBuilder creates patch intent, no file edits |
| `review_proposal` | real review gate | ProposalReviewer approves dry_run or blocks |
| `dry_run_apply` | controlled fake | Q-002A writes dry_run_result with execution_mode=fake and no file write |
| `build` | controlled fake | Q-002A writes build_result with execution_mode=fake and no compiler execution |
| `collect_runtime_evidence` | controlled fake | Q-002A writes runtime_evidence with execution_mode=fake and inconclusive status |
| `evaluate` | controlled fake | Q-002A writes eval_report with inconclusive verdict and no real success claim |
| `done` | controlled fake summary | Q-002A writes workflow_summary with claims_real_* fields set false |
| `blocked` | stub | StubNodeRunner writes blocked_report |

Queue audit:

```text
Q-002A completed the controlled fake execution loop.
Q-010 is partial/stale as originally imagined because retrieve_evidence graph wiring already exists.
Q-010 completed as a reconciliation task, not a duplicate graph wiring implementation.
Q-007 completed EvidencePack observability fields.
Q-002 completed text/metadata contracts.
Q-003 completed source discovery and ignore rules.
Q-004 completed SQLite document/chunk/index-version persistence.
Q-005 completed BM25 inverted index V1.
Q-006 completed Symbol Index V1.
Q-008 completed the retrieval regression query list and evidence-first gate.
Q-009 completed the MCP async job contract.
Q-011 completed workflow decision/change commit binding without auto-commit.
Q-012 completed the manual/supplied runtime evidence contract.
Q-013 completed the controlled build adapter contract and error classifier.
Q-014 completed the repair loop and retry-budget contract.
Q-015 completed the checkpoint, interrupt, resume, and stale resume contract.
Q-016 completed the read-only dashboard projection layer for workflow traces,
artifact DAG, evidence summary, stale/missing artifacts, blockers, and
bottleneck timing.
Q-017 completed the generic DomainAdapter and first GTFO GameProfile contract.
Q-018 completed the runtime screenshot metadata registry contract while keeping
screenshots and captions from proving gameplay success by themselves.
Q-019 completed the local agent decision-quality evaluation contract, including
false-continue/review-miss hard gates and baseline claim limits.
An external review summary identified P0/P1 structural risks that can invalidate
some completed claims. The active Review Repair Queue now supersedes ordinary
Q feature work. R-001 and R-002 are completed. R-003 is the next recommended task. Q-020 remains queued but is
blocked behind the active repair queue.
SPEC_COVERAGE_MATRIX.md is now required input for selecting and closing future tasks.
```

## Spec Coverage Matrix Audit

Requirement-level coverage tracking:

```text
created_at: 2026-06-28
file: docs/SPEC_COVERAGE_MATRIX.md

purpose:
  map DEV_SPEC details to module coverage, queue tasks, implementation status,
  test evidence, and missing requirement records.

closed high-impact missing records:
  MISS-001 EvidencePack observability fields
  MISS-002 text and metadata contracts
  MISS-003 stable index versioning
  MISS-004 BM25 inverted index V1
  MISS-005 symbol index target contract
  MISS-017 retrieval golden query regression gate
  MISS-012 MCP async job contract
  MISS-009 Git workflow decision/change commit binding
  MISS-007 manual/supplied runtime evidence contract
  MISS-006 controlled build adapter and build error classifier
  MISS-008 repair loop and retry budget
  MISS-015 checkpoint/interrupt/resume/stale resume
  MISS-016A dashboard projection layer
  MISS-014A DomainAdapter/GameProfile contract and unknown-domain blocking
  MISS-010A runtime screenshot metadata registry
  MISS-011A local agent decision-quality evaluation contract

current high-impact missing records:
  MISS-010 full multimodal ingestion/caption/storage/confidence policy
  MISS-011 full behavior benchmark runner and real baseline execution
  MISS-013 batch/cache/resource/concurrency controls
  MISS-014 full GameProfile onboarding workflow and capability report
  MISS-016 dashboard UI and persisted trace viewer
```

## Q-008 Audit Findings

Retrieval regression query list:

```text
implemented_at: 2026-06-29
coverage_rows:
  EVAL-001 tested

files changed:
  src/mod_agent/evaluation/__init__.py
  src/mod_agent/evaluation/retrieval_regression.py
  tests/fixtures/retrieval/golden_queries.json
  tests/unit/test_retrieval_regression.py
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md
  docs/IMPLEMENTATION_QUEUE.md

behavior:
  golden query sets load by query_set_id and cases fields from DEV_SPEC 41.5
  GoldenQueryCase supports case_id, user_request, queries, required_source_types,
  expected_sources, expected_symbols, expected_retrieval_methods,
  must_block_if_missing, minimum_hit_rate_at_5, expected_readiness, and
  expected_can_generate_patch
  RetrievalRegressionEvaluator runs DeterministicEvidenceRetriever for each query
  report metrics include evidence_hit_rate_at_5, source_type_coverage,
  symbol_hit_rate, readiness_accuracy, false_continue_rate, and retrieval_p95_ms
  eval_report payload satisfies the existing artifact contract
  missing required evidence fails the report
  must_block_if_missing can represent a high-risk false_continue case

focused test result:
  12 passed
```

## Q-009 Audit Findings

MCP async job contract:

```text
implemented_at: 2026-06-29
coverage_rows:
  MCP-002 tested
  MISS-012 closed

files changed:
  src/mod_agent/mcp/__init__.py
  src/mod_agent/mcp/jobs.py
  src/mod_agent/mcp/tools.py
  src/mod_agent/artifacts/registry.py
  tests/unit/test_mcp_async_jobs.py
  tests/unit/test_artifact_contract.py
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md
  docs/IMPLEMENTATION_QUEUE.md

behavior:
  AsyncJobStore.start_job returns a queued job_id immediately and does not run long tasks
  JobRecord serializes job_id, job_type, status, created_at, started_at,
  finished_at, artifact_refs, trace_refs, and error
  get_job_status reads existing job status without mutation
  cancel_job marks queued/running jobs cancelled and can mark partial artifacts incomplete
  job_status artifact payload validates through ArtifactStore
  async job tool contracts expose start_ingestion, get_job_status,
  run_retrieval_eval, and build_mod
  dangerous direct tools such as run_build and apply_patch are not exposed by Q-009

focused test result:
  24 passed
```

## Q-011 Audit Findings

Git decision-to-commit binding:

```text
implemented_at: 2026-06-29
coverage_rows:
  GIT-001 tested
  GIT-002 partial
  MISS-009 closed

files changed:
  src/mod_agent/git/__init__.py
  src/mod_agent/git/repository.py
  src/mod_agent/git/workflow_binding.py
  tests/unit/test_git_repository.py
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md
  docs/IMPLEMENTATION_QUEUE.md

behavior:
  GitChangeRecord includes decision_artifacts and patch_artifacts arrays
  artifact bindings include artifact_type, path, and artifact_hash
  workflow binding maps a workflow stage to the decision artifact that justified it
  dry_run_apply binds proposal_review as the decision artifact and patch_proposal as the patch artifact
  write_workflow_change_record writes a git_change_record artifact through ArtifactStore
  workflow Git binding does not create commits, tags, pushes, or mutate user Git history
  replay_command and rollback_hint remain metadata only

focused Git/artifact tests:
  16 passed, 4 skipped

focused controlled-agent suite:
  100 passed, 4 skipped
```

## Q-015 Audit Findings

Checkpoint, interrupt, and resume contract:

```text
implemented_at: 2026-06-30
coverage_rows:
  WF-004 tested
  MISS-015 closed

files changed:
  src/mod_agent/artifacts/registry.py
  src/mod_agent/workflow/__init__.py
  src/mod_agent/workflow/checkpointing.py
  src/mod_agent/workflow/graph.py
  src/mod_agent/workflow/interrupts.py
  tests/unit/test_artifact_contract.py
  tests/unit/test_workflow_checkpointing.py
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md
  docs/IMPLEMENTATION_QUEUE.md

behavior:
  workflow_checkpoint artifact records checkpoint_id, run_id, feature_id,
  request_id, checkpoint_stage, state_snapshot, artifact_refs,
  artifact_hashes, resume_allowed_fields, interrupt_reason, and policy details
  resume_report artifact records resume_id, checkpoint_id, run_id, stage,
  decision, status, allowed, reason, applied_updates, stale_reasons, and blockers
  ResumePayload follows the DEV_SPEC resume schema fields
  ResumeValidator validates run_id, stage, decision, approver, and artifact refs
  WorkflowCheckpointStore checks ArtifactStore freshness before accepting resume
  stale upstream artifacts block resume with STALE_RESUME_REJECTED
  repeated resume attempts are blocked with DOUBLE_RESUME_REJECTED
  build_graph accepts LangGraph checkpointer, interrupt_before, and interrupt_after
  parameters; current environment exposes LangGraph MemorySaver, not SqliteSaver

focused Q-015 tests:
  32 passed

focused controlled-agent suite:
  131 passed, 4 skipped
```

## Q-014 Audit Findings

Repair loop and retry budget:

```text
implemented_at: 2026-06-30
coverage_rows:
  EXEC-009 tested
  EXEC-010 tested
  MISS-008 closed

files changed:
  src/mod_agent/__init__.py
  src/mod_agent/artifacts/registry.py
  src/mod_agent/proposal/reviewer.py
  src/mod_agent/repair/__init__.py
  src/mod_agent/repair/planner.py
  src/mod_agent/workflow/graph.py
  src/mod_agent/workflow/nodes.py
  src/mod_agent/workflow/transitions.py
  tests/unit/test_artifact_contract.py
  tests/unit/test_repair_loop.py
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md
  docs/IMPLEMENTATION_QUEUE.md

behavior:
  RepairPlan records repair_id, feature_id, failure_source, failure_class,
  failure_evidence/evidence_refs, hypothesis, minimal_changes, retry_count,
  retry_budget, retry_budget_remaining, retry_exhausted, stop_condition,
  forbidden_regressions, allowed_next_stage, and blockers
  RepairPlanner derives build repair scope from failed build_result diagnostics
  and includes the build_result artifact path as failure evidence
  retry budget exhaustion writes a blocked repair_plan and routes to blocked
  RepairPatchProposalBuilder creates intent-only repair proposals and never
  applies code directly
  ProposalReviewer can validate repair proposals against repair_plan evidence,
  but still enforces evidence binding, scope, permission, test plan, and
  forbidden path checks
  build failures route to create_repair_plan; explicit runtime failures can
  route to create_repair_plan; fake/inconclusive runtime evidence still goes to
  evaluation and does not claim real runtime success

focused Q-014 tests:
  33 passed

focused controlled-agent suite:
  125 passed, 4 skipped

full tests/unit attempt:
  collection failed before execution for legacy RAG tests because optional
  dependencies `jieba` and `mcp` are not installed in the current environment
```

## Q-013 Audit Findings

Controlled build adapter contract:

```text
implemented_at: 2026-06-30
coverage_rows:
  EXEC-003 tested
  EXEC-004 tested
  MISS-006 closed

files changed:
  .gitignore
  config/settings.yaml
  src/mod_agent/__init__.py
  src/mod_agent/artifacts/registry.py
  src/mod_agent/build/__init__.py
  src/mod_agent/build/adapter.py
  src/mod_agent/workflow/graph.py
  src/mod_agent/workflow/nodes.py
  tests/unit/test_artifact_contract.py
  tests/unit/test_build_adapter.py
  tests/unit/test_workflow_graph.py
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md
  docs/IMPLEMENTATION_QUEUE.md

behavior:
  BuildProfile records profile_id, build_system, working_directory, command, timeout_seconds, expected_artifacts, and log_path
  BuildProfileRegistry reads the build.profiles config shape
  BuildAdapter classifies supplied output without running a command
  BuildAdapter skips local execution unless allow_execution is explicit
  approved local execution uses an injected runner in tests, not a hidden subprocess
  BuildErrorClassifier maps compiler output to syntax_error, missing_reference, namespace_error, api_mismatch, il2cpp_access_error, config_binding_error, unsafe_path_error, or unknown
  BuildResult exposes status, command, exit_code, diagnostics, error_class, repair_handoff, duration_ms, expected_artifacts, and claims_real_build_success
  fake graph build emits the upgraded build_result contract and still cannot claim real build success
  .gitignore no longer hides src/mod_agent/artifacts or src/mod_agent/build from git status

focused Q-013 tests:
  40 passed

focused controlled-agent suite:
  119 passed, 4 skipped
```

## Q-012 Audit Findings

Manual and supplied runtime evidence contract:

```text
implemented_at: 2026-06-29
coverage_rows:
  EXEC-005 partial, manual/supplied source contracts improved
  EXEC-006 tested
  MISS-007 closed

files changed:
  src/mod_agent/__init__.py
  src/mod_agent/artifacts/registry.py
  src/mod_agent/runtime/__init__.py
  src/mod_agent/runtime/evidence.py
  src/mod_agent/workflow/graph.py
  src/mod_agent/workflow/nodes.py
  tests/unit/test_artifact_contract.py
  tests/unit/test_runtime_evidence.py
  tests/unit/test_workflow_graph.py
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md
  docs/IMPLEMENTATION_QUEUE.md

behavior:
  runtime_evidence and manual_evidence require execution_mode and evidence_source
  startup_loaded and gameplay_behavior_verified are separate fields
  evidence_items carry type, source, locator, supports_acceptance, confidence, and raw_excerpt
  verification_status and acceptance_status are separate from raw_supplied_output
  verified runtime evidence requires startup_loaded, gameplay_behavior_verified, and explicit acceptance evidence
  fake runtime evidence remains inconclusive and cannot claim real runtime success
  supplied output can be recorded without launching the game and without claiming acceptance
  workflow fake runtime node emits the upgraded runtime evidence contract

focused Q-012 tests:
  30 passed

focused controlled-agent suite:
  105 passed, 4 skipped
```

## Q-002A Audit Findings

Controlled fake execution:

```text
implemented_at: 2026-06-28
files changed:
  src/mod_agent/workflow/graph.py
  tests/unit/test_workflow_graph.py

behavior:
  approved proposal_review path writes dry_run_result, build_result, runtime_evidence, eval_report, and workflow_summary
  blocked proposal_review path does not write fake success artifacts
  no real file write is performed
  no real compiler/build command is executed
  no real runtime/game process is launched
  final workflow_summary remains inconclusive
  final workflow_summary does not claim real mod, build, or runtime success

focused test result:
  71 passed, 4 skipped
```

## Q-007 Audit Findings

EvidencePack observability:

```text
implemented_at: 2026-06-28
coverage_rows:
  RET-007 tested
  RET-008 tested
  RET-010 partial
  OBS-001 partial
  MISS-001 closed

files changed:
  src/mod_agent/evidence/models.py
  src/mod_agent/evidence/readiness.py
  src/mod_agent/evidence/retriever.py
  src/mod_agent/workflow/graph.py
  tests/unit/test_artifact_contract.py
  tests/unit/test_artifact_store.py
  tests/unit/test_evidence_retrieval.py
  tests/unit/test_workflow_graph.py

behavior:
  evidence_pack artifact contract now requires retrieval_methods_used
  evidence_pack artifact contract now requires missing_evidence
  evidence_pack artifact contract now requires disabled_modes
  evidence_pack artifact contract now requires timing
  evidence_pack artifact contract now requires trace_refs
  deterministic retrieval records query, symbol, text, readiness, and total timing
  readiness blockers derive structured missing_evidence entries
  empty EvidencePack also serializes default observability fields
  graph evidence_summary consumes the generic EvidencePack fields without depending on retriever internals
  stub retrieve_evidence node writes the upgraded evidence_pack shape

focused test result:
  32 passed

focused controlled-agent suite:
  72 passed, 4 skipped
```

## Q-010 Audit Findings

Workflow retrieval reconciliation:

```text
implemented_at: 2026-06-28
coverage_rows:
  WF-003 partial, evidence gate verified
  RET-007 tested
  RET-010 partial, trace/evidence details improved
  OBS-001 partial, retrieve_evidence trace details improved

files changed:
  src/mod_agent/workflow/graph.py
  tests/unit/test_workflow_graph.py
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md
  docs/IMPLEMENTATION_QUEUE.md

behavior:
  retrieve_evidence finished trace now includes readiness
  retrieve_evidence finished trace now includes can_generate_patch
  retrieve_evidence finished trace now includes retrieval_methods_used
  retrieve_evidence finished trace now includes missing_evidence_count
  retrieve_evidence finished trace now includes disabled_modes
  retrieve_evidence finished trace now includes timing
  insufficient evidence still writes evidence_pack, then blocks before implementation_plan
  insufficient evidence does not create patch_proposal or proposal_review
  insufficient evidence does not create dry_run_result, build_result, or runtime_evidence

focused test result:
  31 passed

focused controlled-agent suite:
  74 passed, 4 skipped
```

## Q-002 Audit Findings

Knowledge Hub text and metadata contracts:

```text
implemented_at: 2026-06-28
coverage_rows:
  KB-002 tested
  MISS-002 closed

files changed:
  src/mod_agent/knowledge/models.py
  src/mod_agent/knowledge/__init__.py
  tests/unit/test_knowledge_base.py
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md
  docs/IMPLEMENTATION_QUEUE.md

behavior:
  Document keeps raw_text, canonical_text, and text as separate fields
  IndexedFile.to_document builds stable document_id and source metadata
  Chunk carries text and text_for_retrieval separately
  Chunk metadata inherits source metadata and adds chunk identity, span, strategy, symbols, risk tags, evidence kind, source_hash, content_hash, and enrichment fields
  ChunkRecord projects text_for_retrieval into text_for_embedding while leaving raw/canonical document evidence untouched

focused Knowledge Base tests:
  8 passed

focused controlled-agent suite:
  77 passed, 4 skipped
```

## Skill And Control Consistency Audit

Auto-coder execution alignment:

```text
implemented_at: 2026-06-28
files changed:
  .agents/skills/auto-coder/SKILL.md
  docs/EXECUTION_CONTROL_GUIDE.md
  docs/PROJECT_STATE.md

behavior:
  active execution order is unified across the skill and execution guide
  DEV_SPEC product, safety, and architecture rules outrank the execution protocol
  the active skill is the implementation protocol, not the source of product truth
  generated auto-coder references are navigation aids only
  docs/IMPLEMENTATION_QUEUE.md remains the rolling task queue
  next-stage commands continue the queue and do not imply commit

verification:
  skill frontmatter parsed successfully
  skill file is UTF-8 without BOM
  git diff --check passed for the skill and control documents
```

## Q-003 Audit Findings

Source discovery and ignore rules:

```text
implemented_at: 2026-06-28
coverage_rows:
  KB-001 tested
  PERF-003 partial, source hash support improved

files changed:
  src/mod_agent/knowledge/source_discovery.py
  src/mod_agent/knowledge/source_registry.py
  src/mod_agent/knowledge/__init__.py
  tests/unit/test_knowledge_base.py
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md
  docs/IMPLEMENTATION_QUEUE.md

behavior:
  SourceDiscovery discovers indexable files from configured roots
  SourceDiscovery classifies target_source, domain_note, prior_artifact, build_log, runtime_log, reference_mod, decompiled_api, and screenshot source types
  SourceDiscovery assigns stable source_id values independent of content changes
  SourceDiscovery records SHA256 content_hash per discovered file
  SourceDiscovery.from_config reads knowledge.indexable_extensions and safety.generated_mods_access
  SourceRegistry.iter_files now prunes .git, .venv, bin, obj, node_modules, generated, generated_mods, and cache directories by default
  generated_mods remains blocked unless explicitly enabled on the source definition or discovery instance
  SourceRegistry.source_content_hash provides an aggregate hash for incremental decisions

focused Knowledge Base tests:
  12 passed

focused controlled-agent suite:
  81 passed, 4 skipped
```

## Q-004 Audit Findings

SQLite metadata store contract:

```text
implemented_at: 2026-06-28
coverage_rows:
  KB-004 tested
  MISS-003 closed
  PERF-003 partial, chunk persistence and duplicate upsert behavior improved

files changed:
  src/mod_agent/knowledge/database.py
  src/mod_agent/knowledge/models.py
  src/mod_agent/knowledge/__init__.py
  tests/unit/test_knowledge_base.py
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md
  docs/IMPLEMENTATION_QUEUE.md

behavior:
  KnowledgeDatabase creates knowledge_sources, knowledge_documents, knowledge_chunks, and index_versions tables
  KnowledgeDatabase persists collection-scoped source snapshots with status
  KnowledgeDatabase persists document hash records from Document metadata
  KnowledgeDatabase persists chunks bound to collection_id and index_version
  repeated upsert of the same collection/index_version/chunk_id keeps one chunk row
  index_versions record building, stable, and failed status
  failed index versions do not replace the newest stable index version

focused Knowledge Base tests:
  14 passed

focused controlled-agent suite:
  83 passed, 4 skipped
```

## Q-005 Audit Findings

BM25 inverted index V1:

```text
implemented_at: 2026-06-28
coverage_rows:
  RET-003 tested
  MISS-004 closed

files changed:
  src/mod_agent/knowledge/bm25_indexer.py
  src/mod_agent/knowledge/database.py
  src/mod_agent/knowledge/models.py
  src/mod_agent/knowledge/__init__.py
  src/mod_agent/evidence/retriever.py
  tests/unit/test_knowledge_base.py
  tests/unit/test_evidence_retrieval.py
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md
  docs/IMPLEMENTATION_QUEUE.md

behavior:
  BM25Indexer builds a local lexical sparse inverted index over persisted chunks
  bm25_terms stores collection_id, index_version, term, and doc_freq
  bm25_postings stores collection_id, index_version, term, chunk_id, and term_freq
  BM25 query returns BM25Hit with index_version, score, hit_terms, term_frequencies, chunk_id, source_path, span, excerpt, and metadata
  DeterministicEvidenceRetriever queries the latest stable index version when available
  EvidencePack can include retrieval_method=bm25 and bm25 timing/count fields
  BM25 remains independent of dense embeddings, vector stores, and neural sparse encoders

focused Knowledge/Evidence tests:
  22 passed

focused controlled-agent suite:
  85 passed, 4 skipped
```

## Q-006 Audit Findings

Symbol Index V1:

```text
implemented_at: 2026-06-28
coverage_rows:
  RET-002 tested
  MISS-005 closed

files changed:
  src/mod_agent/knowledge/database.py
  src/mod_agent/knowledge/models.py
  src/mod_agent/knowledge/symbol_indexer.py
  src/mod_agent/knowledge/__init__.py
  src/mod_agent/evidence/retriever.py
  tests/unit/test_knowledge_base.py
  tests/unit/test_evidence_retrieval.py
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md
  docs/IMPLEMENTATION_QUEUE.md

behavior:
  KnowledgeDatabase creates symbol_index for collection-scoped chunk symbols
  symbol_index rows bind symbol, symbol_kind, chunk_id, source_path, start_line, end_line, and index_version
  SymbolIndexer.index_chunks builds symbol_index rows from persisted chunk metadata symbols
  SymbolIndexer.search_chunk_symbols returns exact chunk-bound symbol hits
  DeterministicEvidenceRetriever prefers stable chunk symbol_index hits before legacy file-level symbols
  chunk-bound symbol evidence remains retrieval_method=symbol_exact for readiness classification

focused Knowledge/Evidence tests:
  24 passed

focused controlled-agent suite:
  87 passed, 4 skipped
```

## Q-014/Q-015 Joint Smoke Findings

```text
verified_at: 2026-06-30
scope:
  repair loop artifacts and checkpoint/resume gates

files changed:
  tests/unit/test_repair_checkpoint_smoke.py
  docs/PROJECT_STATE.md
  docs/IMPLEMENTATION_QUEUE.md
  docs/SPEC_COVERAGE_MATRIX.md

behavior verified:
  build_result -> repair_plan -> patch_proposal -> proposal_review artifact chain can be checkpointed at review_proposal
  repair patch proposal remains evidence-bound to repair_plan evidence_refs
  review approval resume writes resume_report and only applies approvals.review
  double resume is blocked with DOUBLE_RESUME_REJECTED
  changed repair_plan artifact after checkpoint is blocked with STALE_RESUME_REJECTED

focused Q-014/Q-015 smoke:
  13 passed

focused controlled-agent suite:
  133 passed, 4 skipped
```

## Q-016 Audit Findings

Dashboard trace viewer MVP:

```text
implemented_at: 2026-06-30
coverage_rows:
  OBS-001 partial, dashboard trace projection improved
  OBS-002 partial, bottleneck timing projection added
  OBS-003 partial, read-only projection added but UI absent
  ART-003 partial, artifact DAG projection added but immutable revision UI absent
  MISS-016 partially reduced by projection layer

files changed:
  src/mod_agent/dashboard/__init__.py
  src/mod_agent/dashboard/projections.py
  tests/unit/test_dashboard_projection.py
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md
  docs/IMPLEMENTATION_QUEUE.md

behavior:
  DashboardProjectionBuilder builds read-only feature projections from
  ArtifactStore envelopes and supplied workflow trace events
  workflow_trace preserves event order, node name, stage, status, artifact_refs,
  summary, and details
  artifact_dag exposes artifact nodes, upstream edges, freshness status, stale
  reasons, dashboard_projection fields, blockers, trace_refs, and missing
  expected artifacts
  evidence_summary exposes readiness, can_generate_patch,
  retrieval_methods_used, missing_evidence, disabled_modes, and timing
  bottlenecks are derived from trace details timing and EvidencePack timing
  blocked trace events and artifact blockers are exposed as structured blockers
  projection reads artifacts and checks freshness but does not write artifacts
  or mutate workflow state

focused Q-016 tests:
  25 passed

focused controlled-agent suite:
  135 passed, 4 skipped

post-loop hard gate:
  git status --short shows Q-016 files plus the existing multi-phase dirty worktree
  git diff --stat completed for tracked files; untracked Q-016 files are not
  included by Git in this stat output
  git diff --check completed with line-ending warnings only
  skip_commit_reason: auto-commit is not enabled, and the worktree contains
  many existing uncommitted phase changes that should not be mixed into an
  implicit Q-016 commit
```

## Q-017 Audit Findings

Domain Adapter and GTFO GameProfile contracts:

```text
implemented_at: 2026-06-30
coverage_rows:
  GOV-002 partial, GTFO now behind adapter boundary
  DOM-001 tested
  DOM-002 tested
  DOM-003 tested
  DOM-004 tested
  DOM-005 partial, registry exists but full onboarding workflow absent
  DOM-006 tested
  MISS-014 partially reduced by contracts and unknown-domain blocking

files changed:
  src/mod_agent/__init__.py
  src/mod_agent/domain/__init__.py
  src/mod_agent/domain/models.py
  src/mod_agent/domain/gtfo.py
  src/mod_agent/domain/unsupported.py
  src/mod_agent/proposal/reviewer.py
  tests/unit/test_domain_adapter.py
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md
  docs/IMPLEMENTATION_QUEUE.md

behavior:
  DomainAdapter protocol matches DEV_SPEC section 9.2 surface
  DomainProfile matches DEV_SPEC section 50.8 GameProfile schema fields
  GTFOAdapter exposes GTFO / Unity IL2CPP / BepInEx / HarmonyX profile data
  GTFOAdapter classifies config_only, ui_feedback_without_hook, game_hook,
  runtime_behavior_change, native/interop/reflection-heavy, and unknown/block
  GTFOAdapter exposes default knowledge source definitions, build profile,
  runtime profile, verification strategy, allowed roots, and forbidden paths
  UnsupportedDomainAdapter blocks game-specific runtime changes when no
  GameProfile is available
  ProposalReviewer keeps old behavior when domain_policy is omitted and applies
  domain_profile / forbidden_paths / scope_boundary blocking when supplied
  DomainAdapterRegistry allows future adapters to register without changing
  workflow graph code

focused Q-017 tests:
  20 passed

focused controlled-agent suite:
  141 passed, 4 skipped

post-loop hard gate:
  git status --short shows Q-017 files plus the existing multi-phase dirty worktree
  git diff --stat completed for tracked files; untracked Q-017 files are not
  included by Git in this stat output
  git diff --check completed with line-ending warnings only
  Q-017 trailing-whitespace scan found no matches
  skip_commit_reason: auto-commit is not enabled, and the worktree contains
  many existing uncommitted phase changes that should not be mixed into an
  implicit Q-017 commit
```

## Q-018 Audit Findings

Runtime screenshot registry contract:

```text
implemented_at: 2026-06-30
coverage_rows:
  EXEC-005 partial, screenshot source contract exists but real capture remains
  EXEC-007 tested
  MM-001 partial, runtime screenshot metadata exists but document image loader remains
  MM-004 partial, screenshot metadata artifact exists but image byte storage remains
  MM-006 partial, visual-only screenshot policy enforced but full caption policy remains
  MISS-010A closed

files changed:
  src/mod_agent/runtime/__init__.py
  src/mod_agent/runtime/screenshots.py
  src/mod_agent/artifacts/registry.py
  tests/unit/test_runtime_screenshots.py
  tests/unit/test_artifact_contract.py
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md
  docs/IMPLEMENTATION_QUEUE.md

behavior:
  ScreenshotMetadata records screenshot_id, feature_id, file_path, source,
  captured_at, caption, caption_status, metadata, content_hash,
  supports_acceptance, confidence, and visual-only verification_status
  build_screenshot_metadata validates required identifiers and caption_status
  values without reading or capturing image files
  build_screenshot_registry_payload creates screenshot_registry artifacts with
  screenshot_count, captioned_count, missing_caption_count, screenshots,
  verification_status=inconclusive, acceptance_status=visual_evidence_only,
  and claims_real_runtime_success=false
  screenshot_registry_to_runtime_item converts screenshot metadata into a
  runtime evidence item with empty supports_acceptance and confidence=0.0
  ArtifactTypeRegistry registers screenshot_registry under runtime_evidence
  producer stage for evaluate, repair_plan, and dashboard consumers

focused Q-018 tests:
  25 passed

affected controlled-agent suite:
  111 passed, 4 skipped

verification gap:
  broader command including tests/unit/test_planning.py failed during
  collection with an existing planning/workflow circular import:
  ImportError: cannot import name 'FeatureSpec' from partially initialized
  module 'src.mod_agent.planning'

post-loop hard gate:
  git status --short shows Q-018 files plus the existing multi-phase dirty worktree
  git diff --stat completed for tracked files; untracked Q-018 files are not
  included by Git in this stat output
  git diff --check completed with line-ending warnings only
  Q-018 trailing-whitespace scan found no matches in the new/changed Q-018 files
  skip_commit_reason: auto-commit is not enabled, and the worktree contains
  many existing uncommitted phase changes that should not be mixed into an
  implicit Q-018 commit
```

## Q-019 Audit Findings

Agent decision-quality evaluation contract:

```text
implemented_at: 2026-06-30
coverage_rows:
  EVAL-002 tested
  EVAL-003 tested
  EVAL-004 partial, baseline claim contract exists but real baseline runner absent
  MISS-011A closed
  MISS-011 narrowed to full benchmark runner, real baseline execution,
  multi-run consistency, trace matching, and dashboard integration

files changed:
  src/mod_agent/evaluation/__init__.py
  src/mod_agent/evaluation/agent_quality.py
  tests/fixtures/evaluation/agent_quality_cases.json
  tests/unit/test_agent_quality_eval.py
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md
  docs/IMPLEMENTATION_QUEUE.md

behavior:
  AgentQualityCase binds expected decision contracts to observed workflow,
  evidence, review, repair, final-claim, and baseline metric fields
  AgentQualityEvaluator computes route_accuracy, risk_classification_accuracy,
  evidence_sufficiency, review_correctness, repair_quality, faithfulness,
  answer_relevancy, context_precision, false_continue_rate, review_miss_rate,
  hard_fail_rate, and mean_score
  false continue, review miss, evidence sufficiency mismatch, forbidden claim,
  and required baseline absence are represented as gate failures
  AgentQualityReport serializes to eval_report artifact payloads with
  baseline_status, claims_allowed, and claims_forbidden
  missing optional baseline permits only design-level auditability,
  controllability, and reviewability claims
  missing required baseline fails the report

focused Q-019 tests:
  25 passed

affected controlled-agent suite:
  117 passed, 4 skipped

verification gap:
  direct-LLM baseline execution is not implemented
  trace matching, multi-run consistency, behavior_eval_report artifact type,
  and dashboard integration remain future work

post-loop hard gate:
  git status --short shows Q-019 files plus the existing multi-phase dirty worktree
  git diff --stat completed for tracked files; untracked Q-019 files are not
  included by Git in this stat output
  git diff --check completed with line-ending warnings only
  Q-019 trailing-whitespace scan found no matches in the new/changed Q-019 files
  skip_commit_reason: auto-commit is not enabled, and the worktree contains
  many existing uncommitted phase changes that should not be mixed into an
  implicit Q-019 commit
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
| PROJECT_STATE may overclaim because it is generated by the agent itself | High | Q-001 must verify claims against git status, code, tests, artifacts, and command output |
| Queue may become RAG-first despite capability-first spec direction | High | After Q-001, prioritize runnable controlled loop tasks before deeper optional Knowledge Hub expansion |

## Current Conflict Ledger

| Conflict | Status | Resolution |
| --- | --- | --- |
| RAG QA product vs controlled code-generation platform | resolved in spec | RAG is subsystem, not product goal |
| Need 50k LOC vs risk of filler code | resolved in spec | Count only business code with tests/artifacts |
| BM25 sparse vs neural sparse vector ambiguity | resolved in spec | BM25 inverted index is V1; neural sparse is optional later |
| Image caption vs runtime proof | resolved in spec | Caption is visual evidence only, not success proof |
| Capability-first loop vs RAG/KB-first queue | monitored | Controlled fake loop is runnable; Knowledge Hub tasks proceed only when they unblock evidence-grounded code generation |
| Q-010 original implementation wording vs existing graph wiring | resolved by Q-001 | Q-010 is now reconciliation/verification, not duplicate wiring |
| Skill authority order vs execution guide authority order | resolved | Both now use the same order: user instruction, DEV_SPEC rules, active skill protocol, execution guide, coverage matrix, project state, queue, code/tests, generated references |

## Last Verified Tests

Focused Q-019 suite:

```text
25 passed
```

Affected controlled-agent suite verified after Q-019:

```text
117 passed, 4 skipped
```

The skipped tests are live Git tests that require an available Git executable inside the Python test process. Git behavior is still partially covered by injected-command tests and external git command audits.

A broader command that included `tests/unit/test_planning.py` failed during
collection because of an existing planning/workflow circular import:

```text
ImportError: cannot import name 'FeatureSpec' from partially initialized module 'src.mod_agent.planning'
```

Full `python -m pytest tests/unit` was attempted after Q-014 but could not be used
as the loop gate because legacy RAG tests failed during collection with missing
optional dependencies `jieba` and `mcp`.

## Review Repair Queue Audit

```text
opened_at: 2026-07-01
source_review: C:/Users/10160/Desktop/ai学习/mod_agent_full_issue_summary.md
status: active
ordinary_queue_status: Q-020 and later tasks remain queued but blocked behind
  unresolved R-001 through R-007 unless the user explicitly waives or downgrades
  a finding with evidence

triaged_findings:
  R-001 from P0-002: completed. graph review_proposal now passes a resolved
    DomainReviewPolicy to ProposalReviewer through the default domain registry.
  R-002 from P0-003: completed. ProposalReviewer now blocks evidence-bound
    proposals when no evidence_pack or repair_plan can validate evidence refs.
  R-003 from P0-004: implementation_plan must separate evidence_source_path
    from edit_target_path.
  R-004 from P0-005: real build success claims require expected artifact
    verification, not exit_code alone.
  R-005 from P1-004: ArtifactStore.write must enforce
    required_upstream_artifacts.
  R-006 from P0-006: dashboard destructive operations need permission/audit or
    must be disabled by default.
  R-007 from P0-007: trace/dashboard display needs redaction, size caps, and
    key allowlists.
  R-008 from P0-001: fake/local execution summary must not be read as real
    requested-behavior success.
  R-009 from P1-001: legacy RAG output and mod_agent evidence authority need a
    clear boundary.
  R-010 from P1-002: controlled-agent paths need a single collection resolver.
  R-011 from P1-003: document/chunk/hash/source identity fields need one
    explicit mapping.
  R-012 from P1-005: checkpoint/resume needs graph-level proposal/diff hash
    binding and actual state restoration evidence.
  R-013 from P1-006: dashboard needs mod_agent workflow/artifact/proposal/build/
    runtime/repair projections.

process_change:
  .agents/skills/auto-coder/SKILL.md and docs/EXECUTION_CONTROL_GUIDE.md now
  require unresolved P0/P1 review findings to outrank ordinary Q feature work.
  The post-loop hard gate now includes a review repair gate.

next_recommended_task: R-003
```

## R-001 Audit Findings

Graph Domain Policy Wiring:

```text
implemented_at: 2026-07-01
coverage_rows:
  REVIEW-001 remains partial because R-002 is still open
  DOM-004 tested
  MISS-R001 closed by MISS-R001A

files changed:
  src/mod_agent/workflow/graph.py
  tests/unit/test_workflow_graph.py
  docs/IMPLEMENTATION_QUEUE.md
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md

behavior:
  build_graph accepts optional domain_adapter_registry and creates a default
  registry when none is supplied.
  review_proposal resolves DomainReviewPolicy from target_domain and passes it
  to ProposalReviewer.
  target_domain=gtfo is resolved through GTFO_DOMAIN_NAME when that adapter is
  registered.
  unknown registry lookup falls back to UnsupportedDomainAdapter policy so
  game-specific runtime proposals block through the domain_profile rule.
  default build_graph calls now enforce domain policy when target_domain exists.

focused R-001 tests:
  16 passed

affected workflow/review/repair/checkpoint tests:
  20 passed

verification gap:
  R-002 remains open: direct ProposalReviewer calls can still weaken evidence
  validation when evidence_pack is missing.
  R-003 remains open: implementation_plan still conflates evidence source path
  and edit target path.

next_recommended_task: R-002
```

## R-002 Audit Findings

Evidence Pack Required For Evidence-Bound Review:

```text
implemented_at: 2026-07-01
coverage_rows:
  REVIEW-001 tested
  MISS-R002 closed by MISS-R002A

files changed:
  src/mod_agent/proposal/reviewer.py
  tests/unit/test_proposal_review.py
  tests/unit/test_repair_loop.py
  docs/IMPLEMENTATION_QUEUE.md
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md

behavior:
  ProposalReviewer now blocks a change unit with evidence_refs when neither
  evidence_pack nor repair_plan supplies evidence ids.
  ProposalReviewer still allows repair proposals to validate against repair_plan
  evidence refs when repair_plan is the approved evidence source.
  Evidence refs not present in the approved evidence source still block.

focused R-002 tests:
  13 passed

affected workflow/domain/checkpoint tests:
  24 passed

verification gap:
  R-003 remains open: implementation_plan still conflates evidence source path
  and edit target path.

next_recommended_task: R-003
```

## Next Execution Rule

Use `docs/IMPLEMENTATION_QUEUE.md`.
Use `docs/SPEC_COVERAGE_MATRIX.md` to confirm which requirement rows a task changes.
If the Review Repair Queue is active, select the first ready R task before Q
feature work.

If the queue is stale:

```text
1. Re-audit current code and tests.
2. Update module coverage in this file.
3. Update requirement coverage in docs/SPEC_COVERAGE_MATRIX.md.
4. Rebuild the next 10 task queue from DEV_SPEC.md.
5. Execute the first dependency-free task.
```

Q-001 required audit commands:

```text
git status --short --branch
git diff --stat
git log --oneline --decorate -5
git tag
git remote -v
git ls-remote --heads origin main
git ls-remote --tags origin baseline-controlled-agent-v0
```

If network prevents `ls-remote`, record the failure and do not mark remote verification complete.


## Archived Completed Queue Records From IMPLEMENTATION_QUEUE.md


### Q-000B: Spec Coverage Matrix

```text
Status: done
Module: OBS
Spec refs: 42, 44, 48.2, 50.6
Coverage IDs: GOV-004, MISS-001 through MISS-016
Goal: Add a durable requirement-level matrix so small implementation loops can prove which DEV_SPEC details they cover and which details remain missing.
Inputs: DEV_SPEC.md, docs/PROJECT_STATE.md, docs/IMPLEMENTATION_QUEUE.md, docs/EXECUTION_CONTROL_GUIDE.md
Files to modify: docs/SPEC_COVERAGE_MATRIX.md, docs/PROJECT_STATE.md, docs/IMPLEMENTATION_QUEUE.md, docs/EXECUTION_CONTROL_GUIDE.md
Artifacts produced: none
Trace events: none
Tests: documentation consistency check via git diff/check
Acceptance criteria:
  - matrix defines statuses and maintenance rules
  - matrix records current implemented, partial, queued, not_started, and missing requirements
  - PROJECT_STATE references the matrix as current control input
  - IMPLEMENTATION_QUEUE requires coverage-row updates when tasks close
Failure behavior: if the matrix becomes stale, re-audit code/tests and update it before implementing the next feature
Out of scope: changing product behavior
Dependencies: Q-001 and Q-002A state available
Conflict checks: do not treat matrix rows as implementation evidence
Completed evidence:
  - docs/SPEC_COVERAGE_MATRIX.md created
  - high-impact missing requirements MISS-001 through MISS-016 recorded
  - execution guide, project state, and queue now reference the matrix
```


### Q-001: Re-audit Current Implementation Against Spec

```text
Status: done
Module: WF, ART, KB, RET, OBS
Spec refs: 0, 37, 39, 41, 45, 49, 50
Goal: Compare current code, tests, git state, and queue against DEV_SPEC; update PROJECT_STATE and refresh the queue if capability-first direction conflicts with RAG/KB-first tasks.
Inputs: DEV_SPEC.md, current src/mod_agent, tests/unit, git status/log/tag/remote output
Files to modify: docs/PROJECT_STATE.md, docs/IMPLEMENTATION_QUEUE.md
Artifacts produced: none
Trace events: none
Tests: no code tests required; run targeted status/import checks and focused tests if needed
Acceptance criteria:
  - git remote and baseline push status are recorded honestly
  - dirty worktree files are listed from git status
  - current graph nodes are classified as real, fake, stub, or missing
  - Q-010 is marked fresh, partial, superseded, or replaced
  - queue contains at least one capability-first controlled-loop task
  - unsupported completion levels are downgraded
  - fake/local execution risk and capability-first conflict are recorded
Failure behavior: mark unknown modules lower, do not overclaim
Out of scope: feature implementation
Dependencies: none
Conflict checks: do not treat imported RAG skeleton as completed controlled-agent behavior
Completed evidence:
  - git status/log/tag/remote audited
  - origin/main and baseline tag verified by git ls-remote
  - focused controlled-agent unit suite passed: 69 passed, 4 skipped
  - PROJECT_STATE coverage matrix updated from implementation/test evidence
  - Q-002A confirmed as next capability-first task
  - Q-010 reclassified as reconciliation/partial-stale task
```


### Q-002A: Controlled Fake Execution Loop

```text
Status: done
Module: WF, PROP, REVIEW, BUILD, RUN, OBS
Spec refs: 41.4, 45.12.1, 49.4, 50 capability-first direction
Goal: Keep the main controlled code-generation loop runnable after proposal review by producing isolated fake/local dry-run, build, runtime/manual evidence, and workflow summary artifacts without claiming real mod success.
Inputs: existing workflow graph, proposal review result, ArtifactStore
Files to modify: src/mod_agent/workflow/*, src/mod_agent/artifacts/* or adjacent fake runner modules, tests/unit/* or tests/integration/*
Artifacts produced:
  - dry_run_result.json with execution_mode=fake|local
  - build_result.json with execution_mode=fake|local|supplied_output
  - runtime_evidence.json or manual_evidence.json with execution_mode=fake|manual|supplied_output
  - workflow_summary.json
Trace events:
  - dry_run.fake_started
  - build.fake_started
  - runtime.manual_evidence_recorded
  - workflow.summary_written
Tests:
  - blocked review does not produce fake success artifacts
  - approved review produces explicitly fake/local artifacts
  - workflow_summary does not claim real gameplay/runtime success
  - inconclusive runtime evidence remains inconclusive
Acceptance criteria:
  - every fake/local/supplied-output artifact carries execution_mode
  - final report distinguishes blocked, fake-success, and inconclusive
  - no real file writes, real build, real runtime automation, or generated_mods mutation
Failure behavior: route to blocked or inconclusive, never claim real success
Out of scope: real patch application, real dotnet build, real game runtime verification
Dependencies: Q-001 done
Conflict checks: capability-first loop must not bypass evidence/review gates
Completed evidence:
  - src/mod_agent/workflow/graph.py now uses controlled fake nodes for dry_run_apply, build, collect_runtime_evidence, evaluate, and done
  - approved review path writes explicit fake execution artifacts with execution_mode=fake
  - blocked review path does not write dry_run_result, build_result, runtime_evidence, or workflow_summary
  - workflow_summary remains inconclusive and claims no real mod/build/runtime success
  - focused controlled-agent unit suite passed: 71 passed, 4 skipped
```


### Q-002: Define Knowledge Hub Text/Metadata Contracts

```text
Status: done
Module: KB
Spec refs: 37.3, 37.4, 45.4, 45.5.4
Coverage IDs: KB-002, MISS-002
Goal: Implement or align Document, Chunk, ChunkRecord metadata contracts with raw_text/canonical_text/text_for_retrieval.
Inputs: existing knowledge models
Files to modify: src/mod_agent/knowledge/*, tests/unit/*
Artifacts produced: none
Trace events: none
Tests: contract tests for source metadata and chunk metadata
Acceptance criteria: tests prove metadata inheritance and stable content hashes
Failure behavior: block downstream ingestion/index tasks
Out of scope: real loaders, BM25 ranking
Dependencies: Q-001, unless Q-001 refreshes the queue and supersedes this task
Conflict checks: do not remove existing compatible fields without migration reason
Completed evidence:
  - src/mod_agent/knowledge/models.py now defines Document, Chunk, ChunkRecord, and SourceSpan contracts
  - IndexedFile.to_document preserves raw_text, canonical_text, and text as separate fields
  - chunk_from_document inherits source metadata and adds chunk metadata, evidence kind, source hash, and stable content hash
  - chunk_record_from_chunk uses text_for_retrieval as text_for_embedding without mutating document raw/canonical evidence
  - tests/unit/test_knowledge_base.py covers metadata inheritance and stable hashes
  - focused Knowledge Base tests passed: 8 passed
  - focused controlled-agent unit suite passed: 77 passed, 4 skipped
```


### Q-003: Source Discovery and Ignore Rules

```text
Status: done
Module: KB
Spec refs: 37.2, 45.5.1, 45.18.3
Coverage IDs: KB-001, PERF-003
Goal: Discover supported knowledge sources and ignore forbidden/generated/cache paths.
Inputs: config/settings.yaml, repository fixtures
Files to modify: src/mod_agent/knowledge/source_registry.py or new source_discovery.py, tests/unit/*
Artifacts produced: none
Trace events: optional source_discovery metrics
Tests: discovery includes docs/code/artifacts/log patterns and excludes .git/.venv/bin/obj/generated outputs when configured
Acceptance criteria: stable source_id/content_hash for discovered files
Failure behavior: block loader pipeline
Out of scope: parsing file contents
Dependencies: Q-002
Conflict checks: generated_mods must not be touched unless explicitly configured for a safe fixture
Completed evidence:
  - src/mod_agent/knowledge/source_discovery.py now defines SourceDiscovery and DiscoveredSourceFile
  - SourceDiscovery classifies target_source, domain_note, prior_artifact, build_log, and runtime_log patterns
  - SourceDiscovery and SourceRegistry prune .git, .venv, bin, obj, node_modules, generated, generated_mods, and cache directories unless generated_mods is explicitly enabled
  - SourceDiscovery.from_config reads knowledge.indexable_extensions and safety.generated_mods_access
  - SourceRegistry.iter_files uses deterministic guarded walking instead of unguarded rglob
  - SourceRegistry.source_content_hash returns stable aggregate source hashes for incremental decisions
  - focused Knowledge Base tests passed: 12 passed
  - focused controlled-agent unit suite passed: 81 passed, 4 skipped
```


### Q-004: SQLite Metadata Store Contract

```text
Status: done
Module: KB, RET
Spec refs: 45.18.6
Coverage IDs: KB-004, MISS-003, PERF-003
Goal: Add SQLite-backed source/document/chunk/index_version persistence contract.
Inputs: KnowledgeSource, Document, Chunk contracts
Files to modify: src/mod_agent/knowledge/database.py or new sqlite store, tests/unit/*
Artifacts produced: temp sqlite db in tests
Trace events: none
Tests: write/read sources, documents, chunks, stable index version behavior
Acceptance criteria: failed index build does not replace stable index version
Failure behavior: block BM25 and retrieval integration
Out of scope: dense vector store
Dependencies: Q-002
Conflict checks: no writes outside configured temp/test data roots
Reason for next position:
  Q-003 completed guarded source discovery and aggregate source hashing.
  The next blocker is stable SQLite persistence for documents, chunks, and
  index versions before BM25 and symbol retrieval can bind to chunk ids safely.
Completed evidence:
  - src/mod_agent/knowledge/models.py now defines KnowledgeSourceSnapshot, KnowledgeDocumentRecord, KnowledgeChunkRecord, and IndexVersion contracts
  - src/mod_agent/knowledge/database.py now creates knowledge_sources, knowledge_documents, knowledge_chunks, and index_versions tables
  - KnowledgeDatabase can upsert/read collection-scoped sources, documents, and chunks
  - KnowledgeDatabase records building, stable, and failed index versions
  - failed index versions do not replace the newest stable index version
  - repeated chunk upsert for the same collection/index_version/chunk_id remains a single persisted row
  - focused Knowledge Base tests passed: 14 passed
  - focused controlled-agent unit suite passed: 83 passed, 4 skipped
```


### Q-005: BM25 Inverted Index V1

```text
Status: done
Module: RET
Spec refs: 37.4, 45.8, 45.18.6
Coverage IDs: RET-003, MISS-004
Goal: Implement V1 BM25 lexical sparse inverted index over chunks.
Inputs: Chunk records, SQLite metadata store
Files to modify: src/mod_agent/evidence or knowledge index modules, tests/unit/*
Artifacts produced: temp index db in tests
Trace events: bm25_index metrics optional
Tests: exact keyword/class/error query returns expected chunk_id, score, hit terms
Acceptance criteria: BM25 does not require embedding or vector store
Failure behavior: V1 retrieval is not acceptable without BM25 unless deterministic/symbol explicitly covers the task
Out of scope: neural sparse vector
Dependencies: Q-004
Conflict checks: do not confuse BM25 inverted index with vector sparse encoding
Reason for next position:
  Q-004 completed the SQLite chunk and index-version contract required for
  lexical retrieval state. BM25 is the next V1 retrieval blocker before dense,
  rerank, multimodal, or MCP scaling work.
Completed evidence:
  - src/mod_agent/knowledge/bm25_indexer.py now defines BM25Indexer with index, query, and query_text methods
  - src/mod_agent/knowledge/database.py now creates bm25_terms and bm25_postings tables
  - BM25Indexer replaces terms/postings for one collection_id/index_version and returns BM25IndexResult
  - BM25 query returns BM25Hit with score, hit_terms, term_frequencies, chunk_id, source_path, span, excerpt, and index_version
  - DeterministicEvidenceRetriever queries the latest stable index version and can emit retrieval_method=bm25 evidence
  - BM25 remains a local inverted index and does not require embedding, vector store, or neural sparse encoding
  - focused Knowledge/Evidence tests passed: 22 passed
  - focused controlled-agent unit suite passed: 85 passed, 4 skipped
```


### Q-006: Symbol Index V1

```text
Status: done
Module: RET, KB
Spec refs: 37.4, 45.8, 45.9
Coverage IDs: RET-002, MISS-005
Goal: Implement class/method/config symbol indexing for code evidence.
Inputs: Chunk metadata and simple symbol annotations
Files to modify: src/mod_agent/knowledge/symbol_indexer.py, tests/unit/*
Artifacts produced: temp sqlite db in tests
Trace events: symbol_index metrics optional
Tests: symbol lookup returns source span and chunk_id
Acceptance criteria: review-risk evidence can prefer exact/symbol hits
Failure behavior: degrade to BM25 only with trace warning
Out of scope: full AST parser
Dependencies: Q-002, Q-004
Conflict checks: keep parser lightweight and deterministic for V1
Reason for next position:
  Q-005 completed BM25 lexical retrieval. Symbol V1 is the next required
  high-trust retrieval route before dense, fusion, or rerank work.
Completed evidence:
  - src/mod_agent/knowledge/database.py now creates symbol_index with collection_id, index_version, symbol, symbol_kind, chunk_id, source_path, start_line, end_line, and metadata_json
  - src/mod_agent/knowledge/symbol_indexer.py now builds chunk-bound symbol rows from persisted chunk metadata
  - SymbolIndexer.search_chunk_symbols returns exact symbol hits with chunk_id and source span
  - DeterministicEvidenceRetriever prefers stable chunk symbol_index evidence before legacy file-level symbols
  - chunk-bound symbol evidence keeps retrieval_method=symbol_exact so readiness can treat it as high-trust hook/source evidence
  - focused Knowledge/Evidence tests passed: 24 passed
  - focused controlled-agent unit suite passed: 87 passed, 4 skipped
```


### Q-007: EvidencePack Timing and Missing Evidence Fields

```text
Status: done
Module: RET, OBS
Spec refs: 37.5, 45.4, 45.9, 45.10
Coverage IDs: RET-007, RET-008, RET-010, OBS-001, MISS-001
Goal: Extend EvidencePack and retrieval results with retrieval_methods_used, missing_evidence, timing.
Inputs: existing evidence models/retriever/readiness
Files to modify: src/mod_agent/evidence/models.py, retriever/readiness tests
Artifacts produced: evidence_pack JSON in tests if store exists
Trace events: retrieval.* metrics
Tests: EvidencePack serializes timing and disabled retrieval modes
Acceptance criteria: Graph can consume EvidencePack without knowing retriever internals
Failure behavior: block graph retrieval integration
Out of scope: dashboard rendering
Dependencies: Q-005 or can proceed with fake retriever
Conflict checks: no direct Graph dependency on BM25/dense internals
Reason for next position:
  Q-002A made the workflow runnable through controlled fake execution.
  The next blocker for reliable branching and audit is EvidencePack observability:
  retrieval methods used, missing evidence, disabled modes, and timing.
Completed evidence:
  - EvidencePack dataclass now carries retrieval_methods_used, missing_evidence, disabled_modes, timing, and trace_refs
  - evidence_pack artifact contract requires these fields
  - readiness blockers derive structured missing_evidence entries
  - deterministic retriever records query/symbol/text/readiness/total timing
  - deterministic retriever records disabled BM25/dense/fusion/rerank/neural_sparse modes
  - graph evidence_summary consumes the generic EvidencePack observability fields
  - stub retrieve_evidence payload satisfies the upgraded evidence_pack contract
  - focused Q-007 test subset passed: 32 passed
  - focused controlled-agent unit suite passed: 72 passed, 4 skipped
```


### Q-008: Retrieval Regression Query List

```text
Status: done
Module: EVAL, RET
Spec refs: 41.5, 45.14
Coverage IDs: EVAL-001
Goal: Add versioned golden query list schema and minimal evaluator for evidence hit/source coverage.
Inputs: tests/fixtures
Files to modify: tests/fixtures/*, src/mod_agent/evaluation/*, tests/unit/*
Artifacts produced: eval_report JSON in tests
Trace events: eval.run_started/eval.run_finished optional
Tests: evaluator fails when required evidence is missing
Acceptance criteria: false_continue high-risk cases can be represented
Failure behavior: regression gate blocks phase completion
Out of scope: Ragas integration
Dependencies: Q-007
Conflict checks: do not use answer-quality metrics as primary success criteria
Completion evidence:
  - src/mod_agent/evaluation/retrieval_regression.py added a versioned golden
    query loader, deterministic retrieval evaluator, metrics, and eval_report payload.
  - tests/fixtures/retrieval/golden_queries.json added the first query_set_id.
  - tests/unit/test_retrieval_regression.py verifies fixture pass, eval_report
    artifact compatibility, missing required evidence failure, and false_continue
    high-risk representation.
  - focused Q-008 test subset passed: 12 passed.
```


### Q-009: MCP Async Job Contract

```text
Status: done
Module: MCP, OBS
Spec refs: 45.12.1, 45.18
Coverage IDs: MCP-002, MISS-012
Goal: Define job_id/status/artifact_refs contract for long-running tools.
Inputs: existing CLI/MCP skeleton
Files to modify: src/mod_agent/mcp or tools modules, tests/unit/*
Artifacts produced: job status artifact if store integrated
Trace events: job.queued, job.started, job.finished
Tests: start job returns quickly; get status is read-only; cancellation marks incomplete
Acceptance criteria: ingestion/eval/build can be represented as async jobs
Failure behavior: long tasks must not block request-response path
Out of scope: real background worker pool
Dependencies: ART level 3 recommended
Conflict checks: no hidden patch/build side effects
Completion evidence:
  - src/mod_agent/mcp/jobs.py defines JobRecord, JobArtifactRef, AsyncJobStore,
    and structured MCP/API job responses.
  - src/mod_agent/mcp/tools.py defines safe report-only/read-only async job
    tool contracts for start_ingestion, get_job_status, run_retrieval_eval,
    and build_mod.
  - job_status artifact contract is registered for shared artifact-store use.
  - tests/unit/test_mcp_async_jobs.py verifies immediate queued response,
    read-only status lookup, incomplete partial artifacts on cancellation,
    artifact contract compatibility, hidden dangerous tools, and job_id output.
  - focused Q-009 test subset passed: 24 passed.
```


### Q-010: Reconcile Workflow Retrieval Integration

```text
Status: done
Module: WF, RET, OBS
Spec refs: 37.5, 41.4, 49
Coverage IDs: WF-003, RET-007, RET-010, OBS-001
Goal: Verify current retrieve_evidence graph integration against the spec and update the queue rather than reimplementing work that already exists.
Inputs: current workflow graph, EvidencePack models, retriever/readiness tests
Files to modify: src/mod_agent/workflow/*, tests/unit/test_workflow_graph.py or integration test
Artifacts produced: evidence_pack artifact if ArtifactStore is wired
Trace events: retrieval node started/finished
Tests:
  - sufficient evidence continues
  - missing required evidence routes blocked
  - graph does not depend directly on BM25/dense internals
Acceptance criteria:
  - current implementation remains classified as partial until EvidencePack timing/missing_evidence and stronger trace/artifact fields exist
  - no duplicate graph wiring task is created
  - graph does not generate proposal when readiness insufficient
Failure behavior: block proposal path
Out of scope: real patch application
Dependencies: Q-001; Q-007 if EvidencePack fields are missing
Conflict checks: evidence-before-patch must hold
Completed evidence:
  - retrieve_evidence finished trace includes readiness, can_generate_patch, retrieval_methods_used, missing_evidence_count, disabled_modes, and timing
  - retrieve_evidence finished trace carries the evidence_pack artifact ref
  - insufficient evidence blocks before implementation_plan
  - insufficient evidence does not create patch_proposal, proposal_review, dry_run_result, build_result, or runtime_evidence
  - no duplicate graph retrieval wiring was introduced
  - focused Q-010 test subset passed: 31 passed
  - focused controlled-agent unit suite passed: 74 passed, 4 skipped
```


### Q-011: Git Decision-To-Commit Binding

```text
Status: done
Module: GIT, ART, WF
Spec refs: User Git requirement, 49.3
Coverage IDs: GIT-001, GIT-002, MISS-009
Goal: Bind workflow decisions, artifact refs, and code changes to Git commit metadata without auto-committing on next-stage commands.
Inputs: existing git wrapper/change-record tests, ArtifactStore, workflow artifact refs
Files to modify: src/mod_agent/git*, src/mod_agent/workflow/*, tests/unit/*
Artifacts produced: git_change_record JSON in tests
Trace events: git.change_record_created optional
Tests: change record links decision artifacts to commit metadata; no commit occurs unless explicitly requested
Acceptance criteria: audit/replay metadata can identify which artifacts justified a change
Failure behavior: block commit binding but keep report-only workflow runnable
Out of scope: remote push automation
Dependencies: ART-001, ART-002, Q-002A
Conflict checks: do not commit, tag, push, or mutate user git state in ordinary tests
Completed evidence:
  - GitChangeRecord now records structured decision_artifacts and patch_artifacts with artifact_type, path, and artifact_hash
  - workflow binding helpers select stage-specific decision artifacts from ModAgentState and bind patch_proposal when present
  - write_workflow_change_record persists git_change_record artifacts through ArtifactStore without creating commits
  - injected-command tests verify no git commit command is executed during workflow change-record writing
  - focused Git/artifact tests passed: 16 passed, 4 skipped
  - focused controlled-agent unit suite passed: 100 passed, 4 skipped
```


### Q-012: Manual And Supplied Runtime Evidence Contract

```text
Status: done
Module: RUN, ART, WF
Spec refs: 15.2, 15.3, 49.4.3
Coverage IDs: EXEC-005, EXEC-006, MISS-007
Goal: Define manual/supplied runtime evidence artifacts that can remain inconclusive or prove acceptance without pretending fake evidence is real.
Inputs: runtime_evidence artifact, workflow fake runtime node, EvidencePack readiness rules
Files to modify: src/mod_agent/workflow/*, src/mod_agent/artifacts/*, tests/unit/*
Artifacts produced: manual_evidence or runtime_evidence JSON
Trace events: runtime.manual_evidence_recorded
Tests: supplied output can be recorded; inconclusive output does not claim runtime success; accepted output requires explicit evidence fields
Acceptance criteria: runtime evidence source, execution_mode, acceptance status, and raw supplied output are separated
Failure behavior: route to inconclusive or blocked
Out of scope: launching the game or reading live game directories
Dependencies: Q-002A
Conflict checks: build success and image captions cannot prove gameplay success
Completed evidence:
  - src/mod_agent/runtime/evidence.py defines runtime evidence payload builders for fake, manual, and supplied-output evidence
  - runtime_evidence and manual_evidence artifact contracts now require evidence source, execution_mode, startup_loaded, gameplay_behavior_verified, evidence_items, verification_status, acceptance_status, raw_supplied_output, and claims_real_runtime_success
  - verified manual/supplied evidence is blocked unless startup, gameplay behavior, and explicit acceptance evidence are present
  - fake runtime evidence remains inconclusive and cannot claim real runtime success
  - workflow fake runtime node now emits the upgraded runtime evidence contract
  - focused Q-012 test subset passed: 30 passed
  - focused controlled-agent unit suite passed: 105 passed, 4 skipped
```


### Q-013: Real Build Adapter Contract

```text
Status: done
Module: BUILD, ART, WF
Spec refs: 14, 14.4, 49.4.2
Coverage IDs: EXEC-003, EXEC-004, MISS-006
Goal: Add a controlled build adapter interface and build error classifier while keeping real command execution behind explicit configuration and approval.
Inputs: build_result artifact, permission policy, config/settings.yaml
Files to modify: src/mod_agent/build* or workflow build modules, tests/unit/*
Artifacts produced: build_result JSON
Trace events: build.started, build.finished, build.failed_classified
Tests: fake/local/supplied build remains explicit; classifier extracts error category from supplied compiler output
Acceptance criteria: build adapter can report success/failure without claiming runtime behavior
Failure behavior: build failure routes toward repair planning with classified errors
Out of scope: default real dotnet execution in tests
Dependencies: Q-002A, Q-012 recommended
Conflict checks: no hidden external process execution
Completed evidence:
  - src/mod_agent/build/adapter.py defines BuildProfile, BuildProfileRegistry, BuildAdapter, BuildResult, BuildDiagnostic, and BuildErrorClassifier
  - build_result artifact contract now requires structured build fields, diagnostics, error_class, repair_handoff, execution_mode, and claims_real_build_success
  - local build execution is skipped unless allow_execution is explicit; unit tests use an injected runner and do not execute dotnet
  - supplied build output can be classified without running a command
  - fake graph build now emits the upgraded build_result contract and still cannot claim real build success
  - .gitignore now anchors runtime output directories so src/mod_agent/artifacts and src/mod_agent/build are visible to git status
  - focused Q-013 test subset passed: 40 passed
  - focused controlled-agent unit suite passed: 119 passed, 4 skipped
```


### Q-014: Repair Loop And Retry Budget

```text
Status: done
Module: REPAIR, WF, REVIEW
Spec refs: 16, 49.4.4
Coverage IDs: EXEC-009, EXEC-010, MISS-008
Goal: Add repair plan artifacts and retry-budget routing for build/runtime failures, with every repair proposal re-entering review.
Inputs: build_result, runtime_evidence, proposal_review, permission policy
Files to modify: src/mod_agent/workflow/*, src/mod_agent/planning/*, tests/unit/*
Artifacts produced: repair_plan JSON
Trace events: repair.plan_created, repair.retry_budget_exhausted
Tests: failed build creates repair_plan; retry budget blocks infinite loops; repair proposal re-enters review gate
Acceptance criteria: repair scope is bound to real failure evidence
Failure behavior: exhausted budget routes blocked with evidence
Out of scope: LLM patch generation
Dependencies: Q-013, Q-012
Conflict checks: no direct repair apply without review
Completed evidence:
  - src/mod_agent/repair/planner.py defines RepairPlanner, RepairPlan, stable repair ids, retry budget handling, and RepairPatchProposalBuilder.
  - repair_plan artifact contract now requires failure evidence, hypothesis, minimal_changes, retry_count, retry_budget, retry_exhausted, allowed_next_stage, and blockers.
  - build and explicit runtime failure routes now enter create_repair_plan.
  - non-exhausted repair plans re-enter generate_patch_proposal, then ProposalReviewer; no repair path applies changes directly.
  - retry budget exhaustion routes blocked with RETRY_BUDGET_EXHAUSTED.
  - focused Q-014 tests passed: 33 passed.
  - focused controlled-agent suite passed: 125 passed, 4 skipped.
```


### Q-015: Checkpoint Interrupt Resume Contract

```text
Status: done
Module: WF, ART
Spec refs: 5.6, 49.1.5
Coverage IDs: WF-004, MISS-015
Goal: Add checkpoint, interrupt, resume, and stale resume contracts for long-running human-controlled workflows.
Inputs: workflow state, artifact freshness, permission gates
Files to modify: src/mod_agent/workflow/*, tests/unit/*
Artifacts produced: checkpoint or resume_report JSON
Trace events: workflow.checkpointed, workflow.resumed, workflow.resume_blocked
Tests: resume continues from a valid checkpoint; stale upstream artifact blocks unsafe resume
Acceptance criteria: human approval points can pause without losing artifact lineage
Failure behavior: stale or missing checkpoint routes blocked
Out of scope: distributed checkpoint backend
Dependencies: ART-002, Q-010
Conflict checks: resume must not bypass review or permission gates
Completed evidence:
  - src/mod_agent/workflow/interrupts.py defines InterruptRequest, ResumePayload, ResumeDecision, and ResumeValidator.
  - src/mod_agent/workflow/checkpointing.py defines CheckpointPolicy, WorkflowCheckpoint, ResumeReport, and WorkflowCheckpointStore.
  - workflow_checkpoint and resume_report artifact contracts are registered.
  - build_graph accepts LangGraph checkpointer, interrupt_before, and interrupt_after parameters while preserving the default path.
  - valid resume payloads write resume_report artifacts with applied_updates.
  - stale upstream artifact hashes block resume with STALE_RESUME_REJECTED.
  - double resume is rejected with DOUBLE_RESUME_REJECTED.
  - focused Q-015 tests passed: 32 passed.
  - focused controlled-agent suite passed: 131 passed, 4 skipped.
Joint Q-014/Q-015 smoke evidence:
  - tests/unit/test_repair_checkpoint_smoke.py verifies the build_result -> repair_plan -> patch_proposal -> proposal_review -> workflow_checkpoint -> resume_report chain.
  - review checkpoint resume applies only approvals.review and does not bypass proposal review.
  - stale repair_plan changes after checkpoint block resume with STALE_RESUME_REJECTED.
  - repeated resume blocks with DOUBLE_RESUME_REJECTED.
  - focused Q-014/Q-015 smoke tests passed: 13 passed.
  - focused controlled-agent suite passed: 133 passed, 4 skipped.
```


### Q-016: Dashboard Trace Viewer MVP

```text
Status: done
Module: OBS, ART
Spec refs: 19, 39, 49.2.2
Coverage IDs: OBS-001, OBS-002, OBS-003, ART-003, MISS-016
Goal: Add read-only projections for workflow trace, evidence summary, artifact DAG, and bottleneck timing.
Inputs: artifact envelopes, workflow trace events, EvidencePack timing
Files to modify: src/mod_agent/dashboard* or read-model modules, tests/unit/*
Artifacts produced: dashboard_projection JSON in tests
Trace events: none
Tests: projection exposes node order, artifact refs, stale status, retrieval timing, and blocked reason
Acceptance criteria: process black-box state can be inspected without mutating workflow state
Failure behavior: missing artifacts are shown as missing, not fabricated
Out of scope: polished UI
Dependencies: Q-007, Q-010, ART-001
Conflict checks: dashboard is read-only
Completed evidence:
  - src/mod_agent/dashboard/projections.py defines DashboardProjectionBuilder
    as a read-only artifact/trace projection service.
  - build_feature_projection returns workflow_trace, artifact_dag,
    evidence_summary, bottlenecks, blockers, and missing_artifacts.
  - artifact DAG nodes include dashboard_projection fields, upstream refs,
    freshness status, stale reasons, blockers, and trace_refs.
  - bottleneck summaries are derived from trace details timing and
    EvidencePack timing without mutating workflow state or writing artifacts.
  - missing expected artifacts are represented as missing, not fabricated.
  - focused Q-016 tests passed: 25 passed.
  - focused controlled-agent suite passed: 135 passed, 4 skipped.
```


### Q-017: Domain Adapter And GTFO GameProfile Contracts

```text
Status: done
Module: DOM, REVIEW
Spec refs: 9.2, 9.3, 9.4, 9.5, 43.1, 50.8
Coverage IDs: DOM-001, DOM-002, DOM-003, DOM-004, DOM-005, DOM-006, MISS-014
Goal: Add generic DomainAdapter and first GTFO GameProfile contracts without hardcoding GTFO behavior into workflow modules.
Inputs: permission policy, proposal review, source discovery metadata
Files to modify: src/mod_agent/domain* or adapters modules, tests/unit/*
Artifacts produced: none
Trace events: domain.profile_selected optional
Tests: unknown profile blocks game-specific runtime patching; GTFO profile exposes risk taxonomy and forbidden paths
Acceptance criteria: future Unity/BepInEx/Harmony profiles can be added without changing graph logic
Failure behavior: unknown domain routes blocked for domain-specific actions
Out of scope: real GTFO plugin implementation
Dependencies: REVIEW-001, Q-003
Conflict checks: GTFO-specific behavior must remain behind the profile boundary
Completed evidence:
  - src/mod_agent/domain/models.py defines DomainAdapter, DomainProfile,
    DomainRoute, EvidenceQuery, RuntimeProfile, VerificationPlan,
    DomainReviewPolicy, and DomainAdapterRegistry contracts.
  - src/mod_agent/domain/gtfo.py defines the first GTFO / BepInEx / IL2CPP /
    HarmonyX GameProfile adapter, risk taxonomy, forbidden paths, source
    definitions, build profile, runtime profile, and verification strategy.
  - src/mod_agent/domain/unsupported.py defines an unsupported-domain adapter
    that allows generic planning but blocks game-specific runtime changes.
  - ProposalReviewer accepts an optional domain_policy and blocks unsupported
    GameProfile runtime changes plus domain forbidden/out-of-root paths.
  - tests/unit/test_domain_adapter.py verifies GTFO profile fields, risk
    taxonomy, unknown profile blocking, forbidden paths, safe roots, and
    adapter registry extension.
  - focused Q-017 tests passed: 20 passed.
  - focused controlled-agent suite passed: 141 passed, 4 skipped.
```


### Q-018: Runtime Screenshot Registry Contract

```text
Status: completed
Module: MM, RUN, ART
Spec refs: 15.4, 38.1, 38.4
Coverage IDs: EXEC-007, MM-001, MM-004, MISS-010
Goal: Add screenshot metadata registry contracts without using screenshots as proof of gameplay success.
Inputs: runtime_evidence contract, ArtifactStore, future multimodal source metadata
Files to modify: src/mod_agent/runtime/*, src/mod_agent/artifacts/*, tests/unit/*
Artifacts produced: screenshot_registry or runtime_evidence JSON in tests
Trace events: runtime.screenshot_registered optional
Tests: screenshot metadata can be recorded; missing caption is allowed; screenshot alone cannot verify acceptance
Acceptance criteria: screenshot file metadata is separated from caption and verification status
Failure behavior: low or missing visual evidence remains inconclusive
Out of scope: real screenshot capture and vision caption generation
Dependencies: Q-012
Conflict checks: image evidence must not claim runtime success by itself
Completed evidence:
  - src/mod_agent/runtime/screenshots.py defines ScreenshotMetadata,
    ScreenshotRegistryError, build_screenshot_metadata,
    build_screenshot_registry_payload, and screenshot_registry_to_runtime_item.
  - src/mod_agent/artifacts/registry.py registers screenshot_registry as a
    runtime_evidence-stage artifact consumed by evaluate, repair_plan, and
    dashboard.
  - screenshot_registry payloads separate file metadata, caption fields,
    verification_status, acceptance_status, and claims_real_runtime_success.
  - screenshot_registry_to_runtime_item strips supports_acceptance and
    confidence so a screenshot cannot upgrade runtime_evidence acceptance.
  - tests/unit/test_runtime_screenshots.py verifies missing captions,
    captioned visual evidence, ArtifactStore writes, required fields, and
    non-acceptance conversion.
  - tests/unit/test_artifact_contract.py verifies the screenshot_registry
    artifact contract.
  - focused Q-018 tests passed: 25 passed.
  - affected controlled-agent suite passed: 111 passed, 4 skipped.
  - broader test command including tests/unit/test_planning.py failed during
    collection on an existing planning/workflow circular import, before Q-018
    tests ran.
```


### Q-019: Agent Decision Quality Evaluation Contract

```text
Status: completed
Module: EVAL, WF, REVIEW
Spec refs: 18.3, 41.5, 49.6, 50.7
Coverage IDs: EVAL-002, EVAL-003, EVAL-004, MISS-011
Goal: Define evaluation contracts for route accuracy, evidence sufficiency, review correctness, and baseline comparison.
Inputs: retrieval regression reports, workflow artifacts, proposal_review artifacts
Files to modify: src/mod_agent/evaluation/*, tests/unit/*, tests/fixtures/*
Artifacts produced: eval_report JSON in tests
Trace events: eval.agent_quality_started, eval.agent_quality_finished optional
Tests: baseline metrics serialize; false continue/review miss cases fail the gate
Acceptance criteria: metrics are adapted to code-agent decisions, not generic chatbot answers
Failure behavior: missing baseline blocks improvement claims
Out of scope: external benchmark services
Dependencies: Q-008, Q-010, REVIEW-001
Conflict checks: do not claim measured quality improvement without baseline evidence
Completed evidence:
  - src/mod_agent/evaluation/agent_quality.py defines AgentQualityCase,
    AgentQualityExpected, AgentQualityObservation, AgentQualityEvaluator,
    AgentQualityReport, and load_agent_quality_suite.
  - tests/fixtures/evaluation/agent_quality_cases.json defines a versioned
    local suite with baseline metrics, evidence-bound approval, missing API
    blocking, and repair routing cases.
  - tests/unit/test_agent_quality_eval.py verifies report serialization,
    eval_report artifact compatibility, false-continue hard failure,
    review-miss hard failure, optional baseline claim limits, and required
    baseline failure.
  - Report metrics include route_accuracy, risk_classification_accuracy,
    evidence_sufficiency, review_correctness, repair_quality, faithfulness,
    answer_relevancy, context_precision, false_continue_rate,
    review_miss_rate, hard_fail_rate, and mean_score.
  - claims_allowed and claims_forbidden enforce the baseline rule: without
    baseline metrics the system may claim design auditability/control/review,
    not measured accuracy or reliability improvement.
  - focused Q-019 tests passed: 25 passed.
  - affected controlled-agent suite passed: 117 passed, 4 skipped.
```

## Review Repair Queue

```text
Status: active
Source review: C:/Users/10160/Desktop/ai学习/mod_agent_full_issue_summary.md
Policy:
  - R tasks supersede ordinary Q feature work until R-001 through R-007 are
    done, blocked with exact evidence, downgraded with exact evidence, or
    explicitly waived by the user.
  - Each R task must be closed through the normal small-loop gate: code/test
    inspection, implementation, focused tests, affected tests when shared
    contracts change, diff audit, control-doc update, git decision, stop.
  - P0/P1 findings must not be hidden by broad "next phase" progress.
  - Q-020 and later feature work remain queued but are blocked behind the
    active P0/P1 repair queue.
```


### R-001: Graph Domain Policy Wiring

```text
Status: completed
Module: WF, REVIEW, DOM
Spec refs: 9.5, 11, 49.3.4, 50.8
Source finding: P0-002
Goal: Ensure graph-level review_proposal supplies DomainReviewPolicy to ProposalReviewer when the workflow has a domain/game profile.
Inputs: workflow state, domain adapter route/profile, patch_proposal, evidence_pack
Files to modify: src/mod_agent/workflow/graph.py, src/mod_agent/proposal/reviewer.py if needed, tests/unit/*
Artifacts produced: proposal_review JSON in tests
Trace events: review.proposal_checked or existing review trace event
Tests: graph review blocks unsupported/high-risk domain proposals when domain policy is required
Acceptance criteria: domain policy cannot be bypassed by entering review through the graph
Failure behavior: missing required domain policy blocks the proposal with a clear blocker
Out of scope: adding new game profiles
Dependencies: Q-017
Conflict checks: GTFO-specific rules must remain inside domain adapter/policy, not generic graph code
Completed evidence:
  - build_graph now creates a default domain adapter registry when no registry
    is supplied and passes a resolved DomainReviewPolicy into review_proposal.
  - _run_review_proposal passes domain_policy to ProposalReviewer without
    embedding GTFO-specific rules in graph code.
  - Unknown registered domain review uses UnsupportedDomainAdapter policy, so
    high-risk runtime changes block with domain_profile findings.
  - Default graph construction now blocks unsupported-domain high-risk runtime
    proposals before dry-run.
  - tests/unit/test_workflow_graph.py adds
    test_default_graph_uses_domain_policy_for_unsupported_domain.
  - focused R-001 tests passed: 16 passed.
  - affected workflow/review/repair/checkpoint tests passed: 20 passed.
```


### R-002: Evidence Pack Required For Evidence-Bound Review

```text
Status: completed
Module: REVIEW, ART
Spec refs: 6, 11, 49.3.4
Source finding: P0-003
Goal: Make ProposalReviewer block evidence-bound proposals when evidence_pack is missing or stale instead of silently weakening validation.
Inputs: patch_proposal, evidence_pack, artifact refs
Files to modify: src/mod_agent/proposal/reviewer.py, tests/unit/test_proposal_review.py or graph tests
Artifacts produced: proposal_review JSON in tests
Trace events: review.evidence_binding_failed optional
Tests: direct reviewer API blocks missing evidence_pack for proposals with evidence_refs
Acceptance criteria: every evidence_ref is checked against a real evidence_pack or the review blocks
Failure behavior: proposal_review status is blocked with exact missing-evidence reason
Out of scope: changing retrieval ranking
Dependencies: R-001 optional; can run independently for direct reviewer API
Conflict checks: repair proposals still validate against repair_plan evidence when that is the approved evidence source
Completed evidence:
  - ProposalReviewer blocks evidence-bound proposals when neither evidence_pack
    nor repair_plan provides evidence ids.
  - Evidence refs that cannot be matched to the approved evidence source block
    with evidence_binding findings.
  - repair_plan remains an approved evidence source for repair proposals.
  - tests/unit/test_proposal_review.py adds
    test_reviewer_blocks_evidence_bound_proposal_without_evidence_pack.
  - tests/unit/test_repair_loop.py verifies repair proposal review can pass
    without evidence_pack when repair_plan evidence refs match.
  - focused R-002 tests passed: 13 passed.
  - affected workflow/domain/checkpoint tests passed: 24 passed.
```


### R-003: Separate Evidence Source From Edit Target

```text
Status: completed
Module: PLAN, PROP, REVIEW
Spec refs: 9, 10, 49.3
Source finding: P0-004
Goal: Split evidence_source_path from edit_target_path so implementation_plan cannot use a retrieval source as a write target by default.
Inputs: feature_spec, evidence_pack, source discovery metadata
Files modified:
  src/mod_agent/planning/models.py
  src/mod_agent/planning/implementation_plan.py
  src/mod_agent/proposal/builder.py
  src/mod_agent/artifacts/registry.py
  src/mod_agent/workflow/__init__.py
  src/mod_agent/workflow/nodes.py
  tests/unit/test_planning.py
  tests/unit/test_proposal_review.py
  tests/unit/test_artifact_contract.py
  tests/unit/test_dashboard_projection.py
  tests/unit/test_git_repository.py
  docs/IMPLEMENTATION_QUEUE.md
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md
Completed evidence:
  - ImplementationPlan payloads now include evidence_source_paths separate from target_files.
  - ImplementationPlanner treats source_type target_source as the only current editable evidence source type.
  - Read-only evidence sources such as decompiled_api are preserved in evidence_source_paths but do not become target_files.
  - Missing editable targets produce EDIT_TARGET_UNRESOLVED blockers in implementation planning.
  - Proposed changes carry evidence_source_path and edit_target_path explicitly.
  - PatchProposalBuilder refuses non-blocking plans that lack edit_target_path before reviewer runs.
  - ProposalReviewer was kept as the final rejection gate; it was not given edit-target resolution responsibility.
  - workflow.__init__ now imports build_graph lazily to remove a planning/workflow import cycle exposed by focused planning tests.
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
Files modified:
  src/mod_agent/build/adapter.py
  src/mod_agent/artifacts/registry.py
  tests/unit/test_build_adapter.py
  tests/unit/test_artifact_contract.py
  docs/IMPLEMENTATION_QUEUE.md
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md
Completed evidence:
  - BuildResult payloads now include verified_artifacts and artifact_verification.
  - Local real builds with exit_code 0 must verify each expected_artifacts entry before claims_real_build_success can be true.
  - Expected artifact verification rejects absolute paths, traversal paths, missing paths, and non-file paths.
  - Verified artifacts record path, resolved_path, sha256, size_bytes, and mtime.
  - Missing or unsafe expected artifacts produce build_status artifact_verification_failed and repair_handoff failure_evidence_refs containing artifact_verification.
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
Files modified:
  src/mod_agent/artifacts/store.py
  src/mod_agent/workflow/graph.py
  src/mod_agent/workflow/checkpointing.py
  tests/unit/test_artifact_store.py
  tests/unit/test_artifact_contract.py
  tests/unit/test_repair_checkpoint_smoke.py
  docs/IMPLEMENTATION_QUEUE.md
  docs/SPEC_COVERAGE_MATRIX.md
  docs/PROJECT_STATE.md
  docs/audits/LOOP_HISTORY.md
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
