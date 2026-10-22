"""One distinct, recorded padding delivery revision; retain the first take."""
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hotpost.config import load_settings
from hotpost.voicebench_adapter import VoiceBenchAdapter
from hotpost.editing_adapter import _atomic_json


def main():
    root=ROOT/'data/approved-mirror-tone-20261016'
    item=next(v for v in json.loads((root/'scripts.json').read_text('utf-8'))['result']['items'] if v['code']=='Dec8wlLhu9N')
    source=next(v for v in item['variants'] if v['number']==3)
    text='아, '+source['text'].replace('무게 부담은 덜고 따뜻하게 입기 좋아요. ','')
    assert len(text)<=230 and text.endswith('댓글에 ‘나도’ 남겨주세요.')
    folder=root/'Dec8wlLhu9N-v2';folder.mkdir(exist_ok=True)
    record=folder/'voice.json';sha=hashlib.sha256(text.encode()).hexdigest()
    if record.exists():
        assert json.loads(record.read_text('utf-8'))['script_sha256']==sha
        return
    _atomic_json(folder/'method.json',{'baseline_request_id':168,'preserved_first_request_id':236,
        'source_variant':3,'text':text,'hypothesis':'Replace the hesitant statement opening with direct viewer address/question; remove repeated benefit summary. '
            'Same engine/reference/seed; no gain, pitch shift or time stretching. Pitch proxies do not prove naturalness.',
        'prior_evidence':'First padding take has lower/narrower estimated F0 than the approved baseline.'})
    submitted=folder/'submission.json'
    request=json.loads(submitted.read_text('utf-8'))['request_id'] if submitted.exists() else None
    receipt=VoiceBenchAdapter(load_settings()).synthesize(text,folder/'narration.wav',
        progress=lambda message,pct:print(pct,message,flush=True),request_id=request,
        on_submitted=lambda value:_atomic_json(submitted,{'request_id':value,'script_sha256':sha}),
        generation_key='mirror-tone16-v2-padding-'+sha,require_personal_clone=True)
    _atomic_json(record,{**receipt,'script_sha256':sha,'script':text,'baseline_request_id':168,
        'audio_sha256':hashlib.sha256((folder/'narration.wav').read_bytes()).hexdigest(),
        'auditory_tone_approved':False,'operational_task_changed':False})


if __name__=='__main__':main()
