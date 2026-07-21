import json

import httpx
import pytest

from paper_review import remote as R


@pytest.fixture
def paper(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_REVIEW_REMOTE_URL", "https://x.vercel.app")
    monkeypatch.setenv("PAPER_REVIEW_REMOTE_TOKEN", "tkn")
    d = tmp_path / "2600.00001"
    d.mkdir()
    (d / "workbench.md").write_text(
        '---\nslug: 2600.00001\ntitle_en: "T"\n---\n# body\n'
    )
    (d / "2600.00001_figures.json").write_text(
        json.dumps([
            {"id": "fig1", "data_uri": "data:image/png;base64,AA"},
            {"id": "tbl1", "html": "<table></table>"},  # no data_uri → dropped
        ])
    )
    return tmp_path


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_push_payload(paper):
    seen = {}

    def handler(req):
        seen["headers"] = dict(req.headers)
        seen["json"] = json.loads(req.content)
        return httpx.Response(200, json={"ok": True, "rev": 3, "slug": "2600.00001"})

    out = R.push("2600.00001", paper, client=_client(handler))
    assert out["rev"] == 3 and out["url"] == "https://x.vercel.app"
    assert seen["headers"]["x-token"] == "tkn"
    j = seen["json"]
    assert j["force"] is True and j["slug"] == "2600.00001" and j["title"] == "T"
    assert j["figures"] == [{"id": "fig1", "data_uri": "data:image/png;base64,AA"}]


def test_pull_writes_and_backs_up(paper):
    new_md = "---\nslug: 2600.00001\n---\n# edited on mobile\n"

    def handler(req):
        return httpx.Response(200, json={"slug": "2600.00001", "md": new_md, "rev": 5})

    out = R.pull(paper, client=_client(handler))
    assert out == {"slug": "2600.00001", "rev": 5, "changed": True}
    wb = paper / "2600.00001" / "workbench.md"
    assert wb.read_text() == new_md
    assert "# body" in (paper / "2600.00001" / "workbench.md.bak").read_text()
    # second pull: no change
    out2 = R.pull(paper, client=_client(handler))
    assert out2["changed"] is False


def test_pull_empty_slot(paper):
    def handler(req):
        return httpx.Response(200, json={"empty": True})

    with pytest.raises(RuntimeError):
        R.pull(paper, client=_client(handler))
