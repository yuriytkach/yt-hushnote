#!/usr/bin/env python3

"""
Meeting participant roster for ShepitNote (issue: roster + guardrails).

The summarizer LLM infers participant names and roles purely from what people
say in the transcript. On multi-party calls that misfires: a person mentioned
but absent gets listed as a participant, one speaker is split across two names,
and roles are invented wholesale. This module supplies a config-driven roster of
*known* people (canonical name, role, and name aliases) that summarize.py folds
into the prompt as ground truth, alongside guardrails that keep the Participants
section to people who actually spoke.

Stdlib-only by design (same contract as glossary.py): imported by summarize.py
and by the unit tests, so it must NOT import requests / faster-whisper. All the
pure, testable logic lives here.

Roster file format (plain text, UTF-8), one person per line:
    Name | role | alias1, alias2, ...
The role and aliases columns are optional:
    Roman | scrum master
    Alik
A leading '*' marks the local recorder (the microphone / "You" track):
    * Yuriy | CTO / dev lead | Юрий
Lines starting with '#' and blank lines are ignored. Malformed lines (no name)
are skipped rather than raising.

File layout in the roster directory (the same config directory used for
glossaries):
    roster.txt          — the default roster, used when no roster is selected
    roster.<name>.txt   — a named roster (roster.sigma.txt, roster.acme.txt, ...)
Select a named roster per meeting with `--roster <name>` / MEETING_ROSTER, or
point at any file with `--roster-file <path>`. This lets recurring groups (your
own devs, the whole team, a different company) each have their own file; pick the
matching one for the call, or omit it entirely when an outside guest attends.
Names are cross-language, so there is no per-language variant — script/spelling
differences are handled by the aliases column.
"""

import sys
from collections import namedtuple
from pathlib import Path


# A roster entry. aliases is a list of alternative spellings/diminutives; is_self
# flags the local recorder whose speech is captured on the microphone track.
Person = namedtuple("Person", ["name", "role", "aliases", "is_self"])


def parse_roster(text):
    """Parse roster text into a list of Person entries.

    Skips blank lines and '#' comments. Each entry is `Name | role | aliases`
    where role and aliases are optional; aliases are comma-separated. A leading
    '*' on the line marks the local recorder (is_self=True). Lines with an empty
    name after stripping the marker are skipped.
    """
    people = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        is_self = False
        if line.startswith("*"):
            is_self = True
            line = line[1:].strip()

        parts = [p.strip() for p in line.split("|")]
        name = parts[0] if parts else ""
        if not name:
            continue
        role = parts[1] if len(parts) > 1 and parts[1] else None
        aliases = []
        if len(parts) > 2 and parts[2]:
            aliases = [a.strip() for a in parts[2].split(",") if a.strip()]

        people.append(Person(name=name, role=role, aliases=aliases, is_self=is_self))
    return people


def load_roster_file(path):
    """Parse a single roster file, tolerating a missing/unreadable file ([])."""
    if not path:
        return []
    path = Path(path)
    if not path.is_file():
        return []
    try:
        return parse_roster(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return []


def load_roster(roster_dir, name=None):
    """Load roster entries from roster_dir.

    With `name`, reads `roster.<name>.txt` (a named roster for a recurring group);
    otherwise the default `roster.txt`. A missing directory or absent/unreadable
    file yields [] with no error, so summarization behaves exactly as before when
    no roster is configured.
    """
    if not roster_dir:
        return []
    directory = Path(roster_dir)
    if not directory.is_dir():
        return []
    filename = f"roster.{name}.txt" if name and name.strip() else "roster.txt"
    return load_roster_file(directory / filename)


def resolve_self(people, self_name=None, self_role=None):
    """Resolve the local recorder's (name, role).

    Precedence: an explicit self_name (with optional self_role) wins; otherwise
    the roster entry flagged with '*'. Returns (None, None) when neither is set.
    A blank/whitespace self_name is treated as unset.
    """
    if self_name and self_name.strip():
        role = self_role.strip() if self_role and self_role.strip() else None
        return self_name.strip(), role

    for person in people:
        if person.is_self:
            return person.name, person.role
    return None, None


def roster_prompt_block(people, self_name=None, self_role=None):
    """Build the roster ground-truth block for the summary prompt.

    Returns "" when there is nothing to add (no people and no resolvable self),
    so the prompt is byte-for-byte unchanged from the no-roster case. Otherwise
    returns a leading-newline block listing each known person as
    `- Name — role (aka alias1, alias2)`, with the local recorder annotated.
    """
    resolved_name, resolved_role = resolve_self(people, self_name, self_role)

    if not people and not resolved_name:
        return ""

    lines = [
        "",
        "Known people who may attend this meeting. Treat this as the COMPLETE set "
        "of possible attendees: every speaker is one of the people below, and you "
        "must NOT list any participant who is not in this list (a person named "
        "here may be absent — only list those who actually spoke; someone named "
        "only in the discussion or action items but not in this list is a "
        "non-attendee, not a participant). Use these exact names and roles; do "
        "not invent names or roles that are not listed here. A speaker may be "
        "referred to by any of the aliases in parentheses:",
    ]

    listed = set()
    for person in people:
        detail = person.name
        if person.role:
            detail += f" — {person.role}"
        if person.aliases:
            detail += f" (aka {', '.join(person.aliases)})"
        if person.is_self:
            detail += ' [the local speaker, labelled "You" in the transcript]'
        lines.append(f"- {detail}")
        listed.add(person.name)

    # If self came from explicit name/role (not a roster line), state it too.
    if resolved_name and resolved_name not in listed:
        detail = resolved_name
        if resolved_role:
            detail += f" — {resolved_role}"
        detail += ' [the local speaker, labelled "You" in the transcript]'
        lines.append(f"- {detail}")
    elif resolved_name in listed:
        # Self is already listed with its own role; add the "You" note only if the
        # matching roster line was not itself flagged self (explicit override case).
        if not any(p.is_self and p.name == resolved_name for p in people):
            lines.append(
                f'(The local speaker, labelled "You" in the transcript, is {resolved_name}.)'
            )

    return "\n".join(lines) + "\n"


def main():
    """Preview the roster prompt block (debugging helper)."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Preview the roster prompt block built from roster.txt"
    )
    parser.add_argument(
        "--roster-dir",
        default=str(Path(__file__).resolve().parent),
        help="Directory holding roster.txt (default: this script's dir)",
    )
    parser.add_argument("--self-name", default=None, help="Local recorder name override")
    parser.add_argument("--self-role", default=None, help="Local recorder role override")
    args = parser.parse_args()

    people = load_roster(args.roster_dir)
    print(f"Roster entries: {len(people)}", file=sys.stderr)
    sys.stdout.write(roster_prompt_block(people, args.self_name, args.self_role))


if __name__ == "__main__":
    main()
