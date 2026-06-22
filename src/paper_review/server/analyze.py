"""POST /paper/<slug>/analyze — background batch analysis of unfinished sections.

For each not-yet-done section in workbench.md, spawn a headless claude with
cwd = paper folder, asking it to translate that section inline (no subagent
dispatch — keeps turn count low) and update workbench.md via Edit tool.

Progress is exposed via GET /paper/<slug>/analyze/status (polling).
Cancellation is responsive — we poll cancel_event on every readline iteration.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel

Status = Literal["idle", "running", "done", "error", "cancelled"]


@dataclass
class AnalysisJob:
    job_id: str
    slug: str
    status: Status = "idle"
    total: int = 0
    current: int = 0
    current_heading: str = ""
    log: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    error: Optional[str] = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    last_text_preview: str = ""
    failed_sections: list[str] = field(default_factory=list)
    succeeded_sections: list[str] = field(default_factory=list)


_jobs: dict[str, AnalysisJob] = {}


class AnalyzeBody(BaseModel):
    model: str | None = None
    max_sections: int | None = None
    timeout_per_section: int = 360
    only_sections: list[str] | None = None  # if set, analyze only these (retry mode)


async def start_analysis(slug: str, paper_dir: Path, body: AnalyzeBody) -> dict:
    existing = _jobs.get(slug)
    if existing and existing.status == "running":
        return {"job_id": existing.job_id, "already_running": True}
    job = AnalysisJob(job_id=uuid.uuid4().hex[:12], slug=slug)
    _jobs[slug] = job
    asyncio.create_task(_run_analysis(job, paper_dir, body))
    return {"job_id": job.job_id, "already_running": False}


def get_status(slug: str) -> dict:
    job = _jobs.get(slug)
    if not job:
        return {"status": "idle", "current": 0, "total": 0, "log_tail": []}
    return _serialize(job)


def cancel(slug: str) -> dict:
    job = _jobs.get(slug)
    if not job or job.status != "running":
        raise HTTPException(404, "no running job")
    job.cancel_event.set()
    job.log.append("⏹ 취소 요청")
    return {"ok": True}


def _section_blocks(text: str) -> dict:
    """Map each '### ' section heading → its full block markdown (within the
    '## 섹션별 리뷰' region)."""
    m = re.search(
        r"^##\s+섹션별 리뷰\s*\n(.+?)(?=^##\s|\Z)", text, flags=re.DOTALL | re.MULTILINE
    )
    body = m.group(1) if m else text
    blocks: dict = {}
    for chunk in re.split(r"(?=^###\s)", body, flags=re.MULTILINE):
        c = chunk.strip()
        hm = re.match(r"^###\s+(.+?)\s*$", c, flags=re.MULTILINE)
        if hm:
            blocks[hm.group(1).strip()] = c
    return blocks


def _snapshot_baseline(paper_dir: Path, headings: list[str]) -> None:
    """Store the Claude-authored text of the given sections (right after
    analyze fills them) so the UI can later word-diff user edits against it.
    Best-effort — never raises."""
    try:
        wb = paper_dir / "workbench.md"
        if not wb.exists():
            return
        blocks = _section_blocks(wb.read_text())
        bpath = paper_dir / ".baseline.json"
        try:
            base = json.loads(bpath.read_text())
        except Exception:
            base = {}
        for h in headings:
            if h in blocks:
                base[h] = blocks[h]
        bpath.write_text(json.dumps(base, ensure_ascii=False))
    except Exception:
        pass


async def _run_analysis(job: AnalysisJob, paper_dir: Path, body: AnalyzeBody) -> None:
    job.status = "running"
    job.log.append(f"분석 시작: {job.slug}")

    wb = paper_dir / "workbench.md"
    if not wb.exists():
        job.status = "error"
        job.error = "workbench.md missing"
        job.finished_at = time.time()
        return

    try:
        wb_text = wb.read_text()

        # Step 0: auto-fill prereqs + contributions if still empty.
        # Skip when the user asked for specific section(s) only (single-section run).
        # Track whether a claude call has been made this run — the first one must
        # start a fresh session (no --continue), else a session-less folder fails.
        made_call = False
        needs_prelude = _needs_prelude(wb_text) and not body.only_sections
        if needs_prelude and not job.cancel_event.is_set():
            job.log.append("━━ [pre] 사전지식 카드 + 핵심 contribution + TL;DR 생성")
            await _generate_prelude(
                paper_dir, body.model, body.timeout_per_section, job, cont=False
            )
            made_call = True
            wb_text = wb.read_text()  # reload after edit

        sections_with_range = _parse_unfinished_sections(paper_dir, wb_text)
        if body.only_sections:
            wanted = set(body.only_sections)
            sections_with_range = [
                (h, r) for h, r in sections_with_range if h in wanted
            ]
        if body.max_sections:
            sections_with_range = sections_with_range[: body.max_sections]
        job.total = len(sections_with_range)
        job.log.append(f"미진행 섹션 {job.total}개")
        if not sections_with_range:
            job.status = "done"
            job.log.append("이미 모든 섹션이 완료됨")
            return

        for i, (sec_heading, line_range) in enumerate(sections_with_range):
            if job.cancel_event.is_set():
                job.status = "cancelled"
                break
            job.current = i + 1
            job.current_heading = sec_heading
            job.last_text_preview = ""
            job.log.append(f"━━ [{i+1}/{job.total}] {sec_heading} {line_range or ''}")
            ok = await _analyze_one_section(
                paper_dir,
                sec_heading,
                line_range,
                body.model,
                body.timeout_per_section,
                job,
                cont=made_call,
            )
            made_call = True
            if ok:
                job.succeeded_sections.append(sec_heading)
            else:
                if not job.cancel_event.is_set():
                    job.failed_sections.append(sec_heading)
                    job.log.append(f"   ⚠ 실패 — 다음으로 진행")

        # Snapshot the Claude baseline for sections filled this run (edit-diff)
        if job.succeeded_sections:
            _snapshot_baseline(paper_dir, job.succeeded_sections)

        if job.status == "running":
            job.status = "done"
            job.log.append("✓ 완료")
    except Exception as e:
        job.status = "error"
        job.error = str(e)
        job.log.append(f"✗ {e}")
    finally:
        job.finished_at = time.time()


async def _analyze_one_section(
    paper_dir: Path,
    heading: str,
    line_range: str,
    model: Optional[str],
    timeout: int,
    job: AnalysisJob,
    cont: bool = True,
) -> bool:
    """Spawn one claude -p call and stream-watch its progress. `cont` controls
    --continue: the FIRST claude call of an analyze run must start a fresh
    session (a freshly-ingested folder has none, and `--continue` then errors —
    which used to silently fail every section)."""

    prompt = _build_section_prompt(heading, line_range, paper_dir)
    system_ctx = (
        f"You are inside {paper_dir}, a paper-review workspace. "
        "Auto-analysis mode — do not wait for user input. Use Edit tool freely on "
        "workbench.md. Output minimal chat — the user is reading a progress bar, "
        "not your prose. When you are completely done with the section, reply with "
        "exactly one short line: '✓ done'."
    )

    cmd = ["claude", "-p", prompt]
    if cont:
        cmd += ["--continue"]
    cmd += [
        "--append-system-prompt",
        system_ctx,
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--max-turns",
        "20",
        "--permission-mode",
        "acceptEdits",
    ]
    if model:
        cmd += ["--model", model]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        limit=16 * 1024 * 1024,
        cwd=str(paper_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    start = time.time()
    try:
        assert proc.stdout is not None
        while True:
            if job.cancel_event.is_set():
                job.log.append("   ⏹ killing claude…")
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2)
                except asyncio.TimeoutError:
                    proc.kill()
                return False

            if time.time() - start > timeout:
                job.log.append(f"   ⏱ timeout ({timeout}s) — killing")
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2)
                except asyncio.TimeoutError:
                    proc.kill()
                return False

            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if not line:
                break
            _consume_stream_line(line, job)

        await proc.wait()
        if proc.returncode != 0:
            err_bytes = await proc.stderr.read() if proc.stderr else b""
            err = err_bytes.decode("utf-8", "replace")[-400:]
            job.log.append(f"   ✗ exit {proc.returncode}: {err}")
            return False
        job.log.append("   ✓ section done")
        return True
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2)
            except asyncio.TimeoutError:
                proc.kill()


async def generate_questions(
    paper_dir: Path, model: Optional[str], timeout: int = 240
) -> dict:
    """On-demand: generate probing Q&A questions for the already-analyzed sections."""
    slug = paper_dir.name
    prompt = f"""Generate probing review questions for this paper's ## Q&A section.

Steps:
1. Read workbench.md. Look at the '## 섹션별 리뷰' sections that are already
   filled (they have 요약 / Claude 1차 번역). Skip '_(미진행 …)_' sections.
2. For each filled section, write 1-2 sharp probing questions a careful reviewer
   would ask (challenge an assumption, a missing baseline, an alternative
   explanation, a generalization limit). Korean.
3. Edit the '## Q&A' section of workbench.md: replace the placeholder
   '_(분석 중 Claude가 제기한 질문이 여기에 모입니다...)_' (or append if already
   has content) with, per section:

   ### Q from §{{heading}}
   1. <question>
   2. <question if relevant>

   _답변:_

4. Touch ONLY the ## Q&A section. Do not modify 섹션별 리뷰 / TL;DR / Wrap-up.
5. Reply EXACTLY: '✓ questions done'."""

    system_ctx = (
        f"You are inside {paper_dir}, paper-review workspace. Generate Q&A questions "
        "only. Use the Edit tool on workbench.md. Output minimal chat."
    )
    cmd = [
        "claude",
        "-p",
        prompt,
        "--continue",
        "--append-system-prompt",
        system_ctx,
        "--output-format",
        "stream-json",
        "--verbose",
        "--max-turns",
        "15",
        "--permission-mode",
        "acceptEdits",
    ]
    if model:
        cmd += ["--model", model]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        limit=16 * 1024 * 1024,
        cwd=str(paper_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    start = time.time()
    try:
        assert proc.stdout is not None
        while True:
            if time.time() - start > timeout:
                proc.terminate()
                return {"ok": False, "error": "timeout"}
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if not line:
                break
        await proc.wait()
        return {"ok": proc.returncode == 0, "code": proc.returncode}
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2)
            except asyncio.TimeoutError:
                proc.kill()


async def generate_pipeline(
    paper_dir: Path, model: Optional[str], timeout: int = 360
) -> dict:
    """On-demand: auto-generate the ```pipeline animation spec from the paper."""
    prompt = """Generate an animated-pipeline spec for THIS paper and insert it into workbench.md.

Steps:
1. Read sections.txt and source.txt (and workbench.md) to understand the paper's core process.
2. Decide what the pipeline should depict:
   - Architecture / method papers → the model's inference (or training) pipeline: input → … → output.
   - Analysis / empirical papers → the experimental / diagnostic flow: intervention → measure → analyze.
   - If the paper genuinely has NO single pipeline worth diagramming, reply EXACTLY '✓ pipeline skipped' and do NOT edit anything.
3. Build a JSON spec with 4–7 stages, ordered left→right. Each stage:
   {"label": "짧은 제목\\n부가설명(선택)", "icon": "<icon>", "caption": "한국어 1–2문장 설명"}
   - label: VERY short. Use \\n for an optional 2nd line. Korean or short English terms.
   - icon — pick the closest of: image (이미지 입력), eye (인코더·지각), layers (projection·변환),
     chip (LLM·핵심 모델), bolt (출력·액션·생성), robot (로봇·에이전트), data (데이터셋),
     text (텍스트·언어), target (평가·지표), arrow (기타).
   - caption: Korean, concrete (what this stage does, key detail).
4. Insert into workbench.md a section placed RIGHT BEFORE '## 섹션별 리뷰':

   ## 파이프라인

   ```pipeline
   {"title": "<모델명 또는 핵심> 파이프라인", "stages": [ … ]}
   ```

   If a '## 파이프라인' section already exists, REPLACE its body.
5. The fenced block MUST be valid JSON — double quotes, no trailing commas, no comments, no markdown inside strings.
6. Touch ONLY the 파이프라인 section. Reply EXACTLY '✓ pipeline done'."""

    system_ctx = (
        f"You are inside {paper_dir}, a paper-review workspace. Generate the "
        "pipeline spec only. Use the Edit tool on workbench.md. Output minimal chat."
    )
    cmd = [
        "claude",
        "-p",
        prompt,
        "--continue",
        "--append-system-prompt",
        system_ctx,
        "--output-format",
        "stream-json",
        "--verbose",
        "--max-turns",
        "20",
        "--permission-mode",
        "acceptEdits",
    ]
    if model:
        cmd += ["--model", model]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        limit=16 * 1024 * 1024,
        cwd=str(paper_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    start = time.time()
    try:
        assert proc.stdout is not None
        while True:
            if time.time() - start > timeout:
                proc.terminate()
                return {"ok": False, "error": "timeout"}
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if not line:
                break
        await proc.wait()
        wb = paper_dir / "workbench.md"
        created = bool(
            wb.exists()
            and re.search(r"```pipeline\s*\n", wb.read_text(encoding="utf-8"))
        )
        return {"ok": proc.returncode == 0, "code": proc.returncode, "created": created}
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2)
            except asyncio.TimeoutError:
                proc.kill()


def _build_section_prompt(heading: str, line_range: str, paper_dir: Path) -> str:
    slug = paper_dir.name
    range_hint = (
        f"It corresponds to lines {line_range} of {slug}_source.txt."
        if line_range
        else ""
    )
    return f"""Translate paper section {heading!r} INLINE (no subagent dispatch).

{range_hint}

Steps:
1. Read the section text from {slug}_source.txt using the indicated line range.
   If the section exceeds 8000 chars of source text, split into 2-3 conceptual
   chunks and process each (still inline, no subagent).

2. In workbench.md, locate the H3 heading "### {heading}". Replace its current
   placeholder (which says _(미진행 — `/next-section` 로 진행)_) with this EXACT
   formatted block (keep the <!-- section_id ... --> comment line intact):

   **원문 발췌** (lines {line_range})
   > <1-2 representative sentences in English from the section>

   **요약**
   <4-6 sentences in Korean — what the section ACTUALLY says (key claims, key
    numbers, key comparisons). NOT meta-commentary. For fast reading.>

   **Claude 1차 번역**
   <paragraphs, faithful KO translation — preserve $...$ math, preserve key terms
    in English with "한글(English)" on first occurrence per the paper-review skill
    translation-guide. This is the detailed view — the user can skim summary or
    read fully here.>

   **Claude Reader's Notes**
   <1 short callout: intuition / historical context / implementation note /
    unstated assumption. 200-400자. Skip if no genuine insight.>

3. Preserve the <!-- section_id ... --> comment in the section header. Do not
   touch the ## Q&A section or any other section.

4. After the edit, reply with EXACTLY: '✓ done'. Nothing else.

Do NOT generate questions — Q&A is created on demand by a separate button."""


def _needs_prelude(workbench_md: str) -> bool:
    """True if TL;DR / contributions / prereqs are still placeholder-only."""
    # TL;DR placeholder: 비어있음 marker
    tldr_unfilled = "아직 비어있음" in workbench_md
    # contrib placeholder: "1. \n2. \n3. " (empty numbered items)
    contrib_unfilled = bool(
        re.search(r"## 핵심 contribution[\s\S]*?\n1\. \n2\. \n3\. ", workbench_md)
    )
    # prereqs placeholder
    prereqs_unfilled = "ingest는 사전지식 카드를 미리 만들지 않음" in workbench_md
    return tldr_unfilled or contrib_unfilled or prereqs_unfilled


async def _generate_prelude(
    paper_dir: Path,
    model: Optional[str],
    timeout: int,
    job: AnalysisJob,
    cont: bool = True,
) -> None:
    """One-shot generation of TL;DR + contributions + prereqs."""
    slug = paper_dir.name
    prompt = f"""Generate the workbench prelude (TL;DR, 핵심 contribution, 사전지식 카드) for this paper.

Steps:
1. Read {slug}_source.txt lines 1-200 to understand the paper's abstract,
   introduction, and stated contributions. Read more if needed but stay efficient.
2. Edit workbench.md to fill three sections:

   ## TL;DR
   Replace the placeholder line (_아직 비어있음..._) with 3-5 Korean sentences
   describing what the paper does, what's novel, and headline results. Keep
   technical terms in English where the field standard is English.

   ## 핵심 contribution
   Replace `1. \\n2. \\n3. ` with 3 concrete contribution bullets in Korean.
   Each one sentence. Be specific (mention dataset names, numbers, mechanisms).
   Also remove the placeholder italics line above the numbered list.

   ## 사전지식 카드
   Replace `_(ingest는 사전지식 카드를 미리 만들지 않음...)_` with 5-10 bullet
   items. Each item: `- **<term>** — <1-2 line Korean explanation>`. Pick
   external concepts a reader needs to know BEFORE reading this paper (e.g.,
   for SAM 3: DETR, promptable segmentation, SAM 2, presence head, multimodal
   LLM, etc.). NOT internal concepts the paper defines.

3. Don't touch ## 섹션별 리뷰, ## Q&A, ## Wrap-up — leave those for the section
   loop.

4. Reply EXACTLY: '✓ prelude done'."""

    system_ctx = (
        f"You are inside {paper_dir}, paper-review workspace. "
        "Generate prelude only — TL;DR, contributions, prereqs. "
        "Use Edit tool on workbench.md. Output minimal chat."
    )

    cmd = ["claude", "-p", prompt]
    if cont:
        cmd += ["--continue"]
    cmd += [
        "--append-system-prompt",
        system_ctx,
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--max-turns",
        "15",
        "--permission-mode",
        "acceptEdits",
    ]
    if model:
        cmd += ["--model", model]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        limit=16 * 1024 * 1024,
        cwd=str(paper_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    start = time.time()
    try:
        assert proc.stdout is not None
        while True:
            if job.cancel_event.is_set():
                proc.terminate()
                return
            if time.time() - start > timeout:
                job.log.append(f"   ⏱ prelude timeout — killing")
                proc.terminate()
                return
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if not line:
                break
            _consume_stream_line(line, job)
        await proc.wait()
        if proc.returncode == 0:
            job.log.append("   ✓ prelude done")
        else:
            job.log.append(f"   ⚠ prelude exit {proc.returncode}")
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2)
            except asyncio.TimeoutError:
                proc.kill()


def _consume_stream_line(line: bytes, job: AnalysisJob) -> None:
    try:
        obj = json.loads(line.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return
    t = obj.get("type")
    if t == "system":
        sub = obj.get("subtype")
        if sub == "init":
            job.log.append(f"   ● claude init ({obj.get('model','?')})")
        elif sub == "status":
            job.log.append(f"   · {obj.get('status', '?')}")
        elif sub == "post_turn_summary":
            detail = obj.get("status_detail", "")
            if detail:
                job.log.append(f"   · {detail[:120]}")
    elif t == "stream_event":
        ev = obj.get("event", {})
        et = ev.get("type")
        if et == "content_block_start":
            cb = ev.get("content_block", {})
            if cb.get("type") == "tool_use":
                tool_name = cb.get("name", "")
                tool_input = cb.get("input", {})
                summary = _summarize_tool(tool_name, tool_input)
                job.log.append(f"   ⚙ {summary}")
        elif et == "content_block_delta":
            delta = ev.get("delta", {})
            if delta.get("type") == "text_delta":
                txt = delta.get("text", "")
                job.last_text_preview = (job.last_text_preview + txt)[-200:]
    elif t == "assistant":
        # accumulated text — final form for a content block. We already captured
        # tool_use via stream_event. Just record if there's a tool with full input.
        for c in obj.get("message", {}).get("content", []):
            if c.get("type") == "tool_use":
                tool_name = c.get("name", "")
                tool_input = c.get("input", {})
                # Only log if we haven't via stream_event (delta phase may have
                # already added). Idempotent: dedupe via last log line.
                summary = _summarize_tool(tool_name, tool_input)
                if not job.log or job.log[-1] != f"   ⚙ {summary}":
                    job.log.append(f"   ⚙ {summary}")
    elif t == "result":
        cost = obj.get("total_cost_usd")
        dur = obj.get("duration_ms")
        if cost is not None and dur is not None:
            job.log.append(f"   ⊕ {dur/1000:.1f}s · ${cost:.4f}")
        if obj.get("is_error"):
            job.log.append(f"   ✗ {obj.get('result','')[:200]}")


def _summarize_tool(name: str, input_data: dict) -> str:
    """Compact one-liner of a tool_use event."""
    if name == "Read":
        path = input_data.get("file_path", "?")
        rng = ""
        if input_data.get("offset") or input_data.get("limit"):
            rng = f" [{input_data.get('offset','?')}..+{input_data.get('limit','?')}]"
        return f"Read {Path(path).name}{rng}"
    if name == "Edit":
        path = input_data.get("file_path", "?")
        return f"Edit {Path(path).name}"
    if name == "Write":
        path = input_data.get("file_path", "?")
        return f"Write {Path(path).name}"
    if name == "Bash":
        cmd = input_data.get("command", "")
        return f"Bash: {cmd[:80]}"
    return f"{name}"


def _parse_unfinished_sections(
    paper_dir: Path, workbench_md: str
) -> list[tuple[str, str]]:
    """Returns [(heading, line_range), ...] for sections with the _(미진행)_ marker.

    line_range is read from the <!-- section_id: ... | lines: A-B --> comment,
    falling back to "" if absent.
    """
    start_m = re.search(r"##\s+섹션별 리뷰\s*\n", workbench_md)
    if not start_m:
        return []
    start = start_m.end()
    tail = re.search(r"\n##\s+(?:Q ?& ?A|Wrap-up|메타|정리)\b", workbench_md[start:])
    end = start + tail.start() if tail else len(workbench_md)
    body = workbench_md[start:end]
    chunks = re.split(r"(?=\n### )", body)
    out: list[tuple[str, str]] = []
    for chunk in chunks:
        chunk = chunk.lstrip("\n")
        if not chunk.startswith("### "):
            continue
        head_m = re.match(r"^###\s+(.+?)\s*$", chunk, flags=re.MULTILINE)
        if not head_m:
            continue
        if "(미진행" not in chunk:
            continue
        heading = head_m.group(1)
        # Extract line range from comment
        lr_m = re.search(r"<!--\s*section_id:[^|]*\|\s*lines:\s*(\S+)\s*-->", chunk)
        line_range = lr_m.group(1) if lr_m else ""
        out.append((heading, line_range))
    return out


def _serialize(job: AnalysisJob) -> dict:
    return {
        "job_id": job.job_id,
        "slug": job.slug,
        "status": job.status,
        "total": job.total,
        "current": job.current,
        "current_heading": job.current_heading,
        "log_tail": job.log[-300:],
        "last_text_preview": job.last_text_preview,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error": job.error,
        "failed_sections": list(job.failed_sections),
        "succeeded_sections": list(job.succeeded_sections),
    }
