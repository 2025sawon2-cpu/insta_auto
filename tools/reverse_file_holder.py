"""Reverse search two different product views in the existing Yandex tab."""
from dataclasses import replace
import json,time
from urllib.parse import urlparse
from PIL import Image
from playwright.sync_api import sync_playwright
from hotpost.config import load_settings
from hotpost.browser_search import BrowserSearcher
from hotpost.editing_adapter import _atomic_json
from hotpost.source_browser_runtime import attach_browser,browser_lease
from tools.recover_daily_materials import ROOT


def main():
    s=replace(load_settings(),source_browser_captcha_wait=0);folder=ROOT/'DeRFXHpEwck/reverse-image';folder.mkdir(exist_ok=True)
    images=[]
    for name,index,box in [('package',1,(80,200,650,980)),('filled-velcro',8,(30,250,690,1080))]:
        image=folder/(name+'.png');Image.open(ROOT/'DeRFXHpEwck/reference-visual'/f'{index}.png').crop(box).save(image);images.append(image)
    search=BrowserSearcher(s,folder);search.deadline=time.monotonic()+180
    search.progress=lambda message:print(message,flush=True)
    with browser_lease(s),sync_playwright() as pw:
        c=attach_browser(pw,s);pages=[p for p in c.pages if urlparse(p.url).hostname=='yandex.com']
        if len(pages)!=1:raise RuntimeError('Existing collector Yandex tab required; no new browser or tab.')
        search._page=lambda context,provider:pages[0]
        search._yandex(c,images,80)
    _atomic_json(folder/'results.json',{'candidates':search.candidates,'terms':search.terms,'notes':search.notes,'searches':search.searches,'updated_at':time.time()})
    print(json.dumps({'candidates':len(search.candidates),'terms':search.terms,'notes':search.notes},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
