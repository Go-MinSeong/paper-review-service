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
    args = ap.parse_args()

    arxiv_id = args.arxiv_id.strip()
    # Normalize to bare ID
    m = re.search(r"(\d{4}\.\d{4,5})", arxiv_id)
    if m:
        arxiv_id = m.group(1)

    os.makedirs(args.out_dir, exist_ok=True)

    # Try ar5iv first
    sys.stderr.write(f"[info] trying ar5iv for {arxiv_id}...\n")
    figures = fetch_from_ar5iv(
        arxiv_id, max_width=args.max_width, jpeg_quality=args.jpeg_quality
    )
    source_used = "ar5iv"
    if not figures:
        sys.stderr.write(f"[info] ar5iv yielded 0 figures, trying source tarball...\n")
        figures = fetch_from_tarball(
            arxiv_id, max_width=args.max_width, jpeg_quality=args.jpeg_quality
        )
        source_used = "tarball"

    # Guess section refs
    if figures:
        # Try to auto-discover sources if not given
        slug = arxiv_id.replace("/", "_")
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
