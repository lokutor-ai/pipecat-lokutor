#
# Copyright (c) 2024-2026, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Lokutor speech-to-text service for Pipecat.

Streams 16 kHz mono PCM to Lokutor's ``/ws/stt`` WebSocket and turns the
server's ``transcript`` messages into Pipecat transcription frames:

- ``isFinal: false``  -> ``InterimTranscriptionFrame``
- ``isFinal: true``   -> ``TranscriptionFrame`` (``finalized=True``)

Lokutor's endpoint ends a session when you send ``{"type": "end"}``: the server
finalizes the utterance in progress, answers ``{"type": "status", "data": "done"}``
and closes. When Pipecat's VAD reports that the user stopped speaking this
service sends ``end`` (so the final transcript does not wait for the server's
own 0.7 s silence timer) and then reopens the socket for the next utterance.
"""

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, Optional

from loguru import logger
from websockets.protocol import State

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessorSetup
from pipecat.services.settings import STTSettings
from pipecat.services.stt_service import WebsocketSTTService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601
from pipecat.utils.tracing.service_decorators import traced_stt
from pipecat.utils.types import NOT_GIVEN, NotGiven

# Languages Lokutor's recogniser understands (one model for all of them).
LOKUTOR_STT_LANGUAGES = {
    "en": Language.EN,
    "es": Language.ES,
    "ca": Language.CA,
    "gl": Language.GL,
    "eu": Language.EU,
    "pt": Language.PT,
    "fr": Language.FR,
    "it": Language.IT,
    "de": Language.DE,
}

# The wire format is fixed: 16-bit PCM, 16 kHz, mono.
LOKUTOR_STT_SAMPLE_RATE = 16000

# Seconds to wait for the server's ``ready`` status after the config message.
_READY_TIMEOUT = 10.0


def language_to_lokutor_stt_language(language: Optional[Language]) -> Optional[str]:
    """Map a Pipecat ``Language`` (regional variants included) to a Lokutor STT code.

    Returns ``None`` for a language the recogniser does not cover.
    """
    if language is None:
        return None
    base = str(getattr(language, "value", language)).split("-")[0].lower()
    return base if base in LOKUTOR_STT_LANGUAGES else None


@dataclass
class LokutorSTTSettings(STTSettings):
    """Settings for the Lokutor STT service.

    Parameters:
        keyterms: Custom vocabulary (up to 100 names or terms) written the way
            you give them when what is heard is close. ``None`` sends none.
    """

    keyterms: list[str] | None | NotGiven = field(default_factory=lambda: NOT_GIVEN)


class LokutorSTTService(WebsocketSTTService):
    """Lokutor real-time speech-to-text over WebSocket (``wss://api.lokutor.com/ws/stt``).

    Example::

        stt = LokutorSTTService(
            api_key="your_api_key",
            settings=LokutorSTTService.Settings(language=Language.ES),
        )

    The pipeline's audio input must be 16 kHz mono (Pipecat's default).
    Pass ``language=None`` in the settings to have the language detected.
    """

    Settings = LokutorSTTSettings
    _settings: LokutorSTTSettings

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "wss://api.lokutor.com/ws/stt",
        sample_rate: Optional[int] = None,
        finalize_on_vad_stop: bool = True,
        settings: Optional[LokutorSTTSettings] = None,
        ttfs_p99_latency: Optional[float] = None,
        **kwargs,
    ):
        """Initialize the Lokutor STT service.

        Args:
            api_key: Lokutor API key (or a short-lived ``wst_`` ticket).
            base_url: WebSocket URL of the STT endpoint.
            sample_rate: Must be 16000 or None (use the pipeline's rate, which must be 16000).
            finalize_on_vad_stop: Send ``end`` when Pipecat's VAD reports the
                user stopped speaking, instead of waiting for the server's
                silence timer. The socket is reopened for the next utterance.
            settings: Runtime settings (language, keyterms).
            ttfs_p99_latency: P99 time from speech end to final transcript, in
                seconds. Measure it for your setup with the Pipecat STT benchmark.
            **kwargs: Passed on to ``WebsocketSTTService``.
        """
        default_settings = self.Settings(
            model=None,
            language=Language.EN.value,
            keyterms=None,
        )
        if settings is not None:
            default_settings.apply_update(settings)

        if sample_rate not in (None, LOKUTOR_STT_SAMPLE_RATE):
            raise ValueError("Lokutor STT takes 16 kHz audio only")

        super().__init__(
            sample_rate=sample_rate,
            ttfs_p99_latency=ttfs_p99_latency,
            settings=default_settings,
            **kwargs,
        )

        self._api_key = api_key
        self._base_url = base_url
        self._finalize_on_vad_stop = finalize_on_vad_stop
        self._receive_task = None
        self._session_ending = False
        # Set while a usable socket exists; cleared while one is being reopened.
        self._ready_event = asyncio.Event()
        self._ready_event.set()

    def can_generate_metrics(self) -> bool:
        return True

    def language_to_service_language(self, language: Language) -> Optional[str]:
        return language_to_lokutor_stt_language(language)

    async def setup(self, setup: FrameProcessorSetup):
        await super().setup(setup)
        if self.sample_rate != LOKUTOR_STT_SAMPLE_RATE:
            raise ValueError(
                f"Lokutor STT takes 16 kHz audio, the pipeline provides {self.sample_rate} Hz: "
                "set audio_in_sample_rate=16000 in PipelineParams"
            )
        await self._connect()

    async def stop(self, frame: EndFrame):
        await super().stop(frame)
        await self._disconnect()

    async def cancel(self, frame: CancelFrame):
        await super().cancel(frame)
        await self._disconnect()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, VADUserStoppedSpeakingFrame) and self._finalize_on_vad_stop:
            await self._end_session()

    async def _end_session(self):
        """Ask the server to finalize the utterance; the server then closes the socket."""
        ws = self._websocket
        if self._session_ending or not ws or ws.state is not State.OPEN:
            return
        self._session_ending = True
        self._ready_event.clear()
        try:
            await ws.send(json.dumps({"type": "end"}))
        except Exception as e:
            logger.warning(f"{self} failed to send end: {e}")
            self._session_ending = False
            self._ready_event.set()

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        """Send audio to Lokutor; transcripts arrive through the receive task."""
        await self._ready_event.wait()

        try:
            if not self._websocket or self._websocket.state is not State.OPEN:
                await self._connect_websocket()
            if self._websocket:
                await self._websocket.send(audio)
        except Exception as e:
            yield ErrorFrame(error=f"Lokutor STT error: {e}")
            return

        yield None

    async def _update_settings(self, delta: STTSettings) -> dict[str, Any]:
        changed = await super()._update_settings(delta)
        if changed:
            await self._disconnect()
            await self._connect()
        return changed

    async def _connect(self):
        await super()._connect()
        await self._connect_websocket()
        if self._websocket and not self._receive_task:
            self._receive_task = self.create_task(self._receive_task_handler(self._report_error))

    async def _disconnect(self):
        await super()._disconnect()
        if self._receive_task:
            await self.cancel_task(self._receive_task)
            self._receive_task = None
        await self._disconnect_websocket()

    def _config_message(self) -> dict:
        language = self._settings.language
        config: dict[str, Any] = {"language": language if language else ""}
        keyterms = self._settings.keyterms
        if keyterms:
            config["keyterms"] = list(keyterms)
        return config

    async def _connect_websocket(self):
        if self._websocket and self._websocket.state is State.OPEN:
            return

        logger.debug("Connecting to Lokutor STT")
        try:
            ws = await self._websocket_connect(
                self._base_url,
                additional_headers={"Authorization": f"Bearer {self._api_key}"},
            )
            await ws.send(json.dumps(self._config_message()))
            # Read up to the "ready" status here: audio sent earlier is not transcribed.
            await asyncio.wait_for(self._await_ready(ws), _READY_TIMEOUT)
            self._websocket = ws
            self._session_ending = False
            await self._call_event_handler("on_connected")
        except Exception as e:
            self._websocket = None
            await self.push_error(error_msg=f"Lokutor STT connection error: {e}", exception=e)
            await self._call_event_handler("on_connection_error", f"{e}")
            raise
        finally:
            self._ready_event.set()

    @staticmethod
    async def _await_ready(ws):
        while True:
            data = _parse(await ws.recv())
            if data.get("type") == "status" and data.get("data") == "ready":
                return
            if data.get("type") == "error":
                await ws.close()
                raise ConnectionError(f"Lokutor STT refused the session: {data.get('data')}")

    async def _disconnect_websocket(self):
        try:
            if self._websocket and self._websocket.state is State.OPEN:
                logger.debug("Disconnecting from Lokutor STT")
                await self._websocket.close()
        except Exception as e:
            logger.error(f"{self} error closing websocket: {e}")
        finally:
            self._websocket = None
            await self._call_event_handler("on_disconnected")

    def _get_websocket(self):
        if self._websocket:
            return self._websocket
        raise Exception("Websocket not connected")

    async def _receive_messages(self):
        while True:
            async for message in self._get_websocket():
                data = _parse(message)
                if data:
                    await self._process_message(data)

            # The server closed the socket. After our own ``end`` that is the
            # normal end of a session: open a new one for the next utterance.
            if self._session_ending and not self._disconnecting:
                self._websocket = None
                await self._connect_websocket()
                continue
            return

    async def _process_message(self, data: dict):
        kind = data.get("type")

        if kind == "transcript":
            text = (data.get("data") or "").strip()
            if not text:
                return
            language = data.get("lang") or None
            if data.get("isFinal"):
                await self.stop_processing_metrics()
                await self._handle_transcription(text, True, language)
                await self.emit_stt_usage_metrics()
                await self.push_frame(
                    TranscriptionFrame(
                        text,
                        self._user_id,
                        time_now_iso8601(),
                        language,
                        result=data,
                        finalized=True,
                    )
                )
            else:
                await self.push_frame(
                    InterimTranscriptionFrame(
                        text, self._user_id, time_now_iso8601(), language, result=data
                    )
                )
        elif kind == "error":
            await self.push_error(error_msg=f"Lokutor STT error: {data.get('data')}")
        # {"type": "status", "data": "ready" | "done"} need no action here.

    @traced_stt
    async def _handle_transcription(
        self, transcript: str, is_final: bool, language: Optional[str] = None
    ):
        """Record a transcription for tracing."""
        pass


def _parse(message) -> dict:
    if isinstance(message, bytes):
        return {}
    try:
        data = json.loads(message)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
