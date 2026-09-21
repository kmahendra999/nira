"""Tests for the env-aware Nira home-directory resolver (issue #462).

Covers the single-root consolidation: ``$NIRA_HOME`` >
``$XDG_DATA_HOME/nira`` > ``~/.nira``, backward compatibility
(no env => exactly ``~/.nira``), and the source-tree rejection guard.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from nira.core import paths


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every env var that influences home resolution."""
    for var in (
        "NIRA_HOME",
        "XDG_DATA_HOME",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
    ):
        monkeypatch.delenv(var, raising=False)


class TestGetConfigDir:
    """Precedence and backward compatibility of get_config_dir()."""

    def test_default_when_unset_is_legacy_dir(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Backward-compat: with nothing set, the resolved dir is exactly the
        # historical ~/.nira so existing installs are untouched.
        _clear_env(monkeypatch)
        assert paths.get_config_dir() == (Path.home() / ".nira").resolve()

    def test_respects_nira_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        custom = tmp_path / "oj"
        monkeypatch.setenv("NIRA_HOME", str(custom))
        assert paths.get_config_dir() == custom.resolve()

    def test_respects_xdg_data_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        # Single nested 'nira' dir under XDG_DATA_HOME.
        assert paths.get_config_dir() == (tmp_path / "nira").resolve()

    def test_nira_home_wins_over_xdg(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        oj = tmp_path / "oj_wins"
        monkeypatch.setenv("NIRA_HOME", str(oj))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_loses"))
        assert paths.get_config_dir() == oj.resolve()

    def test_expands_user_in_nira_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setenv("NIRA_HOME", "~/relocated-oj")
        assert paths.get_config_dir() == (Path.home() / "relocated-oj").resolve()

    def test_returns_absolute_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setenv("NIRA_HOME", str(tmp_path / "rel"))
        assert paths.get_config_dir().is_absolute()


class TestDerivedDirs:
    """config_path / data_dir / cache_dir all hang off the single root."""

    def test_config_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setenv("NIRA_HOME", str(tmp_path / "oj"))
        assert paths.get_config_path() == (tmp_path / "oj" / "config.toml").resolve()

    def test_data_dir_equals_config_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setenv("NIRA_HOME", str(tmp_path / "oj"))
        assert paths.get_data_dir() == paths.get_config_dir()

    def test_cache_dir_is_nested_cache(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setenv("NIRA_HOME", str(tmp_path / "oj"))
        assert paths.get_cache_dir() == (tmp_path / "oj" / "cache").resolve()

    def test_cache_dir_under_xdg(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert paths.get_cache_dir() == (tmp_path / "nira" / "cache").resolve()


class TestSourceTreeRejection:
    """A home pointing inside the repo must fail loudly (REVIEW.md)."""

    def test_rejects_path_inside_source_tree(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        source_root = paths._find_source_root()
        assert source_root is not None  # We must be running inside the repo.
        monkeypatch.setenv("NIRA_HOME", str(source_root / "junk_dir"))
        with pytest.raises(paths.ConfigurationError, match="inside the source tree"):
            paths.get_config_dir()


class TestLegacyConstantsHonorEnv:
    """The legacy DEFAULT_CONFIG_* names route through the env-aware resolver.

    This is the exact split-brain bug from #462: the constant used to ignore
    NIRA_HOME entirely. The constant is resolved once at import (the
    install-script model, where the env is set before the process starts), and
    every instance-level default goes through ``get_config_dir()`` so it honors
    the override. ``DEFAULT_CONFIG_DIR`` stays a real attribute so existing
    tests can ``monkeypatch.setattr`` it.
    """

    def test_constant_matches_resolver_at_import(self) -> None:
        from nira.core import config

        # The constant is the import-time resolution of the same function.
        assert config.DEFAULT_CONFIG_DIR == paths.get_config_dir()
        assert config.DEFAULT_CONFIG_PATH == paths.get_config_path()

    def test_constant_is_a_real_settable_attribute(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Install/CLI tests monkeypatch this attribute directly; it must be a
        # real module attribute (not __getattr__-only) for setattr/undo to work.
        from nira.core import config

        monkeypatch.setattr(config, "DEFAULT_CONFIG_DIR", tmp_path / "patched")
        assert config.DEFAULT_CONFIG_DIR == tmp_path / "patched"

    def test_dataclass_defaults_reflect_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Config dataclass field defaults must resolve under the override at
        # instantiation time, not freeze ~/.nira at import.
        _clear_env(monkeypatch)
        from nira.core.config import SessionConfig, StorageConfig

        monkeypatch.setenv("NIRA_HOME", str(tmp_path / "oj"))
        root = (tmp_path / "oj").resolve()
        assert StorageConfig().db_path == str(root / "memory.db")
        assert SessionConfig().db_path == str(root / "sessions.db")

    def test_downstream_consumer_honors_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # End-to-end: a non-config subsystem (credentials) resolves under the
        # custom root, proving the override is no longer split-brain.
        _clear_env(monkeypatch)
        from nira.core import credentials

        monkeypatch.setenv("NIRA_HOME", str(tmp_path / "oj"))
        assert (
            credentials._default_path()
            == (tmp_path / "oj" / "credentials.toml").resolve()
        )

    def test_constant_never_resolves_to_the_real_developer_home(self) -> None:
        """Regression for #787: DEFAULT_CONFIG_DIR is resolved once, at the
        first import of nira.core.config anywhere in the test
        session -- which happens via tests/conftest.py, before any test
        body runs. If conftest.py doesn't set NIRA_HOME before that
        import, this constant (and the ~45 modules that reference it)
        permanently binds to the developer's real ~/.nira for the
        rest of the run, so tests touching e.g. AgentConfigEvolver or
        LearningOrchestrator read/write real files there.

        No monkeypatching here on purpose: this checks the *actual*
        session-wide value tests/conftest.py's import-time setup already
        produced, not a value manufactured by this test.
        """
        from nira.core.config import DEFAULT_CONFIG_DIR

        real_home = (Path.home() / ".nira").resolve()
        assert DEFAULT_CONFIG_DIR != real_home
        assert "NIRA_CONFIG" not in os.environ


class TestMigrateLegacyHome:
    """Adoption of a legacy ``~/.openjarvis`` root."""

    def test_copies_state_and_leaves_legacy_install_intact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        legacy = tmp_path / ".openjarvis"
        (legacy / "skills").mkdir(parents=True)
        (legacy / "config.toml").write_text("x = 1", encoding="utf-8")
        (legacy / "memory.db").write_bytes(b"sqlite")
        (legacy / "memory.db-wal").write_bytes(b"wal")

        result = paths.migrate_legacy_home()

        assert result == tmp_path / ".nira"
        assert (tmp_path / ".nira" / "config.toml").read_text(
            encoding="utf-8"
        ) == "x = 1"
        assert (tmp_path / ".nira" / "skills").is_dir()
        assert (tmp_path / ".nira" / paths._MIGRATION_MARKER).exists()
        # WAL sidecars ride along, or committed transactions would be dropped.
        assert (tmp_path / ".nira" / "memory.db-wal").read_bytes() == b"wal"
        # Copy, not move: the old install must keep working.
        assert legacy.is_dir()
        assert (legacy / "config.toml").exists()

    def test_excludes_install_artifacts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Install artifacts must not follow the state into the new root.

        A virtualenv bakes its own absolute path into pyvenv.cfg and every
        console-script shebang, so a copied one is broken on arrival — and the
        original keeps working only because we left it alone. The installer's
        source checkout and logs are equally not user state, and stale
        server.pid/lock entries would describe a process that is not ours.
        """
        _clear_env(monkeypatch)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        legacy = tmp_path / ".openjarvis"
        legacy.mkdir()
        (legacy / "config.toml").write_text("keep", encoding="utf-8")
        for artifact in (".venv", "src", ".scripts", ".state", "cache"):
            (legacy / artifact).mkdir()
            (legacy / artifact / "payload").write_text("no", encoding="utf-8")
        for runtime in ("server.pid", "server.lock", "server.log"):
            (legacy / runtime).write_text("stale", encoding="utf-8")

        result = paths.migrate_legacy_home()
        assert result is not None

        assert (result / "config.toml").read_text(encoding="utf-8") == "keep"
        for excluded in paths._LEGACY_INSTALL_ARTIFACTS:
            assert not (result / excluded).exists(), f"{excluded} must not be copied"

    def test_is_idempotent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        (tmp_path / ".openjarvis").mkdir()

        assert paths.migrate_legacy_home() is not None
        # Second call has nothing to do and must not raise.
        assert paths.migrate_legacy_home() is None

    def test_never_clobbers_an_existing_nira_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        legacy = tmp_path / ".openjarvis"
        legacy.mkdir()
        (legacy / "config.toml").write_text("old", encoding="utf-8")
        current = tmp_path / ".nira"
        current.mkdir()
        (current / "config.toml").write_text("new", encoding="utf-8")

        assert paths.migrate_legacy_home() is None
        assert (current / "config.toml").read_text(encoding="utf-8") == "new"
        assert legacy.exists(), "legacy root must be left intact, not merged"

    def test_noop_when_no_legacy_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        assert paths.migrate_legacy_home() is None
        assert not (tmp_path / ".nira").exists()

    def test_skips_symlinked_legacy_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Renaming a symlink moves the link and orphans its target, so a
        # symlinked legacy root must be left for the user to resolve.
        _clear_env(monkeypatch)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        real = tmp_path / "elsewhere"
        real.mkdir()
        (tmp_path / ".openjarvis").symlink_to(real, target_is_directory=True)

        assert paths.migrate_legacy_home() is None
        assert (tmp_path / ".openjarvis").is_symlink()

    @pytest.mark.parametrize("var", ["NIRA_HOME", "XDG_DATA_HOME"])
    def test_declines_when_home_is_overridden(
        self, var: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # An explicit override means the user chose a root; silently moving
        # ~/.openjarvis would migrate into a path they are not using.
        _clear_env(monkeypatch)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        (tmp_path / ".openjarvis").mkdir()
        monkeypatch.setenv(var, str(tmp_path / "chosen"))

        assert paths.migrate_legacy_home() is None
        assert (tmp_path / ".openjarvis").is_dir()
