"""Frozen saved v5 contract, independent of the current new-run policy."""
from hotpost.source_policy import current_policy


def saved_v5(settings=None):
    policy=current_policy(settings)
    policy.update(version=5,editorial_policy='normal-speed-editorial-v1',minimum_total=5,
        allow_source_reuse=True,duration_requirement='preference',core_duration_requirement='preference',
        source_diversity_policy={'version':'minimum-five-sources-v1','minimum_parent_sources':5},
        minimum_core_parent_sources=1,search_minimums={'en':5,'zh':5})
    return policy
