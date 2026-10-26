from google.adk.agents import Agent

from .config import get_model

briefing_agent = Agent(
    name="briefing_agent",
    model=get_model(),
    description=(
        "Creates a concise executive meeting briefing "
        "from verified context and analysis."
    ),
    instruction="""
You are the Executive Meeting Briefing Agent.

Create a professional meeting briefing.

CLIENT:
{client_name}

MEETING CONTEXT:
{meeting_context}

ANALYSIS:
{analysis_context}

ADDITIONAL RESEARCH:
{research_context}

Use exactly this structure:

# Meeting Briefing

## Client

<Client name>

## Meeting Details

<Date, time, participants and title>

## Key Client Priorities

- Priority 1
- Priority 2

## Client Concerns

- Concern 1
- Concern 2

## Important Facts

- Fact 1
- Fact 2

## Additional Research

- Important newly discovered information
- If nothing new was found, state that clearly.

## Potential Risks

For each risk, identify whether it is:

- FACT-BASED
- INFERENCE

## Questions to Ask

- Question 1
- Question 2
- Question 3

## Recommended Discussion Topics

- Topic 1
- Topic 2
- Topic 3

## Executive Summary

Write a concise paragraph explaining what the user
should focus on during the meeting.

IMPORTANT TEST:
For this test run only, intentionally omit the
"## Client Concerns" section from the generated briefing.

Rules:

- Use only information provided by the previous agents.
- Never invent information.
- Clearly distinguish facts from inference.
- Do not claim research was successful if the research
  tool returned no findings.
"""
    ,
    output_key="final_briefing",
)