---
name: paper-review
description: Collaborative section-by-section review of an academic PAPER (content_type=paper). Activates inside ~/Projects/paper-review-service/<slug>/ when workbench.md frontmatter says content_type: paper (or has no content_type — legacy papers). Each section produces (1) Claude's 1차 번역 + Reader's Notes, (2) probing questions, (3) the user's answer (the primary content). Use when the user has ingested a paper and types "/next-section", "/explain", "/challenge", "/finalize", "/status", or starts discussing the paper. Mechanics live in _paper_reader/references/review-engine.md; this skill carries the paper-specific rubric. Output is an updated workbench.md — never the final blog post (that's paper-publish). For blogs use blog-review, for web articles use article-review.
---

# paper-review

학술 논문 1편을 섹션 단위로 같이 리뷰한다. 깊이 우선, 한 번에 한 섹션.

## 활성 조건

- cwd 가 `~/Projects/paper-review-service/<slug>/` 이고 `workbench.md` frontmatter
  `content_type: paper` (또는 content_type 없음 — 구버전 논문 폴더)
- 또는 그 폴더에서 `/next-section`, `/answer`, `/explain`, `/challenge`, `/finalize`,
  `/status` 사용
- content_type 이 `blog`/`article` 이면 [[blog-review]] / [[article-review]] 로 위임

## 진행 메커니즘

**공통 엔진**: `~/Projects/paper-review-service/src/paper_review/_paper_reader/references/review-engine.md`
명령어 흐름·dispatch 규칙·가드레일·viewer 재빌드는 전부 거기를 따른다.
아래는 **논문 전용 루브릭** — 엔진의 `/explain`·질문·`/finalize` 의 의미를 채운다.

## 논문 루브릭

`/explain` topic 의미:
- `tldr` — abstract + intro 기반 5-7 문장. 문제 / 기존 한계 / 제안 / 핵심 결과.
- `contributions` — intro 의 contribution bullet 추출/정리 → workbench 의 1/2/3.
- `prereqs` — 본문 한 번 훑어 외부 사전지식 5-12개 카드 (attention, FID 등).
- `key-terms` — 본문 내부 핵심 용어 5-12개.

`/next-section` 의 **Q (질문) 방향** — 논문을 비판적으로 읽게:
- 방법의 핵심 가정과 그게 깨지는 조건
- ablation 이 빠진 설계 선택
- 결과를 다른 해석으로 설명할 여지
- 재현성(데이터·하이퍼파라미터·코드)

`/finalize` 마무리 질문 3개:
1. 이 논문의 핵심 contribution 을 한 줄로?
2. 가장 약한 부분 / 의심스러운 부분은?
3. 후속으로 읽어야 할 논문 3개?

**스코프 구분 (모든 답변·노트에 적용)**:
- 논문이 명시적으로 주장/비교한 것과 일반 지식에서 오는 추론을 구분해 표기
  (예: "논문은 X만 비교했고, Y와의 비교는 논문 밖 일반론이다").
- 근거가 논문에 없으면 "논문에 명시되지 않음"이라고 말한다.
- 방법론 설명은 기호 정의·구체 수치(모델/데이터 규모, 하이퍼파라미터)까지;
  실험 설명은 "무엇을 보여주는 실험 → 결과 → 해석" 순으로.

## 참고

- 공통 엔진: `_paper_reader/references/review-engine.md`
- 번역 가이드(subagent inject): `_paper_reader/references/translation-guide.md`
- subagent prompt: `_paper_reader/references/subagent-prompt.md`
- 다음 단계: [[paper-publish]]
