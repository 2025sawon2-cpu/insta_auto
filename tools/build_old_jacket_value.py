"""Version the older jacket's reviewed B script, personal voice and portrait edit."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time
from PIL import Image, ImageDraw

from hotpost.config import load_settings
from hotpost.source_quality import sha256_file
from hotpost.source_finder import probe_video
from hotpost.studio import Studio
from hotpost.studio_workflow import init_run, snapshot
from hotpost.voicebench_adapter import VoiceBenchAdapter
from tools import build_tiktok_rework as build
from tools import revise_cart_youtube_actions as environment
from tools.rework_tiktok_batch import save

CODE = 'DeJ7hD6zsnR'
ROOT = Path('data/old-jacket-value-20261011-v3')
OLD = Path('data/tiktok-quality-20261011-v2')
QUALITY = ROOT / CODE / 'writing/quality-v2.json'
EDIT = 'old-jacket-value-20261011-v3'
WORK = 'work-7de866f1dc7d4e71'


def read(path):
    return json.loads(Path(path).read_text('utf-8'))


def configure():
    environment.ROOT = ROOT
    environment.EDIT = EDIT
    environment.configure()


def prepare():
    quality = read(QUALITY)
    assert not quality['human_review_pending']
    selected = next(s for s in quality['scripts'] if s['number'] == 2)
    digest = hashlib.sha256(selected['text'].encode()).hexdigest()
    final = build.root(CODE)
    final.mkdir(parents=True, exist_ok=True)
    script = {**selected, 'id': 'old-jacket-value-script-' + digest[:12],
              'sha256': digest, 'status': 'completed', 'created': time.time(),
              'writing_contract': quality['writing_contract']}
    if (final / 'script.json').exists():
        assert read(final / 'script.json')['sha256'] == digest
    else:
        save(final / 'script.json', script)
        (final / 'words.txt').write_text(script['text'], 'utf-8')
    sources = read(OLD / CODE / 'final/approved-sources.json')
    extra = read(Path('data/daily-rework-20261011/DeSvpmAsWgZ/final/approved-sources.json'))
    sources.append(next(s for s in extra if s['name'] == 'kid-front'))
    if (final / 'additional-reviewed-sources.json').exists():
        sources.extend(read(final / 'additional-reviewed-sources.json'))
    for source in sources:
        assert sha256_file(Path(source['path'])) == source['sha256']
        for frame in source['evidence_frames']:
            assert sha256_file(Path(frame['path'])) == frame['sha256']
    save(final / 'proposed-sources.json', sources)
    save(final / 'clips-reviewed.json', {
        'scope': 'Byte-identical previously inspected portrait clips; new timeline requires review',
        'review_paths': [str(OLD / CODE / 'final/clips-reviewed.json'),
                        'data/daily-rework-20261011/DeSvpmAsWgZ/final/clips-reviewed.json'],
        'source_ids': [s['id'] for s in sources]})
    if not (final / 'baseline-state.json').exists():
        save(final / 'baseline-state.json', Studio(load_settings(), workers=False).store.get(WORK))
    if (final / 'voice.json').exists():
        assert read(final / 'voice.json')['script_sha256'] == digest
        return
    submission = final / 'voice-submission.json'
    request = read(submission).get('request_id') if submission.exists() else None
    result = VoiceBenchAdapter(load_settings()).synthesize(
        script['text'], final / 'narration.wav',
        progress=lambda m, n: print(CODE, m, n, flush=True), request_id=request,
        on_submitted=lambda i: save(submission, {'request_id': i, 'script_sha256': digest}),
        generation_key=EDIT + '-' + digest, require_personal_clone=True)
    save(final / 'voice.json', {**result, 'id': 'old-jacket-value-voice-' + digest[:12],
        'path': str(final / 'narration.wav'), 'sha256': sha256_file(final / 'narration.wav'),
        'duration': result['audio']['duration'], 'script_id': script['id'],
        'script_sha256': digest, 'created': time.time(), 'status': 'completed'})
    print('New personal voice saved', result['audio']['duration'], flush=True)


def clips():
    """Previously received store footage: bounded white fit and alternative navy."""
    final = build.root(CODE)
    raw = (OLD / CODE / 'videos/7173259157208911106.mp4').resolve()
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(raw), '-f', 'null', '-'],
                   check=True, capture_output=True)
    definitions = [('store-white', 5.5, 7.8, '매장의 흰 몸판·검은 어깨 패딩 앞뒤 착용'),
                   ('store-navy-front', 7.95, 9.65, '다른 후보를 보여주는 남색 패딩 정면·측면 착용'),
                   ('store-navy-back', 9.65, 10.8, '다른 후보를 보여주는 남색 패딩 뒷면 착용')]
    rows = []
    sheet = Image.new('RGB', (720, 1035), '#222')
    draw = ImageDraw.Draw(sheet)
    for j, (name, start, end, observation) in enumerate(definitions):
        target = final / 'clips' / (name + '-v2.mp4')
        target.parent.mkdir(exist_ok=True)
        if target.exists():
            raise RuntimeError('Existing derivative retained; do not overwrite')
        vf = ('scale=720:1280,setsar=1,fps=30,split[base][label];'
              '[label]crop=230:90:40:200,boxblur=12:2[blur];[base][blur]overlay=40:200')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(start), '-t', str(end-start),
            '-i', str(raw), '-an', '-vf', vf, '-c:v', 'libx264', '-preset', 'veryfast',
            '-crf', '18', str(target)], check=True, capture_output=True)
        meta = probe_video(target)
        frames = []
        for k, fraction in enumerate((.02, .35, .65, .98)):
            timestamp = (meta['duration'] - .04) * fraction
            frame = target.with_name(name + f'-v2-{k}.jpg')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(timestamp), '-i', str(target),
                            '-frames:v', '1', str(frame)], check=True, capture_output=True)
            frames.append({'path': str(frame), 'timestamp': timestamp, 'sha256': sha256_file(frame)})
            with Image.open(frame) as im:
                im.thumbnail((180, 320)); sheet.paste(im, (k*180, j*345+25))
            draw.text((k*180+2, j*345+2), f'{name} {timestamp:.2f}s', fill='white')
        rows.append({'id': EDIT + '-' + name, 'name': name, 'path': str(target),
            'sha256': sha256_file(target), 'video_meta': meta, 'original_path': str(raw),
            'original_sha256': sha256_file(raw), 'original_interval': {'start': start, 'end': end},
            'url': 'https://www.tiktok.com/@roop_tokyo/video/7173259157208911106',
            'provider': 'tiktok', 'rights': 'unknown-check-before-reuse',
            'source_role': 'context' if 'navy' in name else 'core',
            'proposed_observation': observation, 'evidence_frames': frames,
            'pending_visual_review': True, 'editing_eligible': False,
            'preprocessed_blur_regions_px': [[40, 200, 230, 90]]})
    sheet.save(final / 'additional-clip-review-v2.jpg', quality=95)
    save(final / 'additional-proposed-sources-v2.json', rows)
    print('Three bounded derivatives await actual review', flush=True)


def select():
    final = build.root(CODE)
    plan = read(final / 'prepared-plan.json')
    beats = plan['beats']
    shots = {s['id'][5:]: s for s in plan['shots']}
    names = list(shots)
    lengths = [math.ceil((b['end'] - b['start']) * 1000 - 1e-6) for b in beats]
    capacities = tuple(math.floor((shots[n]['end'] - shots[n]['start']) * 1000) for n in names)
    groups = read(final / 'semantic-choices.json')
    assert len(groups) == len(beats)
    assert all(row['text'] == beat['text'] for row, beat in zip(groups, beats))
    # Whole caption cues, bounded source ranges, no looping to fill narration.
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    pairs = [(i, n) for i, row in enumerate(groups) for n in row['allowed']]
    matrix = np.zeros((len(beats) + len(names), len(pairs)))
    for column, (i, name) in enumerate(pairs):
        matrix[i, column] = 1
        matrix[len(beats) + names.index(name), column] = lengths[i]
    constraints = LinearConstraint(matrix, np.r_[np.ones(len(beats)), np.zeros(len(names))],
                                   np.r_[np.ones(len(beats)), capacities])
    costs = np.array([groups[i]['allowed'].index(n) * .01 + names.index(n) * .00001
                      for i, n in pairs])
    solution = milp(costs, integrality=np.ones(len(pairs)), bounds=Bounds(0, 1),
                    constraints=constraints, options={'time_limit': 20})
    if solution.x is None:
        raise ValueError('Reviewed scenes cannot fit whole cues without repetition; obtain more scenes')
    assignment = {i: n for (i, n), x in zip(pairs, solution.x) if x > .5}
    assert len(assignment) == len(beats)
    assert all(sum(lengths[i] for i, n in assignment.items() if n == name) <= cap
               for name, cap in zip(names, capacities))
    for i, beat in enumerate(beats):
        shot = shots[assignment[i]]
        beat.update(selected_shot_id=shot['id'], emphasis=0, needs_review=False,
            options=[{'shot_id': shot['id'], 'relation': groups[i]['relation'],
                'reason': shot['observation'] + ' · ' + groups[i]['reason'], 'reviewed': True}])
    plan['footage_selection_policy'] = 'diverse-sequential-v1'
    plan['cover_spec']['source'] = read(OLD / CODE / 'final/timeline.json')['cover_spec']['source']
    plan['cover_spec']['copy_review'] = {'reviewer': 'codex_session_editorial_review',
        'source_review': 'Previously inspected white body and black shoulder portrait highlight',
        'hook_review': 'Specific chosen product and ownership conflict; no verified current sale claim'}
    save(final / 'prepared-plan.json', plan)
    save(final / 'selection-description.json', {'assignment': sorted(assignment.items()),
        'no_source_quantity_in_writing': True, 'price_and_personal_story_are_context': True})
    build.boundary(CODE, 'cover-candidates', plan=plan)
    print('Whole cues assigned', sorted(assignment.items()), flush=True)


def attach():
    final = build.root(CODE)
    qa = read(final / 'verification.json')
    assert not qa['visual_review_pending']
    result = read(final / 'render-result.json')
    script, voice = read(final / 'script.json'), read(final / 'voice.json')
    studio = Studio(load_settings(), workers=False)
    current = studio.store.get(WORK)
    if any(e['id'] == EDIT for e in current['edits']):
        print('Existing version retained; no duplicate run', flush=True)
        return
    assert current['edit_id'] == read(final / 'baseline-state.json')['edit_id']
    previous = current['edit_id']
    edit = {k: v for k, v in result.items() if k != 'status'}
    edit.update(id=EDIT, script_id=script['id'], voice_id=voice['id'], created=time.time(),
        status='completed', export_path=result['preview_path'], export_verified=True,
        export_kind='web_render', registration_deferred=True, source_diversity=qa['metrics'],
        previous_edit_id=previous, revision_scope='new ownership B script and personal voice')
    plan = read(result['plan_path'])
    def change(state, db):
        assert state['edit_id'] == previous
        for name, item in [('scripts', script), ('voices', voice), ('edits', edit)]:
            if not any(x['id'] == item['id'] for x in state[name]):
                state[name].append(item)
        state.update(script_id=script['id'], voice_id=voice['id'], edit_id=EDIT,
            status='completed', error='', progress=100, message='소유효과 2안 새 대본·개인 음성 검토본')
        state.setdefault('automation', {}).update(active=False, stage='completed')
        parent = state.pop('run_id', None)
        run = init_run(state)
        if parent:
            run['parent_id'] = parent
        used = {b['selected_shot_id'] for b in plan['beats']}
        ids = {s['source_id'] for s in plan['shots'] if s['id'] in used}
        sources = [copy.deepcopy(s) for s in plan['sources'] if s['id'] in ids]
        run['inputs']['source_ids'] = [s['id'] for s in sources]
        snapshot(state)
        run['artifacts']['sources'] = sources
        run.update(status='completed', completed=time.time(), revision_origin=EDIT)
        state['latest_completed_run_id'] = run['id']
        state['quality_revision_path'] = str(QUALITY.resolve())
        studio.store.event(db, state['id'], 'old_jacket_value_revision_added',
                           {'edit_id': EDIT, 'previous_edit_id': previous})
    saved = studio.store.change(WORK, change)
    assert all(next(r for r in saved['runs'] if r['id'] == p['id']) == p for p in current['runs'])
    assert all(x in saved['scripts'] for x in current['scripts'])
    assert all(x in saved['voices'] for x in current['voices'])
    save(final / 'attachment-verification.json', {'edit_id': EDIT, 'run_id': saved['run_id'],
        'prior_runs_unchanged': True, 'old_scripts_retained': True, 'old_voices_retained': True})
    print('Attached new version; prior runs retained', saved['run_id'], flush=True)


def share():
    from tools import share_daily_rework as public
    public.ROOT = ROOT
    public.TITLES[CODE] = '흰검 노스페이스 패딩 · 소유효과 2안'
    public.main(codes=(CODE,), port=8812, receipt_name='old-jacket-value-20261011-v3-share.json',
                writing_revisions={CODE: 'quality-v2.json'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['prepare', 'clips', 'analyze', 'select', 'render', 'attach', 'share'])
    args = parser.parse_args()
    configure()
    if args.phase in ('analyze', 'select', 'render') and (build.root(CODE) / 'render-result.json').exists():
        raise RuntimeError('Completed render version retained; use a new version directory for changes')
    if args.phase in ('analyze', 'render'):
        getattr(build, args.phase)(CODE)
    else:
        globals()[args.phase]()
