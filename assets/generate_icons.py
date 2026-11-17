#!/usr/bin/env python3
"""Generate the Paper Review app and menu bar icons with Pillow.

    .venv/bin/python assets/generate_icons.py
    → app_icon.png (1024x1024), menubar-icon.png (18x18), @2x (36x36)

packaging/build.sh converts app_icon.png to .icns.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024
HERE = Path(__file__).parent


def _background() -> Image.Image:
    image = Image.new("RGBA", (SIZE, SIZE))
    pixels = image.load()
    for y in range(SIZE):
        for x in range(SIZE):
            t = (x + y) / (2 * (SIZE - 1))
            start, end = (40, 38, 72), (90, 90, 151)
            pixels[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(start, end)) + (
                255,
            )
    mask = Image.new("L", (SIZE, SIZE))
    ImageDraw.Draw(mask).rounded_rectangle((22, 22, 1002, 1002), radius=220, fill=255)
    image.putalpha(mask)
    return image


def _draw_app_icon() -> None:
    image = _background()
    shadow = Image.new("RGBA", image.size)
    ImageDraw.Draw(shadow).polygon(
        [(277, 143), (628, 143), (777, 292), (777, 858), (277, 858)],
        fill=(0, 0, 0, 100),
    )
    image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(28)), (0, 18))

    draw = ImageDraw.Draw(image)
    document = [(245, 122), (616, 122), (781, 287), (781, 861), (245, 861)]
    draw.polygon(document, fill="#f2f4fa")
    draw.polygon([(616, 122), (616, 287), (781, 287)], fill="#c8d0ed")

    # Clear, generous strokes stay legible in the Dock.
    for y, width in ((378, 340), (477, 278), (576, 330), (675, 202)):
        draw.rounded_rectangle((316, y, 316 + width, y + 24), radius=12, fill="#7c84c3")

    # The verification mark overlaps the paper as a distinct review signal.
    badge_shadow = Image.new("RGBA", image.size)
    ImageDraw.Draw(badge_shadow).ellipse((563, 590, 866, 893), fill=(0, 0, 0, 100))
    image.alpha_composite(badge_shadow.filter(ImageFilter.GaussianBlur(18)), (0, 10))
    draw = ImageDraw.Draw(image)
    draw.ellipse((554, 575, 846, 867), fill="#73e0c4", outline="#e1fff4", width=12)
    draw.line((622, 720, 682, 777, 785, 663), fill="#174d59", width=31, joint="curve")
    draw.ellipse((607, 705, 638, 736), fill="#174d59")
    draw.ellipse((769, 647, 800, 678), fill="#174d59")
    image.save(HERE / "app_icon.png")


def _draw_menubar_icon(px: int) -> Image.Image:
    scale = px / 18
    image = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    x0, y0 = round(2.5 * scale), round(1.5 * scale)
    x1, y1 = px - x0, px - y0
    draw.rounded_rectangle(
        (x0, y0, x1, y1), radius=max(1, round(3 * scale)), fill=(0, 0, 0, 255)
    )
    # Knock out two text lines and a check so macOS can tint the template glyph.
    line_w = max(1, round(1.5 * scale))
    draw.rounded_rectangle(
        (
            round(5 * scale),
            round(5 * scale),
            round(13 * scale),
            round(5 * scale) + line_w,
        ),
        radius=1,
        fill=(0, 0, 0, 0),
    )
    draw.rounded_rectangle(
        (
            round(5 * scale),
            round(8 * scale),
            round(10 * scale),
            round(8 * scale) + line_w,
        ),
        radius=1,
        fill=(0, 0, 0, 0),
    )
    draw.line(
        (
            round(5 * scale),
            round(12 * scale),
            round(7 * scale),
            round(14 * scale),
            round(12 * scale),
            round(11 * scale),
        ),
        fill=(0, 0, 0, 0),
        width=max(1, round(1.5 * scale)),
    )
    return image


def main() -> None:
    _draw_app_icon()
    for px, name in ((18, "menubar-icon.png"), (36, "menubar-icon@2x.png")):
        _draw_menubar_icon(px).save(HERE / name)
    print("생성: app_icon.png, menubar-icon.png, menubar-icon@2x.png")


if __name__ == "__main__":
    main()
