"""OfficePilot MCP server with switchable workspace backends.

OFFICEPILOT_WORKSPACE_MODE=google enables Gmail and Calendar reads.
Google Tasks writes additionally require
OFFICEPILOT_ALLOW_GOOGLE_TASK_WRITES=true. Task writes are disabled
by default in Google mode.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
try:
    from backend.auth import configured_user_tenants
    from backend.tools.client_matching import identify_meeting_client
    from backend.tools.document_retriever import list_indexed_clients
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from backend.auth import configured_user_tenants
    from backend.tools.client_matching import identify_meeting_client
    from backend.tools.document_retriever import list_indexed_clients

try:
    from .mock_office import (
        discover_next_meeting as mock_discover_next_meeting,
        execute_followup_task as mock_create_followup_task,
        get_calendar as mock_get_calendar,
        list_mock_clients,
        search_emails as mock_search_emails,
    )
    from .google_workspace import (
        discover_next_meeting as google_discover_next_meeting,
        create_followup_task as google_create_followup_task,
        get_calendar as google_get_calendar,
        search_emails as google_search_emails,
    )
except ImportError:  # pragma: no cover - supports direct script execution
    from mock_office import (
        discover_next_meeting as mock_discover_next_meeting,
        execute_followup_task as mock_create_followup_task,
        get_calendar as mock_get_calendar,
        list_mock_clients,
        search_emails as mock_search_emails,
    )
    from google_workspace import (
        discover_next_meeting as google_discover_next_meeting,
        create_followup_task as google_create_followup_task,
        get_calendar as google_get_calendar,
        search_emails as google_search_emails,
    )

mcp = FastMCP("OfficePilot Tools")

WORKSPACE_MODE = os.getenv(
    "OFFICEPILOT_WORKSPACE_MODE", "mock"
).strip().lower()

if WORKSPACE_MODE not in {"mock", "google"}:
    raise ValueError(
        "OFFICEPILOT_WORKSPACE_MODE must be either 'mock' or 'google'."
    )

ALLOW_GOOGLE_TASK_WRITES = (
    os.getenv("OFFICEPILOT_ALLOW_GOOGLE_TASK_WRITES", "false")
    .strip()
    .lower()
    in {"1", "true", "yes"}
)


def _require_identity(user_id: str, tenant_id: str) -> None:
    if not isinstance(user_id, str) or not user_id.strip():
        raise PermissionError("An authenticated user is required.")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise PermissionError("An authenticated tenant is required.")
    if configured_user_tenants().get(user_id) != tenant_id:
        raise PermissionError("The requested user and tenant are not authorized.")


@mcp.tool()
def search_emails(
    client: str,
    user_id: str,
    tenant_id: str,
    max_results: int = 10,
) -> dict:
    """Search emails for a client using mock fixtures or the connected Gmail account."""
    _require_identity(user_id, tenant_id)
    if WORKSPACE_MODE == "google":
        return google_search_emails(
            client=client,
            user_id=user_id,
            max_results=max_results,
        )
    result = mock_search_emails(
        client=client,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    # Keep a predictable output shape without mutating the fixture records.
    result["mode"] = "mock"
    return result


@mcp.tool()
def get_calendar(
    client: str,
    user_id: str,
    tenant_id: str,
    days_ahead: int = 30,
    max_results: int = 10,
) -> dict:
    """Find client-related Calendar events using the selected backend."""
    _require_identity(user_id, tenant_id)
    if WORKSPACE_MODE == "google":
        return google_get_calendar(
            client=client,
            user_id=user_id,
            days_ahead=days_ahead,
            max_results=max_results,
        )
    result = mock_get_calendar(
        client=client,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    result["mode"] = "mock"
    return result


@mcp.tool()
def discover_next_meeting(user_id: str, tenant_id: str) -> dict:
    """Find the earliest upcoming event in the selected calendar backend."""
    _require_identity(user_id, tenant_id)
    if WORKSPACE_MODE == "google":
        result = google_discover_next_meeting(user_id=user_id)
        meeting = result.get("meeting")
        if isinstance(meeting, dict):
            match = identify_meeting_client(
                meeting,
                list_indexed_clients(tenant_id),
            )
            meeting["client"] = match["client"]
            result["client_match"] = match
        return result
    result = mock_discover_next_meeting(
        tenant_id=tenant_id,
        user_id=user_id,
    )
    meeting = result.get("meeting")
    if isinstance(meeting, dict):
        match = identify_meeting_client(
            meeting,
            list_mock_clients(tenant_id),
        )
        meeting["client"] = match["client"]
        result["client_match"] = match
    return result


@mcp.tool()
def create_followup_task(
    client: str,
    task_details: str,
    user_id: str,
    tenant_id: str,
) -> dict:
    """Create a follow-up task in the selected backend; production calls require ADK approval."""
    _require_identity(user_id, tenant_id)
    if WORKSPACE_MODE == "google":
        if not ALLOW_GOOGLE_TASK_WRITES:
            raise PermissionError(
                "Google Tasks writes are disabled by server policy. "
                "Set OFFICEPILOT_ALLOW_GOOGLE_TASK_WRITES=true only "
                "when real Google Tasks creation is explicitly authorized."
            )
        return google_create_followup_task(
            client=client,
            task_details=task_details,
            user_id=user_id,
        )

    result = mock_create_followup_task(client=client, task_details=task_details)
    result["mode"] = "mock"
    return result


if __name__ == "__main__":
    mcp.run(transport="stdio")
