"""Producing the signatures the loader checks.

Phase 13 made skill signature verification reachable: point
``security.signing_key_path`` at an Ed25519 public key and a manifest must
carry a valid signature from it. That left the feature usable only by someone
who already had signing tooling of their own — there was no way, inside Nira,
to make a signature for it to check.

The manifest is edited surgically rather than re-serialised. A ``skill.toml``
is written by hand: it has comments, ordering and formatting that its author
chose, and a round-trip through a TOML writer would quietly discard all of it
to change one line.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple

__all__ = [
    "SIGNATURE_KEY",
    "apply_signature",
    "manifest_path_for",
    "manifest_paths_under",
    "sign_manifest_file",
]

SIGNATURE_KEY = "signature"

# The [skill] table header, and the start of any following table. A signature
# written outside [skill] is not read, so both ends have to be known.
_SKILL_TABLE = re.compile(r"^\s*\[skill\]\s*$", re.M)
_ANY_TABLE = re.compile(r"^\s*\[\[?[^\]]+\]\]?\s*$", re.M)
_EXISTING = re.compile(rf"^\s*{SIGNATURE_KEY}\s*=.*$", re.M)


def manifest_path_for(target: Path) -> Optional[Path]:
    """The ``skill.toml`` for *target*, whether it names the file or its folder.

    Only TOML: ``SKILL.md`` has no field to carry a signature, and silently
    signing the TOML beside it would sign something the user did not point at.
    """
    target = Path(target).expanduser()
    if target.is_file():
        return target if target.suffix == ".toml" else None
    candidate = target / "skill.toml"
    return candidate if candidate.exists() else None


def manifest_paths_under(root: Path) -> list[Path]:
    """Every ``skill.toml`` at or below *root*, in a stable order.

    Someone maintaining a set of skills signs a directory, not a file at a
    time: the one that gets forgotten is the one that stops loading, and it
    stops loading at the moment somebody else tries to use it.

    A file argument is returned as-is when it is TOML, so callers can pass
    either without branching.
    """
    root = Path(root).expanduser()
    if root.is_file():
        return [root] if root.suffix == ".toml" else []
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("skill.toml") if p.is_file())


def _skill_table_span(text: str) -> Optional[Tuple[int, int]]:
    """Where the ``[skill]`` table's body starts and ends."""
    header = _SKILL_TABLE.search(text)
    if header is None:
        return None
    start = header.end()
    following = _ANY_TABLE.search(text, start)
    return start, following.start() if following else len(text)


def apply_signature(text: str, signature: str) -> str:
    """Return *text* with ``signature`` set inside its ``[skill]`` table.

    Replaces an existing signature in place, so re-signing an edited skill
    does not leave the old one behind for the loader to check against.
    """
    span = _skill_table_span(text)
    if span is None:
        raise ValueError("No [skill] table found; this is not a skill manifest.")
    start, end = span
    body = text[start:end]
    line = f'{SIGNATURE_KEY} = "{signature}"'

    existing = _EXISTING.search(body)
    if existing:
        updated = body[: existing.start()] + line + body[existing.end() :]
        return text[:start] + updated + text[end:]

    # Append to the end of the table's own lines, before whatever follows, so
    # it lands inside [skill] rather than in the next table.
    trimmed = body.rstrip("\n")
    trailing = body[len(trimmed) :]
    return text[:start] + trimmed + "\n" + line + trailing + text[end:]


def sign_manifest_file(path: Path, private_key: bytes) -> str:
    """Sign the manifest at *path* in place, returning the signature.

    The signature covers the manifest *without* it, so signing is idempotent:
    signing an already-signed file produces the same signature rather than
    signing the previous signature.
    """
    from nira.security.signing import sign_b64
    from nira.skills.loader import load_skill

    path = Path(path)
    manifest = load_skill(path)
    signature = sign_b64(manifest.manifest_bytes(), private_key)
    path.write_text(
        apply_signature(path.read_text(encoding="utf-8"), signature),
        encoding="utf-8",
    )
    return signature
