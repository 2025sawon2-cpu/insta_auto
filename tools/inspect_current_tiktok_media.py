"""Read only the existing candidate's embedded state; no navigation/request."""
import json
from playwright.sync_api import sync_playwright
from hotpost.config import load_settings
from hotpost.source_browser_runtime import attach_browser, browser_lease
from hotpost.tiktok_download import item_media_urls


settings = load_settings()
with browser_lease(settings), sync_playwright() as pw:
    context = attach_browser(pw, settings)
    page = next(p for p in context.pages if p.url.startswith('https://www.tiktok.com/@18hens/video/'))
    rows = page.locator('script').evaluate_all('els => els.map(e => ({id:e.id,type:e.type,text:e.textContent})).filter(e=>e.text.includes("7652080539364609288"))')
    for row in rows:
        try:
            value = json.loads(row['text'])
            shape = []
            def walk(node, path=''):
                if isinstance(node, dict):
                    if 'video' in node or str(node.get('id')) == '7652080539364609288':
                        shape.append({'path': path, 'keys': list(node)[:25],
                                      'id_matches': str(node.get('id')) == '7652080539364609288',
                                      'video_type': type(node.get('video')).__name__})
                    for key, child in node.items(): walk(child, path + '/' + key)
                elif isinstance(node, list):
                    for i,child in enumerate(node): walk(child, path + '/' + str(i))
            walk(value)
            urls = item_media_urls(value, '7652080539364609288')
            resources = page.evaluate('performance.getEntriesByType("resource").map(e=>e.name)')
            print(json.dumps({'script_id':row['id'], 'type':row['type'], 'length':len(row['text']), 'root_keys':list(value)[:20], 'shape':shape[:10],
                'bound_url_count':len(urls), 'exact_resource_matches':sum(v in urls for v in resources)}, ensure_ascii=False))
        except ValueError:
            print(json.dumps({'script_id':row['id'], 'type':row['type'], 'length':len(row['text']), 'json':False}))
