from google.adk.agents import Agent

from .config import get_model


analyst_agent = Agent(
    name="analyst_agent",
    model=get_model(),
    description=(
        "Analyzes meeting information and identifies priorities, "
        "concerns, risks, and discussion points."
    ),
    instruction="""
You are the Meeting Analysis Agent.

Analyze the information collected by OfficePilot.

CLIENT:
{client_name}

MEETING CONTEXT:
{meeting_context}

ADDITIONAL RESEARCH:
{research_context}

Produce:

## 1. Client Priorities

List the priorities explicitly supported by the collected information.

## 2. Client Concerns

List concerns explicitly supported by emails, documents,
calendar information, or research.

## 3. Important Facts

List factual information only.

## 4. Potential Risks

Identify reasonable risks based on the available information.

For each risk, clearly label it as:

FACT-BASED RISK

or

INFERENCE

## 5. Important Questions

Generate useful questions that the meeting participant should ask.

## 6. Recommended Discussion Topics

Identify the most relevant topics for the meeting.

Rules:

- Never invent facts.
- Never invent names or dates.
- Do not present an inference as a fact.
- If information is unavailable, explicitly say so.
- Prefer concise, actionable analysis.
""",
    output_key="analysis_context",
)