import copy
import hashlib
import json

import pytest
from PIL import Image

from hotpost.writing import pipeline, codex_writer
from hotpost.writing.contract import snapshot
from hotpost.writing.reference_evidence import visual_context


@pytest.fixture
def payload(tmp_path):
    video = tmp_path / 'reference.mp4'
    video.write_bytes(b'bound source fixture')
    image = tmp_path / 'frame.png'
    Image.new('RGB', (32, 32), 'white').save(image)
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    return {'reference_script': '목욕을 도와주는 물건이에요.', 'writing_contract': snapshot(),
        'reference_video_sha256': sha(video), 'reference_visual_evidence': {
            'source_path': str(video), 'source_sha256': sha(video), 'frames': [
                {'frame_id': 'actual-frame', 'path': str(image), 'sha256': sha(image), 'source_timestamp': 0.}]}}


def test_visual_input_keeps_text_and_frame_provenance_separate(payload):
    visual, images = visual_context(payload)
    assert visual['kind'] == 'sampled_reference_frames'
    assert visual['source_sha256'] == payload['reference_video_sha256']
    assert len(images) == 1 and visual['frames'][0]['frame_id'] == 'actual-frame'
    assert 'path' not in visual['frames'][0]


@pytest.mark.parametrize('damage', ['video', 'image', 'source_binding', 'duplicate', 'nan', 'negative', 'empty'])
def test_corrupt_or_misbound_visual_evidence_fails_before_model(payload, monkeypatch, tmp_path, damage):
    value = copy.deepcopy(payload)
    packet = value['reference_visual_evidence']
    if damage == 'video':
        from pathlib import Path
        Path(packet['source_path']).write_bytes(b'changed source')
    elif damage == 'image':
        from pathlib import Path
        Path(packet['frames'][0]['path']).write_bytes(b'changed image')
    elif damage == 'source_binding':
        packet['source_sha256'] = 'wrong'
    elif damage == 'duplicate':
        packet['frames'].append(copy.deepcopy(packet['frames'][0]))
    elif damage == 'nan':
        packet['frames'][0]['source_timestamp'] = float('nan')
    elif damage == 'negative':
        packet['frames'][0]['source_timestamp'] = -.5
    else:
        value['reference_visual_evidence'] = {}
    monkeypatch.setattr(pipeline.codex_writer, 'chat', lambda *a, **k: pytest.fail('model must not run'))
    with pytest.raises(ValueError):
        pipeline.generate(value, tmp_path, lambda: None, lambda *a: None)


def test_each_review_repair_and_comparison_receives_same_actual_images(payload, monkeypatch, tmp_path):
    seen = []
    replies = [{'text': '몸을 받쳐주니 씻기기 편해요. 댓글에 나도 남겨주세요.'},
        {'issues': [{'quote': '씻기기 편해요', 'reason': '구체적인 쓰임을 설명하세요.'}]},
        {'text': '몸을 받쳐 두 손으로 씻겨요. 댓글에 나도 남겨주세요.'},
        {'preferred': 1, 'reason': '실제 쓰임이 구체적입니다.', 'issues': []}]
    def chat(instruction, data, schema, check, state, *, images):
        seen.append((json.loads(data)['reference_visual'], list(images)))
        return replies[len(seen)-1]
    monkeypatch.setattr(pipeline.codex_writer, 'chat', chat)
    monkeypatch.setattr(pipeline, 'review', lambda text, *a, **kw: {
        'text': text, 'integrity_review': {'issues': []}, 'naturalness_review': {'issues': []},
        'quality_summary': {'issues': []}})
    pipeline._generate_single(payload, tmp_path, lambda: None, lambda *a: None)
    assert len(seen) == 4 and all(value == seen[0] for value in seen)


def test_cli_uses_immutable_copies_and_records_actual_frame_sha(payload, tmp_path):
    visual, images = visual_context(payload)
    out = tmp_path / 'call'
    out.mkdir()
    copies, receipts = codex_writer._snapshot_images(images, {'reference_visual': visual}, out)
    original = images[0].read_bytes()
    images[0].write_bytes(b'changed after snapshot')
    assert copies[0].read_bytes() == original
    assert receipts[0]['sha256'] == hashlib.sha256(original).hexdigest()
    assert receipts[0]['frame_id'] == 'actual-frame'
    second = tmp_path / 'second-call'
    second.mkdir()
    with pytest.raises(ValueError, match='SHA'):
        codex_writer._snapshot_images(images, {'reference_visual': visual}, second)
