"""Shared retry / rate-limit helpers for ADK agent callbacks."""

import asyncio
import logging

from backend.llm_config import get_llm_provider_settings

logger = logging.getLogger("officepilot.retry")

# Base sleep when provider == groq (seconds).
_BASE_THROTTLE_SECONDS = 20


async def throttle_for_groq(callback_context=None, extra_sleep: int = 0) -> None:
    """Sleep to avoid hitting Groq rate limits.

    *extra_sleep* lets individual agents add additional breathing room on top of
    the shared base.  Call this from ``before_agent_callback``.
    """
    if get_llm_provider_settings("adk").provider != "groq":
        return
    total = _BASE_THROTTLE_SECONDS + extra_sleep
    logger.debug("Throttling %ss before Groq call", total)
    await asyncio.sleep(total)


async def throttle_analyst(callback_context=None) -> None:
    """Extra-long throttle for analyst_agent (runs after heavy parallel research)."""
    await throttle_for_groq(callback_context, extra_sleep=10)


async def throttle_standard(callback_context=None) -> None:
    """Standard throttle for all other Groq-backed agents."""
    await throttle_for_groq(callback_context, extra_sleep=0)
