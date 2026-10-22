"""Distinguish visual rejection, malformed responses and pending evidence."""
import copy
import time

POLICY = 'source-review-outcome-v1'


class ReviewResponseInvalid(ValueError):
    pass


class NoApprovedOverlayIntervals(ValueError):
    def __init__(self, review, receipt_path):
        super().__init__('독립 가림 검토 완료 · 승인 가능한 구간 없음')
        self.review = copy.deepcopy(review)
        self.receipt_path = str(receipt_path)


def failed_outcome(stage, exc, source, *, scope=None):
    from .model_service import ModelServiceUnavailable, ModelResponseInvalid
    from .studio_pause import StudioPaused
    if isinstance(exc, StudioPaused):
        status, code = 'interrupted', 'operation_paused'
    elif isinstance(exc, NoApprovedOverlayIntervals):
        status, code = 'no_usable_intervals', 'overlay_intervals_rejected'
    elif isinstance(exc, (ReviewResponseInvalid, ModelResponseInvalid)):
        status, code = 'response_error', 'invalid_review_response'
    elif isinstance(exc, ModelServiceUnavailable):
        status, code = 'service_wait', 'model_service_wait'
    else:
        status, code = 'unconfirmed', 'review_evidence_unconfirmed'
    value = dict(policy=POLICY, stage=stage, status=status, code=code,
                 source_sha256=source.get('sha256'), scope=copy.deepcopy(scope),
                 reason=str(exc)[:1000], checked_at=time.time())
    if isinstance(exc, NoApprovedOverlayIntervals):
        value.update(rejected_intervals=exc.review.get('rejected_intervals', []),
                     receipt_path=exc.receipt_path)
    return value


def review_status(source):
    """New typed results take precedence; legacy unknowns never become approval."""
    value = source.get('review_outcome') or {}
    if value.get('policy') == POLICY and value.get('source_sha256') == source.get('sha256'):
        if value.get('status') not in {'overlay_approved','approved'}:
            return value.get('status', 'unconfirmed')
    error = source.get('overlay_review_error') or source.get('presentation_review_error')
    if error:
        if error in ('Visual region proposal omitted or repeated actual frames', 'Invalid visual region count'):
            return 'response_error'
        return 'unconfirmed'
    if source.get('relevance_review_required') or source.get('presentation_review_required'):
        return 'pending'
    return None


def is_transient(source, stage):
    value = source.get('review_outcome') or {}
    if (value.get('policy') == POLICY and value.get('source_sha256') == source.get('sha256')
            and value.get('stage') == stage):
        if value.get('status') in {'service_wait','interrupted'}:return True
        # Narrow compatibility for the exact host cancellation formerly stored
        # as unconfirmed. This permits review only; it never grants approval or
        # clears the task's user-pause gate.
        from .studio_pause import PAUSE_MESSAGE
        return (value.get('status')=='unconfirmed' and value.get('code')=='review_evidence_unconfirmed'
                and value.get('reason')==PAUSE_MESSAGE
                and source.get(stage+'_review_error')==PAUSE_MESSAGE)
    from .scene_requirements import is_service_review_error
    return is_service_review_error(source.get(stage + '_review_error'))
