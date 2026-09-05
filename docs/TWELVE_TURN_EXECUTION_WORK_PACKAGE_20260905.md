# 十二轮要求与完整十日目标：范围及验收覆盖参考

状态：范围与验收参考，不授予任何执行权限，也不是当前队列。

本文保留用户十二轮要求与七组十日目标之间的映射。文件名为兼容已有链接保留；
不得将本文当成可执行启动指令、当前授权凭证、模型重试许可或长期状态账本。
实际范围与授权来自当前任务可核验的用户消息；后续用户要求可改变范围、暂停或替换工作，
无需使用特定取消措辞。文档中的历史引用不能自动授权另一个任务或未来运行。

当前执行只由[Implementation Queue 当前块](IMPLEMENTATION_QUEUE.md)选择；
本轮的精确输入、发送责任和停止条件见[短执行卡](PATCH_ACCEPTANCE_SPRINT_CARD_20260905.md)。
执行卡同样只是有有效期的输入快照，不代替用户消息或产品审批。
历史两小时安排、实际启动时间、提交及运行结果集中保存在
[reconciliation §12](audits/PATCH_AGENT_PROGRESS_RECONCILIATION_20260905.md#12-两小时执行窗口)；
历史窗口不可重放。本文不保存动态HEAD、当前Artifact计数或“已经授权执行”的状态。

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

## 2. 复用已有底座

复用已存在的Fresh、API Evidence接缝、Planning ownership、exact continuation、
Patch源码工具与header correction、ProposalReview、Dry-run、Hook、依赖锁、CI、
交接和release工具。它们的当前实现、历史运行和未证明范围只在当前源码及
[reconciliation](audits/PATCH_AGENT_PROGRESS_RECONCILIATION_20260905.md)核对，
不因本文列出名称而重新建设或宣布通过。

准确区分原始失败、后续修订和当前输入revision。旧有效Evidence可以复用，
完整Findings/Coverage须绑定当前全集；人辅Plan不改写为自主Plan，旧负例不能证明新修复。
当前编辑/supporting数量由选定Plan决定，不在本范围参考中冻结成永久数字。

## 3. 共同执行原则（原A0，无独立完成门）

- 发现真实规则冲突时在对应入口修正；没有冲突时不开展单独的元治理审计。
- 源码身份、有效Evidence/Binding、独立披露、exact approval和真实结果是硬边界；
  测试广度、是否完整Fresh、协作分工和文档更新方式是可调整执行默认值。
- 模型负责语义分组、证据关系、修改集合、代码和失败诊断；确定性代码负责ID、路径、
  hash、span、去重、完整性、预算、状态与权限。人工批准写入不等于形式化证明。
- Artifact保存完整业务信息；每次模型调用只消费有明确依赖的有限上下文。
  减少首轮重复不意味着删除Artifact或丢失行为义务；按需读取必须有真实可用的工具接缝。
- 只让实际依赖上的阻断停止对应动作；保留失败事实，继续独立且已获授权的工作。
- 冻结playbook、stale task packet、历史Core/Stretch和本文件均不选择当前任务。
- 不新建第二StateGraph、认知数据库或长期账本；改动现有合同须先证明当前数据无法正确表示。
- 未来diff需要针对其真实hash的新语义审查和exact approval。时间窗口、历史授权文字、
  当前方案或泛称“所有权限”都不能预先批准尚未产生的Mod字节。

## 4. 工作条目与完成条件

A编号只用于本总包跟踪。实现复用现有合同；不得由编号推导新的API、模块或Artifact名称。

### A0：共同原则

A0仅指第3节共同原则，不是待实施工作项，不设独立验收、审计阶段或前置门。
发现问题才在实际触及的入口处理；其余工作直接推进选定能力。

### A1：生产Patch上下文表示与准入（仅准备，不发送）

- 接入现有context compiler与真实serializer，保留完整Feature语义、用户澄清、exact edit
  bindings、必要supporting和失败边界；原Artifact完整保留。
- 确定性无损验证与模型消费验证分开。可逆只证明数据未额外丢失；模型是否理解binding、
  source和行为约束，要在A2同一次接受运行中取证，不再由A1单独调用模型。
- 分别保存原语义输入、native prepared messages、压缩后initial messages、编码版本、
  实际provider body及response身份，不把多个层次混称一个model_input_sha256。
  实际字段名称以当前源码/receipt为准，本文不另造schema。
- 首轮仅刚好通过不是稳定性证明。对工具返回、final及允许的correction使用已有测试/
  离线重放验证构造与预算；依赖未来模型响应的实际请求，在A2发送前逐轮核验并记录。
- supporting可以按目录、摘要、refs及有限内容进入首轮，但必须先证明完整内容可通过
  当前工具合法按需读取。现有工具未覆盖的材料不能先删再声称系统仍能取回。
- context admission属于确定性系统。复用真实模型测量时验证输入、模型/profile与收据身份，
  明确估计和精确tokenizer的区别；不通过删语义、静默增context或另一个模型估长度绕过问题。

完成条件：形成可核验的exact请求与零网络preflight结果，停止在发送前。
A2的同一次真实返回可作为A1生产消费的接受证据，但不授权A1拥有第二次模型运行。

### A2：唯一Patch接受运行责任与修复验收

A2负责消费A1的选定请求、调用现有bounded Patch Agent、保存所有实际响应及生成来源。
**一次接受运行可能包含多个工具/模型回合；不是“只发一次HTTP”。**
本次选定路径以同一个现有PatchAgentLoopPolicy给continuation、adapter、tool loop及
correction提供总预算，不能在调用方另配一个互相冲突的数值。具体预算和attempt身份只写
当前执行卡及真实receipt；A1、并行审查或重读文档均不能再次消费它。

- 产品Agent自行读取允许源码并生成代码；禁止Codex代写正确after_text、导入参考实现、
  或把Harness实现答案放入输入。Harness只返回输入、实际结果及通过/失败观察。
- 保存压缩后实际输入、每轮请求/响应、模型身份、工具观察、修正、usage和终止事实。
  发送前拒绝、真实HTTP调用、模型返回、生成changes与正式Proposal分别记录。
- 运行ProposalReview、无写Dry-run和适用的既有行为回归；正向验收必须绑定新生成内容。
  原始负例、合法JSON和模型自述均不证明修复通过。
- preserved First Shot/Follow Recoil/Pop、原始ref参数及true路径按当前Feature边界验收。
  warm诊断不自动升级为重启任务硬门，不扩成通用Unity/武器验证平台。
- 新diff → 当前人工语义审查 → 针对该hash的新exact approval → isolated Apply →
  changed Build → 单独范围明确的游戏操作授权 → Runtime。各阶段以真实结果为准。
- 模型失败保留原响应；在已明确预算内合法修正或停止。一个失败不会自动授权另一次接受运行、
  切模型、改变prompt/schema、扩大binding或写入Mod。

完成条件：生成来源与当前行为义务分别通过，并明确Proposal、Review、Dry-run、
语义审查、批准、Apply、Build和Runtime实际到达哪一层。未完成阶段保持未完成。
这是完整十日结果定义，不承诺一张两小时执行卡完成所有阶段。

### A3：自主Planning与最终target selection（十日验收）

主要复用：`src/mod_agent/planning/implementation_plan.py`、
`src/mod_agent/bindings/resolver.py`、`src/mod_agent/workflow/graph.py`及现有Evidence/Plan合同。

- 模型基于需求、preservation义务和当前可用证据选择最终修改集合；确定性代码验证集合、
  current source、范围和绑定并生成Plan。人不再逐项输入用于证明“自主”的target IDs。
- 引用、编号、唯一性与完整性由程序负责；选择哪组源码需要修改仍是语义责任。
  不直接把Findings hints改名为Planning决定。
- 证据不足或修改位置不在当前可验证范围时，返回取证/明确blocked，而非强凑Plan。
- 旧人辅入口与历史Plan保留兼容并明确标记，不能把`planning_model_calls=0`的`c760a9cc…`
  改写为自主结果。

完成条件：产品实际运行Planning模型，原始选择→准入→Plan/Binding可追溯；须通过独立语义评审或下游行为验证，符合FeatureSpec preservation义务。
任务集至少覆盖一个正确选择任务、一个缺证时正确停止任务，以及一个合法目标较多但应只选子集的任务。没有人为补齐目标清单的运行
才能计自主；最终稳定性声明仍由A7的全部适用任务结果限定。

### A4：先产品化已发生的人类语义finding回上游

首版只处理已经出现的真实类别：

```text
后续人工/工程语义finding
→ 判断需要补Evidence
→ 精确取证与旧有效Evidence合并
→ 完整Findings/Coverage
→ 自主Planning与新Plan/Binding
→ 产品Patch
→ 同一行为反例Revalidation
```

复用现有Artifact、人工语义记录、Evidence、Coverage、Planning及单一Graph。
原deterministic Review通过的历史保留，不伪造其曾检测到后续语义问题。
需求投影仍匹配时复用，需求改变则产生必要revision；不复制旧模型执行收据。

把preservation义务接到相关状态/调用链、修改owner和必要checks，不能只加prompt句子。
条件边决定路线，模型不获得最终route/写权限。Evidence不足时明确停止，不先扩EditAuthority。

完成条件：绑定真实failure的产品运行自动走完上述已有合同链并重验，不依赖Codex逐段拼接。
Provider、环境、validator、Build/Test/Runtime的其他故障继续使用各自现有路径；
它们仍属于十日目标，但不在此首版中统一重构成通用故障平台。

### A5：生产Evidence/RAG的三个独立结果

- **A5a 自主API查询**：产品模型选择查询/工具，形成可用source/API Evidence；保留freshness、
  coverage与refs验证。人辅查询与工具仅存在不算自主发现通过。
- **A5b API语义消费**：一次下游判断/修改真实使用API事实，并有对应source及行为/构建验证。
  结构进入EvidencePack、Plan、prompt或模型自报均不足以证明语义影响。
- **A5c 机械字段Owner**：只处理已观察到的重复负担。稳定ID、合法性、完整性/去重和固定延后归
  确定性层；语义分组、证据选择和修改集合仍归模型。Slot filling是可选手段，不预建万能schema。

Context compiler/admission归A1，Planning归A3，语义回上游归A4，模型资格/路由归A7，
不在A5重复修改相同入口或拥有第二次模型调用。

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

## 5. 十日结果依赖，不是第二份执行队列

- A1准备由A2消费；A2经真实行为验证和新exact审批后才进入Apply/Build/Runtime。
- A3提供模型目标选择，A4消费已发生的语义finding，A5提供自主取证与API语义事实。
- A7先固定任务与分母再作资格/路由结论，A6单向消费真实结果，A8验证环境及交付。
- 两小时执行卡只列当次选定的A1/A2和已选择的独立工作，不把A3–A8全部写成两小时硬交付。
  独立且有条件的工作可以提前执行；这不将任何一组默认推迟到十日以后。
- 外部Langfuse、hosted CI、远端发布及游戏操作需要对应目标、连接条件和用户授权；
  缺项仅阻断该外部动作。本地环境重建不因此一并变成不可执行。
- 实际任务、顺序、文件owner和剩余时间只在当前Queue及短执行卡核对；不因本文的编号启动工作。

本文不重启十日计时，不用旧Core/Stretch降低目标，也不声称十日内已实现任意故障泛化。
时间与目标冲突时报告真实取舍，不通过改变完成词或隐藏未完成阶段收口。

## 6. 12次输入逐条覆盖与最新补充

| 输入（本页原文时间） | 本文对应条目 | 交付口径 |
| --- | --- | --- |
| 1，14:33:40：First Shot Match保留现有效果 | A2/A4 | 输入、正向行为和语义审查都要覆盖 |
| 2，14:33:57：由产品Agent修Mod | A2 | 必须真实provider生成；工程不导入正确答案 |
| 3，14:35:06截图：P0/旧Core/完整目标关系 | §1、§5 | 旧Core历史化；复用已有成果；case不是总目标 |
| 4，14:40:04：权威入口、既有合同、七组与边界 | A0、A1–A8 | 全部七组仍在十日范围，权限与证据各守边界 |
| 5，14:58:09：扩范围的合法恢复顺序 | A2/A4 | 精确Evidence全集→新Coverage→新Plan/Binding→Patch；不是先扩EditAuthority |
| 6，15:04:58：自动回正确上游尚未产品化 | A4 | 必须真实产品闭环，不以Codex编排算完成 |
| 7，15:09:44：preservation/state/owner/checks及六类缺口 | A2–A8 | 正向修复、自动重规划、跨任务与交付分别验收 |
| 8，15:26:43：blocker是否限制发挥 | A0/A1 | 限定阻断的依赖路径，继续独立工作 |
| 9，15:26:43：完整约束来源与自由执行 | A0、§5 | 检查触及入口的真实规则，区分平台/产品/工程层，不只留原则口号 |
| 10，15:30:02：Owner表和机械记账 | A3/A5 | 保留语义关联选择，减少固定记账；自主Planning有实际结果 |
| 11，15:40:32截图：能力差距评价 | A2–A8 | 差距变成可验证交付项，状态校准不冒充新能力 |
| 12，15:41:45：三档约束、停止扩parser/Harness、后续主线 | A0/A1/A2/A4、§5 | 本轮只处理必要输入/修复；闭环产品化在既有Graph中完成 |
| 最新补充：新Plan存在≠自主Planning通过 | A3、A7 | 人辅0模型记录不能关闭任务；必须产生真实自主结果 |
| 最新补充：旧行为负例≠新修复验证 | A2 | 新Patch绑定的新回归、Pop及必要Runtime结果才算 |
| 最新补充：44372试算≠生产阻断关闭 | A1 | 最终serializer/preflight、实际发送/返回与usage均须验证 |
| 最新补充：登记覆盖≠交付覆盖 | 全包、§1 | 完成词分别绑定代码、测试、真实运行、交付证据 |
| 最新补充：P0也必须验收Agentic Execution | A2 | 代码来源链和Mod正确性同时通过；当前人辅Planning模式不得伪装全链自治 |

七组映射：端到端=A2/A4；Evidence/RAG=A3/A5；Agentic=A2/A3/A4/A5；
Trace=A6；资格/路由=A7；多任务Eval=A7；环境/CI/Release=A8。

## 7. 技术输入与外部条件的验证要求

- A1编码和每轮预算须绑定选定版本验证；无损往返不证明模型消费质量，也不证明后续turn必过。
- A4人工语义finding的现有合同落点、具体route接缝需要读取当前实现后定；不预造新Artifact类型。
- A7具体3–5任务及可复现真实Build/Runtime失败checkpoint尚需冻结；不存在的样本不得补造。
- 真实Langfuse目的地/接入条件、远端CI状态、可重建依赖和游戏运行窗口须从当前环境核实。
  缺凭据或批准时只阻断对应外部动作，准备和其他独立能力继续。
- 本文始终只是范围参考；选定实施项来自当前Queue与用户请求，不能由覆盖核对自动产生授权。

没有内部默认决定采用新Agent框架、第二StateGraph、认知数据库、万能schema、全局自动fallback、
大量新Parser/Unity模拟、重新解冻playbook或人工代写Mod。若未来真实问题要求改变现有合同，
先说明旧合同无法表达的具体事实及复用为何不足，按正常版本化决定处理。
