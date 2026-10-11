# RepoForge 文档

RepoForge 将自然语言需求推进到有证据、可验收、可授权应用的代码变更。这份入口按阅读目标组织当前实现、使用说明和实测结果；研究方案与历史实验保留在对应专题中。

## 了解项目与实测结果

| 阅读目标 | 入口 | 内容 |
| --- | --- | --- |
| 快速了解产品 | [项目首页](../README.md) | 目标、核心能力、工作流与快速开始 |
| 查看已完成验证 | [实测报告](PUBLIC_RESULTS.md) | 服务化、真实 Agent 入口、模块 EDD、受控代码交付与绑定版本的 CI 结果 |
| 核对服务测量数字 | [负载数值摘录](evidence/service-load-20261009.json) | 五组条件、完整分母、结果与原摘要 SHA-256 |
| 理解交付目标 | [产品契约](ACTIVE_PRODUCT_CONTRACT.md) | 新建、修改、继续修复，以及验收与执行边界 |

## 运行与接入

| 阅读目标 | 入口 | 内容 |
| --- | --- | --- |
| 启动服务演示 | [服务部署与 HTTP 接口](../deployment/service/README.md) | Compose、认证、异步作业、Agent profile 与停止方式 |
| 理解 HTTP 到业务的调用 | [服务业务接线](../src/service_layer/backends.py) | 查询服务复用、登记 profile 和自然语言 Agent 入口 |
| 使用命令行入口 | [CLI 实现](../src/mod_agent/cli.py)、[自然语言路由](../scripts/dsh_request_routing.py) | 命令参数与新建、修改、续接、澄清的路由 |
| 配置补丁续接 | [Patch 上游续接](PATCH_UPSTREAM_CONTINUATION.md) | Evidence / Planning 配置和原 worker 的接入方式 |
| 查看模型选择机制 | [模型资格路由](MODEL_QUALIFIED_ROUTING.md) | 可选角色选择、身份绑定与显式配置关系 |

## 理解架构与评测

| 阅读目标 | 入口 | 内容 |
| --- | --- | --- |
| 了解工作流与职责 | [架构说明](ARCHITECTURE_OVERVIEW.md)、[LangGraph 图](../src/mod_agent/workflow/graph.py) | 控制流、领域边界与具体实现；架构文档中的里程碑保留其原始阶段语境 |
| 查看产物持久化 | [ArtifactStore](../src/mod_agent/artifacts/store.py) | 业务产物、身份与谱系的保存入口 |
| 理解成功与成本计数 | [评测驱动开发](EVALUATION_DRIVEN_DEVELOPMENT.md) | 补丁可用、任务交付、自主程度，以及实验分母与预算 |
| 运行模块评测 | [模块 runner](../scripts/run_module_evaluation.py)、[场景清单](../tests/fixtures/evaluation/module_coverage_v1.json) | 模块、场景、工程用例与执行尝试的组织 |
| 理解负载测量 | [压测说明](../scripts/service_load/README.md)、[汇总器](../scripts/service_load/summarize.py) | 任务吞吐、终态延迟、幂等、限流和资源采样口径 |
| 查看持续集成 | [CI 工作流](../.github/workflows/ci.yml) | 依赖环境、检查选集与运行步骤；最近已记录结果见实测报告 |

## 研究与项目沿革

[检索架构决策](RETRIEVAL_ARCHITECTURE_DECISIONS.md)和[检索验证计划](RETRIEVAL_VALIDATION_PLAN.md)记录设计选择、待验证假设与实验方案。[成果清单](PROJECT_OUTCOMES.md)、[项目状态](PROJECT_STATE.md)及[实施队列](IMPLEMENTATION_QUEUE.md)保留按日期推进的研发记录，历史段落描述当时的条件与结论。

更早的快照包括[状态归档](PROJECT_STATE.history-20260926.md)、[产品合同归档](ACTIVE_PRODUCT_CONTRACT.history-20260926.md)和[评测周期归档](EVALUATION_FIRST_CYCLE.history-20260927.md)。这些材料用于追溯演进；当前对外结果集中在[实测报告](PUBLIC_RESULTS.md)，可执行接口由相应代码和配置定义。
