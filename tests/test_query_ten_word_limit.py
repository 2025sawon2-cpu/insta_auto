"""Universal dispatch limit, with immutable historical receipt grammar."""
import copy
import pytest
from hotpost.source_queries import platform_queries,within_query_word_limit,_clean_tiktok_syntax
from hotpost import source_visual_queries as visual


EN='red black white silver blue green pink gray foldable mirror'
KO='빨간 검정 흰색 파란 초록 회색 분홍 노란 접이식 거울'
ZH='红色 黑色 白色 银色 蓝色 绿色 灰色 粉色 可折叠 镜子'


@pytest.mark.parametrize('word',[EN,KO,ZH])
def test_ten_accepted_eleven_rejected_without_truncation(word):
    assert len(word.split())==10 and within_query_word_limit(word)
    assert platform_queries([word,word+' extra'],'tiktok',20)==[word]
    assert not within_query_word_limit(word+' extra')


@pytest.mark.parametrize('provider',['youtube','bilibili','douyin','xiaohongshu','bing','duckduckgo'])
def test_all_text_provider_pools_obey_same_limit(provider):
    expected=ZH if provider in {'bilibili','douyin','xiaohongshu'} else EN
    assert platform_queries([expected,expected+' extra'],provider,20)==[expected]


def test_whitespace_count_is_not_unicode_character_count():
    assert within_query_word_limit('향기좋은 향수')
    assert within_query_word_limit('floral perfume')
    assert within_query_word_limit(' \t'+EN.replace(' ','\t  ')+'\n')
    assert not within_query_word_limit(' ') and not within_query_word_limit(None)


def test_manual_tiktok_verification_uses_current_word_limit():
    from hotpost.platform_verification import TikTokSearchVerification
    assert TikTokSearchVerification(EN).query==EN
    assert TikTokSearchVerification('가'*181+' 향수').query=='가'*181+' 향수'
    with pytest.raises(ValueError):
        TikTokSearchVerification(EN+' extra')


def test_direct_browser_transport_rejects_before_touching_page():
    from hotpost.browser_search import BrowserSearcher
    audit={}
    assert BrowserSearcher._submit_search(None,object(),'tiktok',EN+' extra',audit) is False
    assert audit['reason']=='query_word_limit_exceeded'
    assert audit['execution']['query_submitted'] is False


@pytest.mark.parametrize('provider',['search_web','search_bing'])
def test_indexed_transport_sends_exact_phrase_without_added_words(monkeypatch,provider):
    from types import SimpleNamespace
    from hotpost import source_finder,search_access
    sent=[]
    monkeypatch.setattr(search_access,'indexed_gate',lambda *a:None)
    monkeypatch.setattr(source_finder,'request_pause',lambda:None)
    def receive(url,*,params,**kwargs):
        sent.append(params['q'])
        return SimpleNamespace(status_code=200,text='',raise_for_status=lambda:None)
    monkeypatch.setattr(source_finder.requests,'get',receive)
    getattr(source_finder,provider)([EN+' extra',EN],2)
    assert sent==[EN]


def test_legacy_visual_receipt_stays_excluded_and_new_receipt_accepts_ten(tmp_path):
    from test_source_visual_queries import actual
    settings,reference,frame,evidence,proposal,review=actual.__wrapped__(tmp_path)
    proposal['queries'][0].update(query=EN,language='en')
    proposal['observations'][0]['text']=EN
    review['proposal_sha256']=visual.digest(proposal)
    legacy=copy.deepcopy(evidence);legacy.pop('query_word_limit')
    review['input_sha256']=visual.digest(legacy)
    receipt={'policy':legacy['policy'],'input_sha256':visual.digest(legacy),'evidence':legacy,
             'proposal':proposal,'review':review,'queries':[]}
    assert visual.verify(receipt)==[]
    newer=copy.deepcopy(receipt);newer['evidence']=evidence
    newer['input_sha256']=visual.digest(evidence)
    newer['review']['input_sha256']=visual.digest(evidence)
    newer['queries']=visual.validate(proposal,newer['review'],evidence)
    assert [r['query'] for r in visual.verify(newer)]==[EN]
    assert _clean_tiktok_syntax(EN)==''  # historical replay remains six words
    assert platform_queries([EN],'tiktok',1)==[EN]  # current dispatch uses ten
