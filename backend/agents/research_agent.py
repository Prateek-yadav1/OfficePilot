import asyncio
import hashlib
import json
import os
import httpx

from google.adk.apps import App
from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.adk.tools import ToolContext
from google.genai import types
from time import perf_counter

from .config import get_model
from .observability import emit_execution_event
from backend.crewai_research.crew import create_research_crew
from backend.crewai_research.config import (
    CREWAI_MODEL_MAX_RETRIES,
    CREWAI_MODEL_TIMEOUT_SECONDS,
)
from backend.crewai_research.observability import (
    begin_crewai_iteration_tracking,
    end_crewai_iteration_tracking,
)
from backend.a2a_demo.client_agent import (
    create_a2a_http_client,
    create_remote_research_agent,
)

_DEFAULT_CREW_TIMEOUT_SECONDS = 300
_MAX_CREW_TIMEOUT_SECONDS = 600
_MAX_RETRIEVED_CONTEXT_CHARS = 12000


class A2AReviewIncomplete(RuntimeError):
    """The research report exists, but its optional A2A review did not."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _crew_timeout_seconds() -> float:
    raw_value = os.getenv(
        "OFFICEPILOT_CREW_TIMEOUT_SECONDS",
        str(_DEFAULT_CREW_TIMEOUT_SECONDS),
    )
    try:
        timeout = float(raw_value)
    except ValueError as exc:
        raise ValueError(
            "OFFICEPILOT_CREW_TIMEOUT_SECONDS must be numeric."
        ) from exc
    if not 0 < timeout <= _MAX_CREW_TIMEOUT_SECONDS:
        raise ValueError(
            "OFFICEPILOT_CREW_TIMEOUT_SECONDS must be between 0 and "
            f"{_MAX_CREW_TIMEOUT_SECONDS}."
        )
    return timeout


def _retrieved_context(tool_context: ToolContext | None) -> str:
    if tool_context is None:
        return "No tenant-scoped retrieval context was available."
    sections = []
    for key, label in (
        ("email_context", "Gmail findings"),
        ("document_context", "PostgreSQL document findings"),
        ("calendar_context", "Calendar findings"),
    ):
        value = tool_context.state.get(key)
        if isinstance(value, str) and value.strip():
            sections.append(f"{label}:\n{value.strip()}")
    meeting_context = tool_context.state.get("meeting_context")
    if meeting_context is not None:
        model_dump = getattr(meeting_context, "model_dump", None)
        meeting_data = (
            model_dump()
            if callable(model_dump)
            else meeting_context
            if isinstance(meeting_context, dict)
            else None
        )
        if isinstance(meeting_data, dict):
            sections.append(
                "Aggregated meeting context:\n"
                + json.dumps(meeting_data, ensure_ascii=True, default=str)
            )
    value = "\n\n".join(sections)
    return value[:_MAX_RETRIEVED_CONTEXT_CHARS] or (
        "No tenant-scoped retrieval context was available."
    )


def _cache_key(
    client: str,
    missing_information: str,
    retrieved_context: str,
    tool_context: ToolContext | None,
) -> str:
    state = tool_context.state if tool_context is not None else {}
    identity = (
        str(state.get("tenant_id") or ""),
        str(state.get("user_id") or ""),
    )
    material = json.dumps(
        [identity, client, missing_information, retrieved_context],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _a2a_failure_reason(exc: Exception) -> str:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, httpx.TimeoutException) or isinstance(
            current,
            asyncio.TimeoutError,
        ):
            return "request_timeout"
        if isinstance(current, httpx.RequestError):
            return "connection_error"
        error_details = str(current).casefold()
        if any(
            name in error_details
            for name in (
                "readtimeout",
                "connecttimeout",
                "timeoutexception",
                "timed out",
            )
        ):
            return "request_timeout"
        if any(
            name in error_details
            for name in (
                "connecterror",
                "connection refused",
                "connection error",
            )
        ):
            return "connection_error"
        current = current.__cause__ or current.__context__
    return "review_failed"


async def _review_with_a2a(report: str) -> str:
    """Send research output to the remote reviewer through ADK's A2A client."""
    started_at = perf_counter()
    emit_execution_event(
        "a2a_started",
        {"direction": "officepilot_to_remote_reviewer"},
    )
    try:
        async with create_a2a_http_client() as httpx_client:
            remote_agent = create_remote_research_agent(httpx_client)
            app = App(
                name="officepilot_a2a_research_review",
                root_agent=remote_agent,
            )
            runner = InMemoryRunner(app=app)
            user_id = "officepilot_research_agent"
            session = await runner.session_service.create_session(
                app_name=app.name,
                user_id=user_id,
            )

            responses: list[str] = []
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session.id,
                new_message=types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=report)],
                ),
            ):
                if getattr(event, "error_code", None):
                    raise A2AReviewIncomplete(
                        _a2a_failure_reason(
                            RuntimeError(
                                f"{event.error_code}: {event.error_message}"
                            )
                        )
                    )
                if event.author == remote_agent.name and event.content:
                    responses.extend(
                        part.text
                        for part in event.content.parts
                        if part.text
                    )

            if not responses:
                raise RuntimeError("A2A reviewer returned no text response.")
    except asyncio.CancelledError:
        emit_execution_event(
            "a2a_cancelled",
            {
                "duration_ms": round(
                    (perf_counter() - started_at) * 1000,
                    2,
                ),
            },
        )
        raise
    except A2AReviewIncomplete as exc:
        event_type = (
            "a2a_timed_out"
            if exc.reason == "request_timeout"
            else "a2a_failed"
        )
        emit_execution_event(
            event_type,
            {
                "failure_reason": exc.reason,
                "duration_ms": round(
                    (perf_counter() - started_at) * 1000,
                    2,
                ),
            },
        )
        raise
    except httpx.TimeoutException as exc:
        emit_execution_event(
            "a2a_timed_out",
            {
                "error_type": type(exc).__name__,
                "duration_ms": round(
                    (perf_counter() - started_at) * 1000,
                    2,
                ),
            },
        )
        raise A2AReviewIncomplete("request_timeout") from exc
    except httpx.RequestError as exc:
        emit_execution_event(
            "a2a_failed",
            {
                "error_type": type(exc).__name__,
                "failure_reason": "connection_error",
                "duration_ms": round(
                    (perf_counter() - started_at) * 1000,
                    2,
                ),
            },
        )
        raise A2AReviewIncomplete("connection_error") from exc
    except Exception as exc:
        reason = _a2a_failure_reason(exc)
        event_type = (
            "a2a_timed_out" if reason == "request_timeout" else "a2a_failed"
        )
        emit_execution_event(
            event_type,
            {
                "error_type": type(exc).__name__,
                "failure_reason": reason,
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        raise A2AReviewIncomplete(reason) from exc

    emit_execution_event(
        "a2a_completed",
        {
            "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            "response_received": True,
        },
    )
    return "\n".join(responses)


async def run_crewai_research(
    client: str,
    missing_information: str,
    tool_context: ToolContext | None = None,
) -> str:
    """Analyze retrieved context with CrewAI and request an advisory A2A review."""
    if not isinstance(client, str) or not client.strip():
        raise ValueError("client must be non-empty text.")
    if not isinstance(missing_information, str) or not missing_information.strip():
        raise ValueError("missing_information must be non-empty text.")
    retrieved_context = _retrieved_context(tool_context)
    result_cache: dict[str, str] | None = None
    cache_key = _cache_key(
        client.strip(),
        missing_information.strip(),
        retrieved_context,
        tool_context,
    )
    if tool_context is not None:
        existing_cache = tool_context.state.get("crewai_research_cache")
        if isinstance(existing_cache, dict):
            result_cache = existing_cache
            cached_result = existing_cache.get(cache_key)
            if isinstance(cached_result, str):
                emit_execution_event(
                    "crewai_deduplicated",
                    {"reason": "identical_request_in_same_execution"},
                )
                return cached_result
        else:
            result_cache = {}

    timeout_seconds = _crew_timeout_seconds()
    crew_started_at = perf_counter()
    iteration_token = begin_crewai_iteration_tracking()
    emit_execution_event(
        "crewai_started",
        {
            "timeout_seconds": timeout_seconds,
            "model_timeout_seconds": CREWAI_MODEL_TIMEOUT_SECONDS,
            "max_retries": CREWAI_MODEL_MAX_RETRIES,
            "max_iterations_per_agent": 1,
            "agents": [
                "Client Research Specialist",
                "Research Analyst",
                "Research Quality Reviewer",
            ],
        },
    )
    crew = None
    try:
        crew = create_research_crew()
        result = await asyncio.wait_for(
            crew.kickoff_async(
                inputs={
                    "client": client.strip(),
                    "missing_information": missing_information.strip(),
                    "retrieved_context": retrieved_context,
                }
            ),
            timeout=timeout_seconds,
        )
    except asyncio.CancelledError:
        emit_execution_event(
            "crewai_cancelled",
            {
                "duration_ms": round(
                    (perf_counter() - crew_started_at) * 1000,
                    2,
                ),
            },
        )
        raise
    except asyncio.TimeoutError:
        emit_execution_event(
            "crewai_timed_out",
            {
                "duration_ms": round(
                    (perf_counter() - crew_started_at) * 1000,
                    2,
                ),
                "timeout_seconds": timeout_seconds,
                "tasks_completed": _completed_task_count(crew),
            },
        )
        partial_report = _partial_crew_report(crew)
        incomplete_report = _incomplete_research(
            partial_report,
            reason="CrewAI research exceeded its execution time limit.",
            review_status="not_run",
        )
        if result_cache is not None:
            result_cache[cache_key] = incomplete_report
            tool_context.state["crewai_research_cache"] = result_cache
        return incomplete_report
    except Exception as exc:
        error_type = type(exc).__name__
        rate_limited = "ratelimit" in error_type.casefold() or (
            "too many" in error_type.casefold()
        )
        emit_execution_event(
            "crewai_failed",
            {
                "duration_ms": round(
                    (perf_counter() - crew_started_at) * 1000,
                    2,
                ),
                "error_type": error_type,
                "tasks_completed": _completed_task_count(crew),
            },
        )
        if rate_limited:
            warning = _rate_limit_message()
            emit_execution_event(
                "provider_rate_limited",
                {
                    "component": "crewai",
                    "provider": os.getenv(
                        "LLM_PROVIDER",
                        "ollama",
                    ).strip().lower(),
                },
            )
            if tool_context is not None:
                warnings = tool_context.state.get("execution_warnings", [])
                if not isinstance(warnings, list):
                    warnings = [str(warnings)]
                if warning not in warnings:
                    warnings.append(warning)
                tool_context.state["execution_warnings"] = warnings
            failure_reason = warning
        else:
            failure_reason = (
                "CrewAI research stopped before all stages completed "
                f"({error_type})."
            )
        partial_report = _partial_crew_report(crew)
        if not partial_report:
            report = _incomplete_research(
                "",
                reason=(
                    failure_reason
                    if rate_limited
                    else (
                        "CrewAI failed before producing usable research "
                        f"findings ({error_type})."
                    )
                ),
                review_status="not_completed",
            )
            if result_cache is not None:
                result_cache[cache_key] = report
                tool_context.state["crewai_research_cache"] = result_cache
            return report
        report = _incomplete_research(
            partial_report,
            reason=failure_reason,
            review_status="incomplete",
        )
        if result_cache is not None:
            result_cache[cache_key] = report
            tool_context.state["crewai_research_cache"] = result_cache
        return report
    finally:
        end_crewai_iteration_tracking(iteration_token)

    emit_execution_event(
        "crewai_completed",
        {
            "duration_ms": round((perf_counter() - crew_started_at) * 1000, 2),
            "tasks": 3,
            "tasks_completed": _completed_task_count(crew),
        },
    )
    report = str(result).strip()
    if not report:
        raise RuntimeError("CrewAI research returned an empty report.")

    review_input = (
        f"Client: {client.strip()}\n"
        f"Requested research: {missing_information.strip()}\n"
        f"CrewAI research report:\n{report}"
    )
    try:
        a2a_review = await _review_with_a2a(review_input)
        final_report = (
            f"CrewAI research report:\n{report}\n\n"
            "Remote A2A reviewer response (advisory; not source verification):\n"
            f"{a2a_review}"
        )
    except A2AReviewIncomplete as exc:
        final_report = _incomplete_research(
            report,
            reason=f"A2A review incomplete ({exc.reason}).",
            review_status="incomplete",
        )
    if result_cache is not None:
        result_cache[cache_key] = final_report
        tool_context.state["crewai_research_cache"] = result_cache
    return final_report


def _completed_task_count(crew: object) -> int:
    return sum(
        1
        for task in getattr(crew, "tasks", [])
        if getattr(task, "output", None) is not None
    )


def _partial_crew_report(crew: object) -> str:
    reports = []
    for task in getattr(crew, "tasks", []):
        output = getattr(task, "output", None)
        raw = getattr(output, "raw", None)
        if isinstance(raw, str) and raw.strip():
            reports.append(raw.strip())
    return "\n\n".join(reports)


def _incomplete_research(
    report: str,
    reason: str,
    review_status: str,
) -> str:
    content = report.strip() or "No usable CrewAI research findings were produced."
    return (
        f"CrewAI research report (incomplete):\n{content}\n\n"
        f"Research status: incomplete. Reason: {reason}\n"
        f"Review status: {review_status}. No successful review is claimed."
    )


def _rate_limit_message() -> str:
    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    if provider == "groq":
        return (
            "Groq reported a rate limit or exhausted free-tier quota during "
            "CrewAI research. No provider fallback was used. Wait for quota "
            "reset or explicitly switch to Ollama with LLM_PROVIDER=ollama."
        )
    return (
        "The selected model provider reported a rate limit during CrewAI "
        "research. No provider fallback was used."
    )


research_agent = Agent(
    name="research_agent",

    model=get_model(),

    description=(
        "Delegates complex client research to a nested "
        "CrewAI workflow and an independent reviewer over A2A."
    ),

    instruction="""
You are the Research Agent in OfficePilot.

Your responsibility is to investigate information that is missing
from the current meeting context.

CLIENT:
{client_name}

INFORMATION CHECK:
{information_status}

Follow these steps:

1. Call the run_crewai_research tool using:

   client = the current client

   missing_information = the missing information

   The tool automatically receives the Gmail, Calendar, and PostgreSQL
   summaries already retrieved for this execution. Do not request duplicate
   research for facts already covered by those summaries.

2. The tool runs the CrewAI research workflow using:

   - Researcher Agent
   - Analyst Agent
   - Reviewer Agent

3. The same tool sends the report to the remote A2A reviewer and returns
   its response. Treat that response as advisory, not as evidence.

4. Summarize the CrewAI findings and clearly identify uncertainties.

5. Never invent information. The remote reviewer is not a new source and
   cannot verify information beyond the supplied context. Do not describe
   findings as verified because the reviewer agreed with them.
6. If the result marks research or review incomplete, preserve that status
   and do not describe the research as successfully reviewed.

If the Information Checker says ENOUGH, return:

No additional research required.

Return a concise research report.
""",

    tools=[run_crewai_research],
    output_key="research_context",
)