from crewai import Agent

from .config import get_crewai_llm


llm = get_crewai_llm()


researcher_agent = Agent(
    role="Client Research Specialist",

    goal=(
        "Analyze tenant-scoped OfficePilot retrieval findings and identify "
        "useful, source-grounded information for an upcoming meeting."
    ),

    backstory=(
        "You are an experienced business research specialist. "
        "You rely only on the context provided by the OfficePilot workflow. "
        "You never invent client facts. You clearly distinguish source-backed "
        "findings from information that could not be found."
    ),

    llm=llm,

    tools=[],

    verbose=False,

    allow_delegation=False,
    max_iter=1,
)