# Patch接受运行卡：输入快照，不授予权限

本卡定位当前输入与责任，不是启动命令、授权凭证、第二Queue或可重放任务。
本卡所选接受运行已消费：Proposal/Review/Dry-run通过，行为33/36，First Shot三项失败。
此卡不能再次启动模型；原claim与失败结果保留，任何下一步另按当前用户请求选择。
实际选择见[Queue当前块](IMPLEMENTATION_QUEUE.md)；十日范围见
[覆盖参考](TWELVE_TURN_EXECUTION_WORK_PACKAGE_20260905.md)。历史执行结果只记
[reconciliation §12](audits/PATCH_AGENT_PROGRESS_RECONCILIATION_20260905.md#12-两小时执行窗口)。

## 1. 适用范围与有效性

- 当前任务：`01a07014-bccb-7420-bbcd-38defc72fecb`，AccurateCrosshair P0。
- 历史启动/本次停止上限：2026-09-05 16:44:24–18:44:24 Asia/Shanghai。
  该时间只是本次执行安排，过期不可重新消费；用户新指令可随时改变安排。
- 权限依据须回查本任务用户“开始做这一步，授权所有权限”及后续确认本页继续执行的消息。
  本卡引用消息不生成授权，也不将权限移交给其他任务。
- 代码检查点`de288295a10930adf251dcfa4b4886848df21ac5`是记录，不是永久当前HEAD。
  代码改动后重新核验受影响请求；最终运行receipt记录实际HEAD与输入身份。
- 以下exact Artifact/source身份不匹配时停止该次产品调用；不阻断无关的已授权平台开发。

## 2. 固定输入

| 输入 | 精确身份 |
| --- | --- |
| FeatureSpec | `fc7be8abc61c9b8e198062dcdba107fd07c57342901ae43551c8e0860806d004` |
| EvidencePack | `10a3fadd00b7437ee988729f8e78cab1d559f2f3bb774920da5ffbb45c17d3fe` |
| P0原人辅Plan | `c760a9cc2e04110c0f5a8fa1f6efcb8d661169fbdf76776596232f795100d129` |
| source snapshot | `421ea5eb4785db9fd03740ab76d9f5eff84bf0cedbee9d749679271febf860a0` |
| 已通过首轮零网络预检的请求 | `c00e2ea00671231a530b154acc3046e3c058179faebe0487066aeed1120d9766`，44,732 bytes |

完整路径及原人辅5目标在本任务scratch的`case_revision/planning-receipt.json`。
新预检见`case_patch_c760_reacceptance_001/preview.json`。自主Plan `e504888e…`只作A3
独立资格评审，不能替换本P0输入。不得由工程侧补目标、正确after_text或参考实现。

## 3. 执行责任和尝试预算

- A1只做生产context/admission实现、聚焦测试、同body的零网络preflight，停止在发送前。
  当前c760请求无需跨客户端校准即可通过。该校准支线暂停，未完成代码单独备份，
  不进入本次执行checkout；原3条用户语义反馈保持不变。
- A2是本卡已执行Patch接受运行的唯一发送责任方。使用现有同一个PatchAgentLoopPolicy，
  最多3次源码工具、5次模型调用总和（含允许的correction），同值传给continuation和adapter。
  一个接受运行可能有多次HTTP；A1、审查和文档重读不能再次调用。
- 使用`qwen3-coder:30b`、context49152/output4096/单请求timeout600；模型digest仍须
  匹配现有本地准入及当前运行收据。模型不匹配不自动切换；本次不使用跨客户端校准。
- 本次保持原策略`finalize_after_first_observation=True`；固定总预算不变。
  启动前须确认剩余时间足够覆盖整个有界运行和收尾，不因卡上写着可做就强行发送。
- 新`attempt.claim`由本次runner独占；保留每回合待发送body及完整解析响应、模型/源码身份、
  工具、usage与终态。首包与预检不符时先保留事实，再停止，HTTP计数为0。
- 总计数和attempt不得由A1/A2各自再配置；失败不自动授权重试。原`ccc254…`失败和A3的
  001发送前失败保持原样，不能重放其claim或把离线诊断写成新执行。

## 4. 允许动作与仍需具体批准的动作

本页当前用户消息已覆盖：平台仓库实施、聚焦测试、本地模型有界接受运行、无写
Proposal/Review/Dry-run、本轮平台提交；这些不是从本卡获得的权限。

尚不存在针对未来diff的exact approval。新diff经当前人工语义审查并获得该hash的新批准后
才能Apply；changed Build与游戏目录写入/启动/Runtime仍须满足各自具体执行边界。
本卡不授权外部模型披露、远端push/发布或自动增加尝试。

## 5. 输出与停止条件

- 本次使用已提交的平台代码，root负责唯一发送；行为验证只消费产品模型生成内容。
- 运行结果存本任务scratch的`case_patch_c760_reacceptance_001`及既有ArtifactStore；
  当前精确结果、提交、命令和限制只汇总到reconciliation，其他入口只摘要链接。
- 完成条件：来源证明、ProposalReview、Dry-run及新内容的既有行为检查分别报告；
  不以合法JSON、合法Plan、旧负例或模型自述宣布修复通过。
- 精确首个失败、source/model漂移、预算耗尽或用户要求暂停时停止对应执行；保留已产生事实。
  未完成P0、A3语义资格、自动replan或七组十日目标时，不以时间结束标成完成。
