#!/usr/bin/env python3

"""
Cloud transcription via any OpenAI-compatible /audio/transcriptions endpoint.

Default preset is Groq (Whisper large-v3) — the same model the local path uses,
just run on the provider's hardware. Because every serious host (Groq, Fireworks,
Together, OpenAI, ...) implements the OpenAI audio-transcription shape, switching
providers is only three settings, no code change:

    CLOUD_TRANSCRIBE_BASE_URL   e.g. https://api.groq.com/openai/v1
    CLOUD_TRANSCRIBE_API_KEY    the provider API key (GROQ_API_KEY is accepted too)
    CLOUD_TRANSCRIBE_MODEL      e.g. whisper-large-v3 / whisper-large-v3-turbo

`transcribe_via_api` returns the SAME result dict shape as
`transcribe.transcribe_audio`:

    {"language": str, "segments": [{"start", "end", "text"}], "text": str}

so the rest of the pipeline (merge_tracks, diarization merge, summarize) is
unchanged.

Audio is transcoded to 16 kHz mono before upload. Whisper resamples to 16 kHz
mono internally, so there is no accuracy loss, and it keeps the upload small and
under provider file-size caps (Groq's free tier caps uploads at 25 MB).
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover - mirrors summarize.py's guard
    print("Error: requests library not installed", file=sys.stderr)
    print("Install with: pip install requests", file=sys.stderr)
    sys.exit(1)


DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "whisper-large-v3"


def _prepare_upload(audio_file):
    """Transcode to a small 16 kHz mono file for upload.

    Returns (path, is_temp). Prefers Opus/OGG (tiny for speech), falls back to
    FLAC (lossless, universally decodable), and finally to the original file if
    ffmpeg is unavailable or both encodes fail — so a missing codec degrades to a
    larger upload rather than a hard failure.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return audio_file, False

    for suffix, codec_args in (
        (".ogg", ["-c:a", "libopus", "-b:a", "24k"]),
        (".flac", ["-c:a", "flac"]),
    ):
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        cmd = [ffmpeg, "-y", "-i", str(audio_file),
               "-ac", "1", "-ar", "16000", *codec_args, tmp_path]
        try:
            subprocess.run(cmd, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.getsize(tmp_path) > 0:
                return tmp_path, True
        except (subprocess.CalledProcessError, OSError):
            pass
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return audio_file, False


def _filter_hallucination_loops(segments, min_repeat=3):
    """Drop runs of `min_repeat`+ consecutive segments with identical text.

    faster-whisper's local path (transcribe.py) sets condition_on_previous_text
    =False specifically to stop Whisper from looping the same boilerplate
    phrase over near-silent audio; Groq's OpenAI-compatible API exposes no such
    knob, so a quiet track can come back as the same short phrase repeated once
    per ~30s chunk for the whole file (e.g. a YouTube-outro hallucination like
    "thanks for watching!"). That exact-repeat-per-chunk shape is not something
    real speech produces, so treat it as the hallucination signature and drop
    the whole run rather than trust any segment in it.
    """
    if not segments:
        return segments
    filtered = []
    i, n = 0, len(segments)
    while i < n:
        key = segments[i]["text"].strip().lower()
        j = i + 1
        while j < n and segments[j]["text"].strip().lower() == key:
            j += 1
        if not key or (j - i) < min_repeat:
            filtered.extend(segments[i:j])
        i = j
    return filtered


def _map_response(payload, fallback_language=None):
    """Map an OpenAI-compatible transcription JSON payload to our result dict.

    Pure (no I/O) so it can be unit-tested. Handles the common shapes:
    - verbose_json with a `segments` list (start/end/text per segment);
    - a plain `{"text": ...}` with no segments (wrapped as one 0-0 segment);
    - segments but no top-level text (joined from the segments).
    Missing timestamps default to 0.0 and missing text to "".
    """
    segments = []
    for seg in payload.get("segments") or []:
        segments.append({
            "start": float(seg.get("start") or 0.0),
            "end": float(seg.get("end") or 0.0),
            "text": (seg.get("text") or "").strip(),
        })

    original_count = len(segments)
    segments = _filter_hallucination_loops(segments)
    if len(segments) != original_count:
        print(
            f"Dropped {original_count - len(segments)} segment(s) that looked like a "
            "Whisper hallucination loop (repeated boilerplate text on near-silent audio).",
            file=sys.stderr,
        )

    text = (payload.get("text") or "").strip()
    if not segments and text:
        segments = [{"start": 0.0, "end": 0.0, "text": text}]
    if (not text and segments) or original_count != len(segments):
        text = " ".join(s["text"] for s in segments).strip()

    language = payload.get("language") or fallback_language or ""
    return {"language": language, "segments": segments, "text": text}


def transcribe_via_api(
    audio_file,
    language=None,
    base_url=DEFAULT_BASE_URL,
    api_key=None,
    model=DEFAULT_MODEL,
    prompt=None,
    timeout=300,
):
    """Transcribe an audio file through a cloud OpenAI-compatible endpoint.

    Raises on any failure (missing key, network error, non-2xx response) so the
    caller can decide whether to fall back to local Whisper. Returns the same
    dict shape as transcribe.transcribe_audio.
    """
    if not api_key or not str(api_key).strip():
        raise RuntimeError("no API key provided for cloud transcription")

    url = base_url.rstrip("/") + "/audio/transcriptions"
    upload_path, is_temp = _prepare_upload(audio_file)

    data = {"model": model, "response_format": "verbose_json"}
    lang = (language or "").strip()
    if lang and lang.lower() != "auto":
        data["language"] = lang
    if prompt and prompt.strip():
        # OpenAI-style transcription `prompt` biases decoding, like Whisper's
        # initial_prompt — reuse the pipeline's hotwords/initial-prompt here.
        data["prompt"] = prompt.strip()

    print(f"Uploading {Path(audio_file).name} to {url} (model: {model})...",
          file=sys.stderr)
    try:
        with open(upload_path, "rb") as fh:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (Path(upload_path).name, fh)},
                data=data,
                timeout=timeout,
            )
    finally:
        if is_temp:
            try:
                os.unlink(upload_path)
            except OSError:
                pass

    if resp.status_code >= 400:
        # Surface the provider's error body (trimmed) — it usually says exactly
        # what is wrong (bad key = 401, file too large = 413, rate limit = 429).
        raise RuntimeError(f"HTTP {resp.status_code} from {url}: {resp.text[:300]}")

    result = _map_response(resp.json(), fallback_language=lang or None)
    print(f"Detected language: {result['language']}", file=sys.stderr)
    return result
