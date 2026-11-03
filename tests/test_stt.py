"""Tests for LokutorSTTService against a local fake of Lokutor's /ws/stt."""

from __future__ import annotations

import asyncio
import json

import pytest
from websockets.asyncio.server import serve

from pipecat.frames.frames import InterimTranscriptionFrame, TranscriptionFrame
from pipecat.transcriptions.language import Language

from pipecat_lokutor import LokutorSTTService
from pipecat_lokutor.stt import (
    LOKUTOR_STT_LANGUAGES,
    language_to_lokutor_stt_language,
)


def test_stt_covers_nine_languages():
    assert set(LOKUTOR_STT_LANGUAGES) == {"en", "es", "ca", "gl", "eu", "pt", "fr", "it", "de"}


def test_language_mapping():
    assert language_to_lokutor_stt_language(Language.ES) == "es"
    assert language_to_lokutor_stt_language(Language.EN_US) == "en"
    assert language_to_lokutor_stt_language(Language.CA) == "ca"
    assert language_to_lokutor_stt_language(Language.JA) is None
    assert language_to_lokutor_stt_language(None) is None


def test_rejects_other_sample_rates():
    with pytest.raises(ValueError):
        LokutorSTTService(api_key="k", sample_rate=24000)


def test_config_message_language_and_keyterms():
    stt = LokutorSTTService(
        api_key="k",
        settings=LokutorSTTService.Settings(language=Language.ES, keyterms=["Lokutor"]),
    )
    assert stt._config_message() == {"language": "es", "keyterms": ["Lokutor"]}

    detect = LokutorSTTService(api_key="k", settings=LokutorSTTService.Settings(language=None))
    assert detect._config_message() == {"language": ""}


def _service(url: str) -> tuple[LokutorSTTService, list]:
    stt = LokutorSTTService(api_key="secret", base_url=url)
    pushed: list = []

    async def push_frame(frame, direction=None):
        pushed.append(frame)

    async def noop(*a, **k):
        return None

    stt.push_frame = push_frame  # type: ignore[method-assign]
    stt.stop_processing_metrics = noop  # type: ignore[method-assign]
    stt.emit_stt_usage_metrics = noop  # type: ignore[method-assign]
    stt._call_event_handler = noop  # type: ignore[method-assign]
    return stt, pushed


def test_partial_final_and_session_reopen():
    """Interim and final frames, ``end`` on VAD stop, and a new session afterwards."""

    async def main():
        sessions: list[dict] = []

        async def handler(ws):
            session = {"auth": ws.request.headers.get("Authorization"), "audio": 0, "msgs": []}
            sessions.append(session)
            session["msgs"].append(json.loads(await ws.recv()))
            await ws.send(json.dumps({"type": "status", "data": "ready", "lang": "en"}))
            async for message in ws:
                if isinstance(message, bytes):
                    session["audio"] += len(message)
                    if session["audio"] == 640:
                        await ws.send(
                            json.dumps(
                                {
                                    "type": "transcript",
                                    "data": "hel",
                                    "isFinal": False,
                                    "lang": "en",
                                }
                            )
                        )
                else:
                    session["msgs"].append(json.loads(message))
                    await ws.send(
                        json.dumps(
                            {
                                "type": "transcript",
                                "data": f"hello {len(sessions)}",
                                "isFinal": True,
                                "lang": "en",
                            }
                        )
                    )
                    await ws.send(json.dumps({"type": "status", "data": "done"}))
                    await ws.close()

        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            stt, pushed = _service(f"ws://127.0.0.1:{port}")

            await stt._connect_websocket()
            receiver = asyncio.create_task(stt._receive_messages())

            async for _ in stt.run_stt(b"\0" * 640):
                pass
            await asyncio.sleep(0.2)
            await stt._end_session()
            for _ in range(50):
                if len(sessions) == 2 and stt._ready_event.is_set():
                    break
                await asyncio.sleep(0.05)

            # Audio after the reopen goes to the second session.
            async for _ in stt.run_stt(b"\0" * 320):
                pass
            await asyncio.sleep(0.2)

            receiver.cancel()
            await stt._disconnect_websocket()
            return sessions, pushed

    sessions, pushed = asyncio.run(main())

    assert len(sessions) == 2
    assert sessions[0]["auth"] == "Bearer secret"
    assert sessions[0]["msgs"] == [{"language": "en"}, {"type": "end"}]
    assert sessions[0]["audio"] == 640
    assert sessions[1]["audio"] == 320

    interim = [f for f in pushed if isinstance(f, InterimTranscriptionFrame)]
    final = [f for f in pushed if isinstance(f, TranscriptionFrame)]
    assert [f.text for f in interim] == ["hel"]
    assert [f.text for f in final] == ["hello 1"]
    assert final[0].finalized is True


def test_server_error_is_reported():
    async def main():
        stt, _ = _service("ws://unused")
        errors: list[str] = []

        async def push_error(error_msg, **kw):
            errors.append(error_msg)

        stt.push_error = push_error  # type: ignore[method-assign]
        await stt._process_message({"type": "error", "data": "boom"})
        return errors

    assert asyncio.run(main()) == ["Lokutor STT error: boom"]
