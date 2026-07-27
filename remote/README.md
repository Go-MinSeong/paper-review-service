# paper-review remote (모바일 이어보기)

로컬 paper-review의 페이퍼 **하나**를 원격 슬롯에 올려두고, 모바일 브라우저에서
읽기 + 섹션별 편집(내 정리/Q&A/frontmatter)을 하는 단일 페이지 앱.
동기화는 전부 **수동**(push / pull)이며 슬롯은 항상 1개 — push가 통째로 교체한다.

```
로컬 detail 📱 버튼 / `paper-review remote push <slug>`   → 슬롯 교체
모바일에서 섹션 ✏️ 편집·저장 (rev 증가, 충돌 시 409)
로컬 갤러리 📥 버튼 / `paper-review remote pull`          → workbench.md 갱신(.bak 백업)
```

## 배포 (최초 1회, Vercel)

1. vercel.com → Add New Project → 이 GitHub repo import
   - **Root Directory: `remote`** (프레임워크 preset: Other)
2. Storage 탭 → **Blob** store 생성해 프로젝트에 연결
   (`BLOB_READ_WRITE_TOKEN` 자동 주입)
3. Settings → Environment Variables → **`REMOTE_TOKEN`** = 긴 랜덤 문자열
   (`openssl rand -hex 24` 등으로 생성)
4. Deploy → 배포 URL 확인

## 로컬 설정 (최초 1회)

갤러리 우측 상단 ⚙ → **설정 → 모바일**에서 배포 URL과 `REMOTE_TOKEN` 값을 입력한다.
`~/.config/paper-review/remote.json`(권한 600, repo 밖)에 저장되며, 저장 후 화면으로
다시 표시되지 않는다. 직접 쓰거나 환경변수(`PAPER_REVIEW_REMOTE_URL` /
`PAPER_REVIEW_REMOTE_TOKEN`, 이쪽이 우선)를 써도 된다.

모바일에서 배포 URL을 열고 같은 토큰 입력(기기에 저장됨).

## 모바일 화면

- **Detail** — 워크벤치. `###` 섹션 단위 ✏️ 편집, ⚙ 로 frontmatter/서문 편집.
- **Summary** — push 시점의 `report.md`. **읽기 전용**(리포트는 로컬 Analyze가 생성).
  리포트가 없는 페이퍼는 전환 버튼이 나오지 않는다.

## 주의

- Analyze/Chat/Publish는 로컬 전용(Claude/velog CLI 필요) — 모바일은 읽기·편집만.
- 저장소는 Vercel Blob의 public(비공개 아님, URL은 사실상 추측 불가) 오브젝트 —
  진짜 민감한 내용은 올리지 말 것.
- pull은 로컬 workbench.md를 덮어쓰기 전에 `workbench.md.bak`으로 백업한다.
- push 후 로컬에서 수정했다면 pull이 그 수정을 되돌릴 수 있음(수동 동기화 원칙).
