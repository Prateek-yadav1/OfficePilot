"""Offline end-to-end demonstration for OfficePilot.

LLM output and the research-agent response are scripted to avoid paid API calls.
Local email/calendar tools, PostgreSQL-backed document retrieval, and the MCP
stdio task tool are exercised by the workflow. The task server is a local mock,
not an external office/task-management integration.
"""

import asyncio
from datetime import date, timedelta
from typing import Any

from google.adk.apps import App
from google.adk.models import LlmCapabilities
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.adk.workflow import Workflow
from google.genai import types
from pydantic import Field

from backend.agents.action_executor import (
    action_executor_agent,
    execute_followup_task_via_mcp,
)
from backend.agents.action_proposal import action_proposal_agent
from backend.agents.aggregator import aggregator_agent
from backend.agents.analyst import analyst_agent
from backend.agents.briefing_agent import briefing_agent
from backend.agents.final_response import final_response_agent
from backend.agents.information_checker import information_checker
from backend.agents.parallel_agents import (
    calendar_agent,
    document_agent,
    email_agent,
)
from backend.agents.planner import planner_agent
from backend.agents.quality_checker import quality_checker
from backend.agents.research_agent import research_agent
from backend.agents.rework_agent import rework_agent
from backend.agents.router import quality_router_agent, router_agent
from backend.agents.workflow import root_agent


CLIENT = "ABC Technologies"
TODAY = date.today()
TOMORROW = TODAY + timedelta(days=1)
FOLLOWUP_DETAILS = (
    "Confirm the next meeting date and follow up on clearer deployment milestones."
)

# Filled by the test-only approval-gated tool. This stores the actual local MCP
# result (or a rejected/error status), not the scripted agent's summary.
OFFLINE_MCP_RESULT: dict[str, Any] | None = None


async def approved_offline_mcp_action(
    client: str,
    task_details: str,
) -> dict[str, Any]:
    """Test-only human gate followed by a real call to the local MCP server."""
    global OFFLINE_MCP_RESULT

    print("\n" + "=" * 75)
    print("HUMAN APPROVAL REQUIRED")
    print("=" * 75)
    print(f"Client: {client}")
    print(f"Proposed task: {task_details}")

    try:
        choice = input("Approve this local mock action? (yes/no): ").strip().lower()
    except EOFError:
        choice = "no"

    if choice not in {"yes", "y"}:
        OFFLINE_MCP_RESULT = {
            "status": "rejected",
            "message": "Human rejected the action. MCP was not called.",
        }
        print("\nACTION RESULT:")
        print(OFFLINE_MCP_RESULT)
        return OFFLINE_MCP_RESULT

    try:
        result = await execute_followup_task_via_mcp(
            client=client,
            task_details=task_details,
        )
        # Preserve the actual result from the MCP client. Do not manufacture a
        # success response if the MCP function raises or returns an error.
        OFFLINE_MCP_RESULT = result
    except Exception as exc:
        OFFLINE_MCP_RESULT = {
            "status": "error",
            "message": f"Local MCP execution failed: {type(exc).__name__}: {exc}",
        }

    print("\nACTUAL LOCAL MCP RESULT:")
    print(OFFLINE_MCP_RESULT)
    return OFFLINE_MCP_RESULT


class ScriptedModel(BaseLlm):
    """Deterministic model adapter for offline ADK workflow tests."""

    model: str = "officepilot-scripted"
    label: str
    steps: list[Any] = Field(default_factory=list)
    step_index: int = 0

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities()

    @classmethod
    def supported_models(cls) -> list[str]:
        return [r"officepilot-scripted"]

    async def generate_content_async(self, llm_request, stream: bool = False):
        if not self.steps:
            part = types.Part(text=f"{self.label}: no scripted response configured.")
        else:
            index = min(self.step_index, len(self.steps) - 1)
            step = self.steps[index]
            self.step_index += 1

            if isinstance(step, dict) and "tool" in step:
                part = types.Part(
                    function_call=types.FunctionCall(
                        id=f"{self.label}-{self.step_index}",
                        name=step["tool"],
                        args=step.get("args", {}),
                    )
                )
            else:
                part = types.Part(text=str(step))

        yield LlmResponse(
            content=types.Content(role="model", parts=[part])
        )


def script_agent(agent, *steps: Any) -> None:
    """Replace this agent's LLM with local scripted output for this test."""
    agent.model = ScriptedModel(label=agent.name, steps=list(steps))


def configure_offline_models() -> None:
    """Attach scripted responses to every agent used by the workflow."""

    script_agent(
        planner_agent,
        "Plan: search email, documents and calendar in parallel; aggregate "
        "findings; research missing information; analyze; prepare and validate "
        "the meeting briefing; then request approval for a follow-up task.",
    )

    # These agents execute their registered local tools before returning the
    # following scripted summary text.
    script_agent(
        email_agent,
        {"tool": "search_emails", "args": {"client": CLIENT}},
        "Email findings: Phase 2 requires ERP integration. The client also "
        "expressed concern about the previous deployment delay.",
    )

    script_agent(
        document_agent,
        {
            "tool": "retrieve_documents",
            "args": {
                "query": "What did the client ask us to improve?",
                "client": CLIENT,
            },
        },
        "Document findings: previous meeting notes request clearer deployment "
        "milestones. The proposal covers ERP integration and deployment "
        "improvements. The contract renews in December 2026.",
    )

    script_agent(
        calendar_agent,
        {"tool": "get_calendar", "args": {"client": CLIENT}},
        f"Calendar findings: the available meeting entry is dated "
        f"2026-09-19 at 11:00. This is before today ({TODAY}). No event for "
        f"tomorrow ({TOMORROW}) appears in the available data.",
    )

    script_agent(
        aggregator_agent,
        "Meeting context: emails identify ERP integration and previous "
        "deployment-delay concerns. Retrieved documents request clearer "
        "milestone tracking. The calendar contains a past meeting record, "
        "not a confirmed meeting for tomorrow.",
    )

    script_agent(
        information_checker,
        "MISSING: The next meeting date is not confirmed in the available "
        "calendar data. Deployment milestones and ownership also need clarification.",
    )
    script_agent(router_agent, "RESEARCH")

    # Scripted on purpose: this avoids making a live CrewAI/LLM call in this
    # no-credit demonstration.It is not evidence of live research execution.
    
    script_agent(
        research_agent,
        "OFFLINE TEST RESEARCH: scripted findings suggest clearer milestone "
        "tracking, explicit ownership, earlier testing and dependency tracking. "
        "The next meeting date remains unconfirmed.",
    )

    script_agent(
        analyst_agent,
        "Client priorities: complete ERP integration in Phase 2 and clarify "
        "deployment milestones. Client concern: previous deployment delay. "
        "The contract is scheduled for renewal in December 2026. Risk "
        "(INFERENCE): unclear owners and dates could make deployment progress "
        "harder to track. Confirm the next meeting date before scheduling.",
    )

    # The first draft intentionally omits Client Concerns to demonstrate the
    # quality-check -> revise -> rework -> pass path.
    script_agent(
        briefing_agent,
        f"""# Meeting Briefing

## Client
{CLIENT}

## Meeting Details
No meeting is confirmed for tomorrow ({TOMORROW}) in the available calendar
 data. The stored meeting entry is 2026-09-19 at 11:00, which is in the past.
Confirm the next meeting date and time.

## Key Client Priorities
- Complete ERP integration in Phase 2.
- Establish clearer deployment milestones and ownership.

## Important Facts
- An email dated 2026-09-05 requests ERP integration in Phase 2.
- Previous meeting notes request clearer deployment milestones.
- The enterprise contract is scheduled for renewal in December 2026.

## Additional Research
- Suggested improvements include earlier testing and dependency tracking.
  These findings are scripted for this offline test.

## Potential Risks
- INFERENCE: unclear milestone ownership and dates may make progress harder to track.

## Questions to Ask
- What is the confirmed date and time of the next meeting?
- Who owns each deployment milestone?
- What testing and dependency checks are required before deployment?

## Recommended Discussion Topics
- Phase 2 ERP integration.
- Deployment milestones, owners and dates.
- Previous deployment concerns and dependency tracking.

## Executive Summary
Focus on ERP integration and a more transparent deployment plan. Confirm the
next meeting date because the available calendar entry is historical.
""",
    )

    script_agent(
        quality_checker,
        "REVISE: The required Client Concerns section is missing.",
        "PASS",
    )
    script_agent(quality_router_agent, "REVISE", "PASS")

    script_agent(
        rework_agent,
        f"""# Meeting Briefing

## Client
{CLIENT}

## Meeting Details
No meeting is confirmed for tomorrow ({TOMORROW}) in the available calendar
 data. The stored meeting entry is 2026-09-19 at 11:00, which is in the past.
Confirm the next meeting date and time.

## Key Client Priorities
- Complete ERP integration in Phase 2.
- Establish clearer deployment milestones and ownership.

## Client Concerns
- The client expressed concern about the previous deployment delay.
- Previous meeting notes request clearer deployment milestones.

## Important Facts
- An email dated 2026-09-05 requests ERP integration in Phase 2.
- The contract is scheduled for renewal in December 2026.

## Additional Research
- Scripted offline test findings suggest earlier testing and dependency tracking.
- Live CrewAI research was not run in this offline demonstration.

## Potential Risks
- INFERENCE: unclear milestone ownership and dates may make deployment
  progress harder to track.

## Questions to Ask
- What is the confirmed date and time of the next meeting?
- Who owns each deployment milestone?
- What testing and dependency checks are required?

## Recommended Discussion Topics
- Phase 2 ERP integration.
- Deployment milestones, ownership and dates.
- Previous deployment concerns.

## Executive Summary
Confirm the next meeting date and agree on clear deployment milestones,
ownership, testing and dependency tracking.
""",
    )

    script_agent(
        action_proposal_agent,
        "Action Type: Create Follow-up Task\n"
        f"Client: {CLIENT}\n"
        f"Details: {FOLLOWUP_DETAILS}",
    )

    # Test-only override: do not use the production require_confirmation=True
    # tool here. The wrapper asks the user directly, then calls the same local
    # MCP client function once if and only if the user approves.
    action_executor_agent.tools = [
        FunctionTool(func=approved_offline_mcp_action)
    ]
    action_executor_agent.output_key = "action_executor_summary"
    script_agent(
        action_executor_agent,
        {
            "tool": "approved_offline_mcp_action",
            "args": {
                "client": CLIENT,
                "task_details": FOLLOWUP_DETAILS,
            },
        },
        "The approval-gated offline action step finished. Use the actual local "
        "MCP result printed by the test harness to determine whether execution "
        "succeeded; do not infer success from this scripted summary.",
    )

    script_agent(
        final_response_agent,
        "OFFLINE ADK WORKFLOW DEMO COMPLETED. Email, document/RAG and calendar "
        "tools were invoked; missing information was routed to a scripted "
        "research node; the briefing went through the quality rework path; "
        "and the human-gated local MCP action step was reached. Check the "
        "printed actual MCP result for the execution status. The available "
        "calendar data does not confirm a meeting for tomorrow.",
    )


def show_event(event) -> None:
    """Print model text and tool calls to make the workflow visible."""
    content = getattr(event, "content", None)
    if not content or not content.parts:
        return

    for part in content.parts:
        if part.text:
            print(f"\n[{event.author}] {part.text}")
        elif part.function_call:
            print(f"\n[{event.author}] TOOL CALL: {part.function_call.name}")


async def main() -> None:
    global OFFLINE_MCP_RESULT
    OFFLINE_MCP_RESULT = None

    configure_offline_models()

    offline_workflow = Workflow(
        name="officepilot_offline_demo",
        description=root_agent.description,
        edges=root_agent.edges,
    )
    offline_app = App(
        name="officepilot_offline_demo",
        root_agent=offline_workflow,
    )

    print("\n" + "=" * 75)
    print("OFFICEPILOT — OFFLINE ADK WORKFLOW DEMO")
    print("=" * 75)
    print("User request:")
    print(f"Prepare me for tomorrow's meeting with {CLIENT}.")
    print(f"Today: {TODAY} | Requested date: {TOMORROW}")
    print("LLM responses: scripted; OpenRouter calls: disabled.")
    print("Email/calendar tools and PostgreSQL-backed retrieval use local components.")
    print("The approved action calls the local MCP mock task server.")

    session_service = InMemorySessionService()
    user_id = "officepilot_demo_user"
    session_id = "officepilot_demo_session"

    runner = Runner(app=offline_app, session_service=session_service)
    await session_service.create_session(
        app_name=offline_app.name,
        user_id=user_id,
        session_id=session_id,
        state={
            "client_name": CLIENT,
            "information_status": (
                "MISSING: upcoming meeting date is not confirmed; "
                "verify deployment milestones."
            ),
        },
    )

    user_message = types.Content(
        role="user",
        parts=[
            types.Part.from_text(
                text=f"Prepare me for tomorrow's meeting with {CLIENT}."
            )
        ],
    )

    # Exactly one workflow invocation. The test-only tool handles approval
    # synchronously from this run, so no ADK confirmation-resume loop is needed.
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=user_message,
    ):
        show_event(event)

    session = await session_service.get_session(
        app_name=offline_app.name,
        user_id=user_id,
        session_id=session_id,
    )

    print("\n" + "=" * 75)
    print("FINAL WORKFLOW STATE CHECK")
    print("=" * 75)

    state_keys = [
        "email_context",
        "document_context",
        "calendar_context",
        "meeting_context",
        "research_context",
        "analysis_context",
        "final_briefing",
        "quality_status",
        "action_executor_summary",
    ]

    if session:
        for key in state_keys:
            value = session.state.get(key)
            print(f"\n{key}:")
            print(str(value)[:1000] if value is not None else "Not set")
    else:
        print("Session state could not be retrieved.")

    print("\naction_result (actual local MCP result):")
    if OFFLINE_MCP_RESULT is None:
        print("Not executed: the workflow did not reach the approval-gated tool.")
    else:
        print(OFFLINE_MCP_RESULT)

    print("\n" + "=" * 75)
    print("OFFLINE ADK WORKFLOW DEMO FINISHED")
    print("=" * 75)
    print(
        "Disclosure: model responses and research output were scripted to avoid "
        "API calls. The local MCP task server executes its mock implementation; "
        "no external task-management service is contacted."
    )


if __name__ == "__main__":
    asyncio.run(main())
