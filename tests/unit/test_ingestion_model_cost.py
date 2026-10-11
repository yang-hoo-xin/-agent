from types import SimpleNamespace

import pytest

from src.core.trace import TraceContext
from src.ingestion.transform.base_transform import measured_model_chat
from src.libs.llm.base_llm import ChatResponse
from src.libs.llm.transport_observation import transport_started


@pytest.mark.parametrize("failed", [False, True])
def test_cost_records_transport_even_when_completion_fails(failed):
    def chat(messages, trace):
        transport_started()
        if failed:
            raise TimeoutError("simulated transport timeout")
        return ChatResponse(content="material", model="test", usage={"total_tokens": 7})

    trace = TraceContext(trace_type="ingestion")
    if failed:
        with pytest.raises(TimeoutError):
            measured_model_chat("refine", SimpleNamespace(chat=chat), [], trace)
    else:
        assert measured_model_chat("refine", SimpleNamespace(chat=chat), [], trace).content == "material"
    row = trace.get_stage_data("refine_model")
    assert row["transport_calls"] == 1
    assert row["status"] == ("failed" if failed else "returned")
    assert row["usage"] == (None if failed else {"total_tokens": 7})


def test_legacy_text_has_unknown_cost_without_changing_result():
    trace = TraceContext(trace_type="ingestion")
    assert measured_model_chat("refine", SimpleNamespace(chat=lambda *a, **kw: "text"), [], trace) == "text"
    row = trace.get_stage_data("refine_model")
    assert row["transport_calls"] == 0 and row["usage"] is None
