"""Figures belong in the section that talks about them, without being asked."""

import json

from paper_review import figplace

FIGS = [
    {
        "id": "fig2",
        "label": "Figure 2",
        "caption_ko": "그림 2 — 아키텍처 개요.",
        "ref_in_section": "overview",
        "data_uri": "data:image/png;base64,AAAA",
    },
    {
        "id": "fig3",
        "label": "Figure 3",
        "caption_en": "Figure 3: adaptive resolution.",
        "ref_in_section": "overview",
        "data_uri": "data:image/png;base64,BBBB",
    },
    {  # a table: HTML only, so an <img> would render broken
        "id": "tbl1",
        "label": "Table 1",
        "ref_in_section": "overview",
        "html": "<table></table>",
    },
    {
        "id": "fig9",
        "label": "Figure 9",
        "ref_in_section": "experiments",
        "data_uri": "data:image/png;base64,CCCC",
    },
]

WB = """---
slug: 2600.11111
---

## 섹션별 리뷰

### 2.1 Overview

<!-- section_id: 2-1-overview | lines: 10-40 -->

**원문 발췌** (lines 10-40)

> "We introduce two complementary designs."

**핵심 해설**

이 절은 설계 원칙을 세운다.

Figure 3 은 적응형 해상도를 보여준다.

마지막 문단이다.

**Claude Reader's Notes**

메모.

### 3 Experiments

<!-- section_id: 3-experiments | lines: 41-80 -->

**핵심 해설**

실험 절.
"""


def _paper(tmp_path):
    d = tmp_path / "2600.11111"
    d.mkdir()
    (d / "workbench.md").write_text(WB)
    (d / "2600.11111_figures.json").write_text(json.dumps(FIGS))
    return d


def test_a_named_figure_lands_next_to_the_paragraph_naming_it(tmp_path):
    d = _paper(tmp_path)
    assert figplace.place(d, "2.1 Overview") == 2
    out = (d / "workbench.md").read_text()

    body = out[out.index("**핵심 해설**") : out.index("**Claude Reader's Notes**")]
    lines = [l for l in body.splitlines() if l.strip()]
    named = lines.index("Figure 3 은 적응형 해상도를 보여준다.")
    assert lines[named + 1] == "![Figure 3](/paper/2600.11111/fig/fig3)"
    assert lines[named + 2] == "Figure 3: adaptive resolution."

    # fig2 is never named in the prose, so it goes to the end of the explanation
    assert lines[-2] == "![Figure 2](/paper/2600.11111/fig/fig2)"
    assert lines[-1] == "그림 2 — 아키텍처 개요."

    assert "tbl1" not in out, "a table has no image bytes to show"
    assert "fig9" not in body, "another section's figure"
    assert "메모." in out and "실험 절." in out


def test_a_table_does_not_follow_a_paragraph_about_a_figure(tmp_path):
    """Matching on the number alone put "Table 3" under the prose about
    Figure 3."""
    d = _paper(tmp_path)
    (d / "2600.11111_figures.json").write_text(
        json.dumps(
            [
                {
                    "id": "tbl3",
                    "label": "Table 3",
                    "ref_in_section": "overview",
                    "data_uri": "data:image/png;base64,DDDD",
                }
            ]
        )
    )
    assert figplace.place(d, "2.1 Overview") == 1
    body = (d / "workbench.md").read_text()
    lines = [l for l in body.splitlines() if l.strip()]
    named = lines.index("Figure 3 은 적응형 해상도를 보여준다.")
    assert "tbl3" not in lines[named + 1], "matched the wrong kind"
    assert lines[named + 1] == "마지막 문단이다."


def test_rerunning_never_duplicates(tmp_path):
    d = _paper(tmp_path)
    figplace.place(d, "2.1 Overview")
    once = (d / "workbench.md").read_text()
    assert figplace.place(d, "2.1 Overview") == 0
    assert (d / "workbench.md").read_text() == once


def test_a_paper_without_section_refs_is_left_alone(tmp_path):
    d = _paper(tmp_path)
    (d / "2600.11111_figures.json").write_text(
        json.dumps([{**f, "ref_in_section": ""} for f in FIGS])
    )
    assert figplace.place(d, "2.1 Overview") == 0
    assert (d / "workbench.md").read_text() == WB
