import asyncio
import json

import pytest

from backend.tools.mcp_client import (
    WorkspaceConfigurationError,
    call_mcp_tool,
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
