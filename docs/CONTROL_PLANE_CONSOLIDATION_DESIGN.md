# 控制面收敛设计

文件名：`CONTROL_PLANE_CONSOLIDATION_DESIGN.md`  
状态：`proposed_normative_design`  
范围：仅限控制面架构收敛  
审查基线：`af178e7eb8125aa3992dcb114014214587733e08`  
实施授权：`false`  
Artifact 迁移授权：`false`  
产品源码、Build、Runtime、进程启动、游戏目录写入授权：`false`

## 1. 文档目的

本文档把已经确认的架构原则转化为一份有限、可审核、可测试的控制面收敛设计。

本文档明确规定：

- capability ownership；
- schema evolution ownership；
- Approval Identity；
- hash 与 projection 分层；
- Artifact lineage 的权威位置；
- Receipt 语义；
- public entry 与 Execution Contract；
- driver 权限和降级方案；
- 影子控制面的迁移与删除顺序；
- 审核粒度分类；
- 必须通过的测试门和完成条件。

本文档的中心问题不是“审核是否太严格”，而是：

> 平台没有稳定定义“人批准的 action 是什么”，因此执行细节、机器证据、运行观察和展示信息被混入同一个证明对象，形成过度耦合的证明体系。

当前错误关系近似为：

```text
Approval Identity
=
Action Identity
+ Execution Detail
+ Machine Evidence
+ Runtime Observation
+ Presentation
```

结果是：

```text
stdout、Store 数量或路径显示变化
→ projection 变化
→ hash 变化
→ Approval 被视为失效
→ 重新审核
```

本文档不降低证据质量、权限精度或 fail-closed 要求。它只规定哪些事实由谁拥有、
在哪一层产生、是否影响批准身份，以及怎样通过唯一公共控制面执行。

### 1.1 使用方式：同一文档、一个工作包、四个阶段

本文件同时作为架构规范和控制面收敛期间的共享修复文档。推进页与审核页围绕同一个
工作包更新本文件中对应章节的“实施合同表”，不再为同一问题建立平行设计文档。

每个工作包采用一次完整循环：

```text
一次设计 → 一次审核 → 一次实施 → 一次验收
```

1. 设计：推进页从实际代码中识别当前 semantic authority，自行选择目标实现，填写实施合同。
2. 审核：审核页检查隐藏 owner、合同扩张、兼容性和严重边界，避免接管正常实现设计。
3. 实施：合同边界确认后，推进页像开发者完成明确作业一样自行规划、编码、测试和自我修正。
4. 验收：审核页依据最终 diff、测试和 authority 转移事实判断工作包是否完成。

实施合同服务于集中确定公共决策，不记录 private helper 命名、局部 class 组织、fixture 命名、
格式化等普通开发选择。推进页可以在已确认的 semantic boundary 内自主调整这些实现细节。

只有影响 authority、公共 schema/API、Approval Identity、hash、lineage、side effect、
failure/retry/checkpoint 或历史兼容性的选择进入 `unresolved_contract_decisions`。该字段闭合后，
推进页即可实施，无需把每个内部步骤变成新的审批对象。

各章节表格中的方括号是待填写位置，不是可以原样保留的示例。工作包进入审核时，推进页将
“推进页决策”列替换为从实际代码得出的明确结论；如果公共合同仍有选择未定，就把它集中写入
`unresolved_contract_decisions`，而不是用模糊措辞隐藏。审核结论通过后，推进页继续完成实现与
验收回填，并在发现偏差时先自查语义边界、主动修正本表。

## 2. 已知结构问题

### 2.1 没有统一 capability 声明

当前 capability 支持状态分散在：

- `build_graph()`；
- `local_entry`；
- materializer dispatch；
- `ArtifactTypeRegistry`；
- run-local driver；
- focused tests。

这会产生同一个 continuation 在不同组件中被不同解释的情况。

已确认的实际表现包括：

- Graph 与 Stagger authority materializer 已能识别 bounded observation projection；
- `preflight_stagger_edit_authority_review()` 仍维护另一套 schema allowlist；
- verification-only continuation 补齐了 Graph 路径，但没有同步形成稳定的公共 Build 入口；
- 公共 Runtime continuation 仍要求自定义 verification-only Build 没有生成的
  `run_manifest.json`。

平台目前无法从一个权威位置回答：

> 哪个精确 capability 已存在、什么请求可以进入、由哪个 Graph route 执行、允许什么副作用、产生什么结果合同？

### 2.2 Approval 没有与 observation 分离

部分 run-local projection 把以下信息与 action identity 一起计算或一起强制：

- Store 总文件数和总字节数；
- stdout 字节和换行；
- Git status 展示；
- run root 是否存在；
- 时间戳和耗时；
- physical locator 或路径展示；
- 执行后才会产生的 Artifact 统计。

这些信息可能有审计价值，但它们回答的是“环境或执行发生了什么”，不是“人批准了什么”。

### 2.3 Receipt 没有足够权威的统一语义

当前 `ArtifactStore.write()` 返回 `ArtifactRef`。

ArtifactStore 已经拥有：

- immutable revision；
- latest alias；
- pending marker；
- freshness；
- `upstream_refs`；
- revision 写入与 latest replacement。

但调用方无法只凭返回的 `ArtifactRef` 无歧义表达完整终态，因此 driver 又自行解释：

- immutable revision path 与 latest alias path；
- revision delta；
- pending 或 partial latest failure；
- 写入是否成功；
- 是否可以 retry/replay/recover。

这已经造成“Store 实际写入成功，但 driver 的 post-write validator 报失败”的
false negative。

### 2.4 外围控制层失控并形成双控制面

合理的 feature driver 可以准备参数、调用公共 API 和展示结果。

当前部分 run-local driver 则自行：

- 判断 authority；
- 判断 schema/capability 是否支持；
- 选择 Graph 调用路径；
- 直接写 ArtifactStore；
- 判断 freshness；
- 定义 retry/replay/recovery；
- 解释 Store commit；
- 产生独立 terminal verdict。

这形成两个控制面：

```text
主控制面：
Public Entry → StateGraph → ArtifactStore

影子控制面：
Run-local Driver → Custom Admission → Graph/Store → Custom Verdict
```

当 Graph/Store 与 driver 都拥有最终解释权时，会出现：

- Graph 成功、driver 判失败；
- driver 通过、Graph lineage 不完整；
- Store committed、post-write validator 判异常；
- Graph 支持、public entry 不支持。

### 2.5 Artifact lineage 被多处重复表达

Artifact durable lineage、Graph runtime state、checkpoint protocol refs、Approval
exact inputs、Receipt produced refs 和 latest alias 具有不同职责。

如果它们都能独立定义 lineage，就会把：

- 历史 identifier baseline；
- current durable upstream；
- checkpoint/resume protocol ref；
- latest lookup；
- driver 推断

错误合并为一条“正式 lineage”。

## 3. 目标与非目标

### 3.1 必须实现的目标

1. 建立一个由 public entry、Graph admission、materializer 和测试共同读取的
   capability 声明来源。
2. 把 Approval Identity 固定为“人批准的 action 身份”。
3. 把 Approval hash 与 machine evidence、observation、presentation hash 分离。
4. 把正式 Artifact lineage 固定在 immutable Artifact envelope 的
   `upstream_refs`。
5. 建立权威的 Store/public-executor structured result。
6. 把 Graph-before-side-effect、retry/replay、checkpoint、failure 和 restoration
   收回公共执行层。
7. 把 feature driver 降级为无平台裁决权的 adapter。
8. 保留所有历史 immutable Artifact 和已执行 driver 的审计价值。
9. 使用增量迁移和真实集成测试，不进行推倒重写。
10. 用第二个真实产品切片验证公共控制面复用性。

### 3.2 明确非目标

以下工作位于本设计的当前范围之外；出现实际需要时，应说明它解决的真实缺口、与现有合同的
关系以及新增成本，再决定是否进入后续工作包：

- 重写整个 StateGraph；
- 重写或删除历史 Artifact；
- 创建第二个 Graph；
- 创建 AuditController、ApprovalController、ValidationController 或
  EvidenceController；
- 创建一个需要再次被 Receipt 的总控 Receipt Artifact；
- 把所有 feature 逻辑塞入 `graph.py`；
- 降低 source、diff、Artifact、lineage 或副作用边界精度；
- 认定所有 driver 都是错误；
- 修改 Stagger 产品验收 Criterion；
- 因为本文档存在而自动 Build、Runtime 或推进产品执行；
- 在现有模型已能表达目标时额外引入 Artifact、Approval、Request 或 Graph 类型。

## 4. 目标控制流与稳定公共契约

### 4.1 唯一目标控制流

```text
Human Approval
→ Public Entry
→ Capability Admission
→ StateGraph
→ ArtifactStore
→ Structured Machine Result
→ Runtime / Product Observation
→ Presentation
```

Feature-specific 代码负责准备该流程需要的输入；公共路径能够表达其需求后，执行统一回到该流程。

### 4.2 三个稳定公共契约

目标控制面只暴露三个稳定公共契约边界：

1. Approval Contract
   - 规范化 exact action identity；
   - 记录 human decision；
   - 不判断 Build/Runtime 成功；
   - 不产生产品验收结论。
2. Execution Contract
   - 接收已批准 action 与 current exact inputs；
   - 执行 capability admission；
   - 强制 Execution Invariants；
   - 不扩大 Approval scope。
3. Store/Result Contract
   - 持久化 durable outputs；
   - 返回权威 machine result；
   - 不决定 action 是否获得授权；
   - 不把 Store 成功提升为产品成功。

这三个契约是调用边界，不是三个新 Controller，也不是三个状态机。

跨契约协作遵循以下职责边界：

- Approval 不判断 Build/Runtime 是否成功；
- Execution 不重新定义 approved target、diff 或 side effects；
- Store/Result 不决定 action 是否获得授权；
- Observation 不批准新的 action；
- Presentation 不决定任何 terminal state。

每个 public entry 以一份由公共契约拥有的 structured result 结束。driver 负责展示该结果；
终态解释继续由公共契约负责。

## 5. 五层语义模型

信息按以下方向流动；低层信息不反向改变高层语义：

```text
Layer 1 — Approval Identity
    ↓
Layer 2 — Execution Contract / Invariants
    ↓
Layer 3 — Machine Evidence Receipt
    ↓
Layer 4 — Runtime / Product Observation
    ↓
Layer 5 — Presentation
```

### 5.1 Layer 1 — Approval Identity

回答：

> 人批准的具体 action 是什么？当前是否仍是同一个 approved action？

只有本层进入 human approval identity hash。

本层必须表达：

- capability identity 与 contract version；
- feature identity；
- exact input Artifact refs；
- 适用的 freshness policy；
- durable lineage roots；
- source-before identity 或 exact diff identity；
- target 与 Binding identity；
- allowed actions；
- forbidden actions；
- side-effect boundary；
- attempt budget 与 stop conditions。

本层排除：

- Store 总文件数和字节数；
- stdout/stderr 格式；
- 非 expiry 语义的时间戳和耗时；
- Git status 展示；
- run root 当前是否存在；
- pending 的展示文本；
- latest alias physical path；
- locator 长度；
- CRLF/LF；
- 执行后才产生的机器结果；
- Runtime 或人工观察。

executor 代码变化只有在改变 capability contract、允许副作用、执行顺序或失败语义时，
才要求升级 capability contract version 并重新获得 Approval。具体执行代码身份写入
Machine Evidence Receipt。

### 5.2 Layer 2 — Execution Contract / Invariants

回答：

> 执行器必须如何执行？本次执行是否违反规则？

本层不进入 Approval Identity hash，由 public executor 和 StateGraph 强制。

本层必须覆盖：

- capability admission 先于受控副作用；
- 首次副作用前重新核对 exact approved inputs；
- Graph admission 先于 Build、Runtime、process launch 或该 route 拥有的 durable write；
- attempt budget；
- one-shot；
- retry/replay/recovery policy；
- checkpoint/resume exact binding；
- allowed output Artifact types；
- unexpected mutation forbidden；
- failure stage/classification；
- no implicit permission expansion；
- no hidden upstream replay；
- process termination 与 restoration；
- pending Store admission policy。

违反本层规则表示执行失败或阻断，不表示 approved action 自动变化，也不授权替代 action。

### 5.3 Layer 3 — Machine Evidence Receipt

回答：

> 平台实际产生了哪些可由机器验证的事实？

本层包括：

- 使用的 Approval Identity；
- 使用的 capability contract version；
- 解释结果所需的具体 executor、source、toolchain 和 environment identity；
- consumed Artifact refs；
- produced Artifact refs；
- Store write outcomes；
- immutable revision 与 latest alias outcome；
- 有语义价值的 revision delta；
- Build command/result 和 DLL identity；
- Runtime process identity 和 machine markers；
- 实际发生的 side effects；
- failure stage 与 failure class；
- retry/replay count；
- termination/restoration result。

现有领域 Artifact 继续承担其职责：

- `BuildResult` 记录 Build 事实；
- `WorkflowCheckpoint` 记录 resumable workflow state；
- `ResumeReport` 记录 resume admission/consumption；
- `RuntimeEvidence` 记录 Runtime machine facts 与绑定 observation；
- evaluation/terminal Artifact 保留现有职责。

Store commit acknowledgement 以 API 级结果为默认表达。只有出现现有结果合同无法保存的 durable
语义时才评估 Artifact 形式，避免形成“Receipt 还需要 Receipt”的递归。

### 5.4 Layer 4 — Runtime / Product Observation

回答：

> 外部系统或产品实际表现如何？

本层包括：

- gameplay/external-system behavior；
- screenshot/capture；
- operator visual/audio report；
- 与 exact run 绑定的用户反馈；
- 依赖外部 stimulus 才有意义的 Runtime marker；
- observation limitations 和未观察条件。

每项 observation 必须保存：

- provenance；
- stimulus；
- exact run identity；
- limitations；
- 支持的 Criterion 或 claim。

Observation 不改变 Approval Identity。新 observation 应形成新的 evidence content 或
immutable revision，不得改写 approved action 或历史 evidence。

### 5.5 Layer 5 — Presentation

回答：

> 人怎样查看已有事实？

本层包括：

- CLI formatting；
- stdout layout；
- Markdown summary；
- hash 缩写；
- path/locator 展示；
- CRLF/LF；
- UI table/label。

Presentation 不得进入 Approval Identity，不得重新定义 Artifact，不得改变执行终态。

如果文本 marker 被程序解析，解析后的 structured fact 属于 Machine Evidence 或 Runtime
Observation；其周围 stdout 排版仍属于 Presentation。

### 5.6 禁止的层级污染

明确禁止：

- Observation 改变 Approval Identity；
- Presentation 改变 Evidence；
- Evidence 重新定义 Approval；
- Execution Result 扩大 side-effect permission；
- Store totals 或 stdout 使相同 action 的 Approval 失效；
- driver 把 Presentation 加入 control hash；
- human summary 成为唯一 durable lineage；
- Build success 被提升为 Runtime/Product success；
- marker success 被提升为未观察的人类视觉/听觉结论。

## 6. C1–C7 规范归属

本文档中的 C1–C7 是控制面设计控制项，不是 Stagger FeatureSpec 的产品 Criterion。

| 编号 | 主题 | 当前分散拥有者 | 目标唯一权威 | 迁移后不再承担该职责的组件 |
| --- | --- | --- | --- | --- |
| C1 | Capability 与 schema evolution | Graph、`local_entry`、materializer、driver | 单一 typed capability declaration | consumer 独立 allowlist |
| C2 | Approval Identity | Request payload、projection、driver | AuthorityRequest/Approval canonical contract | audit snapshot、driver |
| C3 | Hash/projection 分层 | generator、run-local driver | authority canonicalization 与现有 Artifact content hash 各司其职 | 一个 outer hash 覆盖所有层 |
| C4 | Artifact lineage 位置 | Artifact、Graph state、checkpoint、driver | immutable Artifact envelope 的 `upstream_refs` | latest alias、summary、driver 推断 lineage |
| C5 | Receipt 语义 | `ArtifactStore.write()` 与自定义 validator | Store/public-executor structured result 与现有领域 Artifact | feature-specific Store interpreter |
| C6 | Driver 权限和降级 | run-local executor | public entry/StateGraph；driver 仅为 adapter | driver-owned authority、route、Store、retry、verdict |
| C7 | 迁移顺序和测试门 | per-stage patch | 本文迁移计划与 focused integration gate | big-bang rewrite、delete-before-parity |

## 7. C1 — Capability ownership 与 schema evolution

### 7.1 单一 capability 声明

平台必须有一份 typed、declarative capability mapping。

mapping 使用当前 applicable contract 的精确 discriminator；当合同要求两者时，必须联合使用：

```text
schema_version + projection_kind
```

每个 capability declaration 必须绑定：

- capability identity；
- capability contract version；
- request discriminator；
- public entry operation；
- Graph entry route；
- execution mode；
- permitted output Artifact types；
- forbidden side-effect classes；
- materializer/effect factory；
- machine-result contract；
- compatibility/deprecation state。

该 mapping 是 control-plane contract metadata，不是：

- Artifact 类型；
- Approval 类型；
- 持久化数据库；
- 独立 Controller；
- 第二个 Graph。

### 7.2 与 `ArtifactTypeRegistry` 的边界

`ArtifactTypeRegistry` 继续只负责：

- Artifact type contract；
- producer/consumer contract；
- payload validation；
- upstream type requirements。

Graph routing 与 execution authority 由 capability contract 承担；`ArtifactTypeRegistry`
保持 Artifact contract 的职责边界。

capability declaration 属于 control-plane contract boundary，可以引用
`ArtifactTypeRegistry` 中的 Artifact contract，但不能复制其内容。

迁移 Step 1 先列出所有重复 allowlist，再由推进页结合现有模块边界选择一个 source module。
选择完成后：

- public entry；
- Graph admission；
- materializer dispatch；
- focused tests

共同读取该 source。旧表在 authority 迁移完成后转为委托、兼容读取或移除，从而只保留一个
有效解释源。

### 7.3 schema evolution 权限

一个 schema/capability 组合只有同时具备以下内容，才能声明为 supported：

1. capability declaration；
2. request validation；
3. public-entry admission；
4. Graph route 与 Execution Invariants；
5. materializer/effect factory；
6. machine-result semantics；
7. compatibility behavior；
8. 真实 public-entry integration test。

只有 Graph route、materializer branch 或 run-local driver 的局部支持，表示 capability 仍为
`partial`；完成状态以公共入口和真实集成测试为准。

schema evolution 保持历史 Artifact 和旧 Approval 可读；迁移通过兼容读取或显式版本边界完成。

### 7.4 C1 实施合同表：Capability 与 Execution

推进页根据实际代码填写“推进页决策”列。审核页只核对 authority、公共合同、兼容性与严重
边界；实施完成后由推进页回填实际符号和验证结果。表内没有实际证据支持的内容保持未闭合，
不以推测补全。

> **C1 最终验收覆盖（2026-08-03）**：审核页已对 staged bytes、authority migration、
> public/Graph/materializer 写前失败边界及 focused tests 给出
> `post_implementation_verdict=approved`，并允许提交。下表审核列保留的“实施后验收 pending”
> 是最终验收前的历史快照，已被本覆盖声明替代。实施提交为
> `de8e4d6`（`refactor: centralize edit authority capabilities`）。

| 合同项 | 推进页决策 | 审核页复核 | 实施与验收回填 |
| --- | --- | --- | --- |
| semantic goal | 让当前五种已实现的 Stagger Edit Authority review capability 共用一份 typed declaration；现有 `preflight_stagger_edit_authority_review` 与 `resume_stagger_edit_authority_review` 同时正式支持 generic、existing-binding、HUD observation v1、HUD diagnostic v2、bounded observation；未知 discriminator 组合在 public entry、Graph、materializer 一致 fail-closed。 | `合同修订后独立复核：approved；实施后验收 pending。` | 已交付 C1 Step 2：五种 capability 均由同一 declaration 解析；bounded 与 generic 已进入两个现有 public entry；未知组合在副作用前拒绝。 |
| current semantic authority | `src/mod_agent/local_entry.py` 的两个 public entry 维护 schema allowlist、write types 和成功状态；`src/mod_agent/workflow/graph.py::_run_stagger_edit_authority_gate` 独立维护 discriminator、actions、checkpoint scope、outputs 和 terminal stage；`src/mod_agent/runtime/stagger_edit_authority.py::materialize_stagger_edit_authority_approval` 独立维护 freshness scope 与 dispatch。bounded observation 已被 Graph/materializer 接受，但 public preflight 拒绝，public resume 不能返回成功状态。 | `合同修订后独立复核：approved；实施后验收 pending。` | 该段保留为迁移前基线；当前 capability support 与 schema evolution authority 已迁至 `src/mod_agent/edit_authority_capabilities.py`。三个 consumer 只保留 admission、Graph execution 和 materialization effect 职责。 |
| target owner module | 新建中立模块 `src/mod_agent/edit_authority_capabilities.py`，只拥有 Stagger Edit Authority capability declaration 与 exact resolver，不导入 Graph、local entry、Store 或 runtime materializer，避免循环依赖与副作用。 | `合同修订后独立复核：approved；实施后验收 pending。` | 已实现 `EditAuthorityCapabilityDeclaration`、`EDIT_AUTHORITY_CAPABILITIES`、`resolve_edit_authority_capability` 与 `resolve_edit_authority_request_capability`；模块不导入 Graph、local entry、Store 或 materializer。 |
| typed capability schema | frozen `EditAuthorityCapabilityDeclaration` 的必填字段为：`capability_id: str`、`capability_contract_version: str`、`schema_version: str`、`projection_kind: str or None`、`proposal_schema_version: str or None`、`public_operations: frozenset[Literal["preflight", "resume"]]`、`graph_route: Literal["stagger_edit_authority_gate"]`、`execution_mode: Literal["human_review_then_materialize"]`、`side_effect_class: Literal["artifact_store_write_after_accepted_resume"]`、`authority_contract_version: str`、`allowed_actions: tuple[str, ...]`、`forbidden_actions: tuple[str, ...]`、`checkpoint_input_mode: Literal["request_only", "request_and_registered_upstreams"]`、`latest_admission_mode: Literal["request_only", "request_and_registered_upstreams"]`、`materializer_kind: Literal["generic", "existing_binding", "hud_observation", "bounded_observation"]`、`materialized_artifact_fields: tuple[tuple[str, str], ...]`、`review_write_artifact_types: tuple[str, ...]`、`terminal_stage: Literal["binding_resolution", "implementation_plan"]`、`preflight_success_status: str`、`public_success_status: str`、`materializer_success_status: str`、`compatibility_mode: Literal["preserve_historical_identity"]`、`deprecated: bool`。所有字段由 declaration table 完整提供，无调用者默认补义。 | `合同修订后独立复核：approved；实施后验收 pending。` | frozen dataclass 与五行 declaration table 已按本行字段实现；HUD v1/v2 的 Request discriminator 与 technical proposal schema 由同一 declaration 精确绑定；`_build_approval_payload` 直接消费 declaration 的 authority contract 与 action tuples，不再重建第二张 action 表。 |
| discriminator resolution | exact key 为 `(schema_version, projection_kind)`；支持原 generic、existing-binding reauthorization、HUD observation v1、HUD diagnostic v2、bounded observation 五种组合。`projection_kind` 缺失规范化为 `None`；非字符串、未知 schema、known schema + unknown projection、wrong schema + known projection 均拒绝，不回退 generic。 | `合同修订后独立复核：approved；实施后验收 pending。` | `_CAPABILITIES_BY_DISCRIMINATOR` 只含五个 exact key；两个 resolver 对非字符串与未知组合抛出 `UnsupportedEditAuthorityCapabilityError`，无 generic fallback。 |
| public-entry operation | 保留 `preflight_stagger_edit_authority_review(...) -> dict[str, Any]` 与 `resume_stagger_edit_authority_review(...) -> dict[str, Any]` 的名称和调用形状；五份 declaration 的 `public_operations` 均为 `{preflight, resume}`。generic preflight 是明确新增的公共支持：其 `checkpoint_artifact_refs` 为 exact Request 加 Graph 按 artifact type 注册的 Request upstream refs，`review_write_artifact_types` 为 workflow_checkpoint、resume_report、edit_authority_approval、evidence_pack、implementation_plan、binding_resolution，preflight 仍零写入并返回 `READY_FOR_EDIT_AUTHORITY_REVIEW_EXECUTION`；generic resume 继续返回 `EXACT_EDIT_AUTHORITY_RESOLVED`。其他四种保持既有 request-only checkpoint 行为。 | `合同修订后独立复核：approved；实施后验收 pending。` | 两个既有 public entry 签名未变；`_EditAuthorityReviewAdmission.capability`、`_expected_edit_authority_checkpoint_refs` 与 declaration status/write types 已接管操作差异；两个 public entry 均在 Graph 调用前通过 capability owner 强制各自 operation applicability；generic registered-upstream preflight 与 bounded public resume 均有回归。 |
| Graph route | 保留单一 StateGraph 和 `_run_stagger_edit_authority_gate`；Request exact admission 后解析 declaration，再由 declaration 提供 checkpoint input mode、actions、materialized fields 和 terminal stage。Graph 仍负责 interrupt、checkpoint、resume、materializer 调用和 state handoff。 | `合同修订后独立复核：approved；实施后验收 pending。` | `_run_stagger_edit_authority_gate` 在 interrupt 前 exact resolve declaration，并只消费其 checkpoint mode、actions、materialized fields、materializer status 与 terminal stage；未新增节点或 conditional edge。 |
| execution contract | side-effect class 不变：preflight 零写入；批准 resume 只允许 declaration 列出的 workflow protocol 与 materialized Artifact。generic 保留 request + registered upstream checkpoint/freshness 行为；其他四种保留 request-only 行为。RepairPlanner、产品源码修改、Build、process launch 和游戏目录写入继续禁止。 | `合同修订后独立复核：approved；实施后验收 pending。` | 真实 bounded 集成测试证明 preflight revision delta 全零；批准 resume 仅新增 checkpoint、resume、Approval、EvidencePack、ImplementationPlan 各一份，BindingResolution 为零，pending 为空且源码字节不变。 |
| materializer/effect factory | 保留 `materialize_stagger_edit_authority_approval(...)` 单一入口及四个既有 apply implementation；入口先 exact resolve declaration，再按 `latest_admission_mode` 校验 freshness，最后按 `materializer_kind` dispatch。`_build_approval_payload` 必须接收并消费同一 declaration 的 `authority_contract_version`、`allowed_actions`、`forbidden_actions`，不得保留第二张 action 语义表。未知组合以及 HUD Request/proposal schema 不一致在 freshness、Graph interrupt/checkpoint、apply 和 Store write 前拒绝。 | `合同修订后独立复核：approved；实施后验收 pending。` | 单一 materializer 入口已按 declaration 完成 freshness 与 dispatch；四个 apply helper 接收同一 capability；HUD variant、Plan builder 与返回 status 从 capability 精确绑定的 proposal schema/status 推导，写前三层 mismatch 回归的 revision delta 为零；`_build_approval_payload` 的独立 action 分支已删除。 |
| result contract | 不新增 Artifact 或 result wrapper。每份 declaration 分别固定 preflight/public resume/materializer 三个 machine-result status。generic 为 `READY_FOR_EDIT_AUTHORITY_REVIEW_EXECUTION` / `EXACT_EDIT_AUTHORITY_RESOLVED` / `EXACT_EDIT_AUTHORITY_RESOLVED`；existing-binding 为同一 preflight / `EXACT_EDIT_AUTHORITY_RESOLVED` / `EXISTING_EDIT_AUTHORITY_REAUTHORIZED`；HUD v1 为同一 preflight / `STAGGER_HUD_PARENT_OBSERVATION_PLAN_AUTHORIZED` / 同值；HUD v2 为同一 preflight / `STAGGER_HUD_PARENT_DIAGNOSTIC_PLAN_AUTHORIZED` / 同值；bounded 为同一 preflight / `STAGGER_BOUNDED_OBSERVATION_PLAN_AUTHORIZED` / `BOUNDED_OBSERVATION_PLAN_AUTHORIZED`。失败仍为 `BLOCKED` 或既有异常边界。 | `合同修订后独立复核：approved；实施后验收 pending。` | 三类 status 均在 declaration table 固定；Graph 与 public resume 校验 materializer status，bounded public structured result 已由真实链验证。 |
| compatibility/evolution | 所有历史 Request、Approval、Artifact hash 和 immutable revision 保持可读；五个既有 discriminator 的 actions、lineage、outputs、terminal stage 与 materializer 不变。原 generic Request 的 registered upstream projection 与 resume 结果保留；generic 新增的是同一入口的 no-write preflight admission，不改 Request 或执行语义。现有 public caller 不改签名；未知组合从 Graph/materializer 的隐式 generic 回退收紧为 fail-closed。 | `合同修订后独立复核：approved；实施后验收 pending。` | 现有 Request/Approval/Artifact 合同及 public 签名未修改；322 项受影响测试全部通过；未迁移或改写历史 Artifact。 |
| removed authority | local entry、Graph 和 materializer 删除自身 schema/projection allowlist 与组合分支，改为调用 declaration resolver；它们继续拥有各自 admission、execution 与 effect 职责，但不能重新解释 capability support。历史 run-local driver 不修改，仅失去作为 capability authority 的必要性。 | `合同修订后独立复核：approved；实施后验收 pending。` | 三个 capability consumer 文件不再维护五个 Request discriminator；actions、status、write types、terminal/freshness/dispatch 与 HUD proposal 组合绑定均委托 declaration。`ArtifactStore` 为 Artifact contract upstream validation 保留 HUD schema 字面量，职责属于 §7.2，不构成 capability authority。历史 driver 未修改。 |
| semantic boundary | may change：generic 与 bounded observation 可通过两个现有 public entry；unsupported discriminator 一致拒绝；bounded public success status。must remain unchanged：Request/Approval canonical payload 与 hash、Artifact 类型/schema、Graph 数量与 route topology、checkpoint/resume identity、Store/lineage/freshness含义、materializer写入内容、side-effect/retry/recovery权限、产品源码和产品验收。 | `合同修订后独立复核：approved；实施后验收 pending。` | 越界检查通过：仅平台 capability owner、三个 consumer adapter 与 focused tests 变化；C2–C6、产品源码、Artifact 类型、Graph topology、Store/lineage/retry/recovery 均未改。 |
| validation | 一张覆盖五个 exact discriminator key 的表驱动 parity gate，逐项固定 public-operation applicability、authority contract/actions、checkpoint input mode、freshness mode、materialized fields/write types、terminal stage、preflight/public/materializer status；unknown、wrong schema + known projection、known schema + unknown projection 在 public entry、Graph interrupt/checkpoint、materializer apply、Store write 前一致拒绝，并断言 WorkflowCheckpoint、ResumeReport、Approval 和领域输出 revision delta 全为 0；HUD v1/v2 Request 与相反 proposal schema 同样在三层写前拒绝且全相关 revision delta 为 0；generic registered-upstream 兼容测试；至少一条 bounded 使用真实 ArtifactStore revision/latest/pending/freshness、真实 checkpoint/resume 和真实 materializer 的 public preflight→resume→Graph→Store structured-result 集成测试。 | `合同修订后独立复核：approved；实施后验收 pending。` | `python -m pytest -q tests/unit/test_edit_authority_capabilities.py tests/unit/test_stagger_edit_authority.py tests/unit/test_workflow_graph.py tests/unit/test_local_entry.py tests/unit/test_mod_agent_cli.py tests/unit/test_artifact_store.py tests/unit/test_artifact_contract.py tests/unit/test_repair_checkpoint_smoke.py`：322 passed。 |
| unresolved_contract_decisions | `[]` | `合同修订后独立复核：approved；实施后验收 pending。` | `[]` |

## 8. C2 — Approval Identity 与 action boundary

Human Approval 批准的是 action，不是整个机器环境的 snapshot。

迁移从现有 AuthorityRequest exact fields 中定义 canonical Approval Identity view。现有
Request 已表达的语义优先复用，通过 canonical view 收敛解释权。

canonical view 对以下变化必须稳定：

- Store totals；
- presentation formatting；
- stdout line ending；
- 无 expiry 语义的 timestamp；
- unrelated Git status；
- unrelated Artifact；
- run-local path display；
- 不改变 action 语义的 diagnostic counter。

以下任一变化必须改变 Approval Identity：

- exact input Artifact；
- required freshness policy；
- durable lineage root；
- source-before 或 exact diff；
- target/Binding；
- allowed/forbidden action；
- side-effect boundary；
- attempt budget；
- capability contract version。

### 8.1 C2 实施合同表：Approval Identity

> **C2+C3 工作包设计基线（2026-08-03，HEAD `de8e4d6`）**：本包只迁移当前五种
> Stagger Edit Authority Request/Approval 的 action identity 与 hash/projection 解释权。
> C1 declaration、Artifact/Request/Approval 类型、Graph topology、产品行为、Build/Runtime、
> C4 lineage、C5 Receipt 和 C6 driver migration 不在本包中改变。
>
> **实施状态（2026-08-03）**：实施前独立审核已批准；第一次实施后审核给出四项
> `changes_required`，对应 legacy v0 跨版本冻结、ResumeReport 写前交叉验证、resume public
> audit section 与 exact-input canonical order。四项完成有界修正后，第二次实施后独立验收
> `approved`；实现已提交为 `7ed68f4`。该提交完成 current v1 authority/identity/hash 行为；
> 2026-08-03 的跨项复核随后证明 historical v1 仍由 current declaration 重算，capability version
> 前移会使旧 v1 Request/Approval 与引用它们的 lineage 读取失败。因此 C1/C2+C3 当前状态修正为
> `current_behavior_done / historical_v1_compatibility_verified`；旧提交保留，不回滚。§9.4 的有界实现
> 已由独立实施后验收批准并提交为 `9bb6d019e11419c86bd058d98b5c8de854680f4c`；工作包 B 与 C6 尚未启动。

| 合同项 | 推进页决策 | 审核页复核 | 实施与验收回填 |
| --- | --- | --- | --- |
| semantic goal | 对五种已支持的 Stagger Edit Authority capability 定义一份 versioned canonical Approval Identity；人类批准的对象是 exact action，而不是完整技术 payload、运行位置或审计快照。相同 action 的只读观察与展示变化不使批准失效；action、输入、权限或副作用边界变化必须形成新 hash。 | 实施前与实施后独立审核均为 `approved`。 | 已由 commit `7ed68f4` 实现并验收。 |
| current authority | 迁移前由 `src/mod_agent/runtime/stagger_edit_authority.py` 的四个 Request creator/preflight 与本地 `_canonical_json` 分别把整个 `request_payload` hash 成 `request_hash`；`src/mod_agent/artifacts/registry.py::_validate_edit_authority_request` 重复 canonicalization；Graph/materializer 再从 `src/mod_agent/edit_authority_capabilities.py::EDIT_AUTHORITY_CAPABILITIES` 的当前 declaration 补入 capability version、actions 与 side-effect 语义。结果是 hash 未证明后补语义，Registry action 表和 run-local validator 形成附加解释源。目标 owner 是现有 `src/mod_agent/edit_authority_capabilities.py`，creator、Registry、public entry、Graph、materializer 只消费其 identity builder/validator。 | 确认 owner 迁移合同完整。 | 唯一新写 owner 为 `build_edit_authority_approval_identity`、`attach_edit_authority_approval_identity` 与 `validate_edit_authority_request_identity`；creator、Registry、Store、public entry、Graph 和 materializer 只消费该 owner。legacy full-payload canonicalization 仅保留在冻结 v0 envelope/read 分支。 |
| canonical schema | 新 Request 的 `request_payload.approval_identity` 为必填 mapping：`identity_schema_version="edit_authority_approval_identity_v1"`、`hash_domain="edit_authority_approval_identity"`、`capability`（`capability_id`、`capability_contract_version`、exact `schema_version`/`projection_kind`/`proposal_schema_version`、`authority_contract_version`）、`feature_id`、`run_id`、`lineage_root={feature_id,role:"feature_spec",artifact_type:"feature_spec",artifact_hash}`、按下表固定 role 顺序的 `exact_inputs[]`（`role`、`artifact_type`、`artifact_hash`、`required_freshness=latest_and_fresh|registered_exact_and_fresh|registered_exact`）、按下表逐 path 构造的 `action_scope`、`allowed_actions`、`forbidden_actions`、`execution_contract`（Graph route、execution mode、side-effect class、checkpoint/latest admission mode、materializer kind、materialized fields、允许写入的 Artifact types、terminal stage）、`attempt_budget={materialization_commits:1,automatic_retries:0}`。所有键必填，只有声明为 nullable 的 discriminator/proposal schema可以为 null。 | exact schema 已批准。 | `edit_authority_capabilities.py` 已实现该 mapping、五 discriminator exact role/action projection、必填/nullable 校验及 public identity sections。 |
| included fields | identity 包含 exact Feature/run、FeatureSpec lineage root、下表每个输入 Artifact 的 role/type/hash 与 freshness policy；capability/schema/contract versions；下表逐 capability 的 action projection；canonical target path、source-before hash、symbol/span/operation、Binding/change/evidence IDs、dependency hashes、action-only Plan/Proposal/diff/after-source hashes；declaration 的 exact allowed/forbidden actions、输出 Artifact 集、side-effect/execution/terminal contract和一次提交零自动重试预算。revision locator和整份技术proposal不自动进入identity，只有下表列出的path进入。 | exact inputs/action projection 已批准。 | 表驱动测试覆盖五种 discriminator；改变 exact input、source/diff、action、side-effect、budget 或 capability version会改变 hash。 |
| excluded fields | 排除 `source_root`、`build_dependency_root`、Artifact revision `path`、source `resolved_path` 等物理定位；bounded historical baseline 的 `*_recursive_freshness` 与 `*_stale_reasons`；Store totals/pending 展示、Git status、stdout/CRLF、elapsed/timestamp、command/message/status、run-local output path、approved_by/approved_at/resume_id、机器结果与 operator observation。定位值仍由执行器用 exact hash/path containment 校验，但不定义 action。 | audit/presentation exclusion 已批准。 | 单元与真实 bounded public-path 集成测试证明 audit snapshot、历史 freshness/stale reason、outer projection 与展示变化不改变 v1 hash，且 materializer 不再用整份技术 payload 重新定义 action。 |
| canonical serialization | Approval Identity 使用 UTF-8、`ensure_ascii=false`、object keys 排序、紧凑分隔符 `(',', ':')` 的 canonical JSON；固定 schema 的所有键必须存在，`null` 与缺失不同；`exact_inputs` 按 `role` 字符串升序排序，declaration actions/write types 使用冻结 tuple 顺序，proposal 内 Binding/change 等业务数组保持原顺序。物理 locator 不做字符串归一化后入 hash，而是完全排除；canonical product path 按已验证的 POSIX 相对路径原值进入 identity。 | serializer 合同已批准。 | `_canonical_json` 仅为 owner 内部 serializer；`exact_inputs` 按 `role` 字符串升序排序，semantic tuple顺序由 frozen declaration 提供，key insertion order不改变 hash；五种 capability 各有固定 role/hash identity 向量。 |
| contract version | 首版为 `edit_authority_approval_identity_v1`；hash domain 同名。任何 included/excluded 规则、input role/freshness、action scope、side-effect、attempt budget 或 canonical serialization 的语义变化必须使用新 identity schema 或新 capability contract version，不得就地重定义 v1。 | version/domain 已批准。 | 已实现 `APPROVAL_IDENTITY_SCHEMA_VERSION="edit_authority_approval_identity_v1"` 与 `APPROVAL_IDENTITY_HASH_DOMAIN="edit_authority_approval_identity"`。 |
| re-approval rules | exact input Artifact/hash/freshness、FeatureSpec lineage root、source-before/diff、target/Binding/operation/projected IDs、dependency hash、allowed/forbidden action、output/side-effect/execution boundary、attempt budget、capability/authority contract version任一变化都会改变 `request_hash` 并要求重新批准。仅 audit snapshot、物理 locator、Presentation、人类决定 provenance 或执行后结果变化不改变 action hash。 | re-approval boundary 已批准。 | 正负向向量均通过；四条 materializer freshness path 使用 `_request_matches_fresh_approval_identity`，不再以完整 payload/audit 字段制造 re-approval。 |
| historical compatibility | 已物化且没有 `approval_identity` 的 Request 保持 legacy v0：`ArtifactTypeRegistry.validate_envelope`/Store read使用同一identity owner的legacy分支，继续按`sha256(canonical(full request_payload))`及冻结的五种历史discriminator/action语义验证；旧Request/Approval bytes、hash和引用不改。`ArtifactTypeRegistry.validate_write`与`ArtifactStore.write`的新写路径一律要求v1，缺失identity在pending marker前拒绝；因此direct Store write不能伪装成legacy。未来action变化必须新identity/capability version，不得修改v0解释。 | legacy read/new write boundary 已批准。 | legacy v0 immutable envelope/read由 `_build_frozen_legacy_v0_capability_snapshots` 的独立字面 snapshot 解释，不引用当前v1 declaration对象或lookup；测试证明替换当前v1 declaration并重新构造legacy owner仍保持历史actions。新 Request/Approval write及public/Graph/materializer execution均v1-only。 |
| removed authority | 四个 creator 不再自行决定 hash 输入，只组装经当前 source/Artifact 验证的 product action payload并调用公共 identity owner；Registry 删除重复 canonicalizer和 authority-contract→action 表，改为 schema/Artifact validator消费 owner；public entry、Graph、materializer在副作用前验证同一 identity且不得从当前 declaration补出未被 hash 绑定的动作。两个已执行 run-local driver保留只读审计价值，但其 outer projection、hardcoded hash/actions、Store totals与terminal verdict不能创建或解释新 identity。 | 旧 owner 不可旁路是强制验收项。 | Registry 独立 action 表和 creator whole-payload新写 hash权已移除；Store在pending前验证identity、exact upstream multiset与role freshness；direct Approval写前回读exact Request与ResumeReport，并校验 accepted/allowed/decision、request hash、run/resume/approver/time、actions与upstream。缺失或篡改均为revision/pending零增量。 |
| semantic boundary | may change：新 Request payload 增加 versioned `approval_identity`；新 `request_hash`只 hash该 identity；public preflight增加结构化 identity/execution/audit sections；Store/Registry/public/Graph/materializer增加统一写前 identity验证。must remain unchanged：旧 Artifact读取、五种 capability action与副作用、Request/Approval/Artifact类型和Graph topology、产品源码/行为、Build/Runtime、durable upstream semantics、checkpoint/retry/recovery权限及C4–C6。 | 边界已批准。 | 生产 diff仅触及既有 owner/consumer/validator/public projection；未新增 Artifact/Graph/Approval类型或Graph topology，未改产品、Build/Runtime、C4–C6。 |
| unresolved_contract_decisions | `[]` | `[]` | `[]` |

### 8.2 C2 exact input roles 与 action projection

`required_freshness` 只有三种精确语义：

- `latest_and_fresh`：该 role 的 immutable revision 必须是该 Artifact type 的 current latest，且 recursive/exact freshness 为 fresh；
- `registered_exact_and_fresh`：revision 不要求 latest，但必须在 Store 注册、字节/hash 有效且 recursive/exact freshness 为 fresh；
- `registered_exact`：revision 必须在 Store 注册且字节/hash 有效，允许 stale，只能承担合同声明的历史输入职责。

每个 role 从指定 revision object 的 `artifact_hash` 取得逻辑身份；`path` 只用于回读，不进入
Approval Identity。Store 在创建 pending marker 前使用 `(artifact_type, artifact_hash)` 的
multiset 与 immutable Request envelope upstream multiset 一一比较，不能用按 Artifact type
覆盖的 dict。重复 type 由 role、proposal JSON path 和 hash 区分；相同 type/hash 出现两次时，
upstream multiset 也必须出现两次。

| capability discriminator | exact input role → proposal JSON path → Artifact type → required freshness |
| --- | --- |
| `stagger_edit_authority_request_v1` / null | `feature_spec→proposal.feature_spec_revision→feature_spec→latest_and_fresh`; `runtime_evidence→proposal.runtime_evidence_revision→runtime_evidence→latest_and_fresh`; `implementation_plan→proposal.implementation_plan_revision→implementation_plan→latest_and_fresh`; `patch_proposal→proposal.patch_proposal_revision→patch_proposal→latest_and_fresh` |
| `stagger_existing_binding_reauthorization_request_v1` / null | `feature_spec→proposal.feature_spec_revision→feature_spec→latest_and_fresh`; `runtime_evidence→proposal.runtime_evidence_revision→runtime_evidence→latest_and_fresh`; `predecessor_implementation_plan→proposal.predecessor_implementation_plan_revision→implementation_plan→registered_exact_and_fresh`; `patch_proposal→proposal.patch_proposal_revision→patch_proposal→latest_and_fresh`; `current_implementation_plan→proposal.current_implementation_plan_revision→implementation_plan→latest_and_fresh`; `existing_binding_resolution→proposal.existing_binding_resolution_revision→binding_resolution→latest_and_fresh` |
| `stagger_hud_parent_observation_authority_request_v1` / null | `feature_spec→proposal.feature_spec_revision→feature_spec→latest_and_fresh`; `runtime_evidence→proposal.runtime_evidence_revision→runtime_evidence→latest_and_fresh`; `current_implementation_plan→proposal.current_implementation_plan_revision→implementation_plan→latest_and_fresh`; `patch_proposal→proposal.patch_proposal_revision→patch_proposal→latest_and_fresh`; `existing_binding_resolution→proposal.existing_binding_resolution_revision→binding_resolution→latest_and_fresh`; `existing_edit_authority_approval→proposal.existing_edit_authority_approval_revision→edit_authority_approval→latest_and_fresh`; `evidence_pack→proposal.evidence_pack_revision→evidence_pack→latest_and_fresh` |
| `stagger_hud_parent_diagnostic_execution_authority_request_v2` / null | 与 HUD v1 相同七个 exact roles/freshness；proposal schema固定为`stagger_hud_parent_diagnostic_execution_authority_v2`，并额外由action projection绑定三项dependency hash，不增加Artifact upstream role。 |
| `stagger_edit_authority_request_v1` / `bounded_observation_only_plan_materialization` | `feature_spec→proposal.feature_spec_revision→feature_spec→latest_and_fresh`; `runtime_evidence→proposal.runtime_evidence_revision→runtime_evidence→latest_and_fresh`; `evidence_pack→proposal.evidence_pack_revision→evidence_pack→latest_and_fresh`; `historical_implementation_plan→proposal.historical_identifier_baseline.implementation_plan_revision→implementation_plan→registered_exact`; `historical_patch_proposal→proposal.historical_identifier_baseline.patch_proposal_revision→patch_proposal→registered_exact` |

上表每格列出 role 与其来源/策略绑定，不定义 canonical array 顺序。最终
`approval_identity.exact_inputs` 对五种 capability 均按 `role` 字符串升序排序；该顺序由五组
固定 identity 向量测试锁定。

`action_scope` 不是“完整 proposal 再递归删除字段”。owner 只从下表列出的 JSON path 构造新对象；
未列出的字段不得通过 opaque parent object、外层 hash 或派生摘要间接进入。

| capability | action projection 的精确输入 path |
| --- | --- |
| generic | `proposal.ownership_review.{stored_runtime_failure_ownership,replayed_runtime_failure_ownership,reclassification_approval_required,runtime_evidence_mutation_allowed}`；`proposal.diagnosed_responsibility_anchor`；`proposal.current_source.{canonical_target_path,sha256,target_span}`；`proposal.{proposed_target_symbol,proposed_exact_span,proposed_operation,existing_binding_gap,current_edit_authority,approval_scope,root_cause_status,unresolved_root_causes}`；`request_payload.projected_ids` |
| existing-binding | `proposal.{binding_id,preserved_edit_binding,preserved_change,preserved_resolved_repair_target}`；`proposal.current_source.{canonical_target_path,sha256,target_span}`；`proposal.ownership_review.{stored_runtime_failure_ownership,replayed_runtime_failure_ownership,runtime_evidence_mutation_allowed}`；`proposal.{root_cause_status,unresolved_root_causes,projection_boundary}` |
| HUD v1 | `proposal.current_source.{canonical_target_path,sha256}`；`proposal.{diagnostic_bindings,selected_binding_ids,selected_change_ids,excluded_predecessor_binding_ids,excluded_predecessor_change_ids,diagnostic_plan_projection,why_existing_binding_is_insufficient,root_cause_status,claim_boundary,approval_scope}` |
| HUD v2 | HUD v1全部path；`proposal.supporting_source.{canonical_target_path,sha256,config_gate,config_section,config_key,default_value}`；`proposal.identity_api_contract.assemblies[].{role,sha256}`；`proposal.identity_api_contract.{crosshair_gui_layer_identity,unity_object_identity,compile_boundary}`；`request_payload.dependency_hashes` |
| bounded observation | `proposal.reviewed_no_write_projection.{implementation_plan_projection_hash,patch_proposal_projection_hash,standard_diff_hash,unified_diff_sha256,projected_after_source_sha256,binding_id,change_id}`；`proposal.current_source.{canonical_target_path,sha256,target_span}`；`proposal.target_source_evidence_item`；`proposal.implementation_plan_template` 的canonical content必须匹配上述`implementation_plan_projection_hash`，identity保存该action-only hash而不重复保存template locator；`proposal.historical_identifier_baseline.{authority,downstream_authority}`；`proposal.materialization_boundary`；`request_payload.projected_ids` |

明确排除 `reviewed_no_write_projection.reviewed_projection_hash`：该值来自
`project_negative_observation_diff.py` 的 outer projection，真实覆盖 Store file count/bytes 等
audit snapshot，不能进入 action identity。相同原因，任何未知 opaque projection hash只有在其
canonical input contract明确不含audit/observation/presentation后，才能被未来identity schema接纳。

semantic set 的canonical order不是调用者顺序：`allowed_actions`、`forbidden_actions`、
`review_write_artifact_types`和`materialized_artifact_fields`使用C1 frozen declaration中的tuple顺序；
identity builder拒绝调用者重排或补项。`exact_inputs`按 `role` 字符串升序排序；proposal内Binding/change
等业务数组保持原有顺序，数组重排视为action变化。

## 9. C3 — Hash 与 projection 分层

### 9.1 必须区分的 hash

| Hash/identity | 回答的问题 | 何时产生 | 能否授权执行 |
| --- | --- | --- | --- |
| Approval Identity hash | 是否为同一个 approved action | 执行前 | 只能在 exact scope 内授权 |
| Artifact content hash | 是否为同一 immutable Artifact content | Artifact materialization | 否 |
| Machine result content hash | 是否为同一 structured execution result | 执行后 | 否 |
| Observation content hash | 是否为同一日志、截图或 operator observation | observation 后 | 否 |
| Presentation | 如何展示 | 任意时间 | 永不授权 |

当 machine result 或 observation 以 Artifact 持久化时，Artifact content hash 可以同时
标识其内容，但仍不等于 Approval Identity。

### 9.2 projection boundary

preflight projection 可以展示多个 section，但只有 canonical Approval Identity section
进入 approval hash。

概念关系：

```text
approval_hash = hash(canonical(approval_identity))

preflight_output =
  approval_identity
  execution_contract_summary
  audit_snapshot
  presentation
```

具体序列化字段由推进页在迁移时从现有 schema 提取，并通过 tests 固化。新增 payload key
作为显式 contract change 记录，而不是从概念示例直接推导。

`audit_snapshot` 可以为诊断完整性生成 observation digest；human Approval Identity 继续只由
canonical `approval_identity` 计算。

### 9.3 C3 实施合同表：Hash 与 Projection

| 合同项 | 推进页决策 | 审核页复核 | 实施与验收回填 |
| --- | --- | --- | --- |
| hash roles | `request_hash`/`approval_hash` 是 Approval Identity hash，只回答是否同一 approved action；ArtifactStore envelope `artifact_hash` 继续是 immutable Artifact content hash；执行后 Build/Runtime/Store Artifact hash属于 Machine Result content；日志、截图和 operator observation由其内容 hash/Artifact hash标识；stdout、表格、locator与换行只是 Presentation，不拥有授权语义。 | 实施前审核 `approved`。 | 新 Request/Approval 使用 `sha256:` Approval Identity hash；ArtifactStore content hash、机器结果、观察与展示算法/语义未改。 |
| algorithm/domain | Approval Identity hash 为小写 `sha256:` + SHA-256(canonical UTF-8 `approval_identity`)；identity对象内固定 `hash_domain`和`identity_schema_version`完成domain/version separation。ArtifactStore现有无前缀64位content hash算法不改，不与Approval hash互换。 | algorithm/domain 已批准。 | `_approval_identity_hash`实现该算法；ArtifactStore无前缀content hash保持原合同。 |
| canonical inputs | Approval hash精确输入仅为C2 canonical schema及§8.2逐capability表列出的字段；特别排除bounded outer `reviewed_projection_hash`及其Store totals/bytes传递污染。Artifact content hash继续覆盖完整envelope/data/inputs/blockers/trace refs，因此被Approval排除的message、human provenance、物理locator或audit字段仍受Artifact完整性保护。Observation hash只覆盖对应日志、截图或operator payload，不反向进入Approval Identity。 | canonical boundary 已批准。 | 五类 action projection由owner逐path构造；bounded outer hash、Store totals与审计字段未进入identity，而完整Artifact仍由原content hash保护。 |
| projection sections | `preflight_stagger_edit_authority_review`新增`approval_identity`、`execution_contract_summary`、`audit_snapshot`三个结构化section并保留现有flat字段兼容读取：第一项是hash输入；第二项展示declaration约束但不能改写identity；第三项承载revision counts、writes flags等只读观察。CLI/stdout只负责Presentation。 | projection分层已批准。 | `preflight_stagger_edit_authority_review`与`resume_stagger_edit_authority_review`均返回三个section并保留兼容flat字段；resume audit section包含写前/写后revision counts与writes flags；`audit_snapshot`不参与hash。 |
| lifecycle/replay | producer在Request写入前生成identity/hash；Registry与Store在写前校验identity结构、hash及exact upstream绑定；public entry和Graph在interrupt/checkpoint前复核；ResumePayload只传同一`request_hash`；materializer在任何Approval/domain Artifact写入前复核Request、Resume和identity；Approval持久化同一`approval_hash=request_hash`并由exact Request/Resume upstream绑定。执行后机器事实生成自己的Artifact content hash，不修改批准对象。 | lifecycle/replay已批准。 | Store在pending前完成Request/Approval identity、multiset upstream及exact accepted ResumeReport交叉 admission；public/Graph/materializer均拒绝legacy或tamper。bounded真实Store→public entry→Graph→checkpoint/resume→materializer集成通过。 |
| compatibility | absence of `approval_identity`只在`validate_envelope`/read路径标识已存在的legacy v0 Request；读取时使用同一owner的旧full-payload hash规则并绑定冻结的历史capability语义。`validate_write`及Store write拒绝缺失v1 identity的新对象。公共结果显式返回identity mode/version，使调用方不会把legacy full-payload hash误称为v1 action hash。 | compatibility已批准。 | Registry envelope/read仍识别冻结legacy v0；新write与执行入口v1-only。旧whole-payload builder、payload canonicalizer与历史capability解释不能影响新v1。 |
| contamination checks | 表驱动验证Store totals/pending展示、stdout CRLF/LF、Presentation、elapsed/timestamp、approved_at、run-local root、revision/resolved display path、bounded freshness reason及含这些值的outer projection hash变化不改变v1 Approval hash；逐项改变exact Artifact/freshness、source/diff/Binding/action-only Plan/Proposal/diff/source hash、side-effect/output/budget/capability version必须改变hash。key insertion order稳定，missing与null、array order变化按合同严格区分。另验证旧v0 read成功、新v0 write拒绝，以及五类v1 direct Request/Approval身份或upstream篡改均在pending marker前Store零写入。 | contamination与零写入门已批准。 | 全部边界已由 `test_edit_authority_capabilities.py`、`test_artifact_store.py`、`test_artifact_contract.py`、`test_stagger_edit_authority.py`、`test_workflow_graph.py` 覆盖；缺失identity、identity/hash/upstream篡改均在revision/pending零增量时拒绝。 |
| semantic boundary | may change：五种新Request/Approval的identity/hash解释、公共projection分层与写前验证owner。must remain unchanged：Artifact content hash、Machine/Observation证据语义、历史hash、五种action本身、Graph/Store拓扑、产品与外部副作用。C3不新增Receipt Artifact或新的审批系统。 | 边界已批准。 | 未新增Receipt Artifact、审批系统或Graph拓扑；C4–C6与产品/外部副作用均未改。 |
| unresolved_contract_decisions | `[]` | `[]` | `[]` |

### 9.4 工作包 A：historical v1 capability compatibility

本工作包只修复已由当前代码最小复现的 version-advancement 兼容缺口。复现结果：同一
discriminator 的 current declaration 从 `stagger_edit_authority_capability_v1` 前移到 v2 后，
`validate_edit_authority_request_identity(..., allow_legacy=True)` 使用 current declaration 重建旧 v1
identity，并以 `approval_identity does not match` 拒绝历史对象。该问题尚未破坏当前正式 Artifact，
但会在 capability evolution 时使旧 Request/Approval 及引用它们的 recursive freshness 失效。

| 合同项 | 推进页决策 | 审核页复核 | 实施与验收回填 |
| --- | --- | --- | --- |
| semantic goal | 将“当前可写/可执行 declaration”与“历史 versioned declaration 的只读解释”分开。旧 immutable v1 Request/Approval 必须按其存储的 identity schema、capability id/version 和 exact discriminator 解释；current declaration前移不得重定义其 identity。旧v1不得因此获得current execution authority。 | `合同修订后正式复核：approved；实施后独立验收：approved。` | `implemented and verified；commit 9bb6d019e11419c86bd058d98b5c8de854680f4c` |
| bounded owner inventory | Request read：`ArtifactTypeRegistry.validate_envelope → _validate_edit_authority_request(...allow_legacy=True) → validate_edit_authority_request_identity`；Approval read同理由`validate_edit_authority_approval_contract(...allow_legacy=True)`解释。Store recursive freshness通过`ArtifactStore.read`触发上述Registry read。新写由Registry/Store `allow_legacy=False`；public entry、Graph和materializer也都调用`allow_legacy=False`。当前缺口只在capability owner未区分versioned-read/current-execution lookup，其他consumer无需拥有第二套语义。 | `approved；owner inventory无剩余合同阻断。` | `confirmed；未新增consumer authority` |
| versioned declaration owner | 在现有`src/mod_agent/edit_authority_capabilities.py`内建立append-only versioned capability record owner；精确key为`(identity_schema_version, capability_id, capability_contract_version)`。record必须绑定完整canonical identity reconstruction contract，而不只是结果字段：该版本的identity schema/hash domain、canonical serialization与hash算法版本、exact input binding的JSON path/freshness/order、versioned action-projection builder/selector及其精确path/order、schema/projection/proposal discriminator、authority/actions、execution/side-effect/materializer/output/terminal contract和attempt budget。实现可使用数据化descriptor或append-only versioned builder；无论private组织为何，historical rebuild不得从current maps、current constants、current-only input/projection table或已被后续版本修改的helper补义。v1 reconstruction record/builder保留为不可变版本；未来版本新增record/builder，不就地改写旧版本。 | `第一次审核：changes_required；合同修订后：approved。` | `VersionedEditAuthorityCapabilityRecord`、`_VERSIONED_CAPABILITY_RECORDS_BY_KEY`和冻结的v1 builder/serializer/action projection已实现；current helper替换不改变历史v1 hash。 |
| current-write/current-execution lookup | `_CURRENT_CAPABILITY_RECORDS_BY_DISCRIMINATOR`和`_CURRENT_CAPABILITY_RECORDS_BY_ID`只指向current records。identity creator、Registry `validate_write`、Store pending前Request/Approval gate、public preflight/resume、Graph gate和materializer均要求stored identity的versioned key与current record精确相同；旧v1即使可读，也在任何checkpoint/Approval/domain write前fail-closed。 | `approved。` | 两个current索引必须指向同一record；版本混配fail-closed。旧v1的`write_with_result`返回`blocked_before_commit`且`commit_started=false`。 |
| historical-read versioned lookup | Registry envelope/read对带`approval_identity`的对象使用stored `identity_schema_version + capability.capability_id + capability_contract_version`解析versioned record；Request还必须逐项匹配outer `schema_version/projection_kind/proposal.schema_version`，并只调用该record绑定的versioned reconstruction builder/serializer/hasher重建完整expected identity/hash。Approval使用自身stored schema/id/version解析同一record，并验证authority/actions等字段。historical read路径禁止调用模块级current `APPROVAL_IDENTITY_SCHEMA_VERSION`/`APPROVAL_IDENTITY_HASH_DOMAIN`、current declaration input bindings或current-only action projection分支补义。unknown version、identity schema、builder id或discriminator组合fail-closed。 | `第一次审核：changes_required；完整reconstruction合同后approved。` | Request与Approval的`allow_legacy=True`分支按stored version key解析历史record；unknown reconstruction contract写前拒绝。 |
| compatibility/deprecation | versioned record是否为current由current lookup map决定，而不是修改历史record。current record可new-write/new-execute；已登记但非current record为read-only historical：Registry/Store read与recursive freshness允许，public/Graph/materializer execution拒绝。`compatibility_mode`/`deprecated`只描述该版本，不授予执行；legacy v0继续由独立`LegacyV0CapabilitySnapshot`解释。 | `approved。` | 旧v1 Store/Registry读取通过；public、Graph、materializer三侧current execution均在副作用前拒绝；current v2 Request写入与public preflight通过；legacy v0回归保持。 |
| lineage/freshness | 旧v1 Request/Approval在current version前移后仍能由Store按原bytes/hash读取；引用它们的immutable child envelope递归freshness只由其exact upstream和历史versioned read语义决定，不因current pointer改变而失效。该兼容不允许新child write把历史v1误当current action authority；具体new-write仍走current gate。 | `approved。` | 真实temp Store回归证明旧Request/Approval字节不变，exact child在current v2 Request前移latest后仍fresh；无正式Store写入。 |
| public/materializer boundary | public `preflight_stagger_edit_authority_review`、`resume_stagger_edit_authority_review`、Graph `_run_stagger_edit_authority_gate`及所有现有materializer保持current-only。历史read resolver不得被这些路径当作兼容执行fallback；失败发生在Graph interrupt/checkpoint、Approval、Evidence/Plan/Binding和Store pending marker之前。 | `approved。` | 真实public/Graph/materializer回归对旧v1均拒绝且相关Artifact revision delta=0；current v2 public preflight成功。 |
| minimum verification | ①以v1 current生成并物化Request/Approval及引用其lineage；②登记v2 record并将current maps前移；v2除`capability_contract_version`外必须改变至少一项identity-affecting语义，测试采用不同的versioned action-projection builder/path输出；③旧v1 Request/hash/Approval Registry+Store read结果逐字不变；④新v2按新projection语义生成不同identity/hash并可new-write/current-execute；⑤旧v1 public/Graph/materializer execution在副作用前拒绝；⑥旧v1 child recursive freshness保持；⑦legacy v0 read保持；⑧unknown历史version/schema/discriminator/builder组合fail-closed；⑨显式替换current projection/helper语义后，旧v1仍只调用其historical v1 reconstruction builder。 | `合同修订后正式复核：approved。` | 专项回归与受影响套件已覆盖上述边界；最终命令/数量在实施后验收包记录。 |
| semantic boundary | may change：capability owner内部的versioned records、read/current resolver与对应Registry/Store/public/materializer回归。must remain unchanged：五种既有action、Artifact/Approval/Request类型、Graph topology、Store commit/C5 result、C4 upstream规则、产品、Build/Runtime、driver、正式Artifact bytes/hash。 | `approved。` | 生产修改仅`edit_authority_capabilities.py`；测试修改限capability、Store、public/Graph/materializer边界；未触及其他合同或产品链。 |
| unresolved_contract_decisions | `[]`。历史v1为read-only、current version才可写/执行；不存在自动迁移、自动升级或fallback执行。 | `[]` | `[]` |

实施后验证命令：
`python -B -m pytest -q -p no:cacheprovider tests/unit/test_edit_authority_capabilities.py tests/unit/test_artifact_contract.py tests/unit/test_artifact_store.py tests/unit/test_stagger_edit_authority.py tests/unit/test_workflow_graph.py tests/unit/test_local_entry.py`
；推进页结果：`320 passed in 87.96s`；独立验收页复跑结果：`320 passed in 86.77s`，
`post_implementation_verdict=approved`、`execution_blocker=none`。该结果只证明工作包 A 与既有
C1–C3/C5 受影响路径；工作包 B 与 C6 尚未完成。

## 10. C4 — Artifact lineage 的权威位置

### 10.1 durable lineage owner

Artifact-to-Artifact 正式 lineage 只能由 `ArtifactStore` 持久化的 immutable Artifact
envelope 表达，使用 exact `upstream_refs` 和对应 freshness policy。

### 10.2 Graph 中的正确位置

StateGraph 负责 runtime state 和 route。lineage 相关职责只有：

```text
接收 exact ArtifactRef
→ 验证 admission/freshness policy
→ 在 state 中传递 ref
→ Store.write 时传入 exact upstream_refs
→ 记录 produced ref
```

批准后，Graph 不得通过重新查询无关 latest alias 偷换 approved exact input。

Graph conditional edge 决定执行 route，但不创造 durable lineage。

### 10.3 checkpoint/resume 边界

`WorkflowCheckpoint` 和 `ResumeReport` 保存 continuation protocol 与恢复身份。

它们作为 Artifact 时拥有自己的 `upstream_refs`，也可以引用 resume 所需 Artifact。resume
后生成的产品 Artifact 仍按其真实输入建立独立 durable lineage。

### 10.4 alias/locator 边界

- 完整 Artifact hash 是 logical identity；
- immutable revision path 是 durable physical location；
- latest alias 是 mutable lookup pointer；
- shortened physical locator 不是 shortened logical identity；
- revision path 与 alias path 不要求相等；
- alias correctness 由 Store contract、content/hash agreement 判断。

### 10.5 C4 实施合同表：Artifact Lineage

> **当前状态覆盖（2026-08-03）**：§10.5 的“唯一 durable owner”结论仍成立，但跨项最小复现证明
> `ArtifactStore.write` 可把 `list_feature_artifacts()` 返回的 mutable latest alias ref 原样持久化为
> child upstream。此前“调用者必须传入 exact ArtifactRef”只是调用约定，不是 Store admission。
> 因而 C4 已按 §10.7 重新打开；§10.5/§10.6 中的 `unchanged/confirmed` 只保留为首次 inventory
> 的历史结论，不再表示 immutable-upstream admission 已完成。

| 合同项 | 推进页决策 | 审核页复核 | 实施与验收回填 |
| --- | --- | --- | --- |
| semantic goal | 确认 current public/actual execution paths 中 durable Artifact-to-Artifact lineage 只有一个权威 owner；Graph state、checkpoint protocol refs、latest alias、payload validation copy、summary 和 run-local driver 均不得重定义或偷换 immutable envelope 已记录的 exact upstream identity。本工作包先做 bounded inventory；只有发现真实第二 owner 才迁移。 | `实施前独立审核：approved；C4 可按 unchanged/confirmed 收口。` | `completed：bounded inventory 未发现第二 owner；production change=none，test change=none。` |
| durable owner | `ArtifactStore._execute_write` 通过 `inputs["upstream_artifacts"]` 持久化每个 `ArtifactRef` 的 `artifact_type/path/artifact_hash/require_latest`；该 `inputs` 进入 `_ENVELOPE_HASH_FIELDS` 和 `_envelope_content_for_hash`，`ArtifactStore.read` 回算完整 envelope content hash。`ArtifactTypeRegistry` 只拥有每类 Artifact 的 required/one-of/exact upstream role policy，不拥有某次写入的具体 lineage identity。 | `confirmed：immutable envelope inputs 是唯一 durable owner。` | `unchanged/confirmed；现有 Store owner 无需迁移。` |
| upstream rules | 调用者必须传入 exact `ArtifactRef` 列表；其现有顺序进入 canonical envelope content。`ArtifactStore._validate_upstream_refs` 在 pending marker 前验证 feature/type/path/full hash、Registry required roles、exact role set和 freshness。默认 `require_latest=true`；只有 `exact_revision_upstream_types` 中的 role 写为 `false`，此时必须仍能回读该 immutable revision，latest drift 不替换它。当前 verification-only Build 的顺序为 `feature_spec,evidence_pack`；RuntimeEvidence 为 `build_result,feature_spec`；ResumeReport 仅绑定 exact `workflow_checkpoint`。其他 Artifact 继续按 Registry 与现有 Graph write site 的既定顺序，不在 C4 改写。 | `首次inventory确认write sites未主动用latest偷换；跨项复核发现Store未强制immutable path。` | `reopened_for_exact_upstream_boundary；§10.7补齐Store admission。` |
| Graph handoff | `graph._artifact_ref_from_state` 只从 state 的 path/full hash 重建 ref，`graph._record_artifact` 只记录 Store 返回 ref；各 node 在 `ArtifactStore.write(..., upstream_refs=...)` 显式传递真实输入。verification-only admission 记录用户提供并经 Store 校验的 exact FeatureSpec/EvidencePack；`_run_build`、`_run_runtime_evidence` 分别将其真实输入写入 child envelope。Graph route 和 state summary 不持久化第二条 lineage。 | `confirmed：Graph/state是consumer与handoff，不是durable owner。` | `unchanged；公共Build/Runtime路径由现有回归覆盖。` |
| checkpoint/resume | `WorkflowCheckpointStore.create_checkpoint` 把 state refs 同时写入 checkpoint payload 和该 checkpoint 自己的 envelope upstreams；`_checkpoint_lineage_blockers` 校验 snapshot/path/hash 与 envelope refs 一致，exact build roles还必须是 BuildResult ancestry 的唯一最近语义祖先。`resume` 生成的 ResumeReport exact绑定 checkpoint。它们只拥有 continuation protocol lineage；resume 后 RuntimeEvidence仍由 Graph以 `build_result,feature_spec` 建立自己的 durable lineage，checkpoint/snapshot不能替代或改写该 child envelope。 | `confirmed：checkpoint protocol refs不替代产品Artifact lineage。` | `unchanged；exact-role ancestry、歧义分叉和诊断latest替换均由既有负向回归阻断。` |
| revision/alias/pending | full `artifact_hash` 是 logical identity；immutable revision path 是 durable location；latest alias 是可变 lookup pointer；32位 physical locator不缩短 logical identity；pending只是 Store commit protocol状态。C5 的 `ArtifactWriteResult` 分开报告 revision/latest/pending，不改变 C4 lineage。freshness根据 envelope内 `require_latest` 决定是否比较 alias；exact revision仍校验immutable bytes/hash。 | `confirmed：alias/locator/pending均不拥有lineage。` | `unchanged；C5 structured result职责未扩张。` |
| historical compatibility | `ArtifactStore.read` 按 exact path/full hash继续读取历史 immutable revision；普通 freshness保留 latest drift语义，`check_exact_revision_freshness` 与 envelope内 `require_latest=false` 保留 approved exact subgraph。旧 checkpoint按自身 snapshot/envelope/resume binding校验，不能由当前 latest补齐或替换。历史 Artifact、checkpoint、alias与hash均不迁移、不重写。 | `confirmed：历史读取与freshness语义保持兼容。` | `unchanged；未迁移或改写任何历史Artifact/checkpoint/hash。` |
| removed authority | bounded inventory未发现需要移除的第二 owner。`BuildResult.data.verification_only_lineage` 是 evaluation/admission 的内容级一致性副本，必须与当前 exact preflight一致；它不能改变 envelope upstreams，冲突时只会阻断成功声明。Graph summary、checkpoint snapshot、latest查询和run-local driver均为consumer/protocol/lookup/Presentation；现有生产路径没有从它们反向重写已提交 envelope lineage 的接口。已执行 driver只保留历史审计价值。 | `confirmed：没有需迁移的第二authority；validation copy冲突只会fail-closed。` | `none；未删除代码，也未新增owner。` |
| semantic boundary | may change：仅在审核证明现有回归不足时补一条 focused authority regression，证明 latest/summary/checkpoint或payload副本不能替换 exact envelope ref。must remain unchanged：Artifact/Registry/Graph/Store/checkpoint public contracts、freshness语义、exact-role allowlist、Artifact payload、Graph topology、产品行为、Build/Runtime、历史 bytes/hash和C5/C6。若现有测试已覆盖，则生产代码和测试均 unchanged，只运行受影响验证。 | `approved：现有回归足够，production/test change均不需要。` | `边界保持；未触及C6、产品、Build/Runtime或正式Artifact。` |
| unresolved_contract_decisions | `[]`。inventory结论是 existing immutable envelope 已为唯一 durable owner；是否需要补测试仅是 coverage判断，不是公共合同决定。 | `[]` | `[]` |

### 10.6 C4 completion checkpoint

- baseline HEAD：`1485ed43430fccce8753f221304c7fe08da7c146`；
- C1：`done`，commit `de8e4d683257333857df07d7d6237ddddd93f0ef`；
- C2+C3：`done`，commit `7ed68f4709abc558382ce728b4ee1627d18e17c1`；
- C5：`done`，commit `1485ed43430fccce8753f221304c7fe08da7c146`；
- C4：首次 inventory 为 `unchanged/confirmed`；跨项复现后状态为 `reopened_for_exact_upstream_boundary`；
- C4 verification：`python -B -m pytest -q tests/unit/test_artifact_store.py tests/unit/test_artifact_contract.py tests/unit/test_workflow_graph.py tests/unit/test_repair_checkpoint_smoke.py tests/unit/test_local_entry.py tests/unit/test_verification_only_continuation.py`，`281 passed in 70.65s`；
- 工作包 A：`historical_v1_compatibility_verified`，commit `9bb6d019e11419c86bd058d98b5c8de854680f4c`；
- remaining：工作包 B、`C6`、`C7`；
- stop boundary：工作包 B 与 C1–C5 共同 checkpoint 完成前不进入 C6。

### 10.7 工作包 B：immutable upstream admission

本工作包只关闭一个已由当前 Store API 最小复现的 durable-lineage admission 缺口：
`ArtifactStore.write`/`write_with_result` 当前允许调用者把 latest alias `ArtifactRef` 作为 upstream；
`_validate_upstream_refs` 的 `read(upstream)` 能验证 alias 当下字节与 full hash，却不证明
`upstream.path` 是已注册 immutable revision。`_execute_write` 随后把该 path 原样纳入 child envelope；
alias 前移会使 `require_latest=false` 的 child 仍因同一路径字节变化而 stale。

| 合同项 | 推进页决策 | 审核页复核 | 实施与验收回填 |
| --- | --- | --- | --- |
| semantic goal | `ArtifactStore` 的每次新 child write 只能把已注册 immutable revision `ArtifactRef` 持久化进 `inputs.upstream_artifacts`。latest alias继续作为lookup/freshness comparison；不得成为durable upstream path。 | `实施前独立审核：approved；实施后独立验收：approved；execution_blocker=none。` | `implemented and verified；commit dac15ca17db595ffff7ea4a0949f8d80accd0415` |
| bounded owner inventory | authority：`ArtifactStore._execute_write → _validate_upstream_refs` 是所有 `write`/`write_with_result` 在envelope hash、pending marker与revision写入前的共同admission。consumer：Graph `_artifact_ref_from_state`、checkpoint state refs与各materializer传入Store返回的revision ref；`WorkflowCheckpointStore._latest_revision_ref` 会把latest pointer解析回唯一revision。lookup/observation：`local_entry`、verification-only、Stagger runtime及HTTP/dashboard/MCP的 `list_feature_artifacts` 使用只负责latest比较或展示，不拥有durable lineage。validator：Registry只拥有required role/freshness policy；`read`验证bytes/hash/schema但不区分alias/revision角色。当前实际调用路径未发现 `list_feature_artifacts` 结果直接进入child write，缺口位于公开Store API仍可被直接旁路。 | `approved；authority位置与调用面分类成立。` | `confirmed；生产变更未扩张到consumer、Registry或Graph。` |
| immutable path admission | 在 `_validate_upstream_refs` 的任何domain-specific Request/Build/Runtime校验之前，对每个upstream强制：①`feature_id`与child相同；②`artifact_type`合法；③full `artifact_hash`可生成当前32位physical locator；④resolved `path`精确等于该feature/type/hash的 `r/<artifact_type>/<hash[:32]>.json` 或兼容 `revisions/<artifact_type>/<full_hash>.json`；⑤该文件存在，且`ArtifactStore.read`验证envelope feature/type/full hash/content hash/Registry合同通过。latest alias、其他非revision path、path/hash/type/feature不一致均在pending marker前拒绝。 | `approved；短locator collision由full-hash read-back继续fail-closed。` | 新增`ArtifactStore._validate_immutable_upstream_ref`，并由`_validate_upstream_refs`在所有domain-specific分支前逐项调用；旧尾部重复feature/read校验已移除。 |
| write/result boundary | `write()`与`write_with_result()`继续共用 `_execute_write`；不新增API。`write_with_result`沿C5现有合同返回`blocked_before_commit`、`commit_started=false`、`failure_stage=admission_validation`；revision/latest/pending增量均为0。兼容`write()`抛现有`ArtifactStoreError`/`StaleArtifactError`，不隐式转换、重试或恢复。`ArtifactWriteResult`字段与三态语义不改。 | `approved。` | 真实filesystem测试对两种API及四类drift验证写前拒绝与全JSON字节零变化；未修改C5实现。 |
| freshness semantics | child envelope仍保存调用者给出的immutable revision path/full hash及现有`require_latest`布尔值。`require_latest=false`时只验证该immutable revision subgraph，不因alias前移而stale；`require_latest=true`仍比较latest logical identity，alias前移后child按原合同stale，但envelope内path始终是immutable revision。C4不改`_collect_stale_reasons`、`_check_upstream_write_freshness`或exact-role allowlist。 | `approved。` | current revision正向测试证明两种模式均保存revision path；alias前移后exact child为fresh、latest-bound child为stale。 |
| historical compatibility | 新admission仅用于新write。`ArtifactStore.read`、Registry envelope validation与freshness读取路径不增加immutable-path拒绝，因此历史envelope保持原bytes/hash和读取行为，不迁移、不重写。正式共享Store只读扫描113个JSON、288个upstream entry：alias=0、nonrevision=0、missing=0、path目标full-hash mismatch=0；当前不需要历史修复。 | `approved；无迁移要求。` | latest alias仍可由`read`回读；legacy full-hash revision可作为新upstream；正式Store未写。 |
| public caller compatibility | Store成功写入返回的`ArtifactRef.path`本来就是immutable revision path；Graph、checkpoint、authority、Build、Runtime与现有materializer的正常write site行为不变。`list_feature_artifacts`继续返回latest alias，供查询/比较；需要持久化lineage的调用者必须使用Store write result、`list_feature_artifact_revisions`或checkpoint的唯一revision解析结果。不得让Store静默把alias自动替换成latest revision，因为这会隐藏调用者身份错误并改变approved input。 | `approved。` | 317项联合受影响回归通过；未发现正常public/Graph/materializer handoff被拒绝。 |
| contract changes | 仅收紧`ArtifactStore`新write的upstream admission；Artifact/Registry/Graph/checkpoint/public API类型、envelope字段、canonical hash算法、freshness policy、C5 result、recovery和历史read均unchanged。production touchpoint预计仅`src/mod_agent/artifacts/store.py`；focused tests位于`tests/unit/test_artifact_store.py`，只有真实受影响时才补相邻contract/checkpoint回归。 | `approved。` | production仅`store.py`；测试改动为`test_artifact_store.py`和一条verification-only既有private-role测试的fixture隔离。 |
| validation | ①`list_feature_artifacts()`返回的latest alias分别传给`write()`与`write_with_result()`，两者写前拒绝；②result精确为`blocked_before_commit/commit_started=false/admission_validation`；③child revision/latest/pending及原parent字节均零增量；④immutable revision+`require_latest=false`在alias前移后仍fresh；⑤`require_latest=true`仍比较latest identity，且child envelope持久化revision path；⑥current `r/`和legacy `revisions/` revision均接受，alias/nonrevision/path-hash/type/feature drift均拒绝；⑦历史Artifact与alias lookup仍可读；⑧现有ArtifactStore、Artifact contract、Graph/checkpoint/local-entry affected suite通过；⑨正式Store扫描继续无alias/nonrevision upstream。 | `approved。` | 定向5项`5 passed in 1.13s`；联合命令覆盖Store、contract、Graph、checkpoint、local entry、verification-only、Stagger authority/planner，`317 passed in 86.90s`；alias read补充断言`1 passed in 0.33s`。 |
| stop conditions | 若实现必须修改envelope/hash/freshness含义、历史read、Graph/Registry/checkpoint合同、C5 result/recovery，或发现现有公共producer确实依赖alias作为durable upstream，则停止并回到同一合同审核。普通private helper、错误文本和fixture组织不触发重审。 | `approved。` | 未触发；首次联合回归唯一失败来自旧private测试的根外伪ref，已只在该测试中显式隔离filesystem gate，未放宽生产合同。 |
| unresolved_contract_decisions | `[]`。Store拒绝alias而不自动解析替换；历史读取兼容；当前与legacy revision目录均按exact feature/type/full-hash identity接受。 | `[]` | `[]` |

### 10.8 C1–C5 completion checkpoint（2026-08-03）

- checkpoint HEAD：`dac15ca17db595ffff7ea4a0949f8d80accd0415`；
- C1：current capability authority implemented，commit `de8e4d683257333857df07d7d6237ddddd93f0ef`；
  historical v1 capability compatibility verified，commit `9bb6d019e11419c86bd058d98b5c8de854680f4c`；
- C2：canonical Approval Identity implemented，historical versioned resolver verified；
- C3：Approval Identity / Artifact / Machine Result / Observation-Presentation hash边界已在当前
  Stagger Edit Authority范围验证，且current declaration前移不改变旧v1 identity；
- C4：durable lineage owner仍为immutable envelope；新write immutable-upstream admission verified，
  commit `dac15ca17db595ffff7ea4a0949f8d80accd0415`；
- C5：Store-owned `ArtifactWriteResult` primitive complete；public executor adoption仍属于C6；
- 共同验证命令：
  `python -B -m pytest -q -p no:cacheprovider tests/unit/test_edit_authority_capabilities.py tests/unit/test_artifact_contract.py tests/unit/test_artifact_store.py tests/unit/test_stagger_edit_authority.py tests/unit/test_workflow_graph.py tests/unit/test_local_entry.py tests/unit/test_repair_checkpoint_smoke.py tests/unit/test_verification_only_continuation.py tests/unit/test_stagger_planner_admission.py`；
  首次执行因180秒命令预算在未出现测试失败时超时，不计完整结果；同一命令以300秒预算重跑为
  `349 passed in 207.33s`；
- 正式共享Store只读检查仍为113个JSON、288条upstream，alias/nonrevision/missing/hash mismatch均为0；
- remaining：C6、C7、第二产品切片复用验证、后置Authority文档归并与独立审核；
- overall：`partial`。该checkpoint恢复进入C6的前置条件，但不自行授权产品源码、Build/Runtime、
  GTFO、游戏目录或正式产品Artifact副作用，也不触发
  `post_consolidation_authority_document_reconciliation_and_independent_audit`。

## 11. C5 — Receipt 语义

### 11.1 两种结果职责

实施时分别表达：

1. Store commit acknowledgement
   - Store operation 是否提交 immutable revision；
   - latest replacement 是否完成；
   -是否停在 declared partial state。
2. Domain machine evidence
   - Build、Runtime、resume、evaluation 等阶段实际做了什么。

两者保持独立职责；Store acknowledgement 使用 API result，领域事实继续使用现有 Artifact。

### 11.2 Store/public-executor structured result

public execution boundary 必须返回一份权威 structured result，至少能表达：

- logical Artifact identity；
- immutable revision location；
- latest alias location；
- latest 是否指向 committed identity；
- committed、blocked-before-commit 或 partial outcome；
- pending-marker state；
- failure stage/error class；
- recovery 是否可用但未自动授权。

迁移保持 `ArtifactStore.write()` 兼容。推进页可以根据实际调用面选择：

- public executor 包装现有 `ArtifactRef` 和 read-back facts；或
- 增加一个不破坏旧调用方的兼容 Store API。

优先采用增量兼容路径；若全量返回类型调整能显著降低复杂度，推进页需要在合同表中说明
调用面、迁移成本和回滚方式后再决定。

### 11.3 Domain machine evidence

现有 Artifact 继续保持领域权威，不新增总控 Receipt Artifact：

- `BuildResult`：Build facts；
- `WorkflowCheckpoint`：resumable state；
- `ResumeReport`：resume admission/consumption；
- `RuntimeEvidence`：Runtime facts 与 bound observations；
- evaluation/terminal Artifact：现有职责。

Receipt 保持以下语义分离：

- Store success ≠ product success；
- Build success ≠ Runtime success；
- machine marker ≠ human visual/audio success；
- recovery available ≠ recovery authorized。

### 11.4 C5 实施合同表：Store/Result Receipt

#### 11.4.1 有界 owner inventory

- 创建、canonical envelope hash、pending marker、immutable revision、latest alias 和提交顺序的
  当前 owner 是 `src/mod_agent/artifacts/store.py::ArtifactStore.write`；
  `ArtifactTypeRegistry`、upstream/freshness 校验和 `ArtifactStore.read` 是 validator，不能另行解释
  commit outcome。
- Graph、checkpoint 和领域 materializer 当前只消费 `ArtifactRef`；它们没有 Store commit 的第二套
  durable 状态。C5 不改变 Graph route、state topology 或领域 Artifact 合同。
- `ArtifactStore.recover_pending_writes` 是显式 recovery executor。它不授权 recovery，也不能把一次
  initial write 的 partial outcome 改写成“此前已 committed”。
- write admission 先解释 pre-existing exact Store state：有效 exact pending marker 的优先级高于
  revision/latest；普通 write 只能报告该 partial，不得消费它。只有 pending 不存在且 exact revision
  与 latest 已共同验证为同一 logical identity 时，才允许无写入 idempotent committed。
- `workspaces/stagger_c4_evidence_consolidation_001/project_c4_evidence_consolidation.py`
  等 run-local driver 会自行比较 revision count、pending、revision path 和 latest alias。C4 正式写入曾因
  alias path 与 immutable revision path 的角色混淆而在 Store 已成功后产生 false negative；该 driver
  后来改为验证 logical hash 与 alias/revision 字节一致。这个历史事实证明 driver 只能保留 observation
  和 Presentation，不能继续拥有 Store terminal verdict。
- 因此 C5 只迁移一个 semantic decision：一次 Store write 的 authoritative outcome。C6 再把公共
  Build/Runtime/evidence continuation 的结果透传到 public entry；本包不提前迁移这些 driver。

| 合同项 | 推进页决策 | 审核页复核 | 实施与验收回填 |
| --- | --- | --- | --- |
| semantic goal | 消除 `ArtifactStore.write()` 只返回 revision `ArtifactRef`、而外围调用者分别解释 latest/pending/partial 的冲突；让同一 Store owner 对一次 write 给出唯一 machine result，同时不把 Store success 提升为领域或产品 success。 | `实施前独立审核：approved。` | `ArtifactStore 现在独立给出 Store outcome；领域 payload/status 与产品结论未改变。` |
| result owner/API | 在 `src/mod_agent/artifacts/store.py` 定义 public frozen `ArtifactWriteResult`，并增加 `ArtifactStore.write_with_result(...) -> ArtifactWriteResult`。私有 `_execute_write(...)` 是 `write_with_result` 与兼容 `write` 的唯一执行/解释源；`ArtifactStore.write(...) -> ArtifactRef` 继续存在并委托同一 owner。`src/mod_agent/artifacts/__init__.py` 只导出 public type/API。 | `实施前独立审核：approved。` | `已按合同实现并导出 `ArtifactWriteResult`；两个 public write API 只委托 `_execute_write`。` |
| structured result schema | `ArtifactWriteResult` 固定包含：`outcome`；`feature_id`、`artifact_type`、nullable `artifact_hash`；nullable `artifact_ref`；nullable `revision_path`、`latest_alias_path`、`pending_marker_path`；`commit_started`；`revision_state=unavailable\|absent\|valid\|invalid\|unknown`；`latest_alias_state=unavailable\|absent\|matches_identity\|different_identity\|invalid\|unknown`；`pending_marker_state=unavailable\|absent\|present\|invalid\|unknown`；nullable `failure_stage`、`failure_class`、`failure_message`；`recovery_available`；`recovery_authorized=false`。`to_dict()` 是 Presentation/JSON 投影，字段不进入 Artifact content hash 或 Approval Identity。 | `实施前独立审核：approved。` | `public frozen dataclass 与 `to_dict()` 字段精确实现；Artifact hash 计算路径未引用该结果。` |
| outcome state machine | 调用开始先按固定优先级解释 exact state：①有效 exact pending marker 已存在时立即返回 `partial`、`commit_started=false`，不写 marker/revision/latest且不删除 marker；②pending 不存在且 exact revision 与 latest 都验证为同一 logical identity 时，无写入返回 idempotent `committed`、`commit_started=false`；③否则才进入新 attempt。新 attempt 的 `committed` 当且仅当 exact immutable revision 可由 `read` 验证、latest alias 可由相同 logical hash 验证、pending marker 已移除；此时且仅此时 `artifact_ref` 非空。`blocked_before_commit` 表示本 attempt 未成功安装 exact pending marker且未形成新的完整 commit。`partial` 表示本 attempt 已进入 commit protocol但未满足 committed，或终态检查无法证明完整 commit。历史 revision 单独存在、历史 latest 指向其他 identity，或一次 pending-before failure，均不得被误报为 committed/partial。 | `实施前独立审核：approved。` | `Store tests 覆盖三态、pre-existing pending、pre-existing committed、missing revision 与 historical revision/different latest。` |
| revision/alias/pending | revision path 与 latest alias path 是不同 role，不要求字符串相等；同一 logical identity 由 feature/type/full artifact hash 及两侧独立 envelope 验证确定。pre-existing state 检查顺序固定为 exact pending → exact revision/latest idempotence → 新 commit。新写序保持 pending marker → immutable revision（或复用已验证历史 revision）→ latest alias → read-back commit verification → pending cleanup。任何返回 committed 的路径都必须确认 pending absent；locator、文件总数和字节数不参与 outcome。至少覆盖 pre-existing pending 不被消费、pre-existing committed 无写入复用、历史 revision+不同 latest 的 pending-before failure不被旧状态掩盖。 | `实施前独立审核：approved。` | `实际写序和 read-back gate 已实现；成功测试明确断言 revision path != latest alias path 仍 committed。` |
| failure/recovery | `failure_stage` 固定为 nullable `admission_validation\|pending_marker_write\|immutable_revision_write\|latest_alias_write\|commit_verification\|pending_marker_cleanup`；`failure_class` 是实际 exception class 名，message 仅为机器诊断。新 API 捕获一次 attempt 的 `Exception` 并返回 structured failure，不 retry、不 replay、不 recover。有效 pre-existing exact pending 返回 partial；`recovery_available=true` 当且仅当该 partial 的 exact pending marker 存在且 immutable revision valid，`recovery_authorized` 始终 false。只有另行调用现有 `recover_pending_writes()` 才可能恢复；普通 `write_with_result` 与兼容 `write()` 都不得触碰或消费 pre-existing pending。 | `实施前独立审核：approved。` | `latest failure、pending cleanup failure、pre-existing pending+valid/missing revision 均有 filesystem regression；没有测试或生产路径自动调用 recovery。` |
| domain evidence handoff | `BuildResult`、`WorkflowCheckpoint`、`ResumeReport`、`RuntimeEvidence` 与 evaluation/terminal Artifact 继续记录各自领域事实；`ArtifactWriteResult` 只记录这些 Artifact 自身的 Store commit。Store committed 不改变 payload status，也不证明 Build、Runtime、evaluation 或产品 success。 | `实施前独立审核：approved。` | `Graph/state/领域 Artifact 未修改；319 项受影响链回归通过。` |
| compatibility path | 选择兼容 Store API，不全量改变 89 个现有 `write` 调用面。`write()` 使用同一 `_execute_write`：新 commit 或无写入 idempotent committed 时仍返回 immutable revision `ArtifactRef`；non-committed 时重新抛出原 exception type/message，若没有原 exception（包括 pre-existing pending 或只发生终态验证失败）则抛 `ArtifactStoreError`。这有意移除普通 write 隐式完成旧 pending 的行为；显式 recovery API 保持唯一恢复入口。新的 public executor 使用 `write_with_result`，无需再从路径或 Store totals 重建 outcome。现有 `recover_pending_writes()` 返回合同保持可读。 | `实施前独立审核：approved。` | `所有现有生产调用继续使用 `write()`；原成功、OSError、Registry、legacy revision与recovery tests通过。历史非法 Request测试fixture只在种子写入期同步绕过write/envelope validator，生产合同未放宽。` |
| removed authority | C5 完成后，任何 migrated public executor/driver 不得以 revision delta、Store totals、stdout、path equality 或自定义 pending 扫描覆盖 `ArtifactWriteResult.outcome`。现有 run-local driver 保留历史审计价值；C6 迁移前仍可做只读一致性检查，但冲突时必须以 Store result 为 commit authority。负向测试证明一个伪造 post-write path-equality validator 不能把 committed 改成 failed。 | `实施前独立审核：approved。` | `Store result owner 已可供 public executor 消费；driver/public continuation 的实际迁移仍明确留给 C6，本包未提前改动。` |
| semantic boundary | may change：Store write 的 API-level result、commit read-back、失败分类与显式 recovery availability。must remain unchanged：Artifact envelope/content hash、Registry/upstream/freshness、physical locator、Graph topology/state、现有 Artifact 类型/payload/status、Approval Identity、产品行为、Build/Runtime/外部副作用，以及 recovery 的独立授权要求。 | `实施前独立审核：approved。` | `生产变更只在 `src/mod_agent/artifacts/store.py` 与 export；无 Graph/runtime/feature-specific/Product/Artifact-contract 修改。` |
| unresolved_contract_decisions | `[]`。普通 helper、内部 exception transport 和 fixture 组织由实施自行决定，不改变上述 public contract。 | `实施前独立审核：approved。` | `[]` |

实施后受影响测试命令：

`python -B -m pytest -q tests/unit/test_artifact_store.py tests/unit/test_artifact_contract.py tests/unit/test_workflow_graph.py tests/unit/test_repair_checkpoint_smoke.py tests/unit/test_local_entry.py tests/unit/test_build_adapter.py tests/unit/test_verification_only_continuation.py tests/unit/test_stagger_edit_authority.py`

首次实施后独立验收发现：异常分支曾以 `pending_path.exists()` 推断本 attempt 已安装 marker，
会把 pre-existing invalid/collision marker 误报为 partial。实现已改为分别跟踪
`pending_write_attempted`，并只在本 attempt 写后 exact marker 验证通过时设置
`commit_started=true`；新增 invalid marker 与 short-locator collision 零写入回归。

结果：`319 passed in 65.25s`。另执行 `python -B -m py_compile src/mod_agent/artifacts/store.py src/mod_agent/artifacts/__init__.py`，通过。

最终实施后独立复验：`post_implementation_verdict=approved`。C5 已提交为
`1485ed4`（`refactor: make artifact write outcomes authoritative`）。整体
Control Plane Consolidation 仍为 `partial`；C4、C6 与第二产品切片尚未完成。

### 11.5 当前有效实施合同：Edit Authority ordered structured result adoption

> 状态：`independently_verified_and_committed`。本节是当前有效的有界
> C5 adoption 工作包；它不推翻 C1 capability/Approval Identity、C4 lineage、C5 Store primitive
> 或 C6 typed Verification Operation 已提交事实，只修复 Edit Authority 完整审核链尚未消费
> `ArtifactWriteResult` 的缺口。P0 core contract/implementation 已经独立验收并提交为
> `5f68265`；§11.5.10 follow-up 已独立验收并提交为 `9527d40`。P0 最终
> Presentation/result invariants 已闭合；P1-P4 仍未开始。

#### 11.5.1 真实 owner inventory 与 semantic goal

- 当前 active public chain 为
  `WorkflowCheckpoint -> ResumeReport -> EditAuthorityApproval -> EvidencePack -> ImplementationPlan
  -> optional BindingResolution`。Graph 仍调用兼容 `create_checkpoint()`/`resume()`，四类
  materializer 仍顺序调用 `ArtifactStore.write()`；任一后序写入失败时，前序 Artifact 可能已
  committed，但 public entry 只能从 `current_stage`、Graph `artifacts` 与 revision totals 推导整体
  `BLOCKED`，不能返回逐项 C5 machine truth。
- `ArtifactStore.write_with_result()`/`ArtifactWriteResult` 已是单次 Store attempt 的唯一 owner；
  本工作包只让 Edit Authority protocol/materialization chain 消费该 owner，不新建 Receipt Artifact、
  多 Artifact transaction Controller 或自动 recovery。
- `materialize_stagger_edit_authority_approval()` 的生产调用者只有
  `_run_stagger_edit_authority_gate`；其他 direct caller 均为测试，且该函数未从
  `runtime/__init__.py` 导出。它是内部 materialization executor，不是受支持的 public entry。
- 当前 CLI 的 `resume-stagger-edit-authority-review` 维护独立 success-status 集合，并遗漏
  `STAGGER_BOUNDED_OBSERVATION_PLAN_AUTHORIZED`；bounded public success 会被错误投影为 exit 2。
- 本包 semantic goal 是：用一份 declaration-ordered Store fact collection 和一个公共 result
  projector，正交表达平台执行、人类审核、materialization 与 Store side-effect 事实；删除
  Graph/public/CLI 对链级 terminal status 的重复解释，同时保持五种现有 capability、legacy JSON、
  Approval Identity、Artifact payload/hash 和产品副作用边界。

#### 11.5.2 authority 与公共类型

| 合同项 | 已决定的实施合同 |
| --- | --- |
| result owner | `src/mod_agent/edit_authority_capabilities.py` 定义 public frozen `EditAuthorityReviewResultV1`、`EditAuthorityStoreStepV1` 及唯一纯函数 projector/validator。该模块继续不导入 Graph、local entry、Store instance 或 runtime materializer。 |
| Store fact owner | `ArtifactWriteResult`/`ArtifactWriteResult.from_dict()` 继续独占单次 write outcome、commit_started、pending/revision/latest 与 recovery facts；Edit Authority projector只组合 typed Store facts，不复制 C5 state machine。 |
| execution owner | Graph 只拥有 interrupt、checkpoint/resume、materializer 调用顺序与“首次失败立即停止”；它把序列化 `EditAuthorityReviewResultV1` 放入 ephemeral state，不重新解释 Store outcome。 |
| materializer owner | `materialize_stagger_edit_authority_approval()` 与四个 apply helper只拥有业务 payload、exact refs 和真实 materialization Store attempts；可暂时保留旧 flat status作为由 materialization facts派生的兼容字段，但不得拥有完整链级 projector。 |
| public/CLI owner | `resume_stagger_edit_authority_review()`只消费 Graph 的 authoritative structured result并投影 legacy字段；CLI只消费 structured result决定 exit，不维护success字符串集合。 |

`EditAuthorityReviewResultV1` 的 exact public schema 固定为：

```yaml
result_contract_version: edit_authority_review_result_v1
capability_id: str
capability_contract_version: str
approval_identity_hash: str
platform_status: completed | blocked | partial
review_outcome: not_recorded | approved | rejected
materialization_status: not_started | not_applicable | completed | incomplete
failure_stage:
  graph_interrupt
  | checkpoint_construction
  | checkpoint_store
  | resume_validation
  | resume_report_store
  | store_preflight
  | materialization_validation
  | edit_authority_approval_store
  | evidence_pack_store
  | implementation_plan_store
  | binding_resolution_store
  | internal_execution
  | null
store_steps: tuple[EditAuthorityStoreStepV1, ...]
protocol_outputs: tuple[ArtifactRef, ...]       # projector-derived
materialization_outputs: tuple[ArtifactRef, ...] # projector-derived, current-attempt committed writes only
platform_blockers: tuple[dict, ...]
review_reasons: tuple[dict, ...]
artifact_store_commit_started: bool
artifact_store_writes_committed: bool
recovery_available: bool
recovery_authorized: false
retry_count: 0
source_modified: false
build_performed: false
process_launched: false
product_runtime_performed: false
audit_snapshot: dict
```

`approval_identity_hash` 是既有 C2/C3 owner 已验证的 hash；本结果不得重新 canonicalize 或另建
Approval Identity。`audit_snapshot`、revision totals、latest alias、stdout、Presentation 与 result 自身
全部排除 Approval Identity 和 Artifact content hash。

#### 11.5.3 canonical `store_steps` 与 declaration 顺序

唯一内部 Store 事实集合固定为：

```yaml
store_steps:
  - role: exact_artifact_role
    store_result: ArtifactWriteResult
```

caller、Graph 与 materializer不得向 step 填入 `phase`、`required`、output ref、chain status 或
recovery status。唯一 projector 必须验证：

1. `role == store_result.artifact_type`；
2. 每个 result 的 `feature_id` 与当前执行一致；
3. roles 是 `capability.review_write_artifact_types` 的合法有序前缀；
4. role 不重复、不跳过、不重排；
5. 第一个 `blocked_before_commit` 或 `partial` result 必须是最后一个 step；
6. committed output ref 只来自同一 step 的 committed `artifact_ref`；
7. `blocked_before_commit`/`partial` 的 `artifact_ref` 必须为 null，不产生 output；其
   revision/pending/recovery事实只保留在 Receipt；
8. 未执行 roles 由 declaration 完整序列与实际 prefix 的差集推导。

`phase` 只由 role 派生：`workflow_checkpoint`、`resume_report` 属于 protocol，其余 declaration
write roles属于 materialization。requiredness 由 declaration 与已提交审核决定共同推导：

- `review_outcome=rejected`：适用序列只到 protocol prefix；
- `review_outcome=approved`：适用序列为完整 `review_write_artifact_types`；
- `review_outcome=not_recorded`：不得进入 materialization。

`materialized_artifact_fields` 是 Graph 的 effective-ref/result-field 映射，不是本次 Store attempt
列表。尤其 existing-binding 会复用既有 EvidencePack/ImplementationPlan；这些 immutable refs可以
保留在 legacy `artifacts`/Graph effective refs中，但不得进入本次 `materialization_outputs`、不得
增加 committed-write计数，也不得用于判定本次 materialization completed。实际 Store attempt顺序
只由 `review_write_artifact_types` 决定。

#### 11.5.4 审核决定 provenance 与 reasons

`review_outcome` 只能由同一次 `WorkflowCheckpointStore.resume_with_result()` 调用绑定的三项事实
共同决定：传入该次调用的 exact `ResumePayload.decision`、`ResumeValidator`/preflight 返回的
`ResumeDecision`、以及 exact ResumeReport 的 `ArtifactWriteResult`。不允许 public caller 或 projector
另收一份 decision 字符串。

- 只有 `ResumeDecision.status="accepted"`、`allowed=true`、exact payload decision 为
  `approve|reject` 且 ResumeReport Store result=`committed` 时，才能记录 `approved|rejected`；
- ResumeReport 没有 committed，或 decision 为 structured blocked 时，固定
  `review_outcome=not_recorded`；caller 传入 approve/reject 不构成已记录的人类决定；
- 当前 `ResumePayload` 虽有 `notes`，但 Edit Authority public entry不接收、`ResumeReport`也不持久化
  notes；本包不扩展 ResumeReport schema，不得声称保存了人类填写的批准/拒绝理由；
- approved 的 `review_reasons=()`；rejected 固定为规范化 reason
  `EDIT_AUTHORITY_REJECTED`，`failure_stage=null`、`platform_blockers=()`；
- `ResumeDecision.reason="Resume payload accepted."` 只可进入非权威 audit，不能冒充 human reason；
- validation、Store、Graph 与内部执行失败只进入 `platform_blockers`。legacy outer `blockers`可为兼容
  展示合并两类信息，但不能反向决定 structured result。

#### 11.5.5 三轴状态、failure 优先级与停止不变量

| 场景 | `platform_status` | `review_outcome` | `materialization_status` | `failure_stage` |
| --- | --- | --- | --- | --- |
| accepted reject ResumeReport committed | `completed` | `rejected` | `not_applicable` | `null` |
| accepted approve且全部适用roles committed | `completed` | `approved` | `completed` | `null` |
| 首个 protocol Store commit前失败 | `blocked` | `not_recorded` | `not_started` | exact stage |
| Checkpoint committed后、ResumeReport未committed | `partial` | `not_recorded` | `not_started` | `resume_report_store`或`resume_validation` |
| structured blocked decision + ResumeReport committed | `blocked` | `not_recorded` | `not_started` | `resume_validation` |
| accepted approve ResumeReport committed后、首个EditAuthorityApproval Store调用前的preflight/validation失败 | `partial` | `approved` | `incomplete` | `store_preflight`或`materialization_validation` |
| approve ResumeReport committed后首个业务写失败 | `partial` | `approved` | `incomplete` | exact materialization/Store stage |
| 前序业务write committed、后序失败 | `partial` | `approved` | `incomplete` | exact stage |
| 任一 Store result=`partial` | `partial` | 只按committed report决定 | `not_started|incomplete` | exact Store stage |

Resume 阶段优先级必须精确为：

```text
structured blocked decision + ResumeReport committed
  -> failure_stage=resume_validation

structured blocked decision + ResumeReport blocked_before_commit|partial
  -> failure_stage=resume_report_store

resume validation/payload construction抛异常且未调用Store
  -> failure_stage=resume_validation
```

Store写入失败覆盖原validation归类，但不改变`review_outcome=not_recorded`。

失败后停止规则：

1. `preflight_resume()`或`ResumeValidator.validate()`正常返回structured blocked decision时，允许且只允许
   构造/尝试写一份 blocked ResumeReport，记录其真实 Store result 后立即停止；
2. resume validation或payload construction抛异常、无法构造可信 ResumeReport时，不调用ResumeReport
   Store并立即停止；
3. committed human reject ResumeReport后立即停止，不调用Store preflight或materializer；
4. 任一其他非Store failure后不再执行后续Store role；
5. 任一noncommitted Store result后不再执行后续Store role；
6. 不得在前序失败后继续写后序 Artifact。

#### 11.5.6 side effects、projector 与 Presentation

以下字段只由 `store_steps` 派生：

```text
artifact_store_commit_started = any(step.store_result.commit_started)
artifact_store_writes_committed = any(step.store_result.outcome == "committed")
recovery_available = any(step.store_result.recovery_available)
```

`recovery_authorized=false`、`retry_count=0`。Store protocol write与产品副作用分层；source、Build、
process、product Runtime事实固定为false。revision totals、文件数量和latest alias只能进入audit。

唯一 projector是纯函数；对全部通过schema/invariant validation的合法typed facts必须total且确定，不读取
Store、文件系统、环境、stdout或Presentation。非法steps在projector输入验证中fail-closed，不伪造
ArtifactWriteResult。`internal_execution`只表示trusted admission后、projector前的可归属执行异常；公共
层用当前合法step prefix直接返回structured result，不新增第二个“携带同一result”的execution异常通道。
系统级不可恢复异常不纳入业务合同。

一旦 projector形成任一合法 machine result，后续legacy projection、audit、JSON、stdout和CLI失败均不得
重算或降级该结果。只新增：

```text
EditAuthorityPresentationError(LocalEntryError)
```

它由`local_entry.py`拥有，仅携带已冻结的`EditAuthorityReviewResultV1`以及非权威
`presentation_error={error_class,error_message}`/nullable `audit_error`。所有required roles committed后，
machine truth固定为`completed/approved/completed`；Presentation失败不能改为blocked/partial。

#### 11.5.7 Graph state、legacy/CLI 与兼容边界

- `ModAgentState`增加`edit_authority_review_result`，值为序列化
  `EditAuthorityReviewResultV1`；唯一writer为`stagger_edit_authority_gate`，public entry只读。
- 该字段不进入Artifact payload/hash、Approval Identity、audit hash或
  `WorkflowCheckpoint.state_snapshot`；必须有负向测试锁定checkpoint payload不存在该字段。
- legacy status只由三轴结果派生：
  `completed+approved+completed -> capability.public_success_status`；
  `completed+rejected+not_applicable -> BLOCKED`；`blocked|partial -> BLOCKED`。
- `src/mod_agent/cli.py`只允许修改`resume-stagger-edit-authority-review`分支：删除hardcoded success
  status集合，消费structured result；approved completed返回exit 0，rejected/blocked/partial返回exit 2，
  legacy JSON保持。必须覆盖bounded success不再错误返回exit 2。
- `materialize_stagger_edit_authority_approval()`签名可保留；direct tests只验证业务payload、exact refs、
  Store facts与旧flat兼容投影，不得把其status当作公共链级终态。

#### 11.5.8 implementation scope、测试门与停止条件

允许生产定位：

- `src/mod_agent/edit_authority_capabilities.py`
- `src/mod_agent/runtime/stagger_edit_authority.py`
- `src/mod_agent/workflow/graph.py`
- `src/mod_agent/workflow/state.py`
- `src/mod_agent/workflow/checkpointing.py`
- `src/mod_agent/local_entry.py`
- `src/mod_agent/cli.py`中仅`resume-stagger-edit-authority-review`
- 相邻focused unit/integration tests

最低验收：

1. 五种capability均按declaration exact write-role sequence执行；actual steps为合法prefix，失败后无后续写；
2. checkpoint/resume及Approval/Evidence/Plan/Binding各位置覆盖
   `committed|blocked_before_commit|partial`，并逐点注入payload construction/validation异常；
3. structured blocked decision允许且只允许blocked ResumeReport attempt；validation异常不写report；
   若该blocked decision的ResumeReport已committed，结果必须固定为
   `blocked/not_recorded/not_started/resume_validation`，保留真实protocol refs/receipts，且materializer调用为0；
4. accepted reject committed返回`completed/rejected/not_applicable`且materializer调用为0；
5. accepted approve ResumeReport committed后、首个EditAuthorityApproval Store调用前发生
   `store_preflight|materialization_validation`失败时，结果必须固定为
   `partial/approved/incomplete`，保留checkpoint/report committed refs/receipts，不伪造Approval Store result，
   且后续写为0；approval committed后Evidence payload异常同样保留既有refs/receipts，不伪造Evidence result，
   链级partial；
6. existing-binding复用的EvidencePack/ImplementationPlan不计为本次committed outputs；
7. projector负向覆盖role/type/feature漂移、duplicate/skip/reorder及noncommitted后续step；
8. Graph state字段不进入WorkflowCheckpoint payload/hash；audit/revision totals变化不改变machine result；
9.全部required writes committed后Presentation异常携带同一completed result且不改Store facts；
10. CLI真实调用公共entry，bounded approved success exit 0；rejected/blocked/partial exit 2；
11. 现有Approval Identity/hash、C4 immutable upstream、C5 Store三态、C6 typed operation、产品零副作用
    focused回归保持。

停止并回到合同审核的条件：需要改变Request/Approval Identity或hash、Artifact类型/schema、C5三态或
recovery权限、capability discriminator、Graph topology、C6 Verification Operation、ResumeReport schema，
或需要新Receipt Artifact、通用事务Controller、自动retry/recovery。Evidence public entry、
`run_local_request()`、Repair Planning、dynamic review、第二产品切片及后置Authority文档归并不在本包。

```yaml
contract_completeness: closed
unresolved_contract_decisions: []
implementation_authorization: approved
implementation_status: independently_verified_and_committed
```

#### 11.5.9 P0 实施回填（待独立验收）

- 时间盒：`2026-08-06T13:35:00+08:00` 开始，`2026-08-06T14:57:27+08:00`
  形成唯一 staged 对象，未超过四小时上限，未进入 P1–P4。
- 公共 result owner 已落在 `src/mod_agent/edit_authority_capabilities.py` 的
  `EditAuthorityStoreStepV1`、`EditAuthorityReviewResultV1`、
  `project_edit_authority_review_result()` 与 `parse_current_edit_authority_review_result()`；
  projector只组合 Store-owned `ArtifactWriteResult`，不复制 C5 commit state machine。
- 四类 materializer apply helper 改为按 declaration role 顺序调用
  `ArtifactStore.write_with_result()`，保留 exact committed/noncommitted prefix，并在首个
  noncommitted receipt 或两次写之间的 validation/payload 异常后停止。Graph 的
  `_run_stagger_edit_authority_gate()` 使用 `create_checkpoint_with_result()`、
  `resume_with_result()` 和同一 ordered projector；`_finish_stagger_edit_authority_gate()`
  只从机器结果派生 legacy Graph state。
- `ModAgentState.edit_authority_review_result` 只存在于 ephemeral state，checkpoint snapshot
  明确不持久化该字段。`resume_stagger_edit_authority_review()` 严格解析 Graph result，
  `EditAuthorityPresentationError` 在审计/展示失败时携带同一冻结结果；CLI 只按 structured
  三轴结果映射 exit code，不再维护 success-status 字符串集合。
- 失败矩阵实测覆盖 checkpoint/resume 与 Approval/Evidence/Plan/Binding 的 committed、
  blocked_before_commit、partial；human reject、structured blocked resume、resume construction
  exception、Store preflight、首个业务写前 validation、Approval committed 后 Evidence payload
  exception，以及失败后零后续写。实施测试发现并修正“首个 WorkflowCheckpoint result=partial
  被误判 blocked”的 projector 缺陷；当前任一 Store partial 均保持 platform partial。
- 五种 capability 均通过 declaration exact role order；CLI 测试不替换 public function，真实调用
  `resume_stagger_edit_authority_review()` 并消费 structured result。existing-binding 复用的既有
  EvidencePack/ImplementationPlan 不进入本次 committed outputs。
- 精确 focused 命令：
  `python -B -m pytest -q -p no:cacheprovider tests/unit/test_artifact_store.py tests/unit/test_artifact_contract.py tests/unit/test_edit_authority_capabilities.py tests/unit/test_stagger_edit_authority.py tests/unit/test_workflow_graph.py tests/unit/test_mod_agent_cli.py tests/unit/test_verification_operation_contract.py tests/unit/test_verification_operation_checkpointing.py tests/unit/test_verification_operation_graph.py tests/unit/test_verification_operation_cli_adapter.py`

- `changes_required` correction checkpoint (supersedes the staged identity below as the
  current review object): the declaration-owned projector now forbids materialization
  roles after `rejected|not_recorded`; forbids downgrading an all-required-role committed
  chain with a later execution failure; requires an exact non-Store failure stage for an
  incomplete committed-only prefix; and fixes `rejected` to `platform_blockers=()`.
  Adjacent projector and strict-parser negative regressions were added without changing
  the public schema, Graph, materializers, or C5. The exact focused command above now
  reports `449 passed in 76.33s`; the same ten Python files pass `py_compile`, and
  `git diff --cached --check` passes. Current staged identity: 10 files,
  `2942 insertions / 482 deletions`; normal binary diff=`155913 bytes`, SHA256
  `B2EBEB2BDBC800E1E5BAB2DD9282795D4E7D90055521966E1932F15898311A28`;
  `--full-index` binary diff=`156573 bytes`, SHA256
  `B863A2510714FEDC8F4A36F469C986675322569EAA9392FB59934E203C3272EF`.

- Second `changes_required` correction checkpoint (supersedes both staged identities
  below): caller-supplied `execution_failure_stage` now rejects every Store-owned stage
  (`checkpoint_store`, `resume_report_store`, `edit_authority_approval_store`,
  `evidence_pack_store`, `implementation_plan_store`, `binding_resolution_store`). A
  Store failure stage can only be derived from the final real noncommitted
  `EditAuthorityStoreStepV1`. Six-value parameterized projector coverage and a strict
  parser tamper regression were added. The exact focused command reports
  `456 passed in 69.35s`; the same ten Python files pass `py_compile`, and
  `git diff --cached --check` passes. Current staged identity: 10 files,
  `3014 insertions / 482 deletions`; normal binary diff=`158548 bytes`, SHA256
  `61A1806FCB45ADBB4E6D52BD1C9957EA77728F7C559941D613EC4315B654096C`;
  `--full-index` binary diff=`159208 bytes`, SHA256
  `7305E77EE32D1166F49F8BF0AAE72196CC1328D0E317BA0DDE2F0F00DE008EE9`.

- Complete phase/prefix correction checkpoint (supersedes every earlier P0 staged
  identity below): the declaration-owned projector now derives the exact allowed
  non-Store failure-stage set from the real Store prefix, review outcome,
  materialization progress, and presence of a final noncommitted step. Empty,
  checkpoint-only, exact-protocol, partial-materialization, rejected, and fully
  committed phases are fail-closed against misplaced stages. A real noncommitted
  Store step cannot be accompanied by a second execution failure fact. Table-driven
  projector and strict-parser regressions cover the four reproduced failures plus
  adjacent phase mismatches. The exact focused command reports
  `466 passed in 90.32s`; the same ten Python files pass `py_compile`, and
  `git diff --cached --check` passes. Current staged identity: 10 files,
  `3160 insertions / 482 deletions`; normal binary diff=`164397 bytes`, SHA256
  `381806C974D014492926D76D6CFBCC2CA2EE9572AEA736BF7A762682E6EDB65E`;
  `--full-index` binary diff=`165057 bytes`, SHA256
  `18D8B361D13039E1AF4A07EF6170C835495D88106FD2630E2707FBBACDC0DCCC`.

- Final P0 checkpoint: the independent reviewer returned
  `post_implementation_verdict=approved` with `execution_blockers=[]` after an
  independent `466 passed in 93.96s` rerun. The exact approved staged identity above
  was committed as `5f68265` (`Adopt structured Edit Authority review results`). P0
  status is `independently_verified_and_committed`. This checkpoint does not complete
  C6/C7 or the overall consolidation, and P1-P4 remain open.

#### 11.5.10 P0 follow-up contract: Presentation/result invariant correction

```yaml
follow_up_status: independently_verified_and_committed
contract_verdict: approved
p0_core_authority_migration: independently_verified_and_committed
p0_final_presentation_result_invariants: independently_verified_and_committed
allowed_code_files_after_contract_approval:
  - src/mod_agent/cli.py
  - src/mod_agent/edit_authority_capabilities.py
  - tests/unit/test_mod_agent_cli.py
  - tests/unit/test_edit_authority_capabilities.py
forbidden_scope:
  - graph
  - materializer
  - artifact_store_or_c5
  - edit_authority_review_result_public_schema
  - p1_through_p4
```

This follow-up does not roll back commit `5f68265`; it closes two remaining invariants
inside the existing CLI Presentation adapter and declaration-owned result projector.
No code implementation is authorized until this exact contract receives an independent
`approved` verdict.

CLI exception ordering and exact Presentation projection are fixed as follows:

1. The `resume-stagger-edit-authority-review` command catches
   `EditAuthorityPresentationError` before the generic `LocalEntryError` branch.
2. That branch emits exactly this top-level JSON shape:

```yaml
result_type: edit_authority_presentation_error_v1
status: PRESENTATION_FAILED
command: resume-stagger-edit-authority-review
reason: str(EditAuthorityPresentationError)
edit_authority_review_result: exact exception.edit_authority_review_result.to_dict()
presentation_error: exact exception.presentation_error mapping
audit_error: exact exception.audit_error mapping | null
```

No additional top-level fields are permitted in this branch. `result_type` is the
discriminator. `status=PRESENTATION_FAILED` describes only the CLI/Presentation adapter;
it is not `EditAuthorityReviewResultV1.platform_status`, is never projected as
`status=BLOCKED`, and cannot change the nested frozen machine result. The command exits
with code `2` because normal CLI Presentation did not complete. That exit code does not
mean the approved action, Artifact writes, or machine platform status failed. The generic
`LocalEntryError` branch remains byte-shape compatible with its existing
`status=BLOCKED`/exit-`2` behavior and never consumes
`EditAuthorityPresentationError`.

The declaration-owned projector adds one matching result invariant:

- after `project_edit_authority_review_result()` derives the terminal facts, any result
  with `platform_status=completed` requires `platform_blockers=()`; a non-empty tuple is
  rejected with `ValueError` before construction;
- post-completion audit or Presentation errors belong only to
  `EditAuthorityPresentationError.presentation_error` / nullable `audit_error`; they may
  not be copied into `platform_blockers`;
- `EditAuthorityReviewResultV1.from_dict()` continues to reconstruct through the same
  projector, so a serialized `completed` result with non-empty `platform_blockers` also
  fails closed. No second parser rule table is added.

Minimum verification is exact: a completed/approved/completed result carried by a real
CLI `EditAuthorityPresentationError` retains the identical nested mapping, emits the
seven-field discriminator shape above, and exits `2` without printing `BLOCKED`;
projector and strict parser reject completed plus blockers; the historical generic
`LocalEntryError` branch remains unchanged; and the P0 focused authority suite passes.

#### 11.5.11 P0 follow-up implementation checkpoint

- Base HEAD remains `5f682659a826cdb4356b74b25f8fc35c19639cf4`; the follow-up is one
  four-file staged object with no tracked unstaged changes.
- `src/mod_agent/cli.py` catches `EditAuthorityPresentationError` before the generic
  `LocalEntryError` branch and emits only the seven contract fields. The integration
  regression invokes the real CLI and public Edit Authority entry, receives a frozen
  completed Graph result, injects the post-result audit failure, and proves
  `PRESENTATION_FAILED`/exit `2` preserves the identical nested machine mapping without
  printing `BLOCKED`. The generic error JSON remains exact and unchanged.
- `project_edit_authority_review_result()` rejects a derived completed result with any
  `platform_blockers`; strict `EditAuthorityReviewResultV1.from_dict()` rejects the same
  serialized tamper by replaying that projector.
- Exact focused command remains the §11.5.9 ten-file command and reports
  `470 passed in 92.16s`. The four changed Python files pass `py_compile`; both
  `git diff --check` and `git diff --cached --check` pass. No Build, Runtime, GTFO,
  product Store, Graph, materializer, ArtifactStore/C5, public result schema, or P1-P4
  action occurred.
- Staged identity: 4 files, `271 insertions / 0 deletions`; normal binary diff=
  `11526 bytes`, SHA256
  `47F2EA105CC04974BAC7C220C9537315DCE65E5DC6E40ECED3A7525E5BDC7CE0`;
  `--full-index` binary diff=`11790 bytes`, SHA256
  `51ECF1DF7F6ECDB8712E340A0B61DAA80C2A8BDB277776701E8F90AC0A7E8075`.
- The pre-verification status for the staged object was
  `implemented_pending_independent_verification`; commit remained forbidden until the
  independent post-implementation verdict became `approved`.

- Final follow-up checkpoint: independent verification returned
  `post_implementation_verdict=approved` with empty execution, authority, and
  compatibility blocker sets. The unchanged four-file staged identity above was
  committed as `9527d4046f13833a44237a8159d3d1062540f1ce`
  (`Preserve Edit Authority truth on presentation failure`). P0 is now
  `independently_verified_and_committed`; this does not start or complete P1-P4.

## 12. C6 — Driver 权限与降级

### 12.1 driver 允许做什么

feature driver 只能：

- 读取 feature-specific config 和 exact inputs；
- 准备 public entry 接受的参数；
- 调用 public entry；
- 在已批准范围内等待 operator input；
- 收集 public structured result；
- 生成 Presentation。

### 12.2 driver 交还公共层的职责

随着公共入口具备等价能力，feature driver 将以下职责迁回公共层：

- 定义或扩大 Approval 语义；
- 维护 supported-schema allowlist；
- 选择未注册 Graph route；
- 对 public route 拥有的 workflow result 直接 `ArtifactStore.write()`；
- 定义另一套 freshness policy；
- 定义 retry/replay/recovery policy；
- 解释 revision 与 latest alias；
- 独立判断 Store commit；
- 生成最终 terminal verdict；
- 把 Presentation 纳入 Approval Identity hash；
- 单独实现平台级 invariant。

### 12.3 现有 driver 处理规则

- 已执行并被正式引用：作为历史审计证据保留，后续能力通过公共入口演进。
- 包含真实公共缺陷修复：把逻辑与 regression test 迁入权威公共层。
- 只包含 feature semantics：保留或提取为 feature adapter。
- 未执行、无正式引用、已被 public entry 覆盖：在 parity test 和明确迁移授权后删除。
- 包含重复 Store validator：公共 result contract 生效后删除重复解释。

driver 的实际处理由推进页结合引用关系、公共 parity、维护成本和产品推进需求自行规划；
“保留、委托、变薄、迁移、删除”都是可用结果，关键是最终只保留一个 semantic authority。

### 12.4 C6 工作包 1 实施合同表：verification-only Build 公共 continuation

| 合同项 | 推进页决策 | 审核页复核 | 实施与验收回填 |
| --- | --- | --- | --- |
| semantic goal | 让“已有 fresh FeatureSpec + EvidencePack、无需源码 mutation、需要一次 Build 并形成 Build→Runtime handoff”的路径具备稳定公共执行入口。该入口拥有 admission→单一 StateGraph→一次 Build adapter 调用→BuildResult/WorkflowCheckpoint Store outcome→resume preflight→structured terminal result；历史 run-local driver 不再拥有 Store commit、retry/recovery 或 terminal verdict。 | `pending` | `pending` |
| bounded owner inventory | `src/mod_agent/workflow/verification_only.py::preflight_verification_only_continuation` 已拥有 fresh-lineage admission；`src/mod_agent/workflow/graph.py::build_graph/_run_build` 已拥有 verification-only route、Graph-before-factory、BuildResult 领域校验和 checkpoint 触发；`src/mod_agent/workflow/checkpointing.py::WorkflowCheckpointStore` 已拥有 checkpoint payload/resume validation；`src/mod_agent/artifacts/store.py::ArtifactStore.write_with_result` 已拥有单次 Store outcome。缺失的是稳定 local public Build entry，以及 BuildResult/checkpoint 的 `ArtifactWriteResult` 无损返回。`workspaces/stagger_verification_only_build_001/run_build.py::_materialize` 当前仍组装 Graph、解释 Store revision/pending、决定 retry/recovery和 terminal status。 | `pending` | `pending` |
| driver inventory | 已执行并被正式 BuildResult/checkpoint lineage 引用的历史 driver：`workspaces/stagger_verification_only_build_001/run_build.py`。其中 feature-specific 部分是 exact source/dependency snapshot、run-local workspace、NuGet profile、Build adapter 与授权包 Presentation；平台重复部分是 Graph invocation、Store totals/pending推断、checkpoint read-back、retry/recovery和最终 verdict。authority、Runtime、C4/C6/C7 observation drivers 本包 unchanged。 | `pending` | `pending` |
| feature semantics retained | caller/adapter 继续提供 exact `VerificationOnlyContinuationInput`、`run_id`、`request_id`、`user_request`、`target_domain`、`target_mod` 和一个显式 `BuildResultFactory`；该 factory 可准备 feature-specific isolated workspace、dependency snapshot、NuGet profile并返回现有 `BuildResult`。公共入口只在 Graph admission 通过后调用它，最多一次。授权包生成、外部人类 Build 批准和 Presentation 不被本包重新定义。 | `pending` | `pending` |
| platform semantics migrated | 公共层拥有：写前 verification-only admission；Graph-before-effect；Graph admission 通过后的 Store probe→caller factory 严格顺序；factory one-shot；BuildResult identity/lineage验证；BuildResult 与 checkpoint 的 C5 `ArtifactWriteResult`；成功 checkpoint 的 public resume preflight；零自动 retry/replay/recovery；分离 Build domain outcome、Store outcome 和 handoff readiness。`ArtifactWriteResult.to_dict()` 只进入返回的 machine result，不进入 BuildResult 或 WorkflowCheckpoint payload/content hash。 | `pending` | `pending` |
| target public entry | 在 `src/mod_agent/local_entry.py` 增加 `preflight_verification_only_build_continuation(...) -> dict[str, Any]` 与 `execute_verification_only_build_continuation(...) -> dict[str, Any]`。两者接受同一 exact Artifact refs/运行身份；execute 额外接受显式 `build_result_factory` 与 `allow_build_execution=True`。public preflight 只调用零写入的 `preflight_verification_only_continuation`，绝不调用 `preflight_atomic_commit`、不创建probe、不调用factory。execute 只构建现有 verification-only `StateGraph`，`stop_after_build=True`、`persist_build_runtime_handoff=True`。Graph进入verification-only build node后，公共one-shot wrapper先调用`ArtifactStore.preflight_atomic_commit(feature_id, ("build_result", "workflow_checkpoint"))`；probe成功后才把caller factory invocation count从0改为1并调用factory。probe失败时caller factory count保持0。不新增 Graph branch、Controller、Artifact 或 Approval 类型。 | `pending` | `pending` |
| public structured result | execute 返回固定分层：`status=completed|blocked|partial`；`failure_stage=null|authorization|admission|store_preflight|build_execution|post_build_validation|build_result_store|handoff_eligibility|checkpoint_prewrite|checkpoint_store|checkpoint_resume_preflight`；exact `feature_id/run_id/request_id`；`verification_only_preflight`；`build_execution`（caller factory invocation count、side effects may have started、domain status/claims）；nullable `build_result`（immutable ref、payload status、nullable `store_result`）；nullable `workflow_checkpoint`（immutable ref、nullable `store_result`、nullable resume preflight）；`handoff_ready`；`blockers`；`automatic_retry_count=0`；`recovery_performed=false`。Store committed 不证明 Build success；Build success 不证明 checkpoint committed或resume allowed。 | `pending` | `pending` |
| deterministic outcome matrix | `allow_build_execution=false`→`blocked/authorization`，factory=0、两类对象均null、handoff=false；verification admission失败→`blocked/admission`，factory=0、两类对象均null；Store probe失败→`blocked/store_preflight`，factory=0、两类对象均null且不得伪造Store result；caller factory抛异常→`blocked/build_execution`，factory=1、`side_effects_may_have_started=true`、两类对象均null；factory返回后source/identity/BuildResult验证失败→`blocked/post_build_validation`，factory=1、无Store result/ref；BuildResult `blocked_before_commit`→`blocked/build_result_store`，build_result容器含payload status与该Store result但ref=null，checkpoint=null；BuildResult `partial`→`partial/build_result_store`，形状同前；BuildResult committed且domain status=`failed`→`completed/null`，build_result含ref/result，checkpoint=null，handoff=false；BuildResult committed且domain status=`success`但`claims_real_build_success!=true`→`blocked/handoff_eligibility`，build_result含ref/result，checkpoint=null；checkpoint payload/prewrite验证抛异常→`blocked/checkpoint_prewrite`，已committed BuildResult保留，checkpoint=null且无checkpoint Store result；checkpoint `blocked_before_commit`→`blocked/checkpoint_store`，checkpoint容器ref=null且含Store result；checkpoint `partial`→`partial/checkpoint_store`，形状同前；checkpoint committed但resume preflight不允许→`blocked/checkpoint_resume_preflight`，两ref/result均保留，handoff=false；两次Store均committed且resume allowed→`completed/null`，两ref/result均保留，handoff=true。除factory抛异常只能保守记为side effects may have started外，其余有factory调用的行也一律为true；前三行false。所有行retry/recovery均为0/false。 | `pending` | `pending` |
| Graph/Checkpoint Store adoption | verification-only `_run_build` 使用 `write_with_result` 写 BuildResult；非 `committed` 时不创建 checkpoint，并将 exact Store result作为本次 Graph machine result。成功 BuildResult committed 后，`WorkflowCheckpointStore` 增加与现有 `create_checkpoint` 共用 payload/prewrite验证的 `create_checkpoint_with_result`；兼容 `create_checkpoint -> ArtifactRef` 仍走原 `write()`错误合同。checkpoint non-committed 不被 Graph/driver重解释。mutation Build路径继续使用现有 `write()`与返回/异常行为。 | `pending` | `pending` |
| ephemeral-result boundary | `_run_build` 先用不含 Store receipt 的 `build_summary` 创建 checkpoint，checkpoint 写入结束后才把两个 `ArtifactWriteResult.to_dict()` 加入返回 state；因此 machine receipt不会进入 checkpoint `state_snapshot`、Artifact content hash或 Approval Identity。public entry不得用 revision totals、pending扫描、locator equality或stdout覆盖这些结果。 | `pending` | `pending` |
| removed authority | 对未来受支持的 verification-only Build，driver不得直接调用 `build_graph`、`ArtifactStore.write`、`WorkflowCheckpointStore.create_checkpoint`，不得从 Store totals/pending/path推导commit或返回冲突 verdict；必须调用上述 public entry并展示其结果。现有正式引用 driver 不改字节、不删除，标记为 historical audit only。authority regression以“公共入口外层伪造 revision/pending统计不能改变 public result”和“factory不能被调用第二次”为证明。 | `pending` | `pending` |
| compatibility | 现有 `preflight_verification_only_continuation`、直接 `build_graph`测试入口、mutation Build、`WorkflowCheckpointStore.create_checkpoint`、Artifact payload/hash、历史 BuildResult/checkpoint/driver bytes保持可读。verification-only direct Graph新增 machine receipt字段但不改变成功 Artifact identity；Store blocked/partial从原始异常收敛为 Graph blocked state只限该现有 verification-only branch。Runtime public entry、产品 Criterion与正式产品 Store不变。 | `pending` | `pending` |
| implementation scope | 预计生产定位：`src/mod_agent/local_entry.py`、`src/mod_agent/workflow/graph.py`、`src/mod_agent/workflow/checkpointing.py`，必要时只更新`src/mod_agent/workflow/__init__.py`公开导出；focused tests：`tests/unit/test_verification_only_continuation.py`、`tests/unit/test_local_entry.py`、`tests/unit/test_repair_checkpoint_smoke.py`。`ArtifactStore` C5/C4实现原则上 unchanged。 | `pending` | `pending` |
| semantic boundary | may change：verification-only Build public API、该 Graph branch的Store failure返回方式、checkpoint result API、public machine-result schema。must remain unchanged：Build人类Approval family、Artifact/Registry/schema、Graph topology/route、mutation Build、Runtime/evidence执行、产品行为、source/dependency/BuildProfile语义、Artifact lineage/freshness、Store三态/recovery权限、历史bytes/hash。 | `pending` | `pending` |
| validation | 1) public preflight两次确定、零factory、且用spy证明未调用`preflight_atomic_commit`或任何Store writer；2) stale/wrong refs与`allow_build_execution=False`在factory/Store前拒绝；3) event-order回归精确证明Graph admission→`preflight_atomic_commit`→caller factory，probe失败时factory=0；4) factory恰好一次；5) 参数化锁定上述完整outcome matrix及所有nullable ref/result形状；6) Build失败写一份committed BuildResult、无checkpoint、public status completed且domain failed；7) BuildResult blocked/partial分别无checkpoint并保持C5结果；8) Build成功+checkpoint committed+resume allowed返回handoff ready；9) checkpoint prewrite/blocked/partial及committed但resume blocked均无retry/recovery且不被误报成功；10) Store receipt不进入checkpoint payload；11) mutation/direct Graph兼容；12) 一条真实临时Store public entry→Graph→Build adapter→BuildResult→checkpoint→resume-preflight集成。 | `pending` | `pending` |
| self-correction | private helper、fixture和错误文本可在不改变上述公共合同的前提下自主调整。若实施证明`ArtifactWriteResult`无法在不进入durable checkpoint的情况下穿过Graph，或需要改变Store/Graph topology/Artifact类型，停止并回到合同审核。 | `pending` | `pending` |
| unresolved_contract_decisions | `[]` | `pending` | `[]` |

#### 12.4.1 C6 工作包 1 提交前实施状态覆盖（2026-08-04）

> 本节覆盖 §12.4 表中本工作包的 `pending` 实施状态；合同文本本身不变。指定独立实施后验收已给出 `post_implementation_verdict=approved`，实现提交为 `7a6209a`。

- `src/mod_agent/local_entry.py` 已提供 `preflight_verification_only_build_continuation` 与 `execute_verification_only_build_continuation`。public preflight 只执行 verification admission；execute 由 Graph admission 后的 one-shot wrapper 按 `preflight_atomic_commit` → caller `BuildResultFactory` 顺序执行。
- `src/mod_agent/workflow/graph.py::_run_build` 的 verification-only 分支已消费 C5 `ArtifactWriteResult`，分别表达 BuildResult 与 WorkflowCheckpoint 的 committed、blocked-before-commit、partial；mutation Build 继续使用兼容 `write()`/`create_checkpoint()`。
- `src/mod_agent/workflow/checkpointing.py::WorkflowCheckpointStore.create_checkpoint_with_result` 与兼容 `create_checkpoint` 共用 checkpoint payload/prewrite 校验。非 Store 类型的 payload/prewrite 异常在该边界规范化为 `ArtifactStoreError`，不会由外层误报为 Build execution failure。
- verification-only Graph 的二次 admission 失败直接到 `END`，返回 `blocked/admission`；不再进入会写 `BlockedReport` 的通用 blocked 节点。BuildResult/checkpoint receipt 只在 checkpoint 构造后加入 ephemeral Graph result，不进入 durable checkpoint state、Artifact content hash或 Approval Identity。
- caller factory 返回后，payload serialization、fresh-lineage recheck 与 BuildResult validation 的返回型或异常型失败均在任何 Store write 前收敛为 `blocked/post_build_validation`；factory invocation count保持1，结果ref/receipt均为null。
- checkpoint 已 committed 后的 resume preflight 若返回blocked或抛异常，公共入口均返回 `blocked/checkpoint_resume_preflight` 并保留BuildResult/checkpoint两份ref与C5 receipt；异常型结果固定 `resume_preflight=null` 并附机器blocker，不自动retry/recover。
- 公共结构化结果已经按 §12.4 outcome matrix 固定 `completed|blocked|partial`、failure stage、nullable ref/result、handoff readiness、side-effects、retry=0、recovery=false；真实临时 Store partial、checkpoint prewrite、resume blocked 与 TOCTOU admission drift 均有回归。
- 历史 run-local driver 字节未修改；产品源码、正式 ArtifactStore、真实 Build/Runtime、Graph topology、Artifact/Approval 类型均未改变。C6 Runtime/evidence 公共 continuation 仍未实施。
- 提交前验证：`python -B -m pytest -q -p no:cacheprovider tests/unit/test_verification_only_continuation.py` → `34 passed`；C1–C6 联合 focused suite → `368 passed`；`git diff --check` 待最终 staged identity 一并复核。
- 当前状态：`implemented_and_independently_verified`；`commit=7a6209a`；`unresolved_contract_decisions=[]`。整体 C6 仍为 `partial`，Runtime/evidence 公共 continuation 尚未进入本工作包。

本工作包完成后 C6 仍为 `partial`。下一工作包才处理 verification-only Runtime/evidence
continuation 与现有 `preflight_local_runtime`/`resume_local_runtime` 的 Store result/terminal verdict迁移；
不得借本包提前修改GTFO、operator contract、产品Criterion或正式Runtime路径。

### 12.5 C6 工作包 2 实施合同表：initial verification-only RuntimeEvidence 公共 continuation

| 合同项 | 推进页决策 | 审核页复核 | 实施与验收回填 |
| --- | --- | --- | --- |
| semantic goal | 让一个已经具备 exact Build checkpoint、fresh FeatureSpec/BuildResult、外部Runtime授权和feature-specific Runtime effect factory 的 initial verification-only Runtime，在两个现有 public entry 中完成：零写入preflight → exact ResumeReport → 单一StateGraph runtime admission → Store probe → factory一次执行 → RuntimeEvidence C5 receipt → structured terminal result。该模式在 `collect_runtime_evidence` 后停止，不在本包生成BlockedReport、EvalReport或WorkflowSummary，也不宣称产品acceptance完成。 | `pending` | `pending` |
| bounded owner inventory | `preflight_local_runtime`与`_load_runtime_continuation_handoff`拥有checkpoint/Build/DLL/freshness/read-only admission；`WorkflowCheckpointStore`与`ResumeValidator`拥有ResumePayload决策和ResumeReport；Graph `_route_runtime_continuation_entry`拥有Build→Runtime入口；`_run_runtime_evidence`拥有factory调用、context binding、RuntimeEvidence写入和runtime_summary；`ArtifactStore.write_with_result`拥有Store三态。缺口是：initial verification-only driver仍直接resume、build_graph、统计revision/pending并解释终态；现有public resume仍用兼容`write()`、直接跑到blocked/eval/done、异常时抛出，并写run-local summary文件。 | `pending` | `pending` |
| supported operation | 复用 `preflight_local_runtime` 与 `resume_local_runtime`，新增显式 `runtime_evidence_only: bool=False` operation flag。该模式只支持initial continuation：必须提供exact `resume_id`、非空exact `approved_by`、`injected_runtime_admission`和`runtime_evidence_factory`；`recover_accepted_resume=false`、`retry_runtime_observation=false`。preflight返回稳定`runtime_execution_identity`及其hash；execute必须显式接收`expected_runtime_execution_identity_hash`并在ResumeReport前与当前输入重算值比较。默认false保持现有完整Runtime/observation-retry/recovery行为。不得新增第三个public entry、Graph branch、Artifact或Approval类型。 | `pending` | `pending` |
| manifest-free Build→Runtime handoff | `runtime_evidence_only=true`不得要求、生成或伪造`run_manifest.json`。handoff identity从exact immutable `WorkflowCheckpoint`及其`state_snapshot`无损重建：checkpoint的feature/run/request identity、`FeatureSpec`与`BuildResult` exact refs，以及BuildResult中已经验证的artifact path/SHA256/size/mtime；这些字段继续按既有freshness/lineage/DLL校验读取。`run_root`在此模式只承载feature-adapter的profile、output和文件系统边界，不充当Build lineage authority。默认`runtime_evidence_only=false`继续保留现有manifest合同。 | `pending` | `pending` |
| stable runtime execution identity | identity object固定为：`schema_version="verification_only_runtime_execution_identity_v1"`、`hash_domain="mod_agent.verification_only_runtime_execution_identity.v1"`、`checkpoint={artifact_type, artifact_hash, feature_id, checkpoint_id, run_id, request_id}`、exact `resume_id`、exact `approved_by`、完整canonical `runtime_admission`。`artifact_hash`使用immutable WorkflowCheckpoint完整逻辑hash；物理locator/path不进入identity。canonical serialization固定为UTF-8 JSON、`ensure_ascii=false`、对象key字典序、无额外空白；数组保持输入顺序；非JSON值拒绝。hash固定为`sha256:`加上述domain-separated canonical object的SHA-256小写hex。Store totals/pending、stdout、时间戳/耗时、run_root/output展示、Presentation、operator observation和执行后结果均排除。 | `pending` | `pending` |
| feature adapter boundary | driver/调用者继续拥有exact runtime profile、DLL/config destination、operator channel、output root、进程枚举及GTFO factory构造；factory必须在返回payload或抛异常前完成其既有终止/恢复合同。公共层只接受已由人类外部授权包绑定的callable和admission payload，不选择产品Criterion、不替用户观察、不解释黄色X/音频。历史已执行driver字节不改；未来同类initial verification-only Runtime必须调用本operation。 | `pending` | `pending` |
| public preflight | `preflight_local_runtime(..., runtime_evidence_only=True, resume_id=..., approved_by=..., injected_runtime_admission=...)`继续零Artifact/Store/probe/process/game-directory写入；要求exact non-empty `resume_id`、exact non-empty `approved_by`和initial模式，使用上述manifest-free checkpoint handoff，并复用现有freshness/DLL/profile检查。它用现有`ResumeValidator`对同一个exact checkpoint、`resume_id`、`approved_by`与Runtime admission构造完整no-write approve decision projection；不得跳过validator或填入虚构approver。成功结果返回上述完整`runtime_execution_identity`与`runtime_execution_identity_hash`。preflight不得调用`preflight_atomic_commit`或factory。invalid/blocked decision以现有preflight result中的明确blocker返回；输入shape/path编程错误保持现有`LocalEntryError`兼容边界。 | `pending` | `pending` |
| execute identity gate | `resume_local_runtime(..., runtime_evidence_only=True, expected_runtime_execution_identity_hash=...)`把该expected hash作为必填稳定输入。executor对当前exact checkpoint、`resume_id`、`approved_by`与canonical Runtime admission重新运行同一zero-write preflight、重建同一identity并在任何ResumeReport、Graph、Store probe或factory副作用前做常量语义的exact字符串比较；缺失、格式错误或不相等固定为`blocked/authorization`，ResumeReport/runtime factory/业务Store写均为0。public executor拥有该跨调用gate；外部授权包只负责保存并回传preflight给出的hash，不自行解释identity。 | `pending` | `pending` |
| ResumeReport result | `WorkflowCheckpointStore`增加与现有`resume`共用checkpoint读取、decision、ResumeReport payload与upstream的`resume_with_result`。新operation只使用`write_with_result`：non-committed时不得进入Graph/Runtime；只有committed且decision allowed才进入Graph，并在该Store实例中标记consumed。兼容`resume -> (decision, ArtifactRef)`保持现有异常合同。blocked decision可写一份committed blocked ResumeReport，但factory=0。 | `pending` | `pending` |
| Graph-before-effect | public executor用accepted ResumeReport恢复state并构建现有Graph，`runtime_continuation_checkpoint_id`保持exact，`interrupt_after=["collect_runtime_evidence"]`。Graph runtime entry通过后，one-shot wrapper先调用`preflight_atomic_commit(feature_id, ("runtime_evidence",))`，成功后才把caller factory invocation count从0改为1并调用factory；probe失败factory=0。Graph entry/freshness漂移不得启动Runtime。 | `pending` | `pending` |
| RuntimeEvidence Store result | `build_graph`只新增private execution option，把verification-only runtime-evidence-only invocation传给`_run_runtime_evidence`；该模式用`write_with_result`。non-committed不记录RuntimeEvidence ref并在state返回exact result；committed才记录immutable ref。receipt只在RuntimeEvidence payload/context binding完成后加入ephemeral runtime_summary；因为Graph立即interrupt，不进入Eval/WorkflowSummary或任何durable payload/hash。默认Graph路径继续使用兼容`write()`。 | `pending` | `pending` |
| public structured result | 新operation返回：`status=completed|blocked|partial`；`failure_stage=null|authorization|admission|resume_report_store|resume_admission|graph_admission|store_preflight|runtime_execution|post_runtime_validation|runtime_evidence_store`；exact feature/run/request/resume/checkpoint identity；`runtime_execution_identity`与`runtime_execution_identity_hash`；`runtime_preflight`；`runtime_execution`（factory invocation count、side effects may have started、domain verification/acceptance fields）；`resume_report`（nullable ref、nullable Store result、decision）；`runtime_evidence`（nullable ref、payload verification/acceptance status、nullable Store result）；`runtime_evidence_ready`；`blockers`；retry=0、recovery=false、presentation_written=false。Store committed、Runtime执行完成和产品acceptance三者不得互相替代。 | `pending` | `pending` |
| deterministic outcome matrix | public authorization/admission失败→`blocked/authorization|admission`，无ResumeReport、factory=0；ResumeReport blocked-before-commit→`blocked/resume_report_store`，partial→`partial/resume_report_store`，均factory=0；committed但decision blocked→`blocked/resume_admission`，保留report ref/result；Graph entry漂移→`blocked/graph_admission`，report committed、factory=0；Store probe失败→`blocked/store_preflight`，report committed、factory=0；factory抛异常→`blocked/runtime_execution`，factory=1、side effects may have started、RuntimeEvidence null；payload/context/freshness validator返回失败或抛异常→`blocked/post_runtime_validation`，factory=1、无RuntimeEvidence Store result；RuntimeEvidence blocked-before-commit→`blocked/runtime_evidence_store`，partial→`partial/runtime_evidence_store`；RuntimeEvidence committed→`completed/null`且`runtime_evidence_ready=true`，无论产品acceptance true/false/inconclusive。所有行自动retry=0、recovery=false。 | `pending` | `pending` |
| presentation/output boundary | 新operation不写`runtime_resume_result.json`，只返回structured machine result；driver可在返回后生成Presentation。默认legacy模式继续按现有行为写该文件，兼容测试不变。Store totals、pending扫描、locator/path equality、stdout和run-local文件写失败不得覆盖public C5 result。 | `pending` | `pending` |
| compatibility | 默认`runtime_evidence_only=false`的preflight/resume签名行为、observation retry、accepted resume recovery、GTFO factory、operator contract、完整Graph terminal链和run-local summary保持；direct Graph和mutation Runtime保持；历史Artifact/driver可读。may change仅为新增operation、`resume_with_result`兼容API、该模式的RuntimeEvidence C5 result与structured schema。 | `pending` | `pending` |
| validation | 1) 新preflight两次确定且identity/hash逐字一致，Store/factory/process零调用；2) exact Resume admission与错误identity/side-effect authorization写前fail-closed；3) audit snapshot/Presentation变化不改变identity hash；checkpoint artifact hash/identity、`approved_by`、`resume_id`或canonical runtime admission任一变化均改变hash；4) execute缺失/错误expected hash或任一preflight→execute输入漂移均在ResumeReport/Graph/Store前拒绝且全业务revision/pending增量为0；5) C6工作包1 public Build返回的exact checkpoint/BuildResult在Build run没有`run_manifest.json`时可直接进入本public preflight/resume，且没有生成manifest；6) ResumeReport blocked/partial/decision-blocked矩阵；7) event order精确为ResumeReport committed→Graph admission→Store probe→factory once；8) Graph drift/probe失败factory=0；9) factory exception与post-runtime validation返回/异常；10) RuntimeEvidence blocked/partial/committed三态；11) committed acceptance false仍是platform completed但产品未通过；12) receipts不进入RuntimeEvidence payload；13)不产生BlockedReport/Eval/WorkflowSummary和run-local summary；14)现有manifest-based full/retry/recovery/direct Graph兼容；15)真实临时Store public Build→manifest-free public Runtime preflight/resume→ResumeReport→Graph→RuntimeEvidence integration，driver统计不能覆盖结果。 | `pending` | `pending` |
| deferred to later C6 package | verification-only RuntimeEvidence之后的BlockedReport/EvalReport/WorkflowSummary C5 receipt与terminal continuation；C4 implementation-evidence consolidation public path；产品Criterion/人工观察解释；历史driver删除或改写；第二产品切片。 | `pending` | `pending` |
| unresolved_contract_decisions | `[]` | `pending` | `[]` |

#### 12.5.1 C6 工作包 2 提交前实施状态覆盖（2026-08-04）

> 本节覆盖 §12.5 表中本工作包的 `pending` 实施状态；合同文本本身不变。实施前独立合同审核与实施后独立验收均已给出 `approved`，实现提交为 `23c35ac4b9888b170f7e5cab01faa59f5a5eb09b`；不能据此宣称整个 C6 已完成。

- `src/mod_agent/local_entry.py` 的既有 `preflight_local_runtime` 与 `resume_local_runtime` 已支持显式 `runtime_evidence_only=True`。该模式从 exact immutable WorkflowCheckpoint/state snapshot 和 fresh BuildResult 重建 manifest-free handoff，不要求、生成或伪造 `run_manifest.json`；默认 manifest/full/retry/recovery 路径保持原行为。
- `_verification_only_runtime_execution_identity` 已固定 domain-separated canonical identity；preflight 返回 identity/hash，execute 必须显式接收 `expected_runtime_execution_identity_hash`，重新运行同一零写入 preflight，并在 ResumeReport、Graph、Store probe 和 factory 前做 exact comparison。缺失、格式错误、action identity 漂移均返回 `blocked/authorization`。
- runtime-only preflight 始终调用现有 `ResumeValidator`，并把 checkpoint freshness、lineage、consumption readiness 与 exact resume payload 决策的 blocker 合并；blocked readiness 不会跳过 validator，也不把状态硬编码为 fresh/unconsumed。
- `WorkflowCheckpointStore.resume_with_result` 与兼容 `resume` 共用 checkpoint读取、decision、ResumeReport payload/upstream 生成。只有 ResumeReport Store outcome 为 committed 且 decision allowed 时才在当前 Store 实例中标记 checkpoint consumed；non-committed结果不进入Graph/Runtime。
- public executor 在 identity gate 后再次回读 handoff；该阶段的 identity/freshness drift 被收敛为 `blocked/admission`，不会越过 structured result。随后执行顺序固定为 ResumeReport committed → Graph runtime admission → `preflight_atomic_commit` → caller factory一次。
- `src/mod_agent/workflow/graph.py::_run_runtime_evidence` 的私有 result mode 在 factory 返回后完成 Build输出、context、schema、identity、Registry和freshness验证，再使用C5 `write_with_result`写RuntimeEvidence；blocked-before-commit、partial、committed分别保留精确nullable ref/result形状。默认direct Graph路径继续使用兼容`write()`。
- Store probe、caller factory和post-effect Build输出验证分别由public effect wrapper转换为平台拥有的typed failure；Graph按typed stage而不是caller异常类名解释failure stage。caller即使抛出与历史平台异常同名的类型，也固定归类为`runtime_execution`。
- Resume payload/write/decision在公共structured boundary内执行；写前异常返回`blocked/resume_admission`且report/result为null。ResumeReport committed后的state reconstruction异常同样返回`blocked/resume_admission`，但保留exact report ref与C5 committed result。缺失factory固定为structured `blocked/admission`，不再逃逸为`LocalEntryError`。
- Graph在`collect_runtime_evidence`后interrupt；Store receipt只存在于ephemeral `runtime_summary`，不进入RuntimeEvidence payload/content hash，不生成BlockedReport、EvalReport、WorkflowSummary或run-local `runtime_resume_result.json`。RuntimeEvidence committed表示平台工作包完成，不自动表示产品acceptance通过。
- factory、Store probe、payload/context/validator异常均按§12.5 outcome matrix收敛为唯一failure stage；retry=0、recovery=false。历史已执行driver字节未修改，产品源码、正式ArtifactStore、真实Build/Runtime、GTFO和游戏目录均未触碰。
- 提交前验证：`python -m pytest -q -p no:cacheprovider --disable-warnings --maxfail=1 tests/unit/test_edit_authority_capabilities.py tests/unit/test_stagger_edit_authority.py tests/unit/test_artifact_store.py tests/unit/test_artifact_contract.py tests/unit/test_workflow_graph.py tests/unit/test_repair_checkpoint_smoke.py tests/unit/test_local_entry.py tests/unit/test_verification_only_continuation.py` → `382 passed in 73.92s`；其中C6.2单文件 → `55 passed in 14.37s`；四个改动文件 `python -B -m py_compile` 通过；`git diff --check` 通过。
- 当前状态：`implemented_and_independently_verified`；`commit=23c35ac4b9888b170f7e5cab01faa59f5a5eb09b`；`unresolved_contract_decisions=[]`。整体 C6 仍为 `partial`；RuntimeEvidence之后的terminal/evaluation continuation、driver最终降级和第二产品切片仍属于后续工作包。

### 12.6 C6 工作包 3 实施合同表：committed RuntimeEvidence 的公共 terminal continuation

| 合同项 | 推进页决策 | 审核页复核 | 实施与验收回填 |
| --- | --- | --- | --- |
| semantic goal | 对一份已经 committed 的 verification-only RuntimeEvidence，在不重放 ResumeReport、Runtime factory、进程或游戏目录副作用的前提下，使用原 exact WorkflowCheckpoint、accepted ResumeReport 与 RuntimeEvidence 重建 post-Runtime state，并从同一 StateGraph 的现有 `route_after_runtime_evidence → blocked | evaluate → blocked | done` 完成 deterministic terminalization。BlockedReport、EvalReport、WorkflowSummary 的每次写入返回 C5 receipt；public result不再由driver通过revision delta、pending或文件存在性解释terminal verdict。 | `pending` | `pending` |
| bounded owner inventory | `WorkflowCheckpointStore`拥有checkpoint/accepted ResumeReport读取与恢复语义；RuntimeEvidence immutable envelope拥有BuildResult+FeatureSpec exact lineage；`route_after_runtime_evidence`与`route_after_evaluate`拥有terminal route；`_run_fake_evaluate`、`_run_workflow_summary`、`StubNodeRunner`分别拥有EvalReport、WorkflowSummary、BlockedReport payload；`ArtifactStore.write_with_result`拥有commit三态。旧default `resume_local_runtime`从Build checkpoint重跑Runtime并由local entry/driver投影`runtime_verification_chain`、写`runtime_resume_result.json`，不能用于post-Runtime terminalization。 | `pending` | `pending` |
| supported operation | 复用现有 `preflight_local_runtime` 与 `resume_local_runtime`，新增显式 `runtime_terminalization_only: bool=False`。该模式与`runtime_evidence_only`、accepted-resume recovery、observation retry互斥；必须提供exact `resume_id`、`approved_by`、`accepted_resume_report_path/hash`、`runtime_evidence_path/hash`。必须满足`allow_game_launch=false`、`allow_game_directory_write=false`、`runtime_plugin_destination=null`、`runtime_evidence_factory=null`。默认false及C6.2 evidence-only operation保持。不得新增第三个public entry、Artifact/Approval类型或业务Graph node。 | `pending` | `pending` |
| stable terminal identity | preflight返回`runtime_terminal_execution_identity`与hash。identity固定为：`schema_version="verification_only_runtime_terminal_identity_v1"`、`hash_domain="mod_agent.verification_only_runtime_terminal_identity.v1"`、exact immutable checkpoint/resume_report/runtime_evidence三组 `{artifact_type,artifact_hash,feature_id}` 及 checkpoint_id/run_id/request_id/resume_id/approved_by、`terminal_result_scope={allowed_artifact_types:[blocked_report,eval_report,workflow_summary],automatic_retry_count:0,recovery_allowed:false}`。canonical JSON/hash规则与C6.2相同；物理path/locator、run_root、Store totals/pending、stdout、timestamp、Presentation与产品观察排除。execute必须接收`expected_runtime_terminal_identity_hash`并在Graph/Store前重算比较。 | `pending` | `pending` |
| no-write preflight admission | `runtime_terminalization_only=true`不调用Store writer/probe、Graph或factory。它回读exact immutable checkpoint、accepted ResumeReport和RuntimeEvidence：ResumeReport必须accepted/allowed、exact upstream为checkpoint、restored_state等于checkpoint snapshot且resume/run/request/feature/approved_by一致；RuntimeEvidence必须fresh、同feature/run、exact BuildResult/FeatureSpec upstream及payload Build identity与checkpoint一致。preflight明确验证当前exact RuntimeEvidence尚无已开始的terminal chain，并返回稳定identity/hash；任何不一致为blocker。 | `pending` | `pending` |
| replay/partial-attempt boundary | terminal chain identity以exact RuntimeEvidence为根。若已有EvalReport envelope direct-upstream该RuntimeEvidence，或BlockedReport envelope direct-upstream该RuntimeEvidence/由其EvalReport，或WorkflowSummary经EvalReport追溯到它，则不再写入；preflight返回`terminalization_already_started`及现有exact refs。不得自动补写、retry、recover或以latest替换。先前partial/blocked Store结果需要未来独立恢复决定，不在本包处理。 | `pending` | `pending` |
| state reconstruction | public executor从accepted ResumeReport的冻结`restored_state`重建state，重新注入exact checkpoint、ResumeReport、RuntimeEvidence refs；`runtime_summary`仅由durable RuntimeEvidence payload的既有字段重建，不复制C6.2 ephemeral `runtime_evidence_store_result`。因此后续WorkflowSummary的durable payload/hash不会吸收receipt、locator或audit snapshot。 | `pending` | `pending` |
| Graph admission/route | 同一`build_graph`新增一个private typed post-Runtime entry binding，精确绑定上述三份immutable refs并在START route任何Store写前重验state、lineage、freshness与terminal replay gate；随后直接调用现有`route_after_runtime_evidence`，不进入`collect_runtime_evidence`、repair、Runtime factory或新业务node。现有route函数和`blocked|evaluate|done`拓扑语义不变；direct caller提供错误state/ref时写前fail-closed。 | `pending` | `pending` |
| C5 terminal Store results | 仅该private operation使`_run_fake_evaluate`、`_run_workflow_summary`和`StubNodeRunner`使用`write_with_result`。non-committed不记录Artifact ref；committed才记录exact immutable ref。每份receipt仅加入ephemeral machine summary/public result，不进入任何Artifact payload/hash。default Graph继续使用兼容`write()`。由于本操作没有昂贵effect，不调用`preflight_atomic_commit`；第一个Store副作用就是Graph admission之后的目标Artifact `write_with_result`。 | `pending` | `pending` |
| BlockedReport durable lineage | terminal operation写BlockedReport时，envelope `inputs.upstream_artifacts`必须包含触发route的exact immutable source：RuntimeEvidence未验证时绑定RuntimeEvidence；Eval gate blocked时绑定EvalReport。payload中的`upstream_artifacts`仍保留现有展示，但不能替代envelope lineage。历史BlockedReport读取保持，不修改Registry schema或旧bytes。 | `pending` | `pending` |
| structured public result | 返回platform `status=completed|blocked|partial`、`failure_stage=null|authorization|terminal_admission|graph_terminal_admission|eval_report_execution|eval_report_store|blocked_report_execution|blocked_report_store|workflow_summary_execution|workflow_summary_store`；exact identity/hash；checkpoint/resume/RuntimeEvidence输入refs；nullable BlockedReport/EvalReport/WorkflowSummary ref与C5 result；`terminal_route`、`terminal_ready`；domain `final_status=accepted|blocked|inconclusive|null`、acceptance claims；retry=0、recovery=false、presentation_written=false。Store committed、terminal chain完成和产品acceptance严格分离。 | `pending` | `pending` |
| deterministic outcome matrix | admission/identity/replay失败→`blocked/authorization|terminal_admission`，业务Store零写；Graph START drift→`blocked/graph_terminal_admission`；RuntimeEvidence未验证→BlockedReport，committed后platform=`completed`且domain=`blocked`；RuntimeEvidence已验证→EvalReport，non-committed分别`blocked|partial/eval_report_store`且无下游；Eval committed且gate blocked→BlockedReport；Eval committed且route done→WorkflowSummary；第二写non-committed保留Eval ref/result并返回对应`blocked|partial`；payload/lineage构造异常在所属node写前返回`*_execution`并保留已经committed的前序refs/results；全部所需terminal Artifact committed才`completed`。 | `pending` | `pending` |
| compatibility | C6.2 evidence-only identity、返回schema、RuntimeEvidence bytes/hash及interrupt-after行为不变；默认manifest/full Runtime、recovery/retry、mutation/repair routes、现有Eval/summary/blocked payload语义和`runtime_resume_result.json`行为不变；Artifact Registry/Store/checkpoint合同及历史Artifact/driver可读。may change仅为新operation、private typed Graph post-Runtime entry、三个terminal node的可选C5 result mode和BlockedReport新写exact envelope upstream。 | `pending` | `pending` |
| validation | 1) preflight两次确定、Store/Graph/factory零调用；2) identity audit字段变化hash不变，checkpoint/report/RuntimeEvidence/action scope变化hash改变；3) wrong/stale/path-hash-lineage/accepted-report/replay输入在Graph/Store前拒绝；4) C6.2 stop-after-RuntimeEvidence回归不变；5) exact committed unverified RuntimeEvidence→BlockedReport committed，platform completed/domain blocked；6) verified→EvalReport→WorkflowSummary committed；7) Eval gate blocked→EvalReport→BlockedReport；8) 三类terminal write的blocked-before-commit/partial矩阵、nullable refs及前序receipt保留；9) 三类payload/validation异常的structured failure；10) receipts/audit不进入durable payload/hash；11) BlockedReport exact envelope upstream及immutable admission；12) no ResumeReport/RuntimeEvidence新增、factory/process/probe/manifest/run-local summary调用；13) default direct Graph/full Runtime兼容；14) 一条真实临时Store public Build→C6.2 RuntimeEvidence→post-Runtime public terminalization集成，旧driver统计不能覆盖result。 | `pending` | `pending` |
| deferred to later C6 package | C4 implementation-evidence consolidation的public materialization adapter；历史driver改为薄参数/Presentation adapter及未执行driver清理；产品Criterion/人工观察解释；第二产品切片。 | `pending` | `pending` |
| unresolved_contract_decisions | `[]` | `pending` | `[]` |

#### 12.6.1 C6 工作包 3 实施状态覆盖（2026-08-04）

> 本节覆盖 §12.6 表中本工作包的 `pending` 实施状态；实际实现已经由指定 Fresh-Lineage 审核页独立验收，当前状态为 `implemented_and_independently_verified`。本结论只覆盖 committed RuntimeEvidence 的公共 terminal continuation，不得解释为整个 C6 或 CONTROL_PLANE_CONSOLIDATION 已完成。

- `src/mod_agent/local_entry.py` 的既有 `preflight_local_runtime` 与 `resume_local_runtime` 已支持显式 `runtime_terminalization_only=True`。该 operation 只接受 exact immutable WorkflowCheckpoint、accepted ResumeReport、committed RuntimeEvidence 及 exact `resume_id`/`approved_by`；三个Artifact path均必须是immutable revision locator，latest alias写前拒绝。它与 C6.2 RuntimeEvidence-only、recovery、retry、Runtime factory、process launch、`runtime_plugin_destination` 和 game-directory write 互斥，preflight与execute执行同一Store-only scope gate。
- `_verification_only_runtime_terminal_identity` 固定 `verification_only_runtime_terminal_identity_v1` / `mod_agent.verification_only_runtime_terminal_identity.v1` 的 domain-separated canonical identity。物理 locator、run root、Store totals、pending、stdout、时间戳、Presentation和产品观察不进入 hash；execute 必须在 Graph/Store 前回读并比较 `expected_runtime_terminal_identity_hash`。
- `WorkflowCheckpointStore.preflight_runtime_terminal_continuation` 回读并验证 checkpoint、accepted ResumeReport 和 RuntimeEvidence 的 exact identity、restored state、freshness与BuildResult/FeatureSpec lineage；terminal-only admission 验证不可变 BuildResult 中已记录的verified output binding，但不在RuntimeEvidence已经committed后重新要求隔离Build DLL当前仍存在。C6.2 initial Runtime与默认Runtime continuation继续执行当前物理DLL hash/size/mtime检查。`_runtime_terminal_artifact_refs` 对 exact RuntimeEvidence 根扫描已有 EvalReport、BlockedReport和WorkflowSummary，已开始的 terminal chain 在写前 fail-closed，不自动补写、retry或recover。
- `VerificationOnlyRuntimeTerminalInput` 是同一 StateGraph 的 private typed START binding。`_route_runtime_terminal_continuation_entry` 在首个 Store 写前重新验证 exact state/ref/lineage/freshness/replay，然后直接复用现有 `route_after_runtime_evidence`；未增加业务 Graph node，也不进入 `collect_runtime_evidence`、Runtime factory或repair route。
- `_run_fake_evaluate`、`_run_workflow_summary` 与 `StubNodeRunner` 仅在该 private operation 下使用 C5 `write_with_result`。non-committed不记录 Artifact ref；receipt只存在于 ephemeral `runtime_summary`/public result。WorkflowSummary 从 durable RuntimeEvidence 重建 clean runtime summary，不把 C6.2 或 C6.3 receipt写入payload/hash。默认 direct Graph继续使用兼容`write()`。
- terminal BlockedReport 的新 envelope upstream 精确绑定触发 route 的 immutable RuntimeEvidence（未验证路径）或 EvalReport（evaluation gate blocked路径）；payload中的展示副本不承担 durable lineage authority；随机TraceEvent `event_id`只保留为ephemeral trace，不进入terminal BlockedReport `trace_refs`或durable hash。
- public structured result分离 platform `completed|blocked|partial`、唯一 failure stage、三类 nullable ref/C5 result、terminal route/readiness与domain `accepted|blocked|inconclusive`。Store committed、terminal chain完成和产品acceptance不互相替代；retry=0、recovery=false、presentation_written=false。
- 新增受影响回归覆盖：两次确定性零写入preflight；identity audit排除与checkpoint/report/RuntimeEvidence/action字段绑定；错误exact report/evidence hash或alias path及Graph START drift写前拒绝；RuntimeEvidence提交后隔离DLL清理不阻断terminal-only而C6.2/default边界不放宽；unverified→BlockedReport、verified→EvalReport→WorkflowSummary、Eval gate blocked→EvalReport→BlockedReport；三条terminal chain replay写前拒绝；三类Store blocked-before-commit/partial，包括Eval已committed后的BlockedReport第二写失败与前序receipt保留；三类payload执行异常，包括Eval已committed后的BlockedReport构造异常；exact BlockedReport upstream且随机event id不进入durable trace/hash；receipt不进入durable summary；无第二份ResumeReport/RuntimeEvidence、无Store probe/factory/manifest/run-local summary；direct Graph错误state零写入。
- 当前本地验证：最终修正专项 `python -m pytest -q -p no:cacheprovider --disable-warnings --maxfail=1 tests/unit/test_verification_only_continuation.py -k "runtime_terminal or runtime_evidence_only"` → `43 passed, 42 deselected in 23.79s`；C6.3文件级早期回归 `test_verification_only_continuation.py test_mod_agent_state.py` → `86 passed in 35.13s`；最终C1–C6联合 `test_edit_authority_capabilities.py test_stagger_edit_authority.py test_artifact_store.py test_artifact_contract.py test_workflow_graph.py test_repair_checkpoint_smoke.py test_local_entry.py test_verification_only_continuation.py test_mod_agent_state.py` → `415 passed in 90.06s`。最终改动文件 `python -B -m py_compile` 与 `git diff --check` 在提交前重新核对。
- 当前状态：`implemented_and_independently_verified`；`commit=18d1849`；`unresolved_contract_decisions=[]`。整体 C6 仍为 `partial`；driver最终降级、C4 implementation-evidence public adapter、第二产品切片与后置 Authority 文档归并均未触发。

### 12.7 C6 工作包 4 首次实施合同（已被 12.7.2 恢复合同整体替代）

> 状态：`historical_rejected_implementation_contract`。本节及 12.7.1 记录第一次
> 实施和 `changes_required` 验收的历史，不再授权实现。尤其是
> `runtime_evidence_consolidation_only`、workflow 模块内自建 identity/hash、Registry/Store
> 分别解释 consolidation 语义、以及 commit 后由外围 semantic validator 改写公共终态，
> 均被 12.7.2 明确撤回。当前唯一可实施合同从 12.7.2 开始。

| 合同项 | 推进页决策 | 审核页复核 | 实施与验收回填 |
| --- | --- | --- | --- |
| semantic goal | 为“已有 exact Build checkpoint、accepted ResumeReport 与 committed RuntimeEvidence；新的 deterministic implementation evidence 只提升一个 Criterion、但不执行新 Build/Runtime”的真实 C4 consolidation 提供公共 continuation。公共层拥有零写入admission、稳定action identity、同一StateGraph既有`collect_runtime_evidence`节点、单次RuntimeEvidence C5 Store结果和structured result；feature adapter只提供versioned Criterion/evidence delta与exact file bindings，公共层按已注册builder确定性生成待写payload。本包不解释为新Runtime或产品acceptance。 | `pending` | `pending` |
| bounded owner inventory | 历史已执行driver `workspaces/stagger_c4_evidence_consolidation_001/project_c4_evidence_consolidation.py` 的 `NoWriteGraphProjectionStore`自行模拟Store envelope/hash；`accepted_resume_state`自行解释checkpoint/ResumeReport；`execute_graph_once`直接`build_graph`；`materialize`自行解释revision delta、pending、latest alias、changed path和terminal verdict。正式公共owner已存在于`WorkflowCheckpointStore`、Graph `_run_runtime_evidence`、Registry/Store freshness与C5 `write_with_result`，但没有“prior RuntimeEvidence + implementation evidence、无Runtime effect”的public adapter。bounded observation authority的preflight/resume/Graph route已由C1公共入口覆盖，保持unchanged；其三写materializer收缩属于下一独立工作包。 | `pending` | `pending` |
| historical boundary | 历史driver已物化RuntimeEvidence `dd7d08ece472a3a087a5200ec303346caa48735c6c0440a8f8b64334aea755a5`，并被后续Request/Evidence/Approval/Plan/checkpoint/resume lineage引用；driver与所有历史Artifact bytes/hash只读保留，不删除、不重放、不迁移。新公共operation只服务未来同义action，不把历史driver的projection hash、Store totals或locator解释为新authority。 | `pending` | `pending` |
| supported operation | 复用现有`preflight_local_runtime`与`resume_local_runtime`，新增显式`runtime_evidence_consolidation_only: bool=False`；不得新增第三个public entry、CLI路径、Artifact/Approval类型或业务Graph node。该模式与`runtime_evidence_only`、`runtime_terminalization_only`、recovery/retry、runtime factory、process/game-directory/plugin side effect互斥。输入复用exact checkpoint/report/prior RuntimeEvidence path+hash、`resume_id`、`approved_by`，并新增exact EvidencePack path+hash、versioned consolidation delta、envelope status=`blocked`和三项implementation-evidence file binding：`target_source`、`source_contract_report`、`source_contract_report_repeat`，每项为absolute path+SHA256。调用者不提交整份final RuntimeEvidence payload。 | `pending` | `pending` |
| versioned delta contract | 唯一受支持delta为`schema_version="verification_only_criterion_evidence_delta_v1"`、`feature_adapter="stagger_c4_implementation_evidence_v1"`。canonical delta精确包含：目标`criterion_id`与完整`acceptance_criterion`；`before={outcome:not_observed,evidence_strength:none}`；`after={outcome:true,evidence_strength:bound_implementation_evidence}`；排序后的EvidencePack `evidence_ids`；三项file role；`evidence_level=implementation`；`new_build_performed=false`、`new_runtime_performed=false`、`product_source_modified=false`。feature adapter拥有该delta到output payload的versioned deterministic builder；public entry只调用已注册builder，不接受caller callable或任意JSON patch。 | `pending` | `pending` |
| stable action identity | preflight返回`runtime_evidence_consolidation_identity`与hash；固定`schema_version="verification_only_runtime_evidence_consolidation_identity_v1"`、`hash_domain="mod_agent.verification_only_runtime_evidence_consolidation_identity.v1"`。identity绑定checkpoint/accepted report/prior RuntimeEvidence/FeatureSpec/BuildResult/EvidencePack的logical `{artifact_type,artifact_hash,feature_id}`、checkpoint_id/run_id/request_id/resume_id/approved_by、完整canonical versioned delta、status=`blocked`、三个file binding的role+normalized absolute path+SHA256、delta builder contract version，以及`action_scope={allowed_artifact_types:[runtime_evidence],attempt_budget:1,new_build:false,new_runtime:false,source_write:false,recovery:false}`。整份predecessor/final RuntimeEvidence payload hash、Artifact locator、Store totals/pending、stdout、timestamp、elapsed、Presentation、Runtime/Product Observation和执行后result均不作为新增action字段；exact predecessor Artifact hash已经选择了本次消费的不可变输入。execute必须显式接收expected identity hash并在Graph/Store前比较。 | `pending` | `pending` |
| no-write admission | preflight只读验证三个Artifact path均为exact immutable revision；checkpoint/report/prior RuntimeEvidence的accepted state、run/request/feature/build身份与freshness一致；prior RuntimeEvidence在action开始时是当前latest且尚无consolidation child；EvidencePack exact/fresh/latest；三份file当前bytes hash匹配；delta的criterion before状态与predecessor逐项一致。versioned builder从predecessor+delta+exact evidence bindings生成derived final payload，再由公共validator证明：除目标Criterion的outcome/evidence_strength/evidence_refs、确定性追加的一项evidence item/source、versioned message/evidence_source/limitations、prior/binding字段和平台binding外，所有字段逐字保持；其他Criterion不得变化。`acceptance_verified`、`claims_real_runtime_success`、`verification_status`、`acceptance_status`、`runtime_status`、overall acceptance、attempt completion、`real_runtime_performed`、startup/gameplay/operator/raw output/marker/acceptance contract等平台或产品claims必须与predecessor逐字相同，不能提升。derived payload须Registry-valid并保持同run/build/feature。preflight不得调用Graph、Store writer/probe或factory。无效输入返回/抛既有public admission错误且业务Store零增量。 | `pending` | `pending` |
| platform payload binding | 公共层在action identity确定后把完整canonical identity及其hash持久化到derived payload的`verification_only_evidence_consolidation`：`schema_version="verification_only_evidence_consolidation_v1"`、`action_identity`、`action_identity_hash`、exact predecessor RuntimeEvidence、exact EvidencePack、三份file binding、delta schema/adapter、`new_build_performed=false`、`new_runtime_performed=false`、`product_source_modified=false`。execute写前重建并逐字比较derived payload hash；Store committed后从immutable RuntimeEvidence envelope独立读取完整binding、重算action identity/hash并与public result比较。C5 receipt、locator、audit snapshot和整份Runtime/Product Observation不得进入action identity。 | `pending` | `pending` |
| durable lineage | 新RuntimeEvidence envelope upstream顺序固定为BuildResult、FeatureSpec、prior RuntimeEvidence、EvidencePack。BuildResult/FeatureSpec沿用当前RuntimeEvidence contract的latest/fresh admission；prior RuntimeEvidence与EvidencePack在action开始时必须latest/fresh，但写入envelope时以exact immutable ref、`require_latest=false`保存，避免新RuntimeEvidence成为latest后使其自身因predecessor alias前移而stale。payload中的platform binding必须与四个envelope upstream逐项一致。历史runtime envelope保持可读，不重写。 | `pending` | `pending` |
| Graph/state boundary | 使用private typed `VerificationOnlyRuntimeEvidenceConsolidationInput`作为同一StateGraph START binding；从accepted ResumeReport的frozen state恢复，注入exact prior RuntimeEvidence/EvidencePack与最终payload identity；首个Store写前再次验证state、lineage、files、identity和replay，然后直接进入既有`collect_runtime_evidence`并`interrupt_after=[collect_runtime_evidence]`。Graph不调用caller factory、Store probe、process或terminal/evaluate/repair node；`_run_runtime_evidence`仅在该mode消费prepared payload、additional exact upstreams和C5 `write_with_result`。 | `pending` | `pending` |
| replay/partial boundary | 以exact prior RuntimeEvidence为action root。若存在任何新RuntimeEvidence revision以该predecessor作为direct immutable upstream，则preflight返回already-started及exact refs，禁止补写。若只有相同output identity的pre-existing pending，公共executor不消费/恢复；C5 `write_with_result`原样返回partial。无自动retry、replay或recovery。 | `pending` | `pending` |
| structured public result | 返回platform `status=completed|blocked|partial`、`failure_stage=null|authorization|consolidation_admission|graph_consolidation_admission|post_consolidation_validation|runtime_evidence_store`；stable identity/hash；checkpoint/report/prior RuntimeEvidence/EvidencePack logical inputs；canonical delta hash与derived final payload hash；nullable new RuntimeEvidence ref与C5 result；domain字段原样说明目标Criterion变化及未改变的acceptance状态；`new_build_performed=false`、`new_runtime_performed=false`、`runtime_factory_invocation_count=0`、retry=0、recovery=false、presentation_written=false。Store committed只证明consolidated RuntimeEvidence写入，不证明产品accepted。 | `pending` | `pending` |
| deterministic outcome matrix | authorization/expected hash/side-effect scope失败→`blocked/authorization`；exact inputs/files/freshness/replay/payload失败→`blocked/consolidation_admission`；Graph START重验失败→`blocked/graph_consolidation_admission`；prepared payload/context/upstream validation异常→`blocked/post_consolidation_validation`且无Store result；RuntimeEvidence `blocked_before_commit`→`blocked/runtime_evidence_store`、ref=null；`partial`→`partial/runtime_evidence_store`、ref=null；`committed`→`completed/null`、ref/result保留。所有分支无ResumeReport新写、无下游terminal Artifact、factory=0、retry=0、recovery=false。 | `pending` | `pending` |
| removed driver authority | 新受支持consolidation不得由driver直接`build_graph`、模拟Store hash、调用private `_stable_hash`、检查revision totals/pending/latest alias/changed paths或生成public verdict；future adapter只能构造并本地语义验证versioned delta与file bindings，调用两个existing public entry，然后展示structured result。derived final payload由公共层按已注册builder生成和验证。历史已执行driver只保留audit价值，不修改字节。 | `pending` | `pending` |
| compatibility | C6.1 Build、C6.2 initial RuntimeEvidence、C6.3 terminalization、default full Runtime/recovery/retry/direct Graph、现有RuntimeEvidence payload与历史hash均保持。C4仍只提升implementation-level evidence；overall/acceptance保持inconclusive，C6/C7保持not_observed；不修改FeatureSpec、Criterion语义、产品源码、Build、Runtime、GTFO或游戏目录。bounded observation public path保持；其三写materializer、历史ID uniqueness与authority payload本包unchanged。 | `pending` | `pending` |
| validation | 1) 两次preflight确定且Graph/Store/factory零调用；2) audit/Presentation或predecessor中的非action观察展示不被重新展开进identity，任一exact Artifact、canonical delta、file hash/path、approver/action scope变化hash改变；3) alias/wrong/stale/unaccepted/replay/file drift在首写前拒绝且全业务revision/pending零增量；4) RuntimeEvidence committed后物理DLL删除不阻断；5) 任一额外Criterion改动、before不匹配、acceptance/runtime claim提升或未声明payload字段漂移均首写前零增量拒绝；6) platform binding的完整identity可从committed envelope独立重建并验证hash，且与四个exact envelope upstream逐项一致；predecessor/EvidencePack未来alias前移不使child stale；7) Graph START漂移零写；8) derived payload/context异常无Store result；9) C5 blocked-before-commit/partial/committed三态与nullable形状；10) receipt/audit不进入durable payload/hash；11)无新ResumeReport、factory、probe、Build/Runtime/terminal Artifact；12) replay覆盖committed child、revision已落盘partial和pending-only partial；13)历史`dd7d...`及其下游lineage仍可读；14)真实临时Store public Build→C6.2 RuntimeEvidence→implementation-evidence consolidation集成，外层伪造Store统计不能改变public result；15) bounded observation公共入口回归不变。 | `pending` | `pending` |
| unresolved_contract_decisions | `[]`。本包不决定bounded observation三写materializer收缩、driver文件删除、产品Criterion解释、第二产品切片或后置Authority文档归并。 | `pending` | `pending` |

#### 12.7.1 首次实施回填（独立验收 `changes_required`，未提交）

- 实施前独立审核：`approved`；审核基线文档
  `SHA256=2317C93AC537D2595D1B6DC6C30168185E18110B5C560E1F661A4EAD8E2DC298`。
- 当前实现状态：`changes_required_rework_in_progress`；已暂存首次实现与审核后未暂存
  修正不是同一审核对象，旧 normal/full-index diff hash 均失效，不得提交。
- 公共入口：既有 `preflight_local_runtime` / `resume_local_runtime` 新增互斥的
  `runtime_evidence_consolidation_only` operation；调用者只提交 exact protocol refs、
  versioned C4 delta 与三项 file binding，不提交 final RuntimeEvidence payload。
- authority owner：
  `src/mod_agent/workflow/runtime_evidence_consolidation.py` 冻结唯一 C4 delta、
  canonical action identity/hash、deterministic derived payload 与回读重建；
  `local_entry.py` 拥有零写入 preflight、expected-identity gate 和 structured result；
  `checkpointing.py` 拥有 checkpoint/accepted ResumeReport/prior RuntimeEvidence/replay
  admission；`graph.py` 在同一 StateGraph START 重验后只进入既有
  `collect_runtime_evidence`；`ArtifactStore.write_with_result` 拥有唯一 commit result。
- durable boundary：新 child envelope upstream 顺序固定为 BuildResult、FeatureSpec、
  prior RuntimeEvidence、EvidencePack；后两项以 immutable revision、
  `require_latest=false` 保存。Store 的 conditional admission 在 pending 前验证四角色、
  exact-revision set 及 payload/action identity binding；历史 RuntimeEvidence 没有新增
  required field，继续按原合同读取。
- failure/result boundary：expected identity、input/file/freshness/replay/Graph drift均在
  首写前阻断；C5 `blocked_before_commit|partial|committed` 原样进入 public result；
  commit 后 identity 回读异常保留 exact child ref 与 committed receipt，不由外围
  validator 改写为“未提交”。无新 ResumeReport、Store probe、factory、Build、Runtime、
  process、game-directory、terminal Artifact、retry 或 recovery。
- 当前 focused tests：
  `tests/unit/test_verification_only_continuation.py -k runtime_evidence_consolidation`
  → `11 passed, 85 deselected`；
  `test_artifact_store.py test_artifact_contract.py test_workflow_graph.py
  test_verification_only_continuation.py` → `301 passed in 122.38s`。
- 最终 C1–C6 联合回归：
  `test_edit_authority_capabilities.py test_stagger_edit_authority.py
  test_artifact_store.py test_artifact_contract.py test_workflow_graph.py
  test_repair_checkpoint_smoke.py test_local_entry.py
  test_verification_only_continuation.py test_mod_agent_state.py`
  → `426 passed in 128.49s`。
- 当前 `unresolved_contract_decisions=[]`。历史已执行 C4 driver 与 `dd7d...` Artifact
  保持只读；该实现尚未提交，最终 diff、联合 C1–C6 回归和独立验收仍待完成。

#### 12.7.2 C6 工作包 A 恢复实施合同：typed operation 与单一 consolidation semantic owner

本节是当前 C6.4 唯一实施合同，整体覆盖 12.7 与 12.7.1 的首次合同和实现回填。
正式状态为 `implemented_and_independently_verified`，commit=
`6f415d00e008af4a933b32529e82481ad81547ee`。工作包 A 只闭合 C6.4 semantic correctness；
C6.1–C6.3/default/retry/recovery 的内部 typed-family 迁移属于工作包 B。

##### 12.7.2.1 真实混合工作树与处置边界

- 基线 `HEAD=18d1849162ecba3df0ce9d22f9ab7f43ad144a0a`。当前相对 HEAD 的八个
  tracked 文件合计 `2768+/24-`：生产 `2029+/24-`、测试 `739+/0-`。其中首次
  实现八文件已 staged；`registry.py` 与
  `workflow/runtime_evidence_consolidation.py` 另有审核后 unstaged 修正。两层不是
  同一审核对象，首次实施的 normal/full-index diff hash 均失效。
- 不执行 reset、checkout、回滚 C6.1–C6.3 或删除历史 driver。实施时在当前文件上
  有选择地保留正确行为、删除未批准 authority，最后只形成一个新的 staged diff。
- 保留：predecessor + approved delta → derived payload 的确定性规则、C5
  `ArtifactWriteResult` 传递、四个 exact upstream 的 durable lineage、Graph-before-write、
  replay/file/tamper 的真实回归，以及 C6.1–C6.3 已验证兼容行为。
- 删除或降级：`runtime_evidence_consolidation_only` public/internal bool；C6.4 专用
  `VerificationOnlyRuntimeEvidenceConsolidationInput`；workflow 模块自建 canonical JSON/hash；
  Registry、Store、Graph、post-validator 各自保存的字段/hash/claim 子规则；commit 后能
  推翻 Store committed 的 semantic validator；workflow core 内 Stagger Criterion、Evidence
  IDs、report checks 与 file-role 常量；只锁定旧 bool/private helper 形状的重复测试。
- `local_entry.py`、`checkpointing.py`、`graph.py` 必须通过委托 typed operation 和公共
  handoff/result 骨架出现实质删减或 authority 减少，不再以新增一套 C6.4 分支解决问题。
  若新 helper 只增加 owner 而没有旧解释权退出，停止实施并重新审核。

##### 12.7.2.2 当前 bounded owner inventory

| 语义 | 当前首次实现中的 owner/重复解释 | 工作包 A 后唯一职责 |
| --- | --- | --- |
| operation 选择 | `preflight_local_runtime`、`resume_local_runtime`、Graph state 各自消费 `runtime_evidence_consolidation_only` | `src/mod_agent/verification_operations.py` 的 typed contract family 解析；public compatibility normalizer 不为尚未发布的 C6.4 提供 bool |
| Approval/Action Identity | `workflow/runtime_evidence_consolidation.py` 自建 `canonical_json`/`stable_hash`，而C2/C3历史实现的同类primitive仍在`edit_authority_capabilities.py` | 从C2/C3提取的`src/mod_agent/action_identity.py`中立 owner统一 canonical serialization、domain separation 和 hash；Edit Authority历史record与C6 operation都委托它，variant只声明action projection |
| C6.4 product semantic | workflow 模块、Registry、Store、Graph/post-validator分别保留部分规则 | `src/mod_agent/runtime_evidence_consolidation.py` 的纯确定性 contract owner + typed Stagger C4 adapter |
| Artifact semantic precommit | Store `_validate_upstream_refs` 硬编码四角色和部分 binding；Registry重算部分 hash | 顶层 `src/mod_agent/artifact_semantics.py` 提供中立只读 context 与平台固定 handler resolver；artifacts包只调用该中立接口，不导入workflow或feature模块；Registry只验 discriminator/version 已注册 |
| protocol/lineage | `checkpointing.py` 的 exact checkpoint/report/state/lineage/freshness admission | `WorkflowCheckpointStore` 只保留 protocol identity、lineage与freshness admission；same-successor/replay由canonical consolidation owner按trusted binding/adapter解释，operation只携带 typed protocol binding，不重新解释 checkpoint 生命周期 |
| route/order | Graph private C6.4 state + existing `collect_runtime_evidence` | Graph只消费 resolved typed operation，执行 START TOCTOU、顺序和既有节点路由，不保存业务字段表 |
| commit/result | C5 `write_with_result` 正确；外围 post-validator可把 committed改为blocked | Store/C5仍是 commit truth；public只映射 structured result，不以 Presentation/readback重复解释覆盖 committed |
| historical driver | 直接 build Graph、模拟 Store/hash、解释 totals/pending/verdict | 字节和 hash 只读保留；future adapter 只能 prepare feature parameters → call public typed operation → present structured result |

`ArtifactStore` 当前 `_execute_write` 的实际顺序是 Registry validate → immutable upstream/
role/freshness validate → envelope/hash projection → pending/revision/latest protocol。工作包 A 在
immutable upstream 与 Registry 结构校验之后、envelope/hash 与 pending marker 之前插入唯一
semantic precommit；不得把该时机移到 Graph-only 或 post-commit。

##### 12.7.2.3 typed Verification Operation family（工作包 A 只注册一个 variant）

- 新公共模块 `src/mod_agent/verification_operations.py` 定义：
  `VerificationOperationSpec`（preflight 输入）、`VerificationOperationEnvelope`（preflight
  输出与 execute 输入）、`VerificationAttemptPolicy`、`VerificationProtocolBinding`、
  `EvidenceConsolidationOperationV1`、`resolve_verification_operation` 与
  `project_verification_operation`。
- `VerificationOperationEnvelope` 是小型 exact envelope，只含
  `envelope_contract_version="verification_operation_envelope_v1"`、
  `operation_kind="runtime_evidence_consolidation"`、
  `operation_contract_version="runtime_evidence_consolidation_v1"`、
  `approval_identity_hash`、exact `attempt_policy`、exact `protocol_binding` 和 exact typed
  `variant_payload`；缺失、额外字段或未知 kind/version 全部 fail-closed，无 generic fallback。
- `VerificationAttemptPolicy` 对本 variant 精确为
  `{attempt_budget:1,retry_allowed:false,recovery_allowed:false}`。
  `VerificationProtocolBinding` 精确绑定 immutable WorkflowCheckpoint、accepted ResumeReport
  的 logical identity，以及 `resume_id`、`approved_by`；它证明批准协议已经发生，不虚构
  Approval Artifact，也不成为产品 RuntimeEvidence envelope upstream。
- `EvidenceConsolidationOperationV1` 精确绑定 FeatureSpec、BuildResult、prior RuntimeEvidence、
  EvidencePack 的 logical identity、versioned canonical delta、三项 implementation-evidence
  execution binding、output status=`blocked` 和 side-effect scope。它拒绝任意 final
  RuntimeEvidence payload、caller validator/handler/factory 与额外字段。
- `preflight_local_runtime(verification_operation=VerificationOperationSpec(...))` 生成完整
  canonical action identity、domain-separated hash 与 `VerificationOperationEnvelope`；
  `resume_local_runtime(verification_operation=<同一 envelope>,
  expected_approval_identity_hash=<人工批准 hash>)` 重新运行同一零写入 preflight，并在
  ResumeReport新写（本 variant固定为零）、Graph、Store、effect 前逐字比较。missing/mismatch
  返回 `blocked/authorization`，全部业务 Artifact/pending 增量为零。
- C6.4 从未发布，所以删除新的 `runtime_evidence_consolidation_only`，不存在它的 legacy
  compatibility 承诺。typed operation 与任何现有 `runtime_evidence_only`、
  `runtime_terminalization_only`、default/retry/recovery legacy 参数混用时，最外层 public
  normalizer 在 Graph/checkpoint/Store 前拒绝。C6.1–C6.3 的 bool 暂时仅标为既有 public
  compatibility 参数；工作包 B 将其从内部 Graph/checkpoint/result state machine 移除。

##### 12.7.2.4 Approval Identity、locator 与 allowed delta

- `src/mod_agent/action_identity.py` 是从已提交 C2/C3 canonicalization/hash primitive提取的中立
  Action Identity owner，固定 canonical UTF-8 JSON、domain separation 与 SHA256。
  `edit_authority_capabilities.py` 的冻结 legacy v0、historical v1/versioned record仍拥有各自
  projection/reconstruction contract，但其serializer/hasher委托该中立primitive；提取前后的既有
  Request/Approval identity与hash字节必须逐项相同。`verification_operations.py` 与 C6.4 semantic
  owner只声明/提供 action projection，不再实现第二套JSON/hash，也不把Stagger Edit Authority
  capability declaration扩张为Runtime operation owner。
- C6.4 identity projection绑定：四个 exact logical Artifact identity、typed protocol
  binding、canonical delta、file role + content SHA256、`target_source` 的稳定相对逻辑路径
  `Patches/HitFeedbackBehaviorPatch.cs`、output/status、side-effect scope、attempt policy、
  envelope/operation/adapter/builder contract version。绝对 workspace/run-local/Store path、
  locator、Store totals/pending、stdout、timestamp、elapsed、Presentation和执行后 observation/
  receipt全部排除。
- 三项 execution file binding仍携带 absolute path 供 containment/current-bytes 校验；
  Approval Identity和durable binding只保存 role + content SHA256，并只对 `target_source`
  保存上述稳定逻辑路径。相同内容迁移到不同物理根不改变 action hash；path越界或最后时刻
  bytes/hash变化仍由 Execution Contract 在 execute、Graph START与Store precommit拒绝。
  这只证明提交时identity，不保证未来文件可用性；EvidencePack继续解释来源，不新增Artifact。
- 唯一 versioned delta为
  `schema_version="verification_only_criterion_evidence_delta_v1"`、
  `feature_adapter="stagger_c4_implementation_evidence_v1"`。typed Stagger adapter独占 C4
  Criterion文本/identity、四个Evidence IDs、三个file roles、report checks、before/after和
  deterministic evidence/binding builder；公共 workflow/Registry/Store不复制这些常量。
- allowed delta只允许目标Criterion的 outcome、evidence strength、evidence refs以及已批准
  implementation-evidence item/source/binding发生确定性变化。predecessor其余字段逐字保持；
  其他Criterion、`acceptance_verified`、`claims_real_runtime_success`、verification/runtime/
  acceptance/overall status、attempt completion、`real_runtime_performed`、startup/gameplay/
  operator/raw output/marker、run/build/feature identity不得变化，不增加未声明 evidence、
  source、limitation 或任意其他字段。

##### 12.7.2.5 单一 canonical semantic owner 与 trusted precommit

- `src/mod_agent/runtime_evidence_consolidation.py` 是纯确定性 C6.4 semantic owner；不导入
  Graph、checkpoint、具体 `ArtifactStore` 或 Presentation。它唯一负责 resolve adapter、
  canonicalize approved delta、声明 action projection inputs、构造 derived payload、验证
  binding、以及从 predecessor + approved delta + exact evidence重建 submitted payload。
  当前只注册 v1/Stagger C4；unknown contract/adapter/builder fail-closed，不建立通用插件平台。
- 顶层 `src/mod_agent/artifact_semantics.py` 定义非持久化
  `ArtifactSemanticWriteContext` 与 `ArtifactWriteIntent`。Context只读字段精确为 Artifact type、
  feature identity、status、submitted payload、ordered exact upstream refs、exact-revision role
  set、blockers、trace refs、typed semantic intent与只读 Artifact accessor；handler不能写Store、
  启Graph、消费checkpoint、决定C5结果或retry/recovery。
- `ArtifactWriteIntent` exact schema为：
  `schema_version="artifact_write_intent_v1"`、`artifact_type="runtime_evidence"`、feature id、
  status=`blocked`、`semantic_binding={key:"runtime_evidence_consolidation",version:"1"}`、
  ordered exact upstream refs、`exact_revision_upstream_types=[evidence_pack,runtime_evidence]`
  （canonical排序）、`blockers=[]`、`trace_refs=[]`、exact `protocol_refs`（WorkflowCheckpoint与
  accepted ResumeReport的完整immutable `ArtifactRef`）、三项`execution_file_bindings`
  （role、absolute path、content SHA256、仅target_source含稳定logical target path）、
  trusted handler重建的`commit_conflict_key`、expected canonical payload hash、expected full
  Artifact content hash与allowed Artifact type。intent不重复携带caller提交的final payload；
  payload仍是`write`的既有参数并由intent hash绑定。
- `ArtifactStore.write`与`write_with_result`新增可选关键字参数
  `semantic_intent: ArtifactWriteIntent | None = None`；普通无semantic binding Artifact保持历史
  调用与bytes完全兼容。payload出现已注册semantic binding时intent强制必填；intent存在但payload
  binding缺失/未知、或任一字段漂移时pending前拒绝。direct Store caller与Graph使用同一typed
  intent API，不能以“不经过Graph”为由绕过semantic gate。
- `artifact_semantics.py::project_artifact_write_intent` 是唯一 authoritative projector；Graph和
  direct caller都只能调用它，不能自行构造handler或expected hash。projector读取已注册immutable
  checkpoint/report/四upstream和EvidencePack所声明的source/report locator，验证containment与当前
  bytes，然后生成ephemeral intent；绝对locator不进入approval identity或durable payload。
  `ArtifactStore._execute_write` 是唯一consumer：它不信任caller给出的intent，按payload binding
  固定解析同一handler，用intent中的ephemeral locator/protocol refs重新投影并逐字段比较，再按
  Artifact contract重新计算expected payload/full envelope content hash。missing/tampered intent为
  `blocked_before_commit/commit_started=false/admission_validation`。
- durable RuntimeEvidence中的`verification_only_evidence_consolidation`最小exact schema固定为：
  `schema_version="verification_only_evidence_consolidation_v1"`、
  `semantic_binding={key:"runtime_evidence_consolidation",version:"1"}`、
  operation/envelope/adapter/builder contract version、完整canonical action identity及hash、
  canonical delta及hash、四个logical input identity、logical checkpoint/report protocol binding、
  三项`{role,content_sha256,logical_target_path?}`、action scope与
  `new_build_performed=false/new_runtime_performed=false/product_source_modified=false`。它不持久化
  absolute locator，但具备从exact upstream + semantic intent重建批准动作所需的全部稳定字段。
- `artifact_semantics.py` 的固定 `(artifact_type,binding key,version) → handler` 映射使用平台
  内建resolver，不接受caller registration/callable；resolver可延迟委托顶层纯semantic owner，但
  `src/mod_agent/artifacts` 与 Store 不导入 `workflow` 或 bounded feature adapter模块。
- Registry只验证 RuntimeEvidence Artifact结构、binding discriminator/key/version存在且已注册；
  不重算 canonical delta/hash、claim或产品语义。Store不消费完整 VerificationOperation，不认识
  C6.1/C6.4名称；它只消费 intent、Artifact contract、exact upstream 与 trusted semantic binding。
- `_execute_write` 在 immutable upstream/Registry结构校验之后、envelope hash与pending之前调用
  `validate_artifact_semantic_write(context)`；handler重新读取 checkpoint/report/predecessor/
  EvidencePack、验证file current bytes，重建 action identity、expected payload和expected content
  identity，并逐字比较。direct `write`、`write_with_result`、public和Graph共用该唯一不可旁路点。

##### 12.7.2.6 lineage、replay、concurrency 与执行顺序

- child upstream有序固定为 BuildResult、FeatureSpec、prior RuntimeEvidence、EvidencePack，全部
  是已注册 immutable revision。prior RuntimeEvidence/EvidencePack在action开始必须latest/fresh，
  child中`require_latest=false`；BuildResult/FeatureSpec沿现有RuntimeEvidence合同。payload binding
  与四upstream逐项一致；checkpoint/ResumeReport只属于protocol binding。
- 当前 Stagger C4 adapter 明确声明
  `successor_policy="one_child_per_predecessor_for_adapter_v1"`：同一 prior RuntimeEvidence 对
  这个 bounded adapter 只有一个合法 consolidation 后继，因此 conflict key 选择
  `(feature_id, semantic_binding key/version, feature_adapter, predecessor full hash)`，不是
  action identity。不同批准动作只要消费同一 predecessor 与同一 adapter，也不能形成第二child；
  这是当前 adapter 的明确产品语义，不推广为所有未来 consolidation。未来variant若允许同根多个
  不同action child，必须在其合同中选择 action-identity conflict key并重新审核，Store不能自行
  把 predecessor 永久唯一解释成平台通则。
- same-successor 查询由 `src/mod_agent/runtime_evidence_consolidation.py` 的 trusted semantic owner按
  semantic binding key/version、feature adapter和exact predecessor统一解释。checkpoint只拥有
  protocol/lineage/freshness admission，不扫描或解释任意 RuntimeEvidence child；异构binding/adapter
  child不得被提升为这个adapter的`already_started`，但它推进latest后仍由既有freshness规则如实阻断
  旧predecessor。
- predecessor已有该 trusted binding/adapter 的direct child即`already_started`并拒绝第二写；
  revision已落盘但commit未完成按C5 partial。为使并发保证可实施，Store只对带trusted semantic
  intent的写入扩展现有pending协议为版本化reservation；普通Artifact继续使用现有artifact-hash
  pending marker v1和`os.replace`路径，历史marker/recovery行为不变。
- semantic reservation marker v2 exact schema为：
  `schema_version="2.0"`、`status="pending_semantic_commit"`、feature id、artifact type、实际
  artifact hash、revision path、latest path、`semantic_binding_key`、`semantic_binding_version`、
  完整`commit_conflict_key`和其domain-separated SHA256 locator。reservation path使用该locator的
  当前32位物理定位规则；marker内保存完整key/hash，短locator碰撞必须fail-closed，不能把另一key
  解释为当前reservation。locator回读必须同时证明marker的semantic binding key/version与expected
  intent及完整conflict key内的binding字段三者逐字一致。
- v2 reservation使用Store-owned exclusive-create primitive（`O_CREAT|O_EXCL`等价语义），禁止
  `os.replace`覆盖。固定顺序为：首次只读child scan与semantic validation → 计算artifact hash和
  conflict key → exclusive reservation install → 回读完整marker → 在reservation持有期间第二次
  direct-child scan、重新执行semantic precommit/bytes/identity TOCTOU → revision/latest/readback →
  删除同一reservation。检查、第二次precommit和pending安装对同一conflict key不可分离；Store只
  处理中立key/marker，不识别C6.4、Criterion或Evidence ID。
- exclusive-create失败时，Store回读现有v2 marker：完整key相同且提交仍在进行，loser返回C5
  `partial`、`commit_started=false`、`failure_stage=admission_validation`，不覆盖marker、不写
  revision/latest；完整key不同时是locator collision，返回
  `blocked_before_commit/false/admission_validation`。exclusive-create本身在安装前失败固定为
  `blocked_before_commit/false/pending_marker_write`。
- winner一旦exclusive安装并回读自己的完整v2 marker成功，就已经进入C5 commit protocol，
  `commit_started`历史事实固定为`true`，不能由后续cleanup追溯改写。reservation后的第二次
  semantic/TOCTOU验证失败固定为`partial/true/commit_verification`；Store仍只删除自己完整匹配的
  marker，但即使cleanup成功且marker/revision最终均absent，outcome仍为partial、
  `recovery_available=false`。marker cleanup失败固定为
  `partial/true/pending_marker_cleanup`；进程崩溃后marker/revision任一存在也按C5 partial读取，
  不得宣称blocked-before-commit或零写。后续immutable revision/latest/commit verification失败继续
  使用现有`immutable_revision_write|latest_alias_write|commit_verification`阶段。
- `_validate_pending_write_marker`、pending state/readback和`recover_pending_writes`按schema分派：
  v1保持现状；v2可读取/报告，但本operation `recovery_allowed=false`，generic recovery不得消费或
  完成v2 reservation，必须返回`semantic_recovery_not_authorized`且bytes不变。工作包A不新增自动
  或显式semantic recovery API；保留marker作为C5 partial事实，后续恢复需新的权限/合同。
- trusted semantic handler返回中立`commit_conflict_key`，Store不接受caller覆盖。确定性跨进程
  并发回归使用两个不同action hash和同一predecessor/conflict key，强制交错exclusive install，
  证明最多一个child committed；loser为`partial/false/admission_validation`，revision/latest不会出现
  第二份。另以FileExists竞争分支中的不同完整key和预置binding tamper分别锁定
  `blocked_before_commit/false/admission_validation`与marker bytes不被当前attempt覆盖。
  这只是现有Store pending协议的一种versioned marker，不新增事务Controller、后台锁服务或通用
  多Artifact事务。
- 固定顺序：zero-write preflight → expected identity gate → exact checkpoint/accepted report
  admission → Graph START重验 → Store semantic-root临界区 → semantic precommit → Store commit
  revision/latest/pending/readback → interrupt after existing `collect_runtime_evidence` → structured
  result。首个Store副作用必须在Graph START后。
- 不写第二ResumeReport，不调用factory/probe/process，不把当前物理DLL重验冒充新Runtime，不进入
  terminal/eval/blocked/repair，不自动retry/replay/recovery。C5 receipt仅进入ephemeral result，
  不进入RuntimeEvidence payload/hash或旧checkpoint。

##### 12.7.2.7 deterministic outcome matrix

| 条件 | public status / failure_stage | new ref / C5 result | Store delta与后续 |
| --- | --- | --- | --- |
| typed/legacy混用、缺失或错误expected hash、side-effect scope错误 | `blocked/authorization` | `null/null` | 全业务revision/latest/pending零增量；retry=0、recovery=false |
| exact input、file、freshness、replay、delta或preflight semantic失败 | `blocked/consolidation_admission` | `null/null` | 零业务写；retry=0、recovery=false |
| Graph START/TOCTOU/protocol漂移 | `blocked/graph_consolidation_admission` | `null/null` | 零业务写；retry=0、recovery=false |
| Store缺失/篡改semantic intent，或semantic precommit/content identity失败且未安装v2 reservation | `blocked/runtime_evidence_store` | `null/blocked_before_commit` | `commit_started=false`，revision/latest/pending零增量 |
| loser遇到同key既有v2 reservation | `partial/runtime_evidence_store` | `null/partial` | loser `commit_started=false/admission_validation`；不覆盖、不消费、不恢复 |
| winner安装并回读v2 reservation后，二次validation失败 | `partial/runtime_evidence_store` | `null/partial` | `commit_started=true/commit_verification`；即使cleanup成功且marker/revision最终absent也不追溯改写；recovery=false |
| winner cleanup失败、进程中断或revision/latest未完成 | `partial/runtime_evidence_store` | `null/partial` | `commit_started=true`，保留C5精确marker/revision/failure_stage；不消费、不恢复、不重试 |
| Store完成revision/latest/pending清理/readback | `completed/null` | exact RuntimeEvidence ref / `committed` | ref/receipt保留；retry=0、recovery=false |

Store committed是唯一commit truth。完整业务semantic reconstruction必须在pending前完成；commit后
只允许C5自身的integrity/readback确认。public不再运行能把committed改为blocked/“未提交”的第二套
semantic validator；Presentation或外围重复读取失败可以作为audit/presentation error展示，但不能
反向改写machine commit终态。

##### 12.7.2.8 最低 authority、兼容与体量门

1. 正确四个 exact immutable upstream下，分别篡改
   `claims_real_runtime_success`、非目标Criterion、target before/after、canonical delta/hash、
   Evidence IDs、file binding、action scope、contract/adapter/builder version或lineage；`write`与
   `write_with_result`均在pending前拒绝，C5为`blocked_before_commit`、`commit_started=false`，
   revision/latest/pending/Store bytes不变。
   payload有semantic binding但intent缺失、intent有错误protocol/file locator/hash/conflict key/expected
   content identity，以及无binding却提交intent，也必须得到相同零写入结果；普通非semantic
   Artifact不传intent的历史写入保持。
2. unknown operation/version/adapter、typed+legacy混用、preflight→execute identity漂移、Graph
   TOCTOU与同predecessor并发不同child均fail-closed。v1 pending/recovery回归逐字保持；v2 full-key
   locator collision、loser partial/commit_started=false、winner安装成功后二次validation失败且
   cleanup成功仍为partial/commit_started=true、cleanup失败、crash marker读取及generic recovery
   不消费均有filesystem回归。audit、Store totals和Presentation变化hash
   稳定；exact Artifact、delta/content hash、logical target、side-effect scope或attempt policy变化
   hash改变。
3. 正向public → Graph → Store证明三个消费者委托同一operation declaration、neutral identity
   owner和semantic owner；Registry不复制业务hash，artifacts层不反向依赖workflow/feature
   orchestration，direct Store不能旁路；C2/C3既有Edit Authority五类及historical v1/v0固定hash
   在primitive提取前后逐字不变。
4. C5三态、C6.1–C6.3/default/retry/recovery focused回归保持；C6.4无Build、Runtime、factory、
   process、game-directory、terminal Artifact或自动恢复。历史`dd7d...`及下游lineage继续可读。
5. 新增符号、删除/降级旧分支以及 local_entry/checkpoint/graph/Store/Registry/feature adapter
   的迁移前后authority对照进入实施回填；新 staged diff必须唯一，复算normal/full-index hash、
   `diff --check`与联合suite后再送独立验收。

当前 `unresolved_contract_decisions=[]`。若实现需要让 Store 理解完整operation、让caller传validator、
新增Artifact/Approval/业务Graph node、改变C6.1–C6.3行为或保留post-commit semantic verdict，必须停止并
重新审核，不得作为private helper决定。

##### 12.7.2.9 工作包 A 实施回填（待独立验收）

- 实施基线保持 `HEAD=18d1849162ecba3df0ce9d22f9ab7f43ad144a0a`。最终工作树只有本包
  11 个 tracked 文件 staged；e3bb 中两份用户未跟踪文档保持未修改、未暂存。此前首次实现的
  staged+unstaged 两层已被一个 staged identity整体替代，没有 reset、checkout、产品源码、Build、
  Runtime、GTFO、游戏目录或正式产品ArtifactStore副作用。
- typed authority 实际落在 `src/mod_agent/verification_operations.py`：
  `VerificationOperationSpec`、`VerificationOperationEnvelope`、
  `VerificationAttemptPolicy`、`VerificationProtocolBinding`、
  `EvidenceConsolidationOperationV1`、`resolve_verification_operation`、
  `project_verification_operation` 与 `validate_verification_operation_envelope`。
  `preflight_local_runtime`只接受spec并投影envelope/hash；`resume_local_runtime`只接受已投影envelope与
  `expected_approval_identity_hash`。未发布的`runtime_evidence_consolidation_only`和
  `VerificationOnlyRuntimeEvidenceConsolidationInput`已删除，typed/legacy混用写前拒绝。
- 中立identity owner实际为`src/mod_agent/action_identity.py`的`canonical_action_json`、
  `hash_action_identity`与`hash_canonical_value`；C2/C3 current/historical serializer在不改变既有
  Request/Approval bytes与hash的前提下委托该owner。C6 variant只提供action projection，绝对
  execution locator不进入identity；role/content hash与target_source稳定逻辑路径进入identity。
- 单一产品semantic owner实际为`src/mod_agent/runtime_evidence_consolidation.py`。它独占Stagger C4
  adapter、delta、Evidence IDs、file roles、report checks、derived payload与
  predecessor→delta→submitted payload逐字验证，以及同trusted binding/adapter的exact successor
  查询；它不导入Graph、checkpoint、具体Store或
  Presentation。被拒绝实现中的`src/mod_agent/workflow/runtime_evidence_consolidation.py`及其
  workflow-owned hash/validator已退出工作树，Registry与Graph不再复制Criterion/hash/claim表。
- 中立precommit接口实际为`src/mod_agent/artifact_semantics.py`的
  `ArtifactSemanticWriteContext`、`ArtifactSemanticProjection`、`ArtifactWriteIntent`、
  `project_artifact_write_intent`和固定trusted handler resolver。Registry只委托
  `require_registered_semantic_binding`做Artifact结构/discriminator检查；Store不导入C6/feature
  owner，也不接收caller callable。
- `ArtifactStore.write`与`write_with_result`共用`_execute_write`，在immutable-upstream与Registry
  admission之后、envelope hash/pending之前重投影并逐字段比较intent；direct Store、public与Graph
  无旁路。`semantic_read_immutable`与`project_artifact_hash`只提供semantic owner所需只读能力。
  semantic reservation v2由`_write_text_exclusive_atomic`、
  `_serialize_semantic_pending_write`、`_validate_semantic_pending_locator`与
  `_unlink_exact_semantic_pending_marker`拥有；Store只解释中立conflict key/marker。v2 locator回读已
  逐字绑定semantic binding key/version、完整conflict key及其hash；FileExists full-key collision固定
  映射为`admission_validation`。
- v2 C5结果已按批准合同实现：winner安装并回读marker后`commit_started=true`不可追溯；二次
  validation失败且cleanup成功仍为`partial/true/commit_verification`且pending/revision可均absent；
  cleanup失败为`partial/true/pending_marker_cleanup`且marker保留；loser为
  `partial/false/admission_validation`；generic recovery返回
  `semantic_recovery_not_authorized`且不消费marker。成功revision/latest/pending/readback后才返回
  `committed`。
- Public/Graph/checkpoint职责实际分层：public重跑零写preflight并比较expected identity，并委托同一
  semantic owner取得exact successor refs；`WorkflowCheckpointStore.preflight_runtime_evidence_consolidation`
  只保留exact protocol/lineage/freshness admission，不再拥有产品successor扫描；Graph START只做
  state/TOCTOU/order并复用现有`collect_runtime_evidence`；Store pending前
  再调用同一semantic owner。Graph传递C5 receipt到ephemeral result并在collect后interrupt；没有第二
  ResumeReport、factory、probe、process、terminal/eval/blocked/repair路径。committed后不存在能把
  Store truth改为blocked的业务post-validator。
- authority迁移前后：`local_entry.py`由首次混合实现的约`+978`收敛为本包最终`601+/1-`；
  `graph.py`由约`+350`收敛为`190+/24-`；`checkpointing.py`为`191+/0-`并只保留protocol/lineage；
  rejected workflow semantic模块从工作树删除。新增neutral/typed/semantic owner与v2 commit protocol
  使本包相对HEAD仍为净新增，最终不是机械减行提交；实质收缩是旧bool、workflow hash、Registry/
  Store/Graph字段子规则和postcommit verdict authority全部退出，并由三位单一owner及一个Store
  commit时机取代。
- 最终 staged normal binary diff：213,958 bytes，SHA256
  `8A454F68579777579637C24F40AB593E1520465230F4EFF3F97594E3B19A5BEB`；
  `--full-index`：214,684 bytes，SHA256
  `42A85C651A366DDAD8D55815E952E5A8A358C3175EACA1175F3A77F62A597F73`；
  11 files，`4592+/234-`，`git diff --cached --check`通过。
- focused联合命令：
  `python -B -m pytest -q -p no:cacheprovider tests/unit/test_artifact_store.py tests/unit/test_artifact_contract.py tests/unit/test_edit_authority_capabilities.py tests/unit/test_stagger_edit_authority.py tests/unit/test_verification_only_continuation.py`
  → `256 passed in 65.71s`。覆盖C2/C3历史hash、普通Artifact/C5、C6.1–C6.3兼容、typed
  preflight→execute、正确四upstream下claim/非目标Criterion/delta/file/action/version/adapter篡改、
  write与write_with_result零写拒绝、Graph TOCTOU、replay/file drift、v2 winner/loser/cleanup/
  recovery、same-adapter/异构child authority分界、marker binding/full-key collision及两个不同action的
  真实`write_with_result`并发全链。`ruff`在当前Python环境未安装，因此没有伪造lint通过声明；所有变更
  Python模块已通过`py_compile`，联合pytest无collection/import失败。
- 工作包A已完成上次`changes_required`两项修正，经独立复验批准并提交为
  `6f415d00e008af4a933b32529e82481ad81547ee`；C6整体仍为`partial`，工作包B已进入合同审核前
  inventory，第二产品切片和后置Authority文档归并均未触发。

#### 12.7.3 C6 工作包 B：统一 operation authority 与 future adapter 边界

> **工作包状态**：`contract_revised_for_independent_review`。工作包 A 已由独立审核批准并提交为
> `6f415d00e008af4a933b32529e82481ad81547ee`；本节只定义 B 的唯一实施合同。B 不新增产品
> Build/Runtime 能力，不执行正式 Store/Build/Runtime/GTFO 副作用，不修改产品源码。
> `unresolved_contract_decisions=[]`；普通helper、fixture、文件拆分和private executor组织不进入
> 公共合同审核。

##### 12.7.3.1 bounded owner inventory

当前真实状态不是“四个 bool 的命名问题”，而是同一个 operation decision 被五层分别组合：

| 当前能力 | 当前 selector/owner | operation kind | attempt policy | protocol binding | completion scope |
|---|---|---|---|---|---|
| C6.1 verification-only Build | `preflight_verification_only_build_continuation`、`execute_verification_only_build_continuation`、Graph `verification_only_continuation + stop_after_build + persist_build_runtime_handoff` | `verification_build` | initial、one-shot | 无输入 checkpoint；exact FeatureSpec、EvidencePack、run/request identity | `build_handoff` |
| C6.2 RuntimeEvidence-only | public `runtime_evidence_only=True`；Graph `runtime_continuation_checkpoint_id + runtime_evidence_write_results + interrupt_after` | `runtime_execution` | initial、one-shot | exact WorkflowCheckpoint + 新 resume/approver + canonical Runtime admission；新写 ResumeReport | `runtime_evidence_only` |
| default Runtime | 四个 legacy bool 均 false | `runtime_execution` | initial | exact WorkflowCheckpoint + 新 resume/approver；新写 ResumeReport | `runtime_workflow` |
| observation retry | `retry_runtime_observation=True` 与 `preflight_runtime_observation_retry` | `runtime_execution` | observation retry；budget 来自 exact RepairPlan | exact checkpoint + 已接受 ResumeReport + prior RuntimeEvidence + RepairPlan；不写第二份 ResumeReport | `runtime_workflow` |
| accepted-resume recovery | `recover_accepted_resume=True` 与 accepted-resume recovery preflight | `runtime_execution` | recovery of existing attempt | exact checkpoint + 已接受 ResumeReport；不写第二份 ResumeReport | `runtime_workflow` |
| C6.3 terminalization | public `runtime_terminalization_only=True`、Graph `runtime_terminal_continuation` | `runtime_terminalization` | initial Store-only、one-shot | exact checkpoint + accepted ResumeReport + committed RuntimeEvidence | `terminal` |
| C6.4 consolidation | 当前 `VerificationOperationSpec/Envelope` | `runtime_evidence_consolidation` | initial Store-only、one-shot | exact checkpoint + accepted ResumeReport；variant 另绑定四个产品 upstream | `runtime_evidence_consolidation` |

实证 owner 分叉如下：

- `src/mod_agent/verification_operations.py` 当前只注册 C6.4；
- `src/mod_agent/local_entry.py` 同时由 public signature、`_RuntimeContinuationHandoff`、多个 handoff/
  identity/result helper 消费 `runtime_evidence_only`、`runtime_terminalization_only`、
  `recover_accepted_resume`、`retry_runtime_observation`；
- `src/mod_agent/workflow/graph.py::build_graph` 不直接读取这四个名字，但由
  `verification_only_continuation`、`runtime_terminal_continuation`、
  `runtime_continuation_checkpoint_id`、两个 write-result bool 及 stop/persist 组合重新解释 operation；
- `WorkflowCheckpointStore` 通过五个不同 preflight 方法表达 initial/recovery/retry/terminal/
  consolidation，当前尚无 typed dispatcher；
- C6.2、C6.3 和 C6.1 各自拥有 `_verification_only_runtime_execution_identity`、
  `_verification_only_runtime_terminal_identity`、Build preflight `projection_hash`；default/retry/
  recovery 没有统一 action identity；
- 当前 production adapter 只有 `src/mod_agent/cli.py` 的 `preflight-runtime`/`resume-runtime`；它传
  legacy 参数，并在 CLI 内用 `current_stage` 与 `claims_real_runtime_success` 二次解释 exit；
- `workspaces/stagger_verification_only_build_001/run_build.py`、
  `workspaces/stagger_verification_only_runtime_001/run_runtime.py`、
  `workspaces/stagger_c4_evidence_consolidation_001/project_c4_evidence_consolidation.py` 及更早正式
  driver 已有真实执行引用，冻结为 historical audit bytes；B 不修改、重放或要求它们符合新 adapter
  规则。

##### 12.7.3.2 唯一 declaration 与 exact shape

`src/mod_agent/verification_operations.py` 是唯一 operation declaration/schema-evolution owner。
每个 `(operation_kind, operation_contract_version)` 必须精确注册：

- exact variant type/schema；
- exact allowed attempt shape；
- exact protocol-binding type；
- action identity schema/hash domain/projector；
- completion scope、side-effect class、Graph route/handler；
- output Artifact roles/types；
- structured result type；
- compatibility/deprecation 状态。

Public、Graph、checkpoint dispatcher、result mapper 与 tests 只消费这张 declaration；unknown
kind/version、unknown variant/attempt/protocol shape、额外字段均 fail-closed，没有 generic fallback。
中立 `src/mod_agent/action_identity.py` 继续唯一负责 canonical JSON、domain separation 与 hash；
operation declaration 选择 projector，不能在 local_entry/Graph/checkpoint/driver 重新实现 hash。

本包注册四个 operation kinds、七个 exact shapes：

| key | exact variant | exact attempt | exact protocol | completion | side effect / outputs |
|---|---|---|---|---|---|
| `verification_build / verification_build_v1` | `VerificationBuildOperationV1` | `InitialAttemptV1` | `BuildInvocationProtocolBindingV1` | `build_handoff` | caller Build effect；BuildResult，成功可加 WorkflowCheckpoint |
| `runtime_execution / runtime_execution_v1` | `RuntimeExecutionOperationV1` | `InitialAttemptV1` | `NewRuntimeResumeProtocolBindingV1` | `runtime_evidence_only` | Runtime effect；ResumeReport + RuntimeEvidence；在 evidence 后 interrupt |
| `runtime_execution / runtime_execution_v1` | `RuntimeExecutionOperationV1` | `InitialAttemptV1` | `NewRuntimeResumeProtocolBindingV1` | `runtime_workflow` | Runtime effect；ResumeReport + RuntimeEvidence + 现有 terminal chain |
| `runtime_execution / runtime_execution_v1` | `RuntimeExecutionOperationV1` | `ObservationRetryAttemptV1` | 现有 `VerificationProtocolBinding` | `runtime_workflow` | Runtime effect；复用 report；受 RepairPlan budget 约束 |
| `runtime_execution / runtime_execution_v1` | `RuntimeExecutionOperationV1` | `AcceptedResumeRecoveryAttemptV1` | 现有 `VerificationProtocolBinding` | `runtime_workflow` | 恢复同一 Runtime attempt；复用 report |
| `runtime_terminalization / runtime_terminalization_v1` | `RuntimeTerminalizationOperationV1` | `InitialAttemptV1` | 现有 `VerificationProtocolBinding` | `terminal` | Store-only；BlockedReport 或 EvalReport + WorkflowSummary/BlockedReport |
| `runtime_evidence_consolidation / runtime_evidence_consolidation_v1` | 现有 `EvidenceConsolidationOperationV1` | 现有 `VerificationAttemptPolicy(1,false,false)` 的 initial 语义 | 现有 `VerificationProtocolBinding` | `runtime_evidence_consolidation` | Store-only；一份 RuntimeEvidence |

Exact public type schema固定如下；实现不得把这些字段改成一个带大量可空字段的通用对象：

| type | exact fields |
|---|---|
| `BuildInvocationProtocolBindingV1` | `run_id: str`、`request_id: str` |
| `NewRuntimeResumeProtocolBindingV1` | `checkpoint_ref: ArtifactRef`、`resume_id: str`、`approved_by: str`；不存`runtime_admission` |
| 现有 `VerificationProtocolBinding` | `checkpoint_ref`、`accepted_resume_report_ref`、`resume_id`、`approved_by`；字段与C6.4 identity字节不变 |
| `InitialAttemptV1` | `attempt_number=1`、`retry_allowed=false`、`recovery_allowed=false` |
| `ObservationRetryAttemptV1` | `prior_runtime_evidence_ref`、`repair_plan_ref`、`retry_number`、`retry_budget`、`retry_budget_remaining`、`current_attempt_approved_by` |
| `AcceptedResumeRecoveryAttemptV1` | `accepted_resume_report_ref`、`recovery_of_resume_id`、`current_attempt_approved_by`、`automatic_retry_count=0` |
| `VerificationBuildOperationV1` | `feature_spec_ref`、`evidence_pack_ref`、`user_request`、`target_domain`、`target_mod`、`completion_scope=build_handoff`、固定 `build_effect_contract=one_caller_build_factory_invocation_after_graph_admission` |
| `RuntimeExecutionOperationV1` | `completion_scope`、`runtime_action_scope`；`runtime_action_scope`是`runtime_admission`的唯一canonical存储位置，并精确包含game launch/write权限、plugin destination action target及固定one-shot factory contract；不存attempt副本 |
| `RuntimeTerminalizationOperationV1` | `runtime_evidence_ref`、固定 `terminal_result_scope`（allowed Artifact roles、automatic retry=0、recovery=false） |
| 现有 `EvidenceConsolidationOperationV1` | `feature_spec_ref`、`build_result_ref`、`prior_runtime_evidence_ref`、`evidence_pack_ref`、`canonical_delta`、`execution_file_bindings`、`output_status`；字段不变 |

Build caller factory与Runtime caller factory仍是non-authoritative effect adapter，不进入可序列化 envelope；
declaration identity批准的是固定one-shot effect contract与其exact inputs/side-effect scope。factory输出必须在
Store前由现有Build/Runtime validator验证，caller不能用不同factory结果扩张已批准scope。C6.1历史外层授权包
中更细的BuildProfile/command identity继续属于该历史执行证据；B不把未持久化的旧driver projection伪造成
新的公共Artifact或历史Approval。

Normalized `VerificationOperationSpec/Envelope` 的唯一运行时schema固定为：

```text
operation_kind
operation_contract_version
attempt_policy          # 唯一attempt存储位置
protocol_binding        # 唯一checkpoint/resume/protocol存储位置
variant_payload         # 唯一action/completion存储位置
approval_identity       # 仅Envelope；由上述字段投影
approval_identity_hash  # 仅Envelope
```

新shape的`attempt_policy`是`InitialAttemptV1 | ObservationRetryAttemptV1 |
AcceptedResumeRecoveryAttemptV1`。C6.4继续无损保存已提交的旧`VerificationAttemptPolicy`三字段对象；
resolver仅把该exact类型派生为semantic tag=`initial`，不在variant或protocol中写第二份attempt，也不改变
C6.4 identity bytes。`runtime_admission`只存在于`RuntimeExecutionOperationV1.runtime_action_scope`；
`NewRuntimeResumeProtocolBindingV1`不含它，identity projector只能从variant读取。

`RuntimeExecutionOperationV1` 不是 nullable soup：它只存 exact `completion_scope` 与 action scope；
attempt由顶层exact type表达。只有上表四个 runtime-execution 组合注册；retry + evidence-only、recovery +
new ResumeReport、initial + accepted report 等未登记组合在 public/Graph/Store/factory 前拒绝。
`ObservationRetryAttemptV1` 绑定 exact prior RuntimeEvidence、RepairPlan、retry number/budget；
`AcceptedResumeRecoveryAttemptV1` 绑定既有 accepted ResumeReport。accepted protocol 必须分别保存原
ResumeReport approver 与 current-attempt approver，不能把两者静默视为同一身份。

全family的completion literal集合精确为五个：`build_handoff`、`runtime_evidence_only`、
`runtime_workflow`、`terminal`、`runtime_evidence_consolidation`。Build/terminal/consolidation的completion由
exact declaration派生，不在variant重复持久化；只有同一`runtime_execution_v1`下需要区分两种完成范围，
所以其variant存一个`completion_scope`。此前“四类completion”的计数作废。

`VerificationOperationDeclaration` 增加 exact-shape resolver，而不是让 caller 组合 type：
`variant_type + attempt_type + protocol_type + completion_scope` 必须命中一行。C6.4 已提交
`VerificationOperationSpec/Envelope`、identity 字节和 `VerificationProtocolBinding` 保持兼容；本包
扩展同一家族，不创建第二份 envelope。

##### 12.7.3.3 action identity 与跨调用 gate

- typed preflight 构造 exact `VerificationOperationEnvelope`；成功或可归属的authorization/admission失败均
  返回下文固定的`VerificationOperationPreflightResultV1`，而不是执行期
  `VerificationOperationResultV1`；
- typed execute 显式接收 envelope 与 `expected_approval_identity_hash`，重跑相同零写 admission，并在
  ResumeReport/Graph/Store probe/factory/process 前逐字比较；
- identity-incomplete 的历史 default/profile、observation-retry 与 accepted-resume-recovery
  `preflight_local_runtime` 调用固定归类为 `legacy_advisory_preflight_v0`。它只产生无写入的运行条件、
  配置与外部授权准备观察，不构造或返回 `VerificationOperationEnvelope`、Approval Identity hash、
  expected hash、`approved_by` 或自动生成的 `resume_id`，也不声明 operation authorization。该 advisory
  结果不能作为 execute 输入，不能被 `resume_local_runtime`、Graph、checkpoint、Store 或 effect adapter
  消费；default/retry/recovery 的 legacy execute 仍须在同一次 outer execute invocation 中从真实输入形成
  exact Spec/Envelope，并在首个副作用前进入单一 typed executor；
- C6.2 `verification_only_runtime_execution_identity_v1` 与 C6.3
  `verification_only_runtime_terminal_identity_v1` 的 schema、domain、canonical 字节和既有 hash 保持
  逐字兼容，但其 projector/hasher authority 迁入 declaration + `action_identity.py`；
- C6.1 新增独立 clean action identity。现有 `verification_only_lineage.preflight_hash` 继续只是
  BuildResult lineage/evidence 字段，不冒充 Approval Identity，也不因新增 identity 被改写；
- default/retry/recovery 首次获得 declaration-owned action identity；exact Artifact、attempt、Runtime
  admission、side-effect scope、budget 或 capability version 变化必须改变 hash；Store totals、pending、
  stdout、timestamp、absolute Store locator、耗时与 Presentation 不进入 identity；
- C6.1与default/retry/recovery的legacy public调用在同一outer invocation内规范化并使用重算的exact
  envelope，标记为`legacy_public_v0`，不获得“独立preflight→execute漂移已绑定”的新声明；C6.2/C6.3
  已有legacy selector + expected identity hash组合标记为`legacy_selector_bound_identity_v1`并保持原hash
  gate；C6.4及所有新typed caller必须显式提供common expected hash。不能把无expected hash的legacy兼容
  自动提升为新授权能力。

七个shape的identity projector固定如下；所有map经`action_identity.py`的UTF-8、`sort_keys=true`、
`separators=(",", ":")`、`allow_nan=false` canonical JSON后做SHA256，array顺序按下表，不允许projector
自行增删字段：

| shape | identity schema / hash domain | exact canonical projection |
|---|---|---|
| C6.1 Build | `verification_build_action_identity_v1` / `mod_agent.verification_build_action_identity.v1` | `schema_version,hash_domain,operation_kind,operation_contract_version,protocol_binding{run_id,request_id},exact_inputs{feature_spec,evidence_pack},attempt_policy,variant_action{user_request,target_domain,target_mod,build_effect_contract},execution_contract{completion_scope,side_effect_class,output_artifact_types,result_contract}` |
| C6.2 evidence-only | 冻结`verification_only_runtime_execution_identity_v1` / `mod_agent.verification_only_runtime_execution_identity.v1` | 保持现有逐字map：`schema_version,hash_domain,checkpoint{artifact_type,artifact_hash,feature_id,checkpoint_id,run_id,request_id},resume_id,approved_by,runtime_admission`；runtime_admission虽从variant读取，投影位置不变 |
| default initial runtime | `runtime_execution_action_identity_v1` / `mod_agent.runtime_execution_action_identity.v1` | `schema_version,hash_domain,operation_kind,operation_contract_version,checkpoint{logical identity,checkpoint_id,run_id,request_id},attempt_policy,protocol_binding{resume_id,approved_by},runtime_action_scope,completion_scope,execution_contract` |
| observation retry | 同`runtime_execution_action_identity_v1` / 同domain | 与default同序；`attempt_policy`精确加入prior RuntimeEvidence/RepairPlan logical identity、retry number/budget/current approver；`protocol_binding`加入accepted ResumeReport logical identity、original report approver、resume_id |
| accepted-resume recovery | 同`runtime_execution_action_identity_v1` / 同domain | 与default同序；`attempt_policy`精确加入accepted ResumeReport logical identity、recovery_of_resume_id/current approver/automatic_retry_count=0；`protocol_binding`加入accepted report logical identity、original report approver、resume_id |
| C6.3 terminalization | 冻结`verification_only_runtime_terminal_identity_v1` / `mod_agent.verification_only_runtime_terminal_identity.v1` | 保持现有逐字map：`schema_version,hash_domain,checkpoint{artifact_type,artifact_hash,feature_id,checkpoint_id,run_id,request_id},resume_report{logical identity},runtime_evidence{logical identity},resume_id,approved_by,terminal_result_scope{allowed_artifact_types ordered [blocked_report,eval_report,workflow_summary],automatic_retry_count=0,recovery_allowed=false}` |
| C6.4 consolidation | 现有`verification_operation_action_identity_v1` / `mod_agent.verification_operation_action_identity.v1` | 保持当前`project_verification_operation`及C6.4 adapter action projection逐字不变；旧`VerificationAttemptPolicy`三字段map不增加semantic tag |

表中`logical identity`精确为`artifact_type,artifact_hash,feature_id`，不含physical path。`exact_inputs`的
字段顺序虽由canonical map key排序，但role集合固定为FeatureSpec/EvidencePack；所有Artifact array按
declaration role order固定。C6.2/C6.3/C6.4现有golden fixtures的canonical bytes/hash必须逐字相同；
C6.1/default/retry/recovery各新增一个literal golden fixture与literal expected hash，测试不得调用被测
projector生成expected值。新shape没有真实批准实例，因此合同不伪造运行实例hash；实现验收必须回填上述
四个golden fixture hash，任何projection字段变化都使fixture失败并要求重新审核合同。

##### 12.7.3.4 public compatibility normalization

现有 public function 名称保持：

- `preflight_verification_only_build_continuation`；
- `execute_verification_only_build_continuation`；
- `preflight_local_runtime`；
- `resume_local_runtime`。

四个function的typed与legacy调用shape精确固定：

| public function | typed shape | legacy shape / identity级别 |
|---|---|---|
| `preflight_verification_only_build_continuation` | `artifact_store_root + verification_operation: VerificationOperationSpec`；spec必须为C6.1 | 当前FeatureSpec/EvidencePack/run/request/user/target参数全集；`legacy_public_v0` |
| `execute_verification_only_build_continuation` | `artifact_store_root + verification_operation: VerificationOperationEnvelope + expected_approval_identity_hash + build_result_factory + allow_build_execution` | 当前参数全集+factory+allow；无expected hash，`legacy_public_v0` |
| `preflight_local_runtime` | `run_root + artifact_store_root + verification_operation: VerificationOperationSpec`；feature/checkpoint/resume/action均从spec读取并返回execution-grade `VerificationOperationPreflightResultV1` | 具备完整exact protocol identity的C6.2/C6.3 legacy selector保留旧identity projection并返回同一execution-grade preflight result；identity-incomplete的default/profile、observation-retry、accepted-resume-recovery固定为`legacy_advisory_preflight_v0`，只返回历史no-write mapping/`LocalEntryError`，不产生Envelope/hash或执行授权 |
| `resume_local_runtime` | `run_root + artifact_store_root + verification_operation: VerificationOperationEnvelope + expected_approval_identity_hash`，另只允许declaration登记的non-authoritative effect adapter | 当前参数全集；C6.2旧`expected_runtime_execution_identity_hash`与C6.3旧`expected_runtime_terminal_identity_hash`保留为`legacy_selector_bound_identity_v1`；default/retry/recovery无expected hash，为`legacy_public_v0` |

typed shape不再同时接收`feature_id/checkpoint_path/checkpoint_hash/resume_id/approved_by`等identity副本；
这些值来自Envelope exact refs/protocol。`run_root`、`artifact_store_root`及effect adapter属于execution context，
不重定义action identity。legacy shape必须提供当前函数原有完整字段组合；实现可为Python signature增加`None`
默认以支持二选一，但resolver必须在任何副作用前证明“typed全集”或“该legacy全集”且不得混用。common
`expected_approval_identity_hash`与两个旧expected-hash参数也互斥；缺失common hash的typed execute固定
`blocked/authorization`零写拒绝。

四个typed preflight统一返回exact `VerificationOperationPreflightResultV1`：

```text
result_contract_version: Literal["verification_operation_preflight_result_v1"]
preflight_status: Literal["ready", "blocked"]
identity_resolution_status: Literal["unresolved", "declaration_resolved",
                                    "identity_resolved"]
operation_kind: Literal["verification_build", "runtime_execution",
                        "runtime_terminalization", "runtime_evidence_consolidation"] | null
operation_contract_version: str | null
envelope: VerificationOperationEnvelope | null
approval_identity_hash: str | null
failure_stage: Literal["authorization", "admission"] | null
blockers: tuple[VerificationOperationBlockerV1, ...]
audit_snapshot: dict[str, JsonValue]
```

`ready`必须`identity_resolution_status=identity_resolved`，同时具有非空operation kind/version、Envelope、
hash，且`failure_stage=null`、`blockers=()`。preflight blocked精确分三种：

| identity resolution | trusted fields | preflight outcome |
|---|---|---|
| `unresolved` | kind/version/Envelope/hash全null；不回显caller值 | unknown kind/version/shape、typed/legacy混用或缺失required typed field→`blocked/authorization` |
| `declaration_resolved` | declaration给出的kind/version非空；Envelope/hash为null | 构造identity所需的checkpoint/Artifact缺失、bytes/hash/schema/read失败→`blocked/admission` |
| `identity_resolved` | kind/version、canonical Envelope、平台投影hash全非空 | identity形成后的lineage/freshness/file/protocol admission失败→`blocked/admission` |

三类blocked都必须至少一个blocker。Python调用签名错误或non-callable effect adapter仍是`TypeError`。
typed preflight与具备完整exact protocol identity的C6.2/C6.3 legacy selector preflight由同一个
`VerificationOperationPreflightResultV1` projector产生；`ready`继续要求exact Envelope/hash非空。
`legacy_advisory_preflight_v0`保留现有mapping、status字面量与`LocalEntryError`兼容边界：正常返回mapping
表示advisory检查已正常完成，CLI exit=0；`LocalEntryError`表示advisory未正常完成，CLI exit=2。exit=0不表示
action获准、execution-grade identity已形成或执行将成功；advisory status不得交给declaration result projector。

legacy execute只在最外层执行一次 `legacy parameters -> VerificationOperationSpec/Envelope`。typed operation
与任一legacy selector/identity参数混用时零副作用拒绝。规范化后传入executor、Graph、checkpoint与result
mapper的唯一selector是resolved envelope/declaration。以下四个bool只允许在最外层选择
`legacy_advisory_preflight_v0`兼容表面或execute normalizer；它们不再出现在Graph、checkpoint、Store、
semantic validator、result state machine或private handoff：

- `runtime_evidence_only`；
- `runtime_terminalization_only`；
- `recover_accepted_resume`；
- `retry_runtime_observation`。

兼容表：

| surface | B 后状态 | 边界 |
|---|---|---|
| 四个 existing public function 的 legacy keyword | supported + deprecated | 只在函数入口 normalizer 读取；返回字段兼容；不允许新 internal consumer |
| CLI `preflight-runtime`/`resume-runtime` legacy flags | supported + deprecated | 只准备参数并调用public入口；`preflight-runtime`对`legacy_advisory_preflight_v0`保持正常mapping return=0、`LocalEntryError`=2，且不调用execute-result disposition mapper；具备exact identity的preflight读取`VerificationOperationPreflightResultV1.preflight_status`；`resume-runtime`只读取`VerificationOperationResultV1.execution_disposition`；不得解释Store/domain verdict |
| `build_graph` 的 `verification_only_continuation`、`runtime_terminal_continuation`、`runtime_continuation_checkpoint_id` operation selectors | current internal contract removed | production/public call sites迁到 `verification_operation`；frozen historical driver只保留Git/bytes审计，不承诺在当前HEAD重放 |
| checkpoint 五个现有 preflight 方法 | compatibility wrappers | 共同委托 declaration-owned typed dispatcher；方法名不再拥有 operation/attempt 语义 |
| C6.4 typed public path | implemented/current | identity/hash/semantic intent/Store precommit 字节保持 |

generic Graph 的 `stop_after_build`、`interrupt_after` 等非 C6 operation 配置可为其他工作流继续存在；
一旦提供 typed verification operation，其取值必须由 declaration 派生或逐字校验，不再参与 operation
选择。

##### 12.7.3.5 Graph、checkpoint 与 executor 职责

- Public：authorization、legacy normalization、exact input准备、expected-hash gate、structured result；
- Graph：只接收 resolved `VerificationOperationEnvelope` 与 non-authoritative effect adapter；按 declaration
  route/handler 执行 Graph-before-effect、one-shot、TOCTOU 与 interrupt；
- Checkpoint：新增一个 typed admission dispatcher，按 declaration 验证 protocol/attempt；现有方法只做
  兼容投影；checkpoint 不自行组合 completion scope 或 public bool；
- Store：仍只消费 ArtifactWriteIntent、trusted semantic binding、exact upstream 和 C5 commit protocol；
  不接收完整 VerificationOperation，也不识别 C6.1/C6.2/C6.3/C6.4 名称；
- C6.4 业务 invariant 继续只由 `runtime_evidence_consolidation.py` 定义，其他 operation 的平台级
  projector/validator由 declaration 指向的唯一 owner 定义；
- 各 variant 保持独立 executor/lifecycle；不把 Build、Runtime effect、terminalization、consolidation
  合成一个巨型执行器，不新增业务 Artifact/Approval/Controller。

##### 12.7.3.6 authoritative structured result

新增公共 `VerificationOperationResultV1` 小型 envelope，并为四个 operation kind 使用 exact result
variant：`BuildVerificationResultV1`、`RuntimeExecutionResultV1`、
`RuntimeTerminalizationResultV1`、`EvidenceConsolidationResultV1`。公共schema固定为：

```text
result_contract_version: Literal["verification_operation_result_v1"]
operation_kind: Literal["verification_build", "runtime_execution",
                        "runtime_terminalization", "runtime_evidence_consolidation"] | null
operation_contract_version: str | null
approval_identity_hash: str | null
identity_resolution_status: Literal["unresolved", "declaration_resolved",
                                    "approved_identity_only", "identity_resolved"]
platform_status: Literal["completed", "blocked", "partial"]
execution_disposition: Literal["succeeded", "domain_blocked", "platform_blocked",
                               "partial", "operator_input_required"]
failure_stage: str | null
side_effects_may_have_started: bool
attempt_result: VerificationAttemptResultV1 | null
outputs: tuple[VerificationOperationOutputV1, ...]
store_receipts: tuple[VerificationOperationStoreReceiptV1, ...]
blockers: tuple[VerificationOperationBlockerV1, ...]
variant_result: VerificationOperationRejectedResultV1 |
                BuildVerificationResultV1 | RuntimeExecutionResultV1 |
                RuntimeTerminalizationResultV1 | EvidenceConsolidationResultV1
audit_snapshot: dict[str, JsonValue]
```

Exact supporting types：

| type | exact fields / value domain |
|---|---|
| `VerificationOperationRejectedResultV1` | `result_variant: rejected`；不保存caller提交但未验证或尚未current-reconstruct的kind/hash/operation facts |
| `VerificationAttemptResultV1` | `attempt_kind: initial|observation_retry|accepted_resume_recovery`、`attempt_number: int>=1`、`automatic_retry_count: int>=0`、`retry_budget_remaining: int>=0|null`、`current_attempt_is_retry: bool`、`current_attempt_is_recovery: bool`、`recovery_available: bool` |
| `VerificationOperationOutputV1` | `role: str`、`artifact_ref: ArtifactRef`；只有已存在exact immutable ref才进入tuple，不使用null ref占位 |
| `VerificationOperationStoreReceiptV1` | `role: str`、`artifact_write_result: ArtifactWriteResult`；Store attempt已发生才进入tuple |
| `VerificationOperationBlockerV1` | `stage: str`、`code: str`、`message: str`，三者均non-empty |
| `JsonValue` | `null|bool|int|finite float|str|list[JsonValue]|dict[str,JsonValue]`；只用于非权威`audit_snapshot` |

`VerificationAttemptResultV1`值由resolved attempt唯一投影：initial固定`attempt_number=1`、两个
`current_attempt_is_*`均false、budget null；observation retry固定`current_attempt_is_retry=true`、
`attempt_number=retry_number`、budget为该attempt完成后的non-negative remaining；accepted-resume recovery固定
`current_attempt_is_recovery=true`、budget null。三者`automatic_retry_count=0`；`recovery_available`只反映当前
machine result中已有C5/operation recovery事实，不能授权下一次attempt。

execute result按current identity可用性固定四种形状：

| identity resolution | trusted common fields | result boundary |
|---|---|---|
| `unresolved` | kind/version/hash/attempt全null | declaration前`blocked/platform_blocked/authorization`；Rejected variant；outputs/receipts空、side effects=false |
| `declaration_resolved` | declaration kind/version非空；hash/attempt为null | Envelope schema/hash/expected-hash无法形成可信批准identity时的`blocked/authorization`，或无既有approved Envelope的input read失败`blocked/admission`；Rejected variant；不回显caller hash |
| `approved_identity_only` | kind/version与`approval_identity_hash`非空；attempt为null | execute已证明`hash(envelope.approval_identity)=envelope.approval_identity_hash=expected_approval_identity_hash`，但current checkpoint/Artifact read失败，故只能保留“已批准identity”而不能声明current-action reconstruction；`blocked/admission`、Rejected variant、outputs/receipts空、side effects=false |
| `identity_resolved` | kind/version、平台current reconstruction对应的attempt与exact operation variant非空；approval hash在已匹配批准时非空 | current reconstruction完成后的authorization drift、admission/effect/Store及completed/partial结果；不得用Rejected variant |

所有blocked形状blockers非空。`approved_identity_only`的hash只证明Envelope内批准动作及expected gate匹配，
不能证明current Artifact仍可读/新鲜/相同；该区别不得藏入audit_snapshot。`identity_resolved`时若current
reconstruction与approved identity不相同，结果保留已批准hash、以authorization drift阻断，并在blocker中
记录current mismatch；不得把caller expected hash或current mismatch hash冒充新的批准。Rejected variant不能
用于任何effect/Store已开始后的终态。

typed execute在`identity_resolved`时`approval_identity_hash`必须非空。新typed与已绑定C6.2/C6.3路径中，
它是expected gate已匹配的批准hash；`legacy_public_v0`中它只是本次outer invocation投影出的action hash，
必须继续由compatibility level标明“不具备独立preflight→execute批准绑定”，不能因字段同名获得新权限。

`failure_stage`必须为null或命中resolved declaration的ordered `failure_stages`；declaration必须把该tuple
作为exact result contract的一部分，result projector不得输出表外值。现有shape的值集合固定为：

| shape | ordered non-null `failure_stages` |
|---|---|
| C6.1 Build | `authorization,admission,store_preflight,build_execution,post_build_validation,build_result_store,handoff_eligibility,checkpoint_prewrite,checkpoint_store,checkpoint_resume_preflight` |
| C6.2 evidence-only | `authorization,admission,resume_admission,resume_report_store,graph_admission,store_preflight,runtime_execution,post_runtime_validation,runtime_evidence_store` |
| default/retry/recovery runtime workflow | `authorization,admission,resume_admission,resume_report_store,graph_admission,store_preflight,runtime_execution,post_runtime_validation,runtime_evidence_store,graph_terminal_admission,eval_report_execution,eval_report_store,blocked_report_execution,blocked_report_store,workflow_summary_execution,workflow_summary_store` |
| C6.3 terminalization | `authorization,terminal_admission,graph_terminal_admission,eval_report_execution,eval_report_store,blocked_report_execution,blocked_report_store,workflow_summary_execution,workflow_summary_store` |
| C6.4 consolidation | `authorization,consolidation_admission,graph_consolidation_admission,runtime_evidence_store` |

common envelope不再存handoff readiness或operator-input bool。`BuildVerificationResultV1.handoff_ready`是
Build handoff事实唯一owner；`RuntimeExecutionResultV1.operator_input_required`是Runtime operator handoff事实
唯一owner。common `execution_disposition`必须由declaration result projector从authoritative variant field与
platform status派生，并由constructor验证一致：Build `handoff_ready=true`才可`succeeded`；Runtime
`operator_input_required=true`必须`operator_input_required`。反向不一致的result构造fail-closed，不能由
CLI或legacy mapper覆盖。attempt/retry/recovery状态只存在于`attempt_result`；legacy同名字段均从该对象投影。

typed public execution以该对象的 canonical mapping为机器权威。legacy public 返回对象保留现有字段，
并无损嵌入同一 `verification_operation_result`；legacy映射不得产生第二个 status/failure解释。C6.1–C6.4
已批准 outcome matrix逐项保持；default/retry/recovery 的异常改为结构化结果，不再由外围
`LocalEntryError`文本、revision totals、pending、locator或展示文件定义终态。

`legacy_advisory_preflight_v0`不是execute machine result，也不进入上述execution disposition合同。它的CLI
兼容规则固定为：正常返回历史mapping时exit=0，`LocalEntryError`时exit=2；该exit只表达advisory调用是否
正常完成。CLI不得从advisory status推导action authorization、Store/domain verdict或execute disposition。

Exact result variant只承载各operation不同的domain/output事实：

| result variant | exact fields |
|---|---|
| `BuildVerificationResultV1` | `domain_build_status: succeeded|failed|unknown`、`claims_real_build_success: bool`、`build_result_ref: ArtifactRef|null`、`workflow_checkpoint_ref: ArtifactRef|null`、`handoff_ready: bool` |
| `RuntimeExecutionResultV1` | `completion_scope: runtime_evidence_only|runtime_workflow`、`domain_runtime_status: accepted|blocked|inconclusive|unknown`、`resume_report_ref: ArtifactRef|null`、`runtime_evidence_ref: ArtifactRef|null`、`terminal_refs: tuple[ArtifactRef,...]`、`operator_input_required: bool` |
| `RuntimeTerminalizationResultV1` | `domain_acceptance_status: accepted|blocked|inconclusive|unknown`、`runtime_evidence_ref: ArtifactRef`、`eval_report_ref: ArtifactRef|null`、`blocked_report_ref: ArtifactRef|null`、`workflow_summary_ref: ArtifactRef|null` |
| `EvidenceConsolidationResultV1` | `prior_runtime_evidence_ref: ArtifactRef`、`runtime_evidence_ref: ArtifactRef|null`、`derived_payload_hash: str`、`semantic_binding_key: str`、`semantic_binding_version: str` |

每个 ref 字段只允许 exact immutable logical ref或`null`，其nullability由该operation已批准outcome matrix
决定；不得由Presentation重新推断。common result中的role-tagged refs/receipts必须与variant ref逐项相同。

`execution_disposition`由declaration-owned result projector产生，不能由CLI推断：

| condition | execution_disposition |
|---|---|
| `platform_status=partial` | `partial` |
| `platform_status=blocked`且不是明确operator handoff | `platform_blocked` |
| machine result明确需要operator输入且未完成获准action | `operator_input_required` |
| C6.1 completed且Build domain success/handoff合同满足 | `succeeded` |
| C6.1 BuildResult committed但`domain_build_status=failed`且`handoff_ready=false` | `domain_blocked`；`platform_status=completed`、`failure_stage=null`，保持§12.4既有分层 |
| `runtime_execution + runtime_workflow` completed且产品domain accepted | `succeeded` |
| `runtime_execution + runtime_workflow` completed但domain blocked/inconclusive | `domain_blocked` |
| C6.2 evidence-only、C6.3 terminalization或C6.4 consolidation的获准machine action完整committed | `succeeded`，不把产品acceptance冒充该machine action的成功条件 |

default/retry/recovery typed path的deterministic outcome matrix固定如下；“report ref/result”只指本attempt
新写的ResumeReport，retry/recovery复用的accepted report始终是protocol input而不是output/receipt：

| stage/outcome | platform/failure | outputs/receipts | side effects | retry/recovery | legacy mapping |
|---|---|---|---|---|---|
| missing/mismatched expected hash、permission/scope invalid | `blocked/authorization` | none | false | automatic retry=0；no recovery | 抛`VerificationOperationExecutionError(LocalEntryError)`并携带exact machine result |
| handoff/ref/file/freshness/attempt budget/legacy normalization invalid | `blocked/admission` | none | false | 同上 | 同上 |
| initial ResumeReport `blocked_before_commit` | `blocked/resume_report_store` | C5 receipt；ref null | false | 同上 | 同上 |
| initial ResumeReport `partial` | `partial/resume_report_store` | C5 receipt；ref按C5 exact result | false | 同上 | 同上 |
| committed ResumeReport后state reconstruction失败 | `blocked/resume_admission` | report ref + committed receipt保留 | false | 同上 | 同上 |
| retry/recovery accepted-report admission失败 | `blocked/resume_admission` | no new report/output | false | current attempt不自动重试/恢复 | 同上 |
| Graph START/TOCTOU typed binding漂移 | `blocked/graph_admission` | 已committed新report（若有）保留 | false | automatic retry=0；no recovery | 同上 |
| Graph admission后Store probe失败 | `blocked/store_preflight` | 已有report ref/receipt保留 | false；factory count=0 | 同上 | 同上 |
| caller Runtime factory/effect抛异常 | `blocked/runtime_execution` | 已有report保留；RuntimeEvidence null | true | 同上 | 同上 |
| factory返回后identity/payload/source/restoration验证失败 | `blocked/post_runtime_validation` | 已有report保留；RuntimeEvidence null | true | 同上 | 同上 |
| RuntimeEvidence `blocked_before_commit` | `blocked/runtime_evidence_store` | report保留；RuntimeEvidence C5 receipt、ref null | true | 同上 | 同上 |
| RuntimeEvidence `partial` | `partial/runtime_evidence_store` | report保留；RuntimeEvidence receipt/ref按C5 result | true | 同上 | 同上 |
| RuntimeEvidence committed + `runtime_evidence_only` | `completed/null` + `succeeded` | report+RuntimeEvidence exact refs/receipts | true | no automatic retry/recovery | legacy C6.2原structured return保持 |
| RuntimeEvidence committed + `runtime_workflow`，后续terminal Artifact blocked/partial | `blocked|partial/<现有C6.3 exact Store stage>` | 前序refs/receipts全部保留 | true | no automatic retry/recovery | legacy抛携带machine result的`VerificationOperationExecutionError` |
| full terminal chain committed且domain accepted | `completed/null` + `succeeded` | exact terminal refs/receipts | true | no automatic retry/recovery | 返回legacy summary并嵌machine result |
| durable blocked/inconclusive terminal result committed | `completed/null` + `domain_blocked` | exact BlockedReport/Eval refs/receipts | true | no automatic retry/recovery | 返回legacy summary并嵌machine result；CLI exit 1 |
| exact operator input仍必需 | 保留实际platform status + `operator_input_required` | 已有refs/receipts保留 | 按实际factory调用 | no automatic retry/recovery | 返回/抛均携带同一machine result；CLI exit非0 |
| legacy `runtime_resume_result.json` Presentation写失败 | machine result不变 | durable refs/receipts不变 | 不增加业务side effect | no retry/recovery | 抛`VerificationOperationPresentationError(LocalEntryError)`并携带已固定machine result与audit error |

Typed execute public path对所有可归属authorization/admission/effect/Store失败返回
`VerificationOperationResultV1`，不抛外围异常；typed preflight只返回前述
`VerificationOperationPreflightResultV1`，两者不得互换。
legacy default/retry/recovery为保持`except LocalEntryError`兼容，在上表注明处抛其typed subclass，但异常对象
必须携带同一`verification_operation_result`，不得重算status。Python调用形状错误、non-callable effect
adapter等无法形成合法operation的编程错误继续抛`TypeError`；unknown kind/version/shape属于可归属
authorization失败，必须structured blocked而非裸异常。C6.1–C6.4既有return/exception边界保持各自已批准
matrix，仅增加无损machine-result嵌入。

CLI 只读取公共 `verification_operation_result.execution_disposition`映射进程 exit；不得读取
`claims_real_*`、`current_stage`、Store totals/pending/path形成第二个产品 verdict。唯一exit表固定为：

| `execution_disposition` | process exit |
|---|---|
| `succeeded` | `0` |
| `domain_blocked` | `1` |
| `operator_input_required` | `1` |
| `platform_blocked` | `2` |
| `partial` | `2` |

这保留当前 `resume-runtime` 的成功 `0`、已返回但产品未完成 `1`、公共调用异常 `2` 三层外部语义，
同时把原先由CLI读取`current_stage/claims_real_runtime_success`的判断迁给declaration-owned result
projector。preflight成功仍为`0`，structured result缺失/invalid固定`2`，禁止fallback到旧summary。
`runtime_resume_result.json`仅由legacy Presentation adapter保留，不能成为machine result authority，也不由
future typed adapter创建。

##### 12.7.3.7 future adapter 与 frozen driver

当前没有 production caller 使用 C6.1 Build public API，也没有独立 future verification adapter。
B 的实际 migrated adapter不是整个`src/mod_agent/cli.py`，而只限当前`main`中的
`args.command == "preflight-runtime"`与`args.command == "resume-runtime"`两个command branch。实施时把它们
分别抽取为精确符号`_run_preflight_runtime_command`与`_run_resume_runtime_command`，`main`只负责dispatch；
这两个helper只能：

```text
prepare feature parameters
-> call public operation preflight/execute
-> present returned structured result
```

authority regression的扫描范围只覆盖上述两个exact helper symbol及以后由
`verification_operations.py`显式登记的future/migrated adapter qualified symbol；不得把整个`cli.py`或
其他command branch纳入本包禁令。对登记符号，禁止import/call`build_graph`、
`ArtifactStore.write/write_with_result`、`WorkflowCheckpointStore`、private identity/projection/hash，禁止读取
revision totals/pending/locator、`current_stage`或`claims_real_*`来判断终态，禁止自行选择retry/recovery。
`main`的两个dispatch branch只能传入`args`并返回helper的integer exit；其他CLI产品入口及其历史语义
不在C6迁移范围。已执行workspace driver形成冻结清单，保留path + SHA +正式引用，不运行、不修改、
不纳入future adapter gate。

##### 12.7.3.8 实施次序与删除/委托记录

1. 扩展 declaration 与七行 exact-shape parity；C6.4 hash compatibility先锁定；
2. 把 C6.1/C6.2/C6.3 identity projector迁到 declaration + neutral hasher；
3. public normalizer生成typed envelope；typed+legacy混用拒绝；
4. Graph只接收typed operation，删除三套 operation selector组合；
5. checkpoint接入typed dispatcher，private handoff删除两个 attempt bool；
6. 各executor/result mapper消费 declaration，default/retry/recovery改为structured result；
7. CLI降级为参数适配/Presentation；
8. 删除/委托 local_entry 中重复 identity JSON/hash、bool互斥、completion selector和terminal verdict分支；
   Graph/checkpoint/local_entry必须出现实质authority减少，不能只新增typed class后保留旧解释。

private helper、fixture与文件组织可在不改变本节 exact public contract时自主调整。若复用现有Graph node会
保留第二owner，可新增语义准确的private typed handler；它必须替换旧分支并净减少owner，不能形成平行
控制面。

##### 12.7.3.9 最低验收

1. 七行 declaration parity固定 exact variant/attempt/protocol/completion/side-effect/output/result；
2. 每个legacy execute组合及具备完整exact identity的legacy preflight只规范化为唯一typed envelope；
   invalid或typed+legacy混用在ResumeReport/Graph/Store/factory/process前零副作用拒绝；
   `legacy_advisory_preflight_v0`不得产生Envelope/hash/approved_by/自动resume_id，不得成为execute输入，
   并断言Graph、checkpoint consumption、ResumeReport/Store/factory/effect/Presentation调用次数均为0；
3. Graph、checkpoint、Store、semantic validator、result mapper中不存在四个legacy bool消费者；旧Graph
   selector不再是受支持current route；
4. C6.2/C6.3 legacy identity canonical bytes/hash与现有fixtures逐字相同；C6.4 identity/hash不变；
   C6.1 lineage preflight hash不变且新增action hash独立；
5. exact action/audit正负回归：Artifact/attempt/admission/side-effect/budget/version变→hash变；Store
   totals/stdout/time/locator/Presentation变→hash不变；
6. C6.1、C6.2、C6.3、C6.4、default、retry、recovery逐项 public→Graph→checkpoint/Store/result parity；
   初始新写一份ResumeReport，retry/recovery复用原report，C6.2在evidence后interrupt，C6.3直接terminal，
   C6.4只写一份RuntimeEvidence；
7. C5三态、failure stage、nullable refs/receipts、side-effect-started、handoff、retry/recovery矩阵不漂移；
8. unknown kind/version/shape、attempt/protocol/completion非法组合与TOCTOU在首个副作用前拒绝；
9. 对`_run_preflight_runtime_command`、`_run_resume_runtime_command`及显式登记future adapter的窄范围gate
   证明无Graph/Store/checkpoint/private hash/verdict/retry authority；真实CLI集成分别证明
   `legacy_advisory_preflight_v0`正常mapping/`LocalEntryError`为exit 0/2、exact preflight读取
   `VerificationOperationPreflightResultV1.preflight_status`、execute读取
   `VerificationOperationResultV1.execution_disposition`；`cli.py`其他command branch与frozen driver只读清单
   不被误伤；
10. typed及exact-identity legacy preflight success/failure固定为`VerificationOperationPreflightResultV1`，
    `legacy_advisory_preflight_v0`保持历史mapping/`LocalEntryError`且不得伪装为该result；execute
    success/failure固定为`VerificationOperationResultV1`；C6.1 `BuildResult committed + domain failed`的literal golden result必须为
    `completed/domain_blocked/failure_stage=null/handoff_ready=false`；所有common/variant重复兼容字段通过
    constructor负向测试证明不能漂移；unresolved authorization golden result证明identity/attempt均null且只用
    rejected variant，`identity_resolved` admission golden result证明Envelope/hash/attempt/operation variant均
    非空；C6.3及
    runtime-workflow literal failure-stage parity必须覆盖`blocked_report_execution`与`blocked_report_store`；
    真实missing/unreadable/hash-invalid checkpoint fixture必须分别证明preflight
    `declaration_resolved + Envelope/hash null`与execute expected gate已匹配后的
    `approved_identity_only + approved hash non-null`均能structured blocked且零副作用；
11. 现有 focused suite全量通过，并至少一条表驱动真实 public→Graph→checkpoint/Store integration覆盖七个
    shape。实施后回填 exact symbols、删除owner、normal/full-index diff、diff check与测试结果，再交独立
    审核页验收。

##### 12.7.3.10 工作包 B 实施记录（独立验收通过并已提交）

当前实施状态为 `implemented_independently_verified_and_committed`；独立审核页已对
`HEAD=6f415d00e008af4a933b32529e82481ad81547ee` 之上的唯一 staged 对象给出
`post_implementation_verdict=approved`，该对象已原样提交为
`349821cf10e70753bfa5818bf335824db8205694`。C6 工作包 B 与 C6 代码迁移据此完成；该结论不自动完成
C7、第二产品切片或后置 Authority 文档归并。

实际 authority 归属与退出结果：

- `src/mod_agent/verification_operations.py` 的 declaration、`project_verification_operation`、
  `project_verification_operation_result` 与 `project_rejected_verification_operation_result` 是 typed
  Envelope、Approval Identity 与 resolved/rejected machine result 的唯一公共解释源；
  `src/mod_agent/local_entry.py` 的四个 variant adapter只收集已经验证的variant facts并委托该projector，
  不再保存 `execution_disposition` 判断表。
- `src/mod_agent/artifacts/store.py::ArtifactWriteResult.from_dict` 是序列化C5 receipt回到typed machine fact的
  唯一严格parser；`local_entry` 不再使用 `bool(...)`、缺字段默认值或自建枚举解释Store终态。
- `src/mod_agent/local_entry.py::_execute_runtime_workflow_operation` 强制接收非空、已验证的
  `VerificationOperationEnvelope`；legacy default/retry/recovery只在outer execute normalizer中一次性形成
  exact Spec/Envelope，之后Graph、checkpoint、handoff、executor与result mapper不再以private
  `attempt_kind`字符串或旧runtime bool选择语义。
- identity-incomplete default/profile、observation-retry、accepted-resume-recovery preflight保持
  `legacy_advisory_preflight_v0`：只返回历史no-write mapping，不产生Envelope/hash/approved_by/自动resume_id，
  也不进入execute。typed preflight及C6.2/C6.3 exact-identity legacy preflight共同委托
  `VerificationOperationPreflightResultV1` projector。
- typed与legacy execute在任何Graph、Store probe、ResumeReport、factory/effect前汇入上述同一typed
  executor；执行后先固定一个`VerificationOperationResultV1`，legacy compatibility projection只从该
  machine result和既有事实投影。`runtime_resume_result.json`移到machine result之后；Presentation失败只抛
  携带同一machine result与非权威`audit_error`的`VerificationOperationPresentationError`。
- 已删除或降级的旧authority包括：optional `operation=None` executor、private `attempt_kind`路由输入、
  Graph旧runtime selector、`_verification_operation`私有字典传输、local disposition表、早于machine result的
  Presentation写入、C6.4全零hash/default semantic binding以及local宽松Store receipt重建。result中的
  `VerificationAttemptResultV1.attempt_kind`只保留为typed outcome fact，不再拥有路由权。
- `src/mod_agent/cli.py::_run_preflight_runtime_command`只调用identity-incomplete advisory surface并按历史
  exact status映射0/2；execution-grade preflight缺少structured section固定exit 2，execute仅读取公共
  `execution_disposition`。真实CLI测试不mock public函数，证明advisory调用无Graph/checkpoint/Store/effect/
  runtime Presentation副作用；CLI自己的纯显示不构成execution-side Presentation sink。
- C6.1–C6.4、default/retry/recovery的既有外部行为、Graph/checkpoint typed dispatch、C5三态和历史driver
  保持边界；本实施未新增Artifact、Approval或业务Graph类型，未执行Build、Runtime、GTFO或正式产品Store写入。
- 首次独立验收发现并已在原owner内修正三项反例：CLI advisory显式登记
  `READY_FOR_RUNTIME_PROFILE`与`READY_FOR_EXTERNAL_AUTHORIZATION`两个正常历史状态；
  `ArtifactWriteResult.from_dict`封闭committed/blocked-before-commit/partial的跨字段不变量；
  declaration-owned result validator要求每个output都有同role、同ref的committed C5 receipt，并按七种shape
  验证completed exact output chain。initial runtime workflow最小改用现有`resume_with_result()`，完整传递
  blocked/partial/committed三态；noncommitted在Graph/effect前停止，retry/recovery不产生新ResumeReport。
  合法terminal blocked链保留`EvalReport -> BlockedReport`，两个output各自绑定committed receipt。

唯一 staged identity与验证：

- staged files：12；stat：`10280 insertions / 2103 deletions`；
- normal binary diff：`566101 bytes`，
  `SHA256=87B24CE2F7D55FA0B1C234426846A28A502F7F3E4287B65ADD856427539CB31B`；
- full-index binary diff：`566893 bytes`，
  `SHA256=CFD1C40B92ACB5C5E8C8C42CD61110B117F59AD750FC1556F58DC5439FA66F07`；
- 相对首次被拒staged对象的修正delta在合入index前为8 files、`690 insertions / 8 deletions`；
  normal delta `35805 bytes / SHA256=21DC0DD473CC3CD4A6B39088E3EB0096CF75DF0E3B15C1A1CF11AEEA60AB85CF`；
  full-index delta `36333 bytes / SHA256=A0F9C447984823EA0D4590615CFFB74E1147FE0381730BFB13D1B8DD8E890138`；
- `git diff --cached --check`：通过；
- Python 3.10.20 `py_compile`覆盖六个生产模块与六个focused test模块：通过；
- focused命令：
  `python -B -m pytest tests/unit/test_verification_operation_contract.py tests/unit/test_verification_operation_checkpointing.py tests/unit/test_verification_operation_graph.py tests/unit/test_verification_operation_cli_adapter.py tests/unit/test_artifact_store.py tests/unit/test_verification_only_continuation.py tests/unit/test_workflow_graph.py -q -p no:cacheprovider`；
  结果：`385 passed in 130.63s`。

正式独立审核页已核对 staged bytes、authority_removed、兼容与fail-closed证据，并独立重跑同一
focused命令得到`385 passed in 132.18s`；批准对象已提交。进入C7前仍须保持tracked工作树干净，且
不得据此触发第二产品切片或后置Authority文档归并。

B 经独立合同审核、实施、独立验收与提交后，C6代码迁移可标为 complete；第二产品切片仍是跨产品复用
证据，不反向改变本包代码完成事实。C7继续作为迁移/验证规则，随后才进入后置Authority文档归并门。

##### 12.7.3.11 P1：七 shape 真实公共链集成矩阵

> **工作包状态**：`independently_verified_and_committed`；commit=
> `6f79b2557242d129104dc05b638f59f4b9c7f079`。
> **时间盒**：`started_at=2026-08-06T16:46:49+08:00`，目标两小时，绝对停止时间
> `2026-08-06T20:46:49+08:00`。该时间盒只覆盖P1 inventory、合同审核、bounded ordered-receipt owner修复、
> seven-row test实施、focused验证、
> checkpoint和实施后独立验收准备；不得跨入P2-P4。合同获独立审核`approved`前不得修改代码或测试。

###### 12.7.3.11.1 bounded owner/test inventory

当前生产owner已由C6B提交`349821cf10e70753bfa5818bf335824db8205694`统一；P1不创建新owner，但实施前
独立审核已在该owner中复现一条ordered receipt旁路，必须由同一owner修正：

- `src/mod_agent/verification_operations.py::_DECLARATIONS`、`resolve_verification_operation`、
  `project_verification_operation`与`project_verification_operation_result`分别拥有七shape的exact
  declaration、Envelope/Approval Identity和machine result；
- `src/mod_agent/local_entry.py::preflight_verification_only_build_continuation`、
  `execute_verification_only_build_continuation`、`preflight_local_runtime`与`resume_local_runtime`是本矩阵
  唯一允许调用的production public entries；矩阵不得直接调用private executor或`Graph.invoke`代替它们；
- `src/mod_agent/workflow/graph.py::build_graph`只消费exact `VerificationOperationEnvelope`并由declaration
  `graph_handler`决定route；测试允许用“记录后委托原函数”的spy证明真实Graph被创建/执行，但不得替换route、
  node结果或public function；
- `src/mod_agent/workflow/checkpointing.py::WorkflowCheckpointStore`拥有checkpoint/ResumeReport protocol；
  initial Build写WorkflowCheckpoint，initial Runtime写一份ResumeReport，retry/recovery只复用exact accepted
  ResumeReport；
- `src/mod_agent/artifacts/store.py::ArtifactStore.write_with_result`与`ArtifactWriteResult`继续唯一拥有C5
  commit receipt；矩阵使用`tmp_path`下真实filesystem Store，允许delegate spy记录exact write顺序，不得伪造
  receipt或按revision totals/latest alias/path推断机器终态；
- public effect仅使用既有`build_result_factory`/`runtime_evidence_factory`注入点和确定性本地fixture；factory可写
  `tmp_path`下测试输出，但不得执行产品Build、Runtime、GTFO、游戏目录写或正式ArtifactStore副作用。

现有测试证据是分散的：

- `tests/unit/test_verification_only_continuation.py`已有C6.1 public Build、C6.2 evidence-only、C6.3
  terminalization、C6.4 consolidation的真实公共链正向测试，并分别覆盖部分顺序、Store result与失败矩阵；
- `tests/unit/test_workflow_graph.py`已有default/retry/recovery legacy public行为与report复用测试，但没有用一张
  exact typed Envelope矩阵把三行和其余四行共同绑定到declaration-owned result；
- `tests/unit/test_verification_operation_graph.py`只证明七shape的declaration-owned Graph拓扑与旧selector
  不可用；`tests/unit/test_verification_operation_contract.py`证明shape解析、identity/result与部分receipt不变量，
  但没有锁定receipt的ordered语义；
- 独立审核用C6.2 completed事实复现：`outputs=(resume_report,runtime_evidence)`时，把两份committed
  `store_receipts`倒序为`(runtime_evidence,resume_report)`，当前
  `project_verification_operation_result`仍返回`completed/succeeded`。根因是
  `src/mod_agent/verification_operations.py::_validate_operation_result`把receipts转成role字典/set后比较，丢失
  execution order；这是真实production machine-contract旁路，不允许由矩阵只检查role集合掩盖；
- 因此P1的缺口由两部分组成：在现有declaration/result owner内闭合通用ordered receipt invariant；再用一条
  统一证据证明七行都由真实public entry进入、真实Graph运行、真实临时Store提交，并返回同一
  declaration-owned structured result。该修复不改变C5 Store事实、public schema、Graph或checkpoint。
- 按首次批准合同实施owner修复后，现有真实公共链回归`245`项得到`242 passed / 3 failed`，暴露第二个同域
  compatibility blocker：`src/mod_agent/local_entry.py::_terminalization_machine_result`按旧
  `output_artifact_roles=(blocked_report,eval_report,workflow_summary)` allowlist顺序收集receipt，因而把真实执行
  `EvalReport -> BlockedReport`投影成`blocked_report,eval_report`；同一旧顺序还由
  `_runtime_execution_machine_result`用于runtime-workflow terminal receipts。严格validator正确拒绝了该倒序，
  但三文件范围不足以保持既有合法terminal链。不得在validator中重排caller提交的receipts，否则会重新打开
  首轮C6.2倒序旁路。

###### 12.7.3.11.2 exact seven-row matrix

唯一表驱动测试逐行使用typed public调用。每行先调用对应public preflight取得可信Envelope/hash，再把该
Envelope和expected hash交给public execute；C6.1直接使用Build public pair，其余六行使用Runtime public pair。
准备前置Artifact可以通过已验证public链生成；前置准备结束后必须重置event/write counters，目标行的Graph、
Store和effect证据不得被准备步骤冒充。

| row / declaration shape | public entry pair | exact variant / attempt / protocol / completion | 目标行必须提交并返回的exact output roles | checkpoint/ResumeReport规则 | effect与Graph终点 |
|---|---|---|---|---|---|
| C6.1 `verification_build_initial` | `preflight_verification_only_build_continuation` → `execute_verification_only_build_continuation` | `VerificationBuildOperationV1` / `InitialAttemptV1` / `BuildInvocationProtocolBindingV1` / `build_handoff` | `build_result, workflow_checkpoint`，各自有同role、同ref、`committed` C5 receipt | 新写一份WorkflowCheckpoint；无ResumeReport | Build factory恰好1次；Graph使用`verification_build` handler并在handoff checkpoint后结束 |
| C6.2 `runtime_execution_initial_evidence_only` | `preflight_local_runtime` → `resume_local_runtime` | `RuntimeExecutionOperationV1` / `InitialAttemptV1` / `NewRuntimeResumeProtocolBindingV1` / `runtime_evidence_only` | `resume_report, runtime_evidence`及matching committed receipts | 新写一份accepted ResumeReport；不写terminal Artifact | Runtime factory恰好1次；Graph使用`runtime_execution` handler，在`collect_runtime_evidence`后interrupt/end |
| default `runtime_execution_initial_workflow` | 同Runtime pair | `RuntimeExecutionOperationV1` / `InitialAttemptV1` / `NewRuntimeResumeProtocolBindingV1` / `runtime_workflow` | 选用verified deterministic payload时为`resume_report, runtime_evidence, eval_report, workflow_summary`及matching committed receipts | 新写一份accepted ResumeReport | Runtime factory恰好1次；Graph继续进入existing evaluate/summary terminal chain |
| retry `runtime_execution_observation_retry` | 同Runtime pair | `RuntimeExecutionOperationV1` / `ObservationRetryAttemptV1` / `VerificationProtocolBinding` / `runtime_workflow` | 选用verified deterministic payload时为`runtime_evidence, eval_report, workflow_summary`及matching committed receipts；不得含`resume_report` | 绑定prior RuntimeEvidence、RepairPlan与exact accepted report；目标行前后ResumeReport revision数相同 | Runtime factory恰好1次；Graph执行current retry，不重复Build/checkpoint |
| recovery `runtime_execution_accepted_resume_recovery` | 同Runtime pair | `RuntimeExecutionOperationV1` / `AcceptedResumeRecoveryAttemptV1` / `VerificationProtocolBinding` / `runtime_workflow` | 选用verified deterministic payload时为`runtime_evidence, eval_report, workflow_summary`及matching committed receipts；不得含`resume_report` | 复用先前public initial attempt已committed而RuntimeEvidence尚未提交的accepted report；目标行不写第二份report | Runtime factory恰好1次；Graph恢复同一accepted attempt且不重复Build/checkpoint |
| C6.3 `runtime_terminalization_initial` | 同Runtime pair | `RuntimeTerminalizationOperationV1` / `InitialAttemptV1` / `VerificationProtocolBinding` / `terminal` | 选用verified committed RuntimeEvidence时为`eval_report, workflow_summary`及matching committed receipts | exact checkpoint/report作为protocol input，不写新checkpoint/report/RuntimeEvidence | Runtime factory/probe/process均0；Graph使用`runtime_terminalization` handler直接进入existing terminal nodes |
| C6.4 `runtime_evidence_consolidation_initial` | 同Runtime pair | `EvidenceConsolidationOperationV1` / `VerificationAttemptPolicy(1,false,false)` / `VerificationProtocolBinding` / `runtime_evidence_consolidation` | 一份新`runtime_evidence`及matching committed receipt | exact checkpoint/report只作protocol binding；产品upstream仍为BuildResult、FeatureSpec、prior RuntimeEvidence、EvidencePack | Build/Runtime factory/probe/process均0；Graph使用`runtime_evidence_consolidation` handler，经trusted semantic precommit提交后interrupt/end |

###### 12.7.3.11.3 通用 ordered receipt invariant

`src/mod_agent/verification_operations.py::VerificationOperationDeclaration`新增exact frozen字段
`store_attempt_chains: tuple[tuple[str, ...], ...]`，是每个shape合法Store write branch/order的唯一owner。
七个declaration record逐项保存下表全部合法chain；`output_artifact_roles`只继续拥有role到ArtifactType的
allowlist，不再被解释为branch/order owner。`_validate_operation_result`只从resolved declaration的
`store_attempt_chains`验证full chain、committed prefix与noncommitted next role，不得新增全局shape-to-chain map、
按`shape_id`分支表或测试侧resolver。每个shape允许的ordered Store attempt链精确为：

| shape | allowed ordered attempt chain |
|---|---|
| C6.1 Build | `build_result`，或`build_result -> workflow_checkpoint`；前者是domain Build失败且不创建handoff时的完整合法chain，不是长链的completed prefix |
| C6.2 evidence-only | `resume_report -> runtime_evidence` |
| default initial workflow | `resume_report -> runtime_evidence -> blocked_report`，或`resume_report -> runtime_evidence -> eval_report -> blocked_report`，或`resume_report -> runtime_evidence -> eval_report -> workflow_summary` |
| retry/recovery workflow | 与default三条terminal分支相同，但去掉开头`resume_report` |
| C6.3 terminalization | `blocked_report`，或`eval_report -> blocked_report`，或`eval_report -> workflow_summary` |
| C6.4 consolidation | `runtime_evidence` |

`VerificationOperationDeclaration` constructor/contract validation必须保证：`store_attempt_chains`是非空tuple；
每条chain非空、内部role不重复，且每个role都存在于同一record的`output_artifact_roles`。contract test固定七个
declaration的exact `store_attempt_chains` golden tuple；七行public matrix只读取真实resolved declaration，
不得复制第二个runtime/terminal chain resolver。未来改变任何chain集合属于result contract变化，必须重新审核，
不能静默改表。新增字段只强制既有result order invariant，不进入Approval Identity projector、hash bytes或public
`VerificationOperationResultV1` schema。

declaration owner同时提供唯一internal order projector
`src/mod_agent/verification_operations.py::_ordered_store_attempt_roles(declaration, present_roles)`：它只从
`declaration.store_attempt_chains`把当前实际存在的Store role集合投影为唯一合法prefix order；无匹配或多个
不同order时fail-closed。`_project_variant_output_refs`与local compatibility adapter共同委托该helper，不能各自
重新实现set/prefix选择。`src/mod_agent/local_entry.py::_runtime_execution_machine_result`和
`_terminalization_machine_result`只负责收集已有typed `ArtifactWriteResult` projection，随后按该helper返回的
role tuple传给现有`_verification_store_receipts`；它们不得按`output_artifact_roles`、`shape_id`或本地terminal
条件表决定顺序。最终`_validate_operation_result`仍验证收到的receipt顺序，绝不替caller自动纠正倒序事实。

通用验证规则固定为：

1. `outputs`只表示本attempt已经committed的Artifact，并按上述实际write chain排序；completed结果必须等于该
   shape/domain branch的一条完整合法链；blocked/partial在Store链完成前停止时只能是某条合法链的committed
   prefix；
2. 每个committed receipt必须与同位置output逐项同role、同`ArtifactRef`；因此committed receipt role tuple
   必须逐字等于output role tuple，不能只比较集合；
3. 若存在本attempt的noncommitted `ArtifactWriteResult`，只能有一个且只能是最后一个receipt；它之前的
   committed receipts仍须与outputs形成同序prefix，它的role必须是所选合法attempt chain的下一个role；
   noncommitted后不得继续任何receipt，倒序或跳过前序role均fail-closed；
4. 没有Store调用的execution failure可在任意合法committed prefix后停止并只携带该prefix receipts；不得伪造
   “下一个Store失败”receipt；
5. C5三态、ref/nullability、recovery字段继续只由`ArtifactWriteResult.from_dict`解释；operation result validator
   只校验receipt在operation write chain中的order/role/ref，不复制C5字段规则；
6. serialization回归必须把receipt projection逐项交给Store-owned `ArtifactWriteResult.from_dict`恢复，再进入
   同一`project_verification_operation_result`/`VerificationOperationResultV1` validator；不得新增第二个
   operation-result parser或单独的order表。

合法terminal `EvalReport -> BlockedReport`必须保持接受，反序必须拒绝。上述规则同时适用于completed、blocked
与partial，不做C6.2专用特判。

###### 12.7.3.11.4 exact matrix assertions

每行必须另外逐字断言：

1. preflight为`VerificationOperationPreflightResultV1`且`preflight_status=ready`、
   `identity_resolution_status=identity_resolved`；execute为`VerificationOperationResultV1`；并逐字证明
   `preflight.approval_identity_hash == preflight.envelope.approval_identity_hash ==
   execute.approval_identity_hash == expected_approval_identity_hash`，不得只证明caller传了一个expected值；
2. `operation_kind`、`operation_contract_version`、variant类型、attempt类型、protocol类型、completion scope与
   `_DECLARATIONS`中该`shape_id`精确一致，不能在测试复制另一个resolver；
3. `platform_status=completed`、`failure_stage=null`；`execution_disposition`与variant domain facts一致；
4. `tuple(output.role)`与`tuple(receipt.role)`按12.7.3.11.3的ordered chain逐项相同；每个receipt由
   Store-owned typed `ArtifactWriteResult`给出`outcome=committed`且同位置`artifact_ref`与output相同；
5. Graph delegate spy收到的exact Envelope逐字等于`preflight.envelope`，declaration `graph_handler`与该行
   一致，并至少一次执行该handler的
   真实START/route；不得传旧selector、private `attempt_kind`或runtime bool到Graph；
6. Store delegate spy至少观察到该行全部expected writes，顺序满足上表；不把Store totals、`current_stage`、
   latest alias或Presentation字段作为status/disposition判断输入；
7. typed path不创建legacy `runtime_resume_result.json`，其缺失不能改变machine result；
8. factory count、Graph count、新增ResumeReport/WorkflowCheckpoint数量与上表逐行一致。

###### 12.7.3.11.5 adjacent fail-closed gates

P1不复制第二张identity/result规则表。矩阵的focused集合必须继续执行并明确引用以下现有authority gates：

- `test_unregistered_shape_and_checkpoint_context_fail_closed`：unknown/mixed exact shape在public effect前拒绝；
- `test_graph_api_has_no_legacy_c6_selector_parameters`与
  `test_typed_operation_rejects_generic_route_authority`：旧Graph selector/通用route override不可旁路declaration；
- `test_completed_c6_2_requires_runtime_outputs_and_committed_receipts`与
  `test_completed_result_shapes_require_their_exact_committed_chains`：output/receipt不一致和缺失committed chain
  由declaration result owner fail-closed；
- ordered receipt新门必须覆盖：C6.2 completed receipts倒序拒绝；terminal合法
  `eval_report -> blocked_report`接受且反序拒绝；committed prefix + 最后一个noncommitted接受；noncommitted
  后继续、跳role或倒序拒绝；Store-owned receipt serialization round-trip后同样拒绝order drift；
- `_ordered_store_attempt_roles`必须覆盖三类projector边界：C6.3
  `present_roles=(eval_report,)`同时匹配`eval_report -> blocked_report`与
  `eval_report -> workflow_summary`时，因两个projected prefix都精确为`(eval_report,)`而接受；无任何合法prefix
  匹配的impossible role set拒绝；synthetic declaration中相同present role set产生两个不同projected order时
  以歧义拒绝；
- local_entry三个已复现terminal compatibility回归必须恢复通过，同时外部caller直接传入倒序receipt仍由
  `_validate_operation_result`拒绝，证明adapter projection没有变成validator自动纠错；
- 现有typed+legacy混用、expected hash mismatch与TOCTOU测试继续证明首个Graph/Store/effect前零业务写拒绝。

若新矩阵发现超出本节已登记ordered-receipt owner修复的additional production bypass，P1立即停在
`contract_blocked_by_additional_observed_production_bypass`，记录exact反例和最小生产修复范围并重新送合同
审核；不得扩大当前四个允许文件或顺手修其他production owner。

本次真实七行矩阵首次执行已触发该停止门。精确反例为：typed C6.1 Build preflight以
`VerificationOperationSpec`生成`identity_resolved/ready`的exact Envelope；execute接收同一Envelope与
matching expected approval hash，`build_graph(..., verification_operation=envelope)`也收到逐字相同对象；但
`execute_verification_only_build_continuation`构造Graph initial state时仍读取legacy public参数
`user_request`，typed调用中该参数按混用禁止规则为`None`，而没有读取
`envelope.variant_payload.user_request`。Graph START遂在factory、Store probe及业务Artifact写入前返回
`VERIFICATION_OPERATION_STATE_MISMATCH`，changed field=`user_request`。该事实证明typed Build execute尚未
完全从legacy identity输入退出；不能用测试补legacy参数，也不能放宽Graph TOCTOU gate。

最小合同修复范围仍在当前已批准四文件内，只允许
`src/mod_agent/local_entry.py::execute_verification_only_build_continuation`在typed normalization完成后，从
resolved Envelope/variant逐项提供Graph initial state的approved identity字段；legacy调用继续从同一次
outer normalizer形成的同一Envelope读取，不保留第二套输入选择。必须新增typed Build真实public回归，锁定
preflight Envelope、Graph Envelope与initial state的`run_id/request_id/user_request/target_domain/target_mod`
逐项一致，legacy参数不得补入typed调用，factory/Store顺序与既有结果矩阵不变。若修复需要第五个文件、公共
schema/API、Graph gate或identity bytes变化，继续停止而不得实施。

同次矩阵其余观测不构成额外production结论：C6.2、C6.3、C6.4三行已完成真实public链；default与
recovery typed preflight因测试fixture未生成default runtime所需的现有`run_manifest.json`而blocked；retry
seed因此未形成ResumeReport。它们只需在合同重新批准后修正测试前置事实，不改变production合同。

###### 12.7.3.11.6 实施范围、最低验收与停止门

- production修复只允许`src/mod_agent/verification_operations.py`，并且只闭合上述通用ordered receipt
  declaration/projector/validator；`src/mod_agent/local_entry.py`只允许修改
  `_runtime_execution_machine_result`、`_terminalization_machine_result`、
  `execute_verification_only_build_continuation`及对`_ordered_store_attempt_roles`的import/机械调用。前两个
  adapter只退出旧allowlist-order投影；Build execute只允许在typed/legacy normalization完成后，把Graph
  initial state的`run_id/request_id/user_request/target_domain/target_mod`逐项从validated Envelope的
  protocol/variant读取，不得改变其他控制流、failure matrix、factory/Store顺序；相邻owner回归只允许
  `tests/unit/test_verification_operation_contract.py`；七行矩阵与既有真实terminal compatibility回归只允许
  `tests/unit/test_verification_only_continuation.py`。private fixture/spy组织不进入公共合同，但不得mock或替换
  四个production public functions，不得direct `Graph.invoke`作为目标行；
- 禁止触碰local_entry中上述两个machine-result adapter与该Build execute窄投影以外的符号、Graph、
  checkpoint、ArtifactStore/C5、
  public result schema、Approval Identity、Artifact/Graph类型或P2-P4。若上述四文件不足以保持既有合法failure
  matrix，停止并回传exact compatibility blocker，不扩大实现；
- 新增exact一张参数化七行矩阵；已有分散测试保留，不为统一矩阵删除失败注入或降低断言；
- focused命令至少覆盖：
  `tests/unit/test_verification_only_continuation.py`、
  `tests/unit/test_verification_operation_contract.py`、
  `tests/unit/test_verification_operation_graph.py`、
  `tests/unit/test_verification_operation_checkpointing.py`、
  `tests/unit/test_artifact_store.py`；可加入`tests/unit/test_workflow_graph.py`验证既有legacy兼容，但不得以该文件的
  direct Graph测试替代七行矩阵；
- 验收前运行Python parse/compile、上述focused pytest、`git diff --cached --check`，形成唯一staged identity并
  回填test name、七行结果、命令/通过数、normal/full-index bytes+SHA、stat和共享文档SHA；
- 独立审核必须从真实test参数表确认七行逐项执行，而不是单个测试名中包含“seven”；至少抽查一行initial
  Runtime、一行retry/recovery和一行Store-only，确认public function未被mock且真实tmp Store产生matching
  committed receipts；
- `post_implementation_verdict=approved`后才可提交。提交后P1只标记
  `independently_verified_and_committed`并停止；P2-P4、产品Build/Runtime、正式Store、第二产品切片和后置
  Authority文档归并继续保持未开始。

###### 12.7.3.11.7 实施回填与最终checkpoint

- declaration owner新增并拥有`VerificationOperationDeclaration.store_attempt_chains`；七shape的合法ordered
  Store branch全部保存在各自declaration。`output_artifact_roles`只保留role/type allowlist；
  `_ordered_store_attempt_roles`是present Store facts投影为declaration chain顺序的唯一helper，shared prefix产生
  同一tuple时接受、无匹配或不同projected order时拒绝。
- `_validate_operation_result`逐项验证outputs与committed receipt prefix同序、同role、同ref；只允许一个最终
  noncommitted receipt，且完整receipt tuple必须是resolved declaration chain的prefix。外部caller倒序不被
  helper或validator纠正；Store-owned strict parser仍是receipt machine fact的唯一解释源。
- local compatibility adapter仅收集已有trusted Store projections，再委托上述helper；terminal
  EvalReport→BlockedReport与EvalReport→WorkflowSummary的真实顺序恢复。typed Build execute的Graph initial
  state五字段全部来自validated Envelope protocol/variant，已删除typed路径读取legacy `user_request`的旁路；
  Graph TOCTOU gate、factory/Store顺序与result matrix未改变。
- `test_seven_shape_public_operation_matrix_uses_exact_typed_chain`有七个parameter row，分别实际执行C6.1、C6.2、
  default initial、observation retry、accepted-resume recovery、C6.3、C6.4。每行目标调用均从真实production
  public entry进入；public function未被mock；preflight hash、Envelope hash、expected hash、execute result hash
  逐字相同；local `build_graph` delegate收到exact preflight Envelope；真实tmp filesystem
  `ArtifactStore.write_with_result`产生与outputs同序、同role、同ref的committed C5 receipts。initial Runtime各
  新写一份ResumeReport；retry/recovery复用既有accepted report且目标attempt不新写report；Build/Runtime
  deterministic test factory均恰好一次，terminal/consolidation为零。retry的既有observation-failure前置事实
  复用已验证test helper，只用于准备immutable checkpoint/report/RuntimeEvidence/RepairPlan；矩阵目标行仍只
  经public preflight/execute进入Graph和Store。
- recovery前置不再直接调用checkpoint resume：测试先通过真实typed initial public preflight/execute，
  在ResumeReport committed后由deterministic factory异常停在`runtime_execution`，逐项确认无RuntimeEvidence，
  再让目标recovery行复用该exact accepted report；目标Graph/Store/effect计数在前置完成后重新开始。
- 七行逐项断言resolved declaration的exact `graph_handler`；Build行以record-and-delegate spy确认
  `create_initial_state`收到的`run_id/request_id/user_request/target_domain/target_mod`逐项来自preflight
  Envelope；所有typed target均确认不创建`runtime_resume_result.json`。
- 最终精确验证命令：
  `python -B -m py_compile src/mod_agent/verification_operations.py src/mod_agent/local_entry.py tests/unit/test_verification_operation_contract.py tests/unit/test_verification_only_continuation.py`；
  `python -B -m pytest tests/unit/test_verification_only_continuation.py tests/unit/test_verification_operation_contract.py tests/unit/test_verification_operation_graph.py tests/unit/test_verification_operation_checkpointing.py tests/unit/test_artifact_store.py tests/unit/test_workflow_graph.py -q -p no:cacheprovider`；
  修正后结果`379 passed in 123.72s`；七行矩阵单独结果`7 passed in 6.98s`；测试后staged identity未漂移。
- 唯一staged identity基于HEAD`9527d4046f13833a44237a8159d3d1062540f1ce`：四文件，
  `1011 insertions / 31 deletions`；normal binary diff=`50,246 bytes` / SHA256
  `E3E6921A1F4C7DA1167163E82FCAE91E89D0C1E98141A77BCB299B5F4323DA54`；full-index binary
  diff=`50,510 bytes` / SHA256
  `ACBAC22E3C5062A5E930154DF6DE831FEFD2BD0D811081825BE53C15D78CB892`；
  `git diff --cached --check`通过，无tracked unstaged，只有两份既有用户文档untracked。
- production触碰仅`verification_operations.py`与已批准的`local_entry.py`三个精确符号；测试仅两个登记文件。
  未改变public schema/API、Approval Identity bytes、Graph/checkpoint/ArtifactStore/C5、Artifact/Graph类型、产品
  Build/Runtime或P2-P4。独立复验结果为`post_implementation_verdict=approved`；矩阵独立重跑
  `7 passed in 7.23s`，focused suite独立重跑`379 passed in 124.19s`。当前对象已提交为
  `6f79b2557242d129104dc05b638f59f4b9c7f079`；P1=`independently_verified_and_committed`，停止在P2之前。

#### 12.7.4 文档当前状态 override

- §12.5/§12.6 中把 `runtime_evidence_only`、`runtime_terminalization_only` 描述为内部operation
  authority的文字，只是C6.2/C6.3已提交实现的历史快照；当前目标合同以12.7.2/12.7.3为准：
  它们迁移后只能是public compatibility参数。
- §10.5/§10.6、§11.3、§13中关于“C2–C6 unchanged/not implemented”“C4/C6未完成”的文字
  只解释其各自工作包当时状态。当前checkpoint为：C1、C2+C3、C5、historical-v1 compatibility、
  immutable-upstream admission、C6.1、C6.2、C6.3已提交；C6.4=`implemented_and_independently_verified`
  且commit=`6f415d00e008af4a933b32529e82481ad81547ee`；C6工作包B及C6代码迁移=
  `implemented_independently_verified_and_committed`，commit=
  `349821cf10e70753bfa5818bf335824db8205694`。该状态只表示C6 typed operation authority与核心代码
  迁移已经提交；C6完成验收仍等待§12.7.3.9要求的七shape真实公共链矩阵，以及Build生产adapter
  对既有public Build API的实际采用证明。`run_local_request()`与两个Evidence CLI不反向归入C6B，
  它们登记为C7/platform active-entry inventory缺口。
- §11.3 中 C5 primitive 已完成，Build/Runtime public primitive与typed核心迁移已由C6覆盖，但Build
  生产adapter采用证明仍开放；Edit Authority完整审核链采用由§11.5重新打开。Store success、
  Build/Runtime/product success继续明确“不等于”。
- §15完成门追加：C6.1–C6.4及现有default/retry/recovery execute内部使用同一typed contract family；旧bool
  仅在最外层选择`legacy_advisory_preflight_v0`兼容表面或execute normalizer；advisory没有hash、route、Store、
  effect或verdict authority，不算第二控制面；Store pending前经trusted semantic binding完成最终enforcement；artifacts/store
  层不反向依赖workflow/feature模块；历史driver只读且不再拥有execution authority。
- 12.7.3工作包B当前为`implemented_independently_verified_and_committed`；C6 typed operation authority与
  核心代码迁移已经提交，但上述两项C6完成证据仍开放。
  C7曾在当时的bounded inventory下标记为`unchanged_confirmed_and_independently_verified`；后续完整
  active-entry inventory确认Edit Authority protocol/materialization链尚未采用C5 structured result，故该
  “当前Stagger范围完成”结论已被后续事实覆盖。§11.5是第一个修复包，不是C7唯一剩余完成条件；
  七shape真实公共链、Build adapter adoption、两个Evidence CLI、`run_local_request()`与按真实公共入口
  重做的平台级inventory均不得因§11.5完成而自动关闭。当前
  `C1_to_C7_current_stagger_scope=completion_reopened_by_active_entry_and_adoption_gaps`、
  `second_product_slice_cross_product_reuse=not_executed`，
  `post_consolidation_authority_document_reconciliation_and_independent_audit=not_started`。本状态不授权
  第二产品切片或后置Authority文档归并，也不证明全平台所有owner或跨产品复用均已完成。
- “不新增public entry/Graph node”是迁移期默认复用原则，不是永久禁令；只有实际净减少owner、
  保持兼容且不形成平行控制面时才可调整，并须在对应工作包合同中审核。

## 13. C7 — 迁移顺序与停止条件

> **当前迁移规则 override**：本章的早期步骤和“remaining”只保留历史排序价值；当前完成状态
> 以 12.7.4 为准。以下“默认暂停新增 public entry/Graph node”是减少平行控制面的中性偏好，
> 不是永久禁令：只有新结构替换旧 authority、净减少 semantic owner、保持受支持兼容并通过
> authority regression 时才允许调整；仅新增平行 handler/route 不允许。

### Step 0 — 控制新增复杂度

在公共合同仍未确定的领域，默认暂停以下扩张方式；若它是实现目标所必需的选择，推进页把
理由、替代方案和回收计划填入实施合同，由同一工作包审核：

- 新增大型 run-local executor；
- 在 feature workspace 新增 Store validator；
- 新增 outer projection 体系；
- 现有 public entry 可泛化时新增 capability-specific public entry；
- 新增 Graph/controller hierarchy；
- 直接删除已执行 driver 或 immutable Artifact。

### Step 1 — ownership inventory 与 characterization tests

从实际代码逐项列出：

- schema/projection-kind check；
- public-entry admission；
- Graph route；
- materializer dispatch；
- Approval canonicalization；
- freshness check；
- Store write/read-back interpretation；
- checkpoint/resume binding；
- retry/replay/recovery decision；
- driver-local duplicate。

退出门：

- 每项重复 authority/execution invariant 都有一个目标 owner；
- 没有当前行为只由文档推断。

### Step 2 — 建立统一 capability declaration

优先迁移已经实现的：

- verification-only continuation；
- bounded observation authority。

public entry、Graph admission、materializer 和 tests 必须共同读取一份 declaration。

退出门：

- 不会因 duplicate allowlist 出现 Graph 接受但 public entry 拒绝；
- unsupported combination 在所有公共边界一致 fail-closed；
- 没有为 feature instance 新建 public entry。

### Step 3 — 拆分 Approval Identity 与 audit snapshot

为新 Request 定义 canonical Approval Identity；历史 Request/Approval 保持 immutable。

退出门：

- Store totals、stdout formatting、line ending、Presentation 变化不改变 Approval Identity；
- input Artifact、source/diff、lineage、action、side-effect、budget、capability version
  变化会改变 Approval Identity。

### Step 4 — 建立权威 Store/public-executor result

把 revision、alias、pending、partial failure 和 terminal-write interpretation 收回公共边界，
同时保持旧 Store caller 兼容。

退出门：

- 不会因 alias/revision path 不同把 successful commit 报成 failure；
- partial outcome 不会报 full success；
- driver 不再决定 commit status；
- recovery availability 不等于 recovery authority。

### Step 5 — 迁移 Build 与 Runtime public continuation

把 verification-only Build/Runtime driver 中的 shared identity、admission、retry、checkpoint、
process、restoration 和 result handling 迁入公共层。

退出门：

- verification-only Build 有稳定 public entry；
- Build output 可以进入 public Runtime continuation，不伪造历史 `run_manifest.json`；
- Graph admission 先于 Build/Runtime side effect；
- one-shot/failure semantics 由公共执行器强制。

### Step 6 — 迁移 evidence consolidation 与 authority driver

把 C4 consolidation、bounded observation authority 中的公共 Graph/Store/projection 逻辑移出
driver，仅保留 feature-specific evidence、Criterion、source、marker、Binding 参数。

退出门：

- bounded observation 复用现有 public authority entry；
- Approval→Evidence→Plan 的公共写入不再被 feature materializer 重复实现；
- 历史 ID 只用于 uniqueness，不进入新 durable lineage。

### Step 7 — 删除未引用影子控制面

只删除已经达到 public-path parity 的未执行、无正式引用代码。

退出门：

- 被删除文件不被 immutable Artifact、approved Request、checkpoint、receipt 或 current test 引用；
- 回滚依赖 version control 和已保留的历史 Artifact；
- public integration suite 通过。

### Step 8 — 第二个真实产品切片复用验证

第二个产品切片必须复用：

- capability declaration；
- public entry；
- StateGraph；
- Store semantics；
- Approval Identity；
- Receipt boundary。

允许新增的只有 product-specific：

- FeatureSpec；
- evidence adapter；
- Binding；
- Criterion；
- observer；
- Proposal data。

如果第二个切片仍需要平行 executor、authority schema 或 Store validator，说明公共合同尚未
完成，需要回到对应 C1–C6 合同表自查和修正。

### C7 历史 completion checkpoint（2026-08-05；当时独立验收通过，当前已被后续开放门覆盖）

> **当前状态修正（2026-08-06）**：本checkpoint的静态扫描与focused suite仍可作为C6 typed operation
> 迁移证据，但其inventory没有覆盖Edit Authority完整公共链对C5 `ArtifactWriteResult`的采用，也没有验证
> Step 6登记的Approval→Evidence→Plan/Binding多写partial-chain结果。因此它不能继续证明当前Stagger
> 范围全部完成。§11.5是Edit Authority缺口的当前有效实施合同，但不是C7唯一剩余完成条件；七shape
> 真实公共链、Build生产adapter采用、两个Evidence CLI、`run_local_request()`以及按真实入口重做的
> platform inventory仍分别开放。C7状态为`completion_reopened`，整体Control Plane Consolidation保持
> `partial`，且§11.5完成后不得自动恢复complete。

本轮C7从`2026-08-05 19:17 +08:00`开始，受用户明确的60分钟硬时间盒约束。bounded inventory和
联合focused authority suite没有发现需要改变公共schema/API、Approval/Store/C5终态、Graph拓扑或
历史兼容的缺口，因此C7代码与测试变更均为`none`。唯一独立审核页已给出
`post_implementation_verdict=approved`，C7结论为`unchanged_confirmed_and_independently_verified`。
这不是为C7编号补造代码，也不重新打开C1–C6。

当前真实迁移链与commit checkpoint：

- C1 capability authority：`de8e4d683257333857df07d7d6237ddddd93f0ef`；
- C2+C3 Approval Identity/hash分层：`7ed68f4709abc558382ce728b4ee1627d18e17c1`；
- C5 Store machine result：`1485ed43430fccce8753f221304c7fe08da7c146`；
- historical v1 capability compatibility：`9bb6d019e11419c86bd058d98b5c8de854680f4c`；
- C4 immutable upstream admission：`dac15ca17db595ffff7ea4a0949f8d80accd0415`；
- C6.1 public Build continuation：`7a6209abeeb3bac3748828d60f62e3e15443449f`；
- C6.2 public RuntimeEvidence continuation：`23c35ac4b9888b170f7e5cab01faa59f5a5eb09b`；
- C6.3 public terminal continuation：`18d1849162ecba3df0ce9d22f9ab7f43ad144a0a`；
- C6.4 evidence consolidation authority：`6f415d00e008af4a933b32529e82481ad81547ee`；
- C6B typed operation authority收敛：`349821cf10e70753bfa5818bf335824db8205694`。

C7 completion evidence：

1. `edit_authority_capabilities.py`、`action_identity.py`、`ArtifactStore`/`ArtifactWriteResult`、immutable
   envelope upstream refs、`verification_operations.py` declaration/result projector分别保持C1–C6已验收的
   单一owner边界；C7没有创建新owner。
2. 对`workflow/graph.py`、`workflow/checkpointing.py`、`artifacts/store.py`、`artifacts/registry.py`
   的精确静态扫描中，`runtime_evidence_only`、`runtime_terminalization_only`、
   `runtime_evidence_consolidation_only`命中为0；对private handoff/Graph/checkpoint的`attempt_kind`
   路由命中为0。旧bool只保留在public/CLI compatibility boundary，typed result中的`attempt_kind`仅为
   受声明约束的attempt事实，不是private route authority。
3. 现有workspace drivers属于已执行、被历史Artifact/checkpoint或正式审计记录引用的冻结证据；本轮不删除、
   不修改，也不把它们重新解释为当前public execution authority。bounded inventory未发现满足Step 7
   “未执行、无正式引用且已达到public parity”条件的影子控制面。
4. 精确联合命令：
   `python -B -m pytest tests/unit/test_edit_authority_capabilities.py tests/unit/test_stagger_edit_authority.py tests/unit/test_artifact_store.py tests/unit/test_verification_operation_contract.py tests/unit/test_verification_operation_checkpointing.py tests/unit/test_verification_operation_graph.py tests/unit/test_verification_operation_cli_adapter.py tests/unit/test_verification_only_continuation.py tests/unit/test_workflow_graph.py -q -p no:cacheprovider`；
   结果为`440 passed in 127.29s`。测试覆盖Approval Identity正负边界、capability owner不可旁路、Store三态与
   immutable upstream、typed Graph/checkpoint dispatch、legacy/typed汇流、CLI/Presentation、C5 receipt和
   真实public→Graph→checkpoint/resume→Store/result链。
5. 运行后`HEAD=349821cf10e70753bfa5818bf335824db8205694`，tracked工作树干净；仅两份既有用户文档保持
   untracked。未执行产品Build/Runtime、GTFO、游戏目录或正式产品ArtifactStore写入。

独立审核页复算相同文档与commit链、重复完成authority扫描，并重跑相同精确命令得到
`440 passed in 131.88s`；测试后HEAD与Git状态不变。

明确限制：用户本轮排除了Step 8第二产品切片，所以本checkpoint不证明跨产品复用；不触发或实施
`REPAIR_AGENT_PLATFORM_CONTINUOUS_PAGE_AUTHORITY.md`归并与后置独立审核。当前精确状态为：
`C1_to_C7_current_stagger_scope=completion_reopened_by_active_entry_and_adoption_gaps`、
`second_product_slice_cross_product_reuse=not_executed`、
`post_consolidation_authority_document_reconciliation_and_independent_audit=not_started`。
`unresolved_contract_decisions=[]`。

### C7 实施合同表：迁移、实施与停止条件（C1历史工作包快照）

每次只启用一个主要 semantic goal。推进页自行拆解开发步骤；本表记录公共决策和验收证据，
不充当逐函数任务清单。

> **历史快照，不是当前checkpoint**：C1 Step 2 已由独立实施后验收批准并提交为 `de8e4d6`；
> 下表审核列中的“实施后验收 pending”为提交前历史快照。C2–C6 仍为 unchanged，
> 整体 Control Plane Consolidation 仍是 partial，未触发
> `post_consolidation_authority_document_reconciliation_and_independent_audit`。

| 工作包项 | 推进页决策 | 审核页复核 | 实施与验收回填 |
| --- | --- | --- | --- |
| semantic goal | 完成 C1 Step 2：五种现有 Stagger Edit Authority capability 由一份 declaration 供 public entry、Graph、materializer 和 tests 共用，bounded observation 不再是 Graph-only capability。 | `合同修订后独立复核：approved；实施后验收 pending。` | 已完成并由 5-key parity 与 bounded 真实公共链测试证明。 |
| control items | 主项 C1；C7 仅约束本包迁移顺序与测试门。C2 Approval Identity、C3 hash/projection、C4 lineage、C5 Receipt、C6 driver migration 均 unchanged。 | `合同修订后独立复核：approved；实施后验收 pending。` | 实际变更只覆盖 C1 owner migration 与 C7 测试门；C2–C6 未实施。 |
| current authority summary | 见 §7.4：`local_entry.py`、`workflow/graph.py`、`runtime/stagger_edit_authority.py` 分别维护互不完整的 schema/projection 解释。 | `合同修订后独立复核：approved；实施后验收 pending。` | 迁移前事实保留为历史基线；三个 consumer 已停止拥有 capability support 解释权。 |
| target authority summary | `src/mod_agent/edit_authority_capabilities.py` 是 capability support 和 schema evolution 的唯一 owner；public entry、Graph、materializer只消费 declaration 并保留各自执行职责。 | `合同修订后独立复核：approved；实施后验收 pending。` | 目标 owner 已生效；三个 consumer 均调用同一 exact resolver。 |
| contract changes | public API 签名、Request/Approval/Artifact schema、canonical hash、lineage、Store result、retry/checkpoint 均 unchanged。公共行为增加 generic 与 bounded observation 对现有 preflight 的支持、bounded 对现有 resume 的成功解释，以及 unsupported discriminator 的一致 fail-closed；新增 bounded public 成功状态字符串。 | `合同修订后独立复核：approved；实施后验收 pending。` | 仅上述公共行为变化；未新增 public entry、Graph branch、Artifact/Request/Approval 类型。 |
| removed authority | 三个 consumer 的独立 allowlist、action/output/terminal/freshness/dispatch 组合解释被删除或显式委托给 declaration；不删除历史 driver 或 Artifact。 | `合同修订后独立复核：approved；实施后验收 pending。` | capability consumer 的 Request discriminator 与 HUD Request/proposal 组合决策已改为 declaration 字段读取；Store 仅保留自身 Artifact-contract upstream validation 字面量。 |
| compatibility | 历史五类 Request 和 immutable Artifact 可读；原 generic registered-upstream 行为、四类专用 request-only 行为及所有既有 materialized payload 不变。回滚边界是本包代码提交；不迁移历史数据。 | `合同修订后独立复核：approved；实施后验收 pending。` | 322 项受影响回归通过；历史数据未修改；generic upstream 和专用 request-only 行为均有回归。 |
| expected touchpoints | `src/mod_agent/edit_authority_capabilities.py`、`src/mod_agent/local_entry.py`、`src/mod_agent/workflow/graph.py`、`src/mod_agent/runtime/stagger_edit_authority.py`、相关 unit/integration tests；内部测试 fixture 可按真实 Store 路径调整。 | `合同修订后独立复核：approved；实施后验收 pending。` | final staged diff 涉及上述四个生产文件及 `tests/unit/test_edit_authority_capabilities.py`、`tests/unit/test_stagger_edit_authority.py`、`tests/unit/test_workflow_graph.py`；无产品文件。普通 diff 为 99,134 bytes / SHA256 `C638B3A9B17C8D72E4B88E23BE557A8DD641BD6EB0E1AAD42F615A4C77A72F2B`；`--full-index` 为 99,596 bytes / SHA256 `B951C7C33AA4E42371CA0B8999E8E6602314CF5E4888F832879D6926E1521C55`。 |
| semantic boundary | may_change 与 must_remain_unchanged 以 §7.4 为准；本包不实施 C2–C6，不修改产品源码，不新增 Graph/Artifact/Approval/Request/public entry。 | `合同修订后独立复核：approved；实施后验收 pending。` | 越界检查通过；未触发重新合同审核条件。 |
| validation | §15.2 的 5–8、§15.7 的 26–29；新增五组合 declaration parity、unsupported 组合全类型零 revision delta、HUD Request/proposal schema mismatch 三层零写入门与 public operation 不可旁路回归；一条 bounded §15.8 真实 public path 集成测试；同时回归现有 Stagger authority、workflow graph、CLI 调用。 | `合同修订后独立复核：approved；实施后验收 pending。` | §15.2、§15.7 与 §15.8 的本包相关门均有 focused tests；精确命令与 322 passed 见 §7.4 validation。 |
| stop conditions | 只有实现需要改变 Request/Approval canonical identity、Artifact/Graph/public API 类型、lineage/freshness/Store/retry/recovery 语义，或无法保持五种历史 capability 行为时停止回到合同审核。普通 helper、fixture 和错误文本调整不停止。全部控制面完成后登记后置门 `post_consolidation_authority_document_reconciliation_and_independent_audit`，但本工作包完成不触发该门。 | `合同修订后独立复核：approved；实施后验收 pending。` | 未遇到合同级漂移；本包完成不触发后置 Authority 文档归并门，整体控制面状态仍为 partial。 |
| self-check/correction | 实施中先验证真实 Store/materializer 集成；若测试暴露 declaration 字段重复或缺失，在不改变上述 semantic boundary 的前提下自主调整内部类型与 helper，并在验收列记录。 | `合同修订后独立复核：approved；实施后验收 pending。` | 初次集成断言把非本 capability 的 BindingResolution 计入 preflight counts，已修正为按 declaration write types 核验；该调整未改变公共合同。 |
| unresolved_contract_decisions | `[]` | `合同修订后独立复核：approved；实施后验收 pending。` | `[]` |

## 14. 审核粒度分类

任何审核事实在影响 Approval 或阻断执行前，先完成语义分类。

| 事实 | 语义层 | 是否影响 Approval hash | 强制拥有者 |
| --- | --- | --- | --- |
| exact input Artifact/lineage | Approval Identity | 影响 | Authority canonicalization |
| source-before/exact diff | Approval Identity | 影响 | Authority canonicalization |
| side-effect boundary | Approval Identity | 影响 | Authority canonicalization |
| attempt budget | Approval Identity | 影响 | Authority canonicalization |
| Graph-before-Build/Runtime | Execution Invariant | 不影响 | public executor/Graph |
| retry/replay policy | Execution Invariant | 不影响 | public executor/Graph |
| checkpoint consumption | Execution Invariant | 不影响 | checkpoint/resume boundary |
| pending Store state | Execution Invariant + machine result | 不影响 | Store/public executor |
| produced revision/DLL hash | Machine Evidence | 不影响 | Store/BuildResult |
| allowed Artifact revision delta | Machine Evidence + invariant | 不影响 | public executor |
| Store total files/bytes | audit observation | 不影响 | machine-result diagnostics |
| raw stdout/stderr | 按声明用途归 Evidence/Observation | 不影响 | collector |
| human visual/audio report | Runtime/Product Observation | 不影响 | RuntimeEvidence provenance |
| path shortening/locator display | Presentation | 不影响 | UI/CLI |
| CRLF/LF/table layout | Presentation | 不影响 | UI/CLI |

若文本被程序精确解析，必须把解析后的 structured fact 提升到 Evidence/Observation contract；
外围格式仍属于 Presentation。

## 15. 必须通过的测试门

### 15.1 Approval Identity

1. audit snapshot 变化不改变 Approval Identity hash。
2. Presentation 变化不改变 Approval Identity hash。
3. exact input Artifact 变化会改变 Approval Identity hash。
4. source/diff、lineage、action、side-effect、budget、capability version 分别变化时，
   Approval Identity hash 都会变化。

### 15.2 capability ownership

5. supported Request 通过同一 declaration 被 public entry、Graph、materializer 接受。
6. unsupported schema/projection combination 在三处一致拒绝。
7. wrong schema + known projection kind 必须 fail-closed。
8. Graph-only capability 不能通过 public integration gate。

### 15.3 Execution Invariants

9. Graph admission 发生在 Build/Runtime side effect 前。
10. one-shot effect runner 不能被调用两次。
11. retry/replay/recovery 未获得合同和权限时不能发生。
12. unexpected Artifact type/source mutation fail-closed。
13. checkpoint/resume 保持 exact run、request、feature、Artifact refs。

### 15.4 Store/Receipt

14. immutable revision 与 latest alias 路径不同仍可解析为同一 logical Artifact。
15. committed、blocked-before-commit、partial outcome 可以区分。
16. pending marker 被报告但不会隐式 recover。
17. public structured result 不得与 Store outcome 冲突。
18. Store totals/stdout 变化不得使 approved action 失效。

### 15.5 lineage

19. child Artifact lineage 持久化为 exact `upstream_refs`。
20. checkpoint protocol refs 不替代 child Artifact lineage。
21. latest alias drift 不会偷换 approved exact input。
22. historical exact revision 保持可读，但不会自动成为 current authority。

### 15.6 driver downgrade

23. migrated driver 调用 public entry，不直接写 public route output。
24. driver 不维护独立 schema allowlist/Graph route。
25. driver 不能返回与 public structured result 冲突的 terminal status。

### 15.7 authority migration tests

26. 目标 owner 生效后，旧 owner 不能覆盖或旁路目标解释结果。
27. public entry、Graph 和 materializer 对同一 capability 读取相同声明来源。
28. 旧 allowlist、Store interpreter 或 driver verdict 已删除、不可达或显式委托给目标 owner。
29. 文件和符号仍存在时，测试证明它们只承担兼容或 adapter 职责。

### 15.8 真实公共路径集成测试

30. 至少一条真实测试执行：

```text
public entry
→ capability admission
→ StateGraph
→ checkpoint
→ resume
→ materializer/effect runner
→ ArtifactStore
→ structured machine result
```

该测试使用真实 Store alias、revision、pending、freshness 行为。只使用 stub 的正向测试不能
单独证明公共控制面已经完成迁移。

### 15.9 C6 typed operation 与 semantic precommit 完成门

31. C6.1–C6.4及当前default/retry/recovery execute的内部authority全部解析为同一个typed
    Verification Operation contract family；旧bool只允许在最外层选择`legacy_advisory_preflight_v0`
    compatibility surface或execute normalizer。advisory只拥有no-write准备观察，不拥有Approval Identity、
    Envelope/hash、route、Store、effect或execute verdict authority。
32. normalization之后，Graph、checkpoint、Store、semantic validator和result mapper不消费旧bool；
    advisory结果不得进入execute；未知kind/version/variant与typed+legacy混用均在副作用前拒绝。
33. Store 在 pending marker 前通过平台固定 trusted semantic binding 调用唯一 canonical owner；
    direct Store、public 与 Graph 路径不能旁路相同业务 invariant。
34. `src/mod_agent/artifacts` 与 Store 不反向依赖 workflow orchestration 或 feature adapter；Store只
    解释 Artifact contract、`ArtifactWriteIntent`、commit/conflict key与C5 machine outcome。
35. Approval/Action Identity 的 canonical serialization、domain separation 与hash由中立 owner负责；
    operation variant只声明 action projection，Observation/Presentation/物理locator不能传递污染身份。
36. migrated/future adapter只准备参数、调用public typed operation并展示structured result；历史driver
    bytes/hash只读保留，但不能继续build Graph、direct Store write、计算projection或覆盖terminal verdict。
37. 每个迁移包必须列出新增符号、删除/降级的旧owner、迁移前后authority对照和一条旧owner不可旁路
    的负向测试；只新增typed class而旧bool/解释器仍可达不算完成。

### 15.10 Edit Authority ordered structured result 完成门

38. 五种现有capability必须以同一`EditAuthorityReviewResultV1` projector解释完整
    WorkflowCheckpoint→ResumeReport→materialization链；Graph、public entry、materializer和CLI不得各自
    维护链级terminal status表。
39. `store_steps`必须是`capability.review_write_artifact_types`的合法有序前缀；role/type/feature必须精确
    一致，不得duplicate、skip或reorder。第一个noncommitted Store result必须是最后一个step，且失败后
    不得继续写后序Artifact。
40. `review_outcome`只能由同一次`resume_with_result()`的exact payload decision、trusted
    `ResumeDecision`与committed ResumeReport Store result共同产生。caller传入approve/reject但
    ResumeReport未committed时固定为`not_recorded`；不得伪造approved_by、resume_id或人类notes。
41. Resume failure优先级必须锁定：structured blocked decision+committed ResumeReport为
    `resume_validation`；同一decision的ResumeReport Store result为`blocked_before_commit|partial`时为
    `resume_report_store`；validation/payload construction异常且未调用Store时为`resume_validation`。
    Store失败覆盖原validation阶段归类，但不得把`review_outcome`改为approved/rejected。
42. committed reject必须返回`completed/rejected/not_applicable`并停止materialization；approve链任一
    后序失败必须保留所有已committed exact refs/receipts并返回partial/incomplete。只有实际Store调用
    才能产生`ArtifactWriteResult`，两次Store调用之间的异常不得伪造下一step Receipt。
43. `protocol_outputs`、`materialization_outputs`、commit/recovery booleans只能由同一canonical
    `store_steps` projector派生；existing-binding复用的既有EvidencePack/ImplementationPlan不得冒充本次
    committed output。
44. ephemeral `edit_authority_review_result`不得进入WorkflowCheckpoint payload/hash、Artifact hash或
    Approval Identity；audit、revision totals、latest alias、stdout和Presentation变化不得改变machine
    result。
45. 全部required writes committed后，legacy/audit/JSON/stdout/CLI Presentation失败不得推翻
    `completed` machine truth；若抛`EditAuthorityPresentationError`，必须携带同一冻结result。
46. CLI必须通过真实public entry覆盖五种capability，尤其bounded approved success必须exit 0；reject、
    blocked与partial必须exit 2。验收还必须覆盖checkpoint/resume及Approval/Evidence/Plan/Binding各位置的
    Store三态、调用间异常、零后续写和exact receipt/ref保留。
47. structured blocked decision且ResumeReport committed时，projector必须返回
    `blocked/not_recorded/not_started/resume_validation`，保留真实committed protocol refs/receipts，
    materializer调用为0；不得因protocol writes committed而改写为partial或completed。
48. accepted approve ResumeReport committed后、首个EditAuthorityApproval Store调用前发生
    `store_preflight|materialization_validation`失败时，projector必须返回
    `partial/approved/incomplete`，保留checkpoint/report committed refs/receipts，不得伪造Approval
    `ArtifactWriteResult`，且所有后续Store调用为0。

### 15.11 当前全局开放完成门（不属于§11.5实施范围）

本节是当前状态登记，不是把多个开放项合并成一个实施包。每项必须独立完成真实owner inventory、
必要的有界合同审核、实施与验收；§11.5完成只关闭Edit Authority adoption，不自动关闭C6、C7或整体
Control Plane Consolidation。

```yaml
control_plane_semantic_gates:
  edit_authority_c5_structured_result_adoption:
    status: independently_verified_and_committed
    contract: section_11_5
    core_authority_migration: independently_verified_and_committed
    final_presentation_result_invariants: independently_verified_and_committed
  c6_seven_shape_real_public_integration_matrix:
    status: independently_verified_and_committed
    commit: 6f79b2557242d129104dc05b638f59f4b9c7f079
    required_path: public_entry_to_graph_to_checkpoint_or_store_to_structured_result
  build_production_adapter_adoption:
    status: pending_P2_2_run_local_request_migration
    existing_public_api: implemented
    distinct_active_adapter: none
    production_adapter_adoption: not_yet_proven
  run_local_request_authority_migration:
    status: contract_blocked_by_existing_typed_build_semantic_mismatch
  intelligent_evidence_request_authority_migration:
    status: contract_not_started
  evidence_request_authority_migration:
    status: contract_not_started
  active_entry_inventory_final_rerun:
    status: pending_preceding_migrations
    exact_surfaces:
      - cli
      - public_functions
      - mcp
      - http_api
      - mod_agent_dashboard
  active_driver_downgrade:
    status: partial
    required_end_state: parameter_preparation_then_public_entry_then_structured_result_presentation

engineering_product_validation_gates:
  full_repository_regression:
    status: not_proven
  controlled_real_product_build_runtime_regression:
    status: not_executed

overall_completion_gates:
  second_product_slice_cross_product_reuse:
    status: not_executed
  post_consolidation_authority_document_reconciliation_and_independent_audit:
    status: not_started
```

#### 15.11.1 P2.1 Build production adapter adoption inventory checkpoint

- 时间盒：`started_at=2026-08-06T19:02:11.8916024+08:00`，
  `hard_stop=2026-08-06T21:02:11.8916024+08:00`；只读inventory于时间盒开始后停止，未进入实施。
- `src/mod_agent/local_entry.py::preflight_verification_only_build_continuation`与
  `execute_verification_only_build_continuation`是已实现的typed Build public pair；非测试、非workspace生产代码
  当前调用者为零。
- `src/mod_agent/build/adapter.py::BuildAdapter.run_local`仅是低层Build effect adapter：它接收
  `BuildProfile`、runner与执行授权并返回`BuildResult`，不准备`VerificationOperationSpec/Envelope`、不调用
  typed public pair，也不展示`VerificationOperationResultV1`，因此不是独立production adoption对象。
- 唯一active产品链为CLI `run-request` → `run_local_request()` → nested `build_result_factory` →
  `BuildAdapter.run_local`；`run_local_request()`仍自行创建/调用Graph并解释结果，已由本节顺序单列为P2.2，
  不得在P2.1提前合并。
- `workspaces/stagger_verification_only_build_001/run_build.py`与
  `workspaces/stagger_formal_repair_build_001/run_build.py`均已有执行与Artifact/checkpoint引用，是冻结historical
  evidence；不修改bytes，也不把它们改称active adapter。CLI没有独立verification-only Build command；MCP将
  `run_build`列为不暴露的dangerous tool；当前HTTP/UI没有typed Build public caller。
- 独立审核结论：`inventory_verdict=confirmed`、
  `implementation_authorization=not_applicable_no_distinct_active_object`、production/test change均为none。
  P2.1只证明没有独立active对象，不证明生产采用；`build_production_adapter_adoption`保持
  `pending_P2_2_run_local_request_migration`，只有P2.2真实迁移后才能形成第一条production adoption证据。
- 本checkpoint不授权新造entry/adapter，不授权修改历史driver，也不启动P2.2。

#### 15.11.2 P2.2 `run_local_request()` authority migration inventory与合同blocker

> **状态**：`architecture_boundary_selected_option_b`；`implementation_authorization=not_granted`。
> **当前合同时间盒**：`started_at=2026-08-07T12:11:55.6636360+08:00`，
> `hard_stop=2026-08-07T14:11:55.6636360+08:00`。审核时间计入两小时；本节未授权代码或测试修改。
> 先前`2026-08-07T11:42:18.9161797+08:00` inventory已证明现有verification-only Build语义不匹配；
> 本轮在治理迁移commit `d37de0d82f2bdac263cdd9849e371b9d9aa6f58e`之后只继续合同设计，不沿用旧文档副本作为权威。
> **独立合同审核**：基于文档SHA256
> `272C744B6579F1D3E354713EFDBF542C6D48A3DDB78152227F305CF3F5AC952A`的结论为
> `contract_verdict=changes_required`、`blocker_verdict=confirmed`、
> `implementation_authorization=not_granted`。审核认可一次mutation Build边界、三action拆分和
> declaration-owned dispatcher主线，但要求先由用户明确批准same-invocation structural protocol或接受显式
> continuation approver造成的公共兼容变化；审核页与推进页都不得代替用户选择。
> **用户决定**：用户已明确批准按真实transition分层的structural protocol；不批准给全部continuation统一新增
> `approved_by`，也不允许用`source_disclosure_approval_id`、OS用户、checkpoint owner或固定字符串代填。
> 该决定只闭合authorization semantics；它不等于选择A的durable multi-operation边界。最新独立审核要求暂停
> §15.11.2.8–.11的局部修补，先按§15.11.2.13重选A/B架构边界；未完成用户选择与新合同独立`approved`前仍不授权
> 代码、测试、Store或index修改。
> **架构边界决定**：用户于2026-08-07明确选择§15.11.2.13的B，即same-invocation Public Product Executor over
> the existing StateGraph。该决定排除本阶段建设A的跨进程durable continuation平台，但不批准B实施；B的精确
> implementation contract仍须另行形成并通过独立审核。

##### 15.11.2.1 真实active调用链

1. CLI `run-request`调用`src/mod_agent/local_entry.py::run_local_request()`；入口先验证source disclosure、
   isolated write、Build与可选Runtime授权，绑定source revision/model identity，创建run-local workspace并执行
   baseline Build与可选compiled-artifact inspector。
2. `run_local_request()`配置真实evidence provider、patch generator、dry-run与isolated-apply factory、nested
   `build_result_factory`和可选Runtime factory；随后直接调用`build_graph()`、`create_initial_state()`与
   `graph.invoke()`。
3. 同一产品Graph依次拥有FeatureSpec、EvidencePack、ImplementationPlan、PatchProposal/review、dry-run、
   exact-diff approval、isolated apply、mutation Build及可选Runtime/evaluation/repair routing。Build factory在
   approved isolated apply之后调用`BuildAdapter.run_local()`。
4. mutation `_run_build`从`dry_run_result`与可选`isolated_apply_result`取得exact upstream refs，并把
   `input_execution_mode`设为真实`isolated_apply`/dry-run mode；Build失败可进入repair，成功可继续Runtime或
   Build handoff。
5. `run_local_request()`目前从Graph state的`current_stage`、`build_summary.claims_real_build_success`、
   `runtime_summary`与Artifact map构造产品summary；CLI又据Build/Runtime claims选择exit code。这些Build
   terminal解释是P2.2应退出的旧authority，但自然语言、evidence/proposal/review/diff approval/apply、
   isolated workspace、Build effect与CLI Presentation必须保持。

##### 15.11.2.2 现有typed Build public pair不能无损承载该Build

- 现有`VerificationBuildOperationV1`/`verification_build_v1`明确是no-mutation verification-only操作：
  exact inputs只有fresh FeatureSpec与EvidencePack；identity不绑定dry-run、isolated-apply、Proposal、Plan或
  approved diff；`preflight_verification_only_continuation`还要求EvidencePack
  `can_generate_patch=false`、`authoritative_for_patch=false`及唯一verification-only handoff blocker。
- `run_local_request()`的正常EvidencePack用于生成patch，真实Build发生在isolated apply之后；其mutation
  BuildResult lineage由`dry_run_result`与`isolated_apply_result`定义。把它投影为现有typed Build会丢失
  approved mutation/action lineage并改变Artifact identity。
- typed Graph在该operation下固定`input_execution_mode=verification_only`、upstreams=
  `(feature_spec,evidence_pack)`且Build后停止；当前产品链需要真实`isolated_apply` mode、Build失败→repair、
  Build成功→可选Runtime/evaluation。仅以`interrupt_before=["build"]`切开前置Graph并调用现有public pair，
  仍会改变上述lineage、failure routing和后续产品行为。

##### 15.11.2.3 已由真实lineage闭合的一次mutation Build表示边界

1. `ArtifactStore`当前mutation `build_result`写入合同只接受`dry_run_result`和可选
   `isolated_apply_result`，且拒绝verification-only lineage。`run_local_request()`正常写路径实际执行
   isolated apply，因此本入口的一次mutation Build exact inputs应为按角色固定顺序的
   `(dry_run_result_ref, isolated_apply_result_ref)`，两者都必须是同feature的exact immutable revision。
2. Approval/Action Identity不重复列举Plan、Proposal、Review或approved diff。唯一semantic resolver必须从
   两个immediate refs递归验证当前已有链：
   `isolated_apply_result -> (patch_proposal, proposal_review, dry_run_result)`、
   `dry_run_result -> (patch_proposal, proposal_review)`、
   `proposal_review -> patch_proposal`、
   `patch_proposal -> (implementation_plan, evidence_pack)`、
   `implementation_plan -> (feature_spec, evidence_pack)`。同一角色出现多个nearest revision、任何path/hash/
   feature/type漂移、dry-run与apply diff hash不一致、`exact_diff_approved != true`、
   `actual_write_performed != true`或`real_patch_applied != true`均在Build effect前fail-closed。
3. 一次mutation Build的versioned action projection只需绑定：两个immediate logical Artifact identities、
   run/request/feature、稳定Build profile语义（profile id、build system、命令argv、timeout、expected artifact
   relative roles）、`input_execution_mode=isolated_apply`、一次caller Build factory invocation、无自动retry/
   recovery。absolute workspace、stdout/stderr path、Store locator、timestamp和执行后Build observation不进入
   Approval Identity；它们由Execution Contract在Graph/effect前重验。
4. BuildResult继续按当前Store合同以上述两个immediate refs作为ordered durable upstream；不得改成
   FeatureSpec/EvidencePack upstream，也不得把transitive lineage提升成第二套直接upstream owner。
5. BuildResult Store必须使用C5 `write_with_result`并原样进入declaration-owned structured result：
   blocked-before-commit→blocked，partial→partial，committed domain failure→completed/domain-blocked，committed
   success→completed/succeeded。不得从revision totals、latest alias、文件存在或Build stdout重造Store truth。
6. 上述边界足以定义一个append-only、非verification-only的一次mutation Build action；它不得修改既有
   `verification_build_v1` identity/hash bytes、不得伪造verification-only EvidencePack，也不得放宽Graph或
   Store admission。此处只记录可表示边界，尚未授权新增operation kind/version或代码实现。

##### 15.11.2.4 仍未闭合的post-Build lifecycle与结果表示

1. compile-only success可由committed BuildResult结束。现有`WorkflowCheckpointStore`已经以真实mutation
   `dry_run_result + isolated_apply_result -> build_result`验证Build-stage ancestry、persisted exact diff、
   successful real Build与physical output bytes，因此successful mutation Build的checkpoint/lineage机制无需新
   Runtime controller或新Artifact类型，也不需要重放evidence/proposal/apply。但当前`run-request`/`run_local_request`
   没有`approved_by`或`resume_id`输入，而现有typed Runtime public contract要求两者；所以“该入口无损采用现有
   typed Runtime/terminalization”仍是public compatibility decision，不能把checkpoint机制支持误写成入口采用已验收。
2. Build failure不能由现有typed family无损接续。当前产品Graph把failed mutation Build路由到
   `create_repair_plan -> generate_patch_proposal -> review_proposal -> dry_run_apply -> isolated_apply -> build`，
   `RepairPlanner`默认`retry_budget=2`。这会产生新的Proposal/Dry-run/Apply/Build revisions，并要求每次新的
   exact diff approval。
3. 当前typed operation attempt facts明确`automatic_retry_count=0`；
   `VerificationOperationResultV1`/`VerificationOperationDeclaration.store_attempt_chains`又以唯一role tuple表达
   一次有序Store chain，不能诚实表示同一outer action内重复的Build/repair Store attempts。当前repair节点还
   使用兼容`ArtifactStore.write()`，没有可由public result保留的C5 blocked/partial receipt。把整个repair loop
   隐式塞入一次mutation Build会同时改变attempt、receipt、result和failure matrix，并使`run_local_request()`
   继续拥有外围terminal解释。
4. 仅迁移初次Build同样不构成P2.2完成：Build failure仍由旧direct Graph/summary解释，CLI仍可能据
   `current_stage`或`claims_real_build_success`判终态；这违反“structured result是唯一machine truth”的退出门。
5. 当前没有一个既有public typed repair-preparation continuation能接收failed BuildResult、保留原Graph state、
   完成新的exact approval/apply并在下一次Build前停下。成功Build的Runtime continuation不能用于failed Build，
   post-Build `workflow_checkpoint`也不能证明pre-Build repair state。

因此本轮不在以下互斥语义之间替用户或实施者隐式选择：

- 为同一typed family另行设计bounded mutation repair continuation，并为最多两个已批准repair attempts定义
  attempt-scoped ordered C5 receipts与declaration-owned next-operation projection；
- 把完整post-apply product lifecycle升级为一个新typed operation，并同步迁移repair链全部Store结果；
- 改变legacy行为，在首次Build failure后不再进入repair而直接返回domain-blocked。

第三项会破坏当前产品行为，不在现有授权内；第二项会把P2.2从Build authority adoption扩大成完整产品
workflow迁移；第一项是最小保持行为方向，但仍需一份独立合同明确repair operation exact inputs、每次diff
Approval边界、Graph state handoff、attempt-scoped receipt schema和最终result aggregation。未闭合前不得用
local wrapper、caller提供的state snapshot、私有dict或Presentation summary充当过渡authority。

##### 15.11.2.5 当前checkpoint与停止门

- `allowed_production_files=[]`、`allowed_test_files=[]`、`implementation_authorization=not_granted`；本轮
  production/test/Store/index change均必须为none。
- `resolved_contract_facts`：一次mutation Build的exact immediate inputs、transitive lineage验证边界、
  BuildResult upstream、physical-locator排除、C5 BuildResult三态，以及successful mutation Build的现有
  checkpoint/lineage机制支持均如§15.11.2.3/.4。
- `unresolved_contract_decisions=[]`仅表示A/B架构边界已经由用户选择B；用户已经授权的transition级真实
  authorization semantics仍有效，但§15.11.2.8–.11只作为A方案的未批准设计记录。当前状态由§15.11.2.13覆盖为
  `architecture_boundary_selected_option_b`。普通descendant scan、latest/revision totals、进程内set、caller state或
  Presentation均不能替代B要求的Graph-owned route、Store-owned C5 facts或strict product result。
- P2.2保持open且实施暂停，直到B的精确implementation contract形成并获得独立`approved`；P2.3、P2.4、P3、P4
  均不得启动。不得为赶时间新增operation、Graph node、Artifact/Approval类型或修改`run_local_request()`。

##### 15.11.2.6 下一份有界repair-continuation合同的最小分解与新增兼容阻断

为避免一个operation平铺重复role，保持行为的最小结构必须把一次repair cycle拆成三个独立typed action；
每个action各自拥有Envelope、Approval/Action Identity、Store chain和冻结result：

1. `mutation_build_v1`：只消费本次exact DryRun/IsolatedApply refs，one-shot调用Build effect，写一个BuildResult；
   success按requested completion scope结束或建立Build handoff，failure只产生failed-Build handoff，不在同一
   operation内执行repair。
2. `mutation_repair_preparation_v1`：从exact failed-Build handoff恢复既有state，仅执行
   `create_repair_plan -> generate_patch_proposal -> review_proposal -> dry_run_apply`，不执行isolated apply、Build、
   Runtime或terminal；在新的DryRunResult committed后停止。该action不能预先包含尚未生成的diff approval hash。
3. `mutation_repair_apply_v1`：只在operator看到新DryRun并提供exact diff hash后形成Action Identity；消费该
   DryRun及其exact Proposal/Review lineage，重验workspace bytes和Binding，执行一次isolated apply并写一个
   IsolatedApplyResult。committed result再投影下一个`mutation_build_v1`输入。

`verification_operations.py`中的declaration-owned typed dispatcher应是唯一跨action route owner：

- Build blocked/partial→停止并保留本attempt真实C5 result；
- Build committed failed且budget剩余→只投影failed-Build repair handoff；
- repair preparation blocked/partial→停止；committed DryRun→等待exact diff approval；
- apply blocked/partial→停止；committed Apply→投影下一次Build；
- Build committed success且compile-only→完成；requested Runtime→投影Runtime continuation；
- budget exhausted→domain-blocked，不再投影repair。

`run_local_request()`只能把当前typed result交回dispatcher并调用其返回的public operation；不得读取
`current_stage`、Build/Runtime claims、revision totals、latest alias、stdout或Presentation字段决定next route/
terminal。outer aggregation只能保存按attempt顺序排列的冻结typed results及dispatcher projection，不重算
ArtifactWriteResult、Approval hash、platform status或execution disposition。每个repair attempt拥有独立role
chain，因此不修改既有`store_attempt_chains`的唯一role语义。

该最小分解仍有一个无法从现有public inputs诚实构造的protocol fact：

- failed-Build handoff若复用`WorkflowCheckpoint`，必须使用新的versioned repair binding（BuildResult必须failed、
  `claims_real_build_success=false`、`next_graph_node=create_repair_plan`、exact mutation ancestry、attempt number与
  budget、prior action hash），不能沿用只接受successful Build且固定`collect_runtime_evidence`的Runtime binding；
- durable consumption/replay若复用现有`ResumeReport`，就必须有真实`approved_by`。`run-request`目前没有该输入，
  `confirm_isolated_write`/`allow_build`是permission facts而不是actor identity；固定`local_cli_invoker`、复用
  `source_disclosure_approval_id`、checkpoint owner或自动字符串都会虚构审批身份；
- successful Build进入现有typed Runtime也有同一个缺口：CLI/public entry没有现有
  `NewRuntimeResumeProtocolBindingV1`要求的`approved_by`/`resume_id`。自动生成resume id可以作为一次调用的
  protocol nonce，但不能自动生成approver。

用户已经固定：不能把全部transition压成一个Resume模式；same-invocation successful Build→Runtime与failed
Build→repair preparation使用各自versioned structural protocol，不声称human Resume；repair apply在新DryRun形成后
绑定operator返回的exact diff；cross-invocation/manual resume继续使用现有human `ResumeReport/approved_by`。
用户同时拒绝给全部continuation强制新增`approved_by`，也拒绝默认、固定、读取OS用户、复用source-disclosure
approval或checkpoint owner填充approver。该决定状态为`resolved_by_user`，不能在实施中退回统一approver方案。

该决定会扩展typed protocol/result contract并需要durable consumption表达，但不授权代码。若现有Artifact/
ResumeReport不能无损表达，则必须先审核versioned ResumeReport protocol union或新protocol Artifact必要性，不能把
checkpoint descendant scan或进程内私有set冒充durable exactly-once事实。

基于该用户决定，下一版可实施合同还必须同时固定以下边界，不能留到编码阶段决定：

- initial/pre-Build product Graph只执行到`isolated_apply`完成，并在Build effect前交棒给
  `mutation_build_v1`；旧Graph不得先执行Build再包装typed result。
- `mutation_repair_preparation_v1`从exact failed-Build handoff进入`create_repair_plan`，在DryRun committed后
  interrupt；isolated apply、Build、Runtime调用都必须为0。
- `mutation_repair_apply_v1`只执行一次isolated apply并停止；下一个Build只能由dispatcher投影新的
  `mutation_build_v1`输入。
- ordered Store chains至少分别表达`BuildResult(+nullable handoff)`、
  `RepairPlan -> PatchProposal -> ProposalReview -> DryRunResult`和`IsolatedApplyResult`；每一步
  blocked-before-commit/partial/committed、写间异常、first-failure-stop及已committed prefix都由唯一
  declaration result owner解释。
- dispatcher只接受/返回versioned typed facts，不返回callable/private dict，也不读取可变Store、Graph或
  Presentation observation。attempt/budget/remaining/prior action/requested completion scope必须参与相应typed
  contract和checkpoint重验。

##### 15.11.2.7 用户已批准的transition级authorization semantics

该决定已由用户明确批准，状态为`resolved_by_user`，不能在实施中重新合并成一个Resume模式：

| transition | authorization事实 | 明确禁止 |
| --- | --- | --- |
| successful mutation Build→same-invocation Runtime workflow | 原`run-request`同一次调用已经验证的exact `runtime_admission`与run-scoped permissions；不声明Human Resume | 不生成/填写`approved_by`；不复用source-disclosure approval、OS用户、checkpoint owner或固定字符串 |
| failed mutation Build→repair preparation | exact failed-Build handoff、同一次调用的repair budget/attempt事实和原write/build permissions；不声明Human Resume | 不把failed Build伪装成successful Runtime handoff；不虚构approver |
| committed repair DryRun→repair apply | operator在看到该exact DryRun后返回的exact diff hash、既有`confirm_isolated_write` permission与exact DryRun/Proposal/Review lineage | 不提前把未来diff放进preparation identity；不混入Runtime approver |
| cross-invocation/manual resume | 现有Human `ResumeReport`、真实`approved_by`和existing exact resume validation | 不降级成structural permission；不改变历史Human Resume语义 |

`approved_by`不是repair apply Action Identity输入。若未来要为same-invocation exact-diff approval增加actor provenance，
必须另行审核公共输入和durable provenance；本包不能把当前不存在的actor identity写入payload。

##### 15.11.2.8 `resume_report` versioned protocol union与durable consumption/replay

只读inventory证明现有`WorkflowCheckpointStore._durable_consumption_state()`只把committed且`allowed=true`的
`resume_report`作为durable consumption；`ResumeValidator`又对Human `decision=approve`强制真实
`approved_by`。因此structural continuation不能复用现有Human payload，也不能仅靠进程内
`_consumed_checkpoint_ids`/`_seen_resume_ids`、descendant scan或latest/revision totals。最小合同复用是保留
`resume_report` Artifact type，并把当前新写升级为append-only versioned protocol union；不新增Artifact type：

1. payload新增exact `resume_protocol`对象，唯一discriminator为`protocol_kind + protocol_contract_version +
   semantic_binding`。`semantic_binding`固定为exact string object
   `{key: "resume_protocol", version: "1"}`。当前新写只允许：
   - `human_resume_v1`：保留现有Human Resume字段与`ResumeValidator`语义，`approve`仍要求真实
     `approved_by`/`approved_at`；
   - `same_invocation_structural_v1`：只允许§15.11.2.7登记的structural transition，不调用Human
     `ResumeValidator`，不具有Human approval语义。
   历史无`resume_protocol`的Human report保持read-only兼容并继续计入已消费checkpoint；未知kind/version、
   额外字段或跨variant字段混用全部fail-closed。未来Human新写与structural新写都必须经同一protocol owner，
   不再存在一个不参加durable conflict的current write旁路。
2. `same_invocation_structural_v1`的top-level兼容字段固定为：`resume_id=continuation_id`、exact
   `checkpoint_id/run_id/resume_stage`、`decision=continue`、`status=accepted`、`allowed=true`、固定structural
   reason、`applied_updates.restored_state`逐字等于checkpoint snapshot、`stale_reasons=[]`、`blockers=[]`、
   `approved_by=""`、`approved_at=""`、`authority_request_hash=null`。任何非空approver字段、Human decision或
   caller提供的restored state均拒绝。
3. `resume_protocol`的structural `transition_kind` exact literals只允许：
   `prebuild_to_mutation_build`、`successful_build_to_runtime`、
   `failed_build_to_repair_preparation`、`dry_run_to_repair_apply`、
   `repair_apply_to_mutation_build`。其余exact字段为：
   `protocol_kind=same_invocation_structural_v1`、`protocol_contract_version="1"`、`transition_kind`、
   `continuation_id`、checkpoint logical identity（feature/type/full hash与checkpoint id，不含physical locator）、
   source operation kind/version/approval identity hash、next operation kind/version、attempt number、repair budget
   total/remaining、requested completion scope、`runtime_admission`的canonical hash或null、exact diff hash或null，
   以及`semantic_binding={key: "resume_protocol", version: "1"}`。字段只按transition适用；不适用字段必须为null，
   不能省略后由caller补义。
4. 各transition nullability固定：
   - `prebuild_to_mutation_build`：source operation kind/version/hash为null，runtime admission hash与exact diff hash
     为null，next=`mutation_build/1`；
   - `successful_build_to_runtime`：source operation三字段非空，runtime admission hash非空，exact diff hash为null，
     next=`runtime_execution/2`；
   - `failed_build_to_repair_preparation`：source operation三字段非空，runtime admission hash与exact diff hash为null，
     next=`mutation_repair_preparation/1`；
   - `dry_run_to_repair_apply`：source operation三字段非空，exact diff hash非空，runtime admission hash为null，
     next=`mutation_repair_apply/1`；
   - `repair_apply_to_mutation_build`：source operation三字段非空，runtime admission hash与exact diff hash为null，
     next=`mutation_build/1`。
5. `continuation_id`由中立Action Identity primitive对checkpoint logical identity/id、source action identity nullable
   triple、transition kind、next operation kind/version、attempt facts、requested completion scope、适用的canonical
   runtime admission hash和适用的exact diff hash执行domain-separated canonical hash；hash domain固定为
   `mod_agent.structural_continuation.v1`。上述任何字段变化必须改变id；absolute locator、workspace、stdout/stderr、
   timestamp、Presentation和Store totals不进入该hash。
6. 一个纯deterministic `resume_protocol` owner负责：读取exact immutable checkpoint、验证binding/state/
   lineage/freshness/attempt/next route；投影Human或structural expected payload；投影neutral
   `ArtifactWriteIntent`。Registry只验证union discriminator与trusted handler可解析，不能复制route、approver、
   attempt或hash规则；Graph/public可提前/TOCTOU重验但只能委托同一owner。
7. 只有committed且`allowed=true`的Human report（包括validator接受的`approve`或`reject`decision）与structural
   accepted report是consuming report。它们共享同一neutral Store consumption conflict key：exact checkpoint
   logical identity与`checkpoint_id`，不含transition kind、operation kind或approver。一个checkpoint只允许一个
   committed consuming report；不同Human/structural payload、action hash或next route也竞争同一key。key经现有
   `mod_agent.artifact_semantic_commit_conflict.v1`hash，Store使用existing exclusive semantic pending protocol把
   “检查既有consumer/安装reservation”置于同一临界区；Store不识别Runtime、repair或diff语义。
8. Human validation blocked、`allowed=false`的report是non-consuming audit report。它仍经union owner和strict
   payload reproject，但使用只绑定checkpoint、attempted resume id/decision和canonical validation-result hash的
   `non_consuming_audit` conflict key；它不占用consumption key、不进入已消费扫描。先写blocked audit后仍允许一个
   accepted consumer；accepted consumer已存在时，DOUBLE_RESUME仍可写一个allowed=false audit report；audit与
   accepted并发不允许产生第二个accepted consumer。
9. Store pending前由trusted owner重投影expected report并逐字比较payload、exact checkpoint upstream、
   protocol refs、conflict key和expected Artifact hash。`write()`与`write_with_result()`都不能绕过；direct Store
   missing/tampered intent、第二consumer、pending conflict或unknown union version均首个下游effect前拒绝。
10. consumption/C5结果固定：
   - reservation安装前validation或full-key collision→`blocked_before_commit/commit_started=false/
     admission_validation`，checkpoint未消费；
   - 其他attempt已经committed该checkpoint的report→`blocked_before_commit/false/admission_validation`；
   - 其他attempt持有相同reservation或本attempt安装reservation后未committed→`partial`，并保留Store原始
     `commit_started`/pending/revision事实；checkpoint不得进入Graph/effect；
   - report committed且readback identity一致→checkpoint已durably consumed，才可进入Graph/effect；
   - 任一report blocked/partial都不自动retry/recover，不调用`recover_pending_writes`。`recovery_authorized=false`；
     crash/pending残留只能由以后单独授权的C5 recovery处理，当前public调用持续返回partial并停止。
   structural report receipt进入ephemeral operation result，不进入后续产品Artifact payload/hash；report本身作为
   protocol Artifact保留exact checkpoint upstream。
11. accepted structural report committed后，该checkpoint已被durably consumed；随后即使进程在首个业务Store前、
    effect期间、业务Artifact提交后或typed result返回前硬退出，也不得再次消费checkpoint或重入effect。下一次同一
    action的preflight必须由`resume_protocol` owner用exact checkpoint logical identity、`continuation_id`、source action
    identity、next operation identity及attempt facts识别`consumed_without_returned_result`，返回
    `preflight_status=blocked`、`identity_resolution_status=identity_resolved`和exact blocker
    `STRUCTURAL_ACTION_ALREADY_CONSUMED_WITHOUT_TERMINAL_RESULT`；只可返回从同一exact inputs逐字重构并通过trusted
    projector验证的原Envelope/hash，不得生成漂移的新identity或把该状态当作ready。
12. 若caller仍用原先已验证的Envelope/hash调用execute，execute必须在Graph/Store/effect前返回同一operation
    `VerificationOperationResultV1`：`platform_status=partial`、
    `failure_stage=interrupted_after_protocol_consumption`、`side_effects_may_have_started=true`、
    `automatic_retry_count=0`、`recovery_performed=false`、`recovery_authorized=false`。此前committed structural report
    作为variant的`consumed_protocol_ref`保留，但不列入本次`outputs`/`store_receipts`；先前调用的C5 receipt不可从ref、
    pending、revision、latest或Store totals重建。即使发现一个或多个descendant Artifact，也只能作为
    `observed_committed_artifact_refs`审计事实，当前v1结果不得据此重建`succeeded`或补造receipt；零个、一个或多个
    descendant均保持上述partial并拒绝自动retry/recover。若以后要无损恢复completed，必须另审durable result receipt/
    completion protocol，不能在P2.2实现中增加普通descendant/latest扫描。
13. `interrupted_after_protocol_consumption`加入三个mutation declaration及structural Runtime v2的exact
    `failure_stages`；它只由上述跨调用durable consumption事实投影，当前调用可捕获异常不能伪造。该状态不会创建
    第二份consuming report，也不会调用dispatcher的下一operation。

所有Human-only consumer/recovery都必须先解析protocol discriminator：historical无discriminator与
`human_resume_v1`进入Human路径；`same_invocation_structural_v1`不得被
`preflight_accepted_resume_recovery`、Runtime observation retry/recovery、terminal Human admission、Edit Authority或
repair-planning Human review误认。durable consumed scan只把validated consuming Human/structural variants计入；
unknown/tampered report既不能授权也不能占用checkpoint。

上述union会改变未来Human `resume_report`新写bytes/hash，但不改历史bytes、不重解释历史report，也不改变现有
Human public decision语义。它属于P2.2实施前必须单独核准的Artifact protocol evolution；若独立审核否决该union，
P2.2保持blocked，不能在实施中改成新Artifact或无durable consumption的私有状态。

##### 15.11.2.9 exact Graph handoff、typed operation与Store chain

本包在现有`VerificationOperationSpec/Envelope/Declaration/Result` family中append-only登记三个operation kind，
不修改既有七shape identity bytes：

1. `mutation_build` contract version `1`：variant只含ordered exact
   `(dry_run_result_ref, isolated_apply_result_ref)`、stable Build profile、`input_execution_mode=isolated_apply`与
   requested completion scope（`compile_only|runtime_workflow`）。initial与repair后的shape都必须使用§15.11.2.8
   structural protocol，并在Build Graph/effect前先committed一个`resume_report`消费各自的exact checkpoint handoff；
   run/request invocation facts只进入pre-Build checkpoint及Action Identity，不构成无durable consumption的旁路协议。
   operation只调用Build factory一次，只写一个BuildResult；success+runtime scope或failed+budget remaining再写一个
   versioned WorkflowCheckpoint，compile success或budget exhausted不写handoff。
2. `mutation_repair_preparation` contract version `1`：只接受exact failed-Build checkpoint structural protocol，
   START admission重建checkpoint snapshot并逐字验证failed Build、mutation ancestry、attempt/budget/prior action；
   Graph只走`create_repair_plan -> generate_patch_proposal -> review_proposal -> dry_run_apply`，DryRun committed后
   写一个DryRun handoff WorkflowCheckpoint并END。isolated apply、Build、Runtime、evaluation/terminal调用均为0。
3. `mutation_repair_apply` contract version `1`：只接受exact DryRun handoff structural protocol、operator返回的exact
   decision（`approve|reject`）和current isolated-workspace execution constraints。`approve`要求operator value逐字等于
   expected diff hash；`reject`只接受现有exact token `REJECTED_BY_USER`。Action Identity绑定decision、DryRun logical
   identity与exact diff hash，不把Runtime approver或事后事实混入。approve Graph只执行一次`isolated_apply`，committed
   success后写next-Build handoff WorkflowCheckpoint并END；reject仍以structural report消费DryRun checkpoint，但
   isolated-apply effect调用为0，并写一份committed blocked IsolatedApplyResult：`execution_mode=rejected`、
   `actual_write_performed=false`、`real_patch_applied=false`、`exact_diff_approved=false`，随后以
   `completed/domain_blocked/next_operation.route=none`停止。Build、Runtime、evaluation/terminal调用均为0。除exact
   reject token以外的hash mismatch属于preflight authorization/admission blocked：structural report、业务Store、effect均为0，
   DryRun checkpoint保持未消费，outer adapter不得把`operator_input_required`私自改写为`domain_blocked`。

initial产品Graph边界固定为：`run_local_request()`继续调用现有产品Graph完成自然语言/evidence/implementation/
proposal/review/dry-run/first isolated-apply；Graph在Build node/effect前不返回可执行Build state，而是先用
`WorkflowCheckpointStore.create_checkpoint_with_result()`写一份`mutation_prebuild_build_handoff_v1`
WorkflowCheckpoint，再以该exact checkpoint ref和C5 receipt结束pre-Build阶段。checkpoint的`state_snapshot`由Graph
在first isolated-apply committed后从当前`ModAgentState`构造，是后续Build所需run/request/feature/user/target、Artifact
refs/hashes、attempt、approval、blocker、summary及trace的唯一durable state owner。memory checkpointer、interrupt state、
caller mapping和run-local文件只作进程内定位/审计，不能直接传给typed executor或覆盖checkpoint snapshot。

checkpoint write `blocked_before_commit|partial`时pre-Build Graph按真实C5结果停止，Build factory/effect与后续operation
调用均为0；committed后outer adapter只能把exact checkpoint ref交给
`preflight_mutation_build_continuation`。preflight从Store读取checkpoint及ordered DryRun/Apply refs，投影
`prebuild_to_mutation_build` structural protocol；execute先committed consuming `resume_report`，再从checkpoint snapshot
恢复clean state并在任何Build effect前重验全部字段/lineage。typed与legacy mutation Build都经同一outer normalizer进入
该路径；旧Graph不得先Build再包装typed result，也不得从interrupt state跳过checkpoint/report。

pre-Build Graph在checkpoint产生前因Evidence/Proposal/Review/DryRun/first Apply domain blocker或可捕获平台失败停止时，
当前调用尚未形成`VerificationOperationResultV1`。该阶段的唯一machine truth是existing Graph返回的exact
`ModAgentState`及其conditional-edge终态，`run_local_request()`只能把它放入
`run_local_machine_result={schema_version:"run_local_machine_result_v1",source:"prebuild_graph",
prebuild_graph_state:<exact Graph state>,verification_operation_result:null}`，不得读取`current_stage`、claims、summary、
revision totals或stdout重新计算status。CLI对`source=prebuild_graph`只保留既有Graph调用是否正常返回与既有pre-Build
终态投影；一旦checkpoint committed并进入typed operation，result形状必须切换为`source="verification_operation"`、
`prebuild_graph_state=null`、`verification_operation_result=<exact VerificationOperationResultV1>`，其后所有路由/退出码
只读该typed result与declaration-owned `next_operation`。两个source互斥，不能同时非空或同时为空；pre-Build state在
切换后只可进入ordered audit history，不再拥有当前machine truth。

WorkflowCheckpoint仍是唯一state handoff Artifact，但`resume_binding`增加append-only exact discriminator
`binding_kind + binding_contract_version`，只允许：

- `mutation_build_runtime_handoff_v1`：successful real Build、exact mutation ancestry/verified output、
  `next_graph_node=collect_runtime_evidence`、run-scoped runtime admission hash；
- `mutation_build_repair_handoff_v1`：failed Build、`claims_real_build_success=false`、
  `next_graph_node=create_repair_plan`、attempt/budget/prior action；
- `mutation_repair_dry_run_handoff_v1`：exact RepairPlan/Proposal/Review/DryRun chain、expected diff hash、
  `next_graph_node=isolated_apply`；
- `mutation_repair_apply_handoff_v1`：exact Proposal/Review/DryRun/Apply chain、approved diff hash、
  `next_graph_node=build`。
- `mutation_prebuild_build_handoff_v1`：first isolated-apply committed、ordered DryRun/Apply refs、完整pre-Build
  `state_snapshot`、initial `MutationAttemptV1`和requested completion scope，`next_graph_node=build`。

每个binding必须逐字绑定run/request/feature、source operation approval hash、next operation kind/version、attempt facts、
requested completion scope和适用exact refs/hashes；unknown/extra binding、stage/node不匹配、latest alias、state/artifact
drift均在structural report或下一个effect前拒绝。failed handoff不能通过现有successful Runtime blocker，successful
handoff也不能进入repair。

declaration-owned `store_attempt_chains`完整登记：

| shape | exact legal chains |
| --- | --- |
| initial mutation Build | `(resume_report, build_result)`；`(resume_report, build_result, workflow_checkpoint)` |
| repair-followup mutation Build | `(resume_report, build_result)`；`(resume_report, build_result, workflow_checkpoint)` |
| repair preparation | `(resume_report, repair_plan)`（committed RepairPlan domain blocker）；`(resume_report, repair_plan, patch_proposal, proposal_review)`（committed review domain blocker）；`(resume_report, repair_plan, patch_proposal, proposal_review, dry_run_result)`（committed DryRun但不具备apply handoff）；同一最长chain再追加`workflow_checkpoint`（exact diff handoff ready） |
| repair apply | `(resume_report, isolated_apply_result)`；同一prefix再追加`workflow_checkpoint` |
| structural same-invocation Runtime workflow | 沿现有Runtime terminal三条chain，但首项必须是structural `resume_report`，不得虚构Human report receipt |

`output_artifact_roles`只做role→ArtifactType allowlist，合法顺序/branch仍只由declaration record拥有。每个节点必须使用
`write_with_result`并把Store-owned typed `ArtifactWriteResult`保留到Graph ephemeral state；adapter/Graph/local entry不得
从ref、filesystem或totals重造receipt。一个noncommitted Store result必须是最后一次调用，随后所有Store/effect为0。

##### 15.11.2.10 attempt、dispatcher、result与failure matrix

新增exact `MutationAttemptV1`并由三operation共享；字段为：`build_attempt_number`、`repair_attempt_number`、
`repair_budget_total=2`、`repair_budget_remaining`、`prior_action_identity_hash`、`automatic_retry_count=0`、
`recovery_allowed=false`。约束为：initial Build=`build_attempt_number=1/repair_attempt_number=0/remaining=2/
prior=null`；第N次repair preparation/apply和其后Build使用`repair_attempt_number=N`、
`build_attempt_number=N+1`、`remaining=2-N`、exact non-null prior action hash，N只允许1或2。attempt fields与requested
completion scope进入Action Identity、checkpoint binding和dispatcher projection；任一漂移首个Store/effect前拒绝。
budget exhausted时不得创建`mutation_build_repair_handoff_v1`或投影repair operation。

每个mutation result variant都包含一个declaration-owned `next_operation` typed projection，exact schema为：
`projection_contract_version`、`route`（`none|invoke_operation|await_exact_diff_approval`）、source operation kind/version/
approval hash、next operation kind/version或null、exact checkpoint ref或null、next attempt facts或null、requested
completion scope、exact DryRun ref/expected diff hash或null。字段按route固定nullability；不允许`terminal_disposition`、
callable、private dict、Graph state、latest ref、Store totals或Presentation observation。`await_exact_diff_approval`
只显示DryRun/diff事实，不能提前构造repair-apply Envelope/hash；operator返回hash后由public preflight重新读Store并
形成exact Envelope。

`VerificationOperationResultV1.execution_disposition`继续使用已经提交并由strict parser闭合的exact值域
`succeeded|domain_blocked|platform_blocked|partial|operator_input_required`，P2.2不得append新literal。当前operation
的required Store chain全部committed且没有domain/platform blocker时固定为`succeeded`；该值只证明当前action完成，
不声明整个产品workflow完成。后续生命周期只由variant中的`next_operation.route`表达：存在exact下一operation时仍为
`succeeded + invoke_operation`，等待diff时为`operator_input_required + await_exact_diff_approval`，最终完成才是
`succeeded + none`；`domain_blocked`只与`route=none`组合，`platform_blocked|partial`也不得携带可执行next route。
run_local adapter只能把result交给一个中立public dispatcher，或把最终result投影成legacy/CLI Presentation；不能维护
operation-kind→public-function的`if/elif`/第二注册表，也不能修改status/disposition/refs/receipts或读取`current_stage`、
claims、runtime summary、revision totals、latest alias、stdout、Presentation选择route。dispatcher不携callable；
registration/resolution仍由operation declaration owner拥有，public dispatcher通过registered handler key解析，
`verification_operations.py`不反向导入`local_entry.py`。

所有operation统一first-failure-stop矩阵：

| facts | platform/result | Store/side-effect边界 |
| --- | --- | --- |
| declaration/identity/input/lineage/freshness/expected-hash/Graph START drift | `blocked/authorization|admission` | receipts=0；本operation effect=0；Store增量0 |
| structural report `blocked_before_commit` | `blocked/*_protocol_store` | 保留该C5 receipt；其后Graph/effect/Store=0 |
| structural report `partial` | `partial/*_protocol_store` | 保留该C5 receipt；其后Graph/effect/Store=0；retry/recovery=0 |
| report committed后，下一node execution/prewrite validation异常 | `partial/exact node execution stage` | 保留committed protocol ref/receipt和既有committed prefix；未调用Store无receipt；后续=0 |
| 任一业务Store `blocked_before_commit`且此前无committed prefix | `blocked/exact role_store` | 保留真实最后receipt；后续=0 |
| 任一业务Store noncommitted且已有committed prefix，或最后receipt本身partial | `partial/exact role_store` | 保留全部ordered prefix；后续=0；不自动恢复 |
| declaration登记的domain-terminal短链全部committed | `completed/domain_blocked` | 短链必须逐项匹配一条exact legal chain，`next_operation.route=none`；不得按更长chain prefix投影partial或继续 |
| 全部当前branch required roles committed | `completed` | outputs逐项同role/ref匹配committed receipts；dispatcher从declaration+variant投影next route |

合法role tuple本身不决定terminal语义；declaration必须同时登记并由result projector验证以下exact
`store_chain_predicates`。adapter与测试不得按tuple复制第二张predicate表：

| operation/committed chain | exact payload/status predicate | 唯一result/next route |
| --- | --- | --- |
| mutation Build `(resume_report, build_result)` compile branch | BuildResult envelope `status=success`、payload `status=success`、`real_build_performed=true`、`claims_real_build_success=true`，requested completion=`compile_only` | `completed/succeeded/route=none` |
| mutation Build `(resume_report, build_result, workflow_checkpoint)` Runtime branch | 同一successful Build facts、requested completion=`runtime_workflow`，checkpoint binding=`mutation_build_runtime_handoff_v1`且exact runtime admission/attempt/source action一致 | `completed/succeeded/route=invoke_operation(runtime_execution/2)` |
| mutation Build `(resume_report, build_result)` exhausted branch | BuildResult committed但payload `status!=success`或`claims_real_build_success=false`，且`repair_budget_remaining=0`；不得存在repair checkpoint | `completed/domain_blocked/route=none` |
| mutation Build `(resume_report, build_result, workflow_checkpoint)` repair branch | 同一failed Build facts、`repair_budget_remaining>0`，checkpoint binding=`mutation_build_repair_handoff_v1`且exact attempt/prior action一致 | `completed/succeeded/route=invoke_operation(mutation_repair_preparation/1)` |
| repair preparation `(resume_report, repair_plan)` | RepairPlan envelope `status=blocked`，且payload `retry_exhausted=true`、`blockers`非空或`allowed_next_stage!="generate_patch_proposal"` | `completed/domain_blocked/route=none` |
| repair preparation through committed `proposal_review` | ProposalReview envelope `status=blocked`且payload `allowed_next_stage!="dry_run_apply"` | `completed/domain_blocked/route=none`；本operation不在内部重入repair loop |
| repair preparation through committed `dry_run_result` without checkpoint | DryRunResult envelope不是`status=success`，或payload不同时满足`execution_mode="dry_run"`、`actual_write_performed=false`、`real_patch_applied=false`、`approved_by_review=true`、non-empty exact `diff_hash` | `completed/domain_blocked/route=none` |
| repair preparation through committed `dry_run_result, workflow_checkpoint` | DryRunResult满足上述全部handoff-ready facts，checkpoint binding=`mutation_repair_dry_run_handoff_v1`且exact diff/attempt/source action一致 | `completed/operator_input_required/route=await_exact_diff_approval` |
| repair apply `(resume_report, isolated_apply_result)` reject branch | variant decision=`reject`，IsolatedApplyResult envelope `status=blocked`且payload `execution_mode="rejected"`、`actual_write_performed=false`、`real_patch_applied=false`、`exact_diff_approved=false` | `completed/domain_blocked/route=none`，isolated-apply effect=0 |
| repair apply `(resume_report, isolated_apply_result)` failed branch | variant decision=`approve`，IsolatedApplyResult envelope `status=blocked|failed`且payload没有同时满足successful apply facts | `completed/domain_blocked/route=none` |
| repair apply `(resume_report, isolated_apply_result, workflow_checkpoint)` | variant decision=`approve`，IsolatedApplyResult envelope `status=success`且payload `execution_mode="isolated_apply"`、`actual_write_performed=true`、`real_patch_applied=true`、`approved_by_review=true`、`approved_by_user=true`、`exact_diff_approved=true`，`approved_diff_hash`与DryRun `diff_hash`逐字相同；checkpoint binding=`mutation_repair_apply_handoff_v1` | `completed/succeeded/route=invoke_operation(mutation_build/1)` |

successful Build要求handoff、handoff-ready DryRun或successful Apply缺少required checkpoint时，即使前一业务Artifact已
committed也必须为`partial/checkpoint_construction|workflow_checkpoint_store`并保留真实committed prefix；不得把它们
解释为合法短链。RepairPlan允许继续却无Proposal、ProposalReview允许dry-run却无DryRun、failed mutation Build仍有
budget却无repair handoff，同样只能由与当前phase相符的非Store failure或真实noncommitted Store receipt解释partial，
不能产生`failure_stage=null`的completed。projector/from_dict共同重放predicate与chain，不接受caller提供的route/
disposition覆盖derived truth。

Build factory或isolated-apply effect开始后异常必须标记`side_effects_may_have_started=true`；repair preparation纯Store/
model或deterministic node按实际effect边界报告，不能用Store commit反推外部effect。BuildResult committed但checkpoint
blocked/partial为`partial`并保留BuildResult；DryRun committed但handoff checkpoint失败为`partial`，不能假装等待
operator；Apply committed但next-Build checkpoint失败为`partial`，不能直接Build。任何post-commit Presentation/
audit错误不得降级已冻结machine result。

最低合同/实施验收除原§15.11.2.4外必须包括：先committed allowed=false Human blocked report后仍能写一份合法
allowed consumer；accepted consumer后DOUBLE_RESUME仍写non-consuming blocked audit；Human allowed consumer与structural
allowed consumer并发最多一份committed consumer；structural reservation collision/pending/crash三态；historical无
discriminator Human read-only兼容；Edit Authority、repair-planning、C6 Runtime/retry/recovery/terminal的Human-only reader
全部拒绝structural report；continuation id对completion scope/runtime admission/diff/source/route/attempt任一漂移变化；
initial Graph Build factory=0、pre-Build checkpoint snapshot逐字恢复且caller/interrupt state tamper无效；checkpoint形成前
domain blocked只返回`source=prebuild_graph`，checkpoint后只返回`source=verification_operation`；approve/reject两个exact
diff分支及reject apply effect=0；三operation每条短链的payload/status predicate与required handoff缺失partial门；每个role
的blocked-before-commit/partial与写间异常；attempt 1/2、budget exhausted、prior hash和dispatcher drift首写前拒绝；
consuming report committed后在effect前/effect中/Artifact committed后硬退出，下一调用均fail-closed partial、report ref
保留、receipt不重造、side_effects_may_have_started=true、recovery=false；successful mutation Build→structural Runtime完整
公共链；cross-invocation Human Resume保持；run_local只调用中立public dispatcher且CLI只消费当前structured machine
result。任何需要新Artifact type、第二dispatcher/result owner、Graph/Store绕过或修改P2.3-P4的发现都必须停止并重新审核。

##### 15.11.2.11 identity、declaration owner与公共入口

中立canonical JSON/domain-separated SHA256仍只由`action_identity.py`拥有。各semantic owner只声明exact projection；
不得各自实现JSON排序/hash。append-only records固定如下：

| shape | identity schema/hash domain | exact approval projection |
| --- | --- | --- |
| initial/followup `mutation_build` v1 | `mutation_build_identity_v1` / `mod_agent.mutation_build.v1` | run/request/feature；ordered DryRun/Apply logical identities；Build profile stable fields；isolated-apply mode；requested completion；exact `MutationAttemptV1`；structural checkpoint identity/continuation id/source action nullable facts；one Build effect与allowed outputs。initial必须绑定`mutation_prebuild_build_handoff_v1`，followup必须绑定`mutation_repair_apply_handoff_v1` |
| `mutation_repair_preparation` v1 | `mutation_repair_preparation_identity_v1` / `mod_agent.mutation_repair_preparation.v1` | failed checkpoint logical identity、structural continuation id/source action hash、exact attempt/budget/completion scope、bounded node/action scope、allowed output roles；不含尚未生成的Proposal/DryRun/diff |
| `mutation_repair_apply` v1 | `mutation_repair_apply_identity_v1` / `mod_agent.mutation_repair_apply.v1` | DryRun checkpoint logical identity、structural continuation id、exact DryRun/Proposal/Review logical identities、operator返回的exact diff hash、exact attempt/budget/completion scope、one isolated-apply effect与allowed outputs；不含Runtime approver |
| structural same-invocation `runtime_execution` | existing operation kind + append-only contract version `2`；`runtime_execution_identity_v2` / `mod_agent.runtime_execution.v2` | successful mutation Build checkpoint logical identity、structural continuation id/source Build action hash、exact attempt/completion scope、canonical original run-scoped runtime admission/permissions、runtime action scope；不含`approved_by`、Human resume id或physical locator |

现有`runtime_execution` contract version `1`、七shape identity/hash bytes和Human `NewRuntimeResumeProtocolBindingV1`保持
不变；cross-invocation/manual继续解析v1。v2不得fallback到v1 projector，unknown version fail-closed。v2
`RuntimeExecutionResultV1.resume_report_ref`保存structural report ref，declaration chains与现有initial Runtime workflow
相同role顺序；其payload union discriminator证明它不是Human approval。

owner固定为：

- `verification_operations.py`：operation declaration、identity projector registration、attempt/result/next-operation
  projector和合法Store chains唯一owner；
- 新纯模块`resume_protocol.py`：Human/structural ResumeReport union、continuation id、checkpoint consumption semantic
  projection唯一owner；不依赖Graph/local entry/Presentation，且只通过中立read context访问Store；
- 新纯模块`mutation_continuation.py`：三个mutation action的transitive lineage、checkpoint binding、spec inputs和
  post-effect payload validation唯一owner；不写Store、不启Graph、不解释C5 result；
- `artifact_semantics.py`：只登记`resume_report + resume_protocol + 1`trusted handler并生成neutral
  `ArtifactWriteIntent`；Store继续只消费intent/conflict key，不理解operation/repair/Runtime/diff；
- `workflow/checkpointing.py`：state snapshot、versioned checkpoint binding和protocol read/consume orchestration；业务
  invariant委托上述pure owner；
- `workflow/graph.py`：node顺序、START/interrupt/TOCTOU、Graph-before-effect；节点业务/identity/result规则均委托；
- `local_entry.py`与CLI：legacy输入准备、调用public pair、逐字执行`next_operation`、最终Presentation；无route/
  disposition/receipt/hash authority。

公共entry固定为三个exact pair，不建立含nullable factory集合的单体executor：

- `preflight_mutation_build_continuation` / `execute_mutation_build_continuation`；
- `preflight_mutation_repair_preparation` / `execute_mutation_repair_preparation`；
- `preflight_mutation_repair_apply` / `execute_mutation_repair_apply`。

preflight只接收exact Spec及只读execution constraints，返回现有`VerificationOperationPreflightResultV1`；execute只接收
validated Envelope、`expected_approval_identity_hash`与该variant登记的effect adapter，重跑同一preflight并在任何
ResumeReport/Graph/Store/effect前逐字比较。typed operation与legacy mutation参数混用零写入拒绝。structural Runtime
继续使用现有Runtime public entry，但只通过new contract-v2 Spec/Envelope进入；public normalizer不得把v2改写成Human
v1。三个pair内部可以委托private handler，但不能彼此接收不适用factory或字段。

P2.2最终不新增第二套typed-operation verdict schema。checkpoint形成前的pre-Build阶段按§15.11.2.9的互斥
`run_local_machine_result.source=prebuild_graph`保留existing Graph machine truth；checkpoint committed并开始typed action
后，每次action只产生一个authoritative `VerificationOperationResultV1`，`next_operation`属于exact mutation variant
result。`run_local_request()`可以把此前pre-Build state与冻结operation results作为ordered audit history附在legacy
mapping中，但current machine truth只能是互斥source指定的一个对象；CLI在`verification_operation`阶段只读取该result
的`execution_disposition`。history不能参与route、terminal或receipt校验。

declaration `failure_stages`逐shape固定，不允许adapter改名或按异常类名选择：

- mutation Build：`authorization -> admission -> resume_protocol_store -> graph_admission ->
  store_preflight -> build_execution -> post_build_validation -> build_result_store -> checkpoint_construction ->
  workflow_checkpoint_store -> interrupted_after_protocol_consumption -> internal_execution`；
- repair preparation：`authorization -> admission -> resume_protocol_store -> graph_admission ->
  repair_plan_execution -> repair_plan_store -> patch_proposal_execution -> patch_proposal_store ->
  proposal_review_execution -> proposal_review_store -> dry_run_execution -> dry_run_result_store ->
  checkpoint_construction -> workflow_checkpoint_store -> interrupted_after_protocol_consumption -> internal_execution`；
- repair apply：`authorization -> admission -> resume_protocol_store -> graph_admission -> store_preflight ->
  isolated_apply_execution -> post_apply_validation -> isolated_apply_result_store -> checkpoint_construction ->
  workflow_checkpoint_store -> interrupted_after_protocol_consumption -> internal_execution`；
- structural Runtime v2沿用现有Runtime-workflow stage tuple，`resume_report_store`明确表示structural protocol report
  Store结果，并登记`interrupted_after_protocol_consumption`；caller effect异常仍只能是`runtime_execution`，不能通过
  异常类名选择其他平台stage。

所有Store-owned stage只能由该role真实`write_with_result`返回的noncommitted receipt派生；无对应Store调用时不能由
`execution_failure_stage`伪造。无noncommitted receipt的execution stage必须与当前committed prefix所处phase一致；
全部legal chain committed后不能再由`internal_execution`或Presentation降级。strict serialized result继续委托同一
declaration projector重放phase/chain规则。

##### 15.11.2.12 当前合同状态、实施拆包与独立审核门

`user_authorization_semantics=resolved_by_user`，A方案的protocol/operation边界没有获得实施授权。独立审核确认
当前P2.2“Build adapter adoption”与`run_local_request()`真实same-invocation完整生命周期边界不匹配，继续逐字段修补
会把入口迁移扩大成新的durable execution平台。用户已经选择B，因此当前精确状态为
`architecture_boundary_selected_option_b`、`b_implementation_contract=independently_approved_pending_implementation`、
`implementation_authorization=granted_within_§15.11.2.14_exact_scope`；批准绑定的合同文档SHA256为
`3E954A76DF8141347960DE1888C92BE3947C93113C0586330B9E213EC82C105A`。§15.11.2.8–.11保留为A方案的未批准设计记录，
不是rejected最终结论，也不是P2.2a–d实施合同。只允许按§15.11.2.14的I/II/III连续checkpoint实施；不得继续给A追加字段或
启动P2.3–P4。

以下原拆包仅说明A方案的成本，不构成当前实施顺序或授权：

1. P2.2a：ResumeReport protocol union、trusted semantic intent、shared checkpoint conflict/C5三态与历史Human
   compatibility；不接Graph/effect。
2. P2.2b：mutation declarations/identity/attempt/result/dispatcher及versioned checkpoint binding；先用pure/Store
   tests证明，无active entry adoption。
3. P2.2c：三个Graph/public pairs与node `write_with_result`迁移，真实temporary Store failure matrix；不改
   run_local/CLI。
4. P2.2d：`run_local_request()`/`run-request`pre-Build interrupt、public pair adoption、structural Runtime v2与final
   machine-result Presentation；删除旧Build/repair/runtime route/terminal authority并做真实公共集成。

任一子包发现union无法保持Human历史兼容、需要新Artifact type、需要Store识别operation、需要第五个result owner或
必须改变P2.3–P4，立即停止并回合同审核；不得在同一子包顺带决定。只有P2.2a–d均独立验收/提交、active entry静态
inventory证明旧authority退出、成功/failed/repair-budget/Runtime公共矩阵通过后，P2.2与Build production adoption才
可标记complete。当前文档修改、审核时间仍计入`hard_stop=2026-08-07T14:11:55.6636360+08:00`；到点未approved则
只保存合同checkpoint，不写代码、不做WIP commit。

##### 15.11.2.13 architecture boundary reselection：A/B只读比较checkpoint

本节只比较边界，不批准A或B实施。比较基线为HEAD
`d37de0d82f2bdac263cdd9849e371b9d9aa6f58e`的真实源码；production/test/Store/index change均为none。

| 维度 | A：multi-operation durable continuation | B：same-invocation Public Product Executor + existing StateGraph |
| --- | --- | --- |
| 解决的问题 | 把Build、repair preparation、repair apply、后续Build和Runtime拆成可跨调用、可durable消费的独立action | 让当前active `run_local_request()`退出shadow control plane，同时保持本次调用内现有Proposal/Repair/Build/Runtime/Eval生命周期 |
| 核心route owner | 新declaration dispatcher跨三个mutation public pair和Runtime v2选择下一action | 现有`build_graph()` conditional edges继续拥有same-invocation route；Public Product Executor只调用一次Graph并消费Graph产出的冻结product result |
| Approval表示 | 每个action各自Envelope/Action Identity；structural continuation另需protocol consumption identity | 整个workflow不建立总Approval Identity；已经有canonical identity的sub-action继续引用原owner；exact diff hash、Build/Runtime bool/scope permission等只有binding事实而没有canonical Approval Identity的输入不得冒充identity，product result只引用其经验证事实 |
| durable新增 | `resume_report` union、consumption conflict、crash/replay、四类checkpoint binding、structural Runtime v2 | 不新增structural ResumeReport、跨进程exactly-once或自动crash recovery；actual Human/cross-invocation interrupt继续使用现有Human ResumeReport |
| public/schema新增 | 三个public pair、三个operation declaration、Runtime v2、attempt/dispatcher/next-operation/result variants | 一个Public Product Executor public pair及一个strict `ProductExecutionResultV1`；不增加mutation action kind，不改变既有七shape identity/hash |
| Graph改动 | initial pre-Build切断；repair preparation/apply/build拆Graph边界并增加START/STOP/checkpoint消费 | 保留现有nodes/conditional edges/repair budget；仅为product-executor mode把每个durable node的C5 receipt存入ephemeral state并在terminal投影结果 |
| Store/Artifact | 复用Artifact类型仍需`resume_report` semantic binding、shared conflict及新checkpoint binding | Artifact类型/lineage保持；节点继续写既有Artifact，只把兼容`write()`调用迁到`write_with_result()`并first-failure-stop |
| hard exit | 必须定义consumed report后无result的跨调用悬挂态与replay拒绝 | 不声称跨进程恢复；进程硬退出可能没有任何structured result返回，durable Artifact仅作审计/以后显式流程输入，不自动重入、不重建C5 receipt，也不伪造“已持久化的失败result” |
| 行为兼容风险 | 切断现有same-invocation Graph，repair/Runtime每次重建state与handoff，新增协议/identity兼容面 | 保留现有Graph route和最多两次repair；主要风险是C5 first-failure-stop使过去隐式继续的Store失败明确停止，以及legacy result/CLI投影漂移 |
| 预计有界包 | 至少原P2.2a–d四包，且先承担protocol union/crash/replay平台能力 | 三包：B1 product result/Graph C5 facts；B2 Public Product Executor与真实failure matrix；B3 run_local/CLI adoption及旧authority退出 |

真实symbol inventory与修改面：

- A至少触及/新增`verification_operations.py` declarations/dispatcher、`resume_protocol.py`、
  `mutation_continuation.py`、`artifact_semantics.py` trusted binding、`workflow/checkpointing.py` union/consumption、
  `workflow/graph.py` split boundaries、`local_entry.py`三个public pair和adapter、`cli.py` Presentation，以及Registry/
  Store semantic-intent相邻测试；它交付的是新的durable execution平台能力，不只是入口adapter。
- B保留`workflow/graph.py::build_graph`及现有`route_after_*` conditional edges。当前 `_run_build`、
  `_run_runtime_evidence`、`_run_fake_evaluate`、`_run_workflow_summary`和blocked terminal只有在verification-operation
  controls启用时才走`write_with_result`/`use_store_result`；普通`run_local_request()`未传`verification_operation`，
  因此这些节点当前仍走兼容`write()`。B必须建立一个typed product-executor Graph mode统一启用其已有C5路径；该mode
  的exact carrier/owner由B实施合同固定，不能成为新的bool/string route authority。
- 普通run-local active route中仍直接调用`ArtifactStore.write()`且没有可复用C5 branch的节点包括
  `_run_plan_request`、`_run_planning_brief`、`_run_draft_feature_spec`、`_run_retrieve_evidence`、
  `_run_create_implementation_plan`、`_run_generate_patch_proposal`、`_run_review_proposal`（含critic/review）、
  `_run_dry_run_apply`、`_run_create_repair_plan`、`_run_isolated_apply`、`_run_resolve_runtime_binding`。它们全部属于B的
  active C5 adoption范围；每个节点只保存Store返回的typed `ArtifactWriteResult`，不得由ref、state、totals或文件存在
  重建。`_materialize_feature_spec_revision`只在`feature_spec_revision_projection`非空的条件路径调用，当前
  `run_local_request()`没有提供该输入，所以不属于P2.2 active route；B不得宣称它已迁移，若Public Product Executor
  以后接收该条件输入必须另行登记并纳入C5范围。
- B新增一个中立Public Product Executor（exact module/symbol留待B实施合同inventory后固定）作为
  `run_local_request()`唯一调用目标：准备validated Graph inputs/effect adapters→invoke existing StateGraph once→由一个
  declaration-owned product projector产出`ProductExecutionResultV1`。该result覆盖从request planning、planning brief、
  FeatureSpec、EvidencePack、ImplementationPlan开始的全部active Store attempts，并按Graph实际attempt顺序保存冻结的
  Proposal/review/dry-run/apply/Build、适用BindingResolution、Runtime/Eval及BlockedReport/WorkflowSummary sub-results与
  C5 receipts；重复repair role按attempt/phase嵌套记录，不压成一条flat `store_attempt_chains`，也不重算Store/Build/
  Runtime/domain truth。exact schema留给B实施前合同，但任何reachable node的Store failure都不能从result覆盖面省略。
- B的`run_local_request()`只保留workspace/model/effect参数准备、调用executor、legacy Presentation；必须删除其
  `graph.invoke`、`final_build_succeeded`、`current_stage`/Build或Runtime claims及summary判终态。`cli.py`的`run-request`
  必须删除当前`current_stage==done`、`claims_real_runtime_success`、`claims_real_build_success`退出码判断，改为只读取
  strict product result的declaration-owned disposition。Graph外不得存在第二route/status/receipt owner。

B的失败与组合边界：

1. same-invocation Graph route保持当前语义：failed Build可进入`create_repair_plan`，repair budget仍由
   `RepairPlanner(retry_budget=2)`与Graph state约束，successful Build按已有conditional edge进入Runtime/Eval；Public
   Product Executor不维护第二张route表。
2. 每个Store调用一旦返回`blocked_before_commit|partial`，Graph在下一node/effect前停止并把exact receipt及此前
   committed attempt prefix交给product projector；不得继续后续repair/Build/Runtime，也不得伪造未调用receipt。
3. Build/isolated-apply/Runtime effect异常按实际调用点记录`side_effects_may_have_started`；product result聚合冻结
   facts，不用Artifact commit反推effect是否发生。
4. actual dynamic Human review、manual/cross-invocation Runtime Resume继续走现有Human ResumeReport；same-invocation
   ordinary route不写或伪造ResumeReport。进程硬退出可能没有structured result返回；B不承诺exactly-once、自动retry/
   recovery、恢复上次ephemeral receipt或事后伪造machine result。
5. 整个workflow不生成总Approval hash。已有canonical identity的sub-action继续由原owner构造/验证，product projector
   只引用其hash/ref/result；exact diff hash与Build/Runtime permission等existing binding事实由B实施合同固定可信输入与
   validation owner，但不得被包装成不存在的canonical Approval Identity，也不能合并成workflow总hash。

结论：对于当前目标“迁移active主产品入口且保持same-invocation行为”，B需要的机制和修改面
明显小于A，并直接针对`run_local_request()`与CLI的shadow route/result owner；A提供的跨进程、逐attempt durable
continuation/exactly-once能力不是当前入口迁移已经证明必须具备的产品能力。因此推荐把P2.2边界改为B，并把A保留为
未启动的conditional durable-continuation设计记录。用户已明确选择B完成same-invocation active-entry migration；
本阶段不建设A的跨进程durable continuation平台。该选择不等于B实施授权：在新的B精确implementation contract获得
独立`approved`前，`implementation_authorization=not_granted`，P2.2a–d/P2.3–P4全部停止。

用户架构选择checkpoint固定为：

```yaml
architecture_boundary_verdict: option_b
user_architecture_selection: option_b
product_requirement:
  - 移除run_local_request与CLI对Graph route、Store outcome和terminal disposition的shadow authority
  - 保持existing StateGraph拥有same-invocation Proposal/Repair/Build/Runtime/Eval lifecycle
non_requirement:
  - 本阶段不要求跨进程structural continuation、exactly-once、自动crash recovery或C5 receipt重建
existing_owner_mapping:
  graph: same-invocation lifecycle route与conditional edges
  store: 每次Artifact write的C5 outcome
  checkpoint: 既有显式Human/cross-invocation handoff，不扩成ordinary same-invocation协议
  approval: 既有sub-action canonical identity与经验证permission/binding facts各自保留原owner
  run_local_request: validated inputs/effect adapters准备与legacy Presentation
authority_to_remove:
  - run_local_request的graph.invoke与current_stage/Build/Runtime claims终态解释
  - CLI基于current_stage或Build/Runtime claims决定exit code
authority_to_preserve:
  - existing StateGraph nodes、conditional edges、repair budget及domain route semantics
  - Store-owned ArtifactWriteResult三态
  - 既有sub-action identity、Artifact lineage和Human Resume语义
minimum_public_contract:
  - 一个Public Product Executor public pair
  - 一个typed product-executor Graph mode；exact carrier与owner由B implementation contract固定
  - 一个strict ProductExecutionResultV1，覆盖全部active reachable Store attempts并按phase/attempt嵌套
  - noncommitted Store result后的first-failure-stop与Graph外零第二route/status/receipt owner
durability_decision:
  selected: same_invocation_only
  rationale: 当前active-entry migration没有证明跨进程逐attempt continuation是必要产品能力
compatibility_boundary:
  - 保持现有same-invocation Graph lifecycle、最多两次repair、历史Artifact与Human Resume可读/可用
  - hard exit可能不返回structured result；不自动重入、不恢复、不重建receipt
estimated_change_surface:
  architecture_packages:
    - B1 product result与active Graph C5 facts
    - B2 Public Product Executor与真实failure matrix
    - B3 run_local/CLI adoption及旧authority退出
  exact_files_schemas_tests: 由B implementation contract在源码inventory后固定
rejected_alternative:
  option_a: 本阶段不选择；其durable consumption/crash/replay平台能力超出当前已证明需求
unresolved_contract_decisions: []
implementation_authorization: not_granted
```

分层规则：

1. C6 typed operation authority与核心代码提交事实保持，不因后续入口inventory被重写；但C6完成验收必须
   补齐七shape真实公共链矩阵与Build生产adapter采用证明。
2. `evidence-request`、`intelligent-evidence-request`与`run_local_request()`属于C7/platform active-entry
   inventory，不反向塞进C6B；inventory必须以真实public/CLI入口展开，而不是只扫描若干核心文件。
3. 全仓库回归与受控真实产品Build/Runtime是工程/产品验证门，不重新定义Approval Identity、Store三态或
   semantic owner；缺少这些证据时不得声称迁移后的产品行为已经重新验证。
4. 第二产品切片与后置Authority文档归并仍受§17整体完成条件约束；任何局部工作包完成都不能替代它们。

当前唯一推进顺序固定为：

```text
P0  §11.5独立合同审核→有界实施→独立实施后验收
P1  C6七shape真实公共链矩阵；测试发现旁路时另开最小修复合同
P2  Build生产adapter→run_local_request()→intelligent-evidence-request→evidence-request，逐入口单独开包
P3  按CLI/public function/MCP/HTTP/UI真实入口重跑active-entry inventory
P4  focused authority→全仓库回归→受控真实Build/Runtime→第二产品切片→Authority文档归并与最终审核
```

未轮到的条目保持`*_not_started`或`pending_preceding_migrations`，不得在当前工作包顺带实施。
Repair Planning与dynamic review保持`deferred_non_active`；MCP、HTTP API和Mod Agent Dashboard当前保持
只读adapter，不建立执行型迁移包。`local_entry.py`文件体量不单独触发重构，只允许在对应authority迁移
中净减少旧分支。

##### 15.11.2.14 Option B 单一实施合同：same-invocation Public Product Executor

> **合同状态**：`independently_approved_pending_implementation`；
> `contract_verdict=approved`；`implementation_authorization=granted_within_§15.11.2.14_exact_scope`；
> 批准绑定文档SHA256=`3E954A76DF8141347960DE1888C92BE3947C93113C0586330B9E213EC82C105A`。
> **本轮时间盒**：`started_at=2026-08-07T15:01:21.3958612+08:00`，
> `target_checkpoint=2026-08-07T16:01:21.3958612+08:00`，
> `absolute_hard_stop=2026-08-07T16:31:21.3958612+08:00`。本节只授权只读源码inventory与本权威文档修改；
> 独立`contract_verdict=approved`前不得修改生产代码、测试、Store或Git index。

本合同把§15.11.2.13已经由用户选择并独立确认的Option B一次性闭合为三个实施章节。三个章节共享同一public
contract、同一result/C5 owner和同一active-entry迁移边界；它们不是三轮合同。合同approved后允许按I/II/III三个
代码checkpoint连续实施、分别运行focused tests，最后只形成一个整包staged identity并做一次正式独立实施后验收。
任何checkpoint发现需要改变本节public schema、authority、C5终态、Graph lifecycle或兼容矩阵时必须停止并重新送审。

###### 15.11.2.14.1 真实active Graph/Store inventory与条件路径

当前`run_local_request()`构造普通Graph时不传`verification_operation`。因此下表所有active Store调用都必须在
product-executor mode中使用`ArtifactStore.write_with_result()`；已有只在verification controls下启用的C5分支必须
委托同一product recorder，而不是保留第二种result解释。`Store role`按一次真实调用记录，repair中的重复role按
`repair_attempt`重复出现，不压成unique-role chain。

| Graph node / exact symbol | Store role与调用次序 | domain short-chain / reachable branch | P2.2处理 |
| --- | --- | --- | --- |
| `plan_request` / `_run_plan_request` | `request_planning_report` | `plan.blocked=true`后进入`blocked` | `write()`→`write_with_result()` |
| `planning_brief` / `_run_planning_brief` | `mod_planning_brief` | `planning_brief.blocked=true`后进入`blocked` | 同上 |
| `draft_feature_spec` / `_run_draft_feature_spec` | `feature_spec` | `feature_spec.blocked=true`后进入`blocked` | 同上；`_materialize_feature_spec_revision`不在当前入口scope |
| `retrieve_evidence` / `_run_retrieve_evidence` | `evidence_pack` | `can_generate_patch=false`后进入`blocked` | 同上 |
| `create_implementation_plan` / `_run_create_implementation_plan` | `implementation_plan` | `implementation.blocking=true`后进入`blocked` | 同上 |
| `generate_patch_proposal` / `_run_generate_patch_proposal` | `patch_proposal` | blocked proposal进入`blocked`；repair轮次重复该role | 同上 |
| `review_proposal` / `_run_review_proposal` | 可选`critic_assessment`，随后`proposal_review` | critic committed后review仍必须真实执行；review可进入dry-run、repair或blocked | 两次调用均迁移；任一noncommitted后停止且不调用下一次Store |
| `dry_run_apply` / `_run_dry_run_apply` | `dry_run_result` | review/human gate未通过时committed blocked结果进入`blocked` | 同上 |
| `isolated_apply` / `_run_isolated_apply` | `isolated_apply_result` | exact diff reject、未批准或apply失败均是committed domain结果并进入`blocked`；apply effect=0或按真实调用记录 | 同上 |
| `build` / `_run_build` | `build_result`；compile-only成功时随后`workflow_checkpoint` | failed mutation Build进入repair；blocked进入`blocked`；compile-only成功必须同时commit checkpoint才算成功 | BuildResult与checkpoint都保留C5 receipt；不改Build lineage/route |
| `create_repair_plan` / `_run_create_repair_plan` | `repair_plan` | `RepairPlanner(retry_budget=2)`；有blocker/预算耗尽后进入`blocked`，否则进入下一Proposal轮次 | 同上；budget仍由现有Planner+Graph state拥有 |
| `resolve_runtime_binding` / `_run_resolve_runtime_binding` | `binding_resolution` | product-behavior repair binding可继续repair；blocked进入`blocked` | 同上 |
| `collect_runtime_evidence` / `_run_runtime_evidence` | `runtime_evidence` | accepted进入Eval；适用时进入binding/repair；否则进入blocked | product mode统一启用现有`write_with_result()`分支 |
| `evaluate` / `_run_fake_evaluate` | `eval_report` | gate blocked进入`blocked`；其他进入`done` | product mode统一启用现有C5分支 |
| `done` / `_run_workflow_summary` | `workflow_summary` | runtime scope成功只在exact accepted terminal payload committed后成立 | product mode统一启用现有C5分支 |
| `blocked` / `StubNodeRunner.run` | `blocked_report` | 只表示Graph已经选出的domain terminal；不得用于包装平台Store/execution失败 | product mode启用C5；平台first-failure-stop直接END，不再写本role |

`_materialize_feature_spec_revision`只在`feature_spec_revision_projection`非空时可达；当前`run_local_request()`没有该输入，
本包不修改、测试或宣称迁移该条件路径。dynamic Human review、Edit Authority、Repair Planning Authority与manual/cross-process
Runtime Resume仍使用原有独立入口和协议，不进入ordinary same-invocation product mode。

###### 15.11.2.14.2 共享exact公共类型、owner与结果矩阵

新增纯合同模块`src/mod_agent/product_execution.py`，不得导入`local_entry.py`或`workflow/graph.py`。它是以下exact
schema、严格parser和projector的唯一owner：

1. `ProductExecutionRequestV1`：exact字段为`contract_version="1"`、`run_id`、`request_id`、`user_request`、
   `target_domain`、`target_mod`、`requested_completion_scope`（`compile_only|runtime_workflow`）、
   `repair_budget=2`、absolute `isolated_workspace_root`、absolute `isolated_target_root`、absolute `source_root`、
   absolute `artifact_store_root`、`source_snapshot_sha256`、`isolated_source_snapshot_sha256`、
   exact ordered `input_bindings`、exact sorted `completion_classification`、exact bool
   `confirmed_isolated_write`与exact bool `allow_build`。ready preflight要求后两者均true；这些是
   execution/permission facts，不构成workflow Approval Identity。run/request/user/target字段均为non-empty string；四个root均为
   normalized absolute string；两个snapshot SHA均为64位小写hex；repair_budget必须是exact int 2而非bool；`input_bindings`必须是
   tuple且逐项为严格`ProductExecutionInputBindingV1`；unknown/extra/missing/type/null一律拒绝。
2. `ProductExecutionAdaptersV1`由`src/mod_agent/product_executor.py`拥有，exact字段为
   `evidence_pack_factory`、`patch_change_factory`、`dry_run_factory`、`isolated_apply_factory`、
   `build_result_factory`、nullable `runtime_evidence_factory`、nullable `compiled_artifact_verifier`与nullable
   `source_change_verifier`。compile-only要求runtime adapter为null；runtime scope要求非null。测试可注入确定性adapter；
   生产adapter仍由`run_local_request()`按现有权限、settings和physical binding构造。callable不序列化、不持久化、不进入任何
   request/result/hash；preflight与execute只比较exact字段拓扑、callable类型与scope，不要求同一个
   `ProductExecutionAdaptersV1`或callable对象实例。
3. `ProductExecutionGraphModeV1`：data-only frozen carrier，exact字段为`contract_version="1"`和完整
   `ProductExecutionRequestV1`；`build_graph(..., product_execution_mode=...)`是唯一Graph carrier。它不携callable、route、
   result status、receipt或Approval hash，且不能与`verification_operation`、Authority gate、feature revision、legacy
   `stop_after_build`/`persist_build_runtime_handoff`/interrupt selector混用。
4. `ProductExecutionInputBindingV1`：exact字段为`contract_version="1"`、`binding_kind`
   （`source_revision_binding|source_disclosure|model_admission|runtime_admission`）、对应exact
   `binding_contract_version`（依次为`source_revision_binding_v1|source_disclosure_v1|model_admission_v1|runtime_admission_v1`）、
   `canonical_payload`与`canonical_payload_sha256`。payload只允许recursive JSON
   null/bool/int/string/list/object（object key必须string），hash一律委托C2/C3中立canonical JSON/SHA256 primitive并逐字重算；
   它是input integrity，不是Approval Identity。四项必须按上述顺序各出现一次；source revision payload允许null或object，其他
   三项必须object。`canonical_payload`是对应既有owner本次产生的完整record，而不是Product Executor重新定义的字段projection：
   source revision仍由`_verify_source_revision_binding`拥有；source disclosure仍由
   `_source_disclosure_record|_local_no_external_disclosure_record`拥有；model admission仍由
   `_external_model_admission_record|_local_model_admission_record`拥有；runtime admission仍由`_runtime_admission_record`及其runtime
   profile/capability owner拥有。`binding_contract_version`只版本化wrapper与owner选择，不取得、复制或冻结owner payload内部schema。
   `ProductExecutionInputBindingV1.from_dict`只验证wrapper exact shape、canonical JSON类型、kind/version组合与payload hash，不解释
   payload内部业务字段；ready preflight必须另外通过fixed `ProductExecutionInputBindingResolverV1`委托上述唯一owner校验
   owner-produced record与request scope/adapter topology的一致性。resolver不接受caller validator callable，也不得保存
   disclosure/model/runtime/source字段旁表。为消除`product_executor→local_entry`反向导入，实施时把上述六个既有
   builder/validator符号机械迁移为`product_executor.py`中的唯一原定义，`local_entry.py`删除原函数体并直接import/delegate同一符号；
   runtime profile/capability的下层owner仍在现有runtime模块。迁移前后record bytes、字段解释、失败边界与所有legacy caller不变；
   严禁复制实现形成schema双owner。
   execute再次逐字比较preflight的四个binding wrapper bytes，并在Graph/effect前委托同一resolver做TOCTOU一致性重验；model response与
   Runtime physical destination仍由既有effect owner在实际调用前重验。`completion_classification`为按key
   UTF-8排序、key唯一非空string/value exact bool的tuple；空tuple表示不适用。

当前P2.2 public pair的授权真实性边界明确收窄为active product entry adoption：`run_local_request()`是唯一production request
creator，它先从本次真实`allow_source_disclosure`、model/settings、`run_gtfo_runtime`、`allow_game_launch`、
`runtime_plugin_destination`与`allow_game_directory_write`输入调用既有owner，随后才把owner-produced record放入binding wrapper。
public pair保证wrapper/hash、scope、adapter、Graph与effect之间逐字一致，但不声称仅凭record+self-hash可以独立证明任意Python
caller的授权来源，也不登记“拒绝所有self-hash伪造”为V1能力。existing outer authorization与各effect前physical validation保持
唯一真实性owner；未来若要把该pair开放为不经过active entry的独立授权API，必须另审raw authorization input contract，不能通过
解释payload内部字段补齐。
5. `ProductExecutionStoreAttemptV1`：exact字段为`contract_version="1"`、从0连续递增的`sequence`、`phase`、
   `repair_attempt`（0..2）、
   exact `node_name`、exact `artifact_role`和Store-owned `ArtifactWriteResult`。`ProductExecutionOutputV1`逐项保存同一
   `contract_version="1"`、sequence/phase/attempt/node/role与committed `ArtifactRef`。
   phase值域固定为`planning|evidence|proposal|application|build|repair|runtime|evaluation|terminal`，node对应phase只由下述
   declaration的`node_phases`解释。sequence/repair_attempt均须为exact int而非bool。
   `ProductExecutionEffectEventV1`按调用先后保存`contract_version="1"`、从0连续递增的`sequence`、`phase`、`repair_attempt`、`effect_role`
   （`evidence_retrieval|patch_generation|dry_run|isolated_apply|build|runtime`）、`event_status`
   （`started|completed|failed`）、nullable `failure_class`与nullable `failure_message`。每次effect必须先有started，
   completed/failed必须紧随同role/phase/attempt的started且二选一；started/completed要求failure字段均null，failed要求两者
   non-empty。它只回答effect是否可能开始，不替代Artifact或domain结果；callable本身不序列化、不持久化、不进入任何hash。
6. `ProductExecutionPreflightResultV1`：exact字段为`contract_version="1"`、`preflight_status`（`ready|blocked`）、
   non-null exact `request`、`failure_stage`（`authorization|admission|execution_constraint|null`）与exact
   `blockers: tuple[ProductExecutionBlockerV1,...]`。ready要求failure null且blockers空；blocked要求failure non-null、
   至少一个platform blocker且Graph/Store/effect调用全为0。未知/extra/type错误在request形成前抛ContractError，不伪造
   nullable request。它没有Approval hash或Envelope。
7. `ProductExecutionResultV1`：exact字段为`contract_version="1"`、`run_id`、`request_id`、nullable `feature_id`、
   `requested_completion_scope`、`platform_status`（`completed|blocked|partial`）、`execution_disposition`
   （`succeeded|domain_blocked|platform_blocked|partial`）、nullable closed `failure_stage`、
   `side_effects_may_have_started`、`terminal_node`（`build|done|blocked|null`）、ordered `store_attempts`、ordered
   `outputs`、exact `effect_events`、exact `ProductExecutionValidationFactsV1`、
   `blockers: tuple[ProductExecutionBlockerV1,...]`和exact
   `variant_result: ProductBuildCompletionV1|ProductRuntimeCompletionV1`。result不保存Presentation/audit错误、run-local文件路径、
   Store totals或latest alias判断。run/request必须与request逐字相同且non-empty；feature_id若non-null必须non-empty；
   `side_effects_may_have_started`必须exact bool；in-memory collection统一为tuple，`to_dict`唯一投影为JSON array，`from_dict`
   只接受array并按原序恢复tuple；extra/missing/type/null/order drift一律拒绝。
8. `ProductExecutionBlockerV1` exact字段为`contract_version="1"`、`owner`（`domain|platform`）、non-empty `stage`、non-empty
   `code`、non-empty `message`与non-empty `source_node`。domain blocker只能来自现有Graph node冻结输出；platform
   blocker只能由product Graph boundary/preflight产生。completed+succeeded要求两类blocker均空；completed+domain_blocked
   至少一个domain blocker且platform blocker为空；blocked/partial要求至少一个platform blocker。
9. `ProductExecutionValidationDetailV1` exact字段为`contract_version="1"`、`detail_kind`
   （`output_readback|canonical_source|compiled_artifact|source_change|completion_classification`）与recursive canonical JSON
   `payload`；它保存现有legacy audit所需的exact verifier输出，但不能独立改变status。`ProductExecutionValidationFactsV1`
   exact字段为`contract_version="1"`、`output_readback_status`、`canonical_source_status`、`compiled_artifact_status`、`source_change_status`、
   `completion_classification_status`（各为`not_applicable|passed|failed`）、nullable `failure_class`、nullable
   `failure_message`和按上述kind固定顺序、每kind恰一项的`details`。任一failed要求failure两字段non-empty并强制
   partial/post_execution_validation；全为passed/not_applicable要求failure两字段null。验证顺序固定为上述五项并first-failure-stop：
   失败项detail payload=null，失败后的项status=`not_applicable`且payload=null；失败前已完成项保留真实payload。无committed output时
   output readback为not_applicable，否则必须passed或failed；canonical-source在Graph已invoke后适用；compiled artifact只在
   real successful Build后适用；source-change只在successful Build且adapter非null时适用；completion classification只在request
   tuple非空时适用并要求successful Build及前两个适用verifier均passed。status为not_applicable要求对应payload=null；passed要求
   payload为当次fixed validator实际返回的canonical JSON，不能伪造成功payload。
10. `ProductBuildCompletionV1` exact字段为`contract_version="1"`、nullable `build_result_ref`、nullable `workflow_checkpoint_ref`、
    `build_status`（`not_reached|unavailable|success|failed|blocked`）和nullable exact bool `claims_real_build_success`。
    status与ref/claim逐项绑定：`not_reached`要求build ref与claim均null；`unavailable`要求build ref non-null而claim null；
    `success|failed|blocked`要求build ref non-null，success要求claim=true，failed|blocked要求claim=false；checkpoint ref non-null只允许
    compile scope successful full chain。
    succeeded要求两ref non-null、status=success、claim=true；domain_blocked要求blocked_report在common outputs中committed，且build
    status/ref按实际prefix满足上述规则；platform blocked/partial按真实prefix允许尚未到达字段为not_reached或已无法readback字段为unavailable。
11. `ProductRuntimeCompletionV1` exact字段为`contract_version="1"`、nullable `build_result_ref`、`runtime_evidence_ref`、`eval_report_ref`、
    `workflow_summary_ref`、`blocked_report_ref`，`build_status`
    （`not_reached|unavailable|success|failed|blocked`）、`runtime_status`
    （`not_reached|unavailable|accepted|not_accepted|blocked`）、`eval_verdict`
    （`not_reached|unavailable|accepted|blocked|inconclusive`）和`final_status`
    （`not_reached|unavailable|accepted|blocked|inconclusive`）。succeeded要求前四ref non-null、blocked ref null及
    success/accepted/accepted/accepted。build/runtime/eval三阶段的`not_reached`要求对应ref null，`unavailable`要求对应committed ref
    non-null但payload事实不可读，其他非`not_reached`值要求对应ref non-null并逐字来自该Artifact payload；后一阶段非not_reached前，
    所有前置阶段必须已经有committed ref。`final_status=not_reached`要求summary/blocked refs均null；`accepted|inconclusive`要求summary
    ref non-null且blocked ref null；`blocked`要求blocked ref non-null且summary ref null；`unavailable`要求summary/blocked refs恰有一个
    non-null并指向不可读的实际committed terminal Artifact。domain_blocked要求blocked ref non-null、summary ref null且其余字段逐项匹配
    实际committed prefix；platform blocked/partial只允许对应prefix中实际committed refs，不能用status填充值代替missing Artifact。

`ProductExecutionResultV1.from_dict`必须只委托`project_product_execution_result()`和
`ArtifactWriteResult.from_dict()`重放全部不变量；不得在CLI、local entry、Graph或第二parser复制status/receipt规则。
projector只消费resolved product declaration、Graph实际终端fact、exact immutable output payload、ordered Store facts和
effect events；不得读取latest、revision totals、current filesystem existence、stdout、manifest或Presentation。
`failure_stage`的closed owner同样是`ProductExecutionDeclarationV1`：只允许`graph_start`、
`post_execution_validation`，以及由同一declaration的exact node生成的`<node_name>_execution`和由其exact Store role生成的
`<artifact_role>_store`；caller不能提交任意字符串。`ProductExecutionValidationFactsV1`保存fixed executor对canonical
source unchanged、exact compiled artifact、适用source-change与completion classification boundary的通过/失败事实及其
non-authoritative detail；这些验证必须在machine result冻结前完成，失败时不得先返回succeeded。
`validate_product_execution_facts`先完成strict canonical fact validation；`project_product_execution_result`对已通过该
validator的facts必须是deterministic total function，不存在`result_projection` machine failure stage。未知version/shape、
不合法trace或编程输入抛`ProductExecutionContractError`；若Graph副作用已经发生，公共调用不得用fallback projector伪造
`ProductExecutionResultV1`，也不得自动重入，已经committed的C5/Artifact事实保持有效。

结果矩阵固定为：

| facts | `platform_status` | `execution_disposition` | terminal/output要求 |
| --- | --- | --- | --- |
| compile scope：real successful final BuildResult与其WorkflowCheckpoint均committed | `completed` | `succeeded` | terminal=`build`；两项均有同序matching committed receipt |
| runtime scope：final successful Build、accepted RuntimeEvidence、accepted EvalReport与accepted WorkflowSummary均committed | `completed` | `succeeded` | terminal=`done`；exact terminal chain与matching receipts齐全 |
| Graph按现有conditional edge到`blocked`且BlockedReport committed | `completed` | `domain_blocked` | terminal=`blocked`；保留所有committed prefix；failure_stage=null |
| exact diff明确reject并commit blocked IsolatedApplyResult，随后BlockedReport committed | `completed` | `domain_blocked` | apply effect=0；不得改写为platform failure |
| 首次Store调用`blocked_before_commit`，此前无committed output且无effect started | `blocked` | `platform_blocked` | terminal=null；保留唯一noncommitted receipt；无output |
| 任意Store `partial`，或Store failure前已有committed output/effect可能开始 | `partial` | `partial` | exact committed prefix+最后noncommitted receipt；后续Store/effect=0 |
| catchable node/effect异常且无committed prefix、可证明effect未开始 | `blocked` | `platform_blocked` | 无伪造receipt；exact node execution stage |
| catchable node/effect异常且已有committed prefix或effect可能开始 | `partial` | `partial` | 保留prefix/effect fact；无伪造receipt；后续调用=0 |
| Graph outputs committed后exact output readback或fixed canonical-source/compiled-artifact/source-change/completion-classification validation失败 | `partial` | `partial` | failure_stage=`post_execution_validation`；保留全部真实Store facts，unreadable payload status=`unavailable`，不声称product success |
| 进程硬退出/BaseException/进程终止 | 无结果保证 | 无结果保证 | 不自动重入、retry/recovery；不从Artifact/latest/run-local文件重建旧receipt或伪造result |

ordered不变量为：每个actual Store调用恰有一个attempt；committed attempt逐项产生同sequence/phase/attempt/node/role/ref的
output；noncommitted attempt至多一个且必须最后；noncommitted后Graph不得调用任何Store或effect；没有调用就没有receipt；
重复repair role必须保留不同repair_attempt和sequence。`request planning→terminal`的node-role allowlist由
`ProductExecutionDeclarationV1.node_store_roles`在同一模块唯一登记，恰为§15.11.2.14.1表；不得在Graph、local entry或
测试建立第二张role/terminal表。

`ProductExecutionDeclarationV1`的exact frozen字段为`contract_version="1"`、ordered
`node_store_roles: tuple[(node_name, artifact_role),...]`、ordered
`node_phases: tuple[(node_name, phase),...]`与exact `lifecycle_grammar: ProductExecutionLifecycleGrammarV1`。
`ProductExecutionLifecycleGrammarV1`是strict result trace语法的唯一owner；其exact frozen字段为
`contract_version="1"`、ordered `initial_prefix: tuple[str,...]`、ordered
`allowed_successors: tuple[(node_name, tuple[next_node,...]),...]`、ordered
`repair_transition_sources: tuple[str,...]`、exact int `max_repair_attempt=2`与ordered
`terminal_nodes: tuple[str,...]`。所有tuple non-empty、node string non-empty且同一map key唯一；每个grammar node必须存在于
`node_phases`，每个Store node必须存在于`node_store_roles`，无Store route node不得出现在该role表；所有Store role必须恰为
§15.11.2.14.1 allowlist中的role，phase必须属于上述闭合值域。
constructor/from_dict逐字拒绝extra/missing/type/order drift。它只验证Graph已经冻结的history，绝不供Graph
选择实时next route。exact grammar固定为：

- attempt 0 initial prefix只能是下列ordered tuple的合法前缀：
  `plan_request→planning_brief→draft_feature_spec→retrieve_evidence→create_implementation_plan→generate_patch_proposal→review_proposal`；
  前五个planning/evidence节点各最多一次，禁止重复、跳过或在Build之后出现；
- proposal cycle从`generate_patch_proposal→review_proposal`开始，随后只允许
  `dry_run_apply→isolated_apply→build`、`create_repair_plan`或`blocked`；product mode的non-null
  `isolated_apply_factory`与`confirmed_isolated_write=true`使isolated apply成为所有成功Build链的必经node，绝不允许
  `dry_run_apply→build`；optional
  `critic_assessment`只能位于同一review node的`proposal_review`之前，不能单独结束success；
- product mode的`allowed_successors`必须逐字登记现有resolved route：`review_proposal→(dry_run_apply|create_repair_plan|blocked)`、
  `dry_run_apply→(isolated_apply|blocked)`、`isolated_apply→(build|blocked)`；不得沿用base registry中仅在factory为null时存在的
  `dry_run_apply→build`。exact diff reject、未批准或apply failure由committed IsolatedApplyResult形成domain fact后只进入`blocked`；
- failed Build、revise Proposal或适用Runtime/binding failure可以进入`create_repair_plan`。只有committed non-blocking
  RepairPlan才能把repair_attempt从N增加到N+1并回到PatchProposal；attempt必须连续0→1→2，不得跳号、倒退或超过2；
  同一repair attempt内Proposal/Review/DryRun/Apply/Build的attempt值逐字一致；
- successful Build在compile scope只允许随后committed WorkflowCheckpoint并以terminal=build结束；runtime scope只允许
  `collect_runtime_evidence→evaluate→(done|blocked)`，或从Runtime进入
  `resolve_runtime_binding→create_repair_plan`/`create_repair_plan`/`blocked`；WorkflowSummary只能紧随committed
  EvalReport的done route；
- domain short-chain只能在现有conditional edge已经选择blocked后追加一个BlockedReport并结束；platform
  first-failure-stop在失败node直接结束且不得追加BlockedReport；noncommitted Store attempt或failed effect event之后无后继；
- exact合法terminal为compile `build`、runtime `done`或domain `blocked`。任何其他committed-only prefix只有在同一
  result存在合法platform failure stage时才能结束，不能投影completed。

constructor与strict parser必须用该grammar拒绝Build早于Evidence、Summary早于Eval、重复planning、缺少上一轮repair的
attempt=2、跨attempt role错位、跳过isolated_apply后出现committed Build及其他非法短链；正向门覆盖repair 0→1→2、compile success、runtime success、early domain block、
exact-diff reject、Eval→Blocked与repair exhausted。grammar改变属于public result contract变化，必须重新审核。

domain completion predicates固定为：compile success必须是final BuildResult payload `status="success"`且
`claims_real_build_success=true`并有committed WorkflowCheckpoint；runtime success必须是exact final RuntimeEvidence
accepted、EvalReport verdict accepted且WorkflowSummary `final_status="accepted"`。任何较短prefix不能仅因role合法而成为
succeeded。Graph到blocked且BlockedReport committed才是domain_blocked；review revise、failed Build或Runtime repair route在
repair budget未耗尽时都不是terminal result。projector只能验证Graph已选route，不另算下一route。

common nullability固定为：completed要求failure_stage=null、feature_id non-null、terminal_node non-null且无platform blocker；
completed+succeeded要求全部blocker为空；completed+domain_blocked要求terminal_node=blocked且至少一个domain blocker。
blocked/partial要求failure_stage non-null、至少一个platform blocker；blocked要求outputs为空、store_attempts只允许零项或一个
blocked_before_commit；partial允许committed prefix并可有一个最后noncommitted。side_effects_may_have_started只由effect event
的started事实决定，不从Artifact commit反推。from_dict必须逐项重放这些规则。

###### 15.11.2.14.3 A—Result/C5边界实施表

| 字段 | 精确合同 |
| --- | --- |
| `current_authority` | 普通product Graph各node调用兼容`write()`；Build/Runtime/Eval/Summary/Blocked的C5分支只受verification controls启用；`run_local_request()`从Graph summary/claims解释终态。 |
| `target_authority` | Store独占单次C5三态；`ProductExecutionDeclarationV1`+`project_product_execution_result()`独占ordered product result；existing conditional edges独占domain lifecycle route。 |
| `removed_authority` | 所有active node兼容`write()`路径、Graph summary到platform status的外围解释、flat unique-role chain、ref/latest/totals到receipt的反推。 |
| `public_contract` | §15.11.2.14.2的StoreAttempt/Output/Effect/Result exact schema与结果矩阵；不修改`ArtifactWriteResult` public schema。 |
| `compatibility` | Artifact payload、status、upstream order、Registry/Store semantic validation、repair budget=2、conditional edges与historical Artifact bytes不变；domain-short-chain语义不变。 |
| `semantic_boundary` | product mode只把真实Store facts放入ephemeral Graph state；平台failure执行first-failure-stop；domain blocked仍由Graph进入BlockedReport；hard exit无result保证。 |
| `exact_files` | `src/mod_agent/product_execution.py`（new）、`src/mod_agent/workflow/graph.py`、`src/mod_agent/workflow/state.py`、`src/mod_agent/workflow/nodes.py`、`tests/unit/test_product_execution.py`（new）、`tests/unit/test_workflow_graph.py`。 |
| `exact_symbols` | `ProductExecutionDeclarationV1`、`ProductExecutionGraphModeV1`、`ProductExecutionStoreAttemptV1`、`ProductExecutionOutputV1`、`ProductExecutionEffectEventV1`、`ProductExecutionResultV1`、`project_product_execution_result`、`build_graph`、`ModAgentState`、`StateOwnershipPolicy`、表§15.11.2.14.1全部node函数、`StubNodeRunner.run`。 |
| `authority_tests` | 参数化每个active Store调用的blocked_before_commit/partial/committed；noncommitted-last、repeated repair role、critic-first-stop、compile checkpoint failure、terminal blocked failure；supporting wrapper schema exact/extra/nullability与binding hash/owner重验；静态/委托spy证明Product Executor没有复制source disclosure/model/runtime/source revision字段表或validator，legacy与public pair只命中同一owner；lifecycle grammar拒绝Build-before-Evidence、Summary-before-Eval、重复planning、repair跳号/错位/非法短链并接受repair 0→1→2及全部合法terminal；strict parser roundtrip与伪造/乱序receipt拒绝；静态证明普通product mode无`write()`。 |
| `integration_test` | temporary filesystem ArtifactStore上的compile success、runtime success、exact-diff reject、Build repair success、repair exhausted、early planning blocked与每phase Store failure；只注入确定性test adapters。 |
| `stop_conditions` | 需要改Artifact/Registry/C5 schema、改变Graph conditional edge或repair budget、需要第五种result owner、发现未登记active Store调用或现有合法domain route被拒绝时停止回审。 |
| `unresolved_contract_decisions` | `[]` |

###### 15.11.2.14.4 B—Public Product Executor实施表

| 字段 | 精确合同 |
| --- | --- |
| `current_authority` | `run_local_request()`直接`build_graph()`、`create_initial_state()`、`graph.invoke()`；Graph普通模式无统一C5 recorder；外层从state生成machine verdict。 |
| `target_authority` | `src/mod_agent/product_executor.py::preflight_product_execution`与`execute_product_execution`是唯一public pair；execute重跑preflight，构造exact Graph mode与initial state，只调用一次existing StateGraph，并把Graph facts交唯一projector。 |
| `removed_authority` | public caller直接传product route bool/string、在Graph外选择Build/Repair/Runtime/Eval next node、通过private dict/callable dispatcher解释terminal、构造workflow总Approval hash；`local_entry`中六个input-record owner的旧函数体删除，只保留对迁移后同一符号的调用。 |
| `public_contract` | 输入为`ProductExecutionRequestV1`、`ProductExecutionAdaptersV1`和ArtifactStore；preflight返回`ProductExecutionPreflightResultV1`；execute只接受ready preflight对应的exact request/adapters并返回`ProductExecutionResultV1`。execute重跑preflight时要求request与四个input binding canonical bytes逐字相等，并重验adapter字段presence/callable type与completion scope拓扑；不要求同一callable对象实例，也不序列化/hash callable。无expected approval hash、ResumeReport或cross-call authorization。 |
| `compatibility` | `run_local_request()`原参数、compile-only stop+checkpoint、optional Runtime、same-invocation repair最多2次、exact diff交互、actual Human/cross-process Resume均保持；现有verification operation public pairs不变。 |
| `semantic_boundary` | whole workflow无总Approval Identity。已有canonical sub-action identity继续调用原owner；`_read_exact_diff_approval`/PatchApplier exact diff、BuildResult immediate lineage、`_runtime_admission_record`与runtime factory permission只作为各自可信binding，由原validator在effect前重验，不升级为workflow identity。Graph START逐项比较initial state与exact request；各effect adapter调用前再次验证scope/adapter topology与其原有physical binding；canonical-source/compiled-artifact/source-change fixed validation在result冻结前完成。 |
| `exact_files` | `src/mod_agent/product_execution.py`（new）、`src/mod_agent/product_executor.py`（new）、`src/mod_agent/workflow/graph.py`、`src/mod_agent/workflow/state.py`、`tests/unit/test_product_execution.py`（new）、`tests/unit/test_workflow_graph.py`。 |
| `exact_symbols` | `ProductExecutionRequestV1`、`ProductExecutionInputBindingV1`、`ProductExecutionInputBindingResolverV1`、`ProductExecutionAdaptersV1`、`ProductExecutionPreflightResultV1`、`ProductExecutionGraphModeV1`、`ProductExecutionResultV1`、`validate_product_execution_facts`、`preflight_product_execution`、`execute_product_execution`、`_verify_source_revision_binding`、`_source_disclosure_record`、`_local_no_external_disclosure_record`、`_external_model_admission_record`、`_local_model_admission_record`、`_runtime_admission_record`、`build_graph`、`create_initial_state`。 |
| `authority_tests` | unknown/extra/version/type/mixed verification+product mode拒绝；Graph START request drift在首个Store/effect前拒绝；scope/adapter mismatch拒绝且不要求callable对象identity；四个binding wrapper parser只管wrapper/hash且fixed resolver逐项委托原owner，production request必须由run_local的显式授权输入命中同一owner，wrapper/hash或scope漂移拒绝，但不虚构“仅凭payload证明任意Python caller授权来源”的测试；public execute只invoke Graph一次；canonical fact validator错误不得调用fallback projector，pre-effect ContractError与post-Graph ContractError的side-effect/null-result边界分别锁定；projector/parser唯一；无Approval hash/ResumeReport/A方案字段。 |
| `integration_test` | public preflight→execute→real existing Graph→temporary Store→strict result；compile/runtime/repair路径均record-and-delegate真实Graph，不mock public pair或直接`graph.invoke`冒充公共链。 |
| `stop_conditions` | 需要新增Artifact/Approval/Resume union/Runtime v2、cross-process exactly-once、改变verification identity bytes、让executor维护第二route表、为input binding复制既有schema/validator或需要Graph外恢复hard-exit调用时停止回审。 |
| `unresolved_contract_decisions` | `[]` |

catchable pre-Graph public shape/admission错误在ready preflight形成前返回blocked preflight，Graph/Store/effect=0。execute开始后可归属
的node/Store/effect失败必须返回§15.11.2.14.2 machine result。输入端错误Python类型、未知contract version或extra fields在
Graph前抛`ProductExecutionContractError`且零副作用；Graph返回后的canonical fact validator若发现平台编程错误，同样抛
`ProductExecutionContractError`但不得声称零副作用、不得伪造ProductExecutionResult或自动重入，durable Store事实保持。
该异常exact字段为non-empty `reason`与exact bool `side_effects_may_have_started`；CLI只输出
`{status:"CONTRACT_ERROR",reason,side_effects_may_have_started}`并exit2，顶层status不是product platform verdict。
Public Product Executor不写run manifest/result JSON；这些是active entry的Presentation/audit。硬退出可能没有返回值，且本合同
不增加持久化result或恢复协议。

###### 15.11.2.14.5 C—Active Entry降级实施表

| 字段 | 精确合同 |
| --- | --- |
| `current_authority` | `local_entry.py::run_local_request`直接Graph invoke并读取`current_stage`、`build_summary.claims_real_build_success`、`runtime_summary`、artifacts生成终态；`cli.py::run-request`再次按`current_stage`与Build/Runtime claims决定exit。 |
| `target_authority` | `run_local_request`只准备workspace/model/exact request/effect adapters，调用public preflight+execute，并从冻结ProductExecutionResult做legacy/audit Presentation；CLI只用strict parsed `execution_disposition`决定exit。 |
| `removed_authority` | `run_local_request`中的`build_graph`/`create_initial_state`/`graph.invoke`、`final_build_succeeded`终态判断、`_runtime_verification_chain`完成判定及基于current_stage/claims/summary/totals/latest/path/file-existence的route或terminal解释；CLI相同判断。`_verify_final_compiled_artifact_if_built`、canonical source snapshot比较、适用`source_change_verifier`与`completion_classification`的machine gate从local entry移入executor冻结前唯一validation boundary；local entry只投影该次已经冻结的validation details，不重复读取或重跑。 |
| `public_contract` | `run_local_request`现有签名与legacy顶层mapping保留，并新增exact `product_execution_result`；legacy `current_stage`/build/runtime/artifacts仅从冻结result与exact outputs投影，不参与exit。CLI exit：`succeeded→0`、`domain_blocked→1`、`platform_blocked|partial→2`；missing/invalid structured result fail-closed为2。 |
| `compatibility` | pre-executor source disclosure、model selection、baseline Build、isolated workspace、run manifest/failure audit与现有LocalEntryError边界保留；明确diff reject保持正常domain-blocked mapping/exit1。catchable Graph/Store/post-execution validation失败从旧`LocalEntryError`升级为strict product result并exit2，这是本迁移登记的允许变化。result形成后的manifest/result JSON写失败抛`ProductExecutionPresentationError`；CLI exact JSON只有`status="PRESENTATION_FAILED"`、`product_execution_result`和`audit_error={failure_class,failure_message,sink}`三个顶层字段并exit2，不得降级nested machine truth。 |
| `semantic_boundary` | canonical-source、compiled-artifact、source-change和completion-classification只在executor的`validate_product_execution_outputs`执行一次并可在冻结前形成partial；冻结后run manifest/result JSON、stdout/stderr路径和相同validation detail的展示是Presentation，失败只能抛携带逐字相同result的`ProductExecutionPresentationError`。CLI不得读取Graph state、Artifact payload claims或legacy summary决定机器结果。 |
| `exact_files` | `src/mod_agent/product_execution.py`（new）、`src/mod_agent/product_executor.py`（new）、`src/mod_agent/local_entry.py`、`src/mod_agent/cli.py`、`tests/unit/test_product_execution.py`（new）、`tests/unit/test_local_entry.py`、`tests/unit/test_mod_agent_cli.py`、`tests/unit/test_mod_delivery_e2e.py`。 |
| `exact_symbols` | `run_local_request`、`_verify_final_compiled_artifact_if_built`（删除machine owner或机械委托executor）、canonical source snapshot比较、`source_change_verifier`调用、`completion_classification` gate、`validate_product_execution_outputs`、`_runtime_verification_chain`（降级为Presentation-only或删除其完成判断）、`_persist_graph_terminal_result`（Presentation-only）、CLI `main`的`run-request` branch、`ProductExecutionPresentationError`、`preflight_product_execution`、`execute_product_execution`。 |
| `authority_tests` | rg/AST证明run_local/CLI不再import/call `build_graph`、`create_initial_state`、`graph.invoke`或读取上述claims/current_stage决定exit；legacy mapping不能改变nested result；generic pre-result LocalEntryError仍exit2；Presentation failure保留逐字相同result。 |
| `integration_test` | 至少一条不mock `run_local_request`、public executor或Graph的CLI compile链和一条runtime链；只mock最低层model/build/runtime effects，使用temporary filesystem Store；另覆盖domain reject exit1、Store blocked/partial exit2、Graph全部Store committed后compiled/canonical/source-change validation失败形成partial，以及result冻结后audit sink失败保持同一result并exit2。 |
| `stop_conditions` | 需要改变`run_local_request`参数或CLI flags、删除现有audit字段、改变exact diff/Build/Runtime permission、触碰P2.3/P2.4/P3/P4或Authority文档时停止回审。 |
| `unresolved_contract_decisions` | `[]` |

###### 15.11.2.14.6 exact允许范围、三checkpoint与完成门

本合同approved后的生产文件全集只允许：

- `src/mod_agent/product_execution.py`（new）；
- `src/mod_agent/product_executor.py`（new）；
- `src/mod_agent/workflow/graph.py`；
- `src/mod_agent/workflow/state.py`；
- `src/mod_agent/workflow/nodes.py`；
- `src/mod_agent/local_entry.py`；
- `src/mod_agent/cli.py`。

测试文件全集只允许：

- `tests/unit/test_product_execution.py`（new）；
- `tests/unit/test_workflow_graph.py`；
- `tests/unit/test_local_entry.py`；
- `tests/unit/test_mod_agent_cli.py`；
- `tests/unit/test_mod_delivery_e2e.py`。

`ArtifactStore`、Registry、checkpointing、transitions、verification operations、Artifact/Approval schema与历史driver均不修改。
实施checkpoint I只做Graph Store-result carrier/C5 adoption；II只做public executor/result与真实failure matrix；III只做
run_local/CLI authority removal。三段都不得单独commit或进入下一P项；每段focused通过且文档登记事实后，最终合为一个
staged对象送一次独立实施后验收。authority门必须证明：Graph是唯一same-invocation route owner，Store是唯一C5 owner，
product projector是唯一machine result owner，run_local/CLI只剩normalization/Presentation，且任何旧路径都不能绕过
typed mode直接执行product Graph。Product Executor只拥有binding wrapper与组合规则，不得重新拥有source revision、source disclosure、
model admission或runtime admission payload schema；如导入方向要求迁移原owner，旧定义必须删除并由所有caller委托同一符号。

最低focused命令由实施阶段按上述五个测试文件形成；不得执行产品Build/Runtime/GTFO或正式Store。若批准后的真实测试发现
需要第八个生产文件、第六个测试文件、公共schema变化、额外active Store path或任何A方案durable能力，立即停止并回合同
审核。P2.2在最终独立实施验收与commit checkpoint前保持open；P2.3、P2.4、P3、P4保持not_started/stopped。

```yaml
option_b_implementation_contract: independently_approved_pending_implementation
contract_verdict: approved
approved_contract_document_sha256: 3E954A76DF8141347960DE1888C92BE3947C93113C0586330B9E213EC82C105A
architecture_boundary_verdict: option_b
public_executor_pair:
  - preflight_product_execution
  - execute_product_execution
typed_graph_mode: ProductExecutionGraphModeV1
machine_result_owner: project_product_execution_result
machine_result_schema: ProductExecutionResultV1
store_truth_owner: ArtifactWriteResult
graph_route_owner: existing_StateGraph_conditional_edges
whole_workflow_approval_identity: none
durability: same_invocation_only
implementation_checkpoints:
  - I_graph_store_result_carrier_and_C5_adoption
  - II_public_product_executor_and_ProductExecutionResultV1
  - III_run_local_request_and_CLI_authority_removal
unresolved_contract_decisions: []
implementation_authorization: granted_within_§15.11.2.14_exact_scope
P2_3_P2_4_P3_P4: stopped
```

## 16. 变更控制与非黑箱要求

本文档只有经用户明确批准后才成为规范性实施约束。

### 16.1 合同包是开发校准工具，不是逐细节审批系统

实施合同只记录会改变控制权、公共合同、兼容性或严重失败边界的决定。推进页在各 C1–C7
章节表格中自行完成调查、设计和选择；审核页判断这些选择是否满足本文目标。

已决定事项使用明确、可执行的陈述，不使用“可能、倾向、之后再看”等模糊表达。仍需设计的
公共问题集中写入 `unresolved_contract_decisions`；普通 private 实现选择由推进页在编码中解决。

| 需要进入合同包 | 由推进页自主处理 |
| --- | --- |
| semantic authority 与 owner 转移 | private helper 命名和拆分 |
| public schema/API/hash/result | internal class/function 组织 |
| lineage、side effect、retry/checkpoint | fixture、mock 和局部测试数据 |
| 历史兼容和 deprecation | 格式化、局部错误文本 |
| 严重失败边界与恢复权限 | semantic boundary 内的普通重构 |

### 16.2 一次设计、一次审核、一次实施、一次验收

两页共用本文件和同一个工作包：

1. 推进页完成实际代码 inventory，填写本工作包涉及章节的实施合同表，并将
   `unresolved_contract_decisions` 收敛为 `[]`。
2. 审核页只审核 authority、contract、compatibility、semantic boundary 和严重 failure boundary，
   给出一次明确结论。
3. 结论通过后，推进页在 semantic boundary 内自行规划和实施，包括合理调整内部文件、helper、
   测试组织和错误处理。
4. 实施完成后，推进页回填最终符号、final diff、测试和自我修正；审核页进行一次验收。

这个流程类似明确作业目标和评分标准后由开发者自行完成作业。审核页不代替推进页设计代码，
推进页也不把正常工程判断逐项转成审批请求。同一文件相当于小组共享的作业记录：各自承担
职责、互相校准关键决定，同时把主要精力留给实际实现和可验证交付。

### 16.3 实施前与实施后的证据

实施前提交：

- semantic goal；
- current/target authority；
- contract changes 或明确 `unchanged`；
- removed authority；
- compatibility；
- semantic boundary；
- validation 与 stop conditions。

实施后提交：

- exact final diff；
- 实际 public symbols 和 owner；
- behavior、authority、compatibility、integration tests；
- 自查和自我修正记录；
- 是否触发 stop condition。

预计文件和符号用于定位工作范围，不作为新的 Approval Identity。实施中增加内部 touchpoint，
只要 semantic boundary 不变，由推进页说明后继续；公共合同发生变化时回到合同审核。

### 16.4 需要回到合同审核的变化

以下变化会改变工作包的核心语义，需要暂停当前实施并更新同一份合同表：

- 新增或改变 semantic authority；
- 改变公共 schema、API、Approval Identity 或 hash 输入；
- 改变 Artifact lineage、side-effect class、retry/replay/checkpoint 或 recovery authority；
- 新增 Artifact、Approval/Request、Graph、Controller 或 persistent capability service；
- 改变历史 Artifact/Approval 的读取能力；
- 测试发现原 semantic goal 无法由当前合同表达。

这些变化并非永久排除。推进页说明真实缺口、替代方案、兼容成本和回收方式后，可以形成更新
后的明确合同决定，再进入同一轮实施。

### 16.5 同一文档中的状态与规范

各章节的空白实施合同表是两页共享工作区。推进页填写设计与实施结果，审核页填写复核结论，
不为同一工作包创建平行设计文档。

稳定的 schema/API/owner 决定在对应章节表中形成正式记录；当前 run hash、临时日志和完整命令
输出只在“实施与验收回填”中保存必要引用，避免把短期观察提升为长期架构规则。

run-local workaround 可以用于暴露公共缺口或完成已批准的有界实验；一旦它开始拥有 authority、
Store 终态、retry 或 public verdict，就应回到对应合同表，将语义迁回公共层。

## 17. 完成条件

只有同时满足以下条件，才能声明控制面收敛完成：

1. capability support 由一份 declaration 供 public entry、Graph、materializer、tests 使用。
2. Approval Identity 只 hash approved action boundary。
3. Machine Evidence、Observation、Presentation 不能使相同 action 的 Approval 失效。
4. Artifact lineage 只有 immutable envelope 一个 durable owner。
5. Store/public executor 能权威区分 committed、blocked、partial outcome。
6. Graph 与 caller 不会产生冲突 terminal state。
7. Graph-before-side-effect、retry/replay、checkpoint、failure、restoration 由公共层强制。
8. feature driver 已降级为 parameter adapter 与 Presentation。
9. executed historical driver 与 immutable Artifact 保持可读。
10. 第二个真实产品切片复用同一控制面，未创建新的 feature-specific executor 或
    authority subsystem。

当前完成判定还必须逐项关闭§15.10与§15.11登记的开放门。尤其，§11.5完成后只能关闭Edit Authority
structured result adoption，不能把C6/C7或整个平台自动恢复为complete。

在完成全部条件前，状态必须保持 `partial`，不得宣称影子控制面已经删除或通用平台能力
已经完成。
