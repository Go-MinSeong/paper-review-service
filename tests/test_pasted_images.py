"""A pasted screenshot must not be saved inside workbench.md as base64 —
ten of them made a 100KB review 14.5MB and every view of it slow."""

import base64
import json

from fastapi.testclient import TestClient

import paper_review.server.app as A

PNG_A = "data:image/png;base64," + base64.b64encode(b"\x89PNG-a" * 50).decode()
PNG_B = "data:image/png;base64," + base64.b64encode(b"\x89PNG-b" * 50).decode()


def _paper(tmp_path, monkeypatch):
    d = tmp_path / "2610.31329"
    d.mkdir()
    (d / "workbench.md").write_text("---\nstatus: to_read\n---\n")
    (d / "2610.31329_figures.json").write_text(
        json.dumps([{"id": "fig1", "data_uri": "data:image/png;base64,AAAA"}])
    )
    monkeypatch.setattr(A, "_paper_dir", lambda slug: d)
    return d, TestClient(A.app)


def test_pasted_images_become_figures_and_the_text_stays_small(tmp_path, monkeypatch):
    d, c = _paper(tmp_path, monkeypatch)
    text = f"## 4 Results\n\n![image.png]({PNG_A})\n\n![image.png]({PNG_B})\n"
    assert (
        c.put("/paper/2610.31329/workbench.md", json={"text": text}).status_code == 200
    )

    saved = (d / "workbench.md").read_text()
    assert "data:image" not in saved
    assert "![image.png](/paper/2610.31329/fig/paste1)" in saved
    assert "![image.png](/paper/2610.31329/fig/paste2)" in saved

    figs = json.loads((d / "2610.31329_figures.json").read_text())
    assert [f["id"] for f in figs] == ["fig1", "paste1", "paste2"]
    r = c.get("/paper/2610.31329/fig/paste1")
    assert r.status_code == 200 and r.content == b"\x89PNG-a" * 50


def test_saving_the_same_paste_again_does_not_duplicate_it(tmp_path, monkeypatch):
    """The editor keeps its base64 until the next reload, so a second save
    sends the same image again."""
    d, c = _paper(tmp_path, monkeypatch)
    for _ in range(2):
        c.put("/paper/2610.31329/workbench.md", json={"text": f"![x]({PNG_A})"})
    figs = json.loads((d / "2610.31329_figures.json").read_text())
    assert [f["id"] for f in figs] == ["fig1", "paste1"]
