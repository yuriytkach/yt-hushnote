#!/usr/bin/env python3

"""
Unit tests for glossary.py — pure stdlib logic, no requests/faster-whisper/ollama.
Run with: python3 -m unittest discover -s tests
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Make the repo root importable so we can import glossary.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import glossary


class TestNormalizeLanguage(unittest.TestCase):
    def test_none_empty_auto(self):
        self.assertIsNone(glossary.normalize_language(None))
        self.assertIsNone(glossary.normalize_language(""))
        self.assertIsNone(glossary.normalize_language("   "))
        self.assertIsNone(glossary.normalize_language("auto"))
        self.assertIsNone(glossary.normalize_language(" AUTO "))

    def test_codes_lowercased_stripped(self):
        self.assertEqual(glossary.normalize_language("UK"), "uk")
        self.assertEqual(glossary.normalize_language(" Ru "), "ru")
        self.assertEqual(glossary.normalize_language("en"), "en")


class TestParseGlossary(unittest.TestCase):
    def test_skips_comments_and_blanks(self):
        text = "# a comment\n\n   \n# another\n"
        self.assertEqual(glossary.parse_glossary(text), [])

    def test_parses_variants(self):
        entries = glossary.parse_glossary("кубернетіс|кубернетес => Kubernetes")
        self.assertEqual(entries, [(["кубернетіс", "кубернетес"], "Kubernetes")])

    def test_tolerates_extra_spaces(self):
        entries = glossary.parse_glossary("  a  |  b   =>    X  ")
        self.assertEqual(entries, [(["a", "b"], "X")])

    def test_skips_malformed(self):
        # No '=>', empty LHS, and empty RHS are all skipped; the valid line stays.
        text = "no arrow here\n => X\nfoo =>\nбар => Bar"
        self.assertEqual(glossary.parse_glossary(text), [(["бар"], "Bar")])


class TestApplyGlossary(unittest.TestCase):
    def setUp(self):
        self.entries = glossary.parse_glossary(
            "кубернетіс|кубернетес => Kubernetes\n"
            "хелм чарт => helm chart\n"
            "под => pod\n"
        )

    def test_case_insensitive_and_variants(self):
        self.assertEqual(glossary.apply_glossary("кубернетес", self.entries), "Kubernetes")
        self.assertEqual(glossary.apply_glossary("Кубернетес", self.entries), "Kubernetes")
        self.assertEqual(glossary.apply_glossary("кубернетіс", self.entries), "Kubernetes")
        self.assertEqual(glossary.apply_glossary("КУБЕРНЕТЕС", self.entries), "Kubernetes")

    def test_multiword_phrase(self):
        self.assertEqual(
            glossary.apply_glossary("треба зробити хелм чарт зараз", self.entries),
            "треба зробити helm chart зараз",
        )

    def test_whole_word_guard(self):
        # 'под' inside the longer real word 'подключение' must NOT be replaced.
        self.assertEqual(
            glossary.apply_glossary("подключение", self.entries),
            "подключение",
        )
        # standalone token IS replaced
        self.assertEqual(glossary.apply_glossary("це под тут", self.entries), "це pod тут")

    def test_already_correct_target_unchanged(self):
        self.assertEqual(
            glossary.apply_glossary("we run Kubernetes", self.entries),
            "we run Kubernetes",
        )

    def test_empty_entries_identity(self):
        self.assertEqual(glossary.apply_glossary("будь-який текст", []), "будь-який текст")

    def test_cross_entry_longest_first(self):
        # A component-word rule listed BEFORE the multi-word phrase rule must not
        # steal the match: longest-pattern-first is applied across all rules, so
        # file order does not matter.
        entries = glossary.parse_glossary(
            "чарт => chart\n"
            "хелм чарт => helm chart\n"
        )
        self.assertEqual(
            glossary.apply_glossary("треба хелм чарт", entries),
            "треба helm chart",
        )


class TestTermsForPrompt(unittest.TestCase):
    def test_unique_order_stable(self):
        entries = glossary.parse_glossary(
            "a => Kubernetes\n"
            "b => deploy\n"
            "c => Kubernetes\n"  # duplicate target
            "d => Jenkins\n"
        )
        self.assertEqual(
            glossary.terms_for_prompt(entries),
            ["Kubernetes", "deploy", "Jenkins"],
        )

    def test_empty(self):
        self.assertEqual(glossary.terms_for_prompt([]), [])


class TestLoadGlossary(unittest.TestCase):
    def _write(self, directory, name, content):
        (Path(directory) / name).write_text(content, encoding="utf-8")

    def test_shared_plus_language_merged(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "glossary.txt", "графана => Grafana\n")
            self._write(d, "glossary.uk.txt", "кубернетес => Kubernetes\n")
            self._write(d, "glossary.ru.txt", "задеплоить => deploy\n")
            entries = glossary.load_glossary(d, "uk")
            terms = glossary.terms_for_prompt(entries)
            # shared + uk only (NOT ru)
            self.assertIn("Grafana", terms)
            self.assertIn("Kubernetes", terms)
            self.assertNotIn("deploy", terms)

    def test_unknown_language_unions_all(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "glossary.txt", "графана => Grafana\n")
            self._write(d, "glossary.uk.txt", "кубернетес => Kubernetes\n")
            self._write(d, "glossary.ru.txt", "задеплоить => deploy\n")
            entries = glossary.load_glossary(d, None)
            terms = glossary.terms_for_prompt(entries)
            self.assertIn("Grafana", terms)
            self.assertIn("Kubernetes", terms)
            self.assertIn("deploy", terms)

    def test_shared_not_double_counted_for_none(self):
        # `glossary.*.txt` glob must NOT also pick up the shared `glossary.txt`.
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "glossary.txt", "графана => Grafana\n")
            entries = glossary.load_glossary(d, None)
            self.assertEqual(len(entries), 1)

    def test_example_files_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(d, "glossary.uk.txt", "кубернетес => Kubernetes\n")
            self._write(d, "glossary.uk.txt.example", "задеплоить => deploy\n")
            entries = glossary.load_glossary(d, "uk")
            terms = glossary.terms_for_prompt(entries)
            self.assertEqual(terms, ["Kubernetes"])

    def test_missing_dir_and_files(self):
        self.assertEqual(glossary.load_glossary("/nonexistent/path/xyz", "uk"), [])
        self.assertEqual(glossary.load_glossary(None, "uk"), [])
        with tempfile.TemporaryDirectory() as d:
            # empty dir -> no glossary files -> []
            self.assertEqual(glossary.load_glossary(d, "uk"), [])
            self.assertEqual(glossary.load_glossary(d, None), [])


class TestResolveLanguage(unittest.TestCase):
    def test_explicit_wins(self):
        self.assertEqual(glossary.resolve_language("UK", None), "uk")
        self.assertEqual(glossary.resolve_language(" ru ", None), "ru")

    def test_explicit_auto_falls_through(self):
        # 'auto'/'' are not explicit; with no file they resolve to None.
        self.assertIsNone(glossary.resolve_language("auto", None))
        self.assertIsNone(glossary.resolve_language("", None))

    def test_sibling_labeled_json(self):
        with tempfile.TemporaryDirectory() as d:
            transcript = Path(d) / "meeting.txt"
            transcript.write_text("some text", encoding="utf-8")
            (Path(d) / "meeting_speakers_labeled.json").write_text(
                json.dumps({"language": "ru"}), encoding="utf-8"
            )
            self.assertEqual(glossary.resolve_language("", str(transcript)), "ru")

    def test_sibling_plain_json_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            transcript = Path(d) / "meeting.txt"
            transcript.write_text("some text", encoding="utf-8")
            (Path(d) / "meeting.json").write_text(
                json.dumps({"language": "en"}), encoding="utf-8"
            )
            self.assertEqual(glossary.resolve_language(None, str(transcript)), "en")

    def test_sibling_voice_json_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            transcript = Path(d) / "meeting.txt"
            transcript.write_text("some text", encoding="utf-8")
            (Path(d) / "meeting.voice.json").write_text(
                json.dumps({"language": "uk"}), encoding="utf-8"
            )
            self.assertEqual(glossary.resolve_language(None, str(transcript)), "uk")

    def test_labeled_takes_priority_over_plain(self):
        with tempfile.TemporaryDirectory() as d:
            transcript = Path(d) / "meeting.txt"
            transcript.write_text("some text", encoding="utf-8")
            (Path(d) / "meeting_speakers_labeled.json").write_text(
                json.dumps({"language": "uk"}), encoding="utf-8"
            )
            (Path(d) / "meeting.json").write_text(
                json.dumps({"language": "ru"}), encoding="utf-8"
            )
            self.assertEqual(glossary.resolve_language(None, str(transcript)), "uk")

    def test_no_siblings_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            transcript = Path(d) / "meeting.txt"
            transcript.write_text("some text", encoding="utf-8")
            self.assertIsNone(glossary.resolve_language(None, str(transcript)))

    def test_garbage_json_does_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            transcript = Path(d) / "meeting.txt"
            transcript.write_text("some text", encoding="utf-8")
            (Path(d) / "meeting_speakers_labeled.json").write_text(
                "{ not valid json", encoding="utf-8"
            )
            # falls through to None without raising
            self.assertIsNone(glossary.resolve_language(None, str(transcript)))

    def test_json_missing_language_key(self):
        with tempfile.TemporaryDirectory() as d:
            transcript = Path(d) / "meeting.txt"
            transcript.write_text("some text", encoding="utf-8")
            (Path(d) / "meeting.json").write_text(
                json.dumps({"text": "hi", "language": None}), encoding="utf-8"
            )
            self.assertIsNone(glossary.resolve_language(None, str(transcript)))


if __name__ == "__main__":
    unittest.main()
