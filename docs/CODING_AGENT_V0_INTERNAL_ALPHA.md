# Coding Agent v0 Internal Alpha：实际大目标、产品阶段与执行合同

```yaml
document_status: current_implementation_target
document_version: 2026-08-23-rag-1a-relation-aware-explicit-unresolved
completion_claim: none
implementation_authority: current_user_selected_documentation_scope
created_at: 2026-08-16
target_worktree: rag_capability_mainline
target_branch: codex/rag-capability-mainline
target_head_at_audit: 8c5509e7af3bd8d285a412165583441cdc0788b4
current_checkpoint_at_last_sync: 8c5509e7af3bd8d285a412165583441cdc0788b4
product_milestone: coding_agent_v0
first_integrated_delivery: coding_agent_v0_internal_alpha
active_work_package: none_pending_simple_actual_only_task_selection_and_reliability_preflight
current_product_stage: coding_agent_v0_internal_alpha_actual_only_selection
rag_1a_role: internal_evidence_capability
rag_1b_role: public_entry_adoption
```

> 本文定义当前产品里程碑及其第一条内部集成路径，不声称代码已经完成，不授权产品源码写入、Build、Runtime 或外部披露。
> 当前事实仍由源码、测试、真实运行报告和 `docs/ACTIVE_PRODUCT_CONTRACT.md` 决定；本文不得用于覆盖失败事实。

阅读和执行优先级：`§1 实际大目标与工作包构造 → §5 当前物理状态与第一失败层 → §8 唯一实施顺序 → §9 完成门`。模块清点、行数统计、历史工作树、文档分类和后续成熟化只提供背景，不得覆盖这四处当前执行合同。

## 1. 目标与问题

当前仓库已经分别实现了通用 RAG、工程证据检索、Planning、Patch、Review、Dry-run、Build、Runtime、Repair、Eval、ArtifactStore 和 Workflow 能力，但还没有形成一条唯一、真实、可反复运行且由 observation 改变下一步的 Coding Agent 产品闭环。

当前主要问题不是模块缺失，而是：

- RAG/ER 长期作为只读主线独立优化，真实下游消费者进入过晚；
- 模型一度在第一次观察环境前承担 identity、跨引用和工具参数记账；
- `evidence-request`、`intelligent-evidence-request`、`run-request` 和若干直接 Graph 入口并存；
- WallCrawler、BetterHitFeedback 的领域规则部分进入通用入口或通用 Workflow；
- 当前工作树和其他工作树存在尚未归并的代码、文档和安全加固；
- Trace、Eval、Harness、Artifact 和 Workflow 的语境尚未统一。

Coding Agent v0 的目标是把现有能力组合成一条真实纵向链，不重新建设 Agent SDK：

```text
自然语言请求
→ 观察允许的当前工程环境
→ 形成证据与工程判断
→ Implementation Plan
→ PatchProposal
→ Review / Dry-run
→ 隔离 Build/Test
→ 根据真实失败改变一次下一步
→ 完成或明确阻断
```

### 1.1 当前唯一实际大目标

当前大目标不是“继续完善 RAG、EvidencePack、Graph 或失败处理”，而是在一个不预填目标文件、符号或 Patch 答案的自然语言 Issue 上，由同一个 Agent Runner 完成一条可客观判定的工作闭环：

```text
自然语言 Issue
→ 从当前受控工作区 observation 自主定位文件、符号和引用
→ 阅读源码、测试和当前工程证据
→ 形成可由真实消费者使用的 EvidencePack
→ 形成非阻断 Implementation Plan 和受限 PatchProposal
→ Review / Dry-run / 隔离 Apply
→ 执行预先绑定的客观 Build/Test 成功命令
→ 若失败，将真实诊断作为 observation 返回 Agent
→ 形成与首次不同的受限修复
→ 再次 Build/Test
→ 测试通过，或在支持边界内保存物理证据并明确停止
```

Internal alpha 的产品完成必须同时证明：

1. 至少一条受支持 actual-only 任务最终 Build/Test 通过；
2. 至少一次真实 Build/Test 失败改变后续语义动作，并完成不同修复和再次验证；
3. 全过程没有读取 Golden、annotation、历史 Patch 或预填工程答案；
4. 所有写入发生在授权的隔离工作区，修改范围可审查且 `scope_violations=0`；
5. 结果由 Build/Test、diff、Artifact 和运行报告等物理事实判定，不由模型自评。

受控小工程可以证明 Runner、Patch、Build 和 Repair 的机械闭环，但不能单独证明大型仓库、GTFO 领域任务或生产成熟度。Internal alpha 完成后必须使用现有仓库中的真实小型 Issue 复核文件定位和修改能力，再进入 RAG-1B、领域 Harness 和 public alpha。

### 1.2 大目标驱动的工作包构造

本节落实 OpenAI Docs 的结果导向工作方式：给出目标、相关上下文、硬约束、授权边界、所需证据、成功标准和输出格式；对 change/build/fix 请求，在授权范围内连续完成修改、检查和结果复核，不在每个安全步骤停顿。它是推进与交接格式，不新增 Product Schema、Artifact、Gate、审批状态或 Workflow 节点。

每个工作包开始前必须明确：

```yaml
actual_product_goal:
real_task:
objective_success_command:
workspace_and_revision:
current_product_stage:
target_next_product_stage:
first_physical_blocker:
why_this_change_advances_the_goal:
authorized_change_scope:
hard_constraints:
required_physical_evidence:
success_criteria:
stop_condition:
handoff_output:
```

工作包结束时必须回传：

```yaml
claimed_completion:
completion_level:
new_product_stage_crossed:
objective_result:
capability_advanced:
physical_evidence:
observation_changed_next_action:
not_completed:
first_remaining_failure:
responsible_subsystem:
checkpoint_and_worktree:
next_product_stage:
```

构造规则：

- 大目标先于局部实现。局部修正只能来自同一真实任务的第一物理阻断，并必须说明修正后预期跨过哪条产品阶段箭头；
- 安全、范围内的代码修改、相关非破坏性验证、diff 复核和一次必要重放属于同一工作包授权，不需要逐步暂停确认；外部写入、破坏性操作、昂贵操作或实质扩张范围仍需单独授权；
- 环境、fixture、索引或依赖准备必须与产品能力分开报告；修复环境只能声明前置条件成立，不能声明 Coding Agent 阶段前进；
- 新测试、错误码、Schema、validator、版本、文档、运行编号或 checkpoint 只能支持能力交付，不能替代 `Issue → Files → Patch → Build/Test → Repair → Revalidation` 的阶段前进；
- 若没有跨过新的产品阶段，必须写 `capability_advanced: false`，说明本轮只改善了基础、可见性或诊断；
- 连续两个工作包没有跨过产品阶段时，停止继续细化同一局部合同，重新检查真实任务、输入表示、工具面、Agent/Workflow 分工和组合方式；
- 工作包不能用“纵向链”“闭环”“健壮性”作为无验收条件的抽象目标，必须绑定真实 Issue、成功命令、当前工作区身份和最终物理结果。

官方依据：

- [OpenAI 模型指导：目标、上下文、约束、证据、成功标准与自主性边界](https://developers.openai.com/api/docs/guides/latest-model)
- [OpenAI Developers：把 issue 变成可工作的修改，运行检查并审查结果](https://developers.openai.com/)

## 2. 统一术语

| 名称 | 当前唯一含义 | 不拥有的权力 |
| --- | --- | --- |
| 智能面 | 模型理解需求、选择调查方向、解释 observation、决定下一步语义动作 | 来源身份、权限、持久化真相和最终执行权 |
| 控制面 | 权限、预算、副作用、恢复、Artifact commit 和执行边界 | 搜索方向和工程事实解释 |
| Workflow | 可靠执行外壳、条件路由、interrupt/resume 和阶段恢复 | 预先决定 Hook、修改方案或失败后的工程方向 |
| RAG | 找到与请求相关的文档、源码和结构 | 把相关性自动升级为当前工程事实 |
| ER | 将相关信息绑定为当前版本、当前来源的工程事实 | Patch、Build 或 Runtime 权限 |
| RAG-1A | 证明内部证据发现、验证、关系和充分性能力成立 | 公共入口采用 |
| RAG-1B | 让公共产品入口采用同一 RAG-1A executor 和结果 | 重新优化检索或另建语义所有者 |
| Coding Agent v0 | `Evidence → Patch → Build/Test → 一次修复` 的产品里程碑 | 开放式无限自治和通用多 Agent 平台 |
| v0 internal alpha | 使用内部调用面消费真实 EvidencePack 的首个集成证明 | 公共 API 稳定性和生产质量声明 |
| 领域 Harness | 控制 GTFO、插件、进程、日志、截图和恢复 | 通用 Agent 工程语义 |
| Agent Harness | 运行完整 Agent 任务并保存输入、动作、观察和结果 | Golden 真相和产品审批 |
| Eval Harness | 回放数据集并比较 actual 与 expected | 修改 actual 或授予副作用权限 |
| Trace | 记录发生了什么及其关联 | 决定证据真假、充分性或权限 |
| 本地小助手 | 本地模型 provider 和模型身份 | 独立产品 Agent 或长期记忆 |
| Skill/Playbook | 可复用过程知识 | 当前产品事实、运行状态或工具权限 |
| Memory | Agent 在步骤内或跨任务可读取的状态 | Artifact 历史的自动可信化 |

## 3. Observation 的精确定义

Observation 是 Agent 执行动作后，从工具、文件、索引、编译器、测试、Runtime 或用户确认中返回的、可定位到发生时环境的结果。

它至少回答：

- 执行了什么动作；
- 观察到什么结果；
- 来源、版本、路径或 Artifact 身份是什么；
- 动作成功、失败还是只得到部分结果；
- 哪些事实是直接观察，哪些仍是推断或未知。

本项目中的 observation 包括：

- `rg`、BM25、symbol 或 live-read 返回的源码片段和位置；
- metadata 返回的程序集 SHA、MVID、类型、方法和 token；
- IL inspector 返回的当前方法体；
- ArtifactStore commit/read 的结果；
- Dry-run diff；
- Build/Test 的 exit code、诊断和输出 Artifact；
- GTFO Harness 的进程、日志、标记、截图和恢复结果；
- 明确绑定运行身份的人工观察。

模型生成的解释本身不是 observation；它是对 observation 的推断。Workflow 节点完成也不等于工程事实充分。

“Agent 行为成立”的最小证明是：新的 observation 会改变下一步调查或修改动作。固定执行 `search → patch → build` 但不根据结果调整，只是 Workflow。

### 3.1 结果导向的完整工作包原则

本节是指导性推进原则，不新增 Gate、Artifact、审批状态或 Workflow 节点。“完整工作包”是本项目用于落实结果导向协作的管理抽象，不是 OpenAI 官方术语，也不要求单轮完成整个产品里程碑。

| 内容 | 来源与当前解释 |
| --- | --- |
| 目标导向、范围明确、结果可验证 | OpenAI 官方明确建议提供目标、相关上下文、硬约束、所需证据、成功标准和输出要求 |
| 修改后运行检查、审查结果 | OpenAI 官方明确建议 change/build/fix 请求完成范围内修改并执行相关非破坏性验证；Codex 产品说明强调形成可工作的修改、继续迭代、运行检查并审查 diff |
| 不在每个安全步骤停顿 | OpenAI 官方明确建议给出自主性与批准边界，使安全、范围内工作可以持续推进，在外部写入、破坏性、昂贵或实质扩张范围前停止 |
| “完整工作包”这个名称 | 本项目管理抽象，用于防止局部协议修改替代能力交付 |
| 每个工作包具体多大 | 由真实依赖、风险、运行成本和验证成本决定；复杂目标允许拆成多个 checkpoint |

官方依据：

- [OpenAI 模型与自主性指导](https://developers.openai.com/api/docs/guides/latest-model)
- [OpenAI Codex 工作方式](https://developers.openai.com/)

本项目中的完整工作包至少包含：

```text
一个明确能力目标
→ 必需的范围内修改
→ 一次真实运行或真实消费者调用
→ 与改动风险相称的验证
→ 可复现的结果和 diff
→ 成功进入下一能力阶段，或准确停在第一物理失败层
```

工作包不以修改文件数、测试数量、Schema 字段、错误码或文档页数作为完成标准。它也不要求一次完成整条 `Evidence → Patch → Build/Test → Runtime`；例如“证据不足时 ImplementationPlanner 正确阻止 Patch”和“可信 EvidencePack 进入 Build/Test”可以是两个独立工作包。拆分后的每一包仍必须产生可观察价值，不能只有未来才会被消费的结构。

每个 change/build/fix 工作包应在开始时明确：

```yaml
goal:
context:
in_scope:
hard_constraints:
authorization_boundary:
success_criteria:
real_run_or_consumer:
validation:
stop_condition:
```

安全、非破坏且范围内的读取、编辑、定向测试和运行事实收集默认连续完成；外部写入、破坏性操作、昂贵操作、权限扩大或实质扩张范围仍需明确授权。

### 3.2 最小失败处理闭环

当前已证明的负向链只覆盖失败处理体系中的一个分支：

```text
证据不足
→ ImplementationPlanner 读取 committed EvidencePack
→ proposed_changes=[]
→ patch_allowed=false
→ 返回具体证据缺口
```

它证明“不该继续时能够安全停止”，但尚未证明“本来应该继续却失败时，Agent 能根据失败 observation 改变动作”。v0 internal alpha 应沿正向消费者链同步补齐最小失败闭环，不先建设独立失败平台、完整 Trace 平台或新的控制面。

#### 3.2.1 失败类型与有界处理

| 第一物理失败 | 最小处理 | 不应采取的处理 |
| --- | --- | --- |
| 结构化输出不合法 | 保存原始输出；使用同一 Schema 和一致策略纠正一次；仍失败则返回明确结构化错误 | 为单一模型错误增加持久版本或模型专属分支 |
| 工具输入可确定性修复 | 从当前 Registry、observation 或运行内 handle 恢复精确参数后重试一次 | 让模型重抄路径、hash、MVID、token 或长引用 |
| 来源或身份已变化 | 重新观察并重新绑定当前身份；无法验证时停止 | 使用旧身份继续执行 |
| 暂时性工具执行错误 | 在明确重试预算内重试；保存两次物理结果 | 无限重试或把工具故障解释成证据不足 |
| 合法零结果或部分结果 | 作为 observation 返回智能面，由模型换调查方向或停止 | Workflow 固定跳到下一工具或伪造成功 |
| 环境、权限或依赖缺失 | 返回明确阻断和恢复条件 | 修改 Prompt 规避环境事实 |
| 证据不足 | 安全拒绝 Patch，并给出最小调查或 Runtime Probe | 强行继续或修改 Golden 适配 actual |
| Patch/Apply 被拒绝 | 保存范围、权限或事实缺口，回到对应 owner | 放宽来源、权限或副作用完整性 |
| Build/Test 失败 | 保存 exit code、诊断和输出；让 Agent 基于该 observation 形成一次不同的受限修复；再次验证 | 机械重复同一 Patch 或把测试失败直接标为完成 |
| Runtime 失败 | 由领域 Harness 保存进程、日志、标记、截图和恢复事实，再决定是否回到证据、Plan、Patch 或环境 | 用 Runtime Harness 反向决定通用 Agent 工程语义 |

格式或工具重试只用于可恢复失败，并必须有固定上限。证据不足不是需要“重试到成功”的异常；它是合法工程结果。来源身份伪造、actual 读取 Golden、不存在的 observation 引用、未经 metadata 观察读取 IL、未经授权的写入/Build/Runtime 继续 fail-closed。

#### 3.2.2 运行事实和失败归因

每次纵向运行至少在现有运行报告或 Trace 事实中保存：

```yaml
request_ref:
current_stage:
first_failure_stage:
failure_kind:
physical_observation_refs:
retry_count:
agent_next_action:
next_action_changed_by_observation:
result_after_retry_or_repair:
responsible_subsystem:
model_prompt_tool_source_identity:
elapsed_and_token_usage:
```

`responsible_subsystem` 只用于定位 owner，不授予该模块事实解释权。Trace 记录发生了什么，Eval 比较结果和轨迹，Evidence Reasoning 解释工程证据，控制面决定副作用权限；它们不得互相改写。

失败归因至少区分：

```text
structured_output_failure
retrieval_relevance_failure
source_identifier_selection_failure
source_to_metadata_mapping_failure
metadata_identity_failure
il_inspection_failure
engineering_evidence_insufficient
implementation_planning_failure
patch_scope_or_authority_failure
build_compilation_failure
test_behavior_failure
runtime_failure
environment_or_permission_failure
timeout_or_budget_failure
```

只有已有代码中实际登记该名称时，运行时才使用对应标识；本列表首先是文档级归因维度，不授权根据名称猜测或重命名现有字段。

#### 3.2.3 测试与推进速度

失败闭环用于缩短“定位 → 修改正确 owner → 重放”的周期：

```text
开发中：第一失败层的 owner 窄测试 + 同阶段重放
工作包完成：真实消费者或真实纵向运行
checkpoint 前：受影响模块完整回归 + diff 审查
里程碑：端到端真实任务 + actual/expected 隔离 Eval
```

失败分类、错误码和测试本身不算能力前进。每个工作包仍应推动真实运行进入下一阶段，或证明安全拒绝本身就是所需产品结果。

当前优先建设失败处理的准确含义是：把格式、工具、Build/Test repair 和失败归因嵌入正在推进的正向 v0 链；不是暂停可信正向 EvidencePack 和 Patch/Build 消费，先建设通用异常框架。前者预计能显著减少跨层误修和重复全链调试；后者会延迟真实消费者进入。

#### 3.2.4 与原始 `.txt` 失败处理思想的覆盖关系

| 原始思想 | 当前状态与进入时机 |
| --- | --- |
| 证据不足必须拒绝，不编造答案 | 当前中文 BHF 负向消费路径已证明；继续进入正确拒答 Eval |
| Case 包含禁止断言、是否拒绝、缺失证据和最小 Probe | Golden/Hidden-Golden 已有方向；关系级评分和 Runtime Probe 尚未闭合 |
| JSON Schema 验证、统一重试一次、仍失败则优雅返回错误 | Discovery 局部存在；需在唯一 Agent Runner 中形成一致策略，不新增第二套 Schema |
| Coding Agent 定位文件、修改、运行测试直到通过，并具备失败回退 | Planning/Patch/Build/Repair 模块存在；正向纵向证明和一次 observation-driven repair 尚未完成 |
| 失败时说明花费、可复现性和危险操作批准 | 模型、Prompt、来源、Artifact 和运行身份已有局部记录；统一成本报告、稳定性统计和副作用批准证据随真实 v0 运行补齐 |
| 轨迹、最终结果和单步评测 | 当前只需保存完整运行事实；RAG-1A 收口做最小关系/失败 Eval，3–5 个真实任务后再成熟化端到端轨迹评测 |
| 同一任务重复运行并报告波动 | 正式模型和稳定性实验尚未开始；按本地模型实验文档在标准化任务集上执行 |
| Token、延迟、工具次数和失败率 | 局部报告已有；统一指标在唯一 Runner 形成后汇总，不先建设 Dashboard |
| 正确拒答率、held-out 和应拒答 P0 不得强行继续 | Golden/Eval 已登记；完成实际映射后进入回归质量门 |
| Build 成功但 Runtime 失败、旧版本失效、社区与当前程序集冲突 | 作为后续真实 Case 来源；Runtime 闭环和扩大评测集时进入 |

因此，当前文档在概念和开发顺序上登记了原始 `.txt` 的主要失败处理思想，但“登记”不等于“代码已经实现”。当前物理实现只证明证据不足安全拒绝、局部结构化验证、部分工具失败边界和可复现 Artifact；Build/Test repair、Runtime 回流、统一失败归因、稳定性、成本和成熟轨迹 Eval 仍需按真实消费者顺序完成。

#### 3.2.5 失败处理成熟范围与当前目标

以下分层用于说明能力边界和进入顺序，不新增运行时状态机、Approval、质量门或 Artifact 版本。成熟度只能由真实运行证明，不能由字段、测试数量或文档声明自动提升。

| 层级 | 成熟范围 | 当前事实与进入条件 |
| --- | --- | --- |
| F0 安全拒绝 | 证据不足时不编造 Patch；返回具体缺口 | 中文 BHF 负向消费路径已证明 |
| F1 一致失败事实 | 结构化输出原文、第一失败层、工具输入/执行/零结果/环境失败分开记录；可恢复失败有界重试 | 当前局部存在；在正向 v0 链中统一，不单建平台 |
| F2 Observation-driven repair | Patch、隔离 Build/Test、诊断回传、一次不同的受限修复和再次验证 | v0 internal alpha 当前目标；尚未证明 |
| F3 Runtime 与评测成熟化 | Runtime 失败回流；最终结果/轨迹/单步 Eval；正确拒答、held-out、重复运行稳定性、成本和失败率 | 在 F2 和 3–5 个真实任务后逐步进入 |
| F4 生产可靠性 | 多任务回归、并发隔离、长期恢复、权限审计、预算、保留策略、服务监控和运维 | public alpha 与真实运行数据成立后进入 |

F1 和 F2 是当前开发范围。F3、F4 是明确产品目标，但不应提前成为正向 EvidencePack、Patch 和 Build/Test 的阻断项。

进入下一工作包前只完成以下必要前置，不扩张成独立设计阶段：

1. 以可恢复 checkpoint 固定当前代码输入，保留已有文档 WIP 的独立身份；
2. 只读核对唯一内部 Runner 实际调用的结构化输出、工具执行、Build、Repair 和运行报告 owner；
3. 固定一条不读取 Golden、历史实现或预填 Hook 的正向真实请求，以及允许来源、模型、Prompt、程序集和 Build/Test 环境身份；
4. 明确本包成功标准为 `可信 EvidencePack → Plan → Patch → Build/Test → 一次 observation-driven repair → 再次验证`；
5. 明确停止条件：停在第一物理失败层并保存原始事实；不得在同一包跨层增加 Schema、Trace、控制面或模型专属规则；
6. 确认所有失败事实首先进入现有运行报告或 Trace 事实，只有真实消费者证明不可重新推断时才进入持久 Artifact。

随后开发不得把 F1 当作 F2 的前置平台。每跨过一个真实阶段，就在该阶段接入对应的最小失败处理：

```text
结构化模型回合
→ 一致验证、一次纠正、明确失败

工具调用
→ 输入/身份/执行/零结果/环境分流、有界恢复

Patch 与 Build/Test
→ 原始诊断 observation、一次不同修复、再次验证

整条运行
→ 第一失败层、负责模块、动作是否因 observation 改变
```

F2 成立后立即以真实运行数据进入 RAG-1A 收口、最小关系 Eval 和 RAG-1B 公共采用；不继续独立扩张失败处理合同。

#### 3.2.6 最小失败闭环的工程加速验证

最小失败闭环完成后，不直接声明“已经加速”。先执行一次有界的工程效率验证，回答它是否减少真实定位、修复、重跑和人工协调时间，同时保持任务结果、正确拒绝和事实完整性不退化。

验证不新增生产开关、Trace 平台或专用控制状态。数据来自现有运行报告、Git diff、测试命令和工作包开始/结束时间。若历史工作包缺少可比时间字段，应明确标为不可比较，不补造时间。

验证对象分两层：

1. **受控重现层**：各选择一个可复现的结构化输出失败、工具失败和 Build/Test 失败，核对新闭环能否准确给出第一失败层、负责模块、允许的有界恢复和最终结果；
2. **真实工程层**：连续记录最小失败闭环完成后的三个真实工作包，与此前三个最接近的工作包做方向性对照，不挑选最好结果，不将不同难度任务解释成严格因果实验。

至少记录以下可复算指标：

| 指标 | 定义 | 期望方向 |
| --- | --- | --- |
| `time_to_first_failure_attribution` | 运行开始到第一失败层和负责模块被确定的时间 | 降低 |
| `failure_to_next_validated_action_time` | 第一次失败到下一次经验证动作的时间 | 降低 |
| `time_to_next_capability_stage` | 工作包开始到真实运行进入下一阶段或形成正确安全拒绝的时间 | 降低 |
| `full_chain_replay_count` | 为解决同一失败而重新执行完整纵向链的次数 | 降低 |
| `cross_layer_edit_count` | 同一失败处理中修改非负责模块的次数 | 降低 |
| `manual_intervention_count` | 需要人工判断路由、重启、改写输入或解释错误的次数 | 降低 |
| `repeated_same_failure_count` | 修正后再次出现同一物理失败的次数 | 降低 |
| `targeted_test_wall_time` | 定向定位与验证所用测试墙钟时间 | 降低或保持 |
| `checkpoint_regression_wall_time` | checkpoint 完整相关回归时间 | 可以保持；不得通过少跑必要回归伪造加速 |
| `tool_calls`、`model_calls`、`tokens`、`elapsed` | 单工作包的工具、模型和资源成本 | 记录权衡，不要求全部降低 |
| `task_or_safe_stop_correct` | 成功结果正确，或证据不足时正确停止 | 必须保持 |
| `source_and_artifact_integrity` | 来源、身份、actual/expected 隔离和 strict rehydrate | 必须保持 |

方向性结论分为：

```yaml
engineering_acceleration_verdict:
  accelerated: 关键周期缩短，跨层误修或重跑减少，质量与完整性不退化
  mixed: 部分指标改善，但成本转移、任务难度或样本不足使结论不稳定
  not_accelerated: 没有缩短关键周期，或引入额外恢复复杂度
  inconclusive: 缺少可比基线、运行中断或样本不足
```

本验证只回答“最小失败闭环是否改善当前工程循环”，不证明通用 Agent 生产成熟度。若结果为 `mixed`、`not_accelerated` 或 `inconclusive`，只根据实际数据修正失败事实记录、owner 路由或恢复预算；不得以此恢复大型失败平台、完整控制面或新的持久协议。

插入该验证后的工作顺序为：

| 顺序 | 工作包 | 真实交付 | 失败处理位置 |
| ---: | --- | --- | --- |
| 0 | 可恢复输入与必要前置 | 当前代码 checkpoint；唯一内部 Runner、失败 owner、正向输入和 Build/Test 环境身份核对 | 不新增失败平台 |
| 1 | 正向 BHF 证据链 | 自然语言请求进入 source、metadata、IL 并形成可信 committed EvidencePack | 同步统一结构化输出和工具失败事实、有界恢复 |
| 2 | Plan/Patch/Build | EvidencePack 被 ImplementationPlanner 消费，形成受限 Patch、Dry-run 和隔离 Build/Test | 保存 Patch/Apply/Build/Test 第一物理失败 |
| 3 | Observation-driven repair | Build/Test observation 导致一次不同的受限修复并再次验证 | 完成 F2 |
| 4 | 工程加速验证 | 受控三类失败重现 + 后续三个真实工作包方向性对照 | 验证是否真正减少定位、误修和重跑时间 |
| 5 | RAG-1A 收口 | BHF 正向、WallCrawler 负向、Hidden-Golden、最小关系 Eval 和失败归因 | 将真实失败样本纳入 Eval |
| 6 | RAG-1B 与 v0 public alpha | 唯一公共入口采用同一 Agent Runner 和 Evidence executor | 公共结果保持同一失败语义和关联 |
| 7 | Runtime 闭环 | Build 产物进入领域 Harness，Runtime 失败可回流 | 进入 F3 的 Runtime 分支 |
| 8 | Trace/Eval 与模型成熟化 | 3–5 个真实任务后完善轨迹 Eval、稳定性、成本和模型比较 | 完成 F3 的评测范围 |
| 9 | 工具、Memory、Skills、子智能体与生产成熟化 | 由多任务数据决定工具扩展、运行内/长期 Memory、并发和恢复 | 按真实数据进入 F4 |

## 4. 当前模块归位

### 4.1 通用 RAG 与工程知识层

- `src/core/query_engine/`：通用 Dense、Sparse、Hybrid/RRF 和 query processing；
- `src/ingestion/`：摄取、切块、embedding 和通用 BM25 持久化；
- `src/libs/`：LLM、embedding、reranker、loader、splitter 和 vector store；
- `src/mod_agent/knowledge/`：工程来源 Registry、SQLite、symbol 和 Mod Agent BM25；
- `src/mod_agent/evidence/`：工程检索、Discovery、metadata/IL、Evidence Reasoning 和 EvidencePack。

两套 BM25 当前继续并存。只有真实运行证明它们造成 chunk identity、freshness、citation 或过滤行为冲突时，才进行统一；代码重复本身不阻断 v0。

### 4.2 交付与控制执行层

- `src/mod_agent/planning/`：请求与 Implementation Planning；
- `src/mod_agent/proposal/`：Patch 生成和评审；
- `src/mod_agent/execution/`：no-write 与受控 Apply；
- `src/mod_agent/build/`：Build adapter；
- `src/mod_agent/runtime/`、`src/mod_agent/domain/`：领域 Harness；
- `src/mod_agent/repair/`：真实失败后的受控修复规划；
- `src/mod_agent/workflow/`：现有单一 LangGraph 执行外壳；
- `src/mod_agent/artifacts/`：持久业务输出和 lineage；
- `src/mod_agent/product_executor.py`、`src/mod_agent/local_entry.py`：现有产品执行和本地入口资产。

v0 不新增第二 Graph。统一 Agent Runner 应组合现有 Product Executor、Graph 和各模块 adapter；随着 RAG-1B 采用完成，旧入口改为委托或退出。

### 4.3 Eval、Trace、Harness 与模型

- `src/mod_agent/evaluation/`：Agent quality、Hidden-Golden、回归和质量策略；
- `src/observability/evaluation/`：通用 RAG evaluator；
- `src/core/trace/` 与 `workflow_trace`：当前局部运行记录；
- GTFO Runtime 代码：领域 Harness；
- `tests/`：当前 Agent/Eval Harness 的主要执行载体；
- Ollama 和其他 LLM adapter：provider，不拥有 Agent 产品语义。

v0 首次运行只需关联 request、EvidencePack、plan、patch、build attempt、repair attempt 和 final result。完整 Trace 平台、Dashboard、长期指标和跨系统 exporter 不作为 v0 前置。

### 4.4 历史代码资产审计快照（2026-08-16，附录性输入）

本节保留选择 internal alpha 时的代码资产审计，解释哪些模块可复用、需要整合或暂缓。行数、WIP、HEAD 和“最新运行”描述均不是 live status，不创建当前工作；当前事实只读 §5。

本节记录 `rag_capability_mainline` 在 Coding Agent v0 internal alpha 实施前的代码资产状态。统计基于当前工作树中受 Git 跟踪且实际存在的文件；生产源码以 `src/` 为口径。行数分类按文件职责互斥归属，不是运行时 coverage，也不表示分类内每一行都将在单次 v0 运行中执行。

| 范围 | 文件数 | 行数 |
| --- | ---: | ---: |
| 生产源码 `src/` | 213 | 106,384 |
| 测试 | 138 | 89,071 |
| 脚本 | 10 | 3,059 |
| 测试函数 | - | 1,247 |

测试代码约为生产源码的 83.7%。这证明仓库积累了大量局部门和协议验证，但不能单独证明端到端产品闭环成立。

按文件职责形成以下互斥分类：

| 分类 | 文件数 | 行数 | 占生产源码 | 解释 |
| --- | ---: | ---: | ---: | --- |
| 可直接复用 | 74 | 33,817 | 31.8% | internal alpha 可组合使用，架构职责基本正确 |
| 需要修改、整合或降权 | 12 | 31,148 | 29.3% | 保留主要能力，但入口、语义 owner 和 Agent/Workflow 边界需要处理 |
| 暂缓进入 internal alpha | 127 | 41,419 | 38.9% | 不是废代码，但不应阻塞首个闭环 |
| 已证明应删除 | 0 | 0 | 0% | 当前没有足够物理证据授权整模块删除 |

因此第一产品闭环会触及或依赖的结构性资产范围约为：

```text
33,817 行直接复用
+
31,148 行整合后复用
=
64,965 行，占生产源码 61.1%
```

该数字不等于运行时已执行 64,965 行，也不授予重写全部 31,148 行的范围。

可直接复用的主要资产为：

| 能力 | 行数 |
| --- | ---: |
| Evidence 可复用部分 | 6,691 |
| Artifact | 5,403 |
| Workflow checkpoint/state/transition 等支撑 | 4,185 |
| LLM provider | 3,540 |
| Knowledge | 3,034 |
| Proposal/Patch | 2,934 |
| Repair | 1,611 |
| Planning | 1,382 |
| Domain adapter | 1,161 |
| Bindings | 987 |
| Apply | 603 |
| Build | 575 |
| Git adapter | 506 |

其中 `Planning → Proposal → Apply → Build → Repair` 已有约 7,105 行实现。该句是 2026-08-16 的审计结论；2026-08-17 的 actual-only 运行已经把 committed EvidencePack 交给该链并到达 Repair，详见 §5。

需要修改、整合或降权的 31,148 行按文件职责分布如下：

| 改动面 | 行数 | 当前问题 |
| --- | ---: | --- |
| `src/mod_agent/local_entry.py` | 9,752 | 本地模型、Graph、Build、Runtime 和产品呈现集中在单文件 |
| `src/mod_agent/workflow/graph.py` | 4,638 | Workflow 混入 GTFO、Stagger 和 BHF 工程语义 |
| Discovery contract/loop | 5,886 | Planning quality 仍可在第一次 observation 前阻止检索 |
| Edit authority/verification | 4,858 | 应保护副作用和物理事实，不应主导 Agent 调查语义 |
| Product executor/execution | 3,193 | 可作为统一 Runner 的基础，但目前与其他入口职责重复 |
| CLI、智能证据入口及 Graph 导出 | 2,821 | 多入口、WallCrawler 默认值和多个自行建 Graph 的路径并存 |

2026-08-16 审计时没有统一的公共 Agent Runner。`evidence_only.py`、`intelligent_evidence_only.py`、`local_entry.py`、`product_executor.py` 和 `workflow/__init__.py` 均可直接调用 `build_graph()`。Internal alpha 当前只复用现有 `run_local_request()`、`ProductExecutionRequestV1`、`ProductExecutionAdaptersV1`、`preflight_product_execution()`、`execute_product_execution()` 和同一 `build_graph()` 形成内部单链；公共入口统一仍属于 RAG-1B/public alpha，不得在当前 Repair 工作包中扩张。

暂缓进入 internal alpha 的 41,419 行分布为：

| 子系统 | 行数 | 当前处理 |
| --- | ---: | --- |
| GTFO Runtime/领域 Harness | 17,265 | Build/Test 闭环后按真实需求接入 |
| 标准 RAG 基础 | 11,703 | 保留；不因两套 BM25 并存而暂停 v0 |
| Eval/Trace/Dashboard | 7,345 | internal alpha 仅复用最小事实记录，不建设平台 |
| MCP/API/Dashboard 公共接口 | 3,621 | RAG-1B/public alpha 再统一采用 |
| 其他支撑 | 900 | 保留 |
| Calibration/Dense | 585 | 用于评测或后续检索实验 |

Runtime 中约 11,014 行为 Stagger 命名代码。它们尚未真正退出，仍通过 CLI 和 Graph 暴露；应保留为 GTFO Domain Harness，但不得继续决定通用 Agent 流程。

下列激活状态是 2026-08-16 的历史审计快照，不是当前状态：

```text
已激活：
自然语言需求
→ 两段模型规划
→ 确定性 identity 展开
→ Search Plan validator

未激活：
source observation
→ metadata
→ IL
→ EvidencePack
→ Implementation Plan
→ Patch
→ Build/Test
→ Repair
```

该历史运行包含两个结构化模型回合，但工具动作接受、source/metadata/IL dispatch、observation 和 EvidencePack commit 均为零。该失败已经被后续运行跨过，不能继续作为当前第一失败层，也不能重新创建 Search Planning 工作包。

当时的代码/测试 WIP 为 11 个文件、`+2861/-145`。该 WIP 已经经过后续多个 checkpoint 收敛；当前工作树身份只使用 §5 的记录。

## 5. 当前实际任务、产品阶段和第一失败层

> 本节是 2026-08-20 repository explicit-unresolved 同步快照。它是本次 r8 运行详细事实的唯一文档主记录；其他权威文档只保留摘要和本节引用。

### 5.1 当前实际大任务

```yaml
actual_product_goal: coding_agent_v0_internal_alpha
real_task: "When the inspector is given an assembly path that does not exist, it must return exit code 5 and a concise missing-file diagnostic without printing an unhandled exception stack trace. Preserve existing behavior for valid managed assemblies."
task_kind: repository_actual_only_dotnet_issue
prefilled_target_file: false
prefilled_patch_answer: false
golden_or_annotation_visible: false
source_workspace: C:/Users/10160/.codex/visualizations/2026/08/11/019ff15f-9eac-7b13-aad5-faffde4b36b7/rag_capability_mainline/scripts/r8_il_inspector
isolated_workspace: C:/Users/10160/.codex/visualizations/2026/08/11/019ff15f-9eac-7b13-aad5-faffde4b36b7/r/internal_alpha_repo_issue/runs/32e29415/generated_mods/r8_il_inspector
current_checkpoint: e436434dc894df87339b2f3a6767f34477989426
current_worktree_code_wip: "none; four user documentation changes remain independent"
current_wip_staged: 0
current_wip_committed: true
```

客观成功命令、模型/Prompt、工作区 revision、权限和 Build/Test 环境必须绑定在该任务运行报告中；文档不复制会随机器变化的命令输出，也不得在未读取报告时猜测其精确值。

### 5.2 已跨过的真实产品阶段

```yaml
issue_to_files:
  passed: true
  observed_file: Program.cs
evidence:
  committed: true
  store_read: passed
  strict_rehydrate: passed
plan:
  implementation_plan_blocking: false
patch:
  first_patch_proposal_created: true
  repair_attempt_1_patch_created: true
dry_run:
  initial_passed: true
  repair_attempt_1_passed: false
apply:
  initial_isolated_apply_performed: true
  repair_attempt_1_isolated_apply_performed: false
build_test:
  baseline_compilation: passed
  initial_patch_compilation: failed
  initial_compiler_diagnostic_count: 14
  final_run_repair_build_reached: false
repair:
  failure_observation_consumed: true
  exact_edit_binding_grouped: true
  grouped_change_count: 1
  repair_patch_created: true
  repair_review_decision: approve_dry_run
  repair_dry_run_structural_gate: rejected
revalidation:
  earlier_bounded_runs_reached_second_apply_build: true
  repository_objective_passed: false
final_result:
  completed: false
  classification: explicit_unresolved_repository_result
```

基线 `dotnet restore`、`dotnet build --no-restore` 和目标 DLL 验证通过。首次 Patch 经 Review、Dry-run 和隔离 Apply 后产生 14 条 C# 编译器诊断；这些诊断全部确定性解析到同一 `edit_binding_001`。最终 run `32e29415` 的 Repair provider 请求通过 context admission 并返回完整 structured response，Repair PatchProposal 与 approving ProposalReview 均已提交；现有 Dry-run C# structural gate 随后在任何 Repair Apply/Build 前拒绝 unmatched closing brace。

早期有界 runs `30716fd2` 与 `94aa1450` 已真实到达 Repair Apply 和第二 Build，但生成动作没有恢复缺失声明，Build 仍以同类 `assemblyPath`/`peReader` `CS0103` 失败。跨 run 的同一模型/config 又分别出现 Review source representation、无效 Build 修复和 structural-invalid Dry-run 结果；继续完整 rerun只会增加抽样，不提供新的 owner 证据。标准 .NET profile 仍只证明 run-local NuGet 配置与可写缓存隔离，不声明完全 hermetic，也不把 `dotnet` 子进程当作 OS sandbox。

### 5.3 当前第一物理失败层

```yaml
current_product_stage: explicit_unresolved_repository_result
claimed_completion: false
completion_level: explicit_unresolved_repository_result
new_stage_crossed: false
first_physical_failure: repair_attempt1_patch_structurally_invalid
terminal_failure: dry_run_apply_execution/unmatched_closing_brace
responsible_subsystem: repair_model_output_semantic_structural_quality
capability_advanced_platform: true
capability_advanced_product: false
failure_observation_consumed: true
repair_changed_action: true
repair_revalidation_completed: false
repository_objective_passed: false
source_revision_binding: missing
r8_continue_authorized: false
```

当前 first physical failure 是 Repair attempt 1 的模型输出结构无效；ProposalReview 返回 `approve_dry_run`，但 Dry-run 以 `unmatched '}' at character 2141` 正确拒绝，因此不是 Dry-run gate 故障。repository objective 未通过，internal alpha 完成门中的 supported-task pass、verified repair 和 repair revalidation 仍为 false。最终 verdict 禁止继续 r8 run、切模型、手工修 Patch、增加 correction、修改 Review/Dry-run/Graph/continuation 或提高 budget/context。

最终运行身份：

- checkpoint：`e436434dc894df87339b2f3a6767f34477989426`；
- run：`32e29415`；`run_result.json` SHA256：`B7B3F473F8DA8E2500DA67E496DC389B8B9BB5109D8056F49FC170CEB2ED7AD9`；
- Repair PatchProposal：`7ea98cdaae92ead43248a448d81ded4e8ae392fbc1c5d7718238d90d51828253`；ProposalReview：`c06e12d276f2be52526499528c4d3e1e5ea41c500407c36bc5549f7df38f37b3`；
- exact diagnostic projection focused：`3 passed`；完整 `test_local_entry.py`：`90 passed`；`test_repair_loop.py`：`29 passed`。

canonical `Program.cs` SHA256 保持 `C8B7B706DC771BC4955131691EFABEB4137B056E1428BBF6301263112220CAFB`，`r8_il_inspector.csproj` 保持 `0AB60D5BB742EFA934D1C145A4B840DA8220ED8AC3522E8F81F10D40CC19E62A`。`source_revision_binding` 仍为空，`workflow_checkpoint_ref` 仍为 `null`。这些事实限制声明为一个 .NET repository task 的 explicit unresolved result，不证明通用 Coding Agent 完成。

### 5.4 当前明确不做

- 不返回 BHF Prompt、Golden、RAG 排序、EvidencePack、Store 或控制面；
- 不新建 Repair 框架、第二 Agent Runner、第二 Graph 或第二 Artifact；
- 不放宽“补丁必须产生真实替换”的确定性校验；
- 不增加无界模型调用、模型专属永久规则或人工补丁答案；
- 不以修复环境、增加测试、形成 checkpoint 或创建新运行编号声明 internal alpha 完成。

## 6. 污染隔离规则

### 6.1 必须隔离出通用 Runner 的领域特化

- `src/mod_agent/workflow/graph.py` 中直接检查 BetterHitFeedback 方法名和 correlation 文本的规则；
- `src/mod_agent/intelligent_evidence_only.py` 对 WallCrawler 的专用 post-run acceptance；
- `evidence-request` 和 `intelligent-evidence-request` 的 WallCrawler 默认值；
- `src/mod_agent/evidence/gtfo_r8.py` 和固定 `R8_IL_SYMBOLS`；
- Stagger/BetterHitFeedback 专用 Runtime、Edit Authority 和恢复逻辑。

这些内容并非都应删除。固定 R8、BHF 和 WallCrawler 路径可以保留为领域 Harness、确定性基线或校准 fixture；它们不得决定通用 actual discovery、通用 Runner 路由或公共结果语义。

### 6.2 当前应保留的完整性保护

- actual/expected 隔离；
- 当前来源 hash、MVID 和 metadata token；
- metadata 观察后才能读取对应 IL；
- `observed`、`inferred`、`unknown`；
- `support`、`conflict`、`missing`；
- EvidencePack commit/read 和严格回读；
- 未授权写入、Build、Runtime 的阻断；
- 运行内短 handle 到完整身份的确定性映射。

### 6.3 不应继续提升为持久规则的质量问题

- 重复的语义或 query；
- blocker/deferred 表述不理想；
- 模型输出啰嗦；
- 普通排序效果不佳；
- 单一模型在单一 Case 上的表达习惯。

这些进入运行报告和 Eval。只有它们会伪造事实、破坏引用、越权或改写持久 actual 时，才在工具前 fail-closed。

## 7. 跨工作树归并要求

当前 `rag_capability_mainline` 不是所有工作树的并集。以下非祖先 HEAD 必须在 v0 集成前完成语义核对：

| 提交 | 唯一内容 | 处理 |
| --- | --- | --- |
| `9bce437` | 29 文件的 controlled delivery 加固，涉及 CLI、Registry、Proposal、Apply、Ollama 和 `local_entry.py` | 高优先级逐文件比较；不直接整体合并 |
| `9a237b7` | RAG 目标文档变体 | 与当前目标文档逐节确认后标记被替代或移植缺失内容 |
| `c000021` | `AGENTS.md` 能力优先和合同复用变体 | 与当前规则核对语义等价性 |

归并结论必须使用 `adopt`、`already_present`、`superseded`、`domain_only` 或 `reject`，并绑定精确提交和文件；非祖先关系本身不证明代码缺失或缺陷。

## 8. 唯一实施顺序

Coding Agent v0 是上位产品里程碑，v0 internal alpha 是第一集成交付，RAG/ER 是内部证据子系统。它们不是并列项目。

```text
r8 repository objective explicit unresolved 已记录
→ BHF positive calibration explicit unresolved 已记录
→ WallCrawler 负向 actual 与 expected-side comparison 已完成，但 Case 对当前协议无效
→ 冻结 BHF/WC 结果的最小关系 Eval 已完成
→ Relation-aware Evidence/Trace/Eval 基础已形成确定性 checkpoint
→ Wall relation-aware run004 形成部分真实轨迹，但在 EvidencePack 前 Provider timeout，记录 explicit unresolved
→ 当前：选择 simple actual-only 真实任务并完成 Task/Case Reliability preflight
→ 一条 Build/Test 成功 + 一次 Failure → Different Repair → Revalidation
→ Internal Alpha completion checkpoint
→ RAG-1B：唯一公共入口采用同一 Evidence executor + Operational Readiness work
→ ENTRY-001/OPS-001/TOOL-001/REPORT-001/REC-001 全部关闭或形成验证边界
→ 才可运行或声明 Coding Agent v0 public alpha
→ 根据真实失败成熟化 Trace、Eval、Harness 和运行内 Memory
→ 多任务证据成立后再讨论长期 Memory、MCP 扩展、Skills 和子智能体
```

### 8.1 已完成的基础输入：可恢复集成基线

- 历史 WIP 已经经过多个窄 checkpoint 收敛；当前恢复基线为 §5 登记的 `6f6918772662715abaf726dfe8a331f5aee7407d`；
- 三个非祖先提交仍属于归并审计输入，但不阻塞当前 Repair→Revalidation；
- 不因恢复 checkpoint 声称产品阶段前进。

### 8.2 已冻结的校准输入：BHF EvidencePack 与方向评测

- BHF 已证明真实 local model/tool actual、source retrieval、metadata/IL、EvidencePack commit/read/strict rehydrate 与 expected-side comparison 路径可达；
- run002 与 run004 在不同 Search Plan/query 轨迹下均以 `max_model_steps=5`、3 次物理工具调用、第三 required lane 未执行和 `budget_exhausted` 结束，构成稳定失败模式，不是稳定成功；
- run004 committed EvidencePack hash 为 `b554e02190af1117b4b552072eea0404ae4271927b803619db9447c89764e9b1`，其 actual 为 `insufficient/block` 且没有 Hook identity；
- run004 只读 comparison 为 `sufficiency_matches=false`、`control_action_matches=false`、`acceptable_hook_identity_set_matches=false`、`forbidden_hook_identity_hits=[]`；BHF 决定性方向失败是 acceptable identity 缺失，而不是 sufficiency/control action 诊断值；
- 当前最终声明固定为 `failed_explicit_unresolved_for_current_model_and_strategy`。现有 leads 与调度检查了无关 `Enemies.EB_ChargedAttack_Pouncer.ActivateState`，没有形成可信 `Hitreact` 类型桥；
- 当前预算在理想 3 metadata + 1 relevant IL + 1 finish 路径下刚好可容纳，尚无物理证据支持扩大预算；
- 不再继续 BHF prompt、validator、correction、budget、provider、Dense 或稳定性重复运行。Dense provider 探索已以 `reject_dense_currently` 结束，不作为 BHF 方向补偿；详细决定绑定 `artifacts/retrieval_experiments/bge_m3_full_r8_ab_20260821_001/decision_record.json`，SHA256=`7404f84661f7fdc3051e9047b3c3ab8d83fce4772fa9c2686ad1ad29b2b688e7`；第一物理失败记录为同目录 `failure_record.json`，SHA256=`e8c69f52ddeb6cf9436520e34c7f9091820082c341a70224b6195d5cece3a860`；
- BHF 只评发现方向、当前物理身份、禁止方向规避和 expected-truth 隔离；`sufficiency` 与 `control_action` 保留为诊断，不作为 BHF 方向通过条件；
- BHF 的冻结 annotation 与 hash 不变，评分差异由版本化 Case 评分投影表达；
- BHF Hidden-Golden 不能授予 Patch 权限，也不作为 internal alpha 正向修改任务。

### 8.3 Repository 与 calibration explicit-unresolved 结果

- 当前任务详细事实只读 §5；repository objective 未通过，但合同要求的 explicit-failure 分支已形成可核验终止记录；
- 不再继续 r8 run、模型抽样、手工 Patch 修复或 Workflow/continuation 扩展；
- Coding Agent v0 internal alpha 仍未完成，不把平台 gate 正确拒绝无效动作提升为 supported-task success；
- WallCrawler run002 committed EvidencePack hash 为 `4588f5f5e357e00f788ec552af6960c0302aa3adb8ca48987956665077e2d704`，但只完成 2/4 required lanes，唯一 IL 是无关的 `CellMenu.CM_MapZoneGUIItem..ctor`，`verified_findings=[]`，并以 `budget_exhausted` 停止；
- generic comparison 的三项 match 不能把这个 incomplete budget stop 与 evidence-grounded block 区分；WallCrawler Case Reliability 为 `invalid_for_agent_evaluation_for_current_protocol`，Agent behavior 为 `inconclusive`；
- BHF 快速可靠性复检为 `valid_with_limitations`，不改变其 current-model/current-strategy explicit unresolved，也不重开 `OBS-001`；
- 详细审计与输入 hash 只记录在 `docs/audits/rag_1a_calibration_outcome_20260822_001/`；不自动重跑 WallCrawler、扩大 budget、修改 Golden 或启动 RAG-1B。

### 8.4 RAG-1A outcome checkpoint

- BHF committed actual 的方向结果为 fail，Case Reliability 为 `valid_with_limitations`；
- WallCrawler committed actual 不能形成负向能力结论，Case Reliability 为 `invalid_for_agent_evaluation_for_current_protocol`；
- 最小关系级 Eval 已把 lane coverage、required/missing relations、完整 Hook identity、禁止 identity、相关 IL 与 budget terminal 一并计入；
- RAG-1A outcome 为 `explicit_unresolved`，不是 pass；outcome report SHA256 为 `7EFC4F46CB41162585F56F21EF4CB48EA7E347CC676188935D7256C5F5FBA95B`；
- 当前没有已授权 actual-only 执行工作；Wall/BHF 路线均已冻结，下一步只选择一条 simple actual-only 真实任务并先完成独立 Task/Case Reliability preflight。

Relation-aware follow-up did not change the frozen old RAG-1A comparison. It
formed product-code checkpoints `dc93e39` for deterministic
Relation-to-Observation lineage, `a40a65c` for per-call Ollama admission, and
`8c5509e` for one bounded Requirement Projection correction with distinct
Attempt Trace. Four expected-isolated Wall attempts then established later
boundaries without reading expected data. Final run004 at run-level
`num_ctx=65536` made seven model-call attempts, accepted two model tool actions,
and entered the Tool/Observation control loop before the seventh Provider
response timed out after 180 seconds. No relation-aware EvidencePack or
comparison exists, so the result is
`explicit_unresolved_before_artifact_commit`, not a negative-capability verdict
or stability result. Wall context escalation, timeout tuning, Prompt changes,
provider/model switching, and additional Wall repeats are closed for the
current route. BHF remains `valid_with_limitations` plus current-model/current-
strategy explicit unresolved; it is not automatically rerun under the new
relation protocol.

### 8.5 工作包 4：RAG-1B 和 v0 public alpha

- 公共 `run-request` 委托同一 Agent Runner 和 Evidence executor；
- `evidence-request`、`intelligent-evidence-request` 只保留为明确的基线/诊断入口或退出；
- 旧入口不再直接建 Graph、写 Store、解释充分性或生成第二套结果；
- 公共输出保持 EvidencePack、Plan、Patch、Build/Test 和终态关联。

RAG-1B/public entry implementation 可以在 Internal Alpha completion 后继续，
但它本身不授权 Public Alpha 运行或声明。Public Alpha 之前必须形成独立的
Operational Readiness checkpoint：

- `ENTRY-001` 证明唯一公共产品入口委托同一 Runner、现有单一 StateGraph、
  ArtifactStore 与既有 Evidence/Plan/Patch/Review/Apply/Build/Repair owner；
- `OPS-001` 证明既有运行事实可以投影为可查询 lifecycle、heartbeat、stage/run
  deadlines、当前 owner、剩余预算和 terminal receipt；
- `TOOL-001` 证明 fresh execution context 可以从批准的 tool manifest 解析并
  验证 exact tool artifact，而不是猜路径或要求每个 checkout 包含 untracked bin；
- `REPORT-001` 证明 reporting failure 不会隐藏已提交的业务 Artifact；
- `REC-001` 证明最小 cancellation、checkpoint resume 与显式 fallback policy
  存在且不会静默切换 model/tool。

每项必须满足 `docs/audits/ENGINEERING_ISSUE_REGISTER.md` 中的
`minimum_acceptance`，并且 register status 为 `closed`，或由 Operational
Readiness checkpoint 明确记录 `mitigated_with_verified_boundary` 及其验证证据，
才可请求 Public Alpha 授权。Internal diagnostic functions 和兼容 CLI 不要求
删除；它们必须委托唯一 Runner，或明确标记为 non-product baseline/diagnostic，
且不拥有独立 Store、route 或 final-result authority。

这个 gate 不是 WallCrawler/RAG-1A 前置，也不是完整 Trace/Eval engineering
area、Kubernetes、OTel、Langfuse、模型网关或分布式恢复项目。本次只登记完成
门，不授权实现 Operational Readiness。

### 8.6 Internal alpha 之后的连续开发顺序

Internal alpha 没有把成熟 Coding Agent 所需能力从产品目标中删除。它只固定第一条不可替代的纵向证明，使后续能力拥有真实 Runner、工具观察、Artifact 和 Eval 数据作为输入，而不是在没有消费者时预建通用平台。

后续开发按依赖关系推进：

| 顺序 | 阶段 | 必须交付的能力 | 暂不在该阶段扩张 |
| ---: | --- | --- | --- |
| 1 | v0 internal alpha | 独立 actual-only 真实请求形成可信 EvidencePack；产生受限 Patch；隔离 Build/Test；一次真实失败 observation 改变下一动作并完成一次修复 | 用 BHF expected truth 补足实现依据、公共 API 稳定、多 Agent、长期 Memory、完整 Trace 平台 |
| 2 | RAG-1A 收口 | BHF 方向 actual、WallCrawler 负向 actual、Hidden-Golden、最小关系 Eval 和失败归因 | 把 BHF `sufficient/continue` 当作方向通过条件、Dense/RRF/rerank 默认化、完整评测平台 |
| 3 | RAG-1B 与 v0 public alpha | 一个公共入口、一个 Agent Runner、一个 Evidence executor；旧入口明确委托或退出 | 重新优化 RAG/ER、第二 Graph、第二结果语义 |
| 4 | Runtime 闭环 | Build 产物进入 GTFO Domain Harness；部署、进程、日志、标记、截图和恢复形成当前运行 observation | 用 Runtime Harness 决定通用 Agent 工程语义 |
| 5 | 端到端 Trace 与回归 Eval | 关联 request、工具动作、observation、Artifact、Plan、Patch、Build/Runtime、repair 和 final result；先用 3–5 个真实任务验证关联和失败分类 | 先建 Dashboard、OpenTelemetry 或全局 span 平台 |
| 6 | 任务与模型评价扩张 | 扩到 10 个真实任务，再形成 30–50 条标准化任务；固定硬件、Prompt/config、模型/量化/index 身份，比较质量、正确拒答、延迟、吞吐和内存 | 用单一 BHF、单次运行或社交媒体热度决定默认模型 |
| 7 | 工具面与工程泛化 | 根据真实任务增加仓库/语言/Build adapter；让模型在有界工具 Registry 中选择调查、编辑、测试和 Runtime 动作；MCP 只暴露同一 Runner 的工具和状态 | 一次性设计所有工具、让 MCP 成为第二产品 Agent |
| 8 | Skills 与运行内 Memory | Skills 提供过程知识；运行内 Memory 保存当前请求、已读文件、工具 observation、修改尝试和未解决问题 | 将 Skill 文本、Artifact 历史或 Golden 自动视为当前事实 |
| 9 | 长期 Memory | 只有多任务数据证明重复搜索、重复错误或项目约定反复丢失时，才保存可失效、可追溯、可删除的跨任务状态 | 提前保存 Hook 答案、旧输出、临时协议结论或未经验证的推断 |
| 10 | 子智能体、并发与长期自治 | 单 Agent 闭环和 Eval 稳定后，再实现任务分解、owner、结果合并、预算、并发隔离、恢复和停止条件 | 用多 Agent 数量替代单 Agent 的 observation-driven 能力 |
| 11 | 生产成熟化 | 权限、沙箱、恢复、并发、保留策略、服务化、监控和运维基于前述真实运行数据加固 | 因“未来可能需要”恢复大型控制面先行路线 |

该顺序表示默认依赖，不要求把每项能力建设成独立平台。若真实消费者证明某一后续能力必须提前，允许形成有界工作包，但必须绑定具体运行失败、现有消费者和可验证完成门。

现有文档覆盖关系如下：

- `docs/ENGINEERING_RAG_EVIDENCE_INTELLIGENCE_TARGET_DRAFT.md` 负责 RAG-1A、RAG-1B、最小 Eval、Trace/Eval 边界及能力优先原则；
- `docs/LOCAL_MODEL_COMPARATIVE_EVALUATION_EXPERIMENT.md` 负责 30–50 条标准化 Prompt、模型身份、量化、质量、延迟、吞吐和内存的正式评价协议；
- `DEV_SPEC.md` 负责 Planning、Patch、Review、Apply、Build、Runtime、repair、权限和恢复的父产品边界；
- `EVIDENCE_RAG_MCP_SPEC.md` 的 0–3 节负责当前 RAG/MCP 子系统规则，后续导入蓝图只作参考；
- 本文负责把这些能力放入同一 Coding Agent 产品的当前开发顺序。

当前没有一份已批准的独立文档完整拥有长期 Memory、Skills、子智能体、并发和长期自治的实施合同。本节只登记它们的进入条件和顺序；只有前序真实数据成立并选择对应工作时，才编写有界专项设计，不从历史蓝图直接恢复通用框架。

### 8.7 时间盒与不可降级核心

时间盒限制单轮投入和修改范围，不降低阶段完成门。时间盒结束而真实门未满足时，状态必须是 `incomplete`，不得把剩余 Agent 行为移动到后续阶段后再宣称当前阶段完成。

v0 internal alpha 至少必须证明一次：

```text
真实自然语言请求
→ 当前环境 observation
→ 可信 EvidencePack
→ 受限 Implementation Plan 和 Patch
→ 隔离 Build/Test
→ 真实失败 observation 改变后续语义动作
→ 与第一次不同的受限修复
→ 再次验证
```

以下结果不能单独替代该证明：

- 只形成 EvidencePack 或 Planning block；
- 只跑固定 Workflow 节点；
- 单元测试证明某条分支存在，但没有真实纵向运行；
- Build/Test 失败后机械重复同一动作；
- 新增 Schema、validator、错误码、测试数量、Trace 字段或文档；
- 用 BHF 单例成功声明通用 Coding Agent、模型优劣或生产成熟度。

后续能力同样不得因时间盒被删除。若它们尚未达到各自完成门，应保留为明确的后续产品能力，不得用 `deferred` 表述成永久非目标。

### 8.8 Coding Agent 核心定义与 internal alpha 范围

Coding Agent v0 的产品定义不是“调用若干工具并产生 EvidencePack”，而是接收一个真实 issue，在当前受控工作区中定位并阅读相关代码，形成受限修改，运行客观 Build/Test，并根据真实失败 observation 改变下一步，直到支持范围内的任务通过或达到明确停止条件：

```text
Issue / 自然语言请求
→ 定位当前仓库、相关文件、符号和引用
→ 阅读真实代码与已有测试
→ 使用 RAG/ER 补充当前工程事实
→ 形成受限 Implementation Plan 和 PatchProposal
→ Review / Dry-run
→ 沙箱内 Apply
→ 隔离 Build/Test
→ 读取失败 observation
→ 形成与首次不同的受限修复
→ 再次 Build/Test
→ 通过或明确停止
```

文件、符号和修改位置必须来自当前工作区观察、工具结果和已提交 EvidencePack，不得由 Golden、annotation、历史 Patch、预填 Hook 或手工指定最终答案注入。RAG/ER 是这条产品链中的工程证据工具，不是上位产品本身。

#### 8.8.1 Agent 与 Workflow 的最小证明

Workflow、Graph 和控制层可以固定工具准入、权限、预算、沙箱、副作用、持久化、恢复和验证命令；它们不得预先决定需要读取哪个业务文件、选择哪个工程方法、产生何种修改或在 Build/Test 失败后采用哪个修复方向。

internal alpha 必须保存至少一组可比较的动作事实，证明新的 observation 改变了后续语义动作：

```text
first_action
+ build_or_test_observation
→ second_action
```

仅按固定节点执行 `Search → Patch → Build → End`、只改变内部 identity、或者由 Workflow 写死修复内容，均不能证明 Agent 行为成立。

#### 8.8.2 客观完成事实

internal alpha 的完成判断优先使用确定性工程结果，不由模型自评。现有运行报告、Artifact 和 Trace 事实至少应能够表达：

```yaml
issue_ref:
workspace_and_revision:
files_and_symbols_read:
patch_ref:
modified_files:
build_exit_code:
tests_passed:
scope_violations:
first_failure_stage:
failure_observation_refs:
repair_changed_action:
revalidation_result:
final_result:
```

这些是运行事实要求，不授权新增 Trace 平台、Artifact 类型或第二结果 owner。能够从现有 Artifact、Build/Test 输出和运行报告重建的字段不得重复持久化。

证据不足时正确阻止 Patch 是必要的负向能力，但不能替代正向完成门。internal alpha 至少需要一条受支持任务最终 Build/Test 通过，并需要一次真实失败 observation 导致不同修复且完成再次验证。如果首条任务首次即通过，不得人为破坏它制造失败；应使用另一条真实、可复现的失败任务验证 Repair。

#### 8.8.3 最小 Eval 与成熟 Eval 的边界

internal alpha 从第一条纵向运行开始记录最小评测事实，但不以完整 Eval 平台为前置：

| 范围 | internal alpha 要求 | 后续成熟化 |
| --- | --- | --- |
| 最终结果 | Build/Test 是否通过、是否越界修改、最终结果 | 多任务成功率与回归质量门 |
| 轨迹事实 | 文件读取、工具序列、失败位置、修复是否改变 | 轨迹部分分、合理替代路径和系统化错误分析 |
| 单步调试 | 首次文件定位、工具选择和 Repair 方向 | 标准化单步数据集和 held-out 评测 |
| 稳定性 | 保存可重复运行所需身份 | 同任务重复运行和波动区间 |
| 成本 | 记录模型调用、工具调用、Token 和 elapsed | 每成功任务成本、p50/p95 和容量规划 |

30–50 条标准化任务、SWE-bench 子集、正式模型排名、重复运行统计、完整轨迹评分、Dashboard 和 CI 质量门均不阻塞 internal alpha；它们在首条正向闭环和 3–5 条真实任务后进入。

#### 8.8.4 工程贡献与模型贡献分离

internal alpha 不根据单次 Qwen、Phi 或其他模型运行决定模型优劣。每条运行应固定并记录：

```yaml
model_digest_and_quantization:
prompt_identity:
agent_harness_revision:
tool_surface:
workspace_and_source_identity:
sandbox_and_permission_profile:
temperature_seed_and_budgets:
build_test_environment:
```

这些身份用于后续在相同 Harness、任务和硬件下分离模型差异与工程脚手架差异。正式模型选择仍由标准化任务、重复运行、质量、吞吐、延迟、内存和成本数据决定；单次 BHF 或单一步骤结果只用于失败定位。

## 9. 完成门

### 9.1 v0 internal alpha

```yaml
request_and_workspace:
  natural_language_issue: true
  actual_product_goal_bound: true
  objective_success_command_bound: true
  current_workspace_revision_bound: true
  relevant_files_located_from_observation: true
  relevant_symbols_and_references_read: true
  no_prefilled_target_or_patch_answer: true
evidence:
  committed_actual_only_task_pack: true
  strict_rehydrate: true
  bhf_direction_calibration_is_not_patch_authority: true
planning:
  consumes_committed_pack: true
patch:
  bounded_proposal_and_dry_run: true
  sandboxed_apply: true
  scope_violations: 0
build_test:
  isolated_execution: true
  one_supported_task_passed: true
agent_behavior:
  observation_changes_next_action: true
  one_repair_attempt_verified: true
  repair_revalidation_passed: true
trace_eval:
  run_local_fact_chain_recorded: true
  product_stage_progress_recorded: true
  objective_result_recorded: true
  model_prompt_harness_tool_source_identity_recorded: true
  no_full_platform_required: true
```

### 9.2 RAG-1A

- BHF 方向 actual 已提交并按 Case 评分投影完成 expected-truth 隔离比较；
- WallCrawler 负向 actual 已提交并识别关键行为缺失；
- actual 冻结前不读取 annotation、历史实现或旧输出；
- 失败可以归因到 retrieval、selection、metadata、IL、reasoning 或 planning；
- 没有 BHF/WC 固定答案进入通用 discovery。

### 9.3 v0 public alpha

- 一个公共入口；
- 一个 Agent Runner；
- 一个 Evidence executor；
- Workflow 不拥有工程语义；
- Domain Harness 不污染通用 Runner；
- Build/Test observation 可以改变下一动作；
- 重复入口有明确委托或退出状态。

## 10. 时间盒

从 2026-08-17 当前同步点开始，在本地模型和 Build 环境持续可用的前提下，剩余目标为 5–7 个集中工程日：

| 天数 | 交付 |
| --- | --- |
| 1 | 修复现有 Repair Patch owner，完成第二次 Apply/Build/Test 或保存新的第一物理失败 |
| 2 | 受控 actual-only 任务 checkpoint；使用现有仓库真实小型 Issue 复核定位、Patch 和 Build/Test |
| 3 | 最小失败闭环工程加速验证；同步当前产品状态与运行事实 |
| 4 | BHF 方向 Hidden-Golden、WallCrawler 负向 actual 和最小关系 Eval，关闭 RAG-1A |
| 5 | RAG-1B 公共采用、重复入口收缩和 v0 public alpha |
| 6–7 | 全链回归、3–5 个真实任务最小 Eval、文档和 checkpoint 收口 |

该时间盒不是完成承诺。若真实来源、模型或 Build 环境阻断，应返回第一物理失败，不以新增合同或测试数量伪装进度。

## 11. 附录：Markdown 文档审计归类

本轮共检查 44 个 Markdown 文件，按职责归类如下。

### 11.1 当前权威与状态链

- `AGENTS.md`
- `docs/ACTIVE_PRODUCT_CONTRACT.md`
- `docs/PROJECT_STATE.md`
- `docs/IMPLEMENTATION_QUEUE.md`
- `docs/SPEC_COVERAGE_MATRIX.md`
- `docs/ARCHITECTURE_OVERVIEW.md`
- `DEV_SPEC.md`
- `EVIDENCE_RAG_MCP_SPEC.md`

`DEV_SPEC.md` 和 `EVIDENCE_RAG_MCP_SPEC.md` 含大量历史阶段与导入材料，只能按 `AGENTS.md` 的读取顺序读取当前相关段落，不能整体解释为当前队列。

### 11.2 当前能力目标与实验文档

- `docs/ENGINEERING_RAG_EVIDENCE_INTELLIGENCE_TARGET_DRAFT.md`
- `docs/CODING_AGENT_V0_INTERNAL_ALPHA.md`
- `docs/RETRIEVAL_ARCHITECTURE_DECISIONS.md`
- `docs/RETRIEVAL_VALIDATION_PLAN.md`
- `docs/LOCAL_MODEL_COMPARATIVE_EVALUATION_EXPERIMENT.md`
- `evaluation/directional/v2_ret_directional_001_decision.md`

本地模型实验文档当前未跟踪，正式模型排名尚未开始；两模型局部诊断不能升级为默认模型结论。

### 11.3 历史、审计与控制设计

- `docs/CONTROL_PLANE_CONSOLIDATION_DESIGN.md`
- `docs/audits/AGENT_HARNESS_TRANSITION.md`
- `docs/audits/LOOP_HISTORY.md`
- `docs/audits/V2_MAINLINE_TRANSITION.md`
- `docs/GIT_WORKFLOW.md`

这些文件提供历史事实、设计或流程，不自动创建当前工作。

### 11.4 Calibration derived presentation

- `docs/calibration/two_slice_data_readiness/better_hit_feedback/leakage_audit.md`
- `docs/calibration/two_slice_data_readiness/better_hit_feedback/source_coverage.md`
- `docs/calibration/two_slice_data_readiness/wall_crawler/leakage_audit.md`
- `docs/calibration/two_slice_data_readiness/wall_crawler/source_coverage.md`
- `docs/calibration/two_slice_data_readiness/reproducibility_report.md`

这些文件明确是非权威派生展示。Golden expected 与 actual 运行继续隔离。

### 11.5 Skills 与参考材料

- `.agents/skills/hook-discovery-playbook/SKILL.md`
- `.agents/skills/mod-delivery-playbook/SKILL.md`
- `.agents/skills/mod-planning-brief-playbook/SKILL.md`
- `.agents/skills/runtime-diagnosis-playbook/SKILL.md`
- `.agents/skills/qa-tester/SKILL.md` 及 reference
- `.agents/skills/resume-writer/SKILL.md` 及 reference
- `.agents/skills/skill-creator/SKILL.md` 及 reference
- `.agents/skills/auto-coder/references/01-overview.md` 至 `07-future.md`

`auto-coder/SKILL.md` 已冻结为 `SKILL.md.frozen`。Skills 只提供过程知识，不进入 runtime prompt、产品状态、EvidencePack 或工具权限。

### 11.6 其他说明

- `README.md`
- `tests/fixtures/sample_documents/README.md`

README 是用户入口说明；fixture README 只描述测试数据。两者不拥有当前产品完成状态。

## 12. 禁止声明

在完成对应真实门之前，不得声明：

- `rag_capability_mainline` 已包含所有工作树代码；
- RAG-1A、RAG-1B 或 Coding Agent v0 已完成；
- BHF 已自动发现正确 Hook；
- 两模型诊断已经完成模型选型；
- workflow trace 等于端到端 Agent Trace；
- Domain Harness 等于 Agent Harness；
- 当前大量测试通过等于真实纵向产品闭环成立。
