"""Deterministic checks for OfficePilot's generated meeting briefing."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types

from .schemas import MeetingContext


REQUIRED_HEADINGS = (
    "## Client",
    "## Meeting Details",
    "## Key Client Priorities",
    "## Client Concerns",
    "## Important Facts",
    "## Additional Research",
    "## Potential Risks",
    "## Questions to Ask",
    "## Recommended Discussion Topics",
    "## Actionable Steps",
    "## Executive Summary",
)

ISO_DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

UPCOMING_MEETING_PATTERN = re.compile(
    r"\b(?:"
    r"tomorrow(?:['’]s)?\s+(?:meeting|call)"
    r"|meeting\s+(?:scheduled\s+)?for\s+tomorrow"
    r"|meeting\s+tomorrow"
    r"|upcoming\s+meeting"
    r")\b",
    re.IGNORECASE,
)

META_COMMENTARY_PATTERN = re.compile(
    r"^\\s*(?:"
    r"to refine the briefing"
    r"|here(?:'s| is) an example"
    r"|the following changes can be made"
    r"|the improved briefing"
    r")\\b",
    re.IGNORECASE | re.MULTILINE,
)


TASK_RECORD_PATTERN = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*{1,2}\s*)?"
    r"(?:Task\s+\d+|Assignee|Deadline|Status|Priority)\s*:",
    re.IGNORECASE | re.MULTILINE,
)


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    """Accept a structured mapping or a JSON-encoded mapping."""
    if isinstance(value, Mapping):
        return value

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None

        return parsed if isinstance(parsed, Mapping) else None

    return None


def validate_briefing_state(state: Mapping[str, Any]) -> list[str]:
    """Return deterministic validation errors; an empty list means pass."""
    errors: list[str] = []

    briefing = state.get("final_briefing")
    if not isinstance(briefing, str) or not briefing.strip():
        return ["The final briefing is missing or empty."]

    for heading in REQUIRED_HEADINGS:
        if heading not in briefing:
            errors.append(f"Required section is missing: {heading}")

    first_nonempty_line = next(
        (line.strip() for line in briefing.splitlines() if line.strip()),
        "",
    )

    if first_nonempty_line != "# Meeting Briefing":
        errors.append(
            "The final briefing must start with '# Meeting Briefing' "
            "and contain no introductory commentary."
        )

    if META_COMMENTARY_PATTERN.search(briefing):
        errors.append(
            "The final briefing contains review commentary or an example "
            "instead of only the completed briefing."
        )

    context = _as_mapping(state.get("meeting_context"))
    if context is None:
        errors.append(
            "Meeting context is not a structured object; "
            "source-grounded validation cannot be completed."
        )
        return errors

    try:
        validated_context = MeetingContext.model_validate(context)
        meeting_context = validated_context.model_dump()
    except Exception as exc:
        errors.append(
            "Meeting context failed Pydantic validation "
            f"({type(exc).__name__})."
        )
        return errors

    source_keys = (
        "client_name",
        "email_context",
        "document_context",
        "calendar_context",
        "meeting_context",
        "research_context",
        "analysis_context",
    )
    source_text = "\n".join(
        str(state.get(key, "")) for key in source_keys
    )

    # Every explicit ISO date in the briefing must occur in supplied sources.
    for claimed_date in sorted(set(ISO_DATE_PATTERN.findall(briefing))):
        if claimed_date not in source_text:
            errors.append(
                f"Briefing contains an explicit date not found in source "
                f"context: {claimed_date}"
            )

    # Do not describe a known past meeting as tomorrow/upcoming.
    meeting_date_text = str(meeting_context.get("meeting_date", "")).strip()
    try:
        meeting_date = date.fromisoformat(meeting_date_text)
    except (TypeError, ValueError):
        meeting_date = None

    if (
        meeting_date is not None
        and meeting_date < date.today()
        and UPCOMING_MEETING_PATTERN.search(briefing)
    ):
        errors.append(
            f"The source meeting date {meeting_date.isoformat()} is in the "
            "past, but the briefing describes a meeting as tomorrow or upcoming."
        )

    # This document is a meeting briefing, not a task-creation report.
    if TASK_RECORD_PATTERN.search(briefing):
        errors.append(
            "The briefing contains task-record fields such as task IDs, "
            "assignees, deadlines, status, or priority. Keep task proposals "
            "separate and explicitly approved."
        )

    return errors


class QualityBlockedAgent(BaseAgent):
    """Terminal response when deterministic quality checks do not pass."""

    async def _run_async_impl(
        self,
        ctx: InvocationContext,
    ):
        ctx.session.state["execution_status"] = "failed"
        issues = ctx.session.state.get("deterministic_quality_errors", [])
        if not isinstance(issues, list):
            issues = [str(issues)]

        lines = [
            "# Meeting Briefing Withheld",
            "",
            "OfficePilot could not verify the briefing after the permitted "
            "revision attempts. It has not been forwarded to action proposal "
            "or execution.",
            "",
        ]

        if issues:
            lines.append("## Validation issues")
            lines.extend(f"- {issue}" for issue in issues)
        else:
            lines.append(
                "The quality decision did not reach an acceptable state."
            )

        lines.extend(
            [
                "",
                "No follow-up task was executed by this blocked workflow path.",
            ]
        )

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(
                role="model",
                parts=[types.Part(text="\n".join(lines))],
            ),
        )


quality_blocked_agent = QualityBlockedAgent(
    name="quality_blocked_agent",
    description=(
        "Returns a safe terminal response when deterministic briefing "
        "validation does not pass."
    ),
)
