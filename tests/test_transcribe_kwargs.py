#!/usr/bin/env python3

"""
Unit tests for transcribe._build_transcribe_kwargs — pure kwargs logic, no audio,
no faster-whisper (the module is import-safe without it installed).
Run with: python3 -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

# Make the repo root importable so we can import transcribe.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import transcribe


class TestBuildTranscribeKwargs(unittest.TestCase):
    def test_default_none(self):
        """All-None reproduces today's exact default call."""
        self.assertEqual(
            transcribe._build_transcribe_kwargs(None, None, None),
            {"beam_size": 5},
        )

    def test_default_no_args(self):
        """Called with no args at all -> just beam_size."""
        self.assertEqual(transcribe._build_transcribe_kwargs(), {"beam_size": 5})

    def test_language_only(self):
        """Language is added; no initial_prompt/hotwords keys appear."""
        kw = transcribe._build_transcribe_kwargs("uk", None, None)
        self.assertEqual(kw, {"beam_size": 5, "language": "uk"})
        self.assertNotIn("initial_prompt", kw)
        self.assertNotIn("hotwords", kw)

    def test_initial_prompt_only(self):
        """initial_prompt is passed; hotwords absent."""
        kw = transcribe._build_transcribe_kwargs(None, "Kubernetes deploy", None)
        self.assertEqual(kw, {"beam_size": 5, "initial_prompt": "Kubernetes deploy"})
        self.assertNotIn("hotwords", kw)

    def test_hotwords_only(self):
        """hotwords is passed when initial_prompt is empty."""
        kw = transcribe._build_transcribe_kwargs(None, None, "Kubernetes deploy")
        self.assertEqual(kw, {"beam_size": 5, "hotwords": "Kubernetes deploy"})
        self.assertNotIn("initial_prompt", kw)

    def test_precedence_both_set(self):
        """When both are set, initial_prompt wins and hotwords is dropped."""
        kw = transcribe._build_transcribe_kwargs(None, "bias sentence", "hot words")
        self.assertIn("initial_prompt", kw)
        self.assertNotIn("hotwords", kw)
        self.assertEqual(kw["initial_prompt"], "bias sentence")

    def test_all_three(self):
        """Language + initial_prompt + hotwords -> language + initial_prompt only."""
        kw = transcribe._build_transcribe_kwargs("ru", "prompt", "words")
        self.assertEqual(kw, {"beam_size": 5, "language": "ru", "initial_prompt": "prompt"})

    def test_empty_and_whitespace_omitted(self):
        """Empty/whitespace-only values are treated as absent (preserves default)."""
        self.assertEqual(
            transcribe._build_transcribe_kwargs("  ", "   ", "\t"),
            {"beam_size": 5},
        )
        self.assertEqual(
            transcribe._build_transcribe_kwargs("", "", ""),
            {"beam_size": 5},
        )

    def test_values_are_stripped(self):
        """Surrounding whitespace is stripped before storing."""
        kw = transcribe._build_transcribe_kwargs(" uk ", "  hi there  ", None)
        self.assertEqual(kw["language"], "uk")
        self.assertEqual(kw["initial_prompt"], "hi there")

    def test_whitespace_initial_prompt_falls_back_to_hotwords(self):
        """A whitespace-only initial_prompt is 'empty', so hotwords still apply."""
        kw = transcribe._build_transcribe_kwargs(None, "   ", "Helm chart")
        self.assertEqual(kw, {"beam_size": 5, "hotwords": "Helm chart"})

    def test_beam_size_override(self):
        """beam_size is configurable and always present."""
        kw = transcribe._build_transcribe_kwargs(None, None, None, beam_size=1)
        self.assertEqual(kw, {"beam_size": 1})


if __name__ == "__main__":
    unittest.main()
