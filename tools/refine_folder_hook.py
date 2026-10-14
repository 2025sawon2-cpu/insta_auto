"""Versioned repair of weak openings after reviewing the identity-corrected triplet."""
import json
from pathlib import Path
from hotpost.editing_adapter import _atomic_json
from hotpost.writing import codex_writer
from hotpost.writing.checks import review
from hotpost.writing.contract import snapshot, receipt
from hotpost.writing.variants import SCHEMA, validate_triplet


def main():
    root = Path('data/daily-rework-20261011/DeSoiZvyyqj/writing')
    out = root / 'quality-v5.json'
    if out.exists():
        print('Existing hook revision retained; no duplicate writer.', flush=True)
        return
    previous = json.loads((root / 'quality-v4.json').read_text('utf-8'))
    corrected = json.loads(Path(previous['corrected_input']).read_text('utf-8'))
    findings = {
        'status': 'requires_hook_revision', 'render_ready': False,
        'identity_correction': 'SSD/카드/내부 부품 가정 제거는 실제 세 안에 반영됨.',
        'copy_review': 'A/B는 삭제 고민 중심인 원작과 다른 갈등/순서. C만 원작 흐름 및 세 표면 변경. 문장 통째 복사 없음. 법적 판정은 아님.',
        'issues': [
            '반갑네요/괜히 더 귀해요 같은 서두는 의미 없는 감탄으로 첫 제품 호기심이 약하다.',
            'A 썸네일은 지난 여행 보관 설명에 머물고, B의 이 작은 폴더는 제품 차별적 매력이 모호하다.',
            'A 공간 용도 분리/B 내 기록의 가치 차이는 실제 갈등에 남아야 하며 이름만 다른 기능 요약으로 합치면 안 된다.',
            '폰 뒤 부착은 원작 일반 기능으로 유지하나 서로 다른 기기를 한 모델의 시연으로 합쳐 편집하지 않는다.'
        ], 'audio_listened': False}
    _atomic_json(root / 'quality-v4-editorial-review.json', findings)
    contract = snapshot()
    work = root / 'quality-v5'
    work.mkdir(exist_ok=True)
    state = {'directory': work, 'calls': []}
    payload = {'original_reference': corrected['reference_script'],
               'reference_caption': corrected['reference_caption'],
               'identity_constraints': corrected['product_identity_correction'],
               'analysis': previous['analysis'], 'previous_scripts': previous['scripts'],
               'editorial_findings': findings, 'comment_keyword': '폴더'}
    _atomic_json(work / 'input.json', payload)
    print('Folder hook repair: official writer generating all three proposals', flush=True)
    value = codex_writer.chat(
        '실제 검토 결과를 반영하여 3안을 함께 보완하세요. A 심적 회계/B 소유효과/C 원작 흐름 및 의미 있는 표면변경을 유지하되 '
        '첫 문장의 반갑네요, 괜히 더 귀해요, 아까워요 같은 군더더기 감탄을 빼고 생활 갈등과 제품이 바로 만나는 구어체로 시작합니다. '
        'A는 지난 기록과 이번 촬영의 서로 다른 보관 역할, B는 비슷한 장면도 내 기록이면 따로 남기고 싶은 가치 차이가 실제 이야기에서 '
        '작동해야 합니다. 자기 사진에 대한 애착만으로 실험적 소유효과 입증이라고 쓰지 않습니다. 분석·changes에 연출·이론 적용의 한계를 기록합니다. '
        'SSD·카드리더·자동 공간 확보·자동 백업·특정 모델 기본 자석·가격·호환 보장을 발명하지 않습니다. '
        '본문 약20~25초로 자연스럽게 연결하고 기능을 두 번 설명하지 않습니다. 댓글 요청을 없애도 제품을 찾고 싶어야 합니다. '
        '썸네일은 두 줄로 짧게, 폰 뒤에 놓인 실제 작은 폴더와 사진 전송/보관이라는 차별적 매력을 호기심으로 연결합니다. '
        '낭독 문장·원작의 특징적 묶음 그대로 복사 금지, A/B 전체 전개 구별, C만 흐름 유지. '
        '시청자의 반응/조회 성과를 보장하지 않습니다. 확보 소스 수는 집필 조건에 넣지 않습니다.\n\n' + contract['prompt'],
        json.dumps(payload, ensure_ascii=False), SCHEMA, lambda: None, state)
    validate_triplet(value)
    scripts = []
    for v in value['variants']:
        checked = review(v['text'], corrected['reference_script'], keyword='폴더', contract=contract)
        checked.update(**{k: x for k, x in v.items() if k != 'text'}, human_review_pending=True)
        scripts.append(checked)
    _atomic_json(out, {'scripts': scripts, 'analysis': {k: x for k, x in value.items() if k != 'variants'},
                      'writing_contract': receipt(contract), 'calls': state['calls'],
                      'generation_model': 'codex-cli', 'human_review_pending': True,
                      'previous': str(root / 'quality-v4.json')})
    print('Folder hook repair: new three proposals saved', flush=True)


if __name__ == '__main__':
    main()
