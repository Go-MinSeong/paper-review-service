#!/usr/bin/env python3
"""
arXiv 논문에서 figure를 추출해 base64 data URI로 인코딩한 JSON을 만든다.

전략:
1. ar5iv HTML(`https://arxiv.org/html/<id>v1`)에서 <figure> 또는 <img> 추출 (primary)
2. 실패 시 arXiv source tarball(`https://arxiv.org/e-print/<id>`)에서 LaTeX
   \\includegraphics 파싱 → 이미지 파일 매핑 (fallback)

각 이미지를 width <max-width>px로 다운사이즈한 후 base64로 인코딩.

Usage:
    python fetch_figures.py 2410.24164 \\
        --out-dir /tmp/papers --max-width 800 \\
        --source-text /tmp/papers/2410.24164_source.txt

Output: stdout JSON (and write to <out-dir>/<id>_figures.json):
    [
      {"id": "fig3", "label": "Figure 3", "caption_en": "...",
       "caption_ko": "", "data_uri": "data:image/png;base64,...",
       "width": 800, "ref_in_section": null, "source": "ar5iv"}
    ]

ref_in_section은 source_text가 주어졌고 본문에 "Figure 3" 같은 매치가 있으면
첫 등장 부근의 추정 section_id로 채운다. 없으면 null.
"""

import sys
import os
import re
import json
import argparse
import base64
import io
import urllib.request
import urllib.error
import urllib.parse
import tarfile
import gzip
from pathlib import Path

HEADERS = {"User-Agent": "paper-reader/0.3 (research)"}


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _img_url_candidates(src, page_url, join_base):
    """Resolve an <img src> to candidate absolute URLs, most-likely first.

    arXiv's native HTML (arxiv.org/html/<id>v1/) uses PAGE-relative srcs like
    "x1.png" or "extracted/.../fig.jpeg", whereas older ar5iv emits id-prefixed
    srcs like "<id>v1/figures/fig2.jpeg". Joining only against the /html/ root
    (the old assumption) turns "x1.png" into ".../html/x1.png" → 404. Trying
    page-relative first, then the /html/ root, handles both formats without
    having to detect which one a given paper uses.
    """
    if src.startswith("http"):
        return [src]
    out = []
    for cand in (
        urllib.parse.urljoin(page_url, src),
        urllib.parse.urljoin(join_base, src),
    ):
        if cand not in out:
            out.append(cand)
    return out


# ---------- Image processing ----------


def downsize_to_data_uri(raw_bytes, max_width=800, jpeg_quality=80, force_jpeg=True):
    """Resize raster images to max_width if larger; pass SVG through unchanged.
    Returns (data_uri, width_used, mime).

    force_jpeg: if True (default), flatten alpha to white and save as JPEG.
    Cuts file size dramatically for figure-style images. Set False to keep
    PNG when transparency matters.
    """
    # SVG: don't rasterize, embed as-is
    if (
        raw_bytes[:5] == b"<?xml"
        or raw_bytes[:4] == b"<svg"
        or b"<svg" in raw_bytes[:200]
    ):
        b64 = base64.b64encode(raw_bytes).decode("ascii")
        return f"data:image/svg+xml;base64,{b64}", None, "image/svg+xml"

    try:
        from PIL import Image
    except ImportError:
        os.system("pip install pillow --break-system-packages -q")
        from PIL import Image

    try:
        img = Image.open(io.BytesIO(raw_bytes))
    except Exception as e:
        sys.stderr.write(f"[warn] PIL couldn't open image: {e}\n")
        return "", None, ""

    if force_jpeg:
        target_format = "JPEG"
    else:
        target_format = "PNG" if img.mode in ("RGBA", "LA", "P") else "JPEG"

    w, h = img.size
    if w > max_width:
        new_h = int(round(h * max_width / w))
        img = img.resize((max_width, new_h), Image.LANCZOS)
        w = max_width

    buf = io.BytesIO()
    if target_format == "JPEG":
        if img.mode in ("RGBA", "LA"):
            # Flatten alpha onto white background
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        save_kwargs = {"quality": jpeg_quality, "optimize": True, "progressive": True}
        mime = "image/jpeg"
    else:
        save_kwargs = {"optimize": True}
        mime = "image/png"
    img.save(buf, format=target_format, **save_kwargs)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:{mime};base64,{b64}", w, mime


# ---------- Strategy 1: ar5iv HTML ----------


def fetch_from_ar5iv(arxiv_id, max_width=800, jpeg_quality=80):
    """Returns list of figure dicts, or [] on failure."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        os.system("pip install beautifulsoup4 --break-system-packages -q")
        from bs4 import BeautifulSoup

    # ar5iv's <img src> values include the arxiv-id prefix (e.g.
    # "2410.24164v1/figures/fig2.jpeg"), so the join base must be the
    # /html/ root, not /html/<id>/. We still fetch the page itself at the
    # full path for content.
    page_url = f"https://arxiv.org/html/{arxiv_id}v1/"
    join_base = "https://arxiv.org/html/"
    try:
        html = http_get(page_url)
    except urllib.error.HTTPError:
        try:
            page_url = f"https://arxiv.org/html/{arxiv_id}/"
            html = http_get(page_url)
        except Exception:
            return []
    except Exception:
        return []

    soup = BeautifulSoup(html, "lxml")

    figures = []
    seen_srcs = set()
    fig_count = 0
    tbl_count = 0
    seen_table_ids = set()

    def _label_and_id(caption, default_kind):
        """Returns (label, label_id) from caption text. default_kind is 'figure' or 'table'."""
        nonlocal fig_count, tbl_count
        # Try Arabic numerals first: "Figure 3" / "Table 2" / "Fig. 3a"
        m = re.match(
            r"^(Figure|Fig\.?|Table|Tab\.?)\s+(\d+[a-z]?)", caption, re.IGNORECASE
        )
        if m:
            head = m.group(1).rstrip(".").lower()
            num = m.group(2).lower()
            if head.startswith("tab"):
                return f"Table {m.group(2)}", f"tbl{num}"
            else:
                return f"Figure {m.group(2)}", f"fig{num}"
        # Roman numeral tables (IEEE style): "TABLE I", "Table II"
        m = re.match(
            r"^(Figure|Fig\.?|Table|Tab\.?)\s+([IVXLCDM]+)\b", caption, re.IGNORECASE
        )
        if m:
            head = m.group(1).rstrip(".").lower()
            num = m.group(2).upper()
            if head.startswith("tab"):
                return f"Table {num}", f"tbl{num.lower()}"
            else:
                return f"Figure {num}", f"fig{num.lower()}"
        if default_kind == "table":
            tbl_count += 1
            return f"Table {tbl_count}", f"tbl_auto{tbl_count}"
        else:
            fig_count += 1
            return f"Figure {fig_count}", f"fig_auto{fig_count}"

    def _clean_table_html(table_tag):
        """Strip ar5iv-specific attributes that bloat HTML and clash with viewer CSS."""
        # Remove inline width/height/style on root and rows that often hardcode pixel widths
        for attr in ("style", "width", "height", "cellpadding", "cellspacing"):
            if table_tag.has_attr(attr):
                del table_tag[attr]
        # Drop ar5iv id attributes (we already have our own id)
        for el in table_tag.find_all(True):
            if el.has_attr("id"):
                del el["id"]
        return str(table_tag)

    # --- Pass 1: <figure> tags. Each can wrap an <img> (image figure) or <table> (table figure). ---
    figure_tables_seen = set()
    for fig_tag in soup.find_all("figure"):
        # Get caption
        caption = ""
        cap_tag = fig_tag.find("figcaption")
        if cap_tag:
            caption = re.sub(r"\s+", " ", cap_tag.get_text(" ", strip=True)).strip()

        # Detect kind: table > image priority since some figures have both layout artifacts
        inner_table = fig_tag.find("table")
        imgs = fig_tag.find_all("img")

        if inner_table is not None and not imgs:
            # Pure table figure
            label, label_id = _label_and_id(caption, default_kind="table")
            if label_id in seen_table_ids:
                continue
            seen_table_ids.add(label_id)
            figure_tables_seen.add(id(inner_table))
            figures.append(
                {
                    "id": label_id,
                    "kind": "table",
                    "label": label,
                    "caption_en": caption,
                    "caption_ko": "",
                    "html": _clean_table_html(inner_table),
                    "ref_in_section": None,
                    "source": "ar5iv",
                }
            )
            continue

        # Image figure (may also contain a small table that's part of the figure layout — fine, we keep image)
        if not imgs:
            continue
        label, label_id = _label_and_id(caption, default_kind="figure")
        img_tag = imgs[0]
        src = img_tag.get("src", "")
        if not src or src in seen_srcs:
            continue
        seen_srcs.add(src)

        raw = None
        last_err = None
        for full_url in _img_url_candidates(src, page_url, join_base):
            try:
                raw = http_get(full_url, timeout=20)
                break
            except Exception as e:
                last_err = e
        if raw is None:
            sys.stderr.write(f"[warn] failed to fetch image '{src}': {last_err}\n")
            continue

        data_uri, w, _ = downsize_to_data_uri(
            raw, max_width=max_width, jpeg_quality=jpeg_quality
        )
        if not data_uri:
            continue

        figures.append(
            {
                "id": label_id,
                "kind": "image",
                "label": label,
                "caption_en": caption,
                "caption_ko": "",
                "data_uri": data_uri,
                "width": w or max_width,
                "ref_in_section": None,
                "source": "ar5iv",
            }
        )

    # --- Pass 2: standalone <table> elements not already wrapped in a <figure>. ---
    # ar5iv sometimes emits tables outside <figure> with caption in a sibling <p> or
    # an enclosing <div class="ltx_table">.
    for table_tag in soup.find_all("table"):
        if id(table_tag) in figure_tables_seen:
            continue
        # Skip layout / decorative tables (ltx_tabular has actual data)
        cls = " ".join(table_tag.get("class") or [])
        if "ltx_tabular" not in cls and "ltx_equation" in cls:
            continue
        # Try to find an enclosing ltx_table div which often has a caption
        caption = ""
        parent = table_tag.find_parent(class_=re.compile(r"ltx_table"))
        if parent is not None:
            cap = parent.find(class_=re.compile(r"ltx_caption|ltx_caption_label"))
            if cap is None:
                # Fallback: any <figcaption> sibling
                cap = parent.find("figcaption")
            if cap is not None:
                caption = re.sub(r"\s+", " ", cap.get_text(" ", strip=True)).strip()

        # If no caption found, this is probably a layout table; skip
        if not caption:
            continue
        if not re.match(r"^(Table|Tab\.?)\s+\d", caption):
            continue

        label, label_id = _label_and_id(caption, default_kind="table")
        if label_id in seen_table_ids:
            continue
        seen_table_ids.add(label_id)

        figures.append(
            {
                "id": label_id,
                "kind": "table",
                "label": label,
                "caption_en": caption,
                "caption_ko": "",
                "html": _clean_table_html(table_tag),
                "ref_in_section": None,
                "source": "ar5iv",
            }
        )

    return figures


# ---------- Strategy 3: the PDF itself ----------
# ar5iv and the e-print tarball only exist for arXiv papers, so a paper
# registered from a PDF file had no figures at all. Captions are the anchor:
# find "Figure 3:" / "Table 2", work out which graphics or rules belong to it,
# and render that region. Vector charts come out too, which extracting the
# embedded images cannot do — most figures in a LaTeX PDF are drawn, not pasted.
LABEL = re.compile(r"(?m)^[ \t]*(Figure|Fig\.|Table|TABLE|FIGURE)[ \t]*(\d+)\b")
# A caption line reads "Figure 3: …", "Figure 3. …", "Table 3 | …" or
# "Figure 3 Overview of …". A sentence in the body reads "Table 1 is …" or
# "Figure 3, and …" — those are rejected.
AFTER_OK = re.compile(r"^\s*[:.|—–-]|^\s+[A-Z(]")
AFTER_SENTENCE = re.compile(
    r"^\s*(,|and\b|or\b|is\b|are\b|was\b|shows?\b|presents?\b|compares?\b|reports?\b|"
    r"illustrates?\b|summari[sz]es?\b|lists?\b|gives?\b|depicts?\b|in\b|of\b|for\b|with\b|to\b|also\b)"
)
GRAPHIC = {2, 3, 4, 5}


def charboxes(tp, a, b):
    out = []
    for i in range(a, b):
        try:
            l, bt, r, t = tp.get_charbox(i)
        except Exception:
            continue
        if r > l and t > bt:
            out.append((i, l, bt, r, t))
    return out


def first_line_box(tp, start, n):
    """Chars on the caption's own baseline, contiguous in x."""
    cb = charboxes(tp, start, min(n, start + 400))
    if not cb:
        return None
    _, l0, b0, r0, t0 = cb[0]
    xs0, ys0, xs1, ys1 = [l0], [b0], [r0], [t0]
    last_r = r0
    for _, l, bt, r, t in cb[1:]:
        if abs(bt - b0) > 3.0:
            break  # next line
        if l - last_r > 40:
            break  # jumped to another column on the same baseline
        xs0.append(l)
        ys0.append(bt)
        xs1.append(r)
        ys1.append(t)
        last_r = r
    return [min(xs0), min(ys0), max(xs1), max(ys1)]


def caption_paragraph(tp, start, n, line):
    """Grow the first line downward over following lines of the same caption."""
    box = list(line)
    lh = max(line[3] - line[1], 6)
    cb = charboxes(tp, start, min(n, start + 1500))
    lines = {}
    for _, l, bt, r, t in cb:
        key = round(bt / 2)
        lines.setdefault(key, [l, bt, r, t])
        e = lines[key]
        e[0] = min(e[0], l)
        e[1] = min(e[1], bt)
        e[2] = max(e[2], r)
        e[3] = max(e[3], t)
    rows = sorted(lines.values(), key=lambda e: -e[1])
    cur_bottom = box[1]
    for e in rows:
        if e[3] >= cur_bottom + 1:
            continue  # at or above the current bottom
        gap = cur_bottom - e[3]
        if gap > lh * 0.9:
            break
        if e[2] < box[0] + 10 or e[0] > box[2] - 10:
            continue  # other column
        if e[0] < box[0] - 15 or e[2] > box[2] + 60:
            continue
        box[1] = min(box[1], e[1])
        cur_bottom = e[1]
    return box


def _walk(page, form, transforms, out, depth=0):
    objs = (
        page.get_objects(max_depth=1)
        if form is None
        else page.get_objects(form=form, max_depth=1)
    )
    for o in objs:
        if o.type == 5:
            if depth < 12:
                _walk(page, o, [o.get_matrix()] + transforms, out, depth + 1)
            continue
        if o.type not in (2, 3, 4):
            continue
        try:
            rect = o.get_bounds()
        except Exception:
            continue
        # bounds of an object inside a form are in form space: carry them out
        # through every enclosing form's matrix, innermost first
        for m in transforms:
            rect = m.on_rect(*rect)
        out.append(tuple(rect))


def leaf_graphics(page, W, H):
    raw = []
    _walk(page, None, [], raw)
    keep = []
    for l, b, r, t in raw:
        w, h = r - l, t - b
        if (w < 2 and h < 2) or w * h > 0.85 * W * H:
            continue
        if b > H * 0.93 or t < H * 0.06:
            continue  # wholly in the running header / footer band (rules, logos)
        keep.append((l, b, r, t))
    return keep


def page_text(tp, n):
    """One character per char index. get_text_range() drops or merges generated
    characters (ligatures, soft hyphens), so its offsets drift from the indices
    get_charbox() expects — on some pages by over a hundred characters."""
    out = []
    for j in range(n):
        s = tp.get_text_range(j, 1)
        out.append(s[0] if s else " ")
    return "".join(out)


def extract(pdf_path):
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf_path)
    cands = {}  # (kind, num) -> list of candidate records
    for pno in range(len(doc)):
        page = doc[pno]
        W, H = page.get_size()
        tp = page.get_textpage()
        n = tp.count_chars()
        text = page_text(tp, n)
        graphics = leaf_graphics(page, W, H)
        caption_boxes = []
        for m0 in LABEL.finditer(text):
            a0 = text[m0.end() : m0.end() + 40]
            if AFTER_SENTENCE.match(a0) or not AFTER_OK.match(a0):
                continue
            l0 = first_line_box(tp, m0.start(), n)
            if l0:
                caption_boxes.append(caption_paragraph(tp, m0.start(), n, l0))

        for m in LABEL.finditer(text):
            after = text[m.end() : m.end() + 40]
            if AFTER_SENTENCE.match(after) or not AFTER_OK.match(after):
                continue
            kind = "tbl" if m.group(1).lower().startswith("tab") else "fig"
            num = int(m.group(2))
            line = first_line_box(tp, m.start(), n)
            if not line:
                continue
            para = caption_paragraph(tp, m.start(), n, line)
            cx0, cy0, cx1, cy1 = para
            lw = line[2] - line[0]
            if lw < 0.6 * W and line[2] < W * 0.6:
                col = (0, W / 2 + 8)
            elif lw < 0.6 * W and line[0] > W * 0.4:
                col = (W / 2 - 8, W)
            else:
                col = (0, W)
            near = [
                g
                for g in graphics
                if (0 <= g[1] - cy1 <= 60) or (0 <= cy0 - g[3] <= 45)
            ]
            if (
                col != (0, W)
                and near
                and (max(g[2] for g in near) - min(g[0] for g in near)) > 0.6 * W
            ):
                col = (0, W)  # a short caption over a full-width figure or table

            def in_col(g):
                ov = min(g[2], col[1]) - max(g[0], col[0])
                return ov > 0.5 * max(g[2] - g[0], 1)

            def grow(seed, pool, gap):
                if not seed:
                    return None
                box = [
                    min(g[0] for g in seed),
                    min(g[1] for g in seed),
                    max(g[2] for g in seed),
                    max(g[3] for g in seed),
                ]
                changed = True
                while changed:
                    changed = False
                    for g in pool:
                        vgap = max(g[1] - box[3], box[1] - g[3], 0)
                        hov = min(g[2], box[2]) - max(g[0], box[0])
                        if vgap <= gap and hov > -20:
                            nb = [
                                min(box[0], g[0]),
                                min(box[1], g[1]),
                                max(box[2], g[2]),
                                max(box[3], g[3]),
                            ]
                            if nb != box:
                                box = nb
                                changed = True
                return box

            def above():
                pool = [g for g in graphics if in_col(g) and g[1] >= cy1 - 4]
                seed = [g for g in pool if g[1] - cy1 <= 60]
                b = grow(seed, pool, 20)
                if b:
                    b[1] = max(b[1], cy1 + 1)
                return b

            def rules_in_col():
                return [
                    g
                    for g in graphics
                    if in_col(g) and (g[3] - g[1]) < 2.5 and (g[2] - g[0]) > 50
                ]

            def stop_at_neighbour(direction):
                """Where the next float begins — two tables in a column would
                otherwise be captured as one."""
                if direction == "below":
                    tops = [c[3] for c in caption_boxes if c[3] < cy0 - 2]
                    return max(tops) if tops else 0
                bots = [c[1] for c in caption_boxes if c[1] > cy1 + 2]
                return min(bots) if bots else H

            def table_span(direction):
                """Tables are framed by rules of about the same width (booktabs:
                top, mid, bottom). Their rows are text, so growing by graphics
                gaps never crosses from one rule to the next."""
                rules = rules_in_col()
                limit = stop_at_neighbour(direction)
                if direction == "below":
                    near = [r for r in rules if 0 <= cy0 - r[3] <= 110 and r[3] > limit]
                    if not near:
                        return None
                    top = max(near, key=lambda r: r[3])
                    tw = top[2] - top[0]
                    group = [
                        r
                        for r in rules
                        if r[3] <= top[3] + 0.5
                        and r[3] > limit
                        and abs((r[2] - r[0]) - tw) <= 0.35 * tw
                        and top[3] - r[3] <= 0.6 * H
                    ]
                    if len(group) < 2:
                        return None
                    lo = min(group, key=lambda r: r[1])
                    box = [
                        min(r[0] for r in group),
                        lo[1],
                        max(r[2] for r in group),
                        min(top[3], cy0 - 1),
                    ]
                else:
                    near = [r for r in rules if 0 <= r[1] - cy1 <= 110 and r[1] < limit]
                    if not near:
                        return None
                    bot = min(near, key=lambda r: r[1])
                    bw = bot[2] - bot[0]
                    group = [
                        r
                        for r in rules
                        if r[1] >= bot[1] - 0.5
                        and r[1] < limit
                        and abs((r[2] - r[0]) - bw) <= 0.35 * bw
                        and r[1] - bot[1] <= 0.6 * H
                    ]
                    if len(group) < 2:
                        return None
                    hi = max(group, key=lambda r: r[3])
                    box = [
                        min(r[0] for r in group),
                        max(bot[1], cy1 + 1),
                        max(r[2] for r in group),
                        hi[3],
                    ]
                return box if box[3] - box[1] >= 25 else None

            def text_block(direction):
                """A table drawn without rules: take the run of text lines next to
                the caption, stopping at the first gap wider than a blank line."""
                rows = {}
                for i in range(n):
                    try:
                        l, b, r, t = tp.get_charbox(i)
                    except Exception:
                        continue
                    if r <= l or t <= b or not in_col((l, b, r, t)):
                        continue
                    key = round(b / 2)
                    e = rows.setdefault(key, [l, b, r, t])
                    e[0] = min(e[0], l)
                    e[1] = min(e[1], b)
                    e[2] = max(e[2], r)
                    e[3] = max(e[3], t)
                lines = sorted(rows.values(), key=lambda e: -e[1])
                lh = max(cy1 - cy0, 8)
                limit = stop_at_neighbour(direction)
                box = None
                if direction == "below":
                    seq = [e for e in lines if e[3] <= cy0 + 1 and e[3] > limit]
                    edge = cy0
                else:
                    seq = [e for e in lines if e[1] >= cy1 - 1 and e[1] < limit]
                    seq.reverse()
                    edge = cy1
                for e in seq:
                    gap = (edge - e[3]) if direction == "below" else (e[1] - edge)
                    if gap > lh * 2.2:
                        break
                    box = (
                        [
                            min(box[0], e[0]),
                            min(box[1], e[1]),
                            max(box[2], e[2]),
                            max(box[3], e[3]),
                        ]
                        if box
                        else list(e)
                    )
                    edge = e[1] if direction == "below" else e[3]
                return box if box and (box[3] - box[1]) >= 25 else None

            def nearest_rule_side():
                rules = rules_in_col()
                below = [cy0 - r[3] for r in rules if 0 <= cy0 - r[3] <= 110]
                above = [r[1] - cy1 for r in rules if 0 <= r[1] - cy1 <= 110]
                if below and above:
                    return "below" if min(below) <= min(above) else "above"
                if below:
                    return "below"
                return "above" if above else "below"

            if kind == "fig":
                box, where = above(), "above"
                if box is None:
                    box, where = table_span("below"), "flip"
            else:
                first = nearest_rule_side()
                other = "above" if first == "below" else "below"
                box, where = table_span(first), first
                if box is None:
                    box, where = table_span(other), other
                if box is None:
                    box, where = text_block(first) or text_block(other), "text"
                if box is None:
                    box, where = above(), "graphics"
            if box is not None and kind == "tbl":
                # a short caption over a wider table: follow the table, not the caption
                col = (min(col[0], box[0] - 2), max(col[1], box[2] + 2))
            status = "ok" if box else "miss"
            if box is None:
                cands.setdefault((kind, num), []).append(
                    {"page": pno + 1, "status": "miss"}
                )
                continue
            x0, y0, x1, y1 = box
            x0, x1 = max(col[0], x0 - 5), min(col[1], x1 + 5)
            y0, y1 = max(0, y0 - 5), min(H, y1 + 5)
            if (x1 - x0) < 40 or (y1 - y0) < 25:
                cands.setdefault((kind, num), []).append(
                    {"page": pno + 1, "status": "tiny"}
                )
                continue
            rec = {
                "page": pno + 1,
                "kind": kind,
                "num": num,
                "status": status,
                "where": where,
                "box": [round(v) for v in (x0, y0, x1, y1)],
                "caption": re.sub(
                    r"\s+", " ", text[m.start() : m.start() + 400]
                ).strip()[:400],
                "crop": (x0, y0, W - x1, H - y1),
            }
            cands.setdefault((kind, num), []).append(rec)
    found = []
    for key in sorted(cands, key=lambda k: (k[0], k[1])):
        good = [c for c in cands[key] if c.get("status") == "ok"]
        if not good:
            continue
        found.append(good[0])
    return found


def fetch_from_pdf(pdf_path, max_width=800, jpeg_quality=80):
    """Render each captioned figure/table region of a local PDF."""
    try:
        import pypdfium2  # noqa: F401
    except ImportError:
        sys.stderr.write("[warn] pypdfium2 missing — cannot read figures from PDF\n")
        return []
    try:
        regions = extract(pdf_path)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[warn] pdf figure extraction failed: {e}\n")
        return []
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf_path)
    figures = []
    for r in regions:
        page = doc[r["page"] - 1]
        try:
            img = page.render(scale=2, crop=r["crop"]).to_pil()
        except Exception:
            continue
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data_uri, width, _ = downsize_to_data_uri(
            buf.getvalue(), max_width=max_width, jpeg_quality=jpeg_quality
        )
        kind = "table" if r["kind"] == "tbl" else "image"
        label = ("Table " if kind == "table" else "Figure ") + str(r["num"])
        figures.append(
            {
                "id": f"{r['kind']}{r['num']}",
                "kind": kind,
                "label": label,
                "caption_en": r["caption"],
                "caption_ko": "",
                "data_uri": data_uri,
                "width": width,
                "ref_in_section": None,
                "source": "pdf",
                "page": r["page"],
            }
        )
    return figures


# ---------- Strategy 2: arXiv source tarball ----------

# Allow overriding rasterization DPI for PDF figures
PDF_FIG_DPI = 200


def render_pdf_to_png(pdf_bytes):
    """Render first page of a PDF figure to PNG bytes. Used for vector figures
    in the tarball that aren't directly viewable as raster."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        os.system("pip install pypdfium2 --break-system-packages -q")
        import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(pdf_bytes)
    if len(pdf) == 0:
        return None
    page = pdf[0]
    pil_image = page.render(scale=PDF_FIG_DPI / 72).to_pil()
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def fetch_from_tarball(arxiv_id, max_width=800, jpeg_quality=80):
    """Download arXiv e-print tarball, parse LaTeX for \\includegraphics,
    match against included image files, extract figures."""
    src_url = f"https://arxiv.org/e-print/{arxiv_id}"
    try:
        raw = http_get(src_url, timeout=60)
    except Exception as e:
        sys.stderr.write(f"[warn] tarball fetch failed: {e}\n")
        return []

    # Try as gzip first, then tar
    try:
        # Most arXiv source bundles are .tar.gz
        bio = io.BytesIO(raw)
        # Some are bare .gz of a single .tex
        try:
            tar = tarfile.open(fileobj=bio, mode="r:gz")
        except tarfile.ReadError:
            bio.seek(0)
            try:
                tar = tarfile.open(fileobj=bio, mode="r:")
            except tarfile.ReadError:
                # Single gzipped tex file or PDF — no figures extractable
                return []
    except Exception as e:
        sys.stderr.write(f"[warn] tarball open failed: {e}\n")
        return []

    # Index members and extract LaTeX content
    members = {m.name: m for m in tar.getmembers() if m.isfile()}
    tex_blobs = []
    image_files = {}  # basename → bytes
    image_paths = {}  # full path → basename (for matching)

    for name, m in members.items():
        lower = name.lower()
        if lower.endswith(".tex"):
            try:
                content = tar.extractfile(m).read().decode("utf-8", errors="replace")
                tex_blobs.append((name, content))
            except Exception:
                pass
        elif lower.endswith((".png", ".jpg", ".jpeg", ".pdf", ".svg", ".eps")):
            try:
                image_files[name] = tar.extractfile(m).read()
                image_paths[name] = name
            except Exception:
                pass

    if not tex_blobs or not image_files:
        return []

    # Parse \includegraphics{path} or \includegraphics[opts]{path}
    full_tex = "\n".join(b[1] for b in tex_blobs)

    # Captions: find \begin{figure}...\caption{...}...\includegraphics{...}...\end{figure}
    figure_pattern = re.compile(
        r"\\begin\{figure\*?\}(.*?)\\end\{figure\*?\}", re.DOTALL
    )
    inc_pattern = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
    cap_pattern = re.compile(
        r"\\caption(?:\[[^\]]*\])?\{((?:[^{}]|\{[^{}]*\})*)\}", re.DOTALL
    )

    results = []
    fig_idx = 0

    for fmatch in figure_pattern.finditer(full_tex):
        body = fmatch.group(1)
        inc_matches = inc_pattern.findall(body)
        if not inc_matches:
            continue
        cap_match = cap_pattern.search(body)
        caption = ""
        if cap_match:
            # Strip LaTeX commands roughly
            caption = re.sub(r"\\[a-zA-Z]+\*?\s*", " ", cap_match.group(1))
            caption = re.sub(r"[{}]", "", caption)
            caption = re.sub(r"\s+", " ", caption).strip()

        # Resolve image file - try exact match, then with extensions, then basename match
        graphic_path = inc_matches[0].strip()
        candidates = []
        for ext in ["", ".png", ".pdf", ".jpg", ".jpeg", ".svg", ".eps"]:
            candidates.append(graphic_path + ext)
            candidates.append("./" + graphic_path + ext)
        # basename fallback
        bn = os.path.basename(graphic_path)
        for path in image_files:
            if os.path.basename(path).startswith(bn):
                candidates.append(path)

        chosen = None
        for c in candidates:
            for path in image_files:
                if path == c or path.endswith("/" + c) or os.path.basename(path) == c:
                    chosen = path
                    break
            if chosen:
                break

        if not chosen:
            continue

        raw_img = image_files[chosen]

        # Render PDF/EPS to PNG before passing to downsize
        if chosen.lower().endswith(".pdf"):
            png = render_pdf_to_png(raw_img)
            if png is None:
                continue
            raw_img = png
        elif chosen.lower().endswith(".eps"):
            # EPS is rare in modern arXiv but skip — no easy renderer here
            continue

        data_uri, w, _ = downsize_to_data_uri(
            raw_img, max_width=max_width, jpeg_quality=jpeg_quality
        )
        if not data_uri:
            continue

        fig_idx += 1
        # Detect label from caption start
        m = re.match(r"^(Figure|Fig\.?|Table|Tab\.?)\s+(\d+[a-z]?)", caption)
        if m:
            label = f"{m.group(1).rstrip('.')} {m.group(2)}"
            label_id = ("fig" if m.group(1).startswith("Fig") else "tbl") + m.group(
                2
            ).lower()
        else:
            label = f"Figure {fig_idx}"
            label_id = f"fig{fig_idx}"

        results.append(
            {
                "id": label_id,
                "kind": "image",
                "label": label,
                "caption_en": caption,
                "caption_ko": "",
                "data_uri": data_uri,
                "width": w,
                "ref_in_section": None,
                "source": "tarball",
            }
        )

    return results


# ---------- Section ref guessing ----------


def guess_section_refs(figures, source_text_path, sections_index_path):
    """For each figure, find first "Figure N" mention in source.txt and map to
    the section that line belongs to. Mutates figures in place."""
    if not (source_text_path and sections_index_path):
        return
    if not (os.path.isfile(source_text_path) and os.path.isfile(sections_index_path)):
        return

    with open(source_text_path, "r", encoding="utf-8") as f:
        source_lines = f.read().split("\n")
    section_ranges = []  # list of (start, end, label)
    with open(sections_index_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^(\d+)-(\d+):\s*(.+)$", line)
            if m:
                section_ranges.append((int(m.group(1)), int(m.group(2)), m.group(3)))

    def find_section_id_for_line(line_idx):
        for s, e, label in section_ranges:
            if s <= line_idx < e:
                # Convert label to section_id (lowercase, strip leading numbering)
                clean = re.sub(r"^[IVX]+\.\s*|\d+(?:\.\d+)?\s+", "", label)
                clean = re.sub(r"[^A-Za-z0-9가-힣]+", "-", clean).strip("-").lower()
                return clean or None
        return None

    for fig in figures:
        # Build a regex matching the label (e.g. "Figure 3", "Fig. 3", "Fig 3")
        m = re.match(r"^(Figure|Fig\.?|Table|Tab\.?)\s+(\d+[a-z]?)$", fig["label"])
        if not m:
            continue
        num = m.group(2)
        is_fig = fig["label"].lower().startswith("f")
        if is_fig:
            patterns = [
                rf"\bFigure\s+{num}\b",
                rf"\bFig\.\s*{num}\b",
                rf"\bFig\s+{num}\b",
            ]
        else:
            patterns = [rf"\bTable\s+{num}\b", rf"\bTab\.\s*{num}\b"]
        combined = re.compile("|".join(patterns))

        for i, line in enumerate(source_lines):
            if combined.search(line):
                sid = find_section_id_for_line(i)
                if sid:
                    fig["ref_in_section"] = sid
                break


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("arxiv_id", help="arXiv ID (e.g. 2410.24164)")
    ap.add_argument("--out-dir", default="/tmp/papers")
    ap.add_argument("--max-width", type=int, default=800)
    ap.add_argument(
        "--jpeg-quality",
        type=int,
        default=80,
        help="JPEG quality for raster images (1-100). Lower = smaller files.",
    )
    ap.add_argument("--source-text", help="path to source.txt for section ref guessing")
    ap.add_argument(
        "--sections-index", help="path to sections.txt for section ref guessing"
    )
    ap.add_argument(
        "--out-name", help="override output filename (default: <slug>_figures.json)"
    )
    ap.add_argument(
        "--pdf", help="local PDF to read figures from (used when arXiv has none)"
    )
    args = ap.parse_args()

    arxiv_id = args.arxiv_id.strip()
    pdf_only = arxiv_id in ("", "-", "none")
    # Normalize to bare ID
    m = re.search(r"(\d{4}\.\d{4,5})", arxiv_id)
    if m:
        arxiv_id = m.group(1)

    os.makedirs(args.out_dir, exist_ok=True)

    figures, source_used = [], "pdf"
    if not pdf_only:
        sys.stderr.write(f"[info] trying ar5iv for {arxiv_id}...\n")
        figures = fetch_from_ar5iv(
            arxiv_id, max_width=args.max_width, jpeg_quality=args.jpeg_quality
        )
        source_used = "ar5iv"
        if not figures:
            sys.stderr.write(
                "[info] ar5iv yielded 0 figures, trying source tarball...\n"
            )
            figures = fetch_from_tarball(
                arxiv_id, max_width=args.max_width, jpeg_quality=args.jpeg_quality
            )
            source_used = "tarball"
    if not figures and args.pdf and os.path.isfile(args.pdf):
        sys.stderr.write(
            f"[info] reading figures out of {os.path.basename(args.pdf)}...\n"
        )
        figures = fetch_from_pdf(
            args.pdf, max_width=args.max_width, jpeg_quality=args.jpeg_quality
        )
        source_used = "pdf"

    # Guess section refs
    if figures:
        # Try to auto-discover sources if not given
        slug = (args.out_name or "").replace("_figures.json", "") or arxiv_id.replace(
            "/", "_"
        )
        src_text = args.source_text or os.path.join(args.out_dir, f"{slug}_source.txt")
        secs = args.sections_index or os.path.join(args.out_dir, f"{slug}_sections.txt")
        guess_section_refs(figures, src_text, secs)

    # Write output
    out_name = args.out_name or f"{arxiv_id.replace('/', '_')}_figures.json"
    out_path = os.path.join(args.out_dir, out_name)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(figures, f, ensure_ascii=False, indent=2)

    summary = {
        "arxiv_id": arxiv_id,
        "source_used": source_used,
        "figure_count": len(figures),
        "labels": [f["label"] for f in figures],
        "section_refs_filled": sum(1 for f in figures if f.get("ref_in_section")),
        "out_path": out_path,
        "total_data_uri_bytes": sum(len(f.get("data_uri", "")) for f in figures),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
