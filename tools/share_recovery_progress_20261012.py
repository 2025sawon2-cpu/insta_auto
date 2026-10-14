"""Serve only manually inspected, QA-passed renders from the full 18-item batch."""
import html,json,os,re,socket,subprocess,threading,time
from pathlib import Path
import requests
from PIL import Image
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.comparison_share import build_comparison,server_for,LABELS
from hotpost.source_quality import sha256_file
from hotpost.editing_adapter import _atomic_json

ROOT=Path('data/source-recovery-20261012-v1').resolve();PORT=8821
LABELS['DeVUQRZqKRM']='3번 · 접이식 캠핑 수납 테이블'
LABELS['DeWPBQyzpfR']='8번 · 자동 타코야키 기계'

def eligible(studio):
    result=[]
    for t in sorted(studio.store.list(),key=lambda t:t.get('automation',{}).get('rank',999)):
        if t.get('automation',{}).get('selection_date_kst')!='2026-10-12' or t['status']!='completed':continue
        path=ROOT/t['shortcode']/'manual-render-review.json'
        if not path.exists():continue
        manual=json.loads(path.read_text('utf-8'))
        e=next((e for e in t['edits'] if e['id']==t.get('edit_id')),None)
        if not e or manual['edit_id']!=e['id'] or not e.get('quality_verified'):continue
        qa=json.loads(Path(e['quality_review_path']).read_text('utf-8'))
        if not qa['passed'] or manual['render_sha256']!=qa['render_sha256']:continue
        if sha256_file(Path(e['export_path']))!=qa['render_sha256']:raise ValueError('Inspected export changed')
        result.append((t,e,qa))
    return result

def publish(studio,items,assets):
    for t,e,qa in items:
        Image.open(e['cover_path']).convert('RGB').save(Path(e['export_path']).parent/'comparison-poster.jpg',quality=94)
    codes=tuple(t['shortcode'] for t,_,_ in items)
    folder,new=build_comparison(studio,codes=codes,snapshot_suffix='recovery-20261012')
    page=(folder/'index.html').read_text('utf-8').replace('preload="metadata"','preload="none"')
    page=page.replace('<main><h1>','<main><p>오늘 오전 7시 선정된 18건 재작업 · '+str(len(items))+'건 검토 완료, '+str(18-len(items))+'건 진행 중</p><h1>')
    for t,e,qa in items:
        marker='<section><h2>'+html.escape(LABELS.get(t['shortcode'],t['title']))
        start=page.index(marker);end=page.index('</section>',start);m=qa['metrics']
        replay=max(0.0,m['same_source_time_replay_seconds'])
        body=f'<p>사용 원본 {m["parent_files"]}개 · 동일 원본 시간 재사용 {replay:g}초 · 최대 원본 비중 {m["maximum_source_share"]*100:.1f}%</p>'
        body+='<p>완성본의 실제 첫 프레임과 주요 동작을 확인했습니다. 개인 음성 설정·전체 대본 합성·출력 음성 시간축을 검증했으며, 청감상 자연스러움은 재생하며 확인해 주세요.</p>'
        body+='<details><summary>제작 대본</summary><p>'+html.escape(next(s['text'] for s in t['scripts'] if s['id']==e['script_id']))+'</p></details>'
        page=page[:end]+body+page[end:]
    (folder/'index.html').write_text(page,'utf-8')
    # Keep earlier allowed assets and URLs; replace the root page only after copy.
    assets.update({k:v for k,v in new.items() if k!='/'})
    assets['/']=new['/']
    return folder,codes

def verify(url,assets,public=False):
    r=requests.get(url,timeout=30);r.raise_for_status();assert '18건 재작업' in r.text
    assert requests.get(url+'/api/studio',timeout=20).status_code==404
    assert requests.post(url+'/',timeout=20).status_code==405
    for path,file in list(assets.items()):
        if not path.endswith('.mp4'):continue
        r=requests.get(url+path,headers={'Range':'bytes=0-15'},timeout=30)
        assert r.status_code==206 and r.content==file.read_bytes()[:16]
        r=requests.head(url+path+'?download=1',timeout=30);assert r.headers['Content-Disposition'].startswith('attachment;')
        if public:
            digest=__import__('hashlib').sha256()
            with requests.get(url+path,stream=True,timeout=90) as r:
                r.raise_for_status()
                for chunk in r.iter_content(262144):digest.update(chunk)
            assert digest.hexdigest()==sha256_file(file)

def main():
    with socket.socket() as probe:probe.bind(('127.0.0.1',PORT))
    settings=load_settings();studio=Studio(settings,workers=False);items=eligible(studio);assert items
    assets={};folder,codes=publish(studio,items,assets)
    server=server_for(assets,PORT);threading.Thread(target=server.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{PORT}';verify(base,assets)
    process=subprocess.Popen([str(settings.data_dir/'tools/cloudflared.exe'),'tunnel','--url',base,'--no-autoupdate'],
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        for line in process.stdout:
            match=re.search(r'https://[a-z0-9-]+\.trycloudflare\.com',line)
            if not match:continue
            url=match.group(0)
            for attempt in range(18):
                try:verify(url,assets,public=True);break
                except (requests.RequestException,AssertionError):
                    if attempt==17:raise
                    time.sleep(3)
            receipt={'url':url,'verified_public_bytes':True,'port':PORT,'server_pid':os.getpid(),'tunnel_pid':process.pid,
                'root':str(folder),'codes':codes,'goal_scope':18,'goal_complete':False,'temporary':True,'updated_at':time.time()}
            _atomic_json(ROOT/'share.json',receipt)
            print('Verified recovery progress comparison: '+url,flush=True)
            threading.Thread(target=lambda:list(process.stdout),daemon=True).start()
            signature=tuple(e['id'] for _,e,_ in items)
            while process.poll() is None:
                time.sleep(15);items=eligible(studio);new_signature=tuple(e['id'] for _,e,_ in items)
                if new_signature==signature:continue
                folder,codes=publish(studio,items,assets);verify(url,assets,public=True);signature=new_signature
                receipt.update(root=str(folder),codes=codes,updated_at=time.time());_atomic_json(ROOT/'share.json',receipt)
                print('Comparison updated:',len(codes),'of 18',flush=True)
    finally:
        if process.poll() is None:process.terminate()
        server.shutdown();server.server_close()

if __name__=='__main__':main()
