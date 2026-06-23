"""POST /paper/<slug>/chat — spawn headless claude in the paper folder and
stream its stdout (text/event-stream).

Design notes:
- One concurrent chat per paper (per-slug asyncio.Lock).
- We pass --continue every time. On the first call the flag is a no-op (no
  prior session in that cwd); on subsequent calls it resumes the most recent
  one. This means we never have to track session IDs ourselves — cwd is the
  group key.
- Stream is line-based: every newline-terminated chunk from claude's stdout
  becomes one SSE `data:` event. The client parses the inner JSON.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


class ChatBody(BaseModel):
    prompt: str
    max_turns: int = 30
    fresh: bool = False  # if True, omit --continue (start a new session)
    model: str | None = None  # "sonnet" | "opus" | "haiku" or full id


_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


async def stream_chat(slug: str, paper_dir: Path, body: ChatBody, request: Request):
    """Async generator yielding SSE-formatted lines."""
    if not body.prompt.strip():
        raise HTTPException(400, "empty prompt")

    lock = _locks[slug]
    if lock.locked():
        yield _sse(
            {"type": "error", "message": "chat busy — another turn is in flight"}
        )
        return

    async with lock:
        yield _sse({"type": "user", "text": body.prompt})

        # Wrap leading-slash pseudo-commands so Claude Code's slash command
        # parser doesn't intercept them as unknown slash commands.
        user_text = body.prompt
        if user_text.lstrip().startswith("/") and not user_text.lstrip().startswith(
            "/paper-review"
        ):
            user_text = (
                f"User pseudo-command (from paper-review chat UI): {user_text.strip()}\n\n"
                "Apply the matching rule from ~/.claude/skills/paper-review/SKILL.md. "
                "Do not respond that the command is unavailable — these are skill-internal, "
                "not Claude Code slash commands."
            )

        system_ctx = (
            f"You are operating inside {paper_dir}, the paper-review service workspace "
            "(see ~/Projects/paper-review-service/DESIGN.md). The paper-review skill at "
            "~/.claude/skills/paper-review/SKILL.md is implicitly active for every "
            "message in this session — do not require the user to type /paper-review "
            "to activate it. "
            "Treat pseudo-commands like /status, /next-section, /explain <topic>, "
            "/challenge, /finalize, /summarize-progress as defined in that SKILL.md. "
            "All other free-form messages are user replies to whatever section is "
            "currently being reviewed in workbench.md — apply the same skill rules. "
            "workbench.md is the single source of truth; edit it directly with the "
            "Edit tool (do NOT dispatch a sub-agent — process inline). For "
            "/next-section: read the section's line range from <slug>_source.txt, then "
            "Edit the matching '### ' block in workbench.md in place, replacing its "
            "'_(미진행 …)_' placeholder with 원문 발췌 / 요약 / Claude 1차 번역 / "
            "Claude Reader's Notes. "
            "RECORDING REQUESTS: when the user asks you to 기재/기록/메모/저장/추가 "
            "(record / jot down / save) a question, your answer, or a note into the "
            "workbench — e.g. '이 질문 기재해줘', 'Q&A에 추가해줘' — you MUST Edit "
            "workbench.md; never treat a chat-panel reply alone as fulfilling it. "
            "Default target is the '## Q&A' section: append the Q (and the A if "
            "discussed) there, replacing the '_(분석 중 Claude가 제기한 질문이 …)_' "
            "placeholder on first write. If the user ties it to a specific section, "
            "edit that '### ' block instead. After editing, confirm in one line what "
            "you wrote and where. "
            "Keep chat responses short and action-oriented — the "
            "user sees them in a chat panel, not a full terminal."
        )
        cmd = [
            "claude",
            "-p",
            user_text,
            "--append-system-prompt",
            system_ctx,
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--permission-mode",
            "acceptEdits",
            "--max-turns",
            str(body.max_turns),
        ]
        if body.model:
            cmd += ["--model", body.model]
        if not body.fresh:
            cmd.insert(2, "--continue")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            limit=16 * 1024 * 1024,
            cwd=str(paper_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            assert proc.stdout is not None
            while True:
                if await request.is_disconnected():
                    proc.terminate()
                    break
                line = await proc.stdout.readline()
                if not line:
                    break
                try:
                    obj = json.loads(line.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    yield _sse({"type": "raw", "line": line.decode("utf-8", "replace")})
                    continue
                yield _sse_pass(obj)

            await proc.wait()
            if proc.returncode != 0:
                err = ""
                if proc.stderr:
                    err = (await proc.stderr.read()).decode("utf-8", "replace")
                yield _sse(
                    {"type": "error", "code": proc.returncode, "stderr": err[-2000:]}
                )
            yield _sse({"type": "done"})
        finally:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=3)
                except asyncio.TimeoutError:
                    proc.kill()


def chat_route(paper_dir_resolver):
    """Factory that returns the FastAPI route function, parameterized by a
    function that maps slug → Path (for testability)."""

    async def chat(slug: str, body: ChatBody, request: Request):
        d = paper_dir_resolver(slug)
        return StreamingResponse(
            stream_chat(slug, d, body, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return chat


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_pass(obj: dict) -> str:
    """Pass through a claude stream-json line, with light shaping for the UI."""
    t = obj.get("type")
    if t == "stream_event":
        ev = obj.get("event", {})
        et = ev.get("type")
        if et == "content_block_delta":
            delta = ev.get("delta", {})
            if delta.get("type") == "text_delta":
                return _sse({"type": "delta", "text": delta.get("text", "")})
            if delta.get("type") == "input_json_delta":
                return _sse(
                    {
                        "type": "tool_delta",
                        "partial_json": delta.get("partial_json", ""),
                    }
                )
        if et == "content_block_start":
            cb = ev.get("content_block", {})
            if cb.get("type") == "tool_use":
                return _sse(
                    {
                        "type": "tool_start",
                        "name": cb.get("name", ""),
                        "id": cb.get("id"),
                    }
                )
        if et == "message_stop":
            return _sse({"type": "message_stop"})
        return ""  # other stream_event types: skip
    if t == "assistant":
        # accumulated message — useful as fallback if delta path missed
        return ""
    if t == "system":
        sub = obj.get("subtype")
        if sub == "init":
            return _sse(
                {
                    "type": "system",
                    "subtype": "init",
                    "session_id": obj.get("session_id"),
                    "model": obj.get("model"),
                }
            )
        if sub == "status":
            return _sse(
                {"type": "system", "subtype": "status", "status": obj.get("status")}
            )
        if sub == "post_turn_summary":
            return _sse(
                {
                    "type": "system",
                    "subtype": "summary",
                    "status_detail": obj.get("status_detail"),
                    "needs_action": obj.get("needs_action"),
                }
            )
        return ""
    if t == "result":
        return _sse(
            {
                "type": "result",
                "result": obj.get("result"),
                "is_error": obj.get("is_error", False),
                "duration_ms": obj.get("duration_ms"),
                "total_cost_usd": obj.get("total_cost_usd"),
                "session_id": obj.get("session_id"),
            }
        )
    return ""
