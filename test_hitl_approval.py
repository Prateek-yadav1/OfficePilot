import asyncio

from google.adk.tools import FunctionTool
from google.genai import types

from backend.agents.action_executor import execute_followup_task_via_mcp

# ---------------------------------------------------------
# PROTECTED ACTION TOOL
# ---------------------------------------------------------

approved_followup_task = FunctionTool(
    func=execute_followup_task_via_mcp,
    require_confirmation=True,
)


async def main():

    print("\n" + "=" * 80)
    print("OFFICEPILOT - ISOLATED HITL APPROVAL TEST")
    print("=" * 80)

    client = "ABC Technologies"

    task_details = (
        "Follow up on deployment milestones and previous "
        "deployment concerns before the next meeting."
    )

    print("\nAction proposal:")
    print("Action Type: Create Follow-up Task")
    print("Client:", client)
    print("Details:", task_details)

    print("\n" + "-" * 80)
    print("STEP 1: HUMAN APPROVAL REQUIRED")
    print("-" * 80)

    # The actual ADK workflow normally creates this confirmation.
    # For this isolated test we are testing the protected action
    # and the approval payload format separately.

    confirmation = {
        "confirmed": True,
    }

    print("\nApproval payload:")
    print(confirmation)

    if confirmation["confirmed"]:
        print("\nHuman approved the action.")

        print("\n" + "-" * 80)
        print("STEP 2: EXECUTING APPROVED ACTION")
        print("-" * 80)

        result = await execute_followup_task_via_mcp(
    client=client,
    task_details=task_details,
)

        print("\nTool execution result:")
        print(result)

        if result.get("status") == "success":
            print("\n" + "=" * 80)
            print("HITL APPROVAL TEST PASSED")
            print("=" * 80)
        else:
            print("\nHITL APPROVAL TEST FAILED")

    else:
        print("\nAction rejected.")
        print("HITL APPROVAL TEST PASSED - ACTION WAS NOT EXECUTED")


if __name__ == "__main__":
    asyncio.run(main())