import sqlite3

from hotpost.config import Settings
from hotpost.storage import Storage
from hotpost.studio import Studio
from hotpost.studio_titles import caption_title


def test_caption_title_skips_tags_links_and_leading_blank_lines():
    assert caption_title('#캠핑 https://example.com\n\n접으면 카트가 되는 테이블\n제품 설명') == '접으면 카트가 되는 테이블'
    assert caption_title('#태그 https://example.com') == ''


def test_legacy_imported_title_recovery_is_read_only_and_preserves_custom_title(tmp_path):
    settings=Settings(data_dir=tmp_path)
    storage=Storage(settings.db_path);storage.close()
    with sqlite3.connect(settings.db_path) as db:
        db.execute("INSERT INTO posts(shortcode,username,taken_at,kind,caption,first_seen) VALUES('old','fixture',1,'reel','접으면 카트가 되는 테이블\n설명',2)")
    studio=Studio(settings,workers=False)
    state,_=studio.store.create('old','old',prepare=False)
    assert studio.public(state)['title'] == '접으면 카트가 되는 테이블'
    assert studio.store.get(state['id']) == state
    studio.store.change(state['id'],lambda s,db:s.update(title='내가 정한 캠핑 영상 제목'))
    assert studio.public(studio.store.get(state['id']))['title'] == '내가 정한 캠핑 영상 제목'
