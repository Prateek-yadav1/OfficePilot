"""Shared client helpers for OfficePilot's local MCP server."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Literal, Self

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MCP_SERVER = PROJECT_ROOT / "backend" / "tools" / "mcp_server.py"


class _MCPResponseModel(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)


class _EmailRecord(_MCPResponseModel):
    id: str | None = None
    thread_id: str | None = None
    subject: str | None = None
    date: str | None = None
    snippet: str | None = None
    content: str | None = None

    @model_validator(mode="after")
    def require_email_content(self) -> Self:
        if not self.model_fields_set.intersection(
            {"id", "subject", "date", "snippet", "content"}
        ):
            raise ValueError("email record has no recognized fields")
        return self


class _MeetingRecord(_MCPResponseModel):
    id: str | None = None
    title: str | None = None
    date: str | None = None
    time: str | None = None
    start: str | None = None
    end: str | None = None
    participants: list[str] | None = None

    @model_validator(mode="after")
    def require_meeting_details(self) -> Self:
        if not self.model_fields_set.intersection(
            {"id", "title", "date", "start"}
        ):
            raise ValueError("meeting record has no recognized fields")
        return self


class _EmailSearchResponse(_MCPResponseModel):
    source: str = Field(min_length=1)
    client: str = Field(min_length=1)
    count: int = Field(ge=0)
    emails: list[_EmailRecord]
    elapsed_seconds: float | None = Field(default=None, ge=0)
    query: str | None = None
    mode: str | None = None

    @model_validator(mode="after")
    def count_matches_records(self) -> Self:
        if self.count != len(self.emails):
            raise ValueError("email count does not match returned records")
        return self


class _CalendarSearchResponse(_MCPResponseModel):
    source: str = Field(min_length=1)
    client: str = Field(min_length=1)
    count: int = Field(ge=0)
    meetings: list[_MeetingRecord]
    elapsed_seconds: float | None = Field(default=None, ge=0)
    window_days: int | None = Field(default=None, ge=0)
    mode: str | None = None

    @model_validator(mode="after")
    def count_matches_records(self) -> Self:
        if self.count != len(self.meetings):
            raise ValueError("meeting count does not match returned records")
        return self


class _MeetingDiscoveryResponse(_MCPResponseModel):
    source: str = Field(min_length=1)
    status: Literal["found", "not_found"]
    meeting: _MeetingRecord | None
    window_days: int | None = Field(default=None, ge=0)
    elapsed_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def status_matches_meeting(self) -> Self:
        if (self.status == "found") != (self.meeting is not None):
            raise ValueError("meeting status does not match meeting data")
        return self


_RESPONSE_MODELS: dict[str, type[_MCPResponseModel]] = {
    "search_emails": _EmailSearchResponse,
    "get_calendar": _CalendarSearchResponse,
    "discover_next_meeting": _MeetingDiscoveryResponse,
}


def validate_mcp_tool_response(
    tool_name: str,
    response: Any,
) -> dict[str, Any]:
    """Validate known MCP responses while preserving extension fields."""
    if not isinstance(response, dict):
        raise RuntimeError(
            f"OfficePilot MCP tool '{tool_name}' returned a non-object response."
        )

    response_model = _RESPONSE_MODELS.get(tool_name)
    if response_model is None:
        return response

    try:
        validated = response_model.model_validate(response)
    except ValidationError:
        raise RuntimeError(
            f"OfficePilot MCP tool '{tool_name}' returned a malformed response."
        ) from None
    return validated.model_dump(exclude_none=True)


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
        return validate_mcp_tool_response(tool_name, structured)

    if len(text_parts) == 1:
        try:
            parsed = json.loads(text_parts[0])
        except json.JSONDecodeError:
            parsed = {"result": text_parts[0]}
        return validate_mcp_tool_response(tool_name, parsed)

    return validate_mcp_tool_response(tool_name, {"result": text_parts})
