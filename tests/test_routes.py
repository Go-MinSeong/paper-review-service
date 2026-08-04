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


def test_papers_json_lets_an_open_window_refresh():
    """The gallery embeds its list at render time; the desktop app has no
    address bar, so a window left open must be able to re-read it."""
    r = client.get("/papers.json")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    if rows:
        assert {"slug", "status", "tags"} <= set(rows[0])


def test_gallery_refreshes_on_focus():
    from paper_review.server.app import _STATIC_DIR

    js = (_STATIC_DIR / "gallery.js").read_text()
    assert "'/papers.json'" in js
    assert "addEventListener('focus'" in js and "visibilitychange" in js
    # the list has to be reassignable for the refresh to land
    assert "let papers = JSON.parse" in js


def test_delete_moves_to_trash_and_save_keeps_history(tmp_path, monkeypatch):
    """The review is the product: deleting a card and saving over it were both
    one-way doors."""
    import paper_review.server.app as A

    import paper_review

    monkeypatch.setattr(paper_review, "SERVICE_ROOT", tmp_path)
    monkeypatch.setattr(A, "SERVICE_ROOT", tmp_path)
    d = tmp_path / "2600.99999"
    d.mkdir()
    (d / "workbench.md").write_text("---\nstatus: in_progress\n---\n# v1\n")

    # saving keeps the previous text
    r = client.put("/paper/2600.99999/workbench.md", json={"text": "# v2\n"})
    assert r.status_code == 200
    snaps = list((d / ".history").glob("workbench-*.md"))
    assert len(snaps) == 1 and "# v1" in snaps[0].read_text()
    assert (d / "workbench.md").read_text() == "# v2\n"

    # …and only the last few, so it can't grow without bound
    for i in range(3, 12):
        import os, time

        os.utime(d / "workbench.md", (time.time() + i, time.time() + i))
        client.put("/paper/2600.99999/workbench.md", json={"text": f"# v{i}\n"})
    assert len(list((d / ".history").glob("workbench-*.md"))) <= A._HISTORY_KEEP

    # deleting moves the folder aside instead of destroying it
    assert client.delete("/paper/2600.99999").status_code == 200
    assert not d.exists()
    moved = list((tmp_path / "_trash").glob("2600.99999-*"))
    assert len(moved) == 1 and (moved[0] / "workbench.md").exists()


def test_paper_rows_are_cached_until_the_file_changes(tmp_path, monkeypatch):
    """Building a row parses workbench.md and a figures JSON that can be several
    MB — at 100+ papers that ran on every gallery load."""
    import json as _json
    import paper_review.server.app as A

    import paper_review

    monkeypatch.setattr(paper_review, "SERVICE_ROOT", tmp_path)
    monkeypatch.setattr(A, "SERVICE_ROOT", tmp_path)
    A._ROW_CACHE.clear()
    d = tmp_path / "2600.88888"
    d.mkdir()
    (d / "workbench.md").write_text('---\nstatus: to_read\ntitle_en: "One"\n---\n')
    (d / "2600.88888_figures.json").write_text(_json.dumps([{"id": "f1"}]))

    assert A._list_papers()[0]["title_en"] == "One"
    parses = []
    real = A._read_frontmatter
    monkeypatch.setattr(
        A, "_read_frontmatter", lambda p: (parses.append(p), real(p))[1]
    )

    A._list_papers()
    assert parses == [], "unchanged papers must not be re-read"

    import os, time

    (d / "workbench.md").write_text('---\nstatus: to_read\ntitle_en: "Two"\n---\n')
    os.utime(d / "workbench.md", (time.time() + 5, time.time() + 5))
    assert A._list_papers()[0]["title_en"] == "Two", "an edit must invalidate it"
    assert parses, "…by actually re-reading the file"


def test_report_can_be_downloaded_as_a_file():
    """The desktop app can't print the report — pywebview's window.print()
    prints the top-level web view and the report lives in an iframe, so the
    export button did nothing there. A file download always works."""
    import paper_review.server.app as A

    slugs = [p["slug"] for p in A._list_papers()]
    target = next(
        (s for s in slugs if (A.SERVICE_ROOT / s / "report.html").exists()), None
    )
    if not target:
        return  # no report in this checkout
    plain = client.get(f"/paper/{target}/report")
    assert "content-disposition" not in plain.headers  # inline for the iframe
    dl = client.get(f"/paper/{target}/report", params={"download": 1})
    assert dl.status_code == 200
    assert (
        dl.headers["content-disposition"]
        == f'attachment; filename="{target}-report.html"'
    )
    assert dl.content == plain.content


def test_summary_without_a_report_shows_the_report_outline():
    """Summary used to fall back to the workbench with the excerpt/translation
    hidden — the pre-2.4 idea of a summary. A newly registered paper therefore
    showed 파이프라인 / Wrap-up / 메타 / 요약, structure that was retired, and only
    Generate Report made it current."""
    from paper_review.server.app import _STATIC_DIR

    js = (_STATIC_DIR / "detail.js").read_text()
    assert "renderSummaryPlaceholder" in js
    assert "REPORT_OUTLINE" in js
    for sec in ("TL;DR", "개념", "배경", "방법론", "실험", "한계", "후속 연구"):
        assert sec in js, sec
    # the fallback must not render the workbench any more
    i = js.index("No report yet.")
    block = js[i : i + 900]  # the explanatory comment is long
    assert 'style.display = "none"' in block
    # papers analyzed before the block consolidation still count as analyzed
    assert "wb-label-summary" in js and "wb-label-translation" in js


def test_table_figures_never_render_as_broken_images(tmp_path):
    """Tables are extracted as HTML, so /fig/<tbl> has no bytes: a report that
    referenced one with <img> showed a broken image where the table belonged."""
    import json as _json
    import paper_review.server.app as A

    d = tmp_path / "2600.77777"
    d.mkdir()
    (d / "2600.77777_figures.json").write_text(
        _json.dumps([{"id": "tbl1", "html": "<table><tr><td>8192</td></tr></table>"}])
    )
    out = A._inline_table_figs(
        '<p>x</p><img class="paper-fig" src="/paper/2600.77777/fig/tbl1">', d
    )
    assert "<img" not in out and "8192" in out
    # image figures must be left alone
    assert "<img" in A._inline_table_figs('<img src="/paper/x/fig/tbl9">', d)


def test_the_printable_report_is_a_top_level_page_with_a_way_back(
    tmp_path, monkeypatch
):
    """WKWebView prints only the top-level web view, so the app navigates to the
    report to export it — which strands the user unless the page links back."""
    import paper_review.server.app as A
    from fastapi.testclient import TestClient

    d = tmp_path / "2600.66666"
    d.mkdir()
    (d / "workbench.md").write_text("---\nstatus: to_read\n---\n")
    (d / "report.html").write_text("<html><body><h1>R</h1></body></html>")
    monkeypatch.setattr(A, "_paper_dir", lambda slug: d)
    c = TestClient(A.app)

    plain = c.get("/paper/2600.66666/report").text
    assert "pr-printbar" not in plain, "the embedded iframe must stay clean"

    printable = c.get("/paper/2600.66666/report?print=1").text
    assert "window.print()" in printable
    assert 'href="/paper/2600.66666"' in printable, "no way back to the review"
