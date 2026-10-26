import json
import time
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _load_json(filename: str):
    with open(DATA_DIR / filename, "r", encoding="utf-8") as file:
        return json.load(file)


def search_emails(client: str) -> dict:
    """
    Search the company email system for messages related to a client.
    """

    start = time.perf_counter()

    # Simulate network/API latency.
    time.sleep(2)

    emails = [
        item
        for item in _load_json("emails.json")
        if item["client"].lower() == client.lower()
    ]

    elapsed = round(time.perf_counter() - start, 2)

    return {
        "source": "mock_email_system",
        "client": client,
        "count": len(emails),
        "emails": emails,
        "elapsed_seconds": elapsed,
    }


def search_documents(client: str) -> dict:
    """
    Search the company document system for documents related to a client.
    """

    start = time.perf_counter()

    time.sleep(2)

    documents = [
        item
        for item in _load_json("documents.json")
        if item["client"].lower() == client.lower()
    ]

    elapsed = round(time.perf_counter() - start, 2)

    return {
        "source": "mock_document_system",
        "client": client,
        "count": len(documents),
        "documents": documents,
        "elapsed_seconds": elapsed,
    }


def get_calendar(client: str) -> dict:
    """
    Search the company calendar for meetings involving a client.
    """

    start = time.perf_counter()

    time.sleep(2)

    meetings = [
        item
        for item in _load_json("calendar.json")
        if item["client"].lower() == client.lower()
    ]

    elapsed = round(time.perf_counter() - start, 2)

    return {
        "source": "mock_calendar",
        "client": client,
        "count": len(meetings),
        "meetings": meetings,
        "elapsed_seconds": elapsed,
    }
#phase 2
def research_client(client: str, missing_information: str) -> dict:
    """
    Simulates external research for missing client information.
    """

    start = time.perf_counter()

    time.sleep(2)

    research_database = {
        "ABC Technologies": {
            "deployment_delay": (
                "The previous deployment delay was associated with "
                "integration testing and dependency issues."
            ),
            "deployment_improvements": (
                "The proposed deployment improvements include clearer "
                "milestones, earlier testing, and dependency tracking."
            ),
            "deployment_milestones": (
                "The client expects milestone-based deployment tracking "
                "with clear ownership and dates."
            ),
            "meeting_agenda": (
                "The meeting agenda includes Phase 2 progress, "
                "ERP integration planning, deployment improvements, "
                "and resolution of previous deployment concerns."
            ),
            "cto": (
                "The ABC Technologies CTO is responsible for "
                "technical strategy and ERP integration decisions."
            ),
            "product_manager": (
                "The ABC Technologies Product Manager is responsible "
                "for product requirements and Phase 2 coordination."
            ),
        }
    }

    client_data = research_database.get(client, {})

    findings = {}

    missing_lower = missing_information.lower()

    # Look for relevant research topics.
    for topic, information in client_data.items():

        topic_words = topic.replace("_", " ").lower()

        if (
            topic_words in missing_lower
            or topic_words.split()[0] in missing_lower
        ):
            findings[topic] = information

    # If the checker reports an agenda or participant-name issue,
    # provide the corresponding available research.
    if "agenda" in missing_lower:
        findings["meeting_agenda"] = client_data["meeting_agenda"]

    if "cto" in missing_lower:
        findings["cto"] = client_data["cto"]

    if "product manager" in missing_lower:
        findings["product_manager"] = client_data["product_manager"]

    elapsed = round(time.perf_counter() - start, 2)

    return {
        "source": "mock_external_research",
        "client": client,
        "query": missing_information,
        "findings": findings,
        "elapsed_seconds": elapsed,
    }
def execute_followup_task(client: str, task_details: str) -> dict:
    """
    Simulates execution of a follow-up task.
    """

    return {
        "status": "success",
        "action": "followup_task_created",
        "client": client,
        "task_details": task_details,
        "message": (
            f"Follow-up task successfully created for {client}."
        ),
    }