# Evidence-Grounded Controlled Code Generation Agent Platform

Current execution scope and claim boundaries: `docs/ACTIVE_PRODUCT_CONTRACT.md`.

一个面向垂直代码开发场景的受控 Agent 平台。

首个验证场景是 GTFO / BepInEx / IL2CPP / Harmony 风格 DLL Mod 开发，但
GTFO 不是最终边界。项目目标是构建可扩展到其他 Unity / BepInEx /
Harmony 插件项目的代码开发 Agent。

## Phase A: 平台骨架

当前阶段目标：建立**可运行、可测试、可扩展**的平台骨架。

### Phase A 交付清单

- [x] 可导入的 Python 包：`src/mod_agent/`
- [x] 最小 CLI 入口：`python -m src.main plan-request "描述"`
- [x] 测试基线：`pytest tests/unit/test_mod_agent_cli.py` 可运行
- [x] 初始配置：`config/settings.yaml`

### Phase A 约束（必须遵守）

1. **只做占位**：业务节点只能返回 `stubbed` 占位结果，或显式
   `raise NotImplementedError`
2. **不碰游戏目录**：不读取、修改、写入 `generated_mods/`
3. **不执行真实写入**：`apply-patch --confirm` 必须返回 `BLOCKED`
4. **测试驱动**：每个新增类/函数必须有对应单元测试
5. **配置驱动**：外部依赖通过 `config/settings.yaml` 配置

### Phase A 验收标准

```bash
python -m src.main plan-request "test"
python -m src.main apply-patch --confirm
pytest tests/unit/test_mod_agent_cli.py
```

### 当前不做

- 不生成真实 Mod 代码
- 不连接真实游戏目录
- 不执行 confirmed apply
- 不声称构建或运行时成功
- 不把 GTFO 写死成唯一目标

## 产品闭环

项目最终追求的闭环是：

```text
自然语言需求
-> 代码库理解
-> 证据判断
-> 可行性分析
-> 实现方案
-> 最小代码变更
-> 构建 / 测试 / 验证
-> 失败诊断
-> 聚焦修复
-> 用户可理解的结果报告
```

RAG 骨架会保留为 Evidence Knowledge Subsystem，用于代码库理解、证据检索、
引用生成、日志分析和历史 artifact 检索。RAG 不负责批准写入、直接 apply
patch、绕过 review gate 或宣称运行成功。
