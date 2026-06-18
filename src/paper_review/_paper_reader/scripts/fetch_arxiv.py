#!/usr/bin/env python3
"""
arXiv 논문의 메타데이터와 PDF 텍스트를 가져온다.

Usage:
    # arXiv ID or URL
    python fetch_arxiv.py 2410.24164 --out-dir /tmp/papers
    python fetch_arxiv.py https://arxiv.org/abs/2410.24164

    # Local PDF (e.g. user-uploaded or downloaded)
    python fetch_arxiv.py --pdf /mnt/user-data/uploads/foo.pdf --out-dir /tmp/papers
    python fetch_arxiv.py --pdf /path/to/paper.pdf

When given --pdf, this script tries to detect the arXiv ID from the PDF's
first page (looking for `arXiv:NNNN.NNNNN`). If found, metadata is fetched
from the arXiv API. Otherwise minimal metadata (title best-effort, no
authors) is returned and the caller should ask the user to fill the gaps.

Output: stdout JSON with:
    arxiv_id (or null), title, authors, abstract, published, pdf_path, full_text
"""

import sys
import re
import json
import os
import argparse
import urllib.request
import xml.etree.ElementTree as ET


def extract_arxiv_id(s: str) -> str:
    s = s.strip()
    # New format: 2410.12345 or 2410.12345v1
    m = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", s)
    if m:
        return m.group(1)
    # Old format: cs/0501001 or cs.LG/0501001
    m = re.search(r"([a-z\-]+(?:\.[A-Z]{2})?\/\d{7})", s)
    if m:
        return m.group(1)
    raise ValueError(f"Could not extract arXiv ID from: {s!r}")


def find_arxiv_id_in_text(text):
    """Find arXiv:NNNN.NNNNN or older formats in the first ~8KB of text."""
    head = text[:8000]
    m = re.search(r"arXiv\s*:\s*(\d{4}\.\d{4,5})(v\d+)?", head, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"arXiv\s*:\s*([a-z\-]+(?:\.[A-Z]{2})?\/\d{7})", head, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def fetch_metadata(arxiv_id: str) -> dict:
    url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "paper-reader/0.2"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read().decode("utf-8")
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(data)
    entry = root.find("a:entry", ns)
    if entry is None:
        raise RuntimeError(f"No arXiv entry for {arxiv_id}")

    def text_of(elem, path):
        e = elem.find(path, ns)
        return (e.text or "").strip() if e is not None else ""

    title = re.sub(r"\s+", " ", text_of(entry, "a:title"))
    abstract = re.sub(r"\s+", " ", text_of(entry, "a:summary"))
    authors = [
        (a.find("a:name", ns).text or "").strip() for a in entry.findall("a:author", ns)
    ]
    published = text_of(entry, "a:published")
    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "published": published,
    }


def download_pdf(arxiv_id: str, out_dir: str) -> str:
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    safe_id = arxiv_id.replace("/", "_")
    out_path = os.path.join(out_dir, f"{safe_id}.pdf")
    req = urllib.request.Request(pdf_url, headers={"User-Agent": "paper-reader/0.2"})
    with urllib.request.urlopen(req, timeout=60) as r, open(out_path, "wb") as f:
        f.write(r.read())
    return out_path


def extract_text(pdf_path: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        os.system("pip install pypdf --break-system-packages -q")
        from pypdf import PdfReader
    reader = PdfReader(pdf_path)
    parts = []
    for i, page in enumerate(reader.pages):
        try:
            parts.append(page.extract_text() or "")
        except Exception as e:
            parts.append(f"[page {i} extraction failed: {e}]")
    return "\n\n".join(parts)


def best_effort_title(text: str) -> str:
    """Try to extract a paper title from the first non-empty lines of the PDF."""
    for line in text.split("\n"):
        s = line.strip()
        if len(s) > 20 and len(s) < 200 and not s.lower().startswith("arxiv"):
            return s
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?", help="arXiv URL or ID")
    ap.add_argument("--pdf", help="path to a local PDF instead of fetching from arXiv")
    ap.add_argument(
        "--out-dir", default="/tmp/papers", help="where to save PDF and outputs"
    )
    ap.add_argument("--no-text", action="store_true", help="skip text extraction")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    if args.pdf:
        if not os.path.isfile(args.pdf):
            sys.exit(f"PDF not found: {args.pdf}")
        text = extract_text(args.pdf)
        arxiv_id = find_arxiv_id_in_text(text)
        if arxiv_id:
            try:
                meta = fetch_metadata(arxiv_id)
                meta["pdf_path"] = args.pdf
                meta["full_text"] = "" if args.no_text else text
                meta["pdf_arxiv_id_detected"] = True
                print(json.dumps(meta, ensure_ascii=False, indent=2))
                return
            except Exception as e:
                sys.stderr.write(f"[warn] arxiv API failed for {arxiv_id}: {e}\n")
        meta = {
            "arxiv_id": arxiv_id,
            "title": best_effort_title(text),
            "abstract": "",
            "authors": [],
            "published": "",
            "pdf_path": args.pdf,
            "pdf_arxiv_id_detected": arxiv_id is not None,
            "full_text": "" if args.no_text else text,
        }
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return

    if not args.input:
        sys.exit("Either positional arXiv URL/ID or --pdf is required")
    arxiv_id = extract_arxiv_id(args.input)
    meta = fetch_metadata(arxiv_id)
    pdf_path = download_pdf(arxiv_id, args.out_dir)
    meta["pdf_path"] = pdf_path
    if not args.no_text:
        meta["full_text"] = extract_text(pdf_path)
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
