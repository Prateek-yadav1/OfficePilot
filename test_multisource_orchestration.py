import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.agents.parallel_agents import (
    discover_next_meeting,
    search_client_documents,
    search_emails,
)
from backend.agents.planner import client_route_decision
from main import _metadata_from_state


def test_automatic_meeting_match_enables_tenant_scoped_retrieval(monkeypatch):
    meeting_result = {
        "source": "google_calendar",
        "status": "found",
        "meeting": {
            "id": "meeting-123",
            "title": "Acme Robotics pilot review",
            "start": "2026-11-05T10:00:00-07:00",
            "participants": ["Maya Shah"],
        },
        "client_match": {
            "client": "Acme Robotics",
            "confidence": "high",
            "evidence": ["exact_client_name_in_calendar_title"],
        },
    }
    mcp_call = AsyncMock(return_value=meeting_result)
    monkeypatch.setattr(
        "backend.agents.parallel_agents.call_mcp_tool",
        mcp_call,
    )
    context = SimpleNamespace(
        state={
            "original_request": "Prepare me for my next client meeting.",
            "client_name": "Acme Robotics warehouse pilot review on November 5",
            "user_id": "user-1",
            "tenant_id": "tenant-1",
        }
    )

    discovery = asyncio.run(discover_next_meeting(context))
    route = client_route_decision(context)

    assert discovery["meeting"]["id"] == "meeting-123"
    assert route.actions.route == "CLIENT_FOUND"
    assert context.state["client_name"] == "Acme Robotics"
    mcp_call.assert_awaited_once_with(
        "discover_next_meeting",
        {"tenant_id": "tenant-1", "user_id": "user-1"},
    )
    metadata = _metadata_from_state(
        {
            "client_name": "Acme Robotics",
            "discovered_meeting": meeting_result["meeting"],
            "client_match": meeting_result["client_match"],
            "original_request": "Prepare me for my next client meeting.",
        },
        "session-auto",
        {
            "tools": [
                {
                    "tool": "discover_next_meeting",
                    "outcome": "success",
                    "result_count": 1,
                },
                {
                    "tool": "get_calendar",
                    "outcome": "success",
                    "result_count": 0,
                },
            ],
            "sources": [],
        },
    )
    calendar = next(
        item
        for item in metadata["integrations"]
        if item["name"] == "Google Calendar"
    )
    assert calendar["status"] == "completed with 1 result"

    email_result = {"emails": [], "count": 0}
    email_call = AsyncMock(return_value=email_result)
    monkeypatch.setattr(
        "backend.agents.parallel_agents.call_mcp_tool",
        email_call,
    )
    email_context = SimpleNamespace(
        state={"user_id": "user-1", "tenant_id": "tenant-1"}
    )
    assert asyncio.run(
        search_emails("Acme Robotics", email_context)
    ) == email_result
    email_call.assert_awaited_once_with(
        "search_emails",
        {
            "client": "Acme Robotics",
            "tenant_id": "tenant-1",
            "user_id": "user-1",
        },
    )

    document_context = SimpleNamespace(
        state={"user_id": "user-1", "tenant_id": "tenant-1"}
    )
    with patch(
        "backend.agents.parallel_agents.retrieve_client_documents",
        return_value=[{"title": "Acme project brief"}],
    ) as retrieve:
        documents = search_client_documents(
            "project status",
            "Acme Robotics",
            document_context,
        )
    assert documents == [{"title": "Acme project brief"}]
    retrieve.assert_called_once_with(
        query="project status",
        client="Acme Robotics",
        tenant_id="tenant-1",
        limit=3,
    )


def test_zero_email_results_are_reported_as_completed():
    metadata = _metadata_from_state(
        {
            "client_name": "Acme Robotics",
            "client_match": {
                "confidence": "user_provided",
                "evidence": ["explicit_client_name_in_user_request"],
            },
            "original_request": "Prepare me for Acme Robotics.",
        },
        "session-1",
        {
            "tools": [
                {
                    "tool": "search_emails",
                    "outcome": "success",
                    "result_count": 0,
                }
            ],
            "sources": [],
        },
    )

    gmail = next(
        item for item in metadata["integrations"] if item["name"] == "Gmail"
    )
    assert gmail["status"] == "completed with zero results"
    assert gmail["calls"] == 1
    assert (
        "Gmail completed but returned no matching evidence."
        in metadata["missing_information"]
    )


def test_document_failure_is_reported_without_document_sources():
    metadata = _metadata_from_state(
        {
            "client_name": "Acme Robotics",
            "client_match": {"confidence": "user_provided", "evidence": []},
            "original_request": "Prepare me for Acme Robotics.",
        },
        "session-2",
        {
            "tools": [
                {
                    "tool": "search_client_documents",
                    "outcome": "error",
                    "error_type": "ConnectionError",
                }
            ],
            "sources": [],
        },
    )

    documents = next(
        item
        for item in metadata["integrations"]
        if item["name"] == "PostgreSQL / pgvector"
    )
    assert documents["status"] == "failed"
    assert documents["results"] == 0
    assert not any(
        item["source"] == "PostgreSQL / pgvector"
        for item in metadata["sources"]
    )
    assert any(
        "PostgreSQL / pgvector retrieval failed" in item
        for item in metadata["missing_information"]
    )


def test_no_client_clears_stale_match_and_reports_skipped_sources():
    context = SimpleNamespace(
        state={
            "original_request": "Prepare a general office briefing.",
            "client_name": "NOT_FOUND",
            "client_match": {
                "client": "Acme Robotics",
                "confidence": "high",
                "evidence": ["stale_match"],
            },
        }
    )

    event = client_route_decision(context)

    assert event.actions.route == "NO_CLIENT"
    assert context.state["client_name"] == ""
    assert context.state["client_match"]["client"] is None
    assert context.state["workflow_missing_information"]
    assert "client-specific Gmail and PostgreSQL document retrieval were not run" in (
        context.state["workflow_missing_information"][0]
    )
    metadata = _metadata_from_state(
        context.state,
        "session-no-client",
        {"tools": [], "sources": []},
    )
    assert all(
        integration["status"] == "not run"
        for integration in metadata["integrations"]
    )
    assert any(
        "Gmail retrieval was not run" in item
        for item in metadata["missing_information"]
    )
