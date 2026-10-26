
from mcp.server.fastmcp import FastMCP

from mock_office import execute_followup_task
mcp = FastMCP("OfficePilot Tools")


@mcp.tool()
def create_followup_task(client: str, task_details: str) -> dict:
    """Create a follow-up task for a client."""
    return execute_followup_task(
        client=client,
        task_details=task_details,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
