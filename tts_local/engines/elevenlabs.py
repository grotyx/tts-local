"""ElevenLabs TTS 엔진 (REST). 프리셋/저장된 voice_id 사용 + 보이스 클로닝 지원.

- synthesize: voice_id로 합성. output_format=pcm_24000 → WAV로 저장.
- add_voice: 참조 음성 파일들로 Instant Voice Clone 보이스를 생성하고 voice_id 반환.
- synthesize_clone: 참조 음성으로 즉석 보이스를 만든 뒤 합성(편의 메서드).
"""
from __future__ import annotations

import os
from pathlib import Path

import requests

from .base import TTSEngine
from ..wav_utils import write_wav_from_pcm

_BASE = "https://api.elevenlabs.io/v1"


class ElevenLabsEngine(TTSEngine):
    name = "elevenlabs"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.model = cfg.get("model", "eleven_multilingual_v2")
        self.default_voice = cfg.get("voice_id", "")
        self.sample_rate = int(cfg.get("sample_rate", 24000))
        self.api_key = (os.environ.get(cfg.get("api_key_env", "ELEVENLABS_API_KEY"))
                        or cfg.get("api_key"))
        if not self.api_key:
            raise RuntimeError("ELEVENLABS_API_KEY 환경변수가 설정되어 있지 않습니다.")

    def _headers(self) -> dict:
        return {"xi-api-key": self.api_key}

    def synthesize(self, text, out_path, *, voice=None, instruct=None, language=None):
        voice_id = voice or self.default_voice
        if not voice_id:
            raise RuntimeError("ElevenLabs voice_id가 지정되지 않았습니다.")
        url = f"{_BASE}/text-to-speech/{voice_id}"
        params = {"output_format": f"pcm_{self.sample_rate}"}
        payload = {"text": text, "model_id": self.model}
        r = requests.post(url, headers=self._headers(), params=params,
                          json=payload, timeout=300)
        if r.status_code != 200:
            raise RuntimeError(f"ElevenLabs API {r.status_code}: {r.text[:300]}")
        return write_wav_from_pcm(r.content, out_path, self.sample_rate)

    def add_voice(self, name: str, sample_paths: list[str | Path]) -> str:
        """참조 음성 파일들로 보이스를 생성하고 voice_id 반환."""
        url = f"{_BASE}/voices/add"
        files = [("files", (Path(p).name, open(p, "rb"), "audio/wav"))
                 for p in sample_paths]
        try:
            r = requests.post(url, headers=self._headers(),
                              data={"name": name}, files=files, timeout=300)
        finally:
            for _, (_, fh, _) in files:
                fh.close()
        if r.status_code != 200:
            raise RuntimeError(f"ElevenLabs add_voice {r.status_code}: {r.text[:300]}")
        return r.json()["voice_id"]

    def synthesize_clone(self, text, out_path, *, ref_audio, ref_text=None,
                         language=None, x_vector_only=False):
        voice_id = self.add_voice(name="tts-local-clone", sample_paths=[ref_audio])
        return self.synthesize(text, out_path, voice=voice_id)
