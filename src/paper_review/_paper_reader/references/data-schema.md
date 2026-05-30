# Paper Data Schema

`build_html.py`에 넘기는 `paper.json`의 정확한 구조. 번역과 분석을 끝내고 이 schema에 맞춰 단일 JSON 파일을 작성한 뒤, `build_html.py`로 viewer에 주입한다.

## Top-level

```json
{
  "metadata": { ... },
  "prerequisites": [ ... ],
  "key_terms": [ ... ],
  "sections": [ ... ],
  "github": { ... } | null,
  "further_reading": { ... },
  "ambiguities": [ ... ],
  "code_clarifications": [ ... ],
  "figures": [ ... ]
}
```

`ambiguities`, `code_clarifications`, `figures`는 선택. 빈 배열이면 viewer에서 자동으로 안 보임.

## metadata

```json
{
  "title": "Original English title",
  "title_ko": "한국어 제목 (의역해서 자연스럽게)",
  "authors": ["First Author", "Second Author", "..."],
  "venue": "arXiv 2024  /  NeurIPS 2024  /  ICRA 2025  / ...",
  "year": 2024,
  "category": "VLA",
  "arxiv_id": "2410.12345",
  "url": "https://arxiv.org/abs/2410.12345",
  "github_url": "https://github.com/owner/repo",
  "abstract_en": "Original abstract (one paragraph, preserve LaTeX).",
  "abstract_ko": "한국어 번역된 abstract."
}
```

`arxiv_id`, `github_url`은 없으면 `null` 또는 빈 문자열 OK. `title`, `year`, `venue`, `abstract_en`은 필수 (`validate_paper.py`가 검증).

`category` 권장 값 (오픈 리스트, 새 도메인이면 추가 OK):
`VLA`, `Foundation Models`, `LLM`, `VLM`, `Diffusion`, `RL`, `Robotics`, `Vision`, `Speech`, `NLP`, `Theory`, `Systems`, `Other`

가장 적합한 한 개를 고를 것. "Other"는 정말로 어느 카테고리에도 안 맞을 때만.

`notices` (선택, 배열): 추출/처리 중 발생한 사용자 알림. viewer 상단에 노란 박스로 표시됨. 예시:

```json
{
  "metadata": {
    ...,
    "notices": ["ar5iv 변환 실패 — 표가 누락됐을 수 있음. 원문 PDF 확인 권장."]
  }
}
```

전형적 사용:
- `fetch_figures.py`가 tarball fallback을 썼고 (`source: "tarball"`이 다수) 표가 0개일 때 → "표 추출 실패 가능성"
- abstract 추출이 broken cid: 글리프로 깨졌을 때 → "추출 품질 저하"

비어있거나 생략 OK.

## prerequisites (외부 사전 지식)

논문이 사용하지만 정의하지 않는 개념들. **5-12개 권장.**

```json
[
  {
    "term": "Flow Matching",
    "explanation_ko": "여러 문장의 직관적 설명. 왜 이 논문에 필요한지까지 포함."
  }
]
```

작성 가이드:
- `term`은 본문에 등장하는 영문 표기 그대로 (대소문자, 하이픈 정확히)
- `explanation_ko`는 4-6 문장. 정의 + 직관 + 이 논문 맥락에서 왜 중요한지

## key_terms (논문 내부 핵심 용어)

논문이 도입하거나 특정한 의미로 사용하는 용어. **5-12개 권장.**

```json
[
  {
    "term": "Action Expert",
    "definition_ko": "정의 (한 문장 정도)",
    "context_ko": "이 논문에서의 역할과 어디서 처음 등장하는지 (1-2문장)"
  }
]
```

`term`은 본문 등장 시 자동 하이라이트 + hover tooltip 매칭에 쓰이므로 표기를 정확히.

## sections

```json
[
  {
    "id": "introduction",
    "level": 1,
    "title_en": "Introduction",
    "title_ko": "서론",
    "summary_ko": "이 섹션의 4-6 문장 한국어 요약.",
    "paragraphs": [
      {
        "en": "English paragraph (preserve LaTeX, code, references like 'Fig. 3').",
        "ko": "한국어 번역."
      }
    ],
    "readers_notes_md": "선택 항목. 섹션 끝 Reader's Notes 박스에 들어갈 마크다운."
  }
]
```

- `id`: URL fragment용 짧은 영문 식별자. (`"introduction"`, `"method"`, `"exp-libero"` 등)
- `level`: 1 = 메인 섹션, 2 = 서브섹션. 보통 메인만 써도 충분. 너무 잘게 쪼개지 말 것 — 가독성 떨어짐.
- `paragraphs`: 단락 단위 분할. 수식 블록은 단락 안에 포함하거나 별도 단락으로.
- `summary_ko`: **4-6 문장의 한국어 요약**. 이 섹션이 *무엇을 말했는지*를 압축. viewer "요약" 모드에서 paragraphs 대신 표시됨. 비어있어도 viewer는 "(요약 미작성)" 안내로 fallback. 관계는: paragraphs = 정확한 번역, **summary_ko = 빠른 훑기용 요약**, readers_notes_md = 외부 통찰.
- `readers_notes_md`: 마크다운. 헤딩, 리스트, **bold**, `code`, 링크 모두 OK. 없으면 빈 문자열 또는 생략.

### summary_ko 작성 가이드

- **요약은 '무엇을 말했는가'**, Reader's Notes는 '무엇을 생각해야 하는가'. 둘은 다르다.
- 4-6 문장. 본문 paragraphs를 다 옮겨놓은 다음 마지막에 작성하면 자연스럽게 흐름이 잡힌다.
- 핵심 결론 / 핵심 수치 / 핵심 비교를 살린다. 디테일이나 reference 인용은 뺀다.
- 본문에 등장하는 key_terms 영문 표기는 요약에도 그대로 (hover 매칭 유지).
- 수식은 핵심만. 요약에 LaTeX 블록을 넣지 말 것.
- "이 섹션은 ~을 다룬다" 같은 메타 표현보다 "X는 ~한다" 같은 직접 진술이 좋음.

## github (옵션)

GitHub repo가 있을 때만:

```json
{
  "repo": "owner/repo",
  "url": "https://github.com/owner/repo",
  "description": "Short repo description (from GitHub API).",
  "language": "Python",
  "stars": 1234,
  "tree_text": "src/\n  models/\n    smolvla.py\n  utils/\n    ...",
  "highlights_ko": "이 repo에서 주목할 디렉토리/파일을 한국어로 짧게 (markdown OK)."
}
```

`tree_text`는 `<pre>`로 렌더되므로 줄바꿈/들여쓰기 그대로 유지. `fetch_github.py`가 생성한 텍스트를 그대로 쓰면 된다.

`highlights_ko`는 사용자가 가장 가치를 느낄 부분 — "어디부터 코드를 읽으면 좋은지"를 1-3 문단으로.

## further_reading

```json
{
  "from_references": [
    {
      "title": "Paper title",
      "authors": "Author1, Author2 et al.",
      "year": 2023,
      "url": "https://arxiv.org/abs/...",
      "why_ko": "왜 읽어야 하는지 (1-2 문장). 예: 'X 개념의 원 출처', '이 논문의 baseline'."
    }
  ],
  "follow_up": [
    {
      "title": "Paper title",
      "authors": "...",
      "year": 2025,
      "url": "...",
      "why_ko": "예: '이 논문 이후 X 방향으로 발전', 'Y 한계를 해결하려는 후속 작업'."
    }
  ]
}
```

각 그룹 3-5개 권장. 못 찾으면 빈 배열 OK (해당 섹션이 자동으로 안 보임).

## ambiguities (논문이 흐리게 둔 지점)

번역 작업 중 paper-translator가 발견한 "논문이 명시하지 않았거나 모호한" 지점들. 이후 `github-investigator`가 코드와 대조해서 명확히 한다.

```json
[
  {
    "id": "img-resolution",
    "section_id": "the-pi0-model",
    "where_ko": "Section IV, paragraph 3 — \"2 or 3 images per robot\"",
    "question_ko": "이미지 해상도가 명시되지 않음. 인코더 입력 크기는?",
    "search_hint": "Resize, image_size, transforms, crop"
  }
]
```

- `id`: 짧은 영문 식별자, 한 paper 내 unique
- `section_id`: 어느 섹션에 속하는지 (없으면 빈 문자열). viewer에서 해당 섹션 끝에 clarification 박스로 매칭하는 데 사용.
- `where_ko`: 사람이 읽을 위치 표시 (Section/Paragraph/Appendix 등)
- `question_ko`: 무엇이 모호한지 한국어로
- `search_hint`: github-investigator가 코드에서 grep할 키워드 (영문, 콤마 구분 또는 리스트)

작성 가이드:
- 번역 중 자연스럽게 발견된 것만. 억지로 만들지 말 것.
- "Hyperparameter 표가 부록에 있는지" 같은 것보다 "본문이 이 결정을 흐리게 둔 곳"에 집중.
- 5-10개 정도가 적당. 없으면 빈 배열.

## code_clarifications (코드에서 확정한 사실)

`github-investigator` 에이전트가 작성. ambiguities 항목 일부에 대응되거나, ambiguity와 무관하게 코드를 보다 발견한 의미 있는 detail.

```json
[
  {
    "ambiguity_id": "img-resolution",
    "section_id": "the-pi0-model",
    "title_ko": "이미지 해상도",
    "finding_ko": "224×224로 리사이즈 (논문 명시 없음). PaliGemma 기본 입력 크기.",
    "evidence": {
      "file": "src/openpi/transforms.py",
      "lines": "47-52",
      "snippet": "image = image.resize((224, 224), ...)"
    }
  }
]
```

- `ambiguity_id`: 대응되는 ambiguity의 id. 없으면 null이거나 생략 (코드 자체에서 발견한 detail).
- `section_id`: viewer에서 어느 섹션 끝에 표시할지. 없으면 GitHub 섹션 안에 모아 표시.
- `title_ko`: 한 줄 짧은 제목
- `finding_ko`: 발견 내용 (1-3 문장). "(논문 명시 없음)" 같은 단서를 넣어 출처를 명확히.
- `evidence`: 어느 파일 어디에서 확인했는지. `snippet`은 짧게 (3-10 줄).

작성 가이드:
- 모든 ambiguity가 답을 찾을 필요는 없음. 코드를 봐도 모호하면 그건 그대로 둔다.
- ambiguity와 무관해도 "본문에선 안 나왔지만 실무자가 알면 좋은 detail"은 추가 OK.
- 8-15개 정도가 적당.

## figures (논문의 시각 에셋: 이미지 + 표)

`scripts/fetch_figures.py`가 ar5iv HTML 또는 arXiv source tarball에서 추출. 표는 ar5iv의 HTML을 보존하고, 이미지는 base64 data URI로 인라인 저장. 캡션 한국어 번역은 paper-translator가 자기 섹션 작업 시 채운다.

```json
[
  {
    "id": "fig3",
    "kind": "image",
    "label": "Figure 3",
    "caption_en": "Overview of our model and training procedure.",
    "caption_ko": "",
    "data_uri": "data:image/png;base64,iVBORw0KGgo...",
    "width": 800,
    "ref_in_section": null,
    "source": "ar5iv"
  },
  {
    "id": "tbl2",
    "kind": "table",
    "label": "Table 2",
    "caption_en": "Comparison of methods on benchmark X.",
    "caption_ko": "",
    "html": "<table class=\"ltx_tabular\">...</table>",
    "ref_in_section": "experiments",
    "source": "ar5iv"
  }
]
```

공통 필드:
- `id`: 짧은 영문 식별자 (`fig1`, `tbl2` 등). paper 내 unique.
- `kind`: `"image"` 또는 `"table"`. 누락되면 viewer는 `"image"`로 가정.
- `label`: 사람이 읽는 라벨 (`"Figure 3"`, `"Table 2"`). 본문 매칭에 사용.
- `caption_en`, `caption_ko`: 캡션. 빈 문자열이어도 viewer는 라벨만 표시.
- `ref_in_section`: 본문 어느 섹션에 인라인으로 띄울지. null이면 viewer 마지막 "그림 모음" 갤러리에 표시. fetch_figures.py가 본문 첫 등장 위치로 자동 추정.
- `source`: `"ar5iv"` / `"tarball"` / `"manual"`. 디버깅용.

`kind="image"` 전용:
- `data_uri`: base64 data URI. 외부 fetch 실패하면 빈 문자열.
- `width`: 다운사이즈된 width (px). 기본 800.

`kind="table"` 전용:
- `html`: ar5iv의 `<table class="ltx_tabular">` HTML. ar5iv가 변환한 표 그대로 보존되어 검색·copy 가능. tarball fallback에선 표 추출 안 함 (LaTeX 직접 렌더는 의존성 무거워서 제외).

작성 가이드:
- figures+tables 합쳐 보통 5-20개.
- caption_en이 너무 긴(500자+) 항목은 그대로 두되 viewer에서 접힘 처리 (고려 중).
- ar5iv가 실패한 논문(약 5-10%)은 표가 누락될 수 있다. 메인이 인지하면 `metadata.notices`에 한 줄 기록 (data-schema의 metadata 참조).

## Validation

`build_html.py`는 JSON 파싱만 검증한다. 필드가 빠지면 viewer가 빈 영역을 그릴 뿐이므로 schema를 따르려고 노력할 것. 특히:

- `paragraphs`의 각 항목은 `en`과 `ko` 둘 다 비워두지 말 것 (한쪽만 있으면 토글 시 빈 칸이 보임)
- `term`은 영문 표기 정확히 (하이라이트 매칭이 case-sensitive)
- 마크다운 안에 `</script>`가 들어가면 `build_html.py`가 자동으로 escape (걱정 안 해도 됨)

## Output format (PAPER_DATA injection)

`build_html.py`는 paper.json을 단일 라인 compact JSON(`json.dumps(paper, ensure_ascii=False)`)으로 직렬화해 viewer template의 `"__PAPER_DATA__"` 자리에 주입한다. 외부 도구가 viewer HTML에서 PAPER_DATA를 다시 추출할 때는 sentinel 주석으로 감싸진 영역을 찾으면 된다:

```js
/* PAPER_DATA_BEGIN */
const PAPER_DATA = {...compact JSON...};
/* PAPER_DATA_END */
```

가정해도 좋은 것:
- 한 줄로 등장
- `</script>` 시퀀스만 `<\/script>`로 escape됨 (다른 escape 없음)
- 들여쓰기 없음

이 형식이 바뀌면 `build_html.py` 변경 + 변경 이력을 명시할 것.
