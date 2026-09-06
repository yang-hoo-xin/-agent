"""Explicit local configuration for the existing Patch worker and evaluator.

A selected factory is trusted local Python code, not a model-selected tool or a
sandboxed plugin. Only its selected file bytes are verified here. Dependency,
validator-input, and execution-environment identities remain the evaluator's
responsibility; this loader does not create a verification identity.
"""

from __future__ import annotations

import hashlib
import json
import keyword
import re
import sys
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, fields
from pathlib import Path
from threading import RLock
from types import ModuleType
from typing import Any
from uuid import uuid4

from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopError, PatchAgentLoopPolicy

SCHEMA_VERSION = "patch_worker_configuration_v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class PatchWorkerConfigurationError(ValueError):
    """Reject a selected configuration or its local factory with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _error(code: str, message: str) -> PatchWorkerConfigurationError:
    return PatchWorkerConfigurationError(code, message)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate JSON object key.")
        result[name] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("Non-finite JSON number.")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _parse_object(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        # Also reject finite JSON syntax whose exponent overflows Python float.
        _canonical_bytes(value)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise _error("PATCH_WORKER_CONFIGURATION_JSON_INVALID", "Expected strict UTF-8 JSON.") from exc
    if type(value) is not dict:
        raise _error("PATCH_WORKER_CONFIGURATION_SHAPE_INVALID", "Expected one JSON object.")
    return value


def _read_bytes(path: Path, code: str) -> bytes:
    try:
        return path.read_bytes()
    except (OSError, ValueError) as exc:
        raise _error(code, "The selected local file could not be read.") from exc


def read_json_object(path: str | Path) -> dict[str, Any]:
    """Read a JSON object, rejecting duplicate keys and non-finite numbers."""
    try:
        selected = Path(path)
    except (TypeError, ValueError) as exc:
        raise _error("PATCH_WORKER_CONFIGURATION_READ_FAILED", "Invalid local JSON path.") from exc
    return _parse_object(_read_bytes(selected, "PATCH_WORKER_CONFIGURATION_READ_FAILED"))


def _file_reference(path: Path, raw: bytes) -> dict[str, str]:
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def _verified_factory_bytes(reference: dict[str, str]) -> bytes:
    raw = _read_bytes(Path(reference["path"]), "PATCH_BEHAVIOR_FACTORY_READ_FAILED")
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise _error("PATCH_BEHAVIOR_FACTORY_HASH_MISMATCH", "Selected factory bytes changed.")
    return raw


class _LazyBehaviorEvaluator:
    def __init__(
        self, *, configuration_ref: dict[str, str], factory_ref: dict[str, str],
        factory_name: str, kwargs: dict[str, Any],
    ) -> None:
        self._configuration_ref = dict(configuration_ref)
        self._factory_ref = dict(factory_ref)
        self._factory_name = factory_name
        self._kwargs = deepcopy(kwargs)
        self._kwargs_sha256 = hashlib.sha256(_canonical_bytes(kwargs)).hexdigest()
        self._delegate: Callable[..., Any] | None = None
        self._construction_error: PatchWorkerConfigurationError | None = None
        self._constructing = False
        self._lock = RLock()

    def configuration_receipt(self) -> dict[str, Any]:
        """Return detached identities checked at load; never construct or disclose kwargs."""
        return {
            "configuration_ref": dict(self._configuration_ref),
            "factory_ref": dict(self._factory_ref),
            "factory_name": self._factory_name,
            "kwargs_sha256": self._kwargs_sha256,
        }

    def prepare_for_patch_attempt(self) -> None:
        """Recheck source identities and construct once before the first model call."""
        self._get_delegate()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._get_delegate()(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        if name != "verification_identity":
            raise AttributeError(name)
        # Missing optional metadata must stay missing. In particular, do not
        # supply a method returning None to an owner that validates method output.
        return getattr(self._get_delegate(), name)

    def _get_delegate(self) -> Callable[..., Any]:
        with self._lock:
            config_bytes = _read_bytes(
                Path(self._configuration_ref["path"]), "PATCH_WORKER_CONFIGURATION_READ_FAILED"
            )
            if hashlib.sha256(config_bytes).hexdigest() != self._configuration_ref["sha256"]:
                raise _error("PATCH_WORKER_CONFIGURATION_CHANGED", "Selected configuration bytes changed.")
            raw = _verified_factory_bytes(self._factory_ref)
            if self._construction_error is not None:
                raise self._construction_error
            if self._delegate is not None:
                return self._delegate
            if self._constructing:
                raise _error("PATCH_BEHAVIOR_FACTORY_REENTRANT", "Factory construction is already active.")
            self._constructing = True
            try:
                self._delegate = self._construct(raw)
            except PatchWorkerConfigurationError as exc:
                # A failed import or constructor may already have side effects.
                # The same lazy object must not silently execute it a second time.
                self._construction_error = exc
                raise
            finally:
                self._constructing = False
            return self._delegate

    def _construct(self, raw: bytes) -> Callable[..., Any]:
        module_name = f"_mod_agent_patch_factory_{uuid4().hex}"
        module = ModuleType(module_name)
        module.__file__ = self._factory_ref["path"]
        module.__package__ = ""
        # Register only this loaded Python module so ordinary classes/dataclasses
        # work. No factory registry, sys.path extension, or dependency search is added.
        sys.modules[module_name] = module
        try:
            try:
                code = compile(raw, self._factory_ref["path"], "exec", dont_inherit=True)
                exec(code, module.__dict__)
            except (Exception, SystemExit) as exc:
                raise _error("PATCH_BEHAVIOR_FACTORY_LOAD_FAILED", "Selected factory source did not load.") from exc
            factory = module.__dict__.get(self._factory_name)
            if not callable(factory):
                raise _error("PATCH_BEHAVIOR_FACTORY_NOT_CALLABLE", "Exact factory export is absent or not callable.")
            try:
                delegate = factory(**deepcopy(self._kwargs))
            except (Exception, SystemExit) as exc:
                raise _error("PATCH_BEHAVIOR_FACTORY_CONSTRUCTION_FAILED", "Selected factory construction failed.") from exc
            if not callable(delegate):
                raise _error("PATCH_BEHAVIOR_EVALUATOR_NOT_CALLABLE", "Factory must return a callable evaluator.")
            return delegate
        except BaseException:
            sys.modules.pop(module_name, None)
            raise


@dataclass(frozen=True)
class PatchWorkerConfiguration:
    """One explicitly selected worker policy and optional lazy local evaluator."""

    policy: PatchAgentLoopPolicy
    enable_recovery_loop: bool
    _reference: dict[str, str]
    _evaluator: _LazyBehaviorEvaluator | None

    @property
    def reference(self) -> dict[str, str]:
        return dict(self._reference)

    def behavior_evaluator(self) -> _LazyBehaviorEvaluator | None:
        return self._evaluator

    @classmethod
    def load(cls, path: str | Path) -> PatchWorkerConfiguration:
        try:
            selected_path = Path(path).resolve()
        except (TypeError, ValueError, OSError) as exc:
            raise _error("PATCH_WORKER_CONFIGURATION_READ_FAILED", "Invalid local configuration path.") from exc
        raw = _read_bytes(selected_path, "PATCH_WORKER_CONFIGURATION_READ_FAILED")
        value = _parse_object(raw)
        if set(value) != {"schema_version", "policy", "enable_recovery_loop", "behavior_evaluator"}:
            raise _error("PATCH_WORKER_CONFIGURATION_SHAPE_INVALID", "Configuration fields must match the declared schema.")
        if value["schema_version"] != SCHEMA_VERSION:
            raise _error("PATCH_WORKER_CONFIGURATION_VERSION_INVALID", "Unsupported configuration schema version.")
        policy_value = value["policy"]
        allowed_fields = {item.name for item in fields(PatchAgentLoopPolicy)}
        if type(policy_value) is not dict or not set(policy_value).issubset(allowed_fields):
            raise _error("PATCH_WORKER_POLICY_INVALID", "Policy must use exact existing worker fields.")
        try:
            policy = PatchAgentLoopPolicy(**policy_value)
        except (PatchAgentLoopError, TypeError, ValueError) as exc:
            raise _error("PATCH_WORKER_POLICY_INVALID", "Worker policy values are invalid.") from exc
        recovery = value["enable_recovery_loop"]
        if type(recovery) is not bool:
            raise _error("PATCH_WORKER_CONFIGURATION_SHAPE_INVALID", "enable_recovery_loop must be boolean.")
        evaluator_value = value["behavior_evaluator"]
        if recovery and evaluator_value is None:
            raise _error("PATCH_WORKER_RECOVERY_EVALUATOR_REQUIRED", "Recovery requires a selected behavior evaluator.")
        configuration_ref = _file_reference(selected_path, raw)
        evaluator = None
        if evaluator_value is not None:
            if type(evaluator_value) is not dict or set(evaluator_value) != {"factory_ref", "factory_name", "kwargs"}:
                raise _error("PATCH_BEHAVIOR_FACTORY_CONFIGURATION_INVALID", "Evaluator fields must match the declared schema.")
            factory_ref = evaluator_value["factory_ref"]
            if type(factory_ref) is not dict or set(factory_ref) != {"path", "sha256"}:
                raise _error("PATCH_BEHAVIOR_FACTORY_REFERENCE_INVALID", "Factory requires an exact path/hash reference.")
            factory_path = factory_ref["path"]
            digest = factory_ref["sha256"]
            if (type(factory_path) is not str or not factory_path
                    or type(digest) is not str or _SHA256.fullmatch(digest) is None):
                raise _error("PATCH_BEHAVIOR_FACTORY_REFERENCE_INVALID", "Factory path or SHA256 is invalid.")
            local_path = Path(factory_path)
            if (not local_path.is_absolute() or local_path.suffix != ".py"
                    or factory_path.startswith(("\\\\", "//"))):
                raise _error("PATCH_BEHAVIOR_FACTORY_REFERENCE_INVALID", "Factory must be an absolute local .py file.")
            name = evaluator_value["factory_name"]
            if type(name) is not str or not name.isidentifier() or keyword.iskeyword(name):
                raise _error("PATCH_BEHAVIOR_FACTORY_NAME_INVALID", "Factory export must be one exact Python identifier.")
            kwargs = evaluator_value["kwargs"]
            if type(kwargs) is not dict:
                raise _error("PATCH_BEHAVIOR_FACTORY_KWARGS_INVALID", "Factory kwargs must be a JSON object.")
            _verified_factory_bytes(factory_ref)
            evaluator = _LazyBehaviorEvaluator(
                configuration_ref=configuration_ref, factory_ref=factory_ref,
                factory_name=name, kwargs=kwargs,
            )
        return cls(policy, recovery, configuration_ref, evaluator)


__all__ = [
    "PatchWorkerConfiguration",
    "PatchWorkerConfigurationError",
    "read_json_object",
]
