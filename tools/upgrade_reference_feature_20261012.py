"""Re-evaluate one bounded clip using the whole reference and original facts."""
import argparse,copy,time
from pathlib import Path
from types import SimpleNamespace
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.source_functional import reference_review_info,review_function,apply_function_review
from hotpost.source_finder import extract_frames
from hotpost.source_quality import sha256_file
from hotpost.editing_adapter import _atomic_json

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--code');p.add_argument('--source');a=p.parse_args()
    studio=Studio(load_settings(),workers=False);state=next(t for t in studio.store.list() if t['shortcode']==a.code)
    source=next(v for v in state['sources'] if v['id']==a.source)
    assert sha256_file(Path(source['path']))==source['sha256']
    frames=[{'path':f['path'],'source_timestamp':f['source_timestamp']}
        for f in source['mask_review']['evidence_frames'] if any(w['source_start']<=f['source_timestamp']<w['source_end'] for w in source['reviewed_intervals'])]
    info=reference_review_info(state,studio.folder(state['id']))
    reference=extract_frames(Path(state['reference_video']),studio.folder(state['id'])/'source-reference',max_frames=6)
    review=review_function(studio.settings,SimpleNamespace(file_sha256=source['sha256']),reference,frames,info)
    root=Path('data/source-recovery-20261012-v1')/a.code
    _atomic_json(root/('feature-recheck-'+source['sha256'][:16]+'.json'),{'at':time.time(),'source_id':source['id'],
        'previous_review':source['functional_review'],'whole_reference_info':info,'new_review':review})
    if review['same_core_function']:
        def update(s,db):
            actual=next(v for v in s['sources'] if v['id']==source['id'])
            assert actual['sha256']==source['sha256']
            actual.setdefault('functional_review_history',[]).append(copy.deepcopy(actual['functional_review']))
            apply_function_review(actual,review)
            studio.store.event(db,s['id'],'whole_reference_feature_review',{'source_id':source['id'],
                'matched_features':review['matched_reference_features'],'scope':'approved intervals only; original files and prior review preserved'})
        studio.store.change(state['id'],update)
    print({'core':review['same_core_function'],'features':review['matched_reference_features'],
        'reason':review['reason'],'limits':review['context_usage_limits']},flush=True)
