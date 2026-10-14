"""Three benchmark variants, with a bounded review/repair for each draft."""
import json
from . import codex_writer
from .checks import review
from .contract import receipt
from .reference_evidence import COMMENT_KEYWORD
from .script_integrity import digest
from .script_quantities import quantity_readings

TEXT_SCHEMA = {'type':'object','properties':{'text':{'type':'string','minLength':1,'maxLength':3000}},
               'required':['text'],'additionalProperties':False}
ISSUE_SCHEMA = {'type':'object','properties':{'issues':{'type':'array','items':{'type':'object',
    'properties':{'quote':{'type':'string'},'reason':{'type':'string'}},'required':['quote','reason'],
    'additionalProperties':False}}},'required':['issues'],'additionalProperties':False}


def repair_preserves_integrity(before, after):
    """Issue counts cannot trade a repaired fact for a new important defect."""
    def findings(value):
        rows=set()
        for i in value['integrity_review']['issues']:
            if i.get('severity') not in {'critical','copy'}:continue
            if i.get('code')=='unsupported_experience':
                # This lexical flag cannot distinguish permitted fictional
                # first-person staging from an invented verified experience.
                # Keep it as review advice, not a mechanical regression veto.
                continue
            quote=' '.join(i.get('quote','').split())
            source=' '.join(i.get('source_quote','').split())
            claim=quote
            if i.get('code')=='quantity_changed':
                actual={(r['value'],r['unit']) for r in quantity_readings(quote)}
                known={(r['value'],r['unit']) for r in quantity_readings(source)}
                # Keep the incorrect actual claim, even when its sentence moves
                # or switches numeric spelling; a different bad value is new.
                unknown=actual-known
                if unknown:claim=tuple(sorted(unknown))
            elif i.get('code') in {'ground_clearance_reversal','storage_reversal','functional_polarity_reversal'}:
                claim=i['code']  # Each flag denotes one source-bound direction.
            elif i.get('code')=='mitigation_strengthened':
                from .script_integrity import invariants, strengthened
                subjects={r['value'] for r in invariants(source) if r['kind']=='mitigation'}
                active=tuple(sorted(s for s in subjects if strengthened(s,quote)))
                if active:claim=active
            rows.add((i.get('code'),i.get('severity'),claim,source))
        return rows
    return findings(after) <= findings(before)


def _generate_single(payload, directory, check, progress, *, draft=None):
    contract=payload['writing_contract'];reference=payload['reference_script']
    owned = payload.get('generation_mode') == 'self_shot'
    if not reference.strip():raise ValueError('집필할 원본 참고 내용이 없습니다.')
    mode = 'self_shot' if owned else 'benchmark'
    keyword=COMMENT_KEYWORD
    evidence={'reference':reference,'reference_kind':payload.get('reference_kind','provided_text'),
              'reference_caption':payload.get('reference_caption',''),'comment_keyword':keyword,
              'request':payload.get('notes',''),'quantity_readings':list(quantity_readings(reference))}
    if payload.get('variant_context'):
        evidence['variant_context'] = payload['variant_context']
    if owned:
        evidence.update(reference_kind='product_information', product=payload.get('product'), research=payload.get('research', {}))
    state={'directory':directory,'calls':[]}
    rules=contract['prompt']
    def ask(instruction, data, schema):
        return codex_writer.chat(instruction+'\n공통 규칙:\n'+rules,json.dumps(data,ensure_ascii=False),schema,check,state)
    progress(.15,'Codex가 대본을 작성·검토하는 중')
    text=(draft if draft is not None else ask(('제품 정보로 짧고 강렬한 제품 후킹 쇼츠의 새 내레이션 한 편을 쓰세요. ' if owned else
              '원본을 벤치마킹한 완성 내레이션 한 편을 쓰세요. ')+ '분석문 없이 text만 반환하세요.',evidence,TEXT_SCHEMA)['text'].strip()
          ).strip()
    if not text:raise ValueError('Codex가 빈 대본을 반환했습니다.')
    initial=text
    local=review(text,reference,evidence_mode=mode,keyword=keyword,contract=contract)
    progress(.55,'의미·문장 복사·새 사연 추가·말투를 확인하는 중')
    editorial={'status':'unavailable','issues':[]};repair={'attempted':False};warnings=[]
    try:
        value=ask(('제품 근거 자료와 후보를 대조하세요. ' if owned else '원본과 후보를 대조하세요. ')+
                  '실제 문제가 있는 문구를 정확히 인용하고 이유를 적으세요. '
                  '일반 기능의 직접 서술은 이번 규칙에서 허용합니다. 전언 말투를 강요하지 마세요. '
                  '유형전환 A/B는 원작과 다른 편향이 실제 갈등·정보 순서에서 작동하는지 검사하세요. '
                  '서로 편향 이름만 바뀌고 전개가 같은지도 variant_context의 다른 안과 비교하세요. '
                  '표면 치환형만 원작의 메커니즘·흐름을 유지하되 의미 있는 요소 2~3개를 바꿀 수 있습니다. '
                  '1인칭과 새 생활 상황 연출은 허용하며, 설정 변경을 제품 사실 추가와 혼동하지 마세요. '
                  '원문 문장·특징적인 설명 묶음, 추상적 교훈이나 기준·방법에 대한 댓글 요청은 검사하세요. '
                  '수정할 필요가 없으면 issues는 빈 배열입니다. 새 사실·인물·수치 추가나 복사는 구분하세요.',
                  {**evidence,'candidate':text},ISSUE_SCHEMA)
        if any(not i['quote'] or i['quote'] not in text for i in value['issues']):
            raise ValueError('검사 의견의 인용이 실제 대본과 일치하지 않습니다.')
        editorial={'status':'evaluated',**value}
    except (RuntimeError,ValueError,OSError) as exc:
        check();warnings.append('검사 미완료: '+str(exc)[:200])
    issues=[*local['quality_summary']['issues'],*[i['reason'] for i in editorial['issues']]]
    if issues:
        progress(.72,'문제가 있는 부분만 한 번 보완하는 중')
        repair={'attempted':True,'accepted':False,'before_sha256':digest(text)}
        try:
            proposed=ask('문제 부분만 고치고 정상 문장은 유지한 완성 대본을 반환하세요. 새 소구점·사실을 만들지 마세요. '
                         'findings의 실제 인용을 수정 대상으로 삼으세요. 복사 지적은 어미만 바꾸지 말고 '
                         '해당 구절의 어휘와 문장 구성을 다시 쓰되 기능·수치·고유명사는 유지하세요.',
                         {**evidence,'candidate':text,'issues':issues,
                          'findings':{'integrity':local['integrity_review']['issues'],
                                      'naturalness':local['naturalness_review']['issues'],
                                      'editorial':editorial['issues']}},TEXT_SCHEMA)['text'].strip()
            if not proposed:raise ValueError('Codex가 빈 수정안을 반환했습니다.')
            proposed_review=review(proposed,reference,evidence_mode=mode,keyword=keyword,contract=contract)
            progress(.86,'수정 전후를 비교하는 중')
            comparison=ask('두 원고를 같은 규칙으로 비교하세요. 뒤의 원고가 더 낫다고 가정하지 마세요. '
                           '후보 1이 의미·재작성·말투에서 실제로 개선됐으면 preferred=1, 동점·악화면 0입니다. '
                           'issues에는 선택한 원고에 남아 있는 문제만 정확히 인용하세요.',
                           {**evidence,'candidates':[text,proposed]},
                           {'type':'object','properties':{'preferred':{'type':'integer','enum':[0,1]},
                            'reason':{'type':'string'},'issues':ISSUE_SCHEMA['properties']['issues']},
                            'required':['preferred','reason','issues'],'additionalProperties':False})
            chosen=proposed if comparison['preferred']==1 else text
            if any(not i['quote'] or i['quote'] not in chosen for i in comparison['issues']):
                raise ValueError('비교 결과의 인용이 선택 대본과 다릅니다.')
            accept = comparison['preferred']==1 and repair_preserves_integrity(local, proposed_review)
            repair.update(accepted=accept,proposed=proposed,comparison=comparison)
            if accept:
                text=proposed;local=proposed_review;editorial={'status':'evaluated','issues':comparison['issues']}
            elif comparison['preferred']==0:
                editorial={'status':'evaluated','issues':comparison['issues']}
        except (RuntimeError,ValueError,OSError) as exc:
            check();repair['error']=str(exc)[:200];warnings.append('보완 미완료 · 이전 대본 보존')
    check()
    remaining=list(dict.fromkeys([*local['quality_summary']['issues'],*[i['reason'] for i in editorial['issues']]]))
    local['quality_summary'].update(status='issues_found' if remaining else
        'checks_clear_not_guaranteed' if editorial['status']=='evaluated' else 'not_evaluated',issues=remaining)
    candidate={**local,'title':'자동 집필','origin':'codex_internal','source_ids':['R1'],
        'single_pass_review':{**editorial,'script_sha256':digest(text),'reference_sha256':digest(reference),
                              'contract':receipt(contract),'advisory_only':True},
        'estimated_seconds':round(len(text.replace(' ',''))/6,1)}
    audit={'initial_text':initial,'repair':repair,'calls':state['calls'],'warnings':warnings}
    (directory/'writing-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),'utf-8')
    return {'type':'scripts','scripts':[candidate],'writing_contract':receipt(contract),'flow':'single-draft-v1',
        'generation_model':'codex-cli','generation_inference':{'provider':'codex','calls':state['calls'],'fallback':False},
        'benchmark':{} if owned else {'analysis':{'comment_keyword':keyword}},'warnings':warnings,'evidence':{'mode':mode}}


def generate(payload, directory, check, progress):
    if payload.get('generation_mode') == 'self_shot':
        return _generate_single(payload, directory, check, progress)
    from .variants import generate_three
    return generate_three(payload, directory, check, progress, evaluate=_generate_single)
