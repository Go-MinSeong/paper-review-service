"""The menubar dropdown is the only UI for the server, so its rows have to be
current and each has to do something."""

import pytest

rumps = pytest.importorskip("rumps")

from paper_review import menubar as M


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(M, "_lan_ip", lambda: "10.0.0.5")
    return M.PaperReviewMenubarApp(port=7300)


def _titles(app):
    return [getattr(i, "title", i) for i in app.app.menu.values()]


def test_menu_has_no_duplicate_gallery_row(app):
    titles = _titles(app)
    assert "Open Gallery" in titles
    # the old menu repeated the URL as its own row with the same callback
    assert not [t for t in titles if str(t).startswith("http://127.0.0.1")]


def test_every_row_is_actionable_except_status(app):
    dead = [
        i
        for i in app.app.menu.values()
        if isinstance(i, rumps.MenuItem) and i.callback is None
    ]
    assert [i.title for i in dead] == [app.menu_status.title], "only status is inert"


def test_phone_url_is_hidden_when_loopback_only(app, monkeypatch):
    """The server binds loopback by default now, so advertising a LAN address
    would point at something that doesn't answer."""
    monkeypatch.delenv("PAPER_REVIEW_HOST", raising=False)
    app._refresh_lan()
    assert "remote slot" in app.menu_lan.title
    assert app._lan_url() is None


def test_phone_url_tracks_the_current_network(app, monkeypatch):
    monkeypatch.setenv("PAPER_REVIEW_HOST", "0.0.0.0")  # LAN opt-in
    app._refresh_lan()
    assert "10.0.0.5:7300" in app.menu_lan.title
    # the Mac moves networks — the row used to keep its launch-time IP forever
    monkeypatch.setattr(M, "_lan_ip", lambda: "192.168.1.9")
    app._refresh_lan()
    assert "192.168.1.9:7300" in app.menu_lan.title
    monkeypatch.setattr(M, "_lan_ip", lambda: None)
    app._refresh_lan()
    assert "offline" in app.menu_lan.title


def test_status_lines_are_plain_text(app):
    app._set_status("Running · localhost:7300", "green")
    assert app.menu_status.title == "Running · localhost:7300"
    assert "●" not in app.menu_status.title


def test_icon_is_found_and_is_a_template(app):
    p = M._icon_path()
    assert p is not None and p.exists(), "menubar icon must resolve"
    assert p.name == "menubar-icon.png"
