# Patch 上游续接

现有 `continue-fresh-patch` 可通过 `--patch-upstream-config <本地配置文件>`
装配 Evidence / Planning provider。原 `--patch-worker-config` 继续选择共享 worker
和行为验证器。配置是输入，不授予模型披露、修改或审批权限。

配置的精确顶层字段为 `schema_version`（`patch_upstream_configuration_v1`）、
`planning_profile`、`evidence`。Profile 使用现有本地模型字段：`profile_version`、
`base_url`、`model`、`context_window`、`output_budget`、`timeout_seconds`。
`evidence` 可以为 null；启用时只含 `profile`、工作区内相对 `search_root` 和
`max_additional_queries`。加载和装配不调用模型。

本入口要求已绑定的 Repair 输入、启用恢复的原 worker 和允许上游请求的策略。
模型选择是否请求上游；没有请求时保留同 Plan 路径，不强制读取或重新规划。
当前不支持与 `--qualified-model-routing` 同时启用，不静默降级模型资格。

读取工具返回已登记源码或已保存API正文，不重算Evidence/Coverage或Plan。
上游工具请求重评Evidence支持/冲突/覆盖判断，或Planning目标/范围。引用已经存在
不排除需要重评；理由使用现有`reason`自由说明，无新增诊断JSON或固定调查顺序。

Graph在worker开始前按当前配置声明`upstream_effects`，初次生成和失败修订共同使用：

| 值 | 当前接受请求后的执行后果 |
| --- | --- |
| `record_and_stop` | 保存请求并结束本次运行，不自动重评 |
| `assess_then_stop` | 直接Graph尝试重评，成功后停在Plan，不继续Patch |
| `assess_and_continue` | 公开入口可在准入及剩余预算内重评，再接新Plan下的Patch |
| `provider_unavailable_stop` | 该owner未配置provider，保存请求后停止，不假称已经重评 |

Evidence与Planning可以有不同后果。一个自动周期结束后，新worker仍可提出上游请求，
但声明会回到`record_and_stop`；工具不隐藏，请求不被静默替换为普通读取。
这些事实只说明执行能力，不证明模型选对了动作。

一次有界调用可以执行：当前被测代码及失败 → 上游请求 → 完整 Evidence/Coverage
重算（需要时）→ 模型 Planning → 新 Plan → 重建 worker/Binding 上下文 → 原行为
验证 → 新 Proposal/Review/Dry-run。`needs_evidence` 不回退到旧 Plan。
本次调用最多自动完成一个上游周期；后续明确上游请求保留为待处理结果，不发放额外尝试。

Patch、Query、Findings、Planning 共用原模型调用额度；新 worker 只继承剩余读取与
观察字节额度。额度为零仍允许合法直接输出，不强迫读取。预留/尝试、实际发送和收到
响应是不同事实。预算结束或异常不会自动重试或切换模型。

工具读取验证过的 B0 基线；正在修的代码是失败所引用的完整 assistant 输出。
新 Plan 输入保留旧失败作为诊断历史，旧 binding ID 不成为新权限。原成功标准保持；
验证器可读取当前 `implementation_plan`，同一配置的验证器实例保持连续报告身份。
固定旧 Plan 的领域验证器仍须先适配，不能仅因本入口可运行就宣称支持任意新 Plan。

旧 Proposal、Review 和批准不继承。新 Proposal 使用原 Builder/Reviewer，不变更
schema；工具轨迹留在原 journal。`patch_execution_segments` 分别记录各段 Plan 和
worker，`shared_model_budget` 记录整链预算；只读 `patch_execution_index` 保留各段
失败与末段结果，缺失信息显示 unknown。

工程验收使用合成源码和 HTTP 替身，实际运行原 CLI、取证、Planning、物化、行为
检查、Review 和 Dry-run。它证明接线和恢复能力，不证明真实模型修好 AccurateCrosshair。
