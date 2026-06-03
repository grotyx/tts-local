"""오케스트레이터: 대본 → TTS 음성 → (PPTX 오디오 삽입) → MP4 인코딩.

단계별로 중간 산출물을 output 디렉터리에 남겨 재실행/검수가 쉽다.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .engines import make_engine
from .script_parser import parse_script, build_narrations
from .wav_utils import wav_duration_seconds
from . import pptx_audio, slide_export, video_encoder

logger = logging.getLogger(__name__)

# Qwen 등 자동회귀 TTS는 짧은 텍스트에서 비음성(웃음·숨소리)을 환각하며 길이가 폭증할 수 있다.
# 텍스트 길이로 기대 시간을 추정해, 과도하게 길면 재합성한다.
MAX_SYNTH_RETRIES = 4


def _has_cjk(text: str) -> bool:
    return any("가" <= c <= "힣" or "぀" <= c <= "ヿ"
               or "一" <= c <= "鿿" for c in text)


def _estimate_seconds(text: str) -> float:
    """기대 발화 길이(초) 추정. 한국어/CJK는 초당 글자수가 적어 별도 보정."""
    words = len(text.split())
    cps = 6.5 if _has_cjk(text) else 15.0  # CJK는 ~6.5자/초, 영어는 ~15자/초
    return max(words / 2.3, len(text) / cps, 0.8)


def _is_overlong(actual: float, text: str) -> bool:
    """길이가 기대치 대비 비정상적으로 길면(환각 의심) True."""
    return actual > _estimate_seconds(text) * 1.9 + 2.5


import re as _re
_SENT_SPLIT = _re.compile(r"(?<=[.?!。])\s+")


def _split_sentences(text: str) -> list[str]:
    """문장 단위 분리(환각 회피용). em-dash는 쉼표로 치환."""
    text = text.replace("—", ", ").replace("–", ", ")
    return [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]


def _synthesize_chunked(engine, text, out_path: Path, cfg) -> Path:
    """긴 텍스트를 문장 단위로 합성해 이어붙인다(환각 회피 폴백).
    각 문장도 과도하게 길면 seed를 바꿔 재시도한다."""
    import numpy as np
    import soundfile as sf

    sents = _split_sentences(text)
    base_seed = getattr(engine, "seed", None)
    out_path = Path(out_path)
    tmpdir = out_path.parent / "_chunks"
    tmpdir.mkdir(parents=True, exist_ok=True)
    arrays, sr = [], 24000
    try:
        for j, sent in enumerate(sents):
            tmp = tmpdir / f"c{j:02d}.wav"
            for attempt in range(MAX_SYNTH_RETRIES):
                if base_seed is not None:
                    engine.seed = base_seed + attempt
                engine.synthesize(sent, tmp, voice=cfg.voice,
                                  instruct=cfg.instruct, language=cfg.language)
                if not _is_overlong(wav_duration_seconds(tmp), sent):
                    break
            data, sr = sf.read(str(tmp))
            arrays.append(data)
    finally:
        if base_seed is not None:
            engine.seed = base_seed
    sf.write(str(out_path), np.concatenate(arrays), sr)
    for f in tmpdir.glob("c*.wav"):
        f.unlink()
    try:
        tmpdir.rmdir()
    except OSError:
        pass
    return out_path


@dataclass
class PipelineConfig:
    engine: str = "qwen_local"
    engine_cfg: dict = field(default_factory=dict)
    voice: str | None = None
    instruct: str | None = None
    language: str | None = None
    # 클로닝(선택)
    clone: bool = False
    ref_audio: str | None = None
    ref_text: str = ""
    clone_mode: str = "full"   # "full"(음색+ref_text) | "xvec"(음색만)
    # 영상
    video_method: str = "ffmpeg"   # "ffmpeg" | "powerpoint" | "none"
    width: int = 1920
    height: int = 1080
    fps: int = 30
    gap_seconds: float = 0.7
    crf: int = 18
    preset: str = "medium"
    # 음성 후처리: 배속(음정 유지, ffmpeg atempo). 1.0 = 원본
    speed: float = 1.0
    # pptx
    embed_audio: bool = True
    autoplay: bool = True

    @classmethod
    def from_json(cls, path: Path) -> "PipelineConfig":
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
        engine = cfg.get("engine", "qwen_local")
        ecfg = cfg.get("engines", {}).get(engine, {})
        v = cfg.get("video", {})
        p = cfg.get("pptx", {})
        return cls(
            engine=engine, engine_cfg=ecfg,
            voice=ecfg.get("voice") or ecfg.get("voice_id"),
            instruct=ecfg.get("instruct"), language=ecfg.get("language"),
            video_method=v.get("method", "ffmpeg"),
            width=v.get("width", 1920), height=v.get("height", 1080),
            fps=v.get("fps", 30), gap_seconds=v.get("gap_seconds", 0.7),
            crf=v.get("crf", 18), preset=v.get("preset", "medium"),
            speed=float(v.get("speed", 1.0)),
            embed_audio=p.get("embed_audio", True), autoplay=p.get("autoplay", True),
        )


def _atempo_chain(speed: float) -> str:
    """atempo는 0.5~2.0만 지원하므로 범위를 벗어나면 곱으로 체이닝."""
    s = float(speed)
    parts: list[str] = []
    while s > 2.0:
        parts.append("atempo=2.0"); s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5"); s /= 0.5
    parts.append(f"atempo={s:.4f}")
    return ",".join(parts)


def apply_speed(src: Path, dst: Path, speed: float) -> Path:
    """ffmpeg atempo로 음정 유지한 채 배속 적용."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-filter:a", _atempo_chain(speed),
         "-ar", "24000", "-ac", "1", str(dst)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"atempo 실패: {proc.stderr[-800:]}")
    return dst


def generate_audio(narrations: list[str], out_dir: Path, cfg: PipelineConfig,
                   skip_existing: bool = True) -> list[Path]:
    """나레이션 리스트 → slide_001.wav ... 생성. 1-based 인덱스."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(cfg.engine, cfg.engine_cfg)
    paths: list[Path] = []
    try:
        for i, text in enumerate(narrations, start=1):
            wav = out_dir / f"slide_{i:03d}.wav"
            if skip_existing and wav.exists() and wav.stat().st_size > 1000:
                logger.info("건너뜀(이미 있음): %s", wav.name)
                paths.append(wav)
                continue
            if not text.strip():
                logger.warning("슬라이드 %d 나레이션 비어있음 — 건너뜀", i)
                paths.append(wav)
                continue
            logger.info("합성 %d/%d: %s...", i, len(narrations), text[:50])
            # speed!=1.0 이면 원본을 raw/에 두고 배속본을 최종 경로에 만든다(재튜닝 시 재합성 불필요)
            target = (out_dir / "raw" / wav.name) if cfg.speed != 1.0 else wav

            # 환각(웃음 등)으로 길이가 폭증하면 seed를 바꿔 재합성
            base_seed = getattr(engine, "seed", None)
            for attempt in range(MAX_SYNTH_RETRIES):
                if base_seed is not None:
                    engine.seed = base_seed + attempt
                if cfg.clone and cfg.ref_audio:
                    engine.synthesize_clone(text, target, ref_audio=cfg.ref_audio,
                                            ref_text=cfg.ref_text, language=cfg.language,
                                            x_vector_only=(cfg.clone_mode == "xvec"))
                else:
                    engine.synthesize(text, target, voice=cfg.voice,
                                      instruct=cfg.instruct, language=cfg.language)
                dur = wav_duration_seconds(target)
                if not _is_overlong(dur, text):
                    break
                logger.warning("슬라이드 %d 비정상 길이 %.1fs(기대 ~%.1fs) — 재합성 %d/%d",
                               i, dur, _estimate_seconds(text), attempt + 1, MAX_SYNTH_RETRIES)
            if base_seed is not None:
                engine.seed = base_seed  # 복원

            # seed 재시도로도 안 잡히면 문장 단위 분할 합성으로 폴백
            if (not (cfg.clone and cfg.ref_audio)
                    and _is_overlong(wav_duration_seconds(target), text)
                    and len(_split_sentences(text)) > 1):
                logger.warning("슬라이드 %d 문장분할 합성으로 폴백", i)
                _synthesize_chunked(engine, text, target, cfg)

            if cfg.speed != 1.0:
                apply_speed(target, wav, cfg.speed)
            paths.append(wav)
    finally:
        engine.close()
    return paths


def run(script_path: Path, pptx_path: Path, out_dir: Path, cfg: PipelineConfig,
        groups: list[int] | None = None, skip_existing: bool = True,
        narrations_override: list[str] | None = None) -> dict:
    """전체 파이프라인 실행. 산출물 경로 dict 반환.
    narrations_override가 주어지면 대본 재파싱 대신 그 나레이션을 그대로 사용한다
    (사용자가 narrations.json을 직접 편집한 경우 보존)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict = {"out_dir": str(out_dir)}

    # 1) 나레이션 준비: 편집본 우선, 없으면 대본 파싱
    if narrations_override is not None:
        narrations = narrations_override
        logger.info("기존 narration 사용 (%d개, 대본 재파싱 안 함)", len(narrations))
    else:
        script = parse_script(script_path)
        narrations = build_narrations(script, groups)
    (out_dir / "narrations.json").write_text(
        json.dumps({i + 1: t for i, t in enumerate(narrations)},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("나레이션 %d개 준비", len(narrations))

    # 2) TTS 음성 생성
    audio_dir = out_dir / "audio"
    audio_paths = generate_audio(narrations, audio_dir, cfg, skip_existing=skip_existing)
    results["audio_dir"] = str(audio_dir)

    audio_by_slide = {i + 1: p for i, p in enumerate(audio_paths)
                      if Path(p).exists() and Path(p).stat().st_size > 1000}

    stem = Path(pptx_path).stem
    pptx_out = out_dir / f"{stem}_with_audio.pptx"
    mp4_out = out_dir / f"{stem}.mp4"

    if cfg.video_method == "powerpoint":
        # COM 안전 경로: 애니메이션/내장 동영상이 있는 덱도 삽입·타이밍·영상화를
        # PowerPoint가 직접 처리(기존 타임라인 보존). python-pptx 삽입은 건너뜀.
        from .wav_utils import wav_duration_seconds
        from . import pptx_com
        durations = [wav_duration_seconds(p) if (Path(p).exists() and
                     Path(p).stat().st_size > 1000) else 0.0 for p in audio_paths]
        res = pptx_com.narrate_and_export(
            pptx_path, audio_by_slide, durations, pptx_out, mp4_out,
            gap_seconds=cfg.gap_seconds, vert_resolution=cfg.height, fps=cfg.fps)
        results.update(res)
        return results

    # ffmpeg / none 경로: python-pptx로 오디오 삽입(정적 덱에 적합)
    if cfg.embed_audio:
        pptx_audio.embed_audio(pptx_path, audio_by_slide, pptx_out, autoplay=cfg.autoplay)
        results["pptx_with_audio"] = str(pptx_out)

    if cfg.video_method == "ffmpeg":
        img_dir = out_dir / "slides_png"
        images = slide_export.export_slides_png(pptx_path, img_dir, cfg.width, cfg.height)
        n = min(len(images), len(audio_paths))
        slides = [(images[i], audio_paths[i]) for i in range(n)
                  if Path(audio_paths[i]).exists() and Path(audio_paths[i]).stat().st_size > 1000]
        video_encoder.encode_ffmpeg(
            slides, mp4_out, width=cfg.width, height=cfg.height, fps=cfg.fps,
            gap_seconds=cfg.gap_seconds, crf=cfg.crf, preset=cfg.preset)
        results["mp4"] = str(mp4_out)

    return results
