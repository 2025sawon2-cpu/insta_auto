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
        assert evidence['candidates'][0]['first_sentence'] == '기다릴 때 손이 심심하세요?'
        return {'evaluations':[
            {'index':0,'eligible':True,'scores':{'hook':3,'grounding':5,'narration':5},'reason':'본문은 유창하지만 도입이 약함','issues':[]},
            {'index':1,'eligible':True,'scores':{'hook':5,'grounding':4,'narration':3},'reason':'제품에 관한 첫 문장의 반전','issues':[]}]}
    monkeypatch.setattr('hotpost.studio_top_pick._generate', assess)
    candidates = [(0,{'text':'기다릴 때 손이 심심하세요? 제품을 자세히 설명해요.'}),
                  (1,{'text':'이 조명은 선을 꽂을 곳이 없어요. 바닥에 놓으면 켜져요.'})]
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
