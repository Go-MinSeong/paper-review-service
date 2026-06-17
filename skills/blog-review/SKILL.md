---
name: blog-review
description: Collaborative section-by-section review of an engineering / release / tech BLOG post (content_type=blog) — e.g. a vLLM, PyTorch, or company engineering blog. Activates inside ~/Projects/paper-review-service/<slug>/ when workbench.md frontmatter says content_type: blog. Same workbench mechanics as paper-review (/next-section, /answer, /explain, /challenge, /finalize, /status) but with a blog-specific rubric — claims, design decisions & tradeoffs, practical takeaways, benchmark validity, adoption judgment — instead of an academic one. Use when the user ingested a blog URL and starts reviewing it. Output is an updated workbench.md (the final post is produced by paper-publish). For academic papers use paper-review, for general web articles use article-review.
---

# blog-review

엔지니어링·릴리스·테크 블로그 글 1편을 섹션 단위로 같이 리뷰한다.
논문과 달리 블로그는 "왜 이렇게 설계했나 / 실제로 쓸 만한가"가 핵심.

## 활성 조건

- cwd 가 `~/Projects/paper-review-service/<slug>/` 이고 `workbench.md` frontmatter
  `content_type: blog`
- 또는 그 폴더에서 `/next-section`, `/answer`, `/explain`, `/challenge`,
  `/finalize`, `/status` 사용
- content_type 이 `paper`/`article` 이면 [[paper-review]] / [[article-review]] 로 위임

## 진행 메커니즘

**공통 엔진**: `~/Projects/paper-review-service/src/paper_review/_paper_reader/references/review-engine.md`
명령어 흐름·dispatch 규칙·가드레일·viewer 재빌드는 전부 거기를 따른다.
원문이 영어면 paper-translator 가 EN→KO 번역, 이미 한국어면 요약·Notes 만.
아래는 **블로그 전용 루브릭**.

## 블로그 루브릭

`/explain` topic 의미:
- `tldr` — 도입부 기반 5-7 문장. 무엇을 발표/주장하나 / 왜 중요한가 / 핵심 수치.
- `contributions` (= 핵심 주장) — 이 글이 내세우는 주장/기여 2-4개를 workbench 1/2/3 에.
  논문 contribution 과 달리 "성능 N% 개선", "X 기능 최초 지원" 같은 제품/엔지니어링 주장.
- `prereqs` — 글을 이해하는 데 필요한 배경 5-12개 (해당 시스템·이전 릴리스·개념).
- `key-terms` — 글 내부 핵심 용어/컴포넌트 이름.

`/next-section` 의 **Q (질문) 방향** — 블로그를 비판적으로 읽게:
- 이 설계 결정의 **트레이드오프**는? 무엇을 포기했나
- 주장하는 성능/수치의 **측정 조건**은 공정한가 (하드웨어·배치·비교 대상)
- 마케팅/포지셔닝과 실제 기술 기여의 경계
- 내 환경/문제에 **적용**한다면 무엇이 걸림돌인가
- 재현/검증 가능한가 (코드·벤치마크 공개 여부)

`/finalize` 마무리 질문 3개:
1. 이 글의 핵심 주장을 한 줄로?
2. 가장 미심쩍거나 과장으로 보이는 부분은?
3. 내가 실제로 도입/시도한다면 다음 행동은? (또는 더 읽을 자료)

## 참고

- 공통 엔진: `_paper_reader/references/review-engine.md`
- 번역 가이드: `_paper_reader/references/translation-guide.md`
- 다음 단계: [[paper-publish]] (blog 템플릿으로 출판)
