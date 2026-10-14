"""Strengthen the mirror triplet through the official writer, preserving A audio."""
import json
import argparse
from pathlib import Path
from hotpost.editing_adapter import _atomic_json
from hotpost.writing import codex_writer
from hotpost.writing.checks import review
from hotpost.writing.contract import snapshot, receipt
from hotpost.writing.variants import SCHEMA, validate_triplet

ROOT = Path('data/daily-rework-20261011/DeTaESASnr_/writing')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--revision', type=int, choices=(4, 5), default=4)
    revision = parser.parse_args().revision
    destination = ROOT / f'quality-v{revision}.json'
    if destination.exists():
        print('Existing triplet retained; no duplicate writer call.', flush=True)
        return
    previous_path = ROOT / f'quality-v{revision - 1}.json'
    previous = json.loads(previous_path.read_text('utf-8'))
    reference = json.loads((ROOT / 'input.json').read_text('utf-8'))
    contract = snapshot()
    directory = ROOT / f'mirror-quality-v{revision}-writer'
    directory.mkdir(exist_ok=True)
    state = {'directory': directory, 'calls': []}
    instruction = (
        '거울 제품 실제 결과물의 지속 품질 개선입니다. 아래 원작과 기존 세 안을 읽고 세 안을 함께 출력하세요. '
        '1안 자기참조 효과의 본문 text는 기존 원문을 정확히 유지하세요. 이미 외출 직전 경험에서 시작해 '
        '거울/외관/보드 순으로 구성되어 원작 발견 흐름과 다릅니다. 1안 썸네일은 신발 신은 채라는 '
        '상황만 강조하지 말고 나가기 직전 메모와 옷차림을 한곳에서 확인한다는 구체적 매력을 '
        '두 줄에 짧게 연결하세요. 댓글 요청 없이도 이 제품 구조를 알고 싶어야 해요. '
        '2안은 기존 고립 효과가 단정한 은색 면 설명에 머물고 기억 실험과 연결된 의미가 약해요. '
        '같은 관심·기억 카테고리에서 원작과 1안이 사용하지 않은 단순 노출 효과로 바꾸세요. '
        '처음엔 낯설거나 차갑게 느낀 은색 면을 매일 보면서 점차 친근하고 마음에 드는 대상으로 '
        '받아들이는 생활 설정을 하나의 갈등으로 짧게 전개하세요. 단순히 사용하기 편해져서 '
        '좋아한다는 효용 학습과 구분하여 반복 접촉 전후 외관에 대한 태도 변화를 보여주세요. '
        '이론 이름이나 결과 해설은 낭독에 넣지 마세요. 공간 절약을 도입/중간/끝마다 반복하지 마세요. '
        '3안만 원작 정보 격차/기대 위반 흐름을 유지하되 복도/가족/산책 등 표면 최소 2~3곳 의미 있게 '
        '바꾸고 원문 문장·대사·특징적인 설명 묶음을 복사하지 마세요. 전신거울과 자석 보드의 '
        '일반 기능은 모든 안에서 유지합니다. 새로운 제품 수치·판매 조건·기능을 발명하지 않습니다. '
        '1인칭 생활 상황은 연출로 changes에만 기록하고 실제 구매 경험으로 보증하지 않아요. '
        '썸네일 두 줄 모두 도현으로 읽기 좋은 기본 한글과 일반 문장부호, 중간점/이모지 제외. '
        '현재 가격·재고·정품·AS·메모를 잊지 않는다는 보장 없음. 제품 궁금증으로 댓글 나도 한 번. '
        '원고에 확보 소스 수·영상 길이·편집 문제를 제약으로 넣지 않습니다.\n\n' + contract['prompt'])
    if revision == 5:
        instruction = (
            '거울의 v4 세 안을 실제 읽은 뒤 한 번 보완합니다. 세 안의 본문 text와 편향 이름, category, '
            'mechanism_application을 정확히 그대로 유지하세요. 썸네일과 원작 대비 changes/surface_changes만 '
            '보완합니다. A의 나가기 직전 메모와 옷차림/이 보드 한곳에서 확인은 긴 기능 요약이라 '
            '감정과 제품 호기심이 약합니다. 나갈 때 열쇠 챙기면서 옷차림까지 확인하는 자기 경험과 '
            '은색 보드/거울의 구체적 매력을 짧게 만나게 하세요. 원작 보드인줄알았는데의 문장을 '
            '반복하지 않습니다. B의 매일 보니 마음에 들어요는 호감 일기이며 이 제품을 찾아보고 '
            '싶은 차별적 매력이 없습니다. 낯선 은색 외관에 점차 정이 간다는 태도 변화에 거울과 '
            '보드의 구체적 매력을 짧게 연결합니다. 단순 노출이 구매를 보장한다거나 자꾸 써서 '
            '기능이 좋다는 효용 학습으로 바꾸지 않습니다. C는 의미 있는 3표면 변화와 원작 흐름을 '
            '유지하면서 썸네일 첫 줄이 너무 길지 않게 줄입니다. changes와 surface_changes는 직전 '
            '우리 초안이 아니라 실제 원작과 비교하여 현관→작업실 입구, 일반 외출→회의 참석, '
            '일반 메모→동료에게 회의 장소 전달 등으로 정확히 표기합니다. '
            '추상적 기준·방법·이론 해설·확인안내·가격·재고·정품·AS 추가 금지. 두 줄 썸네일은 '
            '도현으로 읽기 좋은 기본 한글과 일반 문장부호만, 중간점/이모지 제외. '
            '세 안을 모두 함께 출력하고 본문은 정확히 유지하세요. 소스 수와 영상 길이는 제약 아님.\n\n'
            + contract['prompt'])
    payload = {
        'reference': reference['reference_script'],
        'reference_kind': 'speech', 'comment_keyword': '나도',
        'previous_analysis': previous['analysis'],
        'previous_scripts': [{k:s[k] for k in ('number', 'bias', 'category', 'text', 'thumbnail_lines', 'changes')}
                             for s in previous['scripts']],
    }
    _atomic_json(directory / 'input.json', payload)
    print('Mirror three-script quality revision started through official Codex CLI.', flush=True)
    result = codex_writer.chat(instruction, json.dumps(payload, ensure_ascii=False), SCHEMA, lambda: None, state)
    validate_triplet(result)
    assert next(s for s in result['variants'] if s['number'] == 1)['text'] == previous['scripts'][0]['text']
    if revision == 5:
        assert all(s['text'] == next(v for v in previous['scripts'] if v['number'] == s['number'])['text']
                   for s in result['variants'])
    scripts = []
    for item in result['variants']:
        checked = review(item['text'], reference['reference_script'], keyword='나도', contract=contract)
        checked.update(**{k:v for k,v in item.items() if k != 'text'}, human_review_pending=True)
        scripts.append(checked)
    _atomic_json(destination, {**previous, 'scripts': scripts,
        'analysis': {k:v for k,v in result.items() if k != 'variants'},
        'writing_contract': receipt(contract), 'calls': state['calls'],
        'human_review_pending': True, 'generation_model': 'codex-cli',
        'previous': str(previous_path.resolve()), 'selected_a_body_preserved': True})
    print('Mirror A/B/C revision saved separately; actual editorial review pending.', flush=True)


if __name__ == '__main__':
    main()
