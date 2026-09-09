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
