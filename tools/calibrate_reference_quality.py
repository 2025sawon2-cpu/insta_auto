"""Read-only ten-reference calibration; real time-labelled frames, durable reviews."""
import argparse
import hashlib
import json
import math
import re
import time
from pathlib import Path

from PIL import Image, ImageDraw

from hotpost.config import load_settings
from hotpost.daily_quality import REVIEW_INSTRUCTION
from hotpost.editing_adapter import _atomic_json
from hotpost.model_service import ModelServiceUnavailable
from hotpost.operation_progress import run_progress_command
from hotpost.source_finder import _executable, probe_video
from hotpost.source_quality import sha256_file
from hotpost.studio import Studio
from hotpost.visual_media import review_frame_data

CASES = [
    ('DeWWWOeDhGk', '주방 매트', 'calibration'),
    ('DeRFXHpEwck', '미니 파일 홀더', 'calibration'),
    ('DeXut7fTAxb', '폴로 니트', 'calibration'),
    ('DeYveh9yeCq', '모듈형 충전기', 'calibration'),
    ('DeXupxVztwJ', '틈새 청소 도구', 'calibration'),
    ('DeVUQRZqKRM', '캠핑 테이블 박스', 'calibration'),
    ('DeXs0K5S52W', '접이식 벽 행거', 'holdout'),
    ('DeYZSuUyzzX', '자석 도어 스토퍼', 'holdout'),
    ('DeY776gqIQw', '반려동물 공기청정기', 'holdout'),
    ('DeWPBQyzpfR', '자동 타코야끼 기계', 'holdout'),
]


def root(settings):
    path = settings.data_dir / 'reference-calibration-20261013-v2-native'
    path.mkdir(exist_ok=True)
    return path


def prepare(settings):
    out = root(settings)
    if (out / 'selection.json').exists():
        raise ValueError('Selection already saved; preserve its original snapshot')
    report_path = settings.data_dir / 'report.json'
    report = json.loads(report_path.read_text('utf-8'))
    posts = {p['shortcode']: p for p in report['posts'] if p.get('tier', 0) >= 1}
    studio = Studio(settings, workers=False)
    tasks = {t['shortcode']: t for t in studio.store.list()}
    records = []
    for code, product, role in CASES:
        post, task = posts[code], tasks[code]
        video = Path(task['reference_video'])
        transcript = Path(task.get('transcript_path') or video.with_name('transcript.json'))
        assert video.is_file() and transcript.is_file()
        text = json.loads(transcript.read_text('utf-8'))
        speech = text.get('speech') or []
        rows = speech or text.get('screen_text') or []
        assert rows, code
        meta = probe_video(video)
        folder = out / code
        folder.mkdir(exist_ok=True)
        frames = folder / 'frames'
        frames.mkdir(exist_ok=True)
        result = run_progress_command([
            str(_executable('ffmpeg')), '-nostdin', '-v', 'info', '-progress', 'pipe:1', '-nostats',
            '-i', str(video), '-vf', "setpts=PTS-STARTPTS,select='isnan(prev_selected_t)+gte(t-prev_selected_t,0.5)',showinfo,scale=360:640:force_original_aspect_ratio=decrease,pad=360:640:(ow-iw)/2:(oh-ih)/2",
            '-fps_mode', 'vfr',
            '-q:v', '2', str(frames / '%04d.jpg')], idle_seconds=60)
        if result.returncode:
            raise RuntimeError(result.stderr[-1000:])
        # Source PTS, normalized to its actual first frame, before scale/pad.
        # No invented output-fps timestamps; no proof of an unobserved action.
        times = [float(t) for t in re.findall(r'\bpts_time:([\d.eE+-]+)', result.stderr)]
        paths = sorted(frames.glob('*.jpg'))
        assert len(times) == len(paths) and times and times[0] == 0, (code, len(times), len(paths))
        samples = [{'path': str(p.resolve()), 'time': t, 'sha256': sha256_file(p)}
                   for p, t in zip(paths, times)]
        sheets = []
        for offset in range(0, len(samples), 12):
            batch = samples[offset:offset + 12]
            sheet = Image.new('RGB', (1440, math.ceil(len(batch) / 4) * 664), 'white')
            draw = ImageDraw.Draw(sheet)
            for i, row in enumerate(batch):
                x, y = (i % 4) * 360, (i // 4) * 664
                with Image.open(row['path']) as frame:
                    sheet.paste(frame.convert('RGB'), (x, y + 24))
                draw.text((x + 8, y + 4), f"{code} | t={row['time']:.2f}s", fill='black')
            path = folder / f'sequence-{offset // 12:02d}.jpg'
            sheet.save(path, quality=94)
            sheets.append({'path': str(path.resolve()), 'sha256': sha256_file(path),
                           'start': batch[0]['time'], 'end': batch[-1]['time']})
        # True source first frame, independent of fps resampling and later body imagery.
        first = folder / 'first-frame.jpg'
        result = run_progress_command([str(_executable('ffmpeg')), '-nostdin', '-v', 'error', '-progress', 'pipe:1',
            '-nostats', '-i', str(video), '-frames:v', '1', '-vf', 'scale=540:-2', '-q:v', '2', str(first)], idle_seconds=60)
        if result.returncode:
            raise RuntimeError(result.stderr[-1000:])
        record = {'shortcode': code, 'product': product, 'role': role, 'tier': post['tier'],
                  'rank_score': post.get('rank_score'), 'task_id': task['id'],
                  'reference_url': post.get('url') or text.get('reference_url'),
                  'video_path': str(video.resolve()), 'video_sha256': sha256_file(video),
                  'duration': meta['duration'], 'transcript_path': str(transcript.resolve()),
                  'transcript_sha256': sha256_file(transcript), 'caption': post.get('caption') or '',
                  'narration_source': 'speech' if speech else 'screen_text',
                  'narration': task.get('reviewed_original_text') or task.get('original_text') or '\n'.join(r['text'] for r in rows),
                  'timed_text': [{**r, 'id': f'ref-{i + 1}'} for i, r in enumerate(rows)],
                  'first_frame': {'path': str(first.resolve()), 'sha256': sha256_file(first)},
                  'samples': samples, 'sheets': sheets}
        _atomic_json(folder / 'evidence.json', record)
        records.append({'shortcode': code, 'product': product, 'role': role, 'evidence_path': str((folder / 'evidence.json').resolve())})
        print(json.dumps({'prepared': code, 'product': product, 'role': role, 'duration': meta['duration'], 'frames': len(samples)}, ensure_ascii=False), flush=True)
    _atomic_json(out / 'selection.json', {'created': time.time(), 'report_generated_at_kst': report['generated_at_kst'],
        'report_sha256': sha256_file(report_path), 'current_hot_count': len(posts), 'selection': records,
        'selection_reason': 'Different product categories, story/supportive imagery and direct demonstration; six development cases and four untouched holdouts'})
    _atomic_json(out / 'strict-policy.json', {'instruction': REVIEW_INSTRUCTION, 'sha256': hashlib.sha256(REVIEW_INSTRUCTION.encode()).hexdigest()})


def review(settings, code, policy):
    out = root(settings)
    selection = json.loads((out / 'selection.json').read_text('utf-8'))
    selected = next(r for r in selection['selection'] if r['shortcode'] == code)
    evidence = json.loads(Path(selected['evidence_path']).read_text('utf-8'))
    if policy == 'strict':
        instruction = json.loads((out / 'strict-policy.json').read_text('utf-8'))['instruction']
    else:
        frozen = json.loads((out / 'calibrated-policy.json').read_text('utf-8'))
        instruction = frozen['instruction']
    if selected['role'] == 'holdout' and not (out / 'calibrated-policy.json').is_file():
        raise ValueError('Freeze the calibration rule before looking at holdouts')
    target = out / code / f'{policy}-review.json'
    if target.exists():
        print(json.dumps({'code': code, 'policy': policy, 'status': 'already_completed'}));return
    for key in ('video', 'transcript'):
        if sha256_file(Path(evidence[key + '_path'])) != evidence[key + '_sha256']:
            raise ValueError('Source evidence changed')
    media = []
    for label, row in [('Actual separate source first frame; do not infer a thumbnail from the body sequence', evidence['first_frame']),
                       *[(f"Actual source BODY sequence at labelled sample times {r['start']}..{r['end']}s; read left-to-right, top-to-bottom", r) for r in evidence['sheets']]]:
        if sha256_file(Path(row['path'])) != row['sha256']:
            raise ValueError('Frame evidence changed')
        img = review_frame_data(row['path'])
        media.extend([{'text': label}, {'inlineData': {'mimeType': img['mimeType'], 'data': img['data']}}])
    data = {'purpose': 'actual_current_hot_reference_review', 'shortcode': code, 'product': evidence['product'],
            'script': evidence['narration'], 'original_text': evidence['narration'], 'original_caption': evidence['caption'],
            'narration_source': evidence['narration_source'], 'duration': evidence['duration'],
            'all_beats': evidence['timed_text'], 'beats': evidence['timed_text'],
            'detailed_beat_ids': [b['id'] for b in evidence['timed_text']],
            'sampling': 'Actual video across the whole duration at 2 samples per second. Sampled frames cannot prove unseen motion; ambiguous observations must stay uncertain.',
            'evidence_scope': 'This is the ORIGINAL reference, not a generated remake. Timed speech may have ASR errors; screen_text is OCR, never audio. Do not invent auditory listening or treat recognition spelling errors as author factual errors.',
            'first_frame_scope': 'Only the separate true first-frame image is source first frame. Instagram separately uploaded poster art was not supplied.',
            'sources': [{'id': code, 'path': evidence['video_path'], 'sha256': evidence['video_sha256']}],
            'previous_findings': []}
    run_path = out / code / f'{policy}-run.json'
    previous = json.loads(run_path.read_text('utf-8')) if run_path.is_file() else {}
    if previous.get('status') == 'confirmed_failure':
        raise ValueError('Same input/policy confirmed failure; do not repeat')
    if previous.get('status') == 'model_wait':
        if previous.get('failures', 0) >= 3 or time.time() < previous['retry_at']:
            raise ValueError('Model recovery wait/actual failure limit')
    run = {'status': 'running', 'started': time.time(), 'instruction_sha256': hashlib.sha256(instruction.encode()).hexdigest(),
           'video_sha256': evidence['video_sha256'], 'failures': previous.get('failures', 0)}
    _atomic_json(run_path, run)
    print(json.dumps({'code': code, 'policy': policy, 'status': 'started'}, ensure_ascii=False), flush=True)
    try:
        from hotpost.script_rewriter import _generate
        value = _generate(settings, instruction, data, media=media)
        if not isinstance(value, dict) or type(value.get('passed')) is not bool or not isinstance(value.get('issues'), list):
            raise ValueError('Invalid review result')
        _atomic_json(target, {'policy': policy, 'instruction_sha256': run['instruction_sha256'],
            'evidence_path': selected['evidence_path'], 'video_sha256': evidence['video_sha256'], 'review': value,
            'checked_at': time.time(), 'audio_listened': False})
        run.update(status='completed', finished=time.time(), passed=value['passed'], issues=len(value['issues']))
        _atomic_json(run_path, run)
        print(json.dumps({'code': code, 'policy': policy, 'status': 'completed', 'review': value}, ensure_ascii=False), flush=True)
    except ModelServiceUnavailable as exc:
        run.update(status='model_wait', retry_at=exc.retry_at, failures=run['failures'] + int(exc.attempted), error=str(exc))
        _atomic_json(run_path, run)
        print(json.dumps({'code': code, 'status': 'model_wait', 'retry_at': exc.retry_at}, ensure_ascii=False), flush=True)
    except Exception as exc:
        run.update(status='confirmed_failure', error=str(exc), finished=time.time())
        _atomic_json(run_path, run)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('prepare', 'review'))
    parser.add_argument('--case')
    parser.add_argument('--policy', choices=('strict', 'calibrated'), default='strict')
    args = parser.parse_args()
    settings = load_settings()
    if args.stage == 'prepare':prepare(settings)
    else:review(settings, args.case, args.policy)


if __name__ == '__main__':main()
