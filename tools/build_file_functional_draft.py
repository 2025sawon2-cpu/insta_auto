"""New review draft from function-reviewed clips; preserve every older run."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from PIL import Image, ImageDraw
from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json as save
from hotpost.source_finder import probe_video
from hotpost.source_quality import sha256_file
from hotpost.source_presentation import POLICY, review_scope
from hotpost.voicebench_adapter import VoiceBenchAdapter
from tools import build_tiktok_rework as build

CODE = 'DeRFXHpEwck'
BASE = Path('data/file-functional-quality-20261011-v3').resolve()
ROOT = BASE / CODE / 'final'
WRITING = BASE / CODE / 'writing/quality-v5.json'
RECEIVED = Path('data/daily-rework-20261011/DeRFXHpEwck/youtube-photo-case-xxQiZmoYNTE').resolve()


def read(path):
    return json.loads(path.read_text('utf-8'))


def setup():
    ROOT.mkdir(parents=True, exist_ok=True)
    bins = next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    os.environ['PATH'] = str(bins) + os.pathsep + os.environ['PATH']
    build.ROOT = BASE


def voice():
    quality = read(WRITING)
    assert {s['number'] for s in quality['scripts']} == {1, 2, 3}
    selected = next(s for s in quality['scripts'] if s['number'] == 1)
    review = read(WRITING.with_name('editorial-review-' + WRITING.stem.removeprefix('quality-') + '.json'))
    assert review['actual_text_review'] and review['writing_sha256'] == sha256_file(WRITING)
    digest = hashlib.sha256(selected['text'].encode()).hexdigest()
    script = dict(selected, id='file-functional-v3-script-' + digest[:12], sha256=digest,
                  human_review_pending=False, quality_draft=True, status='completed', created=time.time())
    save(ROOT / 'script.json', script)
    if (ROOT / 'voice.json').exists():
        assert read(ROOT / 'voice.json')['script_sha256'] == digest
        print('Matching personal voice retained.', flush=True)
        return
    submission = ROOT / 'voice-submission.json'
    request = read(submission).get('request_id') if submission.exists() else None
    result = VoiceBenchAdapter(load_settings()).synthesize(script['text'], ROOT / 'narration.wav',
        require_personal_clone=True, request_id=request, generation_key='file-functional-v3-' + digest,
        on_submitted=lambda rid: save(submission, {'request_id': rid, 'script_sha256': digest}),
        progress=lambda message, n: print(message, n, flush=True))
    save(ROOT / 'voice.json', dict(result, id='file-functional-v3-voice-' + digest[:12],
        path=str(ROOT / 'narration.wav'), sha256=sha256_file(ROOT / 'narration.wav'),
        script_id=script['id'], script_sha256=digest, duration=result['audio']['duration'],
        status='completed', created=time.time()))
    print('New personal voice saved', result['audio']['duration'], flush=True)


def supplement():
    if (ROOT / 'supplement-proposed.json').exists():
        print('Supplement derivatives retained for review.', flush=True)
        return
    reception = read(RECEIVED / 'ump-reassembly.json')
    original = next(t for t in reception['tracks'] if t.get('full_decode_passed'))
    assert sha256_file(Path(original['path'])) == original['sha256']
    definitions = [('blue-items', 10.3, 14.4, '다른 6칸 포켓에 작은 포장 소품을 넣어 정리하는 활용 예시'),
                   ('blue-paper', 16.2, 23.4, '다른 6칸 포켓에 작은 종이 라벨을 끼우는 활용 예시'),
                   ('blue-carry', 25.4, 28.4, '다른 6칸 포켓의 똑딱이 덮개를 닫아 손에 드는 활용 예시')]
    rows = []
    sheet = Image.new('RGB', (720, 345 * len(definitions)), '#222')
    draw = ImageDraw.Draw(sheet)
    for j, (name, start, end, observation) in enumerate(definitions):
        target = ROOT / 'clips' / (name + '.mp4')
        # The recorded 10x-speed note and lower captions are source overlays.
        # Do not replace or blur the handwritten labels on the actual product.
        masks = [[210, 132, 280, 75], [70, 984, 580, 70], [270, 1088, 180, 42]]
        vf = 'scale=720:1280,setsar=1,fps=30'
        for i, (x, y, w, h) in enumerate(masks):
            vf += f',split[base{i}][txt{i}];[txt{i}]crop={w}:{h}:{x}:{y},boxblur=12:2:6:2[blur{i}];[base{i}][blur{i}]overlay={x}:{y}'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(start), '-t', str(end-start),
            '-i', original['path'], '-an', '-vf', vf, '-c:v', 'libx264', '-preset', 'veryfast',
            '-crf', '18', str(target)], check=True, capture_output=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(target), '-f', 'null', '-'],
                       check=True, capture_output=True)
        meta, frames = probe_video(target), []
        for i, fraction in enumerate((.05, .35, .65, .95)):
            t = (meta['duration'] - .05) * fraction
            frame = target.with_name(name + f'-{i}.jpg')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(t), '-i', str(target),
                            '-frames:v', '1', str(frame)], check=True, capture_output=True)
            frames.append({'path': str(frame), 'timestamp': t, 'sha256': sha256_file(frame)})
            with Image.open(frame) as im:
                im.thumbnail((180, 320)); sheet.paste(im, (i*180, j*345+25))
            draw.text((i*180+3, j*345+3), f'{name} {t:.2f}', fill='white')
        rows.append({'id': 'file-functional-v3-' + name, 'name': name, 'path': str(target),
            'sha256': sha256_file(target), 'video_meta': meta, 'original_path': original['path'],
            'original_sha256': original['sha256'], 'original_interval': {'start': start, 'end': end},
            'url': reception.get('url') or 'https://www.youtube.com/shorts/xxQiZmoYNTE',
            'origin_url': 'https://www.youtube.com/shorts/xxQiZmoYNTE', 'provider': 'youtube',
            'rights': 'unknown-check-before-reuse', 'source_role': 'context',
            'proposed_observation': observation, 'evidence_frames': frames,
            'preprocessed_blur_regions_px': masks, 'full_decode_passed': True,
            'pending_visual_review': True, 'editing_eligible': False,
            'exact_reference_sku_confirmed': False, 'original_action_speed': 'source contains10x-speed demonstration'})
    sheet.save(ROOT / 'supplement-review.jpg', quality=95)
    save(ROOT / 'supplement-proposed.json', rows)
    print('Three downloaded-source derivatives await actual review.', flush=True)


def prepare():
    if BASE.name == 'file-functional-quality-20261011-v5':
        prior = BASE.with_name('file-functional-quality-20261011-v4') / CODE / 'final'
        sources = read(prior / 'all-approved-sources.json')
        assert all(sha256_file(Path(s['path'])) == s['sha256'] for s in sources)
        supplements = []
    else:
        sources = read(ROOT / 'approved-sources.json') + read(ROOT / 'supplement-proposed.json')
        review = read(ROOT / 'supplement-reviewed.json')
        assert review['reviewed_source_sha256'] == {s['id']: s['sha256'] for s in sources[4:]}
        supplements = sources[4:]
    for source in supplements:
        limits = ['다른 6칸 아코디언/똑딱이 수납함의 활용 예시. 원본A7벨크로 봉투와 동일 상품 아님.',
                  '작은 종이·포장 소품을 보관하거나 들고 가는 상황만 사용. 벨크로·정량 수납·영수증 실제 시연의 증거 아님.',
                  '약 포장 소품으로 치료·보관 안전을 주장하지 않는다. 원본은 일부10배속 시연.']
        source.update(pending_visual_review=False, editing_eligible=True,
            source_quality='reviewed-portrait', blur_required=False, watermark_masks=[],
            presentation_review_required=False, relevance_review_required=False)
        source['functional_review'] = {'reviewed': True, 'source_sha256': source['sha256'],
            'same_core_function': False, 'context_usable': True, 'context_usage_limits': limits,
            'observed_actions': [source['proposed_observation']],
            'evidence_frames': [f['path'] for f in source['evidence_frames']], 'reviewer': 'codex_session_visual_review'}
        source['presentation_review'] = {'policy': POLICY, 'reviewed': True,
            'source_sha256': source['sha256'], 'scope': review_scope(source), 'usable': True,
            'quality_usable': True, 'action_preserved': True,
            'observations': [source['proposed_observation']], 'evidence_frames': source['evidence_frames'],
            'reviewer': 'codex_session_visual_review'}
    save(ROOT / 'all-approved-sources.json', sources)
    script, voice = read(ROOT / 'script.json'), read(ROOT / 'voice.json')
    assert voice['script_sha256'] == script['sha256']
    plan = build.boundary(CODE, 'analyze', sources=sources, script=script, voice=voice,
                          thumbnail_lines=script['thumbnail_lines'])['plan']
    plan['shots'] = [dict(id='shot-' + s['name'], source_id=s['id'], path=s['path'], sha256=s['sha256'],
        start=0, end=s['video_meta']['duration'], frames=[f['path'] for f in s['evidence_frames']],
        observation=s['proposed_observation'], source_role=s['source_role'],
        context_usage_limits=s['functional_review']['context_usage_limits'],
        evidence_status='actual-decoded-portrait-review') for s in sources]
    plan.update(source_notice='유사 제품 활용 예시 · 동일 상품 아님', quality_draft=True,
                source_coverage_complete=False,
                visual_alignment_gaps=['같은A7상품의 영수증 실제 수납·가방 휴대 시연 미확보'])
    plan['cover_font_style'] = {'font_path': str(load_settings().auto_capcut_root / 'auto_capcut/assets/fonts/DoHyeon-Regular.ttf'),
        'font_family': 'Do Hyeon', 'font_title': '도현', 'font_weight': 700,
        'font_resource_id': '', 'font_status': 'available'}
    save(ROOT / 'prepared-plan.json', plan)
    print(json.dumps([(i+1, b['text'], round(b['start'], 2), round(b['end'], 2))
                      for i,b in enumerate(plan['beats'])], ensure_ascii=False), flush=True)


def select():
    build.select(CODE)


def render():
    build.render(CODE)
    qa = read(ROOT / 'verification.json')
    qa.update(quality_draft=True, source_coverage_complete=False, final_quality_passed=False,
              audio_listened=False)
    save(ROOT / 'verification.json', qa)


def attach():
    from hotpost.studio import Studio
    from hotpost.studio_workflow import init_run, snapshot
    qa = read(ROOT / 'verification.json')
    assert not qa['visual_review_pending']
    assert qa['reviewed_video_sha256'] == sha256_file(ROOT / 'preview.mp4')
    result, plan = read(ROOT / 'render-result.json'), read(ROOT / 'timeline.json')
    script, voice, quality = read(ROOT / 'script.json'), read(ROOT / 'voice.json'), read(WRITING)
    studio = Studio(load_settings(), workers=False)
    state = next(s for s in studio.store.list() if s['shortcode'] == CODE)
    edit_id = BASE.name
    if any(e['id'] == edit_id for e in state['edits']):
        print('Already attached version retained.', flush=True)
        return
    save(ROOT / 'state-before-attachment.json', state)
    edit = {k:v for k,v in result.items() if k != 'status'}
    edit.update(id=edit_id, script_id=script['id'], voice_id=voice['id'], created=time.time(),
        status='completed', export_path=result['preview_path'], export_verified=True,
        exported_at=time.time(), export_kind='web_render', registration_deferred=True,
        source_diversity=qa['metrics'], review_draft=True, source_coverage_complete=False,
        source_limit='같은 기능의 봉투 시연 확보. 영수증 장면의 정확도·후킹은 검토 및 보완 중.')
    def change(s, db):
        for key, obj in [('scripts', script), ('voices', voice), ('edits', edit)]:
            assert not any(x['id'] == obj['id'] for x in s[key])
            s[key].append(copy.deepcopy(obj))
        s['sources'].extend(copy.deepcopy(x) for x in plan['sources']
                            if not any(y['id'] == x['id'] for y in s['sources']))
        s.update(script_id=script['id'], voice_id=voice['id'], edit_id=edit_id,
            status='draft_review', progress=100, error='',
            message='새 검토본: 같은 기능 시연·가방 휴대 장면·구간 반복0초. 후킹 보완 중.')
        s.setdefault('automation', {}).update(active=False, stage='source_wait', source_coverage_complete=False)
        s['script_variants'] = copy.deepcopy(quality)
        s.pop('run_id', None)
        run = init_run(s)
        used = {b['selected_shot_id'] for b in plan['beats']}
        ids = {shot['source_id'] for shot in plan['shots'] if shot['id'] in used}
        run['inputs']['source_ids'] = sorted(ids)
        snapshot(s)
        run.update(status='review', quality_draft=True, source_coverage_complete=False)
        studio.store.event(db, s['id'], 'file_functional_quality_draft', {'edit_id': edit_id, 'metrics': qa['metrics']})
    saved = studio.store.change(state['id'], change)
    for prior in state.get('runs', []):
        assert next(x for x in saved['runs'] if x['id'] == prior['id']) == prior
    save(ROOT / 'attachment.json', {'task_id': saved['id'], 'run_id': saved['run_id'],
        'edit_id': edit_id, 'old_runs_preserved': True, 'source_coverage_complete': False})
    print('New review run attached; older runs preserved and no queue started.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['voice', 'supplement', 'prepare', 'select', 'render', 'attach'])
    parser.add_argument('--revision', choices=['v3', 'v4', 'v5'], default='v3')
    args = parser.parse_args()
    if args.revision in ('v4', 'v5'):
        BASE = BASE.with_name('file-functional-quality-20261011-' + args.revision)
        ROOT = BASE / CODE / 'final'
    if args.revision == 'v5':
        WRITING = WRITING.with_name('quality-v7.json')
    if (ROOT / 'attachment.json').exists() and args.phase != 'attach':
        raise RuntimeError('Attached review version is immutable; prepare a new version.')
    setup()
    globals()[args.phase]()
