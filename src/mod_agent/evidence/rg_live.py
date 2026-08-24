"""Minimal live-workspace rg evidence provider for the real V2 slice."""

from __future__ import annotations

import hashlib
import re
import subprocess
import time
from pathlib import Path

from .models import (
    DETERMINISTIC_EVIDENCE_AUTHORITY,
    EvidenceItem,
    EvidencePack,
    missing_evidence_from_blockers,
)

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
_CSHARP_FILENAME_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_.-]*\.cs\b")
_RG_LINE_RE = re.compile(r"^(.*\.cs):(\d+):(.*)$", re.IGNORECASE)
_CSHARP_METHOD_RE = re.compile(
    r"^(?:(?:public|private|protected|internal|static|virtual|override|abstract|"
    r"sealed|async|extern|unsafe|new|partial)\s+)*"
    r"(?P<return_type>[A-Za-z_][A-Za-z0-9_.<>,?\[\]]*)\s+"
    r"(?P<method_name>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"\((?P<parameters>[^)]*)\)\s*(?:\{|=>)?\s*$"
)
_CSHARP_TYPE_RE = re.compile(
    r"^(?:(?:public|private|protected|internal|static|abstract|sealed|partial)\s+)*"
    r"(?:class|struct|record)\s+(?P<type_name>[A-Za-z_][A-Za-z0-9_]*)\b"
)
_CSHARP_FILE_SCOPED_NAMESPACE_RE = re.compile(
    r"^namespace\s+(?P<namespace>[A-Za-z_][A-Za-z0-9_.]*)\s*;\s*$"
)
_CSHARP_BLOCK_NAMESPACE_RE = re.compile(
    r"^namespace\s+(?P<namespace>[A-Za-z_][A-Za-z0-9_.]*)\s*(?:\{|$)"
)
_CSHARP_MEMBER_DECLARATION_RE = re.compile(
    r"^(?:(?:public|private|protected|internal|static|readonly|const|volatile|"
    r"required|new)\s+)*"
    r"(?P<declared_type>[A-Za-z_][A-Za-z0-9_.]*(?:\s*<[^;={}()]+>)?"
    r"(?:\s*\[\s*\])*\??)\s+"
    r"(?P<member_name>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"(?P<declaration_suffix>\{|=|;)"
)
_STOP_WORDS = {
    "and",
    "change",
    "changing",
    "color",
    "make",
    "other",
    "the",
    "this",
    "without",
}


class RgLiveEvidenceProvider:
    """Collect one source-bound live excerpt without maintaining an index."""

    def __init__(self, workspace_root: str | Path, *, rg_executable: str = "rg") -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.rg_executable = rg_executable

    def collect(
        self,
        *,
        query: str,
        search_root: str | Path,
        source_identity_query: str | None = None,
    ) -> EvidencePack:
        started = time.perf_counter()
        root = (self.workspace_root / search_root).resolve()
        try:
            root.relative_to(self.workspace_root)
        except ValueError as exc:
            return EvidencePack.empty(query=query, reason=f"Search root escapes workspace: {exc}")
        if not root.is_dir():
            return EvidencePack.empty(query=query, reason="Configured target source root is missing.")

        tokens = _query_tokens(query)
        if not tokens:
            return EvidencePack.empty(query=query, reason="Request has no usable rg search terms.")
        pattern = "|".join(re.escape(token) for token in tokens)
        command = (
            self.rg_executable,
            "--line-number",
            "--ignore-case",
            "--glob",
            "*.cs",
            "--max-count",
            "80",
            pattern,
            str(root),
        )
        completed = subprocess.run(
            command,
            cwd=self.workspace_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode not in {0, 1}:
            return EvidencePack.empty(
                query=query,
                reason=f"rg failed with exit code {completed.returncode}: {completed.stderr.strip()}",
            )
        matches = _parse_matches(completed.stdout)
        if not matches:
            return EvidencePack.empty(query=query, reason="rg found no live C# source matches.")

        requested_filename = _requested_csharp_filename(
            source_identity_query if source_identity_query is not None else query
        )
        requested_path: Path | None = None
        if requested_filename is not None:
            requested_paths = tuple(
                sorted(
                    (
                        path.resolve()
                        for path in root.rglob("*.cs")
                        if path.name == requested_filename
                    ),
                    key=lambda path: path.as_posix(),
                )
            )
            if len(requested_paths) != 1:
                return EvidencePack.empty(
                    query=query,
                    reason=(
                        "The explicitly requested C# filename did not resolve to "
                        "exactly one current source file. "
                        f"filename={requested_filename!r}; "
                        f"resolved_count={len(requested_paths)}; "
                        "resolved_paths="
                        f"{[path.as_posix() for path in requested_paths]!r}."
                    ),
                )
            requested_path = requested_paths[0]
            if not any(path == requested_path for path, _, _ in matches):
                return EvidencePack.empty(
                    query=query,
                    reason=(
                        "The explicitly requested C# source file contained no "
                        "request-term match."
                    ),
                )
        selected_path, selected_line = _select_file(
            matches,
            tokens,
            requested_path=requested_path,
        )
        source_bytes = selected_path.read_bytes()
        try:
            source = source_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            return EvidencePack.empty(
                query=query,
                reason=f"Selected live C# source is not valid UTF-8: {exc}",
            )
        lines = source.splitlines(keepends=True)
        method_context = _enclosing_csharp_method(lines, selected_line=selected_line)
        start_line = (
            method_context["declaration_line"]
            if method_context is not None
            else max(1, selected_line - 10)
        )
        end_line = min(len(lines), selected_line + 18)
        excerpt = "".join(lines[start_line - 1 : end_line])
        relative = selected_path.relative_to(self.workspace_root).as_posix()
        file_hash = hashlib.sha256(source_bytes).hexdigest()
        evidence_id = "rg_live_" + hashlib.sha256(
            f"{relative}:{file_hash}:{start_line}:{end_line}".encode()
        ).hexdigest()[:16]
        symbol = (
            str(method_context["method_name"])
            if method_context is not None
            else _best_symbol(excerpt, tokens)
        )
        declared_members = (
            _declared_csharp_members(
                lines,
                declaring_type=str(method_context["declaring_type"]),
                declaring_type_full_name=str(
                    method_context["declaring_type_full_name"]
                ),
            )
            if method_context is not None
            and method_context.get("declaring_type") is not None
            and method_context.get("declaring_type_full_name") is not None
            else None
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        item = EvidenceItem(
            evidence_id=evidence_id,
            source_type="target_source",
            source_path=relative,
            symbol=symbol,
            span={"start_line": start_line, "end_line": end_line},
            retrieval_method="rg_live_read",
            score=1.0,
            claim_supported=f"Live source contains request terms near {symbol or relative}.",
            excerpt=excerpt,
            chunk_id=f"live:{relative}:{start_line}:{end_line}",
            document_id=f"live:{relative}",
            source_ref=str(selected_path),
            source_hash=file_hash,
            file_hash=file_hash,
            doc_hash=file_hash,
            authority=DETERMINISTIC_EVIDENCE_AUTHORITY,
            declaring_type=(
                str(method_context["declaring_type"])
                if method_context is not None
                and method_context.get("declaring_type") is not None
                else None
            ),
            method_name=(
                str(method_context["method_name"])
                if method_context is not None
                else None
            ),
            parameter_types=(
                tuple(method_context["parameter_types"])
                if method_context is not None
                and method_context.get("parameter_types") is not None
                else None
            ),
            return_type=(
                str(method_context["return_type"])
                if method_context is not None
                else None
            ),
            method_kind="method" if method_context is not None else None,
            declared_member_types=(
                {
                    name: str(identity["declared_type"])
                    for name, identity in (declared_members or {}).items()
                }
                if declared_members is not None
                else None
            ),
            declaring_type_full_name=(
                str(method_context["declaring_type_full_name"])
                if method_context is not None
                and method_context.get("declaring_type_full_name") is not None
                else None
            ),
            declared_members=declared_members,
        )
        coverage_blocker = {
            "code": "RG_LIVE_REQUIREMENT_COVERAGE_UNPROVEN",
            "message": (
                "Live lexical source observations do not establish explicit, "
                "verifiable requirement coverage."
            ),
            "needed_evidence": [
                "explicit requirement-to-evidence coverage",
            ],
        }
        return EvidencePack(
            query=query,
            readiness="insufficient",
            can_generate_patch=False,
            items=(item,),
            gaps=(
                "Explicit requirement coverage is not established by rg lexical matches.",
            ),
            blockers=(coverage_blocker,),
            missing_evidence=(
                {
                    "needed_evidence": "explicit requirement-to-evidence coverage",
                    "blocker_code": coverage_blocker["code"],
                    "reason": coverage_blocker["message"],
                },
            ),
            retrieval_methods_used=("rg_live_read",),
            disabled_modes={
                "bm25": "Not selected by the completed directional decision.",
                "dense": "Not selected by the completed directional decision.",
                "fusion": "Not selected by the completed directional decision.",
                "rerank": "Not selected by the completed directional decision.",
            },
            timing={
                "query_processing_ms": 0.0,
                "symbol_ms": 0.0,
                "text_ms": elapsed_ms,
                "bm25_ms": 0.0,
                "dense_ms": 0.0,
                "fusion_ms": 0.0,
                "rerank_ms": 0.0,
                "readiness_ms": 0.0,
                "total_ms": elapsed_ms,
                "final_count": 1.0,
                "excluded_count": 0.0,
            },
            message=(
                "rg plus live file read retained one source-authentic lexical "
                "observation; patch authority remains blocked without explicit "
                "requirement coverage."
            ),
        )

    def collect_query_set(
        self,
        *,
        queries: tuple[dict[str, str], ...],
        search_root: str | Path,
        max_items: int,
    ) -> EvidencePack:
        """Run every focused query independently against current live source."""

        if (
            not queries
            or max_items < len(queries)
            or len(queries) > 64
        ):
            raise ValueError("RG_LIVE_QUERY_SET_BUDGET_INVALID")
        seen_query_ids: set[str] = set()
        items: list[EvidenceItem] = []
        item_ids: set[str] = set()
        query_execution: list[dict[str, object]] = []
        total_ms = 0.0
        for query in queries:
            if set(query) != {"query_id", "query", "requirement_id"} or any(
                not isinstance(query.get(key), str) or not query[key].strip()
                for key in ("query_id", "query", "requirement_id")
            ):
                raise ValueError("RG_LIVE_QUERY_SET_ENTRY_INVALID")
            query_id = str(query["query_id"])
            if query_id in seen_query_ids:
                raise ValueError("RG_LIVE_QUERY_SET_ID_DUPLICATE")
            seen_query_ids.add(query_id)
            lane_pack = self.collect(
                query=str(query["query"]),
                search_root=search_root,
            )
            total_ms += float(lane_pack.timing.get("total_ms", 0.0))
            lane_evidence_ids: list[str] = []
            for item in lane_pack.items:
                lane_evidence_ids.append(item.evidence_id)
                if item.evidence_id not in item_ids and len(items) < max_items:
                    items.append(item)
                    item_ids.add(item.evidence_id)
            query_execution.append(
                {
                    "query_id": query_id,
                    "requirement_id": str(query["requirement_id"]),
                    "query_sha256": hashlib.sha256(
                        str(query["query"]).encode("utf-8")
                    ).hexdigest(),
                    "evidence_ids": lane_evidence_ids,
                }
            )
        blocker = {
            "code": "RG_LIVE_REQUIREMENT_COVERAGE_UNPROVEN",
            "message": (
                "Bounded live query execution does not itself establish explicit "
                "requirement coverage."
            ),
            "needed_evidence": ["explicit requirement-to-evidence findings"],
        }
        return EvidencePack(
            query="\n".join(str(query["query"]) for query in queries),
            readiness="insufficient",
            can_generate_patch=False,
            items=tuple(items),
            gaps=("Explicit requirement coverage findings are not yet resolved.",),
            blockers=(blocker,),
            retrieval_methods_used=("rg_live_query_set", "rg_live_read"),
            missing_evidence=missing_evidence_from_blockers((blocker,)),
            disabled_modes={
                "bm25": "Not used by the current live-source query-set owner.",
                "dense": "Dense retrieval is disabled for this ProductExecution path.",
                "fusion": "Fusion is disabled for this ProductExecution path.",
                "rerank": "Reranking is disabled for this ProductExecution path.",
            },
            timing={
                "query_processing_ms": 0.0,
                "symbol_ms": 0.0,
                "text_ms": total_ms,
                "bm25_ms": 0.0,
                "dense_ms": 0.0,
                "fusion_ms": 0.0,
                "rerank_ms": 0.0,
                "readiness_ms": 0.0,
                "total_ms": total_ms,
                "final_count": float(len(items)),
                "excluded_count": 0.0,
            },
            budget_summary={
                "query_count": len(queries),
                "max_items": max_items,
                "per_query_execution": query_execution,
                "all_queries_executed": len(query_execution) == len(queries),
                "dense_enabled": False,
            },
            message=(
                "Every focused query executed against current live source; semantic "
                "coverage remains owned by the requirement coverage projection."
            ),
        )


def _query_tokens(query: str) -> list[str]:
    return list(
        dict.fromkeys(
            token.lower()
            for token in _TOKEN_RE.findall(query)
            if token.lower() not in _STOP_WORDS
        )
    )[:12]


def _parse_matches(raw: str) -> list[tuple[Path, int, str]]:
    matches: list[tuple[Path, int, str]] = []
    for line in raw.splitlines():
        match = _RG_LINE_RE.match(line)
        if match:
            matches.append((Path(match.group(1)).resolve(), int(match.group(2)), match.group(3)))
    return matches


def _requested_csharp_filename(query: str) -> str | None:
    filenames = tuple(dict.fromkeys(_CSHARP_FILENAME_RE.findall(query)))
    return filenames[0] if len(filenames) == 1 else None


def _select_file(
    matches: list[tuple[Path, int, str]],
    tokens: list[str],
    *,
    requested_path: Path | None = None,
) -> tuple[Path, int]:
    by_path: dict[Path, list[tuple[int, str]]] = {}
    for path, line_number, text in matches:
        by_path.setdefault(path, []).append((line_number, text))
    eligible = (
        {
            path: path_matches
            for path, path_matches in by_path.items()
            if path == requested_path
        }
        if requested_path is not None
        else by_path
    )
    ranked = sorted(
        eligible.items(),
        key=lambda item: (
            -sum(
                sum(1 for token in tokens if token in text.lower())
                for _, text in item[1]
            ),
            -len(item[1]),
            item[0].as_posix(),
        ),
    )
    path, path_matches = ranked[0]
    selected_line, _ = sorted(
        path_matches,
        key=lambda match: (
            -sum(1 for token in tokens if token in match[1].lower()),
            min(
                (
                    index
                    for index, token in enumerate(tokens)
                    if token in match[1].lower()
                ),
                default=len(tokens),
            ),
            match[0],
        ),
    )[0]
    return path, selected_line


def _best_symbol(excerpt: str, tokens: list[str]) -> str | None:
    identifiers = _TOKEN_RE.findall(excerpt)
    scored = sorted(
        identifiers,
        key=lambda identifier: (
            -sum(
                1
                for token in tokens
                if token in identifier.lower() or identifier.lower() in token
            ),
            identifiers.index(identifier),
        ),
    )
    if scored and any(
        token in scored[0].lower() or scored[0].lower() in token for token in tokens
    ):
        return scored[0]
    return identifiers[0] if identifiers else None


def _enclosing_csharp_method(
    lines: list[str],
    *,
    selected_line: int,
) -> dict[str, object] | None:
    """Return the nearest preceding C# method declaration for one selected line."""

    for index in range(min(selected_line, len(lines)) - 1, -1, -1):
        declaration = lines[index].strip()
        match = _CSHARP_METHOD_RE.fullmatch(declaration)
        if match is None:
            continue
        parameters = match.group("parameters").strip()
        declaring_type = _nearest_csharp_type(lines, before_line=index + 1)
        namespace = _nearest_csharp_namespace(lines, before_line=index + 1)
        declaring_type_full_name = (
            f"{namespace}.{declaring_type}"
            if namespace is not None and declaring_type is not None
            else declaring_type
        )
        return {
            "declaration_line": index + 1,
            "declaring_type": declaring_type,
            "declaring_type_full_name": declaring_type_full_name,
            "method_name": match.group("method_name"),
            "parameter_types": () if not parameters else None,
            "return_type": match.group("return_type"),
        }
    return None


def _csharp_method_source_spans(lines: list[str]) -> tuple[dict[str, object], ...]:
    """Return non-overlapping complete C# method source spans."""

    spans: list[dict[str, object]] = []
    occupied_through = 0
    for index, line in enumerate(lines):
        if index + 1 <= occupied_through:
            continue
        match = _CSHARP_METHOD_RE.fullmatch(line.strip())
        if match is None or "=>" in line:
            continue
        depth = 0
        entered_body = False
        lexical_state = "code"
        end_line: int | None = None
        for body_index in range(index, len(lines)):
            brace_delta, lexical_state = _csharp_brace_delta(
                lines[body_index],
                initial_state=lexical_state,
            )
            depth += brace_delta
            if depth > 0:
                entered_body = True
            elif entered_body:
                end_line = body_index + 1
                break
        if end_line is None:
            continue
        start_line = index + 1
        spans.append(
            {
                "method_name": match.group("method_name"),
                "start_line": start_line,
                "end_line": end_line,
                "source_text": "".join(lines[index:end_line]),
            }
        )
        occupied_through = end_line
    return tuple(spans)


def _nearest_csharp_type(lines: list[str], *, before_line: int) -> str | None:
    for index in range(min(before_line, len(lines)) - 1, -1, -1):
        match = _CSHARP_TYPE_RE.match(lines[index].strip())
        if match is not None:
            return match.group("type_name")
    return None


def _nearest_csharp_namespace(lines: list[str], *, before_line: int) -> str | None:
    for index in range(min(before_line, len(lines)) - 1, -1, -1):
        value = lines[index].strip()
        match = _CSHARP_FILE_SCOPED_NAMESPACE_RE.match(value)
        if match is None:
            match = _CSHARP_BLOCK_NAMESPACE_RE.match(value)
        if match is not None:
            return match.group("namespace")
    return None


def _declared_csharp_member_types(
    lines: list[str],
    *,
    declaring_type: str,
) -> dict[str, str]:
    """Extract exact field/property types at one containing C# type level."""

    namespace = _nearest_csharp_namespace(lines, before_line=len(lines))
    declaring_type_full_name = (
        f"{namespace}.{declaring_type}" if namespace is not None else declaring_type
    )
    return {
        name: str(identity["declared_type"])
        for name, identity in _declared_csharp_members(
            lines,
            declaring_type=declaring_type,
            declaring_type_full_name=declaring_type_full_name,
        ).items()
    }


def _declared_csharp_members(
    lines: list[str],
    *,
    declaring_type: str,
    declaring_type_full_name: str,
) -> dict[str, dict[str, object]]:
    """Extract source-bound class-level member declarations for one C# type."""

    declaration_index: int | None = None
    for index, line in enumerate(lines):
        match = _CSHARP_TYPE_RE.match(line.strip())
        if match is not None and match.group("type_name") == declaring_type:
            declaration_index = index
            break
    if declaration_index is None:
        return {}

    members: dict[str, dict[str, object]] = {}
    brace_depth = 0
    entered_type = False
    lexical_state = "code"
    for line_index, line in enumerate(
        lines[declaration_index:],
        start=declaration_index + 1,
    ):
        if entered_type and brace_depth == 1:
            match = _CSHARP_MEMBER_DECLARATION_RE.match(line.strip())
            if match is not None:
                member_name = match.group("member_name")
                declared_type = re.sub(r"\s+", "", match.group("declared_type"))
                identity = {
                    "member_name": member_name,
                    "member_kind": (
                        "property"
                        if match.group("declaration_suffix") == "{"
                        else "field"
                    ),
                    "declared_type": declared_type,
                    "declaring_type": declaring_type_full_name,
                    "declaration_span": {
                        "start_line": line_index,
                        "end_line": line_index,
                    },
                    "is_static": bool(
                        re.search(
                            r"\bstatic\b",
                            line.strip()[: match.start("declared_type")],
                        )
                    ),
                }
                previous = members.get(member_name)
                if previous is None or previous == identity:
                    members[member_name] = identity
                else:
                    members.pop(member_name, None)
        brace_delta, lexical_state = _csharp_brace_delta(
            line,
            initial_state=lexical_state,
        )
        brace_depth += brace_delta
        if brace_depth > 0:
            entered_type = True
        elif entered_type:
            break
    return dict(sorted(members.items()))


def _csharp_brace_delta(
    value: str,
    *,
    initial_state: str,
) -> tuple[int, str]:
    """Count structural braces while ignoring C# comments and string literals."""

    delta = 0
    index = 0
    state = initial_state
    while index < len(value):
        current = value[index]
        following = value[index + 1] if index + 1 < len(value) else ""
        if state == "code":
            if current == "/" and following == "/":
                break
            if current == "/" and following == "*":
                state = "block_comment"
                index += 2
                continue
            if current == '"':
                state = "verbatim_string" if index > 0 and value[index - 1] == "@" else "string"
                index += 1
                continue
            if current == "'":
                state = "character"
                index += 1
                continue
            if current == "{":
                delta += 1
            elif current == "}":
                delta -= 1
            index += 1
            continue
        if state == "block_comment":
            if current == "*" and following == "/":
                state = "code"
                index += 2
            else:
                index += 1
            continue
        if state == "verbatim_string":
            if current == '"' and following == '"':
                index += 2
            elif current == '"':
                state = "code"
                index += 1
            else:
                index += 1
            continue
        if current == "\\":
            index += 2
            continue
        if (state == "string" and current == '"') or (
            state == "character" and current == "'"
        ):
            state = "code"
        index += 1
    return delta, state
