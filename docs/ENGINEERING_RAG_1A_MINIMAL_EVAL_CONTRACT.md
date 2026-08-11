# Engineering RAG-1A 与最小 Eval 收敛合同

```yaml
document_role: joint_contract_review_object
baseline_commit: f11b168b71e9313af008d8e52394f9860c63c3b9
target_document_checkpoint: c4152675a14924f408f611f126d610775a9b64c6
contract_materialization: complete
architecture_direction: approved
joint_contract: design_and_boundary_input
rag_1a_contract: draft_changes_required
calibration_eval_contract: draft_changes_required
data_readiness: blocking
implementation_authorization: not_granted
contract_materialization_status: independently_verified
contract_materialization_verdict: approved
independent_reviewed_sha256: 3FB64991D775332B945EEC60792474A729E82702E8515F7B7E5F553B7CB3EBEA
rag_1a_contract_verdict: changes_required
minimal_eval_contract_verdict: changes_required
rag_1a_code_implementation_authorization: not_granted
minimal_eval_code_implementation_authorization: not_granted
rag_1b_implementation_authorization: not_granted
```

本文是一个可 hash、可 diff 的联合审核对象，但包含两个不可合并的语义所有者：

- RAG-1A 拥有 actual evidence facts、来源准入、检索覆盖、Hook 备选项和三层充分性；
- 最小 Eval 拥有 Golden expected facts、数据身份、比较、指标、报告和质量门。

Eval 只能消费 RAG-1A 的冻结 actual facts。RAG-1A 不得读取 Golden expected facts、Eval 分数或 quality gate 结果来改变 EvidencePack、充分性或产品决定。

## 1. 当前问题与目标

### 1.1 当前真实问题

当前代码存在四处 Evidence readiness/continuation 解释面：

1. `src/mod_agent/evidence/readiness.py::EvidenceReadinessClassifier` 从平面 `EvidenceItem` 列表决定 `readiness/can_generate_patch`；
2. `RgLiveEvidenceProvider` 与 `GTFOR8EvidenceProvider` 各自直接构造并解释 `EvidencePack`；
3. `ImplementationPlanner` 再次解释 readiness、来源权威和 Hook 完整性；
4. StateGraph 再根据 `can_generate_patch` 解释是否继续。

`DeterministicEvidenceRetriever.retrieve()` 还使用共享 `request.max_items`，按 symbol → BM25 → Dense → text 串行填充。前一路径可以耗尽容量，因此当前结果不能证明每条 lane 是否独立执行、覆盖了哪些来源、无命中是否来自未搜索、失败或有边界的缺失。

### 1.2 第一阶段交付能力

```text
自然语言 Hook 工程问题
→ 独立多路检索事实
→ 当前来源身份验证与准入
→ Hook/方案备选项及支持、冲突、缺失关系
→ retrieval / engineering / planning 三层充分性
→ versioned EvidencePack actual facts
→ 独立 Eval 与人工 Golden expected facts 比较
```

第一阶段不实施 Dense/Fusion/RRF/reranker 默认采用、完整 Trace、Langfuse/OTel、Dashboard、CI promotion、RAG-1B 或 Build/Runtime。

## 2. 共享 authority 与接口边界

| 事实 | 唯一 owner | 消费方 | 禁止行为 |
| --- | --- | --- | --- |
| requirement、source binding、lane execution、admission、Hook option、三层充分性 | RAG-1A semantic owner | EvidencePack、Planner、Graph、Eval adapter | provider、Planner、Graph、Eval 重算 |
| EvidencePack commit truth | ArtifactStore/C5 | 控制面、RAG-1A public boundary | Eval 根据文件或 totals 重造 receipt |
| Golden expected facts | 最小 Eval dataset | evaluator | 从当前 RAG 输出反向生成或修标签 |
| actual/expected 比较与 metrics | `AgentQualityEvaluator` 的版本化适配 | `AgentQualityReport`、`QualityGatePolicy` | 建立第二 evaluator 或把分数写回 EvidencePack |
| dataset/observation 可比性 | `RetrievalRegressionRunner` | report comparison | 跳过 dataset/protocol/corpus identity 检查 |
| corpus identity | Arm A `RunManifestCollector.canonical_corpus_snapshot()` | Arm A 与 RAG-1A run binding | 另建目录 tree-hash 算法 |
| workflow transition gate | `build_transition_eval_gate_report` | 既有 workflow evaluation | 决定 retrieval quality 或充分性 |

## 3. 工作包 A：RAG-1A actual evidence facts

### 3.1 authority 迁移

| 范围 | current authority | target authority | removed authority |
| --- | --- | --- | --- |
| Hook requirement | request planning 字段与字符串约定 | `HookDiscoveryDeclarationV1` | Graph/Planner 自行识别需求类型 |
| lane 覆盖 | retriever 顺序与共享容量 | declaration-owned lane grammar | 从最终 items 反推执行路径 |
| 来源准入 | provider 局部判断和 `source_type` | `project_hook_discovery_semantics()` | provider 自行把来源升级为权威事实 |
| 三层充分性 | classifier/provider/Planner/Graph | `project_hook_discovery_semantics()` | 四处 readiness 规则 |
| 持久化解析 | Registry required-fields | `HookDiscoverySemanticsV1.from_dict()` 委托同一 projector | Registry 第二张语义表 |
| 规划消费 | Planner 重算 readiness/Hook | 冻结 planning projection | Planner 自行提升检索结果 |
| Graph 消费 | `can_generate_patch` 的本地解释 | 兼容投影 | Graph 保存来源、lane、充分性表 |

### 3.2 EvidencePack 兼容扩展

现有 `EvidencePack` 仅允许条件增加：

```python
hook_discovery: HookDiscoverySemanticsV1 | None = None
```

规则：

- `hook_discovery is None` 时 `to_artifact_payload()` 不写该键，历史 mapping、bytes 和 hash 不变；
- 新 Hook Discovery pack 必须包含该键；
- 历史 pack 不补默认值，不推断新充分性；
- `HookDiscoverySemanticsV1.from_dict()` 必须严格重放 `project_hook_discovery_semantics()`；
- Registry 只在键存在时委托该 owner，不复制字段或充分性规则；
- FeatureSpec 明确要求 Hook 时，Graph/Planner 对缺少该语义段的 pack fail-closed。

`HookDiscoverySemanticsV1` 精确顶层字段：

```yaml
schema_version: hook_discovery_v1
requirement: HookDiscoveryRequirementV1
source_bindings: [HookDiscoverySourceBindingV1]
lane_runs: [HookDiscoveryLaneRunV1]
admissions: [HookDiscoveryAdmissionV1]
hook_options: [HookDiscoveryOptionV1]
sufficiency: HookDiscoverySufficiencyV1
planning_binding_option_id: string|null
blockers: [object]
gaps: [string]
reproducibility: HookDiscoveryReproducibilityV1
```

`HookDiscoveryReproducibilityV1` 精确字段和 nullability：

```yaml
protocol_document_sha256: sha256:<64 lowercase hex>
retrieval_configuration:
  ref: string
  sha256: sha256:<64 lowercase hex>
  version: string
source_snapshot_sha256: sha256:<64 lowercase hex>
index_snapshot:
  ref: string
  sha256: sha256:<64 lowercase hex>
  version: string
  # 当且仅当本次路径未消费索引时，整个对象为 null
prompt_template:
  ref: string
  sha256: sha256:<64 lowercase hex>
  version: string
  # 当且仅当本次路径未使用 prompt 时，整个对象为 null
model:
  provider: string
  deployment: string
  version: string
  # 当且仅当本次路径未调用模型时，整个对象为 null
reranker:
  provider: string
  model: string
  configuration_sha256: sha256:<64 lowercase hex>
  # 当且仅当本次路径未执行 reranker 时，整个对象为 null
```

不适用项使用 JSON `null`，不得使用空字符串、固定占位或当前系统默认值。精确 prompt 内容仍由原配置/源码 owner 管理；此处只保存可解析 ref/hash/version。

### 3.3 declaration 与来源身份

`HookDiscoveryRequirementV1`：

```yaml
requirement_type: game_hook_investigation
profile_id: gtfo_existing_mod_hook_discovery_v1
query_sha256: sha256:<64 lowercase hex>
required_source_roles: [editable_target, current_product_api]
optional_source_roles: [supporting_reference, immutable_artifact, runtime_observation]
required_lanes: [live_source, symbol_metadata, method_il]
optional_lanes: [bm25_text, immutable_artifact, runtime_observation]
runtime_observation_requirement: optional|required
```

`HookDiscoverySourceBindingV1`：

```yaml
source_binding_id: string
source_id: string
source_type: existing SourceRegistry source_type
source_role: editable_target|current_product_api|supporting_reference|immutable_artifact|runtime_observation|auxiliary
authority_class: authoritative|supporting|auxiliary
version_identity: object
content_sha256: sha256:<64 lowercase hex>
```

约束：

- `source_type` 不决定 `authority_class`；
- 当前产品 API 只有在版本和内容身份经原 owner 验证后才能成为 `current_product_api`；
- 历史实现、参考 Mod、社区内容、Dense-only 命中和 calibration source 不得成为唯一 authoritative Hook discovery source；
- actual facts 不暴露不必要的机器绝对路径。

### 3.4 独立 lane 事实

`HookDiscoveryLaneRunV1`：

```yaml
lane: live_source|symbol_metadata|method_il|bm25_text|immutable_artifact|runtime_observation
required: boolean
budget:
  top_k: positive_integer
execution_status: completed|failed|not_run
coverage_status: covered_with_hits|not_searched|not_found|insufficient_coverage|searched_and_absent
searched_source_binding_ids: [string]
ranked_evidence_ids: [string]
hit_count: non_negative_integer
failure: {code: string, message: string}|null
not_run_reason: string|null
```

首 profile 的每条 required lane 使用独立 `top_k=10`，不共享总 `max_items`。`not_found` 不等于不存在；只有合同声明的来源范围全部完成搜索后，才允许 `searched_and_absent`。

### 3.5 evidence admission 与 Hook option

`HookDiscoveryAdmissionV1`：

```yaml
evidence_id: string
source_binding_id: string
disposition: admitted|excluded
reason_codes: [string]
```

固定排除原因至少包括：

- `source_identity_unverified`
- `source_version_mismatch`
- `content_hash_mismatch`
- `source_role_not_allowed`
- `engineering_irrelevant`
- `auxiliary_only`
- `answer_leakage_reference_only`

`HookDiscoveryOptionV1`：

```yaml
option_id: string
target:
  declaring_type: string
  method_name: string
  parameter_types: [string]
  return_type: string
  method_kind: string
supporting_evidence_ids: [string]
conflicting_evidence_ids: [string]
missing_evidence: [string]
limitations: [string]
engineering_sufficiency: sufficient|partial|insufficient|contradictory
```

`option_id` 由 source binding 与完整方法身份的 canonical bytes 派生，不使用检索分数。它是证据层备选项，不是 Approval 或最终 Hook 授权。

### 3.6 三层充分性

```yaml
retrieval: sufficient|partial|insufficient
engineering: sufficient|partial|insufficient|contradictory
planning: sufficient|partial|insufficient|contradictory
```

规则：

- retrieval：所有 required lane 均实际执行并满足声明 coverage；
- engineering：至少一项 Hook option 具有当前 API 的完整方法身份、权威证据关系和显式限制；分数不能覆盖冲突；
- planning：engineering 足够、存在 editable target、只有一个 planning-ready option，且所有 required 行为事实满足；
- 顶层 EvidencePack `readiness` 必须逐字等于 planning sufficiency；
- `can_generate_patch=True` 当且仅当 planning=`sufficient`；
- blockers、gaps、missing evidence 由同一 projector 派生。

### 3.7 RAG-1A actual facts 接口

唯一投影：

```text
project_hook_discovery_actual_facts(evidence_pack_payload)
  -> HookDiscoveryActualFactsV1
```

`HookDiscoveryActualFactsV1` 必须逐字包含：

1. `schema_version=hook_discovery_actual_facts_v1`；
2. protocol version/hash、requirement type、profile ID、query hash；
3. source binding 的 logical identity、role、authority、version/content identity；
4. 每条 lane 的 budget、execution/coverage、搜索来源、ranked evidence、failure/not-run 原因；
5. admitted/excluded evidence 及原因；
6. Hook option 完整方法身份、support/conflict/missing/limitations；
7. retrieval/engineering/planning 三层充分性；
8. planning binding option；
9. EvidencePack readiness、`can_generate_patch`、blockers、gaps、missing evidence；
10. EvidencePack ref/hash或 canonical payload identity；
11. retrieval latency、API call、token、cost；
12. retrieval configuration、source snapshot、适用 index、prompt/template、model/provider、reranker 的 ref/hash/version或明确 `null`。

actual facts 不包含 Golden expected facts、Eval 指标/阈值、promotion、secret、完整私有 prompt、Approval、Store commit 解释或产品终态。

## 4. 工作包 B：最小 Eval 与 adoption matrix

### 4.1 最终 adoption matrix

| 既有资产 | 裁决 | 当前合同边界 |
| --- | --- | --- |
| 普通 `EvalRunner` | defer | 保留给标准文档 RAG；首轮不作为 RAG-1A runner |
| `RagasEvaluator` | defer | 只作未来回答质量辅助；不得证明来源身份、Hook 或充分性 |
| 局部 Trace/Event | defer | 等待跨系统关联/传播合同；不得成为 Golden 或 gate owner |
| `AgentQualityEvaluator` | adapt | 保留唯一 evaluator、聚合和报告 owner；版本化扩展 Case/Observation，不新建 evaluator |
| `RetrievalRegressionRunner` / `compare_reports` | adopt | 继续拥有 dataset/observation identity、可比性和 comparison mode |
| `QualityGatePolicy` | adopt | 继续拥有 versioned threshold 与 fail-closed gate；首轮不声称 promotion |
| `OfficialArmARunner` / `RgLiveReadProvider` | adapt | 保留 rg + live read 与运行身份；增加来源角色/coverage actual 投影，不伪造 EvidencePack decision |
| `build_transition_eval_gate_report` | defer | 继续拥有既有 workflow transition，不进入 retrieval/EvidencePack 评测 |

### 4.2 现有 Eval schema 的版本化适配

兼容裁决：`not_lossless_requires_versioned_adaptation`。

- `AgentQualityCase` 增加可选严格字段 `hook_discovery_expected: HookDiscoveryExpectedFactsV1 | None`；旧 Case 缺失时按旧 schema/value domain 解析；
- `CaseObservation` 增加可选严格字段 `hook_discovery_actual: HookDiscoveryActualFactsV1 | None`；该对象只能来自 RAG-1A projector；
- `RunManifest` 增加可选 `hook_discovery_reproducibility: HookDiscoveryReproducibilityV1 | None`，直接消费 RAG-1A owner 的同一冻结对象，不建立第二套 retrieval config、index、prompt/model/reranker 字段；
- `AgentQualityReport` 保持唯一报告 owner，记录适配后的 schema version、applicable case IDs 和 exact normalized observations hash；
- `readiness_accuracy` 在新 Hook Case 上比较四值 `sufficient|partial|insufficient|contradictory`；旧三值 Case 继续使用旧 schema，禁止压成 `blocked`；
- `false_continue_rate` 继续使用同一指标，但 expected action 必须来自人工 Golden，actual `can_generate_patch` 必须来自冻结 EvidencePack，报告必须保存 applicable case IDs。

`HookDiscoveryExpectedFactsV1` 精确字段：

```yaml
schema_version: hook_discovery_expected_facts_v1
case_id: string
slice_id: better_hit_feedback_positive|wall_crawler_insufficient
query: string
scenario: positive|insufficient_evidence
required_sources: [ExpectedSourceBindingV1]
allowed_sources: [ExpectedSourceBindingV1]
forbidden_sources: [ExpectedSourceBindingV1]
required_lanes: [string]
expected_coverage: [ExpectedLaneCoverageV1]
required_evidence_claims: [string]
allowed_evidence_claims: [string]
forbidden_evidence_claims: [string]
expected_hook_options: [ExpectedHookOptionV1]
expected_sufficiency:
  retrieval: sufficient|partial|insufficient
  engineering: sufficient|partial|insufficient|contradictory
  planning: sufficient|partial|insufficient|contradictory
expected_readiness: sufficient|partial|insufficient|contradictory
expected_can_generate_patch: boolean
expected_control_action: continue|block
expected_blockers: [string]
annotation:
  source: human
  annotation_version: string
  judgment_sha256: sha256:<64 lowercase hex>
```

上述嵌套对象的精确 schema：

```yaml
ExpectedSourceBindingV1:
  source_id: string
  source_type: existing SourceRegistry source_type
  source_role: editable_target|current_product_api|supporting_reference|immutable_artifact|runtime_observation|auxiliary
  authority_class: authoritative|supporting|auxiliary
  version_identity: object
  content_sha256: sha256:<64 lowercase hex>

ExpectedLaneCoverageV1:
  lane: live_source|symbol_metadata|method_il|bm25_text|immutable_artifact|runtime_observation
  expected_execution_status: completed|failed|not_run
  expected_coverage_status: covered_with_hits|not_searched|not_found|insufficient_coverage|searched_and_absent
  required_source_ids: [string]

ExpectedHookOptionV1:
  option_id: string
  target:
    declaring_type: string
    method_name: string
    parameter_types: [string]
    return_type: string
    method_kind: string
  required_support_source_ids: [string]
  forbidden_support_source_ids: [string]
  required_missing_evidence: [string]
  expected_engineering_sufficiency: sufficient|partial|insufficient|contradictory
```

`required_sources`、`allowed_sources` 和 `forbidden_sources` 均使用同一 `ExpectedSourceBindingV1` schema，但三组不得出现相同 `source_id`。Golden owner 必须在运行前冻结这些对象；Eval adapter 不得根据 actual source bindings补写。

### 4.3 首轮指标与 gate

复用：

- `recall_at_k`
- `mrr_at_k`
- `hook_recall_at_k`
- 适配后的 `readiness_accuracy`
- `continuation_decision_accuracy`
- `false_continue_rate`

只有现有指标无法表达已批准 expected facts 时，才允许在同一 `AgentQualityEvaluator` 增加：required source identity coverage、source authority precision、required-role coverage、unsupported claim rate。不得建立第二 evaluator、runner、comparison owner 或 quality gate。

首轮 dataset 是非 promotion 的 development/smoke 合同集，只包含两条真实 Case。每条 Case 的 exact predicate 必须全部成立；两条 Case 的百分比不得描述为通用产品质量。

## 5. Golden 与 corpus identity

### 5.1 Arm A canonical corpus 是唯一目录身份规则

正式 corpus identity 必须委托 `RunManifestCollector.canonical_corpus_snapshot(search_roots)`：

- 每个文件使用 workspace-relative POSIX path、raw file SHA256 与 `size_bytes`；
- 路径按 `relative_path` 排序；
- 重复路径、symlink、越界路径 fail-closed；
- `selection_policy` 固定 policy schema、search roots、extension allowlist、ignored dirs/files、hidden/ignore/binary/symlink policy；
- `corpus_snapshot_sha256` 是 `{files, selection_policy}` 的 canonical JSON SHA256；
- before/after snapshot 不一致则 `evidence_status=stale`；
- Arm A 与 RAG-1A run 必须共享 dataset、judgment、repository/worktree、corpus 和 protocol identity。

此前记录的 `cd7543ee...` 五文件 tree hash 只能作为历史 lineage 检查值，不能替代上述 canonical corpus identity，也不得复制第二套 aggregate hash 算法。

### 5.2 BetterHitFeedback 历史 materialized source

以下对象已定位且 hash 可复核：

```text
workspaces/stagger_formal_repair_apply_001/run_001/materialized_source/BetterHitFeedback
```

- historical five-file snapshot：`cd7543ee1bbaaa6109cb52b59e93c411ac07f38a9dfd5f6666313010a7adf08f`；
- `Patches/HitFeedbackBehaviorPatch.cs`：`77d0e4c6554444ab027e2fd6f98a3bc2ec7c5d6bcc8f54f977b655920922f0ae`；
- exact FeatureSpec ref：`5d5eb3b126a85527e5d0d36fff75aca006153aed10f69648aaadbd16c8e43d28`。

该对象是 repair/apply 后的最终实现，已经包含目标 Hook 与行为答案，并且位于 Git ignored `workspaces/`。裁决：

- 可以作为 environment-scoped calibration、人工标注历史参考或 `reference_mod` supporting evidence；
- 必须标记 `answer_leakage_reference_only`，不得作为唯一 authoritative Hook discovery source；
- 不进入 held-out/promotion；
- actual retrieval corpus 必须排除其最终实现源码，或只按 supporting/auxiliary 权威参与且不能决定充分性；
- 缺少该目录只使 calibration unavailable，不得改变正式 Golden expected facts。

### 5.3 BetterHitFeedback 正式正向 Golden

正式正向 Case 仍未闭合。必须在独立合同审核前固定：

1. 不包含最终实现答案的、可跨 clone 解析的 canonical corpus manifest；
2. 当前目标程序集/API/IL 的 exact source identity、version/hash；
3. 需要证明行为语义时的 Runtime observation identity；
4. 独立人工标注的 expected Hook、allowed/forbidden facts 与 judgment hash；
5. exact query、search roots、search patterns、required lanes、Top-K 与 coverage；
6. Arm A 和 RAG-1A 运行能够重建同一 canonical corpus snapshot。

在这些事实闭合前：

```yaml
better_hit_feedback_formal_positive_golden: blocked_by_answer_leakage_and_nonportable_corpus
```

### 5.4 WallCrawler 负向 Case

WallCrawler 可使用 `src/mod_agent/evidence/gtfo_r8.py::R8_EXPECTED_SHA256`、exact symbol table、current interop/IL report 与 stub/native-body blocker 作为合同输入。它必须输出实际搜索、coverage、来源身份与缺失事实；参考 Mod 和社区提示不能升级为当前来源。

预期结果：planning 不为 `sufficient`、`can_generate_patch=false`、`false_continue=0`，且不得产生 unsupported planning 或业务副作用。Case 的 exact dataset/protocol identity仍需在本文件后续修订中冻结。

## 6. runner 与报告流程

```text
versioned two-case dataset
  ├─ OfficialArmARunner → deterministic rg/live-read actuals
  └─ RAG-1A actual-facts provider
          ↓
versioned CaseObservation adapter
          ↓
RetrievalRegressionRunner
          ↓
adapted AgentQualityEvaluator
          ↓
AgentQualityReport
          ↓
QualityGatePolicy
```

- Arm A 只产生检索 actuals，不生成 EvidencePack decision；
- `compare_reports` 只比较共同适用、applicable case IDs 一致的 retrieval 指标；
- EvidencePack readiness/coverage/unsupported-decision 只在 RAG-1A arm 计算；
- 普通 `EvalRunner`、Ragas 和 transition gate 不参与首轮；
- Eval 输出不写回 EvidencePack、Graph、Store 或机器终态。

## 7. failure matrix

| 失败 | RAG-1A 结果 | Eval 结果 | 禁止行为 |
| --- | --- | --- | --- |
| request/schema/identity 合同错误 | Store 前 fail-closed | case 不执行 | 写 EvidencePack、生成 expected facts |
| required lane 未执行或 provider 失败 | 保留 lane failed/not_run；planning 不得 sufficient | actual 不完整或 Case fail | 写成 searched_and_absent |
| 来源 revision/hash 漂移 | exclude + blocker | not comparable | fallback 到同名/最新文件 |
| 证据不足 | 合法 EvidencePack，planning insufficient/partial | 与人工 expected 比较 | 泛化成平台失败 |
| EvidencePack Store 非 committed | 由 C5/Product Executor 表达 | 不生成通过报告 | 重造 receipt |
| corpus before/after drift | 不改变已冻结领域事实 | `evidence_status=stale`、gate fail | 宣称正式可比较 |
| Golden 来源缺失或答案泄漏 | 不改变 actual | dataset invalid | 从系统输出生成标签 |
| evaluator/runner/exporter 失败 | 不改变 EvidencePack | 无通过结果 | 把故障写回机器事实 |
| prompt/config/model/index identity 缺失且适用 | RAG 执行按其合同处理 | 不得进入正式可比较报告 | 用空字符串或固定占位冒充 |

## 8. proposed implementation scope（未授权）

### RAG-1A production files

```text
src/mod_agent/evidence/hook_discovery.py
src/mod_agent/evidence/models.py
src/mod_agent/evidence/readiness.py
src/mod_agent/evidence/retriever.py
src/mod_agent/evidence/__init__.py
src/mod_agent/artifacts/registry.py
src/mod_agent/planning/implementation_plan.py
src/mod_agent/workflow/graph.py
```

### Eval production files

```text
src/mod_agent/evaluation/agent_quality.py
src/mod_agent/evaluation/retrieval_regression.py
src/mod_agent/evaluation/quality_policy.py
src/mod_agent/evaluation/arm_a.py
src/mod_agent/evaluation/__init__.py
```

### 禁止范围

- 新 Artifact 类型、Controller、产品入口；
- ArtifactStore/C5、Graph topology、Product Executor；
- `evidence_only.py`、`intelligent_evidence_only.py`、CLI/local entry 的 RAG-1B 迁移；
- Dense/Fusion/RRF/reranker 默认化；
- 完整 Trace、Langfuse/OTel、Dashboard、CI promotion；
- Build/Runtime；
- 从本轮 actual output 生成或修正 Golden。

## 9. 最低测试与验收门

1. 历史 EvidencePack 在 `hook_discovery=None` 时 exact mapping/hash 不变；
2. 新语义段 strict roundtrip，missing/unknown/type/ref/order drift fail-closed；
3. 新 Hook 请求不能消费缺少语义段的历史 pack；
4. required lanes 独立预算，前一 lane 填满不得阻止后续执行；
5. coverage 五态与 provider failure 精确回归；
6. source version/hash drift、supporting 多数命中、answer-leak source 均不能升级权威；
7. score/rank 单独变化不能改变三层充分性；
8. Graph/Planner/Registry 委托同一 owner，静态门禁止重复 source/lane/sufficiency 表；
9. WallCrawler 负向真实 Case 可复现；
10. BetterHitFeedback 历史 source 只能作为 calibration/reference；
11. 正式 BetterHitFeedback corpus 在无答案泄漏且可跨 clone 重建前不得标记 Case ready；
12. Arm A canonical corpus before/after、returned-file live hash 和 protocol identity门通过；
13. adapted evaluator 保持旧三值 Case 兼容，新四值 Case 不丢失 `insufficient/contradictory`；
14. `false_continue_rate` actual 只能来自冻结 EvidencePack；
15. dataset/judgment/protocol/corpus mismatch fail-closed；
16. Standard RAG ResponseBuilder、P2.2 Product Executor focused regressions通过；
17. Dense provider、产品 Build/Runtime、RAG-1B 调用数为0。

## 10. 当前 unresolved contract decisions

```yaml
unresolved_contract_decisions:
  - better_hit_feedback_non_leaking_portable_corpus_manifest
  - better_hit_feedback_current_target_api_il_and_optional_runtime_source_identities
  - better_hit_feedback_independent_human_expected_hook_facts_and_judgment_hash
  - exact_two_case_queries_search_roots_patterns_and_coverage
  - wall_crawler_dataset_and_protocol_identity
  - first_quality_gate_policy_exact_metrics_and_thresholds
  - versioned_case_observation_report_compatibility_serialization
  - rag_reproducibility_binding_exact_applicability_and_nullability
```

只要该列表非空，两份合同不得获得 implementation-approved verdict。独立审核可以确认本文件的 owner、adoption、failure 与禁止扩张边界，但不能据此授权代码。

## 11. 独立合同审核 checkpoint

独立审核已确认本文件成功关闭“没有可 hash、可 diff 合同对象”的治理缺口，但两份实施合同仍为 `changes_required`。除 §10 的外部/数据决定外，还必须在下一修订中闭合：

1. declaration-owned lane coverage grammar：每条 required lane 哪些 coverage 状态满足 requirement，以及 `searched_and_absent`、`not_found`、`covered_with_hits` 对 retrieval sufficiency 的精确影响；
2. planning-ready option 与 required behavior facts 的精确 declaration 字段和 predicate；
3. `source_role` / `authority_class` 的可信输入 owner、合法组合与 `EvidenceDiscoverySource.kind/evidence_class/version_identity` 的 adopt/adapt/defer 关系，禁止 caller 自报 authoritative；
4. `HookDiscoveryExpectedFactsV1` 到现有 `expected_relevant_ids` / `expected_hook_ids` 的 exact projection，以及新 `hook_discovery_actual` 与旧 `decision` 冲突时的 fail-closed 规则；
5. Arm A source/coverage actuals 的独立承载 schema；Arm A 不得伪装成 RAG-1A projector 输出。

上述规则及 §10 未决项闭合并再次独立审核前，禁止修改 RAG/ER/Eval 生产代码。
