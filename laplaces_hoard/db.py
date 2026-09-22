"""SQLite state: work log (computations), notebook cells, settings.

Stdlib sqlite3 only, WAL mode. No FastAPI imports here: this module is
part of the core and is used directly by both the HTTP layer and tests.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS computations (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT UNIQUE NOT NULL,
    engine TEXT NOT NULL,
    operation TEXT NOT NULL,
    input_json TEXT NOT NULL,
    output_json TEXT,
    ok INTEGER NOT NULL,
    error TEXT,
    elapsed_ms REAL NOT NULL,
    source TEXT NOT NULL,
    chart_path TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_computations_engine ON computations(engine);
CREATE INDEX IF NOT EXISTS idx_computations_source ON computations(source);

CREATE TABLE IF NOT EXISTS cells (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    engine TEXT NOT NULL,
    input TEXT NOT NULL,
    result_json TEXT,
    position INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_local = threading.local()
_lock = threading.Lock()


def connect(data_dir: Path) -> sqlite3.Connection:
    """Open (or create) the app database with WAL mode and row access by name."""
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "app.sqlite"
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    with _lock:
        conn.executescript(_SCHEMA)
        conn.commit()
    return conn


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _next_id(conn: sqlite3.Connection) -> str:
    cur = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM computations")
    n = cur.fetchone()["n"]
    return f"L-{n:06d}"


def log_computation(
    conn: sqlite3.Connection,
    *,
    engine: str,
    operation: str,
    input_data: Any,
    output_data: Any,
    ok: bool,
    error: Optional[str],
    elapsed_ms: float,
    source: str,
    chart_path: Optional[str] = None,
) -> str:
    with _lock:
        cid = _next_id(conn)
        conn.execute(
            "INSERT INTO computations "
            "(id, engine, operation, input_json, output_json, ok, error, elapsed_ms, source, chart_path, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                cid,
                engine,
                operation,
                json.dumps(input_data, default=str)[:20000],
                json.dumps(output_data, default=str)[:20000] if output_data is not None else None,
                1 if ok else 0,
                error,
                elapsed_ms,
                source,
                chart_path,
                _now(),
            ),
        )
        conn.commit()
    return cid


def get_computation(conn: sqlite3.Connection, cid: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM computations WHERE id = ?", (cid,)).fetchone()
    return _row_to_dict(row) if row else None


def list_computations(
    conn: sqlite3.Connection,
    *,
    limit: int = 10,
    engine: Optional[str] = None,
    query: Optional[str] = None,
    source: Optional[str] = None,
) -> list[dict]:
    sql = "SELECT * FROM computations WHERE 1=1"
    params: list[Any] = []
    if engine:
        sql += " AND engine = ?"
        params.append(engine)
    if source:
        sql += " AND source = ?"
        params.append(source)
    if query:
        sql += " AND (operation LIKE ? OR input_json LIKE ? OR id = ?)"
        like = f"%{query}%"
        params.extend([like, like, query])
    sql += " ORDER BY seq DESC LIMIT ?"
    params.append(max(1, min(limit, 200)))
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for key in ("input_json", "output_json"):
        if d.get(key):
            try:
                d[key[: -len("_json")]] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                d[key[: -len("_json")]] = None
        else:
            d[key[: -len("_json")]] = None
        d.pop(key, None)
    d["ok"] = bool(d["ok"])
    return d


# --- notebook cells -------------------------------------------------------

def list_cells(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM cells ORDER BY position ASC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["result"] = json.loads(d["result_json"]) if d.get("result_json") else None
        d.pop("result_json", None)
        out.append(d)
    return out


def add_cell(conn: sqlite3.Connection, *, engine: str, input_text: str) -> dict:
    with _lock:
        pos_row = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM cells").fetchone()
        pos = pos_row["p"]
        now = _now()
        cur = conn.execute(
            "INSERT INTO cells (engine, input, result_json, position, created_at, updated_at) "
            "VALUES (?, ?, NULL, ?, ?, ?)",
            (engine, input_text, pos, now, now),
        )
        conn.commit()
        cell_id = cur.lastrowid
    return {"id": cell_id, "engine": engine, "input": input_text, "result": None, "position": pos}


def update_cell(conn: sqlite3.Connection, cell_id: int, *, result: Any) -> None:
    with _lock:
        conn.execute(
            "UPDATE cells SET result_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(result, default=str), _now(), cell_id),
        )
        conn.commit()


def delete_cell(conn: sqlite3.Connection, cell_id: int) -> bool:
    with _lock:
        cur = conn.execute("DELETE FROM cells WHERE id = ?", (cell_id,))
        conn.commit()
        return cur.rowcount > 0


# --- settings --------------------------------------------------------------

def get_setting(conn: sqlite3.Connection, key: str, default: Optional[str] = None) -> Optional[str]:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    with _lock:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
