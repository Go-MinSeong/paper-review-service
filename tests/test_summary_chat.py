"""Discussing the Summary changes nothing until the report is regenerated."""

import asyncio
import json

from paper_review.server import analyze, chat


class _Stdout:
    def __init__(self, lines):
        self._lines = [json.dumps(l).encode() + b"\n" for l in lines]

    async def readline(self):
        return self._lines.pop(0) if self._lines else b""


class _Proc:
    def __init__(self, lines):
        self.stdout = _Stdout(lines)
        self.stderr = None
        self.returncode = None

    async def wait(self):
        self.returncode = 0
        return 0


class _Req:
    async def is_disconnected(self):
        return False


def _run_chat(monkeypatch, paper_dir, target, prompt="3장 표를 줄여줘"):
    seen = {}

    async def fake_exec(*cmd, **kw):
        seen["cmd"] = list(cmd)
        return _Proc(
            [
                {"type": "system", "subtype": "init", "session_id": f"s-{target}"},
                {"type": "result", "result": "3장 표를 핵심 행 5개로 줄이겠습니다.", "session_id": f"s-{target}"},
            ]
        )

    monkeypatch.setattr(chat.asyncio, "create_subprocess_exec", fake_exec)
    body = chat.ChatBody(prompt=prompt, target=target)

    async def drain():
        return [x async for x in chat.stream_chat("x", paper_dir, body, _Req())]

    asyncio.run(drain())
    return seen["cmd"]


def test_a_summary_discussion_cannot_edit_files_and_logs_the_request(tmp_path, monkeypatch):
    (tmp_path / "workbench.md").write_text("---\ncontent_type: paper\n---\n")
    cmd = _run_chat(monkeypatch, tmp_path, "report")

    assert "--disallowedTools" in cmd
    blocked = cmd[cmd.index("--disallowedTools") + 1 :]
    assert {"Edit", "Write"} <= set(blocked)
    ctx = cmd[cmd.index("--append-system-prompt") + 1]
    assert "DO NOT edit" in ctx and "Regenerate Report" in ctx

    log = (tmp_path / chat.REQUESTS).read_text(encoding="utf-8")
    assert "3장 표를 줄여줘" in log and "핵심 행 5개" in log
    assert chat.pending_requests(tmp_path) == 1


def test_review_chat_is_unchanged_and_sessions_do_not_mix(tmp_path, monkeypatch):
    """--continue resumes whatever ran last in the folder; a Summary discussion
    must not become the review chat's session (or the other way round)."""
    (tmp_path / "workbench.md").write_text("---\ncontent_type: paper\n---\n")

    first = _run_chat(monkeypatch, tmp_path, "workbench", prompt="/status")
    assert "--continue" in first and "--disallowedTools" not in first
    assert not (tmp_path / chat.REQUESTS).exists(), "review chat must not log requests"

    report = _run_chat(monkeypatch, tmp_path, "report")
    assert "--continue" not in report, "would resume the review session"

    again = _run_chat(monkeypatch, tmp_path, "workbench", prompt="/status")
    assert again[again.index("--resume") + 1] == "s-workbench"
    report2 = _run_chat(monkeypatch, tmp_path, "report")
    assert report2[report2.index("--resume") + 1] == "s-report"


def test_regeneration_reads_the_requests_and_archives_them(tmp_path):
    (tmp_path / "report-requests.md").write_text("## 2026-09-14 10:00\n\n**요청**: 표 줄이기\n")
    assert "report-requests.md" in analyze._requests_hint(tmp_path)

    analyze._archive_requests(tmp_path)
    assert not (tmp_path / "report-requests.md").exists()
    assert list((tmp_path / ".history").glob("report-requests-*.md"))
    assert analyze._requests_hint(tmp_path) == "", "applied requests must not come back"
