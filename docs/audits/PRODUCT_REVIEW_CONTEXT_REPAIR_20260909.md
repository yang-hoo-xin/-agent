# Product Review 上下文与 CLI 输出修复

基线：`7faf3a32c44606b166549638d94b35758d7e6b90`。
独立工作分支：`codex/fix-product-review-context`。未修改主树 WIP、旧 Actual、native 提示或模型调用预留逻辑；本轮不推送主线。

## 问题与修改

`nlcfg_002` 从自然需求产生的首版代码已通过原完整编译和配置5/5，但 Proposal 的12条引用对应6402字符。产品Graph沿用builder默认6000，仅装入10段，旧Reviewer因覆盖缺失和两条预算遗漏而阻断。这属于本地审阅资料装配问题，不能与推理请求的上下文准入合并归因。

Fresh 入口已有按当前Plan引用计算精确字符量的算法。本轮将同一算法提取为 `PatchProposalBuilder.required_source_snippet_char_limit`，原Fresh函数委托它；Product Graph在生成Proposal时针对当前Plan/Evidence调用该算法。其余直接Graph/Builder调用者显式给定的限额仍生效。

- 保留全部原引用、完整原excerpt和字符计量单位；不按本任务名称特判、不删除引用、不增加模型额度。
- 未引用的数据不计入所需量，缺失excerpt仍由原校验阻断。
- Reviewer、权限和Approval合同未修改。产品Graph的初始及适用行为修订分支都使用当前资料。
- 旧6000默认仍保留给原有显式／普通调用路径；产品内部自动计算与外部改写Graph控制参数分开。
- CLI另在入口把可重配置的stdout/stderr统一为UTF-8；不删除U+FEFF、不改JSON内容、不替换StringIO、不改变stdin或退出判定。

## 原始失败与无模型离线复验

原始Proposal `c4598f87cfbab91a243a83f1566d29942d76c927a375c7b8743b9d7b3f8ca4a6` 保持不变。先直接交原Reviewer，精确复现三条 `context_pack` 阻断。

修后仅在内存按原生产装配形式组合Plan与已保存的生成改动，使用原上游引用及原domain policy调用builder。它不是新Plan Artifact，也未借用旧Proposal的Artifact身份：

- 除 `context_pack` 外，新旧Proposal对象的所有字段完全相同。
- 12段全文均保留，实际字符量及限额均为6402，没有截断或遗漏。
- 同一原domain policy重审旧对象，findings逐项等于历史Review；重审完整新对象为 `approve_dry_run`。
- 原 `ExactTextPatchApplier.run(allow_write=False)` 无写入Dry-run通过。
- 物化后的配置源码SHA仍为 `c2f18b4251835d28bda2f2752fc6a25f05728e92a8810ac38c6b1a7ba146f9ba`，与旧实际编译输入相同。
- 原Artifact及工作区源字节前后相同，0模型调用、0编译、0 Product Artifact写入。

最终离线收据：[original-code-context-replay.json](C:/Users/10160/.codex/visualizations/2026/09/08/01a07fb9-9dfe-7a20-a345-de16b4ab1892/review_context_fix_evidence_001/original-code-context-replay.json)，SHA `89a1021d0bc33dd12c2a7d382e7abeffb6a6fc58878f288a818f01b41d8c2c0d`。原红记录同目录 `original-review-red.json` 保留；更早未显式带domain policy的局部绿记录不作为最终准入依据。

## 公开续接边界

**现有入口不能把本次失败Review无模型续成新的Proposal／Review／Dry-run。**

缺失片段已持久化在旧Proposal里，重审它不会重新运行builder；`proposal_review_context_factory`也只能提供Plan/Evidence。需要原owner为同一代码创建完整context的新Proposal revision，但目前没有保存响应到该owner的公开恢复入口。

现有 `review_run` 要求Proposal/Review/Dry-run三件齐全；`resume_deferred_approval`需要原dry_run_apply checkpoint；`continue_reviewed_patch`需要Apply checkpoint。本次均不满足。Fresh初始路径需要模型factory，Repair路径要求原Review允许Dry-run，frozen-native恢复的是待发送请求，同attempt重入读取已有终态；这些都不是本次保存响应的无模型重装配入口。

因此上述通过是**离线域对象回归**，不是公开入口续接成功或旧run改判。未挂假生成factory、未人工改Graph状态或旧Artifact、未绕过预算和批准。原任务仍累计7/14、余7；Projection/Findings余额已用完，未重启自然语言入口。

## 聚焦与检查点

- Product上下文新回归：旧代码2 failed/1 passed；修后4 passed，2.16s。通过真实Product Graph和原Review/Dry-run到待批准；源码字节不变，Apply/Build/Runtime均未发生。包括多引用、Unicode字符计数、显式小限额、缺失／未引用证据。
- CLI冷进程：原GBK/ASCII失败4项；修后6 passed，12.75s。独立CLI检查点41 passed，12.33s。
- 联合选择217项：首次213 passed/4 failed，93.98s。四项Reviewer正例在修复树串行仍4 failed（0.83s），未改7faf也同样4 failed（1.07s）；原因是旧fixture的source_hash与file_hash相互矛盾，binding也缺对应源身份。只修既有fixture的这两处身份数据，不改生产判定或断言。原4节点随后4 passed（0.62s）；共享fixture影响的Review全文件与新上下文文件共38 passed（3.52s）。未再完整重跑217项；这次选择没有剩余未解决失败。
- 变动文件Ruff致命项及 `git diff --check` 已通过；未宣称全仓或托管CI通过。

准确命令（cwd为本地输出根的 `review_context_fix_001`）：

```powershell
$reviewPython = 'C:/Users/10160/.codex/visualizations/2026/08/11/019ff15f-9eac-7b13-aad5-faffde4b36b7/rag_capability_mainline/.venv/Scripts/python.exe'
& $reviewPython -B -m pytest tests/unit/test_product_proposal_context_budget.py -q --tb=short --basetemp=C:/Users/10160/AppData/Local/Temp/revctx-green2-0909
& $reviewPython -B -m pytest tests/unit/test_cli_unicode_output.py -q --tb=short --basetemp="$env:TEMP\cli-utf8-green-$PID" -o cache_dir=.pytest-cli-unicode
& $reviewPython -B -m pytest tests/unit/test_cli_unicode_output.py tests/unit/test_verification_operation_cli_adapter.py tests/unit/test_mod_agent_cli.py::test_cli_plan_request_prints_planning_only_json tests/unit/test_mod_agent_cli.py::test_cli_plan_request_preserves_true_config_only_route tests/unit/test_mod_agent_cli.py::test_cli_confirmed_apply_is_blocked tests/unit/test_mod_agent_cli.py::test_cli_run_request_forwards_precomputed_targets_but_rejects_legacy_summary tests/unit/test_mod_agent_cli.py::test_cli_displays_exact_structured_human_semantic_decision_contract -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\cli-utf8-cp-$PID" -o cache_dir=.pytest-cli-unicode
& $reviewPython -B -m pytest tests/unit/test_product_proposal_context_budget.py tests/unit/test_proposal_review.py tests/unit/test_fresh_planning_continuation.py tests/unit/test_product_execution.py tests/unit/test_deferred_product_approval.py tests/unit/test_run_request_shared_worker.py tests/unit/test_cli_unicode_output.py tests/unit/test_workflow_graph.py::test_graph_forwards_explicit_proposal_source_snippet_char_limit tests/unit/test_workflow_graph.py::test_proposal_source_snippet_char_limit_must_be_positive -q --tb=short -n 2 --dist=loadfile --basetemp=C:/Users/10160/AppData/Local/Temp/revctx-cp-0909 --junitxml=C:/Users/10160/.codex/visualizations/2026/09/08/01a07fb9-9dfe-7a20-a345-de16b4ab1892/review_context_fix_evidence_001/checkpoint.xml
& $reviewPython -B -m pytest tests/unit/test_proposal_review.py::test_reviewer_approves_evidence_bound_dry_run_proposal tests/unit/test_proposal_review.py::test_reviewer_allows_mixed_evidence_without_edit_binding_for_every_ref tests/unit/test_proposal_review.py::test_reviewer_approves_selected_hook_target_binding tests/unit/test_proposal_review.py::test_proposal_payloads_validate_against_artifact_contract -q --tb=short --basetemp="$env:TEMP\review4-green-$PID" -o cache_dir=.pytest-review4
& $reviewPython -B -m pytest tests/unit/test_proposal_review.py tests/unit/test_product_proposal_context_budget.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\review4-cp-$PID" -o cache_dir=.pytest-review4
```
