"""Shared first-sentence review instruction and literal opening evidence."""
import re

POLICY = 'audience-relevant-first-sentence-20261028-v3'
INSTRUCTION = (
    'Evaluate the FIRST SENTENCE by itself before considering the rest of the narration. '
    'It must be the strongest hook: a concrete recognizable situation, desire, overlooked possibility or '
    'unexpected result that opens meaningful interest and makes the viewer want the next scene. '
    'Evaluate relevance to women in their 30s and 40s who may care about this subject without assuming '
    'their family, household role or tastes. Explain the specific lived inconvenience, desired change, '
    'pleasure or stake that makes THIS opening worth their attention. A physical up/down/left/right '
    'direction puzzle or description of a hand movement is not strong merely because it is unresolved. '
    'Consider why a viewer would care about its answer and whether the image makes that answer trivial. '
    'Reject contrived contradictions and generic advertising when the actual wording offers little payoff. '
    'The goal is curiosity, not explaining the product identity or function immediately. '
    'Do not reveal the identity, function and answer all at once in the opening. '
    'Do not penalize a missing product name or a reveal in later sentences. A generic habit question, '
    'viewer address or psychological-mechanism label alone is not a strong hook. '
    'Do not assume a thumbnail or CTA will make a weak opening work. '
    'Quote the actual opening, name the viewer interest or unresolved question and explain why the viewer wants the next scene; '
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
