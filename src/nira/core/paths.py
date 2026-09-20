"""Central, env-aware resolution of Nira's home directory.

Nira keeps all of its runtime state (config, databases, caches, logs,
credentials, skills, recipes, …) under a single root so it never clutters the
user's home directory beyond one directory. That root is resolved here, with
the following precedence (highest first):

1. ``$NIRA_HOME`` — explicit override (also honored by the shell
   installer, see ``scripts/install/install.sh``).
2. ``$XDG_DATA_HOME/nira`` — when ``$XDG_DATA_HOME`` is set, follow the
   XDG Base Directory spec by nesting a single ``nira`` directory under
   it. We deliberately use ONE directory rather than splitting across XDG
   config/data/cache so the install tree stays self-contained and relocatable.
3. ``~/.nira`` — the historical default. With no env vars set, the
   resolved path is exactly this, so existing installs are untouched.

``config.py`` re-exports :func:`get_config_dir` results through the legacy
``DEFAULT_CONFIG_DIR``/``DEFAULT_CONFIG_PATH`` names (computed dynamically) so
the ~45 modules that import those names keep working while honoring the
override. Modules that previously hardcoded ``Path.home() / ".nira"``
should call :func:`get_config_dir` (or :func:`get_data_dir` /
:func:`get_cache_dir`) instead.

Defense in depth: the resolved root must never live inside the Nira
source tree (a misconfigured ``$NIRA_HOME`` pointing at the repo would
otherwise scatter runtime artifacts into the working tree). This mirrors the
guard in ``learning/spec_search/storage/paths.py`` and fails loudly per
REVIEW.md's no-silent-failure discipline.
"""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_DIR_NAME = ".nira"
_XDG_SUBDIR_NAME = "nira"

# Pre-rename home directory. Nira was forked from OpenJarvis, whose root was
# ``~/.openjarvis``; installs predating the rename still hold all of the user's
# state (config, credentials, every SQLite database) there.
_LEGACY_DIR_NAME = ".openjarvis"
_MIGRATION_MARKER = ".migrated-from-openjarvis"


class ConfigurationError(RuntimeError):
    """Raised when the resolved home directory would violate isolation guarantees."""


def migrate_legacy_home() -> Path | None:
    """Move a pre-rename ``~/.openjarvis`` root to ``~/.nira``, once.

    Returns the new path when a migration happened, else ``None``.

    Deliberately conservative — it acts only when all of the following hold:

    * no ``$NIRA_HOME`` / ``$XDG_DATA_HOME`` override is set, so we are
      reasoning about the default location and not a path the user chose;
    * ``~/.openjarvis`` exists and is a real directory, not a symlink (a
      symlink would make ``rename`` move the link and orphan the target);
    * ``~/.nira`` does not exist, so we can never merge two roots or clobber
      state that a fresh install already wrote.

    Uses ``rename`` rather than a copy: the tree routinely holds gigabytes of
    skills and model data, and rename is atomic within a filesystem, so an
    interrupted migration cannot leave a half-copied root. Cross-device moves
    raise ``OSError``, which is surfaced rather than swallowed — per REVIEW.md's
    no-silent-failure discipline, losing track of the user's data is exactly the
    kind of thing that must fail loudly.
    """
    if os.environ.get("NIRA_HOME") or os.environ.get("XDG_DATA_HOME"):
        return None

    home = Path.home()
    legacy = home / _LEGACY_DIR_NAME
    current = home / _DEFAULT_DIR_NAME

    if current.exists() or not legacy.is_dir() or legacy.is_symlink():
        return None

    legacy.rename(current)
    try:
        (current / _MIGRATION_MARKER).write_text(
            f"Migrated from {legacy} during the OpenJarvis -> Nira rename.\n",
            encoding="utf-8",
        )
    except OSError:
        # The move is what matters and it already succeeded; a missing
        # breadcrumb must not turn a good migration into a failure.
        pass
    return current


def _find_source_root() -> Path | None:
    """Walk upward from this module to find the Nira source root.

    Returns the directory containing the Nira ``pyproject.toml`` (the one
    whose ``name = "nira"``), or ``None`` when running from an installed
    wheel rather than a source checkout.
    """
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        py = candidate / "pyproject.toml"
        if py.exists():
            try:
                content = py.read_text(encoding="utf-8")
            except OSError:
                continue
            if 'name = "nira"' in content.lower():
                return candidate
    return None


def _reject_source_tree(path: Path) -> Path:
    """Raise if ``path`` resolves inside the Nira source tree."""
    source_root = _find_source_root()
    if source_root is not None:
        try:
            path.relative_to(source_root)
        except ValueError:
            pass  # Good — not inside the source tree.
        else:
            raise ConfigurationError(
                f"Nira home ({path}) is inside the source tree "
                f"({source_root}). Nira refuses to write runtime state "
                "inside its own repo. Set NIRA_HOME (or XDG_DATA_HOME) "
                "to a directory outside the repo (default: ~/.nira)."
            )
    return path


def get_config_dir() -> Path:
    """Resolve Nira's single root directory, honoring env overrides.

    Precedence: ``$NIRA_HOME`` > ``$XDG_DATA_HOME/nira`` >
    ``~/.nira``. The result is always absolute and is rejected if it
    falls inside the Nira source tree.
    """
    env_home = os.environ.get("NIRA_HOME")
    if env_home:
        resolved = Path(env_home).expanduser().resolve()
        return _reject_source_tree(resolved)

    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        resolved = (Path(xdg_data).expanduser() / _XDG_SUBDIR_NAME).resolve()
        return _reject_source_tree(resolved)

    return (Path.home() / _DEFAULT_DIR_NAME).resolve()


def get_config_path() -> Path:
    """Resolve the path to ``config.toml`` under the Nira root."""
    return get_config_dir() / "config.toml"


def get_data_dir() -> Path:
    """Resolve the directory for persistent data (databases, blobs, …).

    Consolidated under the single root; identical to :func:`get_config_dir`.
    Provided as a distinct name so call sites read intentionally.
    """
    return get_config_dir()


def get_cache_dir() -> Path:
    """Resolve the directory for regenerable caches (eval datasets, etc.).

    Lives at ``<root>/cache`` so caches stay inside the single Nira
    directory instead of scattering across ``~/.cache``.
    """
    return get_config_dir() / "cache"
