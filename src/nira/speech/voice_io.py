"""Microphone capture with voice activity detection, and audio playback.

Capture used to end an utterance after 1.5 s of silence measured against a
fixed absolute RMS threshold of 500. Both numbers were problems.

The 1.5 s was pure latency on every single turn, paid before any model ran, so
a conversational response budget was gone before transcription started. The
fixed threshold assumed one room: in a noisy one the gate never closes and you
record the full ceiling, while a quiet or low-gain microphone never opens it and
you wait out the startup timeout. A threshold has to be relative to the room's
own noise floor, which is what this measures.

Playback was ``sd.play(); sd.wait()`` — a blocking wait with no way to stop it.
A long answer could not be cut short, and Ctrl-C did not reach it.
"""

from __future__ import annotations

import io
import logging
import threading
import wave
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 16000
_CHANNELS = 1

# 32 ms per chunk. The trailing-silence window is now short enough that 64 ms
# quantisation was a meaningful share of it.
_CHUNK = 512

_SILENCE_SECONDS = 0.4  # trailing silence that ends an utterance
_STARTUP_SILENCE_SECONDS = 5.0  # give up early if speech never begins
_MAX_RECORD_SECONDS = 30  # safety ceiling

# Ambient level is sampled for this long before the gate is armed.
_CALIBRATION_SECONDS = 0.25

# Speech must exceed the measured noise floor by this factor to open the gate.
_NOISE_MULTIPLIER = 3.0

# ...but never below this, so a silent room (floor near zero) does not arm a
# gate that any faint hum would trip.
_MIN_SPEECH_RMS = 120.0

# ...and never above this, so calibrating while the user is already talking
# cannot raise the bar past ordinary speech.
_MAX_SPEECH_RMS = 2000.0

# Closing threshold, as a fraction of the opening one. Hysteresis: without a
# gap the gate chatters on every syllable boundary and clips the utterance.
_RELEASE_RATIO = 0.6


@dataclass
class Recording:
    """Captured audio plus what the gate observed while capturing it."""

    audio: bytes
    """WAV bytes, 16-bit mono."""

    had_speech: bool
    """False when the gate never opened.

    The caller should skip transcription entirely in that case. Sending
    silence to Whisper costs a full decode and reliably hallucinates stock
    phrases ("Thank you.", "Thanks for watching!") out of nothing.
    """

    duration_seconds: float
    noise_floor: float = 0.0
    threshold: float = 0.0


def _rms(data: bytes) -> float:
    """RMS amplitude of 16-bit PCM bytes."""
    import numpy as np

    if not data:
        return 0.0
    samples = np.frombuffer(data, dtype="<i2")
    if samples.size == 0:
        return 0.0
    # float64 accumulate: squaring int16 overflows, and the mean of a large
    # chunk in float32 loses enough precision to wobble a threshold decision.
    return float(np.sqrt(np.mean(samples.astype("float64") ** 2)))


def record_until_silence(
    *,
    sample_rate: int = _SAMPLE_RATE,
    silence_threshold: float | None = None,
    silence_seconds: float = _SILENCE_SECONDS,
    startup_silence_seconds: float = _STARTUP_SILENCE_SECONDS,
    max_seconds: float = _MAX_RECORD_SECONDS,
    calibration_seconds: float = _CALIBRATION_SECONDS,
    chunk: int = _CHUNK,
) -> Recording:
    """Record until the speaker stops, and report whether they ever started.

    ``silence_threshold`` overrides the measured noise floor; leave it unset to
    calibrate against the room, which is almost always what you want.
    """
    try:
        import sounddevice as sd
    except ImportError:
        raise RuntimeError(
            "sounddevice is required for voice input. "
            "Install with: pip install 'Nira[voice]'"
        )

    chunks_per_second = sample_rate / chunk
    silence_chunks = max(1, round(silence_seconds * chunks_per_second))
    startup_chunks = max(1, round(startup_silence_seconds * chunks_per_second))
    max_chunks = max(1, round(max_seconds * chunks_per_second))
    calibration_chunks = (
        0
        if silence_threshold is not None
        else max(1, round(calibration_seconds * chunks_per_second))
    )

    frames: list[bytes] = []
    ambient: list[float] = []
    silence_count = 0
    has_speech = False
    noise_floor = 0.0
    open_at = float(silence_threshold) if silence_threshold is not None else 0.0
    close_at = open_at * _RELEASE_RATIO

    with sd.RawInputStream(
        samplerate=sample_rate,
        channels=_CHANNELS,
        dtype="int16",
        blocksize=chunk,
    ) as stream:
        for index in range(max_chunks):
            raw, _ = stream.read(chunk)
            data = bytes(raw)
            frames.append(data)
            amplitude = _rms(data)

            if index < calibration_chunks:
                ambient.append(amplitude)
                if index == calibration_chunks - 1:
                    # The quietest calibration chunk, not the mean: if the user
                    # started talking during calibration the mean is dominated
                    # by their voice, and the gate would be set above it.
                    noise_floor = min(ambient) if ambient else 0.0
                    open_at = min(
                        max(noise_floor * _NOISE_MULTIPLIER, _MIN_SPEECH_RMS),
                        _MAX_SPEECH_RMS,
                    )
                    close_at = open_at * _RELEASE_RATIO
                continue

            if not has_speech:
                if amplitude > open_at:
                    has_speech = True
                    silence_count = 0
                elif index + 1 >= startup_chunks:
                    break
                continue

            if amplitude > close_at:
                silence_count = 0
            else:
                silence_count += 1
                if silence_count >= silence_chunks:
                    break

    return Recording(
        audio=_frames_to_wav(frames, sample_rate),
        had_speech=has_speech,
        duration_seconds=len(frames) * chunk / sample_rate if sample_rate else 0.0,
        noise_floor=noise_floor,
        threshold=open_at,
    )


def _frames_to_wav(frames: list[bytes], sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(_CHANNELS)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(b"".join(frames))
    return buf.getvalue()


def _decode(audio: bytes, fallback_rate: int):
    """Decode WAV bytes to float32 samples, falling back to raw PCM."""
    import numpy as np
    import soundfile as sf

    try:
        data, rate = sf.read(io.BytesIO(audio), dtype="float32")
        return data, rate
    except Exception:
        samples = np.frombuffer(audio, dtype="<i2").astype("float32") / 32768.0
        return samples, fallback_rate


def play_wav(
    audio: bytes,
    sample_rate: int = 24000,
    *,
    interrupt: threading.Event | None = None,
) -> bool:
    """Play audio, returning True if it finished and False if it was cut short.

    Pass ``interrupt`` to stop playback early — that is what makes a long
    answer interruptible. Previously this was ``sd.play(); sd.wait()``, which
    offers no way in: the reply had to finish, and Ctrl-C did not reach it
    because the wait sat outside the REPL's handler.
    """
    if not audio:
        # Nothing to play, and no reason to import an optional decoder to
        # discover that.
        return True

    try:
        import sounddevice as sd
    except ImportError:
        raise RuntimeError(
            "sounddevice, numpy, and soundfile are required for voice output. "
            "Install with: pip install 'Nira[voice]'"
        )

    data, rate = _decode(audio, sample_rate)
    if len(data) == 0:
        return True

    sd.play(data, rate)
    try:
        if interrupt is None:
            sd.wait()
            return True

        # Poll rather than sd.wait() so the event is observed promptly. 20 ms
        # is well under the ~150 ms at which a person notices a delay, and the
        # cost is negligible next to the audio callback itself.
        while sd.get_stream().active:
            if interrupt.wait(0.02):
                sd.stop()
                return False
        return True
    except KeyboardInterrupt:
        # Ctrl-C during a long reply should stop the audio, not leave it
        # playing while the traceback prints.
        sd.stop()
        raise
    finally:
        # A partially played buffer must not bleed into the next utterance.
        if interrupt is not None and interrupt.is_set():
            sd.stop()


# Barge-in needs a higher bar than ordinary capture. Without acoustic echo
# cancellation the microphone hears the reply itself, so the gate has to ignore
# anything at the level the speakers produce and require the sound to persist.
_BARGE_IN_MULTIPLIER = 6.0
_BARGE_IN_SUSTAIN_SECONDS = 0.25


class SpeechInterrupter:
    """Watch the microphone during playback and signal when the user speaks.

    Use as a context manager; the :attr:`triggered` event is what
    :func:`play_wav` takes as its ``interrupt``.

    This is what makes a spoken reply interruptible rather than something you
    have to sit through. It is deliberately harder to trigger than ordinary
    capture: sustained sound well above the room's floor, because on open
    speakers the microphone is also hearing the reply and a hair trigger makes
    Nira interrupt itself mid-sentence. There is no echo cancellation here, so
    this belongs behind ``speech.barge_in`` and really wants headphones.
    """

    def __init__(
        self,
        *,
        sample_rate: int = _SAMPLE_RATE,
        chunk: int = _CHUNK,
        noise_floor: float = 0.0,
        threshold: float | None = None,
        sustain_seconds: float = _BARGE_IN_SUSTAIN_SECONDS,
    ) -> None:
        self.triggered = threading.Event()
        self._sample_rate = sample_rate
        self._chunk = chunk
        self._threshold = (
            float(threshold)
            if threshold is not None
            else min(
                max(noise_floor * _BARGE_IN_MULTIPLIER, _MIN_SPEECH_RMS * 2),
                _MAX_SPEECH_RMS,
            )
        )
        self._sustain_chunks = max(1, round(sustain_seconds * (sample_rate / chunk)))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def threshold(self) -> float:
        return self._threshold

    def __enter__(self) -> "SpeechInterrupter":
        self._thread = threading.Thread(
            target=self._listen, name="nira-barge-in", daemon=True
        )
        self._thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _listen(self) -> None:
        try:
            import sounddevice as sd
        except ImportError:
            return

        consecutive = 0
        try:
            with sd.RawInputStream(
                samplerate=self._sample_rate,
                channels=_CHANNELS,
                dtype="int16",
                blocksize=self._chunk,
            ) as stream:
                while not self._stop.is_set():
                    raw, _ = stream.read(self._chunk)
                    if _rms(bytes(raw)) > self._threshold:
                        consecutive += 1
                        if consecutive >= self._sustain_chunks:
                            self.triggered.set()
                            return
                    else:
                        consecutive = 0
        except Exception:
            # The reply must keep playing if the microphone is unavailable —
            # losing barge-in is a missing convenience, not a failed turn.
            logger.debug("barge-in listener stopped", exc_info=True)


__all__ = [
    "Recording",
    "SpeechInterrupter",
    "play_wav",
    "record_until_silence",
]
