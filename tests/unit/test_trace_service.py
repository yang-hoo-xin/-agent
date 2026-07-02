"""Tests for TraceService (G5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.observability.dashboard.services.trace_service import TraceService


@pytest.fixture()
def traces_file(tmp_path: Path) -> Path:
    p = tmp_path / "traces.jsonl"
    traces = [
        {
            "trace_id": "t1",
            "trace_type": "ingestion",
            "started_at": "2025-01-01T00:00:00",
            "elapsed_ms": 100.0,
            "stages": [
                {
                    "stage": "load",
                    "elapsed_ms": 20.0,
                    "method": "pdf",
                    "data": {
                        "method": "pdf",
                        "text_preview": "short text",
                    },
                },
                {"stage": "split", "elapsed_ms": 30.0},
                {"stage": "embed", "elapsed_ms": 50.0},
            ],
            "metadata": {"source": "a.pdf"},
        },
        {
            "trace_id": "t2",
            "trace_type": "query",
            "started_at": "2025-01-02T00:00:00",
            "elapsed_ms": 50.0,
            "stages": [
                {"stage": "dense_retrieval", "elapsed_ms": 25.0},
                {"stage": "rerank", "elapsed_ms": 25.0},
            ],
            "metadata": {},
        },
        {
            "trace_id": "t3",
            "trace_type": "ingestion",
            "started_at": "2025-01-03T00:00:00",
            "elapsed_ms": 200.0,
            "stages": [],
            "metadata": {},
        },
    ]
    with p.open("w", encoding="utf-8") as f:
        for t in traces:
            f.write(json.dumps(t) + "\n")
    return p


class TestTraceService:

    def test_list_all(self, traces_file):
        svc = TraceService(traces_file)
        result = svc.list_traces()
        assert len(result) == 3
        # Newest first
        assert result[0]["trace_id"] == "t3"

    def test_list_by_type(self, traces_file):
        svc = TraceService(traces_file)
        ing = svc.list_traces(trace_type="ingestion")
        assert len(ing) == 2
        assert all(t["trace_type"] == "ingestion" for t in ing)

    def test_list_by_type_query(self, traces_file):
        svc = TraceService(traces_file)
        q = svc.list_traces(trace_type="query")
        assert len(q) == 1
        assert q[0]["trace_id"] == "t2"

    def test_list_with_limit(self, traces_file):
        svc = TraceService(traces_file)
        result = svc.list_traces(limit=1)
        assert len(result) == 1

    def test_get_trace_found(self, traces_file):
        svc = TraceService(traces_file)
        t = svc.get_trace("t1")
        assert t is not None
        assert t["trace_id"] == "t1"

    def test_get_trace_not_found(self, traces_file):
        svc = TraceService(traces_file)
        assert svc.get_trace("no_such") is None

    def test_get_stage_timings(self, traces_file):
        svc = TraceService(traces_file)
        t = svc.get_trace("t1")
        timings = svc.get_stage_timings(t)
        assert len(timings) == 3
        assert timings[0]["stage_name"] == "load"
        assert timings[0]["elapsed_ms"] == 20.0
        assert timings[0]["data"]["method"] == "pdf"

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.touch()
        svc = TraceService(p)
        assert svc.list_traces() == []

    def test_missing_file(self, tmp_path):
        svc = TraceService(tmp_path / "nonexistent.jsonl")
        assert svc.list_traces() == []

    def test_malformed_lines_skipped(self, tmp_path):
        p = tmp_path / "bad.jsonl"
        p.write_text('{"trace_id": "ok", "trace_type": "query", "started_at": ""}\nNOT_JSON\n')
        svc = TraceService(p)
        result = svc.list_traces()
        assert len(result) == 1
        assert result[0]["trace_id"] == "ok"

    def test_default_output_redacts_paths_and_sensitive_values(self, tmp_path):
        p = tmp_path / "sensitive.jsonl"
        trace = {
            "trace_id": "sensitive",
            "trace_type": "query",
            "started_at": "2025-01-04T00:00:00",
            "metadata": {
                "query": "find target code",
                "source_path": r"C:\Users\alice\private\design.txt",
                "build_path": "/work/private/build/output.log",
                "api_key": "sk-test-secret",
            },
            "stages": [
                {
                    "stage": "dense_retrieval",
                    "elapsed_ms": 10,
                    "data": {
                        "file_path": r"C:\Users\alice\private\chunk.txt",
                        "authorization": "Bearer secret",
                    },
                }
            ],
        }
        p.write_text(json.dumps(trace) + "\n", encoding="utf-8")

        result = TraceService(p).get_trace("sensitive")

        assert result is not None
        assert result["metadata"]["query"] == "find target code"
        assert result["metadata"]["source_path"] == "[redacted_path:design.txt]"
        assert result["metadata"]["build_path"] == "[redacted_path:output.log]"
        assert result["metadata"]["api_key"] == "[redacted]"
        stage_data = result["stages"][0]["data"]
        assert stage_data["file_path"] == "[redacted_path:chunk.txt]"
        assert stage_data["authorization"] == "[redacted]"

    def test_sensitive_keys_redact_nested_non_string_values(self, tmp_path):
        p = tmp_path / "nested_sensitive.jsonl"
        trace = {
            "trace_id": "nested",
            "trace_type": "query",
            "started_at": "2025-01-04T00:00:00",
            "metadata": {
                "credentials": {
                    "username": "alice",
                    "password": "secret",
                },
                "tokens": ["one", {"nested": "two"}],
            },
            "stages": [
                {
                    "stage": "query_processing",
                    "data": {
                        "secrets": [
                            {"value": "nested"},
                            "plain",
                        ],
                    },
                }
            ],
        }
        p.write_text(json.dumps(trace) + "\n", encoding="utf-8")

        result = TraceService(p).get_trace("nested")

        assert result is not None
        assert result["metadata"]["credentials"] == "[redacted]"
        assert result["metadata"]["tokens"] == "[redacted]"
        assert result["stages"][0]["data"]["secrets"] == "[redacted]"

    def test_default_output_caps_long_text_payloads(self, tmp_path):
        p = tmp_path / "long.jsonl"
        p.write_text(
            json.dumps(
                {
                    "trace_id": "long",
                    "trace_type": "ingestion",
                    "started_at": "2025-01-04T00:00:00",
                    "stages": [
                        {
                            "stage": "load",
                            "elapsed_ms": 10,
                            "data": {"text_preview": "x" * 80},
                        }
                    ],
                    "metadata": {},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        svc = TraceService(p, max_string_chars=40)

        result = svc.get_trace("long")

        assert result is not None
        preview = result["stages"][0]["data"]["text_preview"]
        assert preview == ("x" * 40) + "...[truncated]"

    def test_safe_mode_true_still_returns_redacted_trace_payload(self, tmp_path):
        p = tmp_path / "safe_mode.jsonl"
        trace = {
            "trace_id": "safe",
            "trace_type": "ingestion",
            "started_at": "2025-01-04T00:00:00",
            "metadata": {
                "source_path": r"C:\Users\alice\private\design.txt",
                "token": "raw-token",
            },
            "stages": [],
        }
        p.write_text(json.dumps(trace) + "\n", encoding="utf-8")

        result = TraceService(p, safe_mode=True).get_trace("safe")

        assert result is not None
        assert result["metadata"]["source_path"] == "[redacted_path:design.txt]"
        assert result["metadata"]["token"] == "[redacted]"

    def test_include_raw_returns_raw_trace_payload(self, tmp_path):
        p = tmp_path / "raw.jsonl"
        trace = {
            "trace_id": "raw",
            "trace_type": "ingestion",
            "started_at": "2025-01-04T00:00:00",
            "metadata": {
                "source_path": r"C:\Users\alice\private\design.txt",
                "token": "raw-token",
            },
            "stages": [],
        }
        p.write_text(json.dumps(trace) + "\n", encoding="utf-8")

        result = TraceService(p, include_raw=True).get_trace("raw")

        assert result is not None
        assert result["metadata"]["source_path"] == r"C:\Users\alice\private\design.txt"
        assert result["metadata"]["token"] == "raw-token"

    def test_safe_mode_true_overrides_include_raw_and_stays_redacted(self, tmp_path):
        p = tmp_path / "safe_mode_overrides_raw.jsonl"
        trace = {
            "trace_id": "safe_over_raw",
            "trace_type": "ingestion",
            "started_at": "2025-01-04T00:00:00",
            "metadata": {
                "source_path": r"C:\Users\alice\private\design.txt",
                "token": "raw-token",
            },
            "stages": [],
        }
        p.write_text(json.dumps(trace) + "\n", encoding="utf-8")

        result = TraceService(
            p,
            include_raw=True,
            safe_mode=True,
        ).get_trace("safe_over_raw")

        assert result is not None
        assert result["metadata"]["source_path"] == "[redacted_path:design.txt]"
        assert result["metadata"]["token"] == "[redacted]"
