"""The section index must not invent sections that have no text."""

import importlib.util
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "src/paper_review/_paper_reader/scripts/init_paper.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("init_paper", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_chapter_title_with_no_body_is_not_a_section(tmp_path):
    """ "2 Model Architecture" straight into "2.1 Overview" owns no text — as its
    own section it cost an analyze call and left an empty block in the review."""
    ip = _load()
    text = "\n".join(
        [
            "1 Introduction",
            "Video understanding spans motion, long video and streaming "
            "interaction, and this paper argues the three can share one model.",
            "",
            "2 Model Architecture",  # nothing of its own before 2.1
            "2.1 Overview",
            "We encode frames with an inflated ViT so the temporal axis is "
            "compressed before any token ever reaches the language model.",
        ]
    )
    out = tmp_path / "s.txt"
    ip.write_sections_index(text, out)
    headings = [
        l.split(": ", 1)[1]
        for l in out.read_text().splitlines()
        if l and not l.startswith("#")
    ]
    assert headings == ["1 Introduction", "2.1 Overview"]


def test_a_table_row_read_as_a_heading_is_not_a_section(tmp_path):
    """Heading detection also fires on table rows and prompt templates; their
    "body" is a few characters, which is how "3 GPT-4V (50 frames) 55.3" became
    a reviewable section."""
    ip = _load()
    text = "\n".join(
        [
            "1 Introduction",
            "A real section carries at least a couple of sentences of prose, "
            "which is exactly what tells it apart from a stray table row.",
            "",
            "3 GPT-4V (50 frames) 55.3",
            "7 GPT-4 33.5",
        ]
    )
    out = tmp_path / "s.txt"
    ip.write_sections_index(text, out)
    assert "GPT-4V" not in out.read_text()


def test_prompt_template_and_table_rows_are_not_headings(tmp_path):
    """Numbered list items in quoted prompts and rows of a results table both
    start with a number, which is how "1. Question: {question}" and
    "1 Dense overlap 74.57" became sections."""
    ip = _load()
    prose = (
        "This paragraph exists only so the heading above it clears the "
        "minimum body length that a real section has to carry."
    )
    text = "\n".join(
        [
            "1 Introduction",
            prose,
            "",
            "2. Question: {question}",
            prose,
            "",
            "3 Dense overlap 74.57",
            prose,
            "",
            "4. Keep key insights, important calculations, and the reasoning path.",
            prose,
        ]
    )
    out = tmp_path / "s.txt"
    ip.write_sections_index(text, out)
    got = out.read_text()
    assert "1 Introduction" in got
    for junk in ("{question}", "74.57", "Keep key insights"):
        assert junk not in got, junk


def test_repeated_labels_and_everything_after_the_bibliography_are_dropped(tmp_path):
    """A label a paper prints on every page is a table header, not a section —
    and past "References" the initials of cited authors read as Roman-numeral
    headings ("I. Mordatch, I. Radosavovic, …")."""
    ip = _load()
    prose = (
        "Body text long enough to look like a real section rather than a "
        "stray fragment of a table or a caption."
    )
    text = "\n".join(
        [
            "1 Introduction",
            prose,
            "",
            "ABILITY",  # a results-table column header, reprinted below
            prose,
            "",
            "ABILITY",
            prose,
            "",
            "References",
            "",
            "I. Mordatch, I. Radosavovic, I. Leal, J. Liang and J. Kim, 2024.",
            prose,
        ]
    )
    out = tmp_path / "s.txt"
    ip.write_sections_index(text, out)
    got = out.read_text()
    assert "1 Introduction" in got
    assert "ABILITY" not in got
    assert "Mordatch" not in got


def test_appendix_numbering_that_restarts_is_not_a_section(tmp_path):
    """Papers without a detectable bibliography run straight into an appendix
    whose tables renumber from 1 — "2 Cross-session" after "6 Conclusion". An
    acronym title ("4.3.4 STAL") must survive the all-caps rule that catches
    banners like "DECODED REASONING"."""
    ip = _load()
    prose = (
        "Enough prose to clear the minimum body length, so that what gets "
        "dropped here is dropped for its heading and not for its size."
    )
    text = "\n".join(
        [
            "1 Introduction",
            prose,
            "",
            "4.3.4 STAL",
            prose,
            "",
            "DECODED REASONING",  # a figure banner in a numbered paper
            prose,
            "",
            "6 Conclusion",
            prose,
            "",
            "2 Cross-session",  # appendix table row, numbering restarts
            prose,
            "",
            "6 Nonce",  # the paper already had a section 6
            prose,
        ]
    )
    out = tmp_path / "s.txt"
    ip.write_sections_index(text, out)
    got = out.read_text()
    assert "4.3.4 STAL" in got and "6 Conclusion" in got
    for junk in ("DECODED REASONING", "Cross-session", "Nonce"):
        assert junk not in got, junk
