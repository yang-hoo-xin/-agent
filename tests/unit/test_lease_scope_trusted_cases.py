"""The trusted case driver never sends assertions to the subject worker."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.prepare_patch_sft_data import ref, save
from scripts.run_lease_scope_trusted_cases import run


def test_trusted_driver_sends_only_operation_and_keeps_expected_local(tmp_path):
    worker = tmp_path / "worker.py"
    worker.write_text("""import json,sys
value=json.load(sys.stdin)
print(json.dumps({'received_keys':sorted(value),'result':value.get('value',0)*2}))
""")
    command = save(tmp_path / "command.json", {"executable_ref": ref(Path(sys.executable)),
        "argv": [str(worker)], "cwd": str(tmp_path), "timeout_seconds": 10,
        "isolation": "none_development_probe_only"})
    cases = save(tmp_path / "cases.json", {"schema_version": "lease_scope_trusted_cases_v1",
        "task_id": "public-development", "eligibility": "development_only",
        "cases": [{"case_id": "double", "operation": {"value": 3}, "assertions": [
            {"path": ["result"], "equals": 6}, {"path": ["received_keys"], "equals": ["value"]}]}]})
    result_ref = run(command_ref=command, cases_ref=cases, output_root=tmp_path / "result")
    result = json.loads(Path(result_ref["path"]).read_text())
    assert result["passed"] == 1 and result["behavior_failed"] == 0
    assert result["worker_received_assertions_or_expected"] is False
