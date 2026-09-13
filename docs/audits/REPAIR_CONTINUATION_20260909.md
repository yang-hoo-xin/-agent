# Repair 连续修订与上游返回：2026-09-09

本轮按用户的 Repair 对账实施，基于 `b1bc71f623e800cd170e275edb0242fe6e5f918c`，工作分支为 `codex/repair-feedback-loop`。另一页的 Findings 和整链主树修改没有被覆盖。本文是本轮实现及验证的详细记录；旧模型试验、旧判定结果保持不变。

## 1. 修改与验收边界

| 对账问题 | 实现与可验证结果 | 仍不能声称什么 |
| --- | --- | --- |
| 第二份代码失败后不能继续 | `local_entry.py` 复用原 worker，在原总预算内按当前代码/报告连续修订；接用每段 `final_request`。三份不同代码、两次失败后第三份通过的受控入口回归已执行 | 工程场景使用脚本响应，不是模型质量实验 |
| 读取、反馈和次数历史会被覆盖 | `recovery_revisions` 逐段保存；旧两个字段保留为最新段引用。Graph、产品入口累计账本和执行索引读取完整序列，不把最新别名重复计算 | 不会额外发放调用额度；一次读取或格式修正也会占用模型请求 |
| 有余量却不再给行为纠正机会 | 连续行为失败可以再次进入原 worker；静态投稿错误可使用原来预留给恢复的额度，原总上限不变 | 留有预算不意味着必须花完；工具、证据、环境、身份和字节容量仍能阻断 |
| 无效循环 | 同一物化代码、失败核心、验证身份和已有来源观察集合第三次相同即停止；允许一次重复后继续修正 | 不把措辞变化当成代码改善；不自动增加第三款模型或训练轮次 |
| 投稿或静态检查卡住 | `PatchSubmissionValidationError` 只覆盖无操作替换、原 C# 头部检查和原完整文件 diff 的新增行尾空格。完整材料反馈回同一循环，不自动改代码 | 不是全部 `PatchGenerationError` 或全部 Dry-run 拒绝都可重试；权限、源码哈希、范围、BOM等硬错误仍停止 |
| 硬停后丢失已花预算 | 硬投稿错误返回阻断段，保留已执行请求、读取、字节和原 diagnostics；源码或模型身份漂移不触发额外格式修正 | 停止记录不是修复成功，也不是观测内容被模型理解的证明 |
| 不直接展示当前被测实现 | 从完整组合物化字节构造当前源码窗口与 diff，绑定实际代码哈希；多处同文件修改展示最终组合结果。明确当前行号不是原编辑绑定范围 | 大文件只展示所有修改附近的窗口，`complete=false`；不会据此扩大写权限。展示数据也消耗原反馈字节预算 |
| 反例只有标签 | 新版自有案例检查器在操作发生时记录初始状态、操作顺序和观察步骤；评估入口保留显式 `input`，缺失则标记 `unknown` | 目前新增实际过程生产只覆盖 `snapshot_nested_tags` 与 `paging_partial_tail`；没有给旧记录补造时序 |
| 请求上游必然重建 Plan | 仅在显式上游评估中允许 `retain_current_plan`。当前完整 Plan、失败代码/报告送给同一个 Planning owner；模型在既有 `rationale` 解释范围与实现问题，Graph复验后保留原引用 | 相同目标选择不自动等于保留 Plan；Evidence引用发生变化时不得沿用旧Plan依赖；仍只允许原来的一轮上游评估 |
| 返回后丢历史或重置预算 | 同 Plan 返回沿用旧工具/代码/失败历史，只添加新的评估反馈。原已花预算作为 `prior_worker_budget`，新段记录增量，原共享总账继续约束 | 复用的是同一类 shared worker 的下一执行段，不是同一个 Python 对象；没有继承旧批准 |
| Findings 在上游停止 | 本轮整理了精确源码和失败资料供评审，生产修改继续由另一任务负责 | `7ea960f` 的配置 Actual 仍是失败；另页的父义务补全仅有离线验证，没有第二次 Actual 成功 |

职责保持原划分：RepairPlanner 描述允许的恢复边界，Graph 条件边决定最终路由；共享 worker 理解失败并选择行动；执行器按原标准验证。没有建立独立诊断模型、另一状态机、长期记忆系统或新的诊断 Artifact。

## 2. 工程验证

最小旧版反例先执行：原实现第二次行为失败后结束，三份代码修复场景失败。新版本经 `run_fresh_patch_continuation`、真实 Graph、原 Proposal/Review/Dry-run 路径验证第三份修订。脚本模型只为控制失败顺序；没有真实网络或模型请求，也没有 Apply、正式产品 Build 或游戏 Runtime。

连续修复聚焦用例覆盖：三份不同代码及各自报告绑定、两个恢复段分别读取、共享模型临界值、视图导致字节不足、初始失败代码视图、重复初稿后修正、无进展早停，以及成功/环境/上游请求不强迫耗尽预算。

上游公开 CLI 的脚本验收实际执行 `Patch × 3 → Planning × 1 → Patch × 1`，合计五次模拟 provider 请求；仅剩一次时仍可完成。原三个输入 Artifact 引用及 Plan 修订数不变，旧工具响应与当前失败代码保留且不重复计费，Review/Dry-run各一次。第二次上游请求停止，Planning不再次执行。漂移、初始Planning冒用保留决定、Evidence已改变及“相同目标但明确选择重建Plan”均有反例。

独立评审额外发现并修复两处可复现问题：硬提交错误丢失已执行段计账，以及非法JSON响应在检查模型身份前触发再请求。四项定向回归覆盖初始段硬停、行为段硬停、模型身份漂移和源码漂移。模型身份反例精确断言 `OLLAMA_MODEL_DIGEST_DRIFT`，不接受其他偶然错误代替。

最终跨模块检查覆盖 **376 项**：首次两进程检查 **373 passed / 3 failed，297.36s**。失败都是旧回执口径断言：预算拒绝时现在保留空的恢复历史；字节数现在计算完整新增代码/反馈消息，而不只是失败正文。仅修改这两处测试，仍从实际传输消息独立计算已花字节；三项串行定向复跑 **3 passed，32.38s**。最终该选择集没有未解决失败，未重新运行完整376项。

首次命令（Python为已存在的本地3.10环境；`$repairEvidence`指本轮本地验证目录）：

```powershell
$repairCheckFiles = @(
  'tests/unit/test_continuous_behavior_repair.py',
  'tests/unit/test_patch_submission_static_loop.py',
  'tests/unit/test_patch_recovery_ledger.py',
  'tests/unit/test_patch_working_view.py',
  'tests/unit/test_repair_submission_validation.py',
  'tests/unit/test_repair_review_regressions.py',
  'tests/unit/test_owned_verifier_input.py',
  'tests/unit/test_patch_submission_loop.py',
  'tests/unit/test_patch_submission_cli.py',
  'tests/unit/test_patch_recovery_worker.py',
  'tests/unit/test_patch_read_accounting_admission.py',
  'tests/unit/test_patch_behavior_feedback.py',
  'tests/unit/test_patch_upstream_unchanged_plan.py',
  'tests/unit/test_patch_upstream_replanning.py',
  'tests/unit/test_patch_upstream_cli.py',
  'tests/unit/test_patch_upstream_budget.py',
  'tests/unit/test_patch_execution_index.py',
  'tests/unit/test_patch_agent_loop.py',
  'tests/unit/test_external_patch.py',
  'tests/unit/test_patch_sft_eval.py',
  'tests/unit/test_model_planning_selection.py',
  'tests/unit/test_request_patch_repair_context.py',
  'tests/unit/test_product_patch_journal.py'
)
python -B -m pytest @repairCheckFiles -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\rpl-final-0909" --junitxml="$repairEvidence/combined-checkpoint.xml"
python -B -m pytest tests/unit/test_continuous_behavior_repair.py::test_feedback_view_exceeding_byte_budget_stops_without_spending_it tests/unit/test_patch_upstream_budget.py::test_new_plan_keeps_exhausted_reads_and_consumed_observation_bytes -q --tb=short --basetemp="$env:TEMP\rpl-final-fix-0909" --junitxml="$repairEvidence/checkpoint-focused-followup.xml"
```

日志与JUnit保存在本地输出根的 `scratch/repair_feedback_loop_001/validation/`。检查过程中生产源码未再变化；首次检查后仅有上述两处测试预期与文档更新。另已执行提交校验owner的133项检查和输入记录/评估的19项检查；它们与最终选择集有重叠，不能相加宣传为独立案例数。Ruff的 `E9,F63,F7,F821` 检查与 `git diff --check` 通过；完整Ruff仍存在旧文件未使用导入、异常命名等非本轮清理项。未执行全仓测试或宣称托管CI通过。

## 3. 真实 C# 检查器过程记录

只使用两份此前已结束的错误 C1 源码与新版检查器，在短临时目录实际编译执行。对两个案例的 4 项和 7 项检查，逐行比较原 `check/expected/observed/group/passed`，结果全部相同。错误仍然存在：内层列表双向共享、尾页及超页尺寸错误没有因新增记录变成通过。

新增过程记录包含双向修改发生在哪一侧，以及分页请求的实际尺寸和前后偏移；快照在记录时固定，不随后续列表变动。执行框架保留这些原始结构化输入，不通过案例名字猜测过程，也不把隐藏检查器源码交给模型。

本地详细证据：输出根下 `scratch/repair_feedback_loop_001/validation/c1-input-recording/summary.json`，SHA-256 `86be1cb31635901a5cadb939c2b72686855bd711f96ca629f4965d16a12d2c89`。同目录 `archive-manifest.json` 记录复制来源和校正后的引用；编译二进制与参数文件仍明确引用保留的原临时路径。该验证器身份已改变，不能回填原 Max/30B/1.7B 对照或宣称旧请求看见了这些过程。

## 4. 下一次模型验收与未完成项

本轮未重训1.7B或30B、未执行新的真实模型任务、未上传Langfuse。此前30B两题行为检查通过，但分页在尾空格检查阻断；此前Max在两份预置真实失败上各一次修订成功。这些旧事实不能作为新连续循环或新输入视图的真实模型验收。

下一次有明确范围的真实任务应继续使用原判定和固定模型版本，记录实际请求数、每份代码/反例/后续动作，以及阶段终点。先检验新增机制能否让原阻断继续并修对，再决定是否调整模型或做新的SFT。调用次数与代码修订次数分别统计；不能把阶段完成率、编译通过或一次简单案例通过写成真实Mod交付。

本轮代码尚需与另一页已验证的主树WIP按提交对齐。Findings自然语言入口、First Shot原36项行为、完整修改编译、真实配置路径和适用游戏Runtime仍需各自证据。独立多任务稳定性评测未完成；本轮没有改变这些未验证状态。

## 5. 2026-09-13：默认产品入口的 Patch 上游补查与续行

本次从已验证的 `ed5234b9e0c6a2c453a0fbc0352e7a43964e958e` 建立独立分支 `codex/product-patch-upstream`，未带入原主工作区的文档 WIP，也未合入 `b8b0d63`。以下是新增产品装配的工程验收，不是新的模型或 Mod 验收。

默认 `run-request` 现在将合法 Patch 上游请求交回同一个 Graph：首次尚无失败代码时，使用当前产品 journal 和材料不足请求，不制造失败记录；当前 worker 已生成且验证失败时，核验实际响应、物化代码、报告及后续消费的反馈。Evidence 路径实际执行原 `rg` 检索，合并新旧证据并重算完整 Findings，再由全新单次 Planning selector 形成合法 Plan。明确 `retain_current_plan` 时，重新检查依赖后保留原引用和 worker 历史。新段回到原验证、Review、Dry-run 和精确批准入口。

预算仍使用原任务和五个阶段：查询与 Planning 重评记入 `repair`；完整 Findings 记入 `requirement_findings`；续 worker 消费原 Patch 阶段余量。请求、读取和观察字节不退款，不在运行中增加任何上限。默认无失败补查正例使用原阶段额度 `2/2/1/2/2`，总额 9、实用 8：Projection、Findings、Planning、Patch、查询、Findings、Planning、Patch。失败后的两个正例在执行前分配原任务总额 10、Patch 阶段 3，分别使用 7 和 9 次确定性传输。

产品模式使用自己的实例，不构造 Fresh 请求。产品生命周期只识别一次有精确材料引用的上游评估插入，仍复用原流程与普通 Repair 校验。旧 diff 和 Review 批准清除；仅从原 typed 产品请求重取 `confirmed_write`，以进入本次精确审批 reader，不能代替新 diff 批准。缺 provider、第二次上游请求、当前失败错绑、预算耗尽和 Planning 超时均明确停止。外部发送生成代码或验证反馈前，仍要求已有对应披露授权；拒绝发生在预算预留与发送前。

新增查询和重规划分别使用 `upstream_evidence_queries`、`patch_upstream_planning`，通过原 `trace_upstream_model_call`，Findings 沿用原角色。联合测试验证一次传输对应一条 generation、本地请求与回复文件哈希、同任务两段 journal、新 Evidence 到第二次 Planning 输入的哈希关系，以及原离线联查中的新增材料消费。没有调用 Fresh `_RecordedProvider` 来冒充这些产品调用的统一追踪。

验证全过程只用确定性模型传输、基线编译替身和行为判定替身，真实执行源码检索及原 Graph／worker／静态检查／Review／Dry-run。无真实模型、产品 Apply、真实编译、游戏或 Cloud 上传。

旧路径复现：在短临时目录解压 `git archive ed5234b9e0c6a2c453a0fbc0352e7a43964e958e`，只加入新测试，运行以下首项，得到 **1 failed，6.29s**，精确错误为 `PATCH_AGENT_UPSTREAM_REQUESTED`，仅执行前四次传输，没有补查。修复后以下三个选择共 **4 passed，24.02s**（产品失败用例参数化为保留／新 Plan）：

```powershell
python -B -m pytest tests/unit/test_mod_agent_cli.py::test_cli_run_request_patch_evidence_return_executes_new_search_and_reaches_original_review tests/unit/test_product_execution.py::test_product_upstream_retains_current_failed_plan_and_original_checks tests/unit/test_upstream_product_trace.py::test_product_patch_upstream_trace_keeps_one_task_and_current_material_lineage -q --tb=short --basetemp="$env:TEMP\pupr-four-$PID"
```

最终只做一次有界并行检查，选择 **299 项**：

```powershell
python -X utf8 -B -m pytest tests/unit/test_patch_upstream_replanning.py tests/unit/test_patch_upstream_cli.py tests/unit/test_patch_upstream_unchanged_plan.py tests/unit/test_patch_upstream_budget.py tests/unit/test_product_execution.py tests/unit/test_mod_agent_cli.py tests/unit/test_upstream_product_trace.py tests/unit/test_product_patch_journal.py tests/unit/test_run_request_shared_worker.py tests/unit/test_run_request_external_worker.py tests/unit/test_request_patch_repair_context.py tests/unit/test_deferred_product_approval.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\pucp-$PID"
```

结果 **233 passed / 58 failed / 8 errors，132.36s**。Windows 子进程未继承父进程的 `-X utf8`，旧测试夹具以 GBK 读取 UTF-8 回执。此次并行验证不能称为全绿。未改源码或测试来消除错误，先串行分类两项，再仅补跑剩余失败选择：

```powershell
python -X utf8 -B -m pytest tests/unit/test_patch_upstream_replanning.py::test_human_finding_runs_repair_then_model_planning_in_the_existing_graph tests/unit/test_run_request_external_worker.py::test_production_assembly_uses_external_adapter_inside_original_request_worker -q --tb=short --basetemp="$env:TEMP\puclass-$PID"
python -X utf8 -B -m pytest tests/unit/test_patch_upstream_replanning.py tests/unit/test_patch_upstream_cli.py tests/unit/test_patch_upstream_unchanged_plan.py tests/unit/test_patch_upstream_budget.py tests/unit/test_request_patch_repair_context.py --lf -q --tb=short --basetemp="$env:TEMP\pufix-$PID"
```

分别 **2 passed，3.77s** 和 **64 passed / 6 deselected，145.82s**。因此该 299 项选择最终无未解决失败；未重跑已通过的 233 项，也未声称单次 299 项并行全绿。检查期间生产源码与测试未再变化，之后仅添加本节。15 个改动 Python 文件 AST 解析及 `git diff --check` 通过。Ruff 未安装，未安装新工具。未执行全仓或新 hosted CI；此前的历史通过数量不与本次相加。

未覆盖的触发点与下一交付门：初次 Findings 缺证（尚未进入 Patch）仍会停止；普通 Build 后的 Repair worker 若本段尚未生成新代码而提出上游请求，也仍停止。本次补查仅接已有源码检索与完整 Findings，不声明新增程序集 metadata／IL 调查能力。真实模型能否正确使用新材料、热切换业务是否需要修改及能否通过原业务判定，均待单独授权验收；基线已满足时允许不修改。热切换还需固定真实用户操作、统一源码／依赖快照和独立判定，不能预设坐标或向模型提供正确 Hook。原页继续负责前置失败持久留存，部分 Apply 失败事实记录在其后；本提交不声称解决它们。

## 6. 2026-09-13：首次 Findings 缺证后的默认入口补查

本包以已整合的 `dbe18ae89ec53b0c40db206027d346e489757249` 为基线，在 `codex/initial-findings-reassessment` 独立实施，解决上一节未覆盖的首次 Findings 缺证入口。没有从旧分支丢弃前置失败持久化；未修改 `execution/patch_apply.py` 或 Graph 的 `_run_isolated_apply`，后者 AST 与本包基线相同。

默认 `run-request` 的初次完整、已接受模型 Findings 若判缺证，原 `retrieve_evidence` 节点先保存不可变的不足 Evidence，再调用一次已有查询／真实 `rg`／完整 Findings 能力。第二份 Evidence 精确引用第一份，FeatureSpec、需求投影、义务、关系及原查询不重建、不改变；没有 Plan、Patch、Repair 或虚构失败代码／报告。充分时进入原 Planning、worker、Review 和 Dry-run；仍不足或缺 provider 时明确停止。未配置补查的旧适配器保留原路由，不因本次入口接通改变其结果形状。

新增回调是 `initial_findings_reassessment_factory`；`RequirementCoverageReassessmentFactory.reassess_initial` 复用原补查核心。当前已有 EvidencePack 的 `budget_summary` 增加本次精确旧引用和一次补查标记，未增加 Artifact 类型、Graph 或独立控制面。必要的输入修正是：`rg_live` 过去的 query-set 结果只保留空 evidence IDs，无法区分零命中和工具／来源错误；现在保留 owner 已知的 `retrieval_status` 到每条 `per_query_execution`，不从错误文字猜测。合法零命中可补查；语义 provider 失败、格式未接受、检索故障和来源漂移不能冒充可补查的 Findings。补查没有查询时停止，不用一次空检索后重新打分宣称恢复。

`initial_findings_queries` 通过原统一模型追踪，预算计入已有 `repair`；重算 Findings 使用原 `requirement_findings` 余量。默认阶段额度仍为 `2/2/1/2/2`、总额 9，完整正例实际调用顺序是 Projection／Findings／查询／Findings／Planning／Patch，共 6 次确定性传输。已有消费不退款，阶段上限不提高。Trace 验证两份 Evidence、一次原需求投影、6 条 generation 对应6次传输、正文引用哈希、当前 Planning 输入和现有离线联查中的新增材料消费；没有 Cloud 上传。

旧路径复现和新路径聚焦验证：

```powershell
$env:PYTHONUTF8='1'
python -B -m pytest tests/unit/test_mod_agent_cli.py::test_cli_run_request_initial_findings_gap_searches_before_first_plan_and_patch -q --tb=short --basetemp="$env:TEMP\ifgap-old-$PID"
python -B -m pytest tests/unit/test_mod_agent_cli.py::test_cli_run_request_initial_findings_gap_searches_before_first_plan_and_patch tests/unit/test_mod_agent_cli.py::test_cli_run_request_initial_findings_gap_stops_without_first_plan_or_patch tests/unit/test_upstream_product_trace.py::test_initial_findings_reassessment_trace_binds_both_evidence_revisions_without_repair tests/unit/test_upstream_product_trace.py::test_public_upstream_to_patch_trace_preserves_calls_decisions_and_materials[missing_findings] -q --tb=short --basetemp="$env:TEMP\ifgap-new-$PID"
```

修改前 **1 failed，3.78s**，真实产品入口仅执行 Projection／Findings，合法 missing 后停止，Planning／Patch为0。接通后 **8 passed，21.60s**：完整正例、无provider、阶段／总预算耗尽、再次缺证、查询超时，以及两份Evidence的追踪联查。另有factory 5项通过（2.27s）、空查询新增1项通过（1.62s）、产品读回精确引用／投影错配3项通过（8.72s）；与下面选择集重叠，不相加宣传。

唯一有界检查选择422项，使用可传给Windows子进程的UTF-8环境变量：

```powershell
$env:PYTHONUTF8='1'
python -B -m pytest tests/unit/test_requirement_coverage.py tests/unit/test_rg_live_evidence.py tests/unit/test_product_execution.py tests/unit/test_mod_agent_cli.py tests/unit/test_upstream_product_trace.py tests/unit/test_patch_upstream_replanning.py tests/unit/test_patch_upstream_cli.py tests/unit/test_patch_upstream_unchanged_plan.py tests/unit/test_patch_upstream_budget.py tests/unit/test_run_request_shared_worker.py tests/unit/test_run_request_external_worker.py tests/unit/test_deferred_product_approval.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\ifcp-$PID"
```

首次 **418 passed / 4 failed，192.53s**。三个失败来自初版把所有Product不足Evidence都直接送blocked，改变了旧未配置补查适配器的结果形状；已把新路由限定到实际接入本次补查的流程，原测试断言没有放宽。另一项是既有 `requirement_findings_duplicate_relation_indexes.json` 被Git的Windows签出转换为CRLF；串行复核仍在固定字节哈希断言失败（1 failed，1.43s）。Git中原始LF字节哈希匹配既有固定值，确认只有换行差异后恢复该文件的提交原字节，没有改变内容、预期哈希或Git差异。

修正后只做以下受影响定点检查，**10 passed，23.19s**：

```powershell
$env:PYTHONUTF8='1'
python -B -m pytest tests/unit/test_product_execution.py::test_public_product_executor_runs_real_graph_and_strict_store_chain tests/unit/test_product_execution.py::test_product_execution_blocks_unresolved_change_authority_before_patch tests/unit/test_product_execution.py::test_product_execution_actual8_projection_correction_no_progress_fails_closed tests/unit/test_requirement_coverage.py::test_findings_provider_rejects_frozen_duplicate_relation_indexes tests/unit/test_mod_agent_cli.py::test_cli_run_request_initial_findings_gap_searches_before_first_plan_and_patch tests/unit/test_mod_agent_cli.py::test_cli_run_request_initial_findings_gap_stops_without_first_plan_or_patch -q --tb=short --basetemp="$env:TEMP\iffix-$PID"
```

该422项选择最终无未解决失败；不能表述成一次422项并行全绿，也没有重复整组。检查后只作上述路由修复及定点回归，再写本节。改动Python文件AST及 `git diff --check` 通过；当前运行环境未提供Ruff，未安装新工具。没有运行全仓QA或新CI。

本包全部为确定性传输／编译与行为替身、实际本地检索和原产品流程的工程验证，没有真实模型、产品Apply、真实Build、游戏、封存题或Cloud上传。已接通的是合法完整Findings不足后的现有源码补查；不自动修复未接受的需求投影／Findings格式，不新增metadata／IL调查，不扩大普通Build后Repair入口。真实业务质量仍待单独授权与判定。全包核对和部分Apply失败事实记录由原页继续负责，本包不把它们宣称完成。

## 7. 2026-09-13：可选 symbol／BM25 源码检索进入默认产品入口

本包在 `codex/indexed-source-provider` 从 `03225b37f5f9a5b2907d8eeb74ecc26c062c2486` 接续，先按原页交接只 cherry-pick 知识索引修复 `bb6b5eb936b7c9adbd937acaf205135d7fd5162b`，本树对应 `52a16b8fcf3e19dde56f373b03cd81aa2fabe9ae`。未使用旧 v1 索引运行产品事实，也未等待无关的 MCP 安装入口或 PDF collection 修复。

`run-request` 新增 `--source-retrieval indexed_source`；默认仍是 `rg_live`，Python 入口对应 `source_retrieval_mode`。模式写入原 manifest 与结果，不新增 Graph 或问答入口。`IndexedSourceEvidenceProvider` 是现有 `IncrementalIndexer`、`DeterministicEvidenceRetriever` 和活源物化的薄适配，复用真实 symbol／BM25 检索；没有接入 embedding、模型重排、PDF 问答或完整 Roslyn 平台。

初始需求检索与 A／B／C 的 Evidence 补查共用这一选定实例及 `collect_query_set` 接口。每次只索引当前隔离目标项目的 `.cs`，索引文件留在原任务 `a/source_index` 下。只接受 `bounded_source_chunks_v2`；扫描未完成、文件失败、查询/范围/源码版本失配时停止，不偷偷回退 `rg`。索引只定位，输出的原文、物理 hash、完整方法／字段 span 和成员信息仍由当前源码重建。共同物化代码从原 `rg_live` 抽出，未复制另一套声明解析器。

原 query_id、requirement_id 和全局 `max_items` 保留，不调用旧策略的额外标识符扩展与扩额。symbol／BM25 原分数和索引命中记录在 `per_query_execution.indexed_hits`，不与 `rg` 的固定分数未经校准相加。最终同一源码版本／范围的事实身份不随查询或检索通道改变；仍以 `can_generate_patch=False` 交给原完整 Findings，再进入原 Planning、worker、Review 和 Dry-run。

旧入口复现：新增模式未接入时，公开CLI精确用例因 `unrecognized arguments: --source-retrieval indexed_source` 失败，**1 failed，2.03s**，没有索引、模型或编译执行。接线首轮暴露 ArtifactStore 赋值前引用，已改用原确定的 `run_root/a` 路径，不提前改变 Store 生命周期。随后测试夹具的 Plan 引用路径与输出尾空格已按实际合同修正，没有放宽产品静态检查。

局部验证：原 `rg` **30 passed，2.59s**；新 provider **3 passed，1.90s**，覆盖 CRLF／跨80行索引窗口的完整方法、跨查询事实一致、原查询与全局上限及来源漂移拒绝。新产品选择集共6项：索引失败停止1项先通过，其余5项 `--lf` **5 passed / 1 deselected，29.50s**。initial／A／B／C 四路径均使用真实本地数据库和symbol／BM25；跟踪回归核对实际命中、源码字节、Plan依赖、原失败报告/检查、generation与传输数量以及原离线材料联查。

固定开发夹具中的中文查询实际暴露 `rg_live` 的 ASCII 取词边界；增强方案通过现有分词与BM25找到该方法，材料进入后续请求。此项证明这条具体输入及生产接线，不隔离证明BM25排序算法优于其他算法，不代表真实模型自主查询或总体质量提升。默认方案未切换。

唯一有界检查：

```powershell
$env:PYTHONUTF8='1'
python -B -m pytest tests/unit/test_indexed_source_evidence.py tests/unit/test_indexed_source_product_entry.py tests/unit/test_rg_live_evidence.py tests/unit/test_source_index_lifecycle.py tests/unit/test_mod_agent_cli.py tests/unit/test_product_execution.py tests/unit/test_upstream_product_trace.py tests/unit/test_patch_upstream_replanning.py tests/unit/test_patch_upstream_cli.py tests/unit/test_patch_upstream_unchanged_plan.py tests/unit/test_requirement_coverage.py tests/unit/test_run_request_external_worker.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\ixcp-$PID"
```

**429 passed，231.25s**，没有失败或补跑。源码和测试在检查期间未变化，之后只补本节。原主仓库已安装的 `.venv/Scripts/python.exe -B -m ruff check` 对本包七份Python文件执行 `--select E9,F63,F7,F821` 全部通过；`git diff --check` 通过。未安装新依赖、运行全仓或新CI。

本包使用确定性模型传输、基线编译／行为替身及真实本地检索，未运行真实模型、embedding、模型重排、Build、产品Apply、游戏或Cloud。下一项质量判断仍需固定源码／需求／模型／权限／预算与判定，分开索引构建和查询成本、必要材料召回和实际输入覆盖，再看原业务结果与人工帮助；小工程保留充分读取的简单对照。是否默认采用，必须由这种对照决定。First Shot 的独立单次回测与此包不互为前置，其结果由原页单独归档；本包不修改其恢复预算。

### 精确符号物化纠正

独立审阅在 `550029a` 复现：`HandleState audit`、`max_items=1` 的真实索引命中是 `symbol_exact/HandleState`，但命中的chunk包含调用方；物化器再次按词频排序，返回了含两次调用及audit文字的 `RunAudit`，丢掉了原声明。原429项没有覆盖这一信息替换。本页新增声明在调用方前／后的两个回归，修前均失败（**2 failed，1.08s**）。

`IndexedSourceEvidenceProvider` 现在复用数据库已有 `symbols_for_file` 声明记录，在当前文件hash、原chunk范围和源码行签名都匹配后，以已命中名称的精确声明行调用原活源物化器。精确符号不再与调用点重新竞争词频；BM25仍保留原文本定位。原事实身份、全局max_items、版本与权限校验不变，没有新建导航系统。对于原物化器尚不输出完整方法元数据的单行空方法，保留其已验证源码窗口；明确物化成不同方法则拒绝。

两个定点回归修后 **2 passed，0.67s**。唯一小范围检查选择原rg、provider和新产品入口41项，首轮 **36 passed / 5 failed，12.23s**；五项暴露新增后验校验误拒绝既有 `Load() {}` 源码窗口。保留原窗口行为后，只对五个失败入口 `--lf`，**5 passed / 1 deselected，36.84s**，再确认本P2两个回归 **2 passed，0.82s**。该41项选择最终无遗留失败，未重复429项。

```powershell
$env:PYTHONUTF8='1'
python -B -m pytest tests/unit/test_indexed_source_evidence.py::test_indexed_exact_symbol_keeps_declaration_when_caller_matches_more_terms -q --tb=short --basetemp="$env:TEMP\ixsym-old-$PID"
python -B -m pytest tests/unit/test_indexed_source_evidence.py::test_indexed_exact_symbol_keeps_declaration_when_caller_matches_more_terms -q --tb=short --basetemp="$env:TEMP\ixsym-fix-$PID"
python -B -m pytest tests/unit/test_indexed_source_evidence.py tests/unit/test_indexed_source_product_entry.py tests/unit/test_rg_live_evidence.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\ixsym-check-$PID"
python -B -m pytest tests/unit/test_indexed_source_product_entry.py --lf -q --tb=short --basetemp="$env:TEMP\ixsym-caller-$PID"
python -B -m pytest tests/unit/test_indexed_source_evidence.py::test_indexed_exact_symbol_keeps_declaration_when_caller_matches_more_terms -q --tb=short --basetemp="$env:TEMP\ixsym-final-$PID"
```

本次只改provider、对应测试与本记录；Ruff `E9,F63,F7,F821` 和diff检查通过。小检查后只作上述兼容修正和定点回归。没有模型、embedding、Build、产品Apply、游戏或Cloud操作；接线与总体质量收益仍分别验收。

## 8. 声明物化检查进入原追踪、分数和查询

接入前，原材料hash联查只能证明已经返回的片段被继续传递；即使选错了
`RunAudit`，也可能得到一致的交接记录。现在在第7节的原物化校验位置记录
`evidence.symbol_materialization`，保留原检查、异常和路由。每条本地
`symbol_check`绑定当前observation/trace身份、源码hash、原声明行/签名与实际
物化身份，另有canonical hash，Cloud映射仅保留哈希、行号、有限枚举和固定摘要。
名称、源码、签名和物理路径不进入Cloud载荷。

原`build_patch_live_scores`新增独立`indexed_symbol_declaration_match`：
本次明确一致为1，原校验明确错位为0；源码窗口无法确认、重载部分选择、BM25
及unknown均不评分。必须核对已执行检查、receipt hash和同一observation身份；
仅文件hash相等或仅方法名相等均不足。此分数只表示声明定位一致性，不表示相关性、
检索充分、业务行为或任务完成。原query关联该观察和分数，原本地journal联查返回
经过核验的检查记录JSON pointer，无新Artifact、Graph、CLI、数据库或评估后台。

真实临时本地索引正例，以及两种明确故障注入（不同方法、同名但错误声明位置）
验证了1/0结果；原生产predicate未被替换。另覆盖未确认/部分结果不评分、篡改、
敏感内容过滤、坏sink不改变原产品结果，以及既有OTLP和Score endpoint的离线传输。
聚焦12 passed，3.69秒。唯一小checkpoint67 passed，39.83秒，包含前述12项。

执行目录为本轮`independent_package_fixes_001`，使用主树已安装的`.venv/Scripts/python.exe`：

```powershell
python -B -m pytest tests/unit/test_symbol_materialization_trace.py -q --tb=short --basetemp="$env:TEMP\symbol-trace-$PID"
python -B -m pytest tests/unit/test_symbol_materialization_trace.py tests/unit/test_indexed_source_evidence.py tests/unit/test_indexed_source_product_entry.py tests/unit/test_patch_live_verification_scores.py tests/unit/test_patch_langfuse_query.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\symbol-trace-cp-$PID"
```

Ruff致命规则和diff检查通过。未重跑429项，未调用模型、embedding、Cloud、真实Build、
游戏或用户Mod Apply。上报/查回使用明确离线transport，不能宣称新Cloud验收或告警
配置已经完成；后续仅在获授权的真实任务中验证部署后的上传与查询。

与保存布局修复`dd43117`整合后，代码身份`1b13a93`补一组共同入口/追踪接缝检查：
`python -B -m pytest tests/unit/test_saved_apply_layout.py tests/unit/test_symbol_materialization_trace.py -q --tb=short -n 2 --dist=loadfile --basetemp=C:/Users/10160/AppData/Local/Temp/bound-integration-0913 -o cache_dir=C:/Users/10160/AppData/Local/Temp/bound-integration-cache`，
使用同一主树解释器并设置`PYTHONUTF8=1`，16 passed，12.97秒；未重跑两包的完整选择。

## 9. First Shot完整工具往返预算修复：工程验收

原真实运行`0bef5bc`的`13f25df8cff9e222f1a62d8afaee1505.json`仍保留
34,351 > 32,768的失败。新实现基于该执行版本开发，提交`6731a16`；
输入投影与修复分别整合为`c1ff3d2`、`9155a88`，没有第二次真实模型Actual。

先回放原首响应和绑定源码，复现5调用／3新窗口／2复用、原观察超限及第二请求未发送。
两个原假设经源码核对后需纠正：`model_payload_bytes`为展开视图诊断值，808/807的
引用本来就直接进入工具wire，不能据差额宣称线上重复展开；同adapter已有首响应token
校准，第二请求不必然沿首轮未校准代理，但该校准仍是启发式，非数学token上界。

实际重复发生在第5窗口1–124行与第1窗口51–179行。复用现有引用协议，新增
`excerpt_parts`按顺序组合新文字和先前完整正文的行区间；校验相同源码/快照身份、
连续范围和完整展开hash。只能引用仍在可见历史的完整正文，重复recipe不形成链。
所有调用仍保留独立结果，B0/Ck、绑定和原验收要求不删除。

整个只读batch在dispatch前检查结果预算；完整batch不能准入时逐call返回明确否定，
不把未供给材料当作成功，也不建议接口不支持的缩窗重试。连否定反馈也放不下时停止。
这里的`not_executed`仅表示未dispatch工具结果；准备阶段确实读取源码，不能报零物理IO。
历史消耗继续继承；resume下界同时参考已记录的模型/观察/读取累计值，压缩不退款。
已超额的旧34,351账本仍会在发送前被拒，不能以新编码换实例继续领取额度。

根页在干净代码`9155a88f69040953bea0a3c66e06fadff029a98b`再次完成原材料离线测量：

| 项目 | 新实现的实际回放结果 |
| --- | ---: |
| 既有恢复观察 | 17,657 bytes，保留 |
| 五个工具结果 | 5,387／4,647／808／807／2,611 bytes |
| 工具编码合计＋既有观察 | 14,260＋17,657＝31,917／32,768，剩851 |
| 第一完整HTTP请求体 | 45,042 bytes；原代理加4,096输出预留为49,138／49,152 |
| 第二完整HTTP请求体 | 60,977 bytes；纯字节代理加输出为65,073，超限 |
| 第二请求实际采用的原准入模式 | `same_model_observed_prompt_ratio_upper_bound_v1`，估计38,325，admitted |

五个完整结果均到达原生传输替身，分段展开与实际源码逐字相同。新工具协议说明改变了
首请求；保存的canonical请求还丢失原dict插入顺序，因此不声称wire SHA与旧Actual相同。
校准中的12,642输入tokens来自保存首响应fixture，不是新首请求或第二请求的新实测。
测试返回的第二回复为旧失败C1；loop完成不能算First Shot修复成功。当前剩851观察字节
也不证明足以容纳任意后续新失败，下一真实验收须核定完整预算和既有消耗，不运行中扩额。

原材料回放与两份完整请求在原目录的[整合回放结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/scratch/firstshot_tool_roundtrip_001/integrated_9155a88/final-metrics.json)；
驱动`replay_integrated_9155a88.py`显式核对代码根、旧journal与响应hash、原Artifact引用，
禁用socket连接，并写入新目录，不覆盖旧记录。独立的共享worker接缝测试使用自有marker
fixture，真实执行原生编码→解析/物化→原验证callback，核对所测文件/hash与第二回复一致，
然后通过原Review／Dry-run；判定为明确替身，Apply／Build／Runtime均0。

一次185项checkpoint为180 passed／5 failed，63.26秒。其中1项旧断言把未dispatch正文
计入新增准入字节，已改成保留prior并断言没有新准入/派发；4项在未改`0bef5bc`也失败，
原因是替身索取输入投影已移除的`source_excerpt`。替身现只读取实际提供的Ck引用，
不恢复生产重复正文、不改原行为断言，定向4 passed，23.30秒。该185选择无遗留失败，
不是一次185全绿；后加共享worker接缝1 passed，3.10秒。最后补累计read下界：
已有1次＋本段3次却传3的红例1 failed，1.87秒；修后传3拒绝、传4继续，1 passed，1.33秒。
新文件最终14项与相关预算6项共20 passed，3.64秒，未重跑已通过180项。

独立树`firstshot_tool_roundtrip_001`使用主树`.venv/Scripts/python.exe`、`PYTHONUTF8=1`：

```powershell
python -B -m pytest tests/unit/test_patch_tool_roundtrip_budget.py tests/unit/test_patch_source_coverage_reuse.py tests/unit/test_patch_excerpt_references.py tests/unit/test_patch_agent_loop.py tests/unit/test_repair_input_projection.py tests/unit/test_continuous_behavior_repair.py tests/unit/test_patch_behavior_feedback.py tests/unit/test_external_patch.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\rtcp-$PID"
python -B -m pytest tests/unit/test_external_patch.py::test_external_qwen_reuses_source_feedback_revision_and_original_review_without_ollama_identity tests/unit/test_external_patch.py::test_json_mode_does_not_extract_patch_from_prose_and_retains_exact_response tests/unit/test_continuous_behavior_repair.py::test_initial_repair_context_renders_the_exact_failed_materialization -q --tb=short --basetemp="$env:TEMP\rtfix4-$PID"
python -B -m pytest tests/unit/test_patch_tool_roundtrip_budget.py tests/unit/test_patch_source_coverage_reuse.py::test_resume_cost_floor_uses_new_windows_and_planning_helper_matches_actual_encoding tests/unit/test_patch_source_coverage_reuse.py::test_new_failure_segment_can_recheck_the_same_reference_without_resetting_budget tests/unit/test_patch_source_coverage_reuse.py::test_new_window_budget_exhaustion_keeps_reference_tool_available tests/unit/test_patch_source_coverage_reuse.py::test_visible_reference_still_costs_bytes_and_snapshot_drift_blocks tests/unit/test_patch_source_coverage_reuse.py::test_007_shape_reuses_complete_visible_windows_in_initial_and_failure_rounds -q --tb=short --basetemp="$env:TEMP\rtrcp-$PID"
```

与检索和保存Apply整合后的`9155a88`在`independent_package_fixes_001`执行：

```powershell
python -B -m pytest tests/unit/test_patch_tool_roundtrip_budget.py tests/unit/test_repair_input_projection.py tests/unit/test_indexed_source_product_entry.py tests/unit/test_saved_apply_layout.py -q --tb=short -n 2 --dist=loadfile --basetemp=C:/Users/10160/AppData/Local/Temp/roundtrip-integrated -o cache_dir=C:/Users/10160/AppData/Local/Temp/roundtrip-integrated-cache
```

41 passed，38.83秒。Ruff致命规则和diff检查通过。原始pytest结果仅在工具输出中，
未把测试数当任务数。本包没有真实模型、Cloud、Embedding、游戏、真实Build或用户Mod Apply。
