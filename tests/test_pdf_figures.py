"""Figures come out of a plain PDF, not just arXiv."""

import importlib.util
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "src/paper_review/_paper_reader/scripts/fetch_figures.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("fetch_figures", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _is_caption(ff, text_after):
    return bool(ff.AFTER_OK.match(text_after)) and not ff.AFTER_SENTENCE.match(
        text_after
    )


def test_a_caption_is_told_apart_from_a_sentence_mentioning_the_table():
    """ "Table 1 lists the results" starts a line as often as a caption does."""
    ff = _load()
    for after in (
        ": Parameter-efficient fine-tuning",
        "\r\nSummary of methods",
        ". The overall architecture",
        " Overview of SkillOpt",
    ):
        assert _is_caption(ff, after), after
    for after in (
        " lists the quantitative results",
        " shows the projection",
        ", and Table 3 test",
        " is the main result matrix",
    ):
        assert not _is_caption(ff, after), after


class _Obj:
    def __init__(self, type_, bounds, matrix=None, kids=()):
        self.type = type_
        self._b = bounds
        self._m = matrix
        self.kids = kids

    def get_bounds(self):
        return self._b

    def get_matrix(self):
        return self._m


class _Matrix:
    """Scale-and-translate, like the form matrices LaTeX emits."""

    def __init__(self, s, dx, dy):
        self.s, self.dx, self.dy = s, dx, dy

    def on_rect(self, l, b, r, t):
        return (
            l * self.s + self.dx,
            b * self.s + self.dy,
            r * self.s + self.dx,
            t * self.s + self.dy,
        )


class _Page:
    def __init__(self, objs):
        self._objs = objs

    def get_size(self):
        return (600.0, 800.0)

    def get_objects(self, max_depth=1, form=None):
        return form.kids if form is not None else self._objs


def test_a_figure_inside_a_form_is_found_in_page_coordinates():
    """Figures usually sit inside a form XObject whose contents are in their own
    coordinate space — read literally they land off the page, and the figure is
    invisible to anything anchoring on the caption."""
    ff = _load()
    inner = _Obj(3, (0, 0, 1000, 500))  # image, form space
    form = _Obj(5, (100, 300, 500, 500), matrix=_Matrix(0.4, 100, 300), kids=[inner])
    page = _Page([form, _Obj(2, (0, 780, 600, 781))])  # + a running-header rule

    got = ff.leaf_graphics(page, 600.0, 800.0)

    assert got == [(100.0, 300.0, 500.0, 500.0)], got
