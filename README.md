# Pipecat Lokutor

Lokutor text-to-speech and speech-to-text integration for [Pipecat](https://github.com/pipecat-ai/pipecat).

**Get an API key and test voices at [app.lokutor.com](https://app.lokutor.com).**
**Documentation: [docs.lokutor.com](https://docs.lokutor.com)**

> Lokutor TTS runs entirely on **CPU-only infrastructure**, keeping costs low while delivering high-quality speech synthesis. No GPU markup — just affordable, scalable TTS.

## Installation

```bash
pip install pipecat-lokutor
```

Or with uv:

```bash
uv add pipecat-lokutor
```

## Usage

```python
from pipecat_lokutor import LokutorTTSService

tts = LokutorTTSService(
    api_key="your_api_key",
    voice_id="F1",
    params=LokutorTTSService.InputParams(
        language="en",
        speed=1.0,
        steps=5,
        visemes=False,
    ),
)
```

### Pipecat Pipeline

```python
from pipecat.pipeline.pipeline import Pipeline

pipeline = Pipeline([
    transport.input(),
    stt,
    llm,
    tts,
    transport.output(),
])
```

### Expression tags

Lokutor TTS understands expression tags in the text: the sounds `[laugh]`, `[sigh]` and `[breath]`, and eight emotion tags that change how a sentence is spoken. They are plain text, so an LLM can emit them in its reply and `LokutorTTSService` passes them through unchanged. See [Expression tags](https://docs.lokutor.com/api-reference/expression-tags) for the list and how to use them.

## Speech-to-text

`LokutorSTTService` streams audio to Lokutor's real-time recogniser (`wss://api.lokutor.com/ws/stt`, our own Conv 2.0 model, nine languages: `en`, `es`, `ca`, `gl`, `eu`, `pt`, `fr`, `it`, `de`) and pushes interim and final transcripts.

```python
from pipecat.transcriptions.language import Language
from pipecat_lokutor import LokutorSTTService

stt = LokutorSTTService(
    api_key="your_api_key",
    settings=LokutorSTTService.Settings(
        language=Language.ES,          # None: detect the language
        keyterms=["Lokutor", "Pipecat"],  # optional custom vocabulary, up to 100
    ),
)
```

Notes:

- The pipeline's audio input must be **16 kHz mono** (Pipecat's default); the service refuses to start otherwise.
- Lokutor ends a session when you ask for the final transcript, so the service sends `end` as soon as Pipecat's VAD reports that the user stopped speaking and reopens the socket for the next utterance (`finalize_on_vad_stop=True`). Set it to `False` to rely on the server's own end-of-utterance detection (about 0.7 s of silence).
- Set `ttfs_p99_latency` to the value you measure for your setup with the [Pipecat STT benchmark](https://github.com/pipecat-ai/stt-benchmark).
- The service was tested with Pipecat 1.12.

```python
pipeline = Pipeline([transport.input(), stt, llm, tts, transport.output()])
```

## Voices

Browse and test available voices at [app.lokutor.com](https://app.lokutor.com).

## Supported Languages

32 languages: `en`, `es`, `fr`, `de`, `it`, `pt`, `ja`, `ko`, `zh`, `ar`, `bg`, `hr`, `cs`, `da`, `nl`, `et`, `fi`, `el`, `hi`, `hu`, `id`, `lv`, `lt`, `pl`, `ro`, `ru`, `sk`, `sl`, `sv`, `tr`, `uk`, `vi`.

Pass any Pipecat `Language` (including regional variants like `Language.EN_US`) — it is normalized to the matching Lokutor base code automatically.

## Example

See `examples/groq-stt-groq-llm-lokutor-tts.py` for a full example using Groq STT + Groq LLM + Lokutor TTS.

```bash
# Install dependencies
uv sync

# Set environment variables
export GROQ_API_KEY="your_groq_api_key"
export LOKUTOR_API_KEY="your_lokutor_api_key"

# Run the example
python examples/groq-stt-groq-llm-lokutor-tts.py -t webrtc
```

Then open `http://localhost:7860/client/`.

## Compatibility

Tested with Pipecat v0.0.86+.

## License

BSD 2-Clause License. See `LICENSE` for details.
