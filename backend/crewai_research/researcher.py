from crewai import Agent
from crewai.tools import tool

from .config import get_crewai_llm
from backend.tools.mock_office import research_client


llm = get_crewai_llm()


@tool("OfficePilot Client Research")
def client_research_tool(
    client: str,
    missing_information: str,
) -> str:
    """
    Retrieves verified client information from the
    OfficePilot research database.
    """

    result = research_client(
        client=client,
        missing_information=missing_information,
    )

    return str(result)


researcher_agent = Agent(
    role="Client Research Specialist",

    goal=(
        "Investigate missing information about a client using "
        "the OfficePilot research database and identify useful, "
        "verified facts for an upcoming meeting."
    ),

    backstory=(
        "You are an experienced business research specialist. "
        "You always use the available research tool before "
        "drawing conclusions. You never invent client facts. "
        "You clearly distinguish verified information from "
        "information that could not be found."
    ),

    llm=llm,

    tools=[client_research_tool],

    verbose=True,

    allow_delegation=False,
)