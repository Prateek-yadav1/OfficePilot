from google.adk.agents import Agent
from google.adk import Event, Context

from .config import get_model



router_agent = Agent(
    name="conditional_router",
    model=get_model(),
    description=(
        "Determines whether additional research is required "
        "before meeting analysis."
    ),
    instruction="""
You are the Conditional Routing Agent in OfficePilot.

Your job is to decide what should happen next based on the
Information Checker result.

INFORMATION CHECK:
{information_status}

Return EXACTLY one of these values:

RESEARCH

or

ANALYSIS

Rules:

- If the information check starts with "MISSING", return:
  RESEARCH

- If the information check is "ENOUGH", return:
  ANALYSIS

- Do not perform research yourself.
- Do not invent information.
- Return only one of the two values.
""",
    output_key="next_step",
)


def route_decision(ctx: Context) -> Event:
    """
    Convert the router agent's decision into
    an ADK workflow route.
    """

    decision = str(
        ctx.state.get("next_step", "")
    ).strip().upper()

    if decision.startswith("RESEARCH"):
        return Event(
            route="RESEARCH",
            output="Router decision: additional research is required."
        )

    return Event(
        route="ANALYSIS",
        output="Router decision: sufficient information is available."
    )

quality_router_agent = Agent(
    name="quality_router",
    model=get_model(),
    description=(
        "Determines whether the generated briefing is ready "
        "or requires another refinement cycle."
    ),
    instruction="""
You are the Quality Routing Agent.

Read the Quality Checker result:

QUALITY CHECK:
{quality_status}

Return EXACTLY one of:

PASS

or

REVISE

Rules:

- If the quality check starts with PASS, return:
  PASS

- If the quality check starts with REVISE, return:
  REVISE

- Return only one value.
""",
    output_key="quality_route",
)



def quality_route_decision(ctx: Context) -> Event:
    """Route the briefing based on the quality result."""

    decision = str(
        ctx.state.get("quality_route", "")
    ).strip().upper()

    if decision == "PASS":
        return Event(
            route="PASS",
            output="Quality decision: briefing passed quality checks."
        )

    # REVISE or any unexpected result must not pass automatically.
    return Event(
        route="REVISE",
        output="Quality decision: briefing requires refinement."
    )
