# 학술 강의·발표 나레이션 영상 생성기
### Academic Lecture & Talk Narration Video Generator — powered by Local LLM (Qwen3-TTS) or Gemini TTS

발표·강의 대본(Markdown)을 **로컬 LLM(Qwen3-TTS) 또는 Gemini TTS**로 음성화하고, **PowerPoint에 오디오를 삽입**해 **나레이션이 입혀진 강의 영상(MP4)** 으로 만드는 재사용 가능한 CLI 도구. 학술 발표·강의 자료를 발표자 없이도 영상 강의로 제작합니다.

A reusable CLI that turns lecture/talk scripts (Markdown) into speech with a **local LLM (Qwen3-TTS) or Gemini TTS**, embeds the audio into the PowerPoint, and renders a **narrated lecture video (MP4)** — produce video lectures from academic slides without a live speaker.

- 🎙️ **엔진 플러그인** / pluggable engines: **Gemini** (cloud, 한↔영 코드스위칭), **Qwen3-TTS** (local GPU, 무료·보이스클로닝), **ElevenLabs**
- 🎬 **영상 2경로** / two video paths: **ffmpeg** (정적 슬라이드), **PowerPoint native** (애니메이션·내장 동영상 보존)
- 📝 슬라이드별 나레이션 검토·편집 워크플로우 / per-slide narration review & edit workflow
- 🌐 한국어·영어 / Korean & English

> [한국어](#한국어) · [English](#english)

---

# 한국어

## 무엇을 하나요?

```
대본(.md)  →  [엔진] 슬라이드별 음성(.wav)  →  PPTX에 오디오 삽입  →  영상(.mp4)
                                            └→  narrations.json / .md (검토·편집)
```

1. 대본을 슬라이드별로 파싱
2. 선택한 TTS 엔진으로 슬라이드마다 음성 생성
3. 각 음성을 PowerPoint 슬라이드에 삽입(자동재생)
4. 슬라이드 이미지/애니메이션 + 음성을 합쳐 MP4로 인코딩

## 설치

```bash
# (선택) 가상환경
python -m venv .venv && .venv\Scripts\activate     # Windows
# 의존성
pip install -r requirements.txt
# Qwen 로컬 엔진을 쓸 때만: GPU에 맞는 torch/torchaudio
#   예) NVIDIA Blackwell/RTX 50xx:
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
```

**필수 외부 요소**
- **ffmpeg** : PATH에 있어야 함 (영상/오디오 처리). https://ffmpeg.org
- **PowerPoint + pywin32** (Windows) : 슬라이드 이미지 추출 및 PowerPoint 네이티브 영상화에 필요. (ffmpeg 영상 경로도 슬라이드 PNG 추출에 PowerPoint COM을 사용)
- **API 키** : `gemini`/`elevenlabs` 엔진은 키 필요. 프로젝트 루트에 `.env` 생성:
  ```
  GEMINI_API_KEY=발급키
  # ELEVENLABS_API_KEY=...
  ```
  `.env`는 `.gitignore`에 포함되어 커밋되지 않습니다. `main.py` 실행 시 자동 로드됩니다.

## 엔진별 상세

### 1) `gemini` — Gemini TTS (클라우드, 한국어/혼합 발표 권장)

- 모델: `gemini-3.1-flash-tts-preview` (google-genai SDK, `generate_content_stream`)
- **장점**: 영어↔한국어 **코드스위칭이 자연스럽고 환각이 거의 없음**. 셋업 0(키만 있으면 됨). 빠름(~슬라이드당 수 초).
- 화자(voice): `Charon` 등 Gemini 프리보이스. `config.json`의 `voice` 또는 `--voice`로 지정.
- **instruct가 들어가는 방식이 특별합니다.** 단순 파라미터가 아니라 아래 구조의 프롬프트로 합성 지시를 전달합니다:
  ```
  Read the following transcript based on the audio profile and director's note.
  # Audio Profile
  {audio_profile}
  # Director's note
  {directors_note}
  ## Sample Context:
  {instruct}     ← 예: "...switching seamlessly between English and Korean."
  ## Transcript:
  {슬라이드 나레이션}
  ```
  → `config.json`의 `audio_profile`, `directors_note`, `instruct`로 톤·속도감·억양·언어전환을 제어.
- 출력: 24kHz mono PCM(L16) → WAV.
- 비용: API 사용량 과금.

### 2) `qwen_local` — Qwen3-TTS (로컬 GPU, 무료·무제한, 보이스 클로닝)

- 모델: `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`(프리셋) / `...-Base`(클로닝)
- **장점**: 무료·무제한·오프라인, 데이터가 외부로 안 나감. **보이스 클로닝** 지원.
- 프리셋 화자: 영어 `Ryan`, `Aiden` / 한국어 `Sohee` / 일본어 `Ono_Anna` / 중국어 여러 명. `--language`로 언어 지정 필요.
- 생성 파라미터: `seed`(재현성), `temperature`, `top_p` (config). seed 고정 시 동일 입력=동일 출력.
- **주의(환각)**: 짧은 텍스트나 영어약어+숫자 섞인 긴 한국어에서 비음성(웃음 등)을 채워 길이가 폭증할 수 있음. 도구가 자동 대응:
  1. 길이가 기대치 대비 과도하면 **seed를 바꿔 재시도**(최대 4회)
  2. 그래도 안 되면 **문장 단위로 쪼개 합성 후 이어붙임**(`_synthesize_chunked`)
- **instruct로 속도 제어는 잘 안 됨** → 속도는 `--speed`(아래) 사용.
- 보이스 클로닝:
  ```bash
  --clone --ref-audio voices/me.wav --ref-text "참조 음성에서 말한 텍스트" --clone-mode full
  ```
  - `full`: 참조 음성 + 그 텍스트(ref_text) 사용. 품질↑.
  - `xvec`: 음색(speaker embedding)만 사용, ref_text 불필요.
  - 참조는 3~10초면 충분(길수록 안정). **교차언어 클로닝(한국어 음성→영어 발화)은 억양 전이 한계**가 있으니, 같은 언어 클로닝을 권장.
- 요구사항: NVIDIA GPU(1.7B는 ~6–8GB VRAM). flash-attn 없이 `attn_implementation="sdpa"`로 동작.

### 3) `elevenlabs` — ElevenLabs (클라우드, 유료, 고품질·클로닝)

- 저장된 `voice_id`로 합성. `add_voice`로 참조 음성에서 Instant Voice Clone 생성 가능.
- `ELEVENLABS_API_KEY` 필요. `output_format=pcm_24000` → WAV.

## 대본 형식

라인 시작에 슬라이드 번호를 둡니다. 다음 모두 인식:
```
Slide 1. 첫 슬라이드 나레이션...
## Slide 2 — Title (영어 제목/타임스탬프는 자동 제거)
## 슬라이드 3 — 제목        (한국어)
[Slide 4] ...
```
- 슬라이드 마커 뒤의 `— 제목`, `(0:35 – 0:55)` 타임스탬프, `---` 구분선은 **나레이션에서 자동 제외**됩니다.
- 슬라이드 사이 빈 줄/본문은 해당 슬라이드 나레이션으로 합쳐집니다.

## 워크플로우 (권장: 대본 검토 후 생성)

```bash
# 1) 대본 → 편집용 narrations.json/.md 만 생성
python main.py --script input/talk.md --pptx input/deck.pptx --out output/talk --narrations-only

# 2) output/talk/narrations.json (또는 narrations.md)를 열어 슬라이드별 텍스트 검토·수정
#    - 발음 교정 예: docx→"Word 파일", TLIF→"틸립", PLIF→"플립" 등
#    - narrations.md 는 "## 슬라이드 N — 제목" 형식이라 그대로 다시 파싱 가능

# 3) 편집본 그대로 음성+영상 생성
#    한국어(권장: Gemini Charon, 원본속도):
python main.py --script input/talk.md --pptx input/deck.pptx --out output/talk \
  --engine gemini --use-edited --regenerate --video powerpoint
#    영어(로컬 Qwen Ryan, 1.15배):
python main.py --script input/talk.md --pptx input/deck.pptx --out output/talk \
  --engine qwen_local --voice Ryan --speed 1.15 --use-edited --regenerate --video ffmpeg
```

### 한 줄 실행 (편집 없이)
```bash
python main.py --script input/talk.md --pptx input/deck.pptx --out output/talk --engine gemini
```

### 한 슬라이드만 다시 만들기 (톤 교정 등)
```bash
rm output/talk/audio/slide_003.wav output/talk/audio/raw/slide_003.wav   # 그 슬라이드만 삭제
python main.py --script input/talk.md --pptx input/deck.pptx --out output/talk \
  --engine gemini --use-edited --video powerpoint                         # 나머지 음성 유지, 영상만 재인코딩
```

## 영상 방식 (`--video`)

| 값 | 설명 | 언제 |
|----|------|------|
| `ffmpeg` | 슬라이드를 PNG로 굽고 슬라이드당 길이=나레이션 길이로 합성. 싱크 정확·안정. | 정적 슬라이드 |
| `powerpoint` | 오디오를 PPTX에 넣고 PowerPoint `CreateVideo`로 내보냄. **애니메이션·전환·내장 동영상 보존**. 슬라이드 시간=max(나레이션, 내장 동영상 길이). | 애니메이션/동영상 있는 덱 |
| `none` | 영상 없이 음성 + 오디오 삽입 PPTX만. | 오디오만 필요 시 |

## 주요 옵션

| 옵션 | 설명 |
|------|------|
| `--script PATH` | 대본(.md/.txt) (필수) |
| `--pptx PATH` | 발표 파일(.pptx) (필수) |
| `--out DIR` | 출력 폴더 (기본 `output/<deck>`) |
| `--engine gemini\|qwen_local\|elevenlabs` | 엔진 (기본 config.json) |
| `--voice NAME` | 화자 (gemini=Charon… / qwen=Ryan,Aiden,Sohee) |
| `--language Korean\|English` | 언어 (qwen 권장 명시; gemini 자동) |
| `--instruct "..."` | 톤/스타일 지시 (config 값 덮어씀) |
| `--speed 1.15` | 배속(음정 유지, atempo). 원본은 `audio/raw/` 보존. 생략=원본속도 |
| `--video ffmpeg\|powerpoint\|none` | 영상 방식 |
| `--groups "2,1,1,..."` | 대본↔덱 슬라이드 수 불일치 매핑(덱 슬라이드별 대본 묶음 수, 합=대본수) |
| `--narrations-only` | narrations.json만 생성 후 종료 |
| `--narrations PATH` | 지정한 narrations.json 사용 |
| `--use-edited` | `out/narrations.json`(편집본) 사용, 대본 재파싱 안 함 |
| `--regenerate` | 기존 음성 무시하고 재생성 |
| `--clone --ref-audio ... --ref-text ... --clone-mode full\|xvec` | 보이스 클로닝(qwen) |

## 출력물 (`output/<deck>/`)

```
narrations.json            슬라이드별 나레이션 텍스트
audio/slide_001.wav ...    슬라이드별 음성 (최종, 배속 적용본)
audio/raw/slide_001.wav    배속 전 원본 (--speed 사용 시)
<deck>_with_audio.pptx     오디오 삽입된 PPTX
slides_png/slide_001.png   (ffmpeg) 슬라이드 이미지
<deck>.mp4                 최종 영상
```

## 프로젝트 구조

```
tts_local/
  engines/   base.py(인터페이스) + gemini.py / qwen_local.py / elevenlabs.py
  script_parser.py   대본 파싱(영/한 슬라이드 마커, 제목·타임스탬프 제거)
  pptx_audio.py      python-pptx 오디오 삽입 + 자동재생
  pptx_com.py        PowerPoint COM 삽입 + CreateVideo (애니메이션/동영상 안전)
  slide_export.py    PPTX → PNG (PowerPoint COM)
  video_encoder.py   ffmpeg 합성 / 속도(atempo)
  pipeline.py        오케스트레이터 + 환각 자동대응(seed 재시도·문장분할)
main.py    CLI
config.json  엔진·화자·instruct·영상 기본 설정
```

## 새 엔진 추가

`engines/base.py`의 `TTSEngine`을 상속해 `synthesize()`를 구현하고, `engines/__init__.py`의 `make_engine()`에 한 줄 등록.

## 알려진 팁

- **발음 교정**: TTS가 약어/영문을 잘못 읽으면 narrations.json에서 한글 표기로 바꾸세요 (예: `docx`→`Word 파일`, `TLIF`→`틸립`).
- **속도**: Gemini/Qwen 모두 instruct의 "빠르게"는 약하게 듣습니다. 정확한 배속은 `--speed`(atempo 후처리).
- **한국어 환각**: 로컬 Qwen(Sohee)은 혼합 텍스트에서 환각이 잦음 → Gemini 권장, 혹은 자동 문장분할 폴백에 의존.

---

# English

## What it does

```
script(.md)  →  [engine] per-slide speech(.wav)  →  embed into PPTX  →  video(.mp4)
                                                  └→  narrations.json / .md (review & edit)
```

1. Parse the script into per-slide narration
2. Synthesize speech per slide with the chosen TTS engine
3. Insert each audio into the matching PowerPoint slide (autoplay)
4. Render slides (images/animations) + audio into an MP4

## Install

```bash
python -m venv .venv && .venv\Scripts\activate     # Windows (optional)
pip install -r requirements.txt
# Only for the Qwen local engine: a torch/torchaudio build for your GPU, e.g. Blackwell/RTX 50xx:
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
```

**External requirements**
- **ffmpeg** on PATH (audio/video).
- **PowerPoint + pywin32** (Windows) for slide-image export and native video export (the ffmpeg path also uses PowerPoint COM to export slide PNGs).
- **API keys** for `gemini`/`elevenlabs`. Create `.env` in the project root:
  ```
  GEMINI_API_KEY=your_key
  # ELEVENLABS_API_KEY=...
  ```
  `.env` is gitignored and auto-loaded by `main.py`.

## Engines in detail

### 1) `gemini` — Gemini TTS (cloud; recommended for Korean / mixed-language)
- Model `gemini-3.1-flash-tts-preview` via google-genai SDK streaming.
- **Pros**: natural English↔Korean code-switching, almost no hallucination, zero setup, fast.
- Voice: Gemini prebuilt voices (e.g. `Charon`) via `voice`/`--voice`.
- **Instruct is delivered as a structured prompt** (Audio Profile / Director's note / Sample Context / Transcript) — set `audio_profile`, `directors_note`, `instruct` in `config.json` to control tone, pace, accent, and language switching.
- Output: 24 kHz mono PCM (L16) → WAV. Billed per API usage.

### 2) `qwen_local` — Qwen3-TTS (local GPU; free, voice cloning)
- Models `...-CustomVoice` (presets) / `...-Base` (cloning).
- **Pros**: free, offline, data never leaves the machine; supports **voice cloning**.
- Preset voices: English `Ryan`, `Aiden`; Korean `Sohee`; etc. Set `--language`.
- Params: `seed` (reproducible), `temperature`, `top_p`.
- **Hallucination note**: on short text or long Korean mixed with English acronyms/numbers, it may pad with non-speech (laughter) and balloon in length. The tool handles this automatically: (1) retry with a different **seed** (up to 4×), then (2) **sentence-split synthesis** and concatenate.
- Instruct does **not** reliably control speed → use `--speed`.
- Voice cloning: `--clone --ref-audio voices/me.wav --ref-text "..." --clone-mode full|xvec` (3–10 s reference; same-language cloning recommended — cross-lingual transfer is limited).
- Requires NVIDIA GPU (~6–8 GB VRAM for 1.7B); runs with `attn_implementation="sdpa"` (no flash-attn needed).

### 3) `elevenlabs` — ElevenLabs (cloud, paid)
- Synthesize with a stored `voice_id`; `add_voice` for Instant Voice Clone. Needs `ELEVENLABS_API_KEY`.

## Script format
Start a line with a slide marker (all recognized): `Slide 1.`, `## Slide 2 — Title`, `## 슬라이드 3 — 제목`, `[Slide 4]`. Title tails (`— Title`), timestamps `(0:35 – 0:55)`, and `---` rules are auto-stripped from narration.

## Workflow (recommended: review then generate)
```bash
# 1) Script → editable narrations.json/.md only
python main.py --script input/talk.md --pptx input/deck.pptx --out output/talk --narrations-only
# 2) Edit output/talk/narrations.json (or .md) per slide (fix pronunciations, wording)
# 3) Generate from the edited narration
python main.py --script input/talk.md --pptx input/deck.pptx --out output/talk \
  --engine gemini --use-edited --regenerate --video powerpoint
```

### One-shot
```bash
python main.py --script input/talk.md --pptx input/deck.pptx --out output/talk --engine gemini
```

### Regenerate a single slide
```bash
rm output/talk/audio/slide_003.wav output/talk/audio/raw/slide_003.wav
python main.py --script input/talk.md --pptx input/deck.pptx --out output/talk \
  --engine gemini --use-edited --video powerpoint   # keeps other audio, re-encodes video
```

## Video methods (`--video`)
- `ffmpeg` — slides as PNG, each shown for its narration length. Exact sync, robust. Static slides.
- `powerpoint` — embed audio + PowerPoint `CreateVideo`. **Preserves animations, transitions, embedded videos**; slide time = max(narration, embedded video). For animated/video decks.
- `none` — audio + audio-embedded PPTX only.

## Key options
See the Korean table above — identical flags: `--script --pptx --out --engine --voice --language --instruct --speed --video --groups --narrations-only --narrations --use-edited --regenerate --clone/--ref-audio/--ref-text/--clone-mode`.

## Output (`output/<deck>/`)
`narrations.json`, `audio/slide_NNN.wav` (+ `audio/raw/` if `--speed`), `<deck>_with_audio.pptx`, `slides_png/` (ffmpeg), `<deck>.mp4`.

## Add an engine
Subclass `TTSEngine` in `engines/base.py`, implement `synthesize()`, register in `engines/__init__.py: make_engine()`.

## Tips
- **Pronunciation**: if the TTS mis-reads acronyms, rewrite them phonetically in `narrations.json` (e.g., `docx`→`Word file`).
- **Speed**: "speak faster" in instruct is weak; use `--speed` (atempo) for exact tempo.
- **Korean hallucination**: local Qwen (Sohee) hallucinates on mixed text → prefer Gemini, or rely on the auto sentence-split fallback.

## License
MIT (see project owner).
