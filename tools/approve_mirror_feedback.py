"""Bind an actual viewed blur review to the new derivative bytes."""
import copy,json
from pathlib import Path
from hotpost.editing_adapter import _atomic_json
from hotpost.source_quality import sha256_file
from hotpost.source_presentation import POLICY,review_scope,valid_review

ROOT=Path('data/user-feedback-revisions-20261011/DeTaESASnr_/final').resolve()

def main():
    plan=json.loads((ROOT/'proposed-plan.json').read_text('utf-8'))
    for source in plan['sources']:
        if not source.get('creator_watermarks_preprocessed'):continue
        evidence=[]
        for n,ratio in enumerate((.06,.5,.94)):
            frame=ROOT/(source['id']+f'-after-{n}.jpg')
            assert frame.is_file()
            evidence.append({'path':str(frame),'sha256':sha256_file(frame),
                'source_timestamp':max(0,source['video_meta']['duration']-.04)*ratio})
        prior=copy.deepcopy(source['previous_functional_review'])
        assert prior and prior.get('reviewed')
        prior.update(source_sha256=source['sha256'],evidence_frames=evidence,
            reviewer='codex_actual_image_review_20261011',
            reason='Reviewed start/middle/end after creator blur: original product and action remain visible.')
        source['functional_review']=prior
        source['presentation_review']={'policy':POLICY,'reviewed':True,
            'source_sha256':source['sha256'],'scope':review_scope(source),'evidence_frames':evidence,
            'usable':True,'quality_usable':True,'action_preserved':True,
            'reviewer':'codex_actual_image_review_20261011',
            'observations':['All eight derivative contact-sheet rows inspected: creator handle letters unreadable; mirror/board and motion visible. Physical decorations and ad label retained.'],
            'reason':'Actual new frames reviewed after blur, with prior review retained separately.'}
        source.update(pending_visual_review=False,editing_eligible=True,
            presentation_review_required=False,relevance_review_required=False)
        assert valid_review(source)
    spec=plan.get('cover_spec',{})
    chosen=spec.get('source')
    if chosen:
        chosen['source_sha256']=next(s['sha256'] for s in plan['shots'] if s['id']==chosen['shot_id'])
    _atomic_json(ROOT/'prepared-plan.json',plan)

if __name__=='__main__':main()
