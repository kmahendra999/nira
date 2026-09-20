"""Tests for speech configuration."""

from types import SimpleNamespace

from nira.core.config import NiraConfig, SpeechConfig


def _recorded(audio: bytes = b"RIFFfake", *, had_speech: bool = True):
    """A Recording as record_until_silence now returns.

    It used to return bare WAV bytes. Reporting whether the gate ever opened
    lets the caller skip transcription on silence, which otherwise costs a
    full Whisper decode and reliably hallucinates a stock phrase.
    """
    from nira.speech.voice_io import Recording

    return Recording(audio=audio, had_speech=had_speech, duration_seconds=1.0)


def test_speech_config_defaults():
    cfg = SpeechConfig()
    assert cfg.backend == "auto"
    assert cfg.model == "base"
    assert cfg.language == ""
    assert cfg.device == "auto"
    assert cfg.compute_type == "float16"


def test_nira_config_has_speech():
    cfg = NiraConfig()
    assert hasattr(cfg, "speech")
    assert isinstance(cfg.speech, SpeechConfig)
    assert cfg.speech.backend == "auto"


def test_nira_system_has_speech_backend():
    """NiraSystem has a speech_backend attribute."""
    from nira.system import NiraSystem

    assert "speech_backend" in NiraSystem.__dataclass_fields__


class TestVoiceExtraCoversTheWholeLoop:
    """`pip install 'Nira[voice]'` must yield a voice loop that can both
    hear and answer.

    It used to install only kokoro, while `speech` installed only
    faster-whisper — so neither extra on its own gave a working loop, and the
    CLI's "no STT backend" message recommended `Nira[speech]`, which leaves the
    default tts_backend (kokoro) uninstalled. Voice mode could transcribe and
    then fail to speak.
    """

    def _voice_extra(self) -> list[str]:
        import sys
        from pathlib import Path

        if sys.version_info >= (3, 11):
            import tomllib
        else:  # pragma: no cover - 3.10 only
            import tomli as tomllib

        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        return data["project"]["optional-dependencies"]["voice"]

    def test_voice_extra_installs_the_default_tts_backend(self) -> None:
        from nira.core.config import SpeechConfig

        assert SpeechConfig().tts_backend == "kokoro", (
            "default changed; update the voice extra to match"
        )
        assert any(d.startswith("kokoro") for d in self._voice_extra())

    def test_voice_extra_installs_an_stt_backend(self) -> None:
        assert any(d.startswith("faster-whisper") for d in self._voice_extra())

    def test_voice_extra_installs_audio_io(self) -> None:
        deps = self._voice_extra()
        for required in ("sounddevice", "soundfile", "numpy"):
            assert any(d.startswith(required) for d in deps), f"missing {required}"


class TestConfiguredLanguageReachesTheBackend:
    """speech.language was declared in SpeechConfig and read nowhere.

    Beyond ignoring the user's setting, this cost latency on every turn:
    with no language, Whisper runs a detection pass over each utterance,
    which is wasted work for someone who always speaks the same language.
    """

    def _session(self, language: str):
        from types import SimpleNamespace

        from nira.cli._voice_chat import VoiceSession

        return VoiceSession(SimpleNamespace(speech=SimpleNamespace(language=language)))

    def test_configured_language_is_passed_to_transcribe(self) -> None:
        from unittest.mock import MagicMock, patch

        from nira.cli._voice_chat import record_voice

        backend = MagicMock()
        backend.transcribe.return_value = SimpleNamespace(text="hallo")
        session = self._session("de")
        session._stt_backend = backend
        session._stt_resolved = True

        with patch(
            "nira.speech.voice_io.record_until_silence", return_value=_recorded()
        ):
            record_voice(MagicMock(), session=session)

        assert backend.transcribe.call_args.kwargs["language"] == "de"

    def test_empty_language_means_auto_detect(self) -> None:
        from unittest.mock import MagicMock, patch

        from nira.cli._voice_chat import record_voice

        backend = MagicMock()
        backend.transcribe.return_value = SimpleNamespace(text="hello")
        session = self._session("")
        session._stt_backend = backend
        session._stt_resolved = True

        with patch(
            "nira.speech.voice_io.record_until_silence", return_value=_recorded()
        ):
            record_voice(MagicMock(), session=session)

        assert backend.transcribe.call_args.kwargs["language"] is None

    def test_language_is_resolved_once_per_session(self) -> None:
        session = self._session("fr")

        assert session.get_language() == "fr"
        assert session.get_language() == "fr"

    def test_whitespace_only_language_is_treated_as_auto(self) -> None:
        assert self._session("   ").get_language() is None
