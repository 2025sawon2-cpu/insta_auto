import copy

from hotpost.config import Settings
from hotpost.scene_requirements import assess, coverage_current, input_signature
from test_scene_requirement_intervals import approved, coverage


def test_explicit_alternative_has_separate_cache_and_full_evidence_binding(tmp_path):
    state = approved(tmp_path)
    settings = Settings(data_dir=tmp_path)
    first = assess(settings, state, generate=lambda *a, **k: coverage(state['sources'][0]))
    state['daily_quality']['scene_requirements'] = first
    calls = []
    def generate(*args, **kwargs):
        calls.append(args)
        return coverage(state['sources'][0])
    alternative = assess(settings, state, generate=generate, candidate_source_ids=['source'])
    assert calls and alternative['ready']
    assert alternative['signature'] == input_signature(state)
    state['daily_quality']['scene_requirements'] = alternative
    assert coverage_current(state)
    assert assess(settings, state, generate=lambda *a, **k: (_ for _ in ()).throw(AssertionError()),
                  candidate_source_ids=['source']) == alternative
    from pathlib import Path
    Path(state['sources'][0]['mask_review']['evidence_frames'][0]['path']).write_bytes(b'changed')
    assert not coverage_current(state)


def test_alternative_scope_never_uses_excluded_or_ineligible_source(tmp_path):
    state = approved(tmp_path)
    state['daily_quality']['scene_requirements'] = assess(Settings(data_dir=tmp_path), state,
        generate=lambda *a, **k: coverage(state['sources'][0]))
    other = copy.deepcopy(state['sources'][0]); other.update(id='other', editing_eligible=False)
    state['sources'].append(other)
    def no_model(*a, **k):
        raise AssertionError('No actual eligible candidate in this scope')
    for ids in ([], ['absent'], ['other']):
        result = assess(Settings(data_dir=tmp_path), state, generate=no_model, candidate_source_ids=ids)
        assert not result['ready'] and not result['assessments']
