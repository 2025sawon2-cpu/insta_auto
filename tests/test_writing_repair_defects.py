from hotpost.writing.pipeline import repair_preserves_integrity


def result(issues, advisories=()):
    return {'integrity_review':{'issues':issues},'quality_summary':{'issues':list(advisories)}}


def test_fixing_one_fact_cannot_trade_for_different_fact_error_with_equal_issue_count():
    old = {'code':'quantity_changed','severity':'critical','quote':'3개','source_quote':'2개'}
    new = {'code':'storage_reversal','severity':'critical','quote':'상온 보관','source_quote':'냉장 보관'}
    assert not repair_preserves_integrity(result([old]), result([new]))


def test_improvement_is_not_rejected_only_because_optional_issue_count_increases():
    old = {'code':'quantity_changed','severity':'critical','quote':'3개','source_quote':'2개'}
    assert repair_preserves_integrity(result([old]), result([], ['말투 의견','선호 의견']))
