"""Versioned mirror action correction; preserve narration and all earlier runs."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess
import time
from PIL import Image, ImageDraw
from hotpost.config import load_settings
from hotpost.source_finder import probe_video
from hotpost.source_quality import sha256_file
from hotpost.source_presentation import POLICY, review_scope
from hotpost.studio import Studio
from hotpost.studio_workflow import init_run, snapshot
from tools import build_tiktok_rework as build
from tools import revise_cart_youtube_actions as environment
from tools.rework_tiktok_batch import save

CODE = 'DeTaESASnr_'
ROOT = Path('data/mirror-actions-quality-20261011-v4')
OLD = Path('data/daily-rework-20261011')
EDIT = 'mirror-actions-quality-20261011-v4'
WORK = 'work-d1fa59214c564076'
PREVIOUS = 'tiktok-rework-20261011-' + CODE


def read(path):
    return json.loads(Path(path).read_text('utf-8'))


def configure():
    environment.ROOT, environment.EDIT = ROOT, EDIT
    environment.configure()


def clips():
    final = build.root(CODE)
    final.mkdir(parents=True, exist_ok=True)
    verified = read(ROOT.with_name('mirror-actions-quality-20261011-v4') / CODE /
                    'final/raw-download-verification.json')['existing_downloads_verified']
    definitions = [
        ('closing', '7683128298301410578', 19.0, 19.96, '보드를 왼쪽으로 밀어 거울을 가리는 실제 닫기 동작'),
        ('closed-board', '7683128298301410578', 6.08, 7.18, '벽에 설치되어 닫힌 은색 자석 보드 전체'),
        ('memo-keyring', '7694945682506960149', 13.78, 15.18, '자석 메모판과 오른쪽 금속 열쇠고리의 활용 예시. 개별 열쇠 종류 미확인'),
    ]
    if EDIT.endswith('-v5'):
        definitions = [
            ('opening-finish', '7657376551079660807', 17.7, 19.65, '보드를 오른쪽으로 밀어 전신거울을 드러내는 동작'),
            ('closed-gallery', '7683128298301410578', 7.2, 8.2, '벽에 설치되어 장식과 메모가 붙은 은색 보드'),
            ('cta-open', '7657376551079660807', 20.4, 22.99, '설치된 전신거울과 자석 보드의 다른 방 활용 모습'),
        ]
    sources = []
    sheet = Image.new('RGB', (960, 452 * len(definitions)), '#222')
    draw = ImageDraw.Draw(sheet)
    for row_index, (name, vid, start, end, observation) in enumerate(definitions):
        row = next(x for x in verified if x['url'].endswith('/' + vid))
        raw = Path(row['path'])
        assert row['whole_decode_passed'] and sha256_file(raw) == row['source_sha256']
        target = final / 'clips' / (name + '-v3.mp4')
        target.parent.mkdir(exist_ok=True)
        if target.exists():
            raise RuntimeError('Existing derivative preserved; use a new version')
        # Blur the promotional subtitle only; creator credit remains visible.
        band = [65, 385, 590, 115] if name != 'memo-keyring' else [135, 600, 485, 100]
        x, y, w, h = band
        vf = (f'scale=720:1280,setsar=1,fps=30,split[base][txt];'
              f'[txt]crop={w}:{h}:{x}:{y},boxblur=12:2[blur];[base][blur]overlay={x}:{y}')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(start), '-t', str(end-start),
            '-i', str(raw), '-an', '-vf', vf, '-c:v', 'libx264', '-preset', 'veryfast',
            '-crf', '18', str(target)], check=True, capture_output=True)
        meta = probe_video(target)
        frames = []
        for index, fraction in enumerate((.02, .35, .65, .98)):
            second = max(0, meta['duration'] - .04) * fraction
            frame = target.with_name(f'{name}-v3-{index}.jpg')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(second), '-i', str(target),
                            '-frames:v', '1', str(frame)], check=True, capture_output=True)
            frames.append({'path': str(frame), 'timestamp': second, 'sha256': sha256_file(frame)})
            with Image.open(frame) as im:
                im.thumbnail((240, 426)); sheet.paste(im, (index * 240, row_index * 452 + 24))
            draw.text((index * 240 + 3, row_index * 452 + 3), f'{name} {second:.2f}s', fill='white')
        sources.append({'id': EDIT + '-' + name, 'name': name, 'path': str(target),
            'sha256': sha256_file(target), 'video_meta': meta, 'original_path': str(raw),
            'original_sha256': row['source_sha256'], 'original_interval': {'start': start, 'end': end},
            'url': row['url'], 'provider': 'tiktok', 'rights': 'unknown-check-before-reuse',
            'source_role': 'context' if name == 'memo-keyring' else 'core',
            'proposed_observation': observation, 'evidence_frames': frames,
            'pending_visual_review': True, 'editing_eligible': False,
            'preprocessed_blur_regions_px': [band]})
    sheet.save(final / 'new-clips-review-v3.jpg', quality=95)
    save(final / 'proposed-new-sources.json', sources)
    previous = read(OLD / CODE / 'final/timeline.json')
    cover_path = final / 'clips/opening-finish-v3.mp4' if EDIT.endswith('-v5') else next(
        s['path'] for s in previous['shots'] if s['id'] == 'shot-entry-mirror')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', '1.2' if EDIT.endswith('-v5') else '2',
                    '-i', str(cover_path), '-frames:v', '1',
                    str(final / 'proposed-cover-source.jpg')], check=True, capture_output=True)
    print('Three new derivatives and a proposed used-CTA cover await actual review.', flush=True)


def prepare():
    final = build.root(CODE)
    if (final / 'prepared-plan.json').exists():
        raise RuntimeError('Existing prepared plan preserved')
    editorial = read(OLD / CODE / 'writing/quality-v5.json')
    assert not editorial['human_review_pending']
    base = (ROOT.with_name('mirror-actions-quality-20261011-v4') / CODE / 'final/timeline.json'
            if EDIT.endswith('-v5') else OLD / CODE / 'final/timeline.json')
    plan = copy.deepcopy(read(base))
    script = next(s for s in editorial['scripts'] if s['number'] == 1)
    assert script['text'] == plan['script_text']
    sources = read(final / 'proposed-new-sources.json')
    reviewed = read(final / 'new-clips-reviewed.json')
    assert reviewed['reviewed_source_sha256'] == {s['id']:s['sha256'] for s in sources}
    for source in sources:
        source.update(pending_visual_review=False, editing_eligible=True, blur_required=False,
                      source_quality='reviewed-portrait', presentation_review_required=False,
                      relevance_review_required=False, watermark_masks=[])
        limits = ['유사 슬라이딩 거울/보드 기능. 같은 모델·독립 촬영자 수는 미확인.',
                  '금속 열쇠고리와 메모판의 활용 맥락이며 열쇠 종류·일체형 메모판 제공은 미확인.']
        source['functional_review'] = {'reviewed': True, 'source_sha256': source['sha256'],
            'same_core_function': source['source_role'] == 'core', 'context_usable': True,
            'context_usage_limits': limits, 'observed_actions': [source['proposed_observation']],
            'evidence_frames': [f['path'] for f in source['evidence_frames']], 'reviewer': 'codex_session_visual_review'}
        source['presentation_review'] = {'policy': POLICY, 'reviewed': True,
            'source_sha256': source['sha256'], 'scope': review_scope(source), 'usable': True,
            'quality_usable': True, 'action_preserved': True, 'observations': [source['proposed_observation']],
            'evidence_frames': source['evidence_frames'], 'reviewer': 'codex_session_visual_review'}
        plan['sources'].append(source)
        plan['shots'].append({'id': 'shot-' + source['name'], 'source_id': source['id'],
            'path': source['path'], 'sha256': source['sha256'], 'start': 0,
            'end': source['video_meta']['duration'], 'source_role': source['source_role'],
            'observation': source['proposed_observation'], 'context_usage_limits': limits,
            'evidence_status': 'actual-decoded-frame-review', 'frames': [f['path'] for f in source['evidence_frames']]})
    groups = [(8, 8, 'closing'), (9, 9, 'closed-board'), (10, 11, 'decorate'),
              (13, 13, 'memo-keyring'), (18, 20, 'entry-mirror')]
    if EDIT.endswith('-v5'):
        groups = [(6, 7, 'opening-finish'), (17, 17, 'closed-gallery'), (18, 20, 'cta-open')]
        old_open = next(s for s in plan['shots'] if s['id'] == 'shot-mirror-slide')
        old_open['end'] = 1.84
        old_open['observation'] = '앞부분의 열린 거울만 사용. 뒤의 닫기 컷은 제외.'
        next(s for s in plan['shots'] if s['id']=='shot-full-mirror')['observation'] = '설치된 자석 보드의 닫힌 모습. 거울로 전신 확인하는 직접 장면은 아님.'
    for first, last, name in groups:
        shot = next(s for s in plan['shots'] if s['id'] == 'shot-' + name)
        shot['start'] = .5 if name == 'decorate' else 0
        cursor = shot['start']
        for beat in plan['beats'][first-1:last]:
            duration = beat['end'] - beat['start']
            beat.update(selected_shot_id=shot['id'], options=[{'shot_id': shot['id'], 'relation': shot['source_role'],
                'reason': shot['observation'], 'reviewed': True}], source_start=cursor, source_end=cursor+duration,
                needs_review=False)
            cursor += duration
        assert cursor <= shot['end'] + .04, (name, cursor, shot['end'])
    # Actual closing starts at cue 8 (cue 7 is the end of the opening sentence).
    cover = plan['cover_spec']
    cover.update(lines=script['thumbnail_lines'])
    cover.pop('layout', None); cover.pop('background_path', None)
    cover_name = 'shot-opening-finish' if EDIT.endswith('-v5') else 'shot-entry-mirror'
    shot = next(s for s in plan['shots'] if s['id'] == cover_name)
    timestamp = 1.2 if EDIT.endswith('-v5') else 2
    cover_beat = 5 if EDIT.endswith('-v5') else 17
    cover['source'].update(shot_id=shot['id'], source_id=shot['source_id'], source_sha256=shot['sha256'],
        timestamp=timestamp, timeline_time=plan['beats'][cover_beat]['start']+timestamp,
        frame_path=str(final / 'proposed-cover-source.jpg'), reviewed=True, reviewer='codex')
    for name in ('script.json', 'voice.json'):
        shutil.copy2(OLD / CODE / 'final' / name, final / name)
    save(final / 'prepared-plan.json', plan)
    save(final / 'baseline-state.json', Studio(load_settings(), workers=False).store.get(WORK))
    save(final / 'revision-origin.json', {'changed_beats': [6,7,8,9,10,11,13,17,18,19,20] if EDIT.endswith('-v5') else [8,9,10,11,13,18,19,20],
        'body_script_and_voice_preserved': True, 'tts_regenerated': False,
        'new_downloads': 0, 'writing_revision': str(OLD / CODE / 'writing/quality-v5.json')})
    print('Mirror action plan prepared; narration preserved.', flush=True)


def attach():
    final = build.root(CODE)
    qa = read(final / 'verification.json')
    assert qa['actual_visual_review'] and not qa['visual_review_pending']
    studio = Studio(load_settings(), workers=False)
    current = studio.store.get(WORK)
    if any(e['id'] == EDIT for e in current['edits']):
        return
    assert current['edit_id'] == PREVIOUS
    old = next(e for e in current['edits'] if e['id'] == PREVIOUS)
    result, plan = read(final / 'render-result.json'), read(final / 'timeline.json')
    edit = {k:v for k,v in result.items() if k != 'status'}
    edit.update(id=EDIT, script_id=old['script_id'], voice_id=old['voice_id'], status='completed',
        created=time.time(), export_path=result['preview_path'], export_verified=True,
        export_kind='web_render', registration_deferred=True, source_diversity=qa['metrics'],
        previous_edit_id=PREVIOUS, review_draft=True)
    def change(state, db):
        state['edits'].append(edit)
        state['sources'].extend(copy.deepcopy(s) for s in plan['sources']
                               if not any(x['id'] == s['id'] for x in state['sources']))
        state.update(edit_id=EDIT, status='draft_review', progress=100, error='',
                     message='거울 닫기·메모 활용·마지막 제품 시연과 썸네일을 보완한 검토본')
        state.setdefault('automation', {}).update(active=False)
        parent = state.pop('run_id', None)
        run = init_run(state)
        if parent: run['parent_id'] = parent
        used = {b['selected_shot_id'] for b in plan['beats']}
        ids = {s['source_id'] for s in plan['shots'] if s['id'] in used}
        sources = [copy.deepcopy(s) for s in plan['sources'] if s['id'] in ids]
        run['inputs']['source_ids'] = [s['id'] for s in sources]
        snapshot(state); run['artifacts']['sources'] = sources
        run.update(status='review', quality_draft=True)
        state['quality_revision_path'] = str((OLD / CODE / 'writing/quality-v5.json').resolve())
        studio.store.event(db, WORK, 'mirror_action_revision', {'edit_id': EDIT, 'previous_edit_id': PREVIOUS})
    saved = studio.store.change(WORK, change)
    assert all(next(r for r in saved['runs'] if r['id'] == p['id']) == p for p in current['runs'])
    assert saved['script_id'] == current['script_id'] and saved['voice_id'] == current['voice_id']
    save(final / 'attachment.json', {'task_id': WORK, 'edit_id': EDIT, 'run_id': saved['run_id'],
        'prior_runs_unchanged': True, 'script_and_voice_ids_preserved': True})
    print('Mirror revision attached; prior runs retained.', flush=True)


def share():
    from tools import share_daily_rework as public
    writing = ROOT / CODE / 'writing'
    writing.mkdir(parents=True, exist_ok=True)
    source = OLD / CODE / 'writing/quality-v5.json'
    target = writing / source.name
    if target.exists():
        assert sha256_file(target) == sha256_file(source), 'Existing public writing version preserved'
    else:
        shutil.copy2(source, target)
    public.ROOT = ROOT
    public.TITLES[CODE] = '슬라이딩 거울 · 닫기·메모·제품 시연 보완'
    public.main(codes=(CODE,), port=8814, receipt_name=EDIT+'-share.json',
                writing_revisions={CODE:'quality-v5.json'}, review_codes=(CODE,))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['clips','prepare','render','attach','share'])
    parser.add_argument('--version', type=int, choices=(4,5), default=4)
    args = parser.parse_args()
    ROOT = Path(f'data/mirror-actions-quality-20261011-v{args.version}')
    EDIT = ROOT.name
    configure()
    if args.phase == 'render':
        if (build.root(CODE) / 'render-result.json').exists():
            raise RuntimeError('Existing render preserved')
        build.render(CODE)
    else: globals()[args.phase]()
