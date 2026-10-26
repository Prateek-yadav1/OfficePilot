from google.adk.agents import Agent

from .config import get_model


planner_agent = Agent(
    name="planner_agent",

    model=get_model(),

    description=(
        "Identifies the client or company involved "
        "in an office workflow."
    ),

    instruction="""
You are the OfficePilot Planning Agent.

Your job in this phase is simple.

1. Read the user's request.
2. Identify the client/company involved.
3. Output ONLY the client/company name.
4. Do not search emails.
5. Do not search documents.
6. Do not search the calendar.

Example:

User:
Prepare me for the meeting with ABC Technologies.

Output:
ABC Technologies
""",

    output_key="client_name",
)