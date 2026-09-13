# 保存 Patch 的正式无模型续接

基线：`fcccb3eaa67369deeea90151a5c7c114f586418f`。本次用户明确授权补充既有续接表面，以原 `nlcfg_002` 已保存、已通过配置检查的模型修改重新进入 Proposal／Review／Dry-run。此前不新增入口的限制已由这次指令替代。

## 入口与执行边界

复用 `continue-fresh-patch`，新增 `--reassemble-saved-patch <selection.json>`。保留原 Artifact root、workspace、feature、三份原 Artifact 的 path/hash 参数，必须提供 `--attempt-id`。选择文件严格只有：

```json
{
  "source_attempt_ref": {"path": "原journal绝对路径", "sha256": "原文件SHA256"},
  "logical_budget_ref": {"path": "原逻辑预算回执绝对路径", "sha256": "原文件SHA256"}
}
```

## 公开无模型 Actual

代码固定在 `e27595cd208ec1a0a2fed12009bec499dc30a5bf` 后，实际执行上述公开模式（attempt `nlcfg_002_saved_review_001`），2026-09-09 19:20:32–19:20:37 +08，退出0。新Proposal、Review、Dry-run和新journal均由原Graph／Store独立持久化；公开结果为 `awaiting_exact_diff_approval` 并显示真实diff。

本次计数为模型0、Planning0、Proposal重装配1、Review1、Dry-run1、Apply/Build/Runtime0，没有新generation观察或旧编译／配置重执行。原不可变Artifact、旧journal、原manifest/result与13份规范源文件hash均保持；Feature/Evidence/Plan修订数未增加。逻辑预算仍14已用7余7，各stage合计一致。

精确diff哈希：`sha256:b58f3ead136e6cdbb4cd77b3d5a2d8b52b3a00e6b86e101a51f512cd1e22fe2e`。历史验证仅绑定复核，不变成新执行或新评分；旧 `nlcfg_002` 仍为Review阻断，新的续接结果单列。

[实际验收收据](C:/Users/10160/.codex/visualizations/2026/09/08/01a07fb9-9dfe-7a20-a345-de16b4ab1892/joint_configuration_saved_review_001/acceptance-receipt.json) SHA `6095151a48ccef562176deb043066a561376ab3bd4a569381adc1556e0313ada`，同目录保留准确argv、公开stdout、进程回执与 `review.diff`。没有创建批准，下一步仍须用户对新diff进行精确批准。

上述示意中的说明文字不是可执行引用。模型profile、worker执行配置、上游重评和Repair参数与本模式互斥。原 `PatchContinuationInputV1` 增加可选实例字段，未新建 Artifact 类型、Plan 或批准合同。

实际路径仍是原StateGraph的：

`START → generate_patch_proposal → review_proposal → dry_run_apply → END`

保存模式在START与Proposal节点重验准入；生成节点直接消费经准入的原响应物化结果，不调用 Patch factory、模型或人工 `graph.update_state`。原 builder 重新装配完整上下文，原 Reviewer 仍要求 executable patch，原 applier 仅执行无写入 Dry-run。

原Store在workspace内的Product布局复用既有允许规则；仍禁止workspace位于Store内、任何目标源码落入Store。普通Fresh根规则不变。

## 准入与历史证据

- 原三refs按不可变修订、完整祖先、Feature语义、当前Plan绑定和live source重验，不把latest别名当授权。
- 原journal、terminal、原Proposal／Review、完整保存response及其生成元数据必须互相绑定。
- 原response重新经过既有native parser／Plan overlay／materializer，区分native changes、附生成元数据后的changes及Proposal投影三种hash，最终代码必须与原Proposal和原被测代码一致。
- 旧Review及当前原Reviewer的blocking规则必须只有结构化 `context_pack`；不是根据报错关键词放行。
- 当前范围只支持原Product `run-request` GTFO owner，以及现有完整编译＋真实configuration报告形状。报告、代码、DLL、source inputs、依赖和probe引用逐一复核。历史验证标记 `historical_binding_revalidated`，新编译／验证执行为0，不产生新行为分。
- 预算回执仅作完整性输入，与父Product typed结果、原journal、前次结果及阶段消耗交叉核对。逻辑总账与阶段累计保持同一口径；本次新增额度和provider sends均为0。
- 原不可变r文件及旧journal不改；新Proposal绑定原Feature／Plan／Evidence与旧Proposal／Review，新Review／Dry-run独立写入。Store按原机制推进latest别名。
- 新journal保留原逻辑request_id及来源、历史验证和预算，记录本次物化／Review／Dry-run。旧factory receipt、generation及旧编译不复制为新执行。
- 同attempt及相同输入读取原终态；输入漂移、无终态的已占用attempt不重执行或覆盖。公开结果复用 `review_run` 展示新diff与来源，仍等待精确批准。

## 验证

Graph最小旧反例先因旧1–5模型额度规则失败；保存分支通过原Graph、Reviewer和真实no-write applier。Graph交叉21项通过（10.22s）。严格准入12项通过（14.38s），涵盖原响应／源码／报告／依赖漂移、父结果、原14→12余额交接、累计14用7余7及各阶段相等、旧及当前非context阻断等。CLI／runner12项通过（2.31s），覆盖互斥参数、0模型、diff展示、原逻辑任务、独立journal及幂等。

唯一联合检查点 **202 passed，103.02s**；变动Python致命规则和diff检查通过。所有工程验证未调用真实模型或编译器。Graph测试只替换来源准入边界，完整准入由独立测试及原资料只读预检覆盖；公开无模型Actual在固定提交后单列，不把这些fixture运行记作实际产品续接。

解释器为原主仓库 `.venv/Scripts/python.exe`，cwd为独立 `saved_patch_resume_001`。联合命令：

```powershell
$pythonSaved = 'C:/Users/10160/.codex/visualizations/2026/08/11/019ff15f-9eac-7b13-aad5-faffde4b36b7/rag_capability_mainline/.venv/Scripts/python.exe'
& $pythonSaved -B -m pytest tests/unit/test_saved_patch_admission.py tests/unit/test_saved_patch_graph.py tests/unit/test_saved_patch_cli.py tests/unit/test_fresh_planning_continuation.py tests/unit/test_patch_upstream_budget.py tests/unit/test_patch_upstream_unchanged_plan.py tests/unit/test_reviewed_patch_continuation.py tests/unit/test_reviewed_patch_cli.py tests/unit/test_product_patch_journal.py tests/unit/test_product_execution_query.py tests/unit/test_patch_execution_index.py tests/unit/test_cli_unicode_output.py -q --tb=short -n 2 --dist=loadfile --basetemp=C:/Users/10160/AppData/Local/Temp/saved-cp-0909 --junitxml=C:/Users/10160/.codex/visualizations/2026/09/08/01a07fb9-9dfe-7a20-a345-de16b4ab1892/saved-resume-checkpoint.xml
```

## 2026-09-13：部分写入失败事实及续接边界

本次基线 `dbe18ae89ec53b0c40db206027d346e489757249`，独立分支
`codex/partial-apply-failure`。先用两份临时源码、原 Applier Dry-run
及其精确批准hash复现：第一文件确实被修改，第二次替换抛错，原异常没有
目标写入事实。另在原 Graph 节点及条件边复现写入结果被记成False：
1项失败，1.59秒。原审批和修改范围规则未放宽。

Applier现在保留原异常类型/实例，附带已测量的 `patch_apply_failure`。
每目标记录原/预期/实际读取hash、替换是否正常返回以及当前字节状态。
`actual_write_performed=True`表示至少一次目标替换已确认；False仅用于
确认没有目标替换；没有确认且替换结果不明时保留None。`changed_files`
只列正常返回的替换，其他目标的未知状态仍在逐文件观察中。
`real_patch_applied`只有全部目标替换完成且读取字节匹配时才True；即使目标
全部写成后仅清理失败，Graph仍是failed/blocked，不能进入Build或生成续接批准。

Graph不再将未知factory异常或部分写入硬编码为零写入。Apply已返回、而
ArtifactStore保存结果失败时，逃逸异常仍携带已确认目标事实。任务汇总对
所有已回查Apply结果保留三态，存在调用而缺结果时不填False；异常终态文件、
manifest及公开reviewed续接结果也保留写入明细。已核查的saved-output准入、
无blocker完成条件、源码快照及重复消费检查继续阻止错误续行；未发现原False
直接触发自动清理/重放的现有消费者，不宣称曾经发生数据损坏。

定向验证：9项Applier/Graph故障场景通过，1.63秒。结果投影首次9通过、2失败
（7.79秒）：新测试误将已有domain_blocked退出码写为2，读原CLI确认应为1后
修正测试；两项公开入口和新增收据保存故障场景共3项通过，10.12秒。公开入口
使用原Graph/Store与真实临时文件，模型、编译为明确替身，无真实Mod Apply。

唯一有界检查点选择372项，结果371通过/1失败，112.42秒。失败是旧批准续接
测试把新增 `workflow.route` 的 `workflow_node` 当作已执行节点；串行在本分支
及未改基线各复现1失败（3.71秒、3.99秒）。仅修正该测试区分路线与节点，并
显式检查Review到Dry-run路线，定向1通过，2.41秒；未重跑已通过371项。
该选择最终无未解决失败，不声称一次372项全绿。改动Python的
Ruff `E9,F63,F7,F821`及diff检查通过。

```powershell
$env:PYTHONUTF8='1'
python -m pytest -q -n 2 --dist=loadfile --basetemp C:/Users/10160/AppData/Local/Temp/partial-final -o cache_dir=C:/Users/10160/AppData/Local/Temp/partial-cache tests/unit/test_partial_apply_failure.py tests/unit/test_apply_failure_projection.py tests/unit/test_patch_apply.py tests/unit/test_local_entry.py tests/unit/test_reviewed_patch_continuation.py tests/unit/test_reviewed_patch_cli.py tests/unit/test_deferred_product_approval.py tests/unit/test_product_execution.py
python -m pytest -q tests/unit/test_reviewed_patch_continuation.py::test_reviewed_diff_explicit_approval_reaches_original_graph_apply_and_stops_before_build --basetemp C:/Users/10160/AppData/Local/Temp/partial-route-fixed -o cache_dir=C:/Users/10160/AppData/Local/Temp/partial-cache
```

这解决的是可捕获异常时的事实表达及不误推进；没有跨文件事务、自动回滚、
任意强杀恢复或并发exactly-once保证。未调用真实模型、编译器、游戏或Cloud，
没有对用户Mod执行Apply。历史配置任务的精确批准及后续交付状态不改变。

包级复核随后发现两个批准CLI异常出口仍丢弃异常已携带的写入明细。已让
`apply-patch --resume-approval`和`--human-decision-stdin`复用同一失败投影，
原退出码/blocked语义保持；2项定向出口测试通过，1.18秒：
`python -m pytest -q tests/unit/test_apply_failure_projection.py::test_approval_cli_exception_preserves_confirmed_files --basetemp C:/Users/10160/AppData/Local/Temp/partial-cli -o cache_dir=C:/Users/10160/AppData/Local/Temp/partial-cache`。
未因这次窄改重跑已通过的372项选择；新增CLI与测试Ruff通过。

与首次Findings补查 `bf280231` 合并后的代码为
`51b7b71a6781765af1da2dfb8918dcb3cce39712`。两线共同触及的公开入口、
追踪及失败/批准路径共35项通过，45.38秒；全部变动Python Ruff通过：

```powershell
$env:PYTHONUTF8='1'
python -m pytest -q --basetemp C:/Users/10160/AppData/Local/Temp/all-pack-integration -o cache_dir=C:/Users/10160/AppData/Local/Temp/partial-cache tests/unit/test_mod_agent_cli.py::test_cli_run_request_initial_findings_gap_searches_before_first_plan_and_patch tests/unit/test_mod_agent_cli.py::test_cli_run_request_initial_findings_gap_stops_without_first_plan_or_patch tests/unit/test_upstream_product_trace.py tests/unit/test_partial_apply_failure.py tests/unit/test_apply_failure_projection.py tests/unit/test_reviewed_patch_continuation.py::test_reviewed_diff_explicit_approval_reaches_original_graph_apply_and_stops_before_build
```

生产代码在该检查后未变，之后仅补记本记录和当前合同。

## 2026-09-13：保存布局贯穿批准后隔离 Apply

在 `03225b3` 的独立 `saved_apply_layout_001` 树，用临时Product布局
（Store位于workspace下）、真实ArtifactStore／ProductJournal、保存准入、
原Graph、Review／Dry-run及精确批准，复现了两个工程接缝：

1. 已合法完成保存产物重组，`prepare_reviewed_patch_apply`仍在
   `_apply_inputs`丢掉保存来源语义，抛`PATCH_CONTINUATION_ROOTS_OVERLAP`：
   1 failed，4.10秒。
2. 接回保存来源后，原全目录复制把Store也复制进隔离源码。Graph写回业务记录
   使完整workspace快照变化，导致隔离代码已经写入、`blockers=[]`且下一节点为
   Build，却返回blocked和`source_workspace_written=True`：1 failed，4.93秒。

`reviewed_patch_continuation.py`现在从已核验journal的原
`saved_patch.source_attempt_ref`和`logical_budget.logical_budget_ref`重新执行
保存准入，并比较保存修改与当前Proposal的`diff_intent`；没有伪造来源选择。
只有经过该准入的保存布局，才把已验证Store的精确相对路径绑定进原显示批准数据。
同一范围用于原源码快照、隔离复制、写前/写后核对及后续checkpoint的来源复验。
普通Fresh根隔离未放宽，不按`a`等目录名泛排，也不让目标源码位于Store中。

测试的上游模型和编译收据为明确替身；本节不声称重新从自然语言产生真实模型修改。
保存后的准入、Graph、审批与Applier使用生产实现，临时文件有实际写入。
最终4项核对隔离C#字节、Store未复制、原源码未变及已保存批准hash；源码漂移、
错误批准在复制和写入前拒绝，普通Fresh仍拒绝原重叠布局：4 passed，9.95秒。

唯一相关checkpoint在上述独立目录执行，解释器为原主树`.venv/Scripts/python.exe`：

```powershell
$env:PYTHONUTF8='1'
python -B -m pytest tests/unit/test_saved_apply_layout.py -q --tb=short --basetemp="$env:TEMP\sal6"
python -B -m pytest tests/unit/test_saved_apply_layout.py tests/unit/test_saved_patch_admission.py tests/unit/test_saved_patch_graph.py tests/unit/test_saved_patch_cli.py tests/unit/test_reviewed_patch_continuation.py tests/unit/test_reviewed_patch_cli.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\sac"
```

第一条是较早的2项正例/普通Fresh负例检查（2 passed，5.85秒），随后补齐上述
4项必要断言；第二条最终74 passed，45.85秒。Ruff致命规则及diff检查通过。
结果来自本任务工具输出，未生成独立JUnit或把临时目录当作测试报告。

该修复只证明临时保存布局的工程贯穿。真实`nlcfg_002`仍先受原目标文件缺失阻断：
本次没有恢复这些文件、改写历史refs、调用模型或Cloud、执行真实Build、游戏或用户Mod Apply。
