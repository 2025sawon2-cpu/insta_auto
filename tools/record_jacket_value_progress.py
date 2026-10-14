"""Preserve full-scope quality evidence for the next continuation."""
import json
from pathlib import Path
import time

data=Path('data')
read=lambda path:json.loads(path.read_text('utf-8'))
prior=read(data/'source-quality-progress-20261011-cart-cover.json')
root=data/'daily-jacket-value-20261011-v6/DeSvpmAsWgZ/final'
writing=data/'daily-rework-20261011/DeSvpmAsWgZ/writing'
source=data/'daily-rework-20261011/DeTJ6HbKCdF/youtube-observed-1xElY5438KU'
record={
    'at':time.time(),'goal_status':'active',
    'previous_goal_turn_classification':'progress: glyph detection and actual new cover render/browser verification',
    'this_goal_turn_classification':'progress: official Codex three-variant value redesign and one repair, new personal voice/render/share; additional existing-browser MP4 reception and actual 16-frame review',
    'full_scope':[s.replace('fish-mirror DeTaESASnr_','mirror DeTaESASnr_') for s in prior['full_scope']],
    'additional_source_research':'fish DeSngDcTAUJ remains separate from mirror; no photo-video production resumption',
    'writing_revisions':{'v5':'Restores value/family appeal but repetition and late price explanation remain; retained',
        'v6':read(writing/'quality-v6-editorial-review.json'),
        'all_three_variants':str((writing/'quality-v6.json').resolve()),
        'source_quantity_in_writing':False,'official_cli_only':True},
    'new_personal_voice':read(root/'voice-submission.json'),
    'render':read(root/'verification.json'),
    'attachment':read(root/'attachment-verification.json'),
    'share':read(data/'daily-jacket-value-20261011-v6-three-share.json'),
    'public_whole_file':read(root/'public-verification.json'),
    'browser_playback':read(root/'browser-verification.json'),
    'new_download':{'receipt':read(source/'source-reception.json'),
        'actual_visual_review':read(source/'visual-review.json'),
        'new_sources_received_this_turn':1,'selected_for_core_pulling':False,
        'scope':'same existing YouTube tab, browser playback UMP; no new profile or direct media URL request'},
    'completion_audit':{
        'thumbnail':'Actual readable DoHyeon, first-frame cover, specific product plus conditional price/ownership; effectiveness unproven',
        'script':'Actual A/B new conflicts and C meaningful surface changes reviewed; source count not used; numerical overlap metric advisory only',
        'downloads':'One more complete-decoded actual candidate received but needed pulling action absent; this is not all-source coverage',
        'full_scope':'Incomplete: cannot declare seven-product quality complete based on new jacket'},
    'remaining_by_product':prior['remaining_by_product'],
    'next_action':'Return to cart opening pulling action/blur bands and folder phone attachment/photo-copy, then remaining A7, tent, old jacket and mirror full audits. Keep every previous voice/edit/run/share and authentication stop.'}
record['remaining_by_product']['DeSvpmAsWgZ']='Value/family appeal now restored conditionally; assess hook delivery/current-price comprehension and actual audio quality, do not assert current sales price or same kids SKU.'
(data/'source-quality-progress-20261011-jacket-value-v6.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf-8')
print('Jacket value improvement recorded; full goal active/incomplete')
