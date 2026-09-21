#!/usr/bin/env python3
"""Redraw the architecture diagram.

The file this replaces was titled "OpenJarvis Architecture" and drawn in
upstream's palette. The rename changed its filename and nothing inside it,
so the architecture page carried somebody else's title in their colours.

The structure it described is still the right one -- interfaces over agents,
agents over intelligence and tools, engine and hardware beneath -- so this
keeps the structure and redraws it: Nira's orange, Geist, and the dark
surface the rest of the brand uses.

Run:  uv run python scripts/brand/make_architecture.py
"""

from __future__ import annotations

import io
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
WOFF2 = ROOT / "website/public/assets/fonts/geist-latin-wght-normal.woff2"
OUT = ROOT / "docs/assets/Nira_Architecture.png"

SS = 2                      # supersample, then downscale once at the end
W, H = 1000 * SS, 470 * SS

BG = "#0e0e11"
INK = "#f4f4f5"
MUTED = "#a1a1aa"
ORANGE = "#ea580c"
LIGHT = "#fb923c"

# Each band gets a tint of the accent rather than its own hue: five unrelated
# colours would imply five unrelated things, and these nest.
BANDS = [
    ("#17171c", "#2a2a33"),   # interfaces
    ("#191419", "#3a2a22"),   # agents
    ("#141519", "#242833"),   # intelligence
    ("#131217", "#2b2230"),   # tools
]


def geist(px: int, weight: float = 400) -> ImageFont.FreeTypeFont:
    font = TTFont(str(WOFF2))
    font.flavor = None
    buf = io.BytesIO()
    font.save(buf)
    buf.seek(0)
    face = ImageFont.truetype(buf, px)
    face.set_variation_by_axes([weight])
    return face


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    f_title = geist(27 * SS, 700)
    f_head = geist(17 * SS, 700)
    f_body = geist(13 * SS, 450)
    f_small = geist(12 * SS, 450)

    def box(x0, y0, x1, y1, fill, outline, r=14):
        d.rounded_rectangle((x0 * SS, y0 * SS, x1 * SS, y1 * SS),
                            radius=r * SS, fill=fill, outline=outline,
                            width=max(1, 1 * SS))

    def text(x, y, s, font, fill=INK):
        d.text((x * SS, y * SS), s, font=font, fill=fill)

    # Title, with the mark's dot as a bullet so the diagram belongs to the
    # same set as the logo.
    d.ellipse((40 * SS, 30 * SS, 52 * SS, 42 * SS), fill=LIGHT)
    text(62, 24, "Nira Architecture", f_title)

    # --- User interfaces -------------------------------------------------
    box(40, 72, 960, 126, *BANDS[0])
    text(60, 80, "User interfaces", f_head, ORANGE)
    text(60, 102, "CLI  ·  Browser  ·  Desktop app  ·  Android  ·  Voice  ·  26+ messaging channels",
         f_body, MUTED)

    # --- Agents ----------------------------------------------------------
    box(40, 138, 960, 432, *BANDS[1])
    text(60, 148, "Agents", f_head, ORANGE)
    text(60, 170, "Composable reasoning over intelligence and tools, with approvals before anything risky",
         f_body, MUTED)

    # --- Intelligence / engine / hardware --------------------------------
    box(60, 198, 500, 412, *BANDS[2])
    text(80, 208, "Intelligence", f_head)
    text(80, 230, "On-device models, chosen to fit the machine", f_small, MUTED)

    box(80, 256, 480, 392, "#101218", "#222634")
    text(98, 266, "Engine", f_head)
    text(98, 288, "Ollama · vLLM · SGLang · llama.cpp · cloud APIs", f_small, MUTED)

    box(98, 314, 462, 376, "#0d0f14", "#1e2230")
    text(116, 324, "Hardware", f_head)
    text(116, 346, "Apple Silicon · NVIDIA · AMD · NPUs · CPUs", f_small, MUTED)

    # --- Tools & memory / learning ---------------------------------------
    box(520, 198, 940, 300, *BANDS[3])
    text(540, 208, "Tools & memory", f_head)
    text(540, 230, "Web, files, code, retrieval, persistent", f_small, MUTED)
    text(540, 250, "local state, MCP servers, telemetry", f_small, MUTED)

    box(520, 312, 940, 412, "#141119", "#2e2438")
    text(540, 322, "Learning", f_head)
    text(540, 344, "Every run leaves a trace; traces drive", f_small, MUTED)
    text(540, 364, "prompt, routing and agent improvements", f_small, MUTED)

    # A footer that says the thing the diagram is for.
    text(40, 444, "Everything runs on machines you own. The cloud is an option, not a dependency.",
         f_small, MUTED)

    img.resize((W // SS, H // SS), Image.LANCZOS).save(OUT)
    print(f"  {OUT.relative_to(ROOT)}  {W // SS}x{H // SS}")


if __name__ == "__main__":
    main()
