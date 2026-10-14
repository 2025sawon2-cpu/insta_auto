"""Record the actual cover/contact-sheet review without claiming unseen actions."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hotpost.source_quality import sha256_file


def read(path):
    return json.loads(path.read_text('utf-8'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf-8')


def main():
    code = 'DeSoiZvyyqj'
    final = Path('data/folder-transfer-quality-20261011-v7') / code / 'final'
    old = Path('data/folder-quality-20261011-v6') / code / 'final'
    current, previous = read(final / 'timeline.json'), read(old / 'timeline.json')
    assert current['script_text'] == previous['script_text']
    assert current['voice'] == previous['voice']
    assert sha256_file(Path(current['voice']['output_path'])) == sha256_file(Path(previous['voice']['output_path']))
    assert len(current['beats']) == len(previous['beats'])
    changed = [index + 1 for index, (a, b) in enumerate(zip(current['beats'], previous['beats'])) if a != b]
    assert changed == [11, 12, 13], changed
    qa = read(final / 'verification.json')
    qa.update(actual_visual_review=True, visual_review_pending=False,
              audio_listened=False, final_quality_passed=False,
              reviewed_video_sha256=sha256_file(final / 'preview.mp4'),
              source_coverage_complete=False)
    qa['visual_review'] = {
        'cover_read': True, 'sample_frames_read': 12,
        'storage_cues_revised': True, 'changed_beats': changed,
        'body_script_and_voice_unchanged': True,
        'phone_usb_connection_witnessed': True,
        'pc_generic_file_copy_witnessed': True,
        'phone_files_recents_witnessed': True,
        'phone_photo_copy_to_external_storage_witnessed': False,
        'phone_back_attachment_witnessed': False,
        'limitations': [
            'PC copy is a general file; phone Recents alone does not establish external volume or photo transfer.',
            'Phone-back attachment remains unverified despite the retained body line.',
            'Earlier memory/photo lines still use SSD assembly context; this is a partial source revision.',
            'A cable section is obscured by a small promotional-caption blur; cover has a lower-right blur patch.',
            'Five original files do not establish five independent filmmakers.',
        ],
    }
    save(final / 'verification.json', qa)
    editorial = Path('data/daily-rework-20261011') / code / 'writing/quality-v7-editorial-review.json'
    result = read(editorial)
    result.update(render_visual_review_pending=False, cover_lines_readable=True,
                  rendered_cover_path=str(final / 'cover.png'),
                  render_quality_draft=True, source_coverage_complete=False)
    save(editorial, result)
    print('Actual cover and twelve sampled frames recorded; only beats 11–13 changed.')


def progress():
    code = 'DeSoiZvyyqj'
    final = Path('data/folder-transfer-quality-20261011-v7') / code / 'final'
    prior = Path('data/source-quality-progress-20261011-old-jacket-value-v3.json')
    result = read(prior)
    result.update(recorded_at=datetime.now(timezone(timedelta(hours=9))).isoformat(),
                  previous_progress_receipt=str(prior), full_goal_complete=False,
                  goal_turn_classification='progress',
                  current_turn_tiktok_new_download_count=1)
    result['folder_transfer_v7'] = {
        'render_qa': read(final / 'verification.json'),
        'attachment': read(final / 'attachment.json'),
        'share': read(Path('data/folder-transfer-quality-20261011-v7-share.json')),
        'public_file': read(final / 'public-file-verification.json'),
        'browser': read(final / 'browser-verification.json'),
        'thumbnail_three_variants': 'data/daily-rework-20261011/DeSoiZvyyqj/writing/quality-v7.json',
        'editorial': read(Path('data/daily-rework-20261011') / code / 'writing/quality-v7-editorial-review.json'),
        'source_review': read(Path('data/daily-rework-20261011') / code / 'review/7675662575526497556/visual-review.json'),
        'previous_edits_retained': True, 'new_tts_requests': 0,
        'public_session_id': 4928,
    }
    result['audio_capability'] = {
        'actual_audio_input_attempted': True,
        'result': 'audio content omitted because you do not support audio input',
        'audio_listened': False,
        'preview_sample': 'data/old-jacket-value-20261011-v3/DeJ7hD6zsnR/final/audio-review-first-4s.mp3',
        'additional_user_completion_gate': False,
        'note': 'Whole video playback and audio-stream validation do not establish auditory review.',
    }
    result['remaining_full_scope'] = [
        'Folder phone attachment/photo-transfer lines lack direct matching scenes; some earlier memory lines still use SSD assembly context.',
        'Cart enlarged 360 footage and promotional-caption softening can be improved.',
        'A7 core-action coverage and hook; mirror original-story/source variety remain under review.',
        'Separate fish source material identity remains unresolved.',
        'Retain unsupported actual listening as a limitation, not an extra user-imposed completion gate.',
    ]
    result['completion_audit'].update(folder_thumbnail_three_variants_revised=True,
                                      folder_storage_three_cues_revised=True,
                                      folder_full_render_and_playback=True,
                                      full_objective_proven=False)
    save(Path('data/source-quality-progress-20261011-folder-transfer-v7.json'), result)
    source_path = Path('data/daily-rework-20261011') / code / 'review/7636068417656589600/visual-review.json'
    source = read(source_path)
    source['dense_review_correction'] = {
        'previous_copy_candidate_start': 12.5,
        'actual_12_533_frame': 'SSD assembly still visible',
        'copy_clip_start': 12.7,
        'reviewed_derivatives': str(final / 'clips-reviewed.json'),
        'phone_photos_copy_not_verified': True,
    }
    save(source_path, source)
    print('Full scope retained; current turn source, render and public-playback progress saved.')


if __name__ == '__main__':
    import sys
    progress() if sys.argv[1:] == ['progress'] else main()
