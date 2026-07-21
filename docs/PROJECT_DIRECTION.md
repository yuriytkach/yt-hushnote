# Project direction

This document explains what ShepitNote is trying to become and, equally importantly, what it is not trying to become.

It describes direction rather than a release promise. Current behavior is documented in the README and topic guides; planned work remains tracked in GitHub issues.

## Product boundary

ShepitNote is a **local-first meeting-notes application for Linux**.

Its responsibility begins before transcription and continues after summarization:

1. capture reliable, recoverable meeting audio;
2. preserve source and timing information;
3. transcribe one or more tracks;
4. attribute speech and allow human correction;
5. normalize multilingual engineering terminology;
6. generate structured notes, decisions, and action items;
7. let the user review and control publishing;
8. retain enough artifacts to reprocess a meeting later.

This application-level workflow is the core of the project.

## What ShepitNote is not

ShepitNote is not intended to become:

- a general-purpose desktop dictation application;
- a replacement for every speech engine;
- a hosted meeting bot that silently joins calls;
- a cloud-first SaaS product;
- an autonomous publisher that removes human review;
- a collection of unrelated speech experiments.

Projects such as [Voxtype](https://github.com/peteonrails/voxtype) are better positioned to offer broad Linux voice-to-text and push-to-talk capabilities. ShepitNote may integrate with such tools or engines where useful, but should retain its meeting-specific workflow and recovery model.

## Design principles

### Audio is the source of truth

Transcripts, speaker labels, and summaries can be regenerated. The original meeting cannot. Capture and storage changes must preserve recoverability even when processing fails or is interrupted.

### Local by default

The normal path should work without sending meeting content to third parties. Cloud processing is an explicit per-run choice, with clear disclosure of what will be uploaded.

### Prefer reliable signals over inference

When the operating system can provide separate microphone and call tracks, use those tracks to identify `You` and `Remote` rather than asking a diarization model to guess.

Machine inference remains useful for subdividing the remote side, suggesting participant names, and improving review—but its result should be inspectable and correctable.

### Human review is part of correctness

Speaker names, decisions, action items, and published notes affect other people. The workflow should make review fast rather than pretending it is unnecessary.

### Engines should be replaceable

Transcription and diarization evolve quickly. ShepitNote should define stable application-level data structures and allow engines to be evaluated or replaced without rewriting capture, recovery, review, summaries, and publishing.

### Improve incrementally

The current Bash/Python implementation delivers a working workflow. Architectural improvements should be made through characterization tests and small extractions, not a big-bang rewrite.

## Architecture direction

The desired long-term boundary is:

```text
Linux audio capture and retained recordings
                    │
                    ▼
       transcription backend interface
       ├─ faster-whisper
       ├─ cloud Whisper API
       ├─ whisper.cpp / Vulkan (possible)
       └─ Voxtype adapter (experiment)
                    │
                    ▼
         canonical transcript model
     timestamps · source · language · metadata
                    │
                    ▼
       attribution and diarization layer
                    │
                    ▼
         ShepitNote application workflow
 glossary · roster · relabel · summarize · review
              Confluence · Slack
```

The canonical transcript should eventually preserve enough metadata to compare engines and re-run downstream steps without coupling them to one transcription implementation.

## Current strategic priorities

### 1. Build a repeatable evaluation harness

Before changing engines, chunk sizes, language strategy, or hardware acceleration, compare them on the same representative recordings.

Tracked in [#16](https://github.com/yuriytkach/shepitnote/issues/16).

### 2. Introduce a pluggable transcription interface

Normalize local and cloud transcription behind one contract so new engines do not create branches throughout the orchestrator.

Tracked in [#13](https://github.com/yuriytkach/shepitnote/issues/13).

### 3. Improve mixed-language meetings

The present Whisper path chooses one language per complete file. The target is constrained selection between `uk`, `ru`, and `en` at chunk or speech-segment level while preserving timestamps and avoiding duplicated boundary text.

Tracked in [#15](https://github.com/yuriytkach/shepitnote/issues/15).

### 4. Evaluate Voxtype as an engine, not a replacement product

Voxtype offers useful ideas and implementation experience around chunked processing, engine abstraction, constrained languages, and Linux audio. The experiment should integrate it behind ShepitNote's backend boundary and compare results using the evaluation harness.

ShepitNote should not fork Voxtype merely to recreate the existing meeting workflow inside another codebase.

Tracked in [#14](https://github.com/yuriytkach/shepitnote/issues/14).

### 5. Reduce orchestration coupling

The large Bash entry point should become thinner over time. Pure state, configuration, artifact discovery, and pipeline planning should move into tested modules while shell code remains responsible for external process supervision where appropriate.

Tracked in [#17](https://github.com/yuriytkach/shepitnote/issues/17).

### 6. Consider crash-safe incremental transcription

Background chunk transcription could reduce post-meeting latency and leave a useful partial transcript after interruption. It must remain optional and must never replace retained audio as the source of truth.

Tracked in [#18](https://github.com/yuriytkach/shepitnote/issues/18).

## Related existing work

- [#7](https://github.com/yuriytkach/shepitnote/issues/7) evaluates optional whisper.cpp/Vulkan acceleration on the Radeon 890M. This is a backend implementation concern, not a reason to couple the whole application to whisper.cpp.
- [#12](https://github.com/yuriytkach/shepitnote/issues/12) tracks persistent participant voiceprints for recurring meetings.

## How to evaluate proposed features

A feature belongs in ShepitNote when it materially improves one or more of:

- meeting capture reliability;
- recoverability and reprocessing;
- multilingual transcription quality;
- speaker attribution and correction;
- structured meeting-note quality;
- review effort;
- privacy and user control;
- publishing into the team's knowledge workflow.

A feature may belong in an external engine or upstream project when it is broadly useful for dictation or speech processing but does not require ShepitNote's application context.

When possible, implement generic improvements upstream and keep only the meeting-specific integration in ShepitNote.

## Non-goals for the near term

- replacing the CLI with a full graphical application;
- silently recording or publishing without explicit user control;
- removing local operation in favor of mandatory cloud services;
- supporting every language equally before the uk/ru/en workflow is reliable;
- committing private evaluation recordings or confidential transcripts;
- rewriting the project in Rust, Python, or another language solely for architectural aesthetics.

## Repository description suggestion

GitHub's repository description is not changed by this documentation PR. A concise proposed description is:

> Local-first multilingual meeting notes for Linux: dual-track capture, speaker review, Ollama summaries, and controlled Confluence/Slack publishing.

A shorter alternative is:

> Private multilingual meeting notes for Linux, from recoverable audio to reviewed Confluence and Slack output.
