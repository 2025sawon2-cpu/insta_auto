"""Shared first-sentence review instruction and literal opening evidence."""
import re

POLICY = 'first-sentence-curiosity-gap-20261024-v2'
INSTRUCTION = (
    'Evaluate the FIRST SENTENCE by itself before considering the rest of the narration. '
    'It must be the strongest hook: a concrete unexpected situation or mismatch between action and result '
    'that opens a specific unresolved question and makes the viewer want the next scene. '
    'The goal is curiosity, not explaining the product identity or function immediately. '
    'Do not reveal the identity, function and answer all at once in the opening. '
    'Do not penalize a missing product name or a reveal in later sentences. A generic habit question, '
    'viewer address or psychological-mechanism label alone is not a strong hook. '
    'Do not assume a thumbnail or CTA will make a weak opening work. '
    'Quote the actual opening, name the unresolved question and explain why the viewer wants the next scene; '
    'check whether the answer has already been given away. Clarity of product explanation is not hook strength. '
    'Do not force a question, withheld name, paradox formula or fixed reveal position; avoid vague bait and invented facts. '
    'The body must progressively resolve the question through clues, actions and results and deliver the product appeal. '
    'Do not extinguish curiosity with an immediate explanatory dump or drag out a reveal without new information. '
    'Do not repeat the opening at the end. Preserve an explicitly user-selected script instead of reranking it. '
    'Question endings ~에요?, ~예요?, ~이에요? are forbidden. Rewrite viewer questions naturally with '
    '~세요? forms; never honorify an inanimate product by blind suffix substitution. Statements remain allowed. '
)


def first_sentence(text):
    text = text.strip()
    # Preserve a decimal such as 3.5 while retaining the opening punctuation.
    boundary = re.search(r'(?<!\d)\.|\.(?!\d)|[!?。！？]|\n', text)
    return text[:boundary.end()].strip() if boundary else text
