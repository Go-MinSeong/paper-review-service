"""Parse workbench.md into a structured dict suitable for transform."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Section:
    heading: str
    section_id: str
    line_range: str
    raw_excerpt: str = ""           # **원문 발췌** 블록
    summary: str = ""               # **요약** 블록 (4-6 문장)
    claude_translation: str = ""    # **Claude 1차 번역** 블록
    claude_notes: str = ""          # **Claude Reader's Notes** 블록
    user_answer: str = ""           # legacy — kept for backward compat
    done: bool = False


@dataclass
class QnaItem:
    from_section: str = ""          # e.g. "1 Introduction"
    questions: list[str] = field(default_factory=list)
    answer: str = ""                # 사용자 답변 (placeholder if empty)


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


_BLOCK_PATTERNS = {
    "raw_excerpt":         r"\*\*원문 발췌\*\*[^\n]*\n(.+?)(?=\*\*요약\*\*|\*\*Claude 1차 번역\*\*|\*\*Claude Reader's Notes\*\*|\Z)",
    "summary":             r"\*\*요약\*\*\s*\n(.+?)(?=\*\*Claude 1차 번역\*\*|\*\*Claude Reader's Notes\*\*|\Z)",
    "claude_translation":  r"\*\*Claude 1차 번역\*\*\s*\n(.+?)(?=\*\*Claude Reader's Notes\*\*|\Z)",
    "claude_notes":        r"\*\*Claude Reader's Notes\*\*\s*\n(.+?)\Z",
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
        text = text[fm_match.end():]

    title_m = re.search(r"^#\s+(.+?)\s*$", text, flags=re.MULTILINE)
    wb.title = title_m.group(1) if title_m else wb.frontmatter.get("title_ko") or wb.frontmatter.get("title_en", "")

    wb.tldr = _extract_h2_body(text, "TL;DR")
    wb.contributions = _extract_numbered(_extract_h2_body(text, "핵심 contribution"))
    wb.prereqs = _extract_bullets(_extract_h2_body(text, "사전지식 카드"))

    wb.sections = _extract_sections(text)
    wb.qna = _extract_qna(text)

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


def _extract_sections(text: str) -> list[Section]:
    # The review block runs until the next NON-numbered H2 (Q&A / Wrap-up / 메타).
    # A stray numbered "## 6. …" section heading (some sections get written at H2
    # instead of H3) must NOT terminate it — that silently dropped every section
    # after it from the published draft.
    h2_match = re.search(r"^##\s+섹션별 리뷰\s*\n(.+?)(?=^##\s+(?!\d)|\Z)", text,
                        flags=re.DOTALL | re.MULTILINE)
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

        sec_id = ""
        lines_str = ""
        meta_m = re.search(r"<!--\s*section_id:\s*(\S+)(?:\s*\|\s*lines:\s*(\S+))?\s*-->", chunk)
        if meta_m:
            sec_id = meta_m.group(1)
            lines_str = meta_m.group(2) or ""

        sec = Section(heading=heading, section_id=sec_id, line_range=lines_str)

        for field_name, pat in _BLOCK_PATTERNS.items():
            m = re.search(pat, chunk, flags=re.DOTALL)
            if m:
                value = m.group(1).strip()
                setattr(sec, field_name, value)

        sec.done = bool(sec.claude_translation or sec.user_answer)
        out.append(sec)

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


def _extract_qna(text: str) -> list[QnaItem]:
    """Parse ## Q&A section into [QnaItem]."""
    m = re.search(r"^##\s+Q&A\s*\n(.+?)(?=^##\s|\Z)", text,
                  flags=re.DOTALL | re.MULTILINE)
    if not m:
        return []
    body = m.group(1)
    # Split by ### Q from §...
    chunks = re.split(r"(?=^###\s+Q\s+from\s+§)", body, flags=re.MULTILINE)
    out: list[QnaItem] = []
    for chunk in chunks:
        if not chunk.strip() or not chunk.lstrip().startswith("### Q from §"):
            continue
        head = re.match(r"^###\s+Q\s+from\s+§(.+?)\s*$", chunk, flags=re.MULTILINE)
        if not head:
            continue
        item = QnaItem(from_section=head.group(1).strip())
        qs = re.findall(r"^\s*\d+\.\s+(.+?)\s*$", chunk, flags=re.MULTILINE)
        item.questions = [q for q in qs if q.strip()]
        # Match the user's answer regardless of how it was serialized:
        #   "_답변:_ ..."        (skill placeholder, underscore + colon-marker)
        #   "*답변: ...*"         (WYSIWYG re-serializes each line italic)
        #   "**답변:** ..." / "답변: ..."  (bold / bare variants)
        # The WYSIWYG editor also wraps EACH answer line in its own *...* italic,
        # so we de-emphasize line by line after dropping the label.
        a_match = re.search(
            r"^[ \t>]*[*_]{0,2}\s*답변\s*[*_]{0,2}\s*:?\s*[*_]{0,2}"
            r"(.*?)(?=^[ \t]*###\s|\Z)",
            chunk, flags=re.DOTALL | re.MULTILINE,
        )
        if a_match:
            ans = _deemph_lines(a_match.group(1))
            if (
                ans
                and ans != "<empty>"
                and not ans.startswith("(")
                and "미진행" not in ans
                and "여기에 본인 답변" not in ans
            ):
                item.answer = ans
        out.append(item)
    return out


def _extract_dash_field(body: str, label: str) -> str:
    m = re.search(rf"-[ \t]+\*\*{re.escape(label)}\*\*:[ \t]*(.*?)(?=\n-[ \t]+\*\*|\Z)",
                  body, flags=re.DOTALL)
    return m.group(1).strip() if m else ""


def _extract_followups(body: str) -> list[str]:
    m = re.search(r"-[ \t]+\*\*후속으로 읽을 논문\*\*:[ \t]*\n(.*?)(?=\n-[ \t]+\*\*|\Z)",
                  body, flags=re.DOTALL)
    if not m:
        return []
    items = re.findall(r"^\s*\d+\.[ \t]+(.+?)[ \t]*$", m.group(1), flags=re.MULTILINE)
    return [it for it in items if it.strip()]
