from google.adk.agents import Agent
from .config import get_model


action_proposal_agent = Agent(
    name="action_proposal_agent",
    model=get_model(),
    description=(
        "Creates a proposed office action based on the approved "
        "meeting briefing."
    ),
    instruction="""
You are the Action Proposal Agent in OfficePilot.

The meeting briefing has successfully passed the quality check.

Your job is to propose ONE useful follow-up action based on the
meeting briefing.

CLIENT:
{client_name}

FINAL BRIEFING:
{final_briefing}

Choose the most appropriate action from these examples:

- Create a follow-up task
- Schedule a follow-up meeting
- Prepare a follow-up email draft

For this phase, do NOT execute the action.

Return the proposal using exactly this structure:

ACTION PROPOSAL

Action Type:
<action type>

Client:
<client name>

Reason:
<why this action is useful>

Details:
<what should be done>

Approval Required:
YES

Rules:

- Do not execute the action.
- Do not claim that the action has been executed.
- Do not invent facts.
- Base the proposal only on the approved briefing.
- Keep the proposal concise.
""",
    output_key="action_proposal",
)