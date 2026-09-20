"""Incremental sentence segmentation for speaking a reply while it generates.

Voice mode used to wait for the entire completion before synthesising any of
it, so time-to-first-audio was the cost of the whole reply. Splitting the token
stream into speakable clauses lets synthesis start after the first sentence and
overlap generation with playback, which is where nearly all of the felt latency
goes.

The segmentation is deliberately conservative. Speaking a fragment that the
model has not finished is worse than waiting one more token: a clause cut mid
sentence gets the wrong intonation, and once audio is playing it cannot be
taken back.
"""

from __future__ import annotations

import re
from typing import List

from nira.speech.text_prep import has_speakable_content

# Sentence-final punctuation that is *followed by whitespace*.
#
# Deliberately not anchored to end-of-buffer. Mid-stream the buffer ends
# wherever the last token happened to land, so an end-anchored match fires on
# the "3." of "3.14" and on the '"go.' of '"go."' before the disambiguating
# character has arrived — a premature cut, which is the one failure this
# splitter must not have. Waiting for the following space costs one token.
# The tail left over at the end of a stream is handled by ``flush``.
_BOUNDARY = re.compile(r"[.!?…]+[\"')\]]*(?=\s)")

# Clause break used only to get the FIRST utterance out sooner.
_CLAUSE = re.compile(r"[,;:—–][\"')\]]*(?=\s)")

# Trailing tokens that look like a sentence end but are not, so the buffer must
# keep growing. Ordered longest-first so "e.g." wins over "g.".
_ABBREVIATIONS = (
    "e.g.",
    "i.e.",
    "etc.",
    "vs.",
    "approx.",
    "Dr.",
    "Mr.",
    "Mrs.",
    "Ms.",
    "Prof.",
    "St.",
    "Fig.",
    "No.",
    "cf.",
    "al.",
)

# A list enumerator: "1." or "a)" at the start of a line. Anchored to the line
# start on purpose — matching after any whitespace would also suppress a
# sentence that simply ends in a small number ("The answer is 42.").
#
# Decimals need no rule at all: the period in "3.14" is followed by a digit, so
# it never satisfies the boundary's whitespace lookahead in the first place.
_ENUMERATOR = re.compile(r"(?:^|\n)[ \t]*(?:\d{1,3}|[A-Za-z])[.)]$")

# An initial: "J." and "R." in "J. R. Tolkien".
_INITIAL = re.compile(r"(?:^|\s)[A-Z][.)]$")


def _is_false_boundary(buffer: str, end: int) -> bool:
    """True when the punctuation at *end* does not really end a sentence."""
    head = buffer[:end]
    stripped = head.rstrip()
    if _ENUMERATOR.search(stripped):
        return True
    if _INITIAL.search(stripped):
        return True
    lowered = stripped.lower()
    return any(lowered.endswith(abbr.lower()) for abbr in _ABBREVIATIONS)


class SentenceAccumulator:
    """Turn a stream of tokens into complete, speakable utterances.

    Feed tokens with :meth:`push`; it returns the utterances that became
    complete. Call :meth:`flush` at the end of the stream for the remainder.
    """

    def __init__(
        self,
        *,
        max_chars: int = 240,
        first_chunk_chars: int = 60,
    ) -> None:
        """
        ``max_chars`` force-emits a run-on that never punctuates, so a model
        writing a long unbroken line cannot stall audio indefinitely.

        ``first_chunk_chars`` lets the *first* utterance break at a clause
        boundary (a comma or semicolon) once it is at least this long. Only the
        first, and only because time-to-first-audio dominates the impression of
        responsiveness; later chunks wait for real sentence ends so prosody
        stays natural.
        """
        self._buffer = ""
        self._max_chars = max_chars
        self._first_chunk_chars = first_chunk_chars
        self._emitted = 0

    @property
    def pending(self) -> str:
        """Text held back, waiting for a boundary."""
        return self._buffer

    def push(self, token: str) -> List[str]:
        """Add *token* and return any utterances that are now complete."""
        if not token:
            return []
        self._buffer += token
        return self._drain()

    def flush(self) -> List[str]:
        """Return whatever is left, complete or not."""
        remainder = self._buffer.strip()
        self._buffer = ""
        if not has_speakable_content(remainder):
            return []
        self._emitted += 1
        return [remainder]

    def _drain(self) -> List[str]:
        out: List[str] = []
        while True:
            chunk = self._take_one()
            if chunk is None:
                return out
            out.append(chunk)

    def _take_one(self) -> str | None:
        cut = self._find_cut()
        if cut is None:
            return None
        chunk = self._buffer[:cut].strip()
        self._buffer = self._buffer[cut:].lstrip()
        if not has_speakable_content(chunk):
            # Punctuation on its own ("...", a stray bullet): drop it rather
            # than handing a synthesiser something it cannot pronounce, but
            # keep scanning — the rest of the buffer may hold a real sentence.
            return self._take_one()
        self._emitted += 1
        return chunk

    def _find_cut(self) -> int | None:
        for match in _BOUNDARY.finditer(self._buffer):
            if not _is_false_boundary(self._buffer, match.end()):
                return match.end()

        # A blank line ends a paragraph even without punctuation — headings and
        # list items arrive that way.
        para = self._buffer.find("\n\n")
        if para != -1:
            return para

        if self._emitted == 0 and len(self._buffer) >= self._first_chunk_chars:
            clause = None
            for match in _CLAUSE.finditer(self._buffer):
                clause = match.end()
                break
            if clause is not None:
                return clause

        if len(self._buffer) >= self._max_chars:
            # Break at the last whitespace so a word is not split in half.
            space = self._buffer.rfind(" ", 0, self._max_chars)
            return space if space > 0 else self._max_chars

        return None


__all__ = ["SentenceAccumulator"]
