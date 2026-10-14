"""Correct our SSD assumption without replacing the original reference evidence."""
import json
from tools.recover_daily_materials import ROOT
from hotpost.editing_adapter import _atomic_json
from hotpost.writing import codex_writer
from hotpost.writing.contract import snapshot, receipt
from hotpost.writing.variants import SCHEMA, validate_triplet
from hotpost.writing.checks import review


def main():
    folder = ROOT / 'DeSoiZvyyqj/writing'
    out = folder / 'quality-v4.json'
    if out.exists():
        print('Existing identity revision retained; no duplicate generation', flush=True)
        return
    original = json.loads((folder / 'input.json').read_text('utf-8'))
    previous = json.loads((folder / 'quality-v3.json').read_text('utf-8'))
    contract = snapshot()
    payload = {
        'reference_script': original['reference_script'],
        'reference_caption': original['reference_caption'],
        'previous_scripts': previous['scripts'],
        'previous_analysis': previous['analysis'],
        'comment_keyword': '폴더',
        'product_identity_correction': (
            '원문 발화와 본문에는 SSD라는 명칭, 내부 SSD 삽입, SSD 동봉 여부가 없다. '
            '앞선 입력 notes와 분석에서 SSD 케이스로 좁힌 것은 우리 쪽 가정이었다. '
            '원본의 기능은 폴더 디자인, 사진·영상 외부 전송/보관, 휴대폰 뒤 부착, 작은 휴대성이다. '
            '일반 기능은 직접 쓰되 저장 방식이나 내부 부품/SD카드/SSD를 새로 단정하지 않는다. '
            '화면에는 서로 다른 기기가 섞여 있어 모든 폴더 모델에 같은 기능이 있다고 합치지 않는다. '
            '원작에 있는 폰 부착 편의 자체를 문구에서 일괄 삭제할 필요는 없지만, '
            '어떤 특정 모델의 기본 자석 기능이나 전체 폰 호환을 임의 보장하지 않는다. '
            '외부로 파일을 옮기는 것과 폰의 파일이 자동 삭제되어 공간이 확보되는 것은 다르다. '
            '자동 정리/자동 백업/무손실/용량 수치/현재 가격을 발명하지 않는다.'),
        'editorial_findings': (
            '1안 심적 회계의 지난 사진/다음 촬영 공간 구분은 유지할 만하지만 강의나 이득 반복을 줄인다. '
            '2안 평가 가능성은 쌓인 사진을 보고 필요를 느꼈다는 말만으로 작동했다고 볼 수 없다. '
            '같은 주 카테고리의 다른 미사용 효과를 선택하거나, 평가 가능성이 실제 정보 순서에서 '
            '작동하도록 새 갈등을 만든다. 두 안은 편향 이름만 바꾸지 않고 실제 전개를 달리한다. '
            '제품 정보를 설명하는 자료 해설, 선택 기준을 배우라는 댓글 유도는 실패다. '
            '3안만 원작 흐름 유지+유의미한 인물/장소/계기 변경2~3곳. '
            '원작 문장·대사·특징적인 설명 묶음을 복사하지 않는다. '
            '두 줄 썸네일은 짧고 구체적이며 파일 전송 장치 자체가 궁금해야 한다. '
            '확보 소스 수나 적합성은 집필의 조건이 아니다.')}
    work = folder / 'quality-v4'
    work.mkdir(exist_ok=True)
    _atomic_json(work / 'identity-corrected-input.json', payload)
    state = {'directory': work, 'calls': []}
    print('Folder identity correction: official writer generating three variants', flush=True)
    value = codex_writer.chat(
        '제품 정체를 잘못 좁힌 이전 세 안을 함께 재설계합니다. 약20~30초 자연스러운 낭독으로 '
        '1·2·3안을 반드시 모두 제안하고, 원작 심리 메커니즘 분류와 각 안에서 실제 작동하는 근거를 '
        '함께 씁니다. A/B는 같은 주 카테고리의 서로 다른 미사용 효과로 전체 갈등을 새로 짭니다. '
        '새 사연은 연출로 changes에 기록합니다. 이론 이름을 대본에서 강의하지 않습니다. '
        '자료 한계는 changes/분석에 두고 낭독에 당시/미확인 같은 해설을 붙이지 않습니다.\n\n' + contract['prompt'],
        json.dumps(payload, ensure_ascii=False), SCHEMA, lambda: None, state)
    validate_triplet(value)
    scripts = []
    for variant in value['variants']:
        checked = review(variant['text'], original['reference_script'], keyword='폴더', contract=contract)
        checked.update(**{k: v for k, v in variant.items() if k != 'text'},
                       variant_number=variant['number'], psychological_category=variant['category'],
                       human_review_pending=True)
        scripts.append(checked)
    _atomic_json(out, {'scripts': scripts, 'analysis': {k: v for k, v in value.items() if k != 'variants'},
                      'writing_contract': receipt(contract), 'generation_model': 'codex-cli',
                      'calls': state['calls'], 'human_review_pending': True,
                      'corrected_input': str(work / 'identity-corrected-input.json')})
    print('Folder identity correction: three actual proposals saved', flush=True)


if __name__ == '__main__':
    main()
