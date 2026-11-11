"""로컬 GPU(SDXL, diffusers)로 장면별 후보 이미지를 여러 장 생성한다.
파이프라인은 한 번만 로드하고, 끝나면 VRAM 을 반납한다. 프롬프트는 styles.build() 가 만든 것을 받는다."""
from __future__ import annotations

import gc
import random

from PIL import Image

from .config import flag, get

WIDTH, HEIGHT = 896, 1152  # SDXL 학습 해상도 버킷 (세로 4:5 근처)


def generate_candidates(
    items: list[dict], n: int = 3, seed: int | None = None, steps: int = 30
) -> tuple[list[list[Image.Image]], int]:
    """items: [{'prompt','negative','scene'}...]  ->  장면별 n장의 후보 이미지 리스트."""
    import torch
    from diffusers import StableDiffusionXLPipeline

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU 를 찾지 못했습니다. `python main.py check` 로 확인하세요.")

    model = get("IMAGE_MODEL_ID", "stabilityai/stable-diffusion-xl-base-1.0")
    seed = seed if seed is not None else random.randint(0, 2**31 - 1)
    pipe = None
    try:
        extra = {}
        try:  # SDXL 기본 VAE 의 fp16 불안정(검은/탁한 이미지) 완화
            from diffusers import AutoencoderKL

            extra["vae"] = AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix", torch_dtype=torch.float16)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] fp16-fix VAE 를 불러오지 못해 기본 VAE 사용: {e}")

        if model.lower().endswith((".safetensors", ".ckpt")):
            pipe = StableDiffusionXLPipeline.from_single_file(model, torch_dtype=torch.float16, **extra)
        else:
            try:
                pipe = StableDiffusionXLPipeline.from_pretrained(
                    model, torch_dtype=torch.float16, variant="fp16", use_safetensors=True, **extra)
            except Exception:  # fp16 variant 가 없는 체크포인트
                pipe = StableDiffusionXLPipeline.from_pretrained(
                    model, torch_dtype=torch.float16, use_safetensors=True, **extra)

        try:  # 색이 탁해지는 문제를 줄이는 DPM++ 2M Karras
            from diffusers import DPMSolverMultistepScheduler

            pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, use_karras_sigmas=True)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 스케줄러 교체 실패(기본 사용): {e}")

        lora = get("STYLE_LORA")
        if lora:
            pipe.load_lora_weights(lora)
        if flag("IMAGE_CPU_OFFLOAD"):
            pipe.enable_model_cpu_offload()
        else:
            pipe.to("cuda")

        out: list[list[Image.Image]] = []
        for i, it in enumerate(items):
            print(f"  - 장면 {i + 1}/{len(items)} 후보 {n}장 생성: {it['scene']}")
            cands = []
            for k in range(n):
                gen = torch.Generator("cuda").manual_seed(seed + i * 101 + k)
                cands.append(
                    pipe(
                        prompt=it["prompt"], negative_prompt=it["negative"], width=WIDTH, height=HEIGHT,
                        num_inference_steps=steps, guidance_scale=6.0, generator=gen,
                    ).images[0]
                )
            out.append(cands)
        return out, seed
    finally:
        del pipe
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
