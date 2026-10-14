"""Three thumbnail proposals through the official writer, retaining narration."""
import json
import argparse
from pathlib import Path
from hotpost.editing_adapter import _atomic_json
from hotpost.writing import codex_writer
from hotpost.writing.contract import snapshot, receipt

ROOT = Path('data/daily-rework-20261011/DeSoiZvyyqj/writing')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--revision', type=int, choices=(6, 7), default=6)
    revision = parser.parse_args().revision
    target = ROOT / f'quality-v{revision}.json'
    if target.exists():
        print('Existing thumbnail revision retained; no duplicate writer call', flush=True)
        return
    previous_path = ROOT / ('quality-v5.json' if revision == 6 else 'quality-v6.json')
    previous = json.loads(previous_path.read_text('utf-8'))
    contract = snapshot()
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['variants'],
        'properties': {'variants': {'type': 'array', 'minItems': 3, 'maxItems': 3,
            'items': {'type': 'object', 'additionalProperties': False,
                'required': ['number', 'thumbnail_lines', 'thumbnail_mechanism'],
                'properties': {'number': {'type': 'integer', 'enum': [1, 2, 3]},
                    'thumbnail_lines': {'type': 'array', 'minItems': 2, 'maxItems': 2,
                                        'items': {'type': 'string'}},
                    'thumbnail_mechanism': {'type': 'string'}}}}}}
    instruction = ('기존 폴더 저장 케이스 대본 세 안을 읽고 썸네일 문구만 각 두 줄 새로 제안하세요. '
        '본문은 변경하지 않습니다. A심적회계/B소유효과/C원작손실회피 흐름과 각 원고의 제품 갈등에 맞춥니다. '
        '확인된 일반 매력은 컴퓨터 폴더 모양의 실물 저장 케이스에 사진과 영상을 옮겨 보관하고 '
        '휴대한다는 점입니다. 폰 뒤 부착을 썸네일 중심으로 강제하지 말고, 실물 폴더를 꺼내 '
        '내 사진을 담는 물리적·디지털 의미 전환과 각 안의 심리적 갈등을 연결하세요. '
        '저장장치 용량·속도·동기화·자동 백업·가격·정품·사진 복사 검증은 임의로 추가하지 않습니다. '
        '컴퓨터 화면 속 디지털 폴더라는 뜻과 실물 제품이라는 뜻이 혼동되지 않게 해주세요. '
        '선택 기준·강의·방법이 아닌 이 제품 자체의 호기심을 남깁니다. 원본 썸네일이나 원고 문장 복사 금지. '
        '짧고 선명하게, 도현에 지원되지 않는 중간점/이모지는 빼고 기본 한글과 일반 문장부호만 사용. '
        '대본·음성·소스 수와 편집 길이는 제약으로 넣지 않습니다.\n\n' + contract['prompt'])
    if revision == 7:
        instruction += ('\n실제 세 썸네일 검토 후 한 번 보완합니다. B의 내가 찍어서 더 소중해/실물 폴더에 챙길래는 '
            '감정 일기처럼 읽히고 제품 차별적 반전이 약합니다. 첫 줄에 특정한 폴더 외형 또는 내 사진을 '
            '간직하는 갈등, 둘째 줄에는 실물 제품 안에 디지털 사진을 담는 반전이 자연스럽게 만나게 하세요. '
            'A도 이번 촬영/지난 기록의 역할 차이를 유지하면서 제품을 알고 싶게 하세요. C의 삭제 갈등과 '
            '실물 폴더 반전은 유지하되 원본 문구를 복사하지 않습니다. 폰 부착은 썸네일 필수 요소가 아닙니다. '
            '반드시 의문문으로 끝낼 필요는 없지만 낭독을 듣지 않고도 이 실물 제품의 매력이 전달돼야 합니다. '
            '감정만 설명하거나 보관 의향으로 끝내지 마세요. 본문·음성·편향은 그대로 둡니다.')
    folder = ROOT / f'thumbnail-v{revision}-writer'
    folder.mkdir(exist_ok=True)
    state = {'directory': folder, 'calls': []}
    identity_revision = json.loads((ROOT / 'quality-v4.json').read_text('utf-8'))
    corrected = json.loads(Path(identity_revision['corrected_input']).read_text('utf-8'))
    payload = {'reference': corrected['reference_script'],
        'analysis': previous['analysis'],
        'scripts': [{k: s[k] for k in ('number', 'bias', 'changes', 'text', 'thumbnail_lines')}
                    for s in previous['scripts']]}
    _atomic_json(folder / 'input.json', payload)
    value = codex_writer.chat(instruction, json.dumps(payload, ensure_ascii=False), schema,
                             lambda: None, state)
    assert {v['number'] for v in value['variants']} == {1, 2, 3}
    scripts = []
    for script in previous['scripts']:
        variant = next(v for v in value['variants'] if v['number'] == script['number'])
        scripts.append({**script, **variant, 'human_review_pending': True})
    _atomic_json(target, {**previous, 'scripts': scripts, 'revision': f'folder-thumbnail-v{revision}',
        'previous': str(previous_path.resolve()), 'calls': state['calls'],
        'writing_contract': receipt(contract), 'human_review_pending': True,
        'body_scripts_preserved': True, 'generation_model': 'codex-cli'})
    print('Three new thumbnail proposals saved; narration retained', flush=True)


if __name__ == '__main__':
    main()
