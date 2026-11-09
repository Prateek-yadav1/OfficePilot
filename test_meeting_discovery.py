import asyncio
import importlib
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.agents.planner import client_route_decision
from backend.agents.parallel_agents import search_client_documents
from backend.agents.research_agent import run_crewai_research
from backend.agents.router import route_decision
from backend.tools.mock_office import discover_next_meeting

research_agent_module = importlib.import_module(
    "backend.agents.research_agent"
)


def test_discovers_earliest_upcoming_meeting_across_clients() -> None:
    events = [
        {
            "client": "Past Client",
            "title": "Past meeting",
            "date": "2026-10-31",
            "time": "10:00",
            "participants": [],
        },
        {
            "client": "Later Client",
            "title": "Later meeting",
            "date": "2026-11-04",
            "time": "09:00",
            "participants": [],
        },
        {
            "client": "Next Client",
            "title": "Next meeting",
            "date": "2026-11-02",
            "time": "14:00",
            "participants": [],
        },
    ]

    with patch("backend.tools.mock_office._load_json", return_value=events):
        result = discover_next_meeting(
            now=datetime.fromisoformat("2026-10-31T11:00:00+05:30")
        )

    assert result["status"] == "found"
    assert result["meeting"]["client"] == "Next Client"


def test_reports_when_no_upcoming_meeting_exists() -> None:
    with patch(
        "backend.tools.mock_office._load_json",
        return_value=[
            {
                "client": "Past Client",
                "title": "Past meeting",
                "date": "2026-10-31",
                "time": "10:00",
                "participants": [],
            }
        ],
    ):
        result = discover_next_meeting(
            now=datetime.fromisoformat("2026-10-31T11:00:00+05:30")
        )

    assert result == {
        "source": "mock_calendar",
        "status": "not_found",
        "meeting": None,
    }


def test_crewai_research_is_reviewed_over_a2a() -> None:
    async def run() -> str:
        crew = SimpleNamespace(
            kickoff_async=AsyncMock(return_value="Source-backed report")
        )
        a2a_review = AsyncMock(
            return_value="A2A reviewer received the submitted research context."
        )
        with (
            patch.object(
                research_agent_module,
                "create_research_crew",
                return_value=crew,
            ),
            patch.object(
                research_agent_module,
                "_review_with_a2a",
                a2a_review,
            ),
        ):
            result = await run_crewai_research(
                "ABC Technologies",
                "deployment milestones",
            )

        a2a_review.assert_awaited_once()
        assert "Source-backed report" in result
        assert "A2A reviewer received" in result
        return result

    asyncio.run(run())


def test_invalid_calendar_event_is_reported() -> None:
    with patch(
        "backend.tools.mock_office._load_json",
        return_value=[{"client": "Missing date"}],
    ):
        with pytest.raises(ValueError, match="Invalid mock calendar event"):
            discover_next_meeting(
                now=datetime.fromisoformat("2026-10-31T11:00:00+05:30")
            )


def test_missing_client_skips_research_with_clear_response() -> None:
    context = SimpleNamespace(state={"client_name": "NOT_FOUND"})

    event = client_route_decision(context)

    assert event.actions.route == "NO_CLIENT"
    assert "no upcoming calendar event" in context.state["final_briefing"]


def test_identified_client_continues_to_resource_research() -> None:
    context = SimpleNamespace(
        state={
            "client_name": "XYZ Solutions",
            "original_request": "Prepare me for a meeting with XYZ Solutions.",
        }
    )

    event = client_route_decision(context)

    assert event.actions.route == "CLIENT_FOUND"


def test_sufficient_information_keeps_the_analysis_only_branch() -> None:
    context = SimpleNamespace(
        state={"next_step": "ANALYSIS"},
    )

    event = route_decision(context)

    assert event.actions.route == "ANALYSIS"
    assert "No additional research" in context.state["research_context"]


def test_document_search_uses_client_filter_and_safe_fixed_limit() -> None:
    with patch(
        "backend.agents.parallel_agents.retrieve_client_documents",
        return_value=[],
    ) as retrieve:
        result = search_client_documents(
            query="meeting preparation context",
            client="XYZ Solutions",
            tool_context=SimpleNamespace(
                state={"tenant_id": "tenant-test"}
            ),
        )

    retrieve.assert_called_once_with(
        query="meeting preparation context",
        client="XYZ Solutions",
        tenant_id="tenant-test",
        limit=3,
    )
    assert result == []
