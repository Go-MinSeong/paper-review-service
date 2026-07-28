"""Menubar status item for the desktop app.

The standalone `paper-review menubar` (rumps) runs its own NSApplication, so it
can't be reused here — the .app already has one, driven by pywebview. This adds
an NSStatusItem to that existing app instead, so opening the app puts an icon in
the menubar as well as the Dock.

Everything AppKit touches has to happen on the main thread; `install()` may be
called from the boot thread and hops over by itself.
"""

from __future__ import annotations

import webbrowser

# Strong refs: an NSStatusItem released by Python vanishes from the menubar.
_alive: list = []


def _icon():
    from .menubar import _icon_path

    p = _icon_path()
    if p is None:
        return None
    import AppKit

    img = AppKit.NSImage.alloc().initWithContentsOfFile_(str(p))
    if img is None:
        return None
    img.setSize_(AppKit.NSMakeSize(18, 18))
    img.setTemplate_(True)  # let macOS tint it for the light/dark menubar
    return img


def install(port: int, window) -> None:
    """Add the status item. Best-effort — the app is still usable without it."""
    try:
        import AppKit
        from Foundation import NSObject
    except ImportError:
        return

    class _Actions(NSObject):
        def show_(self, _sender):
            AppKit.NSApp.activateIgnoringOtherApps_(True)
            try:
                window.show()
            except Exception:
                pass

        def browser_(self, _sender):
            webbrowser.open(f"http://127.0.0.1:{port}/")

        def quit_(self, _sender):
            AppKit.NSApp.terminate_(None)

    def _build():
        try:
            target = _Actions.alloc().init()
            bar = AppKit.NSStatusBar.systemStatusBar()
            item = bar.statusItemWithLength_(AppKit.NSVariableStatusItemLength)
            img = _icon()
            if img is not None:
                item.button().setImage_(img)
            else:  # no icon file (e.g. a partial install) — still show something
                item.button().setTitle_("◫")

            menu = AppKit.NSMenu.alloc().init()
            head = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                f"Running · localhost:{port}", None, ""
            )
            head.setEnabled_(False)
            menu.addItem_(head)
            menu.addItem_(AppKit.NSMenuItem.separatorItem())
            for title, sel, key in (
                ("Show Window", "show:", ""),
                ("Open in Browser", "browser:", ""),
            ):
                mi = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    title, sel, key
                )
                mi.setTarget_(target)
                menu.addItem_(mi)
            menu.addItem_(AppKit.NSMenuItem.separatorItem())
            q = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Quit paper-review", "quit:", "q"
            )
            q.setTarget_(target)
            menu.addItem_(q)

            item.setMenu_(menu)
            _alive.extend([item, target, menu])
        except Exception as e:  # never take the app down over a menubar extra
            print(f"paper-review: status item failed: {e}")

    AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(_build)
