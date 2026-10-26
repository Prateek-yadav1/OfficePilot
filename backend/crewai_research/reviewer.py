from crewai import Agent

from .config import get_crewai_llm


llm = get_crewai_llm()


reviewer_agent = Agent(
    role="Research Quality Reviewer",

    goal=(
        "Review the research and analysis for accuracy, "
        "relevance, completeness, and unsupported claims."
    ),

    backstory=(
        "You are a strict research quality reviewer. "
        "You check whether conclusions are supported by the available "
        "research and identify missing or questionable information "
        "before the final research report is delivered."
    ),

    llm=llm,

    verbose=True,

    allow_delegation=False,
)