import asyncio
from types import SimpleNamespace

import pytest

from backend.agents.client_request import extract_explicit_client
from backend.agents.parallel_agents import discover_next_meeting
from backend.agents.planner import client_route_decision


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("Prepare me for my next meeting with Coding Blocks.", "Coding Blocks"),
        ("Prepare for a call with Acme, then discuss renewal.", "Acme"),
        ("Prepare a briefing for client: Northwind Labs.", "Northwind Labs"),
        ("Prepare me for my next client meeting.", None),
        ("Prepare for a meeting with the client I name.", None),
    ],
)
def test_extract_explicit_client(prompt, expected):
    assert extract_explicit_client(prompt) == expected


def test_explicit_client_overrides_planner_discovery_result():
    context = SimpleNamespace(
        state={
            "original_request": "Prepare me for my next meeting with Coding Blocks.",
            "client_name": "XYZ Solutions",
        }
    )

    event = client_route_decision(context)

    assert event.actions.route == "CLIENT_FOUND"
    assert context.state["client_name"] == "Coding Blocks"
    assert context.state["client_match"]["confidence"] == "user_provided"


def test_explicit_client_skips_calendar_discovery_tool(monkeypatch):
    async def unexpected_mcp_call(*args, **kwargs):
        raise AssertionError("MCP discovery must be skipped for named clients.")

    monkeypatch.setattr(
        "backend.agents.parallel_agents.call_mcp_tool",
        unexpected_mcp_call,
    )
    context = SimpleNamespace(
        state={
            "original_request": "Prepare me for my next meeting with Coding Blocks.",
        }
    )

    result = asyncio.run(discover_next_meeting(context))

    assert result["status"] == "skipped"
    assert result["client"] == "Coding Blocks"
    assert context.state["client_match"]["confidence"] == "user_provided"
