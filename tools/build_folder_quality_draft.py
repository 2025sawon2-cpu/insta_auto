"""A versioned folder quality draft; unresolved phone-use coverage stays explicit."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from PIL import Image, ImageDraw
from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json as save
from hotpost.source_finder import probe_video
from hotpost.source_quality import sha256_file
from hotpost.voicebench_adapter import VoiceBenchAdapter
from hotpost.source_presentation import POLICY, review_scope
from tools import build_tiktok_rework as build

CODE = 'DeSoiZvyyqj'
DAILY = (Path('data/daily-rework-20261011') / CODE).resolve()
ROOT = (Path('data/folder-quality-20261011-v6') / CODE / 'final').resolve()
DEFINITIONS = [
    ('gold-display', '7618811833352244494', .7, 3.4, '실물 노란 폴더형 케이스를 들어 앞면과 옆면을 보여줌', 'context'),
    ('blue-assembly', '7595407193336253710', 7.5, 11.5, '파란 폴더 케이스의 SSD와 내부 회로·나사 고정을 보여줌', 'core'),
    ('blue-connect', '7595407193336253710', 11.5, 14.55, '파란 폴더 케이스 덮개를 닫고 USB-C 케이블을 연결함', 'core'),
    ('gold-device', '7594733079185476880', 4.5, 7.0, '부속 케이블·도구와 크기가 다른 폴더 케이스들을 보여줌', 'context'),
    ('gold-install', '7594733079185476880', 10.8, 16.0, '노란 폴더 케이스에 SSD를 넣고 내부 부품을 보여줌', 'core'),
    ('gold-connect', '7594733079185476880', 16.2, 23.6, '노란 폴더에 케이블을 꽂고 연결한 컴퓨터의 테스트 화면을 보여줌', 'core'),
    ('gold-strap', '7594733079185476880', 24.1, 28.05, '폴더 케이스에 스트랩을 끼우고 가방 고리에 걸어 휴대함', 'core'),
    ('gold-hand', '7618811833352244494', 6.1, 9.0, '노란 폴더 케이스를 손에 들고 앞뒤로 돌려 보여줌', 'context'),
    ('gold-desk', '7618811833352244494', 13.6, 16.03, '카메라와 책 옆에 놓인 노란 실물 폴더 케이스', 'context'),
]


def setup():
    ROOT.mkdir(parents=True, exist_ok=True)
    bins = next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    os.environ['PATH'] = str(bins) + os.pathsep + os.environ['PATH']
    build.ROOT = ROOT.parent.parent
    original_boundary = build.boundary
    build.boundary = lambda c, action, **kw: original_boundary(
        c, action, quality_revision='folder-source-scope-v6', **kw)


def voice():
    quality = json.loads((DAILY / 'writing/quality-v5.json').read_text('utf-8'))
    selected = next(s for s in quality['scripts'] if s['number'] == 2)
    assert not selected['human_review_pending']
    digest = hashlib.sha256(selected['text'].encode()).hexdigest()
    script = dict(selected, id='folder-v6-script-' + digest[:12], sha256=digest,
                  writing_contract=quality['writing_contract'], status='completed', created=time.time())
    save(ROOT / 'script.json', script)
    save(ROOT / 'coverage-limitations.json', {
        'status': 'quality_draft', 'completion_claim': False,
        'script_source': str(DAILY / 'writing/quality-v5.json'), 'selected_variant': 2,
        'claims_from_reference_caption': ['사진·영상 별도 보관', '폰 뒤 부착', '휴대'],
        'visual_coverage_unresolved': ['동일 폴더형 제품의 폰 뒤 부착 장면', '사진 파일을 실제 복사하는 화면'],
        'illustration_rule': 'SSD 설치·USB-C 연결·휴대는 해당 동작에만 사용. 포트/폴더 외형은 폰 부착 대사의 보조 화면이며 부착의 직접 증거가 아님.',
        'reference_dense_review': str(DAILY / 'reference-action-density/sampling.json'),
        'mixed_products_excluded': ['ORICO 회색 케이스', 'DKQ03 카드리더', '무관한 자석 고리'],
        'actual_scene_diversity_review_pending': True,
        'audio_listened': False})
    if (ROOT / 'voice.json').exists():
        old = json.loads((ROOT / 'voice.json').read_text('utf-8'))
        assert old['script_sha256'] == digest
        print('Existing matching personal voice retained.', flush=True)
        return
    receipt = ROOT / 'voice-submission.json'
    request = json.loads(receipt.read_text('utf-8')).get('request_id') if receipt.exists() else None
    result = VoiceBenchAdapter(load_settings()).synthesize(
        script['text'], ROOT / 'narration.wav', require_personal_clone=True,
        request_id=request, generation_key='folder-v6-' + digest,
        on_submitted=lambda rid: save(receipt, {'request_id': rid, 'script_sha256': digest}),
        progress=lambda message, n: print(message, n, flush=True))
    save(ROOT / 'voice.json', dict(result, id='folder-v6-voice-' + digest[:12],
        path=str((ROOT / 'narration.wav').resolve()), sha256=sha256_file(ROOT / 'narration.wav'),
        script_id=script['id'], script_sha256=digest, duration=result['audio']['duration'],
        status='completed', created=time.time()))
    print('Personal voice saved', result['audio']['duration'], flush=True)


def clips():
    rows = json.loads((DAILY / 'discovery.json').read_text('utf-8'))['candidates']
    sources = []
    sheet = Image.new('RGB', (720, 345 * len(DEFINITIONS)), '#222')
    draw = ImageDraw.Draw(sheet)
    for j, (name, vid, start, end, observation, role) in enumerate(DEFINITIONS):
        row = next(r for r in rows if r['url'].endswith('/' + vid))
        original = Path(row['path'])
        target = ROOT / 'clips' / (name + '.mp4')
        target.parent.mkdir(exist_ok=True)
        # The English hook above the product is an overlay, not new narration.
        vf = 'scale=720:1280,setsar=1,fps=30'
        masks = []
        if name == 'gold-display':
            vf += ',split[base][txt];[txt]crop=720:180:0:170,boxblur=24:2[blur];[base][blur]overlay=0:170'
            masks.append([0, 170, 720, 180])
        if vid.startswith('761881') or vid.startswith('759540'):
            y = 930 if vid.startswith('761881') else 870
            vf += f',split[base2][mark];[mark]crop=240:60:480:{y},boxblur=12:2[blur2];[base2][blur2]overlay=480:{y}'
            masks.append([480, y, 240, 60])
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(start), '-t', str(end-start),
            '-i', str(original), '-an', '-vf', vf, '-c:v', 'libx264', '-preset', 'veryfast',
            '-crf', '18', str(target)], check=True, capture_output=True)
        meta = probe_video(target)
        frames = []
        for i, fraction in enumerate((.05, .35, .65, .95)):
            t = max(0, meta['duration'] - .05) * fraction
            frame = target.with_name(name + f'-{i}.jpg')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(t), '-i', str(target),
                '-frames:v', '1', str(frame)], check=True, capture_output=True)
            frames.append({'path': str(frame.resolve()), 'timestamp': t, 'sha256': sha256_file(frame)})
            with Image.open(frame) as im:
                im.thumbnail((180, 320)); sheet.paste(im, (i*180, j*345+25))
            draw.text((i*180+3, j*345+3), f'{name} {t:.2f}', fill='white')
        sources.append({'id': 'folder-v6-' + name, 'name': name, 'path': str(target.resolve()),
            'sha256': sha256_file(target), 'video_meta': meta, 'url': row['url'],
            'provider': 'tiktok', 'rights': row.get('rights', 'unknown-check-before-reuse'),
            'original_path': str(original.resolve()), 'original_sha256': sha256_file(original),
            'original_interval': {'start': start, 'end': end}, 'source_role': role,
            'proposed_observation': observation, 'evidence_frames': frames,
            'pending_visual_review': True, 'editing_eligible': False,
            'exact_reference_sku_confirmed': False, 'preprocessed_blur_regions_px': masks})
    sheet.save(ROOT / 'clip-review.jpg', quality=94)
    save(ROOT / 'proposed-sources.json', sources)
    print('Nine bounded clips await actual visual review.', flush=True)


def prepare():
    assert (ROOT / 'clips-reviewed.json').exists(), 'Actual revised clip review required.'
    sources = json.loads((ROOT / 'proposed-sources.json').read_text('utf-8'))
    reviewed = json.loads((ROOT / 'clips-reviewed.json').read_text('utf-8'))
    assert reviewed['reviewed_source_sha256'] == {s['id']: s['sha256'] for s in sources}
    for source in sources:
        limits = ['원본과 정확한 SKU 일치 미확정. 폴더형 저장 케이스의 해당 관찰 동작만 사용.',
                  '자석 고정·폰 부착·실제 사진 파일 복사의 직접 증거가 아님.',
                  '컴퓨터 속도 테스트는 저장장치 연결 맥락이며 전송 속도·용량 수치를 보증하지 않음.']
        source.update(pending_visual_review=False, editing_eligible=True,
            source_quality='light-overlay', blur_required=False, watermark_masks=[],
            presentation_review_required=False, relevance_review_required=False)
        source['functional_review'] = {'reviewed': True, 'source_sha256': source['sha256'],
            'same_core_function': source['source_role'] == 'core', 'context_usable': True,
            'context_usage_limits': limits, 'observed_actions': [source['proposed_observation']],
            'evidence_frames': [f['path'] for f in source['evidence_frames']],
            'reviewer': 'codex_session_visual_review'}
        source['presentation_review'] = {'policy': POLICY, 'reviewed': True,
            'source_sha256': source['sha256'], 'scope': review_scope(source), 'usable': True,
            'quality_usable': True, 'action_preserved': True,
            'observations': [source['proposed_observation']], 'evidence_frames': source['evidence_frames'],
            'reviewer': 'codex_session_visual_review'}
    save(ROOT / 'approved-sources.json', sources)
    script = json.loads((ROOT / 'script.json').read_text('utf-8'))
    voice = json.loads((ROOT / 'voice.json').read_text('utf-8'))
    assert voice['script_sha256'] == script['sha256']
    plan = build.boundary(CODE, 'analyze', sources=sources, script=script, voice=voice,
                          thumbnail_lines=script['thumbnail_lines'])['plan']
    plan['shots'] = [dict(id='shot-' + s['name'], source_id=s['id'], path=s['path'],
        sha256=s['sha256'], start=0, end=s['video_meta']['duration'],
        frames=[f['path'] for f in s['evidence_frames']], observation=s['proposed_observation'],
        source_role=s['source_role'], context_usage_limits=s['functional_review']['context_usage_limits'],
        evidence_status='actual-decoded-portrait-review') for s in sources]
    plan['cover_font_style'] = {'font_path': str(load_settings().auto_capcut_root / 'auto_capcut/assets/fonts/DoHyeon-Regular.ttf'),
        'font_family': 'Do Hyeon', 'font_title': '도현', 'font_weight': 700,
        'font_resource_id': '', 'font_status': 'available'}
    plan['quality_draft'] = True
    plan['source_coverage_complete'] = False
    plan['visual_alignment_gaps'] = ['폰 뒤 부착·사진 파일 복사 장면은 직접 증거가 미확보. 제품 외형 보조 화면으로 검토.']
    save(ROOT / 'prepared-plan.json', plan)
    print(json.dumps([(i+1, b['text'], round(b['start'], 2), round(b['end'], 2))
                      for i, b in enumerate(plan['beats'])], ensure_ascii=False), flush=True)


def select():
    plan = json.loads((ROOT / 'prepared-plan.json').read_text('utf-8'))
    groups = [(1, 2, 'gold-display'), (3, 4, 'gold-install'), (5, 8, 'blue-assembly'),
              (9, 10, 'gold-desk'), (11, 13, 'blue-connect'), (14, 15, 'gold-device'),
              (16, 17, 'gold-strap'), (18, 19, 'gold-hand'), (20, 20, 'gold-strap')]
    for first, last, name in groups:
        shot = next(s for s in plan['shots'] if s['id'] == 'shot-' + name)
        if name == 'gold-strap': shot['start'] = 1.1
        if name == 'gold-hand': shot['start'] = .55
        for beat in plan['beats'][first-1:last]:
            # These shots illustrate the narrative; a USB connection is not a
            # recorded photo-file copy, nor is a folder close-up a phone mount.
            relation = 'direct' if name == 'gold-strap' else 'context'
            beat.update(options=[{'shot_id': shot['id'], 'relation': relation,
                'reason': shot['observation'], 'reviewed': True}], selected_shot_id=shot['id'],
                emphasis=0, needs_review=False)
        needed = plan['beats'][last-1]['end'] - plan['beats'][first-1]['start']
        assert needed <= shot['end'] - shot['start'] + .001, (name, needed)
    plan['beats'][14]['visual_alignment_gap'] = '폰 부착 시연 미확보: 폴더 외형 보조 장면'
    save(ROOT / 'selection-input.json', plan)
    settings = load_settings()
    program = "from pathlib import Path;import json,sys;from auto_capcut.core.studio_timeline import select_shots;p=select_shots(json.loads(Path(sys.argv[1]).read_text('utf-8')));Path(sys.argv[2]).write_text(json.dumps(p,ensure_ascii=False,indent=2),'utf-8')"
    subprocess.run([str(settings.auto_capcut_python), '-X', 'utf8', '-c', program,
                   str(ROOT / 'selection-input.json'), str(ROOT / 'prepared-plan.json')],
                   cwd=settings.auto_capcut_root, check=True)
    plan = json.loads((ROOT / 'prepared-plan.json').read_text('utf-8'))
    from tools.build_source_rework import metrics
    audit = metrics(plan)
    assert audit['replayed_seconds'] < .08, audit
    save(ROOT / 'selection-audit.json', audit)
    result = build.boundary(CODE, 'cover-candidates', plan=plan)
    items = result['candidates']
    sheet = Image.new('RGB', (810, 505 * ((len(items)+2)//3)), '#222')
    draw = ImageDraw.Draw(sheet)
    for i, candidate in enumerate(items):
        with Image.open(candidate['frame_path']) as im:
            im.thumbnail((270, 480)); sheet.paste(im, (i%3*270, i//3*505+25))
        draw.text((i%3*270+3, i//3*505+3), f"{candidate['shot_id']} {candidate['timestamp']:.2f}", fill='white')
    sheet.save(ROOT / 'cover-candidates.jpg', quality=94)
    print(json.dumps(audit, ensure_ascii=False), flush=True)


def render():
    build.render(CODE)
    verification = json.loads((ROOT / 'verification.json').read_text('utf-8'))
    verification.update(quality_draft=True, source_coverage_complete=False,
                        unresolved_source_beats=[15], audio_listened=False)
    save(ROOT / 'verification.json', verification)


def attach():
    from hotpost.studio import Studio
    from hotpost.studio_workflow import init_run, snapshot
    qa = json.loads((ROOT / 'verification.json').read_text('utf-8'))
    assert not qa['visual_review_pending']
    result = json.loads((ROOT / 'render-result.json').read_text('utf-8'))
    plan = json.loads((ROOT / 'timeline.json').read_text('utf-8'))
    script = json.loads((ROOT / 'script.json').read_text('utf-8'))
    voice = json.loads((ROOT / 'voice.json').read_text('utf-8'))
    quality = json.loads((DAILY / 'writing/quality-v5.json').read_text('utf-8'))
    recovery = json.loads((DAILY / 'transcript-recovery.json').read_text('utf-8'))
    reference = Path(recovery['directory']) / 'reference.mp4'
    assert sha256_file(reference) == recovery['video_sha256']
    studio = Studio(load_settings(), workers=False)
    initial = {'reference_video': str(reference), 'creation_mode': 'reference_video'}
    state, created = studio.store.create(CODE, '실물 폴더 저장 케이스 · 품질 검토본',
                                        initial=initial, prepare=False)
    edit_id = 'folder-quality-20261011-v6'
    if any(e['id'] == edit_id for e in state['edits']):
        print('Existing attached review draft retained.', flush=True)
        return
    save(ROOT / 'state-before-attachment.json', state)
    edit = {k: v for k, v in result.items() if k != 'status'}
    edit.update(id=edit_id, script_id=script['id'], voice_id=voice['id'], status='completed',
                created=time.time(), export_path=result['preview_path'], export_verified=True,
                exported_at=time.time(), export_kind='web_render', registration_deferred=True,
                source_diversity=qa['metrics'], review_draft=True, source_coverage_complete=False,
                source_limit='폰 부착·실제 파일 복사·사진 이야기 장면 보완 필요')
    def change(s, db):
        for key, obj in [('scripts', script), ('voices', voice), ('edits', edit)]:
            assert not any(x['id'] == obj['id'] for x in s[key])
            s[key].append(copy.deepcopy(obj))
        s['sources'].extend(copy.deepcopy(x) for x in plan['sources']
                            if not any(y['id'] == x['id'] for y in s['sources']))
        s.update(script_id=script['id'], voice_id=voice['id'], edit_id=edit_id,
                 status='draft_review', progress=100, error='',
                 message='세로 3개 파일·8개 구간 검토본. 폰 부착·사진 이야기 화면 보완 필요.')
        s.setdefault('automation', {}).update(active=False, stage='source_wait',
                                              source_coverage_complete=False)
        s['script_variants'] = copy.deepcopy(quality)
        s.pop('run_id', None)
        run = init_run(s)
        used = {b['selected_shot_id'] for b in plan['beats']}
        ids = {shot['source_id'] for shot in plan['shots'] if shot['id'] in used}
        run['inputs']['source_ids'] = sorted(ids)
        snapshot(s)
        run.update(status='review', quality_draft=True, source_coverage_complete=False)
        studio.store.event(db, s['id'], 'folder_quality_draft', {'edit_id': edit_id,
                            'task_created': created, 'metrics': qa['metrics']})
    saved = studio.store.change(state['id'], change)
    for prior in state.get('runs', []):
        assert next(x for x in saved['runs'] if x['id'] == prior['id']) == prior
    save(ROOT / 'attachment.json', {'task_id': saved['id'], 'run_id': saved['run_id'],
         'edit_id': edit_id, 'old_runs_preserved': True, 'source_coverage_complete': False})
    print('Attached quality draft without queueing production.', saved['id'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['voice', 'clips', 'prepare', 'select', 'render', 'attach'])
    args = parser.parse_args()
    setup()
    globals()[args.phase]()
