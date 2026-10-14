"""Recognize common labels for the same writing mechanism, without closing the list.

This compares declared labels only. It cannot establish whether a mechanism
actually operates in the story; that remains part of the per-variant review.
"""
import re
import unicodedata


ALIASES = {
    'loss_aversion': ('손실회피', 'loss aversion'),
    'anchoring': ('앵커링', '가격앵커', '닻내림', '정박효과', 'anchoring'),
    'endowment': ('소유효과', '보유효과', 'endowment effect'),
    'mental_accounting': ('심적회계', '심리적회계', 'mental accounting'),
    'framing': ('프레이밍', '틀짜기효과', 'framing effect'),
    'decoy': ('미끼효과', '유인효과', 'decoy effect', 'attraction effect'),
    'compromise': ('타협효과', '극단회피', 'compromise effect'),
    'contrast': ('대비효과', '대조효과', 'contrast effect'),
    'status_quo': ('현상유지', 'status quo bias'),
    'default': ('기본값효과', '기본값편향', '디폴트효과', 'default effect'),
    'choice_overload': ('선택과부하', 'choice overload'),
    'regret_aversion': ('후회회피', 'regret aversion'),
    'scarcity': ('희소성', 'scarcity effect', 'scarcity bias'),
    'present_bias': ('현재편향', '현재지향편향', 'present bias'),
    'sunk_cost': ('매몰비용', 'sunk cost'),
    'zero_price': ('무료효과', '제로가격효과', 'zero price effect'),
    'social_proof': ('사회적증거', 'social proof'),
    'authority': ('권위효과', '권위편향', 'authority bias', 'authority effect'),
    'social_comparison': ('사회적비교', 'social comparison'),
    'reciprocity': ('상호성', '호혜성', 'reciprocity'),
    'information_gap': ('정보격차', '정보공백', 'information gap'),
    'isolation': ('고립효과', '격리효과', '폰레스토프', 'von restorff', 'isolation effect'),
    'self_reference': ('자기참조', '자기관련성효과', 'self reference', 'self referential effect'),
    'mere_exposure': ('단순노출', '단순접촉', 'mere exposure'),
    'mental_simulation': ('심적시뮬레이션', '멘탈시뮬레이션', 'mental simulation'),
}


def normalize_label(label):
    return re.sub(r'[\W_]', '', unicodedata.normalize('NFKC', label).casefold())


def mechanism_keys(label):
    normalized = normalize_label(label)
    known = {key for key, aliases in ALIASES.items()
             if any(normalize_label(alias) in normalized for alias in aliases)}
    # Unlisted mechanisms remain usable. Do not force every story into the
    # starter catalogue or silently replace an unfamiliar label with a known one.
    return known or {'unlisted:' + normalized}
