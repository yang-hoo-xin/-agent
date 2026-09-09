"""Cold-process CLI output checks with no model or product execution."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_SOURCE_TEXT = "\ufeff// 配置 🧪\n"
_COLD_PROCESS = r'''
import codecs
import json
import sys
from pathlib import Path
from src.mod_agent import cli

assert Path(cli.__file__).resolve() == Path("src/mod_agent/cli.py").resolve()
encoding, outcome, text = sys.argv[1:]
assert codecs.lookup(sys.stdout.encoding).name == codecs.lookup(encoding).name

def run(**kwargs):
    if outcome == "blocked":
        raise ValueError(text)
    result = {"status": "awaiting_approval", "source": text}
    if outcome == "approval":
        result["approval_input"] = kwargs["diff_approval_reader"](
            {"diff_hash": "exact-test-hash", "unified_diff": text}
        )
    return result

cli.run_local_request = run
raise SystemExit(cli.main([
    "run-request", "encoding-only fixture", "--target-project", "unused",
    "--local-ollama",
]))
'''


def _run_cli(encoding: str, outcome: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-B", "-c", _COLD_PROCESS, encoding, outcome, _SOURCE_TEXT],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "PYTHONIOENCODING": f"{encoding}:strict", "PYTHONUTF8": "0"},
        input=b"REJECTED_BY_USER\n",
        capture_output=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize("encoding", ["gbk", "ascii", "utf-8"])
def test_cli_preserves_unicode_result_in_cold_process(encoding: str) -> None:
    result = _run_cli(encoding, "result")

    assert result.returncode == 0, result.stderr.decode("ascii", errors="backslashreplace")
    assert json.loads(result.stdout.decode("utf-8")) == {
        "status": "awaiting_approval",
        "source": _SOURCE_TEXT,
    }
    assert result.stderr == b""


def test_cli_unicode_error_keeps_blocked_exit_code() -> None:
    result = _run_cli("gbk", "blocked")

    assert result.returncode == 2, result.stderr.decode("ascii", errors="backslashreplace")
    assert json.loads(result.stdout.decode("utf-8")) == {
        "status": "BLOCKED",
        "reason": _SOURCE_TEXT,
    }
    assert result.stderr == b""


def test_cli_preserves_unicode_approval_display_and_rejection_input() -> None:
    result = _run_cli("gbk", "approval")

    assert result.returncode == 0, result.stderr.decode("ascii", errors="backslashreplace")
    assert json.loads(result.stdout.decode("utf-8")) == {
        "status": "awaiting_approval",
        "source": _SOURCE_TEXT,
        "approval_input": "REJECTED_BY_USER",
    }
    display, prompt = json.JSONDecoder().raw_decode(result.stderr.decode("utf-8"))
    assert display["unified_diff"] == _SOURCE_TEXT
    assert display["diff_hash"] == "exact-test-hash"
    assert result.stderr.decode("utf-8")[prompt:] == f"{os.linesep}Exact diff hash approval: "


def test_cli_keeps_caller_owned_text_capture_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.mod_agent import cli

    output, errors = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.setattr(sys, "stderr", errors)
    monkeypatch.setattr(
        cli, "run_local_request", lambda **_: {"status": "awaiting_approval", "source": _SOURCE_TEXT}
    )

    exit_code = cli.main([
        "run-request", "encoding-only fixture", "--target-project", "unused", "--local-ollama"
    ])

    assert exit_code == 0
    assert sys.stdout is output and sys.stderr is errors
    assert json.loads(output.getvalue())["source"] == _SOURCE_TEXT
    assert errors.getvalue() == ""
