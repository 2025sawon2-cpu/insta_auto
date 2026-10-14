"""Recheck existing downloads and densely sample previously unused mirror actions."""
import json
import os
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw
from hotpost.source_finder import probe_video
from hotpost.source_quality import sha256_file
from tools.rework_tiktok_batch import save

DAILY = Path('data/daily-rework-20261011/DeTaESASnr_')
ROOT = Path('data/mirror-actions-quality-20261011-v4/DeTaESASnr_/final')


def main():
    bins = next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/Gyan.FFmpeg*/ffmpeg*/bin'))
    os.environ['PATH'] = str(bins) + os.pathsep + os.environ['PATH']
    ROOT.mkdir(parents=True, exist_ok=True)
    rows = json.loads((DAILY / 'discovery.json').read_text('utf-8'))['candidates']
    downloaded = [r for r in rows if r.get('path')]
    verified = []
    for row in downloaded:
        raw = Path(row['path'])
        result = subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(raw), '-f', 'null', '-'],
                                capture_output=True, timeout=90)
        assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')
        verified.append({'url': row['url'], 'path': str(raw), 'source_sha256': sha256_file(raw),
                         'metadata': probe_video(raw), 'whole_decode_passed': True})
    save(ROOT / 'raw-download-verification.json', {'new_downloads': 0, 'existing_downloads_verified': verified})
    definitions = [('board-direction', '7683128298301410578', 2.7, 6.3),
                   ('open-cta', '7683128298301410578', 17.0, 19.8),
                   ('memo-key', '7694945682506960149', 12.8, 15.4)]
    for name, vid, start, end in definitions:
        folder = ROOT / ('raw-' + name)
        folder.mkdir(exist_ok=True)
        row = next(r for r in verified if r['url'].endswith('/' + vid))
        raw = Path(row['path'])
        sheet = Image.new('RGB', (960, 1808), '#222')
        draw = ImageDraw.Draw(sheet)
        frames = []
        for index in range(16):
            second = start + (end-start) * index / 15
            frame = folder / f'{index:02}.jpg'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(second), '-i', str(raw),
                            '-frames:v', '1', '-vf', 'scale=240:426', str(frame)],
                           check=True, capture_output=True, timeout=30)
            with Image.open(frame) as im:
                sheet.paste(im, (index % 4 * 240, index // 4 * 452 + 24))
            draw.text((index % 4 * 240 + 3, index // 4 * 452 + 3), f'{second:.3f}s', fill='white')
            frames.append({'path': str(frame.resolve()), 'timestamp': second, 'sha256': sha256_file(frame)})
        sheet.save(folder / 'contact.jpg', quality=95)
        save(folder / 'sampling.json', {**row, 'frames': frames, 'actual_visual_review_pending': True})
    print('Six existing downloads decoded; three dense action sheets await actual review.', flush=True)


def approve():
    sources = json.loads((ROOT / 'proposed-new-sources.json').read_text('utf-8'))
    save(ROOT / 'new-clips-reviewed.json', {
        'actual_visual_review': True, 'actual_derivative_frames_read': 12,
        'actual_dense_raw_frames_read': 48, 'reused_decorate_frames_read': 3,
        'proposed_used_cta_cover_read': True,
        'reviewed_source_sha256': {s['id']:s['sha256'] for s in sources},
        'mask_revision': 'v3',
        'first_trials_preserved': True,
        'first_trial_findings': [
            '65px memo blur crop caused an FFmpeg chroma blur-radius failure; reduced radius to 12.',
            'v2 closing/closed-board caption tops and memo left edge remained visible; v3 extends the caption regions.',
            'The initial closed-board interval included the next opening; shortened it to 6.08–7.18.',
            'Decorate at local 0.11 still has an open reflection; use local 0.5 onward for the closed-board context.',
        ],
        'key_type_verified': False,
        'memo_keyring_context_usable': True,
        'limitations': ['Creator credit and advertising disclosure remain visible.',
                       'Promotional subtitle blur patches remain.',
                       'Several downloaded files contain the same source footage; do not count them as independent shoots.'],
    })
    previous = json.loads((DAILY / 'writing/quality-v3.json').read_text('utf-8'))
    v4 = json.loads((DAILY / 'writing/quality-v4.json').read_text('utf-8'))
    v5_path = DAILY / 'writing/quality-v5.json'
    v5 = json.loads(v5_path.read_text('utf-8'))
    assert previous['scripts'][0]['text'] == v5['scripts'][0]['text']
    assert all(s['text'] == next(t for t in v4['scripts'] if t['number']==s['number'])['text'] for s in v5['scripts'])
    assert all(s['bias'] == next(t for t in v4['scripts'] if t['number']==s['number'])['bias'] for s in v5['scripts'])
    v5['human_review_pending'] = False
    for script in v5['scripts']:
        script.update(human_review_pending=False, experience_status='staged_life_situation_not_verified_personal_experience')
    save(v5_path, v5)
    save(DAILY / 'writing/quality-v5-editorial-review.json', {
        'actual_three_scripts_read': True, 'actual_three_thumbnail_pairs_read': True,
        'selected_variant': 1, 'selected_body_unchanged': True,
        'a_mechanism': '자기 경험에 대한 처리와 기억 원리를 외출 상황에 적용한 집필 해석; 실제 시청자 기억 효과는 미측정.',
        'b_mechanism': '처음 낯선 은색 외관을 매일 접하면서 선호가 변하는 설정. 효용 학습과 분리.',
        'c_surface_changes_relative_to_original': ['현관→작업실 입구', '일반 외출→회의 참석', '일반 메모→동료 회의 장소 전달'],
        'literal_reference_sentence_copy_found': False,
        'a_b_reference_flow_preserved': False,
        'c_reference_flow_preserved': True,
        'c_ordinary_function_wording_overlap': True,
        'copyright_legal_guarantee': False,
        'hook_response_measured': False, 'render_visual_review_pending': True,
        'writer_mechanism_metadata_changed_despite_preservation_instruction': True,
        'actual_v5_mechanism_metadata_read': True,
        'mechanism_metadata_meaning_consistent_with_unchanged_text': True,
        'primary_theory_sources': [
            'https://cdn.isr.umich.edu/pubFiles/historicPublications/Theattitudinaleffects_2360_.PDF',
            'https://peda.net/p/Markus%20Lajunen/pmp3/internal-assessment/fofia/sateopi%3Afile/download/1bff3ea36308a106de9e04b54e83bd1de3e24805/Rogers1977.pdf',
        ],
    })
    print('Actual three-script, thumbnail and derivative review saved.', flush=True)


if __name__ == '__main__':
    import sys
    approve() if sys.argv[1:] == ['approve'] else main()
