"""SQLite-backed registry of the projects Nira can work on."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS projects (
    id              TEXT PRIMARY KEY,
    name            TEXT    NOT NULL,
    path            TEXT    NOT NULL,
    default_agent   TEXT    NOT NULL DEFAULT 'claude_code',
    last_session_id TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);
"""

# One project per directory. Registering the same path twice under different
# names would give two independent session histories for one codebase, and
# whichever the user happened to name would forget what the other had done.
_CREATE_PATH_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_path ON projects(path)"
)

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(name: str) -> str:
    """Return a stable id for *name* (``My App`` -> ``my-app``)."""
    return _SLUG_STRIP.sub("-", name.strip().lower()).strip("-")


@dataclass
class Project:
    """A directory Nira can be asked to work in."""

    id: str
    name: str
    path: str
    default_agent: str = "claude_code"
    last_session_id: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "default_agent": self.default_agent,
            "last_session_id": self.last_session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @property
    def exists(self) -> bool:
        """Whether the project directory is still present on this machine."""
        return Path(self.path).is_dir()


class ProjectStore:
    """CRUD for the project registry."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_CREATE_TABLE)
        self._conn.execute(_CREATE_PATH_INDEX)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- writes ---------------------------------------------------------

    def add(
        self,
        name: str,
        path: str | Path,
        *,
        default_agent: str = "claude_code",
    ) -> Project:
        """Register *path* under *name*, replacing any existing entry for it.

        The path is resolved and must be a real directory: a registry entry
        pointing nowhere would fail later, inside an agent run, where the
        cause is far less obvious than it is here.
        """
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError(f"Not a directory: {resolved}")

        project_id = slugify(name)
        if not project_id:
            raise ValueError(f"Project name has no usable characters: {name!r}")

        existing = self.get_by_path(str(resolved))
        created = existing.created_at if existing else _now()
        session = existing.last_session_id if existing else ""

        project = Project(
            id=project_id,
            name=name.strip(),
            path=str(resolved),
            default_agent=default_agent,
            last_session_id=session,
            created_at=created,
            updated_at=_now(),
        )
        # Clear any row holding this path under a different id, so the unique
        # path index cannot reject a rename.
        self._conn.execute(
            "DELETE FROM projects WHERE path = ? AND id != ?",
            (project.path, project.id),
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO projects "
            "(id, name, path, default_agent, last_session_id, "
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                project.id,
                project.name,
                project.path,
                project.default_agent,
                project.last_session_id,
                project.created_at,
                project.updated_at,
            ),
        )
        self._conn.commit()
        return project

    def remember_session(self, project_id: str, session_id: str) -> None:
        """Record the agent session last used for *project_id*.

        This is what lets a follow-up continue where the previous run stopped
        rather than reintroducing the codebase from scratch every time.
        """
        self._conn.execute(
            "UPDATE projects SET last_session_id = ?, updated_at = ? WHERE id = ?",
            (session_id, _now(), project_id),
        )
        self._conn.commit()

    def remove(self, project_id: str) -> bool:
        """Forget a project. Returns False if it was not registered."""
        cursor = self._conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    # -- reads ----------------------------------------------------------

    def get(self, project_id: str) -> Optional[Project]:
        row = self._conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return self._row_to_project(row) if row else None

    def get_by_path(self, path: str | Path) -> Optional[Project]:
        resolved = str(Path(path).expanduser().resolve())
        row = self._conn.execute(
            "SELECT * FROM projects WHERE path = ?", (resolved,)
        ).fetchone()
        return self._row_to_project(row) if row else None

    def resolve(self, reference: str) -> Optional[Project]:
        """Find a project by id, exact name, or unambiguous partial name.

        Spoken and typed requests name projects loosely ("work on the api
        one"), so an exact-id lookup alone would reject most of what a user
        actually says. A partial match that hits more than one project returns
        nothing rather than guessing, because picking the wrong codebase is
        considerably worse than asking again.
        """
        reference = reference.strip()
        if not reference:
            return None

        direct = self.get(slugify(reference))
        if direct is not None:
            return direct

        lowered = reference.lower()
        candidates = [
            project
            for project in self.list()
            if lowered in project.name.lower() or lowered in project.id
        ]
        return candidates[0] if len(candidates) == 1 else None

    def list(self) -> List[Project]:
        rows = self._conn.execute(
            "SELECT * FROM projects ORDER BY updated_at DESC"
        ).fetchall()
        return [self._row_to_project(row) for row in rows]

    @staticmethod
    def _row_to_project(row: sqlite3.Row) -> Project:
        return Project(
            id=row["id"],
            name=row["name"],
            path=row["path"],
            default_agent=row["default_agent"],
            last_session_id=row["last_session_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


__all__ = ["Project", "ProjectStore", "slugify"]
