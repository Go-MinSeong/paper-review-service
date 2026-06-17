#!/usr/bin/env python3
"""
웹 페이지(블로그·테크 리뷰·일반 글) 한 편을 받아 paper-reader 작업 환경을
초기화한다. init_paper.py 의 웹 버전 — 산출물 포맷은 **완전히 동일**하다.

만드는 것 (init_paper.py 와 같은 파일들):
- <out>/<slug>_source.txt    : 본문 (markdown — heading/list 보존)
- <out>/<slug>_sections.txt  : "<line_start>-<line_end>: <heading>" 섹션 인덱스
- <out>/<slug>_paper.json    : metadata 만 채워진 shell (content_type 포함)
- <out>/<slug>_figures.json  : 본문 이미지 (data_uri 임베드, fetch_figures 포맷)

핵심: 이 4개 파일 포맷만 동일하면 review/publish/viewer/server 가 입력이
논문이든 웹이든 그대로 작동한다.

Usage:
    python fetch_web.py https://vllm.ai/blog/2026-06-10-diffusion-gemma
    python fetch_web.py <url> --out-dir /tmp/run --content-type blog
    python fetch_web.py <url> --no-images

Output: stdout JSON (init_paper.py 와 같은 모양):
    {"id", "slug", "source_path", "sections_path", "paper_json_path",
     "content_type", "metadata", "section_count_detected", "warnings"}
"""

import sys
import os
import re
import json
import base64
import argparse
import urllib.parse

import httpx
import trafilatura
from bs4 import BeautifulSoup

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# 같은 디렉토리의 fetch_figures 헬퍼 재사용 (이미지 다운로드 + data_uri 변환)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from fetch_figures import http_get, downsize_to_data_uri  # noqa: E402

# /blog/, blog. 서브도메인, 또는 엔지니어링 블로그 도메인 → blog 로 추정
_BLOG_HINTS = re.compile(
    r"(?:^|\.)blog\.|/blog/|/posts?/|/engineering/|/research/", re.I
)


def classify(url: str, meta_sitename: str) -> str:
    """blog vs article 휴리스틱. 확신 없으면 article."""
    if _BLOG_HINTS.search(url):
        return "blog"
    return "article"


def make_slug(url: str, title: str) -> str:
    """host 약칭 + 제목 슬러그. 예: vllm.ai + 'DiffusionGemma: ...'
    → 'vllm-diffusiongemma-the-first-diffusion-llm'."""
    host = urllib.parse.urlparse(url).hostname or "web"
    host = re.sub(r"^www\.", "", host)
    host_main = host.split(".")[0]
    if title:
        tslug = re.sub(r"[^A-Za-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-")
    else:
        # 제목 없으면 마지막 path 세그먼트
        seg = urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]
        tslug = re.sub(r"[^A-Za-z0-9]+", "-", seg.lower()).strip("-")[:40]
    # 절단으로 끝에 1-2자 조각이 남으면 버린다 ("...llm-d" → "...llm")
    parts = tslug.split("-")
    if len(parts) > 1 and len(parts[-1]) <= 2:
        tslug = "-".join(parts[:-1])
    slug = f"{host_main}-{tslug}".strip("-") or "web"
    return slug


def build_sections_index(source_text: str, out_path: str) -> int:
    """source.txt(markdown)에서 heading 을 뽑아 섹션 인덱스를 쓴다.

    문서 최상단의 단일 h1(문서 제목)은 섹션에서 제외하고, 나머지 heading 을
    모두 평탄하게 섹션으로 쓴다 (논문의 "3 Method"+"3.1" 패턴과 동일). 첫 섹션
    이전 본문(lead)이 있으면 Introduction 섹션으로. heading 이 없으면 'Body' 하나.
    포맷은 init_paper.write_sections_index 와 동일 (<start>-<end>: heading).
    """
    lines = source_text.split("\n")
    raw_hits = []  # (line_idx, level, heading_text)
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(\S.*?)\s*#*\s*$", line)
        if m:
            raw_hits.append((i, len(m.group(1)), m.group(2).strip()))

    total = len(lines)
    # 최상단 단일 h1 = 문서 제목 → 섹션에서 제외
    if raw_hits:
        levels = [lv for _, lv, _ in raw_hits]
        min_lv = min(levels)
        if (
            raw_hits[0][1] == min_lv
            and levels.count(min_lv) == 1
            and min_lv < max(levels)
        ):
            raw_hits = raw_hits[1:]
    hits = [(i, txt) for i, _, txt in raw_hits]

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# Section index — total {total} lines\n")
        f.write("# Format: <line_start>-<line_end>: <heading>\n\n")
        if not hits:
            f.write(f"0-{total}: Body\n")
            return 1
        count = 0
        # 첫 섹션 이전 본문(lead)이 있으면 Introduction 으로
        if hits[0][0] > 1:
            f.write(f"0-{hits[0][0]}: Introduction\n")
            count += 1
        for j, (idx, heading) in enumerate(hits):
            end = hits[j + 1][0] if j + 1 < len(hits) else total
            f.write(f"{idx}-{end}: {heading}\n")
            count += 1
    return count


def extract_images(
    html: str, page_url: str, *, max_width: int, jpeg_quality: int, max_images: int
) -> tuple[list, list]:
    """본문 영역의 <img>/<figure> 를 다운로드해 figures.json 객체 리스트로.
    반환: (figures, warnings)."""
    figures, warnings = [], []
    soup = BeautifulSoup(html, "lxml")
    root = soup.find("article") or soup.find("main") or soup.body or soup
    seen_srcs = set()
    n = 0
    for tag in root.find_all(["figure", "img"]):
        if n >= max_images:
            break
        if tag.name == "figure":
            img = tag.find("img")
            if not img:
                continue
            cap_tag = tag.find("figcaption")
            caption = (
                re.sub(r"\s+", " ", cap_tag.get_text(" ", strip=True)).strip()
                if cap_tag
                else ""
            )
        else:
            # <figure> 안의 <img> 는 위에서 처리 → 중복 방지
            if tag.find_parent("figure"):
                continue
            img = tag
            caption = (img.get("alt") or "").strip()

        src = img.get("src") or img.get("data-src") or ""
        if not src or src.startswith("data:"):
            continue
        # 로고·아이콘·아바타는 콘텐츠가 아님
        if re.search(r"logo|icon|avatar|sprite", src, re.I):
            continue
        full_url = urllib.parse.urljoin(page_url, src)
        if full_url in seen_srcs:
            continue
        seen_srcs.add(full_url)
        try:
            raw = http_get(full_url, timeout=20)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"image fetch failed: {src} ({e})")
            continue
        if src.lower().split("?")[0].endswith(".svg"):
            # SVG 는 Pillow 로 못 여니 raw 를 그대로 data_uri 임베드 (<img> 에서 렌더됨)
            b64 = base64.b64encode(raw).decode("ascii")
            data_uri, w = f"data:image/svg+xml;base64,{b64}", None
        else:
            data_uri, w, _ = downsize_to_data_uri(
                raw, max_width=max_width, jpeg_quality=jpeg_quality
            )
        if not data_uri:
            continue
        n += 1
        figures.append(
            {
                "id": f"fig{n}",
                "kind": "image",
                "label": f"Figure {n}",
                "caption_en": caption,
                "caption_ko": "",
                "data_uri": data_uri,
                "width": w or max_width,
                "ref_in_section": None,
                "source": "web",
            }
        )
    return figures, warnings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out-dir", default="/tmp/papers")
    ap.add_argument(
        "--content-type", choices=["blog", "article", "auto"], default="auto"
    )
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--max-width", type=int, default=800)
    ap.add_argument("--jpeg-quality", type=int, default=80)
    ap.add_argument("--max-images", type=int, default=30)
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    try:
        resp = httpx.get(
            args.url, headers={"User-Agent": _UA}, follow_redirects=True, timeout=30
        )
        resp.raise_for_status()
        html = resp.text
    except Exception as e:  # noqa: BLE001
        sys.exit(f"fetch failed: could not download {args.url} ({e})")

    body_md = trafilatura.extract(
        html,
        output_format="markdown",
        include_tables=True,
        include_comments=False,
        favor_recall=True,
    )
    if not body_md:
        sys.exit(f"extraction failed: no main content found at {args.url}")

    md = trafilatura.extract_metadata(html)
    title = (md.title if md else "") or ""
    author = (md.author if md else "") or ""
    date = (md.date if md else "") or ""
    sitename = (
        (md.sitename if md else "") or urllib.parse.urlparse(args.url).hostname or ""
    )

    content_type = args.content_type
    if content_type == "auto":
        content_type = classify(args.url, sitename)

    slug = make_slug(args.url, title)
    source_path = os.path.join(args.out_dir, f"{slug}_source.txt")
    sections_path = os.path.join(args.out_dir, f"{slug}_sections.txt")
    paper_path = os.path.join(args.out_dir, f"{slug}_paper.json")
    figures_path = os.path.join(args.out_dir, f"{slug}_figures.json")

    with open(source_path, "w", encoding="utf-8") as f:
        f.write(body_md)
    n_sections = build_sections_index(body_md, sections_path)

    warnings = []
    if len(body_md) < 500:
        warnings.append(
            f"extracted body is very short ({len(body_md)} chars) — page may be "
            "paywalled or JS-rendered; review may be thin."
        )

    figures = []
    if not args.no_images:
        figures, fig_warns = extract_images(
            html,
            args.url,
            max_width=args.max_width,
            jpeg_quality=args.jpeg_quality,
            max_images=args.max_images,
        )
        warnings += fig_warns
    with open(figures_path, "w", encoding="utf-8") as f:
        json.dump(figures, f, ensure_ascii=False, indent=2)

    authors = [author] if author else []
    year = int(date[:4]) if date[:4].isdigit() else None
    paper_shell = {
        "metadata": {
            "title": title,
            "title_ko": "",
            "authors": authors,
            "venue": sitename,
            "year": year,
            "category": "",
            "content_type": content_type,
            "arxiv_id": None,
            "url": args.url,
            "source_url": args.url,
            "site": sitename,
            "published_date": date,
            "github_url": "",
            "abstract_en": "",
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
        "id": slug,
        "slug": slug,
        "content_type": content_type,
        "source_path": source_path,
        "sections_path": sections_path,
        "paper_json_path": paper_path,
        "figures_path": figures_path,
        "metadata": {
            "title": title,
            "author": author,
            "site": sitename,
            "published_date": date,
        },
        "section_count_detected": n_sections,
        "figure_count": len(figures),
        "source_text_length": len(body_md),
        "warnings": warnings,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
