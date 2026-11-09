
import asyncio
import importlib
from unittest.mock import AsyncMock, patch

from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.genai import types

from backend.agents.research_agent import research_agent

research_agent_module = importlib.import_module(
    "backend.agents.research_agent"
)


async def main():
    print("\n" + "=" * 70)
    print("OFFICEPILOT - ADK RUNNER MOCK TEST")
    print("=" * 70)

    app = App(
        name="officepilot_adk_runner_mock_test",
        root_agent=research_agent,
    )

    runner = InMemoryRunner(app=app)

    user_id = "mock_test_user"
    session_id = "adk_runner_mock_session"

    session = await runner.session_service.create_session(
        app_name=app.name,
        user_id=user_id,
        session_id=session_id,
        state={
            "client_name": "ABC Technologies",
            "information_status": (
                "MISSING: deployment milestones and previous deployment concerns"
            ),
        },
    )

    mock_result = (
        "Mock research completed for ABC Technologies. "
        "Review deployment milestones, assign owners, and examine previous delays."
    )

    mock_crew = type("MockCrew", (), {})()
    mock_crew.kickoff_async = AsyncMock(return_value=mock_result)
    a2a_reviews = []
    original_a2a_review = research_agent_module._review_with_a2a

    async def capture_a2a_review(report):
        response = await original_a2a_review(report)
        a2a_reviews.append((report, response))
        return response

    print("\nStarting ADK runner with mocked CrewAI...")

    with patch(
        "backend.agents.research_agent.create_research_crew",
        return_value=mock_crew,
    ), patch(
        "backend.agents.research_agent._review_with_a2a",
        side_effect=capture_a2a_review,
    ):
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session.id,
            new_message=types.Content(
                role="user",
                parts=[
                    types.Part(
                        text=(
                            "Research the missing deployment information "
                            "for ABC Technologies."
                        )
                    )
                ],
            ),
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        print("\nADK event text:")
                        print(part.text)

    if mock_crew.kickoff_async.await_count == 0:
        raise AssertionError(
            "ADK did not call the mocked CrewAI research function. "
            "Check whether the agent selected the research tool."
        )
    if not a2a_reviews:
        raise AssertionError(
            "The research result was not sent to the remote A2A reviewer."
        )
    if "not independently verified" not in a2a_reviews[0][1].lower():
        raise AssertionError(
            "The A2A reviewer did not return its source-verification warning."
        )

    print("\nPASS: ADK runner completed its event loop.")
    print("PASS: The mocked CrewAI research function was called.")
    print("PASS: The research result was reviewed over A2A.")
    print("PASS: The A2A reviewer made no source-verification claim.")
    print("PASS: No real CrewAI LLM request was made.")

    print("\n" + "=" * 70)
    print("ADK RUNNER MOCK TEST COMPLETED")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
