"""Gemini TTS 엔진 (google-genai SDK, gemini-3.x-flash-tts).

instruct를 'Audio Profile / Director's note / Sample Context' 구조의 프롬프트로 넣어
톤·스타일·코드스위칭(영어↔한국어)을 제어한다. 스트리밍 PCM(L16)을 받아 WAV로 저장.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

from .base import TTSEngine

_PROMPT_TEMPLATE = """Read the following transcript based on the audio profile and director's note.

# Audio Profile
{audio_profile}

# Director's note
{directors_note}

## Sample Context:
{context}

## Transcript:
{text}"""


def _parse_rate_bits(mime: str) -> tuple[int, int]:
    rate, bits = 24000, 16
    for p in (mime or "").split(";"):
        p = p.strip()
        if p.lower().startswith("rate="):
            try: rate = int(p.split("=", 1)[1])
            except (ValueError, IndexError): pass
        elif p.startswith("audio/L") or p.startswith("audio/l"):
            try: bits = int(p.split("L", 1)[1].split("l", 1)[-1])
            except (ValueError, IndexError): pass
    return rate, bits


def _wav(data: bytes, rate: int, bits: int) -> bytes:
    return struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(data), b"WAVE",
                       b"fmt ", 16, 1, 1, rate, rate * bits // 8, bits // 8, bits,
                       b"data", len(data)) + data


class GeminiEngine(TTSEngine):
    name = "gemini"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.model = cfg.get("model", "gemini-3.1-flash-tts-preview")
        self.default_voice = cfg.get("voice", "Charon")
        self.temperature = float(cfg.get("temperature", 0.6))
        self.audio_profile = cfg.get("audio_profile", "A clear, professional academic presenter.")
        self.directors_note = cfg.get("directors_note",
            "Style: confident, clear, professional. Pace: slightly brisk, natural, no dead air. Accent: neutral.")
        self.default_context = cfg.get("instruct",
            "An university professor presenting at an academic conference: clear, confident, "
            "professional delivery at a slightly brisk pace, switching seamlessly between English and Korean.")
        self.api_key = (os.environ.get(cfg.get("api_key_env", "GEMINI_API_KEY"))
                        or cfg.get("api_key"))
        if not self.api_key or str(self.api_key).startswith("YOUR_"):
            raise RuntimeError("GEMINI_API_KEY가 없습니다(.env 또는 환경변수).")
        self._client = None

    def _client_(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def synthesize(self, text, out_path, *, voice=None, instruct=None, language=None):
        from google.genai import types
        context = self.default_context if instruct is None else instruct
        prompt = _PROMPT_TEMPLATE.format(
            audio_profile=self.audio_profile, directors_note=self.directors_note,
            context=context, text=text)
        cfg = types.GenerateContentConfig(
            temperature=self.temperature,
            response_modalities=["audio"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice or self.default_voice))),
        )
        buf, mime = bytearray(), None
        stream = self._client_().models.generate_content_stream(
            model=self.model,
            contents=[types.Content(role="user",
                                    parts=[types.Part.from_text(text=prompt)])],
            config=cfg)
        for chunk in stream:
            if not getattr(chunk, "candidates", None):
                continue
            content = chunk.candidates[0].content
            if not content or not content.parts:
                continue
            part = content.parts[0]
            if part.inline_data and part.inline_data.data:
                buf.extend(part.inline_data.data)
                mime = part.inline_data.mime_type
        if not buf:
            raise RuntimeError("Gemini TTS: 오디오 데이터가 비어 있습니다.")
        rate, bits = _parse_rate_bits(mime or "audio/L16;rate=24000")
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(_wav(bytes(buf), rate, bits))
        return out_path
