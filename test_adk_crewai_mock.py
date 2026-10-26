
import asyncio
from unittest.mock import AsyncMock, patch

from backend.agents.research_agent import run_crewai_research


async def main():
    print("\n" + "=" * 70)
    print("OFFICEPILOT - MOCK ADK + CREWAI INTEGRATION TEST")
    print("=" * 70)

    client = "ABC Technologies"
    missing_information = (
        "deployment milestones and previous deployment concerns"
    )

    mock_result = (
        "Research completed for ABC Technologies. "
        "Key findings: clarify deployment milestones, identify owners, "
        "and review previous deployment delays."
    )

    # Create a simple mock object instead of modifying CrewAI's Crew instance.
    mock_crew = type("MockCrew", (), {})()
    mock_crew.kickoff_async = AsyncMock(return_value=mock_result)

    print("\nStarting mocked research call...")

    with patch(
        "backend.agents.research_agent.research_crew",
        mock_crew,
    ):
        result = await run_crewai_research(
            client=client,
            missing_information=missing_information,
        )

    # Verify the returned result.
    assert result == mock_result, (
        f"Unexpected result: {result}"
    )

    # Verify that the mock received the expected inputs.
    mock_crew.kickoff_async.assert_awaited_once_with(
        inputs={
            "client": client,
            "missing_information": missing_information,
        }
    )

    print("\nMock research result:")
    print(result)

    print("\nPASS: Research function returned the expected result.")
    print("PASS: CrewAI received the expected inputs.")
    print("PASS: The external LLM was not called.")

    print("\n" + "=" * 70)
    print("MOCK INTEGRATION TEST COMPLETED SUCCESSFULLY")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
