
import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["backend/tools/mcp_server.py"],
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("Available tools:", [tool.name for tool in tools.tools])

            result = await session.call_tool(
                "create_followup_task",
                {
                    "client": "ABC Technologies",
                    "task_details": "Review deployment milestones before the next meeting.",
                },
            )

            print("Tool result:", result)


if __name__ == "__main__":
    asyncio.run(main())
