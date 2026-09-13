# Changelog

## 0.2.0 (2026-09-13)

- Fixed end-of-stream detection: the server signals the end of a synthesis
  with the literal text `EOS`, which the old JSON-only check never matched —
  so every utterance hung until the 10s receive timeout and emitted a
  spurious error frame. `run_tts` now finishes promptly on `EOS`.
- Expanded language support from 5 to all 32 Lokutor languages. Any Pipecat
  `Language` (including regional variants such as `Language.EN_US`) is
  normalized to the matching Lokutor base code.
- Send the canonical `language` field on the wire (matches Lokutor's
  homogenized API vocabulary: `voice` / `language` / `speed` / `steps`).
- Added a test suite for the language mapping.

## 0.1.3 (2026-06-01)

- Fixed PyPI dependency name: `pipecat` -> `pipecat-ai`
- Fixed wheel packaging (hatchling packages config)

## 0.1.1 (2026-06-01)

- Fixed PyPI dependency name: `pipecat` -> `pipecat-ai`

## 0.1.0 (2026-03-27)

- Initial release
- Lokutor TTS service with WebSocket-based streaming
- Support for EN, ES, FR, PT, KO languages
- Multiple voices: M1-M5 (male) and F1-F5 (female)
- Automatic reconnection with exponential backoff
- Metrics tracking
- Full frame lifecycle management
