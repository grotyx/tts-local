"""Qwen3-TTS 로컬 엔진.

- CustomVoice 모델: 프리셋 화자(영어 Ryan/Aiden, 한국어 Sohee 등) + instruct로 톤/감정 제어
- Base 모델: 3~10초 참조 음성으로 보이스 클로닝 (synthesize_clone)

모델은 최초 사용 시 lazy-load (다운로드 ~3.4GB, 이후 캐시). flash-attn이 없으면
attn_implementation="sdpa"로 자동 동작한다(검증 완료, RTX 5090/sm_120).
"""
from __future__ import annotations

from pathlib import Path

from .base import TTSEngine

# 참고: CustomVoice 프리셋 화자
PRESET_VOICES = {
    "Chinese": ["Vivian", "Serena", "Uncle_Fu", "Dylan", "Eric"],
    "English": ["Ryan", "Aiden"],
    "Japanese": ["Ono_Anna"],
    "Korean": ["Sohee"],
}


class QwenLocalEngine(TTSEngine):
    name = "qwen_local"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.model_id = cfg.get("model_id", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
        self.clone_model_id = cfg.get("clone_model_id", "Qwen/Qwen3-TTS-12Hz-1.7B-Base")
        self.device = cfg.get("device", "cuda:0")
        self.attn = cfg.get("attn_implementation", "sdpa")
        self.default_voice = cfg.get("voice", "Ryan")
        self.default_lang = cfg.get("language", "English")
        self.default_instruct = cfg.get("instruct", "")
        # 일관성/안정성용 생성 파라미터 (HF transformers generate kwargs)
        self.seed = cfg.get("seed")
        self.gen_kwargs = {k: cfg[k] for k in
                           ("temperature", "top_p", "top_k",
                            "repetition_penalty", "max_new_tokens") if k in cfg}
        self._model = None       # CustomVoice
        self._clone = None        # Base (클로닝)

    def _seed(self):
        if self.seed is not None:
            from transformers import set_seed
            set_seed(int(self.seed))

    # --- 내부: lazy load ---
    def _load_custom(self):
        if self._model is None:
            import torch
            from qwen_tts import Qwen3TTSModel
            self._model = Qwen3TTSModel.from_pretrained(
                self.model_id, device_map=self.device,
                dtype=torch.bfloat16, attn_implementation=self.attn)
        return self._model

    def _load_clone(self):
        if self._clone is None:
            import torch
            from qwen_tts import Qwen3TTSModel
            self._clone = Qwen3TTSModel.from_pretrained(
                self.clone_model_id, device_map=self.device,
                dtype=torch.bfloat16, attn_implementation=self.attn)
        return self._clone

    # --- API ---
    def synthesize(self, text, out_path, *, voice=None, instruct=None, language=None):
        import soundfile as sf
        model = self._load_custom()
        self._seed()
        wavs, sr = model.generate_custom_voice(
            text=text,
            language=language or self.default_lang,
            speaker=voice or self.default_voice,
            instruct=self.default_instruct if instruct is None else instruct,
            **self.gen_kwargs,
        )
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out_path), wavs[0], sr)
        return out_path

    def synthesize_clone(self, text, out_path, *, ref_audio, ref_text=None,
                         language=None, x_vector_only=False):
        import soundfile as sf
        model = self._load_clone()
        self._seed()
        kwargs = dict(self.gen_kwargs)
        if x_vector_only:
            kwargs["x_vector_only_mode"] = True
        elif ref_text:
            kwargs["ref_text"] = ref_text
        wavs, sr = model.generate_voice_clone(
            text=text,
            language=language or self.default_lang,
            ref_audio=str(ref_audio),
            **kwargs,
        )
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out_path), wavs[0], sr)
        return out_path

    def close(self):
        self._model = None
        self._clone = None
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            pass
