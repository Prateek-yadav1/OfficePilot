import asyncio

from dotenv import load_dotenv
from google.adk.apps import App, ResumabilityConfig
from google.adk.runners import InMemoryRunner
from google.genai import types

from backend.agents.action_executor import action_executor_agent


load_dotenv()


async def main():

    print("\n" + "=" * 80)
    print("OFFICEPILOT - PHASE 5 HITL TEST")
    print("=" * 80)

    app = App(
        name="officepilot_hitl_test",
        root_agent=action_executor_agent,
        resumability_config=ResumabilityConfig(
            is_resumable=True
        ),
    )

    runner = InMemoryRunner(app=app)

    # ---------------------------------------------------------
    # CREATE SESSION
    # ---------------------------------------------------------

    user_id = "test_user"

    session = await runner.session_service.create_session(
        app_name=app.name,
        user_id=user_id,
        session_id="hitl_test_session",
    )

    session_id = session.id

    print("\nSESSION CREATED:")
    print(session_id)

    request = """
Create a follow-up task for ABC Technologies.

The task should be:
Review the Phase 2 ERP integration deployment milestones
and prepare the required follow-up discussion points.
"""

    print("\nUSER REQUEST:")
    print(request)

    print("\n" + "-" * 80)
    print("STARTING ACTION EXECUTOR...")
    print("-" * 80)

    events = []

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=types.Content(
            role="user",
            parts=[
                types.Part(
                    text=request
                )
            ],
        ),
    ):

        events.append(event)

        print("\nEVENT:")
        print(event)

        # Detect ADK human confirmation request
        if event.content and event.content.parts:

            for part in event.content.parts:

                if (
                    part.function_call
                    and part.function_call.name
                    == "adk_request_confirmation"
                ):

                    confirmation_call = part.function_call

                    print("\n" + "=" * 80)
                    print("⏸ HUMAN APPROVAL REQUIRED")
                    print("=" * 80)

                    print("\nCONFIRMATION REQUEST:")
                    print(confirmation_call.args)

                    print("\n" + "-" * 80)
                    print("Type APPROVE or REJECT")
                    print("-" * 80)

                    decision = input(
                    "\nYour decision: "
                    ).strip().upper()

                    confirmed = decision in {"APPROVE", "YES", "Y"}

                    print(
                        f"\nHuman decision: "
                        f"{'APPROVED' if confirmed else 'REJECTED'}"
                    )

                    # Build confirmation response
                    confirmation_response = types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                function_response=types.FunctionResponse(
                                    id=confirmation_call.id,
                                    name="adk_request_confirmation",
                                    response={
                                        "confirmed": confirmed
                                    },
                                )
                            )
                        ],
                    )

                    print("\n" + "-" * 80)
                    print("RESUMING WORKFLOW...")
                    print("-" * 80)

                    async for resumed_event in runner.run_async(
                        user_id=user_id,
                        session_id=session_id,
                        invocation_id=event.invocation_id,
                        new_message=confirmation_response,
                    ):

                        print("\nRESUMED EVENT:")
                        print(resumed_event)

    print("\n" + "=" * 80)
    print("HITL TEST FINISHED")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())