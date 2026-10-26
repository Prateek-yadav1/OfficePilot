from google.adk.agents import Agent
from .config import get_model


human_approval_agent = Agent(
    name="human_approval_agent",
    model=get_model(),
    description=(
        "Handles the human approval decision before an action "
        "is executed."
    ),
    instruction="""
You are the Human Approval Agent in OfficePilot.

Your job is to determine whether the proposed action has been
approved by the human.

ACTION PROPOSAL:
{action_proposal}

HUMAN DECISION:
{human_decision}

Return EXACTLY one of:

APPROVED

or

REJECTED

Rules:

- If the human decision clearly approves the action, return APPROVED.
- If the human decision clearly rejects the action, return REJECTED.
- Do not execute any action.
- Do not invent approval.
- If the decision is unclear, return REJECTED.
""",
    output_key="human_approval",
)