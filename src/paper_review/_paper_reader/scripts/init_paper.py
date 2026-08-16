#!/usr/bin/env python3
"""
한 번의 호출로 paper-reader 작업 환경을 초기화한다.

이 스크립트가 만드는 것:
- /tmp/papers/<id>_source.txt    : 본문 텍스트 (이후 view --view-range로만 접근)
- /tmp/papers/<id>_sections.txt  : "II Related Work: lines 213-319" 식 섹션 인덱스
- /tmp/papers/<id>_paper.json    : metadata만 채워진 paper.json 셸
                                   (prerequisites/key_terms는 빈 배열,
                                    sections=[], github=null, further_reading={})

이렇게 분리하는 이유: 본문 90KB가 컨텍스트에 통째로 들어오지 않게 하고,
이후 작업은 paper.json만을 truth로 신뢰하도록 강제하기 위함.

Usage:
    # arXiv ID/URL
    python init_paper.py 2410.24164
    python init_paper.py https://arxiv.org/abs/2410.24164

    # Local or uploaded PDF
    python init_paper.py --pdf /mnt/user-data/uploads/foo.pdf
    python init_paper.py --pdf /path/to/paper.pdf

    # Output dir override (default /tmp/papers)
    python init_paper.py 2410.24164 --out-dir /tmp/myrun

Output: stdout JSON with the paths and a brief summary:
    {
        "id": "2410.24164",
        "source_path": "...",
        "sections_path": "...",
        "paper_json_path": "...",
        "metadata": { title, authors, ... },
        "section_count": 8,
        "warnings": [...]
    }
"""

import sys
import os
import json
import collections
import re
import argparse
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def run_fetch_arxiv(args_list, out_dir):
    """Call fetch_arxiv.py and return parsed JSON. When invoked inside a frozen
    .app, runner sets PR_RUN_SCRIPT to the self-re-exec prefix so this nested
    call also avoids `python <file>` (unavailable when frozen)."""
    self_cmd = os.environ.get("PR_RUN_SCRIPT")
    if self_cmd:
        prefix = json.loads(self_cmd) + ["fetch_arxiv.py"]
    else:
        prefix = [sys.executable, os.path.join(SCRIPT_DIR, "fetch_arxiv.py")]
    cmd = prefix + args_list + ["--out-dir", out_dir]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        sys.exit(f"fetch_arxiv failed: {proc.returncode}")
    return json.loads(proc.stdout)


# Metric / unit tokens that mark a number-led line as DATA, not a heading
# (case-sensitive so "AP" doesn't match "Application"): "40.6 AP", "5.2 GFLOPs",
# "50 APval", "... 10 epochs".
_METRIC_RE = re.compile(
    r"\b(?:[mM]?AP\w*|AR\w*|G?FLOPs?|TFLOPs?|params?|epochs?|fps|mIoU|IoU)\b"
)


def _is_real_numbered_heading(top, rest):
    """Reject the many number-led NON-headings that the loose numeric rule used
    to promote to sections: metric sentences ("40.6 AP …"), GFLOPs/param values,
    table values ("50 APval"), references ("2024. Accessed …"), contribution
    bullets ("1. A DFL-free … architecture") and wrapped sentence fragments."""
    rest = rest.strip()
    if not rest or not rest[0].isupper():
        return False  # headings start with a capital word
    if top == 0 or top > 20:
        return (
            False  # real top-level sections are 1..~20; 40.6/2024/50 are values/years
        )
    if rest.endswith("-") or rest.endswith(","):
        return False  # hyphenated continuation / mid-sentence clause
    if re.match(r"^(A|An|The)\s", rest):
        return False  # article-led → contribution bullet / sentence, not a title
    if _METRIC_RE.search(rest):
        return False  # carries a metric/unit → a result line, not a heading
    if "{" in rest or "}" in rest:
        return False  # "1. Question: {question}" — a prompt template, not a title
    if rest.endswith(";"):
        return False  # "7. Signals: CH2=C carbon 145 s;" — a clause, not a title
    if rest.endswith(":"):
        return False  # "1. Global Memory:" — a labelled list item
    if re.search(r"\d+\.\d", rest):
        return False  # "1 Dense overlap 74.57" — a table row
    if rest.endswith(".") and " " in rest:
        return False  # a full sentence from a numbered instruction list
    if "," in rest and len(rest) > 40:
        return False  # long clause list → sentence or author affiliations
    return True


def find_section_boundaries(text):
    """Identify section headings in extracted PDF text. Returns list of
    (line_index, label) tuples, plus the line count of the file.

    Heuristics tuned for ML papers:
    - Roman numeral sections: 'I. INTRODUCTION', 'II. RELATED WORK', ...
    - Numbered sections: '1 Introduction', '2.1 Method', ... (with guards that
      reject number-led data/sentences — see _is_real_numbered_heading)
    - All-caps short lines that look like headings ('ABSTRACT', 'REFERENCES')
    """
    lines = text.split("\n")
    hits = []
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or len(s) > 100:
            continue
        # Roman numeral sections (e.g. "I. INTRODUCTION", "VI. EXPERIMENTAL EVALUATION")
        if re.match(r"^(I{1,3}|IV|V|VI{1,3}|IX|X|XI{0,3})\.\s+[A-Z]", s):
            hits.append((i, s))
            continue
        # Numbered (e.g. "1 Introduction", "3.2 Method", "1. Introduction",
        # "3.2. Method") - optional trailing dot covers CVPR/ICCV style.
        m = re.match(r"^(\d+)(?:\.\d+)*\.?\s+(\S.*)$", s)
        if m and len(s) < 80:
            if _is_real_numbered_heading(int(m.group(1)), m.group(2)):
                hits.append((i, s))
            continue
        # All caps (e.g. "ABSTRACT", "ACKNOWLEDGEMENTS", "REFERENCES", "APPENDIX").
        # Skip a single short ALL-CAPS token (e.g. a brand like "DEEPX") — real
        # all-caps headings are longer words.
        if re.match(r"^[A-Z][A-Z\s]{3,40}$", s) and len(s) > 4:
            if " " not in s and len(s) < 7:
                continue
            hits.append((i, s))
            continue
    return hits, len(lines)


# A real section always carries at least a couple of sentences. Everything the
# library had below this was a table fragment, a prompt-template line, or a
# repeated column header misread as a heading — never paper prose.
MIN_SECTION_CHARS = 80


def drop_bodyless(hits, lines, total, min_chars=MIN_SECTION_CHARS):
    """Drop headings that own (almost) no text of their own.

    A chapter title immediately followed by its first subsection ("2 Model
    Architecture" then "2.1 Overview") has nothing between them, and neither
    does a table row misread as a heading. Both used to become real sections:
    analyze spent a Claude call on each and the review carried a block whose
    only content was "본문 없이 장 제목만 있는 구간". The heading line survives as
    the tail of the preceding section, so the source view loses nothing.
    """
    kept = []
    for j, (i, label) in enumerate(hits):
        end = hits[j + 1][0] if j + 1 < len(hits) else total
        body = sum(len(l.strip()) for l in lines[i + 1 : end])
        if body >= min_chars:
            kept.append((i, label))
    return kept


_REFS_RE = re.compile(r"^\s*(?:\d+\.?\s+)?(?:references|bibliography)\s*$", re.I)


def cut_at_references(hits, lines, total):
    """End the index at the bibliography.

    Everything past it is references and appendix: reference entries whose
    initials read as Roman-numeral headings ("I. Mordatch, I. Radosavovic…"),
    prompt dumps, and table headers. Of the sections the library had after this
    line, 25 of 26 were noise. Cutting also stops the last real section from
    swallowing the whole bibliography, since it now ends here.
    """
    refs = [i for i, l in enumerate(lines) if _REFS_RE.match(l) and i > total * 0.3]
    if not refs:
        return hits, total
    cut = refs[-1]
    return [(i, lab) for i, lab in hits if i < cut], cut


def drop_repeats(hits):
    """Drop labels that occur more than once.

    A paper numbers each section exactly once, so a repeated label is a table
    column header reprinted on every page ("ABILITY", "ANSWERS") or a list item
    from a prompt template quoted several times. Both used to become a handful
    of identical sections.
    """
    seen = collections.Counter(label for _, label in hits)
    return [(i, label) for i, label in hits if seen[label] == 1]


_ALLCAPS_OK = re.compile(
    r"^(ABSTRACT|INTRODUCTION|CONCLUSIONS?|REFERENCES|BIBLIOGRAPHY|APPEND(IX|ICES)"
    r"|ACKNOWLED\w+|RELATED WORK|METHODS?|RESULTS|DISCUSSION|LIMITATIONS)\b"
)


def drop_out_of_order(hits):
    """Drop numbered headings that go backwards.

    A paper numbers its sections once, ascending. When "2 Cross-session" turns
    up after "6 Conclusion" it is a row of an appendix table, not section 2 —
    the same for the arithmetic fragments ("3. Thus total 38+19") that reasoning
    traces leave in an appendix. Papers whose bibliography is not detectable
    have no other boundary, so this is what ends the index for them.
    """
    kept, high, tops = [], 0, set()
    for i, label in hits:
        label = label.strip()
        m = re.match(r"^(\d+)(\.\d+)*\.?\s", label)
        if not m:
            kept.append((i, label))  # unnumbered headings carry no order
            continue
        top = int(m.group(1))
        bare = m.group(2) is None
        if top < high or (bare and top in tops):
            continue  # backwards, or a second "6 …" — the paper already had one
        high = top
        if bare:
            tops.add(top)
        kept.append((i, label))
    return kept


def drop_stray_allcaps(hits):
    """In a paper that numbers its sections, a bare ALL-CAPS line mid-document
    is a table or figure banner ("DECODED REASONING"), not a section."""
    numbered = sum(1 for _, l in hits if re.match(r"^\d", l.strip()))
    if numbered < 3:
        return hits
    return [
        (i, l)
        for i, l in hits
        if re.match(r"^\d", l.strip())  # numbered titles may be acronyms (4.3.4 STAL)
        or not l.strip().isupper()
        or _ALLCAPS_OK.match(l.strip())
    ]


def sections(text):
    """(hits, end) — the headings that earn a section, after every filter.

    The one place the filter chain lives: `tidy` re-derives the same list to
    find review blocks that are no longer sections, and when the two pipelines
    were written out separately they drifted apart immediately.
    """
    hits, total = find_section_boundaries(text)
    lines = text.split("\n")
    hits, total = cut_at_references(hits, lines, total)
    hits = drop_stray_allcaps(drop_out_of_order(drop_repeats(hits)))
    return drop_bodyless(hits, lines, total), total


def write_sections_index(text, out_path):
    """Write a human-readable section index file."""
    hits, total = sections(text)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# Section index — total {total} lines\n")
        f.write("# Format: <line_start>-<line_end>: <heading>\n\n")
        for j, (line_idx, label) in enumerate(hits):
            end = hits[j + 1][0] if j + 1 < len(hits) else total
            f.write(f"{line_idx}-{end}: {label}\n")
    return len(hits)


def detect_extraction_quality(text):
    """Return list of warning strings if extraction looks broken."""
    warnings = []
    head = text[:5000]
    cid_count = len(re.findall(r"cid:\d+", head, re.IGNORECASE))
    if cid_count > 5:
        warnings.append(
            f"PDF extraction has {cid_count} 'cid:NNNN' glyphs in the first 5KB — "
            "fonts may be non-embedded. Consider falling back to ar5iv HTML "
            f"(https://arxiv.org/html/<arxiv_id>) for cleaner text."
        )
    # Check if the text is one giant unbroken line (broken paragraph splitting)
    lines = text[:5000].split("\n")
    long_lines = sum(1 for l in lines if len(l) > 500)
    if long_lines > 2:
        warnings.append(
            f"PDF extraction has {long_lines} extremely long lines in the first 5KB — "
            "paragraph splitting may be broken."
        )
    return warnings


def make_slug(arxiv_id, title):
    if arxiv_id:
        return arxiv_id.replace("/", "_")
    # Fall back to first few words of title
    if title:
        slug = re.sub(r"[^A-Za-z0-9]+", "_", title.strip())[:40].strip("_").lower()
        return slug or "paper"
    return "paper"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?", help="arXiv URL or ID")
    ap.add_argument("--pdf", help="path to a local PDF")
    ap.add_argument("--out-dir", default="/tmp/papers")
    args = ap.parse_args()

    if not args.input and not args.pdf:
        sys.exit("Provide either an arXiv URL/ID or --pdf <path>")

    os.makedirs(args.out_dir, exist_ok=True)

    fetch_args = ["--pdf", args.pdf] if args.pdf else [args.input]
    fetched = run_fetch_arxiv(fetch_args, args.out_dir)

    arxiv_id = fetched.get("arxiv_id")
    title = fetched.get("title", "")
    slug = make_slug(arxiv_id, title)

    source_path = os.path.join(args.out_dir, f"{slug}_source.txt")
    sections_path = os.path.join(args.out_dir, f"{slug}_sections.txt")
    paper_path = os.path.join(args.out_dir, f"{slug}_paper.json")

    full_text = fetched.get("full_text", "")
    with open(source_path, "w", encoding="utf-8") as f:
        f.write(full_text)
    n_sections = write_sections_index(full_text, sections_path)
    warnings = detect_extraction_quality(full_text)

    paper_shell = {
        "metadata": {
            "title": title,
            "title_ko": "",
            "authors": fetched.get("authors", []),
            "venue": "",
            "year": (
                int(fetched.get("published", "")[:4])
                if fetched.get("published", "")[:4].isdigit()
                else None
            ),
            "category": "",
            "content_type": "paper",
            "arxiv_id": arxiv_id,
            "url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "",
            "github_url": "",
            "abstract_en": fetched.get("abstract", ""),
            "abstract_ko": "",
        },
        "prerequisites": [],
        "key_terms": [],
        "sections": [],
        "github": None,
        "further_reading": {},
        "ambiguities": [],
        "code_clarifications": [],
        "figures": [],
    }
    with open(paper_path, "w", encoding="utf-8") as f:
        json.dump(paper_shell, f, ensure_ascii=False, indent=2)

    summary = {
        "id": arxiv_id or slug,
        "slug": slug,
        "source_path": source_path,
        "sections_path": sections_path,
        "paper_json_path": paper_path,
        "pdf_path": fetched.get("pdf_path"),
        "metadata": {
            "title": title,
            "authors_count": len(fetched.get("authors", [])),
            "first_authors": fetched.get("authors", [])[:3],
            "abstract_length": len(fetched.get("abstract", "")),
        },
        "section_count_detected": n_sections,
        "source_text_length": len(full_text),
        "warnings": warnings,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
