"""Single-segment Self-RAG training targets and exact evidence-loss masking.

Token spellings follow https://github.com/AkariAsai/self-rag/blob/main/retrieval_lm/utils.py.
This is a training representation, not a retrieval controller or a quality result.
"""
from __future__ import annotations

import json

REFLECTION_TOKENS = {
    "retrieval": {"retrieve": "[Retrieval]", "no_retrieval": "[No Retrieval]",
                  "continue": "[Continue to Use Evidence]"},
    "relevance": {"relevant": "[Relevant]", "irrelevant": "[Irrelevant]"},
    "support": {"fully_supported": "[Fully supported]", "partially_supported": "[Partially supported]",
                "unsupported": "[No support / Contradictory]"},
    "utility": {str(value): f"[Utility:{value}]" for value in range(1, 6)},
}
PARAGRAPH_TOKENS = ("<paragraph>", "</paragraph>")
ALL_TOKENS = tuple(token for family in REFLECTION_TOKENS.values() for token in family.values()) + PARAGRAPH_TOKENS
SCHEMA = "self_rag_reflection_sample_v1"


def register_reflection_tokens(tokenizer) -> dict[str, int]:
    """Append atomic tokens while retaining the tokenizer's existing special tokens."""
    tokenizer.add_special_tokens({"extra_special_tokens": list(ALL_TOKENS)},
                                 replace_extra_special_tokens=False)
    result = {token: tokenizer.convert_tokens_to_ids(token) for token in ALL_TOKENS}
    if (len(set(result.values())) != len(ALL_TOKENS)
            or any(type(value) is not int or value == tokenizer.unk_token_id for value in result.values())
            or any(tokenizer(token, add_special_tokens=False)["input_ids"] != [value]
                   for token, value in result.items())):
        raise ValueError("SELF_RAG_TOKENS_NOT_ATOMIC")
    return result


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or any(token in value for token in ALL_TOKENS):
        raise ValueError("SELF_RAG_TEXT_INVALID:" + name)
    return value


def reflection_example(sample: dict) -> dict:
    """Render caller-labelled train data; no label generation or hidden-set access."""
    if sample.get("schema_version") != SCHEMA or sample.get("split") != "train":
        raise ValueError("SELF_RAG_LABELLED_TRAIN_SAMPLE_REQUIRED")
    sample_id = _text(sample.get("sample_id"), "sample_id")
    question, answer = (_text(sample.get(key), key) for key in ("question", "answer"))
    _text(sample.get("label_origin"), "label_origin")
    labels = sample.get("labels")
    if not isinstance(labels, dict) or set(labels) != set(REFLECTION_TOKENS):
        raise ValueError("SELF_RAG_FOUR_LABEL_FAMILIES_REQUIRED")
    retrieval = labels["retrieval"]
    utility = labels["utility"]
    if (type(retrieval) is not str or retrieval not in REFLECTION_TOKENS["retrieval"]
            or type(utility) is not int or not 1 <= utility <= 5):
        raise ValueError("SELF_RAG_LABEL_INVALID")
    content = REFLECTION_TOKENS["retrieval"][retrieval]
    prompt = {"question": question}
    if retrieval == "no_retrieval":
        if sample.get("evidence") is not None or labels["relevance"] is not None or labels["support"] is not None:
            raise ValueError("SELF_RAG_NO_RETRIEVAL_HAS_EVIDENCE_LABELS")
    else:
        evidence = _text(sample.get("evidence"), "evidence")
        if (type(labels["relevance"]) is not str or type(labels["support"]) is not str
                or labels["relevance"] not in REFLECTION_TOKENS["relevance"]
                or labels["support"] not in REFLECTION_TOKENS["support"]):
            raise ValueError("SELF_RAG_LABEL_INVALID")
        if retrieval == "continue":
            prompt["previously_available_evidence"] = evidence
        else:
            content += PARAGRAPH_TOKENS[0] + evidence + PARAGRAPH_TOKENS[1]
        content += REFLECTION_TOKENS["relevance"][labels["relevance"]]
    content += answer
    if retrieval != "no_retrieval":
        content += REFLECTION_TOKENS["support"][labels["support"]]
    content += REFLECTION_TOKENS["utility"][str(utility)]
    return {"sample_id": sample_id, "split": "train", "tools": [],
        "prompt": [{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
        "completion": [{"role": "assistant", "content": content}],
        "loss_contract": {"completion_only_loss": True}}


def tokenize_reflection_sample(sample, tokenizer, *, token_ids, max_sequence_length):
    from scripts.run_patch_sft_training import tokenize_completion

    row, proof = tokenize_completion(reflection_example(sample), tokenizer, max_sequence_length=max_sequence_length)
    start, end = (token_ids[token] for token in PARAGRAPH_TOKENS)
    labels = row["labels"]
    inside = False
    masked = 0
    for index in range(proof["prompt_tokens"], len(labels)):
        token = row["input_ids"][index]
        if token == start:
            if inside:
                raise ValueError("SELF_RAG_NESTED_EVIDENCE")
            inside = True
        elif token == end:
            if not inside:
                raise ValueError("SELF_RAG_EVIDENCE_BOUNDARY_INVALID")
            inside = False
        elif inside:
            labels[index] = -100
            masked += 1
    if inside:
        raise ValueError("SELF_RAG_EVIDENCE_BOUNDARY_INVALID")
    # 为什么要有它：检索段落是外部供给的条件，只有反思标签及回答属于生成目标。
    from scripts.run_patch_sft_training import canonical, sha

    supervised = {token: labels.count(token_id) for token, token_id in token_ids.items()}
    proof.update(labels_sha256=sha(canonical(labels)), retrieved_content_tokens_masked=masked,
        reflection_token_supervision=supervised, loss_scope="completion_except_retrieved_paragraph_body")
    return row, proof
