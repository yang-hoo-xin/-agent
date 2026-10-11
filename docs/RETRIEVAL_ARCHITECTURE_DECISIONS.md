# Retrieval Architecture Decisions And Open Gaps

## 1. Purpose

This document preserves the retrieval and Agentic RAG decisions discussed for
RepoForge. It separates:

- implemented facts;
- design decisions;
- hypotheses that still require experiments;
- external project patterns worth studying;
- specification material that must not be executed directly.

It is not an implementation-completion record. Experimental claims become
project facts only after the protocol in `docs/RETRIEVAL_VALIDATION_PLAN.md`
has produced reproducible results.

## 2. Current Implemented Baseline

Current source and focused tests already provide a controlled-agent foundation:

- local source registration and stable source identity;
- content/file hash based incremental indexing;
- exact symbol indexing and lookup;
- local BM25 indexing and query;
- deterministic EvidencePack construction;
- source authority and readiness gates;
- optional dense-provider contracts that remain auxiliary;
- evidence binding from retrieval into planning, proposal, review, and repair.

This baseline proves coexistence of deterministic, symbol, and BM25 mechanisms.
It does not prove that any mixed retrieval strategy improves end-to-end code
generation over an `rg`-only baseline.

## 3. Missing Or Unproven Capabilities

The following items are missing or lack production-quality evidence:

1. Agent-controlled decision about whether retrieval is needed.
2. Query-class routing among `rg`, symbol/AST, BM25, and dense retrieval.
3. Retrieval-result relevance or sufficiency scoring calibrated on real tasks.
4. Query rewrite followed by a second retrieval attempt.
5. Multi-step or multi-hop retrieval.
6. Controlled-agent RRF fusion.
7. Controlled-agent reranking.
8. Complete citation and source-span evaluation.
9. Ablation experiments comparing retrieval configurations.
10. Production dense cache, batching, incremental refresh, latency, and cost data.
11. Reliable workspace-change synchronization for disposable code indexes.
12. Rename/delete handling and stale-result fallback to live search.
13. Isolation between branches, worktrees, and index namespaces.
14. Revalidation of every consumed code result against current file content.
15. Measured downstream effects on Hook selection, wrong-file edits, review
    blockers, and final task success.

These are implementation or evaluation tasks, not evidence that the project
must adopt every technique listed above.

## 4. Differentiating Product Decisions

The project can distinguish itself through source-specific retrieval authority,
not by claiming that BM25 plus grep is novel.

### 4.1 Select Retrieval By Data Structure

- Current code uses exact and structure-aware tools: `rg`, live file reads,
  symbol lookup, AST/LSP, and call-graph evidence where available.
- Community notes, historical sessions, release notes, and fragmented technical
  discussion use lexical retrieval such as BM25/FTS with time and source filters.
- Dense retrieval is evaluated only for vague intent or semantic mismatch where
  deterministic retrieval demonstrably misses relevant evidence.

### 4.2 Separate Relevance From Authority

A high retrieval score does not grant permission to modify code.

- Current `target_source` and verified API/source evidence may ground a patch.
- Reference implementations and community notes generate hypotheses and search
  directions.
- Raw community chat is never direct patch authority.
- Build/runtime logs are authoritative only for the diagnostics they observed.

### 4.3 Require Cross-Source Verification

A community or reference-project Hook hint must be verified against current
source, current decompiled API, or current runtime evidence before it can affect
an edit target.

### 4.4 Make Index Freshness Explicit

- Persistent BM25 indexes are appropriate for slower-changing historical and
  community material.
- Current code truth comes from the live workspace.
- Symbol/AST/call-graph indexes are disposable navigation accelerators.
- A code-index hit is re-read and re-hashed before it enters an EvidencePack.
- Stale, missing, renamed, or branch-mismatched results fall back to live search.

### 4.5 Resolve Source Conflict By Authority

When community guidance conflicts with current source or verified API evidence,
the current source/API evidence wins. Scores from different source classes are
not blindly merged into one authority ranking.

### 4.6 Measure Downstream Code-Agent Effects

Retrieval quality is judged by both retrieval metrics and delivery outcomes:

- correct Hook and source-span recall;
- wrong-file modification rate;
- review-blocker precision;
- final controlled-task success;
- latency, model/API calls, tokens, and monetary cost.

## 5. Recommended Three-Layer Architecture

### Layer 1: Persistent Historical And Community Retrieval

Purpose: recover scattered experience, discussions, prior decisions, release
notes, and curated community claims.

Primary mechanisms:

- local archive with source, timestamp, session/thread, author, and provenance;
- BM25/FTS lexical index;
- time, project, version, source-type, and confidence filters;
- incremental hashing and append/update handling;
- read-only output with `requires_verification=true` by default.

This layer proposes search terms, Hook hypotheses, failure explanations, and
reference patterns. It cannot authorize edits.

### Layer 2: Live Code And API Retrieval

Purpose: locate the exact current implementation and verify patch targets.

Primary mechanisms:

- `rg` and direct live file reads as the freshness baseline;
- symbol/AST/LSP/call-graph navigation for structural queries;
- disposable incremental indexes scoped by repository, branch/worktree, and
  index version;
- file existence, content hash, symbol identity, and source-span revalidation
  immediately before evidence consumption.

This layer supplies patch-grounding evidence when authority and freshness checks
pass.

### Layer 3: Evidence Decision And Control

Purpose: decide whether, where, and how retrieval is used and whether its output
is sufficient for the controlled delivery chain.

Responsibilities:

- classify the query and select retrieval tools;
- keep source-class results and authority separate;
- build EvidencePack citations and source spans;
- enforce freshness, authority, readiness, and cross-source verification;
- retry or rewrite within an explicit budget;
- route insufficient evidence to blocked/repair/clarification states;
- expose decisions to proposal review, eval, traces, dashboard, and MCP.

LangGraph remains the workflow control plane. Retrieval does not approve or
apply patches.

## 6. External Project Patterns To Study

These projects are architectural references, not proof that their choices fit
this project.

### Katok

Study for historical/community material:

- local archive design;
- time/session filtering;
- SQLite FTS/BM25 retrieval;
- read-only access to communication history.

Repository: <https://github.com/NomaDamas/katok>

### Semble

Study for coexistence of literal search and code-aware retrieval:

- code-aware chunks;
- BM25 plus static embeddings;
- fusion as an optional retrieval mechanism;
- explicit use of grep for exhaustive literal matching.

Repository: <https://github.com/MinishLab/semble>

### CodeSeek

Study for structural code navigation:

- AST-aware indexing;
- symbol and dependency relationships;
- BM25, dense retrieval, graph signals, fusion, and reranking;
- incremental hash and Git-aware refresh mechanisms.

Repository: <https://github.com/CodeBendKit/codeseek>

### What This Project Retains As Its Own Design

- EvidencePack lineage;
- explicit source authority;
- evidence readiness;
- source conflict resolution;
- proposal review and permission gates;
- build and runtime evidence boundaries;
- eval-gated completion;
- controlled MCP exposure.

## 7. Specification Restructuring Decision

The current `DEV_SPEC.md` and `EVIDENCE_RAG_MCP_SPEC.md` contain useful detail,
but repeated additions and imported legacy blueprints make them unsuitable as a
single linear execution plan.

The target structure is:

1. `DEV_SPEC.md`: concise normative product and control-plane specification.
2. `EVIDENCE_RAG_MCP_SPEC.md`: concise normative retrieval/evidence subsystem
   specification.
3. `docs/RETRIEVAL_VALIDATION_PLAN.md`: preregistered experiments and metrics.
4. `docs/references/`: imported or superseded blueprints retained for design
   reference without execution authority.
5. `docs/PROJECT_STATE.md`: current verified state.
6. `docs/IMPLEMENTATION_QUEUE.md`: unfinished executable work only.
7. `docs/SPEC_COVERAGE_MATRIX.md`: mapping from requirements to implementation
   and evidence.
8. `docs/audits/`: frozen historical evidence and acceptance records.

Until physical extraction is completed, imported/legacy sections inside either
SPEC are reference-only. They cannot create queue work or override the new
normative rules.

## 8. Decisions Versus Hypotheses

Accepted design decisions:

- retrieval strategy is source-specific;
- relevance and authority are separate;
- live workspace validation is required for code evidence;
- community evidence is planning-only until cross-verified;
- LangGraph and review/eval gates retain execution authority;
- experimental techniques do not enter the production path without measured
  benefit.

Unproven hypotheses:

- BM25 improves recall for community/history-dependent tasks;
- symbol/AST navigation improves Hook recall beyond `rg` alone;
- dense retrieval finds additional correct Hooks;
- source-aware hybrid routing reduces wrong-file edits;
- Agentic rewrite/retry improves final success enough to justify its cost.

The hypotheses are defined and gated in
`docs/RETRIEVAL_VALIDATION_PLAN.md`.
