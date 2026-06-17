"""workbench.md → Velog draft markdown."""

from __future__ import annotations

import base64
import json
import re
from datetime import date
from pathlib import Path

from .parser import QnaItem, Section, Workbench, parse

# ── Per-content-type labels ──────────────────────────────────────────────
# The workbench structure is identical across types (review skills fill the
# same blocks); only the surface wording differs. One label set per content_type
# keeps publish a single code path instead of three template files.
_LABELS = {
    "paper": {
        "primary_tag": "paper-review",
        "info_heading": "논문 정보",
        "contrib_heading": "핵심 contribution",
        "followups_heading": "후속으로 읽을 논문",
        "fallback_title": "Paper Review",
    },
    "blog": {
        "primary_tag": "tech-review",
        "info_heading": "글 정보",
        "contrib_heading": "핵심 주장",
        "followups_heading": "더 읽어볼 자료",
        "fallback_title": "Blog Review",
    },
    "article": {
        "primary_tag": "web-review",
        "info_heading": "글 정보",
        "contrib_heading": "핵심 포인트",
        "followups_heading": "더 읽어볼 자료",
        "fallback_title": "Article Review",
    },
}


def _labels(wb: Workbench) -> dict:
    ct = (wb.frontmatter.get("content_type") or "paper").strip().lower()
    return _LABELS.get(ct, _LABELS["paper"])


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
    # Un-escape emphasis markers the WYSIWYG editor escaped against raw HTML
    # spans (`\*\*<span>…</span>\*\*` → `**<span>…</span>**`) so bold/italic
    # actually render — must run BEFORE _merge_color_runs so the healed markers
    # can participate in the color-triple fold.
    draft = _unescape_emph_around_spans(draft)
    # Heal Toast-UI-fragmented color spans so Velog keeps the color (see below).
    draft = _merge_color_runs(draft)
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
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
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
                dm = re.match(
                    r"data:(image/[\w.+-]+);base64,(.*)", fig["data_uri"], re.DOTALL
                )
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
    labels = _labels(wb)
    fm = _render_frontmatter(wb, labels)
    body = _render_body(wb, paper_dir=paper_dir, labels=labels)
    return fm + "\n" + body


def _post_title(wb: Workbench, labels: dict) -> str:
    """Velog 노트 제목 — 원제 사용, 너무 길면 70자에서 축약."""
    title_en = wb.frontmatter.get("title_en", "").strip()
    if title_en:
        if len(title_en) <= 70:
            return title_en
        return title_en[:67].rstrip() + "…"
    return wb.frontmatter.get("title_ko", "").strip() or labels["fallback_title"]


def _render_frontmatter(wb: Workbench, labels: dict) -> str:
    title = _post_title(wb, labels)
    paper_url = wb.frontmatter.get("paper_url", "")
    primary = labels["primary_tag"]
    category = wb.frontmatter.get("category") or primary
    started = wb.frontmatter.get("review_started", date.today().isoformat())

    tags = [primary]
    if category and category.lower() not in {primary, "", "other"}:
        tags.append(category.lower())

    lines = [
        "---",
        f'title: "{_yaml_q(title)}"',
        f"tags: [{', '.join(tags)}]",
        "draft: true",
        "confirm: false",  # velog publish approval gate — flip to true to publish
        "is_private: false",
        f"content_type: {(wb.frontmatter.get('content_type') or 'paper').strip()}",
        f'paper_title: "{_yaml_q(wb.frontmatter.get("title_en", ""))}"',
        f"paper_url: {paper_url}",
        f'category: "{category}"',
        f"original_review_date: {started}",
        "---",
        "",
    ]
    return "\n".join(lines)


def _render_body(wb: Workbench, *, paper_dir: Path, labels: dict) -> str:
    parts: list[str] = []

    title = wb.frontmatter.get("title_ko") or wb.frontmatter.get("title_en", "")
    if title:
        parts.append(f"# {title.strip()}")
        parts.append("")

    if wb.tldr and not _is_placeholder(wb.tldr):
        parts += ["## TL;DR", "", _clean(wb.tldr), ""]

    parts += _render_paper_info(wb, labels)

    real_contribs = [c for c in wb.contributions if c.strip()]
    if real_contribs:
        parts += [f"## {labels['contrib_heading']}", ""]
        for i, c in enumerate(real_contribs, 1):
            parts.append(f"{i}. {_clean(c)}")
        parts.append("")

    real_prereqs = [p for p in wb.prereqs if p.strip() and not p.startswith("_")]
    if real_prereqs:
        parts += ["## 사전지식", ""]
        for p in real_prereqs:
            parts.append(f"- {_clean(p)}")
        parts.append("")

    parts += _render_pipelines(wb, paper_dir=paper_dir)

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
            parts.append(f"**{labels['followups_heading']}**:")
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


def _render_pipelines(wb: Workbench, *, paper_dir: Path) -> list[str]:
    """Render ```pipeline specs for publish. The review page animates them, but
    Velog/Obsidian are static — so if the user exported an animated GIF (stored
    as a figure `pipe<n>`), embed that image; otherwise fall back to a numbered
    step list + a one-line flow so the pipeline is never silently dropped."""
    pipelines = getattr(wb, "pipelines", None) or []
    if not pipelines:
        return []
    slug = paper_dir.name
    figs = _load_figures_index(paper_dir)
    out: list[str] = []
    for i, spec in enumerate(pipelines, 1):
        if not isinstance(spec, dict):
            continue
        title = (spec.get("title") or "파이프라인").strip()
        stages = [s for s in (spec.get("stages") or []) if isinstance(s, dict)]
        out += [f"## {title}", ""]
        fid = f"pipe{i}"
        if figs.get(fid, {}).get("data_uri"):
            # Animated GIF exported from the review page → image (animates on both).
            out += [f"![{title}](/paper/{slug}/fig/{fid})", ""]
        else:
            flow = " → ".join(
                (s.get("label", "").replace("\n", " ").split("(")[0].strip())
                for s in stages
                if s.get("label")
            )
            if flow:
                out += [f"**{flow}**", ""]
            for j, s in enumerate(stages, 1):
                lbl = _clean(s.get("label", "").replace("\n", " ").strip())
                cap = _clean((s.get("caption") or "").strip())
                out.append(f"{j}. **{lbl}**" + (f" — {cap}" if cap else ""))
            out.append("")
    return out


def _render_paper_info(wb: Workbench, labels: dict) -> list[str]:
    title_en = wb.frontmatter.get("title_en", "")
    paper_url = wb.frontmatter.get("paper_url", "")
    category = wb.frontmatter.get("category", "")
    if not (title_en or paper_url):
        return []
    out = [f"## {labels['info_heading']}", ""]
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
        # Render any section with real content — not just ones with a Claude
        # translation. Parent/transition sections (e.g. "6. 표현 분석") often
        # carry only a 요약 or Reader's Notes; skipping them dropped their
        # heading and notes from the post.
        if not any(
            v and not _is_placeholder(v)
            for v in (
                sec.user_answer,
                sec.summary,
                sec.claude_translation,
                sec.claude_notes,
            )
        ):
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
    has_any = any(it.questions or it.answer or it.heading for it in qna)
    if not has_any:
        return []
    parts = ["## Q & A — 토론", ""]
    for item in qna:
        if not (item.questions or item.answer or item.heading):
            continue
        # Format B: the question lives in the header. Render it as a bold
        # question line, then the (often multi-paragraph) answer as normal
        # markdown — not a blockquote, since these answers are long.
        if item.heading:
            parts.append(f"### {_clean_heading(item.heading)}")
            parts.append("")
            if item.answer:
                parts.append(_clean(item.answer))
                parts.append("")
            continue
        # Format A
        if item.from_section:
            parts.append(f"### §{item.from_section}")
            parts.append("")
        if item.questions:
            for i, q in enumerate(item.questions, 1):
                parts.append(f"{i}. {_clean(q)}")
            parts.append("")
        if item.answer:
            parts.append("> 💬 " + _clean(item.answer).replace("\n", "\n> "))
            parts.append("")
    return parts


def _is_placeholder(text: str) -> bool:
    stripped = text.strip()
    return (
        not stripped
        or stripped.startswith(("_(", "*("))  # italic marker, either delimiter
        or "미진행" in stripped
        or "여기에 본인 답변" in stripped
        or stripped == "<empty>"
    )


# WYSIWYG (Toast UI) over-escapes on save: "$\\sigma$" (doubled backslash),
# "정식화한다\." , "Qwen3\-4B". The review page looks fine because marked.js
# un-escapes when rendering — but the published draft was a verbatim copy, so
# Velog received "\\sigma" (a KaTeX line break) and "\." literals. We replicate
# marked's CommonMark backslash-unescaping at export so Velog matches the review.
_MATH_RE = re.compile(r"(\$\$[\s\S]*?\$\$|\$[^$\n]*?\$)")
# Inside math: un-escape ALL ASCII punctuation, incl. "\\"→"\" (restores LaTeX
# commands); single-backslash commands like \frac/\sigma are kept (letters aren't
# in the class).
_MATH_UNESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")
# Outside math: only un-escape "inactive" punctuation that won't re-trigger
# markdown (leave \* \_ \[ \# \| \` \~ \\ escaped so Velog doesn't re-parse them).
_PROSE_UNESCAPE = re.compile(r"""\\([.,:;!?()<>=/"'-])""")


def _unescape_md(text: str) -> str:
    parts = _MATH_RE.split(text)
    for i, p in enumerate(parts):
        parts[i] = (_MATH_UNESCAPE if i % 2 else _PROSE_UNESCAPE).sub(r"\1", p)
    return "".join(parts)


# LaTeX table-styling directives that leak from the paper source into markdown
# table cells (no markdown meaning — Velog renders them as literal garbage).
_LATEX_TABLE_JUNK = re.compile(
    r"\\{1,2}(?:rowcolors?|cellcolor|columncolor)\s*"
    r"(?:\[[^\]]*\])?\s*(?:\{[^}]*\}|[\d.]+)?\s*"
    r"|\\{1,2}(?:hline|toprule|midrule|bottomrule)\b"
    r"|\\{1,2}cline\s*\{[^}]*\}"
)


def _clean(text: str) -> str:
    text = _unescape_md(text)
    text = _LATEX_TABLE_JUNK.sub("", text)
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
    return _unescape_md(h.strip())


# ── Color-span reliability ───────────────────────────────────────────────
# Toast UI's color-syntax plugin splits a colored run around bold/italic
# markers, producing the SYMMETRIC triple
#   <span C>A</span>**<span C>B</span>**<span C>C</span>
# (same emphasis token on both sides of the middle span). Velog's markdown
# parser frequently DROPS the color on these fragmented `**<span>**` forms —
# the user's "색상이 일부 반영 안 됨" symptom. We heal it by folding the triple
# into one span with the emphasis moved inside: <span C>A**B**C</span>, which
# Velog renders reliably. Only the symmetric form is merged (markers stay
# balanced); asymmetric/odd cases are left untouched to avoid dangling markers.
_EMPH = r"(?:\*\*|\*|__|_|~~)"
_OPEN = r'<span style="color:\s*{c}\s*">'
_CONTENT = r"(?:(?!</span>).)*?"
_COLOR_TRIPLE = re.compile(
    _OPEN.format(c=r"(?P<c>[^\";]+?)") + r"(?P<a>" + _CONTENT + r")</span>"
    r"(?P<e>"
    + _EMPH
    + r")"
    + _OPEN.format(c=r"(?P=c)")
    + r"(?P<b>"
    + _CONTENT
    + r")</span>"
    r"(?P=e)" + _OPEN.format(c=r"(?P=c)"),
    re.S,
)
# Adjacent same-color spans separated only by whitespace → one span.
_COLOR_WS = re.compile(
    _OPEN.format(c=r"(?P<c>[^\";]+?)") + r"(?P<a>" + _CONTENT + r")</span>"
    r"(?P<sep>\s*)" + _OPEN.format(c=r"(?P=c)"),
    re.S,
)
# Emphasis wrapping a single colored span — `**<span C>text</span>**`. Velog
# frequently DROPS the color on this "emphasis outside the span" form, so move
# the markers INSIDE: `<span C>**text**</span>`, which Velog renders reliably
# (same fix the triple-merge applies, for the simple non-fragmented case).
_EMPH_WRAPS_SPAN = re.compile(
    r"(?P<e>"
    + _EMPH
    + r")"
    + _OPEN.format(c=r"(?P<c>[^\";]+?)")
    + r"(?P<t>"
    + _CONTENT
    + r")</span>"
    r"(?P=e)",
    re.S,
)


# Toast UI's WYSIWYG markdown serializer escapes emphasis markers that sit
# flush against raw HTML — our color <span>s. A bold-colored run authored as
#   **<span style="color: #e64980">text</span>**
# round-trips through the editor as
#   \*\*<span style="color: #e64980">text</span>\*\*
# which Velog (and marked.js in the review pane) render as LITERAL asterisks
# instead of bold — the "bold가 안 먹는다" symptom. Genuine literal `\*` in
# prose is never flush against a span boundary, so we only un-escape emphasis
# runs immediately adjacent to a `<span>`/`</span>`.
_ESC_EMPH_BEFORE_SPAN = re.compile(r"((?:\\[*_~])+)(?=<span\b)")
_ESC_EMPH_AFTER_SPAN = re.compile(r"(</span>)((?:\\[*_~])+)")


def _unescape_emph_around_spans(text: str) -> str:
    text = _ESC_EMPH_BEFORE_SPAN.sub(lambda m: m.group(1).replace("\\", ""), text)
    text = _ESC_EMPH_AFTER_SPAN.sub(
        lambda m: m.group(1) + m.group(2).replace("\\", ""), text
    )
    return text


def _merge_color_runs(text: str) -> str:
    prev = None
    while prev != text:
        prev = text
        text = _COLOR_TRIPLE.sub(
            lambda m: f'<span style="color: {m.group("c")}">'
            f'{m.group("a")}{m.group("e")}{m.group("b")}{m.group("e")}',
            text,
        )
        text = _COLOR_WS.sub(
            lambda m: f'<span style="color: {m.group("c")}">'
            f'{m.group("a")}{m.group("sep")}',
            text,
        )
        text = _EMPH_WRAPS_SPAN.sub(
            lambda m: f'<span style="color: {m.group("c")}">'
            f'{m.group("e")}{m.group("t")}{m.group("e")}</span>',
            text,
        )
    return text


def _yaml_q(s: str) -> str:
    return s.replace('"', '\\"')
