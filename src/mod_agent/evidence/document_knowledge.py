"""Source-checked document evidence from the normal MCP knowledge/query owner."""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from src.core.query_engine.query_processor import FILTER_PATTERN
from src.core.query_engine.query_service import QUERY_RESPONSE_SCHEMA
from src.core.query_engine.result_cache import fingerprint
from src.mod_agent.knowledge_evidence_config import file_ref, local_path, verify_ref
from src.mod_agent.planning.clarified_request import source_hint_text
from .models import DETERMINISTIC_EVIDENCE_AUTHORITY, EvidenceItem, EvidencePack


def _save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
    return file_ref(path)


def _read_original_text(path):
    # 为什么要有它：跨度沿MaterialLoader的UTF-8解码字符计数；仅移除BOM，不能把CRLF/CR归一化后错移原文偏移。
    return path.read_bytes().decode("utf-8-sig")


def _knowledge_query_context(projection, retrieved):
    """Use actual task text and observed target-source API spellings for document lookup."""
    values = projection if isinstance(projection, dict) else {}
    texts = [row.get("text") for row in values.get("input_obligations", ())
             if isinstance(row, dict) and isinstance(row.get("origin"), dict)
             and row["origin"].get("field") in {"user_request", "target_behavior"}]
    if not texts:
        texts = [row.get("text") for row in values.get("requirements", ()) if isinstance(row, dict)]
    texts = list(dict.fromkeys(source_hint_text(text) for text in texts if isinstance(text, str) and text.strip()))
    original = "\n".join(texts) or source_hint_text(retrieved.query)
    # 为什么要有它：粗分类词不能替代真实问题；代码里实际出现的API拼写只帮助检索，不构成运行证明或修复指令。
    names = []
    pattern = re.compile(r"(?<![\w.])([A-Z][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)(?:<[^>\r\n]+>)?\s*\(")
    for item in retrieved.items:
        if item.source_type == "target_source":
            names.extend(pattern.findall(item.excerpt))
            names.extend(re.findall(r"(?<![\w.])([A-Z][A-Za-z0-9_]*)<[^>\r\n]+>\s*\(", item.excerpt))
    names = sorted(dict.fromkeys(names), key=lambda value: -value.count("."))[:32]
    if names:
        # 为什么要有它：源码API拼写放在有限关键词窗口之前，不能让长篇通用需求截掉实际调查线索。
        # 为什么要有它：索引可能保留全限定名或成员短名；只从同一已观测拼写派生别名，不猜测新API。
        aliases = list(dict.fromkeys(value for name in names
            for value in (name, ".".join(name.split(".")[-2:]), name.rsplit(".", 1)[-1])))
        original = ", ".join(aliases) + "\nObserved target-source lookup hints above.\n" + original
    # 为什么要有它：业务需求中的错误码不是文档元数据过滤器；沿现有语法转义，collection仍由可信配置单独指定。
    return FILTER_PATTERN.sub(lambda match: match.group(0).replace(":", "\\:"), original)


def validate_document_item(item):
    provenance = item.document_provenance
    if (item.source_type != "domain_note" or item.source_authority != "supporting"
            or item.authority != DETERMINISTIC_EVIDENCE_AUTHORITY or item.usage != "document_reference"
            or item.retrieval_method != "mcp_document_original_text" or not isinstance(provenance, dict)
            or provenance.get("schema_version") != "document_knowledge_evidence_v1"
            or any(value is not None for value in (item.module_mvid, item.metadata_token, item.signature_blob,
                item.declaring_type, item.method_name, item.parameter_types, item.return_type))):
        raise ValueError("DOCUMENT_EVIDENCE_BOUNDARY_INVALID")
    record = json.loads(verify_ref(provenance["record_ref"]).read_bytes())
    source = verify_ref(record["source_snapshot_ref"])
    text_path = verify_ref(record["parsed_text_snapshot_ref"])
    run_root = local_path(record["run_root"])
    if (not source.is_relative_to(run_root / "k/s") or not text_path.is_relative_to(run_root / "k/s")
            or item.source_path != source.relative_to(run_root).as_posix()
            or not Path(provenance["record_ref"]["path"]).is_relative_to(run_root / "k/q")
            or not Path(record["query_response_ref"]["path"]).is_relative_to(run_root / "k/q")):
        raise ValueError("DOCUMENT_EVIDENCE_RECORD_SCOPE_INVALID")
    dependencies = record.get("expected_dependency_refs", [])
    expected_versions = {row["relative_path"]: row["source_ref"]["sha256"] for row in dependencies}
    if (provenance.get("dependency_dll_sha256") != expected_versions
            or provenance.get("query_trace_id") != record["query_trace_id"]
            or provenance.get("enhancement_is_original_source") is not False
            or record.get("image_captions_admitted_as_original") is not False):
        raise ValueError("DOCUMENT_EVIDENCE_PROVENANCE_CHANGED")
    observed_dependencies = {row["relative_path"]: row for row in record["current_dependency_validation"].get("files", [])}
    for expected in dependencies:
        observed = observed_dependencies.get(Path(expected["relative_path"]).as_posix(), {})
        if observed.get("sha256") != expected["source_ref"]["sha256"]:
            raise ValueError("DOCUMENT_EVIDENCE_DEPENDENCY_VERSION_CHANGED")
        verify_ref({key: observed[key] for key in ("path", "sha256")})
    original_text = _read_original_text(text_path)
    start, end = record["start_offset"], record["end_offset"]
    if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(original_text)
            or original_text[start:end] != item.excerpt or file_ref(source)["sha256"] != item.source_hash
            or item.file_hash != item.source_hash or item.source_ref != str(source)
            or item.chunk_id != record["chunk_id"] or item.span != {"start_offset": start, "end_offset": end}
            or hashlib.sha256(item.excerpt.encode("utf-8")).hexdigest() != record["original_text_sha256"]
            or provenance["collection"] != record["collection"]
            or provenance["processing_fingerprint"] != record["processing_fingerprint"]):
        raise ValueError("DOCUMENT_EVIDENCE_SOURCE_IDENTITY_CHANGED")
    response = json.loads(verify_ref(record["query_response_ref"]).read_bytes())
    payload = (response.get("response") or {}).get("structuredContent", {})
    matching = [row for row in payload.get("results", []) if row.get("chunk_id") == item.chunk_id
        and row.get("metadata", {}).get("original_text") == item.excerpt
        and row.get("metadata", {}).get("original_start_offset") == start
        and row.get("metadata", {}).get("original_end_offset") == end
        and row.get("metadata", {}).get("source_hash") == item.source_hash
        and row.get("metadata", {}).get("processing_fingerprint") == record["processing_fingerprint"]]
    if payload.get("trace_id") != record["query_trace_id"] or payload.get("collection") != record["collection"] or len(matching) != 1:
        raise ValueError("DOCUMENT_EVIDENCE_QUERY_PROVENANCE_CHANGED")
    return record


def merge_document_augmentation(retrieved, augmentation):
    if (not isinstance(augmentation, EvidencePack) or augmentation.query != retrieved.query
            or augmentation.can_generate_patch or augmentation.requirement_coverage is not None
            or augmentation.provenance_validation.get("target_code_executed") is not False):
        raise ValueError("DOCUMENT_AUGMENTATION_BOUNDARY_INVALID")
    by_id = {item.evidence_id: item for item in retrieved.items}
    for item in augmentation.items:
        validate_document_item(item)
        if item.evidence_id in by_id and by_id[item.evidence_id] != item:
            raise ValueError("DOCUMENT_AUGMENTATION_IDENTITY_CONFLICT")
        by_id[item.evidence_id] = item
    # 为什么要有它：文档只增加可追溯只读依据，最终覆盖与可编辑源码仍由原Findings/Planning/Apply契约决定。
    return replace(retrieved, items=tuple(by_id.values()),
        excluded=(*retrieved.excluded, *augmentation.excluded),
        retrieval_methods_used=tuple(dict.fromkeys((*retrieved.retrieval_methods_used, *augmentation.retrieval_methods_used))),
        budget_summary={**deepcopy(retrieved.budget_summary), "document_knowledge": deepcopy(augmentation.budget_summary)},
        trace_refs=tuple(dict.fromkeys((*retrieved.trace_refs, *augmentation.trace_refs))))


class DocumentKnowledgeAugmentation:
    def __init__(self, configuration, run_root, run_id, *, dependency_binding=None):
        self.configuration, self.run_root, self.run_id = configuration, run_root.resolve(), run_id
        self.dependency_binding = deepcopy(dependency_binding)
        self.dependency_observation = self.verify_dependencies()
        from src.core.settings import load_settings
        self.dense_enabled = load_settings(configuration.value["server_settings_ref"]["path"]).retrieval.dense_enabled
        self.root = self.run_root / "k"
        (self.root / "s").mkdir(parents=True, exist_ok=True)
        (self.root / "q").mkdir(exist_ok=True)
        (self.root / "m").mkdir(exist_ok=True)
        self.sources = {}
        for source in configuration.value["sources"]:
            original = verify_ref(source["source_ref"])
            copied = self._copy(source["source_ref"])
            parsed = self._copy(source.get("parsed_text_ref", source["source_ref"]))
            self.sources[str(original)] = {"binding": source, "source_snapshot_ref": copied, "parsed_text_snapshot_ref": parsed}
        self.items = {}
        self.excluded = []

    def verify_dependencies(self):
        expected = self.configuration.value["dependency_refs"]
        if not expected:
            return {"status": "not_requested", "model_calls": 0}
        from src.mod_agent.planning.memory_dependency_context import dependency_memory_context
        context, observation = dependency_memory_context(workspace_root=self.run_root, binding=self.dependency_binding)
        if observation.get("status") != "verified" or any(
                context.get("dependency_dll_sha256:" + Path(row["relative_path"]).as_posix()) != row["source_ref"]["sha256"]
                for row in expected):
            raise ValueError("KNOWLEDGE_CURRENT_DEPENDENCY_VERSION_MISMATCH")
        return observation

    def _copy(self, reference):
        source = verify_ref(reference)
        destination = self.root / "s" / (reference["sha256"][:24] + ".src")
        if not destination.exists():
            with destination.open("xb") as stream:
                stream.write(source.read_bytes())
        if file_ref(destination)["sha256"] != reference["sha256"]:
            raise ValueError("KNOWLEDGE_SNAPSHOT_COLLISION")
        return file_ref(destination)

    def __call__(self, projection, retrieved):
        from jsonschema import Draft7Validator
        from .knowledge_mcp_client import query_batch
        self.configuration.verify()
        self.dependency_observation = self.verify_dependencies()
        config = self.configuration.value
        original = _knowledge_query_context(projection, retrieved)
        reassessment = retrieved.budget_summary.get("reassessment", {})
        focuses = [str(row["query"]) for row in reassessment.get("queries", []) if isinstance(row.get("query"), str)]
        queries = [original] if not focuses else [original + "\nInvestigation focus: " + focus for focus in dict.fromkeys(focuses)]
        records, requested, new = [], [], []
        for query in queries:
            key = fingerprint({"query": query, "configuration_ref": self.configuration.reference})
            directory = self.root / "q" / key[:24]
            if directory.exists():
                saved = json.loads((directory / "request.json").read_bytes())
                if saved["key"] != key:
                    raise ValueError("KNOWLEDGE_QUERY_IDENTITY_COLLISION")
                if not (directory / "outcome.json").is_file():
                    raise ValueError("KNOWLEDGE_QUERY_OUTCOME_UNKNOWN")
                records.append(directory)
                continue
            if len(list((self.root / "q").iterdir())) >= config["max_queries"]:
                continue
            directory.mkdir()
            arguments = {"query": query, "collection": config["collection"], "top_k": config["top_k"],
                "answer": False, "rewrite": config["rewrite"], "rerank": config["rerank"], "stream": False,
                "request_id": self.run_id + "-kb-" + key[:16]}
            _save(directory / "request.json", {"key": key, "arguments": arguments, "configuration_ref": self.configuration.reference})
            requested.append(arguments); new.append(directory); records.append(directory)
        if new:
            batch = self.root / "m" / uuid4().hex[:12]
            batch.mkdir()
            result = query_batch(self.configuration, requested, batch)
            calls = result.get("calls", [])
            for index, directory in enumerate(new):
                response = calls[index]["response"] if index < len(calls) else None
                _save(directory / "outcome.json", {"batch_ref": file_ref(batch / "result.json"),
                    "response": response, "status": "observed" if response is not None and result["status"] == "completed" else "failed",
                    "provider_termination": "unknown"})
        costs, traces = [], []
        for directory in sorted((self.root / "q").iterdir()):
            if not (directory / "outcome.json").is_file():
                raise ValueError("KNOWLEDGE_QUERY_OUTCOME_UNKNOWN")
            outcome_ref = file_ref(directory / "outcome.json")
            outcome = json.loads(verify_ref(outcome_ref).read_bytes())
            verify_ref(outcome["batch_ref"])
            response = outcome.get("response") or {}
            payload = response.get("structuredContent")
            if outcome.get("status") != "observed" or response.get("isError") or not isinstance(payload, dict) or payload.get("status") != "completed":
                raise ValueError("KNOWLEDGE_MCP_QUERY_FAILED")
            Draft7Validator(QUERY_RESPONSE_SCHEMA).validate(payload)
            arguments = json.loads((directory / "request.json").read_bytes())["arguments"]
            if (payload["query"] != arguments["query"] or payload["collection"] != config["collection"]
                    or payload["request_id"] != arguments["request_id"] or payload["answer"] is not None
                    or "MCP_SECRET_REDACTION_APPLIED" in payload["warnings"]):
                raise ValueError("KNOWLEDGE_QUERY_RESPONSE_BINDING_INVALID")
            usage = payload["usage"]
            llm_reserved = usage.get("rewrite_calls_reserved", 0) + sum(
                row.get("calls_reserved", 0) for row in usage.get("other_model_observations", []))
            if usage.get("answer_calls_reserved") != 0 or llm_reserved > config["max_llm_calls_per_query"]:
                raise ValueError("KNOWLEDGE_QUERY_MODEL_BUDGET_VIOLATED")
            costs.append({"query_ref": file_ref(directory / "request.json"), "response_ref": outcome_ref,
                          "usage": payload["usage"], "cache": payload["cache"], "timing": payload["timing"]})
            traces.append(outcome_ref["path"])
            for index, row in enumerate(payload["results"]):
                try:
                    item = self._item(row, payload, outcome_ref, directory)
                except (ValueError, UnicodeError) as error:
                    self.excluded.append({"query_response_ref": outcome_ref, "result_index": index, "reason": str(error)})
                    continue
                self.items.setdefault(item.evidence_id, item)
        self.configuration.verify()
        self.verify_dependencies()
        llm_known = embedding_known = embedding_tokens = 0
        llm_unknown = embedding_unknown = 0
        input_tokens = output_tokens = 0
        token_unknown = False
        embedding_token_unknown = False
        for cost in costs:
            usage = cost["usage"]
            reserved = usage.get("rewrite_calls_reserved", 0)
            actual = usage.get("rewrite_transport_calls", 0 if reserved == 0 else None)
            if type(actual) is int:
                llm_known += actual
            else:
                llm_unknown += 1
            if reserved:
                tokens = usage.get("rewrite_tokens")
                if isinstance(tokens, dict) and all(type(tokens.get(key)) is int for key in ("prompt_tokens", "completion_tokens")):
                    input_tokens += tokens["prompt_tokens"]; output_tokens += tokens["completion_tokens"]
                else:
                    token_unknown = True
            for observation in usage.get("other_model_observations", []):
                if "calls_reserved" in observation:
                    actual = observation.get("transport_calls")
                    if type(actual) is int:
                        llm_known += actual
                    else:
                        llm_unknown += 1
                    tokens = observation.get("usage")
                    if isinstance(tokens, dict) and all(type(tokens.get(key)) is int for key in ("prompt_tokens", "completion_tokens")):
                        input_tokens += tokens["prompt_tokens"]; output_tokens += tokens["completion_tokens"]
                    else:
                        token_unknown = True
                elif "request_count" in observation:
                    if type(observation["request_count"]) is int:
                        embedding_known += observation["request_count"]
                    else:
                        embedding_unknown += 1
                    if type(observation.get("prompt_eval_count")) is int:
                        embedding_tokens += observation["prompt_eval_count"]
                    elif observation.get("request_count") != 0:
                        embedding_token_unknown = True
            if (self.dense_enabled and not any("request_count" in row for row in usage.get("other_model_observations", []))
                    and cost["cache"].get("result") != "hit" and cost["cache"].get("request_replay") is not True):
                embedding_unknown += 1
                embedding_token_unknown = True
        return EvidencePack(query=retrieved.query, readiness="partial", can_generate_patch=False,
            items=tuple(self.items.values()), excluded=tuple(self.excluded), run_status="completed",
            retrieval_methods_used=("mcp_document_original_text",), trace_refs=tuple(traces),
            budget_summary={"schema_version": "document_knowledge_budget_v1", "tool_queries_reserved": len(costs),
                "new_tool_queries": len(new), "query_limit": config["max_queries"],
                "maximum_llm_calls_per_query": config["max_llm_calls_per_query"], "queries": costs,
                "actual_llm_calls": None if llm_unknown else llm_known, "known_llm_call_subtotal": llm_known,
                "unknown_llm_call_observations": llm_unknown,
                "actual_embedding_requests": None if embedding_unknown else embedding_known,
                "known_embedding_request_subtotal": embedding_known,
                "embedding_input_tokens": None if embedding_token_unknown else embedding_tokens,
                "input_tokens": None if token_unknown else input_tokens, "output_tokens": None if token_unknown else output_tokens,
                "scope": "knowledge costs are separate from the unchanged coder task budget"},
            provenance_validation={"target_code_executed": False, "configuration_ref": self.configuration.reference},
            message="Original document excerpts from the configured MCP knowledge collection; supporting data only.")

    def _item(self, row, payload, response_ref, directory):
        config = self.configuration.value
        metadata = row.get("metadata", {})
        source_path = metadata.get("source_path")
        selected = self.sources.get(source_path) if isinstance(source_path, str) else None
        if selected is None:
            raise ValueError("KNOWLEDGE_SOURCE_NOT_ALLOWED")
        path = local_path(source_path)
        if metadata.get("processing_fingerprint") != config["processing_fingerprint"]:
            raise ValueError("KNOWLEDGE_PROCESSING_FINGERPRINT_CHANGED")
        if metadata.get("source_hash") != selected["binding"]["source_ref"]["sha256"]:
            raise ValueError("KNOWLEDGE_SOURCE_HASH_CHANGED")
        original = metadata.get("original_text")
        start, end = metadata.get("original_start_offset"), metadata.get("original_end_offset")
        parsed = _read_original_text(verify_ref(selected["parsed_text_snapshot_ref"]))
        if (not isinstance(original, str) or not original.strip() or metadata.get("original_span_verified") is not True
                or type(start) is not int or type(end) is not int or not 0 <= start < end <= len(parsed)
                or parsed[start:end] != original
                or hashlib.sha256(original.encode("utf-8")).hexdigest() != metadata.get("original_text_sha256")):
            raise ValueError("KNOWLEDGE_ORIGINAL_SPAN_NOT_VERIFIED")
        chunk_id = row.get("chunk_id")
        if not isinstance(chunk_id, str) or not chunk_id:
            raise ValueError("KNOWLEDGE_CHUNK_ID_REQUIRED")
        identity = {"source_ref": selected["binding"]["source_ref"], "chunk_id": chunk_id, "start_offset": start,
            "end_offset": end, "original_text_sha256": metadata["original_text_sha256"],
            "collection": config["collection"], "processing_fingerprint": config["processing_fingerprint"]}
        evidence_id = "document_" + fingerprint(identity)[:24]
        if evidence_id in self.items:
            validate_document_item(self.items[evidence_id])
            return self.items[evidence_id]
        record = {**identity, "run_root": str(self.run_root), "source_snapshot_ref": selected["source_snapshot_ref"],
            "parsed_text_snapshot_ref": selected["parsed_text_snapshot_ref"], "source_binding": selected["binding"],
            "query_response_ref": response_ref, "query_trace_id": payload["trace_id"],
            "current_dependency_validation": deepcopy(self.dependency_observation),
            "expected_dependency_refs": deepcopy(config["dependency_refs"]),
            "configuration_ref": self.configuration.reference,
            "server_settings_ref": config["server_settings_ref"], "server_entry_ref": config["server_entry_ref"],
            "query_model_identity": payload["cache"].get("model_identity"), "query_usage": payload["usage"],
            "enhancement_is_original_source": False, "enhanced_text_sha256": metadata.get("enhanced_text_sha256"),
            "enhancement_model_identity": metadata.get("enhancement_model_identity"),
            "image_captions": metadata.get("image_captions"), "image_captions_admitted_as_original": False}
        record_path = directory / (evidence_id + ".json")
        if record_path.exists():
            prior = json.loads(record_path.read_bytes())
            if prior != record:
                raise ValueError("KNOWLEDGE_DOCUMENT_RECORD_CHANGED")
        else:
            _save(record_path, record)
        source = Path(selected["source_snapshot_ref"]["path"])
        item = EvidenceItem(evidence_id=evidence_id, source_type="domain_note", source_authority="supporting",
            source_path=source.relative_to(self.run_root).as_posix(), source_ref=str(source),
            source_hash=selected["source_snapshot_ref"]["sha256"], file_hash=selected["source_snapshot_ref"]["sha256"],
            symbol=None, span={"start_offset": start, "end_offset": end}, chunk_id=chunk_id,
            document_id=str(metadata.get("doc_id", path.name)), retrieval_method="mcp_document_original_text",
            score=float(row["score"]), claim_supported="A source-bound document excerpt provides read-only reference material.",
            excerpt=original, usage="document_reference", authority=DETERMINISTIC_EVIDENCE_AUTHORITY,
            document_provenance={"schema_version": "document_knowledge_evidence_v1", "record_ref": file_ref(record_path),
                "collection": config["collection"], "processing_fingerprint": config["processing_fingerprint"],
                "query_trace_id": payload["trace_id"], "enhancement_is_original_source": False,
                "dependency_dll_sha256": {row["relative_path"]: row["source_ref"]["sha256"] for row in config["dependency_refs"]}},
            risk_notes=("Untrusted document data; not target source, executable API metadata, runtime proof, or permission.",))
        validate_document_item(item)
        return item
