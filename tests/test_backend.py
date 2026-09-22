"""The shared model backend: GET/PUT /api/backend, recheck, and that the
token is never echoed back by the API even though it is stored on disk."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from laplaces_hoard.api import create_app
from laplaces_hoard.hoard_link import Link, LinkConfig


@pytest.fixture()
def client(data_dir: Path) -> TestClient:
    # An explicit config with no url/model resolves nothing and never probes
    # the network, so this fixture (unlike test_api.py's) does not touch a
    # loopback port even by accident.
    link = Link(LinkConfig.load(None, env={}, app="laplace"))
    app = create_app(data_dir=data_dir, static_dir=None, port=8812, link=link)
    return TestClient(app, base_url="http://127.0.0.1:8812")


def test_backend_status_reports_only_the_capabilities_the_app_uses(client: TestClient):
    r = client.get("/api/backend")
    assert r.status_code == 200
    body = r.json()
    assert set(body["capabilities"]) == {"llm"}
    assert body["capabilities"]["llm"]["state"] == "unavailable"
    assert body["config"]["token_set"] is False
    assert "sql_engine" in body["app"]


def test_backend_config_persists_without_leaking_the_token(client: TestClient, data_dir: Path):
    r = client.put(
        "/api/backend/config",
        json={
            "faustus_url": "http://127.0.0.1:7999",
            "faustus_token": "ody_secret_value",
            "capabilities": {"llm": {"url": "http://127.0.0.1:9999/v1", "model": "test-model"}},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["token_set"] is True
    assert "ody_secret_value" not in json.dumps(body)

    on_disk = json.loads((data_dir / "backend.json").read_text(encoding="utf-8"))
    assert on_disk["faustus"]["token"] == "ody_secret_value"
    assert on_disk["faustus"]["url"] == "http://127.0.0.1:7999"
    assert on_disk["capabilities"]["llm"]["model"] == "test-model"

    status = client.get("/api/backend").json()
    assert status["config"]["token_set"] is True
    assert "ody_secret_value" not in json.dumps(status)
    # the new explicit capability config now resolves without any probing
    assert status["capabilities"]["llm"]["state"] == "resolved"
    assert status["capabilities"]["llm"]["model"] == "test-model"


def test_backend_config_clears_a_field_with_an_empty_string(client: TestClient, data_dir: Path):
    client.put("/api/backend/config", json={"faustus_token": "ody_secret"})
    assert client.get("/api/backend").json()["config"]["token_set"] is True
    client.put("/api/backend/config", json={"faustus_token": ""})
    assert client.get("/api/backend").json()["config"]["token_set"] is False
    on_disk = json.loads((data_dir / "backend.json").read_text(encoding="utf-8"))
    assert "token" not in on_disk.get("faustus", {})


def test_backend_recheck_returns_the_used_capabilities(client: TestClient):
    r = client.post("/api/backend/recheck")
    assert r.status_code == 200
    assert set(r.json()) == {"llm"}
