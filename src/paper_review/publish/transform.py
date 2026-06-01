"""workbench.md → Velog draft markdown."""

from __future__ import annotations

import base64
import json
import re
from datetime import date
from pathlib import Path

from .parser import QnaItem, Section, Workbench, parse


def workbench_to_draft(
    workbench_md: Path,
    draft_md: Path,
    *,
    paper_dir: Path,
    vault_root: Path | None = None,
) -> None:
    wb = parse(workbench_md)
    draft = render(wb, paper_dir=paper_dir)
    # Bridge editor-inserted figures into the Velog vault so `velog publish`
    # can upload them (no-op when the draft has no figure references).
    draft = _materialize_figures(
        draft, paper_dir=paper_dir, draft_md=draft_md, vault_root=vault_root
    )
    draft_md.write_text(draft)


# ── Figure publish bridge ────────────────────────────────────────────────
# The review UI references figures by live-server routes:
#   ![alt](/paper/<slug>/fig/<id>)        → base64 data_uri in *_figures.json
#   ![alt](/paper/<slug>/figures/<file>)  → a file in <paper_dir>/figures/
#   ![alt](figures/<file>)                → same, relative form
# Velog's publisher (velog-obsidian) only uploads LOCAL files that live inside
# the vault. So at export time we decode/copy each referenced figure into
# <vault>/attachments/<slug>__<id>.<ext> and rewrite the URL to a
# vault-root-relative path the publisher resolves. Remote URLs and paths
# already under attachments/ are left untouched.
_MD_IMG = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_FIG_BY_ID = re.compile(r"^/paper/[^/]+/fig/([^/?#]+)$")
_FIG_BY_FILE = re.compile(r"^(?:/paper/[^/]+/)?figures/([^?#]+)$")
_MIME_EXT = {
    "image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg",
    "image/gif": "gif", "image/webp": "webp", "image/svg+xml": "svg",
}


def _load_figures_index(paper_dir: Path) -> dict:
    files = sorted(paper_dir.glob("*_figures.json"))
    if not files:
        return {}
    try:
        data = json.loads(files[0].read_text())
    except Exception:
        return {}
    items = data if isinstance(data, list) else data.get("figures", [])
    return {f.get("id"): f for f in items if isinstance(f, dict) and f.get("id")}


def _materialize_figures(
    draft: str, *, paper_dir: Path, draft_md: Path, vault_root: Path | None = None
) -> str:
    if "![" not in draft:
        return draft  # fast path: no images at all
    vault = vault_root or draft_md.parent.parent
    attachments = vault / "attachments"
    slug = paper_dir.name
    fig_index: dict | None = None

    def _write(name: str, raw: bytes, ext: str) -> str:
        attachments.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name) or "figure"
        out = attachments / f"{slug}__{safe}.{ext}"
        out.write_bytes(raw)
        return f"attachments/{out.name}"

    def repl(m: "re.Match[str]") -> str:
        nonlocal fig_index
        alt, url = m.group(1), m.group(2).strip()
        if url.startswith(("http://", "https://", "//", "attachments/")):
            return m.group(0)
        try:
            mi = _FIG_BY_ID.match(url)
            if mi:
                if fig_index is None:
                    fig_index = _load_figures_index(paper_dir)
                fig = fig_index.get(mi.group(1))
                if not (fig and fig.get("data_uri")):
                    return m.group(0)
                dm = re.match(r"data:(image/[\w.+-]+);base64,(.*)",
                              fig["data_uri"], re.DOTALL)
                if not dm:
                    return m.group(0)
                raw = base64.b64decode(dm.group(2))
                ext = _MIME_EXT.get(dm.group(1).lower(), "png")
                return f"![{alt}]({_write(mi.group(1), raw, ext)})"
            mf = _FIG_BY_FILE.match(url)
            if mf:
                src = paper_dir / "figures" / mf.group(1)
                if not src.is_file():
                    return m.group(0)
                ext = src.suffix.lstrip(".").lower() or "png"
                return f"![{alt}]({_write(src.stem, src.read_bytes(), ext)})"
        except Exception:
            return m.group(0)  # never break export over one image
        return m.group(0)

    return _MD_IMG.sub(repl, draft)


def render(wb: Workbench, *, paper_dir: Path) -> str:
    fm = _render_frontmatter(wb)
    body = _render_body(wb, paper_dir=paper_dir)
    return fm + "\n" + body


def _post_title(wb: Workbench) -> str:
    """Velog 노트 제목 — 논문 원제 사용, 너무 길면 70자에서 축약."""
    title_en = wb.frontmatter.get("title_en", "").strip()
    if title_en:
        if len(title_en) <= 70:
            return title_en
        return title_en[:67].rstrip() + "…"
    return wb.frontmatter.get("title_ko", "").strip() or "Paper Review"


def _render_frontmatter(wb: Workbench) -> str:
    title = _post_title(wb)
    paper_url = wb.frontmatter.get("paper_url", "")
    category = wb.frontmatter.get("category") or "paper-review"
    started = wb.frontmatter.get("review_started", date.today().isoformat())

    tags = ["paper-review"]
    if category and category.lower() not in {"paper-review", "", "other"}:
        tags.append(category.lower())

    lines = [
        "---",
        f'title: "{_yaml_q(title)}"',
        f"tags: [{', '.join(tags)}]",
        "draft: true",
        "is_private: false",
        f'paper_title: "{_yaml_q(wb.frontmatter.get("title_en", ""))}"',
        f"paper_url: {paper_url}",
        f'category: "{category}"',
        f"original_review_date: {started}",
        "---",
        "",
    ]
    return "\n".join(lines)


def _render_body(wb: Workbench, *, paper_dir: Path) -> str:
    parts: list[str] = []

    title = wb.frontmatter.get("title_ko") or wb.frontmatter.get("title_en", "")
    if title:
        parts.append(f"# {title.strip()}")
        parts.append("")

    if wb.tldr and not _is_placeholder(wb.tldr):
        parts += ["## TL;DR", "", _clean(wb.tldr), ""]

    parts += _render_paper_info(wb)

    real_contribs = [c for c in wb.contributions if c.strip()]
    if real_contribs:
        parts += ["## 핵심 contribution", ""]
        for i, c in enumerate(real_contribs, 1):
            parts.append(f"{i}. {_clean(c)}")
        parts.append("")

    real_prereqs = [p for p in wb.prereqs if p.strip() and not p.startswith("_")]
    if real_prereqs:
        parts += ["## 사전지식", ""]
        for p in real_prereqs:
            parts.append(f"- {_clean(p)}")
        parts.append("")

    parts += _render_sections(wb)

    parts += _render_qna(wb.qna)

    if wb.wrap_one_line or wb.wrap_weakness or wb.wrap_followups:
        parts += ["## 정리", ""]
        if wb.wrap_one_line:
            parts.append(f"**한 줄 요약**: {_clean(wb.wrap_one_line)}")
            parts.append("")
        if wb.wrap_weakness:
            parts.append(f"**한계 / 약점**: {_clean(wb.wrap_weakness)}")
            parts.append("")
        if wb.wrap_followups:
            parts.append("**후속으로 읽을 논문**:")
            for f in wb.wrap_followups:
                if f.strip():
                    parts.append(f"- {_clean(f)}")
            parts.append("")

    parts += [
        "---",
        "",
        "> _이 글은 Claude의 1차 번역 위에 본인 정리·검토를 더해 작성되었습니다._",
        "",
    ]

    return "\n".join(parts)


def _render_paper_info(wb: Workbench) -> list[str]:
    title_en = wb.frontmatter.get("title_en", "")
    paper_url = wb.frontmatter.get("paper_url", "")
    category = wb.frontmatter.get("category", "")
    if not (title_en or paper_url):
        return []
    out = ["## 논문 정보", ""]
    if title_en:
        out.append(f"- **원제**: {title_en}")
    if paper_url:
        out.append(f"- **링크**: {paper_url}")
    if category:
        out.append(f"- **분류**: {category}")
    out.append("")
    return out


def _render_sections(wb: Workbench) -> list[str]:
    parts: list[str] = []
    for sec in wb.sections:
        if not sec.done:
            continue

        parts.append(f"## {_clean_heading(sec.heading)}")
        parts.append("")

        # User callout (if user answer is non-placeholder)
        if sec.user_answer and not _is_placeholder(sec.user_answer):
            user_text = _clean(sec.user_answer).replace("\n", "\n> ")
            parts.append(f"> 💬 **내 정리**")
            parts.append(f"> ")
            parts.append(f"> {user_text}")
            parts.append("")

        # Summary (요약)
        if sec.summary and not _is_placeholder(sec.summary):
            parts.append("**요약**")
            parts.append("")
            parts.append(_clean(sec.summary))
            parts.append("")

        # Body — Claude translation (main content)
        if sec.claude_translation and not _is_placeholder(sec.claude_translation):
            parts.append(_clean(sec.claude_translation))
            parts.append("")

        # Reader's Notes — callout
        if sec.claude_notes and not _is_placeholder(sec.claude_notes):
            notes = _clean(sec.claude_notes).replace("\n", "\n> ")
            parts.append(f"> 💡 **읽으면서 생각해볼 점**")
            parts.append(f"> ")
            parts.append(f"> {notes}")
            parts.append("")

    return parts


def _render_qna(qna: list[QnaItem]) -> list[str]:
    if not qna:
        return []
    has_any = any(it.questions or it.answer for it in qna)
    if not has_any:
        return []
    parts = ["## Q & A — 토론", ""]
    for item in qna:
        if not item.questions and not item.answer:
            continue
        if item.from_section:
            parts.append(f"### §{item.from_section}")
            parts.append("")
        if item.questions:
            for i, q in enumerate(item.questions, 1):
                parts.append(f"{i}. **{_clean(q)}**")
            parts.append("")
        if item.answer:
            parts.append("> 💬 " + _clean(item.answer).replace("\n", "\n> "))
            parts.append("")
    return parts


def _is_placeholder(text: str) -> bool:
    stripped = text.strip()
    return (
        not stripped
        or stripped.startswith(("_(", "*("))   # italic marker, either delimiter
        or "미진행" in stripped
        or "여기에 본인 답변" in stripped
        or stripped == "<empty>"
    )


def _clean(text: str) -> str:
    lines = [ln.rstrip() for ln in text.strip().splitlines()]
    out: list[str] = []
    blank = False
    for ln in lines:
        if not ln:
            if not blank:
                out.append("")
            blank = True
        else:
            out.append(ln)
            blank = False
    return "\n".join(out)


def _clean_heading(h: str) -> str:
    return h.strip()


def _yaml_q(s: str) -> str:
    return s.replace('"', '\\"')
