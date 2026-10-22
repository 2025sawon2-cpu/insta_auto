"""Timestamped reference pixels for spoken-reference writing, separate from OCR."""
import hashlib
import json
from pathlib import Path
import shutil

from ..editing_adapter import _atomic_json
from ..production import file_lock
from ..source_mask_review import sample_source_frames
from ..source_overlay_review import _duration
from .reference_evidence import visual_context, VisualEvidenceIntegrityError

POLICY = 'spoken-reference-actual-frames-v1'


def prepare(settings, video, identity):
    video=Path(video).resolve()
    key=hashlib.sha256(json.dumps([POLICY,str(video),identity]).encode()).hexdigest()
    folder=settings.data_dir/'writing/reference-visual'/key
    path=folder/'evidence.json'
    with file_lock(folder/'prepare.lock'):
        if path.exists():
            evidence=json.loads(path.read_text('utf8'))
            if evidence.get('writing_sample_policy')!=POLICY or evidence.get('source_path')!=str(video):
                raise VisualEvidenceIntegrityError('저장한 집필 원본 프레임의 계약·경로가 다릅니다.')
        else:
            probe=shutil.which('ffprobe')
            if not probe:raise RuntimeError('집필 참고 영상 관찰에 ffprobe가 필요합니다.')
            duration=_duration(video,probe)
            evidence=sample_source_frames(video,identity,folder/'frames',[[0.,duration]],samples_per_interval=6)
            evidence['writing_sample_policy']=POLICY
        visual_context({'reference_video_sha256':identity,'reference_visual_evidence':evidence})
        if not path.exists():_atomic_json(path,evidence)
        return evidence
