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
)

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
_RG_LINE_RE = re.compile(r"^(.*\.cs):(\d+):(.*)$", re.IGNORECASE)
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

    def collect(self, *, query: str, search_root: str | Path) -> EvidencePack:
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

        selected_path, selected_line = _select_file(matches, tokens)
        source = selected_path.read_text(encoding="utf-8")
        lines = source.splitlines()
        start_line = max(1, selected_line - 10)
        end_line = min(len(lines), selected_line + 18)
        excerpt = "\n".join(lines[start_line - 1 : end_line])
        relative = selected_path.relative_to(self.workspace_root).as_posix()
        file_hash = hashlib.sha256(selected_path.read_bytes()).hexdigest()
        evidence_id = "rg_live_" + hashlib.sha256(
            f"{relative}:{file_hash}:{start_line}:{end_line}".encode()
        ).hexdigest()[:16]
        symbol = _best_symbol(excerpt, tokens)
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
        )
        return EvidencePack(
            query=query,
            readiness="sufficient",
            can_generate_patch=True,
            items=(item,),
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
            message="rg plus live file read produced one editable target-source excerpt.",
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


def _select_file(
    matches: list[tuple[Path, int, str]],
    tokens: list[str],
) -> tuple[Path, int]:
    by_path: dict[Path, list[tuple[int, str]]] = {}
    for path, line_number, text in matches:
        by_path.setdefault(path, []).append((line_number, text))
    ranked = sorted(
        by_path.items(),
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
    return path, min(line_number for line_number, _ in path_matches)


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
