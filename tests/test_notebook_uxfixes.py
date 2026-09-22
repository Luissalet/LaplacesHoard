"""Regression from the first user walk (docs/USABILITY_REPORT.md): a failed
notebook cell used to come back as a raw, unhandled 500 (an uncaught
ValueError from parsing "order"), which the notebook UI could not show at
all - the cell simply never appeared, and reappeared empty after reload."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from laplaces_hoard.api import create_app


@pytest.fixture()
def client(data_dir: Path) -> TestClient:
    app = create_app(data_dir=data_dir, static_dir=None, port=8812)
    return TestClient(app, base_url="http://127.0.0.1:8812", raise_server_exceptions=False)


def test_a_bad_math_cell_never_comes_back_as_a_raw_500(client: TestClient):
    resp = client.post("/api/cells", json={"engine": "math", "input": "diff(x**2, x, dos)"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["error"]
    assert "dos" in body["result"]["message"] or "whole number" in body["result"]["message"]
    # and it is visible on reload, not an empty card
    listed = client.get("/api/cells").json()["cells"]
    assert listed[-1]["result"] is not None


def test_a_good_math_cell_with_an_order_still_works(client: TestClient):
    resp = client.post("/api/cells", json={"engine": "math", "input": "diff(x**2, x, 2)"})
    assert resp.status_code == 200
    body = resp.json()
    assert "error" not in (body["result"] or {})
