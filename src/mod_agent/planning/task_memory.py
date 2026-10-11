"""Source-bound task experience, stored only as versioned Artifacts.

This module projects selected execution-record values. It does not infer causes,
repairs, source authority, or permissions from those values. Applicability keys
and JSON locators are supplied explicitly and compared without normalization.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

from src.core.query_engine.tokenization import tokenize_retrieval_text

from ..artifacts import ArtifactRef, ArtifactStore, ArtifactStoreError

_SCHEMA = "source_bound_task_memory_v1"
_ROLES = frozenset({"observation", "failure", "verified_result"})


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256(value: Any) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _selector(value: Any, evidence_ids: set[str]) -> None:
    if not isinstance(value, dict) or value.get("evidence_id") not in evidence_ids:
        raise ValueError("Task memory selection requires an exact evidence_id")
    locator = value.get("locator")
    if not isinstance(locator, list) or any(
        not isinstance(part, (str, int)) or isinstance(part, bool)
        or (isinstance(part, int) and part < 0) for part in locator
    ):
        raise ValueError("Task memory locator must contain exact keys or non-negative indices")


def _select(document: Any, locator: list[str | int]) -> Any:
    current = document
    for part in locator:
        if isinstance(part, str) and isinstance(current, dict) and part in current:
            current = current[part]
        elif type(part) is int and isinstance(current, list) and 0 <= part < len(current):
            current = current[part]
        else:
            raise ValueError(f"Task memory exact locator is unavailable: {_json(locator)}")
    _json(current)
    return copy.deepcopy(current)


def _expiry(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Task memory expires_at must be an ISO timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Task memory expires_at must be an ISO timestamp with timezone") from exc
    if parsed.tzinfo is None:
        raise ValueError("Task memory expires_at must have an explicit timezone")
    return parsed


def validate_task_memory_payload(payload: dict[str, Any]) -> None:
    """Validate representation only; record/retrieve verify actual source bytes."""
    if payload.get("schema_version") != _SCHEMA or payload.get("authority") != "planning_only":
        raise ValueError("Task memory schema or planning-only authority is invalid")
    if not _nonempty(payload.get("lesson_id")):
        raise ValueError("Task memory lesson_id is required")
    if type(payload.get("revision")) is not int or payload["revision"] < 1:
        raise ValueError("Task memory revision must be a positive integer")
    previous = payload.get("previous_revision_ref")
    if payload["revision"] == 1 and previous is not None:
        raise ValueError("Initial task memory cannot have a previous revision")
    if payload["revision"] > 1 and not isinstance(previous, dict):
        raise ValueError("Updated task memory requires its previous revision")
    refs = payload.get("evidence_refs")
    if not isinstance(refs, list) or not refs:
        raise ValueError("Task memory requires bound evidence_refs")
    ids: set[str] = set()
    for ref in refs:
        if not isinstance(ref, dict) or not _nonempty(ref.get("evidence_id")):
            raise ValueError("Task memory evidence_id is required")
        if ref["evidence_id"] in ids:
            raise ValueError("Task memory evidence_id must be unique")
        ids.add(ref["evidence_id"])
        if ref.get("kind") == "json_file":
            if not _nonempty(ref.get("path")) or not Path(ref["path"]).is_absolute():
                raise ValueError("Task memory JSON evidence requires an absolute path")
            if not _sha256(ref.get("sha256")):
                raise ValueError("Task memory JSON evidence requires an exact sha256")
        elif ref.get("kind") == "artifact":
            artifact = ref.get("artifact_ref")
            if not isinstance(artifact, dict) or set(artifact) != {
                "feature_id", "artifact_type", "path", "artifact_hash"
            } or any(not _nonempty(value) for value in artifact.values()):
                raise ValueError("Task memory artifact evidence requires a full ArtifactRef")
            if not _sha256(artifact["artifact_hash"]):
                raise ValueError("Task memory ArtifactRef requires an exact artifact_hash")
            if "store_root" in ref and (not _nonempty(ref["store_root"])
                                         or not Path(ref["store_root"]).is_absolute()):
                raise ValueError("Task memory evidence store_root must be explicit and absolute")
        else:
            raise ValueError("Task memory supports only JSON file or Artifact evidence")
    for field in ("request", "outcome"):
        _selector(payload.get(field), ids)
        if "value" not in payload[field]:
            raise ValueError(f"Task memory {field} must retain its source value")
    request = payload["request"]
    if not _nonempty(request["value"]) or request.get("sha256") != _digest(request["value"]):
        raise ValueError("Task memory request must preserve exact text and sha256")
    facts = payload.get("facts")
    if not isinstance(facts, list) or not facts:
        raise ValueError("Task memory requires source-bound facts")
    for fact in facts:
        _selector(fact, ids)
        if not _nonempty(fact.get("scope")) or not _nonempty(fact.get("key")):
            raise ValueError("Task memory facts require explicit scope and key")
        if fact.get("role") not in _ROLES or "value" not in fact:
            raise ValueError("Task memory facts require a supported role and source value")
    applicability = payload.get("applicability")
    if not isinstance(applicability, dict) or not applicability:
        raise ValueError("Task memory requires explicit applicability conditions")
    if any(not _nonempty(key) or not isinstance(value, (str, int, float, bool, type(None)))
           for key, value in applicability.items()):
        raise ValueError("Task memory applicability must map exact keys to JSON scalars")
    for field in ("unknowns", "invalidation_conditions"):
        value = payload.get(field)
        if not isinstance(value, list) or any(not _nonempty(item) for item in value):
            raise ValueError(f"Task memory {field} must be a list of explicit statements")
    if not payload["invalidation_conditions"]:
        raise ValueError("Task memory requires explicit invalidation conditions")
    _expiry(payload.get("expires_at"))
    _json(payload)


class TaskMemory:
    """Record, revise, and retrieve planning hints through one ArtifactStore.

    A lesson owns one deterministic feature namespace, so separate lessons never
    overwrite each other. Updates name the exact previous revision. JSON-file
    evidence may live outside the Store; Artifact evidence is read through the
    supplied Store's guarded read API. No evidence body is copied to a new DB.
    """

    def __init__(self, store: ArtifactStore) -> None:
        self.store = store

    @staticmethod
    def _feature_id(lesson_id: str) -> str:
        return "task_memory_" + _digest(lesson_id)

    def _current(self, lesson_id: str) -> ArtifactRef | None:
        latest = next((ref for ref in self.store.list_feature_artifacts(
            self._feature_id(lesson_id)) if ref.artifact_type == "task_memory"), None)
        return self._immutable(latest) if latest else None

    def _immutable(self, ref: ArtifactRef) -> ArtifactRef:
        self.store.read(ref)
        for revision in self.store.list_feature_artifact_revisions(ref.feature_id, "task_memory"):
            if revision.artifact_hash == ref.artifact_hash:
                return revision
        raise ValueError("Task memory latest pointer has no registered immutable revision")

    def current(self, lesson_id: str) -> ArtifactRef | None:
        """Return the current immutable reference for an exact lesson id."""
        ref = self._current(lesson_id)
        if ref is not None:
            self.store.read(ref)
        return ref

    def execution_lesson_id(self, run_id: str, *, source_store: ArtifactStore | None = None) -> str:
        """Scope new imports to the resolved source Store and its exact run id.

        Legacy run-only lessons retain their existing namespace and revisions;
        importing into this namespace never migrates or supersedes them.
        """
        if not _nonempty(run_id):
            raise ValueError("Execution memory requires a run id")
        reader = source_store or self.store
        return "execution:" + _digest(str(reader.root)) + ":" + run_id

    def _read_evidence(self, refs: Sequence[dict[str, Any]]) -> dict[str, Any]:
        documents: dict[str, Any] = {}
        for ref in refs:
            if ref["kind"] == "json_file":
                raw = Path(ref["path"]).read_bytes()
                if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
                    raise ValueError(f"Task memory source hash changed: {ref['evidence_id']}")
                documents[ref["evidence_id"]] = json.loads(raw)
            else:
                reader = (ArtifactStore(ref["store_root"], registry=self.store.registry)
                          if "store_root" in ref else self.store)
                documents[ref["evidence_id"]] = reader.read(ArtifactRef(**ref["artifact_ref"]))
        return documents

    def record_execution(
        self, journal_ref: Mapping[str, str], *, source_store: ArtifactStore | None = None,
        previous_revision_ref: ArtifactRef | None = None,
    ) -> ArtifactRef:
        """Deterministically import the existing continuation journal format.

        Only observed status, budgets, identities, and worker outcomes are
        selected. Model prose, diagnoses, and proposed fixes are never promoted
        into lessons. The optional source_store explicitly locates the original
        Artifact owner when memory uses a separate persistent root.
        """
        if set(journal_ref) != {"path", "sha256"}:
            raise ValueError("Execution journal_ref requires exact path and sha256 fields")
        if not Path(journal_ref["path"]).is_absolute() or not _sha256(journal_ref["sha256"]):
            raise ValueError("Execution journal_ref requires an absolute path and exact sha256")
        evidence = {"evidence_id": "journal", "kind": "json_file", **dict(journal_ref)}
        journal = self._read_evidence([evidence])["journal"]
        feature_ref = ArtifactRef(**journal["selected_artifacts"]["feature_spec"])
        reader = source_store or self.store
        feature = reader.read(feature_ref)["data"]
        loop = journal["factory_receipt"]["patch_agent_loop"]
        for value in (journal["run_id"], feature["user_request"], feature["target_mod"], loop["model"]):
            if not _nonempty(value):
                raise ValueError("Execution memory requires bound run/request/target_mod/model identities")
        lesson_id = self.execution_lesson_id(journal["run_id"], source_store=reader)
        scope = lesson_id
        refs = [evidence, {"evidence_id": "feature_spec", "kind": "artifact",
                           "artifact_ref": asdict(feature_ref), "store_root": str(reader.root)}]
        selections: list[dict[str, Any]] = []

        def fact(key: str, locator: list[str | int], role: str = "observation") -> None:
            selections.append({"scope": scope, "key": key, "role": role,
                               "evidence_id": "journal", "locator": locator})

        # Keep physical outcome first so whole-fact context compression preserves it.
        fact("status", ["status"], "failure" if journal["status"] == "continuation_failed"
             else "observation")
        termination = loop.get("termination")
        if isinstance(termination, dict):
            # Upstream arguments/reasons originate in the model. Keep only
            # machine state for that case, not its proposed diagnosis or fix.
            for key in ("code", "status", "turn_index"):
                if key in termination:
                    fact("termination." + key, ["factory_receipt", "patch_agent_loop", "termination", key], "failure")
            if "upstream_request" not in termination and isinstance(termination.get("reason"), str):
                fact("termination.reason", ["factory_receipt", "patch_agent_loop", "termination", "reason"], "observation")
        for key in ("model_call_count", "max_model_calls", "proposal_admitted"):
            fact(key, [key])
        for key in ("model", "provider", "total_observation_bytes", "policy"):
            fact(key, ["factory_receipt", "patch_agent_loop", key])
        turns = journal["factory_receipt"]["worker_turns"]
        if not isinstance(turns, list):
            raise ValueError("Execution journal worker_turns must be a list")
        for index, turn in enumerate(turns):
            for key in ("status", "error_type", "request_ref"):
                if key in turn:
                    fact(f"worker_turns[{index}].{key}",
                         ["factory_receipt", "worker_turns", index, key])
            request_ref = turn.get("request_ref")
            if request_ref is not None:
                if not isinstance(request_ref, dict) or set(request_ref) != {"path", "sha256"}:
                    raise ValueError("Execution worker request_ref requires exact path and sha256")
                refs.append({"evidence_id": f"worker_request_{index}", "kind": "json_file",
                             **request_ref})
        args = {
            "lesson_id": lesson_id, "evidence_refs": refs,
            "request": {"evidence_id": "feature_spec", "locator": ["data", "user_request"]},
            "facts": selections, "outcome": {"evidence_id": "journal", "locator": ["status"]},
            "applicability": {"target_mod": feature["target_mod"], "model": loop["model"]},
            "unknowns": ["An execution outcome does not establish a root cause or a successful repair.",
                         "Current source, dependency API, and binding applicability require fresh evidence."],
            "invalidation_conditions": ["Reject changed evidence hashes or missing exact source selections.",
                                        "Reject absent or changed target_mod/model context.",
                                        "Revalidate source, APIs, bindings, and runtime before product decisions."],
        }
        current = self.current(lesson_id)
        if previous_revision_ref is not None and previous_revision_ref != current:
            raise ValueError("Execution memory previous revision is not current")
        if current is not None:
            payload = self.store.read(current)["data"]
            self._read_evidence(refs)
            selectors = [{key: item[key] for key in ("scope", "key", "role", "evidence_id", "locator")}
                         for item in payload["facts"]]
            if (payload["evidence_refs"] == refs and payload["applicability"] == args["applicability"]
                    and selectors == selections and payload["unknowns"] == args["unknowns"]
                    and payload["invalidation_conditions"] == args["invalidation_conditions"]):
                return current
        return self.record(**args, previous_revision_ref=current)

    def record(
        self, *, lesson_id: str, evidence_refs: Sequence[dict[str, Any]],
        request: dict[str, Any], facts: Sequence[dict[str, Any]],
        outcome: dict[str, Any], applicability: Mapping[str, Any],
        unknowns: Sequence[str], invalidation_conditions: Sequence[str],
        previous_revision_ref: ArtifactRef | None = None, expires_at: str | None = None,
    ) -> ArtifactRef:
        """Extract explicit source selections; reject inferred or supplied values.

        Selections contain ``evidence_id`` and ``locator`` (exact dictionary keys
        or array indices). Facts additionally contain ``scope``, ``key``, and
        ``role``: observation, failure, or verified_result. These roles describe
        the selected record; they do not certify its causal interpretation.
        """
        if not _nonempty(lesson_id):
            raise ValueError("Task memory lesson_id is required")
        current = self._current(lesson_id)
        if current != previous_revision_ref:
            raise ValueError("Task memory update requires the exact current previous_revision_ref")
        prior = self.store.read(current)["data"] if current else None
        refs = copy.deepcopy(list(evidence_refs))
        # Validate the evidence representation before any caller-selected reads.
        provisional = {
            "schema_version": _SCHEMA, "authority": "planning_only", "lesson_id": lesson_id,
            "revision": prior["revision"] + 1 if prior else 1,
            "previous_revision_ref": asdict(current) if current else None,
            "evidence_refs": refs, "request": {**request, "value": "pending", "sha256": _digest("pending")},
            "facts": [{**fact, "value": None} for fact in facts],
            "outcome": {**outcome, "value": None}, "applicability": dict(applicability),
            "unknowns": list(unknowns), "invalidation_conditions": list(invalidation_conditions),
            "expires_at": expires_at,
        }
        validate_task_memory_payload(provisional)
        documents = self._read_evidence(refs)

        def bound(selection: dict[str, Any]) -> dict[str, Any]:
            if "value" in selection or "sha256" in selection:
                raise ValueError("Task memory values must be extracted from evidence, not supplied")
            return {**copy.deepcopy(selection), "value": _select(
                documents[selection["evidence_id"]], selection["locator"])}

        bound_request = bound(request)
        if not _nonempty(bound_request["value"]):
            raise ValueError("Task memory request locator must select non-empty exact request text")
        bound_request["sha256"] = _digest(bound_request["value"])
        payload = {
            **provisional, "node_name": "record_task_memory", "stage": "task_memory",
            "message": "Source-bound execution experience; planning hints only.",
            "request": bound_request, "facts": [bound(fact) for fact in facts],
            "outcome": bound(outcome),
        }
        validate_task_memory_payload(payload)
        return self.store.write(
            feature_id=self._feature_id(lesson_id), artifact_type="task_memory", payload=payload,
            upstream_refs=[current] if current else [],
            exact_revision_upstream_types={"task_memory"} if current else set(),
        )

    def history(self, lesson_id: str) -> list[ArtifactRef]:
        """Return intact revisions in explicit revision order."""
        refs = self.store.list_feature_artifact_revisions(self._feature_id(lesson_id), "task_memory")
        return sorted(refs, key=lambda ref: self.store.read(ref)["data"]["revision"])

    def _revalidate(self, payload: dict[str, Any], context: Mapping[str, Any]) -> list[str]:
        reasons = []
        for key, expected in payload["applicability"].items():
            if key not in context:
                reasons.append(f"current_context missing exact key: {key}")
            elif _json(context[key]) != _json(expected):
                reasons.append(f"applicability changed: {key}")
        expires = _expiry(payload.get("expires_at"))
        if expires is not None and expires <= datetime.now(timezone.utc):
            reasons.append("experience expired")
        try:
            documents = self._read_evidence(payload["evidence_refs"])
            for selection in [payload["request"], payload["outcome"], *payload["facts"]]:
                observed = _select(documents[selection["evidence_id"]], selection["locator"])
                if _json(observed) != _json(selection["value"]):
                    reasons.append("stored selection does not match bound evidence")
        except (OSError, ValueError, ArtifactStoreError) as exc:
            reasons.append(str(exc))
        return reasons

    def retrieve(
        self, query: str, current_context: Mapping[str, Any], max_chars: int = 6000,
    ) -> dict[str, Any]:
        """Return bounded, source-checked planning context, never a permission.

        Ranking is BM25 over the existing shared tokenizer (k1=1.2, b=0.75),
        computed transiently over current applicable records. Compression drops
        complete fields/facts, never substrings, and retains the full ArtifactRef.
        Conflicting explicit scope/key/value records remain inspectable but are
        excluded from all three hint lists. No source text is executed.
        """
        if type(max_chars) is not int or max_chars < 256:
            raise ValueError("Task memory max_chars must be an integer of at least 256")
        result: dict[str, Any] = {
            "relevant_lessons": [], "failed_patterns": [], "reusable_patterns": [],
            "unavailable_evidence": [], "authority": "planning_only", "budget_omitted": 0,
        }
        rows: list[tuple[ArtifactRef, dict[str, Any]]] = []
        unavailable: list[dict[str, Any]] = []
        for feature_id in self.store.list_feature_ids():
            if not feature_id.startswith("task_memory_"):
                continue
            try:
                refs = self.store.list_feature_artifacts(feature_id)
                for ref in refs:
                    if ref.artifact_type != "task_memory":
                        continue
                    ref = self._immutable(ref)
                    payload = self.store.read(ref)["data"]
                    reasons = self._revalidate(payload, current_context)
                    if reasons:
                        unavailable.append({"artifact_ref": asdict(ref), "reasons": reasons})
                    else:
                        rows.append((ref, payload))
            except (OSError, ValueError, ArtifactStoreError) as exc:
                unavailable.append({"feature_id": feature_id, "reasons": [str(exc)]})
        conflicts: dict[tuple[str, str], dict[str, set[int]]] = {}
        for index, (_, payload) in enumerate(rows):
            for fact in payload["facts"]:
                values = conflicts.setdefault((fact["scope"], fact["key"]), {})
                values.setdefault(_json(fact["value"]), set()).add(index)
        conflicted: set[int] = set()
        for (scope, key), values in conflicts.items():
            if len(values) < 2:
                continue
            indices = sorted(set().union(*values.values()))
            conflicted.update(indices)
            unavailable.append({"reason": "conflicting_scope_key_values", "scope": scope, "key": key,
                                "artifact_refs": [asdict(rows[index][0]) for index in indices]})
        rows = [row for index, row in enumerate(rows) if index not in conflicted]
        tokens = [Counter(tokenize_retrieval_text(_json({
            "request": payload["request"]["value"], "facts": payload["facts"],
            "outcome": payload["outcome"]["value"], "applicability": payload["applicability"],
        }), lowercase=False)) for _, payload in rows]
        query_terms = set(tokenize_retrieval_text(query, lowercase=False))
        average_length = sum(sum(doc.values()) for doc in tokens) / max(len(tokens), 1)
        frequencies = Counter(term for doc in tokens for term in doc)

        def score(index: int) -> float:
            doc = tokens[index]
            length = sum(doc.values())
            return sum(
                math.log(1 + (len(rows) - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
                * (doc[term] * 2.2) / (doc[term] + 1.2 * (0.25 + 0.75 * length / max(average_length, 1)))
                for term in query_terms if doc[term]
            )

        ranked = sorted(((score(index), ref, payload) for index, (ref, payload) in enumerate(rows)),
                        key=lambda row: (-row[0], row[2]["lesson_id"]))

        def append_within_budget(field: str, entry: dict[str, Any]) -> bool:
            result[field].append(entry)
            if len(_json(result)) <= max_chars - 16:
                return True
            result[field].pop()
            return False

        for relevance, ref, payload in ranked:
            if relevance <= 0:
                continue
            summary = {
                "artifact_ref": asdict(ref), "lesson_id": payload["lesson_id"],
                "revision": payload["revision"], "authority": "planning_only",
                "applicability": payload["applicability"], "outcome": payload["outcome"],
                "unknowns": payload["unknowns"],
                "invalidation_conditions": payload["invalidation_conditions"],
                "evidence_refs": payload["evidence_refs"], "facts": payload["facts"],
                "request": payload["request"], "omitted_fact_count": 0,
            }
            while not append_within_budget("relevant_lessons", summary):
                if "request" in summary:
                    summary.pop("request")
                elif summary["facts"]:
                    summary["facts"] = summary["facts"][:-1]
                    summary["omitted_fact_count"] += 1
                else:
                    result["budget_omitted"] += 1
                    break
            else:
                for role, field in (("failure", "failed_patterns"),
                                    ("verified_result", "reusable_patterns")):
                    selected = [fact for fact in summary["facts"] if fact["role"] == role]
                    if selected and not append_within_budget(field, {
                        "artifact_ref": asdict(ref), "facts": selected, "authority": "planning_only",
                    }):
                        result["budget_omitted"] += 1
        for entry in unavailable:
            if not append_within_budget("unavailable_evidence", entry):
                result["budget_omitted"] += 1
        return result


def memory_model_view(retrieved: Mapping[str, Any], max_chars: int = 3000) -> dict[str, Any]:
    """Project selected facts without local paths, request bodies, or authority.

    Full evidence/Artifact references stay in the local retrieval receipt. Each
    projected fact names its lesson hash for a checked local join. Entire values
    containing absolute paths are omitted, never rewritten as different facts.
    """
    if type(max_chars) is not int or max_chars < 256:
        raise ValueError("Memory model view max_chars must be an integer of at least 256")

    def contains_path(value: Any) -> bool:
        if isinstance(value, str):
            # Cover standalone and embedded drive/UNC/POSIX paths; conservative
            # omission is preferable to disclosing an unapproved local filename.
            return (Path(value).is_absolute() or PureWindowsPath(value).is_absolute()
                    or re.search(r"[A-Za-z]:[\\/]|\\\\[^\\\s]+\\|(?:^|[\s=(\"'])/\S", value) is not None
                    or any(PureWindowsPath(part.strip('"\'(),;')).is_absolute()
                           or part.startswith(("/", "\\\\")) for part in value.split()))
        if isinstance(value, dict):
            return any(contains_path(key) or contains_path(item) for key, item in value.items())
        if isinstance(value, list):
            return any(contains_path(item) for item in value)
        return False

    result: dict[str, Any] = {"authority": "planning_only", "lessons": [], "omitted_count": 0}
    if retrieved.get("authority") != "planning_only":
        return result
    for lesson in retrieved.get("relevant_lessons", []):
        ref = lesson["artifact_ref"]
        facts = [{field: fact[field] for field in ("scope", "key", "value", "role")}
                 for fact in lesson["facts"]]
        view = {
            "lesson_id": lesson["lesson_id"], "artifact_hash": ref["artifact_hash"],
            "authority": "planning_only", "facts": [],
            "unknowns": [item for item in lesson["unknowns"] if not contains_path(item)],
            "invalidation_conditions": [item for item in lesson["invalidation_conditions"]
                                        if not contains_path(item)],
        }
        if contains_path(view):
            result["omitted_count"] += 1
            continue
        result["lessons"].append(view)
        for fact in facts:
            if contains_path(fact):
                result["omitted_count"] += 1
                continue
            view["facts"].append(fact)
            if len(_json(result)) > max_chars - 16:
                view["facts"].pop()
                result["omitted_count"] += 1
        if not view["facts"] or len(_json(result)) > max_chars - 16:
            result["lessons"].pop()
            result["omitted_count"] += 1
    return result
