"""Record evidence and remaining full-scope work without declaring completion."""
import json
from pathlib import Path
import time

ROOT = Path('data')
read = lambda path: json.loads(path.read_text('utf-8'))
cart = ROOT/'daily-cart-youtube-20261011-v6/DeTJ6HbKCdF/final'
jacket = ROOT/'daily-jacket-cover-20261011-v5/DeSvpmAsWgZ/final'
prior = read(ROOT/'source-quality-progress-20261011-file-v5.json')
record = {
    'at':time.time(), 'goal_status':'active',
    'previous_goal_turn_classification':'progress: existing-browser search integration, actual partial MP4 bug repair and cart v5/v6 render',
    'this_goal_turn_classification':'progress: live cart end playback and whole public-file verification; new jacket glyph detection, cover-only render and real browser verification',
    'full_scope':prior['full_scope'],
    'latest_comparison':read(ROOT/'daily-jacket-cover-20261011-v5-three-share.json'),
    'cart':{'verification':read(cart/'verification.json'),
        'browser':read(cart/'browser-verification.json'),
        'preservation':read(cart/'preservation-verification.json'),
        'public_file':read(cart/'public-verification.json'),
        'actual_comparison_screenshot':str((cart/'comparison-browser.png').resolve())},
    'jacket_cover':{'verification':read(jacket/'verification.json'),
        'browser':read(jacket/'browser-verification.json'),
        'preservation':read(jacket/'preservation-verification.json'),
        'attachment':read(jacket/'attachment-verification.json'),
        'actual_comparison_screenshot':str((jacket/'comparison-browser.png').resolve())},
    'latest_public_files':read(ROOT/'daily-jacket-cover-20261011-v5/public-verification.json'),
    'download_bug':{
        'old_declared_duration':33.1, 'old_actual_decoded_duration':21.133333,
        'old_incomplete_file_preserved':True,
        'old_audit':str((ROOT/'youtube-duration-audit-20261011.json').resolve()),
        'repaired_receipt':str((ROOT/'daily-rework-20261011/DeTJ6HbKCdF/youtube-observed-0PRF6gRJkbA/source-reception.json').resolve()),
        'repaired_actual_duration':33.1, 'repaired_actual_frames':993,
        'method':'existing Chrome playback responses, not separate profile or media URL requests',
        'body_errors':2,'all_download_methods_success_not_claimed':True},
    'checks_this_turn':{'cover_and_typography_tests_passed':18,
        'actual_cover_and_12_jacket_frames_viewed':True,
        'actual_cart_and_jacket_browser_end_playback':True,
        'two_public_whole_files_match_local':True,
        'old_runs_scripts_and_voices_preserved':True,
        'audio_listened':False},
    'completion_audit':{
        'thumbnail_display':'jacket glyph defect repaired, hook effectiveness still unproven',
        'writing':'A/B/C retained; jacket A now weakens reference value/family attraction; content redesign still required',
        'downloads':'one real incomplete MP4 repaired and fully decoded; all source and action coverage not complete',
        'full_scope_quality':'incomplete; cannot infer quality of seven products from these two fixes'},
    'remaining_by_product':{
        'DeRIBMYzn0x':'tent complete reference/thumbnail/script/full-scene/audio audit',
        'DeRFXHpEwck':'A7 receipt insertion scene, early source/text alignment and stronger product curiosity',
        'DeJ7hD6zsnR':'old jacket full hook/reference/value and audio review',
        'DeSoiZvyyqj':'phone attachment/photo-copy scene and photo-story source alignment',
        'DeTaESASnr_':'mirror source diversity/thumbnail/script audit; separate fish DeSngDcTAUJ ingredient/application evidence remains unresolved',
        'DeTJ6HbKCdF':'remaining blur bands, opening pulling text over static loaded view, unfolds/height sentence full action alignment, re-edited duplicate footage',
        'DeSvpmAsWgZ':'restore value/family product attraction without fabricating current discount; current attachment story is not enough'},
    'platform_constraints':'TikTok/Yandex CAPTCHA and Douyin login stops retained; do not replace account/profile or bypass stops',
    'next_action':'Prioritize semantic quality: fresh official Codex three-variant jacket revision preserving price/value and family attraction, then full cart narration/scene alignment; continue action-source search in available existing sessions. Do not count cover glyph cleanup as full hook or script completion.'}
(ROOT/'source-quality-progress-20261011-cart-cover.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf-8')
print('Full seven-product scope retained; current goal remains active/incomplete')
