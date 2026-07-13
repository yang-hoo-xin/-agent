# Evidence RAG / MCP Sub-Spec

Daily execution starts with `docs/ACTIVE_PRODUCT_CONTRACT.md`. This file is read
only when the selected work affects retrieval, knowledge, or MCP. Sections 0-3
are normative subsystem detail; section 4 and later material is reference-only.

This file defines the Evidence Retrieval, Knowledge, and MCP subsystem inside
the Evidence-Grounded Controlled Code Generation Agent Platform.

## 0. Validation-First Normative Override

This section and sections 1-3 are the normative subsystem specification. They
supersede imported, repeated, legacy, or generic RAG material later in this
file whenever that material prescribes a product, implementation phase, or
technology choice.

The imported technical blueprint beginning at section 4 is reference-only. It
may supply implementation patterns after a current requirement and experiment
justify them. It is not an execution plan and does not establish that the
project needs dense retrieval, hybrid fusion, RRF, reranking, multimodal
ingestion, generic question answering, a separate RAG dashboard, or a separate
RAG product.

Current decision sources:

1. `DEV_SPEC.md` section 0.0A for product-level validation-first authority.
2. `docs/RETRIEVAL_ARCHITECTURE_DECISIONS.md` for the three-layer architecture,
   source authority, known gaps, and external patterns to study.
3. `docs/RETRIEVAL_VALIDATION_PLAN.md` for H1-H5, experimental arms, metrics,
   freshness tests, and promotion/stopping rules.
4. Current source and focused tests for exact implemented identifiers and
   behavior.
5. Current state, queue, and coverage documents for execution status.

Normative retrieval baseline:

- current code: `rg` plus live reads, with disposable symbol/AST navigation and
  mandatory live revalidation;
- community/history: persistent BM25/FTS with provenance, time/session filters,
  and planning-only authority until cross-verified;
- dense/RRF/rerank: experimental auxiliary paths;
- LangGraph, EvidencePack readiness, proposal review, build/runtime evidence,
  and eval gates retain control authority.

## 1. Reading Order And Authority

For RAG/MCP implementation work, read in this order:

1. `DEV_SPEC.md` for parent product control: LangGraph workflow, artifact contracts, evidence-before-edit, review, dry-run, build, runtime, repair, eval, dashboard, permission, and rollback.
2. This file, sections 0-3, for normative subsystem rules.
3. `docs/RETRIEVAL_ARCHITECTURE_DECISIONS.md` and
   `docs/RETRIEVAL_VALIDATION_PLAN.md` for architecture and experiments.
4. Current source and tests for exact identifiers, schemas, behavior, and
   already-implemented boundaries.
5. `docs/IMPLEMENTATION_QUEUE.md`, `docs/SPEC_COVERAGE_MATRIX.md`, and
   `docs/PROJECT_STATE.md` for active task selection and coverage status.
6. Section 4 and later imported material only for non-normative implementation
   reference after the preceding authorities justify the work.

Authority split:

| Area | Primary authority | Notes |
| --- | --- | --- |
| Product identity and delivery loop | `DEV_SPEC.md` | Evidence-Grounded Controlled Code Generation Agent Platform remains the product. |
| RAG/MCP normative architecture | Sections 0-3 plus the architecture and validation documents | Defines source-specific retrieval, authority, freshness, EvidencePack, experiments, and controlled MCP boundaries. |
| Imported implementation patterns | Section 4 and later legacy material | Reference-only; use a pattern only after a current requirement and validation decision justify it. |
| Exact names and behavior | Current source/tests | Do not guess identifiers; read code and tests. |
| Task execution order | docs queue/state/matrix | This file defines capability direction, not a second queue. |

Conflict resolution:

1. Source code and focused tests decide exact implemented identifiers and contracts.
2. `DEV_SPEC.md` decides product boundary and safety gates.
3. Sections 0-3 plus the architecture and validation documents decide RAG/MCP
   technical direction.
4. Section 4 and later imported material may suggest implementation patterns but
   cannot decide scope, phase, or technology adoption.

This order is intentional: detail volume is not execution authority. Generic
blueprints remain useful references, but project-specific evidence and
validation decide what is built.

## 2. Integration Rules

### 2.1 Reuse Applicable RAG/MCP Patterns

Reuse the imported blueprint's engineering patterns only where a current
requirement and validation result justify them:

- loader, parser, splitter, transform, encoder, store, retriever, fusion, rerank, response assembly, trace, eval, and dashboard pipeline structure;
- provider abstractions for LLM, embedding, vector store, splitter, reranker, evaluator, vision model, and MCP transport;
- local-first persistence, metadata, hash, incremental update, source attribution, and observability discipline;
- JSON-RPC/MCP lifecycle, stdio cleanliness, `tools/list`, `tools/call`, `content`, `structuredContent`, error mapping, and client simulation tests;
- multimodal image-to-text strategy as an evidence enhancement path, not as proof by itself.

Pluggability helps component replacement and engineering extension. It does not
solve patch authority, evidence authority, workflow control, runtime risk, or
whether an MCP route may perform writes.

### 2.2 Product-Semantics Rewrite

| Imported blueprint concept | This project mapping | Reason |
| --- | --- | --- |
| User query | Feature/change intent plus EvidenceQuery | 本项目不是普通问答入口。 |
| Retrieved answer | EvidencePack plus evidence summary | 输出服务 proposal/review/repair，不直接批准修改。 |
| ResponseBuilder | EvidencePackBuilder / CitationBuilder / MCP result formatter | Citation 保留，最终 answer 权威被移除。 |
| `query_knowledge_hub` | Optional/later browsing view; `retrieve_evidence` first | 知识查询可以存在，但不能成为 patch authority。 |
| General MCP server | Controlled-agent MCP read/report surface | MCP 暴露 graph/artifact/eval 状态，不绕过 LangGraph。 |
| Knowledge dashboard | Workflow/evidence/proposal/review/eval dashboard subpages | Dashboard 主视角是 agent delivery，不是单独知识库产品。 |
| RAG eval | Evidence Retrieval Eval | 增加 readiness accuracy、false-continue、false-block、evidence sufficiency、review binding。 |
| Generic ingestion source | Source-authority-classified knowledge source | 每条证据必须说明是否能支持 patch。 |

### 2.3 Non-Negotiable Boundaries

RAG/MCP must not:

- approve patches by itself;
- write source files directly;
- launch runtime directly;
- copy artifacts into game directories directly;
- treat raw community chat as patch evidence;
- treat screenshots alone as hook correctness proof;
- bypass LangGraph, artifact store, review gate, runtime gate, eval gate, permission policy, or rollback policy;
- treat Skill text as runtime product truth.

## 3. Execution Overlay For This Project

### 3.1 Task Coordination

RAG/MCP work does not use a second task system.

- Implementation tasks enter `docs/IMPLEMENTATION_QUEUE.md`.
- Coverage and verification status enter `docs/SPEC_COVERAGE_MATRIX.md`.
- Current project state and selected next task enter `docs/PROJECT_STATE.md`.
- Code changes must connect to source files, focused tests, artifacts, and graph/dashboard/eval behavior where applicable.

Every RAG/MCP task must declare:

- controlled-agent stage affected: planning, evidence, proposal, review, dry-run, build, runtime, repair, eval, dashboard, or external tool surface;
- artifact inputs and outputs: `feature_spec`, `evidence_pack`, `implementation_plan`, `patch_proposal`, `proposal_review`, `build_report`, `runtime_report`, `repair_plan`, `eval_report`, dashboard projection, or MCP result;
- source authority required before a patch can be proposed;
- focused tests that prove the new behavior.

### 3.2 Job-Oriented Engineering Intent

The RAG/MCP subsystem should demonstrate vertical code-generation agent depth:

- evidence-grounded code generation over generic chatbot answers;
- retrieval quality, source attribution, and false-continue / false-block evaluation;
- controlled external tool surfaces through MCP;
- artifact lineage from evidence to proposal to review to repair;
- production constraints such as approval, rollback, idempotency, observability, degraded mode, and safe failure routing;
- local/private workflow realism suitable for game mod development and enterprise-style agent engineering.

### 3.3 Knowledge Source Phase Schedule

| Item | Phase | Boundary |
| --- | --- | --- |
| Knowledge Base foundation | V1 / Phase C | Local source, artifact, log, and domain-doc indexing; SourceRegistry; metadata; incremental hash. Foundation only, not complete RAG. |
| Evidence RAG foundation | V1 / Phase D | Deterministic retrieval, symbol retrieval, BM25, EvidencePack, readiness gate, evidence-before-edit. |
| RAG-M0/M1 contracts and local retrieval | V1 | Document / Chunk / EvidenceItem / EvidencePack / Retriever contracts; exact/symbol/BM25 local retrieval; no embedding required. |
| artifact/log/domain-doc loader deepening | Validation-gated supporting item | Improve loaders only where a registered case requires the source and the result supports controlled-agent evidence flow. |
| Curated GitHub reference mods | After relevant validation cases justify ingestion | Hand-curated local public mod projects enter as `reference_mod`; default `authoritative_for_patch=false`. |
| ReferenceModLoader metadata contract | Validation-gated | Must record `repo_url`, `commit_sha`, `license`, `imported_at`, and `usage_permission`. |
| Curated community notes | H1 fixture first; production after H1 decision | Curated `community_note` / `community_hint` only; raw chat remains raw-only. |
| CommunityNoteLoader / Extractor | Validation-gated | Process the minimum curated notes required by H1, not full raw chat. Keep claim metadata and verification state. |
| RAG support for GTFO-VSLICE-001 | V2 | Evidence RAG must support hook discovery, implementation_plan, proposal evidence binding, review gate, and repair context. |
| Retrieval evaluation baseline | V2-EVAL-001 | Versioned golden cases, Hook/file correctness, false-continue/false-block, latency, and cost metrics. |
| Deterministic/source-aware ablation | V2-RET-001A | Arms A-D and H1/H2/H4; no authority promotion by score. |
| Dense auxiliary ablation | V2-RET-001B | Arm E and H3 only after deterministic benchmark stability. |
| RRF / Agentic routing ablation | V2-RET-001C | Arms F/G and H5; production adoption depends on measured downstream benefit. |
| Citation / source-span retrieval eval | V2-EVAL-001 / V2-RET-001 | Retrieval trace, golden retrieval eval, citation accuracy, false-continue, and false-block metrics. |
| GitHubRepoImporter | V3 | Allowlisted, license-aware, source-attributed repo import with commit-hash incremental update. |
| DiscordExportImporter | V3 / V3+ | Extract curated notes from exported Discord data; raw chat still does not enter patch context. |
| Thunderstore / Nexus / forum importer | V3+ | Optional external source expansion with ToS, rate limit, attribution, copyright, and data-quality controls. |
| General community crawler | V3+ / deferred | Large-scale crawling, clustering, and automated claim extraction are not V2 blockers. |

### 3.4 Source Authority Rules

| Source type | Patch authority | Allowed use |
| --- | --- | --- |
| `target_source` | Can be authoritative when current and hashed | Direct patch grounding, symbol lookup, implementation constraints. |
| `decompiled_api` | Can be authoritative with provenance | API shape, signatures, hook discovery, compatibility constraints. |
| `prior_artifact` | Contextual authority within artifact lineage | Feature history, proposal/review/build/runtime/eval context. |
| `build_log` / `runtime_log` | Authoritative for observed diagnostics | Repair grounding, failure classification, acceptance evidence. |
| `domain_note` | Supporting authority | Domain constraints when curated and attributed. |
| `reference_mod` | Default `authoritative_for_patch=false` | Implementation pattern, hook hint, build hint; never direct proof of target safety. |
| `community_note` / `community_hint` | Default `planning_only` and `authoritative_for_patch=false` | Hypothesis generation and planning hints requiring verification. |
| `raw_community_chat` | `raw_only` | Storage or later extraction only; never patch context. |
| `screenshot` / image evidence | Supporting evidence | UI/runtime observation with confidence and limitations; not hook proof alone. |

Community note records must preserve `claim`, `claim_type`, `source_locator`, `timestamp`, `confidence`, and `requires_verification`.

### 3.5 Source-Type-Specific Chunking

For `target_source` and `decompiled_api`, the atomic evidence unit should be a symbol, signature, method body, class block, hook point, config key, diagnostic block, or patch site. A splitter must not separate:

- method signature from method body;
- Harmony annotation from patched method;
- compiler diagnostic line from nearby context;
- config key from default value and validation path;
- source span from file hash and symbol locator.

For `reference_mod`, chunks may support pattern, hook, and build hints, but they keep `authoritative_for_patch=false` by default.

For `community_note` and `community_hint`, chunk boundaries preserve the claim metadata and verification state.

For `prior_artifact`, chunk boundaries follow artifact contracts: feature target behavior, evidence refs, proposal change units, review findings, build diagnostics, runtime evidence, repair hypotheses, and eval blockers stay individually addressable.

For docs and markdown, use heading-aware and structure-aware splitting. For logs, use time/window/diagnostic-aware splitting. For images, use image placeholders plus surrounding text and metadata; image-only evidence must be treated as limited confidence unless backed by runtime logs or source/API evidence.

### 3.6 MCP Controlled-Agent Surface

MCP is the external tool surface over controlled-agent state. It is not the top-level product and not a direct execution gateway.

First tool set:

| Tool | First status | Role |
| --- | --- | --- |
| `list_features` | Required | Read feature ids and workflow summaries. |
| `get_feature_status` | Required | Read graph state summary, blockers, warnings, and current stage. |
| `get_artifact` | Required | Return sanitized artifact/dashboard projection. |
| `preview_retrieval` / `retrieve_evidence` | Required | Return EvidencePack shape, evidence refs, readiness, missing evidence, trace refs, and blockers. |
| `preview_patch_proposal` | Required | Return proposal summary, files, change units, context_pack, evidence refs, and blockers. |
| `get_proposal_review` | Required | Return review findings, checked rules, required changes, and allowed next stage. |
| `get_eval_report` | Required | Return eval gate status, metrics, false-success/false-block findings, and blockers. |
| `get_job_status` | Required | Return async/degraded job status and budget_summary continuation semantics. |
| `list_collections` | Optional | Read-only knowledge source and collection summary. |
| `read_evidence_item` | Optional | Read a specific evidence item by evidence_ref with sanitized source span. |
| `query_knowledge_hub` | Optional/later | QA-style view over Evidence Retrieval; not patch authority. |
| `get_document_summary` | Optional/later | Document browsing summary; not patch approval. |
| `run_retrieval_eval` | Required later | Run golden retrieval cases and produce eval artifacts. |

Tool output must include `status`, `content`, `structuredContent`, `artifact_refs`, `trace_refs`, `blockers`, and `isError` where the protocol route requires it.

Disabled until approved-route contracts exist:

- `confirmed_apply`
- `copy_to_game_directory`
- `run_game`
- `delete_artifacts`
- `direct_patch_write`
- `direct_runtime_launch`

Approved-route direction:

- V1/V2: read-only/report-only tool surface; JSON-RPC adapter tests; dangerous tools hidden or method-not-found at wire level.
- V2-MCP-001: model write/runtime requests as LangGraph-backed approval artifacts returning `required_approval`, `approval_record`, `rollback_plan`, and `target_stage`.
- V3: transport/server integration, stdio/http smoke tests, and deployment after approved-route contracts are tested.

### 3.7 Current Code Alignment Snapshot

Checked on 2026-07-09 against the current repository layout.

Implemented or partially implemented V1-aligned pieces:

- `src/mod_agent/knowledge/source_registry.py`, `src/mod_agent/knowledge/database.py`, `src/mod_agent/knowledge/indexer.py`, `src/mod_agent/knowledge/symbol_indexer.py`, and `src/mod_agent/knowledge/bm25_indexer.py` provide the controlled-agent knowledge foundation.
- `tests/unit/test_knowledge_base.py` covers `SourceRegistry`, incremental indexing, exact symbol search, and symbol evidence conversion.
- `src/mod_agent/evidence/models.py`, `src/mod_agent/evidence/retriever.py`, `src/mod_agent/evidence/readiness.py`, and `src/mod_agent/evidence/dense.py` provide EvidencePack modeling, deterministic retrieval, readiness, and dense-provider integration points.
- `tests/unit/test_evidence_retrieval.py`, `tests/unit/test_workflow_graph.py`, `tests/unit/test_planning.py`, and `tests/unit/test_mod_delivery_e2e.py` cover evidence readiness, graph evidence artifacts, planning consumption, and end-to-end evidence flow.
- `src/mod_agent/workflow/graph.py` routes `retrieve_evidence` through the controlled-agent graph and writes `evidence_pack` artifacts.
- `src/mod_agent/mcp/tools.py` and `src/mod_agent/mcp/protocol.py` provide the controlled-agent MCP read/report surface.
- `tests/unit/test_controlled_agent_mcp_tools.py` and `tests/unit/test_controlled_agent_mcp_protocol.py` cover read-only tools, structured MCP result fields, hidden dangerous actions, `tools/list`, and `tools/call`.

Known alignment gaps for V2/V3:

- `ReferenceModLoader` and `CommunityNoteLoader / Extractor` are not the current V1 foundation; they belong to V2.
- Artifact/log/domain-doc loader deepening is a V2 supporting item unless existing focused tests prove a specific loader is already complete.
- Hybrid/RRF/Agentic routing are V2 experiments under the registered validation
  plan; rerank and production adoption remain validation-gated. GitHub repo
  import, Discord export import, and broader importers remain later work.
- The legacy/general `src/mcp_server/...` knowledge-query server path still exists. It can remain as imported RAG/MCP reference material or optional knowledge browsing surface, but controlled-agent work must prefer `src/mod_agent/mcp/...` for graph/artifact-aware MCP behavior.

---

# 4. Imported Technical Blueprint

This section is an imported technical reference for RAG/MCP internals. It is
intentionally preserved for pattern lookup, but it is not normative and is not
an execution plan. Sections 0-3, the architecture decision record, the
validation plan, current source/tests, and the active queue decide whether any
pattern below enters the product.

# 7. Knowledge Base 设计

## 7.1 目标

Knowledge Base 是 Evidence RAG 的数据基础。

它不只是存文档，而是统一管理：

```text
源码
反编译 API
Mod 示例
领域知识
历史 artifacts
build logs
runtime logs
screenshots
legacy summaries
```

## 7.2 Knowledge Source 类型

```python
KnowledgeSourceType = Literal[
    "target_source",
    "reference_mod",
    "decompiled_api",
    "domain_note",
    "community_note",
    "community_hint",
    "raw_community_chat",
    "prior_artifact",
    "build_log",
    "runtime_log",
    "screenshot",
    "legacy_summary",
]
```

## 7.3 Knowledge Document

```python
class KnowledgeDocument(TypedDict):
    doc_id: str
    source_type: str
    source_uri: str
    title: str
    text: str
    metadata: dict
    content_hash: str
    created_at: str
    indexed_at: str
```

## 7.4 Ingestion Pipeline

```text
Source Discovery
  -> Load
  -> Normalize
  -> Split
  -> Enrich Metadata
  -> Extract Symbols
  -> Embed Optional
  -> Index
  -> Trace
```

## 7.5 Source Discovery

Domain Adapter 负责提供 sources：

```python
class KnowledgeSourceRegistry:
    def register_source(self, source: KnowledgeSource) -> None:
        ...

    def list_sources(self, filters: dict | None = None) -> list[KnowledgeSource]:
        ...

    def resolve_source(self, source_id: str) -> KnowledgeSource:
        ...
```

GTFO Adapter 默认 sources：

```text
generated_mods/
reference_mods/
docs/knowledge/
decompiled/
BepInEx logs/
artifacts/features/
legacy_import/summaries/
```

## 7.6 Loader 设计

Source authority and phase rules:

```text
V1 implemented source types are local and controlled: target_source,
reference_mod, decompiled_api, domain_note, prior_artifact, build_log,
runtime_log, manual_note, and screenshot.

V2 may add curated reference_mod projects and curated community_note /
community_hint records. Curated reference mods default to
authoritative_for_patch=false and can support implementation patterns, hook
hints, and build hints only after source attribution and license metadata are
recorded.

raw_community_chat is raw_only. It must not enter patch_proposal.context_pack
or approve implementation_plan changes. Curated community notes are
planning_only and authoritative_for_patch=false unless later verification
promotes a separate target_source / decompiled_api / runtime_log evidence item.
```

### Code Loader

处理：

```text
.cs
.json
.toml
.cfg
.csproj
```

输出：

```text
KnowledgeDocument
```

metadata：

```json
{
  "language": "csharp",
  "namespace": "...",
  "class_names": [],
  "method_names": [],
  "file_path": "...",
  "safe_edit": true
}
```

### Decompiled API Loader

处理：

```text
decompiled class files
interop metadata
API index files
```

metadata：

```json
{
  "api_type": "class | method | field | property",
  "symbol_name": "...",
  "declaring_type": "...",
  "signature": "...",
  "source_confidence": "decompiled"
}
```

### Artifact Loader

处理历史 artifact：

```text
feature_spec.json
implementation_plan.json
patch_proposal.json
build_result.json
runtime_evidence.json
```

metadata：

```json
{
  "artifact_type": "...",
  "feature_id": "...",
  "outcome": "success | failed | blocked | partial",
  "staleness": "current | stale | legacy"
}
```

### Log Loader

处理：

```text
BepInEx LogOutput.log
build stdout/stderr
plugin logs
```

metadata：

```json
{
  "log_type": "build | runtime | startup | gameplay",
  "timestamp": "...",
  "severity": "info | warning | error",
  "plugin_name": "..."
}
```

## 7.7 SQLite 元数据存储

路径：

```text
data/db/knowledge.db
```

表结构：

```sql
CREATE TABLE knowledge_sources (
    source_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    content_hash TEXT,
    last_indexed_at TIMESTAMP,
    metadata_json TEXT
);

CREATE TABLE knowledge_documents (
    doc_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    title TEXT,
    content_hash TEXT NOT NULL,
    text_path TEXT,
    metadata_json TEXT,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE knowledge_chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    metadata_json TEXT,
    token_count INTEGER,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE symbol_index (
    symbol_id TEXT PRIMARY KEY,
    symbol_name TEXT NOT NULL,
    symbol_kind TEXT NOT NULL,
    declaring_type TEXT,
    signature TEXT,
    source_uri TEXT,
    chunk_id TEXT,
    metadata_json TEXT
);

CREATE TABLE artifact_index (
    artifact_id TEXT PRIMARY KEY,
    feature_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    outcome TEXT,
    summary TEXT,
    path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_chunks_doc_id ON knowledge_chunks(doc_id);
CREATE INDEX idx_symbol_name ON symbol_index(symbol_name);
CREATE INDEX idx_artifact_feature ON artifact_index(feature_id);
```

## 7.8 增量索引

规则：

```text
source content_hash 未变 -> skip
source content_hash 改变 -> re-index
artifact stale -> exclude from default context
legacy artifact -> only include through legacy summary
```

## 7.9 验收标准

- 可以索引源码、文档、artifact、log；
- 可以查询 source registry；
- 可以跳过未变化 source；
- 可以从 symbol_index 查 method/class/field；
- 可以把 artifact 纳入 knowledge base；
- legacy raw content 默认不进入 patch context。

---

# 8. Evidence RAG 设计

## 8.1 目标

Evidence RAG 负责回答一个问题：

```text
在生成实现计划或 patch 前，系统有什么证据证明这个方案是合理的？
```

它输出的是 Evidence Pack，而不是自然语言答案。

## 8.2 Evidence Item

```python
class EvidenceItem(TypedDict):
    evidence_id: str
    evidence_type: Literal[
        "source_code",
        "symbol",
        "decompiled_api",
        "domain_doc",
        "prior_artifact",
        "build_log",
        "runtime_log",
        "screenshot",
        "user_constraint",
    ]

    source_uri: str
    locator: dict
    content_excerpt: str
    normalized_summary: str

    relevance_score: float
    confidence: float
    freshness: Literal["current", "recent", "legacy", "unknown"]

    supports: list[str]
    contradicts: list[str]
    gaps: list[str]

    usage_permission: Literal[
        "planning_only",
        "proposal_context",
        "runtime_claim",
        "blocked_from_patch",
    ]
```

## 8.3 Evidence Query

```python
class EvidenceQuery(TypedDict):
    query_id: str
    intent: Literal[
        "request_classification",
        "hook_discovery",
        "api_lookup",
        "implementation_pattern",
        "build_error_lookup",
        "runtime_verification",
        "repair_context",
    ]
    text: str
    required_source_types: list[str]
    optional_source_types: list[str]
    filters: dict
    top_k: int
```

## 8.4 Retrieval Pipeline

```text
Feature Spec
  -> Evidence Query Builder
  -> Deterministic Retriever
  -> Symbol Retriever
  -> Keyword Retriever
  -> Optional Vector Retriever
  -> Fusion
  -> Rerank
  -> Gap Detector
  -> Evidence Pack
```

## 8.5 Deterministic Retriever

默认第一版必须可离线运行，不依赖 embedding。

匹配方式：

```text
exact symbol name
file path
class name
method name
config key
artifact type
error token
log marker
feature keyword
```

接口：

```python
class DeterministicRetriever:
    def retrieve(self, query: EvidenceQuery) -> list[EvidenceItem]:
        ...
```

## 8.6 Symbol Retriever

用于代码和反编译 API。

```python
class SymbolRetriever:
    def search_symbol(
        self,
        name: str,
        kind: str | None = None,
        declaring_type: str | None = None,
    ) -> list[EvidenceItem]:
        ...

    def search_signature(
        self,
        signature_fragment: str,
    ) -> list[EvidenceItem]:
        ...
```

## 8.7 Vector Retriever

第二阶段实现。

后端：

```text
Chroma default
FAISS optional
Qdrant future
```

接口：

```python
class VectorRetriever:
    def index_chunks(self, chunks: list[KnowledgeChunk]) -> IndexResult:
        ...

    def retrieve(self, query: EvidenceQuery) -> list[EvidenceItem]:
        ...
```

## 8.8 Fusion

默认使用 RRF：

```python
def reciprocal_rank_fusion(
    result_sets: list[list[EvidenceItem]],
    k: int = 60,
) -> list[EvidenceItem]:
    ...
```

## 8.9 Rerank

可选后端：

```text
none
cross_encoder
llm_rerank
```

失败回退：

```text
rerank timeout -> use fused results
rerank invalid JSON -> use fused results and warning
rerank unavailable -> use fused results
```

## 8.10 Evidence Readiness

```python
EvidenceReadiness = Literal[
    "ready",
    "partial",
    "insufficient",
]
```

判定规则：

| 请求类型 | 必需证据 |
|---|---|
| config_only | target file + config pattern |
| no_hook_needed | target file + requested behavior mapping |
| game_hook | hook symbol + method signature + reference usage |
| runtime_behavior | runtime verification strategy + log/screenshot source |
| repair_loop | failure evidence + previous proposal + build/runtime result |

## 8.11 Evidence Pack Schema

```json
{
  "schema_version": "0.3",
  "feature_id": "...",
  "queries": [],
  "retrieved": [],
  "excluded": [
    {
      "evidence_id": "...",
      "reason": "stale | low_confidence | irrelevant | unsafe_source"
    }
  ],
  "gaps": [
    {
      "gap_id": "gap_001",
      "description": "No verified hook method found for kill marker behavior.",
      "severity": "blocking"
    }
  ],
  "readiness": "ready | partial | insufficient",
  "recommended_next_action": "continue | ask_user | block",
  "metrics": {
    "num_retrieved": 0,
    "num_blocking_gaps": 0
  }
}
```

## 8.12 验收标准

- deterministic mode 无 embedding 可运行；
- hook 请求没有 symbol evidence 时 block；
- retrieval 输出 retrieved/excluded/gaps；
- implementation plan 必须引用 evidence_id；
- patch proposal change 必须引用 evidence_id；
- harness 可评估 evidence recall / precision / gap detection。

---

# 20. MCP / API / CLI 设计

## 20.1 目标

CLI、API、MCP 都通过 graph commands 或 artifact readers 推进同一条产品链路。

They invoke graph commands such as "start workflow", "resume workflow", or
"read workflow status", or they read durable artifacts/traces. They do not call
individual node handler functions directly. A tool named like a node is still a
graph command facade, not a node bypass.

## 20.2 CLI 命令

```text
mod-agent start-request "<request>"
mod-agent run-workflow <feature_id>
mod-agent show-status <feature_id>
mod-agent show-artifact <feature_id> <artifact_type>
mod-agent search-knowledge "<query>"
mod-agent run-eval <suite>
mod-agent dashboard
```

## 20.3 MCP Tools

只读 / report-only：

```text
list_features
get_feature_status
get_artifact
search_knowledge
preview_patch_proposal
run_eval_suite
```

默认不暴露：

```text
apply_patch
run_build
collect_runtime_evidence
```

## 20.4 API

FastAPI 可选。

默认 endpoints：

```text
GET /features
GET /features/{feature_id}
GET /features/{feature_id}/artifacts
POST /requests
POST /eval/{suite}
```

## 20.5 验收标准

- MCP/API/CLI 共享 artifact store；
- API 不绕过 review gate；
- MCP/API/CLI commands do not call workflow node handlers directly；
- dangerous actions must route through permission/interrupt boundaries；
- dangerous action 默认不可用；
- stdout 不污染 MCP protocol。

---

# 32. Phase C：Knowledge Base and Evidence RAG

## 32.1 与普通 RAG 的区别

普通 RAG：

```text
question -> retrieve documents -> answer
```

本项目 Evidence RAG：

```text
agent wants to edit code
-> retrieve source/API/log/artifact evidence
-> classify evidence readiness
-> bind evidence to plan/proposal/review
-> block if evidence is insufficient
```

因此 Evidence RAG 的输出不是自然语言回答，而是 `evidence_pack.json`。

## 32.2 Evidence Item

```json
{
  "evidence_id": "ev_...",
  "source_type": "target_source",
  "source_path": "generated_mods/BetterHitFeedback/Plugin.cs",
  "symbol": "Plugin.Load",
  "span": {
    "start_line": 10,
    "end_line": 42
  },
  "retrieval_method": "symbol",
  "score": 0.91,
  "claim_supported": "startup config is read in Plugin.Load",
  "excerpt": "short excerpt only",
  "risk_notes": []
}
```

首批 source types：

```text
target_source
reference_mod
decompiled_api
domain_note
prior_artifact
build_log
runtime_log
manual_note
```

## 32.3 Retrieval Pipeline

推荐顺序：

```text
query normalization
-> deterministic retrieval
-> symbol retrieval
-> vector retrieval
-> fusion
-> rerank
-> readiness classification
-> evidence pack write
```

MVP 可以先实现 deterministic retrieval，但接口必须预留 vector/rerank。

## 32.4 Evidence Readiness

Readiness 分级：

| Level | 含义 | 是否允许生成 patch proposal |
| --- | --- | --- |
| `sufficient` | 有源代码/API/日志证据支撑目标和边界 | yes |
| `partial` | 有一些证据，但关键 hook 或风险未确认 | no, unless quick_patch |
| `insufficient` | 证据不足以安全改代码 | no |
| `contradictory` | 证据互相冲突 | no |

阻塞 artifact 示例：

```json
{
  "status": "blocked",
  "blockers": [
    {
      "code": "INSUFFICIENT_HOOK_EVIDENCE",
      "message": "No source/API evidence identifies a safe hook for the requested runtime behavior.",
      "needed_evidence": ["target method", "call timing", "side effect boundary"]
    }
  ]
}
```

## 32.5 测试

最低测试：

```text
deterministic retriever finds exact symbol
retriever returns empty pack for missing source
readiness is insufficient when no evidence exists
quick_patch can use config/text evidence without hook evidence
evidence_pack schema validates
```

---

# 37. Evidence RAG Engineering Design Deep Dive

本章专门补齐 Evidence RAG 的工程深度。  
注意：本项目不是普通知识库问答，但仍然需要一个真正专业的 RAG 子系统。区别在于：

```text
普通 RAG 追求 answer quality。
本项目 Evidence RAG 追求 edit safety、implementation grounding、review evidence 和 repair explainability。
```

因此，RAG 不是一个孤立功能，而是贯穿以下阶段：

```text
Knowledge ingestion
-> evidence indexing
-> request-aware evidence query
-> evidence readiness
-> implementation plan grounding
-> patch proposal grounding
-> review gate verification
-> build/runtime repair grounding
```

## 37.0 Imported RAG/MCP Integration Verdict

The imported RAG/MCP spec is not treated as legacy text to ignore. It is the
more mature engineering blueprint for the Evidence Knowledge Subsystem. The
project adapts it into a vertical code-generation Agent by changing authority,
inputs, outputs, and safety boundaries:

| Imported mature RAG/MCP area | Decision in this project | Adaptation rule |
| --- | --- | --- |
| Document, Chunk, ChunkRecord, metadata, file/hash identity | adopt and strengthen | Keep stable identity, content hash, source hash, chunk metadata, collection/version metadata, and contract tests. |
| Loader pipeline | adopt with source authority | Keep code/doc/artifact/log/image loaders, but each source carries `source_type`, provenance, authority, usage permission, and patch authority flags. |
| Chunking/splitting | adapt by source type | Use symbol-aware chunking for code, structure-aware chunking for specs/docs, artifact-aware chunking for artifacts, log-window chunking for build/runtime logs, and fixed/recursive chunking only as fallback. Do not let generic semantic splitting break class/method/hook boundaries. |
| Embedding and vector store | adopt as auxiliary first | Keep embedding cache, vector store abstraction, batch policy, and score normalization. Dense retrieval remains auxiliary until retrieval eval proves authority for a route. |
| BM25/sparse + symbol retrieval | adopt as core | These are first-class V1/V2 code-generation evidence paths because they are deterministic, inspectable, and easy to test. |
| Hybrid fusion/RRF/rerank | adopt but phase later | Keep imported RRF and rerank architecture. Implement after current EvidencePack identity, proposal context, and retrieval eval can consume ranked evidence safely. |
| Response builder | rename and constrain | Replace user-facing answer generation with EvidencePackBuilder, CitationBuilder, and MCP result formatting. It can summarize evidence, not authorize edits. |
| Citation/source span | adopt | Source spans, chunk refs, symbol signatures, file hashes, and evidence artifact hashes become review and eval inputs, not decorative citations. |
| Multimodal response | adapt | ImageContent/Base64 MCP behavior is useful, but screenshots/images are evidence with confidence and limitations, not proof of hook correctness by themselves. |
| RAG eval metrics | adapt | Keep hit-rate, MRR, citation validity, and rerank lift where useful; add readiness accuracy, false-continue, false-block, evidence sufficiency, and review-binding metrics. |
| MCP server design | adopt wire discipline, adapt tools | Keep JSON-RPC/MCP lifecycle, `tools/list`, `tools/call`, content arrays, structuredContent, stdout discipline, and schema tests. Tool names and permissions follow controlled-agent safety rules. |
| Dashboard design | embed | Knowledge source, chunk, image, retrieval trace, and eval pages become subpages inside the workflow/evidence/proposal/review/eval dashboard. |

High-level replacement rule:

```text
If current Evidence RAG text is shallower than the imported mature RAG spec,
replace the shallow version with the imported technical detail after applying:
  - source authority and patch-authority rules;
  - source-type-specific chunking rules;
  - EvidencePack instead of final answer output;
  - LangGraph graph/artifact/review/eval consumption;
  - MCP safe-tool and approved-route boundaries.
```

## 37.1 设计策略与亮点

本项目的 RAG 设计亮点应明确写进 README、Demo 和面试讲述中：

| 设计亮点 | 策略名词 | 具体含义 |
| --- | --- | --- |
| 代码修改前先找证据 | Evidence-before-Edit | 高风险 patch 先补源码/API/log/artifact 证据 |
| 多路召回 | Hybrid Retrieval | deterministic、symbol、BM25、dense vector 并行召回 |
| 结果融合 | Reciprocal Rank Fusion | 用 RRF 融合 sparse/dense/symbol 结果，降低单一路径偏差 |
| 重排优化 | Cross-Encoder / LLM Rerank | 对候选 evidence 做精排，提升 top evidence 可用性 |
| 证据就绪判断 | Evidence Readiness Gate | 检索结果不是直接使用，必须判断 sufficient/partial/insufficient |
| 证据绑定 | Evidence Binding | implementation plan 和 patch proposal 的每个关键修改必须绑定 evidence_ref |
| 可解释检索 | White-box Retrieval Trace | 记录每路召回、融合、重排、过滤、阻塞原因 |
| 增量索引 | Incremental Indexing | 用 file hash / chunk hash 避免重复处理 |
| 多模态证据 | Multimodal Evidence Injection | 图片、截图、日志通过 caption/summary 注入可检索文本 |
| 回归评估 | Retrieval Eval Harness | 用 golden evidence cases 监控召回和排序退化 |

## 37.2 知识源分类

Evidence RAG 的 knowledge source 不只包括文档，还包括代码、构建日志和历史 artifact。

| Source Type | 示例 | Loader | 检索重点 |
| --- | --- | --- | --- |
| `target_source` | 当前 mod 源码 | `CodeLoader` | 类、方法、配置项、patch 位置 |
| `reference_mod` | 参考 mod 源码 | `ReferenceModLoader` | 可复用模式、负例、实现习惯 |
| `decompiled_api` | IL2CPP / Unity API dump | `ApiLoader` | 类型、方法签名、字段名 |
| `domain_note` | BepInEx、HarmonyX 笔记 | `MarkdownLoader` | 领域规则和安全边界 |
| `prior_artifact` | 旧 feature_spec、review、build_result | `ArtifactLoader` | 历史决策、失败原因、约束 |
| `build_log` | dotnet build output | `BuildLogLoader` | 编译错误、引用缺失、API mismatch |
| `runtime_log` | BepInEx log | `RuntimeLogLoader` | hook 是否触发、异常、行为证据 |
| `screenshot` | 游戏截图、UI 截图 | `ImageEvidenceLoader` | 视觉状态、标记颜色、UI 元素 |

## 37.3 分块策略

分块策略不是随便选一个 `chunk_size`。本项目需要根据 source type 选择策略。

常见分块策略包括：

| 策略 | 英文名 | 优点 | 风险 | 本项目用途 |
| --- | --- | --- | --- | --- |
| 固定长度切分 | Fixed-size Chunking | 实现简单、稳定 | 可能破坏语义和代码结构 | 仅作为 fallback |
| 递归字符切分 | Recursive Character Splitting | 按段落、句子、字符递归，尽量保留边界 | 对代码 symbol 感知不足 | Markdown/domain note 默认策略 |
| 语义切分 | Semantic Chunking | 用 embedding 相似度寻找语义断点 | 成本高，依赖模型质量 | 长文档、架构说明、设计文档 |
| 结构感知切分 | Structure-aware Chunking | 尊重 Markdown 标题、列表、代码块、表格 | 需要 loader 提供结构信息 | README、spec、artifact 文档 |
| 符号感知切分 | Symbol-aware Chunking | 按 class/method/function/patch block 切 | 需要 AST 或轻量 parser | C# / Python / generated source |
| Artifact 感知切分 | Artifact-aware Chunking | 按 artifact 字段切分，保留 schema 语义 | 需要 artifact contract 稳定 | feature_spec、proposal、review |
| 日志窗口切分 | Log-window Chunking | 按异常栈、时间窗口、关键事件聚合 | 容易切太大 | build/runtime logs |

推荐默认策略：

```text
Markdown/domain docs:
  structure-aware -> recursive fallback

C#/Python source:
  symbol-aware -> recursive fallback

JSON artifact:
  artifact-aware by top-level fields

Build/runtime log:
  log-window around warnings/errors/hook events

Screenshot/image caption:
  image placeholder stays with surrounding explanatory text
```

Code-generation chunking constraints:

```text
For target_source and decompiled_api, the atomic evidence unit should be a
symbol, signature, method body, class block, hook point, config key, or patch
site. Generic semantic chunking is not allowed to split a method signature from
its body, a Harmony patch annotation from the patched method, or a diagnostic
line from its nearby compiler context.

For reference_mod, chunks may support pattern/hook/build hints but default to
authoritative_for_patch=false. They can suggest implementation patterns; they
cannot prove that a target patch is safe.

For community_note and community_hint, chunks must preserve claim,
claim_type, source_locator, timestamp, confidence, and
requires_verification. Raw community chat remains raw_only and cannot enter
patch_proposal.context_pack.

For prior_artifact, the chunk boundary follows the artifact contract: feature
spec target behavior, evidence refs, proposal change units, review findings,
build diagnostics, runtime evidence, repair hypotheses, and eval blockers must
stay individually addressable.
```

Chunk metadata 必填字段：

```json
{
  "chunk_id": "chunk_...",
  "source_type": "target_source",
  "source_path": "generated_mods/BetterHitFeedback/Plugin.cs",
  "symbol": "Plugin.Load",
  "heading_path": ["BetterHitFeedback", "Plugin"],
  "start_line": 10,
  "end_line": 42,
  "chunk_strategy": "symbol_aware",
  "content_hash": "sha256...",
  "image_refs": [],
  "artifact_refs": [],
  "risk_tags": ["runtime_hook"]
}
```

## 37.4 向量数据库与索引策略

第一版推荐使用 Chroma，因为本地优先、部署简单、适合求职项目演示。  
但架构必须通过 `VectorStore` 抽象保留迁移路径。

| 后端 | 优点 | 缺点 | 推荐阶段 |
| --- | --- | --- | --- |
| Chroma | 本地部署简单，适合 MVP | 大规模和生产治理一般 | Phase C-D 默认 |
| Qdrant | 过滤能力强，服务化清晰 | 多一个服务依赖 | Week 2+ 可选 |
| Milvus | 大规模向量检索能力强 | 运维成本高 | 未来扩展 |
| FAISS | 性能高，纯本地 | metadata/filter 需要自管 | 实验性后端 |

索引建议采用多轨存储：

```text
Dense index:
  chunk_text_with_context -> embedding -> vector store

Sparse index:
  normalized tokens -> BM25 inverted index

Symbol index:
  symbol name / method signature / config key -> exact lookup

Artifact index:
  feature_id / artifact_type / status / dependency hash -> SQLite

Image index:
  image_id -> local file path + source position + caption hash
```

## 37.5 检索流水线

Evidence retrieval 的标准流程：

```text
EvidenceQuery
  -> QueryProcessor
  -> DeterministicRetriever
  -> SymbolRetriever
  -> SparseRetriever(BM25)
  -> DenseRetriever(VectorStore)
  -> Fusion(RRF)
  -> MetadataFilter
  -> Reranker
  -> EvidenceReadinessClassifier
  -> EvidencePackWriter
```

每一步都必须向 trace 写入结构化事件：

```text
retrieval.query_processed
retrieval.symbol_completed
retrieval.sparse_completed
retrieval.dense_completed
retrieval.fusion_completed
retrieval.rerank_completed
retrieval.readiness_classified
```

## 37.6 配置文件结构示例

`config/settings.yaml` 示例：

```yaml
project:
  name: evidence-grounded-controlled-code-generation-agent-platform
  artifact_root: artifacts
  data_root: data

rag:
  default_collection: mod_agent
  ingestion:
    incremental: true
    file_hash_algorithm: sha256
    chunk_hash_algorithm: sha256
    skip_successful_hash: true
  chunking:
    default_strategy: structure_aware
    fallback_strategy: recursive
    chunk_size: 900
    chunk_overlap: 120
    preserve_code_blocks: true
    preserve_image_refs: true
    source_type_overrides:
      target_source: symbol_aware
      reference_mod: symbol_aware
      prior_artifact: artifact_aware
      build_log: log_window
      runtime_log: log_window
  retrieval:
    top_k_dense: 20
    top_k_sparse: 20
    top_k_symbol: 20
    fusion_method: rrf
    rrf_k: 60
    final_top_k: 8
    require_evidence_for_high_risk: true
  rerank:
    backend: none
    top_m: 20
    timeout_seconds: 20
    fallback_on_error: true
  readiness:
    high_risk_requires:
      - target_source
      - decompiled_api
    quick_patch_allows:
      - target_source
      - prior_artifact

embedding:
  provider: openai
  model: text-embedding-3-small
  batch_size: 64
  cache_enabled: true

vector_store:
  provider: chroma
  persist_directory: data/db/chroma
  collection_name: mod_agent_evidence

sparse_index:
  provider: bm25
  persist_directory: data/db/bm25
  tokenizer: default

vision:
  enabled: true
  provider: azure_openai
  model: gpt-4o
  cache_enabled: true
  max_image_size_px: 2048
  prompt_version: image_caption_v1

observability:
  trace_enabled: true
  trace_path: artifacts/runs
  log_format: jsonl
  dashboard_enabled: true

safety:
  confirmed_write_default: false
  external_side_effect_default: false
  forbidden_paths:
    - .git
    - .venv
    - artifacts/runs
```

## 37.7 具体实现类与函数

推荐文件与类：

```text
src/mod_agent/knowledge/source_registry.py
  KnowledgeSourceRegistry.register(source: KnowledgeSource) -> None
  KnowledgeSourceRegistry.discover(root: Path) -> list[KnowledgeSource]

src/mod_agent/knowledge/loaders/base.py
  BaseLoader.load(source: KnowledgeSource) -> list[Document]

src/mod_agent/knowledge/chunking/base.py
  BaseChunker.split(document: Document) -> list[Chunk]

src/mod_agent/knowledge/chunking/structure_aware.py
  StructureAwareChunker.split(document: Document) -> list[Chunk]

src/mod_agent/knowledge/chunking/symbol_aware.py
  SymbolAwareChunker.split(document: Document) -> list[Chunk]

src/mod_agent/evidence/query.py
  EvidenceQuery
  build_evidence_query(feature_spec, implementation_intent) -> EvidenceQuery

src/mod_agent/evidence/retrievers/*.py
  DeterministicRetriever.retrieve(query) -> list[EvidenceItem]
  SymbolRetriever.retrieve(query) -> list[EvidenceItem]
  SparseRetriever.retrieve(query) -> list[EvidenceItem]
  DenseRetriever.retrieve(query) -> list[EvidenceItem]

src/mod_agent/evidence/fusion.py
  reciprocal_rank_fusion(result_sets, k=60) -> list[EvidenceItem]

src/mod_agent/evidence/readiness.py
  classify_evidence_readiness(query, evidence_items) -> EvidenceReadiness

src/mod_agent/evidence/pack.py
  EvidencePackWriter.write(query, evidence_items, readiness) -> ArtifactRef
```

---

# 38. Multimodal Evidence and Image Processing Design

本项目的多模态不是为了炫技，而是为了让图片、截图、图表和游戏画面能进入 evidence chain。

处理策略采用：

```text
Image-to-Text semantic injection + original image side storage
```

也就是：

```text
图片理解结果进入 chunk text，参与 embedding / BM25。
原始图片保存在本地，通过 image_id 在检索命中后返回或展示。
```

## 38.1 Loader 阶段：图片提取与引用收集

提取策略：

- PDF 中识别 XObject 图片；
- PPT/Office 文档中识别 media 文件；
- Markdown 中识别 `![]()` 引用；
- runtime evidence 中识别 screenshot 文件；
- 为每张图片生成全局唯一 `image_id`，推荐格式：`{doc_hash}_{page}_{seq}`；
- 记录图片在源文档中的页码、段落、标题路径和附近文本。

引用标记：

```text
在转换后的 Markdown 文本中，于图片原始位置插入：

[IMAGE: image_id]
```

Document metadata：

```json
{
  "images": [
    {
      "image_id": "abc123_4_2",
      "source_doc": "docs/architecture.pdf",
      "page": 4,
      "seq": 2,
      "width": 1280,
      "height": 720,
      "mime_type": "image/png",
      "nearby_text": "The following diagram shows the retrieval pipeline."
    }
  ]
}
```

原始图片存储：

```text
data/images/<collection>/<image_id>.png
```

## 38.2 Splitter 阶段：保持图文关联

原则：

- 图片引用标记应与 caption、前后段落尽量保持在同一 chunk；
- 图片位于章节开头时，归入后续解释段落；
- 图片位于章节结尾时，归入前文说明段落；
- 一个 chunk 可以有多个 `image_refs`；
- 如果必须拆开，生成 `image_context_bridge` metadata，记录跨 chunk 关系。

Chunk metadata 扩展：

```json
{
  "image_refs": ["abc123_4_2"],
  "image_context_policy": "same_chunk",
  "image_context_text": "retrieval pipeline diagram"
}
```

## 38.3 Transform 阶段：图片理解与描述生成

Vision LLM 选型：

| 模型 | 提供商 | 特点 | 适用场景 | 推荐度 |
| --- | --- | --- | --- | --- |
| GPT-4o | OpenAI / Azure | 复杂图表和英文技术文档强 | 高质量、国际化、Azure 合规 | 5 |
| Qwen-VL-Max | 阿里云 DashScope | 中文图表、中文 OCR 强，国内访问稳定 | 中文文档、国内部署、成本敏感 | 5 |
| Qwen-VL-Plus | 阿里云 DashScope | 速度快、成本低 | 大批量处理 | 4 |
| Claude Sonnet Vision | Anthropic | 长上下文结合能力强 | 图片需要结合长文本理解 | 4 |
| Gemini Vision | Google | 成本较低 | 大批量低成本 | 3 |
| GLM-4V | 智谱 | 中文支持稳定 | 国内备选 | 4 |

双模型策略：

| 部署环境 | 主选模型 | 备选模型 | 说明 |
| --- | --- | --- | --- |
| 国际化 / Azure | GPT-4o via Azure | Qwen-VL-Max | 英文和企业合规优先 |
| 国内 / 中文 | Qwen-VL-Max | GPT-4o | 中文图表和截图优先 |
| 成本敏感 | Qwen-VL-Plus | Gemini Vision | 批量 caption 降成本 |

描述生成策略：

- 结构化 Prompt：要求输出 `image_type`、`entities`、`relationships`、`text_detected`、`summary`；
- 上下文感知：传入图片前后文本、标题路径、source type；
- 分类型处理：流程图、架构图、数据图表、截图/UI、游戏画面、照片分别使用不同 prompt hint；
- 幂等缓存：图片 hash + prompt_version + model 作为 cache key；
- 降级策略：Vision LLM 失败时保留 `[IMAGE: id]` 和 metadata，不阻塞文本摄取。

图片类型处理表：

| 图片类型 | 理解重点 | Prompt 引导 |
| --- | --- | --- |
| 流程图/架构图 | 节点、边、方向、阶段 | 描述结构、流程顺序、模块关系 |
| 数据图表 | 指标、趋势、异常点 | 提取关键数值和结论 |
| 截图/UI | 控件、状态、可见文本 | 描述界面元素和状态 |
| 游戏画面 | 颜色、标记、HUD、事件 | 描述可验证的游戏状态 |
| 代码截图 | 符号、错误、行号 | 提取代码/错误文本和上下文 |

## 38.4 Storage 阶段：双轨存储

向量库存储：

```text
enhanced_chunk_text = original text with [图片描述: ...] injected
metadata.image_refs = [...]
metadata.image_captions = {...}
```

原始图片索引：

```sql
CREATE TABLE images (
    image_id TEXT PRIMARY KEY,
    collection TEXT NOT NULL,
    file_path TEXT NOT NULL,
    source_doc TEXT NOT NULL,
    source_type TEXT NOT NULL,
    page INTEGER,
    width INTEGER,
    height INTEGER,
    mime_type TEXT,
    content_hash TEXT NOT NULL,
    caption_hash TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

处理缓存：

```sql
CREATE TABLE image_processing_cache (
    cache_key TEXT PRIMARY KEY,
    image_hash TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model_provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    caption_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 38.5 质量保障与边界处理

必须覆盖：

```text
image extraction failure
unsupported image format
oversized image compression
vision model timeout
invalid caption JSON
duplicate image hash
missing image file during retrieval
chunk split separates image and caption
caption injection disabled
```

验收标准：

```text
无图片文档正常摄取
含图片文档产生 image_refs
Vision LLM mock 后 caption 注入 chunk text
重复摄取命中 cache
检索命中后能通过 image_refs 找回原始图片路径
Vision 失败不影响文本 evidence ingestion
```

---

# 45. Adopted RAG Subsystem Specification

本章决定：可以把一号项目中成熟的 RAG 系统整体吸收进来，但必须改变定位。

一号 RAG 的定位是：

```text
Smart Knowledge Hub / MCP Knowledge QA System
```

二号项目中的定位必须是：

```text
Evidence Knowledge Subsystem for Controlled Agentic Code Generation
```

也就是说，二号可以完整继承一号的 RAG 工程套路：

```text
Loader
Splitter
Transform
Embedding
Sparse Index
Vector Store
Hybrid Retrieval
Rerank
Citation
Multimodal Image Handling
Observability
Evaluation
MCP Tool Exposure
Dashboard
```

但它们的第一用途不是“回答用户问题”，而是：

```text
为 planning、implementation plan、patch proposal、review gate、build repair 和 runtime repair 提供证据。
```

## 45.1 实用性判断

整体搬 RAG 系统是实用的，因为：

| 能力 | 对二号项目的价值 |
| --- | --- |
| 文档/代码摄取 | 给 agent 建立领域知识、源码知识、历史 artifact 知识 |
| 分块策略 | 保证检索到的 evidence 不破坏代码/文档语义 |
| Hybrid Search | 同时覆盖符号精确匹配和语义召回 |
| Rerank | 提升高风险修改前 evidence 的可信度 |
| 多模态图片处理 | 支持架构图、截图、游戏画面、UI 状态进入证据链 |
| Trace/Dashboard | 让检索和生成过程可解释 |
| Evaluation | 证明 retrieval/review 不是凭感觉调 prompt |
| MCP | 后续可作为外部 agent 的知识工具 |

需要改造成二号项目形态的部分：

| 一号能力 | 二号处理方式 |
| --- | --- |
| 面向普通用户的 QA response | 放到后续可选，不作为第一版主目标 |
| 直接对外暴露 query_knowledge_hub | 第一版只暴露 read-only / report-only evidence tools |
| 以文档问答指标为核心 | 改成 evidence recall、readiness accuracy、false-continue rate |
| Streamlit 管理普通知识库 | 改成 workflow/evidence/proposal/review/dashboard 一体化 |
| 图片作为回答内容返回 | 第一版先作为 evidence 附件和 runtime proof |

结论：

```text
搬系统，不搬产品定位。
搬工程策略，不搬问答中心叙事。
搬 RAG pipeline，不让 RAG 吞掉 controlled agent workflow。
```

## 45.2 RAG 子系统边界

RAG 子系统在二号中的边界：

```text
Inputs:
  source files
  reference mods
  decompiled APIs
  markdown docs
  prior artifacts
  build logs
  runtime logs
  screenshots/images

Outputs:
  indexed chunks
  evidence items
  evidence packs
  citations
  retrieval traces
  retrieval eval reports
```

RAG 子系统不负责：

```text
deciding whether to edit
generating final patch
approving dangerous writes
claiming runtime success
overriding review gate
```

这些仍由 LangGraph workflow、proposal、review、dry-run、build/runtime 模块负责。

## 45.3 推荐目录结构

一号的 `core/ingestion/query_engine/libs` 可以迁移为二号里的 `knowledge_hub` 子系统，避免污染 agent workflow 主干。

```text
src/mod_agent/
  knowledge_hub/
    __init__.py
    types.py
    settings.py

    ingestion/
      pipeline.py
      document_manager.py
      file_hash.py
      loaders/
        base.py
        markdown_loader.py
        code_loader.py
        pdf_loader.py
        artifact_loader.py
        log_loader.py
        image_loader.py
      chunking/
        base.py
        fixed_chunker.py
        recursive_chunker.py
        semantic_chunker.py
        structure_aware_chunker.py
        symbol_aware_chunker.py
        artifact_aware_chunker.py
        log_window_chunker.py
      transform/
        base.py
        metadata_enricher.py
        image_captioner.py
        chunk_refiner.py
      embedding/
        dense_encoder.py
        sparse_encoder.py
        batch_processor.py
      storage/
        vector_upserter.py
        bm25_indexer.py
        image_storage.py
        sqlite_metadata.py

    retrieval/
      query_processor.py
      deterministic_retriever.py
      symbol_retriever.py
      dense_retriever.py
      sparse_retriever.py
      hybrid_search.py
      fusion.py
      reranker.py
      evidence_readiness.py
      citation_builder.py

    providers/
      llm/
      embedding/
      vector_store/
      reranker/
      vision/

    evaluation/
      retrieval_eval_runner.py
      golden_set.py
      metrics.py

    observability/
      trace_context.py
      retrieval_trace.py
      ingestion_trace.py
```

Agent 主线模块通过接口调用它：

```text
planning -> knowledge_hub.retrieval
implementation_plan -> knowledge_hub.retrieval
patch_proposal -> knowledge_hub.retrieval
review -> knowledge_hub.retrieval + citation_builder
repair -> knowledge_hub.retrieval over build/runtime logs
dashboard -> knowledge_hub.observability + artifact store
```

## 45.4 核心数据类型

`Document`：

```python
@dataclass
class Document:
    document_id: str
    source_type: str
    source_path: str
    text: str
    metadata: dict[str, Any]
```

`Chunk`：

```python
@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    text: str
    metadata: dict[str, Any]
    source_span: SourceSpan | None = None
```

`ChunkRecord`：

```python
@dataclass
class ChunkRecord:
    chunk_id: str
    text_for_embedding: str
    dense_vector: list[float] | None
    sparse_terms: dict[str, float] | None
    metadata: dict[str, Any]
    content_hash: str
```

`EvidenceItem`：

```python
@dataclass
class EvidenceItem:
    evidence_id: str
    chunk_id: str
    source_type: str
    source_path: str
    excerpt: str
    score: float
    retrieval_method: str
    citation: Citation
    metadata: dict[str, Any]
```

`EvidencePack`：

```python
@dataclass
class EvidencePack:
    query_id: str
    feature_id: str
    readiness: str
    items: list[EvidenceItem]
    blockers: list[dict[str, Any]]
    trace_refs: list[str]
```

## 45.5 Ingestion Pipeline

标准流程：

```text
Source Discovery
  -> File Integrity Check
  -> Loader
  -> Canonical Markdown / Structured Text
  -> Splitter
  -> Transform
  -> Dense Encoding
  -> Sparse Encoding
  -> Vector Upsert
  -> BM25 Index Persist
  -> Metadata SQLite Write
  -> Trace Write
```

### 45.5.1 Source Discovery

目标：

```text
发现可索引知识源，并按 source_type 分类。
```

实现类：

```python
class SourceDiscovery:
    def discover(self, roots: list[Path]) -> list[KnowledgeSource]: ...
```

规则：

| 文件/目录 | source_type |
| --- | --- |
| `generated_mods/**/*.cs` | `target_source` |
| `docs/knowledge/**/*.md` | `domain_note` |
| `docs/features/**/feature_spec.json` | `prior_artifact` |
| `docs/features/**/proposal_review.json` | `prior_artifact` |
| `docs/features/**/build_result.json` | `build_log` |
| `*.log` | `runtime_log` or `build_log` |
| `*.png`, `*.jpg` | `screenshot` |

验收标准：

```text
能发现 target source、docs、artifact、log；
能忽略 .git、.venv、bin、obj、node_modules；
每个 source 有 stable source_id 和 content_hash。
```

### 45.5.2 File Integrity Check

从一号继承 SHA256 增量机制：

```sql
CREATE TABLE ingestion_history (
    source_id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    source_type TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('success', 'failed', 'processing', 'skipped')),
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    error_msg TEXT,
    chunk_count INTEGER,
    prompt_version TEXT,
    pipeline_version TEXT
);
```

跳过策略：

```text
same source_path
same content_hash
same pipeline_version
same prompt_version for transform/caption
last status = success
=> skip
```

### 45.5.3 Loader Strategy

Loader 统一输出 `Document`，不直接写向量库。

| Loader | 输入 | 输出重点 |
| --- | --- | --- |
| `CodeLoader` | `.cs`, `.py` | symbol、namespace、class、method、line span |
| `MarkdownLoader` | `.md` | heading_path、code fences、links |
| `PdfLoader` | `.pdf` | canonical markdown、page、images |
| `ArtifactLoader` | `.json` | artifact_type、feature_id、status、key fields |
| `LogLoader` | `.log`, build output | timestamp、severity、error block |
| `ImageLoader` | screenshots | image_id、caption placeholder |

最低实现顺序：

```text
1. MarkdownLoader
2. CodeLoader
3. ArtifactLoader
4. LogLoader
5. ImageLoader / PdfLoader
```

## 45.6 Splitter Strategy

本项目直接吸收一号的 chunking 思路，并扩展到代码生成场景。

### 45.6.1 策略选择表

| Strategy | Class | Default For | Description |
| --- | --- | --- | --- |
| fixed length | `FixedChunker` | fallback only | 按字符/token 数切分 |
| recursive character | `RecursiveChunker` | markdown fallback | 段落 -> 句子 -> 字符递归 |
| semantic | `SemanticChunker` | long design docs | embedding 相似度找断点 |
| structure-aware | `StructureAwareChunker` | markdown/spec/docs | 保留标题、列表、代码块 |
| symbol-aware | `SymbolAwareChunker` | source code | 按 class/method/function 切 |
| artifact-aware | `ArtifactAwareChunker` | JSON artifacts | 按 schema 字段组织 |
| log-window | `LogWindowChunker` | logs | 错误/异常周围窗口聚合 |

### 45.6.2 Chunking Rules

共同规则：

```text
chunk text must be self-contained enough for review
chunk metadata must preserve source location
chunk must not split code block in the middle when avoidable
chunk must keep image placeholder near explanatory text
chunk must expose source_type and risk_tags
```

代码切分规则：

```text
method body <= max_chunk_size:
  one method = one chunk

method body > max_chunk_size:
  split by logical blocks but preserve signature and class metadata

class contains many small methods:
  one chunk per method, plus optional class summary chunk
```

Artifact 切分规则：

```text
feature_spec:
  target_behavior
  non_goals
  acceptance_criteria
  evidence_requirements

patch_proposal:
  summary
  files
  diff_intent
  evidence_refs
  risk_assessment

proposal_review:
  decision
  findings
  required_changes
```

## 45.7 Transform Strategy

Transform 继承一号的增强思路，但要避免让 LLM 改写关键证据。

Transform 类型：

| Transform | 作用 | 是否允许改变事实 |
| --- | --- | --- |
| `MetadataEnricher` | 补 title、tags、summary、risk_tags | no |
| `ImageCaptioner` | 图片转结构化 caption | no |
| `ChunkRefiner` | 清理噪声、补上下文标题 | no semantic rewrite by default |
| `CodeSymbolAnnotator` | 提取 class/method/signature | no |
| `ArtifactSummaryTransform` | 从 artifact 提取 key fields | no |

推荐推进方式：

```text
LLM 可生成 evidence summary，同时保留源码证据；
LLM summary 关联原文 evidence ref；
source span 随 chunk / evidence item 保留；
推测写入 hypothesis 字段，再由 evidence 验证。
```

推荐 caption JSON：

```json
{
  "image_type": "architecture_diagram",
  "visible_text": [],
  "entities": [],
  "relationships": [],
  "summary": "The diagram shows...",
  "confidence": "medium",
  "limitations": []
}
```

## 45.8 Embedding and Sparse Encoding

Dense embedding：

```python
class BaseEmbedding(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Sparse encoding：

```python
class SparseEncoder:
    def fit(self, chunks: list[Chunk]) -> None: ...
    def encode_query(self, query: str) -> SparseVector: ...
    def encode_documents(self, chunks: list[Chunk]) -> list[SparseVector]: ...
```

Embedding 文本构造：

```text
embedding_text =
  heading_path
  + source_type
  + symbol/signature if exists
  + original chunk text
  + image captions if exists
  + artifact key summary if exists
```

不要把以下内容放进 embedding_text：

```text
secret values
full huge logs
binary/base64 image data
unbounded stack traces
```

## 45.9 Retrieval Strategy

二号项目使用四路召回：

```text
deterministic exact evidence
symbol lookup
sparse BM25
dense vector
```

优先级：

```text
review gate uses exact/symbol evidence with highest trust
dense evidence improves recall but cannot alone approve high-risk runtime hook
BM25 is valuable for config keys, class names, error messages
```

### 45.9.1 Query Processor

输入：

```text
user_request
feature_spec
implementation_intent
target_mod
risk_level
required_evidence_types
```

输出：

```json
{
  "query_text": "kill marker color hook BetterHitFeedback",
  "keywords": ["kill marker", "color", "BetterHitFeedback"],
  "symbols": ["HitFeedback", "CrosshairGuiLayer"],
  "filters": {
    "source_type": ["target_source", "decompiled_api", "domain_note"],
    "target_mod": "BetterHitFeedback"
  },
  "risk_level": "high"
}
```

### 45.9.2 RRF Fusion

RRF 公式：

```text
score(d) = sum(1 / (k + rank_i(d)))
```

默认：

```text
k = 60
```

规则：

```text
same chunk_id from multiple retrievers should merge;
retrieval_methods should be preserved;
highest-trust exact/symbol matches can receive boost;
source_type required by risk policy can receive boost.
```

### 45.9.3 Rerank

Rerank 后端：

```text
none
cross_encoder
llm
```

第一版默认 `none`，但接口必须完整。

LLM rerank 必须输出结构化 JSON：

```json
{
  "ranked": [
    {
      "chunk_id": "chunk_1",
      "score": 0.92,
      "reason": "Contains the exact method controlling kill marker color."
    }
  ]
}
```

失败策略：

```text
timeout -> fallback to fusion order
invalid JSON -> fallback to fusion order and trace warning
empty candidates -> return empty list
```

## 45.10 Evidence Readiness Gate

这是二号与一号普通 RAG 最大的差异。  
检索结果经过 readiness 判断后进入 patch grounding。

Readiness policy：

| Risk | Required Evidence | Continue? |
| --- | --- | --- |
| low quick patch | target file or prior artifact | yes |
| medium standard feature | target_source + domain_note | yes if scoped |
| high runtime hook | target_source + API/signature + domain rule | yes |
| high runtime hook missing API | partial | no |
| vague request | none | no |

False continue 是严重问题：

```text
高风险 evidence 不足时，系统优先生成 evidence discovery / clarification / runtime probe 任务。
```

## 45.11 Citation and Source Transparency

每个 evidence item 必须能生成 citation：

```json
{
  "source_path": "generated_mods/BetterHitFeedback/Plugin.cs",
  "start_line": 18,
  "end_line": 42,
  "source_type": "target_source",
  "retrieval_method": "symbol+dense",
  "content_hash": "sha256..."
}
```

Patch proposal 中引用方式：

```json
{
  "change": "Modify kill marker color branch only.",
  "evidence_refs": ["ev_001", "ev_004"],
  "citation_summary": "ev_001 identifies the marker update method; ev_004 confirms normal hit marker branch is separate."
}
```

## 45.12 RAG MCP Tools

The imported MCP design is technically strong and should be retained for wire
discipline, schema discipline, stdio cleanliness, JSON-RPC lifecycle,
tools/list, tools/call, content arrays, structuredContent, tool result
formatting, error mapping, and client simulation tests.

In this project, MCP is not the top-level product and not a direct execution
gateway. MCP is the controlled-agent external tool surface:

~~~text
MCP Client / CLI / API
  -> controlled-agent tool schema
  -> graph command facade or artifact reader
  -> ArtifactStore / EvidencePack / ProposalReview / EvalReport
  -> approved-route record for future write/runtime actions
~~~

MCP tools must not call workflow node handlers directly. A tool with a name that
resembles a node is still a graph command facade or artifact reader, not a node
bypass.

First tool set:

| Tool | First status | Role |
| --- | --- | --- |
| list_features | required | Read feature ids and latest workflow summaries. |
| get_feature_status | required | Read graph state summary, blockers, warnings, and current stage. |
| get_artifact | required | Return sanitized artifact/dashboard projection, not raw unsafe bodies by default. |
| preview_retrieval / retrieve_evidence | required | Return or preview EvidencePack shape, evidence refs, readiness, missing evidence, trace refs, and blockers. |
| preview_patch_proposal | required | Return proposal summary, files, change units, context_pack, evidence refs, and blockers. |
| get_proposal_review | required | Return review findings, checked rules, required changes, and allowed next stage. |
| get_eval_report | required | Return eval gate status, metrics, false-success/false-block findings, and blockers. |
| get_job_status | required | Return async/degraded job status and budget_summary continuation semantics. |
| list_collections | optional | Read-only knowledge source and collection summary. |
| read_evidence_item | optional | Read a specific evidence item by evidence_ref with sanitized source span. |
| query_knowledge_hub | optional/later | QA-style query is allowed only as a view over Evidence Retrieval; it must not become patch authority. |
| get_document_summary | optional/later | Document summary for browsing; not a patch approval source. |
| run_retrieval_eval | required later | Run retrieval golden cases and write/read eval artifacts. |

Output must include:

~~~text
status
content
structuredContent
artifact_refs
trace_refs
blockers
isError
~~~

Disabled unless an approved route contract exists:

~~~text
confirmed_apply
copy_to_game_directory
run_game
delete_artifacts
direct_patch_write
direct_runtime_launch
~~~

Approved-route MCP direction:

~~~text
V1/V2 current:
  read-only/report-only tool surface
  JSON-RPC adapter tests
  dangerous tools hidden or method-not-found at wire level

V2-MCP-001:
  model write/runtime requests as LangGraph-backed approval artifacts
  return required_approval / approval_record / rollback_plan / target_stage
  never execute filesystem writes, game launch, or copy operations directly

V3:
  transport/server integration, stdio/http smoke tests, and production deployment
  after approved-route contracts are tested
~~~

MCP and Skill boundary:

~~~text
Skills are process playbooks for agents. They can guide planning, hook
discovery, patch review, runtime diagnosis, and repair decisions.

MCP tools are product/API surfaces. They expose current state, artifacts,
evidence, review, eval, and approved-route records to outside clients.

Skills must not become runtime product state, schema copies, a Skill registry in
LangGraph, automatic hook scanners, automatic repair executors, or MCP write
automation. MCP tools may expose results produced by source code and artifacts;
they must not treat Skill text as product truth.
~~~

## 45.13 RAG Dashboard Pages

RAG 子系统 dashboard 页面：

```text
Knowledge Sources
Ingestion Runs
Chunk Browser
Image Browser
Hybrid Retrieval Trace
Evidence Pack Viewer
Retrieval Eval Dashboard
```

这些页面嵌入总 Dashboard，不作为单独产品主页面。

## 45.14 RAG Evaluation

从一号继承 QA/RAG 质量评估思路，但指标改成 evidence-first：

| Metric | 含义 |
| --- | --- |
| `evidence_hit_rate_at_k` | Top-K 是否包含人工标注 evidence |
| `symbol_hit_rate` | 符号/方法/配置项是否命中 |
| `source_type_coverage` | 是否覆盖 required source types |
| `readiness_accuracy` | readiness 判断是否正确 |
| `false_continue_rate` | 证据不足却继续的比例 |
| `false_block_rate` | 证据足够却阻塞的比例 |
| `citation_validity` | citation 是否指向真实 source span |
| `rerank_lift` | rerank 前后 Top-K 改善 |

Golden case 示例：

```json
{
  "case_id": "high_risk_runtime_hook_requires_api",
  "user_request": "Make kill marker pink without changing normal hit marker.",
  "expected_route": "full_runtime_investigation",
  "required_source_types": ["target_source", "decompiled_api"],
  "expected_readiness_without_api": "insufficient",
  "expected_readiness_with_api": "sufficient",
  "must_not_continue_without_api": true
}
```

## 45.15 RAG Phase Plan

把一号 RAG 系统迁入二号时，分四层做：

### RAG-M0：接口和数据类型

目标：

```text
定义 Document、Chunk、EvidenceItem、EvidencePack、VectorStore、Retriever 接口。
```

文件：

```text
src/mod_agent/knowledge_hub/types.py
src/mod_agent/knowledge_hub/retrieval/interfaces.py
tests/test_knowledge_hub_contracts.py
```

验收：

```text
contract tests pass
no external model dependency
```

### RAG-M1：本地 deterministic + BM25

目标：

```text
先不用 embedding，也能做 exact/symbol/BM25 evidence retrieval。
```

文件：

```text
deterministic_retriever.py
symbol_retriever.py
sparse_retriever.py
bm25_indexer.py
```

验收：

```text
config key query can hit source;
symbol query can hit method/class;
missing evidence returns insufficient readiness.
```

### RAG-M2：Dense vector + Hybrid fusion

目标：

```text
接入 embedding/vector store，完成 dense + sparse + symbol + RRF。
```

验收：

```text
known golden evidence appears in top_k;
fusion preserves retrieval_methods;
rerank failure can fallback.
```

### RAG-M3：Multimodal + Dashboard + Eval

目标：

```text
图片 caption、image index、retrieval trace dashboard、retrieval eval。
```

验收：

```text
image_refs preserved;
caption injected;
evidence browser can display image-linked chunk;
retrieval eval report generated.
```

## 45.16 Migration Rules from 一号

可以直接继承：

```text
chunking 策略思想
hybrid search 架构
RRF fusion
reranker abstraction
vision caption pipeline
SQLite metadata/cache
dashboard 页面思想
MCP tool schema 思路
testing pyramid
progress tracking style
```

必须改名或改定位：

```text
Query Engine -> Evidence Retrieval Engine
Response Builder -> Evidence Pack / Citation Builder
RAG QA Eval -> Evidence Retrieval Eval
Knowledge Hub Dashboard -> Evidence/Workflow Dashboard
query_knowledge_hub -> retrieve_evidence first, query_knowledge_hub later
```

暂不搬：

```text
面向终端用户的完整自然语言回答生成；
复杂在线服务化部署；
生产级多用户权限；
重型云端向量库；
完整图片返回协议。
```

## 45.17 Practical First-Version Cut

为了两天内可落地，第一版 RAG 子系统只做：

```text
CodeLoader
MarkdownLoader
ArtifactLoader
RecursiveChunker
SymbolAwareChunker basic
BM25 sparse retrieval
Deterministic/symbol retrieval
EvidencePack schema
Readiness classifier
Retrieval trace
Golden retrieval eval mini set
```

第一版不做：

```text
real cloud embedding
real vector database if time is tight
real Vision LLM
full MCP QA
full Streamlit dashboard
semantic chunking
cross-encoder rerank
```

这样仍然保留一号 RAG 架构的上限，同时不会让第一版卡死在外部 API、向量库和多模态成本上。


---

# 46. Full Imported RAG System DEV_SPEC

> Source: C:/Users/10160/Desktop/ai学习/DEV_SPEC.md  
> Import mode: full verbatim integration for RAG subsystem reference.  
> Scope: this imported document is a sub-spec for the Knowledge Hub / Evidence RAG subsystem. It does not override the Evidence-Grounded Controlled Code Generation Agent Platform top-level workflow, safety policy, or artifact contract.

<!-- Dev specification skeleton for the project. Fill sections with details later. -->
# Developer Specification (DEV_SPEC)

> 版本：0.1 — 文档结构草案

## 目录

- 项目概述
- 核心特点
- 技术选型
- 测试方案
- 系统架构与模块设计
- 项目排期
- 可扩展性与未来展望

---

## 1. 项目概述
本项目基于多阶段检索增强生成（RAG, Retrieval-Augmented Generation）与模型上下文协议（MCP, Model Context Protocol）设计，目标是搭建一个可扩展、高可观测、易迭代的智能问答与知识检索框架。

### 设计理念 (Design Philosophy)

> **核心定位：自学与教学同步 (Learning by Teaching)**
> 
> 本项目是我个人技术学习、丰富简历、备战面试的实战历程，同时也是一份同步教学的开源资源。我相信"**教是最好的学**"——在整理代码、撰写文档、录制视频的过程中，我自己对 RAG 的理解也在不断深化。希望这份"边学边教"的成果能够帮助到更多同样在求职路上的朋友。

本项目不仅是一个功能完备的智能问答框架，更是一个专为 **RAG 技术学习与面试求职** 设计的实战平台：

#### 1️⃣ 实战驱动学习 (Learn by Doing)
项目架构本身就是 RAG 面试题的"**活体答案**"。我们将经典面试考点直接融入代码设计，通过动手实践来巩固理论知识：
- 分层检索 (Hierarchical Retrieval)
- Hybrid Search (BM25 + Dense Embedding)
- Rerank 重排序机制
- Embedding 策略与优化
- RAG 性能评测 (Ragas/DeepEval)

#### 2️⃣ 开箱即用与深度扩展并重 (Plug-and-Play & Extensible)
- **开箱即用**：提供 MCP 标准接口，可直接对接 Copilot/Claude，拿到项目即可运行体验。
- **深度扩展**：保留完全模块化的内部结构，方便开发者替换组件、魔改算法，作为具备深度的个人简历项目。
- **扩展指引**：文档中会明确指出各模块的扩展方向与建议，帮助你在掌握基础后继续深入迭代。

#### 3️⃣ 配套教学资源 (Comprehensive Learning Materials)
我会提供**三位一体**的配套学习资源，帮助你快速吃透项目：

| 资源类型 | 内容说明 |
|---------|---------|
| 📄 **技术文档** | 架构设计文档、技术选型说明、模块详解 |
| 💻 **代码示范** | 带详细注释的源码、关键模块的 Step-by-step 实现 |
| 🎬 **视频讲解** | RAG 核心知识点回顾、代码细节精讲、环境配置教程 |

#### 4️⃣ 学习路线与面试指南 (Study Guide & Interview Prep)
针对每个模块，我会整理：
- **📚 知识点清单**：这块涉及哪些理论知识需要提前学习（如 BM25 原理、FAISS 索引类型、Cross-Encoder vs Bi-Encoder）
- **❓ 高频面试题**：结合项目代码讲解常见面试问题及参考答案
- **📝 简历撰写建议**：如何将本项目的亮点写进简历，突出技术深度

#### 5️⃣ 社区交流与持续迭代 (Community & Iteration)
- **经验分享**：我自己的面试经历、大家使用本项目面试的反馈，都会汇总沉淀
- **问题讨论**：一起探讨"如何将本项目写进简历"、"针对本项目的面试题怎么答"
- **持续更新**：从代码 → 八股知识 → 面试技巧，形成完整的求职知识库，帮助大家更好地拿到 Offer 🎯

---

## 2. 核心特点

### RAG 策略与设计亮点
本项目在 RAG 链路的关键环节采用了经典的工程化优化策略，平衡了检索的查准率与查全率，具体思想如下：
- **分块策略 (Chunking Strategy)**：采用智能分块与上下文增强，为高质量检索打下基础。
    - **智能分块**：摒弃机械的定长切分，采用语义感知的切分策略以保留完整语义；
    - **上下文增强**：为 Chunk 注入文档元数据（标题、页码）和图片描述（Image Caption），确保检索时不仅匹配文本，还能感知上下文。
- **粗排召回 (Coarse Recall / Hybrid Search)**：采用 **混合检索** 策略作为第一阶段召回，快速筛选候选集。
    - 结合 **稀疏检索 (Sparse Retrieval/BM25)** 利用关键词精确匹配，解决专有名词查找问题；
    - 结合 **稠密检索 (Dense Retrieval/Embedding)** 利用语义向量，解决同义词与模糊表达问题；
    - 两者互补，通过 RRF (Reciprocal Rank Fusion) 算法融合，确保查全率与查准率的平衡。
- **精排重排 (Rerank / Fine Ranking)**：在粗排召回的基础上进行深度语义排序。
	- 采用 Cross-Encoder（专用重排模型）或 LLM Rerank（可选后端）对候选集进行逐一打分，识别细微的语义差异。
    - 通过 **"粗排(低成本泛召回) -> 精排(高成本精过滤)"** 的两段式架构，在不牺牲整体响应速度的前提下大幅提升 Top-Results 的精准度。

### 全链路可插拔架构 (Pluggable Architecture)
鉴于 AI 技术的快速演进，本项目在架构设计上追求**极致的灵活性**，拒绝与特定模型或供应商强绑定。**整个系统**（不仅是 RAG 链路）的每一个核心环节均定义了抽象接口，支持"乐高积木式"的自由替换与组合：

- **LLM 调用层插拔 (LLM Provider Agnostic)**：
    - 核心推理 LLM 通过统一的抽象接口封装，支持**多协议**无缝切换：
        - **Azure OpenAI**：企业级 Azure 云端服务，符合合规与安全要求；
        - **OpenAI API**：直接对接 OpenAI 官方接口；
        - **本地模型**：支持 Ollama、vLLM、LM Studio 等本地私有化部署方案；
        - **其他云服务**：DeepSeek、Anthropic Claude 等第三方 API。
    - 通过配置文件一键切换后端，**零代码修改**即可完成 LLM 迁移，便于成本优化、隐私合规或 A/B 测试。

- **Embedding & Rerank 模型插拔 (Model Agnostic)**：
    - Embedding 模型与 Rerank 模型同样采用统一接口封装；
    - 支持云端服务（OpenAI Embedding, Cohere Rerank）与本地模型（Sentence-Transformers, BGE）自由切换。

- **RAG Pipeline 组件插拔**：
    - **Loader（解析器）**：支持 PDF、Markdown、Code 等多种文档解析器独立替换；
    - **Smart Splitter（切分策略）**：语义切分、定长切分、递归切分等策略可配置；
    - **Transformation（元数据/图文增强逻辑）**：OCR、Image Captioning 等增强模块可独立配置。

- **检索策略插拔 (Retrieval Strategy)**：
    - 支持动态配置纯向量、纯关键词或混合检索模式；
    - 支持灵活更换向量数据库后端（如从 Chroma 迁移至 Qdrant、Milvus）。

- **评估体系插拔 (Evaluation Framework)**：
    - 评估模块不锁定单一指标，支持挂载不同的 Evaluator（如 Ragas, DeepEval）以适应不同的业务考核维度。

这种设计确保开发者可以**零代码修改**即可进行 A/B 测试、成本优化或隐私迁移，使系统具备极强的生命力与环境适应性。

### MCP 生态集成 (Copilot / ReSearch)
本项目的核心设计完全遵循 Model Context Protocol (MCP) 标准，这使得它不仅是一个独立的问答服务，更是一个即插即用的知识上下文提供者。

- **工作原理**：
    - 我们的 Server 作为一个 **MCP Server** 运行，暴露一组标准的 `tools` 和 `resources` 接口。
    - **MCP Clients**（如 GitHub Copilot, ReSearch Agent, Claude Desktop 等）可以直接连接到这个 Server。
    - **无缝接入**：当你在 GitHub Copilot 中提问时，Copilot 作为一个 MCP Host，能够自动发现并调用我们的 Server 提供的工具（如 `search_documentation`），获取我们内置的私有文档知识，然后结合这些上下文来回答你的问题。
- **优势**：
    - **零前端开发**：无需为知识库开发专门的 Chat UI，直接复用开发者已有的编辑器（VS Code）和 AI 助手。
    - **上下文互通**：Copilot 可以同时看到你的代码文件和我们的知识库内容，进行更深度的推理。
    - **标准兼容**：任何支持 MCP 的 AI Agent（不仅是 Copilot）都可以即刻接入我们的知识库，一次开发，处处可用。

### 多模态图像处理 (Multimodal Image Processing)
本项目采用了经典的 **"Image-to-Text" (图转文)** 策略来处理文档中的图像内容，实现了低成本且高效的多模态检索：
- **图像描述生成 (Captioning)**：利用 LLM 的视觉能力，自动提取文档中插图的核心信息，并生成详细的文字描述（Caption）。
- **统一向量空间**：将生成的图像描述文字直接嵌入到文档文本块（Chunk）中进行向量化。
- **优势**：
    - **架构统一**：无需引入复杂的 CLIP 等多模态向量库，复用现有的纯文本 RAG 检索链路即可实现“搜文字出图”。
    - **语义对齐**：通过 LLM 将图像的视觉特征转化为语义理解，使用户能通过自然语言精准检索到图表、流程图等视觉信息。

### 可观测性、可视化管理与评估体系 (Observability, Visual Management & Evaluation)
针对 RAG 系统常见的“黑盒”问题，本项目致力于让每一次生成过程都**透明可见**且**可量化**，并提供完整的**本地可视化管理平台**：
- **全链路白盒化 (White-box Tracing)**：
    - 记录并可视化 RAG 流水线的每一个中间状态：覆盖 Ingestion（加载→切分→增强→编码→存储）与 Query（查询预处理→Dense/Sparse 召回→融合→重排→响应构建）两条完整链路。
    - 开发者可以清晰看到“系统为什么选了这个文档”以及“Rerank 起了什么作用”，从而精准定位坏 Case。
- **可视化管理平台 (Visual Management Dashboard)**：
    - 基于 Streamlit 的本地 Web 管理面板，提供六大功能页面：
        - **系统总览**：展示当前可插拔组件配置（LLM/Embedding/Splitter/Reranker）与数据资产统计。
        - **数据浏览器**：查看已索引的文档列表、Chunk 详情（原文、metadata 各字段、关联图片），支持搜索过滤。
        - **Ingestion 管理**：通过界面选择文件触发摄取、实时展示各阶段进度、支持删除已摄入文档（跨 4 个存储的协调删除）。
        - **Query 追踪**：查询历史列表，耗时瀑布图，Dense/Sparse 召回对比，Rerank 前后排名变化。
        - **Ingestion 追踪**：摄取历史列表，各阶段耗时与处理详情。
        - **评估面板**：运行评估任务、查看各项指标、历史趋势对比。
    - 所有页面基于 Trace 中的 `method`/`provider` 字段**动态渲染**，更换可插拔组件后 Dashboard 自动适配，无需修改代码。
- **自动化评估闭环 (Automated Evaluation)**：
    - 集成 Ragas 等评估框架（可插拔），为每一次检索和生成计算“体检报告”（如召回率 Hit Rate、准确性 Faithfulness 等指标）。
    - 拒绝“凭感觉”调优，建立基于数据的迭代反馈回路，确保每一次策略调整（如修改 Chunk Size 或更换 Reranker）都有量化的分数支撑。

### 业务可扩展性 (Extensibility for Your Own Projects)
本项目采用**通用化架构设计**，不仅是一个开箱即用的知识问答系统，更是一个可以快速适配各类业务场景的**扩展基座**：

- **Agent 客户端扩展 (Build Your Own Agent Client)**：
    - 本项目的 MCP Server 天然支持被各类 Agent 调用，你可以基于此构建属于自己的 Agent 客户端：
        - **学习 Agent 开发**：通过实现一个调用本 Server 的 Agent，深入理解 Agent 的核心概念（Tool Calling、Chain of Thought、ReAct 模式等）；
        - **定制业务 Agent**：结合你的具体业务需求，开发专属的智能助手（如代码审查 Agent、文档写作 Agent、客服问答 Agent）；
        - **多 Agent 协作**：将本 Server 作为知识检索 Agent，与其他功能 Agent（如代码生成、任务规划）组合，构建复杂的 Multi-Agent 系统。

- **业务场景快速适配 (Adapt to Your Domain)**：
    - **数据层扩展**：只需替换数据源（接入你自己的文档、数据库、API），即可将本系统改造为你的私有知识库；
    - **检索逻辑定制**：基于可插拔架构，轻松调整检索策略以适配不同业务特点（如电商搜索偏重关键词、法律文档偏重语义）；
    - **Prompt 模板定制**：修改系统 Prompt 和输出格式，使其符合你的业务风格与专业术语。

- **学习与实战并重 (Learn While Building)**：
    - 通过扩展本项目，你将同步掌握：
        - **Agent 架构设计**：Function Calling、Tool Use、Memory 管理等核心概念；
        - **LLM 应用工程化**：Prompt Engineering、Token 优化、流式输出等实战技能；
        - **系统集成能力**：如何将 AI 能力嵌入现有业务系统，构建端到端的智能应用。

这种设计让本项目不仅是"学完即弃"的 Demo，而是可以**持续迭代、真正落地**的工程化模板，帮助你将学到的知识转化为实际项目经验。


## 3. 技术选型

### 3.1 RAG 核心流水线设计 

#### 3.1.1 数据摄取流水线 

**目标：** 构建统一、可配置且可观测的数据摄取流水线，覆盖文档加载、格式解析、语义切分、多模态增强、嵌入计算、去重与批量上载到向量存储。该能力应是可重用的库模块，便于在 `ingest.py`、Dashboard 管理面板、离线批处理和测试中调用。

- **自研 Pipeline 框架（设计灵感参考 LlamaIndex 分层思想，但不依赖 LlamaIndex 库）：**
	- 采用自定义抽象接口（`BaseLoader`/`BaseSplitter`/`BaseTransform`/`BaseEmbedding`/`BaseVectorStore`），实现完全可控的可插拔架构。
	- 支持可组合的 Loader -> Splitter -> Transform -> Embed -> Upsert 流程，便于实现可观测的流水线。
	- 与主流 embedding provider 有良好适配，架构中统一使用 Chroma 作为向量存储。


设计要点：
- **明确分层职责**：
  - Loader：负责把原始文件解析为统一的 `Document` 对象（`text` + `metadata`；类型定义集中在 `src/core/types.py`）。**在当前阶段，仅实现 PDF 格式的 Loader。**
		- 统一输出格式采用规范化 Markdown作为 `Document.text`：这样可以更好的配合后面的Splitte（Langchain RecursiveCharacterTextSplitte））方法产出高质量切块。
		- Loader 同时抽取/补齐基础 metadata（如 `source_path`, `doc_type=pdf`, `page`, `title/heading_outline`, `images` 引用列表等），为定位、回溯与后续 Transform 提供依据。
	- Splitter：基于 Markdown 结构（标题/段落/代码块等）与参数配置把 `Document` 切为若干 Chunk，保留原始位置与上下文引用。
	- Transform：可插入的处理步骤（ImageCaptioning、OCR、code-block normalization、html-to-text cleanup 等），Transform 可以选择把额外信息追加到 chunk.text 或放入 chunk.metadata（推荐默认追加到 text 以保证检索覆盖）。
	- Embed & Upsert：按批次计算 embedding，并上载到向量存储；支持向量 + metadata 上载，并提供幂等 upsert 策略（基于 id/hash）。
	- Dedup & Normalize：在上载前运行向量/文本去重与哈希过滤，避免重复索引。

关键实现要素：

- Loader（统一格式与元数据）
	- **前置去重 (Early Exit / File Integrity Check)**：
		- 机制：在解析文件前，计算原始文件的 SHA256 哈希指纹。
		- 动作：检索 `ingestion_history` 表，若发现相同 Hash 且状态为 `success` 的记录，则认定该文件未发生变更，直接跳过后续所有处理（解析、切分、LLM重写），实现**零成本 (Zero-Cost)** 的增量更新。
		- **存储方案**（初期实现，可插拔）：
			- **默认选择：SQLite**，存储于 `data/db/ingestion_history.db`
			- **表结构**：
				```sql
				CREATE TABLE ingestion_history (
				    file_hash TEXT PRIMARY KEY,
				    file_path TEXT NOT NULL,
				    file_size INTEGER,
				    status TEXT NOT NULL CHECK(status IN ('success', 'failed', 'processing')),
				    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
				    error_msg TEXT,
				    chunk_count INTEGER
				);
				CREATE INDEX idx_status ON ingestion_history(status);
				CREATE INDEX idx_processed_at ON ingestion_history(processed_at);
				```
			- **查询逻辑**：`SELECT status FROM ingestion_history WHERE file_hash = ? AND status = 'success'`
			- **替换路径**：后续可升级为 Redis（分布式缓存）或 PostgreSQL（企业级中心化存储）
	
	> **📌 持久化存储架构统一说明**
	> 
	> 本项目在多个核心模块中采用 **SQLite** 作为轻量级持久化存储方案，避免引入重量级数据库依赖，保持本地优先（Local-First）的设计理念：
	> 
	> | 存储模块 | 数据库文件 | 用途 | 表结构关键字段 |
	> |---------|-----------|------|---------------|
	> | **文件完整性检查** | `data/db/ingestion_history.db` | 记录已处理文件的 SHA256 哈希，实现增量摄取 | `file_hash`, `status`, `processed_at` |
	> | **图片索引映射** | `data/db/image_index.db` | 记录 image_id → 文件路径映射，支持图片检索与引用 | `image_id`, `file_path`, `collection` |
	> | **BM25 索引元数据** | `data/db/bm25/` | 存储倒排索引和 IDF 统计信息（未来可扩展用 SQLite） | 当前使用 pickle，可迁移至 SQLite |
	> 
	> **设计优势**：
	> - **零依赖部署**：无需安装 MySQL/PostgreSQL 等数据库服务，`pip install` 即可运行
	> - **并发安全**：WAL (Write-Ahead Logging) 模式支持多进程安全读写
	> - **持久化保证**：摄取历史和索引映射在进程重启后自动恢复，避免重复计算
	> - **架构一致性**：所有 SQLite 模块遵循相同的初始化、查询与错误处理模式，便于维护与扩展
	> 
	> **升级路径**：当系统规模扩展至分布式场景时，可通过统一的抽象接口将 SQLite 替换为 PostgreSQL 或 Redis，无需修改上层业务逻辑。
	
	- **解析与标准化**：
		- 当前范围：**仅实现 PDF -> canonical Markdown 子集** 的转换。
	- 技术选型（Python PDF -> Markdown）：
		- **首选：MarkItDown**（作为默认 PDF 解析/转换引擎）。优点是直接产出 Markdown 形态文本，便于与后续 `RecursiveCharacterTextSplitter` 的 separators 配合。
	- 输出标准 `Document`：`id|source|text(markdown)|metadata`。metadata 至少包含 `source_path`, `doc_type`, `title/heading_outline`, `page/slide`（如适用）, `images`（图片引用列表）。
	- Loader 不负责切分：只做“格式统一 + 结构抽取 + 引用收集”，确保切分策略可独立迭代与度量。

- Splitter（LangChain 负责切分；独立、可控）
	- **实现方案：使用 LangChain 的 `RecursiveCharacterTextSplitter` 进行切分。**
		- 优势：该方法对 Markdown 文档的结构（标题、段落、列表、代码块）有天然的适配性，能够通过配置语义断点（Separators）实现高质量、语义完整的切块。
	- Splitter 输入：Loader 产出的 Markdown `Document`。
	- Splitter 输出：若干 `Chunk`（或 Document-like chunks），每个 chunk 必须携带稳定的定位信息与来源信息：`source`, `chunk_index`, `start_offset/end_offset`（或等价定位字段）。

- Transform & Enrichment（结构转换与深度增强）
	本阶段是 ETL 管道的核心“智力”环节，负责将 Splitter 产出的非结构化文本块转化为结构化、富语义的智能切片（Smart Chunk）。
	- **结构转换 (Structure Transformation)**：将原始的 `String` 类型数据转化为强类型的 `Record/Object`，为下游检索提供字段级支持。
	- **核心增强策略**：
		1. **智能重组 (Smart Chunking & Refinement)**：
			- 策略：利用 LLM 的语义理解能力，对上一阶段“粗切分”的片段进行二次加工。
			- 动作：合并在逻辑上紧密相关但被物理切断的段落，剔除无意义的页眉页脚或乱码（去噪），确保每个 Chunk 是自包含（Self-contained）的语义单元。
		2. **语义元数据注入 (Semantic Metadata Enrichment)**：
			- 策略：在基础元数据（路径、页码）之上，利用 LLM 提取高维语义特征。
			- 产出：为每个 Chunk 自动生成 `Title`（精准小标题）、`Summary`（内容摘要）和 `Tags`（主题标签），并将其注入到 Metadata 字段中，支持后续的混合检索与精确过滤。
		3. **多模态增强 (Multimodal Enrichment / Image Captioning)**：
			- 策略：扫描文档片段中的图像引用，调用 Vision LLM（如 GPT-4o）进行视觉理解。
			- 动作：生成高保真的文本描述（Caption），描述图表逻辑或提取截图文字。
			- 存储：将 Caption 文本“缝合”进 Chunk 的正文或 Metadata 中，打通模态隔阂，实现“搜文出图”。
	- **工程特性**：Transform 步骤设计为原子化与幂等操作，支持针对特定 Chunk 的独立重试与增量更新，避免因 LLM 调用失败导致整个文档处理中断。

- **Embedding (双路向量化)**
	- **差量计算 (Incremental Embedding / Cost Optimization)**：
		- 策略：在调用昂贵的 Embedding API 之前，计算 Chunk 的内容哈希（Content Hash）。仅针对数据库中不存在的新内容哈希执行向量化计算，对于文件名变更但内容未变的片段，直接复用已有向量，显著降低 API 调用成本。
	- **核心策略**：为了支持高精度的混合检索（Hybrid Search），系统对每个 Chunk 并行执行双路编码计算。
		- **Dense Embeddings（语义向量）**：调用 Embedding 模型（如 OpenAI text-embedding-3 或 BGE）生成高维浮点向量，捕捉文本的深层语义关联，解决“词不同意同”的检索难题。
		- **Sparse Embeddings（稀疏向量）**：利用 BM25 编码器或 SPLADE 模型生成稀疏向量（Keyword Weights），捕捉精确的关键词匹配信息，解决专有名词查找问题。
	- **批处理优化**：所有计算均采用 `batch_size` 驱动的批处理模式，最大化 CPU 利用率并减少网络 RTT。

- **Upsert & Storage (索引存储)**
	- **存储后端**：统一使用向量数据库（如 Chroma/Qdrant）作为存储引擎，同时持久化存储 Dense Vector、Sparse Vector 以及 Transform 阶段生成的富 Metadata。
	- **All-in-One 存储策略**：执行原子化存储，每条记录同时包含：
		1. **Index Data**: 用于计算相似度的 Dense Vector 和 Sparse Vector。
		2. **Payload Data**: 完整的 Chunk 原始文本 (Content) 及 Metadata。
		**机制优势**：确保检索命中 ID 后能立即取回对应的正文内容，无需额外的查库操作 (Lookup)，保障了 Retrieve 阶段的毫秒级响应。
- **幂等性设计 (Idempotency)**：
		- 为每个 Chunk 生成全局唯一的 `chunk_id`，生成算法采用确定的哈希组合：`hash(source_path + section_path + content_hash)`。
		- 写入时采用 "Upsert"（更新或插入）语义，确保同一文档即使被多次处理，数据库中也永远只有一份最新副本，彻底避免重复索引问题。
	- **原子性保证**：以 Batch 为单位进行事务性写入，确保索引状态的一致性。

- **文档生命周期管理 (Document Lifecycle Management)**

	为支持 Dashboard 管理面板中的文档浏览与删除功能，Ingestion 层需要提供完整的文档生命周期管理能力：

	- **DocumentManager（文档管理器）**：独立于 Pipeline 的文档管理模块（`src/ingestion/document_manager.py`），负责跨存储的协调操作：
		- `list_documents(collection?) -> List[DocumentInfo]`：列出已摄入文档及其统计信息（chunk 数、图片数、摄入时间）。
		- `get_document_detail(doc_id) -> DocumentDetail`：获取单个文档的详细信息（所有 chunk 内容、metadata、关联图片）。
		- `delete_document(source_path, collection) -> DeleteResult`：协调删除跨 4 个存储的关联数据：
			1. **Chroma** — 按 `metadata.source` 删除所有 chunk 向量
			2. **BM25 Indexer** — 移除对应文档的倒排索引条目
			3. **ImageStorage** — 删除该文档关联的所有图片文件
			4. **FileIntegrity** — 移除处理记录，使文件可重新摄入
		- `get_collection_stats(collection?) -> CollectionStats`：返回集合级统计（文档数、chunk 数、存储大小等）。

	- **Pipeline 进度回调 (Progress Callback)**：在 `IngestionPipeline.run()` 方法中新增可选 `on_progress` 参数：
		```python
		def run(self, source_path: str, collection: str = "default",
		        on_progress: Callable[[str, int, int], None] | None = None) -> IngestionResult:
		```
		- 回调签名：`on_progress(stage_name: str, current: int, total: int)`
		- 各阶段（load / split / transform / embed / upsert）在处理每个 batch 时调用回调，Dashboard 据此展示实时进度条。
		- `on_progress` 为 `None` 时行为与当前完全一致，不影响 CLI 和测试场景。

	- **存储层接口扩展**：为支持 DocumentManager 的删除操作，需扩展以下存储接口：
		- `BaseVectorStore` 新增 `delete_by_metadata(filter: dict) -> int` — 按 metadata 条件批量删除
		- `BM25Indexer` 新增 `remove_document(source: str) -> None` — 移除指定文档的索引条目
		- `FileIntegrityChecker` 新增 `remove_record(file_hash: str) -> None` 和 `list_processed() -> List[dict]`

#### 3.1.2 检索流水线


本模块实现核心的 RAG 检索引擎，采用 **“多阶段过滤 (Multi-stage Filtering)”** 架构，负责接收已消歧的独立查询（Standalone Query），并精准召回 Top-K 最相关片段。

- **Query Processing (查询预处理)**
	- **核心假设**：输入 Query 已由上游（Client/MCP Host）完成会话上下文补全（De-referencing），不仅如此，还进行了指代消歧。
	- **查询转换 (Transformation) 与扩张策略 (Expansion Strategy)**：
		- **Keyword Extraction**：利用 NLP 工具提取 Query 中的关键实体与动词（去停用词），生成用于稀疏检索的 Token 列表。
		- **Query Expansion **：
			- 系统可做 Synonym/Alias Expansion（同义词/别名/缩写扩展），默认策略采用“**扩展融入稀疏检索、稠密检索保持单次**”以控制成本与复杂度。
			- **Sparse Route (BM25)**：将“关键词 + 同义词/别名”合并为一个查询表达式（逻辑上按 `OR` 扩展），**只执行一次稀疏检索**。原始关键词可赋予更高权重以抑制语义漂移。
			- **Dense Route (Embedding)**：使用原始 query（或轻度改写后的语义 query）生成 embedding，**只执行一次稠密检索**；默认不为每个同义词单独触发额外的向量检索请求。

- **Hybrid Search Execution (双路混合检索)**
	- **并行召回 (Parallel Execution)**：
		- **Dense Route**：计算 Query Embedding -> 检索向量库（Cosine Similarity）-> 返回 Top-N 语义候选。
		- **Sparse Route**：使用 BM25 算法 -> 检索倒排索引 -> 返回 Top-N 关键词候选。
	- **结果融合 (Fusion)**：
		- 采用 **RRF (Reciprocal Rank Fusion)** 算法，不依赖各路分数的绝对值，而是基于排名的倒数进行加权融合。
		- 公式策略：`Score = 1 / (k + Rank_Dense) + 1 / (k + Rank_Sparse)`，平滑因单一模态缺陷导致的漏召回。

- **Filtering & Reranking (精确过滤与重排)**
	- **Metadata Filtering Strategy (通用过滤策略)**：
		- **原则：先解析、能前置则前置、无法前置则后置兜底。**
		- Query Processing 阶段应将结构化约束解析为通用 `filters`（例如 `collection`/`doc_type`/`language`/`time_range`/`access_level` 等）。
		- 若底层索引支持且属于硬约束（Hard Filter），则在 Dense/Sparse 检索阶段做 Pre-filter 以缩小候选集、降低成本。
		- 无法前置的过滤（索引不支持或字段缺失/质量不稳）在 Rerank 前统一做 Post-filter 作为 safety net；对缺失字段默认采取“宽松包含”(missing->include) 以避免误杀召回。
		- 软偏好（Soft Preference，例如“更近期更好”）不应硬过滤，而应作为排序信号在融合/重排阶段加权。
	- **Rerank Backend (可插拔精排后端)**：
		- **目标**：在 Top-M 候选上进行高精度排序/过滤；该模块必须可关闭，并提供稳定回退策略。
		- **后端选项**：
			1. **None (关闭精排)**：直接返回融合后的 Top-K（RRF 排名作为最终结果）。
			2. **Cross-Encoder Rerank (本地/托管模型)**：输入为 `[Query, Chunk]` 对，输出相关性分数并排序；适合稳定、结构化输出。CPU 环境下建议默认仅对较小的 Top-M 执行（例如 M=10~30），并提供超时回退。
			3. **LLM Rerank (可选)**：使用 LLM 对候选集排序/选择；适合需要更强指令理解或无本地模型环境时。为控制成本与稳定性，候选数应更小（例如 M<=20），并要求输出严格结构化格式（如 JSON 的 ranked ids）。
		- **默认与回退 (Fallback)**：
			- 默认策略面向通用框架与 CPU 环境：优先保证“可用与可控”，Cross-Encoder/LLM 均为可选增强。
			- 当精排不可用/超时/失败时，必须回退到融合阶段的排序（RRF Top-K），确保系统可用性与结果稳定性。

### 3.2 MCP 服务设计 (MCP Service Design)

**目标：** 设计并实现一个符合 Model Context Protocol (MCP) 规范的 Server，使其能够作为知识上下文提供者，无缝对接主流 MCP Clients（如 GitHub Copilot、Claude Desktop 等），让用户通过现有 AI 助手即可查询私有知识库。

#### 3.2.1 核心设计理念

- **协议优先 (Protocol-First)**：严格遵循 MCP 官方规范（JSON-RPC 2.0），确保与任何合规 Client 的互操作性。
- **开箱即用 (Zero-Config for Clients)**：Client 端无需任何特殊配置，只需在配置文件中添加 Server 连接信息即可使用全部功能。
- **引用透明 (Citation Transparency)**：所有检索结果必须携带完整的来源信息，支持 Client 端展示"回答依据"，增强用户对 AI 输出的信任。
- **多模态友好 (Multimodal-Ready)**：返回格式应支持文本与图像等多种内容类型，为未来的富媒体展示预留扩展空间。

#### 3.2.2 传输协议：Stdio 本地通信

本项目采用 **Stdio Transport** 作为唯一通信模式。

- **工作方式**：Client（VS Code Copilot、Claude Desktop）以子进程方式启动我们的 Server，双方通过标准输入/输出交换 JSON-RPC 消息。
- **选型理由**：
	- **零配置**：无需网络端口、无需鉴权，用户只需在 Client 配置文件中指定启动命令即可使用。
	- **隐私安全**：数据不经过网络，天然适合处理私有知识库与敏感业务数据。
	- **契合定位**：Stdio 完美适配开发者本地工作流，满足私有知识管理与快速原型验证需求。
- **实现约束**：
	- `stdout` 仅输出合法 MCP 消息，禁止混入任何日志或调试信息。
	- 日志统一输出至 `stderr`，避免污染通信通道。

#### 3.2.3 SDK 与实现库选型

- **首选：Python 官方 MCP SDK (`mcp`)**
	- **优势**：
		- 官方维护，与协议规范同步更新，保证最新特性支持（如 `outputSchema`、`annotations` 等）。
		- 提供 `@server.tool()` 等装饰器，声明式定义 Tools/Resources/Prompts，代码简洁。
		- 内置 Stdio 与 HTTP Transport 支持，无需手动处理 JSON-RPC 序列化与生命周期管理。
	- **适用**：本项目的默认实现方案。

- **备选：FastAPI + 自定义协议层**
	- **场景**：需要深度定制 HTTP 行为（如自定义中间件、复杂鉴权流程）或希望学习 MCP 协议底层细节时可考虑。
	- **权衡**：开发成本更高，需自行实现能力协商 (Capability Negotiation)、错误码映射等，且需持续跟进协议版本更新。

- **协议版本**：跟踪 MCP 最新稳定版本（如 `2025-06-18`），在 `initialize` 阶段进行版本协商，确保 Client/Server 兼容性。

#### 3.2.4 对外暴露的工具函数设计 (Tools Design)

Server 通过 `tools/list` 向 Client 注册可调用的工具函数。工具设计应遵循"单一职责、参数明确、输出丰富"原则。

- **核心工具集**：

| 工具名称 | 功能描述 | 典型输入参数 | 输出特点 |
|---------|---------|-------------|---------|
| `query_knowledge_hub` | 主检索入口，执行混合检索 + Rerank，返回最相关片段 | `query: string`, `top_k?: int`, `collection?: string` | 返回带引用的结构化结果 |
| `list_collections` | 列举知识库中可用的文档集合 | 无 | 集合名称、描述、文档数量 |
| `get_document_summary` | 获取指定文档的摘要与元信息 | `doc_id: string` | 标题、摘要、创建时间、标签 |

- **扩展工具（Agentic 演进方向）**：
	- `search_by_keyword` / `search_by_semantic`：拆分独立的检索策略，供 Agent 自主选择。
	- `verify_answer`：事实核查工具，检测生成内容是否有依据支撑。
	- `list_document_sections`：浏览文档目录结构，支持多步导航式检索。

#### 3.2.5 返回内容与引用透明设计 (Response & Citation Design)

MCP 协议的 Tool 返回格式支持多种内容类型（`content` 数组），本项目将充分利用这一特性实现"可溯源"的回答：

- **结构化引用设计**：
	- 每个检索结果片段应包含完整的定位信息：`source_file`（文件名/路径）、`page`（页码，如适用）、`chunk_id`（片段标识）、`score`（相关性分数）。
	- 推荐在返回的 `structuredContent` 中采用统一的 Citation 格式：
		```
		{
		  "answer": "...",
		  "citations": [
		    { "id": 1, "source": "xxx.pdf", "page": 5, "text": "原文片段...", "score": 0.92 },
		    ...
		  ]
		}
		```
	- 同时在 `content` 数组中以 Markdown 格式呈现人类可读的带引用回答（`[1]` 标注），保证 Client 无论是否解析结构化内容都能展示引用。

- **多模态内容返回**：
	- **文本内容 (TextContent)**：默认返回类型，Markdown 格式，支持代码块、列表等富文本。
	- **图像内容 (ImageContent)**：当检索结果关联图像时，Server 读取本地图片文件并编码为 Base64 返回。
		- **格式**：`{ "type": "image", "data": "<base64>", "mimeType": "image/png" }`
		- **工作流程**：数据摄取阶段存储图片本地路径 → 检索命中后 Server 动态读取 → 编码为 Base64 → 嵌入返回消息。
		- **Client 兼容性**：图像展示能力取决于 Client 实现，GitHub Copilot 可能降级处理，Claude Desktop 支持完整渲染。Server 端统一返回 Base64 格式，由 Client 决定如何渲染。

- **Client 适配策略**：
	- **GitHub Copilot (VS Code)**：当前对 MCP 的支持集中在 Tools 调用，返回的 `content` 中的文本会展示给用户。建议以清晰的 Markdown 文本（含引用标注）为主，图像作为补充。
	- **Claude Desktop**：对 MCP Tools/Resources 有完整支持，图像与资源链接可直接渲染。可更激进地使用多模态返回。
	- **通用兼容原则**：始终在 `content` 数组第一项提供纯文本/Markdown 版本的答案，确保最低兼容性；将结构化数据、图像等放在后续项或 `structuredContent` 中，供高级 Client 解析。

### 3.3 可插拔架构设计 (Pluggable Architecture Design)

**目标：** 定义清晰的抽象层与接口契约，使 RAG 链路的每个核心组件都能够独立替换与升级，避免技术锁定，支持低成本的 A/B 测试与环境迁移。

> **术语说明**：本节中的"提供者 (Provider)"、"实现 (Implementation)"指的是完成某项功能的**具体技术方案**，而非传统 Web 架构中的"后端服务器"。例如，LLM 提供者可以是远程的 Azure OpenAI API，也可以是本地运行的 Ollama；向量存储可以是本地嵌入式的 Chroma，也可以是云端托管的 Pinecone。本项目作为本地 MCP Server，通过统一接口对接这些不同的提供者，实现灵活切换。

#### 3.3.1 设计原则

- **接口隔离 (Interface Segregation)**：为每类组件定义最小化的抽象接口，上层业务逻辑仅依赖接口而非具体实现。
- **配置驱动 (Configuration-Driven)**：通过统一配置文件（如 `settings.yaml`）指定各组件的具体后端，代码无需修改即可切换实现。
- **工厂模式 (Factory Pattern)**：使用工厂函数根据配置动态实例化对应的实现类，实现"一处配置，处处生效"。
- **优雅降级 (Graceful Fallback)**：当首选后端不可用时，系统应自动回退到备选方案或安全默认值，保障可用性。

**通用结构示意（适用于 3.3.2 / 3.3.3 / 3.3.4 等可插拔组件）**：

```
业务代码
  │
  ▼
<Component>Factory.get_xxx()  ← 读取配置，决定用哪个实现
  │
  ├─→ ImplementationA()
  ├─→ ImplementationB()  
  └─→ ImplementationC()
      │
      ▼
    都实现了统一的抽象接口
```

#### 3.3.2 LLM 与 Embedding 提供者抽象

这是可插拔设计的核心环节，因为模型提供者的选择直接影响成本、性能与隐私合规。

- **统一接口层 (Unified API Abstraction)**：
	- **设计思路**：无论底层使用 Azure OpenAI、OpenAI 原生 API、DeepSeek 还是本地 Ollama，上层调用代码应保持一致。
	- **关键抽象**：
		- `LLMClient`：暴露 `chat(messages) -> response` 方法，屏蔽不同 Provider 的认证方式与请求格式差异。
		- `EmbeddingClient`：暴露 `embed(texts) -> vectors` 方法，统一处理批量请求与维度归一化。

- **提供者选项与切换场景**：

| 提供者类型 | 典型场景 | 配置切换点 |
|---------|---------|-----------|
| **Azure OpenAI** | 企业合规、私有云部署、区域数据驻留 | `provider: azure`, `endpoint`, `api_key`, `deployment_name` |
| **OpenAI 原生** | 通用开发、最新模型尝鲜 | `provider: openai`, `api_key`, `model` |
| **DeepSeek / 其他云端** | 成本优化、特定语言优化 | `provider: deepseek`, `api_key`, `model` |
| **Ollama / vLLM (本地)** | 完全离线、隐私敏感、无 API 成本 | `provider: ollama`, `base_url`, `model` |

- **技术选型建议**：
	- 本项目采用自研的 `BaseLLM` / `BaseEmbedding` 抽象基类，配合工厂模式（`llm_factory.py` / `embedding_factory.py`）实现统一调用接口。已内置 Azure OpenAI、OpenAI、Ollama、DeepSeek 四种 Provider 适配。
	- 对于其他 Provider，可通过 **OpenAI-Compatible 模式**接入（设置自定义 `api_base`），或实现 `BaseLLM` 接口并在工厂中注册。

	- 对于企业级需求，可在其基础上增加统一的 **重试、限流、日志** 中间层，提升生产可靠性，但本项目暂不实现，这里仅提供思路。
	- **Vision LLM 扩展**：针对图像描述生成（Image Captioning）需求，系统扩展了 `BaseVisionLLM` 接口，支持文本+图片的多模态输入。当前实现：
		- **Azure OpenAI Vision**（GPT-4o/GPT-4-Vision）：企业级合规部署，支持复杂图表解析，与 Azure 生态深度集成。

#### 3.3.3 检索策略抽象

检索层的可插拔性决定了系统在不同数据规模与查询模式下的适应能力。

**设计模式：抽象工厂模式**

与 3.3.2 节的 LLM 抽象类似，检索层各组件的可插拔性同样依赖两层设计：

1. **自研的统一抽象接口**：本项目为向量数据库（`BaseVectorStore`）、Embedding（`BaseEmbedding`）、分块（`BaseSplitter`）等核心组件定义了统一的抽象基类，不同实现只需遵循相同接口即可无缝替换。

2. **工厂函数路由**：每个抽象层配套工厂函数（如 `embedding_factory.py`、`splitter_factory.py`），根据 `settings.yaml` 中的配置字段自动实例化对应实现，实现"改配置不改代码"的切换体验。


通用的“配置驱动 + 工厂路由”结构示意见 3.3.1 节。

下面分别说明各组件如何应用这一模式：

---

**1. 分块策略 (Chunking Strategy)**

分块是 Ingestion Pipeline 的核心环节之一，决定了文档如何被切分为适合检索的语义单元。本项目的 Splitter 层采用可插拔设计（BaseSplitter 抽象接口 + SplitterFactory 工厂），不同分块实现只需遵循相同接口即可无缝替换。

常见的分块策略包括：
- **固定长度切分**：按字符数或 Token 数切分，简单但可能破坏语义完整性。
- **递归字符切分**：按层级分隔符（段落→句子→字符）递归切分，在长度限制内尽量保持语义边界。
- **语义切分**：利用 Embedding 相似度检测语义断点，确保每个 Chunk 是自包含的语义单元。
- **结构感知切分**：根据文档结构（Markdown 标题、代码块、列表等）进行切分。

本项目当前采用 **LangChain 的 `RecursiveCharacterTextSplitter`** 进行切分，该方法对 Markdown 文档的结构（标题、段落、列表、代码块）有天然的适配性，能够通过配置语义断点（Separators）实现高质量、语义完整的切块。

> **当前实现说明**：目前系统使用 LangChain RecursiveCharacterTextSplitter。架构设计上预留了切换能力，如需切换为 SentenceSplitter、SemanticSplitter 或自定义切分器，只需实现 BaseSplitter 接口并在配置中指定即可。

---

**2. 向量数据库 (Vector Store)**

本项目自定义了统一的 BaseVectorStore 抽象接口，暴露 .add()、.query()、.delete() 等方法。所有向量数据库后端（Chroma、Qdrant、Pinecone 等）只需实现该接口即可插拔替换，通过 VectorStoreFactory 根据配置自动选择具体实现。

本项目选用 **Chroma** 作为向量数据库。相比 Qdrant、Milvus、Weaviate 等需要 Docker 容器或分布式架构支撑的方案，Chroma 采用嵌入式设计，`pip install chromadb` 即可使用，无需额外部署数据库服务，非常适合本地开发与快速原型验证。同时 ChromaStore 适配器（src/libs/vector_store/chroma_store.py），与 Pipeline 无缝集成。

> **当前实现说明**：目前系统仅实现了 Chroma 后端。虽然架构设计上预留了工厂模式以支持未来扩展，但当前版本尚未实现其他向量数据库的适配器。

---

**3. 向量编码策略 (Embedding Strategy)**

向量编码是 Ingestion Pipeline 的关键环节，决定了 Chunk 如何被转换为可检索的向量表示。本项目自定义了 BaseEmbedding 抽象接口（src/libs/embedding/base.py），支持不同 Embedding 模型的可插拔替换。

常见的编码策略包括：
- **纯稠密编码（Dense Only）**：仅生成语义向量，适合通用场景。
- **纯稀疏编码（Sparse Only）**：仅生成关键词权重向量，适合精确匹配场景。
- **双路编码（Dense + Sparse）**：同时生成稠密向量和稀疏向量，为混合检索提供数据基础。

本项目当前采用 **双路编码（Dense + Sparse）** 策略：
- **Dense Embeddings（语义向量）**：调用 Embedding 模型（如 OpenAI text-embedding-3）生成高维浮点向量，捕捉文本的深层语义关联。
- **Sparse Embeddings（稀疏向量）**：利用 BM25 编码器生成稀疏向量（Keyword Weights），捕捉精确的关键词匹配信息。

存储时，Dense Vector 和 Sparse Vector 与 Chunk 原文、Metadata 一起原子化写入向量数据库，确保检索时可同时利用两种向量。

> **当前实现说明**：目前系统实现了 Dense + Sparse 双路编码。架构设计上预留了切换能力，如需使用其他 Embedding 模型（如 BGE、Ollama 本地模型）或调整编码策略，可在 Pipeline 中替换相应组件。

---

**4. 召回策略 (Retrieval Strategy)**

召回策略决定了查询阶段如何从知识库中检索相关内容。基于 Ingestion 阶段存储的向量类型，可采用不同的召回方案：
- **纯稠密召回（Dense Only）**：仅使用语义向量进行相似度匹配。
- **纯稀疏召回（Sparse Only）**：仅使用 BM25 进行关键词匹配。
- **混合召回（Hybrid）**：并行执行稠密和稀疏两路召回，再通过融合算法合并结果。
- **混合召回 + 精排（Hybrid + Rerank）**：在混合召回基础上，增加精排步骤进一步提升相关性。

本项目当前采用 **混合召回 + 精排（Hybrid + Rerank）** 策略：
- **稠密召回（Dense Route）**：计算 Query Embedding，在向量库中进行 Cosine Similarity 检索，返回 Top-N 语义候选。
- **稀疏召回（Sparse Route）**：使用 BM25 算法检索倒排索引，返回 Top-N 关键词候选。
- **融合（Fusion）**：使用 RRF (Reciprocal Rank Fusion) 算法将两路结果合并排序。
- **精排（Rerank）**：对融合后的候选集进行重排序，支持 None / Cross-Encoder / LLM Rerank 三种模式。

> **当前实现说明**：目前系统实现了 Hybrid + Rerank 策略。架构设计上预留了策略切换能力，如需使用纯稠密或纯稀疏召回，可通过配置切换；融合算法和 Reranker 同样支持替换。

#### 3.3.4 评估框架抽象

评估体系的可插拔性确保团队可以根据业务目标灵活选择或组合不同的质量度量维度。

- **设计思路**：
	- 定义统一的 `Evaluator` 接口，暴露 `evaluate(query, retrieved_chunks, generated_answer, ground_truth) -> metrics` 方法。
	- 各评估框架实现该接口，输出标准化的指标字典。

- **可选评估框架**：

| 框架 | 特点 | 适用场景 |
|-----|------|---------|
| **Ragas** | RAG 专用、指标丰富（Faithfulness, Answer Relevancy, Context Precision 等） | 全面评估 RAG 质量、学术对比 |
| **DeepEval** | LLM-as-Judge 模式、支持自定义评估标准 | 需要主观质量判断、复杂业务规则 |
| **自定义指标** | Hit Rate, MRR, Latency P99 等基础工程指标 | 快速回归测试、上线前 Sanity Check |

- **组合与扩展**：
	- 评估模块设计为**组合模式**，可同时挂载多个 Evaluator，生成综合报告。
	- 配置示例：`evaluation.backends: [ragas, custom_metrics]`，系统并行执行并汇总结果。

#### 3.3.5 配置管理与切换流程

- **配置文件结构示例** (`config/settings.yaml`)：
	```yaml
	llm:
	  provider: azure  # azure | openai | ollama | deepseek
	  model: gpt-4o
	  # provider-specific configs...
	
	embedding:
	  provider: openai
	  model: text-embedding-3-small
	
	vector_store:
	  backend: chroma  # chroma | qdrant | pinecone
	
	retrieval:
	  sparse_backend: bm25  # bm25 | elasticsearch
	  fusion_algorithm: rrf  # rrf | weighted_sum
	  rerank_backend: cross_encoder  # none | cross_encoder | llm
	
	evaluation:
	  backends: [ragas, custom_metrics]
	
	dashboard:
	  enabled: true
	  port: 8501
	  traces_dir: ./logs
	```

- **切换流程**：

	1. 修改 `settings.yaml` 中对应组件的 `backend` / `provider` 字段。
	2. 确保新后端的依赖已安装、凭据已配置。
	3. 重启服务，工厂函数自动加载新实现，无需修改业务代码。

### 3.4 可观测性与可视化管理平台设计 (Observability & Visual Management Platform Design)

**目标：** 针对 RAG 系统常见的"黑盒"问题，设计全链路可观测的追踪体系与完整的可视化管理平台。覆盖 **Ingestion（摄取链路）** 与 **Query（查询链路）** 两条完整流水线的追踪记录，同时提供数据浏览、文档管理、组件概览等管理功能，使整个系统**透明可见**、**可管理**且**可量化**。

#### 3.4.1 设计理念

- **双链路全覆盖追踪 (Dual-Pipeline Tracing)**：
    - **Ingestion Trace**：以 `trace_id` 为核心，记录一次摄取从文件加载到存储完成的全过程（load → split → transform → embed → upsert），包含各阶段耗时、处理的 chunk 数量、跳过/失败详情。
    - **Query Trace**：以 `trace_id` 为核心，记录一次查询从 Query 输入到 Response 输出的全过程（query_processing → dense → sparse → fusion → rerank），包含各阶段候选数量、分数分布与耗时。
- **透明可回溯 (Transparent & Traceable)**：每个阶段的中间状态都被记录，开发者可以清晰看到"系统为什么召回了这些文档"、"Rerank 前后排名如何变化"，从而精准定位问题。
- **低侵入性 (Low Intrusiveness)**：追踪逻辑与业务逻辑解耦，通过 `TraceContext` 显式调用模式注入，避免污染核心代码。
- **轻量本地化 (Lightweight & Local)**：采用结构化日志 + 本地 Dashboard 的方案，零外部依赖，开箱即用。
- **动态组件感知 (Dynamic Component Awareness)**：Dashboard 基于 Trace 中的 `method`/`provider`/`details` 字段动态渲染，更换可插拔组件后自动适配展示内容，无需修改 Dashboard 代码。


#### 3.4.2 追踪数据结构

系统定义两类 Trace 记录，分别覆盖查询与摄取两条链路：

**A. Query Trace（查询追踪）**

每次查询请求生成唯一的 `trace_id`，记录从 Query 输入到 Response 输出的全过程：

**基础信息**：
- `trace_id`：请求唯一标识
- `trace_type`：`"query"`
- `timestamp`：请求时间戳
- `user_query`：用户原始查询
- `collection`：检索的知识库集合

**各阶段详情 (Stages)**：

| 阶段 | 记录内容 |
|-----|---------|
| **Query Processing** | 原始 Query、改写后 Query（若有）、提取的关键词、method、耗时 |
| **Dense Retrieval** | 返回的 Top-N 候选及相似度分数、provider、耗时 |
| **Sparse Retrieval** | 返回的 Top-N 候选及 BM25 分数、method、耗时 |
| **Fusion** | 融合后的统一排名、algorithm、耗时 |
| **Rerank** | 重排后的最终排名及分数、backend、是否触发 Fallback、耗时 |

**汇总指标**：
- `total_latency`：端到端总耗时
- `top_k_results`：最终返回的 Top-K 文档 ID
- `error`：异常信息（若有）

**评估指标 (Evaluation Metrics)**：
- `context_relevance`：召回文档与 Query 的相关性分数
- `answer_faithfulness`：生成答案与召回文档的一致性分数（若有生成环节）

**B. Ingestion Trace（摄取追踪）**

每次文档摄取生成唯一的 `trace_id`，记录从文件加载到存储完成的全过程：

**基础信息**：
- `trace_id`：摄取唯一标识
- `trace_type`：`"ingestion"`
- `timestamp`：摄取开始时间
- `source_path`：源文件路径
- `collection`：目标集合名称

**各阶段详情 (Stages)**：

| 阶段 | 记录内容 |
|-----|---------|
| **Load** | 文件大小、解析器（method: markitdown）、提取的图片数、耗时 |
| **Split** | splitter 类型（method）、产出 chunk 数、平均 chunk 长度、耗时 |
| **Transform** | 各 transform 名称与处理详情（refined/enriched/captioned 数量）、LLM provider、耗时 |
| **Embed** | embedding provider、batch 数、向量维度、dense + sparse 编码耗时 |
| **Upsert** | 存储后端（method: chroma）、upsert 数量、BM25 索引更新、图片存储、耗时 |

**汇总指标**：
- `total_latency`：端到端总耗时
- `total_chunks`：最终存储的 chunk 数量
- `total_images`：处理的图片数量
- `skipped`：跳过的文件/chunk 数（已存在、未变更等）
- `error`：异常信息（若有）


#### 3.4.3 技术方案：结构化日志 + 本地 Web Dashboard

本项目采用 **"结构化日志 + 本地 Web Dashboard"** 作为可观测性的实现方案。

**选型理由**：
- **零外部依赖**：不依赖 LangSmith、LangFuse 等第三方平台，无需网络连接与账号注册，完全本地化运行。
- **轻量易部署**：仅需 Python 标准库 + 一个轻量 Web 框架（如 Streamlit），`pip install` 即可使用，无需 Docker 或数据库服务。
- **学习成本低**：结构化日志是通用技能，调试时可直接用 `jq`、`grep` 等命令行工具查询；Dashboard 代码简单直观，便于理解与二次开发。
- **契合项目定位**：本项目面向本地 MCP Server 场景，单用户、单机运行，无需分布式追踪或多租户隔离等企业级能力。

**实现架构**：

```
RAG Pipeline
    │
    ▼
Trace Collector (装饰器/回调)
    │
    ▼
JSON Lines 日志文件 (logs/traces.jsonl)
    │
    ▼
本地 Web Dashboard (Streamlit)
    │
    ▼
按 trace_id 查看各阶段详情与性能指标
```

**核心组件**：
- **结构化日志层**：基于 Python `logging` + JSON Formatter，将每次请求的 Trace 数据以 JSON Lines 格式追加写入本地文件。每行一条完整的请求记录，包含 `trace_id`、各阶段详情与耗时。
- **本地 Web Dashboard**：基于 Streamlit 构建的轻量级 Web UI，读取日志文件并提供交互式可视化。核心功能是按 `trace_id` 检索并展示单次请求的完整追踪链路。

#### 3.4.4 追踪机制实现

为确保各 RAG 阶段（可替换、可自定义）都能输出统一格式的追踪日志，系统采用 **TraceContext（追踪上下文）** 作为核心机制。

**工作原理**：

1. **请求开始**：Pipeline 入口创建一个 `TraceContext` 实例，生成唯一 `trace_id`，记录请求基础信息（Query、Collection 等）。

2. **阶段记录**：`TraceContext` 提供 `record_stage()` 方法，各阶段执行完毕后调用该方法，传入阶段名称、耗时、输入输出等数据。

3. **请求结束**：调用 `trace.finish()`，`TraceContext` 将收集的完整数据序列化为 JSON，追加写入日志文件。

**与可插拔组件的配合**：
- 各阶段组件（Retriever、Reranker 等）的接口约定中包含 `TraceContext` 参数。
- 组件实现者在执行核心逻辑后，调用 `trace.record_stage()` 记录本阶段的关键信息。
- 这是**显式调用**模式：不强制、不会因未调用而报错，但依赖开发者主动记录。好处是代码透明，开发者清楚知道哪些数据被记录；代价是需要开发者自觉遵守约定。

**阶段划分原则**：
- **Stage 是固定的通用大类**：`retrieval`（检索）、`rerank`（重排）、`generation`（生成）等，不随具体实现方案变化。
- **具体实现是阶段内部的细节**：在 `record_stage()` 中通过 `method` 字段记录采用的具体方法（如 `bm25`、`hybrid`），通过 `details` 字段记录方法相关的细节数据。
- 这样无论底层方案怎么替换，阶段结构保持稳定，Dashboard 展示逻辑无需调整。

#### 3.4.5 Dashboard 功能设计（六页面架构）

Dashboard 基于 Streamlit 构建多页面应用（`st.navigation`），提供六大功能页面：

**页面 1：系统总览 (Overview)**
- **组件配置卡片**：读取 `Settings`，展示当前可插拔组件的配置状态：
    - LLM：provider + model（如 `azure / gpt-4o`）
    - Embedding：provider + model + 维度
    - Splitter：类型 + chunk_size + overlap
    - Reranker：backend + model（或 None）
    - Evaluator：已启用的 backends 列表
- **数据资产统计**：调用 `DocumentManager.get_collection_stats()` 展示各集合的文档数、chunk 数、图片数。
- **系统健康指标**：最近一次 Ingestion/Query trace 的时间与耗时。

**页面 2：数据浏览器 (Data Browser)**
- **文档列表视图**：展示已摄入的文档（source_path、集合、chunk 数、摄入时间），支持按集合筛选与关键词搜索。
- **Chunk 详情视图**：点击文档展开其所有 chunk，每个 chunk 显示：
    - 原文内容（可折叠长文本）
    - Metadata 各字段（title、summary、tags、page、image_refs 等）
    - 关联图片预览（从 ImageStorage 读取并展示缩略图）
- **数据来源**：通过 `ChromaStore.get_all()` 或 `get_by_metadata()` 读取 chunk 数据。

**页面 3：Ingestion 管理 (Ingestion Manager)**
- **文件选择与摄取触发**：
    - 文件上传组件（`st.file_uploader`）或目录路径输入
    - 选择目标集合（下拉选择或新建）
    - 点击"开始摄取"按钮触发 `IngestionPipeline.run()`
    - 利用 `on_progress` 回调驱动 Streamlit 进度条（`st.progress`），实时显示当前阶段与处理进度
- **文档删除**：
    - 在文档列表中提供"删除"按钮
    - 调用 `DocumentManager.delete_document()` 协调跨存储删除
    - 删除完成后刷新列表
- **注意**：Pipeline 执行为同步阻塞操作，Streamlit 的 rerun 机制天然支持（进度条在同一 request 中更新）。

**页面 4：Ingestion 追踪 (Ingestion Traces)**
- **摄取历史列表**：按时间倒序展示 `trace_type == "ingestion"` 的历史记录，显示文件名、集合、总耗时、状态（成功/失败）。
- **单次摄取详情**：
    - **阶段耗时瀑布图**：横向条形图展示 load/split/transform/embed/upsert 各阶段时间分布。
    - **处理统计**：chunk 数、图片数、跳过数、失败数。
    - **各阶段详情展开**：点击查看 method/provider、输入输出样本。

**页面 5：Query 追踪 (Query Traces)**
- **查询历史列表**：按时间倒序展示 `trace_type == "query"` 的历史记录，支持按 Query 关键词筛选。
- **单次查询详情**：
    - **耗时瀑布图**：展示 query_processing/dense/sparse/fusion/rerank 各阶段时间分布。
    - **Dense vs Sparse 对比**：并列展示两路召回结果的 Top-N 文档 ID 与分数。
    - **Rerank 前后对比**：展示融合排名与精排后排名的变化（排名跃升/下降标记）。
    - **最终结果表**：展示 Top-K 候选文档的标题、分数、来源。

**页面 6：评估面板 (Evaluation Panel)**
- **评估运行**：选择评估后端（Ragas / Custom / All）与 golden test set，点击运行。
- **指标展示**：以表格和图表展示 hit_rate、mrr、faithfulness 等指标。
- **历史趋势**：对比不同时间的评估结果，观察策略调整的效果。
- **注意**：评估面板在 Phase H 实现，Phase G 完成后该页面显示"评估模块尚未启用"的占位提示。

**Dashboard 技术架构**：

```
src/observability/dashboard/
├── app.py                    # Streamlit 入口，页面导航注册
├── pages/
│   ├── overview.py           # 页面 1：系统总览
│   ├── data_browser.py       # 页面 2：数据浏览器
│   ├── ingestion_manager.py  # 页面 3：Ingestion 管理
│   ├── ingestion_traces.py   # 页面 4：Ingestion 追踪
│   ├── query_traces.py       # 页面 5：Query 追踪
│   └── evaluation_panel.py   # 页面 6：评估面板
└── services/
    ├── trace_service.py      # Trace 数据读取服务（解析 traces.jsonl）
    ├── data_service.py       # 数据浏览服务（封装 ChromaStore/ImageStorage 读取）
    └── config_service.py     # 配置读取服务（封装 Settings 读取与展示）
```

**Dashboard 与 Trace 的数据关系**：
- Dashboard 页面 4/5 读取 `logs/traces.jsonl`（通过 `TraceService`），按 `trace_type` 分类展示。
- Dashboard 页面 1/2/3 直接读取存储层（通过 `DataService` 封装 ChromaStore/ImageStorage/FileIntegrity），不依赖 Trace。
- 所有页面基于 Trace 中 `method`/`provider` 字段动态渲染标签，更换组件后自动适配。


#### 3.4.6 配置示例

```yaml
observability:
  enabled: true
  
  # 日志配置
  logging:
    log_file: logs/traces.jsonl  # JSON Lines 格式日志文件
    log_level: INFO  # DEBUG | INFO | WARNING
  
  # 追踪粒度控制
  detail_level: standard  # minimal | standard | verbose

# Dashboard 管理平台配置
dashboard:
  enabled: true
  port: 8501                     # Streamlit 服务端口
  traces_dir: ./logs             # Trace 日志文件目录
  auto_refresh: true             # 是否自动刷新（轮询新 trace）
  refresh_interval: 5            # 自动刷新间隔（秒）
```


### 3.5 多模态图片处理设计 (Multimodal Image Processing Design)

**目标：** 设计一套完整的图片处理方案，使 RAG 系统能够理解、索引并检索文档中的图片内容，实现"用自然语言搜索图片"的能力，同时保持架构的简洁性与可扩展性。

#### 3.5.1 设计理念与策略选型

多模态 RAG 的核心挑战在于：**如何让纯文本的检索系统"看懂"图片**。业界主要有两种技术路线：

| 策略 | 核心思路 | 优势 | 劣势 |
|-----|---------|------|------|
| **Image-to-Text (图转文)** | 利用 Vision LLM 将图片转化为文本描述，复用纯文本 RAG 链路 | 架构统一、实现简单、成本可控 | 描述质量依赖 LLM 能力，可能丢失视觉细节 |
| **Multi-Embedding (多模态向量)** | 使用 CLIP 等模型将图文统一映射到同一向量空间 | 保留原始视觉特征，支持图搜图 | 需引入额外向量库，架构复杂度高 |

**本项目选型：Image-to-Text（图转文）策略**

选型理由：
- **架构统一**：无需引入 CLIP 等多模态 Embedding 模型，无需维护独立的图像向量库，完全复用现有的文本 RAG 链路（Ingestion → Hybrid Search → Rerank）。
- **语义对齐**：通过 LLM 将图片的视觉信息转化为自然语言描述，天然与用户的文本查询在同一语义空间，检索效果可预期。
- **成本可控**：仅在数据摄取阶段一次性调用 Vision LLM，检索阶段无额外成本。
- **渐进增强**：未来如需支持"图搜图"等高级能力，可在此基础上叠加 CLIP Embedding，无需重构核心链路。

#### 3.5.2 图片处理全流程设计

图片处理贯穿 Ingestion Pipeline 的多个阶段，整体流程如下：

```
原始文档 (PDF/PPT/Markdown)
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  Loader 阶段：图片提取与引用收集                           │
│  - 解析文档，识别并提取嵌入的图片资源                        │
│  - 为每张图片生成唯一标识 (image_id)                       │
│  - 在文档文本中插入图片占位符/引用标记                       │
│  - 输出：Document (text + metadata.images[])             │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  Splitter 阶段：保持图文关联                               │
│  - 切分时保留图片引用标记在对应 Chunk 中                     │
│  - 确保图片与其上下文段落保持关联                            │
│  - 输出：Chunks (各自携带关联的 image_refs)                │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  Transform 阶段：图片理解与描述生成                         │
│  - 调用 Vision LLM 对每张图片生成结构化描述                  │
│  - 将描述文本注入到关联 Chunk 的正文或 Metadata 中           │
│  - 输出：Enriched Chunks (含图片语义信息)                  │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  Storage 阶段：双轨存储                                    │
│  - 向量库：存储增强后的 Chunk (含图片描述) 用于检索           │
│  - 文件系统/Blob：存储原始图片文件用于返回展示                │
└─────────────────────────────────────────────────────────┘
```

#### 3.5.3 各阶段技术要点

**1. Loader 阶段：图片提取与引用收集**

- **提取策略**：
  - 解析文档时识别嵌入的图片资源（PDF 中的 XObject、PPT 中的媒体文件、Markdown 中的 `![]()` 引用）。
  - 为每张图片生成全局唯一的 `image_id`（建议格式：`{doc_hash}_{page}_{seq}`）。
  - 将图片二进制数据提取并暂存，记录其在原文档中的位置信息。

- **引用标记**：
  - 在转换后的 Markdown 文本中，于图片原始位置插入占位符（如 `[IMAGE: {image_id}]`）。
  - 在 Document 的 Metadata 中维护 `images` 列表，记录每张图片的 `image_id`、原始路径、页码、尺寸等基础信息。

- **存储原始图片**：
  - 将提取的图片保存至本地文件系统的约定目录（如 `data/images/{collection}/{image_id}.png`）。
  - 仅保存需要的图片格式（推荐统一转换为 PNG/JPEG），控制存储体积。

**2. Splitter 阶段：保持图文关联**

- **关联保持原则**：
  - 图片引用标记应与其说明性文字（Caption、前后段落）尽量保持在同一 Chunk 中。
  - 若图片出现在章节开头或结尾，切分时应将其归入语义上最相关的 Chunk。

- **Chunk Metadata 扩展**：
  - 每个 Chunk 的 Metadata 中增加 `image_refs: List[image_id]` 字段，记录该 Chunk 关联的图片列表。
  - 此字段用于后续 Transform 阶段定位需要处理的图片，以及检索命中后定位需要返回的图片。

**3. Transform 阶段：图片理解与描述生成**

这是多模态处理的核心环节，负责将视觉信息转化为可检索的文本语义。

- **Vision LLM 选型**：

| 模型 | 提供商 | 特点 | 适用场景 | 推荐指数 |
|-----|--------|------|---------|---------|
| **GPT-4o** | OpenAI / Azure | 理解能力强，支持复杂图表解读，英文文档表现优异 | 高质量需求、复杂业务文档、国际化场景 | ⭐⭐⭐⭐⭐ |
| **Qwen-VL-Max** | 阿里云 (DashScope) | 中文理解能力出色，性价比高，对中文图表/文档支持好 | 中文文档、国内部署、成本敏感场景 | ⭐⭐⭐⭐⭐ |
| **Qwen-VL-Plus** | 阿里云 (DashScope) | 速度更快，成本更低，适合大批量处理 | 大批量中文文档、快速迭代场景 | ⭐⭐⭐⭐ |
| **Claude 3.5 Sonnet** | Anthropic | 多模态原生支持，长上下文 | 需要结合大段文字理解图片 | ⭐⭐⭐⭐ |
| **Gemini Pro Vision** | Google | 成本较低，速度较快 | 大批量处理、成本敏感场景 | ⭐⭐⭐ |
| **GLM-4V** | 智谱 AI (ZhipuAI) | 国内老牌，稳定性好，中文支持佳 | 国内部署备选、企业级应用 | ⭐⭐⭐⭐ |

**双模型选型策略（推荐）**：

本项目采用**国内 + 国外双模型**方案，通过配置切换，兼顾不同部署环境和文档类型：

| 部署环境 | 主选模型 | 备选模型 | 说明 |
|---------|---------|---------|------|
| **国际化 / Azure 环境** | GPT-4o (Azure) | Qwen-VL-Max | 英文文档优先用 GPT-4o，中文文档可切换 Qwen-VL |
| **国内部署 / 纯中文场景** | Qwen-VL-Max | GPT-4o | 中文图表理解用 Qwen-VL，特殊需求可切换 GPT-4o |
| **成本敏感 / 大批量** | Qwen-VL-Plus | Gemini Pro Vision | 牺牲部分质量换取速度和成本 |

**选型理由**：

1. **GPT-4o (国外首选)**：
   - 视觉理解能力业界领先，复杂图表解读准确率高
   - Azure 部署可满足企业合规要求
   - 英文技术文档理解效果最佳

2. **Qwen-VL-Max (国内首选)**：
   - 中文场景下表现与 GPT-4o 接近，部分中文图表任务甚至更优
   - 通过阿里云 DashScope API 调用，国内访问稳定、延迟低
   - 价格约为 GPT-4o 的 1/3 ~ 1/5，性价比极高
   - 原生支持中文 OCR，对中文截图、表格识别更准确

- **描述生成策略**：
  - **结构化 Prompt**：设计专用的图片理解 Prompt，引导 LLM 输出结构化描述，而非自由发挥。
  - **上下文感知**：将图片的前后文本段落一并传入 Vision LLM，帮助其理解图片在文档中的语境与作用。
  - **分类型处理**：针对不同类型的图片采用差异化的理解策略：

| 图片类型 | 理解重点 | Prompt 引导方向 |
|---------|---------|----------------|
| **流程图/架构图** | 节点、连接关系、流程逻辑 | "描述这张图的结构和流程步骤" |
| **数据图表** | 数据趋势、关键数值、对比关系 | "提取图表中的关键数据和结论" |
| **截图/UI** | 界面元素、操作指引、状态信息 | "描述截图中的界面内容和关键信息" |
| **照片/插图** | 主体对象、场景、视觉特征 | "描述图片中的主要内容" |

- **描述注入方式**：
  - **推荐：注入正文**：将生成的描述直接替换或追加到 Chunk 正文中的图片占位符位置，格式如 `[图片描述: {caption}]`。这样描述会被 Embedding 覆盖，可被直接检索。
  - **备选：注入 Metadata**：将描述存入 `chunk.metadata.image_captions` 字段。需确保检索时该字段也被索引。

- **幂等与增量处理**：
  - 为每张图片的描述计算内容哈希，存入 `processing_cache` 表。
  - 重复处理时，若图片内容未变且 Prompt 版本一致，直接复用缓存的描述，避免重复调用 Vision LLM。

**4. Storage 阶段：双轨存储**

- **向量库存储（用于检索）**：
  - 存储增强后的 Chunk，其正文已包含图片描述，Metadata 包含 `image_refs` 列表。
  - 检索时通过文本相似度即可命中包含相关图片描述的 Chunk。

- **原始图片存储（用于返回）**：
  - 图片文件存储于本地文件系统，路径记录在独立的 `images` 索引表中。
  - 索引表字段：`image_id`, `file_path`, `source_doc`, `page`, `width`, `height`, `mime_type`。
  - 检索命中后，根据 Chunk 的 `image_refs` 查询索引表，获取图片文件路径用于返回。

#### 3.5.4 检索与返回流程

当用户查询命中包含图片的 Chunk 时，系统需要将图片与文本一并返回：

```
用户查询: "系统架构是什么样的？"
    │
    ▼
Hybrid Search 命中 Chunk（正文含 "[图片描述: 系统采用三层架构...]"）
    │
    ▼
从 Chunk.metadata.image_refs 获取关联的 image_id 列表
    │
    ▼
查询 images 索引表，获取图片文件路径
    │
    ▼
读取图片文件，编码为 Base64
    │
    ▼
构造 MCP 响应，包含 TextContent + ImageContent
```

**MCP 响应格式**：

```json
{
  "content": [
    {
      "type": "text",
      "text": "根据文档，系统架构如下：...

[1] 来源: architecture.pdf, 第5页"
    },
    {
      "type": "image",
      "data": "<base64-encoded-image>",
      "mimeType": "image/png"
    }
  ]
}
```

#### 3.5.5 质量保障与边界处理

- **描述质量检测**：
  - 对生成的描述进行基础质量检查（长度、是否包含关键信息）。
  - 若描述过短或 LLM 返回"无法识别"，标记该图片为 `low_quality`，可选择人工复核或跳过索引。

- **大尺寸/特殊图片处理**：
  - 超大图片在传入 Vision LLM 前进行压缩（保持宽高比，限制最大边长）。
  - 对于纯装饰性图片（如分隔线、背景图），可通过尺寸或位置规则过滤，不进入描述生成流程。

- **批量处理优化**：
  - 图片描述生成支持批量异步调用，提高吞吐量。
  - 单个文档处理失败时，记录失败的图片 ID，不影响其他图片的处理进度。

- **降级策略**：
  - 当 Vision LLM 不可用时，系统回退到"仅保留图片占位符"模式，图片不参与检索但不阻塞 Ingestion 流程。
  - 在 Chunk 中标记 `has_unprocessed_images: true`，后续可增量补充描述。

## 4. 测试方案

### 4.1 设计理念：测试驱动开发 (TDD)

本项目采用**测试驱动开发（Test-Driven Development）**作为核心开发范式，确保每个组件在实现前就已明确其预期行为，通过自动化测试持续验证系统质量。

**核心原则**：
- **早测试、常测试**：每个功能模块实现的同时就编写对应的单元测试，而非事后补测。
- **测试即文档**：测试用例本身就是最准确的行为规范，新加入的开发者可通过阅读测试快速理解各模块功能。
- **快速反馈循环**：单元测试应在秒级完成，支持开发者高频执行，立即发现引入的问题。
- **分层测试金字塔**：大量快速的单元测试作为基座，少量关键路径的集成测试作为保障，极少数端到端测试验证完整流程。

```
        /\
       /E2E\         <- 少量，验证关键业务流程
      /------\
     /Integration\   <- 中量，验证模块协作
    /------------\
   /  Unit Tests  \  <- 大量，验证单个函数/类
  /________________\
```

### 4.2 测试分层策略

#### 4.2.1 单元测试 (Unit Tests)

**目标**：验证每个独立组件的内部逻辑正确性，隔离外部依赖。

**覆盖范围**：

| 模块 | 测试重点 | 典型测试用例 |
|-----|---------|------------|
| **Loader (文档解析器)** | 格式解析、元数据提取、图片引用收集 | - 测试解析单页/多页 PDF<br>- 验证 Markdown 标题层级提取<br>- 检查图片占位符插入位置 |
| **Splitter (切分器)** | 切分边界、上下文保留、元数据传递 | - 验证按标题切分不破坏段落<br>- 测试超长文本的递归切分<br>- 检查 Chunk 的 `source` 字段正确性 |
| **Transform (增强器)** | 图片描述生成、元数据注入 | - Mock Vision LLM，验证描述注入逻辑<br>- 测试无图片时的降级行为<br>- 验证幂等性（重复处理相同输入） |
| **Embedding (向量化)** | 批处理、差量计算、向量维度 | - 验证相同文本生成相同向量<br>- 测试批量请求的拆分与合并<br>- 检查缓存命中逻辑 |
| **BM25 (稀疏编码)** | 关键词提取、权重计算 | - 验证停用词过滤<br>- 测试 IDF 计算准确性<br>- 检查稀疏向量格式 |
| **Retrieval (检索器)** | 召回精度、融合算法 | - 测试纯 Dense/Sparse/Hybrid 三种模式<br>- 验证 RRF 融合分数计算<br>- 检查 Top-K 结果排序 |
| **Reranker (重排器)** | 分数归一化、降级回退 | - Mock Cross-Encoder，验证分数重排<br>- 测试超时后的 Fallback 逻辑<br>- 验证空候选集处理 |

**技术选型**：
- **测试框架**：`pytest`（Python 标准选择，支持参数化测试、Fixture 机制）
- **Mock 工具**：`unittest.mock` / `pytest-mock`（隔离外部依赖，如 LLM API）
- **断言增强**：`pytest-check`（支持多断言不中断执行）

#### 4.2.2 集成测试 (Integration Tests)

**目标**：验证多个组件协作时的数据流转与接口兼容性。

**覆盖范围**：

| 测试场景 | 验证要点 | 测试策略 |
|---------|---------|---------|
| **Ingestion Pipeline** | Loader → Splitter → Transform → Storage 的完整流程 | - 使用真实的测试 PDF 文件<br>- 验证最终存入向量库的数据完整性<br>- 检查中间产物（如临时图片文件）是否正确清理 |
| **Hybrid Search** | Dense + Sparse 召回的融合结果 | - 准备已知答案的查询-文档对<br>- 验证融合后的 Top-1 是否命中正确文档<br>- 测试极端情况（某一路无结果） |
| **Rerank Pipeline** | 召回 → 过滤 → 重排的组合 | - 验证 Metadata 过滤后的候选集正确性<br>- 检查 Reranker 是否改变了 Top-1 结果<br>- 测试 Reranker 失败时的回退 |
| **MCP Server** | 工具调用的端到端流程 | - 模拟 MCP Client 发送 JSON-RPC 请求<br>- 验证返回的 `content` 格式符合协议<br>- 测试错误处理（如查询语法错误） |

**技术选型**：
- **数据隔离**：每个测试使用独立的临时数据库/向量库（`pytest-tempdir`）
- **异步测试**：`pytest-asyncio`（若 MCP Server 采用异步实现）
- **契约测试**：定义各模块间的 Schema，确保接口不漂移

#### 4.2.3 端到端测试 (End-to-End Tests)

**目标**：模拟真实用户操作，验证完整业务流程的可用性。

**核心场景**：

**场景 1：数据准备（离线摄取）**
- **测试目标**：验证文档摄取流程的完整性与正确性
- **测试步骤**：
  - 准备测试文档（PDF 文件，包含文本、图片、表格等多种元素）
  - 执行离线摄取脚本，将文档导入知识库
  - 验证摄取结果：检查生成的 Chunk 数量、元数据完整性、图片描述生成
  - 验证存储状态：确认向量库和 BM25 索引正确创建
  - 验证幂等性：重复摄取同一文档，确保不产生重复数据
- **验证要点**：
  - Chunk 的切分质量（语义完整性、上下文保留）
  - 元数据字段完整性（source、page、title、tags 等）
  - 图片处理结果（Caption 生成、Base64 编码存储）
  - 向量与稀疏索引的正确性

**场景 2：召回测试**
- **测试目标**：验证检索系统的召回精度与排序质量
- **测试步骤**：
  - 基于已摄取的知识库，准备一组测试查询（包含不同难度与类型）
  - 执行混合检索（Dense + Sparse + Rerank）
  - 验证召回结果：检查 Top-K 文档是否包含预期来源
  - 对比不同检索策略的效果（纯 Dense、纯 Sparse、Hybrid）
  - 验证 Rerank 的影响：对比重排前后的结果变化
- **验证要点**：
  - Hit Rate@K：Top-K 结果命中率是否达标
  - 排序质量：正确答案是否排在前列（MRR、NDCG）
  - 边界情况处理：空查询、无结果查询、超长查询
  - 多模态召回：包含图片的文档是否能通过文本查询召回

**场景 3：MCP Client 功能测试**
- **测试目标**：验证 MCP Server 与 Client（如 GitHub Copilot）的协议兼容性与功能完整性
- **测试步骤**：
  - 启动 MCP Server（Stdio Transport 模式）
  - 模拟 MCP Client 发送各类 JSON-RPC 请求
  - 测试工具调用：`query_knowledge_hub`、`list_collections` 等
  - 验证返回格式：符合 MCP 协议规范（content 数组、structuredContent）
  - 测试引用透明性：返回结果包含完整的 Citation 信息
  - 测试多模态返回：包含图片的响应正确编码为 Base64
- **验证要点**：
  - 协议合规性：JSON-RPC 2.0 格式、错误码映射
  - 工具注册：`tools/list` 返回所有可用工具及其 Schema
  - 响应格式：TextContent 与 ImageContent 的正确组合
  - 错误处理：无效参数、超时、服务不可用等异常场景
  - 性能指标：单次请求的端到端延迟（含检索、重排、格式化）

**测试工具**：
- **BDD 框架**：`behave` 或 `pytest-bdd`（以 Gherkin 语法描述场景）
- **环境准备**：
  - 临时测试向量库（独立于生产数据）
  - 预置的标准测试文档集
  - 本地 MCP Server 进程（Stdio Transport）

### 4.3 RAG 质量评估测试

**目标**：验证已设计的评估体系（见 3.3.4 评估框架抽象）是否正确实现，并能有效评估 RAG 系统的召回与生成质量。

**测试要点**：

1. **黄金测试集准备**
   - 构建标准的"问题-答案-来源文档"测试集（JSON 格式）
   - 初期人工标注核心场景，后期持续积累坏 Case

2. **评估框架实现验证**
   - 验证 Ragas/DeepEval 等评估框架的正确集成
   - 确认评估接口能输出标准化的指标字典
   - 测试多评估器并行执行与结果汇总

3. **关键指标达标验证**
   - 检索指标：Hit Rate@K ≥ 90%、MRR ≥ 0.8、NDCG@K ≥ 0.85
   - 生成指标：Faithfulness ≥ 0.9、Answer Relevancy ≥ 0.85
   - 定期运行评估，监控指标是否回归

**说明**：本节重点是验证评估体系的工程实现，而非重新设计评估方法（评估方法的设计见第 3 章技术选型）。

### 4.4 性能与压力测试（可选）

> **说明**：本项目定位为本地 MCP Server，单用户开发环境，采用 Stdio Transport 通信方式。性能与压力测试在当前阶段**不是必需的**，此处列出主要用于：
> 1. **架构完整性**：展示完整的工程化测试体系，体现系统设计的专业性
> 2. **未来扩展性**：若后续需要云端部署或多用户支持，可直接参考此方案
> 3. **性能基准建立**：通过基础性能测试了解系统瓶颈，为优化提供数据支撑

**可选测试场景**：

| 测试类型 | 验证点 | 工具 | 优先级 |
|---------|-------|------|-------|
| **延迟测试** | 单次查询的 P50/P95/P99 延迟 | `pytest-benchmark` | 中（可帮助识别慢查询） |
| **吞吐量测试** | 并发查询时的 QPS 上限 | `locust` | 低（本地单用户无需求） |
| **内存泄漏检测** | 长时间运行后的内存占用 | `memory_profiler` | 低（短期运行无影响） |
| **向量库性能** | 不同数据规模下的查询速度 | 自定义 Benchmark | 中（验证扩展性） |

### 4.5 测试工具链与 CI/CD 集成

**本地开发工作流**：
- **快速验证**：仅运行单元测试，秒级反馈
- **完整验证**：单元测试 + 集成测试，生成覆盖率报告
- **质量评估**：定期执行 RAG 质量测试，监控指标变化

**CI/CD Pipeline 设计**（可选）：
> **说明**：本地项目不强制要求 CI/CD，但配置自动化测试流程有助于代码质量保障与持续集成实践。

- **单元测试阶段**：每次提交自动触发，验证基础功能，生成覆盖率报告
- **集成测试阶段**：单元测试通过后执行，验证模块协作
- **质量评估阶段**：PR 触发，运行完整的 RAG 质量测试，发布评估报告

**测试覆盖率目标**：
- **单元测试**：核心逻辑覆盖率 ≥ 80%
- **集成测试**：关键路径覆盖率 100%（如 Ingestion、Hybrid Search）
- **E2E 测试**：核心用户场景覆盖率 100%（至少 3 个关键流程）


## 5. 系统架构与模块设计

### 5.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                     MCP Clients (外部调用层)                                  │
│                                                                                             │
│    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐                        │
│    │  GitHub Copilot │    │  Claude Desktop │    │  其他 MCP Agent │                        │
│    └────────┬────────┘    └────────┬────────┘    └────────┬────────┘                        │
│             │                      │                      │                                 │
│             └──────────────────────┼──────────────────────┘                                 │
│                                    │  JSON-RPC 2.0 (Stdio Transport)                       │
└────────────────────────────────────┼────────────────────────────────────────────────────────┘
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   MCP Server 层 (接口层)                                     │
│                                                                                             │
│    ┌─────────────────────────────────────────────────────────────────────────────────┐      │
│    │                              MCP Protocol Handler                               │      │
│    │                    (tools/list, tools/call, resources/*)                        │      │
│    └─────────────────────────────────────────────────────────────────────────────────┘      │
│                                           │                                                 │
│    ┌──────────────────────┬───────────────┼───────────────┬──────────────────────┐          │
│    ▼                      ▼               ▼               ▼                      ▼          │
│ ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│ │query_knowledge│ │list_collections│ │get_document_ │  │search_by_    │  │  其他扩展    │    │
│ │    _hub      │  │              │  │   summary    │  │  keyword     │  │   工具...    │    │
│ └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└────────────────────────────────────────┬────────────────────────────────────────────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   Core 层 (核心业务逻辑)                                     │
│                                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐    │
│  │                            Query Engine (查询引擎)                                   │    │
│  │  ┌─────────────────────────────────────────────────────────────────────────────┐    │    │
│  │  │                         Query Processor (查询预处理)                         │    │    │
│  │  │            关键词提取 | 查询扩展 (同义词/别名) | Metadata 解析               │    │    │
│  │  └─────────────────────────────────────────────────────────────────────────────┘    │    │
│  │                                       │                                             │    │
│  │  ┌────────────────────────────────────┼────────────────────────────────────┐        │    │
│  │  │                     Hybrid Search Engine (混合检索引擎)                  │        │    │
│  │  │                                    │                                    │        │    │
│  │  │    ┌───────────────────┐    ┌──────┴──────┐    ┌───────────────────┐    │        │    │
│  │  │    │   Dense Route     │    │   Fusion    │    │   Sparse Route    │    │        │    │
│  │  │    │ (Embedding 语义)  │◄───┤    (RRF)    ├───►│   (BM25 关键词)   │    │        │    │
│  │  │    └───────────────────┘    └─────────────┘    └───────────────────┘    │        │    │
│  │  └─────────────────────────────────────────────────────────────────────────┘        │    │
│  │                                       │                                             │    │
│  │  ┌─────────────────────────────────────────────────────────────────────────────┐    │    │
│  │  │                        Reranker (重排序模块) [可选]                          │    │    │
│  │  │          None (关闭) | Cross-Encoder (本地模型) | LLM Rerank               │    │    │
│  │  └─────────────────────────────────────────────────────────────────────────────┘    │    │
│  │                                       │                                             │    │
│  │  ┌─────────────────────────────────────────────────────────────────────────────┐    │    │
│  │  │                      Response Builder (响应构建器)                           │    │    │
│  │  │            引用生成 (Citation) | 多模态内容组装 (Text + Image)               │    │    │
│  │  └─────────────────────────────────────────────────────────────────────────────┘    │    │
│  └─────────────────────────────────────────────────────────────────────────────────────┘    │
│                                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐    │
│  │                          Trace Collector (追踪收集器)                                │    │
│  │                   trace_id 生成 | 各阶段耗时记录 | JSON Lines 输出                  │    │
│  └─────────────────────────────────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────┬────────────────────────────────────────────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   Storage 层 (存储层)                                        │
│                                                                                             │
│    ┌─────────────────────────────────────────────────────────────────────────────────┐      │
│    │                             Vector Store (向量存储)                              │      │
│    │                                                                                 │      │
│    │     ┌─────────────────────────────────────────────────────────────────────┐     │      │
│    │     │                         Chroma DB                                   │     │      │
│    │     │    Dense Vector | Sparse Vector | Chunk Content | Metadata          │     │      │
│    │     └─────────────────────────────────────────────────────────────────────┘     │      │
│    └─────────────────────────────────────────────────────────────────────────────────┘      │
│                                                                                             │
│    ┌──────────────────────────────────┐    ┌──────────────────────────────────┐             │
│    │       BM25 Index (稀疏索引)       │    │       Image Store (图片存储)     │             │
│    │        倒排索引 | IDF 统计        │    │    本地文件系统 | Base64 编码     │             │
│    └──────────────────────────────────┘    └──────────────────────────────────┘             │
│                                                                                             │
│    ┌──────────────────────────────────┐    ┌──────────────────────────────────┐             │
│    │     Trace Logs (追踪日志)         │    │   Processing Cache (处理缓存)    │             │
│    │     JSON Lines 格式文件           │    │   文件哈希 | Chunk 哈希 | 状态   │             │
│    └──────────────────────────────────┘    └──────────────────────────────────┘             │
└─────────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                              Ingestion Pipeline (离线数据摄取)                               │
│                                                                                             │
│    ┌────────────┐    ┌────────────┐    ┌────────────┐    ┌────────────┐    ┌────────────┐   │
│    │   Loader   │───►│  Splitter  │───►│ Transform  │───►│  Embedding │───►│   Upsert   │   │
│    │ (文档解析) │    │  (切分器)  │    │ (增强处理) │    │  (向量化)  │    │  (存储)    │   │
│    └────────────┘    └────────────┘    └────────────┘    └────────────┘    └────────────┘   │
│         │                  │                  │                  │                │         │
│         ▼                  ▼                  ▼                  ▼                ▼         │
│    ┌────────────┐    ┌────────────┐    ┌────────────┐    ┌────────────┐    ┌────────────┐   │
│    │MarkItDown │    │Recursive   │    │LLM重写     │    │Dense:      │    │Chroma      │   │
│    │PDF→MD     │    │Character   │    │Image       │    │OpenAI/BGE  │    │Upsert      │   │
│    │元数据提取 │    │TextSplitter│    │Captioning  │    │Sparse:BM25 │    │幂等写入    │   │
│    └────────────┘    └────────────┘    └────────────┘    └────────────┘    └────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                Libs 层 (可插拔抽象层)                                        │
│                                                                                             │
│    ┌────────────────────────────────────────────────────────────────────────────────┐       │
│    │                            Factory Pattern (工厂模式)                           │       │
│    └────────────────────────────────────────────────────────────────────────────────┘       │
│                                           │                                                 │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐  │
│  │ LLM Client │ │ Embedding  │ │  Splitter  │ │VectorStore │ │  Reranker  │ │ Evaluator  │  │
│  │  Factory   │ │  Factory   │ │  Factory   │ │  Factory   │ │  Factory   │ │  Factory   │  │
│  ├────────────┤ ├────────────┤ ├────────────┤ ├────────────┤ ├────────────┤ ├────────────┤  │
│  │ · Azure    │ │ · OpenAI   │ │ · Recursive│ │ · Chroma   │ │ · None     │ │ · Ragas    │  │
│  │ · OpenAI   │ │ · BGE      │ │ · Semantic │ │ · Qdrant   │ │ · CrossEnc │ │ · DeepEval │  │
│  │ · Ollama   │ │ · Ollama   │ │ · FixedLen │ │ · Pinecone │ │ · LLM      │ │ · Custom   │  │
│  │ · DeepSeek │ │ · ...      │ │ · ...      │ │ · ...      │ │            │ │            │  │
│  │ · Vision✨ │ │            │ │            │ │            │ │            │ │            │  │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘ └────────────┘ └────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                             Observability 层 (可观测性)                                      │
│                                                                                             │
│    ┌──────────────────────────────────────┐    ┌──────────────────────────────────────┐     │
│    │          Trace Context               │    │         Web Dashboard                │     │
│    │   trace_id | stages[] | metrics      │    │        (Streamlit)                   │     │
│    │   record_stage() | finish()          │    │    请求列表 | 耗时瀑布图 | 详情展开   │     │
│    └──────────────────────────────────────┘    └──────────────────────────────────────┘     │
│                                                                                             │
│    ┌──────────────────────────────────────┐    ┌──────────────────────────────────────┐     │
│    │          Evaluation Module           │    │         Structured Logger            │     │
│    │   Hit Rate | MRR | Faithfulness      │    │    JSON Formatter | File Handler     │     │
│    └──────────────────────────────────────┘    └──────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 目录结构

```
smart-knowledge-hub/
│
├── config/                              # 配置文件目录
│   ├── settings.yaml                    # 主配置文件 (LLM/Embedding/VectorStore 配置)
│   └── prompts/                         # Prompt 模板目录
│       ├── image_captioning.txt         # 图片描述生成 Prompt
│       ├── chunk_refinement.txt         # Chunk 重写 Prompt
│       └── rerank.txt                   # LLM Rerank Prompt
│
├── src/                                 # 源代码主目录
│   │
│   ├── mcp_server/                      # MCP Server 层 (接口层)
│   │   ├── __init__.py
│   │   ├── server.py                    # MCP Server 入口 (Stdio Transport)
│   │   ├── protocol_handler.py          # JSON-RPC 协议处理
│   │   └── tools/                       # MCP Tools 定义
│   │       ├── __init__.py
│   │       ├── query_knowledge_hub.py   # 主检索工具
│   │       ├── list_collections.py      # 列出集合工具
│   │       └── get_document_summary.py  # 文档摘要工具
│   │
│   ├── core/                            # Core 层 (核心业务逻辑)
│   │   ├── __init__.py
│   │   ├── settings.py                   # 配置加载与校验 (Settings：load_settings/validate_settings)
│   │   ├── types.py                      # 核心数据类型/契约（Document/Chunk/ChunkRecord），供 ingestion/retrieval/mcp 复用
│   │   │
│   │   ├── query_engine/                # 查询引擎模块
│   │   │   ├── __init__.py
│   │   │   ├── query_processor.py       # 查询预处理 (关键词提取/查询扩展)
│   │   │   ├── hybrid_search.py         # 混合检索引擎 (Dense + Sparse + RRF)
│   │   │   ├── dense_retriever.py       # 稠密向量检索
│   │   │   ├── sparse_retriever.py      # 稀疏检索 (BM25)
│   │   │   ├── fusion.py                # 结果融合 (RRF 算法)
│   │   │   └── reranker.py              # 重排序模块 (None/CrossEncoder/LLM)
│   │   │
│   │   ├── response/                    # 响应构建模块
│   │   │   ├── __init__.py
│   │   │   ├── response_builder.py      # 响应构建器
│   │   │   ├── citation_generator.py    # 引用生成器
│   │   │   └── multimodal_assembler.py  # 多模态内容组装 (Text + Image)
│   │   │
│   │   └── trace/                       # 追踪模块
│   │       ├── __init__.py
│   │       ├── trace_context.py         # 追踪上下文 (trace_id/stages)
│   │       └── trace_collector.py       # 追踪收集器
│   │
│   ├── ingestion/                       # Ingestion Pipeline (离线数据摄取)
│   │   ├── __init__.py
│   │   ├── pipeline.py                  # Pipeline 主流程编排 (支持 on_progress 回调)
│   │   ├── document_manager.py          # 文档生命周期管理 (list/delete/stats)
│   │   │
│   │   ├── chunking/                    # Chunking 模块 (文档切分)
│   │   │   ├── __init__.py
│   │   │   └── document_chunker.py      # Document → Chunks 转换（调用 libs.splitter）
│   │   │
│   │   ├── transform/                   # Transform 模块 (增强处理)
│   │   │   ├── __init__.py
│   │   │   ├── base_transform.py        # Transform 抽象基类
│   │   │   ├── chunk_refiner.py         # Chunk 智能重组/去噪
│   │   │   ├── metadata_enricher.py     # 语义元数据注入 (Title/Summary/Tags)
│   │   │   └── image_captioner.py       # 图片描述生成 (Vision LLM)
│   │   │
│   │   ├── embedding/                   # Embedding 模块 (向量化)
│   │   │   ├── __init__.py
│   │   │   ├── dense_encoder.py         # 稠密向量编码
│   │   │   ├── sparse_encoder.py        # 稀疏向量编码 (BM25)
│   │   │   └── batch_processor.py       # 批处理优化
│   │   │
│   │   └── storage/                     # Storage 模块 (存储)
│   │       ├── __init__.py
│   │       ├── vector_upserter.py       # 向量库 Upsert
│   │       ├── bm25_indexer.py          # BM25 索引构建
│   │       └── image_storage.py         # 图片文件存储
│   │
│   ├── libs/                            # Libs 层 (可插拔抽象层)
│   │   ├── __init__.py
│   │   │
│   │   ├── loader/                      # Loader 抽象 (文档加载)
│   │   │   ├── __init__.py
│   │   │   ├── base_loader.py           # Loader 抽象基类
│   │   │   ├── pdf_loader.py            # PDF Loader (MarkItDown)
│   │   │   └── file_integrity.py        # 文件完整性检查 (SHA256 哈希)
│   │   │
│   │   ├── llm/                         # LLM 抽象
│   │   │   ├── __init__.py
│   │   │   ├── base_llm.py              # LLM 抽象基类
│   │   │   ├── llm_factory.py           # LLM 工厂
│   │   │   ├── azure_llm.py             # Azure OpenAI 实现
│   │   │   ├── openai_llm.py            # OpenAI 实现
│   │   │   ├── ollama_llm.py            # Ollama 本地模型实现
│   │   │   ├── deepseek_llm.py          # DeepSeek 实现
│   │   │   ├── base_vision_llm.py       # Vision LLM 抽象基类（支持图像输入）
│   │   │   └── azure_vision_llm.py      # Azure Vision 实现 (GPT-4o/GPT-4-Vision)
│   │   │
│   │   ├── embedding/                   # Embedding 抽象
│   │   │   ├── __init__.py
│   │   │   ├── base_embedding.py        # Embedding 抽象基类
│   │   │   ├── embedding_factory.py     # Embedding 工厂
│   │   │   ├── openai_embedding.py      # OpenAI Embedding 实现
│   │   │   ├── azure_embedding.py       # Azure Embedding 实现
│   │   │   └── ollama_embedding.py      # Ollama 本地模型实现
│   │   │
│   │   ├── splitter/                    # Splitter 抽象 (切分策略)
│   │   │   ├── __init__.py
│   │   │   ├── base_splitter.py         # Splitter 抽象基类
│   │   │   ├── splitter_factory.py      # Splitter 工厂
│   │   │   ├── recursive_splitter.py    # RecursiveCharacterTextSplitter 实现
│   │   │   ├── semantic_splitter.py     # 语义切分实现
│   │   │   └── fixed_length_splitter.py # 定长切分实现
│   │   │
│   │   ├── vector_store/                # VectorStore 抽象
│   │   │   ├── __init__.py
│   │   │   ├── base_vector_store.py     # VectorStore 抽象基类
│   │   │   ├── vector_store_factory.py  # VectorStore 工厂
│   │   │   └── chroma_store.py          # Chroma 实现
│   │   │
│   │   ├── reranker/                    # Reranker 抽象
│   │   │   ├── __init__.py
│   │   │   ├── base_reranker.py         # Reranker 抽象基类
│   │   │   ├── reranker_factory.py      # Reranker 工厂
│   │   │   ├── cross_encoder_reranker.py# CrossEncoder 实现
│   │   │   └── llm_reranker.py          # LLM Rerank 实现
│   │   │
│   │   └── evaluator/                   # Evaluator 抽象
│   │       ├── __init__.py
│   │       ├── base_evaluator.py        # Evaluator 抽象基类
│   │       ├── evaluator_factory.py     # Evaluator 工厂
│   │       ├── ragas_evaluator.py       # Ragas 实现
│   │       └── custom_evaluator.py      # 自定义指标实现
│   │
│   └── observability/                   # Observability 层 (可观测性)
│       ├── __init__.py
│       ├── logger.py                    # 结构化日志 (JSON Formatter)
│       ├── dashboard/                   # Web Dashboard (可视化管理平台)
│       │   ├── __init__.py
│       │   ├── app.py                   # Streamlit 入口 (页面导航注册)
│       │   ├── pages/                   # 六大功能页面
│       │   │   ├── overview.py          # 系统总览 (组件配置 + 数据统计)
│       │   │   ├── data_browser.py      # 数据浏览器 (文档/Chunk/图片查看)
│       │   │   ├── ingestion_manager.py # Ingestion 管理 (触发摄取/删除文档)
│       │   │   ├── ingestion_traces.py  # Ingestion 追踪 (摄取历史与详情)
│       │   │   ├── query_traces.py      # Query 追踪 (查询历史与详情)
│       │   │   └── evaluation_panel.py  # 评估面板 (运行评估/查看指标)
│       │   └── services/                # Dashboard 数据服务层
│       │       ├── trace_service.py     # Trace 读取服务 (解析 traces.jsonl)
│       │       ├── data_service.py      # 数据浏览服务 (ChromaStore/ImageStorage)
│       │       └── config_service.py    # 配置读取服务 (Settings 展示)
│       └── evaluation/                  # 评估模块
│           ├── __init__.py
│           ├── eval_runner.py           # 评估执行器
│           ├── ragas_evaluator.py       # Ragas 评估实现
│           └── composite_evaluator.py   # 组合评估器 (多后端并行)

│
├── data/                                # 数据目录
│   ├── documents/                       # 原始文档存放
│   │   └── {collection}/                # 按集合分类
│   ├── images/                          # 提取的图片存放
│   │   └── {collection}/                # 按集合分类（实际存储在 {doc_hash}/ 子目录下）
│   └── db/                              # 数据库与索引文件目录
│       ├── ingestion_history.db         # 文件完整性历史记录 (SQLite)
│       │                                # 表结构：file_hash, file_path, status, processed_at, error_msg
│       │                                # 用途：增量摄取，避免重复处理未变更文件
│       ├── image_index.db               # 图片索引映射 (SQLite)
│       │                                # 表结构：image_id, file_path, collection, doc_hash, page_num
│       │                                # 用途：快速查询 image_id → 本地文件路径，支持图片检索与引用
│       ├── chroma/                      # Chroma 向量库目录
│       │                                # 存储 Dense Vector、Sparse Vector 与 Chunk Metadata
│       └── bm25/                        # BM25 索引目录
│                                        # 存储倒排索引与 IDF 统计信息（当前使用 pickle）
│
├── cache/                               # 缓存目录
│   ├── embeddings/                      # Embedding 缓存 (按内容哈希)
│   ├── captions/                        # 图片描述缓存
│   └── processing/                      # 处理状态缓存 (文件哈希/Chunk 哈希)
│
├── logs/                                # 日志目录
│   ├── traces.jsonl                     # 追踪日志 (JSON Lines)
│   └── app.log                          # 应用日志
│
├── tests/                               # 测试目录
│   ├── unit/                            # 单元测试
│   │   ├── test_dense_retriever.py      # D2: 稠密检索器测试
│   │   ├── test_sparse_retriever.py     # D3: 稀疏检索器测试
│   │   ├── test_fusion_rrf.py           # D4: RRF 融合测试
│   │   ├── test_reranker_fallback.py    # D6: Reranker 回退测试
│   │   ├── test_protocol_handler.py     # E2: 协议处理器测试
│   │   ├── test_response_builder.py     # E3: 响应构建器测试
│   │   ├── test_list_collections.py     # E4: 集合列表工具测试
│   │   ├── test_get_document_summary.py # E5: 文档摘要工具测试
│   │   ├── test_trace_context.py        # F1: 追踪上下文测试
│   │   ├── test_jsonl_logger.py         # F2: JSON Lines 日志测试
│   │   └── ...                          # 其他已有单元测试
│   ├── integration/                     # 集成测试
│   │   ├── test_ingestion_pipeline.py
│   │   ├── test_hybrid_search.py        # D5: 混合检索集成测试
│   │   └── test_mcp_server.py           # E1-E6: MCP 服务器集成测试
│   ├── e2e/                             # 端到端测试
│   │   ├── test_data_ingestion.py
│   │   ├── test_recall.py               # G2: 召回回归测试
│   │   └── test_mcp_client.py           # G1: MCP Client 模拟测试
│   └── fixtures/                        # 测试数据
│       ├── sample_documents/
│       └── golden_test_set.json         # F5/G2: 黄金测试集
│
├── scripts/                             # 脚本目录
│   ├── ingest.py                        # 数据摄取脚本（离线摄取入口）
│   ├── query.py                         # 查询测试脚本（在线查询入口）
│   ├── evaluate.py                      # 评估运行脚本
│   └── start_dashboard.py               # Dashboard 启动脚本
│
├── main.py                              # MCP Server 启动入口
├── pyproject.toml                       # Python 项目配置
├── requirements.txt                     # 依赖列表
└── README.md                            # 项目说明
```

### 5.3 模块说明

#### 5.3.1 MCP Server 层

| 模块 | 职责 | 关键技术点 |
|-----|-----|----------|
| `server.py` | MCP Server 主入口，处理 Stdio Transport 通信 | Python MCP SDK，JSON-RPC 2.0 |
| `protocol_handler.py` | 协议解析与能力协商 | `initialize`、`tools/list`、`tools/call` |
| `tools/*` | 对外暴露的工具函数实现 | 装饰器定义，参数校验，响应格式化 |

#### 5.3.2 Core 层

| 模块 | 职责 | 关键技术点 |
|-----|-----|----------|
| `settings.py` | 配置加载与校验 | 读取 `config/settings.yaml`，解析为 `Settings`，必填字段校验（fail-fast） |
| `types.py` | 核心数据类型/契约（全链路复用） | 定义 `Document/Chunk/ChunkRecord/ProcessedQuery/RetrievalResult`；序列化稳定；作为 ingestion/retrieval/mcp 的数据契约中心 |
| `query_processor.py` | 查询预处理 | 关键词提取、同义词扩展、Metadata 解析 |
| `hybrid_search.py` | 混合检索编排 | 并行 Dense/Sparse 召回，结果融合，Metadata 过滤 |
| `dense_retriever.py` | 语义向量检索 | Query Embedding + VectorStore 检索，Cosine Similarity |
| `sparse_retriever.py` | BM25 关键词检索 | 倒排索引查询，TF-IDF 打分 |
| `fusion.py` | 结果融合 | RRF 算法，排名倒数加权 |
| `reranker.py` | 精排重排 | CrossEncoder / LLM Rerank / Fallback 回退 |
| `response_builder.py` | 响应构建 | MCP 响应格式化，Markdown 生成 |
| `citation_generator.py` | 引用生成 | 从检索结果生成结构化引用列表 |
| `multimodal_assembler.py` | 多模态组装 | Text + Image Base64 编码，MCP 多内容类型 |
| `trace_context.py` | 追踪上下文 | trace_id 生成，阶段记录，finish 汇总 |
| `trace_collector.py` | 追踪收集器 | 收集 trace 并触发持久化到 JSON Lines |

#### 5.3.3 Scripts 层（命令行入口）

| 脚本 | 职责 | 关键技术点 |
|-----|-----|----------|
| `ingest.py` | 离线数据摄取入口 | CLI 参数解析，调用 Ingestion Pipeline，支持 `--collection`/`--path`/`--force` |
| `query.py` | 在线查询测试入口 | CLI 参数解析，调用 HybridSearch + Reranker，支持 `--query`/`--top-k`/`--verbose` |
| `evaluate.py` | 评估运行入口 | 加载 golden_test_set，运行评估，输出 metrics |
| `start_dashboard.py` | Dashboard 启动入口 | Streamlit 应用启动 |

#### 5.3.4 Ingestion Pipeline 层

| 模块 | 职责 | 关键技术点 |
|-----|-----|----------|
| `pipeline.py` | Pipeline 流程编排 | 串行执行（或分阶段可观测），异常处理，增量更新；支持 `on_progress` 回调；统一使用 `core/types.py` 的数据契约 |
| `document_manager.py` | 文档生命周期管理 | list/delete/stats 操作；跨 4 个存储（Chroma/BM25/ImageStorage/FileIntegrity）的协调删除；供 Dashboard 与 CLI 调用 |

| `chunking/document_chunker.py` | Document→Chunks 转换 | 调用 `libs.splitter` 进行文本切分；生成稳定 Chunk ID（格式：`{doc_id}_{index:04d}_{hash}`）；继承 metadata；建立 source_ref 溯源链接 |
| `transform/base_transform.py` | Transform 抽象 | 原子化、幂等；可独立重试；失败降级不阻塞 |
| `transform/chunk_refiner.py` | Chunk 智能重组 | 规则去噪 + 可选 LLM 二次加工；可回退 |
| `transform/metadata_enricher.py` | 元数据增强 | Title/Summary/Tags 规则生成 + 可选 LLM 增强 |
| `transform/image_captioner.py` | 图片描述生成 | Vision LLM；写回 metadata/text；禁用/失败降级 |
| `embedding/dense_encoder.py` | 稠密向量编码 | 通过 `libs.embedding` 调用具体 provider；批处理 |
| `embedding/sparse_encoder.py` | 稀疏向量编码 | BM25 编码/统计（或替换实现）；批处理 |
| `storage/vector_upserter.py` | 向量存储写入 | 通过 `libs.vector_store` Upsert；幂等；metadata 完整 |

#### 5.3.5 Libs 层 (可插拔抽象)

| 抽象接口 | 当前默认实现 | 可替换选项 |
|---------|------------|----------|
| `LLMClient` | Azure OpenAI | OpenAI / Ollama / DeepSeek |
| `VisionLLMClient` | Azure OpenAI Vision (GPT-4o) | OpenAI Vision / Ollama Vision (LLaVA) |
| `EmbeddingClient` | OpenAI text-embedding-3 | BGE / Ollama 本地模型 |
| `Loader` | PDF Loader（MarkItDown） | Markdown/HTML/Code Loader 等 |
| `FileIntegrity` | SQLite (`data/db/ingestion_history.db`) | Redis（分布式）/ PostgreSQL（企业级）/ JSON文件（测试） |
| `Splitter` | RecursiveCharacterTextSplitter | Semantic / FixedLen |
| `VectorStore` | Chroma | Qdrant / Pinecone / Milvus |
| `Reranker` | CrossEncoder | LLM Rerank / None (关闭) |
| `Evaluator` | Ragas | DeepEval / 自定义指标 |

#### 5.3.6 Observability 层

| 模块 | 职责 | 关键技术点 |
|-----|-----|----------|
| `logger.py` | 结构化日志 | JSON Formatter，JSON Lines 输出 |
| `trace_context.py` | 请求级追踪 | trace_id，trace_type（query/ingestion），阶段耗时记录，`finish()` + `to_dict()` 序列化 |
| `trace_collector.py` | 追踪收集器 | 收集 trace 并触发持久化到 JSON Lines |
| `dashboard/app.py` | Dashboard 入口 | Streamlit 多页面应用，`st.navigation` 页面注册 |
| `dashboard/pages/overview.py` | 系统总览 | 组件配置卡片，数据资产统计 |
| `dashboard/pages/data_browser.py` | 数据浏览器 | 文档列表，Chunk 详情，图片预览 |
| `dashboard/pages/ingestion_manager.py` | Ingestion 管理 | 文件上传，摄取触发（进度条），文档删除 |
| `dashboard/pages/ingestion_traces.py` | Ingestion 追踪 | 摄取历史，阶段耗时瀑布图 |
| `dashboard/pages/query_traces.py` | Query 追踪 | 查询历史，Dense/Sparse 对比，Rerank 变化 |
| `dashboard/pages/evaluation_panel.py` | 评估面板 | 运行评估，指标展示，历史趋势（Phase H 实现） |
| `dashboard/services/trace_service.py` | Trace 数据服务 | 解析 traces.jsonl，按 trace_type 分类 |
| `dashboard/services/data_service.py` | 数据浏览服务 | 封装 ChromaStore/ImageStorage 读取 |
| `dashboard/services/config_service.py` | 配置读取服务 | 封装 Settings 展示 |
| `evaluation/eval_runner.py` | 评估执行 | 黄金测试集，指标计算，报告生成 |
| `evaluation/ragas_evaluator.py` | Ragas 评估 | Faithfulness, Answer Relevancy, Context Precision |
| `evaluation/composite_evaluator.py` | 组合评估器 | 多后端并行执行，结果汇总 |


### 5.4 数据流说明

#### 5.4.1 离线数据摄取流 (Ingestion Flow)

```
原始文档 (PDF)
      │
      ▼
┌─────────────────┐     未变更则跳过
│ File Integrity  │───────────────────────────► 结束
│   (SHA256)      │
└────────┬────────┘
         │ 新文件/已变更
         ▼
┌─────────────────┐
│     Loader      │  PDF → Markdown + 图片提取 + 元数据收集
│   (MarkItDown)  │
└────────┬────────┘
         │ Document (text + metadata.images)
         ▼
┌─────────────────┐
│    Splitter     │  按语义边界切分，保留图片引用
│ (Recursive)     │
└────────┬────────┘
         │ Chunks[] (with image_refs)
         ▼
┌─────────────────┐
│   Transform     │  LLM 重写 + 元数据注入 + 图片描述生成
│ (Enrichment)    │
└────────┬────────┘
         │ Enriched Chunks[] (with captions in text)
         ▼
┌─────────────────┐
│   Embedding     │  Dense (OpenAI) + Sparse (BM25) 双路编码
│  (Dual Path)    │
└────────┬────────┘
         │ Vectors + Chunks + Metadata
         ▼
┌─────────────────┐
│    Upsert       │  Chroma Upsert (幂等) + BM25 Index + 图片存储
│   (Storage)     │
└─────────────────┘
```

#### 5.4.2 在线查询流 (Query Flow)

```
用户查询 (via MCP Client)
      │
      ▼
┌─────────────────┐
│  MCP Server     │  JSON-RPC 解析，工具路由
│ (Stdio Transport)│
└────────┬────────┘
         │ query + params
         ▼
┌─────────────────┐
│ Query Processor │  关键词提取 + 同义词扩展 + Metadata 解析
│                 │
└────────┬────────┘
         │ processed_query + filters
         ▼
┌─────────────────────────────────────────────┐
│              Hybrid Search                  │
│  ┌─────────────┐          ┌─────────────┐   │
│  │Dense Retrieval│  并行   │Sparse Retrieval│   │
│  │ (Embedding)  │◄───────►│  (BM25)     │   │
│  └──────┬──────┘          └──────┬──────┘   │
│         │                        │          │
│         └────────┬───────────────┘          │
│                  ▼                          │
│         ┌─────────────┐                     │
│         │   Fusion    │  RRF 融合           │
│         │   (RRF)     │                     │
│         └──────┬──────┘                     │
└────────────────┼────────────────────────────┘
                 │ Top-M 候选
                 ▼
┌─────────────────┐
│    Reranker     │  CrossEncoder / LLM / None
│   (Optional)    │
└────────┬────────┘
         │ Top-K 精排结果
         ▼
┌─────────────────┐
│ Response Builder│  引用生成 + 图片 Base64 编码 + MCP 格式化
│                 │
└────────┬────────┘
         │ MCP Response (TextContent + ImageContent)
         ▼
返回给 MCP Client (Copilot / Claude Desktop)
```

#### 5.4.3 管理操作流 (Management Flow)

```
Dashboard (Streamlit UI)
      │
      ├─── 数据浏览 ──────────────────────────────────────────┐
      │                                                       │
      │    DataService                                        │
      │    ├── ChromaStore.get_by_metadata(source=...)        │
      │    ├── ImageStorage.list_images(collection, doc_hash) │
      │    └── 返回文档列表 / Chunk 详情 / 图片预览            │
      │                                                       │
      ├─── Ingestion 管理 ────────────────────────────────────┤
      │                                                       │
      │    触发摄取：                                          │
      │    ├── IngestionPipeline.run(path, collection,        │
      │    │                         on_progress=callback)    │
      │    └── st.progress() 实时更新进度                      │
      │                                                       │
      │    删除文档：                                          │
      │    ├── DocumentManager.delete_document(source, col)   │
      │    │   ├── ChromaStore.delete_by_metadata(source=...) │
      │    │   ├── BM25Indexer.remove_document(source=...)    │
      │    │   ├── ImageStorage.delete_images(col, doc_hash)  │
      │    │   └── FileIntegrity.remove_record(file_hash)     │
      │    └── 刷新文档列表                                    │
      │                                                       │
      └─── Trace 查看 ───────────────────────────────────────┘
           │
           TraceService
           ├── 读取 logs/traces.jsonl
           ├── 按 trace_type 分类 (query / ingestion)
           └── 返回 Trace 列表与详情
```

### 5.5 配置驱动设计


系统通过 `config/settings.yaml` 统一配置各组件实现，支持零代码切换：

```yaml
# config/settings.yaml 示例

# LLM 配置
llm:
  provider: azure           # azure | openai | ollama | deepseek
  model: gpt-4o
  azure_endpoint: "..."
  api_key: "${AZURE_API_KEY}"

# Embedding 配置
embedding:
  provider: openai          # openai | azure | ollama (本地)
  model: text-embedding-3-small
  
# Vision LLM 配置 (图片描述)
vision_llm:
  provider: azure           # azure | dashscope (Qwen-VL)
  model: gpt-4o
  
# 向量存储配置
vector_store:
  backend: chroma           # chroma | qdrant | pinecone
  persist_path: ./data/db/chroma

# 检索配置
retrieval:
  sparse_backend: bm25      # bm25 | elasticsearch
  fusion_algorithm: rrf     # rrf | weighted_sum
  top_k_dense: 20
  top_k_sparse: 20
  top_k_final: 10

# 重排配置
rerank:
  backend: cross_encoder    # none | cross_encoder | llm
  model: cross-encoder/ms-marco-MiniLM-L-6-v2
  top_m: 30

# 评估配置
evaluation:
  backends: [ragas, custom]
  golden_test_set: ./tests/fixtures/golden_test_set.json

# 可观测性配置
observability:
  enabled: true
  log_file: ./logs/traces.jsonl

# Dashboard 管理平台配置
dashboard:
  enabled: true
  port: 8501                     # Streamlit 服务端口
  traces_dir: ./logs             # Trace 日志文件目录
  auto_refresh: true             # 是否自动刷新（轮询新 trace）
  refresh_interval: 5            # 自动刷新间隔（秒）
```

### 5.6 扩展性设计要点


1. **新增 LLM Provider**：实现 `BaseLLM` 接口，在 `llm_factory.py` 注册，配置文件指定 `provider` 即可
2. **新增文档格式**：实现 `BaseLoader` 接口，在 Pipeline 中注册对应文件扩展名的处理器
3. **新增检索策略**：实现检索接口，在 `hybrid_search.py` 中组合调用
4. **新增评估指标**：实现 `BaseEvaluator` 接口，在配置中添加到 `backends` 列表


## 6. 项目排期

> **排期原则（严格对齐本 DEV_SPEC 的架构分层与目录结构）**
> 
> - **只按本文档设计落地**：以第 5.2 节目录树为“交付清单”，每一步都要在文件系统上产生可见变化。
> - **1 小时一个可验收增量**：每个小阶段（≈1h）都必须同时给出“验收标准 + 测试方法”，尽量做到 TDD。
> - **先打通主闭环，再补齐默认实现**：优先做“可跑通的端到端路径（Ingestion → Retrieval → MCP Tool）”，并在 Libs 层补齐可运行的默认后端实现，避免出现“只有接口没有实现”的空转。
> - **外部依赖可替换/可 Mock**：LLM/Embedding/Vision/VectorStore 的真实调用在单元测试中一律用 Fake/Mock，集成测试再开真实后端（可选）。

### 阶段总览（大阶段 → 目的）

1. **阶段 A：工程骨架与测试基座**
   - 目的：建立可运行、可配置、可测试的工程骨架；后续所有模块都能以 TDD 方式落地。
2. **阶段 B：Libs 可插拔层（Factory + Base 接口 + 默认可运行实现）**
  - 目的：把“可替换”变成代码事实；并补齐可运行的默认后端实现，确保 Core / Ingestion 不仅“可编译”，还可在真实环境跑通。
3. **阶段 C：Ingestion Pipeline（PDF→MD→Chunk→Embedding→Upsert）**
  - 目的：离线摄取链路跑通，能把样例文档写入向量库/BM25 索引并支持增量。
4. **阶段 D：Retrieval（Dense + Sparse + RRF + 可选 Rerank）**
  - 目的：在线查询链路跑通，得到 Top-K chunks（含引用信息），并具备稳定回退策略。
5. **阶段 E：MCP Server 层与 Tools 落地**
   - 目的：按 MCP 标准暴露 tools，让 Copilot/Claude 可直接调用查询能力。
6. **阶段 F：Trace 基础设施与打点**
   - 目的：增强 TraceContext，实现结构化日志持久化，在 Ingestion + Query 双链路打点，添加 Pipeline 进度回调。
7. **阶段 G：可视化管理平台 Dashboard**
   - 目的：搭建 Streamlit 六页面管理平台（系统总览 / 数据浏览 / Ingestion 管理 / Ingestion 追踪 / Query 追踪 / 评估占位），实现 DocumentManager 跨存储协调。
8. **阶段 H：评估体系**
   - 目的：实现 RagasEvaluator + CompositeEvaluator + EvalRunner，启用评估面板页面，建立 golden test set 回归基线。
9. **阶段 I：端到端验收与文档收口**
   - 目的：补齐 E2E 测试（MCP Client 模拟 + Dashboard 冒烟），完善 README，全链路验收，确保“开箱即用 + 可复现”。


---

### 📊 进度跟踪表 (Progress Tracking)

> **状态说明**：`[ ]` 未开始 | `[~]` 进行中 | `[x]` 已完成
> 
> **更新时间**：每完成一个子任务后更新对应状态

#### 阶段 A：工程骨架与测试基座

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| A1 | 初始化目录树与最小可运行入口 | [x] | 2026-01-26 | 目录结构、配置文件、main.py 已创建 |
| A2 | 引入 pytest 并建立测试目录约定 | [x] | 2026-01-26 | pytest 配置、tests/ 目录结构、22 个冒烟测试 |
| A3 | 配置加载与校验（Settings） | [x] | 2026-01-26 | 配置加载、校验与单元测试 |

#### 阶段 B：Libs 可插拔层

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| B1 | LLM 抽象接口与工厂 | [x] | 2026-01-27 | BaseLLM + LLMFactory + 16个单元测试 |
| B2 | Embedding 抽象接口与工厂 | [x] | 2026-01-27 | BaseEmbedding + EmbeddingFactory + 22个单元测试 |
| B3 | Splitter 抽象接口与工厂 | [x] | 2026-01-27 | BaseSplitter + SplitterFactory + 20个单元测试 |
| B4 | VectorStore 抽象接口与工厂 | [x] | 2026-01-27 | BaseVectorStore + VectorStoreFactory + 34个单元测试 |
| B5 | Reranker 抽象接口与工厂（含 None 回退） | [x] | 2026-01-27 | BaseReranker + RerankerFactory + NoneReranker + 单元测试 |
| B6 | Evaluator 抽象接口与工厂 | [x] | 2026-01-27 | BaseEvaluator + EvaluatorFactory + CustomEvaluator + 单元测试 |
| B7.1 | OpenAI-Compatible LLM 实现 | [x] | 2026-01-28 | OpenAILLM + AzureLLM + DeepSeekLLM + 33个单元测试 |
| B7.2 | Ollama LLM 实现 | [x] | 2026-01-28 | OllamaLLM + 32个单元测试 |
| B7.3 | OpenAI & Azure Embedding 实现 | [x] | 2026-01-28 | OpenAIEmbedding + AzureEmbedding + 27个单元测试 |
| B7.4 | Ollama Embedding 实现 | [x] | 2026-01-28 | OllamaEmbedding + 20个单元测试 |
| B7.5 | Recursive Splitter 默认实现 | [x] | 2026-01-28 | RecursiveSplitter + 24个单元测试 + langchain集成 |
| B7.6 | ChromaStore 默认实现 | [x] | 2026-01-30 | ChromaStore + 20个集成测试 + roundtrip验证 |
| B7.7 | LLM Reranker 实现 | [x] | 2026-01-30 | LLMReranker + 20个单元测试 + prompt模板支持 |
| B7.8 | Cross-Encoder Reranker 实现 | [x] | 2026-01-30 | CrossEncoderReranker + 26个单元测试 + 工厂集成 |
| B8 | Vision LLM 抽象接口与工厂集成 | [x] | 2026-01-31 | BaseVisionLLM + ImageInput + LLMFactory扩展 + 35个单元测试 |
| B9 | Azure Vision LLM 实现 | [x] | 2026-01-31 | AzureVisionLLM + 22个单元测试 + mock测试 + 图片压缩 |

#### 阶段 C：Ingestion Pipeline MVP

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| C1 | 定义核心数据类型/契约（Document/Chunk/ChunkRecord） | [x] | 2026-01-30 | Document/Chunk/ChunkRecord + 18个单元测试 |
| C2 | 文件完整性检查（SHA256） | [x] | 2026-01-30 | FileIntegrityChecker + SQLiteIntegrityChecker + 25个单元测试 |
| C3 | Loader 抽象基类与 PDF Loader | [x] | 2026-01-30 | BaseLoader + PdfLoader + PyMuPDF图片提取 + 21单元测试 + 9集成测试 |
| C4 | Splitter 集成（调用 Libs） | [x] | 2026-01-31 | DocumentChunker + 19个单元测试 + 5个核心增值功能 |
| C5 | Transform 基类 + ChunkRefiner | [x] | 2026-01-31 | BaseTransform + ChunkRefiner (Rule + LLM) + TraceContext + 25单元测试 + 5集成测试 |
| C6 | MetadataEnricher | [x] | 2026-01-31 | MetadataEnricher (Rule + LLM) + 26单元测试 + 真实LLM集成测试 |
| C7 | ImageCaptioner | [x] | 2026-02-01 | ImageCaptioner + Azure Vision LLM 实现 + 集成测试 |
| C8 | DenseEncoder | [x] | 2026-02-01 | 批量编码+Azure集成测试 |
| C9 | SparseEncoder | [x] | 2026-02-01 | 词频统计+语料库统计+26单元测试 |
| C10 | BatchProcessor | [x] | 2026-02-01 | BatchProcessor + BatchResult + 20个单元测试 |
| C11 | BM25Indexer（倒排索引+IDF计算） | [x] | 2026-02-01 | BM25索引器+IDF计算+持久化+26单元测试 |
| C12 | VectorUpserter（幂等upsert） | [x] | 2026-02-01 | 稳定chunk_id生成+幂等upsert+21单元测试 |
| C13 | ImageStorage（图片存储+SQLite索引） | [x] | 2026-02-01 | ImageStorage + SQLite索引 + 37个单元测试 + WAL并发支持 |
| C14 | Pipeline 编排（MVP 串起来） | [x] | 2026-02-02 | 完整流程编排+Azure LLM/Embedding集成测试通过 |
| C15 | 脚本入口 ingest.py | [x] | 2026-02-02 | CLI脚本+E2E测试+文件发现+skip功能 |

#### 阶段 D：Retrieval MVP

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| D1 | QueryProcessor（关键词提取 + filters） | [x] | 2026-02-03 | ProcessedQuery类型+关键词提取+停用词过滤+filter语法+38单元测试 |
| D2 | DenseRetriever（调用 VectorStore.query） | [x] | 2026-02-03 | RetrievalResult类型+依赖注入+ChromaStore.query修复+30单元测试 |
| D3 | SparseRetriever（BM25 查询） | [x] | 2026-02-04 | BaseVectorStore.get_by_ids+ChromaStore实现+SparseRetriever+26单元测试 |
| D4 | RRF Fusion | [x] | 2026-02-04 | RRFFusion类+k参数可配置+加权融合+确定性输出+34单元测试 |
| D5 | HybridSearch 编排 | [x] | 2026-02-04 | HybridSearch类+并行检索+优雅降级+元数据过滤+29集成测试 |
| D6 | Reranker（Core 层编排 + Fallback） | [x] | 2026-02-04 | CoreReranker+LLM Reranker集成+Fallback机制+27单元测试+7集成测试 |
| D7 | 脚本入口 query.py（查询可用） | [x] | 2026-02-04 | CLI 查询入口 + verbose 输出 |

#### 阶段 E：MCP Server 层与 Tools

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| E1 | MCP Server 入口与 Stdio 约束 | [x] | 2026-02-04 | server.py 使用官方 MCP SDK + stdio + 2集成测试 |
| E2 | Protocol Handler 协议解析与能力协商 | [x] | 2026-02-04 | ProtocolHandler类+tool注册+错误处理+20单元测试 |
| E3 | query_knowledge_hub Tool | [x] | 2026-02-04 | ResponseBuilder+CitationGenerator+Tool注册+24单元测试+2集成测试 |
| E4 | list_collections Tool | [x] | 2026-02-04 | ListCollectionsTool+CollectionInfo+ChromaDB集成+41单元测试+2集成测试 |
| E5 | get_document_summary Tool | [x] | 2026-02-04 | GetDocumentSummaryTool+DocumentSummary+错误处理+71单元测试 |
| E6 | 多模态返回组装（Text + Image） | [x] | 2026-02-04 | MultimodalAssembler+base64编码+MIME检测+ResponseBuilder集成+54单元测试+4集成测试 |

#### 阶段 F：Trace 基础设施与打点

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| F1 | TraceContext 增强（finish + 耗时统计 + trace_type） | [x] | 2026-02-08 | TraceContext增强(trace_type/finish/elapsed_ms/to_dict)+TraceCollector+28单元测试 |
| F2 | 结构化日志 logger（JSON Lines） | [x] | 2026-02-08 | JSONFormatter+get_trace_logger+write_trace+16单元测试 |
| F3 | 在 Query 链路打点 | [x] | 2026-02-08 | HybridSearch+CoreReranker trace注入(5阶段)+14集成测试 |
| F4 | 在 Ingestion 链路打点 | [x] | 2026-02-08 | Pipeline五阶段trace注入(load/split/transform/embed/upsert)+11集成测试 |
| F5 | Pipeline 进度回调 (on_progress) | [x] | 2026-02-08 | on_progress回调(6阶段通知)+6单元测试 |

#### 阶段 G：可视化管理平台 Dashboard

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| G1 | Dashboard 基础架构与系统总览页 | [x] | 2026-02-09 | app.py多页面导航+overview页+ConfigService+start_dashboard.py+11单元测试 |
| G2 | DocumentManager 实现 | [x] | 2026-02-09 | DocumentManager跨存储协调(ChromaStore+BM25+ImageStorage+IntegrityChecker)+文档删除+21单元测试 |
| G3 | 数据浏览器页面 | [x] | 2026-02-09 | DataService只读门面+文档列表+chunk内容展示+元数据JSON展开+collection切换 |
| G4 | Ingestion 管理页面 | [x] | 2026-02-09 | 文件上传+IngestionPipeline集成+实时进度条+TraceContext自动记录 |
| G5 | Ingestion 追踪页面 | [x] | 2026-02-09 | TraceService读取traces.jsonl+阶段时间线+耗时柱状图+stage详情展开 |
| G6 | Query 追踪页面 | [x] | 2026-02-09 | Query trace过滤+检索结果展示+rerank对比+耗时分析 |

#### 阶段 H：评估体系

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| H1 | RagasEvaluator 实现 | [x] | 2026-02-09 | 19/19 tests passed |
| H2 | CompositeEvaluator 实现 | [x] | 2026-02-09 | 11/11 tests passed |
| H3 | EvalRunner + Golden Test Set | [x] | 2026-02-09 | 15/15 tests passed |
| H4 | 评估面板页面 | [x] | 2026-02-09 | 6/6 tests passed, dashboard page with history tracking |
| H5 | Recall 回归测试（E2E） | [x] | 2026-02-09 | 3 unit+4 e2e(skip without data), hit@k+MRR threshold gating |

#### 阶段 I：端到端验收与文档收口

| 任务编号 | 任务名称 | 状态 | 完成日期 | 备注 |
|---------|---------|------|---------|------|
| I1 | E2E：MCP Client 侧调用模拟 | [x] | 2026-02-23 | 7个E2E测试+import死锁修复+非阻塞readline |
| I2 | E2E：Dashboard 冒烟测试 | [x] | 2026-02-24 | 6个页面冒烟测试+AppTest框架+mock服务 |
| I3 | 完善 README（运行说明 + MCP + Dashboard） | [x] | 2026-02-24 | 快速开始+配置说明+MCP配置+Dashboard指南+测试+FAQ |
| I4 | 清理接口一致性（契约测试补齐） | [x] | 2026-02-24 | VectorStore+Reranker+Evaluator边界测试+83测试全绿 |
| I5 | 全链路 E2E 验收 | [x] | 2026-02-24 | 1198单元+30e2e通过,ingest/query/evaluate脚本验证 |

---

### 📈 总体进度

| 阶段 | 总任务数 | 已完成 | 进度 |
|------|---------|--------|------|
| 阶段 A | 3 | 3 | 100% |
| 阶段 B | 16 | 16 | 100% |
| 阶段 C | 15 | 15 | 100% |
| 阶段 D | 7 | 7 | 100% |
| 阶段 E | 6 | 6 | 100% |
| 阶段 F | 5 | 5 | 100% |
| 阶段 G | 6 | 6 | 100% |
| 阶段 H | 5 | 5 | 100% |
| 阶段 I | 5 | 5 | 100% |
| **总计** | **68** | **68** | **100%** |


---

## 阶段 A：工程骨架与测试基座（目标：先可导入，再可测试）

### A1：初始化目录树与最小可运行入口 ✅
- **目标**：在 repo 根目录创建第 5.2 节所述目录骨架与空模块文件（可 import）。
- **修改文件**：
  - `main.py`
  - `pyproject.toml`
  - `README.md`
  - `.gitignore`（Python 项目标准忽略规则：`__pycache__`、`.venv`、`.env`、`*.pyc`、IDE 配置等）
  - `src/**/__init__.py`（按目录树补齐）
  - `config/settings.yaml`（最小可解析配置）
  - `config/prompts/image_captioning.txt`（可先放占位内容，后续阶段补充 Prompt）
  - `config/prompts/chunk_refinement.txt`（可先放占位内容，后续阶段补充 Prompt）
  - `config/prompts/rerank.txt`（可先放占位内容，后续阶段补充 Prompt）
- **实现类/函数**：无（仅骨架）。
- **实现类/函数**：无（仅骨架，不实现业务逻辑）。
- **实现类/函数**：为当前项目创建一个虚拟环境模块。
 - **验收标准**：
  - 目录结构与 DEV_SPEC 5.2 一致（至少把对应目录创建出来）。
  - `config/prompts/` 目录存在，且三个 prompt 文件可被读取（即使只是占位文本）。
  - 能导入关键顶层包（与目录结构一一对应）：
    - `python -c "import mcp_server; import core; import ingestion; import libs; import observability"`
  - 可以启动虚拟环境模块
- **测试方法**：运行 `python -m compileall src`（仅做语法/可导入性检查；pytest 基座在 A2 建立）。

### A2：引入 pytest 并建立测试目录约定
- **目标**：建立 `tests/unit|integration|e2e|fixtures` 目录与 pytest 运行基座。
- **修改文件**：
  - `pyproject.toml`（添加 pytest 配置：testpaths、markers 等）
  - `tests/unit/test_smoke_imports.py`
  - `tests/fixtures/sample_documents/`（放 1 个最小样例文档占位）
- **实现类/函数**：无。
- **实现类/函数**：无（新增的是测试文件与 pytest 配置）。
- **验收标准**：
  - `pytest -q` 可运行并通过。
  - 至少 1 个冒烟测试（例如 `tests/unit/test_smoke_imports.py` 只做关键包 import 校验）。
- **测试方法**：`pytest -q tests/unit/test_smoke_imports.py`。

### A3：配置加载与校验（Settings）
- **目标**：实现读取 `config/settings.yaml` 的配置加载器，并在启动时校验关键字段存在。
- **修改文件**：
  - `main.py`（启动时调用 `load_settings()`，缺字段直接 fail-fast 退出）
  - `src/observability/logger.py`（先占位：提供 get_logger，stderr 输出）
  - `src/core/settings.py`（新增：集中放 Settings 数据结构与加载/校验逻辑）
  - `config/settings.yaml`（补齐字段：llm/embedding/vector_store/retrieval/rerank/evaluation/observability）
  - `tests/unit/test_config_loading.py`
- **实现类/函数**：
  - `Settings`（dataclass：只做结构与最小校验；不在这里做任何网络/IO 的“业务初始化”）
  - `load_settings(path: str) -> Settings`（读取 YAML -> 解析为 Settings -> 校验必填字段）
  - `validate_settings(settings: Settings) -> None`（把“必填字段检查”集中化，错误信息包含字段路径，例如 `embedding.provider`）
- **验收标准**：
  - `main.py` 启动时能成功加载 `config/settings.yaml` 并拿到 `Settings` 对象。
  - 删除/缺失关键字段时（例如 `embedding.provider`），启动或 `load_settings()` 抛出“可读错误”（明确指出缺的是哪个字段）。
- **测试方法**：`pytest -q tests/unit/test_config_loading.py`。

---

## 阶段 B：Libs 可插拔层（目标：Factory 可工作，且至少有“默认后端”可跑通端到端）

### B1：LLM 抽象接口与工厂
- **目标**：定义 `BaseLLM` 与 `LLMFactory`，支持按配置选择 provider。
- **修改文件**：
  - `src/libs/llm/base_llm.py`
  - `src/libs/llm/llm_factory.py`
  - `tests/unit/test_llm_factory.py`
- **实现类/函数**：
  - `BaseLLM.chat(messages) -> str`（或统一 response 对象）
  - `LLMFactory.create(settings) -> BaseLLM`
- **验收标准**：在测试里用 Fake provider（测试内 stub）验证工厂路由逻辑。
- **测试方法**：`pytest -q tests/unit/test_llm_factory.py`。

### B2：Embedding 抽象接口与工厂 ✅
- **目标**：定义 `BaseEmbedding` 与 `EmbeddingFactory`，支持批量 embed。
- **修改文件**：
  - `src/libs/embedding/base_embedding.py`
  - `src/libs/embedding/embedding_factory.py`
  - `tests/unit/test_embedding_factory.py`
- **实现类/函数**：
  - `BaseEmbedding.embed(texts: list[str], trace: TraceContext | None = None) -> list[list[float]]`
  - `EmbeddingFactory.create(settings) -> BaseEmbedding`
- **验收标准**：Fake embedding 返回稳定向量，工厂按 provider 分流。
- **测试方法**：`pytest -q tests/unit/test_embedding_factory.py`。

### B3：Splitter 抽象接口与工厂
- **目标**：定义 `BaseSplitter` 与 `SplitterFactory`，支持不同切分策略（Recursive/Semantic/Fixed）。
- **修改文件**：
  - `src/libs/splitter/base_splitter.py`
  - `src/libs/splitter/splitter_factory.py`
  - `tests/unit/test_splitter_factory.py`
- **实现类/函数**：
  - `BaseSplitter.split_text(text: str, trace: TraceContext | None = None) -> List[str]`
  - `SplitterFactory.create(settings) -> BaseSplitter`
- **验收标准**：Factory 能根据配置返回不同类型的 Splitter 实例（测试中可用 Fake 实现）。
- **测试方法**：`pytest -q tests/unit/test_splitter_factory.py`。

### B4：VectorStore 抽象接口与工厂（先定义契约）
- **目标**：定义 `BaseVectorStore` 与 `VectorStoreFactory`，先不接真实 DB。
- **修改文件**：
  - `src/libs/vector_store/base_vector_store.py`
  - `src/libs/vector_store/vector_store_factory.py`
  - `tests/unit/test_vector_store_contract.py`
- **实现类/函数**：
  - `BaseVectorStore.upsert(records, trace: TraceContext | None = None)`
  - `BaseVectorStore.query(vector, top_k, filters, trace: TraceContext | None = None)`
- **验收标准**：契约测试（contract test）约束输入输出 shape。
- **测试方法**：`pytest -q tests/unit/test_vector_store_contract.py`。

### B5：Reranker 抽象接口与工厂（含 None 回退）
- **目标**：实现 `BaseReranker`、`RerankerFactory`，提供 `NoneReranker` 作为默认回退。
- **修改文件**：
  - `src/libs/reranker/base_reranker.py`
  - `src/libs/reranker/reranker_factory.py`
  - `tests/unit/test_reranker_factory.py`
- **实现类/函数**：
  - `BaseReranker.rerank(query, candidates, trace: TraceContext | None = None) -> ranked_candidates`
  - `NoneReranker`（保持原顺序）
- **验收标准**：backend=none 时不会改变排序；未知 backend 明确报错。
- **测试方法**：`pytest -q tests/unit/test_reranker_factory.py`。

### B6：Evaluator 抽象接口与工厂（先做自定义轻量指标）
- **目标**：定义 `BaseEvaluator`、`EvaluatorFactory`，实现最小 `CustomEvaluator`（例如 hit_rate/mrr）。
- **修改文件**：
  - `src/libs/evaluator/base_evaluator.py`
  - `src/libs/evaluator/evaluator_factory.py`
  - `src/libs/evaluator/custom_evaluator.py`
  - `tests/unit/test_custom_evaluator.py`
- **验收标准**：输入 query + retrieved_ids + golden_ids 能输出稳定 metrics。
- **测试方法**：`pytest -q tests/unit/test_custom_evaluator.py`。

### B7：补齐 Libs 默认实现（拆分为≈1h可验收增量）

> 说明：B7 只补齐与端到端主链路强相关的默认实现（LLM/Embedding/Splitter/VectorStore/Reranker）。其余可选扩展（例如额外 splitter 策略、更多 vector store 后端、更多 evaluator 后端等）保持原排期不提前。

### B7.1：OpenAI-Compatible LLM（OpenAI/Azure/DeepSeek）
- **目标**：补齐 OpenAI-compatible 的 LLM 实现，确保通过 `LLMFactory` 可创建并可被 mock 测试。
- **修改文件**：
  - `src/libs/llm/openai_llm.py`
  - `src/libs/llm/azure_llm.py`
  - `src/libs/llm/deepseek_llm.py`
  - `tests/unit/test_llm_providers_smoke.py`（mock HTTP，不走真实网络）
- **验收标准**：
  - 配置不同 `provider` 时工厂路由正确。
  - `chat(messages)` 对输入 shape 校验清晰，异常信息可读（包含 provider 与错误类型）。
- **测试方法**：`pytest -q tests/unit/test_llm_providers_smoke.py`。

### B7.2：Ollama LLM（本地后端）
- **目标**：补齐 `ollama_llm.py`，支持本地 HTTP endpoint（默认 `base_url` + `model`），并可被 mock 测试。
- **修改文件**：
  - `src/libs/llm/ollama_llm.py`
  - `tests/unit/test_ollama_llm.py`（mock HTTP）
- **验收标准**：
  - provider=ollama 时可由 `LLMFactory` 创建。
  - 在连接失败/超时等场景下，抛出可读错误且不泄露敏感配置。
- **测试方法**：`pytest -q tests/unit/test_ollama_llm.py`。

### B7.3：OpenAI & Azure Embedding 实现
- **目标**：补齐 `openai_embedding.py` 和 `azure_embedding.py`，支持 OpenAI 官方 API 和 Azure OpenAI 服务的 Embedding 调用，支持批量 `embed(texts)`，并可被 mock 测试。
- **修改文件**：
  - `src/libs/embedding/openai_embedding.py`
  - `src/libs/embedding/azure_embedding.py`
  - `tests/unit/test_embedding_providers_smoke.py`（mock HTTP，包含 OpenAI 和 Azure 测试用例）
- **验收标准**：
  - provider=openai 时 `EmbeddingFactory` 可创建，支持 OpenAI 官方 API 的 text-embedding-3-small/large 等模型。
  - provider=azure 时 `EmbeddingFactory` 可创建，正确处理 Azure 特有的 endpoint、api-version、api-key 配置，支持 Azure 部署的 text-embedding-ada-002 等模型。
  - 空输入、超长输入有明确行为（报错或截断策略由配置决定）。
  - Azure 实现复用 OpenAI Embedding 的核心逻辑，保持行为一致性。
- **测试方法**：`pytest -q tests/unit/test_embedding_providers_smoke.py`。

### B7.4：Ollama Embedding 实现
- **目标**：补齐 `ollama_embedding.py`，支持通过 Ollama HTTP API 调用本地部署的 Embedding 模型（如 `nomic-embed-text`、`mxbai-embed-large` 等），实现 `embed(texts)` 批量向量化功能。
- **修改文件**：
  - `src/libs/embedding/ollama_embedding.py`
  - `tests/unit/test_ollama_embedding.py`（包含 mock HTTP 测试）
- **验收标准**：
  - provider=ollama 时 `EmbeddingFactory` 可创建。
  - 支持配置 Ollama 服务地址（默认 http://localhost:11434）和模型名称。
  - 输出向量维度由模型决定（如 nomic-embed-text 为 768 维），满足 ingestion/retrieval 的接口契约。
  - 支持批量 `embed(texts)` 调用，内部处理单条/批量请求逻辑。
  - 空输入、超长输入有明确行为（报错或截断策略）。
  - mock 测试覆盖正常响应、连接失败、超时等场景。
- **测试方法**：`pytest -q tests/unit/test_ollama_embedding.py`。

### B7.5：Recursive Splitter 默认实现
- **目标**：补齐 `recursive_splitter.py`，封装 LangChain 的切分逻辑，作为默认切分器。
- **修改文件**：
  - `src/libs/splitter/recursive_splitter.py`
  - `tests/unit/test_recursive_splitter_lib.py`
- **验收标准**：
  - provider=recursive 时 `SplitterFactory` 可创建。
  - `split_text` 能正确处理 Markdown 结构（标题/代码块不被打断）。
- **测试方法**：`pytest -q tests/unit/test_recursive_splitter_lib.py`。

### B7.6：ChromaStore（VectorStore 默认后端）
- **目标**：补齐 `chroma_store.py`，支持最小 `upsert(records)` 与 `query(vector, top_k, filters)`，并支持本地持久化目录（例如 `data/db/chroma/`）。
- **修改文件**：
  - `src/libs/vector_store/chroma_store.py`
  - `tests/integration/test_chroma_store_roundtrip.py`
- **验收标准**：
  - provider=chroma 时 `VectorStoreFactory` 可创建。
  - **必须完成完整的 upsert→query roundtrip 测试**：使用 mock 数据完成真实的存储和检索流程，验证返回结果的确定性和正确性。
  - 测试应覆盖：基本 upsert、向量查询、top_k 参数、metadata filters（如支持）。
  - 使用临时目录进行持久化测试，测试结束后清理。
- **测试方法**：`pytest -q tests/integration/test_chroma_store_roundtrip.py`

### B7.7：LLM Reranker（读取 rerank prompt）
- **目标**：补齐 `llm_reranker.py`，读取 `config/prompts/rerank.txt` 构造 prompt（测试中可注入替代文本），并可在失败时返回可回退信号。
- **修改文件**：
  - `src/libs/reranker/llm_reranker.py`
  - `tests/unit/test_llm_reranker.py`（mock LLM）
- **验收标准**：
  - backend=llm 时 `RerankerFactory` 可创建。
  - 输出严格结构化（例如 ranked ids），不满足 schema 时抛出可读错误。
- **测试方法**：`pytest -q tests/unit/test_llm_reranker.py`。

### B7.8：Cross-Encoder Reranker（本地/托管模型，占位可跑）
- **目标**：补齐 `cross_encoder_reranker.py`，支持对 Top-M candidates 打分排序；测试中用 mock scorer 保证 deterministic。
- **修改文件**：
  - `src/libs/reranker/cross_encoder_reranker.py`
  - `tests/unit/test_cross_encoder_reranker.py`（mock scorer）
- **验收标准**：
  - backend=cross_encoder 时 `RerankerFactory` 可创建。
  - 提供超时/失败回退信号（供 Core 层 `D6` fallback 使用）。
- **测试方法**：`pytest -q tests/unit/test_cross_encoder_reranker.py`。

### B8：Vision LLM 抽象接口与工厂集成
- **目标**：定义 `BaseVisionLLM` 抽象接口，扩展 `LLMFactory` 支持 Vision LLM 创建，为 C7 的 ImageCaptioner 提供底层抽象。
- **修改文件**：
  - `src/libs/llm/base_vision_llm.py`
  - `src/libs/llm/llm_factory.py`（扩展 `create_vision_llm` 方法）
  - `tests/unit/test_vision_llm_factory.py`
- **实现类/函数**：
  - `BaseVisionLLM.chat_with_image(text: str, image_path: str | bytes, trace: TraceContext | None = None) -> ChatResponse`
  - `LLMFactory.create_vision_llm(settings) -> BaseVisionLLM`
- **验收标准**：
  - 抽象接口清晰定义多模态输入（文本+图片路径/base64）。
  - 工厂方法 `create_vision_llm` 能根据配置路由到不同 provider（测试中用 Fake Vision LLM 验证）。
  - 接口设计支持图片预处理（压缩、格式转换）的扩展点。
- **测试方法**：`pytest -q tests/unit/test_vision_llm_factory.py`。

### B9：Azure Vision LLM 实现
- **目标**：实现 `AzureVisionLLM`，支持通过 Azure OpenAI 调用 GPT-4o/GPT-4-Vision-Preview 进行图像理解。
- **修改文件**：
  - `src/libs/llm/azure_vision_llm.py`
  - `tests/unit/test_azure_vision_llm.py`（mock HTTP，不走真实 API）
- **实现类/函数**：
  - `AzureVisionLLM(BaseVisionLLM)`：实现 `chat_with_image` 方法
  - 支持 Azure 特有配置：`azure_endpoint`, `api_version`, `deployment_name`, `api_key`
- **验收标准**：
  - provider=azure 且配置 vision_llm 时，`LLMFactory.create_vision_llm()` 可创建 Azure Vision LLM 实例。
  - 支持图片路径和 base64 两种输入方式。
  - 图片过大时自动压缩至 `max_image_size` 配置的尺寸（默认2048px）。
  - API 调用失败时抛出清晰错误，包含 Azure 特有错误码。
  - mock 测试覆盖：正常调用、图片压缩、超时、认证失败等场景。
- **测试方法**：`pytest -q tests/unit/test_azure_vision_llm.py`。

---

## 阶段 C：Ingestion Pipeline MVP（目标：能把 PDF 样例摄取到本地存储）

> 注：本阶段严格按 5.4.1 的离线数据流落地，并优先实现“增量跳过（SHA256）”。

### C1：定义核心数据类型/契约（Document/Chunk/ChunkRecord）
- **目标**：定义全链路（ingestion → retrieval → mcp tools）共用的数据结构/契约，避免散落在各子模块内导致的耦合与重复。
- **修改文件**：
  - `src/core/types.py`
  - `src/core/__init__.py`（可选：统一 re-export 以简化导入路径）
  - `tests/unit/test_core_types.py`
- **实现类/函数**（建议）：
  - `Document(id, text, metadata)`
  - `Chunk(id, text, metadata, start_offset, end_offset, source_ref?)`
  - `ChunkRecord(id, text, metadata, dense_vector?, sparse_vector?)`（用于存储/检索载体；字段按后续 C8~C12 演进）
- **验收标准**：
  - 类型可序列化（dict/json）且字段稳定（单元测试断言）。
  - `metadata` 约定最少包含 `source_path`，其余字段允许增量扩展但不得破坏兼容。
  - **`metadata.images` 字段规范**（用于多模态支持）：
    - 结构：`List[{"id": str, "path": str, "page": int, "text_offset": int, "text_length": int, "position": dict}]`
    - `id`：全局唯一图片标识符（建议格式：`{doc_hash}_{page}_{seq}`）
    - `path`：图片文件存储路径（约定：`data/images/{collection}/{image_id}.png`）
    - `page`：图片在原文档中的页码（可选，适用于PDF等分页文档）
    - `text_offset`：占位符在 `Document.text` 中的起始字符位置（从0开始计数）
    - `text_length`：占位符的字符长度（通常为 `len("[IMAGE: {image_id}]")`）
    - `position`：图片在原文档中的物理位置信息（可选，如PDF坐标、像素位置、尺寸等）
    - 说明：通过 `text_offset` 和 `text_length` 可精确定位图片在文本中的位置，支持同一图片多次出现的场景
  - **文本中图片占位符规范**：在 `Document.text` 中，图片位置使用 `[IMAGE: {image_id}]` 格式标记。
- **测试方法**：`pytest -q tests/unit/test_core_types.py`。

### C2：文件完整性检查（SHA256）
- **目标**：在Libs中实现 `file_integrity.py`：计算文件 hash，并提供“是否跳过”的判定接口（使用 SQLite 作为默认存储，支持后续替换为 Redis/PostgreSQL）。
- **修改文件**：
  - `src/libs/loader/file_integrity.py`
  - `tests/unit/test_file_integrity.py`
  - 数据库文件：`data/db/ingestion_history.db`（自动创建）
- **实现类/函数**：
  - `FileIntegrityChecker` 类（抽象接口）
  - `SQLiteIntegrityChecker(FileIntegrityChecker)` 类（默认实现）
    - `compute_sha256(path: str) -> str`
    - `should_skip(file_hash: str) -> bool`
    - `mark_success(file_hash: str, file_path: str, ...)`
    - `mark_failed(file_hash: str, error_msg: str)`
- **验收标准**：
  - 同一文件多次计算hash结果一致
  - 标记 success 后，`should_skip` 返回 `True`
  - 数据库文件正确创建在 `data/db/ingestion_history.db`
  - 支持并发写入（SQLite WAL模式）
- **测试方法**：`pytest -q tests/unit/test_file_integrity.py`。

### C3：Loader 抽象基类与 PDF Loader 壳子
- **目标**：在Libs中定义 `BaseLoader`，并实现 `PdfLoader` 的最小行为。
- **修改文件**：
  - `src/libs/loader/base_loader.py`
  - `src/libs/loader/pdf_loader.py`
  - `tests/unit/test_loader_pdf_contract.py`
- **实现类/函数**：
  - `BaseLoader.load(path) -> Document`
  - `PdfLoader.load(path)`
- **验收标准**：
  - **基础要求**：对 sample PDF（fixtures）能产出 Document，metadata 至少含 `source_path`。
  - **图片处理要求**（遵循 C1 定义的契约）：
    - 若 PDF 包含图片，应提取图片并保存到 `data/images/{doc_hash}/` 目录
    - 在 `Document.text` 中，图片位置插入占位符：`[IMAGE: {image_id}]`
    - 在 `metadata.images` 中记录图片信息（格式见 C1 规范）
    - 若 PDF 无图片，`metadata.images` 可为空列表或省略该字段
  - **降级行为**：图片提取失败不应阻塞文本解析，可在日志中记录警告。
- **测试方法**：`pytest -q tests/unit/test_loader_pdf_contract.py`。
- **测试建议**：
  - 准备两个测试文件：`simple.pdf`（纯文本）和 `with_images.pdf`（包含图片）
  - 验证纯文本PDF能正常解析
  - 验证带图片PDF能提取图片并正确插入占位符

### C4：Splitter 集成（调用 Libs）
- **目标**：实现 Chunking 模块作为 `libs.splitter` 和 Ingestion Pipeline 之间的**适配器层**，完成 Document→Chunks 的业务对象转换。
- **核心职责（DocumentChunker 相比 libs.splitter 的增值）**：
  - **职责边界说明**：
    - `libs.splitter`：纯文本切分工具（`str → List[str]`），不涉及业务对象
    - `DocumentChunker`：业务适配器（`Document对象 → List[Chunk对象]`），添加业务逻辑
  - **6 个增值功能**：
    1. **Chunk ID 生成**：为每个文本片段生成唯一且确定性的 ID（格式：`{doc_id}_{index:04d}_{hash_8chars}`）
    2. **元数据继承**：将 Document.metadata 复制到每个 Chunk.metadata（source_path, doc_type, title 等）
    3. **添加 chunk_index**：记录 chunk 在文档中的序号（从 0 开始），用于排序和定位
    4. **建立 source_ref**：记录 Chunk.source_ref 指向父 Document.id，支持溯源
    5. **图片引用按需分发**：扫描每个 chunk 文本中的 `[IMAGE: {id}]` 占位符，从 `Document.metadata["images"]` 中提取该 chunk 实际引用的 ImageRef，写入 `chunk.metadata["images"]`（仅含该 chunk 引用的子集）和 `chunk.metadata["image_refs"]`（image_id 列表）。无占位符的 chunk 不含 `images` 字段。⚠️ 不可简单整体继承或丢弃文档级 `images`，否则下游 C7 ImageCaptioner 将无法定位图片路径。
    6. **类型转换**：将 libs.splitter 的 `List[str]` 转换为符合 core.types 契约的 `List[Chunk]` 对象
- **修改文件**：
  - `src/ingestion/chunking/document_chunker.py`
  - `src/ingestion/chunking/__init__.py`
  - `tests/unit/test_document_chunker.py`
- **实现类/函数**：
  - `DocumentChunker` 类
  - `__init__(settings: Settings)`：通过 SplitterFactory 获取配置的 splitter 实例
  - `split_document(document: Document) -> List[Chunk]`：完整的转换流程
  - `_generate_chunk_id(doc_id: str, index: int, text: str) -> str`：生成稳定 Chunk ID
  - `_inherit_metadata(document: Document, chunk_index: int, chunk_text: str) -> dict`：元数据继承 + 图片引用按需分发逻辑（需要 chunk_text 来扫描 `[IMAGE: id]` 占位符）
- **验收标准**：
  - **配置驱动**：通过修改 settings.yaml 中的 splitter 配置（如 chunk_size），产出的 chunk 数量和长度发生相应变化
  - **ID 唯一性**：每个 Chunk 的 ID 在整个文档中唯一
  - **ID 确定性**：同一 Document 对象重复切分产生相同的 Chunk ID 序列
  - **元数据完整性**：Chunk.metadata 包含所有 Document.metadata 字段 + chunk_index 字段
  - **图片分发正确性**：含 `[IMAGE: id]` 占位符的 chunk 其 `metadata["images"]` 仅包含该 chunk 引用的图片子集；不含占位符的 chunk 无 `images` 字段；`metadata["image_refs"]` 列表与占位符一致
  - **溯源链接**：所有 Chunk.source_ref 正确指向父 Document.id
  - **类型契约**：输出的 Chunk 对象符合 `core/types.py` 中的 Chunk 定义（可序列化、字段完整）
- **测试方法**：`pytest -q tests/unit/test_document_chunker.py`（使用 FakeSplitter 隔离测试，无需真实 LLM/外部依赖）。

### C5：Transform 抽象基类 + ChunkRefiner（规则去噪 + LLM 增强）
- **目标**：定义 `BaseTransform`；实现 `ChunkRefiner`：先做规则去噪，再通过LLM进行智能增强，并提供失败降级机制（LLM异常时回退到规则结果，不阻塞 ingestion）。
- **前置条件**（必须准备）：
  - **必须配置LLM**：在 `config/settings.yaml` 中配置可用的LLM（provider/model/api_key）
  - **环境变量**：设置对应的API key环境变量（`OPENAI_API_KEY`/`OLLAMA_BASE_URL`等）
  - **验证目的**：通过真实LLM测试验证配置正确性和refinement效果
- **修改文件**：
  - `src/ingestion/transform/base_transform.py`（新增）
  - `src/ingestion/transform/chunk_refiner.py`（新增）
  - `src/core/trace/trace_context.py`（新增：最小实现，Phase F 完善）
  - `config/prompts/chunk_refinement.txt`（已存在，需验证内容并补充 {text} 占位符）
  - `tests/fixtures/noisy_chunks.json`（新增：8个典型噪声场景）
  - `tests/unit/test_chunk_refiner.py`（新增：27个单元测试）
  - `tests/integration/test_chunk_refiner_llm.py`（新增：真实LLM集成测试）
- **实现类/函数**：
  - `BaseTransform.transform(chunks, trace) -> List[Chunk]`
  - `ChunkRefiner.__init__(settings, llm?, prompt_path?)`
  - `ChunkRefiner.transform(chunks, trace) -> List[Chunk]`
  - `ChunkRefiner._rule_based_refine(text) -> str`（去空白/页眉页脚/格式标记/HTML注释）
  - `ChunkRefiner._llm_refine(text, trace) -> str | None`（可选 LLM 重写，失败返回 None）
  - `ChunkRefiner._load_prompt(prompt_path?)`（从文件加载prompt模板，支持默认fallback）
- **实现流程建议**：
  1. 先创建 `tests/fixtures/noisy_chunks.json`，包含8个典型噪声场景：
     - typical_noise_scenario: 综合噪声（页眉/页脚/空白）
     - ocr_errors: OCR错误文本
     - page_header_footer: 页眉页脚模式
     - excessive_whitespace: 多余空白
     - format_markers: HTML/Markdown标记
     - clean_text: 干净文本（验证不过度清理）
     - code_blocks: 代码块（验证保留内部格式）
     - mixed_noise: 真实混合场景
  2. 创建 `TraceContext` 占位实现（uuid生成trace_id，record_stage存储阶段数据）
  3. 实现 `BaseTransform` 抽象接口
  4. 实现 `ChunkRefiner._rule_based_refine` 规则去噪逻辑（正则匹配+分段处理）
  5. 编写规则模式单元测试（使用 fixtures 断言清洗效果）
  6. 实现 `_llm_refine` 可选增强（读取 prompt、调用 LLM、错误处理）
  7. 编写 LLM 模式单元测试（mock LLM 断言调用与输出）
  8. 编写降级场景测试（LLM 失败时回退到规则结果，标记 metadata）
  9. **编写真实LLM集成测试并执行验证**（必须执行，验证LLM配置）
- **验收标准**：
  - **单元测试（快速反馈循环）**：
    - 规则模式：对 fixtures 噪声样例能正确去噪（连续空白/页眉页脚/格式标记/分隔线）
    - 保留能力：代码块内部格式不被破坏，Markdown结构完整保留
    - LLM 模式：mock LLM 时能正确调用并返回重写结果，metadata 标记 `refined_by: "llm"`
    - 降级行为：LLM 失败时回退到规则结果，metadata 标记 `refined_by: "rule"` 和 fallback 原因
    - 配置开关：通过 `settings.yaml` 的 `ingestion.chunk_refiner.use_llm` 控制行为
    - 异常处理：单个chunk处理异常不影响其他chunk，保留原文
  - **集成测试（验收必须项）**：
    - ✅ **必须验证真实LLM调用成功**：使用前置条件中配置的LLM进行真实refinement
    - ✅ **必须验证输出质量**：LLM refined文本确实更干净（噪声减少、内容保留）
    - ✅ **必须验证降级机制**：无效模型名称时优雅降级到rule-based，不崩溃
    - 说明：这是验证"前置条件中准备的LLM配置是否正确"的必要步骤
- **测试方法**：
  - **阶段1-单元测试（开发中快速迭代）**：
    ```bash
    pytest tests/unit/test_chunk_refiner.py -v
    # ✅ 27个测试全部通过，使用Mock隔离，无需真实API
    ```
  - **阶段2-集成测试（验收必须执行）**：
    ```bash
    # 1. 运行真实LLM集成测试（必须）
    pytest tests/integration/test_chunk_refiner_llm.py -v -s
    # ✅ 验证LLM配置正确，refinement效果符合预期
    # ⚠️ 会产生真实API调用与费用
    
    # 2. Review打印输出，确认精炼质量
    # - 噪声是否被有效去除？
    # - 有效内容是否完整保留？
    # - 降级机制是否正常工作？
    ```
  - **测试分层逻辑**：
    - 单元测试：验证代码逻辑正确
    - 集成测试：验证系统可用性
    - 两者互补，缺一不可

### C6：MetadataEnricher（规则增强 + 可选 LLM 增强 + 降级）
- **目标**：实现元数据增强模块：提供规则增强的默认实现，并重点支持 LLM 增强（配置已就绪，LLM 开关打开）。利用 LLM 对 chunk 进行高质量的 title 生成、summary 摘要和 tags 提取。同时保留失败降级机制，确保不阻塞 ingestion。
- **修改文件**：
  - `src/ingestion/transform/metadata_enricher.py`
  - `tests/unit/test_metadata_enricher_contract.py`
- **验收标准**：
  - 规则模式：作为兜底逻辑，输出 metadata 必须包含 `title/summary/tags`（至少非空）。
  - **LLM 模式（核心）**：在 LLM 打开的情况下，确保真实调用 LLM（或高质量 Mock）并生成语义丰富的 metadata。需验证在有真实 LLM 配置下的连通性与效果。
  - 降级行为：LLM 调用失败时回退到规则模式结果（可在 metadata 标记降级原因，但不抛出致命异常）。
- **测试方法**：`pytest -q tests/unit/test_metadata_enricher_contract.py`，并确保包含开启 LLM 的集成测试用例。

### C7：ImageCaptioner（可选生成 caption + 降级不阻塞）
- **目标**：实现 `image_captioner.py`：当启用 Vision LLM 且存在 image_refs 时生成 caption 并写回 chunk metadata；当禁用/不可用/异常时走降级路径，不阻塞 ingestion。
- **修改文件**：
  - `src/ingestion/transform/image_captioner.py`
  - `config/prompts/image_captioning.txt`（作为默认 prompt 来源；可在测试中注入替代文本）
  - `tests/unit/test_image_captioner_fallback.py`
- **验收标准**：
  - 启用模式：存在 image_refs 时会生成 caption 并写入 metadata（测试中用 mock Vision LLM 断言调用与输出）。
  - 降级模式：当配置禁用或异常时，chunk 保留 image_refs，但不生成 caption 且标记 `has_unprocessed_images`。
- **测试方法**：`pytest -q tests/unit/test_image_captioner_fallback.py`。

### C8：DenseEncoder（依赖 libs.embedding）
- **目标**：实现 `dense_encoder.py`，把 chunks.text 批量送入 `BaseEmbedding`。
- **修改文件**：
  - `src/ingestion/embedding/dense_encoder.py`
  - `tests/unit/test_dense_encoder.py`
- **验收标准**：encoder 输出向量数量与 chunks 数量一致，维度一致。
- **测试方法**：`pytest -q tests/unit/test_dense_encoder.py`。

### C9：SparseEncoder（BM25 统计与输出契约）
- **目标**：实现 `sparse_encoder.py`：对 chunks 建立 BM25 所需统计（可先仅输出 term weights 结构，索引落地下一步做）。
- **修改文件**：
  - `src/ingestion/embedding/sparse_encoder.py`
  - `tests/unit/test_sparse_encoder.py`
- **验收标准**：输出结构可用于 bm25_indexer；对空文本有明确行为。
- **测试方法**：`pytest -q tests/unit/test_sparse_encoder.py`。

### C10：BatchProcessor（批处理编排）
- **目标**：实现 `batch_processor.py`：将 chunks 分 batch，驱动 dense/sparse 编码，记录批次耗时（为 trace 预留）。
- **修改文件**：
  - `src/ingestion/embedding/batch_processor.py`
  - `tests/unit/test_batch_processor.py`
- **验收标准**：batch_size=2 时对 5 chunks 分成 3 批，且顺序稳定。
- **测试方法**：`pytest -q tests/unit/test_batch_processor.py`。

---

**━━━━ 存储阶段分界线：以下任务负责将编码结果持久化 ━━━━**

> **说明**：C8-C10完成了Dense和Sparse的编码工作，C11-C13负责将编码结果存储到不同的后端。
> - **C11 (BM25Indexer)**：处理Sparse编码结果 → 构建倒排索引 → 存储到文件系统
> - **C12 (VectorUpserter)**：处理Dense编码结果 → 生成稳定ID → 存储到向量数据库
> - **C13 (ImageStorage)**：处理图片数据 → 文件存储 + 索引映射

---

### C11：BM25Indexer（倒排索引构建与持久化）
- **目标**：实现 `bm25_indexer.py`：接收 SparseEncoder 的term statistics输出，计算IDF，构建倒排索引，并持久化到 `data/db/bm25/`。
- **核心功能**：
  - 计算 IDF (Inverse Document Frequency)：`IDF(term) = log((N - df + 0.5) / (df + 0.5))`
  - 构建倒排索引结构：`{term: {idf, postings: [{chunk_id, tf, doc_length}]}}`
  - 索引序列化与加载（支持增量更新与重建）
- **修改文件**：
  - `src/ingestion/storage/bm25_indexer.py`
  - `tests/unit/test_bm25_indexer_roundtrip.py`
- **验收标准**：
  - build 后能 load 并对同一语料查询返回稳定 top ids
  - IDF计算准确（可用已知语料对比验证）
  - 支持索引重建与增量更新
- **测试方法**：`pytest -q tests/unit/test_bm25_indexer_roundtrip.py`。
- **备注**：本任务完成Sparse路径的最后一环，为D3 (SparseRetriever) 提供可查询的BM25索引。

### C12：VectorUpserter（向量存储与幂等性保证）
- **目标**：实现 `vector_upserter.py`：接收 DenseEncoder 的向量输出，生成稳定的 `chunk_id`，并调用 VectorStore 进行幂等写入。
- **核心功能**：
  - 生成确定性 chunk_id：`hash(source_path + chunk_index + content_hash[:8])`
  - 调用 `BaseVectorStore.upsert()` 写入向量数据库
  - 保证幂等性：同一内容重复写入不产生重复记录
- **修改文件**：
  - `src/ingestion/storage/vector_upserter.py`
  - `tests/unit/test_vector_upserter_idempotency.py`
- **验收标准**：
  - 同一 chunk 两次 upsert 产生相同 id
  - 内容变更时 id 变更
  - 支持批量 upsert 且保持顺序
- **测试方法**：`pytest -q tests/unit/test_vector_upserter_idempotency.py`。
- **备注**：本任务完成Dense路径的最后一环，为D2 (DenseRetriever) 提供可查询的向量数据库。

### C13：ImageStorage（图片文件存储与索引表契约）
- **目标**：实现 `image_storage.py`：保存图片到 `data/images/{collection}/`，并使用 **SQLite** 记录 image_id→path 映射。
- **修改文件**：
  - `src/ingestion/storage/image_storage.py`
  - `tests/unit/test_image_storage.py`
- **验收标准**：保存后文件存在；查找 image_id 返回正确路径；映射关系持久化在 `data/db/image_index.db`。
- **技术方案**：
  - 复用项目已有的 SQLite 架构模式（参考 `file_integrity.py` 的 `SQLiteIntegrityChecker`）
  - 数据库表结构：
    ```sql
    CREATE TABLE image_index (
        image_id TEXT PRIMARY KEY,
        file_path TEXT NOT NULL,
        collection TEXT,
        doc_hash TEXT,
        page_num INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX idx_collection ON image_index(collection);
    CREATE INDEX idx_doc_hash ON image_index(doc_hash);
    ```
  - 提供并发安全访问（WAL 模式）
  - 支持按 collection 批量查询
- **测试方法**：`pytest -q tests/unit/test_image_storage.py`。

### C14：Pipeline 编排（MVP 串起来）
- **目标**：实现 `pipeline.py`：串行执行（integrity→load→split→transform→encode→store），并对失败步骤做清晰异常。
- **修改文件**：
  - `src/ingestion/pipeline.py`
  - `tests/integration/test_ingestion_pipeline.py`
- **测试数据**：
  - **主测试文档**：`tests/fixtures/sample_documents/complex_technical_doc.pdf`
    - 8章节技术文档（~21KB）
    - 包含3张嵌入图片（需测试图片提取和描述）
    - 包含5个表格（测试表格内容解析）
    - 多页多段落（测试完整分块流程）
  - **辅助测试**：`tests/fixtures/sample_documents/simple.pdf`（简单场景回归）
- **验收标准**：
  - 对 `complex_technical_doc.pdf` 跑完整 pipeline，成功输出：
    - 向量索引文件到 ChromaDB
    - BM25 索引文件到 `data/db/bm25/`
    - 提取的图片到 `data/images/` (SHA256命名)
  - Pipeline 日志清晰展示各阶段进度
  - 失败步骤抛出明确异常信息
- **测试方法**：`pytest -v tests/integration/test_ingestion_pipeline.py`。

### C15：脚本入口 ingest.py（离线可用）
- **目标**：实现 `scripts/ingest.py`，支持 `--collection`、`--path`、`--force`，并调用 pipeline。
- **修改文件**：
  - `scripts/ingest.py`
  - `tests/e2e/test_data_ingestion.py`
- **验收标准**：命令行可运行并在 `data/db` 产生产物；重复运行在未变更时跳过。
- **测试方法**：`pytest -q tests/e2e/test_data_ingestion.py`（尽量用临时目录）。

---

## 阶段 D：Retrieval MVP（目标：能 query 并返回 Top-K chunks）

### D1：QueryProcessor（关键词提取 + filters 结构）
- **目标**：实现 `query_processor.py`：关键词提取（先规则/分词），并解析通用 filters 结构（可空实现）。
- **修改文件**：
  - `src/core/query_engine/query_processor.py`
  - `tests/unit/test_query_processor.py`
- **验收标准**：对输入 query 输出 `keywords` 非空（可根据停用词策略），filters 为 dict。
- **测试方法**：`pytest -q tests/unit/test_query_processor.py`。

### D2：DenseRetriever（调用 VectorStore.query）
- **目标**：实现 `dense_retriever.py`，组合 `EmbeddingClient`（query 向量化）+ `VectorStore`（向量检索），完成语义召回。
- **前置任务**：
  1. 需先在 `src/core/types.py` 中定义 `RetrievalResult` 类型（包含 `chunk_id`, `score`, `text`, `metadata` 字段）
  2. 需确认 ChromaStore.query() 返回结果包含 text（当前存储在 documents 字段，需补充返回）
- **修改文件**：
  - `src/core/types.py`（新增 `RetrievalResult` 类型）
  - `src/libs/vector_store/chroma_store.py`（修复：query 返回结果需包含 text 字段）
  - `src/core/query_engine/dense_retriever.py`
  - `tests/unit/test_dense_retriever.py`
- **实现类/函数**：
  - `RetrievalResult` dataclass：`chunk_id: str`, `score: float`, `text: str`, `metadata: Dict`
  - `DenseRetriever.__init__(settings, embedding_client?, vector_store?)`：支持依赖注入用于测试
  - `DenseRetriever.retrieve(query: str, top_k: int, filters?: dict, trace?) -> List[RetrievalResult]`
  - 内部流程：`query → embedding_client.embed([query]) → vector_store.query(vector, top_k, filters) → 从返回结果提取 text → 规范化结果`
- **验收标准**：
  - `RetrievalResult` 类型已定义并可序列化
  - ChromaStore.query() 返回结果包含 `text` 字段
  - 对输入 query 能生成 embedding 并调用 VectorStore 检索
  - 返回结果包含 `chunk_id`、`score`、`text`、`metadata`
  - mock EmbeddingClient 和 VectorStore 时能正确编排调用
- **测试方法**：`pytest -q tests/unit/test_dense_retriever.py`（mock embedding + vector store）。

### D3：SparseRetriever（BM25 查询）
- **目标**：实现 `sparse_retriever.py`：从 `data/db/bm25/` 载入索引并查询。
- **前置任务**：需在 `BaseVectorStore` 和 `ChromaStore` 中添加 `get_by_ids()` 方法，用于根据 chunk_id 批量获取 text 和 metadata
- **修改文件**：
  - `src/libs/vector_store/base_vector_store.py`（新增 `get_by_ids()` 抽象方法）
  - `src/libs/vector_store/chroma_store.py`（实现 `get_by_ids()` 方法）
  - `src/core/query_engine/sparse_retriever.py`
  - `tests/unit/test_sparse_retriever.py`
- **实现类/函数**：
  - `BaseVectorStore.get_by_ids(ids: List[str]) -> List[Dict]`：根据 ID 批量获取记录
  - `ChromaStore.get_by_ids(ids: List[str]) -> List[Dict]`：调用 ChromaDB 的 get 方法
  - `SparseRetriever.__init__(settings, bm25_indexer?, vector_store?)`：支持依赖注入用于测试
  - `SparseRetriever.retrieve(keywords: List[str], top_k: int, trace?) -> List[RetrievalResult]`
  - 内部流程：
    1. `keywords → bm25_indexer.query(keywords, top_k) → [{chunk_id, score}]`
    2. `chunk_ids → vector_store.get_by_ids(chunk_ids) → [{id, text, metadata}]`
    3. 合并 score 与 text/metadata，组装为 `RetrievalResult` 列表
  - 注意：keywords 来自 `QueryProcessor.process()` 的 `ProcessedQuery.keywords`
- **验收标准**：
  - `BaseVectorStore.get_by_ids()` 和 `ChromaStore.get_by_ids()` 已实现
  - 对已构建索引的 fixtures 语料，关键词检索命中预期 chunk_id
  - 返回结果包含完整的 text 和 metadata
- **测试方法**：`pytest -q tests/unit/test_sparse_retriever.py`。

### D4：Fusion（RRF 实现）
- **目标**：实现 `fusion.py`：RRF 融合 dense/sparse 排名并输出统一排序。
- **修改文件**：
  - `src/core/query_engine/fusion.py`
  - `tests/unit/test_fusion_rrf.py`
- **验收标准**：对构造的排名输入输出 deterministic；k 参数可配置。
- **测试方法**：`pytest -q tests/unit/test_fusion_rrf.py`。

### D5：HybridSearch 编排
- **目标**：实现 `hybrid_search.py`：编排 Dense + Sparse + Fusion 的完整混合检索流程，并集成 Metadata 过滤逻辑。
- **前置依赖**：D1（QueryProcessor）、D2（DenseRetriever）、D3（SparseRetriever）、D4（Fusion）
- **修改文件**：
  - `src/core/query_engine/hybrid_search.py`
  - `tests/integration/test_hybrid_search.py`
- **实现类/函数**：
  - `HybridSearch.__init__(settings, query_processor, dense_retriever, sparse_retriever, fusion)`
  - `HybridSearch.search(query: str, top_k: int, filters?: dict, trace?) -> List[RetrievalResult]`
  - `HybridSearch._apply_metadata_filters(candidates, filters) -> List[RetrievalResult]`：后置过滤兜底
  - 内部流程：`query_processor.process() → 并行(dense.retrieve + sparse.retrieve) → fusion.fuse() → metadata_filter → Top-K`
- **验收标准**：
  - 对 fixtures 数据，能返回 Top-K（包含 chunk 文本与 metadata）
  - 支持 filters 参数（如 `collection`、`doc_type`）进行过滤
  - Dense/Sparse 任一路径失败时能降级到单路结果
- **测试方法**：`pytest -q tests/integration/test_hybrid_search.py`。

### D6：Reranker（Core 层编排 + fallback）
- **目标**：实现 `core/query_engine/reranker.py`：接入 `libs.reranker` 后端，失败/超时回退 fusion 排名。
- **修改文件**：
  - `src/core/query_engine/reranker.py`
  - `config/prompts/rerank.txt`（仅当启用 LLM Rerank 后端时使用）
  - `tests/unit/test_reranker_fallback.py`
- **验收标准**：模拟后端异常时不影响最终返回，且标记 fallback=true。
- **测试方法**：`pytest -q tests/unit/test_reranker_fallback.py`。

### D7：脚本入口 query.py（查询可用）
- **目标**：实现 `scripts/query.py`，作为在线查询的命令行入口，调用完整的 HybridSearch + Reranker 流程并输出检索结果。
- **前置依赖**：D5（HybridSearch）、D6（Reranker）
- **修改文件**：
  - `scripts/query.py`
- **实现功能**：
  - **参数支持**：
    - `--query "问题"`：必填，查询文本
    - `--top-k 10`：可选，返回结果数量（默认 10）
    - `--collection xxx`：可选，限定检索集合
    - `--verbose`：可选，显示各阶段中间结果
    - `--no-rerank`：可选，跳过 Reranker 阶段
  - **输出内容**：
    - 默认模式：Top-K 结果（序号、score、文本摘要、来源文件、页码）
    - Verbose 模式：额外显示 Dense 召回结果、Sparse 召回结果、Fusion 结果、Rerank 结果
  - **内部流程**：
    1. 加载配置 `Settings`
    2. 初始化组件（EmbeddingClient、VectorStore、BM25Indexer、Reranker）
    3. 创建 `QueryProcessor`、`DenseRetriever`、`SparseRetriever`、`HybridSearch` 实例
    4. 调用 `HybridSearch.search()` 获取候选结果
    5. 调用 `Reranker.rerank()` 进行精排（除非 `--no-rerank`）
    6. 格式化输出结果
- **验收标准**：
  - 命令行可运行：`python scripts/query.py --query "如何配置 Azure？"`
  - 返回格式化的 Top-K 检索结果
  - `--verbose` 模式显示各阶段中间结果（便于调试）
  - 无数据时返回友好提示（如"未找到相关文档，请先运行 ingest.py 摄取数据"）
- **测试方法**：手动运行 `python scripts/query.py --query "测试查询" --verbose`（依赖已摄取的数据）。
- **与 MCP Tool 的关系**：
  - `scripts/query.py` 是开发调试用的命令行工具
  - `E3 query_knowledge_hub` 是生产环境的 MCP Tool
  - 两者共享 Core 层逻辑（HybridSearch + Reranker），但入口和输出格式不同

---

## 阶段 E：MCP Server 层与 Tools（目标：对外可用的 MCP tools）

### E1：MCP Server 入口与 Stdio 约束
- **目标**：实现 `mcp_server/server.py`：遵循"stdout 只输出 MCP 消息，日志到 stderr"。
- **修改文件**：
  - `src/mcp_server/server.py`
  - `tests/integration/test_mcp_server.py`
- **验收标准**：启动 server 能完成 initialize；stderr 有日志但 stdout 不污染。
- **测试方法**：`pytest -q tests/integration/test_mcp_server.py`（子进程方式）。

### E2：Protocol Handler 协议解析与能力协商
- **目标**：实现 `mcp_server/protocol_handler.py`：封装 JSON-RPC 2.0 协议解析，处理 `initialize`、`tools/list`、`tools/call` 三类核心方法，并实现规范的错误处理。
- **修改文件**：
  - `src/mcp_server/protocol_handler.py`
  - `tests/unit/test_protocol_handler.py`
- **实现要点**：
  - **ProtocolHandler 类**：
    - `handle_initialize(params)` → 返回 server capabilities（支持的 tools 列表、版本信息）
    - `handle_tools_list()` → 返回已注册的 tool schema（name, description, inputSchema）
    - `handle_tools_call(name, arguments)` → 路由到具体 tool 执行，捕获异常并转换为 JSON-RPC error
  - **错误码规范**：遵循 JSON-RPC 2.0（-32600 Invalid Request, -32601 Method not found, -32602 Invalid params, -32603 Internal error）
  - **能力协商**：在 `initialize` 响应中声明 `capabilities.tools`
- **验收标准**：
  - 发送 `initialize` 请求能返回正确的 `serverInfo` 和 `capabilities`
  - 发送 `tools/list` 能返回已注册 tools 的 schema
  - 发送 `tools/call` 能正确路由并返回结果或规范错误
  - **错误处理**：无效方法返回 -32601，参数错误返回 -32602，内部异常返回 -32603 且不泄露堆栈
- **测试方法**：`pytest -q tests/unit/test_protocol_handler.py`。

### E3：实现 tool：query_knowledge_hub
- **目标**：实现 `tools/query_knowledge_hub.py`：调用 HybridSearch + Reranker，构建带引用的响应，返回 Markdown + structured citations。
- **前置依赖**：D5（HybridSearch）、D6（Reranker）、E1（Server）、E2（Protocol Handler）
- **修改文件**：
  - `src/mcp_server/tools/query_knowledge_hub.py`
  - `src/core/response/response_builder.py`（新增：构建 MCP 响应格式）
  - `src/core/response/citation_generator.py`（新增：生成引用信息）
  - `tests/unit/test_response_builder.py`（新增）
  - `tests/integration/test_mcp_server.py`（补用例）
- **实现类/函数**：
  - `ResponseBuilder.build(retrieval_results, query) -> MCPResponse`：构建 MCP 格式响应
  - `CitationGenerator.generate(retrieval_results) -> List[Citation]`：生成引用列表
  - `query_knowledge_hub(query, top_k?, collection?) -> MCPToolResult`：Tool 入口函数
- **验收标准**：
  - tool 返回 `content[0]` 为可读 Markdown（含 `[1]`、`[2]` 等引用标注）
  - `structuredContent.citations` 包含 `source`/`page`/`chunk_id`/`score` 字段
  - 无结果时返回友好提示而非空数组
- **测试方法**：`pytest -q tests/integration/test_mcp_server.py -k query_knowledge_hub`。

### E4：实现 tool：list_collections
- **目标**：实现 `tools/list_collections.py`：列出 `data/documents/` 下集合并附带统计（可延后到下一步）。
- **修改文件**：
  - `src/mcp_server/tools/list_collections.py`
  - `tests/unit/test_list_collections.py`
- **验收标准**：对 fixtures 中的目录结构能返回集合名列表。
- **测试方法**：`pytest -q tests/unit/test_list_collections.py`。

### E5：实现 tool：get_document_summary
- **目标**：实现 `tools/get_document_summary.py`：按 doc_id 返回 title/summary/tags（可先从 metadata/缓存取）。
- **修改文件**：
  - `src/mcp_server/tools/get_document_summary.py`
  - `tests/unit/test_get_document_summary.py`
- **验收标准**：对不存在 doc_id 返回规范错误；存在时返回结构化信息。
- **测试方法**：`pytest -q tests/unit/test_get_document_summary.py`。

### E6：多模态返回组装（Text + Image）
- **目标**：实现 `multimodal_assembler.py`：命中 chunk 含 image_refs 时读取图片并 base64 返回 ImageContent。
- **修改文件**：
  - `src/core/response/multimodal_assembler.py`
  - `tests/integration/test_mcp_server.py`（补图像返回用例）
- **验收标准**：返回 content 中包含 image type，mimeType 正确，data 为 base64 字符串。
- **测试方法**：`pytest -q tests/integration/test_mcp_server.py -k image`。

---

## 阶段 F：Trace 基础设施与打点（目标：Ingestion + Query 双链路可追踪）

### F1：TraceContext 增强（finish + 耗时统计 + trace_type）
- **目标**：增强已有的 `TraceContext`（C5 已实现基础版），添加 `finish()` 方法、耗时统计、`trace_type` 字段（区分 query/ingestion）、`to_dict()` 序列化功能。
- **修改文件**：
  - `src/core/trace/trace_context.py`（增强：添加 trace_type/finish/elapsed_ms/to_dict）
  - `src/core/trace/trace_collector.py`（新增：收集并持久化 trace）
  - `tests/unit/test_trace_context.py`（补充 finish/to_dict 相关测试）
- **实现类/函数**：
  - `TraceContext.__init__(trace_type: str = "query")`：支持 `"query"` 或 `"ingestion"` 类型
  - `TraceContext.finish() -> None`：标记 trace 结束，计算总耗时
  - `TraceContext.elapsed_ms(stage_name?) -> float`：获取指定阶段或总耗时
  - `TraceContext.to_dict() -> dict`：序列化为可 JSON 输出的字典（含 trace_type）
  - `TraceCollector.collect(trace: TraceContext) -> None`：收集 trace 并触发持久化
- **验收标准**：
  - `record_stage` 追加阶段数据（已有）
  - `finish()` 后 `to_dict()` 输出包含 `trace_id`、`trace_type`、`started_at`、`finished_at`、`total_elapsed_ms`、`stages`
  - 输出 dict 可直接 `json.dumps()` 序列化
- **测试方法**：`pytest -q tests/unit/test_trace_context.py`。


### F2：结构化日志 logger（JSON Lines）
- **目标**：增强 `observability/logger.py`，支持 JSON Lines 格式输出，并实现 trace 持久化到 `logs/traces.jsonl`。
- **修改文件**：
  - `src/observability/logger.py`（增强：添加 JSONFormatter + FileHandler）
  - `tests/unit/test_jsonl_logger.py`
- **实现类/函数**：
  - `JSONFormatter`：自定义 logging Formatter，输出 JSON 格式
  - `get_trace_logger() -> logging.Logger`：获取配置了 JSON Lines 输出的 logger
  - `write_trace(trace_dict: dict) -> None`：将 trace 字典写入 `logs/traces.jsonl`
- **与 F1 的分工**：
  - F1 负责 TraceContext 的数据结构（含 `trace_type`）和 `finish()` 方法
  - F2 负责将 `trace.to_dict()` 的结果持久化到文件
- **验收标准**：写入一条 trace 后文件新增一行合法 JSON，包含 `trace_type` 字段。
- **测试方法**：`pytest -q tests/unit/test_jsonl_logger.py`。

### F3：在 Query 链路打点
- **目标**：在 HybridSearch/Rerank 中注入 TraceContext（`trace_type="query"`），利用 B 阶段抽象接口中预留的 `trace` 参数，显式调用 `trace.record_stage()` 记录各阶段数据。
- **前置依赖**：D5（HybridSearch）、D6（Reranker）、F1（TraceContext 增强）、F2（结构化日志）
- **修改文件**：
  - `src/core/query_engine/hybrid_search.py`（增加 trace 记录：dense/sparse/fusion 阶段）
  - `src/core/query_engine/reranker.py`（增加 trace 记录：rerank 阶段）
  - `tests/integration/test_hybrid_search.py`（断言 trace 中存在各阶段）
- **说明**：B 阶段的接口已预留 `trace: TraceContext | None = None` 参数，本任务负责在调用时传入实际的 TraceContext 实例，并在各阶段记录 `method`/`provider`/`details` 字段。
- **验收标准**：
  - 一次查询生成 trace，包含 `query_processing`/`dense_retrieval`/`sparse_retrieval`/`fusion`/`rerank` 阶段
  - 每个阶段记录 `elapsed_ms` 耗时字段和 `method` 字段
  - `trace.to_dict()` 中 `trace_type == "query"`
- **测试方法**：`pytest -q tests/integration/test_hybrid_search.py`。

### F4：在 Ingestion 链路打点
- **目标**：在 IngestionPipeline 中注入 TraceContext（`trace_type="ingestion"`），记录各摄取阶段的处理数据。
- **前置依赖**：C5（Pipeline）、F1（TraceContext 增强）、F2（结构化日志）
- **修改文件**：
  - `src/ingestion/pipeline.py`（增加 trace 传递：load/split/transform/embed/upsert 阶段）
  - `tests/integration/test_ingestion_pipeline.py`（断言 trace 中存在各阶段）
- **验收标准**：
  - 一次摄取生成 trace，包含 `load`/`split`/`transform`/`embed`/`upsert` 阶段
  - 每个阶段记录 `elapsed_ms`、`method`（如 markitdown/recursive/chroma）和处理详情
  - `trace.to_dict()` 中 `trace_type == "ingestion"`
- **测试方法**：`pytest -q tests/integration/test_ingestion_pipeline.py`。

### F5：Pipeline 进度回调 (on_progress)
- **目标**：在 `IngestionPipeline.run()` 方法中新增可选 `on_progress` 回调参数，支持外部实时获取处理进度。
- **前置依赖**：F4（Ingestion 打点）
- **修改文件**：
  - `src/ingestion/pipeline.py`（在各阶段调用 `on_progress(stage_name, current, total)`）
  - `tests/unit/test_pipeline_progress.py`（新增：验证回调被正确调用）
- **实现要点**：
  - 回调签名：`on_progress(stage_name: str, current: int, total: int)`
  - `on_progress` 为 `None` 时完全不影响现有行为
  - 各阶段在处理每个 batch 或完成时触发回调
- **验收标准**：Pipeline 运行时传入 mock 回调，断言各阶段均被调用且参数正确。
- **测试方法**：`pytest -q tests/unit/test_pipeline_progress.py`。

---

## 阶段 G：可视化管理平台 Dashboard（目标：六页面完整可视化管理）

### G1：Dashboard 基础架构与系统总览页
- **目标**：搭建 Streamlit 多页面应用框架，实现系统总览页面（展示组件配置与数据统计）。
- **前置依赖**：F1-F2（Trace 基础设施）
- **修改文件**：
  - `src/observability/dashboard/app.py`（重写：多页面导航架构）
  - `src/observability/dashboard/pages/overview.py`（新增：系统总览页面）
  - `src/observability/dashboard/services/config_service.py`（新增：配置读取服务）
  - `scripts/start_dashboard.py`（新增：Dashboard 启动脚本）
- **实现要点**：
  - `app.py` 使用 `st.navigation()` 注册六个页面（未完成的页面显示占位提示）
  - Overview 页面：读取 `Settings` 展示组件卡片，调用 `ChromaStore.get_collection_stats()` 展示数据统计
  - `ConfigService`：封装 Settings 读取，格式化组件配置信息
- **验收标准**：`streamlit run src/observability/dashboard/app.py` 可启动，总览页展示当前配置信息。
- **测试方法**：手动运行 `python scripts/start_dashboard.py` 并验证页面渲染。

### G2：DocumentManager 实现
- **目标**：实现 `src/ingestion/document_manager.py`：跨存储的文档生命周期管理（list/delete/stats）。
- **前置依赖**：C5（Pipeline + 各存储模块已就绪）
- **修改文件**：
  - `src/ingestion/document_manager.py`（新增）
  - `src/libs/vector_store/chroma_store.py`（增强：添加 `delete_by_metadata`）
  - `src/ingestion/storage/bm25_indexer.py`（增强：添加 `remove_document`）
  - `src/libs/loader/file_integrity.py`（增强：添加 `remove_record` + `list_processed`）
  - `tests/unit/test_document_manager.py`（新增）
- **实现类/函数**：
  - `DocumentManager.__init__(chroma_store, bm25_indexer, image_storage, file_integrity)`
  - `DocumentManager.list_documents(collection?) -> List[DocumentInfo]`
  - `DocumentManager.get_document_detail(doc_id) -> DocumentDetail`
  - `DocumentManager.delete_document(source_path, collection) -> DeleteResult`
  - `DocumentManager.get_collection_stats(collection?) -> CollectionStats`
- **验收标准**：
  - `list_documents` 返回已摄入文档列表（source、chunk 数、图片数）
  - `delete_document` 协调删除 Chroma + BM25 + ImageStorage + FileIntegrity 四个存储
  - 删除后再次 list 不包含已删除文档
- **测试方法**：`pytest -q tests/unit/test_document_manager.py`。

### G3：数据浏览器页面
- **目标**：实现 Dashboard 数据浏览器页面（查看文档列表、Chunk 详情、图片预览）。
- **前置依赖**：G1（Dashboard 架构）、G2（DocumentManager）
- **修改文件**：
  - `src/observability/dashboard/pages/data_browser.py`（新增）
  - `src/observability/dashboard/services/data_service.py`（新增：封装 ChromaStore/ImageStorage 读取）
- **实现要点**：
  - 文档列表视图：展示 source_path、集合、chunk 数、摄入时间；支持集合筛选
  - Chunk 详情视图：点击文档展开所有 chunk，显示内容（可折叠）、metadata 字段、关联图片
  - `DataService`：封装 `ChromaStore.get_by_metadata()` 和 `ImageStorage.list_images()` 调用
- **验收标准**：可在 Dashboard 中浏览已摄入的文档和 chunk 详情。
- **测试方法**：手动验证（先 ingest 样例数据，再在 Dashboard 浏览）。

### G4：Ingestion 管理页面
- **目标**：实现 Dashboard Ingestion 管理页面（文件上传触发摄取、进度展示、文档删除）。
- **前置依赖**：G2（DocumentManager）、G3（DataService）、F5（on_progress 回调）
- **修改文件**：
  - `src/observability/dashboard/pages/ingestion_manager.py`（新增）
- **实现要点**：
  - 文件上传：`st.file_uploader` 选择文件 + 集合选择
  - 摄取触发：调用 `IngestionPipeline.run(on_progress=...)` + `st.progress()` 实时进度
  - 文档删除：在文档列表中提供删除按钮，调用 `DocumentManager.delete_document()`
- **验收标准**：可在 Dashboard 中上传文件触发摄取、看到实时进度条、删除已有文档。
- **测试方法**：手动验证（上传 PDF → 观察进度 → 删除 → 确认已移除）。

### G5：Ingestion 追踪页面
- **目标**：实现 Dashboard Ingestion 追踪页面（摄取历史列表、阶段耗时瀑布图）。
- **前置依赖**：F4（Ingestion 打点）、G1（Dashboard 架构）
- **修改文件**：
  - `src/observability/dashboard/pages/ingestion_traces.py`（新增）
  - `src/observability/dashboard/services/trace_service.py`（新增：解析 traces.jsonl）
- **实现要点**：
  - 历史列表：按时间倒序展示 `trace_type == "ingestion"` 记录
  - 详情页：横向条形图展示 load/split/transform/embed/upsert 耗时分布
  - `TraceService`：读取 `logs/traces.jsonl`，解析为 Trace 对象列表
- **验收标准**：执行 ingest 后，Dashboard 显示对应的追踪记录与耗时瀑布图。
- **测试方法**：手动验证（先 ingest → 打开 Dashboard → 查看追踪）。

### G6：Query 追踪页面
- **目标**：实现 Dashboard Query 追踪页面（查询历史、Dense/Sparse 对比、Rerank 变化）。
- **前置依赖**：F3（Query 打点）、G1（Dashboard 架构）、G5（TraceService 已实现）
- **修改文件**：
  - `src/observability/dashboard/pages/query_traces.py`（新增）
- **实现要点**：
  - 历史列表：按时间倒序展示 `trace_type == "query"` 记录，支持按 Query 关键词搜索
  - 详情页：耗时瀑布图 + Dense vs Sparse 并列对比 + Rerank 前后排名变化
- **验收标准**：执行 query 后，Dashboard 显示查询追踪详情与各阶段对比。
- **测试方法**：手动验证（先 query → 打开 Dashboard → 查看追踪）。

---

## 阶段 H：评估体系（目标：可插拔评估 + 可量化回归）

### H1：RagasEvaluator 实现
- **目标**：实现 `ragas_evaluator.py`：封装 Ragas 框架，实现 `BaseEvaluator` 接口。
- **修改文件**：
  - `src/observability/evaluation/ragas_evaluator.py`（新增）
  - `src/libs/evaluator/evaluator_factory.py`（注册 ragas provider）
  - `tests/unit/test_ragas_evaluator.py`（新增）
- **实现类/函数**：
  - `RagasEvaluator(BaseEvaluator)`：实现 `evaluate()` 方法
  - 支持指标：Faithfulness, Answer Relevancy, Context Precision
  - 优雅降级：Ragas 未安装时抛出明确的 `ImportError` 提示
- **验收标准**：mock LLM 环境下，`evaluate()` 返回包含 faithfulness/answer_relevancy 的 metrics 字典。
- **测试方法**：`pytest -q tests/unit/test_ragas_evaluator.py`。

### H2：CompositeEvaluator 实现
- **目标**：实现 `composite_evaluator.py`：组合多个 Evaluator 并行执行，汇总结果。
- **修改文件**：
  - `src/observability/evaluation/composite_evaluator.py`（新增）
  - `tests/unit/test_composite_evaluator.py`（新增）
- **实现类/函数**：
  - `CompositeEvaluator.__init__(evaluators: List[BaseEvaluator])`
  - `CompositeEvaluator.evaluate() -> dict`：并行执行所有 evaluator，合并 metrics
  - 配置驱动：`evaluation.backends: [ragas, custom]` → 工厂自动组合
- **验收标准**：配置两个 evaluator 时，返回的 metrics 包含两者的指标。
- **测试方法**：`pytest -q tests/unit/test_composite_evaluator.py`。

### H3：EvalRunner + Golden Test Set
- **目标**：实现 `eval_runner.py`：读取 `tests/fixtures/golden_test_set.json`，跑 retrieval 并产出 metrics。
- **前置依赖**：D5（HybridSearch）、H1-H2（评估器）
- **修改文件**：
  - `src/observability/evaluation/eval_runner.py`（新增）
  - `tests/fixtures/golden_test_set.json`（新增：黄金测试集）
  - `scripts/evaluate.py`（新增：评估运行脚本）
- **实现类/函数**：
  - `EvalRunner.__init__(settings, hybrid_search, evaluator)`
  - `EvalRunner.run(test_set_path) -> EvalReport`：运行评估并返回报告
  - `EvalReport`：包含 hit_rate, mrr, 各 query 结果详情
- **golden_test_set.json 格式**：
  ```json
  {
    "test_cases": [
      {
        "query": "如何配置 Azure OpenAI？",
        "expected_chunk_ids": ["chunk_abc_001", "chunk_abc_002"],
        "expected_sources": ["config_guide.pdf"]
      }
    ]
  }
  ```
- **验收标准**：`python scripts/evaluate.py` 可运行，输出 metrics。
- **测试方法**：`pytest -q tests/integration/test_hybrid_search.py` 或 `python scripts/evaluate.py`。

### H4：评估面板页面
- **目标**：实现 Dashboard 评估面板页面（运行评估、查看指标、历史对比）。
- **前置依赖**：H3（EvalRunner）、G1（Dashboard 架构）
- **修改文件**：
  - `src/observability/dashboard/pages/evaluation_panel.py`（实现：替换占位提示）
- **实现要点**：
  - 选择评估后端与 golden test set
  - 点击运行，展示评估结果（hit_rate、mrr、各 query 明细）
  - 可选：历史评估结果对比图
- **验收标准**：可在 Dashboard 中运行评估并查看指标。
- **测试方法**：手动验证。

### H5：Recall 回归测试（E2E）
- **目标**：实现 `tests/e2e/test_recall.py`：基于 golden set 做最小召回阈值（例如 hit@k）。
- **前置依赖**：H3（EvalRunner + golden_test_set）
- **修改文件**：
  - `tests/e2e/test_recall.py`（新增）
  - `tests/fixtures/golden_test_set.json`（补齐若干条）
- **验收标准**：hit@k 达到阈值（阈值写死在测试里，便于回归）。
- **测试方法**：`pytest -q tests/e2e/test_recall.py`。

---

## 阶段 I：端到端验收与文档收口（目标：开箱即用的"可复现"工程）

### I1：E2E：MCP Client 侧调用模拟
- **目标**：实现 `tests/e2e/test_mcp_client.py`：以子进程启动 server，模拟 tools/list + tools/call。
- **修改文件**：
  - `tests/e2e/test_mcp_client.py`
- **验收标准**：完整走通 query_knowledge_hub 并返回 citations。
- **测试方法**：`pytest -q tests/e2e/test_mcp_client.py`。

### I2：E2E：Dashboard 冒烟测试
- **目标**：验证 Dashboard 各页面在有数据时可正常渲染、无 Python 异常。
- **修改文件**：
  - `tests/e2e/test_dashboard_smoke.py`（新增）
- **实现要点**：
  - 使用 Streamlit 的 `AppTest` 框架进行自动化冒烟测试
  - 验证 6 个页面均可加载、不抛异常
- **验收标准**：所有页面冒烟测试通过。
- **测试方法**：`pytest -q tests/e2e/test_dashboard_smoke.py`。

### I3：完善 README（运行说明 + 测试说明 + MCP 配置 + Dashboard 使用）
- **目标**：让新用户能在 10 分钟内跑通 ingest + query + dashboard + tests，并能在 Copilot/Claude 中使用。
- **修改文件**：
  - `README.md`
- **验收标准**：README 包含以下章节：
  - **快速开始**：安装依赖、配置 API Key、运行首次摄取
  - **配置说明**：`settings.yaml` 各字段含义
  - **MCP 配置示例**：GitHub Copilot `mcp.json` 与 Claude Desktop `claude_desktop_config.json`
  - **Dashboard 使用指南**：启动命令、各页面功能说明、截图示例
  - **运行测试**：单元测试、集成测试、E2E 测试命令
  - **常见问题**：API Key 配置、依赖安装、连接问题排查
- **测试方法**：按 README 手动走一遍。

### I4：清理接口一致性（契约测试补齐）
- **目标**：为关键抽象（VectorStore / Reranker / Evaluator / DocumentManager）补齐契约测试。
- **修改文件**：
  - `tests/unit/test_vector_store_contract.py`（补齐 delete_by_metadata 边界）
  - `tests/unit/test_reranker_factory.py`（补齐边界）
  - `tests/unit/test_custom_evaluator.py`（补齐边界）
- **验收标准**：`pytest -q` 全绿，且 contract tests 覆盖主要输入输出形状。
- **测试方法**：`pytest -q`。

### I5：全链路 E2E 验收
- **目标**：执行完整的端到端验收流程：ingest → query via MCP → Dashboard 可视化 → evaluate。
- **修改文件**：无新文件，验收已有功能
- **验收标准**：
  - `python scripts/ingest.py --path tests/fixtures/sample_documents/ --collection test` 成功
  - `python scripts/query.py --query "测试查询" --verbose` 返回结果
  - Dashboard 可展示摄取与查询追踪
  - `python scripts/evaluate.py` 输出评估指标
- **测试方法**：手动全链路走通 + `pytest -q` 全量测试。

---

### 交付里程碑（建议）

- **M1（完成阶段 A+B）**：工程可测 + 可插拔抽象层就绪，后续实现可并行推进。
- **M2（完成阶段 C）**：离线摄取链路可用，能构建本地索引。
- **M3（完成阶段 D+E）**：在线查询 + MCP tools 可用，可在 Copilot/Claude 中调用。
- **M4（完成阶段 F）**：Ingestion + Query 双链路可追踪，JSON Lines 持久化。
- **M5（完成阶段 G）**：六页面可视化管理平台就绪（评估面板为占位），数据可浏览、可管理、链路可追踪。
- **M6（完成阶段 H+I）**：评估体系完整 + E2E 验收通过 + 文档完善，形成"面试/教学/演示"可复现项目。



## 7. 可扩展性与未来展望

### 7.1 云端部署与后端架构学习
虽然当前阶段我们主要采用“本地运行”模式，但本项目的架构设计完全支持向云端迁移。这也是一个极佳的学习后端工程化的切入点。
- **Server 容器化**：计划编写 Dockerfile，将 MCP Server 打包为容器。这让我们有机会深入理解 Python 环境隔离、依赖管理以及 Docker 的最佳实践。
- **云端接入**：未来可以将 Server 部署至 Azure Container Apps 或 AWS Lambda。
    - **挑战与学习点**：处理网络延时、配置 API Gateway、增加 AuthN/AuthZ 鉴权机制（保护私有数据不被公开访问）。
- **多租户与并发**：从单用户本地服务转变为支持团队共享的服务。
    - **学习点**：在 Chroma 中实现 Namespace 隔离、处理并发请求锁、优化 embedding 缓存策略。

### 7.2 业务深耕：从"通用"到"垂直" (Vertical Domain Adaptation)
RAG 系统的上限取决于其对特定业务数据的理解深度。未来的核心扩展方向是将通用的技术框架与具体的业务场景深度结合。在将本项目应用到实际生产环境时，识别并解决以下“最后一公里”的难题，将是提升系统价值的关键：

- **多源异构数据的复杂适配**：
    - 现实业务中不仅有 PDF，还大量存在 PPTX, DOCX, XLSX 甚至 HTML 数据。
    - **挑战**：如何处理不同格式的特有语义？例如 PPT 中的演讲者备注往往比正文更关键，Excel 中的公式逻辑与跨行关联如何保留？目前的通用处理方式容易丢失这些“隐性知识”，未来需要针对每种格式探索更深度的解析能力。

- **复杂结构化数据的精确理解**：
    - 简单的文本切分（Chunking）在处理表格、层级列表时往往会破坏语义。
    - **挑战**：
        - **表格理解**：如何处理跨页长表格、合并单元格以及含有复杂表头的财务报表？如果切分不当，检索时只能找到数字却不知道对应的列名（指标含义）。
        - **上下文断裂**：当一个完整的逻辑段落（如合同条款）被切分到两个 chunk 时，如何保证检索其中一段时能感知到整体的上下文约束？

- **业务逻辑驱动的生成控制**：
    - 仅仅根据“相似度”召回文档在企业级场景中往往不够。
    - **挑战**：
        - **时效性与版本管理**：当知识库中同时存在“2023版”和“2024版”规章时，如何确保系统不会混淆历史数据与最新标准？
        - **权限与受众适配**：面对内部员工与外部客户，如何控制生成答案的详略程度与敏感信息披露？
        - **拒答机制**：当召回内容的置信度不足时，如何让系统诚实地回答“不知道”而不是基于相关性较低的片段强行拼凑答案（幻觉问题）？

### 7.3 迈向自主智能：Agentic RAG 的演进路径
当前的 RAG 架构主要遵循“一次检索-一次生成”的固有范式，但在面对极其复杂的问题（如跨文档对比、多步推理）时，单一的线性流程往往力不从心。本项目作为标准的 MCP Server，天然具备向 **Agentic RAG（代理式 RAG）** 演进的潜力。这不需要重写现有代码，而是通过在 Server 端提供更细粒度的工具，赋能 Client 端的 Agent 具备更强的自主性：

- **从“单步检索”到“多步决策”**：
    - 目前 Agent 可能只调用一个通用的 `search` 工具。
    - **未来演进**：Server 可以暴露如 `list_directory`（查看目录结构）、`preview_document`（预览摘要）、`verify_fact`（事实核查）等更原子化的工具。Agent 可以像人类研究员一样，先看目录圈定范围，再针对性阅读，最后交叉验证信息，从而解决复杂问题。
- **让 Agent 具备“反思”能力**：
    - **未来演进**：利用现有的评估模块，Server 可以提供一个 `self_check` 接口。Agent 在生成答案后，可以自主调用该接口检测是否存在幻觉，或者检索结果是否真正支撑了论点。如果发现不足，Agent 可以自主决定进行第二轮更深度的搜索。
- **动态策略选择**：
    - **未来演进**：不再硬编码使用混合检索。Server 可以将 `keyword_search` 和 `semantic_search` 作为独立工具暴露。Agent 可以根据用户意图自主判断：如果是搜人名，只用关键词搜；如果是搜概念，通过语义搜。这种工具使用的灵活性正是 Agentic RAG 的核心魅力。

这种演进方向将把本项目从一个“智能搜索引擎”升级为一个“智能研究助理”的基础设施底座。


---

# 47. Secondary Review After Full RAG Import

本章是把一号 RAG DEV_SPEC 完整搬入后二次审查的结果。
结论：完整搬入是可用的，并应解释为二号项目的 `knowledge_hub` / `Evidence Knowledge Subsystem` 子规格，服务二号的主项目定位。

## 47.1 总体结论

```text
可以整合：RAG 工程体系、模块拆分、配置示例、测试体系、排期粒度都值得完整保留。
存在冲突：产品定位、目录结构、阶段编号、MCP 工具含义、评估指标、Dashboard 主视角。
处理方式：一号 RAG 作为二号的 Evidence Knowledge Subsystem 子系统规格；二号原 LangGraph controlled agent workflow 仍是顶层主线。
```

优先级规则：

```text
如果第 46 章与第 0-45 章冲突：
  以第 0-45 章的二号主项目定位、能力推进边界、workflow 主线为准。
  以第 46 章的 RAG 子系统细节、模块实现、测试方法为补充。
```

## 47.2 冲突审查表

| 冲突点 | 一号 RAG 原文 | 二号当前定位 | 冲突等级 | 处理规则 |
| --- | --- | --- | --- | --- |
| 产品名称 | Smart Knowledge Hub / RAG MCP Server | Evidence-Grounded Controlled Code Generation Agent Platform | 高 | 一号产品名只作为 imported source，不作为二号项目名 |
| 主目标 | 文档问答、知识库检索、MCP 查询 | 受控代码生成、证据驱动 patch workflow | 高 | RAG 作为 evidence subsystem，不替代 LangGraph workflow |
| 用户路径 | 用户 query -> retrieve -> answer | request -> plan -> evidence -> proposal -> review -> dry-run | 高 | query path 只服务 evidence retrieval；QA 后置 |
| 目录结构 | `src/core`, `src/ingestion`, `src/libs`, `src/mcp_server` | `src/mod_agent/...` | 中 | 迁移到 `src/mod_agent/knowledge_hub/...` |
| MCP 工具 | `query_knowledge_hub`, `list_collections`, `get_document_summary` | safe report-only / evidence tools | 中 | 第一版暴露 `retrieve_evidence`；QA tools optional |
| Response Builder | 面向用户回答，含 citation 和 multimodal response | EvidencePack / CitationBuilder | 中 | 改名为 evidence/citation 输出，不直接生成最终回答 |
| 评估指标 | Hit Rate、MRR、Faithfulness、Answer Relevancy | evidence recall、readiness accuracy、false-continue rate | 中 | 保留检索指标，生成类指标降级为可选 |
| Dashboard | 知识库管理、query trace、ingestion trace | workflow/evidence/proposal/review/eval dashboard | 中 | RAG dashboard 嵌入总 dashboard，不独立主导 |
| 阶段编号 | A-I 用于 RAG 工程 | A-L 用于二号平台 | 低 | 第 46 章阶段作为 `RAG-A/RAG-B/...` 子阶段引用 |
| 配置文件 | `config/settings.yaml` 面向 RAG 服务 | 全项目 settings 包含 workflow/safety/domain/rag | 低 | 合并到 `rag:`、`knowledge_hub:`、`vision:` 配置域 |
| Vector DB | Chroma 默认后端 | Evidence RAG 可插拔后端 | 低 | Chroma 作为默认本地 backend，接口保持抽象 |
| 多模态 | 图片用于文档检索和返回 | 图片用于 evidence、runtime proof、dashboard | 中 | caption pipeline 保留，返回协议后置 |
| 写操作边界 | RAG 项目基本 read/query | 二号有 patch/dry-run/build 风险 | 高 | RAG 子系统永远不执行 patch/apply |

## 47.3 需要改名映射

为了避免二号项目被一号产品叙事覆盖，迁移实现时使用以下映射：

| 一号名称 | 二号名称 |
| --- | --- |
| Smart Knowledge Hub | Knowledge Hub / Evidence Knowledge Subsystem |
| Query Engine | Evidence Retrieval Engine |
| Response Builder | Evidence Pack Builder / Citation Builder |
| query_knowledge_hub | retrieve_evidence, query_knowledge_hub optional |
| RAG Evaluation | Evidence Retrieval Evaluation |
| DocumentManager | KnowledgeSourceManager |
| TraceContext | RetrievalTraceContext / shared TraceContext |
| Dashboard 管理平台 | Evidence/Workflow Dashboard pages |
| Ingestion Pipeline | Knowledge Ingestion Pipeline |

## 47.4 目录迁移规则

一号目录不要原样搬到 repo 根。迁移到二号后：

```text
src/core/query_engine/*
  -> src/mod_agent/knowledge_hub/retrieval/*

src/ingestion/*
  -> src/mod_agent/knowledge_hub/ingestion/*

src/libs/*
  -> src/mod_agent/knowledge_hub/providers/*

src/mcp_server/tools/query_knowledge_hub.py
  -> src/mod_agent/mcp/tools/retrieve_evidence.py
  -> src/mod_agent/mcp/tools/query_knowledge_hub.py later optional

src/dashboard/*
  -> src/mod_agent/dashboard/pages/knowledge_hub/*
```

推荐推进方式：

```text
`smart-knowledge-hub/` 叙事迁入 `knowledge_hub` 子系统；
`src/core` 能力映射到 `src/mod_agent` 下的产品架构；
RAG pipeline 通过 EvidencePack / readiness / review 支持 patch/apply/build；
所有结果通过 artifact store 和 dashboard/API projection 消费。
```

## 47.5 配置合并规则

第 46 章的一号配置示例保留，但实现时必须合并进二号配置域：

```yaml
knowledge_hub:
  ingestion: ...
  chunking: ...
  retrieval: ...
  rerank: ...
  evaluation: ...

rag:
  evidence_mode: true
  qa_mode_enabled: false

safety:
  confirmed_write_default: false
  external_side_effect_default: false
```

如果配置语义冲突：

```text
workflow/safety/domain 配置优先于 rag 配置；
rag 配置通过 workflow/safety/domain 配置接入写操作能力；
qa_mode_enabled 默认 false；
external model provider 默认 fake/local/mock，真实 API 后置。
```

## 47.6 阶段整合规则

第 46 章的一号阶段应作为二号 Phase C/D/J/K 的子任务来源：

| 一号阶段 | 二号接入位置 |
| --- | --- |
| 阶段 A 工程骨架与测试基座 | 只参考测试/配置方式；二号 Phase A 已有主骨架 |
| 阶段 B Libs 可插拔层 | 二号 Knowledge Hub providers 子阶段 |
| 阶段 C Ingestion Pipeline | 二号 Phase C Knowledge Base |
| 阶段 D Retrieval MVP | 二号 Phase D Evidence RAG |
| 阶段 E MCP Server | 二号 Phase K MCP/API，且默认 safe tools |
| 阶段 F Trace 基础设施 | 二号 Observability 共享 trace |
| 阶段 G Dashboard | 二号 Dashboard 的 Knowledge Hub 页面 |
| 阶段 H 评估体系 | 二号 Evaluation Harness 的 retrieval eval 部分 |
| 阶段 I 端到端验收 | 二号 Demo/E2E 子集 |

## 47.7 功能取舍审查

完整搬入不等于第一版全做。第一版应裁剪：

必须做：

```text
Document/Chunk/Evidence 数据类型
Code/Markdown/Artifact/Log loader
Recursive + symbol-aware chunking
BM25 / deterministic / symbol retrieval
EvidencePack schema
Evidence readiness classifier
Retrieval trace
Mini retrieval eval
```

可以后置：

```text
cloud embedding provider
Chroma real integration
semantic chunking
cross-encoder rerank
Vision LLM real calls
full MCP QA
full Streamlit dashboard
Ragas/DeepEval full integration
```

第一版后的升级承诺：

```text
复杂 gameplay runtime verification 接入真实 run/log/screenshot/manual evidence。
RAG 结果通过 EvidencePack/readiness/review 推进到 apply patch。
retrieval quality 通过真实 eval case 和 dashboard report 证明。
多模态理解通过 Vision LLM、caption cache、confidence policy 和 eval case 升级。
```

## 47.8 二次审查结论

完整搬入后没有不可调和冲突。冲突主要来自“产品定位”和“目录/阶段命名”。

最终解释如下：

```text
第 46 章是一号 RAG 系统的完整迁入规格。
它在二号中整合为 Knowledge Hub / Evidence RAG 的权威子系统规格。
它提供 ingestion、chunking、retrieval、rerank、multimodal、MCP、dashboard、eval 的工程细节。
它服务于二号项目的顶层目标：Evidence-Grounded Controlled Code Generation Agent Platform。
patch/apply/review/build/runtime 决策通过 Evidence-Grounded Controlled Code Generation Agent Platform 的 workflow、artifact 和 eval 链路完成。
```

因此，后续实现时可以放心引用第 46 章做 RAG 子系统，但每次引用都必须同时检查第 47 章的冲突处理规则。

Final adapted definition:

~~~text
The imported mature RAG/MCP spec is the authoritative engineering source for
the Knowledge Hub / Evidence RAG subsystem. It should replace shallower current
RAG text whenever its technical detail is stronger.

Adopt directly:
  Document/Chunk contracts, metadata identity, file and chunk hashes, loader
  pipeline, transform pipeline, embedding cache, sparse/dense retrievers,
  hybrid fusion, RRF, rerank fallback, citation/source-span design, multimodal
  assembly, trace events, retrieval eval, MCP JSON-RPC schema discipline,
  dashboard page concepts, and test pyramid.

Adapt for vertical code generation:
  QA query becomes EvidenceQuery; response builder becomes EvidencePackBuilder
  and CitationBuilder; final answer becomes evidence summary only; dashboard
  knowledge pages become subpages inside workflow/evidence/proposal/review/eval;
  MCP tools become read-only/report-only controlled-agent tools first, then
  approved-route tools later.

Defer until evidence and eval are ready:
  dense authority, RRF/rerank authority, semantic chunking over code, real Vision
  LLM image understanding, broad importers, full MCP transport/server deployment,
  and QA-style query_knowledge_hub as a user-facing product surface.

Reject for this project boundary:
  RAG directly approving patches, RAG directly writing files, raw community chat
  entering patch context, MCP tools bypassing LangGraph routes, Skills becoming
  runtime product state, and screenshots alone proving hook correctness.
~~~

---

