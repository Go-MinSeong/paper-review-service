"""Analyze now produces BOTH the Detail sections and the Summary report in one
tracked job, so the Summary can't lag a version behind."""

import asyncio
from pathlib import Path

import pytest

from paper_review.server import analyze as A

WB_ALL_DONE = """---
status: in_progress
---

## 섹션별 리뷰

### 1 Intro
<!-- section_id: 1 -->
**핵심 해설**
done.
"""


def _paper(tmp_path: Path, wb: str) -> Path:
    d = tmp_path / "2601.00001"
    d.mkdir()
    (d / "workbench.md").write_text(wb)
    return d


def _run(job, d, body):
    asyncio.run(A._run_analysis(job, d, body))


@pytest.fixture(autouse=True)
def _no_jobs():
    A._jobs.clear()
    yield
    A._jobs.clear()


def test_report_runs_after_sections(tmp_path, monkeypatch):
    d = _paper(tmp_path, WB_ALL_DONE)
    calls = []

    async def fake_report(paper_dir, model, timeout=900, job=None):
        calls.append(model)
        (paper_dir / "report.html").write_text("<html></html>")
        assert job is not None and job.phase == "report"
        return {"ok": True}

    monkeypatch.setattr(A, "generate_report", fake_report)
    monkeypatch.setattr(A, "_needs_prelude", lambda t: False)

    async def fake_section(paper_dir, heading, line_range, model, timeout, job, cont=True):
        return True

    monkeypatch.setattr(A, "_analyze_one_section", fake_section)
    monkeypatch.setattr(
        A, "_parse_unfinished_sections", lambda d, t: [("1 Intro", "1-9")]
    )

    job = A.AnalysisJob(job_id="t1", slug=d.name)
    _run(job, d, A.AnalyzeBody(model="m"))

    assert job.status == "done"
    assert calls == ["m"], "report must be built in the same run"
    assert job.phase == "report"
    assert any("report" in line for line in job.log)


def test_report_backfilled_when_nothing_to_analyze(tmp_path, monkeypatch):
    """All sections already done but no report yet → build the missing Summary."""
    d = _paper(tmp_path, WB_ALL_DONE)
    built = []

    async def fake_report(paper_dir, model, timeout=900, job=None):
        built.append(True)
        return {"ok": True}

    monkeypatch.setattr(A, "generate_report", fake_report)
    monkeypatch.setattr(A, "_needs_prelude", lambda t: False)
    monkeypatch.setattr(A, "_parse_unfinished_sections", lambda d, t: [])

    job = A.AnalysisJob(job_id="t2", slug=d.name)
    _run(job, d, A.AnalyzeBody())
    assert built and job.status == "done"

    # …and it is NOT rebuilt when one already exists and nothing changed.
    (d / "report.html").write_text("<html></html>")
    built.clear()
    job2 = A.AnalysisJob(job_id="t3", slug=d.name)
    _run(job2, d, A.AnalyzeBody())
    assert not built


def test_report_failure_does_not_fail_analyze(tmp_path, monkeypatch):
    d = _paper(tmp_path, WB_ALL_DONE)

    async def boom(paper_dir, model, timeout=900, job=None):
        raise RuntimeError("claude died")

    monkeypatch.setattr(A, "generate_report", boom)
    monkeypatch.setattr(A, "_needs_prelude", lambda t: False)
    monkeypatch.setattr(A, "_parse_unfinished_sections", lambda d, t: [])

    job = A.AnalysisJob(job_id="t4", slug=d.name)
    _run(job, d, A.AnalyzeBody())
    assert job.status == "done"  # sections are written; the report is best-effort
    assert any("리포트 실패" in line for line in job.log)


def test_start_report_returns_immediately_with_progress(tmp_path, monkeypatch):
    """The report route must not block for minutes — it starts a job whose
    progress the UI reads from /analyze/status."""
    d = _paper(tmp_path, WB_ALL_DONE)
    gate = asyncio.Event()

    async def slow_report(paper_dir, model, timeout=900, job=None):
        await gate.wait()
        return {"ok": True}

    monkeypatch.setattr(A, "generate_report", slow_report)

    async def scenario():
        out = await A.start_report(d.name, d, "m")
        assert out["already_running"] is False
        await asyncio.sleep(0)  # let the task start
        s = A.get_status(d.name)
        assert s["status"] == "running" and s["phase"] == "report"
        # a second request while running must not spawn another claude
        again = await A.start_report(d.name, d, "m")
        assert again["already_running"] is True
        gate.set()
        for _ in range(50):
            await asyncio.sleep(0.01)
            if A.get_status(d.name)["status"] == "done":
                break
        assert A.get_status(d.name)["status"] == "done"

    asyncio.run(scenario())


def test_idle_status_has_phase():
    assert A.get_status("never-analyzed")["phase"] == "sections"
