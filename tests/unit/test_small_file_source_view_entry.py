"""The public owner and a restarted Findings stage keep the same source view."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from src.mod_agent.evidence import source_view
from src.mod_agent.evidence.rg_live import RgLiveEvidenceProvider
from src.mod_agent.initial_findings_continuation import prepare_initial_findings_continuation
from tests.unit.test_dsh_run_request import _call, _install_execution_boundaries
from tests.unit.test_dsh_run_request import execution_config as execution_config  # noqa: F401
from tests.unit.test_initial_findings_continuation import _failed_run


def _observe_constructors(monkeypatch):
    calls = []
    original = RgLiveEvidenceProvider.__init__

    def create(self, workspace_root, **kwargs):
        original(self, workspace_root, **kwargs)
        calls.append((Path(workspace_root), self.small_file_max_bytes))

    monkeypatch.setattr(RgLiveEvidenceProvider, "__init__", create)
    return calls


def test_normal_entry_records_the_actual_default_source_view(execution_config, monkeypatch, capsys):
    _install_execution_boundaries(execution_config.parent, monkeypatch)
    providers = _observe_constructors(monkeypatch)
    assert _call(execution_config, "make Load record deterministic product diagnostics", monkeypatch) == 0
    result = json.loads(capsys.readouterr().out)
    root = Path(result["run_root"])
    manifest = json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))
    policy = source_view.source_view_policy(8192)
    assert providers and all(limit == 8192 for _, limit in providers)
    assert result["source_view_policy"] == manifest["source_view_policy"] == policy
    spans = [value for value in manifest["execution_observations"].values()
             if value["name"] == "evidence.source_query"]
    assert spans
    for span in spans:
        refs = span["attributes"]["local_detail_refs"]
        request = json.loads(Path(refs["request"]["path"]).read_bytes())
        response = json.loads(Path(refs["response"]["path"]).read_bytes())
        assert request["source_view_policy"] == response["budget_summary"]["source_view_policy"] == policy
        for item in response["items"]:
            assert item["method_name"] is None


@pytest.mark.parametrize("saved_limit", [None, 8192], ids=["legacy-absent", "whole-file"])
def test_findings_preparation_restores_manifest_policy_without_new_calls(
    execution_config, monkeypatch, capsys, saved_limit,
):
    # Construct a controlled old/new run; only test-owned history is adjusted below.
    monkeypatch.setattr(source_view, "NORMAL_RUN_SMALL_FILE_MAX_BYTES", saved_limit or 0)
    providers = _observe_constructors(monkeypatch)
    result, posts = _failed_run(execution_config, monkeypatch, capsys)
    root = Path(result["run_root"])
    path = root / "run_manifest.json"
    manifest = json.loads(path.read_bytes())
    if saved_limit is None:
        del manifest["source_view_policy"]
        path.write_text(json.dumps(manifest), encoding="utf-8")
    prior = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    providers.clear()
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda *_: pytest.fail("Preparation invoked HTTP"))
    prepared = prepare_initial_findings_continuation(run_root=root, run_id=result["run_id"],
        execution_config=execution_config)
    assert prepared["model_calls_performed"] == 0 and len(posts) == 2
    assert providers and all(limit == (saved_limit or 0) for _, limit in providers)
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == prior
