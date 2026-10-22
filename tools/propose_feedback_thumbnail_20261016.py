"""Exercise the shared title policy against preserved references and two videos."""
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hotpost.config import load_settings
from hotpost.script_rewriter import _generate
from hotpost.thumbnail_copy import INSTRUCTION, POLICY
from hotpost.visual_media import review_frame_data


def main():
    out=ROOT/'data/feedback-title-voice-20261016'
    target=out/'thumbnail-proposals.json'
    if target.exists():
        print('Existing proposals preserved:',target); return
    references=json.loads((out/'reference-inputs.json').read_text('utf-8'))
    media=[]
    for row in references:
        media.extend([{'text':'REFERENCE OPENING (not a verified feed poster): '+row['product']},
                      {'inlineData':review_frame_data(row['first_frame'])}])
    products=[]
    with closing(sqlite3.connect((ROOT/'data/studio/studio.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)) as db:
        for code in ('Dec5bcqyffk','Dec8wlLhu9N'):
            state=json.loads(db.execute("SELECT state FROM tasks WHERE json_extract(state,'$.shortcode')=?",(code,)).fetchone()[0])
            script=next(s for s in state['scripts'] if s['id']==state['script_id'])
            edit=next(s for s in state['edits'] if s['id']==state['edit_id'])
            plan=json.loads(Path(edit['plan_path']).read_text('utf-8'))
            products.append({'shortcode':code,'product':state['product'],'script':script['text'],
                             'old_lines':plan['cover_spec']['lines']})
            media.extend([{'text':'OUR CURRENT COVER '+code},{'inlineData':review_frame_data(edit['cover_path'])}])
    result=_generate(load_settings(),INSTRUCTION+
        'Return JSON {reference_analysis:[{product,observed_text,viewer_motive,why_this_wording}], '
        'products:[{shortcode,options:[{lines:[string,string],angle,script_quote,why_watch}],selected_index:integer}]}. '
        'Analyze only text actually visible in the supplied images, preserving uncertainty. '
        'Propose exactly three distinct angles per product, keeping the supplied script unchanged. '
        'Use the NEW policy; do not copy reference-specific popularity, claims, names or events into our titles. '
        'Select one strongest option; zero-based index. All quotes must occur literally in that product script.',
        {'purpose':'thumbnail_feedback_20261016','copy_policy':POLICY,'products':products,
         'references':[{'product':r['product'],'narration':r['narration']} for r in references]},media=media)
    by_code={p['shortcode']:p for p in products}
    for row in result['products']:
        assert row['shortcode'] in by_code and len(row['options'])==3
        assert type(row['selected_index']) is int and 0<=row['selected_index']<3
        for option in row['options']:
            assert len(option['lines'])==2 and all(isinstance(x,str) and x.strip() for x in option['lines'])
            assert option['script_quote'] and option['script_quote'] in by_code[row['shortcode']]['script']
    assert {r['shortcode'] for r in result['products']}==set(by_code)
    target.write_text(json.dumps({'policy':POLICY,'inputs':products,'result':result,
        'operational_tasks_changed':False,'reference_scope':'observed opening frames, not verified feed posters'},ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(result['products'],ensure_ascii=False))


if __name__=='__main__':main()
