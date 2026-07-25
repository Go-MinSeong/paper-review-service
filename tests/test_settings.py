import pytest
from fastapi import HTTPException

from paper_review.server import settings as S


def test_base_name_strips_variant_suffix():
    assert S._base_name("corgi.jpg") == "corgi"
    assert S._base_name("corgi-2.jpg") == "corgi"
    assert S._base_name("redpanda-12.png") == "redpanda"


def test_skill_dir_rejects_traversal():
    for bad in ["../etc", "a/b", "..", "", "x;y"]:
        with pytest.raises(HTTPException):
            S._skill_dir(bad)


def test_safe_char_name_rejects_bad_inputs():
    for bad in ["../x.jpg", "a/b.png", ".hidden.jpg", "note.txt", ""]:
        with pytest.raises(HTTPException):
            S._safe_char_name(bad)
    assert S._safe_char_name("corgi-2.jpg") == "corgi-2.jpg"


def test_illustration_groups_structure():
    g = S.illustration_groups()
    assert set(g) == {"groups", "tag_groups"}
    have = set(S.list_illustrations())
    # every file listed in a group actually exists
    for files in g["groups"].values():
        for f in files:
            assert f in have
    # every tag maps to a real group
    for grp in g["tag_groups"].values():
        assert grp in g["groups"]


def test_drafts_dir_resolution(tmp_path, monkeypatch):
    from paper_review import config as C

    monkeypatch.setattr(C, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.delenv("PAPER_REVIEW_DRAFTS_DIR", raising=False)
    # default
    assert C.get_drafts_dir() == C.DEFAULT_DRAFTS_DIR
    # settings.json wins over default
    C.save_settings({"drafts_dir": "/tmp/my-vault/drafts"})
    assert str(C.get_drafts_dir()) == "/tmp/my-vault/drafts"
    # env wins over settings
    monkeypatch.setenv("PAPER_REVIEW_DRAFTS_DIR", "/tmp/env-vault/drafts")
    assert str(C.get_drafts_dir()) == "/tmp/env-vault/drafts"


def test_splash_boot_sequence(monkeypatch):
    """The launch screen must report progress, hand over to the gallery, and
    surface failures instead of leaving a blank window."""
    from paper_review import app as A

    class W:
        def __init__(self):
            self.js, self.url = [], None

        def evaluate_js(self, s):
            self.js.append(s)

        def load_url(self, u):
            self.url = u

    monkeypatch.setattr(A, "_install_skills", lambda: None)
    monkeypatch.setattr(A, "start_server", lambda port: None)

    monkeypatch.setattr(A, "_wait_server", lambda port, timeout=20.0: True)
    ok = W()
    A._boot(ok, 7777)
    assert ok.url == "http://127.0.0.1:7777/"
    assert any("prStatus" in j for j in ok.js) and not any("prFail" in j for j in ok.js)

    monkeypatch.setattr(A, "_wait_server", lambda port, timeout=20.0: False)
    bad = W()
    A._boot(bad, 7777)
    assert bad.url is None and any("prFail" in j for j in bad.js)


def test_splash_fail_js_escapes_newlines():
    from paper_review.splash import fail_js

    js = fail_js('line1\nline2 "quoted"')
    assert "\\n" in js and "\n" not in js  # real newline would break the JS literal
