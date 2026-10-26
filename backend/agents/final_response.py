from google.adk.agents import Agent
from .config import get_model


final_response_agent = Agent(
    name="final_response_agent",
    model=get_model(),
    description=(
        "Delivers the final quality-approved meeting briefing."
    ),
    instruction="""
You are the Final Response Agent.

The meeting briefing has passed the quality check.

Return the approved meeting briefing exactly as the final
OfficePilot response.

APPROVED BRIEFING:
{final_briefing}

Do not add new facts.

Do not change the meaning.

Do not perform additional research.

Return only the final meeting briefing.
""",
)