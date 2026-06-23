import json
from types import SimpleNamespace

from paper_review.publish import transform as T


def _wb(content_type):
    return SimpleNamespace(frontmatter={"content_type": content_type})


def test_labels_by_content_type():
    assert T._labels(_wb("paper"))["info_heading"] == "논문 정보"
    assert T._labels(_wb("blog"))["primary_tag"] == "tech-review"
    assert T._labels(_wb("article"))["contrib_heading"] == "핵심 포인트"
    # unknown / missing → paper defaults
    assert T._labels(SimpleNamespace(frontmatter={}))["info_heading"] == "논문 정보"


def test_inline_web_figures_positions_by_heading(tmp_path):
    figs = [
        {
            "id": "fig1",
            "data_uri": "data:image/png;base64,AA",
            "caption_en": "Arch",
            "section_heading": "Architecture",
        },
        {
            "id": "fig2",
            "data_uri": "data:image/png;base64,BB",
            "caption_en": "Res",
            "section_heading": "Results",
        },
        {
            "id": "fig3",
            "data_uri": "data:image/png;base64,CC",
            "caption_en": "Orphan",
            "section_heading": "Nowhere",
        },
    ]
    (tmp_path / "x_figures.json").write_text(json.dumps(figs))
    body = "# Title\n\n## Architecture\n\nbody\n\n## Results\n\nmore\n"
    out = T._inline_web_figures(body, tmp_path)
    slug = tmp_path.name
    lines = out.split("\n")
    arch_i = lines.index("## Architecture")
    res_i = lines.index("## Results")
    # fig1 appears between Architecture and Results; fig2 after Results
    assert any(f"/paper/{slug}/fig/fig1" in l for l in lines[arch_i:res_i])
    assert any(f"/paper/{slug}/fig/fig2" in l for l in lines[res_i:])
    # unmatched fig3 goes to the bottom gallery
    assert "## 그림" in out and f"/paper/{slug}/fig/fig3" in out


def test_inline_web_figures_preserves_already_placed(tmp_path):
    # A figure the body already references must stay exactly where it is — not be
    # duplicated, moved to its section_heading, or dumped to a trailing gallery.
    figs = [
        {
            "id": "fig1",
            "data_uri": "data:image/png;base64,AA",
            "caption_en": "Arch",
            "section_heading": "Architecture",
        }
    ]
    (tmp_path / "x_figures.json").write_text(json.dumps(figs))
    slug = tmp_path.name
    body = f"# T\n\n## Intro\n\n![Arch](/paper/{slug}/fig/fig1)\n\n## Architecture\n\nbody\n"
    out = T._inline_web_figures(body, tmp_path)
    assert out.count(f"/paper/{slug}/fig/fig1") == 1  # not duplicated
    assert "## 그림" not in out
    lines = out.split("\n")
    intro_i = lines.index("## Intro")
    arch_i = lines.index("## Architecture")
    assert any("/fig/fig1" in l for l in lines[intro_i:arch_i])  # stayed in Intro


def test_sections_survive_stray_content_h2(tmp_path):
    # A stray content H2 inside 섹션별 리뷰 (e.g. a section written at H2) must
    # not truncate the review block and drop every section after it.
    from paper_review.publish.parser import parse

    wb_md = tmp_path / "workbench.md"
    wb_md.write_text(
        "---\ncontent_type: blog\n---\n# T\n\n## 섹션별 리뷰\n\n"
        "### A\n\n<!-- section_id: a | lines: 0-1 -->\n\n**요약**\nsa\n\n"
        "## 끼어든 제목\n\n"
        "### B\n\n<!-- section_id: b | lines: 2-3 -->\n\n**요약**\nsb\n\n"
        "## Q&A\n\n_(placeholder)_\n"
    )
    heads = [s.heading for s in parse(wb_md).sections]
    assert "A" in heads and "B" in heads


def test_figure_export_rejects_traversal(tmp_path):
    # a crafted figures/<file> ref must not escape the figures dir
    draft = "![x](figures/../../../etc/hosts)"
    out = T._materialize_figures(
        draft, paper_dir=tmp_path, draft_md=tmp_path / "d.md", vault_root=tmp_path
    )
    assert out == draft  # unchanged — escape rejected
