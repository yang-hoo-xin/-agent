# Patch 进度与整页工作核对（2026-09-05 建档）

用途：集中保存目标页工作证据、范围变化及未完成项，供接手后继续工作。
本文不是新的产品状态数据库、审批、验证器或第二份排程。待办优先级只在
[Implementation Queue](../IMPLEMENTATION_QUEUE.md) 维护；本文保存本次核对时的结果。

## 0. 最新状态快照

**两小时并行窗口检查点（0.30）：P0仍未修好；014两次原矩阵仍33/36，015本地27B在第二请求超时。**
Langfuse美区项目已真实查回四次自有任务的54条历史记录和1条行为分数；额外三次历史最初被审核拦住，用户补充明确授权后完成。
DSH需求准备已通过真实页面与原ArtifactStore验收，并新增按精确运行查看diff的只读入口。
Eval可直接汇总一个任务四次独立对照；API按需读取保留来源语义；新Plan领域factory通过原矩阵兼容验收。
以上均不构成First Shot修复、完整自动规划、整Mod Build或GTFO Runtime。此前各节为各自历史检查点。

**真实验收最新（0.29）：冻结90cfc27，Max独立5次请求完成编译反馈修订与格式纠正；最终真实编译成功、原15项检查全过。**
原Proposal/Review/Dry-run绑定通过检查的同一版字节，停止在exact diff审批前。
这是OwnedConfigService、人辅Evidence/Plan下的一次成功；没有Apply、正式Build或游戏Runtime，
AccurateCrosshair仍未修好，不推广为自主Planning或跨任务资格。旧节的“尚未验收”保留历史时点。

**提交闭环最新（0.28）：同一Patch worker现在区分工具、合规提交、完整格式错误和不完整响应；首次及行为修订均可在原余额内纠正格式。**
公开入口的两条五回合离线路径经过原Review/Dry-run；使用预设HTTP响应与合成marker检查，
没有新模型请求、真实编译或原15项验收。请求正文与提交轨迹进入原账本/查询；保存请求不等于发送。
Max修后真实验收尚未执行；当前Mod仍未修好。0.27中的未实现描述保留为该提交的历史边界。

**输出策略最新（0.27）：外部Patch入口改为显式profile策略；默认旧行为/哈希不变，发送层不再无条件强加JSON。**
实际请求模式按每请求记录。纯工具回合与已有格式声明保留；严格Patch校验不放宽。
离线组合验证已通过；尚无修后Max实际验收，也未实现格式失败自动回同worker。

**模型首筛最新（0.26）：同一自有任务真实运行30B、云端3.6 Plus和3.8 Max，均未形成可交付结果，但失败层不同。**
30B为编译失败后原样修订；Plus为编译失败后请求上游；Max为说明文字加JSON，在结构化解析前停止。
可以统计为一个任务、三种配置、三次独立首筛、零次任务完成；三组都未执行15项行为矩阵，
不能记为行为通过率0/15，也不把不同阶段失败合成单一根因或推导模型排名。

**DSH最新（0.25）：真实官方宿主已执行原后端查询，重启后页面显示013的未完成结果。**
只读命令与原session记录已连通；没有模型调用或产品执行。任务提交、审批、执行恢复和交付仍未完成。

**近真实对照输入（0.24）：独立自有C#配置任务已准备，真实编译/磁盘/进程基线可运行。**
原基线15项中7项新增要求失败、8项保留行为通过；后续3组模型实发见0.26，均未产生有效交付。

**外部模型接缝（0.23）：外部千问复用原Patch/Repair worker，解析失败前也保留原HTTP响应。**
后续Plus和Max均已在用户授权的自有源码范围实发并收到响应（0.26）；接口可调用，不等于修订质量合格。

**A7最新（0.22）：3个不同Feature任务已冻结，当前代码下3/3输入准入通过；全部真实模型成绩仍为未运行。**
两个新增任务的真实C#基线验证已执行，原P0保留36项检查；不把输入准入、基线缺陷或离线脚本响应计为模型成功。

**A6最新（0.21）：原Patch查询已接上历史元数据OTLP导出与查回代码，评分必须绑定被测代码和精确矩阵。**
65项相关回归通过；没有发送Langfuse请求，目标服务尚未配置，不能声称真实sink、完整时序或生产观测已交付。

**A5最新（0.20）：API来源身份传播`ceeb1b6`已提交；第一次真实Findings调用返回后因API被列为编辑目标遭拒。**
首失败是`REQUIREMENT_COVERAGE_EDIT_TARGET_IDENTITY_INVALID`，不是后续一次调用预算阻止修正callback的异常。
原响应与请求保留；本次提交中的schema修复复用原校验条件区分“可引用API”和“合法target_source编辑提示”，
115项相关checkpoint通过。没有第二次真实模型发送，九项全support不能据此认可，API正确语义消费仍未证明。
这条A5支线没有Planning/Patch/Mod矩阵执行，不改变013作为最新P0真实记录的定位。

**工具语义收敛已完成离线验收（0.19）：读取与重评用途分开，Graph按当前配置声明保存停止／重评到Plan／重评后继续／provider未配置。**
同一已登记引用仍可因支持关系或覆盖问题请求Evidence重评，没有“已可读就禁止上游”的规则。
该工具语义收敛轮没有新增真实模型、preview或Mod修改；013仍是最新P0真实记录，A5 Findings另见0.20；动作选择质量和有效修订仍未证明。

**2026-09-07最新：整链适配`d6eda97`与指导去重`925790d`已提交。013真实2次调用后主动请求Evidence上游，没有生成代码或运行矩阵。**
首轮5次读取为3新窗口＋2复用，内容进入第二实际请求；模型随后选择`request_patch_upstream`。
三个所列引用都可在原worker读取，离线测算1新窗口/5,308字节，小于当时2窗口/5,839字节余额。
因此请求结构合法，但必要性未证明；不是工具隐藏、额度耗尽，也不是又一次33/36的新测试结果。
本轮不追加真实尝试；工程与真实行为结论分别见0.16及0.18。
不同代码产生的新失败会绑定到实际被测版本；可选Evidence/Planning回流后，新Plan重新装配worker，
经过原行为检查、Proposal、Review和Dry-run。模型、读取及观察字节不重置；原报告不覆盖，旧审批不继承。
新增上游路径为一个有界周期，既有同Plan路径不强迫读取或重新规划。资格路由与A4配置组合仍未支持。
当前case验证器固定c760，因此013未配置真实A4自动续接，不冒充模型已走完上游链。
本轮工程命令、兼容缺陷及限制见0.16；历史窗口中的“当前”不覆盖本快照。

**更新时间：2026-09-06；Patch覆盖复用：`54dff43`；Graph回流：`aa4e00f`／`b792c41`；资格路由：`7b82698`。本节为当前读入口，旧章节保留当时事实。**

**此前009：修正验收器后，5次真实模型调用和修订/重验完整执行，但两份代码仍相同、两次33/36。**
源代码覆盖复用和可见C1引用都在实际请求中成立，未出现008的误拒绝；总11次工具执行为3新窗口＋8复用。
失败后模型只重读已见001/005，未选择新源码；原三项First Shot失败未消除。
独立27B对照010已执行：首轮工具选择有效，第二请求600秒超时，没有代码/矩阵；不能判为语义修复失败。
A4上游回流与A7资格路由均已整合；真实Planning002生成六目标但语义needs_evidence，003反馈后仅选Config三目标、仍错误声称覆盖Loader/Spread。
004内联路径后文件/ID说明正确，恢复同002六目标，但两处新增编辑必要性仍未证明；新Plan均未用于Patch。
当前没有通过原行为矩阵的新Mod修订；新Plan、源码工具往返和平台检查不替代这个结果。
具体009事实见第0.13节；不把本次结果推广为任意模型或跨任务结论。

**008历史结果：源码覆盖复用已真实生效，但验收脚本在第四请求发送前误拒绝，真实修订当时未完成。**
固定54dff43、同Qwen/006+r6/c760；3次真实模型发送与返回，9次工具执行为3个新窗口＋6次复用。
唯一代码仍等于旧失败版本，原矩阵33/36。第四请求保留完整C1、B0、F1与原义务，但旧auditor硬取
紧邻前一消息（实际为tool），不识别earlier-visible Patch引用，触发RuntimeError。账本4是客户端调用次数，
不能冒充4次真实模型推理。没有中途修改执行器或追加实发，没有新Proposal/Review/Dry-run/Apply/Build/Runtime。
实现、回归、请求身份及具体失败见第0.12节；007及更早结果不回写。

**007历史结果：系统自动绑定跨attempt补测并完成真实行为反馈/修订/重验，但Qwen仍未修好First Shot。**
007固定6d38184，通过公开CLI从006与r6两条记录自动解析正式祖先、当前C1和F1；4次真实模型调用、0回放。
两次原矩阵均33/36；两份代码与旧失败版本相同。失败后模型请求5个supporting读取，被剩余1次读取预算拒绝；
下一轮仍可读1次，但模型直接返回旧代码。不能把已申请但未执行的这5处记成新查证，也不能把本次失败全部归因于模型。
自动绑定机制与实际回流已实现，当前profile下任务仍失败；详见第0.10节。

**006历史检查点：005的五处读取阻断已通过公开CLI的离线链和006真实首批读取验证。**
该轮显式配置总6次读取，为失败后保留1次；模型上限5、观察上限32,768、源码窗口64行和编辑范围均不变。
完全相同的源码全文使用可还原引用，当前case五份观察从23,912降至16,234字节。源码与语义约束未裁剪。
006使用固定af36b5d和公开CLI执行，2次真实模型调用、5次实际源码读取、0回放。
模型完整输出与旧失败版本相同；验证器因261字符输出路径失败，原006没有完成矩阵。
随后仅更换独立验证输出目录，用保留的006代码运行原40进程36检查：33通过、原First Shot三项失败。
这是独立无模型复验，不回写006，也没有触发真实模型的第二次查证/修订；完整证据见第0.9节。

**此前公开入口交付阶段：continue-fresh-patch已装配已有Repair引用、行为验证器与共享worker策略，并通过真实CLI路径的离线验收。**
测试仅替换底层HTTP transport，保留CLI解析、配置加载、Adapter、序列化、worker、Graph、Review和Dry-run。
合成项目实际经历“读→生成→检查失败→再读→修订→Review/Dry-run”，该轮真实模型调用0，AccurateCrosshair未修复。
第0.7节中的公开CLI缺口是本次修复前的事实；新接口、准备文件及验证范围见第0.8节。

**此前审查落实（公开CLI接线前）：补齐本次输出Artifact查询，响应引用损坏时降级来源展示，并拒绝明确声明执行未完成的passed报告。**
该轮新增真实模型调用0；在该时点005是最后一次真实运行，执行时固定6411f01，不能归给当时的新提交。
此前“生产路径验证”准确指注入行为callback后调用生产Adapter/Graph的Python API路径；
当时公开`continue-fresh-patch` CLI尚未接入同等Repair输入、行为callback和恢复策略，见第0.7节历史核对。

**此前e892e3e／6411f01检查点：失败后查证预算、实际文件字节比较、保守验证复用和单 Store 查询已提交并通过离线验证。**
生产 Adapter/Graph 的合成项目实际执行“读取→生成→检查失败→再次读取→修订→重验通过”；
这证明该执行分支和剩余额度可用，未证明 AccurateCrosshair 已修好。
旧公共查询开始消费新账本的执行/拒绝/重放/复用语义；旧 ArtifactStore 仍保留权威职责。
这不是 RAG Trace 全面迁移、多任务 Eval 或生产级全链覆盖。详细新证据见第0.6节。

**历史独立真实验收005：固定6411f01，2次新调用、0回放；模型两次均请求5处，
超过初始阶段可用4处（总5处中为失败后保留1处），终止于`PATCH_AGENT_REPEATED_TOOL_BATCH`。**
反馈确实进入第二份实际请求；10条工具请求均未执行，未生成代码、未运行行为矩阵。
这是预算交互后的重复动作停止，不是新的First Shot修复失败矩阵；原3项失败仍只有此前证据。

**上一轮真实运行（mature_repair_001–004）的结论，保留如下：**

**结论：共享 Patch/行为 Repair 的执行能力已增强并实际运行；本轮未修好 First Shot。**
准确定位为**包含执行器修复与严格接续的开发性验证**，不是固定一个版本从头到尾的无中断验收。
不能把本轮全部过程归给最终HEAD，也不能把最终失败单独归因于模型或全部归因于执行器。
Qwen在工具预算反馈后由请求5处改选2处；修正执行ID记账后，两处源码实际返回了模型。
随后模型真实生成和修订各一次，但两份输出的5项`after_text`都与旧父版本完全相同。
两次原行为矩阵均33/36，仍是Match两项和Inner一项失败；Recoil通过。
因此不能把“收到新模型响应”写成“产生更正确的代码”。
最后一次修订只有1个模型轮次，实际可用工具仅`request_patch_upstream`，没有源码读取工具；
模型仍能看到此前两条完整源码观察，但本轮没有证明“新草稿失败后再次查源码再修订”这一完整过程。
[跨版本与源码返回核验](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/mature_repair_004/tool-delivery-proof.json)
记录了每次加载的commit、两个源码观察进入哪份实际请求，以及最后一轮的工具和预算。

| 维度 | 001–004窗口当时事实 |
|---|---|
| 产品任务 | `ACCURATE-CROSSHAIR-SPREAD-TOGGLE-001`；本次仍为显式人辅Planning下的有界产品执行 |
| 固定输入 | Feature `fc7be8…` / Evidence `10a3fadd…` / Plan `c760a9cc…` / 父Proposal `af80386f…` |
| 模型 | 本地`qwen3-coder:30b`；未切换到27b；本轮共5次新模型请求，004另复用2份旧响应，不能重复相加 |
| 实际当前位置 | FeatureSpec→Evidence→Plan→RepairPlan→源码查证→Patch生成/一次修订→行为验证失败 |
| 输出边界 | 新的正式Proposal、Review、Dry-run均未形成；Apply、changed Build、GTFO Runtime均0 |
| 源码 | 原Mod未变；完整快照仍为`421ea5eb4785db9fd03740ab76d9f5eff84bf0cedbee9d749679271febf860a0` |
| 验证对象 | 两份真实模型输出各运行原40进程/36检查矩阵；不是游戏Runtime |
| 实际证据 | [最终来源与代码对照](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/mature_repair_004/final-outcome.json)、[请求/响应/物化/矩阵核验](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/mature_repair_004/acceptance-verification.json) |

### 0.1 已提交与 WIP 分界

| 类别 | 内容 | 验证与限制 |
|---|---|---|
| 已提交 `1ba8607` | 共享worker；正式行为Repair入口；B0/C1/F1/C2；多次原生工具历史；29只读/5编辑；三部分上下文和API按需读取 | 288项受影响checkpoint通过；真实闭环结果仍受下列失败限制 |
| 已提交 `458c098` | 合法读取批次顺序执行；超额返回反馈；一次重选机会；共享剩余调用上限 | 真实Qwen收到反馈后改选001+005；99项受影响checkpoint通过 |
| 已提交 `269b37d` | 未执行批次不占执行ID；严格校验原响应、原请求、模型、上游、源码后接续，明确回放来源 | 124项组合回归通过；实际004复用2旧响应、只新增2次调用 |
| 已提交 `e892e3e` | 共用预算预留/释放；失败点按最终反馈检查实际剩余读取能力；复用正式物化算法比较B0下全文件字节；相同代码反馈及显式确定性验证复用 | 离线完整恢复分支通过，首次直接通过不强迫查证；不同代码不代表修复成功 |
| 已提交 `6411f01` | 单Store只读Patch执行查询，挂入verification-claims；显示请求/执行/重放/验证来源与缺失项 | 真实004查询已生成；未关联到的事实保持unknown，不成为业务准入层 |
| 已提交 `7508971` | 报告接收与Graph准入共同拒绝passed+incomplete；保留缺字段unknown兼容 | 合成回归先复现错误放行再验证修复；不追改历史结果 |
| 已提交 `b4c519a` | 查询本次Artifact及终态exact refs；响应/回放引用缺失损坏时降级；无终态缓存不推断未结束 | 真实成功旧运行和005失败均已查询；无新增模型/行为执行 |
| 已提交 `cdbd4ae` | 公开CLI装配已有Repair refs、受信本地evaluator与共享策略；配置/profile纳入既有attempt身份；查询配置来源 | CLI入口离线恢复链通过；旧API/hash保持兼容；当前Mod没有新真实尝试 |
| 已提交 `af36b5d` | 可选完全相同全文引用；真实编码字节计费；恢复历史还原核验；旧False编码回放兼容；查询编码/展开身份 | 239项受影响检查通过；公开CLI合成5读→失败→第6读→修订→Review/Dry-run通过；真实结果见0.9 |
| 已提交 `6d38184` | 产品确定性绑定源attempt与独立复验；当前未admitted C1与正式祖先分开；现有worker消费当前失败代码；公开CLI与查询接线 | 164项受影响检查及34项查询通过；007真实反馈/修订/重验完成，但代码未改善 |
| 已提交 `54dff43` | 完整可见源码窗口覆盖复用；新窗口/复用/工具请求独立计数与恢复；Graph/查询适配；相同可见C1全文复用 | 348项checkpoint通过，最后表示改动69项相关回归通过（含2新增，不相加）；真实008遇验收脚本表示误判，未完成修订 |
| 已提交 `75f4d49` | 工程认知按CLI→Fresh→Evidence回调实际源码接线显示可选API增强；不再误报仅RgLive | 48项查询/投影回归通过；仍不证明自主API语义或真实运行 |
| 已提交 `aa4e00f`／`b792c41` | 同Graph消费明确human/worker上游请求，回Repair→Evidence/全集Coverage或ModelPlanning→新Plan；独立invocation ID | 隔离282通过＋1换行fixture定点复验通过，主仓交叉44通过，run_id补充后19通过；CLI provider装配与新F1自动重绑未完成 |
| 已提交 `7b82698`／`596dae5` | 既有公开Patch CLI可选qualified角色路由；真实执行/完整固定矩阵/原物化代码/当前worker指纹决定资格；CLI与API缓存重验 | 离线Repair正例与拒绝路径通过；主仓联合176通过，1旧schema测试补排除空新字段后定点通过。没有发布真实qualified profile |
| 已提交 `2e746c7` | Planning可编辑选项内联其已有完整source_path并校验共享表一致，保持原ID/源码/范围/选择自由 | 32项相关检查通过；仅表示改进，不能凭测试称模型语义质量改善 |
| 已提交 `d6eda97` | 三方面整链适配：公开A4 provider装配、当前C2/F2绑定、新Plan共享worker与原Review/Dry-run、共享预算和分段查询 | 335项checkpoint通过；之后最终refs两例、查询一例定点通过。真实Mod尚未修复，详0.16 |
| 已提交 `925790d` | 合并通用失败指导的重复说明；保留原需求/代码/失败、输出基线与动作选择自由 | 18项相关回归通过；首wire44,560字节。013真实模型选择了上游，但未产生代码，详0.17–0.18 |
| 已提交 `ceeb1b6` | Findings/Planning实际输入保留API的source_authority、程序集hash、MVID、token和signature，并说明当前／参考来源及运行语义边界 | 来源信息传播已有；A5 Actual001一轮真实输出被编辑身份校验拒绝，不能称API语义成功，详0.20 |
| 已提交 `3122c26` | `requirement_coverage.py`与`requirement_coverage_provider.py`共享原合法编辑身份谓词，生产schema区分引用域与编辑提示域；新增原Actual离线回归 | 4项聚焦及115项checkpoint通过；其它并行WIP不在本节A5验收范围，不能将工作树整体写成“无WIP” |
| 已提交 `9efcac9` | 原Patch查询到Langfuse历史元数据OTLP导出、查询与有限查回；评分核验代码/报告/矩阵身份，防止同数量异矩阵错绑 | 65项相关回归通过；没有真实服务发送，不增加产品成功、原始时序或跨任务资格声明，详0.21 |
| 已提交 `fdb0fc7` | 固定3任务及真实C#行为判定器，准备器输出原公开CLI参数；复用原任务资格合同和Patch worker，不另造执行器 | 基线和输入准入已有，3任务模型成功率为空；人辅Evidence/Planning，不声明自主规划，详0.22 |
| 已提交 `5a6ca38` | 从原Local adapter抽出3个provider hook，外部Qwen复用原worker；校验实际发送范围和模型身份，并在解析前保留HTTP响应 | 离线共享循环/兼容性与解析失败回归通过；0真实目录查询/生成请求，不声明强模型胜任，详0.23 |
| 已提交 `68088bc` | 新编多文件JSON配置程序、独立真实进程判定器及原continuation输入，支持相同任务/标准作本地与外部对照 | 基线已验证，产品模型未运行；不是完整服务生命周期或模型资格通过，详0.24 |
| 已提交 `c97ee16` | 官方宿主加载只读命令插件，查询原Patch记录；原会话/结果组件显示纯命令结果，stock factory保留但DSH模型step拒绝 | 8项桥接/官方组件测试通过，真实会话查询及重启后显示通过；无产品提交/审批/执行恢复，详0.25 |
| 文档整理 | 本文顶部快照、历史标签、统一Attempt索引、剩余矩阵及短控制文档同步 | 不增加产品能力；文档提交单独记录 |
| 用户原有WIP | ARCHITECTURE_OVERVIEW、ENGINEERING_RAG_EVIDENCE_INTELLIGENCE_TARGET_DRAFT、SPEC_COVERAGE_MATRIX，以及3份未跟踪草案 | 六份文件hash与本轮开始完全一致；不混入本轮提交 |

各次测试集合有重叠，288、99、124不能相加为唯一测试数。以下为001–004历史窗口的组合命令，当前命令见第0.12节：

```powershell
python -B -m pytest tests/unit/test_patch_agent_loop.py tests/unit/test_agent_turn_adapters.py tests/unit/test_patch_recovery_worker.py tests/unit/test_patch_behavior_feedback.py tests/unit/test_patch_repair_continuation.py tests/unit/test_patch_verified_replay.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\replay-repair-check-$PID"
```

结果124 passed、2个既有warnings、22.87秒；这是平台/合成项目验证。
另有3项旧Repair fixture测试在旧planner回放也失败，原因是缺当前源码身份，未放宽Reviewer：
`test_repair_proposal_reenters_review_gate`、`test_repair_proposal_reuses_non_hook_plan_validation_contract`、
`test_repair_review_checkpoint_resume_accepts_review_approval`。全仓测试及发布通过不在本轮结论内。

### 0.2 统一 Attempt 索引

本索引集中列本文P0生成/修订的主要Actual；下方历史段落只保留对应运行详情。
Fresh/A3/A8支线另见第11.4、12.4、12.5节，不混进下列P0调用总数。

| Attempt／范围 | 执行器版本 | 新模型调用 | 复用响应 | 实际结果与定位 |
|---| --- |---:|---:|---|
| 历史：9月4日header correction | 见原运行记录 | 3 | 0 | [5024afcd收据](../../artifacts/g1_assisted_findings_context_repaired_27b_fc/store/cr/5024afcd6671db0cee7f7f0f5c4e92a3.json)；旧4-binding链到Dry-run，不能替代当前5-binding行为验收 |
| 历史：c760首次接受 | 见原运行记录 | 3 | 0 | [ccc254c3收据](../../artifacts/g1_assisted_findings_context_repaired_27b_fc/store/cr/ccc254c3eb122bf821fdf3b7a5e174f5.json)；外层调用预算漏传，未形成新Proposal |
| 历史：c760 reacceptance | 见原运行记录 | 2 | 0 | [结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_patch_c760_reacceptance_001/result.json)；形成af803/Review/Dry-run，行为33/36 |
| 历史：behavior actual_001 | 见原运行记录 | 3 | 0 | [0519c447收据](../../artifacts/g1_assisted_findings_context_repaired_27b_fc/store/cr/0519c4472c7f4949706316d93a0deefb.json)；一次修订代码未变，33/36 |
| 历史：behavior actual_002 | 见原运行记录 | 3 | 0 | [64a3b3a6收据](../../artifacts/g1_assisted_findings_context_repaired_27b_fc/store/cr/64a3b3a6dd7ad3b1a80e23d823ce0b0e.json)；32/36，新增Recoil回归 |
| 本轮：mature_repair_001 | `1ba8607` | 0 | 0 | [结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/mature_repair_001/result.json)；预览漏配evaluator，预算状态不同，发送前拦截 |
| 本轮：mature_repair_002 | `1ba8607` | 1 | 0 | [结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/mature_repair_002/result.json)；一次请求5处被旧单工具规则阻断，未读源码 |
| 本轮：mature_repair_003 | `458c098` | 2 | 0 | [结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/mature_repair_003/result.json)；预算反馈后重选001+005，被错误ID记账阻断 |
| 本轮：mature_repair_004 | `269b37d`；复用003原响应 | 2 | 2，来自003 | [结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/mature_repair_004/result.json)；读2处→真实生成→同矩阵→一次真实修订→同矩阵；两次33/36，停止 |
| 新独立轮：mature_repair_005 | 固定`6411f01`，含恢复变更`e892e3e`；未中途改执行器 | 2 | 0 | [结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/mature_repair_005/result.json)；请求5处→当前可读4处反馈→仍请求同5处→重复批次停止；0读/0代码/0矩阵 |
| 新公开入口轮：public_cli_repair_006 | 固定`af36b5d`；执行器/runner中途未改 | 2 | 0 | [结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_006/actual/result.json)；5读实际入模→返回原失败代码→验证器261字符路径失败；独立短目录复验见0.9 |
| 自动绑定轮：public_cli_repair_007 | 固定`6d38184`；短验证目录r7 | 4 | 0 | [结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_007/actual/result.json)；5读→旧代码→33/36→请求5个supporting被预算拒绝→直接返回旧代码→33/36，停止 |
| 覆盖复用轮：public_cli_repair_008 | 固定`54dff43`；短验证目录r8 | 3 | 0 | [结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_008/actual/result.json)；9工具＝3新窗口＋6复用→旧代码→33/36→第四请求被旧auditor误拒绝，未发送；非模型修订失败 |
| 验收器修正版：public_cli_repair_009 | 生产`54dff43`，冻结HEAD`62a996b`，修正auditor；r9 | 5 | 0 | [结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_009/actual/result.json)；11工具＝3新＋8复用，完整修订/两次矩阵均33/36，代码相同 |
| 独立27B对照：public_cli_repair_010 | 生产`54dff43`，冻结HEAD`2c5f5d6`；r10 | 2发送/1返回 | 0 | [结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_010/actual/result.json)；不同模型首轮自主选4support，3新＋1复用；第二请求600秒超时，无代码/矩阵 |
| 零网络预览：public_cli_repair_011 | `d6eda97` | 0 | 0 | body45,066＋4,096超49,152十字节；未实发、未生成、未验证，原记录保留 |
| 零网络预览：public_cli_repair_012 | `925790d` | 0 | 0 | body44,560准入；旧auditor要求两句旧英文而误拒绝，所有B0/C1/F1/需求检查成立，未实发 |
| 通用指导验收：public_cli_repair_013 | `925790d`，新auditor绑定该版本；r13 | 2发送/2返回 | 0 | [结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_013/actual/summary.json)；5读实际入模→请求Evidence上游；无新代码/矩阵，未启用实际A4续接 |

001–004窗口新请求为0+1+2+2=5；004收据中的4是2回放+2新响应，不能重复累计。
后续独立005另有2次新调用；两个已结束窗口合计7次新调用，不包含2份历史响应回放。
006再新增2次真实调用，001–006合计9次；006预览的内部requested=1不是实际发送，不加入推理总数。
007新增4次，001–007合计13次真实调用；各轮preview与2份历史回放均不加入这个数。
008新增3次，001–008合计16次真实调用。008客户端计数4包含一次发送前被auditor拒绝，物理发送仍为3。
009新增5次，001–009合计21次真实调用，0新增回放；009无发送前误拒绝。
010新增2次真实发送、仅1次完整返回；001–010合计23次模型POST，不代表23个成功完成的响应。
011/012及013-preview均0实发；013新增2次发送与返回，001–013合计25次POST，本轮实际新增只有2次。
001收据中的requested计数也不能冒充HTTP发送，其外层实发计数为0。

### 0.3 最新剩余能力矩阵

| 能力 | 最新已证实 | 仍缺什么 |
|---|---|---|
| 共享Patch/行为Repair入口 | 真实父Proposal→RepairPlan→同worker，模拟可到完整Review/Dry-run | 当前真实修订未通过，不能称成功Repair |
| 公开CLI恢复装配 | d6eda97可选provider配置在原Graph完成一个上游周期，再经新Plan/worker及原Review/Dry-run；同Plan入口保持 | 合成项目已验收，实际case验证器仍固定c760；无任意新Plan的GTFO验收 |
| 真实往返与观察驱动 | 真实预算反馈→重选2处；2处实际源码返回模型→真实完整输出 | 输出代码未改善；不能把工具使用等同语义正确 |
| 覆盖复用与计数 | 013实际3新窗口＋2复用，5条观察进入第二实际请求；不同阶段预算累计不重置已有离线证据 | 允许复核；不以新增字节判断有用，不以不同代码判断修好 |
| C1与失败可见、原义务保留 | 013两份实际请求核验B0、完整C1、三项F1与8项原字段；新失败C2/F2绑定也经合成验证 | 入模不是模型理解证明；008邻接缺陷与012旧短语缺陷分别关闭，不反写历史 |
| 只读范围／三部分上下文 | 29读/5编辑；013实读全部5edit；B0与被测代码的角色明确，API仍是保存Evidence | 未真实消费API工具；未建设全量新的读取目录或任意版本源码切换 |
| 行为修订与Revalidation | 同一产品循环实际完成一次反馈修订和原矩阵重验 | 五项代码均等于旧父版本，原3个First Shot失败未消除 |
| 新草稿失败后再查证 | 54dff43公开CLI离线5＋5路径通过；009失败后001/005引用实际进入第五请求并获得修订 | 只选择已见信息，没有新增源码；两份代码和三项失败不变，有效修复未证明 |
| 停止与来源 | 失败未流入新Proposal/Apply；同B0实际代码比较、无变化反馈和显式确定性结果复用已测试 | 原矩阵仍决定行为结果；旧报告缺完整验证身份则不复用；不宣称通用恢复 |
| 可查询执行索引 | 同Store查询分段Plan/worker、整链预算、上游角色、blocked新Plan及原/当前失败；013查询已生成 | 缺失保持unknown；预算预留不等于真实发送；未完成全部旧Trace/Eval/Langfuse整合 |
| 接续与预算 | 精确原JSON值、类型及文本校验；2原响应回放不新发网；全工作5次新调用 | 仅限定0已执行读的工具选择前缀；不是任意节点或副作用的自动恢复 |
| 上游请求／Replan | 当前不同C2/F2→Evidence/Planning→新Plan→新Patch→原Review/Dry-run的公开链已离线通过；013真实自主请求Evidence | 013请求必要性未证明且该case未配A4；多上游周期、真实新Plan与Build/Runtime闭环仍未证明 |
| 自主Planning／模型资格 | A4真实模型生成新Plan与preflight；公开Patch入口已有可选证据资格路由及离线Repair正例 | 新Plan语义未通过；c760仍人辅P0基线；真实3任务资格集/合格模型条目未发布，initial角色正向资格未验收 |
| Apply／Build／Runtime | 保留原控制合同，Mod源码未变 | 本次全部未执行；隔离C# Harness不是实际游戏运行 |
| 七组完整十日目标 | 本轮推进执行与一类恢复；其它已有底座继续复用 | 自主Evidence/API语义消费、固定Eval、真实Langfuse、hosted CI、Release等未由本轮完成 |

### 0.4 历史章节阅读规则

第1–8节为初次核对，第9节为回读记录，第10节的七组目标澄清仍有效；第11–13节为已结束的执行窗口。
第14节是用户要求术语对账时的阶段快照，早于本节最终结果；其WIP、剩余次数、未生成代码等措辞只适用于当时。
旧段落的“当前”“下一步”“末次运行”均应按章节标签理解，不覆盖第0节。
初次核对所用代码`3694a7725ddd6242ea17db029b88e119a130d378`仅为历史基线。

### 0.5 两个执行器缺陷的闭合证据

不是分别只测“能拒绝”和“能读取”。以下已有回归覆盖连续状态变化，不另造修复层：

- `test_real_budget_reselection_does_not_reserve_unexecuted_provider_call_ids`：重放两份真实003响应，
  五项超额全批不执行→原生预算反馈→模型重选001+005（含重复的合成call ID）→两项顺序读取→结果返回后继续。
- `test_resume_budget_feedback_does_not_mark_rejected_reads_as_executed`：恢复历史时同样不把未执行请求标成已读。
- `test_replay_retains_original_file_and_consumes_shared_budget`与同文件身份拒绝测试：原请求/响应不改，
  校验源码/上游/profile/digest、原始响应和解析结果、严格JSON值及类型；2份旧响应复用不发新请求，仍占原逻辑额度。
- 真实004最终接续：上述原响应没有冒充不同输入；首次原始字节一致，第二份仅原生工具JSON键序变化，
  所有JSON值、类型及文本保持一致并绑定原始wire hash。之后两条源码观察进入两个新实发请求，
  新代码逐binding匹配这两份真实HTTP响应，两个矩阵各40进程/36检查、33通过/3失败。

预算的读取单位为每个实际读取的binding，不是“一个批次等于一次读取”；执行方式为顺序。
请求前的loop_state显示剩余读取次数，工具说明显示计数方式；超额反馈不消耗源码读取次数。
当前工具只读B0，C1通过完整原响应可见；尚未提供任意版本源码切换，因此不宣称跨版本binding去重已通用化。
上述001–004窗口已经结束；后续用户指示的新独立验收见第0.6节，不复用旧窗口的运行时状态。

### 0.6 新一轮能力实现、查询适配与固定版本验收

当前实现复用同一个Patch worker、正式exact-text物化算法、ArtifactStore和Graph；
查询层只向已有记录读取，不被Repair/Apply反向调用，不自行裁定失败owner或产品结果。

- 初始阶段共同预留模型轮次、binding读取数和观察字节；修订阶段释放预留但沿用累计消耗。
  初始反馈字节预留是估计，实际失败时重新按真正反馈对象计算；同时检查已读ref与策略是否仍允许读取。
  该容量声明是worker预算可用，不等于provider最终上下文一定准入。
- 比较对象是同B0和相同文件集合下正式materializer产生的完整文件字节。
  仅rationale/JSON变化不算代码修订；代码不同也不记作修复进展；needs_replan不被强迫改代码。
- 验证器只有显式提供验证输入、实现、环境身份并声明可确定性复用，才能复用同代码的已执行结果。
  新复用记录绑定原报告，标明reused与callback_invoked=false；旧报告不改写；环境变化则重新执行。
  未提供这组身份的旧callback仍执行验证，不伪造复用资格。
- `verification-claims --query patch-execution`只查询显式Store。
  [真实004查询输出](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/patch_execution_query_mature_repair_004_20260906.json)
  核验5条Artifact、16条文件引用和原owner终态hash；显示5条请求未执行、2条实际读取、2份重放和2份新响应。
  旧attempt定义、实际请求入模映射、物化身份或验证执行来源缺字段时保留未核验/unknown。
  `code_revision`是原journal声明，查询不重新推断代码正确性；单任务行为结果不冒充Graph终态eval_report。

本轮受影响checkpoint（最后Graph malformed-policy拒绝小修前）：

```powershell
python -B -m pytest tests/unit/test_patch_agent_loop.py tests/unit/test_patch_recovery_worker.py tests/unit/test_patch_behavior_feedback.py tests/unit/test_patch_repair_continuation.py tests/unit/test_patch_verified_replay.py tests/unit/test_materialized_code_identity.py tests/unit/test_patch_apply.py tests/unit/test_patch_execution_index.py tests/unit/test_fresh_planning_continuation.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\patch-cap-$PID"
```

217 passed，68.50秒。随后仅增加malformed-policy拒绝及4种非法输入回归，执行：

```powershell
python -B -m pytest tests/unit/test_patch_recovery_worker.py -q --tb=short --basetemp="$env:TEMP\prw-policy-$PID"
```

13 passed，14.34秒；包含完整Adapter/Graph恢复链。集合有重叠，不能相加。
Ruff：其余本轮文件通过；local_entry既有10项、graph既有2项仍在，已用HEAD原文件复现相同规则错误，未批量改无关代码。
六份原有用户WIP hash未变。全仓测试、跨任务模型质量、真实Langfuse和部署回退未由本轮证明。

固定版本独立005验收已经执行并结束；仍使用c760、原失败af803、Qwen3-Coder与原行为矩阵。
预检最终body 43,052 bytes，现有准入需求47,148≤49,152；首次实际wire与预检逐字节一致。
2次实发均收到响应；实际prompt token分别11,857与12,765，输出均155 token。
首个物理拒绝是`PATCH_AGENT_TOOL_BATCH_BUDGET_EXCEEDED`：允许读取的5个目标合法，
但请求数5超过本阶段4（同一总额度5中保留1）。第二份实际wire包含全部5条未执行反馈，
每条均显示remaining_read_count=4、total_remaining_read_count=5、reserved_read_count=1，
要求重选不超过本阶段额度或使用已有上下文完成。第二次仍选择同5个name/arguments，
原始provider call IDs不同；不是旧ID误记执行的问题。终态按既有重复批次规则停止。

全程126.34秒，执行结束后冻结HEAD和文件字节核验仍一致，Mod源码未变。
10条工具请求、0实际源码读取、0代码输出、0行为验证、0新Proposal/Review/Dry-run/Apply/Build/Runtime。
`execution_counts.patch=1`只是Patch节点执行一次，不能解释为生成一版代码。
本轮未触发实际的失败后读取、实际代码比较或验证复用；这些能力仍只有前述离线验证，
不能以005证明Qwen能修好或不能修好First Shot。初始4+1预算分配是执行策略，可另行评估，
不是EditAuthority安全边界；不在已结束的005运行中扩大预算或追加调用。

[005实际请求与结果核验](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/mature_repair_005/acceptance-verification.json)
保存上述wire、反馈、冻结版本和结果边界；
[005正式查询输出](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/mature_repair_005/execution-query.json)
显示2份live、0重放、10条not_executed、无代码/行为记录，终态hash通过而attempt定义无法核验。
查询本身新增模型/验证调用0；不把缺关联解释成行为测试失败。

### 0.7 后续审查纠偏：查询成果关联、报告完整性与公开入口

> 本节记录cdbd4ae之前的审查与修复；公开CLI“尚未接通”的表述由第0.8节更新。

本节核验了另页在6411f01时点的审查，实施仅针对本页已交付路径的具体缺口。
审查时的四份文档WIP后来已由6a14aa9提交；六份原有用户WIP仍未修改。
三阶段Trace/Eval/Dashboard迁移保留为参考，没有整套启动。

- `b4c519a`分别读取journal.artifacts与terminal_result已有Proposal/Review/Dry-run引用，
  标明原字段位置、复用ArtifactStore核验；不从Repair父版本推断本次成果。
  response_origin及计数明确为journal声明；响应或原回放引用缺失/损坏，send_observation降为unknown。
  即便引用匹配，也不叫独立发送证明。没有terminal_result缓存只记录“缓存未保存”。
- [有Proposal的真实旧运行查询](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/query_adoption_review/d80_proposal_review_dry_run_query.json)
  已关联af803 Proposal、965b Review与28e5 Dry-run，并由Store核验。
  [005失败运行查询](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/query_adoption_review/mature_repair_005_query.json)
  查到本次RepairPlan，终态三个下游引用保持recorded_null；旧父Proposal仍只在父关系中。
  原journal未改；查询不新增模型或验证执行。
- `7508971`修复passed+execution_origin=incomplete被准入的问题。
  三项合成用例先复现：这种矛盾报告原先可到Dry-run，Graph也接受它；修复后在原报告owner与Graph阻断。
  缺字段或显式unknown仍兼容旧callback，因为unknown不等于没有执行；后续Eval不能把它自动计为已观测成功。
  005未生成行为报告，没有证据表明005实际发生过这种假成功。
- 公开入口缺口确认：CLI没有传behavior_evaluator、enable_recovery_loop，也没有构造已有Repair父引用。
  005通过scratch runner注入这些对象后调用生产API，未经过CLI.main。公开caller接线仍未完成，
  不应将注入式生产类测试称为CLI验收，也不应把RAG EvaluatorFactory硬套给行为报告接口。
- [005读取负载测量](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/query_adoption_review/read-budget-sizing.json)
  显示五份观察共23,912字节；002/003/004均返回相同配置文件1–80行全文。
  这是确定性尺寸检查，未调用模型、未调整读取配置、未实现去重。只提高读取次数未必同时解决观察字节与后续修订空间。

报告准入修复受影响验证：

```powershell
python -B -m pytest tests/unit/test_patch_recovery_worker.py tests/unit/test_patch_behavior_feedback.py tests/unit/test_patch_repair_continuation.py tests/unit/test_fresh_planning_continuation.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\report-origin-$PID"
```

88 passed，65.92秒；包含legacy unknown、显式executed与incomplete，以及原修订/续跑路径。
查询9项故障回归先失败后通过；其完整组合为：

```powershell
python -B -m pytest tests/unit/test_patch_execution_index.py tests/unit/test_engineering_cognition.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\pxi-adopt-check-$PID"
```

38 passed、1 failed，21.20秒。索引29项全部通过；既有失败为
`test_surface_projection_keeps_mcp_as_two_bounded_surfaces`，期望product_cli=21而实际22，
修复前6a14aa9也为22，本轮未修改CLI/engineering_cognition或旧断言分母。
本轮测试文件及查询代码Ruff通过；local_entry/graph既有lint问题见第0.6节。以上测试集合不应跨轮相加。

### 0.8 公开CLI装配与真实入口离线验收

用户明确选择的交付是公开入口装配现有Repair输入、行为验证器、共享worker并做离线验收。
`cdbd4ae`在原`continue-fresh-patch`子命令增加三个参数，没有新Graph或另建执行循环：

- `--patch-worker-config`：严格本地JSON，包含schema_version、policy、enable_recovery_loop、behavior_evaluator。
  policy直接构造现有PatchAgentLoopPolicy；模型参数继续来自已有ollama参数。
  evaluator使用factory_ref(path/sha256)、精确factory_name与JSON kwargs，返回已有callable接口。
- `--repair-inputs`：直接读取已有五项Repair引用，原Artifact/Repair owner负责上游与源码准入。
- `--attempt-id`：复用已有稳定attempt机制。CLI具名attempt要求worker配置；Repair必须具名。

新增装配配置仅解决CLI不能直接表达Python callable及共享策略的问题。现有模型profile、
PatchAgentLoopPolicy和PatchContinuationInputV1继续分别负责模型选择、预算与上游引用。
没有将配置注册为业务Artifact，没有接入RAG evaluator或新增插件注册表。

加载配置只读取并核验，不执行factory。实际新attempt进入生产Adapter后，先构造验证器再发模型请求；
同attempt已有终态时不再次构造。执行的是刚核验的factory文件字节，导出/构造失败不自动重试。
这是用户显式选择的受信本地Python代码，不是模型工具；文件hash不证明依赖闭包或沙箱安全。
可选verification_identity保持缺失/存在语义，不能替没有身份的旧callback制造复用资格。

原request增加可选worker_configuration_ref和worker_profile_sha256，必须成对。
CLI绑定配置文件及实际模型profile；同attempt更换配置/profile/预算会走原身份冲突路径。
旧请求未提供两项时，原canonical身份保持不变。缓存读取前仍核验配置文件。
配置与factory引用写入原journal/receipt，已有只读查询能够核验引用；不输出kwargs内容或执行factory。

**真正经过公开入口的离线证据：**
`tests/unit/test_patch_repair_cli.py`调用真实cli.main(argv)，只stub HTTPTransport并禁止真实socket。
模型身份读取、请求序列化、配置加载、生产Adapter/Graph/worker没有被替换。
测试选中的Python验证器文件真实加载，实际执行合成marker检查。

1. 第1次离线响应选择源码，程序真实读取；第2次消费观察并给出失败代码，验证器实际判失败；
   第3次消费新失败并读取另一个允许ref；第4次消费新观察给出修订，检查通过后形成新Proposal、Review、Dry-run。
2. 失败点实际剩2个模型轮次且有读取额度；两个源码结果、上一版代码、新失败和原preservation均在最终wire。
   每个wire hash与原receipt一致；这四次是测试响应数，不是实际模型调用。
3. 首稿直接通过时0读取；同attempt读取已存结果时0新增HTTP、0新增factory构造。
4. 持续失败停止、无Apply；错误配置、factory hash、缺Repair字段和错误报告hash都在HTTP之前拒绝。

受影响验收命令：

```powershell
python -B -m pytest tests/unit/test_patch_repair_cli.py tests/unit/test_patch_worker_configuration.py tests/unit/test_patch_worker_input_identity.py tests/unit/test_fresh_planning_continuation.py tests/unit/test_patch_repair_continuation.py tests/unit/test_patch_recovery_worker.py tests/unit/test_patch_behavior_feedback.py tests/unit/test_patch_verified_replay.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\public-repair-$PID"
```

191 passed，88.79秒；包括7项公开CLI验收、46项加载器与27项输入身份检查，不能再将这些子集与191相加。
新增配置查询消费单独验证：

```powershell
python -B -m pytest tests/unit/test_patch_execution_index.py -q --tb=short --basetemp="$env:TEMP\pxi-config-final-$PID"
```

32 passed，9.22秒。新配置/CLI/continuation/查询及对应测试Ruff通过；local_entry既有10项问题保留，未批量改无关代码。
六份原有用户WIP未修改；本轮不宣称全仓或发布验收通过。

**当前case已有可读取的装配文件：**
[worker.json](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_preparation_001/worker.json)、
[repair-inputs.json](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_preparation_001/repair-inputs.json)、
[CLI参数列表](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_preparation_001/cli-arguments.json)。
[准备结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_preparation_001/preparation-result.json)
证明实际c760/af803引用通过preflight、原CaseBehaviorAdapter经新加载器构造，模型/行为回调调用均0，源码未变。
此case准备没有执行CLI模型运行，没有新C#矩阵；配置保留005预算，不能写成重复读取问题已修复。
接下来仍需处理重复源码观察与预算分配，然后通过这个公开入口安排独立的真实验收。

### 0.9 005读取预算修复与公开CLI独立006验收

本轮按用户明确要求解决005的已定位读取阻断。区分读取次数与内容字节：

- 006显式策略从5次总读取调整为6次，初始可用5次、后续保留1次；不是把一个批次按一次收费。
- `deduplicate_source_excerpts`是默认False的可选编码。只有同源码快照、source_hash、excerpt_span和全文完全相同，
  才以`excerpt_ref`引用前序完整观察。各binding、target_span和原observation hash独立保留；
  API内容及仅重叠的窗口不合并。缺引用、null引用、篡改或与当前注册源码不符会拒绝。
- `expand_patch_source_observations`纯函数验证还原后的完整身份；恢复从已有工具历史取全文，未新增全局缓存或状态机。
  trace分别保存encoded_payload_sha256/bytes、expanded_payload_bytes和原观察身份，共享字节预算按实际编码计费。
  True模式的payload_admitted与后续模型返回时的admitted_to_model分开；同批未发出不能算已入模。
- 旧policy没有新字段时仅能作为False的旧完整编码回放；True不能冒用旧请求。没有放宽旧上游/源码/请求身份核验。

[固定代码测量](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_006/excerpt-budget-measurement-final.json)
在af36b5d上实际读取c760当前注册源码并还原核验：23,912→16,234字节，节省7,678；
003/004引用002的配置全文，001/005不同窗口保持完整。加入原失败反馈2,071后共18,305，
小于保留后续观察7,768后的初始上限25,000。该测量没有模型调用，不证明模型理解。

公开CLI合成验收由RgLive/Coverage/Planning真实生成5个绑定，不手造权限。
五份展开观察43,317字节，经引用后11,525；失败点剩1读、3模型轮次和19,092字节，随后实际第6读651字节，
修订通过检查、Review和Dry-run。每个绑定仍独立计数，最终wire只含一份相同全文；4次响应均为离线测试数据。

```powershell
python -B -m pytest tests/unit/test_patch_excerpt_references.py tests/unit/test_patch_agent_loop.py tests/unit/test_patch_repair_cli.py tests/unit/test_patch_recovery_worker.py tests/unit/test_patch_behavior_feedback.py tests/unit/test_patch_verified_replay.py tests/unit/test_patch_repair_continuation.py tests/unit/test_patch_worker_configuration.py tests/unit/test_patch_execution_index.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\excerpt-public-$PID"
```

239 passed，38.34秒，2条既有warnings。变更的loop/query/tests Ruff通过；local_entry既有lint问题未批量处理。
旧引用/来源查询只转发新编码字段，未取得产品路由或修复裁决权。六份原有用户WIP保留。

006使用同c760/10a3/af803、同Qwen3-Coder digest、同原40进程36检查、同49152上下文/4096输出；
不重跑Fresh、不换Plan、不人工提供Mod after_text、不回放旧响应。
固定[174个文件和配置](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_006/frozen-inputs.json)。
公开CLI[零网络预览](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_006/preview/summary.json)
43315字节，原准入47411≤49152；原Store保留独立preview journal，内部requested=1而实际发送=0，不计真实推理。
正式006使用另一个attempt，首wire与预览一致；预览不复用到正式执行状态。

**006真实终态：预算阻断已关闭，产品修复未通过。**

- 公开CLI执行246.96秒，2次真实模型POST和2次真实身份GET；模型调用是2，不是HTTP总数4。
  固定代码/输入文件及原Mod源码未变，0回放；原Store仅新增本attempt和原响应，没有修改旧记录。
- 第一次实际wire为43,315字节，Ollama报告11,903输入token；第二次为59,777字节，报告16,131输入token。
  第一次使用现有字节代理准入，第二次使用同模型已观察token比率估算准入。32,768仅是观察内容预算，
  不等于整个请求字节，也不等于模型token窗口；只证明已执行两轮，不保证所有未来回合。
- 第二次实际messages有5条工具结果：3份不同全文及2个excerpt_ref。
  对全部messages递归解码后，完整Configuration源码恰好出现1次；003/004各自范围和身份仍在，
  没有只留本地映射，也没有发送前重新展开为3份全文。实际编码观察16,234字节与receipt一致。
  [实发请求](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_006/actual/request-002.body.json)、
  [源码展开核对](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_006/actual/source-observations-002.json)及
  [最终收据关联核验](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_006/actual/summary.json)
  明确区分程序还原、实际发送和模型理解（未证明）；无需新增检查层。
- Qwen第二份响应完整但raw hash仍为2b4f580c5d1eb2a698b5e8f034ba321089c47b815ecb1703c655a26a19b720df，
  与原父版本一致；同B0完整物化代码比较也为same_materialized_code=true，检测没有丢失。
- 行为callback被调用，但在materialized_changed_files下写SpreadPatches.cs时遇到FileNotFoundError。
  文件全路径261字符，父目录244字符且存在；异常发生在编译和矩阵开始前，report为infrastructure_failed、
  execution_origin=incomplete、failure_owner=environment。工作流正确停在PATCH_BEHAVIOR_REQUIRES_UPSTREAM_DECISION，
  不把它当First Shot行为失败送给模型。因此没有真实第六次读、第二份修订、新Proposal/Review/Dry-run/Apply/Build/Runtime。

**独立路径诊断与无模型复验（不改006终态）：**
[同环境路径探针](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/path_length_006_19f5161d/result.json)
实际复现217/259字符写成功、260/261字符FileNotFoundError，父目录均存在。只在独立诊断目录写普通文本。
没有修改注册表、006冻结配置或原验证器。使用新配置实例
[r6-verification-worker.json](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/r6-verification-worker.json)
仅将输出目录缩短为r6，最深源码路径降至226字符。

通过同一PatchWorkerConfiguration加载原factory，把006已保存的callback输入交给原验证器一次，模型调用0。
原40进程36检查完整执行，33通过、3失败；Recoil通过。失败仍是：

| 原检查 | 期望 | 实际 |
|---|---|---|
| FALSE_MATCH_PRESERVES_EXISTING_FIRST_SHOT_ABSOLUTE_SIZE | 主尺寸30 | main/rendered均140 |
| FALSE_MATCH_SECOND_COOLDOWN_PRESERVES_EFFECT | 主尺寸30 | main/rendered均140 |
| FALSE_INNER_EFFECT_PRESERVED | innerVisible=true、innerSize=30 | true、10 |

[独立复验结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/r6/verification-only-result.json)
绑定原callback、006原响应、新配置与新报告；原006receipt hash仍匹配，没有回填为已完成矩阵。
这说明006真实输出仍未修好，不等于006完整修订循环已经执行。239项工程回归、离线固定响应闭环、
真实Qwen输出与本次独立验证分别记账，不将任何前两项算作Qwen任务成功。
本轮不追加模型尝试；后续配置应使用独立短验证目录，并在模型调用前验证该输出环境。

### 0.10 自动绑定独立复验与007真实Repair

用户进一步要求把引用组装收回Agent本体；本轮没有由Codex拼写最终五项Repair输入或手工增加状态同义字段。
`6d38184`增加产品函数`bind_patch_repair_verification`，由原公开CLI的`--repair-from-verification`调用。
调用方只显式选择source_attempt_ref与verification_result_ref，既有Store/Feature/Evidence/Plan配置继续限定范围。
本次前者是006，后者是r6独立复验；不能从时间、目录或同feature猜测补测归属。

系统机械核验源journal、当前原始响应、callback、原行为报告、矩阵、配置、源码与Plan，沿明确血缘取正式祖先。
当前未admitted的C1通过failed_response_ref/failed_diff_intent进入同worker，parent_*继续表示正式祖先；
接受同Plan内合法但不同于正式祖先的失败代码，不把006冒充新Proposal。对不同模型的规范化合法输出保持同一规则。
派生报告内容寻址、不可变、与新consumer attempt/time无关；原observations逐字保留，
execution_origin=unknown、callback_invoked=false，derivation绑定原executed报告并声明本次0模型/0验证。
短code_revision来自原materializer比较，不由模型抄hash、不提供专用修法；r6本来已有observed_state，未重复包装成新证据。
现有preflight再次核验原来源，原RepairPlan的retry count也被继承。新增可选输入缺省时保留旧attempt身份。
RepairPlan/journal不复制完整C1代码，只存引用和身份；运行中的worker获得已核验的完整C1。

公开CLI离线验收不仅测相同代码：合法但不同的C1也能自动绑定、真实装配、读取/反馈/修订到Review/Dry-run；
错源、篡改或未执行验证在任何HTTP之前停止，同attempt重复调用不再发请求或构造验证器。

```powershell
python -B -m pytest tests/unit/test_patch_repair_binding.py tests/unit/test_patch_repair_cli.py tests/unit/test_patch_worker_input_identity.py tests/unit/test_fresh_planning_continuation.py tests/unit/test_patch_repair_continuation.py tests/unit/test_patch_recovery_worker.py tests/unit/test_patch_behavior_feedback.py tests/unit/test_patch_verified_replay.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\auto-repair-bind-$PID"
```

164 passed，68.83秒。相关只读查询另跑`tests/unit/test_patch_execution_index.py`，34 passed，5.56秒。
变更CLI/binder/planner/query/tests Ruff通过，local_entry既有问题未批量处理；无全仓/跨模型资格声明。

007冻结代码6d38184与176个文件，仍同c760/10a3/Feature、Qwen3-Coder name/digest、model5/read6、32768观察字节、
49152上下文/4096输出，短输出目录r7。公开CLI零网络preview由系统生成rv-31c031...报告及新RepairPlan；
首wire43828字节、原代理准入47924≤49152。实际007使用另一attempt并逐字节匹配preview，0回放。
原三项input/expected/observed/observed_state与当前C1完整传递；wire中report_sha256仍为null，但journal的report ref/hash正确，
故只主张正文与系统绑定已核验，不主张该hash已经传给模型，也不为这个显示字段临时改变冻结执行器。

**真实007轨迹与结果：**

| 真实模型轮次 | 行动与执行 |
|---|---|
| 1 | 请求原5个edit bindings，5次实际读取 |
| 2 | 消费源码后给出完整输出，仍与006/af803原代码相同；原矩阵真实执行33/36 |
| 3 | 收到新行为失败和same-code反馈后，请求5个新的supporting refs；全部在ReadScope，但剩余读取1，整批未执行 |
| 4 | 实际收到预算反馈；仍可选择1次读取或请求上游，但选择直接给出完整修订；仍为同一旧代码；原矩阵再次33/36 |

总4次模型POST，另4次身份GET，0回放；墙钟481.46秒。两份代码raw hash仍为2b4f580c...b720df，物化比较均same=true。
两次矩阵各40进程36检查，均原First Shot三项失败；这是一项task的一次trial内两次验证，不是80个任务。
失败后真实可用3模型轮、1次读取、10989观察字节；5项请求被预算拒绝花2290字节反馈，第四轮仍有2模型轮/1读/8699字节，
不是工具被关闭。不得说5项supporting已实际返回模型，也不得把一次可用读取等同于满足模型整批调查需求。
终止PATCH_BEHAVIOR_CORRECTION_FAILED，没有新Proposal/Review/Dry-run/Apply/Build/Runtime。
这次证明系统自动绑定、真实反馈回流、真实修订调用和重验已执行；没有证明Qwen产生了有效修复或真实完成失败后新查证。

[007实际记录](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_007/actual/summary.json)、
[新失败进入第三请求](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_007/actual/request-003.body.json)、
[第四请求](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_007/actual/request-004.body.json)及
[只读查询](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_007/actual/execution-query.json)
分别保存真实通信、原始结果和机械关联。代码版本/原Mod源码未变；旧006/r6记录未修改；本轮不追加模型或自动换模型。

职责校准：身份、权限、实际计费、物化、验证事实应机械；调查顺序、根因假设、具体实现和是否请求上游由模型决定。
本次5+1是选定配置及离线覆盖场景，不是所有模型的固定认知路径。全局5轮/单次修订等当前策略仍有进一步配置化空间，
但本轮未整体重构policy；跨模型能力必须另行验证适配与任务质量，不能由这些单例推出。

**007后续读取的只读成本测量：**
[独立尺寸记录](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/repair_007_support_measurement_38be2538/measurement.json)
将第三响应提出的5个精确ref按生产codec、以第二请求已交付的完整观察为历史测量：共13,671字节，
比失败点剩余10,989多2,682。因此不是单纯把读取次数调大就能让整批进入原预算。
该测量没有执行新的产品工具、模型或矩阵，不修改007。

| 请求对象 | 精确绑定行 | 返回行 | 编码字节 |
|---|---|---|---:|
| Configuration() | Configuration.cs 23–27 | 1–80，引用已见全文 | 764 |
| GetCrosshairSize(float scalar) | SpreadPatches.cs 160–165 | 96–179 | 3789 |
| GetCrosshairSize() | SpreadPatches.cs 167 | 103–179 | 3567 |
| AccurateCrosshair登记块 | Loader.cs 1–20 | 1–56 | 2105 |
| SetStoredCrosshair(BulletWeapon) | FirstShotPatches.cs 35–52 | 1–76 | 3446 |

每一项单独都可装入当时余额；两个Getter窗口只是重叠，现编码有意不合并。第四轮模型有读1处或请求上游的合法选择，
却直接返回旧代码。当前结论限定为该模型、输入表示和策略组合失败，不证明其他模型必然失败或增加预算必然成功。

### 0.11 用户界面方向：优先复用DSH，不自建产品前端

用户提出不再自行开发前端。已只读核验DeepSeek官方Harness，尚未安装、部署或编写DSH插件；不替代当前P0。
方向是DSH现成Web作为交互入口，薄适配调用Python受控CLI，后端保留唯一业务身份/路由/审批/执行事实所有权。
第一版优先同机运行DSH、Python与GTFO；远端部署需要独立本地受控执行端，服务器CLI不能自动操作浏览器用户的游戏目录。

官方确认[Web/headless/profile/plugin](https://github.com/deepseek-ai/deepseek-harness)存在，项目仍为developer preview；
[CLI说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/cli/reference/README.md)中headless默认输出最终回答。
本项目Patch CLI同样尚无统一stdout事件流，Fresh心跳不代表Patch全链已流式；实时进度、取消/恢复及exact approval都还需适配。
[工具卡片](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-tool/README.md)默认通用展示，
[用户问题接口](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/interaction/user-questions/README.md)
不能直接等同本项目专用diff审批。可先用通用卡片、Markdown/diff文本与问题交互，不能宣称零适配就有完整审批UI。
[安全说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/SAFETY.md)也不支持把禁用模型Shell工具称为插件权限沙箱。
DSH上层若调用外部模型，源码/diff等工具返回同样涉及披露，不能以“只是UI”绕过现有规则。
DSH session只作关联；不再重复建设独立前端或把DSH agent loop嵌成第二业务控制面。

### 0.12 源码覆盖复用、可见C1去重与008验收器误判

`54dff43`在同一个Patch worker增加可选`reuse_covered_source_observations`，缺省False保持旧行为。
开启后`read_accounting_version=new_source_window_v2`：完整所需窗口已被同来源/源码hash/snapshot的
当前可见正文覆盖时返回精确引用，否则获取新窗口。不合并部分重叠窗口，不产生新Evidence或编辑权限。
工具请求、新窗口、复用分别记录；观察ID与新窗口计数解耦，batch/resume/Graph/查询消费同一计数语义。
引用仍消耗真实消息字节与模型调用；连续同批纯引用无新观察停止，不强迫模型按固定顺序调查。
每轮`turn_progress_trace`及物化比较轮次记录信息增量；代码变化本身不等于行为改善。

在007形状离线回归中，初始5项为3新＋2复用，失败后5项为2新＋3复用；公开CLI到Review/Dry-run通过。
另验证直接通过无需工具、引用缺正文/漂移/恢复低估计数拒绝，以及追加查证后原样失败仍停止。

```powershell
python -B -m pytest tests/unit/test_patch_source_coverage_reuse.py tests/unit/test_patch_agent_loop.py tests/unit/test_patch_excerpt_references.py tests/unit/test_patch_covered_source_cli.py tests/unit/test_patch_read_accounting_admission.py tests/unit/test_patch_repair_cli.py tests/unit/test_patch_recovery_worker.py tests/unit/test_patch_behavior_feedback.py tests/unit/test_patch_verified_replay.py tests/unit/test_patch_worker_configuration.py tests/unit/test_patch_worker_input_identity.py tests/unit/test_patch_repair_continuation.py tests/unit/test_patch_repair_binding.py tests/unit/test_fresh_planning_continuation.py tests/unit/test_patch_execution_index.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\reuse-checkpoint-$PID"
```

348 passed，73.05秒。随后发现仅覆盖复用仍会使007同动作末轮反事实请求85451字节、
按007历史校准估算50905>49152；其两份assistant完整Patch恰好逐字相同，各7443字节。
现有恢复消息仅在完整raw已可见且完全相同的情况下省略第二份正文，以`previous_response_ref`明确绑定当前C1；
原响应与各次验证仍独立保存。不同/不存在的raw必须完整提供，新F1和全部原义务不删。
用生产函数复算末轮77992字节、46819<49152，仍仅是007校准下反事实估算，不是008实测token。

```powershell
python -B -m pytest tests/unit/test_patch_visible_revision_context.py tests/unit/test_patch_covered_source_cli.py tests/unit/test_patch_recovery_worker.py tests/unit/test_patch_behavior_feedback.py tests/unit/test_patch_verified_replay.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\visible-context-$PID"
```

最后表示变更69 passed，28.17秒（含2新增；与348重叠，不能相加）。变更core/query/tests Ruff通过；
local_entry原10项、Graph原2项lint问题仍为基线问题，没有批量修复。六份原WIP不变。

**真实008：** 固定54dff43及176文件，同006+r6/C1/F1、Feature/Evidence/c760与Qwen；数字上限5模型/6新窗口/32768观察字节。
数值虽未增加，读取成本语义已改变，不能称旧profile原样重跑。短目录r8，未修改Mod或矩阵。
零网络首轮preview44241字节，代理48337<=49152；真实首wire hash `be086c65...5f4dfb9a`完全匹配。

| 模型客户端轮次 | 实际事实 | 新信息/代码边界 |
|---|---|---|
| 1，已实发/返回 | 请求原5个edit binding，3全文＋2复用进入第二请求 | 3个新源码窗口 |
| 2，已实发/返回 | 请求4个supporting：Configuration、两个GetCrosshairSize及095538位置；全部覆盖，4引用进入第三请求 | 没有新源码，不扣新窗口额度，但实际字节/模型调用计费 |
| 3，已实发/返回 | 原始Patch仍为2b4f580c...b720df；原40进程36检查真实执行33通过/3失败 | 代码未改善，Recoil通过、Match两项140应30、Inner10应30 |
| 4，仅客户端调用，未实发 | 新F1和可见C1引用已形成72750字节请求，达到HTTPTransport；验收脚本误拒绝 | 不能称模型消费了新失败或完成了修订 |

CLI持续288.55秒；3真实POST＋3身份GET，0回放；客户端账本model_call_count=4包含发送前失败。
失败点尚余2模型轮、3新窗口、6913观察字节；单项新查证可用，不代表任意批次均可容纳。
所有9条工具观察已在第三实发请求中可见；第四请求保留它们不代表第四次模型已看到。
没有第二份代码、第二次矩阵、新Proposal/Review/Dry-run/Apply/Build/Runtime。

精确首失败为验收脚本RuntimeError：`Original semantic input obligations failed at transport.`。
原`verify_mature_repair_run.py:audit_wire`硬取F1前一消息作为C1，并要求该消息是assistant。
第四请求当前F1前一消息实际为tool，旧检查误读它；`C1_all_five_change_rows_present=false`，而B0五项、
八项preservation字段、F1 input/expected/observed全部为true。更早完整C1仍在，新引用hash与字节相符。
这属于验收器未适配已实现的输入表示，不能归为Qwen修订失败或声称真实Repair通过。
本轮公开CLI离线测试覆盖了产品worker，但没有覆盖实发包装脚本这条旧相邻位置检查；这是验收准备缺口。
顶层attempt已失败收口；内部behavior_correction保留running最后快照，不表示仍有后台任务。
原008、冻结runner与原auditor不改；另行离线修正和复验此检查，不中途换执行器接续、不追加真实模型。

独立修正版auditor保存在
[audit_wire_visible_c1.py](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/auditor_008_visible_c1_353a1738/audit_wire_visible_c1.py)，
hash `d20833308084e2fb36211112d799fe457da20f9b17bc7357f70145aba3496a47`。
它按引用的精确hash/字节长度解析前序可见assistant全文，再用既有materializer核对当前F1所绑定的代码，
不因位置变化关闭原检查。原第四请求的独立离线核对通过、进程exit0；旧相邻模式、生产函数的引用/不同全文分支、
错误引用、缺全文和引用另一版本的12项断言均完成。但pytest在100%后收尾未退出，两次子任务测试及一次禁用
第三方插件的同范围复验均被中断，不计完整pytest通过，也不认定插件就是原因。此局部测试工具收尾问题尚未定位。
[离线结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/auditor_008_visible_c1_353a1738/offline-audit-result.json)
保留原错误与新解释；新auditor未用于另一真实运行，未将008第四请求记成发送。

后续两小时窗口内，faulthandler将收尾停顿定位到`_pytest.cacheprovider.pytest_sessionfinish`调用
`tempfile.mkdtemp`创建缓存目录。显式设置可写短`cache_dir`后同12项测试完整通过，1.95秒、exit0；
此前中断记录仍保留，不倒改为通过。见
[缓存路径复验](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/auditor_008_visible_c1_353a1738/pytest-cache-location-result.json)。
修正版auditor随后用于独立009，结果如下。

证据：[008结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_008/actual/summary.json)、
[第四请求检查](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_008/actual/request-004.json)、
[单Store查询](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_008/actual/execution-query.json)。

### 0.13 独立009：真实修订完成，当前模型/profile仍未修复

009使用新auditor，真实runner先对008四份保留请求零网络复验，直接C1与引用C1均通过；
固定177文件，HEAD62a996b，生产代码相对54dff43没有变化；原006+r6、Feature/Evidence/c760、
Qwen3-Coder digest、5模型/6新窗口/32768观察字节和原矩阵保持。首轮44241字节及hash与008相同。

5次真实POST及5次响应，另4次身份GET，0回放；worker持续453.04秒。
第1轮请求5个edit位置，3新＋2复用；第2轮请求4个supporting，均复用；第3轮生成原失败代码；
原矩阵33/36。第4轮收到新F1与可见C1引用后请求001/005，2次均复用；结果实际进入第5请求，
第5轮完整修订仍等于原代码，矩阵再次33/36。原始响应hash两次均2b4f580c...b720df。
累计11次工具执行=3新窗口＋8复用；第二/第四轮没有新增源码，不声称所有回合均取得语义进展。
最终`PATCH_BEHAVIOR_CORRECTION_FAILED`；无验收器或预算拒绝，无新Proposal/Review/Dry-run/Apply/Build/Runtime。
这证明当前执行路径能够完成真实反馈、工具往返、修订和重验；该输入/模型/profile组合没有产生有效修复。
不继续为同一30B轨迹追加特殊规则；另行准备同冻结输入的本地27B独立比较，不覆盖009、不宣称通用模型no-go。

证据：[009实际记录](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_009/actual/summary.json)、
[第五实际请求](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_009/actual/request-005.body.json)、
[查询](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_009/actual/execution-query.json)。

### 0.14 两小时窗口：独立模型对照、Graph回流、资格路由和查询修正

010只更换独立目标模型为本地`qwen3.6:27b`，digest `a50eda8ed977ab48a12431878896b27ffd5cef552c17af3317d9623b939a7f1e`。
与009首轮请求相比只有顶层model字段不同，原006+r6/Feature/Evidence/c760/预算/矩阵保持。
首轮真实选择ResetStoredCrosshair、SetStoredCrosshair、RefreshCrosshairSize与GetCrosshairSize支持位置，
3个新窗口＋1次覆盖复用进入第二请求，显示不同模型行动可由同一工具合同处理。
第二请求57650字节已发送，但600秒后超时；2次POST/1次完整响应、没有代码或矩阵。
CLI总783.36秒，终态`PATCH_AGENT_PROVIDER_TURN_FAILED`；不能称27B修复失败或成功，也没有扩大超时重试。
[010实际结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_010/actual/summary.json)。

**A4实现**：aa4e00f在既有Graph中消费明确human finding，或共享worker对已绑定原C1/F1发出的合法上游请求；
conditional回同RepairPlan→Evidence/Coverage或ModelPlanning→新Plan并END。普通Patch错误不自动升级Evidence。
旧有效＋新Evidence全集重新Findings；不复制旧模型收据冒充Fresh，不给operator targets兜底。
模型请求绑定当前失败版本，避免同Plan sibling错绑；旧Plan用户澄清继承，selector反馈在finally恢复避免串任务。
新行为验证产生F1后尚未重绑时明确拒绝，不声称所有回流阶段都已自动接通。
现有CLI尚未装配该入口的Evidence/Planning providers；实际自动链的公开面为原Graph API，没有新增CLI、Graph或Artifact类型。
b792c41补可选既有run_id，区分preview/actual执行，request_id仍标同一逻辑请求。

验证：隔离checkpoint283项为282通过＋1个冻结fixture的CRLF差异失败，Git原blob字节下定点复验通过；
主仓整合后44项交叉验证通过36.93秒，run_id补充后19项通过27.04秒。

**A7实现**：7b82698给原`continue-fresh-patch`增加可选`--qualified-model-routing`；
角色由本次initial/repair上下文决定，显式参数冲突拒绝。没有资格配置时，原显式模型路径不增加资格门。
资格必须来自至少3个不同Feature任务，绑定固定expected_check_ids、模型digest/profile/worker指纹、验证环境和输入身份。
最后worker实际响应→完整raw→原native generator与materializer→最终matrix/Proposal/Review/Dry-run相互核对；
仅有qualified标签、成功schema、Review通过或自报检查数都不够。CLI及直接API缓存返回前重验下层资格事实。
所有新显式试验记录worker指纹，历史缺失保持pending；无自动fallback或新写入/披露权限。
完整正例为离线Repair角色，不声称initial正向资格或真实模型资格已通过，也没有发布真实qualified profile。
主仓A4/A7联合177项为176通过，唯一旧asdict schema测试漏排除新的空routing字段；596dae5只修测试期望，定点通过1.65秒。
详见[资格路由使用说明](../MODEL_QUALIFIED_ROUTING.md)，不是第二任务队列。

**工具与外部依赖**：75f4d49修正工程认知的Fresh/API误报，按CLI→Fresh→Evidence实际回调源码显示可选增强，
仍明确source wiring不等于自主查证或API语义验证；48项查询/投影测试通过14.40秒。
A6实际调用现有单向exporter返回not_configured，没有序列化/enqueue/flush；没有已配置endpoint/项目凭据/具体sink适配，
本地服务本身是否存在未全面核验。SDK未在当前Python安装，未安装/部署/读取额外秘密或发送网络。
[A6记录](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/a6_langfuse_readiness_20260906.json)。

### 0.15 真实A4 Planning：结构事实与语义裁决分开

首次001真实Graph零网络预览body45866＋4096输出=49962>49152，未发送。
Planning角色只输出目标选择JSON，002将其输出预算改为2048，Patch预算不变、不删原材料；47914准入通过。
002固定7b82698，经原Graph create_repair_plan→create_implementation_plan实际发送1次Qwen3-Coder请求，
产生Plan `9f0f4ed3e96e3f324f90e8ba90a736eb3d20e4956a9693a711a9c2ce558d0c0c`，新Patch input preflight通过。
旧c760/source不变、Evidence未重算、Patch/Apply/Build/Runtime均0。
模型选择6目标，但rationale错误声称selected包含Loader；实际只有Configuration与SpreadPatches编辑范围。
独立语义review判needs_evidence：四个共享owner有支撑，constructor/Get(float)必要性说明不足；
不因目标数量多而否决，不因OnFileChanged退supporting就把它视为重启验收缺陷。First Shot绝对准确尺寸澄清确实保留。
[002结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/a4_planning_actual_002/actual/summary.json)、
[002语义review](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/a4_planning_actual_002/semantic-review.json)。

003在同原输入上添加已核验的短语义finding，未给正确目标列表或代码，实际1次Planning调用后生成
Plan `3075cde29024372e3ef7c9a1c95241688ad5543a283655fc510804da39e13bb3`，结构及preflight通过。
但只选择Config的BindAll/header/constructor，却继续声称覆盖Config/Loader/Spread三文件；未用于Patch。
实际输入9个合法可选ID仍含Override和Update，source_identity_table映射及源码正文正确，不能归为程序禁止选择Spread。
[003结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/a4_planning_actual_003/actual/summary.json)。

针对可能的共享表查阅负担，2e746c7仅给可编辑项内联原有完整source_path，仍保留共享表/原ID/源码/全部约束，
并拒绝内联值与表冲突；32项相关检查通过26.79秒。该表示改进不自行证明模型语义更好，最后一次004对照单独记录。

004保持003全部finding和预算，仅表示改变；真Graph preview46908＋2048=48956<49152。
实际1次模型调用，形成Plan `029834a7bf92fd4ab5cc976bb93c4114cebed8a4feb6614844c61f25e3e5f7e8`并通过Patch preflight。
模型现在逐个正确说明6个ID对应的Configuration/Spread方法，Loader错配消失；所选集合与002完全相同。
这只证明本次文件/ID对应改善，constructor/Get(float)仍只有功能角色描述，缺必须编辑的需求/失败因果依据，
所以语义review仍needs_evidence，不继续Patch、不替换c760，也不追加模型尝试。
[004结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/a4_planning_actual_004/actual/summary.json)、
[004语义复核](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/a4_planning_actual_004/semantic-review.json)。

19:22开始的两小时窗口内，真实模型POST为009的5次＋010的2次＋Planning002/003/004各1次＝10次，
完整响应9次（010第二次超时）。所有preview、离线fixtures和模型身份GET均不混入此数。
窗口未形成通过原矩阵的新Patch，没有Mod Apply、changed Build、Runtime或发布。

为后续合法新Plan准备的实例化case factory仅在scratch：通过manifest核验exact Plan、原B0和完整bindings，
历史owner按物理身份映射为相关位置，新输出失败默认unknown，不冒充原根因；旧adapter/wrapper与原Harness源码均未改。
002未获语义通过，因此仅用于零模型构造和3个负向身份检查，未执行Patch或矩阵。
[实例化准备](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/replan_support/preparation_result.json)。

### 0.16 决策指导、上下文与整链适配（2026-09-07）

本轮复用原Graph与Proposal/Review schema，新增的本地provider配置只装配现有owner。
接口说明见[Patch上游续接](../PATCH_UPSTREAM_CONTINUATION.md)，配置不是授权或第二队列。

实际实现及边界：

- 失败指导围绕原需求、被观察否定的假设、缺失事实和合法下一步；保留直接修订、必要复核及上游请求。
  不要求每次读取新增源码，不给First Shot正确实现，不以代码不同替代行为改善。
- 工具说明明确读取的是B0基线，当前被测代码是失败所引用的完整assistant输出；API读取仍是保存的Evidence。
  连续纯引用防循环状态原本不会跨新失败恢复段继承，未修改停止条件；新增跨段复核回归。
- 真实worker形式的合成C1→不同C2→新F2→上游请求现在核验实际response sidecar、物化代码、报告及入模F2，
  原C1/F1保留历史。live与从保存记录进入Graph两条路径均消费新的admitted context。
- `--patch-upstream-config`在现有CLI装配Query、Findings和Planning；必要时旧有效与新Evidence全集重算。
  新Plan重新建立worker、Binding和上下文，不沿用旧prepared input；同一验证器实例连续保存报告，接收当前Plan。
- 原Reviewer在新增Evidence路径暴露了旧源码片段预算不足，修为按新Plan/Evidence重新计算，未放宽Review。
  原RepairPlan编辑子集从新Plan的活动审查输入移除，只保留历史血缘；新Proposal仍经原Review/Dry-run。
- 所有角色共享模型调用上限；新worker继承剩余读取和观察字节，包含已用失败反馈。零读取额度允许直接生成。
  超时不重试；阶段计数按已发生节点保存。预算消耗表示已预留/尝试，实际HTTP发送和响应另看transport记录。
- 同journal保留`patch_execution_segments`、初/当前Plan与角色调用；查询不把末段factory冒充整条链。
  blocked新Plan和预算耗尽时的最终Plan/Evidence也按Graph实际对象返回；缓存重验这些对象，不退回旧成功Plan。

统一checkpoint命令：

```powershell
python -B -m pytest tests/unit/test_patch_upstream_cli.py tests/unit/test_patch_upstream_replanning.py tests/unit/test_patch_upstream_budget.py tests/unit/test_patch_agent_loop.py tests/unit/test_patch_source_coverage_reuse.py tests/unit/test_patch_recovery_worker.py tests/unit/test_patch_behavior_feedback.py tests/unit/test_patch_execution_index.py tests/unit/test_patch_repair_cli.py tests/unit/test_patch_repair_continuation.py tests/unit/test_model_qualification.py tests/unit/test_patch_worker_configuration.py tests/unit/test_patch_read_accounting_admission.py tests/unit/test_patch_covered_source_cli.py tests/unit/test_patch_visible_revision_context.py tests/unit/test_fresh_planning_continuation.py -q --tb=short -n 2 --dist=loadfile -o cache_dir="$env:TEMP/upstream-check-cache" --basetemp="$env:TEMP/upc-$PID"
```

335 passed，204.14秒。其后最终输出引用修正的两个公开CLI负例通过（8.70秒），
预算耗尽后新Plan查询的独立案例通过（1项，4.15秒）；不把重叠验证相加。
新模块与修改后的专属测试Ruff通过；local_entry原有10项、Graph原有2项lint问题未混入本轮清理。
六份用户原有WIP字节未变。上述全部为离线工程/合成项目验收，无真实模型质量或GTFO Runtime结论。

尚未证明：真实模型会在合适时自主请求上游；真实AccurateCrosshair使用新Plan的验证适配；多上游周期；
qualified路由与A4的组合资格；跨任务稳定性。原c760仍为P0所选Plan，002/003/004未晋升为可用修订。

### 0.17 011零网络预览与指导去重

011固定`d6eda97`与181份文件，真实公开CLI预览在发送前停止：body45,066字节＋4,096输出预算
=49,162，超过现有49,152代理准入线10字节。实发0、响应0、矩阵0；内部1表示客户端进入，不能记为模型执行。
原预览和冻结文件均保留，没有中途修改后接续该attempt。

与009首wire精确比较：原22,428字节核心语义输入和7,443字节C1逐字未变，三项F1、5个bindings及源码未变；
增加的825字节来自通用指导、B0说明与工具描述。合并重复指导后，离线重新序列化为44,560字节，
只改变`messages[3].content.required_action`，其他消息和该对象其他字段不变；没有提高预算。

相关验证：`python -B -m pytest tests/unit/test_patch_visible_revision_context.py tests/unit/test_patch_recovery_worker.py -q --tb=short -o cache_dir="$env:TEMP/upguide-cache" --basetemp="$env:TEMP/upguide-$PID"`，18 passed，12.51秒。
这个测量不是模型已接收；独立012将通过同公开CLI预览核验最终wire后才发送，输入/模型/原矩阵保持。

### 0.18 013：真实自主上游请求，仍无代码修复

012通过字节准入后，旧auditor的`C2_requirement_directive_present`仍要求两个旧英文子串，误拒绝新指导。
B0、8项原语义、完整C1/物化及三项F1全为true。新独立auditor绑定`925790d`和local_entry文件hash，
只将该项改成与当前生产`_revision_messages`产生的完整指导逐字比较；不改wire，不取消其它校验。
9项离线检查通过，含缺需求、错误基线、缺C1、错误指导、损坏引用与缺引用全文的拒绝；旧auditor与012记录不变。
[审计器验证](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/auditor_013_current_revision_925790d/result-v2.json)。

013固定`925790d`、181文件、原006+r6/Feature/Evidence/c760、Qwen30B与原5模型/6读取/32,768观察字节。
公开CLI preview与实际首wire逐字一致（44,560字节）；第二实际body62,989字节已发送并收到响应，
两次真实返回记录的输入token分别为12,133和17,429，不能用JSON字节当token数。
实际2次POST/2次响应，另1次模型身份GET，0回放；总176.91秒。
首轮5个edit读取为3新窗口＋2复用，进入第二实际请求。第二轮原生调用`request_patch_upstream`，
required_owner=evidence，理由是需要理解FirstShotPatches相关行为；没有返回代码。

三个refs对应ResetStoredCrosshair、GetCrosshairSize(float scalar)、SetStoredCrosshair。第二请求仍有
`inspect_plan_binding_source`，action为`inspect_or_finish_or_request_upstream`，没有force_final。
Get正文已在此前edit001窗口中，FirstShot两个方法尚未读；三个refs均在当前read enum。
按生产codec只读测量，该批需1新窗口＋2复用，共5,308字节，小于当时2新窗口/5,839字节额度；
此测量不是新执行、不是模型已读。请求合法但上游必要性未证明，不因它声称需要Evidence就自动扩大Plan。

终态为`PATCH_AGENT_UPSTREAM_REQUESTED`（外层failure class为LocalEntryError）。本次case verifier仍固定c760，
没有启用真实A4 providers，因此没有实际取证/重规划。新代码0、矩阵0、Proposal/Review/Dry-run/Apply/Build/Runtime均0。
不能把013写成又一次33/36，也不能写成新策略已提高修复成功率；它证明了该次工具观察后模型自主选择上游。
本轮真实尝试到此停止，尚无通过原矩阵的Mod修订。后续应区分已有引用读取与上游重新评估的决策，
以及领域验证器对新Plan的适配，不把这次选择当作旧Plan错误的证据。

[真实运行记录](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_013/actual/summary.json)、
[只读查询](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_013/actual/execution-query.json)。

### 0.19 一次工具语义收敛：用途与真实执行后果

定点核查确认：013当时的上游工具只写“Request Evidence or Planning assessment”，没有说明
该配置会保存请求并停止，也没有区分普通读取与Evidence判断重评。歧义存在，但不直接证明它导致013的选择。

本轮只改工具描述及当前配置事实的传递：

- 读取工具返回已登记正文；上游工具重评支持/冲突/覆盖判断或Planning范围。已有refs仍可有依据地重评。
- Graph共同入口在worker启动前绑定`upstream_effects`，覆盖公开CLI及直接Graph。
  各owner分别声明`record_and_stop`、`assess_then_stop`、`assess_and_continue`或`provider_unavailable_stop`。
  新Plan的自动周期结束后继续保留上游工具，但如实声明保存后停止。
- 初次生成、行为修订使用同一声明；两工具参数schema、read enum、reason格式、权限和实际Graph路线未改。
  没有新增诊断JSON、指定FirstShot函数、隐藏上游工具或把上游请求改写成读取。

验证：8项独立工具/直接Graph场景、6项公开CLI相反场景通过。既有ref可以直接读取后完成，
也可以以query=[]复用已有Evidence、真正重算Coverage后继续；无需为了测试强制找新引用。
统一checkpoint命令：

```powershell
python -B -m pytest tests/unit/test_patch_tool_effects.py tests/unit/test_patch_tool_effects_cli.py tests/unit/test_patch_agent_loop.py tests/unit/test_patch_recovery_worker.py tests/unit/test_patch_source_coverage_reuse.py tests/unit/test_patch_upstream_cli.py tests/unit/test_patch_upstream_replanning.py tests/unit/test_patch_upstream_budget.py tests/unit/test_patch_repair_cli.py tests/unit/test_patch_verified_replay.py -q --tb=short -n 2 --dist=loadfile -o cache_dir="$env:TEMP/tool-effects-cache" --basetemp="$env:TEMP/te-$PID"
```

185通过、2项旧英文措辞断言失败（74.93秒）。将这两项改为核对实际模型工具历史展开后的B0字节、
当前代码及失败绑定，保留Windows原始换行，定点2项通过（1.21秒）。不写成一次187项全绿。
这是仓库现有测试的适配，008/012验收器与全部历史输入均未修改。

按013原wire只重建工具描述及能力声明字段，44,560→44,881字节；加原4,096输出预算为48,977，
低于49,152代理线，余量175字节。其它消息、B0/C1/F1、原需求和工具参数schema不变。
这是离线字段成本测量，不是新preview、真实模型消费或后续全程准入保证。
[成本核对](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/tool_effects_013_cost.json)。

本次工具语义工作到此收口，不继续对FirstShot做连续提示微调。真实动作选择与任务结果仍需独立模型试验，
Langfuse真实出口、固定多任务Eval与部署交付按各自条件推进，不以该case成功为前置。

### 0.20 A5：API来源传播、第一次真实失败与编辑提示域修复

`ceeb1b6`将已有API身份传到原Findings/Planning输入：`source_authority`、`source_hash`、
`module_mvid`、`metadata_token`和`signature_blob`保留原值；当前来源、参考来源与缺失信息不互相冒充。
明确说明metadata或interop包装不能证明游戏Runtime，也不授予编辑权限。该提交是输入传播与接线，
不是自主API发现、正确语义判断或Mod交付。

**第一次真实运行：**人工选定来源与symbol，复用原Feature全部义务；输入只有4项API，没有Mod target_source。
`current_and_reference`实际发送一次到本地`qwen3-coder:30b`并收到完整响应；
`reference_only`与`no_api`仅做零网络预览，不构成三组真实消融结果。
请求31,019字节，body SHA `0cfca41f48367bfb68f6b5c7ce5ee64471d16763328679cbf1a41f6d38936571`；
记录8,521输入及668输出tokens。实际payload与预览一致，中文请求未出现Unicode替换字符。

| 记录 | 核验事实 |
|---|---|
| [冻结输入](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/a5_api_semantic_001/frozen-inputs.json) | `maximum_model_calls=1`、`target_source_included=false`，无Planning/Patch执行 |
| [实际请求引用](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/a5_api_semantic_001/actual/sent-request.json)与[冻结provider请求](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/a5_api_semantic_001/preview/current_and_reference/frozen-provider-request.json) | provider请求文件SHA `837335028ba244375291b27e79bc8160ab1df6a1c14a5474c9c1414ce58dddbf`；实际schema把4个API ID同时列进引用域和编辑提示域 |
| [原模型输出](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/a5_api_semantic_001/actual/response.json)及[provider原响应](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/a5_api_semantic_001/actual/raw-provider-response.json) | 九项关系均仅引用`evidence_dc1dd1a02b199c2121cb32eb`并返回support，relation 1还将该API列入`edit_target_evidence_ids`；原文件未改 |
| [最终运行记录](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/a5_api_semantic_001/actual/summary.json) | `findings_audit[0]`明确记录首失败`REQUIREMENT_COVERAGE_EDIT_TARGET_IDENTITY_INVALID`；随后内部修正callback被一次调用预算挡住，未发生第二次发送 |

该ID指当前interop `Modules-ASM.dll`的`Dam_EnemyDamageBase.BulletDamage`，
`source_authority=authoritative`、`source_type=decompiled_api`、`span=null`，token为`0x060023B4`，
MVID为`85155e68-33a5-4fa5-a419-c563e7ea5e60`。它是当前程序集API身份和interop调用包装的证据，
不是可修改的Mod源码；包装中的`il2cpp_runtime_invoke`也不证明真实踉跄分支、黄色X或音效行为。

此次有两个并存的问题：模型违反已有target-source编辑提示规则；程序的response schema又把可引用域和
可编辑域混在一起。确定性层正确拒绝了非法位置建议，没有发生越权写入。独立只读审查不能认可九项全support：
修改位置、call timing及全部preservation义务不能由这一API单独证明。不能由身份拒绝反推每项语义都被自动判错，
也不能因模型选择了当前来源的ID就宣称其理解了版本差别或完成正确API语义消费。

**通用修复（本节记录时为WIP）：**从原Coverage validator抽出`is_exact_edit_target_evidence`供两处共用，
原条件逐项保持：确定性来源、`target_source`、非空路径、合法整数span及已有source/file/doc hash。
生产Findings对整个retrieved_pack计算编辑提示域，不按某一关系缩小全局合法目标；API继续保留在完整可引用域。
API-only编辑数组使用`maxItems=0`，允许`[]`及missing判断。旧直接schema调用者保持可选参数兼容；
所有生产Findings调用明确传入合法域。没有新增权限、修改模型预算、改变API来源等级或规定业务修法。

[原Actual回归输入](C:/Users/10160/.codex/visualizations/2026/08/11/019ff15f-9eac-7b13-aad5-faffde4b36b7/rag_capability_mainline/tests/fixtures/evaluation/findings_api_only_actual_001.json)
保留原schema、响应、API输入和来源引用；[专属回归](C:/Users/10160/.codex/visualizations/2026/08/11/019ff15f-9eac-7b13-aad5-faffde4b36b7/rag_capability_mainline/tests/unit/test_findings_edit_target_domain.py)
先证明“原schema接受→原validator拒绝”，再检查API-only、混合源码、多关系完整目标池、missing与旧caller兼容。

```powershell
python -B -m pytest tests/unit/test_findings_edit_target_domain.py -q --tb=short --basetemp="$env:TEMP/a5dom-green-$PID" -o cache_dir="$env:TEMP/a5dom-gc-$PID"
python -B -m pytest tests/unit/test_findings_edit_target_domain.py tests/unit/test_requirement_coverage.py tests/unit/test_api_semantic_consumption.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP/a5dom-cp-$PID" -o cache_dir="$env:TEMP/a5dom-cpc-$PID"
```

结果分别为4 passed（1.36秒）与115 passed（19.46秒，2个既有warning）；集合包含关系明确，不相加为119项。
Ruff及`git diff --check`通过。原Actual001、runner与冻结输入未写，原输入/响应hash回查一致；修复验证新增模型调用为0。
关闭的是schema与身份校验不一致这一首失败，不是九项support的语义质量。API正确语义消费、自主API发现及下游
Planning/Patch结果仍未证明；该A5工作没有新Mod代码、行为矩阵、Apply、Build或GTFO Runtime结果。

### 0.21 A6：复用原查询的历史追踪导出与评分关联

`src/observability/patch_langfuse.py`消费原`project_patch_executions`只读结果，
不改旧Projection V2白名单，不运行Graph、Patch、Repair或行为检查。用既有httpx实现
OTLP/HTTP JSON发送、分数发送和有界分页/延迟查回；不引入新SDK、状态数据库或控制面。

导出内容限于运行状态、已有计数、hash、经过过滤的身份引用。没有源码、提示词、原模型正文、
完整路径或自由文本诊断。历史导入明确使用导入快照时间，原事件时间未知；不能把它用于宣称
原始generation时延、成本或完整因果时序。实际目标仍需单独配置并确认导出范围。

独立审查发现并复现：另一份检查数量相同的矩阵可被错误挂在已核验报告后，产生错误分数。
修复在原score生成owner核验报告对矩阵的精确path/hash引用、执行状态、被保留代码字节、
源码身份及已声明共同身份/分母；缺失或不一致时`score_eligible=false`，追踪仍可导出。
旧矩阵可经报告的精确引用绑定代码，不伪造其原本没有的字段。

```powershell
python -B -m pytest tests/unit/test_patch_langfuse.py tests/unit/test_patch_execution_index.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\lf-score-check"
```

65 passed，20.38秒；Ruff和diff检查通过。反例先证明评分错绑，再证明修复拒绝错绑；HTTP替身
覆盖成功查回、重复准备、部分接收、超时及尚不可查回。真实009的零网络prepare仍返回21个历史
观察和两个33/36局部检查分数；这次检查只输出到终端，没有虚构保存文件，也未重跑模型或矩阵。

真实Langfuse Cloud/自托管服务的接收、持久化、页面显示和查回仍未验收。
已实现的是导出消费代码与离线验证；不是实时全链追踪、模型资格或Mod修复。
配置、接口与边界见[PATCH_LANGFUSE_IMPORT](../PATCH_LANGFUSE_IMPORT.md)。

### 0.22 A7：固定真实源码任务与实际行为基线

新准备器`python -m scripts.prepare_patch_eval_suite`使用原`patch_qualification_tasks_v1`合同、
ArtifactStore和`preflight_patch_continuation`；选定任务后输出原`continue-fresh-patch`参数。
默认只准备/准入；只有显式执行才进入模型。没有新的执行控制面或资格结论。

冻结任务集为`artifacts/peval7/suite.json`，SHA
`0c86555524bfb1a2086a546c8735ab5ced7a98a07fdd6feb1871460f57df2ba3`。
三个Feature分别是独立Eval请求下的Follow Recoil默认值保持、SpreadAPI非法输入保持、原Accurate Spread切换。
前两项是新Eval任务，不能冒充用户要求修改生产默认配置。原P0的重复Repair不增加独立任务分母。

| 任务 | 当前实际结果 |
|---|---|
| 配置默认值任务 | `artifacts/peval7/c1/baseline-verification.json`：3个独立C#进程，5项检查中新增要求1项失败、原行为4项通过 |
| 公开API输入任务 | `artifacts/peval7/c2/baseline-verification.json`：5个独立C#进程，17项检查中非法输入12项断言失败、正常行为5项通过 |
| 原P0任务 | 沿用原36项矩阵；这轮未重跑，不产生新的33/36或修复结果 |

使用原始C#输入、明确的依赖替身、固定.NET7 compiler/references/runtime，在短临时目录编译运行；
不把源码字符串匹配当行为判定，也不称GTFO Runtime。原输入有来源hash，没有导入正确修订答案。
两个新任务的支持关系与目标选择明确为人工编排，不证明模型Evidence/Planning质量。
各attempt的报告按既有response路径隔离，避免覆盖同名matrix；旧报告不改写。

```powershell
python -B -m pytest tests/unit/test_accurate_crosshair_eval.py tests/unit/test_patch_task_suite.py tests/unit/test_model_qualification.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP/a7suite-cp-$PID" -o cache_dir="$env:TEMP/a7suite-cache-$PID"
python -B -m scripts.prepare_patch_eval_suite --suite artifacts/peval7/suite.json
```

24项checkpoint通过，84.29秒；之后报告隔离和反馈调整的8项受影响检查通过，11.29秒，不相加计数。
root在当前工作树再次执行第二条零网络准入：3/3 admitted、`model_calls=0`、`task_success_rate=null`、
`models_qualified=false`。Ruff/diff检查通过。详细用法见[MODEL_QUALIFIED_ROUTING](../MODEL_QUALIFIED_ROUTING.md)。
更强外部模型对照仍需独立自有代码任务；本节GTFO来源任务不因此获得外发许可。

### 0.23 外部千问复用同一个Patch/Repair执行器

`src/mod_agent/external_patch.py`提供显式`ExternalQwenPatchProfile`和
`run_external_patch_continuation`；原`local_entry.py`只抽出模型身份准入、响应身份核验和
provider生成元数据3个hook。本地类及旧收据默认保持，外部实际标记`qwen_chat`、
`model_digest=None`，不能伪造Ollama二进制身份。复用原continuation、Graph、worker、
行为反馈、Proposal、Review和Dry-run，模型调用预算仍由同一worker配置传入。

首版只支持明确清单中的独立target_source；不接受decompiled_api、隐式fallback、旧Ollama回放、
本地qualified路由或外部A4自动续接。请求先核验本轮披露记录、目的地、源码manifest；
每次实际wire分别记录hash、bytes和披露类别，代码/行为反馈出现时需要对应已有批准类别。
模型目录只证明被列出，不证明生成服务可用或任务质量。实际模型字段缺失/漂移在工具执行前停止。

独立审查用HTTP 200且`choices=[]`复现解析前原响应丢失；修复在现有sidecar保存有界响应后才调用
AgentTurn parser。非法JSON、非UTF8、错误模型和超限保留明确原文或编码/前缀；超限不伪造完整hash。
HTTP接收、JSON解码、AgentTurn解析和最终准入分别记账，不把HTTP 200当合法输出，不自动重试。
实际反馈类别也同步到已有model_admission视图，避免同一请求的记录互相矛盾。

旧Local与首版外部联合76项通过（47.02秒）；后续保留修复的专属18项通过（28.18秒）。最终相关检查：

```powershell
python -B -m pytest tests/unit/test_external_patch.py tests/unit/test_agent_turn_adapters.py tests/unit/test_patch_recovery_worker.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP/ext-retention-cp-$PID" -o cache_dir="$env:TEMP/ext-retention-cpc-$PID"
```

57 passed（30.71秒），Ruff/diff检查通过；与前述集合重叠，不合计。
HTTP替身实际走过源码工具、合成验证失败、再次查证、修订及原Review/Dry-run；
这证明生产机制组合，不证明真实千问生成过正确代码。
本轮真实外部模型目录查询和生成调用均为0，披露批准仍需绑定具体任务与目的地。

### 0.24 独立自有C#配置任务：近真实模型对照的可执行输入

`tests/fixtures/patch_eval/owned_config_service`为新编MIT输入：3个C#源码文件、JSON磁盘存储、
命令行入口，没有GTFO源码/API、历史Mod修订或正确参考实现。当前变更要求为`maxRetries`
只接受JSON整数0–5，拒绝7类非法值并保持磁盘字节不变；保留合法值、未知键、服务名、重启读取
和原JSON语法错误处理。它是一个初筛任务，不代表完整领域难度或3任务资格。

准备器复用原FeatureSpec、RgLive、Coverage、ImplementationPlanner、ArtifactStore与
continuation preflight，产出原`continuation-input.json`和`worker.json`。
支持关系和单一Update编辑范围明确为人工编排；不声称自主Fresh/Planning。
本地可用原`continue-fresh-patch`，外部可用原`run_external_patch_continuation`。
没有第二个模型runner；每次真实执行仍需独立attempt/profile和适用授权。

有效输入为[owned_config_service_005/task.json](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/owned_config_service_005/task.json)。
固定.NET7 csc/reference/runtime编译成功，23次独立应用进程检查真实stdout与磁盘：
7项新增校验要求按预期失败、8项保留行为通过。模型输入只含程序源码与需求，不含判定器或正确修订。
判定器按原response路径隔离报告，编译错误、环境失败和行为失败分开记录。

001/002保留NuGet环境失败；003/004为编译方式过渡准备。005已改用既有直接csc路径，
不再恢复NuGet、读取用户配置或延伸A8环境建设。子进程环境使用明确白名单，但这仍不是完整OS沙箱声明。
4项`tests/unit/test_owned_config_task.py`聚焦测试通过（7.11秒），最终005基线另真实运行通过（7.36秒）；
Ruff通过。无模型调用、外发、产品Apply或游戏操作。

source-disclosure-preview明确`approved=false`；MIT身份和源码清单不授予外发权限。
后续真实对照保持同一源码、需求、Plan、检查集和共享worker，分别记录profile与预算。
当前没有产生通过15项检查的模型修订，也没有验证审批退出/恢复、Apply、正式Build和交付查询全链。

### 0.25 DSH：真实宿主、原后端查询与纯命令结果显示

`integrations/dsh-mod-agent`实现`/mod-runs`和`/mod-status`人类命令，调用原Python
`verification-claims / patch-execution`只读查询；不向DSH模型注册产品执行工具。
固定官方DSH 0.1.2-rc.1、Node 24.19.0，独立DSH_HOME，服务只绑定127.0.0.1:3087。
配置指定Python、仓库、Store和Feature；命令不能指定任意路径或Shell。

实际装配中发现并解决三个接缝：

- DSH patch中的name是匹配断言，不能直接改旧目录选择器类型；现禁用auto并组合官方browse前后端。
- stock agent-loop还拥有session factory，整项禁用会导致新建会话失败；现保留factory，使用官方
  `agent/pre-step`拒绝模型step。title模型和遥测等另按查询专用配置关闭，不另写Agent。
- 原chat target把纯command排除在active内容之外；只读客户端activity target激活原会话外壳，
  原CommandNodeView/GenericCommandCard继续显示原command结果。没有伪assistant消息或复制renderer。

```powershell
$env:DSH_RUNTIME_NODE_MODULES='C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/dsh-runtime/node_modules'
$env:MOD_AGENT_PYTHON='C:/Users/10160/miniforge3/python.exe'
node --test integrations/dsh-mod-agent/tests/*.test.mjs
```

8项通过（2.266秒），含真实Python查询与published DSH组件，0skip。
真实UI创建session并执行013的精确`/mod-status`：原session JSONL保留command/run和command/done，
返回`partial`、`PATCH_AGENT_UPSTREAM_REQUESTED`、`proposal_admitted=false`。
重启官方宿主后，CUA在真实页面展开并核对了相同结果；没有以工具成功宣称Mod完成。
证据摘要为[readonly-acceptance.json](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/dsh-runtime/readonly-acceptance.json)。

该查询没有模型事件、行为验证、产品Apply或游戏操作。普通消息的pre-step拒绝有局部测试，
没有作为独立真实transport试验验收；不能扩大为所有DSH插件/任意输入都已隔离。
任务提交、diff审批、任务取消、产品执行恢复、完整交付和界面易用性仍需后续真实验收。
配置与兼容边界见[插件说明](../../integrations/dsh-mod-agent/README.md)。

### 0.26 同一自有任务的真实部署组合首筛

三次运行均消费`owned_config_service_005`原3份源码、1个Update编辑位置、相同Feature/Evidence/Plan、
原15项判定与同一worker配置，冻结生产HEAD为`b5b51d1`。未将前一模型输出交给下一模型，
未改应用源码、判定器或worker。初稿可直接通过，不强制制造失败。该任务仅为初筛，
不是自主Evidence/Planning、共享状态复杂任务、GTFO或跨任务资格验收。

| 运行 | 真实结果 | 原始记录 |
|---|---|---|
| 本地`qwen3-coder:30b` | 5请求/5响应，151.14秒；第3轮与第5轮代码字节完全相同；两次编译均因`CS0103`未解析Environment失败，行为检查未执行 | [local记录](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/owned_config_local_001/launcher-result.json)；journal `fc26256c9feb498441ea73f55784929c.json` |
| 云端`qwen3.6-plus` | 5请求/5响应，22.80秒；第3轮代码因Console/Environment未解析编译失败；第5轮请求Evidence上游，没有修订输出，行为检查未执行 | [Plus记录](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/owned_config_cloud_001/launcher-result.json)；journal `b5f7cc371dec6fa38a7aafbb306910cb.json` |
| 云端`qwen3.8-max` | 2请求/2响应，19.58秒；第2轮返回说明文字加JSON，strict parser在第1字符拒绝；没有编译或行为检查，不手工摘取末尾JSON | [Max记录](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/owned_config_cloud_max_001/launcher-result.json)；journal `c9bdeb2029e2b7a13fd1f3c9f31dc839.json` |

journal均在自有任务的`store/cr`中，保存原响应、身份、预算和停止事实。
终态分别为`PATCH_BEHAVIOR_CORRECTION_FAILED`、`PATCH_AGENT_UPSTREAM_REQUESTED`和
`malformed_structured_output`。不能将第三个终态当代码编译失败，也不能将未执行矩阵写为0/15。
源码未写回；没有新Proposal/Review/Dry-run/Apply、正式Build或游戏Runtime。
前两组有隔离验证器的真实C#编译；这是正式Build阶段之外的检查。

外部两次均由当前任务用户分别批准，预算各最多5次，目的地使用用户明确给出的北京workspace endpoint。
只发送新编自有源码、需求/绑定及各自运行产生的代码/诊断，没有GTFO材料、判定器源码或API key值。
服务目录查询真实返回可用型号；目录列出不等于生成或质量合格。每次使用独立attempt，未自动换第四款。

**Plus动作审查：**原请求理由描述了现有错误处理关系，并称无需修改import，却未指出哪项
Evidence关系失效或哪项事实不可由当前读取取得。因此请求必要性未证明；不因ref已可读就机械拒绝重评，
也不把这次选择写成正确Replan。

**Max协议核查：**冻结源码`patch_agent_loop.py`在普通回合保留两工具且`response_format=None`；
`QwenChatAgentAdapter`仅对非空response_format发送json_object。真实第2轮仍具两工具、auto选择，
所以该轮没有请求JSON mode。这来自冻结代码和轮次记录，不冒充独立wire正文抓包。
旧`provider_output_mode=json_object_not_native_schema`标签对这些普通轮不准确，原记录保留。
后续只在Patch专用外部provider修正实际JSON mode及其记录，不放宽parser、提取旧JSON或重建Repair。
格式失败在本次已离开worker后被拒绝，没有在剩余额度内自动返回格式修订；不得宣称该分支已通过。

**撤回编码故障假设：**原两次本地编译的6份报告按UTF-8读取，替换字符U+FFFD均为0；
CS0103中文原文完整。查看时的显示异常不能归因为OwnedConfigOracle，也不解释模型失败。
新增中文未定义标识符真实编译回归在旧实现即通过（1项，3.75秒），没有生产编码修复、
修改factory或重写旧Artifact。原项目显式`ImplicitUsings=disable`，并非判定器漏掉已启用的隐式using。

此轮支持的决策是：不能把当前profile当作必然交付的唯一主力；先补确证的协议接缝，
然后接受同一代码判定。Local/Cloud对照同时改变模型与服务/适配路径，不能作纯权重因果实验。
所有First Shot事实仍属于此前P0记录，未因这次自有任务改写。

### 0.27 输出合同、profile策略与实际请求记录分层

针对0.26的Max格式失败，首个WIP曾在`_send`无条件补JSON mode。它只经过离线测试，
没有提交或真实执行；用户要求核对阶段与多种情况后，该草稿已替换为以下显式策略。
不是把“所有模型、所有回合必须JSON”固化为通用规则。

`ExternalQwenPatchProfile.output_format_policy`定义：

- `follow_request`为默认值，遵循本次AgentTurnRequest已有声明；默认序列化省略新键，
  与冻结b5b51d1原profile数据及hash保持一致。
- `json_when_patch_submission_allowed`须显式选择：在当前Patch worker允许直接提交、
  且请求尚无格式声明时补一个JSON object声明。`tool_choice=required`的纯工具回合不强加，
  上层已有的response_format也不被覆盖。显式策略有独立profile哈希。

策略在ExternalPatch角色包装进入原记录器之前应用，所以request hash对应生效后的请求。
通用Qwen适配器仍按声明映射协议，`_send`只计量/发送并保存实际
`requested_response_format`与`requested_output_mode`，不自行决定阶段或改payload。
请求JSON不等于响应有效；实际内容仍经原严格JSON/schema、Binding、编译与行为检查。
原错误标签和失败响应不改写，也不手工提取Max末尾的JSON。

当前worker的非工具输出被视为Patch提交，因此新策略下多数混合回合仍可能请求JSON；
它不限制工具调查顺序。如果以后允许单独的说明文字作为过程输出，则需要明确的非提交
分类，不能用无tool_calls就判最终提交。该普通说明分支和预算内自动格式纠正都未由本次实现。
本次不是通用Repair、Provider全兼容或模型质量通过。

54项检查点通过（42.65秒）：

```powershell
python -B -m pytest tests/unit/test_external_patch.py tests/unit/test_agent_turn_adapters.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\ext-json-checkpoint-$PID"
```

随后默认序列化兼容与import整理经3项针对回归通过（7.34秒），15项先前聚焦结果不相加。
验证覆盖默认策略、纯工具/混合/最终声明保留、原四回合工具与修订链、普通回合直接提交、
非法说明文字仍拒绝/原文保存，以及最终wire hash/字节预算。Ruff/diff检查通过。
测试响应替身只证明合同与装配；没有新外部请求、Model Actual、Mod代码或审批/执行行为。

### 0.28 同一worker内的提交识别、格式反馈与停止分层

本轮补的是允许动作、请求协议、收到输出和恢复路径的对应关系。没有新增Graph、Repair层、
自由聊天回合或任务专用修法；决策仍由模型选择，最终提交继续遵守原JSON/schema、Binding与物化合同。

| 实际输出/故障 | 当前处理 |
|---|---|
| 合法工具调用，可附说明文字 | 执行现有工具合同；附带文字不作为Patch提交 |
| 完整JSON满足当前请求schema | 进入原物化、代码验证、Proposal/Review/Dry-run；格式通过不等于代码通过 |
| 完整但非JSON，或违反原schema | 保留原文与具体错误，未物化；原阶段剩余预算内返回同worker |
| 相同非法提交重复，或模型/观察字节不足 | 明确停止；不新增格式专用额度，也不挪用已预留的行为恢复额度 |
| 截断、拒绝、发送/准入失败 | 分别保留原停止信号或provider诊断；不包装成要求模型修JSON的反馈 |

`code_generator.py`复用原严格整段JSON解析和调用方提供的schema；使用已锁定的jsonschema与
referencing，不建立第二份Patch字段定义，不提取说明文字之后的JSON。schema配置错误独立停止，
不从网络取schema。完整格式错误保留原输出、schema和有界错误位置；新上下文沿用原需求、
B0、被测代码、失败与原生工具历史，格式反馈本身计入现有观察字节预算。

独立审查复现了另一处同边界缺陷：原生`length`或`done=false`已说明输出不完整，适配器却先
解析残缺工具参数。Qwen/Ollama现在先识别停止状态，保留raw/state，但不把残缺参数变成可执行动作。
完整的非法工具调用仍由原工具合同拒绝，没有借此放宽工具解析。

`local_entry.py`为每个worker回合保存生效后的`AgentTurnRequest`正文及hash；该记录不是provider
wire，也不是网络发送证明。外部反馈披露缺失时，第二次客户端请求在发送前停止，原提交轨迹仍保存。
原`patch_execution_index`只读展示格式检查、工具执行和行为检查各自的事实；历史缺少请求正文时
标为unknown，不对旧运行追加新门。未准入文本仅为原响应sidecar，不提升为已生成的正式代码记录。

**能力验收：**公开`run_external_patch_continuation`保留生产配置、适配器、序列化、Graph、共享worker、
物化、Review和Dry-run；替换底层HTTP为预设响应，验证器沿用合成静态marker检查。

1. 读取→说明加JSON→格式反馈→合法代码但行为失败→再次读取→修订→Review/Dry-run：
   共5次替身请求；行为失败位置确有2次模型、2次读取及足够字节余额，并实际消费。
2. 读取→合法代码但行为失败→修订回复格式错误→消费格式反馈后再次读取→修订→Review/Dry-run：
   仍共5次；行为恢复段实耗3次模型/1次读取。最终请求保留C1、F1、格式错误原文、原义务及两次工具结果。

这两条离线路径都没有真实模型推理、真实C#编译或原OwnedConfigService 15项检查。
不强迫真实模型采用该工具顺序；初次直接合规并通过也可结束。

**验证记录（各集合有重叠，不相加）：**

```powershell
python -B -m pytest tests/unit/test_external_patch.py tests/unit/test_patch_submission_cli.py tests/unit/test_patch_execution_index.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\psx-$PID"
# 首次75通过/10失败，49.56秒。定位为query旧缺ref兼容及旧异常断言/fixture问题。
python -B -m pytest tests/unit/test_external_patch.py tests/unit/test_patch_submission_cli.py tests/unit/test_patch_execution_index.py --lf -q --tb=short --basetemp="$env:TEMP\psl-$PID"
# 仅重跑10项全部通过，10.40秒；不是一次85项全绿。
python -B -m pytest tests/unit/test_patch_submission_cli.py::test_public_external_behavior_revision_corrects_format_then_reads_with_same_remaining_budget -q --tb=short --basetemp="$env:TEMP\psc3-$PID"
# 新增修订阶段用例1通过，5.14秒；首跑测试误用段内回合号，按全局记录修正断言。
python -B -m pytest tests/unit/test_patch_execution_index.py::test_retained_request_reference_does_not_claim_send_or_expose_full_prompt -q --tb=short --basetemp="$env:TEMP\psq-$PID"
# 请求正文可查不等于观察送达，显示词修正后1通过，1.64秒。
python -X utf8 -B -m pytest tests/unit/test_agent_turn_adapters.py tests/unit/test_patch_agent_loop.py tests/unit/test_patch_recovery_worker.py tests/unit/test_patch_submission_loop.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\psub-worker-$PID" -o cache_dir="$env:TEMP\psub-worker-cache"
# 首次111通过/1失败，16.23秒；旧测试期待空回复耗尽，现明确记录重复非法提交。
python -X utf8 -B -m pytest tests/unit/test_patch_agent_loop.py::test_loop_uses_remaining_fifth_turn_for_feedback_then_stops_repeated_empty_output -q --tb=short --basetemp="$env:TEMP\psub-empty-$PID" -o cache_dir="$env:TEMP\psub-empty-cache-$PID"
# 更新该断言并核对第5回合消费反馈，1通过，0.81秒。
python -X utf8 -B -m pytest tests/unit/test_agent_turn_adapters.py -q --tb=short --basetemp="$env:TEMP\psub-stopfix-$PID" -o cache_dir="$env:TEMP\psub-stopfix-cache"
# 4项截断参数反例先复现失败；修正识别顺序后本文件29通过，0.26秒。
```

提交解析独立17项通过（0.71秒），较早与原codegen组合106通过（3.26秒），后补的1项不冒充已重跑
整个组合。依赖锁离线一致性检查通过196包。新改动的Ruff通过；local_entry原10项和code_generator
原2项存量lint问题与HEAD逐项一致，本轮未清理。diff-check通过。

**前三组编译输入核查：**同构建配置下原基线能编译，三份源码均在编译集合；未定义的Environment/
Console由模型新增，其所在文件原无System导入，没有发现丢失声明或遗漏编译文件。账本中的完整
F1与原报告一致，Plus末轮明确提到这些错误；历史后续请求未保存完整正文，因此不能声称独立核验过
那些旧请求的全部wire。这一限制由新回合正文记录改善，不回写旧Actual。

**下一步边界：**固定本实现与显式Max profile，沿用原自有源码/Plan、原判定器和5次总预算，
取得本次新增运行授权后才实发。是否编译、15项是否执行/通过、是否有效修订分别报告。
尚未证明Max修后表现、任意provider全兼容、多任务资格、自主Planning或First Shot修复。

### 0.29 修后Max独立真实验收：有效修订、原15项通过

用户在当前任务明确授权这次最多新增5次Max请求，仅沿用原自有源码、服务地址和15项判定，
不含GTFO、不Apply、不自动换模型。原prepared-inputs保持发送前状态；本次授权原文与准入记录
另存frozen-inputs。执行HEAD固定`90cfc27ee1d6833de6c3631e5c69862038553e84`；运行中没有修改
worker、prompt、预算、源码、Feature/Evidence/Plan或oracle，没有导入正确实现或手工提取非JSON回复。

生产入口`run_external_patch_continuation`真实运行36.596秒，5请求/5次HTTP200响应，0旧响应重放；
输入25,391 token、输出1,799 token（缓存输入9,472是输入子集）。现在已结束，没有自动续跑。

| 回合 | 模型实际动作 | 程序实际结果 |
|---|---|---|
| 1 | 读取Program的已登记supporting位置 | 返回当前源码；未增加编辑权限 |
| 2 | 读取Update的edit binding并附说明 | 返回JsonConfigStore全文；工具附带说明未当Patch解析 |
| 3 | 提交完整JSON初稿 | 实际编译失败CS0246，ArgumentException未解析；行为检查未执行 |
| 4 | 消费编译诊断，决定在原范围使用System.ArgumentException；回复说明加JSON | 保留完整原文，拒绝格式，按剩余预算回同worker；该回复未被手工摘取或物化 |
| 5 | 返回合规JSON修订 | 代码实际改变；重新编译成功、原15项全过，形成原Proposal/Review/Dry-run |

共2次隔离编译（1失败、1成功）及23次应用进程，23个不同PID。7项新增输入拒绝要求、8项保留行为
均通过；检查顺序、输入/期望、验证器/环境身份与原任务一致。初稿的0项表示未执行，不是0/15失败。
这是自有配置程序的检查，不是First Shot矩阵或正式Build/GTFO Runtime。

两版代码相对同一B0物化后身份不同；最终Proposal/Dry-run字节与第二报告被测修订一致。
原三份源码hash未变，历史失败报告未覆盖。Review为`approve_dry_run`，`semantic_assurance=unproven`；
人工语义审查、exact approval和Apply未发生。

这次真实证明：源码调查→生成→消费真实编译失败→实质修订→同worker预算内格式纠正→重新验证通过。
失败后没有再读源码，不能描述为本轮触发了失败后调查；该分支可达性仍是0.28离线证据。
5次请求均记录JSON object，但第4次仍为说明加JSON；不能把JSON mode当服务保证或独立成功条件。

证据集中于本次独立目录：

- [启动结果与原journal引用](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/owned_config_cloud_max_submission_001/launcher-result.json)
- [请求/响应/代码与矩阵核验](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/owned_config_cloud_max_submission_001/acceptance-verification.json)
- [原只读查询](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/owned_config_cloud_max_submission_001/execution-query.json)
- [15项真实矩阵](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/owned_config_service_005/verification/model_outputs/bb3aa69f64fdb0ebfae3/evaluation_2/matrix.json)

新journal为`9968c07d8f487a473f4c8714e492f0d1.json`；Proposal `7d3deba5…`、Review `1afa0c16…`、
Dry-run `824cfd68…`，完整refs由以上查询定位。两份报告、矩阵、编译/进程日志和Artifact的hash及
代码绑定经独立只读核验，没有重跑模型/编译/行为检查。生效请求中C1、精确编译F1、格式错原文和原义务可见。

请求核验限制：保存的是规范化AgentTurnRequest及发送时wire hash/字节量，没有原wire正文。
离线重新序列化的5个hash均未复现原wire hash，因此不声称独立重放逐字请求体；核验文件保留这一
不一致，内容检查限于保存的生效请求。没有改写已完成运行或为此展开新平台建设。

本次授权已执行完。此结果记为该任务/当前profile的一次通过样本；旧三组首筛仍为0/3，修后本次
独立记1次通过，不覆盖旧失败。复杂任务、跨任务重复资格、自主Planning、First Shot仍未证明。
下一步应消费这个真实样本选择后续独立任务，不重新扩建提交格式流程，也不自动外发GTFO或Apply。

### 0.30 2026-09-07 两小时并行窗口

当前任务用户授权自主推进两小时，并强调P0修复优先。执行窗口从北京时间19:36:52起至21:36:52；
此处只记录安排和发生的事实，不向未来任务授予权限。保持产品模型生成、原验收标准、exact approval、
外部披露和游戏操作边界；没有用Codex代写正确Mod补丁，也没有外发GTFO材料。
本窗口新增P0模型发送6次、完整响应5份（014为4/4，015为2/1）；没有新增云端模型生成。
0.29的Max成功发生在窗口之前，本轮对它做的是历史导入与查询，不重复计为新的成功运行。

**P0两次实际运行：**

| 运行 | 冻结条件与实际动作 | 结果 |
|---|---|---|
| 014 | HEAD `1415ebe`，原c760/5编辑绑定/29可读绑定、原006+r6精确失败输入、Qwen30B、5次总预算；4次实发/4次响应，9次读取为3新窗口+6复用 | 两份代码的after_text均与原失败版本相同，两次40进程/36检查均33通过3失败；终止PATCH_BEHAVIOR_CORRECTION_FAILED，无新Proposal/Review/Dry-run |
| 015 | 与014首请求相比仅model字段变为本地qwen3.6:27b；原messages/tools/Plan/预算/600秒不变 | 2次实发、1次完整响应；首轮自主选择4个supporting读取，第二请求600秒超时，无代码、无矩阵；不是又一次行为修复失败 |

两轮前均完成公开CLI零模型preview，并在首个真实send前逐字比较首请求。没有运行中改执行器或接续
旧响应；源码/冻结文件及既有Store资料未改变。014代码与较早009完全相同，因此沿用合法006+r6选择器，
没有把复验路径改成009来伪装新验证。

014实际F1包含五个原观测字段`validGun/targetSpread/spreadScalar/scaleWrites/startedCoroutines`，
与矩阵相应场景逐值相等，未丢核心状态：Match为false/0/0.2/0/2，第二次冷却的协程数3；
Inner为false/0/1/0/2。协程详细生命周期等额外trace未全部投影；没有直接统计初始化方法入口，
所以“初始化被跳过”仍是解释。不能继续把014失败归因为只给模型尺寸标签。

015首轮输入12,238 token、输出197 token，生成耗时92.132秒，约2.14 token/秒。
运行中Ollama ps报告加载约20.35GB、其中约5.12GB在显存；设备为8GB RTX4060 Laptop。
这说明该部署没有整模GPU驻留和明显延迟约束，不是模型代码能力结论。没有延长超时、追加预算或自动换第三款。

- [014结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_014/actual/summary.json)
- [015结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_015/actual/summary.json)
- [015与014首请求对照](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/public_cli_repair_015/comparison-to-014.json)

**并行提交及验收：**

| 提交 | 做了什么 | 实际证据与限制 |
|---|---|---|
| `98bb008` | 原Langfuse元数据导出器消费提交格式轨迹和脱敏请求引用；格式成功不加行为分数 | 29项聚焦通过/5.45秒；Max真实导入1次observations POST+1次score POST，初查pending，之后只GET查回15条记录和1条分数，身份匹配 |
| `fcf3fc6` | DSH `/mod-submit`经固定stdin bridge调用原plan-request，持久化原request_planning_report/mod_planning_brief | Python11项/5.32秒，Node12项/8.60秒；真实官方页面提交并显示ready_for_feature_spec，2个Artifact核验，0模型；不等于FeatureSpec或实施Plan已生成 |
| `1415ebe` | 一个固定任务的只读trial汇总，按profile/worker/policy分组，核对原矩阵及代码/Artifact链 | 初checkpoint71通过1依赖方向失败；移装配至script后新12项+原守卫13通过/4.33秒，防覆盖1项/0.90秒；一个任务四次trial、三失败一通过，不发布模型资格 |
| `5536cb4` | Patch按需API观察保留source_authority/evidence_source_ref/risk_notes，binding引用与来源引用分开 | 独立worktree红测复现，115项checkpoint通过/3.98秒；合入8项通过/0.84秒；两种来源经真实HTTP序列化的离线传输替身核验。014未读API，不能当作它的失败根因 |
| `088c78d` | 显式新领域factory分开原矩阵锚点与当前精确Plan，核对源码/模型字节，按响应分目录并精确重映射owner | 81项兼容检查通过/29.47秒；合入7项/8.62秒；独立Store合法新Plan/重命名binding、原失败代码，真实两次编译+40进程/36检查仍33/36，报告绑定新Plan。不是模型生成新Plan或修复成功 |
| `46e80b9` | DSH `/mod-review <run_id>`读取该次精确Proposal/Review/Dry-run、显示diff及当前修改文件状态 | Python7项/7.32秒，Node bridge11项/6.38秒；真实handler+Python子进程对Max成功显示853B原diff，旧Max失败无diff；没有借用latest，没有批准/Apply |
| `72a9183` | 补入mod-review的空会话活动识别 | 原遗漏经红测复现，4项客户端检查通过；不改后端权限或模型行为 |

各测试集合有重叠，以上数字不相加为唯一测试总量。新文件Ruff/diff检查通过；local_entry原10项
存量lint保持，不借本轮清理。A5/A4在独立工作树完成，在015结束后才合主树；未污染冻结运行。
`98bb008`提交于19:31:21，属于两小时窗口前的并行准备；其它表列六个实现提交发生在窗口内。

原36项矩阵仍不覆盖整Mod编译、配置解析/键绑定或游戏Runtime。新factory对未覆盖的新位置明确拒绝；
已知旧Config编辑点沿用原范围并列入uncompiled_changed_files。不能将局部矩阵通过升级为全部功能保证。

DSH审查命令随后在真实官方页面显示了853字节原diff与旧验证记录，未批准或执行。空会话活动列表
最初漏掉mod-review，经1项红测复现后补入，4项客户端检查全过（0.234秒）；原官方Conversation
组件参与该检查。[浏览器与会话快照验收](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/dsh_review_browser_20260907_001/acceptance.json)。

**Langfuse实际接入：**用户提供美区项目并自行配置Secret Key。最初沙箱HKCU读不到实际用户变量，
在真实Windows用户环境确认存在；Public Key和Base URL补至用户环境，密钥未写入仓库。
GET projects核验对应项目后上传；最终15 observations/1 score已查回。记录为历史导入，原时序未知，
不是所有阶段实时Tracing。源码、prompt、原回复和本地路径未导出。

- [Cloud查回](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/a6_submission_import_owned_max_001/cloud-readback-20260907T114241864996.json)
- [用户项目](https://us.cloud.langfuse.com/project/cmtr5q7ae024iad0im785u4xl/traces)
- [额外三次失败历史预览](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/a6_owned_comparison_cloud_001/preparation.json)

额外三次历史共39 observations、0 scores。自动审批最初拒绝该追加操作，理由是缺少对这三份具体数据
导出的明确授权和项目归属证明。进程未启动、0HTTP/0POST；root未绕过，已向用户留下可选具体确认。
已有Max成功导入不受影响。[审核阻断记录](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/a6_owned_comparison_cloud_001/approval-review-blocked.json)。
随后用户明确回复“授权这三次历史元数据”，新授权后仍从原动作入口执行，再次GET projects核验同一
项目。三次各1个POST，共3POST+12GET，39条全部verified_remote_readback、无缺失、0score。
原拒绝记录不改写，未通过换工具绕过；4次自有对照合计54条历史记录、1条原15项行为分数。
[追加三次真实导入及查回](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/a6_owned_comparison_cloud_001/import-result.json)。

**本地入口/比较/领域适配证据：**

- [DSH真实需求提交](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/dsh_submit_acceptance_20260907_001/acceptance.json)：原会话日志为可追加文件，后续动作前已保存匹配hash的独立session-at-submit快照及补充引用。
- [DSH精确diff入口验收](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/dsh_review_actual_001/summary.json)
- [四次trial只读报告](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/owned_config_trial_comparison_20260907_001/report-final.json)
- [新Plan原矩阵真实兼容验收](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/vp1/execution-receipt.json)：0模型派生兼容输入，原after_text字节不变，不冒充新模型输出；只证明身份/binding ID变化，不证明扩大修改范围。

**事故与恢复：**A7首次脚本误覆盖旧derived comparison摘要，未覆盖任何模型响应/journal/矩阵。
已即时说明。随后定位当前任务日志14854行原生成命令及14857行原收据，从原未变事实文件恢复8,981字节，
SHA严格回到`8de69acdafa7eb3ce8cfcd06d5919d0daea7e1f2872730307bab60efd23886bd`；误覆盖内容排他备份，
14个保护资料前后hash一致。新查询输出现在排他创建，旧路径被拒绝。
[事故与精确恢复](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/owned_config_history_restore_20260907_001/incident.json)。

仍未完成：First Shot有效修订/原任务审批Apply/changed Build/GTFO Runtime；真实自主Planning与
有依据的自动上游选择；RAG证据改变下游决策的实证；跨任务资格；DSH执行、批准、取消与恢复；
完整实时Trace、hosted CI及Release交付。保留六份用户原WIP，不把本轮平台提交视为这些项目全部完成。

## 1. 结论与范围

> 历史适用：初次核对时点；本节的“当前/末次/下一步”不覆盖第0节最新快照。

**整个聊天缓冲区没有完成，GPT Chat 建议也没有全部落地。**
完成的是一条限定于当前 AccurateCrosshair 请求的审批前产品链：

```text
已有 FeatureSpec / Fresh EvidencePack / 人辅选目标的 ImplementationPlan
-> 本地 Qwen3-Coder 选择一个 binding
-> 读取受限源码 observation
-> 生成初稿
-> 文件头 validator 拒绝
-> 一次 correction
-> PatchProposal / ProposalReview / no-write Dry-run
```

这证明当前输入下工具交互与特定失败修正能到达 Dry-run，不证明多任务
Patch profile、全链自治、任意 validator 自动修复或 changed Build/Runtime。
记录中的 `semantic_assurance.verdict=unproven`、
`human_semantic_review_result=pending` 必须保留。

9 月 4 日对“目标完成”的报告只适用于上述阶段，不能覆盖用户要求的
“当前所有任务以及后续新增任务”。聊天中没有落盘的缓冲计划不能继续
当作可靠交接入口。首次核对只覆盖当时可见要求、提交、源码和运行记录；
第 9 节补记了新页逐轮回读的完整范围及全页工作映射。两次核对均不声称
恢复未提供的内部推理、未落盘消息或源日志中已截断的工具输出。

## 2. 主证据定位

> 历史适用：初次核对时点；本节的“当前/末次/下一步”不覆盖第0节最新快照。

Artifact 根目录相对仓库为
`artifacts/g1_assisted_findings_context_repaired_27b_fc/store`。
该目录是本地运行资产；开新 worktree 时须确认它可访问，Git 提交本身不代表复制了这些文件。

| 对象 | 精确 SHA256 / 身份 |
| --- | --- |
| Feature | `feature_66e54ec4a116` |
| FeatureSpec | `fc7be8abc61c9b8e198062dcdba107fd07c57342901ae43551c8e0860806d004` |
| EvidencePack | `bd2e2bde11e79605c367a2b67e9c68e7d27adbfd998cd79307b2c5c0b8048058` |
| ImplementationPlan | `b11e4dde1215ca7861e3f2160b05dca150522e889a0ecdf4982e87085e0208ae` |
| PatchProposal | `0a2e5c5406ec7ff52bdb0056145bf02d06a3b4f01fbba8e7f169613dd97211e4` |
| ProposalReview | `9468839fc443284ef9215f054435d3f143f0eccd5242efb078c1a0a88eb7a55c` |
| Dry-run | `18b5d478fca78ae0d06090ff8e68097c19feff3bb81a750c08b44112ed228725` |
| 审批 diff hash | `sha256:684615135310c41692a801772bcc8a34b4b1a6af1edc45560e0df1817934f282` |
| 模型 digest | `06c1097efce0431c2045fe7b2e5108366e43bee1b4603a7aded8f21689e90bca` |

末次运行：[receipt](../../artifacts/g1_assisted_findings_context_repaired_27b_fc/store/cr/5024afcd6671db0cee7f7f0f5c4e92a3.json)。
[完整 diff / Dry-run](../../artifacts/g1_assisted_findings_context_repaired_27b_fc/store/features/feature_66e54ec4a116/r/dry_run_result/18b5d478fca78ae0d06090ff8e68097c.json)。

- 运行：`patch_continuation_a1a22fbdcc6e4f89920602208c6c9c9d`。
- 状态：`stopped_before_exact_diff_approval`；3 次模型调用、1 次源码工具、1 次 correction。
- 端到端墙钟：277.13 秒；4 个 binding，2 个文件，新增 7 行、删除 0 行。
  本轮回查原日志第 26303 行的 CLI stdout，`duration_seconds=277.12928229998215`；
  receipt 的 `factory_receipt.duration_seconds=276.27811100002145` 是不同计时范围。
- 初稿与修订稿分别保存在该 receipt 对应的 `.response.txt` 与
  `.response.correction-001.txt`；没有覆盖初稿。
- 本次 Apply、Build、Runtime 均未执行，产品源码未写入。

这里的 inspection 由程序要求必须发生，**binding 由模型选择**。
它不证明模型自主判断“是否需要查工具”，也不证明自主 API discovery。

## 3. 这轮实际做了什么

> 历史适用：初次核对时点；本节的“当前/末次/下一步”不覆盖第0节最新快照。

| 提交（本地时间） | 内容及界限 |
| --- | --- |
| `c403037`，09-04 19:38 | Dry-run 拒绝新添行尾空白；prompt 加明确说明 |
| `0a04055`，20:06 | 保留失败诊断和已生成 Artifact；schema identity；移除 rationale 词面路由判断；修正空白检查边界 |
| `ac92b17`，20:42 | Patch-specific source tool loop、prepare/materialize 分离、生产 CLI 接线 |
| `e431435`，20:59 | 同 adapter 已观测 token/byte 比率估算、provider 失败诊断、调用方预算 |
| `f7d51a8`，21:05 | 后续工具 enum 去掉已看 binding；仍因真实重复动作失败 |
| `138a7e9`，21:09 | 默认一次 observation 后强制 final；不代表多轮调查收敛 |
| `af3215d`，21:19 | materializer 保存源 BOM |
| `d6eeed7`，21:25 | 文件头 replacement 删除全部 using 时阻断；这是启发式保护，不是 C# 编译验证 |
| `3694a77`，21:37 | 针对上述 header 失败的一次模型 correction；末次真实 Dry-run 通过 |

聊天 goal 记录约 2 小时 15 分钟，包含后续 continuation。
Git 时间戳与末次 receipt 支持先完成 loop、后补 correction 的顺序；
不能由提交时间反推出每分钟投入，也不把 goal 的累计 token 数当作已核对的账单费用。
净改动为 16 个源码/测试文件、`+3190/-58`，没有文档更新包含在上述九个提交内。
新 loop 模块 1076 行，体量与重复制式代码仍是明确维护债。

末次成功之前，真实尝试依次暴露：空白、缺调用链上下文、第三 turn
byte gate 拒绝、重复工具请求、BOM/using 丢失。不能只保留末次成功而删除失败记录。
同一源码下 one-shot 到 early-return 的变化与新增 observation 一致，
但 prompt/模式也发生变化，不能宣称已严格证明单一因素的因果收益。

验证记录（来自昨天的执行输出，本次文档核对未重跑）：

- 478 项两 worker checkpoint 在 BOM/header/correction 的最后改动之前通过，
  不能称为最终 HEAD 的全仓库回归。
- 最终 correction 改动后的命令：
  `python -B -m pytest tests/unit/test_patch_agent_loop.py tests/unit/test_patch_code_generator.py tests/unit/test_fresh_planning_continuation.py tests/unit/test_local_entry.py tests/unit/test_workflow_graph.py -q --tb=short`，439 passed。
- header 改动后生成器测试文件 90 passed；已有 jieba warning。
- 4 个 ProposalReview 旧夹具因缺 exact source identity 失败，昨天恢复旧 rationale
  代码后仍能复现；未修夹具，不能声称完整单元套件全绿。

## 4. GPT Chat 原则及三个 Loop 补充项

> 历史适用：初次核对时点；本节的“当前/末次/下一步”不覆盖第0节最新快照。

状态用完整文字，不使用 A/T/P 混合缩写。

| 要求 | 核对状态与实际范围 |
| --- | --- |
| 基础 Agent/tool/observation loop | 已实现，当前一个 binding 的真实工具往返通过；多轮自主调查未通过 |
| 权限内主动完成任务 | 已实现 binding id 输入、受限读取、snapshot 检查；工具 observation 不增加 edit bindings |
| JSON 与 loop 共存 | 已真实通过最终四字段 `changes`；原始合同保留 |
| 工具权限分层 | 首版只有 `inspect_plan_binding_source`；没有任意路径/shell/Apply 工具 |
| 模型负责语义，系统负责已有身份 | binding-only 已有；本轮另收回 BOM。没有跨所有 stage 完成 owner 审计 |
| 每字段检查是否真需模型判断 | Patch 层有实际审计；全项目准则/逐 stage 检查未全部完成 |
| Slot filling | 明确延期；没有固定 slots 新合同 |
| Schema identity | 已有系统侧 `patch_generation` / `2` / schema hash，进入 receipt/generation；非所有 stage 统一完成 |
| 简单 provider schema、避免复杂组合 | 当前 Patch 简单 schema 和防复杂关键词测试存在；通用 provider 兼容框架延期 |
| rationale 非 authority | 当前 ProposalReviewer 的词面匹配 gate 已移除；不得把解释当语义证明 |
| rollback_hint 非 authority | 当前路径是说明；可选旧 Critic 仍按非空提示计 reversibility，未全面纠正其语义评分 |
| Ref-first / copy-last | supporting excerpt 截到 1024 bytes 并记录 hash/truncation；source observation 有限额。没有任意 evidence ref 的完整按需读取工具 |
| One stage one schema | 各 stage 已分离；没有全 stage 迁移/审计，不新增万能输出 |
| 三层责任 | Provider 形状 -> Plan/Binding 身份准入 -> code/Dry-run/后续验证；责任已存在。本记录明确边界，不新增三种 Artifact |
| JSON 通过不等于代码/语义通过 | 真实拒绝和 `unproven` 证明该边界；还没有通用语义验收器 |
| 当前 Artifact 动态收窄 | binding enum 和数量约束存在；工具 enum 无法代替本地验证 |
| Context byte proxy | 部分处理：AgentTurn 后续请求可用经验比例估算；不是 tokenizer，也不是数学保证上界，首轮/其他路径仍有旧 proxy |
| Loop budget / termination | 固定 tool/turn 上限与显式 caller budget存在；production 默认一次观察。逐 turn crash receipt、全轮次身份和端到端时限仍需复核 |
| Observation identity / freshness / error | hash、binding ref、source snapshot、截断、失败原因存在；末端 Graph 重验。不代表任意中间 turn 的跨进程恢复 |
| Loop context / history | 总 observation bytes 有界；初始 supporting 截断。多轮模式仍会重放此前 observation 全文，未实现完整 supersede/history 压缩 |
| Evaluator correction | **只对 `csharp_file_header_usings_removed` 修一次**；不是通用 validator/Review/Dry-run/编译失败修正 |

实现入口：
[Patch loop](../../src/mod_agent/proposal/patch_agent_loop.py)、
[Local entry](../../src/mod_agent/local_entry.py)、
[schema/materializer](../../src/mod_agent/proposal/code_generator.py)、
[Review](../../src/mod_agent/proposal/reviewer.py)、
[context admission](../../src/libs/llm/agent_turn.py)。

## 5. 缓冲区尚未交付及已有底座

> 历史适用：初次核对时点；本节的“当前/末次/下一步”不覆盖第0节最新快照。

| 工作项 | 本次核对结果 |
| --- | --- |
| 当前 Mod 的 Apply / changed Build / Runtime | 未执行；审批前语义复核仍需完成 |
| General validator correction / compiler-test feedback | 仅特定 header correction；其余未接通新的自动反馈内环 |
| `AUTONOMOUS-EVIDENCE-DISCOVERY-001` | 当前 Fresh 是显式人辅 API symbols；自主成功未证明 |
| `AUTONOMOUS-TARGET-SELECTION-001` | 当前四目标由 operator 选择；Plan compiler 已运行，自主语义选择未完成 |
| `MODEL-ROUTING-001` | 手工模型/profile 设置与个例结果存在；role -> qualified profile 正式 resolver 未交付 |
| `PATCH-EVAL-SUITE-001` | 未冻结新的 3-5 项真实 Patch 任务集；旧 RAG 定义不等于 Patch suite |
| `RUNTIME-REPAIR-LOOP-001` | 历史窄 Runtime/Repair 路径存在；当前 Mod 未走，通用自动闭环未完成 |
| `PROVIDER-CONTEXT-ADMISSION-001` | 经验比例补丁已做；模型 tokenizer、模板精确计数及泛化资格未完成 |
| `INFRASTRUCTURE-FALLBACK-001` | 延期；不得把语义失败自动切模型视为通过 |
| 工程认知八视图 | 工具存在；当前仍错报 API 未入 Fresh，verification 只是 inventory；待修 |
| PreCompact / SessionStart | 脚本与 hooks.json 已提交；最新 summary 没有真实生命周期 snapshot，信任/恢复验收未证明 |
| `bounded-task-handoff` | Skill/脚本在 09-02 已建立；当前 task packet 仍 stale，未接住昨日新任务 |
| `release-evidence-packager` | Skill/脚本在 09-02 已建立；最终 manifest、演示与简历材料未交付 |
| 依赖锁与最小 CI | `uv.lock`、`.github/workflows/ci.yml` 在 09-02 已提交；不能再写成“没做”。本次未核对 hosted CI run/clean-room 成功 |
| Local Environment | `scripts/setup_codex_local_environment.py` 已有；Desktop 绑定和实际重建未证明 |
| Langfuse / Trace / Eval | 本地 receipt/lineage存在；Langfuse exporter 仍是 injected transport，无完整真实生产 sink/flush/session/score 验收 |
| pre-commit / dev-check / profiles / Hook enforcement | 未在此次提交中落地；十日草案多数明确延期，不能自动升级到 P0 |
| branch coverage / security / deployment / release | 未完成发布级验收；不由当前 Patch 成功代替 |
| 九目标、五项、三个 txt 成熟度 | 未在这两小时内完整实现/验收。第 9 节保留当时 Core 采纳事实；本页随后明确的完整七组十日目标以第 10 节为准。六份 WIP 全文并未整体获批 |

## 6. 必须纠正的既往结论与当前审查事项

> 历史适用：初次核对时点；本节的“当前/末次/下一步”不覆盖第0节最新快照。

1. “全部缓存任务完成”不成立。此前 goal 完成标记没有覆盖所有已承诺任务。
2. `model -> tool -> observation -> model` 已有真实记录，但工具被强制、默认只查一次；
   不能提升为任意多轮自主 coding worker。
3. “同模型比例 x2 是保守上界”不成立。token/byte 比率可能随内容和模板变化；
   当前是经验估计。需要资格/边界验证，不将该估算包装成精确计数。
4. “early-return 已保证 First Shot/其他行为独立”不成立：新页已在原重启验收范围内
   定位冷启动静态反例。FeatureSpec 第 10 行明确要求 Follow Recoil、First Shot
   Display Mode、Pop Enabled 与 Accurate Spread Enabled 保持行为独立，第 36 行
   要求两值各自重启后验收。最终 diff 在 `_validGun = false` **之前**新增 return：
   - **Follow Recoil**：`SpreadPatches.cs:18` 的 `isShotgun` 初值为 false，唯一后续
     赋值在第 127 行，被 return 跳过。false 冷启动、Follow Recoil=true、持霰弹枪时，
     `RecoilPatches.cs:15-16` 仍执行 `m_moveCircleCrosshair = !SpreadPatches.isShotgun`，
     得到 true；基线识别霰弹枪后得到 false。这是此前交接漏记的共享状态回归。
   - **First Shot Match**：有效枪初始化 `_validGun=true`（第 132 行）被跳过。
     `FirstShotPatches.cs:19-20` 的 Match 效果仍调用 `UpdateSpreadScalar(0.2f)`，
     但 `SpreadPatches.cs:55` 因 `_validGun=false` 返回，实际尺寸更新不发生。
   - **First Shot Inner**：第 140–141 行 `SetStoredCrosshair(weapon)` 被跳过，
     初次持枪显示与真实 cooldown 初始化消失。第 138 行 `_targetSpread` 赋值也被跳过；
     后续 `FirstShotGuiPatches.cs:35-42` / 第 59 行仍通过 `GetCrosshairSize(0.2f)`
     取尺寸，失去武器 spread 输入。
   这些是绑定当前源码和 diff 的控制流差异，不是已执行的游戏测试。
   当前 diff 应先修订，不能继续推荐对现有 hash 批准。原 Artifact 的
   `unproven` / `pending` 保持原样，不把本次源码审查伪装成机器语义 verdict。
5. 热重载 true -> false 若保留此前 `_validGun=true`，`OnConfigReload()` ->
   `UpdateCrosshairSize()` 仍可能用旧状态覆盖。原验收明确要求重启；
   热切换是否纳入验收应明确，不能暗中新增需求，也不能宣称热重载已语义通过。
6. 删除所有 using 不必然都是非法 C#（可能使用完全限定名）。当前 header gate 是
   保护本任务无关内容的启发式，不是全语言的普遍正确性规则。
7. 历史工程认知、状态文档与实际 Artifact 不一致，必须依据当前源码/记录复核。
   这不是聊天可见性本身能修复的问题。

上述源码审查依据：
[SpreadPatches](../../workspaces/actual_only/accurate_crosshair_spread_toggle_preflight_20260824/source/AccurateCrosshair/CrosshairPatches/SpreadPatches.cs)、
[FirstShotPatches](../../workspaces/actual_only/accurate_crosshair_spread_toggle_preflight_20260824/source/AccurateCrosshair/CrosshairPatches/FirstShotPatches.cs)。
另核对了同目录的 `RecoilPatches.cs`、`FirstShotGuiPatches.cs` 与 `PopPatches.cs`。
本轮没有执行游戏或改写已冻结的 Artifact；未发现 Pop 直接开关路径存在上述同类依赖，
这也不等于 Pop Runtime 已验证。

修订不能只把 return 挪到方法尾部：`SetStoredCrosshair` 会经
`UpdateSpreadScalar` 回调 `UpdateCrosshairSize`，仍可能写主准星尺寸。
而 `AdjustCrosshairSize` 第 106–112 行仅在返回 false **且**已有 `_smoothRoutine`
时停止协程；返回 false 且协程为空仍走 else 启动 `ScaleSpreadCircle`。
所以旧页“return false 就阻止后续 coroutine”的字面结论也不成立。
应保留共享武器/First Shot 状态初始化，并明确主尺寸覆盖与 First Shot 专属效果的边界。
现有 `edit_binding_001` 只覆盖 `OverrideCrosshairSize` 第 115–145 行；如需修改其他
owner，须沿现有 Plan/Binding 合同生成精确的新实例或修订，不能借原 binding 越界。

## 7. 本页继续与上下文工具

> 历史适用：初次核对时点；本节的“当前/末次/下一步”不覆盖第0节最新快照。

本页仍可继续；无法仅凭模型自评保证长上下文完全不影响表现。
官方 `/status` 查看 chat/context usage，`/compact` 压缩上下文；
它们不测推理质量。见[桌面端命令](https://learn.chatgpt.com/docs/reference/slash-commands)。
没有在所核对的官方文档中找到自动测量“上下文降低多少智能”的现成 Skill。
现有 Hook 是恢复定位工具，engineering cognition 是可重建事实索引，均不是性能评分器。
若反复出现遗漏最新决定、复活已否决任务、重复调查已明确事实，先对照本记录和队列；
必要时压缩或以短交接开新页。新页/压缩本身不保证更准确。

本次沿用工作树，保护六份原有 WIP；未重写它们，未创建新页，未删模型，未增加自动任务。

## 8. 整页交接与压缩后的历史回查

> 历史适用：初次核对时点；本节的“当前/末次/下一步”不覆盖第0节最新快照。

### 8.1 对补充审查记录的核对

用户补充记录位于
`C:\Users\10160\.codex\attachments\ba7a43b7-62b3-4ea4-850a-4cc0bae70923\pasted-text.txt`。
其中“剩余风险摘要不是完整现状摘要”的提醒成立。接手时必须一起读取本文
第 1–5 节：真实工具往返、header correction、ProposalReview、Dry-run、
schema identity、BOM ownership 和失败记录保存，不能因泛化未完成而降成未实现。
也不能反过来把当前单次成功扩成完整缓冲区、全部业务语义或 Runtime 已通过。

补充记录中的两类更强结论不直接采纳：

- observation 后出现 early-return 是真实输出变化，但不能仅据此证明
  observation 的独立因果收益，或 First Shot 独立性等全部业务义务已满足。
  继续保留第 6 节的明确待核查事项。
- telemetry 校准已进入后续 turn 的 admission，不是“还完全使用静态 bytes”。
  但观测比例加系数仍是经验估算，不称为保证的 token 上界。

### 8.2 已核实的历史入口及限制

- 本页任务 ID：`01a060cf-4b34-7a72-bc7c-438d68fc1331`。
- 本页所在 checkout：
  `C:\Users\10160\.codex\visualizations\2026\08\11\019ff15f-9eac-7b13-aad5-faffde4b36b7\rag_capability_mainline`。
- 本页本地日志：
  `C:\Users\10160\.codex\sessions\2026\09\02\rollout-2026-09-02T14-29-53-01a060cf-4b34-7a72-bc7c-438d68fc1331.jsonl`。
  首项 `session_meta` 的 `session_id`、`id`、`cwd` 与本页匹配。
  本次只读核实文件存在及早先缓冲要求、当前压缩提问可检索；没有修改、重排或修复日志，
  **当时尚未逐项认证整份历史无缺失**。新页回读结果见第 9 节；该结果也不证明
  从未保存过的消息存在，或此前 UI 恢复已经完整。
- `read_thread` 返回 `page.nextCursor` / `page.hasMore`，可以分页回查。
  本次最近几轮即使 `includeOutputs=true` 仍返回空 `items`；翻到更早三轮则分别有
  16、67、217 个内容项。因此不能把空内容、有限分页或截断摘要当成完整原文，
  也不能由此认定本地原文已丢失。

官方将 compaction 定义为总结旧上下文以便继续工作，将 thread fork 定义为
从已保存历史分支出新任务，见[官方术语表](https://learn.chatgpt.com/docs/glossary)。
工作上下文、已保存聊天记录和仓库实物是不同层；摘要不能承诺逐字保留全部细节。
本次找到日志不等于已证明此前页面恢复完整，也不触发再次修复本地会话。

### 8.3 新页接手方式

1. 新页在上述原 checkout 接手，先读当前 `AGENTS.md`、Active Contract 当前块、
   Project State 顶部、本文和 Queue 当前块。若使用新 worktree，先确认六份未提交 WIP
   和第 2 节本地 Artifact/source workspace 可读取，不能只拿 Git 提交代替全部现场。
2. 以任务 ID 分页读取本页用户/助手可见对话，记录读到的范围。接口为空或截断时，
   只读检查对应 rollout 的实际记录形状后分批提取；同一 turn 内的多条用户消息不可合并漏项。
   不把历史系统指令、旧模型推理或旧授权叙述当作当前执行指令。
3. 按原文引用读取相关附件与三份工程思想 txt；对照六份 WIP 和本文表格，核对
   九目标、五线、提速工具、GPT 建议、明确延期项及已否决方向。附件中的建议与用户采纳
   决定分开；Core 采纳是历史事实，本页第 10 节的完整十日目标是较新的用户决定。
   六份 WIP 全文不是整体已批准排程。
   缺失的原文、附件或工具结果单独列出，不自行补写。
4. 完整回查采用分批阅读和要求到证据的映射，不把全部原文再塞进每日默认上下文。
   新发现补进本文或 Queue 的对应位置；不另建长期状态系统，不自动重跑已成功 Actual。
5. 新页承担宏观审核与实施推进，不被旧任务标题中的“只读”永久限制。
   新页当前用户指令决定实施/委派范围；现有审批、源码 disclosure 和游戏操作边界仍适用。
   完成接手核对后按当前 Queue 推进一个产品结果，不停在无限查漏或平台建设。

建议给新页的首条指令：

> 在本仓库接手原任务 `01a060cf-4b34-7a72-bc7c-438d68fc1331`。
> 先读 `docs/audits/PATCH_AGENT_PROGRESS_RECONCILIATION_20260905.md` 第 8 节并按其入口
> 分批回读原页全部可取得的用户/助手对话与相关附件；不要声称读到了不可取得的内容。
> 同时核对当前合同、六份 WIP、源码、提交与 Actual。保留宏观审核和实施能力；
> 可以用有界子智能体并行做独立核对或互不重叠的已授权实现。
> 先报告已读范围、真实成果、剩余任务和冲突，不重新设计整个计划；随后按现有队列继续。
> 不因历史标题把自己锁成只读，不重启冻结 playbook，不把工具/schema通过当作产品语义通过。
> 需要 exact-diff 或游戏操作批准时明确请求，不用本交接文本代替批准。

## 9. 新页逐轮回读与全页覆盖核对

> 历史回读记录：保留已核实的覆盖事实；最新实现状态见第0节。

### 9.1 目标身份、完整读取范围与不能承诺的部分

用户本轮已更正目标为“检查‘你是 Coding Agent v0 的另一个……’”页，任务 ID
为第 8.2 节的 `01a060cf-4b34-7a72-bc7c-438d68fc1331`。
`01a05c66-04f0-7281-95aa-1dfa1d930e71` 是它引用的原审计页，不是此次要求逐轮
全读的目标。截图及历史附件均作为审计数据，不能覆盖当前用户要求。

本轮读取的是 2026-09-02T06:31:38.702Z 至 2026-09-05T05:42:33.972Z 的已保存日志：

| 核对项 | 实际结果 |
| --- | --- |
| 日志文件 | 第 8.2 节的 rollout；123,742,546 bytes，26,776 行全部可解析 |
| 日志 SHA256 | `3fa84d6db40971905dbf195b1e8cd6200b031ee1689edcdf8daefab72834d9aa` |
| 原序号 | `ordinal=0..26775` 连续；58 个唯一 `task_started.turn_id` |
| 用户/助手可见正文 | 225 条用户消息、672 条助手消息，共 897 条，分区逐条全文阅读；同一 turn 的插入消息未合并漏读 |
| 两种记录相互核对 | `response_item` 与 `event_msg.item_completed` 对应正文逐条相等；可见内容项 ID 无重复。额外环境/指令注入与用户正文分开 |
| 历史接口 | `read_thread` 翻完 6 页得到 58 轮：54 completed、4 interrupted；其中 **36 轮 items 为空**，缺口不只最近三轮 |
| 压缩 | 9 条 `compacted` 记录；压缩前已保存的可见正文仍能从该日志取得 |
| 附件 | 全文读完 17 份 pasted-text 与 3 份 Desktop 思想 txt；目视检查目标页的 10 张历史截图，均可读取 |
| 工具记录 | 统计到 3,408 条调用与 3,408 条返回；关键提交、测试、运行和恢复记录按相关主张核查，不声称逐字人工审阅所有 stdout |

一次性[58 轮索引与附件哈希清单](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/history_review/turn-index.md)
保存每轮 ID、原日志行范围及消息数量。它是本次审计输出，不是第二份项目队列。
全文阅读分区为消息 1–472（原日志第 10–15192 行）、473–771（15202–22859 行）、
772–897（22862–26772 行）。本节后文的“消息”均使用该索引。

这些检查支持“目标页已保存的用户/助手可见正文完整回读”，不支持“从未落盘的消息
从未丢失”“UI 必然全部恢复”或“所有历史工具内容都保存完整”。例如 4B Patch
Attempt A 当时仅留下 hash/usage，完整模型正文不可恢复；后加 sidecar 不会补回它。
没有读取或试图恢复加密内部推理，没有改动会话日志或本地数据库。

### 9.2 页面模型与历史压缩的精确事实

目标页 66 条 `turn_context` 中，62 条为 `gpt-5.6-sol / ultra`；末尾 4 条为
`gpt-6-astra / xhigh`，后者属于 3 个不同 turn，其中一次为压缩后的重复上下文记录。
首次 Astra 记录位于原日志第 26421 行，时间为北京时间 2026-09-05 13:14:36。
第 26423 行用户也明确说“我换了astra”。因此“该页一直用 Sol”对早段成立，
对整页不成立；`xhigh` 不能改写成 `ultra`。

这与产品实验中的 Sol/high assisted Patch 是不同层：前者是 Codex 页面配置，
后者是历史受控对照的角色/输出来源。均不能由模型名字推断证据更完整或业务更正确。

[OpenAI 模型文档](https://learn.chatgpt.com/docs/models)支持选择模型/推理档位；
其中要求开启后新建任务的说明针对实验性 context management。
[术语表](https://learn.chatgpt.com/docs/glossary)将 compaction 描述为概括旧上下文。
本轮未取得用户所见模型切换提示的原句及适用版本，不能将其解释为所有中途切模型
都会损坏历史或必然降低表现。当前可操作的保证来自逐轮回查与实物核对，不来自模型自评。

### 9.3 用户决定及整页任务范围

- **宏观审核与开发提速是持续职责**：消息 18/20 要求本页接住原页宏观审核、Skills
  与开发方式改善；不能只留下当前 Patch 任务。工程认知属于 Codex 工具，产品
  Dependency/API Evidence 服务产品 Agent，两者继续分开。
- **三份 txt 全部在范围内**：消息 137/139/141/144 纠正读取范围；三个思想文本、
  九目标、五线、合同/WIP 与聊天排程都要覆盖。`.md` 用于补充工程现实，不应让旧文档
  压过用户新决定。附件中的微内核、注册表、复杂 Hook 或多 Agent 建议不是自动授权。
- **Core 已采纳**：消息 73 当时说排程仅供参考；后续消息 165 明确提出
  Fallback/Core/Full-maturity Stretch，并请求裁决 Repair/更广 Eval 移入 Stretch。
  消息 166（第 6524 行）用户回答“好，按着计划继续推进”，167 随即进入 G0→G1。
  在所回读目标页结束前，原文未撤销这个 Core 决定。一概写“十日排程从未审核”会
  丢掉已发生的采纳；本页后续的新澄清另记在第 10 节，不抹去此历史事实。
  这不等于六份 WIP 全文定版，也不替代后续 exact-diff、披露或游戏操作授权。
  Stretch 指增加完整 Repair→Revalidation 演示和更广 Eval；当前主任务遇到失败而
  必须完成的修复仍是主任务的一部分，不能以 Stretch 为由跳过。
- **辅助工具不能阻塞产品**：消息 175–177 明确正常推进，Hook/认知出现实质缺口
  再修；消息 395 明确八视图长问题“不是验收标准”。不把每个提问变成新 hard gate。
- **工程条件与真实纵向两者都要**：消息 690/694/696 要合理积极推进，并把真实
  纵向结果加到已有工程完成条件，不能以仅测试或仅一次模型成功替换其他义务。
- **全缓冲区未完成**：消息 813–827 形成当前任务、Agent 基础能力与后续任务；
  两小时广泛要求大于最后 goal 的审批前停止点。后者结束不代表其他承诺消失。
- **旧 playbook 已明确冻结**：消息 684 授权冻结；`fd76356` 完成六目录冻结。
  不读取它们来决定下一任务。讨论视频、磁盘、UI、恢复的插入问题各自有处理边界，
  不能因其混在同轮而漏掉，也不能自动替换产品目标。

### 9.4 已落地成果与全工作范围映射

本表补充第 3 节之前的成果和被漏掉的旁支。提交对象与所列关键实物本轮已只读核查；
测试数字、模型运行、Build/Runtime 都保留其**历史执行**属性，没有在本轮重跑。
详细历史执行出处直接指向原日志，避免把全部命令复制到多个控制文档。

| 消息范围 / 工作 | 已有成果与当前界限 |
| --- | --- |
| 1–36：恢复、换页、三工具提速 | 旧页记录可查，用户决定转到本页；集成 `e7523db`，19 focused、387 双 worker checkpoint、只读 review `No findings.` 为历史真实使用，xdist 独立提交 `1c9fcb5`。不由此宣称整体提速已被因果证明 |
| 37–107：首次 Fresh、Findings 首失败、六项提速工具 | 首次两次模型完整响应使 retrieval 4→8，但重复 `relation_index` 拒绝；后续 `1922f14` / `23df983` 修 keyed findings 与 Fresh CLI。`8d74610` / `3da9a92` / `9e4e591` / `d263ed9` 提交 handoff、release、Hook、lock/CI/setup 底座。支持 checkpoint 曾 889 passed；全 unit 曾有历史失败，不能称当前全仓全绿 |
| 108–177：证据语义、三 txt、九目标五线与十日改版 | 已有 Projection V2/Thin Lineage 被确认，未重造；计划拆成短执行与长决策文档，Core 后获采纳。主张、身份、新鲜度、权限不可互代；发布工具的 claim 语义限制仍在，见下节 |
| 178–266：Fresh sufficient、stream/heartbeat、Hook | 历史 Fresh 约 430.6s、2 accepted、9 queries/9 items sufficient。`4ae4f14` 实现可选流式传输并在 Fresh 启用，历史 215 checkpoint 与 6-frame 无源码 smoke；后续完整 27B Fresh 实际有独立 heartbeat。`708f5d3` 修 Hook freshness；桌面信任/完整生命周期仍未证明 |
| 267–317：exact Fresh→Planning、span owner | `2ff0b41` 交付 continuation，真实 blocked Plan 保留 `EDIT_TARGET_NORMALIZATION_UNSAFE`；`8e33076` 修 evidence window 被当 edit span，新的 Fresh sufficient 后形成 non-blocking Plan。不是 continuation 尚未实现 |
| 318–411：Coverage/Planning 分工、入口/API盘点、认知八视图 | `b478782` 的 support/edit subset 是历史桥；真实 6 support→3 edit 漏项触发后续 ownership 迁移。`cffb346` 交付薄认知 CLI；八视图是按需投影，深层语义与实际运行仍有限。MCP/CLI/HTTP/UI 是不同入口，不等于所有模块可任意跳入 |
| 412–491：Planning owner、API seam→caller | `2a5af20` 交付人辅 target selector + 确定性 Plan/Binding，旧 `a5b46b92…` 四点 Plan 真实形成；`8573d09` 修认知缺 owner anchor 仍报 observed。`5eab7a2` API bridge 与 `d8350cf` 生产 caller 均已落地，两个小模型失败不能写成 caller 不存在 |
| 492–547：API双模式、FeatureSpec Runtime、Projection | `b5cb597` 修复重启类要求漏掉 Runtime 义务；`dd28c09` / `128f0b8` 交付正式 `autonomous` / `assisted_explicit` 和程序集搜索；`2bd815d` 修重复义务。人辅只选查询，API事实来自实际程序集。旧 compile-only FeatureSpec 缺陷不能投射到当前 `fc7be8…` |
| 548–622：会话恢复、新页及视频支线 | 用户先取消恢复、后又要求恢复并返回本页继续，记录有成功恢复结果；本轮不再修日志。关联任务 `01a06ad3-79c4-7e03-aeef-f123e5a6b958` 的“当前主线执行与进度总控”已基于用户五张截图完成视频/RAG判断，未取得完整字幕；不列为未做，不称装了视频 Skill |
| 622–649：Findings context 修复与真实 Fresh | `c4216b2` 将冻结输入 73,250 bytes 降至 initial 36,173 / correction 36,474，完整 Evidence 保留，post-change账务内部处理；历史 329 passed。原日志第 19309 行 Fresh CLI 真返回：512.0209442s、2 模型调用、0 correction、14 items、sufficient，生成当前 `bd2e…` |
| 650–700：当前 Plan、API传播、Trace设计、冻结 playbook | 第 19895 行真实 Planning 输出 non-blocking 当前 `b11e…`，4 edit/10 supporting；API传播与语义影响区别被用户明确纠正，详见下节。短进程 Trace/session/flush 责任已讨论，真实 sink 未交付；冻结提交 `fd76356` 已完成 |
| 701–740：exact Patch续接、Windows路径、binding-only | `fa758b5` 接 Plan→Patch→Review→Dry-run，保存 post-call source drift 的生成事实；`66bbe80` 缩短物理 receipt 路径；`d4b7ff9` 收回 `change_id`，保留四个模型字段、旧 frozen 兼容与不可覆盖 response sidecar。第 22105 行历史 331 passed；不是第 3 节九提交才开始具备这些机制 |
| 741–771：4B失败裁决、validator误报、Sol对照 | 4B两次分别暴露 identity 错配和独立代码错误；第二次首拦 `csharp_bound_member_shadowed` 后确认有误报，`686e5f0` 修复。4B本任务 no-go不能归功于该误报。Sol/high `assisted_control` 形成 `6e30b6c… → 8f33f114… → 5f74731…`；第 22770 行真实下游通过，格式审核仍未批准，不能算本地自主成功 |
| 772–826：Qwen3-Coder one-shot、基础能力与缓冲区 | 安装并核验 `qwen3-coder:30b`；首个 one-shot 约 180.09s、11,544/1,626 tokens，4 bindings/2文件，达到 Review/Dry-run。其空白及间接调用链问题随后被发现；不能沿用当时“业务基本正确”。Agent loop、三项补充及独立后续任务已被纳入缓冲区 |
| 827–869：两小时工具往返、失败修复与一次correction | 第 2–4 节九提交及最后运行证据全部保留。真实多轮重复工具失败后默认一次 observation；最终 3次模型/1工具/1correction 到 Dry-run。第 6 节补证 cold-start 独立性回归；末次 goal 完成不等于产品语义或全buffer完成 |
| 870–873：模型磁盘清理建议 | 曾列模型删除选项，但无后续确认/删除结果；卸载驻留模型与删除模型文件不同。本轮不执行清理，不把当时磁盘数字当当前容量 |
| 874–897：换模型、全buffer核对、交接准备 | 页面切到 Astra/xhigh；`474e629` 更新四文档，`597a7a7` 加历史入口。该首次交接尚未逐轮核全页；本节完成其遗漏核对。没有证据支持量化“上下文让模型变笨多少” |

### 9.5 WIP、既往判断和仍未完成事项的关键对齐

**宏观目标有原文入口，不能仅留名称。** 九目标/五线的保留映射见
[现有战略记录](../TEN_DAY_ENGINEERING_MATURITY_DECISION_RECORD_DRAFT.md)第 404–426 行，
三份 txt 的逐项处置见第 428–511、716–852 行；当时采纳 Core 的短 Gate 安排见
[现有短执行页](../TEN_DAY_EXECUTION_PLAN_DRAFT.md)第 38–51 行。
五线是产品闭环、外部调用可靠性、RAG/ER与评测、Trace/Langfuse单向链、固定环境运行部署。
最终 manifest、README结果表、3–5分钟演示、简历和面试问答尚未交付；
`honest_degraded_portfolio_delivery`不能改名为Core达成，public alpha仍是条件结果。
永久拒绝的越权/越级证明与条件延期的PDF/OCR、多模态、模型研究、公共入口扩张和
长期Memory也必须分开；不能因为都没做就视为同类缺口或全部重新启动。

**API 证据的四层不能合并。** 当前 `bd2e…` 中
`data.items` 为 11 个 `target_source` 加 3 个 `decompiled_api`；三条 API 的
`evidence_id` 为 `evidence_4c7460797448a8a8863d2398`、
`evidence_e8ec80617f8bae0373e14635`、`evidence_5596fc147615affc7195eaf6`。
`data.requirement_coverage.findings[*].evidence_ids` 与三者交集为空。
当前 `b11e…` 的 `data.binding_registry.supporting_bindings` 含这 3 条 API，
但 `data.proposed_changes[*].supporting_binding_ids` 四项均为空。
因此 API 查询事实生成、入 EvidencePack、Plan 结构携带已发生；它对 Findings/Planning
决策的语义影响未由该链证明。自主 API 查询成功尚未证明是另一个问题。

**六份 WIP 保留原字节，旧状态不得当作新的否决权。** 短执行草案的
`draft_for_user_review` / `implementation_authorization: not_granted` 未反映后来的 Core
采纳；本次在当前合同/状态/Queue纠正解释，不覆盖用户 WIP。长决策文档中以全九目标
为硬门的段落按 Full-maturity 情景读，不能与后来 Core/Stretch 合并。
RAG 小集的战略三 Case、短页 G4 的 4–6 Case（含 2 held-out）、后来 3–5 项真实 Patch
suite 并非已证明同一输入/指标/消费者的一个任务集；不得互相替代或用一个计数证明
全部 Eval 已完成。

`ARCHITECTURE_OVERVIEW.md` 第 57–64 行仍要求先消费首份 BetterHitFeedback 包；
`SPEC_COVERAGE_MATRIX.md` 第 63–69 行仍保留 `c48b5e8`、12 WIP 和旧 BHF snapshot。
这些不是 9 月当前 AccurateCrosshair 入口。现行选择以 Active 第 1.1 节为准；
保留历史，不通过静默修改 WIP来制造一致。
同样，RAG目标草案第 2116–2241 行的 `as_of:2026-08-16`、BHF目标与next action
是历史设计/校准上下文；模型比较文档第 428–451 行保存旧2×2实验及暂停点，
不能替代当前Qwen3-Coder结果，也没有因本次成功自动恢复正式比较实验。

**需要带走的已知工程欠账**：

- handoff helper 多次 1500-token 超限、Windows direct-script 长时间运行及 `runpy`
  绕行已在消息 186–404 记录；不能只写 task packet stale，也不能断言增加 token 上限
  就能解决。后续按一次聚焦诊断处理，不能挡当前产品。
- release packager 的 `_projection_status` 当前按 verified refs 和同 commit 返回
  `demonstrated`，但这不足以证明任意自然语言 claim。历史消息 124/132 已指出，
  当前 `.agents/skills/release-evidence-packager/scripts/package_release_evidence.py`
  第 361–375、421–431 行仍如此。发布前逐条核对主张范围，不把工具标签当语义证明。
- explicit Patch continuation 已不以 `latest` 决定准入；旧 Planning continuation 的
  latest迁移在消息 700 明确后移，当前 `fresh_planning_continuation.py:483` 仍有该检查。
  不将一次 Patch修复写成全 stage统一，更不自动启动迁移。
- Trace应关联内部 run identity、独立 invocation和共享 session，短CLI退出前flush；
  exporter故障不能改变产品路由，评测分数不是权限。现有 injected transport不证明
  真实生产sink。GitHub迭代可见性、remote备份/PR、hosted CI与发布材料也没有由本次
  本地提交核查证明；历史讨论不授权本轮push或发布。
- 原始模型/运行例证各有限制：27B Fresh成功不能覆盖其旧Patch超时，4B Patch no-go
  不能推广到所有角色，Sol对照不能冒充本地自主，Qwen one-shot/loop不同条件不能当
  单变量因果实验。Router、多真实任务Eval、通用correction、compiler/test和Runtime
  feedback都仍需各自产品证据。

本轮已把当前 P0 推进到“原重启义务下存在已定位的共享状态回归，先修订 Patch”，
而非继续等待对原diff审批。后续排序仅在 Queue维护；不自动重跑旧Actual，不重建
八张图、第二Graph或新的长期任务账本。

### 9.6 本轮实际验证

本轮为完整回读、交接修订和静态产品审查。执行了工程认知 summary、Git只读核查、
日志解析及双记录正文一致性比较、附件/日志文件hash、六份当前Artifact的canonical
hash、两份response bytes hash和diff文本hash核对，均与所引用身份一致。
没有运行pytest、真实模型、Build、Actual、Apply或游戏，没有改写产品源码或原Artifact。
四个当前入口文档的修订不把历史439/478/90等结果升级为本轮或最终HEAD全仓回归。

收口核验：18 个本地文档链接解析后全部存在；六份原有 WIP 的 SHA256 与本轮改动前
一致，目标 rollout 的 SHA256 也未变化。28 个前置提交均为当前 HEAD 的祖先。
独立复核读取了四份文档完整 diff，并对照原文及共享状态源码，未发现剩余实质错误。
文档检查命令：

```text
git diff --check -- docs/ACTIVE_PRODUCT_CONTRACT.md docs/PROJECT_STATE.md docs/IMPLEMENTATION_QUEUE.md docs/audits/PATCH_AGENT_PROGRESS_RECONCILIATION_20260905.md
```

结果：通过。本次四文档修订留在工作树，未暂存或提交；原有六份 WIP 保持原状态。

## 10. 本页后续澄清：完整七组建设就是十日目标

> 目标澄清仍有效：七组均属于十日目标；本节不表示这些目标已经交付。

用户先要求“把当前 AccurateCrosshair 这条 case 推过真实 blocker；不要把这次 case
继续扩成整个项目的长期建设。然后马上回到真正的完整建设目标”，随后以截图明确
当前 P0 是真实 Mod 的正确修改/Build/Runtime，项目目标是可重复、可追踪、可评测、
可交付的生产级 Coding Agent。用户进一步纠正：**“这些所谓长期目标才是真十日目标。”**

因此，本页先前“十日 Core 只是阶段性交付目标”的执行解释撤回。第 9 节准确保留了
旧页 Core 采纳历史，但不能继续用该历史把以下建设默认推到 Day 11+ 或无限期长期目标。

| 十日建设范围 | 要交付和验证的方向 |
| --- | --- |
| 端到端 Coding Agent | 自然语言需求经 FeatureSpec/Evidence/Planning/Patch/Review/Approval/Apply/Build/Runtime；真实失败进入 Repair/Revalidation，最终交付可运行产物 |
| 生产 Evidence/RAG | 自主 API discovery、自主 target selection、来源与 freshness、support/conflict/gap、覆盖度和 API Evidence 的实际语义消费；不能只证明结构携带 |
| Agentic Execution | 模型使用工具和 observation、有界 correction、compiler/test/runtime feedback；覆盖明确真实失败及停止边界，不以任意错误必可自动修复为声明 |
| Trace/Lineage/Langfuse | 真实生产 sink、run/invocation/session 关联、短进程 flush 和证据绑定的评分；观测系统继续是单向 consumer |
| Model Qualification / Routing | 基于真实任务资格结果形成 role→可用 profile；保留各模型/角色/输入的资格边界 |
| 固定任务 Eval | 冻结真实任务集，衡量 Evidence、Patch、Review、Build、Runtime、Repair、工具回合、tokens与延迟；不能以一个 case 代替稳定性 |
| 环境/CI/Release | 锁依赖、实际干净环境重建、hosted CI、可重复 Build、release manifest、README、演示与交付材料 |

这七组是既有五线与相关目标的展开，外部调用可靠性继续贯穿其中；不是新建七套控制系统。
把它们纳入十日目标不等于已经实现，也不把任意仓库/语言、无限任务、任意故障恢复等
未约定的泛化加入目标。当前所需权限仍沿用现有边界。

当前执行顺序保持：先有界解决 AccurateCrosshair 的已知真实 blocker，推进必要的
Build/Runtime；完成后立即返回上述完整建设。若该 case 被独立权限或环境条件阻塞，
必须记录其精确未完成状态并推进不依赖它的十日工作，不能拿等待或扩大 case 消耗整个计划。
已有十日草案的旧 Gate 预算不再证明完整七组范围可执行，后续排程应按实际剩余工作量
调整；出现时间冲突时明确报告并由用户决定取舍，不自动降成“只做 Core”，也不把诚实
报告或局部成功改写成十日目标全部完成。六份用户 WIP 仍保持原字节。

## 11. 本页有界 P0 推进：源码单元、新 Findings/Plan 与当前请求阻断

> 历史执行窗口：当时输入、结果与决定保持冻结；不作为当前执行状态。

### 11.1 主体与失败来源

用户明确要求由**产品 Agent**生成 Mod 修订。工程侧研究修法不等于产品自主修复；
本页曾准备探索 assisted response 导入，但在用户纠正后停止该路线，没有生成或导入
工程修订 `after_text`，没有写 canonical Mod。测试只使用原基线和原 Proposal 中已存在
的错误代码，独立 expected/Harness 不交给产品模型。

原 deterministic `ProposalReview` 已通过。失败来源是后续工程/人工语义复核及其行为
反例，不能改写成原 Review 已检测出语义失败。用户另外明确：关闭 Accurate Spread 后，
First Shot Match **保留现有首发准确尺寸效果**，不改成基于游戏原尺寸缩小。

### 11.2 已实现并验证的源码单元修复

新增检索曾把 `GetCrosshairSize()` 表达式方法当作第 157–179 行窗口；字段检索也会跨入
邻近成员。提交 `aa3a72f77844edd98102494e4a576523736ffe1d` 只修改
`src/mod_agent/evidence/rg_live.py` 和 `tests/unit/test_rg_live_evidence.py`：完整单行表达式
方法及字段使用准确物理单位，并拒绝将注释伪声明、同一行多个声明标成单个精确单位。
本例方法为 167–167，`_targetSpread` 为 28–28。复杂多行形态未升级成完整 C# parser。

先复现范围错误，后补已发现的注释/多声明边界；最终相邻 checkpoint：

```powershell
python -B -m pytest tests/unit/test_rg_live_evidence.py tests/unit/test_requirement_coverage.py tests/unit/test_fresh_planning_continuation.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\rgunit-final-$PID"
```

结果：176 passed，23.69 秒，2 个既有 jieba warnings；两文件 Ruff 与 diff check通过。
这证明测试覆盖的检索行为，不证明新 Mod Patch、Build 或 Runtime。

### 11.3 实际 C# 的有界负例与行为矩阵

本轮以真实七份 Mod C# 源码及外部引擎/配置 doubles 编译运行，保留原基线和原错误
Proposal两种输入。初次12进程捕获 Recoil、Match、Inner cold-start 回归；随后按用户
列出的范围扩至 `2源码 × 2开关 × 7场景 = 28进程`，不是28个独立真实产品任务。

[Harness说明及命令](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_behavior_repro/README.md)
与[28进程结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_behavior_repro/behavior_matrix_results.json)
绑定实际输入；结果文件 SHA256 为 `990d67fce977a2ac57165fb470384cdb8bf355d773dea0404e3cb978f112184d`。
执行命令为该目录的 `python -B prepare.py`、`.\compile.ps1`、`python -B verify.py`。
true七场景观测与基线一致；false cold-start捕获已有三条回归。false且FirstShot=None
的冷启动普通回调保留raw，warm true→false的回调/协程则暴露旧状态覆盖问题。
warm诊断不升级成“分别重启”的原验收硬门；Pop还没有专门场景。
这不是 GTFO Runtime、依赖ABI或完整产品Build验证，当前不再扩此Harness。

### 11.4 一次真实增量 Findings 与新 Plan

任务局部编排复用现有 `RgLiveEvidenceProvider`、
`StructuredModelRequirementCoverageProvider.findings`、`build_requirement_coverage_pack`、
`ImplementationPlanner`、`ArtifactStore` 和 Patch preflight，没有新 Artifact 类型或控制面。
保留未变 FeatureSpec 与已验证 projection；旧有效 Evidence加新增精确源码共29项
整体进入新 Findings，不复制旧 findings 或旧模型执行收据冒充新结果。

本次唯一模型命令：

```text
python C:\Users\10160\.codex\visualizations\2026\09\05\01a07014-bccb-7420-bbcd-38defc72fecb\run_case_findings.py execute
```

结果：`qwen3.6:27b`，一次 Findings，0 projection，0 correction，357.30秒，
9,415 prompt tokens / 543 completion tokens；新 Coverage为sufficient。
这是部分重算，不是新的完整 Fresh run，也没有通过要求完整 Fresh收据的 Planning continuation。

| 对象 | 精确 Artifact hash / 实物 |
| --- | --- |
| 新 EvidencePack | `10a3fadd00b7437ee988729f8e78cab1d559f2f3bb774920da5ffbb45c17d3fe`；[实物](../../artifacts/g1_assisted_findings_context_repaired_27b_fc/store/features/feature_66e54ec4a116/r/evidence_pack/10a3fadd00b7437ee988729f8e78cab1.json) |
| 新 Plan | `c760a9cc2e04110c0f5a8fa1f6efcb8d661169fbdf76776596232f795100d129`；[实物](../../artifacts/g1_assisted_findings_context_repaired_27b_fc/store/features/feature_66e54ec4a116/r/implementation_plan/c760a9cc2e04110c0f5a8fa1f6efcb8d.json) |
| 新 Findings receipt | [执行记录](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_revision/findings-receipt.json)及同目录原始response/provider request |
| Planning receipt | [执行记录](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_revision/planning-receipt.json)；0模型、明确`explicit_operator_assisted`目标选择 |

新Plan保留原四目标，新增`UpdateCrosshairSize`的53–60范围；`AdjustCrosshairSize`、
两个`GetCrosshairSize`及其他新增源码保留supporting，不自动给全部方法写权限。
Bindings通过正式change-support集合检查，现有`preflight_patch_continuation`通过。
工程侧将已核实的失败与用户澄清写入新Plan的既有`side_effect_boundaries`，没有提供
正确实现；这不等于已有自动语义反馈→上游回退→重新规划产品闭环。

### 11.5 当前精确 blocker 与剩余决策

`run_case_patch.py`不带`execute`执行现有生产producer与Agent adapter的零网络请求检查。
它在发送前得到：

```text
failure_classification = provider_request_context_budget_exceeded
provider_body_utf8_bytes = 65821
num_predict = 4096
configured_num_ctx = 49152
conservative_required_context = 69917
```

[完整离线结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_revision/patch-preview.json)。
新Patch网络/模型调用均为0，没有新Proposal/Review/Dry-run，也未消费真实Patch attempt。
这里证明字节代理拒绝了请求；尚无这份请求在Qwen3-Coder tokenizer下的实测长度，
不能写成已证明真实上下文溢出，也不能写成已实测确认误判。

离线体积分析发现binding与supporting输入重复包含成员metadata。仅把完全相同的
`declared_members` / `declared_member_types`改成引用的纸面投影仍不能保证通过当前门，
因此没有把该实验写成修复、修改生产prompt、移除验证或盲目加大`num_ctx`。

P0已形成精确路径阻断。下一有界能力应在七组十日建设中的上下文/外部调用可靠性
范围评估；不继续从本Mod扩出通用框架。工程可先查重复表示与真实计数/可验证估计，
但实现规则改变必须有证据、聚焦验证和明确的当前作用域。其它十日能力不因这一条
请求受阻而全部停止。`EditAuthority`的范围批准与新diff的人工语义/exact批准保持区分。

## 12. 两小时执行窗口

> 历史执行窗口：当时输入、结果与决定保持冻结；不作为当前执行状态。

用户已授权执行工作包。T0为2026-09-05 08:44:24 UTC（北京时间16:44:24），截止10:44:24 UTC。
主线是A1生产输入表示→A2真实Agentic Patch与新修订验证；A3自主Planning独立并行。
工程侧不得提供正确Mod实现；新增exact diff与实际游戏操作按包内边界处理。
具体执行结果在本节续记，不将两小时结束等同于P0或七组十日目标完成。

### 12.1 生产输入压缩与首次真实 Patch 接受运行

`d84d888`在现有`_patch_agent_initial_messages`接入重复成员metadata与supporting
source metadata的共享表示。原有1024-byte supporting excerpt投影之后可canonical逐项
往返；保留5个edit上下文、24个supporting、Feature义务与用户澄清。它没有恢复此前已经
截断的原文，也不是新Binding或更大的模型上下文。

生产serializer零网络检查得到44,600-byte首轮请求，输出预算4,096，配置context49,152。
[输入往返与真实preflight](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_revision/context_codec_preflight_001/context_projection_validation.json)。
3项聚焦回归先红后绿；一次相邻checkpoint为216 passed、2 warnings、18.79秒：

```powershell
python -B -m pytest tests/unit/test_local_entry.py tests/unit/test_patch_agent_loop.py tests/unit/test_fresh_planning_continuation.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\pctx-checkpoint-$PID"
```

随后执行当时的`run_case_patch.py execute`，同一Feature/Evidence `10a3fadd…`/Plan
`c760a9cc…`真实调用`qwen3-coder:30b`。模型digest为
`06c1097efce0431c2045fe7b2e5108366e43bee1b4603a7aded8f21689e90bca`；
3次模型调用（源码工具选择、初稿、既有header correction），1次binding001源码检查。
合计41,575输入/3,340输出tokens，331.44秒。首轮实测13,021 prompt tokens；该数字只说明
这次实际输入，不把旧65,821-byte请求的真实token长度倒推成已测量。

当次continuation终态为`continuation_failed`，不是Proposal/Dry-run成功。
直接原因是**本页临时调用脚本漏传`max_model_calls`**：外层默认1，而内部loop预算5、实际3。
生产CLI已在Agent loop模式传5，故不改生产validator、不增预算。临时调用已改为显式传
`policy.max_total_model_turns`；AST、纯计数校验与五份旧文件hash验证均通过，未重放模型。
[调用方诊断](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_revision/patch-caller-budget-diagnosis.md)。

| 留存事实 | 精确身份 |
| --- | --- |
| 原失败receipt | `cr/ccc254c3eb122bf821fdf3b7a5e174f5.json`，run `patch_continuation_a2ee10450a614ee2884ceb2938079a09` |
| 原最终model response SHA256 | `3c8991684cad1de856ea19337ebac8475f17625ed10cc213933bc77f8f583f76` |
| 实际生成5 changes的SHA256 | `88d7e65162d4453f675deb709551a181541ae5eee00faf6d0aba49a1983d5efe` |
| source snapshot | `421ea5eb4785db9fd03740ab76d9f5eff84bf0cedbee9d749679271febf860a0`，前后相同 |

来源检查另发现当时receipt的`model_input_sha256`是压缩前native输入身份；压缩后的实际
wire body身份没有单独绑定。已有实际模型返回和raw输出，但不能宣称这条完整wire来源链
已通过；修补结果及其后续接受运行另记，不追写旧receipt制造当时没有的观察。

### 12.2 留存新模型输出的离线行为诊断

既有materializer从当时exact Feature/Evidence/Plan和留存最终response重建5 changes，
schema、native model input和changes SHA全部匹配原失败receipt。4项after_text逐字来自
raw；header仅由既有确定性materializer恢复BOM。没有工程正确实现、参考实现或新模型调用。

这次不是给失败continuation补写正式Proposal/Dry-run，而是在独立目录诊断其已生成内容。
[来源证明](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_behavior_repro/acceptance_runs/failed_ccc254_offline_001/provenance_audit.json)
与[结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_behavior_repro/acceptance_runs/failed_ccc254_offline_001/acceptance_results.json)
记录40次C#进程执行、36项检查，32通过、4失败：

- false冷启动霰弹枪的Follow Recoil行为仍错误；
- First Shot Match首轮和第二次cooldown后尺寸为140，基线为30；
- First Shot Inner尺寸为10，基线为30。

新增检查只补既定Pop义务和重复cooldown的正向验收，未扩成Unity模拟或新增任务集。
配置I/O和引擎仍用外部doubles；这不是GTFO Runtime或完整Mod依赖Build。
用户明确的冷启动preservation仍未修复，因此原/新失败输出均不得建议批准或Apply。

### 12.3 自主Planning实现检查点

`e128ff9`把`ModelPlanningTargetSelector`接入既有`create_implementation_plan`节点。
模型读当前源码与完整change-support选择集合，返回语义目标ID；现有compiler/Binding
核验范围、身份并生成新Plan。`needs_evidence`或非法选择生成blocked Plan，不使用人辅
IDs兜底。模型原响应、usage、前后源码验证和receipt hash可回查；未增加第二Graph。
已接受的用户语义反馈保序去重写入新Plan的既有`side_effect_boundaries`，测试证明其继续
进入Patch义务投影。`48ab878`补齐selector输入的完整FeatureSpec，包含原先投影遗漏字段。

基础接线checkpoint：311 passed、2 warnings、112.01秒，命令为：

```powershell
python -B -m pytest tests/unit/test_model_planning_selection.py tests/unit/test_planning.py tests/unit/test_workflow_graph.py tests/unit/test_product_execution.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\a3-final-$PID"
```

之后的反馈贯穿回归先红后绿，10项selector测试4.45秒通过；完整Feature补丁后的同组
10项3.84秒通过。311结果属于基础接线，不冒充后两处小修改再次全跑的结果。
截至该检查点尚无真实Planning模型运行；旧`c760a9cc…`仍是人辅Plan，不能改写其历史。

### 12.4 实际请求身份与一次真实自主目标选择

`43dccbd`在既有Ollama Agent诊断中记录与实际HTTPX JSON encoder一致的请求体hash，
保留每轮provider诊断，并在Patch factory receipt中区分native输入、实际initial messages
和编码版本。没有改变传输字典、输出schema、context或调用预算。
5项聚焦回归先红后绿，四文件checkpoint236 passed、19.86秒：

```powershell
python -B -m pytest tests/unit/test_agent_turn_adapters.py tests/unit/test_patch_agent_loop.py tests/unit/test_local_entry.py tests/unit/test_fresh_planning_continuation.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\pidentity-checkpoint-$PID"
```

加入明确编码版本和准确guide之后，旧5-binding请求变为44,732 bytes，仍在原预算内；
[零网络证明](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_revision/request_identity_preflight_001/verification.json)。
这不补写旧`ccc254…`没有记录的wire观察。

自主Planning输入最初48,170 bytes，被原byte proxy拒绝。`de28829`只共享重复
source_type/path/hash三元组，全Feature、29 observations、9个合法目标、4条反馈及源码
内容可canonical完全还原，最终45,021 bytes。另补返回目标必须属于本次实际prepared enum
的回归，避免仅通过旧helper、但item authority不匹配时receipt误报selected。
12项聚焦测试4.18秒通过，Ruff/diff检查通过。

首次安装节点接受运行`case_autonomous_planning_001`因临时runner预检使用raw Artifact
的JSON字段插入顺序、正式Graph使用FeatureSpec序列化顺序而被strict wire hash检查挡住。
HTTP/model均为0，blocked Plan `1ba3d00…`和原claim保留。修复的是runner输入构造，
解码后的全部Feature/request值相等，未减弱hash检查、修改prompt或重放模型。
[精确差异与诊断](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_autonomous_planning_002/construction-diagnostic.json)。

随后`run_case_autonomous_planning.py execute`在002目录成功执行一次模型调用：
qwen3-coder:30b、11,657输入/318输出tokens、78.61秒。实际wire SHA为
`c62491257ebe0101f0ab129ff1d9cd9072b798805cc51786372686e3e8d6b6d5`，
与预检和provider诊断一致，模型digest前后一致，canonical Mod未写入。

模型自主选择6个精确source units，compiler按Evidence顺序规范化为6 bindings：
OverrideCrosshairSize、BindAll、Configuration文件头、Configuration静态构造函数、
UpdateCrosshairSize、带参数的GetCrosshairSize。没有工程补target IDs；这不是把旧5目标
改写为自主选择。新Plan为
`e504888e5c7a366066495b7db1830dde6243771a79a3cbae8d10cbd82b5d1325`。
[结果与exact refs](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_autonomous_planning_002/result.json)。
Plan.trace_refs绑定selector receipt SHA
`461f54e84033a440955792ecbf14a006f720e9bf8c27fd8b1b089ba62a3358fe`。

**该结果证明模型目标选择与现有Planning节点的真实接线，不证明规划语义质量通过。**
模型rationale提到Loader.cs和FirstShotGuiPatches.cs，但二者不在所选编辑集合；不因这句
解释增加bindings，也不据其自述证明preservation。完整Fresh、自主补证、自动semantic
replan及另一真实任务的Planning资格仍未证明。本次只执行安装的Planning节点，不宣称
公开CLI全链或Graph条件路由闭环已跑通。

新6-binding Plan的Patch零网络预检得到48,773 bytes，原byte proxy加4,096后为52,869，
再次高于49,152；新Patch模型调用为0。该请求SHA为
`bbf7282d0abcc2ab4bfee45e436984822e0d9168c98fe9eea269d530788d6bd5`。
保留完整输入后，下一决策转为核验复用同模型实测prompt校准；不继续仅为字节门裁减
语义输入，也不把新请求的真实token长度称为已测量。

### 12.5 独立锁定环境的实际重建

从`e128ff9983ff59afc67b0c8f4cc0c90f0dbbeab1`的Git对象创建独立源码archive，
没有复制六份用户WIP或主环境。原setup先`uv lock --check`，再按原lock完成新venv
的frozen dev sync；Python3.10.20、uv0.12.9、184项依赖。离线首次只缺PyMuPDF wheel，
按锁下载后28.07秒完成，没有依赖升级。

567份archive源码均与提交字节一致且运行后未变；实际隔离Python import通过。
三个关键测试文件首次163通过、45因过长临时路径触发WinError3；从失败路径263字符
缩到246后，单条probe通过，再`--lf`运行余下44项通过。208个唯一测试均有通过执行，
不是一次208全绿。产品代码、锁、测试内容未为这项环境失败改动。

详细命令、stdout/JUnit身份和每项最新执行状态只保存在
[A8证据汇总](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/environment_rebuild/A8_EVIDENCE.json)，
其SHA为`ac638aa92a913f9e53c8b9ac579484cd98b9fb7b12a313b4fa77d486199f3632`。
这是Windows本机、干净venv、该commit及适用测试的证据；不是干净OS、当前所有后续commit、
完整测试集、hosted CI、产品模型执行、Mod Build或GTFO Runtime。
GitHub connector读取配置origin返回404，不能由此认定仓库不存在；本轮未取得hosted CI，
没有推送或发布。

### 12.6 本轮审查后的路线与文档修正

本页一度把A3自主Plan `e504…`接到P0的Patch预检，因6目标和新观察使首包再次超出
字节代理，随后开始跨客户端实测校准支线。用户转发的审查指出这样混合了Plan、上下文、
策略和调用接线变量。本页采纳：P0回到`c760…`，A3独立评审，A8收口，A6/A7本轮不扩。
自主Plan没有进入真实Patch调用，跨客户端校准没有进入真实模型运行。

校准支线的3份未提交代码/测试共250 additions、3 deletions已按原字节与diff完整备份到
本任务scratch `paused_calibration_wip`；确认只含本页工程改动后，执行checkout恢复到
已提交版本。原6份用户WIP未改。该校准尝试未完成全组测试/preflight，不能标为已交付能力。
其中已做5项测试通过、1项失败后仅该项重跑通过；不会计入已提交代码的236项checkpoint。

审查中“第一次c760的用户澄清没有传入Patch”不成立：该Plan已有3条反馈，第一次输入
投影和receipt对应的native输入包含它们。反馈丢失是在新A3接线发现并于真实运行前修复。
因此First Shot行为失败不能归因于这项并不存在的c760输入遗漏。

原长工作包已改为十日范围与验收参考，移除可执行启动指令、动态授权状态及两小时硬交付
混用；A0降为共同原则，A1停止在发送前，A2是唯一Patch接受运行责任方，A4首版只覆盖
已经出现的人类语义finding回上游，A5按自主查询/语义消费/机械字段分工。
当前输入另由短执行卡定位，实际权限仍来自用户消息及产品审批，任何Markdown都不能
授权新任务重放或预先批准未来diff。七组十日目标未降档。

### 12.7 固定c760的新接受运行与仍未修复的行为

使用同一Feature/Evidence/Plan、原5 bindings、相同qwen3-coder:30b及
`finalize_after_first_observation=True`。本次只使用已提交代码和已修正的调用方，
同一policy的总预算传给continuation与adapter；没有跨客户端校准，没有A3目标替换。
这是预算调用修复和请求身份补齐后的产品修订验收，不是单变量模型质量对照。

```powershell
python -B C:\Users\10160\.codex\visualizations\2026\09\05\01a07014-bccb-7420-bbcd-38defc72fecb\run_case_patch_baseline_reacceptance.py
python -B C:\Users\10160\.codex\visualizations\2026\09\05\01a07014-bccb-7420-bbcd-38defc72fecb\run_case_patch_baseline_reacceptance.py execute
```

零网络首包44,732 bytes及SHA `c00e2ea00671231a530b154acc3046e3c058179faebe0487066aeed1120d9766`
与实际发送前记录一致。真实运行205.25秒、2次模型调用、1次源码工具、0 correction，
27,229输入/1,699输出tokens。正式continuation到达`dry_run_apply`，停在exact approval前。

| 当前输出 | 精确身份 |
| --- | --- |
| 新Proposal | `af80386f328c6773ea54a79e9fa4d80fe67af9fa825e4b59cc7956ead1afa7c8` |
| 新deterministic Review | `965b4982d91838ab5b112c593ca985aacbd6bac1ea02934efae91bce6f009d57`，通过 |
| 新Dry-run | `28e5d9225ae258e332cd70a306e8f297300c2c7183c0324bc1407f98fa83108e`，无写通过 |
| receipt | `cr/d80ca492c728d18a8c294527136f1b38.json`，SHA `689170fa973719bedd09ee104f2204590da0447f172d8fe6e08902766a631d8a` |
| 模型原始content | SHA `2b4f580c5d1eb2a698b5e8f034ba321089c47b815ecb1703c655a26a19b720df`，7,443 bytes |

[完整执行结果与路径](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_patch_c760_reacceptance_001/result.json)
记录source前后一致，Apply/Build/Runtime均为0。
本次请求身份分层为native prepared messages `a08e08bb…`、实际initial messages
`f8803841…`、encoding `patch_agent_context_tables_v1`，以及每轮HTTPX body SHA。

| 真实回合 | body bytes | 实测输入/输出tokens | 实际准入方式 |
| --- | --- | --- | --- |
| 源码检查选择 | 44,732 | 13,044 / 12 | 原byte proxy，44,732+4,096=48,828 |
| 生成Patch | 50,301 | 14,185 / 1,687 | 同一客户端既有实测ratio校准；估计总需33,432 |

第二回合body SHA为`e1a8a4516a62cb18dfbf4dd076a5e1f66f2c8718d3154197ace88a17fe63651b`。
完整解析请求记录经canonical保存，因此初次审查不能直接按字典原插入顺序重放字节。
随后只用现有producer/loop、保留的两个响应，在socket禁止条件下离线重建两包，均匹配
当时记录的body SHA与长度，最终content也一致。该证明是**事后重建匹配发送时hash**，
不是原始HTTP抓包或新的模型调用。旧记录不改。
[重建报告](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_behavior_repro/acceptance_runs/c760_reacceptance_001/offline_wire_reconstruction/report.json)
SHA `d37e7a46ab9d0a5162be867ec1101db306ba4f4b40ae0c35b8a04ea69de27c1a`。

**新行为验收仍失败：40个进程、36项检查，33通过、3失败。**
Shotgun Recoil这次通过；First Shot Match首轮及第二次cooldown仍为140（基线30），
Inner仍为10（基线30）。raw、true路径及Pop相关检查通过。新代码已识别shotgun/archetype，
但false return仍早于`_validGun`、`_targetSpread`及`SetStoredCrosshair`初始化。
这定位剩余First Shot共享状态问题，不能宣布Mod修复完成或申请批准。

[本次行为结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_behavior_repro/acceptance_runs/c760_reacceptance_001/acceptance_results.json)
SHA `e6858aba7dc3d5e3e6ad9957be668b2cdc47fe0c6d3d228a03b24deff4c8b9cb`；
[来源核验](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_behavior_repro/acceptance_runs/c760_reacceptance_001/provenance_audit.json)
SHA `204a9d6d0308de02d8b3482fd7fa5300090f583ed51d0d613b7962fbfbf5883f`。
5处after_text均逐字来自本次模型响应，无文本增删或工程BOM修正；完整diff与Dry-run hash匹配。
测试仍用外部引擎/配置doubles，不是GTFO Runtime。本次没有追加模型尝试，也未申请exact approval。

### 12.8 A3独立质量结论及A7输入盘点边界

A3独立语义评审结论为`needs_evidence`：OverrideCrosshairSize、BindAll、配置声明区、
UpdateCrosshairSize有明确修改依据；静态构造函数已调用BindAll，带参数GetCrosshairSize
的计算也未被现有失败证明有错，二者修改必要性没有得到模型论证。rationale作为编辑集合
解释不成立：Loader/FirstShotGui只是supporting。不能因此扩权限，也不能只因未选
OnFileChanged判错；分别重启不等于热重载验收。
[语义审查](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_autonomous_planning_002/semantic-target-review.json)
SHA `043905889934545e3943099aadf7e1b9405695bc42e38f97dd5071cb45d58627`。
此评审不改写Plan或Graph路由；`needs_evidence`不自动授权重跑Fresh。

A7仅形成[机器输入盘点](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/a7_input_inventory/task_inputs.json)，
SHA `29049758308aefad884eec6a077696e3aeace11e7ffc8958e2d438635d6ff2d6`。
Stagger有原请求、源码及Build/Runtime/Repair实物，但需选择一致的修复前输入链；
WallCrawler有原请求与程序集身份，仍缺绑定的FeatureSpec、真实EvidencePack及可写Mod基线。
没有冻结3–5任务suite、运行资格评测、读取hidden golden或参考Mod实现。该支线已收口。

### 12.9 十二轮输入与本轮实际落实对账

本表是已发生工作对账，不是新Queue或全部完成声明。十二条输入均有对应处理，
但其中的产品交付要求没有全部完成。

| 原输入 | 本轮落实与证据边界 |
| --- | --- |
| 1：First Shot Match保留现有效果 | 3条澄清已在c760及实际Patch输入；新代码Match/Inner仍失败。输入落实，行为未完成 |
| 2：让产品Agent修Mod | 真实模型生成5处代码，来源/实际请求/完整diff核验；没有工程正确after_text。修复本身只部分通过 |
| 3：P0、旧Core与完整目标关系 | 七组全部保留为十日目标；旧Core/Stretch历史化。属于范围校准，不计新增产品能力 |
| 4：当前authority、复用合同、完整七组 | 复用现有Graph/Artifact/Plan/Binding/Review/Dry-run；新diff未批准、Apply/游戏写入均0。文档不再充当授权凭证 |
| 5：扩范围的合法恢复顺序 | 当前Evidence全集/Findings10a与人辅Planc760有效；A3新Plan单独保存。自动补证/重新规划尚未交付 |
| 6：语义失败自动回正确上游 | 缺口仍在。当前人工反馈、Evidence恢复和结果编排仍由Codex组织；不能用模型节点运行冒充自动闭环 |
| 7：preservation、状态、owner、checks及六类缺口 | 新Patch实际33/36检查通过，Recoil修复、First Shot未通过；Pop在现有doubles下通过。Build/Runtime及跨任务稳定性未证明 |
| 8：blocker是否妨碍推进 | 取得独立A3与环境实物，但一度把e504→Patch混进P0；审查后回c760并停止该旁路。没有用新限制替代交付 |
| 9：完整约束与自由执行 | 文档权限/历史窗口/单次调用责任已纠正；实际触及入口有检查。未做全仓所有路径的enforcement审计，也不将其变成前置门 |
| 10：模型与机械记账Owner | 模型真实选择目标，系统编译Binding；重复metadata/source identity已共享。Projection索引负担与Patch slot filling仍未改造 |
| 11：项目能力差距评价 | 当前状态绑定代码、真实运行、行为结果分别说明；A3语义质量needs_evidence，通用Repair、Trace交付、角色路由和多任务Eval未完成 |
| 12：三档约束与立即推进 | 未扩parser/全量Fresh；原/新失败保留；A1不发模型、A2独占接受运行；warm仅诊断。校准WIP备份后移出执行路径，其他支线按最新要求收口 |

新增两轮审查分别促成文档职责拆分和P0/A3路线重新分离；没有采纳错误的“c760丢失澄清”
因果判断。模型可逆输入不等于语义理解、结构Plan不等于正确Planning、Dry-run不等于
行为成功，这三条限制均由本轮实际结果保留。

七组目标的本轮增量分别是：端到端推进到新Dry-run但First Shot未修复；Evidence/RAG完成
本轮需要的输入表示/身份接缝；Agentic获得有来源证明的有界Patch与一次模型选目标；
Trace只补本地实际请求链，未交付Langfuse；模型资格/路由未完成；Eval仅输入盘点，未冻结
真实任务suite；环境取得一个commit的干净venv验证，CI/Release未完成。

### 12.10 本执行窗口内产生的提交

| Commit | 做了什么 | 验证/性质 |
| --- | --- | --- |
| `872b479` | 固定完整目标、历史核对、十二轮要求与执行编排 | 5份本页文档；不计产品运行能力 |
| `d84d888` | 生产Patch输入去重，保留原语义、绑定和supporting信息 | 216相邻测试；真实首包准入/模型返回；模型业务正确性另验 |
| `e128ff9` | 现有Planning节点消费模型目标选择，记录响应与source；将反馈传到Plan/Patch | 基础311测试，后续反馈贯穿10测试；不是全自动replan |
| `48ab878` | Planning模型输入保留完整FeatureSpec | 10项聚焦测试；不再漏掉原Feature字段 |
| `43dccbd` | 记录真实HTTPX body身份、编码版本、实际initial messages与每轮provider诊断 | 236测试；c760新实际两轮及离线重建均匹配记录hash |
| `de28829` | Planning源码身份无损共享，并校验返回ID属于本次prepared允许集合 | 12测试；随后一次真实模型选择与Plan生成，语义质量另评为needs_evidence |

源码单元修复`aa3a72f`发生在本窗口开始前，已在§11.2说明，不能重复算作本窗口新提交。
本轮最后的文档对账/角色修正提交由Git与最终执行报告定位；未完成校准WIP没有提交、没有
计作能力。测试组存在重叠，不将216/311/236/12/208相加作为唯一测试总数。

## 13. 新一轮P0：物理owner与有界行为反馈修正

> 历史执行窗口：当时输入、结果与决定保持冻结；不作为当前执行状态。

本节记录用户再次明确要求“动手”后的独立修复工作。旧两小时执行卡已消费，不作为
本轮或未来操作的授权凭证。固定Feature `fc7…`、Evidence `10a3…`、Plan `c760…`、
qwen3-coder:30b、原5 bindings及原40进程/36检查矩阵；不采用A3的e504。

### 13.1 三项失败的物理owner

对当前af803草稿、原源码、输入和执行轨迹的独立核对表明，三个反例的直接缺陷均为
**Patch实现错误**，而非此次Evidence不足、Plan/Binding越界或执行环境故障。

| 失败 | 物理链条 | 原Plan已有owner |
| --- | --- | --- |
| Match首次cooldown：140，预期30 | timer已把spreadScalar变为0.2，但disabled提前返回使validGun仍false，更新被截断 | OverrideCrosshairSize（001）和UpdateCrosshairSize（005） |
| Match第二次cooldown：140，预期30 | 第二次timer确实完成，但相同状态缺失持续存在，没有尺寸写入 | 同上 |
| Inner可见但尺寸10，预期30 | targetSpread未初始化，FirstShotGui.Enable/GetCrosshairSize读取0并计算出10 | OverrideCrosshairSize（001） |

GetCrosshairSize和First Shot方法是错误状态的消费者，不能仅凭处在调用链就升级为编辑
目标。这证明当前直接缺陷在已允许范围内，不预先保证所有未来修法都能在原范围完成。
[owner原始核对](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/owner_review.json)
保存exact Artifact、源码和观察来源。

矩阵另有需要保留的限制：Match同时检查内部mainSize和可见renderedMainSize。
当前两者均140，故不影响这三个反例的归因；若新修订可见效果正确、仅内部字段不一致，
应停到validator语义复核，不能悄悄改测试或让模型迎合未证明的内部约束。

### 13.2 工程自检材料如何约束本次修法

已完整读取用户的《项目回头自检.txt》（768行）、《项目自检-8月17.txt》（194行）、
《rag_如何保证内容准确性.txt》（194行）及8张截图。这些是工程思想与问题材料，内部的
建议不自动成为当前任务、权限或门禁，也不激活PDF、Dense、微调、多模态等额外建设。

本次采用其中的判断方式：说明真实失败、所需信号、不能删除的环节和完成证据。
已有源码/Evidence能够解释反例，先处理证据被错误用于代码的问题；已有Graph、native
materializer、调用预算和Harness能够复用，只补行为观察的消费连接。API成功或结构合法
不代表业务成功；模型自评不能替代当前可执行检查。

原始Self-RAG训练模型产生reflection tokens来控制检索、生成和自评；外部测试反馈只是
借鉴质量参与决策的思想，不是等价算法，也不说明本项目必须增加训练。
[原始说明](https://selfrag.github.io/)。Ragas Faithfulness关注回答与上下文的一致性，不能
证明Mod运行正确，因而不替代本次行为矩阵。
[官方定义](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/)。
材料中的招聘比例、现成Agent完成百分比等未经独立核实，不作为本次实施或成熟度依据。

### 13.3 有界接缝及平台验证

`3079d31`在LocalOllamaInitialPatchAdapter的native materialization之后、返回Graph之前
接入可选behavior_evaluator。回调取得生成内容的独立副本、已保存模型响应和source身份，
在scratch执行现有矩阵。结果与报告文件内容/hash配对；只有已确认的patch_implementation、
已知绑定内的behavior_failed才进入同client的一次完整修正，随后再次materialize和重验。

header与行为修正共用总模型预算5，发送前检查；Graph的现有receipt消费同步计算两者，
最终generation保存行为报告/响应refs。环境、身份、缺证、新范围、内部字段语义不明或
再次验证失败均停止，不产生Approval，不伪造Build/Runtime，不新增Artifact类型或Graph。

Case适配器使用原Harness副本，仅修正“尚未正式Proposal”的来源显示，不修改36条检查。
它先通过离线旧模型输出重放再次得到33/36；六项分类回归证明错hash、编译/进程故障、
矩阵不完整和仅内部Match字段差异不会被当作可自动修Mod的三类旧失败。
入口位于本任务scratch `firstshot_feedback_001/case_behavior_adapter.py`。

21项平台聚焦测试通过，13.25秒；相邻checkpoint238通过、2旧warnings、19.30秒：

```powershell
python -B -m pytest tests/unit/test_patch_behavior_feedback.py tests/unit/test_fresh_planning_continuation.py tests/unit/test_patch_agent_loop.py tests/unit/test_local_entry.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\pbf-check-$PID"
```

测试使用Synthetic fixture验证协议，不包含工程编写的正确AccurateCrosshair实现；
平台测试通过不能代替真实模型及同矩阵验收。

### 13.4 第一次真实行为修正：反馈已送达，但代码没有改变

命令为本任务scratch的`python -B run_case_behavior_feedback.py execute`，输出在
`firstshot_feedback_001/actual_001`。初稿先经矩阵得到三个原失败，第三次真实模型调用
消费了该轮输入、预期/实际、validGun/targetSpread/spreadScalar等观察；没有正确代码答案。

结果为322.68秒、3次模型调用、两次完整矩阵执行。修正原文SHA为
`271a6e834cdef7cf23dea4dab69ac9295579373614f3032d03450ef0fcbe4a8e`，与初稿的原文字节
不同，但解析后的5处after_text、rationale和rollback_hint完全一致；两次native changes
SHA均为`dbe2e6d96c69a4c73d13f23a8b08f8ac4f23df24652e8d651b602f9cef58f929`。
两次矩阵均33/36，原三项失败不变。不是新的通过Patch，也没有新Proposal/Review/Dry-run。

receipt为`cr/0519c4472c7f4949706316d93a0deefb.json`，SHA
`689cebff8d64c43a0aef4db545e1d1225f5b291b3fe6094a43c47ed7f59f1572`；终止原因
`PATCH_BEHAVIOR_CORRECTION_FAILED`。canonical source前后相同；外层结果中的
failed_during_continuation不能被误读为源码漂移。Apply/Build/Runtime均0。

### 13.5 从实际请求发现的修正上下文缺口

第三轮请求明确包含失败观察，schema也没有把after_text锁成旧值，故不能说反馈未发送
或输出被schema强制固定。但修正轮角色为system/user/user：旧草稿嵌在user JSON中，
且只重用initial messages，未保留原loop获得的工具观察。该丢失可由聚焦测试复现；
它是否导致本次原样返回仍需实际验证，不能直接归咎模型能力。

`d109e32`只在成功LoopResult的内存中深拷贝保留最终生成请求（不扩大持久化状态）；
修正复用原messages/tool_results/provider_state/插入位置，随后追加assistant草稿和user
失败观察。实际serializer回归证明顺序为system→user→assistant工具调用→tool观察→
历史loop状态→assistant草稿→user反馈；观察内容/hash、源码身份和工具次数均保留。
初始请求、Plan、schema、模型、预算和矩阵不变。

新增回归先失败后通过；受影响checkpoint239通过、2旧warnings、19.84秒：

```powershell
python -B -m pytest tests/unit/test_patch_behavior_feedback.py tests/unit/test_patch_agent_loop.py tests/unit/test_fresh_planning_continuation.py tests/unit/test_local_entry.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\pbf-context-check-$PID"
```

第二次有依据的接受运行使用`run_case_behavior_feedback_context.py execute`及独立
`actual_002`目录；旧失败、claims和所有响应保持不变。实际结果另记，不能由239测试
通过预先宣布Mod修复成功。

### 13.6 第二次真实结果：改动发生，但产生回退

Actual002持续327.27秒，3次模型调用、0 header correction、1次行为correction，执行
两次原40进程/36检查矩阵。首包与前次相同；实际修正请求为61,108 bytes，角色顺序和
工具观察均符合§13.5的保留要求，assistant草稿逐字匹配已保存的模型输出。

模型修正仅改变binding001：把disabled return移到weapon/isShotgun识别之前；另外4处
after_text未变。初稿33/36，修订32/36：原Match两项、Inner一项仍失败，并重新引入
`FALSE_COLD_SHOTGUN_RECOIL_PRESERVED`失败。新响应SHA为
`aa12a2398a689f1bd82ae3ff6d903a76ccf350844eec3e9ab38eca0e570e4a0f`；
修订native changes SHA为`7a7b20d51313d077e5c06f3d51a1bc2f1a4cf0d683017eef27f1ba3d668fd67a`。

当前case分类器仅事先核实了三项First Shot失败，故对新增Recoil组合返回
`needs_evidence / unknown`并停止。这表示自动分类覆盖有限，不能据此声称当前Evidence
或Plan必然不足，也不应追写当时报告为已自动识别。其事后源码归因另行核对。

事后核对已确认新增Recoil属于binding001内的Patch回退：冷启动isShotgun保持false，
未修改的RecoilPatches.EnableCrosshairMovement据此错误开启movement。三轮实际请求
字节与provider receipt hash匹配，两次生成代码及物化文件也匹配相应模型响应。
[事后核对报告](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/firstshot_feedback_001/actual_002/post_run_owner_review.json)。
这不修改运行时的unknown分类，也没有扩大回调自动识别范围。

receipt为`cr/64a3b3a6dd7ad3b1a80e23d823ce0b0e.json`，SHA
`ce54c3117f4bdc5de799d265a8eb74952f4d2ac83d909c018405d38588151da8`；
没有新Proposal/Review/Dry-run，Apply/Build/Runtime均0，canonical source未变。
第二次矩阵SHA为`aa2a5b4a4173e9693dfdcd7030cd38587790500c9fc5134b0d309335694fd45e`，
反馈报告SHA为`b21eca3668d4937a7e72386f53c304fe7291d01fdb4f90ae05218694ec235056`。

本轮因此只能证明已实现并真实触发的反馈传递、一次有界修正、来源保留和失败停止；
不能证明修复成功。两个输入组装版本的真实结果均不支持当前qwen3-coder配置已具备
这一case的可靠修复能力。也不能由单case推断该模型在所有任务上都不具备修复能力。

停止继续给同配置追加相似提示或模型调用。为新的技术选择，仅准备了本地
qwen3.6:27b的零网络对照：首包除model字段外完全相同，44,728 bytes、相同schema、
Plan、bindings、context/output预算、工具策略、行为矩阵及停止条件。模型当前存在，
digest为`a50eda8ed977ab48a12431878896b27ffd5cef552c17af3317d9623b939a7f1e`。
这是尚未执行的对照准备，不是自动fallback或默认profile变更；已向用户询问是否进入
更换模型的对照范围，未得到回复前不发送。

### 13.7 用户选择与本轮失败报告

用户随后明确选择“保留当前模型，先提交本轮失败报告”。因此本轮不运行已准备的
qwen3.6:27b对照，不改变默认模型，不追加同配置尝试。对照目录只有零网络预检文件，
没有attempt claim或真实响应；后续是否启用须由新的当前请求决定，旧预检不授予权限。

结论：**原三项首发准星显示失败的物理owner已确认属于Patch实现错误；本轮没有产生
通过同一行为矩阵的新Patch。** 主准星模式两项涉及原binding001/005，内圈错误来自
binding001跳过共享初始化；第二次修订新增的霰弹枪准星移动回归同样来自binding001。
当前未证明Evidence不足、Plan缺少修改范围或测试环境故障导致这些反例。

| 接受运行 | 实际修订结果 | 同一矩阵结果 | 产品到达位置 |
| --- | --- | --- | --- |
| Actual001：接通失败反馈 | 模型只改变JSON排版，5处代码未变 | 33/36，原3项失败 | 生成阶段停止，无新Proposal |
| Actual002：保留读到的源码和模型草稿 | 只改001，把返回提前，新增Recoil回归 | 32/36，共4项失败 | 生成阶段停止，无新Proposal |

两个运行各3次真实模型调用；每次均执行草稿与修订的相同40进程/36检查矩阵。
原响应、输入、报告和来源链均保留，canonical Mod未改变。没有新Review/Dry-run、
exact approval、Apply、changed Build或GTFO Runtime。平台反馈、预算和失败停止的验证
通过，不等于Mod完成，也不等于成功的行为Repair。

本轮代码提交`3079d31`补齐内部行为反馈接缝；`d109e32`保留修正上下文；
`5fe8595`固定物理owner、真实失败及限制。本节补记用户最终选择，不改写任何历史运行。

## 14. 2026-09-06 术语与实现覆盖核对：共享 Patch 与行为 Repair

> 阶段对账快照：早于第0节最新收口；本节WIP与剩余次数只适用于当时。

本节是用户要求的近轮次关键词对账，不是第二队列，也不授予执行权限。
本次核对时已提交 HEAD 为 `458c098`。A=`1ba8607`（共享worker、行为Repair入口、按需读取）；
B=`458c098`（批次读取预算反馈）。WIP 表示已在工作树中但尚未提交，不能归入 A/B。
“模拟”指可重复的程序模型替身及合成项目测试；“真实”指本地产品模型真实返回。

### 14.1 提交实际做了什么

- A 改动6个生产文件、4个测试文件：现有 continuation 支持精确父 Proposal/原 Review/失败报告/原模型响应/原收据；
  START→create_repair_plan→同一 Patch factory 包装→完整 Proposal→Review→Dry-run。
  修订复用同一工具循环，保留原生多次工具往返；支持29个只读引用，其中仍仅5个可编辑。
  supporting/API 内容可按需读取；初始输入保留关键代码、原义务、完整被测 C1 与失败 F1。
- B 解决实际模型一次请求5项读取时立即停止的问题：合法批次顺序执行；超额整批0执行，返回明确预算反馈；
  重复超额停止。模型预算可以由上层下发1–5，本轮后续仅使用剩余额度。
- A 的受影响 checkpoint：288 passed，2个既有 warnings，32.96秒。
- B 后的受影响 checkpoint：99 passed，2个既有 warnings，18.57秒。
- 当前WIP：拒绝且未执行的请求不预占执行ID；已保存真实工具响应的严格校验接续。
  前者原响应回放及loop/adapter共67项通过；后者23项聚焦测试通过，尚待组合验收和提交。

### 14.2 关键术语逐项对应

| # | 术语／说法 | 具体落实与验证范围 | 当前归属 |
|---|---|---|---|
| 1 | 共享 Patch worker | 本次行为Repair和首次生成调用同一有界执行能力；不是所有旧Build/Runtime路径已完成迁移 | A，模拟全链通过 |
| 2 | 同一个执行循环 | 生成与header/behavior修订可复用run_patch_agent_loop；不是另建修复执行器 | A |
| 3 | Patch 内层升级 | 可选多轮查证、工具结果保留、反馈修订、上游请求、共享预算 | A+B，真实完整成功未证 |
| 4 | Agentic Execution | 模型可以决定读哪个已登记位置或提交输出；不以调用工具次数代替智能质量 | A+B，有限真实选择已见 |
| 5 | B0／C1／F1／C2 | 原始代码、上一版完整修改、其失败、相对原始基线的完整替换分别表达 | A，实际wire核验通过 |
| 6 | 正在修的那一版代码 | 模型收到父Proposal对应的原始完整响应及5项after_text，不只是hash | A，父字节核对通过 |
| 7 | assistant | 表示前一条模型输出的消息角色；不是第二个Agent或Codex代写代码 | A |
| 8 | 完整替换／不叠加diff | 未Apply时新版本仍相对B0，保留全部5个变更，不能只输出失败owner子集 | A，模拟验证 |
| 9 | 三部分上下文 | 常驻需求与约束；预置关键编辑源码；按需读取supporting/API目录 | A，实际wire核验 |
| 10 | 轻量上下文 | 可读目录替代重复正文及机械metadata；并未删原验收要求和C1代码 | A，首包准入通过 |
| 11 | Artifact完整≠Prompt全量复制 | 完整Evidence留在Store/读取器；模型首包只携带有用目录和关键源码 | A |
| 12 | Preservation obligations | 原需求、验收、约束、runtime要求、change units、validation、binding IDs等8项原语义字段逐值保留 | A，发送内容核验通过 |
| 13 | First Shot Match／Inner | 原首发准星显示功能；Match两项、Inner一项仍为旧失败。不是新增加的Mod需求 | 既有义务，修复未证 |
| 14 | Follow Recoil／霰弹枪Recoil | 原准星跟随后坐力移动行为；仍须随First Shot修订一起保持 | 既有义务，新矩阵未运行 |
| 15 | ReadScope与EditAuthority分开 | 29个可读binding，只有原5个edit bindings可生成修改；读不会扩写权限 | A，离线/模拟验证 |
| 16 | Supporting Evidence | 可由模型按登记ID读取相关源码；新读取不会自动变成正式change-support或新binding | A |
| 17 | 完整API按需读取 | 同工具读取3条已登记decompiled_api完整excerpt，明确registered_not_live_revalidated | A，不是新API发现 |
| 18 | 自主API发现／通用搜索 | 没有增加任意symbol/text search，也未证明自主生成API查询并形成新Evidence | 未交付，本次只消费已登记资料 |
| 19 | 源码工具观察 | 实际工具读到的源码内容及身份；没有新的业务owner或第二控制面 | 既有能力被A扩充 |
| 20 | 真实往返 | 本轮真实模型接收预算反馈后重选读取；新源码结果返回模型并产出代码的往返尚未完成 | 部分真实，不能写全通过 |
| 21 | 由观察决定下一步 | 真实Qwen由请求5处改为001+005；驱动它变化的是工具预算反馈，不能冒称已理解新源码 | B后的真实局部证据 |
| 22 | 失败观察可解释 | F1包含场景输入/配置、原要求的expected、实际observed、检查及被测版本身份 | A，真实输入核验 |
| 23 | 观察／诊断／执行决定分开 | 失败数据不等于根因标签，owner解释不授予新修改权限；原边界内可进行有依据的调查 | A，模拟；非通用诊断质量证明 |
| 24 | Harness由谁控制 | 确定性回调执行固定检查，模型收到结果；模型不能改测试、期待值或自行宣告通过 | A，当前真实新检查尚未执行 |
| 25 | Header correction | 原一类using失败已有真实成功；新策略与行为修订共用worker和预算 | 历史真实，A复用 |
| 26 | 行为correction | 新草稿验证失败后可在同一循环查证并修订一次 | A，模拟通过；此前真实修订均失败 |
| 27 | General Repair | 没有证明任意compiler/test/runtime/semantic failure都可恢复 | 未证明 |
| 28 | Proposal前后边界 | 草稿修订与正式Proposal新revision有不同lineage要求；不因此另造代码生成算法 | A，本次行为恢复路径 |
| 29 | Repair职责 | 接收失败背景、核验前提、提出恢复方向；不会代替Binding或人工批准 | A扩展既有RepairPlanner |
| 30 | Repair路由／执行入口 | 真实af803父Proposal及行为报告可进入RepairPlan，再进入共享worker；后续完整Review/Dry-run仅模拟通过 | A，真实到worker，未真实闭环 |
| 31 | needs_replan／上游请求 | 工具可请求Evidence/Planning评估并停止，记录refs/理由；没有自动执行完整Evidence→Planning重算 | A，表达和停止已实现，自动回流未证 |
| 32 | unknown继续调查 | 身份合法且有真实观察时可进入有界调查；不会自动认定Plan错或扩大binding | A，模拟通过 |
| 33 | 环境／验证器故障分流 | 明确环境/验证器等问题交原owner，不能自动改Mod迎合故障 | A，有限分类测试；非所有故障恢复 |
| 34 | 单一共享预算 | 读取选择、生成、header/behavior修订共用调用上限；父Repair重试计数不随revision归零 | A+B；本轮3次真实已耗，最多再2次 |
| 35 | 预留修订额度 | 初始生成阶段明确保留后续额度；预览必须带同一个evaluator，否则预算状态不同 | A+B；脚本漏配已修，原失败保留 |
| 36 | 少量接口／多项工具请求 | 读取与请求上游两个接口；合法读取批次顺序执行，超额不给隐式额外权限 | A+B |
| 37 | 工具允许／未用／执行失败 | 分别记录工具可用性、模型选择、实际dispatch与失败；无调用不直接归咎模型 | A+B |
| 38 | 未执行ID被误判复用 | 实际001重选与被拒批次合成ID相同；旧代码错误拦截，修复已回放验证但未提交 | WIP |
| 39 | 能工作，也能可靠停止 | 硬边界与有限反馈停止有测试；实际曾出现过早停止，故不能把所有停止都标为正确 | A+B部分成立，WIP修正误停 |
| 40 | 请求／响应真实身份 | 保存实际provider body、原响应、生成/源码hash；本轮各实发包原语义保留 | A及运行记录，不能靠hash代替语义验证 |
| 41 | checkpoint／幂等恢复 | 同attempt完整结果读取不重跑；未完成attempt不会无条件重发或重置额度 | A；任意阶段自动恢复未证 |
| 42 | 已付费响应可信接续 | 校验原attempt、模型、上游、源码、请求和原始工具响应后复用；明确回放来源，不算新推理 | WIP，23项聚焦通过，004仅零网络预演 |
| 43 | exact-diff approval／Apply | 旧批准不能继承到新代码；当前仍无新批准、Apply、changed Build或游戏操作 | 原合同保留，无新执行 |
| 44 | 审批前编译／行为验证 | 可在临时物化源码上跑既有C# Harness；不宣称正式产物或GTFO运行通过 | 回调已接，新代码尚未产生 |
| 45 | 更正确的新Patch／同矩阵通过 | 本轮真实模型尚未生成新的Patch，没有新的36项行为矩阵结果 | 尚未验证，不能写已修好 |
| 46 | 完整能力为验收单位／积极成熟化 | 已跨输入、工具协议、执行循环、Repair入口和恢复记账实施；模拟整体通过，真实产品结果仍缺最后环节 | A+B+WIP，未全部交付 |

### 14.3 与完整十日目标的关系

这次激活的是 Agentic Execution 与一类行为 Repair 的完整恢复能力。
自主Planning仍保持独立A3评价，P0继续使用显式人辅c760；没有新target selection证明。
没有把这次工作写成七组十日目标完成。固定3–5任务Eval、role→model资格路由、真实Langfuse、
hosted CI、发布交付仍未由本轮证明。Slot filling和跨stage机械字段全部收回也未完成；
本轮只改善了模型输入中已有supporting身份信息的机械搬运。

### 14.4 真实运行与尚未提交工作必须分开

| 目录 | 真实模型请求 | 结果与含义 |
|---|---:|---|
| mature_repair_001 | 0 | 预览漏配evaluator造成预算状态不一致；发送前比较停止，不能称Qwen失败 |
| mature_repair_002 | 1 | Qwen请求5处读取，被旧单工具规则拒绝；0源码工具执行、0新代码 |
| mature_repair_003 | 2 | 先5处，收到预算反馈后重选001+005；未执行ID被错误标为已使用而停止，0新代码 |
| mature_repair_004 | 0，截至本节快照 | 两个原工具响应严格接续的零网络预演；已读2处源码，下一模型生成包已准备，尚未发送 |

各目录位于本任务scratch的`firstshot_feedback_001`。所有历史运行、原响应和失败均保留。
截至此快照实际新模型请求总数3，剩余额度2；回放原响应不重新算一次模型成果，也不重复计费。
原输入为fc7 Feature、10a3 Evidence、c760 Plan、af803父Proposal、qwen3-coder:30b；未改成A3的e504。
本节的“已实现”绝不表示“Mod已经正确”或“生产级通用Repair已经通过”。
