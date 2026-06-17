---
name: paper-ingest
description: Ingest content into the local paper-review service — an academic paper (arXiv URL/ID or local PDF) OR a web page (engineering/release blog, news, op-ed, product/tech review). Creates ~/Projects/paper-review-service/<slug>/ with source.txt, sections.txt, paper.json (incl. content_type), workbench.md skeleton, viewer.html, and extracted figures/images. Use this when the user says "ingest <X>", "리뷰 시작", "paper-review init <...>", or shares an arXiv link / PDF / blog URL and asks to set up a review. Detects the source kind and classifies web content as blog vs article. Does NOT translate — translation is deferred to the matching review skill (paper-review / blog-review / article-review). After ingest, point the user to `paper-review session <slug>`.
---

# paper-ingest

콘텐츠 1편(논문 또는 웹 글)을 받아 **리뷰 워크벤치를 준비**한다. 번역·해석은
하지 않는다 — 그건 타입별 review 스킬이 인터랙티브로 한다.

## 트리거

다음 중 하나가 보이면 활성화:
- arXiv URL / ID, 로컬 PDF 경로
- **웹 페이지 URL** (블로그·릴리스 글·뉴스·테크/제품 리뷰)
- "ingest", "리뷰 시작", "paper-review init", "워크벤치 만들어"
- 사용자가 PDF/링크와 함께 "이거 리뷰하자"

끄고 대화로 답할 신호: 단순 요약 한두 문단, 여러 글 비교. 그땐 ingest 하지 말 것.

## 타입 감지 (content_type)

CLI 가 SOURCE 를 자동 분류한다:
- `.pdf` → paper (PDF) / arxiv ID·URL → paper (arxiv)
- 그 외 `http(s)://` → web. 웹은 다시 **blog vs article** 로 분류:
  - `/blog/`, `/posts/`, `blog.` 서브도메인, 엔지니어링/릴리스 글 → `blog`
  - 그 외 일반 웹 글·뉴스·칼럼·제품 리뷰 → `article`
- 자동 분류가 빗나가면 `--content-type blog|article` 로 강제하거나, ingest 후
  workbench.md frontmatter 의 `content_type:` 한 줄을 고치면 된다.

## 출력 계약

`~/Projects/paper-review-service/<slug>/` 하나 생성:

```
<slug>/
├── original.pdf            # PDF 업로드인 경우만
├── <slug>_source.txt       # 본문 (논문=plain text / 웹=markdown)
├── <slug>_sections.txt     # 섹션 인덱스 (<line_start>-<line_end>: heading)
├── <slug>_paper.json       # 단일 truth shell (metadata.content_type 포함)
├── <slug>_figures.json     # figure/이미지 (data_uri 임베드)
├── workbench.md            # ★ 리뷰 본체 — skeleton (frontmatter 에 content_type)
└── viewer.html             # 뷰어 (부산물)
```

응답은 1-3 문장:
1. 무엇인지 (title + 타입: paper/blog/article)
2. 핵심 1-2개 (추측 OK, 단정조 X)
3. `paper-review session <slug>` 로 리뷰 시작 안내

## 실행

```bash
paper-review init <arxiv-id | arxiv-url | /path/to/paper.pdf | https://blog-url>
# 웹 타입 강제: paper-review init <url> --content-type blog
```

CLI 가 안에서 (소스 종류에 따라):
1. `init_paper.py`(논문) 또는 `fetch_web.py`(웹) → source/sections/paper.json[/figures]
2. (논문·arxiv 만) `fetch_figures.py`
3. `workbench.md` skeleton (content_type frontmatter 포함)
4. `build_html.py` → viewer.html
5. `paper-translator`, `github-investigator` 서브에이전트 설치 (멱등)

## 옵션

- `--content-type blog|article|auto` — 웹 타입 (기본 auto)
- `--no-figures` — figure/이미지 추출 건너뛰기
- `--no-install-agents` — 서브에이전트 설치 안 함
- `--out-dir <path>` — 출력 경로 override

## ❌ 하지 말 것

- **섹션 번역 미리 하지 말 것** — review 가 섹션별 lazy 호출.
- **사전지식 카드 미리 채우지 말 것** — review 중 사용자가 무엇을 모르는지 보고 채움.
- **viewer.html 을 자동으로 띄우지 말 것** — `paper-review serve` 안내만.
- **figure 추출 실패를 ingest 실패로 처리하지 말 것** — 없이도 워크벤치는 작동.

## 실패 모드

- 논문 PDF 추출 품질 경고(cid:NNNN 다수) → workbench 메타에 한 줄 기록 후 진행.
- 웹 본문이 매우 짧음(페이월·JS 렌더) → fetch_web 이 warning 반환. 워크벤치에 메모 후 진행.
- figure/이미지 실패 → "없이 진행" 메모, 비실패.
- `build_html.py` 실패 → 워크벤치는 살리고 viewer 는 다음 세션에서 재시도.

## 다음 단계로의 인계

```
✓ <title> ingest 완료 (<type>) — ~/Projects/paper-review-service/<slug>/
  핵심: <1-2 lines>
  → paper-review session <slug>  로 리뷰 시작
```

서브에이전트가 새로 설치됐으면 "Claude Code 세션 재시작 필요" 한 줄 추가.

## 참고

- 전체 설계: `~/Projects/paper-review-service/DESIGN.md`, `dev/web-extension-plan.md`
- 다음 스킬: [[paper-review]] / [[blog-review]] / [[article-review]], [[paper-publish]]
- 엔진: `~/Projects/paper-review-service/src/paper_review/_paper_reader/`
