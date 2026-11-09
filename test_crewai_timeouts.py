import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.a2a_demo.client_agent import create_a2a_http_client
from backend.agents.observability import (
    begin_execution_observation,
    end_execution_observation,
)
from backend.agents import research_agent as research_agent_module
from backend.crewai_research.config import (
    CREWAI_MODEL_MAX_RETRIES,
    CREWAI_MODEL_TIMEOUT_SECONDS,
)
from backend.crewai_research.crew import create_research_crew
from backend.crewai_research.observability import InstrumentedCrewLLM
from backend.agents.quality_checker import quality_checker
from backend.agents.rework_agent import rework_agent
from backend.agents.planner import planner_agent
from backend.agents.parallel_agents import (
    calendar_agent,
    document_agent,
    email_agent,
)
from backend.agents.router import (
    MAX_QUALITY_REVIEW_CYCLES,
    quality_route_decision,
)


def test_crewai_has_bounded_role_iterations_and_task_timeouts():
    crew = create_research_crew()

    assert len(crew.agents) == 3
    assert len(crew.tasks) == 3
    assert all(agent.max_iter == 1 for agent in crew.agents)
    assert all(agent.max_execution_time == 100 for agent in crew.agents)
    assert all(agent.allow_delegation is False for agent in crew.agents)
    assert all(not agent.tools for agent in crew.agents)
    assert crew.process.value == "sequential"


def test_quality_review_rework_cycles_have_a_hard_limit():
    required_sections = (
        "# Meeting Briefing\n"
        "## Client\nAcme Robotics\n"
        "## Meeting Details\nNot found in available sources.\n"
        "## Key Client Priorities\nNone verified.\n"
        "## Client Concerns\nNone verified.\n"
        "## Important Facts\nNone verified.\n"
        "## Additional Research\nNone performed.\n"
        "## Potential Risks\nNo verified risks.\n"
        "## Questions to Ask\nConfirm project status.\n"
        "## Recommended Discussion Topics\nProject status.\n"
        "## Actionable Steps\nConfirm next steps.\n"
        "## Executive Summary\nPrepare to discuss project status.\n"
    )
    state = {
        "quality_route": "REVISE",
        "quality_status": "REVISE: deterministic test",
        "quality_review_cycles": 0,
        "client_name": "Acme Robotics",
        "final_briefing": required_sections,
        "meeting_context": {
            "client": "Acme Robotics",
            "important_communication": [],
            "client_concerns": [],
            "relevant_documents": [],
            "important_document_facts": [],
            "meeting_title": "Not found in available sources",
            "meeting_date": "Not found in available sources",
            "meeting_time": "Not found in available sources",
            "participants": [],
            "missing_information": [],
        },
    }

    assert MAX_QUALITY_REVIEW_CYCLES == 3
    for cycle in range(1, MAX_QUALITY_REVIEW_CYCLES + 1):
        decision = quality_route_decision(SimpleNamespace(state=state))
        assert decision.actions.route == (
            "BLOCK" if cycle == MAX_QUALITY_REVIEW_CYCLES else "REVISE"
        )

    assert state["quality_review_cycles"] == MAX_QUALITY_REVIEW_CYCLES
    assert state["execution_status"] == "failed"
    assert "did not return PASS" in state["deterministic_quality_errors"][0]


def test_provider_timeouts_are_explicit_and_retry_budget_is_bounded():
    from backend.crewai_research.config import get_crewai_llm
    from backend.agents.config import get_model

    crew_model = get_crewai_llm()
    adk_model = get_model()
    quality_model = quality_checker.model

    assert CREWAI_MODEL_TIMEOUT_SECONDS == 45
    assert CREWAI_MODEL_MAX_RETRIES == 1
    assert crew_model.delegate.timeout == CREWAI_MODEL_TIMEOUT_SECONDS
    assert adk_model._additional_args["timeout"] == 180
    assert adk_model._additional_args["num_retries"] == 0
    assert quality_model._additional_args["timeout"] == 180
    assert quality_model._additional_args["num_retries"] == 0
    assert quality_model._additional_args["max_tokens"] == 128
    assert rework_agent.model._additional_args["max_tokens"] == 900
    assert planner_agent.model._additional_args["max_tokens"] == 128
    assert email_agent.model._additional_args["max_tokens"] == 500
    assert document_agent.model._additional_args["max_tokens"] == 600
    assert calendar_agent.model._additional_args["max_tokens"] == 400


def test_crewai_model_retries_transient_failures_only_within_limit():
    class FlakyModel:
        def __init__(self):
            self.calls = 0

        def call(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("private provider details")
            return "Recovered response"

        def supports_function_calling(self):
            return False

        def supports_stop_words(self):
            return False

        def get_context_window_size(self):
            return 4096

        def supports_multimodal(self):
            return False

    model = FlakyModel()
    instrumented = InstrumentedCrewLLM(
        model="officepilot-instrumented-crewai",
        delegate=model,
        max_retries=1,
        retry_backoff_seconds=0,
    )
    events = []
    tokens = begin_execution_observation(
        "retry-test",
        lambda event_type, data: events.append((event_type, data)),
    )
    try:
        result = instrumented.call(
            messages=[],
            from_agent=SimpleNamespace(role="Research Analyst"),
            from_task=SimpleNamespace(name="analysis"),
        )
    finally:
        end_execution_observation(tokens)

    assert result == "Recovered response"
    assert model.calls == 2
    assert [event for event, _ in events].count("crewai_model_started") == 2
    assert "crewai_model_timed_out" in [event for event, _ in events]
    assert "crewai_model_retrying" in [event for event, _ in events]
    completed = next(data for event, data in events if event == "crewai_model_completed")
    assert completed["agent_iteration"] == 1


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (httpx.ReadTimeout("redacted"), "request_timeout"),
        (httpx.ConnectError("redacted"), "connection_error"),
    ],
)
def test_a2a_timeout_and_connection_errors_are_explicit(
    monkeypatch,
    failure,
    reason,
):
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

    class FakeRunner:
        def __init__(self, app):
            self.session_service = SimpleNamespace(
                create_session=AsyncMock(
                    return_value=SimpleNamespace(id="a2a-session")
                )
            )

        async def run_async(self, **kwargs):
            raise failure
            yield None

    monkeypatch.setattr(
        research_agent_module,
        "App",
        lambda **kwargs: SimpleNamespace(name="test-app"),
    )
    monkeypatch.setattr(research_agent_module, "InMemoryRunner", FakeRunner)
    monkeypatch.setattr(
        research_agent_module,
        "create_a2a_http_client",
        FakeClient,
    )
    monkeypatch.setattr(
        research_agent_module,
        "create_remote_research_agent",
        lambda client: SimpleNamespace(name="remote_reviewer"),
    )
    events = []
    tokens = begin_execution_observation(
        "a2a-error-test",
        lambda event_type, data: events.append((event_type, data)),
    )
    try:
        with pytest.raises(research_agent_module.A2AReviewIncomplete) as exc_info:
            asyncio.run(research_agent_module._review_with_a2a("safe report"))
    finally:
        end_execution_observation(tokens)

    assert exc_info.value.reason == reason, (
        events,
        repr(exc_info.value.__cause__),
    )
    event_type = "a2a_timed_out" if reason == "request_timeout" else "a2a_failed"
    event = next(data for name, data in events if name == event_type)
    assert event["duration_ms"] >= 0
    assert "redacted" not in str(event)


def test_a2a_client_uses_bounded_timeouts_and_authenticated_transport():
    async def verify():
        client = create_a2a_http_client()
        try:
            timeout = client.timeout
            assert timeout.connect == 5
            assert timeout.read == 30
            assert timeout.write == 10
            assert timeout.pool == 5
            assert client.auth is not None
        finally:
            await client.aclose()

    asyncio.run(verify())


def test_a2a_cancellation_propagates_to_caller(monkeypatch):
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

    class FakeRunner:
        def __init__(self, app):
            self.session_service = SimpleNamespace(
                create_session=AsyncMock(
                    return_value=SimpleNamespace(id="a2a-session")
                )
            )

        async def run_async(self, **kwargs):
            await asyncio.Event().wait()
            yield None

    monkeypatch.setattr(
        research_agent_module,
        "App",
        lambda **kwargs: SimpleNamespace(name="test-app"),
    )
    monkeypatch.setattr(research_agent_module, "InMemoryRunner", FakeRunner)
    monkeypatch.setattr(
        research_agent_module,
        "create_a2a_http_client",
        FakeClient,
    )
    monkeypatch.setattr(
        research_agent_module,
        "create_remote_research_agent",
        lambda client: SimpleNamespace(name="remote_reviewer"),
    )

    async def scenario():
        events = []
        tokens = begin_execution_observation(
            "a2a-cancel-test",
            lambda event_type, data: events.append((event_type, data)),
        )
        task = asyncio.create_task(
            research_agent_module._review_with_a2a("safe report")
        )
        await asyncio.sleep(0)
        task.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            end_execution_observation(tokens)
        assert "a2a_cancelled" in [event for event, _ in events]

    asyncio.run(scenario())


def test_crewai_timeout_returns_incomplete_report_without_claiming_review(
    monkeypatch,
):
    class TimeoutCrew:
        tasks = [SimpleNamespace(output=None)]

        async def kickoff_async(self, inputs):
            await asyncio.sleep(1)

    monkeypatch.setenv("OFFICEPILOT_CREW_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setattr(
        research_agent_module,
        "create_research_crew",
        TimeoutCrew,
    )
    a2a_review = AsyncMock()
    monkeypatch.setattr(
        research_agent_module,
        "_review_with_a2a",
        a2a_review,
    )
    events = []
    tokens = begin_execution_observation(
        "crew-timeout-test",
        lambda event_type, data: events.append((event_type, data)),
    )
    try:
        result = asyncio.run(
            research_agent_module.run_crewai_research(
                "Acme Robotics",
                "meeting agenda",
            )
        )
    finally:
        end_execution_observation(tokens)

    assert "Research status: incomplete" in result
    assert "Review status: not_run" in result
    assert "No successful review is claimed." in result
    assert "Remote A2A reviewer response" not in result
    a2a_review.assert_not_awaited()
    assert "crewai_timed_out" in [event for event, _ in events]


def test_crewai_rate_limit_is_reported_without_provider_fallback(monkeypatch):
    class RateLimitError(Exception):
        pass

    class RateLimitedCrew:
        tasks = [SimpleNamespace(output=None)]

        async def kickoff_async(self, inputs):
            raise RateLimitError("private rate-limit response")

    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setattr(
        research_agent_module,
        "create_research_crew",
        RateLimitedCrew,
    )
    context = SimpleNamespace(state={"execution_warnings": []})
    events = []
    tokens = begin_execution_observation(
        "crew-rate-limit-test",
        lambda event_type, data: events.append((event_type, data)),
    )
    try:
        result = asyncio.run(
            research_agent_module.run_crewai_research(
                "Acme Robotics",
                "meeting agenda",
                context,
            )
        )
    finally:
        end_execution_observation(tokens)

    assert "Groq reported a rate limit" in result
    assert "No provider fallback was used." in result
    assert context.state["execution_warnings"] == [
        research_agent_module._rate_limit_message()
    ]
    assert "provider_rate_limited" in [event for event, _ in events]
    assert "private rate-limit response" not in str(events)


def test_repeated_identical_research_in_one_session_is_deduplicated(monkeypatch):
    class SuccessfulCrew:
        tasks = []

        async def kickoff_async(self, inputs):
            assert (
                "PostgreSQL document findings:\nRetrieved facts"
                == inputs["retrieved_context"]
            )
            return "CrewAI findings based on retrieved facts."

    monkeypatch.setattr(
        research_agent_module,
        "create_research_crew",
        SuccessfulCrew,
    )
    a2a_review = AsyncMock(return_value="Advisory review received.")
    monkeypatch.setattr(
        research_agent_module,
        "_review_with_a2a",
        a2a_review,
    )
    context = SimpleNamespace(
        state={
            "user_id": "user-1",
            "tenant_id": "tenant-1",
            "document_context": "Retrieved facts",
        }
    )

    async def scenario():
        first = await research_agent_module.run_crewai_research(
            "Acme Robotics",
            "meeting agenda",
            context,
        )
        second = await research_agent_module.run_crewai_research(
            "Acme Robotics",
            "meeting agenda",
            context,
        )
        return first, second

    first, second = asyncio.run(scenario())
    assert first == second
    a2a_review.assert_awaited_once()


def test_a2a_review_failure_preserves_findings_and_marks_review_incomplete(
    monkeypatch,
):
    class SuccessfulCrew:
        tasks = []

        async def kickoff_async(self, inputs):
            return "Retrieved-source finding: deployment approval is pending."

    monkeypatch.setattr(
        research_agent_module,
        "create_research_crew",
        SuccessfulCrew,
    )
    monkeypatch.setattr(
        research_agent_module,
        "_review_with_a2a",
        AsyncMock(side_effect=research_agent_module.A2AReviewIncomplete("request_timeout")),
    )

    result = asyncio.run(
        research_agent_module.run_crewai_research(
            "Acme Robotics",
            "deployment approval",
        )
    )

    assert "deployment approval is pending" in result
    assert "Review status: incomplete" in result
    assert "No successful review is claimed." in result
    assert "reviewed report" not in result.casefold()
