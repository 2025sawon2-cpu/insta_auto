from types import SimpleNamespace
import pytest
from hotpost.studio_services import ensure_local

def test_cloud_voice_never_starts_service_or_needs_local_settings(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**kw:pytest.fail('No TTS service'))
    ensure_local(SimpleNamespace(),'voice')

def test_script_reuses_existing_codex_entrypoint(monkeypatch):
    seen=[]
    monkeypatch.setattr('hotpost.writing.codex_writer.executable',lambda:seen.append(True) or 'codex')
    ensure_local(SimpleNamespace(),'script')
    assert seen==[True]
