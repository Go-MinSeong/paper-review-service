#!/usr/bin/env python3
"""App icon — an SF Symbol on a rounded-rect background, rendered to PNG.

Drawn with pyobjc (already a dependency via rumps/pywebview) rather than adding
Pillow. Modelled on the same generator in the daily-log project so the three
apps sit consistently in the Dock.

    .venv/bin/python assets/generate_icons.py
    → assets/app_icon.png (1024x1024)

packaging/build.sh turns it into .icns with sips + iconutil.
"""

from __future__ import annotations

import sys
from pathlib import Path

SIZE = 1024.0
SYMBOL = "doc.text.magnifyingglass"  # read a paper, closely
OUT = Path(__file__).parent / "app_icon.png"

# the gallery's accent (Linear-ish indigo) → a darker shade for the gradient
TOP = (0.369, 0.412, 0.824)  # #5e6ad2
BOTTOM = (0.216, 0.235, 0.541)


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

    tiff = canvas.TIFFRepresentation()
    rep = AppKit.NSBitmapImageRep.imageRepWithData_(tiff)
    png = rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
    if not png.writeToFile_atomically_(str(OUT), True):
        print(f"write failed: {OUT}", file=sys.stderr)
        return 1

    print(f"wrote {OUT} ({OUT.stat().st_size // 1024}KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
