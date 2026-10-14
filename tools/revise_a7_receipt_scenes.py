"""Add observed receipt scenes without changing narration or prior artifacts."""
import argparse
import copy
import json
import shutil
import subprocess
import time
from pathlib import Path
from PIL import Image, ImageDraw
from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json as save
from hotpost.source_finder import probe_video
from hotpost.source_quality import sha256_file
from hotpost.source_presentation import POLICY, review_scope
from hotpost.studio import Studio
from hotpost.studio_workflow import init_run, snapshot
from tools import build_tiktok_rework as build
from tools import revise_cart_youtube_actions as environment

CODE = 'DeRFXHpEwck'
ROOT = Path('data/a7-receipt-review-20261011-v6').resolve()
OLD = Path('data/file-functional-quality-20261011-v5').resolve()
EDIT = 'a7-receipt-review-20261011-v6'
PREVIOUS = 'file-functional-quality-20261011-v5'
WORK = 'work-440c6d0fc4794fa5'


def read(path):
    return json.loads(Path(path).read_text('utf-8'))


def configure():
    environment.ROOT, environment.EDIT = ROOT, EDIT
    environment.configure()


def clips():
    final = build.root(CODE)
    final.mkdir(parents=True, exist_ok=True)
    receipt = read(ROOT / CODE / 'receipt-review/reception.json')
    raw = Path(receipt['path'])
    assert receipt['full_decode_passed'] and sha256_file(raw) == receipt['sha256']
    definitions = [('receipt-front', .1, 2.1, '영수증과 티켓이 들어 있는 소형 다중 포켓 파일의 외관'),
                   ('receipt-pages', 6.4, 9.35, '영수증이 들어 있는 파일의 페이지를 넘겨 보관 상태를 확인'),
                   ('receipt-mixed', 13.9, 15.05, '서로 다른 영수증과 종이 소품을 보관한 페이지')]
    rows, sheet = [], Image.new('RGB', (960, 1356), '#222')
    draw = ImageDraw.Draw(sheet)
    for j, (name, start, end, observation) in enumerate(definitions):
        target = final / 'clips' / (name + '-v2.mp4')
        target.parent.mkdir(exist_ok=True)
        if target.exists():
            raise RuntimeError('Existing derivatives preserved; use a new revision.')
        band = [185, 508, 365, 70]
        x, y, w, h = band
        vf = (f'scale=720:1280,setsar=1,fps=30,split[base][txt];'
              f'[txt]crop={w}:{h}:{x}:{y},boxblur=12:2:6:2[blur];[base][blur]overlay={x}:{y}')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(start), '-t', str(end-start),
                        '-i', str(raw), '-an', '-vf', vf, '-c:v', 'libx264', '-preset', 'veryfast',
                        '-crf', '18', str(target)], check=True, capture_output=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(target), '-f', 'null', '-'],
                       check=True, capture_output=True)
        meta, frames = probe_video(target), []
        for k, frac in enumerate((.05, .35, .65, .95)):
            t = (meta['duration']-.05)*frac
            frame = target.with_name(target.stem + f'-{k}.jpg')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(t), '-i', str(target),
                            '-frames:v', '1', str(frame)], check=True, capture_output=True)
            frames.append({'path': str(frame), 'timestamp': t, 'sha256': sha256_file(frame)})
            im = Image.open(frame); im.thumbnail((240, 426))
            sheet.paste(im, (k*240, j*452+25)); draw.text((k*240, j*452+2), f'{name} {t:.2f}s', fill='white')
        rows.append({'id': EDIT+'-'+name, 'name': name, 'path': str(target), 'sha256': sha256_file(target),
            'video_meta': meta, 'original_path': str(raw), 'original_sha256': receipt['sha256'],
            'original_interval': {'start': start, 'end': end}, 'url': receipt['url'],
            'provider': 'tiktok', 'rights': 'unknown-check-before-reuse', 'source_role': 'context',
            'proposed_observation': observation, 'evidence_frames': frames,
            'pending_visual_review': True, 'editing_eligible': False, 'preprocessed_blur_regions_px': [band]})
    save(final / 'proposed-sources-v2.json', rows)
    sheet.save(final / 'clip-review-v2.jpg', quality=95)
    print('Three bounded receipt clips saved for actual review.', flush=True)


def prepare():
    final = build.root(CODE)
    if (final / 'prepared-plan.json').exists():
        raise RuntimeError('Existing prepared plan preserved.')
    approval = read(final / 'source-review.json')
    sources = read(final / 'proposed-sources-v2.json')
    assert approval['actual_visual_review'] and approval['source_hashes'] == {s['id']:s['sha256'] for s in sources}
    plan = copy.deepcopy(read(OLD / CODE / 'final/timeline.json'))
    writing = read(ROOT / CODE / 'writing/quality-v8.json')
    chosen = next(s for s in writing['scripts'] if s['number'] == 1)
    oldscript = read(OLD / CODE / 'final/script.json')
    assert chosen['text'] == oldscript['text']
    limits = ['다른 다중 포켓 파일의 영수증 보관 활용 예시. A7 벨크로 봉투와 동일 상품 아님.',
              '실제 영수증 보관 상태와 페이지 넘김은 확인. 영수증을 넣는 동작·벨크로 여밈·정량 수납의 증거는 아님.']
    for s in sources:
        s.update(pending_visual_review=False, editing_eligible=True, source_quality='reviewed-portrait',
                 blur_required=False, watermark_masks=[], presentation_review_required=False,
                 relevance_review_required=False)
        s['functional_review'] = {'reviewed': True, 'source_sha256': s['sha256'],
            'same_core_function': False, 'context_usable': True, 'context_usage_limits': limits,
            'observed_actions': [s['proposed_observation']], 'evidence_frames': s['evidence_frames']}
        s['presentation_review'] = {'policy': POLICY, 'reviewed': True, 'source_sha256': s['sha256'],
            'scope': review_scope(s), 'usable': True, 'quality_usable': True, 'action_preserved': True,
            'observations': [s['proposed_observation']], 'evidence_frames': s['evidence_frames']}
        plan['sources'].append(s)
        plan['shots'].append({'id':'shot-'+s['name'], 'source_id':s['id'], 'path':s['path'],
            'sha256':s['sha256'], 'start':0, 'end':s['video_meta']['duration'],
            'frames':[f['path'] for f in s['evidence_frames']], 'observation':s['proposed_observation'],
            'source_role':'context', 'context_usage_limits':limits, 'evidence_status':'actual-reviewed-receipt-state'})
    changed = {1:'receipt-front', 2:'receipt-front', 8:'receipt-pages', 9:'receipt-pages',
               10:'receipt-pages', 13:'receipt-mixed'}
    offset = {}
    for n, name in changed.items():
        shot = next(s for s in plan['shots'] if s['id']=='shot-'+name)
        beat = plan['beats'][n-1]; start = offset.get(name, 0)
        beat.update(selected_shot_id=shot['id'], source_start=start, relation='context',
            reason=shot['observation']+' · 넣는 동작의 직접 증거와 구분',
            options=[{'shot_id':shot['id'], 'relation':'context', 'reason':shot['observation'], 'reviewed':True}])
        offset[name] = start + beat['end']-beat['start']
    for key in ('layout', 'background_path'):
        plan['cover_spec'].pop(key, None)
    plan['cover_spec'].update(lines=chosen['thumbnail_lines'],
        copy_review={'reviewed':True, 'text_source':'officialCodex quality-v8 variant1',
                     'hook_review':chosen['thumbnail_mechanism'],
                     'source_review':'Previously inspected pink envelope opening and round Velcro; frame retained'})
    plan['thumbnail_lines'] = chosen['thumbnail_lines']
    plan['source_coverage_complete'] = False
    plan['visual_alignment_gaps'] = ['미니 벨크로 봉투에 영수증을 실제로 넣는 동작 미확보']
    for key in ('rendered_clips', 'cover_path', 'sfx_path', 'output_dir'):
        plan.pop(key, None)
    script = {**oldscript, 'thumbnail_lines':chosen['thumbnail_lines'],
              'thumbnail_mechanism':chosen['thumbnail_mechanism']}
    save(final / 'script.json', script)
    shutil.copy2(OLD / CODE / 'final/voice.json', final / 'voice.json')
    save(final / 'prepared-plan.json', plan)
    save(final / 'baseline-state.json', Studio(load_settings(), workers=False).store.get(WORK))
    save(final / 'revision-origin.json', {'changed_beats': list(changed), 'body_preserved':True,
        'voice_preserved':True, 'tts_regenerated':False, 'new_downloads_used':1,
        'exact_product_and_receipt_insertion_not_proven':True})
    print('Receipt scenes and new cover text prepared; body/voice unchanged.', flush=True)


def attach():
    final = build.root(CODE); qa = read(final / 'verification.json')
    assert qa['actual_visual_review'] and not qa['visual_review_pending']
    studio = Studio(load_settings(), workers=False); current = studio.store.get(WORK)
    if any(e['id']==EDIT for e in current['edits']): return
    assert current['edit_id']==PREVIOUS
    old = next(e for e in current['edits'] if e['id']==PREVIOUS)
    result, plan = read(final / 'render-result.json'), read(final / 'timeline.json')
    edit = {k:v for k,v in result.items() if k!='status'}
    edit.update(id=EDIT, script_id=old['script_id'], voice_id=old['voice_id'], status='completed',
        created=time.time(), export_path=result['preview_path'], export_verified=True,
        export_kind='web_render', registration_deferred=True, source_diversity=qa['metrics'],
        previous_edit_id=PREVIOUS, review_draft=True, source_coverage_complete=False,
        source_limit='유사 제품 영수증 보관 예시. 미니 벨크로 봉투의 실제 삽입 동작 미확보')
    def change(state, db):
        assert state['edit_id']==PREVIOUS
        state['edits'].append(edit)
        state['sources'].extend(copy.deepcopy(s) for s in plan['sources']
                               if not any(x['id']==s['id'] for x in state['sources']))
        state.update(edit_id=EDIT, status='draft_review', progress=100, error='',
                     message='영수증 보관 실물 장면과 구체적인 썸네일을 보완한 검토본')
        state.setdefault('automation',{}).update(active=False, stage='source_wait')
        parent = state.pop('run_id',None); run=init_run(state)
        if parent: run['parent_id']=parent
        used = {b['selected_shot_id'] for b in plan['beats']}
        ids = {s['source_id'] for s in plan['shots'] if s['id'] in used}
        chosen = [copy.deepcopy(s) for s in plan['sources'] if s['id'] in ids]
        run['inputs']['source_ids']=[s['id'] for s in chosen]
        snapshot(state); run['artifacts']['sources']=chosen
        run.update(status='review', quality_draft=True, source_coverage_complete=False)
        state['quality_revision_path']=str(ROOT / CODE / 'writing/quality-v8.json')
        studio.store.event(db,WORK,'a7_receipt_revision',{'edit_id':EDIT,'previous_edit_id':PREVIOUS})
    saved=studio.store.change(WORK,change)
    assert all(next(r for r in saved['runs'] if r['id']==p['id'])==p for p in current['runs'])
    assert saved['script_id']==current['script_id'] and saved['voice_id']==current['voice_id']
    save(final / 'attachment.json', {'task_id':WORK,'edit_id':EDIT,'run_id':saved['run_id'],
        'prior_runs_unchanged':True,'script_and_voice_ids_preserved':True})
    print('Receipt draft attached; prior runs retained.',flush=True)


def share():
    from tools import share_daily_rework as public
    public.ROOT=ROOT;public.TITLES[CODE]='미니 파일홀더 · 영수증 보관 장면 보완'
    public.main(codes=(CODE,), port=8815, receipt_name=EDIT+'-share.json',
                writing_revisions={CODE:'quality-v8.json'}, review_codes=(CODE,))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['clips','prepare','render','attach','share'])
    args=parser.parse_args();configure()
    if args.phase=='render':
        if (build.root(CODE)/'render-result.json').exists(): raise RuntimeError('Existing render preserved.')
        build.render(CODE)
    else: globals()[args.phase]()
