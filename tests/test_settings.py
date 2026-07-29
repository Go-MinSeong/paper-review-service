import sys

import pytest
from fastapi import HTTPException

from paper_review.server import settings as S


def test_base_name_strips_variant_suffix():
    assert S._base_name("corgi.jpg") == "corgi"
    assert S._base_name("corgi-2.jpg") == "corgi"
    assert S._base_name("redpanda-12.png") == "redpanda"


def test_skill_dir_rejects_traversal():
    for bad in ["../etc", "a/b", "..", "", "x;y"]:
        with pytest.raises(HTTPException):
            S._skill_dir(bad)


def test_safe_char_name_rejects_bad_inputs():
    for bad in ["../x.jpg", "a/b.png", ".hidden.jpg", "note.txt", ""]:
        with pytest.raises(HTTPException):
            S._safe_char_name(bad)
    assert S._safe_char_name("corgi-2.jpg") == "corgi-2.jpg"


def test_illustration_groups_structure():
    g = S.illustration_groups()
    assert set(g) == {"groups", "tag_groups"}
    have = set(S.list_illustrations())
    # every file listed in a group actually exists
    for files in g["groups"].values():
        for f in files:
            assert f in have
    # every tag maps to a real group
    for grp in g["tag_groups"].values():
        assert grp in g["groups"]


def test_drafts_dir_resolution(tmp_path, monkeypatch):
    from paper_review import config as C

    monkeypatch.setattr(C, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.delenv("PAPER_REVIEW_DRAFTS_DIR", raising=False)
    # default
    assert C.get_drafts_dir() == C.DEFAULT_DRAFTS_DIR
    # settings.json wins over default
    C.save_settings({"drafts_dir": "/tmp/my-vault/drafts"})
    assert str(C.get_drafts_dir()) == "/tmp/my-vault/drafts"
    # env wins over settings
    monkeypatch.setenv("PAPER_REVIEW_DRAFTS_DIR", "/tmp/env-vault/drafts")
    assert str(C.get_drafts_dir()) == "/tmp/env-vault/drafts"


def test_splash_boot_sequence(monkeypatch):
    """The launch screen must report progress, hand over to the gallery, and
    surface failures instead of leaving a blank window."""
    from paper_review import app as A

    class W:
        def __init__(self):
            self.js, self.url = [], None

        def evaluate_js(self, s):
            self.js.append(s)

        def load_url(self, u):
            self.url = u

    monkeypatch.setattr(A, "_install_skills", lambda: None)
    monkeypatch.setattr(A, "start_server", lambda port: None)

    monkeypatch.setattr(A, "_wait_server", lambda port, timeout=20.0: True)
    ok = W()
    A._boot(ok, 7777)
    assert ok.url == "http://127.0.0.1:7777/"
    assert any("prStatus" in j for j in ok.js) and not any("prFail" in j for j in ok.js)

    monkeypatch.setattr(A, "_wait_server", lambda port, timeout=20.0: False)
    bad = W()
    A._boot(bad, 7777)
    assert bad.url is None and any("prFail" in j for j in bad.js)


def test_splash_fail_js_escapes_newlines():
    from paper_review.splash import fail_js

    js = fail_js('line1\nline2 "quoted"')
    assert "\\n" in js and "\n" not in js  # real newline would break the JS literal


def test_skills_dir_resolves_inside_a_frozen_bundle(tmp_path, monkeypatch):
    """The .app lays skills out at _MEIPASS/skills, but parents[2] lands one
    level above _MEIPASS — Settings → 스킬 came up empty in the app while the
    browser was fine."""
    from paper_review.server import settings as S

    meipass = tmp_path / "Frameworks"
    (meipass / "skills" / "demo").mkdir(parents=True)
    (meipass / "skills" / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: d\n---\n"
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    assert S._skills_root() == meipass / "skills"

    monkeypatch.delattr(sys, "frozen", raising=False)
    assert S._skills_root().name == "skills"  # source checkout path


def test_bundle_excludes_the_same_characters_git_does():
    """The app bundle used to copy the whole characters folder, so every release
    zip shipped the third-party ones even though git ignored them. The spec's
    list and .gitignore have to agree."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = (root / "packaging" / "paper-review.spec").read_text()
    m = re.search(r"LOCAL_ONLY_CHARACTERS = \(([^)]*)\)", spec, re.S)
    assert m, "spec must declare the exclusion list"
    in_spec = {s.strip().strip('\"\'') for s in m.group(1).split(",") if s.strip()}

    ignored = set(
        re.findall(
            r"static/characters/([a-z0-9]+)\*", (root / ".gitignore").read_text()
        )
    )
    assert in_spec == ignored, f"spec {in_spec} vs .gitignore {ignored}"


def test_local_illustration_groups_merge_over_the_shipped_ones(tmp_path, monkeypatch):
    """A local install keeps its own characters without the repo carrying them."""
    import json

    from paper_review.server import settings as S

    shipped = tmp_path / "groups.json"
    shipped.write_text(json.dumps({"groups": {"vision": ["badger"]}, "tag_groups": {"VLM": "vision"}}))
    local = tmp_path / "groups.local.json"
    local.write_text(json.dumps({"groups": {"vision": ["mine"], "extra": ["other"]}}))
    monkeypatch.setattr(S, "GROUPS_FILE", shipped)
    monkeypatch.setattr(S, "LOCAL_GROUPS_FILE", local)
    # groups only survive if their base names resolve to real files
    monkeypatch.setattr(
        S, "list_illustrations", lambda: ["badger.jpg", "mine.jpg", "other.jpg"]
    )

    g = S.illustration_groups()
    assert set(g["groups"]) >= {"vision", "extra"}
    assert set(g["groups"]["vision"]) == {"badger.jpg", "mine.jpg"}

    local.write_text("{ broken")  # must not take the gallery down
    assert S.illustration_groups()["groups"]["vision"] == ["badger.jpg"]


def test_desktop_window_allows_pinch_zoom(monkeypatch):
    """pywebview defaults zoomable=False and then blocks ctrl+wheel — which is
    what a trackpad pinch sends — so the source PDF couldn't be zoomed."""
    from paper_review import app as A

    seen = {}

    class W:
        def __init__(self):
            self.js, self.url = [], None

        def evaluate_js(self, s):
            self.js.append(s)

    def fake_create_window(title, **kw):
        seen.update(kw)
        return W()

    monkeypatch.setattr(A, "_augment_path", lambda: None)
    monkeypatch.setitem(
        sys.modules,
        "webview",
        type(
            "M",
            (),
            {"create_window": staticmethod(fake_create_window), "start": staticmethod(lambda *a, **k: None)},
        ),
    )
    A.run_app(port=1234)
    assert seen.get("zoomable") is True
