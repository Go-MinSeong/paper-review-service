---
name: article-review
description: Collaborative section-by-section review of a general WEB ARTICLE — news, op-ed, product/tech review, or any web page that isn't an engineering blog or academic paper (content_type=article). Activates inside ~/Projects/paper-review-service/<slug>/ when workbench.md frontmatter says content_type: article. Same workbench mechanics as paper-review (/next-section, /answer, /explain, /challenge, /finalize, /status) but with a critical-reading rubric — thesis, key points, evidence quality, bias, counterpoints — instead of an academic one. Use when the user ingested a general web URL and starts reviewing it. Output is an updated workbench.md (the final post is produced by paper-publish). For academic papers use paper-review, for engineering/release blogs use blog-review.
---

# article-review

일반 웹 글(뉴스·칼럼·제품/테크 리뷰·해설 글) 1편을 섹션 단위로 같이 리뷰한다.
핵심은 "주장이 무엇이고, 근거가 탄탄한가, 무엇이 빠졌나"의 비판적 읽기.

## 활성 조건

- cwd 가 `~/Projects/paper-review-service/<slug>/` 이고 `workbench.md` frontmatter
  `content_type: article`
- 또는 그 폴더에서 `/next-section`, `/answer`, `/explain`, `/challenge`,
  `/finalize`, `/status` 사용
- content_type 이 `paper`/`blog` 이면 [[paper-review]] / [[blog-review]] 로 위임

## 진행 메커니즘

**공통 엔진**: `~/Projects/paper-review-service/src/paper_review/_paper_reader/references/review-engine.md`
명령어 흐름·dispatch 규칙·가드레일·viewer 재빌드는 전부 거기를 따른다.
원문이 영어면 paper-translator 가 EN→KO 번역, 이미 한국어면 요약·Notes 만.
아래는 **일반 글 전용 루브릭**.

## 일반 글 루브릭

`/explain` topic 의미:
- `tldr` — 5-7 문장. 글의 주제 / 핵심 주장 / 결론.
- `contributions` (= 핵심 포인트) — 글이 전달하는 핵심 메시지 2-4개를 workbench 1/2/3 에.
- `prereqs` — 글을 이해하는 데 필요한 맥락 5-12개 (사건 배경·인물·용어). 필요 없으면 생략.
- `key-terms` — 글 내부 핵심 용어.

`/next-section` 의 **Q (질문) 방향** — 비판적으로 읽게:
- 이 주장의 **근거**는 무엇이고 출처는 신뢰할 만한가
- 저자의 **관점/이해관계**가 서술에 미친 영향 (bias)
- 빠진 반대 논거 / 다른 시각
- 상관관계를 인과로 비약한 곳은 없는가
- (제품/테크 리뷰면) 장단점이 균형 있게 다뤄졌는가, 비교 기준은 공정한가

`/finalize` 마무리 질문 1개 (Wrap-up 의 `한 줄 contribution` 을 채운다):
1. 글의 핵심 주장을 한 줄로?

약한 근거·생각의 변화는 구조화 리포트(Summary)의 `05 한계` /
`06 후속 연구` 에서 다룬다.

## 참고

- 공통 엔진: `_paper_reader/references/review-engine.md`
- 번역 가이드: `_paper_reader/references/translation-guide.md`
- 다음 단계: [[paper-publish]] (article 템플릿으로 출판)
