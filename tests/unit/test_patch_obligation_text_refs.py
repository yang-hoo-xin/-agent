"""Input-only same-message references preserve every original obligation."""
from copy import deepcopy
import json

import pytest

from src.libs.llm import Message
from src.mod_agent import local_entry as owner
from tests.unit.test_local_entry import _patch_agent_context_fixture


def wire_size(value):
    return len(owner._patch_agent_context_json(owner._patch_agent_context_json(value)).encode('utf-8'))


@pytest.mark.parametrize('text', ['A complete obligation; preserve every value. ' * 30, '保持默认值，重复动作不得再次修改。' * 60, 'quoted \"value\" with \n and \t' * 40])
def test_same_text_roundtrips_each_field_and_saves_wire(text):
    original = _patch_agent_context_fixture()
    original.update(request=text, target_behavior=text, constraints=['unique requirement', text, text + ' distinct'])
    before = deepcopy(original)
    encoded = owner._compact_patch_agent_context(original)
    assert encoded['patch_agent_context_encoding']['version'] == 'patch_agent_context_tables_v2'
    assert encoded['request'] == text
    assert encoded['target_behavior'] == encoded['constraints'][1] == {'text_ref': '/request'}
    assert encoded['constraints'][2] == text + ' distinct'
    assert owner._restore_patch_agent_context(encoded) == before == original
    assert wire_size(encoded) < wire_size(original)


def test_same_constraints_can_use_literal_anchor_without_request_alias():
    original = _patch_agent_context_fixture()
    text = 'An exact separate condition. ' * 50
    original['constraints'] = [text, text]
    encoded = owner._compact_patch_agent_context(original)
    assert encoded['constraints'][1] == {'text_ref': '/constraints/0'}
    assert owner._restore_patch_agent_context(encoded) == original


@pytest.mark.parametrize('ref', ['/missing', '/constraints/01', '/target_behavior', '../other', 1])
def test_unknown_or_cyclic_text_ref_is_rejected(ref):
    original = _patch_agent_context_fixture()
    original['target_behavior'] = original['request'] = 'same long obligation ' * 50
    encoded = owner._compact_patch_agent_context(original)
    encoded['target_behavior']['text_ref'] = ref
    with pytest.raises(owner.LocalEntryError, match='PROJECTION_INVALID'):
        owner._restore_patch_agent_context(encoded)


def test_short_repetition_does_not_pay_for_larger_reference_guide():
    original = _patch_agent_context_fixture()
    original.update(request='x', target_behavior='x')
    encoded = owner._compact_patch_agent_context(original)
    assert encoded['patch_agent_context_encoding']['version'] == 'patch_agent_context_tables_v1'
    assert encoded['target_behavior'] == 'x'
    assert owner._restore_patch_agent_context(encoded) == original


def test_old_encoding_and_literal_ref_like_data_remain_literal():
    original = _patch_agent_context_fixture()
    original['constraints'].append({'text_ref': '/request'})
    encoded = owner._compact_patch_agent_context(original)
    assert encoded['patch_agent_context_encoding']['version'] == 'patch_agent_context_tables_v1'
    assert owner._restore_patch_agent_context(encoded) == original


def test_normal_initial_message_owner_uses_references_without_changing_source_input():
    original = _patch_agent_context_fixture()
    original['target_behavior'] = original['request'] = 'Preserve state and exact acceptance. ' * 50
    messages = (Message(role='system', content='Exact output schema unchanged'), Message(role='user', content=json.dumps(original)))
    encoded = json.loads(owner._patch_agent_initial_messages(messages)[1].content)
    restored = owner._restore_patch_agent_context(encoded)
    assert encoded['target_behavior'] == {'text_ref': '/request'}
    for key in ('request', 'target_behavior', 'constraints', 'acceptance_criteria', 'required_output_schema'):
        assert restored[key] == original[key]
    assert json.loads(messages[1].content) == original
