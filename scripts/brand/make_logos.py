#!/usr/bin/env python3
"""Generate Nira's logo set from the one mark.

The files this replaces were OpenJarvis's: an Iron Man arc reactor, and a
wordmark reading "OpenJarvis". Only their filenames had been changed in the
rename, so the README's header image still showed somebody else's product
name in somebody else's mark.

Everything here is drawn from the same geometry as
``frontend/src-tauri/icons/nira-mark.svg`` -- two stems with round ends and a
diagonal tucked inside them -- so the logo, the app icon and the favicon are
the same letter rather than three drawings that resemble each other.

The wordmark is set in Geist, the face the app and the website already use,
read straight from the woff2 the frontend ships. That is deliberate: a logo
set in whatever font happened to be installed on the machine that generated
it is a logo that changes the next time somebody regenerates it elsewhere.

Run:  uv run python scripts/brand/make_logos.py
"""

from __future__ import annotations

import io
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
WOFF2 = ROOT / "website/public/assets/fonts/geist-latin-wght-normal.woff2"

TILE = "#121214"      # the mark's dark tile
RULE = "#3a3a42"      # its hairline border
ORANGE = "#ea580c"    # Nira's accent
LIGHT = "#fb923c"     # the one point of light
WORD = "#f4f4f5"      # wordmark on dark


def geist(size: int, weight: float = 700) -> ImageFont.FreeTypeFont:
    """Geist at a weight, from the variable woff2 the frontend ships."""
    font = TTFont(str(WOFF2))
    font.flavor = None                     # woff2 -> plain sfnt
    buf = io.BytesIO()
    font.save(buf)
    buf.seek(0)
    face = ImageFont.truetype(buf, size)
    face.set_variation_by_axes([weight])   # the file is wght 100-900
    return face


def draw_mark(draw: ImageDraw.ImageDraw, x: float, y: float, size: float,
              tile: bool = True) -> None:
    """The N, ``size`` px wide, top-left corner at (x, y).

    Coordinates are the 1024-unit ones from the SVG, scaled -- so this and
    the icon cannot drift apart.
    """
    s = size / 1024.0

    def p(*v: float) -> list[float]:
        """Scale a run of alternating SVG x/y units into pixel space."""
        return [x + n * s if i % 2 == 0 else y + n * s
                for i, n in enumerate(v)]

    if tile:
        draw.rounded_rectangle(p(0, 0, 1024, 1024), radius=228 * s, fill=TILE)
        draw.rounded_rectangle(p(8, 8, 1016, 1016), radius=222 * s,
                               outline=RULE, width=max(1, int(16 * s)))

    # The diagonal first, so the stems overlap its corners.
    draw.polygon(p(372.6, 252.2, 724.6, 716.2, 651.4, 771.8, 299.4, 307.8),
                 fill=ORANGE)
    # Two stems, round ends where a round line cap would have landed.
    draw.rounded_rectangle(p(290, 234, 382, 790), radius=46 * s, fill=ORANGE)
    draw.rounded_rectangle(p(642, 234, 734, 790), radius=46 * s, fill=ORANGE)
    # The dot: the thing that is on.
    draw.ellipse(p(658, 250, 718, 310), fill=LIGHT)


def horizontal(path: Path, mark_px: int = 320) -> None:
    """Mark + wordmark, transparent, for the top of a README."""
    gap = int(mark_px * 0.30)
    face = geist(int(mark_px * 0.74), weight=700)

    probe = Image.new("RGBA", (10, 10))
    left, top, right, bottom = ImageDraw.Draw(probe).textbbox(
        (0, 0), "Nira", font=face)
    text_w, text_h = right - left, bottom - top

    pad = int(mark_px * 0.12)
    width = pad + mark_px + gap + text_w + pad
    height = pad + mark_px + pad

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_mark(draw, pad, pad, mark_px)
    # Centred against the mark's own box, with the glyph bbox offset removed
    # so the cap height sits level with the tile rather than the text origin.
    draw.text((pad + mark_px + gap - left, pad + (mark_px - text_h) // 2 - top),
              "Nira", font=face, fill=WORD)
    img.save(path)
    print(f"  {path.relative_to(ROOT)}  {width}x{height}")


def circular(path: Path, size: int = 512) -> None:
    """The mark in a disc, for anywhere that crops to a circle."""
    ss = 4  # supersample: the disc edge is the whole point of this file
    img = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, size * ss - 1, size * ss - 1), fill=TILE,
                 outline=RULE, width=int(size * ss * 0.016))
    inner = int(size * ss * 0.60)
    draw_mark(draw, (size * ss - inner) // 2, (size * ss - inner) // 2, inner,
              tile=False)
    img.resize((size, size), Image.LANCZOS).save(path)
    print(f"  {path.relative_to(ROOT)}  {size}x{size}")


def square(path: Path, size: int = 512, quality: int = 92) -> None:
    """Flat square for chat integrations, which do their own rounding."""
    ss = 4
    img = Image.new("RGB", (size * ss, size * ss), TILE)
    draw = ImageDraw.Draw(img)
    inner = int(size * ss * 0.62)
    draw_mark(draw, (size * ss - inner) // 2, (size * ss - inner) // 2, inner,
              tile=False)
    out = img.resize((size, size), Image.LANCZOS)
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        out.save(path, quality=quality, subsampling=0)
    else:
        out.save(path)
    print(f"  {path.relative_to(ROOT)}  {size}x{size}")


if __name__ == "__main__":
    print("Nira logos, from the mark:")
    horizontal(ROOT / "assets/Nira_Horizontal_Logo.png")
    circular(ROOT / "assets/Nira_Circular_Logo.png")
    square(ROOT / "assets/nira-slack-icon.jpg")
