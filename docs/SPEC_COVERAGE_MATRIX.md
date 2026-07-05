# Spec Coverage Matrix

This file tracks detailed coverage of `DEV_SPEC.md`.

It is not a replacement for `DEV_SPEC.md`, `PROJECT_STATE.md`, or `IMPLEMENTATION_QUEUE.md`.
It is the bridge between the full specification and small implementation loops.

Last updated: 2026-07-05

## Status Values

```text
not_started  Spec requirement is recognized but no project-specific implementation exists.
queued       Requirement is assigned to a queue task.
partial      Some implementation exists, but required contract/test/integration is incomplete.
implemented  Code exists with focused tests.
tested       Code exists, focused tests pass, and state/queue documents reference it.
verified     E2E, regression, performance, or real-world evidence proves the behavior.
deferred     Explicitly postponed by V1 scope.
superseded   Replaced by a newer spec decision.
blocked      Cannot proceed until named evidence, dependency, or user input exists.
```

## Coverage Rules

```text
1. A row is not complete because code exists.
2. A row is not complete because an imported RAG skeleton claims it.
3. Controlled fake/local/supplied-output execution is valid only when execution_mode is explicit.
4. Build success never proves runtime behavior.
5. Image caption evidence never proves gameplay success.
6. Dense/vector/multimodal work must not outrank required V1 evidence contracts.
7. Queue tasks must reference this matrix when they close or defer rows.
```

## Control Documents

| Document | Responsibility |
| --- | --- |
| `DEV_SPEC.md` | Full requirement source |
| `docs/SPEC_COVERAGE_MATRIX.md` | Requirement-level coverage ledger |
| `docs/PROJECT_STATE.md` | Current factual project state |
| `docs/IMPLEMENTATION_QUEUE.md` | Next executable small loops |
| `docs/EXECUTION_CONTROL_GUIDE.md` | How future agents select and close work |

## Product And Governance Coverage

| Coverage ID | Spec Refs | Requirement | Module | Status | Queue / Next | Current Evidence Or Gap |
| --- | --- | --- | --- | --- | --- | --- |
| GOV-001 | 0.0, 50.4 | Capability-first controlled code-generation loop outranks passive RAG expansion | WF | tested | Q-001, Q-002A done | Queue now prioritizes controlled fake execution before deeper Knowledge Hub work |
| GOV-002 | 0.0B, 2.1, 50.8 | Project is a vertical code development Agent, not a GTFO-only script set | DOM | partial | Q-017 done; future onboarding workflow | GTFO rules now live behind a DomainAdapter/GameProfile boundary; full onboarding workflow and capability report remain incomplete |
| GOV-003 | 0.5, 44, 50.7 | Claims must be backed by artifact/test evidence | OBS | partial | ongoing per-loop rule; R-008 done | Q-002A prevents fake execution from claiming real success; R-008 adds explicit workflow_completion_status=fake_execution_completed and requested_behavior_status=not_verified while keeping real-success claims false |
| GOV-004 | 42, 48.2 | Detailed spec requirements need durable tracking | OBS | implemented | this file | This matrix now records requirement-level coverage and gaps |
| GOV-005 | 50.6 | Token and context budget policy must preserve project continuity | OBS | partial | future context-pack task | Execution guide and state files exist; no automated context pack yet |
| GOV-006 | 48.12, 49.8 | ADR and glossary backlog must exist for core design choices | OBS | not_started | future ADR task | No ADR/glossary files tracked yet |
| GOV-007 | 42, 48.2, 50.7 | External review findings must enter the execution queue before feature expansion | OBS | implemented | Q-022 completed; queue refresh ready | `docs/IMPLEMENTATION_QUEUE.md`, `docs/PROJECT_STATE.md`, `docs/EXECUTION_CONTROL_GUIDE.md`, and `.agents/skills/auto-coder/SKILL.md` require unresolved P0/P1 review findings to outrank ordinary Q feature work; the post R-009-HARDENING-001 refresh found no active Review Repair Queue blocker before Q-020 |

## Workflow And Artifact Coverage

| Coverage ID | Spec Refs | Requirement | Module | Status | Queue / Next | Current Evidence Or Gap |
| --- | --- | --- | --- | --- | --- | --- |
| WF-001 | 0.1A, 5, 49.1 | Real LangGraph `StateGraph` control plane | WF | tested | Q-001 done | Graph tests pass; front-half and fake tail execute through graph |
| WF-002 | 5.2, 49.1.3 | State ownership contract prevents arbitrary field writes | WF | tested | Q-001 done | `test_mod_agent_state.py` covers ownership policy |
| WF-003 | 5.5, 49.1.4 | Conditional edge matrix for request/evidence/review/build/runtime/repair | WF | partial | Q-010 and Q-014 done; later E2E branch tasks | Q-010 verifies evidence-before-plan/proposal routing and retrieval trace details; Q-014 verifies build/runtime failure routing into repair; full real runtime branch E2E remains incomplete |
| WF-004 | 5.6, 49.1.5 | Checkpoint, interrupt, resume, stale resume | WF | tested | Q-015 and R-012 done | `src/mod_agent/workflow/checkpointing.py` and `interrupts.py` define checkpoint/resume contracts, MemorySaver-ready graph compile, stale resume blocking, double resume rejection, checkpoint resume_binding for patch_proposal/proposal_review hashes, diff_hash validation, and restored_state output; joint smoke verifies review checkpoint resume over repair artifacts and rejects changed proposal/diff state |
| WF-005 | 5.7, 49.1.4 | Failure routes enter blocked or repair instead of silent continue | WF | partial | Q-014 done; later real runtime branch smoke | Blocked paths and build/runtime repair routes exist; graph-level failed build repair loop is tested, while real runtime branch E2E remains incomplete |
| WF-006 | 41.4, 49.4 | End-to-end controlled fake execution loop | WF | tested | Q-002A and R-008 done | Fake dry-run/build/runtime/eval/summary path tested; fake summaries now distinguish workflow completion from requested behavior verification |
| ART-001 | 6, 49.2 | Artifact envelope with schema version, hash, status, upstream refs | ART | tested | R-005 done | ArtifactStore.write now enforces required_upstream_artifacts, validates same-feature upstream refs, checks upstream hash/schema/freshness before normal writes, and preserves blocked stale resume reports as audit artifacts; R-005 accepted as PASS_WITH_RISK with artifact integrity and immutable revision follow-ups recorded below |
| ART-002 | 6.5, 49.2.4 | Stale detection blocks unsafe downstream use | ART | tested | Q-001 done | Stale artifact tests pass |
| ART-003 | 49.2.2 | Artifact dependency graph and immutable revisions | ART | partial | Q-016 done; future immutable revision/DAG UI task | DashboardProjectionBuilder exposes artifact DAG nodes/edges, upstream status, freshness status, stale reasons, missing artifacts, and dashboard_projection fields; immutable revision history and UI viewer remain incomplete |
| ART-004 | 31, 49.2.3 | Registry covers workflow artifact types | ART | tested | Q-001 and R-011 done | Registry tests pass; R-011 adds evidence_pack identity_schema_version and identity_field_mapping requirements |
| ART-005 | 49.2.5 | Artifact migrations for schema evolution | ART | not_started | future migration task | Unknown schema version is rejected; migration path not implemented |

## Knowledge And Retrieval Coverage

| Coverage ID | Spec Refs | Requirement | Module | Status | Queue / Next | Current Evidence Or Gap |
| --- | --- | --- | --- | --- | --- | --- |
| KB-001 | 7.2, 37.2, 45.5.1 | Source discovery with stable source identity and ignore rules | KB | tested | Q-003 done | SourceDiscovery and SourceRegistry now classify supported source patterns, prune ignored/cache/build directories, and produce stable source ids and content hashes |
| KB-002 | 7.3, 37.3, 45.5.4 | Raw text, canonical text, retrieval text, metadata contract | KB | tested | Q-002 and R-011 done | Document, Chunk, and ChunkRecord contracts now preserve raw/canonical/retrieval text separation with inherited metadata and stable hashes; R-011 defines identity_v1 for document_id, file_hash, source_hash, doc_hash, chunk_id, source_ref, and content_hash |
| KB-003 | 7.6, 45.5.3 | Code, decompiled API, artifact, log loaders | KB | partial | future loader tasks | Existing indexing is code/source oriented; full loader set missing |
| KB-004 | 7.7, 45.18.6 | SQLite metadata store for sources, documents, chunks, index versions | KB | tested | Q-004, R-010, and R-011 done | KnowledgeDatabase now persists collection-scoped sources, documents, chunks, and index_versions; R-010 adds one controlled-agent CollectionResolver so retrieval defaults resolve from `vector_store.collection_name`; R-011 blocks missing or inconsistent document/chunk identity metadata before persistence |
| KB-005 | 7.8, 45.18.3 | Incremental indexing skips unchanged content | KB | tested | Q-001 done | Incremental indexing tests pass for current implementation |
| RET-001 | 8.5, 37.5 | Deterministic retriever for exact evidence | RET | tested | Q-001 and R-010 done | Deterministic retrieval tests pass; R-010 removes the hardcoded controlled-agent default collection from DeterministicEvidenceRetriever and verifies explicit collection overrides |
| RET-002 | 8.6, 37.4, 45.9 | Symbol retrieval with source spans and chunk ids | RET | tested | Q-006 and R-011 done | SymbolIndexer now builds chunk-bound symbol_index rows with collection_id, index_version, chunk_id, source_path, and span; retriever prefers stable chunk symbol evidence before legacy file symbols and R-011 serializes chunk/document identity fields on chunk-backed evidence items |
| RET-003 | 37.4, 45.8, 45.18.6 | BM25 lexical sparse inverted index V1 | RET | tested | Q-005 and R-010 done | BM25Indexer persists bm25_terms and bm25_postings in SQLite, returns score plus hit_terms and term_frequencies, and DeterministicEvidenceRetriever can emit bm25 evidence from the resolved stable collection index version |
| RET-004 | 8.7, 45.8 | Dense retrieval with embedding provider abstraction | RET | tested | Q-022 contract done; real provider deferred | DenseRetrievalProvider contract is disabled by default, exposes DisabledDenseRetrievalProvider and FakeDenseRetrievalProvider, reads persisted chunks through ChunkRecord.text_for_embedding projection, reports retrieval.dense_started/retrieval.dense_finished trace refs, and keeps dense evidence as legacy_rag_auxiliary so it cannot replace BM25/symbol V1 gates; FakeDenseRetrievalProvider requires allow_test_providers=True when loaded through settings; Q-022 does not implement production embedding calls or vector database retrieval |
| RET-005 | 8.8, 45.9.2 | RRF fusion across retrieval routes | RET | not_started | future hybrid retrieval task | No fusion implementation |
| RET-006 | 8.9, 45.9.3 | Rerank with fallback and trace visibility | RET | not_started | future rerank task | No rerank implementation |
| RET-007 | 8.10, 45.10 | Evidence readiness gate blocks unsafe patching | RET | tested | Q-007, Q-010, R-009, and R-009-HARDENING-001 done | Readiness blocks unsafe graph continuation before implementation/proposal/review/execution artifacts; R-009 blocks legacy_rag_auxiliary-only retrieval from advancing writable planning; R-009-HARDENING-001 makes EvidenceItem default to legacy_rag_auxiliary and requires explicit mod_agent_deterministic item authority for planning |
| RET-008 | 8.11, 37.5, 45.4 | EvidencePack includes methods used, missing evidence, disabled modes, timing | RET | tested | Q-007, R-009, R-011, and R-009-HARDENING-001 done | Artifact payload requires and serializes retrieval_methods_used, missing_evidence, disabled_modes, timing, trace_refs, authority, authoritative_for_patch, identity_schema_version, and identity_field_mapping; ImplementationPlanner now rejects authoritative raw dict evidence packs without current identity schema/mapping, explicit item authority, or deterministic item provenance metadata while ignoring auxiliary context for planning |
| RET-009 | 45.11 | Citation and source transparency | RET | partial | future citation task | Evidence refs exist; citation contract not fully implemented |
| RET-010 | 37.8 | Targeted design and process black-box decomposition | RET | partial | Q-010 done; Q-008 and dashboard tasks next | EvidencePack and retrieve_evidence trace now expose methods, missing evidence, disabled modes, and timing; dashboard/eval views remain incomplete |

## Planning, Proposal, Review, And Change Control Coverage

| Coverage ID | Spec Refs | Requirement | Module | Status | Queue / Next | Current Evidence Or Gap |
| --- | --- | --- | --- | --- | --- | --- |
| PLAN-001 | 10.2, 49.3.1 | Request planning classifies ambiguity, risk, and route | PLAN | tested | Q-001 done | Planning tests pass |
| PLAN-002 | 10.3, 49.3.2 | Feature spec includes acceptance contract | PLAN | partial | future acceptance-contract task | Feature spec tests exist; runtime acceptance linkage incomplete |
| PLAN-003 | 10.4, 49.3.2 | Implementation plan binds changes to evidence | PLAN | tested | R-003 done | ImplementationPlan payloads now record evidence_source_paths separately from target_files; ImplementationPlanner only resolves target_source evidence into edit_target_path, read-only evidence blocks with EDIT_TARGET_UNRESOLVED, and PatchProposalBuilder refuses unresolved edit targets before reviewer |
| PROP-001 | 11.2, 49.3.3 | Patch proposal schema is intent-only before apply | PROP | tested | Q-001 done | Proposal tests pass |
| PROP-002 | 11.3, 49.3.3 | Proposal context builder uses evidence without guessing | PROP | partial | future context-builder task | Basic builder exists; richer context pack missing |
| PROP-003 | 11.4 | No-op detector blocks meaningless plans | PROP | tested | Q-001 done | No-op proposal test passes |
| REVIEW-001 | 12.2, 49.3.4 | Review gate checks evidence binding, scope, permissions, forbidden paths | REVIEW | tested | R-001 and R-002 done | Graph-level domain_policy wiring is tested through review_proposal; missing evidence_pack now blocks evidence-bound proposals while repair_plan remains an approved repair evidence source |
| REVIEW-002 | 12.4, 50.3 | Permission model blocks confirmed writes by default | REVIEW | tested | Q-001 done | Permission tests pass |
| REVIEW-003 | 12.5, 9.5 | Path guard prevents unsafe project paths | REVIEW | tested | Q-001 done | Forbidden path test passes |
| GIT-001 | User Git requirement, 49.3 | Bind decisions and code changes to Git commits | GIT | tested | Q-011 done | GitChangeRecord now binds commit metadata to decision_artifacts and patch_artifacts with artifact hashes; workflow helpers build/write records from ModAgentState without auto-committing |
| GIT-002 | User Git requirement | Replay/rollback own changes through Git metadata | GIT | partial | future replay task | Replay and rollback hints exist in git_change_record; automated replay/rollback execution remains missing |

## Execution, Build, Runtime, And Repair Coverage

| Coverage ID | Spec Refs | Requirement | Module | Status | Queue / Next | Current Evidence Or Gap |
| --- | --- | --- | --- | --- | --- | --- |
| EXEC-001 | 13, 49.4.1 | Dry-run apply produces structured result before real write | BUILD | partial | future dry-run adapter task | Q-002A fake dry-run exists; real patch dry-run not implemented |
| EXEC-002 | 49.4.1 | Confirmed apply requires approval and exact diff hash | BUILD | not_started | future confirmed-apply task | Permission model blocks confirmed write; approval flow missing |
| EXEC-003 | 14, 49.4.2 | Build profile and command runner | BUILD | tested | R-004 done | BuildAdapter now requires expected artifact verification before real local builds can claim success; verified_artifacts and artifact_verification carry safe path, sha256, size, and mtime evidence |
| EXEC-004 | 14.4, 49.4.2 | Build error classifier and repair handoff | BUILD | tested | Q-013 done | BuildErrorClassifier covers the required taxonomy, diagnostics are parsed from compiler output, and failed build results expose repair_handoff metadata |
| EXEC-005 | 15.2, 49.4.3 | Runtime evidence source taxonomy: logs, screenshots, manual, supplied output | RUN | partial | Q-012 and Q-018 done; log collector and real screenshot capture remain | Q-012 adds explicit fake/manual/supplied-output source contracts and evidence item schema; Q-018 adds screenshot metadata registry and visual-only runtime item conversion; real log and screenshot collectors remain future work |
| EXEC-006 | 15.3, 49.4.3 | Runtime evidence schema proves acceptance or remains inconclusive | RUN | tested | Q-012 done | Runtime evidence payloads now separate startup_loaded, gameplay_behavior_verified, evidence_items, verification_status, acceptance_status, raw_supplied_output, and claims_real_runtime_success; verified status requires explicit acceptance evidence |
| EXEC-007 | 15.4, 38 | Screenshot registry and image evidence linkage | MM | tested | Q-018 done | `src/mod_agent/runtime/screenshots.py` and `tests/unit/test_runtime_screenshots.py` implement screenshot metadata rows, screenshot_registry artifact payloads, caption status separation, and visual-only runtime item conversion |
| EXEC-008 | 15.5, 38.6 | Vision captioner generates bounded visual descriptions | MM | not_started | future caption task | No captioner implementation |
| EXEC-009 | 16, 49.4.4 | Repair plan with retry budget and evidence-bound scope | REPAIR | tested | Q-014 done | `src/mod_agent/repair/planner.py` creates build/runtime repair_plan payloads from failure evidence, tracks retry_count/retry_budget, and blocks exhausted loops; joint smoke verifies repair_plan freshness is enforced by checkpoint resume |
| EXEC-010 | 49.4.4 | Repair proposal must re-enter review gate | REPAIR | tested | Q-014 done | Repair plans route back to `generate_patch_proposal`; repair proposals are reviewed by `ProposalReviewer` with repair_plan evidence before dry-run; joint smoke verifies review resume cannot skip proposal_review artifact lineage |

## Multimodal Coverage

| Coverage ID | Spec Refs | Requirement | Module | Status | Queue / Next | Current Evidence Or Gap |
| --- | --- | --- | --- | --- | --- | --- |
| MM-001 | 38.1 | Loader extracts image references and metadata | MM | partial | Q-018 done; future multimodal ingestion task | Runtime screenshot metadata can now be registered; document/image loaders that extract image_refs remain missing |
| MM-002 | 38.2 | Splitter preserves image-text relationships | MM | not_started | future multimodal splitter task | No image-text chunk linkage |
| MM-003 | 38.3 | Transform stage performs image understanding with fallback | MM | not_started | future caption task | No vision provider abstraction |
| MM-004 | 38.4 | Dual storage for image bytes and image metadata | MM | partial | Q-018 done; future image storage task | Screenshot metadata registry exists as an artifact contract; original image byte storage and image_processing_cache remain missing |
| MM-005 | 38.5 | Quality boundaries prevent low-confidence image claims | MM | not_started | future multimodal QA task | No visual confidence policy |
| MM-006 | 38.6, 50.1 | Image captions support evidence but do not prove runtime success | MM | partial | Q-018 done; future multimodal QA task | Screenshot registry enforces visual-only status and claims_real_runtime_success=false; full caption confidence policy remains future work |

## Evaluation, Observability, MCP, And Performance Coverage

| Coverage ID | Spec Refs | Requirement | Module | Status | Queue / Next | Current Evidence Or Gap |
| --- | --- | --- | --- | --- | --- | --- |
| EVAL-001 | 18, 41.5, 45.14 | Golden query list and regression gate for evidence retrieval | EVAL | tested | Q-008 done | `src/mod_agent/evaluation/retrieval_regression.py`, `tests/fixtures/retrieval/golden_queries.json`, and `tests/unit/test_retrieval_regression.py` cover evidence hit/source coverage, missing evidence failure, eval_report payload, and false_continue representation |
| EVAL-002 | 18.3, 41.5 | Faithfulness, answer relevancy, context precision adapted to evidence tasks | EVAL | tested | Q-019 done | AgentQualityEvaluator reports faithfulness, answer_relevancy, and context_precision from evidence sufficiency, route/risk relevance, and evidence_ref precision in `tests/unit/test_agent_quality_eval.py` |
| EVAL-003 | 49.6 | Agent decision quality metrics: route accuracy, evidence sufficiency, review correctness, repair quality | EVAL | tested | Q-019 done | `src/mod_agent/evaluation/agent_quality.py` evaluates route_accuracy, risk_classification_accuracy, evidence_sufficiency, review_correctness, repair_quality, false_continue_rate, review_miss_rate, hard_fail_rate, and mean_score |
| EVAL-004 | 50.7 | Baseline evaluation before improvement claims | EVAL | partial | Q-019 done; future real baseline runner | AgentQualityReport carries baseline_status, claims_allowed, and claims_forbidden; missing required baseline fails the report, but direct-LLM baseline execution is not implemented |
| OBS-001 | 19.2, 39.2 | Structured trace event model with latency and artifact refs | OBS | partial | Q-010, Q-016, R-007 done; later trace latency task | retrieve_evidence finished trace records EvidencePack summary and artifact refs; DashboardProjectionBuilder exposes ordered trace events and timing when present; TraceService now sanitizes dashboard trace reads by default and TraceContext uses raw perf_counter_ns elapsed measurement; dashboard smoke e2e passes; generic node latency writer remains incomplete |
| OBS-002 | 39.6 | Monitoring granularity and bottleneck localization | OBS | partial | Q-016 done; future metrics task | DashboardProjectionBuilder derives bottleneck timing from trace details and EvidencePack timing; persistent metrics dashboard remains absent |
| OBS-003 | 19.4, 39.3 | Dashboard pages for workflow, evidence, artifacts, proposals, eval | OBS | tested | R-006, R-007, R-013, and R-009-HARDENING-001 done | DashboardProjectionBuilder now exposes sanitized controlled-agent workflow, evidence authority, artifact, proposal, build, runtime, repair, and eval summaries through ArtifactStore without raw artifact bodies; evidence summary shows readiness, can_generate_patch, authority, authoritative_for_patch, and projection_status together; missing/stale/unknown artifacts render explicit empty or blocked states; observability dashboard includes a read-only Controlled Agent page; DataService destructive methods remain blocked by default; TraceService sanitizes dashboard trace payloads by default; dashboard smoke e2e passes; polished persisted UI remains a future dashboard task |
| MCP-001 | 20.3, 45.12 | Controlled-agent MCP tools expose planning/query/build/status safely | MCP | tested | Q-021 done | ControlledAgentMCPToolSurface exposes read-only/report-only list_features, get_feature_status, get_artifact, preview_retrieval, preview_patch_proposal, get_proposal_review, get_eval_report, and get_job_status tools with structuredContent, artifact_refs, trace_refs, blockers, and hidden dangerous actions; degraded budget jobs use budget_summary.allowed for continuation semantics instead of envelope.status |
| MCP-002 | 45.12.1 | MCP async job contract avoids blocking long operations | MCP | tested | Q-009 done | `src/mod_agent/mcp/jobs.py`, `src/mod_agent/mcp/tools.py`, and `tests/unit/test_mcp_async_jobs.py` cover job_id/status/artifact_refs schema, immediate queued responses, read-only status lookup, cancellation, hidden dangerous tools, and job_status artifact payload |
| PERF-001 | 45.18.1 | API call count reduction and request budgeting | PERF | tested | Q-020 and Q-022 done | PerformanceBudgetPolicy enforces per-operation max_api_calls, blocks unconfigured operations by default, serializes blocked/degraded budget decisions into job_status budget_summary without network calls, and Q-022 reports dense retrieval api_calls, embedded_items, cache_enabled, and budget_decision in evidence_pack budget_summary |
| PERF-002 | 45.18.2 | Batch processing for ingestion, embeddings, captions, eval | PERF | partial | Q-020 contract done; future orchestration | PerformanceBudgetPolicy now supports max_batches and configured operation budgets for indexing, eval, and captions; controlled subsystem batch orchestration remains future work |
| PERF-003 | 45.18.3 | Incremental processing skips duplicate work | PERF | partial | Q-003 and Q-004 done | SourceRegistry exposes stable aggregate source hashes; SQLite chunk upsert deduplicates same collection/index_version/chunk_id; broader loader/chunker/embedding/caption skip policy remains future work |
| PERF-004 | 45.18.4 | Resource controls for chunking, indexing, embeddings, vision | PERF | partial | Q-020 contract done; future integration | Config-driven budgets now cover max_items, max_batches, max_duration_ms, positive max_concurrency, and enforced cache_enabled reporting for indexing, retrieval, eval, captions, and tool_call operations; execution-path integration remains future work |
| PERF-005 | 45.18.5 | Concurrent document upload and concurrent query behavior | PERF | not_started | future concurrency task | No concurrency tests |
| PERF-006 | 41.6 | Performance and stress tests for throughput and latency | PERF | partial | Q-020 smoke done; future benchmark harness | Q-020 adds deterministic budget smoke tests for blocked/degraded decisions and timing_summary serialization; real throughput/latency benchmark harness remains future work |

## Domain And Extensibility Coverage

| Coverage ID | Spec Refs | Requirement | Module | Status | Queue / Next | Current Evidence Or Gap |
| --- | --- | --- | --- | --- | --- | --- |
| DOM-001 | 9.2, 43.1 | Base Domain Adapter interface | DOM | tested | Q-017 done | DomainAdapter protocol, DomainProfile, DomainRoute, EvidenceQuery, RuntimeProfile, VerificationPlan, DomainReviewPolicy, and DomainAdapterRegistry are tested |
| DOM-002 | 9.3, 50.8 | GTFO GameProfile as first high-complexity validation target | DOM | tested | Q-017 done | GTFOAdapter exposes GameProfile fields for GTFO / Unity IL2CPP / BepInEx / HarmonyX, source definitions, build profile, runtime profile, and verification strategy |
| DOM-003 | 9.4 | GTFO risk taxonomy | DOM | tested | Q-017 done | GTFOAdapter classifies config_only, ui_feedback_without_hook, game_hook, runtime_behavior_change, native/interop/reflection-heavy, and unknown/block |
| DOM-004 | 9.5 | GTFO forbidden paths | DOM | tested | R-001 done | DomainReviewPolicy and ProposalReviewer block forbidden/out-of-root paths when domain_policy is supplied directly; graph review_proposal now passes a resolved DomainReviewPolicy through the default domain registry |
| DOM-005 | 27.1, 43.1 | Other Unity/BepInEx/Harmony game profiles can be added | DOM | partial | Q-017 done; future onboarding workflow | DomainAdapterRegistry accepts new adapters without workflow changes; full onboarding flow and capability report are not implemented |
| DOM-006 | 50.8 | Unknown GameProfile blocks game-specific runtime patching | DOM | tested | Q-017 done | UnsupportedDomainAdapter plus ProposalReviewer domain_policy block game-specific runtime patch proposals without experimental/supported GameProfile |

## Recently Closed Coverage Gaps

| Missing ID | Spec Refs | Closed Detail | Closed By | Evidence |
| --- | --- | --- | --- | --- |
| MISS-001 | 8.11, 37.5, 45.10 | EvidencePack now carries `retrieval_methods_used`, `missing_evidence`, disabled mode reporting, `timing`, and `trace_refs` | Q-007 | `tests/unit/test_evidence_retrieval.py`, `tests/unit/test_artifact_contract.py`, `tests/unit/test_workflow_graph.py` |
| MISS-002 | 45.5.4, 45.5.5 | Text and metadata contracts now separate `raw_text`, `canonical_text`, and `text_for_retrieval`; chunk metadata inherits source fields and carries stable hashes | Q-002 | `tests/unit/test_knowledge_base.py` |
| MISS-003 | 45.18.6 | SQLite metadata store now records stable/building/failed index versions and keeps failed index builds from replacing the latest stable version | Q-004 | `tests/unit/test_knowledge_base.py` |
| MISS-004 | 37.4, 45.8 | BM25 inverted index V1 now exists as local SQLite lexical sparse retrieval with explainable term-hit metadata | Q-005 | `tests/unit/test_knowledge_base.py`, `tests/unit/test_evidence_retrieval.py` |
| MISS-005 | 37.4, 45.9 | Symbol Index V1 now binds symbols to stable chunk ids, source paths, spans, and index versions | Q-006 | `tests/unit/test_knowledge_base.py`, `tests/unit/test_evidence_retrieval.py` |
| MISS-017 | 41.5, 45.14 | Golden query regression list and evidence-first retrieval gate now exist for retrieval changes | Q-008 | `tests/fixtures/retrieval/golden_queries.json`, `tests/unit/test_retrieval_regression.py` |
| MISS-012 | 45.12.1 | MCP async job contract now represents ingestion, retrieval eval, and build as queued jobs instead of blocking tool calls | Q-009 | `tests/unit/test_mcp_async_jobs.py`, `tests/unit/test_artifact_contract.py` |
| MISS-009 | User Git requirement, 49.3 | Workflow decisions and code changes now bind to Git commit metadata through git_change_record artifacts without auto-committing | Q-011 | `src/mod_agent/git/repository.py`, `src/mod_agent/git/workflow_binding.py`, `tests/unit/test_git_repository.py` |
| MISS-007 | 49.4.3 | Manual and supplied runtime evidence contracts now record raw supplied output separately and block verified status without explicit acceptance evidence | Q-012 | `src/mod_agent/runtime/evidence.py`, `tests/unit/test_runtime_evidence.py`, `tests/unit/test_workflow_graph.py` |
| MISS-006 | 49.4.2 | Controlled build adapter contract and build error classifier now exist with explicit execution gating and repair_handoff metadata | Q-013 | `src/mod_agent/build/adapter.py`, `tests/unit/test_build_adapter.py`, `tests/unit/test_workflow_graph.py` |
| MISS-008 | 49.4.4 | Repair loop and retry budget now exist with evidence-bound repair_plan artifacts and review-gated repair proposals | Q-014 | `src/mod_agent/repair/planner.py`, `tests/unit/test_repair_loop.py`, `tests/unit/test_workflow_graph.py`, `tests/unit/test_repair_checkpoint_smoke.py` |
| MISS-015 | 5.6, 49.1.5 | Checkpoint, interrupt, resume, and stale resume contracts now exist with workflow_checkpoint and resume_report artifacts | Q-015 | `src/mod_agent/workflow/checkpointing.py`, `src/mod_agent/workflow/interrupts.py`, `tests/unit/test_workflow_checkpointing.py`, `tests/unit/test_repair_checkpoint_smoke.py` |
| MISS-016A | 19, 39, 49.2.2 | Read-only dashboard projection now exposes workflow trace, evidence summary, artifact DAG, stale/missing artifacts, blockers, and bottleneck timing | Q-016 | `src/mod_agent/dashboard/projections.py`, `tests/unit/test_dashboard_projection.py` |
| MISS-014A | 50.8 | DomainAdapter/GameProfile contracts, GTFO profile policy, and unknown-domain runtime-change blocking now exist | Q-017 | `src/mod_agent/domain/`, `src/mod_agent/proposal/reviewer.py`, `tests/unit/test_domain_adapter.py` |
| MISS-010A | 15.4, 38.1, 38.4 | Runtime screenshot metadata registry now exists, and screenshot/caption evidence is kept visual-only instead of proving gameplay success | Q-018 | `src/mod_agent/runtime/screenshots.py`, `src/mod_agent/artifacts/registry.py`, `tests/unit/test_runtime_screenshots.py`, `tests/unit/test_artifact_contract.py` |
| MISS-011A | 18.3, 41.5, 49.6, 50.7 | Agent decision-quality eval contract now exists with local JSON suites, hard gates for false continue/review miss, baseline status, and claim limits | Q-019 | `src/mod_agent/evaluation/agent_quality.py`, `tests/fixtures/evaluation/agent_quality_cases.json`, `tests/unit/test_agent_quality_eval.py` |
| MISS-013A | 45.18 | Controlled-agent performance budget contract now supports config-driven API-call, item, batch, duration, positive concurrency, enforced cache policy, default blocking for unconfigured operations, blocked/degraded decisions, trace summaries, and job_status budget_summary serialization | Q-020 | `src/mod_agent/performance/budget.py`, `src/core/settings.py`, `config/settings.yaml`, `tests/unit/test_performance_budget.py`, `tests/unit/test_config_loading.py`, `tests/unit/test_artifact_contract.py` |
| MISS-018 | 20.3, 45.12 | Controlled-agent read-only/report-only MCP tool surface now exposes safe status/artifact/retrieval/proposal/review/eval/job summaries and preserves degraded budget semantics | Q-021 | `src/mod_agent/mcp/tools.py`, `tests/unit/test_controlled_agent_mcp_tools.py`, `tests/integration/test_mcp_server.py`, `tests/e2e/test_mcp_client.py` |
| MISS-019 | 8.7, 45.8, 45.18.1 | Disabled-by-default dense retrieval provider contract now exists with fake provider tests, trace-visible dense route, and explicit budget accounting while preserving BM25/symbol V1 gates | Q-022 | `src/mod_agent/evidence/dense.py`, `src/mod_agent/evidence/retriever.py`, `src/mod_agent/knowledge/models.py`, `src/core/settings.py`, `tests/unit/test_evidence_retrieval.py`, `tests/unit/test_config_loading.py` |
| MISS-021A | 8.7, 45.8, 45.18.1 | FakeDenseRetrievalProvider can no longer be loaded through normal settings; settings tests must explicitly pass allow_test_providers=True | V1-AUDIT-001 | `src/core/settings.py`, `tests/unit/test_config_loading.py`, `docs/V1_ACCEPTANCE_AUDIT.md` |
| MISS-R001A | 9.5, 11, 49.3.4, 50.8 | Graph review_proposal now passes resolved DomainReviewPolicy from the default domain registry into ProposalReviewer | R-001 | `src/mod_agent/workflow/graph.py`, `tests/unit/test_workflow_graph.py`, `tests/unit/test_domain_adapter.py` |
| MISS-R002A | 6, 11, 49.3.4 | Evidence-bound ProposalReviewer calls now block when no evidence_pack or repair_plan can validate evidence refs | R-002 | `src/mod_agent/proposal/reviewer.py`, `tests/unit/test_proposal_review.py`, `tests/unit/test_repair_loop.py` |
| MISS-R003A | 9, 10, 49.3 | implementation_plan now separates evidence_source_paths from edit_target_path/target_files and blocks read-only evidence sources as unresolved edit targets | R-003 | `src/mod_agent/planning/implementation_plan.py`, `src/mod_agent/proposal/builder.py`, `tests/unit/test_planning.py`, `tests/unit/test_proposal_review.py` |
| MISS-R004A | 12, 14.4, 49.4.2 | BuildResult no longer claims real build success from exit code alone; expected artifacts must be verified with safe path, hash, size, and mtime evidence | R-004 | `src/mod_agent/build/adapter.py`, `tests/unit/test_build_adapter.py`, `tests/unit/test_artifact_contract.py` |
| MISS-R005A | 6, 30, 49.1 | ArtifactStore now enforces required_upstream_artifacts declared in artifact contracts and rejects missing or stale upstream refs on normal writes | R-005 | `src/mod_agent/artifacts/store.py`, `tests/unit/test_artifact_store.py`, `tests/unit/test_artifact_contract.py`, `tests/unit/test_repair_checkpoint_smoke.py` |
| MISS-R005E | 5.6, 49.1.5 | `allow_stale_upstreams` is limited to blocked stale-resume `resume_report` audit writes and normal stale upstream writes remain rejected | R-012 / Review Repair Queue refresh | `src/mod_agent/workflow/checkpointing.py`, `src/mod_agent/artifacts/store.py`, `tests/unit/test_repair_checkpoint_smoke.py` |
| MISS-R006A | 18, 39, 45.12 | DataService delete_document and reset_all are blocked by default and require explicit confirmation, explicit enablement, and permission approval before execution | R-006 | `src/observability/dashboard/services/data_service.py`, `tests/unit/test_dashboard_data_service.py`, `tests/unit/test_permissions.py` |
| MISS-R006B | 18, 39, 45.12 | Controlled-agent dashboard now exposes sanitized workflow/artifact/proposal/build/runtime/repair/eval summaries without raw artifact bodies | R-013 | `src/mod_agent/dashboard/projections.py`, `src/observability/dashboard/pages/mod_agent_dashboard.py`, `tests/unit/test_dashboard_projection.py`, `tests/e2e/test_dashboard_smoke.py` |
| MISS-R007A | 18, 39, 45.12 | TraceService dashboard reads now redact sensitive keys including nested non-string values, hide Windows and POSIX absolute paths, cap long strings, keep safe_mode redacted, and require explicit include_raw=True for unsafe raw trace payloads | R-007 unit closure repair | `src/observability/dashboard/services/trace_service.py`, `src/core/trace/trace_context.py`, `tests/unit/test_trace_service.py`, `tests/unit/test_trace_context.py` |
| MISS-R007B | 39.3 | Dashboard smoke e2e now runs successfully in .venv after installing streamlit | R-007 e2e closure | `tests/e2e/test_dashboard_smoke.py` |
| MISS-R009A | 8.10, 8.11, 37.5, 45.10 | Legacy RAG retrieval output is explicitly auxiliary and cannot bypass mod_agent deterministic evidence/readiness gates for writable planning | R-009 | `src/mod_agent/evidence/models.py`, `src/mod_agent/evidence/readiness.py`, `src/mod_agent/planning/implementation_plan.py`, `tests/unit/test_evidence_retrieval.py`, `tests/unit/test_planning.py` |
| MISS-R010A | 7, 8, 45 | Controlled-agent evidence retrieval now resolves collection identity through one CollectionResolver: explicit collection_id overrides settings, default collection comes from `vector_store.collection_name`, and missing collection configuration routes workflow retrieval to blocked evidence | R-010 | `src/mod_agent/knowledge/collection_resolver.py`, `src/mod_agent/evidence/retriever.py`, `src/mod_agent/workflow/graph.py`, `tests/unit/test_collection_resolver.py`, `tests/unit/test_evidence_retrieval.py`, `tests/unit/test_workflow_graph.py` |
| MISS-R011A | 6, 7, 8, 30, 45.4 | Controlled-agent identity fields now have one tested mapping: document_id identifies the loaded document, file_hash is the loaded source file hash, source_hash is the V1 alias for file_hash, doc_hash is canonical document text hash, chunk_id identifies a chunk, and source_ref points from chunk to document | R-011 | `src/mod_agent/knowledge/models.py`, `src/mod_agent/knowledge/database.py`, `src/mod_agent/evidence/models.py`, `src/mod_agent/evidence/retriever.py`, `src/mod_agent/artifacts/registry.py`, `tests/unit/test_knowledge_base.py`, `tests/unit/test_evidence_retrieval.py`, `tests/unit/test_artifact_contract.py` |
| MISS-R009B | 8.10, 8.11, 37.5, 39.3, 45.8, 45.10 | Authority defaults, raw dict provenance checks, dashboard authority projection, and shared sparse/query tokenization are implemented | R-009-HARDENING-001 | `src/mod_agent/evidence/models.py`, `src/mod_agent/evidence/retriever.py`, `src/mod_agent/planning/implementation_plan.py`, `src/mod_agent/dashboard/projections.py`, `src/core/query_engine/tokenization.py`, `src/core/query_engine/query_processor.py`, `src/ingestion/embedding/sparse_encoder.py`, `tests/unit/test_evidence_retrieval.py`, `tests/unit/test_planning.py`, `tests/unit/test_dashboard_projection.py`, `tests/unit/test_query_processor.py`, `tests/unit/test_sparse_encoder.py` |

## Open Missing Requirement Register

These rows are the current high-impact gaps that must not be forgotten when selecting future tasks.

| Missing ID | Spec Refs | Missing Detail | Blocking Impact | Recommended Task |
| --- | --- | --- | --- | --- |
| MISS-R005B | 6, 49.2.4 | Artifact freshness currently checks direct upstream refs only, not full transitive DAG freshness | A stale deeper dependency can remain hidden behind a fresh direct artifact | future artifact integrity / R-012 follow-up |
| MISS-R005C | 6, 49.2 | ArtifactStore.read does not recompute the envelope content hash at read time; it compares envelope artifact_hash with ArtifactRef artifact_hash | Tampered envelope content is not independently rehashed during read validation | future artifact integrity task |
| MISS-R005D | 49.2.2 | Artifact storage still uses one feature/type file and does not retain immutable historical revision files | Historical artifact revisions can be overwritten and cannot be audited as immutable files | future immutable revision task |
| MISS-020 | 20.3, 45.12 | Final JSON-RPC MCP adapter must map unknown tool names to protocol error instead of reusing facade-level unsupported tool results | Wire-level MCP compliance can be overstated if adapter behavior is not tested separately from ControlledAgentMCPToolSurface | final MCP protocol adapter boundary test |
| MISS-021 | 8.7, 45.8, 45.18.1 | Real dense retrieval provider remains deferred: future work needs index/query API, embedding cache, collection/source filters, top_k/score threshold, and budget-aware batching | Dense retrieval claims can be overstated if Q-022 is described as real embedding/vector database retrieval | future real dense provider task |
| MISS-010 | 38 | Full multimodal image ingestion, captioning, byte storage, cache, and confidence policy remain incomplete; Q-018 only closes runtime screenshot metadata registry | Image evidence can be registered for runtime screenshots, but full multimodal diagnostics and retrieval still lack loader/caption/storage policy | future multimodal task group |
| MISS-011 | 41.5, 49.6, 50.7 | Full behavior benchmark runner, real direct-LLM baseline execution, multi-run consistency, trace matching, and dashboard integration remain incomplete; Q-019 closes the local decision-quality contract only | Project cannot claim measured real-world agent-quality improvement beyond the local fixture suite | future eval baseline task group |
| MISS-013 | 45.18 | Budget/resource-limit contracts exist, but real batch orchestration, cache behavior implementation, execution-path integration, concurrent operation handling, and benchmark harness are incomplete | Scaling and cost-control claims remain limited to contract checks until measured execution paths exist | future performance integration task group |
| MISS-014 | 50.8 | Full GameProfile onboarding workflow, smoke plugin/startup probe, and capability report are absent; Q-017 provides contracts and unknown-domain blocking only | Supported-domain claims still need onboarding evidence before being advertised | future onboarding/capability report task |
| MISS-016 | 19, 39 | Polished dashboard UI, persisted trace viewer, and explicit artifact_status versus blocker-semantics visualization are absent; Q-016 provides the read-only projection layer only | Process black-box problem is reduced but not fully solved for human UI/demo usage | future dashboard UI task group |

## Next Matrix Maintenance Rules

```text
When a queue task starts:
  1. List the Coverage IDs it intends to change.
  2. Read the referenced DEV_SPEC sections.
  3. Add a row if the requirement is missing from this matrix.

When a queue task completes:
  1. Update each affected row status.
  2. Add code files, test files, or artifact evidence in PROJECT_STATE.
  3. Add any new missing detail to the Missing Requirement Register.
  4. Do not mark verified without E2E, regression, performance, or real execution evidence.
```
