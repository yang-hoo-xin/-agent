# 评测驱动开发：已有模块、接线与复用代价检查

日期：2026-09-26。范围：当前工作区源码、调用者、相关测试设计、历史评测聚合记录、只读入口验证。没有实现新评测器、修改产品代码或运行新模型。

## 1. 结论与对初版计划的修正

仓库不是缺少评测基础设施，而是存在多个不同验收边界的闭环：文档 RAG、给定 Plan 的 Patch/Repair、正常产品 Graph、审批后交付、独立任务校准。可复用的执行、裁判、记录和比较模块已相当多，但它们的输入、身份和成功定义并不一致。

前一轮仅查看 `independent_product_adapter.py`，不足以推断真实评测执行器缺失。实际已有 `run_patch_sft_eval.execute_prepared` 的真实 provider/行为裁判链；正常 `run-request` 也已支持通过 `PatchWorkerConfiguration` 注入行为验收。缺口应改写为：**独立双臂实测的执行装配、跨任务/续接的指标投影，以及统一的实验资格与分母**，而不是“从零搭真实执行框架”。

初版“两题→固定 12 题”和“先补适配器”的顺序降为候选。先根据已有验收和记录接缝选最小闭环，再决定任务规模与要补的代码。为什么要有它：先定数量/架构再找能力，容易重复建设，也可能强迫不适配的旧合同服务新场景。

## 2. 检查方法与证据强度

| 检查 | 实际结果 | 证明范围 |
| --- | --- | --- |
| `src`、`scripts`、`tests/unit` Python 静态扫描 | 588 个文件 AST 解析成功，0 语法解析失败；50 个选定模块记录字节哈希、顶层定义与定位；[清单](evaluation_reuse_20260926/source_inventory.json) | 导航与限定名称调用点；不是 588 文件逐行审查，也不证明动态调用可达或行为正确 |
| 冷进程入口检查 | 仓库 `.venv` Python 3.10.20；8 个模块 `--help` 均 exit 0；[记录](evaluation_reuse_20260926/entry_checks.json) | 当前工作区导入和参数解析可用；没有真实 provider、编译器或行为测试 |
| 真实历史 Trace 只读投影 | 原 run + 指定 continuation 均被现有 `inspect_context_chain` 读出；4 份 manifest/result 前后哈希不变；[记录](evaluation_reuse_20260926/trace_reuse_probe.json) | 旧记录查询接线确实可运行，不是仅发现函数；只覆盖选中的两个 segment |
| RAG 原始文件复核 | 初始两臂请求计数/耗时，扩展四臂报告与 journal 哈希核对；[记录](evaluation_reuse_20260926/rag_history_checks.json) | 历史计数/身份复核；没有重跑模型、重标答案或重新证明 holdout 独立性 |
| 相关测试阅读 | 检查了公开产品双臂、独立裁判、Trace、审批漂移、恢复 ledger 和预算测试的使用方式 | 测试设计可定位边界；本轮未执行这些测试，不能宣称其当前通过 |
| 文档收尾检查 | 3 份新 Markdown 的 58 个本地链接全部存在；50 份已记录源码哈希未漂移；三个活动导航文件的 `git diff --check` 通过 | 只验证本次文档引用和检查对象稳定，不宣称全仓测试或 CI 通过 |

本次没有读取冻结 playbook，也没有执行历史实验目录里的 runner；历史资料只作资产定位。静态扫描中的“只有测试调用”限定于扫描范围和解析方式，回调、动态 factory、别名调用另查入口。为什么要有它：例如 `product_trace.py` 将 `inspect_context_chain` 赋给 `inspect` 后调用，不能因直接名称调用扫描未命中而误判没有产品入口。

## 3. 已核对的调用链

```text
正常产品路径
  cli.run-request -> local_entry.run_local_request
    -> RequestPatchExecution -> 共享 Patch worker
      -> PatchWorkerConfiguration.behavior_evaluator（可选工厂）
        -> CompleteCrosshairVerification / 当前 Plan 裁判
    -> 原 Graph Review/Dry-run/审批/Apply/Build/Runtime 与 Eval
  DSH deliver -> resume_deferred_approval -> 原 checkpoint/Build -> 交付收据

给定 Plan 的真实评测路径
  prepare_patch_eval_suite -> patch_task_suite -> continue-fresh-patch
  run_patch_sft_eval.execute_prepared
    -> LocalOllamaInitialPatchAdapter 或 run_external_patch_continuation
    -> OwnedSftOracle -> 原 worker 修订/原 Review 与无写入 Dry-run
    -> attempt journal -> compare_patch_trials（单任务、写入前范围）

独立对照准备路径
  independent_release -> 两臂同源文件准备
  independent_product_adapter -> 真实 parser/Graph + 受控响应与受控编译
  invoke_protected_judge -> 注入 callable 的收据校验
  尚未从这些模块中找到完整真实双臂执行及受保护裁判进程装配

可复用观察路径
  upstream_model_trace / patch_execution_trace -> run manifest / journal
  TraceService -> product_trace --context-chain -> 分 segment 记录与用量
  memory_comparison -> 冻结 on/off 输入；汇总函数仍由调用者提供结果行
```

这些是源码接线图；只有第 2 节的只读操作在本轮执行。为什么要有它：不能把图上有一条边当成该边已完成真实任务验收。

## 4. 可复用资产清单

| 资产与定位 | 当前接线与限制 | 复用候选及代价依据 |
| --- | --- | --- |
| [Patch 任务套件](../../src/mod_agent/evaluation/patch_task_suite.py)，`_checked_suite`、`task_cli_arguments` | 真实 CLI 可执行；套件限制 3–5 题、特定 Mod、已有 Feature/Evidence/Plan；原配置/API题写在源码中，已经暴露 | 适合阶段回归和模型资格实验；不直接当自然语言 E2E 或新 holdout。硬扩通用套件会触及任务合同与既有调用者 |
| [模型实验准备](../../src/observability/evaluation/patch_model_experiment.py)，`prepare_patch_model_experiment` | CLI 已接，冻结 split、profile、输入和暴露；`comparison_axis` 限定只换模型身份 | 复用身份/暴露/单元选择机制；策略对照不能仅改 arm 名，需新的最小实验描述或显式版本扩展 |
| [真实 SFT/Patch 评测执行](../../scripts/run_patch_sft_eval.py)，`execute_prepared` | 本地与 external provider 分支、真实行为验收、失败修订、Token/耗时摘要已存在；明确 `given_operator_Plan_not_natural_language_to_Runtime` | 可用于 Patch/Repair 验收，不必重写模型 runner；扩成完整 E2E 会改变起点和分母，直接复用正常产品入口更合适 |
| [OwnedSftOracle](../../scripts/run_patch_sft_eval.py)、[C# 数据准备/执行](../../scripts/prepare_patch_sft_data.py) | 已有编译、行为矩阵、保留行为与版本绑定；配置需要对应 task/manifest | 可复用独立 C# 裁判实现；新任务仍需编写验收，不能把 Python AST 校准题等价成真实 Python 项目交付 |
| [组合验收](../../src/mod_agent/domain/complete_crosshair_verification.py)、[当前 Plan 裁判](../../src/mod_agent/domain/accurate_crosshair_eval.py) | `CompleteCrosshairVerification` 已组合完整编译/真实配置/可选行为矩阵；工厂经 `factory_ref/factory_name/kwargs` 加载；不证明 Runtime | 现有 Crosshair 配置任务最有利于验证接缝；复用组合者比再做一套 Build/配置 runner 少触及 owner。其他语言不可直接套用 |
| [正常入口](../../src/mod_agent/local_entry.py)第 8149 行附近、[共享执行](../../src/mod_agent/request_patch_execution.py) | 正常 `run-request` 将可选 `behavior_evaluator` 传入共享 worker，并保留原 Graph 主责 | “正常入口不能接验收”是不准确的；优先验证具体配置和动态 factory，不先添加第二入口 |
| [单任务对照](../../src/mod_agent/evaluation/patch_trial_comparison.py) | CLI 已接；核 journal、live response、源码/worker/裁判；`task_denominator=1`，拒绝 product-source writes | 有价值的 Patch 事实校验器；不能简单放宽 no-write 条件后拿来判已 Apply 的交付，宜在外层另做 E2E 结果投影 |
| [独立 release](../../src/mod_agent/evaluation/independent_release.py) | 两臂源码物化可用；明确 `strategy_execution=not_run`；protected judge 需要外部 callable | 复用无答案材料与聚合收据；受保护进程身份字段不是已部署隔离服务，仍须单独检验装配 |
| [独立产品双臂](../../src/mod_agent/evaluation/independent_product_adapter.py) | 唯一直接调用者在测试；simple arm 是传入 submission 的 controlled worker，完整 Graph 臂也注入受控运行；`live_comparison_admitted=False` | 保留为工程接线测试。真实对照宜复用其输入/结果协议与原产品入口，是否新增薄装配优于改造此文件需接缝验证 |
| [记忆对照](../../src/mod_agent/evaluation/memory_comparison.py)、[Planning 消费](../../src/mod_agent/planning/model_selection.py) | Planning 已检索并组装 memory；对照脚本只准备/校验，`summarize_memory_outcomes` 的直接调用者为单测 | 不必重做记忆系统；缺实际运行结果行和统计入口。其“有 unknown 则成功率 null”与草案全分母完成比例不同，需保留原语义另行映射 |
| [Trace/context chain](../../src/mod_agent/evaluation/context_chain.py)、[执行索引](../../src/observability/patch_execution_index.py) | CLI 与服务已接；能聚合已选 generation；代码明确 `money=unknown`、耗时是 model span 之和 | 可直接复用记录读取与身份核验；仍需覆盖全部 continuation、去重、工具耗时/人工等待/价格。不能把片段总数当全任务成本 |
| [恢复/审批](../../src/mod_agent/workflow/checkpointing.py)、[审批后续接](../../src/mod_agent/reviewed_patch_continuation.py)、[DSH 交付](../../scripts/dsh_deliver_run.py) | 已有持久 checkpoint、resume report、漂移检查和交付入口；相关测试检查写回成功后才标 consumed | 适合直接做限定故障注入。没有据此证明任意进程崩溃/并发操作 exactly-once；先找真实边界，不承诺全 8 类已支持 |
| [执行 Eval Gate](../../src/mod_agent/evaluation/gate.py)、[质量策略](../../src/mod_agent/evaluation/quality_policy.py) | Graph 第 5610 行附近实际调用 Gate；外部 evaluation_context 按配置提供 | 不必新建全部门禁；复用产品 claim 边界，但工程 CI 尚未自动运行真实独立任务验收 |
| [文档 RAG](../../scripts/evaluate.py)、[EvalRunner](../../src/observability/evaluation/eval_runner.py)、[Langfuse 导出](../../src/observability/evaluation/langfuse_report.py) | 有真实回答/判分与历史运行；源码与代码导航评测是不同路径 | 直接复用报表与观察状态；Code Agent 成功率需要不同判定，不能强行统一成 Ragas 分数 |
| [实际 rg 基线](../../src/mod_agent/evaluation/arm_a.py)、[Hidden Golden](../../src/mod_agent/evaluation/hidden_golden.py) | 前者有 live rg/read、语料身份与 attestation，后者评已提交的 Evidence 与关系真值；不是模型端到端交付 | 可测检索/证据决策，不需要重新写 Recall 评分框架；使用前仍核暴露与适用任务 |
| [观察复用](../../src/mod_agent/proposal/patch_agent_loop.py) | `reuse_covered_source_observations`、去重及 read accounting 已在正常入口默认 policy 使用 | 可选为资源消融因素；应切换现有 policy 并核预算单位，不先“实现”已存在的优化 |
| [训练](../../scripts/run_patch_sft_training.py)与[ProposalCritic](../../src/mod_agent/proposal/critic.py) | SFT 有 completion-only mask、保存/重载校验；ProposalCritic 是提案评估边界；未发现完整 Self-RAG Critic→筛选→反思 token 训练链 | 可复用训练/校验工具，不能将已有 Patch 训练改名 Self-RAG；新语义数据链的成本远高于接一个指标 |

## 5. 历史目录里挖出的可复用内容

[扩展 RAG 目录](../../artifacts/rag_expansion_20260922/expansion_comparison_summary.json)除了报告，还保存 `bounded_http_runner.py` 和 `selective_router_v1.py`。前者封装请求预算和 transport journal；后者把 RFC 语料、BM25 索引、top-k 固定为特定身份，当前 `route()` 始终返回 BM25，理由是开发题未验证 Dense 增益。它不是已经实现的通用按问题类型路由。

这两个历史脚本可作为抽取请求记账或路由输入合同的参考，但不直接搬入生产。为什么要有它：保留历史原件的可复现性，且一次实验的固定条件不应成为通用产品默认行为。

初始 10 题两臂的 transport `request` 事件分别 110/120；报告耗时为 1,076,203/1,261,656 ms，按相对 Dense 基线计算低 14.699%。BM25 为 `partial`，其中 citation_measurement 是 9 observed / 1 failed_to_measure；Dense 为 complete。扩展开发 6 题和替换留出 4 题的四份报告及四份 transport 均与 summary 哈希一致，请求数 66/72/44/48，共 230。原始报告链接及哈希集中在[复核记录](evaluation_reuse_20260926/rag_history_checks.json)。

这说明“20 道诊断题已有比较资料”有原件支撑，下一步应先复用和解释已有资料，而不是重新做同样 20 题。耗时只说明该整轮评测，包含回答/judge 等调用；留出题已完成验收，不再是下一候选的未见任务。为什么要有它：历史成果值得复用，但不能扩大效果范围或重复消费独立性。

真实 Trace 探针读出 original 的 2 条 generation（输入 7,008、输出 1,978 Token）及所选 continuation 的 2 条（输入 14,920、输出 808）。这些是已选记录的局部用量，金额仍 unknown，耗时为模型 span 之和，其他续接未自动包括。这里不把四条记录相加宣称全任务成本；详见[探针记录](evaluation_reuse_20260926/trace_reuse_probe.json)。

## 6. 复用与新做的代价比较

这里评估的是相对改动范围，不是已测工时；没有把“存在模块”当作复用一定更快的结论。

| 待解决问题 | 复用方案的主要成本 | 新做方案的主要成本 | 当前候选 |
| --- | --- | --- | --- |
| 读取真实记录/用量 | Trace 已验证可读取；需全续接选择、字段映射和缺失覆盖 | 重建 I/O 捕获、身份校验、存储与查询，涉及多个核心 owner | 优先复用读取链，新增最薄的实验投影；接缝风险相对小 |
| 跨任务 E2E 统计 | 旧 Patch comparator 的单题、给定 Plan、no-write 合同与交付范围不兼容 | 一个只读结果汇总层只消费已有事实，但要定义任务/运行/续接身份与分母 | 可能“保留旧校验器 + 新薄汇总”比扩旧 comparator 更省，不新建执行框架 |
| 真实双臂执行 | controlled adapter 带假响应、预设 submission、1–5 调用约束及到批准前的语义 | 新薄装配可直接调用已存在的真实入口，但需处理相同输入、预算与裁判隔离 | 比较改造与新增薄装配；尚未选定，更不能把 controlled 分支直接切 live |
| 已有 C# 任务验收 | 现有组合 verifier 和当前 Plan 身份校验可复用；需核依赖、工厂 kwargs 和任务范围 | 重写编译、配置、行为与反馈很容易复制已解决的问题 | 对匹配任务优先旧组件；先做一个无模型配置/收据兼容性检查 |
| 多项目/多语言 | 核心 worker 可复用，domain 裁判未必适配 | 新领域 harness 需要真实任务、工具链及保留行为，但无需替换 Graph | 等覆盖目标明确再新增领域适配，不为了技术栈数字扩建 |
| 故障注入 | 复用现有 resume/approval/ledger 测试与入口；补真实进程时点观察 | 通用故障平台涉及进程控制、隔离和大量状态空间 | 先补具体缺失案例；是否需要通用设施由重复需求证明 |

每个实施候选先做一个有界接缝探针：同一输入、同一输出义务，记录需改的模块/合同/直接调用者、运行依赖和实际验证耗时；若复用需要修改公共成功定义或复制控制面，则重新比较薄适配和新模块。为什么要有它：复用节省的代码量不等于节省的集成与回归成本，未经探针不能诚实承诺工时。

## 7. 下一步建议及保留未知

建议先用已存在的真实 run 做一个**只读的实验结果行映射**：复用 Trace/执行索引/交付收据，逐字段列出能够提供的身份、阶段判定、Token、人工干预和缺失值，检查是否能完整覆盖选中任务的续接。再选择已有 verifier 能验收的一项真实开发任务验证正常入口，不先定必须两题或新建多少模块。为什么要有它：这是核实统一口径能否落在现有数据上的最短路径，也能直接决定该扩展旧模块还是增加薄汇总。

仍未知：真实双臂独立裁判进程的可运行配置、所有历史续接的全链用量覆盖、通用进程崩溃恢复范围、新项目的真实行为验收成本、Self-RAG 训练收益。本轮没有将任何未知项判成“完全未实现”，也没有用源码存在判成“已经交付”。
