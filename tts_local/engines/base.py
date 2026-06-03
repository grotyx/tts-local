"""TTS 엔진 플러그인 인터페이스.

새 엔진을 추가하려면 TTSEngine을 상속하고 synthesize()를 구현한 뒤
engines/__init__.py의 ENGINE_REGISTRY에 등록하면 끝이다.
모든 엔진은 결과를 24kHz mono 16-bit WAV로 out_path에 저장하고 그 경로를 반환한다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class TTSEngine(ABC):
    name: str = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg or {}

    @abstractmethod
    def synthesize(self, text: str, out_path: Path, *,
                   voice: str | None = None,
                   instruct: str | None = None,
                   language: str | None = None) -> Path:
        """텍스트 → WAV 파일. out_path 반환."""
        raise NotImplementedError

    def synthesize_clone(self, text: str, out_path: Path, *,
                         ref_audio: str | Path,
                         ref_text: str | None = None,
                         language: str | None = None,
                         x_vector_only: bool = False) -> Path:
        """참조 음성으로 보이스 클로닝. 미지원 엔진은 NotImplementedError.

        x_vector_only=True 이면 음색(speaker embedding)만 사용(ref_text 불필요).
        """
        raise NotImplementedError(f"'{self.name}' 엔진은 보이스 클로닝을 지원하지 않습니다.")

    def close(self) -> None:
        """리소스 정리(모델 언로드 등). 기본은 no-op."""
        return None
