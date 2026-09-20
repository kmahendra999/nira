"""SQLite registry of the devices allowed to talk to this Nira."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_KEY_PREFIX = "nira_dk_"
_ENROLL_PREFIX = "nira_en_"

# What a device is allowed to do. Deliberately small — a scope nobody enforces
# is worse than no scope, because it reads like a guarantee.
SCOPE_ASK = "ask"  # send prompts, start agent runs
SCOPE_WATCH = "watch"  # read state and subscribe to progress
SCOPE_APPROVE = "approve"  # answer human-in-the-loop approval requests
SCOPE_ADMIN = "admin"  # manage devices, config, lifecycle

ALL_SCOPES = (SCOPE_ASK, SCOPE_WATCH, SCOPE_APPROVE, SCOPE_ADMIN)

# A newly paired device can ask and watch. Approving a destructive tool call
# and administering the mesh are opt-in: pairing a phone should not silently
# hand it the ability to say yes to anything.
DEFAULT_SCOPES = (SCOPE_ASK, SCOPE_WATCH)

_ENROLLMENT_TTL = timedelta(minutes=10)

_CREATE_DEVICES = """\
CREATE TABLE IF NOT EXISTS devices (
    id          TEXT PRIMARY KEY,
    name        TEXT    NOT NULL,
    platform    TEXT    NOT NULL DEFAULT 'unknown',
    key_hash    TEXT    NOT NULL UNIQUE,
    scopes      TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL,
    last_seen_at TEXT   NOT NULL DEFAULT '',
    revoked_at  TEXT    NOT NULL DEFAULT ''
);
"""

_CREATE_ENROLLMENTS = """\
CREATE TABLE IF NOT EXISTS enrollments (
    token_hash  TEXT PRIMARY KEY,
    name        TEXT    NOT NULL,
    scopes      TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL,
    expires_at  TEXT    NOT NULL,
    used_at     TEXT    NOT NULL DEFAULT ''
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def hash_secret(secret: str) -> str:
    """Return the stored form of a device key or enrollment token.

    A plain SHA-256, not a password KDF, and that is the right call here rather
    than a shortcut. These secrets are 256 bits of CSPRNG output, so there is
    no dictionary to run and nothing for a slow hash to buy; the reason to hash
    at all is that a leaked database must not hand over working keys.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def generate_device_key() -> str:
    return f"{_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def generate_enrollment_token() -> str:
    return f"{_ENROLL_PREFIX}{secrets.token_urlsafe(24)}"


def normalize_scopes(scopes: Sequence[str] | str | None) -> List[str]:
    """Return a sorted, de-duplicated list of recognised scopes."""
    if scopes is None:
        return []
    if isinstance(scopes, str):
        raw = scopes.split(",")
    else:
        raw = list(scopes)
    seen = {item.strip().lower() for item in raw if item and item.strip()}
    unknown = seen - set(ALL_SCOPES)
    if unknown:
        raise ValueError(f"Unknown scope(s): {', '.join(sorted(unknown))}")
    return sorted(seen)


@dataclass
class Device:
    """A paired client, and what it is allowed to do."""

    id: str
    name: str
    platform: str = "unknown"
    scopes: List[str] = field(default_factory=list)
    created_at: str = ""
    last_seen_at: str = ""
    revoked_at: str = ""

    @property
    def revoked(self) -> bool:
        return bool(self.revoked_at)

    def can(self, scope: str) -> bool:
        """Whether this device holds *scope*.

        A revoked device holds nothing, regardless of what its row still says
        — revocation has to be the first question, not one condition among
        several that a caller might forget to combine.
        """
        if self.revoked:
            return False
        return scope in self.scopes or SCOPE_ADMIN in self.scopes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "platform": self.platform,
            "scopes": list(self.scopes),
            "created_at": self.created_at,
            "last_seen_at": self.last_seen_at,
            "revoked": self.revoked,
        }


@dataclass
class Enrollment:
    """A short-lived invitation for one device to claim a key."""

    token: str
    """The secret to carry to the device. Never stored; only its hash is."""

    name: str
    scopes: List[str]
    expires_at: str


class DeviceStore:
    """Registry of paired devices and pending enrollments."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_CREATE_DEVICES)
        self._conn.execute(_CREATE_ENROLLMENTS)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- pairing --------------------------------------------------------

    def create_enrollment(
        self,
        name: str,
        *,
        scopes: Sequence[str] | None = None,
        ttl: timedelta = _ENROLLMENT_TTL,
    ) -> Enrollment:
        """Mint a single-use invitation for a new device.

        Short-lived and one-shot on purpose: the token travels out of band (a
        QR code on screen), so it is briefly visible to anyone who can see the
        screen. A ten-minute window that closes on first use keeps a shoulder
        surfer from claiming it later.
        """
        token = generate_enrollment_token()
        granted = (
            normalize_scopes(scopes) if scopes is not None else list(DEFAULT_SCOPES)
        )
        now = _now()
        expires = now + ttl
        self._conn.execute(
            "INSERT INTO enrollments "
            "(token_hash, name, scopes, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (
                hash_secret(token),
                name.strip(),
                ",".join(granted),
                _iso(now),
                _iso(expires),
            ),
        )
        self._conn.commit()
        return Enrollment(
            token=token, name=name.strip(), scopes=granted, expires_at=_iso(expires)
        )

    def redeem_enrollment(
        self, token: str, *, platform: str = "unknown"
    ) -> tuple[Device, str]:
        """Exchange a valid invitation for a device and its own key.

        Returns the device and its key. The key is returned once and never
        recoverable — only its hash is kept, so a lost key means re-pairing
        rather than reading it back out of the database.
        """
        row = self._conn.execute(
            "SELECT * FROM enrollments WHERE token_hash = ?", (hash_secret(token),)
        ).fetchone()
        if row is None:
            raise ValueError("Unknown enrollment token")
        if row["used_at"]:
            raise ValueError("Enrollment token already used")
        if datetime.fromisoformat(row["expires_at"]) < _now():
            raise ValueError("Enrollment token expired")

        key = generate_device_key()
        device_id = f"dev_{secrets.token_hex(8)}"
        now = _iso(_now())
        self._conn.execute(
            "INSERT INTO devices "
            "(id, name, platform, key_hash, scopes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (device_id, row["name"], platform, hash_secret(key), row["scopes"], now),
        )
        self._conn.execute(
            "UPDATE enrollments SET used_at = ? WHERE token_hash = ?",
            (now, row["token_hash"]),
        )
        self._conn.commit()
        return (
            Device(
                id=device_id,
                name=row["name"],
                platform=platform,
                scopes=normalize_scopes(row["scopes"]),
                created_at=now,
            ),
            key,
        )

    def purge_expired_enrollments(self) -> int:
        """Drop invitations that can no longer be redeemed."""
        cursor = self._conn.execute(
            "DELETE FROM enrollments WHERE used_at != '' OR expires_at < ?",
            (_iso(_now()),),
        )
        self._conn.commit()
        return cursor.rowcount

    # -- authentication -------------------------------------------------

    def authenticate(self, key: str) -> Optional[Device]:
        """Return the device holding *key*, or None.

        A revoked device authenticates as nothing at all rather than as itself
        with no scopes: every caller then fails closed by default, instead of
        depending on each one remembering to check.
        """
        if not key:
            return None
        row = self._conn.execute(
            "SELECT * FROM devices WHERE key_hash = ?", (hash_secret(key),)
        ).fetchone()
        if row is None or row["revoked_at"]:
            return None
        return self._row_to_device(row)

    def touch(self, device_id: str) -> None:
        """Record that a device was just seen, for the pairing list."""
        self._conn.execute(
            "UPDATE devices SET last_seen_at = ? WHERE id = ?",
            (_iso(_now()), device_id),
        )
        self._conn.commit()

    # -- management -----------------------------------------------------

    def revoke(self, device_id: str) -> bool:
        """Revoke a device. Returns False if it was unknown or already revoked.

        Revoked rather than deleted: the audit trail should still be able to
        say which device did what, and a deleted row makes past activity
        anonymous.
        """
        cursor = self._conn.execute(
            "UPDATE devices SET revoked_at = ? WHERE id = ? AND revoked_at = ''",
            (_iso(_now()), device_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def set_scopes(self, device_id: str, scopes: Sequence[str]) -> bool:
        granted = normalize_scopes(scopes)
        cursor = self._conn.execute(
            "UPDATE devices SET scopes = ? WHERE id = ? AND revoked_at = ''",
            (",".join(granted), device_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def get(self, device_id: str) -> Optional[Device]:
        row = self._conn.execute(
            "SELECT * FROM devices WHERE id = ?", (device_id,)
        ).fetchone()
        return self._row_to_device(row) if row else None

    def list(self, *, include_revoked: bool = False) -> List[Device]:
        query = "SELECT * FROM devices"
        if not include_revoked:
            query += " WHERE revoked_at = ''"
        query += " ORDER BY created_at DESC"
        return [self._row_to_device(row) for row in self._conn.execute(query)]

    @staticmethod
    def _row_to_device(row: sqlite3.Row) -> Device:
        return Device(
            id=row["id"],
            name=row["name"],
            platform=row["platform"],
            scopes=normalize_scopes(row["scopes"]),
            created_at=row["created_at"],
            last_seen_at=row["last_seen_at"],
            revoked_at=row["revoked_at"],
        )


__all__ = [
    "ALL_SCOPES",
    "DEFAULT_SCOPES",
    "SCOPE_ADMIN",
    "SCOPE_APPROVE",
    "SCOPE_ASK",
    "SCOPE_WATCH",
    "Device",
    "DeviceStore",
    "Enrollment",
    "generate_device_key",
    "hash_secret",
    "normalize_scopes",
]
