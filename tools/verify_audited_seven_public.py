"""Verify all current exports and all 21 alternatives on the combined page."""
import hashlib,html,json,time
from pathlib import Path
import requests
from hotpost.editing_adapter import _atomic_json as save
from hotpost.request_pacing import request_pause
from hotpost.source_quality import sha256_file

OUT=Path('data/quality-scope-audit-20261011-v1')
def read(p):return json.loads(Path(p).read_text('utf-8'))
def main():
    receipt=Path('data/quality-audited-seven-20261011-v2-share.json')
    if not receipt.exists():receipt=Path('data/quality-audited-seven-20261011-share.json')
    base=read(receipt)['url']
    def req(path):
        request_pause();r=requests.get(base+path,timeout=90);r.raise_for_status();return r
    page=req('/').content.decode('utf-8').replace('\r\n','\n');assert '총 7건' in page
    rows=[]
    for x in read(OUT/'shared-current-selection.json'):
        q=read(x['writing_path']);assert sha256_file(Path(x['writing_path']))==x['writing_sha256']
        assert len(q['scripts'])==3 and all(html.escape(s['text']).replace('\r\n','\n') in page for s in q['scripts'])
        media=req('/'+x['code']+'-final.mp4');digest=hashlib.sha256(media.content).hexdigest()
        assert digest==x['render_sha256']==sha256_file(Path(x['render_path']))
        rows.append({'code':x['code'],'edit_id':x['edit_id'],'url':base+'/'+x['code']+'-final.mp4',
            'public_sha256':digest,'local_sha256':digest,'bytes':len(media.content),
            'all_three_proposals_present':True,'whole_file_identical':True})
        save(OUT/'public-seven-verification.json',{'url':base,'rows':rows,'all_seven_verified':len(rows)==7,'checked_at':time.time()})
        print(x['code'],'current export and all three proposals verified',flush=True)
    a7=next(x for x in read(OUT/'shared-current-selection.json') if x['code']=='DeRFXHpEwck')
    final=Path(a7['plan_path']).parent
    save(final/'public-file-verification.json',next(r for r in rows if r['code']=='DeRFXHpEwck'))

if __name__=='__main__':main()
