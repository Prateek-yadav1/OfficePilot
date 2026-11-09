"""Simple local benchmark and cost estimate for OfficePilot."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.tools.document_retriever import retrieve_documents
from backend.tools.mock_office import get_calendar, search_emails


def evaluate_officepilot_performance(client: str = "ABC Technologies") -> dict[str, Any]:
    """Execute a representative OfficePilot retrieval flow and estimate cost/runtime."""
    start = time.perf_counter()
    tenant_id = os.getenv("OFFICEPILOT_LOCAL_TENANT_ID", "").strip()
    user_id = os.getenv("OFFICEPILOT_LOCAL_USER_ID", "").strip()
    if not tenant_id or not user_id:
        raise RuntimeError(
            "Set OFFICEPILOT_LOCAL_TENANT_ID and OFFICEPILOT_LOCAL_USER_ID "
            "before running the local benchmark."
        )

    email_result = search_emails(client, tenant_id=tenant_id, user_id=user_id)
    calendar_result = get_calendar(
        client,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    document_result = retrieve_documents(
        query="What did the client ask us to improve?",
        client=client,
        tenant_id=tenant_id,
        limit=3,
    )

    elapsed_seconds = round(time.perf_counter() - start, 3)
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()
    estimated_cost_usd = 0.0 if provider in {"ollama", "local"} else 0.07

    report = {
        "client": client,
        "provider": provider,
        "runtime_seconds": elapsed_seconds,
        "email_records": len(email_result.get("emails", [])),
        "calendar_records": len(calendar_result.get("meetings", [])),
        "document_records": len(document_result),
        "estimated_cost_usd": round(estimated_cost_usd, 4),
        "notes": "This benchmark reflects the local data-access flow; billed cloud models would add API cost.",
    }

    return report


if __name__ == "__main__":
    report = evaluate_officepilot_performance()
    print(json.dumps(report, indent=2))
