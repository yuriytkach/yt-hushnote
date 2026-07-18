# Setup Complete! ✓

Your meeting transcription system is ready to use.

## What's Been Set Up

✓ **System Dependencies**: ffmpeg, pactl (PipeWire), Python 3.13
✓ **Python Environment**: Virtual environment created at `./venv/`
✓ **Python Packages**: faster-whisper, requests (installed in venv)
✓ **Ollama**: Running with 7 models available
✓ **Scripts**: All executable and configured
✓ **Recordings Directory**: `./recordings/` created

## Available Ollama Models

Your system has these models ready for summarization:
- `llama3.2:1b` - Fastest (1.2B parameters)
- `mistral:7b` - Good balance (7.2B)
- `qwen2.5-coder:7b` - Code-focused (7.6B)
- `gemma2:9b` - Google model (9.2B)
- `qwen2.5-coder:14b` - Better quality (14.8B, **recommended**)
- `llava:13b` - Multimodal (13B)
- `mixtral:8x7b` - Best quality (46.7B, slower)

**Note**: The scripts default to `llama3.1:8b`, but you don't have that model. Use `-o` to specify one of the above models.

## Quick Start

### Test with a 10-second recording:
```bash
# Record 10 seconds, transcribe, and summarize
./meeting-notes.sh full -d 10 -m tiny -o qwen2.5-coder:14b
```

### For real meetings:
```bash
# Start recording (press Ctrl+C to stop)
./meeting-notes.sh full -o qwen2.5-coder:14b
```

### Available audio sources:
You have several microphones detected:
- **HD Pro Webcam C920** (ID: 98) - Webcam mic
- **USB Audio Mic1** (ID: 64) - USB microphone
- **USB Audio Line1** (ID: 65) - Line input

The script will use your default source. To change:
```bash
pactl set-default-source 98  # Use webcam mic
# or
pactl set-default-source 64  # Use USB mic
```

### Dual-track capture (You/Remote)

To capture your voice and the remote side as two separate, synchronized tracks
(so the transcript is labeled by origin without diarization), set
`AUDIO_SOURCE_TYPE=dual`. The two tracks map like this:

- **You** ← the default *source* (your microphone): `pactl get-default-source`
- **Remote** ← the monitor of the default *sink* (what plays through your
  speakers/headset): `pactl get-default-sink` (its `.monitor` is captured)

So point your default source at the mic you speak into and your default sink at
the device the call audio plays out of, then run:

```bash
AUDIO_SOURCE_TYPE=dual ./hushnote full -d 10 -m tiny -o mistral:7b
```

For Bluetooth headsets in HSP/HFP mode, ffmpeg's PulseAudio capture can be
silent; use the PipeWire backend instead:

```bash
AUDIO_SOURCE_TYPE=dual RECORD_BACKEND=pw-record ./hushnote full
```

## Recommended Settings

For best results:
```bash
# Good balance (fast, decent quality)
./meeting-notes.sh full -m base -o mistral:7b

# Better quality (slower)
./meeting-notes.sh full -m small -o qwen2.5-coder:14b

# Best quality (much slower)
./meeting-notes.sh full -m medium -o mixtral:8x7b
```

## Language & accuracy (uk/ru/en)

`large-v3` is now the default Whisper model — best multilingual accuracy, but
slower on CPU. For known-language meetings, set the language explicitly instead
of relying on auto-detect (which samples only the first ~30s and often mislabels
Ukrainian as Russian):

```bash
./hushnote full -l uk     # or -l ru / -l en; -l auto to auto-detect
```

Set a permanent default with `WHISPER_LANGUAGE=uk` in `.hushnoterc`. See the
[Language selection](README.md#language-selection-ukrainian--russian--english)
section in the README for the full guidance — including a user verification step
for measuring accuracy on your own recordings, which needs your own audio and
can't be done for you.

### English tech terms (Kubernetes, deploy, ...)

For meetings that mix Slavic speech with English programming terms, two opt-in
layers improve accuracy (both empty by default — leaving them unset changes
nothing):

- **Hotwords / initial prompt** bias Whisper toward clean English spellings.
  Set `WHISPER_HOTWORDS="Kubernetes deploy Helm chart Jenkins GitHub"` (or the
  sentence-form `WHISPER_INITIAL_PROMPT`, which takes precedence) in
  `.hushnoterc`.
- **A per-language glossary** normalizes phonetic Cyrillic renderings before the
  summary. Copy a template to activate it, e.g.
  `cp glossary.uk.txt.example glossary.uk.txt`, then edit it for your stack
  (`GLOSSARY_DIR` points at where these files live; default is the hushnote
  directory). Real `glossary.*.txt` files are git-ignored.

Full format, language-resolution behavior, and a with/without verification
procedure are in the README
[English tech-term accuracy](README.md#english-tech-term-accuracy-hotwords--glossary)
section.

## Common Commands

```bash
# List recordings
./meeting-notes.sh list

# Record only (30 minutes)
./meeting-notes.sh record -d 1800

# Transcribe existing audio
./meeting-notes.sh transcribe path/to/audio.wav -m small

# Summarize existing transcription
./meeting-notes.sh summarize path/to/transcript.txt -o qwen2.5-coder:14b
```

## Troubleshooting

If you get "llama3.1:8b not found", either:
1. Use `-o` to specify a model you have (see list above)
2. Or download it: `ollama pull llama3.1:8b`

## Next Steps

Try a test recording to make sure everything works!

```bash
./meeting-notes.sh full -d 10 -m tiny -o mistral:7b
```

This will:
1. Record 10 seconds of audio
2. Transcribe it using the tiny Whisper model
3. Generate a summary using Mistral 7B

Check the `recordings/` directory for the output files.
