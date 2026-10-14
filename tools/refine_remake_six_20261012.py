"""Make the narration's final usage claim agree with the observed solo use."""
import copy,hashlib,json,time
from pathlib import Path
from hotpost.config import load_settings
from hotpost.voicebench_adapter import VoiceBenchAdapter
from hotpost.source_quality import sha256_file
from hotpost.editing_adapter import _atomic_json
from tools import remake_feedback_20261012 as production

code='DeTJ6HbKCdF';root=production.ROOT/code;out=root/'final-v4';out.mkdir(exist_ok=True)
production.FINAL_VERSION='final-v4'
script=copy.deepcopy(production.read(root/'final/script.json'))
script['text']=script['text'].replace('짐을 끌고 온 물건 앞에 그대로 둘러앉는 장면','짐을 끌고 온 물건을 도착한 자리에서 바로 쓰는 모습')
digest=hashlib.sha256(script['text'].encode()).hexdigest()
script.update(id='remake-script-6-v4-'+digest[:12],sha256=digest,thumbnail_lines=['짐 옮기던 물건이','도착하니 식사 자리가?'],created=time.time())
_atomic_json(out/'script.json',script)
_atomic_json(out/'script-revision.json',{'previous_script_id':production.read(root/'final/script.json')['id'],'reason':'실제 한 사람의 테이블 사용 장면을 여럿의 둘러앉는 장면으로 주장하지 않도록 정정','changes':['짐을 끌고 온 물건 앞에 그대로 둘러앉는 장면 → 짐을 끌고 온 물건을 도착한 자리에서 바로 쓰는 모습']})
if not (out/'voice.json').exists():
    submit=out/'voice-submission.json';request=production.read(submit)['request_id'] if submit.exists() else None
    result=VoiceBenchAdapter(load_settings()).synthesize(script['text'],out/'narration.wav',request_id=request,
        on_submitted=lambda i:_atomic_json(submit,{'request_id':i,'script_sha256':digest}),
        generation_key='remake-6-v4-'+digest[:32],require_personal_clone=True,
        progress=lambda m,n:print(m,n,flush=True))
    assert result['speech_plan']['segment_count']==1
    _atomic_json(out/'voice.json',{**result,'id':'remake-voice-6-v4-'+digest[:12],'path':str(out/'narration.wav'),'sha256':sha256_file(out/'narration.wav'),'duration':result['audio']['duration'],'script_id':script['id'],'script_sha256':digest,'created':time.time(),'status':'completed'})
if not (out/'analysis-plan.json').exists():
    p=production.boundary(code,'analyze',sources=production.read(root/'final-v3/timeline.json')['sources'],script=script,voice=production.read(out/'voice.json'))['plan']
    _atomic_json(out/'analysis-plan.json',p)
print([(b['id'],b['text']) for b in production.read(out/'analysis-plan.json')['beats']],flush=True)
