#!/usr/bin/env python3
"""tts-local — 발표 대본 → TTS 음성 → PPTX 삽입 + MP4 인코딩.

사용 예:
  # config.json 기본 엔진(qwen_local)으로 전체 파이프라인
  python main.py --script input/script.md --pptx input/deck.pptx --out output/run1

  # 엔진/보이스 즉석 지정
  python main.py --script s.md --pptx d.pptx --engine gemini --voice Orus

  # 스크립트 23개를 덱 22장에 매핑 (1번 덱 = 스크립트 1+2 병합)
  python main.py --script s.md --pptx d.pptx --groups 2,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1

  # 오디오만 (영상 생략)
  python main.py --script s.md --pptx d.pptx --video none

  # 보이스 클로닝 (Qwen Base / ElevenLabs)
  python main.py --script s.md --pptx d.pptx --clone --ref-audio voices/me.wav --ref-text "..."
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Windows cp949 콘솔에서 em-dash/비ASCII 출력 시 크래시 방지
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 패키지 임포트 경로 보장
sys.path.insert(0, str(Path(__file__).parent))

# .env 로드 (API 키 등) — 이미 설정된 환경변수는 덮어쓰지 않음
import os as _os  # noqa: E402
_envf = Path(__file__).parent / ".env"
if _envf.exists():
    for _line in _envf.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            _os.environ.setdefault(_k.strip(), _v.strip())

from tts_local.pipeline import PipelineConfig, run  # noqa: E402

ROOT = Path(__file__).parent


def parse_groups(s: str | None) -> list[int] | None:
    if not s:
        return None
    return [int(x) for x in s.replace(" ", "").split(",") if x]


def main() -> int:
    ap = argparse.ArgumentParser(description="발표 대본 → TTS → PPTX/MP4")
    ap.add_argument("--script", required=True, help="대본 파일(.md/.txt)")
    ap.add_argument("--pptx", required=True, help="발표 파일(.pptx)")
    ap.add_argument("--out", default=None, help="출력 폴더 (기본 output/<deck>)")
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--engine", default=None, help="qwen_local|gemini|elevenlabs")
    ap.add_argument("--voice", default=None, help="화자/voice_id 덮어쓰기")
    ap.add_argument("--instruct", default=None, help="톤/감정 지시(엔진에 따라)")
    ap.add_argument("--language", default=None)
    ap.add_argument("--groups", default=None, help="덱 슬라이드별 스크립트 묶음 개수(콤마)")
    ap.add_argument("--narrations-only", action="store_true",
                    help="대본→narrations.json만 생성하고 종료(편집용)")
    ap.add_argument("--narrations", default=None,
                    help="편집한 narrations.json 경로(대본 재파싱 대신 이걸 사용)")
    ap.add_argument("--use-edited", action="store_true",
                    help="출력폴더의 기존 narrations.json을 사용(직접 편집한 경우)")
    ap.add_argument("--speed", type=float, default=None,
                    help="음성 배속(음정 유지). 예: 1.15 = 15%% 빠르게")
    ap.add_argument("--video", default=None, choices=["ffmpeg", "powerpoint", "none"])
    ap.add_argument("--no-embed", action="store_true", help="PPTX 오디오 삽입 생략")
    ap.add_argument("--regenerate", action="store_true", help="기존 음성 무시하고 재생성")
    # 클로닝
    ap.add_argument("--clone", action="store_true")
    ap.add_argument("--ref-audio", default=None)
    ap.add_argument("--ref-text", default="")
    ap.add_argument("--ref-text-file", default=None, help="ref_text를 파일에서 읽기(UTF-8)")
    ap.add_argument("--clone-mode", default="full", choices=["full", "xvec"],
                    help="full=음색+ref_text, xvec=음색만")
    ap.add_argument("--log", default="INFO")
    args = ap.parse_args()

    logging.basicConfig(level=getattr(logging, args.log.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    cfg = PipelineConfig.from_json(Path(args.config))
    # CLI 덮어쓰기
    if args.engine:
        import json
        full = json.loads(Path(args.config).read_text(encoding="utf-8"))
        cfg.engine = args.engine
        cfg.engine_cfg = full.get("engines", {}).get(args.engine, {})
        cfg.voice = cfg.engine_cfg.get("voice") or cfg.engine_cfg.get("voice_id")
        cfg.instruct = cfg.engine_cfg.get("instruct")
        cfg.language = cfg.engine_cfg.get("language")
    if args.voice:
        cfg.voice = args.voice
    if args.instruct is not None:
        cfg.instruct = args.instruct
    if args.language:
        cfg.language = args.language
    if args.speed is not None:
        cfg.speed = args.speed
    if args.video:
        cfg.video_method = args.video
    if args.no_embed:
        cfg.embed_audio = False
    if args.clone:
        cfg.clone = True
        cfg.ref_audio = args.ref_audio
        cfg.clone_mode = args.clone_mode
        if args.ref_text_file:
            cfg.ref_text = Path(args.ref_text_file).read_text(encoding="utf-8").strip()
        else:
            cfg.ref_text = args.ref_text

    out_dir = Path(args.out) if args.out else ROOT / "output" / Path(args.pptx).stem
    out_dir.mkdir(parents=True, exist_ok=True)

    # --narrations-only: 편집용 narrations.json만 생성하고 종료
    if args.narrations_only:
        from tts_local.script_parser import parse_script, build_narrations
        import json
        s = parse_script(Path(args.script))
        narr = build_narrations(s, parse_groups(args.groups))
        p = out_dir / "narrations.json"
        p.write_text(json.dumps({i + 1: t for i, t in enumerate(narr)},
                                ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[tts-local] narrations.json 생성({len(narr)}개) → {p}")
        print("편집 후 --narrations 또는 --use-edited 로 음성/영상 생성하세요.")
        return 0

    # 편집한 narrations.json 사용 (대본 재파싱 안 함)
    narrations_override = None
    narr_path = args.narrations or (str(out_dir / "narrations.json") if args.use_edited else None)
    if narr_path:
        import json
        data = json.loads(Path(narr_path).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            narrations_override = [data[k] for k in sorted(data, key=lambda x: int(x))]
        else:
            narrations_override = list(data)
        print(f"[tts-local] 편집 narration 사용: {narr_path} ({len(narrations_override)}개)")

    print(f"[tts-local] engine={cfg.engine} voice={cfg.voice} video={cfg.video_method}")
    print(f"[tts-local] out={out_dir}")
    results = run(Path(args.script), Path(args.pptx), out_dir, cfg,
                  groups=parse_groups(args.groups), skip_existing=not args.regenerate,
                  narrations_override=narrations_override)
    print("\n[tts-local] 완료:")
    for k, v in results.items():
        print(f"  - {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
