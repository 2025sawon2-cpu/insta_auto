"""Preserved, per-reference feedback remake; never pools unrelated tasks."""
import argparse, copy, hashlib, json, sqlite3, subprocess, time
from pathlib import Path
from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json
from hotpost.studio import Studio

ROOT = Path('data/feedback-remake-20261012-v1').resolve()
WORKS = {'DeJ7hD6zsnR': 'work-7de866f1dc7d4e71',
         'DeTaESASnr_': 'work-d1fa59214c564076',
         'DeTJ6HbKCdF': 'work-385b11cdea3040cb',
         'DeSvpmAsWgZ': 'work-ea4d11c896714ac1'}

def read(path):
    return json.loads(Path(path).read_text('utf-8'))

def snapshot():
    studio = Studio(load_settings(), workers=False)
    for code, task in WORKS.items():
        folder = ROOT/code; folder.mkdir(parents=True, exist_ok=True)
        target = folder/'baseline.json'
        if target.exists():
            continue
        state = studio.store.get(task)
        edit = next(e for e in state['edits'] if e['id'] == state['edit_id'])
        plan_path = edit.get('plan_path') or edit.get('plan_json_path')
        if not plan_path:
            plan_path = str(Path(edit['export_path']).parent/'plan.json')
        plan = read(plan_path)
        script = next(s for s in state['scripts'] if s['id'] == state['script_id'])
        voice = next(v for v in state['voices'] if v['id'] == state['voice_id'])
        _atomic_json(target, {'task_id':task,'state':state,'edit':edit,'plan':plan,
                              'script':script,'voice':voice,'saved_at':time.time()})
        ref = state['reference_video']
        subprocess.run(['ffmpeg','-v','error','-y','-i',ref,'-vf',
                        'fps=1/2,scale=270:480:force_original_aspect_ratio=decrease,pad=270:480:(ow-iw)/2:(oh-ih)/2,tile=5x4',
                        '-frames:v','1',str(folder/'reference-overview.jpg')],check=True,capture_output=True)
        print(code, 'snapshot', list(edit), 'reference', ref, flush=True)
    db = sqlite3.connect('file:../VoiceBench/data/voicebench.sqlite3?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    audit=[]
    for request in (168,169,179,180):
        rows=db.execute('SELECT q.id request_id,q.seed,q.quality_mode,q.generation_json,p.reference_sha256,r.manifest_json,r.metrics_json FROM studio_requests q JOIN projects p ON p.id=q.project_id JOIN studio_segments s ON s.request_id=q.id JOIN runs r ON r.job_id=s.job_id WHERE q.id=?',(request,)).fetchall()
        for row in rows:
            v=dict(row);m=json.loads(v.pop('manifest_json'));metrics=json.loads(v.pop('metrics_json'))
            v['engine']=m.get('engine');v['synthesis']=metrics.get('synthesis');v['quality']=metrics.get('quality')
            audit.append(v)
    _atomic_json(ROOT/'voice-settings-audit.json',audit)
    print(json.dumps(audit,ensure_ascii=False),flush=True)

def write(code):
    from hotpost.writing.contract import snapshot as contract_snapshot
    from hotpost.writing.pipeline import generate
    base=read(ROOT/code/'baseline.json');state=base['state']
    folder=ROOT/code/'writing';folder.mkdir(parents=True,exist_ok=True)
    if (folder/'quality.json').exists():
        print('preserved writing',code);return
    specific={
        'DeJ7hD6zsnR': '이 원작의 핵심은 비싼 구매를 되돌아보고 가족 겨울옷으로 가치가 확장되는 발견이다. 제품은 여러 색상과 형태의 노스페이스 패딩이지 특정 흰검 배색 한 벌이 아니다. 실제 참고 전반에는 베이지/핑크/검정/파랑과 성인·키즈가 다양하게 나온다. 외형 부위에 집착하지 말고 제품에 대한 구매 욕구와 명확한 갈등 하나를 구성한다. 원문 언니에게 혼남→환불→가족 구매 전개/택-AS-키즈 특징 묶음을 A/B에 복제하지 않는다. 오늘 가격/할인/재고는 검증하지 않았으므로 특정 금액이나 지금 할인중이라고 단정하지 않는다. 가격 매력은 조건 한 번만 붙이고 명확하게 쓴다.',
        'DeSvpmAsWgZ': '이 레퍼런스는 친구들이 겨울 전에 이미 패딩을 찾는 의외성, 놓친 선택지를 다시 발견하는 매력이다. 베이지/핑크/검정/초록 등 여러 노스페이스 패딩의 착용과 행거 장면이 나온다. 이전 흰 몸판 검은 어깨 원고와 다른 패딩 영상 원고를 입력/모범으로 쓰지 않는다. 독립적인 생활 갈등과 소비자말로 쉽게 이해되는 전개를 만든다. 다른 영상의 환불·가족 일괄 구매 이야기에 기계적으로 합치지 않는다. 오늘 판매가/AS/재고는 새로 검증한 사실이 아니므로 단정하지 않는다. 이 제품을 탐색하고 싶은 구체적인 매력을 남긴다.',
        'DeTaESASnr_': '제품은 옆으로 밀면 전신 거울이 나오는 은색 자석 보드이다. 현관의 열쇠/메모/외출 전 차림 확인이라는 실제 기능은 유지한다. 썸네일은 전신거울/슬라이딩거울 같은 정답을 모두 공개해 궁금증을 해소하지 않는다. 폐쇄된 보드의 실제 이미지와 결합해 이 물건에 무엇이 더 있는지 구체적 정보 공백을 남기고 본문에서 실제 기능으로 해소한다. 과장된 사건이나 불안 유발/미확인 수치를 만들지 않는다. 이전 5번의 일상적인 대화체를 유지하되 원작 전개를 그대로 따라가지 않는다.',
        'DeTJ6HbKCdF': '제품은 접으면 짐을 옮기는 카트가 되고 펼치면 캠핑 테이블로 쓰는 물건이다. 참고에 있는 높이 조절·확장·파라솔 설치 기능은 유지할 수 있다. 기존 기능을 새 갈등에 자연스럽게 배치한다. 별도 짐을 챙기던 원문의 진행과 문장을 A/B에서 그대로 복제하지 않는다. 테이블과 카트의 실제 변형이 무엇인지 바로 이해되게 한다.'}
    notes=('이번 사용자 재제작 지시를 기존 계약보다 우선 적용한다. 항상 3안 A/B/C와 각 안 심리 편향·변경점·2줄 썸네일을 생성한다. A/B는 원작이 쓰지 않은 서로 다른 메커니즘과 새 전개. C만 원작의 흐름+표면2~3개 치환. 각 대본은 공백 정리 후 230자 이내, 자연스러운 일상 대화체, 단일 합성. 마지막은 정확히 댓글에 ‘나도’ 남겨주세요. 로 바로 끝낸다. 이 제품이 궁금하면/정보가 궁금하면/마지막으로 등 끝난다는 예고와 추가 인사를 쓰지 않는다. 본문에서 제품을 궁금해할 이유는 충분히 설명한다. 편향 이름이나 추상적인 교훈을 낭독하지 않는다. 억지 구체화·어색한 해부학적 외형 표현·동일 문구 강박을 없앤다. 원작의 실제 제품 정보와 핵심 매력만 유지하고 이전 실패한 대본은 참고하지 않는다. 썸네일에는 사람 얼굴을 쓰지 않는 제품 장면을 예정하고 문구로 기능 전체 정답을 미리 밝히지 않는다. '+specific[code])
    payload={'reference_script':state.get('reviewed_original_text') or state['original_text'],
             'reference_kind':state.get('reference_kind') or 'speech',
             'reference_caption':state.get('title') or '', 'comment_keyword':'나도',
             'notes':notes,'writing_contract':contract_snapshot()}
    _atomic_json(folder/'input.json',payload)
    result=generate(payload,folder,lambda:None,lambda pct,message:print(code,round(pct*100),message,flush=True))
    _atomic_json(folder/'quality.json',result)
    print(code,json.dumps(result['scripts'],ensure_ascii=False),flush=True)

def discover(code):
    from dataclasses import replace
    from playwright.sync_api import sync_playwright
    from hotpost.browser_search import BrowserSearcher
    from hotpost.source_browser_runtime import attach_browser,browser_lease
    folder=ROOT/code/'discovery';folder.mkdir(parents=True,exist_ok=True)
    query=('노스페이스 눕시 패딩 착용' if code=='DeJ7hD6zsnR' else 'north face puffer jacket try on winter')
    search=BrowserSearcher(replace(load_settings(),source_browser_captcha_wait=0),folder)
    search.progress=lambda m:print(m,flush=True)
    search.deadline=time.monotonic()+250
    with browser_lease(search.settings),sync_playwright() as pw:
        context=attach_browser(pw,search.settings)
        search._platforms(context,[query],12,providers=['tiktok'])
    value={'candidates':search.candidates,'searches':search.searches,'notes':search.notes,'query':query,'time':time.time()}
    _atomic_json(folder/'ledger.json',value)
    print(json.dumps(value,ensure_ascii=False),flush=True)

def search_kids(code):
    from dataclasses import replace
    from playwright.sync_api import sync_playwright
    from hotpost.browser_search import BrowserSearcher
    from hotpost.source_browser_runtime import attach_browser,browser_lease
    folder=ROOT/code/'discovery';previous=read(folder/'ledger.json')
    query='노스페이스 키즈 핑크 패딩'
    search=BrowserSearcher(replace(load_settings(),source_browser_captcha_wait=0),folder/'kids')
    search.progress=lambda m:print(m,flush=True);search.deadline=time.monotonic()+250
    with browser_lease(search.settings),sync_playwright() as pw:
        context=attach_browser(pw,search.settings);search._platforms(context,[query],6,providers=['tiktok'])
    _atomic_json(folder/'kids/ledger.json',{'candidates':search.candidates,'searches':search.searches,'notes':search.notes})
    urls={r['url'] for r in previous['candidates']}
    previous['candidates'].extend(r for r in search.candidates if r['url'] not in urls)
    previous['searches'].extend(search.searches);_atomic_json(folder/'ledger.json',previous)
    print(json.dumps([(i,r['url'],r['title']) for i,r in enumerate(previous['candidates']) if r.get('query')==query],ensure_ascii=False),flush=True)

def repair_triplet(code):
    from hotpost.writing import codex_writer
    from hotpost.writing.variants import SCHEMA,validate_triplet
    from hotpost.writing.checks import review
    from hotpost.writing.contract import snapshot as contract_snapshot,receipt
    folder=ROOT/code/('writing-v3' if code=='DeSvpmAsWgZ' else 'writing-v2');folder.mkdir(parents=True,exist_ok=True)
    if (folder/'quality.json').exists():return
    payload=read(ROOT/code/'writing/input.json');prior=read(ROOT/code/'writing/quality.json')
    contract=contract_snapshot();trace={'directory':folder,'calls':[]}
    instructions=('기존 세 안을 전면 재설계하세요. 소비자 입장에서 실제 읽으면 살수있다면/사고싶어요 같은 막연한 가정·희망만 늘어놓아 제품 욕구가 약하고 심리학 과제처럼 들립니다. 상상의 조건을 영상 전체 이야기로 삼지 마세요. 원작에 실제 있는 노스페이스 성인/키즈 겨울 패딩의 구체적인 선택 매력과 사용 생활 상황을 중심으로 쉽고 자연스러운 이야기를 만드세요. 제품의 형태·용도는 말할 수 있으나 부위 배색에 집착하거나 모든 가족이 같은 색상/가격/모델이라고 단정하지 않습니다. 가격은 현재 확인하지 않았으므로 구체적 판매가·진행중인 할인·AS/재고 보증을 새로 단정하지 마세요. 가격 숫자를 빼도 예산/가족 선택이라는 원작 핵심 가치는 살릴 수 있습니다. 실제 제품의 실루엣/착용/색상 선택과 새 갈등을 연결해 왜 이 노스페이스 패딩을 궁금해해야 하는지 명확히 만드세요. 같은 교훈/희망을 반복해 길이를 채우지 마세요. A/B는 원작과 다른 서로 다른 심리 효과를 주된 가치판단 카테고리 안에서 실제 사건/정보 순서에 적용하고, C는 흐름 유지+표면치환2~3개. 항상3안. 각 안230자 이내, 마지막 정확히 댓글에 ‘나도’ 남겨주세요. 만 쓰고 끝냅니다. 이 제품이 궁금하면 등 예고 금지. 감탄사 아/휴를 일괄 시작하지 마세요. 2줄 썸네일은 제품에 대한 해결되지 않은 구체적인 궁금증을 남깁니다. 규칙 전체:\n'+contract['prompt'])
    if code=='DeSvpmAsWgZ':
        instructions+=' 이 영상은 다른 가족 쇼핑 패딩 영상과 별개의 레퍼런스다. A/B에서는 가족 옷 예산→아이 핑크→엄마 색상→두벌 가격이라는 이전 재작업 공식을 반복하지 않는다. 이 원작의 겨울 오기 전 비싼 패딩이라는 선입견 때문에 놓친 선택지를 다시 발견하는 핵심을 독립적으로 재해석한다. 특정 부위·색상은 소구의 핵심이 아니면 낭독에 억지로 넣지 않는다. 노스페이스 숏패딩 자체의 겨울 차림/실루엣과 구체적인 생활 갈등을 중심으로 작성하고, 지출 부담은 맥락으로 살린다. 원작의 친구→할인→보증묶음→가족 순서를 A/B에 보존하지 않는다. 가짜 할인·오늘최저가를 만들지 않고 제품 욕구를 남긴다.'
    result=codex_writer.chat(instructions,json.dumps({'reference':payload['reference_script'],'failed_scripts':[{k:s[k] for k in ['text','bias','quality_summary']} for s in prior['scripts']]},ensure_ascii=False),SCHEMA,lambda:None,trace)
    validate_triplet(result)
    scripts=[]
    for v in result['variants']:
        assert v['text'].endswith('댓글에 ‘나도’ 남겨주세요.')
        local=review(v['text'],payload['reference_script'],keyword='나도',contract=contract)
        scripts.append({**local,'text':v['text'],'title':('유형전환 A','유형전환 B','표면 치환형')[v['number']-1],
            'variant_number':v['number'],'variant_type':v['variant_type'],'bias':v['bias'],
            'psychological_category':v['category'],'changes':v['changes'],'surface_changes':v['surface_changes'],
            'mechanism_application':v['mechanism_application'],'thumbnail_lines':v['thumbnail_lines'],
            'thumbnail_mechanism':v['thumbnail_mechanism'],'origin':'codex_internal','source_ids':['R1']})
    _atomic_json(folder/'quality.json',{'scripts':scripts,'writing_contract':receipt(contract),'benchmark':{'analysis':result},'generation_inference':trace['calls'],'previous_quality':str(ROOT/code/'writing/quality.json')})
    print(json.dumps([{k:s[k] for k in ['variant_number','text','bias','thumbnail_lines']} for s in scripts],ensure_ascii=False),flush=True)

def voice(code,index=0):
    from hotpost.voicebench_adapter import VoiceBenchAdapter
    from hotpost.source_quality import sha256_file
    final=ROOT/code/'final';final.mkdir(parents=True,exist_ok=True)
    writing=next(n for n in ('writing-v3','writing-v2','writing') if (ROOT/code/n/'quality.json').exists())
    quality_path=ROOT/code/writing/'quality.json'
    quality=read(quality_path);selected=copy.deepcopy(quality['scripts'][index]);text=selected['text']
    assert text.endswith('댓글에 ‘나도’ 남겨주세요.') and len(' '.join(text.split()))<=230
    digest=hashlib.sha256(text.encode()).hexdigest()
    script={**selected,'id':'remake-20261012-script-'+digest[:12],'sha256':digest,'writing_contract':quality['writing_contract'],'status':'completed','created':time.time()}
    if (final/'script.json').exists():assert read(final/'script.json')['sha256']==digest
    else:_atomic_json(final/'script.json',script)
    (final/'words.txt').write_text(text,'utf-8')
    _atomic_json(final/'writing-selection.json',{'quality_path':str(quality_path),'variant':index+1})
    if (final/'voice.json').exists():return
    submit=final/'voice-submission.json';request=read(submit)['request_id'] if submit.exists() else None
    result=VoiceBenchAdapter(load_settings()).synthesize(text,final/'narration.wav',request_id=request,
        on_submitted=lambda i:_atomic_json(submit,{'request_id':i,'script_sha256':digest}),
        generation_key='remake-20261012-'+code+'-'+digest[:32],require_personal_clone=True,
        progress=lambda m,n:print(code,m,n,flush=True))
    assert result['speech_plan']['segment_count']==1
    _atomic_json(final/'voice.json',{**result,'id':'remake-20261012-voice-'+digest[:12],'path':str(final/'narration.wav'),
        'sha256':sha256_file(final/'narration.wav'),'duration':result['audio']['duration'],'script_id':script['id'],
        'script_sha256':digest,'created':time.time(),'status':'completed'})
    print(code,'voice done',result['audio']['duration'],flush=True)

def download(code,index):
    from hotpost.source_finder import probe_video
    from hotpost.source_quality import sha256_file
    from hotpost.tikvideo_download import with_fallback
    folder=ROOT/code/'discovery';data=read(folder/'ledger.json');row=data['candidates'][index]
    if row.get('download_attempted') and not row.get('path'):
        if 'Execution context was destroyed' in row.get('error','') and not row.get('post_document_fix_retry'):
            row['post_document_fix_retry']=True
            row['prior_attempt']={k:row.get(k) for k in ('error','diagnostics','attempted_at')}
        else:raise RuntimeError('Previous failure preserved; no automatic retry')
    if not row.get('path'):
        row.update(download_attempted=True,attempted_at=time.time());_atomic_json(folder/'ledger.json',data)
        diag={};target=folder/(row['url'].rsplit('/',1)[-1]+'.mp4')
        try:
            path=with_fallback(load_settings(),row['url'],target,80*1024*1024,deadline=time.monotonic()+330,diagnostics=diag)
            row.update(path=str(path.resolve()),sha256=sha256_file(path),video_meta=probe_video(path))
        except Exception as exc:
            row['error']=str(exc)[:1200];raise
        finally:
            row['diagnostics']=diag;_atomic_json(folder/'ledger.json',data)
    subprocess.run(['ffmpeg','-v','error','-i',row['path'],'-f','null','-'],check=True,capture_output=True)
    duration=row['video_meta']['duration'];contact=folder/(str(index)+'-contact.jpg')
    subprocess.run(['ffmpeg','-v','error','-y','-i',row['path'],'-vf',
        f'fps=16/{duration},scale=200:356:force_original_aspect_ratio=decrease,pad=200:356:(ow-iw)/2:(oh-ih)/2,tile=4x4',
        '-frames:v','1',str(contact)],check=True,capture_output=True)
    print(json.dumps({'url':row['url'],'meta':row['video_meta'],'contact':str(contact)},ensure_ascii=False),flush=True)

def inventory(code):
    base=read(ROOT/code/'baseline.json')
    for source in base['plan']['sources']:
        print(json.dumps({'id':source['id'],'path':source['path'],'actions':source.get('functional_review',{}).get('observed_actions')},ensure_ascii=False))

CLIPS={
 'DeJ7hD6zsnR':[
  ('pink-held',3,3.5,8.2,[0,0,1,.935],[], '행거에 걸린 분홍색 노스페이스 패딩 전체를 보여줌'),
  ('pink-zip',3,13,18,[0,0,1,.935],[], '분홍색 패딩을 입고 지퍼를 열고 닫으며 앞면을 보여줌'),
  ('gray-held',3,26,31,[0,0,1,.935],[], '회색 패딩을 행거에 들어 앞면과 소매를 보여줌'),
  ('gray-fit',3,31.5,37,[0,0,1,.935],[], '회색 노스페이스 패딩을 입고 앞면과 옆면을 보여줌'),
  ('black-casual',9,2.3,5.2,None,[], '검정 패딩을 입고 거울 앞에서 정면과 측면 차림을 보여줌'),
  ('black-seated',9,6.3,10.8,None,[], '검정 패딩과 청바지를 입고 의자에 앉은 전체 차림'),
  ('pink-kids-hanger',17,9.2,12.9,None,[], '분홍색 노스페이스 키즈 겨울 자켓을 행거에 걸고 앞뒤 형태를 보여줌. 원작의 정확한 모델 일치는 미확인'),
 ],
 'DeSvpmAsWgZ':[
  ('brown-front',4,.2,3.7,None,[], '갈색 노스페이스 숏패딩을 입고 전면 지퍼와 옆 실루엣을 보여줌'),
  ('brown-back',4,4.2,8,None,[], '갈색 숏패딩을 입고 돌아서 뒷면과 옆면을 보여줌'),
  ('black-put-on',1,2.6,5.9,None,[], '검정 숏패딩을 입고 지퍼를 여미는 전신 모습'),
  ('black-outfit',1,8.9,12.4,None,[], '같은 검정 패딩을 모자와 운동화 차림에 입는 모습'),
  ('gray-adult-front',5,7.8,10.6,None,[], '성인 남성이 회색 노스페이스 패딩 전면과 소매를 보여줌'),
  ('gray-adult-back',5,13.0,16.1,None,[], '회색 패딩을 입고 돌아서 뒷면을 보여줌'),
 ]}

def clips(code):
    from PIL import Image,ImageDraw
    from hotpost.source_finder import probe_video
    from hotpost.source_quality import sha256_file
    rows=read(ROOT/code/'discovery/ledger.json')['candidates'];out=ROOT/code/'final';out.mkdir(parents=True,exist_ok=True)
    sources=[]
    for name,index,start,end,crop,blur,description in CLIPS[code]:
        row=rows[index];target=out/'clips'/(name+'.mp4');target.parent.mkdir(exist_ok=True)
        vf='scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,fps=30'
        if crop:
            w,h=row['video_meta']['width'],row['video_meta']['height'];x,y,z,u=crop
            vf=f'crop={int(w*(z-x))//2*2}:{int(h*(u-y))//2*2}:{int(w*x)//2*2}:{int(h*y)//2*2},'+vf
        if not target.exists():
            subprocess.run(['ffmpeg','-v','error','-ss',str(start),'-t',str(end-start),'-i',row['path'],'-an','-vf',vf,'-c:v','libx264','-preset','veryfast','-crf','18',str(target)],check=True,capture_output=True)
        meta=probe_video(target);frames=[]
        for i,fraction in enumerate((.02,.3,.65,.98)):
            frame=target.with_name(name+f'-{i}.jpg');second=(meta['duration']-.05)*fraction
            subprocess.run(['ffmpeg','-v','error','-y','-ss',str(second),'-i',str(target),'-frames:v','1',str(frame)],check=True,capture_output=True)
            frames.append({'path':str(frame),'timestamp':second,'sha256':sha256_file(frame)})
        sources.append({'id':'remake-20261012-'+code+'-'+name,'name':name,'path':str(target),'sha256':sha256_file(target),
            'video_meta':meta,'original_path':row['path'],'original_sha256':row['sha256'],'original_interval':{'start':start,'end':end},
            'url':row['url'],'provider':'tiktok','rights':'unknown-check-before-reuse','source_role':'core',
            'proposed_observation':description,'evidence_frames':frames,'pending_visual_review':True,'crop':crop})
    _atomic_json(out/'new-sources-pending.json',sources)
    for offset in range(0,len(sources),4):
        batch=sources[offset:offset+4];sheet=Image.new('RGB',(800,382*len(batch)),'#222');draw=ImageDraw.Draw(sheet)
        for j,s in enumerate(batch):
            for i,f in enumerate(s['evidence_frames']):
                with Image.open(f['path']) as im:
                    im.thumbnail((200,356));sheet.paste(im,(i*200,j*382+26))
                draw.text((i*200+2,j*382+2),s['name']+f" {f['timestamp']:.2f}",fill='white')
        sheet.save(out/f'new-sources-sheet-{offset//4}.jpg',quality=95)
    print(code,'bounded clips await visual review',flush=True)

FINAL_VERSION='final'

def boundary(code,action,**payload):
    out=ROOT/code/FINAL_VERSION;out.mkdir(parents=True,exist_ok=True)
    req=out/(action+'-request.json');res=out/(action+'-result.json');settings=load_settings()
    if action=='render' and res.exists() and read(res).get('status')=='completed':
        raise RuntimeError('Completed render preserved; use a new version')
    _atomic_json(req,{'action':action,'output_dir':str(out),**payload})
    with (out/(action+'.log')).open('w',encoding='utf-8') as log:
        subprocess.run([str(settings.auto_capcut_python),'-X','utf8','-m','auto_capcut.studio_runner','--request',str(req),'--result',str(res)],cwd=settings.auto_capcut_root,stdout=log,stderr=log,check=True)
    value=read(res);assert value['status']=='completed';return value

def approve_new(code):
    from hotpost.source_presentation import POLICY,review_scope
    from hotpost.source_quality import sha256_file
    out=ROOT/code/'final';sources=read(out/'new-sources-pending.json')
    for s in sources:
        assert sha256_file(Path(s['path']))==s['sha256']
        limits=['검토한 브랜드·제품 형태·착용 상황의 예시. 원작과 동일 SKU, 현재 판매가·재고·AS 및 실제 화자 경험은 입증하지 않음.']
        s.update(pending_visual_review=False,editing_eligible=True,source_quality='reviewed-portrait',blur_required=False,
                 watermark_masks=[],presentation_review_required=False,relevance_review_required=False)
        s['functional_review']={'reviewed':True,'source_sha256':s['sha256'],'same_core_function':True,'context_usable':True,
            'context_usage_limits':limits,'observed_actions':[s['proposed_observation']],
            'evidence_frames':[f['path'] for f in s['evidence_frames']],'reviewer':'codex_session_visual_review'}
        s['visual_review']={'reviewer':'codex_session_visual_review','scope':'actual four bounded derivative frames',
            'evidence_frames':s['evidence_frames'],'observation':s['proposed_observation'],'reviewed_at':time.time()}
        s['presentation_review']={'policy':POLICY,'reviewed':True,'source_sha256':s['sha256'],'scope':review_scope(s),
            'usable':True,'quality_usable':True,'action_preserved':True,'observations':[s['proposed_observation']],
            'evidence_frames':s['evidence_frames'],'reviewer':'codex_session_visual_review'}
    _atomic_json(out/'new-sources-approved.json',sources)

def plan(code):
    from hotpost.source_quality import sha256_file
    from hotpost.script_rewriter import _generate
    from hotpost.scene_analysis import RANK_INSTRUCTION
    final=ROOT/code/'final';base=read(ROOT/code/'baseline.json');sources=[]
    if code in CLIPS:
        sources=read(final/'new-sources-approved.json')
        if code=='DeJ7hD6zsnR':
            old=read('data/tiktok-rework-20261011/DeJ7hD6zsnR/final/approved-sources.json')
            sources.extend(s for s in old if s['name'] in ('beige','beige-fit'))
        else:
            sources.extend(s for s in base['plan']['sources'] if s['id']=='daily-jacket-kid-front')
    else:
        sources=copy.deepcopy(base['plan']['sources'])
        if code=='DeTaESASnr_':
            sources=[s for s in sources if not s['id'].endswith(('panels','wood-room','photo'))]
    for s in sources:assert sha256_file(Path(s['path']))==s['sha256']
    _atomic_json(final/'source-pool.json',sources)
    if (final/'prepared-plan.json').exists():return
    p=boundary(code,'analyze',sources=sources,script=read(final/'script.json'),voice=read(final/'voice.json'))['plan']
    p['cover_spec']['lines']=read(final/'script.json')['thumbnail_lines']
    by_id={s['id']:s for s in sources}
    # Whole bounded clips have already been read; their observation receipt is
    # the semantic catalog, rather than repeated filename-based inference.
    for shot in p['shots']:
        source=by_id[shot['source_id']];shot['observation']='; '.join(source['functional_review']['observed_actions'])
        shot.update(evidence_status='actual-decoded-frame-review',source_role=source.get('source_role','core'),
            context_usage_limits=source['functional_review'].get('context_usage_limits',[]),
            parent_original_sha256=source.get('original_sha256') or source['sha256'])
    rank=_generate(load_settings(),RANK_INSTRUCTION.replace('up to 3 distinct','up to 6 distinct')+
        ' Logo-only macro shots are absent intentionally. Prefer actual whole product, wear/use and distinct garment silhouettes. Return all suitable alternatives up to six. Do not force different parents when their objects conflict with narration.',
        {'beats':[{k:b[k] for k in ('id','text','start','end')} for b in p['beats']],
         'shots':[{k:s.get(k) for k in ('id','observation','source_role','context_usage_limits','parent_original_sha256')} for s in p['shots']]},media=[])
    rows={b['id']:b for b in rank['beats']};ids={s['id'] for s in p['shots']}
    for beat in p['beats']:
        row=rows[beat['id']];options=[{**o,'reviewed':True} for o in row['options'] if o['shot_id'] in ids and o.get('action_match')!='opposite']
        assert options,'No supported source alternatives'
        beat.update(options=options,emphasis=0);beat.pop('selected_shot_id',None)
    _atomic_json(final/'semantic-selection.json',rank);_atomic_json(final/'selection-input.json',p)
    settings=load_settings()
    program='from pathlib import Path;import json,sys;from auto_capcut.core.studio_timeline import select_shots;p=select_shots(json.loads(Path(sys.argv[1]).read_text("utf-8")));Path(sys.argv[2]).write_text(json.dumps(p,ensure_ascii=False,indent=2),"utf-8")'
    subprocess.run([str(settings.auto_capcut_python),'-X','utf8','-c',program,str(final/'selection-input.json'),str(final/'prepared-plan.json')],cwd=settings.auto_capcut_root,check=True)
    p=read(final/'prepared-plan.json');print(code,json.dumps([(b['id'],b['text'],b['selected_shot_id'],round(b['end']-b['start'],2)) for b in p['beats']],ensure_ascii=False),p['footage_diversity'],flush=True)

def strict_plan(code):
    """Session-reviewed semantics; allocate only complete unused motion windows."""
    final=ROOT/code/FINAL_VERSION
    path=final/'selection-input.json'
    p=read(path if path.exists() else final/'analysis-plan.json')
    if not (final/'cover-copy-revision.json').exists():
        p['cover_spec']['lines']=read(ROOT/code/'final/script.json')['thumbnail_lines']
    choices={
      'DeTJ6HbKCdF':[[7,9,1],[14,3,1],[1,14],[14,1],[20,10],[18,20],[2,4],[7,9],[13],[6],[15],[16,19],[20,14],[9,7,16],[19,16,9],[7,9,19],[9,19,7]],
      'DeSvpmAsWgZ':[[5,1,3],[5],[1,3,4],[6,2,4],[4,1,6],[2,6,3],[1,4,2],[3,4],[4,3],[2,6],[3,1,4],[1,2,6],[2,6,4],[5,3,1],[7],[7,6,2],[6,2,4],[6,2,4]],
      'DeJ7hD6zsnR':[[9],[9],[4,2,5],[6,5,2],[3,4,6],[5,3,4],[7],[3,4,2],[1,3,4],[7],[8],[3,4,5],[5,6,2],[2,4,6],[3,4,6],[3,4,6]],
    }
    by_source={s['id']:s for s in p['sources']}
    for shot in p['shots']:
        s=by_source[shot['source_id']]
        shot['observation']='; '.join(s['functional_review']['observed_actions'])
        shot['context_usage_limits']=s['functional_review'].get('context_usage_limits',[])
        # First part has no product; beige hanger starts on another jacket.
        if code=='DeJ7hD6zsnR' and shot['source_id'].endswith('pink-held'):shot['start']=max(shot['start'],2.6)
        if code=='DeJ7hD6zsnR' and shot['source_id'].endswith('pink-zip'):shot['start']=max(shot['start'],3.2)
        if code=='DeJ7hD6zsnR' and s.get('name')=='beige':shot['start']=max(shot['start'],1.6)
        if code=='DeTJ6HbKCdF' and shot['source_id']==p['sources'][14]['id']:shot['start']=max(shot['start'],.75)
    if p.get('session_options_ready'):
        pass
    elif code in choices:
        for b,indices in zip(p['beats'],choices[code],strict=True):
            b['options']=[{'shot_id':s['id'],'relation':'context' if code!='DeTJ6HbKCdF' else 'direct',
                'reason':'실제 검토한 제품 형태·착용/동작이 이 대사와 모순되지 않는 구간','reviewed':True}
                for i in indices for s in p['shots'] if s['source_id']==p['sources'][i-1]['id']]
    else:
        # A closed product can contextualize the opening question and CTA;
        # these lines do not assert a visible key-picking movement.
        for n in (0,15,16):
            for i in (3,4,5,6,10,13,14):
                sid=f'shot-{i}-1'
                if not any(o['shot_id']==sid for o in p['beats'][n]['options']):
                    p['beats'][n]['options'].append({'shot_id':sid,'relation':'context','reason':'설치된 제품 활용 상황','reviewed':True})
        p['beats'][12]['options']=[o for o in p['beats'][12]['options'] if o['shot_id']!='shot-9-1']
    shots={s['id']:s for s in p['shots']};used={};screen={};chosen=[];visits=0
    def windows(a,z,seen):
        cursor=a;out=[]
        for lo,hi in sorted(seen):
            if hi<=cursor or lo>=z:continue
            if lo>cursor:out.append((cursor,min(lo,z)))
            cursor=max(cursor,hi)
        if cursor<z:out.append((cursor,z))
        return out
    def solve(index,last=None):
        nonlocal visits
        visits+=1
        if visits>200000:raise RuntimeError('No bounded assignment in search budget')
        if index==len(p['beats']):return True
        b=p['beats'][index];length=b['end']-b['start'];rows=[]
        for j,o in enumerate(b['options']):
            s=shots[o['shot_id']];source=by_source[s['source_id']]
            key=source.get('original_sha256') or s['sha256'];offset=source.get('original_interval',{}).get('start',0) if source.get('original_sha256') else 0
            for lo,hi in windows(s['start']+offset,s['end']+offset,used.get(key,[])):
                if hi-lo+1e-6<length:continue
                cost={'direct':0,'context':1,'illustration':2}.get(o['relation'],3)+2*(key==last)+screen.get(key,0)/p['duration']
                rows.append((cost,j,o,s,key,lo,lo+length,offset))
        for _,_,o,s,key,lo,hi,offset in sorted(rows,key=lambda r:r[:2]):
            used.setdefault(key,[]).append((lo,hi));screen[key]=screen.get(key,0)+length;chosen.append((o,s,lo-offset,hi-offset))
            if solve(index+1,key):return True
            chosen.pop();used[key].pop();screen[key]-=length
        return False
    assert solve(0),'Collect more semantically valid sources; no freeze/replay fallback'
    for b,(o,s,a,z) in zip(p['beats'],chosen,strict=True):
        b.update(selected_shot_id=s['id'],relation=o['relation'],reason=o['reason'],needs_review=False,source_start=a,source_end=z,emphasis=0)
    # Renderer re-selects locked IDs; assert its allocation remains identical.
    settings=load_settings();_atomic_json(final/'strict-selection-input.json',p)
    program='import json,sys;from pathlib import Path;from auto_capcut.core.studio_timeline import select_shots;p=select_shots(json.loads(Path(sys.argv[1]).read_text("utf-8")));Path(sys.argv[2]).write_text(json.dumps(p,ensure_ascii=False,indent=2),"utf-8")'
    subprocess.run([str(settings.auto_capcut_python),'-X','utf8','-c',program,str(final/'strict-selection-input.json'),str(final/'prepared-plan.json')],cwd=settings.auto_capcut_root,check=True)
    result=read(final/'prepared-plan.json');assert not result['footage_diversity']['frozen_beats'] and result['footage_diversity']['replayed_seconds']<=.001
    _atomic_json(final/'session-semantic-receipt.json',{'reviewer':'codex_session','basis':'actual bounded frames and product/action observations','backtracking_visits':visits,'common_rules_updated':False})
    print(code,result['footage_diversity'],flush=True)

def covers(code):
    from PIL import Image,ImageDraw
    p=read(ROOT/code/FINAL_VERSION/'prepared-plan.json');rows=boundary(code,'cover-candidates',plan=p)['candidates']
    for start in range(0,len(rows),12):
        batch=rows[start:start+12];sheet=Image.new('RGB',(720,350*((len(batch)+3)//4)),'#222');d=ImageDraw.Draw(sheet)
        for i,row in enumerate(batch):
            im=Image.open(row['frame_path']);im.thumbnail((180,320));x=(i%4)*180;y=(i//4)*350;sheet.paste(im,(x,y+25));d.text((x,y),f"{start+i}: {row['shot_id']} {row['timestamp']:.2f}",fill='white')
        sheet.save(ROOT/code/FINAL_VERSION/f'cover-sheet-{start//12}.jpg',quality=95)
    print(code,len(rows),'cover samples',flush=True)

def render(code):
    p=read(ROOT/code/FINAL_VERSION/'prepared-plan.json');assert p['cover_spec']['source']['reviewed']
    result=boundary(code,'render',plan=p);print(code,result['preview_path'],flush=True)

if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['snapshot','write','discover','search_kids','inventory','download','repair_triplet','voice','clips','approve_new','plan','strict_plan','covers','render']);p.add_argument('--code',choices=WORKS);p.add_argument('--index',type=int,default=0);p.add_argument('--version',default='final',choices=['final','final-v2','final-v3','final-v4']);args=p.parse_args();FINAL_VERSION=args.version
    if args.action=='snapshot':snapshot()
    elif args.action=='download':download(args.code,args.index)
    elif args.action=='voice':voice(args.code,args.index)
    else:globals()[args.action](args.code)
