"""Parse workbench.md into a structured dict suitable for transform."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Section:
    heading: str
    section_id: str
    line_range: str
    raw_excerpt: str = ""  # **원문 발췌** 블록
    summary: str = ""  # **요약** 블록 (4-6 문장)
    claude_translation: str = ""  # **Claude 1차 번역** 블록
    claude_notes: str = ""  # **Claude Reader's Notes** 블록
    user_answer: str = ""  # legacy — kept for backward compat
    done: bool = False


@dataclass
class QnaItem:
    from_section: str = ""  # e.g. "1 Introduction"  (format A: "### Q from §…")
    questions: list[str] = field(default_factory=list)
    answer: str = ""  # 사용자 답변 (placeholder if empty)
    heading: str = ""  # format B: "### Q1. <question>" — question lives in the header


@dataclass
class Workbench:
    frontmatter: dict = field(default_factory=dict)
    title: str = ""
    tldr: str = ""
    contributions: list[str] = field(default_factory=list)
    prereqs: list[str] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    qna: list[QnaItem] = field(default_factory=list)
    wrap_one_line: str = ""
    wrap_weakness: str = ""
    wrap_followups: list[str] = field(default_factory=list)
    pipelines: list = field(default_factory=list)  # parsed ```pipeline specs


# A new ingested (sub)section always starts with a `<!-- section_id: … -->`
# marker, so it must terminate every field — otherwise a section whose
# heading was demoted to bold (e.g. an OCR'd figure-label pseudo-section like
# `**DATASET**`) gets absorbed into the *preceding* field. That field is then
# wrapped in `> ` at publish, producing a runaway blockquote in Obsidian that
# swallows several unrelated paragraphs (the review page renders raw markdown
# without the `>`, so it looks fine there). The marker never appears inside a
# real field, so this boundary is a no-op for well-formed sections.
_NEXT_SECTION = r"(?:\*\*[^\n*]+\*\*\s*)?<!--\s*section_id:"
_BLOCK_PATTERNS = {
    "raw_excerpt": rf"\*\*원문 발췌\*\*[^\n]*\n(.+?)(?=\*\*요약\*\*|\*\*Claude 1차 번역\*\*|\*\*Claude Reader's Notes\*\*|{_NEXT_SECTION}|\Z)",
    "summary": rf"\*\*요약\*\*\s*\n(.+?)(?=\*\*Claude 1차 번역\*\*|\*\*Claude Reader's Notes\*\*|{_NEXT_SECTION}|\Z)",
    "claude_translation": rf"\*\*Claude 1차 번역\*\*\s*\n(.+?)(?=\*\*Claude Reader's Notes\*\*|{_NEXT_SECTION}|\Z)",
    "claude_notes": rf"\*\*Claude Reader's Notes\*\*\s*\n(.+?)(?={_NEXT_SECTION}|\Z)",
}


def parse(workbench_md: Path) -> Workbench:
    text = workbench_md.read_text()
    wb = Workbench()

    fm_match = re.match(r"^---\n(.*?)\n---\n", text, flags=re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).splitlines():
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            wb.frontmatter[k.strip()] = v.strip().strip('"')
        text = text[fm_match.end() :]

    title_m = re.search(r"^#\s+(.+?)\s*$", text, flags=re.MULTILINE)
    wb.title = (
        title_m.group(1)
        if title_m
        else wb.frontmatter.get("title_ko") or wb.frontmatter.get("title_en", "")
    )

    wb.tldr = _extract_h2_body(text, "TL;DR")
    wb.contributions = _extract_numbered(_extract_h2_body(text, "핵심 contribution"))
    wb.prereqs = _extract_bullets(_extract_h2_body(text, "사전지식 카드"))

    wb.sections = _extract_sections(text)
    wb.qna = _extract_qna(text)
    wb.pipelines = _extract_pipelines(text)

    wrap = _extract_h2_body(text, "Wrap-up")
    wb.wrap_one_line = _extract_dash_field(wrap, "한 줄 contribution")
    wb.wrap_weakness = _extract_dash_field(wrap, "가장 약한 부분")
    wb.wrap_followups = _extract_followups(wrap)

    return wb


def _extract_h2_body(text: str, header: str) -> str:
    pat = rf"^##\s+{re.escape(header)}\s*\n(.+?)(?=^##\s|\Z)"
    m = re.search(pat, text, flags=re.DOTALL | re.MULTILINE)
    return m.group(1).strip() if m else ""


def _extract_numbered(body: str) -> list[str]:
    items = re.findall(r"^\d+\.[ \t]+(.+?)[ \t]*$", body, flags=re.MULTILINE)
    return [it for it in items if it.strip()]


def _extract_bullets(body: str) -> list[str]:
    items = re.findall(r"^-[ \t]+(.+?)[ \t]*$", body, flags=re.MULTILINE)
    return [it for it in items if it.strip() and not it.startswith("_")]


_SID_RE = re.compile(r"<!--\s*section_id:\s*(\S+)(?:\s*\|\s*lines:\s*(\S+))?\s*-->")


def _title_above(before: str) -> str:
    """The heading line directly above a section_id marker — a `### …` or a
    demoted `**Bold**` title. Returns '' when the nearest non-blank line isn't
    a heading (so the caller can fall back)."""
    for ln in reversed(before.rstrip("\n").split("\n")):
        s = ln.strip()
        if s == "" or s == "<br>":
            continue
        bm = re.match(r"^\*\*([^*\n]+?)\*\*$", s)
        if bm:
            return bm.group(1).strip()
        hm = re.match(r"^#{2,3}\s+(.+)$", s)
        if hm:
            return hm.group(1).strip()
        return ""
    return ""


def _fallback_title(sid: str) -> str:
    s = (sid or "").strip()
    if not s or re.search(r"http|url|^\d{4}-", s):
        return "부록 · 보충 자료"
    return s.replace("-", " ").strip()


def _section_from_segment(heading: str, seg: str) -> Section:
    meta_m = _SID_RE.search(seg)
    sec = Section(
        heading=heading,
        section_id=meta_m.group(1) if meta_m else "",
        line_range=(meta_m.group(2) or "") if meta_m else "",
    )
    for field_name, pat in _BLOCK_PATTERNS.items():
        m = re.search(pat, seg, flags=re.DOTALL)
        if m:
            setattr(sec, field_name, m.group(1).strip())
    sec.done = bool(sec.claude_translation or sec.user_answer)
    return sec


def _extract_sections(text: str) -> list[Section]:
    # The review block runs until the next KNOWN structural H2 (Q&A / Wrap-up /
    # 메타 / 그림). It must NOT stop at a stray content H2 — neither a numbered
    # "## 6. …" nor a plain "## vLLM에서의 구현" (sections sometimes get written
    # at H2 instead of H3). Stopping at an arbitrary H2 silently dropped every
    # section after it — and its figures — from the published draft.
    h2_match = re.search(
        r"^##\s+섹션별 리뷰\s*\n(.+?)(?=^##\s+(?:Q&A|Wrap-up|메타|그림)\s*$|\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not h2_match:
        return []
    body = h2_match.group(1)

    # Sections are normally H3 (### N.) but tolerate a malformed numbered H2.
    section_chunks = re.split(r"(?=^###\s|^##\s+\d)", body, flags=re.MULTILINE)
    out: list[Section] = []
    for chunk in section_chunks:
        chunk = chunk.strip()
        head_m = re.match(r"^#{2,3}\s+(.+?)\s*$", chunk, flags=re.MULTILINE)
        if not head_m:
            continue
        heading = head_m.group(1)

        # Every ingested block carries a `<!-- section_id -->` marker. A chunk
        # usually has exactly one (the section). When a block's own heading was
        # demoted to bold (figure-label dumps, appendix), it has no `###` of its
        # own and gets swept into this chunk — so the chunk holds EXTRA markers.
        # Split on each marker: the first is this section; every extra one is a
        # merged block we publish as its own section instead of dropping it.
        markers = list(_SID_RE.finditer(chunk))
        if len(markers) <= 1:
            out.append(_section_from_segment(heading, chunk))
            continue
        # Main section = chunk up to the 2nd marker (fields can't bleed into the
        # merged block).
        out.append(_section_from_segment(heading, chunk[: markers[1].start()]))
        for mi in range(1, len(markers)):
            seg_start = markers[mi].start()
            seg_end = markers[mi + 1].start() if mi + 1 < len(markers) else len(chunk)
            title = _title_above(chunk[:seg_start]) or _fallback_title(
                markers[mi].group(1)
            )
            out.append(_section_from_segment(title, chunk[seg_start:seg_end]))

    return out


def _extract_pipelines(text: str) -> list:
    """Parse ```pipeline JSON fences (animated pipeline specs) into dicts."""
    out = []
    for m in re.finditer(r"```pipeline\s*\n(.*?)\n```", text, flags=re.DOTALL):
        try:
            out.append(json.loads(m.group(1)))
        except Exception:
            pass
    return out


def _deemph_lines(block: str) -> str:
    """Strip decorative line-wrapping emphasis the WYSIWYG editor adds.

    The Toast UI editor re-serializes each answer line wrapped in its own
    *...* italic, e.g. "1. …남는다.*\\n*2. …필요하다.*". Rendered verbatim that
    leaves literal "*" in the Velog callout. We drop one leading and one
    trailing emphasis run per line (content/emphasis loss is negligible for
    plain answer prose).
    """
    out = []
    for ln in block.splitlines():
        t = ln.strip()
        t = re.sub(r"^[*_]{1,3}", "", t)
        t = re.sub(r"[*_]{1,3}$", "", t)
        out.append(t.strip())
    return "\n".join(out).strip()


def _answer_is_real(ans: str) -> bool:
    ans = ans.strip()
    return bool(
        ans
        and ans != "<empty>"
        and not ans.startswith("(")
        and "미진행" not in ans
        and "여기에 본인 답변" not in ans
        and "답변하면" not in ans  # the "## Q&A" intro placeholder line
    )


def _extract_qna(text: str) -> list[QnaItem]:
    """Parse the ## Q&A section into [QnaItem], tolerating both layouts:

      Format A — Claude-generated:   ### Q from §<section>
                                     1. question …
                                     답변: <user answer>
      Format B — hand-written:       ### Q1. <question text>
                                     <answer paragraphs / bullets>

    Format B was silently dropped because the splitter only matched
    "### Q from §"; its questions then never reached publish.
    """
    m = re.search(
        r"^##\s+Q&A\s*\n(.+?)(?=^##\s|\Z)", text, flags=re.DOTALL | re.MULTILINE
    )
    if not m:
        return []
    body = m.group(1)
    # Split at every "### Q…" header (covers both formats).
    chunks = re.split(r"(?=^###\s+Q)", body, flags=re.MULTILINE)
    out: list[QnaItem] = []
    for chunk in chunks:
        if not chunk.lstrip().startswith("### Q"):
            continue
        # Format A: "### Q from §<section>"
        head_a = re.match(r"^###\s+Q\s+from\s+§(.+?)\s*$", chunk, flags=re.MULTILINE)
        if head_a:
            item = QnaItem(from_section=head_a.group(1).strip())
            qs = re.findall(r"^\s*\d+\.\s+(.+?)\s*$", chunk, flags=re.MULTILINE)
            item.questions = [q for q in qs if q.strip()]
            # Match the user's answer regardless of how it was serialized:
            #   "_답변:_ …" / "*답변: …*" / "**답변:** …" / "답변: …"
            a_match = re.search(
                r"^[ \t>]*[*_]{0,2}\s*답변\s*[*_]{0,2}\s*:?\s*[*_]{0,2}"
                r"(.*?)(?=^[ \t]*###\s|\Z)",
                chunk,
                flags=re.DOTALL | re.MULTILINE,
            )
            if a_match:
                ans = _deemph_lines(a_match.group(1))
                if _answer_is_real(ans):
                    item.answer = ans
            out.append(item)
            continue
        # Format B: "### Q1. <question>" / "### Q. <question>" — the question is
        # the header text and the answer is the body beneath it.
        head_b = re.match(
            r"^###\s+(Q[0-9]*[.)]?\s*\S.*?)\s*$", chunk, flags=re.MULTILINE
        )
        if head_b:
            heading = head_b.group(1).strip()
            after = chunk.split("\n", 1)[1] if "\n" in chunk else ""
            ans = after.strip()
            item = QnaItem(heading=heading)
            if _answer_is_real(ans):
                item.answer = ans
            # Keep only if it carries a real answer (unanswered hand-written
            # prompts shouldn't reach the published post).
            if item.answer:
                out.append(item)
    return out


def _extract_dash_field(body: str, label: str) -> str:
    # Accept -, * or + bullets: the WYSIWYG editor re-serializes `- ` list
    # markers as `* `, which silently broke Wrap-up field extraction.
    # The colon is optional and the value may sit on the following lines: some
    # workbenches write `* **한 줄 contribution**` then a multi-line body below
    # (no `: value` on the same line). Without this the whole Wrap-up dropped.
    m = re.search(
        rf"[-*+][ \t]+\*\*{re.escape(label)}\*\*:?[ \t]*(.*?)(?=\n[-*+][ \t]+\*\*|\Z)",
        body,
        flags=re.DOTALL,
    )
    return m.group(1).strip() if m else ""


def _extract_followups(body: str) -> list[str]:
    m = re.search(
        r"[-*+][ \t]+\*\*후속으로 읽을 논문\*\*:[ \t]*\n(.*?)(?=\n[-*+][ \t]+\*\*|\Z)",
        body,
        flags=re.DOTALL,
    )
    if not m:
        return []
    items = re.findall(r"^\s*\d+\.[ \t]+(.+?)[ \t]*$", m.group(1), flags=re.MULTILINE)
    return [it for it in items if it.strip()]
