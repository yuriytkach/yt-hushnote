#!/usr/bin/env python3

"""
Unit tests for cloud_transcribe — the pure response-mapping and upload-prep
logic, no network and no provider calls. Run with:
    python3 -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

# Make the repo root importable so we can import cloud_transcribe.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cloud_transcribe


class TestMapResponse(unittest.TestCase):
    def test_verbose_json_with_segments(self):
        """A verbose_json payload maps start/end/text and language directly."""
        payload = {
            "language": "russian",
            "text": "Привет мир",
            "segments": [
                {"start": 0.0, "end": 1.5, "text": " Привет"},
                {"start": 1.5, "end": 3.0, "text": " мир "},
            ],
        }
        result = cloud_transcribe._map_response(payload)
        self.assertEqual(result["language"], "russian")
        self.assertEqual(len(result["segments"]), 2)
        self.assertEqual(result["segments"][0], {"start": 0.0, "end": 1.5, "text": "Привет"})
        self.assertEqual(result["segments"][1], {"start": 1.5, "end": 3.0, "text": "мир"})
        self.assertEqual(result["text"], "Привет мир")

    def test_text_only_wrapped_as_single_segment(self):
        """A plain {text} payload (no segments) becomes one 0-0 segment."""
        result = cloud_transcribe._map_response({"text": "hello world"})
        self.assertEqual(result["segments"], [{"start": 0.0, "end": 0.0, "text": "hello world"}])
        self.assertEqual(result["text"], "hello world")

    def test_segments_without_text_join(self):
        """Top-level text is derived by joining segment texts when absent."""
        payload = {"segments": [
            {"start": 0.0, "end": 1.0, "text": "one"},
            {"start": 1.0, "end": 2.0, "text": "two"},
        ]}
        result = cloud_transcribe._map_response(payload)
        self.assertEqual(result["text"], "one two")

    def test_language_fallback(self):
        """Missing language falls back to the provided hint, else empty string."""
        self.assertEqual(
            cloud_transcribe._map_response({"text": "x"}, fallback_language="uk")["language"],
            "uk",
        )
        self.assertEqual(cloud_transcribe._map_response({"text": "x"})["language"], "")

    def test_missing_timestamps_and_text_defaults(self):
        """Missing start/end default to 0.0; missing text to empty (stripped)."""
        payload = {"segments": [{"text": "  hi  "}]}
        result = cloud_transcribe._map_response(payload)
        self.assertEqual(result["segments"][0], {"start": 0.0, "end": 0.0, "text": "hi"})

    def test_empty_payload(self):
        """An empty payload yields empty segments/text and a fallback language."""
        result = cloud_transcribe._map_response({}, fallback_language=None)
        self.assertEqual(result["segments"], [])
        self.assertEqual(result["text"], "")
        self.assertEqual(result["language"], "")

    def test_result_shape_matches_local(self):
        """The returned dict has exactly the keys the rest of the pipeline reads."""
        result = cloud_transcribe._map_response({"text": "x"})
        self.assertEqual(set(result.keys()), {"language", "segments", "text"})

    def test_hallucination_loop_is_dropped(self):
        """A repeated boilerplate phrase across many segments (Groq has no
        condition_on_previous_text guard) is filtered out as a hallucination."""
        payload = {
            "text": "real words. Дякую за перегляд! Дякую за перегляд! Дякую за перегляд! Дякую за перегляд!",
            "segments": [
                {"start": 0.0, "end": 5.0, "text": "real words."},
                {"start": 5.0, "end": 35.0, "text": "Дякую за перегляд!"},
                {"start": 35.0, "end": 65.0, "text": "Дякую за перегляд!"},
                {"start": 65.0, "end": 95.0, "text": "Дякую за перегляд!"},
                {"start": 95.0, "end": 125.0, "text": "Дякую за перегляд!"},
            ],
        }
        result = cloud_transcribe._map_response(payload)
        self.assertEqual(len(result["segments"]), 1)
        self.assertEqual(result["segments"][0]["text"], "real words.")
        self.assertEqual(result["text"], "real words.")

    def test_short_repeat_is_kept(self):
        """Fewer than 3 consecutive identical segments is plausible real speech."""
        payload = {"segments": [
            {"start": 0.0, "end": 1.0, "text": "так"},
            {"start": 1.0, "end": 2.0, "text": "так"},
        ]}
        result = cloud_transcribe._map_response(payload)
        self.assertEqual(len(result["segments"]), 2)


class TestPrepareUpload(unittest.TestCase):
    def test_no_ffmpeg_returns_original(self):
        """Without ffmpeg, upload prep returns the original file untouched."""
        orig = cloud_transcribe.shutil.which
        cloud_transcribe.shutil.which = lambda _name: None
        try:
            path, is_temp = cloud_transcribe._prepare_upload("/tmp/whatever.wav")
        finally:
            cloud_transcribe.shutil.which = orig
        self.assertEqual(path, "/tmp/whatever.wav")
        self.assertFalse(is_temp)


class TestApiKeyGuard(unittest.TestCase):
    def test_missing_key_raises(self):
        """transcribe_via_api refuses to run without an API key (no network)."""
        with self.assertRaises(RuntimeError):
            cloud_transcribe.transcribe_via_api("/tmp/x.wav", api_key="")
        with self.assertRaises(RuntimeError):
            cloud_transcribe.transcribe_via_api("/tmp/x.wav", api_key=None)


if __name__ == "__main__":
    unittest.main()
