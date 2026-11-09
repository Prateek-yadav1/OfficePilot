"""Deterministic final response: return the approved briefing verbatim."""

from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types


class DeterministicFinalResponseAgent(BaseAgent):
    """Emit the approved briefing without generating new content."""

    async def _run_async_impl(
        self,
        ctx: InvocationContext,
    ) -> AsyncGenerator[Event, None]:
        briefing = ctx.session.state.get("final_briefing")

        if not isinstance(briefing, str) or not briefing.strip():
            raise ValueError(
                "Cannot return final response: final_briefing is missing "
                "or is not a non-empty string."
            )

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            branch=ctx.branch,
            content=types.Content(
                role="model",
                parts=[types.Part(text=briefing)],
            ),
        )


final_response_agent = DeterministicFinalResponseAgent(
    name="final_response_agent",
    description=(
        "Returns the quality-approved briefing exactly as stored in "
        "workflow state, without adding or inventing content."
    ),
)
