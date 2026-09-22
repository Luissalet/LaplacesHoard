from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from laplaces_hoard.api import create_app


@pytest.fixture()
def client(data_dir: Path) -> TestClient:
    app = create_app(data_dir=data_dir, static_dir=None, port=8812)
    return TestClient(app, base_url="http://127.0.0.1:8812")


def test_health_reports_service_slug(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "laplaces-hoard"
    assert body["name"] == "Laplace's Hoard"
    assert body["status"] == "ok"


def test_calc_endpoint_logs_and_returns_id(client: TestClient):
    r = client.post("/api/agent/calc", json={"expression": "2*21"})
    assert r.status_code == 200
    body = r.json()
    assert body["exact"] == "42"
    assert body["id"].startswith("L-")
    assert body["cite"] == f"[{body['id']}]"


def test_bad_expression_returns_structured_400(client: TestClient):
    r = client.post("/api/agent/calc", json={"expression": "__import__('os')"})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "error" in detail and "message" in detail


def test_agent_calls_are_recorded_separately_from_ui_calls(client: TestClient):
    client.post("/api/agent/calc", json={"expression": "1+1"})
    client.post("/api/cells", json={"engine": "calc", "input": "2+2"})
    agent_items = client.get("/api/agent-calls").json()["items"]
    all_items = client.get("/api/log").json()["items"]
    assert len(agent_items) >= 1
    assert all(item["source"] == "agent" for item in agent_items)
    assert len(all_items) >= len(agent_items)


def test_data_pipeline_register_describe_query(client: TestClient, sample_csv: Path):
    r = client.post("/api/agent/data_register", json={"path": str(sample_csv), "name": "sample"})
    assert r.status_code == 200
    r = client.post("/api/agent/data_describe", json={"name": "sample"})
    assert r.status_code == 200
    assert r.json()["row_count"] == 6
    r = client.post("/api/agent/data_query", json={"sql": "SELECT COUNT(*) AS n FROM sample", "limit": 10})
    assert r.status_code == 200
    assert r.json()["rows"][0]["n"] == 6


def test_data_query_rejects_write_statement(client: TestClient, sample_csv: Path):
    client.post("/api/agent/data_register", json={"path": str(sample_csv), "name": "sample"})
    r = client.post("/api/agent/data_query", json={"sql": "DELETE FROM sample"})
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "sql_gate"


def test_notebook_cell_lifecycle(client: TestClient):
    r = client.post("/api/cells", json={"engine": "calc", "input": "3*3"})
    assert r.status_code == 200
    cell = r.json()
    assert cell["result"]["exact"] == "9"
    cells = client.get("/api/cells").json()["cells"]
    assert any(c["id"] == cell["id"] for c in cells)
    r = client.delete(f"/api/cells/{cell['id']}")
    assert r.status_code == 200
    cells_after = client.get("/api/cells").json()["cells"]
    assert not any(c["id"] == cell["id"] for c in cells_after)


def test_rerun_reproduces_the_same_result(client: TestClient):
    r = client.post("/api/agent/calc", json={"expression": "6*7"})
    cid = r.json()["id"]
    r2 = client.post(f"/api/log/{cid}/rerun")
    assert r2.status_code == 200
    assert r2.json()["exact"] == "42"


def test_host_header_guard_blocks_dns_rebinding(data_dir: Path):
    app = create_app(data_dir=data_dir, static_dir=None, port=8812)
    client = TestClient(app, base_url="http://evil.example.com")
    r = client.get("/api/health", headers={"Host": "evil.example.com"})
    assert r.status_code == 403


def test_cross_origin_post_is_blocked(client: TestClient):
    r = client.post(
        "/api/agent/calc",
        json={"expression": "1+1"},
        headers={"Origin": "http://evil.example.com"},
    )
    assert r.status_code == 403


def test_sec_fetch_site_cross_site_is_blocked(client: TestClient):
    r = client.post(
        "/api/agent/calc",
        json={"expression": "1+1"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert r.status_code == 403


def test_plain_get_navigation_still_works_from_any_tab(client: TestClient):
    # GET must not be blocked by the origin/sec-fetch-site checks (only non-GET is).
    r = client.get("/api/health", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 200


def test_stats_endpoint(client: TestClient):
    r = client.post("/api/agent/stats", json={"test": "describe", "data": [1, 2, 3, 4, 5]})
    assert r.status_code == 200
    assert r.json()["mean"] == 3.0


def test_date_calc_endpoint(client: TestClient):
    r = client.post("/api/agent/date_calc", json={"operation": "weekday", "value": "2026-09-22"})
    assert r.status_code == 200
    assert r.json()["weekday"] == "Tuesday"


def test_units_endpoint(client: TestClient):
    r = client.post("/api/agent/units_convert", json={"quantity": "1 mile", "to": "km"})
    assert r.status_code == 200
    assert r.json()["to_magnitude"] == pytest.approx(1.60934, abs=0.001)


def test_math_endpoint_solve(client: TestClient):
    r = client.post("/api/agent/math", json={"operation": "solve", "expression": "x**2 - 9 == 0", "variables": ["x"]})
    assert r.status_code == 200
    assert r.json()["verified"] is True
