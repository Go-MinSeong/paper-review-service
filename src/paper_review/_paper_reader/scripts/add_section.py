#!/usr/bin/env python3
"""
한 번에 한 가지를 paper.json에 merge한다. 매 turn마다 새 Python 스크립트를
짜지 말고 이 헬퍼 하나로 통일.

지원하는 merge 종류:
- section: paper.json의 sections 배열에 한 섹션을 append (또는 id 매칭 시 replace)
- prerequisites: prerequisites 배열에 항목들을 append
- key_terms: key_terms 배열에 항목들을 append
- ambiguities: ambiguities 배열에 항목들을 append (paper-translator가 작성)
- code_clarifications: code_clarifications 배열에 항목들을 append (github-investigator가 작성)
- figures: figures 배열을 id 기준 merge. 비어있는 필드는 기존 값 보존 (caption_ko 점진 채움 패턴 지원)
- github: github 필드 set
- further_reading: further_reading 필드 set (덮어씀)
- metadata: metadata 필드의 일부를 update (예: title_ko, abstract_ko, venue, year, github_url)

Usage:
    # Append/replace a section from a JSON file
    python add_section.py --paper /tmp/papers/foo_paper.json \\
        --kind section --data /tmp/section_intro.json

    # 또는 stdin으로
    cat section.json | python add_section.py --paper /tmp/.../paper.json --kind section

    # prerequisites/key_terms도 같은 방식 (data는 배열)
    python add_section.py --paper ... --kind prerequisites --data /tmp/prereqs.json

    # github
    python add_section.py --paper ... --kind github --data /tmp/gh.json

    # metadata 부분 업데이트 (data는 dict, key/value만 update)
    python add_section.py --paper ... --kind metadata --data /tmp/meta_patch.json

    # 배치 모드 — 여러 merge를 한 번의 paper.json read+write로
    python add_section.py --paper /tmp/papers/foo_paper.json --batch /tmp/batch.json

batch.json 형식:
[
  {"kind": "metadata", "data_path": "/tmp/meta.json"},
  {"kind": "prerequisites", "data_path": "/tmp/prereqs.json", "mode": "replace"},
  {"kind": "key_terms", "data_path": "/tmp/key_terms.json", "mode": "replace"},
  {"kind": "section", "data_path": "/tmp/section_intro.json"},
  {"kind": "section", "data": {"id": "method", ...}}    # data inline 도 OK
]

Section JSON 예시:
{
  "id": "introduction",
  "level": 1,
  "title_en": "Introduction",
  "title_ko": "서론",
  "paragraphs": [{"en": "...", "ko": "..."}, ...],
  "readers_notes_md": "..."   // 선택
}

기본 동작은 append. 같은 id의 section이 이미 있으면 replace.
--mode replace를 명시하면 prerequisites/key_terms도 기존 항목을 비우고 set.
"""

import sys
import json
import argparse


def merge_figures(paper, items, mode):
    """Merge figures by id. mode='replace' overwrites whole array.
    mode='append' (default): for each incoming item, replace existing by id
    or append. Crucially, when the incoming item omits a field that the
    existing item has filled (e.g. caption_ko), preserve the existing value.
    This lets fetch_figures.py initially populate figures with empty
    caption_ko, then paper-translator update only caption_ko later without
    losing data_uri.
    """
    if not isinstance(items, list):
        sys.exit("figures data must be a list")
    if mode == "replace":
        paper["figures"] = items
        return f"replaced figures with {len(items)} items"

    existing = paper.setdefault("figures", [])
    by_id = {f.get("id"): (i, f) for i, f in enumerate(existing) if f.get("id")}

    added = 0
    updated = 0
    for incoming in items:
        fid = incoming.get("id")
        if fid and fid in by_id:
            idx, prior = by_id[fid]
            merged = dict(prior)
            for k, v in incoming.items():
                # Don't overwrite a populated value with an empty/missing one
                if v in (None, "", []):
                    continue
                merged[k] = v
            existing[idx] = merged
            updated += 1
        else:
            existing.append(incoming)
            added += 1
    return (
        f"figures merged: {added} added, {updated} updated (now {len(existing)} total)"
    )


VALID_KINDS = {
    "section",
    "prerequisites",
    "key_terms",
    "github",
    "further_reading",
    "metadata",
    "ambiguities",
    "code_clarifications",
    "figures",
}


def load_data(path_or_stdin):
    if path_or_stdin == "-" or path_or_stdin is None:
        return json.loads(sys.stdin.read())
    with open(path_or_stdin, "r", encoding="utf-8") as f:
        return json.load(f)


def merge_section(paper, section):
    if not isinstance(section, dict) or "id" not in section:
        sys.exit("Section data must be a dict with at least an 'id' field")
    sections = paper.setdefault("sections", [])
    for i, s in enumerate(sections):
        if s.get("id") == section["id"]:
            sections[i] = section
            return f"replaced section '{section['id']}' (was at index {i})"
    sections.append(section)
    return f"appended section '{section['id']}' (now {len(sections)} total)"


def merge_list_field(paper, field, items, mode):
    if not isinstance(items, list):
        sys.exit(f"{field} data must be a list")
    if mode == "replace":
        paper[field] = items
        return f"replaced {field} with {len(items)} items"
    existing = paper.setdefault(field, [])
    existing.extend(items)
    return f"appended {len(items)} items to {field} (now {len(existing)} total)"


def merge_dict_field(paper, field, data, replace=True):
    if not isinstance(data, dict):
        sys.exit(f"{field} data must be a dict")
    if replace or paper.get(field) is None:
        paper[field] = data
    else:
        paper[field].update(data)
    return f"set {field}"


def merge_metadata_patch(paper, patch):
    if not isinstance(patch, dict):
        sys.exit("metadata patch must be a dict")
    md = paper.setdefault("metadata", {})
    md.update(patch)
    return f"updated metadata fields: {', '.join(patch.keys())}"


def apply_one(paper, kind, data, mode):
    """Apply a single merge operation. Returns the message string."""
    if kind == "section":
        return merge_section(paper, data)
    elif kind in ("prerequisites", "key_terms", "ambiguities", "code_clarifications"):
        return merge_list_field(paper, kind, data, mode)
    elif kind == "figures":
        return merge_figures(paper, data, mode)
    elif kind == "github":
        return merge_dict_field(paper, "github", data, replace=True)
    elif kind == "further_reading":
        return merge_dict_field(paper, "further_reading", data, replace=True)
    elif kind == "metadata":
        return merge_metadata_patch(paper, data)
    else:
        sys.exit(f"Unknown kind: {kind}")


def summarize(paper):
    return {
        "section_count": len(paper.get("sections", [])),
        "prerequisites_count": len(paper.get("prerequisites", [])),
        "key_terms_count": len(paper.get("key_terms", [])),
        "has_github": paper.get("github") is not None,
        "from_references_count": len(
            (paper.get("further_reading") or {}).get("from_references", [])
        ),
        "follow_up_count": len(
            (paper.get("further_reading") or {}).get("follow_up", [])
        ),
        "ambiguities_count": len(paper.get("ambiguities", [])),
        "code_clarifications_count": len(paper.get("code_clarifications", [])),
        "figures_count": len(paper.get("figures", [])),
    }


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--paper", required=True, help="path to paper.json")
    ap.add_argument(
        "--kind", choices=sorted(VALID_KINDS), help="(single mode) what to merge"
    )
    ap.add_argument(
        "--data", help="(single mode) path to JSON file (or '-' / omit for stdin)"
    )
    ap.add_argument(
        "--mode",
        default="append",
        choices=["append", "replace"],
        help="for list fields: append (default) or replace",
    )
    ap.add_argument(
        "--batch",
        help="(batch mode) path to a batch JSON file: "
        "list of {kind, data_path|data, mode?}",
    )
    args = ap.parse_args()

    with open(args.paper, "r", encoding="utf-8") as f:
        paper = json.load(f)

    messages = []

    if args.batch:
        # Batch mode: one paper.json read+write, multiple merges
        with open(args.batch, "r", encoding="utf-8") as f:
            ops = json.load(f)
        if not isinstance(ops, list):
            sys.exit(
                "--batch file must contain a JSON array of {kind, data|data_path, mode?}"
            )
        for i, op in enumerate(ops):
            kind = op.get("kind")
            if kind not in VALID_KINDS:
                sys.exit(f"batch[{i}]: invalid kind {kind!r}")
            mode = op.get("mode", "append")
            if "data_path" in op:
                with open(op["data_path"], "r", encoding="utf-8") as f:
                    data = json.load(f)
            elif "data" in op:
                data = op["data"]
            else:
                sys.exit(f"batch[{i}]: must provide 'data' or 'data_path'")
            msg = apply_one(paper, kind, data, mode)
            messages.append(f"[{i}/{len(ops)}] {kind}: {msg}")
    else:
        if not args.kind:
            sys.exit("Either --kind (single mode) or --batch (batch mode) is required")
        data = load_data(args.data)
        messages.append(apply_one(paper, args.kind, data, args.mode))

    with open(args.paper, "w", encoding="utf-8") as f:
        json.dump(paper, f, ensure_ascii=False, indent=2)

    summary = {"ok": True, "messages": messages, **summarize(paper)}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
