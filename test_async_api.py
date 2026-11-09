import asyncio
import base64
import json
import stat
import threading
import time

from fastapi.testclient import TestClient

from backend.agents.observability import emit_execution_event
from backend.execution_store import ExecutionStore
from backend import server
from main import WorkflowRunResult


def _result(status: str = "completed") -> WorkflowRunResult:
    return WorkflowRunResult(
        response="# Meeting Briefing\n\n## Executive Summary\nReady.",
        status=status,
        session_id="session-test",
        metadata={
            "session_id": "session-test",
            "client": "Test Client",
            "meeting": {},
            "missing_information": [],
            "integrations": [],
            "sources": [],
            "warnings": [],
            "quality": {
                "status": "FAIL" if status == "failed" else "PASS",
                "deterministic_errors": (
                    ["The briefing did not pass deterministic validation."]
                    if status == "failed"
                    else []
                ),
                "review_cycles": 1,
            },
        },
    )


def _auth_headers(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(
        f"{username}:{password}".encode("utf-8")
    ).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "OFFICEPILOT_AUTH_USERS",
        json.dumps(
            {
                "alice": {
                    "password": "alice-test-password",
                    "user_id": "user-alice",
                    "tenant_id": "tenant-alice",
                },
                "bob": {
                    "password": "bob-test-password",
                    "user_id": "user-bob",
                    "tenant_id": "tenant-bob",
                },
            }
        ),
    )
    monkeypatch.setenv(
        "OFFICEPILOT_A2A_SHARED_SECRET",
        "test-a2a-secret-32-characters-long",
    )
    store = ExecutionStore(tmp_path / "executions.sqlite3")
    monkeypatch.setattr(server, "execution_store", store)
    monkeypatch.setattr(server, "_active_executions", {})
    monkeypatch.setattr(server, "_execution_semaphore", None)
    monkeypatch.setattr(
        server,
        "configure_langfuse",
        lambda: None,
    )
    return TestClient(
        server.app,
        headers=_auth_headers("alice", "alice-test-password"),
    ), store


def _wait_for_terminal(
    client: TestClient,
    status_url: str,
    headers: dict[str, str] | None = None,
):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        response = client.get(status_url, headers=headers)
        assert response.status_code == 200
        execution = response.json()
        if execution["status"] in {
            "completed",
            "completed_with_warnings",
            "failed",
        }:
            return execution
        time.sleep(0.01)
    raise AssertionError("Execution did not reach a terminal state in time.")


def test_execution_persists_progress_and_final_brief(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    calls = []

    async def workflow(
        user_request: str,
        execution_id: str,
        user_id: str,
        tenant_id: str,
    ):
        calls.append((user_request, execution_id))
        emit_execution_event(
            "agent_started",
            {"agent": "planner_agent"},
        )
        await asyncio.sleep(0.01)
        emit_execution_event(
            "agent_completed",
            {"agent": "final_response_agent", "duration_ms": 3},
        )
        return _result()

    monkeypatch.setattr(server, "run_officepilot", workflow)
    with client:
        accepted = client.post(
            "/executions",
            json={"user_request": "Prepare my next meeting."},
            headers={"Idempotency-Key": "request-1"},
        )
        assert accepted.status_code == 202
        accepted_data = accepted.json()

        execution = _wait_for_terminal(client, accepted_data["status_url"])
        assert execution["status"] == "completed"
        assert execution["result"]["response"].startswith("# Meeting Briefing")
        assert execution["result"]["session_id"] == "session-test"
        assert execution["result"]["metrics"]["end_to_end_latency_ms"] is not None

        events = client.get(accepted_data["events_url"]).json()["events"]
        event_types = [event["type"] for event in events]
        assert "agent_started" in event_types
        assert "agent_completed" in event_types

    reopened = ExecutionStore(tmp_path / "executions.sqlite3")
    assert reopened.get(accepted_data["execution_id"])["status"] == "completed"
    assert len(calls) == 1


def test_idempotency_prevents_duplicate_execution(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    calls = []

    async def workflow(
        user_request: str,
        execution_id: str,
        user_id: str,
        tenant_id: str,
    ):
        calls.append(execution_id)
        await asyncio.sleep(0.02)
        return _result()

    monkeypatch.setattr(server, "run_officepilot", workflow)
    with client:
        first = client.post(
            "/executions",
            json={"user_request": "Prepare my next meeting."},
            headers={"Idempotency-Key": "same-request"},
        )
        second = client.post(
            "/executions",
            json={"user_request": "Prepare my next meeting."},
            headers={"Idempotency-Key": "same-request"},
        )
        assert first.status_code == second.status_code == 202
        assert first.json()["execution_id"] == second.json()["execution_id"]
        assert second.json()["duplicate"] is True
        _wait_for_terminal(client, first.json()["status_url"])

    assert len(calls) == 1


def test_workflow_concurrency_limit_keeps_waiting_jobs_queued(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("OFFICEPILOT_MAX_CONCURRENT_WORKFLOWS", "1")
    client, _ = _client(monkeypatch, tmp_path)
    first_started = threading.Event()
    release_first = threading.Event()

    async def workflow(
        user_request: str,
        execution_id: str,
        user_id: str,
        tenant_id: str,
    ):
        first_started.set()
        await asyncio.to_thread(release_first.wait, 15)
        return _result()

    monkeypatch.setattr(server, "run_officepilot", workflow)
    with client:
        first = client.post(
            "/executions",
            json={"user_request": "Prepare the first meeting."},
        ).json()
        assert first_started.wait(1)
        assert client.get(first["status_url"]).json()["status"] == "running"

        try:
            second = client.post(
                "/executions",
                json={"user_request": "Prepare the second meeting."},
            ).json()
            queued = client.get(second["status_url"]).json()
            assert queued["status"] == "queued"
        finally:
            release_first.set()

        assert (
            _wait_for_terminal(client, first["status_url"])["status"]
            == "completed"
        )
        assert (
            _wait_for_terminal(client, second["status_url"])["status"]
            == "completed"
        )


def test_reused_idempotency_key_with_different_request_is_conflict(
    monkeypatch,
    tmp_path,
):
    client, _ = _client(monkeypatch, tmp_path)

    async def workflow(
        user_request: str,
        execution_id: str,
        user_id: str,
        tenant_id: str,
    ):
        return _result()

    monkeypatch.setattr(server, "run_officepilot", workflow)
    with client:
        first = client.post(
            "/executions",
            json={"user_request": "Prepare my next meeting."},
            headers={"Idempotency-Key": "collision"},
        )
        conflict = client.post(
            "/executions",
            json={"user_request": "Prepare an unrelated report."},
            headers={"Idempotency-Key": "collision"},
        )
        assert first.status_code == 202
        assert conflict.status_code == 409


def test_workflow_timeout_is_reported_as_failed(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    monkeypatch.setenv("OFFICEPILOT_WORKFLOW_TIMEOUT_SECONDS", "0.01")

    async def slow_workflow(
        user_request: str,
        execution_id: str,
        user_id: str,
        tenant_id: str,
    ):
        await asyncio.sleep(1)
        return _result()

    monkeypatch.setattr(server, "run_officepilot", slow_workflow)
    with client:
        accepted = client.post(
            "/executions",
            json={"user_request": "Prepare my next meeting."},
        )
        execution = _wait_for_terminal(client, accepted.json()["status_url"])
        assert execution["status"] == "failed"
        assert "0.01 seconds" in execution["error"]


def test_workflow_timeout_preserves_completed_source_findings(
    monkeypatch,
    tmp_path,
):
    client, _ = _client(monkeypatch, tmp_path)
    monkeypatch.setenv("OFFICEPILOT_WORKFLOW_TIMEOUT_SECONDS", "0.02")

    async def stalled_quality_check(
        user_request: str,
        execution_id: str,
        user_id: str,
        tenant_id: str,
    ):
        emit_execution_event(
            "partial_result_updated",
            {
                "session_id": "session-partial",
                "partial_data": {
                    "client_name": "Acme Robotics",
                    "client_match": {
                        "confidence": "user_provided",
                        "evidence": ["explicit_client_name_in_user_request"],
                    },
                    "discovered_meeting": {
                        "id": "meeting-1",
                        "title": "Acme Robotics pilot review",
                        "date": "2026-11-05",
                    },
                    "email_context": "Gmail summary: confirm barcode test results.",
                    "document_context": (
                        "Document finding: deployment approval is pending."
                    ),
                    "calendar_context": "Calendar summary: pilot review.",
                },
            },
        )
        emit_execution_event(
            "tool_completed",
            {
                "tool": "discover_next_meeting",
                "outcome": "success",
                "result_count": 1,
                "source_references": [
                    {
                        "source": "Google Calendar",
                        "id": "meeting-1",
                        "label": "Acme Robotics pilot review",
                    }
                ],
            },
        )
        emit_execution_event(
            "tool_completed",
            {
                "tool": "search_emails",
                "outcome": "success",
                "result_count": 2,
                "source_references": [
                    {
                        "source": "Gmail",
                        "id": "email-1",
                        "label": "Barcode testing",
                    }
                ],
            },
        )
        emit_execution_event(
            "tool_completed",
            {
                "tool": "search_client_documents",
                "outcome": "success",
                "result_count": 1,
                "source_references": [
                    {
                        "source": "PostgreSQL / pgvector",
                        "id": "doc-1",
                        "label": "Acme project brief",
                    }
                ],
            },
        )
        emit_execution_event(
            "agent_started",
            {"agent": "quality_checker", "invocation_id": "inv-1"},
        )
        emit_execution_event(
            "model_started",
            {"agent": "quality_checker", "invocation_id": "inv-1"},
        )
        await asyncio.sleep(1)
        return _result()

    monkeypatch.setattr(server, "run_officepilot", stalled_quality_check)
    with client:
        accepted = client.post(
            "/executions",
            json={"user_request": "Prepare me for Acme Robotics."},
        ).json()
        execution = _wait_for_terminal(client, accepted["status_url"])

    result = execution["result"]
    metadata = result["metadata"]
    assert execution["status"] == "failed"
    assert result["incomplete"] is True
    assert result["response"] == ""
    assert metadata["client"] == "Acme Robotics"
    assert metadata["meeting"]["title"] == "Acme Robotics pilot review"
    assert metadata["failure"]["agent"] == "quality_checker"
    assert metadata["failure"]["operation"] == "model"
    assert metadata["partial_results"]["Gmail"].startswith("Gmail summary")
    assert "deployment approval is pending" in metadata["partial_results"][
        "PostgreSQL / pgvector"
    ]
    integrations = {item["name"]: item for item in metadata["integrations"]}
    assert integrations["Google Calendar"]["status"] == "completed with 1 result"
    assert integrations["Gmail"]["status"] == "completed with 2 results"
    assert (
        integrations["PostgreSQL / pgvector"]["status"]
        == "completed with 1 result"
    )
    assert {source["source"] for source in metadata["sources"]} == {
        "Google Calendar",
        "Gmail",
        "PostgreSQL / pgvector",
    }


def test_quality_checker_timeout_fails_with_saved_source_evidence(
    monkeypatch,
    tmp_path,
):
    client, store = _client(monkeypatch, tmp_path)

    async def timed_out_quality_check(
        user_request: str,
        execution_id: str,
        user_id: str,
        tenant_id: str,
    ):
        emit_execution_event(
            "partial_result_updated",
            {
                "partial_data": {
                    "session_id": "session-quality-timeout",
                    "client_name": "Acme Robotics",
                    "discovered_meeting": {
                        "id": "meeting-2",
                        "title": "Warehouse automation review",
                        "date": "2026-11-05",
                    },
                    "calendar_context": "Calendar: Warehouse automation review.",
                    "email_context": "Gmail: barcode testing remains open.",
                    "document_context": (
                        "PostgreSQL: deployment approval remains pending."
                    ),
                }
            },
        )
        for tool, source, source_id in (
            ("discover_next_meeting", "Google Calendar", "meeting-2"),
            ("search_emails", "Gmail", "email-2"),
            ("search_client_documents", "PostgreSQL / pgvector", "doc-2"),
        ):
            emit_execution_event(
                "tool_completed",
                {
                    "tool": tool,
                    "outcome": "success",
                    "result_count": 1,
                    "source_references": [
                        {
                            "source": source,
                            "id": source_id,
                            "label": source_id,
                        }
                    ],
                },
            )
        emit_execution_event(
            "agent_started",
            {
                "agent": "quality_checker",
                "invocation_id": "quality-check-1",
            },
        )
        emit_execution_event(
            "model_started",
            {
                "agent": "quality_checker",
                "invocation_id": "quality-check-1",
            },
        )
        emit_execution_event(
            "model_timed_out",
            {
                "agent": "quality_checker",
                "invocation_id": "quality-check-1",
                "error_type": "TimeoutError",
                "duration_ms": 180000,
            },
        )
        raise asyncio.TimeoutError("private provider details")

    monkeypatch.setattr(server, "run_officepilot", timed_out_quality_check)
    with client:
        accepted = client.post(
            "/executions",
            json={"user_request": "Prepare me for Acme Robotics."},
        ).json()
        execution = _wait_for_terminal(client, accepted["status_url"])

    result = execution["result"]
    metadata = result["metadata"]
    assert execution["status"] == "failed"
    assert result["status"] == "failed"
    assert result["incomplete"] is True
    assert result["response"] == ""
    assert "quality_checker timed out" in execution["error"]
    assert "1800 seconds" not in execution["error"]
    assert "private provider details" not in execution["error"]
    assert metadata["failure"]["operation"] == "model"
    assert metadata["failure"]["agent"] == "quality_checker"
    assert metadata["client"] == "Acme Robotics"
    assert metadata["partial_results"] == {
        "Gmail": "Gmail: barcode testing remains open.",
        "PostgreSQL / pgvector": (
            "PostgreSQL: deployment approval remains pending."
        ),
        "Google Calendar": "Calendar: Warehouse automation review.",
    }
    assert {source["source"] for source in metadata["sources"]} == {
        "Google Calendar",
        "Gmail",
        "PostgreSQL / pgvector",
    }
    assert {
        item["name"]: item["status"]
        for item in metadata["integrations"]
    } == {
        "Google Calendar": "completed with 1 result",
        "Gmail": "completed with 1 result",
        "PostgreSQL / pgvector": "completed with 1 result",
    }

    persisted = store.get(accepted["execution_id"])
    assert persisted["status"] == "failed"
    assert persisted["result"]["metadata"]["partial_results"] == (
        metadata["partial_results"]
    )
    event_types = [
        item["type"]
        for item in store.events(accepted["execution_id"], limit=100)
    ]
    assert "workflow_failed" in event_types
    assert "workflow_timed_out" not in event_types


def test_research_agent_failure_keeps_successful_gmail_and_document_results(
    monkeypatch,
    tmp_path,
):
    client, _ = _client(monkeypatch, tmp_path)

    async def failed_research(
        user_request: str,
        execution_id: str,
        user_id: str,
        tenant_id: str,
    ):
        emit_execution_event(
            "partial_result_updated",
            {
                "session_id": "session-research-failure",
                "partial_data": {
                    "client_name": "Acme Robotics",
                    "email_context": "Gmail summary: open barcode issue.",
                    "document_context": "Document summary: approval pending.",
                },
            },
        )
        for tool, source, source_id in (
            ("search_emails", "Gmail", "email-2"),
            ("search_client_documents", "PostgreSQL / pgvector", "doc-2"),
        ):
            emit_execution_event(
                "tool_completed",
                {
                    "tool": tool,
                    "outcome": "success",
                    "result_count": 1,
                    "source_references": [
                        {
                            "source": source,
                            "id": source_id,
                            "label": source_id,
                        }
                    ],
                },
            )
        emit_execution_event(
            "agent_started",
            {"agent": "research_agent", "invocation_id": "research-inv"},
        )
        emit_execution_event(
            "tool_failed",
            {
                "tool": "run_crewai_research",
                "invocation_id": "research-inv",
                "error_type": "TimeoutError",
            },
        )
        raise RuntimeError("Private provider exception text.")

    monkeypatch.setattr(server, "run_officepilot", failed_research)
    with client:
        accepted = client.post(
            "/executions",
            json={"user_request": "Prepare me for Acme Robotics."},
        ).json()
        execution = _wait_for_terminal(client, accepted["status_url"])

    result = execution["result"]
    metadata = result["metadata"]
    assert execution["status"] == "failed"
    assert metadata["client"] == "Acme Robotics"
    assert metadata["partial_results"]["Gmail"].startswith("Gmail summary")
    assert "approval pending" in metadata["partial_results"][
        "PostgreSQL / pgvector"
    ]
    assert {
        item["name"]: item["status"]
        for item in metadata["integrations"]
    }["Gmail"] == "completed with 1 result"
    assert {
        item["name"]: item["status"]
        for item in metadata["integrations"]
    }["PostgreSQL / pgvector"] == "completed with 1 result"
    assert {source["source"] for source in metadata["sources"]} == {
        "Gmail",
        "PostgreSQL / pgvector",
    }
    assert "Private provider exception text" not in execution["error"]


def test_model_connection_failure_reports_actionable_ollama_error(
    monkeypatch,
    tmp_path,
):
    client, _ = _client(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")
    monkeypatch.setenv("OLLAMA_API_BASE", "http://127.0.0.1:11434")

    async def unavailable_model(
        user_request: str,
        execution_id: str,
        user_id: str,
        tenant_id: str,
    ):
        emit_execution_event(
            "model_failed",
            {"agent": "planner_agent", "error_type": "APIConnectionError"},
        )
        raise RuntimeError("Internal provider exception details are private.")

    monkeypatch.setattr(server, "run_officepilot", unavailable_model)
    with client:
        accepted = client.post(
            "/executions",
            json={"user_request": "Prepare my next meeting."},
        ).json()
        execution = _wait_for_terminal(client, accepted["status_url"])

    assert execution["status"] == "failed"
    assert "local Ollama model provider could not be reached" in execution["error"]
    assert "llama3.1" in execution["error"]
    assert "Internal provider exception details are private" not in execution["error"]


def test_groq_rate_limit_is_reported_without_provider_fallback(
    monkeypatch,
    tmp_path,
):
    client, _ = _client(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "groq")

    async def rate_limited_model(
        user_request: str,
        execution_id: str,
        user_id: str,
        tenant_id: str,
    ):
        emit_execution_event(
            "model_failed",
            {"agent": "planner_agent", "error_type": "RateLimitError"},
        )
        raise RuntimeError("Private quota response.")

    monkeypatch.setattr(server, "run_officepilot", rate_limited_model)
    with client:
        accepted = client.post(
            "/executions",
            json={"user_request": "Prepare my next meeting."},
        ).json()
        execution = _wait_for_terminal(client, accepted["status_url"])

    assert execution["status"] == "failed"
    assert "Groq reported a rate limit or exhausted quota" in execution["error"]
    assert "No provider fallback was used." in execution["error"]
    assert "Private quota response" not in execution["error"]


def test_bad_request_failure_explains_safe_metadata_and_keeps_partial_data(
    monkeypatch,
    tmp_path,
):
    client, _ = _client(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "groq")

    async def rejected_model_request(
        user_request: str,
        execution_id: str,
        user_id: str,
        tenant_id: str,
    ):
        emit_execution_event(
            "partial_result_updated",
            {
                "partial_data": {
                    "client_name": "Acme Robotics",
                    "document_context": (
                        "Retrieved source: deployment approval is pending."
                    ),
                }
            },
        )
        emit_execution_event(
            "tool_completed",
            {
                "tool": "search_client_documents",
                "outcome": "success",
                "result_count": 1,
                "source_references": [
                    {
                        "source": "PostgreSQL / pgvector",
                        "id": "doc-1",
                        "label": "Warehouse Automation Pilot",
                    }
                ],
            },
        )
        emit_execution_event(
            "model_failed",
            {
                "agent": "document_agent",
                "error_type": "BadRequestError",
                "provider": "groq",
                "http_status": 400,
                "provider_error_code": "invalid_request_error",
                "provider_error_param": "max_tokens",
            },
        )
        raise RuntimeError("PRIVATE_PROVIDER_RESPONSE")

    monkeypatch.setattr(server, "run_officepilot", rejected_model_request)
    with client:
        accepted = client.post(
            "/executions",
            json={"user_request": "Prepare me for Acme Robotics."},
        ).json()
        execution = _wait_for_terminal(client, accepted["status_url"])

    assert execution["status"] == "failed"
    assert "document_agent" in execution["error"]
    assert "groq" in execution["error"]
    assert "HTTP 400" in execution["error"]
    assert "code invalid_request_error" in execution["error"]
    assert "parameter max_tokens" in execution["error"]
    assert "PRIVATE_PROVIDER_RESPONSE" not in execution["error"]
    assert (
        "deployment approval is pending"
        in execution["result"]["metadata"]["partial_results"][
            "PostgreSQL / pgvector"
        ]
    )


def test_workspace_configuration_failure_reports_per_user_oauth_setup(
    monkeypatch,
    tmp_path,
):
    client, _ = _client(monkeypatch, tmp_path)

    async def unavailable_workspace(
        user_request: str,
        execution_id: str,
        user_id: str,
        tenant_id: str,
    ):
        emit_execution_event(
            "tool_failed",
            {
                "tool": "discover_next_meeting",
                "error_type": "WorkspaceConfigurationError",
            },
        )
        raise RuntimeError("Internal Workspace details are private.")

    monkeypatch.setattr(server, "run_officepilot", unavailable_workspace)
    with client:
        accepted = client.post(
            "/executions",
            json={"user_request": "Prepare my next meeting."},
        ).json()
        execution = _wait_for_terminal(client, accepted["status_url"])

    assert execution["status"] == "failed"
    assert "no usable user-specific OAuth connection" in execution["error"]
    assert "OFFICEPILOT_WORKSPACE_TOKEN_FILES" in execution["error"]
    assert "Internal Workspace details are private" not in execution["error"]


def test_completed_with_warnings_status_is_preserved(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)

    async def workflow(
        user_request: str,
        execution_id: str,
        user_id: str,
        tenant_id: str,
    ):
        return _result(status="completed_with_warnings")

    monkeypatch.setattr(server, "run_officepilot", workflow)
    with client:
        accepted = client.post(
            "/executions",
            json={"user_request": "Prepare my next meeting."},
        ).json()
        execution = _wait_for_terminal(client, accepted["status_url"])

    assert execution["status"] == "completed_with_warnings"
    assert execution["result"]["status"] == "completed_with_warnings"


def test_quality_blocked_result_is_not_reported_as_success(
    monkeypatch,
    tmp_path,
):
    client, _ = _client(monkeypatch, tmp_path)

    async def workflow(
        user_request: str,
        execution_id: str,
        user_id: str,
        tenant_id: str,
    ):
        return _result(status="failed")

    monkeypatch.setattr(server, "run_officepilot", workflow)
    with client:
        accepted = client.post(
            "/executions",
            json={"user_request": "Prepare my next meeting."},
        ).json()
        execution = _wait_for_terminal(client, accepted["status_url"])

    assert execution["status"] == "failed"
    assert execution["result"]["status"] == "failed"
    assert "Briefing withheld by the quality gate" in execution["error"]


def test_interrupted_execution_is_not_reported_as_running(tmp_path):
    path = tmp_path / "executions.sqlite3"
    first_store = ExecutionStore(path)
    running, _ = first_store.create(
        "Prepare a running meeting.",
        "user-alice",
        "tenant-alice",
    )
    queued, _ = first_store.create(
        "Prepare a queued meeting.",
        "user-alice",
        "tenant-alice",
    )
    first_store.mark_running(running["execution_id"])

    restarted_store = ExecutionStore(path)
    assert restarted_store.recover_orphaned() == 2
    assert restarted_store.get(running["execution_id"])["status"] == "failed"
    assert restarted_store.get(queued["execution_id"])["status"] == "failed"


def test_execution_database_has_private_file_permissions(tmp_path):
    store = ExecutionStore(tmp_path / "executions.sqlite3")

    permissions = stat.S_IMODE(store.path.stat().st_mode)

    assert permissions & 0o077 == 0


def test_unauthenticated_application_and_api_requests_are_rejected(
    monkeypatch,
    tmp_path,
):
    client, _ = _client(monkeypatch, tmp_path)
    async def workflow(user_request: str, execution_id: str, user_id: str, tenant_id: str):
        return _result()

    monkeypatch.setattr(server, "run_officepilot", workflow)
    with client:
        with TestClient(server.app) as unauthenticated:
            assert unauthenticated.get("/").status_code == 401
        assert unauthenticated.get("/assets/app.js").status_code == 401
        assert unauthenticated.post(
            "/executions",
            json={"user_request": "Prepare my next meeting."},
        ).status_code == 401
        assert unauthenticated.get("/a2a").status_code == 401
        assert unauthenticated.get("/health").status_code == 200


def test_execution_owner_controls_status_events_and_result_access(
    monkeypatch,
    tmp_path,
):
    client, _ = _client(monkeypatch, tmp_path)

    async def workflow(
        user_request: str,
        execution_id: str,
        user_id: str,
        tenant_id: str,
    ):
        return _result()

    monkeypatch.setattr(server, "run_officepilot", workflow)
    with client:
        accepted = client.post(
            "/executions",
            json={"user_request": "Prepare the confidential meeting."},
        ).json()
        _wait_for_terminal(client, accepted["status_url"])

        assert client.get(accepted["status_url"]).status_code == 200
        assert client.get(accepted["events_url"]).status_code == 200
        assert client.get(
            accepted["status_url"],
            headers=_auth_headers("bob", "bob-test-password"),
        ).status_code == 404
        assert client.get(
            accepted["events_url"],
            headers=_auth_headers("bob", "bob-test-password"),
        ).status_code == 404


def test_session_id_is_not_an_authentication_credential(
    monkeypatch,
    tmp_path,
):
    client, _ = _client(monkeypatch, tmp_path)
    with client:
        with TestClient(server.app) as unauthenticated:
            assert unauthenticated.get(
                "/executions/session-test",
                params={"session_id": "session-test"},
            ).status_code == 401
        assert client.get("/executions/session-test").status_code == 404


def test_idempotency_keys_are_scoped_to_user_and_tenant(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    calls = []

    async def workflow(
        user_request: str,
        execution_id: str,
        user_id: str,
        tenant_id: str,
    ):
        calls.append((user_id, tenant_id))
        return _result()

    monkeypatch.setattr(server, "run_officepilot", workflow)
    with client:
        alice = client.post(
            "/executions",
            json={"user_request": "Prepare my next meeting."},
            headers={"Idempotency-Key": "shared-key"},
        )
        bob = client.post(
            "/executions",
            json={"user_request": "Prepare my next meeting."},
            headers=_auth_headers("bob", "bob-test-password")
            | {"Idempotency-Key": "shared-key"},
        )
        assert alice.status_code == bob.status_code == 202
        assert alice.json()["execution_id"] != bob.json()["execution_id"]
        _wait_for_terminal(client, alice.json()["status_url"])
        _wait_for_terminal(
            client,
            bob.json()["status_url"],
            headers=_auth_headers("bob", "bob-test-password"),
        )

    assert set(calls) == {
        ("user-alice", "tenant-alice"),
        ("user-bob", "tenant-bob"),
    }
