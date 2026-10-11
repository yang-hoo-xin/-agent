# RAG / Agent 服务

FastAPI 受理任务，Redis 原子维护队列、幂等键、限流和租约，独立 worker 复用 `QueryService` 与正常自然语言 Agent 入口。每次尝试运行在有界子进程中；原始输入、业务结果和进程记录保存在服务器配置的工作目录。Prometheus 从 API 收集 HTTP 与队列指标。

## 本机启动

从仓库根目录创建 `deployment/service/.env`，设置两个不同的随机值：`SERVICE_API_TOKEN`、`SERVICE_REDIS_PASSWORD`。可参考 `.env.example`；已有 `.env` 不覆盖。凭据仅从环境注入，不提交或写入日志。为什么要有它：服务访问权限与队列凭据需要独立管理，部署镜像及实验原件不应携带密钥。

```powershell
docker compose --env-file deployment/service/.env -f deployment/service/compose.yaml up -d --build --scale worker=2
```

初始化容器会生成真实仓库源码的 BM25 / Chroma 示例语料，首次正常查询逐题核对来源。重启复用哈希相同的语料；源码变化时初始化明确报错，应选择新语料目录/卷并保留旧数据。为什么要有它：旧索引不能被静默当成新版本，初始化也不应删除历史证据。

默认地址：API `http://127.0.0.1:8080/docs`，Prometheus `http://127.0.0.1:9095`。Redis 仅发布到本机 `16379`，其他容器间连接使用项目网络。当前认证和配额面向一个受信任操作方，共享同一命名空间；不是多租户 RBAC。

停止服务并保留数据：

```powershell
docker compose --env-file deployment/service/.env -f deployment/service/compose.yaml down
```

持久数据在本项目的命名卷中；不使用 `down -v` 清理实验记录。为什么要有它：服务重启与删除历史数据是不同操作。

## HTTP 合同

业务接口使用 `Authorization: Bearer <SERVICE_API_TOKEN>`。提交时另带 `Idempotency-Key`（最多128个可打印ASCII字符）。

| 接口 | 用途 |
|---|---|
| `POST /v1/jobs` | 新任务返回202；相同幂等键及绑定请求重放返回200和同一job id |
| `GET /v1/jobs/{id}` | 排队、尝试次数、终态、公开业务结果 |
| `GET /v1/features/{id}/{view}` | 配置 ArtifactStore 后复用原只读 artifacts/status/dashboard 接口 |
| `GET /health` | API 与 Redis 连通性 |
| `GET /metrics` | HTTP 计数/延迟、Redis队列及生命周期累计事件 |

同一幂等键绑定不同请求或执行配置返回409；限流/容量返回429及 `Retry-After`；Redis不可用返回503。请求体在JSON解析前限制大小和读取时间，参数拒绝未知字段、非法类型及非有限数字。为什么要有它：重放不能生成第二个任务，坏输入也不能进入执行队列。

示例检索请求：

```json
{
  "kind": "query",
  "payload": {
    "query": "RedisJobStore IdempotencyConflict",
    "collection": "service_load",
    "top_k": 5,
    "answer": false,
    "rewrite": false,
    "rerank": false
  },
  "timeout_seconds": 60,
  "max_attempts": 2
}
```

`timeout_seconds` 是每次尝试从worker领取开始的执行预算，包含子进程启动；排队时间另记。`max_attempts`最多3。HTTP客户端停止轮询不等于服务端取消任务。活动作业和幂等记录保留到终态后才开始保留期TTL。

`completed` 表示后端返回了结构化结果，必须继续检查领域结果。Agent的澄清、待批准、partial和实际交付各自保留，不能凭HTTP200或队列completed声明代码交付。为什么要有它：基础设施完成与用户需求满足属于不同层次。

## Agent 注册

服务器通过 `SERVICE_AGENT_PROFILES` 注册 `profile_id → 绝对profile路径`，客户端只提交id和需求：

```json
{"kind":"agent","payload":{"profile_id":"registered_project","description":"修改这个已登记工程的需求"},"timeout_seconds":600,"max_attempts":1}
```

API入队绑定profile字节，worker核验相同内容后调用既有 `dsh_request_routing.run_natural_request`。profile必须符合产品入口原有授权与执行约束；服务不接受客户端提供执行器或任意本地路径。失租或执行结果不明的Agent进入 `indeterminate`，不自动重跑。为什么要有它：不确定的源码或工具副作用不能通过盲重试重复执行。

默认Compose演示运行检索，Agent注册表为空。Windows/.NET/GTFO回归profile由Windows本机的同一API和worker模块执行，使用独立Redis命名空间与工作目录；Linux容器只能执行与其文件系统、工具和产品入口兼容的profile。示例本机启动入口：

```powershell
# 先在该进程环境设置SERVICE_API_TOKEN、SERVICE_REDIS_URL、SERVICE_NAMESPACE、
# SERVICE_SETTINGS、SERVICE_WORK_ROOT、SERVICE_AGENT_PROFILES。
.venv\Scripts\python.exe -B -m uvicorn src.service_layer.api:create_app --factory --host 127.0.0.1 --port 8082
.venv\Scripts\python.exe -B -m src.service_layer.worker
```

同一队列的API和worker必须部署一致的注册配置及可访问数据。为什么要有它：跨机器路径不可自动互换，队列中的配置哈希不能替代实际执行依赖。

## 超时、恢复与缓存

worker续租并用租约token提交结果，过期owner不能覆盖新owner。进程取消清理Windows Job / POSIX进程组；关闭客户端进程并不证明外部模型服务器已经停止。短暂Redis连接故障采用退避，永久认证/配置错误明确失败。

Query只对已确认尚未执行的可恢复缓存连接故障，或失租后的只读任务在额度内重试；全部attempt保留。Agent禁止自动重跑。为什么要有它：恢复需遵守原执行副作用边界和重试额度。

Redis结果缓存复用业务层的配置、源码、索引和模型身份。纯稀疏路径绑定实际 Chroma 正文/metadata 的稳定语义哈希，避免旧正文命中和跨进程SQLite文件抖动。此检查包含全量读取/哈希成本。模型身份未知的生成路径不会凭空启用缓存。

## 可重算验证

真实HTTP烟测：`scripts/service_load/http_smoke.py`。异常联调：`runtime_faults.py`。负载和容器采样见 [压测说明](../../scripts/service_load/README.md)，五组编排入口为 `run_matrix.py`。

吞吐以完成的不同job计数，P95注明样本量、nearest-rank算法及完整窗口；提交延迟、任务端到端延迟、排队和执行分别统计。容器资源只包含显式指定的本项目服务，不含外部模型或宿主总资源。为什么要有它：202、重复返回或提前失败都不能被包装成任务吞吐或提速。
