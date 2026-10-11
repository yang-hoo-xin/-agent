# 已记录成果与验证范围

整理日期：2026-10-11。以下是开发过程中已记录原件的精选摘录；原始日志、模型输入输出和运行环境未全量公开。这些摘要便于阅读、对账和定位实现，不能独立证明全部质量，也不代表当前提交已重新执行全部实验。原件 SHA-256 用于后续核对字节身份，哈希本身不证明实验结论。

个人贡献口径为需求定义、架构与技术选型、验收设计，并结合 AI 编码工具推进实现。平台开发、产品本地模型生成的补丁和评测结果分别记录。

## 1. 服务化与受控负载测量

已实现 FastAPI HTTP API、独立 Worker、Redis 队列与租约、幂等提交、限流、缓存、超时和有界重试，并接入 Prometheus 与 Docker Compose。业务层复用现有查询服务和 Agent 正常入口；执行结果不明的 Agent 任务进入 `indeterminate`，不会自动重复执行。

实现入口：[HTTP API](../src/service_layer/api.py)、[Worker](../src/service_layer/worker.py)、[Redis Store](../src/service_layer/store.py)、[业务接线](../src/service_layer/backends.py)、[Compose](../deployment/service/compose.yaml)。公开验证代码：[HTTP 边界](../tests/unit/test_service_http_edges.py)、[Worker](../tests/unit/test_service_worker.py)、[真实 Redis](../tests/integration/test_service_job_store.py)、[故障联调](../scripts/service_load/runtime_faults.py)。

2026-10-09 的 Locust 测量使用 1 个 API、2 个 Worker，语料为 6 个源码文件、37 块、102,823 字节。实际执行 BM25 排序和 Chroma 正文读取；生成、查询改写、Dense 和 Rerank 均关闭，模型调用为 0。每个条件只执行一次，配置运行 60 秒，吞吐分母使用包含收尾的实际观察窗口。

| 条件 | 并发用户 | 完成的不同任务 / 发起操作 | 任务/秒 | 成功任务 P95 |
| --- | ---: | ---: | ---: | ---: |
| 不同查询 | 1 | 28/28 | 0.470 | 2.203 秒 |
| 不同查询 | 4 | 64/64 | 1.028 | 4.031 秒 |
| 不同查询 | 12 | 70/70 | 0.993 | 12.437 秒 |
| 重复查询缓存 | 4 | 62/62 | 0.998 | 4.375 秒 |
| 幂等重复提交 | 4 | 60/268 | 0.981 | 4.297 秒 |

P95 使用 nearest-rank，计时从提交至客户端观察终态，包含排队、子进程启动和轮询。完成数按不同 job 计数，202 响应和幂等重放不增加完成数。[公开数值摘录](evidence/service-load-20261009.json)包含五组原摘要 SHA-256、分母及更精确数值；计算入口为[汇总器](../scripts/service_load/summarize.py)和[负载脚本](../scripts/service_load/locustfile.py)。

缓存组有 56 次命中、6 次未命中，但查询分布与不同查询组不等同，未证明缓存带来端到端提速。12 并发吞吐没有增加，P95 升至 12.437 秒。幂等组达到固定 120 次 POST/分钟限额：328 次 POST 中有 60 次创建、60 次重放、208 次 429；POST 拒绝率为 63.415%，操作拒绝率为 208/268，即 77.612%。该组原 Locust 退出码为 1。

同日真实故障联调的 11 项检查通过，覆盖 Redis 中断时返回 503、恢复后原 Worker 继续执行、实际终止持有任务的 Worker 后由另一 Worker 在租约到期后完成第二次尝试、短预算超时和最终队列恢复。失租首尝试成本仍未知。

这些结果属于单一受信操作者、本机小语料纯检索服务；未测 LLM/完整 Agent 吞吐、多租户隔离、长期稳定性或生产容量，各条件也没有重复测量的波动估计。

## 2. 真实 Agent HTTP 入口

2026-10-09 的一次新任务经 HTTP、正常路由和 LangGraph 运行，执行 179.085 秒、排队 0.136 秒。Qwen3-coder:30b、32K 上下文实际完成 1 次路由和 7 次产品模型调用，共 19,748 输入、2,092 输出 Token；其中 4,680 缓存输入 Token 已包含在输入数内。

候选真实编译通过，5 个独立冷加载进程的 15/15 行为断言通过；领域终态为 `awaiting_approval`，未 Apply、未正式交付、未启动游戏。终态幂等重放返回同一 job，未再次执行。首轮因准备依赖缺失而在产品图前阻断的记录保留，此次属于修复环境后的新运行。

这证明服务入口已接通实际模型与受控验收，不能计入自主交付率。Compose 默认演示检索；本次 Windows/.NET Agent 使用同一服务模块的 Windows 进程，未证明该 Agent 工程可在 Linux 镜像中运行。

## 3. 模块评测驱动修复

2026-10-07 的模块 EDD 记录覆盖 13 个模块、140 个预定义场景，执行 224 个不同工程用例，共 282 次用例执行。最新结果为 222 个通过、2 个因训练依赖问题未解决；三批全部执行记录合计 253 次通过、29 次失败，首次失败保留。

该轮确认并修复两类缺陷：预算配置/用量接受非有限浮点数，以及经验提取未贯通编译 DLL、正式验收和原始 request/stdout 的字节身份。新增 46 个产品回归用例、7 个测量保护用例，复用 171 个已有用例；修复后受影响的 58 项检查通过。

实现与检查：[评测 runner](../scripts/run_module_evaluation.py)、[场景清单](../tests/fixtures/evaluation/module_coverage_v1.json)、[预算校验](../src/mod_agent/performance/budget.py)、[预算反例](../tests/unit/test_module_budget_finiteness.py)、[经验提取](../src/mod_agent/planning/member_repair_learning.py)、[证据绑定反例](../tests/unit/test_member_repair_artifact_binding.py)、[测量保护](../tests/unit/test_module_evaluation_measurement.py)。

224 是工程用例数，282 包含复验，不是用户任务数或自主交付数。部分路径使用模型/编译替身；该轮真实产品模型调用和新增 Mod 交付均为 0，新增 CI 选集没有远端执行记录。

## 4. SpreadAPI 受控代码交付

2026-09-30，已暴露的 C# Mod 开发题完成自然语言入口、源码调查、规划、产品模型补丁、worker 验收、精确绑定的任务委托 Apply 和正式 Build。需求涉及非法数值输入的原子拒绝及状态/回调行为保留。

原版本为 53/87 检查通过，其中正常行为 15/15；候选与最终 DLL 均通过 9 个独立进程、60 个动作、87/87 检查。修改仅涉及 `API/SpreadAPI.cs`，另外 13 个源码文件及原输入工程保持不变。成功尝试包含 6 次产品调用和 1 次路由，共 31,249 Token；此前失败尝试的 42,660 Token 和原始失败记录分别保留。

公开验收实现：[Evaluator](../src/mod_agent/domain/spread_api_evaluator.py)、[受控输入与原子性场景](../tests/fixtures/evaluation/spread_api_input_atomicity.json)、[Evaluator 检查](../tests/unit/test_spread_api_evaluator.py)、[DLL 探针](../scripts/spread_api_probe/Program.cs)。

验收由开发者配置，执行完整 DLL 的冷加载和实际 Harmony 计数，但跳过游戏回调主体，未执行游戏实机或部署。这是开发题受控交付，独立任务增量为 0；前后开发迭代不构成单因素因果对照，也未证明其他工程的稳定交付率。

## 原件身份与公开范围

下列是未全量发布的本地保留摘要的 SHA-256；五组负载摘要身份已列在公开 JSON 内。当前公开代码可用于理解机制和自行验证，复跑会产生新的运行条件与结果。

| 原摘要标识 | SHA-256 |
| --- | --- |
| Agent HTTP assessment，2026-10-09 | `4284187fcba3e4e935951370ab8e2041d89462c9956c6367b15decfd3d13b0e5` |
| Service fault assessment v2，2026-10-09 | `d628f09b5436ff0ef4b9b331666436d5fc49bbc4904676197d1cafafb09b6cea` |
| Module EDD result，2026-10-07 | `1a531b7371bf5dbb3ddab5d42e835445056f9e5097f290f766b290293966ca7b` |
| SpreadAPI result，2026-09-30 | `d902827de35b936397efb0b9b2dce6fc31c0328a8f7fc84bb7564c9d167044b1` |

本页及数值摘录未包含本机绝对路径、个人联系方式、凭据、完整用户/模型输入或游戏二进制。最新十题、开发者辅助实机修复与上述产品模型结果没有合并为一个成功率；当前未给出“优于 Codex”“整体交付率提升”或“生产可用”的结论。
