"""Regressions found in review: static-file escape, error envelope, 500s."""
import http.client
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient

from laplaces_hoard.api import create_app

from conftest import free_port


@pytest.fixture()
def client(data_dir: Path) -> TestClient:
    app = create_app(data_dir=data_dir, static_dir=None, port=8812)
    return TestClient(app, base_url="http://127.0.0.1:8812", raise_server_exceptions=False)


@pytest.fixture()
def static_server(tmp_path: Path):
    """A real uvicorn server (raw paths must reach the router undecoded by a client)."""
    static = tmp_path / "dist"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("INDEX", encoding="utf-8")
    (static / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("SECRET", encoding="utf-8")
    port = free_port()
    app = create_app(data_dir=tmp_path / "data", static_dir=static, port=port)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield port
    server.should_exit = True
    thread.join(timeout=5)


def _raw_get(port: int, path: str) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.putrequest("GET", path, skip_host=True)
    conn.putheader("Host", f"127.0.0.1:{port}")
    conn.endheaders()
    r = conn.getresponse()
    return r.status, r.read()


@pytest.mark.parametrize(
    "path",
    ["/..%2fsecret.txt", "/%2e%2e/secret.txt", "//etc/hostname", "/%2Fetc%2Fhostname", "/..%5csecret.txt"],
)
def test_spa_fallback_never_serves_files_outside_the_frontend(static_server, path):
    status, body = _raw_get(static_server, path)
    assert b"SECRET" not in body
    assert status == 200 and body == b"INDEX"


def test_spa_still_serves_its_own_files(static_server):
    assert _raw_get(static_server, "/favicon.svg") == (200, b"<svg/>")
    assert _raw_get(static_server, "/data")[1] == b"INDEX"
    status, body = _raw_get(static_server, "/api/nope")
    assert status == 404 and b"not_found" in body


def test_engine_errors_use_the_flat_error_envelope(client):
    r = client.post("/api/agent/calc", json={"expression": "__import__('os')"})
    assert r.status_code == 400
    body = r.json()
    assert set(body) == {"error", "message"}


def test_validation_errors_use_the_flat_error_envelope(client):
    r = client.post("/api/agent/calc", json={"expr": "1"})
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "invalid_arguments"
    assert "expression" in body["message"]


def test_sql_error_is_a_400_with_the_duckdb_message(client, sample_csv):
    client.post("/api/agent/data_register", json={"path": str(sample_csv), "name": "sample"})
    r = client.post("/api/agent/data_query", json={"sql": "SELECT nope FROM sample"})
    assert r.status_code == 400
    assert "nope" in r.json()["message"]


def test_register_after_query_through_the_api(client, sample_csv, tmp_path):
    client.post("/api/agent/data_register", json={"path": str(sample_csv), "name": "sample"})
    client.post("/api/agent/data_query", json={"sql": "SELECT 1"})
    r = client.post("/api/agent/data_register", json={"path": str(sample_csv), "name": "sample_again"})
    assert r.status_code == 200, r.text


def test_app_writes_a_rotating_log(client, data_dir):
    client.post("/api/agent/calc", json={"expression": "1/0"})
    assert (data_dir / "logs" / "app.log").exists()


def test_calc_runs_in_the_worker_with_a_timeout(client):
    r = client.post("/api/agent/calc", json={"expression": "9**9**9**9"})
    assert r.status_code == 400
    assert r.json()["error"] == "calc"
    assert "did not finish" in r.json()["message"]
    assert client.post("/api/agent/calc", json={"expression": "2^10"}).json()["exact"] == "1024"


def test_math_accepts_numeric_matrices_and_caps_timeout(client):
    r = client.post("/api/agent/math", json={"operation": "matrix", "matrix_op": "det", "matrix": [[1, 2], [3, 4.5]]})
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "-3/2"
    r = client.post("/api/agent/math", json={"operation": "simplify", "expression": "x", "timeout": 1e9})
    assert r.status_code == 422


def test_math_infers_the_only_variable(client):
    r = client.post("/api/agent/math", json={"operation": "diff", "expression": "x**3"})
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "3*x**2"
    r = client.post("/api/agent/math", json={"operation": "diff", "expression": "x*y"})
    assert r.status_code == 400 and "variable" in r.json()["message"]


def test_solve_reports_real_roots_as_floats(client):
    r = client.post("/api/agent/math", json={"operation": "solve", "expression": "x**3 - 3*x + 1 = 0"})
    body = r.json()
    assert body["verified"] is True and body["count"] == 3
    roots = sorted(sol["numeric"]["x"] for sol in body["result"])
    assert all(isinstance(v, float) for v in roots)
    assert roots[0] == pytest.approx(-1.879385241571817)


def test_notebook_math_cells_understand_operation_shorthand(client):
    cell = client.post("/api/cells", json={"engine": "math", "input": "factor(x**3 - x)"}).json()
    assert cell["result"]["result"] == "x*(x - 1)*(x + 1)"
    cell = client.post("/api/cells", json={"engine": "math", "input": "x**2 = 9"}).json()
    assert cell["result"]["count"] == 2
    cell = client.post("/api/cells", json={"engine": "units", "input": "5 ft 11 in to cm"}).json()
    assert cell["result"]["to_magnitude"] == pytest.approx(180.34)


def test_rerun_of_a_units_check_reruns_the_check(client):
    first = client.post("/api/units/check", json={"expression": "3 m/s * 2 s"}).json()
    again = client.post(f"/api/log/{first['id']}/rerun").json()
    assert again["dimensionality"] == "[length]"
