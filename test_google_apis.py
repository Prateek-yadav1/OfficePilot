"""OfficePilot Google Workspace OAuth smoke test.

This script authenticates a desktop app with Gmail read-only, Calendar
read-only, and (only when task writes are explicitly enabled) Google Tasks
permissions. It prints counts only, not message subjects, event titles, task
names, or account identifiers.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

PROJECT_ROOT = Path(__file__).resolve().parent
CREDENTIALS_FILE = PROJECT_ROOT / "credentials.json"
LEGACY_TOKEN_FILE = PROJECT_ROOT / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]
ALLOW_TASK_WRITES = os.getenv(
    "OFFICEPILOT_ALLOW_GOOGLE_TASK_WRITES",
    "false",
).strip().lower() in {"1", "true", "yes"}
if ALLOW_TASK_WRITES:
    SCOPES.append("https://www.googleapis.com/auth/tasks")


def token_file_for_user(user_id: str, configured_path: str | None = None) -> Path:
    if not user_id.strip():
        raise ValueError("A Workspace user ID is required.")
    if configured_path:
        token_file = Path(configured_path).expanduser().resolve()
    else:
        safe_user_id = re.sub(r"[^A-Za-z0-9._-]", "_", user_id)
        token_file = (
            Path.home() / ".officepilot" / "tokens" / f"{safe_user_id}.json"
        ).resolve()
    if token_file == LEGACY_TOKEN_FILE.resolve():
        raise ValueError(
            "The shared project token.json cannot be used for user-scoped access."
        )
    return token_file


def get_credentials(token_file: Path) -> Credentials:
    if not CREDENTIALS_FILE.is_file():
        raise FileNotFoundError(
            f"OAuth client file was not found: {CREDENTIALS_FILE}\n"
            "Place your downloaded Desktop app OAuth JSON at the project root "
            "and name it credentials.json."
        )

    creds: Credentials | None = None

    if token_file.is_file():
        try:
            token_info = json.loads(token_file.read_text(encoding="utf-8"))
            previously_granted = set(token_info.get("scopes", []))
            if set(SCOPES).issubset(previously_granted):
                creds = Credentials.from_authorized_user_file(
                    str(token_file), scopes=SCOPES
                )
            else:
                print("Existing user token lacks required scopes; Google authorization will reopen.")
        except (OSError, ValueError, json.JSONDecodeError):
            print("Existing user token could not be read; Google authorization will reopen.")

    if creds and not creds.valid:
        try:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                creds = None
        except RefreshError:
            creds = None

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CREDENTIALS_FILE), SCOPES
        )
        creds = flow.run_local_server(
            port=0,
            access_type="offline",
            prompt="consent",
        )
        token_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        token_file.parent.chmod(0o700)
        token_file.write_text(creds.to_json(), encoding="utf-8")
        try:
            token_file.chmod(0o600)
        except OSError:
            pass
        print("Per-user OAuth authorization saved with private file permissions.")

    return creds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--user-id",
        default=os.getenv("OFFICEPILOT_LOCAL_USER_ID", ""),
        help="OfficePilot authenticated user ID for this Workspace connection.",
    )
    parser.add_argument(
        "--token-file",
        help="Private per-user token path; defaults under ~/.officepilot/tokens/.",
    )
    args = parser.parse_args(argv)

    print("\n=== OfficePilot Google Workspace API smoke test ===")
    print("Requested permissions: Gmail read-only and Calendar read-only")
    if ALLOW_TASK_WRITES:
        print("Google Tasks access included because task writes are enabled.")
    print("Privacy: this script prints counts only, not message/event/task details.\n")

    try:
        token_file = token_file_for_user(args.user_id, args.token_file)
        creds = get_credentials(token_file)

        gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
        calendar = build("calendar", "v3", credentials=creds, cache_discovery=False)
        # A real Gmail API call; do not print message contents or metadata.
        gmail.users().getProfile(userId="me").execute()
        gmail_result = gmail.users().messages().list(
            userId="me", q="in:inbox", maxResults=5
        ).execute()
        gmail_count = len(gmail_result.get("messages", []))
        print("Gmail API: CONNECTED")
        print(f"  Authenticated account: verified (address hidden)")
        print(f"  Message IDs returned by inbox search (up to 5): {gmail_count}")

        # A real Calendar API call for the next 30 days.
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=30)
        events_result = calendar.events().list(
            calendarId="primary",
            timeMin=now.isoformat().replace("+00:00", "Z"),
            timeMax=end.isoformat().replace("+00:00", "Z"),
            maxResults=10,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = events_result.get("items", [])
        print("Calendar API: CONNECTED")
        print(f"  Events returned for the next 30 days (up to 10): {len(events)}")

        if ALLOW_TASK_WRITES:
            tasks = build("tasks", "v1", credentials=creds, cache_discovery=False)
            tasklists_result = tasks.tasklists().list(maxResults=10).execute()
            tasklists = tasklists_result.get("items", [])
            print("Google Tasks API: CONNECTED")
            print(f"  Task lists returned (up to 10): {len(tasklists)}")
        else:
            print("Google Tasks access: NOT REQUESTED (task writes disabled)")
        print("\nRESULT: Read-only Workspace checks succeeded. No task was created.")
        mapping = json.dumps({args.user_id: str(token_file)})
        print(
            "\nConfigure this per-user mapping in the protected OfficePilot "
            "environment, then restart the API:"
        )
        print(f"OFFICEPILOT_WORKSPACE_TOKEN_FILES={mapping}")
        return 0

    except HttpError as exc:
        print("\nGoogle API request failed.")
        print(f"HTTP status: {getattr(exc.resp, 'status', 'unknown')}")
        print("Check that the API is enabled, OAuth scopes are authorized, and the account is a test user if the app is in testing mode.")
        print("Google returned an API error; avoid sharing credentials or token files.")
        return 1
    except Exception as exc:
        print(f"\nSetup/authentication failed: {type(exc).__name__}: {exc}")
        print("Check credentials.json, OAuth consent settings, internet access, and the test-user list.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
