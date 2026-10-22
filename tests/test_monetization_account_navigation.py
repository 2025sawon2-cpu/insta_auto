"""A feed link is not evidence of the current Instagram login."""
import pytest

from test_instagram_publish import local_composer
from hotpost.monetization_browser import logged_in_instagram_profile


def test_home_account_card_does_not_make_profile_navigation_ambiguous(local_composer):
    _, page = local_composer
    page.set_content('''<aside><a href="/ggul_dol2/"><img alt="ggul_dol2님의 프로필 사진"><span hidden>프로필</span></a></aside>
        <main><a href="/ggul_dol2/"><img alt="ggul_dol2님의 프로필 사진"></a>
        <a href="/ggul_dol2/">ggul_dol2</a></main>''')
    assert logged_in_instagram_profile(page, '@GGUL_DOL2').count() == 1


@pytest.mark.parametrize('body', [
    '<aside><a href="/someone_else/">프로필</a></aside><main><a href="/ggul_dol2/">ggul_dol2</a></main>',
    '<main><a href="/ggul_dol2/">프로필</a></main>',
    '<aside><a href="/ggul_dol2/">프로필</a><a href="/ggul_dol2/">Profile</a></aside>',
    '<aside><a hidden href="/ggul_dol2/">프로필</a></aside>',
])
def test_incidental_hidden_or_ambiguous_profile_links_do_not_verify_login(local_composer, body):
    _, page = local_composer
    page.set_content(body)
    with pytest.raises(ValueError, match='프로필 메뉴'):
        logged_in_instagram_profile(page, 'ggul_dol2')
