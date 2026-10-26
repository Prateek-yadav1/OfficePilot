from google.adk.agents import Agent

from .config import get_model
from backend.crewai_research.crew import research_crew


async def run_crewai_research(
    client: str,
    missing_information: str,
) -> str:
    """
    Runs the nested CrewAI research workflow asynchronously
    and returns the final research report.
    """

    result = await research_crew.kickoff_async(
        inputs={
            "client": client,
            "missing_information": missing_information,
        }
    )

    return str(result)


research_agent = Agent(
    name="research_agent",

    model=get_model(),

    description=(
        "Delegates complex client research to a nested "
        "CrewAI multi-agent research workflow."
    ),

    instruction="""
You are the Research Agent in OfficePilot.

Your responsibility is to investigate information that is missing
from the current meeting context.

CLIENT:
{client_name}

INFORMATION CHECK:
{information_status}

Follow these steps:

1. Read the missing information identified by the
   Information Checker.

2. Call the run_crewai_research tool using:

   client = the current client

   missing_information = the missing information

3. The CrewAI workflow will perform the research using:

   - Researcher Agent
   - Analyst Agent
   - Reviewer Agent

4. Carefully inspect the returned CrewAI research report.

5. Summarize the verified findings.

6. Clearly identify remaining uncertainties.

7. Never invent information.

If the Information Checker says ENOUGH, return:

No additional research required.

Return a concise research report.
""",

    tools=[run_crewai_research],

    output_key="research_context",
)