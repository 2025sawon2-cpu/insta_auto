"""Find a bounded relevant interval in a long download before the normal quality gate."""
from pathlib import Path

from .operation_progress import run_progress_command


def extract_relevant_segment(settings, video, meta, verifier, output, deadline=None):
    from .source_finder import _executable
    duration = meta.get('duration') or 0
    if not 180 < duration <= settings.source_long_video_max_seconds:
        return None
    ffmpeg = _executable('ffmpeg')
    if not ffmpeg:
        return None
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    length = max(4, min(90, settings.source_segment_seconds))
    scored = []
    # Inspect several intervals across the whole recording, never just its intro.
    for i in range(8):
        start = max(0, (duration - length) * i / 7)
        frames = []
        for j in range(3):
            frame = output / f'scan_{i}_{j}.jpg'
            result = run_progress_command([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-ss', str(start + length * (j + 1) / 4),
                           '-i', str(video), '-frames:v', '1', '-vf', 'scale=480:-2', '-progress', 'pipe:1', '-nostats', str(frame)],
                          idle_seconds=30)
            if result.returncode == 0 and frame.is_file():
                frames.append(frame)
        score = verifier.score(frames) if len(frames) == 3 else None
        if len(frames) == 3 and (score is not None or settings.source_match_mode == 'functional'):
            scored.append((score if score is not None else -1., start))
    # Similarity proposes the best available interval; only actual visual
    # review can approve functional footage, including weak/unavailable CLIP.
    if (not scored or (settings.source_match_mode != 'functional' and max(scored)[0] < .82)
           ):
        return None
    score, start = max(scored)
    target = output / 'segment.mp4'
    result = run_progress_command([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-ss', str(start), '-i', str(video),
                   '-t', str(length), '-map', '0:v:0', '-map', '0:a?', '-c:v', 'libx264', '-preset', 'fast',
                   '-crf', '20', '-c:a', 'aac', '-movflags', '+faststart', '-progress', 'pipe:1', '-nostats', str(target)],
                  idle_seconds=getattr(settings, 'source_download_idle_timeout', 120), progress_dir=output)
    if result.returncode or not target.is_file():
        return None
    return target, {'start': round(start, 3), 'end': round(start + length, 3),
                    'original_duration': duration, 'scan_similarity': round(score, 4) if score >= 0 else None}
