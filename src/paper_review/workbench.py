"""workbench.md generation + parsing.

The workbench.md is the human-readable single source of truth during review.
After ingest, it has only the skeleton (TL;DR, contribution placeholders,
prereqs, section stubs). The paper-review skill fills it in section by section.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass
class WorkbenchMeta:
    slug: str
    title_en: str
    title_ko: str
    paper_url: str
    category: str
    review_started: str
    status: str = "in_progress"  # in_progress | review_done | exported


def render_initial(paper_dir: Path, slug: str) -> str:
    """Build the initial workbench.md from a freshly-ingested paper directory.

    Expects in paper_dir:
      - <slug>_paper.json
      - <slug>_sections.txt
    """
    paper = json.loads((paper_dir / f"{slug}_paper.json").read_text())
    meta = paper.get("metadata", {})
    sections = _parse_sections_txt(paper_dir / f"{slug}_sections.txt")

    title_en = meta.get("title", "(untitled)")
    title_ko = meta.get("title_ko", "")
    paper_url = meta.get("url", "") or meta.get("source_url", "")
    category = meta.get("category", "")
    content_type = meta.get("content_type", "paper")
    today = date.today().isoformat()

    fm = [
        "---",
        f"slug: {slug}",
        f"content_type: {content_type}",
        f'title_en: "{_escape_yaml(title_en)}"',
        f'title_ko: "{_escape_yaml(title_ko)}"',
        f"paper_url: {paper_url}",
        f'category: "{category}"',
        f"review_started: {today}",
        "status: in_progress",
        "---",
        "",
    ]

    tldr = [
        f"# {title_ko or title_en} — 리뷰 워크벤치",
        "",
        "## TL;DR",
        "",
        "_(아직 비어있음. review 시작 시 `/explain tldr` 로 Claude에게 1차 초안 요청)_",
        "",
        f"- **원제**: {title_en}",
        f"- **저자**: {', '.join(meta.get('authors', [])[:3])}{' 외' if len(meta.get('authors', [])) > 3 else ''}",
        f"- **분류**: {category or '_(미정)_'}",
        f"- **링크**: {paper_url}",
        "",
    ]

    contrib = [
        "## 핵심 contribution",
        "",
        "_(review 중에 본인이 채워 넣기 — `/explain contributions` 로 Claude 초안 받을 수 있음)_",
        "",
        "1. ",
        "2. ",
        "3. ",
        "",
    ]

    prereqs = ["## 사전지식 카드", ""]
    prereq_list = paper.get("prerequisites") or []
    if prereq_list:
        for p in prereq_list:
            term = p.get("term", "(term)")
            why = p.get("explanation_ko") or p.get("why") or ""
            prereqs.append(f"- **{term}** — {why}")
    else:
        prereqs.append(
            "_(ingest는 사전지식 카드를 미리 만들지 않음 — review 중 `/explain prereqs` 로 추가)_"
        )
    prereqs.append("")

    section_lines: list[str] = ["## 섹션별 리뷰", ""]
    if sections:
        for sec_id, heading, line_range in sections:
            section_lines += [
                f"### {heading}",
                "",
                f"<!-- section_id: {sec_id} | lines: {line_range} -->",
                "",
                "_(미진행 — `/next-section` 로 진행)_",
                "",
            ]
    else:
        section_lines += [
            "_(sections.txt에 섹션이 없습니다. init_paper의 PDF 추출이 실패했을 수 있음)_",
            "",
        ]

    qna = [
        "## Q&A",
        "",
        "_(분석 중 Claude가 제기한 질문이 여기에 모입니다. 답변하면 publish 시 같이 출판됩니다.)_",
        "",
    ]

    wrap = [
        "## Wrap-up",
        "",
        "- **한 줄 contribution**:",
        "- **가장 약한 부분**:",
        "- **후속으로 읽을 논문**:",
        "  1. ",
        "  2. ",
        "  3. ",
        "",
        "## 메타",
        "",
        "- **총 소요 시간**:",
        "- **마지막 세션**:",
        "",
    ]

    return "\n".join(fm + tldr + contrib + prereqs + section_lines + qna + wrap)


def read_status(workbench_md: Path) -> str:
    """Read the `status:` frontmatter field from a workbench.md."""
    if not workbench_md.exists():
        return "missing"
    text = workbench_md.read_text()
    m = re.search(r"^status:\s*(\S+)\s*$", text, flags=re.MULTILINE)
    return m.group(1) if m else "unknown"


def _parse_sections_txt(path: Path) -> list[tuple[str, str, str]]:
    """Parse sections.txt → [(section_id, heading, line_range), ...]."""
    if not path.exists():
        return []
    out: list[tuple[str, str, str]] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(\d+-\d+):\s*(.+)$", line)
        if not m:
            continue
        line_range, heading = m.group(1), m.group(2)
        out.append((_slugify(heading), heading, line_range))
    return out


def _escape_yaml(s: str) -> str:
    return s.replace('"', '\\"')


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "section"
