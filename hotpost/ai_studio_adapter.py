"""Google AI Studio whole-script browser TTS boundary; import performs no I/O.

The caller owns the logged-in browser. The agent uses the existing logged-in Chrome profile; no API-key discovery,
local model, browser daemon or HTTP TTS service is used.
"""
from __future__ import annotations

import hashlib
import io
import json
import wave
from pathlib import Path
from typing import Any
from uuid import uuid4

from dataclasses import dataclass

@dataclass
class SpeechRequest:
    text: str
    output: Path
    language: str = "ko"
    continuation: dict | None = None


def _fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def prepare_browser_request(
    request: SpeechRequest, *, model: str, voice_name: str,
    voice_description: str, style: str,
) -> dict[str, Any]:
    """Preserve the entire supplied script without local cloning inputs."""
    values = dict(text=request.text, model=model, voice_name=voice_name,
                  voice_description=voice_description, style=style)
    if any(not isinstance(v, str) or not v.strip() for v in values.values()):
        raise ValueError("Text, model, voice description, voice and style are required")
    if request.language != "ko":
        raise ValueError("This prepared browser route currently expects Korean")
    if request.continuation:
        raise ValueError("AI Studio route requires a whole script, without continuation")
    from .writing.script_style import explicit_expression_issues
    if explicit_expression_issues(request.text):
        raise ValueError('사용자 금지 표현: 괜히 반가워요 — 대본을 수정한 뒤 TTS를 준비하세요.')
    payload = {
        "request_id": str(uuid4()), "provider": "google-ai-studio-browser",
        "profile_name": "사원2", **values,
        "text_sha256": hashlib.sha256(request.text.encode("utf-8")).hexdigest(),
    }
    payload["request_sha256"] = _fingerprint(payload)
    return payload


def accept_browser_result(
    request: SpeechRequest, prepared: dict[str, Any], receipt: dict[str, Any],
    downloaded_wav: Path,
) -> dict[str, Any]:
    """Import only the matching fresh download. This is not HQ/ASR approval."""
    signed = {k: v for k, v in prepared.items() if k != "request_sha256"}
    if prepared.get("request_sha256") != _fingerprint(signed):
        raise ValueError("Prepared request changed")
    if prepared.get("text") != request.text:
        raise ValueError("Engine request no longer matches the submitted script")
    for key in ("request_id", "request_sha256", "text_sha256", "provider",
                "profile_name", "model", "voice_name", "voice_description", "style"):
        if receipt.get(key) != prepared.get(key):
            raise ValueError(f"Browser receipt mismatch: {key}")
    if receipt.get("fresh_audio") is not True:
        raise ValueError("A new generated audio source must be observed")
    data = Path(downloaded_wav).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if receipt.get("audio_sha256") != digest:
        raise ValueError("Downloaded audio does not match the browser receipt")
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            channels, width, rate, frames, compression, _ = wav.getparams()
            pcm = wav.readframes(frames)
    except (wave.Error, EOFError) as error:
        raise ValueError("AI Studio download is not a PCM WAV") from error
    if (compression != "NONE" or channels != 1 or width != 2 or rate <= 0
            or frames <= 0 or len(pcm) != frames * channels * width):
        raise ValueError("AI Studio WAV is empty, truncated or not mono PCM16")
    if not any(pcm):
        raise ValueError("AI Studio WAV contains only digital silence")
    request.output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation preserves an existing result, including on repeated import.
    with request.output.open("xb") as output:
        output.write(data)
    return {
        "adapter": prepared["provider"], "model": prepared["model"],
        "voice_name": prepared["voice_name"], "text_sha256": prepared["text_sha256"],
        "request_sha256": prepared["request_sha256"], "audio_sha256": digest,
        "sample_rate": rate, "duration_seconds": frames / rate,
        "seed_supported": False, "reference_uploaded": False,
        "quality_verified": False,
    }


MODEL = "gemini-3.8-flash-tts"
VOICE = "Arlo"
VOICE_DESCRIPTION = "Confident and clear., Deep pitch"
STYLE = 'Native standard Seoul Korean adult male speaking to an adult friend about a practical home improvement. Grounded, natural and clear conversational delivery at a comfortable medium pace. A small curious lift on the opening, then a relaxed, confident finish. Keep the selected voice natural; do not force a deeper register. Avoid exaggerated excitement, sing-song intonation, advertising-host theatrics, comic reactions, whispering and shouting. Read only the exact provided Korean script.'


def verify_wav(payload: bytes) -> dict:
    try:
        with wave.open(io.BytesIO(payload), 'rb') as wav:
            frames, rate = wav.getnframes(), wav.getframerate()
            channels, width = wav.getnchannels(), wav.getsampwidth()
            pcm = wav.readframes(frames)
            if not frames or rate <= 0 or len(pcm) != frames * channels * width or not any(pcm):
                raise ValueError('empty or truncated PCM')
            return dict(duration=frames/rate, sample_rate=rate, channels=channels, sample_width=width)
    except (wave.Error, EOFError, ValueError) as exc:
        raise RuntimeError('Google AI Studio WAV가 비어 있거나 손상됐습니다.') from exc


class AiStudioPending(RuntimeError):
    """The agent continues this exact request in Chrome; never auto-resubmit."""
    def __init__(self, prepared_path, request_id):
        self.prepared_path, self.request_id = str(prepared_path), request_id
        super().__init__(f'Chrome 사원2의 AI Studio에서 이 요청을 이어 실행하세요: {prepared_path}')


class AiStudioAdapter:
    """Reuse the job's request/receipt files; the browser is owned by the agent.

    Python cannot operate the agent's Chrome tool. It prepares or validates the
    result and reports a concrete pending request instead of launching a browser
    service or pretending synthesis finished. The production agent submits and
    downloads via tools/ai_studio_browser.mjs, then calls this same method again.
    """
    def __init__(self, settings=None):
        self.settings = settings

    def voices(self):
        return {'voices':[{'id':VOICE,'name':VOICE,'gender':'male','model':MODEL,
                           'available':True}], 'default_voice':VOICE}

    def default_voice_status(self):
        return {'ready':True,'default_voice_kind':'preset','voice_name':VOICE,
                'provider':'google-ai-studio-browser','browser_verified':False,
                'message':'Arlo 설정됨 · 실제 Chrome 로그인/생성 준비는 제출 직전에 확인', 'errors':[]}

    def preview(self, voice_id):
        raise ValueError('현재 작업의 AI Studio 생성 WAV를 사용하세요.')

    def synthesize(self, text, output_path, *, request_id=None, generation_key=None,
                   on_submitted=None, progress=None, before_save=None,
                   voice_profile_id=None, retry_failed=False):
        if not isinstance(text, str) or not text.strip():
            raise ValueError('전체 선택 원고가 필요합니다.')
        if voice_profile_id not in (None, '', VOICE):
            raise ValueError('확정 목소리는 Arlo입니다.')
        if retry_failed:
            raise ValueError('실패 요청은 자동 재제출하지 않습니다. 같은 탭의 결과부터 확인하세요.')
        output = Path(output_path).resolve()
        folder = output.with_suffix('.ai-studio')
        folder.mkdir(parents=True, exist_ok=True)
        prepared_path, result_path = folder/'prepared.json', folder/'result.json'
        request = SpeechRequest(text=text, output=output)
        if prepared_path.exists():
            prepared = json.loads(prepared_path.read_text(encoding='utf-8'))
            expected = prepare_browser_request(request, model=MODEL, voice_name=VOICE,
                        voice_description=VOICE_DESCRIPTION, style=STYLE)
            if any(prepared.get(k) != v for k,v in expected.items()
                   if k not in ('request_id','request_sha256')):
                raise ValueError('기존 TTS 요청의 원고·화자·설정이 다릅니다. 기존 파일을 보존했습니다.')
            if prepared.get('request_sha256') != _fingerprint({k:v for k,v in prepared.items() if k!='request_sha256'}):
                raise ValueError('기존 AI Studio 요청이 변경됐습니다.')
        else:
            if output.exists() or request_id:
                raise ValueError('이전 TTS 결과/요청은 새 Google 요청으로 자동 대체하지 않습니다.')
            prepared = prepare_browser_request(request, model=MODEL, voice_name=VOICE,
                        voice_description=VOICE_DESCRIPTION, style=STYLE)
            with prepared_path.open('x',encoding='utf-8') as f:
                json.dump(prepared,f,ensure_ascii=False,indent=2)
        if request_id is not None and request_id != prepared['request_id']:
            raise ValueError('저장된 요청 ID가 현재 AI Studio 요청과 다릅니다.')
        if on_submitted:
            on_submitted(prepared['request_id'])
        if result_path.exists():
            result = json.loads(result_path.read_text(encoding='utf-8'))
            if (result.get('request_sha256') != prepared['request_sha256'] or
                    not output.is_file() or hashlib.sha256(output.read_bytes()).hexdigest()!=result.get('audio_sha256')):
                raise ValueError('저장된 TTS 결과가 변경됐습니다.')
            expected_result = {'provider':prepared['provider'],'model':MODEL,
                'voice_name':VOICE,'style':STYLE,'status':'succeeded',
                'seed_supported':False,'segment_count':1}
            if any(result.get(k)!=v for k,v in expected_result.items()):
                raise ValueError('저장된 TTS 결과의 화자·모델·상태가 변경됐습니다.')
            verify_wav(output.read_bytes())
            return result
        receipt_path, download = folder/'browser-receipt.json', folder/'google-download.wav'
        if not receipt_path.is_file() or not download.is_file():
            raise AiStudioPending(prepared_path,prepared['request_id'])
        if before_save:
            before_save()
        meta = accept_browser_result(request,prepared,
                    json.loads(receipt_path.read_text(encoding='utf-8')),download)
        result = {**meta, 'provider':prepared['provider'], 'status':'succeeded',
                  'tts_request_id':prepared['request_id'], 'output_path':str(output),
                  'text':text, 'style':STYLE, 'style_verified':True,
                  'segment_count':1, 'seed':None, 'quality_mode':'google-ai-studio',
                  'audio':verify_wav(output.read_bytes()), 'voice_profile_id':VOICE, 'speech_plan':{'segments':[{'text':text}]}}
        with result_path.open('x',encoding='utf-8') as f:
            json.dump(result,f,ensure_ascii=False,indent=2)
        if progress:
            progress('Google AI Studio Arlo 음성 저장 완료',100)
        return result


def main():
    import argparse
    parser=argparse.ArgumentParser(description='Prepare/import one whole-script Arlo browser TTS request')
    parser.add_argument('--script',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    try:
        result=AiStudioAdapter().synthesize(args.script.read_text(encoding='utf-8').strip(),args.output)
    except AiStudioPending as pending:
        result={'status':'browser_pending','request_id':pending.request_id,
                'prepared_path':pending.prepared_path,'message':str(pending)}
    print(json.dumps(result,ensure_ascii=False,indent=2))




if __name__ == '__main__':
    main()
