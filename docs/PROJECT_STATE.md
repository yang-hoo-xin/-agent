# Project State

This file is the active state summary for the Controlled Mod Agent Platform.
Historical loop details are archived in `docs/audits/LOOP_HISTORY.md`.

Last updated: 2026-07-09

## Current Queue

```text
current_queue: GTFO-VSLICE-001C
last_completed: GTFO-VSLICE-001B implementation_plan Binding Registry through proposal_review and repair proposal
current_stabilization_task: GTFO-VSLICE-001C is active. 001C-A now uses `hook_requirement` for structured Hook Target Selection while retaining `requires_hook_evidence` as the broad legacy evidence gate, requires Hook targets to carry complete method identity, makes `ImplementationPlanner` select exactly one `hook_target_binding_id` per Hook-required change, blocks `AMBIGUOUS_HOOK_TARGET`, and makes proposal_review verify the selected target against `implementation_plan.binding_registry` and the EvidencePack. Current boundary remains evidence/review semantics only: no real GTFO launch, no production hook discovery engine, and no workspace-aware canonical path resolver.
next_recommended_task: Continue GTFO-VSLICE-001C with repair decision quality for the selected GTFO path, using the same evidence-bound artifact loop rather than adding standalone schema work.
ordinary_queue_status: Q-022, MISS-022, MISS-026A, RUNTIME-DENSE-API-BOUNDARY-001, TRANSITION-001, TRANSITION-002, TRANSITION-003, TRANSITION-004, TRANSITION-005, MISS-026D, MISS-026E, STATE-001, SKILL-MCP-001, E2E-001, E2E-002, SKILL-SPLIT-001, SKILL-SPLIT-002, SKILL-SPLIT-003, SKILL-SPLIT-004, SKILL-SPLIT-CLOSURE-001, PLANNING-BRIEF-001, ARTIFACT-INTEGRITY-001, ARTIFACT-INTEGRITY-002, ARTIFACT-INTEGRITY-003, ARTIFACT-PROD-001A, ARTIFACT-PROD-001B, and PLANNING-BRIEF-IMPL-001 completed; approved GTFO launch and real gameplay evidence remain explicit opt-in production runtime automation work
next_stage_after_expert_split: V2 platform expansion is active; prioritize platform capability work over further process Skill splitting
V3_deferred_runtime_track: approved GTFO launch smoke, game directory copy, and real gameplay evidence are V3 or explicit opt-in runtime validation work
career_oriented_progression: V2/V3 tasks must improve interview-visible production Agent platform depth: vertical slice evidence, safe tool integration, observability, evaluation, artifact lineage, runtime feedback, and retrieval quality
current_spec_split_status: EVIDENCE_RAG_MCP_SPEC.md split completed in working tree; DEV_SPEC.md remains root control-plane spec; RAG/MCP is a subsystem spec and must feed the LangGraph artifact loop, not an independent RAG product or MCP execution entrypoint
```

## Current Spec Split State

```text
Split completed:
  EVIDENCE_RAG_MCP_SPEC.md now contains the Evidence RAG / MCP subsystem spec.

Root spec:
  DEV_SPEC.md remains the root control-plane specification. It wins for product
  identity, LangGraph workflow authority, artifact contracts, evidence-before-edit,
  proposal/review gates, runtime gates, evaluation gates, permission policy,
  rollback, dashboard boundaries, and delivery queue discipline.

Subsystem spec:
  EVIDENCE_RAG_MCP_SPEC.md owns RAG/MCP technical detail inside the DEV_SPEC.md
  boundaries. Sections 1-3 define read order, integration overlay, source
  authority, phase placement, and controlled-agent MCP boundaries. Section 4 is
  the imported technical blueprint for ingestion, chunking, retrieval, rerank,
  trace, eval, dashboard, multimodal evidence, and MCP protocol detail.

Conflict rule:
  If the two specs conflict on product boundary, workflow authority, safety,
  review/runtime/eval gates, or external side effects, DEV_SPEC.md wins.

Pollution check:
  RAG/MCP remains a subsystem that serves EvidencePack, proposal/review, repair,
  eval, dashboard, and controlled MCP surfaces. `query_knowledge_hub` remains an
  optional/later browsing view. Write/runtime MCP actions require LangGraph-backed
  approval artifacts and must not execute directly.
```

## V2 Entry Decision

```text
Decision:
  Enter V2 platform expansion instead of continuing MISS-026 live GTFO launch work.

DEV_SPEC basis:
  The project is a vertical controlled code-generation platform.
  RAG grounds planning/proposal/review/build/runtime/eval decisions.
  Dashboard, MCP/API/CLI, and evaluation expose the same artifact-backed product loop.
  GTFO remains the first DomainAdapter and a V3 runtime validation target, not the V2 centerline.
  Knowledge Base and Evidence RAG V1 scope is local and controlled:
  SourceRegistry metadata, local controlled source indexing and source-type
  classification basics, incremental hash indexing, deterministic retrieval,
  symbol retrieval, BM25, EvidencePack, and readiness gates. Dedicated
  artifact/log/domain-doc loaders remain partial unless current source and
  focused tests prove the specific loader path.
  V2 may add curated local reference mods and curated community notes as
  supporting evidence sources, but raw community chat and broad crawlers remain
  outside patch authority.
  V3 owns dense/hybrid/RRF hardening, citation/source-span retrieval eval,
  allowlisted GitHub importing, Discord export importing, and broader community
  importers.

Selected first V2 task:
  GTFO-VSLICE-001 Evidence-Controlled GTFO Vertical Slice.

Why first:
  This keeps V2 centered on a verifiable platform capability: retrieved evidence
  must control hook discovery, implementation_plan, patch_proposal evidence
  binding, review gate, and repair context for one GTFO feature path. V2-PROP-001
  remains necessary, but only as a supporting context-pack upgrade inside the
  vertical slice so work does not drift back into standalone artifact/proposal
  schema deepening.

Immediate execution order:
  1. GTFO-VSLICE-001A: prove current evidence retrieval identity gates the first GTFO slice path inside a LangGraph artifact loop.
  2. V2-PROP-001A: deepen patch_proposal.context_pack only where needed by the slice.
  3. GTFO-VSLICE-001B: bind implementation_plan/proposal/review/repair to edit evidence refs, hook/supporting evidence, and source spans. Completed as the tested `implementation_plan.binding_registry` / `edit_binding_id` / `allowed_edit_binding_ids` sub-loop.
  4. GTFO-VSLICE-001C: tighten concrete GTFO hook-target evidence, review blocker quality, and repair decision quality.
  5. V2-KB-REF-001 and V2-KB-COMM-001: add curated supporting sources after target evidence path works.
  6. V2-EVAL-001, V2-DASH-001, V2-MCP-001, then V2-RET-001.
```

## Knowledge Source Implementation Phase Table

| Project | Phase |
| --- | --- |
| artifact/log/domain-doc loader deepening | V2 supporting item |
| ReferenceModLoader metadata contract | V2 |
| CommunityNoteLoader / Extractor | V2 |
| controlled-agent RRF/rerank | V3 |
| citation/source-span retrieval eval | V3 |
| GitHubRepoImporter | V3 |
| DiscordExportImporter | V3/V3+ |
| Thunderstore/Nexus/forum importer | V3+ |
| general community crawling | V3+ / deferred |

## Career-Oriented Progression Policy

```text
Purpose:
  Project work should raise job-market competitiveness by producing credible
  evidence of production-grade AI Agent platform engineering, not by accumulating
  disconnected documents or schema-only changes.

Task selection filter:
  Prefer tasks that are necessary for a hiring conversation about real systems:
  durable workflow control, evidence-grounded code generation, approval and
  rollback safety, MCP/API/tool boundaries, eval and regression gates,
  observability, artifact lineage, runtime feedback, retrieval quality, and
  production failure handling.

Current implication:
  GTFO-VSLICE-001A stays first inside GTFO-VSLICE-001 because it can
  demonstrate the first verifiable controlled code-generation chain. V2-PROP-001A is still
  valuable only when it helps that chain prove source evidence, symbol context,
  artifact hashes, Git binding, review findings, and repair context end to end.

Non-goal:
  Do not select tasks only because they are easy to document, easy to describe on
  a resume, or convenient schema cleanup. Documentation should explain and
  preserve real implementation priorities; it should not replace capability
  delivery.
```

| Job-facing signal | Project evidence that should be built |
| --- | --- |
| Agent workflow engineering | LangGraph controlled state transitions, blocked/repair routes, checkpoint or resume evidence, and eval-gated completion |
| RAG for code generation | EvidencePack identity, source/symbol/BM25 evidence, readiness gates, source snippets, retrieval eval, and review binding |
| Tool and platform integration | MCP/API/dashboard surfaces with safe read-only routes first and approved write/runtime routes later |
| Production reliability | artifact lineage, Git binding, rollback hints, idempotent writes, pending-write recovery, budget limits, and failure reports |
| Observability and evaluation | trace events, dashboard projections, eval_report artifacts, false-success/false-block cases, and retrieval-quality regression tests |
| Runtime/product feedback | build artifacts, runtime evidence, trust binding, screenshots/logs when approved, and repair context from failures |

## V1 Knowledge And Evidence RAG Code Check

```text
Checked source:
  src/mod_agent/knowledge/models.py
  src/mod_agent/knowledge/source_registry.py
  src/mod_agent/knowledge/source_discovery.py
  src/mod_agent/knowledge/indexer.py
  src/mod_agent/knowledge/bm25_indexer.py
  src/mod_agent/evidence/models.py
  src/mod_agent/evidence/retriever.py
  src/mod_agent/evidence/readiness.py
  src/mod_agent/evidence/dense.py

Checked tests:
  tests/unit/test_knowledge_base.py
  tests/unit/test_evidence_retrieval.py
  tests/unit/test_collection_resolver.py
  tests/unit/test_artifact_contract.py

V1 implemented:
  Document, Chunk, ChunkRecord, SourceRegistry, SourceDiscovery classification
  code, stable source identity, content_hash and file_hash identity, incremental
  indexing skip and reindex behavior, symbol extraction/search, BM25
  indexing/query, EvidenceItem, EvidencePack artifact serialization,
  retrieval_methods_used, disabled_modes, timing, trace_refs,
  identity_schema_version, identity_field_mapping, and EvidenceReadinessClassifier
  blocking auxiliary-only evidence. The focused tests in this check do not
  exhaustively cover every SourceDiscovery classification branch.

Not implemented as controlled-agent V1 completion:
  ReferenceModLoader with repo_url/commit_sha/license/imported_at/
  usage_permission metadata, CommunityNoteLoader / Extractor, community_note,
  community_hint, raw_community_chat processing, RRF fusion in
  src/mod_agent/evidence/retriever.py, rerank in the controlled-agent retriever,
  citation/source-span retrieval eval, GitHubRepoImporter, DiscordExportImporter,
  Thunderstore/Nexus/forum importers, and general community crawler.
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
current RUNTIME-DENSE-API-BOUNDARY-001 status: completed; focused runtime/config/evidence/workflow/API tests passed and additional dashboard/runtime/smoke tests passed; broader `tests/unit` triage is the next quality-hardening track
current TRANSITION-001 status: completed; eval_report artifact coverage and Eval Gate Hard Routing are implemented. Failed `evaluation_gate` now writes a blocked `eval_report`, records eval gate blockers on the envelope/state, routes `evaluate` to `blocked`, and prevents `workflow_summary` from being written on gate failure. The gate covers false-success, false-block, false-continue, review correctness, dry-run safety, build/runtime claim boundaries, insufficient_baseline, stale_evidence, and missing_required_metric; focused eval/workflow/artifact/dashboard tests passed
current TRANSITION-002 status: completed; GitRepository now emits working tree snapshots, diff hashes, proposal/base revision binding metadata, dirty-tree policy, replay command, and rollback hint in git_change_record; dashboard consumes git_change_record; next upgrade is execution-layer proposal binding and dirty-tree stop/resume routing; focused git/artifact/dashboard/workflow/E2E tests passed
current TRANSITION-003 status: completed; PatchProposal now carries explicit change_units, proposal metadata context_pack, no_op_status, and rollback_hints; ProposalReviewer blocks missing or inconsistent proposal context including context_pack change_unit_ids drift; V2-PROP-001 remains the supporting upgrade for source snippets, symbol signatures, artifact hashes, and git base binding inside GTFO-VSLICE-001; dashboard and downstream MCP/domain/repair checkpoint tests consume the upgraded contract
current TRANSITION-004 status: completed; ControlledAgentMCPJsonRpcAdapter is a controlled-agent MCP JSON-RPC adapter for initialize, notifications/initialized, tools/list, and tools/call over the tool surface; it maps unknown or dangerous tool names to JSON-RPC method-not-found errors, preserves content/structuredContent/artifact_refs/trace_refs in tool results, and keeps confirmed_apply/run_game/copy_to_game_directory behind explicit approved routes; next upgrade is stdio/http transport integration, server process wiring, and approved write/runtime tool flows; focused MCP protocol/facade tests passed
current TRANSITION-005 status: completed; runtime_evidence and manual_evidence contracts now carry run_id, build_artifact_ref, build_artifact_hash, plugin_marker_binding, screenshot_refs, and non_goal_preservation; collect_runtime_evidence binds runtime payloads to the graph run and upstream build artifact; eval gate blocks real runtime success claims when required build/run/acceptance marker binding is missing or supplied non-goal preservation evidence reports violations or non-preserved status; focused runtime/eval/workflow/artifact/dashboard tests passed
current MISS-026E status: completed; runtime_evidence now carries `runtime_trust_binding`; GTFO automation records current-run log, feature_id, graph run_id, build artifact hash, plugin load marker, acceptance marker, runtime process identity, and screenshot/runtime artifact linkage checks; V1 acceptance and eval gate block GTFO automation claims unless the trust binding is trusted; focused runtime/eval/workflow/artifact/config tests passed and dashboard/MCP/E2E/runtime-probe affected tests passed; no real GTFO launch or gameplay success is claimed
current V1_TO_V2_TRANSITION status: completed for transition gates; MISS-026 live launch is deferred to V3 or explicit opt-in runtime validation. Settings-driven GTFO runtime graph selection and GTFO marker trust binding are tested without launching GTFO; V2 begins with GTFO-VSLICE-001 so the current working tree proves the evidence retrieval identity path controls a vertical LangGraph artifact-loop code-generation path. HITL evidence now includes checkpoint/static interrupt resume testing plus a dynamic interrupt/Command(resume) review gate before dry-run. Dynamic resume is driven by LangGraph checkpointer state; project workflow_checkpoint/resume_report artifacts are written after resume as audit binding. Reject still writes a blocked dry_run_result as evidence, but does not produce build_result, runtime_evidence, eval_report, or workflow_summary. Production persistent checkpoint backend work remains future work.
current STATE-001 status: completed; LOOP_HISTORY restored from rescue commit c43f4ec, evidence provenance refreshed, and E2E-001 scope boundary recorded
current SKILL-MCP-001 status: completed; `.agents/skills/mod-delivery-playbook/SKILL.md` created as a delivery Skill that feeds the source/test/artifact/LangGraph product loop
current E2E-001 status: completed; minimal planning-to-handoff chain is current-branch verified by tests/unit/test_mod_delivery_e2e.py with controlled temporary BetterHitFeedback source, controlled local build artifact verification, and real local runtime probe evidence
current E2E-002 status: completed; the controlled graph now runs planning_brief between plan_request and draft_feature_spec, writes `mod_planning_brief`, records it as a feature_spec upstream artifact, and FeatureSpecBuilder consumes planning brief handoff evidence/runtime guidance; focused planning/workflow/E2E/artifact/dashboard tests passed
current SKILL-SPLIT-001 status: completed; `.agents/skills/patch-review-playbook/SKILL.md` created as an expert review guide for patch proposals, diffs, evidence binding, permissions, risk, and handoff readiness
current SKILL-SPLIT-002 status: completed; `.agents/skills/runtime-diagnosis-playbook/SKILL.md` created as an expert runtime diagnosis guide for build/runtime evidence, runtime evidence modes, acceptance markers, repair routing, and handoff readiness
current SKILL-SPLIT-003 status: completed; `.agents/skills/hook-discovery-playbook/SKILL.md` created as an expert hook discovery guide for behavior decomposition, evidence-first hook discovery, hook option review, risk classification, and proposal/runtime diagnosis handoff
current SKILL-SPLIT-004 status: completed; `.agents/skills/repair-loop-playbook/SKILL.md` created as an expert repair guide for failed gate classification, bounded repair eligibility, evidence-bound repair scope, review re-entry, and repair/handoff routing
current SKILL-SPLIT-CLOSURE-001 status: completed; all five Skills validate, no template residue is present in HEAD for Skill directories, E2E-001 evidence remains discoverable, and the next step is using these guides to accelerate implementation rather than splitting more process
current PLANNING-BRIEF-001 status: completed; `.agents/skills/mod-planning-brief-playbook/SKILL.md` created for natural language Mod planning intent extraction, request_type classification, knowledge_query_plan planning, retrieved_experience recording, planning options, selected_plan, and feature_spec handoff guidance
current PLANNING-BRIEF-IMPL-001 status: completed; `mod_planning_brief` artifact contract and deterministic `ModPlanningBriefBuilder` now exist with focused tests for config-only, UI feedback, hook-required, and unknown / needs evidence handoffs; E2E-002 covers controlled graph integration and feature_spec handoff consumption; next upgrade is automated RAG retrieval, feature_spec generation, code generation, and real game runtime validation
current ARTIFACT-INTEGRITY-001 status: completed; ArtifactStore.read recomputes the stored envelope content hash, rejects tampered payload content even when the ArtifactRef hash still matches the stored artifact_hash, and rejects missing or unexpected envelope top-level fields; focused artifact tests passed
current ARTIFACT-INTEGRITY-002 status: completed; ArtifactStore.check_freshness and read_for_stage now detect stale deep upstream artifacts through recursive dependency traversal, while write-time and checkpoint-resume gates intentionally remain direct-freshness checks; focused artifact/checkpoint tests passed
current ARTIFACT-INTEGRITY-003 status: completed; ArtifactStore.write now preserves immutable revision files under per-type revision directories while maintaining read-validated latest artifact files for current dashboard/MCP views; focused artifact/dashboard/MCP/workflow/E2E tests passed
current ARTIFACT-PROD-001A status: completed; ArtifactStore.write now writes revision and latest files through same-directory temporary files plus os.replace and cleans temporary files when replacement fails; focused artifact/dashboard/MCP/workflow/E2E tests passed
current ARTIFACT-PROD-001B status: completed; ArtifactStore.write now records pending-write markers around revision/latest updates and recover_pending_writes restores latest from a valid immutable revision after an interrupted latest replace; focused artifact/dashboard/MCP/workflow/E2E tests passed
commit policy: manual commit after focused tests and status review
```

## Evidence Provenance Boundary

```text
history_restored:
  docs/audits/LOOP_HISTORY.md was restored into the current branch from rescue/dirty-worktree-20260702-120029 commit c43f4ec.
git_verifiable_current_branch:
  Claims backed by files currently present in this branch plus focused command output remain current evidence.
checkpoint_evidence:
  E2E-001 evidence files are part of the E2E-001 checkpoint; future changes that modify this claim require focused tests to be rerun.
historical_record_only:
  Claims whose only detailed support is docs/audits/LOOP_HISTORY.md are useful for reconstruction but must not be presented as current branch test evidence until the referenced files exist and focused tests are rerun.
known_current_branch_missing_references:
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
auto_coder_scope:
  .agents/skills/auto-coder/SKILL.md remains the platform-development Skill for DEV_SPEC.md-driven controlled code generation.
mod_delivery_playbook_scope:
  mod-delivery-playbook is planned as a user-facing delivery-process Skill for turning a mod request into feature_spec, evidence, proposal, review, build/runtime evidence, repair, and handoff artifacts.
patch_review_playbook_scope:
  patch-review-playbook is a process-only expert Skill for review procedure, evidence boundary checks, permission and path checks, runtime-risk review, and review output shape.
runtime_diagnosis_playbook_scope:
  runtime-diagnosis-playbook is a process-only expert Skill for build/runtime evidence diagnosis, evidence mode classification, acceptance signal checks, claim boundary control, and repair or handoff routing.
hook_discovery_playbook_scope:
  hook-discovery-playbook is a process-only expert Skill for behavior decomposition, evidence-first hook discovery, hook option review, risk classification, and proposal/runtime diagnosis handoff.
repair_loop_playbook_scope:
  repair-loop-playbook is a process-only expert Skill for failed gate classification, repair eligibility checks, evidence-bound minimal repair scope, review re-entry, and repair or handoff routing.
boundary:
  process Skills must not replace auto-coder, duplicate current product facts, copy interface schemas, embed test results, or become a second platform-development control plane.
runtime_skill_system_boundary:
  No runtime Skill registry, Skill selector, Skill loader, LangGraph selected-skill node injection, or Skill output validator is implemented by SKILL-SPLIT-001, SKILL-SPLIT-002, SKILL-SPLIT-003, or SKILL-SPLIT-004.
hook_automation_boundary:
  No automatic hook scanner, decompiler integration, runtime patch executor, or game binary scanner is implemented by SKILL-SPLIT-003.
repair_automation_boundary:
  No automatic repair executor, retry engine, review bypass, scope expansion, game launch, DLL copy, process control, or MCP write automation is implemented by SKILL-SPLIT-004.
```

## Planning Brief And Knowledge Boundary

```text
planned_mod_planning_brief_playbook:
  PLANNING-BRIEF-001 added a process-only Skill named mod-planning-brief-playbook after SKILL-SPLIT-004 and a Skill split closure audit.
purpose:
  Turn natural language mod ideas into a negotiated planning brief that can feed feature_spec and later controlled code generation.
inputs:
  natural language user request, current knowledge evidence, source/API/log/artifact evidence, restored historical records, and accumulated mod-delivery lessons.
outputs:
  mod_planning_brief, evidence questions, knowledge lookup plan, acceptance intent, risk notes, open questions, and feature_spec guidance.
required_responsibilities:
  - extract Mod planning intent from natural language.
  - classify request_type as config-only, UI feedback, gameplay behavior, runtime diagnostics, hook-required, or unknown / needs evidence.
  - generate knowledge_query_plan before claiming design or implementation direction.
  - retrieve historical experience and delivery lessons from current knowledge evidence, prior artifacts, restored history, and delivery lesson records.
  - identify risk, uncertainty, unavailable evidence, and required acceptance signals.
  - ask clarification questions or present selectable planning directions when the evidence is insufficient.
  - output mod_planning_brief as the handoff artifact.
  - hand mod_planning_brief to feature_spec generation without replacing feature_spec itself.
planned_artifact_name:
  mod_planning_brief
planned_mod_planning_brief_shape:
  user_intent:
    raw_request:
    normalized_goal:
    target_game:
    target_mod:
    expected_user_visible_behavior:
  knowledge_query_plan:
    source_types:
      - current_source
      - game_profile
      - prior_artifacts
      - delivery_lessons
      - symbol_search
      - docs
    queries:
  retrieved_experience:
    relevant_lessons:
    failed_patterns:
    reusable_patterns:
    unavailable_evidence:
  planning_options:
    - option:
      expected_complexity:
      hook_likelihood:
      risk:
      required_evidence:
      acceptance_signal:
  selected_plan:
    scope:
    constraints:
    non_goals:
    user_confirmed:
  handoff:
    feature_spec_guidance:
    hook_discovery_guidance:
    patch_review_notes:
    runtime_verification_expectations:
implementation_status:
  The planning Skill is implemented and validated.
  The `mod_planning_brief` artifact contract and deterministic builder are implemented and tested in PLANNING-BRIEF-IMPL-001.
  The builder's request_type classification gives the graph a stable handoff for later model-backed planning work.
  Next upgrades are natural-language-to-RAG extraction, automated historical experience retrieval, automated delivery lesson retrieval, runtime planning negotiation, automatic code generation guidance, and real game runtime validation.
  E2E-002 proves graph-integrated handoff for `mod_planning_brief` fields consumed by FeatureSpecBuilder.
  Product facts, current state, schemas, test results, and evidence payloads stay in source, docs, tests, and artifacts where downstream consumers can inspect them.
```

## Post E2E-001 Optional Capability Policy

```text
Capability recovery targets:
  - production dense retrieval beyond the tested vector_store bridge
  - full multimodal ingestion and caption pipeline
  - dashboard/API service work beyond local summaries
  - MCP write/runtime operations with approval and rollback evidence
  - run_game and copy_to_game_directory operations through the GTFO runtime automation interface
  - large-scale benchmark harnesses

Immediate recovery focus:
  - bind runtime evidence to feature/build/run ids and live GTFO markers
  - turn MCP inspection into approved write/runtime routes
  - promote local artifact inspection API into service-ready dashboard/API work
  - use expert Skills to accelerate implementation rather than split more process
```

## Unresolved R Gates

| Task | Source Finding | Status | Blocking Reason |
| --- | --- | --- | --- |
| None | post R-009-HARDENING-001 refresh | clear | R-001 through R-013 and R-009-HARDENING-001 are completed; remaining open missing rows are future task groups, not active Review Repair Queue blockers |

## Test Health

```text
latest focused E2E-001 suite:
  .venv\Scripts\python.exe -m pytest tests/unit/test_mod_delivery_e2e.py -q --tb=short
  result: 1 passed

latest affected E2E-001 workflow/build/runtime/artifact suite:
  .venv\Scripts\python.exe -m pytest tests/unit/test_mod_delivery_e2e.py tests/unit/test_workflow_graph.py tests/unit/test_runtime_probe.py tests/unit/test_runtime_evidence.py tests/unit/test_build_adapter.py tests/unit/test_artifact_contract.py -q --tb=short
  result: 56 passed

E2E-001 test status:
  Focused E2E/workflow/build/runtime/artifact tests pass.
  Broader unit baseline triage remains a quality-hardening track after the focused chain.

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
| Dense/vector/multimodal features need production acceleration | Medium | BM25/symbol/deterministic are stable foundations; Q-022 and RUNTIME-DENSE-API-BOUNDARY-001 provide the vector_store bridge and dense failure policy; next track is production dense/RAG operation with eval evidence |
| Claims can outrun implemented evidence | High | Completion levels require tests and artifacts |
| Fake/local execution artifacts need upgrade routing | High | Every artifact includes `execution_mode=fake|local|supplied_output|real`; fake/local evidence should route into real build/runtime probes when the feature requires it |
| External review found P0/P1 structural issues after several Q loops | High | Review Repair Queue is completed through R-009-HARDENING-001; any new P0/P1 review finding still supersedes ordinary Q feature work |
| PROJECT_STATE may overclaim because it is generated by the agent itself | High | Verify claims against git status, code, tests, artifacts, and command output |
| Queue may become RAG-first despite capability-first spec direction | High | Prioritize runnable controlled loop and active repair gates before deeper optional Knowledge Hub expansion |
| Historical evidence may be mistaken for current branch evidence | High | Use the Evidence Provenance Boundary: current claims require present files and rerun tests; LOOP_HISTORY is reconstruction support |
| E2E-001 controlled local proof needs GTFO runtime evidence recovery work | High | E2E-001 proves the controlled local source/build-artifact/runtime-probe chain; RUNTIME-DENSE-API-BOUNDARY-001 adds GTFO runtime automation interface tests; MISS-026 recovery target is marker-bound GTFO runtime evidence with explicit launch approval |
| Focused E2E tests need full-suite hardening | High | E2E-001 focused and affected tests passed; broader unit baseline triage is an active quality-hardening track |
| Platform capabilities need recovery work on the delivery chain | High | Production dense/RAG, full multimodal, dashboard/API polish, write MCP, automatic game operations with approval, and large benchmarks are capability recovery targets that should attach to the tested E2E-001 path |
| Artifact integrity can regress when artifact semantics change | Medium | Keep revision-path, latest-pointer, read-time hash, recursive freshness, direct checkpoint freshness, and audit/report-only allow_stale_upstreams tests in scope for future artifact changes |
| ArtifactStore production storage hardening remains a recovery target | Medium | Atomic same-directory temporary file replacement and manual pending-write recovery are implemented and tested by ARTIFACT-PROD-001A/B; next storage-hardening work adds automatic startup/preflight recovery invocation, states without valid pending marker and revision, cross-process write locking, revision manifest/index files, historical revision query APIs, old-ref migration, and revision garbage collection |
| Retrieval authority and tokenizer changes can regress planning safety or ranking behavior | Medium | R-009-HARDENING-001 completed the authority default, deterministic authority grant, raw dict provenance, dashboard authority display, and shared tokenizer work; future retrieval changes must keep focused sparse/query and planning tests in scope |

## Latest Loop Summary

```text
task: RUNTIME-DENSE-API-BOUNDARY-001
status: completed
files_changed:
  config/settings.yaml
  src/core/settings.py
  src/mod_agent/api/http_server.py
  src/mod_agent/evidence/dense.py
  src/mod_agent/evidence/retriever.py
  src/mod_agent/runtime/gtfo_automation.py
  src/mod_agent/runtime/__init__.py
  src/mod_agent/workflow/graph.py
  tests/unit/test_config_loading.py
  tests/unit/test_evidence_retrieval.py
  tests/unit/test_gtfo_runtime_automation.py
  tests/unit/test_mod_agent_http_api.py
  tests/unit/test_vector_store_dense_provider.py
  tests/unit/test_workflow_graph.py
  docs/PROJECT_STATE.md
  docs/IMPLEMENTATION_QUEUE.md
  docs/SPEC_COVERAGE_MATRIX.md
  docs/V1_ACCEPTANCE_AUDIT.md
behavior:
  GTFORealRuntimeAutomationRunner now provides a GTFO real runtime automation interface with explicit allow_game_launch gating, executable/working-directory/log-path validation, persistent log marker collection, screenshot capture with timeout, failure payload capture, and marker/liveness separation.
  Settings now parse runtime.gtfo.acceptance_markers and build_graph can select make_gtfo_runtime_evidence_factory_from_settings when runtime.gtfo.enabled is true and no runtime_evidence_factory is explicitly supplied.
  build_graph settings-driven GTFO runtime selection keeps allow_game_launch false by default; the graph-level unauthorized path writes failed runtime_evidence, does not call launcher/log/screenshot hooks, does not write workflow_summary, and blocks accepted final status.
  GTFO runtime_trust_binding now binds configurable acceptance markers to current-run logs, feature_id, graph run_id, build artifact hash, plugin load marker, runtime process identity, and screenshot/runtime artifact linkage before V1 accepted status can be reached.
  VectorStoreDenseRetrievalProvider bridges existing EmbeddingFactory and VectorStoreFactory, filters returned ids to known chunks, sorts by normalized score, and can be injected into the graph; dense_required can block evidence when a required dense route fails.
  config/settings.yaml and Settings parse runtime.gtfo.screenshot_timeout_seconds, runtime.gtfo.acceptance_markers, and retrieval.dense_failure_policy.
  ModAgentHttpApi provides an artifact inspection API over ArtifactStore and DashboardProjectionBuilder, exposes health/features/artifacts/dashboard/status routes, returns required_approval for write/runtime POST routes, and rejects absolute artifact_root unless explicitly allowed.
  This creates tested interface behavior for runtime/dense/API recovery work; approved GTFO launch evidence, production runtime automation, production RAG, production HTTP API, production auth, production dashboard, and cloud deployment remain capability recovery targets.
validation:
  .venv\Scripts\python.exe -m pytest tests/unit/test_gtfo_runtime_automation.py tests/unit/test_config_loading.py tests/unit/test_runtime_evidence.py tests/unit/test_transition_eval_gate.py tests/unit/test_artifact_contract.py tests/unit/test_dashboard_projection.py tests/unit/test_workflow_graph.py -q --tb=short -> 89 passed
  .venv\Scripts\python.exe -m pytest tests/unit/test_gtfo_runtime_automation.py tests/unit/test_config_loading.py tests/unit/test_evidence_retrieval.py tests/unit/test_vector_store_dense_provider.py tests/unit/test_workflow_graph.py tests/unit/test_mod_agent_http_api.py -q --tb=short -> 55 passed
  .venv\Scripts\python.exe -m pytest tests/unit/test_dashboard_projection.py tests/unit/test_runtime_evidence.py tests/unit/test_runtime_probe.py tests/unit/test_smoke_imports.py -q --tb=short -> 36 passed, 1 warning
tests:
  focused runtime/config/evidence/workflow/API tests and additional dashboard/runtime/smoke tests passed; broader `tests/unit` is not green.

  Broader test result:
  `.venv\Scripts\python.exe -m pytest tests/unit -q --tb=short --disable-warnings --maxfail=20` -> 20 failed, 1023 passed, 4 skipped, 2 warnings before maxfail stop.
  First observed failure groups: `tests/unit/test_batch_processor.py` timing assertions, `tests/unit/test_embedding_providers_smoke.py` OpenAI/Azure embedding initialization expectations, `tests/unit/test_list_collections.py` include_stats call shape, `tests/unit/test_loader_pdf_contract.py` image metadata when PyMuPDF is unavailable, `tests/unit/test_protocol_handler.py` duplicate `query_knowledge_hub` registration, and `tests/unit/test_ragas_evaluator.py` missing `langchain_community.chat_models.vertexai`.
next:
  Triage the broader `tests/unit` failures as a quality-hardening track. Continue MISS-026 only with explicit opt-in approved GTFO launch smoke if real game process launch, persistent logs, plugin markers, process identity, build artifact hash, and screenshot/runtime artifact linkage evidence are the goal.
```

## Eval Gate Hard Routing

```text
task: TRANSITION-001 Eval Gate Hard Routing
status: completed
coverage:
  EVAL-003
  EVAL-004
source:
  src/mod_agent/evaluation/gate.py
  src/mod_agent/workflow/transitions.py
  src/mod_agent/workflow/graph.py
  tests/unit/test_transition_eval_gate.py
  tests/unit/test_workflow_graph.py
artifact_contract:
  eval_report uses the existing contract and now writes envelope status `blocked` when `evaluation_gate.status` is `failed`.
  evaluation_gate blockers are persisted on the eval_report envelope.
LangGraph_routing:
  evaluate now uses route_after_evaluate.
  Failed evaluation_gate routes to blocked instead of done.
  route_after_evaluate only treats stage=evaluation and EVAL_GATE_* blockers as blocking route inputs.
  workflow_summary is not written when evaluation_gate fails.
eval_cases:
  false-success
  false-block
  false-continue
  review correctness
  dry-run safety
  build/runtime claim boundaries
  insufficient_baseline
  stale_evidence
  missing_required_metric
validation:
  .venv\Scripts\python.exe -m pytest tests/unit/test_transition_eval_gate.py tests/unit/test_workflow_graph.py tests/unit/test_artifact_contract.py tests/unit/test_dashboard_projection.py -q --tb=short -> 52 passed
acceptance:
  Manual runtime evidence with acceptance_verified=True but execution_mode=manual fails the runtime claim boundary case, writes blocked eval_report, creates blocked_report, and does not write workflow_summary.
  Injected evaluation_context baseline_status=insufficient_baseline fails the eval gate, writes blocked eval_report, creates blocked_report, and does not write workflow_summary.
next:
  Runtime Evidence Binding is completed by TRANSITION-005; GTFO marker trust binding is completed by MISS-026E, while real approved launch evidence remains opt-in work.
```

## Runtime Evidence Binding

```text
task: TRANSITION-005 Runtime Evidence Binding
status: completed
commit: 04652a4 TRANSITION-005: bind runtime success claims to runtime evidence context
coverage:
  RUN / runtime evidence contract
  WF / runtime evidence graph binding
  EVAL / runtime success claim boundary
source:
  src/mod_agent/runtime/evidence.py
  src/mod_agent/runtime/probe.py
  src/mod_agent/runtime/__init__.py
  src/mod_agent/workflow/graph.py
  src/mod_agent/evaluation/gate.py
  src/mod_agent/artifacts/registry.py
  tests/unit/test_runtime_evidence.py
  tests/unit/test_transition_eval_gate.py
  tests/unit/test_workflow_graph.py
  tests/unit/test_runtime_probe.py
  tests/unit/test_artifact_contract.py
  tests/unit/test_dashboard_projection.py
artifact_contract:
  runtime_evidence and manual_evidence require run_id, build_artifact_ref, build_artifact_hash, plugin_marker_binding, screenshot_refs, and non_goal_preservation.
LangGraph_routing:
  collect_runtime_evidence binds runtime payloads to state["run_id"] and the upstream build_result ArtifactRef before writing runtime_evidence.
  Existing runtime acceptance routing remains: verified acceptance continues to evaluate; unverified evidence routes to repair.
eval_boundary:
  Real runtime success claims require execution_mode=real, real_runtime_performed=True, acceptance_verified=True, run_id, valid build_artifact_ref, matching build_artifact_hash, and observed plugin markers bound to acceptance_contract.acceptance_criteria.
  Runtime success claims are blocked when supplied non_goal_preservation evidence reports violations or non-preserved status.
validation:
  .\.venv\Scripts\python.exe -m pytest tests/unit/test_runtime_evidence.py tests/unit/test_transition_eval_gate.py tests/unit/test_workflow_graph.py tests/unit/test_runtime_probe.py tests/unit/test_artifact_contract.py tests/unit/test_dashboard_projection.py -q --tb=short -> 65 passed
allowed_claims:
  Runtime evidence payloads now carry graph run and build artifact binding.
  Eval gate consumes runtime binding fields before allowing real runtime success claims.
forbidden_claims:
  Settings-driven GTFO runtime graph selection and GTFO runtime_trust_binding are tested without launching GTFO.
  Configured acceptance markers remain plugin/self-report signals, but V1 accepted status now requires trusted current-run logs, feature_id, graph run_id, build artifact hash, plugin load marker, runtime process identity, and screenshot/runtime artifact checks.
  This does not prove non-goal behavior is actively verified; it only consumes supplied non-goal preservation evidence.
  This does not complete production runtime automation, dense/RAG production integration, API/dashboard service work, MCP transport, or baseline metric collection.
next:
  Explicit opt-in approved GTFO launch smoke if real GTFO runtime evidence is selected; otherwise select one explicit recovery target from docs/V1_TO_V2_TRANSITION.md.
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
  The V1 audit records current status as implemented_with_upgrade_tracks.
  Dense retrieval now has a bridge path from Q-022 contract work into vector_store provider hardening.
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
next:
  Add real/manual/supplied runtime acceptance E2E evidence and feed it into V1 acceptance routing.
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
next:
  Implement automated real runtime execution and real runtime evidence collection on the tested branch.
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
next:
  Promote fake/local, manual, and supplied fixture-style evidence into automated real runtime execution where runtime acceptance is required.
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
  V1 contract path is verified for the current controlled contract path; V2 capability expansion remains gated by recovery targets.
  Real runtime evidence branch is closed by MISS-022 and feeds MISS-026 GTFO runtime evidence work.
  Production runtime automation proceeds through explicit launch approval, real GTFO evidence collection, and focused implementation tests.
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
