"""Google Workspace helpers for OfficePilot.

Requires a root-level credentials.json and token.json created by the
OfficePilot Google API smoke test. This module does not launch OAuth flows;
re-authorize with the smoke-test script if the stored token is missing scopes.

Gmail and Calendar are read-only. Google Tasks creation is a write operation
and should only be called through OfficePilot's ADK confirmation-gated action.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CREDENTIALS_FILE = PROJECT_ROOT / "credentials.json"
TOKEN_FILE = PROJECT_ROOT / "token.json"
SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
)
if os.getenv("OFFICEPILOT_ALLOW_GOOGLE_TASK_WRITES", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}:
    SCOPES += ("https://www.googleapis.com/auth/tasks",)


def _user_token_file(user_id: str) -> Path:
    """Resolve the OAuth token for one authenticated Workspace user."""
    raw_mapping = os.getenv("OFFICEPILOT_WORKSPACE_TOKEN_FILES", "").strip()
    if not raw_mapping:
        raise RuntimeError(
            "OFFICEPILOT_WORKSPACE_TOKEN_FILES must map each user to a token file."
        )
    try:
        mapping = json.loads(raw_mapping)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "OFFICEPILOT_WORKSPACE_TOKEN_FILES must be valid JSON."
        ) from exc
    if not isinstance(mapping, dict) or not isinstance(mapping.get(user_id), str):
        raise PermissionError(
            "No Google Workspace connection is configured for this user."
        )
    resolved_paths = [
        Path(value).expanduser().resolve()
        for value in mapping.values()
        if isinstance(value, str)
    ]
    token_file = Path(mapping[user_id]).expanduser().resolve()
    if resolved_paths.count(token_file) > 1:
        raise RuntimeError(
            "Google Workspace token files must not be shared across users."
        )
    if token_file == TOKEN_FILE.resolve():
        raise RuntimeError(
            "The shared legacy token.json cannot be used for user-scoped access."
        )
    if token_file.is_file():
        try:
            token_file.chmod(0o600)
        except OSError as exc:
            raise RuntimeError(
                "Could not apply private permissions to the user's Workspace token."
            ) from exc
    return token_file


def _load_credentials(user_id: str) -> Credentials:
    """Load a user-specific authorized token without opening a browser."""
    if not CREDENTIALS_FILE.is_file():
        raise FileNotFoundError(
            f"Google OAuth client file not found: {CREDENTIALS_FILE}. "
            "Place your credentials.json in the OfficePilot project root."
        )
    token_file = _user_token_file(user_id)
    if not token_file.is_file():
        raise FileNotFoundError(
            "Google OAuth token for the configured tenant was not found."
        )

    try:
        token_info = json.loads(token_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Could not read token.json. Re-run python test_google_apis.py to authorize."
        ) from exc

    granted_scopes = set(token_info.get("scopes", []))
    missing = set(SCOPES) - granted_scopes
    if missing:
        names = ", ".join(sorted(missing))
        raise RuntimeError(
            f"Google token is missing required scopes: {names}. "
            "Re-run python test_google_apis.py and approve the requested permissions."
        )

    try:
        creds = Credentials.from_authorized_user_file(
            str(token_file),
            scopes=list(SCOPES),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Could not load token.json. Re-run python test_google_apis.py to authorize."
        ) from exc

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                token_file.write_text(creds.to_json(), encoding="utf-8")
                try:
                    token_file.chmod(0o600)
                except OSError:
                    pass
            except RefreshError as exc:
                raise RuntimeError(
                    "Google OAuth token refresh failed. Run python test_google_apis.py "
                    "again to re-authorize."
                ) from exc
        else:
            raise RuntimeError(
                "Google OAuth token is invalid. Run python test_google_apis.py again."
            )
    return creds


@lru_cache(maxsize=128)
def _gmail_service(user_id: str):
    return build(
        "gmail",
        "v1",
        credentials=_load_credentials(user_id),
        cache_discovery=False,
    )


@lru_cache(maxsize=128)
def _calendar_service(user_id: str):
    return build(
        "calendar",
        "v3",
        credentials=_load_credentials(user_id),
        cache_discovery=False,
    )


@lru_cache(maxsize=128)
def _tasks_service(user_id: str):
    return build(
        "tasks",
        "v1",
        credentials=_load_credentials(user_id),
        cache_discovery=False,
    )


def search_emails(
    client: str,
    user_id: str,
    max_results: int = 10,
) -> dict[str, Any]:
    """Search Gmail inbox messages for a client name; return metadata and snippets only."""
    started = time.perf_counter()
    client = client.strip()
    if not client:
        raise ValueError("client must not be empty")
    limit = max(1, min(int(max_results), 20))
    query = f'in:inbox "{client.replace(chr(34), chr(92) + chr(34))}"'
    gmail = _gmail_service(user_id)
    response = gmail.users().messages().list(
        userId="me", q=query, maxResults=limit
    ).execute()
    messages = []
    for item in response.get("messages", []):
        message = gmail.users().messages().get(
            userId="me",
            id=item["id"],
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        headers = {
            header.get("name", "").lower(): header.get("value", "")
            for header in message.get("payload", {}).get("headers", [])
        }
        messages.append(
            {
                "id": message.get("id", item["id"]),
                "thread_id": message.get("threadId", ""),
                "from": headers.get("from", ""),
                "subject": headers.get("subject", "(no subject)"),
                "date": headers.get("date", ""),
                "snippet": message.get("snippet", ""),
            }
        )
    return {
        "source": "google_gmail",
        "client": client,
        "query": query,
        "count": len(messages),
        "emails": messages,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }


def get_calendar(
    client: str,
    user_id: str,
    days_ahead: int = 30,
    max_results: int = 10,
) -> dict[str, Any]:
    """Find matching events on the primary Calendar in the next N days."""
    started = time.perf_counter()
    client = client.strip()
    if not client:
        raise ValueError("client must not be empty")
    days = max(1, min(int(days_ahead), 90))
    limit = max(1, min(int(max_results), 100))
    now = datetime.now(timezone.utc)
    calendar = _calendar_service(user_id)
    response = calendar.events().list(
        calendarId="primary",
        timeMin=now.isoformat(),
        timeMax=(now + timedelta(days=days)).isoformat(),
        q=client,
        singleEvents=True,
        orderBy="startTime",
        maxResults=limit,
    ).execute()
    meetings = []
    for event in response.get("items", []):
        start = event.get("start", {})
        end = event.get("end", {})
        meetings.append(
            {
                "id": event.get("id", ""),
                "title": event.get("summary", "(no title)"),
                "start": start.get("dateTime", start.get("date", "")),
                "end": end.get("dateTime", end.get("date", "")),
                "time_zone": start.get("timeZone", ""),
                "location": event.get("location", ""),
                "description": event.get("description", ""),
                "participants": [
                    attendee.get("displayName") or attendee.get("email", "")
                    for attendee in event.get("attendees", [])
                ],
                "html_link": event.get("htmlLink", ""),
            }
        )
    return {
        "source": "google_calendar",
        "client": client,
        "count": len(meetings),
        "meetings": meetings,
        "window_days": days,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }


def discover_next_meeting(
    user_id: str,
    days_ahead: int = 90,
) -> dict[str, Any]:
    """Return the earliest upcoming event from the primary Google Calendar."""
    started = time.perf_counter()
    days = max(1, min(int(days_ahead), 180))
    now = datetime.now(timezone.utc)
    response = _calendar_service(user_id).events().list(
        calendarId="primary",
        timeMin=now.isoformat(),
        timeMax=(now + timedelta(days=days)).isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=100,
    ).execute()

    events = response.get("items", [])
    if not events:
        return {
            "source": "google_calendar",
            "status": "not_found",
            "meeting": None,
            "window_days": days,
            "elapsed_seconds": round(time.perf_counter() - started, 2),
        }

    event = events[0]
    start = event.get("start", {})
    end = event.get("end", {})
    meeting = {
        "id": event.get("id", ""),
        "title": event.get("summary", "(no title)"),
        "start": start.get("dateTime", start.get("date", "")),
        "end": end.get("dateTime", end.get("date", "")),
        "time_zone": start.get("timeZone", ""),
        "location": event.get("location", ""),
        "description": event.get("description", ""),
        "participants": [
            attendee.get("displayName") or attendee.get("email", "")
            for attendee in event.get("attendees", [])
        ],
    }
    return {
        "source": "google_calendar",
        "status": "found",
        "meeting": meeting,
        "window_days": days,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }


def create_followup_task(
    client: str,
    task_details: str,
    user_id: str,
) -> dict[str, Any]:
    """Create a Google Task. Call only after explicit human approval."""
    started = time.perf_counter()
    client = client.strip()
    task_details = task_details.strip()
    if not client:
        raise ValueError("client must not be empty")
    if not task_details:
        raise ValueError("task_details must not be empty")
    title = f"Follow up: {client}"
    task = _tasks_service(user_id).tasks().insert(
        tasklist="@default",
        body={"title": title, "notes": task_details},
    ).execute()
    return {
        "source": "google_tasks",
        "status": "success",
        "action": "followup_task_created",
        "client": client,
        "task_details": task_details,
        "task_id": task.get("id", ""),
        "title": task.get("title", title),
        "message": f"Google Task created for {client}.",
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }


def reset_service_cache() -> None:
    """Clear cached API service objects (useful for tests)."""
    _gmail_service.cache_clear()
    _calendar_service.cache_clear()
    _tasks_service.cache_clear()
