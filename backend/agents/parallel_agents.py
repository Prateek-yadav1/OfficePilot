from google.adk.agents import Agent, ParallelAgent

from .config import get_model
from backend.tools.mock_office import search_emails, get_calendar
from backend.tools.document_retriever import retrieve_documents

email_agent = Agent(
    name="email_agent",
    model=get_model(),
    description="Finds important email context for a client.",
    instruction="""
You are the Email Research Agent.

Client:
{client_name}

Your ONLY responsibility is to investigate email information.

1. Call search_emails with the client name.
2. Summarize the important emails.
3. Extract client concerns, requirements, requests, and important dates.
4. Do not discuss documents or calendar information.
5. Do not invent information.

Return only the email findings.
""",
    tools=[search_emails],
    output_key="email_context",
)


document_agent = Agent(
    name="document_agent",
    model=get_model(),
    description="Finds relevant company documents using RAG retrieval.",
    instruction="""
You are the Document Research Agent.

Client:
{client_name}

Your ONLY responsibility is to investigate document information.

1. Call retrieve_documents with:
   - query: the important document topics to investigate
   - client: the client name provided above
2. Use the returned documents and relevance scores to identify
   useful information.
3. Extract contract information, requirements, previous meeting
   notes, and other relevant facts.
4. Clearly distinguish facts from documents and never invent details.
5. Do not discuss emails or calendar information.

Return only the document findings.
""",
    tools=[retrieve_documents],
    output_key="document_context",
)



calendar_agent = Agent(
    name="calendar_agent",
    model=get_model(),
    description="Finds upcoming calendar meetings for a client.",
    instruction="""
You are the Calendar Agent.

Client:
{client_name}

Your ONLY responsibility is to investigate calendar information.

1. Call get_calendar with the client name.
2. Identify the relevant meeting.
3. Extract the meeting date, time, title, and participants.
4. Do not discuss emails.
5. Do not discuss documents.
6. Do not invent information.

Return only the calendar findings.
""",
    tools=[get_calendar],
    output_key="calendar_context",
)


parallel_research = ParallelAgent(
    name="parallel_office_research",
    description=(
        "Runs independent email, document, and calendar "
        "research concurrently."
    ),
    sub_agents=[
        email_agent,
        document_agent,
        calendar_agent,
    ],
)