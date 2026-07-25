# review-engine — 콘텐츠 리뷰 공통 메커니즘

> paper-review / blog-review / article-review 세 스킬이 공유하는 엔진.
> 각 스킬 SKILL.md 는 **타입별 루브릭**만 담고, 진행 메커니즘은 이 문서를 따른다.
> (paper-review SKILL.md 의 원래 메커니즘을 타입 중립으로 추출한 것)

## 단일 진실

`workbench.md` 가 유일한 truth. 그 외 파일(`*_paper.json`, `*_source.txt`,
`*_sections.txt`, `*_figures.json`)은 데이터 모델 — Claude 가 직접 손대지 않는다.
`paper.json` 변경은 `_paper_reader/scripts/add_section.py` 를 통해서만.

매 응답이 끝나면 viewer 가 자동 갱신되도록 build_html 도 같이 재호출.

## 활성 후 첫 응답

cwd 가 콘텐츠 폴더이고 `workbench.md` 가 있으면, frontmatter 의 `content_type`
을 먼저 읽는다. 자기 타입이 아니면 매칭 스킬로 위임(예: blog 인데 paper-review
가 떴으면 "이건 blog 라 blog-review 로 진행하겠습니다"). 첫 응답은 한 줄로
어디까지 진행됐는지 + 다음 행동 제안 1개. 자기소개 X.

## 명령어 (공통)

### `/next-section [N]`

다음 미완료 섹션 1개 진행. (N 지정 시 N번째 stub 으로 점프.)

흐름:
1. workbench.md 의 다음 `_(미진행 — ...)_` 섹션 찾고 그 section_id, lines 추출
2. `<slug>_source.txt` 에서 해당 line range 읽음
3. **paper-translator 서브에이전트 1개 dispatch** (직렬, 절대 병렬 X).
   prompt 템플릿은 `_paper_reader/references/subagent-prompt.md`.
   (번역 엔진은 EN→KO 이므로 blog/article 에도 그대로 유효. 본문이 이미
   한국어면 번역은 생략하고 요약·Notes 만 채우게 지시.)
4. 서브에이전트가 paragraphs[], summary_ko, readers_notes_md 채운 section JSON 반환
5. workbench.md 의 해당 ### 섹션 블록을 아래 형식으로 교체:

```markdown
### {heading}

<!-- section_id: {id} | lines: {range} -->

**원문 발췌** (lines {range})
> {1-2 representative sentences, from paragraphs[0]}

**핵심 해설**
{한 덩어리 한국어 해설 — 요약과 번역을 분리하지 않는다. 원문 순서를 따르되
압축해 쓰고, 핵심 문장은 굵게. 수치·기호·비교는 빠뜨리지 않는다.}

**Claude Reader's Notes**
{readers_notes_md if non-empty}

**Q (Claude)**: {타입별 루브릭에 맞춘 질문 1-2개}

**A (내 정리)**:
_(여기에 본인 답변. 자유롭게 답하면 Claude 가 받아 정리해서 채움)_
```

6. `add_section.py` 로 paper.json 에도 섹션 commit (viewer 갱신용)
7. `build_html.py` 재호출
8. Claude 응답: 1줄 — "섹션 X 완료. 답변 기다림 / 다음은 `/next-section`."

### `/answer ...` 또는 자유 답변

활성 섹션(가장 최근 `/next-section`)의 `A (내 정리)` 블록을 사용자 답변 기반으로 채움.

- 발화를 그대로 박지 말고 **3-5 문장으로 정리해서** 박음.
- hedge("잘 모르겠다")는 보존 — 모른다는 것도 정보.
- 답변에서 새 질문이 파생되면 Q 블록에 1개 추가하고 또 기다림(소크라테스 모드).

`/answer` 키워드 없이 답해도 동일 — 직전이 `/next-section` 출력이면 자동 answer 모드.

### `/explain <topic>`

특정 placeholder 를 Claude 가 채움. topic 의 **의미는 타입별 루브릭이 정의**한다:
- `tldr` — 글 도입부 기반 5-7 문장 요약
- `contributions` / `key-points` — 타입별 핵심 항목 추출 → workbench 의 1/2/3
- `prereqs` — 외부 사전지식 5-12개 카드
- `key-terms` — 글 내부 핵심 용어 5-12개
- `<섹션 헤딩>` — 그 섹션을 `/next-section` 과 같은 효과로 진행

### `/challenge <claim 또는 섹션>`

해당 주장/섹션의 **반박/대안/약점** 탐색. 본문은 건드리지 않고 "내 정리" 블록 끝에 callout:

```markdown
> 🔍 **반론 토론**:
> - Claude 가 제기하는 약점/대안 1-3개
> - 사용자 응답
```

### `/finalize`

Wrap-up 단계. workbench 의 `# Wrap-up` 섹션을 채움:
1. 모든 섹션이 done 인지 확인. 미완료 있으면 list 뽑아 확인 후 진행.
2. **타입별 루브릭의 마무리 질문 3개**를 한 번에 출력.
3. 답변 받아 정리해 박음.
4. `status` 를 `review_done` 으로 변경.

### `/status`

```
slug: <slug>   type: <content_type>
sections: N/M done
last_session: <timestamp>
status: in_progress | review_done | exported
```

## 가드레일 (공통)

- **paper-translator dispatch 는 단일 turn 에 1개만.** 병렬 X (톤/용어 일관성).
- **사용자 답변을 그대로 옮겨붙이지 말 것.** 정리하되 의미 보존.
- **viewer.html 을 매 commit 마다 rebuild.** SSE 가 브라우저 자동 새로고침 트리거.
- **workbench.md 외 파일 직접 편집 금지** (예외: paper.json 은 `add_section.py` 통해서만).
- **sections 추가/삭제 금지.** sections.txt 가 source of truth. 잘못 추출됐어도
  review 중엔 그대로 진행, publish 단계에서 사용자가 직접 조정.

## 컨텍스트 관리

긴 세션이 토큰을 비대하게 만들면 `/summarize-progress` 제안: 완료된 섹션을 1줄씩
요약하고 그 외엔 워크벤치 reread 안 함. 며칠 후 `claude --resume` 복귀 시 첫
응답은 `/status` + 다음 행동 1개.

## 보조 도구

```bash
# 섹션 진행 후 viewer 재빌드
~/Projects/paper-review-service/.venv/bin/python \
    ~/Projects/paper-review-service/src/paper_review/_paper_reader/scripts/build_html.py \
    --data <slug>_paper.json \
    --template ~/Projects/paper-review-service/src/paper_review/_paper_reader/assets/viewer-template.html \
    --out viewer.html \
    --skip-validate
```

(또는 `~/Projects/paper-review-service/.venv/bin/python -m paper_review._paper_reader.runner` helper.)
