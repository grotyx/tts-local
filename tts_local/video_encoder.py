"""슬라이드 + 오디오 → MP4 인코딩.

두 가지 경로:
  encode_ffmpeg     : 슬라이드 PNG + 오디오를 ffmpeg로 합성 (정적 슬라이드에 최적, 싱크 정확)
  encode_powerpoint : 오디오 삽입된 PPTX를 PowerPoint 네이티브로 영상화 (애니메이션/전환 보존)
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import time
from pathlib import Path

from .wav_utils import wav_duration_seconds

logger = logging.getLogger(__name__)


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패:\n{' '.join(cmd)}\n{proc.stderr[-1500:]}")


def _audio_duration(path: Path) -> float:
    """WAV는 stdlib로, 그 외(mp3 등)는 ffprobe로 길이 측정."""
    p = Path(path)
    if p.suffix.lower() == ".wav":
        try:
            return wav_duration_seconds(p)
        except Exception:  # noqa: BLE001
            pass
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nokey=1:noprint_wrappers=1", str(p)],
        capture_output=True, text=True)
    return float(out.stdout.strip() or 0.0)


def encode_ffmpeg(slides: list[tuple[Path, Path]], out_path: Path, *,
                  width: int = 1920, height: int = 1080, fps: int = 30,
                  gap_seconds: float = 0.7, crf: int = 18,
                  preset: str = "medium", work_dir: Path | None = None) -> Path:
    """slides: [(image_png, audio_wav), ...] 순서대로. 슬라이드당 길이=오디오+gap."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg 가 PATH에 없습니다.")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(work_dir) if work_dir else out_path.parent / "_segments"
    work.mkdir(parents=True, exist_ok=True)

    scale_pad = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                 f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps}")

    segments: list[Path] = []
    for i, (img, audio) in enumerate(slides, start=1):
        dur = _audio_duration(audio) + gap_seconds
        seg = work / f"seg_{i:03d}.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(img),
            "-i", str(audio),
            "-filter_complex",
            f"[0:v]{scale_pad}[v];[1:a]apad=pad_dur={gap_seconds}[a]",
            "-map", "[v]", "-map", "[a]",
            "-t", f"{dur:.3f}",
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            str(seg),
        ]
        _run(cmd)
        segments.append(seg)
        logger.info("세그먼트 %d/%d (%.1fs)", i, len(slides), dur)

    # concat demuxer (동일 코덱이므로 무손실 결합)
    list_file = work / "concat.txt"
    list_file.write_text(
        "".join(f"file '{s.resolve().as_posix()}'\n" for s in segments),
        encoding="utf-8")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
          "-c", "copy", str(out_path)])
    logger.info("MP4 완료 → %s", out_path)
    return out_path


def _slide_media_seconds(slide) -> float:
    """슬라이드 내 동영상(미디어) 최장 길이(초). 동시에 자동재생으로 설정 시도(best-effort)."""
    longest = 0.0
    try:
        shapes = slide.Shapes
    except Exception:
        return 0.0
    for shp in shapes:
        try:
            if int(shp.Type) != 16:  # msoMedia
                continue
        except Exception:
            continue
        try:
            ln = float(shp.MediaFormat.Length) / 1000.0  # ms → s
            longest = max(longest, ln)
        except Exception:
            pass
        # 내장 동영상을 슬라이드 진입 시 자동재생되도록 (가능한 경로 모두 시도)
        for setter in (
            lambda: setattr(shp.AnimationSettings.PlaySettings, "PlayOnEntry", -1),
            lambda: setattr(shp.AnimationSettings.PlaySettings, "PauseAnimation", 0),
        ):
            try:
                setter()
            except Exception:
                pass
    return longest


def encode_powerpoint(pptx_with_audio: Path, out_path: Path, *,
                      durations: list[float] | None = None,
                      gap_seconds: float = 0.7,
                      vert_resolution: int = 1080, fps: int = 30,
                      quality: int = 90,
                      account_for_media: bool = True) -> Path:
    """PowerPoint 네이티브 'CreateVideo'로 MP4 생성 (애니메이션/전환/내장 동영상 보존).
    durations가 주어지면 각 슬라이드 자동전환 시간을 그 값(+gap)으로 설정한다.
    account_for_media=True 이면 내장 동영상이 잘리지 않도록 자동전환 시간을
    max(나레이션, 슬라이드 내 최장 동영상)으로 잡고, 동영상을 자동재생으로 설정한다."""
    import pythoncom
    import win32com.client

    pptx_with_audio = Path(pptx_with_audio).resolve()
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pythoncom.CoInitialize()
    ppt = win32com.client.Dispatch("PowerPoint.Application")
    pres = None
    try:
        pres = ppt.Presentations.Open(str(pptx_with_audio), WithWindow=False)
        if durations:
            for slide, dur in zip(pres.Slides, durations):
                adv = float(dur) + gap_seconds
                if account_for_media:
                    media_len = _slide_media_seconds(slide)
                    if media_len > 0:
                        adv = max(adv, media_len + gap_seconds)
                t = slide.SlideShowTransition
                t.AdvanceOnTime = True
                t.AdvanceOnClick = False
                t.AdvanceTime = adv
        # CreateVideo(FileName, UseTimingsAndNarrations, DefaultSlideDuration,
        #             VertResolution, FramesPerSecond, Quality)
        pres.CreateVideo(str(out_path), True, 5, vert_resolution, fps, quality)
        # 비동기 → 완료까지 폴링 (Status: 1=진행, 2=대기, 3=완료, 4=실패)
        while True:
            status = pres.CreateVideoStatus
            if status in (3, 4):
                break
            time.sleep(2)
        if status == 4 or not out_path.exists():
            raise RuntimeError("PowerPoint CreateVideo 실패")
        logger.info("PowerPoint MP4 완료 → %s", out_path)
        return out_path
    finally:
        if pres is not None:
            pres.Close()
        ppt.Quit()
        pythoncom.CoUninitialize()
