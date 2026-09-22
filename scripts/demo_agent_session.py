#!/usr/bin/env python3
"""Drive the real MCP adapter against a running app, like an assistant would.

Used to put genuine assistant calls into a demo instance before taking
screenshots: every call goes through laplaces_hoard/mcp_server.py over
stdio, exactly as Faustus or any MCP client runs it.

Usage (repo venv, app already running with --demo):
    .venv/bin/python scripts/demo_agent_session.py http://127.0.0.1:18820
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = Path(__file__).resolve().parent.parent

CALLS = [
    ("data_list", {}),
    ("data_describe", {"name": "sales"}),
    ("data_query", {"sql": "SELECT product, COUNT(*) AS orders, ROUND(SUM(amount), 2) AS revenue "
                            "FROM sales GROUP BY product ORDER BY revenue DESC", "limit": 10}),
    ("stats", {"test": "ttest_ind", "dataset": "sales", "column": "amount", "group_by": "region",
               "where": "region IN ('North', 'South')"}),
    ("calc", {"expression": "pct(15, 2347)"}),
    ("date_calc", {"operation": "business_days", "start": "2026-04-27", "end": "2026-05-08"}),
    ("units_convert", {"quantity": "5 ft 11 in", "to": "cm"}),
    ("data_chart", {"sql": "SELECT strftime(date, '%Y-%m') AS month, ROUND(SUM(amount), 2) AS revenue "
                           "FROM sales GROUP BY month ORDER BY month", "kind": "line", "x": "month", "y": "revenue",
                    "title": "Monthly revenue"}),
]


async def main(base_url: str) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(REPO_ROOT / "laplaces_hoard" / "mcp_server.py")],
        env={**os.environ, "LAPLACE_URL": base_url},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for name, args in CALLS:
                result = await session.call_tool(name, args)
                text = result.content[0].text if result.content else ""
                status = "error" if result.isError else "ok"
                try:
                    cite = json.loads(text).get("cite", "")
                except (json.JSONDecodeError, AttributeError):
                    cite = ""
                print(f"{status:5} {name:14} {cite}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8812"))
