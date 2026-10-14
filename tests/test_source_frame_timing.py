import copy
import shutil
import subprocess

import pytest

from hotpost.source_frame_timing import frame_exposure, probe_native_timing, timing_from_probe
from hotpost.source_mask_review import sample_source_frames
from hotpost.source_quality import sha256_file


def test_vfr_next_pts_and_last_native_duration_not_average_or_output_fps():
    proof=timing_from_probe({'streams':[{'duration':.9,'start_time':10,'avg_frame_rate':'30/1'}],
        'frames':[{'best_effort_timestamp_time':10.,'pkt_duration_time':.01},
                  {'best_effort_timestamp_time':10.2,'pkt_duration_time':.01},
                  {'best_effort_timestamp_time':10.7,'pkt_duration_time':.2}]},'source')
    assert [v for r in proof['frames'] for v in (r['start'],r['end'])]==pytest.approx([0,.2,.2,.7,.7,.9])
    assert frame_exposure({'source_timestamp':.7},'source',proof)['end']==pytest.approx(.9)
    assert frame_exposure({'source_timestamp':.7},'other-source',proof) is None
    changed=copy.deepcopy(proof);changed['frames'][-1]['end']=1.
    assert frame_exposure({'source_timestamp':.7},'source',changed) is None


def test_unknown_duration_duplicate_pts_or_unmatched_sample_cannot_invent_exposure():
    proof=timing_from_probe({'streams':[{'duration':1,'avg_frame_rate':'30/1'}],
        'frames':[{'best_effort_timestamp_time':0}, {'best_effort_timestamp_time':.5},
                  {'best_effort_timestamp_time':.5}, {'best_effort_timestamp_time':.8}]},'source')
    assert frame_exposure({'source_timestamp':.5},'source',proof) is None
    assert frame_exposure({'source_timestamp':.8},'source',proof) is None
    assert frame_exposure({'source_timestamp':.2},'source',proof) is None


def test_duplicate_native_pts_with_mixed_known_unknown_duration_is_ambiguous_not_crash():
    proof=timing_from_probe({'streams':[{'duration':'2','start_time':'0'}],
        'frames':[{'best_effort_timestamp_time':'1.0'},
                  {'best_effort_timestamp_time':'1.0','duration_time':'0.04'}]},'a'*64)
    assert proof['frames']==[]
    assert frame_exposure({'source_timestamp':1},'a'*64,proof) is None


def test_actual_native_probe_and_sampler_keep_existing_file_and_receipt_bytes(tmp_path):
    ffmpeg,ffprobe=shutil.which('ffmpeg'),shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:pytest.skip('Actual native ffmpeg tools unavailable')
    source=tmp_path/'coded-source.mp4'
    subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=10:duration=1',
        '-c:v','libx264','-pix_fmt','yuv420p',str(source)],check=True,capture_output=True)
    digest=sha256_file(source);old_receipt=tmp_path/'old-receipt.json';old_receipt.write_bytes(b'old immutable receipt')
    proof=probe_native_timing(source,digest,ffprobe=ffprobe)
    assert frame_exposure({'source_timestamp':.9},digest,proof)['end']==pytest.approx(1.)
    sampled=sample_source_frames(source,digest,tmp_path/'new-samples',[[0,1]],ffmpeg=ffmpeg,ffprobe=ffprobe)
    assert sampled['native_frame_timing']['source_sha256']==digest
    for frame in sampled['frames']:
        exposure=frame['native_frame_exposure']
        assert exposure['end']-exposure['start']==pytest.approx(.1) # Native 10fps, never guessed 30fps.
        assert exposure['source_sha256']==digest
    assert sha256_file(source)==digest and old_receipt.read_bytes()==b'old immutable receipt'
