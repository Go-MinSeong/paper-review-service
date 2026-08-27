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
import time
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
    # \b, not a trailing slash: qwen.ai puts the id in a query string
    # ("/blog?id=…") and was classified as a general article.
    r"(?:^|\.)blog\.|/blog\b|/posts?\b|/engineering\b|/research\b",
    re.I,
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


def visible_text(html: str) -> str:
    """Roughly what a reader would see — used to tell an empty shell apart."""
    stripped = re.sub(
        r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I
    )
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", stripped)).strip()


def render_js(url: str, timeout: float = 25.0) -> str | None:
    """Load `url` in a windowless WKWebView and return the rendered HTML.

    Some blogs ship an empty container and draw the article with JavaScript, so
    what httpx receives holds no text at all (qwen.ai/blog: four characters).
    WebKit is already here — pywebview pulls in PyObjC — so the page can simply
    be rendered in-process, with no browser dependency and no round trip
    through the app.

    Returns None on any failure (no GUI session, timeout, WebKit missing); the
    caller then reports the page as unreadable, exactly as before.
    """
    try:
        import AppKit  # noqa: F401  (starts the app object the run loop needs)
        import Foundation
        import WebKit
    except Exception:
        return None

    try:
        AppKit.NSApplication.sharedApplication()
        cfg = WebKit.WKWebViewConfiguration.alloc().init()
        # A throwaway data store: the page gets no cookies or local storage of
        # ours, and leaves none behind. We are rendering someone else's JS.
        cfg.setWebsiteDataStore_(WebKit.WKWebsiteDataStore.nonPersistentDataStore())
        # Tall viewport so lazy-loaded images below the fold still load.
        view = WebKit.WKWebView.alloc().initWithFrame_configuration_(
            Foundation.NSMakeRect(0, 0, 1280, 2000), cfg
        )
        view.loadRequest_(
            Foundation.NSURLRequest.requestWithURL_(
                Foundation.NSURL.URLWithString_(url)
            )
        )
    except Exception:
        return None

    loop = Foundation.NSRunLoop.currentRunLoop()
    deadline = time.time() + timeout

    def pump(seconds: float) -> None:
        loop.runMode_beforeDate_(
            Foundation.NSDefaultRunLoopMode,
            Foundation.NSDate.dateWithTimeIntervalSinceNow_(seconds),
        )

    def js(expr: str, wait: float = 8.0):
        box = {}

        def done(res, err):
            # PyObjC requires a void completion handler: returning anything
            # here raises inside the run loop and kills the process.
            box["v"] = None if err else res

        view.evaluateJavaScript_completionHandler_(expr, done)
        end = time.time() + wait
        while "v" not in box and time.time() < end:
            pump(0.05)
        return box.get("v")

    while view.isLoading() and time.time() < deadline:
        pump(0.1)

    # Client-side rendering continues after load finishes, so wait for the text
    # to stop growing rather than for a fixed delay — quicker on fast pages and
    # still correct on slow ones.
    # Two traps here, both hit in practice on qwen.ai:
    #  - an empty shell reads as "unchanged" three polls running, so text has to
    #    appear at all before stability means anything;
    #  - the app paints its chrome first and routes to the article after, so a
    #    nav-only page (413 chars) settles and looks done. Hence a floor on how
    #    early we may accept: the router gets a moment to arrive.
    MIN_TEXT, MIN_SETTLE = 200, 3.0
    started, stable, last = time.time(), 0, -1
    while time.time() < deadline:
        pump(0.3)
        size = js("document.body ? document.body.innerText.length : 0", wait=3.0)
        size = int(size) if isinstance(size, (int, float)) else 0
        elapsed = time.time() - started
        if size >= MIN_TEXT:
            stable = stable + 1 if size == last else 0
            if stable >= 3 and elapsed >= MIN_SETTLE:
                break
        elif elapsed > 8:
            break  # nothing is coming — a login wall, or not a page we can read
        last = size

    html = js("document.documentElement.outerHTML")
    return html if isinstance(html, str) and html.strip() else None


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
        # 직전 heading 텍스트 → 뷰어가 그림을 해당 섹션 자리에 인라인 배치하는 데 사용
        h = img.find_previous(["h1", "h2", "h3", "h4"])
        section_heading = (
            re.sub(r"\s+", " ", h.get_text(" ", strip=True)).strip() if h else ""
        )
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
                "section_heading": section_heading,
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

    def _extract(page: str):
        return trafilatura.extract(
            page,
            output_format="markdown",
            include_tables=True,
            include_comments=False,
            favor_recall=True,
        )

    body_md = _extract(html)
    rendered = False
    if not body_md and len(visible_text(html)) < 400:
        # An empty shell: nothing to extract because nothing arrived. Render it
        # rather than tell the user their page is unreadable. Only on this
        # path — a normal page must not pay for a browser it does not need.
        print("   ! 본문이 비어 있음 — 자바스크립트 렌더 후 재시도", file=sys.stderr)
        page = render_js(args.url)
        if page:
            html, rendered = page, True
            body_md = _extract(html)
    if not body_md:
        # Tell the two failures apart. A page whose served HTML carries almost
        # no text at all is a client-side app (qwen.ai/blog ships 4 characters
        # and an empty container); no extractor can help, and "no main content
        # found" reads like a bug in ours.
        visible = re.sub(
            r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I
        )
        visible = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", visible)).strip()
        if len(visible) < 400:
            sys.exit(
                f"extraction failed: {args.url} 는 본문을 자바스크립트로 그리는 "
                f"페이지라 받아온 HTML에 글이 없습니다 (본문 {len(visible)}자). "
                "브라우저에서 열어 PDF로 저장한 뒤 그 파일을 등록해 주세요."
            )
        sys.exit(f"extraction failed: no main content found at {args.url}")

    md = trafilatura.extract_metadata(html)
    title = (md.title if md else "") or ""
    author = (md.author if md else "") or ""
    date = (md.date if md else "") or ""
    if rendered:
        # A single-page app's <title> and og:* describe the app, not the post:
        # qwen.ai reports "Qwen Studio" and a date three weeks off. The rendered
        # <h1> is the article's own headline. Falling back to the first markdown
        # heading is worse than it sounds — that is usually "Introduction".
        soup_t = BeautifulSoup(html, "lxml")
        heads = [
            re.sub(r"\s+", " ", h.get_text(" ", strip=True)).strip("# ").strip()
            for h in soup_t.find_all("h1")
        ]
        heads = [h for h in heads if len(h) > 10]
        if heads:
            title = max(heads, key=len)
        date = ""  # a wrong date is worse than none
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
