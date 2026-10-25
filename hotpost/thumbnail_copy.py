"""Shared editorial contract for title generation, repair and visual review."""
import re

POLICY = 'representative-image-independent-hook-20261025-v3'
INSTRUCTION = (
    'Thumbnail appeal contract v3; editorial source: hotpost/writing/RULES.md, thumbnail section. '
    'The image represents the product or use scene; the headline earns attention and interest in watching. '
    'Do not require a literal image description, the same benefit to be visibly proved in the cover, '
    'or the same opening sentence, conflict or psychological mechanism as the narration. '
    'Keep a representative image when its only alleged defect is not depicting the headline payoff. '
    'Two lines are typography only: neither line has to name the product or end in a question. '
    'Use observed reference covers only as evidence, not a copying template; never call narration or opening frames an observed feed cover. '
    'Consider women in their 30s and 40s through relevant situations and desires without stereotyping family or household roles. '
    'Possible hooks include surprise, a recognizable inconvenience, overlooked possibilities, curiosity or a desired change. '
    'Use short natural Korean in a friendly respectful voice. Broad reaction headlines such as 이거 대박인데요? '
    'are allowed candidates, not a recommended formula or an automatic failure for lacking a product name or specific function. '
    'Compare their actual curiosity against the risk of sounding like familiar advertising. '
    'Do not impose secrets, questions, paradoxes, a fixed candidate count or a quota of psychological effects. '
    'For multiple candidates vary angles and structures. Quote each headline and explain the reason to stop, '
    'the emotion or question it creates, reading ease and whether the full video delivers its promise. '
    'Evaluate image representativeness and headline appeal separately, then check their combined meaning and expectation. '
    'Loose coupling is allowed; misleading bait is not. Keep factual claims within supplied script/reference evidence '
    'and do not invent popularity, price, efficacy or verified personal experience. '
    'Do not negate actual actions or conditions through exaggerated shorthand. '
    'Preserve a user-selected headline unless its revision is requested. Editorial judgment is not measured click performance. '
)

COPY_REVIEW_INSTRUCTION = (
    ' Also review thumbnail_lines as one complete Korean headline. In thumbnail_review return natural, '
    'reason, problem_quote and proposed_lines. A noun phrase, ellipsis or a question can be natural; '
    'do not demand verbs on both lines. Reject an unintelligible missing predicate or unnatural case relation, '
    'not merely brevity. Quote the actual broken phrase in problem_quote. If natural, keep proposed_lines '
    'identical and problem_quote empty. If broken, propose only a local copy correction without changing '
    'the narration or product facts. Missing literal correspondence with the image, narration opening or conflict '
    'is not a language defect. Reference samples are not an observed feed cover. '
    'Do not add numbers, popularity, prices or promised functions. ' + INSTRUCTION
)


def editorial_schema(base):
    import copy
    schema=copy.deepcopy(base)
    schema['properties']['thumbnail_review']={'type':'object','properties':{
        'natural':{'type':'boolean'},'reason':{'type':'string'},'problem_quote':{'type':'string'},
        'proposed_lines':{'type':'array','items':{'type':'string'},'minItems':2,'maxItems':2}},
        'required':['natural','reason','problem_quote','proposed_lines'],'additionalProperties':False}
    schema['required']=[*schema['required'],'thumbnail_review']
    return schema


def resolve_copy(ask, lines, script, reference, review, *, script_changed=False):
    """One defect-bound comparison; unavailable advice never rewrites narration."""
    import hashlib
    import json
    digest=lambda value:hashlib.sha256(value.encode()).hexdigest()
    receipt={'policy':POLICY,'advisory_only':True,'status':'not_evaluated',
        'script_sha256':digest(script),'reference_sha256':digest(reference),'before':lines,
        'before_sha256':digest(json.dumps(lines,ensure_ascii=False)), 'initial_review':review}
    if not isinstance(review,dict):return lines,receipt
    proposed=review.get('proposed_lines')
    if (type(review.get('natural')) is not bool or not isinstance(proposed,list) or len(proposed)!=2
            or not all(isinstance(s,str) and s.strip() for s in proposed)):
        raise ValueError('썸네일 독립 검토 응답이 완전하지 않습니다.')
    joined=' '.join(lines)
    if not review['natural'] and (not review.get('problem_quote') or review['problem_quote'] not in joined):
        raise ValueError('썸네일 문제 인용이 실제 문구와 다릅니다.')
    receipt['status']='evaluated'
    selected=lines
    if not review['natural'] or script_changed:
        comparison=ask('두 썸네일 문구를 최종 원고·실제 원본 근거와 비교하세요. '
            '1번이 더 낫다고 가정하지 마세요. 자연스럽고 제품 사실과 양립하며 영상이 기대를 충족하는 문구를 선택하세요. '
            '이미지 설명·대본 첫 문장·심리갈등의 동일성을 요구하지 마세요. '
            '새 기능·수치·가격·인기 약속이 추가되면 grounded=false입니다. '
            'preferred는0 또는1, natural과grounded는선택문구의판단입니다. '+INSTRUCTION,
            {'script':script,'reference':reference,'thumbnail_candidates':[lines,proposed],
             'previous_finding':review},
            {'type':'object','properties':{'preferred':{'type':'integer','enum':[0,1]},
                'natural':{'type':'boolean'},'grounded':{'type':'boolean'},'reason':{'type':'string'}},
             'required':['preferred','natural','grounded','reason'],'additionalProperties':False})
        if (type(comparison.get('preferred')) is not int or comparison['preferred'] not in (0,1)
                or type(comparison.get('natural')) is not bool or type(comparison.get('grounded')) is not bool):
            raise ValueError('썸네일 보완 비교 응답이 완전하지 않습니다.')
        receipt['comparison']=comparison
        if comparison['preferred']==1 and comparison['natural'] and comparison['grounded']:
            selected=proposed
    receipt.update(after=selected,after_sha256=digest(json.dumps(selected,ensure_ascii=False)),changed=selected!=lines)
    return selected,receipt


def review_copy(lines):
    """Narrow wording advice, never a substitute for image/editorial review."""
    text = ' '.join(lines) if isinstance(lines, list) and all(isinstance(x, str) for x in lines) else ''
    issues = []
    if re.search(r'왜\s*(?:눈길이\s*갈|끌릴|끌리는)|뭐가\s*특별|어떤\s*비밀|궁금하지\s*않', text):
        issues.append('넓은 호기심 표현: 실제 맥락에서 후킹이 되는지와 흔한 광고로 읽힐 가능성을 비교할 것; 표현만으로 불합격하지 않음')
    return {'policy': POLICY, 'issues': issues, 'advisory_only': True}
