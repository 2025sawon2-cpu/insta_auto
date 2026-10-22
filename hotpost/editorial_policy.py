"""User-approved whole-video montage editing, explicit for new productions."""

VERSION = 'normal-speed-editorial-v1'


def policy():
    return {'version': VERSION, 'allow_source_reuse': True,
            'product_reference_is_not_visual_requirement': True,
            'allow_context_reaction': True}


def enabled(plan):
    return (plan.get('editorial_policy') or {}).get('version') == VERSION


class EditorialWindowGap(ValueError):
    """A selected normal-speed clip needs more real adjacent source frames."""

    def __init__(self, message, diagnostics):
        super().__init__(message)
        self.diagnostics = diagnostics
