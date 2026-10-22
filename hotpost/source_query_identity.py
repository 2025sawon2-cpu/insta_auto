"""Grounded core product identity shared by query review, dispatch and quotas."""
import copy
import re

VERSION = 'core-product-identity-v1'
FLEXIBLE_VERSION = 'core-product-identity-v2'
TOPIC_VERSION = 'reviewed-topic-discovery-v1'
LANGUAGES = ('en', 'zh', 'ko')


def _pattern(term):
    term = re.escape(term.casefold())
    # Latin names are words, not substrings of another brand/product.
    return r'(?<![a-z0-9])'+term+r'(?![a-z0-9])' if re.search('[a-z]', term) else term


def contains(text, terms):
    return any(re.search(_pattern(term), text.casefold()) for term in terms)


def _product_spans(text, term, flexible=False):
    """Keep product words in order; allow reviewed modifiers between whole words."""
    words = term.casefold().split()
    literal = [m.span() for m in re.finditer(_pattern(term), text.casefold())]
    if literal or not flexible or len(words) < 2:
        return literal
    tokens = list(re.finditer(r'\S+', text.casefold()))
    spans, position = [], 0
    for word in words:
        found = next((i for i in range(position, len(tokens)) if tokens[i].group() == word), None)
        if found is None:
            return []
        spans.append(tokens[found].span())
        position = found + 1
    return spans


def _terms(value):
    if not isinstance(value, dict):
        raise ValueError('핵심 제품의 언어별 검색 명사가 없습니다.')
    result = {}
    for lang in LANGUAGES:
        words = value.get(lang, [])
        if not isinstance(words, list) or not 1 <= len(words) <= 12:
            raise ValueError('핵심 제품의 언어별 검색 명사가 없습니다.')
        if any(not isinstance(w, str) or not w.strip() or len(w) > 80 for w in words):
            raise ValueError('핵심 제품 검색 명사 형식이 다릅니다.')
        result[lang] = list(dict.fromkeys(' '.join(w.split()) for w in words))
    return result


def checked_identity(value):
    if not isinstance(value, dict) or value.get('version') not in {VERSION, FLEXIBLE_VERSION, TOPIC_VERSION}:
        raise ValueError('핵심 제품 검색 계약이 없습니다.')
    if value.get('kind') not in {'branded', 'feature', 'category'}:
        raise ValueError('핵심 제품 검색 유형이 다릅니다.')
    result = {'version': value['version'], 'kind': value['kind'], 'product_terms': _terms(value.get('product_terms'))}
    required = value.get('required_terms')
    if not isinstance(required, list) or len(required) > 8:
        raise ValueError('고정할 제품 조건 형식이 다릅니다.')
    result['required_terms'] = []
    for row in required:
        if not isinstance(row, dict) or row.get('kind') not in {'brand', 'model', 'feature'}:
            raise ValueError('고정할 제품 조건 유형이 다릅니다.')
        result['required_terms'].append({**copy.deepcopy(row), 'terms': _terms(row.get('terms'))})
    kinds = {r['kind'] for r in required}
    if (result['kind'] == 'branded' and 'brand' not in kinds
            or result['kind'] == 'feature' and 'feature' not in kinds
            or result['kind'] != 'branded' and 'brand' in kinds):
        raise ValueError('핵심 제품 유형과 고정 조건이 다릅니다.')
    if result['version']==TOPIC_VERSION:
        from .source_queries import language,within_query_word_limit
        for key in ('topic_reference_sha256','topic_text_sha256'):
            if not isinstance(value.get(key),str) or not re.fullmatch(r'[a-f0-9]{64}',value[key]):
                raise ValueError('주제 검색의 원본·본문 결속이 없습니다.')
            result[key]=value[key]
        rows=value.get('approved_queries')
        if not isinstance(rows,list) or len(rows)>16:
            raise ValueError('검토된 주제 검색어 목록이 없습니다.')
        approved=[];words=set();intents=set()
        for row in rows:
            if (not isinstance(row,dict) or set(row)!={'query','language','semantic_key'}
                    or not within_query_word_limit(row['query'])
                    or ' '.join(row['query'].split())!=row['query']
                    or row['language'] not in LANGUAGES or language(row['query'])!=row['language']
                    or not isinstance(row['semantic_key'],str)
                    or not re.fullmatch(r'[a-z][a-z0-9_:-]{1,79}',row['semantic_key'])
                    or row['query'] in words or (row['language'],row['semantic_key']) in intents):
                raise ValueError('주제 검색어의 독립 검토 범위가 다릅니다.')
            approved.append(copy.deepcopy(row));words.add(row['query']);intents.add((row['language'],row['semantic_key']))
        result['approved_queries']=approved
    return result


def validate_identity(value, review, evidence, observations, *, require_complete=True, allow_visual_screen_text=False):
    """Translations/centrality need independent review; literal provenance is checked here."""
    result = checked_identity(value)
    if (review.get('subject_identity_supported') is not True
            or require_complete and review.get('core_identity_complete') is not True):
        raise ValueError('핵심 제품 정체성의 독립 검토를 통과하지 못했습니다.')
    for row in result['required_terms']:
        source = row.get('source')
        if source == 'visual':
            obs = row.get('observation_ids', [])
            if row['kind'] != 'feature' or not obs or not set(obs) <= set(observations):
                raise ValueError('시각 고정 조건의 실제 관찰 근거가 없습니다.')
        else:
            quote = row.get('quote')
            if source not in evidence['text'] or not isinstance(quote, str) or not quote.strip():
                raise ValueError('제품 고정 조건의 원문 인용이 다릅니다.')
            if quote not in evidence['text'][source]:
                refs=row.get('observation_ids') or []
                visual=(allow_visual_screen_text and source=='screen_text' and row['kind']=='feature'
                    and refs and set(refs)<=set(observations)
                    and any(quote in observations[ref]['text'] for ref in refs))
                if not visual:raise ValueError('제품 고정 조건의 원문 인용이 다릅니다.')
                # Explicitly report pixels as the evidence. The original OCR
                # and proposed quote remain unchanged, with no fuzzy matching.
                row['source_evidence']={'kind':'actual_reference_pixels','grounding_basis':'visual_observation',
                    'ocr_quote_literal_match':False,
                    'frame_ids':list(dict.fromkeys(f for ref in refs for f in observations[ref]['frame_ids']))}
            if row['kind'] in {'brand', 'model'} and not contains(quote, [t for ts in row['terms'].values() for t in ts]):
                raise ValueError('브랜드·모델 고정 조건이 실제 원문에 없습니다.')
    # The known brand in an explicit subject hint cannot silently become optional.
    # Background logos/caption brand lists alone do not become a subject hint.
    from .source_queries import BRANDS
    hint = evidence.get('subject_hint', '')
    for en, zh, aliases in BRANDS:
        names = (en, zh, *aliases)
        if contains(hint, names) and not any(r['kind'] == 'brand' and
                any(contains(t, names) for ts in r['terms'].values() for t in ts)
                for r in result['required_terms']):
            raise ValueError('핵심 주제의 브랜드가 검색 고정 조건에서 빠졌습니다.')
    from .source_queries import FEATURES
    for en, zh, aliases in FEATURES:
        names=(en,zh,*aliases)
        if contains(hint,names) and not any(r['kind']=='feature' and
                any(contains(t,names) for ts in r['terms'].values() for t in ts)
                for r in result['required_terms']):
            raise ValueError('핵심 주제의 특징이 검색 고정 조건에서 빠졌습니다.')
    return result


def matches_identity(query, identity):
    if identity is None:
        return True
    from .source_queries import language
    profile = checked_identity(identity)
    if profile['version']==TOPIC_VERSION:
        return any(query==row['query'] for row in profile['approved_queries'])
    lang = language(query)
    from .source_queries import BRANDS
    brand_terms=[t for r in profile['required_terms'] if r['kind']=='brand' for ts in r['terms'].values() for t in ts]
    if any(contains(query,(en,zh,*aliases)) and not any(contains(t,(en,zh,*aliases)) for t in brand_terms)
           for en,zh,aliases in BRANDS):
        return False
    return lang in LANGUAGES and any(_product_spans(query, term, profile['version'] == FLEXIBLE_VERSION)
        for term in profile['product_terms'][lang]) and all(
        contains(query, row['terms'][lang]) for row in profile['required_terms'])


def query_identity(query, identity=None):
    """Brand spellings, product synonyms, spacing and word order do not pad quotas."""
    if identity is None:
        from .source_coverage import search_query_identity
        return search_query_identity(query)
    if not matches_identity(query, identity):
        return ''
    from .source_queries import language
    profile = checked_identity(identity)
    lang = language(query)
    if profile['version']==TOPIC_VERSION:
        return next(lang+':topic:'+row['semantic_key'] for row in profile['approved_queries'] if row['query']==query)
    body = re.sub(r'(?:site:|inurl:)\S+', '', query.casefold())
    if profile['version'] == FLEXIBLE_VERSION:
        # Collect spans on the ORIGINAL text: overlapping product/feature words
        # must not survive merely because an earlier replacement split a phrase.
        spans = [span for term in profile['product_terms'][lang]
                 for span in _product_spans(body, term, True)]
        spans += [m.span() for row in profile['required_terms'] for term in row['terms'][lang]
                  for m in re.finditer(_pattern(term), body)]
        body = ''.join(' ' if any(a <= i < b for a, b in spans) else c for i, c in enumerate(body))
        tokens = sorted(set(re.findall(r'[a-z0-9]+|[\u3400-\u9fff]+|[가-힣]+', body)))
        return lang+':'+('|'.join(tokens))
    groups = [profile['product_terms'][lang], *[r['terms'][lang] for r in profile['required_terms']]]
    for terms in groups:
        for term in sorted(terms, key=len, reverse=True):
            body = re.sub(_pattern(term), ' ', body)
    tokens = sorted(set(re.findall(r'[a-z0-9]+|[\u3400-\u9fff]+|[가-힣]+', body)))
    return lang+':'+('|'.join(tokens))
