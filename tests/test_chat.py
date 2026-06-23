from pathlib import Path

import pytest

from paper_review.server.chat import _review_skill


def _mk(tmp_path: Path, content_type: str | None) -> Path:
    fm = "---\nslug: x\n"
    if content_type is not None:
        fm += f"content_type: {content_type}\n"
    fm += "---\n# x\n"
    (tmp_path / "workbench.md").write_text(fm)
    return tmp_path


@pytest.mark.parametrize(
    "ctype,expected",
    [
        ("paper", "paper-review"),
        ("blog", "blog-review"),
        ("article", "article-review"),
        ("", "paper-review"),
        (None, "paper-review"),
    ],
)
def test_review_skill_matches_content_type(tmp_path, ctype, expected):
    assert _review_skill(_mk(tmp_path, ctype)) == expected


def test_review_skill_no_workbench(tmp_path):
    assert _review_skill(tmp_path) == "paper-review"
