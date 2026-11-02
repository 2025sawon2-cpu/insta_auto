import json
from types import SimpleNamespace

import pytest

from hotpost.writing.hook_policy import first_sentence
from hotpost.writing.script_style import question_ending_issues
from hotpost.writing.checks import review


@pytest.mark.parametrize('text', [
    '만지작거리는 편이에요?', '이런 제품 써본 적 있으신 거예요？',
    '어떤 제품에요 ?', '이게 키링이에요…?', '그런 편이에요” ?',
    '만지작거리는 편이에요!?', '그런 편이에요！？', '좋은 키링이에요\u200b?',
])
def test_forbidden_question_forms_are_reported_without_rewriting(text):
    assert question_ending_issues(text)
    result = review(text, '참고 제품 설명')
    assert result['text'] == text
    assert any('질문형' in item for item in result['quality_summary']['issues'])


@pytest.mark.parametrize('text', [
    '손이 심심할 때 만지시는 편이세요?', '이 귤 키링 보세요.',
    '이건 귤 키링이에요. 다시 오므릴 수 있어요.', '왜 다시 펼쳐질까요?',
    '귤 키링이에요. 직접 만져보시겠어요?',
])
def test_honorific_questions_statements_and_other_question_forms_are_preserved(text):
    assert not question_ending_issues(text)


def test_opening_evidence_preserves_decimal_and_actual_punctuation():
    assert first_sentence('  3.5초 만에 접는 의자예요! 뒤 문장은 별개예요. ') == '3.5초 만에 접는 의자예요!'
    assert first_sentence('첫 문장만 확인하세요？ 뒤는 보지 않아요.') == '첫 문장만 확인하세요？'


def test_later_fluency_cannot_beat_a_stronger_first_sentence(tmp_path, monkeypatch):
    from hotpost.studio_top_pick import choose
    monkeypatch.setattr('hotpost.studio_top_pick.refresh_local_reviews', lambda settings, reference, valid: valid)
    def assess(settings, instruction, evidence):
        assert 'FIRST SENTENCE' in instruction and 'generic habit questions' in instruction
        assert 'curiosity, not explaining the product identity' in instruction
        assert 'progressively resolve' in instruction
        assert evidence['candidates'][0]['first_sentence'] == '가방에 달린 귤, 진짜로 껍질이 벗겨져요.'
        assert evidence['candidates'][1]['first_sentence'] == '귤 하나를 계속 까는데, 먹을 차례가 안 와요.'
        return {'evaluations':[
            {'index':0,'eligible':True,'scores':{'hook':2,'grounding':5,'narration':5},'reason':'기능을 설명해 의문이 끝남','issues':[]},
            {'index':1,'eligible':True,'scores':{'hook':5,'grounding':4,'narration':2},'reason':'왜 먹지 못하는지 구체적 의문이 남음','issues':[]}]}
    monkeypatch.setattr('hotpost.studio_top_pick._generate', assess)
    candidates = [(0,{'text':'가방에 달린 귤, 진짜로 껍질이 벗겨져요. 손뜨개 키링을 설명해요.'}),
                  (1,{'text':'귤 하나를 계속 까는데, 먹을 차례가 안 와요. 껍질을 다시 덮어요.'})]
    _, result = choose(SimpleNamespace(data_dir=tmp_path), {'id':'opening','original_text':'원작 제품 설명'}, candidates)
    assert result['evaluations'][0]['total'] > result['evaluations'][1]['total']
    assert result['selected_index'] == 1


def test_scoring_outage_cannot_restore_a_forbidden_question(tmp_path, monkeypatch):
    from hotpost.studio_top_pick import choose
    monkeypatch.setattr('hotpost.studio_top_pick.refresh_local_reviews', lambda settings, reference, valid: valid)
    monkeypatch.setattr('hotpost.studio_top_pick._generate', lambda *args: (_ for _ in ()).throw(RuntimeError('offline')))
    valid = [(0,{'text':'기다릴 때 손이 심심한 편이에요?'}),
             (1,{'text':'이 제품은 뒤집어도 쏟아지지 않아요.'})]
    index, result = choose(SimpleNamespace(data_dir=tmp_path), {'id':'offline','original_text':'원본'}, valid)
    assert index == 1 and result['quality_status'] == 'not_evaluated'
    with pytest.raises(ValueError, match='금지 질문형'):
        choose(SimpleNamespace(data_dir=tmp_path), {'id':'all-banned','original_text':'원본'}, valid[:1])


def test_a_preferred_repair_cannot_introduce_a_banned_question(tmp_path, monkeypatch):
    from hotpost.writing import pipeline
    from hotpost.writing.contract import snapshot
    original = '바닥에 두면 바로 켜지는 작은 조명이에요. 댓글에 ‘나도’ 남겨주세요.'
    proposed = '이런 조명 좋아하는 편이에요? 댓글에 ‘나도’ 남겨주세요.'
    replies = iter([{'issues':[{'quote':'바닥에 두면','reason':'첫 문장의 구체적 매력을 더 분명하게'}]},
                    {'text':proposed}, {'preferred':1,'reason':'잘못된 자동 선호','issues':[]}])
    monkeypatch.setattr(pipeline.codex_writer, 'chat', lambda *args, **kwargs: next(replies))
    result = pipeline._generate_single({'reference_script':'제품은 바닥에 두면 켜져요.', 'writing_contract':snapshot()},
        tmp_path, lambda:None, lambda *args:None, draft=original)
    assert result['scripts'][0]['text'] == original
    audit = json.loads((tmp_path/'writing-audit.json').read_text('utf-8'))
    assert audit['repair']['attempted'] and audit['repair']['accepted'] is False


@pytest.mark.parametrize('phrase', ['괜히 반가워요', '괜히반가워요', '괜히\n반가워요', '괜히\u200b반가워요'])
def test_explicit_emotion_prohibition_is_reported_without_rewriting(phrase):
    text = '겨울 침대에서 쉬는 시간이 ' + phrase + '.'
    result = review(text, '누빔 텐트')
    assert result['text'] == text
    assert any('사용자 금지 표현' in issue for issue in result['quality_summary']['issues'])


def test_greeting_and_natural_emotion_are_not_a_blanket_ban():
    from hotpost.writing.script_style import explicit_expression_issues
    assert not explicit_expression_issues('만나서 반가워요. 누빔 안쪽이 포근해요.')


def test_scoring_outage_cannot_select_explicitly_banned_emotion(tmp_path, monkeypatch):
    from hotpost.studio_top_pick import choose
    monkeypatch.setattr('hotpost.studio_top_pick.refresh_local_reviews', lambda settings, reference, valid: valid)
    monkeypatch.setattr('hotpost.studio_top_pick._generate', lambda *args: (_ for _ in ()).throw(RuntimeError('offline')))
    candidates = [(0, {'text': '쉬는 시간이 괜히 반가워요.'}), (1, {'text': '누빔 안쪽에서 책을 읽어요.'})]
    index, _ = choose(SimpleNamespace(data_dir=tmp_path), {'id': 'emotion', 'original_text': '누빔 텐트'}, candidates)
    assert index == 1
    with pytest.raises(ValueError, match='사용자 금지 표현'):
        choose(SimpleNamespace(data_dir=tmp_path), {'id': 'emotion', 'original_text': '누빔 텐트'}, candidates[:1])


def test_model_preference_cannot_introduce_explicitly_banned_emotion(tmp_path, monkeypatch):
    from hotpost.writing import pipeline
    from hotpost.writing.contract import snapshot
    original = '누빔 안쪽에서 책을 읽어요. 댓글에 ‘나도’ 남겨주세요.'
    proposed = original.replace('책을 읽어요', '쉬는 시간이 괜히 반가워요')
    replies = iter([{'issues': [{'quote': '책을 읽어요', 'reason': '생활 장면 표현 보완'}]},
                    {'text': proposed}, {'preferred': 1, 'reason': '모델의 잘못된 선호', 'issues': []}])
    monkeypatch.setattr(pipeline.codex_writer, 'chat', lambda *args, **kwargs: next(replies))
    result = pipeline._generate_single({'reference_script': '누빔 안쪽에서 책을 읽을 수 있어요.',
                                       'writing_contract': snapshot()}, tmp_path, lambda: None,
                                      lambda *args: None, draft=original)
    assert result['scripts'][0]['text'] == original
