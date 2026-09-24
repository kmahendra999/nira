"""The Tauri crates and their npm counterparts have to agree on major.minor.

`tauri build` refuses outright when they do not:

    Found version mismatched Tauri packages. Make sure the NPM package and
    Rust crate versions are on the same major/minor releases:
    tauri-plugin-notification (v2.3.3) : @tauri-apps/plugin-notification (v2.4.0)
    tauri-plugin-updater (v2.10.1) : @tauri-apps/plugin-updater (v2.11.0)

Which is how the desktop release job had been failing -- on every push, for
as long as the two lockfiles had been drifting. Nothing noticed, because the
only thing that runs that check is a release build, and a release build is
the one thing nobody runs until they want a release.

Both sides declare a caret range and each resolves independently, so they
drift apart whenever one lockfile is refreshed and the other is not. This
compares the resolved versions, not the ranges, because the ranges were
never the problem.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import tomllib

ROOT = Path(__file__).resolve().parents[2]
CARGO_LOCK = ROOT / "frontend" / "src-tauri" / "Cargo.lock"
PACKAGE_LOCK = ROOT / "frontend" / "package-lock.json"


def _crate_versions() -> dict[str, str]:
    data = tomllib.loads(CARGO_LOCK.read_text(encoding="utf-8"))
    return {
        p["name"]: p["version"]
        for p in data.get("package", [])
        if p.get("name", "").startswith("tauri")
    }


def _npm_versions() -> dict[str, str]:
    data = json.loads(PACKAGE_LOCK.read_text(encoding="utf-8"))
    found: dict[str, str] = {}
    for path, meta in (data.get("packages") or {}).items():
        match = re.search(r"@tauri-apps/([^/]+)$", path)
        if match and meta.get("version"):
            found[match.group(1)] = meta["version"]
    return found


def _minor(version: str) -> tuple[str, str]:
    parts = version.split(".")
    return parts[0], parts[1] if len(parts) > 1 else "0"


# `@tauri-apps/api` pairs with the `tauri` crate; every other JS package
# `plugin-x` pairs with the crate `tauri-plugin-x`. `cli` has no crate.
def _pairs() -> list[tuple[str, str, str, str]]:
    crates, npm = _crate_versions(), _npm_versions()
    pairs = []
    for js_name, js_version in sorted(npm.items()):
        if js_name.startswith("plugin-"):
            crate = f"tauri-{js_name}"
        elif js_name == "api":
            crate = "tauri"
        else:
            continue  # cli, and the per-platform cli-* binaries
        if crate in crates:
            pairs.append((crate, crates[crate], f"@tauri-apps/{js_name}", js_version))
    return pairs


def test_there_are_pairs_to_check() -> None:
    """Guard the guard: a rename upstream would silently empty this."""
    pairs = _pairs()
    assert len(pairs) >= 5, f"only matched {len(pairs)} Tauri package pairs"


@pytest.mark.parametrize("crate,crate_version,js,js_version", _pairs())
def test_major_minor_agree(
    crate: str, crate_version: str, js: str, js_version: str
) -> None:
    assert _minor(crate_version) == _minor(js_version), (
        f"{crate} ({crate_version}) and {js} ({js_version}) are on different "
        "major/minor releases; `tauri build` refuses to build this"
    )
