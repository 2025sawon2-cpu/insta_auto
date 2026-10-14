"""Review the new first-frame boundary proof once; keep prior center review."""
from .review_rank1_mask_application import OUT, review


if __name__=='__main__':
    review(OUT/'mask-boundary-v2/typed-pending-receipt.json',
        OUT/'mask-boundary-v2/official-first-frame-review.json',
        '4132b26618fa97e974e496e719fb9b2d2a4d51020a6f111e624d5977d50a2d50')
