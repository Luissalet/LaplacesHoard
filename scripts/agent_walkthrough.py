#!/usr/bin/env python3
"""Walk the agent use cases of docs/USE_CASES.md over real MCP stdio.

It behaves the way a local 27B model driven by Faustus would: it starts
from list_tools, picks tools by their descriptions, chains names and ids
from one result into the next, and when a call fails it reads the error
and tries what the error tells it to. Every call is printed with the size
of its result, and a summary at the end flags anything a small-context,
text-only model would trip on (big results, images it did not ask for,
errors that do not say what to do).

Usage (app already running, test data generated with scripts/uxtest_data.py):
    .venv/bin/python scripts/agent_walkthrough.py http://127.0.0.1:18820 [files_dir]
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = Path(__file__).resolve().parent.parent
BIG_RESULT_CHARS = 6000  # ~1.5k tokens: a lot for one call in an 8k-16k context


class Walker:
    def __init__(self, session: ClientSession):
        self.s = session
        self.calls: list[dict] = []
        self.scenario = ""

    def title(self, text: str) -> None:
        self.scenario = text
        print(f"\n=== {text}")

    def say(self, text: str) -> None:
        print(f"    · {text}")

    async def call(self, tool: str, args: dict) -> tuple[bool, Any, str]:
        t0 = time.perf_counter()
        res = await self.s.call_tool(tool, args)
        ms = (time.perf_counter() - t0) * 1000
        texts = [c.text for c in res.content if getattr(c, "type", "") == "text"]
        images = [c for c in res.content if getattr(c, "type", "") == "image"]
        text = "\n".join(texts)
        img_bytes = sum(len(getattr(c, "data", "")) for c in images)
        parsed: Any = None
        if not res.isError:
            try:
                parsed = json.loads(texts[0]) if texts else None
            except json.JSONDecodeError:
                parsed = texts[0]
            if isinstance(parsed, dict) and "result" in parsed and len(parsed) == 1:
                parsed = parsed["result"]  # structured-output wrapping, if any
        shown = json.dumps(args, ensure_ascii=False)
        shown = shown if len(shown) <= 150 else shown[:147] + "..."
        status = "ERR" if res.isError else "ok "
        extra = f" + IMAGE {img_bytes:,} b64 chars" if images else ""
        print(f"  {status} {tool:13} {shown}")
        print(f"      -> {len(text):,} chars{extra}, {ms:.0f} ms" + (f" | {text[:300]}" if res.isError else ""))
        self.calls.append({"scenario": self.scenario, "tool": tool, "ok": not res.isError, "chars": len(text),
                           "image": bool(images), "image_chars": img_bytes, "ms": ms,
                           "error": text if res.isError else None})
        return (not res.isError), parsed, text

    def summary(self, tools_chars: int) -> None:
        print("\n=== Summary")
        print(f"  list_tools payload: {tools_chars:,} chars (~{tools_chars // 4:,} tokens) before the first call")
        n = len(self.calls)
        errs = [c for c in self.calls if not c["ok"]]
        imgs = [c for c in self.calls if c["image"]]
        big = [c for c in self.calls if c["chars"] > BIG_RESULT_CHARS]
        print(f"  {n} calls, {len(errs)} errors, {len(imgs)} with an image, {len(big)} over {BIG_RESULT_CHARS:,} chars")
        for c in imgs:
            print(f"  IMAGE without being asked: {c['tool']} in '{c['scenario']}' ({c['image_chars']:,} b64 chars)")
        for c in big:
            print(f"  BIG: {c['tool']} in '{c['scenario']}' ({c['chars']:,} chars)")
        for c in errs:
            print(f"  error: {c['tool']}: {c['error'][:160]}")
        by_tool: dict[str, list[int]] = {}
        for c in self.calls:
            by_tool.setdefault(c["tool"], []).append(c["chars"])
        print("  result size by tool (chars, max): " + ", ".join(f"{k} {max(v):,}" for k, v in sorted(by_tool.items())))


def pick(tools: list, *words: str) -> str:
    """Pick a tool the way retrieval over descriptions would: most keyword hits wins."""
    best, score = "", -1
    for t in tools:
        text = (t.name + " " + (t.description or "")).lower()
        s = sum(text.count(w.lower()) for w in words)
        if s > score:
            best, score = t.name, s
    return best


async def uc_bank(w: Walker, tools: list, files: Path) -> None:
    w.title("UC2 agent: '¿Cuánto me gasté en supermercados en 2025, cuánto es al mes y qué parte de la nómina?'")
    tool = pick(tools, "qué datos hay", "lista de datasets")
    w.say(f"retrieval picks {tool} for 'qué datos tengo'")
    ok, res, _ = await w.call(tool, {})
    known = [d["name"] for d in (res or {}).get("datasets", [])] if ok and isinstance(res, dict) else []
    name = "movimientos_2023_2025"
    if name not in known:
        ok, res, _ = await w.call(pick(tools, "cargar este archivo", "importar CSV"),
                                  {"path": str(files / "movimientos_2023-2025.csv")})
        if not ok:
            w.say("registration failed: the model retries under a new name, as a user would")
            ok, res, _ = await w.call("data_register", {"path": str(files / "movimientos_2023-2025.csv"), "name": "movimientos_b"})
            name = "movimientos_b"
        else:
            name = res["name"]
    ok, res, _ = await w.call("data_describe", {"name": name})
    cols = {c["name"]: c["type"] for c in res["columns"]} if ok else {}
    w.say(f"columns: {cols}")
    amount = next((c for c in cols if c.lower().startswith("importe")), "Importe (€)")
    cat = next((c for c in cols if c.lower().startswith("categor")), "Categoría")
    # what a model writes first: a plain SUM
    ok, res, text = await w.call("data_query", {"sql": f'SELECT SUM("{amount}") AS total FROM {name} WHERE "{cat}" = \'Supermercado\''})
    if not ok or cols.get(amount) == "VARCHAR":
        w.say(f"'{amount}' is text ({cols.get(amount)}) - '-1.234,56'. The model has to repair it in SQL itself")
        ok, res, text = await w.call("data_query", {"sql": f'SELECT SUM(CAST("{amount}" AS DOUBLE)) AS total FROM {name}'})
        fixed = f"CAST(replace(replace(\"{amount}\", '.', ''), ',', '.') AS DECIMAL(12,2))"
        ok, res, _ = await w.call("data_query", {"sql": (
            f"SELECT -SUM({fixed}) AS gasto, COUNT(*) AS n, COUNT(DISTINCT month(\"Fecha operación\")) AS meses "
            f"FROM {name} WHERE \"{cat}\" = 'Supermercado' AND year(\"Fecha operación\") = 2025")})
    if ok and res.get("rows"):
        row = res["rows"][0]
        gasto = row.get("gasto") if isinstance(row, dict) else row[0]
        q_cite = res["cite"]
        ok, r1, _ = await w.call(pick(tools, "calcular", "media"), {"expression": f"{gasto} / 12"})
        ok2, r2, _ = await w.call("data_query", {"sql": (
            f"SELECT SUM(CAST(replace(replace(\"{amount}\", '.', ''), ',', '.') AS DECIMAL(12,2))) AS nomina "
            f"FROM {name} WHERE \"{cat}\" = 'Nómina' AND year(\"Fecha operación\") = 2025")})
        if ok2 and r2.get("rows"):
            nom = r2["rows"][0].get("nomina") if isinstance(r2["rows"][0], dict) else r2["rows"][0][0]
            ok3, r3, _ = await w.call("calc", {"expression": f"ratio({gasto}, {nom}) * 100"})
            w.say(f"answer: {gasto} € in supermarkets {q_cite}, {r1.get('decimal') if ok else '?'} €/month "
                  f"{r1.get('cite') if ok else ''}, {r3.get('decimal') if ok3 else '?'} % of payroll {r3.get('cite') if ok3 else ''}")
    # what a Spanish user types back into the chat: "¿y el 21 % de 1.234,56?"
    w.say("the user follows up in Spanish number style; the model passes it through as typed")
    await w.call("calc", {"expression": "pct(21, 1.234,56)"})
    await w.call("calc", {"expression": "1.234,56 * 0,21"})
    ok, res, _ = await w.call("calc", {"expression": "1.000 * 3"})
    if ok:
        w.say(f"'1.000 * 3' (a Spaniard means 3000) returned {res.get('decimal')} with no warning")


async def uc_jobs(w: Walker, tools: list, files: Path) -> None:
    w.title("UC3 agent: 'Faustus, ¿qué tasa de respuesta tengo, y responden menos en remoto?'")
    ok, res, _ = await w.call("data_register", {"path": str(files / "busqueda_empleo_2026.xlsx")})
    if not ok:
        return
    sheets = res.get("sheets", [])
    w.say(f"sheets: {sheets}")
    apps = next((s for s in sheets if "plicaciones" in s), sheets[0])
    ok, d, _ = await w.call("data_describe", {"name": apps})
    cols = {c["name"]: c["type"] for c in d["columns"]} if ok else {}
    w.say(f"columns: {cols}")
    ok, res, _ = await w.call("data_query", {"sql": (
        f"SELECT Modalidad, COUNT(*) AS enviadas, "
        f"SUM(CASE WHEN Estado IN ('Entrevista','Oferta','Rechazada') THEN 1 ELSE 0 END) AS respondidas "
        f"FROM {apps} GROUP BY Modalidad ORDER BY Modalidad")})
    if ok:
        rows = res["rows"]
        w.say(f"rows: {rows}")
        get = (lambda r, k, i: r[k] if isinstance(r, dict) else r[i])
        remote = next((r for r in rows if get(r, "Modalidad", 0) == "Remoto"), None)
        others = [r for r in rows if get(r, "Modalidad", 0) != "Remoto"]
        if remote and others:
            a, b = get(remote, "respondidas", 2), get(remote, "enviadas", 1) - get(remote, "respondidas", 2)
            c = sum(get(r, "respondidas", 2) for r in others)
            dd = sum(get(r, "enviadas", 1) for r in others) - c
            ok, _, err = await w.call(pick(tools, "es significativo", "prueba"),
                                      {"test": "fisher_exact", "data": [[a, b], [c, dd]]})
            if not ok:
                w.say("the description says data = table [[8, 2], [1, 9]], the schema says list of numbers; "
                      "the model tries chi2_contingency the same way")
                await w.call("stats", {"test": "chi2_contingency", "data": [[a, b], [c, dd]]})
            tot_s = sum(get(r, "respondidas", 2) for r in rows)
            tot_n = sum(get(r, "enviadas", 1) for r in rows)
            await w.call("stats", {"test": "proportion_ci", "successes": tot_s, "trials": tot_n})
    date_col = next((c for c in cols if c.lower().startswith("fecha")), "Fecha envío")
    ok, res, _ = await w.call("data_query", {"sql": f'SELECT MAX("{date_col}") AS ultima FROM {apps}'})
    if ok and res.get("rows"):
        last = res["rows"][0]["ultima"] if isinstance(res["rows"][0], dict) else res["rows"][0][0]
        w.say(f"last application: {last!r} (type from describe: {cols.get(date_col)})")
        await w.call(pick(tools, "días laborables", "business days"),
                     {"operation": "business_days", "start": str(last)[:10], "end": "today", "include_end": False})
    entrevistas = next((s for s in sheets if "ntrevistas" in s), None)
    if entrevistas:
        ok, d2, _ = await w.call("data_describe", {"name": entrevistas})
        if ok:
            w.say(f"Entrevistas sheet (has a title row above the header): columns = {[c['name'] for c in d2['columns']]}")


async def uc_funes(w: Walker, tools: list, files: Path) -> None:
    w.title("UC5 agent + Funes: 'Faustus, ¿cuántas horas programé vs. navegué las dos últimas semanas? Hazme un gráfico'")
    ok, res, _ = await w.call("data_register", {"path": str(files / "funes-export.json")})
    if not ok:
        return
    name = res["name"]
    w.say(f"row_count={res.get('row_count')} columns={[c['name'] + ':' + c['type'][:40] for c in res.get('columns', [])]}")
    # a single row of nested lists: the model has to UNNEST it itself
    sql = (f"WITH s AS (SELECT unnest(spans, recursive := true) FROM {name}) "
           "SELECT category, ROUND(SUM(end_ts - start_ts) / 3600, 1) AS horas FROM s GROUP BY category ORDER BY horas DESC")
    ok, res, _ = await w.call("data_query", {"sql": sql})
    if ok:
        w.say(f"hours by category: {res['rows'][:4]}")
        tool = pick(tools, "gráfico", "chart")
        w.say(f"retrieval picks {tool}; the model is text-only and did not ask for an image")
        ok, res, text = await w.call(tool, {"sql": sql, "kind": "bar", "x": "category", "y": "horas",
                                            "title": "Horas por categoría"})
        if ok:
            w.say(f"chart result text: {text[:240]}")


async def uc_daguerre(w: Walker, tools: list, files: Path) -> None:
    w.title("UC7 agent + Daguerre: '¿Qué focal uso más y disparo a ISO más alto con el móvil que con la Sony?'")
    ok, res, _ = await w.call("data_register", {"path": str(files / "daguerre-library.sqlite"), "name": "fotos"})
    if not ok:
        return
    t = res.get("tables", [res.get("name")])[0]
    ok, d, _ = await w.call("data_describe", {"name": t})
    if ok:
        w.say(f"thumb BLOB in profile: {d['profile'].get('thumb')}")
    await w.call("data_query", {"sql": f"SELECT make, focal_length, COUNT(*) AS n FROM {t} GROUP BY ALL ORDER BY n DESC LIMIT 5"})
    await w.call("stats", {"test": "mannwhitneyu", "dataset": t, "column": "iso", "group_by": "make",
                           "where": "make IN ('Apple', 'SONY')"})
    # a model that forgets the where clause: three cameras
    await w.call("stats", {"test": "mannwhitneyu", "dataset": t, "column": "iso", "group_by": "make"})
    await w.call("data_query", {"sql": f"SELECT * FROM {t} LIMIT 3"})


async def uc_bench(w: Walker, tools: list, files: Path) -> None:
    w.title("UC8 agent: '¿Cuánto pierdo de tokens/s por cada 1k de contexto con qwen3-27b?'")
    ok, res, _ = await w.call("data_register", {"path": str(files / "llama_bench.ndjson")})
    if not ok:
        return
    name = res["name"]
    ok, _, err = await w.call("stats", {"test": "linregress", "dataset": name, "column": "ctx", "column2": "tokens_per_s",
                                        "where": "model = 'qwen3-27b-q4_k_m'"})
    if not ok and "equal-length" in err:
        w.say("the error does not say why the lengths differ (NULLs); a model has to guess 'IS NOT NULL'")
        await w.call("stats", {"test": "linregress", "dataset": name, "column": "ctx", "column2": "tokens_per_s",
                               "where": "model = 'qwen3-27b-q4_k_m' AND tokens_per_s IS NOT NULL"})
    ok, r, _ = await w.call("work_log", {"limit": 3, "engine": "stats"})
    if ok and r.get("items"):
        cid = r["items"][0]["id"]
        await w.call("work_log", {"query": cid})


async def uc_errors(w: Walker, tools: list, files: Path) -> None:
    w.title("Error ergonomics: does each error say what to do next?")
    await w.call("data_describe", {"name": "ventas"})
    await w.call("data_query", {"sql": "SELECT importe FROM movimientos_2023_2025"})
    await w.call("data_query", {"sql": "DELETE FROM movimientos_2023_2025"})
    await w.call("units_convert", {"quantity": "3,5 km", "to": "mi"})
    await w.call("units_convert", {"quantity": "180 libras", "to": "kg"})
    await w.call("date_calc", {"operation": "parse", "text": "el próximo lunes"})
    ok, _, _ = await w.call("math", {"operation": "solve", "expression": "x^2 - 5x + 6 = 0"})
    if not ok:
        await w.call("math", {"operation": "solve", "expression": "x^2 - 5*x + 6 = 0"})
    await w.call("data_register", {"path": str(files / "extracto_cuenta_2025.csv")})
    await w.call("data_register", {"path": str(files / "extracto_cuenta_2025.csv"), "options": {"delimiter": ";"}})
    await w.call("data_register", {"path": "C:\\Users\\me\\Downloads\\movimientos.csv"})


async def run(base_url: str, files: Path) -> Walker:
    params = StdioServerParameters(command=sys.executable, args=[str(REPO_ROOT / "laplaces_hoard" / "mcp_server.py")],
                                   env={**os.environ, "LAPLACE_URL": base_url})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            instr = init.instructions or ""
            listed = await session.list_tools()
            tools = listed.tools
            tools_chars = len(json.dumps([t.model_dump(mode="json", exclude_none=True) for t in tools]))
            print(f"server instructions: {len(instr)} chars")
            print(f"{len(tools)} tools:")
            for t in tools:
                props = (t.inputSchema or {}).get("properties", {})
                first = (t.description or "").strip().splitlines()[0]
                print(f"  {t.name:14} {len(t.description or ''):5} chars, {len(props):2} params | {first[:90]}")
            w = Walker(session)
            for uc in (uc_bank, uc_jobs, uc_funes, uc_daguerre, uc_bench, uc_errors):
                try:
                    await uc(w, tools, files)
                except Exception as exc:  # a scenario crash is a finding, not the end of the walk
                    print(f"  !! scenario crashed: {type(exc).__name__}: {exc}")
            w.summary(tools_chars)
            return w


async def dead_app(files: Path) -> None:
    print("\n=== App not running: what does the model see?")
    params = StdioServerParameters(command=sys.executable, args=[str(REPO_ROOT / "laplaces_hoard" / "mcp_server.py")],
                                   env={**os.environ, "LAPLACE_URL": "http://127.0.0.1:18829"})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.call_tool("calc", {"expression": "1+1"})
            print(f"  isError={res.isError}: {res.content[0].text[:200]}")


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18820"
    files = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO_ROOT / "data-uxtest" / "files"
    if not files.is_dir():
        sys.exit(f"{files} missing: run scripts/uxtest_data.py first")
    asyncio.run(run(base_url, files.resolve()))
    asyncio.run(dead_app(files))


if __name__ == "__main__":
    main()
