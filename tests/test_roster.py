#!/usr/bin/env python3

"""
Unit tests for roster.py — pure stdlib logic, no requests/faster-whisper/ollama.
Run with: python3 -m unittest discover -s tests
"""

import sys
import tempfile
import unittest
from pathlib import Path

# Make the repo root importable so we can import roster.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import roster


class TestParseRoster(unittest.TestCase):
    def test_full_line(self):
        people = roster.parse_roster("Viktor | frontend developer | Витя, Vitya")
        self.assertEqual(len(people), 1)
        p = people[0]
        self.assertEqual(p.name, "Viktor")
        self.assertEqual(p.role, "frontend developer")
        self.assertEqual(p.aliases, ["Витя", "Vitya"])
        self.assertFalse(p.is_self)

    def test_name_only(self):
        (p,) = roster.parse_roster("Alik")
        self.assertEqual(p.name, "Alik")
        self.assertIsNone(p.role)
        self.assertEqual(p.aliases, [])

    def test_name_and_role_no_aliases(self):
        (p,) = roster.parse_roster("Roman | scrum master")
        self.assertEqual(p.name, "Roman")
        self.assertEqual(p.role, "scrum master")
        self.assertEqual(p.aliases, [])

    def test_self_marker(self):
        (p,) = roster.parse_roster("* Yuriy | CTO | Юрий")
        self.assertTrue(p.is_self)
        self.assertEqual(p.name, "Yuriy")
        self.assertEqual(p.role, "CTO")
        self.assertEqual(p.aliases, ["Юрий"])

    def test_self_marker_no_space(self):
        (p,) = roster.parse_roster("*Yuriy | CTO")
        self.assertTrue(p.is_self)
        self.assertEqual(p.name, "Yuriy")

    def test_comments_blanks_and_malformed_skipped(self):
        text = "\n".join([
            "# a comment",
            "   ",
            "Viktor | frontend",
            "|  | just pipes",   # empty name -> skipped
            "*  ",                # self marker but empty name -> skipped
            "Eduard",
        ])
        people = roster.parse_roster(text)
        self.assertEqual([p.name for p in people], ["Viktor", "Eduard"])

    def test_empty_role_column_is_none(self):
        (p,) = roster.parse_roster("Roman |  | Роман")
        self.assertIsNone(p.role)
        self.assertEqual(p.aliases, ["Роман"])

    def test_alias_whitespace_trimmed_and_empties_dropped(self):
        (p,) = roster.parse_roster("Viktor | dev |  Витя , , Vitya ")
        self.assertEqual(p.aliases, ["Витя", "Vitya"])


class TestResolveSelf(unittest.TestCase):
    def test_explicit_name_wins(self):
        people = roster.parse_roster("* Bob | boss")
        name, role = roster.resolve_self(people, "Yuriy", "CTO")
        self.assertEqual((name, role), ("Yuriy", "CTO"))

    def test_explicit_name_without_role(self):
        name, role = roster.resolve_self([], "Yuriy", None)
        self.assertEqual((name, role), ("Yuriy", None))

    def test_falls_back_to_self_line(self):
        people = roster.parse_roster("* Yuriy | CTO\nViktor | dev")
        name, role = roster.resolve_self(people)
        self.assertEqual((name, role), ("Yuriy", "CTO"))

    def test_none_when_nothing_set(self):
        people = roster.parse_roster("Viktor | dev")
        self.assertEqual(roster.resolve_self(people), (None, None))

    def test_blank_explicit_name_ignored(self):
        people = roster.parse_roster("* Yuriy | CTO")
        name, _ = roster.resolve_self(people, "   ", None)
        self.assertEqual(name, "Yuriy")


class TestRosterPromptBlock(unittest.TestCase):
    def test_empty_returns_empty_string(self):
        self.assertEqual(roster.roster_prompt_block([]), "")

    def test_no_people_but_explicit_self(self):
        block = roster.roster_prompt_block([], "Yuriy", "CTO")
        self.assertIn("Yuriy — CTO", block)
        self.assertIn('labelled "You"', block)

    def test_lists_people_roles_aliases(self):
        people = roster.parse_roster(
            "* Yuriy | CTO / dev lead | Юрий\n"
            "Viktor | frontend developer | Витя, Vitya\n"
            "Roman | scrum master"
        )
        block = roster.roster_prompt_block(people)
        self.assertIn("- Yuriy — CTO / dev lead", block)
        self.assertIn('labelled "You"', block)   # self annotated
        self.assertIn("Viktor — frontend developer (aka Витя, Vitya)", block)
        self.assertIn("- Roman — scrum master", block)
        # Leading + trailing newline so the prompt slot spaces cleanly.
        self.assertTrue(block.startswith("\n"))
        self.assertTrue(block.endswith("\n"))

    def test_name_only_person_has_no_dash_role(self):
        people = roster.parse_roster("Alik")
        block = roster.roster_prompt_block(people)
        self.assertIn("- Alik", block)
        self.assertNotIn("Alik —", block)

    def test_guardrail_language_present(self):
        block = roster.roster_prompt_block(roster.parse_roster("Viktor | dev"))
        self.assertIn("do not invent", block.lower())

    def test_closed_set_language_present(self):
        block = roster.roster_prompt_block(roster.parse_roster("Viktor | dev"))
        self.assertIn("complete set", block.lower())


class TestLoadRoster(unittest.TestCase):
    def test_missing_dir_returns_empty(self):
        self.assertEqual(roster.load_roster("/no/such/dir"), [])
        self.assertEqual(roster.load_roster(""), [])
        self.assertEqual(roster.load_roster(None), [])

    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(roster.load_roster(d), [])

    def test_reads_roster_file(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "roster.txt").write_text(
                "* Yuriy | CTO\nViktor | frontend | Витя\n", encoding="utf-8"
            )
            people = roster.load_roster(d)
            self.assertEqual([p.name for p in people], ["Yuriy", "Viktor"])
            self.assertTrue(people[0].is_self)

    def test_named_roster_selects_variant_file(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "roster.txt").write_text("Default | x\n", encoding="utf-8")
            (Path(d) / "roster.sigma.txt").write_text("Sigma | y\n", encoding="utf-8")
            self.assertEqual([p.name for p in roster.load_roster(d)], ["Default"])
            self.assertEqual(
                [p.name for p in roster.load_roster(d, "sigma")], ["Sigma"]
            )
            # Missing named file -> [] (no fallback to default), so a typo is visible.
            self.assertEqual(roster.load_roster(d, "nope"), [])

    def test_load_roster_file_explicit_path(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "custom-team.txt"
            p.write_text("Bob | boss\n", encoding="utf-8")
            self.assertEqual([x.name for x in roster.load_roster_file(str(p))], ["Bob"])
            self.assertEqual(roster.load_roster_file(str(Path(d) / "missing.txt")), [])
            self.assertEqual(roster.load_roster_file(None), [])


if __name__ == "__main__":
    unittest.main()
