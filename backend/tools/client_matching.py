"""Deterministic, evidence-based meeting-to-client matching."""

from __future__ import annotations

import re
from typing import Any


def identify_meeting_client(
    meeting: dict[str, Any],
    known_clients: list[str],
) -> dict[str, Any]:
    """Match only exact client names present in tenant-scoped source data."""
    title = str(meeting.get("title") or meeting.get("summary") or "")
    description = str(meeting.get("description") or "")
    participants = meeting.get("participants") or []
    participant_text = " ".join(
        str(item) for item in participants if isinstance(item, str)
    )
    fields = (
        ("calendar_explicit_client", str(meeting.get("client") or ""), 5),
        ("calendar_title", title, 4),
        ("calendar_participant", participant_text, 3),
        ("calendar_description", description, 1),
    )

    scores: dict[str, int] = {}
    evidence: dict[str, list[str]] = {}
    for candidate in sorted(
        {name.strip() for name in known_clients if isinstance(name, str) and name.strip()},
        key=str.casefold,
    ):
        for source, value, weight in fields:
            if re.search(
                rf"(?<!\w){re.escape(candidate)}(?!\w)",
                value,
                flags=re.IGNORECASE,
            ):
                scores[candidate] = scores.get(candidate, 0) + weight
                evidence.setdefault(candidate, []).append(source)

    if not scores:
        return {
            "client": None,
            "confidence": "none",
            "evidence": [],
        }

    highest_score = max(scores.values())
    winners = [
        candidate
        for candidate, score in scores.items()
        if score == highest_score
    ]
    if len(winners) != 1:
        return {
            "client": None,
            "confidence": "ambiguous",
            "evidence": [],
        }

    client = winners[0]
    return {
        "client": client,
        "confidence": "high" if highest_score >= 3 else "medium",
        "evidence": [
            "tenant_scoped_client_index",
            *evidence[client],
        ],
    }
