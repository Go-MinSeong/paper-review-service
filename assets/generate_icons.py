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
# Menubar glyph: same symbol, but the magnifier detail turns to mush at 18px.
MENUBAR_SYMBOL = "doc.text"
MENUBAR_PT = 16.0  # inside an 18pt slot, matching Apple's menubar metrics

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
    """Black-on-transparent template glyphs. macOS inverts a template image for
    the dark menubar, so it must be pure black + alpha — no colour, no bg."""
    import AppKit

    symbol = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
        MENUBAR_SYMBOL, None
    )
    if symbol is None:
        print(f"SF Symbol '{MENUBAR_SYMBOL}' not found", file=sys.stderr)
        return 1
    config = AppKit.NSImageSymbolConfiguration.configurationWithPointSize_weight_scale_(
        # Regular weight rendered noticeably thinner than the neighbouring
        # menubar glyphs; medium matches their optical weight.
        MENUBAR_PT,
        AppKit.NSFontWeightMedium,
        2,  # 2 = medium scale
    ).configurationByApplyingConfiguration_(
        AppKit.NSImageSymbolConfiguration.configurationWithPaletteColors_(
            [AppKit.NSColor.blackColor()]
        )
    )
    glyph = symbol.imageWithSymbolConfiguration_(config)

    for scale, name in ((1, "menubar-icon.png"), (2, "menubar-icon@2x.png")):
        px = int(18 * scale)
        # Draw into an explicitly-sized bitmap. NSImage.lockFocus() would capture
        # at the display's backing scale instead, so @2x came out 72px on this
        # Retina Mac.
        rep = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
            None, px, px, 8, 4, True, False, AppKit.NSDeviceRGBColorSpace, 0, 0
        )
        ctx = AppKit.NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
        AppKit.NSGraphicsContext.saveGraphicsState()
        AppKit.NSGraphicsContext.setCurrentContext_(ctx)
        # Fit the glyph inside the slot with a little breathing room.
        s = glyph.size()
        fit = (px * 0.92) / max(s.width, s.height)
        w, h = s.width * fit, s.height * fit
        glyph.drawInRect_fromRect_operation_fraction_(
            AppKit.NSMakeRect((px - w) / 2, (px - h) / 2, w, h),
            AppKit.NSZeroRect,
            AppKit.NSCompositingOperationSourceOver,
            1.0,
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
