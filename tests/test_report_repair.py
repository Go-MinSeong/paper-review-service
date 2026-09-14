"""After the report is written, broken diagrams go back to the same session
for a focused fix — kept only when it actually lowers the problem count."""

import asyncio
import json

from paper_review.server import analyze as A


def _report(width):
    return (
        "<html><body><div class='diagram-wrap'>"
        '<svg viewBox="0 0 400 200" xmlns="http://www.w3.org/2000/svg">'
        f'<rect x="10" y="40" width="{width}" height="50"/>'
        '<text x="20" y="70" font-size="13">coarse: c_corr·(1−c_degen)·c_depth·c_long</text>'
        "</svg></div></body></html>"
    )


BAD, GOOD = _report(120), _report(360)
WORSE = BAD.replace(
    "</svg>", '<text x="380" y="150" font-size="14">잘리는 긴 라벨</text></svg>'
)


class _Stdout:
    def __init__(self, lines):
        self._lines = [json.dumps(l).encode() + b"\n" for l in lines]

    async def readline(self):
        return self._lines.pop(0) if self._lines else b""


class _Proc:
    def __init__(self):
        self.stdout = _Stdout(
            [
                {"type": "system", "subtype": "init", "session_id": "s-report"},
                {"type": "result", "result": "ok"},
            ]
        )
        self.stderr = None
        self.returncode = None

    async def wait(self):
        self.returncode = 0
        return 0

    def terminate(self):
        pass


def _generate(tmp_path, monkeypatch, writes):
    """Each claude run writes the next version of report.html."""
    d = tmp_path / "2601.00002"
    d.mkdir()
    (d / "workbench.md").write_text("---\nstatus: to_read\n---\n")
    calls = []

    async def fake_exec(*cmd, **kw):
        calls.append(list(cmd))
        (d / "report.html").write_text(writes[len(calls) - 1], encoding="utf-8")
        return _Proc()

    monkeypatch.setattr(A.asyncio, "create_subprocess_exec", fake_exec)
    job = A.AnalysisJob(job_id="j", slug=d.name)
    res = asyncio.run(A.generate_report(d, None, job=job))
    return d, calls, job, res


def test_diagram_problems_go_back_to_the_same_session_and_the_fix_is_kept(
    tmp_path, monkeypatch
):
    d, calls, job, res = _generate(tmp_path, monkeypatch, [BAD, GOOD])

    assert res["ok"] and len(calls) == 2
    repair = calls[1]
    assert repair[repair.index("--resume") + 1] == "s-report"
    assert "TEXT_OVERFLOW" in repair[repair.index("-p") + 1]
    assert "Write" in repair[repair.index("--disallowedTools") + 1 :]
    assert (d / "report.html").read_text() == GOOD
    assert any("1 → 0" in l for l in job.log)


def test_a_repair_that_does_not_help_is_rolled_back(tmp_path, monkeypatch):
    d, calls, job, res = _generate(tmp_path, monkeypatch, [BAD, WORSE, GOOD])

    assert res["ok"]
    assert len(calls) == 2, "stops at the first round that doesn't improve"
    assert (d / "report.html").read_text() == BAD
    assert any("이전 버전 유지" in l for l in job.log)


def test_a_clean_report_costs_no_extra_turn(tmp_path, monkeypatch):
    _d, calls, _job, res = _generate(tmp_path, monkeypatch, [GOOD])
    assert res["ok"] and len(calls) == 1
