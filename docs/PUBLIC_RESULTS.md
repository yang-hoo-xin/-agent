# RepoForge 实测报告

整理日期：2026-10-11 · [文档入口](README.md) · [项目首页](../README.md)

## 1. 摘要

RepoForge 已贯通自然语言需求、源码调查、模型补丁、受控验收和授权交付，并将查询服务与 Agent 正常入口接入 HTTP 异步任务层。以下记录展示服务能力、真实模型接入、工程评测和代码交付的实测结果。

| 验证方向 | 结果 | 对应范围 |
| --- | --- | --- |
| 异步检索服务 | 4 并发下 64/64 任务完成，1.028 任务/秒，P95 4.031 秒；11 项真实故障检查通过 | 1 个 API、2 个 Worker，小语料 BM25 检索 |
| Agent HTTP 入口 | 真实模型候选编译通过，15/15 行为断言通过 | 正常路由与 LangGraph 执行至 `awaiting_approval` |
| 模块 EDD | 覆盖 13 个模块、224 个不同工程用例，修复 2 类产品缺陷 | 最新 222 个通过，2 个训练依赖问题持续处理 |
| SpreadAPI 交付 | 候选及正式 Build 后 DLL 均通过 87/87 检查 | 已暴露 C# 开发题，9 个独立进程、60 个动作的受控验收 |
| 修复分支 CI 检查点（非完整测试集） | **2491 passed, 3 skipped** | 2026-10-11，commit `4459e8a`，run `38115860060`；截至整理时未合并 `main` |

CI 结果见 [GitHub Actions run 38115860060](https://github.com/yang-hoo-xin/RepoForge/actions/runs/38115860060)，执行范围由[工作流](../.github/workflows/ci.yml)定义。该记录绑定修复分支提交，与下文各日期的实验分别呈现。

项目由维护者负责需求定义、架构与技术选型、验收设计，结合 AI 编码工具推进实现。平台开发、产品本地模型生成的补丁和评测结果分别归因。

## 2. 实验条件与测量口径

| 记录 | 日期与条件 | 计数和完成状态 |
| --- | --- | --- |
| 服务负载 | 2026-10-09；Locust；1 个 API、2 个 Worker；6 个源码文件、37 块、102,823 字节；每条件一次，配置运行 60 秒 | BM25 排序与 Chroma 正文读取；生成、查询改写、Dense、Rerank 关闭，模型调用 0 |
| Agent HTTP | 2026-10-09；Qwen3-coder:30b；32K 上下文；Windows/.NET 进程 | HTTP 入队、正常路由、LangGraph、候选编译及冷加载行为验收 |
| 模块 EDD | 2026-10-07；13 个模块、140 个预定义场景 | 工程用例与复验尝试分别统计，部分模型/编译路径使用替身 |
| SpreadAPI | 2026-09-30；已暴露的 C# Mod 开发题；开发者配置验收 | 完整 DLL 冷加载与实际 Harmony 计数，任务委托 Apply、正式 Build 和最终 DLL 复验 |

服务吞吐按完成的不同 job 数除以包含收尾的实际观察窗口计算；202 响应和幂等重放不增加完成数。P95 使用 nearest-rank，从提交计时至客户端观察成功终态，包含排队、子进程启动和轮询。操作拒绝率以发起操作为分母，HTTP POST 拒绝率另以请求数为分母。

工程用例、重复执行、模型调用和独立用户任务使用各自分母。`awaiting_approval` 表示候选已到待审批阶段；受控 DLL 验收、游戏实机和完整交付按实际到达阶段记录。负载数值与五组原摘要身份见[公开 JSON 摘录](evidence/service-load-20261009.json)，计算实现见[汇总器](../scripts/service_load/summarize.py)和[负载脚本](../scripts/service_load/locustfile.py)。

## 3. 实测结果

### 3.1 服务化与负载

已实现 FastAPI HTTP API、独立 Worker、Redis 队列与租约、幂等提交、限流、缓存、超时和有界重试，并接入 Prometheus 与 Docker Compose。业务层复用现有查询服务和 Agent 正常入口；执行结果不明的 Agent 任务进入 `indeterminate`，不会自动重复执行。

实现入口：[HTTP API](../src/service_layer/api.py)、[Worker](../src/service_layer/worker.py)、[Redis Store](../src/service_layer/store.py)、[业务接线](../src/service_layer/backends.py)、[Compose](../deployment/service/compose.yaml)。公开验证代码：[HTTP 边界](../tests/unit/test_service_http_edges.py)、[Worker](../tests/unit/test_service_worker.py)、[真实 Redis](../tests/integration/test_service_job_store.py)、[故障联调](../scripts/service_load/runtime_faults.py)。

| 条件 | 并发用户 | 完成的不同任务 / 发起操作 | 任务/秒 | 成功任务 P95 |
| --- | ---: | ---: | ---: | ---: |
| 不同查询 | 1 | 28/28 | 0.470 | 2.203 秒 |
| 不同查询 | 4 | 64/64 | 1.028 | 4.031 秒 |
| 不同查询 | 12 | 70/70 | 0.993 | 12.437 秒 |
| 重复查询缓存 | 4 | 62/62 | 0.998 | 4.375 秒 |
| 幂等重复提交 | 4 | 60/268 | 0.981 | 4.297 秒 |

缓存组有 56 次命中、6 次未命中。幂等组达到固定 120 次 POST/分钟限额：328 次 POST 中有 60 次创建、60 次重放、208 次 429；POST 拒绝率为 63.415%，操作拒绝率为 208/268，即 77.612%。该组保留原 Locust 退出码 1。

同日真实故障联调的 11 项检查通过，覆盖 Redis 中断时返回 503、恢复后原 Worker 继续执行、实际终止持有任务的 Worker 后由另一 Worker 在租约到期后完成第二次尝试、短预算超时和最终队列恢复。失租首尝试成本仍未知。

### 3.2 真实 Agent HTTP 入口

2026-10-09 的一次新任务经 HTTP、正常路由和 LangGraph 运行，执行 179.085 秒、排队 0.136 秒。Qwen3-coder:30b、32K 上下文实际完成 1 次路由和 7 次产品模型调用，共 19,748 输入、2,092 输出 Token；其中 4,680 缓存输入 Token 已包含在输入数内。

候选真实编译通过，5 个独立冷加载进程的 15/15 行为断言通过；领域终态为 `awaiting_approval`，未 Apply、未正式交付、未启动游戏。终态幂等重放返回同一 job，未再次执行。首轮因准备依赖缺失而在产品图前阻断的记录保留，此次属于修复环境后的新运行。

Compose 默认演示检索，本次 Agent 使用同一服务模块的 Windows 进程。该结果完成实际模型与受控验收的入口联通，不计入自主交付率。

### 3.3 模块评测驱动修复

2026-10-07 的模块 EDD 记录覆盖 13 个模块、140 个预定义场景，执行 224 个不同工程用例，共 282 次用例执行。最新结果为 222 个通过、2 个因训练依赖问题未解决；三批全部执行记录合计 253 次通过、29 次失败，首次失败保留。

该轮确认并修复两类缺陷：预算配置/用量接受非有限浮点数，以及经验提取未贯通编译 DLL、正式验收和原始 request/stdout 的字节身份。新增 46 个产品回归用例、7 个测量保护用例，复用 171 个已有用例；修复后受影响的 58 项检查通过。

实现与检查：[评测 runner](../scripts/run_module_evaluation.py)、[场景清单](../tests/fixtures/evaluation/module_coverage_v1.json)、[预算校验](../src/mod_agent/performance/budget.py)、[预算反例](../tests/unit/test_module_budget_finiteness.py)、[经验提取](../src/mod_agent/planning/member_repair_learning.py)、[证据绑定反例](../tests/unit/test_member_repair_artifact_binding.py)、[测量保护](../tests/unit/test_module_evaluation_measurement.py)。

224 是工程用例数，282 包含复验。该轮真实产品模型调用和新增 Mod 交付均为 0；10 月 7 日当时新增 CI 选集没有远端执行记录，10 月 11 日修复分支 CI 另见摘要中的绑定提交与运行。

### 3.4 SpreadAPI 受控代码交付

2026-09-30，已暴露的 C# Mod 开发题完成自然语言入口、源码调查、规划、产品模型补丁、worker 验收、精确绑定的任务委托 Apply 和正式 Build。需求涉及非法数值输入的原子拒绝及状态/回调行为保留。

原版本为 53/87 检查通过，其中正常行为 15/15；候选与最终 DLL 均通过 9 个独立进程、60 个动作、87/87 检查。修改仅涉及 `API/SpreadAPI.cs`，另外 13 个源码文件及原输入工程保持不变。成功尝试包含 6 次产品调用和 1 次路由，共 31,249 Token；此前失败尝试的 42,660 Token 和原始失败记录分别保留。

公开验收实现：[Evaluator](../src/mod_agent/domain/spread_api_evaluator.py)、[受控输入与原子性场景](../tests/fixtures/evaluation/spread_api_input_atomicity.json)、[Evaluator 检查](../tests/unit/test_spread_api_evaluator.py)、[DLL 探针](../scripts/spread_api_probe/Program.cs)。

验收执行完整 DLL 冷加载和实际 Harmony 计数，跳过游戏回调主体，未执行游戏实机或部署。该开发题独立任务增量为 0。

## 4. 结果解释与持续验证

| 方向 | 当前观察 | 后续验证方向 |
| --- | --- | --- |
| 队列与吞吐 | 12 并发的吞吐未增加，P95 升至 12.437 秒，排队延迟增加 | 在固定语料与查询分布下比较 Worker 数和队列开销，并增加重复测量 |
| 结果缓存 | 缓存组与不同查询组的查询分布不等同，现有结果未证明端到端提速 | 对同一查询分布执行缓存开关对照，计入内容身份校验和排队成本 |
| 服务容量 | 当前覆盖单一受信操作者、本机小语料纯检索；各条件没有重复测量的波动估计 | LLM/完整 Agent 吞吐、多租户隔离、长期稳定性和生产容量尚待专门评测 |
| Agent 执行环境 | 已验证 Windows/.NET HTTP 入口；尚未证明该 Agent 工程可在 Linux 镜像中运行 | 继续推进兼容领域的容器执行与从待审批到交付的完整路径 |
| 评测与迁移 | EDD 仍有 2 项训练依赖问题；SpreadAPI 前后为开发迭代，未隔离单因素 | 持续修复依赖环境，并用其他工程检验稳定交付；现有结果尚未证明跨工程成功率或单因素收益 |

最新十题、开发者辅助实机修复与本页产品模型结果分别记录，未合并为一个成功率。本报告的结论范围是所列运行条件和验收阶段，未得出“优于 Codex”“整体交付率提升”或“生产可用”的结论。

## 5. 原件身份与公开范围

本报告及[数值摘录](evidence/service-load-20261009.json)精选自已记录原件，未全量公开原始日志、模型输入输出和运行环境；不包含本机绝对路径、个人联系方式、凭据、完整用户/模型输入或游戏二进制。公开代码和摘要提供实现、计数及出处线索，摘要本身不能独立证明全部质量。

以下 SHA-256 对应本地保留的原摘要；五组负载摘要身份列在公开 JSON 内。哈希用于核对字节身份，本身不证明实验结论。不同日期的运行按各自版本解释，本页没有声称当前提交重新执行过全部实验；复跑会产生新的条件与结果。

| 原摘要标识 | SHA-256 |
| --- | --- |
| Agent HTTP assessment，2026-10-09 | `4284187fcba3e4e935951370ab8e2041d89462c9956c6367b15decfd3d13b0e5` |
| Service fault assessment v2，2026-10-09 | `d628f09b5436ff0ef4b9b331666436d5fc49bbc4904676197d1cafafb09b6cea` |
| Module EDD result，2026-10-07 | `1a531b7371bf5dbb3ddab5d42e835445056f9e5097f290f766b290293966ca7b` |
| SpreadAPI result，2026-09-30 | `d902827de35b936397efb0b9b2dce6fc31c0328a8f7fc84bb7564c9d167044b1` |
