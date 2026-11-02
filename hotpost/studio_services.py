"""Check existing entrypoints; never launch a TTS service."""
def ensure_local(settings, kind):
    if kind == 'script':
        from .writing.codex_writer import executable
        executable()
    elif kind != 'voice':
        raise ValueError('Unknown work kind')
    # The agent verifies existing Chrome login/model/Arlo before submission.
