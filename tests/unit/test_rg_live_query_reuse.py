"""Same-batch source query reuse preserves obligations and rejects stale observations."""
from pathlib import Path
import pytest
from src.mod_agent.evidence import rg_live
from src.mod_agent.evidence.rg_live import RgLiveEvidenceProvider


def queries(*texts):
    return tuple({'query_id':f'q{i}','query':text,'requirement_id':f'r{i}'} for i,text in enumerate(texts))


def fixture(tmp_path):
    root=tmp_path/'subject';root.mkdir();(root/'Plugin.cs').write_text('public class Plugin { bool Configuration = true; }\n',encoding='utf-8')
    return RgLiveEvidenceProvider(tmp_path,small_file_max_bytes=8192),root


def count_dispatch(monkeypatch):
    actual=rg_live.subprocess.run;calls=[]
    def run(*args,**kwargs):calls.append(args[0]);return actual(*args,**kwargs)
    monkeypatch.setattr(rg_live.subprocess,'run',run);return calls


def test_identical_queries_share_execution_but_keep_every_obligation(tmp_path,monkeypatch):
    provider,root=fixture(tmp_path);calls=count_dispatch(monkeypatch)
    q=queries('Configuration','Configuration','MissingNeedle','MissingNeedle')
    pack=provider.collect_query_set(queries=q,search_root=root,max_items=4)
    assert len(calls)==2
    rows=pack.budget_summary['per_query_execution']
    assert [(r['query_id'],r['requirement_id']) for r in rows]==[(r['query_id'],r['requirement_id']) for r in q]
    assert [r['observation_reused'] for r in rows]==[False,True,False,True]
    assert rows[1]['evidence_ids']==rows[0]['evidence_ids'] and rows[3]['evidence_ids']==[]
    assert rows[1]['reused_from_lane']=='q0' and rows[3]['reused_from_lane']=='q2'
    assert pack.budget_summary['all_queries_executed'] and not pack.can_generate_patch
    assert pack.budget_summary['query_observation_reuse']['reused_lanes']==2


def test_identifier_and_projected_lane_reuse_same_observation(tmp_path,monkeypatch):
    provider,root=fixture(tmp_path);calls=count_dispatch(monkeypatch)
    pack=provider.collect_query_set(queries=queries('Plugin.cs'),search_root=root,max_items=1,source_identity_query='Plugin.cs')
    assert len(calls)==1
    lane=pack.budget_summary['per_query_execution'][0]
    assert lane['observation_reused'] and lane['reused_from_lane']=='request_identifier:0'
    assert lane['evidence_ids']==pack.budget_summary['request_identifier_queries'][0]['evidence_ids']


def test_new_batch_reads_new_bytes_and_different_path(tmp_path,monkeypatch):
    provider,root=fixture(tmp_path);calls=count_dispatch(monkeypatch);q=queries('Configuration','Configuration')
    first=provider.collect_query_set(queries=q,search_root=root,max_items=2)
    (root/'Plugin.cs').write_text('public class Plugin { bool Configuration = false; }\n',encoding='utf-8')
    second=provider.collect_query_set(queries=q,search_root=root,max_items=2)
    other=tmp_path/'other';other.mkdir();(other/'Plugin.cs').write_text('public class Plugin { int Configuration = 42; }\n',encoding='utf-8')
    third=provider.collect_query_set(queries=q,search_root=other,max_items=2)
    assert len(calls)==3
    assert len({p.items[0].source_hash for p in (first,second,third)})==3
    assert 'false' in second.items[0].excerpt and '42' in third.items[0].excerpt


def test_source_mutation_during_query_fails_closed(tmp_path,monkeypatch):
    provider,root=fixture(tmp_path);actual=provider.collect
    def collect(**kwargs):
        result=actual(**kwargs);(root/'Plugin.cs').write_text('public class Replaced {}\n');return result
    monkeypatch.setattr(provider,'collect',collect)
    with pytest.raises(ValueError,match='RG_LIVE_QUERY_SET_SOURCE_CHANGED'):
        provider.collect_query_set(queries=queries('Configuration','Configuration'),search_root=root,max_items=2)


def test_strategy_change_prevents_reusing_old_result(tmp_path,monkeypatch):
    provider,root=fixture(tmp_path);actual=provider.collect;calls=[]
    def collect(**kwargs):
        calls.append(kwargs);result=actual(**kwargs)
        if len(calls)==1:provider.small_file_max_bytes=0
        return result
    monkeypatch.setattr(provider,'collect',collect)
    pack=provider.collect_query_set(queries=queries('Absent','Absent','Absent'),search_root=root,max_items=3)
    assert len(calls)==2
    assert [r['observation_reused'] for r in pack.budget_summary['per_query_execution']]==[False,False,True]


def test_tool_failure_never_becomes_cached_negative(tmp_path,monkeypatch):
    from subprocess import CompletedProcess
    provider,root=fixture(tmp_path);calls=[]
    def fail(command,**kwargs):calls.append(command);return CompletedProcess(command,2,'','controlled failure')
    monkeypatch.setattr(rg_live.subprocess,'run',fail)
    pack=provider.collect_query_set(queries=queries('Absent','Absent'),search_root=root,max_items=2)
    assert len(calls)==2 and pack.budget_summary['query_observation_reuse']['reused_lanes']==0
    assert not pack.budget_summary['all_queries_executed']


def test_external_search_configuration_keeps_live_fallback(tmp_path,monkeypatch):
    provider,root=fixture(tmp_path);config=tmp_path/'rg.conf';config.write_text('');monkeypatch.setenv('RIPGREP_CONFIG_PATH',str(config));calls=count_dispatch(monkeypatch)
    provider.collect_query_set(queries=queries('Configuration','Configuration'),search_root=root,max_items=2)
    assert len(calls)==2


def test_identifier_secondary_source_is_retained_in_existing_item_budget(tmp_path):
    provider,root=fixture(tmp_path)
    (root/'Plugin.cs').write_text('public class Plugin { bool ConfigEnabled = true; }\n')
    (root/'Consumer.cs').write_text('public class Consumer { bool ConfigEnabled = false; }\n')
    pack=provider.collect_query_set(queries=queries('UnmatchedNeedle'),search_root=root,max_items=2,source_identity_query='ConfigEnabled')
    assert len(pack.items)==2
    assert {Path(item.source_path).name for item in pack.items}=={'Plugin.cs','Consumer.cs'}
    assert len(pack.budget_summary['request_identifier_queries'][0]['evidence_ids'])==2
    assert pack.budget_summary['per_query_execution'][0]['evidence_ids']==[]
    assert not pack.can_generate_patch
