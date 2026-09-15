"""The report-diagram lint flags what looked broken in real Summaries and
stays quiet on what looked right."""

from paper_review.svglint import lint_report, lint_svg


def _svg(body, vb="0 0 400 200"):
    return f'<svg viewBox="{vb}" xmlns="http://www.w3.org/2000/svg">{body}</svg>'


ARROW = '<defs><marker id="a"><path d="M0 0L6 3L0 6z"/></marker></defs>'


def test_a_clean_box_and_arrow_diagram_has_no_findings():
    body = (
        ARROW
        + '<rect x="10" y="60" width="140" height="50"/>'
        + '<text x="80" y="90" font-size="13" text-anchor="middle">Encoder</text>'
        + '<line x1="150" y1="85" x2="240" y2="85" marker-end="url(#a)"/>'
        + '<rect x="240" y="60" width="140" height="50"/>'
        + '<text x="310" y="90" font-size="13" text-anchor="middle">디코더</text>'
    )
    assert lint_svg(_svg(body)) == []


def test_text_wider_than_its_box_is_flagged():
    """2609.04304: "coarse: c_corr·(1−c_degen)·c_depth" ran past its card."""
    body = (
        '<rect x="10" y="40" width="120" height="50"/>'
        '<text x="20" y="70" font-size="13">coarse: c_corr·(1−c_degen)·c_depth·c_long</text>'
    )
    assert any(d.startswith("TEXT_OVERFLOW") for d in lint_svg(_svg(body)))


def test_font_size_from_an_svg_style_class_is_respected():
    """Diagrams that size text through <style> classes were misread at 16px and
    every label looked like it overflowed."""
    body = (
        "<style>.ts{font-size:10px;text-anchor:middle}</style>"
        '<rect x="20" y="30" width="150" height="62"/>'
        '<text class="ts" x="95" y="74">113 spk · accent 위치만</text>'
    )
    assert lint_svg(_svg(body)) == []


def test_labels_drawn_on_top_of_each_other_are_flagged():
    """qwen3.8: "long-range" sat on "widened residual"."""
    body = (
        '<text x="105" y="34" font-size="12.5" text-anchor="middle">widened residual</text>'
        '<text x="60" y="24" font-size="10.5" text-anchor="middle">long-range</text>'
    )
    assert any(d.startswith("TEXT_OVERLAP") for d in lint_svg(_svg(body)))


def test_a_label_wedged_into_a_neighbouring_box_is_flagged():
    """qwen3.8: an edge label "Layer 2" sat half inside the block box it ran
    past — a few px of intrusion, which is why this check measures the
    unshrunk width."""
    body = (
        '<rect x="20" y="94" width="250" height="64"/>'
        '<rect x="300" y="94" width="320" height="64"/>'
        '<text x="283" y="112" font-size="11" text-anchor="middle">Layer 2 prefetch</text>'
    )
    assert any(
        d.startswith("TEXT_OVER_BOX") for d in lint_svg(_svg(body, "0 0 900 470"))
    )

    beside = body.replace('x="283"', 'x="285"').replace(
        "Layer 2 prefetch", "·"
    )  # a small label in the gap is fine
    assert lint_svg(_svg(beside, "0 0 900 470")) == []


def test_text_cut_off_by_the_viewbox_is_flagged():
    body = '<text x="300" y="100" font-size="11">전역 키 하나로 서명 → 컨텍스트에 묶여 있지 않음</text>'
    assert any(d.startswith("TEXT_CLIPPED") for d in lint_svg(_svg(body)))


def test_an_arrow_from_a_box_into_empty_space_is_flagged_but_an_axis_is_not():
    """2608.03893: an arrow left the ridge box and ended nowhere. A chart axis
    also ends in an arrowhead over empty space, but it doesn't leave a box."""
    dangling = (
        ARROW
        + '<rect x="10" y="60" width="120" height="50"/>'
        + '<line x1="130" y1="85" x2="220" y2="85" marker-end="url(#a)"/>'
    )
    assert any(d.startswith("DANGLING_ARROW") for d in lint_svg(_svg(dangling)))

    axis = ARROW + '<line x1="20" y1="180" x2="380" y2="180" marker-end="url(#a)"/>'
    assert lint_svg(_svg(axis)) == []


def test_a_connector_through_an_unrelated_box_is_flagged_but_a_timeline_is_not():
    through = (
        ARROW
        + '<rect x="10" y="70" width="60" height="40"/>'
        + '<rect x="160" y="60" width="80" height="60"/>'
        + '<rect x="330" y="70" width="60" height="40"/>'
        + '<line x1="70" y1="90" x2="330" y2="90" marker-end="url(#a)"/>'
    )
    assert any(d.startswith("EDGE_THROUGH_BOX") for d in lint_svg(_svg(through)))

    # interval bars sitting on a plain guide line (2607.17423)
    timeline = (
        '<line x1="20" y1="66" x2="380" y2="66"/>'
        '<rect x="60" y="58" width="80" height="16"/>'
        '<rect x="200" y="58" width="60" height="16"/>'
    )
    assert lint_svg(_svg(timeline)) == []


def test_report_numbers_each_diagram():
    bad = '<text x="390" y="100" font-size="14">잘리는 긴 라벨입니다</text>'
    html = f"<html><body>{_svg('')}<div>{_svg(bad)}</div></body></html>"
    found = lint_report(html)
    assert found and all(d.startswith("diagram 2 · ") for d in found)
