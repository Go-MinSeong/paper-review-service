# paper-review — 개발 정리 (스터디 발표 / 테크 블로그용)

> 작성: 2026-06-02 · 대상: 스터디 발표 + 테크 블로그
> 저장소: `github.com/Go-MinSeong/paper-review-service` · 로컬 루트: `~/.paper-reviews/`
> 한 줄 정의: **arXiv/PDF 논문을 Claude와 ~2시간 섹션 단위로 같이 리뷰하고, 그 결과를 Velog 블로그 초안으로 뽑아내는 로컬 풀스택 도구.**

---

## 0. TL;DR (발표용 1분 요약)

- **문제**: 논문을 읽고 → 이해하고 → 블로그로 정리하는 과정이 매번 흩어진다. 번역·요약은 LLM이 잘하지만, "내가 이해한 것"과 "발행 가능한 글"로 만드는 마지막 1마일이 항상 수작업.
- **해결**: 논문 1편 = 1 워크스페이스. **Claude가 1차 번역+노트+질문**을 채우고, **내가 답하며 정리본을 완성**한 뒤, **kimjy99 구성 + 내 말투**로 Velog 초안을 자동 추출.
- **형태**: Python CLI + Claude Code 스킬 3개 + FastAPI 로컬 서버(갤러리/리뷰 UI) + macOS 메뉴바 앱. 단일 사용자, 로컬 우선(local-first).
- **현재**: 13편 분량의 워크플로우가 end-to-end로 돌아가고, 갤러리·대시보드·리뷰 UI가 실사용 수준으로 다듬어진 상태.

---

## 1. 왜 만들었나 (개발 배경)

논문 리뷰 블로그를 쓰는 사람의 실제 파이프라인은 대략 이렇다:

1. arXiv/PDF를 연다 → 2. 읽으면서 번역/요약한다 → 3. 헷갈리는 부분을 찾아본다 → 4. "내 언어로" 정리한다 → 5. figure를 추리고 캡션을 붙인다 → 6. 블로그 톤으로 다시 쓴다 → 7. 발행.

각 단계가 **다른 도구**(PDF 뷰어, 번역기, 메모앱, 블로그 에디터)에 흩어져 있고, 특히 **3·4번(이해→내 정리)** 이 LLM 자동화의 사각지대였다. 그냥 "요약해줘"를 누르면 글은 나오지만 *내가 이해한 글*은 아니다.

그래서 설계의 핵심 가정을 이렇게 잡았다:

> **LLM은 1차 번역·노트·질문 생성까지만. "정답이 되는 정리"는 사람이 답을 적으며 만든다.**

이 가정이 전체 데이터 모델(아래 §4)과 publish 톤 전략(§7)을 결정했다.

### 비목표 (의도적으로 안 한 것)

- **양방향 동기화 안 함** — 워크벤치는 단방향(Claude/사람 → 파일 → 브라우저). 병합 지옥 회피.
- **멀티유저 안 함** — 1인 로컬 서비스.
- **Velog API 직접 연동 안 함** — `drafts/`에 .md를 떨어뜨리는 데서 끝. 발행은 기존 `velog publish` 파이프라인이 처리.

---

## 2. 잠긴 설계 결정 (Locked decisions)

구현 전에 합의해 고정한 결정들. 발표에서 "왜 이렇게 짰나"의 근거.

| # | 결정 | 근거 |
|---|---|---|
| D1 | **스킬 3개**로 분리 (ingest / review / publish) | ingest=배치, review=스트리밍 대화, publish=변환 — cadence가 달라 한 스킬에 묶으면 분기 폭증 |
| D2 | paper-review는 **Velog vault 바깥의 별도 서비스** | 리뷰 중간 산출물이 블로그 vault에 섞이면 안 됨 |
| D3 | 서비스 루트 `~/.paper-reviews/<slug>/` — **1 paper = 1 프로젝트** | `cd`만 하면 Claude Code 세션이 폴더 기준으로 자동 그룹화 |
| D4 | **Python CLI + Claude 스킬 + FastAPI** 풀스택 | CLI는 thin orchestrator, 실제 로직은 스킬 안 |
| D5 | 기존 `paper-reader-v8` 엔진 **흡수**(rewrite 아님) | init/figure추출/번역 subagent는 검증된 자산 → 재사용 |
| D6 | `viewer.html` 부산물 동시 생성 | KO/EN 토글·키워드 hover가 리뷰 중 유용 |
| D7 | publish 톤 = **kimjy99 구성 + 내 말투** | 구성(섹션/figure/contribution 박스)은 레퍼런스, 운율은 내 글 샘플에서 학습 |
| D8 | 세션 = Claude Code의 **cwd 기반 프로젝트 그룹** 사용 | 2시간을 N번에 쪼개도 `--resume`로 이어감 |
| D9 | 브라우저 UI는 (초기엔) read-only | 단방향 동기화 유지 — *이 결정은 이후 완화됨(§6, WYSIWYG 편집 도입)* |

> 블로그 포인트: **"읽기 전용으로 시작했다가 인라인 편집을 추가하며 단방향 원칙을 어떻게 지켰나"** 는 좋은 회고 소재. (편집은 frontmatter를 보존하고 본문만 PUT, mtime 낙관적 동시성 체크로 충돌 방지)

---

## 3. 아키텍처 / 구성 요소

```
┌─────────────────────────────────────────────────────────────┐
│  macOS 메뉴바 앱 (rumps)  ── LaunchAgent로 상시 유지          │
│     └─ FastAPI 서버를 서브프로세스로 관리 (start/stop/restart) │
└───────────────┬─────────────────────────────────────────────┘
                │ http://localhost:7300  (+ LAN: 0.0.0.0)
        ┌───────▼────────┐        ┌──────────────────────────┐
        │  Gallery UI    │        │  Review (detail) UI       │
        │  - 카드/리스트  │        │  - PDF | 정리본 split     │
        │  - 대시보드/잔디 │        │  - 섹션 네비, 채팅        │
        │  - 태그/별점    │        │  - WYSIWYG 편집, 분석     │
        └───────┬────────┘        └───────────┬──────────────┘
                │                              │
        ┌───────▼──────────────────────────────▼──────────────┐
        │  Python 패키지  paper_review/                          │
        │   cli.py · server/(app,ingest,analyze,chat,tags,save) │
        │   publish/(parser,transform) · workbench.py · menubar │
        │   _paper_reader/  ← 흡수한 paper-reader-v8 엔진        │
        └───────┬──────────────────────────────────────────────┘
                │ spawn `claude -p` (headless)
        ┌───────▼────────────────────────────────────────────┐
        │  Claude Code 스킬 3개                                 │
        │   paper-ingest · paper-review · paper-publish         │
        └─────────────────────────────────────────────────────┘
```

### 3-1. 구성 요소별 역할

| 구성 요소 | 역할 |
|---|---|
| **CLI** (`paper-review`) | `init` / `serve` / `session` / `export-draft`. thin orchestrator |
| **paper-ingest** (스킬) | arXiv/PDF → `<slug>/` 생성: `source.txt`, `sections.txt`, `paper.json`, `*_figures.json`, `workbench.md` 스켈레톤. (번역 X — 그건 review에서) |
| **paper-review** (스킬) | 폴더 안에서 활성화. 섹션마다 (1) Claude 1차 번역+Reader's Notes, (2) 1~2개 질문, (3) 사용자 답변=메인 콘텐츠 를 누적 |
| **paper-publish** (스킬) | `export-draft`(구조 변환) + 프로즈 톤 매칭(2-pass) → `~/Documents/velog-vault/drafts/<slug>.md` |
| **FastAPI 서버** | 갤러리/리뷰 UI, SSE 라이브 리로드, `claude -p` 헤드리스 분석·채팅 오케스트레이션 |
| **메뉴바 앱** | 서버 라이프사이클 관리 + LaunchAgent로 상시 상주 |
| **`_paper_reader/`** | 흡수한 paper-reader-v8 (init/figure추출/번역 subagent) |

### 3-2. 기술 스택

- **백엔드**: Python, FastAPI, uvicorn, asyncio(서브프로세스), rumps(메뉴바)
- **프런트**: 바닐라 JS (빌드 스텝 없음), marked(마크다운), KaTeX(수식), Toast UI Editor(WYSIWYG)
- **LLM**: Claude Code 헤드리스 (`claude -p`, stream-json) — 분석/채팅/자동 태그
- **저장**: 파일시스템이 곧 DB. `workbench.md`가 단일 진실 소스(single source of truth)

---

## 4. 데이터 모델 — `workbench.md`가 전부다

핵심 설계: **별도 DB 없이 `workbench.md`(마크다운+frontmatter) 하나가 진실 소스.** 사람·Claude·서버·publish가 전부 이 파일을 읽고 쓴다.

```markdown
---
slug: 2605.22903
title_en: "Seeing without Looking: ..."
tags: [VLM, benchmark, ...]      # 등록 시 자동 생성 + 수동 편집
category: ""
rating: 4                         # 별점(있을 때만)
review_started: 2026-05-31
status: in_progress               # to_read → in_progress → review_done → exported
---
# ... 리뷰 워크벤치
## TL;DR
## 핵심 contribution
## 사전지식 카드
## 섹션별 리뷰
### 1. Introduction
<!-- section_id: sec-1 | lines: 1-20 -->
**원문 발췌** / **요약** / **Claude 1차 번역** / **Claude Reader's Notes** / **A (내 정리)**
## Q&A
## Wrap-up
```

- **frontmatter** = 메타데이터 (상태/태그/별점/카테고리). 갤러리·대시보드·publish가 여기서 정보를 읽음.
- **섹션 블록** = `### N. Title` + `<!-- section_id | lines -->` 주석 + 라벨 블록들. 라벨로 "누가 쓴 것"을 구분(§6 작성자 톤).
- **figure**: 본문엔 안 박고 `<slug>_figures.json`에 `{id, label, caption_en/ko, data_uri(base64), kind, ...}`로 보관. 본문/에디터는 `/paper/<slug>/fig/<id>` 짧은 경로로 참조(§기술 하이라이트).

> 블로그 포인트: **"파일시스템을 DB로 쓰기"** — 1인·로컬·버전관리(git) 친화. 마이그레이션 없음, grep으로 디버깅, 사용자가 직접 열어볼 수 있음. 트레이드오프(동시성/쿼리)는 낙관적 mtime 체크 + 클라이언트 집계로 커버.

---

## 5. 전체 워크플로우 (ingest → review → publish)

```
[arXiv/PDF] ──paper-ingest──▶ ~/.paper-reviews/<slug>/   (골격 생성)
                                   │
                                   ▼
       UI에서 "▶ Analyze"  ──▶  claude -p (헤드리스)로 섹션별
                                1차 번역+노트+질문을 workbench.md에 채움
                                   │
                                   ▼
       사람이 리뷰 페이지에서 답을 적고 정리(WYSIWYG/채팅)  ← 핵심 가치
                                   │
                                   ▼
       "↗ Publish" ──export-draft(구조변환)+톤매칭──▶ velog-vault/drafts/<slug>.md
                                   │
                                   ▼
                          기존 `velog publish`로 발행
```

- **등록 시 자동 분석**(deferred trigger) + **자동 태그 생성**(abstract → `claude -p --model haiku`로 3~6개).
- 분석은 백그라운드 job + 폴링 + 토스트 진행률, 취소·부분 실패 복구 지원.
- 5페이지 청크 단위, 모델 선택(Opus/Sonnet/Haiku), 섹션 단위 재실행 가능.

---

## 6. 주요 기능 (영역별)

### 갤러리 (리스트 페이지)
- **카드 / 리스트 뷰 토글** — 그리드는 보기 좋고, 리스트는 긴 제목 전체 표시 + 빈 공간 해소.
- **대시보드** (백엔드 추가 없이 클라이언트 집계): KPI 타일(논문 수/완료율/평균 별점), 리뷰 진행 퍼널, **주간 활동 잔디(GitHub식 히트맵, 1칸=1주)**, 별점 분포, 태그 Top. 닫기 버튼·2행 레이아웃.
- **태그**: 계층형(`CV/segmentation`), 사이드바 트리 + 카드 칩, **태그별 색상**(상위 세그먼트 해시 → 계열 공유 hue).
- **별점**(1~5), **reading list**(to_read), 검색, **최근 활동 시각**("편집/조회 N일 전"), 좌상단 SVG 로고.

### 리뷰 페이지 (detail)
- **3분할 레이아웃**: 섹션 네비 | 원본 PDF | 정리본(워크벤치). 가운데 **드래그 스플리터**로 좌우 비율 조절(+더블클릭 리셋, localStorage 저장).
- **패널 토글**: 원본 PDF / 정리본을 각각 열고 닫아 한쪽을 풀폭으로.
- **섹션 네비** 접기, **요약/상세 토글**, 채팅 패널(헤드리스 Claude), 섹션별 "✨ 분석" 버튼.
- **WYSIWYG 편집**(Toast UI): 글자 **색상 피커**, figure **삽입(캡션까지 함께)**, 저장 시 frontmatter 보존.
- **작성자 톤 구분**: "내 정리" 블록은 연한 accent 배경 틴트, Claude 생성 블록은 기본 캔버스.
- **PDF 내보내기**(인쇄 → "PDF로 저장"): 리뷰 본문만 분리한 인쇄 레이아웃(라이트 강제, figure/표 페이지 보존) — 오프라인/모바일 읽기용.

### Publish
- `export-draft`: `workbench.md` 파싱(parser.py) → kimjy99 구성으로 재배치(transform.py).
- **figure publish 브리지**: 에디터로 넣은 `/paper/.../fig/<id>`를 vault attachments의 실제 파일로 디코드/복사 + URL 치환 → `velog publish`가 업로드 가능.
- 글자 색상 `<span style="color">` 은 Velog가 지원 → 그대로 통과.

### 인프라 / 운영
- **메뉴바 앱 + LaunchAgent** 상시 상주, **Stop hook 자동 커밋**.
- **LAN 접속**: 메뉴바가 `serve --host 0.0.0.0`로 띄움 → 같은 Wi-Fi 폰에서 `http://<lan-ip>:7300`. 메뉴에 LAN 주소 표시.
- **저작권 처리**: IP 기반 캐릭터 일러스트는 gitignore + 히스토리 제거(`git filter-repo`)로 로컬 전용.

---

## 7. publish 톤 전략 (kimjy99 구성 + 내 말투)

publish는 **2-pass**:
1. **Pass 1 (결정적/CLI)** — `transform.py`가 workbench를 구조적으로 재배치. 섹션 순서, contribution 박스, figure 위치 = kimjy99 레퍼런스 구성. 프로즈는 아직 "Claude 1차 번역 직역체".
2. **Pass 2 (Claude, 내 운율)** — `voice_samples/`(내가 쓴 글에서 추린 샘플)을 참고해 본문 영역만 "~합니다" 어미·짧은 문장으로 다듬음. frontmatter·논문정보 박스·figure 캡션은 안 건드림.

> 블로그 포인트: **"구성(레퍼런스에서)과 운율(내 글에서)을 분리 학습"** — 톤 일관성을 위해 voice sample을 외부화하고, 변환을 결정적 파트와 LLM 파트로 쪼갠 설계.

---

## 8. 기술 하이라이트 (블로그에 풀어쓰기 좋은 것들)

### (a) `workbench.md` 단일 진실 소스 + SSE 라이브 리로드
파일 mtime 변화를 SSE로 브라우저에 푸시 → Claude가 파일을 갱신하면 리뷰 페이지가 자동 리로드. DB 없이 "파일 = 상태".

### (b) figure를 base64 인라인 대신 by-id 라우트로 서빙
`figures.json`엔 이미지가 base64로 들어있다(개당 ~120KB). 워크벤치 본문에 인라인하면 파일이 수 MB로 폭증 → 대신 `GET /paper/<slug>/fig/<id>`가 data_uri를 디코드해 바이트로 응답. 본문/에디터는 짧은 경로만 참조.

### (c) figure publish 브리지
에디터 삽입 figure는 라이브 서버 경로라 Velog에서 404. → export 시 `figures.json` base64를 `<vault>/attachments/<slug>__<id>.<ext>` 실제 파일로 떨구고 URL을 vault 상대경로로 치환 → 발행 파이프라인의 이미지 업로더가 인식. (figure 없으면 no-op, 실패해도 export 안 죽음)

### (d) 등록 시 LLM 자동 태그
ingest 성공 후 태그가 없으면 title+abstract를 `claude -p --model haiku`로 보내 3~6개 토픽 태그 생성 → frontmatter 기록. 수동 태그 있으면 skip, 실패해도 ingest 무중단.

### (e) CSS Grid 함정 두 가지 (실전 디버깅)
- **`display:none`는 grid 자동배치를 reflow시킨다** — 섹션레일을 `display:none`으로 접었더니 PDF/워크벤치 패널이 한 트랙씩 밀려 우측이 비었다. → display:none 대신 **0폭 트랙 + overflow:hidden**으로 "트랙에 남겨둔 채 접기". 같은 패턴을 패널 토글에도 재사용.
- **`grid-template-columns` 트랜지션 + `var()`/`max()` 조합이 프리즈된다** — 드래그 스플리터가 멈췄다. Chromium이 var() 기반 트랙 리스트를 보간하다 값이 굳음. → 트랜지션 제거(nav 토글은 슬라이드 대신 즉시 전환으로 trade-off).

### (f) asyncio 서브프로세스 64KB 라인 제한
"Separator is not found, and chunk exceed the limit" 에러. `claude -p` 출력의 한 줄이 기본 StreamReader 한계(64KB)를 넘어 stream read가 죽었다(Edit 자체는 성공). → 모든 `create_subprocess_exec`에 `limit=16MB`.

### (g) WYSIWYG 마크다운 정규화에 강한 섹션 파싱
Toast UI가 저장 시 `_`→`*`, `7.`→`7\.` 식으로 정규화 → 섹션 상태 판별 정규식이 깨졌다. → 구분자 다중 매칭(`[*_]?`), 명시적 H2 경계로 섹션 추출을 견고화.

### (h) 저작권 자산을 히스토리에서 제거
특정 IP 기반 캐릭터 8종을 gitignore로 추적 해제 + **`git filter-repo`로 전체 과거 커밋에서 purge** 후 force-push → 공개 레포엔 오리지널 동물 6종만. 로컬엔 14종 유지(메뉴바 갤러리는 그대로).

> 위 (e)~(h)는 각각 "작은 버그가 알려주는 큰 교훈" 형식의 독립 블로그 글감으로도 좋음.

---

## 9. 개발 타임라인 (커밋 기준 요약)

1. **부트스트랩** — 패키지 골격, paper-reader-v8 흡수, CLI(init/list/rm), 스킬 3종, publish transform, voice samples.
2. **풀스택 UI** — FastAPI 서버, 섹션 네비, diff 하이라이트, figure 모달, 채팅(SSE), 모델 선택, UI 등록/편집, publish 모달, 자동분석.
3. **다듬기** — 갤러리 리디자인, 사이드바, 다크/라이트, Linear+Apple 디자인 시스템, 메뉴바 앱, reading list, 태그 백엔드.
4. **리뷰 UX 심화** — WYSIWYG 에디터, 섹션별 분석 버튼, 캐릭터 일러스트, figure 삽입, 작성자 톤 구분, 글자 색상.
5. **이번 라운드** — figure publish 브리지, PDF 내보내기, 드래그 스플리터, 별점, 대시보드+잔디, 자동 태그, 커스텀 다이얼로그, 리스트/그리드 뷰, 저작권 정리, LAN 접속, 패널 토글, 태그 색상.

(전체 커밋 로그는 저장소 `git log` 참조.)

---

## 10. 향후 계획 / 미해결

- **오프라인 모바일 읽기** — 현재는 PDF 내보내기(수동). 다음 후보: 자기완결 HTML/PDF를 동기화 폴더(iCloud/Obsidian)에 자동 저장.
- **모바일 실시간 접속** — LAN 바인딩 완료. 공유기 기기격리 환경에선 **Tailscale** 등 터널이 확실(미적용).
- **워크벤치 버전/백업** — 현재 저장은 덮어쓰기(낙관적 mtime 체크만). 저장/analyze 직전 스냅샷 + UI 되돌리기 후보.
- **채팅 트랜스크립트 영속화** — 새로고침 시 패널 비워짐(세션은 `--continue`로 유지됨).
- **LAN 토큰 인증** — 공용 Wi-Fi 대비.
- **`pretext` 실험** — 긴 워크벤치 텍스트 가상화/정밀 타이포(재미/학습용 후보).

---

## 11. 발표용 메시지 3줄

1. **"읽기→이해→정리→발행"의 마지막 1마일을 한 워크스페이스로 묶었다** — LLM은 1차까지, 정리는 사람이.
2. **파일 하나(`workbench.md`)를 진실 소스로** 두니 DB·동기화·마이그레이션이 사라지고 git/grep으로 디버깅된다.
3. **작은 버그들이 좋은 글감** — CSS grid reflow, asyncio 64KB, grid transition freeze, 저작권 히스토리 정리까지 전부 재현·검증·기록했다.
