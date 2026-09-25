"""Generating a short video, on a CPU.

This is the expensive one, and the honest framing matters more here than
anywhere else in this package. A video is N frames denoised together, so the
work is roughly *frames × steps* passes through a UNet — where a still image
is one frame × a few steps.

The choice that makes it possible at all is AnimateDiff-Lightning: a
distilled motion module that needs four steps rather than twenty-five. Four
steps over sixteen frames is sixty-four frame-steps, against a single frame
for SD-Turbo. So expect **minutes, not seconds**, for two seconds of video —
and expect it to scale linearly if you ask for more frames.

It is offered because it works and someone asked for it, not because it is
comfortable. The job queue reports elapsed time and an estimate from the
first step onward so the wait is legible rather than a spinner, and the job
is cancellable between steps.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

__all__ = ["available", "why", "run", "MODELS", "DEFAULT_MODEL", "MAX_FRAMES"]

#: 16 frames at 8 fps is two seconds. More is linearly more expensive.
MAX_FRAMES = 32
DEFAULT_FRAMES = 16
DEFAULT_FPS = 8

MODELS: Dict[str, Dict[str, Any]] = {
    "animatediff-lightning": {
        "base": "emilianJR/epiCRealism",
        "motion_repo": "ByteDance/AnimateDiff-Lightning",
        "motion_ckpt": "animatediff_lightning_4step_diffusers.safetensors",
        "steps": 4,
        "guidance": 1.0,
        "size": 512,
        "download_gb": 4.5,
        "note": (
            "Four steps instead of twenty-five. The only one that is sane "
            "without a GPU."
        ),
    },
    "modelscope": {
        "repo": "damo-vilab/text-to-video-ms-1.7b",
        "steps": 25,
        "guidance": 9.0,
        "size": 256,
        "download_gb": 3.5,
        "note": (
            "The original text-to-video. 25 steps — very slow here, but "
            "lower resolution."
        ),
    },
}

DEFAULT_MODEL = "animatediff-lightning"

_PIPELINE: Optional[Any] = None
_PIPELINE_KEY = ""


def available() -> bool:
    try:
        import diffusers  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        return False
    return True


def why() -> str:
    return (
        "Video generation needs torch and diffusers. Install them with: "
        "uv sync --extra generate"
    )


def _load(model: str, report: Callable[[float, str], None]) -> Any:
    global _PIPELINE, _PIPELINE_KEY
    if _PIPELINE is not None and _PIPELINE_KEY == model:
        return _PIPELINE

    import torch

    spec = MODELS[model]
    report(0.02, f"Loading {model} (first run downloads ~{spec['download_gb']} GB)…")

    if model == "animatediff-lightning":
        from diffusers import (
            AnimateDiffPipeline,
            EulerDiscreteScheduler,
            MotionAdapter,
        )
        from huggingface_hub import hf_hub_download
        from safetensors.torch import load_file

        adapter = MotionAdapter().to("cpu", torch.float32)
        adapter.load_state_dict(
            load_file(
                hf_hub_download(spec["motion_repo"], spec["motion_ckpt"]),
                device="cpu",
            )
        )
        pipeline = AnimateDiffPipeline.from_pretrained(
            spec["base"], motion_adapter=adapter, dtype=torch.float32
        )
        pipeline.scheduler = EulerDiscreteScheduler.from_config(
            pipeline.scheduler.config,
            timestep_spacing="trailing",
            beta_schedule="linear",
        )
    else:
        from diffusers import DiffusionPipeline

        pipeline = DiffusionPipeline.from_pretrained(
            spec["repo"], dtype=torch.float32
        )

    pipeline.to("cpu")
    pipeline.enable_attention_slicing()
    # Video holds every frame's latents at once, so VAE slicing is the
    # difference between a few GB and a few tens of GB at decode time.
    if hasattr(pipeline, "enable_vae_slicing"):
        pipeline.enable_vae_slicing()
    pipeline.set_progress_bar_config(disable=True)

    _PIPELINE, _PIPELINE_KEY = pipeline, model
    return pipeline


def _write_mp4(frames, path, fps: int) -> None:
    """Encode frames to mp4, falling back to an animated GIF."""
    try:
        import imageio.v3 as iio
        import numpy as np

        iio.imwrite(
            path, [np.asarray(f) for f in frames], fps=fps, codec="libx264"
        )
        return
    except Exception as exc:
        logger.warning("mp4 encode failed (%s); falling back to GIF", exc)

    from diffusers.utils import export_to_gif

    export_to_gif(frames, str(path.with_suffix(".gif")))


def run(job: Any, report: Callable[[float, str], None]) -> str:
    import torch

    from nira.generate.jobs import output_dir

    model = str(job.params.get("model") or DEFAULT_MODEL)
    if model not in MODELS:
        raise ValueError(
            f"Unknown video model {model!r}. Available: {', '.join(MODELS)}"
        )
    spec = MODELS[model]

    frames = min(int(job.params.get("frames") or DEFAULT_FRAMES), MAX_FRAMES)
    fps = int(job.params.get("fps") or DEFAULT_FPS)
    steps = int(job.params.get("steps") or spec["steps"])
    guidance = float(job.params.get("guidance", spec["guidance"]))
    seed = job.params.get("seed")

    pipeline = _load(model, report)
    if job.cancelled:
        raise RuntimeError("Cancelled before starting")

    generator = None
    if seed is not None:
        generator = torch.Generator(device="cpu").manual_seed(int(seed))

    started = time.time()

    def on_step(_pipe: Any, step: int, _timestep: Any, kwargs: Dict[str, Any]):
        if job.cancelled:
            raise RuntimeError("Cancelled")
        done = (step + 1) / max(1, steps)
        elapsed = time.time() - started
        remaining = (elapsed / max(done, 0.01)) - elapsed
        report(
            0.05 + 0.85 * done,
            f"Step {step + 1} of {steps} · about {int(remaining // 60)}m "
            f"{int(remaining % 60)}s left",
        )
        return kwargs

    report(
        0.05,
        f"Generating {frames} frames at {spec['size']}px — this takes minutes, "
        "not seconds",
    )
    result = pipeline(
        prompt=job.prompt,
        num_frames=frames,
        num_inference_steps=steps,
        guidance_scale=guidance,
        generator=generator,
        callback_on_step_end=on_step,
    )

    if job.cancelled:
        raise RuntimeError("Cancelled")

    report(0.95, "Encoding…")
    produced = getattr(result, "frames", None)
    produced = produced[0] if produced else result.images
    path = output_dir() / f"{job.id}.mp4"
    _write_mp4(produced, path, fps)
    return path.name if path.exists() else f"{job.id}.gif"
