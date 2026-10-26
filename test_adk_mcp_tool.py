
import asyncio
import json

from backend.agents.action_executor import execute_followup_task_via_mcp


async def main():
    result = await execute_followup_task_via_mcp(
        client="ABC Technologies",
        task_details="Test MCP integration from OfficePilot.",
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
