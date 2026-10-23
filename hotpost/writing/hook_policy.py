"""Shared first-sentence review instruction and literal opening evidence."""
import re

POLICY = 'first-sentence-product-hook-20261024-v1'
INSTRUCTION = (
    'Evaluate the FIRST SENTENCE by itself before considering the rest of the narration. '
    'It must be the strongest hook: a concrete product-specific surprise, meaningful conflict, '
    'unexpected result or compelling benefit plus a reason to continue. A generic habit question, '
    'viewer address or psychological-mechanism label alone is not a strong hook. '
    'Do not assume a thumbnail, later explanation or CTA will make a weak opening work. '
    'Quote the actual opening and explain why a viewer would stop and what they want to see next. '
    'Do not force every hook into a question or withheld product name; avoid empty bait and invented facts. '
    'A strong first sentence must be followed by its promised payoff, without repeating the opening at the end. '
    'Question endings ~에요?, ~예요?, ~이에요? are forbidden. Rewrite viewer questions naturally with '
    '~세요? forms; never honorify an inanimate product by blind suffix substitution. Statements remain allowed. '
)


def first_sentence(text):
    text = text.strip()
    # Preserve a decimal such as 3.5 while retaining the opening punctuation.
    boundary = re.search(r'(?<!\d)\.|\.(?!\d)|[!?。！？]|\n', text)
    return text[:boundary.end()].strip() if boundary else text
