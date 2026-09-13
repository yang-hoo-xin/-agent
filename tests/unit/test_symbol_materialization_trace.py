"""Actual local index materialization and explicit fault injection, without models."""
import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pytest

from src.core.trace.execution_trace import ExecutionTrace
from src.mod_agent.evidence import indexed_source
from src.mod_agent.evidence.indexed_source import IndexedSourceEvidenceProvider
from src.mod_agent.upstream_trace import payload_sha256
from src.observability.patch_langfuse_query import join_local_journal, summarize_execution
from src.observability.patch_live_langfuse import (
    OTLP_ENDPOINT, SCORE_ENDPOINT, SYMBOL_CHECK_OPERATION, SYMBOL_CHECK_SCORE_NAME,
    PatchLiveLangfuseSink, build_patch_live_otlp, build_patch_live_scores,
)
from tests.unit.test_upstream_langfuse_query import cloud_row


def _case(tmp_path, *, inline=False, overloaded=False):
    root = tmp_path / "generated_mods" / "Example"
    root.mkdir(parents=True)
    declaration = ["    public void HandleState() {}"] if inline else [
        "    public void HandleState()", "    {", "        // 状态同步", "    }"]
    extra = ["    public void HandleState(int number)", "    {", "        number++;", "    }"] if overloaded else []
    lines = ["namespace PRIVATE_NAMESPACE;", "public sealed class PRIVATE_CLASS", "{", *declaration, *extra,
             "    public void RunAudit()", "    {", "        HandleState();", "        // audit", "    }", "}"]
    source = root / "PRIVATE_SOURCE.cs"
    raw = ("\n".join(lines) + "\n").encode("utf-8")
    source.write_bytes(raw)
    return IndexedSourceEvidenceProvider(tmp_path, tmp_path / "index"), root, source, raw, lines


def _collect(provider, root, query="HandleState audit"):
    return provider.collect_query_set(queries=({"query_id": "q", "query": query, "requirement_id": "r"},),
        search_root=root.relative_to(provider.workspace_root), max_items=1)


def _trace(sink=None):
    rows = {}
    trace = ExecutionTrace("a" * 32, "symbol-test", "test", recorder=lambda row: rows.__setitem__(row["id"], row), sink=sink)
    return trace, rows


def _checks(rows):
    return [row for row in rows.values() if row["name"] == SYMBOL_CHECK_OPERATION]


def _cloud_scores(rows):
    return [{**{key: score[key] for key in ("id", "name", "dataType", "value")},
        "subject": {"kind": "observation", "id": score["observationId"], "traceId": score["traceId"]}}
        for row in rows for score in build_patch_live_scores(row)]


def test_actual_exact_declaration_has_bound_score_and_private_local_query(tmp_path):
    provider, root, source, raw, lines = _case(tmp_path)
    trace, rows = _trace()
    with trace.activate():
        pack = _collect(provider, root)
    exact = next(row for row in _checks(rows) if row["attributes"]["symbol_check_status"] == "exact_declaration")
    assert pack.items[0].method_name == "HandleState" and pack.items[0].span["start_line"] == 4
    assert source.read_bytes() == raw and pack.can_generate_patch is False
    proof = exact["attributes"]["symbol_check"]["checks"][0]
    assert proof["declaration"]["signature"] == lines[3].strip()
    assert proof["source"]["declaration_line"] == lines[3].strip()
    score = build_patch_live_scores(exact)[0]
    assert score["value"] == 1 and score["name"] == SYMBOL_CHECK_SCORE_NAME
    assert score["observationId"] == exact["id"] and score["traceId"] == trace.context.trace_id
    exported = json.dumps([build_patch_live_otlp(row) for row in rows.values()], ensure_ascii=False)
    assert not any(secret in exported for secret in ("PRIVATE", "HandleState", "public void", "状态同步", str(tmp_path)))
    mapped = [dict(cloud_row(row), traceId=trace.context.trace_id) for row in rows.values()]
    queried = summarize_execution(trace.context.trace_id, mapped, _cloud_scores(rows.values()))
    found = next(row for row in queried["symbol_materialization_checks"] if row["observation_id"] == exact["id"])
    assert found["scores"][0]["value"] == 1
    assert found["facts"]["symbol_declaration_checks"][0]["indexed_start_line"] == 4
    journal = tmp_path / "journal.json"
    journal.write_text(json.dumps({"execution_observations": rows}), encoding="utf-8")
    joined = join_local_journal(queried, journal, hashlib.sha256(journal.read_bytes()).hexdigest())
    local = next(row for row in joined["local_evidence"]["observations"] if row["observation_id"] == exact["id"])
    assert local["binding"] == "verified_journal_and_observation_mapping"
    assert local["symbol_check_ref"]["json_pointer"].endswith("/attributes/symbol_check")


@pytest.mark.parametrize("same_name", [False, True], ids=["wrong-method", "same-name-wrong-span"])
def test_known_materialization_mismatch_is_rejected_and_scored_zero(tmp_path, monkeypatch, same_name):
    provider, root, source, raw, lines = _case(tmp_path)
    materialize = indexed_source.materialize_source_location
    wrong_line = lines.index("    public void RunAudit()") + 1

    def wrong_location(**kwargs):
        # Explicitly reproduce the old wrong-method materialization seam. The
        # existing product declaration predicate is untouched and must reject it.
        live = materialize(**{**kwargs, "selected_line": wrong_line})
        return replace(live, method_name="HandleState") if same_name else live

    monkeypatch.setattr(indexed_source, "materialize_source_location", wrong_location)
    trace, rows = _trace()
    with pytest.raises(ValueError, match="INDEXED_SOURCE_SYMBOL_DECLARATION_MISMATCH"), trace.activate():
        _collect(provider, root)
    failed = _checks(rows)[0]
    assert failed["status"] == "failed" and failed["attributes"]["symbol_check_status"] == "declaration_mismatch"
    proof = failed["attributes"]["symbol_check"]["checks"][0]
    assert proof["declaration"]["source_hash"] == proof["materialized"]["source_hash"]  # A matching file hash is insufficient.
    assert proof["materialized"]["span"]["start_line"] == wrong_line != proof["declaration"]["start_line"]
    assert build_patch_live_scores(failed)[0]["value"] == 0
    assert source.read_bytes() == raw
    queried = summarize_execution(trace.context.trace_id,
        [dict(cloud_row(row), traceId=trace.context.trace_id) for row in rows.values()], _cloud_scores(rows.values()))
    assert queried["symbol_materialization_checks"][0]["level"] == "ERROR"
    assert queried["symbol_materialization_checks"][0]["scores"][0]["value"] == 0


@pytest.mark.parametrize("mode", ["window", "bm25", "partial"])
def test_window_bm25_and_partial_materialization_never_emit_success_scores(tmp_path, mode):
    provider, root, _source, _raw, _lines = _case(tmp_path, inline=mode == "window", overloaded=mode == "partial")
    trace, rows = _trace()
    with trace.activate():
        _collect(provider, root, "状态同步" if mode == "bm25" else "HandleState audit")
    checks = _checks(rows)
    expected = {"window": "source_window_unconfirmed", "bm25": "not_applicable", "partial": "partial_selection"}[mode]
    assert any(row["attributes"]["symbol_check_status"] == expected for row in checks)
    assert all(build_patch_live_scores(row) == () for row in checks)


@pytest.mark.parametrize("damage", ["hash", "observation", "status", "unperformed", "source_hash"])
def test_incomplete_or_inconsistent_receipt_cannot_be_promoted_to_a_score(tmp_path, damage):
    provider, root, _source, _raw, _lines = _case(tmp_path)
    trace, rows = _trace()
    with trace.activate():
        _collect(provider, root)
    row = deepcopy(next(item for item in _checks(rows) if item["attributes"]["symbol_check_status"] == "exact_declaration"))
    attrs = row["attributes"]
    receipt = attrs["symbol_check"]
    if damage == "hash":
        attrs["symbol_check_sha256"] = "f" * 64
    elif damage == "observation":
        receipt["observation_id"] = "other"
    elif damage == "status":
        attrs["symbol_check_status"] = receipt["status"] = "unknown"
    elif damage == "unperformed":
        receipt["checks"][0]["declaration_checked"] = False
    else:
        receipt["checks"][0]["materialized"]["source_hash"] = "f" * 64
    if damage != "hash":
        attrs["symbol_check_sha256"] = payload_sha256(receipt)
    assert build_patch_live_scores(row) == ()


def test_sink_failure_preserves_product_outcome_and_existing_score_endpoint(tmp_path):
    class FailingSink:
        def publish(self, _row):
            raise RuntimeError("PRIVATE_SINK_FAILURE")

    provider, root, _source, raw, _lines = _case(tmp_path)
    trace, rows = _trace(FailingSink())
    with trace.activate():
        pack = _collect(provider, root)
    assert pack.items[0].source_hash == hashlib.sha256(raw).hexdigest() and pack.can_generate_patch is False
    assert trace.failure_statistics()["sink"]["total"] > 0
    exact = next(row for row in _checks(rows) if row["attributes"]["symbol_check_status"] == "exact_declaration")

    class Transport:
        def __init__(self):
            self.calls = []

        def _request(self, method, endpoint, *, payload):
            self.calls.append((method, endpoint, payload))
            return {}

    transport = Transport()
    sink = PatchLiveLangfuseSink(transport)
    sink.publish(exact)
    report = sink.shutdown(timeout_millis=2000)
    assert report["score_http_accepted"] == 1
    assert [row[1] for row in transport.calls] == [OTLP_ENDPOINT, SCORE_ENDPOINT]
    assert transport.calls[1][2]["observationId"] == exact["id"]
    assert "PRIVATE" not in json.dumps(transport.calls)
