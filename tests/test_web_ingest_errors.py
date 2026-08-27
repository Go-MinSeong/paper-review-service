"""A failing registration has to say why, in the log the user can read."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _load(rel):
    spec = importlib.util.spec_from_file_location(Path(rel).stem, _ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_runner_raises_with_the_script_message_not_an_exit_code(monkeypatch):
    """check=True raised CalledProcessError, so the script's explanation was
    captured and discarded — the user saw "returned non-zero exit status 1"."""
    from paper_review._paper_reader import runner

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="extraction failed: 자바스크립트로 그리는 페이지"
        )

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="자바스크립트로 그리는 페이지"):
        runner._run("fetch_web.py", "https://example.com")


def test_a_javascript_rendered_page_is_named_as_such(tmp_path, monkeypatch, capsys):
    """qwen.ai/blog serves an empty container: "no main content found" reads
    like our extractor is broken, when nothing was there to extract."""
    fw = _load("src/paper_review/_paper_reader/scripts/fetch_web.py")

    class _Resp:
        text = "<html><body><div id='app'></div><script>render()</script></body></html>"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(fw.httpx, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(fw.trafilatura, "extract", lambda *a, **k: None)
    # the renderer is the fallback before this message; here it fails too
    monkeypatch.setattr(fw, "render_js", lambda *a, **k: None)
    monkeypatch.setattr(
        fw.sys, "argv", ["fetch_web.py", "https://x.test/b", "--out-dir", str(tmp_path)]
    )
    with pytest.raises(SystemExit) as e:
        fw.main()
    msg = str(e.value)
    assert "자바스크립트" in msg and "PDF" in msg, msg


SHELL = "<html><body><div id='app'></div><script>render()</script></body></html>"
RENDERED = (
    "<html><head><title>Qwen</title></head><body><article>"
    "<h1>Qwen3.8-Flash-Next: A New Architecture</h1>"
    "<h2>Introduction</h2><p>" + ("본문 " * 200) + "</p></article></body></html>"
)


def _run_main(
    monkeypatch, tmp_path, html, render_result, url="https://x.test/blog?id=a"
):
    fw = _load("src/paper_review/_paper_reader/scripts/fetch_web.py")

    class _Resp:
        text = html

        def raise_for_status(self):
            pass

    calls = []
    monkeypatch.setattr(fw.httpx, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(
        fw, "render_js", lambda u, **k: (calls.append(u), render_result)[1]
    )
    monkeypatch.setattr(fw, "extract_images", lambda *a, **k: ([], []))
    monkeypatch.setattr(
        fw.sys, "argv", ["fetch_web.py", url, "--out-dir", str(tmp_path), "--no-images"]
    )
    fw.main()
    return fw, calls


def test_an_empty_shell_is_rendered_and_titled_from_the_article(
    tmp_path, monkeypatch, capsys
):
    """The served HTML holds no article, so extraction has nothing to work with
    until the page is rendered — and the app's own <title> names the app."""
    _run_main(monkeypatch, tmp_path, SHELL, RENDERED)
    out = json.loads(capsys.readouterr().out)
    assert out["metadata"]["title"] == "Qwen3.8-Flash-Next: A New Architecture"
    assert out["metadata"]["published_date"] == "", "an SPA date is not the post's"
    assert out["source_text_length"] > 500
    assert out["content_type"] == "blog", "/blog?id= is still a blog"


def test_a_normal_page_never_pays_for_a_browser(tmp_path, monkeypatch, capsys):
    served = (
        "<html><body><article><h1>실제 제목</h1><p>"
        + ("서버가 그린 본문 " * 200)
        + "</p></article></body></html>"
    )
    _, calls = _run_main(monkeypatch, tmp_path, served, RENDERED)
    capsys.readouterr()
    assert calls == [], "rendering is a fallback, not the default path"
