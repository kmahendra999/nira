"""Smoke test that the tmp_nira_home fixture works."""

from __future__ import annotations

from pathlib import Path

from nira.core import config as config_mod


def test_fixture_redirects_default_config_dir(tmp_nira_home: Path) -> None:
    assert config_mod.DEFAULT_CONFIG_DIR == tmp_nira_home
    assert tmp_nira_home.exists()
    assert (tmp_nira_home / ".state").exists()
    assert (tmp_nira_home / ".state" / "models").exists()


def test_fixture_redirects_config_path(tmp_nira_home: Path) -> None:
    assert config_mod.DEFAULT_CONFIG_PATH == tmp_nira_home / "config.toml"
