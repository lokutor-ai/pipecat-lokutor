# Pipecat Lokutor TTS

Lokutor text-to-speech integration for [Pipecat](https://github.com/pipecat-ai/pipecat).

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

## Voices

| Voice | Description |
|-------|-------------|
| M1-M5 | Male voices |
| F1-F5 | Female voices |

## Supported Languages

EN, ES, FR, PT, KO

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
