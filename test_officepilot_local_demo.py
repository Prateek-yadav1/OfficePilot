import asyncio
import os

from backend.tools.document_retriever import retrieve_documents
from backend.agents.action_executor import execute_followup_task_via_mcp


async def main():
    client = "ABC Technologies"
    tenant_id = os.getenv("OFFICEPILOT_LOCAL_TENANT_ID", "").strip()
    user_id = os.getenv("OFFICEPILOT_LOCAL_USER_ID", "").strip()
    if not tenant_id or not user_id:
        raise RuntimeError(
            "Set OFFICEPILOT_LOCAL_TENANT_ID and "
            "OFFICEPILOT_LOCAL_USER_ID before the demo."
        )

    print("\n" + "=" * 65)
    print("OFFICEPILOT - LOCAL INTEGRATION DEMO")
    print("=" * 65)

    # Step 1: Retrieve real documents from PostgreSQL + pgvector
    print("\n[1] Searching office documents...")

    documents = retrieve_documents(
        query="What did the client ask us to improve?",
        client=client,
        tenant_id=tenant_id,
        limit=3,
    )

    if not documents:
        print("No relevant documents found. Stopping.")
        return

    for document in documents:
        print(f"\nDocument: {document['title']}")
        print(f"Content: {document['content']}")
        print(f"Similarity: {document['relevance_score']}")

    # Step 2: Prepare a grounded follow-up proposal
    task_details = (
        "Follow up on the client's request for clearer "
        "deployment milestones."
    )

    print("\n[2] Follow-up action proposal")
    print(f"Client: {client}")
    print(f"Task: {task_details}")

    # Step 3: Ask for explicit human approval
    approval = input("\nApprove this action? (yes/no): ").strip().lower()

    if approval not in {"yes", "y"}:
        print("\nACTION NOT EXECUTED — approval not granted.")
        return

    # Step 4: Execute through the MCP server
    print("\n[3] Executing approved action through MCP...")

    result = await execute_followup_task_via_mcp(
        client=client,
        task_details=task_details,
        tenant_id=tenant_id,
        user_id=user_id,
    )

    print("\nMCP result:")
    print(result)

    print("\nLOCAL INTEGRATION DEMO COMPLETED")


if __name__ == "__main__":
    asyncio.run(main())