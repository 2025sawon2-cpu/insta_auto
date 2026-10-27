import copy
import json
from datetime import datetime, timezone

import pytest

from hotpost.config import Settings
from hotpost.daily_ranking import MODE, WINDOW, build_report, count, publish, select_next
from hotpost.reference_registry import load, save, sync, ranked
from hotpost.final_qa import digest


NOW = datetime(2026, 10, 26, 7, tzinfo=timezone.utc).timestamp()


def inputs(rows):
    profiles = {'started_at': NOW, 'accounts': [
        {'username': 'example', 'followers': '팔로워 1만'}]}
    details = {'started_at': NOW, 'rows': []}
    grid = {'started_at': NOW, 'rows': []}
    for code, hours, views in rows:
        href = f'/example/reel/{code}/'
        details['rows'].append({'username': 'example', 'href': href,
                                'last': NOW-hours*3600, 'caption': '제품'})
        grid['rows'].append({'href': href, 'raw': views})
    return profiles, details, grid


@pytest.mark.parametrize('raw,value,precision', [
    ('1.7만', 17000, 'approximate'), ('8만', 80000, 'approximate'),
    ('팔로워 2.3만', 23000, 'approximate'), ('조회수 8,548회', 8548, 'exact'),
    ('1.5K', 1500, 'approximate'), ('8,548', 8548, 'exact'),
    ('숨김', None, 'missing'), (None, None, 'missing'), ('0', 0, 'exact'),
])
def test_visible_counts_keep_labels_and_allow_abbreviations(raw, value, precision):
    metric = count(raw)
    assert metric['value'] == value and metric['precision'] == precision
    assert metric['raw'] == (str(raw) if raw is not None else '')


def test_only_qualified_posts_within_72_hours_rank_across_publication_dates(tmp_path):
    report = build_report(*inputs([
        ('older', 71, '8만'), ('newer', 1, '2만'), ('below', 2, '1.7만'),
        ('boundary', 72, '3만'), ('expired', 72.01, '99만'), ('future', -1, '99만'),
    ]), Settings(), generated_at=NOW)
    assert {p['shortcode'] for p in report['posts']} == {'older','newer','below','boundary'}
    assert [p['shortcode'] for p in report['posts'] if p['eligible']] == ['older','boundary','newer']
    assert next(p for p in report['posts'] if p['shortcode']=='older')['rank_score'] == 8
    registry = sync(load(tmp_path/'registry'), report, 'report.json')
    assert [p['video_id'] for p in ranked(registry)] == ['older','boundary','newer']
    assert [p['reference']['rank'] for p in ranked(registry)] == [1,2,3]
    assert not any(key in post for post in report['posts'] for key in ('growth','tracking','velocity'))
    assert report['window']['end'] - report['window']['start'] == WINDOW


def panel(body, comments=()):
    """Collected post-panel text: header, body, then commenter/NBSP/age/text blocks."""
    lines = ['example', '오리지널 오디오', '팔로우', 'example', '\xa0', '수정됨', '•', '2일', body]
    for comment in comments:
        lines += ['viewer', '\xa0', '1일', comment, '답글 달기']
    return '\n'.join(lines)


def test_reels_with_daiso_in_post_body_are_kept_but_excluded_from_ranking(tmp_path):
    captions = {
        'body': panel('다이소 북커버 꿀조합\n\n#북커버'),
        'hashtag': panel('북커버 꿀조합\n\n#다이소꿀템'),
        'english': panel('Best DAISO finds'),
        'comment_only': panel('북커버 꿀조합', ['다이소에도 있나요?']),
        'plain': '수집 형식이 다른 캡션',
    }
    report_inputs = inputs([(code, hours, '8만') for hours, code in enumerate(captions, 1)])
    for row, caption in zip(report_inputs[1]['rows'], captions.values()):
        row['caption'] = caption
    report = build_report(*report_inputs, Settings(), generated_at=NOW)
    by_code = {p['shortcode']: p for p in report['posts']}
    for code in ('body', 'hashtag', 'english'):
        post = by_code[code]
        assert not post['eligible'] and post['tier'] == 0 and 'rank' not in post, code
        assert post['assessment']['status'] == 'excluded'
        assert post['assessment']['reasons'] == ['excluded_topic:daiso']
    assert report['collection_verification']['excluded_posts'] == 3
    registry = sync(load(tmp_path/'registry'), report, 'report.json')
    assert [p['video_id'] for p in ranked(registry)] == ['comment_only', 'plain']


def test_each_day_current_values_requalify_without_prior_metrics_or_baseline(tmp_path):
    first = build_report(*inputs([('growing', 12, '1.7만')]), Settings())
    assert not first['posts'][0]['eligible']
    second = build_report(*inputs([('growing', 36, '3만')]), Settings())
    assert second['posts'][0]['eligible']
    registry = sync(load(tmp_path/'registry'), second, 'second.json')
    registry['posts']['growing']['production']['state'] = 'completed'
    third = build_report(*inputs([('growing', 60, '8만')]), Settings())
    sync(registry, third, 'third.json')
    assert registry['posts']['growing']['production']['state']=='completed'
    assert ranked(registry)[0]['reference']['rank_score']==8


def completed(tmp_path, item):
    video, cover = tmp_path/'video.mp4', tmp_path/'cover.png'
    video.write_bytes(b'reviewed video'); cover.write_bytes(b'reviewed cover')
    qa = {'schema_version':1,'video_id':item['video_id'],'task_id':'task','run_id':'run',
          'edit_id':'edit','producer':'producer','reviewed_at':'2026-10-26T07:00:00+09:00',
          'artifacts':{**{name:{'id':name,'sha256':'a'*64} for name in ('script','voice','plan')},
                       'video':{'path':str(video),'sha256':digest(video)},
                       'cover':{'path':str(cover),'sha256':digest(cover)}},
          'checks':{name:{'status':'충족','evidence':[{'asset':asset,'location':'00:01',
                                                   'observation':'Current reviewed content'}]}
                    for name,asset in [('script','script'),('visual','video'),
                                       ('audio_captions','video'),('cover_delivery','cover')]}}
    path=tmp_path/'qa.json'; path.write_text(json.dumps(qa),'utf-8')
    item['production'].update(state='completed',qa_evidence=str(path),final_sha256=digest(video),
                              task_id='task',run_id='run',owner='producer',monitor='monitor')
    return video


def test_completed_rank_stays_visible_and_next_skips_completions_without_recheck(tmp_path):
    report = build_report(*inputs([('first', 10, '8만'), ('second', 1, '3만')]), Settings())
    registry = sync(load(tmp_path/'registry'), report, 'report.json')
    video = completed(tmp_path, registry['posts']['first'])
    assert select_next(registry)=={'action':'audit_history','video_id':'second','rank':2}
    registry['posts']['second']['production']['state']='not_started'
    assert select_next(registry)=={'action':'start','video_id':'second','rank':2}
    assert [p['video_id'] for p in ranked(registry)]==['first','second']
    video.write_bytes(b'changed after review')
    # Reviewed completions are final and are not rechecked later.
    assert select_next(registry)=={'action':'start','video_id':'second','rank':2}


@pytest.mark.parametrize('state', ['in_progress','paused','blocked'])
def test_unfinished_work_outside_current_window_stops_new_selection(tmp_path, state):
    report = build_report(*inputs([('new', 1, '8만')]), Settings())
    registry = sync(load(tmp_path/'registry'), report, 'report.json')
    registry['posts']['old']={'video_id':'old','reference':{'in_latest_report':False},
                              'production':{'state':state}}
    assert select_next(registry)=={'action':'review_existing','video_ids':['old']}


def test_missing_counts_do_not_reuse_stale_values_or_enter_ranking(tmp_path):
    p,d,v=inputs([('post',1,'숨김')])
    assert not build_report(p,d,v,Settings())['posts'][0]['eligible']
    p['accounts'][0]['followers']='확인 불가'
    v['rows'][0]['raw']='8만'
    assert not build_report(p,d,v,Settings())['posts'][0]['eligible']
    d['started_at']=NOW-86400
    with pytest.raises(ValueError,match='different collection'):
        build_report(p,d,v,Settings())


def test_publish_isolated_snapshot_preserves_status_and_does_not_create_growth_tracking(tmp_path):
    settings=Settings(data_dir=tmp_path/'data',web_dir=tmp_path/'web')
    settings.data_dir.mkdir(); settings.web_dir.mkdir()
    report=build_report(*inputs([('post',1,'8만')]),settings,generated_at=NOW)
    registry=sync(load(settings.data_dir/'reference-status.json'),report,'old-report')
    registry['posts']['post']['production']['state']='not_started'
    save(settings.data_dir/'reference-status.json',registry)
    settings.report_path.write_text('{"previous":true}','utf-8')
    snapshot=tmp_path/'snapshot.json'
    publish(report,settings,snapshot)
    saved=json.loads(settings.report_path.read_text('utf-8'))
    assert saved['posts'][0]['production']['state']=='not_started'
    assert json.loads((tmp_path/'previous-report.json').read_text('utf-8'))=={'previous':True}
    from hotpost.storage import Storage
    store=Storage(settings.db_path)
    assert store.conn.execute('select count(*) from hot_view_tracking').fetchone()[0]==0
    assert store.conn.execute('select count(*) from metric_observations').fetchone()[0]==0
    assert store.last_run()['posts']==1
    store.close()


def test_registered_completion_opens_current_media_and_rejects_changed_bytes(tmp_path):
    from hotpost.post_preparation import PostPreparation
    settings=Settings(data_dir=tmp_path/'data')
    settings.data_dir.mkdir()
    report=build_report(*inputs([('post',1,'8만')]),settings)
    registry=sync(load(settings.data_dir/'reference-status.json'),report,'report.json')
    video=completed(settings.data_dir,registry['posts']['post'])
    save(settings.data_dir/'reference-status.json',registry)
    service=PostPreparation(settings)
    result=service.get('post')
    assert result['media']['final'].endswith('?v='+digest(video))
    assert service.media('post','final',digest(video))==video
    original=digest(video)
    video.write_bytes(b'changed')
    assert service.get('post')['media']['final'] is None
    with pytest.raises(FileNotFoundError):
        service.media('post','final',original)
