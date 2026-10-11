"""Input-only references for repeated values in compiled-check observations."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import deepcopy
from os.path import commonprefix

TAG = "$observation_value"
SHORT_TAG = "$v"
TEXT_TAG = "$observation_text"
TABLE = "observation_value_table"
GUIDE = "observation_value_encoding"
VERSION = "inline_observation_values_v1"
TEXT_VERSION = "inline_observation_values_v2"
COMPACT_VERSION = "inline_observation_values_v3"


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _walk(value):
    yield value
    if isinstance(value, dict):
        if any(key in value for key in (TAG, SHORT_TAG, TEXT_TAG)) or any(not isinstance(key, str) for key in value):
            raise ValueError("Reserved reference or unsupported object key")
        for key in sorted(value):
            yield from _walk(value[key])
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def restore_observation_values(feedback):
    """Restore the canonical observation objects without accessing any file/tool."""
    if GUIDE not in feedback:
        return deepcopy(feedback)
    result = deepcopy(feedback)
    guide = result.pop(GUIDE)
    table = result.pop(TABLE)
    if guide.get("version") not in {VERSION, TEXT_VERSION, COMPACT_VERSION} or not isinstance(table, list):
        raise ValueError("Unsupported observation reference encoding")
    reference_key = SHORT_TAG if guide["version"] == COMPACT_VERSION else TAG
    if guide["version"] == COMPACT_VERSION and guide.get("reference_key") != reference_key:
        raise ValueError("Unknown observation reference key")
    values = []

    def decode(value):
        if isinstance(value, dict):
            if reference_key in value:
                index = value[reference_key]
                if set(value) != {reference_key} or type(index) is not int or not 0 <= index < len(values):
                    raise ValueError("Invalid or forward observation value reference")
                return deepcopy(values[index])
            if guide["version"] in {TEXT_VERSION, COMPACT_VERSION} and TEXT_TAG in value:
                if set(value) != {TEXT_TAG} or not isinstance(value[TEXT_TAG], list):
                    raise ValueError("Invalid observation text reference")
                parts = [decode(part) for part in value[TEXT_TAG]]
                if not parts or not all(isinstance(part, str) for part in parts):
                    raise ValueError("Observation text parts must decode to strings")
                return "".join(parts)
            return {key: decode(item) for key, item in value.items()}
        if isinstance(value, list):
            return [decode(item) for item in value]
        return value

    # 为什么要有它：表项只能引用更早的值，禁止循环与前向引用掩盖内容不完整。
    for item in table:
        values.append(decode(item))
    result["observations"] = decode(result["observations"])
    columns = guide.get("columns")
    if columns is not None:
        if (guide["version"] != COMPACT_VERSION or not isinstance(columns, list) or not columns
                or not all(isinstance(key, str) for key in columns) or len(set(columns)) != len(columns)
                or not isinstance(result["observations"], list)
                or any(not isinstance(row, list) or len(row) != len(columns) for row in result["observations"])):
            raise ValueError("Invalid observation columns")
        result["observations"] = [dict(zip(columns, row, strict=True)) for row in result["observations"]]
    digest = hashlib.sha256(_json(result["observations"]).encode("utf-8")).hexdigest()
    if digest != guide.get("original_observations_sha256"):
        raise ValueError("Restored observations differ from original")
    return result


def project_observation_values(feedback):
    """Share exact repeated values; preserve every check and its original order.

    为什么要有它：重复文件快照与执行引用不能挤掉真实失败反馈；引用表内联且可校验还原，不依赖额外模型或工具调用。
    """
    original = deepcopy(feedback)
    rows = original.get("observations")
    if (TABLE in original or GUIDE in original or not isinstance(rows, list) or not rows
            or not all(isinstance(row, dict) and isinstance(row.get("check_id"), str)
                       and {"expected", "observed"} <= row.keys() and not row.get("origin") for row in rows)):
        return original
    try:
        nodes = list(_walk(rows))
        keys = [_json(value) for value in nodes
                if isinstance(value, (dict, list, str)) and len(_json(value).encode("utf-8")) >= 96]
        repeated = {key for key, count in Counter(keys).items() if count > 1}
        groups = {}
        for value in nodes:
            if isinstance(value, str) and len(value) >= 160:
                groups.setdefault(value[:96], set()).add(value)
        prefixes = {}
        for values in groups.values():
            if len(values) >= 3:
                prefix = commonprefix(sorted(values))
                # 为什么要有它：前缀候选不应被任意160字节门槛丢掉；最终按完整编码体积择小，防止反而增大输入。
                if len(prefix.encode("utf-8")) >= 96:
                    prefixes.update({value: prefix for value in values if len(value) > len(prefix)})

        def project(use_prefixes, *, compact=False, columnar=False):
            indices, table = {}, []
            text_references_used = False
            reference_key = SHORT_TAG if compact else TAG
            columns = sorted(rows[0]) if columnar and all(row.keys() == rows[0].keys() for row in rows) else None
            source_rows = [[row[key] for key in columns] for row in rows] if columns is not None else rows

            def shared(value):
                key = _json(value)
                if key not in indices:
                    indices[key] = len(table)
                    table.append(value)
                return {reference_key: indices[key]}

            def encode(value):
                nonlocal text_references_used
                key = _json(value)
                if key in indices:
                    return {reference_key: indices[key]}
                if isinstance(value, dict):
                    rendered = {name: encode(value[name]) for name in sorted(value)}
                elif isinstance(value, list):
                    rendered = [encode(item) for item in value]
                elif isinstance(value, str) and use_prefixes and value in prefixes:
                    prefix = prefixes[value]
                    rendered = {TEXT_TAG: [shared(prefix), value[len(prefix):]]}
                    text_references_used = True
                else:
                    rendered = value
                if key in repeated:
                    indices[key] = len(table)
                    table.append(rendered)
                    return {reference_key: indices[key]}
                return rendered

            projected = deepcopy(original)
            projected["observations"] = encode(source_rows)
            if not table and columns is None:
                return original
            projected[TABLE] = table
            projected[GUIDE] = {
                "version": COMPACT_VERSION if compact else (TEXT_VERSION if text_references_used else VERSION),
                **({"reference_key": reference_key} if compact else {}),
                **({"columns": columns} if columns is not None else {}),
                "original_observations_sha256": hashlib.sha256(_json(rows).encode("utf-8")).hexdigest(),
                "guide": f"Input only: an object containing only {reference_key} replaces that value with the "
                         "0-based entry in observation_value_table. Table entries reference earlier entries only. "
                         "Every check, input, expected and observed value is retained; expand references when reading. "
                         "This does not change check outcomes, source identity or edit authority."
                         + (" An object containing only $observation_text concatenates its list of literal strings "
                            "and string references, in order, to reconstruct the exact original string."
                            if text_references_used else "")
                         + (" observations rows are ordered value arrays: zip each row with columns to recover all "
                            "original field names and values. No check is omitted." if columns is not None else ""),
            }
            return projected if restore_observation_values(projected) == original else original

        # 为什么要有它：共有路径/文本前缀仍须逐字还原；新表示只有更小时采用，不能用删除引用或值换取预算。
        # 为什么要有它：相同检查字段名只需传一次；短引用与列表示均保留版本和完整还原校验，按总字节择小而不删除失败。
        return min((original, project(False), project(True),
                    project(False, compact=True, columnar=True), project(True, compact=True, columnar=True)),
                   key=lambda value: len(_json(value).encode("utf-8")))
    except (KeyError, TypeError, ValueError, RecursionError):
        return original
