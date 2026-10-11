"""Bound anonymous context by already parsed complete adjacent method spans."""
from __future__ import annotations

from collections.abc import Mapping, Sequence


def fallback_source_window(*, selected_line: int, line_count: int,
                           method_spans: Sequence[Mapping[str, object]] = ()) -> tuple[int, int]:
    """Keep the match and its non-method neighborhood without claiming an identity.

    为什么要有它：匿名窗口带入相邻方法的半个声明会制造读取单位重叠；不完整解析不能据此取得编辑权限。
    """
    original = (max(1, selected_line - 10), min(line_count, selected_line + 18))
    spans = []
    for span in method_spans:
        start, end = span.get("start_line"), span.get("end_line")
        if type(start) is not int or type(end) is not int or not 1 <= start <= end <= line_count:
            return original
        if start <= selected_line <= end:
            # A known method contains this match even if its richer identity was
            # unavailable. 为什么要有它：不能把方法内部的未知片段假装成方法外区域并裁掉上下文。
            return original
        spans.append((start, end))
    start, end = original
    for method_start, method_end in spans:
        if method_end < selected_line:
            start = max(start, method_end + 1)
        elif method_start > selected_line:
            end = min(end, method_start - 1)
    return start, end
