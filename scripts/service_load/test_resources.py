"""Docker stats accounting tests; never starts Docker or samples a real container."""
import importlib.util
import json
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location("service_load_resources",Path(__file__).parent/"resources.py")
r=importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def raw(name,cpu,memory):
    return {"Name":name,"Container":name,"ID":"123","CPUPerc":cpu,"MemUsage":memory,"PIDs":"4"}


def test_si_and_binary_units_and_multicore_cpu():
    value=r.parse_row(raw("x","225.50%","1.5MiB / 2GB"))
    assert value["cpu_percent"]==225.5
    assert value["memory_bytes"]==1.5*1024**2 and value["memory_limit_bytes"]==2*1000**3
    assert value["raw"]["MemUsage"]=="1.5MiB / 2GB"
    assert r.parse_row(raw("x","0%","38.21 MiB"))["memory_limit_bytes"] is None


def test_invalid_units_and_na_are_not_zero():
    value=r.parse_row(raw("x","N/A","-- / --"))
    assert value["cpu_percent"] is None and value["memory_bytes"] is None
    assert len(value["parse_errors"])==2


def test_targets_cannot_scan_all_or_other_project():
    for values in [[],["worker=another-worker-1"],["worker=--all"],["unknown=project-unknown-1"]]:
        with pytest.raises(ValueError):r.targets(values,"project")
    assert r.targets(["api=project-api-1","worker=project-worker-2"],"project")=={"project-api-1":"api","project-worker-2":"worker"}


def test_missing_or_unexpected_containers_invalidate_complete_group():
    names={"project-api-1":"api","project-worker-1":"worker"}
    value=r.decode_sample(json.dumps(raw("project-api-1","0%","0B / 1GiB")),names)
    assert value["missing_containers"]==["project-worker-1"] and not value["complete"]
    value=r.decode_sample(json.dumps(raw("other-api-1","10%","1MiB / 1GiB")),names)
    assert value["containers"]=={} and value["output_errors"]


def test_totals_are_same_sample_not_sum_of_individual_peaks():
    selected={"project-api-1":"api","project-worker-1":"worker"}
    rows=[{"event":"resource_start","targets":selected,"run_id":"r1"}]
    for index,(a,b) in enumerate([(200,1),(1,150)]):
        stdout="\n".join([json.dumps(raw(name,str(value)+"%",str(value)+"MiB / 1GiB")) for name,value in zip(selected,(a,b))])
        rows.append({"event":"resource_sample","run_id":"r1","sample_index":index,"started_at":index*2,"finished_at":index*2+1,
            "exit_code":0,**r.decode_sample(stdout,selected)})
    result=r.resource_summary(rows)
    assert result["same_sample_totals"]["cpu_percent"]["peak"]==201
    assert result["same_sample_totals"]["cpu_percent"]["mean"]==176
    assert result["same_sample_totals"]["memory_bytes"]["peak"]==201*1024**2
    assert result["containers"]["project-worker-1"]["cpu_percent"]["peak"]==150
    assert r.resource_summary(rows,window_start=1,window_end=4)["samples_selected"]==1


def test_partial_or_failed_samples_never_become_zero_total():
    selected={"project-api-1":"api","project-worker-1":"worker"}
    rows=[{"event":"resource_start","targets":selected,"run_id":"r1"},
        {"event":"resource_sample","run_id":"r1","sample_index":0,"started_at":0,"finished_at":1,"exit_code":0,
         **r.decode_sample(json.dumps(raw("project-api-1","99%","20MiB / 1GiB")),selected)}]
    result=r.resource_summary(rows)
    assert result["same_sample_totals"]["cpu_percent"]["peak"] is None
    assert result["containers"]["project-worker-1"]["cpu_percent"]["samples"]==0
    assert result["incomplete_group_samples"]==1
