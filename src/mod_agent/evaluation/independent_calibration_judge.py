"""Read-only behavioral judging of PUBLIC engineering calibration programs.

No submitted Python is executed. This small interpreter is intentionally limited
to numeric functions; it is not a sandbox for general Python or a Mod verifier.
"""
from __future__ import annotations

import ast
import operator

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
       ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}
CALLS = {"min": min, "max": max, "abs": abs}
ALLOWED = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.If,
           ast.Expr, ast.Constant, ast.Name, ast.Load, ast.BinOp, ast.UnaryOp,
           ast.USub, ast.UAdd, ast.Compare, ast.Call, ast.IfExp, *OPS)


class UnsupportedProgramError(ValueError):
    pass


def _parse(source):
    if not isinstance(source, str) or len(source.encode()) > 16384:
        raise UnsupportedProgramError("source_size_or_type")
    tree = ast.parse(source)
    compile(tree, "<public-calibration>", "exec")  # Syntax only; never exec/eval.
    nodes = list(ast.walk(tree))
    if len(nodes) > 512 or any(not isinstance(node, ALLOWED) for node in nodes):
        raise UnsupportedProgramError("outside_numeric_calibration_language")
    functions = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name in functions:
            raise UnsupportedProgramError("unique_functions_required")
        if (node.decorator_list or node.returns or node.args.defaults or node.args.kw_defaults
                or node.args.kwonlyargs or node.args.vararg or node.args.kwarg
                or node.args.posonlyargs or any(a.annotation for a in node.args.args)):
            raise UnsupportedProgramError("plain_positional_functions_required")
        functions[node.name] = node
    for node in nodes:
        if isinstance(node, ast.Constant) and (type(node.value) not in (int, float)
                                              or abs(node.value) > 1e12):
            raise UnsupportedProgramError("bounded_numeric_constants_required")
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Name)
                or node.func.id not in CALLS or node.keywords or not 1 <= len(node.args) <= 3):
            raise UnsupportedProgramError("only_min_max_abs_calls")
    return functions


def _expr(node, values):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return values[node.id]
    if isinstance(node, ast.BinOp):
        return OPS[type(node.op)](_expr(node.left, values), _expr(node.right, values))
    if isinstance(node, ast.UnaryOp):
        return (-1 if isinstance(node.op, ast.USub) else 1) * _expr(node.operand, values)
    if isinstance(node, ast.Call):
        return CALLS[node.func.id](*[_expr(arg, values) for arg in node.args])
    if isinstance(node, ast.Compare):
        left = _expr(node.left, values)
        for op, right in zip(node.ops, node.comparators, strict=True):
            right = _expr(right, values)
            if not OPS[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _expr(node.body if _expr(node.test, values) else node.orelse, values)
    raise UnsupportedProgramError("unsupported_expression")


def _body(nodes, values):
    for node in nodes:
        if isinstance(node, ast.Return):
            return True, _expr(node.value, values)
        if isinstance(node, ast.If):
            returned, value = _body(node.body if _expr(node.test, values) else node.orelse, values)
            if returned:
                return returned, value
        else:
            raise UnsupportedProgramError("unsupported_statement")
    return False, None


def judge(*, source, public_task, action):
    """Public requirements are passed by the coordinator, never by the strategy."""
    result = {"compilation": "not_run", "behavior": "not_evaluated",
              "outcome": "insufficient_observation", "task_success": None, "checks": []}
    if action not in {"submit", "no_change", "stop"}:
        return {**result, "outcome": "execution_error", "reason": "invalid_action"}
    if public_task["required_action"] == "stop":
        return {**result, "outcome": "correct_stop" if action == "stop" else "incorrect_continue",
                "task_success": action == "stop"}
    if action == "stop":
        return {**result, "outcome": "incorrect_abandonment", "task_success": False}
    try:
        functions = _parse(source)
    except (SyntaxError, TypeError) as exc:
        return {**result, "compilation": "failed", "outcome": "compilation_failed",
                "task_success": False, "reason": type(exc).__name__}
    except (UnsupportedProgramError, RecursionError) as exc:
        return {**result, "reason": str(exc)}
    result["compilation"] = "passed"
    if not public_task["checks"]:
        return result
    for check in public_task["checks"]:
        try:
            function = functions[check["function"]]
            values = dict(zip((a.arg for a in function.args.args), check["arguments"], strict=True))
            returned, actual = _body(function.body, values)
            passed = returned and actual == check["expected"]
        except UnsupportedProgramError as exc:
            return {**result, "reason": str(exc)}
        except (KeyError, ValueError, TypeError, OverflowError, RecursionError):
            actual, passed = None, False
        result["checks"].append({"check_id": check["check_id"], "kind": check["kind"],
                                 "passed": passed, "actual": actual})
    success = all(row["passed"] for row in result["checks"])
    return {**result, "behavior": "passed" if success else "failed",
            "outcome": "success" if success else "behavior_failed", "task_success": success}

