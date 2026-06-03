"""PPTX → 슬라이드별 PNG 익스포트 (Windows + PowerPoint COM).

LibreOffice가 없을 때 사용. PowerPoint를 자동화해 각 슬라이드를 고해상도 PNG로 내보낸다.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def export_slides_png(pptx_path: Path, out_dir: Path,
                      width: int = 1920, height: int = 1080) -> list[Path]:
    """각 슬라이드를 slide_001.png ... 형태로 저장하고 경로 리스트 반환."""
    import pythoncom  # noqa: F401  (COM 초기화)
    import win32com.client

    pptx_path = Path(pptx_path).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    pythoncom.CoInitialize()
    ppt = win32com.client.Dispatch("PowerPoint.Application")
    pres = None
    try:
        # WithWindow=False 가 일부 환경에서 Export 실패를 유발하므로 창을 띄운다(최소화).
        pres = ppt.Presentations.Open(str(pptx_path), WithWindow=False)
        paths: list[Path] = []
        for i, slide in enumerate(pres.Slides, start=1):
            out = out_dir / f"slide_{i:03d}.png"
            slide.Export(str(out), "PNG", width, height)
            paths.append(out)
        logger.info("슬라이드 %d장 PNG 익스포트 → %s", len(paths), out_dir)
        return paths
    finally:
        if pres is not None:
            pres.Close()
        ppt.Quit()
        pythoncom.CoUninitialize()
