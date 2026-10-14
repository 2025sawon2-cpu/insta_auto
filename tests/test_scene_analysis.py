import base64
from collections import Counter

import pytest

from hotpost import studio_ai
from hotpost.scene_analysis import MAX_BATCH_IMAGES, UNOBSERVED


def catalog(tmp_path, count, frame_count=3):
    shots = []
    for i in range(count):
        frames = []
        for j in range(frame_count):
            path = tmp_path / f'shot-{i}-frame-{j}.jpg'
            path.write_bytes(f'actual-shot-{i}-frame-{j}'.encode())
            frames.append(str(path))
        shots.append({'id': f's{i}', 'start': i * 4, 'end': i * 4 + 3, 'frames': frames})
    return shots


def beat(id='b1'):
    return {'id': id, 'text': '와이어를 당겨 고리에 연결해요', 'start': 0, 'end': 2,
            'options': [{'shot_id': 'cyclic-fallback', 'relation': 'direct'}]}

def test_repetition_feedback_retains_six_grounded_alternatives(monkeypatch,tmp_path):
    shots=catalog(tmp_path,7)
    def generate(settings,instruction,evidence,*,media):
        if media:return {'shots':[{'id':sid,'observation':'실제로 보이는 제품 장면'} for sid in evidence['shot_ids']]}
        assert 'up to 6 distinct' in instruction
        return {'beats':[{'id':'b1','options':[{'shot_id':f's{i}','relation':'context','reason':'확인한 상황'} for i in range(7)]}]}
    monkeypatch.setattr(studio_ai,'_generate',generate)
    _,choices=studio_ai.describe_shots(None,shots,[beat()],review_feedback=[{'kind':'repetition','reason':'같은 구도 반복'}])
    assert len(choices['b1']['options'])==6


def test_33_shots_keep_all_99_frames_in_bounded_groups_then_rank_text(monkeypatch, tmp_path):
    shots = catalog(tmp_path, 33)
    calls, received = [], []

    def generate(settings, instruction, evidence, *, media):
        calls.append((evidence, media))
        if media:
            ids = evidence['shot_ids']
            images = [base64.b64decode(p['inlineData']['data']) for p in media if 'inlineData' in p]
            assert len(ids) <= 6 and len(images) <= MAX_BATCH_IMAGES
            assert len(images) == len(ids) * 3
            for i, shot_id in enumerate(ids):
                number = int(shot_id[1:])
                assert images[i*3:i*3+3] == [f'actual-shot-{number}-frame-{j}'.encode() for j in range(3)]
            received.extend(images)
            assert 'beats' not in evidence  # Narration does not bias visual observations.
            return {'shots': [{'id': sid, 'observation': f'{sid}의 확인된 실제 장면'} for sid in ids]}
        assert len(evidence['shots']) == 33
        assert all(s['evidence_status'] == 'observed' for s in evidence['shots'])
        assert evidence['beats'] == [{**{k: beat()[k] for k in ('id', 'text', 'start', 'end')},
                                     'adjacent_narration':beat()['text']}]
        assert evidence['narration_text']==beat()['text']
        return {'beats': [{'id': 'b1', 'options': [{'shot_id': 's32', 'relation': 'direct', 'reason': '실제 고리 연결'}]}]}

    monkeypatch.setattr(studio_ai, '_generate', generate)
    observed, choices = studio_ai.describe_shots(None, shots, [beat()])
    assert len(calls) == 7  # Six visual batches and one text-only ranking request.
    assert calls[-1][1] == []
    assert Counter(received) == Counter(f'actual-shot-{i}-frame-{j}'.encode() for i in range(33) for j in range(3))
    assert len(observed) == 33
    assert choices['b1']['options'][0]['shot_id'] == 's32'


@pytest.mark.parametrize('rank_options',[[],[{'shot_id':'s0','relation':'context','reason':'다른 도포 용기는 해당 스프레이가 아님'}]])
def test_incompatible_product_is_not_resurrected_by_context_or_fallback(monkeypatch,tmp_path,rank_options):
    shots=catalog(tmp_path,2)
    beats=[{**beat('story'),'text':'나갈 준비를 했는데'},
           {**beat('intro'),'text':'이런 스프레이 하나 두고 싶네요'}]
    def generate(settings,instruction,evidence,*,media):
        if media:
            return {'shots':[{'id':'s0','observation':'빨간 접촉식 도포 용기'},
                             {'id':'s1','observation':'의류와 에어로졸 스프레이 캔'}]}
        assert evidence['narration_text']=='나갈 준비를 했는데 이런 스프레이 하나 두고 싶네요'
        assert evidence['beats'][1]['adjacent_narration']==evidence['narration_text']
        return {'beats':[{'id':'story','options':[{'shot_id':'s0','relation':'context','reason':'일상 의류 관리 상황'}]},
                         {'id':'intro','incompatible_subject_shot_ids':['s0','invented'], 'options':rank_options}]}
    monkeypatch.setattr(studio_ai,'_generate',generate)
    _,choices=studio_ai.describe_shots(None,shots,beats)
    assert choices['story']['options'][0]['shot_id']=='s0'
    assert [o['shot_id'] for o in choices['intro']['options']]==['s1']
    assert choices['intro']['incompatible_subject_shot_ids']==['s0']


def test_image_limit_is_enforced_for_variable_frame_counts(monkeypatch, tmp_path):
    shots = catalog(tmp_path, 7, frame_count=5)
    counts = []

    def generate(settings, instruction, evidence, *, media):
        if media:
            counts.append(sum('inlineData' in part for part in media))
            return {'shots': [{'id': sid, 'observation': '실제 프레임 설명'} for sid in evidence['shot_ids']]}
        return {}

    monkeypatch.setattr(studio_ai, '_generate', generate)
    studio_ai.describe_shots(None, shots, [beat()])
    assert counts == [20, 15]


def test_rank_filters_unknown_unobserved_duplicates_and_context_direct(monkeypatch, tmp_path):
    shots = catalog(tmp_path, 3)
    shots[1].update(source_role='context_only', context_usage_limits='일반 요리 상황만')
    calls = []

    def generate(settings, instruction, evidence, *, media):
        calls.append((evidence, media))
        if media:
            # Emulate the service's latest-text label mapping: context must not erase ID.
            labels = [p['text'] for p in media if 'text' in p]
            assert labels[1].startswith('SHOT s1 at ') and 'CONTEXT ONLY' in labels[1]
            return {'shots': [{'id': 's0', 'observation': '줄을 고리에 거는 손'},
                              {'id': 's1', 'observation': '조리대에서 샐러드를 섞는 모습'}]}
        assert [s['id'] for s in evidence['shots']] == ['s0', 's1']
        return {'beats': [{'id': 'unknown-beat', 'options': []}, {'id': 'b1', 'emphasis': True,
            'options': [{'shot_id': 'invented', 'relation': 'direct'},
                        {'shot_id': 's2', 'relation': 'direct'},
                        {'shot_id': 's1', 'relation': 'direct'},
                        {'shot_id': 's1', 'relation': 'direct'},
                        {'shot_id': 's0', 'relation': 'direct'}]}]}

    monkeypatch.setattr(studio_ai, '_generate', generate)
    observations, choices = studio_ai.describe_shots(None, shots, [beat()])
    assert observations['s2']['evidence_status'] == 'unavailable'
    assert observations['s2']['observation'] == UNOBSERVED
    assert set(choices) == {'b1'}
    assert [(o['shot_id'], o['relation']) for o in choices['b1']['options']] == [('s1', 'context'), ('s0', 'direct')]
    assert choices['b1']['emphasis'] == 0


def test_failed_batch_cannot_invent_observations_for_another_batch(monkeypatch, tmp_path):
    shots = catalog(tmp_path, 7)
    calls = []

    def generate(settings, instruction, evidence, *, media):
        calls.append(evidence)
        if media and 's0' in evidence['shot_ids']:
            # s6 exists globally, but its frames have not been supplied in this call.
            return {'shots': [{'id': 's0', 'observation': '실제 관찰'},
                              {'id': 's6', 'observation': '보지 않은 장면을 꾸며 낸 설명'}]}
        if media:
            raise RuntimeError('One vision batch failed')
        assert [s['id'] for s in evidence['shots']] == ['s0']
        return {'beats': [{'id': 'b1', 'options': [{'shot_id': 's6', 'relation': 'direct'}]}]}

    monkeypatch.setattr(studio_ai, '_generate', generate)
    observations, choices = studio_ai.describe_shots(None, shots, [beat()])
    assert observations['s6']['observation'] == UNOBSERVED
    assert choices['b1']['analysis_status'] == 'fallback'
    assert choices['b1']['options'][0]['shot_id'] == 's0'
    assert choices['b1']['options'][0]['relation'] == 'illustration'
    assert '미확인' in choices['b1']['options'][0]['reason']


def test_missing_descriptions_and_missing_files_are_explicit_not_fabricated(monkeypatch, tmp_path):
    shots = catalog(tmp_path, 2)
    shots[1]['frames'][1] = str(tmp_path / 'missing.jpg')
    calls = []

    def generate(settings, instruction, evidence, *, media):
        calls.append(evidence)
        assert evidence['shot_ids'] == ['s0']
        return {'shots': [{'id': 's0', 'observation': ' '},
                          {'id': 's1', 'observation': '프레임이 없는 장면 설명'}]}

    monkeypatch.setattr(studio_ai, '_generate', generate)
    observations, choices = studio_ai.describe_shots(None, shots, [beat()])
    assert len(calls) == 1  # No grounded descriptions: do not ask text model to guess.
    assert all(o['observation'] == UNOBSERVED and o['tags'] == [] for o in observations.values())
    assert all(o['relation'] == 'illustration' and '미확인' in o['reason'] for o in choices['b1']['options'])


def test_oversized_single_shot_is_rejected_before_silent_downsampling(monkeypatch, tmp_path):
    shots = catalog(tmp_path, 1, frame_count=25)
    monkeypatch.setattr(studio_ai, '_generate', lambda *a, **k: pytest.fail('No oversized vision request'))
    with pytest.raises(ValueError, match='24'):
        studio_ai.describe_shots(None, shots, [beat()])


def test_context_usage_limit_string_is_not_split_into_characters(tmp_path):
    path = tmp_path / 'source.mp4'
    plan = {'shots': [{'id': 's', 'path': str(path)}], 'beats': []}
    source = {'path': str(path), 'sha256': 'known', 'functional_review': {'reviewed': True,
        'same_core_function': False, 'context_usable': True, 'context_usage_limits': '요리 상황만',
        'source_sha256': 'known'}}
    studio_ai.restrict_context_shots(plan, [source])
    assert plan['shots'][0]['context_usage_limits'] == ['요리 상황만']


def test_blank_opening_and_shopping_interface_cannot_be_ranked(monkeypatch,tmp_path):
    from PIL import Image, ImageDraw
    shots=catalog(tmp_path,3)
    Image.new('RGB',(1080,1920),'white').save(shots[0]['frames'][0])
    product=Image.new('RGB',(1080,1920),'white')
    ImageDraw.Draw(product).rectangle((200,600,850,1300),fill='gray')
    product.save(shots[2]['frames'][0])
    def generate(settings,instruction,evidence,*,media):
        if media:
            return {'shots':[{'id':s['id'],'observation':'실제 제품 프레임',
                'visual_type':'shopping_interface' if s['id']=='s1' else 'product'} for s in shots]}
        assert [s['id'] for s in evidence['shots']]==['s2']
        return {'beats':[{'id':'b1','options':[{'shot_id':'s0','relation':'context'},
            {'shot_id':'s1','relation':'context'},{'shot_id':'s2','relation':'context'}]}]}
    monkeypatch.setattr(studio_ai,'_generate',generate)
    observed,choices=studio_ai.describe_shots(None,shots,[beat()])
    assert observed['s0']['selection_exclusion']=='blank_opening'
    assert observed['s1']['selection_exclusion']=='shopping_interface'
    assert [o['shot_id'] for o in choices['b1']['options']]==['s2']


def test_normal_white_background_product_is_not_a_blank_opening(tmp_path):
    from PIL import Image, ImageDraw
    from hotpost.scene_analysis import blank_opening
    frame=tmp_path/'product.jpg'
    image=Image.new('RGB',(1080,1920),'white')
    ImageDraw.Draw(image).rectangle((300,700,800,1200),fill='#bbbbbb')
    image.save(frame)
    assert not blank_opening({'frames':[str(frame)]})


def test_all_blank_samples_require_recollection_without_reusing_excluded_frames(monkeypatch,tmp_path):
    from PIL import Image
    shots=catalog(tmp_path,1)
    Image.new('RGB',(1080,1920),'white').save(shots[0]['frames'][0])
    def generate(settings,instruction,evidence,*,media):
        assert media
        return {'shots':[{'id':'s0','observation':'흰 전환 화면','visual_type':'blank_transition'}]}
    monkeypatch.setattr(studio_ai,'_generate',generate)
    observations,choices=studio_ai.describe_shots(None,shots,[beat()])
    assert observations['s0']['selection_exclusion']=='blank_opening'
    assert choices['b1']['analysis_status']=='no_usable_scenes'
    assert choices['b1']['options']==[]


def test_core_function_acceptance_preserves_product_specific_limits_through_ranking(monkeypatch,tmp_path):
    path=tmp_path/'shoe.mp4'
    frame=tmp_path/'frame.jpg';frame.write_bytes(b'actual shoe frame')
    limits=['Different color/model; cannot prove exact featured product or comfort']
    source={'path':str(path),'sha256':'known','functional_review':{'reviewed':True,
        'same_core_function':True,'context_usable':True,'context_usage_limits':limits,
        'source_sha256':'known'}}
    plan={'shots':[{'id':'shoe','path':str(path),'start':0,'end':2,'frames':[str(frame)]}],
          'beats':[beat()]}
    studio_ai.restrict_context_shots(plan,[source])
    assert plan['shots'][0]['context_usage_limits']==limits
    assert plan['shots'][0].get('source_role')!='context_only'

    def generate(settings,instruction,evidence,*,media):
        if media:
            assert 'USAGE LIMITS' in media[0]['text'] and limits[0] in media[0]['text']
            return {'shots':[{'id':'shoe','observation':'운동화 측면을 손에 들어 보여준다'}]}
        assert evidence['shots'][0]['context_usage_limits']==limits
        return {'beats':[{'id':'b1','options':[{'shot_id':'shoe','relation':'context'}]}]}

    monkeypatch.setattr(studio_ai,'_generate',generate)
    _,choices=studio_ai.describe_shots(None,plan['shots'],plan['beats'])
    assert choices['b1']['options'][0]['relation']=='context'


def test_usage_limits_from_a_different_file_hash_are_not_carried_forward(tmp_path):
    path=tmp_path/'shoe.mp4'
    source={'path':str(path),'sha256':'new','functional_review':{'reviewed':True,
        'same_core_function':True,'context_usage_limits':['Old product restrictions'],
        'source_sha256':'old'}}
    plan={'shots':[{'id':'shoe','path':str(path)}],'beats':[]}
    studio_ai.restrict_context_shots(plan,[source])
    assert 'context_usage_limits' not in plan['shots'][0]


@pytest.mark.parametrize('relation', ['direct', 'context', 'illustration'])
def test_opposite_motion_cannot_return_as_context_or_fallback(monkeypatch, tmp_path, relation):
    shots = catalog(tmp_path, 2)
    def generate(settings, instruction, evidence, *, media):
        if media:
            return {'shots': [{'id': 's0', 'observation': '다리를 밖으로 펼친다'},
                              {'id': 's1', 'observation': '이미 다리가 접힌 카트를 보여준다'}]}
        return {'beats': [{'id': 'b1', 'options': [
            {'shot_id': 's0', 'relation': relation, 'action_match': 'opposite'},
            # The duplicate cannot reintroduce an excluded shot either.
            {'shot_id': 's0', 'relation': 'context'}]}]}
    monkeypatch.setattr(studio_ai, '_generate', generate)
    _, choices = studio_ai.describe_shots(None, shots, [dict(beat(), text='다리를 접어 카트로 바꿔요')])
    assert choices['b1']['opposite_shot_ids'] == ['s0']
    assert choices['b1']['analysis_status'] == 'fallback'
    assert [o['shot_id'] for o in choices['b1']['options']] == ['s1']


def test_folded_state_is_usable_context_and_unknown_exclusion_is_ignored(monkeypatch, tmp_path):
    shots = catalog(tmp_path, 2)
    def generate(settings, instruction, evidence, *, media):
        if media:
            return {'shots': [{'id': 's0', 'observation': '다리를 펼친다'},
                              {'id': 's1', 'observation': '다리가 접힌 카트의 바퀴'}]}
        return {'beats': [{'id': 'b1', 'opposite_shot_ids': ['s0', 'invented'],
            'options': [{'shot_id': 's1', 'relation': 'direct', 'action_match': 'not_established'}]}]}
    monkeypatch.setattr(studio_ai, '_generate', generate)
    _, choices = studio_ai.describe_shots(None, shots, [beat()])
    assert choices['b1']['analysis_status'] == 'ranked'
    assert choices['b1']['opposite_shot_ids'] == ['s0']
    assert choices['b1']['options'][0]['action_match'] == 'not_established'
    assert choices['b1']['options'][0]['relation'] == 'context'


def test_all_opposed_shots_are_not_silently_reused(monkeypatch, tmp_path):
    shots = catalog(tmp_path, 1)
    def generate(settings, instruction, evidence, *, media):
        if media: return {'shots': [{'id': 's0', 'observation': '다리를 펼친다'}]}
        return {'beats': [{'id': 'b1', 'opposite_shot_ids': ['s0'], 'options': []}]}
    monkeypatch.setattr(studio_ai, '_generate', generate)
    _, choices = studio_ai.describe_shots(None, shots, [beat()])
    assert choices['b1']['options'] == []
    assert choices['b1']['analysis_status'] == 'opposite_only'


def test_logo_only_card_is_excluded_but_brand_on_actual_garment_remains(monkeypatch,tmp_path):
    shots=catalog(tmp_path,2)
    def generate(settings,instruction,evidence,*,media):
        if media:
            return {'shots':[{'id':'s0','observation':'로고만 표시된 카드','visual_type':'logo_only'},
                {'id':'s1','observation':'브랜드 로고가 있는 패딩 전체 착용','visual_type':'product'}]}
        assert [s['id'] for s in evidence['shots']]==['s1']
        return {'beats':[{'id':'b1','options':[{'shot_id':'s0','relation':'context'},{'shot_id':'s1','relation':'context'}]}]}
    monkeypatch.setattr(studio_ai,'_generate',generate)
    observations,choices=studio_ai.describe_shots(None,shots,[beat()])
    assert observations['s0']['selection_exclusion']=='logo_only'
    assert [o['shot_id'] for o in choices['b1']['options']]==['s1']
