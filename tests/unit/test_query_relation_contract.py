"""Query references must agree before either evidence tool receives them."""
import json
from copy import deepcopy
from dataclasses import replace

import pytest

from src.mod_agent import local_entry as owner
from src.mod_agent.evidence.requirement_coverage_provider import (
    admit_requirement_projection_response,
)
from tests.unit.test_findings_reassessment_budget import _api, _budget, _factory
from tests.unit.test_requirement_coverage import _initial_findings_reassessment_case


def _contract(case, **kwargs):
    return owner._build_request_upstream_query_contract(
        feature=case.feature, projection=case.pack.requirement_coverage, old=case.pack,
        feedback={'initial_findings_reassessment': {}},
        upstream_search_root='generated_mods/SyntheticMod', **kwargs)


def _query(case):
    target = _contract(case)['payload']['gap_investigation_targets'][0]
    relation = next(row for row in case.materialized['relations']
                    if row['provenance']['relation_index'] == target['relation_index'])
    return {'query': 'ResolveCoverageGap',
            'requirement_id': relation['parent_requirement_ids'][0],
            'gap_ids': [target['gap_id']], 'current_fact_needed': 'Current source fact',
            'modification_impact': 'Plan needs this current fact',
            'authorized_source': 'target_source', 'metadata_queries': []}


@pytest.mark.parametrize('invalid', ['wrong_parent', 'unknown_gap', 'mixed_parents'])
def test_receiver_rejects_gap_mismatch_before_dispatch(tmp_path, monkeypatch, invalid):
    case = _initial_findings_reassessment_case(tmp_path)
    row = _query(case)
    if invalid == 'wrong_parent':
        row['requirement_id'] = next(r['requirement_id'] for r in case.materialized['requirements']
                                     if r['requirement_id'] != row['requirement_id'])
    elif invalid == 'unknown_gap':
        row['gap_ids'] = ['gap_unknown']
    else:
        row['gap_ids'].append(_contract(case)['payload']['gap_investigation_targets'][1]['gap_id'])
    factory = _factory(case, tmp_path, _budget(), [])
    # Serialize the wrong response before replay; neither tool may see it.
    # 为什么要有它：独立合法的 ID 也可能具有错误归属。
    response = json.dumps([row])
    factory.query_selector = lambda *_: json.loads(response)
    monkeypatch.setattr(case.source_provider, 'collect_query_set',
                        lambda **_: pytest.fail('wrong relation dispatched to source tool'))
    factory.source_augmentation_factory = lambda *_: pytest.fail('wrong relation dispatched to API tool')
    with pytest.raises(ValueError, match='PATCH_REASSESSMENT_QUERY_GAP_REQUIREMENT_MISMATCH'):
        factory.reassess_initial(case.state, case.feature)


def test_schema_and_receiver_admit_parent_and_preserve_history(tmp_path):
    case = _initial_findings_reassessment_case(tmp_path)
    old = deepcopy(case.pack.to_artifact_payload())
    row = _query(case)
    contract = _contract(case)
    admit_requirement_projection_response({'queries': [row]}, schema=contract['schema'])
    wrong = deepcopy(row)
    wrong['requirement_id'] = case.materialized['requirements'][1]['requirement_id']
    with pytest.raises(ValueError):
        admit_requirement_projection_response({'queries': [wrong]}, schema=contract['schema'])
    result = _factory(case, tmp_path, _budget(), []).reassess_initial(case.state, case.feature)
    assert result.can_generate_patch
    assert case.pack.to_artifact_payload() == old


def test_schema_allows_multiple_parents_and_no_gaps(tmp_path):
    case = _initial_findings_reassessment_case(tmp_path)
    coverage = deepcopy(case.pack.requirement_coverage)
    parents = [row['requirement_id'] for row in coverage['requirements'][:2]]
    coverage['relations'][0]['parent_requirement_ids'] = parents
    coverage['findings'][0]['parent_requirement_ids'] = parents
    case.pack = replace(case.pack, requirement_coverage=coverage)
    for parent in parents:
        row = _query(case)
        row['requirement_id'] = parent
        admit_requirement_projection_response({'queries': [row]}, schema=_contract(case)['schema'])
    for finding in coverage['findings']:
        finding['unresolved_gaps'] = []
    schema = _contract(case)['schema']
    assert '"enum": []' not in json.dumps(schema)
    admit_requirement_projection_response({'queries': []}, schema=schema)
    with pytest.raises(ValueError):
        admit_requirement_projection_response({'queries': [row]}, schema=schema)


def test_patch_queries_bind_requirements_without_manufacturing_formal_gaps(tmp_path):
    case = _initial_findings_reassessment_case(tmp_path)
    query = _query(case)
    query['gap_ids'] = []
    coverage = deepcopy(case.pack.requirement_coverage)
    for finding in coverage['findings']:
        finding['unresolved_gaps'] = []
    case.pack = replace(case.pack, requirement_coverage=coverage)
    before = deepcopy(case.pack.to_artifact_payload())
    contract = owner._build_request_upstream_query_contract(
        feature=case.feature, projection=coverage, old=case.pack,
        feedback={'recommendation': {'required_owner': 'evidence', 'reason': 'Inspect another current source fact.'}},
        upstream_search_root='generated_mods/SyntheticMod')
    assert contract['payload']['gap_investigation_targets'] == []
    assert contract['payload']['message_type'] == 'patch_upstream_evidence_queries'
    assert contract['schema']['properties']['queries']['maxItems'] == 3
    assert '"enum": []' not in json.dumps(contract['schema'])
    admit_requirement_projection_response({'queries': [query]}, schema=contract['schema'])
    for damaged in ({**query, 'requirement_id': 'unknown'}, {**query, 'gap_ids': ['invented_gap']}):
        with pytest.raises(ValueError):
            admit_requirement_projection_response({'queries': [damaged]}, schema=contract['schema'])
    with pytest.raises(ValueError):
        admit_requirement_projection_response({'queries': [query]}, schema=_contract(case)['schema'])
    assert case.pack.to_artifact_payload() == before


def test_initial_receiver_still_requires_a_real_gap_before_tool_dispatch(tmp_path, monkeypatch):
    case = _initial_findings_reassessment_case(tmp_path)
    query = _query(case)
    query['gap_ids'] = []
    factory = _factory(case, tmp_path, _budget(), [])
    factory.query_selector = lambda *_: [query]
    monkeypatch.setattr(case.source_provider, 'collect_query_set',
                        lambda **_: pytest.fail('Gapless initial query reached source dispatch'))
    with pytest.raises(ValueError, match='PATCH_REASSESSMENT_QUERY_INVALID'):
        factory.reassess_initial(case.state, case.feature)


@pytest.mark.parametrize('authorized', [True, False])
def test_query_tool_view_matches_bound_executor_and_does_not_grant_scope(tmp_path, authorized):
    case = _initial_findings_reassessment_case(tmp_path)
    augmentation = _api(tmp_path, authorized=authorized)
    calls = []
    _factory(case, tmp_path, _budget(), calls, augmentation=augmentation,
             require_api=True).reassess_initial(case.state, case.feature)
    payload = calls[0][1]
    assert payload['query_contract_version'] == 'requirement_queries_v3'
    view = payload['tool_capabilities']
    source, api = view['target_source'], view['dependency_api']
    assert source['tool'] == 'rg_live' and source['file_glob'] == '*.cs'
    assert source['search_root'] == 'generated_mods/SyntheticMod'
    assert 'OR' in source['matching']
    assert api['available'] is authorized
    assert api['source']['assembly_relative_paths'] == ['Reference.dll']
    assert api['source']['allowed_tools'] == (['search_dotnet_metadata', 'inspect_method_il'] if authorized else [])
    assert 'case-insensitive literal substring' in api['tools']['search_dotnet_metadata']['matching']
    assert api['tools']['inspect_method_il']['max_method_inspections'] == 1
    assert not api['tools']['inspect_method_il']['target_code_execution_allowed']
    assert case.state['approvals'] == {}


def test_native_query_schema_preserves_full_constraints_without_transport(tmp_path, monkeypatch):
    import httpx

    from src.libs.llm.ollama_llm import OllamaLLM
    from src.mod_agent.requirement_coverage_model import requirement_coverage_messages
    from tests.unit.test_ollama_llm import MockSettings

    case = _initial_findings_reassessment_case(tmp_path)
    contract = _contract(case)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request',
                        lambda *_: pytest.fail('native preparation sent HTTP'))
    llm = OllamaLLM(MockSettings(), context_window=32768)
    captured = {}
    llm.prepare_structured_chat(requirement_coverage_messages(contract['payload']),
        response_format=contract['schema'], max_tokens=768, temperature=0.0,
        provider_request_recorder=captured.update)
    assert captured['context_admission']['admitted']
    for variant in contract['schema']['properties']['queries']['items']['oneOf']:
        assert variant['additionalProperties'] is False
        assert set(variant['required']) == set(_query(case))


@pytest.mark.parametrize('metadata', ['Info message', 'Type\tMember', 'Type\u2003Member', 'Type?', 'x' * 129])
def test_compact_metadata_domain_is_native_and_host_admitted_before_tools(tmp_path, metadata):
    case = _initial_findings_reassessment_case(tmp_path)
    row = _query(case)
    row.update(authorized_source='dependency_api', metadata_queries=['Load', metadata])
    from jsonschema import Draft7Validator
    from src.mod_agent.evidence.requirement_coverage_provider import RequirementProjectionAdmissionError
    schema = _contract(case)['schema']
    assert not Draft7Validator(schema).is_valid({'queries': [row]})
    with pytest.raises(RequirementProjectionAdmissionError) as caught:
        admit_requirement_projection_response({'queries': [row]}, schema=schema)
    assert caught.value.diagnostic['json_path'] == '$.queries[0].metadata_queries[1]'
    assert caught.value.diagnostic['failure_category'] in {'schema_string_pattern_mismatch', 'schema_string_too_long'}


@pytest.mark.parametrize('field', ['query', 'current_fact_needed', 'modification_impact'])
def test_native_query_text_limits_match_existing_tool_boundary(tmp_path, field):
    case = _initial_findings_reassessment_case(tmp_path)
    row = _query(case)
    row[field] = 'x' * 256
    schema = _contract(case)['schema']
    admit_requirement_projection_response({'queries': [row]}, schema=schema)
    row[field] += 'x'
    with pytest.raises(ValueError):
        admit_requirement_projection_response({'queries': [row]}, schema=schema)


@pytest.mark.parametrize('metadata', ['ConfigFile.Bind', 'ManualLogSource::LogInfo', 'Type`1', 'x' * 128])
def test_compact_metadata_identifiers_and_real_gap_parent_remain_valid(tmp_path, metadata):
    case = _initial_findings_reassessment_case(tmp_path)
    row = _query(case)
    row.update(authorized_source='dependency_api', metadata_queries=[metadata])
    admit_requirement_projection_response({'queries': [row]}, schema=_contract(case)['schema'])


@pytest.mark.parametrize('version', ['requirement_queries_v1', 'requirement_queries_v2'])
def test_explicit_historical_query_version_keeps_unconstrained_original_wire(tmp_path, version):
    case = _initial_findings_reassessment_case(tmp_path)
    schema = _contract(case, contract_version=version)['schema']
    properties = (schema['properties']['queries']['items']['oneOf'][0]['properties']
        if version.endswith('v2') else schema['properties']['queries']['items']['properties'])
    assert properties['metadata_queries']['items'] == {'type': 'string', 'minLength': 1}
    assert properties['query'] == {'type': 'string', 'minLength': 1}
    assert properties['current_fact_needed'] == {'type': 'string', 'minLength': 1}
    assert properties['modification_impact'] == {'type': 'string', 'minLength': 1}
    row = _query(case)
    row['metadata_queries'] = ['Info message']
    admit_requirement_projection_response({'queries': [row]}, schema=schema)
    # 为什么要有它：历史schema可重放不代表旧错误查询可执行，原工具前校验仍会拒绝。
    factory = _factory(case, tmp_path, _budget(), [])
    factory.query_selector = lambda *_: [row]
    with pytest.raises(ValueError, match='PATCH_REASSESSMENT_QUERY_INVALID'):
        factory.reassess_initial(case.state, case.feature)
