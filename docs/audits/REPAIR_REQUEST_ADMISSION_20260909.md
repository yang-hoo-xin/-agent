# 2026-09-09 真实运行触发的请求准入修复

本轮由用户明确执行旧分页、嵌套快照、Findings及FirstShot验证，并要求实测问题触发修复。原运行固定 `7faf3a32c44606b166549638d94b35758d7e6b90`，原记录及执行树不改。两个工程缺口分别有原始阻断记录，没有将它们归为模型修码失败。

## 分页：首请求的保守字节门槛

新分页attempt的首个worker调用被provider发送前的准入检查拒绝：HTTP body的UTF-8代理值13,710，加4,096输出额度为17,806，超过原16,384配置。已预留一次worker调用，但没有开始native模型发送；后续本题仅安排最多四次新增调用，不退款或重领五次。

原始结果位于输出根 `scratch/repair_actual_7faf_001/owned/paging_partial_tail/attempt/actual/summary.json`，SHA-256 `bad4bdd95b7517132802fd408fd9b8411d499424c2111933c25a90113f114465`。该代理不是已测得的native token数量，不能据此宣称模型实际token超窗。

修复只精简native固定规则、source工具说明及重复inspection尾句。任务、B0、C1、F1、完整工作视图、工具参数、schema、模型/输出/观察额度和原准入检查均不变；两条legacy提示的原字节哈希保持。逐条语义核对保存于输出根 `scratch/repair_native_context_001/validation/RULE_PRESERVATION.md`。这是规则文字去重改写，不是原提示的逐字可逆编码。

实际保留请求的离线重放：原13,710被拒；新真实PreparedNative渲染12,273，加4,096为16,369，原gate放行且本地fake sender仅一次。只证明该输入可被准入，余量15字节不代表其他输入均可通过；没有网络/模型调用或编造校准值。精确证据是同目录 `final-reviewed-green.json`。

## FirstShot：已有Repair上下文被重复预留

新FirstShot初次尝试在模型调用前停止，原journal模型调用数0。C1/F1及当前代码视图实际消费26,737字节，最大注册源码窗5,789；旧fresh初稿规则又预留26,737+5,789=32,526，致使32,768总额仅剩242可供当前上下文准入，错误地挡住首发。

已绑定并获准的Repair现在不再使用fresh初稿预留；当前消息仍计26,737，硬上限32,768不变，fresh生成及真正超额的停止行为不变。修复是已有Repair阶段与fresh阶段的区分，不是扩张预算。

实际材料无模型预检仍暴露下一独立门槛：新的首请求body59,605，加4,096后为63,701，超过原49,152保守代理门槛。此处尚未解决；不能因重复预留的回归通过就宣布FirstShot已可实际首发或模型已修好。证据为输出根 `scratch/repair_native_context_001/firstshot-request-preview-001/summary.json`，SHA-256 `38e33fea1a9da46f17bda600e106665f8ca20a018144b540bfa475071ef1463b`。

旧C1只用于验证器准备：完整项目编译、13项配置、原36项分别实际执行；原行为仍33/36。旧临时B0副本缺失已按原checker重新建立基线；旧matrix输出范围限制通过修正新配置实例解决，没有修改原矩阵或原输出。

## 验证

使用已有仓库虚拟环境，短系统临时目录，全部模型传输为明确替身：

- native文字：私有旧请求红→绿；公开10项通过（4.86s）；native/codegen/loop/引用/CLI/adapter一次218项checkpoint通过（20.23s）。
- Repair预留：2红→2绿，另2边界保持；相邻Repair一次31项checkpoint通过（23.84s）。
- 合并两改动后：46项checkpoint首次45通过/1失败（50.25s）。失败测试以固定失败Repair冒充fresh初稿，仍期待fresh预留。改为明确fresh输入保留旧预留断言，并增加已有Repair可以纠正格式的相反场景；仅这两项复跑通过（4.50s），没有改生产逻辑绕过失败。

主要命令（两次checkpoint选择存在重叠，不相加作独立任务数）：

```powershell
python -B -m pytest tests/unit/test_native_patch_rule_context.py tests/unit/test_patch_code_generator.py tests/unit/test_patch_agent_loop.py tests/unit/test_patch_excerpt_references.py tests/unit/test_patch_tool_effects_cli.py tests/unit/test_agent_turn_adapters.py -q --tb=short -n 2 --dist=loadfile
python -B -m pytest tests/unit/test_initial_repair_reservation.py tests/unit/test_patch_repair_continuation.py tests/unit/test_patch_recovery_worker.py -q --tb=short -n 2 --dist=loadfile
python -X utf8 -B -m pytest tests/unit/test_initial_repair_reservation.py tests/unit/test_native_patch_rule_context.py tests/unit/test_continuous_behavior_repair.py tests/unit/test_patch_submission_cli.py tests/unit/test_patch_upstream_unchanged_plan.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\native-merged-0909"
python -X utf8 -B -m pytest tests/unit/test_patch_submission_cli.py::test_format_correction_cannot_spend_model_turns_reserved_for_behavior_repair tests/unit/test_patch_submission_cli.py::test_bound_repair_can_correct_format_without_a_second_fresh_reservation -q --tb=short --basetemp="$env:TEMP\native-followup-0909"
```

这些工程结果不替代新模型验收；后续分页与快照使用新的固定源码/实例，原失败完整保留。FirstShot的第二层输入表示门槛继续作为明确未完成项。
