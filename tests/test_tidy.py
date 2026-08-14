"""tidy-sections must remove the junk blocks and nothing else."""

from paper_review import tidy

WB = """---
slug: x
---

## 섹션별 리뷰

### 1 Introduction

<!-- section_id: 1-introduction | lines: 0-3 -->

**핵심 해설**

진짜 섹션이다.

### 2 Model Architecture

### 3. Timestamps: {START_TIME}

<!-- section_id: t | lines: 5-6 -->

**핵심 해설**

프롬프트 템플릿에서 온 블록.

## Q&A

- 사용자의 답변은 여기 있고 건드리면 안 된다.
"""

SRC = "\n".join(
    [
        "1 Introduction",
        "Body long enough to survive the minimum-length rule that the section "
        "index applies to every heading it finds in the source text.",
        "",
        "2 Model Architecture",
        "3. Timestamps: {START_TIME}",
        "x",
    ]
)


def _paper(tmp_path):
    d = tmp_path / "2600.11111"
    d.mkdir()
    (d / "workbench.md").write_text(WB)
    (d / "2600.11111_source.txt").write_text(SRC)
    return d


def test_plan_names_the_junk_and_spares_the_real_section(tmp_path):
    d = _paper(tmp_path)
    rows = {h: why for h, why, _ in tidy.plan(d)}
    assert rows == {
        "2 Model Architecture": "빈 제목",
        "3. Timestamps: {START_TIME}": "섹션 아님",
    }


def test_apply_keeps_the_review_and_the_answers(tmp_path):
    d = _paper(tmp_path)
    assert tidy.apply(d) == 2
    out = (d / "workbench.md").read_text()
    assert "### 1 Introduction" in out and "진짜 섹션이다" in out
    assert "Timestamps" not in out and "### 2 Model Architecture" not in out
    assert "사용자의 답변은 여기 있고" in out, "Q&A must never be touched"
    assert list((d / ".history").glob("workbench-*.md")), "no snapshot kept"
