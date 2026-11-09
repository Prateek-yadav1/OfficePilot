"""Local ADK agent that delegates a request to a remote A2A agent."""

import os

import httpx
from google.adk.agents import Agent
from google.adk.agents.remote_a2a_agent import (
    AGENT_CARD_WELL_KNOWN_PATH,
    RemoteA2aAgent,
)

from backend.agents.config import get_model


class _SharedSecretHeaderAuth(httpx.Auth):
    async def async_auth_flow(self, request: httpx.Request):
        secret = os.getenv("OFFICEPILOT_A2A_SHARED_SECRET", "")
        if not secret:
            raise RuntimeError(
                "OFFICEPILOT_A2A_SHARED_SECRET is required for A2A calls."
            )
        request.headers["X-OfficePilot-A2A-Key"] = secret
        yield request


def create_a2a_http_client() -> httpx.AsyncClient:
    """Create an A2A transport that authenticates using the service secret."""
    return httpx.AsyncClient(
        auth=_SharedSecretHeaderAuth(),
        timeout=httpx.Timeout(
            connect=5,
            read=30,
            write=10,
            pool=5,
        ),
    )


def create_remote_research_agent(
    httpx_client: httpx.AsyncClient | None = None,
) -> RemoteA2aAgent:
    """Create an A2A client agent for the configured remote reviewer."""
    return RemoteA2aAgent(
        name="remote_research_agent",
        description=(
            "Provides an independent review of research findings through A2A."
        ),
        agent_card=os.getenv(
            "OFFICEPILOT_A2A_AGENT_CARD_URL",
            f"http://127.0.0.1:{os.getenv('PORT', '8000')}/a2a"
            f"{AGENT_CARD_WELL_KNOWN_PATH}",
        ),
        httpx_client=httpx_client or create_a2a_http_client(),
        use_legacy=False,
    )

remote_research_agent = create_remote_research_agent()

root_agent = Agent(
    name="officepilot_a2a_test_root",
    model=get_model(),
    description="Delegates a request to a remote agent using A2A.",
    instruction="""
You are the local A2A coordinator.

For every request, delegate to remote_research_agent.
Do not answer directly from your own knowledge.
After receiving the remote response, report its result faithfully.
Do not claim external research or verification was performed.
""",
    sub_agents=[remote_research_agent],
)
