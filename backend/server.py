"""HTTP API and frontend for asynchronous OfficePilot workflows."""

from __future__ import annotations

import asyncio
import base64
import binascii
from contextlib import asynccontextmanager
import hmac
import logging
import os
import sys
from pathlib import Path
from time import perf_counter
from typing import Any, AsyncIterator, Coroutine
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.auth import (
    AuthenticatedUser,
    authenticate_basic_credentials,
    validate_auth_configuration,
)
from backend.agents.langfuse_setup import configure_langfuse
from backend.agents.observability import (
    begin_execution_observation,
    end_execution_observation,
)
from backend.a2a_demo.remote_agent import a2a_app
from backend.execution_store import (
    ExecutionStore,
    IdempotencyConflictError,
)
from main import WorkflowRunResult, _metadata_from_state, run_officepilot


logger = logging.getLogger("officepilot.server")
execution_store = ExecutionStore()
_active_executions: dict[str, asyncio.Task[None]] = {}
_execution_semaphore: asyncio.Semaphore | None = None


_ACTIVE_OPERATIONS = (
    (
        "agent_started",
        {"agent_completed", "agent_failed", "agent_timed_out"},
        ("agent", "invocation_id"),
        "agent_timed_out",
    ),
    (
        "model_started",
        {"model_completed", "model_failed", "model_timed_out"},
        ("agent", "invocation_id"),
        "model_timed_out",
    ),
    (
        "tool_started",
        {"tool_completed", "tool_failed", "tool_timed_out"},
        ("tool", "invocation_id"),
        "tool_timed_out",
    ),
    (
        "crewai_started",
        {"crewai_completed", "crewai_failed", "crewai_timed_out", "crewai_cancelled"},
        (),
        "crewai_timed_out",
    ),
    (
        "crewai_model_started",
        {
            "crewai_model_completed",
            "crewai_model_failed",
            "crewai_model_timed_out",
        },
        ("agent", "agent_iteration", "attempt"),
        "crewai_model_timed_out",
    ),
    (
        "a2a_started",
        {"a2a_completed", "a2a_failed", "a2a_timed_out", "a2a_cancelled"},
        ("direction",),
        "a2a_timed_out",
    ),
)


def _unresolved_operations(
    events: list[dict[str, Any]],
) -> list[tuple[int, str, dict[str, Any], str]]:
    unresolved: dict[tuple[str, tuple[Any, ...]], tuple[int, str, dict[str, Any], str]] = {}
    for event in events:
        event_type = event["type"]
        data = event["data"]
        for start_type, terminal_types, key_fields, timeout_type in _ACTIVE_OPERATIONS:
            if event_type == start_type:
                key = tuple(data.get(field) for field in key_fields)
                unresolved[(start_type, key)] = (
                    event["id"],
                    start_type,
                    data,
                    timeout_type,
                )
                break
            if event_type in terminal_types:
                key = tuple(data.get(field) for field in key_fields)
                unresolved.pop((start_type, key), None)
    return sorted(unresolved.values(), key=lambda item: item[0])


def _record_active_timeouts(
    execution_id: str,
    events: list[dict[str, Any]],
    timeout_seconds: float,
) -> tuple[str, str]:
    active = _unresolved_operations(events)
    for _, start_type, data, timeout_type in active:
        operation_data = {
            key: data[key]
            for key in ("agent", "tool", "task", "invocation_id", "direction")
            if key in data
        }
        operation_data.update(
            {
                "error_type": "TimeoutError",
                "timeout_seconds": timeout_seconds,
            }
        )
        execution_store.append_event(
            execution_id,
            timeout_type,
            operation_data,
        )
    primary = active[-1] if active else None
    if primary is None:
        return "workflow", "unknown"
    _, start_type, data, _ = primary
    operation = {
        "agent_started": "agent",
        "model_started": "model",
        "tool_started": "tool",
        "crewai_started": "crewai",
        "crewai_model_started": "crewai_model",
        "a2a_started": "a2a",
    }[start_type]
    return operation, str(
        data.get("agent") or data.get("tool") or operation
    )


def _failure_payload(
    execution_id: str,
    error: str,
    error_type: str,
    operation: str,
    failed_agent: str,
    duration_ms: float,
) -> dict[str, Any]:
    execution = execution_store.get(execution_id)
    existing_result = (
        execution.get("result")
        if isinstance(execution, dict)
        else None
    )
    partial_data = (
        existing_result.get("partial_data")
        if isinstance(existing_result, dict)
        else None
    )
    state = dict(partial_data) if isinstance(partial_data, dict) else {}
    events = execution_store.events(execution_id, limit=5000)
    tool_observations: list[dict[str, Any]] = []
    sources: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        data = event["data"]
        if event["type"] == "tool_completed":
            tool_observations.append(
                {
                    "tool": data.get("tool"),
                    "outcome": data.get("outcome"),
                    "result_count": data.get("result_count"),
                }
            )
            for source in data.get("source_references", []):
                if isinstance(source, dict) and source.get("source"):
                    key = (str(source["source"]), str(source.get("id") or ""))
                    sources[key] = source
        elif event["type"] == "tool_failed":
            tool_observations.append(
                {
                    "tool": data.get("tool"),
                    "outcome": "error",
                    "error_type": data.get("error_type"),
                }
            )
        elif event["type"] == "tool_timed_out":
            tool_observations.append(
                {
                    "tool": data.get("tool"),
                    "outcome": "timed_out",
                    "error_type": data.get("error_type"),
                }
            )

    session_id = str(state.get("session_id") or "")
    metadata = _metadata_from_state(
        state,
        session_id,
        {
            "tools": tool_observations,
            "sources": list(sources.values()),
        },
    )
    metadata["warnings"].append(
        "Execution ended before the final briefing passed the quality gate. "
        "Partial source findings are not a completed briefing."
    )
    metadata["failure"] = {
        "operation": operation,
        "agent": failed_agent,
        "reason": error,
        "error_type": error_type,
        "duration_ms": round(duration_ms, 2),
    }
    return {
        "response": "",
        "status": "failed",
        "session_id": session_id,
        "incomplete": True,
        "metadata": metadata,
    }


def _persist_progress(execution_id: str, event_type: str, data: dict[str, Any]) -> None:
    if event_type == "partial_result_updated":
        partial_data = data.get("partial_data")
        if isinstance(partial_data, dict):
            execution_store.update_partial_data(execution_id, partial_data)
        return
    execution_store.append_event(execution_id, event_type, data)


def _max_concurrent_workflows() -> int:
    value = os.getenv("OFFICEPILOT_MAX_CONCURRENT_WORKFLOWS", "2")
    try:
        limit = int(value)
    except ValueError as exc:
        raise RuntimeError(
            "OFFICEPILOT_MAX_CONCURRENT_WORKFLOWS must be a positive integer."
        ) from exc
    if limit < 1:
        raise RuntimeError(
            "OFFICEPILOT_MAX_CONCURRENT_WORKFLOWS must be a positive integer."
        )
    return limit


async def _run_with_execution_deadline(
    workflow: Coroutine[Any, Any, WorkflowRunResult],
    timeout_seconds: float,
) -> WorkflowRunResult:
    task = asyncio.create_task(workflow)
    try:
        return await asyncio.wait_for(
            asyncio.shield(task),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as deadline_error:
        if task.done():
            if task.cancelled():
                raise deadline_error
            inner_error = task.exception()
            if isinstance(inner_error, asyncio.TimeoutError):
                raise RuntimeError(
                    "A workflow operation timed out before the execution "
                    "deadline."
                ) from inner_error
            if inner_error is not None:
                raise inner_error
            raise deadline_error

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise deadline_error


def _result_dict(result: WorkflowRunResult) -> dict[str, Any]:
    return {
        "response": result.response,
        "status": result.status,
        "session_id": result.session_id,
        "metadata": result.metadata,
    }


def _workflow_failure_message(
    execution_id: str,
    error: Exception,
) -> tuple[str, str]:
    """Translate recorded provider failures without exposing exception text."""
    events = execution_store.events(execution_id, limit=5000)
    tool_failure = next(
        (
            event["data"]
            for event in reversed(events)
            if event["type"] == "tool_failed"
        ),
        None,
    )
    if (
        isinstance(tool_failure, dict)
        and tool_failure.get("error_type") == "WorkspaceConfigurationError"
    ):
        return (
            "Google Workspace is enabled, but this user has no usable "
            "user-specific OAuth connection. Configure "
            "OFFICEPILOT_WORKSPACE_TOKEN_FILES for the authenticated user, "
            "authorize it with python test_google_apis.py, and restart "
            "OfficePilot. Shared token.json files are intentionally rejected.",
            "WorkspaceConfigurationError",
        )

    model_failure_event = next(
        (
            event
            for event in reversed(events)
            if event["type"] in {"model_failed", "model_timed_out"}
        ),
        None,
    )
    if not isinstance(model_failure_event, dict):
        return f"Workflow failed ({type(error).__name__}).", type(error).__name__

    model_failure = model_failure_event["data"]
    error_type = str(model_failure.get("error_type") or "ModelError")
    agent = str(model_failure.get("agent") or "workflow")
    if "ratelimit" in error_type.casefold() or "quota" in error_type.casefold():
        provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
        if provider == "groq":
            return (
                f"Groq reported a rate limit or exhausted quota in {agent}. "
                "No provider fallback was used. Wait for quota reset or "
                "explicitly switch to Ollama with LLM_PROVIDER=ollama.",
                error_type,
            )
        return (
            f"The configured model provider reported a rate limit in {agent}. "
            "No provider fallback was used; check the provider quota before "
            "retrying.",
            error_type,
        )
    if error_type == "BadRequestError":
        details = []
        provider = model_failure.get("provider")
        status = model_failure.get("http_status")
        error_code = model_failure.get("provider_error_code")
        error_param = model_failure.get("provider_error_param")
        if isinstance(provider, str) and provider:
            details.append(provider)
        if isinstance(status, int):
            details.append(f"HTTP {status}")
        if isinstance(error_code, str) and error_code:
            details.append(f"code {error_code}")
        if isinstance(error_param, str) and error_param:
            details.append(f"parameter {error_param}")
        detail_text = f" ({', '.join(details)})" if details else ""
        return (
            f"The configured model provider rejected the request in {agent}"
            f"{detail_text}. Verify the selected model's request and "
            "tool-calling compatibility, then retry. Private request and "
            "workspace content are not included in this error.",
            error_type,
        )
    if model_failure_event["type"] == "model_timed_out":
        return (
            f"The model request in {agent} timed out. The workflow failed "
            "before the briefing passed its quality gate; completed source "
            "results are retained. Retry the request.",
            error_type,
        )
    if error_type == "APIConnectionError":
        provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
        if provider in {"ollama", "local"}:
            model = os.getenv("OLLAMA_MODEL", "llama3.1").strip()
            api_base = os.getenv(
                "OLLAMA_API_BASE",
                "http://127.0.0.1:11434",
            ).rstrip("/")
            message = (
                f"The local Ollama model provider could not be reached at "
                f"{api_base}. Start Ollama, verify that model '{model}' is "
                "available, then submit a new request."
            )
        else:
            message = (
                "The configured language-model provider could not be "
                "reached. Check provider connectivity and configuration, "
                "then submit a new request."
            )
        return message, error_type

    return (
        f"The language-model request failed in {agent} ({error_type}). "
        "Check the configured provider and service logs, then retry.",
        error_type,
    )


async def _run_execution(
    execution_id: str,
    user_request: str,
    user_id: str,
    tenant_id: str,
) -> None:
    tokens = None
    workflow_started_at = perf_counter()
    try:
        if _execution_semaphore is None:
            raise ValueError(
                "Workflow execution capacity is not initialized."
            )

        async with _execution_semaphore:
            execution_store.mark_running(execution_id)
            tokens = begin_execution_observation(
                execution_id,
                lambda event_type, data: _persist_progress(
                    execution_id,
                    event_type,
                    data,
                ),
            )

            timeout_seconds = float(
                os.getenv("OFFICEPILOT_WORKFLOW_TIMEOUT_SECONDS", "1800")
            )
            if timeout_seconds <= 0:
                raise ValueError(
                    "OFFICEPILOT_WORKFLOW_TIMEOUT_SECONDS must be positive."
                )
            result = await _run_with_execution_deadline(
                run_officepilot(
                    user_request,
                    execution_id=execution_id,
                    user_id=user_id,
                    tenant_id=tenant_id,
                ),
                timeout_seconds,
            )
            payload = _result_dict(result)
            if (
                execution_store.metrics(execution_id)["tool_calls"].get(
                    "search_client_documents",
                    0,
                ) > 0
                and any(
                    event["type"] == "tool_completed"
                    and event["data"].get("tool") == "search_client_documents"
                    and event["data"].get("result_count") == 0
                    for event in execution_store.events(execution_id, limit=5000)
                )
            ):
                payload["metadata"]["warnings"].append(
                    "No documents were indexed for this client."
                )

            result_status = result.status
            if result_status == "completed" and payload["metadata"]["warnings"]:
                result_status = "completed_with_warnings"
                payload["status"] = result_status

            if result_status == "failed":
                quality_errors = result.metadata["quality"].get(
                    "deterministic_errors",
                    [],
                )
                reason = (
                    "Briefing withheld by the quality gate."
                    if not quality_errors
                    else "Briefing withheld by the quality gate: "
                    + "; ".join(str(item) for item in quality_errors)
                )
                execution_store.fail(execution_id, reason, payload)
                payload["metrics"] = execution_store.metrics(execution_id)
                execution_store.update_result(execution_id, payload)
                return

            execution_store.complete(execution_id, result_status, payload)
            payload["metrics"] = execution_store.metrics(execution_id)
            execution_store.update_result(execution_id, payload)
    except asyncio.TimeoutError:
        timeout_seconds = float(
            os.getenv("OFFICEPILOT_WORKFLOW_TIMEOUT_SECONDS", "1800")
        )
        error = (
            "Workflow exceeded its configured execution timeout "
            f"({timeout_seconds:g} seconds)."
        )
        prior_events = execution_store.events(execution_id, limit=5000)
        operation, failed_agent = _record_active_timeouts(
            execution_id,
            prior_events,
            timeout_seconds,
        )
        duration_ms = (perf_counter() - workflow_started_at) * 1000
        execution_store.append_event(
            execution_id,
            "workflow_timed_out",
            {
                "operation": operation,
                "agent": failed_agent,
                "timeout_seconds": timeout_seconds,
                "duration_ms": round(duration_ms, 2),
            },
        )
        payload = _failure_payload(
            execution_id,
            error,
            "TimeoutError",
            operation,
            failed_agent,
            duration_ms,
        )
        execution_store.fail(execution_id, error, payload)
        payload["metrics"] = execution_store.metrics(execution_id)
        execution_store.update_result(execution_id, payload)
        logger.error(
            "event=workflow_timed_out execution_id=%s operation=%s agent=%s "
            "duration_ms=%.2f",
            execution_id,
            operation,
            failed_agent,
            duration_ms,
        )
    except asyncio.CancelledError:
        error = "Workflow execution was cancelled before completion."
        duration_ms = (perf_counter() - workflow_started_at) * 1000
        payload = _failure_payload(
            execution_id,
            error,
            "CancelledError",
            "workflow",
            "workflow",
            duration_ms,
        )
        execution_store.fail(execution_id, error, payload)
        raise
    except Exception as exc:
        error, root_error_type = _workflow_failure_message(
            execution_id,
            exc,
        )
        prior_events = execution_store.events(execution_id, limit=5000)
        active = _unresolved_operations(prior_events)
        operation = "workflow"
        failed_agent = type(exc).__name__
        model_failure = next(
            (
                event["data"]
                for event in reversed(prior_events)
                if event["type"] in {"model_failed", "model_timed_out"}
            ),
            None,
        )
        if isinstance(model_failure, dict):
            operation = "model"
            failed_agent = str(model_failure.get("agent") or "model")
        if active:
            if not isinstance(model_failure, dict):
                _, start_type, data, _ = active[-1]
                operation = start_type.removesuffix("_started")
                failed_agent = str(
                    data.get("agent") or data.get("tool") or operation
                )
        duration_ms = (perf_counter() - workflow_started_at) * 1000
        execution_store.append_event(
            execution_id,
            "workflow_failed",
            {
                "operation": operation,
                "agent": failed_agent,
                "error_type": root_error_type,
                "duration_ms": round(duration_ms, 2),
            },
        )
        payload = _failure_payload(
            execution_id,
            error,
            root_error_type,
            operation,
            failed_agent,
            duration_ms,
        )
        execution_store.fail(execution_id, error, payload)
        payload["metrics"] = execution_store.metrics(execution_id)
        execution_store.update_result(execution_id, payload)
        logger.error(
            "event=workflow_failed execution_id=%s error_type=%s",
            execution_id,
            root_error_type,
        )
    finally:
        if tokens is not None:
            end_execution_observation(tokens)


def _schedule_execution(
    execution_id: str,
    user_request: str,
    user_id: str,
    tenant_id: str,
) -> None:
    task = asyncio.create_task(
        _run_execution(execution_id, user_request, user_id, tenant_id),
        name=f"officepilot-{execution_id}",
    )
    _active_executions[execution_id] = task
    task.add_done_callback(
        lambda completed, key=execution_id: _active_executions.pop(key, None)
    )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global _execution_semaphore
    validate_auth_configuration()
    if len(os.getenv("OFFICEPILOT_A2A_SHARED_SECRET", "")) < 32:
        raise RuntimeError(
            "OFFICEPILOT_A2A_SHARED_SECRET must contain at least 32 characters."
        )
    _execution_semaphore = asyncio.Semaphore(_max_concurrent_workflows())
    recovered = execution_store.recover_orphaned()
    if recovered:
        logger.warning(
            "event=orphaned_executions_recovered count=%s",
            recovered,
        )

    langfuse_client = configure_langfuse()
    try:
        async with a2a_app.router.lifespan_context(a2a_app):
            yield
    finally:
        active = list(_active_executions.values())
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        _execution_semaphore = None
        if langfuse_client is not None:
            try:
                langfuse_client.flush()
            except Exception:
                logger.exception("Failed to flush Langfuse traces.")


app = FastAPI(
    title="OfficePilot",
    version="1.2.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def require_authenticated_access(request: Request, call_next):
    """Protect the UI and every API except health and the internal A2A service."""
    if request.url.path == "/health":
        return await call_next(request)

    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        fetch_site = request.headers.get("Sec-Fetch-Site", "").casefold()
        origin = request.headers.get("Origin")
        if fetch_site == "cross-site":
            return JSONResponse(
                status_code=403,
                content={"detail": "Cross-site requests are not allowed."},
            )
        if origin:
            origin_host = urlsplit(origin).netloc.casefold()
            request_host = request.headers.get("host", "").casefold()
            if not origin_host or origin_host != request_host:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-origin requests are not allowed."},
                )

    if request.url.path == "/a2a" or request.url.path.startswith("/a2a/"):
        expected = os.getenv("OFFICEPILOT_A2A_SHARED_SECRET", "")
        supplied = request.headers.get("X-OfficePilot-A2A-Key", "")
        if not expected or not hmac.compare_digest(supplied, expected):
            return JSONResponse(
                status_code=401,
                content={"detail": "A2A service authentication required."},
            )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    authorization = request.headers.get("Authorization", "")
    scheme, _, encoded = authorization.partition(" ")
    if scheme.casefold() != "basic" or not encoded:
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required."},
            headers={"WWW-Authenticate": 'Basic realm="OfficePilot"'},
        )
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
        username, separator, password = decoded.partition(":")
    except (binascii.Error, UnicodeDecodeError):
        username, separator, password = "", "", ""
    if not separator:
        username, password = "", ""
    try:
        identity = authenticate_basic_credentials(username, password)
    except RuntimeError:
        logger.error("Authentication is unavailable due to invalid configuration.")
        return JSONResponse(
            status_code=503,
            content={"detail": "Authentication is not configured."},
        )
    if identity is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid credentials."},
            headers={"WWW-Authenticate": 'Basic realm="OfficePilot"'},
        )

    request.state.authenticated_user = identity
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; object-src 'none'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'"
    )
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


def _current_user(request: Request) -> AuthenticatedUser:
    identity = getattr(request.state, "authenticated_user", None)
    if not isinstance(identity, AuthenticatedUser):
        raise HTTPException(status_code=401, detail="Authentication required.")
    return identity
FRONTEND_DIR = PROJECT_ROOT / "frontend"
app.mount(
    "/assets",
    StaticFiles(directory=FRONTEND_DIR),
    name="frontend",
)


class BriefRequest(BaseModel):
    user_request: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="The office briefing request to process.",
    )


class ExecutionAccepted(BaseModel):
    execution_id: str
    status: str
    status_url: str
    events_url: str
    duplicate: bool = False


def _submit_workflow(
    request: BriefRequest,
    idempotency_key: str | None,
    identity: AuthenticatedUser,
) -> ExecutionAccepted:
    if idempotency_key is not None:
        idempotency_key = idempotency_key.strip()
        if not idempotency_key or len(idempotency_key) > 200:
            raise HTTPException(
                status_code=400,
                detail="Idempotency-Key must contain 1 to 200 characters.",
            )

    try:
        execution, created = execution_store.create(
            request.user_request.strip(),
            identity.user_id,
            identity.tenant_id,
            idempotency_key,
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    execution_id = execution["execution_id"]
    if created:
        _schedule_execution(
            execution_id,
            request.user_request.strip(),
            identity.user_id,
            identity.tenant_id,
        )
    return ExecutionAccepted(
        execution_id=execution_id,
        status=execution["status"],
        status_url=f"/executions/{execution_id}",
        events_url=f"/executions/{execution_id}/events",
        duplicate=not created,
    )


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/executions",
    response_model=ExecutionAccepted,
    status_code=202,
)
async def create_execution(
    request: BriefRequest,
    response: Response,
    http_request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ExecutionAccepted:
    accepted = _submit_workflow(
        request,
        idempotency_key,
        _current_user(http_request),
    )
    response.headers["Location"] = accepted.status_url
    return accepted


@app.post(
    "/brief",
    response_model=ExecutionAccepted,
    status_code=202,
    deprecated=True,
)
async def create_brief(
    request: BriefRequest,
    response: Response,
    http_request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ExecutionAccepted:
    """Compatibility route; new clients should submit to /executions."""
    accepted = _submit_workflow(
        request,
        idempotency_key,
        _current_user(http_request),
    )
    response.headers["Location"] = accepted.status_url
    return accepted


@app.get("/executions/{execution_id}")
def get_execution(
    execution_id: str,
    request: Request,
) -> dict[str, Any]:
    identity = _current_user(request)
    execution = execution_store.get(
        execution_id,
        user_id=identity.user_id,
        tenant_id=identity.tenant_id,
    )
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found.")
    execution["metrics"] = execution_store.metrics(execution_id)
    execution["latest_event_id"] = execution_store.latest_event_id(execution_id)
    return execution


@app.get("/executions/{execution_id}/events")
def get_execution_events(
    execution_id: str,
    request: Request,
    after: int = 0,
) -> dict[str, Any]:
    identity = _current_user(request)
    if after < 0:
        raise HTTPException(
            status_code=400,
            detail="The after event ID must be non-negative.",
        )
    if execution_store.get(
        execution_id,
        user_id=identity.user_id,
        tenant_id=identity.tenant_id,
    ) is None:
        raise HTTPException(status_code=404, detail="Execution not found.")
    events = execution_store.events(
        execution_id,
        after_event_id=after,
        user_id=identity.user_id,
        tenant_id=identity.tenant_id,
    )
    return {
        "execution_id": execution_id,
        "events": events,
        "latest_event_id": (
            events[-1]["id"]
            if events
            else execution_store.latest_event_id(execution_id)
        ),
    }


app.mount("/", a2a_app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.server:app", host="0.0.0.0", port=8000, reload=False)
