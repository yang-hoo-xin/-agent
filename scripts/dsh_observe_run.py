"""Deliver explicitly graded page observations to the existing runtime exchange."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
import time
from pathlib import Path

from src.mod_agent.runtime.gtfo_automation import (
    GTFOOperatorCompletionRequest,
    _read_operator_completion,
)

MAX_BYTES = 32768


def _root(directory):
    root = Path(directory)
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("OBSERVATION_DIRECTORY_UNAVAILABLE")
    return root.resolve()


def _path(root, request_id, suffix):
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", request_id):
        raise ValueError("OBSERVATION_REQUEST_ID_INVALID")
    path = root / (request_id + suffix)
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("OBSERVATION_EXCHANGE_NOT_PLAIN_FILE")
    return path


def _request(root, request_id):
    path = _path(root, request_id, ".request.json")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("OBSERVATION_REQUEST_TOO_LARGE")
    exchange = json.loads(path.read_text(encoding="utf-8"))
    data = exchange["request"]
    criteria = data["acceptance_criteria"]
    request = GTFOOperatorCompletionRequest(
        request_id=data["request_id"], feature_id=data["feature_id"], profile_id=data["profile_id"],
        runtime_process_pid=data["runtime_process_pid"], timeout_seconds=data["timeout_seconds"],
        acceptance_criteria=tuple(row["acceptance_criterion"] for row in criteria),
        operator_guidance={row["acceptance_criterion"]: row["operator_guidance"]
                           for row in criteria if row.get("operator_guidance")},
    )
    if (exchange["event"] != "GTFO_OPERATOR_COMPLETION_REQUIRED" or request.request_id != request_id
            or request.to_dict() != data):
        raise ValueError("OBSERVATION_REQUEST_IDENTITY_INVALID")
    if time.time() >= path.stat().st_mtime + request.timeout_seconds:
        raise ValueError("OBSERVATION_REQUEST_EXPIRED")
    return request


def pending_observations(directory):
    root = _root(directory)
    requests = []
    for path in sorted(root.glob("*.request.json")):
        request_id = path.name.removesuffix(".request.json")
        if _path(root, request_id, ".confirmation.json").exists():
            continue
        try:
            requests.append(_request(root, request_id).to_dict())
        except ValueError as exc:
            if str(exc) != "OBSERVATION_REQUEST_EXPIRED":
                raise
    return {"entry": "dsh-observation", "status": "pending" if requests else "none_pending",
            "read_only": True, "requests": requests, "model_calls_performed": 0,
            "runtime_success_claimed": False}


def submit_observations(directory, response):
    root = _root(directory)
    request_id = response["request_id"]
    response_path = _path(root, request_id, ".response.json")
    confirmation_path = _path(root, request_id, ".confirmation.json")
    if response_path.exists() or confirmation_path.exists():
        raise ValueError("OBSERVATION_ALREADY_SUBMITTED")
    request = _request(root, request_id)
    data = request.to_dict()
    if response.get("request_sha256") != data["request_sha256"]:
        raise ValueError("OBSERVATION_DISPLAYED_REQUEST_CHANGED")
    rows = response["observations"]
    if not isinstance(rows, list) or len(rows) != len(data["acceptance_criteria"]):
        raise ValueError("OBSERVATION_ALL_CRITERIA_REQUIRED")
    statuses = {"passed": True, "failed": False, "not_observed": None}
    observations = []
    for criterion, row in zip(data["acceptance_criteria"], rows):
        if row.get("status") not in statuses:
            raise ValueError("OBSERVATION_EXPLICIT_STATUS_REQUIRED")
        observations.append({"criterion_sha256": criterion["criterion_sha256"],
                             "status": row["status"], "notes": row.get("notes"),
                             "criterion_satisfied": statuses[row["status"]]})
    payload = {"schema_version": "gtfo_operator_completion_v1", "request_sha256": data["request_sha256"],
               "feature_id": request.feature_id, "status": "completed",
               "observed_by": response.get("observed_by"), "observations": observations}
    # Use the runtime owner's exact validator before publishing any response.
    _read_operator_completion(request=request, reader=lambda _: payload)
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError("OBSERVATION_RESPONSE_TOO_LARGE")
    confirmation = {"schema_version": "gtfo_operator_completion_confirmation_v1",
                    "request_sha256": data["request_sha256"],
                    "response_sha256": hashlib.sha256(raw).hexdigest(), "status": "confirmed"}
    # Exclusive creation retains an uncertain partial write for inspection; never retry it blindly.
    with response_path.open("xb") as handle:
        handle.write(raw)
    temporary = root / (request_id + ".confirmation.pending")
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(confirmation) + "\n")
    temporary.rename(confirmation_path)
    return {"entry": "dsh-observation", "status": "submitted", "request_id": request_id,
            "request_sha256": data["request_sha256"], "response_sha256": confirmation["response_sha256"],
            "read_only": False, "model_calls_performed": 0, "runtime_success_claimed": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--exchange-directory", required=True)
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.submit:
            raw = sys.stdin.buffer.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("OBSERVATION_RESPONSE_TOO_LARGE")
            result = submit_observations(args.exchange_directory, json.loads(raw))
        else:
            result = pending_observations(args.exchange_directory)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"entry": "dsh-observation", "status": "blocked", "reason": str(exc),
                          "model_calls_performed": 0, "runtime_success_claimed": False}))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
