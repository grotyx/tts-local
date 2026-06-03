"""엔진 레지스트리 + 팩토리."""
from __future__ import annotations

from .base import TTSEngine


def make_engine(name: str, cfg: dict) -> TTSEngine:
    """엔진 이름으로 인스턴스 생성. 무거운 import는 선택된 엔진만 로드."""
    name = (name or "").lower()
    if name == "qwen_local":
        from .qwen_local import QwenLocalEngine
        return QwenLocalEngine(cfg)
    if name == "gemini":
        from .gemini import GeminiEngine
        return GeminiEngine(cfg)
    if name == "elevenlabs":
        from .elevenlabs import ElevenLabsEngine
        return ElevenLabsEngine(cfg)
    raise ValueError(f"알 수 없는 엔진: {name!r} (qwen_local | gemini | elevenlabs)")


AVAILABLE_ENGINES = ["qwen_local", "gemini", "elevenlabs"]
