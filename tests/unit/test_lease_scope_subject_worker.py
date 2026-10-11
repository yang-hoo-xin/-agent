"""Public synthetic contract test for the lease-scope subject worker."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.prepare_lease_scope_subject_worker import prepare

PUBLIC_SUBJECT = '''
using System;
using System.Collections.Generic;
public sealed class LeaseFault : Exception { public LeaseFault(string point) : base(point) {} }
public sealed class LeaseContext {
    public readonly List<string> Events = new List<string>();
    public readonly List<LeaseHandle> Handles = new List<LeaseHandle>();
    public string FailOpen; public int Active;
    public LeaseHandle Open(string name) { Events.Add("try:"+name); if(name==FailOpen) throw new LeaseFault(name);
        var item=new LeaseHandle(this,name); Handles.Add(item); Active++; Events.Add("open:"+name); return item; }
}
public sealed class LeaseHandle : IDisposable { private readonly LeaseContext owner; public readonly string Name;
    public int DisposeCount; public LeaseHandle(LeaseContext owner,string name){this.owner=owner;Name=name;}
    public void Dispose(){DisposeCount++;owner.Active--;owner.Events.Add("close:"+Name);} }
public sealed class ExportPipeline { public int Apply(LeaseContext context,string[] records,Action<string> emit) {
    var reader=context.Open("reader"); var writer=context.Open("writer"); var completed=0;
    try { foreach(var record in records){using(var frame=context.Open("frame:"+record)){emit(record);completed++;}}
        return completed; } finally { writer.Dispose(); reader.Dispose(); } } }
'''


def test_public_subject_worker_exposes_observations_without_expected_values(tmp_path):
    source = tmp_path / "Subject.cs"
    source.write_text(PUBLIC_SUBJECT)
    reference = prepare(source=source, output_root=tmp_path / "worker")
    summary = json.loads(Path(reference["path"]).read_text())
    schema = json.loads(Path(summary["operation_schema_ref"]["path"]).read_text())
    assert schema["contains_expected_values"] is False
    assert summary["eligibility"] == "development_only_not_held_out_after_adapter_design"
    assert summary["hidden_material_used"] is False and summary["model_calls"] == 0
    probes = {Path(ref["path"]).stem: json.loads(Path(ref["path"]).read_text())["response"]
              for ref in summary["probe_refs"]}
    assert probes["normal"]["completed"] == 2 and probes["normal"]["active"] == 0
    assert probes["partial-open-failure"]["exception_type"].endswith("LeaseFault")
    assert probes["callback-failure"]["callback_exception_identity_preserved"] is True
    assert probes["caller-owned"]["caller_owned_dispose_count"] == 0
    plan = json.loads(Path(summary["container_plan_ref"]["path"]).read_text())
    assert "sealed root" in plan["forbidden_mounts"] and plan["image"] is None
