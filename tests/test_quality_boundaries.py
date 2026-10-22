from hotpost.quality_boundaries import boundary_indices


def test_legacy_padding_boundaries_include_both_confirmed_leaks():
    plan=dict(duration=16.488095,fps=30,beats=[],rendered_clips=[
        dict(start=0,duration=70/30),dict(start=70/30,duration=318/30),
        dict(start=388/30,duration=107/30)])
    indices=boundary_indices(plan)
    assert {0,1,69,70,71,387,388,389,494}<=set(indices)
    assert 495 not in indices


def test_interior_mask_boundaries_and_one_frame_are_sampled():
    plan=dict(duration=1,fps=30,beats=[],rendered_clips=[dict(start=0,duration=1,
        watermark_masks=[dict(source_start=10/30,source_end=11/30)])])
    assert {9,10,11,12}<=set(boundary_indices(plan))
