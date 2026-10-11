# 十天工程成熟度战略决策记录与全覆盖账本（待审核草案）

```yaml
document_status: draft_for_user_review
document_role: strategic_decision_record_and_traceability_ledger
daily_execution_authority: none
implementation_authorization: not_granted
product_claim_authority: none
as_of: 2026-09-02
engineering_baseline_head: d263ed983c3cede7165273e0158e4641c4dbeaaf
primary_outcome: evidence_grounded_coding_agent_v0_portfolio_delivery
timebox: ten_working_days
operational_plan: docs/TEN_DAY_EXECUTION_PLAN_DRAFT.md
update_policy: only_when_scope_goal_or_disposition_changes
```

> 本文是对三个外部 `.txt`、当前聊天计划、权威合同和现有 WIP 的统一改版建议。
> 它在用户审核前不进入 `ACTIVE_PRODUCT_CONTRACT`、`IMPLEMENTATION_QUEUE` 或产品执行队列。
> 三个 `.txt` 与聊天计划定义目标和成熟度；仓库 `.md` 只补充当前工程现实、权限边界和已实现事实，不支配新计划。
> 本文不改写现有四份用户 WIP，也不把历史测试、设计或单次运行提升为当前产品成功。
> 本文负责完整记录为什么保留、改变、新增、舍弃或延期，不作为每日执行手册，不在每天或每个 checkpoint 更新。
> 日常执行只读取 `docs/TEN_DAY_EXECUTION_PLAN_DRAFT.md` 和当日 bounded task packet；需要解释取舍时才回查本文。

## 1. 直接裁决

十天内可以争取完成的是：

> 一个可投递简历、可现场演示、证据边界诚实的 Coding Agent v0 internal alpha，并在条件满足时形成窄范围 public alpha。

十天内不能诚实承诺的是：

- 覆盖任意仓库、任意语言、任意模型和任意运行环境的企业生产系统；
- 40～200 条完整长期评测、三模型正式排名和量化研究全部完成；
- 工业级全格式 PDF、完整 OCR、多模态、SFT/LoRA/DPO、长期 Memory、完整 Dashboard 和多租户部署同时上线；
- 自动模型切换、全局熔断、任意节点持久执行、跨主机 exactly-once 或零人工运维；
- 用测试数量、Trace 页面、同一 SHA 或局部 CI 代替产品成功。

DeepSeek 与 GPT Pro 对原混合计划的批判触发一个待用户审核的目标分层改版。原九项目标和三个 txt 的完整成熟要求没有删除，但不再自动等同于十天 Core 承诺：

1. **Fallback**：只保证诚实保存已有进展与 unresolved，不冒充目标完成；
2. **Core target**：一个真实代码任务完成 objective 和 acceptance-required verification，另有正确停止、最小 RAG/ER Eval、单向 Trace、固定环境、远端 CI 和可复现作品包；
3. **Full-maturity Stretch**：在 Core 之上完成真实 Different Repair→Revalidation、更广 Eval、九项目标和条件 public alpha。

十天结束必须区分三个结果，不能把诚实报告等同于目标达成：

| 结果 | 含义 |
| --- | --- |
| `ten_day_full_maturity_stretch_met` | objective、changed-product Build/Test、Different Repair→Revalidation、所需 Runtime、完整十天 Eval、环境/CI 和发布证据全部达到原成熟硬门 |
| `ten_day_core_target_met` | 一个真实 Issue 的 Build/Test、objective、所需 acceptance、正确停止、最小 Eval、Trace、环境/CI 和作品包成立；不声称 Repair/public alpha 已证明 |
| `honest_degraded_portfolio_delivery` | 保存了可复现成果与精确 unresolved，但一个或多个硬门未完成；可以形成诚实作品材料，不能宣称达到同等级十天成熟目标 |

该分层改变了 Repair 在十天承诺中的硬度，当前仅是待用户裁决的计划修订；在用户选择 Core 或 Full-maturity 前，不自动改变权威合同和九项目标。

这意味着“全覆盖”解释为：每项原料都有明确的完成、改写、条件化、延期或拒绝裁决；不是把所有技术名词都塞进十天实现。

### 1.1 执行风格：副作用严格，能力推进积极

当前慢点的一部分来自流程性过度保守：长控制文档、历史事实和禁止项进入每轮上下文后，Codex 容易反复审核权限、复述边界和扩写 validator，而不是让真实运行前进一层。

新版采用双层策略：

| 必须 fail-closed | 默认积极推进 |
| --- | --- |
| 外部数据披露、secret、用户 WIP、exact-diff approval、Apply、Build/Runtime 权限、actual/expected 隔离、source/Artifact identity、证据主张越级 | 已授权仓库路径内的正常编辑、聚焦测试、只读检索、临时 receipt、一个 owner 的 first-failure 修复、同一工作包内必要的机械验证 |

只有左栏失败可以阻断产品阶段。Hook、宏观投影、可选 telemetry、文档同步、coverage 报告、额外模型比较或发布润色失败时，应记录并继续主能力；不得把开发辅助工具提升为新的产品 gate。

这份 700 行以上的计划只用于审核和追踪，不进入每日默认上下文。每天只渲染 800～1500 tokens 的执行包，正向写明：

```text
task_id
goal
base_sha
current_head
source_identity
profile
authorized_actions
read_first
write_allowlist
protected_paths
current_first_failure
next_capability_stage
verification_commands
done_when
stop_when
rollback
unknowns
out_of_scope
```

其中 `authorized_actions` 与 `next_capability_stage` 必须和禁止项同等显眼。已在包内授权的普通仓库编辑、聚焦测试和只读检查不反复请求确认。

### 1.2 宽认知、窄权限

限制应作用于副作用、事实持久化和对外主张，不应把模型的工程推理压成固定表单。

模型在授权工作包内可以主动：

- 提出多个根因假设和技术方案；
- 选择下一条只读调查路线，并在 observation 后改变原计划；
- 并行派出少量只读 explorer 分别检查源码、测试、日志、文档或外部资料；
- 比较方案的能力、信息损失、故障边界、成本和可逆性；
- 先做小实验再决定 owner，而不要求第一次工具调用前描述完整实现拓扑；
- 将表达质量、普通 query、排序和冗余问题记入 Eval，而不是为每个模型失误增加永久 schema；
- 在没有足够事实时提出明确 hypothesis/unknown，但不能把它持久化成 owner fact。

确定性代码只接管必须精确的部分：

- path/hash/span/MVID/token 和跨对象 identity；
- 工具参数展开、预算和副作用；
- authority、approval、Artifact commit/readback 和新鲜度；
- Build/Runtime 物理结果；
- 对外 claim 的证据范围。

执行模式因此改为：

```text
自由形成工程假设
→ 有界只读调查
→ 获得真实 observation
→ 模型重新判断方向
→ 确定性层校验身份与权限
→ 一个 writer 执行最小可逆修改
→ 真实验证
```

不要求内部推理全部结构化或持久化。只有交给工具、跨页面 handoff、进入 Artifact、触发副作用或形成发布声明的边界才要求稳定结构。ReAct 可作为 specialist 内的有界调查策略，但不替代顶层 LangGraph 和人工权限。

### 1.3 计划采纳门

本文当前明确没有执行授权。Day 1 开始前必须由用户审核并明确：

1. 是否采纳“internal alpha 硬目标、public alpha 条件化”的十天定义；
2. 第一真实任务是否继续采用当前 `ACTIVE_PRODUCT_CONTRACT` 选择的 `ACCURATE-CROSSHAIR-SPREAD-TOGGLE-001`，还是显式改选另一条 actual-only任务；
3. 该任务的 objective success command、expected objective result、acceptance、Runtime/Eval applicability；
4. Fresh 所需的 source/profile、本地模型身份、调用和时间预算；
5. 是否授权一次新的 Fresh preflight/model run，并以新决定显式取代旧合同中“不得创建新 fresh preflight/Actual”的冻结状态；
6. 第二个真实 Repair Case 必须已经有当前可复现的真实失败 checkpoint，冻结前序 Artifacts/source/acceptance/authority/objective command，且无预填 Repair 答案、不是人工注入故障；若没有这样的 Case，Full-maturity Stretch 不具备资格，但 Core 不制造失败；
7. 最晚 Day 5 前是否能够提供游戏启动、目标目录写入、观察和恢复授权窗口。

`CODING_AGENT_V0_INTERNAL_ALPHA.md` 中旧 r8 inspector 快照、RAG WIP 中旧 BHF next step 和当前 Active Contract 的 AccurateCrosshair 不能同时作为 active task。采纳时只选一个真实任务，其余作为历史/校准输入。

### 1.4 Codex 工程自主权与产品执行权限分离

本仓库开发存在两个不同权限面，不能再混用：

| 权限面 | 默认方式 |
| --- | --- |
| 产品 Agent 对目标 Mod/外部源码的 Evidence→Patch→Apply→Build→Runtime | 继续受 Evidence、Binding、human approval、外部披露、Build/Runtime 和 acceptance 严格约束 |
| Codex 对本平台仓库的用户授权开发 | 工作包一经批准，Codex 在 write allowlist 内连续完成读取、实现、测试、修正、复核和约定的 checkpoint，不套用 Mod Apply Artifact 审批链 |

一个批准的 Codex 工程工作包默认授权：

- 读取完成该目标所需的当前源码、聚焦测试、配置、日志和精确合同；
- 在明确 write allowlist 内编辑平台代码、测试和必要的短文档；
- 自主选择技术实现细节，只要不改变用户批准的产品目标、证据门和权限边界；
- 运行 focused test、Ruff、compile/check 和一次相关 checkpoint；
- 失败后定位 owner、修改、使用 last-failed/聚焦验证并继续，直到 `done_when` 或 `stop_when`；
- 启动少量只读 explorer、测试或审查子智能体，并由唯一 writer 统一集成；
- 对明显局部、可逆且不改变产品方向的问题直接做小实验，不先向用户申请技术细节决定；
- 工作包明确要求 Git checkpoint 时，在验证通过后形成只包含批准范围的提交。

只有下列情况需要重新请求用户决定：

- 目标、实际任务、acceptance 或 write scope 实质扩大；
- 需要发送新的本地数据类别到外部模型/服务；
- destructive、不可恢复或范围不清的文件/Git 操作；
- 产品目标源码 exact-diff approval、游戏启动、游戏目录写入或真实 Runtime；
- 需要替换已选任务、降低完成门或改变用户可见产品行为；
- 同一 first failure 经一次通用修复仍未消失，需要重新选择表示、架构或模型/profile。

以下不再作为 Codex 日常停止理由：

- 可选宏观投影、Hook analytics、release renderer 或文档同步暂时不可用；
- 历史控制文档尚未复制本轮全部测试叙事；
- 普通技术方案存在多个可逆选择；
- 一个非权威辅助摘要或状态页过期；
- 尚未运行与当前修改无关的全仓测试、模型或 Runtime。

Hook 和工程认知工具的职责是扩大 Codex 的有效自主区间：自动提供当前允许动作、有效验证和 stale 事实，使 Codex少重读、少询问、少重跑。它们不是新的审批员。

## 2. 输入与优先级

### 2.1 目标与成熟度输入

1. `C:/Users/10160/Desktop/rag_如何保证内容准确性.txt`
   - 文档输入质量、PDF 页面级处理、引用与可追溯；
   - Retrieve、IsREL、IsSUP、IsUSE 四类质量问题；
   - 检索、生成、评估、修正或拒答；
   - 内容噪声与检索噪声分离；
   - RAGAS 只作为适用指标来源，不自动成为唯一判断器。
2. `C:/Users/10160/Desktop/项目回头自检.txt`
   - 生产级 RAG、完全离线本地模型、可观测性、微调、实时多模态、可靠 Agent 六类竞争力原料；
   - Golden Case、分层 Eval、CI、性能、成本、稳定性、失败归因、状态恢复、人工审批、沙箱与安全；
   - 工作流与 Agent 的选择边界，以及工具和上下文质量的重要性。
3. `C:/Users/10160/Desktop/项目自检-8月17.txt`
   - 确定性错误、瞬时技术故障、持续故障和长期不可用的分类；
   - 超时、总预算、有界重试、退避、抖动、熔断、降级、转人工；
   - 模型技术可用性与业务有效性分离；
   - 备用模型预验证、能力下降时同步降权；
   - 恢复时不得重放已经完成的副作用，恢复后必须重新探测业务质量。

源文件冻结身份：

| 来源 | SHA256 |
| --- | --- |
| `rag_如何保证内容准确性.txt` | `41A3AAD1921CA7F9CC93B48353FAC2DB868E1329D310A078273BC79314B6325E` |
| `项目回头自检.txt` | `D9394F397F6AFDBEB3AD800EE1197FB18E9554D0E270D857661B2113500BA339` |
| `项目自检-8月17.txt` | `AD08AB37D92FC3ADF63CA2F9FE146E1A1676AEA8FEC761AE96FA4A5A8994056F` |

关键聊天附件冻结身份：

| 主题 | 附件目录 | SHA256 |
| --- | --- | --- |
| Hook/dev-loop/环境自动化 | `0849918b-3fc6-493f-83fa-587b2c6f95b1` | `52123630DF76830FFCB5376E7B1A59D5D88597DCC3B177AD774FBB56CEB62277` |
| 工程读模型与十天路线 | `3af36ac3-19c3-4dc0-9019-358ab8b67054` | `BAB0823C76215EA3FC64E67B8F97D4E31E3554AE71AE6E0C7C82A2CA69DE1128` |
| project-intel 与中心层提案 | `0cc8fd69-59e5-4b03-b10d-0640a1e8a393` | `52C9E796760AAB58E2AD3A711250C62482B91743992188E9623007517DE45612` |
| Codex 官方方式与隐形逻辑 | `bf95be4f-2128-4574-8d92-89ef84710196` | `4B107C332CED02E10927CF09716B7A6CF371E1FDBD24BF101B0A5C7CAA478EAD` |
| 证据语义旧概念交接 | `60681319-c2f0-48ce-b64e-80c9c3367ab9` | `EB5B42F5A59A357497FFEDE31486DE983A97ED55B87E49A45EB1E14C48FF9209` |
| GPT Pro 对原混合计划的批判 | `73a9d8a2-e645-4311-929a-420a39db58a0` | `662C07469BBE90123634B7A9F17339545CA8F3C5EFB265079E40635C5D594DBA` |

这些哈希证明本次映射使用的输入版本，不把聊天建议提升为产品 authority。DeepSeek 批判来自当前对话原文，没有独立附件哈希；它只触发计划职能拆分，不成为工程事实。

### 2.2 必须合并的聊天计划

- P0 产品：修复 Findings `relation_index` 第一失败；
- P0 提速：建立并真实验收 `fresh-coverage` CLI；
- P1：`bounded-task-handoff` Skill；
- P1：PreCompact + SessionStart 最小上下文 Hook；
- P2：依赖锁、Local Environment、最小 CI；
- Day 9–10：`release-evidence-packager`；
- 精简 `AGENTS.md` 和动态状态入口；
- Codex 只读审核、单写者实现、机械验证三类运行方式；
- 仅 Ruff 的快速 pre-commit；
- 两到三个真实工作包后再裁决 `dev-check` CLI；
- branch coverage 先报告、后裁决阈值；
- `/goal` 只承载一个可验证工作包，不包揽整条人工审批链；
- 子智能体优先承担独立只读调查、测试、日志和审查；同一 checkout 只有一个 writer；
- Worktree 只隔离写入，不解决产品语义与共享服务冲突；
- 宏观审核功能必须保留，但复用现有 Projection V2，避免第二数据库和第二 LangGraph；
- 证据语义必须区分身份、主张范围、新鲜度、消费权限，以及 `declared/configured/observed/verified`；
- 旧 Skill、错误路由、重复 Skill 名称和无效路径需要清理；
- 不用工具建设替代九项目标和五项真实产品证据。

### 2.3 工程现实输入

下列文件只用于修正当前事实，不让旧排程覆盖新计划：

- `docs/ACTIVE_PRODUCT_CONTRACT.md`：当前权限、产品选择和真实失败；
- `docs/PROJECT_STATE.md`：当前状态摘要，但其更新时间早于今天提交；
- `docs/CODING_AGENT_V0_INTERNAL_ALPHA.md`：九项工作包语义和完成门；
- `docs/ARCHITECTURE_OVERVIEW.md` WIP：单一 LangGraph、Artifact、Projection 和条件触发边界；
- `docs/ENGINEERING_RAG_EVIDENCE_INTELLIGENCE_TARGET_DRAFT.md` WIP：标准 RAG + ER 双路径、RAG-1A/RAG-1B 和 Eval 边界；
- `docs/SPEC_COVERAGE_MATRIX.md` WIP：覆盖状态，但其中部分 HEAD/状态已过时；
- `docs/LOCAL_MODEL_COMPARATIVE_EVALUATION_EXPERIMENT.md` WIP：本地模型 Level 0–3 升级门。

当前现实基线：

- HEAD 为 `d263ed983c3cede7165273e0158e4641c4dbeaaf`；
- `relation_index` 确定性修复、Fresh CLI、两个 Skill、Context Hook、`uv.lock` 和最小 CI 已提交并有自动测试；
- 当前 20 文件 internal-alpha checkpoint 本地结果为 `889 passed`，但不是 full unit suite；
- 当前分支没有 upstream，尚无远端 GitHub Actions 成功记录；
- Local Environment setup 脚本存在，但 Desktop 绑定尚未证明；
- Hook 代码存在，但 `/hooks` 信任和真实 PreCompact→SessionStart 未证明；
- 新 Fresh CLI 尚无真实本地模型成功 receipt；
- 27B Patch 配置已有两次 600 秒无完整响应；不能再盲目重复；
- 4B Patch 探测技术上返回，但业务语义和 edit binding 未通过；不能作为已验证备用模型；
- AccurateCrosshair 现有 preflight 在 `docs/audits/ACCURATE_CROSSHAIR_SPREAD_TOGGLE_PREFLIGHT_20260824.json` 明确记录 `gameplay_runtime_required_for_delivery: true`；
- 当前真实产品仍缺 changed-product Build/Test 成功和 Failure→Different Repair→Revalidation；
- Projection V2、Rebuild、Thin Lineage 和 Langfuse exporter 已有基础，不应再造事实微内核；
- 现有四份文档 WIP 必须保留，不能被十天实施误提交或覆盖。
- full unit suite 当前不能声称全绿；20 文件/889 项 checkpoint 的精确范围必须随 CI 和简历证据保留；
- 发布脚本入口与实际测试入口存在历史不一致，只有 public/MCP 采用进入关键路径时才修正，不用入口占位状态冒充部署成功。

### 2.4 OpenAI Docs 对 Codex 工作面的约束

本计划保留此前官方资料核对的结论：

- [`AGENTS.md`](https://learn.chatgpt.com/docs/agent-configuration/agents-md) 只保存稳定、跨任务成立的规则；动态状态使用短查询或 receipt，不继续堆入根指令；
- [Skills](https://learn.chatgpt.com/docs/build-skills) 聚焦一个重复工作，按需加载；不能把项目状态、产品 truth 和多个生命周期动作塞进一个 Skill；
- [Hooks](https://learn.chatgpt.com/docs/hooks) 只负责生命周期机械触发、记录、失效和轻量检查；必须受信任且避免多个 Hook 并发写同一状态；
- [Local Environment](https://learn.chatgpt.com/docs/environments/local-environment) 负责新 worktree 环境准备，SessionStart 只做快速 doctor，不在每次恢复时重新安装；
- [Worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees) 隔离独立 writer；ignored 文件只有明确纳入 `.worktreeinclude` 才随受管 worktree 复制；
- [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents) 优先用于读密集调查、测试、日志和审查；并行写必须路径与状态 owner 独立；
- [`/goal`](https://learn.chatgpt.com/docs/long-running-work) 只推进 outcome、constraints 和 verification 清楚的单一结果；不会扩大模型、写入、Build、Runtime 或人工审批权限。

### 2.5 聊天中的工程认知与 Hook 计划逐项裁决

#### 工程认知投影

此前提出的 `inventory/flow/impact/health/context/evidence` 六类需求全部保留，但改变实现顺序和权威关系：

```text
Git / source / registries / owner Artifacts / tests / real receipts
                              ↓
                    只读事实关联与新鲜度
                              ↓
          inventory / flow / context / evidence / macro review
                              ↓
                   handoff / Hook / release renderer
```

Fresh、CI、Review、Build、Runtime 不依赖投影才能运行；它们先产生 owner receipt，投影随后读取。CI 只能由明确 lint、test、contract 和架构规则阻断，不能由综合 `health` 判断阻断。

| 原建议 | 十天裁决 |
| --- | --- |
| `inventory` | 十天只覆盖当前关键 route；全仓 inventory 移到 Day 11+，模块边界不由目录数量猜测 |
| `flow` | 同时显示 `declared/configured/observed/verified`；声明边不冒充执行边 |
| `context` | 快速读取 HEAD、dirty、task packet、owner receipt、有效/失效验证和 next action |
| `evidence` | 保留 owner ref、scope、freshness、limitations；不重算 first failure/readiness |
| `health` | 改成 profile×capability×evidence×freshness 矩阵，不生成综合分 |
| `impact` | Day 11+ 才评估；输出必须区分 `proven/possible/unknown`，不能把静态引用升级为必跑测试或无影响证明 |
| Capability Profile Registry | 只登记现有真实 profile 的语义、预期阶段和合法失败；不成为新执行 owner |
| 增量影响索引 | 两到三个工作包仍证明全量扫描是主要瓶颈后再做 |
| checkout writer lease | 十天先用单 writer + worktree 规则；只有真实并发冲突再实现持久租约 |

共同事实关联至少需要表达 HEAD/source、run/profile、producer、observed result、scope、生成时间、freshness、失效条件和 unknown reason。它是关联协议，不强迫所有 owner 使用同一巨型 payload。

#### Hook 与 dev-loop 自动化

此前 Hook 方案按 observe-only→提示→有限约束三个等级保留：

| Hook/组件 | 十天裁决 |
| --- | --- |
| PreCompact | 保留当前结构化快照；不解析 transcript 为权威事实 |
| SessionStart(compact/resume) | 保留；注入旧 HEAD/ref 后要求重新检查新鲜度 |
| SessionStart(startup) | Day 1 条件增加快速 env doctor；不执行完整安装或测试 |
| PostToolUse | 先 observe-only 记录命令/修改并使旧 verification receipt 失效；只用一个同步 dispatcher |
| PreToolUse | 两个真实任务后只提示严格等价重复命令；零误判后才讨论阻断，保留 `force`、flaky 和用户重跑例外 |
| Stop | 两个真实任务后检查当前 diff 是否缺验证/审查 receipt，最多续跑一次；只读任务和无修改任务直接允许停止 |
| PostCompact/UserPromptSubmit/SubagentStart/SubagentStop | 当前没有精确、必要的机械动作，不进入十天关键路径 |
| Permission/approval Hook | 永久禁止自动批准产品 exact diff |
| 后台 Hook | 不保存关键 receipt、失效或审批事实，只允许低价值 analytics |
| 多个同事件 Hook | 拒绝；每类事件只有一个 dispatcher，内部顺序执行 |
| review 自动调用 | Hook 不假定能直接启动审核智能体；只检查当前 diff 的 review receipt，并由主 Agent 显式调用现有可用审查方式 |

workspace fingerprint/command receipt 概念保留 HEAD、staged/unstaged/untracked relevant digest、环境 fingerprint、规范化命令、起止时间、exit code 和结果。CI 必须独立重跑，绝不复用本地 passed receipt。

`dev-loop/dev-check` 不在十天关键路径重新造完整 CLI。先用现有 Fresh/pytest/Ruff/Hook 运行产品；若两个真实工作包仍重复执行同一命令或漏掉验证，Day 11+ 才固化稳定的 context、verify、receipt、env doctor/bootstrap 子命令。

Fresh Coverage companion Skill 不立即创建。先完成一至两次真实运行；若 Codex 对调用时机、退出码、真实模型权限或 receipt 解释仍反复出错，再创建只说明调用边界的单工作 Skill，不复制 CLI 实现或产品状态。

根 `AGENTS.md` 继续瘦身为稳定规则；只在 4～6 个关键边界目录反复出现职责、contract、invariant 或必跑测试误读时，才新增短目录级 `AGENTS.md`/override。十天内先记录需要的位置，Day 11+ 再按真实误读采用，不能给所有模块铺长说明。

Local Environment 的常用 Build/Test/Run Actions 保留为便捷项：只有 Desktop 生成配置、命令稳定且不会混淆产品 Build/Runtime 权限时才加入，最晚 Day 3 完成或明确延期。transcript 只允许在聊天丢失后 best-effort 恢复用户原话和调试 UI 投影；格式不稳定，永远不重建完成状态、权限、readiness 或产品事实，当前核心 Hook 继续不依赖它。

跨模块 handoff 必须回答：阻断的产品 gate、当前现象是否第一 contract violation、producer/detector/repair owner、被违反合同、影响的 capability/route/Artifact/test/release claim、最小可逆修改、验证组合、十天贡献和 unknown。它是临时判断包，不进入第二长期状态文档。

所有模块“能跑”不解释为每个请求强制调用全部模块。宏观审核应证明每个核心模块有明确 owner、合法入口或 producer、输入输出合同、所属 profile、结构/contract smoke，以及未运行时的 dormant/unknown 原因；具体请求只经过所属 route。

验证保持四层：

1. L0 注册/静态合同；
2. L1 模块 contract smoke；
3. L2 fake/frozen route integration；
4. L3 真实 model/source/Build/Runtime Actual。

Route Family 至少覆盖：真实成功、正确拒绝、Repair/Revalidation、外部依赖故障。模块和边只有进入相应层级才获得该层声明，不能由 L0/L1 推到 L3。

`codex exec --json --output-schema` 只可作为 Day 11+ 的只读投影/schema 实验；其模型输出不能成为项目 owner fact。Sourcegraph、SCIP、全局 CodeQL 数据流和全仓知识图不进入十天。coverage dynamic contexts 或增量 symbol/test mapping 只有 impact 实验证明有收益后采用。当前不新建 Codex SDK orchestrator。

宏观查询默认 `quick`：Git、显式 registry 和最近 receipts；只有用户要求或缓存失效才执行 `deep` 重建。否则工程认知工具本身会成为新的耗时瓶颈。

## 3. 十天结束状态

### 3.1 Core 必须演示的真实链与 Stretch Repair 分支

```text
自然语言 Issue
→ 当前源码与外部资料证据
→ EvidencePack
→ Implementation Plan
→ PatchProposal
→ deterministic Review + no-write Dry-run
→ 人工 exact-diff approval
→ isolated Apply
→ real changed-product Build/Test
→ objective success
→ acceptance-required Runtime/verification
→ 单向 Trace/Eval
→ evidence-bound release package
```

如果主链自然发生真实失败，必要 Repair 属于恢复 Core 的一部分。若主链直接成功，只有已有可复现真实失败 checkpoint 时才增加以下 Full-maturity Stretch 分支：

```text
真实 first failure
→ observation 改变下一动作
→ Different Repair
→ Revalidation
→ objective success
```

必须同时保留正确拒绝路径：

```text
证据不足 / 身份漂移 / 权限不足 / 外部依赖不可用 / 业务结果不合格
→ 精确 first failure
→ 不重放已完成副作用
→ 有界修复、降权、转人工或明确停止
→ 不生成虚假完成声明
```

### 3.2 五项 Full-maturity Stretch 完成定义

| 五项 | Full-maturity Stretch 证据 | 不得冒充的更高声明 |
| --- | --- | --- |
| 真实产品行为闭环 | 一个 actual-only changed-product Build/Test 成功，且绑定的 objective success command 与 objective result 均为 passed；一个真实 Failure→Different Repair→Revalidation 后 objective 同样通过；适用的人工审批与 Runtime 边界 | 通用 Coding Agent、所有仓库稳定成功 |
| 外部调用可靠性控制 | 技术结果/业务结果分离；错误分类；超时和总预算；禁止盲目重试；无副作用重放；无合格备用时明确停止 | 自动故障转移、企业级熔断服务、多供应商高可用 |
| RAG/ER 与评测 | 当前来源身份、support/conflict/missing、正向继续和负向拒绝；小型开发集；引用和泄漏边界；适用的 RAGAS 辅助指标 | 40～200 正式数据集、所有检索机制优于基线 |
| Trace/Langfuse 单向链 | 一条 request→evidence→plan→patch→build→repair/result 的 owner-bound 关联；本地投影与 exporter 聚焦测试；真实 sink 或明确本地边界 | Trace 是产品 truth、Trace 自动修改策略或授权 |
| 固定环境运行与部署 | `uv.lock`、clean worktree frozen install、远端 CI、可重复 CLI 演示、Build/Runtime 环境身份和恢复说明 | 完全 hermetic、多平台、多租户、云生产 SLA；缺远端 CI 时只能进入诚实降级交付 |

### 3.3 九项工作包的 Full-maturity Stretch 归宿

| 九项 | 十天裁决 | 结束门 |
| --- | --- | --- |
| 1. 正向证据链 | 必须完成；不恢复旧 WIP 的重复 BHF 技术路径，使用当前选择先做真实 Fresh | committed EvidencePack 或精确、已处理的 first failure |
| 2. Plan/Patch/Build | 必须完成 | 同一 EvidencePack 被真实消费，产生 changed-product Build/Test，且 objective success command 通过 |
| 3. Observation-driven repair | 必须完成 | 真实诊断导致不同动作，随后 Revalidation 与 objective success command 均通过 |
| 4. 工程加速验证 | 必须完成最小样本 | 三个工作包记录同一组速度与返工指标，不因少跑必要测试伪造提速 |
| 5. RAG-1A 收口 | 必须完成窄范围正负语义；若旧 BHF/WC Case 不再适用，使用经审核的新 Case，不改写历史 expected | actual/expected 隔离、正向方向、负向停止、最小关系 Eval |
| 6. RAG-1B 与 v0 public alpha | 条件交付 | 只有 1–5 通过才统一公共 Evidence executor；否则诚实停在 internal alpha |
| 7. Runtime 闭环 | 必须完成适用的窄范围 Runtime；若所选任务 acceptance 明确为 compile-only，则保存不适用判定 | changed Build 绑定到 Runtime 或明确、经审核的不适用边界 |
| 8. Trace/Eval 与模型成熟化 | 必须完成最小 Trace/Eval；正式模型排名延期 | 一条真实关联、失败归因、5～10 条协议校准条件满足时才运行 |
| 9. 工具、Memory、Skills、子智能体与生产成熟化 | 只验证现有提速工具，不继续扩平台 | handoff/Hook/Local Env/CI 被真实使用；长期 Memory 继续延期 |

## 4. 三个 txt 的全覆盖转化

### 4.1 RAG 准确性原料

| 原料 | 十天处理 | 计划位置 |
| --- | --- | --- |
| 文件体检：哈希、重复、损坏、加密 | 目标保留；退出十天战术页 | Day 11+ 文档 RAG 切片 |
| PDF、Markdown、网页输入 | 全部退出十天战术页；存在真实文档知识需求后恢复，不默认抓取互联网 | Day 11+ |
| 逐页识别原生文本、扫描、复杂布局、异常页 | 目标保留；恢复时采用有界页面路由，不承诺所有格式 | Day 11+ |
| 原生提取、OCR、复杂布局、多模态辅助 | 目标保留；其余标记需人工复核 | Day 11+，完整多模态继续延期 |
| 统一 Markdown/结构化文本并保留页码、标题、列表、表格/图片位置 | 目标保留 | Day 11+ 验收 fixture |
| 漏页、乱码、页眉页脚、水印、多栏、OCR 遗漏、表格、重复文本检查 | 全部保留在未来 QA 清单，不声称当前覆盖 | Day 11+ |
| 文本必须回溯到原 PDF 页面 | 长期硬门保留 | Day 11+ citation/provenance 验收 |
| Retrieve：是否需要检索 | 改为 acceptance/任务类型决定；当前 coding task 默认需要当前证据，不增加训练 token | Day 2、Day 8 |
| IsREL：检索内容是否相关 | 映射到检索与 relation-level Eval | Day 2、Day 8 |
| IsSUP：输出是否被证据支持 | 映射到 Findings、faithfulness、引用覆盖和 unsupported claim | Day 2、Day 8～10 |
| IsUSE：是否解决用户任务 | 映射到 objective command、Build/Runtime acceptance 和用户可用结果 | Day 5～10 |
| 低质量时重新检索、重新生成或拒答 | 保留为有界分流；不得形成开放式循环 | Day 2 first-failure、Day 8 answer path |
| Self-RAG 特殊 token 与训练 | 不进入十天实现；保留四类控制问题，使用现有确定性/外部 Eval 表达 | 延期，触发条件见 §9 |
| RAGAS 映射 relevance/faithfulness/answer relevance | 保留为标准文档回答的辅助 evaluator | Day 11+；不拥有 Coding Agent 决策 truth |
| 内容噪声与检索噪声分离 | 保留 | ingestion QA 与 retrieval Eval 分开 |
| BM25、Dense、Fusion、reranker、Top-K | 先以现有 rg/symbol/BM25 基线测量；只有真实召回失败才启用 Dense/Fusion/rerank | Day 8 实验裁决，不默认生产化 |
| 引用、证据约束回答、证据不足拒答 | 必须交付 | Day 8～10 |

### 4.2 成熟项目复查原料

| 原料 | 十天处理 | 裁决 |
| --- | --- | --- |
| 生产级 RAG | 收缩为“生产纪律明确的 RAG/ER 可验证切片” | 必须；不宣称企业级全覆盖 |
| 完全离线本地小模型 | 保留当前 Ollama 路径，补身份、质量、延迟、token 和失败记录 | 必须 |
| 监控与可观测性 | 复用 owner facts、Projection V2 和单向 Langfuse exporter | 必须最小链，完整平台延期 |
| LoRA/SFT/DPO | 只有稳定基线证明 prompt/tool/模型接口仍有任务差距后才值得做 | 十天关键路径舍弃，长期条件项 |
| 实时多模态 | 与当前受控代码交付不构成必要依赖 | 十天关键路径舍弃，未来 Runtime/screen evidence 触发 |
| 可靠 Agent | 作为十天主产品 | 必须 |
| Ask-my-docs 基础、切块、召回、回答和引用 | 目标保留，但完全退出十天战术页 | Day 11+ |
| 混合检索与 Cross-Encoder | 不因“生产级”标签自动采用；先做 A/B 证据 | 条件化 |
| Prompt/config/model/index 版本身份 | 保留 | Day 1、2、8、9 |
| 40～60 起步并增长到 100～200 Case | 十天只做成功、正确停止、Repair 三 Case 最小集；8～12 development/calibration 与 held-out 扩展移到 Day 11+ | 数量技术细节更改，目标保留 |
| 精确查询、Hook Discovery、模糊意图、配置无 Hook、Repair、证据不足六类 Case | 全部保留在数据设计；十天每类至少一条或明确缺口 | Day 8 |
| Case 来自成功、错 Hook、Build/Runtime 失败、版本失效、社区冲突、正确停止 | 全部保留；优先抽取现有真实历史 | Day 8 |
| 人工边界 Case：同义、错别字、中文需求/英文标识、非精确术语、相似 Hook、旧版本高排资料、社区丰富但无权威来源 | 十天只在三 Case 中自然覆盖或登记缺口；完整边界集移到 Day 11+；表达变体必须人工复核且不得生成 expected 技术事实 | Day 7/Day 11+ |
| 模型只生成表达变体，不能生成 Golden 技术事实 | 硬保留 | 数据集门 |
| Retrieval/EvidencePack/answer/Agent 四层指标 | 全部保留；按适用性运行 | Day 8～10 |
| PR、Nightly、Release 分层 Eval | 十天只交付三 Case smoke；Nightly 和 release held-out 在数据协议稳定后再启用 | Day 11+ |
| LangGraph 管流程，Retriever 管检索 | 保留单一控制面和 provider 边界 | 全程 |
| Vector DB、reranker 后端选择 | 不迁移后端；由实验收益触发 | 舍弃默认迁移 |
| 本地模型首 token、总延迟、吞吐、内存/显存 | 产品运行只顺带记录现有 receipt 已有数据；系统性能实验移到 Day 11+ | Day 11+ |
| 本地离线的隐私、无网、延迟与成本价值 | 作为模型选择的使用条件；本地运行没有可核实美元成本时不虚构金额 | README/模型报告 |
| JSON Schema、一次同构纠正、仍失败则停止 | 保留现有严格边界 | Day 2～6 |
| temperature 0 与 0.7 随机性实验 | 从主产品路径移到模型校准；仅稳定接口后运行 | Day 11+ |
| 三模型、30～50 任务、量化比较 | 不在十天完成；Level 1/2/3 全部移到稳定产品链之后 | 正式研究延期 |
| 每步 Trace、p50/p95、失败率、引用覆盖、成本 | 一次真实链记录；长期分位数需要后续样本 | Day 7～10 |
| Prompt 与配置像代码一样版本化 | 保留 | Day 1 起 |
| 流式多模态端到端、组件延迟、重放、韧性 | 不进入当前产品；保留为未来独立垂直项目 | 延期 |
| Workflow 与 Agent 的选择理由 | 明确：确定性 Workflow 管权限/顺序，Agent 根据 observation 改变调查和 Repair | README/面试材料 |
| 成败可客观判定 | 硬保留 | objective command + Build/Runtime acceptance |
| 工具名称、参数、Schema、指导性错误 | 保留并由 Fresh/CLI/Build 错误事实验收 | Day 2～6 |
| 上下文写入、选择、压缩、隔离 | 用 bounded handoff、运行内状态、Hook 和 owner receipt 实现 | Day 1～6 |
| 最大步数、token、成本和时间 | 保留 | 每个模型/工具工作包 |
| MCP 标准化 | 当前已有部分资产；十天不扩大公共 MCP，public entry 成功后再决定 | 延期/条件化 |
| checkpoint、resume、崩溃恢复 | 验证现有 bounded continuation 和不得重复副作用 | Day 6～7 |
| 人工介入且不空转等待 | 保留 exact-diff interrupt/resume | Day 4～5 |
| 沙箱、最小权限、提示注入和不可信输入 | 保留已有边界，Day 10 做聚焦威胁复查 | Day 1、4、10 |
| 最终结果、轨迹、单步三层 Eval | 全部保留 | Day 8～10 |
| 稳定性、成本、失败归因、脚手架消融 | 十天形成最小三工作包记录；统计性结论延期 | Day 2～10 |
| SWE-bench/外部通用基准 | 不阻断当前领域产品；十天后用小子集另立实验 | 延期 |
| 外部 Agent/工具基准 | 只在任务语义匹配、评测噪声和成本可解释时选小子集；不把单次分数当产品结论 | 延期 |

### 4.3 健壮性原料

| 原料 | 当前项目化处理 | 十天证据 |
| --- | --- | --- |
| 先分类后恢复 | 每个 first failure 标为确定性、瞬时技术、持续依赖、业务质量、权限或环境问题 | receipt/trace |
| 确定性错误不原样重试 | 修参数、身份、Schema、权限或唯一 owner；仍失败则停止 | negative tests + actual |
| 瞬时故障有单次超时和总预算 | 保留预算；当前高风险 Actual 默认不自动重试 | model/tool receipt |
| 指数退避、随机抖动、Retry-After | 只在无副作用、明确可重试的普通服务调用中采用；不套到产品 Actual | 条件实现或明确不适用 |
| 持续失败后熔断 | 当前单次本地 CLI 不建全局熔断器；重复同 profile 失败则人为关闭该 profile 的盲目重试 | EVID-005 决策记录 |
| 备用工具、缓存、部分结果、转人工 | 只允许语义等价且预验证的备用；否则降级为只读/明确 blocked | fallback matrix |
| API 成功不等于业务成功 | 27B timeout 与 4B semantic invalid 分层展示 | 模型质量报告 |
| 业务质量退化监控 | 记录结构通过率、规则违反、任务成功和重复一致性 | Day 8～9 Eval |
| 备用模型必须预验证 | 单任务 Patch profile 诊断只能支持该任务；默认备用建议仍需 5～10 条稳定协议校准，不得自动继承 Patch 权限 | Day 11+ |
| 能力下降时权限同步下降 | 自动写→只读草稿→人工审批→明确停止 | authority-aware degradation |
| 已完成副作用不得因恢复重放 | 复用 checkpoint/resume、Artifact identity 和 consumption facts 验证 | Day 6～7 |
| 服务恢复后重新探测业务能力 | 恢复后运行代表性 smoke，不只看端口或 HTTP | environment/model probe |

## 5. 原 Full-maturity Stretch 执行情景与依赖记录（非日常手册）

> 本节保留最初“十天关闭全部成熟硬门”的完整情景，用于解释风险、依赖和舍弃项；它不再是当前战术排程。
> 当前唯一日用排程由 `docs/TEN_DAY_EXECUTION_PLAN_DRAFT.md` 的 Gate 预算定义。两者冲突时，短页只控制 Core 执行；本节继续定义 Full-maturity Stretch 的更高证据门。
> 本节的 8～12 development 加 2～4 held-out 是被判定过载的原情景，不是当前十天验收门。Full-maturity Stretch 当前未分配十天预算；若用户仍选择它，必须另行重排唯一 Eval 数量和 Gate 预算。

### 统一执行规则

- 每天只有一个产品 writer；其他智能体只读调查、测试、日志分析和独立审查。
- 每个复杂 first failure 默认允许两至三个互相独立的只读调查方向并行，主 Agent 负责比较证据并选择唯一 writer 路线；不让并行探索变成多个事实 owner。
- 两个 writer 只有在路径、状态 owner、外部服务和验收完全独立时才进入不同 worktree。
- 每个工作包只选择一个可验证能力阶段，使用 bounded handoff；复杂连续工作可用 `/goal`，但目标必须写清 outcome、constraints、verification 和 stop conditions。
- 用户采纳当日工作包后，主 Codex 默认连续执行该包，不在每个文件、测试或可逆技术选择处暂停；commentary 只报告进展、真实风险和边界变化。
- 每次只处理当前真实 first failure；不得在同一轮顺手修下游问题。
- 日常命令输出为临时 receipt；Actual、Build、Runtime、release checkpoint 才形成持久证据。
- 所有模型、Prompt、Schema、source、config、environment、dataset 和 index 身份在适用处冻结。
- 新基础设施必须说明它减少了哪个已测量的定位、恢复、误修或重跑成本。
- 每次架构/权限复核只允许一个聚焦回合；没有新证据时立即选择最小实验、明确 blocker 或继续当前能力，不连续扩写合同。
- 普通技术不确定性默认通过只读实验解决，不先升级为用户审批；只有范围、外部披露、不可逆副作用或产品方向会实质改变时才请求决定。
- 文档状态只在稳定 checkpoint 更新一次，不在每个局部测试后同步四份控制文档。
- 开发辅助 Hook 默认 fail-open 并报告降级；只有它保护左栏的真实副作用/身份边界且经过真实任务零误判，才可阻断。

### Day 1：采纳、最小全貌与 Fresh→Planning 断层

唯一主结果：建立可以直接推进产品的最小基线，并确认 Fresh 结果能否被下游消费。

主 writer：

- 完成 §1.3 计划采纳门；只保留一个 active actual task；
- 冻结 HEAD、四份 WIP 哈希、dirty、source/profile、objective success command、acceptance 和 Runtime/Eval applicability；
- 生成最小 `quick current slice`：HEAD、dirty、active task、gate、owner first-failure ref、有效/失效验证、下一证据缺口；它从 Day 1 起供 handoff、Hook 和每日审核共用；
- 冻结工程提速基线：orientation、首次编辑前读取、first-failure 定位、重复命令、stale verification、恢复注入、handoff 缺字段、checkpoint、并行冲突、tool/model/token/elapsed；
- 核对当前 `fresh-coverage` 生成的 exact FeatureSpec/EvidencePack refs 是否有现成调用面继续 Planning；
- 若没有，只补一个读取 exact refs、严格 freshness/readback、停止在既有权限边界的窄 continuation consumer，并用 fixture 证明它不重跑 Fresh；
- 预登记第二个真实 Repair Case：必须能从当前冻结的真实失败 checkpoint 直接进入 Repair，前序 Artifacts/source/acceptance/authority/objective command 已验证；主任务自然产生合适失败时优先使用主任务；不存在该 Case 时不得承诺 Day 5 Repair 门；
- 若 G0 选定 AccurateCrosshair，明确记录 gameplay Runtime 为 delivery 必需项，并在对应 Runtime Gate 前安排授权窗口。

并行运维，只读或独立路径：

- Local Environment/短路径 temp/frozen install/20 文件 checkpoint；
- 启动远端 CI，保存 commit、lock、环境、精确测试范围和已知排除项；
- 信任并 smoke 当前 PreCompact/SessionStart Hook；
- 只禁用会误触发当前任务的旧 Skill；其余 Skill、profiles、PostToolUse、pre-commit 和状态文档精简移到 Day 9 条件队列。

Day 1 后半段必须开始 Fresh preflight。任何需要新数据库、第二 Graph、全量 project intelligence 或大规模控制文档重写的方案立即停止。

### Day 2：Fresh 真实验收、可关联 receipt 与 Patch profile 门

唯一主结果：形成可消费 EvidencePack 或关闭其唯一 first failure，并在日终给出 Patch profile 的初步 go/no-go。

- 冻结 FeatureSpec/request、HEAD、source snapshot、settings、loopback Ollama tag/digest、Prompt/Schema 和预算；同一 Ollama/GPU 的调用串行；
- 执行一次真实 Fresh Coverage；
- stdout receipt 外增加最小 owner receipt/薄 adapter，绑定 run/request、HEAD/source、config/profile/model、started/finished、receipt hash、Artifact refs、scope、freshness、limitations；不复制 EvidencePack payload；
- 合法结果只有 committed EvidencePack + 明确 Coverage，或精确 stage/code/owner first failure；
- 确定性错误只修唯一 owner 一次；provider timeout/429/5xx 不盲目重试；业务非法使用已有一次同构纠正，仍失败则停止；
- 证明 Day 1 continuation consumer 能读取同一 exact refs，而不是重新执行 Fresh；
- 使用冻结 Patch 输入做最小 profile 资格判断：技术响应和业务/Binding 最低门必须分别记录；27B 旧配置不重复，4B 旧结果不晋级。

日终硬门：没有可消费 EvidencePack，停止完整链承诺；没有任何 Patch profile 达到最低门，Day 3 只能形成明确 blocked 或请求一个独立的新 profile 决定。

### Day 3：Plan→Patch→Review→Dry-run→人工审批

唯一主结果：同一 EvidencePack 形成完整、可审查、零写入 diff。

- Patch profile 必须先通过 Day 2 的技术和业务最低门；没有合格 profile，不启动产品 Patch；
- Implementation Plan 区分 exact edit bindings 与 supporting evidence；
- Patch 覆盖 Plan 的完整 change/binding 集；ProposalReviewer 独立重复范围、来源和绑定检查；
- Dry-run 输出完整 unified diff、低成本静态检查和 exact diff hash，source 零修改；
- 每个 exact diff/revision 只有一个有意义审批点；hash/范围不变不重复弹窗，身份漂移才重新审批；
- 审批通过后持久挂起/恢复，不让进程空转；批准不等于语义证明。

日终硬门：没有完整合法 Dry-run diff 或及时人工审批，停止 Apply，不用手工补模型答案。

### Day 4：isolated Apply→changed-product Build/Test→objective

唯一主结果：获得第一个真实 changed-product Build/Test 和 objective 结果。

- 只应用获批 exact diff；重新读取 live source，验证 occurrence/hash/authority；
- 在隔离工作区执行真实 restore/build/test，验证目标产物；
- 执行预登记 objective success command，分别记录 Build result 与 objective result；
- 第一个物理失败保存原始 diagnostics、producer/detector/repair owner、受影响 binding 和已完成副作用；
- 不在同日跨层修多个 owner。

Build 通过但 objective 未通过仍是产品失败。Build 和 objective 都通过时，Core 主任务成功路径成立；第二 Repair Case只影响 Full-maturity Stretch。

### Day 5：Full-maturity Stretch 的真实 Repair Case→Different Repair→Revalidation

原情景结果：完成一次非人工造错的 Failure→Different Repair→Revalidation。它是 Full-maturity Stretch 证据，不是 Core 的无条件硬门。

- 主任务 Day 4 自然产生可修复失败时继续该任务；否则启动 Day 1 预登记的第二真实 Repair Case；
- Repair 只消费精确 observation 和现有 authority，不重复原 Patch，不预填最终答案；
- Repair Proposal、Review、Dry-run、approval、Apply、Build/Test 和 objective 保留完整 lineage；
- Revalidation 后 Build/Test 与 objective success command 必须同时 passed；
- 验证 checkpoint/resume 没有重放已完成 Apply 或其他副作用；
- 同一通用修复仍不能移除同一失败签名时，冻结 explicit unresolved，不继续抽样。

若 G0 选定 AccurateCrosshair，最晚在其 Runtime Gate 前取得游戏启动、目录写入、观察和恢复授权；缺失时不能形成该任务 delivery/public-alpha 主张。

### Day 6：必需 Runtime、崩溃恢复与单向 Trace

唯一主结果：将 changed Build、objective 和必需 Runtime 绑定到一个 truthful terminal result。

- 若 G0 选定 AccurateCrosshair，按已登记 acceptance 执行 gameplay Runtime，不能临时改成 not applicable；若采用另一任务，只按其已审核 acceptance；
- 部署并 hash 验证 exact artifact，收集受信 observation，恢复环境；provider/environment/permission/observation 失败不得自动改源码；
- 仅在现有 checkpoint/resume 无需新增产品代码时，做一次有意进程中断→恢复→不空转→不重放已完成副作用的机械验收；否则标记 durable execution `not_demonstrated` 并移到 Day 11+；
- 形成 request→EvidencePack→Plan→Patch→Build→Repair/Runtime→result 的 owner-bound 单向投影；
- 运行 Thin Lineage、ProjectionRebuild、Langfuse exporter 聚焦测试；有 sink 时发送一条脱敏真实 trace，否则明确 local exporter evidence；
- prompt、model output、chunks 和 rerank 过程只有在披露允许时保存受限引用；默认存 hash、脱敏摘要、指标和 owner refs，不原样落盘；
- 记录 secret/redaction/egress、worktree 文件隔离与 OS/process/network sandbox 的区别。

安全审查和 release evidence 从本日滚动归档，不留到 Day 10 首次发现问题。

### Day 7：ER 小集、正负门与 held-out

唯一主结果：证明 RAG/ER 能在证据充分时继续、证据不足时停止。

- 使用 Day 1 起只读整理的 8～12 条 development/calibration Case，覆盖精确查询、Hook Discovery、模糊意图、配置无 Hook、Repair、证据不足；
- 单独冻结 2～4 条 held-out，禁止根据结果调 Prompt、Top-K、排序、阈值或 expected；
- 预登记最大真实模型调用和墙钟预算；允许确定性 replay 覆盖非关键样本，真实模型优先运行正向、负向和 Repair 三类关键样本；预算内未运行项显示 unknown；
- actual 先冻结，expected 后读取；Golden 技术事实只由人工确认，模型只生成表达变体；
- 至少一条正向继续和一条负向拒绝；
- 测量 retrieval、EvidencePack、answer（适用时）、Agent decision、失败归因和正确停止；RAGAS 仅补适用指标；
- trajectory 同时保留最终结果、单步和部分得分，并区分 required/optional/forbidden、严格顺序/无序/子集语义；
- 增加平均步数、人工介入率、工具失败率、超预算终止率、token/calls/elapsed；
- 人工边界 Case 至少覆盖：同义表达、错别字、中文需求/英文标识、非精确术语、相似 Hook、旧版本高排资料、社区很多但无 authoritative evidence；缺项必须显示 unknown，而不是用重复 Case 凑数；
- cache/中间结果必须绑定 source/config/profile/freshness/limitations，不能代替 current Actual 或写权限。

OpenTelemetry GenAI 语义映射保留为 Day 11+ 的观测标准化项；Day 7 只复用当前 Trace/Projection 字段，不为标准化改写真实运行链。

Dense/Fusion/rerank 只有基线存在可复现漏召回且小实验改善时才采用；否则保持关闭。

### Day 8：条件公共入口；标准文档 RAG 退出十天

唯一主结果：硬门通过时统一公共入口；未通过时收紧 internal alpha，而不是降低标准。

条件 A：Day 1–7 的 objective、Repair、ER 正负门通过，且 required Runtime 通过或经审核为 `not_applicable`。

- 让唯一公共 Agent entry 委托同一 Evidence executor；旧入口只做参数/展示适配或退出；
- 不复制 Store、readiness、terminal、route 或 first-failure owner；
- 形成窄范围 public alpha。

条件 B：任一硬门未通过。

- 保持 internal alpha 或诚实降级交付；保存 exact unresolved，不强推公共入口。

标准文档 RAG、PDF、网页、OCR 和普通 Ask-my-docs 全部移到 Day 11+。其工程成熟目标仍保留在 §4 和 §9，但不再以“公共入口提前完成就顺便做”的方式诱导第二产品线进入十天冲刺。

### Day 9：最小宏观审核、证据语义、安全与发布预检

唯一主结果：让 Day 10 可以直接复验和包装，不再新增产品能力。

- 扩展 Day 1 quick slice 为最小 `context/evidence` 宏观视图：HEAD/dirty/task/gate、owner ref、valid/stale验证、scope、freshness、limitations、next gap；
- 对九项与五项实际进入的 capability/route 输出 discovered count；每项有 owner、entry/producer、input/output contract、profile、smoke 或明确 dormant/unproven/orphan；未扫描的全仓能力显示 unknown，不从目录数猜模块数；
- 只在时间允许时增加这些当前路线的 declared/configured/observed flow；全仓完整 inventory/flow/impact/health、增量索引和综合界面移到 Day 11+；
- 修正 release packager：任意自然语言 claim 只标 evidence-bound；只有受控 claim type、scope、freshness 和同 release identity 全匹配才标 demonstrated；
- CI 纳入真实 Thin Lineage/Langfuse 聚焦测试和小型 RAG smoke，并保留 full-unit 未绿、20 文件 checkpoint 的范围；
- 完成 prompt injection/不可信证据不能取得工具、外发或写权限的负向测试；没有真实 OS/process/network sandbox 就标 `not_demonstrated`；
- 完成依赖、secret、redaction、egress、最小权限和供应链预检；
- 生成 release draft 和三工作包加速报告。

profiles、PostToolUse、PreToolUse、Stop、pre-commit、import gate、branch coverage、`dev-check`、模型 Level 1 和旧 Skill 全面整理全部移到 Day 11+，除非它们是当前已观察 first failure 的唯一 owner。

### Day 10：clean-room、演示、简历、最终证据包与缓冲

唯一主结果：复验已经完成的能力，形成 `ten_day_full_maturity_stretch_met`、`ten_day_core_target_met` 或 `honest_degraded_portfolio_delivery`。

- 全新 worktree/clean checkout 执行 frozen install、Ruff、CI checkpoint、核心 Eval 和演示命令；
- 核对远端 CI 运行、commit、lock、环境、测试范围和排除项；远端 CI 缺失时成熟目标未达成，只能进入降级交付；
- 使用 release-evidence-packager 生成 release manifest、README 结果表、3～5 分钟演示、简历 bullet 和面试问答；
- 每条主张绑定 objective、commit、命令、测试/CI、Build、Runtime、Trace/Eval；
- 未证明内容列为 `not_demonstrated` 或 Future Work；
- 对照本文 §4、§7、§8 做最终遗漏审计；
- 复核九项与五项实际交付路线中的全部能力均有 owner、entry/producer、input/output contract、profile、smoke 或明确 dormant/unproven/orphan；全仓未扫描部分保留 unknown，不反向否决已完成产品证据；
- Day 10 禁止新增产品能力，只允许复验、修复发布阻断、包装或诚实降级；剩余时间作为缓冲。

### 并行副线

| 时间 | 只读或独立路径工作 | 不得阻断 |
| --- | --- | --- |
| Day 1–3 | Local Environment、hosted CI、Hook trust、ER Case 清点 | Fresh/Plan/Patch |
| Day 2–7 | Golden/held-out 人工资料整理、Trace refs、加速指标 | 同一 Ollama/GPU 必须串行 |
| Day 6–9 | 安全、证据归档、release draft | ProductExecution/ArtifactStore 不并发写 |
| Day 9+ | Skill/Hook enforcement、profiles、pre-commit、dev-check、coverage、import gate | Day 10 核心复验与交付 |

任何并行运维若需要写仓库，必须使用独立 worktree/独立路径并由主集成 writer 串行合并；否则保持只读，不得与 Fresh consumer/ProductExecution writer 同 checkout 并发。

## 6. 失败分流与十天止损门

| 检查点 | 通过 | 未通过时的成熟处理 |
| --- | --- | --- |
| 采纳门 | 选定唯一任务、objective、acceptance、权限和预算 | 十天计划保持草案，不启动 Fresh/Actual |
| Day 1 consumer | exact Fresh refs 可被 Planning 消费且不重跑上游 | 只补窄 continuation；仍无解则停止完整链承诺 |
| Day 2 Fresh/profile | 可消费 EvidencePack + Patch profile go/no-go | 只修一个 first failure；无合格 profile 则产品链 blocked |
| Day 3 Dry-run | 完整合法 diff + exact approval | 不进入 Apply，不手补答案 |
| Day 4 Build/objective | Build 与 objective 均 passed，或一个精确 first failure | 只允许 Day 5 的一个 Different Repair |
| Day 5 Repair | Revalidation 与 objective 均 passed | 冻结 explicit unresolved，成熟目标未达成 |
| Day 6 Runtime/Trace | 必需 Runtime、恢复和 owner-bound trace 达门 | 不形成 delivery/public-alpha；记录对应 owner |
| Day 7 ER Eval | 正向、负向、held-out/隔离与最小指标达门 | 不形成 RAG-1A，保持 measured gaps |
| Day 8 public entry | 所有前置硬门通过 | 保持 internal alpha，不降低门槛 |
| Day 10 release | objective/repair/runtime/RAG/CI/证据全齐 | 输出诚实降级交付，不能标成熟目标达成 |

若 Day 2 结束仍没有可消费 EvidencePack，或 Day 3 没有合格 Patch profile，十天 public alpha 不再是合理承诺。此时优先形成可复现、能解释失败的 internal alpha/降级作品包，不同时启动 PDF、多模型和 Dashboard。

## 7. 保留、改变、新增、舍弃与延期账本

### 7.1 原样保留

- 单一 LangGraph `StateGraph` 作为流程和路由 owner；
- ArtifactStore 作为持久业务事实与 lineage owner；
- current source/API/runtime evidence 高于历史、模型和社区材料；
- actual/expected 隔离、Hidden-Golden 后比较；
- EvidencePack 只拥有证据层判断，不授予写、Build 或 Runtime；
- exact path/hash/span/binding 与 live revalidation；
- ProposalReview、no-write Dry-run、人工 exact-diff approval、isolated Apply；
- Build、Runtime、Eval 和产品完成各自独立证据等级；
- first physical failure、一次通用 Repair、一次 Revalidation；
- 本地模型和外部数据披露边界；
- 正向继续与负向拒绝同等重要；
- RAG/ER 与普通文档 RAG 共享基础设施、不共享证据含义和权威；
- 证据点、lineage 线、能力矩阵面和失效时间；
- 真实数据驱动机制采用，不为架构外观扩张。

### 7.2 技术路径改变，但目标保留

| 旧提法 | 改版 |
| --- | --- |
| 每轮先重读大量权威/WIP/历史再确认是否能做 | 每轮只读短 current-state、当前 owner source/test 和精确 refs；长文档按需查询 |
| 任务包主要强调 `stop_when/out_of_scope` | 同时明确 `authorized_actions/next_capability_stage`，范围内默认连续推进 |
| 开发工具异常也 fail-closed | 产品 truth/副作用 fail-closed；可选 Hook/投影/telemetry fail-open 并记录 |
| 模型在第一次 observation 前必须填写完整内部拓扑 | 模型先表达语义和调查方向；确定性代码生成 identity，计划随 observation 演进 |
| 所有模型输出问题都增加 schema/validator | 只对事实伪造、身份、权限和不可恢复持久化错误 fail-closed；普通质量问题进入 Eval/一次纠正 |
| 从 8 月 WIP 的重复 query dispatch/BHF 旧第一失败继续 | 以当前 HEAD、当前选择和真实 Fresh receipt 重新确定 first failure；旧事实仅为历史 |
| Self-RAG 必须训练自省 token | 保留 Retrieve/IsREL/IsSUP/IsUSE 四问题，用确定性规则、模型判断和外部 Eval 分责；训练延期 |
| RAGAS 替代 Self-RAG/整个 Eval | RAGAS 只覆盖适用上下文和回答指标；工程身份、权限、Hook、Build/Runtime 自定义判断 |
| 所有 PR 跑 50～200 Case | PR 跑小型确定性 smoke；Nightly/Release 分层；十天只形成小数据集 |
| “生产级 RAG”意味着默认 Dense+RRF+reranker | 先测 rg/symbol/BM25；只有真实召回收益才采用额外机制 |
| 三模型正式比较马上开始 | 先稳定接口和真实任务；Level 1/2/3 均移到 Day 11+，十天产品运行不产生默认模型结论 |
| 所有瞬时错误自动退避重试 | 高风险 Actual 继续默认零自动重试；只在无副作用且明确可恢复的调用中有界采用 |
| 立即建立全局熔断器 | 当前用 profile 禁止盲目重试和明确停止；共享服务模式有数据后再实现熔断状态机 |
| Hook 恢复聊天 | Hook 只恢复任务定位、Git 和 receipt 指针；客户端聊天丢失不是其能力 |
| 完整 `project_intel` 微内核 | 复用 Projection V2，只做薄 adapter 和只读宏观审核投影 |
| release packager 根据同 SHA + verified 证明任意 claim | 区分 evidence-bound 与受控范围的 demonstrated；不做任意自然语言蕴含判断 |
| 工业级 PDF 全格式一次完成 | PDF/网页/通用文档 ingestion 全部退出当前十天战术页；长期恢复时先做页面身份、最小路由、QA 和明确人工复核 |
| “生产级”作为简历形容词 | 改成可复现 internal alpha + 明确完成门、失败证据和限制 |

### 7.3 新增

- “宽认知、窄权限”的 Agent/Codex 双层自主原则；
- Codex 平台仓库开发自主权与产品 Mod Apply 权限分离；
- 计划采纳门、唯一 active task 和 objective/acceptance 明确化；
- Fallback、Core target 与 Full-maturity Stretch 三层结果分离；
- Day 1 的最小 quick current slice，不等完整宏观系统到 Day 9 才使用；
- Fresh exact refs→Planning 的窄 continuation consumer 验收；
- 第二个非人工造错的真实 Repair Case 预登记；
- 十天 go/no-go 门和失败止损；
- 技术可用性与业务有效性双结果；
- 恢复不得重放已完成副作用的验收；
- 备用模型的预验证与权限降级矩阵；
- 统一工程提速指标和三个工作包的对照；
- 同一 checkout 单 writer 规则；
- 旧 Skill 路由清理；
- clean-room Local Environment 与远端 CI 证明；
- 小型普通文档 RAG/PDF 页面 provenance 切片作为长期目标保留，但退出十天战术页；
- read-only 宏观审核视图；
- 发布主张的 evidence-bound/demonstrated 分离；
- Day 10 逐项遗漏审核。

### 7.4 从十天关键路径舍弃

下列内容不是被永久否定，而是不允许占用十天产品关键路径：

- LoRA、QLoRA、SFT、DPO 和训练数据建设；
- 实时语音、视频、多模态流式产品；
- 全格式 PDF/OCR/复杂表格生产服务；
- 默认 Dense、RRF、Cross-Encoder、外部 reranker；
- 完整 40～200 Case、三模型 Level 2、量化 Level 3；
- SWE-bench、通用外部 Agent benchmark；
- 完整 Trace 平台、长期 Dashboard、Nightly 服务运维；
- Knowledge Hub 产品化、多租户 Vector DB 迁移；
- MCP/HTTP 写接口扩展；
- 通用自动 fallback、全局熔断和多供应商网关；
- 长期 Memory、自动经验提取和策略学习；
- 常驻多 writer 智能体群；
- 全仓 mypy/pyright、泛化 Hypothesis、Sentry、Playwright；
- Windows 当前不可用的 Record & Replay；
- 未经普通聊天验证的 Scheduled Tasks；
- `pytest-testmon`、`pytest-picked` 等新选测插件，除非现有 focused mapping 被真实证明不足。
- Superpowers 或其他大型流程 Skill 包；
- 在 hosted CI 尚无真实失败前预先引入 CI 修复 Skill；首次真实失败后才按 exact run 诊断；
- Codex SDK 或另一个长期 orchestrator，除非现有 thread/goal/worktree 无法表达具体任务。

### 7.5 永久拒绝的错误做法

- 模型或当前输出生成 Golden 技术事实；
- 检索相关性直接授予 edit authority；
- 测试、Build、Runtime、Trace 或同一 SHA 相互越级证明；
- 自动模型 fallback 继承原写权限；
- 为赶排期重复同一失败、提高 timeout 或手工补模型答案；
- 把 supporting evidence 当 exact edit binding；
- 让宏观页、Langfuse、Eval 或 Skill 成为第二状态/路由/充分性 owner；
- 以工具数量、测试数量、文档长度或绿色子集冒充产品完成。

## 8. 完整评测与证据目录（非十天 Core 采集清单）

> 本节保存三个 txt 的完整评测原料，供 Full-maturity Stretch 和 Day 11+ 使用。十天 Core 只执行战术页 G4 的 4～6 Case、两个 held-out 和四个自动提速指标；未采集的目录项不是 Core blocker。

| 层 | 完整成熟指标 | 数据来源 | 目标输出 |
| --- | --- | --- | --- |
| 输入/文档 | 页覆盖、乱码/重复/异常、page provenance、人工复核率 | 小型 PDF/Markdown fixture | ingestion QA report |
| Retrieval | Recall@K、MRR/nDCG、exact/symbol、forbidden、authority、stale | 8～12 development + 隔离验收 | retrieval report |
| EvidencePack | role/relation coverage、duplicate、authority violation、freshness、missing correctness、readiness/action | Fresh/ER actual | evidence report |
| 回答 | faithfulness、citation precision/coverage、unsupported claim、relevance、abstention | 标准文档 RAG Case | answer report |
| Agent 决策 | file/Hook/plan binding、scope expansion、review blocker、repair routing | actual-only任务和负向 Case | decision report |
| 产品 | objective、Build、Runtime applicability、final status |真实 command/Artifact | delivery manifest |
| 健壮性 | error class、retry budget、degradation、duplicate effect、recovery probe | model/tool/runtime receipts | reliability report |
| 轨迹 |最终、trajectory、single-step；声明/配置/观察/验证 | Projection V2 + exporter | trace report |
| 性能 | `time_to_orientation`、`time_to_first_failure_attribution`、`failure_to_next_validated_action_time`、`time_to_next_capability_stage`、`files_read_before_edit`、`duplicate_command_rate`、`stale_verification_rate`、`context_restore_tokens`、`handoff_missing_field_rate`、`checkpoint_wall_time`、`integration_conflicts`、全链回放、跨层误修、测试、tool/model calls、tokens、elapsed | 三个工作包 | acceleration report |
| 模型 | schema、首次通过、纠正后通过、选择、正确停止、延迟、吞吐、资源 | Level 1 条件实验 | model protocol report |
| 环境 | frozen install、Ruff、CI、clean worktree、artifact hash | Local Env + GitHub Actions | reproducibility report |

不建立单一“综合健康分”。每项必须保留 profile、样本数、范围、freshness、unknown 和 limitations。

## 9. 十天后条件队列

只有相应触发成立才进入：

| 未来能力 | 触发条件 |
| --- | --- |
| 40～60 / 100～200 Case | 小型 Case 协议稳定，新增样本能覆盖重复真实失败 |
| Dense/Fusion/rerank | 基线有可复现的相关证据漏召回，实验显著改善且成本可接受 |
| Level 2 三模型比较 | 30～50 冻结任务、held-out、同硬件/运行时/接口、三模型身份齐全 |
| 量化 Level 3 | 已经由 Level 2 选择模型家族 |
| LoRA/SFT/DPO | prompt、tool、检索和模型选择均稳定，仍存在重复、可量化任务差距，并有足够干净数据 |
| LoRA/SFT/DPO 后续验收 | 干净数据、独立 held-out、训练前后指标、训练曲线、退化/遗忘和失败调整必须完整报告 |
| 实时多模态 | 一个真实 Runtime/screen/audio需求无法由现有 observation 完成；语音、屏幕视觉、流式日志应作为不同垂直任务选择其一，不捆绑上线 |
| 全格式 PDF/OCR | 真实文档数据暴露现有页面路由无法处理的稳定失败类别 |
| 全局熔断/模型网关 | 多请求共享依赖的持续故障造成重试风暴或级联影响；实现时必须包含 Closed/Open/Half-Open、冷却探测和恢复后的业务质量 probe，而不只检查端口响应 |
| 长期 Memory | 多个已验证任务重复暴露同一经验检索失败，人工 lesson 不足 |
| MCP/HTTP/Dashboard 扩展 | 真实外部用户或客户端需要缺失接口 |
| 完整宏观 intelligence/impact | 两到三个真实工作包仍反复跨 owner 定位，并能验证静态/观察图的收益 |

## 10. 可行性判断

十天实现“全部长期生产能力”不可行；十天 Core target 有条件可行，Full-maturity Stretch 不应作为无条件承诺。

可行条件：

- G0 不再扩展基础设施；
- G1 能形成可消费 EvidencePack，或只需一个 owner 修复；
- Patch 模型/profile 在一天内作出明确可用或不可用结论；
- 人工 exact-diff 审批及时；
- changed-product Build 和 Runtime 环境可使用；
- 每次只推进一个 active first failure，Gate 提前完成可立即继续，外围工作采用只读并行；
- Public alpha 和模型研究服从关键路径；PDF/普通文档 RAG 已退出十天。

最大风险：

1. 真实本地模型再次出现长时间 provider liveness 或业务质量失败；
2. 当前任务需要多个未授权 edit binding；
3. Build/Runtime 环境出现不可在一天内修复的外部依赖问题；
4. 为追求“全部生产级”重新扩建控制层、Eval 平台或工具体系；
5. WIP 历史状态与当前 HEAD 混用，导致返工；
6. 远端 CI、Hook 信任或 Local Environment 直到最后才验证。
7. 把 Hook、宏观审核或长计划本身变成新的强制 gate，使“提速工具”再次增加等待和解释成本。

基于目前四小时已经完成的底座，速度有望提高，但尚无数据支持“大幅提高”的结论。十天只自动记录总墙钟、first-failure 定位时间、完整重跑次数和 checkpoint 测试耗时；不同任务之间最多称为 `observed workflow-efficiency signals`，不能声称自动化带来某个百分比的因果提升。严格提速结论需要同类任务 before/after、重复运行或消融。

## 11. 审核问题

用户审核时只需裁决以下非技术选择：

1. 十天采用 Core target，还是仍以包含 Repair 和更广 Eval 的 Full-maturity Stretch 作为硬承诺；
2. G0 若找不到可消费 Repair checkpoint，是否接受 Repair 只作为 Stretch 而不制造失败；
3. G1 仍无可消费 EvidencePack 时，是否允许选择另一条具有自动成功命令的 actual-only任务；
4. 必需 Runtime 的游戏启动/目录写入/观察/恢复，以及远端 CI、Langfuse sink、外部模型调用，采用一次边界包还是届时分别授权；
5. 是否接受 PDF/普通文档 RAG、LoRA/DPO、多模态、完整 40～200 Case、正式模型排名明确移到 Day 11+。

其余技术细节可在不改变上述目标、证据门和舍弃边界的前提下，由每天的真实 first failure 调整。
