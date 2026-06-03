"""PowerPoint COM 기반 나레이션 삽입 + 영상 내보내기.

python-pptx XML 조작 대신 PowerPoint가 직접 타임라인을 관리하므로,
애니메이션/전환이 이미 있는 슬라이드나 내장 동영상이 있는 덱에서도 안전하다.

흐름: 원본 열기 → 슬라이드별 나레이션 오디오 삽입(자동재생, 아이콘 숨김)
     → 자동전환 시간 = max(나레이션, 슬라이드 내 최장 동영상)+gap
     → 나레이션 PPTX 저장 → (옵션) CreateVideo 로 MP4.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_MSO_TRUE = -1
_MSO_MEDIA = 16          # msoMedia
_PP_MEDIA_MOVIE = 3      # ppMediaTypeMovie


def _max_movie_seconds(slide) -> float:
    """슬라이드 내 '동영상' 최장 길이(초). 동영상도 자동재생으로 설정(best-effort)."""
    longest = 0.0
    for shp in slide.Shapes:
        try:
            if int(shp.Type) != _MSO_MEDIA or int(shp.MediaType) != _PP_MEDIA_MOVIE:
                continue
        except Exception:
            continue
        try:
            longest = max(longest, float(shp.MediaFormat.Length) / 1000.0)
        except Exception:
            pass
        try:
            shp.AnimationSettings.PlaySettings.PlayOnEntry = _MSO_TRUE
        except Exception:
            pass
    return longest


def narrate_and_export(pptx_path: Path, audio_by_slide: dict[int, Path],
                       durations: list[float], out_pptx: Path,
                       out_mp4: Path | None = None, *, gap_seconds: float = 0.7,
                       vert_resolution: int = 1080, fps: int = 30,
                       quality: int = 90) -> dict:
    """COM으로 나레이션 삽입 + 타이밍 설정 + (옵션)영상화. 산출물 경로 dict 반환."""
    import pythoncom
    import win32com.client

    pptx_path = Path(pptx_path).resolve()
    out_pptx = Path(out_pptx).resolve()
    out_pptx.parent.mkdir(parents=True, exist_ok=True)
    results: dict = {}

    pythoncom.CoInitialize()
    ppt = win32com.client.Dispatch("PowerPoint.Application")
    pres = None
    try:
        pres = ppt.Presentations.Open(str(pptx_path), WithWindow=False)
        slides = pres.Slides
        for idx in range(1, slides.Count + 1):
            slide = slides.Item(idx)
            dur = durations[idx - 1] if idx - 1 < len(durations) else 0.0
            adv = float(dur) + gap_seconds

            audio = audio_by_slide.get(idx)
            if audio and Path(audio).exists():
                # 아이콘을 슬라이드 밖(왼쪽)에 두고 자동재생
                shp = slide.Shapes.AddMediaObject2(
                    str(Path(audio).resolve()), False, True, -50, 0)
                try:
                    shp.AnimationSettings.PlaySettings.PlayOnEntry = _MSO_TRUE
                    shp.AnimationSettings.PlaySettings.HideWhileNotPlaying = _MSO_TRUE
                except Exception as e:  # noqa: BLE001
                    logger.debug("오디오 자동재생 설정 실패(slide %d): %s", idx, e)

            # 내장 동영상이 잘리지 않도록 더 긴 쪽에 맞춤
            movie_len = _max_movie_seconds(slide)
            if movie_len > 0:
                adv = max(adv, movie_len + gap_seconds)

            t = slide.SlideShowTransition
            t.AdvanceOnTime = _MSO_TRUE
            t.AdvanceOnClick = 0
            t.AdvanceTime = adv

        pres.SaveAs(str(out_pptx))
        results["pptx_with_audio"] = str(out_pptx)
        logger.info("나레이션 PPTX 저장 → %s", out_pptx)

        if out_mp4 is not None:
            out_mp4 = Path(out_mp4).resolve()
            out_mp4.parent.mkdir(parents=True, exist_ok=True)
            pres.CreateVideo(str(out_mp4), True, 5, vert_resolution, fps, quality)
            while True:
                status = pres.CreateVideoStatus
                if status in (3, 4):
                    break
                time.sleep(3)
            if status == 4 or not out_mp4.exists():
                raise RuntimeError("PowerPoint CreateVideo 실패")
            results["mp4"] = str(out_mp4)
            logger.info("PowerPoint MP4 완료 → %s", out_mp4)
        return results
    finally:
        if pres is not None:
            pres.Close()
        ppt.Quit()
        pythoncom.CoUninitialize()
