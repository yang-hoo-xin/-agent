# HTTP 异步检索压测

本目录测量真实 QueryService 的 BM25 排名、Chroma 正文读取、Redis 结果缓存及异步队列入口。answer、rewrite、dense、rerank 均关闭；Chroma 的一维常量向量只满足正文存储接口，不参与检索。不是完整 LLM / Coding Agent 吞吐测试。

准备：在实际 worker 所用文件系统中运行，输出目录必须不存在。

```sh
python -B scripts/service_load/prepare_corpus.py --output-root /bench/corpus
```

结果含原文副本及 SHA256、BM25 / Chroma 数据、`settings.yaml`、`queries.json`、正常 QueryService 的六题烟测。将服务的 `SERVICE_SETTINGS` 设为 `/bench/corpus/settings.yaml`，确保 API 与 worker 均可读取相同路径。每次实际构建记录真实文件数量和字节数，不能把重复复制文本当更大语料。为什么要有它：语料和绝对路径决定真实读取内容，配置相同不代表容器能访问同一份索引。

在压测客户端安装 Locust；本目录不更改项目依赖锁。以下示例是 Linux shell，Windows 可用同名环境变量：

```sh
export SERVICE_LOAD_QUERIES=/bench/corpus/queries.json
export SERVICE_LOAD_OUTPUT=/bench/results
export SERVICE_LOAD_MODE=unique
export SERVICE_LOAD_RUN_ID=unique-u4-r1
# SERVICE_API_TOKEN 通过环境注入；不要放在命令参数或结果文件。
locust -f scripts/service_load/locustfile.py --host http://127.0.0.1:8000 \
  --headless -u 4 -r 1 -t 60s --stop-timeout 100 --csv /bench/results/unique-u4-r1
python -B scripts/service_load/summarize.py /bench/results/unique-u4-r1.*.jsonl \
  --output /bench/results/unique-u4-r1.summary.json
```

三种模式分别执行，采用新的 run id，保留启动条件、并发、服务限流、worker 数和每次运行的完整窗口。为什么要有它：不同负载或配置不能混合成一个没有明确分母的吞吐提升数字。

| 模式 | 请求方式 | 核对重点 |
|---|---|---|
| `unique` | 保留真实检索词，附加独立 nonce；每次新幂等键 | 正常检索成功、服务实际缓存 miss/unknown |
| `cache` | 循环六个相同查询，每次新幂等键及 request id | 新作业真正得到 `cache.result=hit`，不能把幂等重放当缓存命中 |
| `idempotency` | 相同正文与幂等键连续提交两次，再等待同一作业 | 第二次 200、created=false、同一 job id；完成吞吐只计一次 |

`SERVICE_LOAD_TIMEOUT` 默认 90 秒，同时作为任务预算和客户端总观察预算；`SERVICE_LOAD_POLL_SECONDS` 默认 0.1 秒。轮询等待只负责等真实作业，并未向服务注入 sleep 假任务。压测结束给出足够 `--stop-timeout` 让在途请求收尾；强制中断、缺少终态和超时全部保留。为什么要有它：提前结束的任务不能从成功率或耗时样本中悄悄消失。

每进程 JSONL 记录 run start/stop、operation start/end、每次 HTTP 的时刻/状态/延迟、作业原始公开结果、缓存与用量。token 和 Authorization 不写入。多进程仅可汇总同一个显式 `SERVICE_LOAD_RUN_ID`；记录各机时钟条件。为什么要有它：重复幂等响应、真正任务、失败和缓存身份必须可逐条复核。

汇总使用 nearest-rank P50/P95，分别给提交 HTTP 延迟、端到端作业延迟、成功作业延迟、HTTP 状态和完整失败分母。完成吞吐为「不同的成功 job id / 完整观测窗口（含收尾）」；202 请求吞吐另列。成功需服务与业务双终态、命中预期源码且 answer/rewrite 调用为零。为什么要有它：快返回 202、空检索、失败业务以及重复返回同一作业都不应计为完成任务。

资源数据由运行方同期保存容器/宿主采样，并绑定本次 run id；本脚本不会以未采集的数据填 CPU、内存或资源收益。缓存模式保留首轮 miss 和实际 hit，不预热删样本；若另做预热，必须单独留其成本与启动边界。为什么要有它：资源与启动条件影响结论，不能把它们隐含在平均数中。

## 显式容器资源采样

`resources.py` 只使用标准库，并通过参数数组调用 `docker stats --no-stream --format json`。必须明确列出项目与容器名；可以重复指定多个 worker，不能空参数扫描全部容器。为什么要有它：仅采集本次项目的 API、worker、Redis 和 Prometheus，避免无关应用进入统计。

```sh
python -B scripts/service_load/resources.py sample --run-id unique-u4-r1 \
  --project rag-agent-service \
  --container api=rag-agent-service-api-1 \
  --container worker=rag-agent-service-worker-1 \
  --container redis=rag-agent-service-redis-1 \
  --container prometheus=rag-agent-service-prometheus-1 \
  --duration 170 --interval 2 --command-timeout 10 \
  --output /bench/results/unique-u4-r1.resources.jsonl
python -B scripts/service_load/resources.py summarize \
  /bench/results/unique-u4-r1.resources.jsonl \
  --output /bench/results/unique-u4-r1.resources.summary.json
```

采样应覆盖同一 Locust run 的开始和收尾。可用 `--window-start`、`--window-end` 指定该次作业汇总中的 Unix 时间，只有整个采样命令区间落在窗口内的样本进入汇总。原始 JSONL 保留每次 stdout/stderr、原始单位、命令起止时间、超时、缺失容器与解析失败。为什么要有它：不能把负载前后的空闲样本混入负载均值，也不能把缺失值补成零。

汇总给每容器采样 CPU／内存的算术均值和观测峰值，并给同一轮完整采样的合计均值、峰值及对应时间。不会相加不同时间的单容器峰值；采样均值不是时间加权均值，也不代表未采到的瞬时峰值。为什么要有它：资源合计必须来自同一次完整观察，离散轮询只能证明实际采到的值。

CPU 保留 Docker 的百分比口径（可能超过 100%），内存按原始 SI／IEC 单位换算。Linux 下 Docker CLI 的内存数字会扣除 inactive file cache；该数据不是宿主总内存。采样不含 Docker VM／daemon 本身、外部 LLM/GPU、负载生成器或其他容器。具体口径参见 [Docker stats 官方文档](https://docs.docker.com/reference/cli/docker/container/stats/)。为什么要有它：容器观测不能泛化为整机资源或完整模型执行成本。
