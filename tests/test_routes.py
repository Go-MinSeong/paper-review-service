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
