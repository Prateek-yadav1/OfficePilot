import json
import time
from datetime import datetime, time as datetime_time
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _load_json(filename: str):
    with open(DATA_DIR / filename, "r", encoding="utf-8") as file:
        return json.load(file)


def _tenant_rows(rows: list[dict], tenant_id: str | None) -> list[dict]:
    if tenant_id is None:
        return rows
    return [
        row
        for row in rows
        if isinstance(row, dict) and row.get("tenant_id") == tenant_id
    ]


def _workspace_rows(
    rows: list[dict],
    tenant_id: str | None,
    user_id: str | None,
) -> list[dict]:
    if tenant_id is None:
        return rows
    if user_id is None:
        return []
    return [
        row
        for row in _tenant_rows(rows, tenant_id)
        if row.get("user_id") == user_id
    ]


def list_mock_clients(tenant_id: str) -> list[str]:
    """Return client labels from documents assigned to one tenant fixture."""
    return sorted(
        {
            str(item["client"])
            for item in _tenant_rows(_load_json("documents.json"), tenant_id)
            if isinstance(item, dict) and item.get("client")
        },
        key=str.casefold,
    )


def search_emails(
    client: str,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> dict:
    """
    Search the company email system for messages related to a client.
    """

    start = time.perf_counter()

    # Simulate network/API latency.
    time.sleep(2)

    emails = [
        item
        for item in _workspace_rows(
            _load_json("emails.json"),
            tenant_id,
            user_id,
        )
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


def search_documents(client: str, tenant_id: str | None = None) -> dict:
    """
    Search the company document system for documents related to a client.
    """

    start = time.perf_counter()

    time.sleep(2)

    documents = [
        item
        for item in _tenant_rows(_load_json("documents.json"), tenant_id)
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


def get_calendar(
    client: str,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> dict:
    """
    Search the company calendar for meetings involving a client.
    """

    start = time.perf_counter()

    time.sleep(2)

    meetings = [
        item
        for item in _workspace_rows(
            _load_json("calendar.json"),
            tenant_id,
            user_id,
        )
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


def discover_next_meeting(
    now: datetime | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> dict:
    """Return the earliest future mock calendar event across all clients."""
    current_time = now or datetime.now().astimezone()
    events = _workspace_rows(
        _load_json("calendar.json"),
        tenant_id,
        user_id,
    )
    upcoming: list[tuple[datetime, dict]] = []

    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(
                f"Invalid mock calendar event at index {index}: expected an object."
            )
        try:
            event_date = datetime.fromisoformat(event["date"]).date()
            if event.get("time"):
                event_start = datetime.combine(
                    event_date,
                    datetime_time.fromisoformat(event["time"]),
                )
                if event_start.tzinfo is None:
                    event_start = event_start.replace(tzinfo=current_time.tzinfo)
                if event_start <= current_time:
                    continue
            else:
                event_start = datetime.combine(
                    event_date,
                    datetime_time.min,
                    tzinfo=current_time.tzinfo,
                )
                if event_date < current_time.date():
                    continue
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid mock calendar event at index {index}: "
                "date or time is missing or malformed."
            ) from exc

        upcoming.append((event_start, event))

    if not upcoming:
        return {
            "source": "mock_calendar",
            "status": "not_found",
            "meeting": None,
        }

    start, event = min(upcoming, key=lambda item: item[0])
    return {
        "source": "mock_calendar",
        "status": "found",
        "meeting": {
            **event,
            "start": start.isoformat(),
        },
    }
#phase 2

def research_client(client: str, missing_information: str) -> dict:
    """
    Retrieve mock research findings for any client.

    Client-specific research is stored separately in research.json.
    Unknown clients return no findings instead of fabricated information.
    """

    start = time.perf_counter()

    # Simulate mock research latency.
    time.sleep(2)

    research_database = _load_json("research.json")

    if not isinstance(research_database, dict):
        raise ValueError("research.json must contain a JSON object.")

    # Match client names without case sensitivity.
    normalized_client = str(client).strip().casefold()

    client_data = next(
        (
            data
            for name, data in research_database.items()
            if name.strip().casefold() == normalized_client
            and isinstance(data, dict)
        ),
        {},
    )

    findings = {}
    missing_lower = str(missing_information).casefold()

    # Match only research topics actually available for this client.
    for topic, information in client_data.items():
        topic_words = topic.replace("_", " ").casefold()

        if topic_words in missing_lower:
            findings[topic] = information

    # Handle common specific research requests safely.
    optional_topic_checks = {
        "agenda": "meeting_agenda",
        "cto": "cto",
        "product manager": "product_manager",
    }

    for search_term, topic_key in optional_topic_checks.items():
        if search_term in missing_lower and topic_key in client_data:
            findings[topic_key] = client_data[topic_key]

    elapsed = round(time.perf_counter() - start, 2)

    return {
        "source": "mock_research_fixture",
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