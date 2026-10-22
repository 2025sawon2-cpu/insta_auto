"""Shared editorial contract for title generation, repair and visual review."""
import re

POLICY = 'subject-specific-natural-copy-20261017-v2'
INSTRUCTION = (
    'Thumbnail appeal contract v2. Choose the headline from this product and this script, not a reusable layout formula. '
    'Two lines are typography only: neither line has to name the product or end in a question. '
    'First explain the relationship between the observed reference image, its actual headline (if supplied), '
    'the viewer situation/desire and the payoff in the script. Never call narration or a video opening an observed feed cover. '
    'Possible motives include a recognizable inconvenience, a desirable look, a concrete benefit, '
    'a surprising change of use or a specific unresolved detail. Choose what this evidence supports; do not force a hidden secret. '
    'A clearly visible benefit can still give a strong reason to watch. Showing a feature does not by itself spoil the headline. '
    'Use short natural Korean with a concrete stake. Avoid generic product-label + why/reason/question endings, '
    'vague claims that something is special, artificial suspense, criteria lessons and unsupported popularity/price promises. '
    'Questions are allowed when their specific answer matters to this viewer and the script actually delivers it. '
    'For multiple candidates use genuinely different angles and sentence structures, not noun swaps in the same template. '
    'Evaluate the actual image and copy together: what does the viewer recognize, want, gain or discover by watching? '
    'Keep all factual claims within the supplied script/reference evidence. Never copy another product headline as a claim. '
)

COPY_REVIEW_INSTRUCTION = (
    ' Also review thumbnail_lines as one complete Korean headline. In thumbnail_review return natural, '
    'reason, problem_quote and proposed_lines. A noun phrase, ellipsis or a question can be natural; '
    'do not demand verbs on both lines. Reject an unintelligible missing predicate or unnatural case relation, '
    'not merely brevity. Quote the actual broken phrase in problem_quote. If natural, keep proposed_lines '
    'identical and problem_quote empty. If broken, propose only a local copy correction without changing '
    'the narration, its psychological mechanism or product facts. Evaluate concrete viewer stakes and the '
    'relationship to supplied actual reference frames. Reference samples are not an observed feed cover. '
    'Do not add numbers, popularity, prices or promised functions. '
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
            '1번이 더 낫다고 가정하지 마세요. 한국어가 자연스럽고 제품 사실·심리갈등·본문과 일치하는 문구만 선택하세요. '
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
        issues.append('제품의 구체적인 이득·갈등 대신 일반적인 궁금증 문구를 사용함')
    return {'policy': POLICY, 'issues': issues, 'advisory_only': True}
