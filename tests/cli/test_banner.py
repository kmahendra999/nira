"""The banner says the product's name.

It said "OpenJarvis" until 2026-09-24 — every invocation of the CLI, in the
first thing printed. The rename rewrote the *comment* above the glyphs, which
went on to describe "a clearly readable capital J", a letter Nira does not
contain, and left the art itself untouched. A find-replace cannot see a word
drawn in slashes, and no test rendered it.

So this pins the art. Changing the wordmark should mean deliberately updating
a test, not discovering years later that the CLI greets people with the name
of the project this one was forked from.
"""

from __future__ import annotations

import re

from nira.cli._banner import _TAGLINE, _WORDMARK, print_banner

# "Nira" in the figlet "standard" font.
EXPECTED = (
    " _   _ _           ",
    "| \\ | (_)_ __ __ _ ",
    "|  \\| | | '__/ _` |",
    "| |\\  | | | | (_| |",
    "|_| \\_|_|_|  \\__,_|",
)


def test_the_wordmark_is_what_we_think_it_is() -> None:
    assert _WORDMARK == EXPECTED


def test_it_does_not_say_the_old_name() -> None:
    """The specific regression.

    `OpenJarvis` in this font is six lines with a `|_|` descender on the last,
    from the lowercase `p`. Nira has no descender, so the row count alone
    tells the two apart — and would have caught the original.
    """
    assert len(_WORDMARK) == 5, "the OpenJarvis wordmark was 6 rows"
    # Its unmistakable fragment: the `/ _ \` bowl of a capital O leading into
    # `_ __   ___ _ __`, which is `pen` plus the start of `Jarvis`.
    joined = "\n".join(_WORDMARK)
    assert "_ __   ___ _ __" not in joined


def test_every_row_is_the_same_width() -> None:
    """A ragged wordmark prints with a torn right edge."""
    widths = {len(row) for row in _WORDMARK}
    assert len(widths) == 1, f"rows differ in width: {sorted(widths)}"


def test_the_tagline_names_no_other_product() -> None:
    assert not re.search(r"jarvis", _TAGLINE, re.IGNORECASE)


def test_printing_it_emits_the_wordmark(capsys) -> None:
    print_banner()

    printed = capsys.readouterr().out
    # Rich may pad or wrap; the distinctive middle row has to survive.
    assert "|  \\| | | '__/ _` |" in printed
    assert _TAGLINE in printed


def test_quiet_prints_nothing(capsys) -> None:
    print_banner(quiet=True)

    assert capsys.readouterr().out == ""
