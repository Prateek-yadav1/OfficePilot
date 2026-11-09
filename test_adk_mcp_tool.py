
import asyncio
import json
import os

from backend.agents.action_executor import execute_followup_task_via_mcp


async def main():
    tenant_id = os.getenv("OFFICEPILOT_LOCAL_TENANT_ID", "").strip()
    user_id = os.getenv("OFFICEPILOT_LOCAL_USER_ID", "").strip()
    if not tenant_id or not user_id:
        raise RuntimeError(
            "Set OFFICEPILOT_LOCAL_TENANT_ID and OFFICEPILOT_LOCAL_USER_ID."
        )
    result = await execute_followup_task_via_mcp(
        client="ABC Technologies",
        task_details="Test MCP integration from OfficePilot.",
        tenant_id=tenant_id,
        user_id=user_id,
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
