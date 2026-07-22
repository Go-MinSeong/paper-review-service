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
