from types import SimpleNamespace
import pytest
from hotpost import cli, collectors
from hotpost.collection_window import in_collection_window
from hotpost.config import Settings
from hotpost.models import Post, Profile
from hotpost.observations import MetricObservation
from hotpost.storage import Storage
from hotpost.studio_automation import all_today
from hotpost.acquisition import candidates


@pytest.mark.parametrize("source", ["browser", "web", "instaloader"])
@pytest.mark.parametrize("already_setup", [False, True])
def test_collection_cutoff_applies_on_first_and_later_runs(tmp_path, monkeypatch, source, already_setup):
    now=1800000000
    monkeypatch.setattr(cli.time, "time", lambda: now)
    monkeypatch.setattr(cli, "_sleep_after_account", lambda *args: None)
    s=Settings(data_dir=tmp_path)
    store=Storage(s.db_path)
    if already_setup:
        store.upsert_posts([Post("history", "u", now-90000, "reel", 10, 1, 100)])
    fetched=[Post(code,"u",stamp,"reel",10,1,100) for code,stamp in
             [("boundary",now-86400),("recent",now-1),("old",now-86401),("future",now+1)]]
    obs=[MetricObservation(p.shortcode,now,now,True,100,10,1,"test") for p in fetched]
    class Collector:
        def fetch(self, name, limit, existing):
            assert self.collection_started_at == now
            return Profile(name),fetched,obs
        def refresh_video_views(self, posts, max_lookups):
            assert all(in_collection_window(p.taken_at,now) for p in posts)
            return []
    monkeypatch.setattr(collectors,"get_collector",lambda *args:Collector())
    try:
        assert cli.collect(s,store,source,["u"])[:3] == (1,0,2)
        assert {p.shortcode for p in store.posts_for("u")} == {"boundary","recent"} | ({"history"} if already_setup else set())
        assert not store.observations_for("old")
        assert not store.observations_for("future")
        if already_setup:
            assert store.posts_for("u")[-1].views == 100
    finally:
        store.close()


def test_no_recent_posts_is_success(tmp_path,monkeypatch):
    now=1800000000
    monkeypatch.setattr(cli.time,"time",lambda:now)
    monkeypatch.setattr(cli,"_sleep_after_account",lambda *args:None)
    monkeypatch.setattr(collectors,"get_collector",lambda *args:SimpleNamespace(fetch=lambda *args,**kwargs:(Profile("u"),[],[])))
    s=Settings(data_dir=tmp_path); store=Storage(s.db_path)
    try:
        assert cli.collect(s,store,"browser",["u"])[:3] == (1,0,0)
        assert store.last_run()["stop_reason"] == ""
    finally:store.close()


def test_automatic_selection_uses_run_start_not_report_finish():
    started=1800000000
    rows=[{"shortcode":code,"kind":"reel","username":"u","tier":1,"rank_score":1,
           "taken_at":stamp,"hot_detected_at":started,"views":10000}
          for code,stamp in [("boundary",started-86400),("new",started),("old",started-86401),("future",started+1)]]
    r={"generated_at":started+3600,"collection_started_at":started,"posts":rows,
       "accounts":[{"username":"u","followers":1000}]}
    assert {p["shortcode"] for p in all_today(r,Settings(),started+3600)} == {"boundary","new"}
    assert {p["shortcode"] for p in candidates(r,Settings())} == {"boundary","new"}


def test_browser_with_only_old_pinned_posts_returns_zero(monkeypatch):
    from hotpost.collectors.browser import BrowserCollector
    client=BrowserCollector(Settings(collect_recovery_limit=5))
    client.collection_started_at=1800000000
    navigation=[]
    page=SimpleNamespace(content=lambda:"",wait_for_timeout=lambda *args:None,
                         mouse=SimpleNamespace(wheel=lambda *args:None))
    client.browser=SimpleNamespace(page=page,navigate=navigation.append,verify_identity=lambda:None)
    def bootstrap():
        client.nodes["old"]={"code":"old","media_type":2,"taken_at":1800000000-86401,"user":{"username":"u"}}
    monkeypatch.setattr(client,"_bootstrap",bootstrap)
    monkeypatch.setattr(client,"_links",lambda _: [{"href":"/u/reel/old/","text":"100","caption":"","thumbnail":""}])
    profile,posts,observations=client.fetch("u",5)
    assert posts == observations == []
    assert navigation == ["u/"]  # No old reel detail/view request.


def test_instaloader_skips_old_post_details(monkeypatch):
    import datetime
    from hotpost.collectors import instaloader_collector as module
    now=1800000000
    old=SimpleNamespace(date_utc=datetime.datetime.fromtimestamp(now-86401,datetime.timezone.utc))
    recent=SimpleNamespace(date_utc=datetime.datetime.fromtimestamp(now-10,datetime.timezone.utc),
        caption="",shortcode="new",is_video=False,typename="GraphImage",likes=10,comments=1,
        url="",mediaid=1)
    profile=SimpleNamespace(username="u",userid=1,full_name="",followers=1,followees=0,
        mediacount=2,biography="",profile_pic_url="",is_private=False,get_posts=lambda:iter([old,recent]))
    monkeypatch.setattr(module.instaloader.Profile,"from_username",lambda *args:profile)
    client=module.InstaloaderCollector(Settings())
    client.collection_started_at=now
    client._loader=SimpleNamespace(context=None)
    _,posts,_=client.fetch("u",5)
    assert [p.shortcode for p in posts] == ["new"]
