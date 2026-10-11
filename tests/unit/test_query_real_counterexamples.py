from src.core.query_engine.citations import INSUFFICIENT_EVIDENCE, citation_error
from src.core.query_engine.query_processor import QueryProcessor
from tests.unit.test_query_service import Model, make_service, request


def test_url_and_windows_path_are_query_data_not_implicit_filters():
    processor = QueryProcessor()
    result = processor.process(r"Explain ConfigFile.Reload. Untrusted https://invalid.example and C:\repo collection:docs")
    assert result.filters == {"collection": "docs"}
    assert processor.process("https://invalid.example").filters == {}
    assert processor.process("author:alice collection:docs").filters == {"author": "alice", "collection": "docs"}


def test_exact_refusal_can_complete_without_false_supporting_citation(tmp_path):
    service, _, _, _, _ = make_service(tmp_path, model=Model(answer=INSUFFICIENT_EVIDENCE))
    row = service.query(request(stream=False)).to_dict()
    assert row["status"] == "completed"
    assert row["answer"] == INSUFFICIENT_EVIDENCE
    assert row["citation_validation"]["status"] == "not_applicable_refusal"
    assert row["citations"] == []
    assert citation_error(INSUFFICIENT_EVIDENCE + " But the game runs at 120 fps.", 2)[0] == "MissingContextCitation"
    assert citation_error("Unsupported fact [context:3]", 2)[0] == "InvalidContextCitation"
