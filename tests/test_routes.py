from fastapi.testclient import TestClient

from paper_review.server.app import app

client = TestClient(app)


def test_read_only_routes_ok():
    for path in ["/", "/tags", "/skills", "/illustrations", "/illustration-groups"]:
        assert client.get(path).status_code == 200, path


def test_unknown_paper_404():
    assert client.get("/paper/definitely-not-a-real-slug").status_code == 404


def test_skill_roundtrip_no_mutation():
    skills = client.get("/skills").json()
    if not skills:
        return
    name = skills[0]["name"]
    md = client.get(f"/skills/{name}").text
    assert md.strip()
    # write the same content back — must succeed and not change the file
    assert client.put(f"/skills/{name}", content=md).status_code == 200
    assert client.get(f"/skills/{name}").text == md


def test_bad_skill_name_404():
    assert client.get("/skills/no_such_skill_xyz").status_code == 404


def test_status_patch_helpers():
    from paper_review.server.tags import STATUSES, _set_status_in_text

    assert "archived" in STATUSES
    t = "---\nslug: x\nstatus: in_progress\n---\n# b\n"
    out = _set_status_in_text(t, "archived")
    assert "status: archived\n" in out and "slug: x" in out
    # inserts when the line is missing
    assert "status: exported" in _set_status_in_text("---\nslug: y\n---\n", "exported")


def test_status_patch_unknown_slug_404():
    r = client.patch(
        "/paper/definitely-not-a-real-slug/status", json={"status": "archived"}
    )
    assert r.status_code == 404


def test_auth_failure_hint():
    from paper_review.server.analyze import AnalysisJob, _hint_auth_failure

    j = AnalysisJob(slug="x", job_id="t")
    _hint_auth_failure("Failed to authenticate: OAuth session expired", j)
    assert any("claude auth login" in l for l in j.log)
    j2 = AnalysisJob(slug="y", job_id="t2")
    _hint_auth_failure("connection reset by peer", j2)
    assert not j2.log


def test_settings_never_returns_the_remote_token():
    s = client.get("/settings").json()
    assert "remote_token" not in s
    assert isinstance(s["remote_token_set"], bool)


def test_settings_panes_save_independently(tmp_path, monkeypatch):
    """Each pane PUTs only its own fields — saving the mobile slot must not
    wipe the publish path, and vice versa."""
    from paper_review import config as C, remote as R

    monkeypatch.setattr(C, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(R, "CONFIG_PATH", tmp_path / "remote.json")
    monkeypatch.delenv("PAPER_REVIEW_REMOTE_URL", raising=False)
    monkeypatch.delenv("PAPER_REVIEW_REMOTE_TOKEN", raising=False)
    monkeypatch.delenv("PAPER_REVIEW_DRAFTS_DIR", raising=False)

    assert (
        client.put("/settings", json={"drafts_dir": "/tmp/vault/drafts"}).status_code
        == 200
    )
    assert (
        client.put(
            "/settings",
            json={"remote_url": "https://a.vercel.app", "remote_token": "t"},
        ).status_code
        == 200
    )

    s = client.get("/settings").json()
    assert s["drafts_dir"] == "/tmp/vault/drafts"  # survived the mobile save
    assert s["remote_url"] == "https://a.vercel.app"
    assert s["remote_token_set"] is True

    # a relative publish path is still rejected
    assert (
        client.put("/settings", json={"drafts_dir": "relative/dir"}).status_code == 400
    )
    # and a URL without a token (none stored yet) is too
    R.save_config("", None)
    assert (
        client.put("/settings", json={"remote_url": "https://a.vercel.app"}).status_code
        == 400
    )


def test_pages_make_room_for_the_traffic_lights_in_the_app():
    """The desktop window runs its content under a transparent titlebar, so both
    pages must detect the app and offset their top strip — otherwise the traffic
    lights land on the sidebar brand / topbar controls."""
    from paper_review.server.app import _STATIC_DIR

    for path in ("/", "/paper/2505.16854"):
        r = client.get(path)
        if r.status_code == 404:
            continue  # that paper isn't in this checkout
        assert 'classList.add("in-app")' in r.text, path

    css = (_STATIC_DIR / "gallery.css").read_text()
    assert "html.in-app .sidebar" in css and "--titlebar-h" in css
    detail = (_STATIC_DIR / "detail.css").read_text()
    assert "html.in-app .topbar" in detail
