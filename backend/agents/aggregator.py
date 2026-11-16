from google.adk.agents import Agent

from .config import get_model
from .schemas import MeetingContext


aggregator_agent = Agent(
    name="context_aggregator",

    model=get_model(max_tokens=1000),
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
- Output a valid JSON object adhering to the schema.
- Do not invent facts.
- Only use information provided by the agents.
- Clearly identify missing information.
- Treat the document context as evidence. Include its current project status,
  technical issues, proposed solutions, pending decisions, approvals, timeline
  requirements, and action items in important_document_facts when present.
- Do not list a project detail as missing_information if it appears in the
  email or document context. Only mark it missing when it is absent from all
  supplied sources.
- Keep each list item concise and direct (1-2 sentences) to ensure focused, high-density facts.
""",

    output_key="meeting_context",
)
