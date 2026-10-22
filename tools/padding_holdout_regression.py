"""Recheck one separately held-out product using the frozen appeal contract."""
import sys
import hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from improve_padding_quality import OUT,read,save,sha
from hotpost.config import load_settings
from hotpost.script_rewriter import _generate
from hotpost.visual_media import review_frame_data

base=ROOT/'data/reference-calibration-20261013-v2-native'
evidence=read(base/'DeYZSuUyzzX/evidence.json');contract=read(base/'calibrated-policy.json')
assert sha(evidence['video_path'])==evidence['video_sha256']
media=[]
for row in [evidence['first_frame'],*evidence['sheets']]:
    assert sha(row['path'])==row['sha256']
    media.extend([dict(text='Original reference evidence, chronological body sheets; separate first frame'),
                  dict(inlineData=review_frame_data(row['path']))])
data=dict(purpose='padding_change_independent_product_appeal_regression',product=evidence['product'],
    script=evidence['narration'],original_text=evidence['narration'],original_caption=evidence['caption'],
    narration_source=evidence['narration_source'],duration=evidence['duration'],
    all_beats=evidence['timed_text'],beats=evidence['timed_text'],
    detailed_beat_ids=[b['id'] for b in evidence['timed_text']],
    evidence_scope='ORIGINAL reference, not a generated remake. Source form deviations are reported separately.',
    sampling='Actual original sampled at 2 frames/second; no continuous motion or auditory review claim')
target=OUT/'qa/independent-holdout.json'
if not target.exists():
    result=_generate(load_settings(),contract['instruction'],data,media=media)
    save(target,dict(case='DeYZSuUyzzX',product=evidence['product'],policy_sha256=hashlib.sha256(contract['instruction'].encode()).hexdigest(),
                     evidence_sha256=sha(base/'DeYZSuUyzzX/evidence.json'),review=result,audio_listened=False))
print(read(target)['review'],flush=True)
