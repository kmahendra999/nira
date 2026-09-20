"""Tests for Faster-Whisper speech backend."""

from unittest.mock import MagicMock, patch

import pytest

from nira.core.registry import SpeechRegistry
from nira.speech.faster_whisper import FasterWhisperBackend


@pytest.fixture(autouse=True)
def _register_faster_whisper():
    """Re-register after any registry clear."""
    if not SpeechRegistry.contains("faster-whisper"):
        SpeechRegistry.register_value("faster-whisper", FasterWhisperBackend)


def test_faster_whisper_backend_registers():
    """Backend registers itself in SpeechRegistry."""
    assert SpeechRegistry.contains("faster-whisper")


def test_faster_whisper_transcribe():
    """Transcribe returns a TranscriptionResult."""
    from nira.speech._stubs import TranscriptionResult

    mock_model = MagicMock()
    mock_segment = MagicMock()
    mock_segment.text = " Hello world"
    mock_segment.start = 0.0
    mock_segment.end = 1.2
    mock_segment.avg_logprob = -0.3

    mock_info = MagicMock()
    mock_info.language = "en"
    mock_info.language_probability = 0.95
    mock_info.duration = 1.5

    mock_model.transcribe.return_value = ([mock_segment], mock_info)

    with patch(
        "nira.speech.faster_whisper.WhisperModel",
        return_value=mock_model,
    ):
        from nira.speech.faster_whisper import FasterWhisperBackend

        backend = FasterWhisperBackend(model_size="base", device="cpu")
        result = backend.transcribe(b"fake audio bytes")

        assert isinstance(result, TranscriptionResult)
        assert result.text == "Hello world"
        assert result.language == "en"
        assert result.duration_seconds == 1.5


def test_faster_whisper_transcribe_temp_file_reopenable_and_removed():
    """The temp file must be closed before the model reads it, and gone after.

    On Windows, an open NamedTemporaryFile holds an exclusive handle, so
    PyAV's reopen of the path inside model.transcribe() fails with EACCES
    unless the file is closed first. Opening the path inside the mocked
    transcribe reproduces that failure mode on Windows.
    """
    import os

    mock_info = MagicMock()
    mock_info.language = "en"
    mock_info.language_probability = 0.95
    mock_info.duration = 1.5

    seen = {}

    def fake_transcribe(path, **kwargs):
        seen["path"] = path
        with open(path, "rb") as fh:
            seen["content"] = fh.read()
        return iter(()), mock_info

    mock_model = MagicMock()
    mock_model.transcribe.side_effect = fake_transcribe

    with patch(
        "nira.speech.faster_whisper.WhisperModel",
        return_value=mock_model,
    ):
        backend = FasterWhisperBackend(model_size="base", device="cpu")
        backend.transcribe(b"fake audio bytes")

    assert seen["content"] == b"fake audio bytes"
    assert not os.path.exists(seen["path"])


def test_faster_whisper_transcribe_removes_temp_file_on_error():
    """The temp file is cleaned up even when transcription fails."""
    import os

    seen = {}

    def fake_transcribe(path, **kwargs):
        seen["path"] = path
        raise RuntimeError("decode failed")

    mock_model = MagicMock()
    mock_model.transcribe.side_effect = fake_transcribe

    with patch(
        "nira.speech.faster_whisper.WhisperModel",
        return_value=mock_model,
    ):
        backend = FasterWhisperBackend(model_size="base", device="cpu")
        with pytest.raises(RuntimeError, match="decode failed"):
            backend.transcribe(b"fake audio bytes")

    assert "path" in seen
    assert not os.path.exists(seen["path"])
    assert "decode failed" in (backend.last_error() or "")


def test_faster_whisper_falls_back_from_unsupported_float16():
    mock_model = MagicMock()

    with (
        patch(
            "nira.speech.faster_whisper.WhisperModel",
            return_value=mock_model,
        ) as mock_whisper,
        patch(
            "nira.speech.faster_whisper.ctranslate2",
            MagicMock(
                get_supported_compute_types=MagicMock(return_value={"float32", "int8"})
            ),
        ),
    ):
        backend = FasterWhisperBackend(
            model_size="base",
            device="cpu",
            compute_type="float16",
        )
        assert backend._ensure_model() is mock_model

    mock_whisper.assert_called_once_with("base", device="cpu", compute_type="int8")


def test_faster_whisper_missing_dependency_hint_uses_desktop_extra():
    with patch("nira.speech.faster_whisper.WhisperModel", new=None):
        backend = FasterWhisperBackend()

        with pytest.raises(ImportError) as excinfo:
            backend._ensure_model()

    assert "uv sync --extra desktop" in str(excinfo.value)
    assert "uv sync --extra speech" not in str(excinfo.value)


def test_faster_whisper_health_no_model():
    """Health returns False before model is loaded."""
    with patch(
        "nira.speech.faster_whisper.WhisperModel",
        new=None,
    ):
        backend = FasterWhisperBackend()
        assert backend.health() is False
        assert "uv sync --extra desktop" in (backend.last_error() or "")


def test_faster_whisper_health_captures_load_error():
    with patch(
        "nira.speech.faster_whisper.WhisperModel",
        side_effect=RuntimeError("missing cublas64_12.dll"),
    ):
        backend = FasterWhisperBackend()
        assert backend.health() is False
        assert "missing cublas64_12.dll" in (backend.last_error() or "")


def test_faster_whisper_supported_formats():
    """Backend supports standard audio formats."""
    with patch("nira.speech.faster_whisper.WhisperModel"):
        from nira.speech.faster_whisper import FasterWhisperBackend

        backend = FasterWhisperBackend.__new__(FasterWhisperBackend)
        formats = backend.supported_formats()
        assert "wav" in formats
        assert "mp3" in formats
        assert "webm" in formats


def _wav_bytes(samples: list[int], *, rate: int = 16000, channels: int = 1) -> bytes:
    import io
    import struct
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buf.getvalue()


def _transcribing_backend():
    model = MagicMock()
    segment = MagicMock()
    segment.text = " hi"
    segment.start = 0.0
    segment.end = 1.0
    model.transcribe.return_value = ([segment], MagicMock(language="en"))
    backend = FasterWhisperBackend()
    backend._model = model
    return backend, model


class TestInMemoryDecoding:
    """A WAV from our own recorder should never touch the disk.

    Every utterance used to be written to a temp file and reopened through
    PyAV — a write, a reopen and a container parse, to recover samples that
    were already in memory.
    """

    def test_wav_is_passed_as_samples_not_a_path(self) -> None:
        backend, model = _transcribing_backend()

        backend.transcribe(_wav_bytes([100, -100] * 800), format="wav")

        source = model.transcribe.call_args.args[0]
        assert not isinstance(source, str), "audio was written to a file"
        assert hasattr(source, "dtype"), "expected a numpy array of samples"

    def test_no_temp_file_is_created_for_wav(self, tmp_path, monkeypatch) -> None:
        backend, _ = _transcribing_backend()
        monkeypatch.setattr("tempfile.tempdir", str(tmp_path))

        backend.transcribe(_wav_bytes([1, 2, 3, 4]), format="wav")

        assert list(tmp_path.iterdir()) == []

    def test_samples_are_normalised_to_float(self) -> None:
        samples = FasterWhisperBackend._decode_pcm(_wav_bytes([32767, -32768]))

        assert samples is not None
        assert samples.dtype.kind == "f"
        assert -1.001 <= float(samples.min()) <= 1.001
        assert -1.001 <= float(samples.max()) <= 1.001

    def test_stereo_is_mixed_down_to_mono(self) -> None:
        """Whisper wants mono; averaging beats dropping a channel."""
        stereo = _wav_bytes([1000, 3000] * 4, channels=2)

        samples = FasterWhisperBackend._decode_pcm(stereo)

        assert samples is not None
        assert len(samples) == 4

    def test_unparseable_bytes_fall_back_to_the_file_path(self) -> None:
        assert FasterWhisperBackend._decode_pcm(b"not a wav at all") is None

    def test_non_wav_format_still_uses_a_file(self) -> None:
        """mp3/m4a need PyAV, which wants a path."""
        backend, model = _transcribing_backend()

        backend.transcribe(b"\xff\xfb fake mp3", format="mp3")

        assert isinstance(model.transcribe.call_args.args[0], str)


class TestConversationalDecodeOptions:
    """transcribe() forwarded only `language`, inheriting batch defaults.

    beam_size=5 with a six-step temperature fallback is right for
    transcribing a recording and wrong for a turn someone is waiting on.
    """

    def _options(self) -> dict:
        backend, model = _transcribing_backend()
        backend.transcribe(_wav_bytes([1, 2, 3, 4]), format="wav")
        return model.transcribe.call_args.kwargs

    def test_greedy_decoding(self) -> None:
        options = self._options()
        assert options["beam_size"] == 1
        assert options["best_of"] == 1

    def test_no_temperature_fallback_ladder(self) -> None:
        """The ladder silently re-decodes up to six times — pure tail latency."""
        assert self._options()["temperature"] == 0.0

    def test_utterances_are_decoded_independently(self) -> None:
        """Conditioning is the mechanism behind Whisper's repetition loops."""
        assert self._options()["condition_on_previous_text"] is False

    def test_bundled_vad_is_enabled(self) -> None:
        """faster-whisper ships Silero and it was switched off."""
        assert self._options()["vad_filter"] is True

    def test_language_is_still_forwarded(self) -> None:
        backend, model = _transcribing_backend()

        backend.transcribe(_wav_bytes([1, 2]), format="wav", language="de")

        assert model.transcribe.call_args.kwargs["language"] == "de"

    def test_no_language_means_auto_detect(self) -> None:
        assert "language" not in self._options()
