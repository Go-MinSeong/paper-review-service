"""A regeneration that doesn't finish must not cost the report that was there.

qwen3.8: a run with extra Summary requests wrote its skeleton (nav + an empty
<!--SECTIONS--> marker), was killed at the timeout before editing the
sections in, and the good report was gone."""

import asyncio
import os

from paper_review.server import analyze as A

OLD = (
    '<nav><a href="#s0">00</a><a href="#s1">01</a></nav>'
    '<section id="s0">old</section><section id="s1">old</section>'
)
NEW = OLD.replace("old", "new")
SKELETON = '<nav><a href="#s0">00</a><a href="#s1">01</a></nav><!--SECTIONS-->'


def _regenerate(tmp_path, monkeypatch, writes, stop=None, code=0, existing=True):
    d = tmp_path / "2601.00003"
    d.mkdir()
    (d / "workbench.md").write_text("---\nstatus: to_read\n---\n")
    (d / "report-requests.md").write_text("## 2026-09-15 10:29\n\n**요청**: 더 쉽게\n")
    if existing:
        (d / "report.html").write_text(OLD)
        (d / "report.md").write_text("old md")

    async def fake_claude(cmd, cwd, job, timeout):
        p = d / "report.html"
        p.write_text(writes)
        later = p.stat().st_mtime + 5
        os.utime(p, (later, later))
        return stop, code, "", "s-report"

    monkeypatch.setattr(A, "_stream_claude", fake_claude)
    job = A.AnalysisJob(job_id="j", slug=d.name)
    return d, asyncio.run(A.generate_report(d, None, job=job))


def test_a_timed_out_skeleton_leaves_the_previous_report_in_place(
    tmp_path, monkeypatch
):
    d, res = _regenerate(tmp_path, monkeypatch, SKELETON, stop="timeout", code=None)

    assert not res["ok"] and res["error"] == "timeout"
    assert (d / "report.html").read_text() == OLD
    assert (d / "report.md").read_text() == "old md"
    assert [p.read_text() for p in (d / ".history").glob("failed-*report.html")] == [
        SKELETON
    ]
    assert (d / "report-requests.md").exists(), "requests were never applied"


def test_a_run_that_exits_with_sections_missing_counts_as_failed(tmp_path, monkeypatch):
    d, res = _regenerate(tmp_path, monkeypatch, SKELETON)

    assert not res["ok"] and "unfinished" in res["error"]
    assert (d / "report.html").read_text() == OLD
    assert (d / "report-requests.md").exists()


def test_a_complete_report_replaces_the_old_one(tmp_path, monkeypatch):
    d, res = _regenerate(tmp_path, monkeypatch, NEW)

    assert res["ok"]
    assert (d / "report.html").read_text() == NEW
    assert not (d / "report-requests.md").exists(), "applied requests are archived"


def test_a_failed_first_report_is_not_shown_as_the_report(tmp_path, monkeypatch):
    d, res = _regenerate(tmp_path, monkeypatch, SKELETON, existing=False)

    assert not res["ok"]
    assert not (d / "report.html").exists()
    assert list((d / ".history").glob("failed-*report.html"))
