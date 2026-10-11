"""Reversible Findings text sharing keeps source facts, obligations and admission intact."""
from copy import deepcopy
import json
from pathlib import PurePosixPath, PureWindowsPath

import pytest

from src.mod_agent.evidence.model_view import deduplicate_findings_input_text, expand_findings_input_text
from src.mod_agent.requirement_coverage_model import requirement_coverage_messages, requirement_coverage_messages_match


def payload():
    text = "保留全部原始用户需求、异常语义和现有行为。" * 35
    obligations = [{"input_obligation_id": "a", "text": text, "mandatory": True,
        "origin": {"field": "user_request", "index": 0}},
        {"input_obligation_id": "b", "text": text, "mandatory": True,
        "origin": {"field": "target_behavior", "index": 0}}]
    return {"message_type": "product_requirement_findings", "semantic_feedback": {"observed_failure": []},
        "relations": [{"relation_index": 1, "parent_requirements": [
            {"role": "change", "text": text, "input_obligations": obligations}]},
            {"relation_index": 2, "parent_requirements": [
                {"role": "preservation", "text": "Keep API", "input_obligations": deepcopy(obligations)}]}],
        "source_observations": [{"evidence_id": "source", "excerpt": text, "source_path": "API.cs"}],
        "rules": ["Original authority constraint."]}


def test_exact_roundtrip_with_all_original_obligation_metadata_and_source_untouched():
    original = payload(); before = deepcopy(original)
    projected = deduplicate_findings_input_text(original)
    assert original == before and projected is not original
    assert expand_findings_input_text(projected) == original
    assert projected['source_observations'] == original['source_observations']
    assert projected['rules'] == original['rules'] and projected['semantic_feedback'] == original['semantic_feedback']
    for relation in projected['relations']:
        for obligation in relation['parent_requirements'][0]['input_obligations']:
            assert obligation['text_ref'] == '/relations/0/parent_requirements/0/text'
            assert obligation['mandatory'] and obligation['origin']
    assert deduplicate_findings_input_text(projected) == projected


@pytest.mark.parametrize('variant', ['short', 'different_text', 'existing_ref'])
def test_only_equal_repeated_text_with_net_savings_is_shared(variant):
    value = payload()
    if variant == 'existing_ref':
        value['relations'][0]['parent_requirements'][0]['text_ref'] = 'unknown'
    elif variant == 'short':
        for relation in value['relations']:
            for parent in relation['parent_requirements']:
                parent['text'] = 'x'
                for obligation in parent['input_obligations']:
                    obligation['text'] = 'x'
    else:
        for index, relation in enumerate(value['relations']):
            for oi, obligation in enumerate(relation['parent_requirements'][0]['input_obligations']):
                obligation['text'] += f' {index}/{oi}'
    assert deduplicate_findings_input_text(value) == value


@pytest.mark.parametrize('damage', ['external', 'chain', 'both', 'version', 'source_pointer'])
def test_malformed_reference_is_rejected(damage):
    value = deduplicate_findings_input_text(payload())
    row = value['relations'][0]['parent_requirements'][0]['input_obligations'][0]
    if damage == 'both':
        row['text'] = 'replacement'
    elif damage == 'version':
        value['findings_input_text_encoding']['version'] = 'unknown'
    else:
        row['text_ref'] = {'external': 'file:///secret', 'chain': '/relations/0/parent_requirements/0/input_obligations/1/text_ref',
            'source_pointer': '/source_observations/0/excerpt'}[damage]
    with pytest.raises(ValueError, match='FINDINGS_INPUT_TEXT'):
        expand_findings_input_text(value)


def messages(value):
    return [{'role': row.role, 'content': row.content} for row in requirement_coverage_messages(value)]


def test_historical_exact_serialization_and_new_encoding_match_but_modified_obligation_does_not():
    original = payload(); projected = deduplicate_findings_input_text(original)
    assert requirement_coverage_messages_match(projected, messages(original))
    assert requirement_coverage_messages_match(projected, messages(projected))
    for field, value in [('mandatory', False), ('text', 'different actual requirement')]:
        changed = deepcopy(original)
        changed['relations'][0]['parent_requirements'][0]['input_obligations'][0][field] = value
        assert not requirement_coverage_messages_match(projected, messages(changed))


def test_net_savings_uses_wire_escaped_message_size_at_boundary():
    value = {'semantic_feedback': {}, 'relations': [{'parent_requirements': [
        {'text': '汉' * 60, 'input_obligations': [{'text': '汉' * 60}, {'text': '汉' * 60}]}]}]}
    result = deduplicate_findings_input_text(value)
    assert result == value
    for length in (60, 80, 150):
        sample = deepcopy(value)
        parent = sample['relations'][0]['parent_requirements'][0]
        parent['text'] = '汉' * length
        for item in parent['input_obligations']:
            item['text'] = parent['text']
        candidate = deduplicate_findings_input_text(sample)
        encode = lambda obj: len(json.dumps(messages(obj), ensure_ascii=False).encode('utf-8'))
        assert encode(candidate) <= encode(sample)


def test_initial_findings_shares_text_without_dropping_any_obligation_or_origin():
    original = payload(); del original['semantic_feedback']
    encoded = deduplicate_findings_input_text(original)
    assert 'findings_input_text_encoding' in encoded
    assert expand_findings_input_text(encoded) == original
    assert len(encoded['relations']) == len(original['relations'])
    assert encoded['source_observations'] == original['source_observations']
    assert requirement_coverage_messages_match(encoded, messages(original))


@pytest.mark.parametrize("path_type", [PurePosixPath, PureWindowsPath])
def test_local_path_guard_checks_raw_and_encoded_meaning_without_changing_wire(monkeypatch, path_type):
    from src.mod_agent import local_entry

    monkeypatch.setattr(local_entry, "Path", path_type)
    raw = payload()
    encoded = deduplicate_findings_input_text(raw)
    before = deepcopy(encoded)
    local_entry._assert_no_absolute_local_paths(raw)
    local_entry._assert_no_absolute_local_paths(encoded)
    assert encoded == before
    assert expand_findings_input_text(encoded) == raw


@pytest.mark.parametrize("path_type", [PurePosixPath, PureWindowsPath])
def test_raw_and_encoded_absolute_text_are_both_rejected(monkeypatch, path_type):
    from src.mod_agent import local_entry

    monkeypatch.setattr(local_entry, "Path", path_type)
    encoded = deduplicate_findings_input_text(payload())
    encoded["relations"][0]["parent_requirements"][0]["text"] = (
        "/private/secret" if path_type is PurePosixPath else "C:/private/secret")
    raw = expand_findings_input_text(encoded)
    for value in (raw, encoded):
        with pytest.raises(local_entry.LocalEntryError, match="absolute local path"):
            local_entry._assert_no_absolute_local_paths(value)


@pytest.mark.parametrize("damage", ["missing_marker", "unknown_marker", "outside_pointer", "absolute_target", "unrelated_metadata"])
def test_encoded_text_does_not_bypass_posix_local_path_guard(monkeypatch, damage):
    from src.mod_agent import local_entry

    monkeypatch.setattr(local_entry, "Path", PurePosixPath)
    encoded = deduplicate_findings_input_text(payload())
    parent = encoded["relations"][0]["parent_requirements"][0]
    if damage == "missing_marker":
        del encoded["findings_input_text_encoding"]
    elif damage == "unknown_marker":
        encoded["findings_input_text_encoding"]["version"] = "unknown"
    elif damage == "outside_pointer":
        parent["input_obligations"][0]["text_ref"] = "/private/secret"
    elif damage == "absolute_target":
        parent["text"] = "/private/secret"
    else:
        encoded["metadata"] = {"text_ref": "/private/secret"}
    expected = (ValueError if damage in {"unknown_marker", "outside_pointer"} else local_entry.LocalEntryError)
    with pytest.raises(expected, match="FINDINGS_INPUT_TEXT|absolute local path"):
        local_entry._assert_no_absolute_local_paths(encoded)
