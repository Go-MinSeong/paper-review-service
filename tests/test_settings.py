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
