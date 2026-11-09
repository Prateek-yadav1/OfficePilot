
import re

from google.adk import Context, Event
from google.adk.agents import Agent

from .client_request import extract_explicit_client
from .config import get_model
from .parallel_agents import discover_next_meeting


planner_agent = Agent(
    name="planner_agent",
    model=get_model(max_tokens=128),

    description=(
        "Identifies a named client or discovers the client for the next "
        "upcoming meeting."
    ),

    instruction="""
You are the OfficePilot Planning Agent.

Your ONLY responsibility is identifying the client or company for the request.

IMPORTANT:
- Company and organization names are not private personal information.
- You are explicitly allowed and expected to identify company names
  mentioned in the user's request.
- Never refuse this extraction task because a company is private.
- Do not provide confidential information about any company.
- Do not research or describe the company.

YOUR TASK:
1. If a client or company is explicitly named, return that exact name.
2. If the user asks about their next or upcoming client meeting but does
   not name the client, call discover_next_meeting.
3. Use a meeting client only when the discovery tool returns a
   client_match with confidence "high" or "medium". The tool matches exact
   calendar evidence against client names already present in the authenticated
   tenant's indexed documents. Never infer a company from a vague event title,
   an email domain, or general knowledge.
4. Return ONLY the exact company name. Do not add explanations.
5. If there is no upcoming event or its client cannot be identified, return
   exactly: NOT_FOUND.
6. For requests that name no client and do not ask about a meeting, return
   exactly: NOT_FOUND.

EXAMPLES:

User:
Prepare me for tomorrow's meeting with ABC Technologies.

Output:
ABC Technologies

User:
Summarize the meeting with Microsoft.

Output:
Microsoft

User:
Prepare a general office briefing.

Output:
NOT_FOUND
""",
    tools=[discover_next_meeting],
    output_key="client_name",
)


def client_route_decision(ctx: Context) -> Event:
    """Skip resource searches when planning did not identify a client."""
    request = str(ctx.state.get("original_request", ""))
    explicit_client = extract_explicit_client(request)
    if explicit_client:
        ctx.state["client_name"] = explicit_client
        ctx.state["client_match"] = {
            "client": explicit_client,
            "confidence": "user_provided",
            "evidence": ["explicit_client_name_in_user_request"],
        }
        return Event(
            route="CLIENT_FOUND",
            output="Using the client explicitly named in the request.",
        )

    client = str(ctx.state.get("client_name", "")).strip()
    named_by_user = bool(
        client
        and re.search(
            rf"(?<!\w){re.escape(client)}(?!\w)",
            request,
            flags=re.IGNORECASE,
        )
    )
    match = ctx.state.get("client_match")
    matched_client = (
        str(match.get("client") or "").strip()
        if isinstance(match, dict)
        else ""
    )
    match_confidence = (
        str(match.get("confidence") or "")
        if isinstance(match, dict)
        else ""
    )
    discovered_meeting = ctx.state.get("discovered_meeting")
    asks_for_next_meeting = bool(
        re.search(
            r"\b(?:next|upcoming)\b.*\b(?:meeting|call|appointment)\b|"
            r"\b(?:meeting|call|appointment)\b.*\b(?:next|upcoming)\b",
            request,
            flags=re.IGNORECASE,
        )
    )
    verified_meeting_match = bool(
        matched_client
        and match_confidence in {"high", "medium"}
        and asks_for_next_meeting
        and isinstance(discovered_meeting, dict)
        and discovered_meeting
    )
    evidence_backed = (
        matched_client.casefold() == client.casefold()
        and verified_meeting_match
    )
    if verified_meeting_match:
        client = matched_client
        ctx.state["client_name"] = matched_client
        return Event(
            route="CLIENT_FOUND",
            output=(
                "The planner result was normalized to the exact "
                "tenant-scoped calendar client match."
            ),
        )

    if client and client.casefold() != "not_found" and not (
        named_by_user or evidence_backed
    ):
        client = ""

    if client and client.casefold() != "not_found":
        return Event(
            route="CLIENT_FOUND",
            output=(
                "A client was identified; starting calendar, email, "
                "and document research."
            ),
        )

    ctx.state["client_name"] = ""
    ctx.state["client_match"] = {
        "client": None,
        "confidence": (
            str(match.get("confidence") or "none")
            if isinstance(match, dict)
            else "none"
        ),
        "evidence": [],
    }
    ctx.state["final_briefing"] = (
        "I could not identify a client for this request. For a next-meeting "
        "briefing, no upcoming calendar event with an identifiable client "
        "was found. You can try naming a client or checking your calendar."
    )
    ctx.state["execution_status"] = "completed_with_warnings"
    ctx.state["execution_warnings"] = [
        "No client could be identified from the request or evidence-backed "
        "calendar match; client-specific sources were not searched."
    ]
    ctx.state["workflow_missing_information"] = [
        "No client could be reliably identified; client-specific Gmail and "
        "PostgreSQL document retrieval were not run."
    ]
    return Event(
        route="NO_CLIENT",
        output="No client was identified; skipping client-specific research.",
    )
