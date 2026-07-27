"""The retired Wrap-up/메타 fields were removed from the generator in 2.6.0 but
never cleaned out of workbenches created before that."""

from paper_review.workbench import migrate_workbench, strip_legacy_wrapup_fields

OLD = """## Wrap-up

- **한 줄 contribution**:
- **가장 약한 부분**:
- **후속으로 읽을 논문**:
  1. 
  2. 
  3. 

## 메타

- **총 소요 시간**:
- **마지막 세션**:
"""

NEW = """## Wrap-up

- **한 줄 contribution**:

## 메타

- **총 소요 시간**:
"""


def test_strips_empty_legacy_fields():
    assert strip_legacy_wrapup_fields(OLD) == NEW


def test_is_idempotent():
    once = strip_legacy_wrapup_fields(OLD)
    assert strip_legacy_wrapup_fields(once) == once


def test_keeps_fields_the_user_actually_filled():
    """Never delete the user's writing — only the empty placeholders."""
    filled = OLD.replace(
        "- **가장 약한 부분**:", "- **가장 약한 부분**: 베이스라인이 하나뿐"
    ).replace("  1. \n", "  1. Attention is all you need\n")
    out = strip_legacy_wrapup_fields(filled)
    assert "베이스라인이 하나뿐" in out
    assert "Attention is all you need" in out
    assert "후속으로 읽을 논문" in out  # its list has a real entry
    assert "마지막 세션" not in out  # still empty → goes


def test_leaves_current_workbenches_alone():
    assert strip_legacy_wrapup_fields(NEW) == NEW


def test_migrate_reports_whether_it_changed(tmp_path):
    p = tmp_path / "workbench.md"
    p.write_text(OLD)
    assert migrate_workbench(p) is True
    assert p.read_text() == NEW
    assert migrate_workbench(p) is False  # nothing left to do
    assert migrate_workbench(tmp_path / "missing.md") is False


def test_gallery_migrates_without_touching_edit_times(tmp_path, monkeypatch):
    """Opening the gallery cleans old workbenches, but housekeeping must not
    make every paper look freshly edited."""
    import os

    from paper_review.server import app as A

    monkeypatch.setattr(A, "SERVICE_ROOT", tmp_path)
    d = tmp_path / "2500.00001"
    d.mkdir()
    wb = d / "workbench.md"
    wb.write_text("---\nstatus: in_progress\n---\n\n" + OLD)
    old_mtime = 1_600_000_000
    os.utime(wb, (old_mtime, old_mtime))

    rows = A._list_papers()

    assert "마지막 세션" not in wb.read_text()
    assert int(wb.stat().st_mtime) == old_mtime
    assert rows[0]["updated_at"] == old_mtime
