"""Versioned, fail-closed quality-gate policy contracts."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QualityGatePolicy:
    policy_schema_version: str
    policy_id: str
    required_metric_names: tuple[str, ...]
    thresholds: Mapping[str, float]

    def __post_init__(self) -> None:
        for name, value in (
            ("policy_schema_version", self.policy_schema_version),
            ("policy_id", self.policy_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not self.required_metric_names or len(set(self.required_metric_names)) != len(
            self.required_metric_names
        ):
            raise ValueError("required_metric_names must be non-empty and unique")
        if set(self.thresholds) != set(self.required_metric_names):
            raise ValueError("thresholds must exactly cover required_metric_names")
        for name, value in self.thresholds.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"threshold for {name} must be numeric")
            if not math.isfinite(value) or not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"threshold for {name} must be finite and within [0, 1]")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> QualityGatePolicy:
        names = value.get("required_metric_names")
        thresholds = value.get("thresholds")
        if not isinstance(names, Sequence) or isinstance(names, (str, bytes)):
            raise ValueError("required_metric_names must be an array")
        if not isinstance(thresholds, Mapping):
            raise ValueError("thresholds must be an object")
        policy = cls(
            policy_schema_version=_required_string(value, "policy_schema_version"),
            policy_id=_required_string(value, "policy_id"),
            required_metric_names=tuple(_required_metric_name(item) for item in names),
            thresholds={str(name): threshold for name, threshold in thresholds.items()},
        )
        supplied_hash = value.get("policy_sha256")
        if supplied_hash is not None and supplied_hash != policy.policy_sha256:
            raise ValueError("policy_sha256 does not match policy content")
        return policy

    @property
    def policy_sha256(self) -> str:
        encoded = json.dumps(
            self.content_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def content_dict(self) -> dict[str, Any]:
        return {
            "policy_schema_version": self.policy_schema_version,
            "policy_id": self.policy_id,
            "required_metric_names": list(self.required_metric_names),
            "thresholds": dict(self.thresholds),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.content_dict(), "policy_sha256": self.policy_sha256}


def evaluate_quality_policy(
    policy: QualityGatePolicy,
    metrics: Mapping[str, Any],
    metric_directions: Mapping[str, bool],
) -> str:
    """Recompute a policy result; never trust a reported pass flag."""

    for name in policy.required_metric_names:
        if name not in metric_directions:
            return "fail"
        value = metrics.get(name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0.0 <= float(value) <= 1.0
        ):
            return "fail"
        threshold = float(policy.thresholds[name])
        if metric_directions[name] and float(value) < threshold:
            return "fail"
        if not metric_directions[name] and float(value) > threshold:
            return "fail"
    return "pass"


def _required_string(value: Mapping[str, Any], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return result


def _required_metric_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("required_metric_names entries must be non-empty strings")
    return value
