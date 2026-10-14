"""One visual confirmation bound to unchanged masks and actual decoded pixels."""
import base64
import hashlib
import io
import json
from pathlib import Path
import sqlite3
from PIL import Image

from hotpost.config import load_settings
from hotpost.mask_application_evidence import input_binding_sha256, _pixels
from hotpost.script_rewriter import _generate

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/rework-top-three-20261014'
TASK='work-1672e441725d4445'
BINDING='bb12a26c1d9e3e7d76790e90fa72b86f7a557c599af3f6fda3315391fcfae39d'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def review(path, destination, binding):
    BINDING=binding
    if destination.exists():raise ValueError('Preserve existing official mask confirmation.')
    receipt=json.loads(path.read_text('utf-8'))
    receipt_sha=sha(path)
    if input_binding_sha256(receipt)!=BINDING or receipt['input_binding_sha256']!=BINDING:
        raise ValueError('Typed actual pixel binding changed.')
    with sqlite3.connect((ROOT/'data/studio/studio.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        state=json.loads(db.execute('SELECT state FROM tasks WHERE id=?',(TASK,)).fetchone()[0])
    if not state['automation'].get('paused_by_user') or state['edit_id']!=receipt['edit_id']:
        raise ValueError('Same failed rank-one output must remain held.')
    edit=next(e for e in state['edits'] if e['id']==state['edit_id'])
    if sha(edit['plan_path'])!=receipt['parent_plan_sha256'] or sha(edit['preview_path'])!=receipt['parent_preview_sha256']:
        raise ValueError('Frozen actual output changed.')
    for row in receipt['concat_inputs']:
        if sha(row['path'])!=row['sha256']:raise ValueError('Actual concat input changed.')
    graph=json.loads(Path(receipt['captures']['after']['graph_path']).read_text('utf-8'))
    if hashlib.sha256(graph['graph'].encode()).hexdigest()!=receipt['graph_sha256']:
        raise ValueError('Actual corrected producer graph changed.')
    media=[];projections=[]
    for case in receipt['cases']:
        if _pixels(case['before'],case['roi'])==_pixels(case['after'],case['roi']):raise ValueError('No actual ROI pixel change.')
        if case['before']['pts']!=case['after']['pts'] or case['before']['time_base']!=case['after']['time_base']:
            raise ValueError('Comparison is not the same decoded PTS.')
        for role in ('before','after'):
            record=case[role]
            # Display transport only: original PNG/native decoded evidence stays unchanged.
            display=io.BytesIO()
            with Image.open(record['path']) as original:
                original.convert('RGB').save(display,format='JPEG',quality=90,optimize=True)
            raw=display.getvalue()
            if len(raw)>1024*1024:raise ValueError('Display projection still exceeds the normal per-image limit.')
            projection={'beat_id':case['beat_id'],'role':role,'original_png_sha256':record['file_sha256'],
                'display_jpeg_sha256':hashlib.sha256(raw).hexdigest(),'canvas':[1080,1920],'quality':90,
                'purpose':'visual display transport; original decoded evidence is unchanged'}
            projections.append(projection)
            media.extend([{'text':json.dumps({'beat_id':case['beat_id'],'role':role,'source_sha256':case['source_sha256'],
                'source_native_frame':case['source_native_frame'],'same_pts':record['pts'],'time_base':record['time_base'],
                'approved_roi':case['roi'],'decoded_roi_rgb_sha256':record['roi_rgb_sha256'],'display_projection':projection},ensure_ascii=False)},
                {'inlineData':{'mimeType':'image/jpeg','data':base64.b64encode(raw).decode()}}])
    evidence={'purpose':'existing_approved_mask_application_pixel_confirmation','input_binding_sha256':BINDING,
        'policy':receipt['policy'],'edit_id':receipt['edit_id'],'parent_plan_sha256':receipt['parent_plan_sha256'],
        'parent_preview_sha256':receipt['parent_preview_sha256'],'cases':receipt['cases'],
        'scope':'Same actual concat, source/native frame, decoded PTS, mask coordinates, strength and intervals. '
            'Only actual renderer application timing changed. These images are prior to adding our narration captions. '
            'This confirmation cannot approve the whole final video or invent motion/recipe facts.',
        'expected_source_overlays':{'beat-6':'pink strip 핫도그NO~밥도그!!','beat-10':'white Hot dog.',
            'beat-19':'two Chinese lines at lower plate'}}
    evidence['display_projections']=projections
    value=_generate(load_settings(),
        'Inspect every provided before/after image pair. Return JSON {passed:boolean, input_binding_sha256:string, '
        'cases:[{beat_id,before_text_readable:boolean,after_text_unreadable:boolean,subject_visible:boolean,reason:string}]}. '
        'Copy the exact input binding. Confirm true ONLY when the indicated inserted source caption is readable '
        'in before and fully unreadable inside the existing approved mask in after, while the real rice/sausage/cheese '
        'food remains visible. Physical objects labels are not creator overlays. Use false for uncertain cases. '
        'Do not approve new mask coordinates, broaden any interval, claim unseen motion or declare final-video completion.',
        evidence,media=media)
    ids={c['beat_id'] for c in receipt['cases']}
    if (value.get('input_binding_sha256')!=BINDING or len(value.get('cases',[]))!=len(ids)
            or {c.get('beat_id') for c in value['cases']}!=ids):raise ValueError('Official result did not bind every exact case.')
    if value.get('passed') is True and not all(all(c.get(k) is True for k in ('before_text_readable','after_text_unreadable','subject_visible')) for c in value['cases']):
        raise ValueError('Partial confirmations cannot approve the repair.')
    if sha(path)!=receipt_sha:raise ValueError('Typed proof changed during confirmation.')
    value.update(actual_calls=1,input_count=len(projections),typed_receipt_sha256=receipt_sha,production_mutation=False,display_projections=projections)
    destination.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':value.get('passed'),'case_count':len(value['cases']),'input_binding_sha256':BINDING,'actual_calls':1}))


def main():
    review(OUT/'rank1-mask-application-bound-pending-receipt.json',
        OUT/'rank1-mask-application-official-review.json',BINDING)


if __name__=='__main__':main()
