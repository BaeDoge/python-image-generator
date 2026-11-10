"""로컬 GPU(SDXL, diffusers)로 만화 컷 배경(글자 없음, 얼굴 비중 낮음)을 여러 장 생성한다.
파이프라인은 한 번만 로드하고 장면 수만큼 생성한 뒤 VRAM 을 반납한다."""
from __future__ import annotations

import gc
import random

from PIL import Image

from .config import flag, get

NEGATIVE = (
    "text, letters, words, numbers, watermark, logo, signature, brand name, realistic, photo, 3d render, "
    "face close-up, deformed, extra limbs, extra fingers, blurry, low quality, cropped, cluttered, "
    "celebrity, famous person"
)
WIDTH, HEIGHT = 896, 1152  # SDXL 학습 해상도 버킷 (세로 4:5 근처)
DEFAULT_STYLE = (
    "flat vector illustration, soft pastel color palette, rounded simple shapes, minimal, cozy mood, "
    "clean uncluttered composition, no visible faces, large calm empty space at the top"
)


def build_prompt(scene: str) -> str:
    return f"{scene}, {get('IMAGE_STYLE', DEFAULT_STYLE)}"


def generate_scenes(scenes: list[str], seed: int | None = None, steps: int = 30) -> tuple[list[Image.Image], int]:
    import torch
    from diffusers import StableDiffusionXLPipeline

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU 를 찾지 못했습니다. `python main.py check` 로 확인하세요.")

    model = get("IMAGE_MODEL_ID", "stabilityai/stable-diffusion-xl-base-1.0")
    seed = seed if seed is not None else random.randint(0, 2**31 - 1)
    pipe = None
    try:
        extra = {}
        try:  # SDXL 기본 VAE 의 fp16 불안정(검은/탁한 이미지) 완화용
            from diffusers import AutoencoderKL

            extra["vae"] = AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix", torch_dtype=torch.float16)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] fp16-fix VAE 를 불러오지 못해 기본 VAE 사용: {e}")

        if model.lower().endswith((".safetensors", ".ckpt")):
            pipe = StableDiffusionXLPipeline.from_single_file(model, torch_dtype=torch.float16, **extra)
        else:
            try:
                pipe = StableDiffusionXLPipeline.from_pretrained(
                    model, torch_dtype=torch.float16, variant="fp16", use_safetensors=True, **extra
                )
            except Exception:  # fp16 variant 가 없는 체크포인트
                pipe = StableDiffusionXLPipeline.from_pretrained(
                    model, torch_dtype=torch.float16, use_safetensors=True, **extra
                )

        lora = get("STYLE_LORA")
        if lora:
            pipe.load_lora_weights(lora)

        if flag("IMAGE_CPU_OFFLOAD"):
            pipe.enable_model_cpu_offload()
        else:
            pipe.to("cuda")

        images = []
        for i, scene in enumerate(scenes):
            print(f"  - 장면 {i + 1}/{len(scenes)} 생성 중: {scene}")
            gen = torch.Generator("cuda").manual_seed(seed + i)
            images.append(
                pipe(
                    prompt=build_prompt(scene),
                    negative_prompt=NEGATIVE,
                    width=WIDTH,
                    height=HEIGHT,
                    num_inference_steps=steps,
                    guidance_scale=6.5,
                    generator=gen,
                ).images[0]
            )
        return images, seed
    finally:
        del pipe
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
