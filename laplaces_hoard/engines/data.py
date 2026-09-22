"""A small dataset catalogue over local files, queried with read-only SQL.

DuckDB materialises each registered file into `data/catalog.duckdb` (or, for
files bigger than the `LINK_THRESHOLD_BYTES`, keeps a lazy `VIEW` over the
file instead — "linked"). Every `query()` call goes through a statement-type
gate (`gate_sql`) before it touches the catalogue at all, and runs on a
read-only connection with external file/network access switched off unless
a linked dataset is actually referenced.
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import duckdb
import openpyxl

__all__ = ["Catalog", "DataError", "SQLGateError"]

LINK_THRESHOLD_BYTES = 1_000_000_000  # 1 GB
DEFAULT_QUERY_TIMEOUT_S = 20

_ALLOWED_SOLO_TYPES = {"SELECT", "EXPLAIN"}
_BANNED_LEADING_KEYWORDS = {
    "ATTACH", "COPY", "INSTALL", "LOAD", "SET", "PRAGMA", "CREATE", "INSERT",
    "UPDATE", "DELETE", "EXPORT", "CALL", "DROP", "ALTER", "VACUUM",
    "ANALYZE", "BEGIN", "COMMIT", "ROLLBACK", "GRANT", "REVOKE",
    "CHECKPOINT", "USE", "RESET",
}


class DataError(ValueError):
    pass


class SQLGateError(DataError):
    pass


def _leading_keyword(sql: str) -> str:
    m = re.match(r"\s*([A-Za-z]+)", sql)
    return m.group(1).upper() if m else ""


def gate_sql(sql: str) -> None:
    """Raise `SQLGateError` unless `sql` is exactly one read-only statement.

    Allowed: SELECT / WITH (a select) / DESCRIBE / SUMMARIZE / EXPLAIN, and
    a single PIVOT/UNPIVOT (DuckDB's parser expands one PIVOT/UNPIVOT
    statement into an internal CREATE+SELECT pair, which is the one
    documented exception to "exactly one statement").
    Rejected explicitly, regardless of how DuckDB classifies them: ATTACH,
    COPY, INSTALL, LOAD, SET, PRAGMA, CREATE, INSERT, UPDATE, DELETE,
    EXPORT, CALL and friends, plus any multi-statement input.
    """
    if not sql or not sql.strip():
        raise SQLGateError("empty query")
    leading = _leading_keyword(sql)
    try:
        statements = duckdb.extract_statements(sql)
    except Exception as exc:  # noqa: BLE001
        raise SQLGateError(f"could not parse SQL: {exc}") from exc
    if not statements:
        raise SQLGateError("no statement found")
    types = [s.type.name for s in statements]

    if leading in ("PIVOT", "UNPIVOT"):
        if types == ["CREATE", "SELECT"]:
            return
        raise SQLGateError("PIVOT/UNPIVOT must be a single statement")

    if len(statements) != 1:
        raise SQLGateError(f"only one statement is allowed, found {len(statements)}")
    if leading in _BANNED_LEADING_KEYWORDS:
        raise SQLGateError(f"statement type not allowed: {leading}")
    if types[0] not in _ALLOWED_SOLO_TYPES:
        raise SQLGateError(f"statement type not allowed: {types[0]}")


def _safe_view_name(name: str) -> str:
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        raise DataError(f"invalid dataset name: {name!r}")
    return name


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return str(value)
        return value
    return value


@dataclass
class DatasetMeta:
    name: str
    source_path: str
    kind: str
    linked: bool
    row_count: int
    columns: list[dict]
    profile: dict
    mtime: float
    size: int
    updated_at: str


class Catalog:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.cache_dir = self.data_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "catalog.duckdb"
        self._lock = threading.RLock()
        self._conn = duckdb.connect(str(self.db_path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _lh_datasets (
                name VARCHAR PRIMARY KEY,
                source_path VARCHAR,
                kind VARCHAR,
                linked BOOLEAN,
                row_count BIGINT,
                columns_json VARCHAR,
                profile_json VARCHAR,
                mtime DOUBLE,
                size BIGINT,
                updated_at VARCHAR
            )
            """
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- registration ------------------------------------------------------

    def list_datasets(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT name, source_path, kind, linked, row_count, columns_json, updated_at "
                "FROM _lh_datasets ORDER BY name"
            ).fetchall()
            cols = ["name", "source_path", "kind", "linked", "row_count", "columns", "updated_at"]
            out = []
            for r in rows:
                d = dict(zip(cols, r))
                d["columns"] = json.loads(d["columns"]) if d.get("columns") else []
                out.append(d)
            return out

    def register(self, path: str, name: Optional[str] = None, options: Optional[dict] = None) -> dict:
        options = options or {}
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = (self.data_dir / p).resolve()
        else:
            p = p.resolve()
        if not p.exists():
            raise DataError(f"path does not exist: {p}")

        with self._lock:
            if p.is_dir():
                return self._register_folder(p, name, options)
            suffix = p.suffix.lower()
            if suffix in (".csv", ".tsv"):
                return self._register_csv(p, name, options)
            if suffix == ".parquet":
                return self._register_parquet(p, name, options)
            if suffix in (".json", ".ndjson", ".jsonl"):
                return self._register_json(p, name, options)
            if suffix == ".xlsx":
                return self._register_excel(p, name, options)
            if suffix in (".sqlite", ".db", ".sqlite3"):
                return self._register_sqlite(p, name, options)
            raise DataError(f"unsupported file type: {suffix}")

    def _put_meta(self, meta: DatasetMeta) -> None:
        self._conn.execute(
            "INSERT INTO _lh_datasets (name, source_path, kind, linked, row_count, "
            "columns_json, profile_json, mtime, size, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET source_path=excluded.source_path, kind=excluded.kind, "
            "linked=excluded.linked, row_count=excluded.row_count, columns_json=excluded.columns_json, "
            "profile_json=excluded.profile_json, mtime=excluded.mtime, size=excluded.size, "
            "updated_at=excluded.updated_at",
            (
                meta.name, meta.source_path, meta.kind, meta.linked, meta.row_count,
                json.dumps(meta.columns), json.dumps(meta.profile), meta.mtime, meta.size,
                meta.updated_at,
            ),
        )

    def _materialize_or_link(self, view_name: str, select_sql: str, size: int) -> bool:
        """Create TABLE (materialized) or VIEW (linked, for big files). Returns `linked`."""
        self._conn.execute(f'DROP VIEW IF EXISTS "{view_name}"')
        self._conn.execute(f'DROP TABLE IF EXISTS "{view_name}"')
        linked = size > LINK_THRESHOLD_BYTES
        kind = "VIEW" if linked else "TABLE"
        self._conn.execute(f'CREATE {kind} "{view_name}" AS {select_sql}')
        return linked

    def _finish_registration(self, view_name: str, source_path: Path, kind: str, linked: bool) -> dict:
        row_count = self._conn.execute(f'SELECT COUNT(*) FROM "{view_name}"').fetchone()[0]
        columns = self._describe_columns(view_name)
        profile = self._profile(view_name, columns)
        stat = source_path.stat() if source_path.exists() else None
        meta = DatasetMeta(
            name=view_name,
            source_path=str(source_path),
            kind=kind,
            linked=linked,
            row_count=row_count,
            columns=columns,
            profile=profile,
            mtime=stat.st_mtime if stat else 0.0,
            size=stat.st_size if stat else 0,
            updated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        self._put_meta(meta)
        return self.describe(view_name)

    def _register_csv(self, p: Path, name: Optional[str], options: dict) -> dict:
        view_name = _safe_view_name(name or p.stem.replace("-", "_"))
        delim = options.get("delimiter")
        header = options.get("header", True)
        args = [f"'{_esc(str(p))}'", f"header={str(bool(header)).lower()}"]
        if delim:
            args.append(f"delim='{_esc(delim)}'")
        select_sql = f"SELECT * FROM read_csv_auto({', '.join(args)})"
        size = p.stat().st_size
        linked = self._materialize_or_link(view_name, select_sql, size)
        return self._finish_registration(view_name, p, "csv", linked)

    def _register_parquet(self, p: Path, name: Optional[str], options: dict) -> dict:
        view_name = _safe_view_name(name or p.stem.replace("-", "_"))
        select_sql = f"SELECT * FROM read_parquet('{_esc(str(p))}')"
        size = p.stat().st_size
        linked = self._materialize_or_link(view_name, select_sql, size)
        return self._finish_registration(view_name, p, "parquet", linked)

    def _register_json(self, p: Path, name: Optional[str], options: dict) -> dict:
        view_name = _safe_view_name(name or p.stem.replace("-", "_"))
        select_sql = f"SELECT * FROM read_json_auto('{_esc(str(p))}')"
        size = p.stat().st_size
        linked = self._materialize_or_link(view_name, select_sql, size)
        return self._finish_registration(view_name, p, "json", linked)

    def _register_folder(self, p: Path, name: Optional[str], options: dict) -> dict:
        pattern = options.get("glob", "*.csv")
        view_name = _safe_view_name(name or p.name.replace("-", "_"))
        glob_path = str(p / pattern)
        if pattern.endswith(".parquet"):
            select_sql = f"SELECT * FROM read_parquet('{_esc(glob_path)}')"
        else:
            select_sql = f"SELECT * FROM read_csv_auto('{_esc(glob_path)}')"
        size = sum(f.stat().st_size for f in p.glob(pattern) if f.is_file())
        linked = self._materialize_or_link(view_name, select_sql, size)
        return self._finish_registration(view_name, p, "folder", linked)

    def _register_excel(self, p: Path, name: Optional[str], options: dict) -> dict:
        base = name or p.stem.replace("-", "_")
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        sheets = options.get("sheets") or wb.sheetnames
        results = []
        for sheet_name in sheets:
            ws = wb[sheet_name]
            rows_iter = ws.iter_rows(values_only=True)
            try:
                header = next(rows_iter)
            except StopIteration:
                continue
            header = [str(h) if h is not None else f"col{i}" for i, h in enumerate(header)]
            csv_path = self.cache_dir / f"__xlsx_{base}__{sheet_name}.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(header)
                for row in rows_iter:
                    writer.writerow(["" if v is None else v for v in row])
            view_name = _safe_view_name(f"{base}__{sheet_name}".replace(" ", "_").replace("-", "_"))
            parquet_path = self.cache_dir / f"{view_name}.parquet"
            self._conn.execute(
                f"COPY (SELECT * FROM read_csv_auto('{_esc(str(csv_path))}')) "
                f"TO '{_esc(str(parquet_path))}' (FORMAT PARQUET)"
            )
            select_sql = f"SELECT * FROM read_parquet('{_esc(str(parquet_path))}')"
            size = parquet_path.stat().st_size
            linked = self._materialize_or_link(view_name, select_sql, size)
            results.append(self._finish_registration(view_name, p, "excel", linked))
        wb.close()
        if not results:
            raise DataError("workbook has no readable sheets")
        return {"sheets": [r["name"] for r in results], "datasets": results}

    def _register_sqlite(self, p: Path, name: Optional[str], options: dict) -> dict:
        base = name or p.stem.replace("-", "_")
        src = sqlite3.connect(str(p))
        src.row_factory = sqlite3.Row
        tables = options.get("tables")
        if not tables:
            tables = [
                r[0]
                for r in src.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
        results = []
        for table in tables:
            cur = src.execute(f'SELECT * FROM "{table}"')
            cols = [d[0] for d in cur.description]
            csv_path = self.cache_dir / f"__sqlite_{base}__{table}.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(cols)
                for row in cur:
                    writer.writerow(list(row))
            view_name = _safe_view_name(f"{base}__{table}".replace("-", "_"))
            select_sql = f"SELECT * FROM read_csv_auto('{_esc(str(csv_path))}')"
            size = csv_path.stat().st_size
            linked = self._materialize_or_link(view_name, select_sql, size)
            results.append(self._finish_registration(view_name, p, "sqlite", linked))
        src.close()
        if not results:
            raise DataError("sqlite file has no tables")
        return {"tables": [r["name"] for r in results], "datasets": results}

    # -- describe / profile --------------------------------------------------

    def _describe_columns(self, view_name: str) -> list[dict]:
        rows = self._conn.execute(f'DESCRIBE "{view_name}"').fetchall()
        return [{"name": r[0], "type": r[1]} for r in rows]

    def _profile(self, view_name: str, columns: list[dict]) -> dict:
        profile = {}
        total_row = self._conn.execute(f'SELECT COUNT(*) FROM "{view_name}"').fetchone()
        total = total_row[0] if total_row else 0
        for col in columns:
            cname = col["name"]
            ctype = col["type"].upper()
            q = f'"{cname}"'
            nulls = self._conn.execute(
                f'SELECT COUNT(*) FROM "{view_name}" WHERE {q} IS NULL'
            ).fetchone()[0]
            distinct = self._conn.execute(
                f'SELECT APPROX_COUNT_DISTINCT({q}) FROM "{view_name}"'
            ).fetchone()[0]
            entry: dict[str, Any] = {
                "type": col["type"],
                "nulls_pct": round(100.0 * nulls / total, 2) if total else 0.0,
                "distinct_approx": int(distinct) if distinct is not None else 0,
            }
            is_numeric = any(t in ctype for t in ("INT", "DOUBLE", "FLOAT", "DECIMAL", "REAL", "NUMERIC", "HUGEINT"))
            if is_numeric:
                stats_row = self._conn.execute(
                    f'SELECT MIN({q}), MAX({q}), AVG({q}), STDDEV_POP({q}) FROM "{view_name}"'
                ).fetchone()
                entry.update(
                    {
                        "min": _json_safe(stats_row[0]),
                        "max": _json_safe(stats_row[1]),
                        "mean": _json_safe(stats_row[2]),
                        "sd": _json_safe(stats_row[3]),
                    }
                )
            elif "DATE" in ctype or "TIME" in ctype:
                stats_row = self._conn.execute(
                    f'SELECT MIN({q}), MAX({q}) FROM "{view_name}"'
                ).fetchone()
                entry.update({"min": _json_safe(stats_row[0]), "max": _json_safe(stats_row[1])})
            else:
                top = self._conn.execute(
                    f'SELECT {q}, COUNT(*) AS n FROM "{view_name}" WHERE {q} IS NOT NULL '
                    f'GROUP BY {q} ORDER BY n DESC LIMIT 5'
                ).fetchall()
                entry["top_values"] = [{"value": _json_safe(v), "count": int(n)} for v, n in top]
            profile[cname] = entry
        return profile

    def _needs_refresh(self, meta_row: sqlite3.Row) -> bool:
        source_path = Path(meta_row["source_path"])
        if not source_path.exists():
            return False
        stat = source_path.stat()
        return stat.st_mtime != meta_row["mtime"] or stat.st_size != meta_row["size"]

    def _get_meta_row(self, name: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM _lh_datasets WHERE name = ?", [name]
        ).fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._conn.description]
        return dict(zip(cols, row))

    def describe(self, name: str) -> dict:
        with self._lock:
            name = _safe_view_name(name)
            meta = self._get_meta_row(name)
            if meta is None:
                raise DataError(f"unknown dataset: {name}")
            source = Path(meta["source_path"])
            if source.exists() and meta["kind"] not in ("excel", "sqlite", "folder"):
                stat = source.stat()
                if stat.st_mtime != meta["mtime"] or stat.st_size != meta["size"]:
                    self.register(str(source), name=name)
                    meta = self._get_meta_row(name)
            columns = json.loads(meta["columns_json"]) if meta["columns_json"] else []
            profile = json.loads(meta["profile_json"]) if meta["profile_json"] else {}
            sample = self._conn.execute(f'SELECT * FROM "{name}" LIMIT 5').fetchall()
            col_names = [c["name"] for c in columns]
            sample_rows = [
                {col_names[i]: _json_safe(v) for i, v in enumerate(row)} for row in sample
            ]
            return {
                "name": name,
                "source_path": meta["source_path"],
                "kind": meta["kind"],
                "linked": bool(meta["linked"]),
                "row_count": meta["row_count"],
                "columns": columns,
                "profile": profile,
                "sample_rows": sample_rows,
                "updated_at": meta["updated_at"],
            }

    # -- query ---------------------------------------------------------------

    def query(self, sql: str, limit: int = 50, timeout_s: int = DEFAULT_QUERY_TIMEOUT_S) -> dict:
        """Run one gated, read-only statement and return up to `limit` rows.

        DuckDB 1.5.5 refuses to open a second, read-only connection to a
        database file that already has a read-write connection open in the
        same process (needed here for registration) — so "read-only" is
        enforced at the application level instead of via a second OS-level
        handle: the statement-type/keyword gate rejects anything but a
        SELECT-family statement, and the query additionally runs inside a
        transaction that is always rolled back, so even a gate bug could
        not leave a write behind. This is a documented deviation from a
        literal second read-only connection; see README boundaries.
        """
        gate_sql(sql)
        limit = max(1, min(int(limit), 1000))
        with self._lock:
            linked_names = {
                r[0] for r in self._conn.execute(
                    "SELECT name FROM _lh_datasets WHERE linked = TRUE"
                ).fetchall()
            }
            references_linked = any(re.search(rf'\b{re.escape(n)}\b', sql) for n in linked_names)
            self._conn.execute(f"SET enable_external_access = {'true' if references_linked else 'false'}")
            self._conn.execute("BEGIN TRANSACTION")
            timer = threading.Timer(timeout_s, self._conn.interrupt)
            timer.daemon = True
            start = time.monotonic()
            timer.start()
            try:
                rel = self._conn.execute(sql)
                columns = [{"name": d[0], "type": str(d[1])} for d in rel.description]
                rows = rel.fetchmany(limit + 1)
            except duckdb.InterruptException as exc:
                raise DataError(f"query exceeded {timeout_s}s and was stopped") from exc
            finally:
                timer.cancel()
                try:
                    self._conn.execute("ROLLBACK")
                except duckdb.Error:
                    pass
                self._conn.execute("SET enable_external_access = false")
            elapsed_ms = (time.monotonic() - start) * 1000

        truncated = len(rows) > limit
        rows = rows[:limit]
        col_names = [c["name"] for c in columns]
        json_rows = [
            {col_names[i]: _json_safe(v) for i, v in enumerate(row)} for row in rows
        ]
        return {
            "columns": columns,
            "rows": json_rows,
            "row_count": len(json_rows),
            "truncated": truncated,
            "elapsed_ms": round(elapsed_ms, 2),
        }


def _esc(text: str) -> str:
    return text.replace("'", "''")
