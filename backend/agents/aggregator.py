from google.adk.agents import Agent

from .config import get_model
from .schemas import MeetingContext


aggregator_agent = Agent(
    name="context_aggregator",

    model=get_model(max_tokens=700),
    output_schema=MeetingContext,

    description=(
        "Combines results produced by the parallel "
        "office research agents."
    ),

    instruction="""
You are the Context Aggregator Agent.

Combine the results from the three research agents.

CLIENT NAME FROM WORKFLOW STATE:
{client_name}

Use this exact client name for the client field. Do not claim the
client identity is missing when this value is available. Do not
infer a different client name from the other sources.

EMAIL CONTEXT:
{email_context}

DOCUMENT CONTEXT:
{document_context}

CALENDAR CONTEXT:
{calendar_context}

Create a structured meeting context containing:

1. Client
2. Important communication
3. Client concerns
4. Relevant documents
5. Important document facts
6. Meeting details
7. Participants
8. Missing information

Rules:
- Do not invent facts.
- Only use information provided by the agents.
- Clearly identify missing information.
""",

    output_key="meeting_context",
)