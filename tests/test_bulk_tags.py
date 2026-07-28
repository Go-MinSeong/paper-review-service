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
