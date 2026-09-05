# 两小时连续执行工作包：Agentic Patch、自主Planning与完整十日目标

状态：用户已授权执行；北京时间2026-09-05 16:44:24启动，执行窗口至18:44:24。
编排基线：`aa3a72f`；当前请求 `ACCURATE-CROSSHAIR-SPREAD-TOGGLE-001`。

本文是本轮要求的执行编排，不是新的状态数据库、审批或第二份长期队列。
当前选择与优先级仍由 [Active Contract §1.1](ACTIVE_PRODUCT_CONTRACT.md)、
[Implementation Queue 当前块](IMPLEMENTATION_QUEUE.md)及用户最新决定约束。
精确运行身份、命令和结果只在 [reconciliation §9–11](audits/PATCH_AGENT_PROGRESS_RECONCILIATION_20260905.md)
维护；本文只引用基线与完成条件。后续真正交接一个实施子项时，再使用已有单能力handoff，
不把本总包塞进800–1500-token包，也不复制整页历史。

## 0. 两小时直接执行指令

执行窗口为启动时刻T0起的120分钟。它是一次连续推进窗口，不是把七组十日目标降为两小时
子集，更不是承诺两小时完成全部七组。用户后续输入继续校准当前目标；没有明确取消就保留主线。
用户已发出“开始做这一步，授权所有权限”。T0为2026-09-05 08:44:24 UTC，截止10:44:24 UTC。
本包内平台实施、测试、提交和本地模型接受运行开始推进；尚未形成的新exact diff仍需相应审查，
具体游戏操作须保持已约定的任务、路径、尝试与恢复边界。

### 0.1 两小时优先交付

1. **生产上下文准入能力**：完成A1的生产接线、聚焦验证与真实serializer/preflight；
   保留FeatureSpec、First Shot澄清、5个exact binding、必要supporting和失败边界。
2. **真实Agentic Patch结果**：条件通过后执行A2，由产品模型读允许源码并生成修订；
   形成新Proposal/Review/Dry-run，并针对新Patch验证原冷启动义务及生成来源。
3. **自主Planning的有界实现结果**：从前段独立并行推进A3；至少争取交付能运行的目标选择
   接缝与验证，资源/时间足够时取得一次真实Planning结果。没有真实自主运行时必须写未验证，
   不能拿代码/测试或当前人辅Plan冒充自主Planning完成。未接生产入口的孤立selector或仅测试替身
   通过只能记局部实现，不能算生产Planning已接通。
4. **可继续的冻结状态**：独立提交、实际测试/模型/Harness结果、准确的失败位置和12轮覆盖更新。

以上是实施目标，不是“失败报告也算成功”的替代标准。某项未达成，120分钟结束时照实列为未完成。

### 0.2 时间安排（执行默认值，不是新的产品门禁）

| T0后时间 | 主执行线 | 可并行的独立工作 |
| --- | --- | --- |
| 0–5分钟 | 核对HEAD、WIP、exact Artifact/source和当前请求；立即进入实现 | 给有界子智能体明确互不重叠的任务和输出；不再全页审计 |
| 5–40分钟 | A1选择并实现可读的无损输入投影；聚焦测试、真实离线preflight；冻结可接受版本 | A3研究已知入口后直接做有界实现/测试；准备新Patch的现有Harness验收与来源核验，禁止写正确Mod答案 |
| 40–85分钟 | A1合格后执行一次新的真实Patch接受运行；保留全轨迹，检查新Proposal/Review/Dry-run与正向行为 | 不与模型争抢GPU/大内存；可继续独立代码、轻量测试、证据核验；共享入口修改统一集成 |
| 85–105分钟 | 若新diff合格，准备具体人工语义/exact审批；授权已具备且时间够则推进相应Apply/Build/Runtime | 待批准或P0精确阻断时，立即集成/验证A3并争取真实Planning运行；否则推进A6/A7.1/A8中一个不依赖阻断的既定任务 |
| 105–120分钟 | 完成正在进行的有界验证、提交与结果保存，更新当前入口和覆盖报告 | 不再启动预计无法在剩余时间结束的新模型/游戏运行；不为凑满时间增加场景或审计 |

阶段提前完成立即前进，不按表空等；必要时按实际依赖调整时间比例。判断余时须计入一个接受运行
内部可能发生的全部模型turn、合法correction及清理时间，不只看单次HTTP timeout。
如果主线在5–40分钟内已经形成不可当轮消除的精确阻断，立即转独立实现，不能把整段时间耗在
不断修同一表示方案上。不得以“进入最后15分钟”为由中断安全清理或遗失已启动运行的结果。

### 0.3 执行责任与权限

- Codex负责平台实现、准确接线、输入/身份验证、独立测试、证据记录和集成；产品模型负责Mod代码。
  禁止工程正确`after_text`、参考实现和Harness答案进入产品生成路径。
- 当前两个并行方向为A1/A2主线与A3实现；来源/Harness核验可作为有界独立支线。不是固定常驻四人
  审查。若碰同一文件或Graph入口，调整为串行；没有额外worktree也不能让多writer抢写。
- 真实Patch首先仍用已选`qwen3-coder:30b`和现有bounded loop/profile；不静默换模型、增context、
  加timeout或改response schema。新增真实Planning使用实施前明确绑定的profile和现有准入。
- 每个实际接受尝试沿当前明确预算执行，第一项新失败必须保留并处理；未经有意义的聚焦证据证明
  已修复，不启动第二次接受运行。不能为了两小时持续工作而不断调用模型。
- 新exact diff就绪后才能请求相应审批。没有批准不Apply，没有相应授权不操作游戏目录/启动游戏；
  缺少这些批准仅阻断对应动作，不让整个两小时停在等待。普通平台读改测不反复询问同一授权。
- 保护六份用户WIP和原Artifact；只提交本次明确归属的代码/测试/文档。阶段性代码不完整时保留
  可解释WIP，不为了“有提交”提交破坏性半成品。

### 0.4 两小时结束必须报告

| 项目 | 必须说明 |
| --- | --- |
| 提交 | 每个commit改了什么、解决哪个触发问题、改动文件、验证结果；不只列hash |
| 当前P0 | 是否取得真实新Patch、Proposal/Review/Dry-run、正向回归及生成来源；批准/Apply/Build/Runtime分别到哪一步 |
| 自主Planning | 实现/测试/真实调用分别是否完成；是否有人补target IDs；人辅和自主结果不得混用 |
| 模型与测试 | exact输入/版本、实际调用次数、tokens/耗时、通过/失败、来源与证明边界 |
| 12轮及新增输入 | 每条对应已实现、已验证、仅分析、未完成；报告期间新增要求不遗漏、不自动算完成 |
| 未完成与下一步 | 精确blocker、已尝试的有界处理、未执行原因、后续独立工作；七组十日目标不打完成总勾 |

可直接使用的启动指令：

> 按本文件第0节，从现在起连续推进120分钟。优先A1→A2，同时安排独立A3实现；复用已有底座，
> 不重做全量Fresh、parser或通用Harness。产品Agent生成Mod修订，Codex只做平台/证据/验证工作。
> 保留既有身份、权限、披露、exact审批和游戏操作边界；真正需要我决定时给具体可审查结果，
> 同时继续不依赖该决定的工作。时间结束报告真实提交、运行、覆盖和未完成，不把两小时结束当目标完成。

## 1. 总目标与不能混用的完成层级

先用产品Agent修复当前AccurateCrosshair并完成其必要验收；成功或形成精确路径阻断后，
立即推进不依赖该阻断的完整十日建设。七组全部在十日目标内：
端到端交付与Repair/Revalidation、生产Evidence/RAG、Agentic Execution、
Trace/Lineage/Langfuse、模型资格与角色路由、固定多任务Eval、可重复环境/CI/Release。
旧Core/Stretch仅解释历史，不是当前降档或延期依据。

“12条输入已登记”“已形成工作安排”“代码已实现”“本地验证通过”“真实运行通过”
和“产品交付完成”分别报告。一个Mod成功、一次模型成功或一份可复现失败报告，都不等于
全部十日目标完成。能力适用范围必须绑定实际任务集、语言、模型与环境，不声称任意任务通用。

用户本轮进一步明确：**自主Planning必须修到真实自主目标选择；行为验证必须对新Patch
证明修复有效。** 不能用人辅Plan存在或旧Proposal负例验证替代这两项交付。

当前P0还须同时满足两个维度：**Mod修订正确**，以及**修订是产品Agent在既有Evidence、Plan、
工具与反馈边界内实际生成的**。Agentic Execution既是七组目标之一，也是当前P0的验收维度。

## 2. 已有底座：复用，不重新建设

| 已有实物 | 当前精确边界 | 本包如何使用 |
| --- | --- | --- |
| `aa3a72f` RgLive修复 | 单行表达式方法/字段精确单位；176相邻测试通过；不是完整C# parser | 冻结复用，除新实际失败外停止扩parser |
| FeatureSpec `fc7be8…` | 原需求及独立性义务存在；不是实现证明 | 保留原身份，用户进一步语义澄清按当前合同进入输入/验收 |
| EvidencePack `10a3fadd…` | 29项；一次真实Findings重算；不是完整Fresh或自主API发现 | 以exact ref消费，不重跑未变projection/全部Fresh |
| Plan `c760a9cc…` | 5edit/24supporting；只新增`UpdateCrosshairSize`；目标选择明确人辅 | 可用作当前Patch受审边界；不能关闭自主Planning任务 |
| 旧Patch `0a2e5c54…` | deterministic Review通过，随后人工/工程语义复核发现回归 | 保留失败来源与旧Artifact；不得继续批准/Apply |
| 28进程C#矩阵 | 旧基线/旧Proposal的7类场景，配外部doubles；不是修复验收或GTFO Runtime | 在新Patch上复用适用检查；warm诊断不升级原硬门 |
| 当前Patch请求检查 | 65821-byte请求被代理以69917需求拒绝，Patch模型/网络调用0 | A1直接解决这一精确路径问题；不称实测token溢出或实测误判 |
| 44372-byte试算 | 现有外壳下、现有1024-byte excerpt投影之后的无损往返；仅离线实验 | 作为A1设计输入，不能直接宣布生产准入已通过 |
| 既有控制与工程能力 | Fresh/API seam/Planning ownership/exact continuation/Patch工具与header correction/Review/Dry-run/Hook/lock/CI/交接和发布工具 | 保留已实现/历史通过/部分验证/未证明区别，补缺口而非重做 |

## 3. 已形成的实施选择，现在显式列出

以下D编号是本包决策索引，不是新Graph节点、Artifact类型或产品字段。

| 编号 | 已形成的选择 | 仍须证明或限制 |
| --- | --- | --- |
| D1 | 先解决生产Patch输入表示，优先可读、无损、可逆的去重/共享引用 | 44372不是最终wire结果，余量仅684；最终格式尚未冻结 |
| D2 | 保留全部义务、用户澄清、24supporting和5edit上下文及其身份 | 不以删证据、删验收或截掉editable源码换准入；不声称恢复此前已截断原文 |
| D3 | 当前Patch复用`c760a9cc…`，不先为所有supporting方法加编辑权 | 需要新修改owner时必须由证据和Planning形成新revision |
| D4 | 产品真实provider生成Mod修订，工程侧不提供正确`after_text` | 工程侧可以修平台接线、提供失败观察、做独立验证；不能冒充产品自治 |
| D5 | First Shot Match保留现有效果，进入输入、正向测试及最终语义审查 | 输入中存在不等于模型遵守；A2必须实际验证 |
| D6 | 复用28进程中的边界内测试，停止扩成Unity/武器平台 | Pop仍是原义务，必须补到现有验证或Runtime；warm仅诊断 |
| D7 | 新Evidence/Plan通过之后的首次Patch采用一次受控接受运行 | 沿现有调用预算；新first failure不自动重试、换模型或增加timeout |
| D8 | 本包必须交付自主Planning及人工语义finding后的正确上游回退 | A3/A4单列硬交付，不用当前人辅恢复或旧Review替代 |
| D9 | 以明确owner区分机械记账和语义选择，减少重复负担 | 不因值是ID就删除语义选择；slot filling是待选实现方式，不是预定新平台 |
| D10 | 固定真实任务集先于正式资格结论和默认模型路由 | 不再救已no-go的本任务4B角色；不据参数量指定默认profile |
| D11 | Trace、环境/CI、数据集准备可与无共享写的实现并行 | 同机模型/GPU/游戏、同一ArtifactStore写入及共享代码必须协调串行 |
| D12 | 只让真实依赖上的阻断影响对应动作；其余十日工作继续 | 不绕硬门，也不把helper、旧文档、临时包超限变成全项目门禁 |

## 4. 工作条目与完成条件

A编号只用于本总包跟踪。实现复用现有合同；不得由编号推导新的API、模块或Artifact名称。

### A0：执行约束和状态词校准

目的：让硬门、流程默认值、历史建议在实际执行中有区别，而非再产一份原则口号。

- 对本包触及的模型入口、Graph路由、Binding、审批/Apply、Build/Runtime及工程工具，
  记录规则来源、适用动作、实际执行者、验证位置与是否阻断；平台权限和仓库规则分开。
- 硬门保留身份/current source、合法Binding、外部披露、exact approval、真实执行与不可逆动作。
  普通平台开发不套Mod Apply审批；历史Core、冻结playbook、stale task packet不选任务。
- 测试广度、是否重跑全部Fresh、是否增加专家/场景/新工具是按证据调整的默认方式。
  辅助投影陈旧不阻断产品；工作包的“停止验证扩张”不等于停止整个产品任务。
- 只修本包实际发现的规则冲突/误用；不启动全仓所有历史入口的无界enforcement审计。

完成条件：触及的入口有可核的适用边界；后续各A项按此执行；状态表不再把登记/分析标成实现。
当前四份未提交状态文档与本包在覆盖核对后按变更归属固定版本，六份用户WIP保持独立。

### A1：生产Patch上下文表示与准入

已确认主要入口：`src/mod_agent/local_entry.py`的`_patch_agent_initial_messages`、
`src/libs/llm/agent_turn.py`；原native producer/materializer和response schema优先保持现有契约。

- 从当前exact请求证明哪些是完全相同的重复metadata；比较可读的无损共享表示。
  实验中的列式/短引用格式仅是待核实现，不能因字节最少就自动选用。
- 对原投影逐字canonical往返；保留全部editable path/hash/span/source_excerpt、义务、
  用户澄清、证据及来源信息。引用只指本消息数据，不提供额外编辑权。
- 将选定方式接入生产输入投影，保留原完整materialization数据、历史native/frozen兼容。
  用真实serializer和最终所有说明文本做零网络preflight，不能只套旧外壳加减字节。
- 然后一次真实产品接受运行，保留exact request/response、schema与source身份、usage和终态。
  实测prompt tokens、模板/消息开销、字节代理和经验估计分别记录。
- 若格式明显损害模型消费，或最终body仍不准入，冻结精确结果，再作一项有界技术决定。
  不默认提高`num_ctx`、删除要求、让另一个模型估长度或建设完整tokenizer平台。

完成条件：生产实际请求通过准入并获得真实返回/usage，输入身份可核；没有新信息丢失或权限变化。
仅离线44372、往返可恢复、代码/测试绿，均不能单独关闭此项。模型业务输出质量由A2继续验收。

### A2：由产品Agent完成当前P0并正向验证

已确认入口：`src/mod_agent/fresh_planning_continuation.py`、
`LocalOllamaInitialPatchAdapter`及现有Proposal/Review/Dry-run/审批/Apply/Build/Runtime路径。

- 以新Evidence和当前受审Plan生成一次新Patch；保留原输出和失败，不导入工程修订答案。
- 不机械使用Findings的全部edit-target hints。当前只增加`UpdateCrosshairSize`，
  `AdjustCrosshairSize`和`GetCrosshairSize`继续supporting，除非新证据证明需要修改并形成新Plan。
- 形成新的Proposal、Review、Dry-run及exact diff；源码漂移时保留生成事实但拒绝有效流转。
- 同时验收生成来源：exact请求/模型profile及digest→实际模型回合→受限工具调用→source
  observation及其hash/freshness→模型原始response→解析/materialization→Proposal/diff。
  新diff的可见代码必须能追溯到产品模型响应；身份、BOM等合法确定性补全单列，不伪装模型输出。
  验证模型输入没有工程正确`after_text`、参考实现或Harness答案；Harness仅回传已选的失败/通过观察。
- 将**新Patch**在隔离测试副本上验证：false冷启动普通尺寸保留、Recoil与First Shot Match/Inner
  独立、true行为保留、相关普通回调、协程路径。结果必须绑定新Patch/源码hash。
- Pop不能被漏掉。复用现有Harness或在必须执行的Runtime中补其专门验收；只补这一已明确缺口，
  不扩大量武器、完整Unity模拟或新的长生命周期Harness。warm true→false仍属附加诊断。
- 人工语义审查与新exact diff批准后，才按已有授权进行isolated Apply、changed Build、真实
  GTFO两值分别重启的验收；必要Repair后进行Revalidation。任何必需结果缺失均保持未完成。

完成条件：新修订消除原三条cold-start回归并保留其它原义务，必要Build/Runtime有绑定证据，
所需恢复操作完成，而且上述产品生成来源链成立。旧负例28进程、旧Dry-run通过、新Plan存在，
或工程侧编写了一份正确实现，均不计本P0完成。
阶段成功只记为“显式人辅Planning下的有界Agentic Patch execution”；自动re-evidence/replan、
自主target selection、通用compiler/test/runtime feedback仍分别等待A3/A4/A5/A7证据。
模型失败时保存原始响应与精确失败，按已有预算修正或明确停止，不由Codex静默代写收尾。
若出现精确阻断：冻结这一条case、保留未完成状态，进入独立A项，不把P0扩成整个项目。

### A3：自主Planning与最终target selection——必须实现

主要复用：`src/mod_agent/planning/implementation_plan.py`、
`src/mod_agent/bindings/resolver.py`、`src/mod_agent/workflow/graph.py`及现有Evidence/Plan合同。

- 模型基于需求、preservation义务和当前可用证据选择最终修改集合；确定性代码验证集合、
  current source、范围和绑定并生成Plan。人不再逐项输入用于证明“自主”的target IDs。
- 引用、编号、唯一性与完整性由程序负责；选择哪组源码需要修改仍是语义责任。
  不直接把Findings hints改名为Planning决定。
- 证据不足或修改位置不在当前可验证范围时，返回取证/明确blocked，而非强凑Plan。
- 旧人辅入口与历史Plan保留兼容并明确标记，不能把`planning_model_calls=0`的`c760a9cc…`
  改写为自主结果。

完成条件：产品实际运行Planning模型，原始选择→准入→Plan/Binding可追溯；至少在当前相关任务
及固定任务集中的另一项适用任务得到验证，含范围不足的正确处理。没有人为补齐目标清单的运行
才能计自主；最终稳定性声明仍由A7的全部适用任务结果限定。

### A4：语义finding→正确上游→Replan/Repair及preservation贯穿——必须实现

主要复用：单一`workflow/graph.py`、`repair/planner.py`、Evidence/Coverage、Planning和现有
Review/人工语义决定/Artifact/receipt表示。具体输入表示先核现有合同，不能默认新建通用失败类型。

- 接受的是**后续人工/工程语义finding**；原deterministic Review通过的历史保持原样。
- 语义诊断判定Evidence不足、Plan范围/集合错误、Patch实现错误、validator误报、provider/环境
  或权限问题；Graph conditional edges决定合法下一步，模型不获得最终route或写权限。
- 需要补证时进行精确检索，对旧仍有效+新增Evidence全集重算相关Findings/Coverage。
  仅在FeatureSpec/projection身份仍匹配时复用projection；需求实质改变则生成所需新revision。
- 再由A3选择目标并生成新Plan/Binding，交产品Patch、验证和后续批准；保留全部新旧输入/输出关系。
  不伪造Runtime、复制旧Fresh收据，或利用Stagger专用入口扩大其它任务范围。
- 将preservation义务连接到相关状态/调用链、修改owner和必须执行的checks；
  不能只有prompt中的一句“保持独立”，也不能仅凭模型rationale宣布义务满足。
- 接通已存在Build/Test/Runtime反馈能力在所选任务上的实际使用；区分真正产品行为失败、观察失败
  与环境失败，不用修Mod来迎合坏validator，不无限重试或自动切模型掩盖语义失败。

完成条件：一个绑定真实失败的产品运行，从finding进入正确上游、产生新证据/Plan/修订并重新验证，
不依赖Codex手工逐阶段拼接；诊断、route与attempt budget均有记录。需要真实Build/Runtime失败
样本时从既有可复现记录或真实任务取得，不能人为制造失败冒充产品修复证据。

### A5：生产Evidence/RAG与model-owned-field责任调整

复用已有source/API工具、`requirement_coverage_provider.py`、`requirement_coverage.py`和Planning。

- 在API-dependent真实任务中让产品模型选择查询/工具，形成可用source/API Evidence。
  人辅查询模式继续明确标记；工具存在或一次失败调用不能关闭自主发现任务。
- 对Projection、Findings、Planning、Patch触及字段给出真实责任表：固定ID生成、合法枚举、
  完整性/去重和已确定post-change延后归系统；义务分组、证据选择和修改集合归模型语义。
- 对已暴露的纯机械重复负担实施局部改进并验证；不为减少字段而删除有语义的关联选择。
  slot filling是否采用由实际错误/成本决定，不预建全stage万能schema或第二模型记账器。
- API Evidence需能追踪到具体判断/修改理由及正确API使用和相应验证；只进入包、Plan或prompt
  不算语义影响，模型自报和单纯ref非空也不够。
- 将context admission、token telemetry、必要的请求可靠性一起验证；条件需要时才调整检索、
  rerank、fallback等手段，不因名称熟悉而重新建设。

完成条件：固定适用任务中有自主查证的成功消费链和缺证正确停止；字段责任改进有测试及实际运行
依据；API使用的主张与真实源/验证对应，效果与成本按冻结输入报告。

### A6：真实Trace/Lineage/Langfuse交付

复用`src/observability/non_authoritative_projection_v2_langfuse_exporter.py`等既有投影和receipt。

- 接真实生产sink、独立invocation与关联session、短CLI退出flush，保留失败也可查的记录。
- 将需求、Evidence、Plan、模型/工具回合、Patch、Review、批准、Build、Runtime和评测结果以
  当前内部身份关联；sink只消费，不能反向决定产品状态、权限或路由。
- tokens、耗时、调用、修正、终态与评分都有明确来源；导出失败不改写产品事实。

完成条件：从观测界面/查询可回查一次真实端到端或明确失败运行，核对关联、flush和score；
只通过injected transport测试、本地JSON存在或Trace页面有条目不算交付。

### A7：固定多任务Eval→模型资格→角色路由

复用现有evaluator接口、观测评测代码、`src/mod_agent/model_admission.py`和provider adapters。

- A7.1先冻结3–5个真实任务及各自source/FeatureSpec/输入、阶段适用性、成功标准和失败分母，
  覆盖配置、多文件行为、API-dependent任务及有真实依据的Repair路径；28进程不是28任务。
- 区分旧RAG小集、Core历史Case定义与新Patch任务集，不拿其中一个代替所有Eval；
  调参数据与留出验证分开，不能模型生成Golden或事后改任务/标准抹平失败。
- A7.2记录Evidence、Patch/Review、Build/Runtime、Repair/Revalidation、调用、tools、tokens、
  延迟和停止结果。没有执行的适用阶段明确未证明，不从统计分母消失。
- A7.3基于可比结果形成各角色可用profile，落地实际role→profile resolver并验收真实调用。
  保留profile/模型digest/编码版本/参数/环境；不把4B本任务no-go推广到所有角色，也不将Sol人辅
  对照计为本地自主。基础设施fallback仅在明确触发和独立资格下使用。

完成条件：任务集、实际结果矩阵和角色选择均可复核；resolver实际选用通过相应资格的profile。
手工指定模型、单例成功、benchmark名字或参数量都不等于此项完成。

### A8：可重复环境、CI与Release

复用`uv.lock`、`.github/workflows/ci.yml`、`scripts/setup_codex_local_environment.py`、
已有Hook/交接和release工具；不再把文件存在列成待新建。

- 在声明依赖的干净环境重建和运行适用检查，取得同commit的hosted CI证据及实际Build可复现性。
  游戏依赖/本机专属验证与CI测试范围分别标明，不能互相冒充。
- 核已有Hook信任/生命周期和工程认知Fresh/API/continuation投影的实际缺口；只修恢复/定位
  必需部分，辅助工具不成为产品Gate或新的认知数据库。
- 交付release manifest、README结果/限制、演示与简历/面试材料。发布器不得仅凭verified ref
  加同SHA就宣称任意自然语言claim已demonstrated；逐条匹配实际证据范围，未证明确标。
- 远端发布、凭据使用和新外部披露按既有授权处理，不能因“需要CI”直接推定可以公开全部本地资产。

完成条件：真实环境/CI/构建证据与交付文件可重现、可查询、口径一致；文档/脚本存在不算这些运行通过。

## 5. 七组目标总体依赖（本次两小时安排以第0节为准）

1. A0仅校准当前执行边界，立即进入A1；不先做全仓流程审计。
2. A1通过→A2产品Patch及正向行为验证→具体diff审查/批准→Apply/Build/Runtime。
3. A2成功或遇到不能当轮消除的精确阻断，转入A3/A4/A5；自主Planning仍必须交付，
   不能因当前人辅Plan可用而延期出十日目标。A3独立实现与本地验证可提前并行；共享集成和真实
   模型运行遵守第0节的资源/时间边界。
4. A3与A4协同：先让模型真实选择目标，再证明finding能自动回正确上游；A5提供自主取证与
   语义消费支撑。改变输入后按新revision重新验证，不重写历史结果。
5. A7.1的数据集定义、A6的只读sink/接口准备、A8的现有环境/CI核查可提前并行。
   正式qualification在相关实现冻结后运行；resolver随后按结果接入。
6. 同一文件或共享Graph/local_entry改动由一个集成writer安排；同机Ollama/GPU/游戏和同一
   ArtifactStore写入串行。没有共享写的测试、只读核验、环境准备可用有界工程子智能体。
7. 真实模型/Actual只用于绑定的接受性运行；固定输入和预算后执行。新first failure先做最小
   可复現诊断与通用修复，再进入下一次明确的接受运行，不把异常变成无限自动重试。

本包不重启十日计时、不沿用已不足以容纳新目标的旧Core预算。精确剩余天数和运行窗口未核定前，
不编造新的开始/截止日期；若资源与十日目标冲突，明确向用户报告取舍，不能静默降低交付范围。

## 6. 12次输入逐条覆盖与最新补充

| 输入（本页原文时间） | 本包对应条目 | 交付口径 |
| --- | --- | --- |
| 1，14:33:40：First Shot Match保留现有效果 | D5、A2/A4 | 输入、正向行为和语义审查都要覆盖 |
| 2，14:33:57：由产品Agent修Mod | D4、A2 | 必须真实provider生成；工程不导入正确答案 |
| 3，14:35:06截图：P0/旧Core/完整目标关系 | §1、D12、§5 | 旧Core历史化；复用已有成果；case不是总目标 |
| 4，14:40:04：权威入口、既有合同、七组与边界 | A0、A1–A8 | 全部七组仍在十日范围，权限与证据各守边界 |
| 5，14:58:09：扩范围的合法恢复顺序 | A2/A4 | 精确Evidence全集→新Coverage→新Plan/Binding→Patch；不是先扩EditAuthority |
| 6，15:04:58：自动回正确上游尚未产品化 | A4 | 必须真实产品闭环，不以Codex编排算完成 |
| 7，15:09:44：preservation/state/owner/checks及六类缺口 | A2–A8 | 正向修复、自动重规划、跨任务与交付分别验收 |
| 8，15:26:43：blocker是否限制发挥 | A0/A1、D12 | 限定阻断的依赖路径，继续独立工作 |
| 9，15:26:43：完整约束来源与自由执行 | A0、§5 | 检查触及入口的真实规则，区分平台/产品/工程层，不只留原则口号 |
| 10，15:30:02：Owner表和机械记账 | A3/A5 | 保留语义关联选择，减少固定记账；自主Planning有实际结果 |
| 11，15:40:32截图：能力差距评价 | A2–A8 | 差距变成可验证交付项，状态校准不冒充新能力 |
| 12，15:41:45：三档约束、停止扩parser/Harness、后续主线 | A0/A1/A2/A4、§5 | 本轮只处理必要输入/修复；闭环产品化在既有Graph中完成 |
| 最新补充：新Plan存在≠自主Planning通过 | A3、A7 | 人辅0模型记录不能关闭任务；必须产生真实自主结果 |
| 最新补充：旧行为负例≠新修复验证 | A2 | 新Patch绑定的新回归、Pop及必要Runtime结果才算 |
| 最新补充：44372试算≠生产阻断关闭 | A1 | 最终serializer/preflight、实际发送/返回与usage均须验证 |
| 最新补充：登记覆盖≠交付覆盖 | 全包、§1 | 完成词分别绑定代码、测试、真实运行、交付证据 |
| 最新补充：P0也必须验收Agentic Execution | D4、A2 | 代码来源链和Mod正确性同时通过；当前人辅Planning模式不得伪装全链自治 |

七组映射：端到端=A2/A4；Evidence/RAG=A3/A5；Agentic=A2/A3/A4/A5；
Trace=A6；资格/路由=A7；多任务Eval=A7；环境/CI/Release=A8。

## 7. 尚未决定的技术点与外部输入

- A1最终编码格式及所需余量尚未选定；无损往返不证明模型消费质量，也不证明后续turn必过。
- A4人工语义finding的现有合同落点、具体route接缝需要读取当前实现后定；不预造新Artifact类型。
- A7具体3–5任务及可复现真实Build/Runtime失败checkpoint尚需冻结；不存在的样本不得补造。
- 真实Langfuse目的地/接入条件、远端CI状态、可重建依赖和游戏运行窗口须从当前环境核实。
  缺凭据或批准时只阻断对应外部动作，准备和其他独立能力继续。
- 二次覆盖核对后才把本包标成选定实施范围；包本身不代替每次新diff批准、外部披露或游戏授权。

没有内部默认决定采用新Agent框架、第二StateGraph、认知数据库、万能schema、全局自动fallback、
大量新Parser/Unity模拟、重新解冻playbook或人工代写Mod。若未来真实问题要求改变现有合同，
先说明旧合同无法表达的具体事实及复用为何不足，按正常版本化决定处理。
