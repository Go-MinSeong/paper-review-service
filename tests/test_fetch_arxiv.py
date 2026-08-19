"""Registration must survive the arXiv API being down or rate-limiting."""

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "src/paper_review/_paper_reader/scripts/fetch_arxiv.py"
)

ABS_PAGE = """
<html><head>
<meta name="citation_title" content="Cross-Model KV Cache Transfer"/>
<meta name="citation_author" content="Heo, Taekyung"/>
<meta name="citation_author" content="Shafipour, Rasoul"/>
<meta name="citation_date" content="2026/08/04"/>
</head><body>
<blockquote class="abstract mathjax">Abstract:  Production deployments often
swap between <span>different-sized</span> models.</blockquote>
</body></html>
"""


def _load():
    spec = importlib.util.spec_from_file_location("fetch_arxiv", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_metadata_falls_back_to_the_abs_page(monkeypatch):
    """A 429 from export.arxiv.org used to fail the whole registration, even
    though the PDF itself downloads from a host that is still fine."""
    fa = _load()
    calls = []

    def fake_get(url, timeout, tries=3):
        calls.append(url)
        if "export.arxiv.org" in url:
            raise RuntimeError("HTTP Error 429: Unknown Error")
        return ABS_PAGE.encode()

    monkeypatch.setattr(fa, "_get", fake_get)
    md = fa.fetch_metadata("2608.03893")

    assert md["title"] == "Cross-Model KV Cache Transfer"
    assert md["authors"] == ["Heo, Taekyung", "Shafipour, Rasoul"]
    assert md["abstract"].startswith("Production deployments often swap")
    assert "Abstract:" not in md["abstract"]
    assert any("arxiv.org/abs" in u for u in calls)


def test_get_retries_before_giving_up(monkeypatch):
    fa = _load()
    monkeypatch.setattr(fa.time, "sleep", lambda _: None)
    attempts = []

    def flaky(req, timeout):
        attempts.append(1)
        raise TimeoutError("read timed out")

    monkeypatch.setattr(fa.urllib.request, "urlopen", flaky)
    with pytest.raises(TimeoutError):
        fa._get("https://arxiv.org/abs/x", 5, tries=3)
    assert len(attempts) == 3, "one attempt is what made a flaky API fatal"
