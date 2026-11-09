
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
    mock_a2a_review = AsyncMock(
        return_value=(
            "A2A reviewer received the submitted research context. "
            "No factual claims were independently verified."
        )
    )

    print("\nStarting mocked research call...")

    with (
        patch(
            "backend.agents.research_agent.create_research_crew",
            return_value=mock_crew,
        ),
        patch(
            "backend.agents.research_agent._review_with_a2a",
            mock_a2a_review,
        ),
    ):
        result = await run_crewai_research(
            client=client,
            missing_information=missing_information,
        )

    assert f"CrewAI research report:\n{mock_result}" in result
    assert "No factual claims were independently verified." in result

    # Verify that the mock received the expected inputs.
    mock_crew.kickoff_async.assert_awaited_once_with(
        inputs={
            "client": client,
            "missing_information": missing_information,
            "retrieved_context": (
                "No tenant-scoped retrieval context was available."
            ),
        }
    )
    mock_a2a_review.assert_awaited_once()

    print("\nMock research result:")
    print(result)

    print("\nPASS: Research function returned the CrewAI and A2A results.")
    print("PASS: CrewAI received the expected inputs.")
    print("PASS: The A2A review was invoked and returned the verification warning.")
    print("PASS: The external LLM was not called.")

    print("\n" + "=" * 70)
    print("MOCK INTEGRATION TEST COMPLETED SUCCESSFULLY")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
