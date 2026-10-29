# -*- coding: utf-8 -*-
"""Builds the app icon from installer/icon.svg.

- With cairosvg available (dev machine): renders installer/icon-png/icon_<N>.png from the SVG
  and the wizard BMPs from installer/wizard*.svg.
- Without it (CI on Windows): uses the committed PNGs/BMPs as they are.
- 16x16 is hand-drawn pixel art (crisp in the tray), not rendered from the SVG.
- Always writes installer/icon.ico (16..256) from the PNGs.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
PNG_DIR = HERE / "icon-png"
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]

AMBER = (245, 180, 0, 255)
COLORS = {
    ".": (0, 0, 0, 0),
    "a": (245, 180, 0, 140),  # anti-aliased corner
    "A": AMBER,
    "K": (26, 26, 26, 255),
    "R": (229, 57, 53, 255),
    "r": (237, 118, 27, 255),  # red/amber blend: rounds the dot's corners
    "k": (136, 103, 13, 255),  # black/amber blend: softens the bell's shoulders
}
# 16x16 pixel art: amber rounded square, black bell, red dot
PIXEL_16 = [
    ".aAAAAAAAAAAAAa.",
    "aAAAAAAKKAArRRrA",
    "AAAAAkKKKkARRRRA",
    "AAAAAKKKKKARRRRA",
    "AAAAkKKKKKkrRRrA",
    "AAAAKKKKKKKKAAAA",
    "AAAAKKKKKKKKAAAA",
    "AAAAKKKKKKKKAAAA",
    "AAAAKKKKKKKKAAAA",
    "AAAKKKKKKKKKKAAA",
    "AAKKKKKKKKKKKKAA",
    "AAAAAAAAAAAAAAAA",
    "AAAAAAKKKKAAAAAA",
    "AAAAAAAKKAAAAAAA",
    "aAAAAAAAAAAAAAAa",
    ".aAAAAAAAAAAAAa.",
]


def pixel_16() -> Image.Image:
    img = Image.new("RGBA", (16, 16))
    for y, row in enumerate(PIXEL_16):
        assert len(row) == 16, (y, row)
        for x, ch in enumerate(row):
            img.putpixel((x, y), COLORS[ch])
    return img


def render_svg(svg: Path, w: int, h: int) -> Image.Image:
    import cairosvg

    data = cairosvg.svg2png(url=str(svg), output_width=w, output_height=h)
    return Image.open(io.BytesIO(data)).convert("RGBA")


def render_all() -> None:
    PNG_DIR.mkdir(exist_ok=True)
    for s in SIZES:
        img = pixel_16() if s == 16 else render_svg(HERE / "icon.svg", s, s)
        img.save(PNG_DIR / f"icon_{s}.png")
    # installer wizard images (BMP, no alpha)
    for name, (w, h) in {
        "wizard": (164, 314), "wizard-2x": (328, 628),
        "wizard-small": (55, 55), "wizard-small-2x": (110, 110),
    }.items():
        src = HERE / ("wizard-small.svg" if name.startswith("wizard-small") else "wizard.svg")
        img = render_svg(src, w, h)
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        bg.save(HERE / f"{name}.bmp")
    # bell glyph for the reminder popup (transparent PNG, 1x and 2x)
    for h in (84, 150, 300):
        render_svg(HERE / "bell.svg", round(h * 180 / 190), h).save(PNG_DIR / f"bell_{h}.png")
    print("rendered PNG/BMP from SVG")


def build_ico() -> Path:
    frames = [Image.open(PNG_DIR / f"icon_{s}.png").convert("RGBA") for s in SIZES]
    out = HERE / "icon.ico"
    frames[-1].save(out, format="ICO", sizes=[(s, s) for s in SIZES], append_images=frames[:-1])
    return out


if __name__ == "__main__":
    import importlib

    try:
        importlib.import_module("cairosvg")
        have_cairo = True
    except Exception:  # not installed, or no cairo DLL (Windows)
        have_cairo = False
    if have_cairo and "--no-render" not in sys.argv:
        render_all()
    else:
        print("cairosvg not available: using committed PNG/BMP files")
    print("OK", build_ico())
