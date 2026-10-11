"""Native v3 compact anchors preserve the original Plan, raw output and exact Apply boundaries."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest
from src.libs.llm import ChatResponse
from src.mod_agent.proposal import code_generator as owner
from src.mod_agent.execution.patch_apply import materialize_exact_text_patch, PatchApplyError
from tests.unit.test_patch_code_generator import _FakeLLM


def fixture(text, count=1, span=None):
    span=span or {'start_line':1,'end_line':len(text.splitlines())}
    bindings=[];items=[];units=[]
    for i in range(count):
        items.append({'evidence_id':f'e{i}','source_type':'target_source','source_path':'M/Code.cs','source_hash':hashlib.sha256(text.encode()).hexdigest(),'span':dict(span),'symbol':None,'excerpt':text})
        bindings.append({'binding_id':f'b{i}','evidence_id':f'e{i}','source_type':'target_source','canonical_target_path':'M/Code.cs','source_hash':items[-1]['source_hash'],'target_span':dict(span),'target_symbol':None})
        units.append({'change_id':f'c{i}','change_type':'modify_behavior','edit_binding_id':f'b{i}','supporting_binding_ids':[],'operation':'minimal_evidence_bound_change','rationale':'Bound change','expected_validation':['compile or static validation']})
    inputs={'user_request':'Make the bounded change and preserve all other behavior.','evidence_items':items,'binding_registry':{'edit_bindings':bindings,'supporting_bindings':[]},'required_change_units':units,'constraints':['Preserve other bytes.']}
    generator=owner.LLMExactPatchGenerator(_FakeLLM('must not call provider'))
    return generator,generator.prepare_native_contract(**inputs),inputs


def response(before,after,binding='b0'):
    row={'edit_binding_id':binding,'after_text':after,'rationale':'Bound local edit','rollback_hint':'Restore exact original.'}
    if before is not None:row['before_text']=before
    return row


def materialize(generator,prepared,rows):
    raw=json.dumps({'changes':rows},ensure_ascii=False)
    patch=generator.materialize_prepared_native(prepared,ChatResponse(content=raw,model='offline-fixture'))
    assert patch.raw_text==raw
    for canonical,row in zip(patch.changes,rows):assert canonical['patch']['after_text']==row['after_text']
    return patch


def test_compact_crlf_multibyte_preserves_raw_and_all_unrelated_bytes(tmp_path):
    text='\ufeffusing System;\r\nclass C {\r\n    string Note = "旧";\r\n    int Keep = 9;\r\n}\r\n'
    gen,prepared,inputs=fixture(text);assert prepared.contract_version=='3'
    patch=materialize(gen,prepared,[response('string Note = "旧";','string Note = "新";')])
    target=tmp_path/'M/Code.cs';target.parent.mkdir();target.write_bytes(text.encode())
    result=materialize_exact_text_patch(workspace_root=tmp_path,diff_intent=patch.changes,implementation_plan={'binding_registry':inputs['binding_registry']})
    assert result.files['M/Code.cs']==text.replace('"旧"','"新"').encode()
    assert target.read_bytes()==text.encode()
    assert patch.changes[0]['patch']['before_text']=='string Note = "旧";'


@pytest.mark.parametrize('before,after', [('Absent','x'),('1','2'),('', 'x'),('aaa','x'),('Value = 1;','Value = 1;')])
def test_missing_ambiguous_empty_and_noop_are_rejected(before,after):
    gen,prepared,_=fixture('class C { int Value = 1; int Other = 1; string X = "aaaa"; }\n')
    with pytest.raises(owner.PatchGenerationError):materialize(gen,prepared,[response(before,after)])


def test_overlapping_substring_occurrences_are_ambiguous():
    gen,prepared,_=fixture('class C { string X = "aaa"; }\n')
    with pytest.raises(owner.PatchGenerationError,match='exactly one'):materialize(gen,prepared,[response('aa','ab')])


def test_overlap_across_bindings_is_rejected_before_apply():
    gen,prepared,_=fixture('class C { int Value = 1; }\n',count=2)
    with pytest.raises(owner.PatchGenerationError,match='overlap'):
        materialize(gen,prepared,[response('Value = 1;','Value = 2;'),response('1','3','b1')])


def test_local_anchor_outside_declared_span_is_rejected():
    gen,prepared,_=fixture('class C {\n int Value = 1;\n}\n',span={'start_line':1,'end_line':1})
    with pytest.raises(owner.PatchGenerationError,match='span'):
        materialize(gen,prepared,[response('Value = 1;','Value = 2;')])


def test_explicit_local_bom_is_never_silently_rewritten():
    gen,prepared,_=fixture('\ufeffusing System;\nclass C {}\n')
    with pytest.raises(owner.PatchGenerationError,match='BOM'):
        materialize(gen,prepared,[response('\ufeffusing System;','using System.Text;')])


def test_crlf_anchor_cannot_match_lf_normalized_text():
    gen,prepared,_=fixture('class C {\r\n int Value = 1;\r\n}\r\n')
    with pytest.raises(owner.PatchGenerationError,match='exactly one'):
        materialize(gen,prepared,[response('int Value = 1;\n','int Value = 2;\n')])


def test_local_code_still_binds_original_source_hash(tmp_path):
    text='class C { int Value = 1; }\n';gen,prepared,inputs=fixture(text)
    patch=materialize(gen,prepared,[response('Value = 1;','Value = 2;')]);target=tmp_path/'M/Code.cs';target.parent.mkdir();target.write_text(text+'// drift\n')
    with pytest.raises(PatchApplyError,match='source_hash'):
        materialize_exact_text_patch(workspace_root=tmp_path,diff_intent=patch.changes,implementation_plan={'binding_registry':inputs['binding_registry']})


def test_old_v2_prepared_schema_retains_full_replacement_and_rejects_anchor():
    text='class C { int Value = 1; }\n';gen,new,_=fixture(text)
    schema=deepcopy(new.response_schema);schema['properties']['changes']['items']['properties'].pop('before_text')
    messages=list(new.messages);payload=json.loads(messages[1].content);payload['required_output_schema']=schema
    messages[1]=replace(messages[1],content=json.dumps(payload,ensure_ascii=False,sort_keys=True))
    old=replace(new,contract_version='2',messages=tuple(messages),response_schema=schema,schema_sha256=owner._canonical_json_sha256(schema))
    patch=materialize(gen,old,[response(None,text.replace('1','2'))]);assert patch.changes[0]['patch']['before_text']==text
    with pytest.raises(owner.PatchGenerationError):materialize(gen,old,[response('Value = 1;','Value = 2;')])


def test_full_context_header_is_checked_after_local_edit():
    gen,prepared,_=fixture('using System;\nclass C { int Value = 1; }\n')
    with pytest.raises(owner.PatchSubmissionValidationError,match='using'):
        materialize(gen,prepared,[response('using System;\n','// removed\n')])


def test_v3_version_cannot_be_relabelled_as_v2():
    gen,prepared,_=fixture('class C { int Value = 1; }\n')
    with pytest.raises(owner.PatchGenerationError,match='version and schema'):
        materialize(gen,replace(prepared,contract_version='2'),[response(None,'class C { int Value = 2; }\n')])


def test_direct_generate_uses_full_context_for_local_header_check():
    text='using System;\nusing System.Text;\nclass C { int Value = 1; }\n'
    _,_,inputs=fixture(text)
    raw=json.dumps({'changes':[response('using System;\n','// one unused using removed\n')]})
    generated=owner.LLMExactPatchGenerator(_FakeLLM(raw)).generate(**inputs,require_native_schema=True,provider_request_recorder=lambda _:None)
    assert generated.changes[0]['patch']['after_text']=='// one unused using removed\n'
    assert generated.raw_text==raw

def test_compiler_rejects_raw_anchor_mismatch_before_candidate_build(tmp_path,monkeypatch):
    from tests.unit.test_full_project_compilation import _checker
    _,context,checker,calls,_=_checker(tmp_path,monkeypatch)
    checker.verify_baseline()
    raw=json.loads(Path(context['model_response']['path']).read_bytes())
    raw['changes'][0]['before_text']='same after_text aimed at a different original anchor'
    target=tmp_path/'changed-raw.json';target.write_text(json.dumps(raw),encoding='utf-8');data=target.read_bytes()
    context['model_response']={'path':str(target),'output_sha256':hashlib.sha256(data).hexdigest(),'output_utf8_bytes':len(data)}
    with pytest.raises(ValueError,match='FULL_COMPILE_MODEL_SELECTION_CHANGED'):checker(context)
    assert len(calls)==1

def test_compiler_accepts_exact_raw_explicit_anchor(tmp_path,monkeypatch):
    from tests.unit.test_full_project_compilation import _checker
    _,context,checker,calls,_=_checker(tmp_path,monkeypatch)
    raw=json.loads(Path(context['model_response']['path']).read_bytes())
    raw['changes'][0]['before_text']=context['generated_changes'][0]['patch']['before_text']
    target=tmp_path/'explicit-raw.json';target.write_text(json.dumps(raw),encoding='utf-8');data=target.read_bytes()
    context['model_response']={'path':str(target),'output_sha256':hashlib.sha256(data).hexdigest(),'output_utf8_bytes':len(data)}
    assert checker(context)['status']=='passed' and len(calls)==2

def test_local_v3_submission_through_actual_source_read_loop(tmp_path):
    from src.libs.llm.agent_turn import AgentMessage,AgentResponseFormat
    from src.mod_agent.proposal.patch_agent_loop import PlanBoundSourceInspector,PatchAgentLoopPolicy,run_patch_agent_loop
    from tests.unit.test_patch_agent_loop import _ScriptedClient,_response,_tool_call
    text='class C { int Value = 1; int Preserve = 9; }\n'
    gen,prepared,inputs=fixture(text);target=tmp_path/'M/Code.cs';target.parent.mkdir();target.write_bytes(text.encode())
    plan={'binding_registry':inputs['binding_registry'],'proposed_changes':inputs['required_change_units']}
    inspector=PlanBoundSourceInspector(workspace_root=tmp_path,implementation_plan=plan,policy=PatchAgentLoopPolicy())
    raw=json.dumps({'changes':[response('Value = 1;','Value = 2;')]});validated=[]
    def validate(turn):validated.append(gen.materialize_prepared_native(prepared,ChatResponse(content=turn.content,model='offline-fixture')))
    client=_ScriptedClient([_response(turn=1,tool_calls=(_tool_call('b0',turn=1),)),_response(turn=2,content=raw)])
    result=run_patch_agent_loop(client=client,initial_messages=tuple(AgentMessage(role=m.role,content=m.content) for m in prepared.messages),final_response_format=AgentResponseFormat(name='patch_response',description='Native v3',schema=prepared.response_schema),source_inspector=inspector,submission_validator=validate)
    assert result.completed and len(client.requests)==2 and len(validated)==1
    assert validated[0].raw_text==raw and target.read_bytes()==text.encode()


def test_v3_fragment_without_anchor_explains_whole_binding_semantics_and_keeps_raw():
    text='using System;\nclass C { int Value = 1; }\n'
    gen,prepared,_=fixture(text)
    raw=json.dumps({'changes':[response(None,'int Value = 2;')]})
    with pytest.raises(owner.PatchSubmissionValidationError) as captured:
        gen.materialize_prepared_native(prepared,ChatResponse(content=raw,model='offline-fixture'))
    error=captured.value
    assert error.diagnostic_content==raw
    assert error.diagnostics['failure_classification']=='csharp_file_header_usings_removed'
    hint=error.diagnostics['native_v3_correction']
    assert 'omitted before_text' in hint and 'entire bound source_excerpt' in hint
    assert 'verbatim' in hint and 'unique fragment' in hint and 'complete replacement' in hint
    assert 'Value = 1' not in hint  # No inferred anchor or reference solution.


@pytest.mark.parametrize('kind',['explicit_anchor','frozen_v2'])
def test_anchor_hint_does_not_change_explicit_anchor_or_frozen_v2_errors(kind):
    text='using System;\nclass C { int Value = 1; }\n'
    gen,prepared,_=fixture(text)
    row=response('using System;\n','// removed\n')
    if kind=='frozen_v2':
        schema=deepcopy(prepared.response_schema);schema['properties']['changes']['items']['properties'].pop('before_text')
        messages=list(prepared.messages);payload=json.loads(messages[1].content);payload['required_output_schema']=schema
        messages[1]=replace(messages[1],content=json.dumps(payload,ensure_ascii=False,sort_keys=True))
        prepared=replace(prepared,contract_version='2',messages=tuple(messages),response_schema=schema,schema_sha256=owner._canonical_json_sha256(schema))
        row=response(None,'int Value = 2;')
    with pytest.raises(owner.PatchSubmissionValidationError) as captured:
        materialize(gen,prepared,[row])
    assert captured.value.diagnostics['failure_classification']=='csharp_file_header_usings_removed'
    assert 'native_v3_correction' not in captured.value.diagnostics


def test_v3_omitted_anchor_hint_reaches_next_loop_request_without_changing_source(tmp_path):
    from src.libs.llm.agent_turn import AgentMessage,AgentResponseFormat
    from src.mod_agent.proposal.patch_agent_loop import PlanBoundSourceInspector,PatchAgentLoopPolicy,run_patch_agent_loop
    from tests.unit.test_patch_agent_loop import _ScriptedClient,_response,_tool_call
    text='using System;\nclass C { int Value = 1; int Preserve = 9; }\n'
    gen,prepared,inputs=fixture(text);target=tmp_path/'M/Code.cs';target.parent.mkdir();target.write_bytes(text.encode())
    plan={'binding_registry':inputs['binding_registry'],'proposed_changes':inputs['required_change_units']}
    inspector=PlanBoundSourceInspector(workspace_root=tmp_path,implementation_plan=plan,policy=PatchAgentLoopPolicy())
    bad=json.dumps({'changes':[response(None,'int Value = 2;')]})
    corrected=json.dumps({'changes':[response('Value = 1;','Value = 2;')]})
    def validate(turn):
        gen.materialize_prepared_native(prepared,ChatResponse(content=turn.content,model='offline-fixture'))
    client=_ScriptedClient([_response(turn=1,tool_calls=(_tool_call('b0',turn=1),)),_response(turn=2,content=bad),_response(turn=3,content=corrected)])
    result=run_patch_agent_loop(client=client,initial_messages=tuple(AgentMessage(role=m.role,content=m.content) for m in prepared.messages),
        final_response_format=AgentResponseFormat(name='patch_response',description='Native v3',schema=prepared.response_schema),
        source_inspector=inspector,submission_validator=validate)
    assert result.completed and len(client.requests)==3
    feedback=[m.content for m in client.requests[-1].messages if isinstance(m.content,dict) and m.content.get('message_type')=='patch_submission_feedback']
    assert len(feedback)==1 and 'native_v3_correction' in feedback[0]['diagnostics']
    assert target.read_bytes()==text.encode()
