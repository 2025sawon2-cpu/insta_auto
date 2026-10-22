"""Real interrupted Bili transfer shape must reach the upper supervisor."""
import hashlib
import json
import os

from hotpost.supervision_evidence import collect_evidence
from hotpost.source_urls import canonical_video_key
from test_supervision_evidence import source_setup,save,job

URL='https://www.bilibili.com/video/BV1Hp4y187tH/'


def transfer(root):
    folder,manifest,worker,entry=source_setup(root)
    entry['workers'][0]['settled']=True
    save(manifest,{'candidates':[{'url':URL,'download_attempted':True}]})
    videos=folder/'videos';videos.mkdir()
    prefix='03_playwright-bilibili_BV1Hp4y187tH'
    info=save(videos/(prefix+'.info.json'),{'webpage_url':URL})
    return videos,prefix,info,entry,manifest


def test_bound_split_transfer_growth_and_merge_do_not_manufacture_double_bytes(tmp_path):
    folder,prefix,info,entry,manifest=transfer(tmp_path)
    bound=job({'source_attempts':[entry]})
    key='received_bytes:'+hashlib.sha256(canonical_video_key(URL).encode()).hexdigest()
    video=folder/(prefix+'.f30066.mp4.part');video.write_bytes(b'x'*100)
    audio=folder/(prefix+'.f30280.m4a.part');audio.write_bytes(b'x'*20)
    first=collect_evidence(tmp_path,bound)
    assert first['progress']=={key:120} and first['waits']==[]
    os.utime(video,None);save(info,{'webpage_url':URL,'timestamp':99999,'filesize':9999999})
    assert collect_evidence(tmp_path,bound)['progress']==first['progress']
    video.write_bytes(b'x'*150)
    assert collect_evidence(tmp_path,bound)['progress']=={key:170}
    final=folder/(prefix+'.mp4');final.write_bytes(b'x'*170)
    assert collect_evidence(tmp_path,bound)['progress']=={key:170}
    video.unlink();audio.unlink()
    save(manifest,{'candidates':[{'url':URL,'downloaded_file':'videos/'+final.name}]})
    assert collect_evidence(tmp_path,bound)['progress']=={key:170}


def test_unbound_url_prefix_metadata_and_other_task_cannot_count(tmp_path):
    folder,prefix,info,entry,manifest=transfer(tmp_path)
    (folder/(prefix+'.mp4.part')).write_bytes(b'x'*100)
    bound=job({'source_attempts':[entry]})
    save(info,{'webpage_url':'https://www.bilibili.com/video/BV1rs4y1K7yX/'})
    assert collect_evidence(tmp_path,bound)['progress']=={}
    save(info,{'webpage_url':URL})
    entry['task_id']='other-task'
    assert collect_evidence(tmp_path,bound)['progress']=={}
    entry['task_id']='work-one'
    (folder/(prefix+'.mp4.part')).unlink()
    (folder/(prefix+'-unrelated.mp4.part')).write_bytes(b'x'*1000)
    (folder/(prefix+'.jpg.part')).write_bytes(b'x'*1000)
    assert collect_evidence(tmp_path,bound)['progress']=={}


def test_real_supervisor_observes_partial_growth_and_still_holds_stalled_transfer(tmp_path):
    from test_studio_supervision import setup,tick
    studio,monitor,now,_,writer,task,_=setup(tmp_path)
    folder,prefix,info,entry,manifest=transfer(tmp_path)
    monitor.collector=collect_evidence
    monitor.pulse();claimed=studio.store.claim()
    entry.update(task_id=task['id'],studio_job_id=claimed['id'])
    claimed['checkpoint']['source_attempts']=[entry]
    studio.store.checkpoint(claimed,claimed['checkpoint'])
    partial=folder/(prefix+'.f30066.mp4.part');partial.write_bytes(b'x')
    tick(monitor,now)
    for size in range(2,12):
        partial.write_bytes(b'x'*size)
        tick(monitor,now)
        monitor.check(claimed)
    assert writer.calls==[]
    tick(monitor,now);tick(monitor,now)
    assert len(writer.calls)==1
    tick(monitor,now)
    assert monitor.summary(task['id'])['jobs'][0]['phase']=='held'
