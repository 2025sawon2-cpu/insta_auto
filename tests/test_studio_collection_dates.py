import sqlite3

from hotpost.config import Settings
from hotpost.studio import Studio


def test_collection_date_is_fixed_across_production_changes(tmp_path):
    settings = Settings(data_dir=tmp_path)
    from hotpost.storage import Storage
    storage = Storage(settings.db_path)
    storage.close()
    with sqlite3.connect(settings.db_path) as db:
        db.execute("INSERT INTO posts(shortcode,username,taken_at,kind,caption,first_seen) VALUES('collected','fixture',1791400000,'reel','수집 날짜 테스트',1791500000)")
    studio = Studio(settings, workers=False)
    task = studio.create('collected')
    assert task['collected_at'] == 1791500000
    studio.store.change(task['id'], lambda s, db: s.update(updated=1791600000))
    assert studio.public(studio.store.get(task['id']))['collected_at'] == 1791500000


def test_old_task_collection_date_projection_is_read_only(tmp_path):
    settings = Settings(data_dir=tmp_path)
    with sqlite3.connect(settings.db_path) as db:
        db.execute('CREATE TABLE posts(shortcode TEXT,first_seen INTEGER)')
        db.execute("INSERT INTO posts VALUES('old',1791500000)")
    studio = Studio(settings, workers=False)
    state, _ = studio.store.create('old','이전 제작 작업')
    assert studio.public(state)['collected_at'] == 1791500000
    assert 'collected_at' not in studio.store.get(state['id'])


def test_studio_date_uses_hot_discovery_day_for_a_previously_collected_post(tmp_path):
    from hotpost.collection_dates import post_collection_dates
    settings = Settings(data_dir=tmp_path)
    from hotpost.storage import Storage
    store = Storage(settings.db_path)
    first, hot = 1791500000, 1791586400
    store.conn.execute("INSERT INTO posts(shortcode,username,taken_at,kind,caption,first_seen) VALUES('later-hot','fixture',1791400000,'reel','나중에 발견한 영상',?)", (first,))
    store.conn.execute("INSERT INTO hot_detections VALUES('later-hot',?)", (hot,))
    store.conn.commit();store.close()
    studio=Studio(settings, workers=False)
    task=studio.create('later-hot')
    assert task['collected_at'] == first
    assert task['collection_date_at'] == hot
    assert task['collection_date_kst'] == post_collection_dates(first,hot)['collection_date_kst']
    assert task['collection_date_basis'] == 'hot_detected'
    saved=studio.store.get(task['id'])
    assert 'collection_date_at' not in saved
    studio.store.change(task['id'], lambda s,db:s.update(updated=hot+86400))
    assert studio.public(studio.store.get(task['id']))['collection_date_at'] == hot


def test_self_shot_browses_by_registration_day(tmp_path):
    studio=Studio(Settings(data_dir=tmp_path), workers=False)
    state,_=studio.store.create('self-shot','내 촬영',initial={'creation_mode':'self_shot','self_shot':{'script_mode':'manual','started':False}})
    task=studio.public(state)
    assert task['collection_date_at'] == state['created']
    assert task['collection_date_basis'] == 'self_shot'
