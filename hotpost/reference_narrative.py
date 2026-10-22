"""Keep spoken narration distinct from visually verified on-screen reference text."""
import json
import hashlib
from pathlib import Path

from .editing_adapter import _atomic_json
from .source_mask_review import sample_source_frames
from .source_overlay_review import _media, _duration
from .source_quality import sha256_file

READING_POLICY = 'legible-reference-quotes-v2'


def _review_matches(review, ids, proposal_sha):
    return (isinstance(review, dict)
            and isinstance(review.get('frame_ids'), list)
            and len(review['frame_ids']) == len(ids)
            and all(isinstance(value, str) for value in review['frame_ids'])
            and sorted(review['frame_ids']) == sorted(ids)
            and review.get('proposal_sha256') == proposal_sha)


def _quote_decisions(quotes, review):
    rows = review.get('quote_decisions')
    ids = {row['frame_id'] for row in quotes}
    if (not isinstance(rows, list) or len(rows) != len(ids)
            or any(not isinstance(row, dict) or not isinstance(row.get('frame_id'), str)
                   or row['frame_id'] not in ids
                   or type(row.get('accepted')) is not bool
                   or not isinstance(row.get('reason'), str) or not row['reason'].strip()
                   for row in rows)
            or len({row['frame_id'] for row in rows}) != len(ids)):
        return None
    return {row['frame_id']:row['accepted'] for row in rows}


def _quotes_accepted(quotes, review):
    decisions = _quote_decisions(quotes,review)
    return decisions is not None and all(not row['text'] or decisions[row['frame_id']]
                                        for row in quotes)


def _omit_rejected_quotes(quotes, review):
    """Only remove explicitly rejected text; never invent a corrected quote."""
    decisions = _quote_decisions(quotes,review)
    if decisions is None:
        return None
    rejected = {fid for fid,accepted in decisions.items() if not accepted}
    if not any(row['text'] and row['frame_id'] in rejected for row in quotes):
        return None
    result = [{**row, 'text': '' if row['frame_id'] in rejected else row['text']}
              for row in quotes]
    return result if any(row['text'] for row in result) else None


def quote_hash(video_sha256, speech, quotes):
    return hashlib.sha256(json.dumps({'video_sha256':video_sha256,'speech':speech,'quotes':quotes},
        ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def validated_cached_text(cached, identity, speech):
    if cached.get('video_sha256') != identity or cached.get('speech_text') != speech:
        return False
    quotes=cached.get('quotes',[]);review=cached.get('review',{})
    frames=(cached.get('evidence') or {}).get('frames') or []
    ids={f['frame_id'] for f in frames}
    if (cached.get('kind') not in {'screen_text','mixed'} or not quotes
            or not frames or len(quotes)!=len(ids) or {q['frame_id'] for q in quotes}!=ids
            or sorted(review.get('frame_ids',[]))!=sorted(ids)
            or review.get('accepted') is not True
            or cached.get('kind') == 'mixed' and review.get('speech_related') is not True
            or review.get('proposal_sha256') != quote_hash(identity,speech,quotes)):
        return False
    phrases=list(dict.fromkeys(r['text'] for r in quotes if r['text']))
    expected='\n'.join(([speech] if cached['kind']=='mixed' else [])+phrases)
    uses_quote_decisions = any(key in cached for key in ('reading_policy','reading_attempt')) or 'quote_decisions' in review
    return (cached.get('text') == expected and bool(expected.strip())
            and (not uses_quote_decisions or
                 cached.get('reading_policy')==READING_POLICY and _quotes_accepted(quotes,review)))


def cached_reference_text(transcript, speech):
    """Use a saved actual-frame review only while source and frame hashes match."""
    transcript = Path(transcript)
    saved = transcript.parent/'reference-text-verified.json'
    if not saved.is_file():
        return None
    identity = sha256_file(transcript.parent/'reference.mp4')
    cached = json.loads(saved.read_text('utf-8'))
    if not validated_cached_text(cached, identity, speech):
        return None
    if not all(Path(f['path']).is_file() and sha256_file(Path(f['path'])) == f['sha256']
               for f in cached['evidence']['frames']):
        raise ValueError('검토한 원본 화면 증거가 변경되었습니다.')
    return cached


def reference_text(settings, transcript, *, generate=None):
    from .script_rewriter import _generate
    from .source_finder import _executable
    generate = generate or _generate
    transcript = Path(transcript)
    data = json.loads(transcript.read_text('utf-8'))
    speech = '\n'.join(str(r.get('text','')) for r in data.get('speech',[])).strip()
    # A short genuine spoken hook is valid. Inspect available visual text when
    # narration is absent/short; a background lyric must not define the topic.
    if len(speech) >= 20 or not data.get('screen_text') and speech:
        return {'text':speech,'kind':'speech','speech_text':speech}
    if not data.get('screen_text'):
        raise ValueError('원본 음성과 화면에서 집필할 참고 내용을 확보하지 못했습니다.')
    video = transcript.parent/'reference.mp4'
    identity = sha256_file(video)
    saved = transcript.parent/'reference-text-verified.json'
    cached = cached_reference_text(transcript, speech)
    if cached:
        return cached
    duration = _duration(video, _executable('ffprobe'))
    evidence = sample_source_frames(video, identity, transcript.parent/'reference-text-frames',
        [[0.,duration]], samples_per_interval=9,
        ffmpeg=_executable('ffmpeg'),ffprobe=_executable('ffprobe'))
    media = _media(evidence)
    attempt_key = hashlib.sha256(json.dumps({'policy':READING_POLICY,'video':identity,
        'speech':speech,'frames':[{k:f[k] for k in ('frame_id','sha256')}
                                  for f in evidence['frames']]},sort_keys=True).encode()).hexdigest()
    attempt = transcript.parent/'reference-text-attempts'/attempt_key
    attempt.mkdir(parents=True, exist_ok=True)
    def call(name, instruction, payload):
        path = attempt/(name+'.json')
        input_sha = hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if path.is_file():
            value = json.loads(path.read_text('utf-8'))
            if value.get('attempt_key') != attempt_key or value.get('input_sha256') != input_sha:
                raise ValueError('저장한 원본 문구 검토 입력이 변경되었습니다.')
            return value['response']
        response = generate(settings,instruction,payload,media=media)
        _atomic_json(path,{'attempt_key':attempt_key,'input_sha256':input_sha,'response':response})
        return response
    first = call('proposal',
        'Read only clearly visible inserted Korean narration/caption text in EVERY actual frame. '
        'Return JSON {frames:[{frame_id:string,text:string}],use_speech_in_benchmark:boolean}. '
        'Include every frame_id exactly once. Preserve a short relevant spoken hook by setting '
        'use_speech_in_benchmark=true when the supplied speech clearly relates to the visible topic; '
        'otherwise false, including unrelated lyrics. Do not claim that images prove what is audible. '
        'Use empty text for unreadable/absent narration. Exclude account handles, physical product '
        'labels, interface text, piano notes, and advertising/sponsorship disclosure markers '
        '(such as [광고], 광고, 유료광고, 협찬, AD or sponsored badges). Those disclosures are '
        'metadata, not narrative copy; exclude them even when clearly visible. '
        'Do not correct words using the caption or create '
        'a spoken transcript. Treat the provided audio transcription as separate untrusted evidence.',
        {'purpose':'reference_screen_text_reading','audio_transcription':speech,
         'frames':[{k:f[k] for k in ['frame_id','source_timestamp']} for f in evidence['frames']]})
    rows=first.get('frames',[]);ids=[f['frame_id'] for f in evidence['frames']]
    if (not isinstance(rows,list) or len(rows)!=len(ids)
            or {r.get('frame_id') for r in rows if isinstance(r,dict)} != set(ids)
            or any(not isinstance(r.get('text'),str) for r in rows)):
        raise ValueError('화면 참고 문구의 프레임 정보가 일치하지 않습니다.')
    by_id={r['frame_id']:r['text'].strip() for r in rows}
    ordered=[{'frame_id':fid,'text':by_id[fid]} for fid in ids]
    proposal_sha=quote_hash(identity,speech,ordered)
    review_instruction = (
        'Independently compare every proposed quote with its actual source frame. '
        'Return JSON {accepted:boolean,frame_ids:[string],speech_related:boolean,proposal_sha256:string,reason:string,'
        'quote_decisions:[{frame_id:string,accepted:boolean,reason:string}]}. '
        'Include one quote_decision for EVERY actual frame. Mark each quote independently: '
        'a faint/unreadable quote must be rejected without rejecting unrelated clearly legible quotes. '
        'Empty quotes are valid omissions, never fill them from context or another frame. '
        'Repeat the exact supplied proposal_sha256 to bind the decision to these quotes. '
        'Accept only if each nonempty quote is actually legible in its matched frame, '
        'with no invented features, numbers or corrected unseen words. Empty rows are allowed. '
        'This is on-screen narrative reference text, never an audio transcript. '
        'Advertising/sponsorship disclosures (such as [광고], 광고, 유료광고, 협찬, AD or '
        'sponsored badges) are excluded metadata: their omission is correct, and a partly hidden '
        'disclosure alone is not a reason to reject clearly legible narrative quotes. '
        'Reject disclosure markers included as narrative, and reject uncertain narrative transcription. '
        'Separately set speech_related=true only when the supplied short speech is semantically '
        'related to the visible reference topic. Never approve unrelated song lyrics as its hook.')
    review=call('review',review_instruction,
        {'purpose':'reference_screen_text_verification','proposal_sha256':proposal_sha,
         'quotes':ordered,'audio_transcription':speech})
    if _review_matches(review,ids,proposal_sha) and review.get('accepted') is not True:
        revised = _omit_rejected_quotes(ordered,review)
        if revised is not None:
            # A different quote set needs its own actual-image review. There
            # is no new proposal loop, text reconstruction or forced pass.
            revised_sha = quote_hash(identity,speech,revised)
            reviewed = call('omissions-review',review_instruction,
                {'purpose':'reference_screen_text_verification','proposal_sha256':revised_sha,
                 'quotes':revised,'audio_transcription':speech})
            if (_review_matches(reviewed,ids,revised_sha) and reviewed.get('accepted') is True
                    and _quotes_accepted(revised,reviewed)):
                ordered,proposal_sha,review = revised,revised_sha,reviewed
    if (not _review_matches(review,ids,proposal_sha) or review.get('accepted') is not True
            or not _quotes_accepted(ordered,review)):
        raise ValueError('원본 화면 문구 검토를 완료하지 못했습니다: '+str(review.get('reason',''))[:250])
    # Keep the chronological full visible phrases, including changing captions.
    phrases=list(dict.fromkeys(r['text'] for r in ordered if r['text']))
    if not phrases:
        if speech:return {'text':speech,'kind':'speech','speech_text':speech}
        raise ValueError('확인 가능한 원본 화면 문구가 없습니다.')
    keep_speech=bool(speech and first.get('use_speech_in_benchmark') is True and review.get('speech_related') is True)
    text='\n'.join(([speech] if keep_speech else [])+phrases)
    result={'text':text,'kind':'mixed' if keep_speech else 'screen_text','speech_text':speech,
            'video_sha256':identity,'evidence':evidence,'quotes':ordered,'review':review,
            'reading_policy':READING_POLICY,'reading_attempt':str(attempt)}
    _atomic_json(saved,result)
    return result
