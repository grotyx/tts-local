"""발표 대본(Markdown/Text)을 슬라이드별 나레이션으로 파싱.

지원 형식 (라인 시작):
    Slide 1. 본문...
    ## Slide 1
    본문...
    [Slide 1] 본문...

반환: OrderedDict{슬라이드번호(int): 나레이션(str)}
"""
from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path

# "Slide 12.", "## Slide 12", "[Slide 12]", "Slide 12:", "## SLIDE 12 — Title",
# 한국어 "## 슬라이드 12 — 제목" 등을 잡는다.
_SLIDE_RE = re.compile(r"^\s*#*\s*\[?\s*(?:slide|슬라이드)\s*0*(\d+)\s*[\]\.:]?\s*", re.IGNORECASE)
# 마크다운 수평선(--- *** ___) → 나레이션에서 제외
_HR_RE = re.compile(r"^\s*[-*_]{3,}\s*$")
# 타임스탬프 "(0:35 – 0:55)" → 발화 대상 아님
_TS_RE = re.compile(r"\(?\s*\d{1,2}:\d{2}\s*[–—-]\s*\d{1,2}:\d{2}\s*\)?")
# 슬라이드 제목 꼬리: 슬라이드 마커 뒤가 대시로 시작(예: "— Cover  (0:00 – 0:25)")
_DASHES = ("—", "–", "-")


def _is_title_tail(rest: str) -> bool:
    """슬라이드 번호 뒤 같은 줄에 붙은 내용이 '나레이션'이 아니라 '제목'인지 판단.
    제목은 대시로 시작하거나 타임스탬프를 포함한다(예: '— Cover  (0:00 – 0:25)')."""
    r = rest.strip()
    return r.startswith(_DASHES) or bool(_TS_RE.search(r))


def parse_script(path: Path) -> "OrderedDict[int, str]":
    """대본 파일 → {슬라이드번호: 나레이션}. 제목/타임스탬프/수평선은 제거."""
    text = Path(path).read_text(encoding="utf-8")
    slides: "OrderedDict[int, list[str]]" = OrderedDict()
    current: int | None = None

    for raw_line in text.splitlines():
        m = _SLIDE_RE.match(raw_line)
        if m:
            current = int(m.group(1))
            rest = raw_line[m.end():].strip()
            slides.setdefault(current, [])
            # 슬라이드 마커 뒤 같은 줄 내용은 '제목'이면 버리고, 나레이션이면 사용
            if rest and not _is_title_tail(rest):
                slides[current].append(rest)
        elif current is not None:
            line = raw_line.strip()
            if line and not _HR_RE.match(line):
                slides[current].append(line)

    out: "OrderedDict[int, str]" = OrderedDict()
    for n, parts in slides.items():
        text_joined = " ".join(parts).strip()
        text_joined = _TS_RE.sub("", text_joined)            # 남은 타임스탬프 제거
        text_joined = re.sub(r"\s{2,}", " ", text_joined).strip()
        out[n] = text_joined
    return out


def build_narrations(script: "OrderedDict[int, str]", groups: list[int] | None = None) -> list[str]:
    """스크립트 슬라이드들을 '덱 슬라이드' 단위로 묶어 나레이션 리스트를 만든다.

    groups: 각 덱 슬라이드가 소비할 스크립트 슬라이드 개수. 합은 len(script)와 같아야 함.
            None이면 1:1 (스크립트=덱).
    예) 스크립트 23개, 덱 22장이고 1번 덱에 S1+S2를 합치려면 groups=[2,1,1,...,1].
    """
    texts = list(script.values())
    if groups is None:
        return texts
    if sum(groups) != len(texts):
        raise ValueError(
            f"groups 합({sum(groups)}) != 스크립트 슬라이드 수({len(texts)})")
    out: list[str] = []
    i = 0
    for g in groups:
        out.append(" ".join(t for t in texts[i:i + g] if t).strip())
        i += g
    return out
