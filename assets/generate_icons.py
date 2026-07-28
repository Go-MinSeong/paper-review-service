#!/usr/bin/env python3
"""App + menubar icons — SF Symbols rendered to PNG.

Drawn with pyobjc (already a dependency via rumps/pywebview) rather than adding
Pillow. Modelled on the same generator in the daily-log project so the three
apps sit consistently in the Dock.

    .venv/bin/python assets/generate_icons.py
    → assets/app_icon.png        (1024x1024, Dock/Finder)
    → assets/menubar-icon.png    (18x18 black template, tinted by macOS)
    → assets/menubar-icon@2x.png (36x36)

packaging/build.sh turns app_icon.png into .icns with sips + iconutil.
"""

from __future__ import annotations

import sys
from pathlib import Path

SIZE = 1024.0
SYMBOL = "doc.text.magnifyingglass"  # read a paper, closely
HERE = Path(__file__).parent
OUT = HERE / "app_icon.png"

# the gallery's accent (Linear-ish indigo) → a darker shade for the gradient
TOP = (0.369, 0.412, 0.824)  # #5e6ad2
BOTTOM = (0.216, 0.235, 0.541)


def _png(image, path: Path) -> bool:
    tiff = image.TIFFRepresentation()
    import AppKit

    rep = AppKit.NSBitmapImageRep.imageRepWithData_(tiff)
    data = rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
    return bool(data.writeToFile_atomically_(str(path), True))


def menubar_icons() -> int:
    """Black-on-transparent template glyphs (macOS inverts them for the dark
    menubar, so: pure black + alpha, no colour, no background).

    Drawn by hand rather than from an SF Symbol: at 18px a symbol's thin strokes
    land on half pixels and read as a faint, blurry icon next to the solid
    glyphs its neighbours use. This is the app's own brand mark — a card with
    three text lines — with every edge on a whole pixel.
    """
    import AppKit

    for px, name in ((18, "menubar-icon.png"), (36, "menubar-icon@2x.png")):
        rep = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
            None, px, px, 8, 4, True, False, AppKit.NSDeviceRGBColorSpace, 0, 0
        )
        ctx = AppKit.NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
        AppKit.NSGraphicsContext.saveGraphicsState()
        AppKit.NSGraphicsContext.setCurrentContext_(ctx)

        u = px / 18.0  # 1 unit = 1pt
        card_w, card_h = round(13 * u), round(15 * u)
        x0, y0 = round((px - card_w) / 2), round((px - card_h) / 2)

        AppKit.NSColor.blackColor().setFill()
        AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            AppKit.NSMakeRect(x0, y0, card_w, card_h), round(2.5 * u), round(2.5 * u)
        ).fill()

        # Knock the lines out of the card: transparent in a template image, so
        # the menubar shows through — that contrast is what makes it readable.
        ctx.setCompositingOperation_(AppKit.NSCompositingOperationDestinationOut)
        line_h = max(1, round(1.5 * u))
        gap = max(1, round(2.5 * u))
        inset = round(2.5 * u)
        full = card_w - inset * 2
        top = y0 + card_h - round(4 * u)
        for i, w in enumerate((full, full, round(full * 0.55))):
            AppKit.NSBezierPath.fillRect_(
                AppKit.NSMakeRect(x0 + inset, top - i * (line_h + gap), w, line_h)
            )

        AppKit.NSGraphicsContext.restoreGraphicsState()
        data = rep.representationUsingType_properties_(
            AppKit.NSBitmapImageFileTypePNG, {}
        )
        if not data.writeToFile_atomically_(str(HERE / name), True):
            print(f"write failed: {name}", file=sys.stderr)
            return 1
        print(f"wrote {HERE / name} ({px}x{px})")
    return 0


def main() -> int:
    import AppKit
    import Quartz

    symbol = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
        SYMBOL, None
    )
    if symbol is None:
        print(f"SF Symbol '{SYMBOL}' not found (needs macOS 11+)", file=sys.stderr)
        return 1

    canvas = AppKit.NSImage.alloc().initWithSize_(AppKit.NSMakeSize(SIZE, SIZE))
    canvas.lockFocus()

    inset = SIZE * 0.06
    radius = SIZE * 0.185  # macOS app-icon squircle proportions
    rect = AppKit.NSMakeRect(inset, inset, SIZE - inset * 2, SIZE - inset * 2)
    path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        rect, radius, radius
    )
    AppKit.NSGradient.alloc().initWithStartingColor_endingColor_(
        AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(*TOP, 1.0),
        AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(*BOTTOM, 1.0),
    ).drawInBezierPath_angle_(path, 270.0)

    # drawInRect_ paints the symbol's own (black) colour — setTemplate_ only
    # tints inside AppKit controls — so set the palette explicitly.
    config = AppKit.NSImageSymbolConfiguration.configurationWithPointSize_weight_scale_(
        SIZE * 0.44, AppKit.NSFontWeightMedium, 3  # 3 = NSImageSymbolScaleLarge
    ).configurationByApplyingConfiguration_(
        AppKit.NSImageSymbolConfiguration.configurationWithPaletteColors_(
            [AppKit.NSColor.whiteColor()]
        )
    )
    tinted = symbol.imageWithSymbolConfiguration_(config)

    s = tinted.size()
    box = AppKit.NSMakeRect(
        (SIZE - s.width) / 2, (SIZE - s.height) / 2, s.width, s.height
    )
    tinted.drawInRect_fromRect_operation_fraction_respectFlipped_hints_(
        box,
        AppKit.NSZeroRect,
        AppKit.NSCompositingOperationSourceOver,
        1.0,
        True,
        {AppKit.NSImageHintInterpolation: Quartz.kCGInterpolationHigh},
    )

    canvas.unlockFocus()

    if not _png(canvas, OUT):
        print(f"write failed: {OUT}", file=sys.stderr)
        return 1
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024}KB)")
    return menubar_icons()


if __name__ == "__main__":
    sys.exit(main())
