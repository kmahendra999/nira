"""The desktop app's icons have to be 8-bit, or it will not start at all.

Tauri hands `default_window_icon()` straight to the tray, and the tray wants
8-bit RGBA: 4 bytes a pixel, so 4096 for a 32x32. These were saved at 16-bit,
which decodes to 8 bytes a pixel, and every launch died in the setup hook
with:

    Failed to setup app: error encountered during setup hook:
    tray icon error: wrong data size, expected 4096 got 8192

Nothing caught it because the icons are correct in every other respect —
right names, right dimensions, right format — and nothing had ever run the
built binary. A 16-bit PNG is also what most image tools produce by default
when asked to convert something, so it is an easy mistake to make twice.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

ICONS = Path(__file__).resolve().parents[2] / "frontend" / "src-tauri" / "icons"

# 6 is RGBA in the PNG spec; 2 is RGB.
_COLOUR_TYPES = {0: "grey", 2: "RGB", 3: "palette", 4: "grey+alpha", 6: "RGBA"}


def _ihdr(path: Path) -> tuple[int, int, int, int]:
    """(width, height, bit_depth, colour_type) from a PNG's IHDR."""
    with path.open("rb") as handle:
        signature = handle.read(8)
        assert signature == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
        handle.read(8)  # chunk length + "IHDR"
        return struct.unpack(">IIBB", handle.read(10))


def _pngs() -> list[Path]:
    return sorted(ICONS.glob("*.png"))


def test_there_are_icons_to_check() -> None:
    """Guard the guard: a move or a rename would otherwise empty this file."""
    assert _pngs(), f"no PNGs under {ICONS}"


@pytest.mark.parametrize("icon", _pngs(), ids=lambda p: p.name)
def test_icon_is_eight_bit(icon: Path) -> None:
    _, _, depth, _ = _ihdr(icon)
    assert depth == 8, (
        f"{icon.name} is {depth}-bit; Tauri's tray reads 8-bit RGBA and a "
        f"{depth}-bit image gives it {depth // 8}x the bytes it expects, "
        "which panics during setup"
    )


@pytest.mark.parametrize("icon", _pngs(), ids=lambda p: p.name)
def test_icon_has_an_alpha_channel(icon: Path) -> None:
    # A tray icon without alpha gets a solid block behind it on every desktop
    # that composites one.
    _, _, _, colour = _ihdr(icon)
    assert colour in (4, 6), (
        f"{icon.name} is {_COLOUR_TYPES.get(colour, colour)}; it needs alpha"
    )


def test_the_tray_icon_is_the_size_tauri_expects() -> None:
    """32x32 RGBA at 8 bits is 4096 bytes — the number in the panic."""
    icon = ICONS / "32x32.png"
    width, height, depth, colour = _ihdr(icon)
    assert (width, height) == (32, 32)
    channels = 4 if colour == 6 else 3
    assert width * height * channels * (depth // 8) == 4096
