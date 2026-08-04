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
