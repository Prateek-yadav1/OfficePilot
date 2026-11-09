
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    tenant_id = os.getenv("OFFICEPILOT_LOCAL_TENANT_ID", "").strip()
    user_id = os.getenv("OFFICEPILOT_LOCAL_USER_ID", "").strip()
    if not tenant_id or not user_id:
        raise RuntimeError(
            "Set OFFICEPILOT_LOCAL_TENANT_ID and OFFICEPILOT_LOCAL_USER_ID "
            "before running the MCP smoke test."
        )
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["backend/tools/mcp_server.py"],
        env=os.environ.copy(),
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("Available tools:", [tool.name for tool in tools.tools])
            assert "discover_next_meeting" in {
                tool.name for tool in tools.tools
            }

            discovery = await session.call_tool(
                "discover_next_meeting",
                {"tenant_id": tenant_id, "user_id": user_id},
            )
            if discovery.isError:
                raise RuntimeError(
                    "MCP next-meeting discovery failed: "
                    f"{discovery.content}"
                )
            print("Next meeting discovery:", discovery.content)

            assert "create_followup_task" in {
                tool.name for tool in tools.tools
            }


if __name__ == "__main__":
    asyncio.run(main())
