"""Papers live under papers/<status>/<slug>/ and move with their status."""

from pathlib import Path

import pytest

from paper_review import library as L


def _paper(root: Path, slug: str, status: str, flat: bool = False) -> Path:
    d = (root / slug) if flat else (root / "papers" / status / slug)
    d.mkdir(parents=True)
    (d / "workbench.md").write_text(f"---\nslug: {slug}\nstatus: {status}\n---\n# x\n")
    return d


def test_finds_papers_in_any_status_folder(tmp_path):
    _paper(tmp_path, "a", "archived")
    _paper(tmp_path, "b", "in_progress")
    assert L.paper_dir("a", tmp_path).parent.name == "archived"
    assert L.paper_dir("b", tmp_path).parent.name == "in_progress"
    assert L.paper_dir("nope", tmp_path) is None
    assert {p.name for p in L.iter_papers(tmp_path)} == {"a", "b"}


def test_still_finds_papers_left_in_the_old_flat_layout(tmp_path):
    """Resolution must not depend on a migration having run."""
    _paper(tmp_path, "old", "in_progress", flat=True)
    assert L.paper_dir("old", tmp_path) == tmp_path / "old"
    assert [p.name for p in L.iter_papers(tmp_path)] == ["old"]


def test_status_change_moves_the_folder(tmp_path):
    _paper(tmp_path, "a", "in_progress")
    dest = L.move_to_status("a", "archived", tmp_path)
    assert dest == tmp_path / "papers" / "archived" / "a"
    assert dest.is_dir() and not (tmp_path / "papers" / "in_progress" / "a").exists()
    assert (dest / "workbench.md").exists(), "content travels with it"


def test_move_is_a_no_op_when_it_would_overwrite(tmp_path):
    """Better a folder in the wrong place than a review lost to a collision."""
    _paper(tmp_path, "a", "in_progress")
    _paper(tmp_path, "a", "archived")  # same slug already parked there
    kept = L.move_to_status("a", "archived", tmp_path)
    assert kept == tmp_path / "papers" / "in_progress" / "a"
    assert (tmp_path / "papers" / "archived" / "a" / "workbench.md").exists()


def test_unknown_status_does_not_create_junk_folders(tmp_path):
    _paper(tmp_path, "a", "in_progress")
    L.move_to_status("a", "not-a-status", tmp_path)
    assert not (tmp_path / "papers" / "not-a-status").exists()
    assert L.paper_dir("a", tmp_path).parent.name == "to_read"


def test_migration_sorts_by_the_status_in_the_file(tmp_path):
    _paper(tmp_path, "one", "archived", flat=True)
    _paper(tmp_path, "two", "exported", flat=True)
    (tmp_path / "_logs").mkdir()  # service dirs must be left alone
    (tmp_path / "notes.txt").write_text("x")

    out = L.migrate(tmp_path)
    assert sorted(out["moved"]) == [("one", "archived"), ("two", "exported")]
    assert (tmp_path / "papers" / "archived" / "one" / "workbench.md").exists()
    assert (tmp_path / "papers" / "exported" / "two").is_dir()
    assert (tmp_path / "_logs").is_dir() and (tmp_path / "notes.txt").exists()
    assert L.migrate(tmp_path)["moved"] == [], "second run has nothing to do"


def test_migration_leaves_a_paper_that_is_busy(tmp_path):
    """Its folder is the cwd of a running claude process."""
    _paper(tmp_path, "busy", "in_progress", flat=True)
    _paper(tmp_path, "idle", "in_progress", flat=True)
    out = L.migrate(tmp_path, is_busy=lambda s: s == "busy")
    assert out["moved"] == [("idle", "in_progress")]
    assert out["skipped"] == ["busy"]
    assert (tmp_path / "busy").is_dir()
