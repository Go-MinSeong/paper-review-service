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
        json.dumps(
            [
                {"id": "fig1", "data_uri": "data:image/png;base64,AA"},
                {"id": "tbl1", "html": "<table></table>"},  # no data_uri → dropped
            ]
        )
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


def test_push_carries_report_and_records_slot(paper):
    """The phone shows Summary too, and the gallery must know which paper the
    slot holds without a network call."""
    (paper / "2600.00001" / "report.md").write_text("## 00 TL;DR\n요약.\n")
    seen = {}

    def handler(req):
        seen["json"] = json.loads(req.content)
        return httpx.Response(200, json={"ok": True, "rev": 7, "slug": "2600.00001"})

    out = R.push("2600.00001", paper, client=_client(handler))
    assert "00 TL;DR" in seen["json"]["report_md"]
    assert out["has_report"] is True
    assert R.slot_state(paper)["slug"] == "2600.00001"


def test_push_without_report_is_fine(paper):
    def handler(req):
        assert json.loads(req.content)["report_md"] == ""
        return httpx.Response(200, json={"ok": True, "rev": 1, "slug": "2600.00001"})

    assert R.push("2600.00001", paper, client=_client(handler))["has_report"] is False


def test_slot_state_absent_or_corrupt(tmp_path):
    assert R.slot_state(tmp_path) == {}
    (tmp_path / R.SLOT_STATE).write_text("not json")
    assert R.slot_state(tmp_path) == {}


def test_save_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "CONFIG_PATH", tmp_path / "remote.json")
    monkeypatch.delenv("PAPER_REVIEW_REMOTE_URL", raising=False)
    monkeypatch.delenv("PAPER_REVIEW_REMOTE_TOKEN", raising=False)

    assert R.read_config() == {"url": "", "token_set": False, "from_env": False}
    R.save_config("https://a.vercel.app/", "secret")
    assert R.load_config() == {"url": "https://a.vercel.app", "token": "secret"}
    # the UI never sends the token back — omitting it must keep the stored one
    R.save_config("https://b.vercel.app", None)
    assert R.load_config()["token"] == "secret"
    assert R.read_config() == {
        "url": "https://b.vercel.app",
        "token_set": True,
        "from_env": False,
    }
    # config file is not world-readable (it holds a shared secret)
    assert oct((tmp_path / "remote.json").stat().st_mode)[-3:] == "600"
    # empty url clears everything
    R.save_config("", None)
    assert not (tmp_path / "remote.json").exists()


def test_save_config_rejects_bad_input(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "CONFIG_PATH", tmp_path / "remote.json")
    with pytest.raises(ValueError):
        R.save_config("my-app.vercel.app", "t")  # no scheme
    with pytest.raises(ValueError):
        R.save_config("https://a.vercel.app", "")  # url without a token
