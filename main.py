import asyncio
import logging
import os
import re
from dataclasses import dataclass
from uuid import uuid4
from typing import Any

from dotenv import load_dotenv
from google.adk.apps import App, ResumabilityConfig
from google.adk.events import Event
from google.adk.runners import InMemoryRunner
from google.genai import types

load_dotenv()

from backend.agents.langfuse_setup import configure_langfuse
from backend.agents.observability import (
    OfficePilotLoggingPlugin,
    validate_user_prompt,
)


@dataclass(frozen=True)
class WorkflowRunResult:
    response: str
    status: str
    session_id: str
    metadata: dict[str, Any]


def _event_text(event: Event) -> str:
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    return "\n".join(
        part.text for part in parts if getattr(part, "text", None)
    )


def _context_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _metadata_from_state(
    state: dict[str, Any],
    session_id: str,
    observations: dict[str, Any],
) -> dict[str, Any]:
    meeting_context = _context_dict(state.get("meeting_context"))
    discovered_meeting = _context_dict(state.get("discovered_meeting"))
    client_match = _context_dict(state.get("client_match"))
    missing_information = meeting_context.get("missing_information", [])
    if not isinstance(missing_information, list):
        missing_information = [str(missing_information)]
    workflow_missing_information = state.get(
        "workflow_missing_information",
        [],
    )
    if isinstance(workflow_missing_information, list):
        missing_information.extend(workflow_missing_information)

    tool_observations = observations.get("tools", [])
    source_references = observations.get("sources", [])
    identified_client = str(
        state.get("client_name")
        or meeting_context.get("client")
        or ""
    ).strip()
    request_text = str(state.get("original_request") or "")
    client_match_evidence = [
        str(item)
        for item in client_match.get("evidence", [])
        if isinstance(item, str)
    ]
    client_match_confidence = str(
        client_match.get("confidence") or "unverified"
    )
    if (
        identified_client
        and re.search(
            rf"(?<!\w){re.escape(identified_client)}(?!\w)",
            request_text,
            flags=re.IGNORECASE,
        )
        and client_match_confidence == "unverified"
    ):
        client_match_confidence = "user_provided"
        client_match_evidence.append("explicit_client_name_in_user_request")
    if client_match_confidence in {"high", "medium"}:
        if any(
            item.get("tool") == "search_emails"
            and (item.get("result_count") or 0) > 0
            for item in tool_observations
        ):
            client_match_evidence.append("tenant_scoped_gmail_results")
        if any(
            item.get("tool") in {"search_client_documents", "retrieve_documents"}
            and (item.get("result_count") or 0) > 0
            for item in tool_observations
        ):
            client_match_evidence.append("tenant_scoped_document_results")
    integration_tools = {
        "Google Calendar": {
            "discover_next_meeting",
            "get_calendar",
        },
        "Gmail": {"search_emails"},
        "PostgreSQL / pgvector": {
            "search_client_documents",
            "retrieve_documents",
        },
    }
    integrations = []
    workspace_mode = os.getenv(
        "OFFICEPILOT_WORKSPACE_MODE",
        "mock",
    ).strip().lower()
    for name, tool_names in integration_tools.items():
        calls = [
            item
            for item in tool_observations
            if item.get("tool") in tool_names
        ]
        executed_calls = [
            item for item in calls if item.get("outcome") != "skipped"
        ]
        result_count = sum(
            max(0, int(item.get("result_count") or 0))
            for item in executed_calls
            if item.get("outcome") == "success"
        )
        if not executed_calls:
            status = "not run"
        elif any(item.get("outcome") == "timed_out" for item in executed_calls):
            status = "timed out"
        elif any(item.get("outcome") == "error" for item in executed_calls):
            status = "failed"
        else:
            status = (
                f"completed with {result_count} "
                f"result{'s' if result_count != 1 else ''}"
                if result_count
                else "completed with zero results"
            )
        backend = (
            "PostgreSQL / pgvector"
            if name == "PostgreSQL / pgvector"
            else (
                "Google Workspace"
                if workspace_mode == "google"
                else "mock fixtures"
            )
        )
        integrations.append(
            {
                "name": name,
                "backend": backend,
                "status": status,
                "calls": len(executed_calls),
                "results": result_count,
            }
        )

    for integration in integrations:
        if integration["status"] == "not run":
            missing_information.append(
                f"{integration['name']} retrieval was not run; its evidence is unavailable."
            )
        elif integration["status"] == "failed":
            missing_information.append(
                f"{integration['name']} retrieval failed; its evidence could not be verified."
            )
        elif integration["status"] == "timed out":
            missing_information.append(
                f"{integration['name']} retrieval timed out; results may be incomplete."
            )
        elif integration["status"] == "completed with zero results":
            missing_information.append(
                f"{integration['name']} completed but returned no matching evidence."
            )

    warnings = state.get("execution_warnings", [])
    if not isinstance(warnings, list):
        warnings = [str(warnings)]

    return {
        "session_id": session_id,
        "client": str(
            state.get("client_name")
            or meeting_context.get("client")
            or ""
        ),
        "meeting": {
            "title": (
                meeting_context.get("meeting_title")
                or discovered_meeting.get("title")
            ),
            "date": (
                meeting_context.get("meeting_date")
                or discovered_meeting.get("start")
                or discovered_meeting.get("date")
            ),
            "time": meeting_context.get("meeting_time"),
            "participants": (
                meeting_context.get("participants")
                or discovered_meeting.get("participants", [])
            ),
        },
        "client_match": {
            "confidence": client_match_confidence,
            "evidence": list(dict.fromkeys(client_match_evidence)),
        },
        "missing_information": list(
            dict.fromkeys(str(item) for item in missing_information if item)
        ),
        "integrations": integrations,
        "sources": source_references,
        "partial_results": {
            "Gmail": str(state.get("email_context") or ""),
            "PostgreSQL / pgvector": str(
                state.get("document_context") or ""
            ),
            "Google Calendar": str(state.get("calendar_context") or ""),
        },
        "warnings": [
            str(item)
            for item in warnings
            if isinstance(item, str)
        ],
        "quality": {
            "status": str(state.get("quality_status", "")),
            "deterministic_errors": state.get(
                "deterministic_quality_errors",
                [],
            ),
            "review_cycles": int(
                state.get("quality_review_cycles", 0) or 0
            ),
        },
    }


async def run_officepilot(
    request: str,
    user_id: str,
    tenant_id: str,
    execution_id: str | None = None,
) -> WorkflowRunResult:
    """Run the OfficePilot workflow for a caller-provided user request."""
    if not user_id.strip() or not tenant_id.strip():
        raise ValueError("A trusted user and tenant identity are required.")
    is_safe, safety_reason = validate_user_prompt(request)
    if not is_safe:
        raise ValueError(f"Request rejected by safety guardrail: {safety_reason}")

    # Import after optional instrumentation setup.
    from backend.agents.workflow import root_agent

    logging_plugin = OfficePilotLoggingPlugin()
    app = App(
        name="officepilot",
        root_agent=root_agent,
        plugins=[logging_plugin],
        resumability_config=ResumabilityConfig(
            is_resumable=True
        ),
    )

    runner = InMemoryRunner(app=app)
    session_id = str(uuid4())
    correlation_id = execution_id or str(uuid4())
    await runner.session_service.create_session(
        app_name=app.name,
        user_id=user_id,
        session_id=session_id,
        state={
            "allow_action_proposal": False,
            "execution_id": correlation_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "original_request": request,
            "session_id": session_id,
        },
    )

    events: list[Event] = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=types.Content(
            role="user",
            parts=[types.Part.from_text(text=request)],
        ),
    ):
        if getattr(event, "error_code", None):
            raise RuntimeError(
                "ADK workflow failed with event "
                f"{event.error_code} ({event.error_message})."
            )
        events.append(event)

    session = await runner.session_service.get_session(
        app_name=app.name,
        user_id=user_id,
        session_id=session_id,
    )
    if session is None:
        raise RuntimeError("The workflow session could not be retrieved.")

    terminal_events = [
        event
        for event in events
        if getattr(event, "author", None)
        in {"final_response_agent", "quality_blocked_agent"}
    ]
    if not terminal_events:
        raise RuntimeError(
            "The workflow ended without a final response or quality-blocked result."
        )

    terminal_event = terminal_events[-1]
    response = _event_text(terminal_event)
    if not response.strip():
        raise RuntimeError("The workflow final response was empty.")

    state = session.state
    execution_status = str(
        state.get("execution_status", "")
    ).strip()
    if terminal_event.author == "quality_blocked_agent":
        execution_status = "failed"
    if execution_status not in {
        "completed",
        "completed_with_warnings",
        "failed",
    }:
        raise RuntimeError(
            "The workflow did not record an approved terminal status."
        )

    metadata = _metadata_from_state(
        state,
        session_id,
        logging_plugin.snapshot(),
    )
    if metadata["missing_information"]:
        metadata["warnings"].append(
            "The briefing includes information that was not available from its sources."
        )
    if any(
        integration["status"] == "no_matches"
        for integration in metadata["integrations"]
    ):
        metadata["warnings"].append(
            "At least one connected source returned no client-matching records."
        )
    if (
        execution_status == "completed"
        and metadata["warnings"]
    ):
        execution_status = "completed_with_warnings"

    return WorkflowRunResult(
        response=response,
        status=execution_status,
        session_id=session_id,
        metadata=metadata,
    )


async def main() -> None:
    langfuse_client = configure_langfuse()

    try:
        request = (
            "Prepare me for tomorrow's meeting with ABC Technologies. "
            "Find the important email context, relevant documents, "
            "and calendar information."
        )

        print("\n" + "=" * 80)
        print("OFFICEPILOT")
        print("=" * 80)
        print("\nUSER REQUEST:")
        print(request)
        print("\nEXECUTING MULTI-AGENT WORKFLOW...")

        tenant_id = os.getenv("OFFICEPILOT_LOCAL_TENANT_ID", "").strip()
        user_id = os.getenv("OFFICEPILOT_LOCAL_USER_ID", "").strip()
        if not tenant_id or not user_id:
            raise RuntimeError(
                "Set OFFICEPILOT_LOCAL_TENANT_ID and OFFICEPILOT_LOCAL_USER_ID "
                "to run the local demo."
            )
        response = await run_officepilot(
            request,
            user_id=user_id,
            tenant_id=tenant_id,
        )

        print("\n" + "=" * 80)
        print("FINAL RESPONSE")
        print("=" * 80)
        print(response.response)

    finally:
        if langfuse_client is not None:
            try:
                langfuse_client.flush()
                print("Langfuse traces flushed.")
            except Exception:
                logging.exception("Failed to flush Langfuse traces.")


if __name__ == "__main__":
    asyncio.run(main())
