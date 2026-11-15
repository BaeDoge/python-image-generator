# AI Illustration Studio

An experimental local AI image-generation project exploring character-focused illustrations and short multi-panel stories.

The project combines structured scene planning, reusable visual-style presets, local Stable Diffusion XL generation, candidate review, and panel composition. It is intended as a practical environment for experimenting with the full workflow around generative images rather than a single prompt-to-image script.

## Project Workflow

```text
Topic and scene context
        |
        v
LLM-assisted scene planning
  - story and panel descriptions
  - visual motifs
  - style selection
        |
        v
Style prompt builder
        |
        v
Local SDXL image generation
  - multiple candidates per scene
  - reproducible seeds
        |
        v
Candidate review
  - basic image quality checks
  - CLIP similarity ranking
  - optional VLM review
        |
        v
Pillow-based panel composition
        |
        v
Generated images and verification report
```

## Features

- **Scene planning:** Uses an LLM to organise scene descriptions and a short visual sequence.
- **Style presets:** Includes flat pastel, paper cut, isometric room, soft watercolor, retro pop, and clay 3D directions.
- **Local image generation:** Runs a Diffusers Stable Diffusion XL pipeline on a CUDA-capable GPU.
- **Candidate generation:** Creates multiple candidates for each scene and records seeds for repeatable experiments.
- **Image review:** Combines basic image-quality checks and CLIP ranking, with optional VLM-based semantic review.
- **Retry workflow:** Simplifies scenes and regenerates candidates when the configured checks are not met.
- **Panel composition:** Uses Pillow to arrange selected images and text into a multi-panel output.
- **Verification report:** Saves candidate review results and unresolved warnings to `verify.json`.

## Technology

| Area | Technology |
| --- | --- |
| Language | Python 3.11 |
| Environment | uv |
| Model runtime | PyTorch, Diffusers |
| Image model | Stable Diffusion XL |
| Image processing | Pillow |
| Candidate ranking | CLIP |
| Optional semantic review | OpenAI-compatible VLM endpoint |
| Hardware | NVIDIA GPU with CUDA |

## Requirements

- Python 3.11 (the project currently targets Python 3.11 and 3.12)
- [uv](https://docs.astral.sh/uv/)
- NVIDIA GPU and a compatible CUDA-enabled PyTorch environment for image generation
- A running OpenAI-compatible LLM endpoint for scene planning
- Sufficient disk space for model weights and generated images

The default image model is `stabilityai/stable-diffusion-xl-base-1.0`. The model can be changed through `IMAGE_MODEL_ID`. Model downloads and inference requirements depend on the selected checkpoint.

## Setup

Clone the repository and install its dependencies:

    git clone https://github.com/BaeDoge/python-image-generator.git
    cd python-image-generator
    uv sync

Create a local environment file:

    copy .env.example .env

Configure the LLM endpoint and, when needed, the image model:

| Variable | Purpose |
| --- | --- |
| `LLM_BASE_URL` | OpenAI-compatible LLM endpoint |
| `LLM_API_KEY` | API key for the LLM endpoint |
| `LLM_MODEL` | Model name exposed by the endpoint |
| `IMAGE_MODEL_ID` | SDXL checkpoint or local model path |
| `STYLE_LORA` | Optional style LoRA path |
| `IMAGE_CPU_OFFLOAD` | Enable CPU offload when GPU memory is limited |
| `VLM_BASE_URL` | Optional image-capable VLM endpoint |
| `VLM_MODEL` | Optional VLM model name |
| `FONT_PATH` | Optional font path for text composition |

Keep populated environment files and API credentials local. Do not commit `.env`.

## Run

Check the local environment:

    uv run python main.py check

Run the planning and text-validation demo without loading the image model:

    uv run python main.py post --demo --no-image

Run the full local image-generation demo:

    uv run python main.py post --demo

The demo uses sample input and saves generated files under `out/`. It does not require a live publishing step. Actual image generation requires the configured model weights and a working CUDA environment.

## Output

A generated run is saved in a timestamped directory under `out/`. Depending on the selected workflow, the directory contains:

- Rendered panel images
- `post.json` with the scene plan and generation inputs
- `verify.json` with image checks, candidate scores, and warnings

The verification report is intended to support human review; it is not a guarantee that every image is semantically correct.

## Tests

Run the test suite:

    uv run python -m unittest discover -s tests -v

The tests cover core logic and can run without performing a full GPU image-generation session.

## Current Scope and Limitations

This repository is an experimental implementation of a structured multi-panel image workflow. The scene-generation and image-processing modules are the main focus; the top-level runner still contains predefined input and output adapters from an earlier workflow and is not yet a general-purpose comic editor or unrestricted text-to-comic application.

- **Character consistency:** The current pipeline does not guarantee identical character appearance, clothing, or proportions across panels. Reference-image conditioning and further training are areas for continued experimentation.
- **Semantic verification:** Without a VLM, image review relies on basic quality checks and CLIP similarity ranking. CLIP scores do not prove that a scene is correct.
- **Human review:** Generated images and verification reports should be reviewed before use.
- **GPU requirements:** Full image generation requires a compatible CUDA environment and sufficient GPU memory. CPU offload can reduce memory pressure at the cost of speed.
- **Model terms:** Check the license and usage terms of the selected checkpoint, LoRA, and other model assets before using generated outputs.

## Development Approach

I use AI tools to explore scene structures, prompt design, and validation strategies, while keeping the implementation and evaluation grounded in actual runs. I review the generated candidates, compare the results with the intended scene, and adjust the prompts, model settings, and composition logic based on what I observe.

The project is being developed as a learning and prototyping environment for character-driven illustrations and short visual stories. The current priority is to improve controllability and visual consistency across scenes.

## Licence

See the repository's `LICENSE` file for the applicable licence and attribution requirements.
