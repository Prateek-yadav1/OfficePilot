from typing import Any

from crewai import Crew, Process
from crewai import Agent, Task

from .researcher import researcher_agent
from .analyst import analyst_agent
from .reviewer import reviewer_agent

from .tasks import (
    research_task,
    analysis_task,
    review_task,
)
from backend.agents.observability import emit_execution_event


_TASK_TIMEOUT_SECONDS = 100


def _new_agent(template: Agent) -> Agent:
    return Agent(
        role=template.role,
        goal=template.goal,
        backstory=template.backstory,
        llm=template.llm,
        tools=list(template.tools or []),
        verbose=False,
        allow_delegation=False,
        max_iter=1,
        max_execution_time=_TASK_TIMEOUT_SECONDS,
        cache=False,
    )


def _new_task(template: Task, agent: Agent) -> Task:
    task = Task(
        name=f"{agent.role} task",
        description=template.description,
        expected_output=template.expected_output,
        agent=agent,
        async_execution=False,
        callback=lambda output: _record_task_completion(task, output),
    )
    return task


def _record_task_completion(task: Task, output: Any) -> None:
    started_at = task.start_time
    ended_at = task.end_time
    duration_ms = None
    if started_at is not None and ended_at is not None:
        duration_ms = round(
            (ended_at - started_at).total_seconds() * 1000,
            2,
        )
    emit_execution_event(
        "crewai_task_completed",
        {
            "task": task.name or "research_task",
            "agent": str(getattr(output, "agent", "unknown")),
            "duration_ms": duration_ms,
        },
    )


def create_research_crew() -> Crew:
    """Create isolated, bounded CrewAI objects for one workflow execution."""
    researcher = _new_agent(researcher_agent)
    analyst = _new_agent(analyst_agent)
    reviewer = _new_agent(reviewer_agent)
    agents = {
        researcher_agent.role: researcher,
        analyst_agent.role: analyst,
        reviewer_agent.role: reviewer,
    }
    tasks = [
        _new_task(research_task, researcher),
        _new_task(analysis_task, analyst),
        _new_task(review_task, reviewer),
    ]
    return Crew(
        agents=list(agents.values()),
        tasks=tasks,
        process=Process.sequential,
        verbose=False,
        max_rpm=3,
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