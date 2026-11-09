"""Shared client helpers for OfficePilot's local MCP server."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MCP_SERVER = PROJECT_ROOT / "backend" / "tools" / "mcp_server.py"


class WorkspaceConfigurationError(RuntimeError):
    """Raised when Google Workspace has no usable per-user connection."""


async def call_mcp_tool(
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Invoke a tool exposed by the local OfficePilot MCP server."""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(MCP_SERVER)],
        env=os.environ.copy(),
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
    text_parts = [
        item.text for item in result.content if hasattr(item, "text")
    ]
    if result.isError:
        detail = " ".join(text_parts) or "No error details returned."
        if any(
            reason in detail
            for reason in (
                "OFFICEPILOT_WORKSPACE_TOKEN_FILES must map each user",
                "No Google Workspace connection is configured for this user.",
                "Google OAuth token for the configured tenant was not found.",
                "Google OAuth token is missing required scopes:",
            )
        ):
            raise WorkspaceConfigurationError(detail)
        raise RuntimeError(
            f"OfficePilot MCP tool '{tool_name}' failed: {detail}"
        )

    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured

    if len(text_parts) == 1:
        try:
            parsed = json.loads(text_parts[0])
        except json.JSONDecodeError:
            return {"result": text_parts[0]}
        return parsed if isinstance(parsed, dict) else {"result": parsed}

    return {"result": text_parts}
