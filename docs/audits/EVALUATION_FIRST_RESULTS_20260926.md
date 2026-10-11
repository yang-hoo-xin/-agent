# 首轮评测驱动开发结果：2026-09-26

本页保留2026-09-26起各批开发与评测经过，数字和当时待办按所属批次解释。最新可填写成果及缺口见[成果清单](../PROJECT_OUTCOMES.md)，活动工作方式见[交付与评测](../EVALUATION_FIRST_CYCLE.md)。AccurateCrosshair交付在第8、9节，独立首轮在第10节，重复及后续结果在第11—13节。

本主记录的结果截面仅包括下文明确命名的已完成证据。后续开发运行、诊断探针与候选策略不自动并入这里的分母；仍保留原运行和原评分文件。为什么要有它：同一目录会继续增长，新增诊断或改进不能回写成旧基线已经成功。

详细逐例判定留在机器记录中，本页集中解释口径、可填写成果及缺口。产品开发、RAG 问答、组件治理、受控编译和独立留出分别报告。为什么要有它：这些证据检验的对象和执行边界不同，不能相互增加成功数。

## 1. 早期回填截面（历史）

下表保留独立首轮附近的原汇总及当时缺口；后续实测已补充其中多项，当前引用使用[成果清单](../PROJECT_OUTCOMES.md)。为什么要有它：保留原解释与分母，同时防止历史“待测”继续影响今天的判断。

| 用户目标 | 本轮可填写的值或事实 | 口径与证据 | 仍不可填写的部分及具体前提 |
| --- | --- | --- | --- |
| 端到端任务交付 | AccurateCrosshair 配置需求已交付；两道 C# 独立工程题首轮 **基线 0/2、候选 1/2（0%→50%）** | 固定平台、模型、权限、预算与裁判；独立性限定于已核本地暴露记录，见第 10 节 | 更多任务与重复波动；修复后重跑已暴露任务不能改写独立首轮成绩 |
| RAG 质量与选型 | **1 份 RFC、16 页、39 chunks、10 道新编诊断题**；8 道可答题的宏平均 evidence-group Recall@3：BM25 **81.25%**，hybrid **68.75%**。AI 引用正确率分别 **17/22、20/27**；严格正确拒答分别 **1/2、1/2** | 固定语料与检索配置，两臂各生成 10 个真实回答；题目、gold 与语义评分均未经人工验证；见第 3 节 | 不能称整批 10 题为无条件语义独立留出：作者自审有 3 题部分重合。需要人工核验、多语料和更多独立事实目标；不能推广为代码任务交付收益 |
| 执行治理与异常恢复 | **18 类已知治理/续接回归场景、30 个 pytest cases**；选定应拒绝边界错误放行 **0/14**，选定重放/续接重复副作用 **0/5**。另一个预注册真实进程退出场景 PC01 恢复 **1/1**、重复目标替换 **0/1** | 组件场景和 PC01 分开计数。PC01 在 Apply 已持久化、CLI 响应前退出，第二进程恢复至受控 Build checkpoint；见第 4 节 | 不能把单点恢复写成任意进程中断成功率；未证明写入中断电、部分写入自动修复、跨进程并发、真实编译部署或游戏副作用。Run 02 全树版本稳定性检查未通过，限制须保留 |
| 上下文与资源优化 | 独立首轮基线/候选输入 **34,930 / 57,824**、输出 **3,563 / 5,857 Token**，平均工具观察 **6.5 / 12**；候选每次成功交付累计成本 **63,681 Token**（含失败运行） | 相同任务与预算，完成率 0/2 对 1/2；P95 为 **233.27 / 237.14 秒**，每臂仅 n=2；见第 10 节 | 当前没有资源节省结论；货币成本及同等完成质量下的优化收益仍待测 |
| 全链路追踪与定位 | 原 B0/B1 **0/2**；新增 dev01_b2、dev02_c1 各 **1/1**；独立首轮固定失败 cb1/tb1 **2/2** 完整重建 | 沿用同一七项标准，原始平台/源码、模型/工具正文及执行边界可核；分批版本保留，见第 6、10 节 | 基础日志与完整 Trace 的盲化定位计时尚未执行，当前未声明定位提速 |
| 评测驱动持续迭代 | 已执行公开开发题 B0/B1 及另一题 dev02，记录失败并补定点反例；CI 配置新增离线治理门禁及测量/反馈/来源测试选集 | 接入范围包括 18 类治理场景、30 cases、聚合器反例，以及任务测量、projection 缺项反馈、findings guidance、frozen product、工具正文测试；见第 7 节 | 远程 CI 未运行，分支保护未核验；真实模型、独立工程留出、PC01 和容器校准不在该自动门禁中。没有重复运行波动或每成功任务成本数据 |
| Self-RAG 质量反馈 | 已完成反思 token 的真实 GPU 校准训练与重载；首批真实 Critic **20 条标注、0 条入选**，修正后已准备 6 条反例校准 | 训练校准使用合成样本；Critic 原标注存在支持度误判，原件保留；见第 9 节 | 真实筛选数据训练、检索控制推理与独立质量对照仍在实施 |

上述“未测/不可填”保留为 unknown 或 N/A，不写成零成本、零故障或零提升。为什么要有它：未出现对应执行或没有完整分母，不等于已经观测到零。

## 2. 真实产品开发基线：B0 与 B1 均未交付

[B0 协议](../../artifacts/eval_driven_20260926/development_protocol.json)和[B1 协议](../../artifacts/eval_driven_20260926/development_candidate_protocol.json)绑定同一公开任务 `owned-config-max-retries-validation`、同一请求及目标源码起点。两者均为 `development`、`independent_holdout_eligible=false`，暴露状态为 `public_previously_used_and_inspected`。

模型配置为本地 `qwen3-coder:30b`，digest `06c1097efce0431c2045fe7b2e5108366e43bee1b4603a7aded8f21689e90bca`，上下文 32,768、最大输出 4,096；任务调用预算 12，worker turns 8、工具轮数 6、观察预算 32,768 bytes、provider timeout 180 秒。入口为自然语言 `run-request`；预批准目标是行为验证通过后等待精确 diff 批准，最终交付还需原 Apply/Build 路径。

| 观察 | B0 `dev01_b0` | B1 `dev01_b1` |
| --- | --- | --- |
| 候选变化 | 冻结的当前产品基线 | 缺失输入义务的结构化纠错提示；另加入保持代码身份的产品布局 oracle 适配 |
| 已记录模型阶段 | projection、projection correction | projection、correction、findings，以及两轮补查 query/findings |
| 已验证产品终态 | `domain_blocked`；`recorded_product_success=false` | `domain_blocked`；`recorded_product_success=false` |
| 终态阻断 | 需求覆盖不足，Planning 没有充分的当前正式覆盖 | 需求仍被判为缺失/未解决，覆盖不足 |
| 任务的 Apply / Build / Runtime / Evaluation | 均未到达 | 均未到达 |
| 可作何结论 | 基线失败已观测 | 候选进入更多证据判断步骤，但未完成需求，不能称修复成功 |

终态及用量以[B0 测量 v2](../../artifacts/eval_driven_20260926/dev01_b0_measurement_v2.json)、[B1 测量](../../artifacts/eval_driven_20260926/dev01_b1_measurement.json)为准；旧的 B0 测量文件保留，不覆盖。结果投影的 `completion`、`independent_task_count`、`task_total_*` 仍为 null，原因是只选择了明确的运行段，没有完整历史证明。这里确认的是两个选定运行的失败终态，不是给全任务或独立任务完成率补零。

B1 协议明确是开发工程增量，不是独立留出或整个任务的单因素因果实验。新增 oracle 未被这两个运行实际走到；它的组件验证不能提升 B1 的产品成功数。

准备阶段的[原始工程行为基线](../../artifacts/eval_driven_20260926/owned_config_baseline_verification.json)确认了 7 项预期需求失败及全部 8 项保留行为通过。这证明存在待修需求与可用裁判；不等于 Agent 已修复，也不等于任务 Build 已通过。

### 追加开发运行：dev02_trace

[dev02 准备 v2](../../artifacts/eval_driven_20260926/dev02_preparation_v2.json)选择此前已暴露的 `AccurateCrosshair` 配置任务：无保存配置时让 Follow Recoil 默认关闭，保留已有显式值、其他默认值与配置键。任务 ID 为 `accurate-crosshair-recoil-default-off`，同样 `development`、`independent_holdout_eligible=false`，使用相同 30b 模型名、32,768 上下文、12 次任务预算；验收要求完整工程编译与真实 BepInEx 配置读写，不要求游戏画面。

[执行收据](../../artifacts/eval_driven_20260926/dev02_execution.json)记录外层墙钟 **131.636 秒**、退出码 1、未超时；[选段测量](../../artifacts/eval_driven_20260926/dev02_measurement.json)记录 projection、findings、planning 共 3 条真实模型响应。最终阻断为 `EDIT_TARGET_NORMALIZATION_UNSAFE`：同一路径的重叠可编辑证据未共享完整且一致的源码/方法身份。该事实先作为新反例保留，不在本报告推断其根因或声称已修复。

运行 manifest 记录基线工程确实 Build 成功、退出码 0、有 DLL 哈希；任务修改后的 Patch/Apply/Build/Runtime/Evaluation 均未到达。执行收据的 `snapshot_root` 所指 `frozen-dev02/child_execution.json` 为 `status=verified`、`failures=[]`。**执行来源 verified、基线 Build 成功和需求交付成功是三件事；本次产品结果仍为 false。** dev02 是不同任务，不能与 B0/B1 作跨任务策略收益对照。

### 追加模板候选：dev01_b2

[模板独立审阅](../../artifacts/eval_driven_20260926/planning_template_review.json)确认两个规划所有者改为共用具体事实义务，保留自定义要求及原放行校验。[新协议](../../artifacts/eval_driven_20260926/dev01_b2_preparation_v2.json)从 dev02 已验证源码快照装配，仅覆盖三个模板文件；未包含正在开发的 Planning 纠正特性。原任务、模型、12 次调用预算和验收保持原配置。

[执行](../../artifacts/eval_driven_20260926/dev01_b2_execution.json)墙钟 96.689 秒、退出码 1；[测量](../../artifacts/eval_driven_20260926/dev01_b2_measurement.json)记录两次真实 projection 调用，输入 5,532、输出 983 Token，14 次源查询。初次输出把输入 5/6/7 同时计入 requirements 和 dispositions；纠错反馈只定位输入 5 并要求保留其他字段，模型只删除了该项 disposition，6/7 仍冲突。原始输出没有列出的 post-change 项由既有契约自动补齐，不是本次持续失败的缺项。未实际调用 Findings 或 Planning 模型，未进入 Patch。该候选的工程语义整理已验证，但本次没有表现出交付改善。

### 追加规划纠正候选：dev02_c1

[协议](../../artifacts/eval_driven_20260926/dev02_c1_preparation_v2.json)从 dev02 冻结源装配，只加入一次预算内目标纠正及 Planning 实际 HTTP 正文保存；没有加入新的证据模板。该版本经过[独立边界审阅](../../artifacts/eval_driven_20260926/planning_correction_review.json)。[实际运行](../../artifacts/eval_driven_20260926/dev02_c1_execution.json)耗时 143.735 秒、退出码 1；[测量](../../artifacts/eval_driven_20260926/dev02_c1_measurement.json)为 4 条生成、输入 17,356、输出 1,313 Token、8 次源查询。

新的纠正通路确实执行一次，但模型返回了与第一轮相同的两个 ID 和 rationale；原 normalizer 再次拒绝，Patch 未到达。这证明反馈与预算接线可执行，**没有证明目标选择或交付效果改善**，也不记作修复成功。相比该任务基线多一次模型调用；两次运行的墙钟没有经过重复/冷暖控制，不作延迟提升结论。

### 追加投影纠错候选：dev01_b3

[协议](../../artifacts/eval_driven_20260926/dev01_b3_preparation_v2.json)及[独立审阅](../../artifacts/eval_driven_20260926/projection_conflict_review.json)绑定了多冲突反馈及已审的追踪/规划接线。[真实执行](../../artifacts/eval_driven_20260926/dev01_b3_execution.json)为 111.719 秒、退出码 1；[测量](../../artifacts/eval_driven_20260926/dev01_b3_measurement.json)为两条生成、输入 7,236、输出 1,019 Token、14 次源查询。实际 HTTP 请求中已包含 5/6/7 三项冲突及组合修复规则，但模型仍返回未解决冲突的投影，原验证继续拒绝；Findings/Patch 均未调用。多冲突反馈的本地合同缺陷已修，**当前本地模型未因此完成该任务**，不将两次受控 callback 的通过记作真实模型通过。

## 3. 固定 RFC 语料的 RAG 实测

语料为 RFC 8259，1 PDF、16 页、39 chunks。题型为精确概念 2、语义改写 3、多证据 3、信息不足 2。配置冻结后完成 20 个 query/arm 对；hybrid 使用 BGE-M3 查询向量，实际记录 10 次 embedding 请求。随后在原来的 top-3 contexts 上，用 `qwen3-coder:30b` 生成 20 个回答；温度 0、输出上限 1,024、无自动重试，gold 未送入生成器。

证据入口：[题集 manifest](../../artifacts/eval_driven_20260926/rag_holdout/manifest.json)、[检索协议](../../artifacts/eval_driven_20260926/rag_holdout/retrieval_protocol.json)、[检索执行](../../artifacts/eval_driven_20260926/rag_holdout/retrieval_execution.json)、[回答协议](../../artifacts/eval_driven_20260926/rag_holdout/answer_protocol.json)、[回答执行](../../artifacts/eval_driven_20260926/rag_holdout/answer_execution.json)。回答客户端没有证明服务端实际 context window，不能把配置推测当成已核验值。

| 指标 | BM25 | Hybrid | 分母说明 |
| --- | ---: | ---: | --- |
| 宏平均 evidence-group Recall@3 | 81.25% | 68.75% | 8 个可答题各自算召回后等权平均 |
| 命中的必需证据组 | 8/11 | 7/11 | 微观组计数，不能直接当成上行宏平均 |
| 全部必需组命中的题 | 6/8 | 5/8 | 不包含 2 个信息不足题 |
| 精确概念题宏平均 Recall@3 | 100% | 100% | 每臂 2 题 |
| 语义改写题宏平均 Recall@3 | 100% | 66.67% | 每臂 3 题 |
| 多证据题宏平均 Recall@3 | 50% | 50% | 每臂 3 题 |
| AI 审阅引用正确 | 17/22，77.27% | 20/27，74.07% | 每次出现的 `[context:N]` 是一个引用单元 |
| AI 审阅严格正确拒答 | 1/2 | 1/2 | 仅 gold 标为信息不足的两题 |
| 可答题观察到的拒答 | 0/8 | 0/8 | 没有拒答不等于答对；另区分当前证据是否充分 |

召回原件见[Recall 报告](../../artifacts/eval_driven_20260926/rag_holdout/recall_report.json)；语义判定见[独立 AI 引用/拒答审阅](../../artifacts/eval_driven_20260926/rag_holdout/citation_refusal_review.json)。两种评分检验不同对象：Recall 按冻结 gold 的完整引文 chunk 替代集合计组命中，其他部分或等价片段不会自动计命中；语义审阅直接核对模型实际收到的文本。因此，未命中完整 gold 组不必然等于毫无可用信息。

49 个引用单元中，37 个正确、12 个错误、unknown 为 0；8 个回答有 9 组实质无引用覆盖缺口。独立语义审阅没有参与题目编写或回答生成，并在评分时未读 Recall 分数，但仍是 AI 判断，`human_verified=false`。其中有边界解释：承认 RFC 不足后仍给出题目所求的外部 draft/关键词，不算严格拒答；没有给出具体算法/规范化步骤的外部文档转介另记覆盖缺口。

典型失败包括：第 06 题两臂都把完整 JSON 根值错误限为对象或数组；第 08 题 BM25 遗漏 `application/json`；第 09 题两臂声明材料不足后仍补充外部 Schema 选择。正确的局部引用并不能使整答结论正确。

题集资格以[语义重合自审](../../artifacts/eval_driven_20260926/rag_holdout/eligibility_review.json)补充限定：作者未看检索分数，对新旧 query 的自审为 7 题目标区别明确、3 题部分重合（03、05、07），并非独立第三方或人工审核。合适的表述是“固定同源语料上新编、未用于本次调参的 10 道诊断题”，不是“10 道全量语义独立留出”。全部题目与原分母保留，没有删掉重合题重算更好分数。

平均查询耗时记录为 55.03 ms / 560.08 ms，但查询顺序固定为每题先 BM25 后 hybrid，包含冷启动/缓存差异；协议只允许描述耗时，不支持速度优越或 P95 改善结论。10 题、单一熟悉文档及 AI gold 也不足以证明普遍检索选型优势。

## 4. 治理、恢复及受限执行的证据层级

[治理矩阵 Run 02](../../artifacts/eval_driven_20260926/governance/run_02/summary.json)覆盖 18 类已知场景，30 个参数化 cases 通过。它们不是 30 个独立工程任务，也不是随机抽样攻击。

| 场景测量 | 观察值 | 执行边界 |
| --- | ---: | --- |
| 应拒绝边界错误放行 | 0/14 | Dry-run、Apply、Build 结果接纳、重放和内存预算等选定边界 |
| 重复副作用 | 0/5 | 各案例分别观察 Build callback、物理 Apply/产物或 resume report；不是同一种副作用的五次重复 |
| 支持的计划内续接 | 2/2 | 延迟批准及批准后 Apply→Build，编译为受控替身 |
| 持久记录读取恢复 | 1/1 | 同一进程重新打开 ArtifactStore，非真实进程崩溃 |
| 部分/未知写入报告 | 1/1 场景族，含 7 cases | 保留实际写入事实并阻断下游，不声称完成了恢复 |

生产执行器、Graph 和 ArtifactStore 在真实临时文件/持久产物上运行；模型回复和编译结果为确定性测试替身，个别传播测试使用内存 Store。[详细边界与测量修正](../../artifacts/eval_driven_20260926/governance/README.md)保留了各例差异。

Run 02 的 pytest 退出码为 0，但全源码快照中并行新增了任务测量模块及其测试，`version_binding_stable=false`，外层 runner 因此保守返回 1。已有文件哈希没有变化；静态检查支持新增文件不在所选执行路径上的推断，但没有运行期 import 捕获。因此不能把 Run 02 写成“整个工作区版本稳定、门禁全绿”。Run 01 及其较弱的 G13 副作用观察也仍保留。

随后单独完成了[PC01 真实进程退出场景](../../artifacts/eval_driven_20260926/governance/process_crash_01/README.md)：普通 `apply-patch --resume-approval` 已完成批准 diff 的物理替换和持久化后，在 CLI 返回前 `os._exit(73)`；新进程读取旧记录、拒绝重复批准，再沿原 checkpoint 到达受控 Build checkpoint。恢复 **1/1**，两进程共一次目标替换，重复替换 **0/1**。该分母不合并到旧 18 类矩阵。

[PC01 汇总](../../artifacts/eval_driven_20260926/governance/process_crash_01/summary.json)与副作用日志证明的是一个预注册的“持久化后响应丢失”点。真实进程、文件、Graph 与存储确实执行；模型/编译仍为受控输入，未验证写入途中崩溃、断电、并发、真实编译器或游戏。其首次外层命令在两个业务进程成功后遇到 Windows 长路径复制失败；[原打包失败](../../artifacts/eval_driven_20260926/governance/process_crash_01/packaging_failure_01.json)保留，后续只把同一 sandbox 归档为 ZIP 并校验，没有重跑业务过程。

独立评分所需的受限 C# worker 前提也已补齐：固定官方 Linux/amd64 镜像 digest `4da9dff9f77f86ae7380a41332b838118f25b96eb27c4ac776325b285a331be0`，SDK 7.0.401 / runtime 7.0.11，离线编译公开输入；运行只读装配产物、非 root、无网络、无 capabilities、禁止提权，固定时间/内存/进程和输出上限。运行文件留在临时内存目录，不返回主机或跨容器持久化。

初始公开校准验证了正常编译/运行、语法错误、异常退出、文件/网络边界、输出超限与超时；独立审阅又发现复制身份和停止异常回收两个 P2，修复后有 28 项纯检查及定点真实容器验证，最终[独立复审通过](../../artifacts/eval_driven_20260926/governance/restricted_csharp_review_02/review_resolution.json)。这些是受限执行组件证据，尚未构成真实未见工程题的受保护 judge 成功率；Linux 的工具链二进制身份也不能替换历史 Windows 校准身份。

## 5. 实际消耗与仍未知的成本

| 选定记录 | 原生 generation 记录 | 输入 Token | 输出 Token | `kind=tool` 观察 | 模型 span 耗时合计 |
| --- | ---: | ---: | ---: | ---: | ---: |
| B0 | 2 | 5,190 | 1,324 | 16 | 96.440 秒 |
| B1 | 7 | 32,464 | 3,580 | 12 | 249.628 秒 |
| dev02_trace（不同任务） | 3 | 11,295 | 1,112 | 8 | 102.187 秒 |
| dev01_b2 | 2 | 5,532 | 983 | 14 | 76.111 秒 |
| dev02_c1 | 4 | 17,356 | 1,313 | 8 | 110.070 秒 |
| dev01_b3 | 2 | 7,236 | 1,019 | 14 | 89.754 秒 |

六个选段共 20 条 live provider generation 记录。这里的模型计数来自去重的原生观察，不是预算预约次数，也不是独立抓包的 HTTP 计数；工具计数仅是记录为 `kind=tool` 的 `evidence.source_query`，不是全部 OS 操作。模型 span 相加不是端到端墙钟、全部工具耗时或纯 GPU 计算时间。dev02 的 131.636 秒是其外层命令墙钟，有明确命令边界，仍不构成完整任务历史或 P95。

B1 比 B0 走了更多模型阶段且仍未交付，因此不能把工具观察 16→12 写成资源优化，也不能把 Token 变化包装成效果代价已优化。完整历史、全部续接和任务开始/结束边界未证明；测量器保留 `task_total_input_tokens`、`task_total_output_tokens`、`task_total_tool_calls`、`task_elapsed_ms` 为 null。

RAG 回答传输记录中的已知消耗另列，不混入 Coding Agent 任务：

| RAG 臂 | 已记录回答请求 / HTTP 200 | prompt_tokens | completion_tokens | 返回的 cached_tokens |
| --- | ---: | ---: | ---: | ---: |
| BM25 | 10/10 | 8,615 | 2,147 | 858 |
| Hybrid | 10/10 | 8,583 | 1,855 | 3,501 |

这些数由 `answer_execution.json` 的 provider usage 逐条相加，未自行扣除 cached_tokens 或换算金额；dense 检索另记录 10 次 embedding 请求。题集结果不应根据这些单次冷/热缓存差异作资源优越归因。

本表未覆盖后续诊断探针、Codex 开发本身、人工时间、电力/硬件、镜像准备或所有重测开销。货币成本 unknown；单位成功任务成本 N/A，因为本次六个开发运行没有成功交付，且完整成本分母未建立。没有全任务 P95 或收益对照。为什么要有它：本地推理不等于零成本，失败阶段的局部用量不能替代完整交付成本。

开发诊断消耗也保留在[本地推理成本台账](../../artifacts/eval_driven_20260926/recorded_inference_cost_ledger.json)：该台账截至 dev01_b2：八组组件探针共 17 次请求尝试（一次超时的 usage 未知），另有 20 次 RAG 回答和当时 14 条产品生成记录。已知部分合计输入 130,700、输出 18,324 Token，另有 10 次 embedding 请求。该小计包含已拒绝的策略及首版 wire 探针的编写失误，不是全项目成本；超时调用没有按零成本处理。未经成功交付验证的提示、压缩、两阶段评估和字段顺序实验均不宣称收益。

## 6. 严格追踪重建：0/2

[重建审计](../../artifacts/eval_driven_20260926/reconstruction_audit.json)在审计前声明七项标准，检查两个明确的失败开发样本 B0/B1，完整满足为 **0/2**。

| 标准 | B0 | B1 | 解释 |
| --- | --- | --- | --- |
| 原始请求 | 已证实 | 已证实 | 原始字节及运行身份可核对 |
| 实际执行平台版本 | 缺失 | 缺失 | 有计划哈希与源码 ZIP，但没有把实际加载模块版本绑定到该次执行的收据 |
| 目标源码版本 | 已证实 | 已证实 | 可恢复并核对所记录快照 |
| 模型实际 I/O | 已证实 | 已证实 | 分别 2/2、7/7 条 generation 的请求、provider 请求、回复及身份可核对 |
| 工具完整 I/O | 缺失 | 缺失 | 16/12 次工具的完整参数和逐次返回正文未全部保存；仅哈希或合并材料不足 |
| 执行/验收边界 | 已证实 | 已证实 | 未到达的阶段有终态依据；基线 Build 与任务 Build 已区分 |
| Lineage | 已证实 | 已证实 | 选定 run/request/trace/artifact 身份一致 |

源码 ZIP 中的 B0 311 个、B1 315 个 Python 文件已核验，但[快照收据](../../artifacts/eval_driven_20260926/snapshot_capture.json)明确只覆盖源码归档，不证明全部环境或实际已加载版本。工具 query 文本有部分可恢复内容，仍不足以还原每次 `query/search_root/source_identity_query/max_items` 及完整 EvidencePack 输出；合并后的材料不能替代原观察。

新增失败样本 dev01_b2 的[独立审阅](../../artifacts/eval_driven_20260926/dev01_b2_reconstruction_review.json)为 **7/7 成立、完整重建 1/1**：核验 414 个冻结文件、2/2 模型完整 I/O、14/14 工具完整 I/O 及源码/配置/终态/谱系。Planning 在调用前拒绝，实际调用为 0，未伪造其 provider body；任务依然未交付。该结果是新增批次，不能改写 B0/B1 的 0/2 或 dev02 的 0/1，也不能据不同失败路径推断相同任务的重建率提升。

新增失败样本 dev02_c1 的[独立审阅](../../artifacts/eval_driven_20260926/dev02_c1_reconstruction_review.json)同样 **7/7 成立、完整重建 1/1**，包含 4/4 模型原文、8/8 工具原文；实际发送的父/child Planning body 与各自 provider hash 一致，父收据未改。它与 dev01_b2 是两个不同失败阶段的新增完整样本，各自版本与单样本分母保留，不作为大样本稳定重建率。

故障定位耗时仍为 null：审阅前已知道相关原因，没有基础日志 vs 完整 Trace 的盲化、平衡顺序计时。本次恢复或审阅完成速度不能填入定位时间改善。

后续补齐记录能力也不追认旧样本完整。为什么要有它：新版本能保存的内容，不能还原旧运行当时未保存的精确输入与输出。

新增 frozen execution 路径的[独立审阅结案](../../artifacts/eval_driven_20260926/frozen_execution_review/review_resolution.json)关闭了两个已复现 P1：未绑定的绝对 settings 输入在进入业务 CLI 前拒绝；项目发起的未绑定相对动态代码执行使来源状态转为 unknown，后者不是阻止动态代码执行的安全沙箱。dev02 的[独立重建审阅](../../artifacts/eval_driven_20260926/dev02_reconstruction_review.json)复用同一七项标准：413 个冻结文件、14 个目标源码文件、165 项依赖、8/8 工具完整 I/O 及谱系通过，模型 I/O 尚缺 Planning 的实际 HTTP body 原文。该独立新增样本仍不完整（0/1）；旧批次仍为 0/2，不覆盖原分母。

## 7. 已落地的开发反馈与检查范围

本轮使用真实 B0 失败形成 projection 缺项反馈反例，B1 再次走正常入口；结果保留为仍未交付。测量投影的 request 身份和 terminal hash 漏检也经反例修复，并有[独立复审](../../artifacts/eval_driven_20260926/governance/task_measurement_review_resolution.json)。受限 C# worker 的两个 P2 同样保留修前反例、修后检查与独立复审，没有通过放松判定取得通过。

[CI 接入收据](../../artifacts/eval_driven_20260926/governance/ci_gate_integration.json)记录新增 required offline governance step：治理聚合器反例及 18 类/30 cases 的场景入口；[后续选集扩展](../../artifacts/eval_driven_20260926/governance/ci_checkpoint_extension.json)曾记录任务测量、projection 缺项反馈和 findings guidance 三个测试文件；其中 findings guidance 因真实诊断无收益已撤回，其文件及 CI 项不在当前主线；[Trace 选集扩展](../../artifacts/eval_driven_20260926/trace_ci_extension.json)再加入 `test_frozen_product.py`、`test_source_query_local_bodies.py`。当前可声明的是“已接入 CI 配置并有本地检查”，不是“远程 CI 已通过”或“发布必经门禁已验证”：hosted CI 未运行、分支保护未核验，PC01、真实模型、独立工程题、真实 .NET fixture/容器校准尚未接入该门禁。

按[原论文](https://arxiv.org/abs/2310.11511)与[作者实现](https://github.com/AkariAsai/self-rag)，Self-RAG 的反思 token 需要进入训练及推理中的检索/生成控制；普通外部打分或 Patch Critic 不等于这条训练链。

Self-RAG 前提已进一步做[只读资产核验](../../artifacts/eval_driven_20260926/self_rag_readiness.json)：历史 Qwen3-1.7B 本地 HF 基座、训练 Python 环境、completion-only QLoRA、保存/重载逻辑可以复用。该次只读核验时训练与推理链尚未接通；后续完整权重校验、专属 token 训练与重载实测见第 9 节。旧 Patch LoRA 不计 Self-RAG。

仍待取得的核心证据是：有资格的独立工程任务完整交付、同完成条件下的效果/资源配对、足够重复的波动、完整版本与工具正文绑定、盲化定位计时，以及训练型 Self-RAG 的训练和对照链。它们不能由本轮的 49 个引用单元、30 个 pytest cases 或公开容器校准数代填。

本记录不修改活动产品契约、旧实验或任何原始评分。后续追加结果应注明新任务/版本、预注册分母和证据位置，并保持本轮失败与未知可追溯。为什么要有它：评测驱动开发需要累积可反驳的事实，而不是持续改写一段只有成功的项目叙述。

## 8. 交付与流程修复：2026-09-26—27

**已完成一个开发者辅助交付闭环。** AccurateCrosshair 的 `Configuration.cs` 仅将 Follow Recoil 默认值从 true 改为 false；原 Graph Proposal、Review、Dry-run、任务委托 Apply 和正式 Build 均执行成功。完整工程编译及五项真实 BepInEx 配置检查通过，保留显式 true/false、其他默认值及配置键。原 14 个输入文件未变；隔离工程、diff、DLL 和验收可由[closure3 回执](C:/Users/10160/.codex/visualizations/2026/09/26/01a0dbd6-eb58-7d82-aacc-86c6fdb8618e/e1/positive-control/closure3/closure-result.json)定位。

closure3 执行耗时 **26.279 秒**，新增产品模型调用 **0**；来源为 Astra 开发者提供补丁，授权来源为 task_delegation_policy。此前 closure1 的目标布局不符合域目录、closure2 的提交记录缺少原生 after_text 字段，均在 Apply 前停止，原始记录保留。26.279 秒只计 closure3 执行段。

前七次运行的阻塞可归到三个直接原因组：

| 运行 | 首个有效阻塞 | 已采取的修复 |
| --- | --- | --- |
| dev01_b0 / b1 / b2 / b3 | 覆盖投影缺项、重复归类；流程模板被当作必须先举证的用户义务 | 通用调查建议移出语义义务，保留用户要求；一次反馈完整冲突 |
| dev02_trace / c1 | 重叠源码窗口无法归一成合法修改范围 | 小文件供给完整源码与哈希，保留精确绑定检查 |
| dev02_c2 | Planning 继续要求配置与 API 证据 | 已配置行为验收时允许先选候选范围，问题随 Plan 进入 Patch |

后续 dev03_flow 仍在 Planning 请求依赖语义；dev04_draft 已进入 Patch，因同时发出两个 upstream 请求而硬失败；dev05_docs 已进入 Patch，再规划时因重复上下文超过调用前估算预算而停止。对应修复为绑定的依赖 XML 文档、可恢复的工具批次反馈、真实验收能力供给和上游 Plan 视图去重。原始选段用量见 [dev02_c2](../../artifacts/eval_driven_20260926/dev02_c2_measurement.json)、[dev03_flow](../../artifacts/eval_driven_20260926/dev03_flow_measurement.json)、[dev04_draft](../../artifacts/eval_driven_20260926/dev04_draft_measurement.json)、[dev05_docs](../../artifacts/eval_driven_20260926/dev05_docs_measurement.json)。

9 月 27 日修复了“不要求启动游戏”被关键词误判为运行时要求的问题：精确任务及混合正反句 28 项通过，直接调用者 44 项通过。上游去重对同一个 dev05 请求离线得到 **30,845 → 28,106 bytes**，完整源码、需求、验收、候选 IDs 与修改 span 保留，57 项聚焦及调用者检查通过；这是请求体体积测量，实际 Token 和交付效果待实跑。

`dev06_context` 随后进入 Patch，但两份候选均未实际改变代码，最后耗尽观察预算。直接原因包括同名定义被引用次数更多的调用方挤出检索窗口、重规划后重复读相同源码，以及无改动反馈再次携带整份代码。已修正单一标识符查询排序；全无改动反馈 **9,105 → 2,994 bytes**，重复提交按有效代码身份识别。原无改动拒绝、混合修改正文和权限检查保留；跨阶段重复读取仍可继续优化。[原运行用量](../../artifacts/eval_driven_20260926/dev06_context_measurement.json)为 11 次模型生成、53,379 输入和 4,891 输出 Token，墙钟 419.478 秒。

**`dev07_definition` 正常入口交付成功。** 同一原需求、模型和预算下，模型自行修改 `Configuration.cs` 的两个默认值表达式；五项配置验收通过，原精确 diff 经任务委托 Apply，正式 Build 产出 DLL。原输入工程、原 run manifest/result 保持不变，未启动游戏或部署。[交付回执](C:/Users/10160/.codex/visualizations/2026/09/26/01a0dbd6-eb58-7d82-aacc-86c6fdb8618e/e1/runs/dev07_definition/delivery/result.json)关联工程、补丁、DLL、验收与两段执行回执。

[dev07 用量](../../artifacts/eval_driven_20260926/dev07_definition_measurement.json)：**10 次模型生成、50,253 输入 / 2,376 输出 Token**；2 次源码检索、4 次源码读取、1 次上游请求。生成至保存审批点墙钟 **331.043 秒**；Apply/Build 续接 **3.991 秒、0 新增模型调用**。这些是两个执行段，段间开发者检查等待未合并成端到端耗时。该任务已参与调优；本轮取得一个可复查开发样本，尚无独立留出、重复波动、P95 或资源收益结论。

活动工作方式同时清理：AGENTS **13→8 条、6,795→3,769 bytes**；首轮阶段计划归档，当前入口 **10,798→1,588 bytes**；全局 Python 验证 skill **3,406→1,803 bytes**，取消固定追加检查和提前结束。QA 触发收窄，合法 FAIL/SKIP 笔记获接受，8 项检查通过。已备份移除 `.codex/hooks.json` 自动挂载；源码、修改范围和验收守卫保留在产品入口。回归选集新增需求否定、上游视图、同名检索、无改动反馈及任务委托测试；这是 CI 配置接入，远程 CI 尚未运行。

## 9. 当前入口与下一阶段实测前提：2026-09-27

**`dev08_entry` 使用公共 runner 完成当前版本交付。** 自然语言入口、模型补丁、五项配置验收、精确委托 Apply 和正式 Build 均完成；原 run result 保留审批点状态，交付回执另行关联。[批次结果](../../artifacts/eval_driven_20260926/dev08_entry_batch_result.json)记录 **351.560 秒、10 次模型生成、50,278 输入 / 2,598 输出 Token、9 个 native 工具观察**，交付续接 0 模型调用。这是同一已暴露需求的新版本运行，独立任务数没有增加；单个执行时长不用于声明稳定 P95。

检查入口时修复了一处实际断路：Patch 的补查请求原来共用初始 Findings 的规则，formal gap 为空就被 schema 禁止查询。现在 Patch 可按现有 requirement 调查新事实，初始 Findings 仍绑定真实 gap，读取范围和预算不变。共享查询合同移至 `evidence/reassessment_query_contract.py`；`defer_approval=True` 可省略未使用的批准读取器，实际 Apply 授权保持。原两项 CLI 路径、延期与非延期审批反例及直接调用者已验证；公共 runner 和通用交付 adapter 已经实际消费这些入口。

独立评测的真实执行桥已补齐。新通用 factory 将公开 C# worker、候选源码与 host 私有断言分开；[v2 控制结果](C:/Users/10160/.codex/visualizations/2026/09/26/01a0dbd6-eb58-7d82-aacc-86c6fdb8618e/e1/restricted-lease-controls-v2-20260927/controls-summary.json)中，原错误实现 **9/12**、两种入口的修复实现均 **12/12**，语法错误在编译阶段拒绝且未执行行为检查。16 个容器核验固定镜像、禁网、只读根文件系统并清理成功。这些为已暴露开发控制；catalog/transfer 首轮执行结果见第 10 节。验收 probe 程序集与原工程正式 Build 分开记录。

Self-RAG 已完成一次真实 GPU 校准训练：[训练记录](C:/Users/10160/.codex/visualizations/2026/09/26/01a0dbd6-eb58-7d82-aacc-86c6fdb8618e/e1/self-rag-public-calibration/train/result.json)。5 条明确标为合成的校准样本、5 个 optimizer steps，训练阶段 **9.092 秒**，峰值 CUDA allocated **4,561,190,912 bytes**；四类反思 token 对应行均变化，393 个保存参数与重载值精确一致（允许无损 dtype 转换），token IDs 重载一致。真实 Critic 标注、筛选、检索控制推理和独立质量对照仍在推进；这些校准样本不填独立质量样本数。

RAG 对原新编 10 题按已有语义判重结果筛出 **7 道 distinct 问题**，不按结果挑题。该[子集统计](../../artifacts/eval_driven_20260926/rag_holdout/distinct_subset_report.json)中，5 道可答题 Recall@3 宏平均为 BM25 **70%**、Hybrid **80%**，引用正确率分别 **9/13**、**13/16**，严格拒答均 **1/2**。范围仍是 1 份 RFC / 39 chunks，判重与引用评分为 AI 审阅，未经人工核验；原 10 题结果保留。该差异提示旧题重合和问题组成会影响检索结论，尚未据此改变默认策略。

`local_entry` 装配拆分已迁出 NuGet 构建实现至 `src/mod_agent/build/nuget.py`：7 个定义的 AST 与迁出前完全一致，旧导出和 `LocalEntryError` 类型兼容。FullProjectCompilation 与 worker 指纹同步绑定新实现文件；兼容、冷导入、构建命令、直接调用者和指纹漂移检查通过，独立审阅未发现本次迁移引入的阻断。此次验证未新增真实模型或 Build 运行；上面的 dev08 是迁移前交付记录。当前 `local_entry` 仍有 14,301 行，`run_local_request` 为 1,729 行、47 个参数。下一处明确耦合是下层验收与依赖文档模块为 GameFolder 绑定、快照和安全复制反向导入总入口；迁出该职责可以解除这些依赖，随后再收拢工程准备和模型装配。

Self-RAG 首批真实 Critic 标注已执行：20 次生成、23,996 输入 / 3,351 输出 Token，**20 条标注、0 条进入 Generator 训练集**，见[原始结果](C:/Users/10160/.codex/visualizations/2026/09/26/01a0dbd6-eb58-7d82-aacc-86c6fdb8618e/e1/self-rag-critic-01/execution/result.json)。独立审阅发现引文空白匹配过严、检索与支持度标签组合矛盾，以及把错误的 JSON 顶层类型结论判为 fully_supported。仅修正排版匹配会误收实质错误答案；下一版先用已暴露反例校准支持度与效用判断，保留本批全部原件。

## 10. 两道独立工程题首轮对照与格式门禁修复：2026-09-27

[首轮统计](C:/Users/10160/.codex/visualizations/2026/09/26/01a0dbd6-eb58-7d82-aacc-86c6fdb8618e/e1/independent-benchmark-20260927/primary-results.json)关联冻结协议、发布清单及四次实际运行。两题分别检验缓存状态一致性与批处理原子性，为同一 OwnedTraining C# 工程题集的两个变体；基线和候选在当前发布者读取题目前冻结，历史公开发布及本地暴露审查范围保留。原始请求/源码字节复核未变。

| 首次运行 | 基线 | 候选 |
| --- | --- | --- |
| Catalog | 规划无精确修改目标，未产补丁；81.747 秒 | 8/8 行为检查、精确委托 Apply、正式 Build；210.031 秒 |
| Transfer | 新增 6 行尾部空白，两次相同提交被拒；233.271 秒 | 新增 5 行尾部空白，两次相同提交被拒；237.139 秒 |

候选完成 **1/2**，基线 **0/2**。候选累计 **21 次生成、57,824 输入 / 5,857 输出 Token、24 个工具观察**；基线为 **13 次生成、34,930 / 3,563 Token、13 个工具观察**。候选每次成功交付的累计 Token 为 **63,681**，计入失败任务。完成质量不同，未据此声称资源节省。每臂 n=2 的经验 P95 等于最大值；机器同期承担开发工作，尚无稳定延迟分布。运行内人工介入和开发者改写模型补丁均为 0；成功交付续接新增模型调用为 0。

固定失败样本 cb1/tb1 的[独立重建审阅](C:/Users/10160/.codex/visualizations/2026/09/26/01a0dbd6-eb58-7d82-aacc-86c6fdb8618e/e1/independent-benchmark-20260927/reconstruction-round1.json)为 **2/2**，沿用七项标准，含 13 次模型与 13 个工具观察的真实输入输出；完整记录保留实际工具 dispatch 区别及终态快照字段缺失的核对依据。盲化定位耗时未执行。

已移除通用尾部空白硬拒，Dry-run/Apply 保留格式统计与原始补丁字节，源码前像、修改范围和批准哈希检查保持。3 个反例先失败，修复后 78 项相关检查通过，并经独立审阅；同题新的正常入口开发运行使用新目录，独立首轮结果保持不变。原协议重复轮已准备，尚未执行。

入口依赖准备也已迁至 `build/dependencies.py`：9 个定义行为保持，验收及依赖文档模块解除对总入口的反向导入；140 项相关检查与独立审阅通过。

## 11. 后续实测与纠错：2026-09-28

Transfer 的开发运行 td1/td2/td3 均未交付。去掉尾部空白硬拒后，候选进入真实行为验收，但仍只有原隐藏检查 4/8；补充公开反例后，公开检查为 0/4。测试参考修复在真实受限执行中为公开 4/4，原错误候选为 0/4。运行原件分别位于 e1/i2/r/td1、td2、td3；独立首轮 0/2→1/2 的分母与结果保持。

已修复上游模型猜想进入硬约束的接线。td2 的真实反馈还显示重复物化代码与相同期望占用预算；保持所有公开输入/实测/可还原预期，纠错累计字节由 36,339 降至 28,633，额度仍为 30,472。td2/td3 输入为 44,887/41,924 Token，工具观察均 14，调用均 12，耗时 290.524/284.276 秒；两次都失败，当前未声明成功交付的资源收益。下一处已定位的冗余是无新事实重查后仍调用 Findings/Planning，正在修复。

扩展 RAG 语料已真实入库：3 份 RFC、42 页、90 块，实际 ID/全文与预测绑定一致。14 道留出题中，11 道可答题的证据组 Recall@3 宏平均 BM25 59.1%、Hybrid 50.0%，微平均为 9/16、8/16；完整证据均 4/11。3 道不可答题的拒答尚未评分。原36条检索已执行，CustomEvaluator 不识别实际 RetrievalResult 的接线缺陷已修，18项检查通过，开发BM25正常CLI完成；原失败与[重算](../../artifacts/eval_driven_20260926/rag_multirfc_20260927/retrieval_rescored_02.json)均保留。

Self-RAG 的六条Critic校准原结果为0/6；独立核查发现host将完整Q8回答错标拒答、将Q6被选中的正确前提强制要求为矛盾。修订期望后复用原响应评分为1/6，没有新增模型调用或覆盖旧结果。真实训练数据经独立来源审阅，最终接受5条原模型回答，另保留5条明确标记的合成控制样本；100步训练、69.307秒、峰值CUDA allocated 4,730,301,952 bytes，参数/token重载验证通过。[训练原件](C:/Users/10160/.codex/visualizations/2026/09/26/01a0dbd6-eb58-7d82-aacc-86c6fdb8618e/e1/self-rag-reviewed-training-02/execution/train/result.json)明确标签来源为Codex辅助复核与合成控制，不称自动Critic成功或人工金标。独立推理环境缺少Chroma的问题已修复，既有训练依赖版本保持；三臂生成与质量统计已完成，见下表。

[可重算质量汇总](C:/Users/10160/.codex/visualizations/2026/09/26/01a0dbd6-eb58-7d82-aacc-86c6fdb8618e/e1/self-rag-independent-20260928/blind-review-01/quality-summary-01.json)对应14题、42份原始答案。两名Codex评审分别审查七题的三份匿名答案，每题一次来源辅助AI审阅；不是人工金标，也没有双标一致性数据。聚合逐份验证源答案哈希、上下文和审阅引文。

| 策略 | 无证据断言/可判定断言 | 完整回答 | 严格引用正确率 | 正确完整拒答/不可答题 | 模型调用 | 输入/输出Token | 整轮秒数 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 固定检索 | 10/37（27.0%） | 4/14 | 3/5 | 2/3 | 14 | 16,329/1,645 | 159.735 |
| 当前反思token微调 | 57/104（54.8%） | 1/14 | 3/18 | 0/3 | 28 | 10,537/3,168 | 425.387 |
| 本地外部Critic+一次修订 | 11/38（28.9%） | 5/14 | 1/5 | 2/3 | 42 | 59,239/6,046 | 802.409 |

“完整回答”包含对不可答题的合理拒答，微调臂的1/14即带事实说明的合理拒答。固定检索与外部Critic各一条歧义断言单列，未放入真假分母；微调臂另有1/3题在部分回答中作出合理拒答。平均效用分别2.64/1.86/2.93（满分5）；逐题最近秩P95分别23.506/61.974/84.393秒，n=14时为最大值。生成基座为Qwen3-1.7B，单轮、小训练集、AI审阅以及外部Critic与生成器共用GPU的限制保留。当前微调没有显示质量收益，外部Critic的新增调用未降低无证据断言率，不能填写为“下降”。各臂断言数量不同，以上为描述性对照，金额成本尚未测量。

本轮盲化定位试验[记录](C:/Users/10160/.codex/visualizations/2026/09/26/01a0dbd6-eb58-7d82-aacc-86c6fdb8618e/e1/independent-benchmark-20260927/localization-round1/timing-results.json)为3次超时、1次信息不足，按时正确的配对为0；不能填写定位提速。原计时存在共同派发、精确消息接收缺失及一个答案文件改写的限制，均保留。

新增的上游诊断权限、公开反馈隔离、反馈去重、真实检索类型和Critic期望反例已加入现有CI选集。一次本地等效执行为1293通过、47失败、2跳过，原日志保留在 `artifacts/eval_driven_20260928/ci_checkpoint_01/`。随后通过新显式预算夹具修复原32个缺预算失败，通过可选短目录夹具修复原7个路径长度失败，原断言保持；新增直接调用用例亦通过。全选集尚未重新运行，远程CI尚未执行。

td4 开发运行仍失败，墙钟229.261秒，真实模型响应11次、31,615输入/2,579输出Token。[首因核查](../../artifacts/eval_driven_20260928/transfer_evidence_reuse/td4-first-failure-analysis.json)发现剩1次额度时旧preflight固定要求Query+Findings两次，虽前三次复查均复用Findings，第四次仍在Query前停止。错误码通过冻结规则离线复现，原stdout已丢失，未伪称取回。已改为预检查即将执行的Query，实际需要Findings时仍检查共享总额度；runner开始保留失败stdout/stderr及退出原因。31项runner与22项预算/复查检查通过，真实模型尚未复跑。该修复不增加额度，最后一次Query后若需要Patch仍会正常停止；重复upstream请求的上下文闭合仍待修。三组回归文件加入同一CI检查，没有增加流水线。

按用户选择，Jev 先作[可行性评估](../JEV_FEASIBILITY_20260928.md)，不切换Self-RAG主线。尚未调用Jev或取得其项目内收益数据。

**结果判读与采用决定**：本轮Self-RAG微调明显退化，不进入产品默认路径；外部Critic尚未证明其额外调用值得，暂不推广；固定检索作为对照保留，质量仍待改进。当前先补齐评测能力和数据，后续Self-RAG实验优先核验训练筛选与推理接受判断的混用，以及具体标签、输入协议或反思决策失效，不无假设扩大训练。为什么要有它：评测结果要落实为采用、投入和下一项可验证假设，不能只留下负面数字与限制说明。

剩余旧夹具已按实际合同修正：阶段预算用例显式选择该可选策略，任务总预算用例保留默认行为；重复归类反例选用当前真实义务，不再依赖已删除的平台非目标序号。47文件的当前CI选集本地重跑 **1420通过、2跳过、0失败**，耗时272.273秒，前后源码哈希无漂移，见 `artifacts/eval_driven_20260928/ci_checkpoint_02/`。两个跳过为显式真实Docker选项，远程CI尚未执行。

Transfer续接的原生工具交换缺失已有正常CLI反例：两个补查完成后，后续模型请求中原先均没有对应upstream工具回复。现从已哈希绑定的真实响应恢复assistant调用并附上完成结果，保留旧源码观察；22项检查和独立审阅通过。td5按原任务、模型及12次额度运行，用于检验该上下文缺口是否造成重复补查；运行结果另行保留，不改变独立首轮计数。

**td5复验与下一步决定**：实际11次生成、53,979输入/3,504输出Token、13个工具观察、315.042秒，未交付。补查请求为1次，随后生成候选并完成三次真实行为验收；三份候选代码哈希完全相同，每次仍为私有4/8、公开0/4。终止点为反馈观察额度耗尽，直接的无效工作是反复提交与验收未改变的失败代码。保留原生工具闭合修复；下一步核查修订入口为何未识别这一重复，以及实际模型输入是否提供了可执行的差异反馈，暂不增加额度重试同一路径。[运行](../../artifacts/eval_driven_20260928/transfer_upstream_exchange/execution-result.json)与[诊断](../../artifacts/eval_driven_20260928/transfer_upstream_exchange/diagnosis.json)保留原件。为什么要有它：复验要区分已改善的流程与尚未改善的代码结果，预算耗尽不能遮住前面的无效修订。

后续已核对td5的真实provider请求：最后两次请求确实含有“代码与已失败版本完全相同”的提示及绑定反馈。缺少该提示这一解释已被排除；现有验证复用模块也存在，本裁判明确未声明可确定性复用。因此下一项开发验证应比较当前修订上下文与保留必要事实的精简上下文，区分供给方式与本地模型修订能力，不再增加同义提醒或直接放宽全局复用权限。独立 `continue-fresh-patch` 路径的旧测试schema和计费预期已修，11项通过，确认新增upstream回复189字节实际计费、旧工具记录保留且无Apply/Build/Runtime。

**扩展RAG回答评测完成**：正常 `scripts/evaluate.py --answer-mode generated` 入口完成开发8答与留出28答，共36份，33,787输入/6,023输出Token；本机服务日志时间窗对应36个chat和18个embedding成功响应，embedding Token未知。修复了生成器丢弃原生usage的记录缺口，87项相关检查通过；原问题、配置、金标、36组检索顺序及正文保持。Chroma的3个物理文件哈希变化原因未判明，全部90个ID与正文核对一致，不称物理索引字节冻结。[执行汇总](../../artifacts/eval_driven_20260926/rag_multirfc_20260927/answer_execution_summary_01.json)关联实际记录。

| 14题留出回答 | BM25 | Hybrid |
| --- | --- | --- |
| 正确的context引用/全部context引用 | 16/24（66.7%） | 11/20（55.0%） |
| 正确拒答/3道不可答题 | 3/3 | 3/3 |
| 所需证据组命中 | 9/16 | 8/16 |
| 完整取得所需证据/11道可答题 | 4/11 | 4/11 |
| 回答输入/输出Token | 13,293/2,312 | 13,508/2,575 |
| 本次整轮秒数 | 113.180 | 541.726 |

[语义评分汇总](../../artifacts/eval_driven_20260926/rag_multirfc_20260927/answer_quality_summary_01.json)按每次context引用计数，部分支持不计正确；精确可定位的chunk-ID变体保留，文献名称转述不双计。两名Codex评审各核查七题两答，策略名匿名展示，评审者参与过项目或制包，属于来源辅助AI评审，并非独立双盲或人工金标。正确拒答允许附有事实解释；缺引用与错误拒答分开。耗时含本机加载和同期开发资源竞争，不能把倍数当作纯策略速度差。

**RAG结果判读与采用决定**：继续保留BM25默认；本轮Hybrid增加嵌入调用，没有提高证据覆盖、引用正确率或拒答表现，暂不推广为默认。共同缺口是完整证据仅4/11，且“引用序号存在”仍会引用到不能支持断言的段落。后续优先区分漏取必要片段与生成器错引/过度概括，再做针对性补查或引用修订实验，不先扩大Dense投入。为什么要有它：方案选型要同时看支持证据、回答质量和实际成本，固定基线也需要继续修已观察到的失败。

**Self-RAG现有记录的进一步判读**：只读配对核实三臂14/14使用相同有序证据，外部Critic初始答案14/14与固定检索相同；其14次均拒绝并重写，原AI效用评分仅2题上升、12题不变。训练臂14/14均自评fully_supported，无法区分本轮57条无证据断言。由此将后续核验重点放在修订判定、标签区分能力与生成提示/输出协议/权重变化；材料不同这一解释已被本批数据排除。先完成当前测量，不新增无假设训练；保留[配对记录](C:/Users/10160/.codex/visualizations/2026/09/26/01a0dbd6-eb58-7d82-aacc-86c6fdb8618e/e1/self-rag-independent-20260928/existing_policy_diagnosis_01.json)。

**独立任务三轮重复已完成**：[重复汇总](C:/Users/10160/.codex/visualizations/2026/09/26/01a0dbd6-eb58-7d82-aacc-86c6fdb8618e/e1/independent-benchmark-20260927/repeat-results-03.json)覆盖原2道任务、每臂3轮、共12次真实运行。每臂实际平台指纹保持不变，同任务的源码、模型、权限、裁判和额度身份一致；没有把重复算成新的独立任务。

| 三轮结果/累计成本 | 冻结基线 | 冻结候选 |
| --- | --- | --- |
| 各轮成功数（每轮2题） | 0、0、0 | 1、0、0 |
| 成功运行/全部运行 | 0/6 | 1/6 |
| 各轮完成率均值/范围 | 0% / 0—0% | 16.7% / 0—50% |
| 首次行为验收失败后的修复成功 | 0/2 | 0/1 |
| 模型调用 | 58 | 56 |
| 输入/输出Token | 167,353/14,533 | 156,732/15,563 |
| 平均native工具观察 | 8.33 | 10.83 |
| 经验P95秒数（每臂n=6，等于最大值） | 233.271 | 242.318 |
| 含失败运行的每次成功交付Token | 无成功，未定义 | 172,295 |

行为修复分母来自实际裁判的behavior_failed；语法/格式提交失败另列，不混用。首轮独立主结果仍为0/2与1/2；后两轮均0/2，候选唯一成功来自Catalog首轮。**判读与采用决定：首轮差异未形成稳定交付改善，不能把50%写成平台稳定完成率或据此推广冻结候选。** 保留这批完整失败与波动，继续围绕已观察的规划阻断和无效修订做开发验证；新的调优效果需要新留出任务验证。为什么要有它：重复运行要能够推翻过强的首轮结论，而不是只报告最好的那一轮。

## 12. 资源对照、续接修复与测量补齐：2026-09-28

对同一已暴露的 AccurateCrosshair 配置需求进行三对真实运行，比较普通源码观察与“源码摘录去重＋已覆盖观察复用”组合策略。源码、模型、32K上下文、12次任务调用额度和五项配置验收一致，按 AB / BA / AB 交错执行。该试验只有一个开发任务，六次运行不增加独立任务数。

初次候选为0/3、基线3/3；[原运行](../../artifacts/eval_driven_20260928/context_resource_comparison/execution-result.json)定位到同Plan续接创建新worker时，丢失了真实响应提供的prompt-token校准。其34,001字节请求重新按“字节＋输出预算”估计为38,097，触发32K限制。现将纯校准数据按模型digest、端点与完整配置绑定传递，保留新transport与原额度。离线相同请求估计为21,284，随后真实入口复验候选3/3交付，校准丢失这一阻断已修复。

| 修复后的三对结果 | 普通观察 | 去重＋复用 |
| --- | --- | --- |
| 完整交付 | 3/3 | 3/3 |
| 输入Token合计 | 66,655 | 134,337 |
| 输出Token合计 | 5,464 | 6,219 |
| 模型调用合计 | 15 | 24 |
| 平均native工具观察 | 4 | 7 |
| 每次成功交付的输入＋输出Token | 24,039.67 | 46,852 |
| 经验P95秒数（每臂n=3，最大值） | 228.955 | 203.823 |

[完整运行](../../artifacts/eval_driven_20260928/context_resource_calibrated/execution-result.json)保留六次原始结果与交付引用；[独立核查与重算](../../artifacts/eval_driven_20260928/context_resource_calibrated/derived-results-01.json)校验113个原件引用。两组均完成相同补丁、5/5配置检查、精确委托Apply和正式Build；成功交付续接0新增模型调用。该runner启动时仍使用旧汇总公式，其原报告的 `tokens_per_successful_delivery` 仅含输入；当前聚合器已修复为输入＋输出，并保留缺失用量为未知，以上表按修正口径计算，未覆盖原报告。

**判读与处理**：续接校准修复保留；组合“优化”在交付质量相同的三对运行中使输入增加101.5%、总Token增加94.9%，没有证明资源收益。普通 `run-request` 默认关闭这两个开关，显式worker配置仍可用于实验。真实输入显示候选首批已获得完整源码，之后额外请求BepInEx默认绑定语义；因此不再笼统归因缺源码，后续如继续投入，应分别验证观察身份标记、工具说明与引用表示对补查选择的影响。低于基线的本轮耗时包含加载、缓存和机器竞争，不据此推广策略。为什么要有它：局部压缩字节不能替代端到端用量，质量不变却增加调用的默认策略应当回退。

**嵌入成本记录已接通**：OpenAI兼容embedding适配器将原生usage、实际输入哈希和耗时传入现有TraceContext及EvalRunner；缺失usage保留未知，不推算SDK内部HTTP重试。相同18题的新检索复验记录18次嵌入、639个原生输入Token（开发134、留出505）、0次回答生成；18组有序ID与正文和原记录一致。见[新复验](../../artifacts/eval_driven_20260928/embedding_usage_replay/result.json)。它补齐今后的成本采集，原36份回答实验缺失的嵌入用量仍按原样保留。

**测量回归**：续接校准、embedding用量和定位时钟三组测试加入原CI检查，选集由47增至50个文件；当前相关测量与正常CLI检查139通过，见 `artifacts/eval_driven_20260928/measurement_closure_checks.xml`。原47文件的1420通过、2跳过是前一检查点，未宣称新版50文件或远程CI已经全量运行。

**定位测量与处理**：复用原cb1/tb1两次失败、原因果评分标准和现有context-chain/失败journal导航；基础组与增强组均可读取相同完整原始材料，增强组额外获得导航。冻结执行、目录开放到首个最终回答的固定计时、每格6次调用/12次读取/180秒，顺序为cb1基础→增强、tb1增强→基础。这是本地Qwen诊断实验，使用已知开发失败及来源辅助AI评分。

[v4原结果](C:/Users/10160/.codex/visualizations/2026/09/26/01a0dbd6-eb58-7d82-aacc-86c6fdb8618e/e1/independent-benchmark-20260927/localization-ai-round1-v4/summary-01.json)没有正确配对，暴露模型把`/`当JSON根节点、工具返回含糊KeyError，以及模型格式/额度失败被笼统归为测量故障。已明确指针语义、增加可操作反馈，分别保留模型无效回答、额度失败和程序故障。原回答不覆盖，语义评分继续按原三项因果要求执行。

| 同预算v5复验 | 结果 | 实际秒数 | 输入/输出Token |
| --- | --- | --- | --- |
| cb1基础日志 | 最终JSON因512输出上限截断 | 96.666 | 13,409/1,311 |
| cb1追踪导航 | 只复述终态错误，缺少源码已检索→候选池为空→规划调用前拒绝的定位 | 46.127 | 11,564/802 |
| tb1追踪导航 | 读取额度耗尽，无最终诊断 | 69.166 | 19,456/1,151 |
| tb1基础日志 | 调用额度耗尽，无最终诊断 | 24.686 | 6,617/487 |

[v5评分](C:/Users/10160/.codex/visualizations/2026/09/26/01a0dbd6-eb58-7d82-aacc-86c6fdb8618e/e1/independent-benchmark-20260927/localization-ai-round1-v5/summary-01.json)为基础0/2、增强0/2，正确配对0；[实际成本和首因](C:/Users/10160/.codex/visualizations/2026/09/26/01a0dbd6-eb58-7d82-aacc-86c6fdb8618e/e1/independent-benchmark-20260927/localization-ai-round1-v5/cost-and-diagnosis-01.json)记录21次模型调用、51,046输入/3,751输出Token。表中为各格全部调用用量，512是单次输出上限。错误/无答耗时不计定位成功或P95收益。

**决定与后续处理**：当前没有定位提速依据，停止追加同配置跑分。读取工具原本要求模型显式填写已有默认值的指针、行号等参数，tb1基础组因此出现5次参数错误；现只要求material_id，其余按需填写。另修复参数错误在创建新读取前发生时可能误带旧read_id的问题；23项针对性检查通过，原v5未触发该旧ID路径。上述最后两项修改尚无新模型收益测量。下一步把开发重心放回Transfer无效修订；后续定位实验优先改善导航可用性与短答案协议，而不是扩大预算凑出速度差。为什么要有它：失败的测量要指出可处理的供给问题并调整投入，快速错误和反复跑分都不能充当定位能力。

## 13. Transfer失败诊断与正常入口复验：2026-09-28

再次核对td5真实请求，完整B0源码、受测候选、四个公开反例及重复代码警告均已送达；修订请求还包含旧格式错误候选、过时推测与重复反馈。复用原请求进行两次单轮诊断：原13消息请求仍要求读取源码；保留当前合同/源码/候选/全部最新观察的8消息视图改为再次请求upstream，未生成可验证修订。后续简明直接修复调用逐字复制已失败代码，不能据输入变短采用该方案。

让同一模型先诊断实际失败再生成，得到新的临时余额模拟实现。既有受限Docker实际编译及公开检查为**3/4**，链式信用、累计扣款回滚和余额溢出回滚通过，版本溢出因抛出错误异常类型而失败；再次直接反馈后，代码字节仍不变。共6次开发诊断调用、33,210输入/3,766输出Token、模型请求合计253.452秒；[汇总与原响应](../../artifacts/eval_driven_20260928/transfer_repair_context_probe/probe-summary.json)链接[真实公开验收](C:/Users/10160/.codex/visualizations/2026/09/26/01a0dbd6-eb58-7d82-aacc-86c6fdb8618e/e1/tp/dr1/result.json)。未提供参考实现或人工修改模型代码；这些阶段控制不填独立任务或产品交付分母。模型诊断中仍有错误的异常观察转述和算术说明，未被采纳为事实。

**处理决定**：实现可选 `diagnose_behavior_failures`，默认关闭。在真实行为失败且至少剩两次共享调用时，先诊断当前候选和全部实际反馈，再继续原Patch循环；诊断占用同一调用、上下文字节与provider上下文额度，无工具执行权，模型分析只作待验证假设。诊断正文超出剩余字节时保留原响应和成本，跳过正文继续原修订，不新增语义审批。为什么要有它：观测表格未促成改码，而诊断先行已产生可验证的部分改善，需要回到正常入口测收益和额外成本。

输入、共享预算、候选更新、禁止工具执行、源码漂移及调用者的**42项相关检查分批通过**。其中原重复代码夹具在读取Ck后再次插入marker，实际不再重复，已改为重复绑定候选正文并保留全部原断言。两组新检查与该调用者加入现有CI选集，目前53文件；未宣称新版选集已完整执行或远程CI通过。

正常入口双臂按[冻结协议](../../artifacts/eval_driven_20260928/transfer_diagnosis_product/protocol.json)执行：td6普通修订、td7启用诊断；同一需求、源码、模型、32K上下文、12次调用、32K观察字节、原私有8项与公开4项验收，仅诊断开关不同。两臂均从自然语言需求开始，未注入以上诊断候选。[最终结果](../../artifacts/eval_driven_20260928/transfer_diagnosis_product/execution-result.json)现已完成：均未交付，各自在三次行为检查中重复同一代码，止于`PATCH_BEHAVIOR_NO_PROGRESS`。诊断增加调用和Token，当前保持默认关闭，不继续同配置跑分；阶段3/4未转化为本轮产品交付。为什么要有它：原件已有终态就据此收口，不能让“已启动”叙述掩盖真实负结果或继续驱动无期限试验。
