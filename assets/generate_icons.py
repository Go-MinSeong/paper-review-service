#!/usr/bin/env python3
"""Generate the Paper Review app icon with Pillow.

    .venv/bin/python assets/generate_icons.py
    → app_icon.png (1024x1024)

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


def main() -> None:
    _draw_app_icon()
    print("생성: app_icon.png")


if __name__ == "__main__":
    main()
