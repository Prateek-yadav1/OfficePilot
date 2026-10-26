
import asyncio
from types import SimpleNamespace

from google.adk.tools import FunctionTool
from google.adk.tools.tool_confirmation import ToolConfirmation
from backend.tools.mock_office import execute_followup_task


async def main():
    print("=" * 60)
    print("OFFICEPILOT - HITL TOOL GATE TEST")
    print("=" * 60)

    calls = []

    def tracked_execute(client: str, task_details: str) -> dict:
        calls.append({
            "client": client,
            "task_details": task_details,
        })
        return execute_followup_task(
            client=client,
            task_details=task_details,
        )

    protected_tool = FunctionTool(
        func=tracked_execute,
        require_confirmation=True,
    )

    confirmation_requests = []

    def request_confirmation(*, hint=""):
        confirmation_requests.append(hint)

    # Use a lightweight context instead of assigning to ADK's
    # read-only ToolContext.actions property.
    context = SimpleNamespace(
        tool_confirmation=None,
        actions=SimpleNamespace(skip_summarization=False),
        request_confirmation=request_confirmation,
    )

    args = {
        "client": "ABC Technologies",
        "task_details": "Review deployment milestones before the next meeting.",
    }

    # Test 1: No confirmation
    print("\nTEST 1: No confirmation")

    result = await protected_tool.run_async(
        args=args,
        tool_context=context,
    )

    assert "error" in result, result
    assert len(confirmation_requests) == 1
    assert len(calls) == 0

    print("PASS: Execution blocked pending confirmation.")

    # Test 2: Rejection
    print("\nTEST 2: Rejection")

    context.tool_confirmation = ToolConfirmation(confirmed=False)

    result = await protected_tool.run_async(
        args=args,
        tool_context=context,
    )

    assert "error" in result, result
    assert len(calls) == 0

    print("PASS: Rejected action was not executed.")

    # Test 3: Approval
    print("\nTEST 3: Approval")

    context.tool_confirmation = ToolConfirmation(confirmed=True)

    result = await protected_tool.run_async(
        args=args,
        tool_context=context,
    )

    assert result["status"] == "success", result
    assert len(calls) == 1, calls

    print("PASS: Approved action executed exactly once.")
    print("Result:", result)

    print("\n" + "=" * 60)
    print("ALL HITL TOOL GATE TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
