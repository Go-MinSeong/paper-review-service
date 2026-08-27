"""A failing registration has to say why, in the log the user can read."""

import importlib.util
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
    monkeypatch.setattr(
        fw.sys, "argv", ["fetch_web.py", "https://x.test/b", "--out-dir", str(tmp_path)]
    )
    with pytest.raises(SystemExit) as e:
        fw.main()
    msg = str(e.value)
    assert "자바스크립트" in msg and "PDF" in msg, msg
