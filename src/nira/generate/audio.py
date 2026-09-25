"""Generating audio: speech, and music or sound effects.

Two genuinely different jobs behind one endpoint, chosen by ``mode``:

**speech** reuses the TTS backend the app already has — Kokoro is configured
in ``[speech] tts_backend`` and is what reads replies aloud. Speech synthesis
is cheap: Kokoro runs faster than real time on a CPU, so a paragraph is a
second or two.

**music** is a different animal. MusicGen-small is ~1.2 GB and, without a GPU,
generates roughly at one-to-two times real time per second of output — a ten
second clip is a minute or so of work. That is slow but not unreasonable, and
unlike video it degrades gracefully: ask for less audio and you wait less.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

__all__ = ["available", "why", "run", "MODES"]

MODES = ("speech", "music")

#: MusicGen sizes. `small` is the only one worth offering without a GPU.
MUSIC_MODELS = {
    "small": {"repo": "facebook/musicgen-small", "download_gb": 1.2},
    "medium": {"repo": "facebook/musicgen-medium", "download_gb": 3.5},
}

MAX_MUSIC_SECONDS = 30

_MUSIC: Optional[Any] = None
_MUSIC_KEY = ""


def available() -> bool:
    # Speech needs only the existing TTS stack; music needs transformers.
    # Report available if either can work, and fail per-mode with a message
    # that names what is missing.
    try:
        import soundfile  # noqa: F401
    except ImportError:
        return False
    return True


def why() -> str:
    return (
        "Audio generation needs soundfile. Install it with: "
        "uv sync --extra generate"
    )


def _generate_speech(job: Any, report: Callable[[float, str], None]) -> str:
    import soundfile as sf

    from nira.core.config import load_config
    from nira.generate.jobs import output_dir

    config = load_config()
    voice = str(job.params.get("voice") or config.speech.voice_id)
    speed = float(job.params.get("speed") or config.speech.voice_speed or 1.0)

    report(0.1, "Loading the voice…")
    try:
        from nira.speech.tts import synthesize  # type: ignore[attr-defined]
    except Exception as exc:  # pragma: no cover - depends on the speech extra
        raise RuntimeError(
            "Speech synthesis needs the speech extra and a TTS backend. "
            "Install it with: uv sync --extra speech"
        ) from exc

    report(0.3, f"Speaking as {voice}…")
    samples, sample_rate = synthesize(job.prompt, voice=voice, speed=speed)
    if job.cancelled:
        raise RuntimeError("Cancelled")

    report(0.9, "Saving…")
    filename = f"{job.id}.wav"
    sf.write(output_dir() / filename, samples, sample_rate)
    return filename


def _load_music(size: str, report: Callable[[float, str], None]) -> Any:
    """Load MusicGen's model and processor directly.

    Not ``transformers.pipeline("text-to-audio")``: that helper is broken in
    transformers 5.17 — its preprocess step calls ``BatchEncoding.to(dtype=…)``
    and BatchEncoding has no such argument, so every generation raises a
    TypeError from inside the library. The model API underneath is stable and
    documented, and going straight to it also means the exact sampling rate
    rather than whatever the pipeline decides to report.
    """
    global _MUSIC, _MUSIC_KEY
    if _MUSIC is not None and _MUSIC_KEY == size:
        return _MUSIC

    from transformers import AutoProcessor, MusicgenForConditionalGeneration

    spec = MUSIC_MODELS[size]
    report(
        0.05,
        f"Loading MusicGen {size} (first run downloads ~{spec['download_gb']} GB)…",
    )
    processor = AutoProcessor.from_pretrained(spec["repo"])
    model = MusicgenForConditionalGeneration.from_pretrained(spec["repo"]).to("cpu")

    _MUSIC = (processor, model)
    _MUSIC_KEY = size
    return _MUSIC


def _generate_music(job: Any, report: Callable[[float, str], None]) -> str:
    import soundfile as sf

    from nira.generate.jobs import output_dir

    size = str(job.params.get("model") or "small")
    if size not in MUSIC_MODELS:
        raise ValueError(
            f"Unknown music model {size!r}. Available: {', '.join(MUSIC_MODELS)}"
        )
    seconds = min(int(job.params.get("seconds") or 10), MAX_MUSIC_SECONDS)

    try:
        processor, model = _load_music(size, report)
    except ImportError as exc:
        raise RuntimeError(
            "Music generation needs transformers. Install it with: "
            "uv sync --extra generate"
        ) from exc

    if job.cancelled:
        raise RuntimeError("Cancelled")

    # MusicGen counts in tokens, at 50 per second of audio.
    tokens = int(seconds * 50)
    report(
        0.15,
        f"Composing {seconds}s — expect roughly {seconds * 6}s on this CPU…",
    )
    inputs = processor(text=[job.prompt], padding=True, return_tensors="pt")
    values = model.generate(**inputs, do_sample=True, max_new_tokens=tokens)

    if job.cancelled:
        raise RuntimeError("Cancelled")

    report(0.9, "Saving…")
    filename = f"{job.id}.wav"
    # (batch, channels, samples) -> (samples, channels) for soundfile.
    audio = values[0].cpu().numpy()
    if audio.ndim > 1:
        audio = audio.T
    sf.write(
        output_dir() / filename, audio, model.config.audio_encoder.sampling_rate
    )
    return filename


def run(job: Any, report: Callable[[float, str], None]) -> str:
    mode = str(job.params.get("mode") or "speech").lower()
    if mode not in MODES:
        raise ValueError(f"Unknown audio mode {mode!r}. Use one of: {', '.join(MODES)}")
    return (
        _generate_speech(job, report)
        if mode == "speech"
        else _generate_music(job, report)
    )
