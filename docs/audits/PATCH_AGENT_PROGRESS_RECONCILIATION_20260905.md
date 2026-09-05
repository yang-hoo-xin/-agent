# 2026-09-05：Patch 进度与聊天缓冲任务核对

核对基线：产品代码 `3694a7725ddd6242ea17db029b88e119a130d378`。
用途：集中保存 9 月 4 日工作证据、范围变化及未完成项，供本页和新页恢复工作。
本文不是新的产品状态数据库、审批、验证器或第二份排程。待办优先级只在
[Implementation Queue](../IMPLEMENTATION_QUEUE.md) 维护；本文保存本次核对时的结果。

## 1. 结论与范围

**整个聊天缓冲区没有完成，GPT Chat 建议也没有全部落地。**
完成的是一条限定于当前 AccurateCrosshair 请求的审批前产品链：

```text
已有 FeatureSpec / Fresh EvidencePack / 人辅选目标的 ImplementationPlan
-> 本地 Qwen3-Coder 选择一个 binding
-> 读取受限源码 observation
-> 生成初稿
-> 文件头 validator 拒绝
-> 一次 correction
-> PatchProposal / ProposalReview / no-write Dry-run
```

这证明当前输入下工具交互与特定失败修正能到达 Dry-run，不证明多任务
Patch profile、全链自治、任意 validator 自动修复或 changed Build/Runtime。
记录中的 `semantic_assurance.verdict=unproven`、
`human_semantic_review_result=pending` 必须保留。

9 月 4 日对“目标完成”的报告只适用于上述阶段，不能覆盖用户要求的
“当前所有任务以及后续新增任务”。聊天中没有落盘的缓冲计划不能继续
当作可靠交接入口。本次只核对可见要求、提交、源码和运行记录；不声称
能够恢复未提供的内部推理、全部历史 UI 消息或丢失的工具输出。

## 2. 主证据定位

Artifact 根目录相对仓库为
`artifacts/g1_assisted_findings_context_repaired_27b_fc/store`。
该目录是本地运行资产；开新 worktree 时须确认它可访问，Git 提交本身不代表复制了这些文件。

| 对象 | 精确 SHA256 / 身份 |
| --- | --- |
| Feature | `feature_66e54ec4a116` |
| FeatureSpec | `fc7be8abc61c9b8e198062dcdba107fd07c57342901ae43551c8e0860806d004` |
| EvidencePack | `bd2e2bde11e79605c367a2b67e9c68e7d27adbfd998cd79307b2c5c0b8048058` |
| ImplementationPlan | `b11e4dde1215ca7861e3f2160b05dca150522e889a0ecdf4982e87085e0208ae` |
| PatchProposal | `0a2e5c5406ec7ff52bdb0056145bf02d06a3b4f01fbba8e7f169613dd97211e4` |
| ProposalReview | `9468839fc443284ef9215f054435d3f143f0eccd5242efb078c1a0a88eb7a55c` |
| Dry-run | `18b5d478fca78ae0d06090ff8e68097c19feff3bb81a750c08b44112ed228725` |
| 审批 diff hash | `sha256:684615135310c41692a801772bcc8a34b4b1a6af1edc45560e0df1817934f282` |
| 模型 digest | `06c1097efce0431c2045fe7b2e5108366e43bee1b4603a7aded8f21689e90bca` |

末次运行：[receipt](../../artifacts/g1_assisted_findings_context_repaired_27b_fc/store/cr/5024afcd6671db0cee7f7f0f5c4e92a3.json)。
[完整 diff / Dry-run](../../artifacts/g1_assisted_findings_context_repaired_27b_fc/store/features/feature_66e54ec4a116/r/dry_run_result/18b5d478fca78ae0d06090ff8e68097c.json)。

- 运行：`patch_continuation_a1a22fbdcc6e4f89920602208c6c9c9d`。
- 状态：`stopped_before_exact_diff_approval`；3 次模型调用、1 次源码工具、1 次 correction。
- 端到端墙钟：277.13 秒；4 个 binding，2 个文件，新增 7 行、删除 0 行。
- 初稿与修订稿分别保存在该 receipt 对应的 `.response.txt` 与
  `.response.correction-001.txt`；没有覆盖初稿。
- 本次 Apply、Build、Runtime 均未执行，产品源码未写入。

这里的 inspection 由程序要求必须发生，**binding 由模型选择**。
它不证明模型自主判断“是否需要查工具”，也不证明自主 API discovery。

## 3. 这轮实际做了什么

| 提交（本地时间） | 内容及界限 |
| --- | --- |
| `c403037`，09-04 19:38 | Dry-run 拒绝新添行尾空白；prompt 加明确说明 |
| `0a04055`，20:06 | 保留失败诊断和已生成 Artifact；schema identity；移除 rationale 词面路由判断；修正空白检查边界 |
| `ac92b17`，20:42 | Patch-specific source tool loop、prepare/materialize 分离、生产 CLI 接线 |
| `e431435`，20:59 | 同 adapter 已观测 token/byte 比率估算、provider 失败诊断、调用方预算 |
| `f7d51a8`，21:05 | 后续工具 enum 去掉已看 binding；仍因真实重复动作失败 |
| `138a7e9`，21:09 | 默认一次 observation 后强制 final；不代表多轮调查收敛 |
| `af3215d`，21:19 | materializer 保存源 BOM |
| `d6eeed7`，21:25 | 文件头 replacement 删除全部 using 时阻断；这是启发式保护，不是 C# 编译验证 |
| `3694a77`，21:37 | 针对上述 header 失败的一次模型 correction；末次真实 Dry-run 通过 |

聊天 goal 记录约 2 小时 15 分钟，包含后续 continuation。
Git 时间戳与末次 receipt 支持先完成 loop、后补 correction 的顺序；
不能由提交时间反推出每分钟投入，也不把 goal 的累计 token 数当作已核对的账单费用。
净改动为 16 个源码/测试文件、`+3190/-58`，没有文档更新包含在上述九个提交内。
新 loop 模块 1076 行，体量与重复制式代码仍是明确维护债。

末次成功之前，真实尝试依次暴露：空白、缺调用链上下文、第三 turn
byte gate 拒绝、重复工具请求、BOM/using 丢失。不能只保留末次成功而删除失败记录。
同一源码下 one-shot 到 early-return 的变化与新增 observation 一致，
但 prompt/模式也发生变化，不能宣称已严格证明单一因素的因果收益。

验证记录（来自昨天的执行输出，本次文档核对未重跑）：

- 478 项两 worker checkpoint 在 BOM/header/correction 的最后改动之前通过，
  不能称为最终 HEAD 的全仓库回归。
- 最终 correction 改动后的命令：
  `python -B -m pytest tests/unit/test_patch_agent_loop.py tests/unit/test_patch_code_generator.py tests/unit/test_fresh_planning_continuation.py tests/unit/test_local_entry.py tests/unit/test_workflow_graph.py -q --tb=short`，439 passed。
- header 改动后生成器测试文件 90 passed；已有 jieba warning。
- 4 个 ProposalReview 旧夹具因缺 exact source identity 失败，昨天恢复旧 rationale
  代码后仍能复现；未修夹具，不能声称完整单元套件全绿。

## 4. GPT Chat 原则及三个 Loop 补充项

状态用完整文字，不使用 A/T/P 混合缩写。

| 要求 | 核对状态与实际范围 |
| --- | --- |
| 基础 Agent/tool/observation loop | 已实现，当前一个 binding 的真实工具往返通过；多轮自主调查未通过 |
| 权限内主动完成任务 | 已实现 binding id 输入、受限读取、snapshot 检查；工具 observation 不增加 edit bindings |
| JSON 与 loop 共存 | 已真实通过最终四字段 `changes`；原始合同保留 |
| 工具权限分层 | 首版只有 `inspect_plan_binding_source`；没有任意路径/shell/Apply 工具 |
| 模型负责语义，系统负责已有身份 | binding-only 已有；本轮另收回 BOM。没有跨所有 stage 完成 owner 审计 |
| 每字段检查是否真需模型判断 | Patch 层有实际审计；全项目准则/逐 stage 检查未全部完成 |
| Slot filling | 明确延期；没有固定 slots 新合同 |
| Schema identity | 已有系统侧 `patch_generation` / `2` / schema hash，进入 receipt/generation；非所有 stage 统一完成 |
| 简单 provider schema、避免复杂组合 | 当前 Patch 简单 schema 和防复杂关键词测试存在；通用 provider 兼容框架延期 |
| rationale 非 authority | 当前 ProposalReviewer 的词面匹配 gate 已移除；不得把解释当语义证明 |
| rollback_hint 非 authority | 当前路径是说明；可选旧 Critic 仍按非空提示计 reversibility，未全面纠正其语义评分 |
| Ref-first / copy-last | supporting excerpt 截到 1024 bytes 并记录 hash/truncation；source observation 有限额。没有任意 evidence ref 的完整按需读取工具 |
| One stage one schema | 各 stage 已分离；没有全 stage 迁移/审计，不新增万能输出 |
| 三层责任 | Provider 形状 -> Plan/Binding 身份准入 -> code/Dry-run/后续验证；责任已存在。本记录明确边界，不新增三种 Artifact |
| JSON 通过不等于代码/语义通过 | 真实拒绝和 `unproven` 证明该边界；还没有通用语义验收器 |
| 当前 Artifact 动态收窄 | binding enum 和数量约束存在；工具 enum 无法代替本地验证 |
| Context byte proxy | 部分处理：AgentTurn 后续请求可用经验比例估算；不是 tokenizer，也不是数学保证上界，首轮/其他路径仍有旧 proxy |
| Loop budget / termination | 固定 tool/turn 上限与显式 caller budget存在；production 默认一次观察。逐 turn crash receipt、全轮次身份和端到端时限仍需复核 |
| Observation identity / freshness / error | hash、binding ref、source snapshot、截断、失败原因存在；末端 Graph 重验。不代表任意中间 turn 的跨进程恢复 |
| Loop context / history | 总 observation bytes 有界；初始 supporting 截断。多轮模式仍会重放此前 observation 全文，未实现完整 supersede/history 压缩 |
| Evaluator correction | **只对 `csharp_file_header_usings_removed` 修一次**；不是通用 validator/Review/Dry-run/编译失败修正 |

实现入口：
[Patch loop](../../src/mod_agent/proposal/patch_agent_loop.py)、
[Local entry](../../src/mod_agent/local_entry.py)、
[schema/materializer](../../src/mod_agent/proposal/code_generator.py)、
[Review](../../src/mod_agent/proposal/reviewer.py)、
[context admission](../../src/libs/llm/agent_turn.py)。

## 5. 缓冲区尚未交付及已有底座

| 工作项 | 本次核对结果 |
| --- | --- |
| 当前 Mod 的 Apply / changed Build / Runtime | 未执行；审批前语义复核仍需完成 |
| General validator correction / compiler-test feedback | 仅特定 header correction；其余未接通新的自动反馈内环 |
| `AUTONOMOUS-EVIDENCE-DISCOVERY-001` | 当前 Fresh 是显式人辅 API symbols；自主成功未证明 |
| `AUTONOMOUS-TARGET-SELECTION-001` | 当前四目标由 operator 选择；Plan compiler 已运行，自主语义选择未完成 |
| `MODEL-ROUTING-001` | 手工模型/profile 设置与个例结果存在；role -> qualified profile 正式 resolver 未交付 |
| `PATCH-EVAL-SUITE-001` | 未冻结新的 3-5 项真实 Patch 任务集；旧 RAG 定义不等于 Patch suite |
| `RUNTIME-REPAIR-LOOP-001` | 历史窄 Runtime/Repair 路径存在；当前 Mod 未走，通用自动闭环未完成 |
| `PROVIDER-CONTEXT-ADMISSION-001` | 经验比例补丁已做；模型 tokenizer、模板精确计数及泛化资格未完成 |
| `INFRASTRUCTURE-FALLBACK-001` | 延期；不得把语义失败自动切模型视为通过 |
| 工程认知八视图 | 工具存在；当前仍错报 API 未入 Fresh，verification 只是 inventory；待修 |
| PreCompact / SessionStart | 脚本与 hooks.json 已提交；最新 summary 没有真实生命周期 snapshot，信任/恢复验收未证明 |
| `bounded-task-handoff` | Skill/脚本在 09-02 已建立；当前 task packet 仍 stale，未接住昨日新任务 |
| `release-evidence-packager` | Skill/脚本在 09-02 已建立；最终 manifest、演示与简历材料未交付 |
| 依赖锁与最小 CI | `uv.lock`、`.github/workflows/ci.yml` 在 09-02 已提交；不能再写成“没做”。本次未核对 hosted CI run/clean-room 成功 |
| Local Environment | `scripts/setup_codex_local_environment.py` 已有；Desktop 绑定和实际重建未证明 |
| Langfuse / Trace / Eval | 本地 receipt/lineage存在；Langfuse exporter 仍是 injected transport，无完整真实生产 sink/flush/session/score 验收 |
| pre-commit / dev-check / profiles / Hook enforcement | 未在此次提交中落地；十日草案多数明确延期，不能自动升级到 P0 |
| branch coverage / security / deployment / release | 未完成发布级验收；不由当前 Patch 成功代替 |
| 九目标、五项、三个 txt 成熟度 | 目标保留，未在这两小时内完整实现/验收；十日排程仍按未审核草案处理 |

## 6. 必须纠正的既往结论与当前审查事项

1. “全部缓存任务完成”不成立。此前 goal 完成标记没有覆盖所有已承诺任务。
2. `model -> tool -> observation -> model` 已有真实记录，但工具被强制、默认只查一次；
   不能提升为任意多轮自主 coding worker。
3. “同模型比例 x2 是保守上界”不成立。token/byte 比率可能随内容和模板变化；
   当前是经验估计。需要资格/边界验证，不将该估算包装成精确计数。
4. “early-return 已保证 First Shot/其他行为独立”尚无充分证据。
   最终 diff 在 `_validGun = false` **之前**新增 return，会跳过
   `FirstShotPatches.ResetStoredCrosshair()` 与 `SetStoredCrosshair()`。
   当前 FirstShot Match 会调用 `UpdateSpreadScalar()`，后者依赖 `_validGun`
   才实际更新尺寸。须按 FeatureSpec 的独立性义务验证，不能因 diff 干净直接批准。
5. 热重载 true -> false 若保留此前 `_validGun=true`，`OnConfigReload()` ->
   `UpdateCrosshairSize()` 仍可能用旧状态覆盖。原验收明确要求重启；
   热切换是否纳入验收应明确，不能暗中新增需求，也不能宣称热重载已语义通过。
6. 删除所有 using 不必然都是非法 C#（可能使用完全限定名）。当前 header gate 是
   保护本任务无关内容的启发式，不是全语言的普遍正确性规则。
7. 历史工程认知、状态文档与实际 Artifact 不一致，必须依据当前源码/记录复核。
   这不是聊天可见性本身能修复的问题。

上述源码审查依据：
[SpreadPatches](../../workspaces/actual_only/accurate_crosshair_spread_toggle_preflight_20260824/source/AccurateCrosshair/CrosshairPatches/SpreadPatches.cs)、
[FirstShotPatches](../../workspaces/actual_only/accurate_crosshair_spread_toggle_preflight_20260824/source/AccurateCrosshair/CrosshairPatches/FirstShotPatches.cs)。
这里没有执行游戏或改写已冻结的 Artifact；问题仍需实测界定。

## 7. 本页继续与上下文工具

本页仍可继续；无法仅凭模型自评保证长上下文完全不影响表现。
官方 `/status` 查看 chat/context usage，`/compact` 压缩上下文；
它们不测推理质量。见[桌面端命令](https://learn.chatgpt.com/docs/reference/slash-commands)。
没有在所核对的官方文档中找到自动测量“上下文降低多少智能”的现成 Skill。
现有 Hook 是恢复定位工具，engineering cognition 是可重建事实索引，均不是性能评分器。
若反复出现遗漏最新决定、复活已否决任务、重复调查已明确事实，先对照本记录和队列；
必要时压缩或以短交接开新页。新页/压缩本身不保证更准确。

本次沿用工作树，保护六份原有 WIP；未重写它们，未创建新页，未删模型，未增加自动任务。
