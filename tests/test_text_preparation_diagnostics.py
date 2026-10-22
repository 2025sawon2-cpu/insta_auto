"""A text plan's diagnostic must use its persisted host owner selection."""
import copy
import hashlib
import json

import pytest

from test_preparation_query_diagnostics import captured
from test_source_visual_query_minima_v5 import WORDS, proposal, model, plan
from hotpost import source_visual_queries as visual
from hotpost.source_preparation import save_bundle
from hotpost.source_text_query_receipts import cached_text_receipt, apply_text_queries
from hotpost.source_coverage import search_scope_for_state
from hotpost.video_agent_context import preparation_query_diagnostics


def text_selected(tmp_path):
    studio,state,bundle,reference,frames,register=captured(tmp_path)
    caption='재킷 세워진 칼라 가로 퀼팅 앞 지퍼 지퍼 주머니 짧은 밑단'
    state=studio.store.change(state['id'],lambda s,db:s.update(original_text=caption))
    policy=json.loads(bundle.read_text('utf8'))['query_plan']['source_policy']
    parent=visual.cached_visual_queries(studio.settings,reference,frames,caption,{},
        model(proposal(),[]),search_minimums=policy['search_minimums'],subject_hint='재킷')
    with studio.store.transaction() as db:
        job=studio.store.enqueue(db,state['id'],'collect_sources',{'run_id':state['run_id']},'text-plan')
    owner={'task_id':state['id'],'job_id':job,'run_id':state['run_id']}
    def generate(settings,instruction,data,**kwargs):
        if 'proposal_sha256' not in data:
            return {'queries':[{'id':lang+str(i),'query':q,'language':lang,
                'text_quotes':[{'source':'caption','quote':caption}]} for lang,words in WORDS.items() for i,q in enumerate(words)]}
        flags=dict(supported=True,central_product=True,short_noun_phrase=True,
            no_unobserved_claims=True,core_identity_preserved=True,quoted_modifiers_supported=True)
        return {'input_sha256':data['input_sha256'],'proposal_sha256':data['proposal_sha256'],
            'text_search_only':True,'core_identity_complete':True,
            'checks':[dict(query_id=q['id'],**flags) for q in data['proposal']['queries']]}
    receipt=cached_text_receipt(studio.settings,parent,owner,generate)
    document=plan(parent);document.update(source_policy=policy,run_id=state['run_id'],search_context=search_scope_for_state(state))
    document=apply_text_queries(document,receipt,owner=owner)
    assert document['minimum_query_plan_ready']
    save_bundle(bundle,caption,{},reference,frames,frames[0],query_plan=document);register()
    selected={**owner,'source_policy':policy,'search_context':search_scope_for_state(state),
        'path':str(bundle.resolve()),'sha256':hashlib.sha256(bundle.read_bytes()).hexdigest()}
    with studio.store.transaction() as db:
        db.execute('update jobs set checkpoint=? where id=?',(json.dumps({'planning_preparation':selected}),job))
    return studio,state,bundle,selected


@pytest.mark.parametrize('damage',[None,'missing_selection','task','job','run','scope','policy','path','sha','payload_run','duplicate_owner'])
def test_actual_text_receipt_diagnostic_uses_real_owned_selection_and_validators(tmp_path,damage):
    studio,state,bundle,selected=text_selected(tmp_path)
    with studio.store.transaction() as db:
        if damage=='duplicate_owner':
            other=studio.store.enqueue(db,state['id'],'collect_sources',{'run_id':state['run_id']},'other')
            duplicate={**selected,'job_id':other}
            db.execute('update jobs set checkpoint=? where id=?',(json.dumps({'planning_preparation':duplicate}),other))
        elif damage=='payload_run':db.execute('update jobs set payload=? where id=?',(json.dumps({'run_id':'foreign'}),selected['job_id']))
        else:
            bad=copy.deepcopy(selected)
            field={'task':'task_id','job':'job_id','run':'run_id','scope':'search_context',
                'policy':'source_policy','sha':'sha256','path':'path'}.get(damage)
            if field:bad[field]='foreign'
            cp={} if damage=='missing_selection' else {'planning_preparation':bad}
            db.execute('update jobs set checkpoint=? where id=?',(json.dumps(cp),selected['job_id']))
    before_state=copy.deepcopy(studio.store.get(state['id']))
    before={p:p.read_bytes() for p in tmp_path.rglob('*.json')}
    result=preparation_query_diagnostics(studio,state)
    assert len(result)==1
    row=result[0]
    if damage is None:
        assert row['status']=='reusable' and row['current_query_contract'],row
        assert row['contract_kind']=='text' and row['contract_job_id']==selected['job_id']
    else:
        assert row['status']=='unverified' and 'owned preparation selection' in row['reason']
        assert not row.get('current_query_contract')
    assert studio.store.get(state['id'])==before_state
    assert {p:p.read_bytes() for p in before}==before
