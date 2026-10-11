# 活动文档入口清理与导航验证

日期：2026-09-26。请求：移出活动入口中的历史叙述，复用现有能力导航，并围绕具体需求完成实现与入口验证。

本轮具体需求是文档入口清理；没有修改产品 Python、模型配置、审批机制或历史运行产物。文档任务的正常入口为活动文档链接和现有只读导航命令，不将它计作产品 Agent 真实任务成功。

## 1. 改动与归档

| 活动入口 | 清理前行数 | 清理后行数 | 保留职责 | 原字节归档 |
| --- | --- | --- | --- | --- |
| [产品契约](../ACTIVE_PRODUCT_CONTRACT.md) | 1,802 | 56 | 稳定执行边界、权限与声明口径 | [原文](../ACTIVE_PRODUCT_CONTRACT.history-20260926.md) |
| [项目状态](../PROJECT_STATE.md) | 2,980 | 54 | 可定位实现、事实层级、缺口和既有导航 | [原文](../PROJECT_STATE.history-20260926.md) |
| [实施队列](../IMPLEMENTATION_QUEUE.md) | 1,679 | 27 | 当前选择、紧邻候选和执行方式 | [原文](../IMPLEMENTATION_QUEUE.history-20260926.md) |

原始字节快照取自当时工作区，包含此前未提交改动，不从 HEAD 还原。归档仍位于原 `docs` 目录，保持相对链接基址。旧 `Current Development Selection` 锚点保留短导航；旧 Follow Recoil 锚点只跳转历史段，不恢复旧任务。

归档是历史资料而非活动合同；只有当前问题需要追溯时才读取，不能据此恢复旧任务或授权。为什么要有它：原始证据应保全，但读取入口不能继续携带过期指令。

三个原文 SHA-256：

```text
ACTIVE_PRODUCT_CONTRACT: efa702f781df6ddb68042eeb641bc0ad0ac002776cf3bd3db707f7916939fbb2
PROJECT_STATE:           8a028d56e2516591742489fefd3ca1be4f990c3c06f7de5a572cbb34c8f294ce
IMPLEMENTATION_QUEUE:    6dcef223e9e37b0717840580d65f343e71bd4213f2824522ba47176b8d74f65f
```

另有两处直接相关的小修：评测协议的历史交付链接改指归档；架构说明末尾失效的 `AGENTS.md section 2` 引用改为当前请求与适用工作约定。其他架构叙述与既有 WIP 保留。检查前身份见[快照清单](active_entry_cleanup_20260926/before.json)。

## 2. 复用导航与静态链路

现有工程认知工具的 summary，以及 `CompleteCrosshairVerification`、`make_complete_crosshair_evaluator`、`PatchWorkerConfiguration` 精确符号查询，均已由并行只读调查执行并返回 exit 0。项目状态页仅保留代表性入口命令，不增加另一套索引或任务包。

源码核对路径：`cli.run-request` 加载 worker 配置 → `run_local_request` 注入行为裁判 → `RequestPatchExecution` 使用共享适配器 → lazy factory 按哈希/工厂名/kwargs 装配 → 组合 verifier 产生反馈。符号导航是定位工具，动态配置和真实执行仍需单独核验。

相关现有测试使用受控 HTTP、编译器或裁判替身，属于可复用回归资产；本轮没有运行这些产品测试或真实编译，不将它们写成新增通过结果。

## 3. 本轮验证

验证覆盖归档字节、当前文档链接、两类历史锚点、无关 WIP、实际文档导航命令及 diff 空白检查。聚合结果保存在[最终验证记录](active_entry_cleanup_20260926/verification-final.json)。

独立审阅由没有参与编辑的审阅者检查：稳定合同是否遗漏、历史是否完整保留、是否仍有旧任务被标为当前、正常入口是否可定位。提出的历史交付链接修正已落实；最终只读审阅通过，没有发现稳定边界遗漏、旧授权恢复或将导航误报为产品通过。

首次检查保留在[原校验记录](active_entry_cleanup_20260926/verification.json)：归档、链接、无关 WIP 与导航均通过，但架构说明补丁将末尾 CRLF 改成 LF，导致“反向替换后逐字恢复”校验失败。仅恢复该补丁区域原换行后复核；已经通过且实现未变的导航不重复执行。

文档改动不运行无关产品模型或全套测试。为什么要有它：本轮验收对象是阅读和导航入口，产品成功率需要另行真实任务证据。
