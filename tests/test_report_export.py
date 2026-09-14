"""Exporting the Summary: everything opens on paper, and the HTML stands alone."""

import json

from fastapi.testclient import TestClient

import paper_review.server.app as A

REPORT = (
    "<html><head><title>R</title></head><body>"
    "<details><summary>깊게 — 왜</summary><p>접혀 있던 내용</p></details>"
    '<img class="paper-fig" src="/paper/2600.33333/fig/fig1">'
    "</body></html>"
)


def _paper(tmp_path, monkeypatch):
    d = tmp_path / "2600.33333"
    d.mkdir()
    (d / "workbench.md").write_text("---\nstatus: to_read\n---\n")
    (d / "report.html").write_text(REPORT)
    (d / "2600.33333_figures.json").write_text(
        json.dumps([{"id": "fig1", "data_uri": "data:image/png;base64,AAAA"}])
    )
    monkeypatch.setattr(A, "_paper_dir", lambda slug: d)
    return TestClient(A.app)


def test_a_printed_summary_opens_its_collapsed_blocks(tmp_path, monkeypatch):
    """A <details> block cannot be clicked open on paper, so a printout used to
    drop whatever was folded inside it."""
    c = _paper(tmp_path, monkeypatch)

    for q in ("", "?print=1"):
        html = c.get(f"/paper/2600.33333/report{q}").text
        assert "id='pr-print-expand'" in html, q
        assert "beforeprint" in html, q

    printable = c.get("/paper/2600.33333/report?print=1").text
    assert "__prOpenAllDetails" in printable.split("id='pr-printbar'", 1)[-1] or (
        "window.__prOpenAllDetails && window.__prOpenAllDetails()" in printable
    )


def test_the_html_export_is_a_single_file_that_downloads(tmp_path, monkeypatch):
    """Downloaded reports pointed figures at this server, so opened anywhere else
    every image was broken — and the app would open HTML in its window rather
    than offer to save it."""
    c = _paper(tmp_path, monkeypatch)
    r = c.get("/paper/2600.33333/report/export.html")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/octet-stream")
    assert "attachment" in r.headers["content-disposition"]
    assert "2600.33333-summary.html" in r.headers["content-disposition"]

    html = r.content.decode("utf-8")
    assert "/paper/2600.33333/fig/" not in html, "figures must travel inside the file"
    assert 'src="data:image/png;base64,AAAA"' in html
    assert "<details>" in html, "collapsibles stay interactive in HTML"
    assert "id='pr-contrast'" in html and "id='pr-print-expand'" in html
