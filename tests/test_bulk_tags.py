"""Bulk edits and tag renames — doing either one paper at a time doesn't scale
(tagging an imported batch of 90 meant 90 menus)."""

import pytest
from fastapi.testclient import TestClient

from paper_review.server import app as A
from paper_review.server.app import app

client = TestClient(app)


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "SERVICE_ROOT", tmp_path)
    from paper_review.server import tags as T

    monkeypatch.setattr(T, "SERVICE_ROOT", tmp_path)
    A._ROW_CACHE.clear()
    for slug, tags in (("p1", "[VLM, agents]"), ("p2", "[Agent]"), ("p3", "[LLM]")):
        d = tmp_path / slug
        d.mkdir()
        (d / "workbench.md").write_text(
            f'---\nstatus: to_read\ntags: {tags}\ntitle_en: "{slug}"\n---\n# body\n'
        )
    return tmp_path


def _tags(lib, slug):
    from paper_review.server.tags import _parse_tags_value, _read_frontmatter_tags

    return _read_frontmatter_tags(lib / slug / "workbench.md")


def test_bulk_status_and_tags(lib):
    r = client.post(
        "/papers/bulk",
        json={
            "slugs": ["p1", "p2"],
            "status": "archived",
            "add_tags": ["survey"],
            "remove_tags": ["agents"],
        },
    )
    assert r.status_code == 200 and r.json()["changed"] == ["p1", "p2"]
    assert "status: archived" in (lib / "p1" / "workbench.md").read_text()
    assert _tags(lib, "p1") == ["VLM", "survey"]
    assert set(_tags(lib, "p2")) == {"Agent", "survey"}
    assert "status: to_read" in (lib / "p3" / "workbench.md").read_text(), "untouched"


def test_bulk_skips_unknown_slugs_instead_of_failing(lib):
    r = client.post("/papers/bulk", json={"slugs": ["p1", "nope"], "status": "exported"})
    assert r.status_code == 200
    assert r.json()["changed"] == ["p1"] and r.json()["missing"] == ["nope"]


def test_rename_tag_merges_case_variants(lib):
    """Agent vs agents is exactly the drift this exists to fix."""
    r = client.post("/tags/rename", json={"old": "Agent", "new": "agents"})
    assert r.status_code == 200 and r.json()["papers"] == 1
    assert _tags(lib, "p2") == ["agents"]
    # merging into a tag a paper already has must not duplicate it
    client.post("/tags/rename", json={"old": "VLM", "new": "agents"})
    assert _tags(lib, "p1") == ["agents"]


def test_rename_to_empty_removes_the_tag(lib):
    assert client.post("/tags/rename", json={"old": "LLM", "new": ""}).json()["papers"] == 1
    assert _tags(lib, "p3") == []


def test_rename_requires_a_source_tag(lib):
    assert client.post("/tags/rename", json={"old": " ", "new": "x"}).status_code == 400


def test_card_overlay_buttons_do_not_share_a_slot():
    """The pick checkbox first shipped at left:8px — exactly on top of the
    DELETE button. Every overlay button needs its own column."""
    import re

    from paper_review.server.app import _STATIC_DIR

    css = (_STATIC_DIR / "gallery.css").read_text()
    lefts = {}
    for sel in ("card-pick", "card-del", "card-tagedit", "card-log", "card-remote"):
        m = re.search(rf"\.{sel} \{{[^}}]*?left: (\d+)px", css, re.S)
        assert m, sel
        lefts[sel] = int(m.group(1))
    assert len(set(lefts.values())) == len(lefts), f"overlapping slots: {lefts}"
    assert min(abs(a - b) for a in lefts.values() for b in lefts.values() if a != b) >= 26


def test_bulk_bar_floats_instead_of_scrolling_under_the_header():
    from paper_review.server.app import _STATIC_DIR

    css = (_STATIC_DIR / "gallery.css").read_text()
    block = css[css.index(".bulk-bar {") : css.index("}", css.index(".bulk-bar {"))]
    assert "position: fixed" in block, "in-flow, it slid under the sticky header"


def test_search_reaches_archived_papers():
    """97 of 109 papers here are archived; searching the default view returned
    nothing and you had to know to switch to Archived first."""
    from paper_review.server.app import _STATIC_DIR

    js = (_STATIC_DIR / "gallery.js").read_text()
    i = js.index("const filtered = papers.filter")
    block = js[i : i + 600]
    assert "p.status === 'archived' && !searchQuery" in block, (
        "archived must stay hidden by default but be searchable"
    )


def test_pdf_pane_has_its_own_zoom():
    """WebKit draws the PDF with a native plugin inside an iframe, so it can't
    be zoomed from inside — the pane scales the iframe instead."""
    from paper_review.server.app import _STATIC_DIR, _TEMPLATES_DIR

    js = (_STATIC_DIR / "detail.js").read_text()
    assert "applyPdfZoom" in js and "gesturechange" in js
    assert "e.ctrlKey" in js  # a trackpad pinch arrives as ctrl+wheel
    html = (_TEMPLATES_DIR / "detail.html").read_text()
    for btn in ("pdf-zoom-in", "pdf-zoom-out", "pdf-zoom-reset"):
        assert btn in html, btn
