# Evidence-Grounded Controlled Code Generation Agent Platform DEV_SPEC

Authority and reading order are defined only by `AGENTS.md` section 2. This file remains
the detailed root control-plane specification. Older phase tables, imported
material, and historical addenda do not create active work unless the active
contract and current queue select it.

# 0.0A Validation-First Specification Authority

This section is the highest-priority specification rule. It supersedes older
roadmaps, imported blueprints, phase tables, and addenda when they prescribe a
technology before the project has measured its effect.

The product is an evidence-grounded controlled code-generation Agent platform.
Its implementation order is determined by measurable delivery capability, not
by the number of modules described in this file.

Current normative progression:

```text
stable controlled GTFO vertical slice
-> agent decision-quality evaluation baseline
-> retrieval ablation and freshness evaluation
-> measured production retrieval decision
-> dashboard/MCP projection of proven behavior
```

Normative supporting documents:

- `docs/RETRIEVAL_ARCHITECTURE_DECISIONS.md` records accepted retrieval
  boundaries, known gaps, source-specific architecture, and unproven claims.
- `docs/RETRIEVAL_VALIDATION_PLAN.md` defines H1-H5, experimental arms,
  metrics, freshness tests, and promotion/stopping rules.
- `EVIDENCE_RAG_MCP_SPEC.md` defines the Evidence Retrieval / Knowledge / MCP
  subsystem only inside this product boundary.
- `docs/IMPLEMENTATION_QUEUE.md`, `docs/PROJECT_STATE.md`, and
  `docs/SPEC_COVERAGE_MATRIX.md` record executable work, current verified state,
  and implementation coverage.

Technology promotion rules:

1. `rg` plus live file reads is the code-retrieval freshness baseline.
2. Symbol/AST/LSP/call-graph indexes are disposable navigation aids until their
   Hook-recall and stale-result behavior pass the registered evaluation.
3. BM25 is evaluated separately for persistent community/history sources and
   current code; success in one source class does not prove success in another.
4. Dense retrieval, RRF, reranking, multi-hop retrieval, and Agentic retries are
   experimental until the registered ablations demonstrate downstream benefit.
5. Retrieval relevance never grants patch authority. Current source/API/runtime
   verification, EvidencePack readiness, proposal review, permission, build,
   runtime, and eval gates retain authority.
6. Imported or legacy technical blueprints are reference material. They cannot
   add implementation work or override this section without a recorded decision
   backed by evaluation evidence.

Specification restructuring rule:

- Keep the normative product contract concise and executable.
- Move imported, superseded, or generic material to `docs/references/` in a
  later mechanical extraction step without treating that move as a capability.
- Preserve completed implementation evidence in state, matrix, queue history,
  and audit documents rather than repeating it throughout this specification.
- Do not report an architectural mechanism as a project advantage until its
  registered metric and downstream effect have been measured.

# 0.0 Capability-First Execution Override

This override supersedes older wording in this document that says to implement
"only the next incomplete phase" as a schema/audit slice.

For this greenfield project, a phase means product capability progression:

```text
request -> feature_spec -> evidence_pack -> implementation_plan
-> patch_proposal -> proposal_review -> isolated fake dry_run_result
-> structured build_result -> runtime/manual evidence -> workflow_summary
```

Audits, checkpoints, schemas, validators, and policy checks are implementation
supports. They should unlock runnable capability, not become product phases by
themselves.

Implementation priority:

1. Keep the main loop runnable.
2. Wire existing adapters before adding new passive contracts.
3. Use fake/local/supplied-output runners as stepping stones toward real writes,
   real builds, and real runtime automation.
4. Label early artifacts by capability level so they can be upgraded without
   re-litigating scope.
5. Add focused tests around the runnable loop segment and then move to the next
   capability-bearing step.

Implementation boundaries should be written as forward paths: what can run now,
what evidence upgrades it, and what unlocks the next level. Avoid turning
boundary work into a substitute for product progress.

# 0.0B Current Product Direction Lock

This project is a vertical controlled code generation platform, not a generic
RAG Q&A application.

Career-oriented progression lock:

```text
The project is advanced for job-market competitiveness, not for checklist
completion. Each V2/V3 task should build visible evidence of production-grade
Agent platform engineering: workflow control, evidence-grounded code generation,
tool safety, observability, evaluation, retrieval quality, artifact lineage,
runtime feedback, and external tool/data integration.

Prefer tasks that create interview-visible engineering depth:
  - one runnable vertical slice over several isolated schemas;
  - measured eval and trace evidence over broad claims;
  - safe MCP/API/dashboard surfaces over private-only scripts;
  - production constraints such as approval, rollback, idempotency, recovery,
    budgets, and failure routing over happy-path demos;
  - industry-relevant concepts such as LangGraph-style durable agent workflow,
    MCP tool integration, OpenTelemetry-style observability, retrieval eval,
    and controlled write/runtime approval.

Do not prioritize work merely because it is easier to document. A task should be
selected when it improves the project's ability to demonstrate real enterprise
engineering judgment, systems design depth, and practical AI-agent delivery
experience during interviews.
```

Evidence RAG and MCP subsystem detail lives in `EVIDENCE_RAG_MCP_SPEC.md`.

```text
DEV_SPEC.md is the parent control-plane specification.
EVIDENCE_RAG_MCP_SPEC.md is the Evidence RAG / MCP subsystem specification.
RAG/MCP implementation must support the same LangGraph artifact loop, evidence-before-edit rule, review gates, runtime gates, evaluation, dashboard, and job-oriented engineering intent defined here.
```

All non-RAG core modules must be upgraded toward the same engineering depth as
the imported RAG spec. In practice, LangGraph workflow, artifact contract,
planning, proposal, review, dry-run, build, runtime evidence, repair, memory,
evaluation, dashboard, MCP/API/CLI, and demo packaging should each define goals,
named strategies, inputs/outputs, schemas, state transitions, failure handling,
implementation classes, observability, tests, acceptance criteria, implementation
boundaries, phase breakdown, and ADR/trade-off notes.

Implementation rule:

1. Preserve useful implemented retrieval components and legacy design material,
   but promote only the parts justified by current requirements and evaluation.
2. Integrate accepted behavior under the current controlled-agent knowledge and
   evidence modules; read source before naming an implementation path.
3. Make LangGraph controlled code generation the top-level product loop.
4. Raise non-RAG specs and code to RAG-level rigor instead of simplifying RAG.
5. Keep old RAG product naming and QA-first workflows subordinate to the current
   vertical code generator goal.

# 0.0C Skill, Spec, State, And Artifact Roles

Reusable procedures belong in Skills. Product facts, interface contracts,
current branch state, queue status, test evidence, and artifact payloads remain
outside Skills.

Current roles:

1. `.agents/skills/auto-coder/SKILL.md` is frozen as `SKILL.md.frozen`. It is
   retained for historical review and is not an active development authority.
2. `.agents/skills/mod-delivery-playbook/SKILL.md` is the user-facing mod
   delivery process Skill. It runs the delivery chain from planning input to
   handoff summary while linking back to source code, artifacts, tests, and
   current state documents for facts.
3. `DEV_SPEC.md` remains the product and architecture source of truth.
4. `docs/PROJECT_STATE.md`, `docs/IMPLEMENTATION_QUEUE.md`, and
   `docs/SPEC_COVERAGE_MATRIX.md` remain the current state, work queue, and
   coverage ledgers.
5. Artifact files and test output remain the source of delivery evidence.

The first proven delivery chain is E2E-001:

```text
planning input -> feature_spec -> evidence_pack -> implementation_plan
-> patch_proposal -> proposal_review -> dry_run_result -> build_result
-> runtime_evidence -> eval_report -> workflow_summary
```

Current E2E-001 proof level:

1. Current-branch evidence exists in `tests/unit/test_mod_delivery_e2e.py`
   in the E2E-001 checkpoint.
2. The test uses a controlled temporary BetterHitFeedback source file and
   deterministic symbol evidence.
3. The build path verifies an expected local artifact through `BuildAdapter`
   using the controlled test build factory/runner, then provides a path toward a
   real C# toolchain build and game-loadable artifact proof.
4. The runtime path launches a real local subprocess probe through
   `RuntimeProbeRunner`, then feeds the real GTFO runtime validation track.
5. The next runtime capability step should connect GTFO launch, persistent game
   logs, screenshots, plugin markers, and gameplay evidence under one verified
   run record.

Expert Skills may be split when they help the delivery chain move faster and
their outputs stay connected to source code, artifacts, tests, and LangGraph
routing. Start with:

```text
patch-review-playbook
runtime-diagnosis-playbook
hook-discovery-playbook
repair-loop-playbook
```

# 0.0D High-Risk Git And Queue Handling

Before high-risk work, run a Git status check and name the files that will be
changed. High-risk work includes confirmed writes, game directory operations,
runtime launch/copy operations, broad refactors, schema migrations, history
repair, and queue/spec rewrites.

Rules:

1. Preserve user changes while planning each edit against the current Git state.
2. Convert restored historical records into current branch proof by restoring
   the referenced files and rerunning focused tests.
3. Keep commits user-directed and evidence-backed.
4. If a task changes queue order, update `docs/IMPLEMENTATION_QUEUE.md` and
   `docs/SPEC_COVERAGE_MATRIX.md` in the same loop.
5. Review-repair tasks outrank ordinary Q work when an active P0/P1 finding is
   present.
6. Platform expansion should be selected by capability value. Strong near-term
   tracks include real dense retrieval, multimodal evidence, dashboard/API
   service work, MCP integration, game launch/copy automation with approval, and
   benchmark harnesses.

# 0.1A LangGraph Control-Plane Clarification

This clarification overrides older wording in this document wherever it is
ambiguous.

LangGraph is the workflow runtime/control plane. Business node behavior may be
stubbed, fake, local, supplied-output, or real during staged implementation, and
the workflow runtime should use a real LangGraph `StateGraph`/compiled graph for
graph execution, routing, interrupt/resume, checkpointing, and graph audit.

Implementation rules:

1. "Stub graph" means stubbed business nodes inside a real LangGraph graph.
2. LangGraph conditional edges own routing. A route matrix may declare routes,
   and helper functions may compute route labels or validate transitions, but
   helpers should remain supporting code around the primary workflow runner.
3. `transitions.py` may contain route predicates, route labels, and transition
   validation, with LangGraph `add_conditional_edges` remaining the execution
   wiring.
4. A single route registry/source should feed both LangGraph edge construction
   and any audit/Mermaid exporter so visual output cannot drift from execution.
5. `human_approval` in diagrams means a LangGraph interrupt/resume step that can
   collect approval evidence and resume the product loop.
6. LangGraph controls when artifact-producing nodes run. Nodes write artifacts
   through `ArtifactStore` and emit trace through trace wrappers/writers.
   LangGraph itself is not the artifact store.
7. LangGraph checkpointing is the source of truth for resumable graph state.
   Additional workflow run tables may index metadata for dashboard and API use.
8. Use canonical names consistently:

```text
node names: plan_request, draft_feature_spec, retrieve_evidence,
create_implementation_plan, generate_patch_proposal, review_proposal,
dry_run_apply, build, collect_runtime_evidence, create_repair_plan, evaluate,
done, blocked

artifact/stage names: request_planning_report, feature_spec, evidence_pack,
implementation_plan, patch_proposal, proposal_review, dry_run_result,
build_result, runtime_evidence, repair_plan, eval_report
```
9. `ModAgentState` is runtime control state. Artifacts are the durable audit and
   state projection. State entries must reference artifacts by ref/hash; durable
   claims must be recoverable from artifacts/traces, not hidden state.
10. CLI/API/MCP commands should call graph commands or artifact readers so the
    external interface follows the same product loop.
11. Evidence RAG / Knowledge Hub feeds evidence decisions inside the LangGraph
    controlled workflow.
12. Specialist nodes are implementation roles inside one LangGraph orchestrator
    and can grow as the single controlled graph matures. The optional
    ProposalCritic local/injected assessment boundary may score a registered
    proposal inside `review_proposal`, but it is
    read-only, writes a separate `critic_assessment` artifact, and has no route,
    path, approval, or write authority. Deterministic ProposalReviewer rules and
    LangGraph conditional edges retain final decision authority.
13. Interrupt/resume and checkpoint/resume should mature alongside real build
    and runtime branches.

If a later section conflicts with this clarification, follow this section.

## 0.1B LangGraph Maturity And Claim Levels

Use this ladder when reporting progress:

| Level | Meaning | Current Signal | Next Capability |
| --- | --- | --- | --- |
| L0 | hand-written loop or pseudo graph | workflow skeleton | LangGraph-backed routing |
| L1 | real `StateGraph` invocation with compatibility wrapper | thin LangGraph migration | broader graph ownership |
| L2 | conditional edges own routing and route audit uses same registry | LangGraph routes decisions | stronger audit and dashboard views |
| L3 | interrupt/resume and checkpoint/resume are tested | mature local control plane | real build/runtime automation |
| L4 | bounded repair/eval paths are artifact-backed | controlled local loop | real mod capability |

Reporting rules:

1. Report which part of routing is graph-owned and which part remains adapter
   compatibility work.
2. Generate Mermaid or graph audit output from the same route registry used to
   construct LangGraph edges.
3. Report large dirty diffs as accumulated work and separate them from the
   current task summary.
4. Use the task id from `PROGRESS_TRACKING.md` and `06-schedule.md` exactly when
   those files are the active planning source.
5. Documentation updates should help select and execute the next capability
   step.

> 版本：0.4  
> 状态：Greenfield Developer Specification  
> 关系：本文件是 `spec.md` 的开发执行版，必须与 `SKILL.md` 一起使用。  
> 目标：让一个新会话中的 coding agent 只靠本文件和 skill，就能按阶段把项目做成可运行、可测试、可展示的工程，而不是只读懂愿景。

---

# 0. DEV_SPEC 使用协议

## 0.1 文件分工

本仓库的顶层说明文件各自承担不同职责：

| 文件 | 职责 | 更新频率 | 使用方式 |
| --- | --- | --- | --- |
| `SKILL.md` | 规定 agent 工作方式、读取顺序、安全边界 | 中 | 每次实现阶段都必须遵守 |
| `DEV_SPEC.md` | 给出技术设计、接口、阶段任务、验收标准 | 高 | 实施时的 source of truth |

本文件不是普通产品文档，也不是只给人看的架构介绍。它必须满足三个条件：

```text
1. 能拆成可执行任务。
2. 每个任务能生成或修改明确文件。
3. 每个任务有测试、验收标准和实现边界。
```

## 0.2 与 `spec.md` 的关系

`spec.md` 是系统级技术规格，描述平台应该是什么。  
`DEV_SPEC.md` 是开发规格，描述如何一步一步把它做出来。

因此，本文件保留并展开 `spec.md` 的主体内容，但增加以下实施层信息：

- 模块落地顺序；
- 文件级任务拆分；
- artifact schema 的写入与校验策略；
- LangGraph 节点的输入输出约束；
- RAG、review、dry-run、build、runtime、repair 等关键模块的失败路径；
- 每阶段最低测试要求；
- agent 使用 `SKILL.md` 时的 prompt 和工作协议；
- 第一天、第二天、第一周分别应该完成什么；
- Demo、验证和发布时需要保留的交付边界。

## 0.3 开发原则

本项目的开发优先级如下：

```text
Graph state > hidden state
Artifact contract > prompt-only memory
Evidence before patch
Review before apply
Dry-run before write
Build evidence before success claim
Runtime evidence before gameplay claim
Eval before resume claim
```

任何实现只要违反这些优先级，即使 demo 看起来能跑，也应视为不可接受。

## 0.4 新会话启动协议

每次让 coding agent 开始干活时，建议使用下面的会话启动语：

```text
Read SKILL.md and DEV_SPEC.md.
This is a greenfield project. Do not copy old project source.
Follow the capability-first execution override.
Advance the runnable product loop before adding passive validators.
Use structured artifacts, trace events, focused tests, safe fake runners, and side-effect boundaries.
```

如果目标是第一天开工，使用：

```text
Implement the next runnable loop segment.
Prefer adapter wiring and fake/local execution paths over more schema-only work.
Move real patch/build/runtime success claims forward by attaching artifact-backed evidence.
```

## 0.5 完成声明规则

每次阶段完成后，最终回复必须包含：

```text
Phase:
Changed files:
Artifacts produced:
Validation commands:
What is now true:
What is still stubbed:
Next recommended phase:
```

避免使用以下低价值声明：

```text
"应该可以"
"理论上支持"
"后续可扩展"
"大概完成"
"未测试但逻辑简单"
```

如果没跑测试，必须明确写：

```text
Validation not run: <reason>
```

---

# 0A. 一号文档深度迁移原则

一号 `DEV_SPEC.md` 的价值不在于它只写了 RAG，而在于它做到：

```text
愿景 -> 技术选型 -> 模块接口 -> 数据结构 -> 失败路径 -> 测试策略 -> 小阶段排期
```

二号项目应把这种深度扩展到 RAG 之外。二号的核心是 controlled agentic code generation platform，因此以下模块都应逐步达到类似深度：

| 模块 | 必须达到的深度 |
| --- | --- |
| LangGraph Workflow | 节点、条件边、checkpoint、人类中断、失败转移、trace |
| Artifact Contract | envelope、schema、生命周期、stale detection、store interface |
| Knowledge Base | source discovery、loader、metadata store、incremental index |
| Evidence RAG | deterministic/symbol/vector/rerank/fusion/readiness/evidence pack |
| Domain Adapter | risk taxonomy、managed paths、build profile、runtime evidence hints |
| Planning Layer | request route、feature spec、implementation plan、blocking uncertainty |
| Patch Proposal | context builder、schema、diff plan、no-op detector、scope boundary |
| Review Gate | evidence binding、scope check、risk check、permission check |
| Dry-run Apply | virtual patch、path guard、diff stats、write isolation |
| Build Adapter | profile、command runner、error classifier、repair handoff |
| Runtime Evidence | logs、screenshots、manual confirmation、vision caption fallback |
| Repair Loop | failure type、hypothesis、minimal fix plan、retry budget |
| Memory Compression | artifact index、context pack、token budget、critical constraint retention |
| Evaluation Harness | golden cases、module metrics、regression report、dashboard summary |
| Dashboard | workflow viewer、evidence browser、proposal viewer、eval dashboard |
| MCP/API/CLI | external tools、schema、local inspection、write/launch approval routes |

判断某一章是否足够深，用下面的检查表：

```text
是否说清楚为什么存在？
是否说清楚输入输出？
是否指定文件和目录？
是否给出数据结构或 schema？
是否定义失败路径？
是否定义测试？
是否定义验收标准？
是否说明不要做什么？
```

只有全部回答“是”，该章才算达到一号文档级别。

---

> 版本：0.3  
> 状态：Greenfield Technical Specification  
> 项目类型：Evidence-Grounded Controlled Code Generation Agent Platform
> 初始领域：GTFO / BepInEx / Unity IL2CPP / HarmonyX Mod Development  
> 核心能力：LangGraph Workflow、Knowledge Base、Evidence RAG、Patch Proposal、Review Gate、Build/Runtime Feedback、Evaluation Harness、Dashboard、MCP/API  
> 目标：把自然语言 Mod 需求转化为可追踪、可评估、可审查、可回滚的受控代码生成流程。

---

## 目录

1. 项目概述  
2. 项目定位与非目标  
3. 核心特点  
4. 总体架构  
5. LangGraph Workflow 设计  
6. Artifact Contract 设计  
7. Knowledge Base 设计  
8. Evidence RAG 设计  
9. Domain Adapter 设计  
10. Planning Layer 设计  
11. Patch Proposal 设计  
12. Review Gate 与 Delivery Confidence 设计
13. Dry-run Apply 设计  
14. Build Adapter 设计  
15. Runtime Evidence 与 Multimodal 设计  
16. Repair Loop 设计  
17. Memory 与 Context Compression 设计  
18. Evaluation Harness 设计  
19. Observability 与 Dashboard 设计  
20. MCP / API / CLI 设计  
21. 配置系统设计  
22. 测试方案  
23. CI/CD 与质量门禁  
24. 项目排期  
25. 旧项目吸收策略  
26. Demo 与简历包装  
27. 可扩展性与未来展望  

---

# 1. 项目概述

Evidence-Grounded Controlled Code Generation Agent Platform 是一个用于游戏 Mod 开发的受控代码生成 Agent 平台。

它不只是一个“让 LLM 写代码”的工具，而是一套完整的工程化系统：

```text
User Natural Language Request
  -> LangGraph Workflow
  -> Request Planning
  -> Feature Spec
  -> Knowledge Base / Evidence RAG
  -> Implementation Plan
  -> Patch Proposal
  -> Proposal Review Gate
  -> Dry-run Apply
  -> Build Adapter
  -> Runtime Evidence Collection
  -> Repair Loop
  -> Evaluation Harness
  -> Dashboard / Demo / Resume Packaging
```

本项目的核心目标是解决一个实际问题：

> 非专家用户只描述想要的 Mod 功能，系统能够通过领域知识、源码证据、构建反馈和运行时证据，逐步生成可审查、可验证、可修复的 Mod 实现方案。

初始目标领域是：

```text
GTFO / BepInEx / Unity IL2CPP / HarmonyX
```

但项目架构不应写死 GTFO。GTFO 只是第一个 Domain Adapter。长期目标是形成：

```text
Domain-Adapter-Based Mod Agent Platform
```

也就是说，平台主体负责：

```text
workflow orchestration
artifact contracts
knowledge base
evidence retrieval
patch proposal
review gate
tool permission
evaluation harness
dashboard
```

具体游戏或技术栈由 Domain Adapter 提供：

```text
GTFO Adapter
Other Unity IL2CPP Adapter
Unity Mono Adapter
BepInEx Generic Adapter
MelonLoader Adapter
```

---

# 2. 项目定位与非目标

## 2.1 项目定位

本项目可以被描述为：

```text
A LangGraph-based controlled code generation platform for game mod development,
featuring artifact-driven workflow state, evidence-oriented RAG over source code
and domain knowledge, proposal review gates, dry-run safety, build/runtime feedback
loops, and evaluation harnesses for agent decision quality.
```

中文定位：

```text
这是一个面向游戏 Mod 开发的受控 Agentic Code Generation 平台。
它用 LangGraph 编排自然语言需求、知识库检索、证据绑定、实现规划、
Patch Proposal、安全 Review Gate、Dry-run、Build/Runtime Feedback 和
Evaluation Harness，形成一条可追踪、可评估、可扩展的 AI 工程化链路。
```

## 2.2 面向对象

本项目面向三类用户。

### 1. 非专家 Mod 需求用户

他们不需要知道：

```text
Harmony patch class
IL2CPP method signature
BepInEx plugin lifecycle
Unity field name
C# namespace
build command
```

他们只需要表达：

```text
让击杀标记变成粉色，但不要改变普通命中、弱点命中、伤害、声音或其他反馈。
```

系统负责：

```text
需求澄清
风险判断
证据检索
实现规划
patch proposal
安全审查
build/runtime 验证
```

### 2. 开发者 / 项目维护者

他们需要看到：

```text
为什么选这个 hook
证据来自哪里
会改哪些文件
为什么没有改其他文件
build 为什么失败
runtime 证据是否足够
repair plan 是否合理
```

### 3. 面试 / 简历 / Demo 观看者

他们需要看懂：

```text
这是一个 LangGraph Agent 项目
它不是普通 RAG 问答
它有知识库和检索
它有受控执行
它有安全 gate
它有 evaluation harness
它能展示工程深度
```

## 2.3 非目标

本项目不是：

- 普通 RAG 文档问答系统；
- 单纯 MCP 知识库；
- 无约束代码生成 bot；
- 只靠 prompt 的脚本集合；
- 只服务一个 sample mod 的一次性工具；
- 旧项目代码的直接复制；
- 一堆互相独立的 validators；
- 只会生成 markdown 报告的文档项目；
- 只追求能跑一次 demo 的薄包装项目。

---

# 3. 核心特点

## 3.1 LangGraph 作为控制平面

LangGraph 不是装饰性技术点，而是本项目的控制平面。

它负责：

```text
workflow state
node transition
conditional edges
human interrupt
repair loop
blocked path
artifact writing
trace emission
evaluation hook
```

系统不是线性脚本，而是一个有状态图：

```text
plan_request
  -> draft_feature_spec
  -> retrieve_evidence
  -> create_implementation_plan
  -> generate_patch_proposal
  -> review_proposal
  -> dry_run_apply
  -> build
  -> collect_runtime_evidence
  -> evaluate
  -> done
```

失败路径：

```text
retrieve_evidence -> blocked
review_proposal -> revise_patch_proposal
build -> repair_plan
runtime_evidence -> repair_plan
human_approval -> LangGraph interrupt/resume -> blocked or continue
```

## 3.2 Knowledge Base + Evidence RAG

本项目的 RAG 不是普通问答 RAG，而是 Evidence RAG。

普通 RAG 的目标是：

```text
用户问问题 -> 检索文档 -> 生成回答
```

本项目的 Evidence RAG 目标是：

```text
Agent 要改代码 -> 检索源码 / 文档 / 日志 / artifact / API evidence
-> 判断证据是否足够 -> 绑定到 implementation plan 和 patch proposal
```

证据不仅用于回答，还用于控制：

```text
是否允许进入 patch generation
是否允许使用某个 hook
是否允许声明 runtime behavior verified
是否允许 repair loop 继续
```

## 3.3 Artifact-driven Workflow

聊天上下文不是系统状态。

系统状态必须沉淀为 artifact：

```text
request_plan.json
feature_spec.json
evidence_report.json
implementation_plan.json
patch_proposal.json
proposal_review.json
apply_result.json
build_result.json
runtime_evidence.json
repair_plan.json
eval_report.json
workflow_trace.json
```

这样可以解决：

```text
上下文污染
旧项目碎片干扰
Codex / LLM 忘记前置约束
无法复现历史决策
无法评估 agent 行为
```

## 3.4 Controlled Patch Proposal

LLM 不直接修改代码。

LLM 只能生成：

```text
patch_proposal.json
```

Proposal 经过 review gate 后，才能进入 dry-run apply。

Confirmed apply 需要人工确认。

## 3.5 Build / Runtime / Repair Loop

生成 patch 不是终点。

系统必须支持：

```text
build
error classification
runtime evidence collection
repair planning
repair proposal
regression guard
```

其中 build success 只代表编译成功，不代表游戏内行为成功。

## 3.6 Evaluation Harness

本项目不靠“看起来能跑”证明能力，而是靠 harness 衡量：

```text
request planning accuracy
risk classification accuracy
evidence recall
evidence precision
review block correctness
dry-run safety
build error classification
repair plan correctness
golden path success rate
```

---

# 4. 总体架构

## 4.1 顶层架构

```text
                   User / CLI / MCP / API
                            |
                            v
               LangGraph Workflow Orchestration
                            |
        ------------------------------------------------
        |              |              |                |
        v              v              v                v
  Artifact Store   Knowledge Base   Safety Layer   Trace Layer
        |              |              |                |
        v              v              v                v
 Feature Spec   Evidence RAG   Review / Permission   Dashboard
        |              |              |
        v              v              v
 Implementation Plan -> Patch Proposal -> Dry-run Apply
        |                                     |
        v                                     v
 Build Adapter -----------------------> Runtime Evidence
        |                                     |
        v                                     v
 Repair Loop <-------------------------- Evaluation Harness
```

## 4.2 目录结构

```text
controlled-mod-agent/
  README.md
  SPEC.md
  SKILL.md
  pyproject.toml

  config/
    settings.yaml
    logging.yaml
    eval.yaml

  src/
    mod_agent/
      workflow/
        state.py
        graph.py
        nodes.py
        transitions.py
        interrupts.py
        checkpointer.py

        # `graph.py` owns StateGraph construction.
        # `transitions.py` owns route labels/predicates/validation only.
        # Keep the primary workflow execution loop in graph.py.

      artifacts/
        store.py
        schemas.py
        validators.py
        lifecycle.py
        stale_detection.py
        hash_utils.py

      knowledge/
        source_registry.py
        ingestion_pipeline.py
        loaders.py
        splitters.py
        transforms.py
        index_store.py
        sqlite_store.py
        symbol_index.py
        artifact_index.py
        log_index.py
        screenshot_index.py
        legacy_importer.py

      rag/
        query_builder.py
        deterministic_retriever.py
        keyword_retriever.py
        symbol_retriever.py
        vector_retriever.py
        fusion.py
        reranker.py
        evidence_pack.py
        readiness.py

      domain/
        base.py
        registry.py
        gtfo/
          adapter.py
          profile.py
          evidence_sources.py
          build_profile.py
          runtime_profile.py
          safety_policy.py
          verification.py

      planning/
        request_router.py
        taxonomy.py
        risk_classifier.py
        feature_spec_builder.py
        acceptance_contract.py
        implementation_planner.py

      proposal/
        context_builder.py
        generator.py
        patch_schema.py
        diff_model.py
        noop_detector.py

      review/
        proposal_reviewer.py
        schema_review.py
        semantic_alignment.py
        scope_minimality.py
        evidence_binding.py
        stale_review.py

      safety/
        permissions.py
        tool_registry.py
        path_guard.py
        approval.py
        sandbox_policy.py

      apply/
        dry_run.py
        patch_parser.py
        file_plan.py
        apply_result.py

      build/
        adapter.py
        profile.py
        result_parser.py
        error_classifier.py

      runtime/
        evidence_collector.py
        log_analyzer.py
        screenshot_registry.py
        verification.py

      repair/
        repair_planner.py
        repair_context.py
        repair_proposal.py
        regression_guard.py

      memory/
        context_pack.py
        compression.py
        feature_history.py
        token_budget.py

      observability/
        trace.py
        events.py
        run_store.py
        metrics.py

      evaluation/
        harness.py
        case_schema.py
        runner.py
        metrics.py
        report.py
        regression.py

      dashboard/
        app.py
        pages/
          overview.py
          workflow.py
          artifacts.py
          evidence.py
          patches.py
          build_runtime.py
          evals.py
          legacy.py
        services/
          trace_service.py
          artifact_service.py
          evidence_service.py
          eval_service.py

      api/
        server.py
        schemas.py

      mcp/
        server.py
        tools.py
        resources.py

  tests/
    unit/
    integration/
    golden/

  eval_cases/
    request_planning/
    evidence_retrieval/
    proposal_review/
    dry_run/
    build_repair/
    golden_path/

  knowledge/
    raw/
    processed/
    indexes/
    sqlite/

  artifacts/
    features/

  logs/
    traces.jsonl
    runs/

  legacy_import/
    raw/
    summaries/
    accepted/
    rejected/

  docs/
    architecture/
    demo/
    resume/
    security/
    lessons/
```

---

# 5. LangGraph Workflow 设计

## 5.1 设计目标

LangGraph Workflow Layer 负责把所有模块串成受控流程。

This layer is implemented with LangGraph `StateGraph` and conditional edges.
Node handlers may be simple or stubbed, but graph execution, routing,
interrupt/resume, and checkpoint/resume are framework responsibilities.

它必须满足：

```text
可中断
可恢复
可追踪
可评估
可阻断
可修复
可人工确认
```

## 5.2 Graph State

The names in `StageName` are durable artifact/stage labels. They are not a
second set of workflow node names. Workflow node names use the canonical node
list from Section 0.1A.

```python
from typing import TypedDict, Literal

StageName = Literal[
    "request_planning",
    "feature_spec",
    "evidence_retrieval",
    "implementation_plan",
    "patch_proposal",
    "proposal_review",
    "dry_run_apply",
    "build",
    "runtime_evidence",
    "repair_plan",
    "evaluation",
    "done",
    "blocked",
]

RiskLevel = Literal[
    "low",
    "medium",
    "high",
    "critical",
    "unknown",
]

ExecutionPath = Literal[
    "config_only",
    "no_hook_needed",
    "quick_patch",
    "standard_feature",
    "game_hook_investigation",
    "runtime_investigation",
    "repair_loop",
    "blocked_ambiguous",
]

class ModAgentState(TypedDict):
    request_id: str
    feature_id: str | None
    user_request: str

    target_domain: str | None
    target_mod: str | None
    execution_path: ExecutionPath | None
    risk_level: RiskLevel | None

    current_stage: StageName
    next_stage: StageName | None

    artifacts: dict[str, str]
    artifact_hashes: dict[str, str]

    approvals: dict[str, bool]
    blockers: list[dict]
    warnings: list[dict]

    evidence_summary: dict
    review_summary: dict
    build_summary: dict
    runtime_summary: dict
    eval_summary: dict

    trace_id: str
    run_id: str
    metrics: dict
```

## 5.3 Node 列表

```text
initialize_run
plan_request
draft_feature_spec
retrieve_evidence
create_implementation_plan
generate_patch_proposal
review_proposal
dry_run_apply
build
collect_runtime_evidence
create_repair_plan
evaluate
interrupt_resume_gate
blocked
done
```

`interrupt_resume_gate` is a LangGraph interrupt/resume point. It collects
permission evidence and returns a resumable graph decision instead of flattening
the question into an opaque status.

## 5.4 Node 输入输出约定

每个 node 必须：

```text
读取上游 artifact
执行本阶段逻辑
写入本阶段 artifact
更新 ModAgentState
写 trace event
返回 state delta
```

推荐推进方式：

```text
直接修改 generated source
绕过 artifact store
读取 raw chat history 当主状态
吞掉异常
返回 fake success
```

## 5.5 条件边

```text
plan_request
  if blocked_ambiguous -> blocked
  else -> draft_feature_spec

retrieve_evidence
  if readiness == "ready" -> create_implementation_plan
  if readiness == "partial" and risk <= medium -> interrupt_resume_gate
  if readiness == "insufficient" -> blocked

review_proposal
  if PASS -> dry_run_apply
  if PASS_WITH_WARNINGS -> interrupt_resume_gate
  if NEEDS_REVISION -> generate_patch_proposal
  if BLOCKED -> blocked

dry_run_apply
  if safe and approval_required -> interrupt_resume_gate
  if safe and no approval_required -> build
  if unsafe -> blocked

build
  if success -> collect_runtime_evidence
  if failure -> create_repair_plan

collect_runtime_evidence
  if verified -> evaluate
  if inconclusive -> interrupt_resume_gate
  if failed -> create_repair_plan

evaluate
  if pass -> done
  if regression -> create_repair_plan
```

## 5.6 Checkpointing

默认实现：

```text
LangGraph SqliteSaver
```

存储位置：

```text
data/db/workflow_checkpoints.db
```

Ownership rule:

```text
LangGraph checkpointer owns resumable graph state.
Custom tables may index run metadata and audit summaries for dashboard/API use
while LangGraph checkpoint/resume remains the workflow state source.
```

表结构：

```sql
CREATE TABLE workflow_runs (
    run_id TEXT PRIMARY KEY,
    feature_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    current_stage TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE workflow_checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    state_json TEXT NOT NULL,
    artifact_hashes_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 5.7 失败处理

| 失败类型 | 处理方式 |
|---|---|
| node exception | 写 error trace，进入 blocked |
| artifact missing | stale/block |
| evidence insufficient | blocked |
| review failed | revise or block |
| build failed | repair plan |
| runtime inconclusive | human approval |
| eval regression | repair plan |

## 5.8 测试要求

单元测试：

```text
test_graph_normal_path
test_graph_blocks_on_insufficient_evidence
test_graph_interrupts_before_confirmed_write
test_graph_enters_repair_on_build_failure
test_graph_marks_artifact_stale
```

集成测试：

```text
test_stub_workflow_end_to_end
test_config_only_golden_path
test_hook_request_blocks_without_evidence
```

---

# 6. Artifact Contract 设计

## 6.1 目标

Artifact 是系统的主状态。

它必须解决：

```text
跨 node 数据传递
长上下文压缩
审查与回溯
eval case 构建
dashboard 展示
legacy import 管理
```

## 6.2 Artifact 存储路径

```text
artifacts/features/<feature_id>/
  request_plan.json
  feature_spec.json
  evidence_report.json
  implementation_plan.json
  patch_proposal.json
  proposal_review.json
  dry_run_result.json
  build_result.json
  runtime_evidence.json
  repair_plan.json
  eval_report.json
  workflow_trace.json
```

## 6.3 通用 Envelope

```json
{
  "schema_version": "0.3",
  "artifact_type": "feature_spec",
  "feature_id": "20260623_001_make-kill-marker-pink",
  "run_id": "run_001",
  "producer_node": "draft_feature_spec",
  "created_at": "2026-06-23T12:00:00Z",
  "input_artifact_hashes": {
    "request_plan": "sha256:..."
  },
  "content": {},
  "validation": {
    "status": "valid",
    "errors": [],
    "warnings": []
  },
  "hash": "sha256:..."
}
```

## 6.4 Artifact 生命周期

```text
created
  -> validated
  -> consumed
  -> stale
  -> superseded
```

## 6.5 Stale Detection

规则：

```text
如果上游 artifact hash 改变，下游 artifact stale。
```

示例：

```text
feature_spec changed
  -> evidence_report stale
  -> implementation_plan stale
  -> patch_proposal stale
  -> proposal_review stale
```

## 6.6 Artifact Store 接口

```python
class ArtifactStore:
    def write_artifact(
        self,
        feature_id: str,
        artifact_type: str,
        content: dict,
        producer_node: str,
        input_artifact_hashes: dict[str, str],
    ) -> ArtifactRef:
        ...

    def read_artifact(
        self,
        feature_id: str,
        artifact_type: str,
    ) -> dict:
        ...

    def validate_artifact(
        self,
        artifact: dict,
    ) -> ValidationResult:
        ...

    def mark_stale(
        self,
        feature_id: str,
        artifact_type: str,
        reason: str,
    ) -> None:
        ...

    def list_feature_artifacts(
        self,
        feature_id: str,
    ) -> list[ArtifactRef]:
        ...
```

## 6.7 验收标准

- 所有 artifact 写入必须经过 ArtifactStore；
- artifact hash 稳定；
- schema validation 可阻断 workflow；
- stale artifact routes to refresh / repair before apply/build；
- dashboard 能按 feature_id 展示 artifact chain。

---

# 7. Knowledge Base and Evidence RAG

Detailed Knowledge Base and Evidence RAG design moved to `EVIDENCE_RAG_MCP_SPEC.md`.

`DEV_SPEC.md` keeps the parent workflow, artifact, safety, proposal, review, build, runtime, repair, eval, and dashboard boundaries. RAG/MCP implementation must feed those boundaries through EvidencePack, source authority, retrieval trace, and artifact references.

# 9. Domain Adapter 设计

## 9.1 目标

Domain Adapter 负责把平台能力接入具体 Mod 技术栈。

平台主体不应知道：

```text
GTFO 的目录长什么样
BepInEx log 在哪里
IL2CPP hook 风险是什么
build command 怎么跑
哪些路径安全可编辑
哪些 runtime evidence 有效
```

这些都由 Domain Adapter 提供。

## 9.2 Base Interface

```python
class DomainAdapter(Protocol):
    domain_name: str

    def identify_project(self, root: str) -> DomainProfile:
        ...

    def collect_knowledge_sources(self, profile: DomainProfile) -> list[KnowledgeSource]:
        ...

    def classify_request(self, user_request: str) -> DomainRoute:
        ...

    def build_evidence_queries(self, feature_spec: dict) -> list[EvidenceQuery]:
        ...

    def safe_edit_roots(self, profile: DomainProfile) -> list[str]:
        ...

    def forbidden_paths(self, profile: DomainProfile) -> list[str]:
        ...

    def build_profile(self, profile: DomainProfile) -> BuildProfile:
        ...

    def runtime_profile(self, profile: DomainProfile) -> RuntimeProfile:
        ...

    def verification_strategy(self, feature_spec: dict) -> VerificationPlan:
        ...
```

## 9.3 GTFO Adapter

GTFO Adapter 默认识别：

```text
BepInEx plugin project
C# project file
generated_mods/
BepInEx references
interop assemblies
decompiled API index
plugin config files
BepInEx logs
```

## 9.4 GTFO 风险等级

```text
config_only -> low
ui_feedback_without_hook -> medium
game_hook -> high
runtime_behavior_change -> high
native/interop/reflection-heavy -> critical
unknown -> unknown/block
```

## 9.5 GTFO Managed Paths

优先作为只读、受控修改或显式交付步骤处理：

```text
BepInEx core dlls
game binaries
interop generated dlls
decompiled reference files
legacy_import/raw
knowledge/indexes
artifacts from other feature_id
```

## 9.6 验收标准

- 没有 adapter 时先生成 adapter onboarding / evidence discovery 步骤；
- adapter 能识别 safe_edit_roots；
- adapter 能提供 knowledge sources；
- adapter 能提供 build profile；
- adapter safety policy 能被 path guard 调用。

---

# 10. Planning Layer 设计

## 10.1 目标

Planning Layer 把自然语言请求转成结构化开发合同。

输出：

```text
request_plan.json
feature_spec.json
implementation_plan.json
```

## 10.2 Request Plan

```json
{
  "request_id": "...",
  "user_request": "...",
  "target_domain": "gtfo",
  "target_mod": "BetterHitFeedback",
  "execution_path": "game_hook_investigation",
  "risk_level": "high",
  "ambiguities": [],
  "blocking_questions": [],
  "initial_constraints": [
    "do not change normal hit marker",
    "do not change weakspot marker",
    "do not change damage",
    "do not change sound"
  ]
}
```

## 10.3 Feature Spec

```json
{
  "feature_id": "...",
  "title": "Make GTFO kill marker pink",
  "intent": "ui_feedback_change",
  "target_behavior": {
    "change": "kill marker color becomes pink",
    "scope": "kill marker only"
  },
  "non_goals": [
    "normal hit marker",
    "weakspot marker",
    "damage",
    "sound",
    "other hit feedback behavior"
  ],
  "acceptance": [
    {
      "id": "acc_001",
      "description": "Kill marker appears pink in the target mod.",
      "verification": "runtime evidence or explicit log marker"
    }
  ],
  "risk_level": "high"
}
```

## 10.4 Implementation Plan

```json
{
  "feature_id": "...",
  "plan_id": "...",
  "target_files": [],
  "managed_files": [],
  "required_evidence": [],
  "selected_strategy": "...",
  "alternatives_considered": [],
  "implementation_steps": [],
  "validation_steps": [],
  "rollback_plan": []
}
```

## 10.5 验收标准

- vague request 应先进入 clarification / evidence discovery / planning brief；
- non-goals 必须保留；
- implementation plan 必须引用 evidence；
- implementation boundaries 必须明确；
- acceptance contract 可被 runtime/eval 使用。

---

# 11. Patch Proposal 设计

## 11.1 目标

Patch Proposal 是 LLM 输出代码修改的唯一合法形式。

它不是直接 diff，而是结构化修改计划。

## 11.2 Proposal Schema

```json
{
  "schema_version": "0.3",
  "feature_id": "...",
  "proposal_id": "...",
  "base_artifact_hashes": {
    "feature_spec": "...",
    "implementation_plan": "...",
    "evidence_report": "..."
  },
  "target_files": [],
  "managed_files": [],
  "changes": [
    {
      "change_id": "change_001",
      "operation": "create | modify | delete",
      "file_path": "...",
      "rationale": "...",
      "evidence_ids": [],
      "diff": "..."
    }
  ],
  "expected_validation": {
    "compile": true,
    "runtime": true,
    "manual": true
  },
  "risk_assessment": {
    "risk_level": "high",
    "requires_human_approval": true
  }
}
```

## 11.3 Context Builder

输入：

```text
feature_spec
implementation_plan
evidence_pack
domain_profile
safety_policy
context_pack
```

输出：

```json
{
  "included": [],
  "excluded": [],
  "critical_constraints": [],
  "token_budget": {
    "max": 12000,
    "used": 9300
  }
}
```

## 11.4 No-op Detector

如果 feature 已满足，输出：

```json
{
  "status": "already_satisfied",
  "evidence_ids": [],
  "no_changes_required": true
}
```

## 11.5 验收标准

- proposal schema validates；
- 每个 change 引用 evidence；
- managed file 的处理方式应在 proposal 中说明；
- no-op 不生成假 diff；
- proposal 不直接写文件。

---

# 12. Review Gate 与 Delivery Confidence 设计

## 12.1 目标

Review Gate 是写入前的质量、证据和交付信心提升环节。

## 12.2 Review Checks

```text
schema_validity
artifact_freshness
target_mod_alignment
semantic_alignment
scope_minimality
evidence_binding
path_safety
risk_level
human_approval_required
```

## 12.3 Review Result

```json
{
  "schema_version": "0.3",
  "feature_id": "...",
  "proposal_id": "...",
  "reviewed_proposal_hash": "...",
  "status": "PASS | PASS_WITH_WARNINGS | NEEDS_REVISION | BLOCKED",
  "blocking_findings": [],
  "warnings": [],
  "required_revisions": [],
  "requires_human_approval": true
}
```

## 12.4 Permission Model

工具权限分级：

```text
read_only
report_only
dry_run
confirmed_write
external_process
dangerous
```

默认允许：

```text
read_only
report_only
dry_run
```

需要更高执行级别和显式意图的能力：

```text
confirmed_write
dangerous
```

## 12.5 Path Guard

```python
class PathGuard:
    def validate_path(
        self,
        path: str,
        safe_roots: list[str],
        forbidden_roots: list[str],
    ) -> PathValidationResult:
        ...
```

## 12.6 验收标准

- stale proposal routes to refresh / repair；
- wrong target mod routes to adapter/profile correction；
- semantic drift routes to proposal revision；
- managed path changes route to higher review；
- confirmed write records approval and rollback metadata；
- review result hash 必须匹配 proposal hash。

---

# 13. Dry-run Apply 设计

## 13.1 目标

Dry-run Apply 只计算会发生什么，不实际写文件。

## 13.2 Dry-run Result

```json
{
  "feature_id": "...",
  "proposal_id": "...",
  "would_create": [],
  "would_modify": [],
  "would_delete": [],
  "blocked_paths": [],
  "patch_conflicts": [],
  "safe_to_apply": false,
  "requires_human_approval": true
}
```

## 13.3 验收标准

- dry-run 不写文件；
- 会列出 would-change files；
- path conflict 可见；
- blocked path 可见；
- confirmed apply 不在第一版启用。

---

# 14. Build Adapter 设计

## 14.1 目标

Build Adapter 把不同 Mod 项目的构建命令抽象为统一接口。

## 14.2 Build Profile

```json
{
  "build_system": "dotnet",
  "project_file": "...",
  "command": "dotnet build",
  "working_dir": "...",
  "expected_outputs": [],
  "log_path": "..."
}
```

## 14.3 Build Result

```json
{
  "feature_id": "...",
  "status": "success | failed | skipped",
  "command": "...",
  "exit_code": 0,
  "stdout_path": "...",
  "stderr_path": "...",
  "errors": [],
  "warnings": [],
  "duration_ms": 0
}
```

## 14.4 Error Classifier

错误类型：

```text
syntax_error
missing_reference
namespace_error
api_mismatch
il2cpp_access_error
config_binding_error
unsafe_path_error
unknown
```

## 14.5 验收标准

- build output 结构化；
- error classifier 可单测；
- build failure 进入 repair plan；
- build success 不等于 runtime verified。

---

# 15. Runtime Evidence 与 Multimodal 设计

## 15.1 目标

Runtime Evidence 用来证明游戏内行为，而不是只证明插件加载。

## 15.2 Evidence Source

```text
BepInEx startup log
plugin runtime marker
manual note
screenshot
vision summary
config snapshot
```

## 15.3 Runtime Evidence Schema

```json
{
  "feature_id": "...",
  "startup_loaded": true,
  "gameplay_behavior_verified": false,
  "evidence_items": [
    {
      "type": "log | screenshot | manual_note | vision_summary",
      "source": "...",
      "locator": "...",
      "supports_acceptance": [],
      "confidence": 0.0
    }
  ],
  "verification_status": "verified | partial | failed | inconclusive"
}
```

## 15.4 Screenshot Registry

```sql
CREATE TABLE screenshots (
    screenshot_id TEXT PRIMARY KEY,
    feature_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    captured_at TIMESTAMP,
    caption TEXT,
    metadata_json TEXT
);
```

## 15.5 Vision Captioner

可选模块。

失败回退：

```text
vision unavailable -> keep screenshot metadata only
caption low quality -> mark low_confidence
manual verification available -> use manual note
```

## 15.6 验收标准

- startup_loaded 与 gameplay_behavior_verified 分离；
- screenshot 有 metadata；
- vision output 可选；
- runtime evidence 可进入 repair loop；
- dashboard 能展示 runtime timeline。

---

# 16. Repair Loop 设计

## 16.1 目标

Repair Loop 根据失败证据生成修复计划，而不是盲目重试。

## 16.2 Repair Plan

```json
{
  "feature_id": "...",
  "failure_source": "build | runtime | eval",
  "failure_evidence": [],
  "root_cause_hypotheses": [],
  "recommended_fix_strategy": "...",
  "forbidden_regressions": [],
  "requires_new_evidence": true
}
```

## 16.3 验收标准

- repair plan 引用失败证据；
- repair proposal 仍需 review；
- repair loop 需要 attempt budget、stop condition 和下一步交付建议；
- 每轮 repair 记录 attempt number；
- regression guard 保留原 acceptance。

---

# 17. Memory 与 Context Compression 设计

## 17.1 目标

解决长上下文和旧项目污染。

## 17.2 Context Pack

```json
{
  "context_pack_id": "...",
  "feature_id": "...",
  "included_artifacts": [],
  "excluded_artifacts": [
    {
      "artifact": "...",
      "reason": "stale | irrelevant | legacy_quarantined | token_budget"
    }
  ],
  "critical_constraints": [],
  "domain_assumptions": [],
  "token_budget": {
    "max_tokens": 12000,
    "used_tokens": 8000
  }
}
```

## 17.3 Legacy Import

旧项目导入流程：

```text
raw legacy fragment
  -> classify
  -> summarize
  -> extract reusable principle
  -> reject obsolete implementation
  -> index accepted summary
```

分类：

```text
reusable_schema
reusable_domain_knowledge
reusable_eval_case
reusable_test_pattern
obsolete_code
sample_specific_noise
```

## 17.4 验收标准

- raw legacy 默认不进入 prompt；
- context pack 报告 included/excluded；
- critical constraints 不丢；
- token budget 可见；
- Codex/LLM 不依赖历史聊天。

---

# 18. Evaluation Harness 设计

## 18.1 目标

Harness 评估 Agent 决策质量，不替代 unit test。

## 18.2 Eval Case

```json
{
  "case_id": "...",
  "category": "request_planning | evidence_retrieval | proposal_review | dry_run | build_repair | golden_path",
  "input": {},
  "expected": {
    "route": "...",
    "risk_level": "...",
    "must_block": false,
    "required_artifacts": [],
    "required_evidence": []
  },
  "scoring": {
    "metrics": []
  }
}
```

## 18.3 Metrics

```text
path_accuracy
risk_classification_accuracy
evidence_recall
evidence_precision
evidence_gap_detection
implementation_plan_completeness
proposal_schema_validity
semantic_alignment_correctness
review_block_correctness
dry_run_safety
build_error_classification_accuracy
repair_plan_correctness
golden_path_success_rate
```

## 18.4 Harness Interface

```python
class EvaluationHarness:
    def run_case(self, case_path: str) -> EvalResult:
        ...

    def run_suite(self, suite_name: str) -> EvalReport:
        ...

    def compare_reports(self, before: str, after: str) -> RegressionReport:
        ...
```

## 18.5 Eval Report

```json
{
  "suite": "golden_path",
  "total_cases": 10,
  "passed": 8,
  "failed": 2,
  "metrics": {
    "path_accuracy": 0.9,
    "review_block_correctness": 1.0
  },
  "failures": []
}
```

## 18.6 验收标准

- harness 可独立运行；
- eval report 输出 JSON + Markdown；
- dashboard 展示 eval；
- README claim 映射 metric；
- regression report 可比较前后变化。

---

# 19. Observability 与 Dashboard 设计

## 19.1 目标

让 Agent 的每一步都可见。

## 19.2 Trace Event

```python
class TraceEvent(TypedDict):
    trace_id: str
    run_id: str
    feature_id: str
    node_name: str
    stage: str
    status: str
    started_at: str
    ended_at: str
    duration_ms: int
    inputs_summary: dict
    outputs_summary: dict
    artifacts_written: list[str]
    blockers: list[dict]
    warnings: list[dict]
    metrics: dict
```

## 19.3 Trace Storage

```text
logs/traces.jsonl
data/db/workflow_checkpoints.db
```

## 19.4 Dashboard 页面

```text
Overview
Workflow Run Viewer
Artifact Browser
Evidence Browser
Patch Proposal Viewer
Review Gate Viewer
Build / Runtime Timeline
Repair Loop Viewer
Evaluation Dashboard
Legacy Import Viewer
```

## 19.5 页面设计

### Overview

显示：

```text
当前 domain adapter
feature 数量
成功/失败/blocked 数量
最近 eval summary
知识库 source 数量
```

### Workflow Run Viewer

显示：

```text
graph node timeline
current stage
blocked reason
human approval point
```

### Evidence Browser

显示：

```text
retrieved evidence
excluded evidence
gaps
source type distribution
evidence-to-change binding
```

### Patch Proposal Viewer

显示：

```text
target files
diff preview
change rationale
evidence bindings
risk assessment
```

### Evaluation Dashboard

显示：

```text
suite results
metric trends
regression report
failed cases
```

## 19.6 验收标准

- 每个 node 写 trace；
- dashboard 可按 feature_id 查看完整链路；
- evidence 与 patch change 能互跳；
- eval report 可视化；
- demo 不需要翻一堆 JSON 才能讲清楚。

---

# 20. MCP / API / CLI 设计

CLI and API remain graph-command and artifact-reader surfaces in this parent spec. Detailed MCP protocol, tool schema, safe read/report tools, and approved-route direction moved to `EVIDENCE_RAG_MCP_SPEC.md`.

MCP tools must not bypass LangGraph, review gates, artifact contracts, permission policy, or runtime safety gates.

# 21. 配置系统设计

## 21.1 settings.yaml

```yaml
project:
  name: controlled-mod-agent
  default_domain: gtfo

workflow:
  checkpointer: sqlite
  checkpoint_db: data/db/workflow_checkpoints.db
  max_repair_attempts: 3

knowledge:
  db_path: data/db/knowledge.db
  raw_dir: knowledge/raw
  processed_dir: knowledge/processed
  indexes_dir: knowledge/indexes

retrieval:
  deterministic_enabled: true
  symbol_enabled: true
  vector_enabled: false
  vector_backend: chroma
  fusion_algorithm: rrf
  rerank_backend: none
  top_k: 20

embedding:
  provider: fake
  model: local-fake
  dimension: 384

llm:
  provider: openai_compatible
  model: default
  temperature: 0.0

safety:
  confirmed_write_enabled: false
  require_review_for_dry_run: true
  require_human_approval_for_high_risk: true

domain:
  gtfo:
    project_root: .
    generated_mods_dir: generated_mods
    decompiled_dir: knowledge/raw/decompiled
    bep_in_ex_log: logs/LogOutput.log

observability:
  enabled: true
  trace_file: logs/traces.jsonl

dashboard:
  enabled: true
  port: 8501

evaluation:
  cases_dir: eval_cases
  reports_dir: reports/eval
```

## 21.2 验收标准

- 所有 provider 可配置；
- 测试中可用 fake provider；
- 缺配置时给出明确错误；
- 配置应把 fallback、降级和升级路径写成显式结果。

---

# 22. 测试方案

## 22.1 测试理念

本项目采用 TDD + Evaluation Harness 双层测试。

```text
unit tests -> 验证模块逻辑
integration tests -> 验证模块协作
golden tests -> 验证端到端路径
eval harness -> 验证 agent 决策质量
```

## 22.2 单元测试

覆盖：

```text
artifact schema
stale detection
request planning
evidence retrieval
path guard
proposal review
dry-run apply
build error classifier
runtime evidence parser
context pack
eval metrics
```

## 22.3 集成测试

覆盖：

```text
real LangGraph graph with stubbed business nodes end-to-end
knowledge ingestion -> retrieval
feature spec -> evidence -> implementation plan
proposal -> review -> dry-run
build failure -> repair plan
```

## 22.4 Golden Path Tests

```text
config_only_success
hook_request_blocks_without_evidence
wrong_target_mod_blocked
semantic_drift_blocked
build_failure_creates_repair_plan
runtime_startup_not_equal_verified
```

## 22.5 性能测试

| 测试 | 指标 | 工具 |
|---|---|---|
| retrieval latency | P50/P95 | pytest-benchmark |
| knowledge indexing | docs/sec | custom |
| eval suite time | total duration | custom |
| dashboard loading | page load time | manual |

## 22.6 验证命令

```powershell
python -B -m compileall src
python -B -m unittest discover -s tests
python -m mod_agent.evaluation.runner --suite golden_path
```

---

# 23. CI/CD 与质量门禁

## 23.1 本地质量门禁

必须通过：

```text
compileall
unit tests
golden tests
schema validation
```

可选：

```text
coverage
lint
type check
eval regression
```

## 23.2 GitHub Actions

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e .[dev]
      - run: python -B -m compileall src
      - run: python -B -m unittest discover -s tests
      - run: python -m mod_agent.evaluation.runner --suite smoke
```

## 23.3 验收标准

- PR 应保持 unit tests 通过或附带明确 repair/eval 记录；
- eval regression 需要报告；
- CI 不调用真实 LLM；
- CI 不需要游戏本体；
- CI 不写 generated source。

---

# 24. 项目排期

## 24.1 排期原则

```text
先平台骨架，再默认实现
先 deterministic，再 vector
先 dry-run，再 confirmed write
先 harness，再宣传 claim
先 dashboard 可解释，再复杂自动化
```

## 24.2 阶段总览

### Phase A：工程骨架与 LangGraph Runtime Skeleton

目标：

```text
项目可安装、真实 LangGraph StateGraph 可跑、业务节点可 stub、
artifact 可写、trace 可见。
```

交付：

```text
pyproject.toml
workflow/state.py
workflow/graph.py
artifacts/store.py
observability/trace.py
tests
```

验收：

```text
stub request -> done
blocked path works
artifact store writes
trace event exists
```

### Phase B：Artifact Contract

目标：

```text
所有阶段输出结构化 artifact。
```

验收：

```text
schema validation
stale detection
artifact hash binding
dashboard artifact browser stub
```

### Phase C：Knowledge Base

目标：

```text
索引源码、artifact、log、domain doc。
```

验收：

```text
knowledge.db created
source registry works
symbol index works
incremental indexing works
```

### Phase D：Evidence RAG

目标：

```text
deterministic retrieval + evidence pack + readiness。
```

验收：

```text
retrieved/excluded/gaps
insufficient evidence blocks
implementation plan references evidence
```

### Phase E：Planning

目标：

```text
自然语言 -> request_plan -> feature_spec -> implementation_plan。
```

验收：

```text
risk classification
acceptance contract
forbidden changes
```

### Phase F：Patch Proposal + Review

目标：

```text
LLM 生成 proposal，apply 能力由 review、dry-run、approval 和 rollback metadata 推进。
```

验收：

```text
proposal schema
review block cases
semantic drift detection
```

### Phase G：Dry-run Apply + Build

目标：

```text
dry-run file plan + build result。
```

验收：

```text
no real writes
build errors classified
repair plan on failure
```

### Phase H：Runtime Evidence + Repair

目标：

```text
log/screenshot/manual evidence + repair loop。
```

验收：

```text
startup != gameplay verified
runtime evidence schema
repair proposal gated
```

### Phase I：Evaluation Harness

目标：

```text
可评估 planning/retrieval/review/golden path。
```

验收：

```text
eval report JSON/Markdown
regression comparison
README claim mapping
```

### Phase J：Dashboard + MCP

目标：

```text
项目可展示，可通过 MCP 查询。
```

验收：

```text
dashboard pages
MCP read-only tools
no dangerous tool exposure
```

---

# 25. 旧项目吸收策略

## 25.1 原则

旧项目不是直接迁移对象，而是知识来源。

推荐推进方式：

```text
旧 src 进入 source review / reference extraction
generated_mods 进入 fixture / build evidence / migration input
旧 prompt 提炼为 prompt contract 或 eval case
旧 artifact 作为 historical evidence，升级为当前 artifact 后再消费
旧上下文提炼为 architecture note，再由当前架构吸收
```

允许吸收：

```text
domain knowledge
failure cases
artifact schema lessons
review gate lessons
eval cases
demo lessons
```

## 25.2 流程

```text
legacy_import/raw
  -> classify
  -> summarize
  -> extract reusable principle
  -> accept/reject
  -> index accepted summary
```

## 25.3 验收标准

- 每个 legacy import 有 summary；
- 每个 accepted fragment 有 reason；
- rejected fragment 有 reason；
- raw legacy 不进入 patch context；
- legacy viewer 可展示状态。

---

# 26. Demo 与简历包装

## 26.1 Demo Matrix

| Demo | 展示能力 |
|---|---|
| Config-only request | low-risk workflow |
| Hook request blocked | evidence gate |
| Wrong target proposal | review gate |
| Build failure repair | repair loop |
| Eval regression | harness |
| Dashboard walkthrough | observability |

## 26.2 简历 Bullet

```text
Built a LangGraph-based controlled code generation platform for game mod development,
with artifact-driven workflow state, evidence-oriented RAG over source code and
domain knowledge, review gates for patch safety, dry-run execution, build/runtime
feedback loops, and an evaluation harness for agent decision quality.
```

## 26.3 Caveats

README 必须说明：

```text
confirmed apply disabled by default
runtime verification may require manual evidence
GTFO adapter is first domain only
vector retrieval optional
MCP write tools disabled by default
```

---

# 27. 可扩展性与未来展望

## 27.1 新 Domain Adapter

新增步骤：

```text
implement DomainAdapter
define safe edit roots
define forbidden paths
define build profile
define runtime profile
define evidence sources
add eval cases
```

## 27.2 新 Retrieval Backend

新增步骤：

```text
implement VectorRetriever
register backend
add config option
add retrieval eval cases
```

## 27.3 新 Review Rule

新增步骤：

```text
implement ReviewCheck
add to ProposalReviewer
add unit tests
add blocked eval case
```

## 27.4 新 Dashboard 页面

新增步骤：

```text
add service
add page
read artifact/trace/eval data
avoid direct workflow mutation
```

## 27.5 未来方向

```text
multi-domain mod support
confirmed apply with signed approval
automated runtime test harness
vision-based gameplay verification
LangGraph remote execution
MCP resource browser
eval-driven prompt optimization
```

---

# 28. 第一版完成定义

第一版完成不要求真实自动做复杂 Mod。

第一版必须证明：

```text
LangGraph graph 可跑
Artifact contract 成立
Knowledge base 可索引
Evidence RAG 可阻断/继续
Patch proposal 受 review gate 控制
Dry-run 安全
Build failure 可进入 repair
Evaluation harness 可跑
Dashboard 能解释流程
```

第一版不强求：

```text
confirmed apply
真实 gameplay 自动验证
复杂 vision
多 domain adapter
生产级 API
```

第一版的成功标准是：

```text
这个项目已经不是旧碎片集合，而是一个可解释、可评估、可扩展的受控 Agent 平台骨架。
```

---

# 29. Developer Execution Layer

本章是 `DEV_SPEC.md` 相比 `spec.md` 增加的核心实施层。  
前文回答“系统是什么”，本章回答“开发 agent 应该怎么把系统做出来”。

## 29.1 总体实施节奏

推荐节奏不是先做炫酷 demo，而是先建立平台骨架：

```text
Day 1:
  Phase A：项目骨架、LangGraph workflow、artifact store、permission model、trace event

Day 2:
  Phase B-C：artifact contract、knowledge source registry、deterministic evidence retrieval

Day 3-4:
  Phase D-F：planning、feature spec、implementation plan、patch proposal、review gate

Day 5:
  Phase G-H：dry-run apply、build adapter、runtime evidence、repair loop

Week 2:
  Phase I-K：memory compression、evaluation harness、dashboard、MCP/API、demo packaging
```

每一天都必须保持下面的完成状态：

```text
main importable
focused tests passing
artifacts written through store
trace events emitted
side effects routed through explicit approval and rollback/evidence records
README or docs updated when user-facing behavior changes
```

## 29.2 每个 phase 的最低交付物

每个 phase 至少交付四类东西：

| 类型 | 说明 |
| --- | --- |
| Code | 真实模块、接口或 stub，文档更新应服务于可运行能力 |
| Artifact | 该阶段产生的结构化输出 |
| Test | 单元测试或集成测试 |
| Trace | 可解释的事件记录，方便 dashboard 和 eval 复用 |

如果某阶段暂时是 stub，也必须满足：

```text
stub has same public interface as future real implementation
stub writes the same artifact shape as future implementation
stub exposes explicit status="stubbed"
stub exposes the next evidence step toward real success
```

## 29.3 文件命名约定

推荐顶层 Python 包：

```text
src/mod_agent/
```

除非已经进入某个 phase，否则不要提前创建空目录。目录增长应跟随真实模块增长。

核心命名规则：

```text
workflow/        LangGraph state, graph, nodes, transitions
artifacts/       artifact envelope, store, schemas, validators
planning/        request routing, feature spec, implementation plan
knowledge/       source discovery, loaders, indexing
evidence/        retrieval, fusion, rerank, readiness
domain/          adapters and risk policies
proposal/        patch proposal generation and context builder
review/          proposal review gate and safety findings
apply/           dry-run patch apply and path guards
build/           build profiles, runners, error classifier
runtime/         log/screenshot/manual evidence collection
repair/          failure analysis and repair plan
memory/          artifact index and context pack
evaluation/      eval cases, runner, metrics, reports
observability/   trace event schema and storage
dashboard/       local visual UI
api/             HTTP API
mcp/             MCP tools and resources
tools/           tool registry and permission model
model/           LLM provider abstractions
config/          settings loading and validation
```

## 29.4 Artifact envelope 标准

所有 artifact 都必须采用统一 envelope。不要让每个模块随意写 JSON。

```json
{
  "schema_version": "1.0",
  "artifact_type": "feature_spec",
  "feature_id": "20260623_001_example",
  "run_id": "run_...",
  "stage": "draft_feature_spec",
  "status": "success",
  "created_at": "2026-06-23T00:00:00Z",
  "inputs": {
    "request_id": "req_...",
    "upstream_artifacts": []
  },
  "data": {},
  "warnings": [],
  "blockers": [],
  "trace_refs": []
}
```

最小字段要求：

| 字段 | 规则 |
| --- | --- |
| `schema_version` | 必须存在，便于迁移 |
| `artifact_type` | 必须是注册类型 |
| `feature_id` | feature 级 artifact 必须存在 |
| `run_id` | workflow run 级 artifact 必须存在 |
| `stage` | 必须等于产生它的 graph node 或 phase |
| `status` | `success`、`blocked`、`failed`、`stubbed`、`skipped` 之一 |
| `data` | 业务内容只能放这里 |
| `blockers` | 阻塞原因必须结构化 |
| `trace_refs` | 关联 trace event id |

## 29.5 Trace event 标准

每个 graph node 至少产生两个 trace event：

```text
node_started
node_finished
```

失败或阻塞时额外产生：

```text
node_blocked
node_failed
repair_requested
human_approval_required
```

Trace event schema：

```json
{
  "event_id": "evt_...",
  "run_id": "run_...",
  "feature_id": "feature_...",
  "stage": "retrieve_evidence",
  "event_type": "node_finished",
  "timestamp": "2026-06-23T00:00:00Z",
  "duration_ms": 123,
  "status": "success",
  "summary": "retrieved 8 evidence items",
  "artifact_refs": ["artifacts/features/.../evidence_pack.json"],
  "metrics": {},
  "warnings": [],
  "blockers": []
}
```

禁止把 trace 写成自然语言流水账。Dashboard、eval、debug 都要能读取结构化字段。

---

# 30. Phase A：LangGraph Runtime Skeleton With Stubbed Business Nodes

## 30.1 目标

Phase A 的目标是建立平台骨架，而不是实现真实 mod 修改。

完成后必须成立：

```text
用户请求可以进入 graph
graph 可以走完 stubbed-business-node golden path
每个 node 更新 state
每个 node 通过 artifact store 写 artifact
每个 node 写 trace event
危险动作默认不执行
测试能证明 normal path 与 blocked path
```

## 30.2 文件清单

```text
pyproject.toml
README.md
src/mod_agent/__init__.py
src/mod_agent/workflow/state.py
src/mod_agent/workflow/graph.py
src/mod_agent/workflow/nodes.py
src/mod_agent/workflow/transitions.py
src/mod_agent/artifacts/envelope.py
src/mod_agent/artifacts/store.py
src/mod_agent/observability/trace.py
src/mod_agent/tools/permissions.py
tests/test_workflow_graph.py
tests/test_artifact_store.py
tests/test_permissions.py
```

## 30.3 A1：项目骨架

实现内容：

```text
create package src/mod_agent
create pyproject.toml
define project metadata
configure pytest
configure ruff or minimal lint later, not required on day 1
```

验收标准：

```text
python -c "import mod_agent" succeeds when installed/editable
pytest discovers tests
README names project and first milestone
```

交付边界：

```text
不要复制旧项目 src
不要提前创建大量空模块
不要在 Phase A 连接真实游戏目录
```

## 30.4 A2：Graph State

核心 state 必须是 TypedDict 或 Pydantic model。推荐先用 TypedDict 保持轻量。

```python
class ModAgentState(TypedDict):
    run_id: str
    request_id: str
    feature_id: str | None
    user_request: str
    target_domain: str
    target_mod: str | None
    execution_path: str | None
    risk_level: str | None
    current_stage: str
    artifacts: dict[str, str]
    approvals: dict[str, bool]
    blockers: list[dict]
    trace: list[dict]
    metrics: dict[str, object]
```

实现要求：

```text
state initializer must create run_id and request_id
feature_id may be None before planning
current_stage starts as "start"
artifacts starts empty
approvals starts empty
blockers starts empty
```

测试：

```text
state initializer returns required keys
state can be serialized to JSON-compatible dict
missing user_request is rejected or blocked
```

## 30.5 A3：Artifact Store

Artifact store 是所有阶段写文件的唯一入口。

接口草案：

```python
class ArtifactStore:
    def write(self, feature_id: str, artifact_type: str, payload: Mapping[str, Any]) -> ArtifactRef: ...
    def read(self, ref: ArtifactRef) -> dict[str, Any]: ...
    def list_feature_artifacts(self, feature_id: str) -> list[ArtifactRef]: ...
    def exists(self, ref: ArtifactRef) -> bool: ...
```

路径规则：

```text
artifacts/features/<feature_id>/<artifact_type>.json
artifacts/runs/<run_id>/workflow_trace.jsonl
```

验收标准：

```text
write creates parent directories
write wraps payload in envelope
read returns same envelope
artifact_type is validated
paths cannot escape artifact root
```

## 30.6 A4：Permission Model

Phase A 只实现权限模型，不执行危险命令。

权限分级：

| Level | 示例 | 默认 |
| --- | --- | --- |
| `read_only` | read file, list artifacts | allowed |
| `report_only` | planning, retrieval report | allowed |
| `dry_run_write` | patch dry-run, diff simulation | allowed with explicit phase |
| `confirmed_write` | modify generated source | blocked |
| `external_side_effect` | copy into game directory, run external executable | blocked |

接口草案：

```python
class PermissionDecision(TypedDict):
    allowed: bool
    level: str
    reason: str
    required_approval: str | None
```

测试：

```text
read_only is allowed
confirmed_write records approval and rollback metadata
external_side_effect records approval and runtime/build evidence
decision includes reason
```

## 30.7 A5：Stub Nodes

Phase A 的 graph nodes：

```text
plan_request
draft_feature_spec
retrieve_evidence
create_implementation_plan
generate_patch_proposal
review_proposal
dry_run_apply
build
collect_runtime_evidence
create_repair_plan
evaluate
done
blocked
```

每个 stub node 必须：

```text
receive state
set current_stage
write an artifact with status="stubbed"
emit trace event
return updated state
```

推荐推进方式：

```text
stub node reports capability_level and next_real_step
stub node produces the same artifact shape as the future real node
stub node connects to retrieval / patch / generated source work through explicit follow-up tasks
```

## 30.8 A6：Graph Transitions

最小正常路径：

```text
start
-> plan_request
-> draft_feature_spec
-> retrieve_evidence
-> create_implementation_plan
-> generate_patch_proposal
-> review_proposal
-> dry_run_apply
-> build
-> collect_runtime_evidence
-> evaluate
-> done
```

最小阻塞路径：

```text
plan_request -> blocked
retrieve_evidence -> blocked
review_proposal -> blocked
dry_run_apply -> blocked
```

测试：

```text
normal path reaches done
vague request can route to blocked
blocked state includes blocker reason
trace contains node_started and node_finished
```

---

# 31. Phase B：Artifact Contract

## 31.1 目标

Phase B 要把 artifact 从“能写 JSON”升级为“系统契约”。

必须实现：

```text
registered artifact types
schema validation
stale detection
artifact dependency graph
artifact lifecycle status
contract tests
```

## 31.2 Artifact 类型注册表

首批类型：

```text
request_planning_report
feature_spec
evidence_pack
implementation_plan
patch_proposal
proposal_review
dry_run_result
build_result
runtime_evidence
repair_plan
eval_report
workflow_trace
```

每种类型必须声明：

```text
artifact_type
schema_version
required_fields
producer_stage
allowed_statuses
stale_inputs
```

## 31.3 Stale Detection

当上游 artifact 改变后，下游 artifact 进入 refresh / repair 路由。

推荐实现：

```text
每个 artifact envelope 记录 inputs.upstream_artifacts
每个 upstream ref 记录 path + sha256
read artifact 时可检查 upstream sha256 是否变化
变化则 status_view = stale
```

验收标准：

```text
修改 feature_spec 后 implementation_plan 被识别 stale
stale artifact routes to refresh before patch proposal review
dashboard 可以显示 stale reason
```

---

# 32. Phase C: Knowledge Base and Evidence RAG

Phase C/D RAG implementation detail moved to `EVIDENCE_RAG_MCP_SPEC.md`.

The parent requirement remains: Knowledge Base and Evidence RAG must produce inspectable evidence for planning, proposal, review, repair, eval, and dashboard flows, not final patch authority by themselves.

# 33. Phase D-F：Planning, Proposal, Review

## 33.1 Request Planning

Request planning 不负责写代码，只负责把用户请求变成 route decision。

执行路径：

```text
quick_patch
standard_feature
game_hook_investigation
full_runtime_investigation
repair_loop
blocked_ambiguous
blocked_out_of_scope
```

输出 artifact：

```json
{
  "route": "standard_feature",
  "risk_level": "medium",
  "target_mod": "BetterHitFeedback",
  "requires_hook_evidence": true,
  "requires_runtime_evidence": false,
  "uncertainties": [],
  "blocked": false
}
```

## 33.2 Feature Spec

Feature spec 必须把自然语言愿望变成可验收需求。

必填字段：

```text
feature_id
user_request
target_behavior
non_goals
target_mod
risk_level
acceptance_criteria
evidence_requirements
runtime_verification_plan
```

反例：

```text
"让体验更好" 先进入 clarification / planning brief
"修一下那个问题" 没有上下文时生成 clarification / evidence request
```

## 33.3 Implementation Plan

Implementation plan 是“准备怎么改”，不是 patch。

必填字段：

```text
target_files
target_symbols
evidence_refs
proposed_changes
side_effect_boundaries
test_plan
rollback_plan
open_questions
```

验收标准：

```text
每个 proposed_change 至少绑定一个 evidence_ref
每个 target_file 必须在允许范围内
高风险计划必须声明 runtime verification
open_questions 非空且 blocking=true 时先进入 clarification / evidence discovery
```

## 33.4 Patch Proposal

Patch proposal 是 reviewable artifact，不是直接写文件。

必填字段：

```text
proposal_id
feature_id
summary
files
diff_intent
evidence_refs
scope_boundary
risk_assessment
expected_tests
manual_review_notes
```

推荐推进方式：

```text
不要在 proposal 阶段修改源文件
不要生成未绑定 evidence 的 hook 修改
不要把 unrelated refactor 塞进 proposal
不要把 no-op 当成 patch
```

## 33.5 Review Gate

Review gate 至少检查：

```text
schema_validity
evidence_binding
scope_boundary
target_alignment
risk_policy
forbidden_paths
permission_level
test_plan_presence
no_op_detection
```

Review result：

```json
{
  "decision": "approve_dry_run",
  "findings": [],
  "required_changes": [],
  "allowed_next_stage": "dry_run_apply"
}
```

决策枚举：

```text
approve_dry_run
revise_proposal
blocked_insufficient_evidence
blocked_scope_risk
blocked_requires_human
already_satisfied
```

---

# 34. Phase G-H：Dry-run, Build, Runtime, Repair

## 34.1 Dry-run Apply

Dry-run apply 的目标是证明 patch 可以被应用，但不真正写入最终 source。

必须输出：

```text
changed_files
diff_stats
path_guard_result
conflict_result
would_write
permission_required
```

验收标准：

```text
dry-run 不修改 generated source
路径逃逸被拒绝
forbidden path 被拒绝
diff stats 可读
失败进入 repair 或 blocked
```

## 34.2 Confirmed Apply

第一版不要求 confirmed apply。  
如果后续实现，必须满足：

```text
requires human approval artifact
approval includes proposal_id and diff hash
write only allowed after review decision approve_write
write emits irreversible_side_effect trace event
rollback hint is recorded
```

## 34.3 Build Adapter

Build adapter 不是简单跑 shell。它必须把构建结果结构化。

Build profile：

```json
{
  "profile_id": "gtfo_bepinex_il2cpp",
  "working_directory": "generated_mods/BetterHitFeedback",
  "command": ["dotnet", "build"],
  "expected_artifacts": ["bin/Debug/BetterHitFeedback.dll"],
  "timeout_seconds": 120
}
```

Build result：

```json
{
  "status": "failed",
  "exit_code": 1,
  "duration_ms": 12000,
  "stdout_excerpt": "",
  "stderr_excerpt": "",
  "error_class": "compile_error",
  "diagnostics": []
}
```

Error classes：

```text
compile_error
missing_reference
api_mismatch
package_restore_failure
timeout
permission_denied
unknown
```

## 34.4 Runtime Evidence

Runtime evidence 不是“我觉得能用”。它至少来自：

```text
runtime log
manual user confirmation
screenshot
video frame
game-side artifact
```

MVP 可以只支持手动 evidence，但必须结构化：

```json
{
  "source": "manual_confirmation",
  "claim": "kill marker became pink and normal hit marker did not change",
  "confidence": "medium",
  "attachments": [],
  "limitations": ["manual observation only"]
}
```

## 34.5 Repair Loop

Repair plan 不是“再试一次”。它必须说明失败类型、假设、最小修复。

字段：

```text
failure_source
failure_class
evidence_refs
hypothesis
minimal_changes
retry_budget
stop_condition
```

推荐推进方式：

```text
不要无限 repair
不要在没有新 evidence 时扩大 scope
不要用 repair loop 绕过 review gate
```

---

# 35. Phase I-K：Memory, Eval, Dashboard, MCP/API

## 35.1 Memory and Context Compression

本项目 memory 的 source of truth 是 artifact，不是聊天记录。

Context pack 生成逻辑：

```text
select feature artifacts
rank by relevance and recency
preserve critical constraints
compress long evidence excerpts
report included/excluded artifacts
report token budget
```

Context pack 必填：

```text
feature_id
purpose
included_artifacts
excluded_artifacts
critical_constraints
evidence_summary
open_blockers
token_estimate
```

## 35.2 Evaluation Harness

Eval 不是装饰。它用于证明 agent 决策质量可回归。

首批指标：

```text
path_accuracy
risk_accuracy
evidence_recall
proposal_schema_validity
review_block_correctness
dry_run_safety
repair_plan_quality
golden_path_completion
```

Eval case：

```json
{
  "case_id": "quick_patch_config_default",
  "user_request": "Change default EnableDiagnosticLogging to false.",
  "expected_route": "quick_patch",
  "expected_risk": "low",
  "expected_blocked": false,
  "must_not_require_hook_evidence": true
}
```

最低验收：

```text
eval runner can run all cases
report includes pass/fail per metric
regression summary is written as artifact
dashboard can read eval report
```

## 35.3 Dashboard

Dashboard 必须解释 workflow，而不是做漂亮壳。

第一版页面：

```text
Overview
Workflow Run Viewer
Artifact Browser
Evidence Browser
Patch Proposal Viewer
Review Findings
Evaluation Dashboard
```

每个页面必须回答一个问题：

| 页面 | 回答的问题 |
| --- | --- |
| Overview | 当前系统有哪些 run、feature、失败和阻塞 |
| Workflow Run Viewer | 某次请求走到哪一步，为什么停下 |
| Artifact Browser | 产生了哪些 artifact，是否 stale |
| Evidence Browser | patch 依据哪些证据，证据是否充分 |
| Patch Proposal Viewer | 准备改哪些文件，scope 是否可控 |
| Review Findings | 为什么允许或阻止下一步 |
| Evaluation Dashboard | 系统在哪些决策上退化 |

## 35.4 MCP/API

MCP/API 默认只暴露 safe tools。

首批 tools：

```text
plan_request
list_artifacts
read_artifact
retrieve_evidence
review_proposal
run_eval
get_workflow_status
```

默认不暴露：

```text
confirmed_apply
copy_to_game_directory
run_external_game
delete_artifacts
```

接口规则：

```text
MCP/API 通过 graph state 推进
MCP/API 写 source 走 proposal/review/dry-run/apply 链路
所有 tool 输出都必须有 schema
危险工具必须返回 required_approval 而不是执行
```

---

# 36. Agent Implementation Checklists

## 36.1 开始任一 phase 前

必须检查：

```text
读过 SKILL.md
读过 DEV_SPEC.md 对应 phase
确认当前 git/worktree 状态
确认不会复制旧 source
确认该 phase 的文件清单
确认最低测试命令
```

## 36.2 修改代码前

必须回答：

```text
这个改动属于哪个 phase？
会新增或修改哪些 artifact？
是否改变 graph transition？
是否改变 permission boundary？
是否需要新增测试？
是否存在危险 side effect？
```

## 36.3 完成阶段前

必须验证：

```text
python -B -m compileall src
python -B -m unittest discover -s tests
```

如果项目采用 pytest，则改为：

```text
python -B -m pytest
```

并在 README 或本文件相关位置更新验证命令。

## 36.4 高杠杆推进方式

```text
README 更新应绑定代码、artifact、测试或 demo 入口。
Prompt 工作应沉淀为 artifact schema、node contract 或 eval case。
Patch 生成应尽快接入 evidence、review、dry-run、build/runtime 验证链。
Apply 能力按 dry-run -> reviewed write -> rollback metadata 的顺序推进。
Runtime success 应由 log、marker、screenshot、manual/probe evidence 逐步升级。
旧项目目录作为 knowledge source、reference pattern、fixture 或 migration input 使用。
Demo 状态应展示真实 workflow 状态，并把 blocked/repair 变成可操作下一步。
Trace 优先结构化，同时允许 dashboard 生成可读摘要。
Eval case 应和新能力同步补充，避免最后集中补课。
```

## 36.5 第一周完成定义

第一周完成不要求真实自动改出复杂 Mod。第一周完成要求平台骨架可信。

必须能演示：

```text
natural language request
-> graph run
-> request planning artifact
-> feature spec artifact
-> evidence pack artifact
-> implementation plan artifact
-> patch proposal artifact
-> review result artifact
-> dry-run result artifact
-> eval report artifact
-> dashboard view
```

允许仍然 stub：

```text
real vector embeddings
real reranker
real confirmed apply
real gameplay runtime automation
production MCP server
multi-domain adapter
```

第一周建议真实落地：

```text
graph state
artifact store
permission model
trace event schema
review decision schema
eval case runner
```

## 36.6 面试讲述角度

最终项目应该能这样讲：

```text
我做的不是普通 RAG 问答，而是一个面向游戏 Mod 开发的受控 Agentic Code Generation 平台。
它用 LangGraph 管理 workflow state、分支、人类确认和 repair loop；
用 artifact contract 把每一步的输入输出结构化；
用 Evidence RAG 检索源码、API、日志和历史 artifact，确保代码生成前有证据；
用 patch proposal 和 review gate 阻止 scope creep 与无证据修改；
用 dry-run/build/runtime evidence 形成安全闭环；
用 evaluation harness 和 dashboard 让 agent 决策质量可以被观察和回归。
```

这段话中的每个名词都必须能在代码、artifact、测试或 dashboard 中找到对应实现。

---

# 37. Evidence RAG Engineering Design Deep Dive

Detailed Evidence RAG engineering design moved to `EVIDENCE_RAG_MCP_SPEC.md`.

Use the sub-spec for ingestion, source authority, source-type chunking, retrieval, fusion, rerank, citation/source span, multimodal evidence, trace, eval, dashboard subpages, and MCP tool discipline.

# 39. Observability and Visual Management Deep Design

可观测性不是日志堆积，而是让每一次 agent 决策可以被解释、追踪和回归。

核心抽象：

```text
Workflow Trace
Evidence Trace
Proposal Trace
Safety Trace
Build/Runtime Trace
Eval Trace
```

## 39.1 白盒化目标

系统必须回答：

```text
为什么选择这个 execution_path？
为什么认为证据足够或不足？
为什么这个 patch proposal 被允许 dry-run？
为什么 review gate 阻塞？
为什么 build 失败被分类为某类错误？
为什么 repair plan 只改这些文件？
```

## 39.2 Trace 事件模型

统一事件：

```json
{
  "event_id": "evt_...",
  "run_id": "run_...",
  "feature_id": "feature_...",
  "stage": "retrieve_evidence",
  "event_type": "retrieval.fusion_completed",
  "timestamp": "2026-06-23T00:00:00Z",
  "duration_ms": 52,
  "input_refs": [],
  "output_refs": [],
  "metrics": {
    "dense_count": 20,
    "sparse_count": 20,
    "symbol_count": 4,
    "final_count": 8
  },
  "decision": "continue",
  "warnings": [],
  "blockers": []
}
```

## 39.3 Dashboard 页面设计

第一版页面：

| 页面 | 关键组件 | 数据源 |
| --- | --- | --- |
| Overview | run 列表、阶段分布、阻塞统计 | workflow_trace.jsonl |
| Workflow Run Viewer | 节点时间线、条件边、当前状态 | state snapshot + trace |
| Evidence Browser | 多路召回对比、RRF 分数、readiness | evidence_pack |
| Proposal Viewer | 文件变更意图、evidence binding | patch_proposal |
| Review Gate Viewer | findings、decision、required_changes | proposal_review |
| Build/Runtime Viewer | build error class、runtime evidence | build_result/runtime_evidence |
| Evaluation Dashboard | 指标趋势、失败 case、回归 diff | eval_report |
| Artifact Browser | artifact DAG、stale status | artifact store |

## 39.4 配置示例

```yaml
dashboard:
  enabled: true
  framework: streamlit
  host: localhost
  port: 8501
  pages:
    overview: true
    workflow: true
    evidence: true
    proposal: true
    review: true
    build_runtime: true
    evaluation: true
    artifacts: true

trace:
  storage: jsonl
  path: artifacts/runs
  include_payload_excerpt: true
  max_excerpt_chars: 2000
  redact_secrets: true
```

## 39.5 实现类与函数

```text
src/mod_agent/observability/trace.py
  TraceEvent
  TraceWriter.write(event: TraceEvent) -> None
  TraceReader.list_runs() -> list[RunSummary]
  TraceReader.read_run(run_id: str) -> list[TraceEvent]

src/mod_agent/dashboard/app.py
  create_app(settings) -> DashboardApp

src/mod_agent/dashboard/pages/evidence.py
  render_evidence_browser(feature_id: str) -> None

src/mod_agent/dashboard/pages/workflow.py
  render_workflow_run(run_id: str) -> None
```

---

# 40. Architecture and Flow Diagrams

本章补齐可直接放进 README 或面试材料的架构图和流程图。

## 40.1 总体架构图

```text
User / MCP Client / CLI
        |
        v
API / MCP / CLI Adapter
        |
        v
LangGraph Workflow Control Plane
        |
        +--> Planning Layer
        +--> Artifact Store
        +--> Knowledge Base
        +--> Evidence RAG
        +--> Patch Proposal
        +--> Review Gate
        +--> Dry-run Apply
        +--> Build Adapter
        +--> Runtime Evidence
        +--> Repair Loop
        +--> Evaluation Harness
        +--> Observability Dashboard
        |
        v
Structured Artifacts + Trace Events
```

## 40.2 Evidence RAG 流程图

```text
Source Discovery
  -> Loader
  -> Chunker
  -> Transform / Caption / Metadata Enrich
  -> Dense Embedding
  -> Sparse Index
  -> Symbol Index
  -> Vector Store / SQLite / BM25

User Request / Feature Spec
  -> EvidenceQuery
  -> Hybrid Retrieval
  -> Fusion
  -> Rerank
  -> Readiness Gate
  -> Evidence Pack
  -> Implementation Plan / Patch Proposal / Review Gate
```

## 40.3 Controlled Patch 流程图

```text
Feature Spec
  -> Evidence Pack
  -> Implementation Plan
  -> Patch Proposal
  -> Review Gate
      -> blocked
      -> revise_proposal
      -> approve_dry_run
  -> Dry-run Apply
      -> conflict / path violation -> blocked or repair
      -> clean diff -> build
  -> Build
      -> failed -> Repair Plan
      -> success -> Runtime Evidence
```

## 40.4 MCP Client 侧调用模拟

```text
MCP Client
  -> tools/list
  -> tools/call plan_request
  -> tools/call retrieve_evidence
  -> tools/call read_artifact
  -> tools/call review_proposal
  -> tools/call get_workflow_status
```

MCP tool 输出必须包含：

```text
content
structuredContent
artifact_refs
trace_refs
status
blockers
```

---

# 41. Testing Strategy and Quality Gates

测试方案必须像一号文档一样分层写清楚。  
本项目测试重点不是“覆盖率好看”，而是证明 agent 决策链条可靠。

## 41.1 测试分层策略

| 测试层级 | 目标 | 示例 |
| --- | --- | --- |
| Unit Tests | 验证单个组件内部逻辑 | chunker、retriever、permission、schema |
| Contract Tests | 防止模块间接口漂移 | artifact envelope、MCP schema、VectorStore |
| Integration Tests | 验证模块协作 | ingestion pipeline、hybrid retrieval、review gate |
| End-to-End Tests | 验证完整业务路径 | natural request -> proposal -> review -> dry-run |
| Evaluation Tests | 验证 agent 决策质量 | route accuracy、retrieval recall、review correctness |
| Safety Tests | 验证危险动作被拦截 | forbidden paths、confirmed_write blocked |
| Dashboard Smoke | 验证可观测页面能读数据 | run viewer、evidence browser |

## 41.2 单元测试

| 模块 | 测试重点 | 典型测试用例 |
| --- | --- | --- |
| Loader | 解析、metadata、图片引用 | 单文件、多页、无图片、图片占位符 |
| Chunker | 边界、overlap、metadata 传递 | 标题切分、代码块不破坏、symbol-aware |
| Transform | caption、metadata enrich、降级 | mock Vision LLM、caption cache、失败 fallback |
| Embedding | 批处理、缓存、维度 | fake embedding、空文本、超长文本 |
| BM25 | token、IDF、排序 | exact keyword、stopword、无结果 |
| DenseRetriever | filter、top_k、空结果 | fake vector store |
| Fusion | RRF 分数 | 多路结果融合、重复 id、空路 |
| Reranker | 排序、timeout fallback | mock scorer、invalid output |
| Readiness | sufficient/partial/blocked | high-risk no API evidence -> blocked |
| Review Gate | evidence binding、scope | missing evidence_ref -> blocked |
| Permission | side-effect boundary | confirmed_write default blocked |

## 41.3 集成测试

| 场景 | 验证点 | 测试策略 |
| --- | --- | --- |
| Ingestion Pipeline | Loader -> Chunker -> Transform -> Storage | fixture docs + temp db |
| Hybrid Search | symbol + BM25 + dense + fusion | known query/document pairs |
| Evidence Readiness | 检索结果是否能阻断高风险修改 | missing target_source case |
| Proposal Review | proposal 是否绑定证据 | generated fake proposal |
| Dry-run Apply | patch 不真正写 source | temp workspace |
| Build Adapter | build output 被结构化 | fake command runner |
| MCP Server | JSON-RPC schema 和工具输出 | simulated MCP client |

## 41.4 端到端测试

场景 1：Quick patch no-hook

```text
输入：修改配置默认值
期望：
  route = quick_patch
  requires_hook_evidence = false
  proposal only touches config/source constant
  review approves dry_run
```

场景 2：Runtime hook high-risk

```text
输入：修改击杀标记颜色但不影响其他命中反馈
期望：
  route = full_runtime_investigation
  requires_hook_evidence = true
  no target/API evidence -> blocked
```

场景 3：MCP Client 功能测试

```text
启动 MCP server
发送 tools/list
调用 plan_request
调用 retrieve_evidence
读取 evidence_pack artifact
确认 structuredContent 包含 status、artifact_refs、blockers
```

## 41.5 RAG 质量评估测试

黄金集格式：

```json
{
  "case_id": "hook_evidence_kill_marker",
  "query": "Where is kill marker color controlled?",
  "expected_sources": ["target_source", "decompiled_api"],
  "expected_symbols": ["HitFeedback", "CrosshairGuiLayer"],
  "minimum_hit_rate_at_5": 0.8,
  "must_block_if_missing": true
}
```

指标：

```text
Hit Rate@K
MRR
NDCG@K
Evidence source coverage
Evidence readiness accuracy
False-continue rate
False-block rate
```

目标阈值：

```text
Hit Rate@5 >= 0.85 for golden evidence cases
MRR >= 0.70 for symbol-heavy cases
False-continue rate = 0 for high-risk missing-evidence cases
```

## 41.6 性能与压力测试

第一版不是生产服务，但要有基准。

| 类型 | 指标 | 工具 |
| --- | --- | --- |
| Ingestion latency | docs/minute, chunks/sec | pytest-benchmark |
| Retrieval latency | P50/P95/P99 | pytest-benchmark |
| Memory use | peak RSS during ingestion | memory_profiler |
| Vector scale | query latency at 1k/10k/100k chunks | custom benchmark |
| Dashboard load | page render time | Playwright or smoke script |

---

# 42. Detailed Roadmap and Progress Tracking

## 42.1 阶段总览

| Phase | 目的 | 核心产物 |
| --- | --- | --- |
| A | 工程骨架与 LangGraph runtime skeleton | importable package、StateGraph、trace、artifact store |
| B | Artifact contract | envelope、schema、stale detection |
| C | Knowledge ingestion | loaders、chunkers、indexes |
| D | Evidence RAG | hybrid retrieval、readiness、evidence_pack |
| E | Planning layer | request_plan、feature_spec、implementation_plan |
| F | Proposal and review | patch_proposal、proposal_review |
| G | Dry-run and build | dry_run_result、build_result |
| H | Runtime and repair | runtime_evidence、repair_plan |
| I | Memory and compression | context_pack、artifact index |
| J | Evaluation harness | eval cases、metrics、report |
| K | Dashboard and MCP/API | visual pages、safe tools |
| L | Demo and resume packaging | demo scripts、README、talking points |

## 42.2 进度跟踪表

| Phase | Status | Owner | Blocking Risk | Required Tests | Demo Evidence |
| --- | --- | --- | --- | --- | --- |
| A | Not started | coding agent | package layout drift | workflow + artifact tests | graph run trace |
| B | Not started | coding agent | schema churn | contract tests | artifact DAG |
| C | Not started | coding agent | loader complexity | ingestion tests | indexed sample source |
| D | Not started | coding agent | weak recall | retrieval eval | evidence_pack |
| E | Not started | coding agent | vague routing | planning eval | request_plan |
| F | Not started | coding agent | unsafe proposal | review tests | blocked/approved examples |
| G | Not started | coding agent | accidental writes | dry-run safety tests | diff stats |
| H | Not started | coding agent | unverifiable runtime | runtime schema tests | manual evidence |
| I | Not started | coding agent | context bloat | token budget tests | context_pack |
| J | Not started | coding agent | eval too late | eval runner tests | eval_report |
| K | Not started | coding agent | API bypasses graph | MCP contract tests | tools/list output |
| L | Not started | coding agent | resume overclaim | doc review | demo script |

## 42.3 每个任务必须写清楚的字段

后续新增每个小任务时使用此模板：

```text
Task ID:
Goal:
Prerequisites:
Files to modify:
Classes/functions to implement:
Artifacts produced:
Trace events:
Tests:
Acceptance criteria:
Failure behavior:
Next capability step:
```

## 42.4 Phase A 细化示例

```text
Task ID: A1
Goal: Initialize importable package and minimal CLI entry.
Prerequisites: none
Files:
  pyproject.toml
  src/mod_agent/__init__.py
  src/mod_agent/cli.py
  tests/test_smoke_import.py
Classes/functions:
  main(argv: list[str] | None = None) -> int
Artifacts:
  none
Trace:
  none
Tests:
  python -B -m pytest tests/test_smoke_import.py
Acceptance:
  import mod_agent succeeds
  CLI --help exits 0
Next capability step:
  connect downstream business-node behavior after import/CLI smoke
```

```text
Task ID: A4
Goal: Implement artifact store and envelope writer.
Prerequisites: A1
Files:
  src/mod_agent/artifacts/envelope.py
  src/mod_agent/artifacts/store.py
  tests/test_artifact_store.py
Classes/functions:
  ArtifactEnvelope
  ArtifactRef
  ArtifactStore.write(...)
  ArtifactStore.read(...)
Artifacts:
  artifacts/features/<feature_id>/<artifact_type>.json
Trace:
  artifact.write_started
  artifact.write_finished
Tests:
  write/read roundtrip
  path traversal blocked
  invalid artifact type rejected
Acceptance:
  all writes go through ArtifactStore
Next capability step:
  dashboard rendering
```

---

# 43. Extensibility Design Points

## 43.1 新 Domain Adapter

新增 domain adapter 优先实现领域差异，并通过既有 workflow 主干接入。

接口：

```python
class DomainAdapter(Protocol):
    def classify_request(self, request: str) -> DomainRequestHints: ...
    def risk_policy(self) -> RiskPolicy: ...
    def forbidden_paths(self) -> list[str]: ...
    def build_profiles(self) -> list[BuildProfile]: ...
    def evidence_requirements(self, route: str, risk: str) -> EvidenceRequirement: ...
```

扩展示例：

```text
GTFOAdapter
UnityMonoAdapter
BepInExGenericAdapter
MelonLoaderAdapter
```

## 43.2 新 Retrieval Backend

通过 `VectorStore` / `SparseIndex` 抽象替换检索后端，业务层保持在稳定接口上演进。

验收：

```text
same contract tests pass
same evidence_pack schema
same readiness behavior
```

## 43.3 新 Review Rule

Review rule 必须是可组合规则：

```python
class ReviewRule(Protocol):
    rule_id: str
    def evaluate(self, proposal: PatchProposal, context: ReviewContext) -> ReviewFinding | None: ...
```

新增 review rule 时优先沉淀为独立 rule。
需要阻断、修复或升级的事项应出现在 review finding 中。

## 43.4 新 Dashboard 页面

新增页面必须声明：

```text
Question answered:
Artifacts read:
Trace events read:
User action allowed:
User action forbidden:
```

---

# 44. Confidence, Context, and Documentation Honesty

本节专门回应一个现实问题：大文档如何被 agent 稳定使用。

## 44.1 200KB Markdown 是否难以读取

200KB Markdown 对一次性完整推理确实不理想。问题不是“读不了”，而是：

```text
一次性塞入上下文会挤压代码、测试输出和当前任务空间；
长文档容易让 agent 记住目录却漏掉执行细节；
如果没有章节索引和任务模板，后续会话容易只读一部分就开始写。
```

因此，本项目必须采用分层读取策略：

```text
先读 0 / 0A / 当前 phase / 36 / 42；
实现某模块时再读对应设计章；
需要 RAG 时读 37；
需要多模态时读 38；
需要 dashboard 时读 39；
需要测试时读 41。
```

## 44.2 文档可执行深度

以后不按文档长度判断成熟度，而按检查表判断：

```text
是否有设计策略名词？
是否有具体执行步骤？
是否有配置示例？
是否有类和函数？
是否有测试方法？
是否有验收标准？
是否有失败路径？
是否有实现边界和下一步能力？
```

缺少关键项时，将该章标为“需要补齐执行深度”，并列出下一步。

## 44.3 后续文档收口标准

DEV_SPEC 最终收口时要满足：

```text
每个核心模块都有 deep dive；
每个 phase 都有 task-level checklist；
每个 task 都有 files/classes/tests/acceptance；
README 只摘取可展示内容，不复制全部 DEV_SPEC；
SKILL.md 强制 agent 按 phase 读取，而不是全量盲读；
Demo script 只展示已经由 artifact/test/eval 支撑的能力。
```

---

# 45. Adopted RAG Subsystem Specification

Adopted RAG/MCP subsystem specification moved to `EVIDENCE_RAG_MCP_SPEC.md`, including the full imported mature RAG material and the project-specific integration rules.

The active rule in this parent spec is simple: RAG/MCP detail may strengthen the Evidence Knowledge Subsystem, but it cannot override the controlled code-generation workflow, evidence-before-edit policy, artifact contracts, review gates, permission gates, runtime gates, or evaluation gates.

# 48. Module Depth Upgrade Plan

本章把第 37-47 章中已经成型的 RAG 工程写法，抽象成所有核心模块都必须遵守的“章节合同”。

核心结论：

```text
RAG 章节成熟，不是因为它长，而是因为它同时具备：
策略命名、流程拆解、契约结构、失败路径、配置示例、实现落点、观测信号、测试分层、评估指标、阶段排期和迁移规则。
```

因此，后续不是继续堆文字，而是把这套章节合同复制到其它模块：

```text
LangGraph Workflow
Artifact Contract
Planning
Patch Proposal
Review Gate
Dry-run / Build / Runtime / Repair
Memory / Context Compression
Evaluation Harness
Dashboard
MCP / API / CLI
Demo / Resume Packaging
```

## 48.1 Engineering Spec Standards

成熟工程 spec 的结构来自三类方法的叠加：

| 方法 | 给本项目的启发 |
| --- | --- |
| arc42 | 把 goals、constraints、solution strategy、building blocks、runtime view、crosscutting concepts、quality requirements、risks 分开写 |
| C4 | 从 system context、container、component、code 分层，并补 dynamic/deployment 视图 |
| ADR | 对关键技术决策记录 decision、rationale、trade-off、consequence |

落到本项目，每个核心模块都要回答：

```text
为什么存在？
输入输出是什么？
使用什么命名策略？
主流程、失败流程、阻塞流程是什么？
关键 artifact/schema/config 长什么样？
代码落在哪些目录、类、函数？
如何 trace、metric、log、dashboard 展示？
如何测试和评估？
做到什么才算完成？
哪些事情明确不做？
为什么这样取舍？
```

## 48.2 Universal Module Chapter Contract

所有非 RAG 核心模块后续都应按这个固定结构重写：

```markdown
## <Module Name> Design

### Goals and Non-goals
### Strategy Names and Design Highlights
### Inputs / Outputs / Artifacts
### State Machine / Flow / Conditional Edges
### Data Structures / Schema / Configuration Example
### Implementation Classes / Core Functions / Directory Mapping
### Failure Paths / Fallback / Idempotency / Retry Budget
### Observability / Trace / Metrics / Dashboard Mapping
### Testing Strategy
### Acceptance Criteria
### Implementation Boundaries
### Phase Breakdown and Progress Tracking
### ADR / Trade-off Notes
```

这不是形式主义。每一节都必须写成具体工程对象，而不是散文。

反例：

```text
“有一个 reviewer 检查 proposal。”
```

合格写法：

```text
ProposalReviewer.evaluate(proposal, context) -> ReviewResult
ScopeRule.evaluate(change, feature_spec) -> Finding | None
EvidenceBindingRule.evaluate(change, evidence_pack) -> Finding | None
```

反例：

```text
“失败后进入修复。”
```

合格写法：

```text
schema_invalid -> blocked_schema_error
stale_input -> mark_stale_and_stop
build_timeout -> build_failed_timeout -> repair_plan
human_denied -> blocked_human_denied
retry_budget_exhausted -> blocked_retry_exhausted
```

## 48.3 Chapter Definition of Done

每章必须通过以下验收门，才算达到与 RAG 同级的工程深度：

| 验收项 | 通过标准 |
| --- | --- |
| 目标清晰 | 说明为什么存在、解决什么问题、非目标是什么 |
| I/O 清晰 | 明确输入 artifact、输出 artifact、调用方、被调用方 |
| 策略命名 | 至少有 2-4 个命名过的设计策略，而非只有散文描述 |
| 流程闭环 | 主路径、失败路径、block 路径、回退路径都写清楚 |
| 契约存在 | 有 schema、state delta、config 示例或 trace 字段 |
| 代码落点 | 有目录、类、函数、接口、扩展点 |
| 测试分层 | 不只列用例名，还写验证目标、fixture、依赖 |
| 观测可见 | 指明 traces、metrics、logs、dashboard 页面 |
| phase 可执行 | 有任务拆分、依赖、验收、下一步能力 |
| honesty | 明确 stub 部分、能力等级、升级路径 |

缺少关键项时，该章标为“需要补齐 RAG 级深度”，并列出下一步。

## 48.4 Rewrite Priority

不要平均用力。按对系统骨架的影响排序：

第一批，定义控制平面：

```text
1. LangGraph Workflow
2. Artifact Contract
3. Planning
4. Patch Proposal
5. Review Gate
```

第二批，定义执行闭环：

```text
6. Dry-run Apply
7. Build Adapter
8. Runtime Evidence
9. Repair Loop
10. Memory / Context Compression
```

第三批，定义展示和外部接口：

```text
11. Evaluation Harness
12. Dashboard
13. MCP / API / CLI
14. Demo / Resume Packaging
15. ADR / Glossary
```

原因：

```text
Workflow + Artifact + Planning + Proposal + Review 定义系统语义。
Dry-run + Build + Runtime + Repair 执行这些语义。
Dashboard + MCP/API/CLI 展示和暴露这些语义。
```

## 48.5 LangGraph Workflow Upgrade Requirements

Workflow 是二号项目的控制平面，必须达到 RAG retrieval pipeline 同级深度。

需要补强的策略名词：

```text
Thread-scoped Checkpointing
Interrupt Gate
Idempotent Pre-interrupt Effects
Resume Command Contract
Conditional Edge Matrix
State Ownership Contract
Time-travel Read-only Replay
Repair Re-entry Policy
```

必须补充：

| 补强项 | 内容 |
| --- | --- |
| State ownership | 哪个 node 允许写哪些 state 字段，哪些字段只读 |
| Conditional edge matrix | `from_stage x condition -> to_stage` 表 |
| Interrupt policy | 哪些 stage 可中断，payload 是什么，谁恢复 |
| Checkpoint semantics | checkpoint 频率、resume 粒度、error state 是否持久化 |
| Side-effect idempotency | interrupt 前的 side effect 必须可重复或可去重 |
| Trace contract | 每个 node 最少写哪些 trace attributes |
| Graph tests | normal、blocked、interrupt/resume、stale resume、double resume、repair re-entry |

示例条件边矩阵：

| From | Condition | To |
| --- | --- | --- |
| `plan_request` | `request.is_ambiguous` | `blocked` |
| `retrieve_evidence` | `readiness=insufficient` | `blocked` |
| `review_proposal` | `decision=revise` | `generate_patch_proposal` |
| `review_proposal` | `decision=approve_dry_run` | `dry_run_apply` |
| `build` | `status=failed` | `create_repair_plan` |
| `runtime_evidence` | `acceptance_unverified` | `create_repair_plan` |

## 48.6 Artifact Contract Upgrade Requirements

Artifact 不是“存 JSON”，而是系统主状态的可审计投影。

需要补强的策略名词：

```text
Artifact Dependency Graph
Freshness View
Schema Evolution Policy
Producer-Consumer Registry
Stale Propagation Rules
Artifact Projection for Dashboard
```

每种 artifact 都必须声明：

```text
artifact_type
producer_stage
consumer_stages
required_upstream_artifacts
required_upstream_hashes
allowed_statuses
stale_propagation_rules
dashboard_projection
eval_visibility
schema_version
migration_policy
```

示例：

```json
{
  "artifact_type": "implementation_plan",
  "producer_stage": "create_implementation_plan",
  "consumer_stages": ["generate_patch_proposal", "review_proposal"],
  "required_upstream_artifacts": ["feature_spec", "evidence_pack"],
  "allowed_statuses": ["success", "blocked", "failed", "stubbed"],
  "stale_if": ["feature_spec.hash_changed", "evidence_pack.hash_changed"],
  "dashboard_projection": ["summary", "target_files", "evidence_refs", "open_questions"],
  "eval_visibility": true
}
```

## 48.7 Planning / Proposal / Review Upgrade Requirements

这三章必须写成一条完整变更控制链：

```text
request_plan
-> feature_spec
-> implementation_plan
-> patch_proposal
-> proposal_review
-> dry_run_result
```

### Planning Strategies

需要补强的策略名词：

```text
Route Taxonomy
Blocking Uncertainty
Acceptance Contract
Strategy Selection Matrix
Risk-tiered Evidence Requirement
Human Clarification Boundary
```

Planning 不只分类，还要把模糊问题结构化：

```json
{
  "uncertainty_id": "unclear_target_mod",
  "severity": "blocking",
  "question": "Which existing mod should be modified?",
  "allowed_resolution": ["human_answer", "artifact_context"],
  "default_action": "block"
}
```

### Patch Proposal Strategies

需要补强的策略名词：

```text
Change Unit Model
Scope Boundary Contract
Evidence-backed Diff Intent
No-op Classification
Rollback Hint Requirement
```

每个 change unit 必须包含：

```json
{
  "change_id": "chg_001",
  "change_type": "modify_config_default",
  "target_file": "generated_mods/BetterHitFeedback/Plugin.cs",
  "target_symbol": "EnableDiagnosticLogging",
  "operation": "change_default_value",
  "rationale": "User requested diagnostic logging default false.",
  "evidence_refs": ["ev_001"],
  "risk_tags": ["config_only"],
  "expected_validation": ["compile", "config default assertion"],
  "rollback_hint": "Restore previous default value."
}
```

### Review Gate Strategies

Review Gate 必须升级为规则引擎式 spec。

需要补强的策略名词：

```text
Rule Registry
Structured Finding
Evidence Binding Rule
Scope Minimality Rule
Semantic Target Alignment Rule
Permission Boundary Rule
Composite Review Decision
```

规则模板：

```json
{
  "rule_id": "scope_minimality",
  "input": {
    "proposal_ref": "patch_proposal.json",
    "feature_spec_ref": "feature_spec.json",
    "evidence_pack_ref": "evidence_pack.json"
  },
  "logic": "Every change must map to declared target_behavior or validation support.",
  "finding_levels": ["info", "warning", "blocking"],
  "blocking_condition": "any unrelated file or symbol change appears",
  "trace_metrics": {
    "num_changes_checked": 0,
    "num_unbound_changes": 0
  },
  "tests": [
    "test_blocks_unbound_change",
    "test_warns_on_non_minimal_refactor",
    "test_passes_runtime_validation_helper_change"
  ]
}
```

## 48.8 Execution Validation Loop Upgrade Requirements

Dry-run、Build、Runtime、Repair 不应分散写成后处理，而应写成闭环：

```text
Virtual Apply
-> Structured Build
-> Verification Ladder
-> Repair Budget
```

### Dry-run Strategies

```text
Virtual Patch Application
Path Guard
Diff Stats Contract
Write Isolation
Dry-run Result Hash
```

### Build Strategies

```text
Build Profile Registry
Structured Build Result
Error Taxonomy
Diagnostic Extraction
Repair Handoff Contract
```

Build error taxonomy：

```text
compile_error
missing_reference
api_mismatch
package_restore_failure
timeout
permission_denied
unknown
```

### Runtime Strategies

```text
Verification Ladder
Runtime Evidence Pack
Manual Evidence Contract
Log-Screenshot Correlation
Non-goal Preservation Check
```

Verification ladder：

| Level | Meaning |
| --- | --- |
| `startup_loaded` | plugin/mod loaded without startup error |
| `target_path_executed` | expected hook/path/log executed |
| `acceptance_evidence_observed` | target behavior evidence observed |
| `non_goals_preserved` | declared non-goals were not affected |

### Repair Strategies

```text
Failure Evidence Pack
Root-cause Hypothesis Registry
Minimal Fix Plan
Retry Budget Policy
Stop Condition Contract
```

Repair plan 必须说明：

```text
failure_source
failure_class
evidence_refs
hypothesis
minimal_changes
retry_budget_remaining
stop_condition
scope_expansion_allowed=false by default
```

## 48.9 Dashboard / MCP / API Upgrade Requirements

Dashboard、MCP、API 不是入口装饰，而是系统数据面的投影和安全暴露层。

每个 Dashboard 页面必须声明：

```text
Question answered
Artifacts read
Trace events read
Metrics displayed
Allowed user actions
Forbidden user actions
```

每个 MCP/API tool 必须声明：

```text
tool_name
input_schema
output_schema
structuredContent
artifact_refs
trace_refs
permission_level
human_confirmation_required
error_schema
contract_tests
```

第一版默认：

```text
read-only and report-only tools allowed
confirmed write tools hidden or disabled
external side-effect tools disabled
```

## 48.10 Observability as a Required Block

Observability 不是单独章节，而是每章必填块。

采用三信号模型：

| Signal | 用途 |
| --- | --- |
| Trace | 表示一次请求穿过系统的路径、因果链、阶段耗时 |
| Metric | 聚合运行测量，用于趋势、SLO、回归 |
| Structured Log | 事件记录，带稳定 schema，可与 trace/metric 关联 |

每章必须补四类观测信息：

```text
Golden path metrics:
  node latency, retrieval latency, review pass rate, build success rate, runtime verification completion rate

Anti-pattern metrics:
  stale artifact reuse, unbound change count, false-continue count, retry exhaustion count

Trace fields:
  run_id, feature_id, stage, decision, artifact_refs, blockers

Dashboard mapping:
  Evidence Browser, Proposal Viewer, Review Gate Viewer, Build/Runtime Viewer, Eval Dashboard
```

## 48.11 Testing Must Have Two Axes

测试除 unit/integration/E2E 外，还应增加两条轴：

```text
Software engineering test axis:
  code correctness, schema compatibility, API contract, side-effect safety

Agent quality evaluation axis:
  decision quality, route accuracy, evidence sufficiency, review correctness, repair quality
```

第一条轴：

```text
unit tests
contract tests
integration tests
E2E tests
safety tests
dashboard smoke tests
```

第二条轴：

```text
route accuracy
risk accuracy
context precision
context recall
evidence readiness accuracy
false-continue rate
false-block rate
review block correctness
dry-run safety
repair plan correctness
golden path success rate
```

特别要求：contract tests 必须单独列出，因为以下对象都是系统边界：

```text
artifact schema
MCP input/output schema
review result schema
build result schema
runtime evidence schema
repair plan schema
trace event schema
```

## 48.12 ADR and Glossary Requirements

RAG 章节之所以成熟，是因为已经出现了“为什么这样选”的解释。其它章节也必须把关键取舍沉淀成 ADR。

ADR 模板：

```markdown
## ADR-<number>: <Decision Title>

### Context
### Decision
### Alternatives Considered
### Rationale
### Consequences
### Revisit Trigger
```

首批应补 ADR：

```text
ADR: Review before apply
ADR: Dry-run before confirmed write
ADR: MCP tools default read-only
ADR: Deterministic retrieval before vector retrieval
ADR: Artifact store as source of workflow truth
ADR: Runtime success requires evidence, not build success
ADR: Dashboard reads artifacts/traces, not hidden state
```

Glossary 必须统一：

```text
feature
artifact
evidence
evidence_pack
proposal
review
finding
dry_run
runtime_evidence
repair_plan
context_pack
domain_adapter
execution_path
risk_level
readiness
checkpoint
interrupt
resume
stale
confirmed_write
```

## 48.13 Target End State

当其它模块都按本章升级后，整份 DEV_SPEC 应该达到：

```text
不是“RAG 很成熟，其它章节像 TODO”。
而是每个核心章节都能独立回答：
为什么存在？
输入输出是什么？
用什么策略？
为什么这样选？
关键数据长什么样？
失败时怎么退？
如何观测？
如何测试？
如何验收？
当前 phase 到哪里为止？
```

这才是“与 RAG 同级的工程深度”。

---

# 49. Non-RAG Module Deepening Pass

本章不是方法论，而是对非 RAG 核心模块的实际补强。  
第 37-47 章已经把 RAG / Knowledge Hub 补到成熟工程规格；本章把同样粒度落到控制平面、变更控制、执行验证、接口和展示层。

优先级规则：

```text
第 49 章是第 5-20 章中非 RAG 模块的补充细化。
如果早期章节只给出概念，而本章给出 schema / rule / class / flow，则以后实现时以本章为准。
如果本章与第 46 章 imported RAG 冲突，RAG 相关实现看第 46/47，非 RAG 控制流看第 49。
```

---

## 49.1 LangGraph Workflow Control Plane

### 49.1.1 Goals and Non-goals

目标：

```text
把自然语言请求推进为一组可恢复、可审计、可中断、可评估的 workflow stage。
```

非目标：

```text
Workflow 不负责具体 RAG 检索算法。
Workflow 不负责直接生成 patch diff。
Workflow 不绕过 artifact store 保存隐藏状态。
Workflow 不在没有 permission decision 的情况下执行副作用。
```

### 49.1.2 Strategy Names and Design Highlights

| 策略 | 含义 |
| --- | --- |
| Thread-scoped Checkpointing | 每个 run/thread 独立持久化 graph state，支持 resume |
| Interrupt Gate | 高风险节点通过人类确认中断，不在节点内部静默继续 |
| Idempotent Pre-interrupt Effects | interrupt 前已执行的写 artifact / trace 操作必须可重复或可去重 |
| Resume Command Contract | resume 必须携带 approval / correction / rejection 的结构化 payload |
| Conditional Edge Matrix | 用表格定义条件边，不把路由逻辑散落在节点里 |
| State Ownership Contract | 每个节点只允许写自己的 state 字段集合 |
| Repair Re-entry Policy | repair loop 回到指定节点并记录跳转依据 |

### 49.1.3 State Ownership Contract

`ModAgentState` 字段所有权：

| Field | Writer | Readers | Notes |
| --- | --- | --- | --- |
| `run_id` | state initializer | all nodes | immutable |
| `request_id` | state initializer | all nodes | immutable |
| `feature_id` | `plan_request` | all downstream | only set once |
| `user_request` | state initializer / human correction | planning | correction requires trace |
| `execution_path` | `plan_request` | all downstream | stale if feature_spec changes |
| `risk_level` | `plan_request` / domain adapter | review, permission | high risk requires evidence |
| `current_stage` | every node | dashboard | append-only trace mirrors it |
| `artifacts` | artifact-producing nodes | all downstream | values are artifact refs |
| `approvals` | interrupt/resume handler | review/apply/runtime | must include approver + diff hash when relevant |
| `blockers` | any blocking node | dashboard/eval | structured blocker objects |
| `metrics` | nodes and eval | dashboard | never source of truth |

Rule:

```text
节点修改 state 字段时记录 owner、correction artifact 和 trace event。
如果必须修正上游字段，必须通过 explicit correction artifact + trace event。
```

### 49.1.4 Conditional Edge Matrix

| From Stage | Condition | To Stage |
| --- | --- | --- |
| `start` | always | `plan_request` |
| `plan_request` | `blocked=true` | `blocked` |
| `plan_request` | `route=quick_patch` | `draft_feature_spec` |
| `plan_request` | `route=full_runtime_investigation` | `draft_feature_spec` |
| `draft_feature_spec` | `acceptance_missing=true` | `blocked` |
| `retrieve_evidence` | `readiness=insufficient` | `blocked` |
| `retrieve_evidence` | `readiness=partial and risk=low` | `create_implementation_plan` |
| `retrieve_evidence` | `readiness=sufficient` | `create_implementation_plan` |
| `create_implementation_plan` | `open_questions.blocking=true` | `blocked` |
| `generate_patch_proposal` | `proposal.status=already_satisfied` | `done` |
| `review_proposal` | `decision=blocked` | `blocked` |
| `review_proposal` | `decision=revise_proposal` | `generate_patch_proposal` |
| `review_proposal` | `decision=requires_human` | `human_approval` |
| `review_proposal` | `decision=approve_dry_run` | `dry_run_apply` |
| `dry_run_apply` | `path_guard=failed` | `blocked` |
| `dry_run_apply` | `conflict=true` | `create_repair_plan` |
| `dry_run_apply` | `clean=true` | `build` |
| `build` | `status=failed` | `create_repair_plan` |
| `build` | `status=success and runtime_required=true` | `collect_runtime_evidence` |
| `build` | `status=success and runtime_required=false` | `evaluate` |
| `collect_runtime_evidence` | `acceptance_verified=false` | `create_repair_plan` |
| `collect_runtime_evidence` | `acceptance_verified=true` | `evaluate` |
| `create_repair_plan` | `retry_budget_remaining>0` | `generate_patch_proposal` |
| `create_repair_plan` | `retry_budget_remaining=0` | `blocked` |
| `evaluate` | always | `done` |

`human_approval` rows are implemented as LangGraph interrupt/resume boundaries,
not as ordinary nodes that can silently continue or block.

### 49.1.5 Interrupt Policy

| Stage | Interrupt Reason | Payload | Resume Allowed Fields |
| --- | --- | --- | --- |
| `plan_request` | ambiguous target / missing mod | clarification request | `user_request`, `target_mod` |
| `review_proposal` | high-risk change / write approval | proposal summary + evidence refs | `approvals.review` |
| `dry_run_apply` | path risk | diff hash + path list | `approvals.dry_run` |
| `confirmed_apply` | real write | diff hash + rollback hint | `approvals.confirmed_write` |
| `collect_runtime_evidence` | manual verification | checklist + evidence upload fields | `runtime_evidence.manual` |

Resume payload schema:

```json
{
  "resume_id": "resume_...",
  "run_id": "run_...",
  "stage": "review_proposal",
  "decision": "approve",
  "approved_by": "human",
  "approved_at": "2026-06-23T00:00:00Z",
  "artifact_refs": ["artifacts/features/.../patch_proposal.json"],
  "diff_hash": "sha256...",
  "notes": ""
}
```

### 49.1.6 Trace and Metrics

Required trace events:

```text
workflow.node_started
workflow.node_finished
workflow.node_blocked
workflow.edge_selected
workflow.interrupt_requested
workflow.resume_received
workflow.repair_reentry
workflow.done
```

Metrics:

```text
node_duration_ms
edge_selection_count
blocked_count_by_stage
interrupt_count_by_stage
resume_success_count
repair_reentry_count
stale_resume_count
```

### 49.1.7 Implementation Classes

```text
src/mod_agent/workflow/state.py
  ModAgentState
  StateOwnershipPolicy

src/mod_agent/workflow/graph.py
  build_graph(settings, artifact_store, trace_writer) -> CompiledGraph

src/mod_agent/workflow/transitions.py
  route_label_for_stage(stage: str, state: ModAgentState) -> str
  route_registry() -> Mapping[str, Mapping[str, str]]
  validate_transition(from_stage, to_stage, state) -> None

src/mod_agent/workflow/interrupts.py
  InterruptRequest
  ResumePayload
  ResumeValidator.validate(payload, state) -> ResumeDecision

src/mod_agent/workflow/checkpointing.py
  CheckpointPolicy
  WorkflowCheckpointStore
```

### 49.1.8 Tests

| Test | Goal |
| --- | --- |
| `test_normal_path_reaches_done` | normal graph path works |
| `test_ambiguous_request_blocks` | blocking condition routes to blocked |
| `test_evidence_insufficient_blocks` | readiness controls transition |
| `test_review_revise_loops_to_proposal` | revise path works |
| `test_interrupt_resume_approval` | interrupt can resume with valid payload |
| `test_double_resume_rejected` | idempotent resume |
| `test_stale_resume_rejected` | diff/artifact hash mismatch blocks |
| `test_repair_budget_exhaustion_blocks` | loop is bounded |

Acceptance:

```text
All routing decisions execute through LangGraph conditional_edges.
The route matrix/registry may generate those conditional_edges and audit output.
Every node writes trace.
Every artifact-producing node writes through ArtifactStore.
Interrupt/resume paths are covered by tests.
No node performs confirmed writes.
```

---

## 49.2 Artifact Contract as System State

### 49.2.1 Goals and Non-goals

目标：

```text
把 workflow 每一步的输出变成可审计、可版本化、可 freshness 检查的结构化 artifact。
```

非目标：

```text
Artifact Store 不是通用数据库。
Artifact Store 不负责执行 stage 逻辑。
Artifact Store 不保存 secret。
Artifact Store validates path traversal and records violations as structured findings.
```

### 49.2.2 Strategy Names

| 策略 | 含义 |
| --- | --- |
| Artifact Dependency Graph | 记录 artifact 之间的上游/下游关系 |
| Freshness View | 根据 upstream hash 判断 artifact 是否 stale |
| Schema Evolution Policy | artifact schema 版本化和迁移规则 |
| Producer-Consumer Registry | 每种 artifact 的生产者和消费者固定注册 |
| Immutable Artifact Revision | 默认写新 revision，不静默覆盖历史 |
| Dashboard Projection | 每种 artifact 声明 dashboard 展示字段 |

### 49.2.3 Artifact Registry

```json
{
  "artifact_type": "patch_proposal",
  "schema_version": "1.0",
  "producer_stage": "generate_patch_proposal",
  "consumer_stages": ["review_proposal", "dry_run_apply"],
  "required_upstream_artifacts": ["feature_spec", "evidence_pack", "implementation_plan"],
  "allowed_statuses": ["success", "blocked", "failed", "stubbed", "already_satisfied"],
  "stale_if": [
    "feature_spec.hash_changed",
    "evidence_pack.hash_changed",
    "implementation_plan.hash_changed"
  ],
  "dashboard_projection": ["summary", "change_count", "target_files", "risk_tags"],
  "eval_visibility": true
}
```

### 49.2.4 Freshness Algorithm

```text
On write:
  compute artifact_hash
  store upstream artifact refs + hashes

On read_for_stage:
  load artifact envelope
  recompute upstream hashes
  if mismatch:
    return FreshnessView(status="stale", stale_reasons=[...])
  else:
    return FreshnessView(status="fresh")
```

Stale behavior:

| Consumer | Stale Input Behavior |
| --- | --- |
| `generate_patch_proposal` | block and require plan regeneration |
| `review_proposal` | block review |
| `dry_run_apply` | block dry-run |
| `build` | block build if proposal/dry_run stale |
| `dashboard` | display stale warning |
| `eval` | mark case invalid unless explicitly evaluating stale behavior |

### 49.2.5 Implementation Classes

```text
src/mod_agent/artifacts/registry.py
  ArtifactTypeRegistry
  ArtifactContract

src/mod_agent/artifacts/envelope.py
  ArtifactEnvelope
  ArtifactRef
  ArtifactHash

src/mod_agent/artifacts/store.py
  ArtifactStore.write(...)
  ArtifactStore.read(...)
  ArtifactStore.read_for_stage(...)

src/mod_agent/artifacts/freshness.py
  FreshnessChecker.check(ref) -> FreshnessView

src/mod_agent/artifacts/migrations.py
  ArtifactMigration
  MigrationRegistry
```

### 49.2.6 Tests

```text
test_write_wraps_envelope
test_path_traversal_rejected
test_upstream_hash_recorded
test_stale_detected_after_upstream_change
test_consumer_blocks_stale_artifact
test_schema_version_rejected_if_unknown
test_dashboard_projection_present
```

Acceptance:

```text
No stage reads raw JSON directly.
Every artifact type is registered.
Stale detection works across at least feature_spec -> implementation_plan -> patch_proposal.
Schema version is explicit.
```

### 49.2.7 Physical Locator And Atomic Commit Reliability

The committed revision identity remains the complete `artifact_hash` stored in
the envelope, `ArtifactRef`, and upstream binding. Physical storage uses a
short deterministic locator only to keep the local write path addressable:

```text
features/<feature_id>/<artifact_type>.json
  -> mutable latest envelope projection

features/<feature_id>/r/<artifact_type>/<artifact_hash first 32 hex>.json
  -> immutable committed revision locator

features/<feature_id>/p/<artifact_type>/<artifact_hash first 32 hex>.json
  -> internal pending-write marker
```

The 32-hex locator is not revision identity. An existing short-locator file is
read and checked against the complete hash, feature id, artifact type, schema,
and envelope content before it can be reused. A different complete hash at the
same locator is a deterministic collision and blocks overwrite.

Write-time idempotence checks the exact legacy full-hash revision location
before the short-locator location. A valid legacy revision is reused without
copy, migration, or a second revision file. Explicit `ArtifactRef` reads use
the persisted path and validate that referenced revision only; they do not scan
other revisions or rewrite old paths. Legacy pending markers are not recovered
or migrated by this compatibility boundary.

The commit order remains:

```text
pending marker
-> immutable revision
-> latest envelope projection
-> pending marker cleanup
```

Each file is written through a short same-directory temporary file, followed
by flush, `fsync`, and `os.replace`. Parent directories are created before the
replace operation. Pending data records the complete artifact hash and the
actual intended revision and latest locations; identity is never inferred from
the abbreviated filename.

Before `intelligent-evidence-request` constructs or invokes the graph, model,
or evidence tools, `ArtifactStore` probes the actual pending, revision, and
latest write locations for `evidence_run_attempt`, `request_planning_report`,
`mod_planning_brief`, `feature_spec`, and `evidence_pack`. The probe uses the
production locator and atomic-write implementation, removes its reserved probe
files after success, and creates no business revision, latest projection,
`ArtifactRef`, or upstream binding.

A recognized unaddressable-path replace failure returns the existing CLI
top-level `BLOCKED` result with exit code 2 and a machine-readable diagnostic:

```text
category = infrastructure_preflight_failure
component = artifact_store
stage = artifact_preflight
code = artifact_path_unaddressable
operation = os.replace
model_execution_started = false
tool_execution_started = false
model_call_count = 0
tool_call_count = 0
details include artifact_type, path_role, path lengths, parent existence,
and the operating-system error number without absolute local paths
```

Unknown `OSError` values are not relabeled as this path failure. The historical
blocked run's observed process exit code remains 1; current source and focused
tests prove exit code 2 for the new recognized preflight branch but do not
explain or rewrite that historical discrepancy.

The verified reliability claim is limited to the current Windows process,
local NTFS artifact root, and single-process evidence-only write chain. It does
not establish arbitrary path-length support, a Windows-specific path layer,
cross-process locking, fallback storage, dual writes, migration, retention,
garbage collection, or crash recovery beyond the normal pending commit flow.

### 49.2.8 Durable Evidence Attempt Identity And Provider Diagnostics

`intelligent-evidence-request` writes an `evidence_run_attempt` revision with
status `running`, `run_validity=attempt_started`, and
`terminal_stage=before_graph` before `graph.invoke` can make the first model
call. A terminal `success` or `failed` revision uses the same `run_id`; an
external call that later fails validation therefore remains bound to a durable
attempt identity even when no EvidencePack is produced.

The terminal revision records model and external-model call counts, accepted
model actions, executed evidence tools, failure attribution, and one sanitized
provider-turn envelope per provider response. Each tool-call diagnostic keeps
`provider_reported_tool_name` and `adapter_extracted_tool_name` as distinct
values and also records `normalized_tool_name`, `normalization_applied`, JSON
validity, argument SHA256, provider request and tool-call ids, finish reason,
API type, streaming state, and reported usage. It does not persist API keys,
complete prompts, source roots, or raw tool arguments.

The production Qwen Evidence request explicitly uses `stream=false`. Unknown
tool names fail before evidence-tool execution and do not trigger an automatic
provider retry. `accepted_model_actions` counts accepted model tool actions and
an accepted model finish; a deterministic control-plane finish is not counted.
These fields provide run diagnosis and attribution evidence. They do not prove
semantic correctness or authorize later workflow stages.

---

## 49.3 Change Control Chain

This section deepens Planning, Patch Proposal, and Review Gate as one continuous control chain.

### 49.3.1 Request Planning

Strategies:

```text
Route Taxonomy
Blocking Uncertainty
Acceptance Contract
Strategy Selection Matrix
Risk-tiered Evidence Requirement
```

Route taxonomy:

| Route | Description | Evidence Requirement | Runtime Requirement |
| --- | --- | --- | --- |
| `quick_patch` | config/text/default value change | target source or artifact | no |
| `standard_feature` | bounded feature with known target | target source + domain note | maybe |
| `game_hook_investigation` | hook selection needed | target source + API evidence | yes |
| `full_runtime_investigation` | behavior safety depends on runtime | target source + API + runtime plan | yes |
| `repair_loop` | fix failed build/runtime | failure evidence pack | maybe |
| `blocked_ambiguous` | missing critical info | clarification | no |

Blocking uncertainty schema:

```json
{
  "uncertainty_id": "missing_target_mod",
  "severity": "blocking",
  "question": "Which mod should be modified?",
  "why_blocking": "Changing the wrong mod is a high-risk scope error.",
  "resolution_sources": ["human_answer", "existing_artifact"],
  "default_action": "block"
}
```

Implementation:

```text
src/mod_agent/planning/router.py
  RequestRouter.route(user_request, context) -> RequestPlan

src/mod_agent/planning/uncertainty.py
  UncertaintyClassifier.classify(request, route) -> list[Uncertainty]

src/mod_agent/planning/acceptance.py
  AcceptanceContractBuilder.build(request_plan) -> AcceptanceContract
```

### 49.3.2 Feature Spec and Implementation Plan

Feature spec must include:

```text
target_behavior
non_goals
acceptance_criteria
evidence_requirements
risk_level
runtime_verification_required
blocking_uncertainties
```

Implementation plan must include:

```text
target_files
target_symbols
change_intents
evidence_refs
side_effect_boundaries
validation_plan
rollback_plan
open_questions
```

Implementation plan cannot proceed if:

```text
blocking uncertainties exist
evidence readiness insufficient
target files are outside domain adapter allowed roots
risk level requires runtime plan but none exists
```

### 49.3.3 Patch Proposal

Strategies:

```text
Change Unit Model
Scope Boundary Contract
Evidence-backed Diff Intent
No-op Classification
Rollback Hint Requirement
```

Patch proposal schema:

```json
{
  "proposal_id": "prop_...",
  "feature_id": "feature_...",
  "status": "success",
  "summary": "Change diagnostic logging default to false.",
  "change_units": [
    {
      "change_id": "chg_001",
      "change_type": "modify_config_default",
      "target_file": "generated_mods/BetterHitFeedback/Plugin.cs",
      "target_symbol": "EnableDiagnosticLogging",
      "operation": "change_default_value",
      "rationale": "Requested default behavior.",
      "evidence_refs": ["ev_001"],
      "risk_tags": ["config_only"],
      "expected_validation": ["compile", "unit_config_default"],
      "rollback_hint": "Restore default true."
    }
  ],
  "scope_boundary": {
    "allowed_files": ["generated_mods/BetterHitFeedback/Plugin.cs"],
    "forbidden_files": [],
    "no_unrelated_refactor": true
  }
}
```

Implementation:

```text
src/mod_agent/proposal/context_builder.py
  ProposalContextBuilder.build(feature_spec, evidence_pack, implementation_plan) -> ProposalContext

src/mod_agent/proposal/generator.py
  PatchProposalGenerator.generate(context) -> PatchProposal

src/mod_agent/proposal/noop.py
  NoOpClassifier.classify(context) -> NoOpDecision
```

### 49.3.4 Review Gate

Strategies:

```text
Rule Registry
Structured Finding
Composite Review Decision
Evidence Binding Rule
Scope Minimality Rule
Semantic Target Alignment Rule
Permission Boundary Rule
```

Review finding schema:

```json
{
  "finding_id": "find_001",
  "rule_id": "evidence_binding",
  "level": "blocking",
  "message": "Change chg_002 has no evidence_refs.",
  "change_id": "chg_002",
  "artifact_refs": ["patch_proposal.json", "evidence_pack.json"],
  "recommended_action": "revise_proposal"
}
```

Composite decision:

```text
any blocking finding -> blocked or revise_proposal
warnings only -> approve_dry_run with warnings
no findings -> approve_dry_run
high risk + write requested -> requires_human
already satisfied -> already_satisfied
```

Implementation:

```text
src/mod_agent/review/rules/base.py
  ReviewRule.evaluate(context) -> ReviewFinding | None

src/mod_agent/review/rules/evidence_binding.py
src/mod_agent/review/rules/scope_minimality.py
src/mod_agent/review/rules/semantic_target_alignment.py
src/mod_agent/review/rules/permission_boundary.py

src/mod_agent/review/reviewer.py
  ProposalReviewer.evaluate(proposal, context) -> ReviewResult
```

Tests:

```text
test_blocks_unbound_change
test_blocks_forbidden_path
test_warns_non_minimal_refactor
test_passes_config_quick_patch
test_requires_human_for_high_risk_write
test_already_satisfied_decision
```

---

## 49.4 Execution Validation Loop

Execution validation is a closed loop:

```text
Dry-run Apply
-> Build Adapter
-> Runtime Evidence
-> Repair Loop
```

### 49.4.1 Dry-run Apply

Strategies:

```text
Virtual Patch Application
Path Guard
Diff Stats Contract
Write Isolation
Dry-run Hash
```

Dry-run result schema:

```json
{
  "status": "success",
  "proposal_id": "prop_...",
  "would_write": true,
  "actual_write_performed": false,
  "changed_files": ["generated_mods/BetterHitFeedback/Plugin.cs"],
  "diff_stats": {
    "files": 1,
    "insertions": 1,
    "deletions": 1
  },
  "path_guard": {
    "status": "passed",
    "checked_paths": []
  },
  "diff_hash": "sha256...",
  "blockers": []
}
```

### 49.4.2 Build Adapter

Strategies:

```text
Build Profile Registry
Structured Build Result
Error Taxonomy
Diagnostic Extraction
Repair Handoff Contract
```

Build profile:

```json
{
  "profile_id": "gtfo_bepinex_il2cpp",
  "working_directory": "generated_mods/BetterHitFeedback",
  "command": ["dotnet", "build"],
  "timeout_seconds": 120,
  "expected_artifacts": ["bin/Debug/BetterHitFeedback.dll"]
}
```

Build result:

```json
{
  "status": "failed",
  "exit_code": 1,
  "error_class": "api_mismatch",
  "diagnostics": [
    {
      "file": "Plugin.cs",
      "line": 42,
      "message": "Type not found",
      "code": "CS0246"
    }
  ],
  "repair_handoff": {
    "allowed": true,
    "failure_evidence_refs": ["build_log_chunk_001"]
  }
}
```

### 49.4.3 Runtime Evidence

Strategies:

```text
Verification Ladder
Runtime Evidence Pack
Manual Evidence Contract
Log-Screenshot Correlation
Non-goal Preservation Check
```

Runtime evidence schema:

```json
{
  "verification_level": "acceptance_evidence_observed",
  "sources": [
    {
      "source_type": "manual_confirmation",
      "claim": "Kill marker is pink; normal hit marker unchanged.",
      "confidence": "medium",
      "attachments": []
    }
  ],
  "non_goals_checked": [
    {
      "non_goal": "Do not change normal hit marker.",
      "status": "preserved",
      "evidence_refs": []
    }
  ],
  "limitations": ["manual observation only"]
}
```

### 49.4.4 Repair Loop

Strategies:

```text
Failure Evidence Pack
Root-cause Hypothesis Registry
Minimal Fix Plan
Retry Budget Policy
Stop Condition Contract
```

Repair plan schema:

```json
{
  "repair_id": "repair_...",
  "failure_source": "build",
  "failure_class": "api_mismatch",
  "evidence_refs": ["build_diag_001"],
  "hypothesis": "Referenced API type name differs in current IL2CPP dump.",
  "minimal_changes": [
    {
      "target_file": "Plugin.cs",
      "intent": "replace API type reference with verified symbol"
    }
  ],
  "retry_budget_remaining": 1,
  "scope_expansion_allowed": false,
  "stop_condition": "same error after retry"
}
```

Tests:

```text
test_dry_run_does_not_write
test_path_guard_blocks_escape
test_build_error_classified
test_runtime_evidence_requires_claim
test_repair_plan_has_retry_budget
test_repair_does_not_expand_scope_without_evidence
```

---

## 49.5 Memory and Context Compression

Memory must be artifact-based, not chat-history-based.

Strategies:

```text
Artifact-indexed Memory
Critical Constraint Retention
Token Budget Accounting
Context Pack Provenance
Lossy Summary Guard
```

Context pack schema:

```json
{
  "context_pack_id": "ctx_...",
  "feature_id": "feature_...",
  "purpose": "patch_proposal",
  "included_artifacts": [],
  "excluded_artifacts": [
    {
      "artifact_ref": "runtime_evidence.json",
      "reason": "not produced yet"
    }
  ],
  "critical_constraints": [
    "Do not change normal hit marker."
  ],
  "evidence_summary": [],
  "token_estimate": 3200,
  "lossy_sections": []
}
```

Acceptance:

```text
critical non-goals are preserved;
included/excluded artifacts are listed;
token budget is reported;
context pack can be regenerated deterministically for same inputs.
```

---

## 49.6 Evaluation Harness for Agent Quality

Evaluation has two responsibilities:

```text
software correctness regression
agent decision quality regression
```

Strategies:

```text
Golden Path Matrix
Module-specific Eval Cases
False-continue Guard
False-block Guard
Decision Trace Replay
Eval Report Artifact
```

Agent metrics:

| Metric | Meaning |
| --- | --- |
| `route_accuracy` | request route matches expected |
| `risk_accuracy` | risk level matches expected |
| `evidence_readiness_accuracy` | readiness decision is correct |
| `false_continue_rate` | unsafe continuation when should block |
| `false_block_rate` | unnecessary block when should continue |
| `review_block_correctness` | review blocks expected unsafe proposal |
| `dry_run_safety` | dry-run avoids real writes and path escapes |
| `repair_plan_correctness` | repair plan is minimal and evidence-backed |
| `golden_path_success_rate` | full happy path completes |

Eval case schema:

```json
{
  "case_id": "standard_feature_requires_evidence",
  "user_request": "Make kill marker pink but do not change normal hit markers.",
  "expected_route": "full_runtime_investigation",
  "expected_risk": "high",
  "expected_required_evidence": ["target_source", "decompiled_api"],
  "expected_without_evidence": "blocked",
  "must_not_continue_without_evidence": true
}
```

Acceptance:

```text
eval runner writes eval_report artifact;
eval report includes per-case pass/fail;
false_continue_rate is visible as top-level metric;
dashboard can read latest eval report.
```

---

## 49.7 Dashboard, MCP, API, CLI Data Plane

### 49.7.1 Dashboard Page Contracts

| Page | Question Answered | Reads | Forbidden Action |
| --- | --- | --- | --- |
| Workflow Run Viewer | Where did the run go and why? | trace + state snapshots | mutate state |
| Artifact DAG | Which artifacts are fresh/stale? | artifact registry + hashes | rewrite artifacts |
| Evidence Browser | Which evidence supports the change? | evidence_pack | approve patch |
| Proposal Viewer | What change units are proposed? | patch_proposal | apply patch |
| Review Gate Viewer | Why blocked/approved? | proposal_review | override findings |
| Build/Runtime Viewer | What verification exists? | build_result/runtime_evidence | claim success |
| Eval Dashboard | What decisions regressed? | eval_report | edit eval cases |

### 49.7.2 MCP/API Tool Contracts

Every tool must expose:

```json
{
  "name": "review_patch_proposal",
  "permission_level": "report_only",
  "input_schema": {},
  "output_schema": {},
  "returns": {
    "content": [],
    "structuredContent": {},
    "artifact_refs": [],
    "trace_refs": [],
    "blockers": []
  },
  "human_confirmation_required": false
}
```

First safe tools:

```text
get_workflow_status
list_artifacts
read_artifact
retrieve_evidence
preview_patch_proposal
review_patch_proposal
run_eval_suite
```

Explicitly disabled by default:

```text
confirmed_apply
copy_to_game_directory
run_game
delete_artifacts
```

Tests:

```text
test_tools_list_schema
test_tool_output_schema
test_dangerous_tool_hidden_by_default
test_review_tool_returns_structured_findings
test_mcp_error_is_structured
```

---

## 49.8 ADR Backlog and Glossary Backlog

### 49.8.1 ADR Backlog

```text
ADR-001: LangGraph as workflow control plane
ADR-002: Artifact store as source of workflow truth
ADR-003: Evidence before patch proposal
ADR-004: Review before dry-run/apply
ADR-005: Dry-run before confirmed write
ADR-006: Runtime success requires runtime evidence
ADR-007: MCP tools grow from inspection to approved write/runtime routes
ADR-008: Deterministic retrieval before vector dependency
ADR-009: Dashboard reads artifacts/traces, not hidden state
ADR-010: Imported RAG spec is subsystem, not top-level product
```

### 49.8.2 Glossary Backlog

Each term must have one canonical definition:

```text
feature
feature_id
run_id
artifact
artifact_ref
evidence
evidence_item
evidence_pack
readiness
proposal
change_unit
review_finding
dry_run
build_result
runtime_evidence
repair_plan
context_pack
domain_adapter
execution_path
risk_level
checkpoint
interrupt
resume
stale
confirmed_write
external_side_effect
```

Acceptance:

```text
Glossary is referenced by schemas and dashboard labels.
No module invents synonyms for these terms.
```

---

# 50. Development Acceleration Addendum

本章把框架取舍、能力叙事、V1/V2 规划、specialist node、token budget、baseline evaluation 和 GameProfile onboarding 落成推进路线。
它的目的不是给项目降速，而是把每个边界写成可继续实现、可验证、可调整的安排。

## 50.1 Capability Narrative and Evidence Roadmap

本项目应清楚表达每项能力当前做到哪里、下一步如何升级。

能力升级路线：

```text
LLM 单次代码生成 -> evidence/review/dry-run/build/runtime 闭环代码生成
BepInEx 单游戏支持 -> GameProfile onboarding -> 多游戏能力报告
RAG 检索命中 -> EvidencePack -> readiness/review -> patch grounding
build success -> runtime probe/log/screenshot/manual evidence -> gameplay confidence
baseline eval 缺失 -> golden eval set -> measured improvement report
```

本项目核心叙事：

```text
通过 evidence、proposal、review、dry-run、build、runtime、repair 的阶段化流程，
把高风险代码生成从一次性黑盒输出变成可阻断、可复盘、可评估的工程过程。
```

成熟度表述：

```text
Before baseline evaluation exists, emphasize auditability, controllability, and
reviewability by design.
After baseline evaluation exists, report measured improvements for the selected
case set and metrics.
```

这条路线适用于 README、demo script、resume bullets 和面试讲述。

## 50.2 Framework Selection ADR

不要把框架选择写成依赖列表。每个框架必须写清楚：

```text
Framework
Used for
Why reuse
Why not self-build
V1/V2 phase
Fallback
Risk
Not responsible for
```

### 50.2.1 Recommended Framework Decisions

| Framework | Used for | Phase | Why reuse | Growth Path |
| --- | --- | --- | --- | --- |
| LangGraph | workflow orchestration, state transitions, checkpoint, interrupt | V1 | 复用成熟有状态 graph 和 human approval/checkpoint contracts；production HITL still requires dynamic interrupt/Command(resume) path | connect domain decisions, evidence sufficiency, patch review, and runtime verification into graph routing |
| Pydantic v2 | artifact/state/review/evidence schemas | V1 | schema-first、验证强、可测试 | make business decisions explicit in typed artifacts |
| pydantic-settings + YAML | config/env/secrets overlay | V1 | 配置结构化、测试 fake provider 方便 | evolve toward environment profiles and secret integration |
| Typer + Rich | local CLI | V1 | 快速做 `run/show/eval/dashboard` | wrap graph commands and handoff reports |
| pytest | unit/contract/integration/golden tests | V1 | fixture/tmp_path/monkeypatch 成熟 | grow into module eval and transition gates |
| Ruff | formatter + linter | V1 | 工具链简单 | add type checking when it improves speed |
| sqlite3 / SQLite FTS5 | local metadata, source index, simple text retrieval | V1 | 本地零服务依赖 | bridge to vector/search backends as retrieval matures |
| ripgrep subprocess | deterministic text/symbol search fallback | V1 | 快、稳定、可解释 | complement semantic retrieval |
| tree-sitter | optional source symbol extraction | V1 optional / V2 | 比手写代码 parser 稳 | improve C# symbol and patch context |
| unidiff | unified diff parsing | V1 | 只做 diff 结构解析 | feed path policy and review findings |
| MCP Python SDK | tool exposure | V1/V2 | 官方 SDK，减少协议自研 | move from local tool surface to transport/server integration |
| Streamlit | local dashboard | V1/V2 | 快速多页本地 dashboard | evolve into product dashboard or API-backed frontend |
| OpenAI-compatible thin wrapper | first LLM provider abstraction | V1 | 可控、易 mock | grow into provider routing |
| LiteLLM | multi-provider router | V2 | provider 多了再上 | simplify provider expansion |
| Qdrant | dense+sparse hybrid vector backend | V2 | hybrid search 更适合长期路线 | production dense/hybrid retrieval |
| FastAPI | HTTP API | V2 | 服务化时再上 | production API and dashboard backend |
| OpenTelemetry | production observability | V2 | 标准 traces/metrics/logs | production traces/metrics/logs |
| Ragas | supplementary RAG metrics | V2 optional | 补普通 RAG 指标 | combine with agent-specific eval |

### 50.2.2 Framework Responsibility Plan

框架优先承担通用基础设施，项目代码负责把这些能力组合成垂直产品能力。

优先由本项目定义：

```text
Domain Adapter
GameProfile onboarding
Evidence Readiness Gate
Review Gate rules
PathGuard
DryRunApply
Change Unit Model
Build error taxonomy
Runtime verification ladder
Repair budget policy
Agent eval metrics
```

这些能力可以复用框架组件，但产品语义、artifact contract、eval case 和 dashboard projection 应由本项目沉淀。

## 50.3 Evidence Decision Layer

RAG 在本项目中不是问答入口，而是 agent 决策输入层。

定位：

```text
RAG -> Evidence Decision Layer
```

检索结果必须先转换为 `EvidenceItem`，再进入 `EvidencePack`，然后由 readiness / review / planning 消费。

Evidence item 推进：

```text
进入 implementation plan 的证据等级
选择 hook 的证据等级
生成 patch proposal 的证据等级
review 通过所需的证据等级
build repair 扩大搜索范围所需的失败证据
runtime verified 的证据等级
```

直接升级路线：

```text
相似 chunk -> EvidenceItem -> EvidencePack -> readiness -> patch grounding
RAG answer -> runtime hypothesis -> probe/log/screenshot/manual evidence
dense vector 命中 -> target_source/API evidence enrichment
```

高风险代码修改必须满足：

```text
target source evidence
domain/API evidence where applicable
acceptance/non-goal constraints
review gate approval
```

## 50.4 V1 Framework Cut

V1 目标是证明受控工作流、artifact、evidence、review、dry-run、eval 能闭环，而不是展示最多框架。

### 50.4.1 V1 Required

```text
LangGraph
Pydantic v2
pydantic-settings + YAML
Typer + Rich
pytest
Ruff
sqlite3 / SQLite FTS5
ripgrep subprocess
unidiff
FakeLLM
OpenAICompatibleLLM thin wrapper
MCP Python SDK read-only tools
Streamlit minimal dashboard
```

### 50.4.2 V1 Optional

```text
tree-sitter for symbol extraction
pytest-cov
mypy or pyright, choose one only if it does not slow Phase A/B
```

### 50.4.3 V2 Acceleration Track

This subsection is a conditional technology catalog, not the V2 product
mainline, implementation sequence, or active queue. Section 51 is the
normative V2 real-task intelligence-transfer program. No item below may be
selected from technology preference alone; it requires the exact observed
product failure or capability trigger recorded by section 51.

```text
Qdrant
Chroma
LiteLLM
FastAPI
OpenTelemetry
Ragas
Cross-Encoder rerank
Vision LLM real calls
SQLAlchemy
complex multi-agent supervisor
production auth
cloud deployment
```

Planning rule:

```text
These frameworks may appear in interfaces and ADRs.
Promote them when they unlock the next concrete product capability.
```

## 50.5 Specialist Node Design

不要把本项目写成“多 agent 大会”。

V1 使用：

```text
one LangGraph orchestrator
three LLM-backed specialist nodes
deterministic tools first
```

V1 specialist nodes：

| Node | Role | Input | Output | Permission |
| --- | --- | --- | --- | --- |
| Planner | route request, create request_plan/feature_spec draft | user_request + minimal context | request_plan / feature_spec | report_only |
| Evidence | formulate evidence query and summarize evidence_pack | feature_spec + retrieval outputs | evidence_pack summary / readiness rationale | read_only |
| Reviewer | evaluate proposal against rules and evidence | patch_proposal + feature_spec + evidence_pack | proposal_review | report_only |

Specialist node growth shape:

```text
single-purpose role
artifact-in / artifact-out
trace-visible
tool-limited by declared purpose
promotable to stronger automation after tests and review
```

Specialist node must have:

```text
input artifact contract
output artifact contract
prompt contract
allowed tools
permission level
trace events
token budget
tests with fake LLM
```

All other capabilities start deterministic:

```text
retrieval
path guard
dry-run
build parsing
runtime evidence validation
eval scoring
dashboard rendering
```

## 50.6 Token and Context Budget Policy

Context budget is a first-class delivery planning policy.

Default context strategy:

```text
Start each node from a purpose-built context pack.
Expand to source trees, artifacts, legacy history, or full logs when the task requires it.
Prefer top evidence packs for LLM nodes, then attach raw source/log excerpts as needed.
Use deterministic/symbol/FTS retrieval first when it speeds up evidence collection.
```

Per-node budget:

| Node | Default Context | Expansion Path |
| --- | --- | --- |
| Planner | user_request + project brief + route taxonomy | targeted source or prior artifacts when planning needs detail |
| Evidence | feature_spec + retrieval query + top candidates | broader indexed chunks when recall is insufficient |
| Proposal | feature_spec + evidence_pack + implementation_plan | source excerpts and symbol signatures for concrete edits |
| Reviewer | proposal + feature_spec + evidence_pack + review rules | repository context for scope or semantic checks |
| Repair | failure evidence pack + relevant prior artifacts | related feature history when failure repeats |

Context pack schema extension:

```json
{
  "context_pack_id": "ctx_...",
  "purpose": "review_proposal",
  "token_budget": 6000,
  "estimated_tokens": 4200,
  "included_artifacts": [],
  "excluded_artifacts": [],
  "excluded_by_policy": ["raw_legacy_history", "full_logs"],
  "critical_constraints": [],
  "truncation_policy": "preserve_constraints_then_evidence_then_summary"
}
```

If budget is exceeded:

```text
preserve critical constraints
preserve evidence citations
summarize long logs
drop unrelated artifacts
block rather than silently omit required evidence
```

## 50.7 Claim Validation and Baseline Evaluation

Reliability claims require baseline comparison.

Baseline:

```text
LLM direct patch generation
```

Controlled Agent:

```text
request planning
-> evidence retrieval
-> implementation plan
-> patch proposal
-> review gate
-> dry-run
-> build/runtime
-> repair
```

Comparison metrics:

| Metric | Meaning |
| --- | --- |
| hook_selection_correctness | selected hook/symbol matches expected evidence |
| build_pass_rate | generated change builds |
| runtime_trigger_rate | expected runtime path triggered |
| false_success_rate | system claimed success without evidence |
| non_goal_violation_count | declared non-goals violated |
| review_block_correctness | unsafe changes blocked |
| repair_attempts | number of repair loops |
| token_cost | estimated or measured token usage |
| latency | wall-clock runtime |
| human_intervention_count | number of human approvals/questions |

Evidence narrative:

```text
No baseline data:
  present design intent, auditability, controllability, and reviewability.

Baseline exists:
  report measured improvements for the selected metrics and case set.
```

Eval artifact must include:

```json
{
  "baseline": "direct_llm_patch",
  "controlled_agent": "evidence_review_dryrun_pipeline",
  "case_set": "golden_path_v1",
  "metrics": {},
  "claims_allowed": [],
  "claims_next": []
}
```

## 50.8 GameProfile Onboarding

The platform grows game support through GameProfile onboarding.

New games enter through a lightweight onboarding path and can mature from
experimental to supported as evidence, build, and runtime checks accumulate.

GameProfile status:

```text
unsupported
experimental
supported
deprecated
```

Onboarding flow:

```text
identify runtime
collect assemblies / logs / source references
define allowed roots and managed paths
build GameProfile
index evidence sources
run smoke plugin or equivalent startup probe
generate capability report
mark domain as supported / experimental / unsupported
```

GameProfile schema:

```json
{
  "game_id": "gtfo",
  "display_name": "GTFO",
  "runtime": "Unity IL2CPP",
  "mod_loader": "BepInEx",
  "harmony": "HarmonyX",
  "status": "experimental",
  "allowed_roots": [],
  "managed_paths": [],
  "build_profiles": [],
  "evidence_sources": [],
  "smoke_tests": [],
  "known_limitations": [],
  "capability_report_ref": ""
}
```

Capability report must answer:

```text
Can we compile a minimal plugin?
Can we detect plugin startup in logs?
Can we index target/source/API evidence?
Can we classify risk levels?
Which runtime verification levels are available?
What should be implemented next?
```

Before a GameProfile is complete:

```text
planning may classify request;
evidence retrieval may inspect generic docs;
patch proposal should produce onboarding/evidence tasks for game-specific runtime changes.
```

## 50.9 Architecture and Flow Diagram Review

After adding the governance rules above, the existing diagrams in Chapter 40 are mostly directionally correct, but they need two clarifications:

```text
Evidence RAG should be labeled as Evidence Decision Layer / Knowledge Hub, not a QA endpoint.
Domain Adapter should explicitly include GameProfile onboarding and risk policy.
Specialist nodes should appear inside the single LangGraph orchestrator, not as
free multi-agent workers. Do not split many specialist nodes before the core
graph, routing, interrupt/resume, and checkpoint/resume are stable.
V1 framework cut means vector DB / Vision / FastAPI / OpenTelemetry are optional future containers, not V1 required path.
```

### 50.9.1 Revised Top-level Architecture

```text
User / CLI / MCP Client
        |
        v
Safe Adapter Layer
  - CLI commands
  - MCP inspection plus approved write/runtime routes
  - API later
        |
        v
LangGraph Workflow Control Plane
  - state
  - checkpoint
  - conditional edges
  - interrupt/resume
        |
        +--> Specialist Nodes
        |      - Planner
        |      - Evidence
        |      - Reviewer
        |
        +--> Deterministic Tools
        |      - ripgrep / FTS / symbol lookup
        |      - PathGuard
        |      - DryRunApply
        |      - Build runner
        |
        +--> Domain Layer
        |      - Domain Adapter
        |      - GameProfile
        |      - Risk Policy
        |
        +--> Evidence Decision Layer
        |      - Knowledge Hub
        |      - EvidencePack
        |      - Readiness Gate
        |
        +--> Change Control Layer
        |      - Feature Spec
        |      - Implementation Plan
        |      - Patch Proposal
        |      - Review Gate
        |
        +--> Execution Validation Loop
        |      - Dry-run
        |      - Build
        |      - Runtime Evidence
        |      - Repair
        |
        +--> Evaluation and Observability
               - JSONL traces
               - Eval reports
               - Streamlit dashboard

All stages write:
  Structured Artifacts + Trace Events
```

### 50.9.2 Revised Evidence Decision Flow

```text
Feature Spec / Implementation Intent
        |
        v
Context Budget Policy
        |
        v
Deterministic Retrieval First
  - symbol lookup
  - SQLite FTS5 / BM25
  - ripgrep
        |
        v
Optional Dense Retrieval Later
  - vector DB deferred to V2
        |
        v
Evidence Items
        |
        v
Evidence Pack
        |
        v
Readiness Gate
   | insufficient -> blocked
   | partial low-risk -> continue with warning
   | sufficient -> implementation plan / proposal / review
```

### 50.9.3 Revised Controlled Patch Flow

```text
Request
  -> Planner Specialist
  -> Request Plan
  -> Feature Spec
  -> Evidence Decision Layer
  -> Implementation Plan
  -> Patch Proposal
  -> Review Gate
      -> blocked
      -> revise proposal
      -> requires human approval
      -> approve dry-run
  -> Dry-run Apply
      -> path violation -> blocked
      -> conflict -> repair
      -> clean -> build
  -> Build
      -> failed -> Failure Evidence Pack -> Repair Plan
      -> success -> Runtime Verification Ladder
  -> Runtime Evidence
      -> not verified -> Repair Plan
      -> verified + non-goals preserved -> Eval
  -> Eval Report
  -> Done
```

### 50.9.4 Diagram Suitability Verdict

Current Chapter 40 diagrams are suitable as high-level sketches, but implementation should follow the revised diagrams in this section because they add:

```text
GameProfile boundary
Evidence Decision Layer naming
Specialist node containment
V1 deterministic-first retrieval
Context budget gate
Baseline/eval before claims
Runtime verification ladder before success
```

Therefore:

```text
Chapter 40 remains useful for README-level explanation.
Chapter 50.9 is the implementation-level architecture reference for V1.
```

---

# 51. V2 Real-Task Intelligence Transfer Program

This chapter defines the V2 capability program that begins after the controlled
workflow baseline exists. It supersedes any interpretation of V2 as a list of
frameworks to install or as a replay of the stage names Proposal, dry-run,
apply, build, and runtime.

V2 is advanced through one real product request at a time. The current request
is WallCrawler. Platform infrastructure may grow only when the current run
exposes an exact missing capability, protocol failure, evidence gap, or
verification failure.

## 51.1 Problem, Goal, And Optimization Target

The implemented control plane can already route planning, evidence, Proposal,
review, dry-run, approval, isolated apply, build, runtime, and repair. That
proves controlled execution behavior. It does not by itself prove that the
platform has taken over the substantive decisions that an operator previously
performed.

The unproven decisions include:

```text
which registered source is relevant;
which bounded evidence tool should run first;
which symbol is discovered from the observation rather than supplied manually;
which dependent tool call follows from that symbol;
what the observed evidence proves and does not prove;
whether the current tool set is sufficient;
whether the run should finish, block, or request one bounded capability.
```

Without this capability, the operator or Codex can precompute paths, symbols,
tool order, IL reports, and blockers while LangGraph only validates the answer.
That is a controlled workflow, not demonstrated intelligence transfer.

The V2 optimization target is therefore:

```text
maximize verified platform-owned task decisions inside a real request
while preserving deterministic route, permission, evidence, write, and claim authority
```

The target is not maximum autonomy, maximum model calls, maximum tool count, or
minimum human approval. Human approval remains mandatory where disclosure,
write, game launch, game-directory copy, or runtime control requires it.

## 51.2 Status And Authority Model

Architecture references use the existing exact states:

- `implemented`: current source plus focused evidence supports the recorded
  claim boundary;
- `documented_only`: responsibility separation or a possible design, not an
  implementation or queue entry;
- `conditional_trigger`: implementation may be selected only after the exact
  real-task signal named by the reference is recorded.

Implementation status and semantic evidence status are separate. A model
adapter or loop can be implemented and locally tested while real-model semantic
quality remains unproven.

The single LangGraph `StateGraph` remains the control plane. Specialist loops
operate inside their nodes. They cannot authorize paths or writes, approve a
Proposal, launch build/runtime work, or choose final graph routes. ArtifactStore
owns durable outputs and lineage. Deterministic policy owns validation and
promotion.

## 51.3 V2 Program Shape

The V2 program has one current core gate and a set of later conditional product
gates.

### 51.3.1 Core Intelligence-Transfer Gate

```text
V2-A controlled intelligent input
-> V2-B bounded intelligent loop inside retrieve_evidence
-> V2-C real WallCrawler run with no manual answers
-> V2-D add only the exact capability or loop repair exposed by that run
-> rerun V2-C
-> resolve the intelligence-transfer gate truthfully
```

The gate can resolve with grounded `needs_more_evidence`. It does not require
WallCrawler Hook feasibility or Proposal readiness. It does require the model
to perform an observation-dependent evidence sequence and finish truthfully
within the configured boundary.

### 51.3.2 Conditional Delivery-Intelligence Gates

Only after the core gate is resolved may the selected product request activate
one later gate:

```text
evidence-to-implementation planning
-> Proposal-only generation and review
-> deterministic dry-run and exact approval
-> isolated apply and real build
-> failure-driven build repair when observed
-> separately approved runtime evidence and diagnosis
-> evaluation, delivery, repair, or explicit unresolved handoff
```

These are not a preapproved consecutive queue. Each gate has its own entry
evidence, selected capability, permission boundary, verification, and stop
condition. Dry-run and apply remain deterministic control mechanisms; no model
role is added merely because a later stage exists.

## 51.4 V2-A Controlled Intelligent Input

### 51.4.1 Input Representation

The model input combines:

```text
natural-language product goal;
path-hidden Source Registry views;
allowed read-only tools per source;
model-step, tool-call, result-byte, and total-observation budgets;
external disclosure boundary;
evidence-only stopping boundary;
current compact action/observation trajectory;
deduplicated metadata-method and IL-inspection catalogs;
latest full observation only.
```

Machine-local roots, API keys, write targets, and unrestricted filesystem
access are not model input. Source identity is preserved through registered
source id, relative path, live file identity, assembly identity where
applicable, and current-run observation identity.

### 51.4.2 Information Preserved And Lost

The representation preserves:

```text
the product goal;
which evidence classes and tools are available;
the current source and assembly identity;
the exact observed method identity needed for dependent IL work;
the exact direct IL identity, method-body outcome, instruction count, and
inspection observation id after its full payload rotates out;
prior action summaries and observation ids;
budget, stop state, and per-turn serialized discovery-message byte counts.
```

It intentionally removes:

```text
absolute local paths;
unrelated source trees;
earlier full observations after their compact identities are recorded;
hidden model reasoning;
unapproved local material;
operator-supplied answers that would make the intelligence claim circular.
```

Loss is acceptable only when the compact trajectory retains every identity
required for a legal dependent action. If a required source, method identity,
constraint, or observation reference is lost, the run blocks or the context
representation is repaired; the model may not reconstruct it by guessing.

### 51.4.3 Input-Pollution Boundary

A V2-C acceptance run requires all four current audit counts to remain zero:

```text
manual_symbol_count
manual_tool_sequence_count
precomputed_report_count
operator_intervention_count
```

The user may approve sources and data disclosure. That approval does not select
the source, DLL, symbol, Hook, method, or tool sequence for the model.

## 51.5 V2-B Bounded Evidence Intelligence Loop

### 51.5.1 Core Mechanism

```text
initial goal and registered source views
-> provider-neutral Agent turn
-> native tool call or final structured output
-> deterministic source/tool/argument validation
-> local read-only tool execution
-> observation identity and byte accounting
-> compact trajectory plus deduplicated method/inspection catalogs
-> latest full observation without catalog duplication
-> dependent next Agent turn
-> deterministic conclusion validation
-> EvidencePack
-> LangGraph conditional edge
```

Native provider structures terminate at the adapter. Qwen Chat `tool_calls`,
OpenAI Responses typed items, and any future provider representation do not
enter EvidencePack or LangGraph state as provider authority.

The current dependent discovery sequence is:

```text
search_dotnet_metadata
-> current-run observation containing exact method_id values
-> inspect_method_il using one observed method_id
```

The IL call is illegal when the method identity was not created by a prior
current-run metadata observation for the same registered source identity.

### 51.5.2 Current Budget Boundary

Current implemented defaults are:

```text
max_tool_calls: 6
max_model_steps: 8
max_result_bytes_per_call: 65,536
max_total_observation_bytes: 262,144
metadata model observation cap: 16,384 bytes
parallel tool calls: disabled
Qwen thinking for this sequence: disabled
```

The prior real Qwen baseline used 8 model steps, 6 tool calls, and 205,912
observation bytes before ending without a conclusion. Run 008 used 7 model
steps, all 6 tool calls, 20,417 observation bytes, and 35,134 provider input
tokens. It exposed a successful IL observation that disappeared from compact
interpretation and caused four later metadata searches. Repair 009 records
per-turn serialized discovery-message bytes and, after an IL observation,
directs the model to finish unless one exact unresolved gap justifies another
tool call. The local metadata-to-IL-to-finish fixture uses 13,864 message bytes
in three turns versus the 38,774-byte seven-turn pre-repair fixture. These are
provider-independent serialized-message measurements; a later real run must
separately report provider token usage. Comparing total observation size with
205,912 or message bytes with the recorded fixture is a task acceptance
measurement, not a generic hard budget embedded in every future request.

### 51.5.3 Conclusion Boundary

Final evidence conclusions use the exact current classes:

```text
observed
inferred
unknown
```

Observed and inferred conclusions cite current-run observations. Inferred
conclusions state limitations. Unknown conclusions do not cite an observation
as proof and state the missing boundary. A decision of
`sufficient_for_proposal` cannot contain open gaps. A decision of
`needs_more_evidence` must identify an unresolved question or missing
capability.

No conclusion, score, or model self-report can grant write authority or bypass
Evidence readiness, Binding Registry, Proposal review, approval, runtime, or
evaluation gates.

## 51.6 V2-C Real-Model Acceptance

### 51.6.1 Required Evidence Mode

Injected or fake models prove local contracts only. The intelligence-transfer
claim requires at least one separately approved real-model run against the
current WallCrawler request and current registered source identities.

The run remains evidence-only and stops at `evidence_retrieval`. It does not
create `implementation_plan`, Proposal, dry-run, apply, build, or runtime
artifacts.

### 51.6.2 Acceptance Conditions

The run must establish all applicable conditions from actual trajectory data:

```text
run_status is completed rather than budget_exhausted;
the model finishes before the model-step and tool-call budgets are exhausted;
all input-pollution counts are zero;
the model selects a registered source without being given the answer;
the model selects metadata search as an evidence action;
metadata returns a current-run, source-bound, observation-bound candidate_ref;
the model selects a dependent IL read using that candidate_ref;
the control layer resolves and validates the candidate_ref as an internal method_id;
the conclusion cites the resulting IL observation;
the conclusion passes observed/inferred/unknown validation;
no identical source/tool/arguments action repeats;
per-turn provider usage is recorded;
the graph stops at evidence_retrieval;
forbidden later artifacts are absent.
```

Semantic relevance is reviewed separately for the real case. Current
`semantic_relevance_evaluated=false` is truthful until that review occurs.
Tool-call success alone is not semantic acceptance.

### 51.6.3 Valid Outcomes

```text
grounded needs_more_evidence
  -> intelligence transfer may pass;
  -> Proposal remains locked;
  -> exact gaps may select one later evidence task.

grounded sufficient_for_proposal
  -> intelligence transfer may pass;
  -> the evidence-only run still stops;
  -> a separate Proposal-only task may be selected.

budget, schema, provider, tool, identity, repetition, or grounding failure
  -> intelligence transfer does not pass;
  -> route only to one bounded repair based on that failure.
```

### 51.6.4 Local Real-Model Acceptance Boundary

A non-injected local model may supply real-model trajectory evidence without
external disclosure only when all model inputs remain on-device and the client
accepts a literal `127.0.0.1` or `::1` HTTP origin. The local client must reject
LAN addresses, domain names including `localhost`, HTTPS origins, URL paths,
credentials, queries, fragments, redirects, and environment proxy routing. Its
EvidencePack identity is `local_agent_turn_adapter`, not external and not
injected/test.

Capability, convergence, and semantic acceptance are independent:

```text
capability gate
  -> within 8 model turns and 6 tools;
  -> registered metadata search followed by an IL read whose candidate_ref
     came from a prior metadata observation in the same run and whose internal
     method_id was resolved and validated by the control layer;
  -> an observed/inferred conclusion cites the IL observation;
  -> input pollution and repeated identical calls are absent;
  -> evidence-only stop is preserved.

convergence gate
  -> exactly 3 model turns and 2 tools on the intended path;
  -> zero corrections and no broad metadata search after successful IL.

semantic gate
  -> deterministic tools project structured observation facts and one exact
     canonical_claim for each mechanically verifiable fact;
  -> observed conclusions count as verified findings only when the claim equals
     one canonical_claim and cites only that fact's observation_id;
  -> inferred conclusions require fact-bearing observation refs and limitations
     but remain unverified; unknown conclusions cite no observation and state
     their evidence limitation;
  -> reference integrity, bounded uncertainty, PersistentID/identity gaps, and
     Proposal lock are checked post-run through the same provider-neutral path;
  -> expected symbols and hidden scoring rules never enter model-visible context.
```

A bounded four-turn trajectory may pass capability and fail convergence. Raw
local tokens are recorded but are not numerically compared with a hosted
provider that uses different tokenization and accounting.

`WALLCRAWLER-LOCAL-MODEL-EVIDENCE-011` implemented this boundary with Ollama
0.32.0 and `qwen3:4b-instruct`. Its one run preserved local-data and stop
boundaries but failed all three gates: 7 turns, 6 metadata-only calls, 3
repeated exact action signatures, no IL inspection, and no IL-grounded
conclusion. The exact UTF-8 request was preserved. This selects no repair by
itself. `WALLCRAWLER-INTELLIGENT-EVIDENCE-012` then repaired only the observed
query/repeat contract locally: metadata lookup is described as case-insensitive
literal-substring matching over fully qualified managed symbols; exact repeated
source/tool/arguments are rejected before execution; one repeat-specific answer-free correction
is allowed; and a second repeat stops deterministically. The injected recovery
path reaches observation-derived IL and an IL-bound conclusion without adding
tools or runtime budget. This is not real-model acceptance.

`WALLCRAWLER-LOCAL-MODEL-EVIDENCE-013` exercised prompt v5 once with the same
011 local model and inputs. It reduced the executed path to metadata, metadata,
and one observation-derived IL read with no exact repeat, but failed finish
acceptance twice: wrong top-level fields, then `sufficient_for_proposal` with
open questions. The deterministic budget stop removed the rejected IL-grounded
conclusion from the final pack, so all three hidden gates remained false. The
run also showed that an example-like query placeholder can be copied as a
literal query and that method-origin provenance is incorrectly coupled to final
convergence in the current report. These are observed failure directions only;
no repair or rerun is automatically selected.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-014` repairs only those three structural
failures under deterministic injection. Prompt v6 represents tool arguments as
field names rather than copyable values; the shared finish schema and bounded
correction both expose decision/open-gap constraints; and method-origin
provenance is derived from the accepted IL action independently from finish
convergence. The normal three-turn and repeated-method fixtures remain below
their unchanged message-byte thresholds. No tool, runtime budget, route,
disclosure, or stop boundary changes, and no real-model acceptance is claimed.

`WALLCRAWLER-LOCAL-MODEL-EVIDENCE-015` exercised prompt v6 exactly once through
the same loopback-only model, original request bytes, source identities, and
budgets. The old value-like placeholder was not copied. The model searched both
sources with the same five invented behavioral symbol strings and received zero
methods, then twice returned to the same current-interop source/tool/arguments
signature. Both repeats were rejected before execution and deterministic
correction exhaustion stopped the run after 4 model turns and 2 metadata tools.
No method_id, IL action, or model conclusion was produced. Capability,
convergence, and semantic gates all failed while the evidence-only stop and
input-pollution boundary passed. This run did not exercise finish validation or
method-origin provenance and selects no repair or rerun automatically.

The following infrastructure validation used the same 342-byte request,
registered source identities, artifact root, loopback-only
`qwen3:4b-instruct`, and unchanged 8-step/6-tool envelope. Before the repair, a
run had stopped at the first `request_planning_report` pending-marker replace:
the temporary source path was 222 characters, the target was 269, the parent
existed, and `os.replace` returned WinError 3 before any model or evidence-tool
call. That evidence supports a path-addressability root cause for this deployed
write chain, but it is not a general Windows conclusion.

After section 49.2.7 was implemented and its focused no-model tests passed, one
new run completed the graph persistence path under run id
`intelligent_evidence_5327cb5988774bc5aba6cfcc53f8d2ab`. All four evidence-only
runtime artifact types produced validated revision and latest files; the
longest actual revision/pending path was 224 characters, and no pending or
temporary file remained. The run then ended legally as `budget_exhausted` after
6 model turns and 4 executed metadata searches plus 2 rejected repeated
actions. It selected no IL inspection and emitted no accepted evidence
conclusion. Capability, convergence, and semantic gates therefore remain false;
the persistence result proves only that the earlier infrastructure stop no
longer prevents this bounded run from reaching Agent execution and durable
EvidencePack output.

One separately approved external `qwen3.6-plus` execution then exercised the
post-diagnostic contract exactly once with no automatic retry. Run
`intelligent_evidence_448f8515e5634f9faf629494f8febbef` completed at
`evidence_retrieval` in 7 model turns and 6 evidence-tool calls. It performed
four metadata searches and two dependent IL inspections. Both inspections
were selected through model-visible `candidate_ref` values and resolved by the
control layer to current-run internal method identities. EvidencePack
provenance records both complete chains:

```text
obs-003
-> candidate_73ff66bd287ccffec09039cd
-> method_b4cf489925e45dbbe0661c06
-> obs-004

obs-005
-> candidate_dab6a6eb4f59525935cddc34
-> method_04088bcea8cc3f1a170053db
-> obs-006
```

The run produced `needs_more_evidence`, stopped before implementation planning,
and created no Proposal, build, or runtime artifact. Its running and terminal
`evidence_run_attempt` revisions share the run id; the terminal revision
records 7 external model calls, 7 accepted model actions, 6 executed tools, and
matching provider-reported and adapter-extracted tool names for all six calls.
The EvidencePack hash is
`2174bca310480916658811dd46e9cd8858b2a241371310a4365379add2b60a81`.

This run proves the bounded model-tool-observation identity loop under the
recorded request, source snapshots, tool contract, model, and budget. It does
not prove semantic acceptance or V2-C completion. The current post-run semantic
evaluator returned a false positive on this pack: observation `obs-006` proves
only the inspected method identity and instruction sequence `nop; ret`, while
the model labeled Hook viability and possible base-class logic as observed;
observation `obs-004` proves a static-field getter body, not the claimed
movement-physics or surface-interaction behavior. The evaluator currently
checks symbol/reference association rather than predicate-level observation
fidelity, and the external Qwen entry does not invoke the WallCrawler evaluator
path used by the local Ollama entry. Until those two observed defects are
repaired and tested, the recorded semantic result is invalid, evidence
sufficiency is false, implementation planning remains locked, and V2-C remains
incomplete.

The bounded semantic repair is now implemented without changing graph routing,
model/tool budgets, or later workflow stages. Prompt contract v9 exposes only
observation id plus deterministic `canonical_claim` in the model view, while
EvidencePack retains the complete `observation_fact_catalog`. Unsupported
`observed` text no longer enters `verified_findings`. The provider-neutral
post-run evaluator separately checks reference integrity, exact observed-fact
matching, bounded unverified inference, bounded unknowns, verified-finding
purity, unresolved identity evidence, and Proposal lock. Focused regression
passed 154 related tests. Offline reevaluation of the preserved external Qwen
pack now reports capability true, convergence false, and semantic false, with
both overreaching observed conclusions rejected. Because that pack predates the
fact catalog and no new real model run occurred, this repair is implemented and
locally validated but does not establish semantic acceptance or V2-C completion.

## 51.7 V2-D Failure-Driven Capability Growth

V2-D is `conditional_trigger`, not an open tool-building phase.

| Observed failure class | Allowed response | Forbidden expansion |
| --- | --- | --- |
| provider request or response mismatch | repair the current adapter mapping and add a captured regression | replace the control plane or build a generic provider router |
| action/schema failure | repair the exact tool/final contract or validation feedback | weaken deterministic validation |
| repeated work or context growth | repair trajectory reconstruction, observation shape, deduplication, or post-inspection stop signaling; 009 applies this to the 008 direct-IL loss | add unbounded chat memory or silently enable provider-side retained conversation state |
| metadata result noise | narrow the current query/result representation | activate Dense/RRF/rerank without a measured retrieval failure |
| missing current method identity | add the smallest current-source identity lookup proven necessary | build a general decompiler platform |
| missing native mapping | add one bounded read-only mapping tool for the exact registered material | claim native semantics from interop wrappers |
| tool process failure | repair the registered local tool invocation and evidence reporting | allow unrestricted Shell or target execution |
| grounded `needs_more_evidence` | select one exact evidence acquisition task | convert an unresolved gap into Proposal readiness |
| semantic irrelevance | repair source projection, query choice, or the exact missing evidence tool | pass because the trajectory was structurally valid |

Each repair has a finite retry budget and returns to the same V2-C acceptance
run. Repeated failure at the stop condition yields an explicit unresolved or
blocked handoff.

## 51.8 Conditional Post-Core Capability Gates

The following design is deeper than a stage list. Each gate defines the
decision capability to prove, its input representation, deterministic authority,
failure boundary, and evidence required for promotion.

### 51.8.1 Evidence-To-Implementation Planning

Entry trigger:

```text
the intelligence-transfer gate is resolved;
the selected evidence decision supports planning;
the user selects a Proposal-oriented product task.
```

Capability to prove:

```text
transform FeatureSpec, EvidencePack, current Binding Registry, acceptance
criteria, non-goals, and runtime applicability into a bounded implementation
intent without inventing paths, symbols, Hooks, APIs, or configuration fields.
```

The model may propose change intent and unresolved alternatives. Deterministic
validation owns target binding, writable scope, evidence refs, risk, and whether
planning may continue. Missing Hook, source identity, configuration identity,
or runtime plan blocks the gate.

Promotion evidence is an implementation plan whose targets and claims are
bound to current artifacts and source identity. The gate stops before source
write.

### 51.8.2 Proposal-Only Generation And Review

Entry trigger:

```text
a current validated implementation plan exists;
the Proposal-only task is explicitly selected;
required source disclosure is approved for that generation run.
```

Capability to prove:

```text
generate a minimal exact patch proposal from the bounded context pack and
survive deterministic review without relying on copied or invented authority.
```

The Proposal context preserves exact evidence refs, target bindings, source
excerpts, acceptance criteria, non-goals, side-effect boundaries, and rollback
intent. It excludes unrelated source and historical chat.

ProposalReviewer remains authoritative. ProposalCritic is called only when the
explicit `critic_requirement` requires it. A review failure may select one
proposal-repair task; it cannot authorize a write or activate parallel critics,
Worker self-check, or second-level Critic without the documented real failure
trigger.

Promotion evidence is a reviewed Proposal that is allowed to enter dry-run.
The gate performs no source write.

### 51.8.3 Deterministic Dry-Run And Exact Approval

Entry trigger:

```text
Proposal review permits dry-run;
current bindings and source identities are fresh.
```

No new model intelligence is required by default. The capability is
deterministic simulation and user inspection:

```text
fresh live-source read;
exact before/after display;
unique-match and path validation;
no-write result;
exact context/diff hash;
explicit approval boundary.
```

Conflict, ambiguity, stale binding, or source drift blocks. A model may explain
the conflict only in a separately selected repair task; it cannot reinterpret
the approved bytes.

### 51.8.4 Isolated Apply And Real Build

Entry trigger:

```text
the user approves the exact displayed hash;
fresh source and Binding Registry checks still match.
```

Apply remains deterministic and isolated. Build uses the declared profile and
must verify the expected artifact identity. Neither exit code zero nor DLL
existence alone proves runtime behavior.

If build fails, the next intelligence capability is not generic self-healing.
It is a failure-evidence-bound repair loop:

```text
compiler diagnostics and build log refs
-> bounded root-cause hypothesis
-> minimal repair intent
-> new Proposal
-> normal review, dry-run, approval, apply, and build gates
```

The repair model cannot edit directly, broaden scope without evidence, or skip
review because the failure occurred after approval.

### 51.8.5 Runtime Evidence And Diagnosis

Entry trigger:

```text
the selected request requires runtime acceptance;
a verified build artifact exists;
the user separately approves each required game copy, launch, process, capture,
or manual observation action.
```

Runtime intelligence is evidence interpretation, not autonomous game control.
It receives only approved logs, screenshots, probe output, manual notes, current
build identity, environment identity, acceptance criteria, and non-goals.

The runtime gate must separate:

```text
startup/load evidence;
configuration and identity binding evidence;
gameplay behavior evidence;
non-goal preservation evidence;
missing or contradictory signals.
```

A build-level fact cannot become a gameplay claim. A local probe cannot become
real game evidence. A runtime failure may select one bounded diagnosis/repair
task, which re-enters Proposal review and the normal execution gates.

### 51.8.6 Evaluation, Delivery, And Reuse

Delivery claims use the weakest evidence boundary. Evaluation records the
selected case, route, evidence sufficiency, Hook/file correctness where ground
truth exists, review correctness, repair attempts, token usage, latency, human
interventions, runtime applicability, and limitations.

One successful WallCrawler run proves that bound task and environment only. It
does not establish cross-project generality. Artifact history and Git preserve
audit lineage; they do not become learned memory or policy. Reusable lessons
remain planning-only and require a separately triggered experiment under the
long-term memory rules.

## 51.9 Task Promotion Contract

Only one selected product task enters `docs/IMPLEMENTATION_QUEUE.md`. A V2 task
record must identify:

```text
the concrete product decision or observed failure;
the intelligence capability being transferred;
the current source, artifact, log, or runtime evidence;
the model and tool input representation;
the information intentionally excluded;
the deterministic authority that remains outside the model;
the exact permissions and disclosure required;
the focused verification and real-run acceptance;
the stop condition and conditional next outcomes.
```

A later gate is not activated because it appears in this chapter. It activates
only when the preceding real result supplies its exact trigger and the user or
product decision selects it.

## 51.10 Current WallCrawler Mapping

Current verified mapping:

| Work | V2 role | Current claim |
| --- | --- | --- |
| `WALLCRAWLER-PLAN-001` through `WALLCRAWLER-CURRENT-HOOK-EVIDENCE-003` | real request, deterministic Evidence, source/tool baseline | supporting evidence and regression baseline; not intelligent-transfer proof |
| `WALLCRAWLER-INTELLIGENT-EVIDENCE-004` | V2-A and V2-B plus first V2-C attempt | bounded loop implemented; prior real Qwen run ended without conclusion |
| acceptance-hardening insertion | failure-driven validation repair | conclusion, provenance, identity, budget, and input-audit boundaries tested locally |
| `WALLCRAWLER-INTELLIGENT-EVIDENCE-005` | failure-driven provider/context/observation repair | structured turns and compact context tested locally; no new real-model semantic acceptance |
| `WALLCRAWLER-INTELLIGENT-EVIDENCE-006` | post-005 V2-C real-model acceptance | real Qwen used six focused metadata searches and only 20,001 observation bytes, but never selected IL and failed two exact finish validations; intelligence transfer remains unresolved |
| `WALLCRAWLER-INTELLIGENT-EVIDENCE-007` | 006-triggered V2-D contract/progress repair | one exact nested finish schema is shared across model response format, system context, and bounded correction; metadata/IL observation progress and remaining acceptance requirements are locally tested with unchanged tools and budgets; no external model call |
| `WALLCRAWLER-INTELLIGENT-EVIDENCE-008` | post-007 V2-C real-model acceptance | real Qwen converged in 7 steps, selected one metadata-derived IL read, and emitted a valid `needs_more_evidence` finish; the gate remains unresolved because no grounded conclusion cited the IL observation and later compact context misrepresented the successful IL step as `observed_methods: []` |
| `WALLCRAWLER-INTELLIGENT-EVIDENCE-009` | 008-triggered V2-D compact-IL and convergence repair | direct IL outcomes survive in a deduplicated inspection catalog, repeated metadata method identities collapse, the latest full observation is not duplicated, per-turn message bytes are recorded, and missing IL citation receives one bounded correction; 75 focused tests passed with unchanged tools and budgets and no external call |
| `WALLCRAWLER-LOCAL-MODEL-EVIDENCE-011` | loopback-only local real-model acceptance plus local provider boundary | Ollama native tools and separate hidden gates are implemented and 85 focused tests pass; the one real local run used six metadata searches with three repeated signatures, selected no IL, and failed capability, convergence, and semantic gates while preserving local-data and evidence-only boundaries |
| `WALLCRAWLER-INTELLIGENT-EVIDENCE-012` | 011-triggered V2-D query-semantics and exact-repeat repair | prompt v5 states the actual literal managed-symbol query semantics; exact repeated source/tool/arguments are rejected before execution with one repeat-specific answer-free correction; deterministic recovery reaches changed metadata query, observation-derived IL, and grounded conclusion; a second repeat stops; 198 affected tests pass with no real model call, tool addition, or runtime-budget increase |
| `WALLCRAWLER-LOCAL-MODEL-EVIDENCE-013` | post-012 same-model local V2-C rerun | exact 011 input and 4B Q4 identity preserved; 5 turns and 3 tools reached observation-derived IL with no repeat; two invalid finishes exhausted correction, no accepted final conclusion survived, all hidden gates failed, and Proposal remained locked |
| `WALLCRAWLER-INTELLIGENT-EVIDENCE-014` | 013-triggered V2-D query/finish/provenance repair | prompt v6 removes copyable argument values, shares finish cross-field rules across initial and correction context, and separates valid method-origin provenance from convergence; 31 direct and 199 affected deterministic tests pass with unchanged tools, budgets, and evidence-only stop; no real model call |
| `WALLCRAWLER-LOCAL-MODEL-EVIDENCE-015` | post-014 same-model local V2-C rerun | exact request/source/model/budget boundaries preserved; the removed placeholder was not copied, but identical zero-result query strings were used across both sources and repeat correction exhausted before method_id or IL; 4 turns, 2 metadata tools, no model conclusion, all hidden gates false, Proposal locked |
| 2026-07-17 artifact persistence validation | infrastructure unblock plus one bounded local execution | short physical locators, complete-hash collision checks, legacy revision reads, atomic preflight, and structured CLI blocking are implemented; run `intelligent_evidence_5327cb5988774bc5aba6cfcc53f8d2ab` persisted all evidence-only artifacts and then ended `budget_exhausted`; all V2-C gates remain false |
| 2026-07-18 external Qwen evidence-loop validation | attempt diagnostics plus real candidate_ref identity loop | checkpoint `5c78e06` durably binds pre-call and terminal attempt revisions and sanitized provider diagnostics; one approved `qwen3.6-plus` run completed four metadata searches, two candidate_ref-derived IL reads, and a grounded-abstention finish with complete provenance, but the current semantic evaluator produced a demonstrated false positive and is not invoked by this provider path; V2-C and implementation readiness remain false |

The 006-exposed model-facing acceptance-contract repair is complete as 007 and
was exercised exactly once by 008. The 008-exposed compact IL, inspection-
citation, and post-IL convergence failure is repaired locally as 009. It does
not authorize a larger budget, a new tool, Proposal, implementation, provider-
side conversation retention, or another external run. 011 later exercised the
same loop through a literal-loopback local model and exposed identifier-query
and repeated-action failures; 012 repairs those two contracts locally without
resolving real-model intelligence transfer. 013 then reached IL without a
repeat but failed final-schema convergence and exposed query-placeholder plus
provenance-report coupling. 014 repairs those three structural defects locally.
015 exercised prompt v6 once without copying the removed placeholder but failed
before IL because it did not revise zero-result literal symbol queries and then
exhausted repeat correction. It therefore does not validate the finish or
provenance repairs and does not select another repair automatically. Any
later external rerun requires new exact per-run disclosure approval; any local
rerun requires a separately selected bounded task and the same loopback-only
boundary. Both must stop at `evidence_retrieval`. The result selects only one of:

```text
intelligence gate resolved with Proposal still locked;
one exact evidence-capability task;
one exact loop/provider/tool repair;
explicit unresolved or blocked handoff.
```

## 51.11 Non-Goals

This program does not authorize:

```text
an always-on multi-agent swarm;
top-level ReAct migration;
parallel specialist fan-out without a separable real risk;
two-level Critic without the recorded cross-context review failure;
Dense, RRF, rerank, or formal retrieval expansion without measured need;
a generic decompiler or native reverse-engineering platform;
automatic source, Hook, path, permission, or write authority selection;
automatic game copy, launch, process control, or gameplay claim;
long-term memory, policy learning, or threshold tuning from chat history;
framework installation as a substitute for a verified product capability.
```


