from __future__ import annotations

import hashlib
import tempfile
import unittest
import wave
from pathlib import Path

from hotpost.ai_studio_adapter import accept_browser_result, prepare_browser_request, SpeechRequest


class AIStudioBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.request = SpeechRequest(" 첫 문장 123원.\n마지막 문장까지 읽어요. ",
                                     self.root / "out.wav")
        self.prepared = prepare_browser_request(
            self.request, model="gemini-3.8-flash-tts", voice_name="test voice",
            voice_description="Synthetic Korean voice", style="Warm and clear")
        self.download = self.root / "download.wav"
        with wave.open(str(self.download), "wb") as wav:
            wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            wav.writeframes(b"\x01\x00" * 2400)
        self.receipt = {k: v for k, v in self.prepared.items() if k != "text"}
        self.receipt.update(fresh_audio=True, audio_sha256=hashlib.sha256(
            self.download.read_bytes()).hexdigest())

    def accept(self):
        return accept_browser_result(self.request, self.prepared, self.receipt, self.download)

    def test_whole_script_without_cloning_inputs_or_fake_seed(self):
        self.assertEqual(self.prepared["text"], self.request.text)
        for key in ("seed", "reference", "reference_text", "output"):
            self.assertNotIn(key, self.prepared)
        self.assertNotIn("private", str(self.prepared))
        result = self.accept()
        self.assertEqual(self.request.output.read_bytes(), self.download.read_bytes())
        self.assertEqual(result["duration_seconds"], .1)
        self.assertIs(result["quality_verified"], False)
        self.assertIs(result["seed_supported"], False)

    def test_receipt_rejects_another_request_voice_style_or_stale_audio(self):
        for key in ("request_id", "request_sha256", "text_sha256", "model", "voice_name",
                    "voice_description", "style", "profile_name", "audio_sha256", "fresh_audio"):
            original = self.receipt[key]
            self.receipt[key] = False if key == "fresh_audio" else "different"
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.accept()
            self.assertFalse(self.request.output.exists())
            self.receipt[key] = original

    def test_changed_preparation_or_engine_script_cannot_be_imported(self):
        self.prepared["style"] = "different"
        with self.assertRaisesRegex(ValueError, "changed"):
            self.accept()
        self.prepared["style"] = "Warm and clear"
        self.request = SpeechRequest("different", self.request.output)
        with self.assertRaisesRegex(ValueError, "script"):
            self.accept()

    def test_download_validation_does_not_overwrite_existing_output(self):
        self.request.output.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            self.accept()
        self.assertEqual(self.request.output.read_bytes(), b"existing")

    def test_corrupt_truncated_and_empty_audio_rejected(self):
        original = self.download.read_bytes()
        for data in (b"not a wav", original[:-2], original[:44], original[:44] + bytes(4800)):
            self.download.write_bytes(data)
            self.receipt["audio_sha256"] = hashlib.sha256(data).hexdigest()
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                self.accept()
            self.assertFalse(self.request.output.exists())

    def test_required_configuration_is_not_silently_defaulted(self):
        for key in ("model", "voice_name", "voice_description", "style"):
            settings = dict(model="model", voice_name="voice", voice_description="description", style="style")
            settings[key] = ""
            with self.subTest(key=key), self.assertRaises(ValueError):
                prepare_browser_request(self.request, **settings)


if __name__ == "__main__":
    unittest.main()
