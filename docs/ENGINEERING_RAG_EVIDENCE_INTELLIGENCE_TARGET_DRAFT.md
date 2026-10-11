# 工程 RAG / 证据智能能力目标、系统边界与验证计划（整合草案）

```yaml
document_status: draft_for_independent_review
repository_normative: false
execution_authority: none
implementation_authorization: not_granted
supersedes: none
created_at: 2026-08-11
last_consolidated_at: 2026-08-16
promotion_target: authoritative_product_target_document
document_purpose: capability_target_boundary_and_validation_plan
current_scope:
  - standard_document_rag
  - engineering_evidence_retrieval
  - rag_1a_evidence_semantics
  - rag_1b_public_evidence_adoption
linked_product_milestone: coding_agent_v0_internal_alpha
explicitly_separate_scope:
  - trace_platform
  - evaluation_platform
explicitly_deferred_scope:
  - knowledge_hub_productization
  - mcp_http_dashboard_expansion
  - multimodal_productionization
  - dense_rrf_rerank_default_adoption
architecture_commitment: bounded_validation_first
decision_record_status: twelve_decisions_consolidated
```

> 本文是拟提升为仓库权威目标文档的整合草案，不是当前产品完成声明、实施合同或执行队列。
> 本文不授权修改代码、测试、ArtifactStore、产品源码或运行 Build/Runtime，也不自动授权 RAG-1A、RAG-1B 或任何后续阶段。
> 文中的精确源码事实必须在各实施包开始前，针对届时的目标分支、HEAD、工作树和测试重新复核。
> 本文覆盖标准文档 RAG 与工程证据检索（ER），但不复制历史模板的全部实现细节；历史能力必须在本文中获得 adopt、adapt、experimental、defer、reject 或 reference-only 的唯一裁决后，才能进入当前产品。
> Coding Agent v0 的统一语境、模块归位、observation 定义、跨工作树归并和 internal alpha 完成门见 `docs/CODING_AGENT_V0_INTERNAL_ALPHA.md`；本文只拥有 RAG/ER 能力边界。

## 1. 文档目的

控制面解决：Agent 允许做什么、由谁决定、哪些副作用真实发生、失败后能否继续以及机器结果由谁解释。

本文解决另一组问题：

- 系统能否从文档、源码、API、symbol、IL、Artifact 和运行时观察中找到相关信息；
- 检索命中能否被验证为当前、可回读、身份一致的工程证据；
- 证据支持哪些 Hook 或实现方向、与哪些事实冲突、还缺什么；
- 当前证据是否足以进入实施规划；
- 标准文档 RAG 与工程证据检索如何复用同一基础设施而不形成两套重复平台；
- 哪些普通 RAG 能力已经存在，哪些只是可选实验，哪些不适合进入 Coding Agent 主链。

目标关系：

```text
自然语言 Mod 需求
  → 工程问题分解
  → 标准文档 RAG + 工程证据检索
  → 来源与身份校验
  → EvidencePack
  → Hook/方案备选项 + 支持/冲突/缺失关系 + 充分性
  → 实施规划或明确阻断
  → 既有控制面
  → Approval / Apply / Build / Runtime / Product result
```

本文不新增 RAG Controller、Evidence Controller、第二套 Agent 工作流或新的执行控制协议。

## 2. 文档来源、优先级与历史材料裁决

### 2.1 当前决策优先级

涉及 RAG/ER 的工作按以下顺序解释：

1. 届时目标分支的当前源码与聚焦测试决定已实现的精确标识符、schema 和行为。
2. 本文在正式审核通过后决定 RAG/ER 的产品目标、能力边界、采用规则、工作包和完成门。
3. 当前控制面权威文档决定 Approval、Graph 路由、Artifact lineage、Store commit truth、执行权限与产品终态。
4. 后续独立 Trace/Eval 文档决定 trace context、span、exporter、数据集、指标、阈值和评测运行方式。
5. 历史 RAG 文档只提供工程模式，不决定当前范围、默认算法、实施顺序或完成状态。

源码和测试不会因为本文描述目标而自动获得对应实现；历史代码存在也不会因为本文引用而自动升级为当前产品采用。

### 2.2 原始通用 RAG 模板

审查对象：

```text
C:\Users\10160\Desktop\ai_learn\新建文件夹\DEV_SPEC.md
SHA256=CC29F1C50E0305110A38BA011F9BA1F220A7CCBC2F7601A84CF59146768E2298
```

该文件是用于借鉴的外部通用 RAG/MCP 项目模板，不是当前项目的旧版本设计，也不是当前仓库的完成状态来源。

它可以提供：

- ingestion、loader、splitter、transform、embedding、index、retrieval 的工程模式；
- Dense、BM25、RRF、reranker、citation、response projection 的通用实现思路；
- provider abstraction、MCP stdio、Dashboard、Trace、Eval 和 Multimodal 的参考结构；
- 本地优先、增量处理、失败回退和测试分层的工程经验。

它不能决定：

- 当前产品身份和第一产品目标；
- 工程 Evidence 的 authority、充分性或执行权限；
- Dense/RRF/reranker 是否成为默认路径；
- 当前公共接口、Artifact schema、数据库表、目录布局和完成状态；
- 当前实施阶段或优先级。

原始模板中的历史完成表、测试数量、阈值和“生产环境”措辞只作为模板自述，不作为当前仓库证据。

### 2.3 历史适配稿

审查对象：

```text
C:\Users\10160\.codex\worktrees\e3bb\MODULAR-RAG-MCP-SERVER-main\EVIDENCE_RAG_MCP_SPEC.md
SHA256=BDCC6A30F817A56548627D212A299437B87C8442010993FD638E2C88FC615407
```

该文件是把原始通用 RAG 模板适配到 Controlled Agent 产品后的历史规格。

裁决：

- §0–§3 中与本文一致的 source authority、validation-first、EvidencePack、read-only MCP 和 live revalidation 原则可以继承；
- §4 以后的导入蓝图只作为 reference-only 工程模式库；
- 后文“整体吸收”“完整继承”“authoritative engineering source”等与文件前部 reference-only 声明冲突的措辞由本文覆盖；
- 旧 V1/V2/V3、RAG-M0–M3、MCP required tools、Dashboard 和 Multimodal 排期不再构成当前队列；
- 旧 EvidenceItem、EvidenceQuery、EvidencePack、readiness 示例不构成当前公共 schema。

### 2.4 文档之间的职责

```text
本文
  决定为什么做、做什么、不做什么、如何验证、何时停止

原始通用 RAG 模板
  提供通用 RAG 工程结构参考

历史 EVIDENCE_RAG_MCP_SPEC
  提供适配过程和历史能力目录参考

当前源码与测试
  决定精确实现事实

控制面文档
  决定执行权威

未来 Trace/Eval 文档
  决定观测和质量证明方式
```

## 3. 核心产品问题与第一阶段目标

### 3.1 标准文档 RAG 的问题

标准文档 RAG 负责从外部文档知识中检索相关上下文，并提供可回读引用，用于：

- 普通知识查询；
- 官方文档、README、教程和领域资料检索；
- Agent 的背景知识补充；
- 后续可选知识中心；
- 工程证据检索的文档检索路径。

它可以生成带引用的回答或摘要，但不拥有 Coding Agent 的工程事实、执行权限或产品终态。

### 3.2 工程证据检索（ER）的问题

工程证据检索是标准文档 RAG 在软件工程 Agent 场景中的领域增强，不是替代 RAG 的新学术范式。

它需要回答：

> 在当前产品版本、当前目标范围和明确搜索覆盖下，观察到了哪些可回读工程事实；这些事实支持或反驳哪些 Hook/实现方向；还缺少什么；当前是否足以进入实施规划？

### 3.3 第一产品目标

当前产品级里程碑调整为 **Coding Agent v0 纵向闭环**。它不替代或暂停 RAG/ER，也不新建通用 Agent 框架；RAG-1A 是 v0 的只读证据工具子系统。第一份可信 BetterHitFeedback EvidencePack 形成后立即进入 v0 internal alpha 的既有 Planning、Patch、Build/Test 消费链；该内部消费用于暴露真实字段需求，不替代随后用 BetterHitFeedback、WallCrawler 和最小 Eval 完成 RAG-1A。

产品路径为：

```text
自然语言 Mod 功能需求
  → RAG/ER 工程证据发现与验证
  → EvidencePack
  → Implementation Plan
  → PatchProposal
  → Review / Dry-run
  → 隔离 Build/Test
  → 完成，或根据真实失败调整下一步
```

当前立即依赖仍是：在不读取 Golden、历史实现或已知 Hook 的条件下，让 BetterHitFeedback 真实运行完成 `source → metadata → IL → EvidencePack`。该依赖完成前不启动新的 Coding Agent 框架；完成后也不得继续孤立打磨只读证据结构，而应先接入 v0 internal alpha，再完成 WallCrawler、Hidden-Golden 和最小 Eval，形成 RAG-1A checkpoint。RAG-1B 随后负责公共入口采用，v0 public alpha 再使用该公共路径。

RAG/ER 不声称最终 Hook 一定正确。它负责提供可审计的证据基础和充分性结论；模型负责工程语义与基于 observation 的方向选择，确定性代码负责身份、权限、工具参数和持久化完整性。既有 Graph 与控制层限制允许的副作用，但不预先决定工程方向。

Coding Agent v0 至少证明两条路径：

- 成功路径：自然语言需求形成证据、修改建议和受控 Patch，并通过 Build/Test；
- 失败修复路径：第一次 Build/Test 失败后，Agent 读取真实诊断并改变下一步修改，而不是沿固定 Workflow 重放。

### 3.4 成果假设与存在价值

第一阶段不是为了证明“检索链更复杂”，而是验证以下成果假设：

> 工程证据检索能够减少缺乏证据支持的工程决策，并同时提高“有充分证据时进入规划”和“证据不足时停止规划”的可靠性。

这项假设必须由一正一负两个真实切片共同检验：

- BetterHitFeedback：证据充分时形成可审计的 Hook/方案备选项并进入实施规划；
- WallCrawler：证据不足时明确缺口并阻止缺乏支持的实施规划。

只提高召回数量、检索层数、测试数量或 Artifact 写入成功率，均不能证明 RAG/ER 值得存在。

### 3.5 第一阶段非目标

RAG-1A 当前工作包不以以下能力为主目标。Planning、Patch 和隔离 Build/Test 只允许在首份 committed BetterHitFeedback EvidencePack 后作为 v0 internal alpha 的真实消费者进入；公共产品采用仍在 RAG-1A checkpoint 和 RAG-1B 后进行。该内部消费不得反向扩大当前只读证据合同：

- Build/Runtime diagnosis；
- 通用知识中心产品化；
- 自动批准 Patch；
- 自动 Apply、Build 或 Runtime；
- 完整 Trace/Eval 平台；
- Dense/RRF/reranker 生产化；
- Agentic retrieval router；
- 通用证据需求框架。

上述延期边界针对跨领域、动态选择任意工具、开放式自循环以及统一处理所有工程需求的通用 Agentic retrieval router 或通用证据需求框架。该延期不排除 RAG-1A 第一 Hook Discovery 切片完成既定产品目标所必需的有界 Agent Evidence Discovery 子层。该子层只负责：

- 将自然语言功能需求投影为可审计的工程问题和约束；
- 将工程问题投影为来源角色、检索路径、查询表达和 coverage 要求；
- 调用既有 RAG/ER 检索与精确验证能力形成 Hook/方案备选项；
- 将 actual evidence 交给既有单一证据语义所有者计算关系和充分性。

它不建立通用 Agent 框架、第二工作流、动态工具注册中心、无限自主循环、第二充分性所有者或副作用控制器。第一阶段的 Requirement Projection 只处理 Hook Discovery 所需的最小工程语义，不得扩张为统一处理所有 Agent 任务的 `Requirement Framework`。

## 4. 术语与双路径体系

### 4.1 标准文档 RAG

输入主要包括：

- PDF、Markdown、README、官方资料和领域说明；
- issue、教程、整理后的笔记和历史知识文档；
- 适合以 Document/Chunk 表示的内容。

输出主要包括：

- retrieved chunks；
- source/citation projection；
- 搜索覆盖和故障信息；
- 可选自然语言回答或摘要。

### 4.2 工程证据检索（ER）

输入主要包括：

- 当前源码、symbol、method、signature、metadata 和 IL；
- 当前版本 API/Assembly；
- immutable Artifact 和 lineage；
- 绑定精确身份的运行时观察；
- supporting reference Mod、领域资料和历史验证案例。

输出主要包括：

- 已准入证据；
- Hook/方案备选项投影；
- support、conflict、missing 和 limitation 关系；
- 搜索覆盖；
- retrieval/engineering/planning 三层充分性；
- versioned EvidencePack 语义。

### 4.3 共享检索基础能力

两条路径共享可复用的基础设施能力，而不是复制为两个平台：

```text
source registration
loader / parser
raw content identity
chunk / structured unit
index providers
BM25 / dense capability
citation / locator
provenance / freshness
retrieval diagnostics
```

共享基础能力表示可复用的检索机制，不表示共享语义权威。两条路径可以复用来源注册、加载、切分、索引、BM25、Dense、引用和 provenance，但不得因此共用同一 score 含义、证据事实解释或充分性规则。

```text
共享：检索机制与基础设施能力
不共享：证据含义、分数语义、充分性与行动权威
```

两条路径不得共享为同一事实的内容：

- 普通 RAG 回答真实性；
- 工程证据充分性；
- Approval 或执行权限；
- 产品成功状态；
- Eval truth。

### 4.4 组合关系

```text
                              自然语言需求
                                   │
                         Agent Evidence Discovery
                    ┌──────────────┴──────────────┐
                    │                             │
          Requirement Projection           Search Planning
                    │                             │
                    └──────────────┬──────────────┘
                                   │
                       Bounded Discovery Loop
                                   │
               ┌───────────────────┴───────────────────┐
               │                                       │
          标准文档 RAG                         工程证据检索
               │                                       │
      文档 / 手册 / README                    source / symbol / metadata
        教程 / 领域知识                       IL / Artifact / 运行时事实
               │                                       │
          文档检索 + 引用                    精确查找 + 类型化投影
               └───────────────────┬───────────────────┘
                                   │
                              证据准入
                                   │
                    Hook/方案备选项与关系投影
                                   │
                              证据充分性
                                   │
                              EvidencePack
                                   │
                                实施规划
                                   │
                                既有控制面
```

Agent Evidence Discovery 决定应调查什么以及如何使用检索工具；RAG/ER 负责执行检索并返回当前来源事实；Evidence Reasoning 负责解释已准入证据支持什么、冲突什么、缺少什么以及是否足以进入实施规划。

三者可以组合，但不得互相取代：

- BM25、symbol search、metadata/IL inspector 不解释最终需求；
- Requirement Projection 和 Search Planning 不拥有来源真实性或充分性；
- EvidencePack 不反向生成搜索计划或 Golden；
- Eval 不参与 actual discovery。

## 5. 当前已验证基础与真实限制

下表只表示代码骨架或局部能力存在，不表示已形成端到端生产级 RAG/ER。

| 范围 | 当前事实 | 主要依据 | 当前限制 |
| --- | --- | --- | --- |
| 文档导入/切块 | 存在文档 loader、`DocumentChunker`、recursive splitter 和稳定 chunk ID | `src/libs/loader/`、`src/ingestion/chunking/document_chunker.py`、`src/libs/splitter/recursive_splitter.py` | 尚未形成覆盖文档、源码、IL、日志和 Artifact 的统一 source-specific 策略 |
| Dense 索引/检索 | 存在 embedding、vector store、`VectorUpserter`、`DenseRetriever` | `src/ingestion/storage/vector_upserter.py`、`src/core/query_engine/dense_retriever.py` | `config/settings.yaml` 当前默认 `retrieval.dense_enabled=false`；相似度不能证明工程事实 |
| Sparse 检索 | 存在 `BM25Indexer` 与 `SparseRetriever` | `src/ingestion/storage/bm25_indexer.py`、`src/core/query_engine/sparse_retriever.py` | 主要表达文本/词项匹配，不表达工程 identity 和行为语义 |
| Hybrid/RRF | `HybridSearch` 支持 Dense/Sparse、RRF、metadata filter 和单路降级 | `src/core/query_engine/hybrid_search.py` | 只证明通用检索能力存在，不证明适合当前 Hook Discovery 默认路径 |
| Reranking | 存在 `CoreReranker` 及 cross-encoder/LLM 后端 | `src/core/query_engine/reranker.py`、`src/libs/reranker/` | `config/settings.yaml` 当前默认 `rerank.enabled=false` |
| 引用/回答 | 存在 `CitationGenerator`、`ResponseBuilder` | `src/core/response/` | chunk/source citation 不自动证明具体工程 claim |
| 普通 MCP 查询 | 存在 `QueryKnowledgeHubTool`、collection 和 document summary 相关能力 | `src/mcp_server/` | 属于知识查询入口，不拥有 Mod Agent 工程行动决定 |
| 普通 RAG Trace | `TraceContext`、`TraceCollector` 覆盖 query/ingestion | `src/core/trace/` | 尚未形成经过合同验证的跨 RAG、Agent、Graph、Artifact、Build/Runtime 和 Eval 关联与传播规则；本文不预设单一全局根 ID |
| 普通 RAG Eval | 存在 `EvalRunner`、hit rate、MRR、Ragas evaluator 和 Dashboard 页面 | `src/observability/evaluation/`、`src/libs/evaluator/` | `tests/fixtures/golden_test_set.json` 中 `expected_chunk_ids` 为空，不能证明真实 retrieval quality |
| Mod Agent 工作流事件 | `TraceEvent` 保存 run/feature/node/stage/status、Artifact refs 和摘要；intelligent evidence 入口会写入 `workflow_trace` Artifact | `src/mod_agent/workflow/nodes.py`、`src/mod_agent/intelligent_evidence_only.py` | 属于局部事件和既有入口审计事实，不是统一的 span Trace，也不替代控制面或 EvidencePack truth |
| Agent 工程质量评测 | `AgentQualityEvaluator` 已覆盖检索、Hook、readiness、continuation、任务/文件结果以及延迟、token、API 调用和成本指标 | `src/mod_agent/evaluation/agent_quality.py` | `tests/fixtures/evaluation/agent_quality_cases.json` 明确是 calibration，不是 measured retrieval evidence；现有 readiness 标签和值域不自动成为 RAG-1A 新语义 owner |
| 版本化回归比较与质量门 | `RetrievalRegressionRunner`、`QualityGatePolicy` 支持版本化 dataset/observation identity、可比性检查、calibration/benchmark/promotion 和 fail-closed threshold gate | `src/mod_agent/evaluation/retrieval_regression.py`、`src/mod_agent/evaluation/quality_policy.py` | 只有 held-out 且 promotion-eligible 的报告可进入 promotion；当前 `tests/fixtures/retrieval/golden_queries.json` 是受控 fixture，未形成正式 held-out 质量证据 |
| Arm A 确定性基线 | `OfficialArmARunner`/`RgLiveReadProvider` 记录 rg + live read、corpus/hash、命令、协议、数据集、Git 与环境身份 | `src/mod_agent/evaluation/arm_a.py` | 是可复现实验基线，不是产品端到端 Trace，也不证明 RAG-1A 已采用或优于其他检索路径 |
| 既有 transition Eval gate | `build_transition_eval_gate_report` 覆盖 false block/continue、stale evidence、review/dry-run/Build/Runtime claim boundary 和缺失指标 | `src/mod_agent/evaluation/gate.py` | 是既有 workflow transition 的确定性评测门；不得据此重算 retrieval quality、EvidencePack 充分性或 RAG-1A expected facts |
| Mod Agent Knowledge | 存在 source registry、incremental index、symbol index 和 BM25 foundation | `src/mod_agent/knowledge/` | 当前只覆盖有限本地来源和结构 |
| Mod Agent Evidence | 存在 `EvidenceRequest`、`EvidenceItem`、`EvidencePack`、`EvidenceReadinessClassifier` | `src/mod_agent/evidence/` | 当前 EvidencePack 负担较多；尚未有严格版本化 Hook Discovery 语义段 |
| Deterministic Evidence | 当前默认检索以 symbol/text 为主，dense 可选 | `src/mod_agent/evidence/retriever.py` | symbol、BM25、dense 共享容量和分数不可直接比较；未使用 RRF |
| Intelligent Evidence | 存在 intelligent evidence discovery 和专用入口 | `src/mod_agent/intelligent_evidence_only.py` | 当前入口仍直接创建/调用 Graph、写 Store 并解释终态，是 RAG-1B 的迁移对象 |
| Evidence fail-closed | readiness 可表达 `sufficient/partial/insufficient/contradictory`，并投影 `can_generate_patch` | `src/mod_agent/evidence/readiness.py` | 规则较粗，且需要防止 Graph、CLI、入口形成第二解释 owner |

实施前必须重新核对这些文件的当前 HEAD、working tree、测试和 schema；本表不是永久完成声明。

## 6. 共享检索基础能力

### 6.1 来源身份

来源身份至少在语义上区分：

- stable logical source identity；
- source kind；
- source revision/version；
- content identity/hash；
- logical locator；
- source role；
- usage/sensitivity boundary。

内容哈希可以用于缓存和去重，但不能单独取代逻辑来源身份。相同内容出现在不同产品版本、路径、来源类别或权限范围时，必须保持可区分。

### 6.2 数据摄取生命周期

目标生命周期：

```text
discover
  → read immutable/raw source
  → normalize without losing raw identity
  → split/project by source type
  → attach derived annotations
  → build selected indexes
  → record coverage/status
```

不变量：

- 原始内容必须可回读；
- normalization 不能删除来源身份和定位；
- LLM summary、tag、rewrite、OCR 和 image caption 必须标记为 derived；
- derived text 不能覆盖 raw excerpt 或自动获得 source authority；
- ingestion 成功不等于 Evidence admission 成功；
- 索引成功不等于当前来源仍新鲜；
- 失败项、跳过项、未处理项必须进入 coverage/status；
- 未变化内容可以复用缓存，但进入 ER 前仍要验证当前来源身份。

### 6.3 切块与结构化单位

| 来源类型 | 目标切分/投影原则 |
| --- | --- |
| 普通文档、Markdown、README | heading/section/paragraph/code-block aware |
| PDF | 保留页码、标题、原始位置和图片引用 |
| 源码 | module/class/method/signature/hook-site aware |
| 反编译 API | assembly/type/member/signature aware |
| IL/metadata | assembly/type/method/token/instruction-block aware |
| Build/Runtime log | diagnostic/event/time-window aware |
| Artifact | contract field、upstream 和 outcome aware |
| 历史案例 | request/environment/evidence/decision/change/acceptance aware |
| 图片 | 保留原图、caption、上下文和来源关系 |
| 后备路径 | fixed/recursive，仅在没有更合适结构时使用 |

禁止把固定长度、recursive 或 semantic splitter 写成适用于所有来源的全局最佳策略。

### 6.4 原始内容与派生内容

下列内容必须可区分：

```text
raw source
normalized source
rule-derived metadata
LLM-generated summary/tags
image caption
model-generated search lead
```

普通 RAG 可以检索派生内容以改善召回；工程证据检索只有在回读并验证原始来源后，才能把对应事实准入为权威证据。

### 6.5 索引、来源与证据的关系

```text
index hit
  = locator / retrieval lead

live or immutable source validation
  = identity and freshness fact

Evidence admission
  = engineering-use decision
```

禁止把索引中的旧文本、embedding 命中、BM25 命中或模型描述直接解释为当前事实。

### 6.6 存储与 provider

当前已有 SQLite、BM25 persistence、Chroma/vector abstraction 等实现。本文不冻结新的数据库布局或迁移方案。

原则：

- 复用当前已实现 provider；
- 没有至少两个真实消费者或切换需求时，不新增抽象层；
- provider 差异不得改变证据真实性或控制面权威；
- provider 失败必须结构化暴露并影响 coverage；
- 不因模板存在 Qdrant、Milvus、Pinecone、Redis 或 PostgreSQL 描述而提前实现适配。

## 7. 标准文档 RAG 子系统

### 7.1 产品用途与边界

标准文档 RAG 是当前项目保留的独立能力面，不被 ER 删除或伪装。

本章的目的，是固定生产 RAG 所需的最小工程闭环和与 ER 的接口，不是把当前主产品改造成企业知识平台。当前只展开数据摄取、切块、检索、过滤、引用和必要故障边界；知识中心、多模态、HTTP API 和 Dashboard 只保留延期裁决。

它负责：

- 文档、知识和说明资料的摄取与检索；
- 普通查询的相关片段、引用和可选回答；
- 为 Agent 提供背景知识；
- 为 ER 提供文档检索路径。

它不负责：

- 证明当前产品源码或 Runtime 行为；
- 决定最终 Hook；
- 批准 Patch、Apply、Build 或 Runtime；
- 解释 Store commit 或产品终态。

### 7.2 查询处理

普通 RAG 可以包含：

- 保留原始查询；
- 独立查询投影；
- 关键词和实体提取；
- 别名和同义词扩展；
- collection/doc type/language/time/access filters；
- 查询预算和 top-k。

原始通用模板假设 query 已由外部 MCP Host 完成上下文补全。当前项目不能把该假设提升为产品前提：

- 原始用户需求必须保留；
- 外部 Host 改写只能作为投影；
- ER 的 requirement decomposition 必须由当前产品记录；
- 无法消除的歧义必须进入 gaps 或用户输入请求。

### 7.3 检索路径

标准文档 RAG 支持：

```yaml
baseline_capabilities:
  - sparse_bm25
  - exact_metadata_filter
supported_experimental_capabilities:
  - dense_retrieval
  - reciprocal_rank_fusion
  - cross_encoder_rerank
  - llm_rerank
```

这些标签描述采用状态，不冻结当前源码中的配置键或 provider 名称。

普通 RAG 可以使用 Dense + Sparse + RRF；但是否成为默认路径必须由非空 ground truth 的普通 RAG 数据集证明，不能由原始模板或模块存在决定。

### 7.4 过滤语义

过滤条件分为：

- hard identity/security filter；
- ordinary metadata filter；
- soft preference。

规则：

- access、sensitivity、source identity、version 和 content binding 属于硬约束；缺失时不得以宽松包含方式进入可信结果；
- collection、doc type 等普通过滤根据产品需求决定缺失策略，但必须可观测；
- recency 等软偏好可以成为排序信号；
- 对 `missing->include` 的使用必须限制在非安全、非身份的普通召回场景。

### 7.5 融合与重排序

RRF 和 reranker 回答“哪些检索结果优先查看”，不回答“哪些内容为真”。

要求：

- 保留各路径原始结果和原始排名；
- RRF 分数不能取代原始 score、来源 identity 或 evidence confidence；
- reranker 失败可以回退，但必须记录 fallback；
- LLM reranker 输出必须结构化且不能建立 source truth；
- 普通 RAG 的排序提升不能自动迁移为 ER 的充分性提升。

### 7.6 检索故障与覆盖范围

单路失败时可以降级，但必须记录：

- 失败的路径；
- 未搜索的来源；
- 返回结果使用了哪些路径；
- coverage 是否完整；
- 是否仍允许回答；
- 是否只能返回部分结果或要求重试。

禁止静默降级后仍声称完成了完整搜索。

### 7.7 引用与回答

普通 RAG 的结果必须分开：

```text
retrieved chunks
source/citation projection
generated answer or summary
```

引用至少需要能回到来源和原文位置；精确 schema 由实施时的当前源码合同决定。

规则：

- 回答生成失败不能抹掉已经成功的检索结果；
- 引用证明使用了哪个来源，不自动证明生成的论断被来源蕴含；
- 来源路径、页码、chunk、摘录、hash 和 score 只保留适用字段；
- 普通回答不能成为 ER 或控制面的机器结果 owner。

#### 7.7.1 证据不足、拒答与有界部分回答

标准文档 RAG 必须把“检索执行是否正常”和“当前内容是否足以支持回答”分开：

- 检索路径正常完成但证据不足，不属于平台执行失败；
- 检索路径故障、覆盖不完整或来源验证失败，不得伪装成单纯的“没有答案”；
- 只有被已验证来源明确支持的论断才允许作为确定性回答；
- 内容只能支持部分论断时，可以返回有边界的部分回答，但必须明确哪些内容已有支持、哪些内容仍缺证据；
- 内容不足以支持明确回答时，必须返回明确的证据不足结果，不能用语言流畅度、引用数量、相关性分数或模型置信度补足事实缺口；
- 拒答或有界部分回答应保留已执行检索路径、coverage、适用引用和缺失证据，使调用方能够区分“没有搜索”“搜索失败”“搜索完成但未找到”和“找到相关内容但不足以支持论断”；
- 标准 RAG 的证据不足结果不得被 ER、Planner、Graph 或控制面解释为工程充分性、Approval 或执行权限。

精确公共字段、版本和值域由标准文档 RAG 的实施合同固定；本文不猜测标识符。兼容层可以投影历史回答形状，但不得把证据不足重写为确定性成功回答，也不得把领域拒答重写为平台失败。

### 7.8 延后能力边界

标准文档 RAG 本阶段只需覆盖数据摄取、切块、检索、过滤、引用和必要故障信息。以下能力保留为历史工程参考，不展开为当前产品设计：

- 知识中心：仅保留后续只读知识浏览的可能性，不属于 RAG-1A/RAG-1B；
- 多模态：图片说明只能作为派生注释，第一阶段不要求 Vision LLM 或多模态向量库；
- HTTP API、Dashboard、外部 MCP 产品面：另行审核，不是当前 RAG 的前置架构。

这些能力不得绕过 Agent Graph 或控制面，也不得因为历史模块存在而被宣称为当前用户产品已完成。

### 7.9 标准文档 RAG 的质量证明接口

标准文档 RAG 需要自己的质量数据，不得只用 ER 指标代替：

- 数据摄取正确性；
- 来源和引用有效性；
- Recall@K、MRR、nDCG；
- 回答忠实性和相关性（仅适用于回答生成）；
- 证据不足识别、拒答和有界部分回答的正确性；
- 延迟、provider 故障和回退；
- 过期索引和过滤正确性。

精确数据集、阈值、评测运行器和报告格式由后续独立 Eval 文档决定。原始模板中的固定阈值不直接继承。

## 8. 工程证据检索（ER）

### 8.1 第一证据需求类型

第一阶段只允许 Hook Discovery 需求类型。本文不冻结其精确公共标识符、字段和值域；这些必须在 RAG-1A 合同中从当前源码和真实切片确定。

该类型负责声明：

- 需要验证的工程问题；
- 必须搜索的来源角色；
- 哪些来源可选；
- 哪些行为语义需要运行时观察；
- 何种缺失会阻止规划；
- 搜索覆盖如何解释。

禁止在第一阶段建立覆盖 Build 诊断、Runtime 修复、通用软件工程和未来产品的巨型需求框架。

### 8.2 来源感知的多路检索

目标检索路径包括：

- 精确/实时源码；
- symbol/metadata；
- 反编译 API；
- IL；
- BM25/文本；
- 不可变 Artifact；
- 精确运行时观察；
- 可选 Dense；
- 支持性的参考实现、社区资料和历史资料。

每条路径拥有独立预算和独立事实：

- 是否执行；
- 搜索范围；
- 命中数量；
- 原始排序信号；
- 失败；
- 未执行原因；
- 覆盖范围。

禁止让一条路径先填满共享容量，从而掩盖其他路径是否发现了有价值的信息。

### 8.3 证据准入

顺序固定为：

```text
检索命中
  → 精确来源解析
  → 来源身份/版本/hash 验证
  → 来源权威分类
  → 工程相关性验证
  → 已准入证据
```

证据准入不等于证据正确性：

- 来源身份正确只证明来源和内容匹配；
- 工程相关性判断该事实是否与当前问题相关；
- 行为含义可能仍需 IL、调用方或运行时观察；
- 规划就绪度需要该需求类型规定的证据组合。

### 8.4 Hook/方案备选项投影

每项投影至少需要在语义上表达：

- 稳定逻辑身份；
- 支持性证据；
- 冲突证据；
- 缺失证据；
- 限制；
- 当前工程充分性。

它表达“为什么值得考虑或排除”，不是最终 Hook 决定，也不是执行授权。

### 8.5 排名与充分性分离

```text
排序
  回答：先检查什么

充分性
  回答：当前证据是否足以进入下一工程阶段
```

Dense、BM25、RRF、reranker、LLM confidence 都不得直接决定充分性。

### 8.6 搜索覆盖与负面结论

必须区分：

- `not_searched`：没有执行对应搜索；
- `not_found`：执行了搜索但没有命中；
- `insufficient_coverage`：搜索发生但范围不足；
- `searched_and_absent`：在明确边界内完成足够覆盖并确认不存在。

只有最后一种情况可以支持有边界的“不存在”论断。未命中不能自动解释为不存在。

## 9. 来源权威

### 9.1 权威证据

能够在其适用范围内形成当前事实：

- 当前 hash 绑定来源；
- 精确版本绑定的 Assembly/API；
- 不可变 Artifact；
- 精确身份绑定的运行时观察。

### 9.2 支持性证据

可以支持假设、模式或背景，但不能单独成为当前版本事实：

- 参考 Mod；
- 既往实现；
- 整理后的领域笔记；
- 历史 Build/Runtime 记录；
- 框架/官方文档在其框架语义范围内。

### 9.3 辅助线索

只能指示下一步搜索方向：

- 社区内容；
- 仅由 Dense 获得的命中；
- 未绑定身份的历史内容；
- 模型内部知识；
- 未验证的截图/图片说明。

### 9.4 来源组合

工程结论可以由多个来源共同支持：

```text
框架规则
  + 当前源码/API/IL 事实
  + 可选运行时观察
  + 明确标记的推断
```

不得把支持性或辅助来源通过多数投票、RRF 或 LLM 总结升级为权威来源。

### 9.5 三层正确性

```text
身份正确性
  → 工程相关性
  → 规划就绪度
```

三层不能合并成一个不透明总分。

## 10. 证据充分性

### 10.1 检索充分性

回答：是否完成了该需求类型所要求的合理搜索。

输入包括：

- 必需检索路径；
- 实际检索路径执行；
- 覆盖范围；
- 故障；
- `not_searched/not_found/insufficient_coverage/searched_and_absent`。

### 10.2 工程充分性

回答：某个 Hook/实现方向是否有足够工程依据。

输入包括：

- 权威/支持性证据；
- 支持/冲突/缺失关系；
- 来源身份和新鲜度；
- 行为语义；
- 限制。

### 10.3 规划就绪度

回答：当前 EvidencePack 是否足以进入实施规划。

明确：

```text
规划已就绪
  != human approved
  != apply allowed
  != build allowed
  != runtime allowed
  != final correctness
```

### 10.4 运行时观察

运行时观察不是所有 Hook Discovery 的通用前置条件。

以下情况通常可由静态证据支持：

- 方法存在；
- 签名；
- 类型关系；
- 静态调用方；
- 框架 API 约束。

以下情况可能需要运行时观察：

- 参数的真实行为含义；
- 路径是否在目标行为中触发；
- UI/gameplay 状态与方法之间的关系；
- 该需求类型明确要求的高风险行为确认。

### 10.5 兼容投影

现有 `can_generate_patch` 暂时保留为兼容投影，其唯一允许含义是：

```text
证据已经可以支持方案/规划生成。
```

它不表示 Approval、Apply permission、Build permission、Runtime acceptance 或最终正确性。

## 11. EvidencePack 与版本化语义

### 11.1 EvidencePack 的角色

EvidencePack 是可持久化的证据决策包。这里的“决策”仅指证据层解释。

EvidencePack 拥有：

- 已准入证据事实；
- provenance；
- Hook/方案备选项投影；
- 支持/冲突/缺失关系；
- 覆盖范围；
- 检索/工程/规划三层充分性；
- gaps 和 Evidence blockers。

EvidencePack 不拥有：

- Approval；
- Apply/Build/Runtime permission；
- 最终产品事实；
- 模型内部 trace；
- Eval 事实；
- Dashboard 状态；
- Store 提交事实。

### 11.2 复用现有 Artifact

第一阶段复用现有 EvidencePack Artifact，不新增第二种证据 Artifact。

禁止新增 `EvidenceDecision`、`HookDecision` 或其他与 EvidencePack 重叠的持久化事实类型，除非真实源码清点证明现有 Artifact 无法无损承载，并经过独立合同审核。

### 11.3 版本化 Hook Discovery 语义段

新语义采用 EvidencePack 内严格版本化扩展：

- 只对新 Hook Discovery 需求类型必填；
- 精确 schema、版本值、序列化和 Registry 委托必须由 RAG-1A 合同固定；
- 公共入口/Graph/Registry 不能各自保存一份规则；
- 语义所有者必须能够从来源、准入事实和需求类型重建完整语义；
- 写入后可以从持久化 payload 严格回读。

本文不猜测该语义段的实际字段名或版本标识符。

### 11.4 历史兼容

- 历史 EvidencePack 继续可读；
- 不自动补默认字段后伪装成新版；
- 不自动推断 Hook Discovery sufficiency；
- 不改变历史 bytes、hash 或 Artifact identity；
- 新需求类型不能消费缺少新版语义的历史 pack，除非另有显式兼容合同；
- 兼容展示不能反向改变持久化事实。

### 11.5 避免 EverythingPack

现有 EvidencePack 已包含较多检索、发现、模型、工具和展示字段。新语义段必须只增加 Hook Discovery 所需稳定事实。

禁止继续加入：

- 完整 prompt 历史；
- token/latency；
- exporter 专用 span；
- Dashboard 字段；
- 隐藏思维链；
- Build/Runtime/Product 最终结果；
- 不适用于本需求类型的大量 nullable 字段。

## 12. 权威与接口边界

### 12.1 权责映射

| 事实 | 目标 owner | 其他层允许做什么 |
| --- | --- | --- |
| 原始来源身份 | 对应来源所有者 | 引用和回读 |
| Document/Chunk 身份 | 共享检索基础能力 | 检索和展示 |
| 检索路径结果 | 对应 retriever/provider | 保留原始结果和故障 |
| 证据准入 | RAG-1A 单一语义所有者 | 委托验证 |
| Hook/方案备选项关系 | 同一语义所有者 | 消费结果 |
| 三层充分性 | 同一语义所有者 | Graph/Planner 消费，不重算 |
| EvidencePack payload 语义 | 同一语义所有者 | Registry 委托，Store 写入 |
| EvidencePack 持久化提交 | 既有 ArtifactStore/C5 所有者 | 公共结果引用 receipt |
| Graph 路由 | 现有 StateGraph | 公共入口调用，不解释路由 |
| Approval/副作用 | 现有控制面 | RAG/ER 只提供输入 |
| 展示 | 公共适配器/CLI | 展示冻结结果 |
| Trace/Eval | 后续独立所有者 | 只读取可信投影 |

### 12.2 单一语义所有者

RAG-1A 的同一纯语义所有者必须负责：

- 读取需求类型；
- 规范化检索路径/覆盖事实；
- 验证来源准入；
- 建立 Hook/方案备选项关系；
- 计算三层充分性；
- 构造并验证新版 EvidencePack 语义段。

readiness 兼容层、Graph、Registry、公共入口和测试只能委托，不得复制另一套来源/需求类型/充分性解释。

### 12.3 控制面边界

- 证据充分性可以作为 Planner/Graph 的可信输入；
- 证据充分性不等于人工 Approval；
- RAG score、reranker score、LLM confidence、Trace 或 Dashboard 不能授予副作用权限；
- ArtifactStore commit 只证明 EvidencePack 持久化，不证明 Hook 正确或产品成功；
- 控制面不应重新计算证据充分性。

RAG-1A 与 RAG-1B 是同一项工程证据能力的两个实施阶段，不是两个独立子系统或两个产品：RAG-1A 固定并实现证据语义，RAG-1B 让现有产品入口采用同一语义和公共执行结果。

### 12.4 领域特化与 actual 污染边界

BetterHitFeedback、WallCrawler 和固定 GTFO R8 路径可以作为领域 Harness、确定性基线或 calibration fixture 保留，但不得拥有通用 Discovery、公共 Evidence executor 或 Coding Agent Runner 的语义：

- 通用 Workflow 不直接检查 BetterHitFeedback 方法名、correlation 文案或 WallCrawler 缺失项；
- 通用 intelligent evidence 结果不调用 Case 专用 post-run evaluator 解释产品终态；
- 公共入口不默认把自然语言请求绑定为 WallCrawler；
- 固定 `R8_IL_SYMBOLS` 和 `GTFOR8EvidenceProvider` 只能从明确的基线/领域入口调用；
- BHF/WC 专用符号可以存在于 fixture 和聚焦测试，但不得从测试常量进入实际模型输入或检索计划；
- 领域 Runtime、Edit Authority 和恢复代码继续受领域边界保护，不迁入通用 Runner。

RAG-1B 实施前必须清点 `evidence-request`、`intelligent-evidence-request`、`run-request`、`run_local_request()`、Product Executor 和所有直接 `build_graph()` 的入口。最终每个旧入口只能标记为委托、诊断基线、领域 Harness 或退出，不能继续拥有第二套 Store 写入、充分性解释或终态投影。

## 13. RAG-1A：证据语义

### 13.1 唯一目标

交付可验证的 Hook Discovery Evidence 语义：

```text
自然语言需求
  → Requirement Projection
  → Search Planning
  → Bounded Discovery Loop
  → 来源感知的检索路径事实
  → 证据准入
  → Hook/方案备选项关系
  → 三层充分性
  → 版本化 EvidencePack 语义
```

### 13.2 实施前只读清点

必须先精确核对：

- 当前 `EvidenceRequest`、`EvidenceItem`、`EvidencePack` schema；
- `to_artifact_payload()`、parser、Registry 和 fixtures；
- `EvidenceReadinessClassifier` 的所有规则和调用方；
- retriever 的检索路径顺序、容量、score、覆盖范围和故障事实；
- Graph、Planner、CLI 和专用入口中所有 `readiness` / `can_generate_patch` 解释；
- 历史 EvidencePack bytes/hash 兼容测试；
- BetterHitFeedback 和 WallCrawler 的真实来源。

完成清点后才能固定允许修改的精确文件清单。

### 13.3 预计实现范围

RAG-1A 可能涉及但不预先授权：

- Evidence 模型和序列化器；
- readiness 兼容适配器；
- retriever 检索路径/覆盖投影；
- 第一 Hook Discovery 切片的最小 Requirement Projection、Search Planning 和 Bounded Discovery Loop；
- 单一语义所有者；
- Registry 委托；
- 聚焦的单元/合同测试。

### 13.4 明确禁止

RAG-1A 不得：

- 修改 Graph 拓扑；
- 新增公共产品入口；
- 修改 ArtifactStore/C5 语义；
- 新增 Artifact 类型；
- 实施 MCP/HTTP/Dashboard；
- 实施 Trace/Eval 平台；
- 生产化 Dense/RRF/reranker；
- 修改 Build/Runtime/Product 逻辑；
- 建立第二 readiness 所有者。

### 13.5 RAG-1A 必需的 Agent Evidence Discovery 子层

#### 13.5.1 缺失能力与架构位置

RAG-1A 的目标不是只验证预先给定的工程方向。它必须能够在没有获得 Golden、历史实现、最终 Hook 身份或预期充分性结论的条件下，从自然语言需求和允许来源中形成可审计的工程调查过程。

给定 Hook 后验证其 SHA、MVID、metadata token、signature、方法体和 IL，只能证明 evidence verification 成立；不能证明系统具备 evidence discovery。RAG-1A 完成必须同时具备发现与验证能力。

Agent Evidence Discovery 位于 Agent 请求与 RAG/ER 工具之间：

```text
自然语言请求
  → Requirement Projection
  → Search Planning
  → Bounded Discovery Loop
  → RAG/ER retrieval and precise verification
  → Evidence Reasoning
  → EvidencePack
```

它是 RAG-1A 达成自然语言到工程证据发现目标所必需的子层，不属于底层 BM25、Dense、symbol、metadata 或 IL provider，也不是独立产品、通用 Agent 框架或第二控制面。

#### 13.5.2 Requirement Projection

Requirement Projection 将自然语言投影为第一 Hook Discovery 切片所需的最小、可审计工程语义，包括：

- 行为目标；
- 触发条件；
- 主体和目标对象；
- 硬约束；
- 禁止结果；
- 用户提供的实现线索；
- 可观察验收信号；
- 进入规划前必须回答的问题；
- 可以延期到规划或 Runtime 阶段的问题。

用户提供的实现线索不得自动升级为实现决定。例如“可以调查爬梯子逻辑”表示需要调查梯子机制解决了什么问题，不表示必须复制梯子路径或采用固定路线。

Requirement Projection 不得输出：

- 最终预期 Hook；
- Golden Case 或 judgment identity；
- expected evidence 或 expected missing evidence；
- expected sufficiency；
- expected continue/block；
- Annotation 中的 acceptable/forbidden Hook 身份。

第一阶段只实现 Hook Discovery 的有界投影，不建立面向所有 Agent 任务的统一 Requirement Framework。其他需求类型只有在真实产品切片证明需要后，才可以另行扩展，不得通过预留通用字段提前拥有。

#### 13.5.3 Search Planning

Search Planning 将 Requirement Projection 投影为有界调查计划，包括：

- 需要回答的工程问题；
- 必需和可选来源角色；
- 需要执行的检索路径；
- 每条路径的查询表达；
- coverage 要求；
- 需要进行精确源码、API、metadata 或 IL 验证的发现；
- 哪些未闭合问题会阻止实施规划；
- 哪些问题明确延期到规划或 Runtime 验证。

Search Plan 中出现完整方法身份，只能因为 earlier actual retrieval 已经发现该身份；不得从 Golden、历史实现、固定测试或预期 Annotation 复制。

Requirement Projection 和 Search Planning 只负责调查输入，不拥有来源真实性、EvidencePack 三层充分性、Approval、Apply、Build、Runtime 或产品结果。

#### 13.5.4 Bounded Discovery Loop

Bounded Discovery Loop 是 RAG-1A 的实际产品能力，不是校准 runner：

```text
根据 Search Plan 做开放发现
  → 从 actual evidence 形成 Hook/方案备选项
  → 对实际发现的方向做精确源码/API/metadata/IL 验证
  → 针对一个明确且仍可检索的缺口最多补充一次查询
  → 冻结 actual facts
  → 交给 Evidence Reasoning
```

第一阶段固定为有界过程：

- 一次开放发现；
- 一次针对实际发现方向的精确验证；
- 最多一次由明确缺口触发的补充检索。

不得演变为无限自循环、任意工具自主选择、通用任务分解框架或第二 Agent 工作流。若补充检索后仍缺少 planning-blocking evidence，应产生 bounded partial 或 block，而不是继续扩大搜索。

#### 13.5.5 单一所有权与接口

| 事实或决定 | 唯一职责 |
| --- | --- |
| 自然语言工程语义投影 | Requirement Projection |
| 调查问题、来源角色和检索计划 | Search Planning |
| 实际检索与精确验证执行 | Bounded Discovery Loop 调用既有 RAG/ER 工具 |
| 当前来源身份与物理事实 | 原来源、索引、metadata/IL owner |
| 证据准入、关系和三层充分性 | 既有 RAG-1A 单一证据语义所有者 |
| 持久化证据结果 | EvidencePack |
| expected facts 与比较 | 独立 Calibration Eval |
| 副作用授权和产品状态 | 既有控制面 |

不得因增加 Agent Evidence Discovery 而新增第二 Evidence Artifact、第二充分性规则表、第二 Graph route、第二 Store commit truth 或新的 Approval Identity。

#### 13.5.6 失败边界

- 无法形成有意义的工程问题：返回需求投影不足；真实交互可请求澄清，冻结校准题只能产生 bounded partial/block；
- 无法形成来源或查询：返回搜索规划不足，不声称已完成检索；
- 必需检索路径失败：retrieval insufficient；
- 只发现名称但无法绑定当前身份：engineering insufficient；
- 只发现 `nop; ret`、abstract 或 supporting lead：不得提升为行为事实；
- 证据相互冲突：contradictory/block；
- 明确缺口在一次补充检索后仍未闭合：planning block；
- actual 提前读取 Golden 或历史答案：本次校准无效，不计作普通能力失败；
- Eval 或 Trace 失败：不得修改已冻结的 actual EvidencePack。

### 13.6 当前偏差复盘与纠偏基线

本节记录 RAG-1A 从 fixture 到真实 Agent Discovery 实施过程中已经观察到的偏差。它用于解释当前工作包和止损依据，不建立新的合同、状态机或审批链。

#### 13.6.1 偏差形成过程

1. **Golden/Data Readiness 阶段**：actual/expected 隔离、历史答案泄漏、当前版本来源身份、BHF/WC 正负向标准和可复现重放是必要准备；但该阶段持续过久，逐渐形成“风险 → 字段 → hash → validator → 负向门”的实现惯性，而当时尚无真实 RAG 输出消费这些结构。
2. **第一版 RAG-1A**：已知 Hook 和 expected missing 被注入 actual，只形成“给定方向 → 验证方向”。移除注入是正确纠偏，并暴露出 discovery 缺失。
3. **Phase 2A/2B**：Requirement Projection 和 Search Planning 补齐了“自然语言 → 决定调查什么”的必要能力；偏差从模型开始承担 requirement、question、family、source 等 identity 以及跨数组引用时出现。Agent 的工作思路逐渐变成第一次 observation 前必须一次写对的数据库拓扑。
4. **Phase 2C**：严格 EvidencePack 回读、跨引用验证、legacy bytes/hash 保真和篡改负向门中有保护物理事实的必要部分；但主线一度从“发现真实证据”偏向“让只读 EvidencePack 的全部字段永久一致”。
5. **Phase 3 后的真实 BHF 调试**：Search Plan 不闭合、family 引用不稳定、代码查询表示不合适、来源标识选择错误、IL 重载身份不精确、模型输出截断和 requirement identity 重复先后暴露。检索表示、来源绑定和 metadata token 精确读取属于真实能力建设；把模型质量问题持续转化为 Schema、validator、correction、版本和兼容规则则会再次偏离。

准确归纳为：

```yaml
precursor: long_fixture_and_contract_phase
clear_turning_point: phase_2b_to_phase_2c
dominant_symptom: model_must_build_exact_topology_before_first_observation
```

#### 13.6.2 保留能力与停止扩张项

已经由真实工程完整性需要证明、应继续保留的内容：

- actual/expected 隔离；
- 来源 SHA、MVID 与 metadata token；
- IL 精确读取；
- `observed` / `inferred` / `unknown`；
- `support` / `conflict` / `missing`；
- EvidencePack commit/read 与严格回读；
- Hidden-Golden expected truth 隔离；
- 运行内短 handle；
- 模型不拥有 authority、tool、路径、hash 或精确工具参数身份。

在第一个真实下游消费者暴露缺口前，停止继续扩展：

- 模型生成内部 identity 或重复跨对象引用；
- 新 EvidencePack 字段与持久化版本；
- 与当前真实输入无关的 legacy 兼容扩展；
- 新 Trace 平台、控制面或通用 parser/schema 框架；
- 为单一模型错误增加永久产品规则。

#### 13.6.3 不围绕假设优化的四问

每项修改开始前只回答四个工程问题：

1. **来自哪次真实运行失败**：明确请求、失败阶段、物理事实和为什么无法继续；不能只写“未来可能需要”。
2. **是否让同一真实运行前进一层**：按 `planning → source → metadata → IL → EvidencePack → Eval` 计；新增测试、错误码、字段或版本本身不算前进。
3. **谁真实消费持久字段**：必须指出现有消费者、被改变的决定以及删除后会失败的真实用例；否则留在运行报告，不进入 EvidencePack。
4. **属于事实完整性还是输出质量**：来源伪造、Golden 泄漏、不存在的 observation 引用、未观察 metadata 就读取 IL、Store 回读改写需要 fail-closed；重复语义、普通 query 质量、blocker/deferred 范围、排序和表达冗长应进入 Eval 或诊断，不应永久阻止第一次只读工具调用。

模型 identity 记账职责已经从 provider-facing Projection/Search Plan 中移除，确定性代码可以生成 requirement、question、lane 和 family identity 并展开到既有持久 Search Plan。最新完整 BHF 随后在 Search Planning 阶段因多个 query family 产生完全相同的物理 dispatch 而停止，错误码为 `SEARCH_PLAN_QUERY_FAMILY_DISPATCH_AMBIGUOUS`，工具调用和 observation 仍为零。该错误没有伪造工程事实，属于 planning quality；当前正确修复方向是在确定性合并层折叠同一 investigation 内物理等价的 dispatch 并记录 quality finding，而不是恢复模型 identity 或新增持久化验证。

#### 13.6.4 当前唯一 RAG 能力工作包

当前不扩大为完整 Coding Agent，也不继续完善证据治理。唯一能力目标是：

> 自然语言 BetterHitFeedback 请求在不读取 Golden 和历史实现的条件下，实际完成 `source → metadata → IL → EvidencePack`。

工作包 A：模型 identity 记账移交确定性代码。该工作已经形成当前 WIP，但尚未形成独立 checkpoint。

- 模型只表达需求语义、首个工程问题、查询表达、来源选择以及 planning/deferred 的语义内容；
- 确定性代码生成 requirement、question、family 的运行内 identity，建立引用，从 Registry 填充 authority 与实际工具，并展开到既有持久 Search Plan；
- 模型侧优先使用嵌套语义结构，不再输出需要跨数组手工对齐的 identity；
- 相同语义或物理 dispatch 重复由确定性代码折叠并记录 planning quality finding，不在第一次 observation 前永久阻断只读检索；
- 不新增 EvidencePack 版本、模型分支或 Golden 修改。

工作包 B：当前只允许先完成同一 investigation 内完全相同 dispatch 的确定性折叠，然后固定 Qwen 4B、当前自然语言请求、allowlist、source index 和程序集，再运行一次完整 BHF。该运行不重试、不调整 Prompt、不运行 Phi/Terminal，也不读取 annotation；必须记录：

```text
requirement_projection
search_plan
source_retrieval
identifier_selection
metadata_dispatch
il_dispatch
evidence_pack_commit
strict_rehydrate
```

按第一真实失败层分流：

| 第一失败事实 | 归因 | 下一所有者 |
| --- | --- | --- |
| 相关源码没有进入窗口 | `retrieval_relevance_failure` | RAG source/BM25/symbol 表示 |
| 相关源码进入但模型未选择 | `source_identifier_selection_failure` | 模型或 selection 表示；不修改 validator |
| metadata 绑定到错误方法 | `source_to_metadata_mapping_failure` | RAG/ER identity bridge |
| IL 成功但因果关系不足 | 工程证据不足，不自动视为系统故障 | Evidence Reasoning 与 Eval，可产生 block |
| EvidencePack 成功 | actual 已形成 | 立即运行 BHF Hidden-Golden，不再重构 |

同一工作包若失败，应冻结第一失败层的物理证据并停止，不在同轮继续修改其他层。

## 14. RAG-1B：公共证据入口采用

### 14.1 唯一目标

把 intelligent evidence 产品入口收敛为：

```text
旧输入适配器
  → 公共证据预检/执行边界
  → 既有 StateGraph 证据路由
  → 真实 ArtifactStore 结果
  → 结构化证据执行结果
  → 展示
```

### 14.2 权威退出

完成后，旧 intelligent evidence 入口不得继续：

- 直接创建 Graph；
- 直接调用 Graph；
- 直接写业务 Store；
- 根据 `current_stage`、summary、claims、文件存在或 Store totals 判断终态；
- 重算 RAG-1A 充分性；
- 伪造未发生的 Store receipt。

### 14.3 公共结果边界

精确结果 schema 由 RAG-1B 实施前合同确定。至少需要区分：

- 平台执行状态；
- 证据领域结果；
- 实际 Store receipt；
- 已提交的 EvidencePack ref；
- 失败阶段；
- blockers；
- 副作用是否开始；
- 展示是否完成。

Store 已提交不等于证据充分；证据不足不等于平台失败。

### 14.4 前置条件

RAG-1B 代码实施前必须：

- P2.2 后续修正完成并独立验收；
- RAG-1A 合同和实现完成；
- 公共入口/Graph/Store/旧兼容/结果边界经过独立合同审核；
- 当前活跃入口清点重新复核。

截至本文本轮状态同步，P2.2 Option B Product Executor 及其 terminal repair result follow-up 已独立验收并提交，因此第一项已经满足。该完成事实不自动满足 RAG-1A、RAG-1B 公共合同或活跃入口清点，也不授权启动 RAG-1B。

### 14.5 明确禁止

RAG-1B 不得：

- 顺带迁移 P2.4 或执行 P3；
- 新建 Controller；
- 复制语义所有者；
- 重定义 Graph 路由；
- 新增 Store 提交解释；
- 实施 Trace/Eval；
- 启动 Build/Runtime；
- 把旧入口逻辑平移到新的大型执行器。

### 14.6 与 Coding Agent v0 的交接

RAG-1B 不负责让检索、Planning 或充分性变得更聪明；它只让公共产品入口采用已经由 RAG-1A 证明的 Evidence executor，并消除旧入口中的重复 owner。RAG-1B 之前允许 v0 internal alpha 通过内部调用面消费 committed EvidencePack，以验证真实下游需要哪些证据字段；RAG-1B 独立 checkpoint 后，同一消费链升级为 Coding Agent v0 public alpha：

```text
公共 Evidence executor
→ committed EvidencePack
→ 既有 Implementation Planning
→ 既有 Patch / Review / Dry-run
→ 隔离 Build/Test
```

该交接不得在 RAG-1B 内修改检索、Golden、证据关系或充分性算法；若下游消费暴露 EvidencePack 缺口，必须以具体读取失败、错误计划或 Build/Test 结果为依据返回对应 owner。

## 15. 第一验证切片

### 15.1 正向切片：BetterHitFeedback Hook Discovery

需要证明：

- 输入是自然语言功能需求；
- 搜索问题由需求类型形成，而不是硬编码最终 Hook；
- 当前来源、symbol/API/IL 等真实证据可回读；
- Hook/方案备选项来自已准入证据；
- 支持、冲突和缺失关系可审计；
- 达到规划就绪度时只允许进入实施规划；
- 结果不自动获得 Apply/Build/Runtime 权限。

BetterHitFeedback 的 Hidden-Golden Discovery Run 必须在没有收到 `ES_Hitreact.ActivateState` 最终身份的条件下，从自然语言和允许来源发现并精确绑定有依据的观察方向；同时不能把伤害输入单独解释为反应结果。BHF 在本阶段评测“是否发现并验证了正确方向”，不再以 `sufficient/continue` 作为方向评测通过条件；是否足以进入实施规划由真实 EvidencePack 的充分性与 ImplementationPlanner 独立裁决。

#### 15.1.1 BHF 方向评测投影（2026-08-17 登记）

BHF 的冻结 annotation v5 及 `frozen_judgment_hash=C43DA97715FF4408FF1687EBB7B4756B2F5FED8D3EBF1ADF78A53EED8F1507A1` 保持不变，不根据当前 actual 输出改写。Eval 在 annotation 之上采用显式、版本化的 Case 评分投影：

- **计分**：可接受的观察方向及其当前物理身份、禁止方向未被当作唯一权威、来源/身份验证、actual/expected 隔离和泄漏检查；
- **诊断但不决定 BHF 方向通过**：`expected_sufficiency`、`expected_control_action`、尚缺关系证据和 Patch 是否允许；
- **合法组合**：`discovery_direction=correct`、`evidence_sufficiency=insufficient`、`planning_action=block` 可以同时成立，并可通过 BHF 方向评测；
- **权限边界**：Hidden-Golden 比较不能授予 Patch、Apply、Build 或 Runtime 权限，ImplementationPlanner 只消费 actual EvidencePack；
- **任务分离**：Coding Agent v0 internal alpha 的正向 Patch/Build 链使用一个当前允许来源足以支持、具有自动 Build/Test 判定的独立 actual-only 工程任务，不用 BHF 的 expected truth 补足实现依据。

该评分投影只适用于 BHF 的方向校准。WallCrawler 继续按自身负向证据语义评价相关结构、关键行为缺失和 `insufficient/block`，不得自动继承 BHF 的计分字段。

### 15.2 负向切片：WallCrawler Hook 证据不足

需要证明：

- 相关名称、社区内容、Dense 命中或模型推测不能自动成为当前事实；
- 搜索范围和 coverage 被记录；
- 缺失证据被明确表达；
- 系统返回 evidence insufficient/partial，而不是编造 Hook；
- unsupported planning 被阻止；
- 没有业务副作用。

WallCrawler 的 Hidden-Golden Discovery Run 必须在没有收到冻结缺失清单和预期 block 结论的条件下，从自然语言推导工程约束，发现 PathMove、Ladder、locomotion、zone/layout 等相关结构，并根据 `nop; ret`、abstract 和行为证据缺失产生 `insufficient/block`。用户提供的梯子与 JSON 路径只能作为调查线索，不能自动升级为实现方向或当前事实。

### 15.3 不能使用的验收方式

- 把预期 Hook 写死在实现中；
- 从当前实现输出反向生成 golden；
- 使用空 ground truth；
- 只用正向案例；
- 只证明 Artifact 写入成功；
- 只证明测试数量增加；
- 用 Build/Runtime 成功替代 retrieval/sufficiency 正确性。

### 15.4 Hidden-Golden Discovery Run

Hidden-Golden Discovery Run 是对 RAG-1A 真实 Agent Evidence Discovery 能力的 expected truth isolation protocol，不是 Discovery Loop 本身，也不得实现第二套发现逻辑。它不是 hidden test、blind benchmark 或 held-out benchmark。BetterHitFeedback 的 Golden 形成使用了历史实现和有界 Runtime 观察作为 expected 侧的参考辅助，因此不能声称严格盲测；这里的 Hidden 只表示 actual 生成期间隔离 expected truth。比较器必须显式登记 Case 评分投影，区分计分字段、诊断字段和权限字段；不得把 annotation 中存在的每个 expected 字段自动提升为同一完成门。

```text
              Golden annotation
                     │
                     × actual 冻结前不可见
                     │
自然语言请求
  → 真实 Requirement Projection
  → 真实 Search Planning
  → 真实 Bounded Discovery Loop
  → 真实 Evidence Reasoning
  → 冻结 actual EvidencePack
                     │
                     ▼
          Eval 加载 Golden expected facts
                     │
                     ▼
          比较 actual / expected 并归因
```

Actual 运行只可读取：

- 原始自然语言请求；
- manifest 登记的 allowlist 和 corpus identity；
- 内容身份绑定的当前源码、API、程序集、metadata/IL；
- 当前检索配置；
- 由当前请求形成的 Requirement Projection 和 Search Plan。

Actual 冻结前不可读取：

- Golden annotation 和 judgment hash；
- acceptable/forbidden Hook 完整身份；
- expected evidence、expected missing evidence、expected sufficiency 和 expected action；
- 历史成功实现和 expected 侧 Runtime support records；
- 固定答案测试、项目状态中的已选 Hook 和先前 Agent/RAG 输出。

Hidden 表示 expected truth 对 actual 不可见，不表示隐藏 actual 过程。Actual 必须保存足以审计以下关系的结构化事实：

```text
request
  → requirement projection
  → search plan
  → executed queries and lane coverage
  → discovered evidence
  → precise verification
  → Hook/方案备选项
  → support/conflict/missing
  → three-layer sufficiency
  → EvidencePack
```

不要求保存私有思维链。可追溯性由结构化输入、查询、coverage、证据引用、身份验证、关系、原因和稳定 ref/hash/version 提供。

Eval 只能在 actual 冻结后读取 Golden；它只能比较和归因，不得补齐、重算或修改 actual facts。若 actual 在冻结前读取任何 expected truth，本次校准协议失效，不得把结果计作 Discovery 能力成绩。

## 16. 能力采用矩阵

| 原始/历史能力 | 当前裁决 | 当前用途或限制 |
| --- | --- | --- |
| Document/Chunk contract | adapt | 精确 schema 以当前源码为准 |
| source metadata/locator | adopt | 必须补 source identity/revision/content 区分 |
| file/content hash | adopt | 用于缓存和内容身份，不单独作为来源身份 |
| incremental ingestion | adopt | 使用前仍需 current source validation |
| generic recursive splitter | adapt | 仅作为文档/后备路径 |
| semantic splitter | experimental | 不用于破坏源码方法/签名边界 |
| source-specific chunking | adopt | 文档、源码、IL、日志、Artifact 分别处理 |
| LLM chunk refinement | experimental | derived annotation，不覆盖 raw source |
| image caption | defer | supporting/auxiliary，不证明 Hook |
| BM25/Sparse | baseline | 普通 RAG 和 ER 文本路径 |
| exact/live source lookup | baseline | ER 当前事实路径 |
| symbol/metadata/IL | baseline_for_er | Hook Discovery 工程路径 |
| Dense | experimental | 当前默认关闭，不是完成门 |
| RRF | experimental | 普通 RAG 可实验，ER 不据此判 truth |
| Cross-Encoder rerank | deferred_experiment | 需下游收益证据 |
| LLM rerank | deferred_experiment | 需成本、稳定性和质量证据 |
| citation/source span | adopt_and_extend | 普通引用 + 工程 claim relation |
| ResponseBuilder | standard_rag_only | ER 中只是 Presentation |
| Knowledge Hub | defer | 后续只读产品面 |
| MCP stdio/schema discipline | retain_reference | 不进入 RAG-1A/RAG-1B |
| HTTP API | defer | 不是第一阶段前置架构 |
| Dashboard | separate_future_work | 不成为 truth owner |
| Trace platform | separate_document | 本文只定义 emit boundary |
| Eval platform | separate_document | 本文只定义 quality questions |
| Multimodal production | defer | 由真实案例触发 |
| Agentic retrieval router | defer | 不因工具存在自动建设 |
| complete RAG platform migration | reject | 复用现有实现，不重建目录 |
| second Evidence Artifact | reject | 第一阶段复用 EvidencePack |
| new RAG/Evidence Controller | reject | 使用 provider/semantic owner/public boundary |

## 17. 与 Trace/Eval 的接口边界

Trace/Eval 需要覆盖标准文档 RAG、ER、控制面和执行循环，但其完整设计不属于本文。

### 17.1 可评测的可信运行投影

RAG/ER 至少应能够向未来独立能力提供可信投影：

- 请求/查询身份；
- 需求/类型身份；
- 已执行检索路径；
- 搜索范围和覆盖；
- 来源/证据 ref；
- 被排除的证据和理由；
- Hook/方案备选项关系；
- 三层充分性；
- EvidencePack ref；
- provider/model/tool 运行身份的非权威观测；
- 延迟/token/成本挂点；
- 故障/回退。

这里的“可信投影”是实际运行事实，不是 Eval truth：

- RAG/ER 产生 actual facts，例如实际检索到的 ref、排名、coverage、准入/排除关系和充分性结果；
- Golden Case 中的 expected evidence、accepted/forbidden decision、预期充分性和标签属于独立 Eval 数据集；
- Eval runner 比较 actual facts 与 expected facts，并产生指标、分数和回归判断；
- RAG/ER 不写入 Golden 标签，不根据当前输出反向生成 expected facts，也不把 Eval 分数保存为 EvidencePack 事实；
- 测试、Dashboard、Trace 和 Eval 不能为了让 Case 通过而改写实际检索、来源准入或充分性结果。

Hidden-Golden 不降低 actual 的可追溯性，只隔离 expected truth：

- RAG/ER 保存实际执行的需求投影、搜索计划、query、coverage、证据、精确验证、关系和充分性；
- Calibration Eval 单独保存 Golden judgment identity、frozen actual ref、比较协议和失败归因；
- expected facts 不进入 EvidencePack，actual facts 不因 Eval 结果被修改；
- 当前阶段使用各原 owner 的 ref/hash/version 建立关系，不预设一个全局根 ID；
- 后续 Trace 合同可以消费这些事实，但不得重算 Discovery 或充分性。

### 17.2 实验复现身份原则

为了让独立 Eval 能够比较、分组和复现实验，RAG/ER 必须为适用运行暴露下列身份或稳定版本引用：

- prompt/template 的稳定 ref/hash/version；精确模板内容由既有受控配置或源码 owner 像代码一样进行版本管理；
- retrieval configuration version，覆盖适用的检索路径、lane budget、Top-K、过滤、融合和 fallback policy；
- model/provider/deployment version；
- index snapshot/version 及其适用来源覆盖身份；
- reranker provider/model/configuration version；
- 运行所消费的源码、文档、程序集或 Artifact 身份仍由各自原有 owner 提供，不由上述版本字段替代。

这些身份只证明“本次运行使用了什么配置和资源”，不证明来源内容为真、回答忠实、工程证据充分或产品执行成功。它们：

- 不进入 Approval Identity；
- 不成为 EvidencePack 的工程事实或三层充分性输入；
- 不授予 Graph、Store、Apply、Build 或 Runtime 权限；
- 只作为复现、实验分组、方差分析、消融和 Trace 关联输入；
- 运行结果、EvidencePack、Trace/Eval 只保存稳定 ref/hash/version 或经合同允许的脱敏投影，不复制完整私有 prompt；
- secret 不得进入 prompt/template；需要 secret 的运行时注入必须由既有敏感信息 owner 管理，且不成为模板内容或复现记录；
- prompt/template ref 无法解析到当时的精确版本内容时，该次运行不得进入正式可比较 Eval；
- 缺少正式比较所需的关键身份时，该次运行不得进入可比较的正式 Eval 报告，但除非对应运行合同另有规定，不因此重算平台执行结果；
- 必须遵守 source-disclosure、model-admission、脱敏和敏感信息边界，不因复现要求保存 secret、完整私有 prompt 或不必要绝对路径。

Eval dataset/protocol version 属于独立 Eval 运行输入，不属于 RAG/ER 机器结果。上述身份的精确 schema、canonical bytes、owner、nullability 和兼容策略由对应实施合同及独立 Trace/Eval 文档固定；本文不猜测字段名。

### 17.3 单向消费与失败边界

边界：

- Trace/Eval 不写回 EvidencePack 事实；
- Trace/Eval 不重算充分性；
- Trace/Eval 不改变 Approval、Store 提交或产品终态；
- exporter 失败不改变冻结机器结果；
- 隐藏思维链不进入 trace；
- 精确 trace schema、指标、阈值和 Dashboard 由独立文档决定。

### 17.4 既有 Trace/Eval 资产的复用边界

后续最小 Eval 合同和独立 Trace 文档不得把当前工程误判为从零开始。正式新增 runner、metric、comparison、quality gate 或 baseline provider 之前，必须逐项清点并裁决下列既有资产：

- `src/core/trace/` 的 query/ingestion `TraceContext` 与 JSONL collector；
- `TraceEvent` 和 intelligent evidence 的 `workflow_trace` 局部事件/Artifact；
- `AgentQualityEvaluator` 的检索、Hook、readiness、decision、task/file outcome 与 cost/latency 指标；
- `RetrievalRegressionRunner` 的版本化 dataset/observation、可比性和 promotion 约束；
- `QualityGatePolicy` 及其 fail-closed threshold evaluation；
- `OfficialArmARunner`/`RgLiveReadProvider` 的确定性 `rg + live read` 基线与可复现运行身份；
- `build_transition_eval_gate_report` 的既有 workflow transition 质量门。

每项只能得到 `adopt`、`adapt`、`defer` 或 `reject` 的显式裁决及理由。不得在未完成该 adoption matrix 前建立功能重复的 evaluator、regression comparator、quality policy、Arm A runner 或 transition gate。

本节在目标文档 checkpoint 时只登记 adoption matrix 的义务。联合设计曾在 Git checkpoint `7938ced`（`docs(rag-er): checkpoint changes-required joint contract design`）中物化并完成独立审核：`contract_materialization_verdict=approved`、`rag_1a_contract_verdict=changes_required`、`minimal_eval_contract_verdict=changes_required`，没有获得代码实施或资产采用授权。该联合合同已从 active tree 删除，只作为 Git 历史中的设计与边界输入保留；如需核对，必须从该精确 checkpoint 只读回看。两切片 fixture handoff 完成后，应根据当时的真实数据与当前源码重新收缩 RAG-1A 和 Calibration Eval 合同，不得直接恢复或实施历史对象中的具体 schema、runner、指标、文件范围或测试门。后续合同仍须分别裁决普通 `EvalRunner`、Ragas evaluator、局部 Trace/Event、`AgentQualityEvaluator`、`RetrievalRegressionRunner`、`QualityGatePolicy`、`OfficialArmARunner` 和 transition gate；不能用 inventory 行或 changes-required 历史设计代替采用结论。

复用不等于提升语义权威：

- 现有 Agent quality Case/observation schema 可以作为最小 Eval 合同的适配输入，但不会自动拥有 RAG-1A 的三层充分性、拒答、`insufficient/contradictory` 或 EvidencePack actual facts；
- 现有 transition gate 继续只判断其登记的 workflow transition 条件，不得决定检索相关性、来源准入或工程证据充分性；
- Arm A 只作为 A–D 实验中的确定性基线和复现设施，不是产品 Trace root，也不自动获得 promotion 资格；
- 现有局部 Trace/Event 可以被未来统一 Trace adapter 消费，但不得通过名称或字段相似直接拼接成统一 trace truth；精确关联字段和传播规则由独立 Trace 合同决定；
- 现有 calibration/development fixture 只证明 evaluator、runner 和 gate 的机械行为；没有真实 held-out Case、正式 protocol identity 和可比较运行报告时，不得声称产品质量改善。

独立 Trace 合同需要解决的是可信关联、基数和传播规则，而不是预先规定一个 ID 强行贯穿全部对象。一个请求可以关联多次检索、Graph/repair attempt、Artifact commit、Build/Runtime 和 Eval run；同一 Artifact 或 Eval 数据也可能参与多次运行。具体是一对一、一对多还是多对多，以及哪些 identity 可以作为可信 join key，必须由原 identity owner 和后续 Trace 合同共同固定。关联不完整只影响观测完整性，不得改变 Approval、Graph route、Store commit truth 或冻结机器结果。

### 17.4.1 证据约束型校准夹具轻量模式

BetterHitFeedback 与 WallCrawler 两切片完成后，可以把其中经实际重放证明必要的共同边界提炼为“证据约束型校准夹具”（Evidence-grounded Calibration Fixture）轻量模式。该模式用于后续相似工程评测任务的讨论输入；是否复用必须根据新任务的问题、可取得证据和失败边界另行确认，不能因任务名称或字段相似而自动套用。

可复用内容只限以下六项结构原则：

1. 题目与 expected judgment 分离；
2. 被测检索范围采用明确 allowlist；
3. 物理事实从内容身份绑定的输入重算；
4. expected judgment 独立于被测系统输出，并由明确登记的标注/复核者拥有；当前两切片采用 operator-confirmed requirements + independently model-reviewed technical calibration annotation，不表示独立人类标注、盲测、held-out 或 promotion；
5. 被测系统输出与 annotation 只在比较阶段相遇；
6. 脚本只报告重放事实，不授予产品或质量 verdict。

这六项原则描述的是如何制作可复算、可比较且不向被测系统直接暴露 expected judgment 的校准夹具，不是通用 Eval schema、runner、Registry、Readiness authority、质量门或产品控制面。当前两个切片也不能证明该模式已经覆盖其他任务类型、RAG 泛化能力、held-out 表现或产品晋级条件。

后续遇到相似内容时，应先讨论并核对新任务的输入表示、证据 owner、允许检索范围、人工判断来源和失败边界，再决定是否复用该模式。只有多个不同任务的实际夹具证明存在稳定的共同机械步骤时，才允许另行讨论共享工具；不得从当前两条切片直接推导通用评测平台。

### 17.5 最终 Trace、Eval、质量门、CI/CD 与 Dashboard 工程闭环目标

本节记录长期工程指导目标，不是 RAG-1A 的实施合同，也不授权建设完整 Trace/Eval 平台、CI 流水线或 Dashboard。它的作用是把当前分散在 RAG、ER、控制面、Artifact、Build/Runtime、Eval 和历史可观测性材料中的原则收敛成同一条最终产品闭环，同时防止“治理和面板建设替代检索与证据能力交付”。

目标不是收集更多日志，而是让每次真实请求和每次代码、配置或模型变更最终都能够回答：

- 本次运行实际执行了什么，使用了哪些源码、语料、配置、模型和工具版本；
- 检索了哪些范围，各 lane 的 coverage、命中、失败和 fallback 是什么；
- 哪些证据被接纳或排除，形成了哪些 Hook/方案备选项、支持、冲突和缺失关系；
- 为什么允许继续规划，或为什么因证据不足而停止；
- Graph、ArtifactStore、Build、repair、Runtime 和产品终态分别发生了什么；
- actual facts 与独立 Golden expected facts 的差异是什么；
- 相对冻结 baseline 是否发生质量、稳定性、延迟或成本回退；
- 回退应只报告、产生告警，还是阻止 PR 合并或 Release；
- 使用者能否从面板中的失败指标逐层定位到 Case、检索路径、EvidencePack、Artifact、Receipt、Graph 节点和 Build/Runtime 事实。

长期闭环如下：

```text
代码、配置、语料、模型或产品变更
  ↓
单元、集成、静态与确定性安全测试
  ↓
冻结 dataset / judgment / protocol / corpus / config identity
  ↓
RAG / ER / Agent / Graph / Store / Build / Runtime 产生可信 actual facts
  ↓
Trace 按经审核的关联规则保存实际发生的事实
  ↓
Eval 将 actual facts 与独立 expected facts 比较
  ↓
不可变评测报告与失败归因
  ↓
版本化 QualityGatePolicy
  ↓
PR / Nightly / Release 分层执行、报告、告警或阻断
  ↓
Dashboard 只读展示、趋势比较和失败钻取
```

各层职责必须保持正交：

- **Trace** 只记录实际发生的事件、身份、关联、阶段、延迟、成本和失败，不决定证据是否正确，不生成 Golden，也不授予副作用权限；
- **Eval** 只比较可信 actual facts 与独立 expected facts，产生适用指标和失败归因，不把标签或分数写回 EvidencePack、Graph、Store 或产品结果；
- **Gate** 只消费已冻结的 Eval 报告、适用 Case 和版本化策略，将指标转化为通过、告警或阻断结论，不重新执行检索或解释单条业务事实；
- **CI/CD** 负责触发、隔离运行、保存报告 artifact、传播 job verdict 和执行发布策略，不成为新的业务事实 owner；
- **Dashboard** 只读取结构化报告与可信投影，展示当前 commit、dataset/protocol/corpus/config identity、指标、baseline delta、失败 Case、延迟和成本趋势，不自行计算 gate truth。

未来 Trace 至少应能关联适用的请求、检索、Graph attempt、Artifact、Store Receipt、Build/Runtime 和 Eval run，但本文不预设单一全局根 ID。关联可能是一对多或多对多；精确传播、可信 join key、采样、脱敏、保留期限和 exporter 由后续独立 Trace 合同固定。Trace 缺失或 exporter 失败只能降低观测完整性，不能重算已经冻结的机器结果。

未来评测与 CI/CD 应分层采用：

- **PR**：运行快速、稳定、确定性的 schema/serializer、Golden 泄漏、数据身份、stale corpus、forbidden Hook/文件、false continue 及已批准 calibration smoke。答案泄漏、不可比较却声称通过、证据不足仍继续等安全边界可以成为硬失败；检索分数、延迟和成本的小幅波动不得在没有批准 policy 和稳定数据前被随意设为硬门；
- **Nightly**：运行更完整的 development 数据、重复运行、方差、baseline/treatment、延迟、token、成本和 Dense/Fusion/reranker 实验，主要形成趋势与回归归因；只有经过独立批准且已证明稳定的规则才能阻断后续 promotion；
- **Release**：在后续数据成熟后使用冻结 held-out、fresh corpus、相同 protocol、明确 metric applicability 和版本化 QualityGatePolicy。Release gate 失败可以阻止发布，但 held-out、promotion 和正式百分比阈值不是当前 Data Readiness 或 RAG-1A 第一实现包的前置条件。

面板最终应支持以下最小诊断路径：

```text
失败 gate / 指标
  ↓
受影响 Case 与 actual/expected 差异
  ↓
检索 lane、范围、coverage、排名和 fallback
  ↓
接纳/排除证据及 Hook/方案支持、冲突、缺失关系
  ↓
EvidencePack 与三层充分性
  ↓
Graph / Store / Build / repair / Runtime 阶段
  ↓
原始 Trace、Artifact、Receipt、日志和版本身份
```

失败处置必须区分产品事实、评测基础设施和观测基础设施：纯读取、查询、评测或 exporter 失败可以按照以后批准的幂等策略重试；可能启动副作用的 Apply、Build、Runtime 不得因 Trace/Eval 或 Dashboard 失败自动重放。进程硬退出而没有形成结构化结果时，不根据面板、文件存在性或历史 totals 伪造成功或失败；未来恢复能力必须继续服从控制面和 effect recovery 合同。

本闭环是长期完成方向，不改变当前能力优先顺序：

```text
两切片 Data Readiness
  ↓
只收缩 source authority、lane coverage、planning predicate 等最小合同决定
  ↓
RAG-1A 检索、证据准入与充分性能力实施
  ↓
运行 BetterHitFeedback / WallCrawler calibration
  ↓
复用并适配既有 Evaluator 形成报告
  ↓
RAG-1B 活跃产品入口采用
  ↓
数据成熟后再建设完整 Trace / CI/CD / Dashboard 闭环
```

因此，完整 Trace、Langfuse/OpenTelemetry、正式 CI 晋级门、统一 Dashboard、40–60 条数据、held-out、promotion 和全部未来 provider/model/reranker 身份不得成为当前 Data Readiness 或 RAG-1A 的前置阻断项。Data Readiness 是能力实施前最后一个主动前置包；其通过后若继续扩建控制层、合同或可观测性平台而没有交付可运行的 RAG-1A 检索与证据能力，即违反本文的能力优先目标。

## 18. MCP、HTTP API 与 Dashboard 边界

### 18.1 MCP

当前可保留两类概念：

- Standard RAG 的只读 Knowledge Hub 工具；
- Mod Agent 的 Graph/Artifact 感知型只读/报告工具。

它们可以共享底层检索/provider，但不能共享执行权威。

第一阶段不新增 MCP 工具。未来 MCP 工具必须：

- 返回结构化检索或 EvidencePack 投影；
- 不直接调用工作流节点处理器；
- 不绕过公共入口、Graph、ArtifactStore 或审批；
- 保持 stdout 协议清洁；
- 写操作另行通过现有控制面批准。

### 18.2 HTTP API

HTTP API 不是 RAG-1A/RAG-1B 的前置架构。未来需要时，只能消费同一公共结果和只读模型，不得形成第二终态解释。

### 18.3 Dashboard

Dashboard 可以展示：

- 数据摄取状态；
- 文档/chunk；
- 检索诊断；
- EvidencePack；
- 后续 Trace/Eval 报告。

Dashboard 不得拥有来源事实、充分性、Store 提交或产品终态。当前 RAG 工作不扩建 Dashboard。

## 19. 隐私、敏感信息与模型边界

潜在敏感数据包括：

- 私有源码；
- 产品程序集与逻辑路径；
- API key 和配置；
- prompt；
- 文档 chunk；
- Artifact；
- Build/Runtime 日志；
- 用户输入和人工意见。

要求：

- 数据摄取前进行来源分类和授权；
- 检索按来源/collection/敏感级别范围过滤；
- 访问/敏感级别过滤缺失时 fail-closed；
- 外部 embedding/reranker/LLM 调用遵守现有 source-disclosure 和 model-admission 边界；
- 原始来源与派生内容分别标记；
- Trace/Eval 默认不保存 secret 和不必要绝对路径；
- 本地 provider 只降低外部传输风险，不解决检索错误或权威问题；
- 社区内容默认只作支持性/辅助输入；
- provider 输出不得自动成为当前事实。

## 20. 失败边界与停止条件

### 20.1 检索/ER 失败边界

- 某条检索路径失败：记录失败和覆盖范围，不伪造空结果为完整搜索；
- 来源读取/hash/版本失败：不得准入权威证据；
- 派生注释失败：保留原始来源，按需求类型决定降级；
- Dense/reranker 失败：允许回退到已验证基线，但记录回退；
- 语义投影失败：不得写入声称完整的新 EvidencePack 语义；
- Store 未提交：保留真实 receipt，不伪造 Artifact ref；
- 展示失败：不得改变已冻结的机器结果。

### 20.2 必须停止并重新审核

出现以下情况必须停止当前实施包：

- 需要新增 Artifact 类型；
- 需要第二充分性所有者；
- 需要修改 Graph 拓扑；
- 需要修改 ArtifactStore/C5 语义；
- 需要新 Controller；
- 需要重新解释历史 EvidencePack；
- Registry、Graph、公共入口或 Store 开始复制需求类型/来源/充分性规则；
- RAG score、reranker score 或 LLM confidence 被解释为事实；
- LLM 增强内容覆盖原始来源；
- 硬身份/安全过滤使用宽松包含；
- RAG-1A 扩张为完整 RAG 平台；
- RAG-1B 扩张到 P2.4/P3；
- Trace/Eval 被顺带实施；
- Golden 数据由当前输出反向生成；
- 第一切片依赖硬编码最终 Hook 才能通过；
- 新抽象只增加层数，没有交付检索/充分性新能力。

## 21. 文档门、实施门与完成门

### 21.1 权威目标文档门

本文从草案提升为仓库权威目标文档前必须：

1. 十二项决策完整落盘；
2. 历史材料优先级与采用矩阵闭合；
3. 在届时目标分支完成源码、测试、配置和入口清点；
4. 与控制面、产品合同、Harness、未来 Trace/Eval 文档的边界无冲突；
5. 第一正向/负向切片的需求和真实基准来源确定；
6. 文档内未决产品/架构决定为空；
7. 文档被 Git 跟踪并形成独立 checkpoint；
8. 通过独立文档审核。

文档权威化不要求先完成大规模数据集，也不自动授权代码实施。

### 21.2 RAG-1A 实施门

权威目标文档独立审核并形成 Git checkpoint 后，允许并行开展两项只读/合同工作：

1. RAG-1A 当前源码、测试、配置、入口和 owner 的有界清点及实施合同设计；
2. 独立最小 Eval/Golden Case 合同设计。

两项工作需要相互对齐接口，但不得互相复制权威：RAG-1A 固定能够稳定产生哪些 actual facts；最小 Eval 合同固定比较哪些 expected facts、如何标注和如何判定。只读 inventory 和合同设计可以并行，完整 Eval 平台、runner 实施和 CI 门禁不构成这些只读工作的前置条件。

最小 Eval 合同设计必须完成 §17.4 的既有资产 adoption matrix，并优先以适配方式复用 `AgentQualityEvaluator`、`RetrievalRegressionRunner`、`QualityGatePolicy` 和 `OfficialArmARunner`。矩阵必须核对 `AgentQualityCase`、`CaseObservation`、`RunManifest` 和 `AgentQualityReport` 能否无损表达 source identity、coverage、EvidencePack actual facts 和三层充分性；同时核对现有 `readiness_accuracy` 与 `false_continue_rate` 的标签和值域是否精确覆盖 RAG-1A 的证据不足继续规划边界。只有现有接口无法无损表达已经批准的 actual/expected facts、数据身份或比较边界时，才允许登记 `adapt` 并提出最小 schema 投影；该差异必须作为明确合同决定独立审核，不能在实现中隐式复制第二套 evaluator、指标、回归或晋级 owner。

最小 Eval 合同必须覆盖以下提纲：

1. 权威与非所有权边界；
2. Golden Case 数据合同；
3. actual facts 接口；
4. 数据来源、人工标注与表达变体；
5. BetterHitFeedback 正向 Case、WallCrawler 证据不充分 Case及后续 development/held-out 扩展边界；
6. 检索、EvidencePack、拒答和 Agent 决策指标；
7. A–D 确定性基线实验；
8. 复现身份和配置冻结；
9. runner、重复运行、方差和失败归因；
10. PR/Nightly/Release 分层门禁的延期边界；
11. RAG-1A 接口对齐门；
12. 完成门与禁止扩张项。

第一份最小 Eval 合同不得实施 Dense、Fusion、Cross-Encoder、完整 Trace 平台或 CI 全量门禁。

第一完成门只要求两条真实切片闭环：BetterHitFeedback 正向 Case、WallCrawler 证据不充分 Case、exact actual/expected facts 分离、正式 protocol identity、可复现基线运行，以及 Golden 不得从当前输出反向生成。扩展到 40–60 条或更多 Case、拆分 development/held-out 数据、promotion 门和长期统计稳定性属于后续数据成熟阶段，不阻断 RAG-1A 第一阶段合同和代码实施。

RAG-1A 代码实施必须同时满足：

- 有界所有者清点完成；
- 精确需求类型、语义段、兼容性和失败矩阵固定；
- 修改文件和禁止文件清单固定；
- BetterHitFeedback/WallCrawler 真实基准固定；
- RAG-1A 实施合同独立审核批准；
- 最小 Eval 合同独立审核批准；
- 两份合同对 actual/expected facts、复现身份和正负切片的接口无冲突。

RAG-1A 当前缺失能力的实施顺序是依赖链，不是三个并行开发任务：

1. **Actual Execution Isolation**：移除固定 Hook、固定缺口和 expected facts 对 actual 的注入；
2. **Agent Evidence Discovery Capability**：实现最小 Requirement Projection、Search Planning 和 Bounded Discovery Loop；
3. **Hidden-Golden Discovery Validation**：调用同一真实能力路径生成并冻结 actual，再由 Eval 与 Golden 比较。

第一步完成不要求 BetterHitFeedback/WallCrawler 保持原结论；移除答案注入后暴露 discovery 缺失属于有效结果。第二步不得实现为 BetterHitFeedback/WallCrawler 专用映射，应使用至少一条无关自然语言 smoke 证明不存在 Case 硬编码。第三步不得在 calibration adapter 中复制发现逻辑。

### 21.3 RAG-1A 完成门

- 单一语义/充分性所有者；
- 旧 EvidencePack 可读且 bytes/hash 未漂移；
- 新需求类型无法被旧 pack 冒充；
- 正向/负向语义测试通过；
- Registry/Graph/CLI 无重复规则；
- 无新 Artifact/Controller/Store 语义。
- actual 路径不存在固定 Hook、固定 missing evidence 或 expected action 注入；
- 自然语言可以形成可审计的 Requirement Projection 和 Search Plan；
- 至少一条无关自然语言 smoke 证明不是 BetterHitFeedback/WallCrawler 固定映射；
- Hook/方案备选项只能从已准入 actual evidence 形成；
- BetterHitFeedback 在 Hidden-Golden 条件下发现并验证有依据的观察方向，避免禁止方向成为唯一权威，并报告独立的充分性、动作和后续限制；BHF 方向通过不要求 `sufficient/continue`；
- WallCrawler 在 Hidden-Golden 条件下发现相关结构和关键行为缺口，产生 `insufficient/block`；
- actual 冻结前无法读取 Golden expected facts；
- Eval 只能比较冻结结果，不能修改 actual；
- 不新增通用 Agent router、统一 Requirement Framework、第二工作流、第二充分性 owner 或副作用权限。

RAG-1A 的退出门以三组实际结果为准：

```yaml
bhf_positive:
  actual_committed: true
  source_to_metadata_to_il: completed
  hidden_golden_compared: true
  acceptable_direction_verified: true
  forbidden_direction_not_sole_authority: true
  sufficiency_and_action_are_diagnostics: true

wall_crawler_negative:
  actual_committed: true
  missing_behavior_evidence_recognized: true
  planning_action: block

evaluation:
  actual_expected_isolated: true
  first_failure_attribution: available
```

满足该退出门后应形成 RAG-1A checkpoint，并停止增加没有真实下游消费依据的 EvidencePack 字段、版本和持久语义。此时 v0 internal alpha 已经提供第一轮内部消费事实；下一步是 RAG-1B 公共入口采用及 Coding Agent v0 public alpha。

### 21.4 RAG-1B 实施门

- P2.2 后续修正完成并独立验收（当前已满足）；
- RAG-1A 已完成；
- 公共入口/结果/Graph/Store/旧兼容合同闭合；
- intelligent evidence 活跃入口清点完成；
- 独立合同审核批准。

### 21.5 RAG-1B 完成门

- 公共证据边界是唯一公共执行入口；
- 旧入口只负责参数适配和展示；
- 无直接 Graph/Store/终态旁路；
- 结构化结果保留真实 ref/receipt/故障；
- 证据不足与平台失败不混淆；
- 首次失败即停止和历史兼容有真实测试；
- 未实施延期能力。

### 21.6 RAG/ER 第一阶段完成门

- BetterHitFeedback 正向链可复现；
- WallCrawler 不充分链可复现；
- 同一需求类型、来源权威和充分性所有者服务两条链；
- 结果能被 Planner/Graph 消费而不授予执行权限；
- 与标准文档 RAG 基线的关系可解释；
- 没有以测试数量、模块存在或 Dashboard 展示代替质量证明。

### 21.7 能力优先与证据驱动推进原则（指导性，不新增 Gate）

本节用于帮助实现智能体保持产品交付方向，不新增 Artifact、Schema、Approval、质量门或状态机，也不替代各阶段既有完成门。

#### 21.7.1 默认推进方式

每个工作包默认从一次真实运行中已经观察到的第一失败层开始，并以让同一真实运行前进到下一能力阶段为目标：

```text
request
→ planning
→ source observation
→ metadata
→ IL
→ EvidencePack
→ Eval
→ Implementation Plan
→ Patch
→ Build/Test
→ Runtime
```

新增测试、错误码、字段、hash 或文档本身不构成能力阶段前进。它们可以支持能力交付，但不能替代真实运行结果。

#### 21.7.2 模型与确定性代码的默认分工

模型默认负责：

- 需求语义；
- 工程问题；
- 查询与调查方向；
- observation 的相关性判断；
- 下一步行动；
- 推断、限制和停止理由。

确定性代码默认负责：

- 运行内 identity；
- 路径、hash、MVID 和 token；
- 跨对象引用；
- source authority；
- 工具参数展开；
- 权限、预算和副作用；
- Artifact commit 与严格回读。

当模型因复制 identity、路径、hash 或跨引用而在第一次 observation 前停止时，优先检查责任分配，不优先增加 Prompt、Schema 或 correction 分支。

#### 21.7.3 尽早观察真实环境

Planning 默认只需形成足以支持第一次只读调查的最小语义，不要求在第一次工具调用前完整描述全部实现、验证和 Runtime 问题。

Planning 可以随着真实 observation 被修正；持久化拓扑由确定性代码从已经发生的事实中形成。

#### 21.7.4 持久字段的进入依据

一个字段进入持久 Artifact 前，至少应满足以下一项：

- 保存不可重新推断的物理事实；
- 保护 actual/expected 隔离；
- 保护来源、权限或副作用完整性；
- 已有真实下游消费者读取它并改变决定；
- 删除它会使已运行的真实用例失去可复现性。

仅用于单次诊断、模型质量分析或未来可能使用的信息，优先保存在运行报告中，不立即提升为 EvidencePack 或产品 Schema。

#### 21.7.5 Workflow 与 Agent 的边界

Workflow、Graph 和控制层可以限制：

- 允许调用什么；
- 哪些前置物理事实必须存在；
- 哪些动作需要授权；
- 如何持久化和恢复。

它们不应预先决定：

- 搜索什么工程方向；
- 选择哪个方法；
- 如何解释 observation；
- Build/Test 失败后采用什么修复方向。

下一步是否随 observation 改变，是判断系统是否仍具有 Agent 行为的主要依据。

#### 21.7.6 只读子系统退出原则

首份 committed BHF EvidencePack 形成后，默认停止增加新的持久语义并进入 v0 internal alpha 的首个真实下游消费者；BHF/WC 与最小 Eval 随后关闭 RAG-1A，再由 RAG-1B 完成公共入口采用。

只有真实 Planner、Patch、Build 或 Runtime 使用暴露缺口时，才重新修改 EvidencePack；不能仅根据预想的未来需要继续扩展。

#### 21.7.7 偏移触发复核

以下情况不自动阻止工作，但应触发一次简短方向复核：

- 连续工作包没有推动真实运行进入下一阶段；
- 模型反复在第一次 observation 前因格式或 identity 失败；
- 新增持久字段没有当前消费者；
- 测试和 validator 增长明显，但完整真实切片没有前进；
- 同一失败被连续解释为新的 Schema、版本或控制要求；
- 只读子系统已满足完成门，却仍未进入下游采用。

复核只回答：

```text
observed_failure:
current_stage:
expected_next_stage:
change_adds_real_information:
existing_consumer:
why_durable_state_is_needed:
```

该复核不创建新 Artifact，不需要独立审批，也不应发展成新的控制流程。

#### 21.7.8 合理例外

以下情况可以在 observation 前保持严格验证：

- 防止 Golden 或历史答案进入 actual；
- 防止伪造来源身份；
- 防止不存在的引用进入工具；
- 防止未经当前 metadata 观察直接读取 IL；
- 防止未授权写入、Build 或 Runtime；
- 防止 Store 回读改写已冻结事实。

例外需要说明它保护的具体事实或副作用，而不能只使用“未来可能需要”作为理由。

### 21.8 Coding Agent v0 纵向闭环及后续能力顺序

Coding Agent v0 是当前上位产品里程碑，不是 RAG-1A 之后才启动的独立 Agent SDK。RAG-1A 是它内部的证据能力；首份可信 BHF EvidencePack 形成后，v0 internal alpha 立即复用现有 Implementation Planning、Patch、Review/Dry-run、Build/Test 和 Repair 能力，形成一条最小受控纵向链：

```text
自然语言需求
→ RAG/ER EvidencePack
→ Implementation Plan
→ PatchProposal
→ Review / Dry-run
→ 隔离 Build/Test
→ 完成，或根据真实诊断修复一次
```

v0 完成至少要求：

- `natural_language_to_evidence`；
- `evidence_to_patch`；
- `patch_to_build_test`；
- `build_failure_changes_next_action`。

RAG/ER 的后续改进必须由该消费者的真实失败归因驱动：源码未进入窗口归 RAG 检索；源码存在但当前身份缺失归 metadata/IL；Planner 缺关系归 Evidence Reasoning；从未被消费者读取的持久字段应删除或降级；Build 失败后无法回到相关源码归 Agent Loop；只在 Runtime 暴露的问题归 Runtime evidence。

Eval 与最小可追溯从 v0 首次运行开始伴随记录，但不先建设平台：关联 request、EvidencePack、plan、patch、build attempt、repair attempt 和 final result；比较范围外修改、Build/Test 结果、是否使用真实诊断、证据不足时是否停止。完整 Trace 平台、Dashboard、CI 晋级门和正式多模型排名仍延期。

v0 必须拥有运行内工作记忆：当前请求、已读文件、tool observations、已尝试修改、Build 失败和当前待解决问题。跨任务长期记忆只在多个独立真实任务反复证明需要后进入，且不得保存 Golden、历史 Hook、旧 Agent 错误或临时协议结论作为当前事实。

后续顺序固定为：

```text
跨工作树/WIP 归并基线
→ 重复物理 query dispatch 的确定性折叠
→ BHF EvidencePack
→ Coding Agent v0 internal alpha Evidence/Plan/Patch/Build
→ 一次 observation-driven repair
→ BHF/WC Hidden-Golden 与最小 Eval
→ RAG-1A checkpoint
→ RAG-1B 公共入口采用
→ Coding Agent v0 public alpha
→ 根据 v0 真实失败改进 RAG/ER
→ Runtime 闭环
→ 端到端 Trace / 回归 Eval
→ 有数据后再决定长期记忆、MCP 扩展、Skills 与子智能体
```

## 22. 十二项决策登记

| 编号 | 已选决定 | 解决的问题 | 明确排除 |
| --- | --- | --- | --- |
| 1 | 当前产品目标为 Coding Agent v0 纵向闭环；自然语言到 EvidencePack 的 RAG/ER 是其第一个工具子系统 | 让证据产生真实 Planning/Patch/Build 消费，避免孤立优化只读系统 | 暂停 RAG 后另建 Agent SDK、知识中心第一优先 |
| 2 | EvidencePack 是可持久化证据决策包，但“决策”只属于证据层 | 保存当时为什么值得考虑/拒绝 | Approval、执行、Trace/Eval 事实 |
| 3 | 来源感知的多路检索，证据准入在排名之前 | 防止共享容量和分数掩盖来源差异 | top-1/总分决定 Hook |
| 4 | 检索、工程、规划三层充分性；运行时观察按需使用 | 防止“充分”等于“可以修改” | 通用 Runtime 前置、巨型需求框架 |
| 5 | 索引只发现位置，绑定当前身份的来源才形成事实 | 防止过期索引和社区内容升级 | 索引命中等于证据 |
| 6 | BHF EvidencePack 用于 RAG/ER 方向校准；v0 internal alpha 的正向 Patch/Build 链使用独立 actual-only 工程任务；BHF/WC 与最小 Eval 随后关闭 RAG-1A；RAG-1B 再完成公共入口采用并形成 v0 public alpha | 防止把方向 Golden 当作 Patch 授权，同时让证据字段尽快接受真实下游消费 | 用 BHF expected truth 补足实现依据、两个独立 RAG 产品、无限延长只读合同期、完整 Trace/Eval 平台前置 |
| 7 | 复用 EvidencePack，新增严格版本化 Hook Discovery 语义；旧包不自动升级 | 避免第二 Artifact 和历史重解释 | 第二充分性所有者、Store/Graph 扩张 |
| 8 | 历史 `EVIDENCE_RAG_MCP_SPEC.md` 是适配稿；兼容原则可继承，导入蓝图只供参考 | 解决文档内部权威冲突 | 整体照搬 §4 以后路线 |
| 9 | 原始 `DEV_SPEC.md` 是外部通用 RAG 模板，不是当前产品完成状态 | 保留专业通用 RAG 工程价值 | 由模板决定当前产品和默认算法 |
| 10 | 标准文档 RAG 与 ER 共享检索机制和基础设施能力，但不共享 score 含义、证据语义或充分性权威 | 防止 ER 吞掉普通 RAG或重复建设两套平台 | 相关性等于证据事实、共享基础等于共享语义权威 |
| 11 | 原草案未完全覆盖普通 RAG，需要覆盖数据摄取、切块、检索、过滤和引用，并对 provider、MCP、多模态作有限边界裁决 | 形成完整但不过度扩张的 RAG+ER 目标 | 重建大型知识平台、只写 ER 控制衔接而遗忘普通 RAG |
| 12 | 将能力边界和当前路线整合进同一文档；最小 Eval/运行事实伴随纵向切片，完整 Trace/Eval 平台独立延期 | 防止讨论记录堆叠，也防止无评测地推进真实修改 | 一次性大迁移、Dashboard 或治理建设替代能力交付 |

## 23. 当前未决事项

产品方向已经闭合。当前未决项来自真实运行和首个下游消费者，必须按 §21.7 逐项推进，不得重新扩张为实施前总合同：

```yaml
current_capability_items:
  - reconcile current WIP with non-ancestor delivery hardening before v0 integration
  - collapse physically identical query dispatches without blocking first read-only observation
  - complete BetterHitFeedback source-to-metadata-to-IL-to-EvidencePack actual
  - Coding Agent v0 internal alpha consumes committed EvidencePack through Plan/Patch/Build
  - one observation-driven Build/Test repair path
  - BetterHitFeedback Hidden-Golden comparison after committed actual
  - WallCrawler real negative discovery and committed actual
  - minimal relation-level Eval mapping and first-failure attribution
  - RAG-1A checkpoint
  - RAG-1B public Evidence executor adoption without duplicate owner
  - Coding Agent v0 public alpha through the unique public entry
  - minimal run-local correlation across request/evidence/plan/patch/build/result
```

以下不属于本文未决事项，将由其他文档或未来实验决定：

- 完整 Trace schema/exporter、统一 span 平台与 Dashboard；
- 正式 Eval dataset runner、长期指标阈值和 CI promotion；
- Dense/RRF/reranker provider 和默认采用；
- MCP/HTTP/Dashboard 产品化；
- Multimodal；
- Knowledge Hub 用户界面。
- 跨任务长期记忆、Skills 和子智能体扩展；

## 24. 当前准确状态

```yaml
as_of: 2026-08-16
standard_rag_engineering_skeleton: implemented_in_parts
data_readiness: bounded_fixture_review_passed_no_independent_data_readiness_verdict
general_hybrid_retrieval: implemented_but_not_currently_proven_as_default
dense_capability: implemented_but_disabled_by_default
reranker_capability: implemented_but_disabled_by_default
citations: implemented_at_retrieval_source_level
query_and_ingestion_trace: implemented_locally
mod_agent_workflow_event_trace: implemented_locally_not_unified_span_trace
agent_evidence_trace_facts: partially_present
end_to_end_agent_trace: incomplete
ordinary_rag_quality_evidence: insufficient_due_to_non_authoritative_goldens
mod_agent_agent_quality_evaluator: implemented_as_evaluation_control_skeleton
mod_agent_retrieval_regression_and_quality_policy: implemented_not_formal_product_evidence
mod_agent_arm_a_rg_live_read_baseline: implemented_as_reproducible_experimental_baseline
mod_agent_transition_eval_gate: implemented_for_existing_workflow_transition_boundaries
trusted_held_out_agent_retrieval_quality_evidence: not_established

better_hit_feedback_environment_source: hash_bound_current_api_il_historical_implementation_and_bounded_runtime_inputs_replayed
better_hit_feedback_formal_positive_golden: bounded_fixture_review_passed_reference_assisted_calibration_sufficient_continue
wall_crawler_negative_source: bounded_fixture_review_passed_independent_calibration_insufficient_block

rag_1a_code_implementation:
  status: uncommitted_wip_real_discovery_not_closed
  worktree: rag_capability_mainline
  branch: codex/rag-capability-mainline
  current_head: c48b5e82fe3eed524d5c9f868980748136e28bfd
  implementation_tracked_unstaged_files_before_document_sync: 12
  documentation_sync_tracked_files: 6
  total_tracked_unstaged_files_after_document_sync: 17
  untracked_files_after_document_sync: 2
  implementation_diff_stat_before_document_sync: +3258/-208
  actual_execution_isolation: implemented
  requirement_projection: implemented_with_provider_semantics_and_deterministic_identity_materialization
  search_planning: implemented_but_real_full_bhf_stops_on_duplicate_physical_dispatch
  deterministic_source_retrieval: implemented_multi_lane_with_bounded_identifier_expansion
  metadata_tool: implemented
  dynamic_single_method_il_by_metadata_token: implemented_in_uncommitted_wip
  evidence_reasoning: implemented_initial_working_slice
  evidence_pack_strict_roundtrip: implemented
  bounded_discovery_loop: implemented_in_tests_and_partial_real_runs_not_end_to_end_proven
  hidden_golden_protocol: minimal_eval_implemented
  hidden_golden_complete_bhf_actual: not_available

latest_real_bhf:
  report_sha256: 2B4AD4946656848672D9140DE506FEFFADC29ECA9F8B79AAA84490B511513247
  model: qwen3_4b_instruct
  ollama_version: 0.32.13
  status: failed
  failure_stage: search_planning
  failure_code: SEARCH_PLAN_QUERY_FAMILY_DISPATCH_AMBIGUOUS
  physical_cause: semantically_duplicate_query_families_produce_same_dispatch
  provider_tool_calls: 0
  observations: 0
  evidence_pack_commit: false

current_first_blocker: duplicate_physical_query_dispatch_blocks_first_observation
current_only_capability_goal: natural_language_bhf_to_source_metadata_il_evidence_pack
next_change:
  deterministic_code: collapse_exact_duplicate_dispatches_within_one_investigation
  evaluation_record: planning_quality_finding
  then: one_fixed_qwen_bhf_actual
  forbidden_expansion: new_evidencepack_version_new_artifact_new_registry_store_trace_control_or_golden_change

cross_worktree_reconciliation:
  required_before_v0_integration: true
  non_ancestor_heads:
    - 9bce437
    - 9a237b7
    - c000021
  highest_priority: 9bce437_delivery_hardening_29_files

rag_1a_exit: not_reached
rag_1b: not_started_follows_rag_1a_runnable_capability
coding_agent_v0:
  role: current_product_vertical_milestone
  immediate_dependency: committed_actual_only_task_evidence_pack_with_current_source_support
  bhf_role: rag_er_discovery_direction_calibration_not_patch_authority
  internal_alpha: uses_independent_actual_only_positive_task_before_rag_1a_public_closure
  public_alpha: follows_rag_1a_checkpoint_and_rag_1b_public_adoption
  implementation_strategy: compose_existing_planning_patch_review_build_and_repair_modules
  completion_requires:
    - natural_language_to_evidence
    - evidence_to_patch
    - patch_to_build_test
    - build_failure_changes_next_action

minimal_eval: accompanies_v0_without_new_platform
minimal_trace: run_fact_correlation_required_without_full_trace_platform
run_local_working_memory: required_for_v0
cross_task_long_term_memory: deferred_until_repeated_real_task_evidence

p2_2_option_b_product_executor: independently_verified_and_committed
p2_2_option_b_implementation_commit: f57045bb5b3f671f60bdd107308ba9fe3f3c3293
p2_2_follow_up_completion: independently_verified_and_committed
p2_2_follow_up_implementation_commit: 20b6ccb34e9322f4c73d7556130e7da043aff110
p2_2_follow_up_checkpoint_commit: 14db12ea429233bb3c8378cdfb20bd6be63fbbfc

previous_target_document_review_verdict: approved
previous_target_document_checkpoint_commit: c4152675a14924f408f611f126d610775a9b64c6
current_document_update: pending_sync_checkpoint_and_review
overall: finish_bhf_actual_feed_v0_internal_close_rag_1a_adopt_via_rag_1b_then_v0_public
```

此前目标文档版本已完成独立审核并纳入 Git。本次更新重新编排能力优先原则、RAG-1A 偏差复盘和 Coding Agent v0 路线，在形成新的文档 checkpoint 与审核前，不继承此前文档 hash 的审核结论。

BetterHitFeedback / WallCrawler 两切片的分层 fixture 与冻结 judgment 继续作为独立 expected 尺子；当前 RAG 输出不反向修改 Golden。模型 identity 记账已经移交确定性代码。最新完整 BHF 在 Search Planning 阶段因多个 query family 产生完全相同的物理 dispatch 而零工具调用；这属于 planning quality，不属于 source、metadata、IL 或 EvidencePack 事实失败。

下一工作包先核对当前 WIP 与三个非祖先提交，形成可恢复基线；随后只折叠同一 investigation 内物理等价的 query dispatch，并立即重跑固定 Qwen BHF。EvidencePack 成功后先进入 v0 internal alpha 的 Planning/Patch/Build 消费，再完成 BHF/WC Hidden-Golden 与最小 Eval，形成 RAG-1A checkpoint；RAG-1B 随后完成公共采用和 v0 public alpha。不再以预想需求扩充只读结构。
