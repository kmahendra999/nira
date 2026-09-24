"""Write settings back into ``config.toml`` without losing the file.

The UI and the CLI both need to persist a handful of user choices — is memory
on, which tailnet address the phone should dial — and a config file is the only
place that survives a restart. Editing it by hand is where this goes wrong:
``~/.nira/config.toml`` is a file people read and comment, and a naive
``toml.dump(load(...))`` round-trip silently deletes every comment in it.

So: tomlkit (a hard dependency, and it preserves comments, ordering and
whitespace), plus an atomic replace so a crash mid-write cannot leave a
truncated config behind.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, Optional

import tomlkit

from nira.core.config import get_config_dir

__all__ = ["config_path", "read_config_document", "update_config_section"]


def config_path() -> Path:
    """Return the path of the config file Nira actually loads."""
    override = os.environ.get("NIRA_CONFIG", "").strip()
    if override:
        return Path(override).expanduser()
    return get_config_dir() / "config.toml"


def read_config_document(path: Optional[Path] = None) -> tomlkit.TOMLDocument:
    """Parse ``path`` (default: the live config) into an editable document."""
    target = path or config_path()
    if not target.exists():
        return tomlkit.document()
    try:
        return tomlkit.parse(target.read_text(encoding="utf-8"))
    except Exception:
        # A config we cannot parse is not a config we may rewrite: returning a
        # fresh document here would let the caller replace a hand-edited file
        # that merely has a typo in an unrelated section.
        raise


def update_config_section(
    section: str,
    values: Mapping[str, Any],
    *,
    path: Optional[Path] = None,
) -> Path:
    """Merge ``values`` into ``[section]`` of the config file and save it.

    ``section`` may be dotted (``"server.auth"``), in which case the nested
    tables are created as needed. A value of ``None`` removes that key, which
    is how a caller says "go back to the built-in default" rather than pinning
    the default into the file where a later release could not change it.

    Returns the path written.
    """
    target = path or config_path()
    doc = read_config_document(target)

    table: Any = doc
    for part in section.split("."):
        existing = table.get(part)
        if not isinstance(existing, (dict, tomlkit.items.Table)):
            existing = tomlkit.table()
            table[part] = existing
        table = existing

    for key, value in values.items():
        if value is None:
            table.pop(key, None)
        else:
            table[key] = value

    rendered = tomlkit.dumps(doc)
    target.parent.mkdir(parents=True, exist_ok=True)

    # Atomic: write beside the target on the same filesystem, then rename over
    # it. os.replace is atomic on POSIX and on Windows, so a reader either sees
    # the whole old file or the whole new one — never a half-written config.
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

    # load_config is lru_cached, so without this the process that just wrote
    # the file keeps reading the old values — `nira network set` reported the
    # setting it had replaced, and every later command in that process worked
    # from the stale config. Invalidate here rather than at each call site:
    # a caller that forgets gets a silent wrong answer, not an error.
    _invalidate_config_cache()

    return target


def _invalidate_config_cache() -> None:
    from nira.core.config import clear_config_cache

    clear_config_cache()
