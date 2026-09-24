"""Startup banner — Nira wordmark + tagline."""

from __future__ import annotations

# "Nira" rendered in the figlet "standard" font. Stored as plain text
# (no inline Rich markup) so the backslashes in the glyphs don't collide with
# Rich's [tag] markup or Python raw-string escaping — colour is applied at
# print time via a style argument.
#
# This said "OpenJarvis" until 2026-09-24. The rename rewrote the comment
# above it — which described "a clearly readable capital J", a letter Nira
# does not contain — and left the glyphs alone, because a find-replace cannot
# see a word drawn in slashes. It is the first thing the CLI prints.
_WORDMARK = (
    " _   _ _           ",
    "| \\ | (_)_ __ __ _ ",
    "|  \\| | | '__/ _` |",
    "| |\\  | | | | (_| |",
    "|_| \\_|_|_|  \\__,_|",
)

_TAGLINE = "Personal AI, On Personal Devices"


def print_banner(quiet: bool = False) -> None:
    """Print the Nira startup banner. No-op when quiet."""
    if quiet:
        return
    try:
        from rich.console import Console

        console = Console()
        for line in _WORDMARK:
            console.print(line, style="bold bright_blue", highlight=False, markup=False)
        console.print(f"      {_TAGLINE}", style="cyan", highlight=False, markup=False)
        console.print()
    except ImportError:
        for line in _WORDMARK:
            print(line)
        print(f"      {_TAGLINE}")
        print()
