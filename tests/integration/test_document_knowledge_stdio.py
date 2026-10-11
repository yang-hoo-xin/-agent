"""Real SDK/client/server/BM25 document evidence; ingestion vectors are offline fakes."""
import json

from src.mod_agent.evidence.models import EvidencePack
from src.mod_agent.evidence.document_knowledge import validate_document_item
from src.mod_agent.evidence.requirement_coverage import is_exact_edit_target_evidence
from src.mod_agent.knowledge_evidence_config import file_ref
from tests.unit.test_document_knowledge import config


def test_real_stdio_document_result_is_source_verified_and_reused_without_another_rpc(tmp_path, monkeypatch):
    from tests.unit.test_incremental_ingestion_correctness import _pipeline_factory
    make, embeddings = _pipeline_factory(tmp_path / "storage", monkeypatch)
    pipeline = make("docs")
    source = tmp_path / "api.md"
    source.write_text("ConfigFile.Reload reads configuration from disk. ConfigReloaded fires after reload.\n", encoding="utf-8")
    inserted = pipeline.run(str(source))
    assert inserted.success and embeddings["docs"].calls
    configuration, _ = config(tmp_path, fingerprint=pipeline.processing_fingerprint,
        sources=[{"source_ref": file_ref(source)}])
    owner, _ = configuration.bind(run_root=tmp_path / "run", run_id="document_test")
    initial = EvidencePack(query="ConfigFile.Reload", readiness="insufficient", can_generate_patch=False)
    first = owner({}, initial)
    assert first.items and not first.can_generate_patch
    assert all(not is_exact_edit_target_evidence(item) for item in first.items)
    assert all(validate_document_item(item)["source_ref"] == file_ref(source) for item in first.items)
    report_path = next((tmp_path / "run/k/m").glob("*/result.json"))
    report = json.loads(report_path.read_bytes())
    assert report["status"] == "completed" and report["stdout_protocol_only"]
    assert report["all_local_processes_exited"] and report["processes"][0]["exit_code"] == 0
    assert report["client_concurrency_scope"] == "same_process_document_sessions_serialized"
    assert report["calls"][0]["response"]["structuredContent"]["usage"]["answer_calls_reserved"] == 0
    assert owner({}, initial).items == first.items
    assert len(list((tmp_path / "run/k/m").iterdir())) == 1
