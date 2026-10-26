import asyncio

from dotenv import load_dotenv
from google.adk.apps import App, ResumabilityConfig
from google.adk.runners import InMemoryRunner

from backend.agents.workflow import root_agent


load_dotenv()


async def main() -> None:

    app = App(
    name="officepilot",
    root_agent=root_agent,
    resumability_config=ResumabilityConfig(
        is_resumable=True
    ),
)

    runner = InMemoryRunner(app=app)

    request = (
        "Prepare me for tomorrow's meeting with ABC Technologies. "
        "Find the important email context, relevant documents, "
        "and calendar information."
    )

    print("\n" + "=" * 80)
    print("OFFICEPILOT - PHASE 4")
    print("=" * 80)

    print("\nUSER REQUEST:")
    print(request)

    print("\n" + "-" * 80)
    print("EXECUTING MULTI-AGENT WORKFLOW...")
    print("-" * 80)

    response = await runner.run_debug(request)

    print("\n" + "=" * 80)
    print("FINAL RESPONSE")
    print("=" * 80)

    print(response)


if __name__ == "__main__":
    asyncio.run(main())