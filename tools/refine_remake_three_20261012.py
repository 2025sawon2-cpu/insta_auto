"""An actual pink kids-wearing view instead of another hanger return."""
import argparse,copy,json,subprocess
from pathlib import Path
from PIL import Image,ImageDraw
from hotpost.source_quality import sha256_file
from hotpost.source_finder import probe_video
from hotpost.editing_adapter import _atomic_json
from hotpost.source_presentation import POLICY,review_scope
ROOT=Path('data/feedback-remake-20261012-v1/DeJ7hD6zsnR').resolve()

def stage():
    folder=ROOT/'final-v3';source=json.loads((ROOT/'discovery/ledger.json').read_text('utf-8'))['candidates'][13]
    clip=folder/'pink-kids-wear-clean-v2.mp4'
    graph='[0:v]scale=720:1280,setsar=1,fps=30,split=4[base][caption][creator][upper];[caption]crop=476:90:130:610,boxblur=18:3:8:3[c];[creator]crop=218:64:194:192,boxblur=18:3:8:3[w];[upper]crop=180:80:240:104,boxblur=18:3:8:3[u];[base][c]overlay=130:610[b];[b][w]overlay=194:192[b2];[b2][u]overlay=240:104[v]'
    if clip.exists() and clip.stat().st_size<1024:clip.rename(folder/'pink-kids-wear-failed.mp4')
    if not clip.exists():subprocess.run(['ffmpeg','-v','error','-ss','13.0','-t','1.45','-i',source['path'],'-filter_complex',graph,'-map','[v]','-an','-c:v','libx264','-crf','18','-preset','veryfast',str(clip)],check=True,capture_output=True)
    frames=[];sheet=Image.new('RGB',(800,356),'#222')
    for i,t in enumerate((.02,.43,.9,1.4)):
        f=folder/f'pink-kids-clean-{i}.jpg';subprocess.run(['ffmpeg','-v','error','-y','-ss',str(t),'-i',str(clip),'-frames:v','1',str(f)],check=True,capture_output=True)
        im=Image.open(f);im.thumbnail((200,356));sheet.paste(im,(i*200,0));frames.append({'path':str(f),'timestamp':t,'sha256':sha256_file(f)})
    sheet.save(folder/'pink-kids-clean-review.jpg',quality=95)
    _atomic_json(folder/'pink-kids-pending.json',{'id':'remake-v3-pink-kids-wear','name':'pink-kids-wear','path':str(clip),'sha256':sha256_file(clip),'video_meta':probe_video(clip),'original_path':source['path'],'original_sha256':source['sha256'],'original_interval':{'start':13.0,'end':14.45},'provider':'tiktok','url':source['url'],'rights':'unknown-check-before-reuse','source_role':'core','evidence_frames':frames,
       'applied_overlay_cleanup':{'caption_pixels':[130,610,476,90],'creator_pixels':[[194,192,218,64],[240,104,180,80]],'baked_in':True}})

def finish():
    folder=ROOT/'final-v3';s=json.loads((folder/'pink-kids-pending.json').read_text('utf-8'));assert sha256_file(Path(s['path']))==s['sha256']
    observation='분홍색 키즈 패딩을 입은 몸통·소매와 지퍼 앞을 움직이는 손. 로고만 보여주는 컷이 아님. 삽입 대사와 작은 DECOlog 표시는 실제 위치를 확인하여 가림.'
    s.update(editing_eligible=True,source_quality='reviewed-portrait',blur_required=False,watermark_masks=[],presentation_review_required=False,relevance_review_required=False)
    s['functional_review']={'reviewed':True,'source_sha256':s['sha256'],'same_core_function':True,'context_usable':True,'context_usage_limits':['핑크 키즈 패딩 착용의 예시. 동일 SKU·판매 조건·실제 구매 경험을 입증하지 않음.'],'observed_actions':[observation],'evidence_frames':[f['path'] for f in s['evidence_frames']],'reviewer':'codex_session_visual_review'}
    s['presentation_review']={'policy':POLICY,'reviewed':True,'source_sha256':s['sha256'],'scope':review_scope(s),'usable':True,'quality_usable':True,'action_preserved':True,'observations':[observation],'evidence_frames':s['evidence_frames'],'reviewer':'codex_session_visual_review'}
    p=json.loads((ROOT/'final-v2/timeline.json').read_text('utf-8'))
    for key in ('rendered_clips','cover_path','sfx_path','output_dir'):p.pop(key,None)
    p['sources'].append(s);p['shots'].append({'id':'new-pink-kids-wear','source_id':s['id'],'path':s['path'],'sha256':s['sha256'],'start':0,'end':s['video_meta']['duration'],'frames':[f['path'] for f in s['evidence_frames']],'observation':observation,'source_role':'core','evidence_status':'observed'})
    p['beats'][9].update(options=[{'shot_id':'new-pink-kids-wear','relation':'context','reason':observation,'reviewed':True}]);p['beats'][9].pop('selected_shot_id',None)
    for shot in p['shots']:
        if shot['id']=='new-gray-outdoor-back':shot['start']=.9
    for beat in p['beats']:beat.pop('selected_shot_id',None)
    p['session_options_ready']=True;_atomic_json(folder/'selection-input.json',p);_atomic_json(folder/'pink-kids-approved.json',s)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['stage','finish']);a=parser.parse_args();globals()[a.action]()
