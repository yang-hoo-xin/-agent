"""Append-only pytest facts for the selected module evaluation.

为什么要有它：collection, setup, call and teardown are distinct evidence; a missing
test or failed fixture must never be reported as a successful product case.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _emit(kind, **values):
    path = os.environ.get("MODULE_EVALUATION_EVENTS")
    if path:
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"kind": kind, "utc": datetime.now(timezone.utc).isoformat(),
                                     **values}, ensure_ascii=False) + "\n")


def pytest_collection_finish(session):
    _emit("collected", nodeids=[item.nodeid for item in session.items])


def pytest_collectreport(report):
    if report.failed:
        _emit("collection_error", nodeid=report.nodeid, detail=str(report.longrepr))


def pytest_runtest_logstart(nodeid, location):
    _emit("started", nodeid=nodeid)


def pytest_runtest_logreport(report):
    _emit("phase", nodeid=report.nodeid, phase=report.when, outcome=report.outcome,
          duration_seconds=report.duration, wasxfail=getattr(report, "wasxfail", None),
          detail=str(report.longrepr) if report.failed or report.skipped else None)


def pytest_sessionfinish(session, exitstatus):
    _emit("finished", exit_code=int(exitstatus))
