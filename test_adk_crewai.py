import asyncio

from dotenv import load_dotenv
from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.genai import types

from backend.agents.research_agent import research_agent


load_dotenv()


async def main():

    print("\n" + "=" * 80)
    print("OFFICEPILOT - PHASE 6 ADK + CREWAI INTEGRATION TEST")
    print("=" * 80)

    app = App(
        name="officepilot_adk_crewai_test",
        root_agent=research_agent,
    )

    runner = InMemoryRunner(app=app)

    user_id = "test_user"
    session_id = "adk_crewai_test_session"

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

    print("\nSESSION CREATED:")
    print(session.id)

    request = """
Prepare additional research for ABC Technologies.

The missing information is:
deployment milestones and previous deployment concerns.
"""

    print("\nUSER REQUEST:")
    print(request)

    print("\n" + "-" * 80)
    print("STARTING ADK RESEARCH AGENT...")
    print("-" * 80)

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[
                types.Part(
                    text=request
                )
            ],
        ),
    ):

        if event.content and event.content.parts:

            for part in event.content.parts:

                if part.text:

                    print("\nADK RESPONSE:")
                    print(part.text)

    print("\n" + "=" * 80)
    print("ADK + CREWAI INTEGRATION TEST COMPLETED")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())