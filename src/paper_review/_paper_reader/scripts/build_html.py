#!/usr/bin/env python3
"""
viewer-template.html에 paper.json을 주입해 self-contained HTML을 생성한다.

Usage:
    python build_html.py --data paper.json --template viewer-template.html --out out.html
"""
import sys
import os
import re
import json
import argparse


PLACEHOLDER = '"__PAPER_DATA__"'


def _slug(s):
    """Lowercase, strip non-alphanumeric, collapse to a comparison key."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def normalize_figure_refs(paper):
    """fetch_figures.py가 채운 ref_in_section은 sections.txt의 raw label에서
    파생됐고, 실제 paper.json sections[].id는 메인이 별도로 부여하므로 둘이
    어긋날 수 있다. 빌드 시 fuzzy matching으로 figures의 ref_in_section을
    실제 section.id로 바꿔 viewer 렌더링이 매칭되게 한다.
    """
    figures = paper.get("figures") or []
    sections = paper.get("sections") or []
    if not figures or not sections:
        return 0

    # Build candidates: each section's id and titles, all normalized
    section_keys = []
    for sec in sections:
        sid = sec.get("id") or ""
        candidates = {_slug(sid), _slug(sec.get("title_en")), _slug(sec.get("title_ko"))}
        candidates.discard("")
        section_keys.append((sid, candidates))

    n_changed = 0
    for fig in figures:
        ref = fig.get("ref_in_section")
        if not ref:
            continue
        ref_slug = _slug(ref)
        if not ref_slug:
            continue

        # 1) exact id match — already correct, leave alone
        if any(ref == sid for sid, _ in section_keys):
            continue

        # 2) substring match: figure's slug is a substring of a candidate, or vice versa
        best = None
        for sid, candidates in section_keys:
            for c in candidates:
                if ref_slug == c or ref_slug in c or c in ref_slug:
                    # Prefer longer overlap when ambiguous: pick the candidate
                    # whose length is closest to ref_slug
                    score = min(len(ref_slug), len(c)) / max(len(ref_slug), len(c))
                    if best is None or score > best[0]:
                        best = (score, sid)
                    break

        if best:
            new_id = best[1]
            if new_id and new_id != ref:
                fig["ref_in_section"] = new_id
                n_changed += 1
        else:
            # No match — clear it so the figure goes into the unmatched gallery
            fig["ref_in_section"] = None
            n_changed += 1

    return n_changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="path to paper.json")
    ap.add_argument("--template", required=True, help="path to viewer-template.html")
    ap.add_argument("--out", required=True, help="output HTML path")
    ap.add_argument("--skip-validate", action="store_true",
                    help="skip the validate_paper.py gate (use only when intentional)")
    args = ap.parse_args()

    # --- Validation gate ---
    if not args.skip_validate:
        try:
            from validate_paper import check_paper as _check
        except ImportError:
            # validate_paper.py lives in the same scripts/ dir
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from validate_paper import check_paper as _check
        with open(args.data, "r", encoding="utf-8") as f:
            _paper_for_validation = json.load(f)
        errors, warnings = _check(_paper_for_validation, paper_path=args.data)
        if warnings:
            sys.stderr.write(f"⚠️  {len(warnings)} validation warning(s):\n")
            for w in warnings:
                sys.stderr.write(f"  - {w}\n")
        if errors:
            sys.stderr.write(f"❌ {len(errors)} validation error(s) — refusing to build:\n")
            for e in errors:
                sys.stderr.write(f"  - {e}\n")
            sys.stderr.write(
                "\nFix the errors and rebuild, or pass --skip-validate to override.\n"
                "Run: python validate_paper.py <paper.json> for details.\n"
            )
            sys.exit(2)

    with open(args.data, "r", encoding="utf-8") as f:
        paper = json.load(f)

    n_normalized = normalize_figure_refs(paper)
    if n_normalized:
        print(f"[info] normalized {n_normalized} figure ref_in_section values")

    data_text = json.dumps(paper, ensure_ascii=False)

    with open(args.template, "r", encoding="utf-8") as f:
        tpl = f.read()

    if PLACEHOLDER not in tpl:
        sys.exit(f"Template missing placeholder {PLACEHOLDER}")

    # Prevent the data string from accidentally closing the <script> tag
    safe_data = data_text.replace("</script>", "<\\/script>")

    out_html = tpl.replace(PLACEHOLDER, safe_data)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(out_html)
    print(f"Wrote {args.out} ({len(out_html):,} chars)")


if __name__ == "__main__":
    main()
