from hotpost import config

def test_google_tts_needs_no_local_checkout_or_key():
    settings=config.Settings()
    assert not any(k.startswith('voicebench_') for k in vars(settings))
    assert settings.studio_api_key_file.name=='unused-legacy-key'
