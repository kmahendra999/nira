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
