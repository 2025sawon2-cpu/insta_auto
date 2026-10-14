import sys
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from hotpost.config import Settings
from hotpost import transcript


def write_audio(path, rate=16000):
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((1, 2, rate, 3, 'NONE', 'not compressed'))
        stream.writeframes(np.array([-32768, 0, 32767], dtype='<i2').tobytes())


def test_faster_whisper_receives_normalized_samples_without_av_decoding(tmp_path, monkeypatch):
    audio = tmp_path / 'audio.wav'
    write_audio(audio)
    calls = []
    class Model:
        def __init__(self, *args, **kwargs):
            pass
        def transcribe(self, samples, **kwargs):
            assert isinstance(samples, np.ndarray)
            np.testing.assert_allclose(samples, [-1, 0, 32767 / 32768])
            calls.append(kwargs)
            return iter([SimpleNamespace(text=' 실제 대사 ', start=0, end=1)]), SimpleNamespace(language='ko')
    monkeypatch.setattr(transcript.sys, 'platform', 'win32')
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=Model))
    speech, language, _ = transcript._speech(Settings(data_dir=tmp_path), audio, [])
    assert speech == [{'source': 'speech', 'start': 0.0, 'end': 1.0, 'text': '실제 대사'}]
    assert language == 'ko' and len(calls) == 1


def test_pcm_loader_rejects_wrong_rate_instead_of_changing_speech_speed(tmp_path):
    audio = tmp_path / 'audio.wav'
    write_audio(audio, rate=8000)
    with pytest.raises(ValueError, match='16kHz'):
        transcript._pcm_audio(audio)
