"""WAV 헤더 생성 / 검증 유틸. 일부 엔진(Gemini)은 헤더 없는 raw PCM을 반환하므로
44바이트 RIFF/WAVE 헤더를 붙여 표준 WAV 파일로 저장한다."""
from __future__ import annotations

import struct
import wave
from pathlib import Path


def has_wav_header(audio_bytes: bytes) -> bool:
    """이미 RIFF/WAVE 헤더가 있는지 확인."""
    if len(audio_bytes) < 12:
        return False
    return audio_bytes[:4] == b"RIFF" and audio_bytes[8:12] == b"WAVE"


def build_header(data_size: int, sample_rate: int, channels: int = 1,
                 bits_per_sample: int = 16) -> bytes:
    """44바이트 PCM WAV 헤더 생성."""
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", data_size + 36, b"WAVE", b"fmt ", 16, 1,
        channels, sample_rate, byte_rate, block_align, bits_per_sample,
        b"data", data_size,
    )


def write_wav_from_pcm(pcm_or_wav: bytes, out_path: Path, sample_rate: int,
                       channels: int = 1, bits_per_sample: int = 16) -> Path:
    """raw PCM 또는 이미 WAV인 바이트를 받아 .wav 파일로 저장."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if has_wav_header(pcm_or_wav):
        out_path.write_bytes(pcm_or_wav)
    else:
        header = build_header(len(pcm_or_wav), sample_rate, channels, bits_per_sample)
        out_path.write_bytes(header + pcm_or_wav)
    return out_path


def wav_duration_seconds(path: Path) -> float:
    """WAV 길이(초). ffprobe 없이 표준 라이브러리로 계산."""
    with wave.open(str(path), "rb") as w:
        frames = w.getnframes()
        rate = w.getframerate()
        return frames / float(rate) if rate else 0.0
