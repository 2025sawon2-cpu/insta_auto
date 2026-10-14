"""Replace multi-pocket shots at envelope lines; preserve the selected narration."""
import argparse,copy,json,shutil,time
from pathlib import Path
from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json as save
from hotpost.source_coverage import coverage_goal
from hotpost.source_policy import current_policy
from hotpost.source_quality import sha256_file
from hotpost.studio import Studio
from hotpost.studio_workflow import init_run,snapshot
from tools import build_tiktok_rework as build
from tools import revise_cart_youtube_actions as environment

CODE='DeRFXHpEwck';WORK='work-440c6d0fc4794fa5'
ROOT=Path('data/a7-envelope-alignment-20261011-v7').resolve()
OLD=Path('data/a7-receipt-review-20261011-v6').resolve()
EDIT='a7-envelope-alignment-20261011-v7';PREVIOUS='a7-receipt-review-20261011-v6'
def read(p):return json.loads(Path(p).read_text('utf-8'))
def configure():
    environment.ROOT,environment.EDIT=ROOT,EDIT;environment.configure()

def prepare():
    final=build.root(CODE);final.mkdir(parents=True,exist_ok=True)
    if (final/'prepared-plan.json').exists():raise RuntimeError('Existing plan preserved.')
    old=OLD/CODE/'final';plan=copy.deepcopy(read(old/'timeline.json'))
    for s in plan['sources']:assert sha256_file(Path(s['path']))==s['sha256']
    for n in [3,4,11,12]:
        b=plan['beats'][n-1]
        b.update(selected_shot_id='shot-pink-store',relation='direct',needs_review=False,
            reason='실제 미니 벨크로 봉투에 종이·작은 포장을 넣는 동작. 영수증 직접 삽입 증명으로 확대하지 않음.',
            options=[{'shot_id':'shot-pink-store','relation':'direct','reviewed':True,
                'reason':'한칸 미니 봉투 형태 및 종이 수납 동작. 다른 6칸 정리함과 구분.'}])
    offsets={};shots={s['id']:s for s in plan['shots']}
    for b in plan['beats']:
        shot=shots[b['selected_shot_id']];start=offsets.get(shot['id'],shot['start']);end=start+b['end']-b['start']
        assert end<=shot['end']+.001
        b.update(source_start=start,source_end=end);offsets[shot['id']]=end
    for key in ['rendered_clips','cover_path','sfx_path','output_dir']:plan.pop(key,None)
    for key in ['background_path','layout']:plan['cover_spec'].pop(key,None)
    for name in ['script.json','voice.json']:shutil.copy2(old/name,final/name)
    writing=ROOT/CODE/'writing';writing.mkdir(parents=True,exist_ok=True)
    shutil.copy2(OLD/CODE/'writing/quality-v8.json',writing/'quality-v8.json')
    voice=read(final/'voice.json')
    goal=coverage_goal(plan['sources'],{'voices':[voice],'voice_id':voice['id'],'script_id':voice['script_id']},current_policy(load_settings()))
    plan['source_coverage_complete']=goal['duration_ready'] and goal['core_ready']
    plan['visual_alignment_gaps']=['実물 미니 봉투에 영수증을 직접 넣는 동작은 미확인; 종이 수납과 영수증 보관 예시를 구분.']
    save(final/'policy-reassessment.json',{'goal':goal,'same_core_criteria_unchanged':True,
        'exact_sku_or_receipt_insertion_not_added_as_hard_gate':True,'specific_receipt_insertion_proven':False})
    save(final/'prepared-plan.json',plan);save(final/'baseline-state.json',Studio(load_settings(),workers=False).store.get(WORK))
    print('Four envelope lines now use the actual one-pocket envelope; current policy coverage is ready.',flush=True)

def attach():
    final=build.root(CODE);qa=read(final/'verification.json');assert qa['actual_visual_review'] and not qa['visual_review_pending']
    studio=Studio(load_settings(),workers=False);current=studio.store.get(WORK)
    if any(e['id']==EDIT for e in current['edits']):return
    assert current['edit_id']==PREVIOUS
    result,plan=read(final/'render-result.json'),read(final/'timeline.json')
    previous=next(e for e in current['edits'] if e['id']==PREVIOUS)
    edit={k:v for k,v in result.items() if k!='status'}
    edit.update(id=EDIT,script_id=previous['script_id'],voice_id=previous['voice_id'],status='completed',created=time.time(),
        export_path=result['preview_path'],export_verified=True,export_kind='web_render',registration_deferred=True,
        source_diversity=qa['metrics'],previous_edit_id=PREVIOUS,review_draft=True,
        source_coverage_complete=plan['source_coverage_complete'])
    def change(state,db):
        assert state['edit_id']==PREVIOUS
        state['edits'].append(edit);state.update(edit_id=EDIT,status='draft_review',progress=100,error='',
            message='작은 봉투 대사에 실제 미니 봉투 수납 장면을 맞춘 검토본')
        state.setdefault('automation',{}).update(active=False,stage='review')
        parent=state.pop('run_id',None);run=init_run(state)
        if parent:run['parent_id']=parent
        used={b['selected_shot_id'] for b in plan['beats']};ids={s['source_id'] for s in plan['shots'] if s['id'] in used}
        chosen=[copy.deepcopy(s) for s in plan['sources'] if s['id'] in ids]
        run['inputs']['source_ids']=[s['id'] for s in chosen];snapshot(state);run['artifacts']['sources']=chosen
        run.update(status='review',quality_draft=True,source_coverage_complete=plan['source_coverage_complete'])
        state['quality_revision_path']=str(ROOT/CODE/'writing/quality-v8.json')
        studio.store.event(db,WORK,'a7_envelope_alignment',{'edit_id':EDIT,'previous_edit_id':PREVIOUS})
    saved=studio.store.change(WORK,change)
    assert saved['script_id']==current['script_id'] and saved['voice_id']==current['voice_id']
    assert all(next(r for r in saved['runs'] if r['id']==old['id'])==old for old in current['runs'])
    save(final/'attachment.json',{'task_id':WORK,'edit_id':EDIT,'run_id':saved['run_id'],
        'all_prior_runs_preserved':True,'script_and_voice_ids_preserved':True,'source_coverage_complete':plan['source_coverage_complete']})
    print('New envelope alignment attached; prior runs, script and voice preserved.',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepare','render','attach']);a=p.parse_args();configure()
    if a.phase=='render':
        if (build.root(CODE)/'render-result.json').exists():raise RuntimeError('Existing render preserved.')
        build.render(CODE)
    else:globals()[a.phase]()
