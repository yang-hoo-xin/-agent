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

