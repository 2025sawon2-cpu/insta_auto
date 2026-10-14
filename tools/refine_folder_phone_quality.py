"""Correct mixed-product mounting claims in all three official variants."""
import argparse
import json
from pathlib import Path
from hotpost.config import load_settings
from hotpost.studio import Studio
from hotpost.editing_adapter import _atomic_json as save
from hotpost.writing import codex_writer
from hotpost.writing.contract import snapshot, receipt
from hotpost.writing.checks import review
from hotpost.writing.variants import SCHEMA, validate_triplet

ROOT=Path('data/folder-phone-review-20261011-v8/DeSoiZvyyqj').resolve()
PREVIOUS=Path('data/daily-rework-20261011/DeSoiZvyyqj/writing/quality-v7.json')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--revision',type=int,choices=(8,9),default=9)
    revision=parser.parse_args().revision
    target=ROOT/f'writing/quality-v{revision}.json'
    if target.exists():
        print('Existing official triplet preserved.',flush=True);return
    previous_path=PREVIOUS if revision==8 else ROOT/'writing/quality-v8.json'
    previous=json.loads(previous_path.read_text('utf-8'))
    state=next(s for s in Studio(load_settings(),workers=False).store.list() if s['shortcode']=='DeSoiZvyyqj')
    identity=json.loads(Path('data/daily-rework-20261011/DeSoiZvyyqj/writing/quality-v4.json').read_text('utf-8'))
    corrected=json.loads(Path(identity['corrected_input']).read_text('utf-8'))
    reference=corrected['reference_script']
    assert reference.strip(), 'Actual saved reference is required; empty task field is not a reference.'
    contract=snapshot();folder=ROOT/f'writing/generation-v{revision}';folder.mkdir(parents=True,exist_ok=True)
    calls={'directory':folder,'calls':[]}
    instruction=(
        '폴더 모양 저장 케이스의 제품 사실 정정입니다. 원작과 기존 세 안을 직접 읽고 세 안 모두 함께 출력하세요. '
        '원작이 큰 폴더 케이스·작은 폴더 케이스·회색 ORICO 케이스를 혼용한 사실을 제품 사용 설명에서 구분합니다. '
        '일반 기능을 전언이나 검증 해설로 만들지 않습니다. 폴더형 케이스의 사진·영상 저장과 휴대폰 USB 연결은 '
        '직접 서술하되, 폰 뒤에 붙임을 이 케이스의 기본 기능으로 합치지 않습니다. '
        '별도 자석 패치가 있는 것과 케이스 기본 기능을 혼동하지 않습니다. '
        '본문 중 폰 뒤에 붙임 표현만 폰과 케이블로 연결해 사용하는 설명으로 정확하고 자연스럽게 바꾸세요. '
        'A의 심적 회계, B의 소유효과, C의 손실회피·정보격차 흐름과 인물·계기·여행 기록 상황은 유지합니다. '
        '새 정보 순서나 새 이야기로 전면 재작성하지 않습니다. 단순 수정으로 부자연스러운 경우 해당 연결 문장만 다듬으세요. '
        'C만 원작 흐름 유지/의미 있는 표면 2~3곳 변경 규칙 그대로, 원문 문장·특징적 묶음 복사 금지. '
        '세 안 썸네일은 기존과 정확히 유지합니다. 이번 목적은 부착 기능 혼용 수정이지 썸네일 재실험이 아닙니다. '
        '자동 백업·동기화·자동 폰 용량 확보·앱 없이 작동·호환 기종·속도·용량·가격·재고·기본 자석 부착 발명 금지. '
        '대본 안에 검토·출처·단서 해설이나 서로 다른 제품이라는 제작 설명을 낭독하지 않습니다. '
        '이야기는 연출이며 확인된 구매 경험이 아니고 심리 효과는 제작 가설입니다. '
        '확보 영상 수·길이·소스 부족은 집필 제약이 아닙니다. 댓글은 제품에 폴더 한 번.\n\n'+contract['prompt'])
    if revision==9:
        instruction += ('\n직전 입력의 작업 original_text 필드가 비어 원작을 전달하지 못한 문제를 정정합니다. '
            '아래 저장된 실제 원작 전사문을 직접 읽고 원작 대비 분석과 changes/surface_changes를 정확히 다시 적으세요. '
            '세 본문 text와 편향 및 썸네일 문구는 직전 v8과 정확히 유지하세요. 새로운 원고를 만들지 않습니다. '
            'A/B가 원작과 어떻게 다른 정보 순서/생활 갈등인지, C의 아이사진→부모님사진/일반보관상황→여행후카페/사진촬영대상→다음가족외출 같은 '
            '의미 있는 표면 변경을 실제 원작과 비교하세요. 원문 문장·특징적인 설명묶음 복사 여부도 직접 판단합니다. '
            '전사문의 혼뒤는 제품 기능을 추가할 근거가 아니며 부착 주장을 현재 기본 기능으로 다시 넣지 않습니다.')
    payload={'reference_script':reference,'reference_kind':'speech',
             'previous_analysis':previous['analysis'],'previous_scripts':previous['scripts'],
             'product_facts':['폴더 아이콘 모양의 실물 저장 케이스','사진·영상 파일 보관',
                              '휴대폰 USB 케이블 연결','작은 케이스 휴대'],
             'product_identity_correction':'Separate magnetic patch and ORICO footage do not establish built-in magnetic mounting on this folder case.'}
    save(folder/'input.json',payload);print('Official Codex triplet product correction started.',flush=True)
    result=codex_writer.chat(instruction,json.dumps(payload,ensure_ascii=False),SCHEMA,lambda:None,calls)
    validate_triplet(result);scripts=[]
    for item in result['variants']:
        old=next(s for s in previous['scripts'] if s['number']==item['number'])
        assert item['thumbnail_lines']==old['thumbnail_lines']
        assert item['bias']==old['bias']
        if revision==9:assert item['text']==old['text']
        checked=review(item['text'],reference,keyword='폴더',contract=contract)
        checked.update({k:v for k,v in item.items() if k!='text'},human_review_pending=True)
        scripts.append(checked)
    save(target,{**previous,'scripts':scripts,'analysis':{k:v for k,v in result.items() if k!='variants'},
        'writing_contract':receipt(contract),'calls':calls['calls'],'generation_model':'codex-cli',
        'previous':str(previous_path.resolve()),'human_review_pending':True,'thumbnail_lines_preserved':True,
        'reference_input':identity['corrected_input'],'reference_kind':'speech'})
    print('Three corrected variants saved for actual editorial review.',flush=True)


if __name__=='__main__':main()
