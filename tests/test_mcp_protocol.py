"""Proof that the MCP adapter works: spawn mcp_server.py over real stdio
against a live instance of the app and drive it through the MCP protocol
(list_tools + call_tool), not just import its Python functions directly.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MCP_SERVER_PATH = REPO_ROOT / "laplaces_hoard" / "mcp_server.py"


@pytest.mark.asyncio
async def test_mcp_lists_all_tools_and_calls_calc_and_data_query(live_app):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(MCP_SERVER_PATH)],
        env={**os.environ, "LAPLACE_URL": live_app.base_url},
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools_result = await session.list_tools()
            names = {t.name for t in tools_result.tools}
            expected = {
                "calc", "math", "units_convert", "stats", "date_calc",
                "data_list", "data_register", "data_describe", "data_query",
                "data_chart", "work_log",
            }
            assert expected.issubset(names), f"missing tools: {expected - names}"

            for tool in tools_result.tools:
                if tool.name == "calc":
                    assert "Keywords:" in (tool.description or "")

            calc_result = await session.call_tool("calc", {"expression": "0.1 + 0.2"})
            assert not calc_result.isError
            text = calc_result.content[0].text
            assert '"exact":"3/10"' in text.replace(" ", "") or "3/10" in text

            reg_result = await session.call_tool(
                "data_register",
                {"path": str((REPO_ROOT / "tests" / "fixtures" / "tiny.csv"))},
            )
            assert not reg_result.isError, reg_result.content

            query_result = await session.call_tool(
                "data_query", {"sql": "SELECT COUNT(*) AS n FROM tiny", "limit": 10}
            )
            assert not query_result.isError, query_result.content
            assert '"n"' in query_result.content[0].text or "n" in query_result.content[0].text


@pytest.mark.asyncio
async def test_mcp_reports_clear_error_when_app_not_running():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(MCP_SERVER_PATH)],
        env={**os.environ, "LAPLACE_URL": "http://127.0.0.1:18999"},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("calc", {"expression": "1+1"})
            assert result.isError
            assert "laplaces-hoard_unavailable" in result.content[0].text


def test_mcp_server_refuses_non_loopback_url(monkeypatch):
    import importlib
    import sys as _sys

    monkeypatch.setenv("LAPLACE_URL", "http://example.com:8812")
    _sys.modules.pop("laplaces_hoard.mcp_server", None)
    with pytest.raises(RuntimeError, match="loopback"):
        importlib.import_module("laplaces_hoard.mcp_server")

    # restore a sane default so any later import in this process is clean
    monkeypatch.setenv("LAPLACE_URL", "http://127.0.0.1:8812")
    _sys.modules.pop("laplaces_hoard.mcp_server", None)
    importlib.import_module("laplaces_hoard.mcp_server")
