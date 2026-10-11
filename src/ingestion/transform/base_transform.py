"""Base class for chunk transform operations."""

from abc import ABC, abstractmethod
import time
import threading
from typing import List, Optional

from src.core.types import Chunk
from src.core.trace.trace_context import TraceContext


def measured_model_chat(operation, llm, messages, trace):
    """Keep native model cost separate from nested chunk/transform wall time.

    为什么要有它：并发增强的完成次数不能替代真实传输、Token 和失败成本。
    """
    from src.libs.llm.transport_observation import observe_transport
    from src.libs.llm.base_llm import ChatResponse
    from src.observability.evaluation.answer_generation import observed_usage

    started = time.perf_counter()
    response = None
    observation = {"transport_calls": 0, "status": "failed"}

    def sent():
        observation["transport_calls"] += 1

    def prepared(**facts):
        observation.update(facts)

    try:
        with observe_transport(sent, request_callback=prepared):
            response = llm.chat(messages, trace=trace)
        observation["status"] = "returned"
        return response
    finally:
        if trace is not None:
            observation["usage"] = observed_usage(response) if isinstance(response, ChatResponse) else None
            observation["model"] = response.model if isinstance(response, ChatResponse) else None
            trace.record_stage(operation + "_model", observation,
                               elapsed_ms=(time.perf_counter() - started) * 1000)


def measured_chunk_call(operation, function, chunk, trace):
    started = time.perf_counter()
    result = None
    try:
        result = function(chunk, trace)
        return result
    finally:
        ended = time.perf_counter()
        if trace is not None:
            trace.record_stage(operation + ":" + chunk.id, {
                "chunk_id": chunk.id, "worker_thread": threading.get_ident(),
                "started_monotonic": started, "finished_monotonic": ended,
                "outcome": result[1] if result is not None else "failed",
                "error": result[2] if result is not None else "raised"}, elapsed_ms=(ended - started) * 1000)


class BaseTransform(ABC):
    """Abstract base class for chunk transformation operations.
    
    Transform operations process chunks to enhance their quality, add metadata,
    or prepare them for downstream processing (embedding, indexing).
    
    Design Principles:
        - Single Responsibility: Each transform does ONE type of enhancement
        - Atomic Operations: Failure in one chunk doesn't affect others
        - Observable: Records processing info in TraceContext
        - Graceful Degradation: Returns original chunk on unrecoverable errors
    """
    
    @abstractmethod
    def transform(
        self,
        chunks: List[Chunk],
        trace: Optional[TraceContext] = None
    ) -> List[Chunk]:
        """Transform a list of chunks.
        
        Args:
            chunks: List of chunks to transform
            trace: Optional trace context for observability
            
        Returns:
            List of transformed chunks (same length as input)
            
        Raises:
            ValueError: If input validation fails
        """
        pass
