---
name: qa-tester
description: Run explicitly requested repository QA for user flows, integration, Dashboard, MCP, or compound scenarios. Use focused-python-verification for ordinary Python implementation and bug fixes verified by pytest.
---

# QA Tester

`qa-tester` 仅作为验收执行参考，以本轮完整组合目标决定覆盖范围。复用其中仍适用的方法，核对现有测试的实际断言，补齐真实入口、模型、组件组合、性能与异常验证；沿用已有授权，不恢复旧版强制串行、强制报表或重复审批。
为什么要有它：技能应帮助完成验收，不能成为压缩任务范围或增加流程等待的依据。

Choose sufficient checks for the full user-selected acceptance boundary. For
ordinary Python implementation or bug fixes, use focused-python-verification;
select this skill when acceptance concerns the broader user flow or an explicit
QA scenario.
为什么要有它：两个skill按验收对象分工，避免同一次局部修复重复加载和执行验证流程。

## Select the target

1. Read the user's requested behavior and the current source or test that owns
   it. 为什么要有它： current owners and interfaces can differ from historical
   QA plans.
2. For diagnosis, start with the exact failing command or smallest relevant test
   selection; this is a starting point, not the complete acceptance scope.
   为什么要有它： a focused failure preserves the signal needed to diagnose
   one behavior.
3. Cover every part of the current requested acceptance boundary. Beyond that
   scope, expand or repeat testing when a relevant change, failure, or unresolved
   concern identifies a wider affected boundary. 为什么要有它： verification
   must satisfy the full request, while additional runs should follow evidence
   rather than a fixed run count.

There is no required `QA_TEST_PLAN.md` or `QA_TEST_PROGRESS.md`. Use either file
only when the user supplies it for the current task. 为什么要有它： neither
file is part of the current repository contract.

## Execute and assess

- Record the exact command, exit status, and the relevant original output.
  为什么要有它： a pass claim needs current-run evidence rather than source
  inspection alone.
- Compare the observed result with the requested behavior and every assertion
  in the selected test. 为什么要有它： an exit code alone may miss a semantic
  failure.
- If the selected check fails and the user requested a fix, repair the verified
  owner and rerun the affected selection. 为什么要有它： the next action
  should respond to the observed failure rather than a preset retry budget.
- Reuse evidence only when it is bound to the same behavior, revision, and
  environment; state that binding. 为什么要有它： precise reuse avoids both
  redundant runs and unsupported cross-test claims.
- Stop when the user-selected acceptance boundary is demonstrated.
  为什么要有它：more tests do not strengthen a claim once its affected boundary is
  covered.

For Dashboard or MCP-specific mechanics, read
[references/test_patterns.md](references/test_patterns.md) only when that
surface is selected. 为什么要有它： those details are irrelevant to ordinary
unit or CLI checks.

## State-changing helpers

The helpers under `scripts/` are optional tools for legacy compound scenarios.
They are not the default QA entry point.

- `qa_bootstrap.py`, `qa_config.py`, and `qa_multistep.py` require
  `--target-repo` pointing to an independent checkout that contains a
  `.qa-isolated-target` marker. 为什么要有它： these helpers clear data or
  change configuration and must not target the active checkout.
- The marker and path checks are local guards, not an operating-system sandbox.
  Inspect the target before use. 为什么要有它： filesystem aliases or external
  processes can still change state outside the helper's knowledge.
- Do not run Provider or network-backed checks without the authorization and
  credentials required for that exact run. 为什么要有它： a QA request does
  not itself authorize external calls.
- `qa_validate_notes.py <progress.md>` checks PASS/FAIL/SKIP result rows (also
  ✅/❌/⏭️). It rejects missing files, empty result tables, duplicate IDs or empty
  fields. 为什么要有它：失败和跳过也是合法记录；表格完整仍不证明命令执行过。

Report the selected scope, commands, results, fixes, and any untested boundary.
为什么要有它： the user needs to know exactly what the QA result establishes.
