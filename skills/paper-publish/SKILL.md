---
name: paper-publish
description: Two-pass transform of a paper-review workbench.md into a Velog blog draft. Pass 1 runs `paper-review export-draft <slug>` (CLI, deterministic structural reshape into kimjy99 layout). Pass 2 polishes the prose to match the user's voice using voice samples from voice_samples/. Use when the user says "/paper-publish", "블로그 글로 변환", "publish draft", "export to velog", or runs `paper-review export-draft`. Output goes to ~/Documents/velog-vault/drafts/<slug>.md. After this, the Velog publish CLI (separate tool) handles the actual posting.
---

# paper-publish

워크벤치 → Velog 드래프트. 두 단계로 분리.

## 활성 조건

- 사용자가 `/paper-publish`, "출판", "블로그 글로 변환", "publish draft", "drafts 에 떨어뜨려" 같은 발화
- 또는 cwd 가 `~/Projects/paper-review-service/<slug>/` 이고 status 가 `review_done` 일 때 자동 제안

## 사전 조건

- `~/Projects/paper-review-service/<slug>/workbench.md` 가 존재
- 워크벤치 status 가 `review_done` 이 이상적 (아니면 진행 중 섹션만 출판 — 사용자 동의 받고 진행)
- `~/Documents/velog-vault/drafts/` 디렉토리 존재 (없으면 자동 생성)

## 워크플로우

### Pass 1 — 구조 변환 (CLI, 결정적)

```bash
paper-review export-draft <slug>
```

이게 하는 일:
1. workbench.md 파싱 (`publish/parser.py`)
2. kimjy99 구성으로 재배치:
   - frontmatter 부착 (tags, draft: true, paper_title, paper_url, category, original_review_date)
   - 제목 → TL;DR → 논문 정보 → 핵심 contribution → 섹션별 (사용자 답변 메인, Claude 번역은 `<details>` 안으로 강등, Reader's Notes 는 `> 💡 ` callout) → 정리
3. `~/Documents/velog-vault/drafts/<slug>.md` 작성
   - **figure 브리지**: 본문의 `![](/paper/<slug>/fig/<id>)` (에디터 삽입) 와 `figures/<file>` 참조를 `<vault>/attachments/<slug>__<id>.<ext>` 실제 파일로 디코드/복사하고 URL 을 vault 상대경로로 치환. 그래야 `velog publish` 의 `find_local_images` 가 잡아 업로드함. (그림 없으면 no-op)
   - 글자 색상 `<span style="color:…">` 은 그대로 통과 — Velog 가 인라인 HTML span 색상을 지원함.

Pass 1 결과물은 구조는 맞지만 **프로즈가 Claude 1차 번역 운율** (직역체) 이 섞여 있음. Pass 2 로 다듬는다.

### Pass 2 — 톤 매칭 (Claude, 본인 운율)

Pass 1 끝나면 사용자에게 묻는다: "톤 다듬을까요?" → yes 면 Pass 2.

방법:
1. `~/Projects/paper-review-service/src/paper_review/publish/voice_samples/*.md` 읽기 (5개, 총 ~25KB)
2. `drafts/<slug>.md` 읽기
3. **본문 영역만** (frontmatter, 논문 정보 박스, figure 캡션 제외) 운율 변환:
   - 짧은 문장 선호 (긴 문장은 둘로 쪼개기)
   - "~합니다" 어미 일관성
   - 수동태 → 능동태
   - 영어 어순 잔재 제거 ("~을 통해" 남발 제거, "~할 수 있다" 능동/수동 구분)
   - 도메인 표준 표기 유지 (attention, softmax, transformer 등 그대로)
4. **건드리지 말 것**:
   - 수식 (`$...$`, `$$...$$`)
   - 코드 블록
   - 모델명/데이터셋명/벤치마크명
   - figure 경로
   - frontmatter
5. Edit 도구로 drafts/<slug>.md 인플레이스 갱신

### Pass 3 (선택) — 사용자 최종 검토

Pass 2 끝나고:
1. "drafts/<slug>.md 에 떨어뜨렸어요. Obsidian 으로 한 번 봐주세요." 안내
2. 사용자 수정 후 publish 는 별도 CLI: `velog publish drafts/<slug>.md`

## ❌ 하지 말 것

- **Pass 2 를 자동으로 돌리지 말 것** — 사용자 동의 받고. Pass 1 결과를 그대로 쓰고 싶을 수도 있음.
- **voice_samples 의 거친 직역체를 그대로 모사하지 말 것** — 운율 (문장 길이, 어미) 만 모사하고, 깊이/구조는 kimjy99 따라가야 함. samples 는 구식 학생 노트라는 점 인지.
- **figure 캡션을 본인 말투로 다시 쓰지 말 것** — caption 은 객관 사실 묘사. 사용자 운율 무관.
- **사용자 답변 (workbench 의 A 블록) 을 압축하지 말 것** — Pass 1 에서 이미 거기를 본문으로 승격. Pass 2 는 표현 다듬기만.

## Pass 2 system prompt (참고)

```
다음은 사용자가 직접 쓴 논문 리뷰 운율 샘플입니다. 문장 길이, 어미 ("~합니다"),
한국어 어순을 학습하세요. 단, 깊이와 구성은 학습하지 마세요 — 그건 별도 kimjy99
템플릿이 결정합니다.

<voice_samples/Transformer.md ...>

이제 다음 글의 본문 영역만 운율을 본인 말투로 다듬으세요. 수식·코드·고유명사·
frontmatter 는 절대 건드리지 마세요. 의미 변경 금지.

<drafts/<slug>.md>
```

## 출판 후 처리

Pass 2 끝나면 워크벤치 status 를 `exported` 로 변경. 같은 paper 를 다시 publish 하면 drafts 의 파일을 덮어씀 (warning 후 진행).

## 참고

- 구조 templater: `~/Projects/paper-review-service/src/paper_review/publish/transform.py`
- 워크벤치 파서: `~/Projects/paper-review-service/src/paper_review/publish/parser.py`
- Voice samples: `~/Projects/paper-review-service/src/paper_review/publish/voice_samples/*.md`
- Velog 출판 다음 단계: 별도 CLI `velog publish` (`project_velog_obsidian_pipeline` 참조)
