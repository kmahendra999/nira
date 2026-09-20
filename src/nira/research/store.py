"""Keeping a research report so the link to it leads somewhere.

``channel_agent`` answers a long query over Telegram, Slack or iMessage with a
preview and ``nira://research/<id>``. ``tauri.conf.json`` registers the scheme
with the OS, the desktop app parses the URL and knows what to do with it — and
the report itself was never written down. The full text went out of scope the
moment the preview was cut from it, and the id was a fresh uuid that referred
to nothing.

So the link was not merely unrenderable. It promised a reader something that
had already been thrown away, which is worse than not offering the link: a
missing feature is a disappointment, a broken promise is a bug report.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from nira.core.paths import get_config_dir

logger = logging.getLogger(__name__)

__all__ = ["ResearchReport", "ResearchStore"]

# Reports are long — a deep research answer runs to thousands of words — and
# they are read once, days at most after they arrive. Keeping every one
# forever would grow a database nobody prunes.
_DEFAULT_KEEP = 200


# Enough Markdown to make a preview readable. Not a parser: this runs on text
# nobody will see rendered, and the failure mode of getting it slightly wrong
# is a preview with a stray character rather than a broken document.
_FENCE = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_QUOTE = re.compile(r"^\s{0,3}>\s?", re.M)
_BULLET = re.compile(r"^\s*[-*+]\s+", re.M)
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+", re.M)
_RULE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$", re.M)
_EMPHASIS = re.compile(r"(\*{1,3}|_{1,3})(.+?)\1", re.S)
_WHITESPACE = re.compile(r"\s+")


def _as_prose(markdown: str) -> str:
    """Flatten Markdown to the words it contains."""
    text = _FENCE.sub(" ", markdown)
    text = _IMAGE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _RULE.sub(" ", text)
    text = _HEADING.sub("", text)
    text = _QUOTE.sub("", text)
    # Bullets become sentence breaks rather than vanishing, so a list does not
    # read as one run-on line.
    text = _BULLET.sub("\u00b7 ", text)
    text = _NUMBERED.sub("\u00b7 ", text)
    text = _EMPHASIS.sub(r"\2", text)
    return _WHITESPACE.sub(" ", text).strip()


@dataclass
class ResearchReport:
    """One completed piece of research, and where it came from."""

    id: str
    query: str
    report: str
    channel: str = ""
    created_at: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def preview(self, limit: int = 280) -> str:
        """The opening, as prose, for a list where the whole thing will not fit.

        Markdown is stripped rather than shown. A report opens with a heading
        and is full of emphasis, so a raw preview reads as
        ``# Title Running a model **trades** ...`` — the syntax crowds out the
        words in exactly the place where there is least room for them.
        """
        text = _as_prose(self.report)
        if len(text) <= limit:
            return text
        # Cut at a word so the preview does not end mid-token.
        cut = text[:limit].rsplit(" ", 1)[0]
        return f"{cut}…"

    def to_dict(self, *, full: bool = True) -> Dict[str, Any]:
        body = {
            "id": self.id,
            "query": self.query,
            "channel": self.channel,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }
        # A listing sends previews; asking for one report sends the report.
        # Returning every full text in a list would make the common case pay
        # for the rare one.
        body["report"] = self.report if full else ""
        body["preview"] = self.preview()
        return body


class ResearchStore:
    """SQLite-backed storage for research reports."""

    def __init__(
        self,
        db_path: Union[str, Path, None] = None,
        *,
        keep: int = _DEFAULT_KEEP,
    ) -> None:
        path = Path(db_path) if db_path else get_config_dir() / "research.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = path
        self._keep = max(1, keep)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS research_reports (
                id         TEXT PRIMARY KEY,
                query      TEXT NOT NULL,
                report     TEXT NOT NULL,
                channel    TEXT DEFAULT '',
                created_at REAL NOT NULL,
                metadata   TEXT DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_research_created
                ON research_reports(created_at DESC);
            """
        )
        self._conn.commit()

    def save(
        self,
        query: str,
        report: str,
        *,
        report_id: str = "",
        channel: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ResearchReport:
        """Store a report and return it, minting an id when none is given.

        The caller usually supplies the id, because it has already put that id
        in a message it is about to send — writing the report under a different
        one would recreate exactly the dangling link this store exists to fix.
        """
        entry = ResearchReport(
            id=report_id or uuid.uuid4().hex[:16],
            query=query,
            report=report,
            channel=channel,
            created_at=time.time(),
            metadata=metadata or {},
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO research_reports "
            "(id, query, report, channel, created_at, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                entry.id,
                entry.query,
                entry.report,
                entry.channel,
                entry.created_at,
                json.dumps(entry.metadata),
            ),
        )
        self._conn.commit()
        self._prune()
        return entry

    def get(self, report_id: str) -> Optional[ResearchReport]:
        row = self._conn.execute(
            "SELECT id, query, report, channel, created_at, metadata "
            "FROM research_reports WHERE id = ?",
            (report_id,),
        ).fetchone()
        return self._row(row) if row else None

    def recent(self, limit: int = 20) -> List[ResearchReport]:
        rows = self._conn.execute(
            "SELECT id, query, report, channel, created_at, metadata "
            "FROM research_reports ORDER BY created_at DESC LIMIT ?",
            (max(1, limit),),
        ).fetchall()
        return [self._row(row) for row in rows]

    def delete(self, report_id: str) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM research_reports WHERE id = ?", (report_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def count(self) -> int:
        return int(
            self._conn.execute("SELECT COUNT(*) FROM research_reports").fetchone()[0]
        )

    def close(self) -> None:
        self._conn.close()

    def _prune(self) -> None:
        """Drop the oldest beyond the keep limit.

        Deliberately by count rather than age: a report you were sent this
        morning should still open this evening, and someone who researches
        rarely should not lose their only report to a clock.
        """
        self._conn.execute(
            "DELETE FROM research_reports WHERE id NOT IN ("
            "  SELECT id FROM research_reports ORDER BY created_at DESC LIMIT ?"
            ")",
            (self._keep,),
        )
        self._conn.commit()

    @staticmethod
    def _row(row: tuple) -> ResearchReport:
        report_id, query, report, channel, created_at, metadata = row
        try:
            parsed = json.loads(metadata) if metadata else {}
        except ValueError:
            parsed = {}
        return ResearchReport(
            id=report_id,
            query=query,
            report=report,
            channel=channel or "",
            created_at=created_at or 0.0,
            metadata=parsed,
        )
