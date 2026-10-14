"""Shared subject-first visual contract, calibrated against real reference reels."""

POLICY = 'product-appeal-first-20261013-v1'

PRODUCT_APPEAL_INSTRUCTION = (
    'Evaluate the complete video as a product-interest montage: clear promoted subject, visible useful '
    'or attractive aspects, and a coherent engaging sequence. Narration supplies the entertaining story; '
    'footage supplies product appeal. Exact sentence-by-sentence or same-moment visual illustration is '
    'a preference, not a pass/fail requirement. Missing actors, travel, friends, shopping, emotions, '
    'a particular spilled ingredient, or other fictional/everyday story events are not missing required '
    'scenes when actual relevant product/use/detail footage communicates the topic and its appeal. '
    'Product installation, cleaning, texture, styling and usable-state views may support a problem or '
    'benefit line without literally reenacting it. Judge them in the whole narrative and video context. '
    'Repeated appearances of the same product, a return to its hero view, or successive parts of one '
    'demonstration are natural when they add a new view, use, benefit or closure. Reject repetition only '
    'with concrete redundant footage that weakens interest; counts and percentages alone are not defects. '
    'Keep a real distinction between supportive footage and demonstrative proof. Never describe an '
    'unseen action as observed. A supportive shot need not establish the narrated action, but must '
    'remain relevant to the promoted product, use or appeal. Missing literal correspondence is advisory '
    'only and cannot by itself request collection or reediting. Block an actual misleading demonstration '
    '(wrong product/function/part presented as the promoted one, opposite action shown as that action), '
    'a sequence that fails to reveal the promoted product or meaningful appeal, or an evidenced factual '
    'contradiction. Minor color/model/design differences and nonliteral stories are not such contradictions. '
    'A separate accessory must never be labelled the main product\'s own connected part without evidence, '
    'but a relevant accessory can honestly illustrate the general setting without claiming that identity. '
    'Preserve source usage limits and file/time evidence. Only a shot offered as an actual action or '
    'transition demonstration needs evidence of its necessary initial/final states; supportive product '
    'views need evidence of the visible product/use/appeal they actually supply, not proof of absent story events. '
    'Do not inflate casual reference-stated comfort/cushioning copy into a universal guarantee for all '
    'objects, heights or conditions. Flag explicit unsupported universal safety/health promises or concrete '
    'false facts, not an absolute promise invented by the reviewer. Do not rewrite narration to fit footage. '
)


def reference_instruction(render_instruction):
    """Separate observed reference appeal from contractual requirements for our remakes."""
    return (
        render_instruction
        + ' This evaluation is an ORIGINAL reference, not a remake. Its creator watermark, face in a '
        'cover, different comment keyword, personal voice, or missing two-line curiosity format are '
        'project_contract_deviations, not intrinsic failures of reference product appeal. Record those '
        'separately and never use them as reasons to discard its natural montage/story structure. '
        'passed and issues evaluate product communication and real misleading/quality defects only. '
        'Return also product_appeal_summary:string, allowed_mismatches:[{beat_id,time,quote,shown,why_acceptable}], '
        'and project_contract_deviations:[{kind,beat_id,reason}]. Empty allowed_mismatches is valid for '
        'a closely aligned reference; never invent a mismatch. Use exact supplied text and actual times. '
        'Distinguish actual uploaded poster from source first frame. If poster was not supplied, limit '
        'that conclusion to the source first frame; do not claim it is the Instagram poster. '
        'Any blocking issue must identify the actual observed damage to product understanding or appeal; '
        'do not force a pass merely because the post is popular.'
    )
