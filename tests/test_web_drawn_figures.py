"""Figures a page draws itself (inline SVG, CSS) have no image file to fetch —
archerhume's post had five and registered none."""

import importlib.util
import io
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _ROOT / "src/paper_review/_paper_reader/scripts"


def _load():
    sys.path.insert(0, str(_SCRIPTS))  # fetch_web imports fetch_figures
    spec = importlib.util.spec_from_file_location("fetch_web", _SCRIPTS / "fetch_web.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _png():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(buf, "PNG")
    return buf.getvalue()


PAGE = """<html><body><article>
<h2>Setup</h2>
<figure class="chart"><svg viewBox="0 0 10 10"></svg>
  <figcaption>Figure 1. Latency by request size.</figcaption></figure>
<figure class="highlight"><pre>print("code")</pre></figure>
<blockquote>quote</blockquote>
<h2>Results</h2>
<figure><div class="bars"></div><figcaption>Figure 2. Odds by option order.</figcaption></figure>
<figure><div class="bars"></div><figcaption>Figure 3. Calibration.</figcaption></figure>
</article></body></html>"""


def test_drawn_figures_are_captured_in_order_and_code_blocks_are_not(monkeypatch):
    fw = _load()
    asked = {}

    def fake_snapshot(url, wanted):
        asked["wanted"] = wanted
        return {0: _png(), 2: _png()}  # the middle one fails to capture

    monkeypatch.setattr(fw, "snapshot_figures", fake_snapshot)
    figs, warns = fw.extract_images(
        PAGE, "https://example.com/p", max_width=800, jpeg_quality=80, max_images=30
    )

    # the <pre> figure (document index 1) is a code block, not a figure
    assert [i for i, _ in asked["wanted"]] == [0, 2, 3]
    assert [f["caption_en"] for f in figs] == [
        "Figure 1. Latency by request size.",
        "Figure 3. Calibration.",
    ]
    assert [f["id"] for f in figs] == ["fig1", "fig2"], "ids stay contiguous"
    assert figs[0]["section_heading"] == "Setup"
    assert figs[1]["section_heading"] == "Results"
    assert all(f["data_uri"].startswith("data:image/png") for f in figs)
    assert not any("_drawn" in f for f in figs)
    assert any("could not be captured" in w for w in warns)


def test_a_page_with_only_image_files_never_starts_a_browser(monkeypatch):
    fw = _load()
    monkeypatch.setattr(
        fw, "snapshot_figures", lambda *a: (_ for _ in ()).throw(AssertionError)
    )
    monkeypatch.setattr(fw, "http_get", lambda url, timeout=20: _png())
    page = '<article><figure><img src="/a.png"><figcaption>c</figcaption></figure></article>'
    figs, _ = fw.extract_images(
        page, "https://example.com/p", max_width=800, jpeg_quality=80, max_images=30
    )
    assert len(figs) == 1 and figs[0]["caption_en"] == "c"
