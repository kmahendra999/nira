"""Voice activity detection and playback control.

Capture previously ended an utterance after 1.5 s of silence measured against a
fixed absolute RMS threshold of 500. The 1.5 s was latency paid on every turn
before any model ran; the fixed threshold assumed one room, so a noisy one
never closed the gate and a quiet microphone never opened it.

These cover the replacement: a threshold derived from the room's own noise
floor, hysteresis so the gate does not chatter between syllables, an explicit
report of whether speech was ever heard, and playback that can be stopped.
"""

from __future__ import annotations

import struct
import sys
import threading
from types import SimpleNamespace

import pytest

from nira.speech.voice_io import Recording, _rms, play_wav, record_until_silence


def _pcm(amplitude: int, frames: int = 512) -> bytes:
    """A chunk of 16-bit PCM at a constant amplitude."""
    return struct.pack(f"<{frames}h", *([amplitude] * frames))


class _FakeStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return None

    def read(self, chunk: int):
        self.reads += 1
        if not self._chunks:
            # The device keeps producing; silence stands in for an idle mic.
            return bytes(chunk * 2), False
        return self._chunks.pop(0), False


def _install_mic(monkeypatch, stream: _FakeStream) -> None:
    monkeypatch.setitem(
        sys.modules, "sounddevice", SimpleNamespace(RawInputStream=lambda **_: stream)
    )


class TestRms:
    def test_silence_is_zero(self) -> None:
        assert _rms(bytes(1024)) == 0.0

    def test_constant_amplitude_is_that_amplitude(self) -> None:
        assert _rms(_pcm(1000)) == pytest.approx(1000.0)

    def test_empty_input_is_zero(self) -> None:
        assert _rms(b"") == 0.0

    def test_full_scale_does_not_overflow(self) -> None:
        """int16 squared overflows int16; the accumulator must be wider."""
        assert _rms(_pcm(-32768)) == pytest.approx(32768.0)


class TestNoiseFloorCalibration:
    def test_threshold_is_derived_from_the_room(self, monkeypatch) -> None:
        """A noisy room must get a higher bar than a quiet one."""
        loud_room = _FakeStream([_pcm(400)] * 40)
        _install_mic(monkeypatch, loud_room)
        noisy = record_until_silence(
            sample_rate=16000, startup_silence_seconds=0.5, max_seconds=1.0
        )

        quiet_room = _FakeStream([_pcm(10)] * 40)
        _install_mic(monkeypatch, quiet_room)
        quiet = record_until_silence(
            sample_rate=16000, startup_silence_seconds=0.5, max_seconds=1.0
        )

        assert noisy.threshold > quiet.threshold

    def test_constant_room_noise_does_not_count_as_speech(self, monkeypatch) -> None:
        """The old fixed threshold recorded the full ceiling in a noisy room."""
        stream = _FakeStream([_pcm(600)] * 60)
        _install_mic(monkeypatch, stream)

        result = record_until_silence(
            sample_rate=16000, startup_silence_seconds=0.5, max_seconds=2.0
        )

        assert result.had_speech is False

    def test_speech_well_above_the_floor_opens_the_gate(self, monkeypatch) -> None:
        chunks = [_pcm(50)] * 8 + [_pcm(4000)] * 10 + [_pcm(50)] * 30
        _install_mic(monkeypatch, _FakeStream(chunks))

        result = record_until_silence(
            sample_rate=16000, startup_silence_seconds=1.0, max_seconds=3.0
        )

        assert result.had_speech is True

    def test_explicit_threshold_skips_calibration(self, monkeypatch) -> None:
        """An override must apply from the first chunk, not after calibration."""
        stream = _FakeStream([_pcm(1000)] * 4 + [bytes(1024)] * 40)
        _install_mic(monkeypatch, stream)

        result = record_until_silence(
            sample_rate=16000,
            silence_threshold=500,
            silence_seconds=0.1,
            max_seconds=3.0,
        )

        assert result.had_speech is True
        assert result.threshold == 500


class TestSilenceWindow:
    def test_startup_timeout_reports_no_speech(self, monkeypatch) -> None:
        """Silence must be reported, not transcribed.

        A full Whisper decode of room tone costs a turn's entire latency
        budget and reliably invents a stock phrase out of the noise.
        """
        _install_mic(monkeypatch, _FakeStream([bytes(1024)] * 200))

        result = record_until_silence(
            sample_rate=16000, startup_silence_seconds=0.3, max_seconds=5.0
        )

        assert result.had_speech is False
        assert isinstance(result, Recording)

    def test_recording_stops_after_the_trailing_silence_window(
        self, monkeypatch
    ) -> None:
        # 8 calibration chunks, then speech, then silence.
        chunks = [_pcm(20)] * 8 + [_pcm(5000)] * 5 + [bytes(1024)] * 100
        stream = _FakeStream(chunks)
        _install_mic(monkeypatch, stream)

        result = record_until_silence(
            sample_rate=16000,
            silence_seconds=0.2,  # ~6 chunks at 32 ms
            startup_silence_seconds=1.0,
            max_seconds=10.0,
        )

        assert result.had_speech is True
        # Calibration + speech + roughly the silence window, nowhere near the
        # 10 s ceiling. The old 1.5 s window would have read far more.
        assert stream.reads < 30

    def test_a_brief_pause_does_not_end_the_utterance(self, monkeypatch) -> None:
        """Hysteresis: the gate must not close between syllables."""
        chunks = (
            [_pcm(20)] * 8
            + [_pcm(5000)] * 4
            + [bytes(1024)] * 2  # short inter-word pause
            + [_pcm(5000)] * 4
            + [bytes(1024)] * 100
        )
        stream = _FakeStream(chunks)
        _install_mic(monkeypatch, stream)

        record_until_silence(
            sample_rate=16000,
            silence_seconds=0.2,
            startup_silence_seconds=1.0,
            max_seconds=10.0,
        )

        # Must have kept recording past the pause to reach the second burst.
        assert stream.reads > 18

    def test_max_seconds_is_a_hard_ceiling(self, monkeypatch) -> None:
        """Continuous speech must still stop somewhere."""
        _install_mic(monkeypatch, _FakeStream([_pcm(8000)] * 10_000))

        result = record_until_silence(
            sample_rate=16000, startup_silence_seconds=1.0, max_seconds=0.5
        )

        assert result.duration_seconds == pytest.approx(0.5, abs=0.05)


class TestPlayback:
    @pytest.fixture(autouse=True)
    def _stub_soundfile(self, monkeypatch):
        """soundfile ships in the voice extra, not the core dependency set.

        Raising from read() also exercises the raw-PCM fallback, which is what
        handles a backend returning bare samples rather than a WAV container.
        """

        def _read(*_args, **_kwargs):
            raise RuntimeError("not a WAV container")

        monkeypatch.setitem(sys.modules, "soundfile", SimpleNamespace(read=_read))

    def _fake_sd(self, active_reads: int = 100):
        state = {"played": None, "stopped": False, "remaining": active_reads}

        def _play(data, rate):
            state["played"] = (data, rate)

        def _stop():
            state["stopped"] = True
            state["remaining"] = 0

        def _get_stream():
            state["remaining"] -= 1
            return SimpleNamespace(active=state["remaining"] > 0)

        return state, SimpleNamespace(
            play=_play, wait=lambda: None, stop=_stop, get_stream=_get_stream
        )

    def test_plays_to_completion_without_an_interrupt(self, monkeypatch) -> None:
        state, fake = self._fake_sd()
        monkeypatch.setitem(sys.modules, "sounddevice", fake)

        assert play_wav(_pcm(1000), 16000) is True
        assert state["played"] is not None

    def test_interrupt_stops_playback(self, monkeypatch) -> None:
        """A long answer has to be interruptible.

        Playback was sd.play() + sd.wait(), which offers no way in: the reply
        had to finish, and Ctrl-C did not reach it.
        """
        state, fake = self._fake_sd()
        monkeypatch.setitem(sys.modules, "sounddevice", fake)

        interrupt = threading.Event()
        interrupt.set()

        assert play_wav(_pcm(1000), 16000, interrupt=interrupt) is False
        assert state["stopped"] is True

    def test_an_unset_interrupt_still_plays_through(self, monkeypatch) -> None:
        state, fake = self._fake_sd(active_reads=3)
        monkeypatch.setitem(sys.modules, "sounddevice", fake)

        assert play_wav(_pcm(1000), 16000, interrupt=threading.Event()) is True
        assert state["stopped"] is False

    def test_empty_audio_is_a_no_op(self, monkeypatch) -> None:
        state, fake = self._fake_sd()
        monkeypatch.setitem(sys.modules, "sounddevice", fake)

        assert play_wav(b"", 16000) is True
        assert state["played"] is None
