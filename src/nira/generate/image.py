"""Generating an image, on a CPU.

The model choice is the whole design. A standard Stable Diffusion run is
20-50 denoising steps, and on a 12900K with no GPU each step is seconds — so
a single 512x512 image is minutes. The *turbo* distillations do the same job
in one to four steps, which turns "go and make a cup of tea" into "wait about
half a minute". That is the difference between a feature someone uses and one
they try once.

So the default is SD-Turbo: ~2.5 GB, one step, 512x512. SDXL-Turbo is offered
for when quality matters more than the wait, and plain SD 1.5 for when someone
wants the classic sampler with a step count they control.

Weights download on first use and are cached by Hugging Face under
~/.cache/huggingface. Nothing is bundled.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

__all__ = ["available", "why", "run", "MODELS", "DEFAULT_MODEL"]


#: Model id -> what a user needs to know to choose.
MODELS: Dict[str, Dict[str, Any]] = {
    "sd-turbo": {
        "repo": "stabilityai/sd-turbo",
        "steps": 1,
        "guidance": 0.0,  # Turbo models are trained for no classifier-free guidance.
        "size": 512,
        "download_gb": 2.5,
        "note": "Fastest. One step, 512px. The sensible default without a GPU.",
    },
    "sdxl-turbo": {
        "repo": "stabilityai/sdxl-turbo",
        "steps": 2,
        "guidance": 0.0,
        "size": 512,
        "download_gb": 6.9,
        "note": "Better detail, a few times slower. Still only a couple of steps.",
    },
    "sd-1.5": {
        "repo": "stable-diffusion-v1-5/stable-diffusion-v1-5",
        "steps": 20,
        "guidance": 7.5,
        "size": 512,
        "download_gb": 4.0,
        "note": (
            "The classic sampler. Best prompt-following, and minutes per "
            "image here."
        ),
    },
}

DEFAULT_MODEL = "sd-turbo"

# Cached between jobs: loading a pipeline is several seconds of disk and RAM,
# and the queue runs jobs back to back.
_PIPELINE: Optional[Any] = None
_PIPELINE_KEY: str = ""


def available() -> bool:
    try:
        import diffusers  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        return False
    return True


def why() -> str:
    return (
        "Image generation needs torch and diffusers. Install them with: "
        "uv sync --extra generate"
    )


def _load(model: str, report: Callable[[float, str], None]) -> Any:
    global _PIPELINE, _PIPELINE_KEY
    if _PIPELINE is not None and _PIPELINE_KEY == model:
        return _PIPELINE

    import torch
    from diffusers import AutoPipelineForText2Image

    spec = MODELS[model]
    report(0.02, f"Loading {model} (first run downloads ~{spec['download_gb']} GB)…")

    pipeline = AutoPipelineForText2Image.from_pretrained(
        spec["repo"],
        dtype=torch.float32,  # float16 is a GPU optimisation; CPU wants fp32.
        safety_checker=None,
        requires_safety_checker=False,
    )
    pipeline.to("cpu")
    # The default attention slicing trades a little speed for much less peak
    # RAM. On a box with 152 GB that is not the constraint, but it also keeps
    # the model from fighting the Ollama process for memory.
    pipeline.enable_attention_slicing()
    pipeline.set_progress_bar_config(disable=True)

    _PIPELINE, _PIPELINE_KEY = pipeline, model
    return pipeline


def run(job: Any, report: Callable[[float, str], None]) -> str:
    """Generate one image and return its filename under ``output_dir()``."""
    import torch

    from nira.generate.jobs import output_dir

    model = str(job.params.get("model") or DEFAULT_MODEL)
    if model not in MODELS:
        raise ValueError(
            f"Unknown image model {model!r}. Available: {', '.join(MODELS)}"
        )
    spec = MODELS[model]

    steps = int(job.params.get("steps") or spec["steps"])
    guidance = float(job.params.get("guidance", spec["guidance"]))
    size = int(job.params.get("size") or spec["size"])
    seed = job.params.get("seed")

    pipeline = _load(model, report)
    if job.cancelled:
        raise RuntimeError("Cancelled before starting")

    generator = None
    if seed is not None:
        generator = torch.Generator(device="cpu").manual_seed(int(seed))

    started = time.time()

    def on_step(_pipe: Any, step: int, _timestep: Any, kwargs: Dict[str, Any]):
        # Cancellation has to be checked here: a step can take seconds, and
        # the user pressing stop should not wait for the whole run.
        if job.cancelled:
            raise RuntimeError("Cancelled")
        done = (step + 1) / max(1, steps)
        elapsed = time.time() - started
        remaining = (elapsed / max(done, 0.01)) - elapsed
        report(
            0.05 + 0.9 * done,
            f"Step {step + 1} of {steps} · about {int(remaining)}s left",
        )
        return kwargs

    report(0.05, f"Generating at {size}×{size}…")
    result = pipeline(
        prompt=job.prompt,
        num_inference_steps=steps,
        guidance_scale=guidance,
        height=size,
        width=size,
        generator=generator,
        callback_on_step_end=on_step,
    )

    if job.cancelled:
        raise RuntimeError("Cancelled")

    report(0.97, "Saving…")
    filename = f"{job.id}.png"
    result.images[0].save(output_dir() / filename)
    return filename
