"""Faster-Whisper speech-to-text backend (local, CTranslate2-based)."""

from __future__ import annotations

import logging
import os
import tempfile
from typing import List, Optional

from nira.core.registry import SpeechRegistry
from nira.speech._stubs import Segment, SpeechBackend, TranscriptionResult

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None  # type: ignore[assignment, misc]

try:
    import ctranslate2
except ImportError:
    ctranslate2 = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


# Decode settings tuned for conversation rather than transcription accuracy.
#
# transcribe() previously forwarded only `language`, inheriting faster-whisper's
# defaults: beam_size=5, best_of=5, a six-step temperature fallback ladder, and
# condition_on_previous_text=True. Those are the right defaults for batch
# transcribing a recording, and the wrong ones for a turn in a conversation,
# where the user is waiting and the utterance is a few seconds long.
#
#   beam_size=1      greedy. Beam search buys accuracy on hard audio and costs
#                    a multiple of the decode; a short, close-mic utterance is
#                    not hard audio.
#   temperature=0.0  a single pass. The default ladder silently re-decodes up
#                    to six times when a heuristic says the output looks wrong,
#                    which is exactly the tail latency a conversation cannot
#                    absorb.
#   condition_on_previous_text=False
#                    each utterance is independent here, and conditioning is
#                    the mechanism behind Whisper's well-known repetition
#                    loops, where one bad transcript poisons the rest.
#   vad_filter=True  faster-whisper ships Silero and it was switched off.
#                    Trimming non-speech before the decode removes work and
#                    suppresses the hallucinated stock phrases Whisper emits
#                    when handed silence.
#   without_timestamps=True
#                    segment timings are not used by any caller here.
_CONVERSATIONAL_DECODE: dict = {
    "beam_size": 1,
    "best_of": 1,
    "temperature": 0.0,
    "condition_on_previous_text": False,
    "vad_filter": True,
    "without_timestamps": True,
}


@SpeechRegistry.register("faster-whisper")
class FasterWhisperBackend(SpeechBackend):
    """Local speech-to-text using Faster-Whisper (CTranslate2)."""

    backend_id = "faster-whisper"

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "float16",
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._model: Optional[WhisperModel] = None
        self._last_error: Optional[str] = None

    def _resolve_compute_type(self) -> str:
        """Pick a CTranslate2 compute type supported by the configured device."""
        if ctranslate2 is None:
            return self._compute_type

        try:
            supported = set(ctranslate2.get_supported_compute_types(self._device))
        except Exception as exc:
            logger.debug(
                "Could not inspect CTranslate2 compute types for %s: %s",
                self._device,
                exc,
            )
            return self._compute_type

        if self._compute_type in supported:
            return self._compute_type

        preferences = (
            ("int8", "float32", "int8_float32", "int16")
            if self._compute_type == "float16"
            else ("float32", "int8", "int8_float32", "int16")
        )
        fallback = next((value for value in preferences if value in supported), None)
        if fallback is None:
            return self._compute_type

        logger.warning(
            "CTranslate2 compute_type=%r is not supported on device=%r; "
            "using %r instead",
            self._compute_type,
            self._device,
            fallback,
        )
        return fallback

    def _ensure_model(self) -> WhisperModel:
        """Lazy-load the Whisper model on first use."""
        if self._model is None:
            if WhisperModel is None:
                self._last_error = (
                    "faster-whisper is not installed. "
                    "Install with: uv sync --extra desktop"
                )
                raise ImportError(self._last_error)
            compute_type = self._resolve_compute_type()
            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=compute_type,
            )
        self._last_error = None
        return self._model

    @staticmethod
    def _decode_pcm(audio: bytes):
        """Return float32 samples for WAV bytes, or None if unparseable.

        faster-whisper accepts a numpy array directly, so a WAV produced by our
        own recorder never needs to touch the disk. It used to be written to a
        temp file and reopened through PyAV on every single utterance — a
        write, an fsync-less flush, a reopen and a container parse, all to hand
        back samples we already had in memory.
        """
        import io
        import wave

        try:
            with wave.open(io.BytesIO(audio), "rb") as wf:
                if wf.getsampwidth() != 2:
                    return None
                channels = wf.getnchannels()
                frames = wf.readframes(wf.getnframes())
        except (wave.Error, EOFError, OSError):
            return None

        import numpy as np

        samples = np.frombuffer(frames, dtype="<i2").astype("float32") / 32768.0
        if channels > 1:
            # Whisper wants mono; average the channels rather than dropping one.
            samples = samples.reshape(-1, channels).mean(axis=1)
        return np.ascontiguousarray(samples)

    def transcribe(
        self,
        audio: bytes,
        *,
        format: str = "wav",
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio bytes using Faster-Whisper."""
        try:
            model = self._ensure_model()

            kwargs = dict(_CONVERSATIONAL_DECODE)
            if language:
                kwargs["language"] = language

            source = self._decode_pcm(audio) if format in ("wav", ".wav") else None
            if source is not None:
                segments_iter, info = model.transcribe(source, **kwargs)
                segments_list = list(segments_iter)
            else:
                # A container we cannot parse ourselves (mp3, m4a, …): hand it
                # to PyAV through a file, as before.
                #
                # delete=False + manual unlink: on Windows an open
                # NamedTemporaryFile holds an exclusive handle, so PyAV's
                # reopen of tmp.name inside model.transcribe() fails EACCES.
                suffix = f".{format}" if not format.startswith(".") else format
                tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
                try:
                    with tmp:
                        tmp.write(audio)
                    segments_iter, info = model.transcribe(tmp.name, **kwargs)
                    segments_list = list(segments_iter)
                finally:
                    try:
                        os.unlink(tmp.name)
                    except OSError as unlink_exc:
                        logger.debug(
                            "Could not remove temp audio file %s: %s",
                            tmp.name,
                            unlink_exc,
                        )
        except Exception as exc:
            self._last_error = str(exc)
            raise

        # Build result
        text = "".join(seg.text for seg in segments_list).strip()
        segments = [
            Segment(
                text=seg.text.strip(),
                start=seg.start,
                end=seg.end,
                confidence=None,
            )
            for seg in segments_list
        ]

        self._last_error = None
        return TranscriptionResult(
            text=text,
            language=getattr(info, "language", None),
            confidence=getattr(info, "language_probability", None),
            duration_seconds=getattr(info, "duration", 0.0),
            segments=segments,
        )

    def health(self) -> bool:
        """Check if model is loaded or loadable."""
        try:
            self._ensure_model()
            return True
        except Exception as exc:
            self._last_error = str(exc)
            logger.debug("Faster-Whisper health check failed: %s", exc)
            return False

    def last_error(self) -> Optional[str]:
        """Return the last model load or transcription error, if any."""
        return self._last_error

    def supported_formats(self) -> List[str]:
        """Supported audio formats (same as ffmpeg/Whisper)."""
        return ["wav", "mp3", "m4a", "ogg", "flac", "webm"]
