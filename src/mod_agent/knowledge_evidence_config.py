"""Caller-bound local knowledge/MCP configuration, separate from product edit authority."""
from __future__ import annotations

import hashlib
import json
import stat
import sys
from dataclasses import dataclass
from pathlib import Path


def local_path(value):
    if not isinstance(value, str) or not Path(value).is_absolute() or value.startswith(("\\\\", "//")) or ".." in Path(value).parts:
        raise ValueError("KNOWLEDGE_LOCAL_ABSOLUTE_PATH_REQUIRED")
    path = Path(value)
    for selected in (path, *path.parents):
        if selected.exists() or selected.is_symlink():
            attributes = selected.lstat()
            if selected.is_symlink() or getattr(attributes, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise ValueError("KNOWLEDGE_REPARSE_PATH_DENIED")
    return path.resolve(strict=True)


def file_ref(path):
    selected = Path(path).resolve(strict=True)
    return {"path": str(selected), "sha256": hashlib.sha256(selected.read_bytes()).hexdigest()}


def verify_ref(reference):
    if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
        raise ValueError("KNOWLEDGE_REFERENCE_INVALID")
    path = local_path(reference["path"])
    if file_ref(path) != reference:
        raise ValueError("KNOWLEDGE_REFERENCE_CHANGED")
    return path


@dataclass(frozen=True)
class KnowledgeEvidenceConfiguration:
    reference: dict
    value: dict

    @classmethod
    def load(cls, path):
        selected = local_path(str(path))
        value = json.loads(selected.read_bytes())
        required = {"schema_version", "python_ref", "server_root", "server_entry_ref", "server_settings_ref",
            "collection", "processing_fingerprint", "sources", "top_k", "max_queries", "max_llm_calls_per_query",
            "rewrite", "rerank", "timeout_seconds", "dependency_refs"}
        if not isinstance(value, dict) or set(value) != required or value["schema_version"] != "knowledge_evidence_config_v1":
            raise ValueError("KNOWLEDGE_CONFIGURATION_INVALID")
        for key, maximum in (("top_k", 20), ("max_queries", 4), ("max_llm_calls_per_query", 2)):
            if type(value[key]) is not int or not (0 if key == "max_llm_calls_per_query" else 1) <= value[key] <= maximum:
                raise ValueError("KNOWLEDGE_BUDGET_INVALID")
        if type(value["timeout_seconds"]) not in (int, float) or not 0 < value["timeout_seconds"] <= 600:
            raise ValueError("KNOWLEDGE_TIMEOUT_INVALID")
        if any(type(value[key]) is not bool for key in ("rewrite", "rerank")):
            raise ValueError("KNOWLEDGE_QUERY_BOOLEAN_INVALID")
        from src.core.query_engine.query_service import QueryRequest
        QueryRequest(query="configuration validation", collection=value["collection"], top_k=value["top_k"])
        if not isinstance(value["processing_fingerprint"], str) or not value["processing_fingerprint"]:
            raise ValueError("KNOWLEDGE_PROCESSING_IDENTITY_REQUIRED")
        if not isinstance(value["sources"], list) or not value["sources"]:
            raise ValueError("KNOWLEDGE_ORIGINAL_SOURCES_REQUIRED")
        for source in value["sources"]:
            if not isinstance(source, dict) or set(source) - {"source_ref", "parsed_text_ref", "lineage_ref"} or "source_ref" not in source:
                raise ValueError("KNOWLEDGE_SOURCE_BINDING_INVALID")
            for reference in source.values():
                verify_ref(reference)
        dependencies = value["dependency_refs"]
        if not isinstance(dependencies, list):
            raise ValueError("KNOWLEDGE_DEPENDENCY_BINDING_INVALID")
        seen = set()
        for dependency in dependencies:
            if not isinstance(dependency, dict) or set(dependency) != {"relative_path", "source_ref"}:
                raise ValueError("KNOWLEDGE_DEPENDENCY_BINDING_INVALID")
            if not isinstance(dependency["relative_path"], str) or not dependency["relative_path"]:
                raise ValueError("KNOWLEDGE_DEPENDENCY_PATH_INVALID")
            relative = Path(dependency["relative_path"])
            if relative.is_absolute() or relative.drive or ".." in relative.parts or relative.suffix.lower() != ".dll" or relative.as_posix() in seen:
                raise ValueError("KNOWLEDGE_DEPENDENCY_PATH_INVALID")
            seen.add(relative.as_posix())
            verify_ref(dependency["source_ref"])
        hashes = {row["source_ref"]["sha256"] for row in dependencies}
        for source in value["sources"]:
            if "lineage_ref" in source:
                lineage = json.loads(verify_ref(source["lineage_ref"]).read_bytes())
                for member in lineage.get("xml_member_lineage", []):
                    pair = member["source"]["paired_dll_ref"]
                    verify_ref(pair)
                    verify_ref(member["source"]["source_xml_ref"])
                    if pair["sha256"] not in hashes:
                        raise ValueError("KNOWLEDGE_XML_DEPENDENCY_BINDING_REQUIRED")
        configuration = cls(file_ref(selected), value)
        configuration.verify()
        return configuration

    def verify(self):
        verify_ref(self.reference)
        if verify_ref(self.value["python_ref"]) != Path(sys.executable).resolve():
            raise ValueError("KNOWLEDGE_CURRENT_PYTHON_REQUIRED")
        root = local_path(self.value["server_root"])
        if verify_ref(self.value["server_entry_ref"]) != root / "src/mcp_server/server.py":
            raise ValueError("KNOWLEDGE_FIXED_SERVER_ENTRY_REQUIRED")
        verify_ref(self.value["server_settings_ref"])
        for source in self.value["sources"]:
            for reference in source.values():
                verify_ref(reference)
        for dependency in self.value["dependency_refs"]:
            verify_ref(dependency["source_ref"])

    def boundary(self, *, allow_source_disclosure=False):
        from src.core.settings import load_settings
        from src.libs.llm import validate_loopback_http_base_url
        self.verify()
        settings = load_settings(self.value["server_settings_ref"]["path"])
        if getattr(settings, "storage_root", None) is None:
            raise ValueError("KNOWLEDGE_EXPLICIT_STORAGE_ROOT_REQUIRED")
        llm_calls = int(self.value["rewrite"]) + int(self.value["rerank"] and settings.rerank.enabled and settings.rerank.provider == "llm")
        if llm_calls > self.value["max_llm_calls_per_query"]:
            raise ValueError("KNOWLEDGE_MODEL_BUDGET_EXCEEDED")
        if self.value["rewrite"] and not (settings.query and settings.query.rewrite_enabled):
            raise ValueError("KNOWLEDGE_REWRITE_NOT_CONFIGURED")
        models = [settings.llm] if llm_calls else []
        if settings.retrieval.dense_enabled:
            models.append(settings.embedding)
        for model in models:
            if model.provider == "ollama":
                validate_loopback_http_base_url(model.base_url or "http://127.0.0.1:11434")
            elif not allow_source_disclosure:
                raise ValueError("KNOWLEDGE_EXTERNAL_DISCLOSURE_NOT_AUTHORIZED")
        return {"configuration_ref": self.reference, "server_settings_ref": self.value["server_settings_ref"],
            "server_entry_ref": self.value["server_entry_ref"], "collection": self.value["collection"],
            "processing_fingerprint": self.value["processing_fingerprint"], "storage_root": settings.storage_root,
            "maximum_tool_queries": self.value["max_queries"], "maximum_llm_calls_per_query": llm_calls,
            "embedding_calls_scope": "separately observed; at most one query embedding input per RPC",
            "model_identity": {"provider": settings.llm.provider, "model": settings.llm.model,
                "revision": settings.query.model_revision if settings.query else None, "revision_origin": "caller_configured"},
            "os_sandbox_claimed": False, "target_code_executed": False}

    def bind(self, *, run_root, run_id, allow_source_disclosure=False, game_folder_dependency=None):
        from src.mod_agent.evidence.document_knowledge import DocumentKnowledgeAugmentation
        boundary = self.boundary(allow_source_disclosure=allow_source_disclosure)
        # 为什么要有它：知识查询预算和身份独立记录，不刷新coder预算，也不将文档变成编辑或执行授权。
        owner = DocumentKnowledgeAugmentation(self, Path(run_root), run_id, dependency_binding=game_folder_dependency)
        return owner, {"status": "configured", **boundary, "records_root": str(owner.root),
                       "dependency_validation": owner.verify_dependencies()}
