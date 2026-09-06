"""Offline qualification of explicit local factory loading and lazy construction."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from src.mod_agent.patch_worker_configuration import (
    PatchWorkerConfiguration,
    PatchWorkerConfigurationError,
    read_json_object,
)
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _write_configuration(tmp_path, source=None, *, kwargs=None):
    value = {
        "schema_version": "patch_worker_configuration_v1", "policy": {},
        "enable_recovery_loop": source is not None, "behavior_evaluator": None,
    }
    factory = None
    if source is not None:
        factory = tmp_path / "trusted_factory.py"
        factory.write_text(source, encoding="utf-8")
        value["behavior_evaluator"] = {
            "factory_ref": {"path": str(factory), "sha256": _sha(factory.read_bytes())},
            "factory_name": "make_evaluator", "kwargs": kwargs or {},
        }
    path = tmp_path / "worker.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path, factory, value


def _rewrite(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def test_disabled_evaluator_preserves_existing_policy_defaults_and_detached_reference(tmp_path):
    path, _, _ = _write_configuration(tmp_path)
    loaded = PatchWorkerConfiguration.load(path)
    assert loaded.policy == PatchAgentLoopPolicy()
    assert loaded.enable_recovery_loop is False
    assert loaded.behavior_evaluator() is None
    expected = {"path": str(path.resolve()), "sha256": _sha(path.read_bytes())}
    assert loaded.reference == expected
    loaded.reference["sha256"] = "changed"
    assert loaded.reference == expected


def test_loading_and_receipt_do_not_execute_source_or_construct_factory(tmp_path):
    marker = tmp_path / "side_effects.txt"
    source = f'''
from pathlib import Path
marker = Path({str(marker)!r})
with marker.open("a") as stream:
    stream.write("import\\n")
def make_evaluator():
    with marker.open("a") as stream:
        stream.write("construct\\n")
    def evaluate(context):
        with marker.open("a") as stream:
            stream.write("evaluate\\n")
        return context
    return evaluate
'''
    path, _, value = _write_configuration(tmp_path, source)
    loaded = PatchWorkerConfiguration.load(path)
    evaluator = loaded.behavior_evaluator()
    assert evaluator is loaded.behavior_evaluator()
    receipt = evaluator.configuration_receipt()
    assert not marker.exists()
    assert set(receipt) == {"configuration_ref", "factory_ref", "factory_name", "kwargs_sha256"}
    assert receipt["configuration_ref"] == loaded.reference
    assert receipt["factory_ref"] == value["behavior_evaluator"]["factory_ref"]
    receipt["factory_ref"]["sha256"] = "changed"
    assert evaluator.configuration_receipt()["factory_ref"] == value["behavior_evaluator"]["factory_ref"]
    evaluator.prepare_for_patch_attempt()
    evaluator.prepare_for_patch_attempt()
    assert marker.read_text().splitlines() == ["import", "construct"]
    assert evaluator({"evaluation_index": 1}) == {"evaluation_index": 1}
    assert marker.read_text().splitlines() == ["import", "construct", "evaluate"]


def test_optional_verification_identity_stays_absent_and_lazy_call_still_works(tmp_path):
    path, _, _ = _write_configuration(
        tmp_path, "def make_evaluator():\n    return lambda context: context\n"
    )
    evaluator = PatchWorkerConfiguration.load(path).behavior_evaluator()
    with pytest.raises(AttributeError, match="verification_identity"):
        _ = evaluator.verification_identity
    assert getattr(evaluator, "verification_identity", None) is None
    assert evaluator({"ok": True}) == {"ok": True}


def test_verification_identity_query_constructs_once_and_forwards_live_method(tmp_path):
    marker = tmp_path / "constructed.txt"
    source = f'''
from dataclasses import dataclass
from pathlib import Path
@dataclass
class Evaluator:
    identity_calls: int = 0
    def __call__(self, context):
        return context
    def verification_identity(self):
        self.identity_calls += 1
        return {{"identity_calls": self.identity_calls}}
def make_evaluator():
    with Path({str(marker)!r}).open("a") as stream:
        stream.write("construct\\n")
    return Evaluator()
'''
    path, _, _ = _write_configuration(tmp_path, source)
    evaluator = PatchWorkerConfiguration.load(path).behavior_evaluator()
    assert not marker.exists()
    assert evaluator.verification_identity() == {"identity_calls": 1}
    evaluator.prepare_for_patch_attempt()
    assert evaluator.verification_identity() == {"identity_calls": 2}
    assert marker.read_text().splitlines() == ["construct"]


def test_nested_kwargs_are_detached_from_configuration_and_receipt(tmp_path):
    source = '''
def make_evaluator(*, options):
    options["values"].append("factory_mutation")
    return lambda context: {"options": options, "context": context}
'''
    kwargs = {"options": {"values": [1], "flag": True, "empty": None}}
    path, _, value = _write_configuration(tmp_path, source, kwargs=kwargs)
    evaluator = PatchWorkerConfiguration.load(path).behavior_evaluator()
    expected_hash = _sha(json.dumps(kwargs, sort_keys=True, separators=(",", ":")).encode())
    first_receipt = evaluator.configuration_receipt()
    value["behavior_evaluator"]["kwargs"]["options"]["values"].append("caller_mutation")
    result = evaluator({"index": 1})
    assert result["options"]["values"] == [1, "factory_mutation"]
    assert evaluator.configuration_receipt() == first_receipt
    assert first_receipt["kwargs_sha256"] == expected_hash
    assert read_json_object(path)["behavior_evaluator"]["kwargs"]["options"]["values"] == [1]


def test_factory_hash_drift_is_rejected_before_source_execution(tmp_path):
    marker = tmp_path / "must_not_exist.txt"
    path, factory, _ = _write_configuration(tmp_path, "def make_evaluator():\n    return lambda context: context\n")
    evaluator = PatchWorkerConfiguration.load(path).behavior_evaluator()
    factory.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n", encoding="utf-8")
    with pytest.raises(PatchWorkerConfigurationError) as raised:
        evaluator.prepare_for_patch_attempt()
    assert raised.value.code == "PATCH_BEHAVIOR_FACTORY_HASH_MISMATCH"
    assert not marker.exists()


def test_configuration_drift_is_rejected_before_factory_construction(tmp_path):
    path, _, value = _write_configuration(tmp_path, "def make_evaluator():\n    return lambda context: context\n")
    evaluator = PatchWorkerConfiguration.load(path).behavior_evaluator()
    value["policy"]["max_tool_rounds"] = 4
    _rewrite(path, value)
    with pytest.raises(PatchWorkerConfigurationError) as raised:
        evaluator.prepare_for_patch_attempt()
    assert raised.value.code == "PATCH_WORKER_CONFIGURATION_CHANGED"


def test_compiles_the_exact_bytes_just_checked_without_a_loader_reread(tmp_path, monkeypatch):
    original = b"def make_evaluator():\n    return lambda context: 'verified'\n"
    changed = b"def make_evaluator():\n    return lambda context: 'changed'\n"
    path, factory, _ = _write_configuration(tmp_path, original.decode())
    original_on_disk = factory.read_bytes()
    evaluator = PatchWorkerConfiguration.load(path).behavior_evaluator()
    original_read = Path.read_bytes
    reads = []

    def read_then_change(selected):
        raw = original_read(selected)
        if selected == factory:
            reads.append(raw)
            factory.write_bytes(changed)
        return raw

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "read_bytes", read_then_change)
        assert evaluator({}) == "verified"
    assert reads == [original_on_disk]
    with pytest.raises(PatchWorkerConfigurationError) as raised:
        evaluator({})
    assert raised.value.code == "PATCH_BEHAVIOR_FACTORY_HASH_MISMATCH"


@pytest.mark.parametrize(("source", "code"), [
    ("raise RuntimeError('import failed')\n", "PATCH_BEHAVIOR_FACTORY_LOAD_FAILED"),
    ("def make_evaluator(:\n", "PATCH_BEHAVIOR_FACTORY_LOAD_FAILED"),
    ("def Make_Evaluator():\n    return lambda context: context\n", "PATCH_BEHAVIOR_FACTORY_NOT_CALLABLE"),
    ("make_evaluator = 3\n", "PATCH_BEHAVIOR_FACTORY_NOT_CALLABLE"),
    ("def make_evaluator():\n    raise RuntimeError('factory failed')\n", "PATCH_BEHAVIOR_FACTORY_CONSTRUCTION_FAILED"),
    ("def make_evaluator():\n    return {}\n", "PATCH_BEHAVIOR_EVALUATOR_NOT_CALLABLE"),
])
def test_source_export_and_construction_errors_are_lazy_and_coded(tmp_path, source, code):
    path, _, _ = _write_configuration(tmp_path, source)
    evaluator = PatchWorkerConfiguration.load(path).behavior_evaluator()
    with pytest.raises(PatchWorkerConfigurationError) as raised:
        evaluator.prepare_for_patch_attempt()
    assert raised.value.code == code


def test_failed_constructor_is_not_automatically_reexecuted(tmp_path):
    marker = tmp_path / "attempted.txt"
    source = f'''
from pathlib import Path
def make_evaluator():
    with Path({str(marker)!r}).open("a") as stream:
        stream.write("attempt\\n")
    raise ValueError("invalid local evaluator")
'''
    path, _, _ = _write_configuration(tmp_path, source)
    evaluator = PatchWorkerConfiguration.load(path).behavior_evaluator()
    for _ in range(2):
        with pytest.raises(PatchWorkerConfigurationError):
            evaluator.prepare_for_patch_attempt()
    assert marker.read_text().splitlines() == ["attempt"]


@pytest.mark.parametrize("policy", [
    {"unknown_policy": 3}, {"max_total_model_turns": 6}, {"max_total_model_turns": True},
    {"max_tool_rounds": 0}, {"allow_batched_reads": 1}, [], None,
])
def test_invalid_policy_uses_existing_policy_constraints(tmp_path, policy):
    path, _, value = _write_configuration(tmp_path)
    value["policy"] = policy
    _rewrite(path, value)
    with pytest.raises(PatchWorkerConfigurationError) as raised:
        PatchWorkerConfiguration.load(path)
    assert raised.value.code == "PATCH_WORKER_POLICY_INVALID"


def test_explicit_policy_fields_are_preserved_without_a_second_budget_owner(tmp_path):
    path, _, value = _write_configuration(tmp_path)
    value["policy"] = {"max_tool_rounds": 5, "max_total_model_turns": 4, "allow_batched_reads": True}
    _rewrite(path, value)
    actual = asdict(PatchWorkerConfiguration.load(path).policy)
    assert actual == {**asdict(PatchAgentLoopPolicy()), **value["policy"]}


@pytest.mark.parametrize(("change", "code"), [
    (lambda v: v.update(extra=True), "PATCH_WORKER_CONFIGURATION_SHAPE_INVALID"),
    (lambda v: v.pop("policy"), "PATCH_WORKER_CONFIGURATION_SHAPE_INVALID"),
    (lambda v: v.update(schema_version="other"), "PATCH_WORKER_CONFIGURATION_VERSION_INVALID"),
    (lambda v: v.update(enable_recovery_loop=1), "PATCH_WORKER_CONFIGURATION_SHAPE_INVALID"),
    (lambda v: v.update(behavior_evaluator=None), "PATCH_WORKER_RECOVERY_EVALUATOR_REQUIRED"),
    (lambda v: v.update(behavior_evaluator=[]), "PATCH_BEHAVIOR_FACTORY_CONFIGURATION_INVALID"),
    (lambda v: v["behavior_evaluator"].update(extra=True), "PATCH_BEHAVIOR_FACTORY_CONFIGURATION_INVALID"),
    (lambda v: v["behavior_evaluator"].update(factory_ref={}), "PATCH_BEHAVIOR_FACTORY_REFERENCE_INVALID"),
    (lambda v: v["behavior_evaluator"]["factory_ref"].update(path="relative.py"), "PATCH_BEHAVIOR_FACTORY_REFERENCE_INVALID"),
    (lambda v: v["behavior_evaluator"]["factory_ref"].update(sha256="A" * 64), "PATCH_BEHAVIOR_FACTORY_REFERENCE_INVALID"),
    (lambda v: v["behavior_evaluator"]["factory_ref"].update(sha256="0" * 64), "PATCH_BEHAVIOR_FACTORY_HASH_MISMATCH"),
    (lambda v: v["behavior_evaluator"].update(factory_name="module.make_evaluator"), "PATCH_BEHAVIOR_FACTORY_NAME_INVALID"),
    (lambda v: v["behavior_evaluator"].update(factory_name="class"), "PATCH_BEHAVIOR_FACTORY_NAME_INVALID"),
    (lambda v: v["behavior_evaluator"].update(kwargs=[]), "PATCH_BEHAVIOR_FACTORY_KWARGS_INVALID"),
])
def test_exact_shapes_names_and_references_are_required(tmp_path, change, code):
    path, _, value = _write_configuration(tmp_path, "def make_evaluator():\n    return lambda context: context\n")
    change(value)
    _rewrite(path, value)
    with pytest.raises(PatchWorkerConfigurationError) as raised:
        PatchWorkerConfiguration.load(path)
    assert raised.value.code == code


@pytest.mark.parametrize("raw", [
    b'{"value":1,"value":2}', b'{"outer":{"value":1,"value":2}}',
    b'{"value":NaN}', b'{"value":Infinity}', b'{"value":1e999}', b'\xff',
])
def test_shared_json_reader_rejects_duplicate_keys_non_finite_numbers_and_invalid_utf8(tmp_path, raw):
    path = tmp_path / "input.json"
    path.write_bytes(raw)
    with pytest.raises(PatchWorkerConfigurationError) as raised:
        read_json_object(path)
    assert raised.value.code == "PATCH_WORKER_CONFIGURATION_JSON_INVALID"


@pytest.mark.parametrize("raw", ["[]", "null", "1"])
def test_shared_json_reader_requires_one_object(tmp_path, raw):
    path = tmp_path / "input.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(PatchWorkerConfigurationError) as raised:
        read_json_object(path)
    assert raised.value.code == "PATCH_WORKER_CONFIGURATION_SHAPE_INVALID"
