import json
from types import SimpleNamespace
from unittest.mock import patch
from hotpost.config import Settings
from hotpost.production_health import check

def test_browser_health_does_not_claim_logged_in_or_contact_old_service():
    with patch('hotpost.writing.codex_writer.executable',return_value='codex'),patch('hotpost.production_health.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps({'ready':True}))):
        result=check(Settings())
    assert not result['ready']
    assert result['checks']['google_ai_studio']['configured']
    assert not result['checks']['google_ai_studio']['ready']
    assert 'voicebench' not in result['checks']
