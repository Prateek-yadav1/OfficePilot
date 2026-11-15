import asyncio
import json

import pytest

from backend.tools.mcp_client import (
    WorkspaceConfigurationError,
    call_mcp_tool,
    validate_mcp_tool_response,
)


def test_mcp_email_response_is_validated_and_extension_fields_are_preserved():
    response = validate_mcp_tool_response(
        "search_emails",
        {
            "source": "mock_email_system",
            "client": "ABC Technologies",
            "count": 1,
            "emails": [
                {
                    "subject": "Deployment delay",
                    "date": "2026-09-02",
                    "content": "The client raised a concern.",
                }
            ],
            "tenant_marker": "test",
        },
    )

    assert response["emails"][0]["subject"] == "Deployment delay"
    assert response["tenant_marker"] == "test"


@pytest.mark.parametrize(
    "response",
    [
        {
            "source": "google_gmail",
            "client": "ABC Technologies",
            "count": 1,
            "emails": [],
        },
        {
            "source": "google_gmail",
            "client": "ABC Technologies",
            "count": 0,
            "emails": ["not an email object"],
        },
    ],
)
def test_malformed_mcp_email_response_fails_explicitly(response):
    with pytest.raises(RuntimeError, match="returned a malformed response"):
        validate_mcp_tool_response("search_emails", response)


def test_mcp_calendar_discovery_rejects_inconsistent_status():
    with pytest.raises(RuntimeError, match="returned a malformed response"):
        validate_mcp_tool_response(
            "discover_next_meeting",
            {
                "source": "google_calendar",
                "status": "found",
                "meeting": None,
            },
        )


def test_google_workspace_missing_user_token_returns_actionable_error(
    monkeypatch,
):
    monkeypatch.setenv("OFFICEPILOT_WORKSPACE_MODE", "google")
    monkeypatch.delenv("OFFICEPILOT_WORKSPACE_TOKEN_FILES", raising=False)
    monkeypatch.setenv(
        "OFFICEPILOT_AUTH_USERS",
        json.dumps(
            {
                "demo": {
                    "password": "local-validation-password",
                    "user_id": "officepilot-local-demo",
                    "tenant_id": "local-demo",
                }
            }
        ),
    )

    with pytest.raises(
        WorkspaceConfigurationError,
        match="OFFICEPILOT_WORKSPACE_TOKEN_FILES",
    ):
        asyncio.run(
            call_mcp_tool(
                "discover_next_meeting",
                {
                    "user_id": "officepilot-local-demo",
                    "tenant_id": "local-demo",
                },
            )
        )
