"""Record actual current render review and preserve the complete goal scope."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from hotpost.source_quality import sha256_file
from tools.rework_tiktok_batch import save

ROOT = Path('data/mirror-actions-quality-20261011-v5/DeTaESASnr_/final')


def read(path):
    return json.loads(Path(path).read_text('utf-8'))


def review():
    old = read('data/daily-rework-20261011/DeTaESASnr_/final/timeline.json')
    plan = read(ROOT / 'timeline.json')
    assert plan['script_text'] == old['script_text']
    assert plan['voice'] == old['voice']
    assert sha256_file(Path(plan['voice']['path'])) == plan['voice']['sha256']
    changed = [i+1 for i,(a,b) in enumerate(zip(old['beats'],plan['beats'])) if a != b]
    assert changed == [6,7,8,9,10,11,13,17,18,19,20], changed
    qa = read(ROOT / 'verification.json')
    qa.update(actual_visual_review=True, visual_review_pending=False, audio_listened=False,
              reviewed_video_sha256=sha256_file(ROOT / 'preview.mp4'),
              body_script_and_voice_preserved=True)
    qa['visual_review'] = {
        'cover_read': True, 'sample_frames_read': 12,
        'opening_and_closing_corrected': True,
        'assembly_removed_at_collection_line_and_cta': True,
        'memo_and_metal_keyring_context_read': True, 'individual_key_type_verified': False,
        'changed_beats': changed,
        'earlier_wrong_action_labels_corrected_in_current_plan': True,
        'source_files_not_independent_shoot_count': True,
        'largest_file_share_reduced': False,
        'limits': ['Promotional-caption blur patches and original creator credits remain.',
                  'Some source files reuse the same room footage.',
                  'Fictional exit situation is not a verified personal purchase/use experience.',
                  'No measured comment/click-rate guarantee.'],
    }
    save(ROOT / 'verification.json', qa)
    editorial_path = Path('data/daily-rework-20261011/DeTaESASnr_/writing/quality-v5-editorial-review.json')
    editorial = read(editorial_path)
    editorial.update(render_visual_review_pending=False, selected_render_cover_read=True,
                     selected_render_samples_read=12, selected_a_body_and_voice_preserved=True)
    save(editorial_path, editorial)
    origin = read('data/mirror-actions-quality-20261011-v4/DeTaESASnr_/final/reference-sampling.json')
    origin.update(actual_review_pending=False, actual_four_frames_read=True,
                  same_floor_assembly_scene_visually_present_in_7616753780129893650=True,
                  pixel_exact_match_or_original_uploader_proven=False,
                  note='Same curtain/shelf/floor/panel setup is visible; this assembly scene was intentionally removed from final product-use cues.')
    save(ROOT / 'reference-scene-review.json', origin)
    print('Current mirror cover and twelve actual render samples reviewed; earlier version preserved.')


def progress():
    prior = Path('data/source-quality-progress-20261011-folder-transfer-v7.json')
    state = read(prior)
    state.update(recorded_at=datetime.now(timezone(timedelta(hours=9))).isoformat(),
                 previous_progress_receipt=str(prior), goal_turn_classification='progress',
                 full_goal_complete=False, current_turn_tiktok_new_download_count=0)
    state['mirror_actions_v5'] = {
        'qa': read(ROOT / 'verification.json'), 'attachment': read(ROOT / 'attachment.json'),
        'share': read('data/mirror-actions-quality-20261011-v5-share.json'),
        'public_file': read(ROOT / 'public-file-verification.json'),
        'browser': read(ROOT / 'browser-verification.json'),
        'six_existing_downloads': read('data/mirror-actions-quality-20261011-v4/DeTaESASnr_/final/raw-download-verification.json'),
        'editorial': read('data/daily-rework-20261011/DeTaESASnr_/writing/quality-v5-editorial-review.json'),
        'new_tts_requests': 0, 'original_and_v4_edits_preserved': True,
        'undownloaded_candidates': {'count': 3, 'download_attempted_this_turn': False,
                                   'status': 'Previously unselected; do not count as failed downloads.'},
        'new_downloads': 0,
        'validation': {'comparison_share_tests_passed': 6,
                       'changed_helpers_py_compile_passed': True,
                       'public_session_id': 17447},
    }
    state['remaining_full_scope'] = [
        'Folder direct phone-photo copying/back attachment and earlier assembly context remain unresolved.',
        'A7 core-action coverage and thumbnail hook remain under review.',
        'Cart 360-source enlargement/promotional-caption blur can be improved.',
        'Fish material identity remains separate from mirror and unresolved.',
        'Mirror current A/three-script review/action render completed; visual room reuse and source credits remain quality limits.',
        'Actual audio input unsupported; preserve as a limitation, not a new completion gate.',
    ]
    state['completion_audit'].update(mirror_three_variant_editorial_review=True,
        mirror_current_render_full_playback=True, mirror_action_alignment_reworked=True,
        A7_remaining=True, full_objective_proven=False)
    save(Path('data/source-quality-progress-20261011-mirror-actions-v5.json'), state)
    print('Full scope retained; mirror production and public-playback progress saved.')


if __name__ == '__main__':
    import sys
    progress() if sys.argv[1:] == ['progress'] else review()
