"""Tests for speech configuration."""

from nira.core.config import NiraConfig, SpeechConfig


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
