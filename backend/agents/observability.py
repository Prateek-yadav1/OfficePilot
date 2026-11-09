"""Privacy-conscious lifecycle logging for OfficePilot agents."""

import logging
import re
import sqlite3
import asyncio
from contextvars import ContextVar, Token
from time import monotonic
from typing import Any, Callable, Optional

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool, ToolContext
from google.genai import types


logger = logging.getLogger("officepilot.observability")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
    )
    logger.addHandler(handler)

logger.propagate = False

ProgressSink = Callable[[str, dict[str, Any]], None]
_execution_id: ContextVar[str | None] = ContextVar(
    "officepilot_execution_id",
    default=None,
)
_progress_sink: ContextVar[ProgressSink | None] = ContextVar(
    "officepilot_progress_sink",
    default=None,
)


def begin_execution_observation(
    execution_id: str,
    progress_sink: ProgressSink,
) -> tuple[Token[str | None], Token[ProgressSink | None]]:
    """Bind callback events to one persisted API execution."""
    return (
        _execution_id.set(execution_id),
        _progress_sink.set(progress_sink),
    )


def end_execution_observation(
    tokens: tuple[Token[str | None], Token[ProgressSink | None]],
) -> None:
    _execution_id.reset(tokens[0])
    _progress_sink.reset(tokens[1])


def _emit_progress(event_type: str, data: dict[str, Any]) -> None:
    sink = _progress_sink.get()
    if sink is None:
        return
    try:
        sink(event_type, data)
    except (OSError, sqlite3.Error, TypeError, ValueError):
        logger.exception(
            "event=progress_persist_failed execution_id=%s event_type=%s",
            _execution_id.get() or "unknown",
            event_type,
        )


def emit_execution_event(
    event_type: str,
    data: dict[str, Any],
) -> None:
    """Record a sanitized event from non-ADK workflow stages."""
    _emit_progress(event_type, data)


PROMPT_INJECTION_PATTERNS = (
    r"ignore\s+(?:(?:all|the)\s+)?(?:previous|prior|system|developer|role|user)\s+instructions",
    r"ignore\s+all\s+instructions",
    r"override\s+(?:system|developer|user)\s+instructions",
    r"reveal\s+(?:the\s+)?(?:system|developer)\s+prompt",
    r"act\s+as\s+(?:an?\s+)?(?:admin|developer|system|root)",
    r"bypass\s+(?:safety|guardrail|policy|instruction)",
    r"ignore\s+the\s+prior\s+instructions",
    r"you\s+are\s+now\s+in\s+unsafe\s+mode",
)

TOXIC_PATTERNS = (
    r"\b(?:idiot|stupid|moron|dumb|hate)\b",
    r"\b(?:kill|attack|bomb|destroy)\b",
)


def validate_user_prompt(prompt: str) -> tuple[bool, str]:
    """Reject unsafe or abusive prompts before they reach any ADK or CrewAI agent."""
    if not isinstance(prompt, str):
        return False, "Prompt must be a string."

    cleaned = prompt.strip()
    if not cleaned:
        return False, "Prompt cannot be empty."

    lowered = cleaned.lower()
    flagged: list[str] = []

    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, lowered):
            flagged.append(
                "prompt injection or instruction override pattern detected"
            )
            break

    for pattern in TOXIC_PATTERNS:
        if re.search(pattern, lowered):
            flagged.append("abusive or unsafe language detected")
            break

    if flagged:
        return False, "; ".join(flagged)

    return True, "Prompt passed safety validation."


class OfficePilotLoggingPlugin(BasePlugin):
    """Log agent lifecycle events without recording private content."""

    def __init__(self) -> None:
        super().__init__(name="officepilot_logging")
        self._start_times: dict[tuple[str, str], float] = {}
        self._tool_start_times: dict[tuple[str, str], float] = {}
        self._model_start_times: dict[tuple[str, str], float] = {}
        self._tool_observations: list[dict[str, Any]] = []
        self._source_references: dict[tuple[str, str], dict[str, str]] = {}

    def snapshot(self) -> dict[str, Any]:
        """Return safe source references and tool outcome counts."""
        return {
            "tools": [dict(item) for item in self._tool_observations],
            "sources": [
                dict(item) for item in self._source_references.values()
            ],
        }

    def _emit_partial_state(
        self,
        callback_context: CallbackContext | ToolContext,
    ) -> None:
        state = getattr(callback_context, "state", None)
        if state is None:
            return
        partial_data: dict[str, Any] = {}
        for key in ("client_name", "client_match", "discovered_meeting"):
            value = state.get(key)
            if isinstance(value, str):
                partial_data[key] = value[:500]
            elif isinstance(value, dict):
                partial_data[key] = value
        for key in ("email_context", "document_context", "calendar_context"):
            value = state.get(key)
            if isinstance(value, str) and value.strip():
                partial_data[key] = value[:8000]
        meeting_context = state.get("meeting_context")
        model_dump = getattr(meeting_context, "model_dump", None)
        if callable(model_dump):
            context = model_dump()
            if isinstance(context, dict):
                fields = {
                    "client",
                    "important_communication",
                    "client_concerns",
                    "relevant_documents",
                    "important_document_facts",
                    "meeting_title",
                    "meeting_date",
                    "meeting_time",
                    "participants",
                    "missing_information",
                }
                partial_data["meeting_context"] = {
                    key: context[key]
                    for key in fields
                    if key in context
                }
        if partial_data:
            emit_execution_event(
                "partial_result_updated",
                {
                    "session_id": str(state.get("session_id") or ""),
                    "partial_data": partial_data,
                },
            )

    def _persist_retrieval_result(
        self,
        tool_name: str,
        result: Any,
        tool_context: ToolContext,
    ) -> None:
        state = getattr(tool_context, "state", None)
        if state is None or not hasattr(state, "__setitem__"):
            return

        key_by_tool = {
            "search_emails": "email_context",
            "get_calendar": "calendar_context",
            "search_client_documents": "document_context",
            "retrieve_documents": "document_context",
            "discover_next_meeting": "calendar_context",
        }
        state_key = key_by_tool.get(tool_name)
        if state_key is None:
            return

        if tool_name in {"search_client_documents", "retrieve_documents"}:
            records = result if isinstance(result, list) else []
            lines = []
            for record in records:
                if not isinstance(record, dict):
                    continue
                title = str(record.get("title") or "Client document")
                content = str(record.get("content") or "").strip()
                score = record.get("relevance_score")
                lines.append(
                    f"Document: {title}"
                    + (f" (relevance {score})" if score is not None else "")
                    + (f"\n{content}" if content else "")
                )
            text = "\n\n".join(lines) or (
                "Document retrieval completed with zero results."
            )
        elif tool_name == "search_emails":
            records = result.get("emails", []) if isinstance(result, dict) else []
            lines = [
                "\n".join(
                    value
                    for value in (
                        f"Subject: {record.get('subject')}"
                        if record.get("subject")
                        else "",
                        f"Date: {record.get('date')}"
                        if record.get("date")
                        else "",
                        f"Snippet: {record.get('snippet')}"
                        if record.get("snippet")
                        else "",
                    )
                    if value
                )
                for record in records
                if isinstance(record, dict)
            ]
            text = "\n\n".join(lines) or (
                "Gmail retrieval completed with zero results."
            )
        elif tool_name == "get_calendar":
            records = (
                result.get("meetings", [])
                if isinstance(result, dict)
                else []
            )
            lines = [
                "\n".join(
                    value
                    for value in (
                        f"Meeting: {record.get('title')}"
                        if record.get("title")
                        else "",
                        f"Start: {record.get('start')}"
                        if record.get("start")
                        else "",
                        f"End: {record.get('end')}"
                        if record.get("end")
                        else "",
                        (
                            "Participants: "
                            + ", ".join(str(item) for item in record["participants"])
                        )
                        if isinstance(record.get("participants"), list)
                        and record["participants"]
                        else "",
                    )
                    if value
                )
                for record in records
                if isinstance(record, dict)
            ]
            text = "\n\n".join(lines) or (
                "Calendar retrieval completed with zero results."
            )
        else:
            meeting = result.get("meeting") if isinstance(result, dict) else None
            text = (
                "\n".join(
                    f"{label}: {meeting[key]}"
                    for key, label in (
                        ("title", "Meeting"),
                        ("start", "Start"),
                        ("end", "End"),
                    )
                    if isinstance(meeting, dict) and meeting.get(key)
                )
                or "Calendar discovery completed without a matching meeting."
            )

        state[state_key] = text[:8000]

    def _record_source_references(
        self,
        tool_name: str,
        result: Any,
    ) -> None:
        references: list[dict[str, str]] = []
        if tool_name == "search_emails" and isinstance(result, dict):
            emails = result.get("emails", [])
            if isinstance(emails, list):
                references.extend(
                    {
                        "source": "Gmail",
                        "id": str(item["id"]),
                        "label": str(item.get("subject") or "Email"),
                    }
                    for item in emails
                    if isinstance(item, dict) and item.get("id")
                )
        elif tool_name == "get_calendar" and isinstance(result, dict):
            meetings = result.get("meetings", [])
            if isinstance(meetings, list):
                references.extend(
                    {
                        "source": "Google Calendar",
                        "id": str(item["id"]),
                        "label": str(item.get("title") or "Calendar event"),
                        **(
                            {"url": str(item["html_link"])}
                            if item.get("html_link")
                            else {}
                        ),
                    }
                    for item in meetings
                    if isinstance(item, dict) and item.get("id")
                )
        elif tool_name == "discover_next_meeting" and isinstance(result, dict):
            meeting = result.get("meeting")
            if isinstance(meeting, dict) and meeting.get("id"):
                references.append(
                    {
                        "source": "Google Calendar",
                        "id": str(meeting["id"]),
                        "label": str(meeting.get("title") or "Calendar event"),
                        **(
                            {"url": str(meeting["html_link"])}
                            if meeting.get("html_link")
                            else {}
                        ),
                    }
                )
        elif tool_name in {
            "search_client_documents",
            "retrieve_documents",
        } and isinstance(result, list):
            references.extend(
                {
                    "source": "PostgreSQL / pgvector",
                    "id": str(item.get("id") or item.get("title", "")),
                    "label": str(item.get("title") or "Client document"),
                }
                for item in result
                if isinstance(item, dict)
                and (item.get("id") or item.get("title"))
            )

        for reference in references:
            identity = (reference["source"], reference["id"])
            self._source_references[identity] = reference

    async def before_agent_callback(
        self,
        *,
        agent: BaseAgent,
        callback_context: CallbackContext,
    ) -> Optional[types.Content]:
        invocation_id = getattr(callback_context, "invocation_id", "unknown")
        agent_name = agent.name
        key = (invocation_id, agent_name)

        self._start_times[key] = monotonic()

        logger.info(
            "event=agent_started agent=%s invocation_id=%s",
            agent_name,
            invocation_id,
        )
        _emit_progress(
            "agent_started",
            {"agent": agent_name, "invocation_id": invocation_id},
        )
        return None

    async def after_agent_callback(
        self,
        *,
        agent: BaseAgent,
        callback_context: CallbackContext,
    ) -> Optional[types.Content]:
        invocation_id = getattr(callback_context, "invocation_id", "unknown")
        agent_name = agent.name
        key = (invocation_id, agent_name)

        started_at = self._start_times.pop(key, None)
        duration_ms = (
            round((monotonic() - started_at) * 1000, 2)
            if started_at is not None
            else None
        )

        logger.info(
            "event=agent_completed agent=%s invocation_id=%s duration_ms=%s",
            agent_name,
            invocation_id,
            duration_ms,
        )
        _emit_progress(
            "agent_completed",
            {
                "agent": agent_name,
                "invocation_id": invocation_id,
                "duration_ms": duration_ms,
            },
        )
        self._emit_partial_state(callback_context)
        return None

    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> Optional[LlmResponse]:
        invocation_id = getattr(callback_context, "invocation_id", "unknown")
        agent_name = getattr(callback_context, "agent_name", "unknown")
        self._model_start_times[(invocation_id, agent_name)] = monotonic()
        _emit_progress(
            "model_started",
            {
                "agent": agent_name,
                "invocation_id": invocation_id,
            },
        )
        return None

    async def after_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> Optional[LlmResponse]:
        invocation_id = getattr(callback_context, "invocation_id", "unknown")
        agent_name = getattr(callback_context, "agent_name", "unknown")
        started_at = self._model_start_times.pop(
            (invocation_id, agent_name),
            None,
        )
        duration_ms = (
            round((monotonic() - started_at) * 1000, 2)
            if started_at is not None
            else None
        )
        usage = getattr(llm_response, "usage_metadata", None)
        token_usage = {
            "prompt_tokens": getattr(usage, "prompt_token_count", None),
            "completion_tokens": getattr(usage, "candidates_token_count", None),
            "total_tokens": getattr(usage, "total_token_count", None),
        }
        logger.info(
            "event=model_completed agent=%s invocation_id=%s duration_ms=%s "
            "prompt_tokens=%s completion_tokens=%s total_tokens=%s",
            agent_name,
            invocation_id,
            duration_ms,
            token_usage["prompt_tokens"],
            token_usage["completion_tokens"],
            token_usage["total_tokens"],
        )
        _emit_progress(
            "model_completed",
            {
                "agent": agent_name,
                "invocation_id": invocation_id,
                "duration_ms": duration_ms,
                **token_usage,
            },
        )
        return None

    async def before_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
    ) -> Optional[dict[str, Any]]:
        """Validate tool inputs before execution; never log input contents."""
        tool_name = getattr(tool, "name", type(tool).__name__)
        args = tool_args if isinstance(tool_args, dict) else {}

        client_tools = {
            "search_emails",
            "get_calendar",
            "discover_next_meeting",
            "search_client_documents",
            "retrieve_documents",
            "create_followup_task",
            "execute_followup_task_via_mcp",
        }
        write_tools = {
            "create_followup_task",
            "execute_followup_task_via_mcp",
        }

        def blocked(reason: str) -> dict[str, Any]:
            logger.warning(
                "event=tool_blocked tool=%s reason=%s",
                tool_name,
                reason,
            )
            return {
                "status": "blocked",
                "error": f"OfficePilot guardrail blocked this tool call: {reason}",
            }

        if tool_name in client_tools:
            tenant_id = getattr(tool_context, "state", {}).get("tenant_id")
            if not isinstance(tenant_id, str) or not tenant_id.strip():
                return blocked("an authenticated tenant context is required")
            client = args.get("client")
            if tool_name not in {"discover_next_meeting"} and (
                not isinstance(client, str) or not client.strip()
            ):
                return blocked("client must be non-empty text")
            if tool_name not in {"discover_next_meeting"} and len(client.strip()) > 120:
                return blocked("client exceeds the 120-character limit")
            if tool_name not in {"discover_next_meeting"} and any(
                ord(ch) < 32 and ch not in "\t\r\n" for ch in client
            ):
                return blocked("client contains unsupported control characters")

        if tool_name in write_tools:
            if getattr(tool_context, "state", {}).get(
                "allow_action_proposal"
            ) is not True:
                return blocked("task writes are disabled by workflow policy")
            details = args.get("task_details")
            if not isinstance(details, str) or not details.strip():
                return blocked("task_details must be non-empty text")
            if len(details.strip()) > 2000:
                return blocked("task_details exceeds the 2000-character limit")

        invocation_id = getattr(tool_context, "invocation_id", "unknown")
        self._tool_start_times[(invocation_id, tool_name)] = monotonic()
        logger.info(
            "event=tool_started tool=%s invocation_id=%s",
            tool_name,
            invocation_id,
        )
        _emit_progress(
            "tool_started",
            {"tool": tool_name, "invocation_id": invocation_id},
        )
        return None


    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: Any,
    ) -> Optional[dict[str, Any]]:
        """Log a sanitized tool outcome without logging returned content."""
        tool_name = getattr(tool, "name", type(tool).__name__)
        invocation_id = getattr(tool_context, "invocation_id", "unknown")
        started_at = self._tool_start_times.pop(
            (invocation_id, tool_name),
            None,
        )
        duration_ms = (
            round((monotonic() - started_at) * 1000, 2)
            if started_at is not None
            else None
        )

        failed = (
            isinstance(result, dict)
            and (
                bool(result.get("error"))
                or result.get("status") in {"error", "blocked"}
            )
        )
        skipped = (
            isinstance(result, dict)
            and result.get("status") == "skipped"
        )
        result_count = (
            len(result)
            if isinstance(result, list)
            else (
                result.get("count")
                if isinstance(result, dict)
                and isinstance(result.get("count"), int)
                else (
                    len(result.get("emails", []))
                    if isinstance(result, dict)
                    and isinstance(result.get("emails"), list)
                    else (
                        len(result.get("meetings", []))
                        if isinstance(result, dict)
                        and isinstance(result.get("meetings"), list)
                        else (
                            1
                            if isinstance(result, dict)
                            and isinstance(result.get("meeting"), dict)
                            else (
                                0
                                if isinstance(result, dict)
                                and result.get("status") == "not_found"
                                else None
                            )
                        )
                    )
                )
            )
        )
        outcome = "error" if failed else ("skipped" if skipped else "success")
        source_reference_start = set(self._source_references)
        if outcome == "success":
            self._record_source_references(tool_name, result)
            self._persist_retrieval_result(tool_name, result, tool_context)
        source_references = [
            dict(reference)
            for identity, reference in self._source_references.items()
            if identity not in source_reference_start
        ]
        observation = {
            "tool": tool_name,
            "outcome": outcome,
            "duration_ms": duration_ms,
            "result_count": result_count,
        }
        self._tool_observations.append(observation)
        logger.info(
            "event=tool_completed tool=%s invocation_id=%s outcome=%s "
            "duration_ms=%s",
            tool_name,
            invocation_id,
            outcome,
            duration_ms,
        )
        _emit_progress(
            "tool_completed",
            {
                "tool": tool_name,
                "invocation_id": invocation_id,
                "outcome": outcome,
                "duration_ms": duration_ms,
                "result_count": result_count,
                "source_references": source_references,
            },
        )
        if outcome == "success":
            self._emit_partial_state(tool_context)
        return None

    async def on_agent_error_callback(
        self,
        *,
        agent: BaseAgent,
        callback_context: CallbackContext,
        error: Exception,
    ) -> None:
        logger.error(
            "event=agent_failed agent=%s invocation_id=%s error_type=%s",
            agent.name,
            getattr(callback_context, "invocation_id", "unknown"),
            type(error).__name__,
        )
        key = (
            getattr(callback_context, "invocation_id", "unknown"),
            agent.name,
        )
        started_at = self._start_times.pop(key, None)
        _emit_progress(
            "agent_timed_out"
            if isinstance(error, asyncio.TimeoutError)
            else "agent_failed",
            {
                "agent": agent.name,
                "error_type": type(error).__name__,
                "duration_ms": (
                    round((monotonic() - started_at) * 1000, 2)
                    if started_at is not None
                    else None
                ),
            },
        )
        self._emit_partial_state(callback_context)

    async def on_model_error_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
        error: Exception,
    ) -> Optional[LlmResponse]:
        invocation_id = getattr(callback_context, "invocation_id", "unknown")
        agent_name = getattr(callback_context, "agent_name", "unknown")
        started_at = self._model_start_times.pop(
            (invocation_id, agent_name),
            None,
        )
        event_type = (
            "model_timed_out" if _is_timeout_error(error) else "model_failed"
        )
        duration_ms = (
            round((monotonic() - started_at) * 1000, 2)
            if started_at is not None
            else None
        )
        logger.warning(
            "event=%s agent=%s invocation_id=%s error_type=%s duration_ms=%s",
            event_type,
            agent_name,
            invocation_id,
            type(error).__name__,
            duration_ms,
        )
        error_details = _safe_error_metadata(error)
        _emit_progress(
            event_type,
            {
                "agent": agent_name,
                "invocation_id": invocation_id,
                "duration_ms": duration_ms,
                "error_type": type(error).__name__,
                **error_details,
            },
        )
        return None

    async def on_tool_error_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        error: Exception,
    ) -> Optional[dict[str, Any]]:
        tool_name = getattr(tool, "name", type(tool).__name__)
        invocation_id = getattr(tool_context, "invocation_id", "unknown")
        started_at = self._tool_start_times.pop(
            (invocation_id, tool_name),
            None,
        )
        duration_ms = (
            round((monotonic() - started_at) * 1000, 2)
            if started_at is not None
            else None
        )
        _emit_progress(
            "tool_failed",
            {
                "tool": tool_name,
                "invocation_id": invocation_id,
                "duration_ms": duration_ms,
                "error_type": type(error).__name__,
                **_safe_error_metadata(error),
            },
        )
        self._tool_observations.append(
            {
                "tool": tool_name,
                "outcome": "error",
                "duration_ms": duration_ms,
                "error_type": type(error).__name__,
                **_safe_error_metadata(error),
            }
        )
        self._emit_partial_state(tool_context)
        return None


def _safe_error_metadata(error: BaseException) -> dict[str, Any]:
    """Extract allowlisted provider/error metadata, never exception text."""
    metadata: dict[str, Any] = {}
    seen: set[int] = set()
    pending = [error]
    nested_types: list[str] = []

    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        nested_types.append(type(current).__name__)

        status = getattr(current, "status_code", None)
        if status is None:
            status = getattr(getattr(current, "resp", None), "status", None)
        if isinstance(status, int) and 100 <= status <= 599:
            metadata.setdefault("http_status", status)

        for attribute, key in (
            ("code", "provider_error_code"),
            ("param", "provider_error_param"),
            ("llm_provider", "provider"),
            ("model", "model"),
        ):
            value = getattr(current, attribute, None)
            if (
                isinstance(value, str)
                and value
                and len(value) <= 120
                and re.fullmatch(r"[A-Za-z0-9._:/-]+", value)
            ):
                metadata.setdefault(key, value)

        if isinstance(current, BaseExceptionGroup):
            pending.extend(reversed(current.exceptions))
        cause = current.__cause__ or current.__context__
        if cause is not None:
            pending.append(cause)

    if len(set(nested_types)) > 1:
        metadata["nested_error_types"] = list(dict.fromkeys(nested_types))[:8]
    return metadata


def _is_timeout_error(error: Exception) -> bool:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (asyncio.TimeoutError, TimeoutError)):
            return True
        error_type = type(current).__name__.casefold()
        if "timeout" in error_type or "timedout" in error_type:
            return True
        current = current.__cause__ or current.__context__
    return False
