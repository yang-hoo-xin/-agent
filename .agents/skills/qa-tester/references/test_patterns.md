# Dashboard and MCP Test Patterns

Read this reference only when the selected QA target is a Dashboard or MCP
surface.

## Dashboard

- Prefer an existing focused AppTest test that reaches the selected page.
  为什么要有它： repository tests preserve current setup and assertions better
  than an improvised script.
- When a new focused AppTest reproduction is necessary, print or assert the
  exact element values involved in the requested behavior. 为什么要有它：
  element counts alone do not establish the displayed semantics.
- Treat Streamlit tab output as a flat rendered result unless the current
  Streamlit API provides an explicit tab relationship. 为什么要有它： content
  found somewhere in the render does not prove where it appeared.
- Do not call destructive Dashboard services against the active checkout. Use
  an isolated test fixture or an explicitly marked isolated checkout.
  为什么要有它：UI verification must not erase current repository data.

The maintained smoke entry point is currently:

```text
python -B -m pytest tests/e2e/test_dashboard_smoke.py -q --tb=short
```

Read that test before selecting a narrower node or assertion. 为什么要有它：
its current imports and fixtures are the exact contract for this repository.

## MCP

- Prefer the maintained protocol tests and select only the cases that cover the
  requested method or failure. 为什么要有它： hand-written protocol sessions
  easily freeze old method names or protocol fields.
- If a subprocess reproduction is necessary, bound its timeout, capture stdout
  and stderr, and terminate it in a `finally` block. 为什么要有它： a failed
  protocol assertion must not leave a server process running.
- Read current server metadata and tests before writing JSON-RPC fields or tool
  names. 为什么要有它： identifiers must come from current source rather than
  this reference.

The maintained MCP test entry points are currently:

```text
python -B -m pytest tests/e2e/test_mcp_client.py -q --tb=short
python -B -m pytest tests/integration/test_mcp_server.py -q --tb=short
```

These commands are examples for the selected surface, not a requirement to run
both. 为什么要有它： the verification set must stay proportional to the user
request.
