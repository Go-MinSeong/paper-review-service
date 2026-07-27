"""Tests must never touch the developer's own paper library.

SERVICE_ROOT defaults to the checkout, and the route tests exercise handlers
that read — and now, for one-time migrations, WRITE — every workbench.md under
it. Running the suite once rewrote 14 real papers. Point the whole suite at a
throwaway root instead; tests that need papers create them there.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolated_service_root(tmp_path, monkeypatch):
    from paper_review.server import app as server_app

    root = tmp_path / "library"
    root.mkdir()
    monkeypatch.setattr(server_app, "SERVICE_ROOT", root)
    monkeypatch.setattr(server_app, "_VIEWS_FILE", root / ".views.json")
    yield root
