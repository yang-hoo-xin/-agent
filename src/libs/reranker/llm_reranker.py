"""LLM-based Reranker implementation.

This module implements reranking using Large Language Models to evaluate
the relevance of candidate passages to a given query. It reads prompts from
config/prompts/rerank.txt and structures LLM outputs for downstream processing.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from src.core.settings import resolve_path, resolve_storage_path
from src.libs.llm.base_llm import BaseLLM, Message
from src.libs.llm.llm_factory import LLMFactory
from src.libs.reranker.base_reranker import BaseReranker


class LLMRerankError(RuntimeError):
    """Raised when LLM reranking fails."""


class LLMReranker(BaseReranker):
    """LLM-based reranker using structured prompts.
    
    This implementation leverages an LLM to score and rerank candidate passages
    based on their relevance to a query. It reads the reranking prompt from
    a configurable file and expects structured JSON output from the LLM.
    
    Design Principles Applied:
    - Pluggable: Can be swapped with other reranker implementations via factory.
    - Config-Driven: Prompt file path and LLM settings come from configuration.
    - Observable: Supports TraceContext for monitoring (Stage F integration).
    - Fallback-Aware: Returns signal on failure for upstream fallback logic.
    - Structured Output: Validates LLM output against expected schema.
    """
    
    def __init__(
        self,
        settings: Any,
        prompt_path: Optional[str] = None,
        llm: Optional[BaseLLM] = None,
        **kwargs: Any
    ) -> None:
        """Initialize the LLM Reranker.
        
        Args:
            settings: Application settings containing LLM and rerank configuration.
            prompt_path: Optional path to rerank prompt file. If None, uses default
                'config/prompts/rerank.txt'. Used for testing to inject custom prompts.
            llm: Optional LLM instance. If None, creates via LLMFactory from settings.
                Used for testing to inject mock LLMs.
            **kwargs: Additional provider-specific parameters.
        """
        self.settings = settings
        self.prompt_path = prompt_path or str(resolve_path("config/prompts/rerank.txt"))
        self.llm = llm or LLMFactory.create(settings)
        self.kwargs = kwargs
        
        # Load prompt template
        try:
            self.prompt_template = self._load_prompt_template(self.prompt_path)
        except Exception as e:
            raise LLMRerankError(f"Failed to load rerank prompt from {self.prompt_path}: {e}") from e
    
    def _load_prompt_template(self, path: str) -> str:
        """Load the rerank prompt template from file.
        
        Args:
            path: Path to the prompt template file.
        
        Returns:
            The prompt template as a string.
        
        Raises:
            FileNotFoundError: If prompt file doesn't exist.
            IOError: If file can't be read.
        """
        prompt_file = Path(path)
        if not prompt_file.exists():
            raise FileNotFoundError(f"Rerank prompt file not found: {path}")
        
        return prompt_file.read_text(encoding="utf-8")
    
    def _build_rerank_prompt(self, query: str, candidates: List[Dict[str, Any]]) -> str:
        """Build the reranking prompt with query and candidates.
        
        Args:
            query: The user query string.
            candidates: List of candidate records to rerank.
        
        Returns:
            Formatted prompt string ready for LLM.
        """
        # Format candidates for the prompt
        candidates_text = []
        for i, candidate in enumerate(candidates):
            passage_id = candidate.get("id", f"passage_{i}")
            text = candidate.get("text", candidate.get("content", ""))
            candidates_text.append(f"Passage ID: {passage_id}\nText: {text}\n")
        
        candidates_str = "\n".join(candidates_text)
        
        # Construct full prompt
        full_prompt = f"{self.prompt_template}\n\nQuery: {query}\n\nPassages:\n{candidates_str}\n\nOutput only a JSON array: exactly one passage_id and integer score (0-3) per candidate, no reasoning or other fields."
        
        return full_prompt
    
    def _parse_llm_response(self, response_text: str, *, native=False) -> List[Dict[str, Any]]:
        """Parse and validate LLM response.
        
        Args:
            response_text: Raw text response from LLM.
        
        Returns:
            List of parsed ranking records with passage_id and score.
        
        Raises:
            LLMRerankError: If response doesn't match expected schema.
        """
        # Try to extract JSON from response (LLM might wrap in markdown)
        text = response_text.strip()
        
        # Remove markdown code blocks if present
        if not native and text.startswith("```json"):
            text = text[7:]
        elif not native and text.startswith("```"):
            text = text[3:]
        if not native and text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        
        # Parse JSON
        def unique_fields(pairs):
            # 为什么要有它：重复JSON键不能靠解码器的最后一个值覆盖前值而绕过严格输出合同。
            if len(dict(pairs)) != len(pairs):
                raise LLMRerankError("Rerank response has duplicate object fields")
            return dict(pairs)
        try:
            parsed = json.loads(text, object_pairs_hook=unique_fields)
        except json.JSONDecodeError as e:
            raise LLMRerankError(
                f"LLM response is not valid JSON: {e}\nResponse: {response_text[:200]}"
            ) from e
        
        # Validate structure
        if not isinstance(parsed, list):
            raise LLMRerankError(
                f"Expected JSON array, got {type(parsed).__name__}\nResponse: {response_text[:200]}"
            )
        
        # Validate each item
        for i, item in enumerate(parsed):
            if not isinstance(item, dict):
                raise LLMRerankError(
                    f"Item {i} is not a dict (type: {type(item).__name__})"
                )
            if "passage_id" not in item:
                raise LLMRerankError(f"Item {i} missing required field 'passage_id'")
            if "score" not in item:
                raise LLMRerankError(f"Item {i} missing required field 'score'")
            # 为什么要有它：紧凑合同禁止解释字段消耗输出预算，也不能将布尔值或越界分数当合法评分。
            if set(item) != {"passage_id", "score"}:
                raise LLMRerankError("Rerank records allow only passage_id and score")
            if not isinstance(item["passage_id"], str) or not item["passage_id"]:
                raise LLMRerankError("Rerank passage_id must be a non-empty string")
            score = item["score"]
            if type(score) is not int or not 0 <= score <= 3:
                raise LLMRerankError(
                    f"Item {i} score must be numeric integer 0-3"
                )
        
        return parsed
    
    def _map_results_to_candidates(
        self,
        parsed_results: List[Dict[str, Any]],
        candidates: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Map LLM ranking results back to original candidate objects.
        
        Args:
            parsed_results: Parsed LLM output with passage_id and score.
            candidates: Original candidate list.
        
        Returns:
            Reranked list of candidate objects, sorted by score descending.
        """
        # Create mapping from id to candidate
        id_to_candidate = {}
        for i, candidate in enumerate(candidates):
            candidate_id = candidate.get("id", f"passage_{i}")
            id_to_candidate[candidate_id] = candidate

        # 为什么要有它：缺失、重复或陌生ID不能静默丢弃候选并伪装成功重排。
        actual_ids = [result["passage_id"] for result in parsed_results]
        if (len(actual_ids) != len(candidates) or len(set(actual_ids)) != len(actual_ids)
                or set(actual_ids) != set(id_to_candidate)):
            raise LLMRerankError("Rerank response must cover every candidate exactly once")
        
        # Build reranked list
        reranked = []
        for result in parsed_results:
            passage_id = result["passage_id"]
            score = result["score"]
            
            if passage_id in id_to_candidate:
                candidate = id_to_candidate[passage_id].copy()
                # Update score with LLM rerank score
                candidate["rerank_score"] = float(score)
                reranked.append(candidate)
        
        # Sort by rerank score descending
        reranked.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
        
        return reranked

    @staticmethod
    def _candidate_ids(candidates):
        ids = [candidate.get("id", f"passage_{i}") for i, candidate in enumerate(candidates)]
        if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
            raise LLMRerankError("Rerank candidate IDs must be non-empty unique strings")
        return ids

    @staticmethod
    def _response_schema(ids):
        # 为什么要有它：原生输出只需候选ID与四档分数，减少无用解释；逐ID覆盖仍由宿主严格验证。
        return {"type": "array", "minItems": len(ids), "maxItems": len(ids),
                "items": {"type": "object", "additionalProperties": False,
                          "properties": {"passage_id": {"type": "string", "enum": ids},
                                         "score": {"type": "integer", "enum": [0, 1, 2, 3]}},
                          "required": ["passage_id", "score"]}}

    def _persist_evidence(self, evidence_id, kind, value):
        # 为什么要有它：请求须在发送前落盘，响应和调用索引保持私有且逐调用隔离，公共trace只带hash。
        directory = resolve_storage_path(self.settings, "rerank_requests")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{evidence_id}.{kind}.json"
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != raw:
            raise LLMRerankError("Rerank evidence persistence verification failed")
        return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    
    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        trace: Optional[Any] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Rerank candidates using LLM-based relevance scoring.
        
        Args:
            query: The user query string.
            candidates: List of candidate records to rerank.
            trace: Optional TraceContext for observability.
            **kwargs: Additional parameters (timeout, temperature, etc.).
        
        Returns:
            Reranked list of candidates sorted by LLM-assigned relevance score.
            On success, each candidate will have 'rerank_score' in metadata.
        
        Raises:
            ValueError: If query or candidates are invalid.
            LLMRerankError: If LLM call fails or response is malformed.
        """
        # Validate inputs
        self.validate_query(query)
        self.validate_candidates(candidates)
        ids = self._candidate_ids(candidates)
        
        # If only one candidate, no need to rerank
        if len(candidates) == 1:
            return candidates
        
        # Build prompt
        try:
            prompt = self._build_rerank_prompt(query, candidates)
        except Exception as e:
            raise LLMRerankError(f"Failed to build rerank prompt: {e}") from e
        
        # Call LLM
        from src.libs.llm.ollama_llm import OllamaLLM
        from src.libs.llm.transport_observation import observe_transport
        from src.observability.evaluation.answer_generation import observed_usage
        begun = time.perf_counter()
        transport = {"starts": 0, "observed": False}
        response = None
        native_response = None
        native = isinstance(self.llm, OllamaLLM)
        evidence_id = uuid4().hex if native else None
        private = {"schema_version": "compact-rerank-evidence.v1", "evidence_id": evidence_id,
                   "trace_id": getattr(trace, "trace_id", None), "candidate_ids": ids}
        public = {"contract": "compact-rerank.v1", "evidence_id": evidence_id, "status": "failed"}
        def sent():
            transport["starts"] += 1
            transport["observed"] = True
        def prepared(**facts):
            if "transport_started" in facts:
                transport["observed"] = True
        def record_request(frozen):
            transport["observed"] = True
            private["request_ref"] = self._persist_evidence(evidence_id, "request", frozen)
            public.update(request_body_sha256=frozen["body_sha256"],
                          request_body_bytes=frozen["body_size_bytes"], persisted_before_transport=True)
        def record_response(raw):
            nonlocal native_response
            native_response = deepcopy(raw)
            private["response_ref"] = self._persist_evidence(evidence_id, "response", raw)
            public.update(response_sha256=private["response_ref"]["sha256"],
                          response_bytes=private["response_ref"]["bytes"])
        try:
            messages = [Message(role="user", content=prompt)]
            call_kwargs = dict(kwargs)
            if native:
                call_kwargs.update(response_format=self._response_schema(ids),
                                   provider_request_recorder=record_request,
                                   provider_response_recorder=record_response)
            with observe_transport(sent, request_callback=prepared):
                response = self.llm.chat(messages, trace=trace, **call_kwargs)
            response_text = response.content
            raw = response.raw_response
            # 为什么要有它：即使截断内容恰好是合法JSON，也不能把未完成的模型响应当成功评分。
            if isinstance(raw, dict) and (raw.get("done") is False or raw.get("done_reason") in {"length", "max_tokens"}
                    or any(c.get("finish_reason") in {"length", "max_tokens"} for c in raw.get("choices", []) if isinstance(c, dict))):
                raise LLMRerankError("Rerank response incomplete or truncated")
            if native and not {"request_ref", "response_ref"} <= private.keys():
                raise LLMRerankError("Rerank native evidence missing")
            parsed_results = self._parse_llm_response(response_text, native=native)
            reranked = self._map_results_to_candidates(parsed_results, candidates)
            public["status"] = "validated"
            return reranked
        except Exception as e:
            private["failure_type"] = type(e).__name__
            diagnostics = getattr(e, "diagnostics", None)
            if isinstance(diagnostics, dict):
                private["failure_diagnostics"] = diagnostics
                public["failure_classification"] = diagnostics.get("failure_classification")
            if isinstance(e, LLMRerankError):
                raise
            raise LLMRerankError(f"LLM call failed during reranking: {e}") from e
        finally:
            usage = observed_usage(response) if response is not None else None
            if native_response is not None:
                public.update(done=native_response.get("done"), done_reason=native_response.get("done_reason"))
                if all(type(native_response.get(k)) is int and native_response[k] >= 0 for k in ("prompt_eval_count", "eval_count")):
                    usage = {"prompt_tokens": native_response["prompt_eval_count"],
                             "completion_tokens": native_response["eval_count"],
                             "total_tokens": native_response["prompt_eval_count"] + native_response["eval_count"]}
            public.update(model=getattr(self.llm, "model", None), calls_reserved=1,
                          transport_calls=transport["starts"] if transport["observed"] else None,
                          response_received=response is not None or native_response is not None, usage=usage)
            persistence_error = None
            if native:
                private["observation"] = deepcopy(public)
                try:
                    observation_ref = self._persist_evidence(evidence_id, "observation", private)
                    public["observation_sha256"] = observation_ref["sha256"]
                except Exception as error:
                    # 为什么要有它：证据写入失败也要保留实际发送计数，但不能把未落盘索引宣称为可查原件。
                    persistence_error = error
                    public.update(status="failed", failure_classification="rerank_evidence_persistence_failed")
            if trace is not None:
                # 为什么要有它：重排也可能调用模型，完整查询成本不能只统计最终回答；未知传输或usage不填零。
                trace.record_stage("rerank_model", public,
                    elapsed_ms=(time.perf_counter() - begun) * 1000)
            if persistence_error is not None:
                raise LLMRerankError("Rerank evidence persistence failed") from persistence_error
