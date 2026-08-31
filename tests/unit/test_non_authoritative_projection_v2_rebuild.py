from __future__ import annotations

import ast
import builtins
import copy
import inspect
import json
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import pytest

import src.observability.non_authoritative_projection_v2_rebuild as rebuild_module
from src.non_authoritative_projection.contracts_v2 import (
    ProjectionContractError,
    ProjectionViewV2,
)
from src.observability.non_authoritative_projection_v2_rebuild import (
    load_canonical_projection_view_v2,
    rebuild_projection_view_v2,
)


FIXTURE_ROOT = (
    Path(__file__).parents[1]
    / "fixtures"
    / "non_authoritative_projection"
    / "v2_rebuild"
)
PROJECT_ROOT = Path(__file__).parents[2]
MOD_AGENT_ROOT = PROJECT_ROOT / "src" / "mod_agent"
PROJECTION_V2_CONTRACT_PATH = (
    PROJECT_ROOT / "src" / "non_authoritative_projection" / "contracts_v2.py"
)
FORBIDDEN_CONTROL_IMPORT = (
    "src.observability.non_authoritative_projection_v2_rebuild"
)
EXPECTED_CANONICAL_SHA256 = (
    "44e51640d55937bc6c0e62dc110a0ecb01119d38f723e9723557cc8a4404a2c7"
)


def _fixture_bytes(name: str) -> bytes:
    return (FIXTURE_ROOT / name).read_bytes()


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _mapping_inputs(name: str) -> tuple[Mapping[str, object], ...]:
    decoded = json.loads(_fixture_bytes(name).decode("utf-8"))
    assert type(decoded) is list
    frozen = _freeze(decoded)
    assert type(frozen) is tuple
    assert all(isinstance(item, Mapping) for item in frozen)
    return cast(tuple[Mapping[str, object], ...], frozen)


def _snapshot(value: object) -> bytes:
    return json.dumps(
        _plain(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _all_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return set(value).union(*(_all_keys(item) for item in value.values()), set())
    if isinstance(value, (list, tuple)):
        return set().union(*(_all_keys(item) for item in value), set())
    return set()


def _plain_inputs(name: str) -> list[dict[str, Any]]:
    value = json.loads(_fixture_bytes(name).decode("utf-8"))
    assert type(value) is list
    assert all(type(item) is dict for item in value)
    return cast(list[dict[str, Any]], value)


def _select_fact(
    facts: list[dict[str, Any]],
    *,
    owner: str,
    run_id: str | None,
    owner_sequence: int | None,
) -> dict[str, Any]:
    return next(
        item
        for item in facts
        if item["fact"]["owner"] == owner
        and item["fact"]["run_id"] == run_id
        and item["fact"]["owner_sequence"] == owner_sequence
    )


def _select_edge(
    edges: list[dict[str, Any]],
    *,
    run_id: str,
    owner_sequence: int,
) -> dict[str, Any]:
    return next(
        item
        for item in edges
        if item["source"]["run_id"] == run_id
        and item["source"]["owner_sequence"] == owner_sequence
    )


def _baseline_view() -> ProjectionViewV2:
    return rebuild_projection_view_v2(
        _fixture_bytes("unordered_facts.json"),
        _fixture_bytes("unordered_edges.json"),
    )


def _module_name(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).with_suffix("").as_posix().replace("/", ".")


def _resolve_import_from(current_module: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    package = current_module.split(".")[:-1]
    parent_hops = node.level - 1
    if parent_hops > len(package):
        return ""
    anchor = package[: len(package) - parent_hops]
    if node.module:
        anchor.extend(node.module.split("."))
    return ".".join(anchor)


def _imported_names_from_tree(
    current_module: str,
    tree: ast.Module,
) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_import_from(current_module, node)
            if base:
                imported.add(base)
            imported.update(
                f"{base}.{alias.name}" if base else alias.name
                for alias in node.names
            )
    return imported


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return _imported_names_from_tree(_module_name(path), tree)


def _imported_names_from_source(current_module: str, source: str) -> set[str]:
    return _imported_names_from_tree(current_module, ast.parse(source))


def _imports_rebuild_entry(name: str) -> bool:
    return name == FORBIDDEN_CONTROL_IMPORT or name.startswith(
        FORBIDDEN_CONTROL_IMPORT + "."
    )


def _assert_complete_mod_agent_tree_has_no_dependency_on_v2_rebuild_entry() -> None:
    violations: list[str] = []
    for path in sorted(MOD_AGENT_ROOT.rglob("*.py")):
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        for imported in sorted(_imported_names(path)):
            if _imports_rebuild_entry(imported):
                violations.append(f"{relative_path}: {imported}")

    assert violations == []


def _assert_control_import_guard_resolves_exact_absolute_and_relative_paths() -> None:
    absolute = _imported_names_from_source(
        "src.mod_agent.future_control",
        "from src.observability import non_authoritative_projection_v2_rebuild",
    )
    relative = _imported_names_from_source(
        "src.mod_agent.workflow.future_control",
        (
            "from ...observability.non_authoritative_projection_v2_rebuild "
            "import rebuild_projection_view_v2"
        ),
    )
    existing_absolute = _imported_names_from_source(
        "src.mod_agent.future_control",
        "import src.observability.dashboard.app",
    )
    existing_relative = _imported_names_from_source(
        "src.mod_agent.workflow.future_control",
        "from ...observability.dashboard import app",
    )

    assert FORBIDDEN_CONTROL_IMPORT in absolute
    assert FORBIDDEN_CONTROL_IMPORT in relative
    assert any(_imports_rebuild_entry(name) for name in absolute)
    assert any(_imports_rebuild_entry(name) for name in relative)
    assert "src.observability.dashboard.app" in existing_absolute
    assert "src.observability.dashboard.app" in existing_relative
    assert not any(_imports_rebuild_entry(name) for name in existing_absolute)
    assert not any(_imports_rebuild_entry(name) for name in existing_relative)


def test_unordered_trusted_mapping_and_json_bytes_rebuild_stable_scoped_view() -> None:
    facts = _mapping_inputs("unordered_facts.json")
    edges = _mapping_inputs("unordered_edges.json")
    facts_before = _snapshot(facts)
    edges_before = _snapshot(edges)
    facts_bytes = _fixture_bytes("unordered_facts.json")
    edges_bytes = _fixture_bytes("unordered_edges.json")

    from_mappings = rebuild_projection_view_v2(
        tuple(reversed(facts)),
        tuple(reversed(edges)),
    )
    from_json = rebuild_projection_view_v2(facts_bytes, edges_bytes)
    repeated = rebuild_projection_view_v2(facts, edges)

    assert isinstance(from_json, ProjectionViewV2)
    assert from_mappings == from_json == repeated
    assert from_mappings.canonical_bytes() == from_json.canonical_bytes()
    assert from_mappings.canonical_sha256() == EXPECTED_CANONICAL_SHA256
    assert from_json.diagnostics == ()
    assert len(from_json.facts) == 4
    assert len(from_json.edges) == 3

    product_refs = tuple(
        fact.ref for fact in from_json.facts if fact.ref.owner == "product_execution"
    )
    revision_refs = tuple(
        fact.ref for fact in from_json.facts if fact.ref.owner == "artifact_store"
    )
    assert len(product_refs) == 3
    assert len(revision_refs) == 1
    assert {ref.owner_sequence for ref in product_refs} == {4, 5}
    assert {ref.run_id for ref in product_refs} == {
        "run_projection_rebuild_001",
        "run_projection_rebuild_002",
    }
    assert {
        ref.owner_sequence
        for ref in product_refs
        if ref.run_id == "run_projection_rebuild_001"
    } == {4, 5}
    assert {
        (ref.run_id, ref.request_id)
        for ref in product_refs
        if ref.owner_sequence == 4
    } == {
        ("run_projection_rebuild_001", "request_projection_rebuild_001"),
        ("run_projection_rebuild_002", "request_projection_rebuild_002"),
    }
    assert len({ref.artifact_ref for ref in product_refs}) == 1
    assert {edge.target for edge in from_json.edges} == {revision_refs[0]}
    assert all(edge.source.owner == "product_execution" for edge in from_json.edges)
    assert all(edge.reporter.fact == edge.source for edge in from_json.edges)

    assert _snapshot(facts) == facts_before
    assert _snapshot(edges) == edges_before
    assert facts_bytes == _fixture_bytes("unordered_facts.json")
    assert edges_bytes == _fixture_bytes("unordered_edges.json")


def test_complete_view_has_a_separate_strict_canonical_read_path() -> None:
    view = _baseline_view()
    canonical_bytes = view.canonical_bytes()
    view_mapping = view.to_dict()
    mapping_before = _snapshot(view_mapping)

    assert load_canonical_projection_view_v2(canonical_bytes) == view
    assert load_canonical_projection_view_v2(MappingProxyType(view_mapping)) == view
    assert view.canonical_sha256() == EXPECTED_CANONICAL_SHA256
    assert canonical_bytes == view.canonical_bytes()
    assert _snapshot(view_mapping) == mapping_before

    noncanonical_bytes = _fixture_bytes("noncanonical_view.json")
    assert json.loads(noncanonical_bytes.decode("utf-8")) == view.to_dict()
    with pytest.raises(ProjectionContractError, match="bytes are non-canonical"):
        load_canonical_projection_view_v2(noncanonical_bytes)
    with pytest.raises(ProjectionContractError, match="bytes are non-canonical"):
        load_canonical_projection_view_v2(canonical_bytes + b"\n")
    escaped_key = canonical_bytes.replace(
        b'"schema_version"',
        b'"\\u0073chema_version"',
        1,
    )
    assert json.loads(escaped_key.decode("utf-8")) == view.to_dict()
    with pytest.raises(ProjectionContractError, match="bytes are non-canonical"):
        load_canonical_projection_view_v2(escaped_key)

    unknown = copy.deepcopy(view.to_dict())
    unknown["unknown"] = None
    with pytest.raises(ProjectionContractError, match="fields or field order"):
        load_canonical_projection_view_v2(unknown)

    reordered_facts = copy.deepcopy(view.to_dict())
    reordered_facts["facts"].reverse()
    with pytest.raises(ProjectionContractError, match="serialization order"):
        load_canonical_projection_view_v2(reordered_facts)

    reordered_edges = copy.deepcopy(view.to_dict())
    reordered_edges["edges"].reverse()
    with pytest.raises(ProjectionContractError, match="serialization order"):
        load_canonical_projection_view_v2(reordered_edges)

    wrong_view_schema = copy.deepcopy(view.to_dict())
    wrong_view_schema["schema_version"] = "1"
    with pytest.raises(ProjectionContractError, match="schema version"):
        load_canonical_projection_view_v2(wrong_view_schema)


def test_json_bytes_reject_duplicate_keys_nonstandard_values_and_wrong_shapes() -> None:
    with pytest.raises(ProjectionContractError, match="duplicate key: path"):
        rebuild_projection_view_v2(
            _fixture_bytes("duplicate_nested_key_facts.json"),
            b"[]",
        )

    with pytest.raises(ProjectionContractError, match="duplicate key: schema_version"):
        rebuild_projection_view_v2(
            b'[{"schema_version":"2","schema_version":"2"}]',
            b"[]",
        )

    duplicate_view_key = (
        b'{"schema_version":"2","schema_version":"2",'
        b'"facts":[],"edges":[],"diagnostics":[]}'
    )
    with pytest.raises(ProjectionContractError, match="duplicate key: schema_version"):
        load_canonical_projection_view_v2(duplicate_view_key)

    with pytest.raises(ProjectionContractError, match="non-standard numeric constant"):
        rebuild_projection_view_v2(b'[{"schema_version":NaN}]', b"[]")
    with pytest.raises(ProjectionContractError, match="strict UTF-8 JSON"):
        rebuild_projection_view_v2(b"\xff", b"[]")
    with pytest.raises(ProjectionContractError, match="strict UTF-8 JSON"):
        load_canonical_projection_view_v2(
            b"\xef\xbb\xbf"
            b'{"schema_version":"2","facts":[],"edges":[],"diagnostics":[]}'
        )
    with pytest.raises(ProjectionContractError, match="strict UTF-8 JSON"):
        rebuild_projection_view_v2(b"[] []", b"[]")
    with pytest.raises(ProjectionContractError, match="exact array"):
        rebuild_projection_view_v2(b"{}", b"[]")
    with pytest.raises(ProjectionContractError, match="items must be mappings"):
        rebuild_projection_view_v2(b"[1]", b"[]")
    with pytest.raises(ProjectionContractError, match="exact object"):
        load_canonical_projection_view_v2(b"[]")
    with pytest.raises(ProjectionContractError, match="schema version"):
        load_canonical_projection_view_v2(
            b'{"schema_version":"1","facts":[],"edges":[],"diagnostics":[]}'
        )


def test_wrong_fields_schema_hashes_and_scalar_shapes_fail_before_rebuild() -> None:
    baseline_fact = _plain_inputs("unordered_facts.json")[0]
    baseline_edge = _plain_inputs("unordered_edges.json")[0]
    invalid_facts: list[dict[str, Any]] = []

    unknown = copy.deepcopy(baseline_fact)
    unknown["unknown"] = None
    invalid_facts.append(unknown)

    nested_unknown = copy.deepcopy(baseline_fact)
    nested_unknown["fact"]["artifact_ref"]["unknown"] = None
    invalid_facts.append(nested_unknown)

    wrong_schema = copy.deepcopy(baseline_fact)
    wrong_schema["schema_version"] = "1"
    invalid_facts.append(wrong_schema)

    wrong_payload_schema = copy.deepcopy(baseline_fact)
    wrong_payload_schema["payload_schema_version"] = "1"
    invalid_facts.append(wrong_payload_schema)

    uppercase_hash = copy.deepcopy(baseline_fact)
    uppercase_hash["fact"]["artifact_ref"]["artifact_hash"] = "A" * 64
    invalid_facts.append(uppercase_hash)

    payload_hash_drift = copy.deepcopy(baseline_fact)
    payload_hash_drift["payload_sha256"] = "b" * 64
    invalid_facts.append(payload_hash_drift)

    bool_sequence = copy.deepcopy(baseline_fact)
    bool_sequence["fact"]["owner_sequence"] = True
    invalid_facts.append(bool_sequence)

    reordered = copy.deepcopy(baseline_fact)
    reordered = {
        "fact": reordered["fact"],
        "schema_version": reordered["schema_version"],
        "payload_sha256": reordered["payload_sha256"],
        "payload_schema_version": reordered["payload_schema_version"],
    }
    invalid_facts.append(reordered)

    for invalid_fact in invalid_facts:
        with pytest.raises(ProjectionContractError):
            rebuild_projection_view_v2((invalid_fact,), ())

    wrong_edge_schema = copy.deepcopy(baseline_edge)
    wrong_edge_schema["schema_version"] = "1"
    with pytest.raises(ProjectionContractError, match="schema version"):
        rebuild_projection_view_v2((), (wrong_edge_schema,))

    unsupported_relation = copy.deepcopy(baseline_edge)
    unsupported_relation["relation"] = "inferred_from_order"
    with pytest.raises(ProjectionContractError, match="relation is unsupported"):
        rebuild_projection_view_v2((), (unsupported_relation,))


def test_duplicate_identity_edge_diagnostic_and_occurrence_drift_fail_closed() -> None:
    facts = _plain_inputs("unordered_facts.json")
    edges = _plain_inputs("unordered_edges.json")

    with pytest.raises(ProjectionContractError, match="duplicate complete fact identity"):
        rebuild_projection_view_v2(tuple((*facts, copy.deepcopy(facts[0]))), ())
    with pytest.raises(ProjectionContractError, match="duplicate edge"):
        rebuild_projection_view_v2(tuple(facts), tuple((*edges, copy.deepcopy(edges[0]))))

    original = _select_fact(
        facts,
        owner="product_execution",
        run_id="run_projection_rebuild_001",
        owner_sequence=4,
    )
    drifted = copy.deepcopy(original)
    drifted["fact"]["artifact_ref"]["path"] = (
        "C:/store/features/feature_projection_v2_rebuild_001/r/"
        "patch_proposal/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.json"
    )
    drifted["fact"]["artifact_ref"]["artifact_hash"] = "b" * 64
    drifted["payload_sha256"] = "b" * 64
    with pytest.raises(ProjectionContractError, match="maps to multiple Artifact identities"):
        rebuild_projection_view_v2((original, drifted), ())

    revision = _select_fact(
        facts,
        owner="artifact_store",
        run_id=None,
        owner_sequence=None,
    )
    edge = copy.deepcopy(
        _select_edge(
            edges,
            run_id="run_projection_rebuild_001",
            owner_sequence=4,
        )
    )
    edge["relation"] = "conflicts_with"
    conflict = rebuild_projection_view_v2((original, revision), (edge,))
    assert len(conflict.diagnostics) == 1

    duplicate_diagnostic = copy.deepcopy(conflict.to_dict())
    duplicate_diagnostic["diagnostics"].append(
        copy.deepcopy(duplicate_diagnostic["diagnostics"][0])
    )
    with pytest.raises(ProjectionContractError, match="duplicate diagnostic"):
        load_canonical_projection_view_v2(duplicate_diagnostic)
    duplicate_diagnostic_bytes = json.dumps(
        duplicate_diagnostic,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    with pytest.raises(ProjectionContractError, match="duplicate diagnostic"):
        load_canonical_projection_view_v2(duplicate_diagnostic_bytes)

    altered_diagnostic = copy.deepcopy(conflict.to_dict())
    altered_diagnostic["diagnostics"][0]["edge_sha256"] = "0" * 64
    with pytest.raises(ProjectionContractError, match="complete inputs"):
        load_canonical_projection_view_v2(altered_diagnostic)


def test_missing_mismatch_and_conflict_remain_item_level_without_adjudication() -> None:
    facts = _plain_inputs("unordered_facts.json")
    edges = _plain_inputs("unordered_edges.json")
    source = _select_fact(
        facts,
        owner="product_execution",
        run_id="run_projection_rebuild_001",
        owner_sequence=4,
    )
    revision = _select_fact(
        facts,
        owner="artifact_store",
        run_id=None,
        owner_sequence=None,
    )
    edge = _select_edge(
        edges,
        run_id="run_projection_rebuild_001",
        owner_sequence=4,
    )

    missing_target = rebuild_projection_view_v2((source,), (edge,))
    missing_source = rebuild_projection_view_v2((revision,), (edge,))
    assert [item.code for item in missing_target.diagnostics] == [
        "missing_target_fact"
    ]
    assert {item.code for item in missing_source.diagnostics} == {
        "missing_source_fact",
        "missing_reporter_fact",
    }

    mismatch_edge = copy.deepcopy(edge)
    mismatch_edge["reporter"]["payload_sha256"] = "0" * 64
    mismatch_edge["reporter"]["owner_sequence"] = 9
    mismatch = rebuild_projection_view_v2((source, revision), (mismatch_edge,))
    assert {item.code for item in mismatch.diagnostics} == {
        "reporter_payload_sha256_mismatch",
        "reporter_owner_sequence_mismatch",
    }

    mismatch_reordered = copy.deepcopy(mismatch.to_dict())
    mismatch_reordered["diagnostics"].reverse()
    with pytest.raises(ProjectionContractError, match="complete inputs"):
        load_canonical_projection_view_v2(mismatch_reordered)

    conflict_edge = copy.deepcopy(edge)
    conflict_edge["relation"] = "conflicts_with"
    conflict = rebuild_projection_view_v2((source, revision), (conflict_edge,))
    assert [item.code for item in conflict.diagnostics] == ["explicit_conflict"]
    assert {fact.ref for fact in conflict.facts} == {
        conflict.diagnostics[0].primary_fact,
        conflict.diagnostics[0].related_fact,
    }
    assert _all_keys(conflict.to_dict()).isdisjoint(
        {
            "replay_promotion",
            "fresh_actual_status",
            "pause",
            "resume",
            "retry",
            "admission",
            "first_failure",
            "failure_chain",
            "claim",
            "claim_impact",
            "queue",
            "recovery",
            "winner",
            "final_status",
            "apply_authorized",
            "repair_required",
            "next_attempt_authorized",
        }
    )


def test_artifact_store_revision_is_target_only_and_cannot_invent_scope() -> None:
    facts = _plain_inputs("unordered_facts.json")
    edges = _plain_inputs("unordered_edges.json")
    baseline = rebuild_projection_view_v2(tuple(facts), tuple(edges))
    assert all(edge.target.owner == "artifact_store" for edge in baseline.edges)

    invalid_source = copy.deepcopy(edges[0])
    invalid_source["source"] = copy.deepcopy(invalid_source["target"])
    invalid_source["reporter"]["fact"] = copy.deepcopy(invalid_source["target"])
    invalid_source["reporter"]["owner_sequence"] = 0
    with pytest.raises(ProjectionContractError, match="cannot report without"):
        rebuild_projection_view_v2((), (invalid_source,))

    revision = copy.deepcopy(
        _select_fact(
            facts,
            owner="artifact_store",
            run_id=None,
            owner_sequence=None,
        )
    )
    revision["fact"]["run_id"] = "invented_run"
    with pytest.raises(ProjectionContractError, match="must be null"):
        rebuild_projection_view_v2((revision,), ())


def test_trusted_pure_data_inputs_are_read_only_and_entry_has_no_write_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _mapping_inputs("unordered_facts.json")
    edges = _mapping_inputs("unordered_edges.json")
    facts_before = _snapshot(facts)
    edges_before = _snapshot(edges)
    facts_bytes = _fixture_bytes("unordered_facts.json")
    edges_bytes = _fixture_bytes("unordered_edges.json")

    class AbilitySentinel:
        iterated = False

        def __iter__(self):
            self.iterated = True
            return iter(())

    sentinel = AbilitySentinel()
    with pytest.raises(ProjectionContractError, match="exact tuple"):
        rebuild_projection_view_v2(cast(Any, sentinel), ())
    assert sentinel.iterated is False

    def blocked_open(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("The pure rebuild entry attempted file access.")

    monkeypatch.setattr(builtins, "open", blocked_open)
    before_paths = tuple(tmp_path.rglob("*"))
    from_mappings = rebuild_projection_view_v2(facts, edges)
    from_bytes = rebuild_projection_view_v2(facts_bytes, edges_bytes)
    loaded = load_canonical_projection_view_v2(from_bytes.canonical_bytes())

    assert from_mappings == from_bytes == loaded
    assert tuple(tmp_path.rglob("*")) == before_paths == ()
    assert _snapshot(facts) == facts_before
    assert _snapshot(edges) == edges_before


def test_module_and_control_dependencies_preserve_projection_boundary() -> None:
    _assert_complete_mod_agent_tree_has_no_dependency_on_v2_rebuild_entry()
    _assert_control_import_guard_resolves_exact_absolute_and_relative_paths()
    contract_imports = _imported_names(PROJECTION_V2_CONTRACT_PATH)
    assert not any(_imports_rebuild_entry(name) for name in contract_imports)

    source = inspect.getsource(rebuild_module)
    tree = ast.parse(source)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)

    assert imports == {
        "__future__",
        "collections.abc",
        "json",
        "src.non_authoritative_projection.contracts_v2",
        "typing",
    }
    assert tuple(inspect.signature(rebuild_projection_view_v2).parameters) == (
        "facts",
        "edges",
    )
    assert tuple(
        inspect.signature(load_canonical_projection_view_v2).parameters
    ) == ("value",)
    for forbidden in (
        "ProductExecutor",
        "Graph",
        "ActualRunner",
        "ArtifactStore",
        "Repair",
        "Apply",
        "Retry",
        "permission",
        "checkpoint",
        "Path(",
        "open(",
        ".write",
    ):
        assert forbidden not in source
