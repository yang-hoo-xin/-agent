"""Task-specific hidden acceptance for AccurateCrosshair spread toggling.

This is an expected-side compile/IL oracle. It is not a product Harness, Runner,
or gameplay verifier and must remain outside the future Agent source root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import deque
from pathlib import Path
from typing import Any


TASK_ID = "ACCURATE-CROSSHAIR-SPREAD-TOGGLE-001"
SECTION = "General Settings"
TOGGLE_KEY = "Accurate Spread Enabled"
INDEPENDENT_KEYS = (
    "Follow Recoil",
    "First Shot Display Mode",
    "Pop Enabled",
)


class AcceptanceError(ValueError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _run_json(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise AcceptanceError(
            f"INSPECTOR_FAILED:{completed.returncode}:{completed.stderr.strip()}"
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AcceptanceError("INSPECTOR_OUTPUT_INVALID") from exc
    if not isinstance(value, dict):
        raise AcceptanceError("INSPECTOR_OUTPUT_NOT_OBJECT")
    return value


def _load_methods(assembly: Path, inspector: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metadata = _run_json(
        ["dotnet", str(inspector), str(assembly), "--find-metadata", "AccurateCrosshair"]
    )
    methods: list[dict[str, Any]] = []
    seen_tokens: set[str] = set()
    for row in metadata.get("methods", []):
        if not isinstance(row, dict):
            continue
        token = str(row.get("metadata_token") or "")
        symbol = str(row.get("symbol") or "")
        if not token or not symbol or token in seen_tokens or not row.get("has_method_body"):
            continue
        seen_tokens.add(token)
        report = _run_json(
            [
                "dotnet",
                str(inspector),
                str(assembly),
                "--inspect-method-token",
                token,
                symbol,
            ]
        )
        inspected = report.get("methods")
        if isinstance(inspected, list) and len(inspected) == 1 and isinstance(inspected[0], dict):
            methods.append(inspected[0])
    return metadata, methods


def _instructions(method: dict[str, Any]) -> list[dict[str, Any]]:
    value = method.get("instructions")
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _calls(method: dict[str, Any]) -> list[str]:
    return [
        str(row["resolved"])
        for row in _instructions(method)
        if row.get("opcode") in {"call", "callvirt", "newobj"} and row.get("resolved")
    ]


def _method_attributes(method: dict[str, Any]) -> str:
    rows = [
        *list(method.get("custom_attributes") or []),
        *list(method.get("declaring_type_custom_attributes") or []),
    ]
    values: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        values.append(str(row.get("constructor") or ""))
        values.extend(str(value) for value in row.get("printable_ascii_runs", []))
    return " ".join(values)


def _config_binding(methods: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    for method in methods:
        rows = _instructions(method)
        key_indexes = [
            index
            for index, row in enumerate(rows)
            if row.get("opcode") == "ldstr" and row.get("resolved") == key
        ]
        for key_index in key_indexes:
            bind_index = next(
                (
                    index
                    for index in range(key_index + 1, min(len(rows), key_index + 35))
                    if str(rows[index].get("resolved") or "").endswith("ConfigFile.Bind")
                ),
                None,
            )
            if bind_index is None:
                continue
            prior_refs = [
                str(row.get("resolved") or "")
                for row in rows[key_index:bind_index]
                if row.get("opcode") in {"call", "ldsfld"} and row.get("resolved")
            ]
            after = rows[bind_index + 1 : min(len(rows), bind_index + 8)]
            write = next(
                (
                    str(row.get("resolved") or "")
                    for row in after
                    if row.get("opcode") in {"call", "stsfld"} and row.get("resolved")
                    and (
                        ".set_" in str(row.get("resolved"))
                        or row.get("opcode") == "stsfld"
                    )
                ),
                None,
            )
            if write is None:
                continue
            if ".set_" in write:
                read = write.replace(".set_", ".get_", 1)
            else:
                read = write
            if read not in prior_refs:
                continue
            return {
                "key": key,
                "bind_method": method["symbol"],
                "read_member": read,
                "write_member": write,
            }
    return None


def _contains_true_default(methods: list[dict[str, Any]], binding: dict[str, Any]) -> bool:
    targets = {str(binding["write_member"])}
    getter = next(
        (
            method
            for method in methods
            if method.get("symbol") == binding["read_member"]
        ),
        None,
    )
    if getter is not None:
        targets.update(
            str(row["resolved"])
            for row in _instructions(getter)
            if row.get("opcode") == "ldsfld" and row.get("resolved")
        )
    for method in methods:
        if not str(method.get("symbol") or "").endswith("..cctor"):
            continue
        rows = _instructions(method)
        for index, row in enumerate(rows):
            if row.get("resolved") not in targets:
                continue
            window = rows[max(0, index - 5) : index]
            if any(value.get("opcode") == "ldc.i4.1" for value in window):
                return True
    return False


def _reloads_key(methods: list[dict[str, Any]], binding: dict[str, Any]) -> bool:
    for method in methods:
        if method.get("symbol") == binding["bind_method"]:
            continue
        rows = _instructions(method)
        has_key = any(row.get("opcode") == "ldstr" and row.get("resolved") == binding["key"] for row in rows)
        has_write = any(row.get("resolved") == binding["write_member"] for row in rows)
        if has_key and has_write:
            return True
    return False


def _call_graph(methods: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
    by_symbol = {str(method["symbol"]): method for method in methods}
    graph = {
        symbol: {value for value in _calls(method) if value in by_symbol}
        for symbol, method in by_symbol.items()
    }
    return by_symbol, graph


def _closure(start: str, graph: dict[str, set[str]]) -> set[str]:
    result: set[str] = set()
    pending = [start]
    while pending:
        value = pending.pop()
        if value in result:
            continue
        result.add(value)
        pending.extend(sorted(graph.get(value, set()) - result))
    return result


def _offset(value: object) -> int:
    text = str(value or "")
    return int(text.removeprefix("IL_"), 16)


def _local_key(row: dict[str, Any]) -> str | None:
    opcode = str(row.get("opcode") or "")
    if opcode.startswith("stloc.") or opcode.startswith("ldloc."):
        return opcode.split(".", 1)[1]
    if opcode in {"stloc.s", "ldloc.s", "stloc", "ldloc"}:
        return str(row.get("operand"))
    return None


def _toggle_branch(rows: list[dict[str, Any]], read_member: str) -> tuple[int, int, int] | None:
    for read_index, row in enumerate(rows):
        if row.get("opcode") != "call" or row.get("resolved") != read_member:
            continue
        stack: list[tuple[bool, bool]] = [(False, True)]
        locals_: dict[str, tuple[bool, bool]] = {}
        for index in range(read_index + 1, min(len(rows), read_index + 14)):
            current = rows[index]
            opcode = str(current.get("opcode") or "")
            if opcode in {"nop"}:
                continue
            if opcode in {"ldc.i4.0", "ldc.i4.1"}:
                value = opcode.endswith("1")
                stack.append((value, value))
                continue
            local = _local_key(current)
            if opcode.startswith("stloc") and local is not None and stack:
                locals_[local] = stack.pop()
                continue
            if opcode.startswith("ldloc") and local is not None and local in locals_:
                stack.append(locals_[local])
                continue
            if opcode in {"ceq", "cgt.un"} and len(stack) >= 2:
                right = stack.pop()
                left = stack.pop()
                if opcode == "ceq":
                    stack.append((left[0] == right[0], left[1] == right[1]))
                else:
                    stack.append((left[0] != right[0], left[1] != right[1]))
                continue
            if opcode.startswith("brtrue") or opcode.startswith("brfalse"):
                if not stack:
                    break
                condition = stack.pop()
                if condition[0] == condition[1]:
                    continue
                target = _offset(current.get("operand"))
                fallthrough = _offset(rows[index + 1]["offset"])
                branch_on_true = opcode.startswith("brtrue")
                false_start = target if condition[0] == branch_on_true else fallthrough
                true_start = target if condition[1] == branch_on_true else fallthrough
                return index, false_start, true_start
            if opcode in {"conv.i4", "dup"}:
                continue
            break
    return None


def _successors(rows: list[dict[str, Any]], index: int) -> list[int]:
    opcode = str(rows[index].get("opcode") or "")
    if opcode == "ret":
        return []
    if opcode.startswith("br"):
        target_offset = _offset(rows[index].get("operand"))
        targets = [
            position for position, row in enumerate(rows) if _offset(row["offset"]) == target_offset
        ]
        if opcode.startswith("br.s") or opcode == "br":
            return targets
        return [*targets, *([index + 1] if index + 1 < len(rows) else [])]
    return [index + 1] if index + 1 < len(rows) else []


def _path_profile(rows: list[dict[str, Any]], start_offset: int, effect_calls: set[str]) -> dict[str, bool]:
    offsets = {_offset(row["offset"]): index for index, row in enumerate(rows)}
    start = offsets.get(start_offset)
    if start is None:
        return {"effect_reachable": False, "return_reachable": False}
    queue: deque[int] = deque([start])
    seen: set[int] = set()
    effect = False
    returned = False
    while queue:
        index = queue.popleft()
        if index in seen:
            continue
        seen.add(index)
        row = rows[index]
        if row.get("opcode") == "stind.r4" or str(row.get("resolved") or "") in effect_calls:
            effect = True
        if row.get("opcode") == "ret":
            returned = True
        queue.extend(_successors(rows, index))
    return {"effect_reachable": effect, "return_reachable": returned}


def evaluate_assembly(assembly: Path, inspector: Path, build_exit_code: int) -> dict[str, Any]:
    metadata, methods = _load_methods(assembly, inspector)
    by_symbol, graph = _call_graph(methods)
    toggle = _config_binding(methods, TOGGLE_KEY)
    checks: dict[str, Any] = {
        "build_passed": build_exit_code == 0,
        "toggle_binding_present": toggle is not None,
        "toggle_default_true": bool(toggle and _contains_true_default(methods, toggle)),
        "toggle_reload_bound": bool(toggle and _reloads_key(methods, toggle)),
    }
    independent = {key: _config_binding(methods, key) for key in INDEPENDENT_KEYS}
    checks["independent_config_bindings_present"] = all(independent.values())
    checks["independent_config_behavior_present"] = all(
        binding
        and any(
            binding["read_member"] in _calls(method)
            and method.get("symbol") not in {binding["bind_method"]}
            for method in methods
        )
        for binding in independent.values()
    )

    prefix_methods = [
        method
        for method in methods
        if "HarmonyLib.HarmonyPrefix..ctor" in _method_attributes(method)
        and "ShowSpreadCircle" in _method_attributes(method)
    ]
    checks["spread_prefix_found"] = len(prefix_methods) == 1
    spread_detail: dict[str, Any] = {}
    if toggle and len(prefix_methods) == 1:
        prefix_symbol = str(prefix_methods[0]["symbol"])
        prefix_closure = _closure(prefix_symbol, graph)
        sinks = {
            symbol
            for symbol in prefix_closure
            if any(
                str(row.get("resolved") or "").endswith(("get_HipFireSpread", "get_AimSpread"))
                for row in _instructions(by_symbol[symbol])
            )
            and any(row.get("opcode") == "stind.r4" for row in _instructions(by_symbol[symbol]))
        }
        toggle_callers = {
            symbol for symbol, method in by_symbol.items() if toggle["read_member"] in _calls(method)
        }
        config_methods = {
            str(toggle["bind_method"]),
            *{
                str(method["symbol"])
                for method in methods
                if any(row.get("opcode") == "ldstr" and row.get("resolved") == TOGGLE_KEY for row in _instructions(method))
            },
        }
        behavior_toggle_callers = toggle_callers - config_methods
        gate_methods = [
            symbol for symbol in prefix_closure if symbol in behavior_toggle_callers
        ]
        gate_pass = False
        gate_method = None
        for symbol in gate_methods:
            rows = _instructions(by_symbol[symbol])
            branch = _toggle_branch(rows, str(toggle["read_member"]))
            if branch is None:
                continue
            _, false_start, true_start = branch
            effect_calls = sinks - {symbol}
            false_profile = _path_profile(rows, false_start, effect_calls)
            true_profile = _path_profile(rows, true_start, effect_calls)
            if (
                false_profile["return_reachable"]
                and not false_profile["effect_reachable"]
                and true_profile["effect_reachable"]
            ):
                gate_pass = True
                gate_method = symbol
                break
        non_config_toggle_callers_are_spread_only = bool(behavior_toggle_callers) and behavior_toggle_callers.issubset(prefix_closure)
        first_shot = independent.get("First Shot Display Mode")
        first_shot_preserved_before_gate = False
        if gate_method and first_shot:
            rows = _instructions(by_symbol[gate_method])
            toggle_indexes = [
                index for index, row in enumerate(rows) if row.get("resolved") == toggle["read_member"]
            ]
            first_shot_indexes = [
                index for index, row in enumerate(rows) if row.get("resolved") == first_shot["read_member"]
            ]
            first_shot_preserved_before_gate = bool(
                toggle_indexes and first_shot_indexes and min(first_shot_indexes) < min(toggle_indexes)
            )
        checks.update(
            {
                "spread_sink_found": bool(sinks),
                "false_bypasses_spread_override": gate_pass,
                "true_preserves_spread_override": gate_pass,
                "toggle_behavior_scope_is_spread_only": non_config_toggle_callers_are_spread_only,
                "first_shot_path_precedes_toggle_gate": first_shot_preserved_before_gate,
            }
        )
        spread_detail = {
            "prefix_symbol": prefix_symbol,
            "spread_sink_symbols": sorted(sinks),
            "gate_method": gate_method,
            "behavior_toggle_callers": sorted(behavior_toggle_callers),
        }
    else:
        checks.update(
            {
                "spread_sink_found": False,
                "false_bypasses_spread_override": False,
                "true_preserves_spread_override": False,
                "toggle_behavior_scope_is_spread_only": False,
                "first_shot_path_precedes_toggle_gate": False,
            }
        )

    passed = all(checks.values())
    return {
        "task_id": TASK_ID,
        "assembly_sha256": _sha256(assembly),
        "assembly_mvid": metadata.get("module_mvid"),
        "target_code_executed": False,
        "checks": checks,
        "spread_analysis": spread_detail,
        "acceptance_passed": passed,
        "failure_codes": sorted(key for key, value in checks.items() if not value),
        "claim_boundary": {
            "compile_test_preflight_only": True,
            "gameplay_runtime_verified": False,
            "product_delivered": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assembly", required=True, type=Path)
    parser.add_argument("--inspector", required=True, type=Path)
    parser.add_argument("--build-exit-code", required=True, type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate_assembly(
        args.assembly.resolve(),
        args.inspector.resolve(),
        args.build_exit_code,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["acceptance_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
