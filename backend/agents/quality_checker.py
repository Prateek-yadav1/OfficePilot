from google.adk.agents import Agent

from .config import get_model
from .retry_utils import throttle_standard


async def _throttle_for_cloud_rate_limits(callback_context):
    if get_llm_provider_settings("adk").provider == "groq":
        await asyncio.sleep(20)


quality_checker = Agent(
    name="quality_checker",
    model=get_model(max_tokens=256),
    before_agent_callback=throttle_standard,
    description=(
        "Critically reviews the generated meeting briefing "
        "for completeness, accuracy, formatting, consistency, "
        "and actionability."
    ),
    instruction="""You are the Quality Checker Agent in OfficePilot.

CLIENT:
{client_name}

MEETING CONTEXT:
{meeting_context}

DOCUMENT FINDINGS:
{document_context}

CURRENT BRIEFING:
{final_briefing}

CRITICAL FORMAT REQUIREMENT:
Your response MUST begin immediately with either "PASS" or "REVISE:".
DO NOT write any introduction, thinking aloud, preamble, or conversational filler like "I'll begin the quality check".
Start your reply with the word PASS or REVISE on line 1.

Check:
1. Does the briefing contain the required sections (Client, Meeting Details, Key Client Priorities, Client Concerns, Important Facts, Potential Risks, Questions to Ask, Recommended Discussion Topics, Executive Summary)?
2. Are risks labeled as FACT-BASED or INFERENCE?
3. Is formatting readable with proper headings?

If acceptable, reply:
PASS

If critical issues exist, reply:
REVISE: <short explanation>
""",
    output_key="quality_status",
)