#!/usr/bin/env python3

"""
Meeting summarization script using Ollama
Takes transcription text and generates meeting notes, summaries, and action items
"""

import argparse
import json
import os
import sys
from pathlib import Path

import glossary
import roster as roster_mod

try:
    import requests
except ImportError:
    print("Error: requests library not installed", file=sys.stderr)
    print("Install with: pip install requests", file=sys.stderr)
    sys.exit(1)


DEFAULT_OLLAMA_URL = "http://localhost:11434"

SUMMARY_PROMPT = """You are an assistant that writes concise meeting notes from transcripts.

Produce the following sections using markdown headings:

## Summary
2-3 sentences covering what the meeting was about and what was concluded.

## Discussion
Bullet points of the main topics covered. Be specific, not generic.

## Decisions
Key decisions or conclusions reached. Omit this section if none were made.

## Action Items
A markdown checklist of concrete next steps that were explicitly agreed on, with owner and deadline if mentioned. Only include items that were clearly committed to — not vague intentions or possibilities. Omit this section entirely if there are no real action items.

## Participants
List ONLY the people who actually spoke in this meeting — those who appear as a [Speaker] label in the transcript. Rules:
- Each distinct speaker label is exactly one person; never list the same person twice under different names.
- Do NOT list anyone who is only mentioned or talked about by others but did not themselves speak.
- Do NOT invent a job title or role you cannot support from the transcript; if unsure of someone's role, give the name alone.
- Write each participant as their name and role only (e.g. "Viktor — frontend developer"); do NOT repeat any alias/nickname list.
{roster}{normalization}
Transcription:
{transcription}

Use markdown headings and bullet points. Do not wrap your response in a code block."""


TRANSLATE_PROMPT = """Translate the following meeting transcript into English.

Rules:
- Keep each line's leading [Speaker] label exactly as-is.
- Translate faithfully and completely; do NOT summarize, condense, or omit anything.
- Preserve technical and product names, and any English words already present.
- Output ONLY the translated transcript — no preamble, no notes.

Transcript:
{transcription}"""


def query_ollama(prompt: str, model: str = "llama3.1:8b", ollama_url: str = DEFAULT_OLLAMA_URL) -> str:
    """
    Query Ollama API for text generation

    Args:
        prompt: The prompt to send
        model: Model name to use
        ollama_url: Ollama API URL

    Returns:
        Generated text response
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False
    }
    # Cap the CPU threads Ollama uses for this generation so summarization leaves
    # cores free (set by shepitnote via CPU_THREADS). Ignored if unset/invalid.
    num_thread = os.getenv("OLLAMA_NUM_THREAD")
    if num_thread and num_thread.strip():
        try:
            payload["options"] = {"num_thread": int(num_thread)}
        except ValueError:
            pass

    try:
        response = requests.post(
            f"{ollama_url}/api/generate",
            json=payload,
            timeout=600  # 10 min: a translate pass is a longer generation than a summary
        )
        response.raise_for_status()
        return response.json()["response"]
    except requests.exceptions.RequestException as e:
        print(f"Error querying Ollama: {e}", file=sys.stderr)
        sys.exit(1)


def load_transcription(file_path: str) -> str:
    """Load transcription from file (supports .txt, .json)"""
    path = Path(file_path)

    if not path.exists():
        print(f"Error: Transcription file not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    if path.suffix == ".json":
        data = json.loads(path.read_text())
        return data.get("text", "")
    else:
        return path.read_text()


def _build_summary_prompt(transcription: str, known_terms=None, roster_block="") -> str:
    """Format SUMMARY_PROMPT, optionally folding in glossary terms (soft LLM
    normalization) and a roster of known participants. When known_terms is
    empty/None the {normalization} slot is empty and when roster_block is empty
    the {roster} slot is empty, reproducing the earlier prompt byte-for-byte."""
    if known_terms:
        normalization = (
            "The transcript may render some technical or product names "
            "phonetically or misspelled. When a word clearly refers to one of "
            "these known terms, normalize it to the canonical spelling: "
            + ", ".join(known_terms) + "."
        )
    else:
        normalization = ""
    return SUMMARY_PROMPT.format(
        transcription=transcription,
        normalization=normalization,
        roster=roster_block or "",
    )


def summarize_meeting(
    transcription: str,
    model: str,
    ollama_url: str,
    known_terms=None,
    roster_block="",
) -> dict:
    """Generate meeting notes from a transcription in a single Ollama call.

    known_terms: optional list of canonical glossary targets. When non-empty, an
    instruction to normalize phonetic renderings toward those terms is folded into
    the prompt.
    roster_block: optional pre-built roster ground-truth block (from roster.py).
    When both are empty/None, the prompt and behavior are unchanged from before.
    """
    print(f"Generating meeting summary using {model}...", file=sys.stderr)

    text = query_ollama(
        _build_summary_prompt(transcription, known_terms, roster_block),
        model=model,
        ollama_url=ollama_url,
    )

    return {"summary": _strip_code_fence(text)}


def translate_to_english(transcription: str, model: str, ollama_url: str) -> str:
    """Translate a transcript to English via Ollama, preserving [Speaker] labels.

    Used for the opt-in translate-first flow: for non-English meetings (e.g. ru/uk),
    translating before summarizing gives markedly better notes than asking one model
    to translate + summarize + structure in a single pass, because the summary model
    then works in the language it is strongest in. Returns the English transcript
    (code fences stripped); on any failure query_ollama exits, matching the rest of
    the pipeline's fail-fast behavior.
    """
    print(f"Translating transcript to English using {model}...", file=sys.stderr)
    text = query_ollama(
        TRANSLATE_PROMPT.format(transcription=transcription),
        model=model,
        ollama_url=ollama_url,
    )
    return _strip_code_fence(text)


def _strip_code_fence(text: str) -> str:
    """Strip wrapping code fences that models sometimes add around markdown output."""
    import re
    # Match optional language tag: ```markdown or ```md or just ```
    text = text.strip()
    text = re.sub(r"^```[a-z]*\n", "", text)
    text = re.sub(r"\n```$", "", text)
    return text.strip()


def save_summary(result: dict, output_file: str, format: str):
    """Save summary in specified format."""
    output_path = Path(output_file)

    if format in ("txt", "md"):
        output_path.write_text(result["summary"] + "\n")
    elif format == "json":
        output_path.write_text(json.dumps(result, indent=2))

    print(f"Summary saved to: {output_path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Summarize meeting transcription using Ollama")
    parser.add_argument("transcription_file", help="Path to transcription file (.txt or .json)")
    parser.add_argument("-m", "--model", default="llama3.1:8b",
                       help="Ollama model to use (default: llama3.1:8b)")
    parser.add_argument("-u", "--ollama-url", default=DEFAULT_OLLAMA_URL,
                       help=f"Ollama API URL (default: {DEFAULT_OLLAMA_URL})")
    parser.add_argument("-f", "--format", default="md",
                       choices=["txt", "md", "json"],
                       help="Output format (default: md)")
    parser.add_argument("-o", "--output",
                       help="Output file (default: transcription_file_summary.md)")
    parser.add_argument("-l", "--language", default=None,
                       help="Transcript language for glossary selection "
                            "(default: explicit > detected from sibling JSON > union)")
    parser.add_argument("--glossary-dir", default=str(Path(__file__).resolve().parent),
                       help="Directory of glossary.*.txt term files "
                            "(default: this script's directory)")
    parser.add_argument("--no-glossary", action="store_true",
                       help="Disable glossary term normalization entirely")
    parser.add_argument("--roster-dir", default=str(Path(__file__).resolve().parent),
                       help="Directory holding roster.txt (known participants + "
                            "roles) folded into the summary as ground truth "
                            "(default: this script's directory)")
    parser.add_argument("--roster", default=None,
                       help="Select a named roster file roster.<NAME>.txt in the "
                            "roster dir (default: roster.txt); e.g. --roster sigma. "
                            "Falls back to MEETING_ROSTER env")
    parser.add_argument("--roster-file", default=None,
                       help="Explicit path to a roster file (overrides --roster "
                            "and --roster-dir)")
    parser.add_argument("--no-roster", action="store_true",
                       help="Disable the participant roster entirely (use when an "
                            "outside guest not in any roster attends)")
    parser.add_argument("--self-name", default=None,
                       help="Name of the local recorder (the 'You'/mic track); "
                            "overrides a '*' line in roster.txt")
    parser.add_argument("--self-role", default=None,
                       help="Role of the local recorder (used with --self-name)")
    parser.add_argument("--translate", dest="translate",
                       action=argparse.BooleanOptionalAction, default=None,
                       help="Translate the transcript to English before "
                            "summarizing (better notes for non-English meetings). "
                            "Default: off / SUMMARY_TRANSLATE env")
    parser.add_argument("--translate-model", default=None,
                       help="Model for the translate step (default: same as -m, "
                            "or SUMMARY_TRANSLATE_MODEL env)")

    args = parser.parse_args()

    # Resolve the translate-first flow: CLI flag wins, else env, else off.
    def _env_bool(name, default=False):
        v = os.getenv(name)
        if v is None or not v.strip():
            return default
        return v.strip().lower() in ("1", "true", "yes", "on")

    translate = args.translate if args.translate is not None else _env_bool("SUMMARY_TRANSLATE")
    translate_model = args.translate_model or os.getenv("SUMMARY_TRANSLATE_MODEL") or args.model

    # Heads-up when a cloud model is in play: the transcript leaves the machine.
    # shepitnote prints a fuller cloud banner, but this covers direct calls too.
    if ":cloud" in (args.model or "").lower() or ":cloud" in (translate_model or "").lower():
        print(f"Note: '{args.model}' is a cloud model — the transcript is sent "
              "to Ollama Cloud for summarization.", file=sys.stderr)

    # Load transcription
    transcription = load_transcription(args.transcription_file)

    if not transcription.strip():
        print("Error: Transcription is empty", file=sys.stderr)
        sys.exit(1)

    # Apply the per-language term glossary (issue #8) before summarizing. This is
    # opt-in: with no glossary files present, entries is empty, the transcript is
    # untouched, and no known-terms instruction is added — identical to before.
    known_terms = []
    if not args.no_glossary:
        language = glossary.resolve_language(args.language, args.transcription_file)
        entries = glossary.load_glossary(args.glossary_dir, language)
        if entries:
            transcription = glossary.apply_glossary(transcription, entries)
            known_terms = glossary.terms_for_prompt(entries)
            print(f"Glossary: {len(entries)} rule(s) applied "
                  f"(language: {language or 'union'})", file=sys.stderr)

    # Build the participant roster block (known names + roles as ground truth,
    # plus the local-speaker identity). Opt-in: with no roster.txt and no
    # --self-name, roster_block is "" and the prompt is unchanged. self-name/role
    # fall back to env so shepitnote can forward MEETING_SELF_NAME/ROLE.
    roster_block = ""
    if not args.no_roster:
        # Precedence: explicit --roster-file > named --roster/MEETING_ROSTER
        # (roster.<name>.txt) > default roster.txt in --roster-dir.
        if args.roster_file:
            people = roster_mod.load_roster_file(args.roster_file)
        else:
            roster_name = args.roster or os.getenv("MEETING_ROSTER")
            people = roster_mod.load_roster(args.roster_dir, roster_name)
        self_name = args.self_name or os.getenv("MEETING_SELF_NAME")
        self_role = args.self_role or os.getenv("MEETING_SELF_ROLE")
        roster_block = roster_mod.roster_prompt_block(people, self_name, self_role)
        if roster_block:
            print(f"Roster: {len(people)} known participant(s) provided "
                  "as ground truth", file=sys.stderr)

    # Opt-in translate-first: convert the (glossary-normalized) transcript to
    # English before summarizing. Done after the glossary pass so canonical term
    # spellings carry into the translation.
    if translate:
        transcription = translate_to_english(
            transcription, model=translate_model, ollama_url=args.ollama_url
        )

    # Determine output file
    if args.output:
        output_file = args.output
    else:
        trans_path = Path(args.transcription_file)
        suffix = ".md" if args.format == "md" else f".{args.format}"
        output_file = trans_path.with_name(f"{trans_path.stem}_summary{suffix}")

    # Generate summary
    try:
        result = summarize_meeting(
            transcription,
            model=args.model,
            ollama_url=args.ollama_url,
            known_terms=known_terms,
            roster_block=roster_block,
        )

        # Save results
        save_summary(result, output_file, args.format)

        print("\nSummarization complete!", file=sys.stderr)

    except Exception as e:
        print(f"Error during summarization: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
