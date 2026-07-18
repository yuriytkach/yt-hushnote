#!/usr/bin/env python3

"""
Per-language term glossary for HushNote (issue #8).

Meetings mix Russian and Ukrainian speech with embedded English tech terms
(Kubernetes, deploy, Helm chart, ...). Whisper frequently renders those English
terms phonetically in Cyrillic. This module applies a config-driven, per-language
find/replace over the transcript before summarization, normalizing known terms to
their canonical spelling, and exposes the canonical target list so the LLM summary
step can soft-normalize the remainder.

Stdlib-only by design: this module is imported by summarize.py and by the unit
tests, so it must NOT import requests, faster-whisper, or transcribe (which tries
to import faster-whisper). All the pure, testable logic lives here.

Glossary file format (plain text, UTF-8):
    # comments start with '#'; blank lines are ignored
    pattern => replacement
The left-hand side may list phonetic variants separated by '|', all mapping to the
single canonical right-hand side, e.g.:
    кубернетіс|кубернетес => Kubernetes
Matching is case-insensitive (Unicode/Cyrillic-aware) and whole-word-ish, so a
pattern is not replaced when it appears inside a longer word.

File layout in the glossary directory:
    glossary.txt          — shared, applied for every language
    glossary.<lang>.txt   — per language (glossary.uk.txt, glossary.ru.txt, ...)
For a resolved language L, the shared file plus glossary.L.txt are merged. When the
language is unknown (auto-detect with no recorded language), the shared file plus
every glossary.*.txt are merged as a union — safe because uk entries don't match ru
text and the English targets are identical.
"""

import json
import re
import sys
from pathlib import Path


def normalize_language(language):
    """Normalize a language code to a lowercase value or None (auto-detect).

    Mirrors transcribe._normalize_language (duplicated intentionally to keep this
    module free of the faster-whisper import): None, empty/whitespace-only, and
    'auto' (any case) all collapse to None; any other code is stripped/lowercased.
    """
    if language is None:
        return None
    language = language.strip()
    if not language:
        return None
    if language.lower() == "auto":
        return None
    return language.lower()


def parse_glossary(text):
    """Parse glossary text into a list of (alternatives, replacement) tuples.

    Skips blank lines and '#' comment lines. Each rule is `pattern => replacement`;
    the left-hand side is split on '|' into stripped, non-empty alternatives.
    Malformed lines (no '=>', or an empty side) are skipped rather than raising.
    """
    entries = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=>" not in line:
            continue
        lhs, _, rhs = line.partition("=>")
        replacement = rhs.strip()
        alternatives = [a.strip() for a in lhs.split("|") if a.strip()]
        if not alternatives or not replacement:
            continue
        entries.append((alternatives, replacement))
    return entries


def _compile_entry(alternatives):
    """Compile alternatives into a whole-word-ish, case-insensitive regex.

    Uses Unicode-aware lookarounds so a pattern inside a longer word is not
    clobbered (e.g. 'под' inside 'подключение'). Longer alternatives are tried
    first so multi-word phrases win over any shorter overlap.
    """
    ordered = sorted(alternatives, key=len, reverse=True)
    alternation = "|".join(re.escape(a) for a in ordered)
    return re.compile(r"(?<!\w)(?:" + alternation + r")(?!\w)", re.IGNORECASE)


def apply_glossary(text, entries):
    """Apply glossary entries to text, returning the normalized text.

    Case-insensitive, whole-word matching; each match is replaced by the literal
    canonical replacement. Empty entries return the text unchanged (identity).

    Entries are applied longest-pattern-first ACROSS all rules (not just within a
    single rule), so a multi-word phrase rule wins over a rule for one of its
    component words regardless of the order the rules appear in the file
    (e.g. `хелм чарт => helm chart` beats `хелм => Helm` even if listed after it).
    """
    if not entries:
        return text
    ordered = sorted(
        entries,
        key=lambda e: max((len(a) for a in e[0]), default=0),
        reverse=True,
    )
    result = text
    for alternatives, replacement in ordered:
        pattern = _compile_entry(alternatives)
        # Use a function replacement so backslashes / group refs in the canonical
        # term are treated literally (not as re.sub template escapes).
        result = pattern.sub(lambda _m, r=replacement: r, result)
    return result


def terms_for_prompt(entries):
    """Return the unique canonical replacements, preserving first-seen order."""
    seen = set()
    terms = []
    for _alternatives, replacement in entries:
        if replacement not in seen:
            seen.add(replacement)
            terms.append(replacement)
    return terms


def _read_glossary_file(path):
    """Parse a single glossary file, tolerating a missing/unreadable file."""
    try:
        return parse_glossary(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return []


def load_glossary(glossary_dir, language=None):
    """Load and merge glossary entries for the given language.

    Always includes the shared `glossary.txt`. For a known language L, adds
    `glossary.<L>.txt`. For an unknown language (None), adds every `glossary.*.txt`
    found (union fallback). A missing directory or absent files yield [] with no
    error, so summarization behaves exactly as before when no glossary is present.
    """
    if not glossary_dir:
        return []
    directory = Path(glossary_dir)
    if not directory.is_dir():
        return []

    entries = []
    shared = directory / "glossary.txt"
    if shared.is_file():
        entries.extend(_read_glossary_file(shared))

    language = normalize_language(language)
    if language:
        lang_file = directory / f"glossary.{language}.txt"
        if lang_file.is_file():
            entries.extend(_read_glossary_file(lang_file))
    else:
        # Union fallback: every per-language file. `glossary.*.txt` does not match
        # the shared `glossary.txt` (needs a segment between the dots) nor the
        # `.txt.example` templates (they don't end in `.txt`).
        for lang_file in sorted(directory.glob("glossary.*.txt")):
            entries.extend(_read_glossary_file(lang_file))
    return entries


def resolve_language(explicit, transcription_file):
    """Resolve the glossary language: explicit > detected-from-JSON > None.

    1. If an explicit language is set (normalized), use it.
    2. Otherwise look for a sibling transcription JSON next to the transcript and
       read its recorded "language" field, checking, in order, the dual/diarized
       labeled output, the raw transcription JSON, then the dual voice track.
    3. Otherwise return None (caller applies the union fallback).

    Never raises: a missing or malformed JSON is ignored.
    """
    explicit = normalize_language(explicit)
    if explicit:
        return explicit

    if not transcription_file:
        return None

    base = Path(transcription_file).with_suffix("")
    candidates = [
        f"{base}_speakers_labeled.json",
        f"{base}.json",
        f"{base}.voice.json",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if isinstance(data, dict):
            detected = normalize_language(data.get("language"))
            if detected:
                return detected
    return None


def main():
    """Preview glossary substitution on a text file (debugging helper)."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Preview per-language glossary substitution on a text file"
    )
    parser.add_argument("text_file", help="Path to a transcript .txt/.json file")
    parser.add_argument("--glossary-dir", default=str(Path(__file__).resolve().parent),
                        help="Directory holding glossary.*.txt files (default: this script's dir)")
    parser.add_argument("-l", "--language", default=None,
                        help="Language code (default: explicit > detected-from-JSON > union)")
    args = parser.parse_args()

    language = resolve_language(args.language, args.text_file)
    entries = load_glossary(args.glossary_dir, language)
    print(f"Language: {language or '(auto/union)'}; glossary entries: {len(entries)}",
          file=sys.stderr)
    text = Path(args.text_file).read_text(encoding="utf-8")
    sys.stdout.write(apply_glossary(text, entries))


if __name__ == "__main__":
    main()
