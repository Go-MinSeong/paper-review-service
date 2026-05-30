# paper-review service — Design (v0)

> 작성: 2026-05-26 / Owner: 고민성 (Go-MinSeong)
> Status: **잠긴 설계** — 구현 시작 전 합의 완료
> 관련: [Velog ↔ Obsidian pipeline](../Documents/velog-vault) (별도 서비스)

## 0. 한 줄 요약

PDF/arXiv 논문을 받아 **첨부 `paper-reader-v8` 엔진**으로 골격을 만들고, 본인과 Claude가 **~2시간 인터랙티브로 섹션 단위 같이 리뷰**한 뒤, 그 결과를 **kimjy99 톤 + 본인 말투**로 Velog 드래프트(.md)로 추출하는 로컬 서비스.

## 1. 목표 / 비목표

**Goal (v0)**
- 논문 1편당 ~2시간 짜리 "함께 리뷰" 워크플로우를 끝까지 돌릴 수 있게 한다.
- 산출물 두 가지: (a) 리뷰용 워크벤치 (`workbench.md` + viewer.html), (b) Velog 드래프트 `.md`.
- 기존 [Velog ↔ Obsidian pipeline](https://) (push-only, manual CLI)과 **publish 단계에서만** 연동한다.

**Non-goal**
- 양방향 동기화. 워크벤치는 단방향 (Claude → 파일 → 브라우저 표시).
- 브라우저 UI에서의 텍스트 편집. 편집은 Claude Code 대화로만.
- 멀티 사용자. 1인 로컬 서비스.
- Velog API 직접 연동. drafts/ 에 떨어뜨리는 데서 끝. 발행은 기존 `velog publish` 가 처리.

## 2. 잠긴 결정 사항

| # | 결정 | 근거 |
|---|---|---|
| D1 | 스킬 3개 (ingest / review / publish) | ingest=batch, review=streaming, publish=transform — cadence가 달라 1개 스킬에 묶으면 SKILL.md 분기 폭증 |
| D2 | paper review는 **Velog vault 바깥의 별도 서비스** | drafts/ 는 논문 외 다른 종류 글도 받음. 리뷰 중간 산출물이 섞이면 안 됨 |
| D3 | 서비스 루트: `~/.paper-reviews/<slug>/` | 1 paper = 1 Claude Code 프로젝트. `cd` 만 하면 `~/.claude/projects/...` 에 세션이 자동 그룹화 |
| D4 | Python CLI + Claude 스킬 + FastAPI 서버 풀스택 (v0) | `velog publish` 패턴 미러링. CLI는 thin orchestrator, 실제 로직은 스킬 안 |
| D5 | 첨부 `paper-reader-v8` 흡수 (rewrite 아님) | init/fetch_figures/add_section/build_html/paper-translator subagent는 검증된 자산. `paper-ingest` 가 이걸 호출 |
| D6 | viewer.html은 부산물로 같이 생성 | KO/EN 토글, 키워드 hover는 리뷰 중 유용. read 전용 |
| D7 | publish 톤: **kimjy99 구성 + 본인 말투** | 구성=섹션 구조/figure 위치/contribution 박스 (kimjy99), 운율=짧은 문장/"~합니다" 어미 (papers/*/notion.md 샘플링) |
| D8 | 세션 관리: Claude Code의 cwd 기반 프로젝트 그룹 사용 | 별도 세션 매니저 빌드 안 함. `claude --resume` 으로 2시간을 N번에 쪼개도 OK |
| D9 | 브라우저 UI = read-only | 단방향 동기화 유지. 편집 UI를 넣으면 충돌/병합 지옥 |

## 3. 디렉토리 구조

```
~/.paper-reviews/                       # 서비스 루트
├── DESIGN.md                           # ← 이 문서
├── pyproject.toml                      # paper-review CLI 패키지
├── src/paper_review/
│   ├── cli.py                          # init/serve/session/export-draft 진입점
│   ├── slugger.py                      # arxiv_id → <slug> 매핑
│   ├── server/                         # FastAPI 로컬 서버
│   │   ├── app.py
│   │   ├── routes.py                   # /paper/<slug>, /paper/<slug>/workbench.md, /paper/<slug>/figures/*
│   │   ├── watcher.py                  # workbench.md mtime → SSE
│   │   └── static/                     # PDF.js, viewer CSS, hot-reload JS
│   └── publish/
│       ├── transform.py                # workbench.md → draft.md
│       ├── voice_samples/              # papers/*/notion.md 에서 추린 운율 샘플
│       └── kimjy_template.md           # 구성 템플릿 (frontmatter + 섹션 순서)
└── <slug>/                             # paper 1편
    ├── source.txt                      # paper-reader-v8 init 산출 (본문 plain text)
    ├── sections.txt                    # 섹션 인덱스
    ├── paper.json                      # paper-reader-v8 단일 truth
    ├── workbench.md                    # ★ 리뷰 본체 — Claude 가 누적 업데이트
    ├── figures/                        # fetch_figures.py 산출
    ├── viewer.html                     # build_html.py 산출 (부산물)
    ├── original.pdf                    # 업로드 원본 사본
    └── .claude/                        # Claude Code 프로젝트 디렉토리

~/.claude/skills/
├── paper-ingest/                       # paper-reader-v8 흡수 + 슬림화
├── paper-review/                       # 신규
└── paper-publish/                      # 신규

~/Documents/velog-vault/drafts/<slug>.md  ← publish 출구. 이후 velog publish가 처리
```

## 4. workbench.md 구조

리뷰 중 살아 움직이는 본체. 섹션 단위로 누적 채워짐.

```markdown
---
slug: 2010.11929_vit
title_en: "An Image is Worth 16x16 Words"
title_ko: "ViT"
paper_url: https://arxiv.org/abs/2010.11929
review_started: 2026-05-26
status: in_progress       # in_progress | review_done | exported
---

# ViT — 리뷰 워크벤치

## TL;DR  (Claude 1차 작성)
...

## 핵심 contribution
1. ...
2. ...
3. ...

## 사전지식 카드
- attention(Vaswani 2017): ...
- ...

## 섹션별 리뷰

### Abstract
**원문 발췌**
> ...
**Claude 1차 번역**
...
**Claude Reader's Notes**
...
**Q (Claude)**: 이 paper가 ResNet 보다 데이터 적을 때 약한 이유를 직관으로 설명한다면?
**A (내 정리)**:   ← 여기를 본인이 답하면 Claude 가 받아 정리해서 채움

### Introduction
...

## Wrap-up
- 한 줄 contribution:
- 가장 약한 부분:
- 후속 읽을거리:

## 메타
- 총 소요 시간:
- 마지막 세션:
```

## 5. 세 스킬의 계약

### Skill 1: `paper-ingest`

**Trigger**: 사용자가 `paper-review init <pdf|arxiv>` 호출 or 슬래시 `/paper-review init ...`

**Input**: arXiv ID/URL or local PDF path

**Steps**
1. slug 결정 (`arxiv_id` 우선, fallback: pdf basename)
2. `~/.paper-reviews/<slug>/` 생성
3. paper-reader-v8 init_paper.py 호출 → `source.txt`, `sections.txt`, `paper.json`
4. fetch_figures.py 호출 → `figures/` + `figures.json`
5. metadata + prereqs + key_terms + figures batch merge
6. workbench.md 초기 골격 생성 (TL;DR + contribution 3개 + 사전지식 카드 + 섹션 stub만 채움)
7. build_html.py 호출 → `viewer.html`

**Output**: 위 디렉토리 + Claude 응답 1-3 문장 ("어떤 paper, contribution 요약, 어디부터 들어갈지 제안")

**Out of scope**: 섹션 본문 번역 (그건 review 스킬이 들어갈 때 lazy 생성). paper-reader-v8 는 미리 다 번역하지만, 우리는 review와 결합하기 위해 의도적으로 deferred.

### Skill 2: `paper-review`

**Trigger**: 사용자가 `<slug>` cwd 안에서 Claude Code 켜고 대화 시작 — workbench.md 가 존재하면 자동 활성

**Modes**
- `/next-section [N]` — 다음 섹션 들어가기. Claude가 ①원문 발췌 ②1차 번역 ③Reader's Notes ④질문 1-2개 출력하고 본인 답변 대기
- `/answer ...` (또는 그냥 자유 답변) — 본인 답변을 받아 workbench.md 의 해당 섹션 "A (내 정리)" 블록에 정리해 박음
- `/explain <term>` — 사전지식 카드 확장
- `/challenge <claim>` — paper의 특정 주장에 대해 반박/대안 토론
- `/finalize` — wrap-up 단계 (한 줄 contribution, 가장 약한 부분, 후속 읽을거리)
- `/status` — 진행률 (섹션 N/M)

**Invariants**
- workbench.md 외 파일은 건드리지 않음
- Claude의 1차 번역은 *초안*, 본인 답변이 *본문*. publish 때 본인 답변이 우선.
- 한 섹션 끝나기 전에 다음 섹션으로 안 넘어감. 본인이 명시적으로 `/next-section` 해야 진행.

**Output**: workbench.md 누적 갱신. status: `review_done` 으로 마무리.

### Skill 3: `paper-publish`

**Trigger**: 사용자가 `paper-review export-draft <slug>` 호출 or `/paper-publish` (cwd 가 그 slug 안일 때)

**Input**: `~/.paper-reviews/<slug>/workbench.md` (+ paper.json + figures/)

**Steps**
1. workbench.md 파싱 — TL;DR, contribution, 섹션별 (원문 / Claude번역 / 본인답변 / Reader's Notes), wrap-up
2. kimjy99 템플릿에 매핑:
   - 섹션 순서: Introduction → Method → Experiments → Conclusion (paper 구조 따라감)
   - 각 섹션 본문 = 본인답변 위주, Claude 번역은 보조 인용/요약, Reader's Notes 는 callout
   - 수식은 inline `$..$` / block `$$..$$`
   - figure는 `figures/` 의 경로 그대로 (velog publish가 업로드+URL 치환 처리)
3. 운율 변환 — voice_samples/ 의 papers/*/notion.md 패턴을 system prompt 로 사용해 본인 어미/문장 길이로 다듬기
4. frontmatter 부착 (Velog ↔ Obsidian 파이프라인 규칙):
   - `tags: [paper-review, <category>]`
   - `draft: true` (안전 게이트)
   - `is_private: false`
   - `paper_title`, `paper_url`, `category`, `original_review_date`
5. `~/Documents/velog-vault/drafts/<slug>.md` 작성
6. workbench.md status → `exported`

**Output**: drafts/<slug>.md. Claude 응답 1-2문장.

## 6. CLI

```bash
paper-review init <pdf|arxiv-id>       # Skill 1 호출. 1번에 끝.
paper-review serve [--port 7300]       # FastAPI 로컬 서버 시작. 모든 paper gallery + 개별 paper detail
paper-review session <slug>            # cd ~/.paper-reviews/<slug> && claude
paper-review export-draft <slug>       # Skill 3 호출. drafts/ 에 떨어뜨림
paper-review list                      # 진행 중인 paper 목록 + status
paper-review rm <slug>                 # 폐기 (확인 프롬프트)
```

CLI는 thin orchestrator. 실제 로직 — paper-reader-v8 호출, workbench 생성, publish 변환 — 은 스킬 안 또는 별도 모듈.

## 7. FastAPI 서버 (`paper-review serve`)

**라우트**
- `GET /` — gallery (모든 paper 카드)
- `GET /paper/<slug>` — detail. 좌측 PDF.js, 우측 workbench live render
- `GET /paper/<slug>/workbench.md` — raw markdown (브라우저 측 marked.js 렌더)
- `GET /paper/<slug>/figures/<file>` — figure 정적 서빙
- `GET /paper/<slug>/viewer.html` — paper-reader-v8 뷰어 새 탭으로
- `GET /paper/<slug>/events` — SSE. workbench.md mtime 변경시 reload 이벤트

**프론트엔드**
- 정적 HTML + 작은 JS (프레임워크 X)
- PDF.js — npm 안 거치고 CDN URL 또는 vendored bundle
- marked.js + KaTeX — workbench.md 렌더
- SSE 수신시 워크벤치 pane 만 갱신 (PDF는 유지)

**보안/스코프**
- localhost only (`127.0.0.1` bind). 인증 없음.
- v0은 read-only — POST 라우트 없음.

## 8. 2시간 워크플로우 (구체)

```
T+0:00  paper-review init ~/Downloads/foo.pdf
        → 5분 batch. ingest 완료.
T+0:05  paper-review serve &  # 브라우저 자동 오픈
T+0:05  paper-review session 2410.24164_foo
        → claude 시작. workbench.md 보고 자동 인사 + 첫 섹션 제안.
T+0:15  /next-section abstract
        → Claude 출력. 본인 답변 (3-5분).
T+1:30  (4-7개 섹션 진행)
T+1:45  /finalize
        → wrap-up 질문 3개. 답변.
T+2:00  Ctrl-D (세션 종료). 워크벤치 status: review_done.
        [별일자도 OK] paper-review export-draft 2410.24164_foo
        → drafts/2410.24164_foo.md 생성.
        → velog publish drafts/2410.24164_foo.md
```

쪼개기: T+1:00 에 점심 먹으러 가도 `claude --resume` 으로 같은 cwd 에서 재개.

## 9. paper-reader-v8 흡수 전략

원본은 `/tmp/paper-reader-v8/paper-reader/` (사용자 ~/Downloads/paper-reader-v8 (1).skill 압축).

**그대로 재사용**
- `scripts/init_paper.py`
- `scripts/fetch_arxiv.py`
- `scripts/fetch_figures.py`
- `scripts/fetch_github.py`
- `scripts/add_section.py`
- `scripts/validate_paper.py`
- `scripts/build_html.py`
- `assets/viewer-template.html`
- `assets/agents/paper-translator.md` (Claude Code named subagent)
- `assets/agents/github-investigator.md`
- `references/translation-guide.md`
- `references/data-schema.md`

**수정**
- 출력 경로 하드코딩 (`/mnt/user-data/outputs/`, `/tmp/papers/`) → `~/.paper-reviews/<slug>/` 기반으로 환경 변수 또는 인자
- `paper-reader` 스킬의 "한 번에 다 번역" 워크플로우 → ingest 는 골격만, 번역은 review 가 섹션별 lazy 호출

**제거/대체**
- present_files 호출 (Claude.ai 전용) → 그냥 콘솔에 파일 경로 print
- `--skip-validate` 옵션은 유지

## 10. publish 톤 학습 — 구체

**Voice samples 수집**
- `~/Documents/velog-vault/papers/*/notion.md` 중 본인이 직접 쓴 부분만 발췌 (autogenerated header 제외)
- 5-7개를 `~/.paper-reviews/src/paper_review/publish/voice_samples/` 에 정적 저장

**Style template (kimjy99 모사)**
- 섹션 순서: 제목 → 메타 (paper 정보 박스) → Abstract → Introduction → Related Work → Method → Experiments → Discussion/Conclusion
- 각 섹션 헤더는 H2 (`##`)
- Method 안 subsection 은 H3
- Contribution은 Introduction 끝의 bullet list
- Figure 는 본문 안 inline 삽입 + `> Figure N: ...` 형식 caption
- 수식은 별 줄 block
- Reader's Notes 는 `> 💡 ...` callout

**System prompt 패턴**
```
You are reshaping a paper review draft into a Velog blog post.
Voice samples (run-on, short sentences, "~합니다" endings):
<voice_samples...>
Structure template (kimjy99 style):
<kimjy_template.md...>
Preserve the user's answers (under "A (내 정리)") as the primary content.
Use Claude's draft translation only as supplementary detail.
```

## 11. v0 범위 / v1 이연

**v0 (이번 작업)**
- 스킬 3개
- CLI 6개 명령
- FastAPI 서버 (gallery + detail + SSE)
- viewer.html은 paper-reader-v8 그대로 활용
- voice samples 수집 + publish 톤 변환

**v1 이연**
- 멀티 paper 동시 진행시 서버 라우팅 개선
- workbench.md → Notion DB 자동 백업 (이미 papers/<>/ 에 notion-attachments 가 있는 걸로 보아 본인이 Notion도 씀)
- session timer (지금 1.5시간 지났습니다 알림)
- 자동 figure→text alt 생성
- Obsidian 플러그인 (vault 외부 paper-review 폴더를 vault 안에서 보이게)

## 12. 알려진 리스크

1. **PDF.js 부피** — vendored bundle 약 3MB. CDN으로 회피 가능하지만 오프라인 못 씀. → vendored + lazy load
2. **paper-reader-v8 서브에이전트 의존** — `paper-translator` named agent가 `~/.claude/agents/` 에 install 안 되어 있으면 fallback (general-purpose) 사용. install.sh를 paper-review init 시 자동 호출.
3. **운율 변환 품질** — voice samples 가 거친 직역체라 그대로 흉내내면 퀄리티 하락. system prompt 에서 "운율만 모사, 깊이/구조는 kimjy99 따라" 명시 필요.
4. **session resume 시 컨텍스트 비대** — 2시간 세션을 4번 resume 하면 토큰 비대. paper-review 스킬에 `/summarize-progress` 추가해서 long-running 시 압축.
5. **workbench.md 충돌** — 사용자가 Obsidian/VSCode 에서 동시에 편집하면 Claude의 다음 write가 덮어씀. v0 가이드: "리뷰 중에는 외부 편집 금지". v1에서 file lock.

## 13. Resolved (2026-05-26)

- [x] **CLI 패키지 이름**: `paper-review` 확정 (`velog-publish` 와 페어링)
- [x] **FastAPI 기본 포트**: `7300` 확정
- [x] **paper-reader-v8 흡수 방식**: `src/paper_review/_paper_reader/` 로 vendor (scripts/, assets/, references/). subagent 정의(`paper-translator.md`, `github-investigator.md`)는 `paper-review init` 시 `~/.claude/agents/` 로 install (멱등). 이렇게 하면 CLI와 스킬 양쪽에서 같은 경로로 호출 가능.
- [x] **viewer.html lazy translation**: PAPER_DATA가 빌드 타임 placeholder 치환 (build_html.py:132). 하지만 build_html은 단순 string replace라 가볍다 — 섹션 1개 커밋될 때마다 `add_section.py` → `build_html.py` 재호출이 정답. 브라우저는 file-watch SSE로 viewer.html mtime 변경 감지하면 자동 reload.

## 14. 참조

- 첨부 스킬: `~/Downloads/paper-reader-v8 (1).skill` (`/tmp/paper-reader-v8/paper-reader/`)
- 기존 paper 리뷰: `~/Documents/velog-vault/papers/{Transformer,DDPM,Vision-Transformer,...}/`
- Velog 파이프라인: 메모리 [project_velog_obsidian_pipeline](../.claude/projects/-Users-msgo-Downloads-LLM-as-Judge/memory/project_velog_obsidian_pipeline.md)
- 톤 reference: https://kimjy99.github.io/categories/논문리뷰/
