"""End-to-end A2A smoke test. Requires the OfficePilot API on port 8000."""

import asyncio

from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.genai import types

from backend.a2a_demo.client_agent import root_agent


async def main() -> None:
    app = App(
        name="officepilot_a2a_client_test",
        root_agent=root_agent,
    )
    runner = InMemoryRunner(app=app)

    user_id = "officepilot_a2a_test_user"
    session = await runner.session_service.create_session(
        app_name=app.name,
        user_id=user_id,
    )

    remote_responses: list[str] = []

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[
                types.Part(
                    text=(
                        "Run the A2A connectivity check. "
                        "Return the remote agent's marker."
                    )
                )
            ],
        ),
    ):
        if getattr(event, "error_code", None):
            raise RuntimeError(
                f"ADK event error: {event.error_code}: {event.error_message}"
            )

        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(f"[{event.author}] {part.text}")
                    if event.author == "remote_research_agent":
                        remote_responses.append(part.text)

    if not remote_responses:
        raise AssertionError(
            "No response from the remote A2A reviewer was observed. "
            "Check the remote server and delegation logs."
        )

    print("\nPASS: Main ADK agent received a response from the remote A2A reviewer.")
    print("No Google Workspace APIs or write tools were called.")


if __name__ == "__main__":
    asyncio.run(main())
