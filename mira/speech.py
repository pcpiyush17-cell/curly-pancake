from __future__ import annotations

import os
from typing import Protocol


class SpeechProvider(Protocol):
    name: str
    transcription_enabled: bool
    synthesis_enabled: bool

    def transcribe(self, audio: bytes, content_type: str) -> str: ...
    def synthesize(self, text: str) -> bytes: ...


class BrowserSpeechFallback:
    name = "browser"
    transcription_enabled = False
    synthesis_enabled = False

    def transcribe(self, audio: bytes, content_type: str) -> str:
        raise RuntimeError("Server transcription is not configured")

    def synthesize(self, text: str) -> bytes:
        raise RuntimeError("Server speech synthesis is not configured")


class OpenAISpeechProvider:
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        transcription_model: str | None,
        synthesis_model: str | None,
        voice: str,
    ) -> None:
        from openai import OpenAI

        timeout = float(os.getenv("MIRA_OPENAI_SPEECH_TIMEOUT_SECONDS", "30"))
        self.client = OpenAI(api_key=api_key, timeout=timeout, max_retries=1)
        self.transcription_model = transcription_model
        self.synthesis_model = synthesis_model
        self.voice = voice
        self.transcription_enabled = bool(transcription_model)
        self.synthesis_enabled = bool(synthesis_model)

    def transcribe(self, audio: bytes, content_type: str) -> str:
        if not self.transcription_model:
            raise RuntimeError("Server transcription is not configured")
        result = self.client.audio.transcriptions.create(
            model=self.transcription_model,
            file=("voice-input.webm", audio, content_type),
            language="en",
        )
        return result.text.strip()

    def synthesize(self, text: str) -> bytes:
        if not self.synthesis_model:
            raise RuntimeError("Server speech synthesis is not configured")
        response = self.client.audio.speech.create(
            model=self.synthesis_model,
            voice=self.voice,
            input=text,
            response_format="mp3",
        )
        return response.content


def build_speech_provider() -> SpeechProvider:
    api_key = os.getenv("OPENAI_API_KEY")
    transcription_model = os.getenv("MIRA_OPENAI_STT_MODEL")
    synthesis_model = os.getenv("MIRA_OPENAI_TTS_MODEL")
    if not api_key or not (transcription_model or synthesis_model):
        return BrowserSpeechFallback()
    try:
        return OpenAISpeechProvider(
            api_key=api_key,
            transcription_model=transcription_model,
            synthesis_model=synthesis_model,
            voice=os.getenv("MIRA_OPENAI_TTS_VOICE", "coral"),
        )
    except ImportError:
        return BrowserSpeechFallback()

