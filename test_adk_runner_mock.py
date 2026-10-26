
import asyncio
from unittest.mock import AsyncMock, patch

from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.genai import types

from backend.agents.research_agent import research_agent


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

    print("\nStarting ADK runner with mocked CrewAI...")

    with patch(
        "backend.agents.research_agent.research_crew",
        mock_crew,
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

    print("\nPASS: ADK runner completed its event loop.")
    print("PASS: The mocked CrewAI research function was called.")
    print("PASS: No real CrewAI LLM request was made.")

    print("\n" + "=" * 70)
    print("ADK RUNNER MOCK TEST COMPLETED")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
