"""The site's nginx config must carry its security headers into every location.

nginx inherits ``add_header`` from an outer level *"if and only if there are no
add_header directives defined on the current level"*. Every location in
``website/nginx.conf`` sets one of its own -- a Cache-Control, a
Content-Disposition, a Content-Type -- so each one silently discarded the whole
server-level set, and the site served no CSP, no X-Frame-Options, no nosniff
and no Referrer-Policy on any URL a reader could reach.

That was invisible: the directives were right there in the file, and nothing
asked the server what it actually sent. This test asks the config instead of
asking nginx, so it needs no container and cannot drift from the file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NGINX_CONF = ROOT / "website" / "nginx.conf"
SNIPPET = ROOT / "website" / "security-headers.conf"

INCLUDE = "include /etc/nginx/security-headers.conf;"

REQUIRED_HEADERS = (
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Content-Security-Policy",
)


def _location_blocks(text: str) -> list[tuple[str, str]]:
    """Every ``location`` block as (header line, body), brace-matched."""
    blocks: list[tuple[str, str]] = []
    for match in re.finditer(r"^\s*(location\s[^{]*)\{", text, re.M):
        depth, index = 1, match.end()
        while depth and index < len(text):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
            index += 1
        blocks.append((match.group(1).strip(), text[match.end() : index - 1]))
    return blocks


@pytest.fixture(scope="module")
def conf() -> str:
    return NGINX_CONF.read_text(encoding="utf-8")


def test_the_snippet_defines_every_required_header() -> None:
    snippet = SNIPPET.read_text(encoding="utf-8")
    for header in REQUIRED_HEADERS:
        assert (
            f"add_header {header} " in snippet or f"add_header {header}" in snippet
        ), f"{header} is missing from security-headers.conf"
    # `always`, or the headers vanish on the 404 the site serves for a bad URL.
    for line in snippet.splitlines():
        if line.strip().startswith("add_header"):
            assert line.rstrip().endswith("always;"), (
                f"add_header without `always` would be dropped on error "
                f"responses: {line.strip()}"
            )


def test_the_server_level_includes_the_snippet(conf: str) -> None:
    # Split on a real location directive, not on the word in a comment.
    first = re.search(r"^\s*location\s[^{]*\{", conf, re.M)
    server_level = conf[: first.start()] if first else conf
    assert INCLUDE in server_level


def test_every_location_that_sets_a_header_reinstates_the_set(conf: str) -> None:
    """The actual trap: one add_header in a location drops all inherited ones."""
    offenders = []
    for name, body in _location_blocks(conf):
        if "add_header" not in body:
            continue  # inherits the server-level set untouched
        if INCLUDE not in body:
            offenders.append(name)
    assert not offenders, (
        "these locations set an add_header of their own, which discards every "
        "inherited header, and do not include the security snippet: "
        + ", ".join(offenders)
    )


def test_the_build_context_admits_the_snippet() -> None:
    """A .dockerignore that excludes it fails the image build, not this test."""
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "!website/security-headers.conf" in dockerignore

    dockerfile = (ROOT / "website" / "Dockerfile").read_text(encoding="utf-8")
    assert "security-headers.conf /etc/nginx/security-headers.conf" in dockerfile
