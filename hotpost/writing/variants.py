"""The agreed A/B/C contract is the actual benchmark generation output."""
import json

from . import codex_writer
from .contract import receipt
from .reference_evidence import COMMENT_KEYWORD
from .script_integrity import digest
from .mechanisms import mechanism_keys


def obj(properties):
    return {'type':'object', 'properties':properties, 'required':list(properties), 'additionalProperties':False}

STRING = {'type':'string', 'minLength':1}
STRINGS = {'type':'array', 'items':STRING}
TYPES = ('transformation_a', 'transformation_b', 'surface_substitution')
VARIANT = obj({'number':{'type':'integer','enum':[1,2,3]},
    'variant_type':{'type':'string','enum':list(TYPES)}, 'bias':STRING, 'category':STRING,
    'changes':STRING, 'surface_changes':STRINGS, 'mechanism_application':STRING,
    'text':{'type':'string','minLength':1,'maxLength':3000},
    'thumbnail_lines':{'type':'array','items':STRING,'minItems':2,'maxItems':2},
    'thumbnail_mechanism':STRING})
SCHEMA = obj({'original_category':STRING, 'original_mechanisms':{**STRINGS,'minItems':1},
    'original_hook_analysis':STRING,
    'variants':{'type':'array','items':VARIANT,'minItems':3,'maxItems':3}})


def validate_triplet(value):
    variants = value['variants']
    if [v['number'] for v in variants] != [1,2,3] or [v['variant_type'] for v in variants] != list(TYPES):
        raise ValueError('대본 1·2·3안의 번호·유형이 일치하지 않습니다.')
    normalize = lambda s: ''.join(s.split()).casefold()
    biases = [mechanism_keys(v['bias']) for v in variants[:2]]
    original = set().union(*(mechanism_keys(s) for s in value['original_mechanisms']))
    if any(len(b) != 1 for b in biases):
        raise ValueError('1·2안은 각각 하나의 주된 편향·심리효과를 선택해야 합니다.')
    if biases[0] & biases[1] or any(b & original for b in biases):
        raise ValueError('1·2안은 원작이 쓰지 않은 서로 다른 편향이어야 합니다.')
    if any(normalize(v['category']) != normalize(value['original_category']) for v in variants[:2]):
        raise ValueError('1·2안의 심리 카테고리가 원작 분석과 일치하지 않습니다.')
    if len({normalize(s) for s in variants[2]['surface_changes']}) < 2:
        raise ValueError('3안의 의미 있는 표면 치환 요소가 부족합니다.')


def generate_three(payload, directory, check, progress, *, evaluate):
    contract = payload['writing_contract']
    reference = payload['reference_script']
    if not reference.strip():
        raise ValueError('집필할 원본 참고 내용이 없습니다.')
    keyword = COMMENT_KEYWORD
    evidence = {'reference':reference, 'reference_kind':payload.get('reference_kind','provided_text'),
        'reference_caption':payload.get('reference_caption',''), 'comment_keyword':keyword,
        'request':payload.get('notes','')}
    state = {'directory':directory,'calls':[]}
    progress(.1,'원작 심리 후킹을 분석하고 대본 1·2·3안을 함께 작성하는 중')
    value = codex_writer.chat(
        '원작의 심리 후킹을 분석한 뒤 항상 세 안을 한 번에 작성하세요. '
        '1안 transformation_a와 2안 transformation_b는 원작의 같은 주된 카테고리 안에서 '
        '원작이 사용하지 않은 서로 다른 편향·심리효과로 도입·갈등·정보 순서·마무리를 새로 설계하세요. '
        '이름만 붙이지 말고 mechanism_application에 실제 작동하는 문구·갈등을 설명하세요. '
        '3안 surface_substitution만 원작 메커니즘·전개 흐름을 유지하며 의미 있는 요소를 '
        '2~3개 바꿔 surface_changes에 적으세요. 제품 사실·매력은 유지하지만 특징적 설명 묶음은 복사하지 않습니다. '
        '각 안의 변화 한 줄, 두 줄 썸네일 문구와 심리 적용을 함께 작성하세요. 썸네일은 원작 후킹을 '
        '다르게 적용하며 그 제품에 대해 궁금해지는 구체적인 갈등·차이를 만듭니다. '
        '원작의 편향·효과 전체를 original_mechanisms에 기록하고 1·2안의 category는 original_category와 같게 하세요. '
        'bias에는 주된 편향·효과 하나의 이름만 쓰고 적용 설명은 mechanism_application에 따로 적으세요. '
        '한글·영문 별칭이나 설명을 붙인 이름으로 같은 메커니즘을 새 효과처럼 사용하지 마세요. '
        '새 생활 상황·1인칭 연출은 changes에 표시하며 실제 구매 경험으로 기록하지 않습니다. '
        '댓글 요청을 빼도 제품 자체를 찾아보고 싶은 이유가 남아야 합니다. '
        '참고 당시·소개됐어요·현재 확인되지 않았어요 같은 자료 해설과 검증 안내를 낭독·썸네일에 넣지 않습니다. '
        '현재 판매 조건을 입증하지 못한 주장은 삭제하거나 가정으로만 표현하고, 필요한 한계는 분석 메타데이터에 남기세요. '
        '현재 최저가·재고·AS·원작의 특징적인 보증 묶음을 사실로 단정하지 마세요. '
        '짧고 간결하게 한 갈등을 전개하고 같은 기능·이득을 뒤에서 요약해 반복하지 마세요. 제품 기능을 반복하거나 '
        '기준·방법·추상적인 교훈을 알려주는 내용으로 끝내지 마세요. 보유 장면 수로 집필을 제한하지 마세요.\n\n'
        +contract['prompt'], json.dumps(evidence,ensure_ascii=False), SCHEMA, check, state)
    contract_attempts = []
    try:
        validate_triplet(value)
    except ValueError as exc:
        initial = {'value':value, 'error':str(exc)}
        contract_attempts.append(initial)
        # Retain the failed draft even if the official repair call fails.
        (directory/'variant-contract-initial.json').write_text(
            json.dumps(initial,ensure_ascii=False,indent=2),'utf-8')
        check()
        progress(.2,'세 안의 심리효과·유형 계약 문제를 한 번 보완하는 중')
        value = codex_writer.chat(
            '세 안의 계약 검사에 실패했습니다. 아래 오류를 고치고 항상 세 안을 함께 반환하세요. '
            '원작과 겹치거나 1·2안끼리 같은 효과는 별칭으로 바꾸지 말고, 다른 미사용 효과가 '
            '실제로 작동하도록 해당 안의 도입·갈등·정보 순서·마무리와 썸네일을 재설계하세요. '
            '문제 없는 안의 원고는 보존하세요. 1·2안은 각각 하나의 주된 효과 이름만 bias에 적습니다. '
            '같은 주 카테고리 유지, 3안의 의미 있는 표면 치환 2~3곳, 제품 사실 유지·원문 복사 금지 '
            '계약도 지키세요. 보유 소스 수는 집필에 넣지 않습니다.\n\n'+contract['prompt'],
            json.dumps({'evidence':evidence,'failed_triplet':initial},ensure_ascii=False),
            SCHEMA,check,state)
        validate_triplet(value)
        contract_attempts.append({'value':value,'status':'repaired'})
    generation_calls = list(state['calls'])
    scripts = []; audits = []; warnings = []
    for variant in value['variants']:
        check()
        target = directory / ('variant-'+str(variant['number']))
        target.mkdir(exist_ok=True)
        context = {'original_mechanisms':value['original_mechanisms'],
            'original_hook_analysis':value['original_hook_analysis'], 'selected_variant':variant,
            'other_variants':[v for v in value['variants'] if v['number'] != variant['number']]}
        result = evaluate({**payload, 'variant_context':context, 'comment_keyword':keyword}, target, check,
            lambda pct,message:progress(.3+(variant['number']-1)*.22+pct*.2,
                                       str(variant['number'])+'안 · '+message), draft=variant['text'])
        candidate = result['scripts'][0]
        candidate.update(title=('유형전환 A','유형전환 B','표면 치환형')[variant['number']-1],
            variant_number=variant['number'], variant_type=variant['variant_type'], bias=variant['bias'],
            psychological_category=variant['category'], changes=variant['changes'],
            surface_changes=variant['surface_changes'], mechanism_application=variant['mechanism_application'],
            thumbnail_lines=variant['thumbnail_lines'], thumbnail_mechanism=variant['thumbnail_mechanism'])
        scripts.append(candidate)
        audit = json.loads((target/'writing-audit.json').read_text('utf-8'))
        audits.append({'number':variant['number'], **audit})
        warnings.extend(result['warnings'])
        state['calls'].extend(result['generation_inference']['calls'])
    audit = {'flow':'three-variants-v1','initial_variants':value,'generation_calls':generation_calls,
        'variant_reviews':audits,'calls':state['calls'], 'warnings':warnings,
        'contract_attempts':contract_attempts,
        'reference_sha256':digest(reference)}
    (directory/'writing-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),'utf-8')
    return {'type':'scripts','scripts':scripts,'writing_contract':receipt(contract),'flow':'three-variants-v1',
        'generation_model':'codex-cli','generation_inference':{'provider':'codex','calls':state['calls'],'fallback':False},
        'benchmark':{'analysis':{'comment_keyword':keyword,'original_category':value['original_category'],
            'original_mechanisms':value['original_mechanisms'],'original_hook_analysis':value['original_hook_analysis']}},
        'warnings':warnings,'evidence':{'mode':'benchmark'}}
