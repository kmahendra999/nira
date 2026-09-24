#!/usr/bin/env python3
"""Every link in the README, the docs and the website, and whether it resolves.

Phase 18 found seventeen dead links in the README by hand, once, and only
months after the rename that broke them. This is that audit as something that
runs.

Two lanes, because the two kinds of link fail for different reasons:

* ``--offline`` resolves relative paths and in-page anchors against the source
  tree. It is deterministic, needs no network, and belongs on every pull
  request.
* The default adds external URLs. Those go stale on somebody else's schedule,
  so they belong on a timer rather than in the way of a merge.

Some links point at files mkdocs generates at build time and that therefore do
not exist in the tree. Rather than skip that whole subtree -- which is most of
the documentation's internal links -- each generated path is mapped back to the
source that produces it, so a link to a module that was deleted still fails.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent

# Where links are read from.
SITE_ROOT = ROOT / "website" / "public"

MARKDOWN_GLOBS = ("*.md", "docs/**/*.md")
HTML_GLOBS = ("website/public/**/*.html",)

# Schemes that name something this script cannot and should not resolve.
SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "#!")

# Hosts that answer a bot with a challenge rather than the page. A failure
# from one of these says nothing about the link, so it is reported as
# unverifiable rather than counted as broken.
BOT_WALLED = ("twitter.com", "x.com", "linkedin.com", "reddit.com", "medium.com")

MD_LINK = re.compile(r"\[[^\]]*\]\(\s*([^)\s]+?)\s*(?:\"[^\"]*\")?\s*\)")
MD_REF = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)", re.M)
HTML_ATTR = re.compile(r"(?:href|src)\s*=\s*[\"']([^\"']+)[\"']", re.I)
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$", re.M)


@dataclass(frozen=True)
class Link:
    source: Path
    line: int
    target: str


@dataclass
class Failure:
    link: Link
    reason: str


def _slug(text: str) -> str:
    """Approximate the anchor mkdocs and GitHub derive from a heading."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links keep their text
    text = re.sub(r"[`*_]", "", text)
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    return re.sub(r"[\s]+", "-", text.strip().lower())


def anchors_of(path: Path) -> set[str]:
    """Every anchor a page offers -- headings in markdown, ids in HTML."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    found: set[str] = set()
    if path.suffix in (".html", ".htm"):
        # A hand-written page names its sections with id=, not with headings.
        return set(re.findall(r"\bid=[\"\']([^\"\']+)[\"\']", text))
    seen: dict[str, int] = defaultdict(int)
    for _, heading in HEADING.findall(text):
        slug = _slug(heading)
        if not slug:
            continue
        count = seen[slug]
        seen[slug] += 1
        found.add(slug if count == 0 else f"{slug}-{count}")
    # Explicit anchors, e.g. <a id="x"> or {#x}
    found.update(re.findall(r"<a\s+(?:id|name)=[\"']([^\"']+)[\"']", text, re.I))
    found.update(re.findall(r"\{#([\w-]+)\}", text))
    return found


def _iter_files() -> Iterable[Path]:
    for pattern in MARKDOWN_GLOBS + HTML_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            if path.is_file():
                yield path


def collect_links() -> list[Link]:
    links: list[Link] = []
    for path in _iter_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        patterns = (
            (HTML_ATTR,) if path.suffix == ".html" else (MD_LINK, MD_REF, HTML_ATTR)
        )
        for pattern in patterns:
            for match in pattern.finditer(text):
                target = match.group(1).strip()
                line = text.count("\n", 0, match.start()) + 1
                links.append(Link(path, line, target))
    return links


def _generated_source(relative: Path) -> Path | None:
    """The file that produces a path mkdocs generates, or None.

    ``docs/gen_ref_pages.py`` writes ``api-reference/<module>.md`` for every
    module under ``src/``; ``docs/gen_install_script.py`` copies the two
    installers to the docs root.
    """
    parts = relative.parts
    if parts[:1] == ("api-reference",):
        rest = Path(*parts[1:])
        if rest.name == "index.md":
            return ROOT / "src" / rest.parent / "__init__.py"
        if rest.name == "SUMMARY.md":
            return ROOT / "docs" / "gen_ref_pages.py"
        return ROOT / "src" / rest.with_suffix(".py")
    if relative.as_posix() == "install.sh":
        return ROOT / "scripts" / "install" / "install.sh"
    if relative.as_posix() == "install.ps1":
        return ROOT / "deploy" / "windows" / "install.ps1"
    return None


def _generated_site_path(relative: Path) -> Path | None:
    """The source for a published path that is not in ``website/public``.

    ``.github/workflows/docs.yml`` assembles the Pages site: the front page
    from ``website/public``, the installer from where it actually lives, the
    documentation from the mkdocs build, and ``config.json`` written inline.
    """
    posix = relative.as_posix()
    if posix == "install.sh":
        return ROOT / "scripts" / "install" / "install.sh"
    if posix == "config.json":
        return ROOT / ".github" / "workflows" / "docs.yml"
    if posix == "docs" or posix.startswith("docs/"):
        return ROOT / "mkdocs.yml"
    if posix == "downloads" or posix.startswith("downloads/"):
        # Removed at publish time and served from a release instead.
        return ROOT / ".github" / "workflows" / "docs.yml"
    return None


def check_local(link: Link) -> str | None:
    """Resolve a relative link, returning a reason when it goes nowhere."""
    target, _, fragment = link.target.partition("#")

    if not target:  # an anchor into this same file
        if fragment and fragment not in anchors_of(link.source):
            return f"no heading anchors to '#{fragment}'"
        return None

    in_site = SITE_ROOT in link.source.parents
    if target.startswith("/"):
        if not in_site:
            return None  # absolute on some other host's terms; not ours to resolve
        resolved = (SITE_ROOT / target.lstrip("/")).resolve()
    else:
        resolved = (link.source.parent / target).resolve()

    if resolved.is_dir():
        return None

    if resolved.exists():
        if fragment and resolved.suffix == ".md":
            if fragment not in anchors_of(resolved):
                return f"'{resolved.name}' has no anchor '#{fragment}'"
        return None

    # Not in the tree -- it may be written at build time, by mkdocs for the
    # documentation or by the workflow that assembles the published site.
    for base_dir, generator in (
        (ROOT / "docs", _generated_source),
        (SITE_ROOT, _generated_site_path),
    ):
        try:
            relative = resolved.relative_to(base_dir)
        except ValueError:
            continue
        source = generator(relative)
        if source is None:
            continue
        if not source.exists():
            return f"generated from {source.relative_to(ROOT)}, which is missing"
        return None
    return "no such file"


def check_external(url: str) -> tuple[bool, str]:
    """(ok, reason). Unverifiable hosts come back ok with a reason."""
    import requests

    headers = {"User-Agent": "nira-link-check/1.0 (+https://github.com/)"}
    last = ""
    for method in ("head", "get"):
        for _ in range(2):
            try:
                response = requests.request(
                    method,
                    url,
                    timeout=20,
                    allow_redirects=True,
                    headers=headers,
                    stream=(method == "get"),
                )
                response.close()
            except requests.RequestException as exc:
                last = type(exc).__name__
                continue
            if response.status_code < 400:
                return True, ""
            # Plenty of servers refuse HEAD but serve GET.
            if method == "head" and response.status_code in (403, 405, 501):
                last = f"HTTP {response.status_code}"
                break
            if response.status_code in (401, 403, 429):
                return True, f"unverifiable (HTTP {response.status_code})"
            last = f"HTTP {response.status_code}"
            break
    if any(host in url for host in BOT_WALLED):
        return True, f"unverifiable ({last})"
    return False, last or "unreachable"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Check only relative paths and anchors; skip external URLs.",
    )
    parser.add_argument(
        "--jobs", type=int, default=16, help="Concurrent external requests."
    )
    args = parser.parse_args()

    links = collect_links()
    failures: list[Failure] = []
    notes: list[Failure] = []

    external: list[Link] = []
    local = 0
    for link in links:
        if link.target.startswith(SKIP_SCHEMES) or link.target.startswith("{"):
            continue
        # `../<path>.md` in a contributing guide is an instruction, not a link.
        if "<" in link.target or ">" in link.target:
            continue
        if link.target.startswith(("http://", "https://")):
            external.append(link)
            continue
        if link.target.startswith("//"):
            continue
        # A dev-server URL in a quickstart is an instruction to the reader,
        # not a link to anywhere this can reach.
        if re.match(
            r"https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])\b", link.target
        ):
            continue
        local += 1
        reason = check_local(link)
        if reason:
            failures.append(Failure(link, reason))

    checked_external = 0
    if not args.offline and external:
        unique = sorted({link.target for link in external})
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            verdicts = dict(zip(unique, pool.map(check_external, unique)))
        checked_external = len(unique)
        for link in external:
            ok, reason = verdicts[link.target]
            if not ok:
                failures.append(Failure(link, reason))
            elif reason:
                notes.append(Failure(link, reason))

    scope = "offline" if args.offline else "offline + external"
    print(
        f"Checked {local} relative and {checked_external} external "
        f"link(s) across {len(set(link.source for link in links))} files "
        f"[{scope}]"
    )

    if notes:
        print(f"\n{len(notes)} unverifiable (not counted as failures):")
        for note in notes[:20]:
            rel = note.link.source.relative_to(ROOT)
            print(f"  {rel}:{note.link.line}  {note.link.target}  — {note.reason}")

    if not failures:
        print("\nAll links resolve.")
        return 0

    print(f"\n{len(failures)} broken link(s):")
    by_file: dict[Path, list[Failure]] = defaultdict(list)
    for failure in failures:
        by_file[failure.link.source].append(failure)
    for path in sorted(by_file):
        print(f"\n  {path.relative_to(ROOT)}")
        for failure in by_file[path]:
            print(f"    :{failure.link.line}  {failure.link.target}")
            print(f"        {failure.reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
