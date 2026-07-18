#!/usr/bin/env python3

"""
Meeting summarization script using Ollama
Takes transcription text and generates meeting notes, summaries, and action items
"""

import argparse
import json
import sys
from pathlib import Path

import glossary

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
Names or roles of identifiable speakers, if mentioned.
{normalization}
Transcription:
{transcription}

Use markdown headings and bullet points. Do not wrap your response in a code block."""


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
    try:
        response = requests.post(
            f"{ollama_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False
            },
            timeout=300  # 5 minute timeout
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


def _build_summary_prompt(transcription: str, known_terms=None) -> str:
    """Format SUMMARY_PROMPT, optionally folding known terms in for soft LLM
    normalization. When known_terms is empty/None the {normalization} slot is
    empty, reproducing the pre-#8 prompt byte-for-byte."""
    if known_terms:
        normalization = (
            "The transcript may render some technical or product names "
            "phonetically or misspelled. When a word clearly refers to one of "
            "these known terms, normalize it to the canonical spelling: "
            + ", ".join(known_terms) + "."
        )
    else:
        normalization = ""
    return SUMMARY_PROMPT.format(transcription=transcription, normalization=normalization)


def summarize_meeting(
    transcription: str,
    model: str,
    ollama_url: str,
    known_terms=None,
) -> dict:
    """Generate meeting notes from a transcription in a single Ollama call.

    known_terms: optional list of canonical glossary targets. When non-empty, an
    instruction to normalize phonetic renderings toward those terms is folded into
    the prompt. When empty/None, the prompt and behavior are unchanged from before.
    """
    print(f"Generating meeting summary using {model}...", file=sys.stderr)

    text = query_ollama(
        _build_summary_prompt(transcription, known_terms),
        model=model,
        ollama_url=ollama_url,
    )

    return {"summary": _strip_code_fence(text)}


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

    args = parser.parse_args()

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
        )

        # Save results
        save_summary(result, output_file, args.format)

        print("\nSummarization complete!", file=sys.stderr)

    except Exception as e:
        print(f"Error during summarization: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
