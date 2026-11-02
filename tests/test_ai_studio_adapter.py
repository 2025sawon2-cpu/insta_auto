import hashlib
import json
import wave
import io
from pathlib import Path
import pytest
from hotpost.ai_studio_adapter import AiStudioAdapter,AiStudioPending,MODEL,VOICE,STYLE



def valid_wav():
    stream=io.BytesIO()
    with wave.open(stream,'wb') as wav:
        wav.setparams((1,2,24000,0,'NONE','not compressed'));wav.writeframes(b'\x01\x00'*2400)
    return stream.getvalue()


@pytest.mark.parametrize('text', ['쉬는 시간이 괜히 반가워요.', '시간이 괜히\n반가워요.'])
def test_forbidden_script_cannot_prepare_or_resume_tts(tmp_path, text):
    out = tmp_path / 'voice.wav'
    for _ in range(2):
        with pytest.raises(ValueError, match='사용자 금지 표현'):
            AiStudioAdapter().synthesize(text, out)
        assert not out.exists()
        assert not out.with_suffix('.ai-studio').joinpath('prepared.json').exists()


def test_browser_pending_is_one_persisted_whole_request_without_side_effects(tmp_path):
    adapter=AiStudioAdapter();out=tmp_path/'voice.wav';text=' 첫 문장!\n마지막 문장. '
    ids=[]
    for _ in range(2):
        with pytest.raises(AiStudioPending) as pending:
            adapter.synthesize(text,out,on_submitted=ids.append)
        prepared=json.loads(Path(pending.value.prepared_path).read_text('utf-8'))
        assert prepared['text']==text and prepared['model']==MODEL and prepared['voice_name']==VOICE
        assert prepared['style']==STYLE and 'seed' not in prepared
        assert not out.exists()
    assert ids[0]==ids[1]
    with pytest.raises(ValueError,match='원고'):
        adapter.synthesize('다른 원고',out)


def test_import_matches_browser_receipt_then_reuses_only_untampered_result(tmp_path):
    adapter=AiStudioAdapter();out=tmp_path/'voice.wav'
    with pytest.raises(AiStudioPending) as pending:adapter.synthesize('전체 원고. 끝 문장.',out)
    folder=Path(pending.value.prepared_path).parent
    prepared=json.loads((folder/'prepared.json').read_text('utf-8'))
    wav=folder/'google-download.wav'
    with wave.open(str(wav),'wb') as w:
        w.setparams((1,2,24000,0,'NONE','not compressed'));w.writeframes(b'\x01\x00'*2400)
    receipt={k:v for k,v in prepared.items() if k!='text'}
    receipt.update(fresh_audio=True,audio_sha256=hashlib.sha256(wav.read_bytes()).hexdigest())
    (folder/'browser-receipt.json').write_text(json.dumps(receipt),'utf-8')
    result=adapter.synthesize(prepared['text'],out)
    assert result['status']=='succeeded' and result['seed_supported'] is False
    assert result['voice_name']=='Arlo' and result['segment_count']==1
    assert result['quality_verified'] is False and result['seed'] is None
    assert adapter.synthesize(prepared['text'],out)==result
    out.write_bytes(b'tampered')
    with pytest.raises(ValueError,match='변경'):adapter.synthesize(prepared['text'],out)


def test_old_provider_and_manual_retry_cannot_create_a_new_submission(tmp_path):
    a=AiStudioAdapter()
    with pytest.raises(ValueError):a.synthesize('전체.',tmp_path/'old.wav',request_id=17)
    assert not (tmp_path/'old.ai-studio/prepared.json').exists()
    with pytest.raises(ValueError):a.synthesize('전체.',tmp_path/'retry.wav',retry_failed=True)
    with pytest.raises(ValueError):a.synthesize('전체.',tmp_path/'other.wav',voice_profile_id='other')
