import copy
import json
import os
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageChops, ImageStat
import pytest

from hotpost import production_delivery as delivery


@pytest.fixture
def font():
    path = os.environ.get('HOTPOST_TEST_KCC_FONT')
    if not path or not Path(path).is_file():
        pytest.skip('Set HOTPOST_TEST_KCC_FONT to the official KCC font for media integration checks')
    return Path(path)


def test_style_preserves_content_geometry_and_source_plan(tmp_path, monkeypatch):
    font = tmp_path / 'font.ttf'
    font.write_bytes(b'test')
    monkeypatch.setattr(delivery, 'checked_font', lambda *args, **kwargs: (font, ('KCC-Ganpan', 'Regular')))
    plan = {'cover_spec': {'lines': ['제목', '둘째줄'], 'style': {'line_width': 900,
             'shadow_effect': {'blur': .8, 'alpha': .95}}, 'layout': ['old'], 'font_render_check': {'checked': True}},
            'caption_style': {'font_family': 'DSRefinedLetter M', 'shadow_effect': {'blur': .6, 'alpha': .9}},
            'captions': [{'start': 0, 'end': 2, 'text': '대본!'}], 'beats': ['same'], 'voice': 'same'}
    before = copy.deepcopy(plan)
    result = delivery.apply_current_style(plan, font)
    assert plan == before
    assert result['cover_spec']['style'] == {'line_width': 900, 'shadow_effect': {'blur': 1., 'alpha': .95}}
    assert result['caption_style']['shadow_effect'] == {'blur': .8, 'alpha': .9}
    assert result['caption_style']['font_family'] == 'DSRefinedLetter M'
    for field in ('captions', 'beats', 'voice'):
        assert result[field] == plan[field]
    assert 'layout' not in result['cover_spec']
    assert 'font_render_check' not in result['cover_spec']


def test_actual_font_identity_and_missing_glyph(font):
    delivery.checked_font(font, '옷걸이 이불! [광고]', family='KCC-Ganpan')
    with pytest.raises(ValueError, match='family'):
        delivery.checked_font(font, 'test', family='DoHyeon')
    with pytest.raises(ValueError, match='glyphs'):
        delivery.checked_font(font, '\U0010ffff')


def test_requires_raw_input_confirmation(tmp_path):
    with pytest.raises(ValueError, match='Confirm'):
        delivery.finalize('missing.mp4', 'missing.png', tmp_path, 'missing.ttf')


def test_real_delivery_first_frame_once_and_audio_clock_unchanged(tmp_path, font):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('ffmpeg/ffprobe required')
    raw = tmp_path / 'raw.mp4'
    cover = tmp_path / 'raw.png'
    Image.new('RGB', (360, 640), 'black').save(cover)
    subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-f', 'lavfi', '-i', 'color=blue:s=360x640:r=30:d=1',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(raw)], check=True)
    before = delivery.digest(raw), delivery.digest(cover)
    result = delivery.finalize(raw, cover, tmp_path / 'delivery', font, unmarked_inputs=True)
    assert result['audio_packets_unchanged'] and result['video_pts_unchanged'] and result['full_decode']
    assert not result['quality_complete']
    assert before == (delivery.digest(raw), delivery.digest(cover))
    frames = tmp_path / 'frame-%02d.png'
    subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', result['video'], '-frames:v', '2', str(frames)], check=True)
    with Image.open(tmp_path / 'frame-01.png') as first, Image.open(result['cover']) as marked:
        # Single application at first frame, allowing lossy codec rounding.
        assert max(ImageStat.Stat(ImageChops.difference(first.convert('RGB'), marked.convert('RGB'))).mean) < 2
    with Image.open(tmp_path / 'frame-02.png') as second:
        assert second.getpixel((50, 400))[2] > 230  # Body starts immediately after one cover frame.
        assert second.crop((290, 25, 350, 55)).convert('L').getextrema()[1] > 150  # Readable body disclosure.
    with pytest.raises(ValueError, match='Already delivered'):
        delivery.finalize(result['video'], result['cover'], tmp_path / 'again', font, unmarked_inputs=True)
    with pytest.raises(FileExistsError):
        delivery.finalize(raw, cover, tmp_path / 'delivery', font, unmarked_inputs=True)
