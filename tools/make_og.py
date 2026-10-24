#!/usr/bin/env python3
"""Regenerate content/og.png with the atelier palette.

Not part of the build: CI only needs markdown and pygments. Run this by hand
when the site's identity changes:

    python tools/make_og.py

Needs Pillow and a Windows install of Georgia + Consolas (or edit FONT_* below).
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "content" / "og.png"

FONT_DIR = Path("C:/Windows/Fonts")
FONT_SERIF = FONT_DIR / "georgia.ttf"
FONT_SERIF_ITALIC = FONT_DIR / "georgiai.ttf"
FONT_MONO = FONT_DIR / "consola.ttf"

PAPER_TOP = (247, 239, 223)
PAPER_BOTTOM = (236, 223, 200)
INK = (36, 30, 22)
INK_2 = (79, 66, 50)
BRASS = (160, 111, 40)
BRASS_LIGHT = (201, 154, 76)
TEAL = (11, 103, 95)
RULE = (201, 171, 124)


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def draw_sigil(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color, width: int = 2) -> None:
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color, width=width)
    d.ellipse((cx - r * 0.4, cy - r * 0.4, cx + r * 0.4, cy + r * 0.4), outline=color, width=width)
    for i in range(8):
        a = math.radians(i * 45)
        x1, y1 = cx + r * 1.04 * math.cos(a), cy + r * 1.04 * math.sin(a)
        x2, y2 = cx + r * 1.34 * math.cos(a), cy + r * 1.34 * math.sin(a)
        d.line((x1, y1, x2, y2), fill=color, width=width)
    star = []
    for i in range(8):
        a = math.radians(i * 45 - 90)
        rr = r * (0.62 if i % 2 == 0 else 0.24)
        star.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(star, fill=color)


def draw_circle(d: ImageDraw.ImageDraw, cx: float, cy: float) -> None:
    tint = BRASS + (58,)
    for radius, width in ((300, 2), (272, 1), (238, 2), (186, 1), (120, 2), (74, 2)):
        d.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=tint, width=width)
    for i in range(24):
        a = math.radians(i * 15)
        long = i % 3 == 0
        r1, r2 = 238, 268 if long else 252
        d.line(
            (cx + r1 * math.cos(a), cy + r1 * math.sin(a),
             cx + r2 * math.cos(a), cy + r2 * math.sin(a)),
            fill=tint, width=2,
        )
    for i in range(8):
        a = math.radians(i * 45 + 22.5)
        x, y = cx + 205 * math.cos(a), cy + 205 * math.sin(a)
        d.polygon([(x - 10, y + 6), (x, y - 8), (x + 10, y + 6)], fill=BRASS + (70,))
    star = []
    for i in range(10):
        a = math.radians(i * 36 - 90)
        rr = 150 if i % 2 == 0 else 52
        star.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(star, outline=BRASS + (70,), width=2)


def draw_mascot(img: Image.Image, x: int, y: int, size: int = 190) -> None:
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    s = size / 200.0

    def box(a: float, b: float, c: float, e: float):
        return (a * s, b * s, c * s, e * s)

    d.ellipse(box(38, 186, 162, 198), fill=(36, 30, 22, 45))
    d.line(box(70, 172, 70, 192), fill=INK + (255,), width=round(7 * s))
    d.line(box(130, 172, 130, 192), fill=INK + (255,), width=round(7 * s))
    d.rounded_rectangle(box(118, 34, 142, 78), radius=round(8 * s), fill=INK_2 + (255,), outline=INK + (255,), width=round(6 * s))
    d.ellipse(box(124, 14, 148, 38), fill=(36, 30, 22, 52))
    d.rounded_rectangle(box(38, 66, 162, 176), radius=round(30 * s), fill=BRASS + (255,), outline=INK + (255,), width=round(7 * s))
    d.rounded_rectangle(box(54, 82, 146, 128), radius=round(14 * s), fill=PAPER_TOP + (255,), outline=INK + (255,), width=round(6 * s))
    d.ellipse(box(88, 93, 112, 117), fill=TEAL + (255,))
    d.ellipse(box(101, 97, 107, 103), fill=PAPER_TOP + (235,))
    d.line(box(78, 148, 122, 148), fill=INK + (140,), width=round(6 * s))
    d.ellipse(box(52, 156, 60, 164), fill=INK + (110,))
    d.ellipse(box(140, 156, 148, 164), fill=INK + (110,))
    layer = layer.rotate(-5, resample=Image.BICUBIC, expand=False)
    img.alpha_composite(layer, (x, y))


def main() -> None:
    img = Image.new("RGBA", (W, H), PAPER_TOP + (255,))
    px = img.load()
    for y in range(H):
        color = lerp(PAPER_TOP, PAPER_BOTTOM, y / H)
        for x in range(W):
            px[x, y] = color + (255,)

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    # blueprint grid
    for x in range(0, W, 44):
        d.line((x, 0, x, H), fill=BRASS + (20,), width=1)
    for y in range(0, H, 44):
        d.line((0, y, W, y), fill=BRASS + (20,), width=1)

    draw_circle(d, 1010, 250)
    img = Image.alpha_composite(img, overlay)

    draw_mascot(img, 905, 318)
    d = ImageDraw.Draw(img)

    # brand
    draw_sigil(d, 96, 82, 17, BRASS, 2)
    d.text((128, 58), "Explosion Awas", font=font(FONT_SERIF, 38), fill=INK + (255,))
    d.text((130, 104), "O U T P U T   L O G", font=font(FONT_MONO, 13), fill=BRASS + (255,))
    d.text((1090, 62), "EST. 2026", font=font(FONT_MONO, 13), fill=BRASS + (255,), anchor="ra")

    # the stamp
    stamp = Image.new("RGBA", (150, 54), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stamp)
    sd.rounded_rectangle((2, 2, 147, 51), radius=4, outline=BRASS + (255,), width=3)
    sd.text((75, 27), "PUBLIC", font=font(FONT_MONO, 18), fill=BRASS + (255,), anchor="mm")
    stamp = stamp.rotate(-8, resample=Image.BICUBIC, expand=True)
    img.alpha_composite(stamp, (1040, 96))

    # headline
    head = font(FONT_SERIF, 70)
    head_it = font(FONT_SERIF_ITALIC, 70)
    d.text((90, 186), "Agent output,", font=head, fill=INK + (255,))
    d.text((90, 276), "published as it comes.", font=head_it, fill=BRASS + (255,))

    # underline the second line, like the website
    width = d.textlength("published as it comes.", font=head_it)
    d.rectangle((90, 368, 90 + width, 376), fill=BRASS + (48,))

    d.line((90, 520, 1110, 520), fill=RULE + (255,), width=1)
    d.text((90, 544), "explosion-awas.github.io", font=font(FONT_MONO, 16), fill=INK_2 + (210,))
    d.text((1110, 544), "notes  ·  code  ·  papers", font=font(FONT_MONO, 14), fill=BRASS + (255,), anchor="ra")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
