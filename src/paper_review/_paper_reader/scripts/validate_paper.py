#!/usr/bin/env python3
"""
paper.json의 구조적 완성도를 검사하는 게이트.

build_html.py가 빌드 직전에 자동 호출. ERROR가 있으면 build_html이 실패하므로
메인이 빠뜨린 부분을 채우고 다시 빌드해야 한다. WARN은 빌드는 되지만
stderr로 알림.

이 스크립트의 역할은 instructions가 잡지 못한 구조적 누락을 코드 게이트로
잡아내는 것이다 — 즉 "메인이 잊었어도 빌드 단계에서 막힘" 보장.

Usage:
    python validate_paper.py /tmp/papers/<slug>_paper.json
    python validate_paper.py paper.json --json    # machine-readable

Exit:
    0 if no errors (warnings OK)
    2 if any errors
"""
import sys
import os
import re
import json
import argparse


# Required metadata fields. Missing → ERROR.
REQUIRED_METADATA = ("title", "year", "venue", "abstract_en")

# Recommended metadata fields. Missing → WARN.
RECOMMENDED_METADATA = ("title_ko", "abstract_ko", "category")

# Allowed category values (open list — anything else is OK but flagged for review)
KNOWN_CATEGORIES = {
    "VLA", "Foundation Models", "LLM", "VLM", "Diffusion", "RL", "Robotics",
    "Vision", "Speech", "NLP", "Theory", "Systems", "Other",
}


def _count_main_sections_from_index(sections_path):
    """Parse sections.txt and return the count of "main" section headings —
    excluding non-translatable ones (REFERENCES, ACKNOWLEDGEMENTS).
    Returns None if the file isn't found or unparseable.
    """
    if not os.path.isfile(sections_path):
        return None
    skip_terms = ("REFERENCES", "ACKNOWLEDG", "BIBLIOGRAPHY")
    count = 0
    with open(sections_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^\d+-\d+:\s*(.+)$", line)
            if not m:
                continue
            label = m.group(1).strip().upper()
            if any(t in label for t in skip_terms):
                continue
            count += 1
    return count if count > 0 else None


def _guess_sections_index_path(paper_path):
    """If paper.json is at /tmp/papers/<slug>_paper.json, sections.txt is at
    /tmp/papers/<slug>_sections.txt."""
    base = os.path.basename(paper_path)
    if not base.endswith("_paper.json"):
        return None
    slug = base[: -len("_paper.json")]
    return os.path.join(os.path.dirname(paper_path), f"{slug}_sections.txt")


def check_paper(paper, paper_path=None):
    """Returns (errors, warnings). Each is a list of strings."""
    errors = []
    warnings = []

    md = paper.get("metadata", {}) or {}

    # --- Required metadata ---
    for field in REQUIRED_METADATA:
        v = md.get(field)
        if not v or (isinstance(v, str) and not v.strip()):
            errors.append(f"metadata.{field} is missing or empty")

    # --- Recommended metadata ---
    for field in RECOMMENDED_METADATA:
        v = md.get(field)
        if not v or (isinstance(v, str) and not v.strip()):
            warnings.append(f"metadata.{field} is missing (recommended)")

    if md.get("category") and md["category"] not in KNOWN_CATEGORIES:
        warnings.append(
            f"metadata.category={md['category']!r} is not in known list "
            f"({sorted(KNOWN_CATEGORIES)}); review for typos"
        )

    # --- GitHub linkage: github_url present but no github block ---
    gh_url = (md.get("github_url") or "").strip()
    if gh_url and not paper.get("github"):
        errors.append(
            f"metadata.github_url={gh_url!r} is set but paper.github is null. "
            "fetch_github + github-investigator step was likely skipped."
        )

    # --- Sections sanity ---
    sections = paper.get("sections") or []
    if not sections:
        errors.append("paper.sections is empty (no translation done)")
    main_sections = [s for s in sections if s.get("level", 1) == 1]

    # --- Coverage check: compare against sections.txt index ---
    if paper_path and main_sections:
        idx_path = _guess_sections_index_path(paper_path)
        detected = _count_main_sections_from_index(idx_path) if idx_path else None
        if detected and len(main_sections) < detected * 0.5:
            errors.append(
                f"section coverage too low: paper.json has {len(main_sections)} main sections "
                f"but sections.txt detected {detected}. Translation likely truncated. "
                f"If skipping was intentional, add a metadata.notices entry explaining why "
                f"and re-run with --skip-validate."
            )
        elif detected and len(main_sections) < detected:
            missing = detected - len(main_sections)
            warnings.append(
                f"section coverage partial: {len(main_sections)}/{detected} main sections translated "
                f"({missing} missing). If intentional, ensure metadata.notices documents the skip."
            )

    # Sections without summary_ko
    sections_missing_summary = [
        s.get("id", "?") for s in sections
        if not (s.get("summary_ko") or "").strip()
    ]
    if sections and len(sections_missing_summary) / len(sections) > 0.3:
        warnings.append(
            f"summary_ko missing in {len(sections_missing_summary)}/{len(sections)} sections "
            f"({sections_missing_summary[:5]}{'...' if len(sections_missing_summary)>5 else ''})"
        )

    # paragraphs en/ko both present
    for s in sections:
        for i, p in enumerate(s.get("paragraphs") or []):
            if not (p.get("en") or "").strip() or not (p.get("ko") or "").strip():
                warnings.append(
                    f"section {s.get('id','?')!r} paragraph {i} has empty en or ko"
                )
                break  # one warning per section is enough

    # --- Reader's Notes coverage for content-heavy sections ---
    # 본문 ko 길이 > 1000자인 level-1 섹션은 readers_notes_md 가 비어있으면 ERROR.
    # paper-translator 가 "통찰 없으면 생략" 룰을 너무 적극 활용하는 문제 대응.
    for s in sections:
        if s.get("level", 1) != 1:
            continue
        paragraphs = s.get("paragraphs") or []
        total_chars = sum(len((p.get("ko") or "")) for p in paragraphs)
        if total_chars < 1000:
            continue  # short section, notes optional
        notes = (s.get("readers_notes_md") or "").strip()
        if not notes:
            errors.append(
                f"section {s.get('id','?')!r} has {total_chars} chars of translated "
                f"body but readers_notes_md is empty. Core sections require at least one "
                f"insight note (or an explicit one-line statement that no insight applies)."
            )
        elif len(notes) < 80:
            warnings.append(
                f"section {s.get('id','?')!r} readers_notes_md is very short "
                f"({len(notes)} chars) for a {total_chars}-char section — placeholder?"
            )

    # --- summary_ko vs paragraph copy-paste heuristic ---
    # summary_ko 첫 부분이 paragraphs[0].ko 와 ~60자+ 일치하면 재요약 의심.
    for s in sections:
        summary = (s.get("summary_ko") or "").strip()
        paragraphs = s.get("paragraphs") or []
        if not summary or not paragraphs:
            continue
        first_para = (paragraphs[0].get("ko") or "").strip()
        head_len = min(80, len(first_para))
        if head_len >= 60 and first_para[:head_len] in summary:
            warnings.append(
                f"section {s.get('id','?')!r} summary_ko 가 첫 단락을 그대로 인용한 "
                f"것으로 보임 (first {head_len} chars 일치). 압축이 아니라 복붙이면 재작성 권장."
            )

    # --- prereqs / key_terms presence ---
    # 4+ main 섹션 paper 는 prereqs 빈 경우 ERROR — 단순 demo paper 가 아닌 이상
    # "읽기 전 알아두면 좋은 것" 카드가 비어 viewer 가 빈약해짐. 짧은 paper(<4 main)
    # 는 진짜 사전 지식 없을 수 있어 WARN 유지.
    prereqs = paper.get("prerequisites") or []
    if not prereqs:
        if len(main_sections) >= 4:
            errors.append(
                f"prerequisites is empty for a {len(main_sections)}-section paper. "
                "Step 4 (외부 개념 식별) 가 skip 되었거나 너무 짧게 끝남. 핵심 섹션이 있는 "
                "paper 는 prereqs 최소 2개 — 정말 필요 없으면 한 줄 사유와 함께 placeholder "
                "항목 1개라도 둘 것."
            )
        else:
            warnings.append("prerequisites is empty (단계 4 skipped?)")
    elif len(prereqs) == 1 and len(main_sections) >= 4:
        warnings.append(
            f"prerequisites has only 1 entry for a {len(main_sections)}-section paper — "
            "본문이 사용하는 외부 개념을 더 찾을 수 있을 가능성. 메인이 step 4 를 빠르게 "
            "넘긴 신호일 수 있음."
        )
    if not paper.get("key_terms"):
        warnings.append("key_terms is empty (단계 4 skipped?)")

    # --- ambiguities: heuristic for "translator forgot to record any" ---
    ambiguities = paper.get("ambiguities") or []
    if not ambiguities and len(main_sections) >= 4:
        warnings.append(
            f"ambiguities is empty across {len(main_sections)} main sections — "
            "paper-translator may have skipped this step. "
            "If this is intentional (paper genuinely had no vague spots), ignore."
        )

    # If ambiguities exist but no code_clarifications, github-investigator was probably skipped
    code_clars = paper.get("code_clarifications") or []
    if ambiguities and not code_clars and gh_url:
        warnings.append(
            f"{len(ambiguities)} ambiguities recorded but code_clarifications is empty. "
            "github-investigator step may have been skipped."
        )

    # --- figures: when arxiv_id present, missing figures is suspicious ---
    if md.get("arxiv_id") and "figures" not in paper:
        warnings.append(
            "figures field absent (not even an empty array); "
            "fetch_figures.py call may have been skipped"
        )

    return errors, warnings


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paper", help="path to paper.json")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable JSON output")
    ap.add_argument("--quiet", action="store_true",
                    help="only print on errors (suppress 'OK' message)")
    args = ap.parse_args()

    with open(args.paper, "r", encoding="utf-8") as f:
        paper = json.load(f)

    errors, warnings = check_paper(paper, paper_path=args.paper)

    if args.json:
        print(json.dumps(
            {"errors": errors, "warnings": warnings,
             "ok": not errors,
             "paper_path": args.paper},
            ensure_ascii=False, indent=2,
        ))
    else:
        if errors:
            sys.stderr.write(f"❌ {len(errors)} error(s) in {args.paper}:\n")
            for e in errors:
                sys.stderr.write(f"  - {e}\n")
        if warnings:
            sys.stderr.write(f"⚠️  {len(warnings)} warning(s):\n")
            for w in warnings:
                sys.stderr.write(f"  - {w}\n")
        if not errors and not warnings and not args.quiet:
            sys.stdout.write(f"✓ {args.paper}: no issues\n")
        elif not errors and not args.quiet:
            sys.stdout.write(f"✓ {args.paper}: ok with warnings\n")

    sys.exit(2 if errors else 0)


if __name__ == "__main__":
    main()
