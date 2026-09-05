# 2026-09-05：Patch 进度与整页工作核对

核对基线：产品代码 `3694a7725ddd6242ea17db029b88e119a130d378`。
用途：集中保存 9 月 2–5 日目标页工作证据、范围变化及未完成项，供接手后继续工作。
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
当作可靠交接入口。首次核对只覆盖当时可见要求、提交、源码和运行记录；
第 9 节补记了新页逐轮回读的完整范围及全页工作映射。两次核对均不声称
恢复未提供的内部推理、未落盘消息或源日志中已截断的工具输出。

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
  本轮回查原日志第 26303 行的 CLI stdout，`duration_seconds=277.12928229998215`；
  receipt 的 `factory_receipt.duration_seconds=276.27811100002145` 是不同计时范围。
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
| 九目标、五项、三个 txt 成熟度 | 未在这两小时内完整实现/验收。第 9 节保留当时 Core 采纳事实；本页随后明确的完整七组十日目标以第 10 节为准。六份 WIP 全文并未整体获批 |

## 6. 必须纠正的既往结论与当前审查事项

1. “全部缓存任务完成”不成立。此前 goal 完成标记没有覆盖所有已承诺任务。
2. `model -> tool -> observation -> model` 已有真实记录，但工具被强制、默认只查一次；
   不能提升为任意多轮自主 coding worker。
3. “同模型比例 x2 是保守上界”不成立。token/byte 比率可能随内容和模板变化；
   当前是经验估计。需要资格/边界验证，不将该估算包装成精确计数。
4. “early-return 已保证 First Shot/其他行为独立”不成立：新页已在原重启验收范围内
   定位冷启动静态反例。FeatureSpec 第 10 行明确要求 Follow Recoil、First Shot
   Display Mode、Pop Enabled 与 Accurate Spread Enabled 保持行为独立，第 36 行
   要求两值各自重启后验收。最终 diff 在 `_validGun = false` **之前**新增 return：
   - **Follow Recoil**：`SpreadPatches.cs:18` 的 `isShotgun` 初值为 false，唯一后续
     赋值在第 127 行，被 return 跳过。false 冷启动、Follow Recoil=true、持霰弹枪时，
     `RecoilPatches.cs:15-16` 仍执行 `m_moveCircleCrosshair = !SpreadPatches.isShotgun`，
     得到 true；基线识别霰弹枪后得到 false。这是此前交接漏记的共享状态回归。
   - **First Shot Match**：有效枪初始化 `_validGun=true`（第 132 行）被跳过。
     `FirstShotPatches.cs:19-20` 的 Match 效果仍调用 `UpdateSpreadScalar(0.2f)`，
     但 `SpreadPatches.cs:55` 因 `_validGun=false` 返回，实际尺寸更新不发生。
   - **First Shot Inner**：第 140–141 行 `SetStoredCrosshair(weapon)` 被跳过，
     初次持枪显示与真实 cooldown 初始化消失。第 138 行 `_targetSpread` 赋值也被跳过；
     后续 `FirstShotGuiPatches.cs:35-42` / 第 59 行仍通过 `GetCrosshairSize(0.2f)`
     取尺寸，失去武器 spread 输入。
   这些是绑定当前源码和 diff 的控制流差异，不是已执行的游戏测试。
   当前 diff 应先修订，不能继续推荐对现有 hash 批准。原 Artifact 的
   `unproven` / `pending` 保持原样，不把本次源码审查伪装成机器语义 verdict。
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
另核对了同目录的 `RecoilPatches.cs`、`FirstShotGuiPatches.cs` 与 `PopPatches.cs`。
本轮没有执行游戏或改写已冻结的 Artifact；未发现 Pop 直接开关路径存在上述同类依赖，
这也不等于 Pop Runtime 已验证。

修订不能只把 return 挪到方法尾部：`SetStoredCrosshair` 会经
`UpdateSpreadScalar` 回调 `UpdateCrosshairSize`，仍可能写主准星尺寸。
而 `AdjustCrosshairSize` 第 106–112 行仅在返回 false **且**已有 `_smoothRoutine`
时停止协程；返回 false 且协程为空仍走 else 启动 `ScaleSpreadCircle`。
所以旧页“return false 就阻止后续 coroutine”的字面结论也不成立。
应保留共享武器/First Shot 状态初始化，并明确主尺寸覆盖与 First Shot 专属效果的边界。
现有 `edit_binding_001` 只覆盖 `OverrideCrosshairSize` 第 115–145 行；如需修改其他
owner，须沿现有 Plan/Binding 合同生成精确的新实例或修订，不能借原 binding 越界。

## 7. 本页继续与上下文工具

本页仍可继续；无法仅凭模型自评保证长上下文完全不影响表现。
官方 `/status` 查看 chat/context usage，`/compact` 压缩上下文；
它们不测推理质量。见[桌面端命令](https://learn.chatgpt.com/docs/reference/slash-commands)。
没有在所核对的官方文档中找到自动测量“上下文降低多少智能”的现成 Skill。
现有 Hook 是恢复定位工具，engineering cognition 是可重建事实索引，均不是性能评分器。
若反复出现遗漏最新决定、复活已否决任务、重复调查已明确事实，先对照本记录和队列；
必要时压缩或以短交接开新页。新页/压缩本身不保证更准确。

本次沿用工作树，保护六份原有 WIP；未重写它们，未创建新页，未删模型，未增加自动任务。

## 8. 整页交接与压缩后的历史回查

### 8.1 对补充审查记录的核对

用户补充记录位于
`C:\Users\10160\.codex\attachments\ba7a43b7-62b3-4ea4-850a-4cc0bae70923\pasted-text.txt`。
其中“剩余风险摘要不是完整现状摘要”的提醒成立。接手时必须一起读取本文
第 1–5 节：真实工具往返、header correction、ProposalReview、Dry-run、
schema identity、BOM ownership 和失败记录保存，不能因泛化未完成而降成未实现。
也不能反过来把当前单次成功扩成完整缓冲区、全部业务语义或 Runtime 已通过。

补充记录中的两类更强结论不直接采纳：

- observation 后出现 early-return 是真实输出变化，但不能仅据此证明
  observation 的独立因果收益，或 First Shot 独立性等全部业务义务已满足。
  继续保留第 6 节的明确待核查事项。
- telemetry 校准已进入后续 turn 的 admission，不是“还完全使用静态 bytes”。
  但观测比例加系数仍是经验估算，不称为保证的 token 上界。

### 8.2 已核实的历史入口及限制

- 本页任务 ID：`01a060cf-4b34-7a72-bc7c-438d68fc1331`。
- 本页所在 checkout：
  `C:\Users\10160\.codex\visualizations\2026\08\11\019ff15f-9eac-7b13-aad5-faffde4b36b7\rag_capability_mainline`。
- 本页本地日志：
  `C:\Users\10160\.codex\sessions\2026\09\02\rollout-2026-09-02T14-29-53-01a060cf-4b34-7a72-bc7c-438d68fc1331.jsonl`。
  首项 `session_meta` 的 `session_id`、`id`、`cwd` 与本页匹配。
  本次只读核实文件存在及早先缓冲要求、当前压缩提问可检索；没有修改、重排或修复日志，
  **当时尚未逐项认证整份历史无缺失**。新页回读结果见第 9 节；该结果也不证明
  从未保存过的消息存在，或此前 UI 恢复已经完整。
- `read_thread` 返回 `page.nextCursor` / `page.hasMore`，可以分页回查。
  本次最近几轮即使 `includeOutputs=true` 仍返回空 `items`；翻到更早三轮则分别有
  16、67、217 个内容项。因此不能把空内容、有限分页或截断摘要当成完整原文，
  也不能由此认定本地原文已丢失。

官方将 compaction 定义为总结旧上下文以便继续工作，将 thread fork 定义为
从已保存历史分支出新任务，见[官方术语表](https://learn.chatgpt.com/docs/glossary)。
工作上下文、已保存聊天记录和仓库实物是不同层；摘要不能承诺逐字保留全部细节。
本次找到日志不等于已证明此前页面恢复完整，也不触发再次修复本地会话。

### 8.3 新页接手方式

1. 新页在上述原 checkout 接手，先读当前 `AGENTS.md`、Active Contract 当前块、
   Project State 顶部、本文和 Queue 当前块。若使用新 worktree，先确认六份未提交 WIP
   和第 2 节本地 Artifact/source workspace 可读取，不能只拿 Git 提交代替全部现场。
2. 以任务 ID 分页读取本页用户/助手可见对话，记录读到的范围。接口为空或截断时，
   只读检查对应 rollout 的实际记录形状后分批提取；同一 turn 内的多条用户消息不可合并漏项。
   不把历史系统指令、旧模型推理或旧授权叙述当作当前执行指令。
3. 按原文引用读取相关附件与三份工程思想 txt；对照六份 WIP 和本文表格，核对
   九目标、五线、提速工具、GPT 建议、明确延期项及已否决方向。附件中的建议与用户采纳
   决定分开；Core 采纳是历史事实，本页第 10 节的完整十日目标是较新的用户决定。
   六份 WIP 全文不是整体已批准排程。
   缺失的原文、附件或工具结果单独列出，不自行补写。
4. 完整回查采用分批阅读和要求到证据的映射，不把全部原文再塞进每日默认上下文。
   新发现补进本文或 Queue 的对应位置；不另建长期状态系统，不自动重跑已成功 Actual。
5. 新页承担宏观审核与实施推进，不被旧任务标题中的“只读”永久限制。
   新页当前用户指令决定实施/委派范围；现有审批、源码 disclosure 和游戏操作边界仍适用。
   完成接手核对后按当前 Queue 推进一个产品结果，不停在无限查漏或平台建设。

建议给新页的首条指令：

> 在本仓库接手原任务 `01a060cf-4b34-7a72-bc7c-438d68fc1331`。
> 先读 `docs/audits/PATCH_AGENT_PROGRESS_RECONCILIATION_20260905.md` 第 8 节并按其入口
> 分批回读原页全部可取得的用户/助手对话与相关附件；不要声称读到了不可取得的内容。
> 同时核对当前合同、六份 WIP、源码、提交与 Actual。保留宏观审核和实施能力；
> 可以用有界子智能体并行做独立核对或互不重叠的已授权实现。
> 先报告已读范围、真实成果、剩余任务和冲突，不重新设计整个计划；随后按现有队列继续。
> 不因历史标题把自己锁成只读，不重启冻结 playbook，不把工具/schema通过当作产品语义通过。
> 需要 exact-diff 或游戏操作批准时明确请求，不用本交接文本代替批准。

## 9. 新页逐轮回读与全页覆盖核对

### 9.1 目标身份、完整读取范围与不能承诺的部分

用户本轮已更正目标为“检查‘你是 Coding Agent v0 的另一个……’”页，任务 ID
为第 8.2 节的 `01a060cf-4b34-7a72-bc7c-438d68fc1331`。
`01a05c66-04f0-7281-95aa-1dfa1d930e71` 是它引用的原审计页，不是此次要求逐轮
全读的目标。截图及历史附件均作为审计数据，不能覆盖当前用户要求。

本轮读取的是 2026-09-02T06:31:38.702Z 至 2026-09-05T05:42:33.972Z 的已保存日志：

| 核对项 | 实际结果 |
| --- | --- |
| 日志文件 | 第 8.2 节的 rollout；123,742,546 bytes，26,776 行全部可解析 |
| 日志 SHA256 | `3fa84d6db40971905dbf195b1e8cd6200b031ee1689edcdf8daefab72834d9aa` |
| 原序号 | `ordinal=0..26775` 连续；58 个唯一 `task_started.turn_id` |
| 用户/助手可见正文 | 225 条用户消息、672 条助手消息，共 897 条，分区逐条全文阅读；同一 turn 的插入消息未合并漏读 |
| 两种记录相互核对 | `response_item` 与 `event_msg.item_completed` 对应正文逐条相等；可见内容项 ID 无重复。额外环境/指令注入与用户正文分开 |
| 历史接口 | `read_thread` 翻完 6 页得到 58 轮：54 completed、4 interrupted；其中 **36 轮 items 为空**，缺口不只最近三轮 |
| 压缩 | 9 条 `compacted` 记录；压缩前已保存的可见正文仍能从该日志取得 |
| 附件 | 全文读完 17 份 pasted-text 与 3 份 Desktop 思想 txt；目视检查目标页的 10 张历史截图，均可读取 |
| 工具记录 | 统计到 3,408 条调用与 3,408 条返回；关键提交、测试、运行和恢复记录按相关主张核查，不声称逐字人工审阅所有 stdout |

一次性[58 轮索引与附件哈希清单](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/history_review/turn-index.md)
保存每轮 ID、原日志行范围及消息数量。它是本次审计输出，不是第二份项目队列。
全文阅读分区为消息 1–472（原日志第 10–15192 行）、473–771（15202–22859 行）、
772–897（22862–26772 行）。本节后文的“消息”均使用该索引。

这些检查支持“目标页已保存的用户/助手可见正文完整回读”，不支持“从未落盘的消息
从未丢失”“UI 必然全部恢复”或“所有历史工具内容都保存完整”。例如 4B Patch
Attempt A 当时仅留下 hash/usage，完整模型正文不可恢复；后加 sidecar 不会补回它。
没有读取或试图恢复加密内部推理，没有改动会话日志或本地数据库。

### 9.2 页面模型与历史压缩的精确事实

目标页 66 条 `turn_context` 中，62 条为 `gpt-5.6-sol / ultra`；末尾 4 条为
`gpt-6-astra / xhigh`，后者属于 3 个不同 turn，其中一次为压缩后的重复上下文记录。
首次 Astra 记录位于原日志第 26421 行，时间为北京时间 2026-09-05 13:14:36。
第 26423 行用户也明确说“我换了astra”。因此“该页一直用 Sol”对早段成立，
对整页不成立；`xhigh` 不能改写成 `ultra`。

这与产品实验中的 Sol/high assisted Patch 是不同层：前者是 Codex 页面配置，
后者是历史受控对照的角色/输出来源。均不能由模型名字推断证据更完整或业务更正确。

[OpenAI 模型文档](https://learn.chatgpt.com/docs/models)支持选择模型/推理档位；
其中要求开启后新建任务的说明针对实验性 context management。
[术语表](https://learn.chatgpt.com/docs/glossary)将 compaction 描述为概括旧上下文。
本轮未取得用户所见模型切换提示的原句及适用版本，不能将其解释为所有中途切模型
都会损坏历史或必然降低表现。当前可操作的保证来自逐轮回查与实物核对，不来自模型自评。

### 9.3 用户决定及整页任务范围

- **宏观审核与开发提速是持续职责**：消息 18/20 要求本页接住原页宏观审核、Skills
  与开发方式改善；不能只留下当前 Patch 任务。工程认知属于 Codex 工具，产品
  Dependency/API Evidence 服务产品 Agent，两者继续分开。
- **三份 txt 全部在范围内**：消息 137/139/141/144 纠正读取范围；三个思想文本、
  九目标、五线、合同/WIP 与聊天排程都要覆盖。`.md` 用于补充工程现实，不应让旧文档
  压过用户新决定。附件中的微内核、注册表、复杂 Hook 或多 Agent 建议不是自动授权。
- **Core 已采纳**：消息 73 当时说排程仅供参考；后续消息 165 明确提出
  Fallback/Core/Full-maturity Stretch，并请求裁决 Repair/更广 Eval 移入 Stretch。
  消息 166（第 6524 行）用户回答“好，按着计划继续推进”，167 随即进入 G0→G1。
  在所回读目标页结束前，原文未撤销这个 Core 决定。一概写“十日排程从未审核”会
  丢掉已发生的采纳；本页后续的新澄清另记在第 10 节，不抹去此历史事实。
  这不等于六份 WIP 全文定版，也不替代后续 exact-diff、披露或游戏操作授权。
  Stretch 指增加完整 Repair→Revalidation 演示和更广 Eval；当前主任务遇到失败而
  必须完成的修复仍是主任务的一部分，不能以 Stretch 为由跳过。
- **辅助工具不能阻塞产品**：消息 175–177 明确正常推进，Hook/认知出现实质缺口
  再修；消息 395 明确八视图长问题“不是验收标准”。不把每个提问变成新 hard gate。
- **工程条件与真实纵向两者都要**：消息 690/694/696 要合理积极推进，并把真实
  纵向结果加到已有工程完成条件，不能以仅测试或仅一次模型成功替换其他义务。
- **全缓冲区未完成**：消息 813–827 形成当前任务、Agent 基础能力与后续任务；
  两小时广泛要求大于最后 goal 的审批前停止点。后者结束不代表其他承诺消失。
- **旧 playbook 已明确冻结**：消息 684 授权冻结；`fd76356` 完成六目录冻结。
  不读取它们来决定下一任务。讨论视频、磁盘、UI、恢复的插入问题各自有处理边界，
  不能因其混在同轮而漏掉，也不能自动替换产品目标。

### 9.4 已落地成果与全工作范围映射

本表补充第 3 节之前的成果和被漏掉的旁支。提交对象与所列关键实物本轮已只读核查；
测试数字、模型运行、Build/Runtime 都保留其**历史执行**属性，没有在本轮重跑。
详细历史执行出处直接指向原日志，避免把全部命令复制到多个控制文档。

| 消息范围 / 工作 | 已有成果与当前界限 |
| --- | --- |
| 1–36：恢复、换页、三工具提速 | 旧页记录可查，用户决定转到本页；集成 `e7523db`，19 focused、387 双 worker checkpoint、只读 review `No findings.` 为历史真实使用，xdist 独立提交 `1c9fcb5`。不由此宣称整体提速已被因果证明 |
| 37–107：首次 Fresh、Findings 首失败、六项提速工具 | 首次两次模型完整响应使 retrieval 4→8，但重复 `relation_index` 拒绝；后续 `1922f14` / `23df983` 修 keyed findings 与 Fresh CLI。`8d74610` / `3da9a92` / `9e4e591` / `d263ed9` 提交 handoff、release、Hook、lock/CI/setup 底座。支持 checkpoint 曾 889 passed；全 unit 曾有历史失败，不能称当前全仓全绿 |
| 108–177：证据语义、三 txt、九目标五线与十日改版 | 已有 Projection V2/Thin Lineage 被确认，未重造；计划拆成短执行与长决策文档，Core 后获采纳。主张、身份、新鲜度、权限不可互代；发布工具的 claim 语义限制仍在，见下节 |
| 178–266：Fresh sufficient、stream/heartbeat、Hook | 历史 Fresh 约 430.6s、2 accepted、9 queries/9 items sufficient。`4ae4f14` 实现可选流式传输并在 Fresh 启用，历史 215 checkpoint 与 6-frame 无源码 smoke；后续完整 27B Fresh 实际有独立 heartbeat。`708f5d3` 修 Hook freshness；桌面信任/完整生命周期仍未证明 |
| 267–317：exact Fresh→Planning、span owner | `2ff0b41` 交付 continuation，真实 blocked Plan 保留 `EDIT_TARGET_NORMALIZATION_UNSAFE`；`8e33076` 修 evidence window 被当 edit span，新的 Fresh sufficient 后形成 non-blocking Plan。不是 continuation 尚未实现 |
| 318–411：Coverage/Planning 分工、入口/API盘点、认知八视图 | `b478782` 的 support/edit subset 是历史桥；真实 6 support→3 edit 漏项触发后续 ownership 迁移。`cffb346` 交付薄认知 CLI；八视图是按需投影，深层语义与实际运行仍有限。MCP/CLI/HTTP/UI 是不同入口，不等于所有模块可任意跳入 |
| 412–491：Planning owner、API seam→caller | `2a5af20` 交付人辅 target selector + 确定性 Plan/Binding，旧 `a5b46b92…` 四点 Plan 真实形成；`8573d09` 修认知缺 owner anchor 仍报 observed。`5eab7a2` API bridge 与 `d8350cf` 生产 caller 均已落地，两个小模型失败不能写成 caller 不存在 |
| 492–547：API双模式、FeatureSpec Runtime、Projection | `b5cb597` 修复重启类要求漏掉 Runtime 义务；`dd28c09` / `128f0b8` 交付正式 `autonomous` / `assisted_explicit` 和程序集搜索；`2bd815d` 修重复义务。人辅只选查询，API事实来自实际程序集。旧 compile-only FeatureSpec 缺陷不能投射到当前 `fc7be8…` |
| 548–622：会话恢复、新页及视频支线 | 用户先取消恢复、后又要求恢复并返回本页继续，记录有成功恢复结果；本轮不再修日志。关联任务 `01a06ad3-79c4-7e03-aeef-f123e5a6b958` 的“当前主线执行与进度总控”已基于用户五张截图完成视频/RAG判断，未取得完整字幕；不列为未做，不称装了视频 Skill |
| 622–649：Findings context 修复与真实 Fresh | `c4216b2` 将冻结输入 73,250 bytes 降至 initial 36,173 / correction 36,474，完整 Evidence 保留，post-change账务内部处理；历史 329 passed。原日志第 19309 行 Fresh CLI 真返回：512.0209442s、2 模型调用、0 correction、14 items、sufficient，生成当前 `bd2e…` |
| 650–700：当前 Plan、API传播、Trace设计、冻结 playbook | 第 19895 行真实 Planning 输出 non-blocking 当前 `b11e…`，4 edit/10 supporting；API传播与语义影响区别被用户明确纠正，详见下节。短进程 Trace/session/flush 责任已讨论，真实 sink 未交付；冻结提交 `fd76356` 已完成 |
| 701–740：exact Patch续接、Windows路径、binding-only | `fa758b5` 接 Plan→Patch→Review→Dry-run，保存 post-call source drift 的生成事实；`66bbe80` 缩短物理 receipt 路径；`d4b7ff9` 收回 `change_id`，保留四个模型字段、旧 frozen 兼容与不可覆盖 response sidecar。第 22105 行历史 331 passed；不是第 3 节九提交才开始具备这些机制 |
| 741–771：4B失败裁决、validator误报、Sol对照 | 4B两次分别暴露 identity 错配和独立代码错误；第二次首拦 `csharp_bound_member_shadowed` 后确认有误报，`686e5f0` 修复。4B本任务 no-go不能归功于该误报。Sol/high `assisted_control` 形成 `6e30b6c… → 8f33f114… → 5f74731…`；第 22770 行真实下游通过，格式审核仍未批准，不能算本地自主成功 |
| 772–826：Qwen3-Coder one-shot、基础能力与缓冲区 | 安装并核验 `qwen3-coder:30b`；首个 one-shot 约 180.09s、11,544/1,626 tokens，4 bindings/2文件，达到 Review/Dry-run。其空白及间接调用链问题随后被发现；不能沿用当时“业务基本正确”。Agent loop、三项补充及独立后续任务已被纳入缓冲区 |
| 827–869：两小时工具往返、失败修复与一次correction | 第 2–4 节九提交及最后运行证据全部保留。真实多轮重复工具失败后默认一次 observation；最终 3次模型/1工具/1correction 到 Dry-run。第 6 节补证 cold-start 独立性回归；末次 goal 完成不等于产品语义或全buffer完成 |
| 870–873：模型磁盘清理建议 | 曾列模型删除选项，但无后续确认/删除结果；卸载驻留模型与删除模型文件不同。本轮不执行清理，不把当时磁盘数字当当前容量 |
| 874–897：换模型、全buffer核对、交接准备 | 页面切到 Astra/xhigh；`474e629` 更新四文档，`597a7a7` 加历史入口。该首次交接尚未逐轮核全页；本节完成其遗漏核对。没有证据支持量化“上下文让模型变笨多少” |

### 9.5 WIP、既往判断和仍未完成事项的关键对齐

**宏观目标有原文入口，不能仅留名称。** 九目标/五线的保留映射见
[现有战略记录](../TEN_DAY_ENGINEERING_MATURITY_DECISION_RECORD_DRAFT.md)第 404–426 行，
三份 txt 的逐项处置见第 428–511、716–852 行；当时采纳 Core 的短 Gate 安排见
[现有短执行页](../TEN_DAY_EXECUTION_PLAN_DRAFT.md)第 38–51 行。
五线是产品闭环、外部调用可靠性、RAG/ER与评测、Trace/Langfuse单向链、固定环境运行部署。
最终 manifest、README结果表、3–5分钟演示、简历和面试问答尚未交付；
`honest_degraded_portfolio_delivery`不能改名为Core达成，public alpha仍是条件结果。
永久拒绝的越权/越级证明与条件延期的PDF/OCR、多模态、模型研究、公共入口扩张和
长期Memory也必须分开；不能因为都没做就视为同类缺口或全部重新启动。

**API 证据的四层不能合并。** 当前 `bd2e…` 中
`data.items` 为 11 个 `target_source` 加 3 个 `decompiled_api`；三条 API 的
`evidence_id` 为 `evidence_4c7460797448a8a8863d2398`、
`evidence_e8ec80617f8bae0373e14635`、`evidence_5596fc147615affc7195eaf6`。
`data.requirement_coverage.findings[*].evidence_ids` 与三者交集为空。
当前 `b11e…` 的 `data.binding_registry.supporting_bindings` 含这 3 条 API，
但 `data.proposed_changes[*].supporting_binding_ids` 四项均为空。
因此 API 查询事实生成、入 EvidencePack、Plan 结构携带已发生；它对 Findings/Planning
决策的语义影响未由该链证明。自主 API 查询成功尚未证明是另一个问题。

**六份 WIP 保留原字节，旧状态不得当作新的否决权。** 短执行草案的
`draft_for_user_review` / `implementation_authorization: not_granted` 未反映后来的 Core
采纳；本次在当前合同/状态/Queue纠正解释，不覆盖用户 WIP。长决策文档中以全九目标
为硬门的段落按 Full-maturity 情景读，不能与后来 Core/Stretch 合并。
RAG 小集的战略三 Case、短页 G4 的 4–6 Case（含 2 held-out）、后来 3–5 项真实 Patch
suite 并非已证明同一输入/指标/消费者的一个任务集；不得互相替代或用一个计数证明
全部 Eval 已完成。

`ARCHITECTURE_OVERVIEW.md` 第 57–64 行仍要求先消费首份 BetterHitFeedback 包；
`SPEC_COVERAGE_MATRIX.md` 第 63–69 行仍保留 `c48b5e8`、12 WIP 和旧 BHF snapshot。
这些不是 9 月当前 AccurateCrosshair 入口。现行选择以 Active 第 1.1 节为准；
保留历史，不通过静默修改 WIP来制造一致。
同样，RAG目标草案第 2116–2241 行的 `as_of:2026-08-16`、BHF目标与next action
是历史设计/校准上下文；模型比较文档第 428–451 行保存旧2×2实验及暂停点，
不能替代当前Qwen3-Coder结果，也没有因本次成功自动恢复正式比较实验。

**需要带走的已知工程欠账**：

- handoff helper 多次 1500-token 超限、Windows direct-script 长时间运行及 `runpy`
  绕行已在消息 186–404 记录；不能只写 task packet stale，也不能断言增加 token 上限
  就能解决。后续按一次聚焦诊断处理，不能挡当前产品。
- release packager 的 `_projection_status` 当前按 verified refs 和同 commit 返回
  `demonstrated`，但这不足以证明任意自然语言 claim。历史消息 124/132 已指出，
  当前 `.agents/skills/release-evidence-packager/scripts/package_release_evidence.py`
  第 361–375、421–431 行仍如此。发布前逐条核对主张范围，不把工具标签当语义证明。
- explicit Patch continuation 已不以 `latest` 决定准入；旧 Planning continuation 的
  latest迁移在消息 700 明确后移，当前 `fresh_planning_continuation.py:483` 仍有该检查。
  不将一次 Patch修复写成全 stage统一，更不自动启动迁移。
- Trace应关联内部 run identity、独立 invocation和共享 session，短CLI退出前flush；
  exporter故障不能改变产品路由，评测分数不是权限。现有 injected transport不证明
  真实生产sink。GitHub迭代可见性、remote备份/PR、hosted CI与发布材料也没有由本次
  本地提交核查证明；历史讨论不授权本轮push或发布。
- 原始模型/运行例证各有限制：27B Fresh成功不能覆盖其旧Patch超时，4B Patch no-go
  不能推广到所有角色，Sol对照不能冒充本地自主，Qwen one-shot/loop不同条件不能当
  单变量因果实验。Router、多真实任务Eval、通用correction、compiler/test和Runtime
  feedback都仍需各自产品证据。

本轮已把当前 P0 推进到“原重启义务下存在已定位的共享状态回归，先修订 Patch”，
而非继续等待对原diff审批。后续排序仅在 Queue维护；不自动重跑旧Actual，不重建
八张图、第二Graph或新的长期任务账本。

### 9.6 本轮实际验证

本轮为完整回读、交接修订和静态产品审查。执行了工程认知 summary、Git只读核查、
日志解析及双记录正文一致性比较、附件/日志文件hash、六份当前Artifact的canonical
hash、两份response bytes hash和diff文本hash核对，均与所引用身份一致。
没有运行pytest、真实模型、Build、Actual、Apply或游戏，没有改写产品源码或原Artifact。
四个当前入口文档的修订不把历史439/478/90等结果升级为本轮或最终HEAD全仓回归。

收口核验：18 个本地文档链接解析后全部存在；六份原有 WIP 的 SHA256 与本轮改动前
一致，目标 rollout 的 SHA256 也未变化。28 个前置提交均为当前 HEAD 的祖先。
独立复核读取了四份文档完整 diff，并对照原文及共享状态源码，未发现剩余实质错误。
文档检查命令：

```text
git diff --check -- docs/ACTIVE_PRODUCT_CONTRACT.md docs/PROJECT_STATE.md docs/IMPLEMENTATION_QUEUE.md docs/audits/PATCH_AGENT_PROGRESS_RECONCILIATION_20260905.md
```

结果：通过。本次四文档修订留在工作树，未暂存或提交；原有六份 WIP 保持原状态。

## 10. 本页后续澄清：完整七组建设就是十日目标

用户先要求“把当前 AccurateCrosshair 这条 case 推过真实 blocker；不要把这次 case
继续扩成整个项目的长期建设。然后马上回到真正的完整建设目标”，随后以截图明确
当前 P0 是真实 Mod 的正确修改/Build/Runtime，项目目标是可重复、可追踪、可评测、
可交付的生产级 Coding Agent。用户进一步纠正：**“这些所谓长期目标才是真十日目标。”**

因此，本页先前“十日 Core 只是阶段性交付目标”的执行解释撤回。第 9 节准确保留了
旧页 Core 采纳历史，但不能继续用该历史把以下建设默认推到 Day 11+ 或无限期长期目标。

| 十日建设范围 | 要交付和验证的方向 |
| --- | --- |
| 端到端 Coding Agent | 自然语言需求经 FeatureSpec/Evidence/Planning/Patch/Review/Approval/Apply/Build/Runtime；真实失败进入 Repair/Revalidation，最终交付可运行产物 |
| 生产 Evidence/RAG | 自主 API discovery、自主 target selection、来源与 freshness、support/conflict/gap、覆盖度和 API Evidence 的实际语义消费；不能只证明结构携带 |
| Agentic Execution | 模型使用工具和 observation、有界 correction、compiler/test/runtime feedback；覆盖明确真实失败及停止边界，不以任意错误必可自动修复为声明 |
| Trace/Lineage/Langfuse | 真实生产 sink、run/invocation/session 关联、短进程 flush 和证据绑定的评分；观测系统继续是单向 consumer |
| Model Qualification / Routing | 基于真实任务资格结果形成 role→可用 profile；保留各模型/角色/输入的资格边界 |
| 固定任务 Eval | 冻结真实任务集，衡量 Evidence、Patch、Review、Build、Runtime、Repair、工具回合、tokens与延迟；不能以一个 case 代替稳定性 |
| 环境/CI/Release | 锁依赖、实际干净环境重建、hosted CI、可重复 Build、release manifest、README、演示与交付材料 |

这七组是既有五线与相关目标的展开，外部调用可靠性继续贯穿其中；不是新建七套控制系统。
把它们纳入十日目标不等于已经实现，也不把任意仓库/语言、无限任务、任意故障恢复等
未约定的泛化加入目标。当前所需权限仍沿用现有边界。

当前执行顺序保持：先有界解决 AccurateCrosshair 的已知真实 blocker，推进必要的
Build/Runtime；完成后立即返回上述完整建设。若该 case 被独立权限或环境条件阻塞，
必须记录其精确未完成状态并推进不依赖它的十日工作，不能拿等待或扩大 case 消耗整个计划。
已有十日草案的旧 Gate 预算不再证明完整七组范围可执行，后续排程应按实际剩余工作量
调整；出现时间冲突时明确报告并由用户决定取舍，不自动降成“只做 Core”，也不把诚实
报告或局部成功改写成十日目标全部完成。六份用户 WIP 仍保持原字节。

## 11. 本页有界 P0 推进：源码单元、新 Findings/Plan 与当前请求阻断

### 11.1 主体与失败来源

用户明确要求由**产品 Agent**生成 Mod 修订。工程侧研究修法不等于产品自主修复；
本页曾准备探索 assisted response 导入，但在用户纠正后停止该路线，没有生成或导入
工程修订 `after_text`，没有写 canonical Mod。测试只使用原基线和原 Proposal 中已存在
的错误代码，独立 expected/Harness 不交给产品模型。

原 deterministic `ProposalReview` 已通过。失败来源是后续工程/人工语义复核及其行为
反例，不能改写成原 Review 已检测出语义失败。用户另外明确：关闭 Accurate Spread 后，
First Shot Match **保留现有首发准确尺寸效果**，不改成基于游戏原尺寸缩小。

### 11.2 已实现并验证的源码单元修复

新增检索曾把 `GetCrosshairSize()` 表达式方法当作第 157–179 行窗口；字段检索也会跨入
邻近成员。提交 `aa3a72f77844edd98102494e4a576523736ffe1d` 只修改
`src/mod_agent/evidence/rg_live.py` 和 `tests/unit/test_rg_live_evidence.py`：完整单行表达式
方法及字段使用准确物理单位，并拒绝将注释伪声明、同一行多个声明标成单个精确单位。
本例方法为 167–167，`_targetSpread` 为 28–28。复杂多行形态未升级成完整 C# parser。

先复现范围错误，后补已发现的注释/多声明边界；最终相邻 checkpoint：

```powershell
python -B -m pytest tests/unit/test_rg_live_evidence.py tests/unit/test_requirement_coverage.py tests/unit/test_fresh_planning_continuation.py -q --tb=short -n 2 --dist=loadfile --basetemp="$env:TEMP\rgunit-final-$PID"
```

结果：176 passed，23.69 秒，2 个既有 jieba warnings；两文件 Ruff 与 diff check通过。
这证明测试覆盖的检索行为，不证明新 Mod Patch、Build 或 Runtime。

### 11.3 实际 C# 的有界负例与行为矩阵

本轮以真实七份 Mod C# 源码及外部引擎/配置 doubles 编译运行，保留原基线和原错误
Proposal两种输入。初次12进程捕获 Recoil、Match、Inner cold-start 回归；随后按用户
列出的范围扩至 `2源码 × 2开关 × 7场景 = 28进程`，不是28个独立真实产品任务。

[Harness说明及命令](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_behavior_repro/README.md)
与[28进程结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_behavior_repro/behavior_matrix_results.json)
绑定实际输入；结果文件 SHA256 为 `990d67fce977a2ac57165fb470384cdb8bf355d773dea0404e3cb978f112184d`。
执行命令为该目录的 `python -B prepare.py`、`.\compile.ps1`、`python -B verify.py`。
true七场景观测与基线一致；false cold-start捕获已有三条回归。false且FirstShot=None
的冷启动普通回调保留raw，warm true→false的回调/协程则暴露旧状态覆盖问题。
warm诊断不升级成“分别重启”的原验收硬门；Pop还没有专门场景。
这不是 GTFO Runtime、依赖ABI或完整产品Build验证，当前不再扩此Harness。

### 11.4 一次真实增量 Findings 与新 Plan

任务局部编排复用现有 `RgLiveEvidenceProvider`、
`StructuredModelRequirementCoverageProvider.findings`、`build_requirement_coverage_pack`、
`ImplementationPlanner`、`ArtifactStore` 和 Patch preflight，没有新 Artifact 类型或控制面。
保留未变 FeatureSpec 与已验证 projection；旧有效 Evidence加新增精确源码共29项
整体进入新 Findings，不复制旧 findings 或旧模型执行收据冒充新结果。

本次唯一模型命令：

```text
python C:\Users\10160\.codex\visualizations\2026\09\05\01a07014-bccb-7420-bbcd-38defc72fecb\run_case_findings.py execute
```

结果：`qwen3.6:27b`，一次 Findings，0 projection，0 correction，357.30秒，
9,415 prompt tokens / 543 completion tokens；新 Coverage为sufficient。
这是部分重算，不是新的完整 Fresh run，也没有通过要求完整 Fresh收据的 Planning continuation。

| 对象 | 精确 Artifact hash / 实物 |
| --- | --- |
| 新 EvidencePack | `10a3fadd00b7437ee988729f8e78cab1d559f2f3bb774920da5ffbb45c17d3fe`；[实物](../../artifacts/g1_assisted_findings_context_repaired_27b_fc/store/features/feature_66e54ec4a116/r/evidence_pack/10a3fadd00b7437ee988729f8e78cab1.json) |
| 新 Plan | `c760a9cc2e04110c0f5a8fa1f6efcb8d661169fbdf76776596232f795100d129`；[实物](../../artifacts/g1_assisted_findings_context_repaired_27b_fc/store/features/feature_66e54ec4a116/r/implementation_plan/c760a9cc2e04110c0f5a8fa1f6efcb8d.json) |
| 新 Findings receipt | [执行记录](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_revision/findings-receipt.json)及同目录原始response/provider request |
| Planning receipt | [执行记录](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_revision/planning-receipt.json)；0模型、明确`explicit_operator_assisted`目标选择 |

新Plan保留原四目标，新增`UpdateCrosshairSize`的53–60范围；`AdjustCrosshairSize`、
两个`GetCrosshairSize`及其他新增源码保留supporting，不自动给全部方法写权限。
Bindings通过正式change-support集合检查，现有`preflight_patch_continuation`通过。
工程侧将已核实的失败与用户澄清写入新Plan的既有`side_effect_boundaries`，没有提供
正确实现；这不等于已有自动语义反馈→上游回退→重新规划产品闭环。

### 11.5 当前精确 blocker 与剩余决策

`run_case_patch.py`不带`execute`执行现有生产producer与Agent adapter的零网络请求检查。
它在发送前得到：

```text
failure_classification = provider_request_context_budget_exceeded
provider_body_utf8_bytes = 65821
num_predict = 4096
configured_num_ctx = 49152
conservative_required_context = 69917
```

[完整离线结果](C:/Users/10160/.codex/visualizations/2026/09/05/01a07014-bccb-7420-bbcd-38defc72fecb/case_revision/patch-preview.json)。
新Patch网络/模型调用均为0，没有新Proposal/Review/Dry-run，也未消费真实Patch attempt。
这里证明字节代理拒绝了请求；尚无这份请求在Qwen3-Coder tokenizer下的实测长度，
不能写成已证明真实上下文溢出，也不能写成已实测确认误判。

离线体积分析发现binding与supporting输入重复包含成员metadata。仅把完全相同的
`declared_members` / `declared_member_types`改成引用的纸面投影仍不能保证通过当前门，
因此没有把该实验写成修复、修改生产prompt、移除验证或盲目加大`num_ctx`。

P0已形成精确路径阻断。下一有界能力应在七组十日建设中的上下文/外部调用可靠性
范围评估；不继续从本Mod扩出通用框架。工程可先查重复表示与真实计数/可验证估计，
但实现规则改变必须有证据、聚焦验证和明确的当前作用域。其它十日能力不因这一条
请求受阻而全部停止。`EditAuthority`的范围批准与新diff的人工语义/exact批准保持区分。

## 12. 两小时执行窗口

用户已授权执行工作包。T0为2026-09-05 08:44:24 UTC（北京时间16:44:24），截止10:44:24 UTC。
主线是A1生产输入表示→A2真实Agentic Patch与新修订验证；A3自主Planning独立并行。
工程侧不得提供正确Mod实现；新增exact diff与实际游戏操作按包内边界处理。
具体执行结果在本节续记，不将两小时结束等同于P0或七组十日目标完成。
