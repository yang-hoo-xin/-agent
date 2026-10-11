# 本地模型严谨对比评价实验协议与报告

```yaml
document_status: experiment_protocol_and_report_template
repository_normative: false
execution_authority: none
product_quality_authority: none
created_at: 2026-08-15
scope:
  - local_model_selection
  - rag_1a_agent_model_diagnostics
  - structured_output_reliability
  - quality_latency_memory_tradeoff
current_experiment_level: level_1_bounded_protocol_diagnostic_paused
current_pause_reason: await_stable_post_identity_materialization_model_interface
formal_model_selection_status: not_started
```

> 本文独立于 RAG/ER 产品目标、控制面合同和 Golden 数据资产。它规定如何产生有说服力的本地模型实验报告，但不授予默认模型晋级、产品质量批准或执行权限。
>
> 当前单条 BetterHitFeedback（BHF）运行只用于定位真实失败，不构成正式模型排名。正式评价必须满足本文规定的升级门槛。

## 1. 原始笔记要求

原始笔记对模型对比研究的要求如下：

> “选择三个模型，例如 Llama 3.2 3b、phi-4 mini 和 mistral 7b，在完全相同的硬件上测试它们，比较内存占用、每秒 token 数，以及它们在一套标准化的 30 到 50 条测试 prompt 上的输出质量，把实际数据和分析写成简洁的技术报告。”
>
> “用系统性数据做选择，而不是采用社交媒体上最流行的模型。”
>
> “如果要进阶就使用模型量化的版本，去记录质量与速度之间的取舍。”

来源：[原始笔记：模型对比研究](C:/Users/10160/.codex/attachments/c1460aa6-116c-4587-acfa-4978e144c88d/pasted-text.txt:414)。

笔记还要求：

- 固定 Prompt/config/model/index 身份，进行 smoke、nightly、held-out 和成本报告。见[原始笔记：持续质量](C:/Users/10160/.codex/attachments/c1460aa6-116c-4587-acfa-4978e144c88d/pasted-text.txt:347)。
- 记录每秒生成 token、首 token 延迟、总响应延迟。见[原始笔记：本地推理测量](C:/Users/10160/.codex/attachments/c1460aa6-116c-4587-acfa-4978e144c88d/pasted-text.txt:388)。
- 使用 JSON Schema、确定性验证和对所有模型完全一致的一次重试策略。见[原始笔记：结构化输出](C:/Users/10160/.codex/attachments/c1460aa6-116c-4587-acfa-4978e144c88d/pasted-text.txt:398)。
- 在独立保留集上测量 JSON 有效率、完全匹配准确率和正确拒答率。见[原始笔记：独立评测](C:/Users/10160/.codex/attachments/c1460aa6-116c-4587-acfa-4978e144c88d/pasted-text.txt:481)。

本文将这些要求落成可复现的实验协议，不把示例模型、单次运行或某个量化版本预先写成产品结论。

## 2. 评价目标与归因边界

模型比较需要回答四个不同问题：

1. 模型能否稳定遵守当前结构化交互协议；
2. 在检索结果和工具接口完全相同时，模型能否作出更相关的工程选择；
3. 模型能否完成 RAG-1A 的发现、验证和充分性判断，而不读取 Golden expected；
4. 质量提升是否值得增加的内存、延迟和运行成本。

不得把下列问题混成“模型能力”：

- 相关源码没有进入输入窗口：属于检索或排序问题；
- 相关源码已经进入窗口但模型选择无关标识：属于当前模型、当前任务表示和当前选择接口的组合结果；
- metadata 身份无法进入 IL：属于工具接口或身份表示问题；
- Golden 泄漏进 actual 输入：属于评测污染；
- Store 回读改变语义：属于持久化正确性问题；
- 结构化输出无法解析：属于协议遵循与运行可靠性问题。

实验报告必须分别登记这些失败层，不能把工具或检索失败归因于模型，也不能把模型选择失败归因于控制面。

## 3. 实验成熟度与升级门槛

### 3.1 Level 0：有界故障诊断

用途：用一条真实请求确认某个精确失败是否只出现在特定模型上。

允许：

- 同一请求、同一冻结输入、同一 response format；
- 只更换模型；
- 运行到第一个需要比较的步骤即停止；
- 保存原始输出、解析结果、模型身份和运行耗时。

禁止据此声称：

- 默认模型已经选定；
- 某模型整体优于另一模型；
- RAG-1A、Golden 或产品质量已经通过；
- 结果可以泛化到其他任务、Prompt、量化或硬件。

当前 BHF `selection_ids` 对照属于此级别。

### 3.2 Level 1：协议校准实验

升级条件：

- RAG-1A 的相关步骤能够在至少一条正向任务和一条负向任务上真实运行；
- Prompt、Schema、重试策略和工具接口在实验期间冻结；
- 准备 5～10 条覆盖不同失败类型的 calibration/development 任务；
- actual 在读取 expected 前已经保存；
- 能区分检索、选择、工具、证据推理和持久化失败。

此级别用于验证实验脚手架和指标能否工作，仍不产生正式模型排名。

### 3.3 Level 2：正式模型对比研究

只有同时满足以下条件才升级：

- 30～50 条标准化任务已经冻结并完成独立复核；
- 至少包含一个未参与 Prompt、排序和参数调整的 held-out 子集；
- 三个模型均可在同一硬件、同一 Ollama 版本和等价运行配置下合法运行；
- 每个模型的精确 tag、digest、参数规模、量化和上下文身份可取得；
- Prompt、Schema、代码、数据集、索引和 corpus snapshot 均有稳定身份；
- 统一 runner 能保存原始输出、解析结果、实际工具轨迹和性能数据；
- 失败样本不会从统计中静默删除；
- Golden expected 在 actual 运行结束前不可见。

Level 2 才能形成“默认模型建议”或“本机环境下的质量/性能结论”。

### 3.4 Level 3：量化与压缩实验

在 Level 2 已经确认模型家族后，再比较同一模型的不同量化。必须保持数据集、Prompt、上下文和 runner 不变，报告质量、速度、内存与稳定性的变化。量化实验不得与模型家族比较混成同一结论。

## 4. 标准化任务集

正式任务集建议覆盖以下类型：

| 类型 | 主要观察 |
|---|---|
| 精确代码符号 | exact/symbol 命中和精确身份保持 |
| 中文自然语言与英文代码标识 | 跨语言需求理解与工程词汇定位 |
| 模糊功能需求 | 从用户表达形成工程问题，而非复述需求 |
| 多个相似标识 | 相关选择、错误选择和排序敏感性 |
| 无相关标识 | 正确停止与拒绝编造 |
| 来源不足 | `insufficient/block` 是否正确 |
| 当前版本冲突 | 是否拒绝过时来源和历史实现 |
| source → metadata → IL | 动态身份能否完成精确验证 |
| 正向规划边界 | 是否在证据足够时避免错误阻止 |
| 负向规划边界 | 是否在证据不足时避免错误继续 |

任务来源应优先采用真实项目历史、真实失败和当前版本证据。可以用模型生成同义表达，但不得让模型生成 Golden 技术事实。BHF 与 WallCrawler（WC）可作为 calibration/development Case，不得冒充 held-out 成绩。

## 5. 必须冻结的实验变量

每次运行至少保存：

```yaml
run_identity:
  run_id:
  started_at:
  hardware_identity:
  operating_system:
  ollama_version:
  model_tag:
  model_digest:
  parameter_size:
  quantization:
  context_length:
  temperature:
  seed:
  thinking_enabled:
  streaming_enabled:
  max_output_tokens:
  retry_policy:
  prompt_sha256:
  schema_sha256:
  code_revision:
  dataset_version:
  corpus_snapshot_sha256:
  index_identity:
  inventory_sha256:
  inventory_order_sha256:
```

约束：

- 同一比较批次只改变模型身份；
- 三个模型使用同一任务顺序或预先登记的平衡顺序；
- 正式计时前允许一次不计分的 warm-up，并单独报告 cold start；
- 运行期间避免其他重负载任务影响内存和延迟；
- 不为某个模型单独修改 Prompt、Schema、inventory、Top-K 或重试次数；
- 若模型无法使用同等量化或上下文，必须在报告中登记为混杂变量；
- `temperature=0` 的可靠性主实验与 `temperature=0.7` 的随机性敏感实验必须分开报告。

## 6. 指标体系

### 6.1 结构化输出与选择层

- JSON/Schema 有效率；
- 首次输出有效率；
- 一次统一纠正后的有效率；
- 完全匹配准确率；
- 相关稳定身份的选择精确率和召回率；
- 禁止稳定身份命中率；
- unknown handle、重复 handle 和越界选择率；
- 无相关项时的正确停止率；
- 错误继续率与错误阻止率；
- 同一任务重复运行的一致率。

短 handle 只属于单次运行。评分时必须先由确定性代码把 handle 解析为稳定来源/标识身份，再与隐藏 expected 比较，不能跨运行直接比较 `sNN` 字符串。

### 6.2 RAG/ER 与 Agent 层

- 必需证据 Recall@K；
- MRR 或 nDCG@K；
- source authority precision；
- stale evidence rate；
- required/support/conflict/missing 关系覆盖；
- 动态 metadata 身份绑定成功率；
- IL 精确验证成功率；
- planning sufficiency 正确率；
- planning action 正确率；
- EvidencePack commit/read/strict rehydrate 成功率；
- 答案泄漏率；
- 失败阶段归因准确率；
- 完整任务成功率。

RAGAS 类指标只可辅助测量上下文和回答质量，不能替代 Hook、来源权威、当前版本身份、IL 验证和 planning judgment 指标。

### 6.3 性能与资源层

- 首 token 延迟；
- 总响应延迟；
- 输入 token、输出 token；
- 输出 tokens/s；
- Prompt evaluation 与 generation duration；
- 峰值系统内存和显存；
- 每条任务模型调用次数；
- 每条任务工具调用次数；
- 每条成功任务的总耗时；
- 超时、进程失败和预算耗尽率。

本地模型没有可直接比较的 API 美元成本时，不虚构美元数值；优先报告时间、token、内存/显存和可实际测得的能耗。

## 7. 重复运行与统计

正式 Level 2 建议至少：

```text
30～50 条任务 × 每条 3 次 × 3 个模型
```

报告：

- 每个指标的样本数；
- 平均值、中位数、标准差和最差值；
- 成功率及 95% 置信区间；
- 同一任务上的配对差异；
- 失败类型分布；
- 冷启动与预热运行分离结果；
- 预先登记的异常值处理规则。

原则：

- 超时、非法输出和工具调用失败属于结果，不能从分母删除；
- 小样本差异应报告效应大小和不确定性，不用单次百分比宣布胜负；
- 二元成功结果优先采用同任务配对比较；
- 平均延迟受长尾影响时，同时报告中位数和高分位数；
- 每个模型保留逐任务原始记录，以便第三方复算汇总。

## 8. 一致的执行协议

每个模型执行相同流程：

```text
冻结 request / corpus / prompt / schema
→ 运行 actual
→ 保存原始模型输出与 provider timing
→ 确定性解析和验证
→ 若协议允许，执行一次不含答案的同构纠正
→ 保存最终 actual 与失败阶段
→ actual 冻结后读取 expected
→ 计算质量、可靠性和性能指标
→ 生成逐任务记录及汇总报告
```

不得：

- 在 actual 前读取 Golden annotation；
- 因某个模型失败而修改任务或 expected；
- 给不同模型不同数量的纠正机会；
- 将完整历史实现、已知 Hook 或旧 Agent 输出放入输入；
- 把运行时格式错误隐藏成“无结果”；
- 在比较结束后挑选对某个模型有利的子集作为主结果。

## 9. 晋级与选择规则

以下属于硬失败，不能由平均分抵消：

```yaml
answer_leakage: must_be_zero
unknown_handle_accepted: must_be_zero
forbidden_final_selection_on_critical_case: must_be_zero
false_continue_on_critical_negative_case: must_be_zero
artifact_identity_corruption: must_be_zero
actual_expected_order_violation: must_be_zero
```

通过硬门后，模型选择采用多目标比较，不强行压成一个不透明总分：

1. 先比较工程质量与可靠性；
2. 再比较延迟、内存和吞吐；
3. 明确展示质量提升需要付出的资源代价；
4. 若两个模型质量差异落在不确定范围内，优先选择资源更低或稳定性更高者；
5. 若没有模型通过硬门，结论应是当前组合不满足要求，而不是勉强选出第一名。

任何默认模型建议必须引用精确实验报告、数据集版本和模型 digest。社交媒体评价、排行榜印象或单条 BHF 结果不能成为晋级依据。

## 10. 当前有界诊断登记

```yaml
experiment_id: rag1a_bhf_identifier_selection_diagnostic_20260815
experiment_level: level_0_bounded_failure_diagnostic
formal_ranking_eligible: false
task_count: 1
baseline_model:
  tag: qwen3:4b-instruct
  digest: 0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0
comparison_model:
  tag: phi4-mini:3.8b-q4_K_M
  digest: 78fad5d182a7c33065e153a5f8ba210754207ba9d91973f57dffa7f487363753
  parameter_size: 3.8B
  quantization: Q4_K_M
  status: selection_only_completed
frozen_input:
  task: better_hit_feedback
  identifier_inventory_size: 64
  response_shape: action_plus_selection_ids
baseline_observation:
  selected_ids:
    - s42
    - s33
    - s34
    - s22
  relevant_damage_or_reaction_identity_selected: false
comparison_observation:
  selected_ids:
    - s01
    - s10
    - s42
    - s44
  selected_stable_identities:
    - System.Runtime.InteropServices
    - System.Runtime.CompilerServices
    - EnemyBehaviour
    - XXHash
  relevant_damage_or_reaction_identity_selected: false
  input_tokens: 4124
  output_tokens: 26
  elapsed_seconds: 2.592994499980705
  metadata_dispatch_count: 0
  il_dispatch_count: 0
input_space_observation:
  lexical_damage_bullet_or_melee_identity_count: 5
  explicit_reaction_hitreact_or_stagger_identity_count: 0
  exact_reaction_direction_available_in_inventory: false
protocol_identity:
  baseline_ollama_version: 0.32.11
  comparison_ollama_version: 0.32.13
  ollama_version_matched: false
  request_sha256: 975612665FF3779774E09D189D1C7877E31E34B5E924C07D0E1CD2050E005187
  frozen_plan_raw_sha256: 89A84CAF5A999C177DF9F544CED1CB80105877C6D77B0FFB7016A5F75A868CA9
  inventory_file_sha256: 666C9E22C477021A0D321331748378BEABD54CF4DD9FEF30A4CF0CC5DA4371DA
  model_inventory_sha256: BE2129AF08BE241F219FD4819CA33808E7D80B8664E81D65C39F3EC500FFF0E8
  response_schema_sha256: 6E507FD8BFADA994723311263F92E09A0F29E980F6A00D61B21D6D0ED3F4A6F1
  phi_report_sha256: BCEC41A1C20AB75624A5DADBC700705A7D4BA42B5DECA26EE026FC40638BD20D
excluded_preliminary_runs:
  count: 2
  reason:
    - incomplete_refs_in_reporter_postprocessing
    - unnormalized_plan_envelope_passed_to_reporter
  tool_dispatch_occurred: false
conclusion:
  - qwen3_4b_failed_current_bhf_identifier_selection
  - phi4_mini_3_8b_failed_current_bhf_identifier_selection
  - cross_model_identifier_selection_failure_under_shared_frozen_plan_and_inventory
  - shared_input_space_does_not_expose_explicit_reaction_identity
  - result_does_not_compare_independent_planning_ability
  - runtime_version_difference_prevents_formal_model_ranking
  - no_default_model_decision
```

上述 `sNN` 只用于定位各次运行，不能作为跨运行 expected。Phi-4 Mini 结果已经解析为稳定身份；正式报告见 [phi4_selection_only_report.json](C:/Users/10160/.codex/visualizations/2026/08/11/019ff15f-9eac-7b13-aad5-faffde4b36b7/runtime_replay/rag1a_source_bridge_20260815/better_hit_feedback/phi4_selection_only_report.json)。

本次结果只证明：两个模型在同一个由 Qwen 基线运行形成的冻结 plan 和同一份64项输入清单下，都没有选择宽泛的 damage/bullet/melee 相邻标识。它没有比较两个模型各自从自然语言形成 Requirement Projection 和 Search Plan 的能力，也没有证明所有模型都会失败。

Qwen 基线运行的 Ollama 版本为 `0.32.11`，Phi-4 Mini 正式运行的版本为 `0.32.13`。Level 0 可以把它保留为带混杂因素的诊断证据，但 Level 2 正式比较必须在相同运行时重新执行，不能直接复用本次数字形成模型排名。

输入清单本身只有5个包含 `damage`、`bullet` 或 `melee` 的宽泛标识，没有包含 `reaction`、`hitreact` 或 `stagger` 的精确标识。因此不能把失败单独归因于模型；下一工程步骤应测量清单的相关性排序、信息密度、查询来源和任务表示，确认相关工程方向能否进入模型可见输入。该审查不得读取 Golden 后把正确 Hook 或专用同义词写回检索路径。

动态单方法 IL 适配属于独立工具能力，不计入 selection-only 模型对照成绩。只有进入完整 RAG-1A 实验时，才记录 metadata/IL 工具成功率。

### 10.1 共享两回合 2×2 Planning 诊断

2026-08-16 在同一 Ollama `0.32.13`、同一共享两回合 Requirement Projection/Search Planning 接口下完成了 2 个模型 × 2 个任务的 planning-only 诊断。该诊断禁用工具调用，不读取 Golden 或历史 Hook，只验证协议结构与有限语义表现。

报告：`runtime_replay/rag1a_source_bridge_20260815/better_hit_feedback/planning_2x2_report.json`

```yaml
experiment_id: shared_two_turn_planning_2x2_20260816
experiment_level: level_1_bounded_protocol_calibration_diagnostic
formal_ranking_eligible: false
report_sha256: 67DF97B43095A1AFE57C38D19C2A26FA1707565BB772FBC8E2B3458C516A27C3
base_revision: c48b5e82fe3eed524d5c9f868980748136e28bfd
golden_accessed: false
historical_hook_accessed: false
tool_dispatch_allowed: false
runs:
  - model: qwen3:4b-instruct
    task: better_hit_feedback
    result: executable_plan
  - model: qwen3:4b-instruct
    task: terminal_authentication_lights
    result: executable_plan
  - model: phi4-mini:3.8b-q4_K_M
    task: better_hit_feedback
    result: planning_failed
    failure: QUERIES_INVALID
  - model: phi4-mini:3.8b-q4_K_M
    task: terminal_authentication_lights
    result: planning_failed
    failure: SEARCH_PLAN_LANE_QUESTION_COVERAGE_INVALID
```

这个结果支持的结论仅为：在当时的共享两回合协议下，Qwen 两条 planning-only 输入被确定性校验接受，Phi 两条输入均形成闭合 JSON，但没有通过查询或拓扑语义校验。它不能证明 Qwen 的完整 BHF 能力更强；随后同一 Qwen 完整 BHF 仍因重复 `requirement_ids` 在零工具调用处失败。

### 10.2 Phi 输出上限与拆回合诊断

在 2×2 之前，Phi 的一体式 BHF Planning 使用 `8192` 输出 token 仍在上限处截断：`stop_reason=length`、输出 `8192` token、JSON 未闭合。报告 SHA256 为 `909C2148F08C80500F5EBEDA9AA9156405A60BA19F2219AEEFE1A6CB4E72E614`。这证明当时一体式表示对该模型不可执行，但不证明 inventory 容量、整个 Discovery Loop 或 Phi 在其他接口下不可用。

拆成 Requirement Projection 与 Search Planning 两个有界回合后，Phi 可以返回闭合 JSON；完整 BHF 随后在 `SEARCH_PLAN_QUERY_FAMILY_INVALID` 停止，工具调用为零。报告 SHA256 为 `063610545089FDCB4C97A8F8EA9BDE93A383128A78FB884F1E0EEEEE4FD07167`。

因此两回合改造解决的是传输与结构上限，不自动解决工程语义、查询质量或 identity 记账问题。

### 10.3 当前暂停点、未完成项与恢复门槛

```yaml
level_0_selection_diagnostic: completed
level_1_planning_2x2_diagnostic: completed_under_pre_identity_materialization_protocol
level_1_protocol_calibration: not_closed
level_2_formal_model_comparison: not_started
level_3_quantization_tradeoff: not_started
default_model_selection: not_granted
pause_reason:
  - production_model_interface_is_changing_to_deterministic_identity_materialization
  - old_planning_results_cannot_rank_models_under_the_new_interface
  - coding_agent_v0_vertical_delivery_has_higher_priority
```

模型实验不是被取消，而是在模型不再承担 requirement/question/family identity 后等待新的稳定模型接口。恢复时不得从零重做全部历史诊断；只执行以下最小顺序：

1. 新接口形成稳定 checkpoint；
2. 使用完全相同的新接口重跑 Qwen/Phi × BHF/无关任务的一次 2×2 planning-only smoke；
3. 只判断协议可执行性，不做模型排名；
4. Coding Agent v0 或完整 RAG-1A 真实运行证明模型选择成为产品瓶颈后，才决定是否进入 30～50 条任务、三模型、重复运行和 held-out 的 Level 2；
5. Level 2 完成前不得用本节结果改变默认模型。

当前不应为了“补完一半实验”立即启动长基准。正确收尾是保存上述报告身份、失败上限和恢复触发条件，然后让产品主线继续前进。

## 11. 正式实验报告模板

### 11.1 实验摘要

```yaml
experiment_id:
experiment_level:
hypothesis:
dataset_version:
task_count:
repetitions_per_task:
held_out_task_count:
hardware_identity:
ollama_version:
code_revision:
prompt_sha256:
schema_sha256:
corpus_snapshot_sha256:
```

### 11.2 模型身份

| 模型 | Digest | 参数规模 | 量化 | Context | 是否满足固定条件 |
|---|---|---:|---|---:|---|
| 模型 A |  |  |  |  |  |
| 模型 B |  |  |  |  |  |
| 模型 C |  |  |  |  |  |

### 11.3 质量与可靠性结果

| 指标 | 模型 A | 模型 B | 模型 C | 置信区间/说明 |
|---|---:|---:|---:|---|
| 首次 JSON 有效率 |  |  |  |  |
| 完全匹配准确率 |  |  |  |  |
| 相关选择召回率 |  |  |  |  |
| 禁止选择命中率 |  |  |  |  |
| 正确停止率 |  |  |  |  |
| planning action 正确率 |  |  |  |  |
| 完整任务成功率 |  |  |  |  |

### 11.4 性能结果

| 指标 | 模型 A | 模型 B | 模型 C | 说明 |
|---|---:|---:|---:|---|
| 首 token 延迟 |  |  |  | cold/warm 分开 |
| 总响应延迟 |  |  |  |  |
| 输出 tokens/s |  |  |  |  |
| 峰值内存 |  |  |  |  |
| 峰值显存 |  |  |  |  |
| 每条成功任务总耗时 |  |  |  |  |

### 11.5 失败归因

| 失败层 | 模型 A | 模型 B | 模型 C | 物理证据引用 |
|---|---:|---:|---:|---|
| retrieval relevance |  |  |  |  |
| identifier selection |  |  |  |  |
| structured output |  |  |  |  |
| metadata identity |  |  |  |  |
| IL verification |  |  |  |  |
| evidence reasoning |  |  |  |  |
| persistence/rehydration |  |  |  |  |

### 11.6 结论

报告必须分别给出：

- 哪些结论被数据支持；
- 哪些差异仍落在不确定范围内；
- 哪些结果来自脚手架或工具，而非模型；
- 推荐模型及其适用边界，或明确说明没有模型满足硬门；
- 下一项最小实验，不把未验证猜测写成产品路线。

## 12. 与 RAG/ER、Eval 和 Trace 的关系

- RAG/ER 产生 actual facts，不读取 expected；
- 本文定义模型实验如何比较，不重算 EvidencePack 充分性；
- Golden 数据集拥有 expected judgment，模型实验只读使用；
- Trace 提供运行事实和关联，不授予模型晋级；
- 控制面不因模型得分自动授予 Apply、Build 或 Runtime 权限；
- 正式 Eval 可以消费本文的逐任务记录和汇总指标，但不得将实验报告写回产品机器事实；
- 在 RAG-1A 尚未产生完整正向和负向 actual 前，Level 2 正式对比不是主线阻断项。

本文应在以下时机更新：

1. 完成 Phi-4 Mini 的 Level 0 selection-only 对照时，填写当前诊断结果；
2. RAG-1A 正向与负向链成立后，登记 Level 1 升级决定；
3. 30～50 条冻结任务和 held-out 子集准备完成后，冻结 Level 2 协议；
4. 三模型重复运行完成后，形成正式技术报告；
5. 只有 Level 2 证据支持时，才讨论默认模型；
6. Level 3 单独记录量化带来的质量与速度取舍。
