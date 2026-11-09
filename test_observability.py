import asyncio
import logging
from types import SimpleNamespace

from backend.agents.observability import (
    OfficePilotLoggingPlugin,
    begin_execution_observation,
    end_execution_observation,
    logger,
)
from main import _metadata_from_state


def _record_tool_result(result: object, caplog) -> str:
    plugin = OfficePilotLoggingPlugin()
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=logger.name)
    try:
        asyncio.run(
            plugin.after_tool_callback(
                tool=SimpleNamespace(name="search_client_documents"),
                tool_args={},
                tool_context=SimpleNamespace(invocation_id="test"),
                result=result,
            )
        )
    finally:
        logger.removeHandler(caplog.handler)
    return caplog.text


def test_list_tool_result_is_logged_as_success(caplog):
    log = _record_tool_result(["private document result"], caplog)

    assert "outcome=success" in log
    assert "private document result" not in log


def test_error_tool_result_is_logged_as_error(caplog):
    log = _record_tool_result({"error": "backend unavailable"}, caplog)

    assert "outcome=error" in log
    assert "backend unavailable" not in log


def test_document_tool_result_is_persisted_before_agent_response():
    plugin = OfficePilotLoggingPlugin()
    events = []
    tokens = begin_execution_observation(
        "document-partial",
        lambda event_type, data: events.append((event_type, data)),
    )
    context = SimpleNamespace(
        invocation_id="document-invocation",
        state={},
    )

    try:
        asyncio.run(
            plugin.after_tool_callback(
                tool=SimpleNamespace(name="search_client_documents"),
                tool_args={},
                tool_context=context,
                result=[
                    {
                        "title": "Warehouse Automation Pilot",
                        "content": "Deployment approval is pending.",
                        "relevance_score": 0.91,
                    }
                ],
            )
        )
    finally:
        end_execution_observation(tokens)

    assert "Deployment approval is pending." in context.state["document_context"]
    partial_event = next(
        data
        for event_type, data in events
        if event_type == "partial_result_updated"
    )
    assert (
        "Deployment approval is pending."
        in partial_event["partial_data"]["document_context"]
    )


def test_model_error_event_keeps_allowlisted_metadata_only():
    class ProviderBadRequest(Exception):
        status_code = 400
        code = "invalid_request_error"
        param = "max_tokens"
        llm_provider = "groq"
        model = "openai/gpt-oss-120b"
        body = {"message": "PRIVATE_REQUEST_AND_WORKSPACE_CONTENT"}

    plugin = OfficePilotLoggingPlugin()
    events = []
    tokens = begin_execution_observation(
        "model-bad-request",
        lambda event_type, data: events.append((event_type, data)),
    )
    callback_context = SimpleNamespace(
        invocation_id="document-invocation",
        agent_name="document_agent",
    )

    async def record_error():
        await plugin.before_model_callback(
            callback_context=callback_context,
            llm_request=SimpleNamespace(),
        )
        await plugin.on_model_error_callback(
            callback_context=callback_context,
            llm_request=SimpleNamespace(),
            error=ProviderBadRequest("PRIVATE_EXCEPTION_MESSAGE"),
        )

    try:
        asyncio.run(record_error())
    finally:
        end_execution_observation(tokens)

    failure = events[-1][1]
    assert failure["error_type"] == "ProviderBadRequest"
    assert failure["http_status"] == 400
    assert failure["provider_error_code"] == "invalid_request_error"
    assert failure["provider_error_param"] == "max_tokens"
    assert failure["provider"] == "groq"
    assert failure["model"] == "openai/gpt-oss-120b"
    assert "PRIVATE" not in str(failure)


def test_tool_exception_group_reports_nested_types_without_messages():
    plugin = OfficePilotLoggingPlugin()
    events = []
    tokens = begin_execution_observation(
        "tool-exception-group",
        lambda event_type, data: events.append((event_type, data)),
    )
    context = SimpleNamespace(
        invocation_id="email-invocation",
        state={},
    )

    try:
        asyncio.run(
            plugin.on_tool_error_callback(
                tool=SimpleNamespace(name="search_emails"),
                tool_args={},
                tool_context=context,
                error=ExceptionGroup(
                    "private group details",
                    [
                        TimeoutError("private timeout details"),
                        ValueError("private validation details"),
                    ],
                ),
            )
        )
    finally:
        end_execution_observation(tokens)

    failure = events[-1][1]
    assert failure["error_type"] == "ExceptionGroup"
    assert failure["nested_error_types"] == [
        "ExceptionGroup",
        "TimeoutError",
        "ValueError",
    ]
    assert "private" not in str(failure).casefold()


def test_quality_checker_model_timeout_is_recorded_without_provider_details():
    plugin = OfficePilotLoggingPlugin()
    events = []
    tokens = begin_execution_observation(
        "quality-timeout",
        lambda event_type, data: events.append((event_type, data)),
    )
    callback_context = SimpleNamespace(
        invocation_id="quality-invocation",
        agent_name="quality_checker",
    )

    async def record_timeout():
        await plugin.before_model_callback(
            callback_context=callback_context,
            llm_request=SimpleNamespace(),
        )
        try:
            raise TimeoutError("private provider details")
        except TimeoutError as cause:
            error = RuntimeError("model invocation failed")
            error.__cause__ = cause
        assert await plugin.on_model_error_callback(
            callback_context=callback_context,
            llm_request=SimpleNamespace(),
            error=error,
        ) is None

    try:
        asyncio.run(record_timeout())
    finally:
        end_execution_observation(tokens)

    assert [event for event, _ in events] == [
        "model_started",
        "model_timed_out",
    ]
    timeout_event = events[-1][1]
    assert timeout_event["agent"] == "quality_checker"
    assert timeout_event["error_type"] == "RuntimeError"
    assert timeout_event["duration_ms"] >= 0
    assert "private provider details" not in str(timeout_event)


def test_integration_metadata_identifies_live_workspace_backend(monkeypatch):
    monkeypatch.setenv("OFFICEPILOT_WORKSPACE_MODE", "google")

    metadata = _metadata_from_state(
        {},
        "test-session",
        {"tools": [], "sources": []},
    )
    backends = {
        integration["name"]: integration["backend"]
        for integration in metadata["integrations"]
    }

    assert backends["Google Calendar"] == "Google Workspace"
    assert backends["Gmail"] == "Google Workspace"
    assert backends["PostgreSQL / pgvector"] == "PostgreSQL / pgvector"
