"""Attach the four completed, reviewed outputs without modifying earlier runs."""
import copy,json,time
from pathlib import Path
from PIL import Image
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.studio_workflow import init_run,snapshot
from hotpost.editing_adapter import _atomic_json
from hotpost.source_quality import sha256_file
from hotpost.source_finder import probe_video
from tools.report_seven_revision_changes import summary

ROOT=Path('data/feedback-remake-20261012-v1').resolve()
VERSIONS={'DeJ7hD6zsnR':'final-v3','DeTaESASnr_':'final-v3','DeTJ6HbKCdF':'final-v4','DeSvpmAsWgZ':'final-v3'}
def read(p):return json.loads(p.read_text('utf-8'))

def attach(code,version):
    out=ROOT/code/version;base=read(ROOT/code/'baseline.json');report=read(out/'daily-review.json')
    result=read(out/'render-result.json');plan=read(out/'timeline.json')
    assert report['passed'] and report['audio_timing_audit']['passed']
    assert sha256_file(Path(result['preview_path']))==report['render_sha256']
    assert read(out/'effective-voice-audit.json')['matches_preferred_configuration']
    metrics=summary(out/'timeline.json')
    _atomic_json(out/'verification.json',{'actual_visual_review':True,'visual_review_pending':False,
        'metadata':probe_video(Path(result['preview_path'])),'metrics':metrics,
        'audio_timing_audit':report['audio_timing_audit'],'auditory_naturalness_reviewed':False,
        'render_sha256':report['render_sha256'],'quality_review_path':report['review_path']})
    Image.open(out/'cover.png').convert('RGB').save(out/'comparison-poster.jpg',quality=95)
    studio=Studio(load_settings(),workers=False);current=studio.store.get(base['task_id'])
    editid='remake-20261012-'+code+'-'+version
    if any(e['id']==editid for e in current['edits']):return
    assert current['edit_id']==base['edit']['id']
    content=out if (out/'script.json').exists() else ROOT/code/'final'
    script=read(content/'script.json');voice=read(content/'voice.json')
    selection=read(ROOT/code/'final/writing-selection.json');quality=read(Path(selection['quality_path']))
    edit={**result,'id':editid,'status':'completed','created':time.time(),
        'script_id':script['id'],'voice_id':voice['id'],'export_path':result['preview_path'],
        'export_verified':True,'export_kind':'web_render','review_draft':True,
        'registration_deferred':True,'quality_verified':True,'quality_review_path':report['review_path'],
        'previous_edit_id':current['edit_id']}
    def update(s,db):
        s['scripts'].append(copy.deepcopy(script));s['voices'].append(copy.deepcopy(voice))
        candidates=copy.deepcopy(quality['scripts'])
        # Preserve original three proposals; separately record the final clause correction.
        s.update(script_id=script['id'],approved_script_id=script['id'],voice_id=voice['id'],
            approved_voice_id=voice['id'],quality_revision_path=selection['quality_path'],script_candidates=candidates,
            selected_candidate=copy.deepcopy(script),cover_revision_path=str(out/'cover-copy-revision.json'))
        if (out/'script-revision.json').exists():s['script_revision_path']=str(out/'script-revision.json')
        merged={v['id']:v for v in s['sources']};merged.update({v['id']:copy.deepcopy(v) for v in plan['sources']})
        s['sources']=list(merged.values());s['edits'].append(edit)
        s.update(edit_id=editid,status='draft_review',progress=100,error='',message='재제작 완료 · 실제 화면·썸네일·출력 음성 시간 검토 통과')
        s.setdefault('automation',{}).update(active=False)
        parent=s.pop('run_id',None);run=init_run(s)
        if parent:run['parent_id']=parent
        snapshot(s);used={b['selected_shot_id'] for b in plan['beats']};ids={h['source_id'] for h in plan['shots'] if h['id'] in used}
        run['inputs']['source_ids']=list(ids);run['artifacts']['sources']=[copy.deepcopy(v) for v in plan['sources'] if v['id'] in ids]
        run.update(status='review',quality_draft=True)
        studio.store.event(db,s['id'],'user_feedback_remake',{'edit_id':editid,'previous_edit_id':current['edit_id']})
    saved=studio.store.change(current['id'],update)
    assert all(next(r for r in saved['runs'] if r['id']==old['id'])==old for old in current['runs'])
    _atomic_json(out/'attachment.json',{'task_id':current['id'],'edit_id':editid,'run_id':saved['run_id'],'prior_runs_unchanged':True,'summary':metrics})
    print(code,version,metrics['parent_files'],metrics['largest_source_share'],flush=True)

if __name__=='__main__':
    for code,version in VERSIONS.items():attach(code,version)
