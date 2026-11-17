from paper_review import statusitem


def test_icon_is_found():
    """The app's menubar icon resolves from a source checkout (the frozen app
    finds the same file under _MEIPASS)."""
    p = statusitem._icon_path()
    assert p is not None and p.exists() and p.name == "menubar-icon.png"
