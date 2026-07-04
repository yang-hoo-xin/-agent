"""Shared deterministic tokenization for retrieval paths."""

from __future__ import annotations

import re

import jieba

_CODE_LIKE_TERM_RE = re.compile(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*")


def tokenize_retrieval_text(
    text: str,
    *,
    lowercase: bool = False,
    min_token_length: int = 1,
) -> list[str]:
    """Tokenize text while preserving code-like terms across query and sparse paths.

    jieba is a mandatory project dependency; environments without it should use
    the project virtualenv instead of silently changing Chinese tokenization.
    """

    tokens: list[str] = []
    protected_matches = list(_CODE_LIKE_TERM_RE.finditer(text))
    masked_parts: list[str] = []
    last = 0
    for match in protected_matches:
        start, end = match.span()
        masked_parts.append(text[last:start])
        masked_parts.append(" " * (end - start))
        last = end
        tokens.append(match.group(0))
    masked_parts.append(text[last:])

    masked_text = "".join(masked_parts)
    for token in jieba.lcut(masked_text):
        token = token.strip()
        if not token:
            continue
        if re.fullmatch(r"[\s\W]+", token, re.UNICODE):
            continue
        tokens.append(token)

    if lowercase:
        tokens = [token.lower() for token in tokens]
    return [token for token in tokens if len(token) >= min_token_length]
