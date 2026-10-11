"""Run a declared set of retained local chat requests once, without tool dispatch.

为什么要有它：先用同模型的原始请求对照检验输入假设，复用现有transport和记录，避免每次复制产品runner。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.libs.llm.agent_turn import _LoopbackHttpJsonSender, validate_loopback_http_base_url  # noqa: E402
from src.libs.llm.transport_observation import observe_transport  # noqa: E402
from src.mod_agent import model_admission  # noqa: E402
from src.mod_agent.model_qualification import read_bound_json  # noqa: E402


def ref(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
    return ref(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    plan_ref = ref(args.plan)
    plan = read_bound_json(plan_ref)
    endpoint = validate_loopback_http_base_url(plan["base_url"])
    requests = [(item["label"], read_bound_json(item["request_ref"])) for item in plan["requests"]]
    if not requests or len({label for label, _ in requests}) != len(requests):
        raise ValueError("PROBE_REQUEST_LABELS_INVALID")
    for label, body in requests:
        if not label or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in label):
            raise ValueError("PROBE_LABEL_INVALID")
        if body.get("model") != plan["model"] or body.get("stream") is not False:
            raise ValueError("PROBE_MODEL_OR_STREAM_CHANGED")
    if not args.execute:
        print(json.dumps({"plan_ref": plan_ref, "requests": len(requests), "model_calls": 0}))
        return
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    before = model_admission.read_ollama_model_identity(endpoint, plan["model"])
    model_admission.validate_ollama_model_identity(before, expected_base_url=endpoint, expected_model=plan["model"])
    if before["digest"] != plan["model_digest"]:
        raise ValueError("PROBE_MODEL_DIGEST_CHANGED")
    source_refs = [ref(__file__), ref(Path(__file__).resolve().parents[1] / "src/libs/llm/agent_turn.py")]
    save(root / "started.json", {"plan_ref": plan_ref, "model_identity": before, "source_refs": source_refs})
    sender = _LoopbackHttpJsonSender(timeout_seconds=plan["timeout_seconds"])
    rows = []
    for label, body in requests:
        cell = root / label
        cell.mkdir()
        row = {"label": label, "input_ref": save(cell / "input.json", body), "transport_attempts": 0}
        def sent():
            row["transport_attempts"] += 1
        def wire(raw):
            with (cell / "wire.json").open("xb") as stream:
                stream.write(raw)
            row["wire_ref"] = ref(cell / "wire.json")
        started = time.perf_counter()
        try:
            with observe_transport(sent, local_request_body_callback=wire):
                response = sender(endpoint + "/api/chat", body, {})
            row["response_ref"] = save(cell / "response.json", response)
            row.update(status="returned", input_tokens=response.get("prompt_eval_count"),
                       output_tokens=response.get("eval_count"), done_reason=response.get("done_reason"))
        except Exception as error:
            row.update(status="failed", error={"type": type(error).__name__, "message": str(error)})
        row["seconds"] = time.perf_counter() - started
        rows.append({**row, "record_ref": save(cell / "record.json", row)})
    after = model_admission.read_ollama_model_identity(endpoint, plan["model"])
    model_admission.assert_ollama_model_identity_stable(expected=before, observed=after)
    assert all(ref(r["path"])["sha256"] == r["sha256"] for r in source_refs)
    result = save(root / "result.json", {"scope": "Single-turn local input diagnostic, no tool dispatch, Build or Apply; not product delivery.",
        "plan_ref": plan_ref, "model_before": before, "model_after": after, "source_refs": source_refs, "rows": rows})
    print(json.dumps(result))


if __name__ == "__main__":
    main()
