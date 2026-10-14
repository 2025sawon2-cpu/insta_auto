"""Record observed render/source evidence without declaring the whole goal complete."""
import json
from pathlib import Path
import time
from hotpost.editing_adapter import _atomic_json as save


def read(path):
    return json.loads(path.read_text('utf-8')) if path.exists() else None


def main():
    data = Path('data')
    final = data / 'tent-product-cta-20261011-v4/DeRIBMYzn0x/final'
    product = data / 'daily-rework-20261011/DeTJ6HbKCdF'
    attempts = []
    for suffix in ('', '-playback-length-v2', '-fixed-720p-v3', '-buffer-before-decode-v4',
                   '-from-start-ad-aware-v5', '-visible-360p-v6'):
        root = product / ('youtube-observed-SUMUG36alRU' + suffix)
        attempts.append({'root': str(root.resolve()), 'result': read(root / 'source-reception.json'),
                         'browser': read(root / 'videos/01_youtube_SUMUG36alRU.reception.json')})
    record = {
        'recorded_at': time.time(), 'goal_turn_classification': 'progress',
        'full_goal_complete': False,
        'full_scope': {
            'original_three': ['DeRIBMYzn0x', 'DeRFXHpEwck', 'DeJ7hD6zsnR'],
            'later_video_four': ['DeSoiZvyyqj', 'DeTaESASnr_', 'DeTJ6HbKCdF', 'DeSvpmAsWgZ'],
            'additional_source_research': ['DeSngDcTAUJ'],
            'mirror_is_not_fish': True, 'photo_video_production_resumed': False},
        'tent': {name: read(final / filename) for name, filename in {
            'render_qa': 'verification.json', 'preservation': 'preservation-verification.json',
            'attachment': 'attachment.json', 'public_file': 'public-verification.json',
            'browser_playback': 'browser-verification.json', 'revision': 'revision-origin.json'}.items()},
        'tent_share': read(data / 'tent-product-cta-20261011-v4-share.json'),
        'additional_completed_download': read(product / 'youtube-observed-Rqs0hC5lpXI/source-reception.json'),
        'additional_source_actual_review': read(product / 'youtube-observed-Rqs0hC5lpXI/visual-review.json'),
        'later_completed_downloads': {vid: {
            'receipt': read(product / ('youtube-observed-' + vid) / 'source-reception.json'),
            'actual_review': read(product / ('youtube-observed-' + vid) / 'visual-review.json')}
            for vid in ('GvI-RWVv6x8', '-rqp7klUPCg', 'kVz3rckivWQ', 'f_cYO8w3hAI', '8DfD7PuK59Q')},
        'cart_opening_v7': {name: read(data / 'daily-cart-opening-20261011-v7/DeTJ6HbKCdF/final' / filename)
            for name, filename in {'render': 'verification.json', 'preservation': 'preservation-verification.json',
                'attachment': 'attachment.json', 'public_file': 'public-verification.json',
                'browser_playback': 'browser-verification.json', 'revision': 'revision-origin.json'}.items()},
        'cart_opening_share': read(data / 'daily-cart-opening-20261011-v7-share.json'),
        'tiktok_session_recheck': read(data / 'tiktok-session-recheck-20261011/recheck-authorized.json'),
        'folder_tiktok_downloads': {vid: {
            'decode': read(data / ('daily-rework-20261011/DeSoiZvyyqj/review/' + vid) / 'decode-sampling.json'),
            'actual_review': read(data / ('daily-rework-20261011/DeSoiZvyyqj/review/' + vid) / 'visual-review.json')}
            for vid in ('7636068417656589600', '7571797457391111446')},
        'older_jacket_new_script_review': read(data / 'old-jacket-value-20261011-v3/DeJ7hD6zsnR/writing/quality-v2-editorial-review.json'),
        'long_source_attempts': attempts,
        'download_changes': ['Caller deadlines preserved; normal longer playback gets bounded time up to 300 seconds',
            'Only verify candidate tracks after the player reports the final buffer; still require full decode duration/dimensions',
            'Failed received tracks retained as diagnostic-only bytes, never approved for editing',
            'Each justified retry has its own evidence directory; latest observed search receipt selected by recorded time',
            'Ads do not set the main-video duration, expectations or final-buffer signal',
            'First main-video playback starts at zero; unchanged bytes are checked against current duration/dimensions',
            'Visible player errors stop early with evidence; an explicit existing quality menu is the optional recovery route'],
        'tests_this_turn': '32 tests passed: test_youtube_download.py + test_youtube_ump.py + test_tiktok_download.py; py_compile + diff check passed',
        'remaining_full_scope': [
            'Actual audio hearing and final caption/narration quality across the full requested set',
            'Cart opening now has actual loaded walking; enlarged 360 footage and subtitle softening still need improvement',
            'Folder phone attachment/photo-transfer story still lacks strong direct matching scenes',
            'Old jacket price/family attraction restored in three new drafts; new voice/render and visual repetition still pending',
            'A7 selected product/core-action coverage and hook still under review',
            'Mirror original-story/source variety and separate fish material identity remain incomplete',
            'TikTok live search is now normal after user correction; same-session two downloads succeeded; preserve other platform authentication gates',
            'Hook/click/comment improvement is not established by subjective frame review'],
        'global_workers_restarted': False, 'capcut_registry_modified': False}
    save(data / 'source-quality-progress-20261011-tent-cta-and-long-source.json', record)
    print('Full-scope progress recorded; completion remains unproven.', flush=True)


if __name__ == '__main__':
    main()
