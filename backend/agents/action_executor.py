
import asyncio
import sys
from pathlib import Path

from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import get_model


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MCP_SERVER = PROJECT_ROOT / "backend" / "tools" / "mcp_server.py"


async def execute_followup_task_via_mcp(
    client: str,
    task_details: str,
) -> dict:
    """Execute the follow-up task through the OfficePilot MCP server."""

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(MCP_SERVER)],
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(
                "create_followup_task",
                {
                    "client": client,
                    "task_details": task_details,
                },
            )

            if result.isError:
                raise RuntimeError("MCP follow-up task execution failed")

            return {
                "status": "success",
                "message": "MCP tool executed successfully.",
                "result": [
                    item.text
                    for item in result.content
                    if hasattr(item, "text")
                ],
            }


approved_followup_task = FunctionTool(
    func=execute_followup_task_via_mcp,
    require_confirmation=True,
)


action_executor_agent = Agent(
    name="action_executor_agent",
    model=get_model(),
    description=(
        "Executes a proposed office action only after "
        "explicit human approval."
    ),
    instruction="""
You are the Action Executor Agent in OfficePilot.

Read the action proposal from {action_proposal}.
Extract the client name and task details.

Call the protected follow-up task tool with those values.
ADK must request explicit human confirmation before execution.

If approved and the tool succeeds, report success.
If rejected, report ACTION NOT EXECUTED.
Never claim success unless the tool returns successfully.
""",
    tools=[approved_followup_task],
    output_key="action_result",
)
