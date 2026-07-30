"""Update check: a chip in the corner, never a blocked page or a false alarm."""

import httpx
import pytest

from paper_review import update as U


@pytest.fixture(autouse=True)
def _clear_cache():
    U._cache.update(at=0.0, value=None)
    yield
    U._cache.update(at=0.0, value=None)


def _stub(monkeypatch, *, tag="v9.9.9", status=200, boom=False):
    def fake_get(url, **kw):
        if boom:
            raise httpx.ConnectError("offline")
        return httpx.Response(
            status,
            json={
                "tag_name": tag,
                "html_url": f"https://example.test/{tag}",
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(U.httpx if hasattr(U, "httpx") else httpx, "get", fake_get)
    import sys

    monkeypatch.setitem(sys.modules, "httpx", type("M", (), {"get": staticmethod(fake_get)}))


def test_flags_a_newer_release(monkeypatch):
    _stub(monkeypatch, tag="v99.0.0")
    out = U.check(force=True)
    assert out["newer"] is True and out["latest"] == "99.0.0"
    assert out["url"].endswith("v99.0.0")


def test_same_or_older_release_is_not_an_update(monkeypatch):
    from paper_review import __version__

    _stub(monkeypatch, tag=f"v{__version__}")
    assert U.check(force=True)["newer"] is False
    _stub(monkeypatch, tag="v0.0.1")
    assert U.check(force=True)["newer"] is False


def test_offline_and_errors_never_nag(monkeypatch):
    _stub(monkeypatch, boom=True)
    out = U.check(force=True)
    assert out["newer"] is False and out["latest"] is None
    _stub(monkeypatch, status=403)  # rate limited
    assert U.check(force=True)["newer"] is False


def test_unparsable_versions_are_ignored(monkeypatch):
    _stub(monkeypatch, tag="nightly")
    assert U.check(force=True)["newer"] is False
    assert U._parse("2.17.0.dev1") is None  # a dev build never claims to differ


def test_result_is_cached(monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return httpx.Response(
            200,
            json={"tag_name": "v99.0.0", "html_url": "x"},
            request=httpx.Request("GET", url),
        )

    import sys

    monkeypatch.setitem(sys.modules, "httpx", type("M", (), {"get": staticmethod(fake_get)}))
    U.check(force=True)
    U.check()
    U.check()
    assert len(calls) == 1, "the gallery calls this on every load"


def test_route_exposes_the_check():
    from fastapi.testclient import TestClient

    from paper_review.server.app import app

    r = TestClient(app).get("/update")
    assert r.status_code == 200
    assert set(r.json()) == {"current", "latest", "url", "newer"}
