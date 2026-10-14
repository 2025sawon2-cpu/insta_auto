import sys
from types import SimpleNamespace

import pytest

from hotpost.operation_progress import ProgressWatch, NoProgressTimeout, run_progress_command, watch_browser_transfer
from hotpost.youtube_download import transfer_matches_selected_player, player_media_identity


def test_ffmpeg_machine_progress_continues_without_output_files(tmp_path):
    script = '''import time
for i in range(7):
 print('frame='+str(i), flush=True)
 print('out_time_us='+str(i*1000000), flush=True)
 print('progress=continue', flush=True)
 time.sleep(.4)
print('progress=end', flush=True)
'''
    result = run_progress_command([sys.executable, '-u', '-c', script], idle_seconds=1)
    assert result.returncode == 0
    assert 'frame=6' in result.stdout


def test_ffmpeg_duplicate_progress_and_heartbeats_do_not_keep_process_alive():
    script = '''import time
for i in range(30):
 print('frame=1', flush=True)
 print('out_time_us=1000000', flush=True)
 print('progress=continue', flush=True)
 print('alive='+str(i), flush=True)
 time.sleep(.1)
'''
    with pytest.raises(NoProgressTimeout):
        run_progress_command([sys.executable, '-u', '-c', script], idle_seconds=1)


def player(video='E2vmIs5gmTc', resource='selected'):
    return {'videoDetails':{'videoId':video}, 'streamingData':{
        'sabrStreamingUrl':'https://r1.googlevideo.com/videoplayback?id='+resource+'&expire=1000&ip=192.0.2.1&lsig=source-signature&sparams=id%2Cexpire%2Cip&sabr=1'}}


def test_first_ump_response_streams_before_requestfinished_and_can_outlast_idle_window():
    selected = 'E2vmIs5gmTc'
    url = player()['streamingData']['sabrStreamingUrl']+'&rn=5'
    now = [0]
    watch = ProgressWatch(30, clock=lambda:now[0])
    callbacks = {}
    session = SimpleNamespace(on=lambda key, handler:callbacks.update({key:handler}), send=lambda *a:None, detach=lambda:None)
    close = watch_browser_transfer(SimpleNamespace(new_cdp_session=lambda p:session), None, watch,
        lambda src:transfer_matches_selected_player(src, player(), selected,
            page_url='https://www.youtube.com/watch?v='+selected),transfer_identity=player_media_identity)
    callbacks['Network.responseReceived']({'requestId':'first-ump','response':{
        'url':url,'status':200,'mimeType':'application/vnd.yt-ump','headers':{}}})
    # requestfinished and the decoded body are deliberately never provided.
    for _ in range(20):
        now[0] += 20
        callbacks['Network.dataReceived']({'requestId':'first-ump','dataLength':100})
        watch.check()
    assert now[0] == 400
    close()


@pytest.mark.parametrize('response,ad,page_id,resource',[
    (player('OlderVid123'),False,'E2vmIs5gmTc','selected'),
    (player(),True,'E2vmIs5gmTc','selected'),
    (player(),False,'OlderVid123','selected'),
    (player(),False,'E2vmIs5gmTc','advertisement'),
])
def test_previous_video_and_advertisement_never_renew_selected_transfer(response,ad,page_id,resource):
    url = player(resource=resource)['streamingData']['sabrStreamingUrl']
    assert not transfer_matches_selected_player(url,response,'E2vmIs5gmTc',
        page_url='https://www.youtube.com/watch?v='+page_id,ad=ad)


def test_signed_resource_identity_rejects_signature_or_signed_parameter_changes():
    original = player()['streamingData']['sabrStreamingUrl']
    for url in (original.replace('source-signature','other'),original.replace('expire=1000','expire=2000'),
        original.replace('r1.googlevideo.com','r1.googlevideo.com.attacker.invalid')):
        assert not transfer_matches_selected_player(url,player(),'E2vmIs5gmTc',
            page_url='https://www.youtube.com/watch?v=E2vmIs5gmTc')


@pytest.mark.parametrize('mime,headers',[
    ('application/vnd.yt-ump',{}),
    ('video/mp4',{'Content-Range':'bytes 0-99/200'}),
])
def test_duplicate_response_bytes_with_changed_url_counter_do_not_renew_progress(mime,headers):
    now=[0]
    watch=ProgressWatch(30,clock=lambda:now[0])
    callbacks={}
    session=SimpleNamespace(on=lambda key,handler:callbacks.update({key:handler}),send=lambda *a:None,detach=lambda:None)
    close=watch_browser_transfer(SimpleNamespace(new_cdp_session=lambda p:session),None,watch,
        lambda src:transfer_matches_selected_player(src,player(),'E2vmIs5gmTc',
            page_url='https://www.youtube.com/watch?v=E2vmIs5gmTc'),transfer_identity=player_media_identity)
    for index in range(3):
        now[0]=index*10
        request_id=str(index)
        callbacks['Network.responseReceived']({'requestId':request_id,'response':{
            'url':player()['streamingData']['sabrStreamingUrl']+'&rn='+request_id+'&pseq='+request_id,
            'status':206 if headers else 200,'mimeType':mime,'headers':headers}})
        callbacks['Network.dataReceived']({'requestId':request_id,'dataLength':100})
    assert watch.last_progress==0
    now[0]=30
    with pytest.raises(NoProgressTimeout):watch.check()
    close()
