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
