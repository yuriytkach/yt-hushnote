# CLAUDE.md — ShepitNote

Private, local, multilingual (uk/ru/en) meeting notes for Linux: **record → transcribe
(faster-whisper) → label who said what → summarize (Ollama) → optionally publish
(Confluence + Slack)**. A fork of [peteonrails/hushnote](https://github.com/peteonrails/hushnote).
User-facing overview lives in `README.md`; this file is the map for working *on* the code.

## Architecture — the one mental model to hold

`shepitnote` is a **bash orchestrator** (~3100 lines) that shells out to small,
single-purpose **Python workers** running in `./venv`. Contract for every worker:
**data → stdout, logs/errors → stderr**, so bash captures a result with `$(...)` while the
user still sees progress. Nothing else talks to the network or the mic — the workers do.
`setup.sh` builds `venv/` (deps declared in `pyproject.toml`, extras `diarize`/`gpu`; there is no
`requirements.txt`); workers are invoked as `"$PYTHON" worker.py …` where `PYTHON=venv/bin/python3`.

## File map

**Orchestration / shell**
- `shepitnote` — the CLI. All commands, config load + resolution, per-command flag parsing,
  CPU/nice caps, the guided `meeting` flow, the process watchdog. Start here for almost anything.
- `record_audio.sh` — capture (backends `ffmpeg`/`pw-record`; modes `microphone`/`monitor`/`both`/`dual`).
- `compress.sh` — WAV → MP3. `setup.sh` — create venv + deps (`--model` prepull, `--diarize` CPU pyannote).
- `migrate_recordings.sh` — one-off recordings-layout migration.

**Python workers** (venv; data→stdout, logs→stderr)
- `transcribe.py` — faster-whisper; VAD + anti-hallucination, hotwords/initial-prompt, translate-first.
- `cloud_transcribe.py` — OpenAI-compatible `/audio/transcriptions` (Groq preset); **same result dict shape** as `transcribe.py`.
- `summarize.py` — Ollama structured summary; imports `glossary`; forwards `OLLAMA_NUM_THREAD`.
- `glossary.py` — **pure**, stdlib-only per-language Cyrillic→Latin term normalization (imported by `summarize.py` + tests).
- `roster.py` — **pure**, stdlib-only known-participant roster (name/role/aliases, `*`=self, closed-set); builds the summary-prompt ground-truth block. Named files `roster.<name>.txt`. Imported by `summarize.py`/`label.py` + tests.
- `speaker_guess.py` — **pure**, stdlib-only: LLM speaker-name guess prompt + tolerant JSON parse + segment-level speaker merge/name-apply. Imported by `label.py` + tests.
- `diarize.py` — pyannote.audio **4.x**, `speaker-diarization-community-1`.
- `merge_tracks.py` — interleave voice(You)/system(Remote) transcription JSON → `_speakers_labeled.json`; `--system-diarization` splits `Remote N`.
- `merge_diarization.py` — merge single-track diarization + transcription by timestamp.
- `label.py` / `apply_labels.py` — interactive speaker labeling → final `.txt`. `label.py` is roster-aware: pre-fills an LLM name guess per speaker (best-effort Ollama; graceful fallback), accept/correct/`merge <id|name>`/drop, `--auto-guess`/`--no-guess`.
- `meeting_ui.py` — **pure** helpers for the guided flow (`configured_targets`, `parse_yes_no`, metadata title, `detect_language`). The interactive loop itself is bash `meeting_ui()` in `shepitnote`.

**Publishing** (`hooks/`, invoked as `POST_SUMMARY_HOOK` with `$1 = <base>_summary.md`)
- `publish.py` — dispatcher; runs each configured publisher (Confluence first, so Slack can link the page).
- `confluence_publish.py` — idempotent create/update page; writes `<base>.confluence_page_id`.
- `slack_publish.py` — runs a *second, terser* Ollama TL;DR pass → Slack; writes `<base>.slack_done` (posts are non-idempotent, marker prevents re-posts).

**Config / templates / tests / docs**
- `.shepitnoterc.example` — annotated template documenting **every** option; **this is the config reference**. Copy → `.shepitnoterc` (git-ignored, sourced at startup).
- `glossary*.txt.example` — glossary templates. `roster.txt.example` — participant-roster template (copy → `roster.txt`, git-ignored). `tests/` — unittest. `docs/` — topic guides (see bottom).

## Pipeline & per-meeting file layout

`recordings/<YYYYMMDD>/meeting_<YYYYMMDD>_<HHMMSS>/`, all sharing base `meeting_<ts>`:

| suffix | what |
|---|---|
| `.wav` / `.voice.wav`+`.system.wav` | raw capture (single / dual) → compressed to matching `.mp3` |
| `.json` / `.voice.json`+`.system.json` | per-track transcription (start/end/text + language) |
| `.system_speakers.json` | remote-track diarization (dual + `DUAL_REMOTE_DIARIZATION`) |
| `_speakers_labeled.json` | combined, speaker-labeled segments → fed to `apply_labels.py` |
| `.txt` | **final transcript** · `_summary.md` — **final notes** |
| `_metadata.json` | human title, date, language (edited by the guided flow) |
| `.hook_done` / `.slack_done` / `.confluence_page_id` | idempotency markers |

Flow: `record → compress → trim silent tail → transcribe → summarize → POST_SUMMARY_HOOK`.
In `dual` mode trimming is skipped; the two tracks are transcribed then interleaved by timestamp.
`status`/`catchup` use the markers above to find pending/partial meetings.

## Config resolution & where to change things

In `shepitnote`, in order: (1) `.shepitnoterc` sourced at top (`set -a`); (2) defaults block
`VAR="${VAR:-default}"` (~L28–120); (3) `main()` (~L2489) **strips global flags** before dispatch —
`--cloud`/`--no-cloud` set `CLOUD` then call `cloud_resolve()`; `--no-diarize` sets
`DUAL_REMOTE_DIARIZATION=false` and exports `SHEPITNOTE_DIARIZE_OVERRIDE` so `process-last`'s
re-invoked child (which re-sources the rc) still honors it; (4) `cloud_resolve()` maps `CLOUD` →
`OLLAMA_MODEL`/`CLOUD_TRANSCRIBE*` and **exports** them for children + workers; (5) each command
function parses its own flags in a local `case` loop.

- **Add a config option:** default in the top block → document in `.shepitnoterc.example` → `export` it if a worker/child needs it.
- **Add a CLI flag:** the relevant command function's `case` parser **and** `print_usage()`; thread it into that command's worker-args array.
- **Add a worker:** Python at repo root, run via `"$PYTHON"`, data→stdout/logs→stderr; keep pure logic in an importable module with a unittest.

## Tests

`venv/bin/python -m unittest discover -s tests` (unittest, **no pytest in venv**; 320 tests).
Tests import modules directly (`sys.path` → repo root) and cover **pure logic only** — no mic,
Ollama, or network. `shepitnote` runs `main` only when executed, not sourced, so bash helpers
are unit-testable too. Add tests for new pure logic; keep side-effecting code thin.

## Runtime environment (this machine)

No usable discrete GPU → **Whisper runs on CPU** (`large-v3` default, ~real-time). **Ollama runs
on the AMD iGPU** (unified ~61 GB RAM) — don't run heavy Whisper + Ollama at once. `CPU_THREADS`
(default: half the cores) + `PROCESSING_NICE` (default 10) keep the desktop responsive. Diarization
is CPU pyannote 4.x — install with `./setup.sh --diarize` (CPU torch wheels **on purpose**; the CUDA
`torchcodec` build breaks it). Optional cloud mode (`--cloud`): Ollama Cloud summaries
(`gpt-oss:120b-cloud`, free tier) + Groq Whisper — sends data off-machine (see `docs/CLOUD.md`).

## Docs index (deep dives)

- `docs/SETUP.md` — install, first run, CPU limits · `docs/AUDIO.md` — capture modes, dual-track, echo cancellation (`aec`), call routing, output files
- `docs/LANGUAGE.md` — Whisper models, uk/ru/en selection, hallucination control, hotwords/glossary, translate-first
- `docs/DIARIZATION.md` — speaker diarization · `docs/PUBLISHING.md` — hook, Confluence, Slack, guided flow · `docs/CLOUD.md` — cloud mode & privacy
