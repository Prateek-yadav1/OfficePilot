import json

from backend.tools import mock_office
from backend.tools import google_workspace
from backend.tools.client_matching import identify_meeting_client
from backend.tools import mcp_server


def test_workspace_meetings_and_emails_are_filtered_by_tenant(
    monkeypatch,
):
    monkeypatch.setenv(
        "OFFICEPILOT_AUTH_USERS",
        json.dumps(
            {
                "alice": {
                    "password": "alice-test-password",
                    "user_id": "user-alice",
                    "tenant_id": "tenant-a",
                },
                "bob": {
                    "password": "bob-test-password",
                    "user_id": "user-bob",
                    "tenant_id": "tenant-b",
                },
            }
        ),
    )
    fixture_data = {
        "emails.json": [
            {
                "tenant_id": "tenant-a",
                "user_id": "user-alice",
                "client": "Shared Client",
                "subject": "Alice-only email",
            },
            {
                "tenant_id": "tenant-b",
                "user_id": "user-bob",
                "client": "Shared Client",
                "subject": "Bob-only email",
            },
        ],
        "calendar.json": [
            {
                "tenant_id": "tenant-a",
                "user_id": "user-alice",
                "client": "Shared Client",
                "title": "Alice-only meeting",
                "date": "2026-11-02",
                "time": "10:00",
                "participants": [],
            },
            {
                "tenant_id": "tenant-b",
                "user_id": "user-bob",
                "client": "Shared Client",
                "title": "Bob-only meeting",
                "date": "2026-11-03",
                "time": "10:00",
                "participants": [],
            },
        ],
        "documents.json": [
            {"tenant_id": "tenant-a", "client": "Shared Client"},
            {"tenant_id": "tenant-b", "client": "Shared Client"},
        ],
    }
    monkeypatch.setattr(
        mock_office,
        "_load_json",
        lambda filename: fixture_data[filename],
    )

    alice_email = mcp_server.search_emails(
        "Shared Client",
        user_id="user-alice",
        tenant_id="tenant-a",
    )
    alice_meeting = mcp_server.discover_next_meeting(
        user_id="user-alice",
        tenant_id="tenant-a",
    )
    bob_email = mcp_server.search_emails(
        "Shared Client",
        user_id="user-bob",
        tenant_id="tenant-b",
    )
    bob_meeting = mcp_server.discover_next_meeting(
        user_id="user-bob",
        tenant_id="tenant-b",
    )

    assert [item["subject"] for item in alice_email["emails"]] == [
        "Alice-only email"
    ]
    assert alice_meeting["meeting"]["title"] == "Alice-only meeting"
    assert alice_meeting["meeting"]["client"] == "Shared Client"
    assert bob_email["emails"][0]["subject"] == "Bob-only email"
    assert bob_meeting["meeting"]["title"] == "Bob-only meeting"


def test_tenant_without_a_client_index_match_does_not_guess():
    result = identify_meeting_client(
        {
            "title": "Quarterly customer sync",
            "description": "Review roadmap and open topics.",
            "participants": ["person@example.com"],
        },
        ["Shared Client", "Other Organization"],
    )

    assert result == {
        "client": None,
        "confidence": "none",
        "evidence": [],
    }


def test_ambiguous_calendar_name_is_not_resolved_by_guessing():
    result = identify_meeting_client(
        {
            "title": "ACME review",
            "participants": [],
            "description": "",
        },
        ["ACME", "acme"],
    )

    assert result["client"] is None
    assert result["confidence"] == "ambiguous"


def test_workspace_oauth_tokens_cannot_be_shared_between_users(
    monkeypatch,
    tmp_path,
):
    shared = tmp_path / "shared-user-token.json"
    monkeypatch.setenv(
        "OFFICEPILOT_WORKSPACE_TOKEN_FILES",
        json.dumps({"user-alice": str(shared), "user-bob": str(shared)}),
    )

    try:
        google_workspace._user_token_file("user-alice")
    except RuntimeError as exc:
        assert "must not be shared" in str(exc)
    else:
        raise AssertionError("A shared per-user Workspace token was accepted.")


def test_workspace_oauth_tokens_resolve_per_authenticated_user(
    monkeypatch,
    tmp_path,
):
    alice = tmp_path / "alice-token.json"
    bob = tmp_path / "bob-token.json"
    monkeypatch.setenv(
        "OFFICEPILOT_WORKSPACE_TOKEN_FILES",
        json.dumps(
            {
                "user-alice": str(alice),
                "user-bob": str(bob),
            }
        ),
    )

    assert google_workspace._user_token_file("user-alice") == alice
    assert google_workspace._user_token_file("user-bob") == bob
