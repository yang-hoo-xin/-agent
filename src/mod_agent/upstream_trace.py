"""Read-only projections for upstream execution observations.

These helpers describe actually supplied values. They do not select evidence,
change model messages, infer private reasoning, or grant execution authority.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from contextlib import contextmanager
from functools import wraps
from typing import Any

from src.core.trace.execution_trace import current_trace, trace_operation


def payload_sha256(value: Any) -> str | None:
    try:
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    except Exception:
        # Legacy extension values may be valid for their owner without being
        # canonical JSON. Unknown trace identity must not become a product gate.
        return None


def material_identities(items) -> list[dict[str, Any]] | None:
    """Bind an evidence ID to its source and the exact supplied excerpt bytes."""
    try:
        return _material_identities(items)
    except Exception:
        # None means unavailable; [] would incorrectly claim no input material.
        return None


def _material_identities(items) -> list[dict[str, Any]]:
    identities = []
    for raw in items:
        item = raw.to_dict() if hasattr(raw, "to_dict") else raw
        excerpt = item.get("excerpt")
        identities.append({
            "evidence_id": item.get("evidence_id"),
            "source_type": item.get("source_type"),
            "source_hash": item.get("source_hash"),
            "excerpt_sha256": (
                hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
                if isinstance(excerpt, str) else None
            ),
        })
    return identities


def model_input_materials(payload: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    """Read only the actual source_observations payload, including its identity table.

    Findings currently sends no source_hash. It remains unknown here; evidence_id
    plus exact excerpt_sha256 can link to the source-bound retrieval observation.
    """
    try:
        table = payload.get("source_identity_table", [])
        observations = []
        for item in payload.get("source_observations", []):
            identity = {}
            if "source_identity_ref" in item:
                identity = table[item["source_identity_ref"]]
            observations.append({**identity, **item})
        return material_identities(observations)
    except Exception:
        return None


def findings_attributes(findings: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return _findings_attributes(findings)
    except Exception:
        return {"observation_projection_status": "unavailable", "reason_status": "reason_unavailable"}


def _findings_attributes(findings: Mapping[str, Any]) -> dict[str, Any]:
    rows = findings.get("findings", [])
    counts = Counter(row.get("relationship") for row in rows)
    gaps = sum(len(row.get("unresolved_gaps", [])) for row in rows)
    return {
        "structured_output_sha256": payload_sha256(findings),
        "relationship_counts": {name: counts[name] for name in ("support", "conflict", "missing")},
        "unresolved_gap_count": gaps,
        "selected_evidence_ids": list(dict.fromkeys(
            evidence_id for row in rows for evidence_id in row.get("evidence_ids", [])
        )),
        "decision_summary_origin": "deterministic_structured_result",
        "decision_summary": f"证据判断：支持 {counts['support']} 项，冲突 {counts['conflict']} 项，缺失 {counts['missing']} 项；未解决缺口 {gaps} 项。",
        "reason_status": "reason_unavailable",
    }


def update_observation(span, **attributes) -> None:
    """Observation projection errors must never change the product result."""
    try:
        span.update(**attributes)
    except Exception:
        # The core trace counts recorder/sink failures. This protects optional
        # projection code from becoming a second product gate.
        return


@contextmanager
def observe_local_tool_bodies(span, input_payload):
    """Retain actual arguments and a returned value, using the existing local store.

    为什么要有它：hashes and merged evidence cannot recover a discarded per-call result;
    observation failures must not replace the product's result or exception.
    """
    trace = current_trace()
    references, capture = {}, {}

    def retain(role, payload):
        if trace is None:
            return
        try:
            root = trace.context.metadata.get("local_body_root")
            if root is None or span.observation_id is None:
                capture[role] = {"status": "unknown", "reason": "local_body_root_unavailable"}
            else:
                # Imported at invocation time because the model observer also uses
                # these upstream projection helpers. No new body format or store.
                from src.mod_agent.upstream_model_trace import _json, _local_body

                reference = _local_body(root, span.observation_id, "tool." + role + ".json", _json(payload))
                references[role] = reference
                capture[role] = {"status": "retained"}
        except Exception as error:
            capture[role] = {"status": "unknown", "reason": "local_body_capture_failed",
                             "error_type": type(error).__name__}
        update_observation(span, local_detail_refs=dict(references),
                           local_tool_body_capture=dict(capture))

    retain("request", input_payload)
    try:
        yield lambda payload: retain("response", payload)
    except BaseException:
        capture.setdefault("response", {"status": "unknown", "reason": "business_exception_no_returned_payload"})
        update_observation(span, local_tool_body_capture=dict(capture))
        raise
    finally:
        if trace is not None and "response" not in capture:
            capture["response"] = {"status": "unknown", "reason": "no_returned_payload_recorded"}
            update_observation(span, local_tool_body_capture=dict(capture))


def observe_evidence_factory(factory):
    """Bind the final returned pack after audit enrichment and any fallback."""
    @wraps(factory)
    def observed(*args, **kwargs):
        if current_trace() is None:
            return factory(*args, **kwargs)
        with trace_operation("evidence.assemble") as span:
            result = factory(*args, **kwargs)
            try:
                from src.mod_agent.evidence.dotnet_metadata import _member_access_trace_values

                values = _member_access_trace_values(result)
                update_observation(span,
                    evidence_payload_sha256=values.get("payload_sha256"),
                    output_payload_sha256=values.get("payload_sha256"),
                    produced_materials=material_identities(result.items),
                    produced_member_access_fact_count=values.get("fact_count"),
                    produced_member_access_facts_sha256=values.get("facts_sha256"),
                    fact_delivery_status="evidence_pack_assembled_model_delivery_unproven",
                    readiness=result.readiness, can_generate_patch=result.can_generate_patch)
            except Exception:
                update_observation(span, observation_projection_status="unavailable")
            return result
    return observed
