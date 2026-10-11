"""Shared structural citation admission; semantic faithfulness remains a separate measurement."""
import re

CONTEXT_CITATION = re.compile(r"\[context:(\d+)\]")
INSUFFICIENT_EVIDENCE = "Insufficient evidence in the supplied contexts."


def citation_error(answer, count):
    # 为什么要有它：严格的纯拒答不声称来源事实；要求它引用无关片段反而会制造错误引用，附加事实仍走原引用检查。
    if answer.strip() == INSUFFICIENT_EVIDENCE:
        return None
    numbers = [int(value) for value in CONTEXT_CITATION.findall(answer)]
    if not count and numbers:
        return "CitationWithoutContext", "RAG-off answer invented a retrieved-context citation."
    if count and not numbers:
        return "MissingContextCitation", "RAG-on answer did not cite any retrieved context."
    invalid = sorted({number for number in numbers if not 1 <= number <= count})
    if invalid:
        return "InvalidContextCitation", f"Answer cited unavailable context numbers: {invalid}."
    return None
