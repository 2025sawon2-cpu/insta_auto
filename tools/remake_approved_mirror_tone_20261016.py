"""Generate preserved voice revisions through the existing official boundaries."""
import hashlib
import json
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from hotpost.config import load_settings
from hotpost.script_rewriter import _generate
from hotpost.voicebench_adapter import VoiceBenchAdapter
from hotpost.writing.contract import snapshot
from hotpost.editing_adapter import _atomic_json


def digest(text): return hashlib.sha256(text.encode('utf-8')).hexdigest()


def main():
    folder=ROOT/'data/approved-mirror-tone-20261016'
    folder.mkdir(exist_ok=True)
    settings=load_settings()
    with closing(sqlite3.connect((ROOT.parent/'VoiceBench/data/voicebench.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)) as db:
        row=db.execute('SELECT original_text,output_path,output_sha256 FROM studio_requests WHERE id=168').fetchone()
    assert row and hashlib.sha256(Path(row[1]).read_bytes()).hexdigest()==row[2]
    baseline={'request_id':168,'product':'현관 은색 슬라이딩 거울·자석 보드','text':row[0],
        'audio_path':row[1],'audio_sha256':row[2], 'confirmed_by_owner':True,
        'confirmation':'2026-10-16 사용자: 승인영상은 거울영상이 맞다'}
    _atomic_json(folder/'approved-baseline.json',baseline)
    audit=ROOT/'data/feedback-title-voice-20261016/voice-audit.json'
    inputs=json.loads(audit.read_text('utf-8'))['actual_requests_inspected']
    inputs=[{'code':code,'request_id':request,'text':next(v for v in inputs if v['request_id']==request)['text']}
            for code,request in [('Dec5bcqyffk',230),('Dec8wlLhu9N',231)]]
    scripts=folder/'scripts.json'
    if not scripts.exists():
        result=_generate(settings,
            'Return JSON {items:[{code,variants:[{number:integer,text:string,changes:string}],selected_number:integer,reason:string}]}. '
            'Produce exactly 3 complete Korean narration revisions for EACH supplied product, retaining all product facts and the same central appeal. '
            'The owner confirmed the mirror speech as the approved speaking-tone baseline. Use its conversational manner and breath flow, '
            'not its product facts, storyline or distinctive sentence templates. This is a delivery revision, not a new product story. '
            'Aim for direct ordinary conversation with warmth: brief viewer address, naturally linked functions and immediate practical benefit. '
            'Remove redundant scene explanation, vague retrospective summaries and low-energy indecisive endings. '
            'Do not add emotional stage directions, excited sales delivery, unsupported claims, prices or experiences. '
            'Keep each complete text under 230 characters and end exactly with 댓글에 ‘나도’ 남겨주세요. '
            'Explain specific changes and select one strongest version for whole-script synthesis. '
            'Keep the three variants and their facts for review; do not insert mirror-specific situations into other products.\n'+snapshot()['prompt'],
            {'purpose':'approved_mirror_tone_revision_20261016','baseline':baseline['text'],'products':inputs})
        assert {i['code'] for i in result['items']}=={i['code'] for i in inputs}
        for item in result['items']:
            assert [v['number'] for v in item['variants']]==[1,2,3]
            assert item['selected_number'] in (1,2,3)
            for variant in item['variants']:
                text=variant['text']
                assert len(text)<=230 and text.endswith('댓글에 ‘나도’ 남겨주세요.')
        _atomic_json(scripts,{'baseline':baseline,'original_inputs':inputs,'result':result,'writing_contract':{
            k:v for k,v in snapshot().items() if k!='prompt'},'created':time.time()})
    result=json.loads(scripts.read_text('utf-8'))['result']
    for item in result['items']:
        target=folder/item['code'];target.mkdir(exist_ok=True)
        variant=next(v for v in item['variants'] if v['number']==item['selected_number'])
        text=variant['text'];text_sha=digest(text)
        record=target/'voice.json'
        if record.exists():
            assert json.loads(record.read_text('utf-8'))['script_sha256']==text_sha
            continue
        _atomic_json(target/'selected-script.json',variant)
        submitted=target/'submission.json'
        request=json.loads(submitted.read_text('utf-8'))['request_id'] if submitted.exists() else None
        receipt=VoiceBenchAdapter(settings).synthesize(text,target/'narration.wav',
            progress=lambda message,pct:print(item['code'],pct,message,flush=True),request_id=request,
            on_submitted=lambda value:_atomic_json(submitted,{'request_id':value,'script_sha256':text_sha}),
            generation_key='mirror-tone16-'+item['code']+'-'+text_sha,require_personal_clone=True)
        _atomic_json(record,{**receipt,'script_sha256':text_sha,'script':text,'baseline_request_id':168,
            'audio_sha256':hashlib.sha256((target/'narration.wav').read_bytes()).hexdigest(),
            'auditory_tone_approved':False,'operational_task_changed':False})
        print(item['code'],'saved',str(record),flush=True)


if __name__=='__main__': main()
