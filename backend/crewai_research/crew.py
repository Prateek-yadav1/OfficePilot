from crewai import Crew, Process

from .researcher import researcher_agent
from .analyst import analyst_agent
from .reviewer import reviewer_agent

from .tasks import (
    research_task,
    analysis_task,
    review_task,
)


research_crew = Crew(
    agents=[
        researcher_agent,
        analyst_agent,
        reviewer_agent,
    ],

    tasks=[
        research_task,
        analysis_task,
        review_task,
    ],

    process=Process.sequential,

    verbose=True,
)