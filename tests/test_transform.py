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


def test_figure_export_rejects_traversal(tmp_path):
    # a crafted figures/<file> ref must not escape the figures dir
    draft = "![x](figures/../../../etc/hosts)"
    out = T._materialize_figures(
        draft, paper_dir=tmp_path, draft_md=tmp_path / "d.md", vault_root=tmp_path
    )
    assert out == draft  # unchanged — escape rejected
