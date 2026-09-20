"""Turn a model's markdown reply into something worth hearing.

Voice mode fed raw markdown straight to the synthesiser, so a reply with a
fenced code block had the code read out character by character, links were read
as their URLs, and every ``**`` and ``##`` was pronounced or mangled depending
on the backend.

The rules here are about *speech*, not rendering: anything that only carries
meaning visually is dropped rather than flattened. A code block is the clearest
case — hearing forty seconds of punctuation is worse than hearing nothing, so it
becomes a short spoken placeholder instead.
"""

from __future__ import annotations

import re

_FENCED_CODE = re.compile(r"```[^\n]*\n.*?(?:```|\Z)", re.DOTALL)
_INDENTED_CODE = re.compile(r"(?:^(?: {4}|\t)[^\n]*\n?)+", re.MULTILINE)
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_AUTOLINK = re.compile(r"<(https?://[^>]+)>")
_BARE_URL = re.compile(r"https?://\S+")
_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]*", re.MULTILINE)
_BLOCKQUOTE = re.compile(r"^[ \t]{0,3}>[ \t]?", re.MULTILINE)
_BULLET = re.compile(r"^[ \t]*[-*+•][ \t]+", re.MULTILINE)
_RULE = re.compile(r"^[ \t]{0,3}(?:[-*_][ \t]?){3,}[ \t]*$", re.MULTILINE)
_TABLE_DIVIDER = re.compile(r"^[ \t]*\|?[ \t:|-]+\|[ \t:|-]*$", re.MULTILINE)
_TABLE_PIPES = re.compile(r"^[ \t]*\|(.+)\|[ \t]*$", re.MULTILINE)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_EMPHASIS = re.compile(r"(\*{1,3}|_{1,3})(\S(?:.*?\S)?)\1", re.DOTALL)
_STRIKETHROUGH = re.compile(r"~~(.+?)~~", re.DOTALL)
_BLANK_RUN = re.compile(r"\n{3,}")
_SPACE_RUN = re.compile(r"[ \t]{2,}")

_CODE_PLACEHOLDER = "(code block omitted)"


def _speak_table_row(match: "re.Match[str]") -> str:
    """Read a table row as a comma-separated list of its cells."""
    cells = [cell.strip() for cell in match.group(1).split("|")]
    return ", ".join(cell for cell in cells if cell)


def strip_markdown_for_speech(text: str) -> str:
    """Return *text* with markdown reduced to what makes sense spoken.

    Code blocks become a short placeholder, links keep their text and lose
    their URL, and structural markers (headings, bullets, rules, table pipes)
    are removed. Emphasis markers are dropped but the words they wrap are kept.
    """
    if not text:
        return ""

    out = _FENCED_CODE.sub(f"\n{_CODE_PLACEHOLDER}\n", text)
    # Only after fences are gone, so a fenced block's body is not matched twice.
    out = _INDENTED_CODE.sub(f"\n{_CODE_PLACEHOLDER}\n", out)

    out = _IMAGE.sub(r"\1", out)
    out = _LINK.sub(r"\1", out)
    # A URL read aloud is noise; its surrounding sentence carries the meaning.
    out = _AUTOLINK.sub("", out)
    out = _BARE_URL.sub("", out)

    out = _RULE.sub("", out)
    out = _TABLE_DIVIDER.sub("", out)
    out = _TABLE_PIPES.sub(_speak_table_row, out)
    out = _HEADING.sub("", out)
    out = _BLOCKQUOTE.sub("", out)
    out = _BULLET.sub("", out)

    out = _INLINE_CODE.sub(r"\1", out)
    out = _STRIKETHROUGH.sub(r"\1", out)
    # Repeated: ``**bold _and_ italic**`` needs more than one pass to unwrap.
    for _ in range(3):
        replaced = _EMPHASIS.sub(r"\2", out)
        if replaced == out:
            break
        out = replaced

    out = _SPACE_RUN.sub(" ", out)
    out = _BLANK_RUN.sub("\n\n", out)
    return out.strip()


def has_speakable_content(text: str) -> bool:
    """True when *text* holds anything a synthesiser could pronounce."""
    return any(ch.isalnum() for ch in text)


__all__ = ["has_speakable_content", "strip_markdown_for_speech"]
