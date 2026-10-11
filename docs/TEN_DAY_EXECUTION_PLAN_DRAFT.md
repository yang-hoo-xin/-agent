# 十天核心纵向闭环与证据化作品交付计划（战术页，待审核）

```yaml
document_role: sole_daily_execution_plan
status: draft_for_user_review
implementation_authorization: not_granted
baseline_head: d263ed983c3cede7165273e0158e4641c4dbeaaf
decision_record: docs/TEN_DAY_ENGINEERING_MATURITY_DECISION_RECORD_DRAFT.md
fallback_outcome: honest_degraded_portfolio_delivery
core_target: one_real_vertical_objective_required_acceptance_trace_ci
stretch_target: repair_broader_eval_public_alpha
proposed_goal_tiering_change: true
proposed_selected_ten_day_target: core_target
requires_user_approval: true
full_maturity_stretch_budgeted: false
```

> 本文件是每天唯一读取的十天计划。完整目标、三个 txt、九项、五项和所有保留/改变/新增/舍弃/延期理由在 decision record；日常不重读它。

## 1. 十天结果分层

| 层级 | 十天结束条件 |
| --- | --- |
| Fallback | `honest_degraded_portfolio_delivery`：当前真实进展、first failure、有效测试/CI、限制和未证明项可复现；它不是目标达成，只是失败后仍可诚实交付的材料 |
| Core target | 一个真实 Issue 经过 `Evidence→Plan→Patch→Dry-run→Approval→Apply→Build/Test→objective→acceptance-required verification`；另有一个正确停止；绑定 owner Trace、clean environment 和远端 CI |
| Full-maturity Stretch | 原九项/三个 txt 的更高完成标准，包含真实 Different Repair→Revalidation、更广 Eval 和条件 public alpha；本战术页没有为它分配十天预算 |

本页提出选择 Core target。把 Repair 和更广 Eval 移出 Core 是对原九项目标硬度的实质改版，必须由用户审核；若仍要求 Full-maturity 作为十天硬目标，需要重新排程，不能假装当前预算可执行。主任务自然发生且完整闭合的 Repair 可以计入更高证据；主任务没有 Repair 时，只有既有真实失败 checkpoint 才能补，不制造失败。PDF、完整宏观图和正式模型比较完全退出十天执行队列。

Day 10 的项目认知声明固定为：active route `demonstrated`，相邻能力 `partially_mapped`，whole repository `not_demonstrated`。不能同时延期完整 project intelligence 又声称掌握全仓点线面。

## 2. 执行方式

- 用户一次采纳当日工作包后，Codex 在 write allowlist 内连续读、改、测、修、复核；普通技术选择不逐步请示。
- 宽认知、窄权限：允许多个假设和只读调查；外部披露、不可逆操作、产品 exact diff、游戏运行和目标变更仍需用户决定。
- 一个 integration writer；只读 explorer 可并行。独立写任务只有路径、状态和外部资源完全独立时才用 worktree，最终串行集成。
- 产品 Actual/Ollama/游戏 Runtime 使用同一机器资源时，优先级固定：主产品 Actual→Build/Runtime→Repair→关键 Eval→实验；低优先级不抢占。
- 每次只修当前 first failure。可选 Hook、宏观投影、telemetry、文档或指标失败不阻断产品。
- 只自动记录四个提速数据：总墙钟、first-failure 定位时间、完整重跑次数、checkpoint 测试耗时；其余指标 Day 11+ 再扩。不同任务间只报告 observed signals，不宣称工具造成某个百分比的因果提速。

## 3. Gate 预算，不按日历机械停顿

| Gate | 最大预算 | 唯一结果 |
| --- | ---: | --- |
| G0 Eligibility | 0.5 天 | 唯一任务、objective command、acceptance/Runtime、权限窗口、远端 CI 可用性；只读检查是否已有真实 Repair checkpoint |
| G1 Evidence/Profile | 2 天 | Fresh exact refs 可被 Planning 消费；一次真实 Fresh 得到 EvidencePack 或精确 first failure；Patch profile 技术/业务 go-no-go |
| G2 Patch/Objective | 2 天 | Plan→Patch→Review→Dry-run→一个 exact approval→isolated Apply→Build/Test→objective |
| G3 Acceptance/Trace | 1.5 天 | acceptance-required Runtime/verification、环境恢复和现有 owner-bound Trace；主任务失败时完成其必要 Repair，若完整闭合则同时形成更高 Repair 证据 |
| G4 Eval/CI/Rehearsal | 2 天 | 4～6 个最小 Case（必须含一个正确停止和两个 held-out，多数可确定性 replay）、远端 CI、第一次 clean-room rehearsal、最小 current context/evidence view |
| G5 Release | 1 天 | security/release 阻断关闭，README、演示、简历和 evidence package 初稿 |
| Buffer | 1 天 | 只做最终重跑、发布阻断修复、材料渲染或诚实降级；不新增能力 |

Gate 提前完成就立即进入下一 Gate，不等待日历。超过预算则降级十天目标；Buffer 的完整 1 天不可借用。

G0 计入十天，不隐藏为额外 Day 0。技术事实由 Codex 从当前合同、源码、环境和历史 receipt 预填；用户只裁决是否接受 Core target 改版、模型/外部调用边界、exact-diff 和 Runtime 授权窗口。G0 同时记录是否有可复现 Repair checkpoint，但它不阻断 Core。

环境/CI、Case 材料和证据整理可只读并行；涉及仓库写入时不得与 integration writer 同 checkout 并发。Ollama、GPU、游戏 Runtime 和同一 ArtifactStore 写入全部按 §2 优先级串行。

## 4. 六个 go/no-go

1. G0 未固定任务、objective、acceptance 或必要权限：Core target 不启动；只进入 Fallback。
2. G1 没有 Fresh→Planning consumer：只补这个产品断层，不建新平台。
3. G1 没有可消费 EvidencePack，或没有合格 Patch profile：停止 Core target 的 Patch 链，保留精确 first failure。
4. G2 没有完整 Dry-run 与 exact approval：不进入 Apply；Build 通过也不能替代 objective。
5. G3 缺 acceptance-required Runtime/环境：Core target 未达成；没有真实 Repair checkpoint不影响 Core，但不得声称 Repair 已证明。
6. G4 缺正确停止 Case、远端 CI、最小 Eval、Trace 或 clean-room rehearsal：Core target 未达成；进入 Fallback 的诚实材料交付。

## 5. 当前 Gate task packet

```text
task_id / goal
base_sha / current_head / source_identity / profile
authorized_actions / read_first
write_allowlist / protected_paths
current_first_failure / next_capability_stage
verification_commands
done_when / stop_when
rollback / unknowns / out_of_scope
```

控制在 800～1500 tokens。每个 Gate 开始或 HEAD/权限/source identity 改变时重建，不按日历机械生成。状态更新只写：已跨过的阶段、当前 first failure、有效验证、下一动作；不维护长篇每日叙事。

## 6. 十天关键路径外

默认移到 Day 11+：完整 inventory/flow/impact/health、PostToolUse/PreToolUse/Stop enforcement、`dev-check`、新增 Skill、pre-commit 扩展、branch coverage 门、import architecture rules、8～12+ 数据集、PDF/OCR、多模型 Level 1/2、Dense/RRF/rerank、MCP/Dashboard、长期 Memory、SFT/DPO、多模态。

只有它成为当前 first failure 的唯一 owner，才可提前进入。
